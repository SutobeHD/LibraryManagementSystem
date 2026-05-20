# Research-first rule for features

**Feature touches ≥ 2 modules or has multiple plausible approaches → start in `docs/research/`.** Don't dive into code first.

## Workflow

1. Check `docs/research/_INDEX.md` (or run `/pipeline`) — in-flight doc for this area? Read end-to-end before suggesting anything.
2. No existing doc → `/research-new <slug>` scaffolds `docs/research/research/idea_<slug>.md` from `_TEMPLATE.md`. User fills `## Original Idea` (1–3 sentences) — the only manual writing the pipeline needs.
3. State chain (each `git mv` = + `## Lifecycle` line + `_INDEX.md` update):
   `idea_` → `drafting_` → `ideagate_`⛔A → `exploring_` → `midgate_`⛔B → `evaluated_` → `draftplan_` → `review_` → `plangate_`⛔C → `accepted_` → `inprogress_` → `archived/implemented_`
4. **Skip pipeline for:** one-off bug fixes, single-file refactors, plain questions, doc edits.

Full stage/prefix cheat-sheet + routines + branch flow: `docs/research/README.md`.

## The 4 gates — user sign-off points

Routines advance **work-states** autonomously. Three gate-states + the PR gate need the user:

| Gate | State | User action |
|---|---|---|
| A | `ideagate_` | `/gate-pass` (→ `exploring_`) or `/gate-reject` (→ `drafting_`) — confirm idea + Research Plan |
| B | `midgate_` | `/gate-pass` / `/gate-reject` — review mid-research checkpoint |
| C | `plangate_` | `/gate-pass` (→ `accepted_`) or `/gate-reject` (→ `rework_`) — approve plan + Task Queue |
| D | open PR | review the `routine/*` PR, order the rebase/merge to `main` |

**Only the user passes a gate.** A routine reaching a `*gate_` state stops there. **Never** auto-advance a `*gate_` doc. **Never** merge or rebase a routine branch to `main` — that is GATE D, user-ordered.

This replaces the old "no unilateral promotion" rule: the gates ARE the sign-off. Verification agents gate the work-states in between (idea-check, research-check, plan-review).

## Routines write code — bounded

The old "routines are docs-only" rule is relaxed. `research-implement` may write code, but **only**:
- in `inprogress_` state,
- on `routine/<slug>-task-<N>` branches — **never `main`**,
- Task Queue items approved at GATE C — no freelancing,
- 1 task = 1 small PR; CI + a review-agent gate it; the user merges (GATE D).

`research-draft` / `research-explore` / `research-plan` stay docs-only. No routine touches `app/`, `frontend/`, `src-tauri/`, `tests/` outside an `inprogress_` doc's approved Task Queue.

## Writing style for research docs — Caveman+

Research docs are **persistent files**, not user output. Apply Caveman+ per `working-style.md`:

- Bullets > prose. Fragments OK. Drop articles/filler/hedges.
- Respect per-section word caps in `_TEMPLATE.md` (Problem ≤60 words, Findings entries ≤80 words, Recommendation ≤80 words).
- No "we considered", "it appears that", "in order to", "it should be noted", "after investigation". Direct subject + verb + object.
- No section meta-prose ("This section captures..."). The heading carries the meaning.

**Bad** (real example, 38 words for one fact):
> After investigation, it appears that the AcoustID free tier has a rate limit of 3 requests per second which would require us to consider batching strategies for the bulk lookup endpoint.

**Good** (8 words, same info):
> AcoustID 3 req/s. Bulk endpoint preferred. Batch by 100.

The plain instruction line under each `_TEMPLATE.md` heading (e.g. "≤60 words. What / why...") is overwritten by real content. Stage/gate markers (`> ↓ Stage…`, `> ⛔ GATE…`) are structural — keep them. `## Original Idea` is verbatim — never edit it.

## Graduation: `implemented_` lands

Archive as `implemented_` = rename + doc-syncer hits. **Before** the move:

1. `docs/architecture.md` — data flows reflect shipped behavior
2. `docs/FILE_MAP.md` (or `/regen-maps`) — new files
3. `docs/{backend,frontend,rust}-index.md` — new endpoints / symbols
4. `CHANGELOG.md` if user-visible (`/changelog-bump`)

`## Decision / Outcome` checkbox list in the doc enforces the audit trail.
