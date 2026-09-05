# -*- coding: utf-8 -*-
"""SQLite mirror for generated Victoria 3 datasets."""

from __future__ import annotations

import csv
import json
import sqlite3
from contextlib import closing
from pathlib import Path

SQLITE_NAME = "dataset.sqlite"
SQLITE_SCHEMA_VERSION = "sqlite_v3_jsonl_indexes"
JSONL_DIR = "tables"
INDEX_FIELDS = {
    "country_id",
    "tag",
    "country_label",
    "state_id",
    "market_id",
    "war_id",
    "diplomatic_play",
    "building",
    "sector",
    "culture",
    "dimension",
}


def _safe_table_name(name: str) -> str:
    clean = "".join(char if char.isalnum() or char == "_" else "_" for char in name)
    if not clean or clean[0].isdigit():
        clean = f"t_{clean}"
    return clean


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        return fields, list(reader)


def csv_to_jsonl(csv_path: Path, jsonl_path: Path) -> int:
    if not csv_path.exists():
        return 0
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with csv_path.open("r", encoding="utf-8-sig", newline="") as source, jsonl_path.open("w", encoding="utf-8", newline="\n") as target:
        reader = csv.DictReader(source)
        for row in reader:
            target.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            count += 1
    return count


def write_dataset_jsonl(dataset_dir: Path, manifest: dict[str, object], table_descriptions: dict[str, str]) -> dict[str, str]:
    outputs = manifest.get("outputs", {})
    if not isinstance(outputs, dict):
        return {}
    jsonl_outputs: dict[str, str] = {}
    for table in table_descriptions:
        output_name = outputs.get(table)
        if not output_name:
            continue
        csv_path = dataset_dir / str(output_name)
        jsonl_path = dataset_dir / JSONL_DIR / f"{table}.jsonl"
        csv_to_jsonl(csv_path, jsonl_path)
        jsonl_outputs[table] = str(Path(JSONL_DIR) / jsonl_path.name)
    return jsonl_outputs


def read_jsonl_table(jsonl_path: Path, limit: int = 500, offset: int = 0) -> dict[str, object]:
    if not jsonl_path.exists():
        raise RuntimeError("JSONL 表不存在，请先构建数据包")
    rows = []
    total = 0
    start = max(0, offset)
    stop = start + max(0, limit)
    with jsonl_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            if start <= total < stop:
                rows.append(json.loads(line))
            total += 1
    return {"count": total, "limit": limit, "offset": offset, "rows": rows}


def _write_table(conn: sqlite3.Connection, table: str, csv_path: Path) -> int:
    if not csv_path.exists():
        return 0
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows_iter = reader
        table_name = _safe_table_name(table)
        conn.execute(f"DROP TABLE IF EXISTS {_quote(table_name)}")
        if not fields:
            conn.execute(f"CREATE TABLE {_quote(table_name)} (_empty TEXT)")
            return 0
        columns = ", ".join(f"{_quote(field)} TEXT" for field in fields)
        conn.execute(f"CREATE TABLE {_quote(table_name)} ({columns})")
        placeholders = ", ".join("?" for _ in fields)
        sql = f"INSERT INTO {_quote(table_name)} ({', '.join(_quote(field) for field in fields)}) VALUES ({placeholders})"
        count = 0
        batch = []
        for row in rows_iter:
            batch.append([row.get(field, "") for field in fields])
            if len(batch) >= 5000:
                conn.executemany(sql, batch)
                count += len(batch)
                batch = []
        if batch:
            conn.executemany(sql, batch)
            count += len(batch)
    table_name = _safe_table_name(table)
    for field in fields:
        if field in INDEX_FIELDS:
            index_name = _safe_table_name(f"idx_{table_name}_{field}")
            conn.execute(f"CREATE INDEX IF NOT EXISTS {_quote(index_name)} ON {_quote(table_name)} ({_quote(field)})")
    return count


def write_dataset_sqlite(dataset_dir: Path, manifest: dict[str, object], table_descriptions: dict[str, str]) -> Path:
    sqlite_path = dataset_dir / SQLITE_NAME
    if sqlite_path.exists():
        sqlite_path.unlink()

    outputs = manifest.get("outputs", {})
    if not isinstance(outputs, dict):
        outputs = {}

    with closing(sqlite3.connect(sqlite_path)) as conn, conn:
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA synchronous=OFF")
        conn.execute(
            "CREATE TABLE dataset_manifest (key TEXT PRIMARY KEY, value TEXT)"
        )
        conn.execute(
            "CREATE TABLE dataset_tables (name TEXT PRIMARY KEY, description TEXT, rows INTEGER, source_file TEXT)"
        )
        conn.executemany(
            "INSERT INTO dataset_manifest (key, value) VALUES (?, ?)",
            [
                ("manifest", json.dumps(manifest, ensure_ascii=False)),
                ("dataset", str(manifest.get("dataset", ""))),
                ("generated_at", str(manifest.get("generated_at", ""))),
            ],
        )
        for table, description in table_descriptions.items():
            output_name = outputs.get(table)
            if not output_name:
                continue
            csv_path = dataset_dir / str(output_name)
            count = _write_table(conn, table, csv_path)
            conn.execute(
                "INSERT OR REPLACE INTO dataset_tables (name, description, rows, source_file) VALUES (?, ?, ?, ?)",
                (table, description, count, str(csv_path.name)),
            )
        conn.commit()
    return sqlite_path


def list_sqlite_tables(sqlite_path: Path) -> list[dict[str, object]]:
    if not sqlite_path.exists():
        return []
    with closing(sqlite3.connect(sqlite_path)) as conn, conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute("SELECT name, description, rows, source_file FROM dataset_tables ORDER BY name")]


def iter_sqlite_rows(sqlite_path: Path, table: str):
    """Stream every record for exports without a silent pagination ceiling."""
    table_name = _safe_table_name(table)
    with closing(sqlite3.connect(sqlite_path.resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        conn.row_factory = sqlite3.Row
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table_name,)).fetchone():
            raise RuntimeError(f'未知 SQLite 表：{table}')
        for row in conn.execute(f'SELECT * FROM {_quote(table_name)}'):
            yield dict(row)


def read_sqlite_table(sqlite_path: Path, table: str, limit: int = 500, offset: int = 0) -> dict[str, object]:
    if not sqlite_path.exists():
        raise RuntimeError("SQLite 数据库不存在，请先构建数据包")
    table_name = _safe_table_name(table)
    with closing(sqlite3.connect(sqlite_path)) as conn, conn:
        conn.row_factory = sqlite3.Row
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        if not exists:
            raise RuntimeError(f"未知 SQLite 表：{table}")
        total = conn.execute(f"SELECT COUNT(*) AS count FROM {_quote(table_name)}").fetchone()["count"]
        rows = [
            dict(row)
            for row in conn.execute(
                f"SELECT * FROM {_quote(table_name)} LIMIT ? OFFSET ?",
                (max(0, limit), max(0, offset)),
            )
        ]
    return {"table": table, "count": total, "limit": limit, "offset": offset, "rows": rows}


def query_sqlite_select(sqlite_path: Path, sql: str, limit: int = 500) -> dict[str, object]:
    if not sqlite_path.exists():
        raise RuntimeError("SQLite 数据库不存在，请先构建数据包")
    statement = (sql or "").strip().rstrip(";")
    lowered = statement.lower()
    if not (lowered.startswith("select ") or lowered.startswith("with ")):
        raise RuntimeError("只允许 SELECT/WITH 只读查询")
    blocked = (" insert ", " update ", " delete ", " drop ", " alter ", " create ", " attach ", " detach ", " vacuum ", " pragma ")
    padded = f" {lowered} "
    if any(token in padded for token in blocked):
        raise RuntimeError("查询包含非只读关键字，已拒绝")
    wrapped = f"SELECT * FROM ({statement}) LIMIT ?"
    with closing(sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)) as conn, conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(row) for row in conn.execute(wrapped, (max(0, limit),))]
    return {"sql": statement, "limit": limit, "count": len(rows), "rows": rows}
