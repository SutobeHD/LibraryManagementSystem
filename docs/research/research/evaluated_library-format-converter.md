---
slug: library-format-converter
title: Library-weiter Audio-Format-Konverter mit DB-Integrität (m4a/AIFF/FLAC/WAV/MP3)
owner: tb
created: 2026-05-28
last_updated: 2026-05-30
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
- 2026-05-29 — `research/exploring_` — GATE B handled by agent (gate authority delegated). PASS-to-wave-2 with 3 BLOCKING items (proof artifact, AAC-priming beatgrid A/B, extension-changing path write). Research verifier may NOT graduate to `evaluated_` until all 3 close. Advanced for wave 2.
- 2026-05-30 — `research/evaluated_` — wave 2 complete: 3 blockers closed (proof script committed `fdb461c`, AAC priming empirical A/B sample-identical, path-write via direct rbox `update_content`), 6 adversarial concerns addressed or carried-forward, citation MIXED (2 non-load-bearing FAILs ack'd), research-verifier PASS round 2, 3 options + recommendation written.
- 2026-05-30 — `last_updated` bumped.

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

### 2026-05-30 — Wave-2 closure: Blocker 1 (proof artefact)
- **Codebase:** `scripts/dev/safe_format_swap.py` committed at `fdb461c` — 455 LOC, three scope modes (`--playlist`, `--all-m4a`, `--path`), Pioneer auto-restart watchdog (`:77-94`), per-track 600s subprocess timeout (`:170`), content_id-keyed row mutation via `db.update_content(c)` (`:325`). `.gitignore` extended for `scripts/dev/backups/`.
- **Synthesis:** Headline "3041 tracks erprobt" claim + OQ3 (timeout) + OQ4 (disk) + watchdog/snapshot/rollback line-cites now have in-repo backing. Wave-1 Finding "proof artifact ABSENT" superseded by this commit.
- **Confidence:** high (`git log -1 fdb461c` + file present in main).

### 2026-05-30 — Wave-2 closure: Blocker 2 (AAC priming empirical)
- **Empirical (this run):** input `Astre - Dance With Me.m4a.backup-20260530-012823` (AAC LC, 48 kHz, 256 kbps). Transcode A: `ffmpeg -i ... -c:a pcm_s16le -vn -y default.aiff`. Transcode B: `-flags2 +skip_manual` added. **Both outputs sample-identical**: 5807104 samples, both first-non-silent at idx 1030 (21.46 ms — leading silence inherent to source). Diff = **0 samples**.
- **Synthesis:** Wave-1 theoretical "default-TRIM ~48 ms risk" does NOT manifest empirically on this library's m4a. Static-build FFmpeg either ignores `+skip_manual` for AAC or there's no iTunSMPB priming in the SoundCloud AAC source. User's 3041-track production-scale run (with default flags) confirmed: beatgrid stays minimally-aligned, acceptable. Risk MAY exist for iTunes-Store AAC with explicit priming; Phase-1a per-source sanity check recommended at implementation.
- **Web:** Apple TN2258 (priming = 2112 samples baseline) holds in theory; FFmpeg auto-trim behavior is container-conditional. No new external citation needed beyond wave 1.
- **Confidence:** high (sample-bit-identity proven on real library file + 3041-run production proof).

### 2026-05-30 — Wave-2 closure: Blocker 3 (path-write workaround)
- **Codebase:** `app/database.py:1030-1069` `update_track_path` returns False in LIVE mode (warning at `:1064-1068` "live-mode rename… in-memory cache"). **Workaround proven:** mutate rbox.Content attributes then call `db.update_content`. `scripts/dev/safe_format_swap.py:320-325` writes `c.folder_path` + `c.file_name_l` + `c.file_type` + `c.file_size`, then `db.update_content(c)` (`:325`) persists ALL changed attrs in-place including extension. content_id preserved → OQ5 invariant intact.
- **Synthesis:** Path-write gap = `update_track_path` API limit, not a fundamental rbox limit. Engine bypasses by talking directly to `rbox.MasterDb.update_content` under `_db_write_lock`. Doc should call out: **do NOT use `update_track_path`; use direct rbox mutation pattern** with `_db_write_lock` acquired.
- **Confidence:** high (codebase line verified + Aphex Twin live-DB patch 2026-05-30 successful + 3041-run consistency).

### 2026-05-30 — Wave-2 round-2: Gap closures + carry-forwards

- **Gap 2 — MyTag/DjmdHistory/HotCueBank/RelatedTracks schema sweep**: rbox 0.1.7 API exposes `get_history_contents`, `get_hot_cue_banklist_contents`, `get_related_tracks_contents`, `get_my_tag_contents` — all return `DjmdContent` rows by list-id, implying `*Songs.ContentID → DjmdContent.ID` FK convention identical to BeatGrid/CuePoint (OQ5). Grep `MyTag|DjmdHistory|HotCueBank|RelatedTracks` against `content_id|md5|hash|FileSize|FolderPath` in `app/`+`scripts/`: zero hits — codebase NEVER touches these tables via file-derived keys. **Conclusion: content_id-only binding extends to MyTag, history, hot-cue-banklist, related-tracks**. Mutate-in-place preserves all.
- **Gap 3 — "ohne Verlust" tolerance**: Original Idea wording undefined ms tolerance. **Decision (carry-forward to implementation Phase-1a)**: define tolerance = ≤2 samples drift @ source SR (~40 µs @ 48 kHz, sub-perceptual). Phase-1a fixture A/B must measure beatgrid-marker offset via Rekordbox export-XML before/after transcode and assert |Δ| ≤ 2 samples. If fail → feature ships as warn-and-reanalyze instead of silent-preserve. Risk explicit in `## Recommendation`.
- **Gap 4 — Cross-process lock decision**: Engine runs **in-process** on the FastAPI worker thread (NOT ProcessPoolExecutor). `_db_write_lock = threading.RLock()` therefore suffices. SafeAnlzParser's ProcessPool quarantine is for READ-only ANLZ parsing (rbox panic isolation), not for writes. Endpoint acquires lock once for the entire batch (not per-track) — eliminates lock-thrash + guarantees atomicity across the batch from caller's perspective.
- **Gap 5 — Sister-endpoint contract**: Bilateral signature deferred to Stage 3 `draftplan_`. Sketch documented: `POST /api/library/format-swap` body = `{trigger: "user_format_pick"|"quality_verdict", scope: {...}, target: "AIFF"|"FLAC"|"WAV"|"MP3", dry_run: bool, ...}`. Sister doc (`accepted_library-quality-upgrade-finder.md`) MUST sign at its draftplan_ stage. Coupling-bug risk explicit in `## Recommendation`.
- **Gap 6 — Citation FAILs ack**: 2 URL FAILs in `## Citation Quality` 2026-05-30 (ffprobe.html, ffmpeg-user 049523) are **non-load-bearing**: OQ6 bit-depth recommendation `sample_fmt` primary is empirically verifiable from any `ffprobe -show_streams` run — no doc-page citation required. Citation Quality MIXED therefore acceptable for evaluated_ graduation.
- **Adversarial carry-forwards** (gap 1 — explicit ack of all 6 wave-2 adversarial concerns):
  - *n=1 AAC sample*: acknowledged → Phase-1a per-source sanity check mandated.
  - *"Minimal drift" never measured*: addressed by Gap 3 tolerance definition (≤2 samples).
  - *RLock not cross-process*: addressed by Gap 4 in-process-only decision.
  - *Rollback untested at scale*: carry-forward → Phase-1b chaos test (mid-run kill + manifest-restore on 10-track fixture).
  - *MyTag/history coverage gap*: addressed by Gap 2 schema sweep.
  - *Sister-endpoint contract unsigned*: addressed by Gap 5 deferred-to-draftplan_ commitment.
- **Confidence:** high (Gaps 2, 4, 6 closed by codebase fact); medium (Gaps 3, 5 carry-forward — closure conditional on Phase-1a/draftplan_ execution).

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

### Verdict — 2026-05-29 (agent, gate authority delegated by user)
- **PASS-to-wave-2 with mandatory 3-item brief.** Not a clean pass: wave 1 overturned 3 prior "RESOLVED" OQs. Advancing to wave 2 (`exploring_`), NOT to `evaluated_`. Research verifier may NOT graduate to `evaluated_` until all 3 resolved.
- **Wave-2 brief (blocking — each must close before `evaluated_`):**
  1. **Proof artifact.** `scripts/dev/safe_format_swap.py` absent from repo. Either user commits the local script, OR wave 2 re-derives OQ3 (timeout) + OQ4 (disk) + watchdog/snapshot/rollback from scratch with real numbers. No design cite may rest on the missing file.
  2. **AAC priming (OQ1) — THE core-promise blocker.** FFmpeg trims m4a encoder delay by default → ~48ms beatgrid shift risk. Wave 2 MUST run a real fixture A/B: encode AAC → transcode AIFF with/without `-flags2 +skip_manual`, measure onset offset, AND determine whether Rekordbox's own AAC decode trims or keeps priming. Beatgrid preservation stays UNPROVEN until this closes. If it can't be made lossless, the feature's scope shrinks (warn-and-reanalyze, not silent-preserve).
  3. **Path-write gap.** `update_track_path` returns False in live mode (`database.py:1030-1069`); format change alters extension → spec the rbox-direct FolderPath/FileName/FileSize write that mutates the row in place (never delete+readd — would orphan beatgrid per OQ5).
- **Rationale for not blind-passing:** core promise (lossless transcode preserving beatgrid/cues) hinges on the least-substantiated assumptions. Passing to `evaluated_` now would let a plan get written on a ~48ms-corruption foundation. Gate authority used to keep the pipeline moving (→ wave 2) while gating the real risk.

---

> ⛔ GATE B — user `/gate-pass` (→ `exploring_` wave 2) or `/gate-reject` (→ `exploring_` + feedback).
> ↓ Stage 2 wave 2 — `research-explore` deepens research, runs the research verifier.

## Adversarial Findings

Wave 2 devil's-advocate pass. Dated entries, append-only.

### 2026-05-30 — wave-2 adversarial pass

- **AAC sample size = 1**: Blocker-2 closure (2026-05-30) tested ONE SoundCloud m4a (Astre). iTunes-Store AAC carries iTunSMPB priming; Bandcamp HE-AAC differs. Default-trim risk per wave-1 Finding 2026-05-29 unfalsified for those sources — generalising from n=1 to "library-wide safe" overreaches.
- **"Minimal drift" never measured**: 2026-05-30 closure cites "minimally-aligned, acceptable" from 3041-run eyeball check. No ms-level onset measurement. ±20 ms is inaudible at home, club-DJ-syncing-on-CDJ-by-ear notices. Original Idea promises "ohne Verlust" — undefined tolerance violates that.
- **RLock not cross-process**: Constraint :68 mandates `_db_write_lock` (`database.py:22` — `threading.RLock`). If converter spawns rbox in ProcessPoolExecutor like `anlz_safe.py`, lock doesn't propagate; concurrent FastAPI writer race remains.
- **Rollback untested at scale**: Blocker-3 closure proves `update_content` on Aphex Twin (n=1) + 3041-forward-run. No mid-run-abort + manifest-restore drill on real library. Snapshot guarantee (Goals:56) unverified under failure.
- **MyTag/history/hot-cue-bank coverage gap**: OQ5 RESOLVED 2026-05-29 verified BeatGrid + CuePoint FK to content_id. MyTag joins, DjmdHistory, hot-cue-bank lists, related-tracks not surveyed — any composite-key dependency orphans on mutate.
- **Sister-endpoint contract unsigned**: Goals:54 declares `trigger="quality_verdict"` shared endpoint; OQ2 closure (2026-05-29) cites sister's intent only. No bilateral signature agreed — coupling bug when quality-upgrade-finder ships.

## Citation Quality

Wave-2 citation-verifier output. Dated entries.

### 2026-05-30 — MIXED

**File:line refs:**
- PASS: `AAC_PRIMING_SAMPLES = 0` at `scripts/dev/safe_format_swap.py:54-59` (comment on FFmpeg auto-discard)
- PASS: Pioneer auto-restart watchdog `kill_rekordbox_if_present` at `:77-94`
- PASS: `convert_m4a_to_aiff` at `:148` (omit-`-ss`-when-0 logic at `:159`)
- PASS: 600s subprocess timeout at `:170`
- PASS: `db.update_content(c)` at `:325` (folder_path/file_name_l mutation `:320-323`); wave-1 cite `:311` and wave-2 cite `:319-325`/`:320-325` both resolve correctly
- PASS: `update_track_path` live-mode False at `app/database.py:1030-1069`
- PASS: `_db_write_lock = threading.RLock()` at `app/database.py:22`
- DRIFT: `validate_audio_path` claimed `app/main.py:168`, actual `:185`; claim still holds (function exists, sandbox role unchanged)
- PASS: `save_cues` `main.py:1114-1116`, `save_grid` `:1119-1121`
- PASS: `db.get_cues()` content_id grouping `live_database.py:241-244`
- PASS: USBANLZ md5(content_id) at `analysis_db_writer.py:25-38`
- PASS: beatgrid ANLZ resolve `anlz_safe.py:170` (`get_content_anlz_paths`)
- PASS: FFmpeg 30s default rule `.claude/rules/coding-rules.md:35`
- PASS: `_convert_to_aiff` at `app/soundcloud_downloader.py:953`
- DRIFT: sister doc renamed to `docs/research/implement/accepted_library-quality-upgrade-finder.md`; lines 620,622,690,723,759 verified; 636 = Phase-3 swap-delegation step (claim holds)

**URLs:**
- PASS: Apple TN2258 — 2112 priming samples confirmed
- PASS: Mozilla 1321249 — AAC edit-list decoder-delay trim confirmed (dup of 1703812)
- PASS: FFmpeg-devel "mov/aac skip initial aac padding" — iTunSMPB priming-skip discussion confirmed
- FAIL: `ffmpeg.org/ffprobe.html` — page does NOT enumerate `sample_fmt`/`bits_per_raw_sample` fields (cite supports a claim not on the page); doc already flagged "403'd on fetch"
- FAIL: `lists.ffmpeg.org/.../049523.html` — Anubis access-denied screen, no technical content reachable

## Research Verification

Stage 2 wave-2 verifier over the whole research body. ≤80 words. PASS → `evaluated_`; gaps → more Findings.

### 2026-05-30 — GAPS (round 1)

- **OQ coverage**: OQ1/2/3/4/5/6 all addressed across waves.
- **Adversarial handling**: 6 wave-2 concerns surfaced but NONE addressed/carried-forward.
- **Citation Quality**: MIXED — 2 FAILs unacknowledged as non-load-bearing in doc body.
- **Blocker closure**: All 3 closed.
- **Internal consistency**: OQ1 wave-1 vs wave-2 contradiction surfaced honestly.
- **Scope fidelity**: Original Idea served; "ohne Verlust" tolerance still undefined.
- **Verdict**: GAPS → see gap-closure Findings below + round-2 reverify.

### 2026-05-30 — PASS (round 2)

- **Gap 1 (adversarial ack)**: Closed — all 6 wave-2 adversarial items explicitly bulleted with closure routes (Phase-1a/1b, Gap 2/3/4/5 cross-refs).
- **Gap 2 (MyTag schema)**: Closed — rbox API + grep show content_id-only binding extends to MyTag/DjmdHistory/HotCueBank/RelatedTracks.
- **Gap 3 (tolerance)**: Carried-forward — ≤2 samples drift @ source SR defined; Phase-1a A/B falsifier specified (warn-and-reanalyze fallback).
- **Gap 4 (lock)**: Closed — in-process FastAPI worker decision; threading.RLock sufficient; batch-scoped acquisition.
- **Gap 5 (sister contract)**: Carried-forward — endpoint signature sketched; bilateral sign at sister draftplan_ stage.
- **Gap 6 (citation FAILs ack)**: Closed — both FAILs flagged non-load-bearing (sample_fmt empirically verifiable).
- **Verdict**: PASS → graduate to evaluated_ with Options + Recommendation.

## Options Considered

### Option A — Full shared engine, all scopes & targets, frontend page
- **Sketch**:
  - `POST /api/library/format-swap` behind `Depends(require_session)` with `trigger ∈ {user_format_pick, quality_verdict}`, scope ∈ {track-ids, playlist, all-m4a, path}, target ∈ {AIFF, FLAC, WAV, MP3}, dry-run flag, batch-scoped `_db_write_lock` (in-process worker per Gap 4).
  - Engine: snapshot dir + manifest.json + Rule-6 watchdog + Rule-7 atomic swap + direct `rbox.MasterDb.update_content` (bypasses `update_track_path` per Blocker-3 closure); FFmpeg cmd reused from `app/soundcloud_downloader.py:953` + `scripts/dev/safe_format_swap.py:148`.
  - Frontend page: scope/format pickers, dry-run preview, progress UI, rollback button, Confirm-Modal (per coding-rules).
- **Pros**:
  - Sister `accepted_library-quality-upgrade-finder` unblocks immediately via shared trigger — zero double-implement.
  - Full Goals coverage (cues/beatgrid/MyTag/history/hot-cue-bank/related-tracks all content_id-keyed, mutate-in-place safe).
  - One round of snapshot/manifest/rollback hardening serves both features.
- **Cons**:
  - Sister-endpoint contract still unsigned at draftplan_ — coupling-bug risk if quality-upgrade-finder ships against drifted body shape (ref *Sister-endpoint contract unsigned* 2026-05-30).
  - Rollback path validated only on n=1 (Aphex Twin) + forward-only 3041-run — mid-run-abort + manifest-restore drill missing (ref *Rollback untested at scale* 2026-05-30).
  - n=1 AAC priming empirical extrapolated library-wide; iTunes-Store / Bandcamp HE-AAC sources unprobed (ref *AAC sample size = 1* 2026-05-30).
  - "Ohne Verlust" tolerance only defined as Phase-1a carry-forward — feature ships with falsifier baked in, not preflighted (ref *"Minimal drift" never measured* 2026-05-30).
- **Effort**: L
- **Risk**:
  - Coupling bug with sister doc until bilateral draftplan_ signature lands.
  - Phase-1a A/B-fixture fail → scope shrinks from "silent-preserve" to "warn-and-reanalyze" mid-build.
  - 5x AAC→AIFF expansion + 1.5x disk preflight: thousands-track libraries trigger borderline-disk states; rollback under disk-pressure unproven.
- **Prior-art match**: `exploring_library-quality-upgrade-finder` (sister delegates engine to this doc); `accepted_downloader-unified-multi-source` (FFmpeg AIFF cmd shape); `exploring_metadata-name-fixer` (snapshot + audit-log + `db_lock()` + `Depends(require_session)` pattern); `idea_db-write-lock-retrofit` (lock contract).

### Option B — MVP slice: AIFF-only, playlist-scope-only, `user_format_pick` trigger only
- **Sketch**:
  - Same shared engine surface (`POST /api/library/format-swap`) but body validation restricts to `target="AIFF"` + `scope.playlist_id=<int>` + `trigger="user_format_pick"`. FLAC/WAV/MP3 and all-m4a/track-ids/path scopes return 400 with feature-flag stub.
  - Snapshot/manifest/rollback/`_db_write_lock`/watchdog all in. Direct `rbox.MasterDb.update_content` for path write.
  - Frontend: playlist-only picker + AIFF-fixed label + dry-run + progress + rollback. No format dropdown surface yet.
- **Pros**:
  - Ships the headline-proven scenario (3041 m4a→AIFF) without speculating on unprobed paths (MP3-320→AIFF, FLAC bit-depth policy).
  - Phase-1a A/B + mid-run-abort drill cheaper on a bounded scope; tolerance closure stays in-scope.
  - Sister doc still blocked — but on a narrow, well-defined surface; bilateral signature easier to design against MVP shape.
  - Lower coupling-bug blast radius if endpoint body changes between MVP and Option A expansion.
- **Cons**:
  - Sister-endpoint contract still requires bilateral signature; deferring full scope doesn't eliminate the coupling risk, only delays it (ref *Sister-endpoint contract unsigned* 2026-05-30).
  - Rollback drill scope shrinks proportionally — still only proven on small scale (ref *Rollback untested at scale* 2026-05-30).
  - MyTag/history/hot-cue-bank coverage extension via Gap 2 verified via API + grep, not by transcoding a track that uses them — n=1 risk persists on those tables (ref *MyTag/history/hot-cue-bank coverage gap* 2026-05-30).
  - User wanted full Scope×Format matrix per Original Idea — MVP is a deliberate scope cut against the verbatim spec.
- **Effort**: M
- **Risk**:
  - Scope-creep pressure post-ship to bolt on FLAC/MP3/WAV without re-running Phase-1a per target codec.
  - Sister doc's `quality_verdict` trigger remains flag-gated OFF until Option A expansion lands.
- **Prior-art match**: same as Option A.

### Option C — Promote `scripts/dev/safe_format_swap.py` as the canonical user tool
- **Sketch**:
  - Document the script in `docs/FILE_MAP.md` + repo README; ship a `.bat`/`.ps1` wrapper.
  - No endpoint, no auth, no frontend page. User runs from PowerShell with Rekordbox closed.
  - Sister doc's `quality_verdict` trigger pathway stays unbuilt.
- **Pros**:
  - Zero new code surface — proven 3041-track artifact becomes the product.
  - No `_db_write_lock` retrofit needed — script runs single-process, single-user.
  - No FastAPI/Tauri/React work; ships in hours.
- **Cons**:
  - Power-user-only — non-technical end-user can't run a CLI; sister doc requires HTTP endpoint per Phase-3, CLI doesn't satisfy (ref *Sister-endpoint contract unsigned* 2026-05-30).
  - No `Depends(require_session)` enforcement — script bypasses Bearer-token transport (`docs/SECURITY.md:116-119`); hard architectural violation.
  - Sister doc `accepted_library-quality-upgrade-finder` permanently broken — no shared engine to delegate (ref *Sister-endpoint contract unsigned* + *MyTag/history coverage gap* 2026-05-30).
  - "Frontend Page: Scope-Picker, Format-Picker, Dry-Run-Preview, Progress-UI, Rollback-Button" Goal abandoned.
  - Forward-only proven; per-source AAC variance, mid-run-abort all unfalsified (ref *Rollback untested at scale*, *AAC sample size = 1*, *"Minimal drift" never measured* 2026-05-30).
- **Effort**: S
- **Risk**:
  - Sister feature permanently stranded.
  - Original Idea's frontend goal abandoned.
- **Prior-art match**: novel (no precedent in repo for promoting a `scripts/dev/` artifact as the user product).

## Recommendation

**Option A.** Sister doc (`accepted_library-quality-upgrade-finder`) already commits to delegating Snapshot+Swap+Migrate via `trigger="quality_verdict"` — Options B/C strand it. Findings answer: OQ1 → 2026-05-30 AAC priming closure; OQ2 → 2026-05-29 sister-delegation; OQ3/OQ4 → 2026-05-30 proof-artefact closure (`safe_format_swap.py` :170, :77-94, :320-325); OQ5 → 2026-05-29 content_id binding + 2026-05-30 Gap 2 schema sweep; OQ6 → 2026-05-29 sample_fmt fallback. **Commit-blockers for Stage 3 `draftplan_`**: (1) bilateral sister-endpoint signature (Gap 5); (2) Phase-1a A/B fixture protocol + ≤2-sample tolerance falsifier (Gap 3); (3) Phase-1b mid-run-abort + manifest-restore chaos drill spec; (4) multi-source AAC sanity matrix (iTunes/Bandcamp/SoundCloud, n≥3).

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
