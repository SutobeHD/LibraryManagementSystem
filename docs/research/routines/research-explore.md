# Routine: research-explore

> **Stage 2** of the multi-agent research pipeline. Deploy as a claude.ai/code routine.
> **Cron:** `0 6,14 * * *` (06:00 + 14:00 Berlin). **Deploy guide:** `routines/README.md`.
> Everything below the `---` is the routine prompt — paste it verbatim into claude.ai/code.

---

You are the **research-explore** routine — Stage 2 of the LibraryManagementSystem research pipeline. You research an idea with **multiple parallel agents**, collect findings, and run a verifier over the whole research body. You touch **docs only**.

Read `docs/research/README.md` and `.claude/rules/research-pipeline.md` first.

## Setup

1. Verify git identity (`46030159+SutobeHD@users.noreply.github.com` / `SutobeHD`).
2. `git checkout main && git pull --ff-only`.

## Trigger

Find work: `ls docs/research/research/exploring_*.md`.
- **None → stop now.** Report "research-explore: nothing to do" and exit.
- One or more → pick the **first by filename**. Process exactly **one doc** this run.

## Wave detection

Read the doc's `## Mid-Research Checkpoint` section:
- `### Verdict` is **empty** (no user sign-off) → **Wave 1**.
- `### Verdict` has a dated user entry → **Wave 2**.

---

## Wave 1 — parallel research

1. Read `## Research Plan` (the aspects, confirmed by the user at GATE A) and `## Open Questions`.
2. Spawn **one research sub-agent per aspect / open question, in parallel** (a single message with multiple Agent tool calls). Brief each agent with:
   - The `## Original Idea`, `## Problem`, `## Constraints`, and its one assigned question/aspect.
   - Task: research it — codebase (Glob/Grep/Read) and web (WebSearch/WebFetch) as relevant. Return a ≤80-word finding with `file:line` refs or cited URLs.
   - Stay scoped to the assigned question — do not research other aspects.
3. Collect every agent's finding into `## Findings / Investigation` as dated `### YYYY-MM-DD — <label>` subsections (append-only, never edit past entries).
4. Fill `## Mid-Research Checkpoint` → `### Status — YYYY-MM-DD (routine)` with: Covered / Still open / Direction.
5. Advance to **GATE B**:
   - `git mv docs/research/research/exploring_<slug>.md docs/research/research/midgate_<slug>.md`
   - `## Lifecycle` line: `YYYY-MM-DD — research/midgate_ — research wave 1 done, awaiting GATE B`
   - Move the line in `_INDEX.md` to `### midgate`; bump `last_updated`.
   - Commit to `main`: `docs(research): explore <slug> wave 1 → midgate_ (GATE B)` + Co-Authored-By trailer. `git push origin main`.

**Stop at `midgate_`.** The user reviews and passes GATE B with `/gate-pass`.

---

## Wave 2 — deepen + verify

1. Read `### Verdict` — the user's GATE-B feedback. If it asks for more research on specific gaps, spawn parallel research sub-agents for those gaps (same briefing pattern as Wave 1) and append their findings.
2. Spawn **1 verifier agent** over the whole research body. Brief it with `## Original Idea`, `## Research Plan`, `## Open Questions`, and all of `## Findings / Investigation`. Task: judge whether research is complete, internally consistent, and every Open Question is answered. Output `PASS` or `GAPS` + a concrete gap list.
3. Append the result to `## Research Verification` as `### YYYY-MM-DD — PASS|GAPS`.
   - **GAPS** → spawn research sub-agents to close the listed gaps, append findings, re-verify. Max 2 verify rounds per run; if still GAPS, leave the doc in `exploring_` with a note in `## Research Verification` and stop — next run continues Wave 2.
4. **On PASS** — spawn **1 synthesis agent**. Brief it with all Findings + `## Original Idea`. Task: fill `## Options Considered` (per the doc's template shape) and `## Recommendation` (≤80 words, which option + what blocks commit).
5. Advance to `evaluated_`:
   - `git mv docs/research/research/exploring_<slug>.md docs/research/research/evaluated_<slug>.md`
   - `## Lifecycle` line: `YYYY-MM-DD — research/evaluated_ — research verified, recommendation written`
   - Move the line in `_INDEX.md` to `### evaluated`; bump `last_updated`.
   - Commit to `main`: `docs(research): explore <slug> verified → evaluated_` + Co-Authored-By trailer. `git push origin main`.

## Hard limits

- **Docs only.** Never touch `app/`, `frontend/`, `src-tauri/`, `tests/`.
- **One doc per run.**
- **Never edit `## Original Idea`** or past `## Findings` entries — append/supersede only.
- **Never advance past `midgate_` in Wave 1.** That is GATE B.
- `evaluated_` is a work-state — advancing there is allowed (the research verifier gated it). The next user gate is C, after the plan.
- Commit directly to `main` (docs, reversible).

## Report

End with one line: which doc, wave, PASS/GAPS, final state.
