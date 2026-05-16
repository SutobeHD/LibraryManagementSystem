---
slug: library-quality-upgrade-finder
title: Find higher-quality replacement files for tracks already in library
owner: tb
created: 2026-05-15
last_updated: 2026-05-15
tags: [quality, upgrade, spectral, replacement, rekordbox-metadata]
related: [library-extended-remix-finder, analysis-remix-detector, external-track-match-unified-module]
---

# Find higher-quality replacement files for tracks already in library

> **Caveman style.** Fragments, bullets. Drop articles/filler/hedges. No prose paragraphs. Respect per-section caps below.
> State = folder + filename prefix (not frontmatter). Lifecycle = audit trail. See `../README.md`.

## Lifecycle

- 2026-05-15 — `research/idea_` — created from template
- 2026-05-15 — research/idea_ — section fill (research dive)
- 2026-05-15 — research/idea_ — transcode + safety refinement after Problem framing
- 2026-05-15 — research/idea_ — exploring_-ready rework loop (deep self-review pass)
- 2026-05-15 — research/exploring_ — promoted; quality bar met (6 OQ resolved + 5 PARKED; corrected _db_write_lock location bug; extended safety rules 5→7; Phase 1/2/3 with measurable exit gates)

---

## Problem

Library mixes lossless (FLAC/WAV) with MP3-128/256; some "FLAC" are MP3-transcodes (cliff 16-19 kHz vs Nyquist 22.05 kHz). CDJ-3000 + good headphones expose gap. No per-track quality signal today. No "lossless exists at Bandcamp" surface. Auditor + replacement-finder needed. Blast radius dominates: wrong swap loses cue/beatgrid/MyTag investment = data loss.

## Goals / Non-goals

**Goals** (each testable, metric in parens)
- Per-track quality score: container + true bitrate + sample rate + bit depth + spectral cutoff. (Metric: row in `track_quality` table for ≥ 99 % of scannable files within run; ffprobe-parse-error tracked.)
- Transcode-detection on lossless containers. (Metric: precision ≥ 0.95 on a 50-track labelled fixture mixing genuine lossless + known MP3→FLAC transcodes + bandlimited-master edge-cases.)
- External-source candidate search. (Metric: for a labelled 100-track set with known upgrade exists/doesn't-exist split, recall ≥ 0.70 for "exists" subset, false-positive rate ≤ 0.05 for "doesn't exist" subset.)
- Ranked replacement suggestions in UI; per-track explicit user confirm. (Metric: zero replace-without-confirm code path; UI test asserts.)
- On accept: snapshot → swap → migrate Rekordbox cue/beatgrid/MyTag/rating/color/play count intact when same edit. (Metric: post-swap diff of `master.db` content row preserves all six fields byte-for-byte; cue-point delta ≤ 5 ms after format-padding offset correction.)
- Re-use shared module from `idea_external-track-match-unified-module` (fuzzy + chromaprint + adapter registry). Do not fork.

**Non-goals**
- Auto-replace without per-track confirm.
- Replacing tracks with different edits — sister-doc `library-extended-remix-finder`.
- Cloud purchase automation. Surface link + manual download M1.
- Reviving removed backup engine (commits `cc171ee` / `8fe5036`). Snapshot = scoped local file copy only.
- Re-cueing / re-beatgridding when edits differ. Refuse the replace, route to remix-finder.
- Bundling `fpcalc` in M1. PATH-detect + skip-if-missing per shared-module convention.

## Constraints

External facts bounding the solution. Each cited + re-verified 2026-05-15.

- **Blast radius maximal**. Overwrite = loss of cue / beatgrid / MyTag investment. `docs/SECURITY.md` treats user audio as user-data root (never agent-writable autonomously). This feature crosses that line only under per-track user consent.
- **`master.db` writes must hold `_db_write_lock`** — RLock at `app/database.py:22` (verified 2026-05-15, **not** `app/main.py:138` as Findings #1 said). Helper `with db_write_lock():` exposed at `app/database.py:39`. Decorator `@serialise_db_write` at `:44`. Any rbox metadata-migration write path MUST acquire it. rbox 0.1.7 quirks → use `app/usb_one_library.py` patterns; rbox parsing only via `SafeAnlzParser` (`app/anlz_safe.py`, ProcessPoolExecutor `max_workers=1`).
- **`ALLOWED_AUDIO_ROOTS` sandboxing** — list declared `app/main.py:138`; `validate_audio_path` at `app/main.py:168`; canonical check at `app/main.py:617` (`if not any(resolved.is_relative_to(root) for root in ALLOWED_AUDIO_ROOTS)`). Downloads + snapshots MUST land inside a configured root before any swap.
- **Rekordbox metadata semantics**. Cue points + beatgrid anchors = time offsets (ms / sample-indexed) in `master.db` + `.ANLZ` sidecars. Survive a file swap only if new file has same edit boundary (intro start, length, silence padding). Beatgrid `first_beat_position` is sample-anchored — 50 ms shift desyncs every cue downstream. Format-encoder padding (10-30 ms typical) requires post-swap auto-align pass.
- **Spectral analysis cost re-verified 2026-05-15**. librosa 0.10.1 pinned in `requirements.txt:34`. Default STFT `n_fft=2048, hop_length=512` is FFT-vectorised numpy → throughput ~ 150-300× realtime on a modern i7 core. 6-min track ≈ 1.2-2.4 s wall, matches original 1-3 s estimate. 10k-track audit single-threaded ≈ 4-7 h; with 4 workers ≈ 1-2 h. **Pi4 calibration NOT in scope** (project targets desktop/laptop; sidecar runs in Tauri on user machine). Must run in bounded worker pool + resumable via `(file_path, mtime, size)` skip key.
- **ffprobe + ffmpeg = PATH-only, NOT bundled**. Verified `FFMPEG_BIN = "ffmpeg"` at `app/config.py:6`; consumer at `app/services.py:178` derives `ffprobe` via `FFMPEG_BIN.replace("ffmpeg", "ffprobe")`. `CLAUDE.md` confirms "External | FFmpeg in PATH | system". `backend.spec` grep for `ffprobe|chromaprint` → no hits (2026-05-15). Quality-audit must follow same PATH contract; degrade gracefully on missing ffprobe (skip-with-warning row in `track_quality`). Bundling = Schicht-A dep-pinning decision per-platform, M2+ topic.
- **External-source legal/auth**. SoundCloud HQ/lossless requires Go+ uploader settings; Bandcamp/Beatport/Qobuz require user purchases — no scraping of paid content. Local "HQ folder" = friction-free, MVP source.
- **Match key + fingerprint** delegated to `idea_external-track-match-unified-module` (M1 PATH-detect fpcalc, function-only API, single shared `Candidate` dataclass). Threshold 0.65 baseline (`app/soundcloud_api.py:583`). ISRC override when ID3/Vorbis tag present.
- **No backup engine** (removed commits `cc171ee` + `8fe5036`). Snapshot = scoped local file copy → `<library-root>/.upgrade-snapshots/<YYYY-MM-DD>/`. Inside `ALLOWED_AUDIO_ROOTS[0]` so sandbox check passes.
- **Sidecar SQLite for `track_quality`**, NOT `master.db` (don't pollute rbox-managed tables). Sister-doc `library-extended-remix-finder` proposes unified `app/data/track_suggestions.db` with `kind` column — coordinate; quality scoring belongs in its own `track_quality` table though (different cardinality: 1 row per file, vs N candidates per track).

## Open Questions

Numbered. Each resolvable (yes/no or X vs Y), not philosophy. Status tag per item.

1. **Spectral-cutoff threshold** — hard 20 kHz cliff vs composite (cutoff + noise-floor + user override). **RESOLVED → composite** (Findings 2026-05-15 #2). Bandlimited-master + 48→44.1 downsample false-positives forbid single hard threshold. Open sub-Q: noise-floor metric exact form (PARKED to draftplan; needs labelled fixture to calibrate).
2. **Duration-delta tolerance** — 250 / 500 / 1000 ms. **RESOLVED → 1 s hard refusal** (Findings #2, safety-rule 1). Empirical: format-padding deltas typically < 50 ms; 250-500 ms territory = bonus-track / different fade-out; ≥ 1 s = different edit certain.
3. **Fingerprint** — chromaprint vs mel-correlation. **RESOLVED → chromaprint** (Findings #2, safety-rule 2). Cross-encoding robustness wins over mel-correlation; shared module owns the wrapper (`idea_external-track-match-unified-module`); PATH-detect fpcalc, skip-if-missing per M1 plan in that doc.
4. **Snapshot location** — sibling-per-replace vs consolidated `.upgrade-snapshots/<date>/`. **RESOLVED → consolidated** (Findings #2, safety-rule 4). Cheaper to prune; discoverable; lives inside `ALLOWED_AUDIO_ROOTS[0]` so sandbox passes.
5. **Re-analyse policy after replace** — always vs only on duration/bit-depth/sample-rate change. **PARKED to Phase 2 draftplan.** Not blocking idea_ → exploring_; need to measure `analysis_engine` runtime on i7 first. Current bias: only on sample-rate / bit-depth delta (waveform overview regen mandatory); cue-point integrity preserved by safety-rule 1 + post-swap padding offset.
6. **Quality scoring** — strict ordering vs composite weights. **PARKED but pre-decided** → composite, weights `container 0.40 / sample_rate 0.20 / bit_depth 0.15 / spectral_cutoff 0.25` (rationale: lossless container is dominant signal but transcoded-FLAC must be down-weighted by cutoff). Exact threshold calibration deferred to fixture-driven tune at draftplan.
7. **Paid-store adapters in MVP** — yes / SC-only / local-only. **RESOLVED → local-HQ-folder + SoundCloud (link-surface)** for Phase 2 via shared adapter-registry. Bandcamp / Beatport / Qobuz = Phase 3, surface-link-only, no scrape of paid content (legal). DRM-encrypted SoundCloud Go+ = "available there" flag, never extract.
8. **UI surface** — standalone Quality-Audit view vs per-row badge. **RESOLVED → both** (Findings #2). Standalone for full-library awareness; per-row badge for in-context discovery. Click-through from badge enters same replace flow. Single Audit view shared with sister-docs (rename to "Library Audit" with `kind` tabs / facets — see sister-doc `library-extended-remix-finder` Recommendation cross-cutting).
9. **NEW — `track_quality` schema location** — own table in unified `app/data/track_suggestions.db` (sister-doc proposed) vs dedicated `app/data/track_quality.db`. **PARKED to draftplan**. Bias: own DB. `track_quality` is 1 row per file (cardinality matches file count); `track_suggestions` is N rows per track (different access pattern + retention TTL).
10. **NEW — concurrency model for full-library audit** — `concurrent.futures.ProcessPoolExecutor` vs `ThreadPoolExecutor` vs async-via-asyncio. **PARKED to draftplan**. librosa = GIL-bound numpy → ProcessPool likely; ffprobe = subprocess → either works. Pi4 NOT in scope per Constraints.
11. **NEW — interaction with `analysis_engine.py`** — does quality-audit invoke full `analysis_engine` or only the new lightweight quality path? **PARKED**. Bias: separate. Quality path = ffprobe + STFT-cutoff-only, ~1-3 s/track. Full `analysis_engine` (BPM, key, cues, hot-cues, beatgrid) = ~ 15-30 s/track. Replace flow may invoke full re-analyse on sample-rate change (open Q 5).

## Findings / Investigation

Dated subsections, append-only. Never edit past entries — supersede.

### 2026-05-15 — initial audit

**Quality dimensions, ordered**
- Container/codec: FLAC / WAV / ALAC > AIFF > MP3-320 > MP3-256 > MP3-V0/V2 > MP3-192 > MP3-128 > MP3 < 128 / OGG-low / AAC-low.
- Sample rate: 44.1 / 48 kHz baseline; 88.2 / 96 / 176.4 / 192 kHz hi-res.
- Bit depth (lossless only): 16-bit standard, 24-bit hi-res, 32-bit float rare.
- Channels: stereo standard; mono is a downgrade flag.
- True bitrate vs declared: "320 kbps MP3" with ABR / padding may be well below 320 mean — check ffprobe `bit_rate` on the stream, not container.

**Transcoded-from-lossy detection (anti-fraud check)**
- Lossy encoders low-pass; cliff height encodes source bitrate.
- Heuristic cutoffs (encoder-dependent): MP3-128 ~ 16 kHz; MP3-192 ~ 17-18 kHz; MP3-256 ~ 19 kHz; MP3-320/V0 ~ 19-20 kHz; AAC-256 ~ 20 kHz; lossless @ 44.1 kHz → Nyquist 22.05 kHz.
- Algorithm: full-track STFT, median over time per FFT bin, highest bin > -60 dBFS = cutoff. Lossless container + cutoff < 21 kHz = flag as transcoded.
- Pitfalls: bandlimited masters (vinyl rips, classical, spoken-word); 48 → 44.1 kHz downsample (Nyquist shifts). Need second-pass noise-floor-shape (lossy → sharper transition band).
- Tools: librosa already in deps; spek/sox = external CLIs to avoid for headless. `app/analysis_engine.py` natural home.

**Local quality scoring pipeline (offline batch)**
- Per track: ffprobe → container/codec/declared bitrate/sample rate/bit depth/duration; librosa → spectral cutoff + noise-floor shape.
- Persist to `track_quality` table (sidecar SQLite, NOT `master.db`); version column for re-scan idempotence.
- Resumable: skip on `(file_path, mtime, size)` match.

**External sources — feasibility snapshot**
- **Local "HQ folder"** — user-configured path under `ALLOWED_AUDIO_ROOTS`. Scan once with same pipeline; match by ISRC then title/artist/duration. Zero auth, zero network. Highest-leverage MVP.
- **SoundCloud** — existing `app/soundcloud_*` infra; HQ/lossless gated by Go+. Reuse SC matcher; threshold 0.65 calibrated.
- **Bandcamp** — no official search API; artist-page scrape + purchase library viable. Follow-up.
- **Beatport** — partner credentials required; user-account-scoped library API exists. Follow-up.
- **Qobuz** — hi-res search API exists, user auth required. Follow-up.

**Replacement workflow**
1. Candidate found → download to staging dir inside `ALLOWED_AUDIO_ROOTS`.
2. Re-scan staging file through quality pipeline; reject if not strictly better on weighting.
3. Same-edit check: duration delta < tolerance (Q2) AND mel-fingerprint correlation > threshold on first 30 s + last 30 s.
4. Pass → snapshot original → swap in place (or update `master.db` path on extension change).
5. Migrate metadata: cue / beatgrid / MyTag / rating / color / play count survive automatically (rows keyed by content_id, only blob changed). Re-run `analysis_engine` on sample-rate / bit-depth delta (waveform overview).
6. Fail → refuse, route to remix-finder.

**Risk catalogue**
- Wrong-edit silent replace → cue desync. Mitigation: step 3 gate.
- Format-padding drift → 10-30 ms cue shift. Mitigation: post-swap auto-align offset.
- rbox panic on post-swap metadata reread → SafeAnlzParser only.
- User undo: snapshot folder discoverable; "Restore from snapshot" UI action.
- Disk pressure: snapshots double-allocate; show used-space, offer prune-older-than-N.

**Tie-in to sister doc**
- Shared: external adapters, fuzzy matcher, quality scorer, fingerprint.
- Diverges on intent: this doc wants same-edit; sister wants different edits. Same gate code, inverted polarity.

### 2026-05-15 — transcode-detection robustness + replacement safety after Problem framing

**Transcode-detection false-positive cases.** 21 kHz cliff heuristic mis-flags three legit-lossless classes:
- (a) **Bandlimited masters**: vinyl rips (RIAA + cart roll-off), classical no-HF programme, spoken-word.
- (b) **48 kHz → 44.1 kHz downsampled lossless**: anti-alias cliff at 20-21 kHz looks lossy-ish.
- (c) **Intentionally lowpass'd productions**: D&B/dubstep aesthetics roll off HF.

Mitigation: noise-floor-shape second pass (lossy → sharper transition + quantisation-noise floor below cutoff vs natural rolloff). Per-track user override ("this IS lossless") pins verdict.

**Replacement-safety hard rules** (refuse-by-default if any fails):
1. Duration delta **< 1 s** or refuse.
2. **Chromaprint match required** when cue points or beatgrid exist.
3. Sample rate match within Rekordbox-supported range, or **re-analyse warning**.
4. **Snapshot before replace** → `<library-root>/.upgrade-snapshots/<YYYY-MM-DD>/`.
5. **User-explicit per-track confirmation**. No batch auto-replace.

**Quality-source priority matrix** (feasibility × legality):
- (a) Local "HQ folder" — friction-free, no rate limit, lossless. MVP.
- (b) Bandcamp purchase — lossless, user auth + manual download.
- (c) Beatport — lossless WAV/AIFF, auth + manual.
- (d) Qobuz hi-res — subscription.
- (e) SoundCloud Go+ — DRM, surface-as-link only.

**UX**: standalone Quality-Audit view + per-row badge. Click-through enters same replace flow.

**Coordination with sister-docs**: `extended-remix-finder` + `remix-detector` share fuzzy + chromaprint. Recommend unified `app/external_track_match.py`.

**Open-Question movement**: Q1 composite; Q2 1 s; Q3 chromaprint; Q4 consolidated; Q8 both.

### 2026-05-15 — exploring_-ready rework: constraint re-verification + transcode-detection deepening + replacement-safety hardening

**Constraint corrections vs Findings #1.**
- `_db_write_lock` lives at **`app/database.py:22`**, not `app/main.py:138` (Findings #1 + Constraints v1 wrong; sister-doc `external-track-match-unified-module` Constraints §6 already flagged this). Confirmed via `Grep "_db_write_lock" app/` — 5 hits, all in `app/database.py`. Helper `db_write_lock()` ctx at `:39`; decorator `@serialise_db_write` at `:44`. Constraints section updated.
- `ALLOWED_AUDIO_ROOTS` declared `app/main.py:138`; `validate_audio_path` at `:168`; canonical `Path.is_relative_to` check at `:617`. Verified.
- librosa pin `librosa==0.10.1` at `requirements.txt:34`. STFT cost claim re-verified: default `n_fft=2048, hop_length=512`, FFT-vectorised → ~150-300× realtime; 6-min track ≈ 1.2-2.4 s wall on i7 core. 10k tracks ÷ 4 workers ≈ 1-2 h. Pi4 calibration NOT in scope (project = Tauri desktop sidecar).
- ffprobe + ffmpeg PATH-only re-verified: `FFMPEG_BIN = "ffmpeg"` at `app/config.py:6`; `app/services.py:178` derives ffprobe via `.replace("ffmpeg", "ffprobe")`. `backend.spec` grep `ffprobe|chromaprint` → no hits. CLAUDE.md states "External | FFmpeg in PATH | system". Quality-audit MUST gracefully skip on missing ffprobe (warning row in `track_quality`), NOT fail hard.

**Transcode-detection robustness — concrete composite formula.**
- Inputs per file (raw):
  - `cutoff_hz`: highest STFT bin > -60 dBFS (median over time).
  - `transition_steepness`: dB drop per kHz across 1.5 kHz centred on cutoff (lossy ≈ steep, natural ≈ gentle).
  - `noise_floor_below`: mean magnitude (dB) of bins 0.5 kHz below cutoff, baselined against bins 2 kHz below cutoff (lossy → quantisation hiss raises baseline).
  - `claimed_lossless`: bool from container = FLAC/WAV/ALAC/AIFF.
  - `nyquist_hz`: from sample rate.
- Verdict (priority order, first match wins):
  - User override pin → returns user value, skip all rules.
  - `claimed_lossless && cutoff_hz < nyquist_hz - 1500 && transition_steepness > 8 dB/kHz` → `transcoded_from_lossy` (high confidence).
  - `claimed_lossless && cutoff_hz < nyquist_hz - 1500 && transition_steepness ≤ 8 dB/kHz` → `bandlimited_master_likely` (medium confidence) — surface in UI but do not down-rank.
  - `!claimed_lossless && cutoff_hz > 20500` → unusual; flag for inspection (possibly mis-tagged lossless).
  - else → verdict matches container (`lossless` / `lossy`).
- Calibration deferred to fixture: 50-track labelled set covering (i) genuine 16/44.1 FLAC, (ii) genuine 24/96 FLAC, (iii) MP3-128/192/256/320 → FLAC transcodes, (iv) vinyl-rip FLAC, (v) 48 → 44.1 downsampled lossless, (vi) classical w/ no HF. Threshold for `transition_steepness` is the single tunable; default 8 dB/kHz is a starting guess.

**Replacement-safety hard rules — operational detail (extends Findings #2 rules).**
- **Rule 1 (duration delta < 1 s)** measured ffprobe `format=duration` to ms; not sample-count (sample-count diff on resample doesn't mean different edit).
- **Rule 2 (chromaprint match)** uses `fpcalc -length 120` (default chromaprint compare-on-2-min); threshold = chromaprint-stock similarity ≥ 0.95. If fpcalc PATH-missing → refuse replace AND surface UI warning ("install fpcalc to enable safe replace"), never silent-bypass.
- **Rule 3 (sample-rate match)** Rekordbox supports 44.1/48/88.2/96/176.4/192 kHz. Sample-rate change MUST trigger waveform-overview regen via `analysis_engine` (cue-position semantics in `.ANLZ` are sample-indexed at the file's sample rate). Mismatch outside supported set → refuse.
- **Rule 4 (snapshot)** path = `validate_audio_path(library_root / ".upgrade-snapshots" / today_iso / new_filename)`. Must pass sandbox. Atomic copy (`shutil.copy2` for mtime preservation) **before** swap; only swap after copy verifies same SHA-256 as source. Snapshot manifest = small JSON sibling (`snapshot_manifest.json`) capturing original path, new candidate URL, ffprobe diff, chromaprint match score, timestamp, user-confirm token.
- **Rule 5 (per-track confirm)** UI flow: candidate-list view → click track → modal showing (i) ffprobe diff old/new, (ii) spectral plot old/new, (iii) chromaprint match score, (iv) duration delta in ms, (v) cue/beatgrid preservation expectation, (vi) snapshot path, (vii) explicit "Confirm replace" button (NOT default-focused). Browser confirm()/alert() forbidden per coding-rules.
- **NEW Rule 6 — Rekordbox-open check.** Refuse replace if Rekordbox process is currently running (file would be locked + cache de-sync). Surface "Close Rekordbox to replace" message. Process check = OS-specific (`tasklist` on Windows, `pgrep -i rekordbox` on Unix), wrapped in `app/system_diag.py` if not present.
- **NEW Rule 7 — Atomic file swap.** Use OS-level move (`os.replace`) for atomicity; on Windows w/ open handle it raises → caller surfaces Rule 6 message. Never partial-write the target.

**Cost model — full-library audit, refined.**
- Per track: ffprobe ≈ 50-100 ms; librosa load (mp3 6-min) ≈ 0.6-1.0 s; STFT cutoff + noise-floor ≈ 0.6-1.4 s. Total ≈ 1.3-2.5 s/track wall on i7.
- 10k tracks single-thread = 3.6-7 h; 4 ProcessPool workers = 0.9-1.75 h (librosa = GIL-bound numpy, ProcessPool wins).
- Resumable: skip key `(abs_path, mtime_ns, size_bytes, codec_pipeline_version)`; re-scan only on (file changed) OR (pipeline version bump).
- Replacement re-scan (post-swap, single file) negligible: ≤ 3 s.

**ffprobe degradation contract.**
- Missing ffprobe: `track_quality` row gets `verdict="unknown_no_ffprobe"`, all numeric fields null. UI shows "ffprobe unavailable — install FFmpeg" banner once per session, not per row. Audit run does NOT abort.
- Missing librosa: should never happen (pinned dep), but defensive: fall back to ffprobe-declared bitrate/format only, verdict = `"container_only"`.
- Missing fpcalc: quality-audit + replace-suggestion paths still work; replace-execute path refuses (rule 2 hard fail) until installed.

**Sister-doc consistency check.**
- `idea_external-track-match-unified-module` confirms M1 scope = function-only API, flat `app/external_track_match.py`, fpcalc PATH-detect. This doc's safety-rule 2 (chromaprint required for replace) is downstream consumer of that M1 → consistent.
- `idea_library-extended-remix-finder` proposes unified `app/data/track_suggestions.db` with `kind` column. **Disagree partially**: quality-audit `track_quality` table (1 row per file, no `kind` column needed; different access pattern + retention) lives in its own DB or in same physical SQLite file but separate table. Open Q 9 captures this.
- All three sister-docs converge on shared adapter registry — no fork risk.

**Open-Question movement this round.**
- Q5 PARKED to draftplan (needs `analysis_engine` runtime profile first).
- Q6 PARKED-but-pre-decided (composite weights `0.40 / 0.20 / 0.15 / 0.25`; final calibration via fixture).
- Q7 RESOLVED (local + SC link-surface for Phase 2; paid stores Phase 3, surface-link only, no scraping).
- Q9, Q10, Q11 added (PARKED to draftplan).
- All 11 open questions either RESOLVED, PARKED with stated bias, or PARKED to draftplan with explicit blocker — meets ≥50% resolution criterion for exploring_.

## Options Considered

Required by `evaluated_`. Sketch ≤3 bullets, pros, cons, effort (S/M/L/XL), risk.

### Option A — Local-folder-only MVP, full pipeline (single shot)

- Sketch: quality scorer + cutoff/noise-floor verdict + duration/chromaprint gate + snapshot/swap. External source = one user "HQ" folder. No network. Ship Phases 1+2 together.
- Pros: zero auth/legal; end-to-end flow exercised; immediate user value for those w/ HQ archive; sister-doc gets shared infra immediately.
- Cons: replacement plumbing risk lands before scoring is field-validated; ceiling for users w/o HQ archive; no audit-only fallback.
- Effort: L (M + M combined; sequencing reduces refactor cost)
- Risk: Medium-high — replace blast-radius lands before users have stress-tested the verdict pipeline.

### Option B — Audit-only forever (no replace, ever)

- Sketch: quality scoring + transcode verdict + UI badges + Audit view. No replace flow. User does upgrades manually via the badges.
- Pros: zero replace-blast-radius; ships fast; pure read-side; satisfies the privacy-conservative user.
- Cons: half-feature; spectral-analysis investment doesn't pay back without close-the-loop replace; sister-docs (extended-remix, remix-detector) still need chromaprint built elsewhere.
- Effort: S
- Risk: Low.

### Option C — Full source matrix in one go (SC + Bandcamp + Beatport + Qobuz + local)

- Sketch: parallel adapter for every store behind unified search interface. Audit + replace + all adapters concurrently.
- Pros: maximum user value if all five adapters survive ToS + auth maintenance.
- Cons: huge scope; per-store auth flows; legal/TOS care per adapter; long path to first user value; high partial-implementation rot risk; paid stores need surface-link-only by Constraint anyway, so most adapter work is for SC + local.
- Effort: XL
- Risk: High — adapter maintenance is ongoing, scrapers break.

### Option D — Phased (audit → local replace → external surfaces)

- Sketch: Phase 1 = audit + badges + transcode verdict (no replace, no external). Phase 2 = local-HQ-folder replace with safety rules 1-7. Phase 3 = SC adapter + Bandcamp/Beatport/Qobuz as surface-link-only. Each phase = standalone shippable.
- Pros: blast-radius code (Phase 2) lands only after scoring proven by Phase 1 dogfooding; sister-docs consume Phase 1 deliverables (shared adapter registry from `external-track-match-unified-module`); each phase = independent gate; small reversible cuts.
- Cons: longer total timeline; Phase 1 alone without "the point" (replace) may feel incomplete to users; coordinating with sister-docs adds calendar dependency.
- Effort: M (P1) + M (P2) + L (P3)
- Risk: Low-medium per phase; aggregate Low.

### Option E — Audit + manual-upload-only replace (no auto-download)

- Sketch: Phase 1 audit + badges. Phase 2 = user drag-drops replacement file into UI; we run safety rules + snapshot/swap. No external-source scanner at all (M1+M2).
- Pros: zero adapter / network surface; close-loop value with much smaller scope than Option D; user already has the HQ file in hand by the time they engage.
- Cons: doesn't surface "an upgrade exists out there" (Goal #3 unmet); requires user-driven discovery; loses the "find me upgrades" angle.
- Effort: S (P1) + S (P2)
- Risk: Very low. But Goal #3 (external candidate search) is the differentiator vs spek.exe — Option E drops it.

## Recommendation

**Option D**, phase deliverables + exit gates pinned:

**Phase 1 — Audit-only** (deliverable shippable standalone)
- Deliverables: `track_quality` sidecar SQLite schema + ffprobe wrapper + librosa cutoff + noise-floor pipeline + transcode verdict + per-track user override + UI badges + standalone Quality-Audit view + Audit-progress + resumable scan.
- Cross-cutting deliverable: ensure shared `app/external_track_match.py` ships in parallel (lives in sister-doc `external-track-match-unified-module`'s scope; Phase 1 here depends on that module's M1 only for `Candidate` dataclass + adapter registry shape — does NOT yet consume fuzzy/chromaprint).
- **Exit gate to Phase 2:** Phase 1 audit dogfooded on owner's 5-30k library; verdict precision ≥ 0.95 on labelled 50-track fixture; zero crash/hang reports across 2 weeks; performance ≤ 2 h on owner's library w/ 4-worker pool.

**Phase 2 — Local-HQ-folder replace** (close-the-loop)
- Deliverables: local "HQ folder" scanner reuses Phase 1 pipeline + safety rules 1-7 (duration <1s / chromaprint / sample-rate / snapshot / per-track-confirm / Rekordbox-closed / atomic-swap) + `.upgrade-snapshots/<date>/` + "Restore from snapshot" UI + post-swap auto-align cue-offset pass + replace-suggestion modal (per safety-rule 5 spec).
- Cross-cutting: chromaprint (`fpcalc`) PATH-detect via shared module; fail-closed if missing (rule 2).
- **Exit gate to Phase 3:** 100 replaces dogfooded across genuine + bandlimited-master + cross-sample-rate cases without metadata loss; "Restore from snapshot" tested on ≥ 5 reverts; disk-pressure prune UI shipped.

**Phase 3 — External-source adapters** (discovery beyond local)
- Deliverables: SoundCloud adapter (reuses existing OAuth + matcher); Bandcamp / Beatport / Qobuz as surface-link-only (no scrape, no download). DRM sources (SC Go+) flagged "available there", never extracted. Adapter registry mutation hooks via shared module.
- **Exit gate to graduation:** recall metric (Goals §3) ≥ 0.70 on labelled 100-track fixture; zero ToS-breach paths (paid-content scraping); user-feedback shows replace flow is preferred over manual.

**Cross-cutting (all phases):**
- Consume `app/external_track_match.py` from sister-doc `external-track-match-unified-module` (M1 function-only API; M1 PATH-detect fpcalc). Do not fork.
- Coordinate UI shell with sister-docs `library-extended-remix-finder` + `analysis-remix-detector` → single "Library Audit" view with `kind` tabs (quality / extended / remix) rather than three competing panels.

**Blockers before `evaluated_` (none block exploring_):**
- Open Q5 (re-analyse policy) — blocks Phase 2 draftplan only.
- Open Q6 (composite scoring weights final calibration) — blocks Phase 1 draftplan; needs labelled fixture.
- Open Q7 — RESOLVED.
- Open Q9/10/11 — blocks draftplan, not exploring_.
- Confirm: no backup-engine revival; `.upgrade-snapshots/` is the path. **Stated; needs owner ack at evaluated_.**
- Confirm: shared `app/external_track_match.py` lands first (sister-doc M1). Without it, this doc's Phase 2 cannot safely ship rule 2 (chromaprint).

---

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

## Review

Filled at `review_`. Unchecked box or rework reason → `rework_`.

- [ ] Plan addresses all goals
- [ ] Open questions answered or deferred
- [ ] Risk mitigations defined
- [ ] Rollback path clear
- [ ] Affected docs identified (`architecture.md`, `FILE_MAP.md`, indexes, `CHANGELOG.md`)

**Rework reasons:**
- …

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

- Code (existing, verified 2026-05-15): `app/database.py:22` (`_db_write_lock` RLock), `app/database.py:39` (`db_write_lock()` ctx), `app/main.py:138` (`ALLOWED_AUDIO_ROOTS`), `app/main.py:168` (`validate_audio_path`), `app/main.py:617` (sandbox check), `app/config.py:6` (`FFMPEG_BIN`), `app/services.py:178` (ffprobe derivation), `app/anlz_safe.py` (SafeAnlzParser quarantine), `app/analysis_engine.py` (librosa pipeline), `requirements.txt:34` (`librosa==0.10.1`)
- External docs: <chromaprint / fpcalc upstream docs — fill at exploring_>; ffprobe `format=duration` / `bit_rate` field reference; Rekordbox supported sample rates
- Related research: `library-extended-remix-finder`, `analysis-remix-detector`, `external-track-match-unified-module`
