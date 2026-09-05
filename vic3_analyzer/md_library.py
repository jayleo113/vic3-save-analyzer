# -*- coding: utf-8 -*-
"""Markdown report library helpers.

The desktop MD library is the user-facing handoff format for chat models that
cannot reach a local API. Keep this module independent from the heavy parser so
library indexing and cache checks stay fast.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path


INDEX_NAME = "00_资料库索引.md"
MANIFEST_NAME = "md_library_manifest.json"
SCHEMA_VERSION = "md_full_v4"


def file_size_label(size: int) -> str:
    if size >= 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024 * 1024):.1f}GB"
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f}MB"
    if size >= 1024:
        return f"{size / 1024:.1f}KB"
    return f"{size}B"


def save_fingerprint(path: Path) -> dict[str, object]:
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "mtime": stat.st_mtime,
        "size": stat.st_size,
    }


def load_manifest(cache_root: Path) -> dict[str, object]:
    path = cache_root / MANIFEST_NAME
    if not path.exists():
        return {"reports": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"reports": {}}
    if not isinstance(data, dict):
        return {"reports": {}}
    data.setdefault("reports", {})
    return data


def save_manifest(cache_root: Path, manifest: dict[str, object]) -> Path:
    cache_root.mkdir(parents=True, exist_ok=True)
    path = cache_root / MANIFEST_NAME
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def cached_report_for_save(save_path: Path, library_root: Path, cache_root: Path) -> Path | None:
    manifest = load_manifest(cache_root)
    entry = manifest.get("reports", {}).get(str(save_path.resolve()))
    if not isinstance(entry, dict):
        return None
    current = save_fingerprint(save_path)
    if entry.get("mtime") != current["mtime"] or entry.get("size") != current["size"]:
        return None
    if entry.get("schema") != SCHEMA_VERSION:
        return None
    report_name = str(entry.get("report") or "")
    report = library_root / report_name
    return report if report.is_file() else None


def remember_report(save_path: Path, report: Path, cache_root: Path) -> None:
    manifest = load_manifest(cache_root)
    reports = manifest.setdefault("reports", {})
    if not isinstance(reports, dict):
        reports = {}
        manifest["reports"] = reports
    fingerprint = save_fingerprint(save_path)
    reports[str(save_path.resolve())] = {
        **fingerprint,
        "schema": SCHEMA_VERSION,
        "report": report.name,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    save_manifest(cache_root, manifest)


def clean_temp_files(library_root: Path) -> None:
    if not library_root.exists():
        return
    for item in library_root.iterdir():
        if item.is_file() and item.suffix.lower() in {".csv", ".json"}:
            item.unlink()


def ensure_md_name(path: Path) -> Path:
    if path.suffix.lower() == ".md":
        return path
    return path.with_suffix(path.suffix + ".md")


def normalize_legacy_names(library_root: Path) -> None:
    if not library_root.exists():
        return
    for item in library_root.iterdir():
        if not item.is_file() or item.suffix.lower() == ".md":
            continue
        if ".md_第" not in item.name:
            continue
        fixed_name = item.name.replace(".md_第", "_第")
        fixed = item.with_name(fixed_name)
        fixed = ensure_md_name(fixed)
        if not fixed.exists():
            item.rename(fixed)


def report_identity(report: Path) -> tuple[str, str]:
    pattern = re.compile(r"(.+?)_(\d{4}-\d{2}-\d{2})_体系化国家报告(?:_第\d+次导出)?\.md$")
    match = pattern.match(report.name)
    if match:
        return match.group(1), match.group(2)
    return "未知", "未知"


def write_index(library_root: Path) -> Path:
    library_root.mkdir(parents=True, exist_ok=True)
    normalize_legacy_names(library_root)
    reports = sorted(
        [item for item in library_root.glob("*.md") if item.name != INDEX_NAME],
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    lines = [
        "# Victoria 3 存档 MD 资料库",
        "",
        f"- 更新时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 报告数量：{len(reports)}",
        "- 用途：给不能访问本地 API 的聊天环境直接读取。这里尽量只放 Markdown 报告，不放 CSV/JSON 表格。",
        "",
        "| 序 | 国家 | 游戏日期 | 文件 | 修改时间 | 大小 |",
        "|---:|---|---|---|---|---:|",
    ]
    for index, report in enumerate(reports, 1):
        country, date = report_identity(report)
        modified = datetime.fromtimestamp(report.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        lines.append(f"| {index} | {country} | {date} | `{report.name}` | {modified} | {file_size_label(report.stat().st_size)} |")
    index_path = library_root / INDEX_NAME
    index_path.write_text("\n".join(lines), encoding="utf-8")
    return index_path


def validate_report(report: Path) -> list[str]:
    issues = []
    if not report.is_file():
        return ["报告文件不存在"]
    text = report.read_text(encoding="utf-8", errors="replace")
    country, filename_date = report_identity(report)
    if filename_date != "未知":
        year, month, day = [int(part) for part in filename_date.split("-")]
        variants = {
            f"{year}-{month:02d}-{day:02d}",
            f"{year}.{month}.{day}",
            f"{year}.{month:02d}.{day:02d}",
        }
        if not any(variant in text[:1200] for variant in variants):
            issues.append("文件名日期和正文日期可能不一致")
    required = ["## 世界总览", "## 国家档案", "#### 8. 国际关系、条约与外交结构", "#### 9. 战争与历史战争"]
    for marker in required:
        if marker not in text:
            issues.append(f"缺少章节：{marker}")
    if "附属体系、傀儡国与势力范围" not in text:
        issues.append("缺少附属体系总览")
    if country == "未知":
        issues.append("文件名没有识别出国家和日期")
    return issues


def copy_report_to_library(document: Path, library_root: Path, final_name: str) -> Path:
    library_root.mkdir(parents=True, exist_ok=True)
    final_report = library_root / final_name
    if final_report.exists():
        stem = final_report.stem
        suffix = final_report.suffix
        for index in range(2, 1000):
            candidate = library_root / f"{stem}_第{index}次导出{suffix}"
            if not candidate.exists():
                final_report = candidate
                break
    if document.resolve() != final_report.resolve():
        shutil.copy2(document, final_report)
    return final_report
