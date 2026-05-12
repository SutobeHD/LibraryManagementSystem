# Changelog

## [Unreleased]

### Added (behind feature flags — not user-visible yet)
- **WaveformEditor extension** (`docs/research/implement/inprogress_waveform-editor-extensions.md`):
  Soft-DAW-style per-track editor with 4 panels — cues, loops, beatgrid, metadata —
  mounted in both `WaveformEditor` and `daw/DjEditDaw` behind feature flags
  (`FEATURE_CUE_PANEL`, `FEATURE_LOOP_PANEL`, `FEATURE_BEATGRID_PANEL`,
  `FEATURE_METADATA_PANEL`, all `false` in production).
  - Shared state via `useTrackEditorState` hook (Context + `useReducer`).
  - 3-step persistent undo across app restart (`localStorage['trackEditor_v1']`).
  - Audio audition on hot-cue pad clicks (WaveformEditor only).
  - 8-CDJ-color memory-cue palette + 16-color hot-cue surface palette.
  - Active-loop radio invariant (max 1 active per track).
  - Beatgrid: anchor-shift / tap-BPM / per-beat (read-only display).
  - Metadata dual-save to Rekordbox `master.db` + ID3 tags.

### Fixed
- `db.save_track_cues`, `db.get_track_cues`, `db.save_track_beatgrid` were
  referenced from `app/main.py` but did not exist anywhere — every call would
  have raised `AttributeError`. Slice 0–3 of the WaveformEditor extension work
  added minimal JSON-sidecar persistence so the existing endpoints don't crash.

### Changed
- `app/anlz_writer.py`:
  - `_build_pcpt_entry` reads `status` from the cue dict
    (backward-compat default preserves the previous hardcoded behaviour).
  - `_build_pcp2_entry` reads `loop_numerator` / `loop_denominator` from the
    cue dict (default `0`).
- `app/main.py` `TrackUpdateReq` Pydantic model extended with `Title`,
  `Artist`, `Album`, `BPM`, `Key` fields (all optional / nullable).

## v1.0.0-beta — 2026-05-07

First public **beta**. Standalone DJ-library manager that competes with
Rekordbox/Serato while staying open and local-first.

### Workflows fully supported

1. **SoundCloud → Library → USB → Club**
   - SC OAuth login, playlist + likes browser
   - Per-playlist Download button — full pipeline with anonymous fallback
     when SC's v2 API rejects the token
   - Auto-analyse (BPM / Key / Beatgrid / Phrases / Auto-Hot-Cues / Auto-
     Memory-Cues / Waveform via librosa+scipy+numba)
   - Auto-import into library + auto-add to `SC_<playlist-name>`
   - USB-Sync to CDJ-3000 ready stick
2. **Local Files → Library → USB → Club**
   - Drag-drop / folder picker
   - Folder name becomes the playlist; every file (incl. duplicates) is
     bundled into one coherent playlist
   - Same full analyse + ANLZ + auto-add pipeline as SC
   - USB-Sync end-to-end

### Library

- **Standalone XML mode** — full feature parity with Live: create / rename /
  move / delete / duplicate / reorder, folders, smart playlists with
  Rekordbox-XML-spec conditions (BPM, Key, Genre, Rating, DateAdded, …),
  cues + beatgrid persisted on save
- **Live mode** — direct master.db via pyrekordbox
- DBWrapper routes every CRUD operation to the active mode without API
  duplication

### USB Export

- `PIONEER/rekordbox/exportLibrary.db` via rbox.OneLibrary
- `PIONEER/USBANLZ/<bucket>/<hash>/ANLZ0000.{DAT,EXT,2EX}` per track
- Audio copy under `Contents/<Artist>/<Title>`
- Cover artwork copy
- Mode-agnostic LibrarySource abstraction so Standalone-XML works for export
  the same as Live

### UI

- 4-card XML submode picker (New Empty / Standalone / Import / Defined Path)
- Import Manager with 7-stage live pipeline + per-stage timestamps
- Sticky import progress banner — visible on every screen, click to open
  manager
- Click-to-rate (5 stars) + Pioneer color-tag picker (9 colors) inline in
  the track table
- Tokenized search: `bpm:120-130 key:Am genre:techno year:2024 rating:>3`
- Right-click context menus on tracks (9 actions) and playlists (7 actions)
  — both via React portal + document-level capture-listener so they actually
  work in Tauri WebView2
- Edit-mode toggle removed — everything is always editable
- Playlist drag-reorder works (Tauri main-window `dragDropEnabled: false`)
- Player drag-seek with `track.TotalTime` fallback for chunked streams
- Pane height fills full window when no player is shown

### Tauri / Dev

- Debug build auto-spawns Python backend + Vite if their ports are free —
  direct exe launch behaves like `npm run tauri dev`
- Children killed on `RunEvent::Exit`

### SoundCloud

- Optional **Aggressive Download Mode** (hidden setting) — bypasses the
  default snipped-preview gate. Reveal by tapping the dot under "SoundCloud
  Sync" in Settings 5×. Use only for tracks you have a personal right to.

### Known limitations

- USB-Sync requires `pyrekordbox` (`rbox.OneLibrary`) — bundled with the
  release binary
- Manual Hot-Cue editing is post-MVP (auto-cues from analysis only for now)
- Master.db creation without an existing Rekordbox install is post-MVP

### Build & install

- Windows MSI + NSIS installers via `scripts/local-release.ps1`
- No code-signing — SmartScreen warning on first run is expected
- SHA256SUMS published with each release
