---
slug: waveform-overhaul
title: Waveform Overhaul — display types, multi-band rendering, color presets
owner: tb
created: 2026-05-20
last_updated: 2026-05-20
tags: []
related: []
---

# Waveform Overhaul — display types, multi-band rendering, color presets

> **Caveman style.** Fragments, bullets. Drop articles/filler/hedges. No prose paragraphs. Respect per-section caps below.
> State = folder + filename prefix (not frontmatter). Lifecycle = audit trail. See `../README.md`.
> Routines advance this doc by state. 4 user gates: A `ideagate_`, B `midgate_`, C `plangate_`, D PR-merge.

## Lifecycle

- 2026-05-20 — `research/idea_` — created from template
- 2026-05-20 — `research/drafting_` — Stage 1: idea worked up — Problem → Research Plan
- 2026-05-20 — `research/ideagate_` — drafted + idea-verified, awaiting GATE A

## Original Idea (verbatim — never edit)

<!--
Written ONCE by the user. 1–3 sentences, raw. NEVER edited after — not by routines, not by the user.
Every verifier (Stage 1 idea-check, Stage 2 research-check, Stage 3 plan-review) checks its work
against this block. It is the anchor against scope-creep and misreading.
-->

More waveform display types — distinct rendering styles/kinds, not just recolors — each offering several fixed, consistent color palettes to pick from. Support configurable frequency-band counts beyond today's 3-band split (e.g. 6-band) with user-adjustable color thresholds, but always ship sensible presets as defaults. Inspiration: deadmau5's in-development DJ software (https://www.youtube.com/watch?v=A2lwxhFPPDI).

---

> ↓ Stage 1 — `drafting_`. `research-draft` fills Problem → Research Plan. Agent 2 fills Idea Verification.

## Problem

One render style only (wavesurfer.js bar) + 4 color modes (blue / rgb / 3band / custom). Band count hardcoded 3; split thresholds hardcoded 200/2500 Hz; some band colors hardcoded despite a settings UI. No named palette presets. DJs want richer, finer waveform reading. Competitors (Rekordbox, Serato, deadmau5's tool) ship more styles + bands.

## Goals / Non-goals

**Goals**
- Multiple waveform render styles/types — selectable, not just recolors.
- Per style: several fixed, named color palettes — consistent set.
- Configurable band count beyond 3 (e.g. 6-band).
- User-adjustable per-band frequency thresholds.
- Every option always has a sensible preset/default — never unconfigured.

**Non-goals**
- Realtime / audio-reactive live visuals — offline track waveform only.
- Changing CDJ export waveform formats (pwv2/3/5/6/7 — Pioneer byte-locked).
- Backend analysis-pipeline rearchitecture beyond band-split generalization.
- Beat-grid / cue / phrase overlays — separate features.

## Constraints

- wavesurfer.js **7.12.6**. Current multi-band = one slave WaveSurfer instance + one filtered-audio Blob per band (`frontend/src/components/waveform/useMultibandLayers.js`). N bands → N instances + N Blobs → memory + CPU scale with N. `frontend/package.json:26`.
- Backend band split: 4th-order Butterworth, **hardcoded 200 / 2500 Hz**, RMS @ 150 fps. `app/analysis_engine.py:879-915`.
- API `/api/audio/waveform` returns `rgb_low/mid/high` float arrays + `pwv7`. `app/main.py:663`.
- CDJ export formats `pwv2/3/5/6/7` byte-locked to Pioneer hardware — 3-band fixed there. Extra bands are **frontend-display-only**, cannot feed CDJ export. `app/analysis_engine.py`.
- Existing settings: `waveform_visual_mode`, `waveform_color_low/mid/high`. `frontend/src/components/settings/SettingsAppearance.jsx:15-54`.
- Band colors partly hardcoded despite the settings UI: `useMultibandLayers.js:54-56`, `frontend/src/components/shared/WaveformMiniCanvas.jsx:32-46`.
- 4 render contexts share renderers — main editor, overview strip, ranking view, track-table thumbnail. New styles must work (or degrade) across all.

## Open Questions

1. Which waveform render styles are feasible with wavesurfer.js 7.12.6 — custom-renderer API vs. replacing it with a custom canvas renderer? Enumerate feasible styles (bars, filled outline, mirror, dots/spectrum, stereo-split) + integration cost each.
2. Can the band split generalize 3 → N (e.g. 6) end-to-end — backend Butterworth bank + frontend render — without breaking `pwv7`? What is the sane max N (perf + perceptual)?
3. Frequency thresholds — expose as user-editable? What default band-edge sets for 3 / 4 / 6 / N bands are perceptually sound (octave / mel / Rekordbox-like)?
4. Color-palette model — how to structure named, fixed, consistent palettes per render style with an always-present default? Data schema + which presets to ship.
5. How do competitors (Rekordbox, Serato, Traktor, deadmau5's tool) present waveform render styles + multi-band visualization — what is the table-stakes set?

## Research Plan

- Agent 1 — Render styles: wavesurfer 7.12.6 custom-renderer vs custom-canvas; feasible style list + integration cost.
- Agent 2 — N-band feasibility: backend 3→N Butterworth split, frontend N-band render, sane max N, perf, `pwv7` impact.
- Agent 3 — Frequency thresholds: perceptually-sound default band-edge sets (3/4/6/N); editable or fixed.
- Agent 4 — Palette/preset model: data schema, named palettes per style, always-a-default rule, preset ship-list.
- Agent 5 — Competitor UX: Rekordbox / Serato / Traktor / deadmau5 waveform render styles + band visualization.

## Idea Verification

### 2026-05-20 — PASS
- Draft faithfully serves all idea elements: render styles (not recolors), fixed per-style palettes, N-band beyond 3, user-adjustable thresholds, always-present presets, deadmau5 inspiration. Non-goals fence scope; Open Questions resolvable; Research Plan covers them 1:1.

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
