# -*- coding: utf-8 -*-
"""Read Victoria 3 saves as text, using community melters when needed."""

from __future__ import annotations

import os
import subprocess
import tempfile
import zipfile
from pathlib import Path


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
    return replacement_ratio < 0.001 and ("meta_data" in decoded or "country_manager" in decoded or "pops" in decoded)


def melt_save_with_garibaldi(path: Path, community_dir: Path, out: Path | None = None) -> Path:
    melter = garibaldi_melter_path(community_dir)
    if not melter:
        raise RuntimeError("没有找到 Garibaldi/Rakaly melter，无法自动转换二进制存档")
    if out is None:
        out = Path(tempfile.gettempdir()) / f"{path.stem}.melted.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PATH"] = str(melter.parent) + os.pathsep + env.get("PATH", "")
    command = [str(melter), "save", str(path), str(out)]
    result = subprocess.run(command, cwd=str(community_dir / "Garibaldi"), env=env, capture_output=True, text=True)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"Rakaly melter 转换失败：{message}")
    return out


def read_save(path: Path, community_dir: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(b"PK"):
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            target = "gamestate" if "gamestate" in names else names[0]
            data = zf.read(target)
            if looks_like_text_save(data):
                return data.decode("utf-8", errors="replace")
        melted = melt_save_with_garibaldi(path, community_dir)
        return melted.read_text(encoding="utf-8", errors="replace")
    if not looks_like_text_save(raw):
        melted = melt_save_with_garibaldi(path, community_dir)
        return melted.read_text(encoding="utf-8", errors="replace")
    return raw.decode("utf-8", errors="replace")


def save_kind(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(b"PK"):
        return "zip"
    return "text" if looks_like_text_save(raw) else "binary_or_unknown"
