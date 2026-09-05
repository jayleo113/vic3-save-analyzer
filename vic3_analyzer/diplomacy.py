# -*- coding: utf-8 -*-
"""Diplomacy, pact, subject, and treaty parsing."""

from __future__ import annotations

import re

from vic3_analyzer import metrics, parser_core

SUBJECT_ACTION_NAMES = {
    "puppet": "傀儡国",
    "protectorate": "保护国",
    "vassal": "附庸国",
    "personal_union": "共主邦联",
    "colony": "殖民地",
    "chartered_company": "特许公司领地",
    "dominion": "自治领",
    "tributary": "朝贡国",
}


def parse_relations_for_countries(txt: str, countries: dict[int, dict], country_ids: set[int]) -> list[dict]:
    db = parser_core.database_block(txt, "relations")
    if not db:
        return []
    rows = []
    for key, open_pos, close in parser_core.iter_top_blocks(db, 0, len(db)):
        if not key.isdigit():
            continue
        block = db[open_pos + 1 : close]
        first_block = parser_core.subblock(block, "first")
        second_block = parser_core.subblock(block, "second")
        first = parser_core.top_value(first_block, "country")
        second = parser_core.top_value(second_block, "country")
        if not first or not second or not first.isdigit() or not second.isdigit():
            continue
        first_id = int(first)
        second_id = int(second)
        if first_id not in country_ids and second_id not in country_ids:
            continue
        relation_value = metrics.num(parser_core.top_value(block, "relations"))
        improve = metrics.num(parser_core.top_value(block, "improve_relations"))
        tension = metrics.num(parser_core.top_value(block, "tension"))
        hostility = ";".join(parser_core.list_value(block, "hostility"))
        for country_id, partner_id, side, side_block, partner_block in (
            (first_id, second_id, "first", first_block, second_block),
            (second_id, first_id, "second", second_block, first_block),
        ):
            if country_id not in country_ids:
                continue
            rows.append(
                {
                    "relation_id": int(key),
                    "country_id": country_id,
                    "tag": countries.get(country_id, {}).get("tag", ""),
                    "partner_id": partner_id,
                    "partner_tag": countries.get(partner_id, {}).get("tag", ""),
                    "side": side,
                    "relations": relation_value,
                    "improve_relations": improve,
                    "tension": tension,
                    "hostility": hostility,
                    "obligation": parser_core.top_value(side_block, "obligation") or "",
                    "partner_obligation": parser_core.top_value(partner_block, "obligation") or "",
                    "truce": parser_core.top_value(block, f"{side}_truce") or "",
                    "last_action": parser_core.top_value(side_block, "last_action") or "",
                }
            )
    return sorted(rows, key=lambda row: (row["tag"], row["partner_tag"], row["relation_id"]))


def parse_pacts_for_countries(txt: str, countries: dict[int, dict], country_ids: set[int]) -> list[dict]:
    db = parser_core.database_block(txt, "pacts")
    if not db:
        return []
    rows = []
    for key, open_pos, close in parser_core.iter_top_blocks(db, 0, len(db)):
        if not key.isdigit():
            continue
        block = db[open_pos + 1 : close]
        targets = parser_core.subblock(block, "targets")
        first = parser_core.top_value(targets, "first")
        second = parser_core.top_value(targets, "second")
        if not first or not second or not first.isdigit() or not second.isdigit():
            continue
        first_id = int(first)
        second_id = int(second)
        if first_id not in country_ids and second_id not in country_ids:
            continue
        action = parser_core.top_value(block, "action") or ""
        for country_id, partner_id, side in ((first_id, second_id, "first"), (second_id, first_id, "second")):
            if country_id not in country_ids:
                continue
            rows.append(
                {
                    "pact_id": int(key),
                    "country_id": country_id,
                    "tag": countries.get(country_id, {}).get("tag", ""),
                    "partner_id": partner_id,
                    "partner_tag": countries.get(partner_id, {}).get("tag", ""),
                    "side": side,
                    "action": action,
                    "start_date": parser_core.top_value(block, "start_date") or "",
                    "forced_duration": metrics.num(parser_core.top_value(block, "forced_duration")),
                    "liberty_desire": metrics.num(parser_core.top_value(block, "liberty_desire")),
                }
            )
    return sorted(rows, key=lambda row: (row["tag"], row["action"], row["partner_tag"]))


def parse_subject_relations(pact_rows: list[dict], countries: dict[int, dict]) -> list[dict]:
    rows = []
    seen = set()
    first_side = [row for row in pact_rows if row.get("side") == "first" and row.get("action") in SUBJECT_ACTION_NAMES]
    for row in first_side:
        pact_id = row.get("pact_id")
        if pact_id in seen:
            continue
        seen.add(pact_id)
        overlord_id = row.get("country_id")
        subject_id = row.get("partner_id")
        overlord = countries.get(overlord_id, {}) if isinstance(overlord_id, int) else {}
        subject = countries.get(subject_id, {}) if isinstance(subject_id, int) else {}
        overlord_market = overlord.get("market") or ""
        subject_market = subject.get("market") or ""
        rows.append(
            {
                "pact_id": pact_id,
                "type": SUBJECT_ACTION_NAMES.get(row.get("action"), row.get("action") or ""),
                "raw_action": row.get("action") or "",
                "overlord_id": overlord_id,
                "overlord_tag": overlord.get("tag", row.get("tag") or ""),
                "subject_id": subject_id,
                "subject_tag": subject.get("tag", row.get("partner_tag") or ""),
                "start_date": row.get("start_date") or "",
                "forced_duration": row.get("forced_duration"),
                "liberty_desire": row.get("liberty_desire"),
                "same_market": bool(overlord_market and subject_market and overlord_market == subject_market),
                "overlord_market": overlord_market,
                "subject_market": subject_market,
                "subject_gdp": subject.get("gdp"),
                "subject_population": subject.get("population"),
                "subject_prestige": subject.get("prestige"),
                "overlord_gdp": overlord.get("gdp"),
                "overlord_population": overlord.get("population"),
            }
        )
    return sorted(rows, key=lambda item: (item["overlord_tag"], item["type"], item["subject_tag"]))


def parse_treaties_for_countries(txt: str, countries: dict[int, dict], country_ids: set[int]) -> tuple[list[dict], list[dict]]:
    treaty_db = parser_core.database_block(txt, "treaty_manager")
    article_db = parser_core.database_block(txt, "treaty_article_manager")
    raw_treaties: dict[int, dict] = {}
    if treaty_db:
        for key, open_pos, close in parser_core.iter_top_blocks(treaty_db, 0, len(treaty_db)):
            if not key.isdigit():
                continue
            block = treaty_db[open_pos + 1 : close]
            first = parser_core.top_value(block, "first_country") or ""
            second = parser_core.top_value(block, "second_country") or ""
            name_block = parser_core.subblock(block, "name") or ""
            scripted = parser_core.subblock(name_block, "scripted") or ""
            dynamic = parser_core.subblock(name_block, "dynamic") or ""
            name_type = parser_core.top_value(scripted, "scripted_name") or parser_core.top_value(dynamic, "dynamic_name") or parser_core.top_value(name_block, "scripted_name") or parser_core.top_value(name_block, "dynamic_name") or ""
            context = parser_core.subblock(scripted, "context") or parser_core.subblock(dynamic, "context") or ""
            first_id = int(first) if first.isdigit() else None
            second_id = int(second) if second.isdigit() else None
            raw_treaties[int(key)] = {
                "treaty_id": int(key),
                "name_type": name_type,
                "first_country_id": first_id if first_id is not None else "",
                "first_tag": countries.get(first_id, {}).get("tag", "") if first_id is not None else "",
                "second_country_id": second_id if second_id is not None else "",
                "second_tag": countries.get(second_id, {}).get("tag", "") if second_id is not None else "",
                "entered_into_force_on": parser_core.top_value(block, "entered_into_force_on") or "",
                "binding_period": metrics.num(parser_core.top_value(block, "binding_period")),
                "context_date": parser_core.top_value(context, "date") or "",
                "context_region": parser_core.top_value(context, "region") or "",
                "context_hub": parser_core.top_value(context, "hub") or "",
                "frozen_by_countries": ";".join(parser_core.list_value(block, "frozen_by_countries")),
            }

    raw_articles = []
    treaty_ids_from_articles: set[int] = set()
    if article_db:
        for key, open_pos, close in parser_core.iter_top_blocks(article_db, 0, len(article_db)):
            if not key.isdigit():
                continue
            block = article_db[open_pos + 1 : close]
            treaty = parser_core.top_value(block, "treaty") or ""
            treaty_id = int(treaty) if treaty.isdigit() else None
            source = parser_core.top_value(block, "source_country") or ""
            target = parser_core.top_value(block, "target_country") or ""
            source_id = int(source) if source.isdigit() and source != "4294967295" else None
            target_id = int(target) if target.isdigit() and target != "4294967295" else None
            treaty_row = raw_treaties.get(treaty_id if treaty_id is not None else -1, {})
            involved = {value for value in (source_id, target_id, treaty_row.get("first_country_id"), treaty_row.get("second_country_id")) if isinstance(value, int)}
            if involved & country_ids and treaty_id is not None:
                treaty_ids_from_articles.add(treaty_id)
            contraventions = parser_core.subblock(block, "current_contraventions") or ""
            raw_articles.append(
                {
                    "article_id": int(key),
                    "treaty_id": treaty_id if treaty_id is not None else "",
                    "article": parser_core.top_value(block, "article") or "",
                    "source_country_id": source_id if source_id is not None else "",
                    "source_tag": countries.get(source_id, {}).get("tag", "") if source_id is not None else "",
                    "target_country_id": target_id if target_id is not None else "",
                    "target_tag": countries.get(target_id, {}).get("tag", "") if target_id is not None else "",
                    "goods": parser_core.top_value(block, "goods") or "",
                    "quantity": metrics.num(parser_core.top_value(block, "quantity")),
                    "state": parser_core.top_value(block, "state") or "",
                    "law_type": parser_core.top_value(block, "law_type") or "",
                    "inputs": ";".join(parser_core.list_value(block, "inputs")),
                    "current_contraventions": ";".join(f"{match.group(1)}:{match.group(2)}" for match in re.finditer(r"(?m)^\s*(\d+)\s*=\s*([^\s{}]+)", contraventions)),
                    "first_country_id": treaty_row.get("first_country_id", ""),
                    "first_tag": treaty_row.get("first_tag", ""),
                    "second_country_id": treaty_row.get("second_country_id", ""),
                    "second_tag": treaty_row.get("second_tag", ""),
                }
            )

    treaty_rows = []
    for treaty_id, row in raw_treaties.items():
        first_id = row.get("first_country_id")
        second_id = row.get("second_country_id")
        if first_id in country_ids or second_id in country_ids or treaty_id in treaty_ids_from_articles:
            treaty_rows.append(row)
    treaty_id_set = {row["treaty_id"] for row in treaty_rows}
    article_rows = [row for row in raw_articles if row.get("treaty_id") in treaty_id_set]
    return (
        sorted(treaty_rows, key=lambda row: (row["first_tag"], row["second_tag"], row["treaty_id"])),
        sorted(article_rows, key=lambda row: (row["treaty_id"], row["article_id"])),
    )
