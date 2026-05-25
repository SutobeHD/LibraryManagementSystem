---
slug: quality-settings-lossless-tagging
title: Quality settings + unique lossless-track tagging
owner: tb
created: 2026-05-22
last_updated: 2026-05-25
tags: [downloader, library, quality, schema]
related: [library-quality-upgrade-finder, downloader-unified-multi-source]
---

# Quality settings + unique lossless-track tagging

> **Caveman style.** Fragments, bullets. Drop articles/filler/hedges. No prose paragraphs. Respect per-section caps below.
> State = folder + filename prefix (not frontmatter). Lifecycle = audit trail. See `../README.md`.
> Routines advance this doc by state. 4 user gates: A `ideagate_`, B `midgate_`, C `plangate_`, D PR-merge.

## Lifecycle

- 2026-05-22 — `research/idea_` — created from template
- 2026-05-22 — `research/drafting_` — state move (manual); ready for the `research-draft` routine to fill Problem → Research Plan
- 2026-05-25 — `research/ideagate_` — `research-draft` routine filled Problem → Research Plan + Idea Verification (PASS); awaits GATE A

## Original Idea (verbatim — never edit)

In den Download-Einstellungen sollte man Quality-Präferenzen festlegen können
(z. B. „Lossless bevorzugen", „Maximum Hi-Res"). Lossless-Tracks sollten in
der Library eindeutig markiert werden — über einen Tag, ein Icon oder ein
DB-Feld — sodass man auf einen Blick sieht, was echtes Lossless ist und was
lossy.

---

> ↓ Stage 1 — `drafting_`. `research-draft` fills Problem → Research Plan. Agent 2 fills Idea Verification.

## Problem

Downloader fetches mixed quality (MP3 / FLAC / Hi-Res) — no user preference. Library shows no lossless marker — user can't see at a glance what's real lossless vs lossy / transcoded. Cost: wrong-quality downloads waste storage; manual per-track quality audit; can't filter library by quality tier.

## Goals / Non-goals

**Goals**
- Settings: quality-preference ladder (e.g. Lossless-preferred → MP3-fallback; Max-Hi-Res mode)
- Downloader honors preference when picking source variant
- Library marker (DB field + UI badge) — lossless vs lossy vs hi-res
- Marker computed from probed file, not source-stated quality
- Reuse `quality_engine` + integrate with `accepted_downloader-unified-multi-source.md`

**Non-goals**
- Transcode-detection deep-dive (lives in `exploring_library-quality-upgrade-finder.md`)
- Audio-fingerprint quality classifier (separate research)
- Re-encoding lossy → lossless (impossible)
- Auto-replacing existing library tracks (quality-upgrade-finder territory)

## Constraints

External facts bounding solution (rate limits, data shape, perf budget, legal, capacity). Cite source.

- Source-stated quality often lies — MP3-source transcoded → FLAC label common; ground truth needs probe (`exploring_library-quality-upgrade-finder.md`)
- `master.db` schema change → migration + `_db_write_lock` per `coding-rules.md`
- Reuse mandatory: `quality_engine` + unified-downloader source-variant resolver (per `accepted_downloader-unified-multi-source.md`)
- Hi-Res threshold: typically > 16-bit and/or > 44.1 kHz; no universal definition (community: > 16/48 minimum)
- SQLite WAL on `master.db` — pattern reference: `app/usb_one_library.py`
- ffprobe already shipped in PATH (per `CLAUDE.md`) — cheap probe primitive available

## Open Questions

Numbered. Each resolvable (yes/no or X vs Y), not philosophy. Each becomes a parallel research agent in Stage 2.

1. DB field shape: enum (`lossless` / `lossy` / `hires` / `unknown`) vs bool-pair (`is_lossless`, `is_hires`)?
2. Marker computed at download time vs library-scan time vs both?
3. Quality-preference ladder: per-source override or global only?
4. UI marker: TrackList column + badge vs filter-pill only? Where exactly?
5. Reuse `quality-upgrade-finder` probe logic or independent probe path?

## Research Plan

Required by `ideagate_` (GATE A). ≤80 words. Which aspects Stage 2 researches in parallel — one bullet per agent. User confirms this list at GATE A.

- Agent 1: Integration with `quality_engine` + downloader source-variant resolver + settings-side preference-ladder shape
- Agent 2: DB schema — enum vs bool-pair; migration cost; reuse of `quality-upgrade-finder` fields if any
- Agent 3: UI placement — TrackList column, badge component, settings panel; pattern-match existing conventions
- Agent 4: Probe-vs-trust — cheapest reliable probe (ffprobe metadata vs spectral); reuse `quality-upgrade-finder` logic?

## Idea Verification

Stage 1 Agent 2. Dated entries, append-only. PASS / FAIL + ≤40-word reason (checked vs `## Original Idea`).

### 2026-05-25 — PASS
- Draft covers both pillars of Original Idea: (a) quality-preference settings ("Lossless bevorzugen", "Maximum Hi-Res") and (b) unique lossless library marker (Tag/Icon/DB-Feld). No scope creep, no missing pillars.

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
