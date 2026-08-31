# -*- coding: utf-8 -*-
"""维多利亚 3 存档分析器。

用法:
    python analyze.py
    python analyze.py <存档路径>

输出:
    reports/<存档名>_report.md
    reports/<存档名>_countries.csv
    reports/<存档名>_great_powers.csv
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path


SAVE_DIR = Path.home() / "Documents" / "Paradox Interactive" / "Victoria 3" / "save games"
TOOL_DIR = Path(__file__).resolve().parent
REPORT_DIR = TOOL_DIR / "reports"
COMMUNITY_DIR = TOOL_DIR / "community"


COMMUNITY_SOURCES = [
    {
        "name": "Garibaldi",
        "url": "https://github.com/OakenTrader/Garibaldi",
        "license": "MIT",
        "role": "指标体系、自动存档流水线、Rakaly melter/extractor 集成参考",
        "local_path": COMMUNITY_DIR / "Garibaldi",
    },
    {
        "name": "vic3-reader",
        "url": "https://github.com/RobertoTCo/vic3-reader",
        "license": "MIT",
        "role": "Python 分层框架、parser/metrics/orchestrator 结构参考",
        "local_path": COMMUNITY_DIR / "vic3-reader",
    },
    {
        "name": "rakaly/jomini",
        "url": "https://github.com/rakaly/jomini",
        "license": "MIT",
        "role": "Paradox/Jomini 存档底层解析思路；当前通过 Garibaldi 自带 Rakaly 可执行文件使用 melt 能力",
        "local_path": None,
    },
]


LAW_NAMES = {
    "law_presidential_republic": "总统共和制",
    "law_parliamentary_republic": "议会共和制",
    "law_monarchy": "君主制",
    "law_autocracy": "独裁制",
    "law_oligarchy": "寡头制",
    "law_wealth_voting": "财富投票",
    "law_census_voting": "财产投票",
    "law_universal_suffrage": "普选制",
    "law_national_supremacy": "民族至上",
    "law_racial_segregation": "种族隔离",
    "law_cultural_exclusion": "文化排斥",
    "law_multicultural": "多元文化",
    "law_total_separation": "完全政教分离",
    "law_state_religion": "国教",
    "law_freedom_of_conscience": "良心自由",
    "law_elected_bureaucrats": "民选官僚",
    "law_appointed_bureaucrats": "任命官僚",
    "law_national_militia": "国民军",
    "law_professional_army": "职业军队",
    "law_mass_conscription": "大规模征兵",
    "law_interventionism": "干涉主义",
    "law_laissez_faire": "自由放任",
    "law_command_economy": "指令经济",
    "law_free_trade": "自由贸易",
    "law_protectionism": "保护主义",
    "law_land_based_taxation": "土地税",
    "law_per_capita_based_taxation": "人头税",
    "law_proportional_taxation": "比例税",
    "law_graduated_taxation": "累进税",
    "law_tenant_farmers": "佃农",
    "law_homesteading": "宅地法",
    "law_commercialized_agriculture": "商业化农业",
    "law_local_police": "地方警察",
    "law_religious_schools": "宗教学校",
    "law_public_schools": "公立学校",
    "law_private_schools": "私立学校",
    "law_charitable_health_system": "慈善医院",
    "law_private_health_insurance": "私人医疗保险",
    "law_public_health_insurance": "公共医疗保险",
    "law_censorship": "审查制度",
    "law_right_of_assembly": "集会权",
    "law_protected_speech": "言论保护",
    "law_no_workers_rights": "无工人权利",
    "law_regulatory_bodies": "监管机构",
    "law_worker_protections": "工人保护",
    "law_compulsory_primary_school": "强制小学",
    "law_no_womens_rights": "无妇女权利",
    "law_women_own_property": "女性财产权",
    "law_women_in_the_workplace": "女性就业",
    "law_womens_suffrage": "妇女选举权",
    "law_wage_subsidies": "工资补贴",
    "law_old_age_pension": "养老金",
    "law_migration_controls": "移民管制",
    "law_no_migration_controls": "无移民管制",
    "law_slavery_banned": "禁止奴隶制",
}


def brace_span(txt: str, start: int) -> int:
    depth = 0
    in_string = False
    escape = False
    for pos in range(start, len(txt)):
        char = txt[pos]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return pos
    raise ValueError("花括号不匹配")


def block_after(txt: str, marker: str) -> tuple[str, int, int] | None:
    pos = txt.find(marker)
    if pos < 0:
        return None
    open_pos = txt.find("{", pos)
    close = brace_span(txt, open_pos)
    return txt[open_pos + 1 : close], open_pos, close


def top_level_block(txt: str, key: str) -> tuple[str, int, int] | None:
    match = re.search(rf"(?m)^{re.escape(key)}\s*=\s*\{{", txt)
    if not match:
        return None
    open_pos = txt.find("{", match.start())
    close = brace_span(txt, open_pos)
    return txt[open_pos + 1 : close], open_pos, close


def subblock(block: str, key: str) -> str | None:
    match = re.search(rf"(?m)^\s*{re.escape(key)}\s*=\s*\{{", block)
    if not match:
        return None
    open_pos = block.find("{", match.start())
    close = brace_span(block, open_pos)
    return block[open_pos + 1 : close]


def top_value(block: str | None, key: str) -> str | None:
    if not block:
        return None
    match = re.search(rf"(?m)^\s*{re.escape(key)}\s*=\s*([^\n{{}}]+)", block)
    return match.group(1).strip().strip('"') if match else None


def list_value(block: str | None, key: str) -> list[str]:
    if not block:
        return []
    match = re.search(rf"(?m)^\s*{re.escape(key)}\s*=\s*\{{([^{{}}]*)\}}", block)
    if not match:
        return []
    return [x.strip('"') for x in re.findall(r'"[^"]*"|\S+', match.group(1))]


def iter_top_blocks(txt: str, start: int, end: int):
    pos = start
    while pos < end:
        if txt[pos] in " \t\r\n":
            pos += 1
            continue
        match = re.match(r"([^\s={}]+)\s*=", txt[pos:end])
        if not match:
            pos += 1
            continue
        key = match.group(1)
        value_pos = pos + match.end()
        while value_pos < end and txt[value_pos] in " \t\r\n":
            value_pos += 1
        if value_pos < end and txt[value_pos] == "{":
            close = brace_span(txt, value_pos)
            yield key, value_pos, close
            pos = close + 1
        else:
            pos = value_pos


def iter_anonymous_blocks(txt: str):
    pos = 0
    while pos < len(txt):
        open_pos = txt.find("{", pos)
        if open_pos < 0:
            return
        close = brace_span(txt, open_pos)
        yield txt[open_pos + 1 : close]
        pos = close + 1


def database_block(txt: str, manager: str) -> str | None:
    manager_block = top_level_block(txt, manager)
    if not manager_block:
        manager_block = block_after(txt, manager + "={")
    if not manager_block:
        return None
    block = manager_block[0]
    db_pos = block.find("database=")
    if db_pos < 0:
        return block
    open_pos = block.find("{", db_pos)
    close = brace_span(block, open_pos)
    return block[open_pos + 1 : close]


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
        close = brace_span(block, open_pos)
        values = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", block[open_pos + 1 : close])]
        pos = close + 1
    return values


def latest_trend(block: str | None, key: str) -> float | None:
    values = last_trend_values(subblock(block or "", key))
    return values[-1] if values else None


def trend_stats(block: str | None, key: str) -> dict[str, object]:
    values = last_trend_values(subblock(block or "", key))
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


def garibaldi_melter_path() -> Path | None:
    if os.name == "nt":
        path = COMMUNITY_DIR / "Garibaldi" / "bin" / "rakaly_windows" / "melter.exe"
    else:
        path = COMMUNITY_DIR / "Garibaldi" / "bin" / "rakaly_linux" / "melter"
    return path if path.exists() else None


def looks_like_text_save(data: bytes) -> bool:
    sample = data[:200_000]
    if b"\x00" in sample:
        return False
    decoded = sample.decode("utf-8", errors="replace")
    if not decoded:
        return False
    replacement_ratio = decoded.count("\ufffd") / max(len(decoded), 1)
    return replacement_ratio < 0.001 and ("meta_data" in decoded or "country_manager" in decoded or "pops" in decoded)


def melt_save_with_garibaldi(path: Path, out: Path | None = None) -> Path:
    melter = garibaldi_melter_path()
    if not melter:
        raise RuntimeError("没有找到 Garibaldi/Rakaly melter，无法自动转换二进制存档")
    if out is None:
        out = Path(tempfile.gettempdir()) / f"{path.stem}.melted.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PATH"] = str(melter.parent) + os.pathsep + env.get("PATH", "")
    command = [str(melter), "save", str(path), str(out)]
    result = subprocess.run(command, cwd=str(COMMUNITY_DIR / "Garibaldi"), env=env, capture_output=True, text=True)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"Rakaly melter 转换失败：{message}")
    return out


def community_status() -> dict[str, object]:
    sources = []
    for source in COMMUNITY_SOURCES:
        local_path = source.get("local_path")
        installed = bool(local_path and Path(local_path).exists())
        sources.append(
            {
                "name": source["name"],
                "url": source["url"],
                "license": source["license"],
                "role": source["role"],
                "installed": installed,
                "local_path": str(local_path) if local_path else None,
            }
        )
    melter = garibaldi_melter_path()
    return {
        "community_dir": str(COMMUNITY_DIR),
        "sources": sources,
        "rakaly_melter": str(melter) if melter else None,
        "rakaly_melter_available": melter is not None,
    }


def read_save(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(b"PK"):
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            target = "gamestate" if "gamestate" in names else names[0]
            data = zf.read(target)
            if looks_like_text_save(data):
                return data.decode("utf-8", errors="replace")
        melted = melt_save_with_garibaldi(path)
        return melted.read_text(encoding="utf-8", errors="replace")
    if not looks_like_text_save(raw):
        melted = melt_save_with_garibaldi(path)
        return melted.read_text(encoding="utf-8", errors="replace")
    return raw.decode("utf-8", errors="replace")


def save_kind(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(b"PK"):
        return "zip"
    return "text" if looks_like_text_save(raw) else "binary_or_unknown"


def find_latest_save() -> Path | None:
    saves = glob.glob(str(SAVE_DIR / "*.v3"))
    if not saves:
        return None
    return Path(max(saves, key=os.path.getmtime))


def meta(txt: str) -> dict[str, object]:
    meta_block = block_after(txt, "meta_data={")
    block = meta_block[0] if meta_block else txt[:5000]
    return {
        "version": top_value(block, "version") or "?",
        "date": top_value(block, "game_date") or top_value(txt, "date") or "?",
        "country": top_value(block, "name") or "?",
        "rank": top_value(block, "rank") or "?",
        "mods": list_value(block, "mods"),
    }


def num(value: str | None) -> float | None:
    if not value:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", value)
    return float(match.group(0)) if match else None


def country_block_by_id(txt: str, country_id: int | str) -> str | None:
    db = database_block(txt, "country_manager")
    if not db:
        return None
    key = str(country_id)
    needle = "\n" + key + "={"
    pos = db.find(needle)
    if pos < 0 and db.startswith(key + "={"):
        pos = 0
    if pos < 0:
        return None
    open_pos = db.find("{", pos)
    close = brace_span(db, open_pos)
    return db[open_pos + 1 : close]


def parse_countries(txt: str) -> dict[int, dict]:
    db = database_block(txt, "country_manager")
    if not db:
        return {}
    countries = {}
    for key, open_pos, close in iter_top_blocks(db, 0, len(db)):
        if not key.isdigit():
            continue
        block = db[open_pos + 1 : close]
        tag = top_value(block, "definition")
        if not tag:
            continue
        pop = 0
        for pop_key in ("population_lower_strata", "population_middle_strata", "population_upper_strata"):
            value = top_value(block, pop_key)
            if value and value.isdigit():
                pop += int(value)
        cid = int(key)
        gdp_trend = trend_stats(block, "gdp")
        prestige_trend = trend_stats(block, "prestige")
        literacy_trend = trend_stats(block, "literacy")
        sol_trend = trend_stats(block, "avgsoltrend")
        countries[cid] = {
            "id": cid,
            "tag": tag,
            "government": top_value(block, "government") or "",
            "capital": top_value(block, "capital") or "",
            "market": top_value(block, "market") or "",
            "legitimacy": num(top_value(block, "legitimacy")),
            "infamy": num(top_value(block, "infamy")),
            "gdp": gdp_trend["latest"] or None,
            "gdp_start": gdp_trend["start"],
            "gdp_change": gdp_trend["change"],
            "gdp_change_pct": gdp_trend["change_pct"],
            "gdp_samples": gdp_trend["samples"],
            "prestige": prestige_trend["latest"] or None,
            "prestige_start": prestige_trend["start"],
            "prestige_change": prestige_trend["change"],
            "prestige_change_pct": prestige_trend["change_pct"],
            "literacy": literacy_trend["latest"] or None,
            "literacy_start": literacy_trend["start"],
            "literacy_change": literacy_trend["change"],
            "literacy_change_pct": literacy_trend["change_pct"],
            "sol": sol_trend["latest"] or None,
            "sol_start": sol_trend["start"],
            "sol_change": sol_trend["change"],
            "sol_change_pct": sol_trend["change_pct"],
            "population": pop or None,
            "raw_block": block,
        }
    return countries


def player_country_id(txt: str, countries: dict[int, dict], meta_country: str) -> int | None:
    player_block = block_after(txt, "player_manager={")
    if player_block:
        ids = re.findall(r"country\s*=\s*(\d+)", player_block[0])
        if ids:
            return int(ids[0])
    for country_id, row in countries.items():
        if row.get("tag") == meta_country:
            return country_id
    return None


def parse_rankings(txt: str, countries: dict[int, dict]) -> list[dict]:
    ranking_block = block_after(txt, "country_rankings={")
    if not ranking_block:
        return []
    rows = []
    pattern = re.compile(
        r"\{\s*rank=(\w+)\s+target=(\w+)\s+prestige=(-?\d+(?:\.\d+)?)\s+score=(-?\d+(?:\.\d+)?)\s+country=(\d+)",
        re.S,
    )
    for rank, target, prestige, score, country_id in pattern.findall(ranking_block[0]):
        cid = int(country_id)
        c = countries.get(cid, {})
        rows.append(
            {
                "country_id": cid,
                "tag": c.get("tag", ""),
                "rank": rank,
                "target": target,
                "prestige": float(prestige),
                "score": float(score),
                "government": c.get("government", ""),
                "infamy": c.get("infamy"),
            }
        )
    rows.sort(key=lambda row: row["prestige"], reverse=True)
    for i, row in enumerate(rows, start=1):
        row["prestige_rank"] = i
    return rows


def parse_laws(txt: str, country_id: int) -> list[dict]:
    pattern = rf"law=([A-Za-z0-9_\-]+)\s+country={country_id}\s+active=yes"
    return [{"law": LAW_NAMES.get(raw, raw), "raw": raw} for raw in re.findall(pattern, txt)]


def parse_culture_map(txt: str) -> dict[str, str]:
    db = database_block(txt, "cultures")
    if not db:
        return {}
    cultures = {}
    for key, open_pos, close in iter_top_blocks(db, 0, len(db)):
        if not key.isdigit():
            continue
        block = db[open_pos + 1 : close]
        culture_type = top_value(block, "type")
        if culture_type:
            cultures[key] = culture_type
    return cultures


def select_major_country_ids(countries: dict[int, dict], rankings: list[dict], player_id: int | None, limit: int = 30) -> list[int]:
    selected: list[int] = []

    def add(country_id: int | None) -> None:
        if country_id is not None and country_id in countries and country_id not in selected:
            selected.append(country_id)

    add(player_id)
    for row in rankings:
        add(row.get("country_id"))
        if len(selected) >= limit:
            return selected
    for key, _ in sorted(countries.items(), key=lambda item: item[1].get("gdp") or -1, reverse=True):
        add(key)
        if len(selected) >= limit:
            return selected
    for key, _ in sorted(countries.items(), key=lambda item: item[1].get("population") or -1, reverse=True):
        add(key)
        if len(selected) >= limit:
            return selected
    return selected


def parse_all_states(txt: str, countries: dict[int, dict]) -> tuple[list[dict], dict[int, int]]:
    states_block = database_block(txt, "states")
    if not states_block:
        return [], {}
    states = []
    state_to_country = {}
    for key, open_pos, close in iter_top_blocks(states_block, 0, len(states_block)):
        if not key.isdigit():
            continue
        block = states_block[open_pos + 1 : close]
        country = top_value(block, "country")
        if not country or not country.isdigit():
            continue
        country_id = int(country)
        state_id = int(key)
        state_to_country[state_id] = country_id
        country_row = countries.get(country_id, {})
        states.append(
            {
                "country_id": country_id,
                "tag": country_row.get("tag", ""),
                "state_id": state_id,
                "region": top_value(block, "state_region") or "",
                "capital": top_value(block, "capital") or "",
                "arable_land": num(top_value(block, "arable_land")),
                "incorporation": num(top_value(block, "incorporation")),
                "infrastructure": num(top_value(block, "infrastructure")),
                "infrastructure_usage": num(top_value(block, "infrastructure_usage")),
                "trade_capacity": num(top_value(block, "trade_capacity")),
                "trade_capacity_usage": num(top_value(block, "trade_capacity_usage")),
                "devastation": num(top_value(block, "devastation")),
                "bureaucracy_cost": num(top_value(block, "base_pop_bureaucracy_cost")),
                "previous_country": top_value(block, "previous_country_definition") or "",
                "last_owner_change": top_value(block, "last_owner_change") or "",
            }
        )
    return states, state_to_country


def parse_states_for_country(txt: str, country_id: int) -> list[dict]:
    states_block = database_block(txt, "states")
    if not states_block:
        return []
    states = []
    for key, open_pos, close in iter_top_blocks(states_block, 0, len(states_block)):
        if not key.isdigit():
            continue
        block = states_block[open_pos + 1 : close]
        if top_value(block, "country") != str(country_id):
            continue
        states.append(
            {
                "state_id": int(key),
                "region": top_value(block, "state_region") or "",
                "arable_land": num(top_value(block, "arable_land")),
                "incorporation": num(top_value(block, "incorporation")),
                "infrastructure": num(top_value(block, "infrastructure")),
                "infrastructure_usage": num(top_value(block, "infrastructure_usage")),
                "bureaucracy_cost": num(top_value(block, "base_pop_bureaucracy_cost")),
                "previous_country": top_value(block, "previous_country_definition") or "",
                "last_owner_change": top_value(block, "last_owner_change") or "",
            }
        )
    return states


def parse_buildings_for_countries(txt: str, state_to_country: dict[int, int], countries: dict[int, dict], country_ids: set[int]) -> tuple[list[dict], list[dict]]:
    db = database_block(txt, "building_manager")
    if not db:
        return [], []
    rows = []
    aggregate: dict[tuple[int, str], dict] = {}
    for key, open_pos, close in iter_top_blocks(db, 0, len(db)):
        if not key.isdigit():
            continue
        block = db[open_pos + 1 : close]
        state = top_value(block, "state")
        if not state or not state.isdigit():
            continue
        state_id = int(state)
        country_id = state_to_country.get(state_id)
        if country_id not in country_ids:
            continue
        country_row = countries.get(country_id, {})
        building = top_value(block, "building") or top_value(block, "type") or ""
        levels = num(top_value(block, "levels") or top_value(block, "level") or "0") or 0
        staffing = num(top_value(block, "staffing"))
        goods_sales = num(top_value(block, "goods_sales"))
        goods_cost = num(top_value(block, "goods_cost"))
        profit = num(top_value(block, "profit_after_reserves"))
        row = {
            "country_id": country_id,
            "tag": country_row.get("tag", ""),
            "state_id": state_id,
            "building_id": int(key),
            "building": building,
            "levels": levels,
            "staffing": staffing,
            "throughput": num(top_value(block, "throughput")),
            "salary_rate": num(top_value(block, "salary_rate")),
            "goods_sales": goods_sales,
            "goods_cost": goods_cost,
            "profit_after_reserves": profit,
            "cash_reserves": num(top_value(block, "cash_reserves")),
            "active": top_value(block, "active") or "",
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
    db = database_block(txt, "building_manager")
    if not db:
        return []
    rows = []
    for key, open_pos, close in iter_top_blocks(db, 0, len(db)):
        if not key.isdigit():
            continue
        block = db[open_pos + 1 : close]
        state = top_value(block, "state")
        if not state or int(state) not in state_ids:
            continue
        rows.append(
            {
                "building_id": int(key),
                "state_id": int(state),
                "building": top_value(block, "building") or top_value(block, "type") or "",
                "levels": num(top_value(block, "levels") or top_value(block, "level") or "0") or 0,
                "cash_reserves": num(top_value(block, "cash_reserves")),
            }
        )
    return rows


def parse_pops_for_countries(
    txt: str,
    state_to_country: dict[int, int],
    countries: dict[int, dict],
    country_ids: set[int],
    culture_map: dict[str, str],
    progress=None,
) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
    db = database_block(txt, "pops")
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
        state = top_value(block, "location") or top_value(block, "state")
        if not state or not state.isdigit():
            continue
        country_id = state_to_country.get(int(state))
        if country_id not in country_ids:
            continue

        country_row = countries.get(country_id, {})
        workforce = int(num(top_value(block, "workforce")) or 0)
        dependents = int(num(top_value(block, "dependents")) or 0)
        size = int(num(top_value(block, "size")) or workforce + dependents)
        if size <= 0:
            continue
        pop_type = top_value(block, "type") or top_value(block, "pop_type") or "unknown"
        raw_culture = top_value(block, "culture") or "unknown"
        culture = culture_map.get(raw_culture, raw_culture)
        religion = top_value(block, "religion") or "unknown"
        workplace = top_value(block, "workplace") or ""
        loyalist_balance = int(num(top_value(block, "loyalists_and_radicals")) or 0)
        loyalists = int(num(top_value(block, "loyalists")) or 0)
        radicals = int(num(top_value(block, "radicals")) or 0)
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
    db = database_block(txt, "pops")
    if not db:
        return {"total": 0, "rows": [], "by_type": [], "by_culture": [], "by_religion": []}

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
        state = top_value(block, "location") or top_value(block, "state")
        country = top_value(block, "country")
        if state_ids:
            if not state or not state.isdigit() or int(state) not in state_ids:
                continue
        elif country_id is not None and country != str(country_id):
            continue

        workforce = int(num(top_value(block, "workforce")) or 0)
        dependents = int(num(top_value(block, "dependents")) or 0)
        size = int(num(top_value(block, "size")) or workforce + dependents)
        if size <= 0:
            continue

        pop_type = top_value(block, "type") or top_value(block, "pop_type") or "unknown"
        raw_culture = top_value(block, "culture") or "unknown"
        culture = (culture_map or {}).get(raw_culture, raw_culture)
        religion = top_value(block, "religion") or "unknown"
        workplace = top_value(block, "workplace") or ""

        row_loyalists = int(num(top_value(block, "loyalists")) or 0)
        row_radicals = int(num(top_value(block, "radicals")) or 0)
        loyalist_balance = int(num(top_value(block, "loyalists_and_radicals")) or 0)
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


def parse_laws_for_countries(txt: str, countries: dict[int, dict], country_ids: set[int]) -> list[dict]:
    rows = []
    for law, country in re.findall(r"law=([A-Za-z0-9_\-]+)\s+country=(\d+)\s+active=yes", txt):
        country_id = int(country)
        if country_id not in country_ids:
            continue
        rows.append(
            {
                "country_id": country_id,
                "tag": countries.get(country_id, {}).get("tag", ""),
                "law": LAW_NAMES.get(law, law),
                "raw_law": law,
            }
        )
    return sorted(rows, key=lambda row: (row["tag"], row["raw_law"]))


def parse_interest_groups_for_countries(txt: str, countries: dict[int, dict], country_ids: set[int]) -> list[dict]:
    db = database_block(txt, "interest_groups")
    if not db:
        return []
    rows = []
    for key, open_pos, close in iter_top_blocks(db, 0, len(db)):
        if not key.isdigit():
            continue
        block = db[open_pos + 1 : close]
        country = top_value(block, "country")
        if not country or not country.isdigit():
            continue
        country_id = int(country)
        if country_id not in country_ids:
            continue
        rows.append(
            {
                "country_id": country_id,
                "tag": countries.get(country_id, {}).get("tag", ""),
                "interest_group_id": int(key),
                "definition": (top_value(block, "definition") or top_value(block, "name") or "").strip('"'),
                "clout": num(top_value(block, "clout")),
                "political_strength": num(top_value(block, "political_strength")),
                "loyalists_political_strength": num(top_value(block, "loyalists_political_strength")),
                "radicals_political_strength": num(top_value(block, "radicals_political_strength")),
                "in_government": top_value(block, "in_government") or "",
                "approval": num(top_value(block, "approval")),
            }
        )
    return sorted(rows, key=lambda row: (row["tag"], -(row["clout"] or 0), row["definition"]))


def parse_technology_for_countries(txt: str, countries: dict[int, dict], country_ids: set[int]) -> list[dict]:
    db = database_block(txt, "technology")
    if not db:
        return []
    rows = []
    for key, open_pos, close in iter_top_blocks(db, 0, len(db)):
        if not key.isdigit():
            continue
        block = db[open_pos + 1 : close]
        country = top_value(block, "country")
        if not country or not country.isdigit():
            continue
        country_id = int(country)
        if country_id not in country_ids:
            continue
        acquired = list_value(block, "acquired_technologies")
        spreading = list_value(block, "currently_spreading_technologies")
        rows.append(
            {
                "country_id": country_id,
                "tag": countries.get(country_id, {}).get("tag", ""),
                "research_technology": top_value(block, "research_technology") or "",
                "acquired_count": len(acquired),
                "spreading_count": len(spreading),
                "acquired_technologies": ";".join(acquired),
                "currently_spreading": ";".join(spreading),
            }
        )
    return sorted(rows, key=lambda row: (row["tag"], row["research_technology"]))


def parse_relations_for_countries(txt: str, countries: dict[int, dict], country_ids: set[int]) -> list[dict]:
    db = database_block(txt, "relations")
    if not db:
        return []
    rows = []
    for key, open_pos, close in iter_top_blocks(db, 0, len(db)):
        if not key.isdigit():
            continue
        block = db[open_pos + 1 : close]
        first_block = subblock(block, "first")
        second_block = subblock(block, "second")
        first = top_value(first_block, "country")
        second = top_value(second_block, "country")
        if not first or not second or not first.isdigit() or not second.isdigit():
            continue
        first_id = int(first)
        second_id = int(second)
        if first_id not in country_ids and second_id not in country_ids:
            continue
        relation_value = num(top_value(block, "relations"))
        improve = num(top_value(block, "improve_relations"))
        tension = num(top_value(block, "tension"))
        hostility = ";".join(list_value(block, "hostility"))
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
                    "obligation": top_value(side_block, "obligation") or "",
                    "partner_obligation": top_value(partner_block, "obligation") or "",
                    "truce": top_value(block, f"{side}_truce") or "",
                    "last_action": top_value(side_block, "last_action") or "",
                }
            )
    return sorted(rows, key=lambda row: (row["tag"], row["partner_tag"], row["relation_id"]))


def parse_pacts_for_countries(txt: str, countries: dict[int, dict], country_ids: set[int]) -> list[dict]:
    db = database_block(txt, "pacts")
    if not db:
        return []
    rows = []
    for key, open_pos, close in iter_top_blocks(db, 0, len(db)):
        if not key.isdigit():
            continue
        block = db[open_pos + 1 : close]
        targets = subblock(block, "targets")
        first = top_value(targets, "first")
        second = top_value(targets, "second")
        if not first or not second or not first.isdigit() or not second.isdigit():
            continue
        first_id = int(first)
        second_id = int(second)
        if first_id not in country_ids and second_id not in country_ids:
            continue
        action = top_value(block, "action") or ""
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
                    "start_date": top_value(block, "start_date") or "",
                    "forced_duration": num(top_value(block, "forced_duration")),
                    "liberty_desire": num(top_value(block, "liberty_desire")),
                }
            )
    return sorted(rows, key=lambda row: (row["tag"], row["action"], row["partner_tag"]))


def parse_companies_for_countries(txt: str, countries: dict[int, dict], country_ids: set[int]) -> list[dict]:
    db = database_block(txt, "companies")
    if not db:
        return []
    rows = []
    for key, open_pos, close in iter_top_blocks(db, 0, len(db)):
        if not key.isdigit():
            continue
        block = db[open_pos + 1 : close]
        country = top_value(block, "country")
        if not country or not country.isdigit():
            continue
        country_id = int(country)
        if country_id not in country_ids:
            continue
        prod = trend_stats(block, "productivity_trend")
        rows.append(
            {
                "company_id": int(key),
                "country_id": country_id,
                "tag": countries.get(country_id, {}).get("tag", ""),
                "company_type": top_value(block, "company_type") or top_value(block, "type") or "",
                "building_id": top_value(block, "building") or "",
                "state_region": top_value(block, "state_region") or "",
                "prosperity": num(top_value(block, "prosperity")),
                "ceo": top_value(block, "ceo") or "",
                "productivity_start": prod["start"],
                "productivity_latest": prod["latest"],
                "productivity_change": prod["change"],
                "productivity_change_pct": prod["change_pct"],
                "productivity_samples": prod["samples"],
            }
        )
    return sorted(rows, key=lambda row: (row["tag"], -(row.get("prosperity") or 0), row["company_type"]))


def parse_wars_for_countries(txt: str, countries: dict[int, dict], country_ids: set[int]) -> tuple[list[dict], list[dict]]:
    db = database_block(txt, "war_manager")
    if not db:
        return [], []
    war_rows = []
    participant_rows = []
    for key, open_pos, close in iter_top_blocks(db, 0, len(db)):
        if not key.isdigit():
            continue
        block = db[open_pos + 1 : close]
        war_id = int(key)
        participants_block = subblock(block, "war_participants") or ""
        participants = []
        for match in re.finditer(r"\{\s*diplomatic_play=.*?\}", participants_block, re.S):
            item = match.group(0)
            country = top_value(item, "country")
            if not country or not country.isdigit():
                continue
            country_id = int(country)
            participants.append(country_id)
            if country_id in country_ids:
                participant_rows.append(
                    {
                        "war_id": war_id,
                        "country_id": country_id,
                        "tag": countries.get(country_id, {}).get("tag", ""),
                        "diplomatic_play": top_value(item, "diplomatic_play") or "",
                        "war_support": num(top_value(item, "war_support")),
                        "initial_war_support": num(top_value(item, "initial_war_support")),
                        "battles_war_support_delta": num(top_value(item, "battles_war_support_delta")),
                        "exhaustion_war_support_delta": num(top_value(item, "exhaustion_war_support_delta")),
                        "situations_war_support_delta": num(top_value(item, "situations_war_support_delta")),
                        "violator": top_value(item, "violator") or "",
                    }
                )
        involved_major = [country_id for country_id in participants if country_id in country_ids]
        attacker_deal = subblock(block, "attacker_peace_deal")
        defender_deal = subblock(block, "defender_peace_deal")
        attacker_peace_country = top_value(attacker_deal, "country") or ""
        defender_peace_country = top_value(defender_deal, "country") or ""
        if not involved_major and attacker_peace_country.isdigit() and int(attacker_peace_country) in country_ids:
            involved_major.append(int(attacker_peace_country))
        if not involved_major and defender_peace_country.isdigit() and int(defender_peace_country) in country_ids:
            involved_major.append(int(defender_peace_country))
        if not involved_major:
            continue
        peace_date = top_value(block, "peace_date") or ""
        status = "active" if not peace_date or peace_date == "1.1.1" else "ended"
        if top_value(block, "dead") == "yes" and status == "active":
            status = "historical_unresolved_date"
        war_rows.append(
            {
                "war_id": war_id,
                "status": status,
                "diplomatic_play": top_value(block, "diplomatic_play") or "",
                "start_date": top_value(block, "start_date") or "",
                "peace_date": peace_date,
                "days_since_exhaustion": num(top_value(block, "days_since_exhaustion")),
                "participant_country_ids": ";".join(str(country_id) for country_id in participants),
                "participant_tags": ";".join(countries.get(country_id, {}).get("tag", str(country_id)) for country_id in participants),
                "major_country_ids": ";".join(str(country_id) for country_id in involved_major),
                "major_tags": ";".join(countries.get(country_id, {}).get("tag", str(country_id)) for country_id in involved_major),
                "attacker_peace_country": countries.get(int(attacker_peace_country), {}).get("tag", attacker_peace_country) if attacker_peace_country.isdigit() else attacker_peace_country,
                "defender_peace_country": countries.get(int(defender_peace_country), {}).get("tag", defender_peace_country) if defender_peace_country.isdigit() else defender_peace_country,
                "attacker_last_proposal_date": top_value(attacker_deal, "last_proposal_date") or "",
                "defender_last_proposal_date": top_value(defender_deal, "last_proposal_date") or "",
            }
        )
    return (
        sorted(war_rows, key=lambda row: (row["status"] != "active", row["start_date"], row["war_id"])),
        sorted(participant_rows, key=lambda row: (row["tag"], row["war_id"])),
    )


def parse_war_goals_for_countries(txt: str, countries: dict[int, dict], country_ids: set[int]) -> list[dict]:
    db = database_block(txt, "war_goal_manager")
    if not db:
        return []
    rows = []
    for key, open_pos, close in iter_top_blocks(db, 0, len(db)):
        if not key.isdigit():
            continue
        block = db[open_pos + 1 : close]
        holder = top_value(block, "holder") or ""
        creator = top_value(block, "creator") or ""
        target = subblock(block, "target") or ""
        target_country = top_value(target, "country") or ""
        ids = [value for value in (holder, creator, target_country) if value.isdigit()]
        if not any(int(value) in country_ids for value in ids):
            continue
        rows.append(
            {
                "war_goal_id": int(key),
                "type": top_value(block, "type") or "",
                "holder_id": holder,
                "holder_tag": countries.get(int(holder), {}).get("tag", holder) if holder.isdigit() else holder,
                "creator_id": creator,
                "creator_tag": countries.get(int(creator), {}).get("tag", creator) if creator.isdigit() else creator,
                "target_country_id": target_country,
                "target_country_tag": countries.get(int(target_country), {}).get("tag", target_country) if target_country.isdigit() else target_country,
                "target_state": top_value(target, "state") or "",
                "target_region": top_value(target, "region") or "",
                "target_other": top_value(target, "other") or "",
                "diplomatic_play": top_value(block, "diplomatic_play") or "",
                "demand_type": top_value(block, "demand_type") or "",
                "status": top_value(block, "status") or "",
                "initial_war_goal": top_value(block, "initial_war_goal") or "",
            }
        )
    return sorted(rows, key=lambda row: (row["diplomatic_play"], row["holder_tag"], row["type"]))


def parse_diplomatic_plays_for_countries(txt: str, countries: dict[int, dict], country_ids: set[int]) -> tuple[list[dict], list[dict]]:
    db = database_block(txt, "diplomatic_plays")
    if not db:
        return [], []
    play_rows = []
    cost_rows = []
    for key, open_pos, close in iter_top_blocks(db, 0, len(db)):
        if not key.isdigit():
            continue
        block = db[open_pos + 1 : close]
        ids = set()
        for value in [top_value(block, "initiator"), top_value(block, "target"), *list_value(block, "initiators"), *list_value(block, "targets"), *list_value(block, "involved")]:
            if value and value.isdigit():
                ids.add(int(value))
        if not ids.intersection(country_ids):
            continue
        country_records = subblock(block, "country_records") or ""
        for item in iter_anonymous_blocks(country_records):
            country = top_value(item, "country")
            if not country or not country.isdigit():
                continue
            country_id = int(country)
            if country_id not in country_ids:
                continue
            material_cost = sum(float(value) for value in re.findall(r"value=(-?\d+(?:\.\d+)?)", subblock(item, "materiel_cost_of_war") or ""))
            cost_rows.append(
                {
                    "diplomatic_play": int(key),
                    "country_id": country_id,
                    "tag": countries.get(country_id, {}).get("tag", ""),
                    "side": top_value(item, "side") or "",
                    "materiel_cost_of_war": material_cost,
                    "wage_cost_of_war": num(top_value(item, "wage_cost_of_war")),
                    "total_known_war_cost": material_cost + (num(top_value(item, "wage_cost_of_war")) or 0),
                }
            )
        play_rows.append(
            {
                "diplomatic_play": int(key),
                "type": top_value(block, "type") or "",
                "state": top_value(block, "state") or "",
                "strategic_region": top_value(block, "strategic_region") or "",
                "initiator_id": top_value(block, "initiator") or "",
                "initiator_tag": countries.get(int(top_value(block, "initiator") or -1), {}).get("tag", top_value(block, "initiator") or ""),
                "target_id": top_value(block, "target") or "",
                "target_tag": countries.get(int(top_value(block, "target") or -1), {}).get("tag", top_value(block, "target") or ""),
                "initiator_side_tags": ";".join(countries.get(int(value), {}).get("tag", value) for value in list_value(block, "initiators") if value.isdigit()),
                "target_side_tags": ";".join(countries.get(int(value), {}).get("tag", value) for value in list_value(block, "targets") if value.isdigit()),
                "involved_tags": ";".join(countries.get(int(value), {}).get("tag", value) for value in list_value(block, "involved") if value.isdigit()),
                "war": top_value(block, "war") or "",
                "escalation": num(top_value(block, "escalation")),
                "start_date": top_value(block, "start_date") or "",
                "end_date": top_value(block, "end_date") or "",
            }
        )
    return (
        sorted(play_rows, key=lambda row: (row["end_date"] in {"", "1.1.1"}, row["start_date"], row["diplomatic_play"]), reverse=True),
        sorted(cost_rows, key=lambda row: (row["tag"], row["diplomatic_play"])),
    )


def parse_military_formations_for_countries(txt: str, countries: dict[int, dict], country_ids: set[int]) -> list[dict]:
    db = database_block(txt, "military_formation_manager")
    if not db:
        return []
    rows = []
    for key, open_pos, close in iter_top_blocks(db, 0, len(db)):
        if not key.isdigit():
            continue
        block = db[open_pos + 1 : close]
        country = top_value(block, "country")
        if not country or not country.isdigit() or int(country) not in country_ids:
            continue
        current = subblock(block, "current_location") or ""
        target = subblock(block, "target_location") or ""
        rows.append(
            {
                "formation_id": int(key),
                "country_id": int(country),
                "tag": countries.get(int(country), {}).get("tag", ""),
                "type": top_value(block, "type") or "",
                "ordinal_number": top_value(block, "ordinal_number") or "",
                "home_hq": top_value(block, "home_hq") or "",
                "supply_hub": top_value(block, "supply_hub") or "",
                "organization": num(top_value(block, "organization")),
                "supply": num(top_value(block, "supply")),
                "delivered_supply": num(top_value(block, "delivered_supply")),
                "supply_priority": top_value(block, "supply_priority") or "",
                "flags": ";".join(list_value(block, "flags")),
                "default_unit_types": ";".join(list_value(block, "default_unit_types")),
                "unit_type_count": len(list_value(block, "default_unit_types")),
                "mobilization_options": ";".join(list_value(block, "active_mobilization_options")),
                "mobilization_option_count": len(list_value(block, "active_mobilization_options")),
                "current_location_type": top_value(current, "type") or "",
                "current_location_id": top_value(current, "identity") or "",
                "target_location_type": top_value(target, "type") or "",
                "target_location_id": top_value(target, "identity") or "",
                "creation_date": top_value(block, "creation_date") or "",
                "ai_tag": top_value(block, "ai_tag") or "",
            }
        )
    return sorted(rows, key=lambda row: (row["tag"], row["type"], row["formation_id"]))


def battle_side_stats(side_block: str | None) -> dict[str, object]:
    block = side_block or ""
    stats = subblock(block, "statistics") or ""
    return {
        "country": top_value(block, "country") or "",
        "formation": top_value(block, "formation") or "",
        "commander": top_value(block, "commander") or "",
        "order_type": top_value(block, "order_type") or "",
        "battle_condition": top_value(block, "battle_condition") or "",
        "dead": sum(int(value) for value in re.findall(r"num_dead=(\d+)", stats)),
        "wounded": sum(int(value) for value in re.findall(r"num_wounded=(\d+)", stats)),
        "demoralized": sum(int(value) for value in re.findall(r"num_demoralized=(\d+)", stats)),
    }


def parse_battles_for_countries(
    txt: str,
    countries: dict[int, dict],
    country_ids: set[int],
    culture_map: dict[str, str],
    progress=None,
) -> tuple[list[dict], list[dict]]:
    db = database_block(txt, "battle_manager")
    if not db:
        return [], []
    battle_rows = []
    casualty_rows = []
    entries = [(key, open_pos, close) for key, open_pos, close in iter_top_blocks(db, 0, len(db)) if key.isdigit()]
    total_entries = max(len(entries), 1)
    last_bucket = -1
    for index, (key, open_pos, close) in enumerate(entries):
        if progress and (index % 250 == 0 or index + 1 == len(entries)):
            bucket = int((index + 1) * 100 / total_entries)
            if bucket != last_bucket:
                progress(bucket, f"扫描战斗条目 {index + 1:,}/{len(entries):,}")
                last_bucket = bucket
        if not key.isdigit():
            continue
        block = db[open_pos + 1 : close]
        data = subblock(block, "battle_data") or ""
        attacker = battle_side_stats(subblock(data, "attacker"))
        defender = battle_side_stats(subblock(data, "defender"))
        side_ids = [int(v) for v in (attacker["country"], defender["country"]) if str(v).isdigit()]
        if not any(country_id in country_ids for country_id in side_ids):
            continue
        name_match = re.search(r'key="STATE_REGION_NAME"\s+value="([^"]+)"', block)
        battle_rows.append(
            {
                "battle_id": int(key),
                "war_id": top_value(block, "war") or "",
                "front": top_value(block, "front") or "",
                "type": top_value(block, "type") or "",
                "state_region": name_match.group(1) if name_match else "",
                "province": top_value(block, "province") or "",
                "attacker_country_id": attacker["country"],
                "attacker_tag": countries.get(int(attacker["country"]), {}).get("tag", attacker["country"]) if str(attacker["country"]).isdigit() else attacker["country"],
                "defender_country_id": defender["country"],
                "defender_tag": countries.get(int(defender["country"]), {}).get("tag", defender["country"]) if str(defender["country"]).isdigit() else defender["country"],
                "status": top_value(block, "status") or "",
                "start_date": top_value(block, "start_date") or "",
                "end_date": top_value(block, "end_date") or "",
                "attacker_start_battalions": num(top_value(block, "attacker_start_battalions")),
                "defender_start_battalions": num(top_value(block, "defender_start_battalions")),
                "attacker_starting_manpower": num(top_value(block, "attacker_starting_manpower")),
                "defender_starting_manpower": num(top_value(block, "defender_starting_manpower")),
                "attacker_ending_manpower": num(top_value(block, "attacker_ending_manpower")),
                "defender_ending_manpower": num(top_value(block, "defender_ending_manpower")),
                "attacker_dead": attacker["dead"],
                "attacker_wounded": attacker["wounded"],
                "defender_dead": defender["dead"],
                "defender_wounded": defender["wounded"],
                "num_captured_provinces": num(top_value(block, "num_captured_provinces")),
                "capturing_country": top_value(block, "capturing_country") or "",
                "lost_provinces_country": top_value(block, "lost_provinces_country") or "",
            }
        )
        for side_name, side_block in (("attacker", subblock(data, "attacker")), ("defender", subblock(data, "defender"))):
            if not side_block:
                continue
            country = top_value(side_block, "country") or ""
            if not country.isdigit() or int(country) not in country_ids:
                continue
            stats = subblock(side_block, "statistics") or ""
            for item in iter_anonymous_blocks(stats):
                culture = top_value(item, "culture") or ""
                casualty_rows.append(
                    {
                        "battle_id": int(key),
                        "war_id": top_value(block, "war") or "",
                        "side": side_name,
                        "country_id": int(country),
                        "tag": countries.get(int(country), {}).get("tag", ""),
                        "culture": culture_map.get(culture, culture),
                        "raw_culture": culture,
                        "dead": int(num(top_value(item, "num_dead")) or 0),
                        "wounded": int(num(top_value(item, "num_wounded")) or 0),
                        "demoralized": int(num(top_value(item, "num_demoralized")) or 0),
                    }
                )
    if progress:
        progress(100, f"战斗扫描完成，可读战斗 {len(battle_rows):,}")
    return (
        sorted(battle_rows, key=lambda row: (row["war_id"], row["start_date"], row["battle_id"])),
        sorted(casualty_rows, key=lambda row: (row["tag"], row["war_id"], row["battle_id"], row["side"])),
    )


def pct(value) -> str:
    if value is None or value == "":
        return "NA"
    return f"{float(value) * 100:.1f}%"


def nice_token(value) -> str:
    if value is None or value == "":
        return "NA"
    text = str(value)
    for prefix in ("building_", "law_", "ig_", "gov_", "pm_", "decree_", "state_trait_", "lgbtq_"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    return text.replace("_", " ")


def rows_for(rows: list[dict], country_id: int) -> list[dict]:
    return [row for row in rows if row.get("country_id") == country_id]


def top_rows(rows: list[dict], key: str, limit: int = 5) -> list[dict]:
    return sorted(rows, key=lambda row: row.get(key) or 0, reverse=True)[:limit]


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


def summarize_building_categories(buildings: list[dict]) -> list[dict]:
    totals: dict[str, dict] = {}
    for row in buildings:
        category = building_category(str(row.get("building", "")))
        item = totals.setdefault(category, {"category": category, "levels": 0, "staffing": 0, "profit": 0})
        item["levels"] += row.get("levels") or 0
        item["staffing"] += row.get("staffing") or 0
        item["profit"] += row.get("profit_after_reserves") or 0
    return sorted(totals.values(), key=lambda row: row["levels"], reverse=True)


def social_reading(country: dict, pop: dict | None, cultures: list[dict], types: list[dict], igs: list[dict]) -> list[str]:
    notes = []
    sol = country.get("sol")
    literacy = country.get("literacy")
    if sol is not None:
        if sol >= 20:
            notes.append("生活水平处在高位，社会整合主要压力不在生存线，而在政治参与、福利分配和身份承认。")
        elif sol >= 10:
            notes.append("生活水平处在中间带，国家仍能维持基本秩序，但工资、税负和商品短缺容易转化为政治压力。")
        else:
            notes.append("生活水平偏低，社会冲突更可能围绕粮食、住房、工资和税收展开。")
    if literacy is not None:
        if literacy >= 0.6:
            notes.append("识字率较高，官僚、技术、公共舆论和改革运动的扩散能力较强。")
        elif literacy >= 0.3:
            notes.append("识字率处在过渡阶段，现代部门会增长，但传统地方社会仍有很强惯性。")
        else:
            notes.append("识字率偏低，国家能力、产业升级和政治动员都会受教育结构限制。")
    if pop:
        loyalists = pop.get("loyalists") or 0
        radicals = pop.get("radicals") or 0
        total = pop.get("population_detail") or country.get("population") or 0
        if total:
            radical_share = radicals / total
            loyalist_share = loyalists / total
            if radical_share > loyalist_share * 1.3 and radicals > 100_000:
                notes.append("激进派明显压过效忠派，制度合法性和生活条件已经形成可见张力。")
            elif loyalist_share > radical_share * 1.3 and loyalists > 100_000:
                notes.append("效忠派基础较厚，现行国家秩序短期内有较强承压能力。")
            elif radicals or loyalists:
                notes.append("效忠与激进力量相对接近，社会方向会更依赖经济周期、战争和改革节奏。")
    if cultures:
        top = cultures[0]
        share = top.get("share") or 0
        if share >= 0.8:
            notes.append(f"文化结构高度集中，主体文化是 {top.get('dimension')}，身份政治成本相对较低。")
        elif share >= 0.5:
            notes.append(f"存在清晰主体文化 {top.get('dimension')}，但少数文化已经足以影响治理和同化政策。")
        else:
            notes.append("文化结构多元，没有单一文化压倒性主导，国家整合更依赖制度包容和地方治理。")
    if types:
        top_type = types[0].get("dimension")
        notes.append(f"最大职业群体是 {nice_token(top_type)}，这会决定税基、消费结构和政治诉求的底色。")
    if igs:
        top_ig = igs[0]
        notes.append(f"最强利益集团是 {nice_token(top_ig.get('definition') or '未知集团')}，其影响力会塑造改革阻力和政府稳定性。")
    return notes or ["当前可读字段不足，暂时只能给出谨慎的数据描述。"]


def write_system_document(
    path: Path,
    out: Path,
    meta_info: dict,
    countries_rows: list[dict],
    major_states: list[dict],
    building_summary: list[dict],
    pop_summary: list[dict],
    pop_by_type: list[dict],
    pop_by_culture: list[dict],
    pop_by_religion: list[dict],
    law_rows: list[dict],
    ig_rows: list[dict],
    tech_rows: list[dict],
    relation_rows: list[dict],
    pact_rows: list[dict],
    company_rows: list[dict],
    war_rows: list[dict],
    war_participant_rows: list[dict],
    diplomatic_play_rows: list[dict],
    war_cost_rows: list[dict],
    war_goal_rows: list[dict],
    military_formation_rows: list[dict],
    battle_rows: list[dict],
    battle_casualty_rows: list[dict],
) -> None:
    lines = [
        "# 维多利亚 3 主要国家体系化档案",
        "",
        "## 文档定位",
        "",
        f"- 存档：`{path.name}`",
        f"- 游戏日期：{meta_info['date']}",
        f"- 覆盖对象：玩家国家优先，再按威望/GDP/人口筛选出的 {len(countries_rows)} 个主要国家",
        "- 读法：先看“世界总览”，再看单个国家档案；CSV 表保留完整机器数据。",
        "",
        "## 世界总览",
        "",
    ]
    total_gdp = sum(row.get("gdp") or 0 for row in countries_rows)
    total_pop = sum(row.get("population") or 0 for row in countries_rows)
    lines.extend(
        [
            f"- 主要国家合计 GDP：{fmt(total_gdp, 2)}",
            f"- 主要国家合计人口：{fmt(total_pop, 2)}",
            f"- 平均生活水平：{sol_text(sum((row.get('sol') or 0) for row in countries_rows) / len(countries_rows)) if countries_rows else 'NA'}",
            f"- 平均识字率：{pct(sum((row.get('literacy') or 0) for row in countries_rows) / len(countries_rows)) if countries_rows else 'NA'}",
            "",
            "### 主要国家对照",
            "",
        ]
    )
    overview = []
    for row in countries_rows:
        overview.append(
            {
                "order": row["selection_order"],
                "tag": row["tag"],
                "rank": row["power_rank"],
                "gdp": fmt(row["gdp"], 2),
                "gdp_share": pct(row.get("major_gdp_share")),
                "gdp_change": fmt(row.get("gdp_change"), 2),
                "pop": fmt(row["population"], 2),
                "gdp_pc": fmt(row["gdp_per_capita"], 2) if row.get("gdp_per_capita") != "" else "NA",
                "literacy": pct(row["literacy"]),
                "sol": sol_text(row["sol"]),
                "states": row["states"],
            }
        )
    lines.extend(md_table(overview, [("序", "order"), ("国家", "tag"), ("等级", "rank"), ("GDP", "gdp"), ("GDP占比", "gdp_share"), ("GDP变化", "gdp_change"), ("人口", "pop"), ("人均GDP", "gdp_pc"), ("识字率", "literacy"), ("生活水平", "sol"), ("州数", "states")], limit=30))
    lines.extend(["", "## 国家档案", ""])

    pop_by_id = {row["country_id"]: row for row in pop_summary}
    tech_by_id = {row["country_id"]: row for row in tech_rows}
    for country in countries_rows:
        cid = country["country_id"]
        tag = country["tag"]
        states = rows_for(major_states, cid)
        buildings = rows_for(building_summary, cid)
        types = top_rows(rows_for(pop_by_type, cid), "population", 8)
        cultures = top_rows(rows_for(pop_by_culture, cid), "population", 8)
        religions = top_rows(rows_for(pop_by_religion, cid), "population", 8)
        laws = rows_for(law_rows, cid)
        igs = top_rows(rows_for(ig_rows, cid), "clout", 8)
        relations = rows_for(relation_rows, cid)
        pacts = rows_for(pact_rows, cid)
        companies = rows_for(company_rows, cid)
        war_parts = rows_for(war_participant_rows, cid)
        country_wars = [war for war in war_rows if str(cid) in str(war.get("major_country_ids", "")).split(";")]
        plays = [row for row in diplomatic_play_rows if str(tag) in str(row.get("involved_tags", "")).split(";") or row.get("initiator_tag") == tag or row.get("target_tag") == tag]
        war_costs = rows_for(war_cost_rows, cid)
        goals = [row for row in war_goal_rows if row.get("holder_tag") == tag or row.get("creator_tag") == tag or row.get("target_country_tag") == tag]
        formations = rows_for(military_formation_rows, cid)
        battles = [row for row in battle_rows if row.get("attacker_tag") == tag or row.get("defender_tag") == tag]
        casualties = rows_for(battle_casualty_rows, cid)
        pop = pop_by_id.get(cid)
        tech = tech_by_id.get(cid, {})
        infra_stressed = [s for s in states if (s.get("infrastructure_usage") or 0) > (s.get("infrastructure") or 0)]
        incorporated = [s for s in states if (s.get("incorporation") or 0) >= 1]
        categories = summarize_building_categories(buildings)
        best_rel = top_rows([r for r in relations if r.get("relations") is not None], "relations", 5)
        worst_rel = sorted([r for r in relations if r.get("relations") is not None], key=lambda row: row.get("relations") or 0)[:5]

        lines.extend(
            [
                f"### {country['selection_order']}. {tag}",
                "",
                "#### 基本位置",
                "",
                f"- 国家ID：{cid}",
                f"- 排名/等级：{country.get('power_rank') or 'NA'}；威望排名：{country.get('prestige_rank') or 'NA'}；威望：{fmt(country.get('prestige'), 2)}",
                f"- GDP：{fmt(country.get('gdp'), 2)}；主要国家GDP占比：{pct(country.get('major_gdp_share'))}；全世界GDP占比：{pct(country.get('world_gdp_share'))}",
                f"- GDP历史：起点 {fmt(country.get('gdp_start'), 2)}，变化 {fmt(country.get('gdp_change'), 2)}，变化率 {pct(country.get('gdp_change_pct'))}",
                f"- 人口：{fmt(country.get('population'), 2)}；人均GDP：{fmt(country.get('gdp_per_capita'), 2) if country.get('gdp_per_capita') != '' else 'NA'}",
                f"- 生活水平：{sol_text(country.get('sol'))}，变化 {sol_text(country.get('sol_change'))}；识字率：{pct(country.get('literacy'))}，变化 {pct(country.get('literacy_change'))}；恶名：{fmt(country.get('infamy'), 2)}",
                f"- 政府：{nice_token(country.get('government'))}；市场：{country.get('market') or 'NA'}；首都州ID：{country.get('capital') or 'NA'}；合法性：{sol_text(country.get('legitimacy'))}",
                "",
                "#### 领土与基础设施",
                "",
                f"- 州数量：{len(states)}；已整合州：{len(incorporated)}；基建超载州：{len(infra_stressed)}；平均破坏度：{sol_text(sum((s.get('devastation') or 0) for s in states) / len(states)) if states else 'NA'}",
            ]
        )
        state_preview = [
            {
                "state": row.get("region") or row.get("state_id"),
                "infra": fmt(row.get("infrastructure"), 1),
                "used": fmt(row.get("infrastructure_usage"), 1),
                "inc": pct(row.get("incorporation")),
                "arable": fmt(row.get("arable_land"), 0),
                "dev": sol_text(row.get("devastation")),
            }
            for row in sorted(states, key=lambda s: (s.get("infrastructure_usage") or 0) - (s.get("infrastructure") or 0), reverse=True)[:8]
        ]
        if state_preview:
            lines.extend(md_table(state_preview, [("州/地区", "state"), ("基建", "infra"), ("使用", "used"), ("整合", "inc"), ("耕地", "arable"), ("破坏度", "dev")]))
        lines.extend(["", "#### 经济与建筑体系", ""])
        lines.append(f"- 建筑类型数：{len(buildings)}；建筑实例数：{country.get('building_entries')}")
        if categories:
            lines.extend(md_table([{"cat": c["category"], "levels": fmt(c["levels"], 0), "staff": fmt(c["staffing"], 1), "profit": fmt(c["profit"], 1)} for c in categories], [("部门", "cat"), ("等级", "levels"), ("雇佣", "staff"), ("利润", "profit")]))
        top_buildings = top_rows(buildings, "levels", 10)
        if top_buildings:
            lines.extend(["", "主要建筑："])
            lines.extend(md_table([{"building": nice_token(b["building"]), "levels": fmt(b["levels"], 0), "staff": fmt(b["staffing"], 1), "profit": fmt(b["profit_after_reserves"], 1)} for b in top_buildings], [("建筑", "building"), ("等级", "levels"), ("雇佣", "staff"), ("利润", "profit")]))
        if companies:
            lines.extend(["", "公司与企业："])
            lines.extend(md_table([{"company": nice_token(c["company_type"]), "region": nice_token(c["state_region"]), "prosperity": sol_text(c["prosperity"]), "prod": sol_text(c["productivity_latest"]), "change": sol_text(c["productivity_change"])} for c in companies[:10]], [("公司", "company"), ("地区", "region"), ("繁荣度", "prosperity"), ("生产率", "prod"), ("生产率变化", "change")]))
        lines.extend(["", "#### 人口、职业、文化、宗教", ""])
        if pop:
            lines.extend(
                [
                    f"- 人口明细合计：{fmt(pop.get('population_detail'), 2)}；劳动力：{fmt(pop.get('workforce'), 2)}；被扶养者：{fmt(pop.get('dependents'), 2)}",
                    f"- 效忠派：{fmt(pop.get('loyalists'), 2)}；激进派：{fmt(pop.get('radicals'), 2)}；无工作场所/未锚定人口：{fmt(pop.get('unanchored'), 2)}",
                ]
            )
        if types:
            lines.extend(md_table([{"d": nice_token(r["dimension"]), "pop": fmt(r["population"], 2), "share": pct(r["share"]), "rad": fmt(r["radicals"], 1), "loy": fmt(r["loyalists"], 1)} for r in types], [("职业", "d"), ("人口", "pop"), ("占比", "share"), ("激进", "rad"), ("效忠", "loy")]))
        if cultures:
            lines.extend(["", "文化构成："])
            lines.extend(md_table([{"d": r["dimension"], "pop": fmt(r["population"], 2), "share": pct(r["share"])} for r in cultures], [("文化", "d"), ("人口", "pop"), ("占比", "share")]))
        if religions:
            lines.extend(["", "宗教构成："])
            lines.extend(md_table([{"d": r["dimension"], "pop": fmt(r["population"], 2), "share": pct(r["share"])} for r in religions], [("宗教", "d"), ("人口", "pop"), ("占比", "share")]))
        lines.extend(["", "#### 法律、阶层与政治力量", ""])
        lines.append("- 现行法律：" + ("、".join(nice_token(row["law"]) for row in laws) if laws else "未读到"))
        if igs:
            lines.extend(md_table([{"ig": nice_token(r["definition"]), "clout": pct(r["clout"]), "approval": sol_text(r["approval"]), "gov": r["in_government"]} for r in igs], [("利益集团", "ig"), ("影响力", "clout"), ("认可", "approval"), ("执政", "gov")]))
        lines.extend(["", "#### 科技与现代化", ""])
        lines.append(f"- 当前研究：{nice_token(tech.get('research_technology'))}；已掌握科技数：{tech.get('acquired_count', 'NA')}；正在扩散：{tech.get('spreading_count', 'NA')}")
        if tech.get("currently_spreading"):
            lines.append(f"- 扩散科技：{', '.join(nice_token(item) for item in str(tech.get('currently_spreading')).split(';') if item)}")
        lines.extend(["", "#### 国际关系与外交结构", ""])
        lines.append(f"- 外交关系记录：{len(relations)}；条约/外交行动记录：{len(pacts)}")
        if best_rel:
            lines.extend(["", "关系较好对象："])
            lines.extend(md_table([{"p": r["partner_tag"], "rel": sol_text(r["relations"]), "tension": sol_text(r["tension"]), "last": r["last_action"]} for r in best_rel], [("对象", "p"), ("关系", "rel"), ("紧张", "tension"), ("最近行动", "last")]))
        if worst_rel:
            lines.extend(["", "关系较差对象："])
            lines.extend(md_table([{"p": r["partner_tag"], "rel": sol_text(r["relations"]), "tension": sol_text(r["tension"]), "last": r["last_action"]} for r in worst_rel], [("对象", "p"), ("关系", "rel"), ("紧张", "tension"), ("最近行动", "last")]))
        if pacts:
            lines.extend(["", "主要条约/外交行动："])
            lines.extend(md_table([{"p": r["partner_tag"], "action": nice_token(r["action"]), "start": r["start_date"], "liberty": sol_text(r["liberty_desire"])} for r in pacts[:10]], [("对象", "p"), ("类型", "action"), ("开始", "start"), ("自由欲", "liberty")]))
        lines.extend(["", "#### 战争与历史战争", ""])
        lines.append(f"- 相关战争记录：{len(country_wars)}；参战方记录：{len(war_parts)}；外交博弈：{len(plays)}；战争目标：{len(goals)}；战斗记录：{len(battles)}")
        if country_wars:
            lines.extend(md_table([{"id": w["war_id"], "status": w["status"], "start": w["start_date"], "peace": w["peace_date"], "majors": w["major_tags"], "parts": w["participant_tags"]} for w in country_wars[:10]], [("战争ID", "id"), ("状态", "status"), ("开始", "start"), ("结束", "peace"), ("主要国家", "majors"), ("参战方", "parts")]))
        if plays:
            lines.extend(["", "外交博弈/阵营："])
            lines.extend(md_table([{"id": p["diplomatic_play"], "type": nice_token(p["type"]), "region": nice_token(p["strategic_region"]), "init": p["initiator_side_tags"], "target": p["target_side_tags"], "war": p["war"]} for p in plays[:8]], [("博弈ID", "id"), ("类型", "type"), ("区域", "region"), ("进攻方阵营", "init"), ("目标方阵营", "target"), ("战争ID", "war")]))
        if goals:
            lines.extend(["", "战争目标："])
            lines.extend(md_table([{"type": nice_token(g["type"]), "holder": g["holder_tag"], "target": g["target_country_tag"], "region": nice_token(g["target_region"]), "status": g["status"]} for g in goals[:10]], [("目标", "type"), ("提出方", "holder"), ("目标国", "target"), ("区域", "region"), ("状态", "status")]))
        if formations:
            lines.extend(["", "军队/海军编成："])
            lines.extend(md_table([{"id": f["formation_id"], "type": f["type"], "org": sol_text(f["organization"]), "supply": sol_text(f["supply"]), "delivered": sol_text(f["delivered_supply"]), "units": nice_token(f["default_unit_types"]), "mob": f["mobilization_option_count"]} for f in formations[:10]], [("编成ID", "id"), ("类型", "type"), ("组织", "org"), ("补给", "supply"), ("已送补给", "delivered"), ("单位类型", "units"), ("动员选项", "mob")]))
        if war_parts:
            lines.extend(["", "战争支持度/消耗："])
            lines.extend(md_table([{"id": w["war_id"], "support": sol_text(w["war_support"]), "battle": sol_text(w["battles_war_support_delta"]), "exh": sol_text(w["exhaustion_war_support_delta"])} for w in war_parts[:10]], [("战争ID", "id"), ("战争支持", "support"), ("战斗影响", "battle"), ("消耗影响", "exh")]))
        if war_costs:
            lines.extend(["", "财政与军需成本："])
            lines.extend(md_table([{"id": c["diplomatic_play"], "side": c["side"], "mat": fmt(c["materiel_cost_of_war"], 1), "wage": fmt(c["wage_cost_of_war"], 1), "total": fmt(c["total_known_war_cost"], 1)} for c in war_costs[:10]], [("博弈ID", "id"), ("阵营", "side"), ("军需成本", "mat"), ("工资成本", "wage"), ("合计", "total")]))
        if battles:
            lines.extend(["", "主要战斗："])
            lines.extend(md_table([{"id": b["battle_id"], "where": nice_token(b["state_region"]), "status": b["status"], "start": b["start_date"], "a": b["attacker_tag"], "d": b["defender_tag"], "dead": fmt((b.get("attacker_dead") or 0) + (b.get("defender_dead") or 0), 0)} for b in battles[:10]], [("战斗ID", "id"), ("地点", "where"), ("结果", "status"), ("开始", "start"), ("进攻", "a"), ("防守", "d"), ("死亡", "dead")]))
        if casualties:
            total_dead = sum(row.get("dead") or 0 for row in casualties)
            total_wounded = sum(row.get("wounded") or 0 for row in casualties)
            lines.append(f"- 累计可读伤亡：死亡 {fmt(total_dead, 0)}；受伤 {fmt(total_wounded, 0)}。")
        lines.extend(["", "#### 社会学解读", ""])
        for note in social_reading(country, pop, cultures, types, igs):
            lines.append(f"- {note}")
        lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")


def build_system_export(path: Path, txt: str, limit: int = 30, full_pops: bool = True, progress=None) -> tuple[Path, dict[str, Path]]:
    def mark(percent: int, label: str) -> None:
        if progress:
            progress(percent, label)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = f"{path.stem}_{stamp}_systems"
    mark(5, "读取存档元数据")
    meta_info = meta(txt)
    countries = parse_countries(txt)
    player_id = player_country_id(txt, countries, str(meta_info["country"]))
    rankings = parse_rankings(txt, countries)
    major_ids = select_major_country_ids(countries, rankings, player_id, limit)
    major_set = set(major_ids)
    mark(12, "整理主要国家")
    all_states, state_to_country = parse_all_states(txt, countries)
    major_states = [row for row in all_states if row["country_id"] in major_set]
    mark(20, "整理州、基建、破坏度")
    building_details, building_summary = parse_buildings_for_countries(txt, state_to_country, countries, major_set)
    mark(30, "整理建筑和经济部门")
    culture_map = parse_culture_map(txt) if full_pops else {}
    if full_pops:
        pop_summary, pop_by_type, pop_by_culture, pop_by_religion = parse_pops_for_countries(
            txt,
            state_to_country,
            countries,
            major_set,
            culture_map,
            progress=lambda p, label: mark(30 + int(p * 0.28), label),
        )
    else:
        pop_summary, pop_by_type, pop_by_culture, pop_by_religion = [], [], [], []
    mark(58, "整理人口、职业、文化、宗教")
    law_rows = parse_laws_for_countries(txt, countries, major_set)
    ig_rows = parse_interest_groups_for_countries(txt, countries, major_set)
    tech_rows = parse_technology_for_countries(txt, countries, major_set)
    mark(68, "整理制度、利益集团、科技")
    relation_rows = parse_relations_for_countries(txt, countries, major_set)
    mark(70, "整理外交关系")
    pact_rows = parse_pacts_for_countries(txt, countries, major_set)
    mark(72, "整理外交条约")
    company_rows = parse_companies_for_countries(txt, countries, major_set)
    mark(74, "整理公司和GDP占比")
    war_rows, war_participant_rows = parse_wars_for_countries(txt, countries, major_set)
    mark(76, "整理战争与参战方")
    diplomatic_play_rows, war_cost_rows = parse_diplomatic_plays_for_countries(txt, countries, major_set)
    war_goal_rows = parse_war_goals_for_countries(txt, countries, major_set)
    military_formation_rows = parse_military_formations_for_countries(txt, countries, major_set)
    mark(79, "整理外交博弈、战争目标、军队")
    battle_rows, battle_casualty_rows = parse_battles_for_countries(
        txt,
        countries,
        major_set,
        culture_map,
        progress=lambda p, label: mark(79 + int(p * 0.03), label),
    )
    mark(82, "整理外交、战争、战斗、军队")

    rank_by_country = {row["country_id"]: row for row in rankings}
    world_gdp = sum(row.get("gdp") or 0 for row in countries.values())
    major_gdp = sum((countries[country_id].get("gdp") or 0) for country_id in major_ids)
    countries_rows = []
    for order, country_id in enumerate(major_ids, 1):
        row = countries[country_id]
        pop_detail = next((item for item in pop_summary if item["country_id"] == country_id), None)
        countries_rows.append(
            {
                "selection_order": order,
                "country_id": country_id,
                "tag": row["tag"],
                "power_rank": rank_by_country.get(country_id, {}).get("rank", ""),
                "prestige_rank": rank_by_country.get(country_id, {}).get("prestige_rank", ""),
                "gdp": row["gdp"],
                "world_gdp_share": ((row["gdp"] or 0) / world_gdp) if world_gdp else "",
                "major_gdp_share": ((row["gdp"] or 0) / major_gdp) if major_gdp else "",
                "gdp_start": row["gdp_start"],
                "gdp_change": row["gdp_change"],
                "gdp_change_pct": row["gdp_change_pct"],
                "population": row["population"],
                "gdp_per_capita": (row["gdp"] or 0) / row["population"] if row.get("population") else "",
                "prestige": row["prestige"],
                "prestige_start": row["prestige_start"],
                "prestige_change": row["prestige_change"],
                "prestige_change_pct": row["prestige_change_pct"],
                "literacy": row["literacy"],
                "literacy_start": row["literacy_start"],
                "literacy_change": row["literacy_change"],
                "literacy_change_pct": row["literacy_change_pct"],
                "sol": row["sol"],
                "sol_start": row["sol_start"],
                "sol_change": row["sol_change"],
                "sol_change_pct": row["sol_change_pct"],
                "government": row["government"],
                "market": row["market"],
                "capital": row["capital"],
                "legitimacy": row["legitimacy"],
                "infamy": row["infamy"],
                "states": sum(1 for state in major_states if state["country_id"] == country_id),
                "building_entries": sum(1 for building in building_details if building["country_id"] == country_id),
                "pop_entries": pop_detail["pop_entries"] if pop_detail else 0,
                "loyalists": pop_detail["loyalists"] if pop_detail else "",
                "radicals": pop_detail["radicals"] if pop_detail else "",
                "unanchored": pop_detail["unanchored"] if pop_detail else "",
            }
        )

    outputs = {
        "systems_report": REPORT_DIR / f"{stem}_report.md",
        "systems_document": REPORT_DIR / f"{stem}_document.md",
        "systems_summary": REPORT_DIR / f"{stem}_summary.json",
        "major_countries": REPORT_DIR / f"{stem}_major_countries.csv",
        "states": REPORT_DIR / f"{stem}_states.csv",
        "building_summary": REPORT_DIR / f"{stem}_building_summary.csv",
        "building_details": REPORT_DIR / f"{stem}_building_details.csv",
        "companies": REPORT_DIR / f"{stem}_companies.csv",
        "population_summary": REPORT_DIR / f"{stem}_population_summary.csv",
        "population_by_type": REPORT_DIR / f"{stem}_population_by_type.csv",
        "population_by_culture": REPORT_DIR / f"{stem}_population_by_culture.csv",
        "population_by_religion": REPORT_DIR / f"{stem}_population_by_religion.csv",
        "laws": REPORT_DIR / f"{stem}_laws.csv",
        "interest_groups": REPORT_DIR / f"{stem}_interest_groups.csv",
        "technology": REPORT_DIR / f"{stem}_technology.csv",
        "relations": REPORT_DIR / f"{stem}_relations.csv",
        "pacts": REPORT_DIR / f"{stem}_pacts.csv",
        "wars": REPORT_DIR / f"{stem}_wars.csv",
        "war_participants": REPORT_DIR / f"{stem}_war_participants.csv",
        "diplomatic_plays": REPORT_DIR / f"{stem}_diplomatic_plays.csv",
        "war_costs": REPORT_DIR / f"{stem}_war_costs.csv",
        "war_goals": REPORT_DIR / f"{stem}_war_goals.csv",
        "military_formations": REPORT_DIR / f"{stem}_military_formations.csv",
        "battles": REPORT_DIR / f"{stem}_battles.csv",
        "battle_casualties": REPORT_DIR / f"{stem}_battle_casualties.csv",
    }
    write_csv(outputs["major_countries"], countries_rows, ["selection_order", "country_id", "tag", "power_rank", "prestige_rank", "gdp", "world_gdp_share", "major_gdp_share", "gdp_start", "gdp_change", "gdp_change_pct", "population", "gdp_per_capita", "prestige", "prestige_start", "prestige_change", "prestige_change_pct", "literacy", "literacy_start", "literacy_change", "literacy_change_pct", "sol", "sol_start", "sol_change", "sol_change_pct", "government", "market", "capital", "legitimacy", "infamy", "states", "building_entries", "pop_entries", "loyalists", "radicals", "unanchored"])
    mark(88, "写出 CSV 表格")
    write_csv(outputs["states"], major_states, ["country_id", "tag", "state_id", "region", "capital", "arable_land", "incorporation", "infrastructure", "infrastructure_usage", "trade_capacity", "trade_capacity_usage", "devastation", "bureaucracy_cost", "previous_country", "last_owner_change"])
    write_csv(outputs["building_summary"], building_summary, ["country_id", "tag", "building", "sector", "building_count", "levels", "staffing", "goods_sales", "goods_cost", "profit_after_reserves"])
    write_csv(outputs["building_details"], building_details, ["country_id", "tag", "state_id", "building_id", "building", "levels", "staffing", "throughput", "salary_rate", "goods_sales", "goods_cost", "profit_after_reserves", "cash_reserves", "active"])
    write_csv(outputs["companies"], company_rows, ["company_id", "country_id", "tag", "company_type", "building_id", "state_region", "prosperity", "ceo", "productivity_start", "productivity_latest", "productivity_change", "productivity_change_pct", "productivity_samples"])
    write_csv(outputs["population_summary"], pop_summary, ["country_id", "tag", "population_detail", "workforce", "dependents", "loyalists", "radicals", "unanchored", "pop_entries"])
    write_csv(outputs["population_by_type"], pop_by_type, ["country_id", "tag", "dimension", "raw_dimension", "population", "share", "workforce", "dependents", "loyalists", "radicals"])
    write_csv(outputs["population_by_culture"], pop_by_culture, ["country_id", "tag", "dimension", "raw_dimension", "population", "share", "workforce", "dependents", "loyalists", "radicals"])
    write_csv(outputs["population_by_religion"], pop_by_religion, ["country_id", "tag", "dimension", "raw_dimension", "population", "share", "workforce", "dependents", "loyalists", "radicals"])
    write_csv(outputs["laws"], law_rows, ["country_id", "tag", "law", "raw_law"])
    write_csv(outputs["interest_groups"], ig_rows, ["country_id", "tag", "interest_group_id", "definition", "clout", "political_strength", "loyalists_political_strength", "radicals_political_strength", "in_government", "approval"])
    write_csv(outputs["technology"], tech_rows, ["country_id", "tag", "research_technology", "acquired_count", "spreading_count", "acquired_technologies", "currently_spreading"])
    write_csv(outputs["relations"], relation_rows, ["relation_id", "country_id", "tag", "partner_id", "partner_tag", "side", "relations", "improve_relations", "tension", "hostility", "obligation", "partner_obligation", "truce", "last_action"])
    write_csv(outputs["pacts"], pact_rows, ["pact_id", "country_id", "tag", "partner_id", "partner_tag", "side", "action", "start_date", "forced_duration", "liberty_desire"])
    write_csv(outputs["wars"], war_rows, ["war_id", "status", "diplomatic_play", "start_date", "peace_date", "days_since_exhaustion", "participant_country_ids", "participant_tags", "major_country_ids", "major_tags", "attacker_peace_country", "defender_peace_country", "attacker_last_proposal_date", "defender_last_proposal_date"])
    write_csv(outputs["war_participants"], war_participant_rows, ["war_id", "country_id", "tag", "diplomatic_play", "war_support", "initial_war_support", "battles_war_support_delta", "exhaustion_war_support_delta", "situations_war_support_delta", "violator"])
    write_csv(outputs["diplomatic_plays"], diplomatic_play_rows, ["diplomatic_play", "type", "state", "strategic_region", "initiator_id", "initiator_tag", "target_id", "target_tag", "initiator_side_tags", "target_side_tags", "involved_tags", "war", "escalation", "start_date", "end_date"])
    write_csv(outputs["war_costs"], war_cost_rows, ["diplomatic_play", "country_id", "tag", "side", "materiel_cost_of_war", "wage_cost_of_war", "total_known_war_cost"])
    write_csv(outputs["war_goals"], war_goal_rows, ["war_goal_id", "type", "holder_id", "holder_tag", "creator_id", "creator_tag", "target_country_id", "target_country_tag", "target_state", "target_region", "target_other", "diplomatic_play", "demand_type", "status", "initial_war_goal"])
    write_csv(outputs["military_formations"], military_formation_rows, ["formation_id", "country_id", "tag", "type", "ordinal_number", "home_hq", "supply_hub", "organization", "supply", "delivered_supply", "supply_priority", "flags", "default_unit_types", "unit_type_count", "mobilization_options", "mobilization_option_count", "current_location_type", "current_location_id", "target_location_type", "target_location_id", "creation_date", "ai_tag"])
    write_csv(outputs["battles"], battle_rows, ["battle_id", "war_id", "front", "type", "state_region", "province", "attacker_country_id", "attacker_tag", "defender_country_id", "defender_tag", "status", "start_date", "end_date", "attacker_start_battalions", "defender_start_battalions", "attacker_starting_manpower", "defender_starting_manpower", "attacker_ending_manpower", "defender_ending_manpower", "attacker_dead", "attacker_wounded", "defender_dead", "defender_wounded", "num_captured_provinces", "capturing_country", "lost_provinces_country"])
    write_csv(outputs["battle_casualties"], battle_casualty_rows, ["battle_id", "war_id", "side", "country_id", "tag", "culture", "raw_culture", "dead", "wounded", "demoralized"])

    summary = {
        "save": str(path),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "mode": "systems",
        "limit": limit,
        "full_pops": full_pops,
        "meta": meta_info,
        "major_country_ids": major_ids,
        "counts": {
            "major_countries": len(countries_rows),
            "states": len(major_states),
            "building_summary": len(building_summary),
            "building_details": len(building_details),
            "companies": len(company_rows),
            "population_summary": len(pop_summary),
            "population_by_type": len(pop_by_type),
            "population_by_culture": len(pop_by_culture),
            "population_by_religion": len(pop_by_religion),
            "laws": len(law_rows),
            "interest_groups": len(ig_rows),
            "technology": len(tech_rows),
            "relations": len(relation_rows),
            "pacts": len(pact_rows),
            "wars": len(war_rows),
            "war_participants": len(war_participant_rows),
            "diplomatic_plays": len(diplomatic_play_rows),
            "war_costs": len(war_cost_rows),
            "war_goals": len(war_goal_rows),
            "military_formations": len(military_formation_rows),
            "battles": len(battle_rows),
            "battle_casualties": len(battle_casualty_rows),
        },
        "outputs": {key: str(value) for key, value in outputs.items()},
    }
    write_json(outputs["systems_summary"], summary)

    lines = [
        "# 维多利亚 3 主要国家体系导出",
        "",
        f"- 存档：`{path.name}`",
        f"- 游戏日期：{meta_info['date']}",
        f"- 主要国家数量：{len(countries_rows)}",
        f"- 人口结构：{'已完整扫描' if full_pops else '未扫描'}",
        "",
        "## 固定表格",
        "",
        "| 表 | 内容 | 行数 |",
        "|---|---|---:|",
    ]
    labels = {
        "systems_document": "体系化国家文档：按国家逐项解读经济、社会、制度、外交",
        "major_countries": "国家总表：经济、人口、威望、社会压力",
        "states": "州体系：各主要国家拥有州",
        "building_summary": "建筑体系汇总：按国家和建筑类型",
        "building_details": "建筑体系明细：按建筑实例",
        "companies": "公司/企业：公司类型、地区、繁荣度、生产率历史",
        "population_summary": "人口总结构：劳动力、被扶养者、忠诚/激进",
        "population_by_type": "人口职业结构",
        "population_by_culture": "人口文化结构",
        "population_by_religion": "人口宗教结构",
        "laws": "社会制度/法律结构",
        "interest_groups": "社会集团/利益集团结构",
        "technology": "科技结构",
        "relations": "国际关系数值",
        "pacts": "外交条约/附庸/竞争/行动",
        "wars": "战争/历史战争总表",
        "war_participants": "主要国家参战方、战争支持度和消耗",
        "diplomatic_plays": "外交博弈：战争双方阵营、升级、区域",
        "war_costs": "战争财政和军需成本",
        "war_goals": "战争目标",
        "military_formations": "军队/海军编成、军种、动员选项、补给",
        "battles": "战斗记录：地点、日期、胜负、兵力、伤亡",
        "battle_casualties": "战斗伤亡：按国家和文化拆分",
        "systems_summary": "机器可读总索引 JSON",
    }
    for key, label in labels.items():
        rows = summary["counts"].get(key, 1 if key in {"systems_summary", "systems_document"} else "")
        lines.append(f"| `{outputs[key].name}` | {label} | {rows} |")
    lines.extend(["", "## 主要国家预览", ""])
    preview = [
        {
            "order": row["selection_order"],
            "tag": row["tag"],
            "rank": row["power_rank"],
            "gdp": fmt(row["gdp"], 2),
            "pop": fmt(row["population"], 2),
            "sol": sol_text(row["sol"]),
            "prestige": fmt(row["prestige"], 2),
        }
        for row in countries_rows[:20]
    ]
    lines.extend(md_table(preview, [("序", "order"), ("国家", "tag"), ("等级", "rank"), ("GDP", "gdp"), ("人口", "pop"), ("生活水平", "sol"), ("威望", "prestige")]))
    lines.extend(["", "## 说明", "", "- 这些 CSV 的列名固定；换存档后内容会变，但表结构保持不变。", "- 国际关系和条约按双方拆成双向行，便于按任意国家过滤。", "- 文化名来自存档内 cultures 数据库；无法识别时保留原始值。"])
    outputs["systems_report"].write_text("\n".join(lines), encoding="utf-8")
    mark(95, "写出体系化文档")
    write_system_document(
        path,
        outputs["systems_document"],
        meta_info,
        countries_rows,
        major_states,
        building_summary,
        pop_summary,
        pop_by_type,
        pop_by_culture,
        pop_by_religion,
        law_rows,
        ig_rows,
        tech_rows,
        relation_rows,
        pact_rows,
        company_rows,
        war_rows,
        war_participant_rows,
        diplomatic_play_rows,
        war_cost_rows,
        war_goal_rows,
        military_formation_rows,
        battle_rows,
        battle_casualty_rows,
    )
    mark(100, "导出完成")
    return outputs["systems_document"], outputs


def active_construction(country_block: str | None) -> list[dict]:
    queue = subblock(country_block or "", "construction_queue")
    if not queue:
        return []
    counts = Counter(re.findall(r"type=([A-Za-z0-9_\-]+)", queue))
    return [{"building": key, "count": value} for key, value in counts.most_common()]


def fmt(value, digits=1) -> str:
    if value is None:
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


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def md_table(rows: list[dict], fields: list[tuple[str, str]], limit: int | None = None) -> list[str]:
    out = []
    shown = rows[:limit] if limit else rows
    out.append("| " + " | ".join(label for label, _ in fields) + " |")
    out.append("|" + "|".join("---" for _ in fields) + "|")
    for row in shown:
        out.append("| " + " | ".join(str(row.get(key, "")) for _, key in fields) + " |")
    return out


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def sol_text(value) -> str:
    return "NA" if value is None else f"{value:.2f}"


def build_report(path: Path, txt: str, full_pops: bool = False) -> tuple[Path, dict[str, Path]]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = f"{path.stem}_{stamp}"
    meta_info = meta(txt)
    countries = parse_countries(txt)
    player_id = player_country_id(txt, countries, str(meta_info["country"]))
    player = countries.get(player_id) if player_id is not None else None
    rankings = parse_rankings(txt, countries)
    laws = parse_laws(txt, player_id) if player_id is not None else []
    country_block = country_block_by_id(txt, player_id) if player_id is not None else None
    states = parse_states_for_country(txt, player_id) if player_id is not None else []
    buildings = parse_buildings(txt, {s["state_id"] for s in states})
    culture_map = parse_culture_map(txt) if full_pops else {}
    pop_stats = parse_pops(txt, {s["state_id"] for s in states}, player_id, culture_map) if full_pops else empty_pop_stats()
    construction = active_construction(country_block)

    country_rows = [
        {
            "prestige_rank": i + 1,
            "country_id": cid,
            "tag": row["tag"],
            "gdp": row["gdp"],
            "population": row["population"],
            "prestige": row["prestige"],
            "literacy": row["literacy"],
            "sol": row["sol"],
            "government": row["government"],
            "infamy": row["infamy"],
        }
        for i, (cid, row) in enumerate(sorted(countries.items(), key=lambda item: item[1].get("prestige") or -1, reverse=True))
    ]
    gp_rows = [r for r in rankings if r["rank"] == "great_power"][:16]

    outputs = {
        "countries_csv": REPORT_DIR / f"{stem}_countries.csv",
        "great_powers_csv": REPORT_DIR / f"{stem}_great_powers.csv",
        "states_csv": REPORT_DIR / f"{stem}_states.csv",
        "buildings_csv": REPORT_DIR / f"{stem}_buildings.csv",
        "laws_csv": REPORT_DIR / f"{stem}_laws.csv",
        "pops_csv": REPORT_DIR / f"{stem}_pops.csv",
        "pops_by_type_csv": REPORT_DIR / f"{stem}_pops_by_type.csv",
        "pops_by_culture_csv": REPORT_DIR / f"{stem}_pops_by_culture.csv",
        "pops_by_religion_csv": REPORT_DIR / f"{stem}_pops_by_religion.csv",
        "summary_json": REPORT_DIR / f"{stem}_summary.json",
    }
    write_csv(outputs["countries_csv"], country_rows, ["prestige_rank", "country_id", "tag", "gdp", "population", "prestige", "literacy", "sol", "government", "infamy"])
    write_csv(outputs["great_powers_csv"], gp_rows, ["prestige_rank", "country_id", "tag", "rank", "target", "prestige", "government", "infamy"])
    write_csv(outputs["states_csv"], states, ["state_id", "region", "arable_land", "incorporation", "infrastructure", "infrastructure_usage", "bureaucracy_cost", "previous_country", "last_owner_change"])
    write_csv(outputs["buildings_csv"], buildings, ["building_id", "state_id", "building", "levels", "cash_reserves"])
    write_csv(outputs["laws_csv"], laws, ["law", "raw"])
    write_csv(outputs["pops_csv"], pop_stats["rows"], ["pop_id", "state_id", "type", "culture", "raw_culture", "religion", "size", "workforce", "dependents", "loyalists", "radicals", "workplace"])
    write_csv(outputs["pops_by_type_csv"], pop_stats["by_type"], ["name", "population", "share"])
    write_csv(outputs["pops_by_culture_csv"], pop_stats["by_culture"], ["name", "population", "share"])
    write_csv(outputs["pops_by_religion_csv"], pop_stats["by_religion"], ["name", "population", "share"])

    building_counter = Counter()
    for row in buildings:
        building_counter[row["building"]] += float(row["levels"] or 0)
    top_buildings = [{"building": name, "levels": round(levels, 2)} for name, levels in building_counter.most_common(30)]

    lines = [
        "# 维多利亚 3 存档分析报告",
        "",
        f"- 存档：`{path.name}`",
        f"- 文件时间：{datetime.fromtimestamp(path.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 游戏版本：{meta_info['version']}",
        f"- 游戏日期：{meta_info['date']}",
        f"- 存档国家：{meta_info['country']}",
        f"- 启用 Mod 数：{len(meta_info['mods'])}",
        f"- 人口明细模式：{'完整扫描' if full_pops else '快速模式（未扫描 pops 全库）'}",
        "",
    ]
    if player:
        gdp_pc = (player["gdp"] or 0) / player["population"] if player.get("population") else None
        lines.extend(
            [
                "## 玩家国家总览",
                "",
                "| 指标 | 数值 |",
                "|---|---:|",
                f"| 国家ID | {player_id} |",
                f"| 标签 | {player['tag']} |",
                f"| 政府 | {player['government'] or 'NA'} |",
                f"| GDP | {fmt(player['gdp'], 2)} |",
                f"| 人口 | {fmt(player['population'], 2)} |",
                f"| 人口明细合计 | {fmt(pop_stats['total'], 2) if full_pops else '未扫描'} |",
                f"| 人均GDP | {fmt(gdp_pc, 2)} |",
                f"| 威望 | {fmt(player['prestige'], 2)} |",
                f"| 识字率 | {(player['literacy'] or 0) * 100:.2f}% |",
                f"| 平均生活水平 | {sol_text(player['sol'])} |",
                f"| 正统性 | {player['legitimacy'] if player['legitimacy'] is not None else 'NA'} |",
                f"| 恶名 | {player['infamy'] if player['infamy'] is not None else 'NA'} |",
                f"| 忠诚派 | {fmt(pop_stats.get('loyalists'), 2) if full_pops else '未扫描'} |",
                f"| 激进派 | {fmt(pop_stats.get('radicals'), 2) if full_pops else '未扫描'} |",
                f"| 无工作场所/未锚定人口 | {fmt(pop_stats.get('unanchored'), 2) if full_pops else '未扫描'} |",
                "",
            ]
        )

    lines.extend(["## 列强/威望排名", ""])
    rank_rows = [
        {
            "rank": row["prestige_rank"],
            "tag": row["tag"],
            "power": row["rank"],
            "prestige": fmt(row["prestige"], 2),
            "infamy": row["infamy"] if row["infamy"] is not None else "NA",
        }
        for row in rankings[:20]
    ]
    lines.extend(md_table(rank_rows, [("威望序位", "rank"), ("国家", "tag"), ("等级", "power"), ("威望", "prestige"), ("恶名", "infamy")]))
    lines.append("")

    lines.extend(["## GDP 前十", ""])
    gdp_rows = []
    for i, row in enumerate(sorted(countries.values(), key=lambda item: item.get("gdp") or -1, reverse=True)[:10], 1):
        gdp_rows.append({"rank": i, "tag": row["tag"], "gdp": fmt(row["gdp"], 2), "pop": fmt(row["population"], 2)})
    lines.extend(md_table(gdp_rows, [("排名", "rank"), ("国家", "tag"), ("GDP", "gdp"), ("人口", "pop")]))
    lines.append("")

    lines.extend(["## 人口前十", ""])
    pop_rows = []
    for i, row in enumerate(sorted(countries.values(), key=lambda item: item.get("population") or -1, reverse=True)[:10], 1):
        pop_rows.append({"rank": i, "tag": row["tag"], "pop": fmt(row["population"], 2), "gdp": fmt(row["gdp"], 2)})
    lines.extend(md_table(pop_rows, [("排名", "rank"), ("国家", "tag"), ("人口", "pop"), ("GDP", "gdp")]))
    lines.append("")

    if states:
        lines.extend(["## 玩家国家州表", ""])
        state_rows = [
            {
                "state_id": row["state_id"],
                "infra": fmt(row["infrastructure"], 1),
                "used": fmt(row["infrastructure_usage"], 1),
                "arable": row["arable_land"] if row["arable_land"] is not None else "NA",
                "previous": row["previous_country"] or "NA",
            }
            for row in sorted(states, key=lambda x: x["state_id"])
        ]
        lines.extend(md_table(state_rows, [("州ID", "state_id"), ("基础设施", "infra"), ("使用", "used"), ("可耕地", "arable"), ("上一归属", "previous")], 30))
        lines.append("")

    if top_buildings:
        lines.extend(["## 玩家国家建筑结构", ""])
        lines.extend(md_table(top_buildings, [("建筑", "building"), ("等级合计", "levels")], 30))
        lines.append("")

    for title, rows in (
        ("## 人口：职业结构", pop_stats["by_type"]),
        ("## 人口：文化结构", pop_stats["by_culture"]),
        ("## 人口：宗教结构", pop_stats["by_religion"]),
    ):
        if rows:
            pretty_rows = [
                {"name": row["name"], "population": fmt(row["population"], 2), "share": f"{row['share'] * 100:.2f}%"}
                for row in rows[:30]
            ]
            lines.extend([title, ""])
            lines.extend(md_table(pretty_rows, [("类别", "name"), ("人口", "population"), ("占比", "share")]))
            lines.append("")

    if construction:
        lines.extend(["## 建造队列类型", ""])
        lines.extend(md_table(construction, [("建筑", "building"), ("队列数量", "count")], 30))
        lines.append("")

    if laws:
        lines.extend(["## 当前法律", ""])
        lines.extend(md_table(laws, [("法律", "law"), ("原始字段", "raw")]))
        lines.append("")

    lines.extend(
        [
            "## 数据限制",
            "",
            "- 本工具直接解析存档文本/压缩包里的 gamestate 风格结构。",
            "- 国家名优先显示 tag；完整中文名需要继续接本地化文件。",
            "- 文化、宗教、职业人口明细已经按存档原始 ID/字段导出；完整中文名需要继续接本地化与定义文件。",
            "- 部分模组会改字段或新增建筑，本工具会保留原始字段名。",
        ]
    )

    summary = {
        "save": str(path),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "meta": meta_info,
        "player_country_id": player_id,
        "player": {k: v for k, v in (player or {}).items() if k != "raw_block"},
        "counts": {
            "countries": len(countries),
            "rankings": len(rankings),
            "states": len(states),
            "buildings": len(buildings),
            "pops": len(pop_stats["rows"]),
        },
        "full_pops": full_pops,
        "outputs": {key: str(value) for key, value in outputs.items()},
    }
    write_json(outputs["summary_json"], summary)

    report_path = REPORT_DIR / f"{stem}_report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path, outputs


def doctor_payload() -> dict[str, object]:
    latest = find_latest_save()
    return {
        "ok": latest is not None,
        "tool_dir": str(TOOL_DIR),
        "save_dir": str(SAVE_DIR),
        "reports_dir": str(REPORT_DIR),
        "latest_save": str(latest) if latest else None,
        "latest_save_kind": save_kind(latest) if latest else None,
        "python": sys.version.split()[0],
        "community": community_status(),
    }


def print_or_json(payload: dict[str, object], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    for key, value in payload.items():
        print(f"{key}: {value}")


def main() -> None:
    global REPORT_DIR
    parser = argparse.ArgumentParser(description="Victoria 3 通用存档读取器")
    parser.add_argument("--json", action="store_true", help="输出稳定 JSON，方便其他脚本/API 调用")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("doctor", help="检查存档目录、最新存档和运行环境")
    subparsers.add_parser("latest", help="显示最新存档路径")
    subparsers.add_parser("community", help="显示已集成的社区来源和可用后端")
    melt_parser = subparsers.add_parser("melt", help="用社区 Rakaly melter 把存档转换为文本")
    melt_parser.add_argument("save", help="指定 .v3 存档")
    melt_parser.add_argument("--out", help="输出文本路径；不填则放到 reports")
    systems_parser = subparsers.add_parser("systems", help="按固定模板导出主要国家的经济/建筑/人口/社会/国际关系体系")
    systems_parser.add_argument("save", nargs="?", help="指定 .v3 存档；不填则读取最新存档")
    systems_parser.add_argument("--out", help="报告输出目录")
    systems_parser.add_argument("--limit", type=int, default=30, help="主要国家数量，默认 30")
    systems_parser.add_argument("--no-pops", action="store_true", help="跳过人口明细扫描")
    report_parser = subparsers.add_parser("report", help="生成 Markdown 报告和 CSV/JSON 数据")
    report_parser.add_argument("save", nargs="?", help="指定 .v3 存档；不填则读取最新存档")
    report_parser.add_argument("--out", help="报告输出目录")
    report_parser.add_argument("--full", action="store_true", help="完整扫描人口明细；会明显变慢")

    commands = {"doctor", "latest", "community", "melt", "systems", "report"}
    argv = sys.argv[1:]
    if not argv:
        argv = ["report"]
    elif argv[0] not in commands and not argv[0].startswith("-"):
        argv = ["report", *argv]
    args = parser.parse_args(argv)

    if args.command == "doctor":
        print_or_json(doctor_payload(), args.json)
        return

    if args.command == "latest":
        latest = find_latest_save()
        payload = {"latest_save": str(latest) if latest else None, "kind": save_kind(latest) if latest else None}
        print_or_json(payload, args.json)
        return

    if args.command == "community":
        print_or_json(community_status(), args.json)
        return

    if args.command == "melt":
        save_path = Path(args.save).expanduser().resolve()
        out_path = Path(args.out).expanduser().resolve() if args.out else (REPORT_DIR / f"{save_path.stem}.melted.txt")
        melted = melt_save_with_garibaldi(save_path, out_path)
        print_or_json({"ok": True, "input": str(save_path), "output": str(melted)}, args.json)
        return

    if args.command in {"report", "systems"} and args.out:
        REPORT_DIR = Path(args.out).expanduser().resolve()

    save_arg = args.save if args.command in {"report", "systems"} else None
    path = Path(save_arg) if save_arg else find_latest_save()
    if not path or not path.is_file():
        payload = {"ok": False, "error": "未找到存档文件", "hint": "请手动指定路径：python analyze.py report <路径>"}
        print_or_json(payload, args.json)
        sys.exit(2)
    txt = read_save(path)
    if args.command == "systems":
        report_path, outputs = build_system_export(path, txt, limit=max(1, args.limit), full_pops=not args.no_pops)
    else:
        report_path, outputs = build_report(path, txt, full_pops=getattr(args, "full", False))
    payload = {"ok": True, "report": str(report_path), "outputs": {label: str(output) for label, output in outputs.items()}}
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"已生成报告: {report_path}")
        for label, output in outputs.items():
            print(f"{label}: {output}")


if __name__ == "__main__":
    main()
