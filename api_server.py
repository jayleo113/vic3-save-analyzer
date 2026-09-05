# -*- coding: utf-8 -*-
"""Local HTTP API and disk cache builder for Victoria 3 save exports."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import time
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import analyze
import launcher
from vic3_analyzer import data_store, external_tools
from vic3_analyzer.cache_io import atomic_json, cache_lock
from vic3_analyzer.fingerprint import full_hash
from vic3_analyzer.snapshot_store import code_version


CACHE_ROOT = analyze.TOOL_DIR / "data_cache"
CONTENT_INDEX_NAME = "content_index.json"
API_TOKEN = ""
DATASET_SCHEMA_VERSION = "api_dataset_v5_verified_world"

SYSTEM_DATASETS = {
    "major_countries": "国家总表、GDP、人口、历史变化",
    "states": "州、基建、破坏度",
    "building_summary": "建筑汇总",
    "building_details": "建筑明细",
    "companies": "公司与生产率历史",
    "markets": "市场总表",
    "market_members": "市场成员国",
    "market_states": "州级市场与贸易容量",
    "market_trade_goods": "州级交易商品",
    "population_summary": "人口总览",
    "population_by_type": "职业结构",
    "population_by_culture": "文化结构",
    "population_by_religion": "宗教结构",
    "laws": "法律制度",
    "interest_groups": "利益集团",
    "political_movements": "政治运动",
    "technology": "科技",
    "relations": "外交关系",
    "pacts": "外交行动",
    "subject_relations": "宗主国、附属国与傀儡关系",
    "treaties": "正式条约",
    "treaty_articles": "条约条款",
    "wars": "战争与历史战争",
    "war_participants": "参战方与战争支持度",
    "diplomatic_plays": "外交博弈",
    "war_costs": "战争成本",
    "war_goals": "战争目标",
    "military_formations": "军队编成",
    "battles": "战斗记录",
    "battle_casualties": "战斗伤亡",
}

DOCUMENTS = {
    "systems_document": "体系化国家文档",
    "systems_report": "表格索引",
    "systems_summary": "机器索引 JSON",
}

LLM_CORE_TABLES = [
    "major_countries",
    "states",
    "markets",
    "market_members",
    "building_summary",
    "companies",
    "population_summary",
    "population_by_type",
    "population_by_culture",
    "population_by_religion",
    "laws",
    "interest_groups",
    "political_movements",
    "relations",
    "pacts",
    "treaties",
    "wars",
    "war_participants",
    "diplomatic_plays",
    "war_goals",
    "battles",
    "battle_casualties",
]


def query_value(query: dict[str, list[str]], key: str, default: str = "") -> str:
    values = query.get(key)
    return values[0] if values else default


def bool_query(value: str, default: bool = True) -> bool:
    if value == "":
        return default
    return value.lower() not in {"0", "false", "no", "off"}


def set_api_token(token: str | None) -> None:
    global API_TOKEN
    API_TOKEN = (token or "").strip()


def save_from_text(raw: str = "latest") -> Path | None:
    saves = launcher.list_save_paths()
    raw = (raw or "latest").strip()
    if raw == "latest":
        return saves[0] if saves else None
    if raw.isdigit():
        index = int(raw)
        return saves[index - 1] if 1 <= index <= len(saves) else None
    path = Path(unquote(raw)).expanduser()
    return path if path.is_file() else None


def save_from_query(query: dict[str, list[str]]) -> Path | None:
    return save_from_text(query_value(query, "save", "latest"))


def dataset_id_for_save(path: Path, mode: str, limit: int, full_pops: bool) -> str:
    preview = launcher.save_preview(path)
    return dataset_id_from_identity(preview.get("country"), preview.get("date"), mode, limit, full_pops)


def dataset_id_from_identity(country_raw: object, date_raw: object, mode: str, limit: int, full_pops: bool) -> str:
    country = analyze.safe_filename_part(country_raw, "UNKNOWN")
    date = analyze.safe_filename_part(date_raw, "DATE_UNKNOWN")
    detail = f"{mode}_top{limit}_{'full' if full_pops else 'lite'}"
    return analyze.safe_filename_part(f"{country}_{date}_{detail}")


def identity_from_report(report: Path) -> tuple[str, str] | None:
    stem = report.name
    for suffix in ("_systems_document.md", "_report.md"):
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    match = re.match(r"(.+)_(\d{4}-\d{2}-\d{2})$", stem)
    if not match:
        return None
    return match.group(1), match.group(2)


def enrich_manifest_identity(manifest: dict[str, object]) -> bool:
    source = manifest.get("source", {})
    outputs = manifest.get("outputs", {})
    if not isinstance(source, dict) or not isinstance(outputs, dict):
        return False
    if source.get("game_country") and source.get("game_date"):
        return False
    dataset_dir = Path(str(manifest.get("dataset_dir", "")))
    report_name = outputs.get("systems_document") or manifest.get("report")
    if not report_name:
        return False
    identity = identity_from_report(dataset_dir / str(report_name))
    if not identity:
        return False
    source.setdefault("file_country", source.get("country"))
    source.setdefault("file_date", source.get("date"))
    source["game_country"], source["game_date"] = identity
    source["country"], source["date"] = identity
    return True


def manifest_path(dataset_dir: Path) -> Path:
    return dataset_dir / "manifest.json"


def load_manifest(dataset_dir: Path) -> dict[str, object] | None:
    path = manifest_path(dataset_dir)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def content_index_path() -> Path:
    return CACHE_ROOT / CONTENT_INDEX_NAME


def load_content_index() -> dict[str, object]:
    path = content_index_path()
    if not path.exists():
        return {"schema": "content_index_v1", "saves": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"schema": "content_index_v1", "saves": {}}
    if not isinstance(data.get("saves"), dict):
        data["saves"] = {}
    return data


def save_content_index(index: dict[str, object]) -> None:
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    path = content_index_path()
    atomic_json(path, index)


def view_key(mode: str, limit: int, full_pops: bool) -> str:
    return f"{mode}_top{limit}_{'full' if full_pops else 'lite'}"


def register_content_view(manifest: dict[str, object]) -> None:
    with cache_lock(CACHE_ROOT / 'content_index.lock'):
        _register_content_view(manifest)


def _register_content_view(manifest: dict[str, object]) -> None:
    source = manifest.get("source", {})
    options = manifest.get("options", {})
    if not isinstance(source, dict) or not isinstance(options, dict):
        return
    quick_hash = str(source.get("quick_hash") or "")
    if not quick_hash:
        return
    key = view_key(str(options.get("mode") or "systems"), int(options.get("limit") or 0), bool(options.get("full_pops")))
    index = load_content_index()
    saves = index.setdefault("saves", {})
    if not isinstance(saves, dict):
        return
    entry = saves.setdefault(quick_hash, {"views": {}, "sources": []})
    if not isinstance(entry, dict):
        return
    views = entry.setdefault("views", {})
    sources = entry.setdefault("sources", [])
    if isinstance(views, dict):
        views[key] = manifest.get("dataset")
    if isinstance(sources, list) and source.get("path") not in sources:
        sources.append(source.get("path"))
    entry["country"] = source.get("game_country") or source.get("country")
    entry["date"] = source.get("game_date") or source.get("date")
    entry["updated_at"] = datetime.now().isoformat(timespec="seconds")
    save_content_index(index)


def rebuild_content_index() -> dict[str, object]:
    with cache_lock(CACHE_ROOT / 'content_index.lock'):
        return _rebuild_content_index()


def _rebuild_content_index() -> dict[str, object]:
    index = {"schema": "content_index_v1", "saves": {}}
    saves = index["saves"]
    if not CACHE_ROOT.exists():
        save_content_index(index)
        return index
    for dataset_dir in CACHE_ROOT.iterdir():
        if not dataset_dir.is_dir() or dataset_dir.name.startswith('.'):
            continue
        manifest = load_manifest(dataset_dir)
        if not manifest:
            continue
        manifest["dataset"] = dataset_dir.name
        manifest["dataset_dir"] = str(dataset_dir)
        enrich_manifest_identity(manifest)
        source = manifest.get("source", {})
        options = manifest.get("options", {})
        if not isinstance(source, dict) or not isinstance(options, dict):
            continue
        quick_hash = str(source.get("quick_hash") or "")
        if not quick_hash:
            continue
        key = view_key(str(options.get("mode") or "systems"), int(options.get("limit") or 0), bool(options.get("full_pops")))
        entry = saves.setdefault(quick_hash, {"views": {}, "sources": []})
        entry["views"][key] = dataset_dir.name
        path = source.get("path")
        if path and path not in entry["sources"]:
            entry["sources"].append(path)
        entry["country"] = source.get("game_country") or source.get("country")
        entry["date"] = source.get("game_date") or source.get("date")
        entry["updated_at"] = source.get("generated_at") or manifest.get("generated_at", "")
    save_content_index(index)
    return index


def find_dataset_by_content(path: Path, mode: str, limit: int, full_pops: bool, content_hash: str | None = None) -> dict[str, object] | None:
    content_hash = content_hash or full_hash(path)
    preview = launcher.save_preview(path)
    quick_hash = str(preview.get("quick_hash") or "")
    if not quick_hash:
        return None
    key = view_key(mode, limit, full_pops)
    index = load_content_index()
    saves = index.get("saves", {})
    entry = saves.get(quick_hash) if isinstance(saves, dict) else None
    views = entry.get("views", {}) if isinstance(entry, dict) else {}
    dataset = views.get(key) if isinstance(views, dict) else None
    if dataset:
        manifest = dataset_from_text(str(dataset))
        if manifest and manifest.get("schema_version") == DATASET_SCHEMA_VERSION and manifest.get('source', {}).get('sha256') == content_hash and outputs_valid(manifest):
            manifest["content_cached"] = True
            return manifest
    for manifest in list_datasets():
        source = manifest.get("source", {})
        options = manifest.get("options", {})
        if not isinstance(source, dict) or not isinstance(options, dict):
            continue
        if (
            source.get("quick_hash") == quick_hash
            and options.get("mode") == mode
            and options.get("limit") == limit
            and options.get("full_pops") == full_pops
            and manifest.get("schema_version") == DATASET_SCHEMA_VERSION
            and source.get('sha256') == content_hash
            and outputs_valid(manifest)
        ):
            register_content_view(manifest)
            manifest["content_cached"] = True
            return manifest
    return None


def dataset_sort_key(item: dict[str, object]) -> tuple[str, str]:
    source = item.get("source", {})
    game_date = ""
    if isinstance(source, dict):
        game_date = str(source.get("game_date") or source.get("date") or "")
    return (game_date, str(item.get("generated_at", "")))


def list_datasets() -> list[dict[str, object]]:
    if not CACHE_ROOT.exists():
        return []
    rows = []
    for dataset_dir in CACHE_ROOT.iterdir():
        if not dataset_dir.is_dir() or dataset_dir.name.startswith('.'):
            continue
        manifest = load_manifest(dataset_dir)
        if not manifest:
            continue
        manifest["dataset"] = dataset_dir.name
        manifest["dataset_dir"] = str(dataset_dir)
        enrich_manifest_identity(manifest)
        rows.append(manifest)
    return sorted(rows, key=dataset_sort_key, reverse=True)


def dataset_from_text(raw: str = "latest") -> dict[str, object] | None:
    raw = (raw or "latest").strip()
    datasets = list_datasets()
    if raw == "latest":
        return datasets[0] if datasets else None
    for item in datasets:
        if item.get("dataset") == raw:
            return item
    return None


def outputs_valid(manifest):
    if manifest.get('parser_version') != code_version(analyze.TOOL_DIR):
        return False
    root = Path(str(manifest.get('dataset_dir', '')))
    hashes = manifest.get('output_hashes', {})
    if not hashes:
        return False
    try:
        return all((root / name).is_file() and full_hash(root / name) == digest for name, digest in hashes.items())
    except OSError:
        return False


def manifest_matches(manifest: dict[str, object], path: Path, mode: str, limit: int, full_pops: bool, content_hash: str | None = None) -> bool:
    stat = path.stat()
    source = manifest.get("source", {})
    options = manifest.get("options", {})
    preview = launcher.save_preview(path)
    return (
        isinstance(source, dict)
        and isinstance(options, dict)
        and source.get("path") == str(path.resolve())
        and source.get("mtime") == stat.st_mtime
        and source.get("size") == stat.st_size
        and source.get("quick_hash") == preview.get("quick_hash")
        and options.get("mode") == mode
        and options.get("limit") == limit
        and options.get("full_pops") == full_pops
        and manifest.get("schema_version") == DATASET_SCHEMA_VERSION
        and source.get('sha256') == (content_hash or full_hash(path))
        and outputs_valid(manifest)
    )


def clean_dataset_dir(dataset_dir: Path) -> None:
    root = CACHE_ROOT.resolve()
    target = dataset_dir.resolve()
    if root not in target.parents:
        raise RuntimeError("缓存目录不在项目 data_cache 内，已拒绝清理")
    if dataset_dir.exists():
        shutil.rmtree(dataset_dir)
    dataset_dir.mkdir(parents=True, exist_ok=True)


def build_dataset(
    path: Path,
    mode: str = "systems",
    limit: int = 30,
    full_pops: bool = True,
    force: bool = False,
    progress=None,
) -> dict[str, object]:
    with cache_lock(CACHE_ROOT / 'build.lock'):
        old_temporary = set(CACHE_ROOT.glob('.building_*'))
        try:
            return _build_dataset(path, mode, limit, full_pops, force, progress)
        finally:
            for temporary in set(CACHE_ROOT.glob('.building_*')) - old_temporary:
                if temporary.is_dir() and CACHE_ROOT.resolve() in temporary.resolve().parents:
                    shutil.rmtree(temporary)


def _build_dataset(path, mode, limit, full_pops, force, progress):
    started = time.perf_counter()
    content_hash = full_hash(path)
    mode = "quick" if mode == "quick" else "systems"
    dataset_id = dataset_id_for_save(path, mode, limit, full_pops) + '_' + content_hash[:12]
    dataset_dir = CACHE_ROOT / dataset_id
    existing = load_manifest(dataset_dir)
    if existing and not force and manifest_matches(existing, path, mode, limit, full_pops, content_hash):
        changed = enrich_manifest_identity(existing)
        sqlite_name = str(existing.get("sqlite") or data_store.SQLITE_NAME)
        sqlite_path = dataset_dir / sqlite_name
        if not sqlite_path.exists() or existing.get("sqlite_schema_version") != data_store.SQLITE_SCHEMA_VERSION:
            sqlite_path = data_store.write_dataset_sqlite(dataset_dir, existing, SYSTEM_DATASETS)
            existing["sqlite"] = sqlite_path.name
            existing["sqlite_schema_version"] = data_store.SQLITE_SCHEMA_VERSION
            changed = True
        if changed:
            manifest_path(dataset_dir).write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
        existing["ok"] = True
        existing["cached"] = True
        register_content_view(existing)
        return existing
    if not force:
        content_match = find_dataset_by_content(path, mode, limit, full_pops, content_hash)
        if content_match:
            content_match["ok"] = True
            content_match["cached"] = True
            return content_match

    final_dir = dataset_dir
    dataset_dir = CACHE_ROOT / ('.building_' + uuid.uuid4().hex)
    dataset_dir.mkdir(parents=True)
    previous_report_dir = analyze.REPORT_DIR
    analyze.REPORT_DIR = dataset_dir
    txt = None
    try:
        if progress:
            progress(1, f"读取存档：{path.name}")
        txt = analyze.read_save(path)
        if progress:
            progress(18, "存档读取完成")
        if mode == "quick":
            if progress:
                progress(25, "生成快速报告")
            report, outputs = analyze.build_report(path, txt, full_pops=full_pops)
        else:
            report, outputs = analyze.build_system_export(
                path,
                txt,
                limit=limit,
                full_pops=full_pops,
                progress=(lambda p, label: progress(18 + int(p * 0.78), label)) if progress else None,
            )
        if progress:
            progress(97, "写入数据仓库")
    finally:
        analyze.REPORT_DIR = previous_report_dir
        if txt is not None:
            analyze.clear_database_block_cache(txt)

    stat = path.stat()
    preview = launcher.save_preview(path)
    report_identity = identity_from_report(Path(report))
    game_country = report_identity[0] if report_identity else preview.get("country")
    game_date = report_identity[1] if report_identity else preview.get("date")
    dataset_id = dataset_id_from_identity(game_country, game_date, mode, limit, full_pops) + '_' + content_hash[:12]
    final_dir = CACHE_ROOT / dataset_id
    report_path = Path(report)
    report_text = report_path.read_text(encoding='utf-8')
    heading, separator, body = report_text.partition('\n')
    provenance = f"\n\n- 数据来源：{path.name}\n- 存档内部身份：{game_country}，{game_date}\n- 源文件 SHA-256：`{content_hash}`\n"
    report_path.write_text(heading + provenance + separator + body, encoding='utf-8')
    manifest = {
        "ok": True,
        "cached": False,
        "dataset": dataset_id,
        "dataset_dir": str(final_dir),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "schema_version": DATASET_SCHEMA_VERSION,
        "parser_version": code_version(analyze.TOOL_DIR),
        "seconds": round(time.perf_counter() - started, 2),
        "source": {
            "path": str(path.resolve()),
            "mtime": stat.st_mtime,
            "size": stat.st_size,
            "country": game_country,
            "date": game_date,
            "game_country": game_country,
            "game_date": game_date,
            "file_country": preview.get("country"),
            "file_date": preview.get("date"),
            "version": preview.get("version"),
            "quick_hash": preview.get("quick_hash"),
            "sha256": content_hash,
        },
        "options": {"mode": mode, "limit": limit, "full_pops": full_pops},
        "report": Path(report).name,
        "outputs": {name: Path(output).name for name, output in outputs.items()},
        "tables": SYSTEM_DATASETS,
        "documents": DOCUMENTS,
        "accelerators": external_tools.status(analyze.TOOL_DIR),
    }
    summary_name = manifest['outputs'].get('systems_summary')
    if summary_name:
        summary = json.loads((dataset_dir / summary_name).read_text(encoding='utf-8'))
        summary['outputs'] = {key: str(final_dir / value) for key, value in manifest['outputs'].items()}
        summary['source_sha256'] = content_hash
        atomic_json(dataset_dir / summary_name, summary)
    manifest['jsonl_outputs'] = {}
    manifest['jsonl_storage'] = 'sqlite_on_demand'
    sqlite_path = data_store.write_dataset_sqlite(dataset_dir, manifest, SYSTEM_DATASETS)
    manifest["sqlite"] = sqlite_path.name
    manifest["sqlite_schema_version"] = data_store.SQLITE_SCHEMA_VERSION
    if full_hash(path) != content_hash:
        raise RuntimeError('导出期间存档已变化，请保存完成后重试')
    manifest['seconds'] = round(time.perf_counter() - started, 2)
    manifest['output_hashes'] = {str(p.relative_to(dataset_dir)): full_hash(p)
                               for p in dataset_dir.rglob('*') if p.is_file()}
    summary_name = manifest['outputs'].get('systems_summary')
    if summary_name:
        manifest['extraction'] = json.loads((dataset_dir / summary_name).read_text(encoding='utf-8')).get('extraction', {})
    atomic_json(manifest_path(dataset_dir), manifest)
    backup = CACHE_ROOT / ('.previous_' + uuid.uuid4().hex)
    if final_dir.exists():
        final_dir.rename(backup)
    try:
        dataset_dir.rename(final_dir)
    except BaseException:
        if backup.exists():
            backup.rename(final_dir)
        raise
    if backup.exists() and CACHE_ROOT.resolve() in backup.resolve().parents:
        shutil.rmtree(backup)
    register_content_view(manifest)
    if progress:
        progress(100, "完成")
    return manifest


def output_path(manifest: dict[str, object], name: str) -> Path:
    outputs = manifest.get("outputs", {})
    if not isinstance(outputs, dict) or name not in outputs:
        raise RuntimeError(f"数据包缺少输出：{name}")
    return Path(str(manifest["dataset_dir"])) / str(outputs[name])


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def package_payload(manifest: dict[str, object], names: list[str], include_docs: bool) -> dict[str, object]:
    tables = {}
    for name in names:
        if name not in SYSTEM_DATASETS:
            continue
        csv_path = output_path(manifest, name)
        rows = read_csv_rows(csv_path)
        tables[name] = {
            "description": SYSTEM_DATASETS[name],
            "count": len(rows),
            "rows": rows,
        }
    documents = {}
    if include_docs:
        for name, description in DOCUMENTS.items():
            doc_path = output_path(manifest, name)
            documents[name] = {
                "description": description,
                "content": doc_path.read_text(encoding="utf-8", errors="replace"),
            }
    return {
        "ok": True,
        "dataset": manifest.get("dataset"),
        "source": manifest.get("source"),
        "options": manifest.get("options"),
        "tables": tables,
        "documents": documents,
    }


class ApiHandler(BaseHTTPRequestHandler):
    server_version = "vic3-save-analyzer-api/0.3"

    def log_message(self, fmt: str, *args: object) -> None:
        return

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        super().end_headers()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.end_headers()

    def json_response(self, payload: dict[str, object], status: int = 200) -> None:
        data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def text_response(self, text: str, content_type: str = "text/plain; charset=utf-8", status: int = 200) -> None:
        data = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        try:
            self.route()
        except Exception as exc:
            self.json_response({"ok": False, "error": str(exc)}, status=500)

    def do_POST(self) -> None:
        self.do_GET()

    def route(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        path = parsed.path.rstrip("/") or "/"

        if path == "/":
            self.json_response(
                {
                    "ok": True,
                    "name": "Victoria 3 Save Analyzer API",
                    "version": launcher.APP_VERSION,
                    "storage": str(CACHE_ROOT),
                    "auth": "required" if API_TOKEN else "none",
                    "endpoints": [
                        "/api/health",
                        "/api/saves",
                        "/api/datasets",
                        "/api/build?save=latest&limit=30&full_pops=1",
                        "/api/tables",
                        "/api/sql/tables?dataset=latest",
                        "/api/package?dataset=latest",
                        "/api/table/major_countries?dataset=latest",
                        "/api/sql/table/major_countries?dataset=latest&limit=100",
                        "/api/jsonl/table/major_countries?dataset=latest&limit=100",
                        "/api/sql/query?dataset=latest&q=select * from major_countries limit 5",
                        "/api/document/systems_document?dataset=latest",
                    ],
                }
            )
            return

        if path == "/api/health":
            self.json_response({
                "ok": True,
                "version": launcher.APP_VERSION,
                "storage": str(CACHE_ROOT),
                "auth": "required" if API_TOKEN else "none",
                "accelerators": external_tools.status(analyze.TOOL_DIR),
            })
            return

        if path.startswith("/llm/"):
            self.route_llm(path, query)
            return

        if not self.authorized(query):
            self.json_response({"ok": False, "error": "需要 API token"}, status=401)
            return

        if path == "/api/saves":
            saves = launcher.list_save_paths()
            items = []
            for index, save in enumerate(saves, 1):
                item = dict(launcher.save_preview(save))
                item["index"] = index
                item["path"] = str(save)
                items.append(item)
            self.json_response({"ok": True, "count": len(items), "saves": items})
            return

        if path == "/api/datasets":
            datasets = list_datasets()
            self.json_response({"ok": True, "count": len(datasets), "storage": str(CACHE_ROOT), "datasets": datasets})
            return

        if path == "/api/tables":
            self.json_response({"ok": True, "tables": SYSTEM_DATASETS, "documents": DOCUMENTS})
            return

        if path == "/api/sql/tables":
            manifest = dataset_from_text(query_value(query, "dataset", "latest"))
            if not manifest:
                self.json_response({"ok": False, "error": "还没有数据包，请先调用 /api/build 或在终端运行 build"}, status=404)
                return
            sqlite_name = str(manifest.get("sqlite") or data_store.SQLITE_NAME)
            sqlite_path = Path(str(manifest["dataset_dir"])) / sqlite_name
            self.json_response({"ok": True, "dataset": manifest["dataset"], "sqlite": str(sqlite_path), "tables": data_store.list_sqlite_tables(sqlite_path)})
            return

        if path == "/api/sql/query":
            manifest = dataset_from_text(query_value(query, "dataset", "latest"))
            if not manifest:
                self.json_response({"ok": False, "error": "还没有数据包，请先调用 /api/build 或在终端运行 build"}, status=404)
                return
            sql = query_value(query, "q") or query_value(query, "sql")
            if not sql:
                self.json_response({"ok": False, "error": "缺少 q 参数，例如 q=select * from major_countries limit 5"}, status=400)
                return
            sqlite_name = str(manifest.get("sqlite") or data_store.SQLITE_NAME)
            sqlite_path = Path(str(manifest["dataset_dir"])) / sqlite_name
            limit = int(query_value(query, "limit", "500"))
            payload = data_store.query_sqlite_select(sqlite_path, sql, limit=limit)
            payload.update({"ok": True, "dataset": manifest["dataset"], "sqlite": str(sqlite_path)})
            self.json_response(payload)
            return

        if path == "/api/package":
            manifest = dataset_from_text(query_value(query, "dataset", "latest"))
            if not manifest:
                self.json_response({"ok": False, "error": "还没有数据包，请先调用 /api/build 或在终端运行 build"}, status=404)
                return
            raw_tables = query_value(query, "tables", "all").strip()
            if raw_tables and raw_tables != "all":
                names = [name.strip() for name in raw_tables.split(",") if name.strip()]
            else:
                names = list(SYSTEM_DATASETS)
            include_docs = bool_query(query_value(query, "documents", "1"), default=True)
            self.json_response(package_payload(manifest, names, include_docs))
            return

        if path in {"/api/build", "/api/export"}:
            save_path = save_from_query(query)
            if not save_path:
                self.json_response({"ok": False, "error": "未找到存档"}, status=404)
                return
            mode = query_value(query, "mode", "systems")
            limit = max(1, int(query_value(query, "limit", "30")))
            full_pops = bool_query(query_value(query, "full_pops", "1"), default=True)
            force = bool_query(query_value(query, "force", "0"), default=False)
            self.json_response(build_dataset(save_path, mode, limit, full_pops, force))
            return

        if path.startswith("/api/table/") or path == "/api/table":
            table = path.removeprefix("/api/table/") if path.startswith("/api/table/") else query_value(query, "name")
            table = table.strip()
            if table not in SYSTEM_DATASETS:
                self.json_response({"ok": False, "error": f"未知表：{table}", "available": list(SYSTEM_DATASETS)}, status=404)
                return
            manifest = dataset_from_text(query_value(query, "dataset", "latest"))
            if not manifest:
                self.json_response({"ok": False, "error": "还没有数据包，请先调用 /api/build 或在终端运行 build"}, status=404)
                return
            csv_path = output_path(manifest, table)
            rows = read_csv_rows(csv_path)
            self.json_response({"ok": True, "dataset": manifest["dataset"], "table": table, "count": len(rows), "rows": rows, "source": str(csv_path)})
            return

        if path.startswith("/api/sql/table/") or path == "/api/sql/table":
            table = path.removeprefix("/api/sql/table/") if path.startswith("/api/sql/table/") else query_value(query, "name")
            table = table.strip()
            if table not in SYSTEM_DATASETS:
                self.json_response({"ok": False, "error": f"未知表：{table}", "available": list(SYSTEM_DATASETS)}, status=404)
                return
            manifest = dataset_from_text(query_value(query, "dataset", "latest"))
            if not manifest:
                self.json_response({"ok": False, "error": "还没有数据包，请先调用 /api/build 或在终端运行 build"}, status=404)
                return
            sqlite_name = str(manifest.get("sqlite") or data_store.SQLITE_NAME)
            sqlite_path = Path(str(manifest["dataset_dir"])) / sqlite_name
            limit = int(query_value(query, "limit", "500"))
            offset = int(query_value(query, "offset", "0"))
            payload = data_store.read_sqlite_table(sqlite_path, table, limit=limit, offset=offset)
            payload.update({"ok": True, "dataset": manifest["dataset"], "sqlite": str(sqlite_path)})
            self.json_response(payload)
            return

        if path.startswith("/api/jsonl/table/") or path == "/api/jsonl/table":
            table = path.removeprefix("/api/jsonl/table/") if path.startswith("/api/jsonl/table/") else query_value(query, "name")
            table = table.strip()
            if table not in SYSTEM_DATASETS:
                self.json_response({"ok": False, "error": f"未知表：{table}", "available": list(SYSTEM_DATASETS)}, status=404)
                return
            manifest = dataset_from_text(query_value(query, "dataset", "latest"))
            if not manifest:
                self.json_response({"ok": False, "error": "还没有数据包，请先调用 /api/build 或在终端运行 build"}, status=404)
                return
            sqlite_path = Path(str(manifest['dataset_dir'])) / str(manifest.get('sqlite') or data_store.SQLITE_NAME)
            limit = int(query_value(query, "limit", "500"))
            offset = int(query_value(query, "offset", "0"))
            payload = data_store.read_sqlite_table(sqlite_path, table, limit=limit, offset=offset)
            payload.update({"ok": True, "dataset": manifest["dataset"], "table": table, "source": str(sqlite_path)})
            self.json_response(payload)
            return

        if path.startswith("/api/document/"):
            name = path.removeprefix("/api/document/").strip()
            if name not in DOCUMENTS:
                self.json_response({"ok": False, "error": f"未知文档：{name}", "available": list(DOCUMENTS)}, status=404)
                return
            manifest = dataset_from_text(query_value(query, "dataset", "latest"))
            if not manifest:
                self.json_response({"ok": False, "error": "还没有数据包，请先调用 /api/build 或在终端运行 build"}, status=404)
                return
            doc_path = output_path(manifest, name)
            if name == "systems_summary":
                self.text_response(doc_path.read_text(encoding="utf-8"), "application/json; charset=utf-8")
            else:
                self.text_response(doc_path.read_text(encoding="utf-8"), "text/markdown; charset=utf-8")
            return

        self.json_response({"ok": False, "error": "未知接口"}, status=404)

    def authorized(self, query: dict[str, list[str]]) -> bool:
        if not API_TOKEN:
            return True
        token = query_value(query, "token")
        if token == API_TOKEN:
            return True
        header = self.headers.get("Authorization", "")
        return header == f"Bearer {API_TOKEN}"

    def token_authorized(self, token: str) -> bool:
        return not API_TOKEN or token == API_TOKEN

    def public_base_url(self) -> str:
        scheme = self.headers.get("X-Forwarded-Proto") or "http"
        host = self.headers.get("Host") or "127.0.0.1"
        return f"{scheme}://{host}"

    def route_llm(self, path: str, query: dict[str, list[str]]) -> None:
        parts = [part for part in path.split("/") if part]
        if len(parts) < 2 or not self.token_authorized(parts[1]):
            self.json_response({"ok": False, "error": "需要有效 token"}, status=401)
            return
        token = parts[1]
        action = parts[2] if len(parts) >= 3 else ""
        manifest = dataset_from_text(query_value(query, "dataset", "latest"))
        if not manifest:
            self.json_response({"ok": False, "error": "还没有数据包"}, status=404)
            return

        if action == "package":
            raw_tables = query_value(query, "tables", "").strip()
            names = [name.strip() for name in raw_tables.split(",") if name.strip()] if raw_tables else LLM_CORE_TABLES
            include_docs = bool_query(query_value(query, "documents", "0"), default=False)
            self.json_response(package_payload(manifest, names, include_docs))
            return

        if action == "table" and len(parts) >= 4:
            name = parts[3].strip()
            if name not in SYSTEM_DATASETS:
                self.json_response({"ok": False, "error": f"未知表：{name}", "available": list(SYSTEM_DATASETS)}, status=404)
                return
            csv_path = output_path(manifest, name)
            rows = read_csv_rows(csv_path)
            self.json_response({"ok": True, "dataset": manifest["dataset"], "table": name, "count": len(rows), "rows": rows})
            return

        if action == "document" and len(parts) >= 4:
            name = parts[3].strip()
            if name not in DOCUMENTS:
                self.json_response({"ok": False, "error": f"未知文档：{name}", "available": list(DOCUMENTS)}, status=404)
                return
            doc_path = output_path(manifest, name)
            if name == "systems_summary":
                self.text_response(doc_path.read_text(encoding="utf-8"), "application/json; charset=utf-8")
            else:
                self.text_response(doc_path.read_text(encoding="utf-8"), "text/markdown; charset=utf-8")
            return

        base = self.public_base_url()
        datasets = list_datasets()
        lines = [
            "# Victoria 3 Save Analyzer LLM Gateway",
            "",
            f"当前默认数据包：`{manifest.get('dataset')}`",
            "",
            "## 一个地址读取核心数据",
            "",
            f"{base}/llm/{token}/package",
            "",
            "## 本地 API 的 SQLite 只读查询",
            "",
            "公网 LLM 网关默认不暴露自由 SQL；本地 API 可使用 `/api/sql/query?q=select * from major_countries limit 5`。",
            "",
            "## 常用单表地址",
            "",
        ]
        for name in LLM_CORE_TABLES:
            lines.append(f"- {SYSTEM_DATASETS[name]}: {base}/llm/{token}/table/{name}")
        lines.extend(["", "## 文档地址", ""])
        for name, description in DOCUMENTS.items():
            lines.append(f"- {description}: {base}/llm/{token}/document/{name}")
        lines.extend(["", "## 可用数据包", ""])
        for item in datasets:
            source = item.get("source", {})
            country = source.get("country", "") if isinstance(source, dict) else ""
            date = source.get("date", "") if isinstance(source, dict) else ""
            lines.append(f"- `{item.get('dataset')}`  {country}  {date}")
        self.text_response("\n".join(lines), "text/markdown; charset=utf-8")


def serve(host: str = "127.0.0.1", port: int = 8765, token: str = "") -> None:
    set_api_token(token)
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((host, port), ApiHandler)
    print(f"本地数据 API：http://{host}:{port}")
    print(f"数据仓库：{CACHE_ROOT}")
    print(f"访问密钥：{'已启用' if API_TOKEN else '未启用'}")
    print("按 Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        server.server_close()


def print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def print_build_summary(manifest: dict[str, object]) -> None:
    if not manifest.get("ok"):
        print(f"失败：{manifest.get('error')}")
        return
    print("完成")
    print(f"来源：{'已有缓存' if manifest.get('cached') else '新建数据'}")
    print(f"数据包：{manifest.get('dataset')}")
    print(f"位置：{manifest.get('dataset_dir')}")
    if manifest.get("cached"):
        print("耗时：直接读取缓存")
    else:
        print(f"耗时：{manifest.get('seconds', 0)} 秒")
    outputs = manifest.get("outputs", {})
    jsonl_outputs = manifest.get("jsonl_outputs", {})
    print(f"文件：{len(outputs) if isinstance(outputs, dict) else 0} 个")
    print('数据读取：SQLite；JSON接口按需读取')
    print("本地 API：python api_server.py serve")
    print("读取数据：http://127.0.0.1:8765/api/package?dataset=latest")
    print("查国家表：http://127.0.0.1:8765/api/sql/table/major_countries?dataset=latest&limit=20")
    print("读JSONL：http://127.0.0.1:8765/api/jsonl/table/major_countries?dataset=latest&limit=20")


def print_dataset_list() -> None:
    datasets = list_datasets()
    print(f"数据仓库：{CACHE_ROOT}")
    if not datasets:
        print("还没有数据包。")
        return
    for index, item in enumerate(datasets, 1):
        source = item.get("source", {})
        options = item.get("options", {})
        country = source.get("game_country") or source.get("country", "") if isinstance(source, dict) else ""
        date = source.get("game_date") or source.get("date", "") if isinstance(source, dict) else ""
        file_country = source.get("file_country", "") if isinstance(source, dict) else ""
        file_date = source.get("file_date", "") if isinstance(source, dict) else ""
        mode = options.get("mode", "") if isinstance(options, dict) else ""
        note = ""
        if file_country and file_date and (file_country != country or file_date != date):
            note = f"  文件名：{file_country} {file_date}"
        print(f"[{index}] {item.get('dataset')}  {country}  {date}  {mode}{note}")


def print_content_index() -> None:
    index = rebuild_content_index()
    saves = index.get("saves", {})
    print(f"内容复用索引：{content_index_path()}")
    if not isinstance(saves, dict) or not saves:
        print("还没有内容索引。")
        return
    for number, (quick_hash, entry) in enumerate(sorted(saves.items(), key=lambda item: str(item[1].get("updated_at", "")), reverse=True), 1):
        if not isinstance(entry, dict):
            continue
        views = entry.get("views", {})
        sources = entry.get("sources", [])
        print(f"[{number}] {entry.get('country', '')} {entry.get('date', '')} {quick_hash[:12]}  视图:{len(views) if isinstance(views, dict) else 0}  来源:{len(sources) if isinstance(sources, list) else 0}")


def print_save_list() -> None:
    saves = launcher.list_save_paths()
    print(f"找到存档：{len(saves)}")
    for index, save in enumerate(saves, 1):
        item = launcher.save_preview(save)
        latest = " 最新" if index == 1 else ""
        print(f"[{index}] {item.get('country')} {item.get('date')} {item.get('size')} {item.get('source')} {save.name}{latest}")


def print_status() -> None:
    print(f"版本：v{launcher.APP_VERSION}")
    print(f"数据仓库：{CACHE_ROOT}")
    print("读取后端：")
    tools = external_tools.status(analyze.TOOL_DIR)
    for name in ["rust_scanner", "jomini_extractor", "garibaldi_native_extractor", "garibaldi_melter", "rakaly_cli"]:
        print(f"- {name}: {tools.get(name) or '未安装'}")
    active = tools.get("active_backends", [])
    print("当前可用：" + ("、".join(active) if isinstance(active, list) else str(active)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Victoria 3 Save Analyzer local data API")
    subparsers = parser.add_subparsers(dest="command")

    serve_parser = subparsers.add_parser("serve", help="启动本地 API 服务")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)
    serve_parser.add_argument("--token", default=os.environ.get("VIC3_API_TOKEN", ""), help="公网/API 访问密钥")

    build_parser = subparsers.add_parser("build", help="读取存档并写入 F 盘数据仓库")
    build_parser.add_argument("--save", default="latest", help="latest、存档序号或完整 .v3 路径")
    build_parser.add_argument("--mode", default="systems", choices=["systems", "quick"])
    build_parser.add_argument("--limit", type=int, default=30)
    build_parser.add_argument("--no-pops", action="store_true", help="跳过人口明细")
    build_parser.add_argument("--force", action="store_true", help="即使缓存可用也重新生成")
    build_parser.add_argument("--json", action="store_true", help="输出 JSON")

    subparsers.add_parser("list", help="列出已有数据包")
    subparsers.add_parser("content", help="列出内容复用索引")
    subparsers.add_parser("saves", help="快速列出已识别存档")
    subparsers.add_parser("status", help="显示读取加速器和缓存状态")

    args = parser.parse_args()
    command = args.command or "serve"
    if command == "serve":
        serve(getattr(args, "host", "127.0.0.1"), getattr(args, "port", 8765), getattr(args, "token", ""))
        return
    if command == "list":
        print_dataset_list()
        return
    if command == "content":
        print_content_index()
        return
    if command == "saves":
        print_save_list()
        return
    if command == "status":
        print_status()
        return
    if command == "build":
        path = save_from_text(args.save)
        if not path:
            print_json({"ok": False, "error": "未找到存档"})
            return
        progress = None if args.json else launcher.ProgressPrinter(steps=launcher.COMBINED_EXPORT_STEPS)
        if progress:
            print("正在写入本地数据仓库")
            progress.start()
        try:
            manifest = build_dataset(path, args.mode, max(1, args.limit), not args.no_pops, args.force, progress)
        finally:
            if progress:
                progress.stop()
        if args.json:
            print_json(manifest)
        else:
            print_build_summary(manifest)
        return


if __name__ == "__main__":
    main()
