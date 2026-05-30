# Research & Implementation Pipeline

Persistent feature lifecycle. Every idea moves: `research/` → `implement/` → `archived/`. **Stage + state = folder + filename prefix**, not frontmatter. File system is single source of truth.

Files are never deleted — closed topics live in `archived/` forever as historical record.

Doc style: **Caveman+** (fragments, bullets, no prose). Per-section **soft** word caps in `_TEMPLATE.md` (recommendations, not hard blocks). Full rule + bad/good example in `.claude/rules/research-pipeline.md`.

**Multi-agent workflow.** **8 remote routines** advance docs autonomously: 5 daily work-state routines move docs forward through the pipeline; 3 cross-cutting routines feed new ideas (`research-spawn`), re-validate shipped features (`research-watchdog`), and detect inter-doc conflicts (`research-cross-linker`). Routines trigger on a doc's **state** — no manual marker needed. Each routine spawns multiple sub-agents in parallel; specialist verifiers gate each stage. The user keeps **4 deliberate sign-off gates** (A/B/C/D). See "Stages", "The 4 Gates", "The 8 routines" below.

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

## The 8 routines

Remote routines (claude.ai/code, cron in Berlin time). Each reads one trigger condition, spawns multiple sub-agents in parallel, early-exits if there is no work. Prompts versioned in `routines/` — deploy per `routines/README.md`.

### Daily work-state routines — advance docs through the pipeline

| Routine | Cron | Reads | Sub-agents | Output |
|---|---|---|---|---|
| `research-draft` | 05:00 | `drafting_` | Scout + Prior-Art + Risk-Surface (parallel) → Worker → Idea-Verifier | pass → `ideagate_` · mismatch → rework (max 3×, then `parked_`) |
| `research-explore` | 06:00 + 14:00 | `exploring_` | Tiered per-OQ: Codebase-Researcher + Web-Researcher + Synthesis (all parallel) · Wave 2: Adversarial + Citation-Quality + Research-Verifier + Options-Synthesis | wave 1 → `midgate_` · wave 2 → `evaluated_` |
| `research-plan` | 13:00 | `evaluated_`, `rework_` | Planner → parallel Threat-Modeller + Migration-Path + Performance-Budget → Test-Plan-Agent → Planner (Task Queue) → Plan-Reviewer | pass → `plangate_` · gaps → `rework_` |
| `research-implement` | 03:00 + 15:00 | `accepted_`, `inprogress_` | per task: Approach-Probe + Selector → Code-Agent → parallel Standard-Review + Security-Review + Test-Coverage-Review → Doc-Sync | 1 task → 1 `routine/*` branch → 1 PR |
| `research-triage` | 07:30 | all (read-only) | — | GitHub Issue "Pipeline Digest": gates, ready PRs, routine activity, trends, loop-guards, blockers |

### Cross-cutting routines — idea generation, re-validation, conflict detection

| Routine | Cron | Reads | Sub-agents | Output |
|---|---|---|---|---|
| `research-spawn` | Sundays 05:00 | TODO/FIXME, CHANGELOG, GH issues, MAP smells, dep majors (read-only) | 5 parallel scouts + Synthesiser | GitHub Issue "Idea Backlog": prioritised idea proposals. User authors `## Original Idea`. |
| `research-watchdog` | 1st of month 04:00 | 5 oldest unchecked `archived/implemented_` | 5 parallel Probe-Agents | `## Lifecycle` line on each (OK / WARN / FLAG) + follow-up proposals into Idea Backlog issue |
| `research-cross-linker` | Tuesdays 04:30 | all active docs in `research/` + `implement/` | per-doc Extractors + Overlap-Analyser | `related:` frontmatter + `## Cross-links (auto-managed)` block on overlapping docs; CONFLICT notification on Pipeline Digest |

Wave 1 vs wave 2: `research-explore` checks the doc — a `## Mid-Research Checkpoint` block with user sign-off present → wave 2, else wave 1.

---

## Multi-agent mechanics

A routine is a Claude Code session with the `Agent` tool. "Multiple instances" = the routine spawns sub-agents (parallel where independent). Each work stage now runs a tighter chain of specialists rather than one monolithic agent — the doc grows section-by-section with each verifier gating the next.

- **Stage 1** — Scout (codebase) + Prior-Art (archived/active) + Risk-Surface (constraints + dependencies) run **parallel and read-only**, then feed into the Worker that writes `## Prior Art` / `## Problem` / `## Goals / Non-goals` / `## Constraints` / `## Dependencies` / `## Open Questions` / `## Research Plan`. Idea-Verifier checks intent fidelity, prior-art handling, and OQ tractability against `## Original Idea`. Mismatch → worker reruns (max 3, then `parked_`).
- **Stage 2** — Per Open Question: parallel **Codebase-Researcher** + **Web-Researcher** + a **Synthesis** agent that reconciles them into one `## Findings / Investigation` block with citations mandatory on both axes. Wave 2 adds an **Adversarial-Agent** (devil's advocate against the findings) and a **Citation-Quality-Verifier** (probes every `file:line` ref + URL — failure triggers re-research). Then **Research-Verifier** over the whole body; PASS triggers an **Options-Synthesis-Agent** writing `## Options Considered` + `## Recommendation` with each option's "Cons" referencing a concrete Adversarial Finding.
- **Stage 3** — **Planner** writes `## Implementation Plan` + `## API / UX Surface` + `## Telemetry`. Parallel specialists fill **`## Threat Model`** (STRIDE-light), **`## Migration Path`** (DB schema / file layout / IPC contracts), **`## Performance Budget`** (numeric budgets + worst-case scenarios). A **Test-Plan-Agent** writes `## Test Plan` covering every threat + step + perf row + OQ + migration. **Planner** then writes `## Task Queue` referencing Steps + Test IDs. **Plan-Reviewer** works an expanded `## Review` checklist (Threat-coverage, Migration rollback, Perf worst-case, Test-Plan completeness, Task Queue PR-sized, Dependencies audited).
- **Stage 4** — Per Task Queue item: **Approach-Probe** drafts 2-3 mini-sketches (≤30 LoC each); **Selector** picks one with reasoning. **Code-Agent** implements only the selected approach + Test-Plan rows. Three parallel reviewers — **Standard** (coding-rules.md compliance), **Security** (Threat-Model coverage + universal patterns), **Test-Coverage** (every Test-Plan row exists and runs). **Doc-Sync-Agent** proposes FILE_MAP / index updates on the branch. PR body lists every reviewer outcome.

**Idea fidelity.** `## Original Idea (verbatim — never edit)` is written once by the user and never changed. Every verifier at every stage checks its work against it — no scope-creep, no misread.

**Cross-cutting mechanics.** `research-spawn` runs 5 parallel scouts looking for idea-signals (TODO/FIXME clusters, CHANGELOG follow-up phrases, GH issues, MAP code smells, dep major versions) → Synthesiser dedupes against existing docs → Idea Backlog issue. `research-watchdog` parallel-probes 5 oldest archived/implemented_ docs against today's codebase + dep CHANGELOGs + external GitHub signals → OK / WARN / FLAG + Idea-Backlog followup proposals. `research-cross-linker` extracts per-doc footprints (files / symbols / externals) and an Overlap-Analyser classifies pairs as CONFLICT / OVERLAP / NEIGHBOUR — `related:` frontmatter + `## Cross-links` block written per doc; CONFLICTs surface on Pipeline Digest.

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

## Conflict resolution — when cross-linker flags CONFLICT

`research-cross-linker` (Tuesdays 04:30) detects when **two or more active docs at stage ≥ `draftplan` target the same file(s)**. Two plans landing on `main` near-simultaneously will collide. The CONFLICT lands as a `## Cross-links` section on both docs and a comment on the `Pipeline Digest` issue.

You have **3 resolution options**:

### 1. Sequence — let one finish, then the other

If the two docs touch the same file but are otherwise independent: order them so the second waits for the first.

1. Pick the higher-priority / smaller-scope doc to run first.
2. `git mv` the other to `parked_` (if still in research/) or `blocked_` (if in implement/). Routines skip both.
3. Append a `## Lifecycle` line: `YYYY-MM-DD — <stage>/<paused-state>_ — sequenced behind <other-slug>, awaiting its merge`.
4. Update `_INDEX.md`.
5. When the first ships (`archived/implemented_`), `git mv` the second back to its prior work state + Lifecycle line + `_INDEX.md`. Routines resume.

### 2. Merge — combine into a single plan

If the two docs really cover the same feature with different angles: merge them.

1. Pick the more developed doc as the "host". Archive the other as `superseded_<slug>_<date>.md`.
2. In the superseded doc, fill `## Decision / Outcome`: `Result: superseded`, `Why: merged into <host-slug>`, code refs = none.
3. In the host doc, fold the superseded doc's `## Findings`, `## Adversarial Findings`, `## Options Considered` into the host as dated subsections — never edit past entries, append.
4. Update `_INDEX.md` for both moves.
5. Re-run `research-cross-linker` (manual trigger or wait for Tuesday) — should now show no CONFLICT.

### 3. Pause — kick the can to the user

If you don't have time to decide right now: `git mv` both to `parked_` / `blocked_`. They sit idle until you decide. `research-triage` will flag them as stalled after 7 days.

**Don't** let routines work two `inprogress_` docs that target the same file simultaneously — you'll get duplicate refactors, merge conflicts on `main`, and review-agent confusion. Resolve every CONFLICT before either reaches GATE D.

---

## Graduation: `implemented_` lands

Rename + doc updates. **Before** the `git mv` → `archived/implemented_`:

1. `docs/architecture.md` — data flows reflect shipped behavior
2. `docs/FILE_MAP.md` — new files have one-line entries
3. `docs/{backend,frontend,rust}-index.md` — new endpoints/symbols
4. `CHANGELOG.md` if user-visible

`## Decision / Outcome` section in doc has checkbox list — audit trail explicit.

After `implemented_`, shipped behavior lives in `architecture.md`; research doc remains as historical "why".
