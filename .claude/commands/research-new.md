---
description: Scaffold a new research topic from _TEMPLATE.md → docs/research/research/idea_<slug>.md + update _INDEX.md
argument-hint: "<slug> [<one-line title>]  e.g.  recommender-stems-baseline 'Stem-aware similarity ranking'"
allowed-tools: Read, Write, Edit, Bash
---

Start a new research topic. Slug + optional title: $ARGUMENTS

## Process

1. **Validate slug:**
   - Must be `<area>-<topic>` kebab-case (e.g. `recommender-stems-baseline`, `usb-format-wizard-flow`).
   - Must be unique across `docs/research/{research,implement,archived}/*.md`. Check with `ls docs/research/research/ docs/research/implement/ docs/research/archived/`. If slug already exists, **stop and ask** the user to pick another.

2. **Verify pipeline rules:**
   - Re-read `docs/research/README.md` once if you haven't this session, especially the **Stages and prefixes** and **The One Gate** sections.

3. **Scaffold the file:**
   - Source: `docs/research/_TEMPLATE.md`
   - Target: `docs/research/research/idea_<slug>.md`
   - Copy via `Read` template → `Write` target.
   - Set frontmatter:
     - `slug: <slug>` (no changes through entire lifecycle)
     - `title: <user-provided title>` (one line)
     - `owner: tb` unless user said otherwise
     - `created: <today's date YYYY-MM-DD>`
     - `last_updated: <today's date YYYY-MM-DD>`
     - `tags: []` (leave empty, user fills)
     - `related: []` (leave empty)
   - Body sections from template stay as-is. The user fills only `## Original Idea` (1–3 sentences); the routines fill the rest.

4. **Append first Lifecycle line** to the doc:
   ```
   YYYY-MM-DD — research/idea_ — created from template
   ```

5. **Update `docs/research/_INDEX.md`:**
   - Find the `### idea` section under `## research/`.
   - Replace `_(none)_` if it's the only item, or append a new line:
     ```
     - [idea_<slug>.md](research/idea_<slug>.md) — <title> (YYYY-MM-DD)
     ```
   - Don't reorder existing lines.

6. **Report (3 lines max):**
   - Path created: `docs/research/research/idea_<slug>.md`
   - `_INDEX.md` updated: 1 line added under `### idea`
   - Next step suggestion: "Write the raw idea into `## Original Idea`, then `git mv` to `drafting_<slug>.md` — the research-draft routine works it up from there."

## Don'ts

- Don't auto-commit. The user reviews the scaffolded file first.
- Don't promote state (idea → drafting etc.) — that's an explicit user action.
- Don't invent the slug if it's missing — ask.
- Don't write code-level details into the scaffolded research doc — that lives in the eventual implementation. The research doc captures **why** and **options**, not **how-to**.
