# -*- coding: utf-8 -*-
"""Formatting and file-output helpers for reports."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path


def safe_filename_part(value: object, fallback: str = "UNKNOWN") -> str:
    text = str(value or "").strip().strip('"') or fallback
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", text)
    text = re.sub(r"\s+", "_", text)
    text = text.strip("._ ")
    return text[:80] or fallback


def normalize_game_date(value: object) -> str:
    text = str(value or "").strip().strip('"')
    match = re.match(r"^(\d{1,5})\.(\d{1,2})\.(\d{1,2})(?:\.\d+)?$", text)
    if match:
        year, month, day = match.groups()
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    return safe_filename_part(text, "DATE_UNKNOWN")


def fmt(value, digits=1) -> str:
    if value is None:
        return "NA"
    if isinstance(value, str) and not value.strip():
        return "NA"
    value = float(value)
    sign = "-" if value < 0 else ""
    value = abs(value)
    if value >= 1_000_000_000:
        return f"{sign}{value / 1_000_000_000:.{digits}f}B"
    if value >= 1_000_000:
        return f"{sign}{value / 1_000_000:.{digits}f}M"
    if value >= 1_000:
        return f"{sign}{value / 1_000:.{digits}f}K"
    return f"{sign}{value:.0f}"


def pct(value) -> str:
    if value is None or value == "":
        return "NA"
    return f"{float(value) * 100:.1f}%"


def sol_text(value) -> str:
    if value is None:
        return "NA"
    if isinstance(value, str) and not value.strip():
        return "NA"
    return f"{float(value):.2f}"


def nice_token(value) -> str:
    if value is None or value == "":
        return "NA"
    text = str(value)
    for prefix in ("building_", "law_", "ig_", "gov_", "pm_", "decree_", "state_trait_", "lgbtq_"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    return text.replace("_", " ")


def md_table(rows: list[dict], fields: list[tuple[str, str]], limit: int | None = None) -> list[str]:
    out = []
    shown = rows[:limit] if limit else rows
    out.append("| " + " | ".join(label for label, _ in fields) + " |")
    out.append("|" + "|".join("---" for _ in fields) + "|")
    for row in shown:
        out.append("| " + " | ".join(str(row.get(key, "")) for _, key in fields) + " |")
    return out


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
