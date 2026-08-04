# Tooling — what's wired

## Python (`pyproject.toml`)

- **`ruff`** — lint + format. Rules: `E`, `F`, `W`, `I`, `B`, `UP`, `RUF`, `SIM`. Line length 100, target py310.
- **`black`** — editor integrations that don't speak ruff.
- **`mypy`** — gradual, `check_untyped_defs=false`. Tightened as type-hint coverage grows.
- **`pytest`** — markers: `slow`, `integration`. Default: `pytest tests/ -v`.

CI enforces all four green on push + PR — **blocking**, baseline zero. `scripts/`
is in scope too. Never re-add `|| true` to `ci.yml`; suppress at the site with a
stated reason instead. Baselines + what the first zeroing pass found:
`docs/QUALITY_GATES.md`.

```bash
ruff check .          # one path — see the warning below
ruff format .
mypy app/
pytest tests/
```

**Give ruff exactly one path.** Passing several silently drops some of them:
`ruff format --check app tests` reports 108 files, `tests app` reports 55 — same
tree, one argument order apart. The old `ruff check app/ tests/ scripts/` looked
at 65 of 118 files and exited 0. `.` plus `extend-exclude` in `pyproject.toml` is
the only form that covers everything, including `backend_entry.py` and
`.claude/hooks/`, which no invocation had ever reached.

`ruff` and `mypy` are version-pinned identically in `ci.yml` and
`.pre-commit-config.yaml` (`ruff==0.15.8`, `mypy==1.19.1`). Bump both in one
commit, after re-clearing the gate.

**Verify with `--no-cache`.** Ruff's cache serves stale results and silently
shrinks the file count while doing so. A cached run reported "All checks passed"
on a tree with an unsorted import block during the gate sweep, and a cached
`ruff format` declined to rewrite a drifted file. CI starts cold; a cached local
green proves nothing.

**Never run `ruff check --select X --fix`.** Under a narrowed `--select`, every
`# noqa` for a rule outside the selection reads as unused and `RUF100` strips it.
This deleted 50 valid directives in one command during the gate sweep.

### Excluded files (`pyproject.toml`)

Relocation to `scripts/dev/` (`HANDOVER.md` Phase 5.3) is done — only `app/analysis_inspector.py` remains excluded. `pyproject.toml` still carries the old `brute_force_*`/`inspect_*`/… exclude patterns (dead, harmless). New dev/debug one-offs go straight to `scripts/dev/`, never `app/`.

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

- **`ci.yml`** — lint+test on push+PR. Jobs: `python-lint-test` (ruff+ruff-format+mypy+pytest+map-drift), `rust-lint-test` (rustfmt+clippy+test), `frontend-lint` (eslint+prettier+build). Every step is blocking except clippy — see `docs/QUALITY_GATES.md`.
- **`release.yml`** — release builds.
- `regen_maps.py --check` runs in `python-lint-test` — MAP.md/MAP_L2.md drift fails CI. After structural changes, regen via `python scripts/regen_maps.py` (or `/regen-maps`) and commit the maps with the code.

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
- `ruff` + `ruff-format` on every staged Python file (no path allowlist — `extend-exclude` in `pyproject.toml` decides scope)
- `mypy` on `app/`
- `cargo fmt --check` on `src-tauri/`
- `prettier` + `eslint` on `frontend/src/`
- `validate-research-docs` + `routine-divider-check` — research-pipeline doc hygiene
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
