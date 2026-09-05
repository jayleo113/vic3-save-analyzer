# -*- coding: utf-8 -*-
"""Build a static LLM-readable share bundle from a cached dataset."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import api_server


OUTPUT_DIR = Path(__file__).resolve().parent / "public_share"


CORE_TABLES = [
    "major_countries",
    "states",
    "markets",
    "market_members",
    "building_summary",
    "companies",
    "population_summary",
    "population_by_type",
    "population_by_culture",
    "population_by_religion",
    "laws",
    "interest_groups",
    "political_movements",
    "relations",
    "pacts",
    "treaties",
    "wars",
    "war_participants",
    "diplomatic_plays",
    "war_goals",
    "battles",
    "battle_casualties",
]


def main() -> None:
    manifest = api_server.dataset_from_text("latest")
    if not manifest:
        raise SystemExit("没有可分享的数据包，请先运行 api_server.py build")

    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True)

    source = manifest.get("source", {})
    package = {
        "ok": True,
        "dataset": manifest.get("dataset"),
        "source": source,
        "tables": {},
    }
    for name in CORE_TABLES:
        csv_path = api_server.output_path(manifest, name)
        rows = api_server.read_csv_rows(csv_path)
        package["tables"][name] = {
            "description": api_server.SYSTEM_DATASETS[name],
            "count": len(rows),
            "rows": rows,
        }
        (OUTPUT_DIR / f"{name}.csv").write_text(
            csv_path.read_text(encoding="utf-8-sig"),
            encoding="utf-8",
        )

    (OUTPUT_DIR / "latest_core.json").write_text(
        json.dumps(package, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    doc_path = api_server.output_path(manifest, "systems_document")
    (OUTPUT_DIR / "systems_document.md").write_text(
        doc_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    country = source.get("country", "") if isinstance(source, dict) else ""
    date = source.get("date", "") if isinstance(source, dict) else ""
    version = source.get("version", "") if isinstance(source, dict) else ""
    lines = [
        f"# Victoria 3 {country} {date} 数据入口",
        "",
        f"- 数据包：`{manifest.get('dataset')}`",
        f"- 国家：{country}",
        f"- 游戏日期：{date}",
        f"- 版本：{version}",
        "",
        "## 先读这个",
        "",
        "- `latest_core.json`：核心结构化数据，适合对话模型直接读取。",
        "- `systems_document.md`：体系化国家文档。",
        "",
        "## 可用表格",
    ]
    for name in CORE_TABLES:
        lines.append(f"- `{name}.csv`：{api_server.SYSTEM_DATASETS[name]}")
    lines.extend(
        [
            "",
            "## 给对话模型的指令",
            "",
            (
                "请读取这个 gist 入口中的 `latest_core.json` 和 `systems_document.md`，"
                f"基于数据分析 Victoria 3 {country} {date} 的国家情况。"
                "不要使用 1886 或旧上传文件。"
            ),
        ]
    )
    (OUTPUT_DIR / "README.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(OUTPUT_DIR)
    print(OUTPUT_DIR / "README.md")
    print(OUTPUT_DIR / "latest_core.json")


if __name__ == "__main__":
    main()
