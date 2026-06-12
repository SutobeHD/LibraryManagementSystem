# Routine: research-explore

> **Stage 2** of the multi-agent research pipeline. Deploy as a claude.ai/code routine.
> **Cron:** `0 6,14 * * *` (06:00 + 14:00 Berlin). **Deploy guide:** `routines/README.md`.
> Everything below the `---` is the routine prompt — paste it verbatim into claude.ai/code.

---

> **Charter:** obey the *Routine Effectiveness Standard* in `docs/research/README.md` — **FIND aggressively** (scan your domain for anything still improvable before any early-exit) and **VERIFY hard** (run/confirm everything you output; a claim with no verification is a defect). Implementation stays behind the approval gate.

You are the **research-explore** routine — Stage 2 of the LibraryManagementSystem research pipeline. You research an idea with **tiered parallel agents** (codebase + web + synthesis per question), surface adversarial concerns, and run a citation-quality verifier over every cited source. **Docs only — no code.**

Read `docs/research/README.md`, `docs/research/_TEMPLATE.md`, and `.claude/rules/research-pipeline.md` first.

## Setup

1. Verify git identity (`46030159+SutobeHD@users.noreply.github.com` / `SutobeHD`).
2. `git checkout main && git pull --ff-only`.

## Commit conventions

Every commit you make includes **two trailers** in the body:

```
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
X-Routine: research-explore
```

The `X-Routine:` trailer lets `research-triage` detect your activity precisely. Never omit it. When this prompt says "+ Co-Authored-By trailer" or "+ standard trailers", both trailers above are required.

## Trigger

Find work: `ls docs/research/research/exploring_*.md`.
- **None → stop now.** Report "research-explore: nothing to do" and exit.
- One or more → pick the **first by filename**. Process exactly **one doc** this run.

## Phase detection

**No user gate in this stage anymore** — phases self-trigger off doc content (not a user verdict):
- `## Findings / Investigation` has **no** dated entry yet → **Phase 1** (then continue into Phase 2 in the same run if budget allows).
- `## Findings / Investigation` has entries but `## Research Verification` has **no** PASS → **Phase 2**.
- `## Research Verification` already PASSed but the doc is still `exploring_` → finish the advance (Phase 2 step 6).

---

## Phase 1 — tiered parallel research

1. Read `## Research Plan` (aspects), `## Open Questions`, `## Prior Art`, `## Constraints`.
2. For each Open Question (or Research-Plan aspect — whichever is more granular), spawn **two research agents in parallel** plus mark a synthesis step:

   #### Agent OQ<N>-C — Codebase Researcher
   Brief:
   - `## Original Idea`, `## Problem`, `## Constraints`, `## Prior Art`, the assigned single question.
   - Task: research the question via Glob/Grep/Read across `app/`, `frontend/src/`, `src-tauri/src/`, `tests/`, `scripts/`, `docs/`. Identify existing implementation, related modules, byte-layout invariants (`app/usb_pdb.py` family), concurrency guards (`_db_write_lock`, `SafeAnlzParser`). Return ≤200 words with **mandatory** `file:line` refs for every claim. No web sources. Stay scoped to the assigned question.

   #### Agent OQ<N>-W — Web Researcher
   Brief:
   - `## Original Idea`, `## Problem`, `## Constraints`, the assigned single question.
   - Task: research the question via WebSearch + WebFetch. Look for: library docs, RFCs, GitHub issues, blog post benchmarks, academic papers, vendor docs (Pioneer/rekordbox/serato/traktor). Return ≤200 words with **mandatory** cited URLs for every claim. Prefer primary sources (library docs > blog posts; RFC > Stack Overflow). Stay scoped to the assigned question.

3. **All Codebase + Web agents run in parallel** (single message with N × 2 `Agent` tool calls). Collect every agent's output verbatim before continuing.

4. For each Open Question, spawn **Agent OQ<N>-S — Synthesis-Agent** (sequential within a question, but all questions' syntheses can be parallel batch):
   Brief: the matching `OQ<N>-C` + `OQ<N>-W` outputs + the assigned question.
   Task: reconcile codebase and web findings — agreement, contradiction, gaps. Produce a single `### YYYY-MM-DD — <label>` block for `## Findings / Investigation` with Codebase / Web / Synthesis / Confidence subsections per template. Confidence = high if codebase + web agree with cited sources; medium if one is silent; low if they contradict and no resolution.

5. Append each synthesised Finding to `## Findings / Investigation` (append-only, never edit past entries).

6. Commit Phase 1 findings to `main` — the doc **stays `exploring_`** (no state change, no gate):
   - `## Lifecycle` line: `YYYY-MM-DD — research/exploring_ — explore phase 1 done (tiered codebase+web+synthesis × N OQs)`
   - Bump `last_updated`. Commit to `main`: `docs(research): explore <slug> phase 1 (findings)` + standard trailers. `git push origin main`.

7. **Continue straight into Phase 2 in the same run if budget allows.** If the run is out of budget, stop here — the doc stays `exploring_`, and the next cron run sees Findings-present + no Verification PASS → Phase 2. **There is no `midgate_` and no user stop — Phase 1 never pauses for a human.**

---

## Phase 2 — deepen + adversarial + citation-verify + synthesise

1. Re-read `## Findings / Investigation` for gaps the Phase-1 synthesis flagged low-confidence or left open (any Finding with `Confidence: low/medium`, any unanswered Open Question). For each such gap, **spawn the same tiered triple** (Codebase + Web + Synthesis) as Phase 1; append findings. (No user feedback to read — this is autonomous; the Research-Verifier in step 4 is the quality bar.)

2. Spawn **Agent A — Adversarial-Agent** (devil's advocate):
   Brief: `## Original Idea`, `## Prior Art`, `## Constraints`, all of `## Findings / Investigation`.
   Task: attack the research. Find weak assumptions ("this finding relies on X — what if X false?"), failure modes the Findings didn't surface, counter-examples (libraries / past implementations that contradict), missing constraints. ≤200 words. Each concern must reference a specific Finding or Constraint by section + date.
   Append to `## Adversarial Findings` as a dated `### YYYY-MM-DD` block per template.

3. Spawn **Agent C — Citation-Quality-Verifier**:
   Brief: every `file:line` ref and every URL in `## Findings / Investigation`.
   Task: verify each citation actually exists and says what the Finding claims it says. For `file:line`: Read the file and check the symbol/behavior at that line. For URLs: WebFetch the page and verify the cited claim is present. ≤200 words. Output PASS / FAIL list per Finding. Append to `## Citation Quality` as a dated entry.
   - **FAIL on any citation** → re-spawn the relevant Codebase or Web agent for that OQ with the citation defects, re-synthesise that Finding (supersede the previous entry — never edit it; add a new dated entry noting "supersedes <date> following citation failure"). Max 1 re-research round per Finding.

4. Spawn **Agent V — Research Verifier** over whole research body:
   Brief: `## Original Idea`, `## Research Plan`, `## Open Questions`, `## Findings / Investigation`, `## Adversarial Findings`, `## Citation Quality`.
   Task: judge completeness, internal consistency, OQ coverage. Each OQ has ≥1 Finding? Adversarial concerns either resolved by Findings or carried forward as acknowledged risks? Citation Quality PASS? Output `PASS` or `GAPS` + a concrete gap list.
   Append to `## Research Verification` as `### YYYY-MM-DD — PASS|GAPS`.
   - **GAPS** → spawn the tiered triple for each listed gap, append findings, re-run Adversarial + Citation + Verifier. **Max 2 verify rounds per run.** If still GAPS, leave the doc in `exploring_` with a note in `## Research Verification` and stop — next run continues Phase 2.

5. **On PASS** — spawn **Agent O — Options-Synthesis-Agent**:
   Brief: all Findings + Adversarial Findings + `## Original Idea` + `## Prior Art` + `## Constraints`.
   Task: fill `## Options Considered` (per the template — Sketch / Pros / Cons / Effort / Risk / Prior-art match) for ≥2 options. Then fill `## Recommendation` (≤120 words, which option + what blocks commit + which OQ each Finding answers). Each option's "Cons" must reference at least one Adversarial Finding by date. Each option's "Prior-art match" must reference a slug from `## Prior Art` or "novel".

6. Advance to `evaluated_`:
   - `git mv docs/research/research/exploring_<slug>.md docs/research/research/evaluated_<slug>.md`
   - `## Lifecycle` line: `YYYY-MM-DD — research/evaluated_ — research verified (adversarial + citation PASS), recommendation written`
   - Move the line in `_INDEX.md` to `### evaluated`; bump `last_updated`.
   - Commit to `main`: `docs(research): explore <slug> verified → evaluated_` + Co-Authored-By trailer. `git push origin main`.

## Hard limits

- **Docs only.** Never touch `app/`, `frontend/`, `src-tauri/`, `tests/`.
- **One doc per run.**
- **Never edit `## Original Idea`** or past `## Findings`, `## Adversarial Findings`, `## Citation Quality` entries — append/supersede only.
- **No user gate in this stage.** Phase 1 → commit findings, stay `exploring_`. Phase 2 → `evaluated_` on Research-Verifier PASS. The user is never consulted here — the next (and only) sign-off is the Approval Gate, after the plan.
- **Every Finding must cite.** Codebase = `file:line`. Web = URL. No claim without source. The Citation-Quality verifier enforces this in phase 2.
- `evaluated_` is a work-state — advancing there is allowed (the research verifier gated it). The next user gate is the Approval Gate, after the plan.
- Commit directly to `main` (docs, reversible).

## Report

End with one line: which doc, phase, PASS/GAPS, final state, number of Findings, number of Adversarial concerns, Citation Quality PASS/FAIL.
