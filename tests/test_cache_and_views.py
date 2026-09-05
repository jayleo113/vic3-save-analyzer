from __future__ import annotations

import io
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import analyze
import api_server
from vic3_analyzer import md_library, parser_core, rust_backend, world_data
from vic3_analyzer.cache_io import atomic_json, cache_lock
from vic3_analyzer.fingerprint import full_hash, quick_hash
from vic3_analyzer.progress import ProgressPrinter
from vic3_analyzer.snapshot_store import SnapshotStore

ROOT = Path(__file__).resolve().parents[1]
TEMP = ROOT / 'data_cache' / 'test_runs'
TEMP.mkdir(parents=True, exist_ok=True)


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=TEMP)
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_middle_overwrite_same_size_and_time(self):
        save = self.root / 'same.v3'
        save.write_bytes(b'a' * 3_000_000)
        stat = save.stat()
        old_quick, old_full = quick_hash(save), full_hash(save)
        report = self.root / 'test.md'
        report.write_text('report', encoding='utf-8')
        md_library.remember_report(save, report, self.root)
        with save.open('r+b') as handle:
            handle.seek(1_500_000)
            handle.write(b'b')
        os.utime(save, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.assertEqual(old_quick, quick_hash(save))
        self.assertNotEqual(old_full, full_hash(save))
        self.assertIsNone(md_library.cached_report_for_save(save, self.root, self.root))

    def test_module_reuse_corruption_and_repair(self):
        first = SnapshotStore(self.root, 'year1', 'version1')
        value = [{'population': 20, 'culture': '汉'}]
        first.put('population', value, 'same-inputs')
        first.close()
        second = SnapshotStore(self.root, 'year2', 'version1')
        self.assertEqual(second.get('population', 'same-inputs'), value)
        self.assertIsNone(second.get('changed', 'new-inputs'))
        second.connection.execute("UPDATE objects SET payload=X'00'")
        second.connection.commit()
        self.assertIsNone(second.get('population'))
        second.put('population', value, 'same-inputs')
        self.assertEqual(second.get('population'), value)
        second.close()
        third = SnapshotStore(self.root, 'year2', 'version2')
        self.assertIsNone(third.get('population', 'same-inputs'))
        third.close()

    def test_concurrent_manifest_updates(self):
        target = self.root / 'index.json'
        atomic_json(target, {})
        def add(number):
            with cache_lock(self.root / 'index.lock'):
                value = json.loads(target.read_text())
                value[str(number)] = number
                atomic_json(target, value)
        threads = [threading.Thread(target=add, args=(n,)) for n in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(json.loads(target.read_text())), 12)

    def test_failed_build_preserves_previous_and_rename_reuses(self):
        save = self.root / 'save.v3'
        save.write_text('meta_data={\nname=CHI\ngame_date=1842.1.1\n}\n', encoding='utf-8')
        def export(path, text, **kwargs):
            folder = analyze.REPORT_DIR
            document = folder / '中国_1842-01-01_systems_document.md'
            document.write_text('# test', encoding='utf-8')
            summary = folder / 'summary.json'
            summary.write_text('{}', encoding='utf-8')
            return document, {'systems_document': document, 'systems_summary': summary}
        with patch.object(api_server, 'CACHE_ROOT', self.root / 'cache'), patch.object(analyze, 'build_system_export', side_effect=export):
            first = api_server.build_dataset(save)
            original_report = api_server.output_path(first, 'systems_document').read_bytes()
            with patch.object(analyze, 'build_system_export', side_effect=RuntimeError('injected failure')):
                with self.assertRaisesRegex(RuntimeError, 'injected failure'):
                    api_server.build_dataset(save, force=True)
            self.assertEqual(api_server.output_path(first, 'systems_document').read_bytes(), original_report)
            self.assertEqual(list(api_server.CACHE_ROOT.glob('.building_*')), [])
            renamed = self.root / 'renamed.v3'
            renamed.write_bytes(save.read_bytes())
            reused = api_server.build_dataset(renamed)
            self.assertTrue(reused['cached'])
            self.assertEqual(reused['dataset'], first['dataset'])
            save.write_text(save.read_text().replace('1842', '1843'), encoding='utf-8')
            with patch.object(analyze, 'build_system_export', side_effect=RuntimeError('new content')):
                with self.assertRaisesRegex(RuntimeError, 'new content'):
                    api_server.build_dataset(save)


class ParserTests(unittest.TestCase):
    def test_quoted_and_commented_braces(self):
        text = '{ x="} { \\\"" # } ignored\n y={a=1}\n}'
        self.assertEqual(parser_core.brace_span(text, 0), len(text) - 1)
        with self.assertRaises(ValueError):
            parser_core.brace_span('{', 0)

    def test_iterator_offsets_without_tail_copies(self):
        text = 'prefix\n1={a=2}\n2=none\n3={b={x=1}}\n'
        entries = list(parser_core.iter_top_blocks(text, 7, len(text)))
        self.assertEqual([r[0] for r in entries], ['1', '3'])
        self.assertEqual([text[a:b+1] for _, a, b in entries], ['{a=2}', '{b={x=1}}'])

    def test_chinese_progress_fits_narrow_terminal(self):
        with patch('shutil.get_terminal_size', return_value=os.terminal_size((20, 20))):
            text, padding = ProgressPrinter._fit_line('读取人口 · 20,000/42,000，剩余22,000', 40)
        import unicodedata
        width = sum(2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in text + padding)
        self.assertLessEqual(width, 19)

    def test_rust_scanner_is_optional(self):
        with patch.dict(os.environ, {"VIC3_RUST_SCANNER": str(Path("missing-vic3-scan.exe"))}, clear=False):
            self.assertFalse(rust_backend.status(ROOT)['rust_scanner_available'])
            self.assertIsNone(rust_backend.scan_blocks(ROOT, ROOT / "missing.txt"))


if __name__ == '__main__':
    unittest.main()
