# Working style

## Communication — three buckets

- **Internal** (tool calls, thinking, plans, subagent prompts, search queries, commit messages): **Caveman.** Drop articles/filler/hedges. Fragments OK. Direct nouns + minimal verbs.
- **Persistent files written to repo** (research docs, FILE_MAP/index entries, MEMORY entries, CHANGELOG lines, doc syncs): **Caveman+.** Bullets > prose. Respect per-section word caps in `_TEMPLATE.md`. No "we considered", "it should be noted", "in order to". Direct subject + verb + object.
- **User output** (visible turn replies): **Detailed without fluff.** No "Großartig!", no "Lass mich kurz...", no "Hoffe das hilft", no "Sieht das gut aus?" (unless really asking). Lists, tables, code blocks, full commands, `file:line` refs welcome. Long is fine when content earns it; what's banned is padding.

**Language:** German for conversation. Code/filenames/commit messages/file contents stay English.

## Code & files

- Edit existing files before creating new ones.
- No comments unless WHY is non-obvious (workaround, known panic, verified-against-byte-layout invariant). Don't narrate WHAT.
- No new markdown files unless asked.
- No emojis in code/config unless asked.

## Tooling discipline

- Parallel tool calls when independent — free.
- Commit autonomously, atomically (see `commit-and-git.md`). Push autonomous, non-force.
- PostToolUse hook runs `ruff format` / `cargo fmt` / `prettier` automatically after `Edit`/`Write` — only run manually if the hook reports failure.

---

## Subagent delegation — default ON

Subagents underused. Spawn by default for non-trivial work; keeps main context clean, gets focused expert with right tools pre-bound.

### Decision tree — spawn if…

| Trigger | Spawn |
|---|---|
| Multi-file change in `app/`, `frontend/src/`, `src-tauri/src/`, `tests/`, `scripts/`, `docs/research/{research,implement,archived}/` (non-trivial) | `doc-syncer` (post-edit, pre-commit) |
| Edit in `app/{analysis,anlz,audio,usb_pdb,phrase_generator}_*.py` or `src-tauri/src/audio/**` | `audio-stack-reviewer` (runs cargo + ruff + mypy actively) |
| New/changed FastAPI route (esp. `master.db` writers, `require_session`-gated mutations, new Pydantic models) | `route-architect` (start **before** touching `app/main.py`) |
| Non-doc-only code change before commit/push | `test-runner` |
| Frontend change OR backend route the UI calls | `e2e-tester` (before declaring "done") |
| Broad search > 2 likely locations | `Explore` |
| Open-ended research / "how does X work" multi-step | `general-purpose` (or `claude-code-guide` for Claude Code itself) |
| Implementation strategy with > 1 plausible approach | `Plan` |

### Cost calibration

5 inline Read/Grep on the same sub-task ≈ 1 subagent spawn. Spawn earlier, not later. Inline = ~15-30k in main context; subagent = ~5-10k + ~1k summary back.

### When NOT to spawn

- One file read + one edit — no analysis needed.
- User just gave context that a delegation would lose.
- Same agent twice in a row for related sub-problems → `SendMessage` to continue, don't re-spawn.

### Anti-patterns

- 6+ inline Read/Grep when one `Explore` summarises.
- Manual FILE_MAP edit instead of `doc-syncer`.
- Inline `pytest` + copy-pasting output instead of `test-runner`.
- Self-reviewing audio-stack edit instead of `audio-stack-reviewer`.
- Forgetting `e2e-tester` on UI changes — type-check ≠ feature works.
