"""v0.3 acceptance runner.

This script uses real local saves when available and writes a concise Markdown
record under data_cache/benchmarks. It avoids GitHub/network operations.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import analyze
import api_server
import launcher
from vic3_analyzer import data_store, history, md_library
from vic3_analyzer.cache_io import atomic_bytes, atomic_json


def _clock(seconds: float) -> str:
    seconds = int(max(0, seconds))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _row(case: str, ok: bool, seconds: float, note: str) -> dict[str, object]:
    return {"case": case, "ok": ok, "seconds": round(seconds, 3), "note": note}


def _source(manifest: dict[str, object]) -> str:
    source = manifest.get("source", {})
    if not isinstance(source, dict):
        return "未知"
    return f"{source.get('country', '未知国家')} {source.get('date', '未知日期')}"


def build_case(results: list[dict[str, object]], label: str, path: Path, limit: int, full: bool = True) -> dict[str, object] | None:
    started = time.perf_counter()
    try:
        manifest = api_server.build_dataset(path, limit=limit, full_pops=full)
        api_server.outputs_valid(manifest)
        summary = json.loads(api_server.output_path(manifest, "systems_summary").read_text(encoding="utf-8"))
        if analyze.normalize_game_date(summary["meta"]["date"]) != manifest["source"]["game_date"]:
            raise RuntimeError("报告日期与 manifest 日期不一致")
        note = f"{_source(manifest)}；{'缓存' if manifest.get('cached') else '新建'}；{manifest.get('dataset')}"
        results.append(_row(label, True, time.perf_counter() - started, note))
        return manifest
    except Exception as exc:
        results.append(_row(label, False, time.perf_counter() - started, str(exc)))
        return None


def check_http(results: list[dict[str, object]], dataset: str) -> None:
    started = time.perf_counter()
    server = ThreadingHTTPServer(("127.0.0.1", 0), api_server.ApiHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        query = urllib.parse.urlencode({"dataset": dataset, "limit": 2})
        for route in [
            "/api/health",
            "/api/sql/table/major_countries?" + query,
            "/api/jsonl/table/subject_relations?" + query,
        ]:
            with urllib.request.urlopen(base + route, timeout=10) as response:
                body = json.load(response)
                if not body.get("ok"):
                    raise RuntimeError(route + " 返回失败")
        results.append(_row("本地 API 表读取", True, time.perf_counter() - started, dataset))
    except Exception as exc:
        results.append(_row("本地 API 表读取", False, time.perf_counter() - started, str(exc)))
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def write_report(results: list[dict[str, object]], target: Path) -> None:
    passed = sum(1 for row in results if row["ok"])
    failed = len(results) - passed
    lines = [
        "# v0.3 验收检查",
        "",
        f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 通过：{passed}",
        f"- 失败：{failed}",
        "",
        "| 项目 | 结果 | 耗时 | 说明 |",
        "|---|---|---:|---|",
    ]
    for row in results:
        status = "通过" if row["ok"] else "失败"
        lines.append(f"| {row['case']} | {status} | {_clock(float(row['seconds']))} | {row['note']} |")
    atomic_bytes(target, ("\n".join(lines) + "\n").encode("utf-8"))


def main() -> None:
    output_dir = ROOT / "data_cache" / "benchmarks"
    output_dir.mkdir(parents=True, exist_ok=True)
    results_path = output_dir / ("v03_acceptance-" + time.strftime("%Y%m%d-%H%M%S") + ".json")
    report_path = output_dir / ("v03_acceptance-" + time.strftime("%Y%m%d-%H%M%S") + ".md")
    results: list[dict[str, object]] = []
    saves = launcher.list_save_paths()
    if not saves:
        results.append(_row("发现存档", False, 0, "没有找到 Victoria 3 存档"))
        write_report(results, report_path)
        atomic_json(results_path, results)
        print(f"验收报告：{report_path}")
        return

    latest = saves[0]
    latest_manifest = build_case(results, "最新存档完整 MD 数据包", latest, 0, True)
    repeated = build_case(results, "同存档重复读取缓存", latest, 0, True)
    scoped = build_case(results, "同存档换范围复用", latest, 30, True)
    if scoped:
        check_http(results, str(scoped["dataset"]))
    if latest_manifest:
        started = time.perf_counter()
        try:
            report = launcher.run_desktop_md_export(latest, open_folder=False, quiet_summary=True)
            if not report or md_library.validate_report(report):
                raise RuntimeError("桌面 MD 校验失败")
            results.append(_row("桌面单个 MD 导出", True, time.perf_counter() - started, str(report)))
        except Exception as exc:
            results.append(_row("桌面单个 MD 导出", False, time.perf_counter() - started, str(exc)))
    if len(saves) >= 2:
        previous = build_case(results, "历史对照样本建库", saves[1], 30, True)
        if previous and scoped:
            started = time.perf_counter()
            try:
                text = history.compare(previous, scoped)
                if "附属关系" not in text or "地区归属差异" not in text:
                    raise RuntimeError("历史对照缺少关键章节")
                results.append(_row("两点历史对照", True, time.perf_counter() - started, f"{_source(previous)} -> {_source(scoped)}"))
            except Exception as exc:
                results.append(_row("两点历史对照", False, time.perf_counter() - started, str(exc)))
    datasets = api_server.list_datasets()[:5]
    if len(datasets) >= 3:
        started = time.perf_counter()
        try:
            text = history.timeline(datasets[:3])
            if "相邻变化摘要" not in text:
                raise RuntimeError("时间线缺少摘要")
            results.append(_row("多存档时间线", True, time.perf_counter() - started, "已使用最近 3 个数据包"))
        except Exception as exc:
            results.append(_row("多存档时间线", False, time.perf_counter() - started, str(exc)))

    atomic_json(results_path, results)
    write_report(results, report_path)
    print(f"验收报告：{report_path}")
    print(f"机器记录：{results_path}")
    print(f"通过：{sum(1 for row in results if row['ok'])} / {len(results)}")


if __name__ == "__main__":
    main()
