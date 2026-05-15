# Commit strategy + Git workflow

## Git identity — use the GitHub noreply email

**Always use the GitHub-provided noreply email for commits.** Format:

```
<github-numeric-id>+<github-username>@users.noreply.github.com
```

For this repo: `46030159+SutobeHD@users.noreply.github.com`. The author name is `SutobeHD`.

### Why noreply

- GitHub's privacy setting "Block command line pushes that expose my email" rejects pushes (`GH007`) whose commits carry a non-public email. Without noreply, the first push blocks with: `remote rejected — push declined due to email privacy restrictions`.
- Even if you disable that setting and force-publish your real email into git history, it lives there forever — no way to scrub without rewriting history. Noreply avoids the leak in the first place.
- The KIT student email (`uzfzk@student.kit.edu`) is the user's personal default `git config user.email` outside this repo. Don't carry it into a public open-source repo.

### Setup — first-time per fresh clone

The agent must verify this **before the first commit** in any new clone:

```bash
git config user.email                    # expect: 46030159+SutobeHD@users.noreply.github.com
git config user.name                     # expect: SutobeHD

# If not set correctly, set them in the local repo config:
git config user.email "46030159+SutobeHD@users.noreply.github.com"
git config user.name "SutobeHD"
```

These are **per-repo** settings (no `--global`) so they don't leak to other repos on the same machine.

### If you discover the email was wrong AFTER local commits but BEFORE first push

Rewriting commits *before* they're public is **not** a public-history rewrite — the "revertable" rule does not apply, because there's nothing remote yet for anyone to be holding a reference to.

**Important:** rebase **from `origin/main`**, not `--root`. `--root` would also rewrite the upstream commits that are already public, which would force-push them (forbidden). Bound the rebase to your local-only commits:

```bash
git rebase --exec 'git commit --amend --no-edit --reset-author' origin/main
```

`--reset-author` reuses whatever `git config user.email` + `user.name` are currently set to. Run after fixing the config. Push afterwards (normal fast-forward push — your commit SHAs are new, but `origin/main` only knows about the merge-base, so the rebased branch is a strict descendant).

The settings allowlist permits this *specific* form. `git rebase --root*` is in the **deny** list — never run `--root` on a branch that has any commits already on `origin`.

### NEVER do this AFTER first push

Once any of the commits are on `origin`, `git rebase --root --exec` is the same as a force-push — it rewrites SHAs that other clones may already track. The fix at that point is `git revert <bad-author-sha>` + a new commit with the correct author, **not** a history rewrite.

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

## Push policy — autonomous, auto-triggered after every commit

User wants commits pushed to `origin/main` (or the current branch's tracking remote) **automatically and immediately** after each commit lands locally. No asking, no batching at end-of-session.

### How it actually fires

Two layers of enforcement, defense-in-depth:

1. **Soft rule (this doc):** after every `git commit ...` you run, follow it with `git push origin <current-branch>` unless the soft-rule escape clause applies (see below).
2. **Hard hook:** `.claude/hooks/auto-push-after-commit.py` is wired as a PostToolUse hook in `.claude/settings.json` matching `Bash`. After every `Bash(git commit ...)` it parses the just-landed commit, runs `git fetch --quiet`, checks drift, and pushes. Whether the agent forgets the soft rule or not, the hook still fires.

### Escape clauses (when NOT to auto-push)

- **The commit message contains `[skip-push]` or `[no-push]`** (case-insensitive, in subject or body). Use this when you're about to do multiple related commits and only want to push once at the end.
- **Local is behind origin.** The hook detects this via `git status -sb` after `git fetch` and aborts with a stderr note. Don't auto-rebase or auto-merge — that would change SHAs in non-revertable ways. User pulls manually, then pushes.
- **Detached HEAD.** No upstream branch — skip.
- **Push fails** (GH007 private-email, auth, network). Hook surfaces the error on stderr but never reverts the commit. Agent notices and fixes (typically a git-identity issue — see "Git identity" above).

### Constraint that survives auto-push: revertable history

Every push must remain revertable via a future `git revert` commit. That rules out anything that rewrites public history.

### Allowed (autonomous, no confirmation)

- `git push`, `git push origin main`, `git push origin HEAD`, `git push origin <branch>:<branch>` — normal fast-forward pushes.
- `git push -u origin <branch>`, `git push --set-upstream origin <branch>` — first-time push of a new branch.
- `git revert <sha>` — produces a new commit that inverts a previous one. The canonical "undo button" once something is public.

### Forbidden (in `deny` list of `.claude/settings.json`, hard-blocked)

- `git push --force` / `git push -f` — rewrites remote history. Cannot be undone without coordinated rebases on every clone.
- `git push --force-with-lease` — still rewrites history; the lease just makes it slightly less hostile.
- `git commit --amend` on an already-pushed commit — would require force-push to land.
- `git rebase -i` on already-pushed commits — same problem.
- `git reset --hard origin/main` (or `origin/master`) — destroys local commits silently.
- `git branch -D` — destroys a branch outright.
- `--no-verify` to skip pre-commit hooks.

### Before push — always (handled by the hook)

The auto-push hook runs `git fetch --quiet && git status -sb` itself before pushing. If `behind`, the hook aborts and prints the count to stderr. The agent then surfaces this to the user. **The agent does not rebase or merge to "fix" the drift autonomously** — rebase produces a different SHA chain that may not be revertable cleanly.

If you're invoking `git push` manually (not via auto-trigger), do the same fetch + status check yourself first.

### What "revertable" means in practice

- Every committed change must land as a normal commit (not amend, not squash).
- Every push must be a fast-forward (no force).
- If something was wrong: `git revert <sha>` → new commit, push that. Public history grows but never shrinks.
- If a sequence of commits needs to come out together: revert them in reverse order (`git revert <newest>..<oldest>` or one-by-one). Cleanest for shared history.

### What this does NOT cover

- Tags (`git tag`) — still in `ask`. Tagging a release is a deliberate action.
- Merges (`git merge`) — still in `ask`. Merge commits are revertable, but the user usually wants to decide the merge strategy.
- Cherry-pick (`git cherry-pick`) — still in `ask`. Mostly used in recovery flows where intent matters.
- PR creation (`gh pr create`) — still in `ask`. The choice between direct-push and PR is a workflow decision.

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
