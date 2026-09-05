# -*- coding: utf-8 -*-
"""Population parsing and aggregation."""

from __future__ import annotations

import re
from collections import Counter

from vic3_analyzer import metrics, parser_core

POP_KEYS = {
    "location",
    "state",
    "country",
    "workforce",
    "dependents",
    "size",
    "type",
    "pop_type",
    "culture",
    "religion",
    "workplace",
    "loyalists_and_radicals",
    "loyalists",
    "radicals",
}


def parse_pops_for_countries(
    txt: str,
    state_to_country: dict[int, int],
    countries: dict[int, dict],
    country_ids: set[int],
    culture_map: dict[str, str],
    progress=None,
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    db = parser_core.database_block(txt, "pops")
    if not db:
        return [], [], [], []

    summaries: dict[int, dict] = {}
    by_type: dict[tuple[int, str], dict] = {}
    by_culture: dict[tuple[int, str], dict] = {}
    by_religion: dict[tuple[int, str], dict] = {}

    entries = list(re.finditer(r"(?m)^(\d+)=(\{|none)", db))
    total_entries = max(len(entries), 1)
    last_bucket = -1
    for index, match in enumerate(entries):
        if progress and (index % 5000 == 0 or index + 1 == len(entries)):
            bucket = int((index + 1) * 100 / total_entries)
            if bucket != last_bucket:
                progress(bucket, f"扫描人口条目 {index + 1:,}/{len(entries):,}")
                last_bucket = bucket
        if match.group(2) == "none":
            continue
        end = entries[index + 1].start() if index + 1 < len(entries) else len(db)
        block = db[match.end() : end]
        values = parser_core.top_values(block, POP_KEYS)
        state = values.get("location") or values.get("state")
        if not state or not state.isdigit():
            continue
        country_id = state_to_country.get(int(state))
        if country_id not in country_ids:
            continue

        country_row = countries.get(country_id, {})
        workforce = int(metrics.num(values.get("workforce")) or 0)
        dependents = int(metrics.num(values.get("dependents")) or 0)
        size = int(metrics.num(values.get("size")) or workforce + dependents)
        if size <= 0:
            continue
        pop_type = values.get("type") or values.get("pop_type") or "unknown"
        raw_culture = values.get("culture") or "unknown"
        culture = culture_map.get(raw_culture, raw_culture)
        religion = values.get("religion") or "unknown"
        workplace = values.get("workplace") or ""
        loyalist_balance = int(metrics.num(values.get("loyalists_and_radicals")) or 0)
        loyalists = int(metrics.num(values.get("loyalists")) or 0)
        radicals = int(metrics.num(values.get("radicals")) or 0)
        if not loyalists and not radicals:
            if loyalist_balance >= 0:
                loyalists = loyalist_balance
            else:
                radicals = -loyalist_balance

        summary = summaries.setdefault(
            country_id,
            {
                "country_id": country_id,
                "tag": country_row.get("tag", ""),
                "population_detail": 0,
                "workforce": 0,
                "dependents": 0,
                "loyalists": 0,
                "radicals": 0,
                "unanchored": 0,
                "pop_entries": 0,
            },
        )
        summary["population_detail"] += size
        summary["workforce"] += workforce
        summary["dependents"] += dependents
        summary["loyalists"] += loyalists
        summary["radicals"] += radicals
        summary["unanchored"] += size if not workplace or workplace == "4294967295" else 0
        summary["pop_entries"] += 1

        for store, dimension, raw_dimension in (
            (by_type, pop_type, pop_type),
            (by_culture, culture, raw_culture),
            (by_religion, religion, religion),
        ):
            item = store.setdefault(
                (country_id, dimension),
                {
                    "country_id": country_id,
                    "tag": country_row.get("tag", ""),
                    "dimension": dimension,
                    "raw_dimension": raw_dimension,
                    "population": 0,
                    "workforce": 0,
                    "dependents": 0,
                    "loyalists": 0,
                    "radicals": 0,
                },
            )
            item["population"] += size
            item["workforce"] += workforce
            item["dependents"] += dependents
            item["loyalists"] += loyalists
            item["radicals"] += radicals

    if progress:
        progress(100, f"人口扫描完成，可读人口组 {sum(row['pop_entries'] for row in summaries.values()):,}")

    for store in (by_type, by_culture, by_religion):
        for item in store.values():
            total = summaries.get(item["country_id"], {}).get("population_detail") or 0
            item["share"] = item["population"] / total if total else 0

    return (
        sorted(summaries.values(), key=lambda row: row["tag"]),
        sorted(by_type.values(), key=lambda row: (row["tag"], -row["population"], row["dimension"])),
        sorted(by_culture.values(), key=lambda row: (row["tag"], -row["population"], row["dimension"])),
        sorted(by_religion.values(), key=lambda row: (row["tag"], -row["population"], row["dimension"])),
    )


def parse_pops(txt: str, state_ids: set[int], country_id: int | None, culture_map: dict[str, str] | None = None) -> dict[str, object]:
    db = parser_core.database_block(txt, "pops")
    if not db:
        return empty_pop_stats()

    rows = []
    by_type = Counter()
    by_culture = Counter()
    by_religion = Counter()
    total = 0
    loyalists = 0
    radicals = 0
    unanchored = 0

    entries = list(re.finditer(r"(?m)^(\d+)=(\{|none)", db))
    for index, match in enumerate(entries):
        key = match.group(1)
        if match.group(2) == "none":
            continue
        end = entries[index + 1].start() if index + 1 < len(entries) else len(db)
        block = db[match.end() : end]
        values = parser_core.top_values(block, POP_KEYS)
        state = values.get("location") or values.get("state")
        country = values.get("country")
        if state_ids:
            if not state or not state.isdigit() or int(state) not in state_ids:
                continue
        elif country_id is not None and country != str(country_id):
            continue

        workforce = int(metrics.num(values.get("workforce")) or 0)
        dependents = int(metrics.num(values.get("dependents")) or 0)
        size = int(metrics.num(values.get("size")) or workforce + dependents)
        if size <= 0:
            continue

        pop_type = values.get("type") or values.get("pop_type") or "unknown"
        raw_culture = values.get("culture") or "unknown"
        culture = (culture_map or {}).get(raw_culture, raw_culture)
        religion = values.get("religion") or "unknown"
        workplace = values.get("workplace") or ""

        row_loyalists = int(metrics.num(values.get("loyalists")) or 0)
        row_radicals = int(metrics.num(values.get("radicals")) or 0)
        loyalist_balance = int(metrics.num(values.get("loyalists_and_radicals")) or 0)
        if not row_loyalists and not row_radicals:
            if loyalist_balance >= 0:
                row_loyalists = loyalist_balance
            else:
                row_radicals = -loyalist_balance
        total += size
        loyalists += row_loyalists
        radicals += row_radicals
        if not workplace or workplace == "4294967295":
            unanchored += size

        by_type[pop_type] += size
        by_culture[culture] += size
        by_religion[religion] += size
        rows.append(
            {
                "pop_id": int(key),
                "state_id": int(state) if state and state.isdigit() else "",
                "type": pop_type,
                "culture": culture,
                "raw_culture": raw_culture,
                "religion": religion,
                "size": size,
                "workforce": workforce,
                "dependents": dependents,
                "loyalists": row_loyalists,
                "radicals": row_radicals,
                "workplace": workplace,
            }
        )

    def counter_rows(counter: Counter) -> list[dict]:
        return [
            {"name": name, "population": value, "share": (value / total if total else 0)}
            for name, value in counter.most_common()
        ]

    return {
        "total": total,
        "loyalists": loyalists,
        "radicals": radicals,
        "unanchored": unanchored,
        "rows": rows,
        "by_type": counter_rows(by_type),
        "by_culture": counter_rows(by_culture),
        "by_religion": counter_rows(by_religion),
    }


def empty_pop_stats() -> dict[str, object]:
    return {
        "total": 0,
        "loyalists": 0,
        "radicals": 0,
        "unanchored": 0,
        "rows": [],
        "by_type": [],
        "by_culture": [],
        "by_religion": [],
    }
