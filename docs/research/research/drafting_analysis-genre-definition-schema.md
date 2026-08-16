---
slug: analysis-genre-definition-schema
title: Declarative genre/style definitions + rule-based auto-detection from track files
owner: tb
created: 2026-08-16
last_updated: 2026-08-16
tags: [analysis, genre, taxonomy, classification, metadata]
related: []
supersedes: []
superseded_by: []
---

# Declarative genre/style definitions + rule-based auto-detection from track files

> **Caveman+ style.** Fragments, bullets. Drop articles/filler/hedges. No prose paragraphs.
> Word caps are **soft** — recommendations, not hard blocks. Exceed when topic complexity demands; routines may flag excess length but never truncate facts.
> State = folder + filename prefix (not frontmatter). Lifecycle = audit trail. See `../README.md`.
> Routines advance this doc **autonomously** by state. **One** user gate: `approvalgate_` — read `## Approval Summary` + `## Mockup`, then `/approve` or `/reject`. After approval you test the finished branch locally and merge it yourself.
> Section ownership: each `> ↓ Stage X — <agent>: …` marker names the agent that fills the section. Don't write into a section before its stage.

## Lifecycle

- 2026-08-16 — `research/idea_` — created from template
- 2026-08-16 — `research/drafting_` — Stage 1 pre-filled by interactive agent (Prior Art, Problem, Goals, Constraints, Dependencies, 11 OQs, Research Plan); Idea-Verifier pass pending → `research-draft`

## Original Idea (verbatim — never edit)

<!--
Written ONCE by the user. 1–3 sentences, raw. NEVER edited after — not by routines, not by the user.
Every verifier (Stage 1 idea-check, Stage 2 research-check, Stage 3 plan-review, Stage 4 doc-sync) checks
its work against this block. It is the anchor against scope-creep and misreading.
-->

ich möchte Genres und ähnliches so definieren das man Algorithmen schreiben kann diese zu erkennen in track dateien

---

> ↓ Stage 1 — `drafting_`. `research-draft` fills Problem → Research Plan via 4 agents (Scout, Prior-Art, Risk-Surface, Worker). Verifier fills Idea Verification.

## Prior Art

- **Shipped (code, no research doc):** `hint_genre()` `app/analysis_engine.py:2035` — hardcoded if/elif over `(bpm, brightness, texture)` → 10 fixed labels, no confidence, no subgenres, untunable; result persisted as `genre_hint`. `detect_mood()` `:1964` — same shape for mood: 6 labels + 5 spectral scalars.
- **Active research:** [accepted_recommender-rules-baseline](../implement/accepted_recommender-rules-baseline.md) — dual-track genre decision (Rekordbox `Genre` = user truth locally, `genre_hint` for SC candidates); this doc changes what `genre_hint` is worth. [accepted_recommender-similar-tracks](../implement/accepted_recommender-similar-tracks.md) — planned 46-dim feature vector (MFCC, chroma, bandwidth, flatness, tempo_variability), extraction **not yet shipped** → share ONE extraction pass, don't decode twice. [inprogress_recommender-taste-llm-audio](../implement/inprogress_recommender-taste-llm-audio.md) — consumes same scalars. [inprogress_analysis-underground-mainstream-classifier](../implement/inprogress_analysis-underground-mainstream-classifier.md) — derived-label precedent (sidecar store + migrate framework, `app/popularity_engine.py`); orthogonal axis, reusable store pattern.
- **Superseded / abandoned:** none.
- **External precedent:** Rekordbox / Serato / Traktor carry genre as free-text ID3 tag only — no audio-side detection. Beatport / Discogs taxonomies are editorial, not feature-derived. Essentia ships pretrained genre models (Discogs-EffNet, MusiCNN) — Stage 2 evaluates; `essentia==2.1b6.dev1110` already pinned (`requirements.txt:48`, optional import).

## Problem

Genre in library = free-text ID3 / Rekordbox field: missing, inconsistent, or wrong on large parts of collection. Only audio-side detector = 10-branch if/elif (`hint_genre`), no confidence, no subgenres, not user-editable, accuracy never measured. DJ-relevant styles (peak-time techno vs melodic house) unreachable. Cost of not doing: manual per-track tagging, weak input for recommender + smart playlists + USB export.

## Goals / Non-goals

**Goals**
- Definition format for genres **and adjacent attributes** (style, mood, energy, era, vocal/instrumental) — data, not code
- Detector evaluates definitions vs per-track features → label(s) + confidence + **which rule fired** (explainable)
- User adds/edits definitions without code change; invalid definition fails safe (skip + log, never crash analysis)
- Measured accuracy vs ground truth + regression test in repo (repo rule: no claim without measurement — `docs/ANALYSIS_HANDOVER.md` §0)
- Hierarchy (parent genre → subgenre) + multi-label output

**Non-goals**
- Overwriting user `Genre` in `master.db` / ID3 without explicit user action
- Cloud / API genre lookup (local-first)
- Duplicating recommender similarity work — this feeds it
- Deciding rules-vs-ML now — Stage 2 decides on measured evidence

## Constraints

- **Feature inventory today** (`accepted_recommender-similar-tracks.md:74`, re-verify Stage 2): persisted = `bpm`, `bpm_raw`, `key`/`camelot`/`key_id`/`key_confidence`, `lufs`, `replay_gain`, `peak`, `stereo{}`, `mood{brightness,warmth,texture,spectral_centroid,spectral_rolloff}`, `genre_hint`, `grid_confidence` ≈ 12–15 scalars. NOT persisted: MFCC/chroma aggregates, `spectral_bandwidth`, `spectral_flatness`, `tempo_variability`, any rhythm-pattern descriptor.
- **Perf:** existing `detect_mood` librosa pass ≈ 0.15 s/track; MFCC + chroma_cqt + bandwidth + flatness ≈ +0.3–0.5 s/track on already-decoded `y` (`accepted_recommender-similar-tracks.md:75`). Full analysis today 15–30 s/track.
- **Cache:** `ANALYSIS_VERSION = 3` (`app/analysis_cache.py:32`) — new persisted features force a bump → full library re-analysis. Budget that migration.
- **DB:** Rekordbox `Genre` = user truth. Any `master.db` write acquires `_db_write_lock` (`app/database.py`); `/api/genres` (`app/main.py:886`) reads master.db genres only. Derived-label sidecar-DB precedent: `app/popularity_engine.py`, `app/db_taste.py`, `app/variant_schema.py`.
- **USB export:** PDB genre table `0x01` byte layout (`app/usb_pdb.py`) — writing detected genres into an export changes rows the CDJ reads; byte invariants must hold.
- **Stack:** madmom/essentia build only on py3.10; CI + container run py3.11 → librosa fallback (`docs/ANALYSIS_HANDOVER.md` §2). Any essentia-model path must degrade cleanly and be capability-gated (`AnalysisEngine.capabilities()`).
- **Schicht-A pinning:** new dep = `==X.Y.Z` + license/CVE audit (`.claude/rules/coding-rules.md`). No PyYAML in `requirements.txt` today → JSON is the zero-dep format.
- **Legal:** pretrained model weights carry own licenses (Discogs-EffNet family often non-commercial) — verify before any bundling.

## Dependencies

Undecided — depends on OQ5 (rules vs ML). Rules-only path adds **none**.

| Dep | Kind | Version | License | Schicht-A audit needed? | Why |
|---|---|---|---|---|---|
| _(rules-only path)_ | — | — | — | no | JSON + stdlib only; `numpy`/`librosa` already pinned |
| `essentia` pretrained models | py + model weights | `2.1b6.dev1110` (pinned) + weights TBD | AGPL (lib) / weights TBD | yes (weights) | OQ5 ML path; py3.10-only build |
| `scikit-learn` (fallback classifier) | py | TBD | BSD-3 | yes | only if OQ5 picks a trained-local model |

## Open Questions

1. **Format** — JSON rule file (zero dep) vs YAML (new dep) vs SQLite table (UI-editable) vs Python DSL? Must be user-editable + schema-validatable + diffable in git.
2. **Rule semantics** — hard feature ranges vs weighted scoring vs decision tree? How is confidence derived, and how are ties/overlaps between two matching definitions resolved?
3. **Separability** — can the 12–15 already-persisted scalars separate the top ~20 DJ-relevant genres at useful accuracy, or is that mathematically hopeless without new features? Measure, don't guess.
4. **New features worth their compute** — which of MFCC, chroma, `spectral_bandwidth`, `spectral_flatness`, `tempo_variability`, onset/rhythm periodicity, percussive/harmonic ratio actually raise separability? Coordinate with `recommender-similar-tracks` 46-dim vector — one extraction, two consumers.
5. **Rules vs ML vs hybrid** — hand-written definitions vs essentia pretrained (Discogs-EffNet) vs rules-over-embeddings. Trade: explainability + user-editability (goal) vs accuracy vs py3.10-only stack vs weight licensing.
6. **Ground truth** — where from? user library ID3 genres as noisy labels, hand-labelled subset, or synthetic like `scripts/selftest_analysis.py`? Which metric (top-1 / top-3 / per-genre recall) and what counts as "good enough"?
7. **Taxonomy** — whose vocabulary (Beatport / Discogs / user-defined), how deep the hierarchy, how are user-invented styles ("peak-time techno") expressed?
8. **Storage + write-back** — sidecar DB (popularity_engine pattern) vs `master.db` `Genre` write vs MyTag. Multi-label + confidence need a shape `master.db` doesn't have. Opt-in write-back to ID3 / Rekordbox / USB export?
9. **Relation to existing code** — replace `hint_genre()` outright, or wrap it as one built-in definition set? What breaks in `accepted_recommender-rules-baseline` which consumes `genre_hint` today?
10. **"und ähnliches" scope** — which adjacent attributes get the same definition mechanism in M1 (mood/energy) vs later (era, vocal/instrumental, danceability)? `detect_mood()` becomes a definition set too?
11. **Editing UX + safety** — file in app data dir vs in-app editor; validation on load, versioning of definition sets, fallback when a user definition is broken or matches everything.

## Research Plan

- Agent 1 (codebase + web): definition-format survey — JSON-schema-validated rules, existing OSS genre-rule engines, MusicBrainz/Discogs taxonomy shapes → OQ1, OQ7
- Agent 2 (codebase): full feature inventory + extraction cost re-measurement in `analysis_engine.py`; what a shared extraction pass with `recommender-similar-tracks` looks like → OQ3, OQ4
- Agent 3 (web + codebase): separability evidence — published per-feature genre-discrimination results (BPM/spectral/MFCC/rhythm), essentia model accuracy + weight licenses → OQ3, OQ5
- Agent 4 (codebase): storage + write-back paths — sidecar-DB precedent, `master.db` `Genre` semantics, MyTag, USB PDB genre table → OQ8
- Agent 5 (codebase + web): ground-truth + metric design; reuse of `scripts/selftest_analysis.py` harness for a genre benchmark → OQ6
- Agent 6 (codebase): blast radius on `genre_hint` consumers + `ANALYSIS_VERSION` bump / re-analysis migration → OQ9, OQ10, OQ11

## Idea Verification

### 2026-08-16 — PENDING
- Stage 1 pre-filled by interactive agent (not by `research-draft`). Prior Art / Constraints cites drawn from sister docs + code, **not yet re-verified line-by-line**.
- Awaiting `research-draft` Idea-Verifier pass before `drafting_` → `exploring_`.

## Findings / Investigation

Stage 2 Synthesis-Agents (one per OQ). Dated subsections, append-only. ≤150 words each (soft). Never edit past entries — supersede.

### YYYY-MM-DD — <label>
- **Codebase:** … (`file:line` refs required)
- **Web:** … (cited URLs required)
- **Synthesis:** …
- **Confidence:** high / medium / low

## Adversarial Findings

Stage 2 Adversarial-Agent (phase 2). Devil's-advocate — what could go wrong, what assumptions are weak, what dependencies betray us. ≤120 words. Append-only.

### YYYY-MM-DD
- **Weak assumption:** …
- **Failure mode:** …
- **Counter-example:** …

If none survive scrutiny: **"No surviving objections — proceed with caution flags above."**

## Citation Quality

Stage 2 Citation-Verifier (phase 2). Checks every `file:line` ref + URL in `## Findings` exists + says what the Finding claims. PASS / FAIL list. ≤80 words.

### YYYY-MM-DD — <PASS|FAIL>
- PASS: Findings 1, 2, 4 — citations verified
- FAIL: Finding 3 — `app/main.py:123` no such symbol, replace or remove

---

> ↓ Stage 2 phase 2 (autonomous; no user gate) — `research-explore` deepens findings, runs Adversarial + Citation verifiers, then the Research-Verifier gates the whole body before Options-Synthesis advances the doc to `evaluated_`.

## Research Verification

Stage 2 wave-2 verifier over whole research body. ≤120 words. PASS → `evaluated_`; gaps → more Findings.

### YYYY-MM-DD — <PASS|GAPS>
- Coverage of Open Questions: …
- Internal consistency: …
- Citation quality (cross-ref `## Citation Quality`): …
- Adversarial concerns addressed: …

## Options Considered

Stage 2 Synthesis-Agent (phase 2 PASS). Per option: sketch ≤5 bullets, pros, cons, S/M/L/XL, risk, prior-art match.

### Option A — <name>
- Sketch:
- Pros:
- Cons:
- Effort:
- Risk:
- Prior-art match: <slug or "novel">

### Option B — <name>
- Sketch:
- Pros:
- Cons:
- Effort:
- Risk:
- Prior-art match: <slug or "novel">

## Recommendation

Stage 2 Synthesis-Agent (phase 2 PASS). ≤120 words. Which option + what blocks commit + which OQ each Finding answers.

---

> ↓ Stage 3 — `implement/draftplan_`. `research-plan` fills Implementation Plan + Task Queue via 5 agents (Planner, Threat-Modeller, Migration, Perf-Budget, Test-Plan). Reviewer fills Review. On Review PASS, the Mockup+Summary-Agent fills `## Approval Summary` + `## Mockup`, then advances to `approvalgate_`.

## Implementation Plan

Stage 3 Planner-Agent. Concrete enough that someone else executes without re-deriving.

### Scope
- **In:** …
- **Out:** …

### Step-by-step
1. …

### Files touched
Path + role (read / edit / new):
- `<path>` — <role> — <why>

### Testing
High-level (see `## Test Plan` for concrete pytest/cargo cases):
- …

### Risks & rollback
- …

## Threat Model

Stage 3 Threat-Modeller-Agent. Required when feature touches: auth, `require_session`, filesystem (paths in / out), `master.db` writes, network, secrets, user-supplied paths. Otherwise: **"N/A — no security surface."**

### Assets
- … (data, secrets, attacker goal)

### Trust boundaries
- … (which layer trusts which input)

### Threats (STRIDE-light)
| ID | Threat | Mitigation in plan | Test covers |
|---|---|---|---|
| T1 | … | step N / file X | test_… |

### Residual risk
- ≤60 words — what cannot be eliminated, why acceptable.

## Migration Path

Stage 3 Migration-Path-Agent. Required when feature changes: DB schema, file layout, settings/config shape, IPC contract, on-disk caches, USB export bytes. Otherwise: **"N/A — no migration."**

### Before → After
- Data shape today: …
- Data shape after: …
- Existing-data handling: in-place migrate / lazy on read / one-shot backfill

### Backfill / forward-compat
- Migration script: `<file>` (or "no script — schema-additive")
- Old client reads new data: yes/no — how degraded
- Rollback: restore via `<backup>` / re-run reverse migration `<file>`

### User-visible behavior during migration
- … (downtime, progress UI, can app start before complete?)

## Performance Budget

Stage 3 Perf-Budget-Agent. Numbers, not "fast". If feature has no perceptible runtime cost: **"N/A — analysis-only / one-shot."**

| Path | Budget | Measured today | Source |
|---|---|---|---|
| <e.g. POST /api/duplicates/scan> | p95 ≤ 800ms / 50MB peak | … | `tests/perf/…` or "untested" |

### Worst-case scenario
- Input shape: <e.g. 50k tracks, 200 dupes>
- Expected impact: …
- Mitigation if exceeded: …

## API / UX Surface

Stage 3 Planner-Agent. What is added / changed at every layer the user / frontend touches.

### Backend (FastAPI)
- New routes: `<METHOD> <path>` — auth: `require_session`? rate-limited? lock?
- Changed routes: `<METHOD> <path>` — what changed in request/response shape

### Frontend (React)
- New components / hooks / IPC calls (axios + invoke):
- Changed components: …

### Tauri (Rust commands)
- New `#[tauri::command]`s: …
- Changed signatures: …

### CLI / sidecar logs
- New stdout markers (e.g. `LMS_TOKEN=`-style): …

## Telemetry

Stage 3 Planner-Agent. How we know it works after ship. ≤80 words. Otherwise: **"N/A — no runtime behavior to observe."**

- Log markers (`logger.info("op=… …")`): …
- Counters / timing: …
- Health-endpoint surface: …
- User-visible status (toast, statusline, dashboard tile): …

## Test Plan

Stage 3 Test-Plan-Agent. Concrete test cases, one row per. Must cover Threat Model + Migration + Perf budgets.

| ID | Layer | Test file | Case | Covers (Threat / OQ / Step) |
|---|---|---|---|---|
| T1 | py | `tests/test_<area>.py::test_<case>` | … | Threat T1 |
| T2 | rust | `src-tauri/src/audio/.../tests` | … | Step 3 |
| T3 | js | `frontend/src/**/*.test.js` | … | OQ 2 |
| T4 | integration | `tests/test_<integration>.py` | end-to-end happy path | full flow |
| T5 | perf | `tests/perf/<file>.py` (new) | p95 budget vs target | Perf table row N |

## Task Queue

<!--
Small, individually-committable implementation tasks. Written by research-plan (Stage 3),
approved by the user at the Approval Gate. research-implement works ONE task per branch:
routine/<slug>-task-<N>. 1 task = 1 feature = 1 PR. Tick - [x] when the PR is merged.
Keep tasks small — a task too big to review in one PR must be split.
Each task should map back to a Step in ## Implementation Plan and have ≥1 row in ## Test Plan.
-->

- [ ] <task — small, single-purpose, independently testable> — covers Step N, tests T<m>, T<n>

## Review

Stage 3 Reviewer-Agent (`review_`). Unchecked box or rework reason → `rework_`.

- [ ] Plan addresses all goals
- [ ] Plan matches `## Original Idea` — no scope-creep
- [ ] Open questions answered or deferred
- [ ] Prior Art referenced — no duplicated past work
- [ ] Threat Model present + each threat has a test (or N/A justified)
- [ ] Migration Path present + rollback documented (or N/A justified)
- [ ] Performance Budget set + worst-case scenario documented (or N/A justified)
- [ ] API / UX Surface enumerated for every layer touched
- [ ] Telemetry defined for shipped behavior (or N/A justified)
- [ ] Test Plan covers every Threat + every Step + every Perf row
- [ ] Task Queue items are small + independently committable + reference Steps + Tests
- [ ] Dependencies audited — new libs have Schicht-A entries
- [ ] Risk mitigations defined
- [ ] Rollback path clear
- [ ] Affected docs identified (`architecture.md`, `FILE_MAP.md`, indexes, `CHANGELOG.md`)

**Rework reasons:**
- …

## Approval Summary

Stage 3 Mockup+Summary-Agent (after Plan-Reviewer PASS). **Plain user-facing English — NOT Caveman.** This block is what the user reads to decide yes/no. ≤200 words. No `file:line` jargon — describe effects, not internals.

- **What it does:** 1–2 sentences, plain language. What the feature gives the user.
- **What you'll notice:** bullet list of user-visible effects (new button, faster scan, new export option, …).
- **Scope:** N files touched · N tasks · effort S/M/L · risk low/med/high.
- **Rollback:** one line — how it's undone if you dislike it after merge.
- **Mockup:** see `## Mockup` below.

## Mockup

Stage 3 Mockup+Summary-Agent. Adaptive to feature type — decide from `## API / UX Surface`:

- **UI feature** (has frontend components): write a self-contained static wireframe to `docs/research/mockups/<slug>.html` (inline CSS, no build step, no external assets — open in a browser locally). Fill the **UI** block below. Leave the **Backend** block empty/removed.
- **Backend / DSP / USB / DB feature** (no visible UI): fill the **Backend** block with a concrete example — sample API request/response, CLI/log output, or before→after data (metadata tags, USB tree, DB rows). Show the shape the user will actually see. Leave the **UI** block empty/removed.

### UI — mockup file
- `docs/research/mockups/<slug>.html` — <one-line layout + key-interaction description>

### Backend — concrete example
```text
<sample response / CLI output / before→after — the user-visible shape>
```

---

> ⛔ APPROVAL GATE — user `/approve` (→ `accepted_`) or `/reject "<reason>"` (→ `rework_`). The single sign-off: read `## Approval Summary` + `## Mockup`. After approval, nothing is re-researched.
> ↓ Stage 4 — `inprogress_`. `research-implement` builds each Task Queue item via 5 agents (Approach-Probe, Code, Standard-Review, Security-Review, Test-Coverage-Review, Doc-Sync) on a `routine/*` branch. You test + merge the branch yourself.

## PR Log

Stage 4. One row per task PR. `research-implement` appends; user notes merge after local testing.

| Task | Branch | PR | CI | Std Rev | Sec Rev | Test Cov | Doc Sync | Merged |
|---|---|---|---|---|---|---|---|---|
| … | `routine/<slug>-task-N` | #… | pass/fail | pass/fail | pass/fail | pass/fail | pass/fail | YYYY-MM-DD |

## Implementation Log

Stage 4 Code-Agent + Approach-Probe. Dated entries. What built / surprised / changed-from-plan.

### YYYY-MM-DD — Approach Probe (task N)
- Sketches considered: A (…), B (…), C (…)
- Selected: <letter> — why
- Rejected: … — why

### YYYY-MM-DD — Implementation
- Built: …
- Surprised: …
- Deviation from plan: …

---

## Decision / Outcome

Required by `archived/*`. Stage 4 Doc-Sync-Agent populates the checklist; user signs off after testing the branch locally + merging.

**Result**: implemented | superseded | abandoned
**Why**: …
**Rejected alternatives:**
- …

**Code references**: PR #…, commits …, files …

**Performance achieved** (vs `## Performance Budget`):
- <path> — measured p95 / peak — pass/fail

**Telemetry confirmed live**:
- <marker> visible in <logs / dashboard / health endpoint>

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
- Supersedes: <slug or none>
- Superseded by: <slug or none>
