# Contributing

Contributions are welcome, especially:

- new Victoria 3 save fields
- better localization labels
- stronger parser compatibility across game versions and mods
- report templates
- war, diplomatic play, front, and market-system extraction

Please keep exports stable when possible. If a CSV column changes, update:

1. `analyze.py`
2. `launcher.py`
3. `README.md`
4. `VICTORIA3_SAVE_READING_SKILL.md`

Before submitting changes, run:

```powershell
python -m py_compile analyze.py launcher.py
python analyze.py systems --limit 5 --no-pops
```
