# -*- coding: utf-8 -*-
"""Small numeric and trend helpers used by save parsers."""

from __future__ import annotations

import re

from vic3_analyzer import parser_core


def num(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", value)
    return float(match.group(0)) if match else None


def last_trend_values(block: str | None) -> list[float]:
    if not block:
        return []
    values = []
    pos = 0
    while True:
        match = re.search(r"values\s*=\s*\{", block[pos:])
        if not match:
            break
        open_pos = pos + match.end() - 1
        close = parser_core.brace_span(block, open_pos)
        values = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", block[open_pos + 1 : close])]
        pos = close + 1
    return values


def latest_trend(block: str | None, key: str) -> float | None:
    values = last_trend_values(parser_core.subblock(block or "", key))
    return values[-1] if values else None


def trend_stats(block: str | None, key: str) -> dict[str, object]:
    values = last_trend_values(parser_core.subblock(block or "", key))
    if not values:
        return {"start": "", "latest": "", "change": "", "change_pct": "", "samples": 0}
    start = values[0]
    latest = values[-1]
    change = latest - start
    return {
        "start": start,
        "latest": latest,
        "change": change,
        "change_pct": change / start if start else "",
        "samples": len(values),
    }


def date_sort_key(value: object) -> tuple[int, int, int, int]:
    parts = [int(part) for part in re.findall(r"\d+", str(value or ""))[:4]]
    while len(parts) < 4:
        parts.append(0)
    return tuple(parts[:4])
