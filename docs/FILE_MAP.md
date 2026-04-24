# FILE_MAP.md — RB Editor Pro

> **Read this first.** One-line-per-file map of the entire codebase. Use this to find the right file for any task without searching blindly.
> Last updated: 2026-04-11

---

## Root

| File | Purpose |
|------|---------|
| `CLAUDE.md` | AI agent coding rules, principles, mandatory post-edit workflow |
| `package.json` | Root npm scripts: `dev:full` (starts all), `tauri dev`, `tauri build` |
| `requirements.txt` | Python deps: FastAPI, librosa, scipy, keyring, yt-dlp, python-dotenv |
| `docker-compose.yml` | Docker: backend port 8000 + frontend port 5173 with volume mounts |
| `README.md` | Project overview, features, tech stack, setup instructions |
| `PROJECT_WIKI.md` | Extended feature documentation and architectural detail |

---

## app/ — Python FastAPI Backend

| File | Purpose |
|------|---------|
| `app/main.py` | **All 80+ API routes** — see backend-index.md for full route list. Also contains `validate_audio_path()`, request models, startup event, CORS config, global error handlers |
| `app/config.py` | Path constants: `REKORDBOX_ROOT`, `DB_FILENAME`, `FFMPEG_BIN`, `BACKUP_DIR`, `EXPORT_DIR`, `LOG_DIR`, `TEMP_DIR`, `MUSIC_DIR`, `DB_KEY` |
| `app/services.py` | 11 business logic classes: `XMLProcessor`, `SystemGuard`, `AudioEngine` (FFmpeg), `FileManager`, `LibraryTools`, `SettingsManager`, `MetadataManager`, `SystemCleaner`, `BeatAnalyzer`, `ImportManager`, `ProjectManager` |
| `app/database.py` | `RekordboxXMLDB` — parses Rekordbox XML into in-memory cache; `RekordboxDB` — live SQLite access via rbox. Methods: `load_xml`, `get_tracks`, `get_playlists`, `get_track_details`, `save_xml`, `add_track`, `delete_track`, `save_track_cues`, `save_track_beatgrid` |
| `app/live_database.py` | `LiveRekordboxDB` — thread-safe direct access to Rekordbox `master.db` via rbox library with automatic backup management. Added: `get_analysis_writer()`, `get_unanalyzed_track_ids()` |
| `app/analysis_engine.py` | `AnalysisEngine` (class methods: `submit`, `get_status`, `analyze_sync`) + free `run_full_analysis(path)` — production DSP: madmom RNN beat tracking, essentia key detection, full ANLZ waveform generation (PWAV/PWV2/PWV3/PWV4/PWV5/PWV6/PWV7). ProcessPoolExecutor-based async pipeline |
| `app/analysis_db_writer.py` | `AnalysisDBWriter` — orchestrates: analyze track → write ANLZ files → update master.db. Methods: `analyze_and_save(track_id, force?)`, `analyze_batch(track_ids)` (progress generator), `get_unanalyzed_tracks()` |
| `app/anlz_writer.py` | Binary ANLZ file writer producing Rekordbox-compatible `.DAT`, `.EXT`, `.2EX` files. Public API: `build_dat()`, `build_ext()`, `build_2ex()`, `write_anlz_files(anlz_dir, track_path, analysis_result)`. All tags rbox-validated |
| `app/audio_analyzer.py` | Background analysis worker pool; wraps `AnalysisEngine` for HTTP task tracking with `task_id` polling |
| `app/soundcloud_api.py` | `SoundCloudPlaylistAPI` — SC unofficial v2 API with dynamic client_id scraping, exponential backoff, pagination. Added: `resolve_track_from_url()`, `download_url` in normalized track. `SoundCloudSyncEngine` — fuzzy title/artist matching. `AuthExpiredError`, `RateLimitError` |
| `app/soundcloud_downloader.py` | SC downloader with two-stage acquisition: (1) official `/tracks/{id}/download` when `downloadable=true`, (2) fallback to v2 `media.transcodings[]` (progressive MP3 or HLS→ffmpeg copy-mux) — same signed streams the web player plays. Legal gates: skip snipped previews, honor 401/403, never probe paid quality. Dedup-aware (registry + SHA-256). Auto-organizes files. Post-download: analysis + auto-playlist sort. |
| `app/download_registry.py` | SQLite download registry: dedup by sc_track_id (O(1)) + SHA-256 content hash. Analysis history log. Multi-device via device_id UUID. `init_registry()`, `is_already_downloaded()`, `find_by_hash()`, `register_download()`, `update_analysis()`, `get_history()`, `get_stats()` |
| `app/usb_manager.py` | `UsbDetector` (scan, initialize_usb), `UsbProfileManager` (CRUD for sync profiles), `UsbSyncEngine` (sync_collection, sync_playlists, sync_metadata — lock-file concurrency, XML export w/ control-char sanitization `_xml_safe()`, drive-letter path normalization). `_clean_filename` strips trailing dots/spaces + reserved names (Windows silently drops them). Copy error handler: only real disconnects (drive root missing) abort batch; ENOENT on a single bad filename skips that track and continues. |
| `app/backup_engine.py` | Git-like incremental backup: compressed JSON changesets, HEAD tracking, commit timeline, restore |
| `app/rekordbox_export.py` | Converts `AnalysisEngine` results → Rekordbox XML `TRACK` elements with `TEMPO` nodes and `POSITION_MARK` cues |
| `app/rekordbox_bridge.py` | High-level: export selected tracks → Rekordbox XML; import from XML exports |
| `app/rbep_parser.py` | Parses `.rbep` (Rekordbox Editor Project) XML: volume envelopes, BPM maps, hot cues, memory cues, beat grids |
| `app/xml_generator.py` | `RekordboxXML` — generates valid `DJ_PLAYLISTS` XML from Python track data with dynamic/static beatgrids and cue points |
| `app/sidecar.py` | `SidecarStorage` — persists artist metadata (SoundCloud links, custom fields) in `app_data.json` sidecar file |
| `app/batch_worker.py` | CLI tool for batch track metadata updates (comments/tags) using rbox `MasterDb` — find/replace/append/set operations |
| `app/__init__.py` | Package init (empty) |

---

## frontend/src/ — React Frontend

### Core

| File | Purpose |
|------|---------|
| `frontend/src/main.jsx` | App root: lazy-loaded tab views, session token init, global error boundary, tab router |
| `frontend/src/api/api.js` | **Central Axios instance** — always use this. Handles session tokens, 401 refresh queue, 429 exponential backoff, HttpOnly cookie support, 10s default timeout (disabled for long-running calls like `/api/usb/sync` via `{ timeout: 0 }`), Tauri context detection |
| `frontend/src/index.css` | Global styles (Tailwind base + custom) |

### Audio Engine

| File | Purpose |
|------|---------|
| `frontend/src/audio/DawState.js` | Immutable DAW state reducer: regions, cues, loops, transport, undo/redo via full-state snapshots. `dawReducer`, `cuePointsToState`, `snapToGrid` |
| `frontend/src/audio/DawEngine.js` | Web Audio API playback: `AudioContext` lifecycle, multi-source scheduling, region-based playback |
| `frontend/src/audio/AudioRegion.js` | Non-destructive region data model: source file reference, gain, fades, start/end offset |
| `frontend/src/audio/TimelineState.js` | Timeline: regions, markers, beat grid, playback position, selection state |
| `frontend/src/audio/RbepSerializer.js` | `.rbep` XML parser/serializer: beat↔seconds conversion using tempo maps, `POSITION_MARK` cue handling |

### Utilities

| File | Purpose |
|------|---------|
| `frontend/src/utils/AudioBandAnalyzer.js` | Splits waveform into low/mid/high frequency bands for 3-band visualization |

### Feature Views (Lazy-Loaded Tabs)

| File | Purpose |
|------|---------|
| `frontend/src/components/LibraryView.jsx` | Track browser with filter/search, calls `GET /api/library/tracks` |
| `frontend/src/components/PlaylistBrowser.jsx` | Rekordbox playlist tree navigation, calls `GET /api/playlists/tree` |
| `frontend/src/components/MetadataView.jsx` | Track metadata editor: title, artist, album, genre, comments, calls `POST /api/track/{tid}` |
| `frontend/src/components/TrackTable.jsx` | Reusable sortable track table with Camelot wheel colors, BPM/key display, multi-select |
| `frontend/src/components/Player.jsx` | Compact audio player with play/pause, volume, progress, stream via `GET /api/stream` |
| `frontend/src/components/SoundCloudView.jsx` | SC track search and preview interface |
| `frontend/src/components/SoundCloudSyncView.jsx` | SC sync: match SC tracks to library, trigger download, preview matches |
| `frontend/src/components/SoundCloudProgressModal.jsx` | Download progress overlay with per-track status |
| `frontend/src/components/UsbView.jsx` | USB device manager: detect drives, sync profiles, trigger `POST /api/usb/sync` (no timeout for long-running syncs), progress streaming |
| `frontend/src/components/BackupManager.jsx` | Library backup/restore: timeline view, create snapshots, `POST /api/library/backup` |
| `frontend/src/components/XmlCleanView.jsx` | Rekordbox XML cleanup/validation tool, calls `POST /api/xml/clean` |
| `frontend/src/components/InsightsView.jsx` | Library analytics: low quality, no artwork, lost tracks, bitrate stats |
| `frontend/src/components/RankingView.jsx` | Track ranking/sorting by quality metrics |
| `frontend/src/components/ImportView.jsx` | Import wizard: add tracks from file or API |
| `frontend/src/components/SettingsView.jsx` | **Tabbed** preferences panel (8 tabs): Library, Backup, Export, Audio (CPAL device), Analysis quality, Appearance (band colors + locale), Shortcuts (key capture), Network (proxy). Calls `GET/POST /api/settings`. |
| `frontend/src/components/ToolsView.jsx` | Batch operations: rename, clean titles, find duplicates, batch comments |
| `frontend/src/components/DesignView.jsx` | UI theme/design preview and customization |
| `frontend/src/components/WaveformEditor.jsx` | Legacy waveform editor (superseded by `DjEditDaw`) |

### Shared UI Components

| File | Purpose |
|------|---------|
| `frontend/src/components/ToastContext.jsx` | Toast notification provider — `useToast()` → `toast.success/error/info()` — never use `alert()` |
| `frontend/src/components/BatchEditBar.jsx` | Batch editing toolbar for multi-track operations (operates on selection) |
| `frontend/src/components/RenameModal.jsx` | Modal dialog for renaming items, props: `isOpen`, `onConfirm`, `currentName` |

### DAW Editor (`daw/`)

| File | Purpose |
|------|---------|
| `frontend/src/components/daw/DjEditDaw.jsx` | **Root DAW container** — orchestrates toolbar, timeline, browser, palette, transport |
| `frontend/src/components/daw/DawToolbar.jsx` | DAW toolbar: save/open/export/edit-mode buttons |
| `frontend/src/components/daw/DawTimeline.jsx` | Timeline canvas: regions, beat grid, playhead display + interactive cue/beatgrid editing |
| `frontend/src/components/daw/DawBrowser.jsx` | Media browser sidebar for selecting/loading tracks into DAW |
| `frontend/src/components/daw/DawControlStrip.jsx` | Control strip: track info, BPM display, playback transport, snap-to-grid toggle |
| `frontend/src/components/daw/DawScrollbar.jsx` | Custom horizontal scrollbar for timeline navigation |
| `frontend/src/components/daw/WaveformOverview.jsx` | Mini-map waveform overview for quick timeline navigation |
| `frontend/src/components/daw/ExportModal.jsx` | Export dialog: region range, fade settings, format options |

### Non-Destructive Editor (`editor/`)

| File | Purpose |
|------|---------|
| `frontend/src/components/editor/NonDestructiveEditor.jsx` | Main editor: regions, cues, loops, envelope editing orchestration |
| `frontend/src/components/editor/TimelineCanvas.jsx` | Canvas renderer: regions, beat grid, markers, playhead (uses `requestAnimationFrame`) |
| `frontend/src/components/editor/RegionBlock.jsx` | Individual region UI: drag/resize/edit handles |
| `frontend/src/components/editor/EnvelopeOverlay.jsx` | Volume envelope editor overlay: draw/edit fade curves |
| `frontend/src/components/editor/EditorBrowser.jsx` | File browser sidebar for loading audio sources |
| `frontend/src/components/editor/Palette.jsx` | Right-side palette: clip library and editing tools |
| `frontend/src/components/editor/index.js` | Editor module re-exports |

### Frontend Config

| File | Purpose |
|------|---------|
| `frontend/package.json` | Frontend deps: React 18, Vite 7.x, Tauri API v2, axios, WaveSurfer.js, Tailwind, Lucide icons |
| `frontend/vite.config.js` | Vite: React plugin, `/api` proxy → localhost:8000, Tauri integration |
| `frontend/tailwind.config.js` | Tailwind: glassmorphism design system, custom slate tones |
| `frontend/postcss.config.js` | PostCSS: Tailwind + Autoprefixer |

---

## src-tauri/ — Rust Desktop Wrapper

| File | Purpose |
|------|---------|
| `src-tauri/src/main.rs` | App init, splashscreen, Tauri commands: `close_splashscreen`, `login_to_soundcloud` (PKCE OAuth), `export_to_soundcloud`. Registers `AudioCommandState` |
| `src-tauri/src/soundcloud_client.rs` | SC OAuth 2.1 + PKCE: `get_auth_url()`, `wait_for_callback()` (one-shot HTTP server), `exchange_code_for_token()`. Also contains `Track` struct |
| `src-tauri/src/audio/mod.rs` | Audio module re-exports: engine, playback, analysis, commands, export, metadata |
| `src-tauri/src/audio/engine.rs` | `AudioEngine`/`AudioController` — Symphonia codec decoding, memory-mapped file loading (memmap2, zero-copy), decoder abstraction for MP3/FLAC/WAV/ALAC/ISOMP4 |
| `src-tauri/src/audio/playback.rs` | `PlaybackEngine` — CPAL device-agnostic audio output, ringbuf lock-free sample queue, stream init + error recovery |
| `src-tauri/src/audio/analysis.rs` | `compute_waveform` (RustFFT), `estimate_bpm`, `detect_key` (chromatic) — 3-band freq split: low 20–300Hz, mid 300Hz–4kHz, high 4kHz–20kHz |
| `src-tauri/src/audio/commands.rs` | Tauri IPC handlers: `load_audio`, `get_3band_waveform`, `start_project_export`, `list_audio_devices` (CPAL output device enumeration) — all return `Result<T, String>`. `AudioCommandState` shared state |
| `src-tauri/src/audio/export.rs` | `render_project` — offline audio synthesis. Structs: `AudioRegion`, `ProjectState`, `Fade` |
| `src-tauri/src/audio/metadata.rs` | Tag read/write via lofty: ID3 (MP3), FLAC tags, ALAC metadata |
| `src-tauri/build.rs` | Tauri build script (required, do not modify) |
| `src-tauri/Cargo.toml` | Rust deps: tauri 2.2, cpal, symphonia, rustfft, rubato, ringbuf, memmap2, hound, lofty, sha2, reqwest, tokio, serde |
| `src-tauri/tauri.conf.json` | Tauri config: window title, size, splashscreen, bundle identifier |
| `src-tauri/capabilities/main.json` | Minimal permissions: `core:default`, `shell:allow-open` (for OAuth browser) |

---

## scripts/

| File | Purpose |
|------|---------|
| `scripts/screenshot.py` | Playwright screenshot utility for UI at localhost:5173 |
| `scripts/test_xml_sync.py` | Validates Rekordbox XML generation with mock track data |

---

## docs/

| File | Purpose |
|------|---------|
| `docs/PROJECT_OVERVIEW.md` | High-level project overview |
| `docs/DOWNLOAD_EVALUATION.md` | SoundCloud track download evaluation notes |

---

## .claude/

| File | Purpose |
|------|---------|
| `docs/FILE_MAP.md` | **This file** — master project navigation map |
| `docs/architecture.md` | System architecture, data flows, security model, performance characteristics |
| `docs/frontend-index.md` | React component index: props, key functions, Tauri IPC calls |
| `docs/backend-index.md` | FastAPI routes, Python class/method index, response envelopes |
| `docs/rust-index.md` | Tauri commands, Rust module index, event system, crate list |
| `.claude/agents/director.md` | Orchestrator agent — routes tasks to specialist agents |
| `.claude/agents/frontend-agent.md` | React/TS specialist |
| `.claude/agents/backend-agent.md` | Python/FastAPI specialist |
| `.claude/agents/rust-agent.md` | Rust/Tauri specialist |
| `.claude/agents/qa-agent.md` | QA/defensive programming reviewer |

---

## Key Entry Points by Task Type

| Task | Start here |
|------|-----------|
| Add/modify API route | `app/main.py` |
| Change business logic | `app/services.py` |
| Modify Rekordbox DB queries | `app/database.py` (XML mode) or `app/live_database.py` (live) |
| Change audio analysis | `app/analysis_engine.py` |
| Add React view/component | `frontend/src/components/` |
| Change DAW editor | `frontend/src/components/daw/DjEditDaw.jsx` → relevant child |
| Modify DAW state | `frontend/src/audio/DawState.js` |
| Change API client | `frontend/src/api/api.js` |
| Add Tauri command | `src-tauri/src/audio/commands.rs` (audio) or `src-tauri/src/main.rs` (other) |
| Modify audio engine | `src-tauri/src/audio/engine.rs` + `playback.rs` |
| Modify waveform analysis | `src-tauri/src/audio/analysis.rs` |
| Change USB sync | `app/usb_manager.py` |
| Change SoundCloud integration | `app/soundcloud_api.py` (matching) or `app/soundcloud_downloader.py` (download) or `src-tauri/src/soundcloud_client.rs` (OAuth) |
| Change backup system | `app/backup_engine.py` |
| Change toast/notifications | `frontend/src/components/ToastContext.jsx` |
| Change app settings | `app/config.py` (paths) or `app/services.py:SettingsManager` |
