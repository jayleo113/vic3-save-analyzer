# -*- coding: utf-8 -*-
"""Read Victoria 3 saves as text, using community melters when needed."""

from __future__ import annotations

import os
import subprocess
import zipfile
from pathlib import Path

from . import external_tools
from .fingerprint import full_hash
from .cache_io import atomic_json, cache_lock
import json


def garibaldi_melter_path(community_dir: Path) -> Path | None:
    if os.name == "nt":
        path = community_dir / "Garibaldi" / "bin" / "rakaly_windows" / "melter.exe"
    else:
        path = community_dir / "Garibaldi" / "bin" / "rakaly_linux" / "melter"
    return path if path.exists() else None


def looks_like_text_save(data: bytes) -> bool:
    sample = data[:200_000]
    if b"\x00" in sample:
        return False
    decoded = sample.decode("utf-8", errors="replace")
    if not decoded:
        return False
    replacement_ratio = decoded.count("\ufffd") / max(len(decoded), 1)
    markers = ("meta_data", "game_date", "country_manager", "pops", "={", "= {")
    return replacement_ratio < 0.001 and any(marker in decoded for marker in markers)


def melt_cache_path(path: Path, cache_root: Path | None = None) -> Path:
    root = cache_root or path.parent
    return root / "melted" / f"{full_hash(path)}.melted.txt"


def melt_save_with_garibaldi(path: Path, community_dir: Path, out: Path | None = None, cache_root: Path | None = None) -> Path:
    melter = garibaldi_melter_path(community_dir)
    if not melter:
        raise RuntimeError("没有找到 Garibaldi/Rakaly melter，无法自动转换二进制存档")
    if out is None:
        out = melt_cache_path(path, cache_root)
    with cache_lock(out.with_suffix('.lock')):
        source_hash, tool_hash = full_hash(path), full_hash(melter)
        marker = out.with_suffix('.json')
        try:
            known = json.loads(marker.read_text(encoding='utf-8'))
            if out.exists() and known == {'source': source_hash, 'tool': tool_hash, 'text': full_hash(out)}:
                return out
        except (OSError, ValueError):
            pass
        pending = out.with_suffix('.partial')
        env = os.environ.copy()
        env['PATH'] = str(melter.parent) + os.pathsep + env.get('PATH', '')
        env['TEMP'] = env['TMP'] = str(out.parent)
        try:
            result = subprocess.run([str(melter), 'save', str(path), str(pending)],
                cwd=str(community_dir / 'Garibaldi'), env=env, capture_output=True, text=True)
            if result.returncode != 0 or not pending.is_file() or not pending.stat().st_size:
                raise RuntimeError(f"Rakaly melter 转换失败：{(result.stderr or result.stdout or '').strip()}")
            if full_hash(path) != source_hash:
                raise RuntimeError('转换期间存档发生变化，请重试')
            os.replace(pending, out)
            atomic_json(marker, {'source': source_hash, 'tool': tool_hash, 'text': full_hash(out)})
            return out
        finally:
            pending.unlink(missing_ok=True)


def read_save(path: Path, community_dir: Path, project_root: Path | None = None, cache_root: Path | None = None) -> str:
    with path.open("rb") as handle:
        sample = handle.read(256_000)
    if sample.startswith(b"PK"):
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            target = "gamestate" if "gamestate" in names else names[0]
            data = zf.read(target)
            if looks_like_text_save(data):
                return data.decode("utf-8", errors="replace")
        if project_root and cache_root:
            native = external_tools.native_extract_to_text(path, project_root, cache_root)
            if native:
                return native[0].read_text(encoding="utf-8", errors="replace")
        melted = melt_save_with_garibaldi(path, community_dir, cache_root=cache_root)
        return melted.read_text(encoding="utf-8", errors="replace")
    if not looks_like_text_save(sample):
        if project_root and cache_root:
            native = external_tools.native_extract_to_text(path, project_root, cache_root)
            if native:
                return native[0].read_text(encoding="utf-8", errors="replace")
        melted = melt_save_with_garibaldi(path, community_dir, cache_root=cache_root)
        return melted.read_text(encoding="utf-8", errors="replace")
    return path.read_text(encoding="utf-8", errors="replace")


def save_kind(path: Path) -> str:
    with path.open('rb') as handle:
        raw = handle.read(256_000)
    if raw.startswith(b"PK"):
        return "zip"
    return "text" if looks_like_text_save(raw) else "binary_or_unknown"
