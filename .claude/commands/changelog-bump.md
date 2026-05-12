---
description: Append unreleased commits to CHANGELOG.md under [Unreleased], grouped by Conventional Commits type
argument-hint: "[release version, e.g. 1.2.0 — if omitted, just refreshes [Unreleased]]"
allowed-tools: Bash, Read, Edit
---

Update CHANGELOG.md from recent commits. Optional release version: $ARGUMENTS

## Process

1. **Find the cut-off point:**
   ```bash
   # Last tag (release), or the commit that last touched CHANGELOG.md as fallback
   LAST_TAG=$(git describe --tags --abbrev=0 2>/dev/null)
   if [ -z "$LAST_TAG" ]; then
     LAST_CHANGELOG_COMMIT=$(git log -1 --format=%H -- CHANGELOG.md)
     RANGE="${LAST_CHANGELOG_COMMIT}..HEAD"
   else
     RANGE="${LAST_TAG}..HEAD"
   fi
   git log --pretty=format:"%h%x09%s" $RANGE -- . ':!CHANGELOG.md'
   ```

2. **Parse commits by Conventional-Commits type.** Group into buckets:
   - `Added` ← `feat(...)`
   - `Fixed` ← `fix(...)`
   - `Changed` ← `refactor(...)`, `perf(...)`
   - `Removed` ← `revert(...)`
   - `Documentation` ← `docs(...)`
   - `Tests` ← `test(...)`
   - `Build` ← `build(...)`, `ci(...)`, `chore(deps...)`, `chore(claude...)`
   - `Internal` ← everything else (`chore` without notable scope)

   Drop the type/scope prefix from the subject for readability. Keep scope as suffix in parens: `subject (scope)`.

3. **Read existing CHANGELOG.md.** Identify the `## [Unreleased]` section (or create one at the top if missing — under the `# Changelog` heading).

4. **Merge — never duplicate:** for each grouped commit, check if a line with the same `(<hash>)` reference already exists. If yes, skip.

5. **If `<version>` argument was provided:**
   - Rename `## [Unreleased]` → `## [<version>] - YYYY-MM-DD`
   - Add a fresh empty `## [Unreleased]` at the top.

6. **Write the updated CHANGELOG.md.** Preserve formatting style of the existing file (Keep a Changelog convention is the default).

7. **Report (3 lines max):**
   - Commits ingested: N
   - Section updated: `[Unreleased]` (or `[<version>] - <date>`)
   - Suggested commit message: `docs(changelog): bump unreleased section with N commits`

## Don'ts

- Don't commit the changelog update — let the user review first.
- Don't tag a release (`git tag`) — that's an explicit user action.
- Don't include commits that already appear in earlier release sections.
- Don't summarise commits creatively. Use the actual commit subject (cleaned of type/scope prefix). The commit message is the source of truth.
- Don't include commits to `CHANGELOG.md` itself — would be self-referential.
