# Changelog

## Unreleased

- v0.4 target: historical comparison groups and complete world-chain reports across multiple saves.
- Planned focus: territory changes, country lifecycle, subject relations, markets, treaties, wars, battles, casualties, political movements, and long-run economic/social changes.

## 0.3.0

- Added a v0.3 acceptance runner that checks real-save export, cache reuse, range reuse, local API reads, desktop Markdown export, and historical comparison.
- Added multi-save campaign timeline output for explicitly selected snapshots.
- Added an optional Rust top-level block scanner project under `rust/vic3_parser_rs`, plus Python discovery through accelerator diagnostics.
- Added a persistent save catalog under `data_cache/save_catalog.json` so save picking reuses country/date/version previews when the file has not changed.
- Upgraded dataset cache validation from size/time only to size/time plus a fast content fingerprint, reducing wrong-cache risk for manual saves and repeated filenames.
- Added a content reuse index under `data_cache/content_index.json` so the same save content can reuse an existing dataset even if the file path or manual filename differs.
- Added optional high-speed extractor discovery for Garibaldi native `vic3-extract`, Garibaldi/Rakaly `melter`, Rakaly CLI, and future Jomini-based extractors.
- Reworked binary/unknown save reading to write melted text under the project `data_cache/` folder instead of the system temporary directory.
- Added standard data packages with SQLite; the JSONL-compatible endpoint reads SQLite on demand instead of creating a full mirror by default.
- Added `/api/jsonl/table/<name>` and expanded `/api/health`/`api_server.py status` with accelerator diagnostics.
- Added terminal accelerator diagnostics so users can see whether the current machine is using a native extractor or Python fallback.
- Bumped API dataset schema and SQLite/JSONL schema versions so old caches rebuild cleanly.

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
