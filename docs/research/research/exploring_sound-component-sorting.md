---
slug: sound-component-sorting
title: Nach Klang-Bestandteilen sortieren (Bass, Hi-Hats, Bells, Melodie)
owner: tb
created: 2026-11-08
last_updated: 2026-11-10
tags: [analysis, similarity, sorting, stems]
related: [recommender-similar-tracks, recommender-taste-llm-audio]
supersedes: []
superseded_by: []
---

# Nach Klang-Bestandteilen sortieren (Bass, Hi-Hats, Bells, Melodie)

> **Caveman+ style.** Fragments, bullets. Drop articles/filler/hedges. No prose paragraphs.
> Word caps are **soft** — recommendations, not hard blocks. Exceed when topic complexity demands; routines may flag excess length but never truncate facts.
> State = folder + filename prefix (not frontmatter). Lifecycle = audit trail. See `../README.md`.
> Routines advance this doc **autonomously** by state. **One** user gate: `approvalgate_` — read `## Approval Summary` + `## Mockup`, then `/approve` or `/reject`. After approval you test the finished branch locally and merge it yourself.
> Section ownership: each `> ↓ Stage X — <agent>: …` marker names the agent that fills the section. Don't write into a section before its stage.

## Lifecycle

- 2026-11-08 — `research/idea_` — created from template; Original Idea = user quote of 2026-11-08 (docs/LIBRARY_ANALYSIS_HANDOVER.md §9)
- 2026-11-08 — `research/idea_` — user answered OQ 1-10 (recorded inline), added W9 similar song structure; §D of the handover still open
- 2026-11-10 — `research/drafting_` — user: "Ja, bis zum Gate" + "nix final bauen, nur planen und testen"; Stage 1 drafted interactively (remote routines dead since 2026-06)
- 2026-11-10 — `research/exploring_` — drafted (scout + prior-art + risk-surface + worker + verifier PASS, 0 rework rounds), ready for explore

## Original Idea (verbatim — never edit)

<!--
Written ONCE by the user. 1–3 sentences, raw. NEVER edited after — not by routines, not by the user.
Every verifier (Stage 1 idea-check, Stage 2 research-check, Stage 3 plan-review, Stage 4 doc-sync) checks
its work against this block. It is the anchor against scope-creep and misreading.
-->

„Ich möchte am Ende zum Beispiel auch nach gleichen Bässen sortieren können oder Bässen mit einer gewissen Tiefe, dann will ich z.B. auch nach Bells sortieren können, nach Hi-Hat-Anteil und gleichen Hi-Hats oder so und wie melodisch und was für Melodien und nach ähnlichen Melodien z.B.“ (tb, 2026-11-08)

---

> ↓ Stage 1 — `drafting_`. `research-draft` fills Problem → Research Plan via 4 agents (Scout, Prior-Art, Risk-Surface, Worker). Verifier fills Idea Verification.

## Prior Art

- **Shipped:** none for components. Nearest: `app/analysis_extras.py` (PR #78) — whole-track bass share < 60 / < 120 Hz + low-band mono correlation, no component isolation. `scripts/library_measure_anlz.py` (PR #78) — reads + unmasks Rekordbox PSSI for 4744 tracks, script only, not in the app.
- **Active research:** [accepted_recommender-similar-tracks](../implement/accepted_recommender-similar-tracks.md) — whole-track similarity, 4 named slices (mfcc26 / chroma12 / spectral4 / dynamics4) in `app_data/track_vectors.db` (`:434-435`), **0/12 tasks built**; backfill at 22.05 kHz (`:438`) cuts the hats band; "Out: sklearn/FAISS/PyTorch" (`:445`). → this doc **extends that store** (new slices, `VECTOR_VERSION` bump `:484`), no second store.
- **Active research:** [inprogress_recommender-taste-llm-audio](../implement/inprogress_recommender-taste-llm-audio.md) — torch gated at M2 (`:300-307`: installer ≤ +400 MB, boot ≤ +5 s, p95 CPU ≤ 3 s), benchmark never run (`:474`). → **one** torch decision for both docs.
- **Active research:** [inprogress_analysis-underground-mainstream-classifier](../implement/inprogress_analysis-underground-mainstream-classifier.md) — plans a sortable column (`:618`), same UI pattern. [accepted_library-quality-upgrade-finder](../implement/accepted_library-quality-upgrade-finder.md) — spectral-cutoff sidecar, no component overlap. [drafting_performance-overhaul](drafting_performance-overhaul.md) — light track list drops heavy fields (`:28`).
- **Superseded / abandoned:** none on stems, embeddings, structure or component sorting (`docs/research/archived/` = 7 security docs + 1 superseded auth model).
- **External precedent:** Stage 2 (RQ2 / RQ5 web agent) — Rekordbox Related Tracks, stems products, sample-similarity tools.

## Problem

4765-track library sorts by whole-track metadata only (BPM, key, genre, rating). A DJ picks by ear for component traits: bass character, hat pattern, melody, build-up. No query "bass like this one" or "same structure". Cost: manual digging per set; tracks that would mix well by component stay undiscovered.

## Goals / Non-goals

**Goals**
- G1 **value columns** per track, sortable: bass depth (fundamental Hz, sub share, boom length), hi-hat amount + openness + grid pattern (on-beat / off-beat / 8th / 16th), melodic-ness (lead lines), structure numbers (intro bars, first drop, drop count, break share).
- G2 **seed similarity** — "sort by similarity to this track" per component: bass (sound + line), hats (sound + pattern), melody (same notes, transposition-invariant), structure (W9).
- G3 **categories / filters**: melody type (Lead; Acid line — unconfirmed, voice input heard "Unassed"; Vocal hook — user "maybe"), structure families.
- G4 **user-definable sound classes** from example tracks (bells = first example of many).
- G5 every feature evaluated against a user-provided example set (track IDs only); thresholds from measured distributions.
- G6 local-only, GPU optional, fits the analysis-depth model (own level or background job); extends `track_vectors.db` named slices.

**Non-goals**
- No stem export / stem playback; stems never persisted (≈ 1 TB vs 178 GB free).
- No cloud inference; no audio leaves the machine.
- No writes to `master.db`, ANLZ, audio files or file tags.
- No "next track" recommender (that is recommender-rules-baseline / taste).
- No replacement of whole-track similar-tracks; no second vector store.
- No model training beyond small per-class classifiers on fixed embeddings.
- Nothing built before the approval gate (user 2026-11-10: plan + test only).

## Constraints

- **External APIs / rate limits:** none at runtime. One-time model-weight download from official hosts only if a model option wins (Stage 2); no runtime model download exists in `app/` today (grep `huggingface|hf_hub|torch.hub` = 0 hits).
- **Data shape (`master.db`, ANLZ, USB PDB):** PSSI XOR-masked in 54.5 % of files; pyrekordbox 0.1.7 parses masked PSSI as garbage (`scripts/library_measure_anlz.py:16`); the app only masks (`app/anlz_usb_export.py:72`), never unmasks. 20 tracks without PSSI, 3 without grid; kind → label mapping unverified against the Rekordbox UI (handover §3.4.1). Track dicts carry **no** `phrases` at runtime (`get_all_tracks` returns `self.tracks.values()` at `app/live_database.py:673` / `app/database.py:1186`; grep `phrases` = 0 hits in both files); no route returns PSSI per track. Full ANLZ pass = 216 s for 4765 tracks → not a startup task. rbox never for ANLZ files.
- **Schicht-A pinning / library version:** `requirements.txt:38-41` numpy 1.26.4, scipy 1.11.4, numba 0.58.1, librosa 0.10.1. scikit-learn is REQUIRED in `backend.spec:56` but **unpinned** (1.9.0 installed transitively). torch / onnxruntime absent. One-file EXE (`backend.spec:175` `EXE(` takes binaries + datas, no `COLLECT`; `:186-187` `upx=False`, `runtime_tmpdir=None`): missing REQUIRED → `SystemExit` (`:80-82`); OPTIONAL list exists (`:65`, madmom / essentia).
- **Perf / capacity:** base audio pass 0.18 s CPU per audio second = 67 CPU-h, 6.6 h @12 workers; madmom +5 GB RSS per worker (handover §3.5.1). `hpss` ≈ 20 s CPU + 1.9 GB RSS per 5-min track; `pyin` full track ≈ 75 s; band split 2.8 s (handover §9.2.1). GPU RTX 2070 SUPER 8 GB, must stay optional (taste doc `:67`). torch CUDA wheel 1.99 GB (cu130) to 2.86 GB (cu128) vs CPU wheel 111-121 MB (handover §9.2.1). Baselines: 67 CPU-h = base audio pass; the ~33 CPU-h in the user's answer 10 is the **extra** cost of the no-dependency combo (bands + hpss + chroma/mfcc) on top of it.
- **Legal / compliance:** weight licences must allow this use (flag CC-BY-NC / research-only); example set = track IDs only, never audio in the repo.
- **Concurrency invariants:** no `master.db` write → `_db_write_lock` not involved. Any route taking a path → `validate_audio_path` / `ALLOWED_AUDIO_ROOTS`; mutating routes behind `require_session` (`.claude/rules/coding-rules.md:14-15`). Subprocess always with `timeout=` (`:36`). Partial results never into `AnalysisCache` (handover §0). Settings read once per job in the main process (handover §3.6.1). No persistent job table exists; precedents: phrase batch `_phrase_jobs` (`app/main.py:7268-7274`), `analyze-batch` NDJSON + single-flight (`:5841`, `:5982`).
- **Sister-plan rules:** similar-tracks `:59` feature extraction only in `track_vector_builder.py`; `:484` `VECTOR_VERSION` bump per new slice; `track_vectors.db` path is CWD-relative (`app/db_taste.py:42-44`).
- **UI:** TrackTable sort = `t[key]` on this branch (`frontend/src/components/TrackTable.jsx:252-276`); typed `SORT_VALUES` with null-last only on `origin/feat/sortable-columns` (`8c30c89`, not merged into PR #60 / #78); `customColumns` headers not sortable (`:521-530`). Light-list merge point `app/main.py:1116-1124` — copy, never mutate the cached dict.

## Dependencies

Candidates only — Stage 2 decides (RQ1, RQ2, RQ5, RQ6). **W9 (structure) and the baseline value features need no new dependency.**

| Dep | Kind | Version | License | Schicht-A audit needed? | Why |
|---|---|---|---|---|---|
| torch | py | 2.15.0 (PyPI, CPU, 120.8 MiB) / 2.14.1+cu130 (1.99 GB; cu128 build 2.86 GB) | BSD-3-Clause | yes | inference runtime for separation / embeddings / pitch — only if a model option wins |
| torchaudio | py | 2.11.1 | BSD-2-Clause | yes | audio I/O + transforms for torch models |
| demucs | py | 4.1.0 | MIT (code); weights: verify in Stage 2 | yes | source-separation candidate (bass / drums / other / vocals) |
| onnxruntime | py | 1.31.1 (14.2 MiB, CPU EP) | MIT | yes | torch-free inference candidate |
| audio-embedding model (CLAP / PANNs class) | py + weights | Stage 2 | verify in Stage 2 | yes | user-definable sound classes (G4) |
| neural pitch tracker (CREPE / basic-pitch class) | py + weights | Stage 2 | verify in Stage 2 | yes | melody line on an isolated part (W6-W8) |
| GPU (CUDA) | hardware | RTX 2070 SUPER 8 GB, CUDA 13.4 | — | no | optional accelerator, never required |

## Open Questions

### User decisions (asked + answered 2026-11-08; German as given; hurdles + numbers: handover §9.2 / §9.2.1)

1. **W1 gleiche Bässe** — ähnlicher *Klang* (Timbre), ähnliche *Linie* (Rhythmus/Noten) oder beides? Kick mitzählen oder nicht?
   → **Antwort tb 2026-11-08:** beides (Klang und Linie). Kick: nicht beantwortet, beide Varianten vorsehen.
2. **W2 Bass-Tiefe** — „Tiefe“ = Tonhöhe in Hz, Sub-Bass-Anteil (< 60 Hz) oder Länge/Wucht des Basses?
   → **Antwort tb 2026-11-08:** alles drei (Tonhöhe, Sub-Anteil, Länge/Wucht).
3. **W3 Bells** — welche Klänge zählen (Bell-Synth, Röhrenglocke, metallischer Pluck, Cowbell)? Bitte 5 Beispiel-Tracks mit, 5 ohne (nur Track-IDs).
   → **Antwort tb 2026-11-08:** verallgemeinern: alles, was sich als eigenes Geräusch definieren lässt, soll eine Klasse sein (Bell nur ein Beispiel, viele weitere). → benutzerdefinierte Klangklassen aus Beispielen. Beispiel-IDs noch offen.
4. **W4 Hi-Hat-Anteil** — Lautstärke, Dichte (8tel / 16tel / Offbeat) oder offen vs. geschlossen?
   → **Antwort tb 2026-11-08:** eher offene Hats; zusätzlich sortierbar nach Offbeat / Onbeat / 8tel / 16tel; ein Track trägt diese Eigenschaften gekreuzt (mehrere Attribute).
5. **W5 gleiche Hi-Hats** — Klang oder Pattern? Bitte 5 Paare „gleiche Hats“.
   → **Antwort tb 2026-11-08:** Klang und Pattern, beides. Paare noch offen.
6. **W6 wie melodisch** — zählt ein Pad / Akkordbett als melodisch, oder nur eine Lead-Linie?
   → **Antwort tb 2026-11-08:** eher Lead-Melodie zählt, nicht Pad/Akkordbett (Spracheingabe „Delete-Melodie“ = Lead).
7. **W7 Melodie-Art** — welche Kategorien (Arpeggio, Lead, Chords/Pad, Acid-Linie, Vocal-Hook, …)? Du benennst sie.
   → **Antwort tb 2026-11-08:** Lead, Acid-Linie (Spracheingabe „Unassed“, unsicher — nachfragen), Vocal-Hook „maybe“.
8. **W8 ähnliche Melodien** — gleiche Noten oder gleiches Gefühl? Zählt eine transponierte Melodie als ähnlich?
   → **Antwort tb 2026-11-08:** gleiche Noten; transponiert zählt als ähnlich.
9. **Neue Dependency** — torch / Source-Separation-Modell OK? Darf es die GPU nutzen? Fakt: GPU-torch für Windows = 2,0–2,9 GB Wheel, CPU-torch 111–121 MB; das Installer-Gate von `recommender-taste` (+400 MB) schafft nur CPU-torch. Eine torch-Entscheidung für beide Features.
   → **Antwort tb 2026-11-08:** erlaubt (torch und GPU). Plan: CPU-torch gepinnt, GPU optional.
10. **Tiefe** — gehört das zur Analysetiefe „Hoch“ (Handover §3.6) oder zu einer dritten Stufe „Maximal“?
   → **Antwort tb 2026-11-08:** im Prinzip eigene Stufe „Maximal“; bei ~33 CPU-h Baseline erst optimieren und nochmal reden.

11. **W9 ähnlicher Aufbau (neu 2026-11-08)** — „nach ähnlichen Segmenten sortieren, also nach ähnlichen Aufbauen vom Song“: alle Songs mit gleichem Aufbau, nach verschiedenen Aufbauten sortieren, oder zu einem Seed-Track Songs mit gleichem / ähnlichem Aufbau sehen. Signal liegt schon vor: Rekordbox-PSSI-Phrasenfolge für 4744 Tracks (Stage D) + LMS-Phrasen. Offen: Ähnlichkeit auf Phrasen-Kinds, Bar-Längen oder beidem? Zählt die Reihenfolge strikt (Sequenz) oder nur die Anteile (Intro-Länge, Chorus-Anzahl)?

Still open with the user: example track IDs (bells 5 + 5, hat pairs 5), the W7 category heard as "Unassed" (Acid?), W1 kick in or out, W9 sequence vs shares.

### Research questions (Stage 2 — one agent group each)

- **RQ1** Isolation: do W1 / W5 / W8 need model-based source separation, or do band split + HPSS suffice? Quality proxy + cost, CPU vs GPU. Bass similarity with the kick in vs out (user: plan both variants).
- **RQ2** Runtime: torch bundled vs optional on-demand runtime vs torch-free ONNX — which fits the installer / boot limits and the pinning rules?
- **RQ3** W9: which representation + metric for structure similarity; is Rekordbox PSSI sufficient; cost to hold it for all tracks.
- **RQ4** Value features W2 / W4 / W6 without separation: usable, coarse, or useless? Stability + cost.
- **RQ5** W3 user-definable sound classes: few-shot on a pretrained audio embedding — which model, licence, cost, does it work inside dense mixes?
- **RQ6** Melody: pitch tracker + transposition-invariant similarity for W8; feasibility of W7 categories.
- **RQ7** Storage: extend `track_vectors.db` named slices (sister plan unbuilt) — schema, key (track id vs path + mtime + size), versioning.
- **RQ8** UI: how measured values become sortable columns, a similarity action and filters, given `feat/sortable-columns` is unmerged.
- **RQ9** Depth: cost of the user's "Maximal" level (CPU-h, RAM, GPU) after optimisation; background job as fallback if it exceeds a stated budget. Result goes back to the user (answer 10: "erst optimieren und nochmal reden").
- **RQ10** Evaluation: protocol + minimum example set so each wish is measured, not assumed.

## Research Plan

- Agent 1 (codebase): prior art, runtime phrase data, sidecar pattern, extension points, UI integration, build rules → RQ3, RQ7, RQ8, RQ9.
- Agent 2 (web): separation / drum / pitch / embedding models — licences, Windows py3.11 wheels, footprint, DJ-software precedent, packaging → RQ1, RQ2, RQ5, RQ6.
- Agent 3 (measurement, isolated env): Demucs-class separation, embeddings, pitch on this machine, CPU vs GPU, time / RAM / VRAM → RQ1, RQ2, RQ5, RQ6.
- Agent 4 (measurement): structure representations + metrics on the 4744 measured PSSI sequences → RQ3.
- Agent 5 (measurement, no new dependency): W2 / W4 / W5 / W6 value features on 40 tracks with Rekordbox grids — distributions, stability, cost → RQ4.
- Synthesis: evaluation protocol + example-set size → RQ10.

## Idea Verification

Stage 1 Verifier. Dated entries, append-only. PASS / FAIL + ≤40-word reason (checked vs `## Original Idea` + `## Prior Art`).

### 2026-11-10 — PASS
- Intent: W1-W9 + every recorded answer covered, no scope creep. Prior art: 9 doc citations + 8 `file:line` refs spot-checked, overlap flagged, "extend, no second store" consistent. Tractability: RQ1-RQ10 all assigned.
- Six minor defects fixed in the same pass: G3 Acid / Vocal hook marked unconfirmed, RQ9 no longer reopens the user's "Maximal" decision, 67 vs 33 CPU-h reconciled, RQ1 gains kick in / out, `backend.spec` line corrected, one wheel-size source.

---

> ↓ Stage 2 — `exploring_` (autonomous; no user gate). On Idea-Verifier PASS, `research-draft` advances `drafting_` → `exploring_` directly. `research-explore` runs parallel tiered agents (codebase + web + synthesis per OQ), an Adversarial agent, a Citation-Quality verifier, and a Research-Verifier — one autonomous pass to `evaluated_`.

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
