---
name: victoria3-save-reading
description: Read Victoria 3 save files and export structured country, economy, population, diplomacy, war, and report data for this local analyzer project.
---

# Victoria 3 Save Reading Skill

Use this project-local skill when the user asks to read, parse, export, compare, or report on Victoria 3 save data. This is not a global Codex skill installation; it is a single project document that explains the local analyzer's expected behavior.

## Project Location

- Formal/local tool folder: the repository root.
- User-facing output: `F:\vic3-save-analyzer\exports\<country>_<game-date>\`
- Desktop MD library: `%USERPROFILE%\Desktop\Victoria3存档MD报告\`
- Local API data cache: `F:\vic3-save-analyzer\data_cache\`
- MD library cache manifest: `F:\vic3-save-analyzer\data_cache\md_library\md_library_manifest.json`
- Exported files must be prefixed with the save's in-game country name and in-game date, for example `瑞士_1858-08-04_systems_wars.csv`.
- System exports should include market tables, political movements, formal treaties, and treaty articles alongside the existing economy, population, diplomacy, and war tables.
- API config: `F:\vic3-save-analyzer\config\api_config.json`
- Avoid writing bulky generated reports, cache files, or temporary save expansions to the C drive.

## Main User Intent

The user wants systematic report export, not gameplay advice. Treat the save as a historical-social dataset. Prefer structured extraction first, then readable documents and tables.

Default report framing:

- Country overview
- GDP, GDP share, GDP per capita, and historical trend changes
- Building and economic system
- Companies and enterprise performance
- Population, workforce, dependents, loyalists, radicals
- Job, culture, and religion structure
- Laws and institutions
- Interest groups and class politics
- Technology and modernization
- Diplomacy, pacts, wars, and historical wars
- Diplomatic plays, war goals, formations, battles, casualties, war costs, occupation, state devastation, and state ownership-change clues
- War, unrest, and territorial-change timelines built from readable wars, diplomatic plays, war goals, battle records, casualties, `previous_country`, and `last_owner_change`
- Machine-readable JSON index

Avoid defaulting to "what should I do next". Only give strategy advice when the user explicitly asks for it.

## Current Tool Behavior

The launcher menu should stay simple:

```text
[1] MD 资料库
[2] 完整导出
[3] AI / API
[0] 退出
```

MD-only desktop export should generate a data-first full-country report, but leave only one `.md` file directly under `%USERPROFILE%\Desktop\Victoria3存档MD报告\`, named like `<country>_<game-date>_体系化国家报告.md`.
Do not turn the MD-only report into a gameplay guide or long interpretive essay. It should expose the data cleanly; deeper interpretation can happen later through API or another framework.
The MD-only menu should offer direct latest export, multi-select export, and export-all. Multi-select input supports comma-separated indexes and ranges such as `1,3,5` and `2-6`.
The MD library should maintain `00_资料库索引.md`, clean generated CSV/JSON files from the desktop MD folder, and reuse cached reports when the save path, size, and modified time have not changed.

Current split modules:

- `vic3_analyzer/md_library.py`: desktop MD library, index, cache, self-checks
- `vic3_analyzer/save_discovery.py`: Documents/OneDrive/Steam Cloud save discovery
- `vic3_analyzer/progress.py`: terminal progress rendering
- `vic3_analyzer/parser_core.py`: low-level Jomini brace/database parsing helpers
- `vic3_analyzer/country_names.py`: country tag to Chinese display-name mapping, with localization-file support
- `vic3_analyzer/formatting.py`: filename, number, Markdown table, CSV/JSON helpers
- `vic3_analyzer/data_store.py`: SQLite mirror for generated API datasets
- `vic3_analyzer/save_reader.py`: text/zip/binary save reading and Garibaldi/Rakaly melt bridge
- `vic3_analyzer/metrics.py`: numeric parsing, trend extraction, date sort helpers
- `vic3_analyzer/buildings.py`: building scan, building sector classification, construction queue parsing
- `vic3_analyzer/states.py`: state ownership, infrastructure, devastation, state trade-goods parsing
- `vic3_analyzer/pops.py`: population scan, workforce/dependent, culture/religion/job aggregation
- `vic3_analyzer/diplomacy.py`: relations, pacts, subject states, treaty and treaty-article parsing

One-click export should:

1. Let the user choose a scanned save by in-game country/date, or directly export the latest `.v3` save.
2. Generate a fast local report.
3. Generate a full systematic country document.
4. Export fixed CSV/JSON tables.
5. Copy outputs into categorized F-drive export folders.

API/data-cache exports should additionally create `dataset.sqlite` inside `F:\vic3-save-analyzer\data_cache\<dataset>\`. Keep Markdown and CSV as transparent source artifacts, but use SQLite for repeated API reads and future filtering/query features.

Terminal progress should stay compact and human-readable:

- Keep one dynamic status line during export.
- Show percentage, current step number, total steps, and concrete scanned/remaining item counts when available.
- Do not show estimated remaining time unless there is a reliable phase-specific model.
- Do not use decorative progress bars that risk wrapping in Windows Terminal.

API deep report should:

1. Use DeepSeek/OpenAI-compatible API settings from the launcher.
2. Send extracted structured data, not raw hidden reasoning.
3. Produce classified tables and field explanations first.
4. Avoid predictions, gameplay advice, or subjective analysis unless requested.

Local data API should:

1. Run locally by default at `127.0.0.1:8765`.
2. Expose save listing through `/api/saves`.
3. Expose disk-backed data builds through `/api/build` and the compatibility alias `/api/export`.
4. Expose every fixed systems table through `/api/table/<table_name>`.
5. Reuse generated outputs from `data_cache/` instead of reparsing the save for every table request.

Public conversation API should:

1. Use `public_api.py` to start a temporary Cloudflare tunnel when a model without local tools needs access.
2. Require a token for save data endpoints.
3. Prefer a single package URL: `/api/package?dataset=latest&token=<token>`.
4. Store the tunnel binary under `F:\vic3-save-analyzer\tools\`, not on the C drive.

## Expected Output Categories

When launched from the UI, copy reports into:

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

Important fixed outputs:

- `*_systems_document.md`
- `*_systems_report.md`
- `*_systems_major_countries.csv`
- `*_systems_states.csv`
- `*_systems_building_summary.csv`
- `*_systems_building_details.csv`
- `*_systems_companies.csv`
- `*_systems_markets.csv`
- `*_systems_market_members.csv`
- `*_systems_market_states.csv`
- `*_systems_market_trade_goods.csv`
- `*_systems_population_summary.csv`
- `*_systems_population_by_type.csv`
- `*_systems_population_by_culture.csv`
- `*_systems_population_by_religion.csv`
- `*_systems_laws.csv`
- `*_systems_interest_groups.csv`
- `*_systems_political_movements.csv`
- `*_systems_technology.csv`
- `*_systems_relations.csv`
- `*_systems_pacts.csv`
- `*_systems_treaties.csv`
- `*_systems_treaty_articles.csv`
- `*_systems_wars.csv`
- `*_systems_war_participants.csv`
- `*_systems_diplomatic_plays.csv`
- `*_systems_war_costs.csv`
- `*_systems_war_goals.csv`
- `*_systems_military_formations.csv`
- `*_systems_battles.csv`
- `*_systems_battle_casualties.csv`
- `*_systems_summary.json`

## Parser Principles

- Prefer structured parsing over fragile string slicing.
- Use existing helpers in `analyze.py`: `database_block`, `iter_top_blocks`, `subblock`, `top_value`, `list_value`, `trend_stats`.
- Preserve fixed column names whenever extending CSVs.
- Support text saves, ZIP saves, and binary/unknown saves through Garibaldi/Rakaly melter.
- Keep community integration as the base where practical: Garibaldi, vic3-reader, and rakaly/jomini.
- When fields are not found, output blanks or "未读到"; do not invent data.

## Important Data Areas

Country:

- Country id, tag, rank, prestige rank
- GDP and GDP trend
- World GDP share and selected-major-country GDP share
- Population, GDP per capita
- Literacy and SOL trend
- Government, market, capital, legitimacy, infamy

Economy and companies:

- Building detail and building summary
- Building sector classification
- Company type, country, state region, prosperity, CEO
- Company productivity trend start/latest/change/change percentage

Population:

- Population detail total
- Workforce and dependents
- Loyalists and radicals
- Unanchored/no-workplace population
- Job, culture, religion shares

Politics:

- Active laws
- Interest group clout, approval, political strength, government status

Diplomacy and war:

- Relations, pacts, obligations, truce, last action
- War total table with active and historical wars
- War participant table with war support and exhaustion deltas
- Diplomatic play table with initiator/target sides and escalation
- War goal table with holder, creator, target country, target state/region, and status
- Military formation table with army/navy type, unit types, mobilization options, organization, supply, and locations
- Battle table with date, location, victory status, battalions, manpower, casualties, captured provinces, and occupation/lost province fields
- Battle casualty table by country and culture
- State devastation should be kept in the state table

## Editing Guidance

Keep the project usable by double-clicking the `.bat` launcher. If adding fields, update all three places:

1. CSV output in `analyze.py`
2. Markdown document generation in `analyze.py`
3. F-drive export category/API bundle in `launcher.py`

After changes, run at least:

```powershell
python -m py_compile analyze.py launcher.py
"0" | python launcher.py
```

For deeper verification, run:

```powershell
python analyze.py systems --limit 5 --no-pops
```
