# Handover — full library measurement (library analysis v2)

**For:** a fresh Claude instance with no prior context.
**From:** session of 2026-11-08 that built v1 (`scripts/library_analysis.py`).
**User:** tb. Talks German. Wants every claim measured, not assumed ("Teste immer selber"). Short sentences, tables, paste-ready commands, one command per block (the user switches between cmd and PowerShell; `&&` and `;` each break in one of them).
**Goal (user's words, 2026-11-08):** "Ich will das volle Ausmaß, alles messen was geht." Measure everything that can be measured about the user's library: metadata, file properties, Rekordbox's own analysis data, and the audio itself. Then cross-check the sources against each other. The user also wants a setting for how deep a track is analysed: **Rekordbox level or high level** (§3.6).

Read first: `CLAUDE.md`, `.claude/rules/*.md`, then this file. `docs/ANALYSIS_HANDOVER.md` is the older handover for engine *accuracy* work; read §2 (setup) only if you touch the engine itself.

---

## 0. Iron rules

- **Read-only towards user data.** Never write `master.db`, ANLZ files, audio files, USB sticks, `exports/`, `backups/`. Never call `/api/library/analyze-batch` or anything in `app/analysis_db_writer.py`: those write `master.db` and ANLZ, including cues.
- **Never put a partial result into `AnalysisCache`.** `run_full_analysis` returns cached dicts as-is, and the ANLZ writer turns them into Rekordbox files. A cached dict without `waveform` would give empty waveforms the next time the user analyses that track. Your own results go to your own store (§4).
- **Measure, then claim.** Every number in the report comes from a run. Write "estimate" next to anything that does not.
- **Long jobs run in the background, resumable.** The audio stage takes hours (§3.5).
- **Do not kill processes you did not start.** A backend from another checkout often runs on :8000.
- **Commit atomically and push** (non-force). Use Conventional Commits with the `Co-Authored-By` trailer the harness gives you. Open a PR only after asking the user.
- **Feature registry** (`docs/features/*.toml`): update the entry in the same commit as the code (§6).

---

## 1. Starting point

### 1.1 What exists

| Item | Where | State |
|---|---|---|
| v1 report script | `scripts/library_analysis.py` on `feat/library-analysis` (commit `d520daf`) | done, 10 tests in `tests/test_library_analysis.py` |
| Registry entry | `library-analysis-report` in `docs/features/analysis.toml` | `in_progress`, todos listed |
| Genre atlas | `app/genre_atlas.py` + `app/data/genre_atlas.json` (301 genres, 29 tags, 116 scenes) | in PR #59, which is also merged into the integration PR #60 |
| Quality scanner (ffprobe) | `scripts/dev/scan_audio_quality.py` + `scripts/dev/rescan_unreadable.py`, **only on `feat/artist-hub`** (commit `15fb92f`) | registry `quality-tiers-audit`, `in_progress` |
| PSSI mask code | `app/anlz_usb_export.py:mask_pssi` on `claude/dreamy-planck-w7771v` (PR #60) | masks for USB export; XOR, so the same op unmasks |
| Light track list | `GET /api/library/tracks?light=true` on PR #60's backend | drops `beatGrid`, `Cues`, `positionMarks`, `phrases` |
| Sortable columns | `frontend/src/utils/trackSort.js` on `feat/sortable-columns` | `SORT_VALUES` maps a column id to a sort value; new measured columns plug in there later |

v1 run (2026-11-07, 4760 tracks, 6 s): report at `tmp/library-analysis/{report.md,report.json,tracks.csv}`. Key numbers:

| Finding | Value |
|---|---|
| Atlas candidate from metadata / tempo only / none | 67.1 % / 20.6 % / 12.3 % |
| Cause of "none" | no Genre value and BPM in the gaps of the level-1 typical windows (142-148, 155-170 BPM) |
| Genre field filled | 48.3 %, 36 distinct values, spelling variants (HARD TECHNO / Hard Techno …) |
| Label / Rating / Colour filled | 8.2 % / 33 % / 10 % |
| Formats | aiff 2906, m4a 738, mp3 642, wav 198, flac 164; 112 streams (soundcloud: / spotify:) |
| LMS analysis cache | 2 of 4648 local tracks, both failed results |

### 1.2 Branch to work on: ask the user once

`feat/library-analysis` is based on `main` and `feat/genre-atlas-hints`. It lacks PR #60's `mask_pssi`, the light route and the newer backend fields.

**Recommendation:** create a new branch `feat/library-measure` from `origin/claude/dreamy-planck-w7771v` (PR #60) and cherry-pick `d520daf`, plus the `library-analysis-report` registry entry from `docs/features/analysis.toml`. Cherry-pick needs the user's go-ahead (`.claude/rules/agentic-mode.md`), so ask: "Neuer Branch auf Basis von PR #60, Analyse-Commit rüberholen?" If the user says no, stay on `feat/library-analysis` and copy the 10-line mask routine with a comment that points to `anlz_usb_export.py`.

Fresh worktree: `npm install` is not needed (Python only). Use the main checkout's `.venv` through a junction: `cmd //c "mklink /J .venv C:\Users\tb\Documents\GitHub\LibraryManagementSystem\.venv"`.

### 1.3 Environment (measured 2026-11-08)

- `.venv` is CPython 3.11. `AnalysisEngine.capabilities()` = madmom RNN beats, **no essentia** (no Windows wheel), so key detection uses the K-S + Temperley fallback.
- pyrekordbox 0.1.7. ffprobe and ffmpeg are on PATH (WindowsApps alias).
- Machine: 16 cores / 32 threads, 62 GB RAM, 178 GB free in the home drive.
- Print on a cp1252 console breaks on non-ASCII (`→` raised UnicodeEncodeError in the backend). Write files as UTF-8 and set `PYTHONIOENCODING=utf-8` for runs.
- Pre-commit ruff differs from the `.venv` ruff. The first commit of a new `.py` file can fail on reformat: restage and commit again.

---

## 2. Data sources

| Source | How | Cost | Notes |
|---|---|---|---|
| Track list | `GET /api/library/tracks` (v1 `--api`), or a JSON snapshot (`--save-input` once, then `--input`) | full: 140 MB, about 20 s; light: 3.2 MB, 0.2 s | Use the snapshot for repeat runs. Fields: ID, Title, Artist, Album, Genre, Label, Key, BPM, Rating, ColorID, Comment, MyTag, TagIDs, path, TotalTime, Bitrate, SampleRate, ReleaseYear, StockDate, PlayCount, Composer, Remixer, Lyricist, Subtitle, ISRC, Artwork, beatGrid (full only), Cues (newer backend) |
| File probe | ffprobe per file (port the `feat/artist-hub` scanner) | I/O bound, minutes | codec, bitrate, VBR, sample rate, bit depth, channels, duration, tags, errors |
| Rekordbox ANLZ | `app/anlz_safe.py:resolve_anlz_paths(db_path, ids)` → `{"DAT","EXT","EX2"}` paths; parse with `pyrekordbox.anlz.AnlzFile` | 60 ids resolved in 0.5 s; parsing is fast | **Never rbox for ANLZ files**: it silently returns no grids. rbox only for MasterDb. `db_path` = `%APPDATA%\Pioneer\rekordbox\master.db` (read-only) |
| Audio | decode + LMS engine functions (`app/analysis_engine.py`) | about 0.136 s CPU per second of audio (§3.5) | 4628 of 4648 local files exist (20 missing) |

**ANLZ tags present (measured on 60 random tracks):** every track has DAT (PQTZ, PCOB×2, PVBR, PWAV, PWV2, PPTH), EXT (PQTZ in 59 as PQT2, PCOB/PCO2×2, PSSI, PWV3, PWV4, PWV5) and EX2 (PWV6, PWV7, PWVC). pyrekordbox warns "Tag 'PVB2' not supported"; this is harmless.

**PSSI is XOR-masked in about half the files.** pyrekordbox 0.1.7 does not unmask.

- Measured on 200 random tracks: 198 have PSSI. 107 were masked and 91 plain.
- After unmasking with the `mask_pssi` routine, which detects masking by mood not in 1..3, every mood is 1..3. The moods were high 166, mid 31, low 1. Each track has 6 to 47 phrases, median 18.
- Recipe: read the file bytes, walk the tags (`app/anlz_cue_patch.py:_walk_tags`), apply the XOR to the PSSI tag only, splice the result back, then `AnlzFile.parse(data)`.
- Phrase kinds per mood follow the Deep Symmetry djl-analysis "Song Structure" spec. Verify the mapping against the Rekordbox UI on 3 tracks before you rely on it:
  - high: 1 Intro, 2 Up, 3 Down, 5 Chorus, 6 Outro
  - mid: 1 Intro, 2-7 Verse 1-6, 8 Bridge, 9 Chorus, 10 Outro
  - low: 1 Intro, 2-4 Verse 1, 5-7 Verse 2, 8 Bridge, 9 Chorus, 10 Outro
- The measured kind values fit these ranges: high 1/2/3/5/6, mid 1-10.

**Rekordbox-written vs LMS-written ANLZ:** tracks that LMS analysed carry LMS's ANLZ, and PR #60 lists known LMS writer bugs (PWV5 red/blue swapped, PWV4 byte order, PWV2 whiteness). Record per track who wrote the file if you can tell. If you cannot, say so in the report.

---

## 3. Measurement catalogue — everything

Each row becomes a column in the per-track output. Status: **exists** = code is there, **new** = write it.

### 3.1 Stage A — metadata (v1, exists)

Field fill rates, the Genre vocabulary and spelling variants, atlas coverage and evidence sources, leave-genre-out agreement, MyTags, source and format, SoundCloud uploaders and labels without a scene note. Keep it. Fix the two v1 todos along the way if cheap:

- The BPM fallback over min-max windows belongs in `app/genre_atlas.py` (PR #59 code). Ask before touching it.
- Write scene notes for the top uploaders.

### 3.2 Stage B — derived from the track list (new, seconds)

| Measurement | How |
|---|---|
| Paper quality tier A/B/C/D | format + Bitrate + SampleRate with the user's rules (§5). Refined by Stage C, overridden by Stage E |
| Tempo landscape | BPM histogram (1 BPM bins), per Genre and per atlas level-1; gaps and clusters |
| Key landscape | Camelot distribution; harmonic neighbours per track (same key, ±1, relative major/minor) = mixability count |
| Library growth | StockDate per month × genre / BPM / format (`StockDate` is the text "None" for 23 tracks: treat as missing) |
| Duplicate candidates | normalised Artist + Title, the same track in two formats; later compared with the audio fingerprint (E) |
| Preparation state | beatGrid present (full payload only), Cues count, Rating / Colour / MyTag set, SoundCloud URL in Comment |
| Scene map | uploader / Label × genre × BPM; candidates for new atlas scene notes |
| Contradictions | Genre outside that genre's atlas BPM window; MyTag vs Genre; MyTag "Bad Quality" / "BadFormat" vs paper tier |
| Artist / playcount / rating stats | tracks per artist, artists across genres, never-played tracks, rating per genre |

### 3.3 Stage C — file probe (new port, minutes)

Port `scan_audio_quality.py` + `rescan_unreadable.py` from `feat/artist-hub` (`git show feat/artist-hub:scripts/dev/scan_audio_quality.py`). Do not rewrite them. Add to `paths` of the owning registry entry.

| Measurement | Use |
|---|---|
| codec, profile, bitrate (CBR/VBR), sample rate, bit depth, channels | precise paper tier |
| duration vs Rekordbox TotalTime | > 2 s difference = truncated = D |
| container vs extension mismatch, undecodable, missing | direct D |
| encoder tag (LAME / iTunes / ffmpeg) | source hints |
| sibling `*.m4a.backup-<ts>` next to an AIFF | flag `konvertiert` (about 2899 AIFFs come from AAC about 256k) |
| file size | bytes per minute sanity check |

### 3.4 Stage D — Rekordbox ANLZ (new, minutes, no audio decode)

| Tag | Measurement |
|---|---|
| PQTZ / PQT2 | grid present, beat count, **tempo changes** (variable-tempo grid), first downbeat offset, bars |
| PCOB / PCO2 | hot cue count, memory cue count, loops, colours, comments |
| PSSI (unmasked) | Rekordbox phrase mood (high/mid/low), phrase sequence, intro / outro length in bars, chorus count, end beat |
| PWV6 / PWV7 (EX2) | 3-band waveform: low / mid / high energy per frame → bass-heavy vs bright, energy curve. Verify the byte layout against pyrekordbox structs first |
| PWV4 / PWV5 | colour waveform as a second energy / brightness proxy; mind the LMS-writer bugs (§2) |
| PPTH | path stored in ANLZ vs real path (moved files) |

### 3.5 Stage E — audio (new runner, hours)

**Measured cost:** `run_full_analysis` single-process, `use_cache=False`:

| File | Length | Time |
|---|---|---|
| AIFF | 6:02 | 57.4 s |
| MP3 | 5:48 | 43.4 s |
| FLAC | 4:14 | 30.3 s |

- That is about 0.136 s of CPU per second of audio.
- The library has 392.5 h of local audio, so 53 CPU-hours.
- Ideal parallel time is 6.7 h with 8 workers, 4.5 h with 12, and 3.3 h with 16. These are estimates: measure with `--limit 50` first. Set `OMP_NUM_THREADS=1`, `OPENBLAS_NUM_THREADS=1` and `MKL_NUM_THREADS=1` per worker, or numpy threads will fight each other.

**Decode once.** `run_full_analysis` loads the audio itself and also builds waveforms, PVBR and cues, which you don't need. Write `measure_track(path)` that loads once and calls the engine's building blocks in the same order as `run_full_analysis` (`app/analysis_engine.py:2323`):

1. `librosa.load(path, sr=None, mono=False)`
2. `compute_stereo_features` on the native stereo signal
3. Mono-downmix and resample to 44.1 kHz
4. `get_encoder_delay`, `find_first_signal_onset`
5. `detect_beats`, `detect_key`, `detect_phrases`, `detect_tempo_changes`
6. `calculate_lufs` on the native signal, `calculate_replay_gain`
7. `detect_mood`, `hint_genre`
8. Your own extras, below

Skip `generate_waveform_data`, `generate_pvbr` and the cue generators. Then measure the speed gain.

Engine fields to keep:

- tempo: `bpm`, `bpm_raw`, `beat_count`, `downbeat_index`, `beat_method`, `grid_confidence`, `tempo_anchors` (count + spread)
- key: `key`, `camelot`, `key_confidence`, `key_method`
- loudness and stereo: `lufs`, `replay_gain`, `peak`, `stereo{width, balance, phase_correlation, is_mono}`
- mood: `mood{mood, brightness, warmth, texture, spectral_centroid, spectral_rolloff}`, `genre_hint`
- phrases: `phrases[]{label, mood, energy, start_ms, end_ms}` (store compact)
- file: `encoder_delay_ms`, `first_signal_ms`, `duration`, `sample_rate_native`, `channels`

Sample from the run: `grid_confidence` was 0.11-0.29 and `key_confidence` 0.36-0.61 on three normal techno tracks. Check the distribution before you call a value "low".

New measurements in the same pass (cheap once decoded):

| Id | Measurement | Method |
|---|---|---|
| E1 | **spectral cutoff** → measured quality tier | STFT on the native signal, median magnitude per bin, highest bin > -60 dBFS; hard-edge test (steep drop within about 300 Hz). Thresholds in §5 |
| E2 | clipping | count of samples with \|x\| ≥ 0.999 in runs ≥ 3; optional true peak via 4× oversampling |
| E3 | dynamics | PLR = peak dBFS − LUFS; crest factor; optional loudness range from 3 s short-term loudness |
| E4 | silence | leading (`first_signal_ms`) and trailing silence |
| E5 | DC offset | mean per channel |
| E6 | bass share | energy share < 60 Hz and < 120 Hz |
| E7 | low-band mono compatibility | L/R correlation of the < 150 Hz band (club rigs sum the bass to mono) |
| E8 | audio fingerprint | **Chromaprint** via `app/external_track_match.py:fingerprint` (finds the same master across formats). It needs `fpcalc` on PATH, which is **not installed** (checked 2026-11-08). Installing it is a new dependency: ask the user. The duplicate finder's `app/main.py:_fingerprint_python_fallback` (MD5 over 30 s PCM at 11025 Hz) only catches bit-identical decodes, not MP3 vs AIFF of the same master. Its docstring claims more |

**Runner** (`scripts/library_measure_audio.py`, new):

- **Pool:** `ProcessPoolExecutor(max_workers=N, max_tasks_per_child=20)`. Default N = 12; RAM is not the limit at 62 GB, but measure peak RSS per worker.
- **Output:** one JSON line per track to `tmp/library-analysis/measure/audio.jsonl`. The key is `ID + path + mtime + size`; a re-run skips rows whose key is unchanged. That makes the run resumable after a crash or sleep.
- **Errors:** an error is a row too (`status: error`, type, message). Never drop a track silently.
- **Hangs:** use a per-track time budget (for example 10 × duration). If a worker hangs, record the track and recycle the pool.
- **CLI:** `--limit`, `--workers`, `--only-ids`, `--input <tracks.json>`, `--depth rekordbox|high` (default `high`, see §3.6).
- **Progress:** print a one-line progress every 50 tracks with the rate and ETA.
- **Sleep:** Windows sleep kills the night run. Tell the user to keep the machine awake, or use the app's keep-awake tool if available.

### 3.6 Analysis depth setting — Rekordbox level vs high level (user requirement 2026-11-08)

The user's words: "Man soll einstellen können, wie intensiv analysiert werden soll beim Track-Analysieren, ob Rekordbox-Level oder High-Level."

| Level | Computes | Purpose |
|---|---|---|
| **Rekordbox** | BPM, beats + downbeat, grid confidence, key, waveforms (PWAV … PWV7), phrases, tempo anchors, PVBR, auto cues | everything ANLZ / USB export and the CDJs need; nothing more |
| **Hoch** (high) | Rekordbox level + LUFS, ReplayGain, peak, stereo, mood / brightness / warmth / texture, genre hint, and every new Stage-E measurement (E1-E8) | the full measurement |

What exists:

- `run_quick_analysis` is the internal pass 1 (BPM / key / beats) for instant playback. It stays and is not a user level.
- `run_full_analysis` today sits between the two levels: Rekordbox data plus LUFS, mood and stereo, but none of E1-E8.
- **Dead setting to replace:** the "Analysis Quality" section in `frontend/src/components/settings/SettingsAnalysis.jsx` offers `analysis_quality` = fast / standard / thorough. The default `'standard'` is set in `SettingsView.jsx`. **No backend code reads it** (registry `analysis-settings` note), and its per-track times are not measured. Replace that section with the depth selector rather than adding a second one.

Design (verify each point in code before building):

1. **One setting, `analysis_depth`** = `"rekordbox"` | `"high"`.
   - It is stored with the other app settings through `GET`/`POST /api/settings`, which go through the `settings.json` manager in `app/services.py`.
   - The default is `"rekordbox"`.
   - Measure both levels on the same 50 tracks. If high costs little extra, show the user the numbers and ask whether high becomes the default.
2. **The engine takes a `depth` argument.**
   - Split `run_full_analysis` so the high-only parts run only at `depth="high"`.
   - Time every stage once on the 50 tracks. The engine already has stage boundaries (`emit(...)`). Put the measured split per stage into this file.
3. **Cache.** Results carry `"depth"`. A cached entry satisfies a request only if its depth is ≥ the requested depth. A cached Rekordbox-level result must never answer a high-level request. Bump `ANALYSIS_VERSION` in `app/analysis_cache.py` if the result shape changes.
4. **Every caller passes the setting.** The callers of `run_full_analysis` on PR #60 are:
   - `app/analysis_db_writer.py:204`
   - `app/anlz_sidecar.py:52`
   - `app/audio_analyzer.py:134` and `:165`
   - `app/services.py:1067` (import)

   Read the setting once per job, not per track.
5. **Optional per-run override:** "Analysieren (Rekordbox)" / "Analysieren (Hoch)" in the track context menu or batch dialog. Ask the user before building it.
6. **The measurement runner (§3.5) uses the same switch:** `--depth rekordbox|high`, default `high` for the library run.

This touches backend, engine, cache and settings UI:

- Run `python scripts/feature_map.py --who analysis-settings` and `--who analysis-engine` first.
- `analysis-api-manual` has active work on PR #58 / #60.
- Spawn `route-architect` if a route changes.
- Spawn `audio-stack-reviewer` for the engine edit, and `e2e-tester` for the settings UI.
- Registry entry: `analysis-depth` in `docs/features/analysis.toml`.

### 3.7 Stage F — network (only if the user asks)

These are optional and not started without the user's say:

- SoundCloud and Spotify play counts (`popularity-classifier`, partial)
- MusicBrainz or Discogs lookups to fill Label and Year

---

## 4. Output

- `tmp/library-analysis/` (gitignored): `report.md`, `report.json`, `tracks.csv`, plus `measure/{probe,anlz,audio}.jsonl`.
- Never commit audio-derived dumps.
- `tracks.csv` gets one column per measurement. It is semicolon-separated UTF-8 with BOM, as in v1, because the user opens it in Excel.
- Keep the report sections numbered. Add sections in this order:
  - Quality map
  - Preparation
  - Tempo / key landscape
  - Rekordbox phrases
  - Audio features
  - Cross-checks
  - Duplicates
  - Errors / missing files

---

## 5. User decisions already made (do not re-ask)

**Quality tiers** (confirmed 2026-10-24). Every file gets a paper rating and a measured rating, and **the worse one wins**. Defects force D.

| Tier | Paper rule | Spectral cutoff |
|---|---|---|
| A Verlustfrei | PCM/FLAC/ALAC ≥ 44.1 kHz/16 bit, no known lossy source | ≥ 20.5 kHz @44.1k, ≥ 21 kHz @48k, no hard edge |
| B Club-tauglich | MP3 ≥ 240 (CBR 256/320, VBR V0), AAC ≥ 192, Opus ≥ 128; a lossless container with such a source is B, not A | ≥ 19 kHz |
| C Notspielbar | MP3 160-224, AAC 112-160, Opus 80-112 | > 17 and < 19 kHz |
| D Unspielbar | MP3 ≤ 128, AAC ≤ 96, Opus < 80 | ≤ 17 kHz |

- **Direct D:** sample rate < 44.1 kHz, mono, missing, undecodable, truncated (> 2 s vs Rekordbox length), wrong extension without decodable content.
- **Flags:**
  - `konvertiert`: lossless container with a known lossy source.
  - `aufgeblasen`: paper ≥ 1 tier better than measured, no known source.
  - `prüfen`: cutoff within ±300 Hz of a boundary, or a natural roll-off on a lossless master. Write a spectrogram PNG; the user's override persists.
- Streams get no tier.
- LAME lowpass reference: 128 → 17.0 kHz, 160 → 17.5, 192 → 18.6, 256 → 19.7, 320 → 20.5.
- Paper-only count from 2026-10-24: A 301, B 4240, C 35, D 126, 112 streams. B is an upper bound until the spectral run.

**MP3 export ceiling:** 320 CBR. Never inflate lossy sources.

---

## 6. Cross-checks (the actual insights)

| Check | Output |
|---|---|
| LMS engine BPM / key vs Rekordbox BPM / key | agreement %, octave errors (×2, ×0.5), Camelot distance histogram. This doubles as the real-library validation of the engine (registry idea `analysis-real-world-validation`) |
| LMS phrases vs Rekordbox PSSI | boundary match within ±1 bar, label agreement |
| Paper tier vs measured cutoff | tier map + `konvertiert` / `aufgeblasen` / `prüfen` lists |
| MyTag "Bad Quality" / "BadFormat" vs measured tier | where the user's tags agree, where they don't |
| LUFS / PLR per genre | loudest and quietest outliers, clipping offenders |
| Phase correlation < 0.2 or low-band correlation < 0.5 | mono-risk list |
| Mood / brightness / bass share per genre and atlas level-1 | genre profiles; tracks far from their genre's profile |
| Rekordbox grid with tempo changes, low `grid_confidence` | grid-check list |
| Audio fingerprint (Chromaprint, if `fpcalc` is approved) vs Stage-B duplicate candidates | real duplicates vs same name / different track |

---

## 7. Plan with done criteria

| Phase | Content | Done when |
|---|---|---|
| P0 | Branch decision (§1.2), registry entry `in_progress` with branch | committed + pushed |
| P1 | Stage B in `library_analysis.py` | tests on synthetic tracks, real run, numbers in report |
| P2 | Stage C port | real run over all files, error list, paper tier per file |
| P3 | Stage D ANLZ reader incl. PSSI unmask | unit test with a masked + plain PSSI fixture built in the test (no user files in the repo); real run; phrase-kind mapping checked against Rekordbox UI on 3 tracks (ask the user for a screenshot) |
| P4 | Stage E runner | `--limit 50` run with timing + peak RSS; then the full run in the background; resume tested by killing it once |
| P5 | Cross-checks + report sections + CSV columns | report renders; every section has real numbers |
| P5b | Analysis depth setting (§3.6) | engine `depth` argument, depth-aware cache, setting in `/api/settings`, settings UI replaces the dead "Analysis Quality" block; per-stage timing at both levels measured on 50 tracks and written into §3.6; engine tests + `audio-stack-reviewer` + `e2e-tester` green |
| P6 (separate, ask first) | Expose measured features to the app (route + sortable columns via `SORT_VALUES` in `trackSort.js`) | start `route-architect` before touching `app/main.py` |

For every phase:

- Run `ruff check` and `ruff format` on the files you changed, plus `mypy` on any new module.
- Run `pytest tests/test_library_analysis.py` and the new test files.
- Run `python scripts/regen_maps.py`.
- Run `python scripts/feature_map.py --check`.
- Add `docs/FILE_MAP.md` rows for new files.
- Finish with an atomic commit and a push.

Registry: keep `library-analysis-report` (`docs/features/analysis.toml`) current: status, `paths`, `todo`, and `notes` with the measured numbers. Relate it to `quality-tiers-audit`, `duplicate-finder` and `analysis-real-world-validation` instead of duplicating them. If you port the scanner, move its `paths` ownership in the same commit.

---

## 8. Known traps

- The full track list is 140 MB and the frontend times out after 10 s. The script uses its own 180 s timeout. Prefer a snapshot (`--save-input`).
- 20 local files are missing on disk. 112 tracks are streams with no file. Skip both in Stages C-E and list them.
- `essentia` is absent, so `key_method` = K-S fallback. Report the method next to key agreement numbers.
- `AnalysisCache` holds 2 old failed entries (LUFS -100). Ignore them; they are not your data.
- `hint_genre` is a crude BPM + brightness rule (`app/analysis_engine.py:2035`). It is not a genre classifier. Show it, but do not treat it as truth.
- Rekordbox may hold files open. ffprobe then fails with an empty body; that is why `rescan_unreadable.py` exists.
- Never "fix" the byte layouts in `app/usb_pdb.py` or the ANLZ writers from this task. Reading only.

---

## 9. First commands

```bash
cd C:\Users\tb\Documents\GitHub\LibraryManagementSystem\.claude\worktrees\library-analysis
```

```bash
.venv\Scripts\python.exe scripts\library_analysis.py --save-input tmp\library-analysis\tracks.json
```

```bash
.venv\Scripts\python.exe scripts\library_analysis.py --input tmp\library-analysis\tracks.json
```

```bash
.venv\Scripts\python.exe -m pytest tests\test_library_analysis.py -q
```
