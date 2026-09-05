# Community Sources

This project is designed around a "community first, local report layer second" approach.

Referenced projects:

| Project | Role | License |
|---|---|---|
| Garibaldi | Victoria 3 metrics pipeline ideas, native extractor, and bundled Rakaly melter workflow | MIT |
| vic3-reader | Python parser/metrics/orchestrator structure reference | MIT |
| rakaly/jomini | Paradox/Jomini save parsing approach | MIT |

The repository does not vendor full third-party clones by default. Use `scripts/install_community_tools.ps1` to fetch optional community tooling into the ignored `community/` folder.

v0.3 automatically detects these optional local tools when present:

- `community/Garibaldi/bin/rakaly_windows/vic3-extract.exe`
- `community/Garibaldi/bin/rakaly_windows/melter.exe`
- `tools/rakaly.exe`
- `rust/vic3_extract/target/release/vic3_extract.exe`
- `VIC3_RAKALY` and `VIC3_JOMINI_EXTRACTOR` environment variables

Local custom layer:

- Chinese desktop launcher
- categorized desktop report export
- persistent save catalog and cache fingerprints
- standard SQLite/JSONL data packages
- systematic country dossier
- GDP share and trend tables
- companies, population, politics, diplomacy, wars, and historical wars
- DeepSeek/OpenAI-compatible classified API report mode
