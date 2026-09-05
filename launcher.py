# -*- coding: utf-8 -*-
"""简洁双击启动器：一键导出 / API 深度报表。"""

from __future__ import annotations

import base64
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import analyze
from vic3_analyzer import external_tools, md_library, save_catalog, terminal_ui
from vic3_analyzer.progress import ProgressPrinter


APP_VERSION = "0.3"
PROJECT_DIR = Path(__file__).resolve().parent
CONFIG_DIR = PROJECT_DIR / "config"
CONFIG_FILE = CONFIG_DIR / "api_config.json"
LEGACY_CONFIG_FILE = Path.home() / ".vic3-save-analyzer" / "api_config.json"
SAVE_PREVIEW_CACHE: dict[tuple[str, float, int], dict] = {}
PREVIEW_BYTES = 512_000

PROVIDERS = {
    "1": {
        "provider": "DeepSeek",
        "label": "DeepSeek V4 Flash",
        "base_url": "https://api.deepseek.com",
        "endpoint": "/chat/completions",
        "model": "deepseek-v4-flash",
        "hint": "推荐：速度快，上下文很长，适合完整存档报告。",
    },
    "2": {
        "provider": "DeepSeek",
        "label": "DeepSeek V4 Pro",
        "base_url": "https://api.deepseek.com",
        "endpoint": "/chat/completions",
        "model": "deepseek-v4-pro",
        "hint": "更深：适合社会学、国际关系长文档分析，速度会慢一些。",
    },
    "3": {
        "provider": "OpenAI",
        "label": "OpenAI",
        "base_url": "https://api.openai.com",
        "endpoint": "/v1/chat/completions",
        "model": "gpt-5",
        "hint": "使用 OpenAI 兼容聊天接口。",
    },
}
DEFAULT_PROVIDER = PROVIDERS["1"]
EXPORT_ROOT = PROJECT_DIR / "exports"
DATA_CACHE_ROOT = PROJECT_DIR / "data_cache"
DESKTOP_MD_ROOT = Path.home() / "Desktop" / "Victoria3存档MD报告"
MD_CACHE_ROOT = DATA_CACHE_ROOT / "md_library"

COMBINED_EXPORT_STEPS = [
    (1, "定位存档"),
    (18, "读取存档"),
    (20, "建目录"),
    (28, "生成快速报告"),
    (48, "国家与经济"),
    (67, "人口结构"),
    (78, "市场与政治"),
    (83, "外交战争"),
    (87, "写表格"),
    (96, "写文档"),
    (97, "复制文件"),
    (100, "完成"),
]

API_EXPORT_STEPS = [
    (1, "定位存档"),
    (18, "读取存档"),
    (20, "建目录"),
    (35, "国家与经济"),
    (55, "人口结构"),
    (65, "市场政治"),
    (72, "外交战争"),
    (75, "复制文件"),
    (90, "API 生成"),
    (100, "完成"),
]


def clear() -> None:
    terminal_ui.clear()


def pause() -> None:
    terminal_ui.pause()


def ask(prompt: str) -> str:
    return terminal_ui.ask(prompt)


def line(title: str = "") -> None:
    terminal_ui.title(title)


def mask(value: str | None) -> str:
    if not value:
        return "未保存"
    return "*" * min(max(len(value), 8), 24)


def encode_secret(secret: str) -> str:
    return "b64:" + base64.b64encode(secret.encode("utf-8")).decode("ascii")


def decode_secret(value: str | None) -> str:
    if not value:
        return ""
    if value.startswith("b64:"):
        return base64.b64decode(value[4:].encode("ascii")).decode("utf-8")
    return value


def load_config() -> dict:
    source = CONFIG_FILE if CONFIG_FILE.exists() else LEGACY_CONFIG_FILE
    if not source.exists():
        return {}
    try:
        return json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_config(config: dict) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    if os.name == "nt":
        os.system(f'attrib +h "{CONFIG_FILE}" >nul 2>nul')


def saved_label(config: dict) -> str:
    if not config.get("api_key"):
        return "未保存"
    provider = config.get("provider") or "自定义"
    model = config.get("model") or "未指定模型"
    return f"{provider} / {model} / {mask(decode_secret(config.get('api_key')))}"


def choose_provider(old: dict) -> dict:
    line("API 服务")
    for key, preset in PROVIDERS.items():
        print(f"[{key}] {preset['label']}  {preset['hint']}")
    print("[4] 自定义 OpenAI 兼容接口")
    default = "1"
    choice = ask(f"\n选择 [{default}]: ").strip() or default
    if choice in PROVIDERS:
        return dict(PROVIDERS[choice])
    custom_base = ask(f"API 地址 [{old.get('base_url') or 'https://api.deepseek.com'}]: ").strip() or old.get("base_url") or "https://api.deepseek.com"
    custom_endpoint = ask(f"聊天路径 [{old.get('endpoint') or '/chat/completions'}]: ").strip() or old.get("endpoint") or "/chat/completions"
    custom_model = ask(f"模型 [{old.get('model') or 'deepseek-v4-flash'}]: ").strip() or old.get("model") or "deepseek-v4-flash"
    return {
        "provider": "自定义",
        "label": "自定义",
        "base_url": custom_base,
        "endpoint": custom_endpoint,
        "model": custom_model,
        "hint": "",
    }


def input_api_config(save: bool) -> dict | None:
    old = load_config()
    print()
    preset = choose_provider(old)
    print("\n密钥设置")
    print("API Key 输入时不会显示。")
    try:
        api_key = getpass.getpass("API Key: ").strip()
    except EOFError:
        api_key = ""
    if not api_key:
        print("没有输入 API Key。")
        return None
    config = {
        "provider": preset["provider"],
        "label": preset["label"],
        "base_url": preset["base_url"],
        "endpoint": preset["endpoint"],
        "model": preset["model"],
        "api_key": encode_secret(api_key),
        "saved_at": datetime.now().isoformat(timespec="seconds"),
    }
    if save:
        save_config(config)
        print(f"已保存 API 设置：{CONFIG_FILE}")
    return config


def saved_api_config() -> dict | None:
    config = load_config()
    if not config.get("api_key"):
        print("还没有保存过 API。")
        return None
    print("\n使用上次保存的 API")
    print(f"服务：{config.get('provider') or '自定义'}")
    print(f"地址：{config.get('base_url') or DEFAULT_PROVIDER['base_url']}")
    print(f"模型：{config.get('model') or DEFAULT_PROVIDER['model']}")
    print(f"API Key：{mask(decode_secret(config.get('api_key')))}")
    return config


def list_save_paths() -> list[Path]:
    return analyze.list_save_paths()


def file_size_label(size: int) -> str:
    return save_catalog.file_size_label(size)


def save_source_label(path: Path) -> str:
    return save_catalog.save_source_label(path)


def read_save_preview_text(path: Path, max_bytes: int = PREVIEW_BYTES) -> str:
    return save_catalog._read_preview_text(path, max_bytes)


def preview_value(text: str, key: str) -> str:
    match = re.search(rf"(?m)^\s*{re.escape(key)}\s*=\s*(\"[^\"]*\"|[^\s{{}}]+)", text)
    if not match:
        return ""
    return match.group(1).strip().strip('"')


def filename_save_hint(path: Path) -> tuple[str, str]:
    return save_catalog.filename_save_hint(path)


def save_preview(path: Path) -> dict:
    stat = path.stat()
    cache_key = (str(path), stat.st_mtime, stat.st_size)
    cached = SAVE_PREVIEW_CACHE.get(cache_key)
    if cached:
        return cached
    preview = dict(save_catalog.preview(path, DATA_CACHE_ROOT, analyze.COUNTRY_NAMES))
    preview["path"] = path
    SAVE_PREVIEW_CACHE[cache_key] = preview
    return preview


def choose_save_path() -> Path | None:
    saves = list_save_paths()
    if not saves:
        print("没有找到 Victoria 3 存档。")
        return None

    previews = render_save_picker(saves, multi=False)

    choice = ask("\n选择：").strip()
    if not choice or choice == "0":
        return None
    if not choice.isdigit() or not (1 <= int(choice) <= len(previews)):
        print("选择无效。")
        return None
    return previews[int(choice) - 1]["path"]


def render_save_picker(saves: list[Path], multi: bool = False) -> list[dict]:
    print("\n正在读取存档列表...")
    previews = [save_preview(path) for path in saves]
    line(f"存档列表（{len(previews)} 个）")
    for index, item in enumerate(previews, 1):
        latest = "  最新" if index == 1 else ""
        print(f"{index:>2}. {item['country']}  {item['date']}  {item['source']}  {item['size']}  {item['path'].name}{latest}")
    print(" 0. 返回")
    if multi:
        print("\n可多选：1,3,5 或 2-6")
    return previews


def parse_selection(raw: str, total: int) -> list[int]:
    indexes: list[int] = []
    seen: set[int] = set()
    for part in re.split(r"[,\s，、]+", raw.strip()):
        if not part:
            continue
        if "-" in part:
            start_raw, end_raw = part.split("-", 1)
            if not start_raw.isdigit() or not end_raw.isdigit():
                continue
            start, end = int(start_raw), int(end_raw)
            if start > end:
                start, end = end, start
            candidates = range(start, end + 1)
        elif part.isdigit():
            candidates = [int(part)]
        else:
            continue
        for index in candidates:
            if 1 <= index <= total and index not in seen:
                indexes.append(index)
                seen.add(index)
    return indexes


def choose_save_paths_multi() -> list[Path]:
    saves = list_save_paths()
    if not saves:
        print("没有找到 Victoria 3 存档。")
        return []

    previews = render_save_picker(saves, multi=True)

    choice = ask("选择：").strip()
    if not choice or choice == "0":
        return []
    indexes = parse_selection(choice, len(previews))
    if not indexes:
        print("选择无效。")
        return []
    return [previews[index - 1]["path"] for index in indexes]


def normalize_chat_endpoint(config: dict) -> str:
    base_url = (config.get("base_url") or DEFAULT_PROVIDER["base_url"]).strip().rstrip("/")
    endpoint = (config.get("endpoint") or DEFAULT_PROVIDER["endpoint"]).strip()
    if base_url.endswith("/chat/completions"):
        return base_url
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    return base_url + endpoint


def unique_directory(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 1000):
        if path.suffix:
            candidate = path.with_name(f"{path.stem}_第{index}次导出{path.suffix}")
        else:
            candidate = path.with_name(f"{path.name}_第{index}次导出")
        if not candidate.exists():
            return candidate
    if path.suffix:
        return path.with_name(f"{path.stem}_{datetime.now().strftime('%H%M%S')}{path.suffix}")
    return path.with_name(f"{path.name}_{datetime.now().strftime('%H%M%S')}")


def prepare_export_output(path: Path, txt: str) -> Path:
    meta_info = analyze.meta(txt)
    countries = analyze.parse_countries(txt)
    player_id = analyze.player_country_id(txt, countries, str(meta_info["country"]))
    identity = analyze.save_identity(meta_info, countries, player_id)
    run_dir = unique_directory(EXPORT_ROOT / identity["label"])
    run_dir.mkdir(parents=True, exist_ok=True)
    analyze.REPORT_DIR = run_dir
    return run_dir


def desktop_md_label(path: Path) -> str:
    preview = save_preview(path)
    country = analyze.safe_filename_part(preview.get("country"), "未知国家")
    date = analyze.safe_filename_part(preview.get("date"), "未知日期")
    return f"{country}_{date}"


def prepare_desktop_md_output(path: Path) -> Path:
    DESKTOP_MD_ROOT.mkdir(parents=True, exist_ok=True)
    analyze.REPORT_DIR = DESKTOP_MD_ROOT
    return DESKTOP_MD_ROOT


def clean_desktop_md_temp_files() -> None:
    md_library.clean_temp_files(DESKTOP_MD_ROOT)


def write_desktop_md_index() -> Path:
    return md_library.write_index(DESKTOP_MD_ROOT)


def keep_only_md_report(run_dir: Path, document: Path, path: Path, outputs: dict[str, Path]) -> Path:
    stem = document.name
    if stem.endswith("_systems_document.md"):
        stem = stem[: -len("_systems_document.md")]
    else:
        stem = desktop_md_label(path)
    country, date = md_library.report_identity(document)
    final_name = md_library.canonical_report_name(country if country != "未知" else stem, date)
    final_report = md_library.copy_report_to_library(document, run_dir, final_name)
    generated = {Path(item).resolve() for item in outputs.values()}
    generated.add(document.resolve())
    for item in generated:
        if item != final_report.resolve() and item.exists() and item.is_file():
            item.unlink()
    clean_desktop_md_temp_files()
    write_desktop_md_index()
    return final_report


def copy_to_category(path: Path, target_dir: Path) -> None:
    if path and path.exists():
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target_dir / path.name)


def categorize_run_outputs(run_dir: Path, quick_report: Path | None, quick_outputs: dict[str, Path], outputs: dict[str, Path]) -> None:
    categories = {
        "01_总览索引": ["systems_document", "systems_report"],
        "02_国家总表": ["major_countries", "states"],
        "03_经济市场公司": [
            "building_summary",
            "building_details",
            "companies",
            "markets",
            "market_members",
            "market_states",
            "market_trade_goods",
        ],
        "04_人口社会政治": [
            "population_summary",
            "population_by_type",
            "population_by_culture",
            "population_by_religion",
            "interest_groups",
            "political_movements",
            "pops_csv",
            "pops_by_type_csv",
            "pops_by_culture_csv",
            "pops_by_religion_csv",
        ],
        "05_制度科技": ["laws", "technology"],
        "06_外交条约战争": [
            "relations",
            "pacts",
            "treaties",
            "treaty_articles",
            "diplomatic_plays",
            "war_goals",
            "wars",
            "war_participants",
            "war_costs",
            "military_formations",
            "battles",
            "battle_casualties",
        ],
        "07_快速报告": ["summary_json", "countries_csv", "great_powers_csv", "states_csv", "buildings_csv", "laws_csv"],
        "08_机器数据": ["systems_summary"],
    }
    if quick_report:
        copy_to_category(quick_report, run_dir / "07_快速报告")
    merged = {**quick_outputs, **outputs}
    for dirname, keys in categories.items():
        for key in keys:
            copy_to_category(merged.get(key), run_dir / dirname)


def print_combined_summary(started: float, run_dir: Path, quick_report: Path, quick_outputs: dict[str, Path], document: Path, outputs: dict[str, Path]) -> None:
    elapsed = ProgressPrinter._clock(time.time() - started)
    terminal_ui.done(
        [
            ("耗时", elapsed),
            ("文件夹", run_dir),
            ("主报告", document),
            ("表格索引", outputs["systems_report"]),
        ]
    )


def run_combined_export(path: Path | None = None) -> None:
    latest_mode = path is None
    print("\n导出中")
    if latest_mode:
        path = analyze.find_latest_save()
    if not path:
        print("没有找到 Victoria 3 存档。")
        return
    progress = ProgressPrinter(total_hint_seconds=240, steps=COMBINED_EXPORT_STEPS, title="完整导出")
    progress.start()
    txt = None
    try:
        progress(1, "找到最新存档" if latest_mode else f"已选择存档：{path.name}")
        progress(5, "读取并展开存档")
        txt = analyze.read_save(path)
        progress(18, "存档读取完成")
        run_dir = prepare_export_output(path, txt)
        progress(20, "创建分类目录")
        progress(21, "生成快速报告")
        quick_report, quick_outputs = analyze.build_report(path, txt, full_pops=False)
        progress(28, "快速报告完成")
        document, outputs = analyze.build_system_export(
            path,
            txt,
            limit=30,
            full_pops=True,
            progress=lambda p, label: progress(28 + int(p * 0.68), label),
        )
        progress(97, "复制到分类目录")
        categorize_run_outputs(run_dir, quick_report, quick_outputs, outputs)
        progress(100, "分类复制完成")
    except Exception as exc:
        progress.stop()
        terminal_ui.failed(exc)
        return
    finally:
        if txt is not None:
            analyze.clear_database_block_cache(txt)
    progress.stop()
    print_combined_summary(progress.started, run_dir, quick_report, quick_outputs, document, outputs)
    terminal_ui.open_folder(run_dir)


def print_md_only_summary(started: float, run_dir: Path, report: Path) -> None:
    elapsed = ProgressPrinter._clock(time.time() - started)
    terminal_ui.done([("耗时", elapsed), ("文件夹", run_dir), ("MD报告", report)])


def print_cached_md_summary(started: float, report: Path) -> None:
    elapsed = ProgressPrinter._clock(time.time() - started)
    terminal_ui.done([("耗时", elapsed), ("状态", "存档未变化，已复用资料库报告"), ("文件夹", DESKTOP_MD_ROOT), ("MD报告", report)])


def existing_valid_md_report_for_save(path: Path) -> Path | None:
    return md_library.cached_report_for_save(path, DESKTOP_MD_ROOT, MD_CACHE_ROOT)


def run_desktop_md_export(path: Path | None = None, open_folder: bool = True, quiet_summary: bool = False) -> Path | None:
    import api_server
    latest_mode = path is None
    print("\n导出全量 MD 数据文档")
    started = time.time()
    if latest_mode:
        path = analyze.find_latest_save()
    if not path:
        print("没有找到 Victoria 3 存档。")
        return None
    DESKTOP_MD_ROOT.mkdir(parents=True, exist_ok=True)
    cached = md_library.cached_report_for_save(path, DESKTOP_MD_ROOT, MD_CACHE_ROOT)
    if cached:
        clean_desktop_md_temp_files()
        write_desktop_md_index()
        if quiet_summary:
            print(f"完成：{cached.name}（缓存）")
        else:
            print_cached_md_summary(started, cached)
        if open_folder:
            terminal_ui.open_folder(DESKTOP_MD_ROOT)
        return cached
    progress = ProgressPrinter(total_hint_seconds=240, steps=COMBINED_EXPORT_STEPS, title="MD导出")
    progress.start()
    txt = None
    try:
        progress(1, "找到最新存档" if latest_mode else f"已选择存档：{path.name}")
        manifest = api_server.build_dataset(path, limit=0, full_pops=True, progress=lambda p, label: progress(int(p * .96), label if p < 100 else '写入MD报告'))
        run_dir = DESKTOP_MD_ROOT
        document = api_server.output_path(manifest, 'systems_document')
        identity = manifest['source']
        name = md_library.canonical_report_name(identity['game_country'], identity['game_date'])
        report = md_library.copy_report_to_library(document, run_dir, name)
        issues = md_library.validate_report(report)
        if issues:
            raise RuntimeError('报告校验失败：' + '；'.join(issues))
        from vic3_analyzer.fingerprint import full_hash
        if full_hash(path) != identity['sha256']:
            raise RuntimeError('存档已变化，请保存完成后重试')
        md_library.remember_report(path, report, MD_CACHE_ROOT, expected_hash=identity['sha256'])
        write_desktop_md_index()
        progress(100, "完成")
    except Exception as exc:
        progress.stop()
        terminal_ui.failed(exc)
        return None
    finally:
        if txt is not None:
            analyze.clear_database_block_cache(txt)
    progress.stop()
    if quiet_summary:
        elapsed = ProgressPrinter._clock(time.time() - started)
        print(f"完成：{report.name}（{elapsed}）")
    else:
        print_md_only_summary(progress.started, run_dir, report)
    if open_folder:
        terminal_ui.open_folder(run_dir)
    return report


def run_desktop_md_batch(paths: list[Path]) -> None:
    if not paths:
        return
    started = time.time()
    print(f"\n批量导出 MD：{len(paths)} 个存档")
    completed: list[Path] = []
    failed: list[tuple[Path, str]] = []
    for index, path in enumerate(paths, 1):
        print(f"\n[{index}/{len(paths)}] {path.name}")
        report = run_desktop_md_export(path, open_folder=False, quiet_summary=True)
        if report:
            completed.append(report)
        else:
            failed.append((path, "导出失败"))
    elapsed = ProgressPrinter._clock(time.time() - started)
    print("\n批量完成")
    print(f"耗时：{elapsed}")
    print(f"成功：{len(completed)}")
    print(f"失败：{len(failed)}")
    for failed_path, reason in failed:
        preview = save_preview(failed_path)
        print(f"  {preview.get('country', '未知国家')} {preview.get('date', '未知日期')} · {failed_path.name}：{reason}")
    print(f"位置：{DESKTOP_MD_ROOT}")
    terminal_ui.open_folder(DESKTOP_MD_ROOT)


def desktop_md_menu() -> None:
    while True:
        choice = terminal_ui.menu(
            f"Victoria 3 存档读取器 v{APP_VERSION}",
            [("1", "导出最新存档为单个 MD"), ("2", "选择多个存档批量导出 MD"), ("3", "整理资料库命名与索引"), ("4", "导出全部存档 MD"), ("0", "返回")],
            subtitle="MD 资料库",
            footer=f"输出位置：{DESKTOP_MD_ROOT}",
        )
        if not choice or choice == "0":
            return
        if choice == "1":
            run_desktop_md_export()
            pause()
        elif choice == "2":
            selected = choose_save_paths_multi()
            if selected:
                run_desktop_md_batch(selected)
            pause()
        elif choice == "3":
            result = md_library.organize_library(DESKTOP_MD_ROOT)
            index = write_desktop_md_index()
            terminal_ui.done([("重命名", result.get("renamed", 0)), ("归档重复", result.get("archived", 0)), ("索引", index), ("文件夹", DESKTOP_MD_ROOT)])
            terminal_ui.open_folder(DESKTOP_MD_ROOT)
            pause()
        elif choice == "4":
            paths = list_save_paths()
            if paths:
                run_desktop_md_batch(paths)
            else:
                print("没有找到 Victoria 3 存档。")
            pause()


def read_limited(path: Path, max_chars: int) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) > max_chars:
        return text[:max_chars] + "\n[后文已截断]\n"
    return text


def compact_system_bundle_for_api(document: Path, outputs: dict[str, Path]) -> str:
    parts = [
        "SYSTEM_DOCUMENT_MD:\n" + read_limited(document, 70_000),
        "SUMMARY_JSON:\n" + read_limited(outputs["systems_summary"], 35_000),
    ]
    csv_limits = {
        "major_countries": 35_000,
        "states": 35_000,
        "companies": 35_000,
        "population_summary": 35_000,
        "population_by_type": 35_000,
        "population_by_culture": 35_000,
        "population_by_religion": 25_000,
        "building_summary": 45_000,
        "building_details": 45_000,
        "markets": 35_000,
        "market_members": 35_000,
        "market_states": 45_000,
        "market_trade_goods": 45_000,
        "laws": 35_000,
        "interest_groups": 35_000,
        "political_movements": 35_000,
        "relations": 35_000,
        "pacts": 35_000,
        "treaties": 35_000,
        "treaty_articles": 45_000,
        "wars": 45_000,
        "war_participants": 45_000,
        "diplomatic_plays": 45_000,
        "war_costs": 45_000,
        "war_goals": 45_000,
        "military_formations": 45_000,
        "battles": 45_000,
        "battle_casualties": 45_000,
    }
    for key, max_chars in csv_limits.items():
        path = outputs.get(key)
        if path:
            parts.append(f"{key.upper()}_CSV:\n" + read_limited(path, max_chars))
    return "\n\n".join(parts)


def call_chat_api(config: dict, content: str) -> str:
    api_key = decode_secret(config.get("api_key"))
    model = config.get("model") or DEFAULT_PROVIDER["model"]
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "你是一个维多利亚3存档数据整理助手。请只基于给定结构化存档数据生成分类报表，"
                    "不要写游玩建议，不要写预测，不要写主观战略判断；缺失字段标注未读到。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "请生成一份分类数据报表，不要先做分析。按固定栏目输出：国家总表、GDP占比、历史变化、"
                    "公司与企业、建筑部门、市场总表、市场成员、州级贸易商品、人口职业、文化宗教、"
                    "法律制度、利益集团、政治运动、科技、外交关系、外交行动、正式条约、条约条款、"
                    "外交博弈、战争目标、军队编成、战斗记录、伤亡、战争成本、占领推进和州破坏度。"
                    "战争和历史战争必须融入外交与国家分表，列出战争状态、起止时间、参战方、战争支持度和消耗。"
                    "每一类先给表格，再给极短字段说明；不要提出下一步玩法。\n\n"
                    + content
                ),
            },
        ],
        "max_tokens": 16000,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        normalize_chat_endpoint(config),
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "vic3-save-analyzer/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"API 返回错误 {exc.code}: {detail[:1000]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"无法连接 API：{exc}") from exc

    result = json.loads(body)
    return result["choices"][0]["message"].get("content", "")


def print_api_summary(started: float, run_dir: Path, out: Path, document: Path, outputs: dict[str, Path]) -> None:
    elapsed = ProgressPrinter._clock(time.time() - started)
    print("\n完成")
    print(f"耗时：{elapsed}")
    print(f"文件夹：{run_dir}")
    print(f"API 报表：{out}")
    print(f"本地报告：{document}")
    print(f"表格索引：{outputs['systems_report']}")


def run_api_analysis(config: dict, path: Path | None = None) -> None:
    print("\nAPI 报表")
    if path is None:
        path = analyze.find_latest_save()
    if not path:
        print("没有找到 Victoria 3 存档。")
        return
    total_started = time.time()
    progress = ProgressPrinter(total_hint_seconds=300, steps=API_EXPORT_STEPS)
    progress.start()
    txt = None
    try:
        progress(1, f"准备存档：{path.name}")
        progress(5, "读取并展开存档")
        txt = analyze.read_save(path)
        progress(18, "存档读取完成")
        run_dir = prepare_export_output(path, txt)
        progress(20, "创建分类目录")
        document, outputs = analyze.build_system_export(
            path,
            txt,
            limit=30,
            full_pops=True,
            progress=lambda p, label: progress(18 + int(p * 0.55), label),
        )
        progress(73, "复制到分类目录")
        categorize_run_outputs(run_dir, None, {}, outputs)
        progress(75, "本地体系数据已分类")
    except Exception as exc:
        progress.stop()
        print(f"\n失败：{exc}")
        return
    finally:
        if txt is not None:
            analyze.clear_database_block_cache(txt)
    progress.stop()
    print("调用 API")
    api_content = compact_system_bundle_for_api(document, outputs)
    api_progress = ProgressPrinter(total_hint_seconds=90, steps=API_EXPORT_STEPS)
    api_progress.start()
    api_progress(80, "等待 API 生成深度报表")
    try:
        answer = call_chat_api(config, api_content)
    except Exception as exc:
        api_progress.stop()
        print(f"API 分析失败：{exc}")
        print(f"本地体系文档仍可查看：{document}")
        return

    out = document.with_name(document.stem + "_api_tables.md")
    out.write_text("# API 深挖分类报表\n\n" + answer + "\n", encoding="utf-8")
    copy_to_category(out, run_dir / "01_总览索引")
    api_progress(100, "API 报表完成")
    api_progress.stop()
    print_api_summary(total_started, run_dir, out, document, outputs)
    try:
        os.startfile(run_dir)
    except OSError:
        pass


def api_menu() -> None:
    while True:
        clear()
        config = load_config()
        line(f"Victoria 3 存档读取器 v{APP_VERSION} - API 深度报表")
        print(f"已保存：{saved_label(config)}")
        print()
        print("[1] 临时导入 API 并生成报表")
        print("[2] 导入 API、保存、并生成报表")
        print("[3] 使用上次保存的 API 生成报表")
        print("[0] 返回")
        choice = ask("\n选择：").strip()
        if not choice:
            return
        if choice == "1":
            cfg = input_api_config(save=False)
            if cfg:
                run_api_analysis(cfg)
            pause()
        elif choice == "2":
            cfg = input_api_config(save=True)
            if cfg:
                run_api_analysis(cfg)
            pause()
        elif choice == "3":
            cfg = saved_api_config()
            if cfg:
                run_api_analysis(cfg)
            pause()
        elif choice == "0":
            return


def run_local_data_api() -> None:
    terminal_ui.section("本地数据 API")
    print("主地址：http://127.0.0.1:8765")
    print("给工具读取：http://127.0.0.1:8765/api/package?dataset=latest")
    print("SQL 示例：http://127.0.0.1:8765/api/sql/table/major_countries?dataset=latest&limit=20")
    print(f"数据仓库：{DATA_CACHE_ROOT}")
    print("按 Ctrl+C 停止")
    script = Path(__file__).with_name("api_server.py")
    try:
        subprocess.run([sys.executable, str(script), "serve"])
    except KeyboardInterrupt:
        print("\n已停止")


def run_public_data_api() -> None:
    print("\n公网数据 API")
    print("会生成一个带密钥的 HTTPS 地址。窗口不要关，关了公网地址就失效。")
    script = Path(__file__).with_name("public_api.py")
    try:
        subprocess.run([sys.executable, str(script)])
    except KeyboardInterrupt:
        print("\n已停止")


def run_data_api_command(*args: str) -> None:
    script = Path(__file__).with_name("api_server.py")
    subprocess.run([sys.executable, str(script), *args])


def print_accelerator_status() -> None:
    status = external_tools.status(PROJECT_DIR)
    terminal_ui.title("读取加速诊断")
    active = status.get("active_backends", [])
    print("当前后端：" + ("、".join(active) if isinstance(active, list) and active else "Python 回退"))
    rows = [
        ("Rust 顶层块扫描器", status.get("rust_scanner") or "未编译"),
        ("Jomini 专用提取器", status.get("jomini_extractor") or "未安装"),
        ("Garibaldi 原生提取器", status.get("garibaldi_native_extractor") or "未安装"),
        ("Garibaldi/Rakaly melter", status.get("garibaldi_melter") or "未安装"),
        ("Rakaly CLI", status.get("rakaly_cli") or "未安装"),
        ("数据缓存", DATA_CACHE_ROOT),
    ]
    for name, value in rows:
        print(f"{name}：{value}")


def data_api_menu() -> None:
    while True:
        choice = terminal_ui.menu(
            f"Victoria 3 存档读取器 v{APP_VERSION}",
            [
                ("1", "为最新存档建库"),
                ("2", "选择存档建库"),
                ("3", "查看已有数据包"),
                ("4", "启动本地 API"),
                ("5", "启动公网 API"),
                ("6", "查看内容复用索引"),
                ("7", "读取加速诊断"),
                ("0", "返回"),
            ],
            subtitle="数据 API",
            footer=f"数据仓库：{DATA_CACHE_ROOT}",
        )
        if not choice or choice == "0":
            return
        if choice == "1":
            run_data_api_command("build", "--save", "latest")
            pause()
        elif choice == "2":
            selected = choose_save_path()
            if selected:
                run_data_api_command("build", "--save", str(selected))
            pause()
        elif choice == "3":
            run_data_api_command("list")
            pause()
        elif choice == "4":
            run_local_data_api()
            pause()
        elif choice == "5":
            run_public_data_api()
            pause()
        elif choice == "6":
            run_data_api_command("content")
            pause()
        elif choice == "7":
            print_accelerator_status()
            pause()


def full_export_menu() -> None:
    while True:
        choice = terminal_ui.menu(
            f"Victoria 3 存档读取器 v{APP_VERSION}",
            [("1", "导出最新存档完整资料"), ("2", "选择一个存档完整导出"), ("0", "返回")],
            subtitle="完整导出",
            footer=f"输出位置：{EXPORT_ROOT}",
        )
        if not choice or choice == "0":
            return
        if choice == "1":
            run_combined_export()
            pause()
        elif choice == "2":
            selected = choose_save_path()
            if selected:
                run_combined_export(selected)
            pause()


def ai_api_menu() -> None:
    while True:
        choice = terminal_ui.menu(
            f"Victoria 3 存档读取器 v{APP_VERSION}",
            [("1", "生成 API 深度报表"), ("2", "管理本地/公网数据 API"), ("0", "返回")],
            subtitle="AI / API",
            footer=f"API：{saved_label(load_config())}",
        )
        if not choice or choice == "0":
            return
        if choice == "1":
            api_menu()
        elif choice == "2":
            data_api_menu()


def run_v03_acceptance_check() -> None:
    terminal_ui.section("v0.3 验收检查")
    print("会检查最新存档导出、缓存复用、换范围复用、本地 API 表读取和历史对照。")
    print("结果写入 F 盘项目的 data_cache/benchmarks，不会上传 GitHub。")
    script = PROJECT_DIR / "scripts" / "v03_acceptance.py"
    try:
        subprocess.run([sys.executable, str(script)], cwd=str(PROJECT_DIR))
    except KeyboardInterrupt:
        print("\n已停止")


def main() -> None:
    while True:
        config = load_config()
        choice = terminal_ui.menu(
            f"Victoria 3 存档读取器 v{APP_VERSION}",
            [("1", "导出最新 MD"), ("2", "选择存档批量导出"), ("3", "资料库与设置"), ("0", "退出")],
            footer=f"报告位置：{DESKTOP_MD_ROOT}",
        )
        if not choice:
            sys.exit(0)
        if choice == "1":
            run_desktop_md_export()
            pause()
        elif choice == "2":
            selected = choose_save_paths_multi()
            if selected:
                run_desktop_md_batch(selected)
            pause()
        elif choice == "3":
            settings_menu()
        elif choice == "0":
            sys.exit(0)


def settings_menu() -> None:
    while True:
        choice = terminal_ui.menu(
            '资料库与设置',
            [('1', 'MD 资料库'), ('2', '完整分类导出'), ('3', 'AI / API'), ('4', '历史存档对照'), ('5', 'v0.3 验收检查'), ('0', '返回')],
        )
        if choice in {'', '0'}:
            return
        {'1': desktop_md_menu, '2': full_export_menu, '3': ai_api_menu, '4': history_menu, '5': run_v03_acceptance_check}.get(choice, lambda: None)()


def history_menu() -> None:
    import api_server
    from vic3_analyzer import history
    from vic3_analyzer.cache_io import atomic_bytes
    datasets = api_server.list_datasets()
    if len(datasets) < 2:
        print('请先导出同一局游戏的至少两个存档。')
        pause()
        return
    for i, item in enumerate(datasets, 1):
        source = item['source']
        print(f"{i}. {source.get('country')}  {source.get('date')}")
    print()
    print('输入两个编号生成两点对照；输入三个以上编号生成战役时间线。')
    raw = terminal_ui.ask('选择同一局存档编号（如 2,1 或 5,4,3,2,1）：')
    try:
        indices = [int(s.strip()) - 1 for s in raw.replace('，', ',').split(',')]
        if len(indices) < 2 or len(set(indices)) != len(indices) or any(i < 0 or i >= len(datasets) for i in indices):
            raise ValueError('请选择至少两个不同的存档')
        selected = [datasets[i] for i in indices]
        first, second = selected[0], selected[-1]
        if len(selected) == 2:
            body = history.compare(first, second)
            prefix = "历史对照"
        else:
            body = history.timeline(selected)
            prefix = "战役时间线"
        name = analyze.safe_filename_part(f"{prefix}_{first['source']['country']}_{first['source']['date']}_至_{second['source']['country']}_{second['source']['date']}")
        target = DESKTOP_MD_ROOT / (name + '.md')
        atomic_bytes(target, body.encode('utf-8'))
        terminal_ui.done([('报告', target)])
        terminal_ui.open_folder(DESKTOP_MD_ROOT)
    except (ValueError, OSError, RuntimeError) as exc:
        terminal_ui.failed(exc)
    pause()


if __name__ == "__main__":
    main()
