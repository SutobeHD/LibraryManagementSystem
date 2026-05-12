# Tooling — what's wired and how to use it

## Python tooling (`pyproject.toml`)

- **`ruff`** — lint + format (replaces flake8 + isort + most black usage). Rules: `E`, `F`, `W`, `I`, `B`, `UP`, `RUF`, `SIM`. Line length 100. Target py310.
- **`black`** — kept for editor integrations that don't speak ruff. Same defaults as ruff format.
- **`mypy`** — gradual / lenient now (`check_untyped_defs = false`). Tightened as the codebase fills in type hints.
- **`pytest`** — config in `[tool.pytest.ini_options]`. Markers: `slow`, `integration`. Default invocation: `pytest tests/ -v`.

CI enforces all four green on push + PR.

Run from repo root:
```bash
ruff check app/ tests/
ruff format app/ tests/
mypy app/
pytest tests/
```

### Excluded files (per pyproject.toml)

Dev/debug scripts under `app/` aren't lint-clean by design — `app/brute_force_*.py`, `app/inspect_*.py`, `app/debug_*.py`, `app/diag_*.py`, `app/check_*.py`, `app/verify_*.py`, `app/find_*.py`, `app/fix_*.py`, `app/calibrate_*.py`, `app/final_*.py`, `app/mass_verify*.py`, `app/analysis_inspector.py`. They're staged for relocation to `scripts/dev/` (see `HANDOVER.md` Phase 5.3).

## Frontend tooling

- **`frontend/.eslintrc.cjs`** — ESLint react-standard config.
- **`frontend/.prettierrc`** — Prettier defaults.
- **`frontend/jsconfig.json`** — VSCode hints; plain JS (no TypeScript).

Run from repo root:
```bash
npx prettier --write frontend/src
npx eslint frontend/src --fix
```

Or from `frontend/`: `npm run lint` (if wired in `package.json`).

## Rust tooling

```bash
cargo check  --manifest-path src-tauri/Cargo.toml
cargo fmt    --manifest-path src-tauri/Cargo.toml
cargo clippy --manifest-path src-tauri/Cargo.toml -- -D warnings
cargo test   --manifest-path src-tauri/Cargo.toml
```

## CI workflows (`.github/workflows/`)

- **`ci.yml`** — lint + test on push + PR. Jobs: `python-lint-test` (ruff + pytest), `rust-lint-test` (clippy + cargo test), `frontend-lint` (eslint).
- **`release.yml`** — release builds.

The `regen_maps.py --check` step is wired in CI to fail the build if `docs/MAP.md` / `docs/MAP_L2.md` drift from source.

## Auto-format hook

`.claude/hooks/format-on-edit.py` is wired via `PostToolUse` matcher (`Edit|Write`) in `.claude/settings.json`. After any `Edit` or `Write` tool call, it dispatches:

- `app/*.py` / `tests/*.py` → `ruff format` + `ruff check --fix`
- `frontend/src/**/*.{js,jsx}` → `npx prettier --write` + `npx eslint --fix`
- `src-tauri/src/**/*.rs` → `cargo fmt --manifest-path src-tauri/Cargo.toml`

Non-blocking — failures are logged to stderr but don't revert the edit. Agent decides whether to fix manually.

## Pre-commit hook (`.pre-commit-config.yaml`)

One-time install per machine:
```bash
pip install pre-commit
pre-commit install
```

Then every `git commit` runs:
- `trailing-whitespace`, `end-of-file-fixer`, `check-yaml/json/toml`, `check-added-large-files (>500kb)`, `check-merge-conflict`, `detect-private-key`, `mixed-line-ending`
- `ruff` + `ruff-format` on `app/`, `tests/`
- `mypy` on `app/`
- `cargo fmt --check` on `src-tauri/`
- `prettier` + `eslint` on `frontend/src/`
- `forbid-env-files` / `forbid-master-db` — fail if staged

**Bypass is denied by `.claude/settings.json`** — the agent cannot use `--no-verify`. Hook failure means: fix and commit again.

## Map regeneration (`scripts/regen_maps.py`)

```bash
python scripts/regen_maps.py            # write docs/MAP.md + docs/MAP_L2.md
python scripts/regen_maps.py --check    # CI: exit 1 if drift
python scripts/regen_maps.py --stdout   # preview without writing
```

Sources: Python AST + Rust regex (`pub` items) + JS regex (exports). Deterministic. Safe to run without project runtime deps installed.

## Security audit

```bash
npm run audit             # npm audit --audit-level=high + signatures
npm run lint:lockfile     # lockfile-lint with validate-https / allowed-hosts npm
./scripts/security-audit.ps1    # Windows full audit
./scripts/security-audit.sh     # Unix full audit
```

See `docs/SECURITY.md` for the threat model and accepted risks.
