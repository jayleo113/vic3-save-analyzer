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
from . import country_names
from .cache_io import atomic_json, cache_lock
from .fingerprint import full_hash
from .snapshot_store import code_version


INDEX_NAME = "00_资料库索引.md"
MANIFEST_NAME = "md_library_manifest.json"
SCHEMA_VERSION = "md_full_v5_verified_world"
ARCHIVE_DIR_NAME = "_旧版重复报告"


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
        "sha256": full_hash(path),
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
    atomic_json(path, manifest)
    return path


def cached_report_for_save(save_path: Path, library_root: Path, cache_root: Path) -> Path | None:
    manifest = load_manifest(cache_root)
    changed = False
    entry = manifest.get("reports", {}).get(str(save_path.resolve()))
    if not isinstance(entry, dict):
        return None
    current = save_fingerprint(save_path)
    if entry.get("mtime") != current["mtime"] or entry.get("size") != current["size"]:
        return None
    if entry.get('sha256') != current['sha256']:
        return None
    if entry.get("schema") != SCHEMA_VERSION:
        return None
    if entry.get('parser_version') != code_version(Path(__file__).resolve().parents[1]):
        return None
    report_name = str(entry.get("report") or "")
    report = library_root / report_name
    expected = entry.get('report_sha256')
    if report.is_file() and full_hash(report) == expected:
        return report
    organize_library(library_root)
    for candidate in library_root.glob("*.md"):
        if candidate.name == INDEX_NAME:
            continue
        try:
            if full_hash(candidate) == expected:
                entry["report"] = candidate.name
                changed = True
                if changed:
                    save_manifest(cache_root, manifest)
                return candidate
        except OSError:
            continue
    return None


def remember_report(save_path: Path, report: Path, cache_root: Path, expected_hash: str | None = None) -> None:
    with cache_lock(cache_root / 'md_library.lock'):
        _remember_report(save_path, report, cache_root, expected_hash)


def _remember_report(save_path: Path, report: Path, cache_root: Path, expected_hash: str | None):
    manifest = load_manifest(cache_root)
    reports = manifest.setdefault("reports", {})
    if not isinstance(reports, dict):
        reports = {}
        manifest["reports"] = reports
    fingerprint = save_fingerprint(save_path)
    if expected_hash and fingerprint['sha256'] != expected_hash:
        raise RuntimeError('存档已变化，未缓存旧报告，请重试')
    reports[str(save_path.resolve())] = {
        **fingerprint,
        "schema": SCHEMA_VERSION,
        "parser_version": code_version(Path(__file__).resolve().parents[1]),
        "report": report.name,
        "report_sha256": full_hash(report),
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


def canonical_report_name(country: object, date: object) -> str:
    country_part = re.sub(r'[<>:"/\\|?*\r\n\t]+', "_", str(country or "未知国家")).strip(" ._") or "未知国家"
    date_part = re.sub(r"[^\d-]+", "_", str(date or "未知日期")).strip(" ._") or "未知日期"
    return f"{country_part}_{date_part}_国家报告.md"


def _date_from_text(text: str) -> str:
    match = re.search(r"游戏日期[：:]\s*(\d{4})[.-](\d{1,2})[.-](\d{1,2})", text[:2000])
    if not match:
        return ""
    year, month, day = [int(part) for part in match.groups()]
    return f"{year:04d}-{month:02d}-{day:02d}"


def _country_from_text(text: str) -> str:
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
        if len(cells) < 2 or cells[0] in {"序", "---", ""}:
            continue
        country = cells[1]
        if country and country not in {"国家", "---"}:
            country = re.sub(r"\s*\([A-Z0-9_]{2,}\)\s*$", "", country).strip()
            if re.fullmatch(r"[A-Z]{2,4}", country):
                return country_names.display_name(country)
            return country
    return ""


def report_identity_from_content(report: Path) -> tuple[str, str]:
    try:
        text = report.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "", ""
    return _country_from_text(text), _date_from_text(text)


def report_identity(report: Path) -> tuple[str, str]:
    pattern = re.compile(r"(.+?)_(\d{4}-\d{2}-\d{2})_(?:体系化国家报告|国家报告)(?:_第\d+次导出)?\.md$")
    match = pattern.match(report.name)
    if match:
        country = match.group(1)
        content_country, content_date = ("", "")
        if re.fullmatch(r"[A-Z]{2,4}", country) or not re.search(r"[\u4e00-\u9fff]", country):
            content_country, content_date = report_identity_from_content(report)
        if re.fullmatch(r"[A-Z]{2,4}", country) or (content_country and not re.search(r"[\u4e00-\u9fff]", country)):
            return content_country or country, content_date or match.group(2)
        return country, match.group(2)
    content_country, content_date = report_identity_from_content(report)
    if content_country and content_date:
        return content_country, content_date
    return "未知", "未知"


def organize_library(library_root: Path) -> dict[str, int]:
    library_root.mkdir(parents=True, exist_ok=True)
    normalize_legacy_names(library_root)
    archive = library_root / ARCHIVE_DIR_NAME
    renamed = 0
    archived = 0
    by_identity: dict[tuple[str, str], list[Path]] = {}
    for report in library_root.glob("*.md"):
        if report.name == INDEX_NAME:
            continue
        country, date = report_identity(report)
        if country == "未知" or date == "未知":
            continue
        by_identity.setdefault((country, date), []).append(report)
    for (country, date), reports in by_identity.items():
        canonical = library_root / canonical_report_name(country, date)
        keep = max(reports, key=lambda item: item.stat().st_mtime)
        archive.mkdir(parents=True, exist_ok=True)
        for report in reports:
            if report == keep:
                continue
            target = archive / report.name
            if target.exists():
                target = archive / f"{report.stem}_{datetime.fromtimestamp(report.stat().st_mtime).strftime('%Y%m%d%H%M%S')}{report.suffix}"
            report.rename(target)
            archived += 1
        if keep.name != canonical.name:
            if canonical.exists():
                target = archive / f"{canonical.stem}_{datetime.fromtimestamp(canonical.stat().st_mtime).strftime('%Y%m%d%H%M%S')}{canonical.suffix}"
                canonical.rename(target)
                archived += 1
            keep.rename(canonical)
            renamed += 1
    return {"renamed": renamed, "archived": archived}


def write_index(library_root: Path) -> Path:
    library_root.mkdir(parents=True, exist_ok=True)
    organize_library(library_root)
    reports = sorted(
        [item for item in library_root.glob("*.md") if item.name != INDEX_NAME],
        key=lambda item: (report_identity(item)[0], report_identity(item)[1]),
    )
    by_country: dict[str, list[Path]] = {}
    for report in reports:
        country, _date = report_identity(report)
        by_country.setdefault(country, []).append(report)
    lines = [
        "# Victoria 3 存档 MD 资料库",
        "",
        f"- 更新时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- 报告数量：{len(reports)}",
        f"- 重复旧报告归档：`{ARCHIVE_DIR_NAME}`",
        "- 用途：给不能访问本地 API 的聊天环境直接读取。这里尽量只放 Markdown 报告，不放 CSV/JSON 表格。",
        "",
    ]
    for country in sorted(by_country):
        country_reports = sorted(by_country[country], key=lambda item: report_identity(item)[1], reverse=True)
        lines.extend(["", f"## {country}", "", "| 游戏日期 | 文件 | 修改时间 | 大小 |", "|---|---|---|---:|"])
        for report in country_reports:
            _country, date = report_identity(report)
            modified = datetime.fromtimestamp(report.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            lines.append(f"| {date} | `{report.name}` | {modified} | {file_size_label(report.stat().st_size)} |")
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
        try:
            if full_hash(document) == full_hash(final_report):
                return final_report
        except OSError:
            pass
        archive = library_root / ARCHIVE_DIR_NAME
        archive.mkdir(parents=True, exist_ok=True)
        archived = archive / f"{final_report.stem}_{datetime.fromtimestamp(final_report.stat().st_mtime).strftime('%Y%m%d%H%M%S')}{final_report.suffix}"
        final_report.rename(archived)
    if document.resolve() != final_report.resolve():
        shutil.copy2(document, final_report)
    return final_report
