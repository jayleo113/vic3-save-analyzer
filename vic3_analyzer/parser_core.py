# -*- coding: utf-8 -*-
"""Low-level helpers for reading Jomini-style Victoria 3 save text."""

from __future__ import annotations

import re

_DATABASE_BLOCK_CACHE: dict[tuple[int, str], tuple[str, str | None]] = {}


def clear_database_block_cache(txt: str | None = None) -> None:
    if txt is None:
        _DATABASE_BLOCK_CACHE.clear()
        return
    txt_id = id(txt)
    for key in [key for key in _DATABASE_BLOCK_CACHE if key[0] == txt_id]:
        del _DATABASE_BLOCK_CACHE[key]


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


def subblock(block: str | None, key: str) -> str | None:
    if not block:
        return None
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


def top_values(block: str | None, keys: set[str]) -> dict[str, str]:
    if not block:
        return {}
    values = {}
    for match in re.finditer(r"(?m)^\s*([A-Za-z0-9_\-]+)\s*=\s*([^\n{}]+)", block):
        key = match.group(1)
        if key in keys and key not in values:
            values[key] = match.group(2).strip().strip('"')
            if len(values) == len(keys):
                break
    return values


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


def iter_numbered_entries(db: str):
    entries = list(re.finditer(r"(?m)^(\d+)=(\{|none)", db))
    for index, match in enumerate(entries):
        key = match.group(1)
        if match.group(2) == "none":
            continue
        end = entries[index + 1].start() if index + 1 < len(entries) else len(db)
        yield key, db[match.end() : end]


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
    cache_key = (id(txt), manager)
    cached = _DATABASE_BLOCK_CACHE.get(cache_key)
    if cached and cached[0] is txt:
        return cached[1]

    manager_block = top_level_block(txt, manager)
    if not manager_block:
        manager_block = block_after(txt, manager + "={")
    if not manager_block:
        _DATABASE_BLOCK_CACHE[cache_key] = (txt, None)
        return None
    block = manager_block[0]
    db_pos = block.find("database=")
    if db_pos < 0:
        _DATABASE_BLOCK_CACHE[cache_key] = (txt, block)
        return block
    open_pos = block.find("{", db_pos)
    close = brace_span(block, open_pos)
    result = block[open_pos + 1 : close]
    _DATABASE_BLOCK_CACHE[cache_key] = (txt, result)
    return result
