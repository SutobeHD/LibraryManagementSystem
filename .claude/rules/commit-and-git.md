# Commit strategy + Git workflow

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

### Commit workflow (automatic)

```bash
# Don't blanket-add. Stage what you touched, by name.
git add <file1> <file2> ...

# Commit. Use a HEREDOC for multi-line bodies.
git commit -m "<subject>"

# Verify
git log -1 --oneline
```

For multi-line bodies pass via HEREDOC, include the `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` trailer.

### Anti-patterns

- One mega-commit at end of session covering 4 unrelated things. **Forbidden.**
- "WIP" or "stuff" or "fix" without scope. **Forbidden.**
- Commit with broken tests **without saying so** in the body. Bad. If you must checkpoint, label it: `chore(wip): partial route refactor, tests red — see body`.
- Amending a commit that was already pushed. Make a new commit.
- `--no-verify` to skip hooks. Fix the hook failure instead. (Also: the flag is in the `deny` list of settings.json.)

---

## Push policy — stays confirmed

- **`git push` requires user confirmation.** Always. Even for `main`.
- **Never `--force` push** without explicit, scoped permission. Never to `main`/`master`.
- Run `git fetch && git status -sb` **before** push and surface drift.

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
