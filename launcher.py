# -*- coding: utf-8 -*-
"""简洁双击启动器：一键导出 / API 深度报表。"""

from __future__ import annotations

import base64
import getpass
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import analyze


CONFIG_DIR = Path.home() / ".vic3-save-analyzer"
CONFIG_FILE = CONFIG_DIR / "api_config.json"

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
DESKTOP_REPORT_ROOT = Path.home() / "Desktop" / "Victoria3存档报告"


class ProgressPrinter:
    def __init__(self) -> None:
        self.started = time.time()
        self.last_percent = -1

    def __call__(self, percent: int, label: str) -> None:
        percent = max(0, min(100, int(percent)))
        elapsed = max(time.time() - self.started, 0.1)
        if percent > 0:
            remaining = max((elapsed / percent) * (100 - percent), 0)
            eta = f"{int(remaining // 60):02d}:{int(remaining % 60):02d}"
        else:
            eta = "--:--"
        if percent != self.last_percent:
            print(f"[{percent:3d}%] {label}，预计剩余 {eta}")
            self.last_percent = percent


def clear() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def pause() -> None:
    try:
        input("\n按回车返回...")
    except EOFError:
        return


def ask(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        return ""


def line(title: str = "") -> None:
    if title:
        print(title)
    print("-" * 42)


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
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
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
        print(f"已保存 API 设置到 C 盘配置：{CONFIG_FILE}")
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


def normalize_chat_endpoint(config: dict) -> str:
    base_url = (config.get("base_url") or DEFAULT_PROVIDER["base_url"]).strip().rstrip("/")
    endpoint = (config.get("endpoint") or DEFAULT_PROVIDER["endpoint"]).strip()
    if base_url.endswith("/chat/completions"):
        return base_url
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    return base_url + endpoint


def prepare_desktop_output(path: Path) -> Path:
    run_dir = DESKTOP_REPORT_ROOT / f"{path.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    analyze.REPORT_DIR = run_dir
    return run_dir


def copy_to_category(path: Path, target_dir: Path) -> None:
    if path and path.exists():
        target_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target_dir / path.name)


def categorize_run_outputs(run_dir: Path, quick_report: Path | None, quick_outputs: dict[str, Path], outputs: dict[str, Path]) -> None:
    categories = {
        "01_总览文档": ["systems_document", "systems_report"],
        "02_快速报告": ["summary_json", "countries_csv", "great_powers_csv", "states_csv", "buildings_csv", "laws_csv"],
        "03_经济公司": ["major_countries", "building_summary", "building_details", "companies"],
        "04_人口社会": ["population_summary", "population_by_type", "population_by_culture", "population_by_religion", "pops_csv", "pops_by_type_csv", "pops_by_culture_csv", "pops_by_religion_csv"],
        "05_制度外交科技战争": [
            "laws",
            "interest_groups",
            "technology",
            "relations",
            "pacts",
            "wars",
            "war_participants",
            "diplomatic_plays",
            "war_costs",
            "war_goals",
            "military_formations",
            "battles",
            "battle_casualties",
        ],
        "06_机器数据": ["systems_summary"],
    }
    if quick_report:
        copy_to_category(quick_report, run_dir / "02_快速报告")
    merged = {**quick_outputs, **outputs}
    for dirname, keys in categories.items():
        for key in keys:
            copy_to_category(merged.get(key), run_dir / dirname)


def run_combined_export() -> None:
    print("\n正在一键导出：快速报告 + 体系化国家文档...")
    path = analyze.find_latest_save()
    if not path:
        print("没有找到 Victoria 3 存档。")
        return
    progress = ProgressPrinter()
    progress(1, "找到最新存档")
    run_dir = prepare_desktop_output(path)
    progress(3, "创建桌面分类目录")
    txt = analyze.read_save(path)
    progress(18, "存档读取完成")
    quick_report, quick_outputs = analyze.build_report(path, txt, full_pops=False)
    progress(28, "快速报告完成")
    document, outputs = analyze.build_system_export(path, txt, limit=30, full_pops=True, progress=lambda p, label: progress(28 + int(p * 0.68), label))
    categorize_run_outputs(run_dir, quick_report, quick_outputs, outputs)
    progress(100, "分类复制完成")
    print("\n一键导出完成。")
    print(f"桌面分类目录：{run_dir}")
    print(f"快速报告：{quick_report}")
    print(f"快速摘要 JSON：{quick_outputs['summary_json']}")
    print(f"体系文档：{document}")
    print(f"表格索引：{outputs['systems_report']}")
    print(f"总索引 JSON：{outputs['systems_summary']}")
    try:
        os.startfile(document)
        os.startfile(run_dir)
    except OSError:
        pass


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
        "laws": 35_000,
        "interest_groups": 35_000,
        "relations": 35_000,
        "pacts": 35_000,
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
                    "公司与企业、建筑部门、人口职业、文化宗教、法律制度、利益集团、科技、外交关系、"
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


def run_api_analysis(config: dict) -> None:
    print("\n正在生成本地分类数据并准备 API 报表，大存档可能需要几分钟...")
    path = analyze.find_latest_save()
    if not path:
        print("没有找到 Victoria 3 存档。")
        return
    progress = ProgressPrinter()
    progress(1, "找到最新存档")
    run_dir = prepare_desktop_output(path)
    progress(3, "创建桌面分类目录")
    txt = analyze.read_save(path)
    progress(18, "存档读取完成")
    document, outputs = analyze.build_system_export(path, txt, limit=30, full_pops=True, progress=lambda p, label: progress(18 + int(p * 0.55), label))
    categorize_run_outputs(run_dir, None, {}, outputs)
    progress(75, "本地体系数据已分类")
    print("正在调用 API 生成分类报表...")
    api_content = compact_system_bundle_for_api(document, outputs)
    try:
        answer = call_chat_api(config, api_content)
    except Exception as exc:
        print(f"API 分析失败：{exc}")
        print(f"本地体系文档仍可查看：{document}")
        return

    out = document.with_name(document.stem + "_api_tables.md")
    out.write_text("# API 深挖分类报表\n\n" + answer + "\n", encoding="utf-8")
    copy_to_category(out, run_dir / "01_总览文档")
    progress(100, "API 报表完成")
    print("\nAPI 报表完成。")
    print(f"桌面分类目录：{run_dir}")
    print(f"API报表：{out}")
    try:
        os.startfile(out)
    except OSError:
        pass


def api_menu() -> None:
    while True:
        clear()
        config = load_config()
        line("Victoria 3 存档读取器 - API 深度报表")
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


def main() -> None:
    while True:
        clear()
        config = load_config()
        line("Victoria 3 存档读取器")
        print(f"API：{saved_label(config)}")
        print()
        print("[1] 一键导出：快速报告 + 体系化文档")
        print("[2] API 深度报表")
        print("[0] 退出")
        choice = ask("\n选择：").strip()
        if not choice:
            sys.exit(0)
        if choice == "1":
            run_combined_export()
            pause()
        elif choice == "2":
            api_menu()
        elif choice == "0":
            sys.exit(0)


if __name__ == "__main__":
    main()
