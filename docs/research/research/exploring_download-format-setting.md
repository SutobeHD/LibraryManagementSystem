---
slug: download-format-setting
title: Download-Format-Setting — Standard AIFF + User-konfigurierbares Ziel-Format pro Download
owner: tb
created: 2026-05-28
last_updated: 2026-05-28
tags: [downloader, soundcloud, aiff, settings, ux]
related: [library-format-converter, downloader-unified-multi-source]
supersedes: []
superseded_by: []
---

# Download-Format-Setting — Standard AIFF + User-konfigurierbares Ziel-Format pro Download

> **Caveman+ style.** Fragments, bullets. Drop articles/filler/hedges. No prose paragraphs.
> Word caps are **soft** — recommendations, not hard blocks. Exceed when topic complexity demands; routines may flag excess length but never truncate facts.
> State = folder + filename prefix (not frontmatter). Lifecycle = audit trail. See `../README.md`.
> Routines advance this doc by state. 4 user gates: A `ideagate_`, B `midgate_`, C `plangate_`, D PR-merge.
> Section ownership: each `> ↓ Stage X — <agent>: …` marker names the agent that fills the section. Don't write into a section before its stage.

## Lifecycle

- 2026-05-28 — `research/idea_` — created (user request after SC-downloader security audit)
- 2026-05-28 — `research/drafting_` — Stage 1 worker filled Problem → Research Plan inline at creation time (faster than waiting for next routine cycle; same outputs the routine would have produced)
- 2026-05-28 — `research/ideagate_` — Stage 1 verifier PASS, awaiting GATE A
- 2026-05-29 — `research/exploring_` — GATE A PASSED by user; AIFF default + 6-Option-Dropdown specs confirmed; advanced for Stage 2 wave-2 verifier

## Original Idea (verbatim — never edit)

<!--
Written ONCE by the user. 1-3 sentences, raw. NEVER edited after — not by routines, not by the user.
Every verifier (Stage 1 idea-check, Stage 2 research-check, Stage 3 plan-review, Stage 4 doc-sync) checks
its work against this block. It is the anchor against scope-creep and misreading.
-->

Beim Download standardmäßig in AIFF-Dateien umgewandelt (Apple Lossless, die besten für Metadaten). Soll immer einstellbar sein in Settings, in welches Format die Dateien konvertiert werden. An bestehendes Format-Konverter-Research anschließen, nichts unnötig doppeln.

---

> ↓ Stage 1 — `drafting_`. `research-draft` fills Problem → Research Plan via 4 agents (Scout, Prior-Art, Risk-Surface, Worker). Verifier fills Idea Verification.

## Prior Art

- **Active — HIGH overlap, complementary scope:** [`ideagate_library-format-converter`](ideagate_library-format-converter.md) (GATE A) — library-weiter Batch-Konverter mit DB-Integrität (Cues, Beatgrid, Playlists). **Dieses Doc ist die per-Download-Variante**, das andere Doc ist post-hoc-Library-Migration. Geteilte Primitive: FFmpeg AIFF-Cmd, AAC-Priming-Drift (OQ 1 dort), `_convert_to_aiff` helper. Hier KEINE Snapshot/Rollback/DB-row-rewrite Logik nötig — Track ist beim Format-Convert noch nicht in `master.db`.
- **Active — bigger scope, slower ship:** [`accepted_downloader-unified-multi-source`](../implement/accepted_downloader-unified-multi-source.md) — Goal Q11 ist exakt "AIFF-as-default output". Aber das Doc bündelt SpotiFLAC + Tidal/Qobuz/Amazon + 100%-match + Quality-Ranker + Genre-sync + Provenance. **Mein Scope ist der ship-bare Subset davon**, der unabhängig vom unified-downloader-Build heute landen kann.
- **Shipped — code already there:** `app/soundcloud_downloader.py:_convert_to_aiff` (Function existiert), `_aiff_requested()` (reads `sc_download_format == "aiff"`), default `"auto"` (passthrough). UI fehlt komplett — Setting nicht in Settings.json-Schema, nicht in `SetReq`, nicht im SettingsView. → Half-built feature; dieses Doc schließt die Lücke.
- **External precedent:** Rekordbox-Editor hat keine Download-Format-Wahl (kein Download). Serato DJ Pro Default = original source format. Apple Music Match: ALAC. Tidal-Downloader-CLI: FLAC/ALAC config-flag. Convention: lossless default + user-overridable.

## Problem

Stage 1 Worker. Soft 60w cap.

SC-Downloads schreiben Source-Format (MP3 progressive / AAC HLS / Original-Upload je nach Track + Account-Tier). User will lossless AIFF als Default — beste DJ-SW-Kompatibilität, beste ID3-Tag-Surface (Rekordbox/CDJ-3000 reads ID3v2 nativ aus AIFF). Heute: `sc_download_format` Setting existiert (auto/aiff), aber kein UI, kein Default-AIFF, keine erweiterten Targets (FLAC/WAV/ALAC/MP3).

## Goals / Non-goals

**Goals**
- **Default-Setting** `sc_download_format = "aiff"` (statt heutigem `"auto"`).
- **Settings-UI** (Settings-Tab) mit Dropdown — 6 Targets, AIFF preselected:
  1. **AIFF** (uncompressed PCM, ~30 MB / 3 min, CDJ-3000 nativ) ← Default
  2. **ALAC** (Apple Lossless, .m4a Container, ~15 MB / 3 min)
  3. **FLAC** (Free Lossless Audio Codec, ~15 MB / 3 min, best DJ-SW compat outside Rekordbox)
  4. **WAV** (uncompressed PCM, RIFF Container, ~30 MB / 3 min, equivalent to AIFF audio-wise)
  5. **MP3-320 CBR** (lossy 320 kbps Constant-Bitrate, ~7 MB / 3 min) — surfaces lossy warning toast
  6. **Original** (passthrough — was SC liefert, kein Re-Encode-Step nach HLS-Mux)
- **Setting persisted** via existing `SettingsManager` + `SetReq` Pydantic field.
- **Per-format Conversion-Matrix** dokumentiert: welche Source → welches Target ist sinnvoll (kein fake-lossless re-encode MP3→FLAC).
- **Reuse** of existing `_convert_to_aiff` + extension dafür (`_convert_to_target_format`).
- **Tag-preservation** via mutagen (cross-format) — bereits gelöst in `app/audio_tags.py`, hier nur einbinden.

**Non-goals**
- Library-weiter Batch-Konverter — separates Feature, siehe [[library-format-converter]].
- DB-Integrity (Cues/Beatgrid/Playlists überschreiben) — Track wird hier vor Library-Import konvertiert, also keine row-rewrite Logik.
- Multi-Source-Quality-Picking, SpotiFLAC, Tidal/Qobuz — siehe [[downloader-unified-multi-source]].
- AAC-Priming-Drift Auflösung — wenn `_convert_to_aiff` heute drift hat, ist das auch beim batch-converter Problem. Wird DORT als OQ 1 erforscht. Hier nur referenziert — dieses Doc übernimmt was immer dort beschlossen wird.
- Format-Auswahl per-Download (UI im Download-Button) — Setting only, MVP. Per-Download override = follow-up.

## Constraints

Stage 1 Worker + Risk-Surface-Agent.

- **Existing setting key** `sc_download_format`: aktuell nur "auto" / "aiff" supported (`app/soundcloud_downloader.py:_aiff_requested`). Schema-additiv erweitern; alte Werte bleiben gültig.
- **SetReq Pydantic v2**: neuer typed field nötig (`Literal["aiff", "flac", "wav", "alac", "mp3", "original"]`). Siehe Schicht-A pinning in [`.claude/rules/coding-rules.md`](../../../.claude/rules/coding-rules.md).
- **FFmpeg in PATH** required für jede non-passthrough conversion. Bereits requirement.
- **Mutagen 1.47.0** für cross-format tag preservation. Bereits `requirements.txt`.
- **`validate_audio_path`** Sandbox für source + target Pfade — Convert läuft in `tempfile.NamedTemporaryFile`, finale Move geht in `MUSIC_DIR/SoundCloud/…` (existing pattern).
- **Subprocess-timeout** 30s default (Coding-Rules) ist zu kurz für lossless conversion großer Tracks. Bereits in `_convert_to_aiff` auf `_DOWNLOAD_TIMEOUT * 2 = 360s` gesetzt. Reuse.
- **Storage expansion** AAC→AIFF ~5x (relevant ab Library-Größe). Disclaimer im Settings-UI.
- **Legal posture**: AIFF/FLAC/WAV/ALAC sind alle lossless re-container/-encode dessen was SC bereits ausgeliefert hat. Keine Quality-Boost-Vortäuschung — wenn Source MP3 320 ist, schreiben wir keine "lossless FLAC" Behauptung in den Tag. Siehe Quality-Policy in [[downloader-unified-multi-source]] (lossless-first rule).
- **Default-change is user-visible**: `sc_download_format` switch von "auto" → "aiff" ändert das Verhalten von Bestandskunden. Migration: behalte "auto" als legitim explicit Wert (= passthrough), aber set fresh installs default = "aiff". Existing settings.json mit "auto" oder fehlendem Key bleibt unverändert — UI labelt "auto" als "Original (Source-Format beibehalten)".

## Dependencies

| Dep | Kind | Version | License | Schicht-A audit needed? | Why |
|---|---|---|---|---|---|
| FFmpeg | system PATH | n/a | LGPL/GPL | no | already required for HLS mux + existing `_convert_to_aiff` |
| mutagen | py | 1.47.0 (pinned) | GPL | no | already in `requirements.txt`, cross-format tag preservation |

**None new** — uses existing stack only.

## Open Questions

Stage 1 Worker. Numbered. Each resolvable.

1. **Default value für fresh installs**: hard-set `"aiff"`, oder ein einmaliger First-Run-Dialog ("welches Format willst du standardmäßig?") mit AIFF preselected? Letztere ist DX-freundlich, kostet UI-Aufwand.
2. **`"original"` semantics**: passthrough (= heute "auto") = bytes-identisch wie SC sie liefert (MP3/AAC/WAV/FLAC je nach Quality-Tier des Tracks), kein Re-Encode. Aber: HLS-Streams werden bereits per ffmpeg `-c copy` zu .m4a remuxt — gilt das schon als "non-original"? Vorschlag: ja, "original" = "kein zusätzlicher conversion-Step nach dem download/mux". Reicht das oder muss user explizit sehen "wir haben dein MP3 zu AIFF konvertiert"?
3. **Quality-Loss-Warnung bei lossless → lossy** (z.B. user wählt MP3-320 als Default): UI-Warnung nötig? Vorschlag: bei MP3 / ALAC-256kbps Targets einmal "lossy target — Original-Quality geht verloren" toast/disclaimer.
4. **MP3-Bitrate-Fixierung**: 320 kbps CBR fest, oder Sub-Setting (192/256/320/VBR-V0)? Vorschlag: 320 CBR fix für MVP — der DJ-Use-Case will eine konsistente Qualitätsfloor, kein Bitrate-Tuning.
5. **ALAC vs AIFF Default — RESOLVED 2026-05-29 (user)**: AIFF default (uncompressed PCM, CDJ-3000 nativ, dein Wording matches). ALAC als alternative Settings-Option (compressed lossless, .m4a, ~50% kleiner). Full dropdown ships M1 mit 6 Targets — AIFF preselected. Apple Lossless / ALAC ist im Dropdown sichtbar mit Hinweis "lossless, kleiner als AIFF, weniger DJ-SW-getestet".
6. **Apply-zu-Lokal-Import**: Soll dieses Setting auch greifen beim manuellen Drag-und-Drop-Import (`app/services.py:ImportManager`)? Vorschlag: NEIN für MVP — lokal-importierte Files lässt der User idR im Original (er hat sie ja schon im finalen Format gespeichert). Apply nur auf Downloads (SC heute, unified later).

## Research Plan

Stage 1 Worker. Each bullet = one Stage-2 agent.

- **Agent 1 (codebase):** map alle Stellen wo `sc_download_format` heute gelesen wird + alle Stellen wo `_convert_to_aiff` aufgerufen wird; check ob es noch andere Download-Pfade gibt (lokal-import / unified-downloader-stub) die das Setting reuse-fähig wären. Output: file:line Liste.
- **Agent 2 (codebase + sister docs):** delta-check vs [[library-format-converter]] und [[downloader-unified-multi-source]] — was an FFmpeg-Cmd / Tag-Preservation / AAC-Priming-Behandlung kann verbatim referenziert werden statt re-spezifiziert. OQ 5 (AIFF vs ALAC) + OQ 2 ("original" semantics) hier klären.
- **Agent 3 (web):** AIFF vs ALAC vs FLAC für DJ-software (Rekordbox 7, Serato DJ Pro, VirtualDJ) — welches Format hat in 2026 die beste Tag-/Cover-Art-/Cue-Preservation. Cite Rekordbox docs + community-threads (DJTechTools, r/Beatmatch).
- **Agent 4 (codebase):** Settings-UI architecture in `frontend/src/components/SettingsView.jsx` (oder wo immer die Settings-Tabs leben) — wie heisst das aktuelle Pattern für Dropdown-Settings; gibt's einen vorhandenen "Download"-Section oder müssen wir einen einführen?

## Idea Verification

Stage 1 Verifier. Dated entries, append-only. PASS / FAIL + ≤40-word reason (checked vs `## Original Idea` + `## Prior Art`).

### 2026-05-28 — PASS
- **Intent**: AIFF default + Settings-Dropdown both in Goals, OQ 5 surfaces the AIFF-vs-ALAC clarifier (user wrote "AIFF (Apple Lossless)", which are two different formats — answer waits for GATE A). "Nichts unnötig doppeln" honoured: every overlap with `library-format-converter` / `downloader-unified-multi-source` is a Prior-Art cross-link, not a re-spec.
- **Prior-art**: Both active sister docs labelled with explicit scope-delta (per-download here, library-batch / multi-source there). Half-built code state (`_convert_to_aiff` + `sc_download_format`) cited file-precise — anchors the diff against drift.
- **Plan**: 6 OQs all yes/no or X-vs-Y, no philosophy. 4 Research-Plan bullets cover OQs 1-6 without orphans (codebase delta agent doubles for OQs 2+5; UI agent answers the Settings-pattern unknown).

---

> ⛔ GATE A — user `/gate-pass` (→ `exploring_`) or `/gate-reject` (→ `drafting_`).
> ↓ Stage 2 — `exploring_`. `research-explore` runs parallel tiered agents (codebase + web + synthesis per OQ), an Adversarial agent, and a Citation-Quality verifier.

## Findings / Investigation

Stage 2 Synthesis-Agents (one per OQ). Dated subsections, append-only. ≤150 words each (soft). Never edit past entries — supersede.

### YYYY-MM-DD — <label>
- **Codebase:** … (`file:line` refs required)
- **Web:** … (cited URLs required)
- **Synthesis:** …
- **Confidence:** high / medium / low

## Adversarial Findings

Stage 2 Adversarial-Agent (wave 2). Devil's-advocate — what could go wrong, what assumptions are weak. ≤120 words. Append-only.

### YYYY-MM-DD
- **Weak assumption:** …
- **Failure mode:** …
- **Counter-example:** …

## Citation Quality

Stage 2 Citation-Verifier (wave 2). Checks every `file:line` ref + URL in `## Findings` exists + says what the Finding claims.

### YYYY-MM-DD — <PASS|FAIL>
- …

## Mid-Research Checkpoint

GATE B. `research-explore` fills Status after wave 1. User fills Verdict via `/gate-pass` or `/gate-reject`.

### Status — YYYY-MM-DD (routine)
- Covered: …
- Still open: …
- Direction: …
- Adversarial concerns surfaced: …

### Verdict — YYYY-MM-DD (user)
- _(empty until GATE B)_

---

> ⛔ GATE B — user `/gate-pass` (→ `exploring_` wave 2) or `/gate-reject` (→ `exploring_` + feedback).
> ↓ Stage 2 wave 2 — `research-explore` deepens, runs Adversarial + Citation verifiers.

## Research Verification

Stage 2 wave-2 verifier over whole research body. PASS → `evaluated_`; gaps → more Findings.

### YYYY-MM-DD — <PASS|GAPS>
- …

## Options Considered

Stage 2 Synthesis-Agent (wave 2 PASS). Per option: sketch ≤5 bullets, pros, cons, S/M/L/XL, risk, prior-art match.

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

Stage 2 Synthesis-Agent (wave 2 PASS). ≤120 words.

---

> ↓ Stage 3 — `implement/draftplan_`. `research-plan` fills Implementation Plan + Task Queue via 5 agents (Planner, Threat-Modeller, Migration, Perf-Budget, Test-Plan). Reviewer fills Review.

## Implementation Plan

Stage 3 Planner-Agent.

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

## Threat Model

Stage 3 Threat-Modeller-Agent. Required when feature touches: auth, `require_session`, filesystem, `master.db` writes, network, secrets, user-supplied paths.

**Preliminary**: feature touches user-supplied path (`tempfile` + final move into `MUSIC_DIR/SoundCloud/<artist>/<title>.<ext>`) via existing `_build_save_path` sandbox. New FFmpeg subprocess invocation. Both patterns already audited in shipped SC downloader. **Likely N/A — no new attack surface beyond [[project-sc-downloader-security]] invariants.**

### Assets
- …

### Trust boundaries
- …

### Threats (STRIDE-light)
| ID | Threat | Mitigation in plan | Test covers |
|---|---|---|---|
| T1 | … | step N / file X | test_… |

### Residual risk
- …

## Migration Path

Stage 3 Migration-Path-Agent.

### Before → After
- **Settings.json today:** `sc_download_format` optional, default `"auto"` (passthrough). Two values supported (`"auto"`, `"aiff"`).
- **Settings.json after:** `sc_download_format` typed enum, default `"aiff"` for fresh installs. Old `"auto"` value preserved (re-labelled `"original"` in UI, kept as alias for backwards-compat).
- **Existing-data handling:** schema-additive only. No migration script needed. SettingsManager._sanitize_loaded picks up the new field on next load.

### Backfill / forward-compat
- Migration script: **no script — schema-additive**.
- Old client reads new data: ja, ignoriert unknown values (Pydantic v2 with extra="ignore").
- Rollback: revert the SetReq field; defaults fall back to `"auto"`.

### User-visible behavior during migration
- Existing settings.json users keep their current behavior. Fresh installs / users who toggle the UI for the first time see AIFF default. **No silent format-switch on upgrade.**

## Performance Budget

Stage 3 Perf-Budget-Agent.

| Path | Budget | Measured today | Source |
|---|---|---|---|
| SC download MP3-passthrough | p95 ≤ 30s | … | existing |
| SC download AIFF-converted (10min track) | p95 ≤ 60s (incl. ffmpeg pcm_s16le pass) | not measured | needs Stage 3 perf-probe |
| Settings-UI dropdown change | p95 ≤ 100ms (local settings.json write) | … | existing |

### Worst-case scenario
- Input shape: 60-min DJ-Set (250 MB lossless source), target AIFF
- Expected impact: 2-3 min ffmpeg conversion + 3x disk write
- Mitigation if exceeded: keep `_DOWNLOAD_TIMEOUT * 2` timeout, surface progress in UI, allow user-cancel

## API / UX Surface

Stage 3 Planner-Agent.

### Backend (FastAPI)
- New routes: **none** — settings flow uses existing `PUT /api/settings` + `GET /api/settings` (both `Depends(require_session)` for mutation).
- Changed routes: `SetReq` Pydantic model gains one typed field.

### Frontend (React)
- New components: Settings-Dropdown für Download-Format (Component pattern depends on Agent 4 finding).
- Changed components: SettingsView gets the new dropdown.

### Tauri (Rust commands)
- **None** — pure Python + frontend feature.

### CLI / sidecar logs
- New log marker: `[SC-DL] format-policy=<target> source=<ext>` per download for telemetry.

## Telemetry

Stage 3 Planner-Agent.

- Log marker `[SC-DL] format-policy=<target> source=<ext>` per download — see what users pick over time.
- Counter (in-memory or registry): conversions performed per target format — for follow-up: which formats are actually used.
- User-visible: format-badge on each download task card (e.g. "→ AIFF") so user sees what was applied.

## Test Plan

Stage 3 Test-Plan-Agent.

| ID | Layer | Test file | Case | Covers |
|---|---|---|---|---|
| T1 | py | `tests/test_soundcloud_downloader.py` (new) | aiff target converts MP3 source via `_convert_to_target_format` | Step N |
| T2 | py | same | flac/wav/alac/mp3/original targets all dispatch correctly | OQ 2, 4 |
| T3 | py | same | tags preserved cross-format (mutagen round-trip) | Step N |
| T4 | py | `tests/test_settings.py` | new `sc_download_format` enum value rejected outside enum | Threat T1 |
| T5 | py | same | "auto" alias still accepted (back-compat) | Migration |
| T6 | js | `frontend/src/**/SettingsView.test.jsx` | dropdown change persists via api | UX |
| T7 | integration | `tests/test_sc_download_format_e2e.py` (new) | end-to-end SC download with AIFF target | full flow |

## Task Queue

- [ ] Task 1 — backend `SetReq` field + `SettingsManager` default + `_convert_to_target_format` helper extending existing `_convert_to_aiff` (S, covers Steps 1-3, tests T1-T5)
- [ ] Task 2 — wire into `SoundCloudDownloader._do_download` Step 3a (replace `_aiff_requested()` branch with full target-format switch) (S, covers Step 4, test T7)
- [ ] Task 3 — frontend Settings-Dropdown + format-badge on task card (M, covers Step 5, test T6)
- [ ] Task 4 — docs sync: `FILE_MAP.md`, `backend-index.md` if SetReq layout entry, `CHANGELOG.md` user-visible (S)

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

---

> ⛔ GATE C — user `/gate-pass` (→ `accepted_`) or `/gate-reject` (→ `rework_`).
> ↓ Stage 4 — `inprogress_`. `research-implement` builds each Task Queue item via 5 agents (Approach-Probe, Code, Standard-Review, Security-Review, Test-Coverage-Review, Doc-Sync) on a `routine/*` branch.

## PR Log

| Task | Branch | PR | CI | Std Rev | Sec Rev | Test Cov | Doc Sync | Merged |
|---|---|---|---|---|---|---|---|---|
| … | `routine/<slug>-task-N` | #… | pass/fail | pass/fail | pass/fail | pass/fail | pass/fail | YYYY-MM-DD |

## Implementation Log

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

Required by `archived/*`. Stage 4 Doc-Sync-Agent populates the checklist; user signs off (GATE D).

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

- Code (already exists, half-built): `app/soundcloud_downloader.py:_convert_to_aiff`, `_aiff_requested`
- Related research:
  - [[library-format-converter]] (active, ideagate, library-wide batch variant)
  - [[downloader-unified-multi-source]] (active, accepted, unified-downloader variant — Q11 = AIFF default)
- Supersedes: none
- Superseded by: none
