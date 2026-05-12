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
- **Commit autonomously, intensely, atomically** (see `commit-and-git.md`). **Never auto-push** — always confirm.
- **Prefer subagents over inline work** for tasks that match an agent's description. `doc-syncer` for sync, `test-runner` for tests, `e2e-tester` for UI, `audio-stack-reviewer` for audio review, `route-architect` for new API routes. Keeps the main context clean.
- **PostToolUse hook** runs `ruff format` / `cargo fmt` / `prettier` automatically after `Edit`/`Write` — don't run them manually unless the hook reported failure.
