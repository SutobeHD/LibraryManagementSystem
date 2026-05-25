---
slug: download-gate-assistant
title: In-app download-gate assistant (Hypeddit etc.)
owner: tb
created: 2026-05-22
last_updated: 2026-05-25
tags: [downloader, ux, webview, credentials]
related: [downloader-unified-multi-source, safe-download-sources-survey]
---

# In-app download-gate assistant (Hypeddit etc.)

> **Caveman style.** Fragments, bullets. Drop articles/filler/hedges. No prose paragraphs. Respect per-section caps below.
> State = folder + filename prefix (not frontmatter). Lifecycle = audit trail. See `../README.md`.
> Routines advance this doc by state. 4 user gates: A `ideagate_`, B `midgate_`, C `plangate_`, D PR-merge.

## Lifecycle

- 2026-05-22 — `research/idea_` — created from template
- 2026-05-22 — `research/drafting_` — state move (manual); ready for the `research-draft` routine to fill Problem → Research Plan
- 2026-05-25 — `research/ideagate_` — `research-draft` routine filled Problem → Research Plan + Idea Verification (PASS); awaits GATE A

## Original Idea (verbatim — never edit)

Möglichkeit, in den Einstellungen vorab Accounts für Download-Gate-Dienste
(Hypeddit etc.) zu hinterlegen. Beim Download eines gegateten Tracks soll das
Gate direkt in der App geöffnet werden (eingebettetes Webview), sodass der
User den Gate-Durchlauf bequem an einer Stelle durchklicken kann — ohne viel
Werbung und ohne ständiges Neu-Einloggen.

---

> ↓ Stage 1 — `drafting_`. `research-draft` fills Problem → Research Plan. Agent 2 fills Idea Verification.

## Problem

Free-promo tracks gated behind Hypeddit / Toneden etc. — user visits each gate per track, clicks through ad flow, re-logs-in often. Cost: 30-60 s per gated track; context-switch out of app; some gates demand email / social-follow even after past completion.

## Goals / Non-goals

**Goals**
- Settings: pre-configure gate-service accounts (Hypeddit, Toneden, …)
- On gated download: open gate in embedded webview, auto-logged-in via stored session
- Pass-through to actual download once gate completes (user clicks through manually)
- Encrypted credential storage at rest (OS keyring / DPAPI)
- Cookie jar persistence per gate-service (avoid re-login each visit)
- Integration with `accepted_downloader-unified-multi-source.md` gated-track resolution

**Non-goals**
- Bypassing gate (illegitimate — artists set gate intentionally)
- Auto-clicking through gate ("ad-skip" — ToS-violating + adversarial)
- Headless / scripted gate completion (same risk as bypass)
- Building gate-service ourselves

## Constraints

External facts bounding solution (rate limits, data shape, perf budget, legal, capacity). Cite source.

- Tauri 2 webview (Wry / WebView2 on Windows) — supports embedded URLs; per-window cookie isolation possible
- Credentials → encrypted store: `keyring` Python lib (system keyring), Rust `keyring` crate, or DPAPI on Windows direct
- `require_session` bearer auth (per `coding-rules.md`) — any credential-fetch endpoint behind it; never log creds (not at INFO / DEBUG / redacted)
- Each gate-service ToS must allow embedded webview login + manual click-through (not scripted)
- Per `accepted_downloader-unified-multi-source.md` — gated-track resolution routes through this assistant; integration point in source-resolver
- Browser-dev mode (`npm run dev:full`) — no Tauri webview; gate-assistant degrades to "open in default browser" fallback

## Open Questions

Numbered. Each resolvable (yes/no or X vs Y), not philosophy. Each becomes a parallel research agent in Stage 2.

1. Tauri 2 webview: can embed external URL with isolated cookie jar per service?
2. Credential store: `keyring` Python lib vs Rust `keyring` crate vs Windows DPAPI direct?
3. Hypeddit / Toneden ToS: do they allow embedded-webview login (not just browser-only)?
4. Gate detection: source resolver returns gate-URL, or downloader probes link first?
5. MVP gate-service list — Hypeddit only, or also Toneden / others?
6. Existing OSS tools in this space (cross-link `drafting_safe-download-sources-survey.md` findings)?

## Research Plan

Required by `ideagate_` (GATE A). ≤80 words. Which aspects Stage 2 researches in parallel — one bullet per agent. User confirms this list at GATE A.

- Agent 1: Tauri 2 webview embedding — isolated cookie jars per origin, persistent session, URL injection patterns
- Agent 2: Gate-service inventory + ToS — Hypeddit, Toneden, others; which allow embedded-webview login; MVP shortlist
- Agent 3: Credential store — `keyring` Python lib vs Rust `keyring` crate vs DPAPI; integration with `require_session` bearer model
- Agent 4: Gate detection + downloader integration — where in unified-downloader does gated-track route; UX on first gate

## Idea Verification

Stage 1 Agent 2. Dated entries, append-only. PASS / FAIL + ≤40-word reason (checked vs `## Original Idea`).

### 2026-05-25 — PASS
- Draft covers all three Original-Idea pillars: (a) pre-configured gate-service accounts in Settings, (b) embedded in-app webview on gated download, (c) streamlined click-through without ads + without constant re-login. No scope creep.

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
