---
slug: safe-download-sources-survey
title: Survey of safe / legit download tooling on GitHub
owner: tb
created: 2026-05-22
last_updated: 2026-05-25
tags: [downloader, survey, oss, integration]
related: [downloader-unified-multi-source, external-track-match-unified-module, download-gate-assistant]
---

# Survey of safe / legit download tooling on GitHub

> **Caveman style.** Fragments, bullets. Drop articles/filler/hedges. No prose paragraphs. Respect per-section caps below.
> State = folder + filename prefix (not frontmatter). Lifecycle = audit trail. See `../README.md`.
> Routines advance this doc by state. 4 user gates: A `ideagate_`, B `midgate_`, C `plangate_`, D PR-merge.

## Lifecycle

- 2026-05-22 — `research/idea_` — created from template
- 2026-05-22 — `research/drafting_` — state move (manual); ready for the `research-draft` routine to fill Problem → Research Plan
- 2026-05-25 — `research/ideagate_` — `research-draft` routine filled Problem → Research Plan + Idea Verification (PASS); awaits GATE A

## Original Idea (verbatim — never edit)

GitHub-Survey nach legitimen / „safe" Download-Tools und -Quellen — was an
Open-Source-Tooling existiert (streamrip-Klasse, Bandcamp-/Beatport-Downloader,
multi-source) und welche Architektur-Ansätze (account-based vs. mirror-scraping
vs. buy-to-own) als Inspiration / Integrationspfad für unseren Downloader in
Frage kommen.

---

> ↓ Stage 1 — `drafting_`. `research-draft` fills Problem → Research Plan. Agent 2 fills Idea Verification.

## Problem

Downloader narrow in source coverage. Unknown what OSS prior art exists (streamrip-class, Bandcamp, Beatport collection-downloaders, multi-source orchestrators) or which architectures (account-based / mirror-scrape / buy-to-own) ship safely. Cost: reinventing solved patterns; missing legit integration paths; building on shaky legal / safety ground.

## Goals / Non-goals

**Goals**
- Catalog active OSS download tooling on GitHub (≥1 release in last 12 mo OR commit < 6 mo old)
- Per-tool: source coverage, auth model, license, safety / legal posture, last update
- Architecture taxonomy: account-based vs mirror-scrape vs buy-to-own vs API-keyed
- Integration shortlist: Python library? CLI shell-out? logic port? inspiration only?
- Feed source-priority list of `accepted_downloader-unified-multi-source.md`

**Non-goals**
- Building new sources in this doc (separate implementation docs per source)
- Legal opinion (flag risk only — don't adjudicate)
- Re-evaluating already-accepted unified-downloader architecture
- Closed-source tools (scope is OSS prior art)

## Constraints

External facts bounding solution (rate limits, data shape, perf budget, legal, capacity). Cite source.

- Project license — must check root `LICENSE` for vendoring compat (MIT/Apache → GPL code only shellable-out, not vendor-able)
- Python sidecar — Python-native libs preferred; Rust/Go OK via subprocess; pure-JS browser-extensions unusable
- Local-first — tools requiring own backend server out of scope
- "Safe" = clear ToS posture + no telemetry + user pays for content downloaded
- 2026 maintenance reality: many Qobuz/Tidal forks abandoned post-API changes — verify activity not just popularity
- Existing modules to reuse: `external_track_match` (matching), `require_session` (auth), `quality_engine` (per accepted downloader doc)

## Open Questions

Numbered. Each resolvable (yes/no or X vs Y), not philosophy. Each becomes a parallel research agent in Stage 2.

1. streamrip vs orpheusdl vs custom: which is most maintained 2026 + best integration shape?
2. Bandcamp: official-API tools (bandcamp-dl class) vs scraping — which still works 2026?
3. Beatport: does a legit collection-downloader (buy-to-own) exist or only scraping?
4. Multi-source orchestrators: are there "downloader-of-downloaders" patterns worth copying?
5. Account auth: how do existing tools store credentials (keyring / env / encrypted file)?
6. License compat: which tools' code can vendor/port (MIT/Apache) vs only inspire (GPL)?

## Research Plan

Required by `ideagate_` (GATE A). ≤80 words. Which aspects Stage 2 researches in parallel — one bullet per agent. User confirms this list at GATE A.

- Agent 1: streamrip-class (Qobuz/Tidal/Deezer multi-source) — top 5 active forks 2026, feature matrix, license, integration shape
- Agent 2: Bandcamp ecosystem — official-API tools, buy-to-own flow, what still works 2026
- Agent 3: Beatport / DJ-store tooling — collection-downloaders, buy-to-own legality, what exists
- Agent 4: Multi-source orchestrator patterns + credential storage — plugin registry, source-priority resolution
- Agent 5: License + safety audit — GPL-compat, telemetry, ToS posture per candidate

## Idea Verification

Stage 1 Agent 2. Dated entries, append-only. PASS / FAIL + ≤40-word reason (checked vs `## Original Idea`).

### 2026-05-25 — PASS
- Draft covers Original Idea: GitHub survey of legit / "safe" tooling (streamrip-class, Bandcamp / Beatport, multi-source) AND architecture inspirations (account / mirror-scraping / buy-to-own) feeding the unified downloader. No scope creep.

---

> ⛔ GATE A — user `/gate-pass` (→ `exploring_`) or `/gate-reject` (→ `drafting_`).
> ↓ Stage 2 — `exploring_`. `research-explore` runs parallel agents, fills Findings.

## Findings / Investigation

Dated subsections, append-only. ≤80 words each. Never edit past entries — supersede.

### YYYY-MM-DD — <label>
- …

## Mid-Research Checkpoint

GATE B. `research-explore` fills Status after wave 1. User fills Verdict via `/gate-pass` or `/gate-reject`.

### Status — YYYY-MM-DD (routine)
- Covered: …
- Still open: …
- Direction: …

### Verdict — YYYY-MM-DD (user)
- _(empty until GATE B)_

---

> ⛔ GATE B — user `/gate-pass` (→ `exploring_` wave 2) or `/gate-reject` (→ `exploring_` + feedback).
> ↓ Stage 2 wave 2 — `research-explore` deepens research, runs the research verifier.

## Research Verification

Stage 2 wave-2 verifier over the whole research body. ≤80 words. PASS → `evaluated_`; gaps → more Findings.

### YYYY-MM-DD — <PASS|GAPS>
- …

## Options Considered

Required by `evaluated_`. Per option: sketch ≤3 bullets, pros, cons, S/M/L/XL, risk.

### Option A — <name>
- Sketch:
- Pros:
- Cons:
- Effort:
- Risk:

### Option B — <name>
- Sketch:
- Pros:
- Cons:
- Effort:
- Risk:

## Recommendation

Required by `evaluated_`. ≤80 words. Which option + what blocks commit.

---

> ↓ Stage 3 — `implement/draftplan_`. `research-plan` fills Implementation Plan + Task Queue. Agent B fills Review.

## Implementation Plan

Required from `implement/draftplan_`. Concrete enough that someone else executes without re-deriving.

### Scope
- **In:** …
- **Out:** …

### Step-by-step
1. …

### Files touched
- …

### Testing
- …

### Risks & rollback
- …

## Task Queue

<!--
Small, individually-committable implementation tasks. Written by research-plan (Stage 3),
approved by the user at GATE C. research-implement works ONE task per branch:
routine/<slug>-task-<N>. 1 task = 1 feature = 1 PR. Tick - [x] when the PR is merged.
Keep tasks small — a task too big to review in one PR must be split.
-->

- [ ] <task — small, single-purpose, independently testable>

## Review

Filled at `review_` by `research-plan` Agent B. Unchecked box or rework reason → `rework_`.

- [ ] Plan addresses all goals
- [ ] Plan matches `## Original Idea` — no scope-creep
- [ ] Open questions answered or deferred
- [ ] Task Queue items are small + independently committable
- [ ] Risk mitigations defined
- [ ] Rollback path clear
- [ ] Affected docs identified (`architecture.md`, `FILE_MAP.md`, indexes, `CHANGELOG.md`)

**Rework reasons:**
- …

---

> ⛔ GATE C — user `/gate-pass` (→ `accepted_`) or `/gate-reject` (→ `rework_`).
> ↓ Stage 4 — `inprogress_`. `research-implement` builds each Task Queue item on a `routine/*` branch.

## PR Log

Stage 4. One row per task PR. `research-implement` appends; user notes the merge (GATE D).

| Task | Branch | PR | CI | Review | Merged |
|---|---|---|---|---|---|
| … | `routine/<slug>-task-N` | #… | pass/fail | pass/fail | YYYY-MM-DD |

## Implementation Log

Filled during `inprogress_`. Dated entries. What built / surprised / changed-from-plan.

### YYYY-MM-DD
- …

---

## Decision / Outcome

Required by `archived/*`.

**Result**: implemented | superseded | abandoned
**Why**: …
**Rejected alternatives:**
- …

**Code references**: PR #…, commits …, files …

**Docs updated** (required for `implemented_`):
- [ ] `docs/architecture.md`
- [ ] `docs/FILE_MAP.md`
- [ ] `docs/backend-index.md` (if backend changed)
- [ ] `docs/frontend-index.md` (if frontend changed)
- [ ] `docs/rust-index.md` (if Rust/Tauri changed)
- [ ] `CHANGELOG.md` (if user-visible)

## Links

- Code: <file:line or PR>
- External docs: <url>
- Related research: <slugs>
