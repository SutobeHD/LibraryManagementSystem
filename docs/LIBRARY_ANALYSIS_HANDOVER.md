# Handover — full library measurement (library analysis v2)

**For:** a fresh Claude instance with no prior context.
**From:** session of 2026-11-08 that built v1 (`scripts/library_analysis.py`).
**User:** tb. Talks German. Wants every claim measured, not assumed ("Teste immer selber"). Short sentences, tables, paste-ready commands, one command per block (the user switches between cmd and PowerShell; `&&` and `;` each break in one of them).
**Goal (user's words, 2026-11-08):** "Ich will das volle Ausmaß, alles messen was geht." Measure everything that can be measured about the user's library: metadata, file properties, Rekordbox's own analysis data, and the audio itself. Then cross-check the sources against each other. The user also wants a setting for how deep a track is analysed: **Rekordbox level or high level** (§3.6). Later the user wants to sort by **individual sound parts**: similar basses, bass depth, bells, hi-hat amount, similar hi-hats, how melodic, melody type, similar melodies. That block is to be **planned, not built** (§9).

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
| Quality scanner (ffprobe) | `scripts/dev/scan_audio_quality.py` (230 lines, CLI `root --out --workers`) + `scripts/dev/rescan_unreadable.py` (138 lines), on `feat/artist-hub` (commit `15fb92f`) **and on PR #60** (checked 2026-11-08); not on `feat/library-analysis` | registry `quality-tiers-audit`, `in_progress` |
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

**Dry run (2026-11-08, `git merge-tree --write-tree`, nothing checked out):**

- PR #60 contains all of `main` (0 commits behind) and `app/genre_atlas.py` + `app/data/genre_atlas.json`.
- `feat/library-analysis` has 7 commits PR #60 lacks: `d520daf` (script + tests) and 6 docs commits (registry, handover).
- Cherry-pick of `d520daf` onto PR #60: **clean**. Merge of the whole branch onto PR #60: **0 conflicts.**
- So either path works without conflict: rebase the 7 commits onto `origin/claude/dreamy-planck-w7771v`, or a new branch from PR #60 + cherry-pick. Both are rebase/cherry-pick operations → user's go-ahead first.

Fresh worktree: `npm install` is not needed (Python only). Use the main checkout's `.venv` through a junction: `cmd //c "mklink /J .venv C:\Users\tb\Documents\GitHub\LibraryManagementSystem\.venv"`.

### 1.3 Environment (measured 2026-11-08)

- `.venv` is CPython 3.11. `AnalysisEngine.capabilities()` = madmom RNN beats, **no essentia** (no Windows wheel), so key detection uses the K-S + Temperley fallback.
- **`import madmom` on its own fails on 3.11** (`ImportError: cannot import name 'MutableSequence' from 'collections'`). It only works after `app/analysis_engine.py:_apply_madmom_compat_shims` ran: import the engine first (`from app import analysis_engine as ae; ae._ensure_libs()`), also in every worker process.
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

#### 3.4.1 Built and measured (2026-11-08) — `scripts/library_measure_anlz.py`

Spike exists: module + CLI (`--input --db --limit --out --summary-only`), 23 tests in `tests/test_library_measure_anlz.py` (synthetic PMAI/PSSI/PQTZ/PQT2/PPTH/PCOB/PCO2/PWV5/6/7/PWVC builders, no user files). ruff + mypy clean (mypy reports one **pre-existing** error in `app/anlz_writer.py:604`, untouched). Output: `tmp/library-analysis/measure/anlz.jsonl` (11.6 MB, one row per track incl. error rows).

**Full-library run (read-only):**

| Measurement | Value |
|---|---|
| `resolve_anlz_paths` | 4764 of 4765 snapshot tracks in 0.30 s (1 SoundCloud stream without path; 111 streams **do** have ANLZ) |
| Files present | DAT / EXT / EX2 4764 each (100 %) |
| Runtime | 200 tracks 10.6 s; **all 4765 in 216 s** (22/s, single process) |
| Status | ok 4754, partial 10, no_anlz_path 1, **0 file errors** |
| Tag errors (pyrekordbox `Const` too strict) | `PQT2 u1` 9× (0x02000002 instead of 0x01000002), `PCPT u1` 2× (0x100000 instead of 0x10000). Tolerant parse keeps every other tag; PQT2/PCOB read raw |
| Tag sets | DAT `PPTH,PVBR,PQTZ,PWAV,PWV2,PCOB,PCOB` 4763/4764; EXT standard 4722, 21 without PQT2, 20 without PSSI; EX2 `PPTH,PWV7,PWV6,PWVC` 4764/4764 |
| Grid | missing in 3 (PQTZ with 0 entries; 2 of them also all-zero PWV7 → probably broken audio). Beats min 5 / median 745 / max 18173. First downbeat median 46 ms, p90 878 ms, > 2 s: 4 |
| Tempo changes | 9 tracks. 8 carry PQT2 flag **0x02000002** (13-59 distinct BPM, 71-208 switches), 1 with 0x01000002 (1 switch 53.97 → 215.88). 1 track has 0x02000002 without changes. → high byte 02 = variable-tempo marker (8/9, measured, no spec) |
| Cues | **0 hot cues in the whole library**, memory cues in 1 track (23), 0 loops, 0 comments, 0 colours |
| PSSI | present 4744; **masked 2584 (54.5 %) / plain 2160**. Moods high 3954 / mid 772 / low 18. Phrases min 3 / median 18 / max 431 (91-min mix). Intro bars top: 8 (1279), 16 (817), 4 (558). Outro bars top: 8 (822), 16 (416). Fills in 3822 tracks. After unmask every mood is 1..3 and beats ascend |
| Writer guess | rekordbox 4749, conflict 15, **lms 0**. Signals: PSSI header layout (LMS `end_beat` @0x16 vs RB @0x1A + u2=1), PWVC payload (LMS zeros, RB e.g. `0050 006f 006d`), PQT2 u3 (LMS 0). The 15 conflicts = PQT2 u3 == 0 with otherwise RB signals → **u3 vote unreliable**. File header u1..u4 and tag order are identical for RB and LMS → no signal. No real LMS file in the library → heuristic tested against synthetic files only |
| PPTH | DAT: `?/<file name>` 1587, empty 1440, **extension mismatch 1732** (PPTH `.m4a`, file `.aiff` → analysis predates the conversion), full path 5. EX2: mismatch 2710, basename 1587, full 466 |

**PWV6 / PWV7 layout (numbers):**

- PWV7: header 24, `len_entry_bytes` = 3, `tag_len − 24 == 3 × len_entries` in every sample; **frames == PWV5 frames in 4764/4764**; `frames / 150 − TotalTime` median +0.47 s (p5 0.05, p95 0.95, none > 2 s) → 150 half-frames/s verified. Byte max 127 (7 bit).
- PWV6: header 20, always 1200 frames = 3600 bytes (4764/4764), byte max 116.
- **Band order [low, mid, high] measured:** byte 0 correlates +0.75 with PWV5 red, byte 1 +0.44 green, byte 2 +0.54 blue (30 tracks); PWV6 vs PWV4 d3/d4/d5: +0.87 / +0.44 / +0.48. Assumes Rekordbox RGB = red low / green mid / blue high. **Contradicts the djl-analysis text** ("mid, high, low"); LMS writer and rbox say [low, mid, high] and the numbers agree. Means low 52.6 / mid 36.9 / high 15.1; bass_share median 0.50 (0-0.75), brightness median 0.135. Byte scaling (linear vs non-linear) **not** verified — assumed linear.

**3 tracks for the Rekordbox-UI check of the kind → label mapping (§2), ask the user for screenshots:**

- high: "MODE_1_Need _T1C7#005_preview" – T1-C7 Records, ID 157309106, 142 BPM, masked: kinds `1,5,5,2,5,5,5,6` → Intro, Chorus×2, Up, Chorus×3, Outro (k1k2k3 `000,100,100,010,100,100,100,100`).
- mid: "I'll Be Your Only Friend - Radio Mix" – Flamman/Abraxas, ID 235643068, 170 BPM: `1,2,3,4,9,3,5,6,3,3,3,9,8,9,3,9` → Intro, Verse1-3, Chorus, Verse2, Verse4, Verse5, Verse2×3, Chorus, Bridge, Chorus, Verse2, Chorus.
- low: "Wanna Be Down" – Karl Seery, HZRX, ID 80581211, 130 BPM: `1,2,8,3,3,4,8,8,5,9,9,9,9,10` → Intro, Verse1, Bridge, Verse1×3, Bridge×2, Verse2, Chorus×4, Outro.

**Open points:**

- After unmask, `bank` ≠ 0 (230-255) and `u1` ≠ 0 in 2573 of 2584 masked files; 0 in every plain file. Entries are plausible → either real extra data in RB 7 or the mask does not cover header bytes 0x14-0x1F correctly. Deep Symmetry notes the same "unexpected" bank values. Don't rely on `bank`/`u1` from masked files.
- High-mood variants (Intro 1/2, Up 1-3, Chorus 1/2 via k1-k3) not mapped — source adoc 404; `kind_variants` kept raw in the JSONL.
- Label mapping unverified against the Rekordbox UI (P3 criterion).
- The pre-existing `tests/conftest.py` import prints `LMS_TOKEN=…` into captured stdout — not from this work, but it violates the never-log rule; worth a separate fix.

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
- **Sleep:** Windows sleep kills the night run. Tell the user to keep the machine awake, or use the app's keep-awake tool (`mcp__ccd_host__request_keep_awake` exists in the desktop app's tool list, checked 2026-11-08).

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

#### 3.6.1 Verified against the code (2026-11-08, HEAD `d040bad` + PR #60)

`analysis_engine.py`, `anlz_sidecar.py`, `analysis_settings.py` identical on both branches. PR #60 differs in `analysis_cache.py` (adds `WaveformCache`), `main.py`, `services.py`, `analysis_db_writer.py`, `audio_analyzer.py`.

**Settings storage**

- `SettingsManager` = `app/services.py:772`; `DEFAULT` :774-793; `load()` :843 merges `{**DEFAULT, **sanitized}`; `save()` :873 atomic tmp + `os.replace`. `CONFIG = Path("settings.json")` is **relative to the cwd** (:773).
- `GET /api/settings` `main.py:3015` (PR #60 :4928). `POST` :3022 → `SetReq.model_dump()` + `model_extra` → `save(payload)`: **replaces the whole file, no merge**.
- `SetReq` (`main.py:409`) is `extra="allow", strict=True` → unknown keys persist. `analysis_quality` is therefore stored in `settings.json` today although 0 backend reads exist (both branches).
- `get_settings()` (`app/analysis_settings.py:129`) = frozen dataclass from `RB_ANALYSIS_*` env only. Never reads `settings.json`. **`analysis_depth` does not belong there.**
- Build: `analysis_depth: _Literal["rekordbox","high"] | None = None` in `SetReq` (pattern: `sc_download_format` :442), `"analysis_depth": "rekordbox"` in `SettingsManager.DEFAULT`.

**Frontend**

- "Analysis Quality" block = `SettingsAnalysis.jsx:16-37`, `set('analysis_quality', …)` :26. Default `SettingsView.jsx:69`.
- Load: `api.get('/api/settings')` inline in `SettingsView.jsx:132`, merged `{...DEFAULTS, ...res.data}`. Save: `api.post('/api/settings', settings)` :157 sends the whole object.
- Build: replace the block, add `analysis_depth: 'rekordbox'` to DEFAULTS, drop `analysis_quality` from DEFAULTS (optionally strip it on load).

**Engine stages (`run_full_analysis` :2323-2576)**

| emit | Output | Level |
|---|---|---|
| `load` 5/15 | load; **`compute_stereo_features` inline at :2401** (no own emit) | stereo = high |
| `beats` 20/45 | bpm, beats, downbeat, grid_confidence | RB |
| `key` 50/60 | key | RB |
| `waveform` 65/80 | `generate_waveform_data(y, sr)` | RB |
| `phrases` 82/88 | phrases | RB |
| `tempo_grid` 89 | tempo_anchors | RB |
| `pvbr` 91 | pvbr | RB |
| `lufs` 93 | lufs, replay_gain | high |
| `mood` 94 | `detect_mood(y, sr, bpm, lufs)`, `hint_genre` | high |
| `cues` 95 | hot/memory cues from phrases + beats | RB |
| (no emit) | peak = `max(abs(y))` :2490 | ~free; keep in RB |

- **No RB stage depends on a high output.** `detect_phrases` computes its own per-phrase `mood` from energy (:1427), independent of track mood → PSSI unaffected (`anlz_writer.py:602`). The split is clean.
- Downstream defaults when lufs/peak are missing: `analysis_db_writer.py:159` (-100), `services.py:1016-1017`, :1255-1256, :1362-1363 → import metadata Loudness/Peak = 0 at RB depth.

**Cache (`analysis_cache.py`)**

- Key = absolute path; valid if `version` + `size` + `mtime` (±1 s) match (:65-78). `USE_CONTENT_HASH=False` (:34) → the toml desc "per Content-Hash" is wrong. `ANALYSIS_VERSION = 3` (:32).
- `get` returns the stored dict as-is; `put` is per path (one entry per file). **Errors are never cached** (`put` only in the success branch :2563).
- Existing bug, same root as the depth problem: on a hit, `auto_hot_cues` / `auto_memory_cues` / `memory_cue_grid` arguments are ignored.
- Build: store `result["depth"]`; `get(file_path, min_depth)` with rank `{"rekordbox": 0, "high": 1}`; entries without `depth` count as `high` (today's result already carries lufs/mood/stereo) — or bump `ANALYSIS_VERSION` to 4 (full re-analysis). **A RB run must not overwrite an existing high entry** (`put` guard) — not in the original design.

**Callers of `run_full_analysis`** (handover list was incomplete)

| Caller | HEAD | PR #60 | Settings today |
|---|---|---|---|
| `analysis_db_writer` | :126 direct, same process | :204 `_run_analysis` via executor (entry :137, batch :364) | none |
| `anlz_sidecar` | :52 | :52 | none |
| `audio_analyzer.analyze_track` / `analyze_sync` | :85 / :115 | :134 / :165 | `mode` speed (default, `main.py:590`) → `duration_cap=120` → **no cache** |
| `services.BeatAnalyzer.analyze` | import :948, **call :972** | import :1067, **call :1091** | none |
| `soundcloud_downloader` | **:1453** | **:1525** | none — **missing from the original list** |
| `AnalysisEngine.submit` / `analyze_sync` | :2206 / :2235 | same | `submit` has **no callers**; `run_quick_analysis` only called from `submit` → dead |

- `submit` passes args **positionally** `(file_path, None, True, None, hot, mem, grid)` — append `depth` as the **last** keyword parameter or the positions shift.
- Analysis runs in worker processes; reading `settings.json` there depends on the relative cwd. Read `depth` **once per job in the main process** and pass it: `analyze_batch` / `analyze_and_save`, import path `services.py` ~:1263 / :1382 (PR #60), SC download, sidecar. `write_companion_anlz` (`services.py:1451`) re-analyses with `None` → becomes a cache hit with the depth-aware cache.
- `audio_analyzer` `mode` speed/accuracy is a **second half-dead quality knob** (120 s cap, no cache). Merge into depth or remove — decision needed.

**Open decisions for the user (§3.6)**

1. Keep `peak` in the RB level (near-free, feeds import "Peak")?
2. Import "Loudness" at RB depth: write 0 or compute lufs anyway?
3. Old cache entries: treat as `high`, or bump `ANALYSIS_VERSION` → 4 (full re-analysis)?
4. `audio_analyzer` `mode` speed/accuracy: fold into depth or delete?
5. Fix the cue-toggle cache bug in the same change?
6. Actively strip `analysis_quality` from existing `settings.json` files?

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
| P7 (plan only) | Sound-component sorting (§9): research doc, user's answers, measured isolation choice, per-wish feature definitions | doc reaches the approval gate; no code before the user approves |
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
- **On `feat/library-analysis` the backend already returns the light shape** (measured 2026-11-08: 4765 tracks, 3.5 MB, 0.2 s, `beatGrid` present for 0 tracks, `Cues` present for 700). "beatGrid present" (§3.2 preparation state) is therefore unavailable from the track list on this branch; take grid presence from Stage D (PQTZ) instead.
- 20 local files are missing on disk. 112 tracks are streams with no file. Skip both in Stages C-E and list them.
- `essentia` is absent, so `key_method` = K-S fallback. Report the method next to key agreement numbers.
- `AnalysisCache` holds 2 old failed entries (LUFS -100). Ignore them; they are not your data.
- `hint_genre` is a crude BPM + brightness rule (`app/analysis_engine.py:2035`). It is not a genre classifier. Show it, but do not treat it as truth.
- Rekordbox may hold files open. ffprobe then fails with an empty body; that is why `rescan_unreadable.py` exists.
- Never "fix" the byte layouts in `app/usb_pdb.py` or the ANLZ writers from this task. Reading only.

---

## 9. Sound-component sorting — wishes to plan, not solved here

The user stated these on 2026-11-08 and asked explicitly that they be **recorded, not solved**, so that you can plan them without hurdles. Your job for this block is a plan (phase P7), not code. The user's words:

> "Ich möchte am Ende zum Beispiel auch nach gleichen Bässen sortieren können oder Bässen mit einer gewissen Tiefe, dann will ich z.B. auch nach Bells sortieren können, nach Hi-Hat-Anteil und gleichen Hi-Hats oder so und wie melodisch und was für Melodien und nach ähnlichen Melodien z.B."

"Zum Beispiel" and "oder so": these are examples of a direction. The direction is **sorting by individual sound components of a track**, not only whole-track features. Plan for the direction, starting with these eight.

### 9.1 The wishes, split by kind of sort

Two kinds of sort hide in the list:

- **Value:** a number per track, so it becomes a sortable column.
- **Similarity:** "like this track", so it needs a seed track and a ranking.

| # | Wish (user's word) | Kind | Signal it needs | Open question for the user |
|---|---|---|---|---|
| W1 | gleiche Bässe | similarity | bass part isolated: sound (timbre) and/or line (rhythm, notes) | similar *sound*, similar *line*, or both? Kick included or not? |
| W2 | Bässe mit einer gewissen Tiefe | value | how low and how strong the bass is | "Tiefe" = pitch in Hz, sub-bass amount, or length/boom of the bass? |
| W3 | Bells | value (amount), maybe similarity | detection of bell-like sounds | which sounds count (bell synth, tubular bell, metallic pluck, cowbell)? 5 example tracks with, 5 without |
| W4 | Hi-Hat-Anteil | value | hi-hat part isolated: loudness and/or density | loudness, density (8ths / 16ths / offbeat), open vs closed? |
| W5 | gleiche Hi-Hats | similarity | hi-hat sound and/or pattern | sound or pattern? |
| W6 | wie melodisch | value | amount of pitched / tonal content vs percussive | is a pad / chord bed "melodic", or only a lead line? |
| W7 | was für Melodien | category | melody type per track | which categories (e.g. arpeggio, lead, chords/pad, acid line, vocal hook)? The user names them |
| W8 | ähnliche Melodien | similarity | melody line isolated, as a note sequence or contour | same notes or same feel? Does a transposed melody count as similar? |

Ask the 8 questions as **one numbered list** in German; the user answers numbered lists fast. Add these two:

- **(9)** Is a new dependency (torch, a source-separation model) OK, and may it use the GPU?
- **(10)** Does this belong to the "Hoch" depth level (§3.6), or a third level such as "Maximal"?

### 9.2 Hurdles the plan must clear (facts, measured 2026-11-08 unless marked)

| Hurdle | Fact | Consequence for the plan |
|---|---|---|
| Parts are mixed together | W1, W4, W5, W6-W8 need the bass, the hi-hats or the melody **separately**. The engine today only has whole-track features plus band energy (§3.5 E6/E7) | Choose how to isolate the parts. Approach families, none chosen or tested: frequency-band heuristics (no deps, crude: kick and bass share a band); harmonic/percussive split (`librosa.effects.hpss`, installed, crude); model-based source separation (e.g. Demucs class, needs torch). Benchmark on the user's example tracks before you decide |
| No ML stack installed | `.venv` has librosa, madmom, numba, sklearn. **Not** installed: torch, torchaudio, demucs, onnxruntime, tensorflow, crepe, essentia (no Windows wheel), faiss, hnswlib | Every model-based path is a **new dependency**. It needs the user's approval, exact pinning (`requirements.txt` `==`, `.claude/rules/coding-rules.md`), and a check of installer size (`backend.spec`) |
| torch decision already pending elsewhere | `docs/research/implement/inprogress_recommender-taste-llm-audio.md` gates torch at its M2 benchmark (CLAP / MERT embeddings). It estimates the installer at +200-500 MB (from that doc, not re-measured) | Make **one** torch decision for both features. Read that doc first; do not contradict it |
| Similarity storage already planned | `docs/research/implement/accepted_recommender-similar-tracks.md` (accepted, 0/12 tasks) plans a whole-track vector (about 46 dims: MFCC, chroma, spectral, BPM, key, LUFS). It is stored in `app_data/track_vectors.db` as **named slices** so reasons ("similar bass") can be computed per slice | Component similarity (W1, W5, W8) = **more named slices** (bass, hats, melody) in the same store. Extend that plan; do not build a second store |
| Hardware | GPU: NVIDIA RTX 2070 SUPER, 8 GB, driver 617.14. CPU: 16 cores / 32 threads. RAM: 62 GB | Measure CPU vs GPU time on 10 tracks before you estimate the full run. The base audio pass alone is about 53 CPU-hours (§3.5) |
| Disk | Storing separated parts as audio: 392.5 h × 4 stems at 44.1 kHz 16-bit stereo = about **1 TB**. Free on the home drive: 178 GB | **Never persist stems.** Separate, extract features, discard, in the same worker |
| Melody pitch tracking | `librosa.pyin` is installed (slow; time not measured here). Model trackers (CREPE etc.) need torch or TF. essentia's melody extractor is unavailable on Windows | Plan the pitch tracker together with the separation decision, since a pitch tracker works far better on an isolated melody part |
| Instrument detection (W3 bells, W4 hats) | No tagger installed. Choices: a pretrained sound-event tagger (dependency), handcrafted detectors (e.g. inharmonic partials for bells, high-band onsets for hats), or a small classifier trained on the user's labelled examples (sklearn installed) | The user's example tracks (questions 3-5) are the ground truth for any choice |
| Ground truth | The user's rule is to measure, not assume. No labelled set exists | First plan step: collect from the user 10-20 example tracks per wish (and pairs that "sound alike") and keep them as the evaluation set. Store only track IDs, never audio, in the repo |
| UI fit | TrackTable sorts by one value per column (`SORT_VALUES` in `frontend/src/utils/trackSort.js` on `feat/sortable-columns`) | Value wishes (W2, W3, W4, W6) become columns. Similarity wishes (W1, W5, W8) need a new action, "Nach Ähnlichkeit zu diesem Track sortieren" (bass / hats / melody). Category W7 becomes a filter or column. Plan both paths |

#### 9.2.1 Hurdles measured (2026-11-08, read-only, nothing installed)

Setup: `.venv` py3.11, librosa 0.10.1, scipy 1.11.4, numpy 1.26.4, `*_NUM_THREADS=1`, mono 44.1 kHz. CPU ≈ wall everywhere (single-thread). Tracks: Delusion (SERA J, ID 58442992, 294 s AIFF 48k), Onyra (Triptykh, 177985252, 286 s WAV), Initial Spark (Kobosil, 6009916, 300 s AIFF 48k).

**Baseline "no new dependency", CPU seconds per track (3 tracks, min-max):**

| Step | CPU s | Note |
|---|---|---|
| `librosa.load` mono 44.1k | 0.1-0.2 (1.4 first call, JIT) | |
| `librosa.effects.hpss` full track | 18.9-20.3 | **peak RSS 1.86-1.91 GB** per process (STFT + median filter) → 12 workers ≈ 23 GB (estimate) |
| `hpss` 60 s excerpt | 3.4 | |
| 4-band butterworth + RMS env + onsets | 2.7-2.9 | |
| `librosa.pyin` 30 s (65-2093 Hz) | 7.6-8.4 | full track = 73-83 s (estimate, linear) |
| `chroma_cqt` + `mfcc` 44.1k | 1.8-1.9 | at 22.05k: 0.9. The similar-tracks doc's "+0.30-0.45 s/track" (`accepted_recommender-similar-tracks.md:75`) is ~2× too optimistic |

Band raw values (hats proxy): > 6 kHz RMS share -16 … -18.5 dB; high-band onsets/s 6.0 / 5.3 / 2.6 (at 145-157 BPM 8ths ≈ 5/s, 16ths ≈ 10/s → plausible density scale). Sub < 60 Hz gave 10.8-13.4 onsets/s against a 4/4 kick at 2.5/s → the default onset picker **massively over-fires in the lowpass band**; tune peak picking per band. `pyin` voiced share 0.39 / 0.59 / 0.39 — in the mix the kick/bass region dominates, so pyin on the mix is no melody measure without isolation.

**Library extrapolation (estimate; 392.9 h / 4633 files / Ø 305 s; linear, ideal parallel):**

| Step | CPU-h @1 worker | wall-h @12 |
|---|---|---|
| hpss full | 26.4 | 2.2 |
| hpss 60 s/file | 4.4 | 0.4 |
| 4-band split + env + onsets | 3.8 | 0.3 |
| pyin full track | **103** | 8.6 |
| pyin 30 s/file | 10.2 | 0.9 |
| chroma_cqt + mfcc 44.1k / 22.05k | 2.4 / 1.2 | 0.2 / 0.1 |
| **Combo A** load + bands + hpss full + chroma/mfcc 44k | 33 | 2.8 |
| **Combo B** = A + pyin full | 137 | 11.4 |
| **Combo C** load + bands + hpss 60 s + chroma/mfcc 22k + pyin 30 s | 20 | 1.7 |

Reference: base audio pass (§3.5) 53 CPU-h → Combo A = +63 %, Combo B = ×2.6. pyin on full tracks is out; use excerpts or an isolated melody part.

**Dependency facts (PyPI JSON + wheel HEAD, exact unless marked):**

| Package | Latest stable | Win cp311 wheel | Notes |
|---|---|---|---|
| torch (PyPI) | 2.15.0 (2026-10-28), py ≥ 3.11 | 120.8 MiB **CPU-only** | CUDA wheels only on download.pytorch.org |
| torch +cu130 | 2.14.1 | **1.99 GB** | matches the driver |
| torch +cu128 / +cu126 | 2.9.1 | 2.86 GB / 2.58 GB | Windows bundles the CUDA DLLs in the wheel |
| torch +cpu (index) | 2.9.1 | 111 MB | |
| torchaudio | 2.11.1 | 2.2 MB | needs torch ≥ 2.11 |
| demucs | 4.1.0 (2026-07) | 0.1 MiB | deps torch ≥ 2.1, einops, huggingface-hub, julius, lameenc, safetensors, sphn; weights download at runtime, htdemucs ~80 MB, `_ft` ~320 MB (estimate) |
| onnxruntime | 1.31.1 | 14.2 MiB (CPU EP) | GPU EP = `onnxruntime-gpu` + external CUDA/cuDNN DLLs, not checked |
| openunmix | 1.3.0 (2024-04) | < 0.1 MiB | needs torch + torchaudio; umxhq weights ~140 MB (estimate) |

- `nvidia-smi`: driver 617.14, **CUDA UMD 13.4** → cu126-cu130 all runnable. RTX 2070 SUPER = Turing sm_75; CUDA 13 dropped only sm_50-70, so cu130 should work (from memory; verify with `torch.cuda.get_arch_list()` after any install).
- A GPU pin needs `--extra-index-url` + `==X.Y.Z+cu130`; plain `requirements.txt` pinning against PyPI yields the CPU wheel.
- `backend.spec`: `collect_all` for REQUIRED (`librosa, numba, scipy, sklearn, soundfile, audioread, lazy_loader`, line 52) + OPTIONAL (`madmom, essentia`) into a **one-file EXE** (`runtime_tmpdir=None`, `upx=False`, lines 172-183); `release.yml` ships it as `src-tauri/binaries/RB_Backend-<target>`. One-file = full extraction to temp at every start → +2-2.9 GB torch-cu doubles disk and hurts boot; the taste doc's gate "sidecar cold-boot ≤ +5 s" (`inprogress_recommender-taste-llm-audio.md:305`) is directly affected. Missing REQUIRED → `SystemExit` (line 76), so torch would have to be OPTIONAL with a loud warning or every CI build runner pulls the 2 GB wheel. Site-packages today 512 MB (scipy 104, llvmlite 78, sklearn 34).

**Research-doc facts to reuse:**

- torch gate: `inprogress_recommender-taste-llm-audio.md:80` "M2 benchmark gates Option B swap-in"; thresholds :300-307 (installer delta ≤ +400 MB, p95 CPU ≤ 3.0 s, cold scan ≤ 30 h, boot ≤ +5 s, NDCG ≥ +0.10, PyInstaller Win+macOS green); :309 "Any-of-above fail → stay on Option A indefinitely"; :127 assumes "torch wheel ~180 MB" = the CPU wheel. **With a GPU wheel (2.0-2.9 GB) the +400 MB gate is unreachable**; only CPU-torch + model can pass it. :289 benchmark plan assumes "no discrete GPU" — it does not know the RTX 2070 SUPER. Status: `inprogress_` since 2026-05-29, only T1 shipped, M2 never run.
- Named slices: `accepted_recommender-similar-tracks.md:434` "4 named slices (mfcc26/chroma12/spectral4/dynamics4)", columns `mfcc_blob, chroma_blob, spectral_blob, dynamics_blob, vector_version, computed_at` (:450-457), store `app_data/track_vectors.db` (:435), reasons = per-slice cosine subscores (:439, :57, :492), weights :297, `VECTOR_VERSION` bump on any new slice (:484). Task queue :526-537 = **0/12**, none of `app/track_vector_builder.py`, `_store.py`, `recommender_similar.py` exists yet.
- Conflicts to plan around: the backfill "re-decodes via `librosa.load(sr=22050, mono=True)`" (:438) → Nyquist 11 kHz, **hats band 10-16 kHz cut off**; component slices need the 44.1k path. :59 "zero new librosa/numpy feature extraction calls inside the recommender module" → extraction belongs in `track_vector_builder.py`. :445 "Out: sklearn/FAISS/PyTorch (M2/M3)". Taste :67 "GPU optional" → GPU must never be mandatory. Neither doc mentions bass / hi-hat / melody / stems.
- Registry: `sound-component-sorting` exists (`docs/features/analysis.toml`, status `idea`, 4 todos); `recommender-similar-tracks` planned 0/12; `recommender-taste` partial, todo "M2 torch-Dep-Freigabe". `_INDEX.md` has no sound-component doc.

**Instrument detection without a new dependency (sketch, untested):**

- Bells: harmonic part from hpss, STFT peaks 2-6 kHz, partials vs integer multiples of f0 → inharmonicity index; spectral flatness + decay time per peak track (> 300 ms) → "long + metallic"; aggregate share of frames with bell signature → column value; later an sklearn classifier on these features.
- Hi-hat amount: > 6 kHz onset density normalised to BPM (onsets per beat → 8ths / 16ths / offbeat) with per-band tuned peak picking; high-band RMS share (measured -16 … -18.5 dB) + percussive share of hpss in the high band; open vs closed from onset decay length.
- Ground truth from the user: 10-20 track IDs per wish (bells: which sounds count), hats: 5 "many" + 5 "few" + 5 pairs "same hats". IDs only in the repo.

Scratch scripts and raw numbers of this measurement: session scratchpad (`bench_components.py`, `bench_results.json`, `extrapolate.py`), not in the repo.

### 9.3 What the plan must deliver (P7)

- A research doc via `/research-new sound-component-sorting` (`docs/research/README.md`). Put the user's quote above, verbatim, as `## Original Idea`. The remote research routines are dead (memory note 2026-09-03), so run the stages interactively.
- The user's answers to the 10 questions, recorded in the doc.
- The isolation approach chosen **by measurement** on the user's example tracks: quality and time per track, CPU vs GPU. Include the option "no new dependency" as a baseline.
- Per wish: the feature definition, its unit or value range, how it is evaluated against the example set, and the column or similarity slice it lands in.
- Total cost for the whole library (time, RAM, dependency size), and how it fits the depth levels (§3.6).
- How it extends `recommender-similar-tracks` (named slices) and shares the torch decision with `recommender-taste`.
- A stop at the approval gate. The user signs off before any code.

---

## 10. First commands

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
