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
- 2026-05-31 — `implement/draftplan_` — planning started (research-plan routine)

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

> ↓ Stage 3 — `implement/draftplan_`. `research-plan` fills Implementation Plan + specialists + Task Queue. Reviewer fills Review.

## Implementation Plan

### Scope

**In:**
- New engine module `app/format_converter.py` — snapshot dir + `manifest.json` + Pioneer auto-restart watchdog + atomic swap + direct `rbox.MasterDb.update_content` under batch-scoped `_db_write_lock`.
- `POST /api/library/format-swap` (`Depends(require_session)`), body `{trigger, scope, target, dry_run, options}`. Returns `task_id`.
- Targets: AIFF (pcm_s16le / pcm_s24le auto), FLAC (bit-depth auto via ffprobe `sample_fmt`), WAV (pcm_s16le/24le), MP3 (`-q:a`).
- Scopes: `track_ids`, `playlist_id`, `all_m4a`, `path` (mirrors `safe_format_swap.py:175-212`).
- ffprobe bit-depth + sample-rate detect; disk-space preflight (1.5× abort / 1.2× warn); per-track 600s subprocess timeout.
- Dry-run plan (counts, size forecast, per-track preview) — no writes.
- Progress polling via in-memory tracker + `GET /api/library/format-swap/status/{task_id}`.
- Rollback: `POST /api/library/format-swap/rollback` `{manifest_id}`.
- Frontend page `FormatConverterView.jsx`: scope picker, format picker, dry-run preview, progress UI, rollback button (ConfirmModal + `useToast`).
- Sister hook: `quality-upgrade-finder`'s `/api/quality/swap/request` proxies into this engine with `trigger="quality_verdict"`.

**Out (per Non-goals):**
- No CDJ/USB-export changes. No quality auditing (delegated to sister). No Rekordbox re-analyze trigger. No Rust DSP — transcode stays Python (`coding-rules.md:20-21`).
- No `update_track_path` use — returns False in live mode (`database.py:1030-1069`).

### Step-by-step

1. **Engine module `app/format_converter.py`** — port `scripts/dev/safe_format_swap.py` into class `FormatSwapEngine`. Reuse verbatim: watchdog `kill_rekordbox_if_present` (`:77-94`), `backup_master_db` (`:97-107`), per-track row mutation + persist `c.folder_path/file_name_l/file_type/file_size` → `db.update_content(c)` (`:320-325`), per-track DB-fail individual rollback (`:326-348`), atomic manifest writes (`:273-278`). Replace `print` → `logger.info("op=… …")`; `input()` confirm → dry-run/explicit-confirm body flag; `sys.exit` → raised `FormatSwapError`. Use shared `db` singleton's live `MasterDb` connection (`live_database.py:41`) — do NOT open a second `rbox.MasterDb`.
2. **Lock (Gap 4 in-process decision):** acquire `app.database._db_write_lock` (`database.py:22`) ONCE for the whole batch via `with db_lock():`. Engine runs in-process on a daemon `threading.Thread` (NOT ProcessPoolExecutor) — `threading.RLock` propagates. Pre-flight `_is_rekordbox_running()` (`main.py:3164`) → 409 if true; watchdog kills re-launches every 50 tracks (`:290`).
3. **FFmpeg transcode — per-target codec args.** Base cmd from `soundcloud_downloader.py:953` + `safe_format_swap.py:148-172` (`-hide_banner -loglevel error -i SRC -vn -map_metadata 0 -ar <src_sr> -y DST`). `FFMPEG_BIN` from `app/config.py:6`. Per target: **AIFF/WAV** `-c:a pcm_s16le|pcm_s24le` (bit-depth step 4), `-ar` locked to source SR (no resample → no cue drift); **FLAC** `-c:a flac -sample_fmt s16|s32`; **MP3** `-c:a libmp3lame -q:a 0` (`options.mp3_quality` override) `-write_id3v2 1`; **AAC priming (OQ1)** default flags only — empirical A/B (Findings 2026-05-30) sample-identical, keep `AAC_PRIMING_SAMPLES=0` + comment cite. Mutagen tag re-write post-convert (cover dropped by `-vn`; RB artwork cache content_id-keyed, `analysis_db_writer.py:25-38`).
4. **ffprobe bit-depth detect** (`probe_bit_depth`): `ffprobe -select_streams a:0 -show_entries stream=sample_fmt,bits_per_raw_sample -of csv` — primary `sample_fmt` (`s16`→16, `s32/s24`→24), fallback `bits_per_raw_sample` (often N/A for PCM, OQ6). Reuse `probe_sample_rate` (`safe_format_swap.py:133-145`). FLAC = auto-from-source; `options.force_16bit_flac` toggle (OQ6 deferred-to-user).
5. **Disk-space preflight (OQ4):** sum source `file_size`, est target = `sum × ratio[target]` (AIFF/WAV 5.5, FLAC 3.0, MP3 1.0). `shutil.disk_usage(MUSIC_DIR).free` — abort 400 if `free < 1.5×est`, warn-flag if `< 1.2×est`.
6. **Per-track 600s timeout (OQ3 — deviation from 30s default `coding-rules.md:35`):** `subprocess.run(..., timeout=600)` + inline comment citing OQ3 (10× margin over worst 60-min-set-on-slow-USB). ffprobe stays 30s.
7. **POST endpoint** `/api/library/format-swap` (pattern from `analyze_batch:3099`): `Depends(require_session)`, Pydantic v2 `FormatSwapReq`. Every resolved src+dst path through `validate_audio_path` (`main.py:185`). `dry_run=True` → synchronous plan. `dry_run=False` → register task, spawn daemon thread, return `{task_id}`. mode≠live → 400.
8. **Progress reporting** — new `app/format_swap_tracker.py` modeled on `app/import_tracker.py` (thread-safe singleton, `register/update/get`, `_MAX_KEEP` prune). `GET /api/library/format-swap/status/{task_id}` returns dict. (NDJSON streaming `analyze_batch:3124` rejected — long batch + rollback need queryable persistent task; polling matches `import_tracker` precedent.)
9. **Rollback** `POST /api/library/format-swap/rollback` `{manifest_id}` (`require_session`): port `rollback()` (`safe_format_swap.py:383-412`) — restore DB+WAL+SHM from backup, rename audio backups back, delete new files, under `db_lock()` + `_is_rekordbox_running()` 409 guard. Manifests under app-data `format_swap_backups/` (NOT `scripts/dev/backups/`).
10. **Sister-endpoint contract (commit-blocker 1, Gap 5):** bilateral signature — sister's `/api/quality/swap/request` `{track_id, candidate_id}` resolves candidate→target format, calls engine in-process with `trigger="quality_verdict"`, `scope={track_ids:[track_id]}`, `target=<candidate container>`. Shared request model in one module; sister imports it. Engine treats both triggers identically post-resolution; `trigger` logged only. Sister doc signs at its draftplan_.
11. **Phase-1a A/B fixture + ≤2-sample falsifier (commit-blocker 2, Gap 3):** synth 1kHz tone → AAC-encode → transcode each target → assert onset offset |Δ| ≤ 2 samples @ source SR. RB-export-XML beatgrid-marker compare helper. Fail → that target ships warn-and-reanalyze (`beatgrid_preserved=false`), not silent-preserve.
12. **Phase-1b mid-run-abort chaos drill (commit-blocker 3):** 10-track fixture, kill engine thread mid-run (or simulate `update_content` raise), run rollback from partial manifest — assert DB+files restored, content_ids intact.
13. **Multi-source AAC sanity matrix (commit-blocker 4):** n≥3 AAC sources (iTunes-Store w/ iTunSMPB, Bandcamp HE-AAC, SoundCloud LC) through Phase-1a falsifier. Source over tolerance → per-source warn-and-reanalyze.
14. **Frontend `FormatConverterView.jsx`:** scope picker (track-ids / playlist dropdown / all-m4a / path), format picker, Dry-Run → preview table (counts + size forecast + disk warning), Convert → ConfirmModal → poll `status/{task_id}`, progress bar, Rollback (manifest list + ConfirmModal). axios via `frontend/src/api/api.js`; `useToast`; no `alert/confirm/prompt`.

### Files touched

- `app/format_converter.py` — **new** — `FormatSwapEngine` (snapshot/manifest/watchdog/swap/rollback/transcode), ported from proven script.
- `app/format_swap_tracker.py` — **new** — thread-safe task tracker (clone of `import_tracker.py` shape).
- `app/main.py` — **edit** — 3 routes (POST swap, GET status, POST rollback) + `FormatSwapReq` model; reuses `validate_audio_path:185`, `_is_rekordbox_running:3164`, `db_lock`.
- `app/config.py` — **edit** — add `FORMAT_SWAP_BACKUP_DIR` (app-data path) if not derivable.
- `scripts/dev/safe_format_swap.py` — **read** — engine reference (do not modify; remains standalone CLI).
- `app/soundcloud_downloader.py` — **read** — `_convert_to_aiff:953` FFmpeg shape + mutagen pattern.
- `app/database.py` / `app/live_database.py` — **read** — `_db_write_lock:22`, `db_lock`, shared `MasterDb` (`live_database.py:41`); do NOT touch `update_track_path:1030`.
- `frontend/src/views/FormatConverterView.jsx` — **new** — converter page.
- `frontend/src/api/api.js` — **edit** — `formatSwap`, `formatSwapStatus`, `formatSwapRollback` helpers.
- frontend nav/router (`App.jsx`/sidebar) — **edit** — register the view.
- `tests/test_format_converter.py` — **new** — engine + endpoint + auth + disk + Phase-1a/1b cases.
- `tests/fixtures/` — **new** — synth-tone AAC + multi-source AAC fixtures.
- `docs/{architecture,FILE_MAP,backend-index,frontend-index}.md`, `CHANGELOG.md` — **edit** — graduation docs.

### Testing
- Engine unit: scope resolution, bit-depth detect, disk preflight thresholds, manifest atomicity.
- Endpoint: auth 401 (no Bearer), 409 (RB running), dry-run plan, 400 (xml mode), path-sandbox 403.
- Phase-1a: per-target ≤2-sample onset falsifier; multi-source AAC matrix (n≥3).
- Phase-1b: mid-run-abort + manifest-restore drill (10-track fixture).
- Sister: `quality_verdict` trigger reaches same engine with correct scope/target.
- Frontend: view renders pickers/progress/rollback; ConfirmModal gates convert + rollback.

### Risks & rollback
- **Coupling bug** with sister until bilateral draftplan_ signature lands (Gap 5) → shared request model in one module, sister imports it.
- **Phase-1a fail** for some AAC source → scope degrades to warn-and-reanalyze for that target/source, not full feature loss; response carries `beatgrid_preserved`.
- **Disk pressure** on thousands-track libs → 1.5× hard abort before any write; originals kept as `.backup-<ts>` (never deleted until user confirms).
- **RB auto-restart mid-run** → watchdog kill every 50 tracks + per-track DB-fail individual rollback + clean abort on persistent "Rekordbox running".
- **Rollback** = restore DB+WAL+SHM from snapshot + rename audio backups back + delete new files, from `manifest.json`; manifest written atomically + anchored before first track.

## Threat Model

### Assets
- **Rekordbox `master.db`** + WAL/SHM — beatgrid, cues, hot/memory cues, MyTag, playlist membership (content_id-keyed). Corruption = silent library loss.
- **Original audio files** — irreplaceable user masters; snapshot/manifest is sole recovery.
- **`SESSION_TOKEN`** / paired device-token (`app/auth.py`) — bearer secrets, never-log.
- **Filesystem outside `ALLOWED_AUDIO_ROOTS`** — attacker goal: read/write/overwrite arbitrary files via crafted `scope.path`, output path, or `manifest_id`.

### Trust boundaries
- HTTP body (`scope`, `target`, `options`, `manifest_id`) = **untrusted** — validate before use.
- `require_session` gate = trust boundary; only past it does engine touch DB/FS.
- `db.tracks` paths = user-trusted (Rekordbox import) per `validate_audio_path:208-217` escape-hatch.
- FFmpeg subprocess = trusted binary, **untrusted argv** (filenames from FS/DB).
- rbox `update_content` = trusted only under `_db_write_lock` held.

### Threats (STRIDE-light)

| ID | Threat | Mitigation in plan | Test covers |
|---|---|---|---|
| FS-1 | `scope.path` traverses outside sandbox (`../`, symlink, abs path) | Resolve + `is_relative_to(ALLOWED_AUDIO_ROOTS)` on dir before enumeration; `validate_audio_path:185` per resolved src; dir-scope needs its own resolve-then-`is_relative_to` check (validate_audio_path is file-only/extension-gated, won't cover a dir) | T13 |
| FS-2 | Output/dst path escapes sandbox (new ext, attacker-influenced name) | Derive dst from validated src dir only (same parent, ext swap); re-resolve + `is_relative_to` dst; never accept dst from body | T14 |
| A-1 | Missing/forged Bearer hits mutating routes | All 3 routes `Depends(require_session)` (`app/auth.py`); constant-time `safe_compare` | T15 |
| CI-1 | Command injection via crafted filename into FFmpeg | `subprocess.run([...], shell=False)` arg-list (never string); paths passed as list elements, `-i`/dst positional | T16 |
| DOS-1 | Huge batch / 5.5× expansion exhausts disk | Step 5 preflight `shutil.disk_usage().free`; 400 abort at 1.5×est before any write; per-track 600s timeout (Step 6) | T17 |
| TI-1 | Concurrent writer corrupts `master.db` (lock bypass) | `_db_write_lock` (`app/database.py:22`) acquired once batch-scoped, in-process thread (Gap 4); `_is_rekordbox_running` → 409 | T18 |
| FS-3 | Rollback `manifest_id` traversal → restore/overwrite arbitrary file | Treat `manifest_id` as opaque basename; reject path separators/`..`; resolve under fixed `FORMAT_SWAP_BACKUP_DIR` (app-data, Step 9) + `is_relative_to` | T19 |
| T-1 | Originals deleted/overwritten before snapshot | Manifest written atomically + anchored before first track (Step 9/Risks); originals kept `.backup-<ts>`, never deleted until user confirm; per-track DB-fail individual rollback | T20 |
| ID-1 | Token / full paths leak in logs | Never-log token rule (`app/auth.py`); Telemetry logs filenames+markers only, no token, no full src paths; `safe_error_message` sanitises | T21 |

### Residual risk
n=1→library-wide AAC-priming extrapolation may mis-preserve beatgrid for unprobed sources → `beatgrid_preserved=false` warn-and-reanalyze fallback, not corruption. Rollback proven small-scale only (Phase-1b drill). `validate_audio_path` db.tracks exact-match escape-hatch trusts import integrity. Disk-pressure rollback path unproven. Sister-endpoint coupling drift until bilateral signature lands.

## Migration Path

### Before → After

**DjmdContent row (today):** `content_id=<N>`, `FolderPath="D:/Music/x.m4a"`, `FileName="x.m4a"`, `FileType=4` (m4a), `FileSize=<aac bytes>`. On disk: `x.m4a`. Beatgrid/CuePoint/MyTag/History/HotCueBank/RelatedTracks all FK → `content_id` (OQ5; Gap 2 sweep).

**After swap:** SAME `content_id=<N>`. `FolderPath="D:/Music/x.aiff"`, `FileName="x.aiff"`, `FileType=<aiff code>`, `FileSize=<pcm bytes>`. On disk: `x.aiff` (new) + `x.m4a.backup-<ts>` (original kept). All content_id-keyed children untouched.

**Existing-data handling:** in-place row mutation — `c.folder_path/file_name_l/file_type/file_size` set, then `db.update_content(c)` (`safe_format_swap.py:320-325`) under batch `_db_write_lock`. NEVER delete+readd (new content_id orphans beatgrid/cues).

### Backfill / forward-compat

**No schema migration** — no new `master.db` table/column; row-level field mutation only. No backfill script.

**Old client reads:** Rekordbox reads mutated rows directly. content_id binding keeps beatgrid, cues, hot/memory cues, MyTag, playlist membership intact (OQ5 + Gap 2). RB re-reads audio at new FolderPath.

**Rollback recipe** (from `manifest.json`, ported `safe_format_swap.py:383-412`):
1. RB closed — `_is_rekordbox_running()` → 409 abort if open.
2. For each `manifest["db_backups"]` entry: `shutil.copy2(backup, orig)` — restores `master.db` + `-wal` + `-shm`.
3. For each `manifest["tracks"]`: rename `original.audio_backup` (`x.m4a.backup-<ts>`) → `original.folder_path` (`x.m4a`); `unlink` `new.folder_path` (`x.aiff`).
4. Under `db_lock()`. Manifest written atomically (tmp+replace, `:273-278`), anchored before first track — partial runs fully revertable.

### User-visible behavior during migration

**Downtime:** Rekordbox MUST be closed. Pre-flight 409 if running; watchdog kills auto-relaunched `rekordbox.exe`/`Upmgr` every 50 tracks (`:77-94`, `:290`). Library locked from RB use until run completes or rolled back.

**Progress UI:** non-blocking — `POST` returns `task_id` immediately; daemon thread converts; frontend polls `GET status/{task_id}` (Queued|Converting|Completed|Aborted|Failed, per-track counter, `beatgrid_preserved`).

**App startup:** independent — converter is a triggered batch task, not a boot dependency. App starts/runs normally before, during, after. Originals kept as `.backup-<ts>` until user confirms.

## Performance Budget

| Path | Budget | Measured today | Source |
|---|---|---|---|
| `POST .../format-swap` dry-run (sync) | p95 ≤ 1.5s for 3041 tracks | untested | estimate. Enumerate from DB + sum `file_size` (no ffprobe per track — uses `DjmdContent.FileSize` already in `master.db`). No per-track probe in dry-run → fast. |
| `POST .../format-swap` launch (`dry_run=false`) | ≤ 50ms to return `task_id` | untested | estimate. Registers task + spawns daemon thread, returns immediately. No transcode on request path. |
| `GET .../status/{task_id}` | p95 ≤ 10ms | untested | estimate. In-memory dict lookup in `format_swap_tracker` (clone of `import_tracker`). No DB, no disk. |
| Per-track transcode throughput | ≥ 10x realtime | ~10x realtime, CPU+disk-bound | OQ3 empirical (ffmpeg `pcm_s16le`). 60-min set: 6-30s SSD / 60-180s slow USB. |
| Full-batch wall-clock, 3041-track headline (m4a→AIFF) | SSD ≤ 25 min; slow USB ≤ 3.5 hr | proven complete (3041-run, `safe_format_swap.py`, wall-clock not recorded) | OQ3 extrapolation. Avg ~4-min track ≈ 0.4-2.4s SSD / 4-12s USB. ×3041 ≈ 20-120 min SSD, 3-10 hr USB. Mix-dependent. |
| Peak memory | ≤ 150 MB RSS over baseline | untested | estimate. Engine streams one ffmpeg subprocess per track; no whole-library audio in RAM. Manifest JSON + DB handle only. |

### Worst-case scenario

Input: 5000-track lib, all 60-min DJ sets, target AIFF, on antivirus-scanned slow USB.

Impact:
- Wall-clock: 5000 × 60-180s = **80-250 hr** (multi-day). Per-track 600s timeout caps any single hang.
- Disk: 5.5x expansion + `.backup-<ts>` originals kept → ~6.5x source footprint live. Preflight aborts (400) before write if `free < 1.5×est`.
- **Lock contention (key risk):** engine holds `_db_write_lock` for the WHOLE batch (Gap 4, per-batch for atomicity). Every other `master.db` writer — mytag edits, analysis writes, cue saves — **blocks for the entire run** (here days, realistically minutes-hours). Real cost, not theoretical.

Mitigation if exceeded:
- Disk preflight 1.5x hard-abort / 1.2x warn (OQ4).
- Per-track 600s subprocess timeout (OQ3).
- RB-restart watchdog every 50 tracks.
- Scope down (track_ids / playlist / path) — user controls batch size.
- Lock tradeoff: per-track lock would free writers between tracks but **breaks batch atomicity** (partial-state visible to concurrent readers, harder rollback). Plan chose per-batch deliberately (Gap 4). **Documented contention cost: long batches = long writer starvation. Recommend UI warning when batch > ~500 tracks; consider per-N-track lock release as a future option if starvation observed.**

## API / UX Surface

### Backend (FastAPI)

**new** `POST /api/library/format-swap` (`Depends(require_session)`)
```jsonc
// request
{
  "trigger": "user_format_pick",            // | "quality_verdict"
  "scope": { "track_ids": [123,456] },       // OR {"playlist_id": 42} OR {"all_m4a": true} OR {"path": "D:/Music/House"}
  "target": "AIFF",                          // AIFF | FLAC | WAV | MP3
  "dry_run": false,
  "options": { "force_16bit_flac": false, "mp3_quality": 0 }
}
// dry_run=true response
{ "status": "ok", "data": {
  "dry_run": true, "scope": "playlist 'X' (id=42)",
  "convertible": 38, "skipped": 2,
  "source_mb": 410.2, "estimated_target_mb": 2256.0,
  "disk_free_mb": 51200.0, "disk_warning": false, "disk_abort": false,
  "preview": [{ "id": 123, "name": "track.m4a" }]
}}
// dry_run=false response
{ "status": "ok", "data": { "task_id": "a1b2c3d4e5f6" } }
```

**new** `GET /api/library/format-swap/status/{task_id}` (`require_session`)
```jsonc
{ "status": "ok", "data": {
  "id": "a1b2c3d4e5f6", "status": "Converting",   // Queued|Converting|Completed|Aborted|Failed
  "progress": 62, "total": 38, "converted": 24, "failed": 1,
  "current_track": "kick.m4a", "manifest_id": "manifest-20260531-141200.json",
  "beatgrid_preserved": true, "error": null
}}
```

**new** `POST /api/library/format-swap/rollback` (`require_session`)
```jsonc
// request
{ "manifest_id": "manifest-20260531-141200.json" }
// response
{ "status": "ok", "data": { "restored_tracks": 24, "db_restored": true } }
```

**changed** `POST /api/quality/swap/request` (sister doc) — proxies `{track_id, candidate_id}` → calls engine in-process with `trigger="quality_verdict"`. Signed bilaterally here.

### Frontend (React)

- **new** `FormatConverterView.jsx` — scope picker, format picker, Dry-Run preview table (counts + size forecast + disk warning), Convert (ConfirmModal), live progress bar (polls status), Rollback (manifest list + ConfirmModal). `useToast` for all errors. No `alert/confirm/prompt`.
- **changed** `frontend/src/api/api.js` — add `formatSwap(body)`, `formatSwapStatus(taskId)`, `formatSwapRollback(manifestId)` (axios via shared `api`).
- **changed** nav/router — register the view in the Library/Tools section.

### Tauri (Rust commands)
- **none.** No new Tauri commands. All transport over existing HTTP sidecar + Bearer token. No Rust DSP path (Non-goal).

### CLI / sidecar logs
- **unchanged** `scripts/dev/safe_format_swap.py` stays as standalone power-user CLI (engine reference).
- Sidecar emits `op=format_swap.*` markers (see Telemetry). No token, no full paths beyond filenames already logged elsewhere.

## Telemetry

Log markers (`logger.info`):
- `op=format_swap.start trigger=%s scope=%s target=%s n=%d dry_run=%s`
- `op=format_swap.disk free_mb=%d est_mb=%d abort=%s warn=%s`
- `op=format_swap.track i=%d/%d id=%s sr=%d action=convert|skip|fail`
- `op=format_swap.watchdog killed_rekordbox=true`
- `op=format_swap.done converted=%d failed=%d aborted=%s elapsed_s=%.1f manifest=%s`
- `op=format_swap.rollback manifest=%s restored=%d`

Counters/timing: per-batch converted/failed/skipped, elapsed_s, MB written. Health: task state in tracker (`Queued/Converting/Completed/Aborted/Failed`) queryable via status endpoint. User-visible: progress bar (`progress`, `current_track`), disk warning, `beatgrid_preserved` flag, rollback result toast. Never log token; log filenames not full paths where avoidable.

## Test Plan

_(Stage 3 Test-Plan-Agent — pending)_

## Task Queue

<!--
Small, individually-committable implementation tasks. Written by research-plan (Stage 3),
approved by the user at the Approval Gate. research-implement works ONE task per branch:
routine/<slug>-task-<N>. 1 task = 1 feature = 1 PR. Tick - [x] when the PR is merged.
Each task maps back to a Step in ## Implementation Plan + has ≥1 row in ## Test Plan.
-->

_(Stage 3 Planner-Agent second pass — pending)_

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

_(Stage 3 Mockup+Summary-Agent — pending Plan-Reviewer PASS)_

## Mockup

_(Stage 3 Mockup+Summary-Agent — pending Plan-Reviewer PASS)_

---

> ⛔ APPROVAL GATE — user `/approve` (→ `accepted_`) or `/reject "<reason>"` (→ `rework_`). The single sign-off: read `## Approval Summary` + `## Mockup`. After approval, nothing is re-researched.
> ↓ Stage 4 — `inprogress_`. `research-implement` builds each Task Queue item on a `routine/*` branch. You test + merge the branch yourself.

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
