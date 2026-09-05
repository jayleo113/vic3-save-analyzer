# -*- coding: utf-8 -*-
"""Optional high-speed save extractor discovery and wrappers."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from . import rust_backend
from .fingerprint import full_hash
from .cache_io import atomic_json, cache_lock

_EXIT_USE_PYTHON = 3


def _exe(name: str) -> str:
    return f"{name}.exe" if os.name == "nt" else name


def garibaldi_dir(project_root: Path) -> Path:
    return project_root / "community" / "Garibaldi"


def garibaldi_native_extractor(project_root: Path) -> Path | None:
    root = garibaldi_dir(project_root)
    folder = "rakaly_windows" if os.name == "nt" else "rakaly_linux"
    path = root / "bin" / folder / _exe("vic3-extract")
    return path if path.exists() else None


def garibaldi_melter(project_root: Path) -> Path | None:
    root = garibaldi_dir(project_root)
    folder = "rakaly_windows" if os.name == "nt" else "rakaly_linux"
    path = root / "bin" / folder / _exe("melter")
    return path if path.exists() else None


def rakaly_cli(project_root: Path) -> Path | None:
    candidates: list[Path] = [project_root / "tools" / _exe("rakaly")]
    if os.environ.get("VIC3_RAKALY"):
        candidates.append(Path(os.environ["VIC3_RAKALY"]))
    if shutil.which("rakaly"):
        candidates.append(Path(shutil.which("rakaly") or ""))
    for path in candidates:
        if str(path) and path.exists():
            return path
    return None


def jomini_extractor(project_root: Path) -> Path | None:
    candidates: list[Path] = [project_root / "rust" / "vic3_extract" / "target" / "release" / _exe("vic3_extract")]
    if os.environ.get("VIC3_JOMINI_EXTRACTOR"):
        candidates.append(Path(os.environ["VIC3_JOMINI_EXTRACTOR"]))
    if shutil.which("vic3_extract"):
        candidates.append(Path(shutil.which("vic3_extract") or ""))
    for path in candidates:
        if str(path) and path.exists():
            return path
    return None


def status(project_root: Path) -> dict[str, object]:
    native = garibaldi_native_extractor(project_root)
    melter = garibaldi_melter(project_root)
    rakaly = rakaly_cli(project_root)
    jomini = jomini_extractor(project_root)
    rust = rust_backend.status(project_root)
    return {
        "garibaldi_native_extractor": str(native) if native else "",
        "garibaldi_melter": str(melter) if melter else "",
        "rakaly_cli": str(rakaly) if rakaly else "",
        "jomini_extractor": str(jomini) if jomini else "",
        "rust_scanner": rust.get("rust_scanner", ""),
        "active_backends": [name for name, value in {
            "rust_scanner": rust.get("rust_scanner_available"),
            "jomini": jomini,
            "garibaldi_native": native,
            "garibaldi_melter": melter,
            "rakaly_cli": rakaly,
            "python_text_zip": True,
        }.items() if value],
    }


def _cache_key(save_path: Path) -> str:
    return full_hash(save_path)


def native_extract_to_text(save_path: Path, project_root: Path, cache_root: Path) -> tuple[Path, dict[str, object]] | None:
    with cache_lock(cache_root / 'native_extract.lock'):
        return _native_extract_to_text(save_path, project_root, cache_root)


def _native_extract_to_text(save_path, project_root, cache_root):
    """Use Garibaldi's native extractor to melt a save and emit reusable text."""
    binary = garibaldi_native_extractor(project_root)
    if not binary:
        return None
    root = garibaldi_dir(project_root)
    schema = root / "src" / "save_schema.toml"
    if not schema.exists():
        return None
    out_dir = cache_root / "native_extract" / _cache_key(save_path)
    text_path = out_dir / "gamestate.melted.txt"
    summary_path = out_dir / "summary.json"
    tool_hash = full_hash(binary) + full_hash(schema)
    if text_path.exists() and summary_path.exists():
        try:
            summary = json.loads(summary_path.read_text(encoding='utf-8'))
            if summary.get('tool_hash') == tool_hash and summary.get('text_sha256') == full_hash(text_path):
                return text_path, summary
        except json.JSONDecodeError:
            pass
    out_dir.mkdir(parents=True, exist_ok=True)
    pending = text_path.with_suffix('.partial')
    source_hash = full_hash(save_path)
    command = [str(binary), str(save_path), str(out_dir), "--schema", str(schema), "--emit-text", str(pending)]
    env = os.environ.copy()
    env['TEMP'] = env['TMP'] = str(out_dir)
    result = subprocess.run(command, cwd=str(root), env=env, capture_output=True, text=True)
    if result.returncode == _EXIT_USE_PYTHON:
        pending.unlink(missing_ok=True)
        return None
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        pending.unlink(missing_ok=True)
        return None
    try:
        summary = json.loads(result.stdout)
    except json.JSONDecodeError:
        summary = {"raw_stdout": result.stdout.strip()}
    summary["backend"] = "garibaldi_native"
    summary["text"] = str(text_path)
    if not pending.is_file() or not pending.stat().st_size:
        raise RuntimeError("高速提取器没有生成文本输出")
    if source_hash != full_hash(save_path):
        pending.unlink(missing_ok=True)
        raise RuntimeError('转换期间存档发生变化，请重试')
    os.replace(pending, text_path)
    summary['tool_hash'] = tool_hash
    summary['text_sha256'] = full_hash(text_path)
    atomic_json(summary_path, summary)
    return text_path, summary
