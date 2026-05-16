# Commit strategy + Git workflow

## Git identity — GitHub noreply email

Always: `46030159+SutobeHD@users.noreply.github.com`, name `SutobeHD`. Per-repo (no `--global`).

**Why noreply:** GitHub's "Block command line pushes that expose my email" rejects pushes (`GH007`) with non-public emails. Noreply also avoids leaking real email permanently into git history.

### Verify in fresh clone (before first commit)

```bash
git config user.email   # expect: 46030159+SutobeHD@users.noreply.github.com
git config user.name    # expect: SutobeHD

# Fix if wrong:
git config user.email "46030159+SutobeHD@users.noreply.github.com"
git config user.name "SutobeHD"
```

### Wrong email AFTER local commits, BEFORE first push — rewrite is OK

Local-only commits aren't public yet, so the "revertable" rule doesn't apply. **Bound the rebase to `origin/main`, NOT `--root`** (`--root` would rewrite already-public upstream commits = effectively force-push, forbidden).

```bash
git rebase --exec 'git commit --amend --no-edit --reset-author' origin/main
```

`--reset-author` reuses current `git config` identity. Run after fixing config. Push afterwards (normal fast-forward — new SHAs but strict descendant of merge-base).

`git rebase --root*` is in the deny list — never run `--root` on a branch with any commits already on `origin`.

### Wrong email AFTER first push — never rewrite

Use `git revert <bad-author-sha>` + new commit with correct author. NOT a history rewrite.

---

## Commit strategy — intense, atomic, autonomous

**Default: commit aggressively without asking.** Dense atomic history. After every logical unit, new commit. No batching unrelated changes. No end-of-session mega-commits.

### When to commit (just do it)

- One feature/fix/refactor = one commit. No mixing.
- After each passing test cycle when meaningful.
- Before starting unrelated change — flush current first.
- After successful build/lint/type-check gating the change.
- Doc update with code change → same commit, docs follow code.
- After subagent deliverable that compiles/tests cleanly.
- Before risky/exploratory change — checkpoint known-good state.

**Cadence:** 2–6 files for one coherent purpose, tree green (or no worse) → commit.

### When NOT to commit autonomously

- Tree broken (failing tests/build you introduced). Fix first.
- Changes uncoupled → split into multiple commits.
- File contains `.env`-like content, secrets, audio, `master.db`, USB binaries → surface to user.
- User said "don't commit yet" this session.

### Commit message — Conventional Commits

```
<type>(<scope>): <imperative summary, <70 chars>

<optional body — why, not what>
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `build`, `ci`, `revert`.

Scopes: `backend`, `frontend`, `tauri`, `audio`, `usb`, `pdb`, `anlz`, `sc`, `analysis`, `db`, `docs`, `claude`, `deps`.

Examples:
- `fix(pdb): use 0x34 flag on data pages (was 0x24, corrupted F:-drive parity)`
- `feat(backend): add POST /api/duplicates/scan with _db_write_lock`
- `refactor(audio): extract beatgrid bisect logic from anlz_safe`

### Workflow

```bash
git add <file1> <file2> ...     # by name, never blanket
git commit -m "<subject>"        # HEREDOC for multi-line body
git log -1 --oneline             # verify
```

Multi-line body: HEREDOC with `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` trailer.

### Anti-patterns

- Mega-commit covering 4 unrelated things. **Forbidden.**
- "WIP" / "stuff" / "fix" without scope. **Forbidden.**
- Commit broken tests without saying so. Bad. If checkpointing, label: `chore(wip): partial refactor, tests red — see body`.
- Amending pushed commit. Make new commit.
- `--no-verify`. Deny-listed. Fix the hook failure.

---

## Push policy — autonomous, hook-fired after every commit

Commits push to `origin/<current-branch>` **automatically and immediately**. No asking, no batching.

### How it fires

1. **Soft rule:** after every `git commit`, follow with `git push origin <branch>`.
2. **Hard hook:** `.claude/hooks/auto-push-after-commit.py` (PostToolUse on `Bash`) parses just-landed commit, runs `git fetch --quiet`, checks drift, pushes. Fires whether agent remembers or not.

### Escape clauses (skip auto-push)

- Commit message contains `[skip-push]` or `[no-push]` (case-insensitive, subject/body). Use for multi-commit sequences pushed at end.
- **Local behind origin.** Hook detects via `git status -sb` after fetch, aborts to stderr. Don't auto-rebase/merge (non-revertable SHA change). User pulls manually.
- Detached HEAD — no upstream, skip.
- Push fails (GH007, auth, network). Hook surfaces error to stderr, never reverts commit. Agent fixes (usually git-identity issue).

### Constraint: revertable history

Every push must be revertable via future `git revert`. No public-history rewrites.

### Allowed (autonomous)

- `git push`, `git push origin main/HEAD/<branch>` — fast-forward.
- `git push -u origin <branch>` — first push of new branch.
- `git revert <sha>` — canonical undo for public commits.

### Forbidden (deny-listed in `.claude/settings.json`)

- `git push --force` / `-f` / `--force-with-lease` — all rewrite remote history.
- `git commit --amend` on already-pushed commit.
- `git rebase -i` on already-pushed commits.
- `git reset --hard origin/main` — destroys local commits silently.
- `git branch -D` — destroys branch outright.
- `--no-verify`.

### What "revertable" means

- Every commit lands as normal commit (no amend, no squash).
- Every push is fast-forward (no force).
- Wrong commit → `git revert <sha>` → new commit → push. History grows, never shrinks.
- Sequence to undo → revert in reverse order.

### NOT covered by auto-push (still `ask`)

Tags (`git tag`), merges (`git merge`), cherry-pick, `gh pr create` — workflow decisions stay manual.

---

## Git sync status — when to check

Don't `git fetch` every prompt — slow + usually wasted. Check at **task start**, not every turn.

### Check when

- User mentions PR/branch/commit/merge/remote state.
- User describes feature/file you don't find locally (maybe unpulled remote work).
- About to `git push` — always `git fetch && git status -sb` first.
- About to `git commit` after long pause / hours-old fetch — quick check prevents stale-base commits.
- Bug user says "should be fixed already" — maybe behind.
- First task after long pause — orientation cheap.
- User asks CI/Actions/release state → `gh run list` + `git log origin/main..HEAD`.

### Skip when

- Pure local work, no remote reference (refactor, rename, doc edit, local test).
- Just fetched this session, no signal remote moved.
- User said "just do X".
- Read-only exploration / explanation.

### How (cheap → expensive)

1. `git status -sb` — local ahead/behind from last fetch, no network.
2. `git fetch --quiet && git status -sb` — ~1-2s refresh. Pre-push standard.
3. `git log --oneline ..@{u}` for upstream diff, `gh pr list --state open --author @me` for PRs.

Surface in 1 line: `"local: 2 ahead, 0 behind origin/main — safe to push"`. Don't paste raw output.

### Anti-pattern

Don't `git fetch` then commit/push silently on drifted base. Surface state to user; pulling is their decision.
