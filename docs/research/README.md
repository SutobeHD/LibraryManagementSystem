# Research & Implementation Pipeline

Persistent feature lifecycle. Every idea moves: `research/` → `implement/` → `archived/`. **Stage + state = folder + filename prefix**, not frontmatter. File system is single source of truth.

Files are never deleted — closed topics live in `archived/` forever as historical record.

Doc style: **Caveman+** (fragments, bullets, no prose). Per-section word caps in `_TEMPLATE.md`. Full rule + bad/good example in `.claude/rules/research-pipeline.md`.

**Multi-agent workflow.** Five remote routines advance docs autonomously. Routines trigger on a doc's **state** — no manual marker needed. Multiple agent instances research in parallel. Verification agents gate each stage. The user keeps **4 deliberate sign-off gates** (A/B/C/D). See "Stages", "The 4 Gates", "The 5 routines" below.

---

## Layout

```
docs/research/
├── README.md                   ← this file
├── _TEMPLATE.md                ← copy for new topic
├── _INDEX.md                   ← live dashboard
│
├── routines/                   ← versioned routine prompts (deploy to claude.ai/code)
│   ├── README.md
│   ├── research-draft.md
│   ├── research-explore.md
│   ├── research-plan.md
│   ├── research-implement.md
│   └── research-triage.md
│
├── research/                   ← Stage 1+2: draft, gate, explore, evaluate
│   ├── idea_<slug>.md
│   ├── drafting_<slug>.md
│   ├── ideagate_<slug>.md
│   ├── exploring_<slug>.md
│   ├── midgate_<slug>.md
│   ├── evaluated_<slug>.md
│   └── parked_<slug>.md
│
├── implement/                  ← Stage 3+4: plan, gate, build
│   ├── draftplan_<slug>.md
│   ├── review_<slug>.md
│   ├── plangate_<slug>.md
│   ├── rework_<slug>.md
│   ├── accepted_<slug>.md
│   ├── inprogress_<slug>.md
│   └── blocked_<slug>.md
│
└── archived/                   ← terminal
    ├── implemented_<slug>_<YYYY-MM-DD>.md
    ├── superseded_<slug>_<YYYY-MM-DD>.md
    └── abandoned_<slug>_<YYYY-MM-DD>.md
```

Slug stays through entire lifecycle. Only prefix + folder change. Date suffix added when entering `archived/`.

---

## Stages and prefixes

Two state kinds:
- **Work states** — a routine works the doc. Routine does the `git mv` to the next state when done.
- **Gate states** (`*gate_`) — work paused, waiting on the user. **Only the user** advances them (`/gate-pass` or `/gate-reject`).

### research/ — Stage 1 (draft) + Stage 2 (explore)

| Prefix | Kind | Meaning | Next |
|---|---|---|---|
| `idea_` | user | Raw idea. User fills `## Original Idea` (1–3 sentences). | `drafting_` |
| `drafting_` | work | **Stage 1.** `research-draft` works it up + verifies vs original idea. Rework-loop internal. | `ideagate_` |
| `ideagate_` | **gate ⛔** | **GATE A.** Worked-up idea + Research Plan await user OK. | `exploring_` |
| `exploring_` | work | **Stage 2.** `research-explore` runs parallel research agents. | `midgate_` (wave 1) / `evaluated_` (wave 2) |
| `midgate_` | **gate ⛔** | **GATE B.** Mid-research checkpoint awaits user review. | `exploring_` |
| `evaluated_` | work | Research verified, Recommendation written. | `implement/draftplan_` |
| `parked_` | — | Paused, no owner. Routines skip it. | `exploring_` when picked up |

### implement/ — Stage 3 (plan) + Stage 4 (build)

| Prefix | Kind | Meaning | Next |
|---|---|---|---|
| `draftplan_` | work | **Stage 3.** `research-plan` writes Implementation Plan + Task Queue. | `review_` |
| `review_` | work | Plan-verification agent runs. | `plangate_` or `rework_` |
| `plangate_` | **gate ⛔** | **GATE C.** Reviewed plan awaits user approval. | `accepted_` |
| `rework_` | work | Review found gaps. `research-plan` reworks the plan. | `review_` |
| `accepted_` | work | Plan approved, Task Queue active. | `inprogress_` |
| `inprogress_` | work | **Stage 4.** `research-implement` builds tasks on `routine/*` branches, opens PRs. | `archived/implemented_` |
| `blocked_` | — | Paused (external dep, library bug). Routines skip it. | `inprogress_` when unblocked |

### archived/ — terminal

| Prefix | Meaning |
|---|---|
| `implemented_<slug>_<YYYY-MM-DD>` | Shipped. `architecture.md` / `FILE_MAP.md` / `*-index.md` updated. |
| `superseded_<slug>_<YYYY-MM-DD>` | Replaced. Successor in `## Decision / Outcome`. |
| `abandoned_<slug>_<YYYY-MM-DD>` | Dropped. Reason mandatory in `## Decision / Outcome`. |

---

## The 4 Gates

The pipeline runs autonomously between gates. At each gate it pauses on a `*gate_` doc until the user acts. `research-triage` reports open gates daily so none stall silently.

| Gate | State | User confirms | Pass → | Reject → |
|---|---|---|---|---|
| **A** | `ideagate_` | Worked-up idea matches intent + Research Plan is right | `exploring_` | `drafting_` |
| **B** | `midgate_` | Research is heading the right direction | `exploring_` (wave 2) | `exploring_` (with feedback block) |
| **C** | `plangate_` | Implementation Plan + Task Queue approved | `accepted_` | `rework_` |
| **D** | open PR | Branch reviewed + CI green → rebase/merge to `main` | merged | comment / close PR |

GATE A/B/C: user runs `/gate-pass <slug>` or `/gate-reject <slug> "<reason>"`. GATE D: user reviews the PR and orders the rebase/merge — **routines never merge or rebase to `main`**.

---

## The 5 routines

Remote routines (claude.ai/code, cron in Berlin time). Each reads one work state, spawns sub-agents, early-exits if no doc in that state. Prompts versioned in `routines/` — deploy per `routines/README.md`.

| Routine | Cron | Reads | Sub-agents | Output |
|---|---|---|---|---|
| `research-draft` | 05:00 | `drafting_` | Agent 1 (worker) + Agent 2 (idea-verifier) | pass → `ideagate_` · mismatch → rework (max 3×, then `parked_`) |
| `research-explore` | 06:00 + 14:00 | `exploring_` | N parallel research agents (1/Open Question) + verifier in wave 2 | wave 1 → `midgate_` · wave 2 → `evaluated_` |
| `research-plan` | 13:00 | `evaluated_`, `rework_` | Agent A (plan + Task Queue) + Agent B (plan-reviewer) | pass → `plangate_` · gaps → `rework_` |
| `research-implement` | 03:00 + 15:00 | `accepted_`, `inprogress_` | per task: code-agent + review-agent | 1 task → 1 `routine/*` branch → 1 PR |
| `research-triage` | 07:30 | all (read-only) | — | GitHub Issue "Pipeline Digest": docs/state, open gates, ready PRs, blockers |

Wave 1 vs wave 2: `research-explore` checks the doc — a `## Mid-Research Checkpoint` block with user sign-off present → wave 2, else wave 1.

---

## Multi-agent mechanics

A routine is a Claude Code session with the `Agent` tool. "Multiple instances" = the routine spawns sub-agents (parallel where independent).

- **Stage 1** — worker drafts the idea into Problem/Goals/Constraints/Open Questions + a `## Research Plan`; verifier checks it against `## Original Idea`. Mismatch → worker reruns.
- **Stage 2** — one research agent per Open Question, **parallel**. Findings collected into `## Findings / Investigation`. Wave 2 adds one verifier over the whole research body → `## Research Verification`.
- **Stage 3** — plan agent writes `## Implementation Plan` + `## Task Queue`; reviewer agent checks it.
- **Stage 4** — per Task Queue item: code-agent writes code, review-agent verifies it.

**Idea fidelity.** `## Original Idea (verbatim — never edit)` is written once by the user and never changed. Every verifier checks its work against it — no scope-creep, no misread.

---

## Stage 4 — branch / PR / commit flow

Routines may write code — **only** in `inprogress_`, **only** on `routine/*` branches, **only** Task Queue items approved at GATE C.

1. **Task Queue** — small, individually-committable tasks. `research-implement` works only these, no freelancing.
2. **Branch isolation** — each task → `routine/<slug>-task-<N>`. Never `main`.
3. **Small commits** — 1 task = 1 feature = 1 PR. Atomic Conventional Commits (`commit-and-git.md`). Clean error-tracking.
4. **Test on branch** — push branch → `gh pr create` vs `main`. CI (`ci.yml`) runs automatically on PRs: `pytest` + `cargo test` + `npm build` are blocking.
5. **Agent review** — review-agent verifies the task vs the plan spec. CI green **and** review pass → PR "ready".
6. **GATE D** — user reviews ready PRs (triage digest lists them) and orders rebase/merge. Routines never merge/rebase to `main`.
7. **Failure path** — CI red or review fail → task stays unchecked in the queue, branch stays open with a diagnosis note, next run fixes it.

---

## Transitioning between states

Four actions, in order (consistent working tree if interrupted):

1. **`git mv <old> <new>`** — preserves history. (New file not yet tracked → plain `mv` + `git add`.)
2. **Append `## Lifecycle` line:** `YYYY-MM-DD — <stage>/<state>_ — <one-line context>`
3. **Update `_INDEX.md`** — move topic to new state's section.
4. **Bump `last_updated`** in frontmatter (only if content touched too; not for pure rename).

Work state → work state: the routine does this. Gate state → work state: the user does this (`/gate-pass`, `/gate-reject` automate steps 1–3).

### Skipping states OK

Trivial topics: `idea_` → `accepted_` in one sitting if framing+drafting+sign-off happen together. Every skipped stage still gets a Lifecycle line — audit trail stays complete.

### Splits / merges

- **Split** (one research → N features): leaving `evaluated_` → archive source as `superseded_<slug>_<date>.md`, create N new `draftplan_<sub-slug>.md`. Superseded doc lists all children.
- **Merge** (two plans → one): archive both as `superseded_*`, create one new plan, cross-link.

### Pausing a doc

Editing a doc yourself and want routines to leave it alone → `git mv` it to `parked_` (research/) or `blocked_` (implement/). Routines skip both.

---

## Graduation: `implemented_` lands

Rename + doc updates. **Before** the `git mv` → `archived/implemented_`:

1. `docs/architecture.md` — data flows reflect shipped behavior
2. `docs/FILE_MAP.md` — new files have one-line entries
3. `docs/{backend,frontend,rust}-index.md` — new endpoints/symbols
4. `CHANGELOG.md` if user-visible

`## Decision / Outcome` section in doc has checkbox list — audit trail explicit.

After `implemented_`, shipped behavior lives in `architecture.md`; research doc remains as historical "why".
