# -*- coding: utf-8 -*-
"""Building parsing and summarization."""

from __future__ import annotations

import re
from collections import Counter

from vic3_analyzer import metrics, parser_core


def building_category(name: str) -> str:
    name = name.lower()
    if any(token in name for token in ("mine", "logging", "oil", "rubber", "gold", "coal", "iron", "lead", "sulfur")):
        return "资源开采"
    if any(token in name for token in ("farm", "plantation", "ranch", "whaling", "fishing", "rye", "wheat", "rice", "maize", "millet", "livestock")):
        return "农业与初级品"
    if any(token in name for token in ("barracks", "naval", "military", "conscription", "port")):
        return "军事与海军"
    if any(token in name for token in ("railway", "power", "canal")):
        return "基础设施"
    if any(token in name for token in ("administration", "university", "arts", "urban", "trade_center", "manor", "financial")):
        return "治理、服务与城市部门"
    if name:
        return "工业制造"
    return "未知"


def parse_buildings_for_countries(txt: str, state_to_country: dict[int, int], countries: dict[int, dict], country_ids: set[int]) -> tuple[list[dict], list[dict]]:
    db = parser_core.database_block(txt, "building_manager")
    if not db:
        return [], []
    rows = []
    aggregate: dict[tuple[int, str], dict] = {}
    building_keys = {
        "state",
        "building",
        "type",
        "levels",
        "level",
        "staffing",
        "goods_sales",
        "goods_cost",
        "profit_after_reserves",
        "throughput",
        "salary_rate",
        "cash_reserves",
        "active",
    }
    for key, block in parser_core.iter_numbered_entries(db):
        values = parser_core.top_values(block, building_keys)
        state = values.get("state")
        if not state or not state.isdigit():
            continue
        state_id = int(state)
        country_id = state_to_country.get(state_id)
        if country_id not in country_ids:
            continue
        country_row = countries.get(country_id, {})
        building = values.get("building") or values.get("type") or ""
        levels = metrics.num(values.get("levels") or values.get("level") or "0") or 0
        staffing = metrics.num(values.get("staffing"))
        goods_sales = metrics.num(values.get("goods_sales"))
        goods_cost = metrics.num(values.get("goods_cost"))
        profit = metrics.num(values.get("profit_after_reserves"))
        row = {
            "country_id": country_id,
            "tag": country_row.get("tag", ""),
            "state_id": state_id,
            "building_id": int(key),
            "building": building,
            "levels": levels,
            "staffing": staffing,
            "throughput": metrics.num(values.get("throughput")),
            "salary_rate": metrics.num(values.get("salary_rate")),
            "goods_sales": goods_sales,
            "goods_cost": goods_cost,
            "profit_after_reserves": profit,
            "cash_reserves": metrics.num(values.get("cash_reserves")),
            "active": values.get("active") or "",
        }
        rows.append(row)
        key2 = (country_id, building)
        item = aggregate.setdefault(
            key2,
            {
                "country_id": country_id,
                "tag": country_row.get("tag", ""),
                "building": building,
                "sector": building_category(building),
                "building_count": 0,
                "levels": 0,
                "staffing": 0,
                "goods_sales": 0,
                "goods_cost": 0,
                "profit_after_reserves": 0,
            },
        )
        item["building_count"] += 1
        item["levels"] += levels or 0
        item["staffing"] += staffing or 0
        item["goods_sales"] += goods_sales or 0
        item["goods_cost"] += goods_cost or 0
        item["profit_after_reserves"] += profit or 0
    return rows, sorted(aggregate.values(), key=lambda row: (row["tag"], -row["levels"], row["building"]))


def parse_buildings(txt: str, state_ids: set[int]) -> list[dict]:
    db = parser_core.database_block(txt, "building_manager")
    if not db:
        return []
    rows = []
    for key, open_pos, close in parser_core.iter_top_blocks(db, 0, len(db)):
        if not key.isdigit():
            continue
        block = db[open_pos + 1 : close]
        state = parser_core.top_value(block, "state")
        if not state or int(state) not in state_ids:
            continue
        rows.append(
            {
                "building_id": int(key),
                "state_id": int(state),
                "building": parser_core.top_value(block, "building") or parser_core.top_value(block, "type") or "",
                "levels": metrics.num(parser_core.top_value(block, "levels") or parser_core.top_value(block, "level") or "0") or 0,
                "cash_reserves": metrics.num(parser_core.top_value(block, "cash_reserves")),
            }
        )
    return rows


def summarize_building_categories(buildings: list[dict]) -> list[dict]:
    totals: dict[str, dict] = {}
    for row in buildings:
        category = building_category(str(row.get("building", "")))
        item = totals.setdefault(category, {"category": category, "levels": 0, "staffing": 0, "profit": 0})
        item["levels"] += row.get("levels") or 0
        item["staffing"] += row.get("staffing") or 0
        item["profit"] += row.get("profit_after_reserves") or 0
    return sorted(totals.values(), key=lambda row: row["levels"], reverse=True)


def active_construction(country_block: str | None) -> list[dict]:
    queue = parser_core.subblock(country_block or "", "construction_queue")
    if not queue:
        return []
    counts = Counter(re.findall(r"type=([A-Za-z0-9_\-]+)", queue))
    return [{"building": key, "count": value} for key, value in counts.most_common()]
