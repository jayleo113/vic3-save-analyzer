"""Optional Rust scanner discovery.

The analyzer keeps Python as the stable orchestration layer. This module only
uses the Rust helper when the user has built it locally; otherwise callers keep
using the existing Python parser.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def _exe(name: str) -> str:
    return f"{name}.exe" if os.name == "nt" else name


def scanner_path(project_root: Path) -> Path | None:
    candidates = [
        project_root / "rust" / "vic3_parser_rs" / "target" / "release" / _exe("vic3-scan"),
        project_root / "rust" / "vic3_parser_rs" / "target" / "debug" / _exe("vic3-scan"),
    ]
    if os.environ.get("VIC3_RUST_SCANNER"):
        candidates.insert(0, Path(os.environ["VIC3_RUST_SCANNER"]))
    for path in candidates:
        if path.is_file():
            return path
    return None


def status(project_root: Path) -> dict[str, object]:
    scanner = scanner_path(project_root)
    return {
        "rust_scanner": str(scanner) if scanner else "",
        "rust_scanner_available": bool(scanner),
    }


def scan_blocks(project_root: Path, text_path: Path) -> dict[str, object] | None:
    scanner = scanner_path(project_root)
    if not scanner:
        return None
    result = subprocess.run([str(scanner), str(text_path)], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "Rust 扫描器执行失败").strip())
    return json.loads(result.stdout)
