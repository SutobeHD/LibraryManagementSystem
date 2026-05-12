---
description: Create a new branch + push + open a PR via gh — guided, with auto-generated title/body from commit log
argument-hint: "<branch-name> [<PR title>]   e.g.  feat/recommender-baseline  'Recommender rules baseline'"
allowed-tools: Bash, Read
---

Open a pull request for the current work. Args: $ARGUMENTS

## Process

1. **Sync check first.** Always:
   ```bash
   git fetch --quiet
   git status -sb
   ```
   - If behind origin/main → tell the user, suggest `git pull --ff-only` or rebase first. Do not push.
   - If working tree dirty → tell the user, stop. We don't auto-stash.

2. **Identify the commits that will land on the PR:**
   ```bash
   git log --oneline origin/main..HEAD
   ```
   Show this list to the user as a sanity check.

3. **Create the branch from current HEAD:**
   ```bash
   git switch -c <branch-name>
   ```
   If `<branch-name>` already exists locally or remotely, stop and ask the user for a different name.

4. **Push with upstream tracking** (this is in the `ask` list — confirm with user once before executing):
   ```bash
   git push -u origin <branch-name>
   ```

5. **Draft the PR title + body:**
   - Title: user-provided argument, or fall back to the most recent commit's subject.
   - Body: auto-generate from commit log:
     ```
     ## Summary
     - <commit 1 subject>
     - <commit 2 subject>
     - <commit 3 subject>

     ## Test plan
     - [ ] <propose based on what changed — read git diff stat>

     🤖 Generated with [Claude Code](https://claude.com/claude-code)
     ```
   - Read `git diff origin/main..HEAD --stat` to figure out which test commands are relevant (pytest? cargo test? frontend? e2e?).

6. **Create the PR** via `gh pr create` (in `ask` list — confirm with user):
   ```bash
   gh pr create --base main --head <branch-name> --title "<title>" --body "$(cat <<'EOF'
   <body>
   EOF
   )"
   ```

7. **Return the PR URL** so the user can open it.

8. **Switch back to main** so the user isn't left on the feature branch:
   ```bash
   git switch main
   ```

## Don'ts

- Don't push to `main` directly via this command — that's not its purpose.
- Don't merge the PR automatically.
- Don't force-push.
- Don't include CI / pre-commit failures silently — surface them before pushing.
- Don't fabricate test plan items; base them on actual file changes.
