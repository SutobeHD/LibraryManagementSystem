# Working style

## Communication — internal vs output

- **Internal** (tool calls, plans, reasoning, search queries, sub-agent prompts): **Caveman style** for token efficiency. Drop articles, filler, hedges. Fragments are fine. Direct nouns + minimal verbs.
- **Output to user** (visible turn replies): **Detailed and thorough but without fluff**. No "Great!", no "Let me help you with that", no marketing phrases, no hedging ("could potentially maybe"). Get to substance immediately. Use lists/tables when structure helps clarity. Concrete verbs > vague phrases. The reply is allowed — and expected — to be long when there's real content to convey; what's banned is the *padding around* that content.

**Banned in user output:** "Großartig!", "Ich helfe dir gerne", "Erfolgreich für dich implementiert", "Hoffe das hilft", "Sieht das gut aus?" (unless really asking), "Lass mich kurz...", "Wie du sehen kannst..."

**Welcomed in user output:** long lists, exhaustive tables, multiple code blocks, full commands, all relevant `file:line` refs, point-by-point reasoning.

**Language:** German for conversation. Code, filenames, commit messages, file contents stay English (the repo is English).

## Code & files

- **Edit existing files** before creating new ones.
- **No comments unless the WHY is non-obvious** (a workaround, a known panic, a verified-against-byte-layout invariant). Don't narrate WHAT.
- **No new markdown files unless asked.** CLAUDE.md + the `.claude/rules/*.md` set is enough.
- **No emojis in code or config files** unless the user explicitly asks. The repo is English-prose plus code; emojis are noise in diffs.

## Tooling discipline

- **Parallel tool calls** are free. Use them when steps are independent.
- **Commit autonomously, intensely, atomically** (see `commit-and-git.md`). Push is also autonomous now (non-force, revertable).
- **PostToolUse hook** runs `ruff format` / `cargo fmt` / `prettier` automatically after `Edit`/`Write` — don't run them manually unless the hook reported failure.

---

## Subagent delegation — default ON

**Subagents are underused. Treat them as the default for any non-trivial work, not as an optional optimisation.** Every spawn keeps the main context clean and gets you a focused expert with the right tools pre-bound.

### Decision tree — spawn an agent if…

| Trigger | Spawn |
|---------|-------|
| Edited any file in `app/`, `frontend/src/`, `src-tauri/src/`, `tests/`, `scripts/`, or `docs/research/{research,implement,archived}/` and the change wasn't trivial | `doc-syncer` (post-edit, before commit) |
| Edited `app/analysis_*.py`, `app/anlz_*.py`, `app/audio_*.py`, `app/usb_pdb.py`, `app/phrase_generator.py`, or any file under `src-tauri/src/audio/` | `audio-stack-reviewer` (runs cargo + ruff + mypy actively) |
| Adding a new FastAPI route, especially one that writes `master.db`, gates on `X-Session-Token`, or needs new Pydantic models | `route-architect` (start *before* touching `app/main.py`) |
| Made a code change that should be tested (anything non-doc-only) | `test-runner` (post-edit, before commit, before push) |
| Frontend component change OR backend route change that the UI calls | `e2e-tester` (post-change, before declaring "done") |
| Broad search across files (e.g. "where is X defined", "find all callers of Y") with > 2 likely locations | `Explore` (general-purpose lookup) |
| Open-ended question / multi-step research / "figure out how X works" | `general-purpose` (or `claude-code-guide` for Claude Code itself) |
| Designing implementation strategy for a feature with > 1 plausible approach | `Plan` (architect agent) |

### Cost / benefit

| Action | Tokens spent | Context savings |
|--------|--------------|-----------------|
| Inline Read of 5 files + Grep + analysis | ~15-30k in main context | 0 |
| Spawn `Explore` with the same task | ~5-10k for the subagent + a 1k summary back | ~25k freed in main |

Once you've spent more than ~5 tool calls on the same sub-task, you've already paid for a subagent spawn. Default to spawning earlier.

### When NOT to spawn

- The work is one file read + one edit — no analysis needed.
- The user is mid-conversation and a delegation would lose context they just gave you.
- The agent's description doesn't match the task at all (don't force-fit).
- You'd be spawning the same agent twice in a row for related sub-problems — instead, use `SendMessage` to continue the existing agent with new instructions (preserves its context).

### Concrete patterns

**After a multi-file Python edit:**
```
1. Make the edit (PostToolUse hook formats + lints automatically)
2. Spawn test-runner with the area: "Ran edits in app/usb_pdb.py.
   Run pytest tests/test_pdb_structure.py and tell me if byte
   fidelity still holds."
3. While test-runner runs: spawn doc-syncer in parallel: "Updated
   the OneLibrary writer to support a new field. Sync FILE_MAP.md
   and backend-index.md."
4. Wait, integrate both reports, commit.
```

**Before writing a FastAPI route:**
```
1. Spawn route-architect: "Need POST /api/usb/format-wizard that
   writes MYSETTING.DAT. Request body has 5 fields. Should hold
   _db_write_lock? Surface the Pydantic model and the cluster
   in main.py."
2. Apply its proposed route code.
3. Spawn test-runner on tests/test_usb_manager.py.
4. Commit.
```

**Open-ended research:**
```
1. Don't grep 8 files looking for "how does the import pipeline
   work". Spawn general-purpose with the question.
2. It returns a concise map of file:line refs.
3. You read the 2-3 actually-relevant files yourself.
```

### Anti-patterns

- **Running 6+ Read/Grep tool calls inline** when a single `Explore` invocation would answer the question with one summary.
- **Doing a "post-edit doc sync" yourself** by manually editing FILE_MAP.md — `doc-syncer` does this with awareness of the research-pipeline + index docs.
- **Running `pytest` inline and copy-pasting the output** — `test-runner` parses, classifies, summarises in 5 lines max.
- **Reviewing your own audio-stack change** — `audio-stack-reviewer` runs cargo clippy / mypy actively; you would forget at least one tool.
- **Forgetting that `e2e-tester` exists** for UI changes. Type-check passing ≠ feature working — only a real browser run proves it.
