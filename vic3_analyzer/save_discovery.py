# -*- coding: utf-8 -*-
"""Victoria 3 save discovery helpers."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path


STEAM_APP_ID = "529340"


def candidate_save_dirs(home: Path | None = None) -> list[Path]:
    home = home or Path.home()
    roots = [
        home / "Documents" / "Paradox Interactive" / "Victoria 3" / "save games",
        home / "OneDrive" / "Documents" / "Paradox Interactive" / "Victoria 3" / "save games",
    ]
    for drive in "CDEFG":
        for steam_root in (Path(f"{drive}:/steam"), Path(f"{drive}:/Steam"), Path(f"{drive}:/Program Files (x86)/Steam")):
            userdata = steam_root / "userdata"
            if not userdata.exists():
                continue
            roots.extend(user_dir / STEAM_APP_ID / "remote" / "save games" for user_dir in userdata.glob("*") if user_dir.is_dir())

    seen = set()
    result = []
    for root in roots:
        key = str(root).lower()
        if key in seen or not root.exists():
            continue
        seen.add(key)
        result.append(root)
    return result


def date_tuple_from_text(value: object) -> tuple[int, int, int]:
    parts = [int(part) for part in re.findall(r"\d+", str(value or ""))[:3]]
    if len(parts) < 3:
        return (0, 0, 0)
    year, month, day = parts
    if month < 1 or month > 12:
        month = 1
    if day < 1 or day > 31:
        day = min(max(day, 1), 31)
    return (year, month, day)


def filename_date_tuple(path: Path) -> tuple[int, int, int]:
    match = re.search(r"(\d{4})[_\-\s.]+(\d{1,2})[_\-\s.]+(\d{1,2})", path.stem)
    return date_tuple_from_text(".".join(match.groups())) if match else (0, 0, 0)


def quick_save_game_date_tuple(path: Path) -> tuple[int, int, int]:
    try:
        raw = path.read_bytes()[:512_000]
        if raw.startswith(b"PK"):
            with zipfile.ZipFile(path) as zf:
                names = zf.namelist()
                target = "gamestate" if "gamestate" in names else names[0]
                with zf.open(target) as handle:
                    raw = handle.read(512_000)
        text = raw.decode("utf-8", errors="replace")
        match = re.search(r"(?m)^\s*(?:game_date|date)\s*=\s*\"?(\d{1,5}[._-]\d{1,2}[._-]\d{1,5})\"?", text)
        if match:
            parsed = date_tuple_from_text(match.group(1))
            if parsed != (0, 0, 0):
                return parsed
    except Exception:
        pass
    return filename_date_tuple(path)


def list_save_paths(sort_by: str = "modified") -> list[Path]:
    saves: list[Path] = []
    seen = set()
    for folder in candidate_save_dirs():
        for path in folder.glob("*.v3"):
            key = str(path.resolve()).lower()
            if key in seen:
                continue
            seen.add(key)
            saves.append(path)
    if sort_by == "game_date":
        return sorted(saves, key=lambda item: (quick_save_game_date_tuple(item), item.stat().st_mtime), reverse=True)
    return sorted(saves, key=lambda item: item.stat().st_mtime, reverse=True)


def find_latest_save() -> Path | None:
    saves = list_save_paths()
    return saves[0] if saves else None
