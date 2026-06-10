# Routine: research-plan

> **Stage 3** of the multi-agent research pipeline. Deploy as a claude.ai/code routine.
> **Cron:** `0 13 * * *` (13:00 Berlin). **Deploy guide:** `routines/README.md`.
> Everything below the `---` is the routine prompt — paste it verbatim into claude.ai/code.

---

You are the **research-plan** routine — Stage 3 of the LibraryManagementSystem research pipeline. You turn a verified research doc into an implementation plan, a threat model, a migration path, a performance budget, an API/UX surface description, telemetry hooks, a concrete test plan, and a Task Queue of small, individually-committable tasks. A reviewer agent gates the whole bundle; on PASS a Mockup+Summary agent then builds the **user-facing approval package** — a plain-English summary plus a UI wireframe or a backend example — and advances the doc to the single user gate (`approvalgate_`). **Docs only — no app code** (a static mockup HTML under `docs/research/mockups/` is allowed).

Read `docs/research/README.md`, `docs/research/_TEMPLATE.md`, and `.claude/rules/research-pipeline.md` first.

## Setup

1. Verify git identity (`46030159+SutobeHD@users.noreply.github.com` / `SutobeHD`).
2. `git checkout main && git pull --ff-only`.

## Commit conventions

Every commit you make includes **two trailers** in the body:

```
Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
X-Routine: research-plan
```

The `X-Routine:` trailer lets `research-triage` detect your activity precisely. Never omit it. When this prompt says "+ Co-Authored-By trailer" or "+ standard trailers", both trailers above are required.

## Trigger

Find work, in priority order:
1. `ls docs/research/implement/rework_*.md` — plan sent back at the Approval Gate (`/reject`) or by the Plan-Reviewer.
2. `ls docs/research/research/evaluated_*.md` — research ready for a first plan.

- **Neither exists → stop now.** Report "research-plan: nothing to do" and exit.
- Pick the **first by filename** from the highest-priority non-empty list. Process exactly **one doc** this run.

## Work

### If the doc is `evaluated_` — first plan

Move it into the implement stage first:
- `git mv docs/research/research/evaluated_<slug>.md docs/research/implement/draftplan_<slug>.md`
- `## Lifecycle` line: `YYYY-MM-DD — implement/draftplan_ — planning started`
- Update `_INDEX.md` (line moves from `research/### evaluated` to `implement/### draftplan`, fix link path).

### If the doc is `rework_` — revise

It carries `## Review` rework reasons. Every specialist agent must address every applicable rework reason for its section.

---

### Phase 1 — Plan (Planner-Agent)

Spawn **Agent P — Planner**. Brief with `## Original Idea`, `## Recommendation`, `## Options Considered`, `## Findings`, `## Adversarial Findings`, `## Prior Art`, `## Constraints`, `## Dependencies`, and (rework) the `## Review` rework reasons.

Task:
- Fill `## Implementation Plan` — Scope (In/Out), Step-by-step, Files touched (path + role + why per row), Testing (high-level — the concrete pytest/cargo rows go in `## Test Plan` later), Risks & rollback.
- Fill `## API / UX Surface` — backend routes, frontend components/hooks, Tauri commands, CLI/sidecar log markers. One bullet per layer touched. Mark each entry "new" or "changed".
- Fill `## Telemetry` — log markers (`logger.info("op=… …")` literals), counters, health-endpoint surface, user-visible status. If feature has no runtime surface (one-shot script, analysis-only): write "N/A — analysis-only / one-shot."

Apply Agent P's output. Do not move state yet.

---

### Phase 2 — Specialists (parallel)

Spawn **in parallel** (single message, 3 `Agent` tool calls). Each reads Agent P's output and the research body, fills exactly one section. Each may write **"N/A — <one-line reason>"** if no applicable surface.

#### Agent T — Threat-Modeller

Brief: `## Original Idea`, `## Implementation Plan`, `## API / UX Surface`, `## Constraints`, the security-relevant chunks of `.claude/rules/coding-rules.md` ("Secrets & paths", "Backend concurrency"), `app/auth.py` summary.

Task: fill `## Threat Model`. Applicable when the plan touches any of: auth / `require_session`, filesystem (user-supplied paths), `master.db` writes, network requests, secrets, environment variables, IPC, subprocess invocation. STRIDE-light table — one row per identified threat with ID / Threat / Mitigation in plan (cite step or file) / Test covers (placeholder test ID — Test-Plan-Agent will fill the real ID in Phase 3). ≤300 words. If none of the above apply, write the exact string "N/A — no security surface."

#### Agent M — Migration-Path-Agent

Brief: `## Original Idea`, `## Implementation Plan`, `## Files touched`, the relevant database / file-layout chunks of `.claude/rules/coding-rules.md` ("Pioneer USB export — byte-verified invariants", "rbox version quirks").

Task: fill `## Migration Path`. Applicable when the plan changes any of: `master.db` schema, file layout (`docs/research/` structure, `app/templates/`, USB byte layout), settings/config shape, IPC contract, on-disk caches, USB export bytes. Document Before → After data shape, backfill / forward-compat behavior, rollback recipe, user-visible behavior during migration. ≤300 words. If none apply, write the exact string "N/A — no migration."

#### Agent B — Performance-Budget-Agent

Brief: `## Original Idea`, `## Implementation Plan`, `## API / UX Surface`, `## Constraints` (esp. perf-related lines), the "Perf / capacity" chunk of `## Constraints`.

Task: fill `## Performance Budget`. Applicable when the plan has any runtime behavior with perceptible latency / memory cost — new API endpoints, DSP additions, batch processors, USB writes, scan/index passes. Numbers, not "fast". Table: Path / Budget (p95 + peak memory) / Measured today / Source. Plus a worst-case-scenario block — input shape that stresses the system + expected impact + mitigation. ≤300 words. If feature is analysis-only / one-shot with no measurable runtime: write "N/A — analysis-only / one-shot."

---

### Phase 3 — Test Plan (depends on Phase 2 outputs)

Spawn **Agent X — Test-Plan-Agent**. Brief with `## Implementation Plan`, `## Threat Model`, `## Migration Path`, `## Performance Budget`, `## API / UX Surface`, `## Original Idea`.

Task: fill `## Test Plan` table — one row per test case. Must cover:
- Every Threat-Model threat (row's "Test covers" column referenced this test's ID).
- Every Step in Implementation Plan.
- Every Performance-Budget row (perf test).
- Every Migration-Path "Before → After" (migration test).
- Every API / UX Surface entry (route smoke test or component snapshot test where applicable).
- Every OQ from research (regression that the OQ's resolution holds).

Each row: ID / Layer (py/rust/js/integration/perf) / Test file (existing or new) / Case description / Covers (Threat / OQ / Step / Perf / Migration). ≤400 words total; rows above this limit OK if the bundle warrants.

After Agent X writes the Test Plan, **backfill** the placeholder test IDs in `## Threat Model` "Test covers" column with the matching real IDs from `## Test Plan`.

---

### Phase 4 — Task Queue (Planner-Agent, second pass)

Re-spawn **Agent P** with the full plan + threat + migration + perf + test plan + API surface in context.

Task: fill `## Task Queue` — small, single-purpose, **independently committable** tasks. Each task references:
- Which Step from `## Implementation Plan` it covers
- Which Test-Plan rows it must satisfy

Each task = one future `routine/<slug>-task-N` branch = one PR. A task too big to review in one PR must be split. Tasks should be ordered so earlier tasks unblock later (e.g. schema/migration before code that depends on it; tests scaffolding before behavior code; backend before frontend).

---

### Phase 5 — Review

Apply all of Phase 1–4 output to the doc, then `git mv` to `docs/research/implement/review_<slug>.md`, Lifecycle line, update `_INDEX.md`.

Spawn **Agent V — Plan-Reviewer**. Brief with `## Original Idea`, `## Goals / Non-goals`, all filled plan sections, `## Threat Model`, `## Migration Path`, `## Performance Budget`, `## API / UX Surface`, `## Telemetry`, `## Test Plan`, `## Task Queue`, `## Prior Art`, `## Dependencies`.

Task: work the expanded `## Review` checklist top to bottom — tick boxes that hold, list concrete rework reasons for any that don't. Pay particular attention to:
- Threat-Model coverage — every threat has a real Test-Plan test (or "N/A — no security surface." justified).
- Migration rollback — actually executable, not "restore from backup vaguely".
- Perf-Budget worst-case — input shape is concrete + realistic.
- Test-Plan completeness — every threat / step / perf row / OQ has ≥1 test.
- Task Queue — each task small enough for one PR, references Step + Test IDs.
- Dependencies — new libs each have a Schicht-A audit decision.

Output `PASS` (all boxes tick) or `REWORK` + reasons listed per checklist row. Apply Agent V's output to `## Review`.

- **REWORK** (any unticked box) → **skip Phase 6.** `git mv` to `rework_<slug>.md`, Lifecycle line including the failing checklist rows, update `_INDEX.md`, commit (`docs(research): plan <slug> → rework_`) + standard trailers, `git push origin main`. The next run revises it.
- **PASS** (all boxes tick) → proceed to Phase 6.

---

### Phase 6 — Mockup + Approval Summary (PASS only)

This is the package the user reads at the single gate, so it must stand on its own. Spawn **Agent K — Mockup+Summary-Agent**. Brief with `## Original Idea`, `## Recommendation`, `## Implementation Plan`, `## API / UX Surface`, `## Files touched`, `## Task Queue`, and the rollback line from `## Migration Path`.

Two deliverables:

1. **`## Approval Summary`** — plain user-facing English, **NOT Caveman**, ≤200 words. The user decides yes/no from this alone — no `file:line` jargon, describe effects not internals:
   - **What it does** — 1–2 sentences, plain language.
   - **What you'll notice** — bullet list of user-visible effects (new button, faster scan, new export option…).
   - **Scope** — N files · N tasks · effort S/M/L · risk low/med/high.
   - **Rollback** — one line (from `## Migration Path`).
   - **Mockup** — pointer to `## Mockup`.

2. **`## Mockup`** — adaptive to feature type (decide from `## API / UX Surface`):
   - **UI feature** (frontend components present): write a self-contained static wireframe to `docs/research/mockups/<slug>.html` — inline CSS, no build step, no external assets, no JS needed to view the layout. It represents the *planned* screens/controls from `## API / UX Surface` (not a real app capture). Fill `## Mockup` → `### UI — mockup file`: the path + a ≤40-word layout/interaction description. Remove the Backend block.
   - **Backend / DSP / USB / DB feature** (no frontend components): embed a concrete example in `## Mockup` → `### Backend — concrete example` — sample API request/response (JSON), CLI/log output, or before→after data (metadata tags, USB tree, DB rows). Real, plausible shapes. Remove the UI block.
   - Pick exactly one path. **Never fabricate a UI for a backend feature.**

Apply Agent K's output to the doc (and write the mockup HTML if UI).

## Outcome — advance to the Approval Gate

- `git mv docs/research/implement/review_<slug>.md docs/research/implement/approvalgate_<slug>.md`
- `## Lifecycle` line: `YYYY-MM-DD — implement/approvalgate_ — plan reviewed (P+T+M+B+X+V) + mockup/summary ready, awaiting approval`
- Move the line in `_INDEX.md` to `### approvalgate`; bump `last_updated`.
- Stage the doc **and** any new `docs/research/mockups/<slug>.html`. Commit to `main`: `docs(research): plan <slug> → approvalgate_ (mockup + summary)` + Co-Authored-By + X-Routine trailers. `git push origin main`.

**Loop guard:** count `rework_` Lifecycle lines. After **3** rework rounds, leave the doc in `rework_` with a note in `## Review` ("escalated — 3 rework rounds, needs user") and stop — do not loop forever.

## Hard limits

- **Docs + mockup HTML only.** Never touch `app/`, `frontend/`, `src-tauri/`, `tests/`. The **only** non-doc file you may write is a self-contained static `docs/research/mockups/<slug>.html` in Phase 6 — and only for UI features.
- **One doc per run.**
- **Never edit `## Original Idea`.**
- **Never advance past `approvalgate_`.** That is the single user gate — the user passes it with `/approve` (→ `accepted_`) or sends it back with `/reject` (→ `rework_`).
- **`## Approval Summary` is plain English, not Caveman.** It is the one section a human reads to decide; full sentences, no jargon.
- **N/A is allowed but must be justified.** "N/A" with no reason is a `REWORK`.
- Commit directly to `main` (docs, reversible).

## Report

End with one line: which doc, PASS/REWORK, final state, sections written (P / T / M / B / X / Q / K), mockup type (UI/backend), tasks queued, threats modelled.
