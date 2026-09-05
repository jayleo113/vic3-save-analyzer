# -*- coding: utf-8 -*-
"""State and territory parsing helpers."""

from __future__ import annotations

from vic3_analyzer import metrics, parser_core


def parse_state_trade_goods(block: str) -> list[dict]:
    traded_goods = parser_core.list_value(block, "traded_goods")
    trade_block = parser_core.subblock(block, "trade")
    goods_block = parser_core.subblock(trade_block or "", "goods")
    goods_items = []
    if goods_block:
        for good_key, good_open, good_close in parser_core.iter_top_blocks(goods_block, 0, len(goods_block)):
            item_block = goods_block[good_open + 1 : good_close]
            goods_items.append((good_key, metrics.num(parser_core.top_value(item_block, "value"))))
    if not goods_items:
        goods_items = [(str(index), "") for index, _ in enumerate(traded_goods)]
    rows = []
    for index, (good_id, trade_value) in enumerate(goods_items):
        rows.append(
            {
                "goods_id": good_id,
                "goods_name": traded_goods[index] if index < len(traded_goods) else "",
                "trade_value": trade_value,
            }
        )
    return rows


def parse_all_states(txt: str, countries: dict[int, dict]) -> tuple[list[dict], dict[int, int]]:
    states_block = parser_core.database_block(txt, "states")
    if not states_block:
        return [], {}
    rows = []
    state_to_country = {}
    state_keys = {
        "country",
        "state_region",
        "capital",
        "arable_land",
        "incorporation",
        "infrastructure",
        "infrastructure_usage",
        "trade_capacity",
        "trade_capacity_usage",
        "devastation",
        "base_pop_bureaucracy_cost",
        "previous_country_definition",
        "last_owner_change",
    }
    for key, block in parser_core.iter_numbered_entries(states_block):
        values = parser_core.top_values(block, state_keys)
        country = values.get("country")
        if not country or not country.isdigit():
            continue
        country_id = int(country)
        state_id = int(key)
        state_to_country[state_id] = country_id
        country_row = countries.get(country_id, {})
        trade_goods = parse_state_trade_goods(block)
        rows.append(
            {
                "country_id": country_id,
                "tag": country_row.get("tag", ""),
                "state_id": state_id,
                "region": values.get("state_region") or "",
                "capital": values.get("capital") or "",
                "arable_land": metrics.num(values.get("arable_land")),
                "incorporation": metrics.num(values.get("incorporation")),
                "infrastructure": metrics.num(values.get("infrastructure")),
                "infrastructure_usage": metrics.num(values.get("infrastructure_usage")),
                "trade_capacity": metrics.num(values.get("trade_capacity")),
                "trade_capacity_usage": metrics.num(values.get("trade_capacity_usage")),
                "devastation": metrics.num(values.get("devastation")),
                "bureaucracy_cost": metrics.num(values.get("base_pop_bureaucracy_cost")),
                "previous_country": values.get("previous_country_definition") or "",
                "last_owner_change": values.get("last_owner_change") or "",
                "_trade_goods": trade_goods,
            }
        )
    return rows, state_to_country


def parse_states_for_country(txt: str, country_id: int) -> list[dict]:
    all_states, _ = parse_all_states(txt, {})
    return [
        {
            "state_id": row["state_id"],
            "region": row.get("region") or "",
            "arable_land": row.get("arable_land"),
            "incorporation": row.get("incorporation"),
            "infrastructure": row.get("infrastructure"),
            "infrastructure_usage": row.get("infrastructure_usage"),
            "bureaucracy_cost": row.get("bureaucracy_cost"),
            "previous_country": row.get("previous_country") or "",
            "last_owner_change": row.get("last_owner_change") or "",
        }
        for row in all_states
        if row.get("country_id") == country_id
    ]
