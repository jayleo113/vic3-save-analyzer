# -*- coding: utf-8 -*-
"""Persistent save preview catalog for fast save picking."""

from __future__ import annotations

import json
import re
import zipfile
from datetime import datetime
from pathlib import Path

from . import country_names
from .fingerprint import file_fingerprint
from .formatting import normalize_game_date, safe_filename_part
from .cache_io import atomic_json, cache_lock

PREVIEW_BYTES = 384_000
CATALOG_SCHEMA_VERSION = "save_catalog_v1"


def file_size_label(size: int) -> str:
    if size >= 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024 * 1024):.1f}GB"
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f}MB"
    if size >= 1024:
        return f"{size / 1024:.1f}KB"
    return f"{size}B"


def save_source_label(path: Path) -> str:
    text = str(path).lower()
    if "\\steam\\userdata\\" in text or "/steam/userdata/" in text:
        return "Steam云"
    if "\\onedrive\\" in text or "/onedrive/" in text:
        return "OneDrive"
    return "本地文档"


def filename_save_hint(path: Path) -> tuple[str, str]:
    stem = path.stem.strip()
    match = re.search(r"(.+?)[_\-\s]+(\d{4})[_\-\s.]+(\d{1,2})[_\-\s.]+(\d{1,2})", stem)
    if match:
        country = match.group(1).strip("_- ")
        year, month, day = match.group(2), int(match.group(3)), int(match.group(4))
        return country or stem, f"{year}-{month:02d}-{day:02d}"
    return stem, ""


def _preview_value(text: str, key: str) -> str:
    match = re.search(rf"(?m)^\s*{re.escape(key)}\s*=\s*(\"[^\"]*\"|[^\s{{}}]+)", text)
    if not match:
        return ""
    return match.group(1).strip().strip('"')


def _read_preview_text(path: Path, max_bytes: int = PREVIEW_BYTES) -> str:
    with path.open("rb") as handle:
        magic = handle.read(4)
    if magic.startswith(b"PK"):
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            target = "gamestate" if "gamestate" in names else names[0]
            with zf.open(target) as handle:
                return handle.read(max_bytes).decode("utf-8", errors="replace")
    with path.open("rb") as handle:
        return handle.read(max_bytes).decode("utf-8", errors="replace")


def _catalog_path(cache_root: Path) -> Path:
    return cache_root / "save_catalog.json"


def load_catalog(cache_root: Path) -> dict[str, object]:
    path = _catalog_path(cache_root)
    if not path.exists():
        return {"schema": CATALOG_SCHEMA_VERSION, "entries": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"schema": CATALOG_SCHEMA_VERSION, "entries": {}}
    if data.get("schema") != CATALOG_SCHEMA_VERSION or not isinstance(data.get("entries"), dict):
        return {"schema": CATALOG_SCHEMA_VERSION, "entries": {}}
    return data


def save_catalog(cache_root: Path, catalog: dict[str, object]) -> None:
    cache_root.mkdir(parents=True, exist_ok=True)
    atomic_json(_catalog_path(cache_root), catalog)


def preview(path: Path, cache_root: Path, names: dict[str, str] | None = None, force: bool = False) -> dict[str, object]:
    with cache_lock(cache_root / 'catalog.lock'):
        return _preview(path, cache_root, names, force)


def _preview(path: Path, cache_root: Path, names: dict[str, str] | None, force: bool):
    names = names or {}
    stat = path.stat()
    key = str(path.resolve())
    catalog = load_catalog(cache_root)
    entries = catalog.setdefault("entries", {})
    old = entries.get(key) if isinstance(entries, dict) else None
    if (
        isinstance(old, dict)
        and not force
        and old.get("size_raw") == stat.st_size
        and old.get("mtime_ns") == stat.st_mtime_ns
    ):
        old["path"] = path
        return old
    filename_country, filename_date = filename_save_hint(path)
    try:
        text = _read_preview_text(path)
        raw_date = _preview_value(text, "game_date") or _preview_value(text, "date")
        raw_country = _preview_value(text, "name") or filename_country or safe_filename_part(path.stem, "未知国家")
        status = "可读"
    except Exception as exc:
        raw_date = ""
        raw_country = filename_country or "读取失败"
        status = str(exc)[:50]
    fp = file_fingerprint(path)
    item = {
        "path": path,
        "path_text": key,
        "country": country_names.display_name(raw_country, names),
        "date": normalize_game_date(raw_date) if raw_date else filename_date or "未知日期",
        "version": _preview_value(text, "version") if "text" in locals() else "未知版本",
        "rank": _preview_value(text, "rank") if "text" in locals() else "未知地位",
        "size": file_size_label(stat.st_size),
        "size_raw": stat.st_size,
        "mtime": stat.st_mtime,
        "mtime_ns": stat.st_mtime_ns,
        "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
        "source": save_source_label(path),
        "status": status,
        "quick_hash": fp["quick_hash"],
    }
    if isinstance(entries, dict):
        serializable = dict(item)
        serializable["path"] = key
        entries[key] = serializable
        save_catalog(cache_root, catalog)
    return item


def preview_many(paths: list[Path], cache_root: Path, names: dict[str, str] | None = None) -> list[dict[str, object]]:
    return [preview(path, cache_root, names) for path in paths]
