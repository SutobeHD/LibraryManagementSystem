# CLAUDE.md — Agent Operating Manual

> Read this first. Then `docs/FILE_MAP.md`. Then start working.

This repo is set up for **highly autonomous agentic coding**. Run, build, test, refactor, and self-correct without asking for permission on every step. Ask only when the action is destructive, irreversible, or changes shared state (push, force-push, dropping data, deleting branches).

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

## Build / Dev / Test — full command list

All commands run from repo root unless noted.

### Day-to-day dev

```bash
npm run dev:full          # backend (port 8000) + frontend (port 5173), concurrent
npm run tauri dev         # full desktop app (Rust + Python + React)
npm run dev               # frontend only
```

### Build

```bash
npm run build             # frontend production build → frontend/dist
npm run tauri build       # full desktop binary (Windows .msi / .exe via backend.spec)
```

### Test

```bash
pytest                    # Python backend tests (tests/)
pytest tests/test_analysis.py -v   # single file
```

> Frontend has no test runner wired yet — if you add one, default to Vitest and update this file.

### Audit / lint

```bash
npm run audit             # npm audit --audit-level=high + signatures
npm run lint:lockfile     # lockfile-lint with validate-https / allowed-hosts npm
./scripts/security-audit.ps1     # full Windows audit (or .sh on Unix)
```

### Cleanup

```bash
npm run cleanup           # kill anything on ports 8000 / 5173
```

### Helper scripts (`scripts/`)

- `local-release.ps1` — local build & version bump
- `screenshot.py` — diagnostic screenshot capture
- `security-audit.{ps1,sh}` — dependency + lockfile audit
- `test_xml_sync.py` — XML pipeline smoke test

---

## Coding rules — non-negotiable

These are **load-bearing constraints**, not style preferences. Violating them breaks the project.

### Dependency pinning (Schicht-A Hardening 2026)

- **Python:** every dep in `requirements.txt` is `==X.Y.Z`. Never relax to `>=` or `~=`. Never bump without checking CVE notes + running `pytest`.
- **Node:** lockfile is canonical. Run `npm run lint:lockfile` after any dep change. `npm ci` (not `npm install`) for reproducible installs in CI.
- **Rust:** Cargo.lock is committed. Don't `cargo update` casually.

### Secrets & paths

- `.env` is **never committed**. `.env.example` is the only template. Required keys today: `SOUNDCLOUD_CLIENT_ID`, `SOUNDCLOUD_CLIENT_SECRET`.
- `ALLOWED_AUDIO_ROOTS` sandboxes filesystem access — never bypass via `os.path.normpath` tricks. Use `Path.is_relative_to(resolved_root)` (already canonical pattern in `app/main.py:validate_audio_path`).
- System endpoints sit behind `X-Session-Token` (one-shot via `POST /api/system/init-token`). Never leak the token in logs/heartbeats.

### Stack boundaries

- Audio DSP heavy lifting → Rust (`src-tauri/src/audio/`) for realtime, Python (`app/analysis_engine.py`, librosa/madmom/essentia) for offline.
- HTTP / orchestration / DB → Python.
- UI / state / interactions → React.
- Don't cross layers needlessly. Don't reimplement Python logic in JS or vice versa.

### Backend concurrency

- `app/main.py:_db_write_lock` (RLock) serialises **all** Rekordbox `master.db` writers. Any new write path through `rbox`/`pyrekordbox` MUST acquire it.
- `app/anlz_safe.py:SafeAnlzParser` (ProcessPoolExecutor, `max_workers=1`) quarantines rbox calls — rbox 0.1.5/0.1.7 has known `unwrap()` panics. Never call rbox parsing directly from the main process.

### rbox version quirks

- rbox 0.1.7's `OneLibrary.create()` and `create_content()` are broken. Workaround: `app/usb_one_library.py` uses a pre-built template (`app/templates/exportLibrary_template.db`) and mutates it. Don't "fix" this by re-enabling create_content — it raises `Unexpected null for non-null column`.

### Pioneer USB export

- PDB byte layout in `app/usb_pdb.py` is verified **byte-for-byte against a real Pioneer-exported F: drive**. Comments explain every magic number. Read the file before changing it. A wrong flag/offset corrupts the stick silently — Rekordbox refuses to load it without telling you why.

---

## Agentic operating mode — what to do without asking

You have broad permission to act locally. The settings allowlist (`.claude/settings.json`) reflects this. Default behaviour:

### Just do these

- Run any `npm run …`, `python -m app.main`, `pytest`, `cargo check`, `cargo fmt`, `cargo build` command.
- Read any file, search across the codebase, use Grep/Glob freely.
- Edit / create / delete files in the working tree.
- Run linters and formatters after edits (`ruff format app/`, `cargo fmt`, `prettier --write frontend/src`).
- `git status`, `git diff`, `git log`, `git branch`, `git add`, `git restore` (staging-area only), `git stash`.
- **`git commit`** — commit atomically and intensely after each logical unit of work. See "Commit strategy" section.
- `git fetch`, `git pull --ff-only` (fast-forward only — safe).
- `git checkout -b`, `git switch -c` (new branches).
- `gh pr view`, `gh pr list`, `gh issue view`, `gh run list` — read-only GitHub queries.
- Use parallel tool calls aggressively when steps are independent.
- Spawn subagents (`Explore`, `general-purpose`, `Plan`) for broad searches / multi-step research.

### Confirm first

- `git push`, `git push --force` (always confirm; **never** force-push to `main`).
- `git reset --hard`, `git clean -fd`, branch deletion, history rewrites.
- `gh pr create`, `gh pr merge`, `gh pr close`, `gh issue close`.
- `npm install <new-dep>` / `pip install <new-dep>` / `cargo add` — adding a new dep is a security decision.
- Anything under `requirements.txt`, `Cargo.toml`, `package.json` `dependencies` that bumps versions.
- Touching `.env*` files (read OK, write needs sign-off).
- Deleting files outside `tmp/`, `temp/`, `scratch/`, `work/`, `build/`, `dist/`, `target/`.

### Don't

- Never edit user data: `**/music/`, `**/exports/`, `**/backups/`, USB drive paths, `master.db`, `*.DAT`, `*.ANLZ` files outside `app/templates/`.
- Never disable hooks (`--no-verify`), bypass signing, or skip security audits.
- Never commit `.env`, `*.db`, audio files, build artefacts (they're in `.gitignore` for a reason).

---

## Commit strategy — commit intensely, atomically, autonomously

**Default: commit aggressively without asking.** The user wants a dense, atomic commit history. After **every logical unit of work**, create a new commit. Don't batch unrelated changes. Don't wait until the end of a long session.

### When to commit (autonomous — just do it)

- **One feature / fix / refactor = one commit.** Don't mix.
- **After each passing test cycle** when the change is meaningful.
- **Before starting an unrelated change** — flush current work first.
- **After a successful build / lint / type-check** that gates the change.
- **When a doc update accompanies a code change** — same commit; docs follow code.
- **After spawning out a subagent's deliverable** that compiles/tests cleanly.
- **Before any risky/exploratory change** — checkpoint the known-good state.

Rough cadence guide: if you've touched **2–6 files** for **one coherent purpose** and the tree is in a green state (or at least no worse than before) — that's a commit.

### When NOT to commit autonomously

- Tree is broken (failing tests/build introduced by your change). Fix first, then commit.
- Changes are **uncoupled** — split into multiple commits first.
- File touched contains anything `.env`-like, secrets, audio files, `master.db`, USB binaries — surface to user, don't add.
- The user said "don't commit yet" in this session.

### Commit message style

Follow [Conventional Commits](https://www.conventionalcommits.org/) loosely. One-line subject (under 70 chars), optional body:

```
<type>(<scope>): <imperative summary>

<optional body — why, not what>
```

Types in use here: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `build`, `ci`, `revert`.

Scopes that match this repo: `backend`, `frontend`, `tauri`, `audio`, `usb`, `pdb`, `anlz`, `sc` (soundcloud), `analysis`, `db`, `docs`, `claude` (for `.claude/` config), `deps`.

Examples:
- `fix(pdb): use 0x34 flag on data pages (was 0x24, corrupted F:-drive parity)`
- `feat(backend): add POST /api/duplicates/scan with _db_write_lock`
- `refactor(audio): extract beatgrid bisect logic from anlz_safe`
- `docs(file-map): add row for app/usb_mysettings.py`
- `chore(claude): tighten doc-syncer agent description`

### Push policy — stays confirmed

- **`git push` requires user confirmation.** Always. Even for `main`.
- **Never `--force` push** without explicit, scoped permission. Never to `main`/`master`.
- Run `git fetch && git status -sb` **before** push and surface drift.

### Commit workflow (automatic)

```bash
# Don't blanket-add. Stage what you touched, by name.
git add <file1> <file2> ...

# Commit. Use a HEREDOC for multi-line bodies.
git commit -m "<subject>"

# Verify
git log -1 --oneline
```

For multi-line bodies use the pattern from `~/.claude/CLAUDE.md` rules — pass via HEREDOC, include the `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` trailer.

### Anti-patterns

- One mega-commit at end of session covering 4 unrelated things. **Forbidden.**
- "WIP" or "stuff" or "fix" without scope. **Forbidden.**
- Commit with broken tests **without saying so** in the body. Bad. If you must checkpoint, label it: `chore(wip): partial route refactor, tests red — see body`.
- Amending a commit that was already pushed. Make a new commit.
- `--no-verify` to skip hooks. Fix the hook failure instead.

---

## Git sync status — when to check, when to skip

Don't blindly `git fetch` before every prompt — it's slow and usually wasted. Instead, apply this heuristic at the **start of a task** (not every turn):

### Check sync status when:

- The user mentions a **PR, branch, commit, merge, or remote state** ("is X already on main?", "did the fix land?", "rebase onto main", "what's on the PR?").
- The user describes a **feature/file they expect to exist** that you don't immediately find locally — could be unpulled remote work.
- About to **`git push`** — always run `git fetch && git status -sb` first to see if the remote moved ahead. Refuse to force-push without explicit user OK.
- About to **`git commit`** and the last fetch was hours ago or session is long-running — quick check prevents committing on top of a stale base.
- A bug is reported that the user says "should be fixed already" — could be a checkout that's behind.
- **First task after a long pause** (session resumed, new chapter starting) — quick orientation is cheap.
- The user asks about CI / GitHub Actions / release state — check `gh run list` + `git log origin/main..HEAD`.

### Skip sync check when:

- The task is **pure local work** with no remote reference (refactor, rename, doc edit, local test run).
- You **just** fetched in this session and nothing about the conversation suggests remote moved.
- The user explicitly says "just do X" — they don't want overhead.
- Read-only exploration / explanation.

### How to check (cheap → expensive)

1. **Cheapest:** `git status -sb` — shows local ahead/behind from last fetch. No network.
2. **Standard:** `git fetch --quiet && git status -sb` — ~1-2 s, refreshes ahead/behind. Use before push/commit-on-stale-base.
3. **Deeper:** add `git log --oneline ..@{u}` to see what's new upstream, or `gh pr list --state open --author @me` for PRs.

Surface findings in 1 line: `"local: 2 ahead, 0 behind origin/main — safe to push"` or `"local: 0 ahead, 3 behind — pull first?"`. Don't paste raw output unless asked.

### Anti-pattern

Don't run `git fetch` then proceed silently if there's drift. Always tell the user **before** you commit/push on a base that moved. The user pulling is their decision; surface the state, don't decide for them.

---

## Self-correction loop (post-edit workflow)

After **every code edit**, before reporting done, do these in this order:

1. **Run the relevant linter / formatter:**
   - Python files → `ruff check <file>` then `ruff format <file>` if available; otherwise just check syntax with `python -c "import ast; ast.parse(open('<file>').read())"`.
   - Rust files → `cargo check --manifest-path src-tauri/Cargo.toml` and `cargo fmt --manifest-path src-tauri/Cargo.toml`.
   - JS/TSX → `npx prettier --write <file>` if prettier is configured.
2. **Run the tests that cover the file you changed**, not the entire suite (unless the change is cross-cutting).
3. **For UI changes:** start `npm run dev:full` and verify the feature in a browser. Type-check passing ≠ feature working. If you can't launch a browser, say so explicitly.
4. **Re-read `docs/FILE_MAP.md` if you added a file or significantly changed an existing one** — update the relevant row. The map is the single source of truth for navigating this repo.
5. **Summarise in 1–2 sentences** what changed and what's verified. No long recaps — the diff speaks for itself.

If a step fails, fix the root cause. Don't bypass.

---

## Where to find things — fast

- **Master map:** `docs/FILE_MAP.md` (one-line-per-file for the whole codebase)
- **Architecture & data flows:** `docs/architecture.md`
- **123 FastAPI routes:** `app/main.py` (see `docs/backend-index.md` for grouped route list)
- **React component index:** `docs/frontend-index.md`
- **Rust/Tauri index:** `docs/rust-index.md`
- **Security model:** `docs/SECURITY.md`
- **Project overview & history:** `docs/PROJECT_OVERVIEW.md`
- **Naming conventions:** `docs/NAMING_MAP.md`
- **Changelog:** `CHANGELOG.md`

When unsure where logic lives, search `docs/FILE_MAP.md` first. It's cheaper than grepping.

---

## Slash commands available

Defined in `.claude/commands/`:

- `/dev-full` — start backend + frontend dev servers
- `/tauri-dev` — start full desktop app
- `/tauri-build` — production desktop build
- `/test-py` — run Python test suite
- `/audit` — npm audit + lockfile lint + security-audit script
- `/sync-docs` — refresh `docs/FILE_MAP.md` + index docs from current code
- `/route-add` — guided: add a new FastAPI route with all the right boilerplate
- `/full-check` — run everything: lint + test + audit + cargo check
- `/sync-check` — fetch + report local-vs-origin drift + open PRs
- `/commit` — stage + atomic commit with Conventional-Commits message (splits unrelated changes)

---

## Subagents available

Defined in `.claude/agents/`:

- `doc-syncer` — keep `docs/FILE_MAP.md`, `backend-index.md`, `frontend-index.md`, `rust-index.md` in sync with the codebase
- `route-architect` — design + scaffold new FastAPI routes including auth gates, DB locks, and response models
- `audio-stack-reviewer` — cross-stack reviewer for Python (librosa/madmom) + Rust (cpal/symphonia/rubato) audio paths

Use them when a task fits — they keep the main context clean.

---

## Working style

- **Be terse.** German is the user's default conversation language; replies in Caveman style (no articles/filler) for code and config tasks. Code/file contents stay in English to match the repo.
- **Edit existing files** before creating new ones.
- **No comments unless the WHY is non-obvious** (a workaround, a known panic, a verified-against-byte-layout invariant). Don't narrate WHAT.
- **No new markdown files unless asked.** This file is enough.
- **Parallel tool calls** are free. Use them.
- **Commit autonomously, intensely, atomically** (see Commit strategy). **Never auto-push** — always confirm.

---

## When you hit something weird

1. Check `docs/FILE_MAP.md` row for that file — likely a non-obvious invariant is documented.
2. Check `CHANGELOG.md` for recent rework in that area.
3. Check `git log -- <file>` for recent commits.
4. If a parser/writer/exporter behaves oddly, suspect rbox version quirks — check `app/anlz_safe.py` and `app/usb_one_library.py` for the known patterns.
5. If the desktop app misbehaves, check that the Python sidecar booted: `curl http://127.0.0.1:8000/api/system/health`.
