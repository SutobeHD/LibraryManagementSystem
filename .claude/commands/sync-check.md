---
description: Check git sync state vs origin (fetch + ahead/behind + open PRs)
allowed-tools: Bash
---

Run the standard sync check:

```bash
git fetch --quiet
git status -sb
git log --oneline ..@{u} 2>/dev/null | head -20
gh pr list --state open --author @me --limit 10 2>/dev/null
```

Report in 4 lines max:

1. **Local vs origin:** `N ahead, M behind <branch>` — or "in sync"
2. **New upstream commits** (if any): list count + short summary
3. **Open PRs** (if any): count + titles
4. **Recommendation:** "safe to push" / "pull first" / "rebase needed" / "clean"

Skip raw command output. Just the verdict.
