# -*- coding: utf-8 -*-
"""简洁双击启动器：一键导出 / API 深度报表。"""

from __future__ import annotations

import base64
import getpass
import json
import os
import re
import shutil
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import analyze


APP_VERSION = "0.1"
CONFIG_DIR = Path.home() / ".vic3-save-analyzer"
CONFIG_FILE = CONFIG_DIR / "api_config.json"
SAVE_PREVIEW_CACHE: dict[tuple[str, float, int], dict] = {}

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

COMBINED_EXPORT_STEPS = [
    (1, "定位存档"),
    (18, "读取并展开存档"),
    (20, "创建输出目录"),
    (28, "生成快速报告"),
    (48, "整理国家、州、经济建筑"),
    (67, "扫描人口、职业、文化、宗教"),
    (78, "整理市场、公司、政治运动、条约"),
    (83, "整理外交、战争、军队、战斗"),
    (87, "写出 CSV 表格"),
    (96, "写出体系化文档"),
    (97, "复制到桌面分类目录"),
    (100, "完成并输出结论"),
]

API_EXPORT_STEPS = [
    (1, "定位存档"),
    (18, "读取并展开存档"),
    (20, "创建输出目录"),
    (35, "整理国家、州、经济建筑"),
    (55, "扫描人口、社会结构"),
    (65, "整理市场、政治、条约"),
    (72, "整理外交、战争、军队"),
    (75, "复制本地分类数据"),
    (90, "等待 API 生成深度报表"),
    (100, "完成并输出结论"),
]


class ProgressPrinter:
    def __init__(self, total_hint_seconds: int = 180, steps: list[tuple[int, str]] | None = None) -> None:
        self.started = time.time()
        self.total_hint_seconds = total_hint_seconds
        self.percent = 0
        self.label = "准备"
        self.steps = steps or [(100, "完成")]
        self.last_percent = -1
        self.last_label = ""
        self.last_print = 0.0
        self.line_len = 0
        self.has_line = False
        self.done = False
        self.lock = threading.Lock()
        self.thread: threading.Thread | None = None

    def start(self) -> None:
        self.done = False
        print(f"流程：{len(self.steps)} 步，最后一步是「{self.steps[-1][1]}」")
        self.thread = threading.Thread(target=self._heartbeat, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        with self.lock:
            self.done = True
        if self.thread:
            self.thread.join(timeout=0.3)
        if self.has_line:
            print()
            self.has_line = False

    def _heartbeat(self) -> None:
        while True:
            time.sleep(8)
            with self.lock:
                if self.done:
                    return
                percent = self.percent
                label = self.label
            self(percent, label, force=True, remember=False)

    @staticmethod
    def _clock(seconds: float) -> str:
        seconds = max(0, int(seconds))
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    @staticmethod
    def _short_label(label: str) -> str:
        scan = re.search(r"扫描(人口|战斗)条目\s+([\d,]+)/([\d,]+)", label)
        if scan:
            kind, done_raw, total_raw = scan.groups()
            done = int(done_raw.replace(",", ""))
            total = int(total_raw.replace(",", ""))
            left = max(total - done, 0)
            return f"{kind}扫描 {done_raw}/{total_raw}，剩 {left:,} 条"
        if "仍在处理" in label:
            return label.replace("，仍在处理", "")
        if len(label) > 32:
            return label[:31] + "..."
        return label

    @staticmethod
    def _fit_line(text: str, previous_len: int) -> tuple[str, str]:
        width = max(shutil.get_terminal_size((96, 20)).columns - 1, 48)
        if len(text) > width:
            text = text[: max(width - 3, 1)] + "..."
        padding = " " * max(0, previous_len - len(text))
        return text, padding

    def _step(self, percent: int) -> tuple[int, str]:
        for index, (upper, name) in enumerate(self.steps, 1):
            if percent <= upper:
                return index, name
        return len(self.steps), self.steps[-1][1]

    def __call__(self, percent: int, label: str, force: bool = False, remember: bool = True) -> None:
        percent = max(0, min(100, int(percent)))
        now = time.time()
        with self.lock:
            self.percent = max(self.percent, percent)
            if remember:
                self.label = label
            percent = self.percent
            should_print = (
                force
                or percent != self.last_percent
                or label != self.last_label
                or now - self.last_print >= 6
            )
            if not should_print:
                return
            self.last_percent = percent
            self.last_label = label
            self.last_print = now
        step_index, step_name = self._step(percent)
        detail = self._short_label(label)
        current = detail or step_name
        if current == step_name:
            current = step_name
        text = (
            f"进度 {percent:3d}%  "
            f"步骤 {step_index:02d}/{len(self.steps):02d}  "
            f"{current}"
        )
        text, padding = self._fit_line(text, self.line_len)
        print("\r" + text + padding, end="", flush=True)
        self.line_len = len(text)
        self.has_line = True


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


def list_save_paths() -> list[Path]:
    if not analyze.SAVE_DIR.exists():
        return []
    return sorted(analyze.SAVE_DIR.glob("*.v3"), key=lambda item: item.stat().st_mtime, reverse=True)


def save_preview(path: Path) -> dict:
    stat = path.stat()
    cache_key = (str(path), stat.st_mtime, stat.st_size)
    cached = SAVE_PREVIEW_CACHE.get(cache_key)
    if cached:
        return cached
    txt = None
    try:
        txt = analyze.read_save(path)
        meta_info = analyze.meta(txt)
        countries = analyze.parse_countries(txt)
        player_id = analyze.player_country_id(txt, countries, str(meta_info["country"]))
        identity = analyze.save_identity(meta_info, countries, player_id)
        preview = {
            "path": path,
            "country": identity["country"],
            "date": identity["date"],
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "status": "可读",
        }
        SAVE_PREVIEW_CACHE[cache_key] = preview
        return preview
    except Exception as exc:
        preview = {
            "path": path,
            "country": "读取失败",
            "date": "未知日期",
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            "status": str(exc)[:40],
        }
        SAVE_PREVIEW_CACHE[cache_key] = preview
        return preview
    finally:
        if txt is not None:
            analyze.clear_database_block_cache(txt)


def choose_save_path() -> Path | None:
    saves = list_save_paths()
    if not saves:
        print("没有找到 Victoria 3 存档。")
        return None

    print("\n正在扫描存档列表，只读取国家和游戏日期...")
    previews = []
    for index, path in enumerate(saves, 1):
        text = f"扫描存档 {index}/{len(saves)}，剩 {len(saves) - index} 个：{path.name}"
        print("\r" + text + " " * 30, end="", flush=True)
        previews.append(save_preview(path))
    print()

    line("选择要导出的存档")
    for index, item in enumerate(previews, 1):
        latest = " 最新" if index == 1 else ""
        print(f"[{index}] {item['country']} | {item['date']} | {item['modified']} | {item['path'].name}{latest}")
    print("[0] 返回")

    choice = ask("\n选择：").strip()
    if not choice or choice == "0":
        return None
    if not choice.isdigit() or not (1 <= int(choice) <= len(previews)):
        print("选择无效。")
        return None
    return previews[int(choice) - 1]["path"]


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
        candidate = path.with_name(f"{path.name}_第{index}次导出")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{path.name}_{datetime.now().strftime('%H%M%S')}")


def prepare_desktop_output(path: Path, txt: str) -> Path:
    meta_info = analyze.meta(txt)
    countries = analyze.parse_countries(txt)
    player_id = analyze.player_country_id(txt, countries, str(meta_info["country"]))
    identity = analyze.save_identity(meta_info, countries, player_id)
    run_dir = unique_directory(DESKTOP_REPORT_ROOT / identity["label"])
    run_dir.mkdir(parents=True, exist_ok=True)
    analyze.REPORT_DIR = run_dir
    return run_dir


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
    print("\n结论：一键导出完成。")
    print(f"总耗时：{elapsed}")
    print("最后一步：复制全部报告和表格到桌面分类目录。")
    print(f"输出目录：{run_dir}")
    print(f"主报告：{document}")
    print(f"表格索引：{outputs['systems_report']}")
    print(f"快速报告：{quick_report}")
    print(f"总索引 JSON：{outputs['systems_summary']}")
    print(f"建议先打开：{run_dir / '01_总览索引'}")


def run_combined_export(path: Path | None = None) -> None:
    latest_mode = path is None
    print("\n正在导出：快速报告 + 体系化国家文档...")
    if latest_mode:
        path = analyze.find_latest_save()
    if not path:
        print("没有找到 Victoria 3 存档。")
        return
    progress = ProgressPrinter(total_hint_seconds=240, steps=COMBINED_EXPORT_STEPS)
    progress.start()
    txt = None
    try:
        progress(1, "找到最新存档" if latest_mode else f"已选择存档：{path.name}")
        progress(5, "读取并展开存档")
        txt = analyze.read_save(path)
        progress(18, "存档读取完成")
        run_dir = prepare_desktop_output(path, txt)
        progress(20, "创建桌面分类目录")
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
        progress(97, "复制到桌面分类目录")
        categorize_run_outputs(run_dir, quick_report, quick_outputs, outputs)
        progress(100, "分类复制完成")
    except Exception as exc:
        progress.stop()
        print(f"\n导出失败：{exc}")
        return
    finally:
        if txt is not None:
            analyze.clear_database_block_cache(txt)
    progress.stop()
    print_combined_summary(progress.started, run_dir, quick_report, quick_outputs, document, outputs)
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
    print("\n结论：API 深度报表完成。")
    print(f"总耗时：{elapsed}")
    print("最后一步：保存 API 报表并复制到总览索引目录。")
    print(f"输出目录：{run_dir}")
    print(f"API 报表：{out}")
    print(f"本地体系主报告：{document}")
    print(f"表格索引：{outputs['systems_report']}")


def run_api_analysis(config: dict, path: Path | None = None) -> None:
    print("\n正在生成本地分类数据并准备 API 报表，大存档可能需要几分钟...")
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
        run_dir = prepare_desktop_output(path, txt)
        progress(20, "创建桌面分类目录")
        document, outputs = analyze.build_system_export(
            path,
            txt,
            limit=30,
            full_pops=True,
            progress=lambda p, label: progress(18 + int(p * 0.55), label),
        )
        progress(73, "复制到桌面分类目录")
        categorize_run_outputs(run_dir, None, {}, outputs)
        progress(75, "本地体系数据已分类")
    except Exception as exc:
        progress.stop()
        print(f"\n本地体系数据生成失败：{exc}")
        return
    finally:
        if txt is not None:
            analyze.clear_database_block_cache(txt)
    progress.stop()
    print("正在调用 API 生成分类报表...")
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
        os.startfile(out)
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


def main() -> None:
    while True:
        clear()
        config = load_config()
        line(f"Victoria 3 存档读取器 v{APP_VERSION}")
        print(f"API：{saved_label(config)}")
        print()
        print("[1] 选择存档导出")
        print("[2] 直接导出最新存档")
        print("[3] API 深度报表")
        print("[0] 退出")
        choice = ask("\n选择：").strip()
        if not choice:
            sys.exit(0)
        if choice == "1":
            selected = choose_save_path()
            if selected:
                run_combined_export(selected)
                pause()
        elif choice == "2":
            run_combined_export()
            pause()
        elif choice == "3":
            api_menu()
        elif choice == "0":
            sys.exit(0)


if __name__ == "__main__":
    main()
