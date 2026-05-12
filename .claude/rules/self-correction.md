# Self-correction loop (post-edit workflow)

After **every code edit**, before reporting done, do these in this order:

## 1. Run the relevant linter / formatter

Note: a PostToolUse hook (`.claude/hooks/format-on-edit.py`) wired in `.claude/settings.json` auto-runs the formatter after every `Edit`/`Write`. You usually don't need to invoke these manually — but you DO need to verify they didn't fail.

If the hook is unavailable or you want to check explicitly:

- **Python** (`app/`, `tests/`): `ruff check <file>` + `ruff format <file>` (config in `pyproject.toml`). For type checks: `mypy <file>`. As fallback: `python -c "import ast; ast.parse(open('<file>').read())"`.
- **Rust** (`src-tauri/src/`): `cargo check --manifest-path src-tauri/Cargo.toml` + `cargo fmt --manifest-path src-tauri/Cargo.toml` + `cargo clippy --manifest-path src-tauri/Cargo.toml -- -D warnings`.
- **JS/JSX** (`frontend/src/`): `npx prettier --write <file>` + `npx eslint <file>` (config in `frontend/.eslintrc.cjs`).

## 2. Run the tests that cover the file you changed

Not the entire suite (unless the change is cross-cutting).

- **Backend:** `pytest tests/test_<area>.py -v`
- **Rust:** `cargo test --manifest-path src-tauri/Cargo.toml <test_name>`
- **Frontend:** `node --experimental-vm-modules frontend/src/audio/dawState/dawReducer.test.js` (or whatever the test scaffold is for the area)

Use the `test-runner` subagent for a focused run + failure analysis. It knows the test-path mapping per area and can classify failures (real-bug / flaky / stale-test / setup-error).

## 3. For UI changes — verify in a real browser

**Preferred:** use the `e2e-tester` subagent with `preview_*` tools — it spawns dev servers, navigates, captures screenshots + console logs. Picks the right channel (Web Preview vs Tauri WebDriver) automatically.

**Fallback:** start `npm run dev:full` manually and verify by hand.

**Type-check passing ≠ feature working.** If you can't launch a browser, say so explicitly in the report.

## 4. Re-read `docs/FILE_MAP.md` if you added a file or significantly changed an existing one

Or run `python scripts/regen_maps.py` to regenerate `docs/MAP.md` + `docs/MAP_L2.md` deterministically (covers `FILE_MAP`-style nav from the AST).

For non-trivial multi-file changes, use the `doc-syncer` subagent — it also handles `backend-index.md` / `frontend-index.md` / `rust-index.md` / `docs/research/_INDEX.md`.

## 5. Research-pipeline lifecycle graduation

If working in `docs/research/implement/inprogress_<slug>.md` and code just shipped:

- Update `docs/architecture.md` to reflect the new data flow.
- Update `docs/FILE_MAP.md` (or run `/regen-maps`) with new files.
- Update the relevant `docs/{backend,frontend,rust}-index.md`.
- Update `CHANGELOG.md` if user-visible (run `/changelog-bump`).
- `git mv` the doc to `docs/research/archived/implemented_<slug>_<YYYY-MM-DD>.md`.
- Append a `Lifecycle` line and update `docs/research/_INDEX.md`.
- **Only then commit.**

**You may NOT promote `inprogress_` → `implemented_` without explicit user sign-off** — see `research-pipeline.md`.

## 6. Summarise in 1–2 sentences

What changed and what's verified. No long recaps — the diff speaks for itself. Concrete: `"Added POST /api/duplicates/scan with _db_write_lock. ruff + pytest tests/test_database.py green. backend-index.md updated."`

---

If a step fails, fix the root cause. Don't bypass.
