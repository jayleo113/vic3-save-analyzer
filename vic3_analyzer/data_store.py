# -*- coding: utf-8 -*-
"""SQLite mirror for generated Victoria 3 datasets."""

from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

SQLITE_NAME = "dataset.sqlite"
SQLITE_SCHEMA_VERSION = "sqlite_v2_indexes"
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


def _write_table(conn: sqlite3.Connection, table: str, csv_path: Path) -> int:
    if not csv_path.exists():
        return 0
    fields, rows = _read_csv(csv_path)
    table_name = _safe_table_name(table)
    conn.execute(f"DROP TABLE IF EXISTS {_quote(table_name)}")
    if not fields:
        conn.execute(f"CREATE TABLE {_quote(table_name)} (_empty TEXT)")
        return 0
    columns = ", ".join(f"{_quote(field)} TEXT" for field in fields)
    conn.execute(f"CREATE TABLE {_quote(table_name)} ({columns})")
    placeholders = ", ".join("?" for _ in fields)
    sql = f"INSERT INTO {_quote(table_name)} ({', '.join(_quote(field) for field in fields)}) VALUES ({placeholders})"
    conn.executemany(sql, ([row.get(field, "") for field in fields] for row in rows))
    for field in fields:
        if field in INDEX_FIELDS:
            index_name = _safe_table_name(f"idx_{table_name}_{field}")
            conn.execute(f"CREATE INDEX IF NOT EXISTS {_quote(index_name)} ON {_quote(table_name)} ({_quote(field)})")
    return len(rows)


def write_dataset_sqlite(dataset_dir: Path, manifest: dict[str, object], table_descriptions: dict[str, str]) -> Path:
    sqlite_path = dataset_dir / SQLITE_NAME
    if sqlite_path.exists():
        sqlite_path.unlink()

    outputs = manifest.get("outputs", {})
    if not isinstance(outputs, dict):
        outputs = {}

    with sqlite3.connect(sqlite_path) as conn:
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
    with sqlite3.connect(sqlite_path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute("SELECT name, description, rows, source_file FROM dataset_tables ORDER BY name")]


def read_sqlite_table(sqlite_path: Path, table: str, limit: int = 500, offset: int = 0) -> dict[str, object]:
    if not sqlite_path.exists():
        raise RuntimeError("SQLite 数据库不存在，请先构建数据包")
    table_name = _safe_table_name(table)
    with sqlite3.connect(sqlite_path) as conn:
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
    with sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        rows = [dict(row) for row in conn.execute(wrapped, (max(0, limit),))]
    return {"sql": statement, "limit": limit, "count": len(rows), "rows": rows}
