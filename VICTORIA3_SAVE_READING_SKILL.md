---
name: victoria3-save-reading
description: Read Victoria 3 save files and export structured country, economy, population, diplomacy, war, and report data for this local analyzer project.
---

# Victoria 3 Save Reading Skill

Use this project-local skill when the user asks to read, parse, export, compare, or report on Victoria 3 save data. This is not a global Codex skill installation; it is a single project document that explains the local analyzer's expected behavior.

## Project Location

- Formal/local tool folder: the repository root.
- Advanced/dev copy: optional local copy under the user's Desktop.
- User-facing output: `%USERPROFILE%\Desktop\Victoria3存档报告\<country>_<game-date>\`
- Exported files must be prefixed with the save's in-game country and in-game date, for example `SWI_1858-08-04_systems_wars.csv`.
- API config: `%USERPROFILE%\.vic3-save-analyzer\api_config.json`

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
- Diplomatic plays, war goals, formations, battles, casualties, war costs, occupation, and state devastation
- Machine-readable JSON index

Avoid defaulting to "what should I do next". Only give strategy advice when the user explicitly asks for it.

## Current Tool Behavior

The launcher menu should stay simple:

```text
[1] 一键导出：快速报告 + 体系化文档
[2] API 深度报表
[0] 退出
```

One-click export should:

1. Read the latest `.v3` save from the Victoria 3 save directory.
2. Generate a fast local report.
3. Generate a full systematic country document.
4. Export fixed CSV/JSON tables.
5. Copy outputs into categorized desktop folders.

API deep report should:

1. Use DeepSeek/OpenAI-compatible API settings from the launcher.
2. Send extracted structured data, not raw hidden reasoning.
3. Produce classified tables and field explanations first.
4. Avoid predictions, gameplay advice, or subjective analysis unless requested.

## Expected Output Categories

When launched from the UI, copy reports into:

```text
01_总览文档
02_快速报告
03_经济公司
04_人口社会
05_制度外交科技战争
06_机器数据
```

Important fixed outputs:

- `*_systems_document.md`
- `*_systems_report.md`
- `*_systems_major_countries.csv`
- `*_systems_states.csv`
- `*_systems_building_summary.csv`
- `*_systems_building_details.csv`
- `*_systems_companies.csv`
- `*_systems_population_summary.csv`
- `*_systems_population_by_type.csv`
- `*_systems_population_by_culture.csv`
- `*_systems_population_by_religion.csv`
- `*_systems_laws.csv`
- `*_systems_interest_groups.csv`
- `*_systems_technology.csv`
- `*_systems_relations.csv`
- `*_systems_pacts.csv`
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
3. Desktop category/API bundle in `launcher.py`

After changes, run at least:

```powershell
python -m py_compile analyze.py launcher.py
"0" | python launcher.py
```

For deeper verification, run:

```powershell
python analyze.py systems --limit 5 --no-pops
```
