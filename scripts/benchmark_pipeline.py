"""Run reproducible real-save exports with per-stage timings and table digests."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import analyze
import launcher


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--saves', nargs='+', required=True)
    parser.add_argument('--run', required=True)
    parser.add_argument('--limit', type=int, default=5)
    parser.add_argument('--full-pops', action='store_true')
    args = parser.parse_args()
    run_root = ROOT / 'data_cache' / 'benchmarks' / args.run
    run_root.mkdir(parents=True, exist_ok=True)
    stages = {}
    for name in list(vars(analyze)):
        function = getattr(analyze, name)
        if name.startswith('parse_') and callable(function):
            def measured(*a, _fn=function, _name=name, **kw):
                started = time.perf_counter()
                try:
                    return _fn(*a, **kw)
                finally:
                    stages[_name] = stages.get(_name, 0) + time.perf_counter() - started
            setattr(analyze, name, measured)
    saves = launcher.list_save_paths()
    results = []
    for selection in args.saves:
        path = saves[int(selection) - 1] if selection.isdigit() else Path(selection)
        stages.clear()
        folder = run_root / str(len(results) + 1)
        analyze.REPORT_DIR = folder
        started = time.perf_counter()
        text = analyze.read_save(path)
        read_seconds = time.perf_counter() - started
        try:
            report, outputs = analyze.build_system_export(path, text, limit=args.limit, full_pops=args.full_pops)
            elapsed = time.perf_counter() - started
            tables = {}
            for name, output in outputs.items():
                if output.suffix != '.csv':
                    continue
                with output.open(encoding='utf-8-sig', newline='') as handle:
                    rows = list(csv.DictReader(handle))
                encoded = json.dumps(rows, ensure_ascii=False, sort_keys=True).encode('utf-8')
                tables[name] = {'rows': len(rows), 'sha256': hashlib.sha256(encoded).hexdigest()}
            result = {'save': str(path), 'bytes': path.stat().st_size, 'seconds': elapsed,
                      'read_seconds': read_seconds, 'stages': dict(stages), 'tables': tables,
                      'report': str(report), 'full_pops': args.full_pops, 'limit': args.limit}
            result['extraction'] = json.loads(outputs['systems_summary'].read_text(encoding='utf-8')).get('extraction', {})
            results.append(result)
            (run_root / 'results.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
            print(json.dumps({k: v for k, v in result.items() if k not in {'tables', 'report'}}, ensure_ascii=False), flush=True)
        finally:
            analyze.clear_database_block_cache(text)
            del text


if __name__ == '__main__':
    main()
