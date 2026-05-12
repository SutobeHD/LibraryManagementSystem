---
description: Regenerate docs/MAP.md and docs/MAP_L2.md from current source (AST-based, deterministic)
allowed-tools: Bash, Read
---

Re-run the deterministic map generator:

```bash
python scripts/regen_maps.py
```

This rewrites:
- `docs/MAP.md` — Level 1 (file → 1-line purpose)
- `docs/MAP_L2.md` — Level 2 (L1 + public classes/functions/methods)

Sources scanned:
- Python AST: `app/**/*.py`, `tests/**/*.py`, `scripts/**/*.py`
- Rust regex: `src-tauri/src/**/*.rs` (`pub` items only)
- JS regex: `frontend/src/**/*.{js,jsx,mjs,cjs}` (exports only)

After regenerating:
1. Run `git diff docs/MAP.md docs/MAP_L2.md` and summarise what changed in 1–3 lines.
2. If only line numbers / formatting drifted, commit as `docs(maps): regen`.
3. If real new symbols appeared, mention them in the report so the user knows what was added.

For CI / pre-commit verification (no write): `python scripts/regen_maps.py --check` — exits 1 if regeneration would change anything.
