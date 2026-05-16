# Tooling — what's wired

## Python (`pyproject.toml`)

- **`ruff`** — lint + format. Rules: `E`, `F`, `W`, `I`, `B`, `UP`, `RUF`, `SIM`. Line length 100, target py310.
- **`black`** — editor integrations that don't speak ruff.
- **`mypy`** — gradual, `check_untyped_defs=false`. Tightened as type-hint coverage grows.
- **`pytest`** — markers: `slow`, `integration`. Default: `pytest tests/ -v`.

CI enforces all four green on push + PR.

```bash
ruff check app/ tests/
ruff format app/ tests/
mypy app/
pytest tests/
```

### Excluded files (`pyproject.toml`)

Dev/debug scripts under `app/` aren't lint-clean by design: `brute_force_*`, `inspect_*`, `debug_*`, `diag_*`, `check_*`, `verify_*`, `find_*`, `fix_*`, `calibrate_*`, `final_*`, `mass_verify*`, `analysis_inspector.py`. Staged for relocation to `scripts/dev/` (`HANDOVER.md` Phase 5.3).

## Frontend

- ESLint: `frontend/.eslintrc.cjs` (react-standard).
- Prettier: `frontend/.prettierrc`.
- `frontend/jsconfig.json` for VSCode (plain JS, no TS).

```bash
npx prettier --write frontend/src
npx eslint frontend/src --fix
```

Or from `frontend/`: `npm run lint`.

## Rust

```bash
cargo check  --manifest-path src-tauri/Cargo.toml
cargo fmt    --manifest-path src-tauri/Cargo.toml
cargo clippy --manifest-path src-tauri/Cargo.toml -- -D warnings
cargo test   --manifest-path src-tauri/Cargo.toml
```

## CI (`.github/workflows/`)

- **`ci.yml`** — lint+test on push+PR. Jobs: `python-lint-test` (ruff+pytest), `rust-lint-test` (clippy+test), `frontend-lint` (eslint).
- **`release.yml`** — release builds.
- `regen_maps.py --check` fails CI on `docs/MAP.md`/`MAP_L2.md` drift.

## Auto-format hook (`PostToolUse` on `Edit|Write`)

`.claude/hooks/format-on-edit.py` dispatches:
- `app/*.py` / `tests/*.py` → `ruff format` + `ruff check --fix`
- `frontend/src/**/*.{js,jsx}` → `npx prettier --write` + `npx eslint --fix`
- `src-tauri/src/**/*.rs` → `cargo fmt`

Non-blocking — failures logged to stderr, edit not reverted. Agent decides to fix.

## Pre-commit hook (`.pre-commit-config.yaml`)

One-time install per machine:
```bash
pip install pre-commit
pre-commit install
```

Every `git commit` runs:
- `trailing-whitespace`, `end-of-file-fixer`, `check-yaml/json/toml`, `check-added-large-files (>500kb)`, `check-merge-conflict`, `detect-private-key`, `mixed-line-ending`
- `ruff` + `ruff-format` on `app/`, `tests/`
- `mypy` on `app/`
- `cargo fmt --check` on `src-tauri/`
- `prettier` + `eslint` on `frontend/src/`
- `forbid-env-files` / `forbid-master-db` — fail if staged

**`--no-verify` denied by `.claude/settings.json`.** Hook failure → fix + recommit.

## Map regen (`scripts/regen_maps.py`)

```bash
python scripts/regen_maps.py            # write docs/MAP.md + MAP_L2.md
python scripts/regen_maps.py --check    # CI: exit 1 on drift
python scripts/regen_maps.py --stdout   # preview
```

Sources: Python AST + Rust regex (`pub`) + JS regex (exports). Deterministic. No project runtime deps required.

## Security audit

```bash
npm run audit             # npm audit --audit-level=high + signatures
npm run lint:lockfile     # lockfile-lint
./scripts/security-audit.ps1    # Windows full audit
./scripts/security-audit.sh     # Unix full audit
```

Threat model + accepted risks: `docs/SECURITY.md`.
