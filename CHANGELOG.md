# Changelog

## [Unreleased]

- Analysis accuracy + engine fixes:
  - Improved: exact-octave BPM accuracy (Acc-1). `detect_beats_madmom` now
    constrains the madmom DBN tempo window to the octave of a robust coarse
    estimate (librosa log-normal prior) — an "octave prior" that stops the
    tracker locking onto half-/double-time. Measured (synthetic, n=50, madmom):
    seed 11 Acc-1 72%→78%, seed 12 82%→94%; Acc-2 and KEY stay 100%; the
    180-210 BPM band's half-time errors are largely eliminated. (Window never
    binds when coarse + DBN already agree, the common real-music case.)
  - Fixed: `requirements.txt` was missing `rbox==0.1.7` (the Rust-backed package
    that `import rbox` resolves to across 10 modules — MasterDb/Anlz/OneLibrary).
    Only `pyrekordbox==0.1.7` (a *different*, pure-Python package used solely for
    my-settings structs) was pinned, so a clean install left live-DB / ANLZ /
    USB-export features in their soft `rbox=None` fallback.
  - Fixed: produced ANLZ cue entries (PCPT) wrote two wrong constants
    (0x00100000 instead of 0x10000; zero instead of the u2 const 1000), so the
    `.DAT`/`.EXT` files diverged from the Rekordbox cue layout and were rejected
    by strict ANLZ parsers. Now spec-conformant — independently verified by
    pyrekordbox `AnlzFile.parse_file()` parsing all three produced files.
  - Fixed: essentia key names normalized flats→sharps (Eb→D#, …); the active
    essentia path otherwise returned empty Camelot/key_id for ~5 of 12 keys.
  - Fixed: `madmom` RNN beat tracking was dead code on Python 3.10+ (the
    project target) — `import madmom` raised on removed `collections`/`numpy`
    symbols and was silently swallowed, so the librosa fallback always ran.
    `_apply_madmom_compat_shims()` restores the symbols; RNN path now active.
  - Fixed: octave disambiguation counted onset-envelope frames (inflated on
    sharp signals → falsely doubled slow tracks); now counts discrete onset
    events (true onsets-per-beat).
  - Fixed: neutral `minor_bias` (1.10→1.0) — the minor thumb made major triads
    read as their mediant minor (D major→F# minor).
  - Fixed: PSSI phrase ids written per the track mood bank (crate-digger enum);
    previously-invalid ids showed blank/wrong phrase labels on CDJ/Rekordbox.
  - Added: optional 16-bar memory-cue grid for beatmatching
    (`memory_cue_grid` setting / `RB_ANALYSIS_MEMORY_CUE_GRID`).
  - Changed: BPM output range raised to 215 (fast DnB/footwork/hardcore no
    longer octave-folded to half-time).
  - Added: `scripts/compare_rekordbox.py` (A/B accuracy vs a real library) +
    `scripts/selftest_analysis.py` (autonomous synthetic-ground-truth accuracy,
    MIREX Acc-1/Acc-2). Self-test with RNN: BPM Acc-2 100%, KEY exact 100%.
- Added: Phase-1 Bearer-token authentication on 84 mutation endpoints.
  New `app/auth.py` self-generates session token at sidecar boot, captured
  by Tauri stdout reader + dev-middleware fallback. Frontend attaches
  `Authorization: Bearer` via bootstrap promise. New `safe_compare` helper.
  `SHUTDOWN_TOKEN` query-string scheme deleted (redundant under `require_session`).

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
