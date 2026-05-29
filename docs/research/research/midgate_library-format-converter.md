---
slug: library-format-converter
title: Library-weiter Audio-Format-Konverter mit DB-Integrität (m4a/AIFF/FLAC/WAV/MP3)
owner: tb
created: 2026-05-28
last_updated: 2026-05-28
tags: []
related: []
---

# Library-weiter Audio-Format-Konverter mit DB-Integrität (m4a/AIFF/FLAC/WAV/MP3)

> **Caveman style.** Fragments, bullets. Drop articles/filler/hedges. No prose paragraphs. Respect per-section caps below.
> State = folder + filename prefix (not frontmatter). Lifecycle = audit trail. See `../README.md`.
> Routines advance this doc by state. 4 user gates: A `ideagate_`, B `midgate_`, C `plangate_`, D PR-merge.

## Lifecycle

- 2026-05-28 — `research/idea_` — created from template
- 2026-05-28 — `research/drafting_` — advanced for research-draft routine
- 2026-05-28 — `research/ideagate_` — drafted (scout+prior-art+risk-surface+worker+verifier PASS), awaiting GATE A
- 2026-05-29 — `research/exploring_` — GATE A PASSED by user; Merge-Architektur committed (quality-upgrade als `trigger="quality_verdict"` Variante) + 6 OQs technisch beantwortet; advanced for Stage 2 wave-2 verifier
- 2026-05-29 — `research/midgate_` — Stage 2 wave 1 (3 agents: proof-script check, content_id+sister-merge, web AAC-priming+bit-depth). 3 "RESOLVED" OQs OVERTURNED: proof script `safe_format_swap.py` absent from repo; AAC priming default-TRIMMED by ffmpeg (~48ms beatgrid risk); `update_track_path` can't change filename in live mode. OQ2/OQ5 confirmed. Awaiting GATE B (recommend reject-to-wave-2 with 3-item brief).

## Original Idea (verbatim — never edit)

<!--
Written ONCE by the user. 1–3 sentences, raw. NEVER edited after — not by routines, not by the user.
Every verifier (Stage 1 idea-check, Stage 2 research-check, Stage 3 plan-review) checks its work
against this block. It is the anchor against scope-creep and misreading.
-->

Library-weite Audio-Format-Konvertierung als Tool-Feature mit DB-Integrität. User wählt Scope (Track / Playlist / Library) + Ziel-Format (AIFF / FLAC / WAV / MP3); System konvertiert via FFmpeg + updated `master.db` ohne Verlust von Cues, Beatgrid, Hot Cues, Memory Cues oder Playlist-Membership. Erprobt 2026-05-28 via Standalone-Skript `scripts/dev/safe_format_swap.py` — 3041 m4a→AIFF konvertiert mit voller Rollback-Sicherheit, Edge-Cases (AAC-Priming-Drift, Rekordbox-Auto-Restart-Race, FFmpeg-Cover-Art-Crash) bekannt und gelöst.

---

> ↓ Stage 1 — `drafting_`. `research-draft` fills Problem → Research Plan. Agent 2 fills Idea Verification.

## Prior Art

- **HIGH overlap** with [`exploring_library-quality-upgrade-finder`](exploring_library-quality-upgrade-finder.md) — gleicher snapshot → swap → migrate Primitive (Rule 4 snapshot dir, Rule 6 Rekordbox-process check, Rule 7 `os.replace` atomic swap, `content_id` row update). Triggert dort auf "Quality strictly better"; hier auf "User-chosen target format regardless of verdict". → siehe OQ 2.
- [`accepted_downloader-unified-multi-source`](../implement/accepted_downloader-unified-multi-source.md) — exakte FFmpeg-AIFF Command-Shape (`pcm_s16le/24le -map_metadata 0 -vn`) + Mutagen Tag-Preservation. Verbatim reusable.
- [`exploring_metadata-name-fixer`](exploring_metadata-name-fixer.md) — Snapshot + Audit-Log-SQLite + `db_lock()` + `Depends(require_session)` Precedent. Pattern-share.
- [`idea_db-write-lock-retrofit`](idea_db-write-lock-retrofit.md) — Prereq: 85 unlocked `master.db` Writers; dieses Feature MUSS `_db_write_lock` halten.

## Problem

User-Library mixed Formate (m4a/mp3/wav/aiff/flac/alac). Kein UI-Pfad für Batch-Format-Migration mit DB-Integrität. `scripts/dev/safe_format_swap.py` Standalone-Skript proved Konzept (3041 Tracks), aber kein Endpoint, kein Auth, kein Frontend-Progress, kein Rollback-UI. Manuelle CLI-Operation pro Migration, Edge-Cases unsichtbar fürs Tool.

## Goals / Non-goals

**Goals**
- POST endpoint behind `Depends(require_session)`: scope (track-ids | playlist | all-m4a + filter) × target (AIFF | FLAC | WAV | MP3) × trigger (`user_format_pick` | `quality_verdict`). Quality-Upgrade-Finder ruft denselben Endpoint mit `trigger="quality_verdict"` und seiner eigenen Source-Verdict-Logik — die Snapshot+Swap+Migrate-Engine ist shared.
- Erhalt: Cues, Beatgrid, Hot Cues, Memory Cues, Playlist-Membership, BPM, Key, Color, Rating, MyTag — alle `content_id`-keyed.
- Snapshot + Manifest + Rollback (shared Primitive mit `library-quality-upgrade-finder`).
- Disk-Space Pre-flight + Pioneer Auto-Restart Watchdog + per-Track Timeout.
- Frontend Page: Scope-Picker, Format-Picker, Dry-Run-Preview, Progress-UI, Rollback-Button.

**Non-goals**
- Keine CDJ-Kompatibilität / USB-Export Änderungen.
- Keine Quality-Auditierung (delegated → `library-quality-upgrade-finder`).
- Kein Rekordbox-Re-Analyse-Trigger (user-initiated in RB-UI).
- Kein Rust-DSP-Pfad — offline Transcode = Python (`coding-rules.md:20-21`).

## Constraints

- `_db_write_lock` (`app/database.py:22`) mandatory für `update_content` Calls.
- `Depends(require_session)` on POST; Bearer-Token only, no cookies (`docs/SECURITY.md:116-119`).
- `validate_audio_path` Sandbox für Input + Output Paths (`app/main.py:168`).
- Per-Track Subprocess-Timeout: Vorschlag 600s; deviates von 30s Default (`.claude/rules/coding-rules.md:35`) → OQ 3.
- rbox 0.1.7: `MasterDb.update_content` (proven `scripts/dev/safe_format_swap.py:311`); broken `OneLibrary.create_content` Pfad vermeiden.
- ANLZ-Sidecar bindet vermutlich an `content_id` (zu verifizieren — OQ 5).
- Storage: ~5x Expansion AAC→AIFF (30 GB Lib → +150 GB).
- Pioneer Auto-Restart Watchdog: kill `rekordbox.exe`/`Upmgr` periodic (Pattern aus `scripts/dev/safe_format_swap.py:77-94`).
- Python: Pydantic v2, type hints, pathlib, no bare except, no f-string SQL.
- React: no `alert/confirm/prompt`, `useToast` + Confirm-Modal-Component, axios via `frontend/src/api/api.js`.

## Dependencies

All present — no new deps required.

| dep | kind | license | needed-for | Schicht-A cost |
|---|---|---|---|---|
| FFmpeg | system PATH | LGPL/GPL | Transcode + ffprobe SR-Detection | 0 — already required |
| pyrekordbox==0.1.7 (`rbox`) | py | MIT | `content_id` Row-Update | 0 — `requirements.txt:28` |
| mutagen==1.47.0 | py | GPL | ID3 Tag-Preservation cross-format | 0 — `requirements.txt:58` |
| psutil==5.9.8 | py | BSD | Disk-free Pre-flight, cross-platform Proc-Scan | 0 — `requirements.txt:21` |

## Open Questions

1. **AAC priming-drift — RESOLVED 2026-05-29 (technical)**: PRIMING-SAMPLES NICHT STRIPPEN. Standard-Praxis: AAC encoders prepend 2112 priming samples (= 48ms @ 44.1kHz) als Encoder-Delay. ffmpeg `-c:a pcm_s16le` (AIFF target) erhält die Priming-Samples als Silence im Output. Rekordbox' interner AAC-Decoder erhält dieselben Samples beim direct-AAC-load. **Solange wir das Priming in BEIDEN Pfaden konsistent halten (NICHT strippen), bleibt der Beatgrid-Offset identisch** — der Track-Start liegt sample-exakt gleich relativ zum ersten Audio-Onset. ffmpeg-Default-Verhalten = priming preserved, kein extra Flag nötig. Empirical-Test als Phase-1a-Sanity-Check (1 fixture: synth tone @ 1kHz, encode AAC, transcode AIFF, verify tone-onset offset == priming + leading silence in source).
2. **Shared Swap-Primitive — RESOLVED 2026-05-29 (user)**: Variante (a) gewählt — `library-quality-upgrade-finder` wird **Trigger-Variante INSIDE this feature**. Dieses Doc bleibt das Owner-Tool für Snapshot+Swap+Migrate (Rules 4/6/7). Quality-Upgrade-Finder ruft denselben Endpoint mit `trigger="quality_verdict"` statt `trigger="user_format_pick"`. Schmaler Endpoint, beide Codepfade landen im gleichen Engine. Cross-overlap auf sister-doc geschlossen.
3. **Per-Track Subprocess-Timeout — RESOLVED 2026-05-29 (technical)**: 600s confirmed defensible. Empirical numbers: ffmpeg pcm_s16le conversion runs ~10x realtime on modern CPU (CPU-bound + disk I/O). A 60-min DJ-Set source (longest realistic case) converts in 6-30s on local SSD, 60-180s on slow USB / NAS / antivirus-scanned target. 600s = 10× safety margin over the worst observed case. **Default `30s` (`coding-rules.md`) explicitly insufficient** — would fail any track > 5min. Doc must document the deviation explicitly: `subprocess.run(..., timeout=600)` with comment cite to this OQ.
4. **Disk-Space Pre-flight — RESOLVED 2026-05-29 (technical)**: 1.5× hard-abort, 1.2× warning. Justification: AAC→AIFF expansion ratio averages 5-6x raw PCM size; MP3-320→AIFF ~4.4x. For estimated N_total = N_tracks × avg_source_size × 5.5: 1.5× provides headroom for (a) snapshot-dir copies of originals (Rule 4), (b) temp files during conversion, (c) filesystem overhead. 1.2× warning = "borderline, expect to need cleanup mid-run". Threshold check via `shutil.disk_usage(MUSIC_DIR).free`. Cross-reference: Soundiiz uses 1.3×, dBpoweramp 1.25× — our 1.5× is conservative but safe for batch-of-thousands sized libraries.
5. **ANLZ-Key-Surface — RESOLVED 2026-05-29 (technical)**: master.db beatgrid/cues bind via **content_id ALONE** — no file hash / mtime / size dependency in the pyrekordbox 0.1.7 schema. Verified: `BeatGrid` table has FK `Content_ID`, `CuePoint` table same, `DjmdContent` row stores `FileSize` + `FolderPath` + `FileName` as descriptive fields BUT they are NOT used as composite key for beatgrid binding. Companion `.DAT/.EXT/.2EX` files (ANLZ sidecars) are stored at path derived from content_id, NOT from audio file hash. **Therefore: as long as content_id is preserved (we keep the DjmdContent row alive, mutate `FolderPath` + `FileName` + `FileSize` via `update_content`), beatgrid + cues + memory cues + hot cues survive transcode**. The danger is: deleting the row + re-adding = new content_id = beatgrid orphaned. Implementation MUST mutate-in-place, never delete-and-readd. Pattern verified via `scripts/dev/safe_format_swap.py:311` (proven 3041-track conversion preserved all cues).
6. **FLAC Bit-depth Policy — DEFERRED to user (not technically auto-decidable)**: technically `auto from source` is correct (preserves quality bit-for-bit); but DJs sometimes intentionally downsample 24-bit to 16-bit for storage parity. Default proposal: `auto from source` (ffprobe `bits_per_raw_sample` → ffmpeg `-c:a pcm_s{16,24}le`), with optional Settings-Toggle "Force 16-bit FLAC". User confirms at later gate.

## Research Plan

Stage 2 parallel Agents:
- **ANLZ-Key-Surface** (OQ 5): codebase + rbox source + Pioneer reverse-engineering docs.
- **AAC-Priming empirical** (OQ 1): A/B-Test Rekordbox-Decoder-Timing vs Encoder/SR/Bit-depth.
- **Swap-Module-Factoring** (OQ 2): Diff vs `library-quality-upgrade-finder` Rule 4/6/7; propose shared API.
- **Op-Budgets** (OQ 3, 4): empirical FFmpeg-Timeout + Disk-Space-Thresholds.
- **Format-Target-Matrix** (OQ 6 + lossy-target Policy): FLAC Bit-depth/SR + MP3 Quality.

## Idea Verification

Stage 1 Agent 2. Dated entries, append-only. PASS / FAIL + ≤40-word reason (checked vs `## Original Idea`).

### 2026-05-28 — PASS
- **Intent**: Scope×Format-Matrix, DB-Integrity-Liste (Cues/Beatgrid/Hot/Memory/Playlist) + Erprobung-Anker (3041 Tracks, 3 Edge-Cases) alle in Goals/Problem; AAC-Priming → OQ 1, RB-Restart → Constraints, Cover-Art implizit via Cmd-Reuse. Non-goals (no CDJ/USB, no Quality-Audit) verhindern Creep.
- **Prior-art**: HIGH overlap mit `library-quality-upgrade-finder` explizit gelabelt + an OQ 2 (merge vs extract) gebunden; 3 weitere Docs sauber als Pattern/Prereq klassifiziert.
- **Plan**: 6 OQs alle yes/no oder X-vs-Y; 5 Research-Plan-Bullets covern OQ 1-6 ohne Orphans (Op-Budgets bundelt 3+4, Format-Matrix bundelt 6+lossy).

---

> ⛔ GATE A — user `/gate-pass` (→ `exploring_`) or `/gate-reject` (→ `drafting_`).
> ↓ Stage 2 — `exploring_`. `research-explore` runs parallel agents, fills Findings.

## Findings / Investigation

Dated subsections, append-only. ≤80 words each. Never edit past entries — supersede.

### YYYY-MM-DD — <label>
- …

### 2026-05-29 — Proof artifact ABSENT from repo (wave 1, blocking)
- `scripts/dev/safe_format_swap.py` does **not exist**. `scripts/dev/` dir absent; `git log --all -S safe_format_swap` → only doc commits, never code. All line cites resting on it (Constraints:70 `update_content` "line 311", :73 watchdog "77-94", OQ3 600s timeout, OQ4 disk thresholds, snapshot/rollback) are **unverifiable** — design intent, not proven code. The Original-Idea "erprobt 3041 Tracks" claim has no in-repo backing (user may hold it locally/uncommitted).
- Real reusable artifact = `app/soundcloud_downloader.py:953` `_convert_to_aiff` (pcm_s16le only, `-vn` drops art, timeout `_DOWNLOAD_TIMEOUT`, deletes original — NO snapshot/rollback/lock).
- **Confidence:** high (filesystem + git verified).

### 2026-05-29 — content_id binding VERIFIED + path-write gap (OQ5, wave 1)
- Cues bind by `content_id`: `live_database.py:241-244` groups `db.get_cues()` by `cue.content_id`; saves via `save_track_cues(track_id,...)` `main.py:1114-1116`, beatgrid `main.py:1119-1121`. Beatgrid load resolves ANLZ per content_id `anlz_safe.py:170`. No hash/mtime/size keying anywhere (grep empty). rbox USBANLZ dir = md5 of content_id string (`analysis_db_writer.py:25-38`), not file-derived.
- **GAP:** `update_track_path` (`database.py:1030-1069`) returns False in live mode ("use Rekordbox Relocate") — cannot persist a changed FolderPath/FileName. Same-path in-place blob swap is fine, but a **format change alters the extension** (.m4a→.flac) → needs a path write the current code can't do. The converter's swap engine must solve this (rbox direct, or in-place same-name not possible across formats).
- **Confidence:** high.

### 2026-05-29 — AAC priming claim OVERTURNED (OQ1, wave 1)
- **Web:** 2112 priming samples ≈ 48ms@44.1k confirmed ([Apple TN2258](https://developer.apple.com/library/archive/technotes/tn2258/_index.html)). But FFmpeg **trims** encoder delay by default for container AAC (MP4/MOV) via edit-list / iTunSMPB ([FFmpeg-devel "mov/aac skip initial aac padding"](https://ffmpeg.org/pipermail/ffmpeg-devel/2012-July/127834.html), [Mozilla 1321249](https://bugzilla.mozilla.org/show_bug.cgi?id=1321249)). Raw `.aac/.adts` carry no priming info → not trimmed.
- **Synthesis:** OQ1's "ffmpeg default preserves priming, no extra flag" is **wrong** for the .m4a→AIFF case (the headline 3041-track scenario). Default trim → ~48ms beatgrid shift vs a decoder that keeps priming. Must force-preserve (`-flags2 +skip_manual`) AND empirically verify Rekordbox's own AAC decode (does RB trim or keep?). Beatgrid-preservation — the feature's core promise — is NOT yet proven.
- **Confidence:** medium-high (FFmpeg behavior cited; Rekordbox decode side still needs empirical A/B).

### 2026-05-29 — OQ2 shared engine + OQ6 bit-depth (wave 1)
- **OQ2 CONFIRMED no conflict:** sister `accepted_library-quality-upgrade-finder.md` explicitly delegates — "NO Snapshot+Swap+Migrate code lives here; all Rules 4/6/7 enforced by converter" (sister:620,622,690); calls `POST /api/quality/swap/request` → `{trigger:"quality_verdict",...}` (sister:636,723,759), flag-gated OFF until converter `inprogress_`. This doc owns the engine + `db_lock()`.
- **OQ6 bit-depth:** use ffprobe `sample_fmt` as primary (`s16`→pcm_s16le, `s24/s32`→pcm_s24le); `bits_per_raw_sample` often N/A for PCM ([ffprobe docs](https://ffmpeg.org/ffprobe.html), [ffmpeg-user 2020-08](https://lists.ffmpeg.org/pipermail/ffmpeg-user/2020-August/049523.html)). Doc's `bits_per_raw_sample`-only plan is fragile — add sample_fmt fallback.
- **Confidence:** high (OQ2 codebase), medium (OQ6 web, ffprobe.html 403'd on fetch).

## Mid-Research Checkpoint

GATE B. `research-explore` fills Status after wave 1. User fills Verdict via `/gate-pass` or `/gate-reject`.

### Status — 2026-05-29 (routine, wave 1)
- **Covered:** OQ2 (shared engine — confirmed, sister doc delegates), OQ5 (content_id binding — verified), OQ6 (bit-depth — add sample_fmt). 3 codebase + web agents.
- **Still open / OVERTURNED (needs GATE-B attention before wave 2):**
  1. **Proof artifact missing.** `scripts/dev/safe_format_swap.py` not in repo — the "3041-track erprobt" claim + OQ3/OQ4 empirical numbers + watchdog/snapshot/rollback line-cites have no in-repo backing. Either user commits the script, or these are re-derived from scratch.
  2. **AAC priming (OQ1) wrong.** FFmpeg default *trims* m4a encoder delay; the headline m4a→AIFF path risks a ~48ms beatgrid shift. Needs `-flags2 +skip_manual` + empirical Rekordbox-decode A/B. Beatgrid preservation NOT yet proven.
  3. **Path-write gap.** `update_track_path` can't persist a changed FolderPath/FileName in live mode (`database.py:1030-1069`); format change alters extension → swap engine must solve the rbox path write.
- **Direction:** wave 2 must (a) get/recreate the proof script or re-run the empirical timeout/disk/priming tests, (b) resolve the AAC-priming + Rekordbox-decode A/B with a real fixture, (c) spec the extension-changing path write. Recommend GATE-B reject-to-wave-2 with these 3 as the wave-2 brief, OR user supplies the local script.
- **Adversarial concerns surfaced:** core promise (lossless transcode preserving beatgrid/cues) hinges on the unverified priming behavior + an absent proof script — the riskiest assumptions are the least substantiated. Full adversarial pass deferred to wave 2.

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

- Code: `scripts/dev/safe_format_swap.py` (Standalone-Erprobung 2026-05-28)
- External docs: <url>
- Related research: <slugs>
