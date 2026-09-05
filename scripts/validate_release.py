"""End-to-end checks for cached views, HTTP reads and desktop Markdown export."""
from __future__ import annotations

import json
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import analyze
import api_server
import launcher
from vic3_analyzer import data_store, history, md_library
from vic3_analyzer.cache_io import atomic_json


def main():
    results = []
    saves = launcher.list_save_paths()
    output = ROOT / 'data_cache' / 'benchmarks' / ('release-validation-' + time.strftime('%Y%m%d-%H%M%S') + '.json')
    def build(label, path, limit, full=True):
        start = time.perf_counter()
        manifest = api_server.build_dataset(path, limit=limit, full_pops=full)
        assert api_server.outputs_valid(manifest)
        summary = json.loads(api_server.output_path(manifest, 'systems_summary').read_text(encoding='utf-8'))
        assert analyze.normalize_game_date(summary['meta']['date']) == manifest['source']['game_date']
        assert manifest['source']['game_date'] in manifest['report']
        result = {'case': label, 'seconds': round(time.perf_counter()-start, 3),
                  'cached': manifest['cached'], 'dataset': manifest['dataset'],
                  'reused_modules': manifest.get('extraction', {}).get('reused_modules', []),
                  'cross_snapshot_modules': manifest.get('extraction', {}).get('cross_snapshot_modules', [])}
        results.append(result)
        atomic_json(output, results)
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return manifest
    latest = saves[0]
    first = build('latest_top5_full', latest, 5)
    build('latest_same_view_cached', latest, 5)
    larger = build('latest_top30_shared_world', latest, 30)
    assert len(larger['extraction']['reused_modules']) >= 18
    small = data_store.read_sqlite_table(Path(first['dataset_dir']) / 'dataset.sqlite', 'major_countries')['rows']
    big = data_store.read_sqlite_table(Path(larger['dataset_dir']) / 'dataset.sqlite', 'major_countries')['rows']
    index = {r['country_id']: r for r in big}
    for row in small:
        for key, value in row.items():
            if key != 'major_gdp_share':
                assert index[row['country_id']][key] == value, (key, row['country_id'])
    previous = build('previous_year_full', saves[2], 30)
    text = history.compare(previous, larger)
    assert '地区归属差异' in text and '附属关系' in text
    build('historical_lite', saves[6], 5, False)
    full = build('historical_add_population', saves[6], 5, True)
    assert len(full['extraction']['reused_modules']) >= 15
    server = ThreadingHTTPServer(('127.0.0.1', 0), api_server.ApiHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f'http://127.0.0.1:{server.server_port}'
        query = urllib.parse.urlencode({'dataset': larger['dataset'], 'limit': 2})
        for route in ['/api/health', '/api/sql/table/major_countries?' + query,
                      '/api/jsonl/table/subject_relations?' + query]:
            with urllib.request.urlopen(base + route, timeout=10) as response:
                assert json.load(response)['ok']
        results.append({'case': 'http_health_sql_jsonl', 'passed': True})
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    start = time.perf_counter()
    report = launcher.run_desktop_md_export(latest, open_folder=False)
    assert report and not md_library.validate_report(report)
    assert report.parent == launcher.DESKTOP_MD_ROOT
    with patch.object(api_server, 'build_dataset', side_effect=AssertionError('MD cache missed')):
        assert launcher.run_desktop_md_export(latest, open_folder=False) == report
    results.append({'case': 'desktop_full_md_and_repeat', 'seconds': round(time.perf_counter()-start,3),
                    'report': str(report), 'passed': True})
    atomic_json(output, results)
    print('Release validation passed', flush=True)


if __name__ == '__main__':
    main()
