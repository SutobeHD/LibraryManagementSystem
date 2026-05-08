# FILE_MAP.md — LibraryManagementSystem

> **Read this first.** One-line-per-file map of the entire codebase. Use this to find the right file for any task without searching blindly.
> Last updated: 2026-05-05

---

## Root

| File | Purpose |
|------|---------|
| `CLAUDE.md` | AI agent coding rules, principles, mandatory post-edit workflow |
| `package.json` | Root npm scripts: `dev:full` (starts all), `tauri dev`, `tauri build` |
| `requirements.txt` | Python deps: FastAPI, uvicorn, psutil, requests, sqlalchemy, librosa, scipy, numba, keyring, python-dotenv, soundfile, lameenc, numpy, rbox, madmom, essentia |
| `docker-compose.yml` | Docker: backend port 8000 + frontend port 5173 with volume mounts |
| `README.md` | Project overview, features, tech stack, setup instructions |
| `PROJECT_WIKI.md` | Extended feature documentation and architectural detail |

---

## app/ — Python FastAPI Backend

| File | Purpose |
|------|---------|
| `app/main.py` | **All 123 API routes** — see backend-index.md for full route list. Also contains `validate_audio_path()` (uses `Path.is_relative_to` against resolved roots — no startswith), request models, startup event, CORS config (explicit method whitelist), global error handlers, `_db_write_lock` (RLock serialising rbox writers), `SHUTDOWN_TOKEN` one-shot via `POST /api/system/init-token` (heartbeat no longer leaks token). New routes: `POST /api/system/init-token`, `GET/POST /api/usb/playcount/*`, `POST /api/phrase/generate`, `POST /api/phrase/commit`, `POST /api/duplicates/scan`, `GET /api/duplicates/results`, `POST /api/duplicates/merge` |
| `app/config.py` | Path constants: `REKORDBOX_ROOT`, `DB_FILENAME`, `FFMPEG_BIN`, `BACKUP_DIR`, `EXPORT_DIR`, `LOG_DIR`, `TEMP_DIR`, `MUSIC_DIR`, `DB_KEY` |
| `app/services.py` | 11 business logic classes: `XMLProcessor`, `SystemGuard`, `AudioEngine` (FFmpeg), `FileManager`, `LibraryTools`, `SettingsManager`, `MetadataManager`, `SystemCleaner`, `BeatAnalyzer`, `ImportManager` (reads native tags via `audio_tags.read_tags` then falls back to `Artist - Title` filename split — no longer hardcodes "New Import"/"Imported"), `ProjectManager` |
| `app/audio_tags.py` | Read/write native audio tags via mutagen. `write_tags(path, updates, artwork)` mirrors metadata edits to ID3/FLAC/MP4/Vorbis/AIFF/WAV. `read_tags(path)` returns a dict (title/artist/album/genre/year/comment/bpm/key/isrc) — probes format-specific keys, then falls back to `"Artist - Title"` filename parsing |
| `app/database.py` | `RekordboxXMLDB` — parses Rekordbox XML into in-memory cache; `RekordboxDB` — live SQLite access via rbox. Methods: `load_xml`, `get_tracks`, `get_playlists`, `get_track_details`, `save_xml`, `add_track`, `delete_track`, `save_track_cues`, `save_track_beatgrid` |
| `app/live_database.py` | `LiveRekordboxDB` — thread-safe direct access to Rekordbox `master.db` via rbox library with automatic backup management. Added: `get_analysis_writer()`, `get_unanalyzed_track_ids()`. `_load_beatgrids_from_anlz()` is dispatched to a daemon thread by `_start_beatgrid_background_load()` after `loaded=True`, batches via `SafeAnlzParser.load_all_beatgrids` (subprocess-isolated, bisecting) so rbox panics on bad rows cannot crash or block the backend |
| `app/anlz_safe.py` | `SafeAnlzParser` — process-isolated wrapper around `rbox.MasterDb` + `rbox.Anlz`. Defenses: (1) `_validate_anlz_header()` rejects files without `PMAI` magic / size ≥ 28B, (2) `ProcessPoolExecutor(max_workers=1)` quarantines all rbox calls — including `get_content_anlz_paths` — so Rust panics only kill the worker, (3) `load_all_beatgrids()` chunks tracks (500/chunk) and bisects on panic to identify and blacklist the offending track id (~log₂N restarts), (4) `_bad_ids` cache + 60s chunk timeout + `MAX_PANICS_PER_RUN=32` budget. Defends against known rbox 0.1.5 `unwrap()` panic in `masterdb/database.rs:1162` that aborts the Python process on malformed rows (Windows exit 0xC0000409) |
| `app/analysis_engine.py` | `AnalysisEngine` (class methods: `submit`, `get_status`, `analyze_sync`) + free `run_full_analysis(path)` — production DSP: madmom RNN beat tracking, essentia key detection, full ANLZ waveform generation (PWAV/PWV2/PWV3/PWV4/PWV5/PWV6/PWV7). ProcessPoolExecutor-based async pipeline |
| `app/analysis_db_writer.py` | `AnalysisDBWriter` — orchestrates: analyze track → write ANLZ files → update master.db. Methods: `analyze_and_save(track_id, force?)`, `analyze_batch(track_ids)` (progress generator), `get_unanalyzed_tracks()` |
| `app/anlz_writer.py` | Binary ANLZ file writer producing Rekordbox-compatible `.DAT`, `.EXT`, `.2EX` files. Public API: `build_dat()`, `build_ext()`, `build_2ex()`, `write_anlz_files(anlz_dir, track_path, analysis_result)`. All tags rbox-validated |
| `app/audio_analyzer.py` | Background analysis worker pool; wraps `AnalysisEngine` for HTTP task tracking with `task_id` polling |
| `app/soundcloud_api.py` | `SoundCloudPlaylistAPI` — SC unofficial v2 API with dynamic client_id scraping, exponential backoff, pagination. Added: `resolve_track_from_url()`, `download_url` in normalized track. `SoundCloudSyncEngine` — fuzzy title/artist matching. `AuthExpiredError`, `RateLimitError` |
| `app/soundcloud_downloader.py` | SC downloader with two-stage acquisition: (1) official `/tracks/{id}/download` when `downloadable=true`, (2) fallback to v2 `media.transcodings[]` (progressive MP3 or HLS→ffmpeg copy-mux) — same signed streams the web player plays. Legal gates: skip snipped previews, honor 401/403, never probe paid quality. Dedup-aware (registry + SHA-256). Auto-organizes files. Post-download pipeline: optional AIFF conversion via ffmpeg (`pcm_s16le`, controlled by `sc_download_format` setting), then `_apply_sc_metadata` writes title/artist/album/genre/year/comment + cover art via `audio_tags.write_tags`, then SHA-256 hash + registry + analysis + auto-playlist sort. Helpers: `_fetch_sc_metadata`, `_fetch_artwork_bytes` (resizes -large→-t500x500), `_apply_sc_metadata`, `_convert_to_aiff`, `_aiff_requested`. |
| `app/download_registry.py` | SQLite download registry: dedup by sc_track_id (O(1)) + SHA-256 content hash. Analysis history log. Multi-device via device_id UUID. `init_registry()`, `is_already_downloaded()`, `find_by_hash()`, `register_download()`, `update_analysis()`, `get_history()`, `get_stats()` |
| `app/usb_manager.py` | `UsbDetector` (scan, initialize_usb), `UsbProfileManager` (CRUD for sync profiles), `UsbSyncEngine` (sync_collection, sync_playlists default `["library_one", "library_legacy"]`, sync_metadata — lock-file concurrency, XML export w/ control-char sanitization `_xml_safe()`, drive-letter path normalization). `_sync_library_one` passes `_get_safe_dest_path` as `dest_resolver` to OneLibraryUsbWriter so both writers share the same audio destination tree. `_clean_filename` strips trailing dots/spaces + reserved names (Windows silently drops them). Copy error handler: only real disconnects (drive root missing) abort batch; ENOENT on a single bad filename skips that track and continues. |
| `app/usb_one_library.py` | `OneLibraryUsbWriter` — writes `PIONEER/rekordbox/exportLibrary.db` so Rekordbox 6/7 auto-detects the stick. **Template-based approach** (rbox 0.1.7 workaround): copies bundled `app/templates/exportLibrary_template.db` onto the USB, then mutates its placeholder content rows via `update_content` to populate user data. rbox's `create_content` is fundamentally broken (raises "Unexpected null for non-null column" on every call, and no Python-level NewContent constructor exists) — the template approach bypasses it. Other `create_*` calls (image/artist/album/genre/key/label/playlist) work normally. Hard cap = template's slot count (16 from F: drive baseline); overflow tracks fall through to legacy XML. Optional `dest_resolver` reuses legacy `<USB>/PIONEER/Contents/<Artist>/<Album>/file` tree. |
| `app/templates/build_template.py` | CLI tool: `python -m app.templates.build_template <path_to_rekordbox_stick>` — derives a clean+anonymised exportLibrary template from any Rekordbox-exported USB stick. Strips playlist tree + my_tags + name fields on artists/albums/labels/keys/genres/images, but keeps the content-row count as our placeholder slot count. |
| `app/templates/exportLibrary_template.db` | Anonymised OneLibrary template (16 placeholder content rows). Used by `OneLibraryUsbWriter.sync` as the writeable base — bypasses rbox 0.1.7's broken `OneLibrary.create()`. Rebuild from a Rekordbox-exported stick with more tracks for higher track caps. |
| `app/usb_mysettings.py` | CDJ + DJM hardware-settings writer for `<USB>/PIONEER/MYSETTING.DAT`, `MYSETTING2.DAT`, `DJMMYSETTING.DAT`. 42 editable fields total (22 player + 7 player-extended + 13 mixer). Uses `pyrekordbox.MySettingFile`/`MySetting2File`/`DjmMySettingFile`. Public API: `get_schema()` (JSON for frontend dropdowns), `read_settings(usb_root)`, `write_settings(usb_root, values)`, `write_defaults(usb_root)`. Auto-seeded on every sync via `UsbSyncEngine._ensure_usb_structure`. API routes: `GET /api/usb/mysettings/schema`, `GET /api/usb/mysettings/{device_id}`, `POST /api/usb/mysettings`. |
| `app/usb_artwork.py` | Cover-art extraction + bucketed write. `get_artwork_bytes(audio_path)` reads embedded ID3 APIC / FLAC Picture / MP4 covr atom, falls back to `cover.jpg` sidecar. `write_artwork_pair(audio_path, image_id, pioneer_dir)` resizes via Pillow to small (~80×80) + medium (~500×500) JPEGs and drops them at `PIONEER/Artwork/<bucket>/a<id>.jpg` + `_m.jpg`. Bucket = `image_id // 1000` zero-padded. `usb_relative_path(image_id)` returns the `/PIONEER/Artwork/...` URL stored in OneLibrary's `image.path` field. |
| `app/usb_pdb.py` | Full `export.pdb` + `exportExt.pdb` writer (legacy CDJ DeviceLibrary). Implements the Crate Digger spec from scratch: file header, 20-table directory, 4 KiB pages with bit-packed row count + reverse-order row index footer, DeviceSQL string encoder (short ASCII / long UTF-16-LE). Row encoders for tracks (djmdContent 0x00, 0x88-byte fixed header + 21 string offsets), genres (0x01), artists (0x02 far-name 0x0064), albums (0x03 far-name 0x0084), labels (0x04), keys (0x05), colors (0x06 — 8 default Pioneer colours pre-populated), playlist tree (0x07), playlist entries (0x08). exportExt.pdb has its own 5-table directory: tags (0x03 subtype 0x0684 far-name with category folder support), tag_tracks (0x04 16-byte association rows). Public API: `write_export_pdb(usb_root, contents, artists, albums, keys, genres, labels, playlists, playlist_entries)`, `write_export_ext_pdb(usb_root, tags, tag_categories, tag_track_links)`. Index pages NOT implemented — works for libraries ≤ ~500 tracks via linear scan. **Anti-corruption fixes (vs. F: drive byte-diff)**: (1) Table descriptor `empty_candidate` set to `last_page` (never 0 — page 0 is the file header so 0 fails Rekordbox validation and triggers "Device library is corrupted" dialog). (2) Data-page flag `0x34` (not `0x24`) — bit 4 (0x10) is set on every data page real Rekordbox writes. |
| `app/backup_engine.py` | Git-like incremental backup: compressed JSON changesets, HEAD tracking, commit timeline, restore |
| `app/rekordbox_export.py` | Converts `AnalysisEngine` results → Rekordbox XML `TRACK` elements with `TEMPO` nodes and `POSITION_MARK` cues |
| `app/rekordbox_bridge.py` | High-level: export selected tracks → Rekordbox XML; import from XML exports |
| `app/rbep_parser.py` | Parses `.rbep` (Rekordbox Editor Project) XML. Real-format aware: `<filepath>` directly under `<song>`, `<edit>` directly under `<track>`, `<position>/<data>/<section>` collected as a list (not a single object). Exposes `positions[]` and `editEndBeats` for timeline duration. Volume envelopes, BPM maps, hot cues, memory cues, beat grids |
| `app/xml_generator.py` | `RekordboxXML` — generates valid `DJ_PLAYLISTS` XML from Python track data with dynamic/static beatgrids and cue points |
| `app/sidecar.py` | `SidecarStorage` — persists artist metadata (SoundCloud links, custom fields) in `app_data.json` sidecar file |
| `app/batch_worker.py` | CLI tool for batch track metadata updates (comments/tags) using rbox `MasterDb` — find/replace/append/set operations |
| `app/playcount_sync.py` | **NEW** USB Play-Count Sync engine: `load_usb_sync_meta`, `save_usb_sync_meta`, `diff_playcounts` (three-way diff), `resolve_playcounts` (commits to PC DB + USB XML), `read_usb_xml_playcounts`. API: `GET /api/usb/playcount/diff`, `POST /api/usb/playcount/resolve` |
| `app/phrase_generator.py` | **NEW** Phrase & Auto-Cue Generator: `extract_beats_from_db`, `detect_first_downbeat` (librosa energy), `generate_phrase_cues` (phrase/bar markers), `commit_cues_to_db` (hot cues A–H via rbox). API: `POST /api/phrase/generate`, `POST /api/phrase/commit` |
| `app/__init__.py` | Package init (empty) |

---

## frontend/src/ — React Frontend

### Core

| File | Purpose |
|------|---------|
| `frontend/src/main.jsx` | App root: lazy-loaded tab views, session token init, global error boundary, tab router. **Sidebar** — 220px, groups: Library / Editor / Sync / Utilities / Lab. Footer: Backups + Settings + Exit. DotGridBackdrop component for selection/loading screens (24px radial dots, amber2, no gradient blur). Lazy imports for UtilitiesView |
| `frontend/src/api/api.js` | **Central Axios instance** — always use this. Handles session tokens, 401 refresh queue, 429 exponential backoff, HttpOnly cookie support, 10s default timeout (disabled for long-running calls like `/api/usb/sync` via `{ timeout: 0 }`), Tauri context detection |
| `frontend/src/index.css` | Global styles — Melodex CSS vars (`--mx-*`, `--ink-*`, `--amber*`), DM Sans + JetBrains Mono via Google Fonts, primitives (`.nav-item`, `.btn-primary`, `.btn-ghost`, `.btn-secondary`, `.input-glass`, `.glass-panel`, `.mx-card`, `.mx-panel`, `.mx-caption`, `.mx-mono`, `.mx-chip`), DAW/region/playhead styles recolored to amber, monochrome scrollbars |

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
| `frontend/src/components/UsbView.jsx` | USB device manager — filters USB sticks only (no system/fixed drives). Main Sync Source toggle (PC/USB), Target Ecosystem card, dynamic storage bar colors, Eject in header, Playlists above Contents. Compat matrix: orange AlertTriangle for wrong-format, red X for incompat. ETA placeholder. Includes inline collapsible MetadataSyncPanel (smart/manual sync modes, category checkboxes). Sub-components: `Toggle`, `PillBtn`, `PillTab`, `Row`, `SpaceBar`, `PlaylistTreeNode`, `UsbLibraryTree`, `PlayCountSync`, `MetadataSyncPanel` |
| `frontend/src/components/UsbSettingsView.jsx` | CDJ + DJM hardware-settings editor (writes `PIONEER/MYSETTING.DAT`, `MYSETTING2.DAT`, `DJMMYSETTING.DAT`). Device picker → 3 file tabs (Player / Player Extended / Mixer) → groups → labelled dropdown per field. Fetches schema dynamically from `/api/usb/mysettings/schema` (no hardcoded enum tables — keeps frontend in lock-step with pyrekordbox). Reset-to-defaults + dirty-state guard on device switch. |
| `frontend/src/components/BackupManager.jsx` | Library backup/restore: timeline view, create snapshots, `POST /api/library/backup` |
| `frontend/src/components/XmlCleanView.jsx` | Rekordbox XML cleanup/validation tool, calls `POST /api/xml/clean` |
| `frontend/src/components/InsightsView.jsx` | Library analytics: low quality, no artwork, lost tracks, bitrate stats |
| `frontend/src/components/RankingView.jsx` | Track ranking/sorting by quality metrics |
| `frontend/src/components/ImportView.jsx` | Two-panel import: left drop zone + file list, right settings panel (Library Quality Analyzer, Format Conversion with all audio formats, Safe Deletion Protocol with backup toggle) |
| `frontend/src/components/SettingsView.jsx` | **Tabbed** preferences panel (8 tabs): Library, Backup, Export, Audio (CPAL device), Analysis quality, Appearance (band colors + locale), Shortcuts (key capture), Network (proxy). Calls `GET/POST /api/settings`. |
| `frontend/src/components/ToolsView.jsx` | Batch operations: rename, clean titles, find duplicates, batch comments |
| `frontend/src/components/DesignView.jsx` | Design Lab: 10 feature mockup pages (Stems, Smart Playlist, Batch Tag, Set Planner, Streaming Hub, DVS, Collab, Harmonic Mixing, Routing Matrix, Macros) + 20 selectable tileable line-pattern background themes (Beat Grid/Wave Lines/Cue Markers/Spectrum/Crosshatch/Circuit/Constellations/Sunburst/Tribal/Notes/Bold Stripes/Thick Diagonals/Arcs/Chevron/Heavy Grid/Wave+Cues/Pulse+Cues/Segmented Wave/Dual Wave/Stepped Wave) stored in localStorage |
| `frontend/src/components/UtilitiesView.jsx` | Utilities hub grid dashboard: Phrase Cues, Duplicate Finder, XML Cleaner, Mass Format Converter (placeholder). Sub-views open inline with back button |
| `frontend/src/components/WaveformEditor.jsx` | Legacy waveform editor (superseded by `DjEditDaw`) |
| `frontend/src/components/PhraseGeneratorView.jsx` | **NEW** Phrase & Auto-Cue Generator: track selector, phrase length picker (8/16/32), generate preview list (amber phrase / grey bar markers), two-step Generate → Commit flow |
| `frontend/src/components/DuplicateView.jsx` | **NEW** Acoustic Duplicate Finder: scan library, group by fingerprint similarity, left group list + right card detail panel, master selection, merge play counts, POST /api/duplicates/merge |

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
| `frontend/src/components/daw/ExportModal.jsx` | **Export dialog** with folder picker, format options (WAV/MP3/FLAC), normalization. Helpers: `pickDirectory()` (tauri-plugin-dialog), `createFolderIfNotExists()` (tauri-plugin-fs mkdir), `writeBinaryFile()` (tauri-plugin-fs writeFile with error propagation). WAV: DawEngine.renderTimeline → audioBufferToWav → fs write. MP3/FLAC: POST /api/audio/render → download → fs write. Browser fallback: download via blob. Reads default_export_dir from /api/settings |

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
| `frontend/tailwind.config.js` | Tailwind: **Melodex design system** — amber #E8A42A accent, DM Sans + JetBrains Mono, `mx-*` (surfaces), `ink-*` (text), `line-*` (borders), `amber2.*` palette. Legacy `djdark`/`neon.*` aliases preserved |
| `frontend/postcss.config.js` | PostCSS: Tailwind + Autoprefixer |

---

## src-tauri/ — Rust Desktop Wrapper

| File | Purpose |
|------|---------|
| `src-tauri/src/main.rs` | App init, splashscreen, Tauri commands: `close_splashscreen`, `login_to_soundcloud` (PKCE OAuth), `export_to_soundcloud`. Registers `AudioCommandState` |
| `src-tauri/src/soundcloud_client.rs` | SC OAuth 2.1 + PKCE: `get_auth_url()`, `wait_for_callback()` (one-shot HTTP server), `exchange_code_for_token()`. Also contains `Track` struct |
| `src-tauri/src/audio/mod.rs` | Audio module re-exports: engine, playback, analysis, commands, export, metadata, fingerprint |
| `src-tauri/src/audio/engine.rs` | `AudioEngine`/`AudioController` — Symphonia codec decoding, memory-mapped file loading (memmap2, zero-copy), decoder abstraction for MP3/FLAC/WAV/ALAC/ISOMP4 |
| `src-tauri/src/audio/playback.rs` | `PlaybackEngine` — CPAL device-agnostic audio output, ringbuf lock-free sample queue, stream init + error recovery |
| `src-tauri/src/audio/analysis.rs` | `compute_waveform` (RustFFT), `estimate_bpm`, `detect_key` (chromatic) — 3-band freq split: low 20–300Hz, mid 300Hz–4kHz, high 4kHz–20kHz |
| `src-tauri/src/audio/commands.rs` | Tauri IPC handlers: `load_audio`, `get_3band_waveform`, `start_project_export`, `list_audio_devices` (CPAL output device enumeration) — all return `Result<T, String>`. `AudioCommandState` shared state |
| `src-tauri/src/audio/export.rs` | `render_project` — offline audio synthesis. Structs: `AudioRegion`, `ProjectState`, `Fade` |
| `src-tauri/src/audio/metadata.rs` | Tag read/write via lofty: ID3 (MP3), FLAC tags, ALAC metadata |
| `src-tauri/src/audio/fingerprint.rs` | **NEW** Acoustic fingerprinting: decode via Symphonia → 11025 Hz mono → 32-band Mel spectrogram → Chromaprint-style u32 hash words. `hamming_similarity()`. Tauri commands: `fingerprint_track(path)`, `fingerprint_batch(paths, window)` (emits `fingerprint_progress` events) |
| `src-tauri/build.rs` | Tauri build script (required, do not modify) |
| `src-tauri/Cargo.toml` | Rust deps: tauri =2.10.2 (pinned), reqwest =0.12.28 (pinned), tauri-plugin-shell, tauri-plugin-dialog (folder picker via `open { directory: true }`), tauri-plugin-fs (binary writes via `writeFile` + folder creation via `mkdir`), cpal, symphonia, rustfft, rubato, ringbuf, memmap2, hound, lofty, sha2, tokio, serde |
| `src-tauri/tauri.conf.json` | Tauri config: window title, size, splashscreen, bundle identifier |
| `src-tauri/capabilities/main.json` | Permissions: `core:default`, `shell:allow-spawn` (sidecar `rb-backend` only — no `allow-execute` to prevent RCE), `dialog:default/allow-open/allow-save`, `fs:default/allow-write-file/allow-read-file/allow-mkdir` (binary writes + folder creation) |

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
