# CLAUDE.md — Agent Operating Manual

> Entry point. Read this in full, then drill into the specific rule file or doc the task points you at.

This repo is set up for **highly autonomous agentic coding**. Run, build, test, refactor, and self-correct without asking for permission on every step. Ask only when the action is destructive, irreversible, or changes shared state (push, force-push, dropping data, deleting branches).

The detailed rules live in `.claude/rules/*.md` — imported below so they're in context every session, but split for maintainability.

## Rule imports

@.claude/rules/working-style.md
@.claude/rules/agentic-mode.md
@.claude/rules/commit-and-git.md
@.claude/rules/self-correction.md
@.claude/rules/coding-rules.md
@.claude/rules/research-pipeline.md
@.claude/rules/tooling.md
@.claude/rules/troubleshooting.md

---

## What this project is

**Music Library Manager** — standalone desktop DJ-library manager. Direct competitor to Rekordbox/Serato. Exports USB sticks that Pioneer CDJ-3000 (and other CDJ/XDJ hardware) read natively. Local-first, no cloud, no subscription.

Three stacks under one roof:

| Layer | Tech | Lives in |
|---|---|---|
| **Frontend** | React 18 + Vite 7 + Tailwind 3 + axios + wavesurfer.js | `frontend/` |
| **Backend (sidecar)** | Python 3.10+ FastAPI on port 8000 | `app/` |
| **Desktop wrapper** | Tauri 2 + Rust (cpal/symphonia/rubato native audio) | `src-tauri/` |
| **External** | FFmpeg in PATH | system |

The Tauri wrapper boots a bundled Python sidecar (`backend_entry.py` / `backend.spec`) and a Vite-served React frontend. Browser dev mode also works (`npm run dev:full`).

---

## Build / Dev / Test — quick reference

```bash
# Dev
npm run dev:full          # backend (8000) + frontend (5173), concurrent
npm run tauri dev         # full desktop app

# Build
npm run build             # frontend production
npm run tauri build       # desktop binary (.msi / .exe on Windows)

# Test
pytest                                              # full Python suite
pytest tests/test_<area>.py -v                      # focused
cargo test --manifest-path src-tauri/Cargo.toml     # Rust
node --experimental-vm-modules <test_file>          # frontend Mocha

# Audit / lint
npm run audit             # npm audit + signatures
npm run lint:lockfile     # lockfile-lint
ruff check app/ tests/    # Python
cargo clippy --manifest-path src-tauri/Cargo.toml -- -D warnings  # Rust
npx eslint frontend/src   # Frontend

# Cleanup
npm run cleanup           # kill anything on :8000 / :5173
```

Full tooling reference in `.claude/rules/tooling.md`.

---

## Where to find things — fast

### Navigation docs (start here, cheapest to expensive)

- **L1 — `docs/MAP.md`** — auto-generated file → 1-line purpose. **First stop** when looking for where logic lives.
- **L2 — `docs/MAP_L2.md`** — auto-generated L1 + public classes/functions/methods. For finding a specific symbol.
- **L3 — `docs/backend-index.md`** — all 146 FastAPI routes grouped by feature.
- **L3 — `docs/frontend-index.md`** — React components with props, IPC calls.
- **L3 — `docs/rust-index.md`** — Tauri commands, modules, crates.
- **`docs/FILE_MAP.md`** — manually curated map (predates MAP.md/MAP_L2.md). Has narrative invariants per file.
- **`docs/architecture.md`** — system diagrams + 8 data flows.

Regenerate L1/L2: `python scripts/regen_maps.py` or `/regen-maps`.

### Feature lifecycle (work-in-flight)

- **`docs/research/`** — feature lifecycle pipeline. Each feature lives in a `<state>_<slug>.md` doc moving through `research/` → `implement/` → `archived/`.
- **`docs/research/_INDEX.md`** — live dashboard. **Check this when the user mentions a feature area** — there may be an in-flight plan you must not contradict.
- **`docs/research/README.md`** — full pipeline rules.
- **`docs/research/_TEMPLATE.md`** — copy when starting a topic (or use `/research-new`).

### Mission docs (active multi-phase work)

- **`docs/HANDOVER.md`** — multi-phase mission briefings (Slopcode-Cleanup style). DoD, status reporting, escalation rules.
- **`docs/e2e-testing.md`** — Web Preview (`preview_*`) vs Tauri WebDriver, channel-picker.

### Reference docs

- **`docs/SECURITY.md`** — Schicht-A pinning, threat model, accepted risks.
- **`docs/PROJECT_OVERVIEW.md`** — high-level overview.
- **`docs/NAMING_MAP.md`** — v0.0.2 rename refactor audit trail.
- **`CHANGELOG.md`** — what shipped when.

### Tooling config

- **Python:** `pyproject.toml` — ruff / black / mypy / pytest
- **Frontend:** `frontend/.eslintrc.cjs`, `frontend/.prettierrc`, `frontend/jsconfig.json`
- **CI:** `.github/workflows/ci.yml` (lint+test), `release.yml`
- **Hooks:** `.claude/hooks/format-on-edit.py` (PostToolUse), `.pre-commit-config.yaml` (manual install)
- **MCP / preview servers:** `.claude/launch.json`, `.mcp.json`

---

## Slash commands available

Defined in `.claude/commands/`:

| Command | Purpose |
|---------|---------|
| `/dev-full` | Start backend + frontend dev servers |
| `/tauri-dev` | Start full desktop app |
| `/tauri-build` | Production desktop build |
| `/test-py` | Run Python test suite (with optional `-k` filter) |
| `/audit` | npm audit + lockfile lint + security-audit script |
| `/full-check` | All quality gates: lint + test + audit + cargo check |
| `/sync-check` | git fetch + drift verdict + open PRs |
| `/sync-docs` | Refresh FILE_MAP + index docs from current code |
| `/regen-maps` | Regenerate `docs/MAP.md` + `docs/MAP_L2.md` from AST |
| `/route-add` | Guided FastAPI route scaffold |
| `/research-new` | Scaffold new research topic |
| `/commit` | Stage + atomic commit with Conventional-Commits message |
| `/pr-new` | Create branch + push + open PR |
| `/changelog-bump` | Append unreleased commits to CHANGELOG.md |
| `/help` | List all slash commands + subagents |

---

## Subagents available

Defined in `.claude/agents/`:

| Agent | Use when |
|-------|----------|
| `doc-syncer` | Sync FILE_MAP / backend/frontend/rust-index / research/_INDEX against code+FS |
| `route-architect` | Design new FastAPI routes with all conventions applied |
| `audio-stack-reviewer` | Review Python DSP + Rust audio. Actively runs cargo check/clippy + ruff + mypy |
| `test-runner` | Run pytest / cargo test / frontend / e2e tests. Parse failures. Classify |
| `e2e-tester` | Drive the app like a user via `preview_*` or Tauri WebDriver. Screenshots + console + network |

Use them when a task fits — they keep the main context clean.

---

## Git identity — verify before first commit in a fresh clone

```bash
git config user.email   # must be: 46030159+SutobeHD@users.noreply.github.com
git config user.name    # must be: SutobeHD
```

If not, set them per-repo (no `--global`). Full reasoning + rewrite recipe for already-committed-but-not-yet-pushed commits in `.claude/rules/commit-and-git.md`.

---

## When in doubt

1. Check `docs/MAP.md` (or `FILE_MAP.md`) for the file.
2. Check `docs/research/_INDEX.md` for in-flight plans.
3. Check `CHANGELOG.md` + `git log -- <file>` for recent context.
4. For deeper rules, consult `.claude/rules/troubleshooting.md`.
