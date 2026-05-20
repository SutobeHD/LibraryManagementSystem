# Self-Imposed Limits — Audit & Implementation Report

Date: 2026-05-20
Branch: `claude/investigate-track-data-F8dNm`

Trigger: hot cues were hard-capped at 8, but Rekordbox 6/7 + CDJ-3000 support 16
(banks A..H and I..P). Audit looked for every numeric limit our code imposes that
is stricter than the underlying format / hardware actually requires.

---

## Part 1 — Findings

### 1a. Dead settings — config existed but was bypassed

Worst class: a setting suggests configurability, but the code path ignores it.

| Setting | Defined | Bypassed by |
|---|---|---|
| `cue_max_hot` | `analysis_settings.py` (env `RB_ANALYSIS_CUE_MAX_HOT`) | `anlz_writer._build_pcob` / `_build_pco2` (`[:8]`), `phrase_generator` (`_MAX_HOT_CUES=8`), `main.py` (`min(written, 8)`) |
| `phrase_bars` | `analysis_settings.py` (env `RB_ANALYSIS_PHRASE_BARS`) | `analysis_engine.detect_phrases` hardcoded `phrase_bars = 8` |

### 1b. Real restrictions tighter than Rekordbox / CDJ

| Limit | Where | Was | Format / hardware truth |
|---|---|---|---|
| Hot cues | 5 code sites | 8 | 16 (CDJ-3000, Rekordbox 6/7) |
| UI hot-cue slots | WaveformEditor + DAW | 8 | needs 16 |
| Memory cues | `cue_max_memory` | 16 | ANLZ has no limit; spacing is the real bound |
| Long-file analysis | `audio_analyzer.py` | speed 120 s / legacy >200 MB→600 s, silent | should be reported / configurable |
| BPM output fold | `bpm_output_min/max` | 80–180 | debatable; folds reggae/hip-hop/uptempo |
| USB filename segment | `usb_manager.py` | 40 chars | exFAT allows 255 |

### 1c. Excluded (left unchanged — intentionally)

- **Playlists < 5 tracks** (`services.py:XMLProcessor.MIN_TRACKS_THRESHOLD`) — used
  only to gate Artist/Label playlist generation in `XMLProcessor.process`.
  Confirmed scoped to that view; left as-is per request.
- **Format-locked limits** — PWAV 400 / PWV2 100 / PVBR 400 / `detail_fps` 150,
  USB volume label 11 (FAT32), PDB page 4096 + row-group 16, rating 0–5, waveform
  byte clamps 0–255. These match the target binary format and must NOT change.

---

## Part 2 — Implementation

| Change | File(s) | Before → After |
|---|---|---|
| Hot-cue cap (setting) | `analysis_settings.py` | `cue_max_hot` 8 → 16 |
| Hot-cue cap (ANLZ writer) | `anlz_writer.py` | new `REKORDBOX_MAX_HOT_CUES = 16`; `[:8]` → `[:REKORDBOX_MAX_HOT_CUES]` in `_build_pcob` + `_build_pco2` |
| Hot-cue cap (phrase → DB) | `phrase_generator.py` | `_MAX_HOT_CUES = 8` → public `MAX_HOT_CUES = 16` |
| Hot-cue cap (route report) | `main.py` | `min(written, 8)` → `min(written, MAX_HOT_CUES)` |
| Memory-cue cap | `analysis_settings.py` | `cue_max_memory` 16 → 40 |
| `phrase_bars` bypass fixed | `analysis_engine.py` | hardcoded `8` → `_S.phrase_bars` |
| BPM output fold widened | `analysis_settings.py` | `bpm_output_min/max` 80/180 → 60/200 |
| Speed cap configurable + logged | `analysis_settings.py`, `audio_analyzer.py` | hardcoded `120.0` → `speed_mode_duration_cap_s` setting; `_speed_mode_cap()` logs at INFO |
| Legacy truncation logged | `audio_analyzer.py` | silent >200 MB cap → WARNING log |
| UI hot cues — WaveformEditor | `useWaveformInteractions.js`, `WaveformControls.jsx` | 8 colors → 16 + `MAX_HOT_CUES`; both `[1..8]` strips → 16 slots (A..P) |
| UI hot cues — DAW | `helpers.js`, `cues.js`, `DawControlStrip.jsx`, `dawReducer.test.js` | `hotCues[8]` → `[16]`, 8 colors → 16, `cp.num < 8` → `< 16` |
| USB filename segments | `usb_manager.py` | artist/title `[:40]` → `[:80]` |

---

## Part 3 — Caveats / verification

- **CDJ hardware:** PCPT `hot_cue` field is a `u32` — values 1..16 fit the ANLZ
  format. CDJ-3000 reads all 16; CDJ-2000NXS2 and older read only the first 8 and
  silently ignore I..P. Cross-check 16-cue export on real CDJ-3000 hardware.
- **rbox path:** `commit_cues_to_db` writes hot cues to `master.db` via
  `rbox.MasterDb.set_hot_cues`. rbox 0.1.x accepting 16 slots is unverified; a
  failure surfaces as HTTP 503 from the route. The ANLZ-file path (our own writer)
  fully supports 16 regardless.
- **BPM 60–200 is a DSP behavior change** (user-approved): tracks at 60–79 BPM
  keep their tempo instead of folding up; 181–200 BPM keep tempo instead of
  folding down. Tradeoff: residual half-time misdetections landing in 60–80 are no
  longer auto-doubled by the final fold. The `onset_density` step still does the
  primary octave correction before this fold.
- **Hotkeys stay 1–8** (bank 1) in both editors — number keys cannot address
  9–16. Slots I..P are click-only. A bank toggle is possible future work.
- **DAW is the canonical cue subsystem** — both editors now use 16 for
  consistency.

---

## Part 4 — Configurability

All limits below are overridable via `RB_ANALYSIS_<NAME>` environment variables
(`analysis_settings.py`):

| Env var | Default |
|---|---|
| `RB_ANALYSIS_CUE_MAX_HOT` | 16 |
| `RB_ANALYSIS_CUE_MAX_MEMORY` | 40 |
| `RB_ANALYSIS_BPM_OUTPUT_MIN` | 60 |
| `RB_ANALYSIS_BPM_OUTPUT_MAX` | 200 |
| `RB_ANALYSIS_PHRASE_BARS` | 8 (now actually wired) |
| `RB_ANALYSIS_SPEED_MODE_DURATION_CAP_S` | 120 |

`REKORDBOX_MAX_HOT_CUES` (`anlz_writer.py`) is a hard format ceiling, not a
tunable — it is the absolute maximum the ANLZ format / CDJ-3000 support.
