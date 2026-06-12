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

**Fresh clone / new worktree — install deps FIRST.** `tauri` and `vite` live in `node_modules/.bin`; a fresh tree has none → "command not found". Run `npm install` (root) **and** `npm install --prefix frontend` before any dev/build. For UI verification prefer `npm run dev:full` (browser, no build) — `npm run tauri dev` / `tauri build` additionally need the bundled Python sidecar binary. When a change needs in-app checking, hand the user a paste-ready `cd <path> && npm run dev:full` instead of waiting to be asked.

Full tooling reference in `.claude/rules/tooling.md`.

---

## Where to find things — fast

### Navigation docs (start here, cheapest to expensive)

- **L1 — `docs/MAP.md`** — auto-generated file → 1-line purpose. **First stop** when looking for where logic lives.
- **L2 — `docs/MAP_L2.md`** — auto-generated L1 + public classes/functions/methods. For finding a specific symbol.
- **L3 — `docs/backend-index.md`** — ~140 FastAPI routes grouped by feature.
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
- **Hooks:** `.claude/hooks/format-on-edit.py` (PostToolUse Edit|Write), `.claude/hooks/auto-push-after-commit.py` (PostToolUse Bash), `.pre-commit-config.yaml` (manual install)
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
| `/pipeline` | Show research pipeline state + the open approval gate |
| `/dashboard` | Start the local research-pipeline web dashboard |
| `/gate-list` | List the open approval gate + PRs waiting to test & merge |
| `/gate-status` | Show one research doc's pipeline state + next step |
| `/approve` | Approve the doc at `approvalgate_` — start implementation |
| `/reject` | Reject the doc at `approvalgate_` — send the plan back |
| `/print-routine` | Print a routine prompt below `---` (paste-ready for claude.ai/code) |
| `/commit` | Stage + atomic commit with Conventional-Commits message |
| `/pr-new` | Create branch + push + open PR |
| `/changelog-bump` | Append unreleased commits to CHANGELOG.md |
| `/help` | List all slash commands + subagents |

---

## AI autonomy & remote routines — streamlining bias

This repo runs a **multi-agent research pipeline**: **8 remote routines** (claude.ai/code) advance `docs/research/` docs autonomously while the user is afk. Daily routines trigger on a doc's **state** (folder + filename prefix); cross-cutting routines maintain pipeline health (idea generation, re-validation, conflict detection). Each routine spawns multiple specialist sub-agents in parallel; verification agents gate every stage. The user signs off **once** — at the single approval gate (`approvalgate_`: idea summary + mockup + change list) — then tests + merges the finished branch.

### Daily work-state routines

| Routine | Cron (Berlin) | Reads state | Does |
|---|---|---|---|
| `research-draft` | 05:00 | `drafting_` | Scout + Prior-Art + Risk-Surface (parallel) → Worker → Verifier → `exploring_` (autonomous) |
| `research-explore` | 06:00 + 14:00 | `exploring_` | Tiered per-OQ (Codebase + Web + Synthesis) → Adversarial + Citation + Research-Verifier → `evaluated_` (autonomous) |
| `research-plan` | 13:00 | `evaluated_`, `rework_` | Planner → parallel Threat-Modeller + Migration + Perf-Budget → Test-Plan → Task Queue → Reviewer → Mockup+Summary → `approvalgate_` (the gate) |
| `research-implement` | 03:00 + 15:00 | `accepted_`, `inprogress_` | Approach-Probe → Code → Standard + Security + Test-Coverage Reviews → Doc-Sync → PR (you test + merge) |
| `research-triage` | 07:30 | all (read-only) | Pipeline Digest issue: gates, ready PRs, routine activity, trend metrics, loop-guards, blockers |

### Cross-cutting routines

| Routine | Cron (Berlin) | Reads | Does |
|---|---|---|---|
| `research-spawn` | Sun 04:00 | TODO/FIXME, CHANGELOG, GH issues, MAP smells, deps (read-only) | 5 parallel scouts → Idea Backlog issue with prioritised proposals. **User authors `## Original Idea`.** |
| `research-watchdog` | 1st-of-month 04:00 | 5 oldest unchecked `archived/implemented_*` | parallel probes (code refs / deps / external invariants / library health) → `## Lifecycle` line + follow-up proposals into Idea Backlog |
| `research-cross-linker` | Tue 04:30 | all active docs | per-doc Extractors + Overlap-Analyser → `related:` frontmatter + `## Cross-links` block; CONFLICT notifications |

`research-implement` may write code — bounded to `inprogress_` docs, `routine/*` branches, approval-gate-approved Task Queue items (no new research). It never merges/rebases to `main` — the user tests the branch + merges. `research-watchdog` and `research-cross-linker` write narrow doc edits only (Lifecycle lines / frontmatter / Cross-links block). `research-spawn` never creates `idea_*.md` — only proposals in the Idea Backlog issue (user authors the real Original Idea).

Full rules: `.claude/rules/research-pipeline.md` + `docs/research/README.md`. Routine prompts versioned in `docs/research/routines/`.

**Streamlining default ON.** Spotted a manual ritual (state moves, doc syncs, multi-step bookkeeping)? Automate it — slash-command, hook, routine, marker — and show the diff. See `.claude/rules/agentic-mode.md` "Streamlining bias".

Manage routines: https://claude.ai/code/routines or via `/schedule` skill.

---

## Subagents — DEFAULT ON

Spawn the agent when its trigger fires. Inline-doing the agent's work floods main context. Full decision tree + cost calibration + anti-patterns in `.claude/rules/working-style.md` (Subagent delegation section).

Quick reminder of triggers: `doc-syncer` (multi-file/rename), `route-architect` (before `app/main.py` route edit), `audio-stack-reviewer` (audio/anlz/usb_pdb edits), `test-runner` (pre-commit/push), `e2e-tester` (UI changes), `Explore` (broad search > 2 locations), `general-purpose` / `Plan` / `claude-code-guide` for research/architecture/Claude-Code questions.

---

## Git identity — verify in fresh clone

```bash
git config user.email   # must be: 46030159+SutobeHD@users.noreply.github.com
git config user.name    # must be: SutobeHD
```

Set per-repo (no `--global`) if not. Reasoning + rewrite recipe in `.claude/rules/commit-and-git.md`.
