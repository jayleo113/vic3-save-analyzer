# -*- coding: utf-8 -*-
"""Fast file fingerprints for save/cache invalidation."""

from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path


def text_hash(text: str) -> str:
    digest = hashlib.sha256()
    for offset in range(0, len(text), 4 * 1024 * 1024):
        digest.update(text[offset:offset + 4 * 1024 * 1024].encode('utf-8'))
    return digest.hexdigest()


def full_hash(path: Path) -> str:
    """Verify every byte; refuse a file that changes while being read."""
    before = path.stat()
    hasher = hashlib.sha256()
    with path.open('rb') as handle:
        while chunk := handle.read(4 * 1024 * 1024):
            hasher.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError('存档正在被游戏写入，请保存完成后重试')
    return hasher.hexdigest()


def quick_hash(path: Path, sample_bytes: int = 1024 * 1024) -> str:
    """Hash the parts that change when a save changes, without reading huge files fully."""
    stat = path.stat()
    hasher = hashlib.sha256()
    hasher.update(str(stat.st_size).encode("ascii"))
    with path.open("rb") as handle:
        head = handle.read(sample_bytes)
        hasher.update(head)
        if stat.st_size > sample_bytes:
            handle.seek(max(0, stat.st_size - sample_bytes))
            hasher.update(handle.read(sample_bytes))
    return hasher.hexdigest()


def file_fingerprint(path: Path) -> dict[str, object]:
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "mtime_ns": stat.st_mtime_ns,
        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
        "quick_hash": quick_hash(path),
    }
