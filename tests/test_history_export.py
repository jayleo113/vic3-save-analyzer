import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vic3_analyzer import data_store, history


class HistoryTests(unittest.TestCase):
    def test_missing_tables_are_not_reported_as_disappearance(self):
        sample = {'source': {'country': '中国', 'date': '1900-01-01', 'path': '中国.v3'}}
        def rows(manifest, table):
            return [{'tag': 'CHI', 'country_name': '中国', 'gdp': '100'}] if table == 'major_countries' else []
        with patch.object(history, '_available', return_value={'major_countries', 'states'}), patch.object(history, '_rows', side_effect=rows):
            report = history.compare(sample, sample)
        self.assertIn('未提供该表，无法比较', report)
        self.assertIn('政治运动', report)
        self.assertIn('市场成员关系', report)

    def test_multi_snapshot_timeline_reports_observed_changes(self):
        samples = [
            {'source': {'country': '中国', 'date': '1900-01-01', 'path': 'a.v3'}},
            {'source': {'country': '中国', 'date': '1901-01-01', 'path': 'b.v3'}},
            {'source': {'country': '中国', 'date': '1902-01-01', 'path': 'c.v3'}},
        ]
        values = {
            '1900-01-01': [{'tag': 'CHI', 'country_name': '中国', 'gdp': '100', 'population': '10'}],
            '1901-01-01': [{'tag': 'CHI', 'country_name': '中国', 'gdp': '120', 'population': '11'}],
            '1902-01-01': [{'tag': 'CHI', 'country_name': '中国', 'gdp': '150', 'population': '12'}],
        }
        def rows(manifest, table):
            if table == 'major_countries':
                return values[manifest['source']['date']]
            return []
        with patch.object(history, '_available', return_value={'major_countries', 'states'}), patch.object(history, '_rows', side_effect=rows):
            report = history.timeline(samples)
        self.assertIn('战役时间线对照', report)
        self.assertIn('相邻变化摘要', report)
        self.assertIn('GDP 100→120', report)

    def test_streaming_rows_has_no_export_limit_and_releases_file(self):
        import sqlite3
        from contextlib import closing
        root = Path(__file__).resolve().parents[1] / 'data_cache' / 'test_runs'
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as folder:
            path = Path(folder) / '数据.sqlite'
            with closing(sqlite3.connect(path)) as conn, conn:
                conn.execute('CREATE TABLE records (value INTEGER)')
                conn.executemany('INSERT INTO records VALUES (?)', [(n,) for n in range(12001)])
            values = list(data_store.iter_sqlite_rows(path, 'records'))
            self.assertEqual(len(values), 12001)
            self.assertEqual(values[-1]['value'], 12000)
            path.unlink()


if __name__ == '__main__':
    unittest.main()
