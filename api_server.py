# -*- coding: utf-8 -*-
"""Local HTTP API and disk cache builder for Victoria 3 save exports."""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import analyze
import launcher
from vic3_analyzer import data_store


CACHE_ROOT = analyze.TOOL_DIR / "data_cache"
API_TOKEN = ""
DATASET_SCHEMA_VERSION = "api_dataset_v3"

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
    country = analyze.safe_filename_part(preview.get("country"), "UNKNOWN")
    date = analyze.safe_filename_part(preview.get("date"), "DATE_UNKNOWN")
    detail = f"{mode}_top{limit}_{'full' if full_pops else 'lite'}"
    return analyze.safe_filename_part(f"{country}_{date}_{detail}")


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


def dataset_sort_key(item: dict[str, object]) -> tuple[str, str]:
    source = item.get("source", {})
    game_date = ""
    if isinstance(source, dict):
        game_date = str(source.get("date") or "")
    return (game_date, str(item.get("generated_at", "")))


def list_datasets() -> list[dict[str, object]]:
    if not CACHE_ROOT.exists():
        return []
    rows = []
    for dataset_dir in CACHE_ROOT.iterdir():
        if not dataset_dir.is_dir():
            continue
        manifest = load_manifest(dataset_dir)
        if not manifest:
            continue
        manifest["dataset"] = dataset_dir.name
        manifest["dataset_dir"] = str(dataset_dir)
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


def manifest_matches(manifest: dict[str, object], path: Path, mode: str, limit: int, full_pops: bool) -> bool:
    stat = path.stat()
    source = manifest.get("source", {})
    options = manifest.get("options", {})
    return (
        isinstance(source, dict)
        and isinstance(options, dict)
        and source.get("path") == str(path.resolve())
        and source.get("mtime") == stat.st_mtime
        and source.get("size") == stat.st_size
        and options.get("mode") == mode
        and options.get("limit") == limit
        and options.get("full_pops") == full_pops
        and manifest.get("schema_version") == DATASET_SCHEMA_VERSION
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
    mode = "quick" if mode == "quick" else "systems"
    dataset_id = dataset_id_for_save(path, mode, limit, full_pops)
    dataset_dir = CACHE_ROOT / dataset_id
    existing = load_manifest(dataset_dir)
    if existing and not force and manifest_matches(existing, path, mode, limit, full_pops):
        sqlite_name = str(existing.get("sqlite") or data_store.SQLITE_NAME)
        sqlite_path = dataset_dir / sqlite_name
        if not sqlite_path.exists() or existing.get("sqlite_schema_version") != data_store.SQLITE_SCHEMA_VERSION:
            sqlite_path = data_store.write_dataset_sqlite(dataset_dir, existing, SYSTEM_DATASETS)
            existing["sqlite"] = sqlite_path.name
            existing["sqlite_schema_version"] = data_store.SQLITE_SCHEMA_VERSION
            manifest_path(dataset_dir).write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
        existing["ok"] = True
        existing["cached"] = True
        return existing

    clean_dataset_dir(dataset_dir)
    previous_report_dir = analyze.REPORT_DIR
    analyze.REPORT_DIR = dataset_dir
    txt = None
    started = time.time()
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
    manifest = {
        "ok": True,
        "cached": False,
        "dataset": dataset_id,
        "dataset_dir": str(dataset_dir),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "schema_version": DATASET_SCHEMA_VERSION,
        "seconds": round(time.time() - started, 2),
        "source": {
            "path": str(path.resolve()),
            "mtime": stat.st_mtime,
            "size": stat.st_size,
            "country": preview.get("country"),
            "date": preview.get("date"),
            "version": preview.get("version"),
        },
        "options": {"mode": mode, "limit": limit, "full_pops": full_pops},
        "report": Path(report).name,
        "outputs": {name: Path(output).name for name, output in outputs.items()},
        "tables": SYSTEM_DATASETS,
        "documents": DOCUMENTS,
    }
    sqlite_path = data_store.write_dataset_sqlite(dataset_dir, manifest, SYSTEM_DATASETS)
    manifest["sqlite"] = sqlite_path.name
    manifest["sqlite_schema_version"] = data_store.SQLITE_SCHEMA_VERSION
    manifest_path(dataset_dir).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
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
    server_version = "vic3-save-analyzer-api/0.1"

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
                        "/api/sql/query?dataset=latest&q=select * from major_countries limit 5",
                        "/api/document/systems_document?dataset=latest",
                    ],
                }
            )
            return

        if path == "/api/health":
            self.json_response({"ok": True, "version": launcher.APP_VERSION, "storage": str(CACHE_ROOT), "auth": "required" if API_TOKEN else "none"})
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
    print(f"文件：{len(outputs) if isinstance(outputs, dict) else 0} 个")
    print("本地 API：python api_server.py serve")
    print("读取数据：http://127.0.0.1:8765/api/package?dataset=latest")
    print("查国家表：http://127.0.0.1:8765/api/sql/table/major_countries?dataset=latest&limit=20")


def print_dataset_list() -> None:
    datasets = list_datasets()
    print(f"数据仓库：{CACHE_ROOT}")
    if not datasets:
        print("还没有数据包。")
        return
    for index, item in enumerate(datasets, 1):
        source = item.get("source", {})
        options = item.get("options", {})
        country = source.get("country", "") if isinstance(source, dict) else ""
        date = source.get("date", "") if isinstance(source, dict) else ""
        mode = options.get("mode", "") if isinstance(options, dict) else ""
        print(f"[{index}] {item.get('dataset')}  {country}  {date}  {mode}")


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

    args = parser.parse_args()
    command = args.command or "serve"
    if command == "serve":
        serve(getattr(args, "host", "127.0.0.1"), getattr(args, "port", 8765), getattr(args, "token", ""))
        return
    if command == "list":
        print_dataset_list()
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
