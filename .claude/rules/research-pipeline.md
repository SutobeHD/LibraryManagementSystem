# Research-first rule for features

**Feature touches ≥ 2 modules or has multiple plausible approaches → start in `docs/research/`.** Don't dive into code first.

## Workflow

1. Check `docs/research/_INDEX.md` (or run `/pipeline`) — in-flight doc for this area? Read end-to-end before suggesting anything. Also check the `Idea Backlog` GitHub Issue — `research-spawn` may have already proposed something.
2. No existing doc → `/research-new <slug>` scaffolds `docs/research/research/idea_<slug>.md` from `_TEMPLATE.md`. User fills `## Original Idea` (1–3 sentences) — the only manual writing the pipeline needs.
3. State chain (each `git mv` = + `## Lifecycle` line + `_INDEX.md` update):
   `idea_` → `drafting_` → `exploring_` → `evaluated_` → `draftplan_` → `review_` → `approvalgate_`⛔ → `accepted_` → `inprogress_` → `archived/implemented_`
   Everything `drafting_` → `review_` runs **autonomously** — verification agents gate each hop, no user stop. The **single** user gate is `approvalgate_` (idea summary + mockup + change list). After `/approve` the build runs autonomously to PRs; you test the `routine/*` branch locally and merge it yourself.
4. **Skip pipeline for:** one-off bug fixes, single-file refactors, plain questions, doc edits.

Full stage/prefix cheat-sheet + 8 routines + branch flow: `docs/research/README.md`.

## The 8 routines — quick map

5 daily work-state routines move docs forward; 3 cross-cutting routines maintain pipeline health.

| Routine | Schedule (Berlin) | Trigger | Touches |
|---|---|---|---|
| `research-draft` | daily 05:00 | `drafting_*.md` exists | docs → `main` |
| `research-explore` | daily 06:00 + 14:00 | `exploring_*.md` exists | docs → `main` |
| `research-plan` | daily 13:00 | `evaluated_*.md` or `rework_*.md` | docs → `main` |
| `research-implement` | daily 03:00 + 15:00 | `accepted_*.md` or `inprogress_*.md` | code on `routine/*` branches + PRs |
| `research-triage` | daily 07:30 | always | `Pipeline Digest` GitHub Issue |
| `research-spawn` | Sundays 04:00 | TODO/FIXME, CHANGELOG, GH issues, etc. | `Idea Backlog` GitHub Issue |
| `research-watchdog` | 1st of month 04:00 | archived/implemented_ unchecked 30+ days | `## Lifecycle` line + `Idea Backlog` follow-ups |
| `research-cross-linker` | Tuesdays 04:30 | active docs with footprint overlap | `related:` frontmatter + `## Cross-links` block |

Every work routine spawns specialist sub-agents (Scout / Prior-Art / Risk-Surface; Codebase + Web + Synthesis per OQ; Threat-Modeller / Migration / Perf-Budget / Test-Plan; Approach-Probe + multi-reviewer). Full per-routine agent chain: `docs/research/README.md` "Multi-agent mechanics".

## The one gate — single user sign-off point

Routines advance **every** work-state autonomously (verification agents gate each hop). The user is asked **once**, at `approvalgate_`, and then again only to merge.

| Gate | State | User action |
|---|---|---|
| **Approval** | `approvalgate_` | `/approve` (→ `accepted_`) or `/reject "<reason>"` (→ `rework_`) — read the `## Approval Summary` (idea in plain words + change list) + `## Mockup`, then yes/no |
| Merge | open PR | land the finished `routine/*` PR — **not a research gate**, just shipping. The user can merge it, or instruct the interactive agent to (`gh pr merge`). Test first when practical. |

**Only the user passes the Approval Gate.** A routine reaching `approvalgate_` stops there. **Never** auto-advance it — that single sign-off is user-only.

**Merging is not user-only.** The interactive agent may merge a finished `routine/*` PR (or any branch) **on the user's instruction** — `gh pr merge` is autonomous for it. What stays forbidden: the **remote routines** (claude.ai/code cron) never merge or rebase to `main` — they only open PRs and stop. Headless self-merge without human-in-the-loop is the line; an interactive merge the user asked for is not.

The earlier idea/mid-research/plan checkpoints (old GATE A/B/C) are gone as user stops — verification agents replace them: Idea-Verifier (drafting), Adversarial + Citation + Research-Verifier (exploring), Plan-Reviewer (review). Everything the user needs to decide is bundled into the Approval Summary + Mockup so the single yes/no is fully informed and **nothing is re-researched after `/approve`**.

## Routines write code — bounded

The old "routines are docs-only" rule is relaxed. `research-implement` may write code, but **only**:
- in `inprogress_` state,
- on `routine/<slug>-task-<N>` branches — **never `main`**,
- Task Queue items approved at the Approval Gate — no freelancing, no new research,
- 1 task = 1 small PR; CI + a review-agent gate it; the user — or the interactive agent on the user's instruction — tests locally + merges. (The remote routine itself never merges.)

`research-draft` / `research-explore` / `research-plan` stay docs-only. No routine touches `app/`, `frontend/`, `src-tauri/`, `tests/` outside an `inprogress_` doc's approved Task Queue.

## Writing style for research docs — Caveman+

Research docs are **persistent files**, not user output. Apply Caveman+ per `working-style.md`:

- Bullets > prose. Fragments OK. Drop articles/filler/hedges.
- Respect per-section **soft** word caps in `_TEMPLATE.md` (Problem ≤60, Findings ≤150 per entry, Approval Summary ≤200, etc. — recommendations, exceedable when topic complexity demands).
- No "we considered", "it appears that", "in order to", "it should be noted", "after investigation". Direct subject + verb + object.
- No section meta-prose ("This section captures..."). The heading carries the meaning.

**Bad** (real example, 38 words for one fact):
> After investigation, it appears that the AcoustID free tier has a rate limit of 3 requests per second which would require us to consider batching strategies for the bulk lookup endpoint.

**Good** (8 words, same info):
> AcoustID 3 req/s. Bulk endpoint preferred. Batch by 100.

The plain instruction line under each `_TEMPLATE.md` heading (e.g. "≤60 words. What / why...") is overwritten by real content. Stage/gate markers (`> ↓ Stage…`, `> ⛔ APPROVAL GATE…`) are structural — keep them. `## Original Idea` is verbatim — never edit it. **Exception:** `## Approval Summary` is **plain user-facing English** (not Caveman) — the user reads it to decide yes/no; full sentences are fine there.

## Graduation: `implemented_` lands

Archive as `implemented_` = rename + doc-syncer hits. **Before** the move:

1. `docs/architecture.md` — data flows reflect shipped behavior
2. `docs/FILE_MAP.md` (or `/regen-maps`) — new files
3. `docs/{backend,frontend,rust}-index.md` — new endpoints / symbols
4. `CHANGELOG.md` if user-visible (`/changelog-bump`)

`## Decision / Outcome` checkbox list in the doc enforces the audit trail.
