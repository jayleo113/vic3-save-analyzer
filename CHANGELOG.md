# Changelog

## 0.2.0

- Refactored the analyzer into maintainable modules for save discovery, save reading, parser core, formatting, metrics, states, buildings, pops, diplomacy, Markdown library management, terminal UI, and SQLite data storage.
- Added Chinese-first country display names across save lists, exported reports, CSV/SQLite tables, and API-facing datasets, while preserving tags such as `中国（CHI）` for filtering and verification.
- Added a disk-backed Markdown library cache for repeated single-MD exports of unchanged saves.
- Added SQLite dataset mirrors with indexed common fields such as `country_id`, `tag`, `state_id`, `building`, `market_id`, `war_id`, and `diplomatic_play`.
- Added local API endpoints for SQLite table reads and read-only SQL queries.
- Improved latest-save handling by using real file modified time while preserving the in-game country/date in output names.
- Improved terminal UX with clearer menus, compact single-line progress, cleaner summaries, batch export output, and more useful API instructions.
- Expanded reports with market, political movement, treaty, subject/puppet, war, battle, casualty, and territorial-change data.
- Cleaned old generated output and ignored local caches, save files, logs, community tools, and API secrets.

## 0.1.0

- Added desktop one-click export.
- Added categorized report folders on the Windows desktop.
- Added systematic country dossier output.
- Added GDP share, GDP history, SOL history, literacy history, and prestige history fields.
- Added companies and enterprise productivity exports.
- Added population, culture, religion, law, interest group, technology, diplomacy, pact, war, and historical war exports.
- Added DeepSeek/OpenAI-compatible API classified report mode.
- Added project-local Victoria 3 save reading skill document.
