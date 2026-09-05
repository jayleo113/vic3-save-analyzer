# Victoria 3 Save Analyzer / Vic3 存档读取器

Current version: v0.3

Next target: v0.4 will focus on historical comparison groups and a complete world-chain timeline across multiple saves.

维护规则见 [AGENTS.md](AGENTS.md)；第五至第九项的实现、实测和限制见 [v0.3 验收记录](docs/V0.3_ACCEPTANCE.md)。下一阶段目标见 [v0.4 路线：历史对照与完整世界链](docs/V0.4_ROADMAP.md)。

Victoria 3 save parser and report exporter for Paradox grand strategy saves. It extracts country systems, GDP share, historical trends, buildings, companies, population structure, laws, interest groups, diplomacy, wars, and historical wars into Markdown, CSV, and JSON reports.

中文：这是一个维多利亚 3 存档读取器，会把 `.v3` 存档整理成体系化国家档案和分类报表。它不是玩法攻略工具，默认目标是把国家的经济、建筑、人口、制度、外交和战争数据完整导出来。

## Keywords

Victoria 3, Vic3, Victoria 3 save analyzer, Victoria 3 save parser, Vic3 save reader, Paradox save parser, Jomini save, Clausewitz save, grand strategy tools, GDP report, population report, diplomacy report, war history report, DeepSeek API.

## Features

- One-click Windows export into the desktop Markdown report library.
- Reads the latest Victoria 3 `.v3` save automatically.
- Supports text saves, ZIP saves, and optional binary-save melting through Garibaldi/Rakaly.
- Exports systematic country dossiers in Markdown.
- Exports fixed CSV/JSON tables for scripts, spreadsheets, and AI report generation.
- Adds GDP share, GDP per capita, GDP history, prestige history, literacy history, and standard-of-living history.
- Exports companies and enterprise productivity trends.
- Exports population by job, culture, religion, loyalists, radicals, workforce, and dependents.
- Exports markets, market members, state trade goods, laws, political movements, interest groups, technology, relations, pacts, formal treaties, treaty articles, diplomatic plays, war goals, armies/navies, battles, casualties, wars, historical wars, and state ownership-change clues.
- Builds explicit two-save comparisons and multi-save timelines from wars, diplomatic plays, war goals, battles, casualties, subjects, markets, treaties, laws, movements, and state owner-change fields.
- Maintains a desktop Markdown library with `00_资料库索引.md` for chat-model handoff when local APIs are unavailable.
- Desktop Markdown export is a data-first full-country document; interpretation is intentionally left to API or other analysis frameworks.
- Reuses unchanged Markdown reports through a disk-backed cache, so repeated exports of the same save return immediately.
- Shows a compact single-line status with real scan counts, without simulated completion times.
- Provides a local HTTP data API for save listing, disk-backed data builds, per-table JSON reads, SQLite queries, and JSONL table reads.
- Uses a persistent save catalog and fast content fingerprints so unchanged saves can be identified without deep rescans.
- Reuses identical save content through `data_cache/content_index.json`, so copied or renamed saves can still find an existing dataset view.
- Stores reusable world modules in `data_cache/snapshots.sqlite`; country scopes share the same extraction.
- Writes reusable data packages under `data_cache/`; the JSONL-compatible table endpoint reads SQLite on demand.
- Compares explicitly selected historical snapshots, including territory, subjects, laws, markets, treaties, movements and recorded wars.
- Detects optional acceleration backends: Garibaldi native extractor, Garibaldi/Rakaly melter, Rakaly CLI, and the optional Rust top-level block scanner.
- Optional DeepSeek/OpenAI-compatible API report mode for classified tables.

## Quick Start

Download or clone the repository, then run on Windows:

```powershell
python -m py_compile analyze.py launcher.py api_server.py
python launcher.py
```

Or double-click:

```text
run-analyzer.bat
启动维多利亚3存档读取器.bat
```

Launcher menu:

```text
1. 导出最新 MD
2. 选择存档批量导出
3. 资料库与设置
0. 退出
```

The default save folder is:

```text
C:\Users\<username>\Documents\Paradox Interactive\Victoria 3\save games
```

Default Markdown reports go directly into the desktop `Victoria3存档MD报告` folder. Intermediate files stay in the project. Optional categorized exports are written to:

```text
F:\vic3-save-analyzer\exports\<country>_<game-date>\
```

The MD-only desktop option writes a single rich Markdown report to:

```text
C:\Users\<username>\Desktop\Victoria3存档MD报告\<中文国家>_<game-date>_国家报告.md
```

The library index groups reports by Chinese country name and sorts each country by game date. Older duplicate reports are moved to `_旧版重复报告` so the first folder level stays easy to scan.

Inside that option:

```text
[1] 直接导出最新存档
[2] 扫描列表并多选导出
[3] 导出全部存档
[0] 返回
```

Multi-select accepts input such as `1,3,5` or `2-6`.

The desktop Markdown library keeps only `.md` files and the index file:

```text
C:\Users\<username>\Desktop\Victoria3存档MD报告\00_资料库索引.md
```

If the same save file has already been exported and its size/modified time has not changed, the launcher reuses the existing report instead of scanning the full save again.

## v0.3 Data Pipeline

```text
.v3 save
  -> persistent save catalog
  -> text/zip reader or optional native extractor
  -> reusable world modules
  -> standard data package
  -> Markdown / SQLite / API
```

The save picker uses `data_cache/save_catalog.json` and refreshes an entry only when the file size or modified timestamp changes. API datasets also store a fast content fingerprint, so manual saves with confusing names do not silently reuse the wrong cache.

Exact dataset views are content-addressed through `data_cache/content_index.json`: if a save is copied or renamed but the quick content fingerprint is unchanged, `api_server.py build` can reuse the existing matching dataset instead of scanning again.

Diagnostic command:

```powershell
python api_server.py status
```

See [docs/V0.3_TECH_STACK.md](docs/V0.3_TECH_STACK.md). Rust acceleration design is documented in [docs/RUST_ACCELERATION.md](docs/RUST_ACCELERATION.md).

## Current Modularization

The analyzer is split into maintainable helper modules:

```text
vic3_analyzer/md_library.py      Markdown library, index, cache, report self-checks
vic3_analyzer/save_discovery.py  local Documents and Steam Cloud save discovery
vic3_analyzer/progress.py        compact terminal progress display
vic3_analyzer/parser_core.py     low-level Jomini brace/database parsing helpers
vic3_analyzer/country_names.py   country tag to Chinese display-name mapping
vic3_analyzer/formatting.py      filename, number, Markdown table, CSV/JSON helpers
vic3_analyzer/data_store.py      SQLite mirror for generated API datasets
vic3_analyzer/fingerprint.py     fast save fingerprints for cache validation
vic3_analyzer/save_catalog.py    persistent save preview catalog
vic3_analyzer/external_tools.py  optional Garibaldi/Rakaly/Jomini/Rust backend discovery
vic3_analyzer/save_reader.py     text/zip/binary save reading and Garibaldi/Rakaly melt bridge
vic3_analyzer/metrics.py         numeric parsing, trend extraction, date sort helpers
vic3_analyzer/snapshot_store.py  reusable module snapshots and content-addressed objects
vic3_analyzer/world_data.py      one-pass world extraction and selected-country views
vic3_analyzer/history.py         two-save comparisons and multi-save timelines
vic3_analyzer/rust_backend.py    optional Rust scanner discovery and wrapper
vic3_analyzer/buildings.py       building scan, building sector classification, construction queue parsing
vic3_analyzer/states.py          state ownership, infrastructure, devastation, state trade-goods parsing
vic3_analyzer/pops.py            population scan, workforce/dependent, culture/religion/job aggregation
vic3_analyzer/diplomacy.py       relations, pacts, subject states, treaty and treaty-article parsing
```

Every exported file is also prefixed with the save's in-game country name and in-game date, for example `瑞士_1858-08-04_systems_wars.csv`. Repeated exports of the same in-game date keep that label and only add a simple repeat suffix to the export folder when needed.

## Output Folders

When launched from the UI, reports are categorized as:

```text
01_总览索引
02_国家总表
03_经济市场公司
04_人口社会政治
05_制度科技
06_外交条约战争
07_快速报告
08_机器数据
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
| `*_systems_markets.csv` | market owner, members, GDP, population, state count, trade capacity |
| `*_systems_market_members.csv` | countries inside each market |
| `*_systems_market_states.csv` | state-level market infrastructure and trade capacity |
| `*_systems_market_trade_goods.csv` | state-level traded goods and trade value |
| `*_systems_population_summary.csv` | population, workforce, dependents, loyalists, radicals |
| `*_systems_population_by_type.csv` | population by job |
| `*_systems_population_by_culture.csv` | population by culture |
| `*_systems_population_by_religion.csv` | population by religion |
| `*_systems_laws.csv` | active laws and institutions |
| `*_systems_interest_groups.csv` | interest group clout, approval, and political strength |
| `*_systems_political_movements.csv` | political movement identity, ideology, radicalism, participating pop count |
| `*_systems_technology.csv` | research and acquired technologies |
| `*_systems_relations.csv` | bilateral relations |
| `*_systems_pacts.csv` | diplomatic pacts and actions |
| `*_systems_treaties.csv` | formal treaties, countries, start date, binding period |
| `*_systems_treaty_articles.csv` | treaty article details such as defense, trade, goods, law, investment |
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
python api_server.py build --save latest
python api_server.py saves
python api_server.py list
python api_server.py content
python api_server.py status
python api_server.py serve
python public_api.py
```

## Local Data API

Run:

```powershell
python api_server.py build --save latest
python api_server.py serve
```

Default address:

```text
http://127.0.0.1:8765
```

Persistent API data packages are stored under:

```text
F:\vic3-save-analyzer\data_cache\
```

Each built dataset keeps the original Markdown/CSV files and also writes:

```text
F:\vic3-save-analyzer\data_cache\<dataset>\dataset.sqlite
F:\vic3-save-analyzer\data_cache\<dataset>\tables\*.jsonl
```

The SQLite/JSONL mirrors are versioned separately from the save parser. When mirror rules change, the tool rebuilds them from existing CSV files instead of reparsing the full `.v3` save.

Useful endpoints:

| Endpoint | Meaning |
|---|---|
| `/api/health` | API status |
| `/api/saves` | list available saves with country, game date, version, size, and path |
| `/api/datasets` | list already-built data packages |
| `/api/tables` | list available data tables |
| `/api/build?mode=systems&save=latest&limit=30&full_pops=1` | build or refresh a data package |
| `/api/table/major_countries?dataset=latest` | read one table as JSON |
| `/api/sql/tables?dataset=latest` | list tables available in the SQLite mirror |
| `/api/sql/table/major_countries?dataset=latest&limit=100` | read one table from SQLite |
| `/api/jsonl/table/major_countries?dataset=latest&limit=100` | read one JSONL-backed table |
| `/api/sql/query?dataset=latest&q=select * from major_countries limit 5` | run a read-only SQLite query |
| `/api/table/markets?dataset=latest` | read market data as JSON |
| `/api/table/population_by_culture?dataset=latest` | read culture population data as JSON |
| `/api/document/systems_document?dataset=latest` | read the generated Markdown document |

The `save` parameter accepts `latest`, a save index from `/api/saves`, or a full local `.v3` path. Build once, then use `dataset=latest` or a concrete dataset id to read tables quickly without reparsing the save. CSV endpoints remain simple and transparent; SQLite endpoints are better for repeated API reads and future filtering.

## Public Conversation API

For a chat model that cannot access local tools or `127.0.0.1`, start a temporary HTTPS tunnel:

```powershell
python public_api.py
```

The command prints one token-protected URL like:

```text
https://xxxx.trycloudflare.com/api/package?dataset=latest&token=...
```

Give that single URL to another chat model. It returns the selected dataset, fixed CSV tables as JSON, and the systematic Markdown documents. Keep the terminal window open while testing; closing it stops the public API.

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

## AI Report API Mode

API mode supports DeepSeek and OpenAI-compatible chat endpoints.

Built-in presets:

- DeepSeek V4 Flash
- DeepSeek V4 Pro
- OpenAI
- Custom OpenAI-compatible endpoint

API mode is designed to generate classified tables first. It should not write gameplay advice, predictions, or subjective analysis unless explicitly requested.

See [docs/API_AND_PRIVACY.md](docs/API_AND_PRIVACY.md).

## Privacy

Do not commit real `.v3` save files, generated reports, API data caches, or API keys. The repository `.gitignore` excludes saves, reports, `exports/`, `data_cache/`, local API configs, community clones, and backup files.

## Project-Local Skill

The file [VICTORIA3_SAVE_READING_SKILL.md](VICTORIA3_SAVE_READING_SKILL.md) describes how future Codex sessions should read and extend this analyzer.

## License

MIT
