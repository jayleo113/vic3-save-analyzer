# Victoria 3 Save Analyzer / Vic3 存档读取器

Victoria 3 save parser and report exporter for Paradox grand strategy saves. It extracts country systems, GDP share, historical trends, buildings, companies, population structure, laws, interest groups, diplomacy, wars, and historical wars into Markdown, CSV, and JSON reports.

中文：这是一个维多利亚 3 存档读取器，会把 `.v3` 存档整理成体系化国家档案和分类报表。它不是玩法攻略工具，默认目标是把国家的经济、建筑、人口、制度、外交和战争数据完整导出来。

## Keywords

Victoria 3, Vic3, Victoria 3 save analyzer, Victoria 3 save parser, Vic3 save reader, Paradox save parser, Jomini save, Clausewitz save, grand strategy tools, GDP report, population report, diplomacy report, war history report, DeepSeek API.

## Features

- One-click desktop export for Windows.
- Reads the latest Victoria 3 `.v3` save automatically.
- Supports text saves, ZIP saves, and optional binary-save melting through Garibaldi/Rakaly.
- Exports systematic country dossiers in Markdown.
- Exports fixed CSV/JSON tables for scripts, spreadsheets, and AI report generation.
- Adds GDP share, GDP per capita, GDP history, prestige history, literacy history, and standard-of-living history.
- Exports companies and enterprise productivity trends.
- Exports population by job, culture, religion, loyalists, radicals, workforce, and dependents.
- Exports laws, interest groups, technology, relations, pacts, diplomatic plays, war goals, armies/navies, battles, casualties, wars, and historical wars.
- Shows progress percentage and estimated remaining time in the one-click desktop exporter.
- Optional DeepSeek/OpenAI-compatible API report mode for classified tables.

## Quick Start

Download or clone the repository, then run on Windows:

```powershell
python -m py_compile analyze.py launcher.py
python launcher.py
```

Or double-click:

```text
run-analyzer.bat
启动维多利亚3存档读取器.bat
```

Launcher menu:

```text
[1] 一键导出：快速报告 + 体系化文档
[2] API 深度报表
[0] 退出
```

The default save folder is:

```text
C:\Users\<username>\Documents\Paradox Interactive\Victoria 3\save games
```

Desktop exports are copied to:

```text
C:\Users\<username>\Desktop\Victoria3存档报告\<save_name_timestamp>\
```

## Output Folders

When launched from the UI, reports are categorized as:

```text
01_总览文档
02_快速报告
03_经济公司
04_人口社会
05_制度外交科技战争
06_机器数据
```

Important outputs:

| File | Meaning |
|---|---|
| `*_systems_document.md` | systematic country dossier |
| `*_systems_report.md` | table index |
| `*_systems_major_countries.csv` | country overview, GDP share, historical changes |
| `*_systems_states.csv` | owned states |
| `*_systems_building_summary.csv` | building summary by country and building type |
| `*_systems_building_details.csv` | building instance details |
| `*_systems_companies.csv` | company type, country, region, prosperity, productivity history |
| `*_systems_population_summary.csv` | population, workforce, dependents, loyalists, radicals |
| `*_systems_population_by_type.csv` | population by job |
| `*_systems_population_by_culture.csv` | population by culture |
| `*_systems_population_by_religion.csv` | population by religion |
| `*_systems_laws.csv` | active laws and institutions |
| `*_systems_interest_groups.csv` | interest group clout, approval, and political strength |
| `*_systems_technology.csv` | research and acquired technologies |
| `*_systems_relations.csv` | bilateral relations |
| `*_systems_pacts.csv` | diplomatic pacts and actions |
| `*_systems_wars.csv` | active and historical wars |
| `*_systems_war_participants.csv` | war support and exhaustion by participating country |
| `*_systems_diplomatic_plays.csv` | diplomatic play sides, escalation, region, linked war |
| `*_systems_war_costs.csv` | material, wage, and known total war cost |
| `*_systems_war_goals.csv` | war goals, holders, creators, targets, status |
| `*_systems_military_formations.csv` | armies/navies, unit types, mobilization options, supply |
| `*_systems_battles.csv` | battle location, dates, victory, manpower, battalions, casualties |
| `*_systems_battle_casualties.csv` | battle casualties by country and culture |
| `*_systems_summary.json` | machine-readable index |

## Command Line

```powershell
python analyze.py
python analyze.py report
python analyze.py report --full
python analyze.py systems
python analyze.py systems --limit 30
python analyze.py systems --no-pops
python analyze.py --json doctor
python analyze.py --json latest
python analyze.py --json community
python analyze.py melt "C:\path\to\save.v3"
```

## Optional Community Tools

This repository does not vendor full community clones. To fetch optional helper projects into the ignored `community/` folder:

```powershell
.\scripts\install_community_tools.ps1
```

Referenced projects:

- Garibaldi
- vic3-reader
- rakaly/jomini

See [docs/COMMUNITY_SOURCES.md](docs/COMMUNITY_SOURCES.md).

## API Mode

API mode supports DeepSeek and OpenAI-compatible chat endpoints.

Built-in presets:

- DeepSeek V4 Flash
- DeepSeek V4 Pro
- OpenAI
- Custom OpenAI-compatible endpoint

API mode is designed to generate classified tables first. It should not write gameplay advice, predictions, or subjective analysis unless explicitly requested.

See [docs/API_AND_PRIVACY.md](docs/API_AND_PRIVACY.md).

## Privacy

Do not commit real `.v3` save files, generated reports, or API keys. The repository `.gitignore` excludes saves, reports, local API configs, community clones, and backup files.

## Project-Local Skill

The file [VICTORIA3_SAVE_READING_SKILL.md](VICTORIA3_SAVE_READING_SKILL.md) describes how future Codex sessions should read and extend this analyzer.

## License

MIT
