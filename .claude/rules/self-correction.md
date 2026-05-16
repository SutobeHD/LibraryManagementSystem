# Self-correction loop (post-edit workflow)

After every code edit, before reporting done — in this order:

## 1. Linter / formatter

PostToolUse hook auto-runs formatter after `Edit`/`Write` (see `tooling.md`). Verify it didn't fail. If unavailable / explicit check:

- **Python** (`app/`, `tests/`): `ruff check <file>` + `ruff format <file>`. Types: `mypy <file>`. Fallback: `python -c "import ast; ast.parse(open('<file>').read())"`.
- **Rust** (`src-tauri/src/`): `cargo check` + `cargo fmt` + `cargo clippy -- -D warnings` (all `--manifest-path src-tauri/Cargo.toml`).
- **JS/JSX** (`frontend/src/`): `npx prettier --write <file>` + `npx eslint <file>`.

## 2. Tests covering changed file

Not the entire suite unless cross-cutting.

- **Backend:** `pytest tests/test_<area>.py -v`
- **Rust:** `cargo test --manifest-path src-tauri/Cargo.toml <test_name>`
- **Frontend:** `node --experimental-vm-modules <test_file>`

`test-runner` subagent knows path mapping + classifies failures (real-bug / flaky / stale-test / setup-error).

## 3. UI changes — verify in browser

**Preferred:** `e2e-tester` subagent with `preview_*` tools — spawns dev servers, navigates, screenshots + console logs. Picks Web Preview vs Tauri WebDriver channel automatically.

**Fallback:** `npm run dev:full` + manual verify.

**Type-check passing ≠ feature working.** If you can't launch a browser, say so explicitly.

## 4. FILE_MAP / index docs

Added file or significantly changed existing → re-read `docs/FILE_MAP.md` or run `python scripts/regen_maps.py` for `MAP.md`/`MAP_L2.md`.

Non-trivial multi-file → `doc-syncer` subagent (also handles `backend-index.md` / `frontend-index.md` / `rust-index.md` / `docs/research/_INDEX.md`).

## 5. Research-pipeline graduation

Working in `inprogress_<slug>.md` and code shipped → full graduation checklist in `research-pipeline.md`. **You may NOT promote `inprogress_` → `implemented_` without explicit user sign-off.**

## 6. Summarise in 1–2 sentences

What changed + what verified. Diff speaks for itself. Concrete: `"Added POST /api/duplicates/scan with _db_write_lock. ruff + pytest tests/test_database.py green. backend-index.md updated."`

---

Step fails → fix root cause. Don't bypass.
