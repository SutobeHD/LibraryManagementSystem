# app/ INDEX — Python Backend

> Module and endpoint map for the FastAPI backend. Update when adding/removing endpoints or modules.
> Last updated: 2026-04-30

---

## Entry Point & Server Config (`app/main.py`)

FastAPI app (~1700 lines). Security: CORS locked to localhost, session token auth on system endpoints, `validate_audio_path()` enforces `ALLOWED_AUDIO_ROOTS` sandbox on all file I/O.

### Library Endpoints
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/library/tracks` | All tracks with full metadata (XML or live DB depending on mode) |
| GET | `/api/playlist/{pid}/tracks` | Tracks in a specific playlist |
| GET | `/api/track/{tid}` | Single track full detail |
| GET | `/api/track/{tid}/cues` | Hot cues + memory cues for a track |
| GET | `/api/track/{tid}/beatgrid` | Beatgrid data for a track |
| POST | `/api/track/{tid}` | Update track metadata fields |
| DELETE | `/api/track/{tid}` | Delete a track |
| POST | `/api/track/delete` | Delete track by body param |
| POST | `/api/track/cues/save` | Save cue points for a track |
| POST | `/api/track/grid/save` | Save beatgrid for a track |
| PATCH | `/api/tracks/batch` | Batch update metadata on multiple tracks |
| POST | `/api/tracks/move` | Move tracks between playlists |
| GET | `/api/artists` | All artists (normalized) |
| GET | `/api/artist/{aid}/tracks` | Tracks by artist |
| GET | `/api/genres` | All genres |
| GET | `/api/labels` | All labels |
| GET | `/api/albums` | All albums |
| GET | `/api/label/{aid}/tracks` | Tracks by label |
| GET | `/api/album/{aid}/tracks` | Tracks by album |
| GET | `/api/artwork` | Serve artwork image for a track (path param) |

### Playlist Endpoints
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/playlists/tree` | Full playlist tree (nested folders + playlists) |
| POST | `/api/playlists/create` | Create new playlist |
| POST | `/api/playlists/rename` | Rename playlist |
| POST | `/api/playlists/move` | Move playlist in tree |
| POST | `/api/playlists/delete` | Delete playlist |
| POST | `/api/playlists/add-track` | Add track to playlist |
| POST | `/api/playlists/remove-track` | Remove track from playlist |
| POST | `/api/playlists/reorder` | Reorder tracks within playlist |

### Audio Endpoints
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/stream` | Stream audio file (range-request, sandboxed, query param `path`) |
| GET | `/api/audio/stream` | Alias for stream endpoint |
| GET | `/api/audio/waveform` | Multiband waveform data (pps param controls points-per-second) |
| POST | `/api/audio/analyze` | Start async BPM/key analysis → returns `{ task_id }` |
| GET | `/api/audio/analyze/{task_id}` | Poll analysis result: `{ status, bpm, key, confidence }` |
| POST | `/api/audio/slice` | Slice audio file at beat positions |
| POST | `/api/audio/render` | Render audio with FFmpeg (format conversion, export) |
| POST | `/api/audio/import` | Import a local audio file into the library |
| POST | `/api/track/{tid}/analyze` | Full analysis pipeline on single track |
| POST | `/api/track/{tid}/analyze-full` | **[NEW]** Analyze + write ANLZ files + update master.db in one call. Body: `{ force: bool }`. Requires live DB mode, Rekordbox must be closed |
| POST | `/api/library/analyze-batch` | **[NEW]** Batch analyze multiple tracks; NDJSON streaming progress. Body: `{ track_ids: [int], force: bool }` |
| GET | `/api/library/analyze-status` | **[NEW]** Report analysis engine capabilities + count of unanalyzed tracks |

### Project (DAW / RBEP) Endpoints
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/projects` | List `.rbep` project files |
| POST | `/api/projects/save` | Save non-destructive edit project to `.rbep` |
| GET | `/api/projects/{name}` | Load and parse a specific `.rbep` project |
| GET | `/api/projects/rbep/list` | List available `.rbep` files |
| GET | `/api/projects/rbep/{name}` | Get parsed content of a `.rbep` project |

### Library Management Endpoints
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/library/status` | Library load state, mode (XML/live), path |
| POST | `/api/library/mode` | Switch between XML and live (SQLite) mode |
| POST | `/api/library/load` | Load a Rekordbox XML file into memory |
| POST | `/api/library/unload` | Unload current library |
| POST | `/api/library/new` | Create a new empty library |
| POST | `/api/library/backup` | Create an incremental backup snapshot |
| GET | `/api/library/backups` | List all backup commits with timestamps |
| GET | `/api/library/backup/{commit_hash}/diff` | Show diff for a specific backup commit |
| POST | `/api/library/restore` | Restore library to a specific backup commit |
| POST | `/api/library/sync` | Sync current XML with live DB state |
| POST | `/api/library/smart-playlists` | Generate smart playlists from rules |
| POST | `/api/library/scan-folder` | **[NEW]** Background scan of a directory; auto-imports audio files not yet in library. Body: `{ path: str }` |
| POST | `/api/library/clean-titles` | Clean track title strings (remove tags, fix encoding) |
| POST | `/api/debug/load_xml` | Debug endpoint: reload XML from disk |

### Rekordbox XML Endpoints
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/xml/clean` | Clean Rekordbox XML (strip tags, fix encoding, normalize) |
| POST | `/api/rekordbox/export` | Export selected tracks to Rekordbox-compatible XML |
| POST | `/api/rekordbox/import` | Import tracks from a Rekordbox XML export |
| POST | `/api/file/write` | Write raw XML content to a file (sandboxed) |

### Insights Endpoints
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/insights/low_quality` | Tracks below bitrate/quality threshold |
| GET | `/api/insights/no_artwork` | Tracks missing embedded artwork |
| GET | `/api/insights/lost` | Tracks whose file paths no longer exist on disk |

### Tools Endpoints
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/tools/duplicates` | Find duplicate tracks (title + artist matching) |
| POST | `/api/tools/duplicates/merge` | Merge a set of duplicate tracks |
| POST | `/api/tools/duplicates/merge-all` | Auto-merge all detected duplicates |
| POST | `/api/tools/rename` | Rename tracks (not supported in XML-only mode) |
| POST | `/api/tools/batch-comment` | Batch update comments on multiple tracks |
| POST | `/api/metadata/merge` | Merge metadata from one track into another |

### SoundCloud Endpoints
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/soundcloud/playlists` | Fetch SC playlists for authenticated user |
| GET | `/api/soundcloud/me` | Get authenticated SC user profile |
| POST | `/api/soundcloud/auth-token` | Store SC OAuth token (called after Tauri OAuth flow) |
| GET | `/api/soundcloud/settings` | Get SC-specific settings (target folder, etc.) |
| PUT | `/api/soundcloud/settings` | Update SC settings |
| POST | `/api/soundcloud/preview-matches` | Preview library matches for SC playlist tracks (dry run) |
| POST | `/api/soundcloud/sync` | Run SC playlist sync (match + mark) |
| POST | `/api/soundcloud/sync-all` | Sync all SC playlists at once |
| POST | `/api/soundcloud/merge` | Merge SC playlist into local playlist |
| POST | `/api/soundcloud/download` | **[UPDATED]** Start legal download: body `ScDownloadRequest`. Accepts URL or pre-resolved track data. Rejects if `downloadable=false`. Uses official SC API only. Returns `{task_id}`. |
| GET | `/api/soundcloud/tasks` | List all active download tasks |
| GET | `/api/soundcloud/task/{task_id}` | Poll status of a download task |
| GET | `/api/soundcloud/history` | **[NEW]** Paginated analysis history log. Params: `limit`, `offset`, `status`, `device_id`, `search`, `this_device_only` |
| GET | `/api/soundcloud/history/stats` | **[NEW]** Aggregate stats: total/analyzed/failed counts, device count, date range |
| GET | `/api/soundcloud/check/{sc_track_id}` | **[NEW]** O(1) dedup check — returns `{already_downloaded: bool}` |
| DELETE | `/api/soundcloud/history/{sc_track_id}` | **[NEW]** Remove registry entry (to allow re-download). Does NOT delete the file. |
| POST | `/api/artist/soundcloud` | Associate artist with SC profile |

### USB Sync Endpoints
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/usb/devices` | Scan drives for Rekordbox USB libraries |
| GET | `/api/usb/profiles` | List all sync profiles |
| POST | `/api/usb/profiles` | Save/update a sync profile |
| DELETE | `/api/usb/profiles/{device_id}` | Delete a sync profile |
| GET | `/api/usb/{device_id}/contents` | List tracks/playlists on USB device |
| GET | `/api/usb/diff/{device_id}` | Calculate diff: what would change in a sync |
| POST | `/api/usb/sync` | Run USB sync for specific playlists (long-running, no timeout — can take minutes for large libraries) |
| POST | `/api/usb/sync/all` | Sync entire local library to USB |
| POST | `/api/usb/eject` | Eject a USB device |
| POST | `/api/usb/reset` | Reset USB library to factory state |
| POST | `/api/usb/initialize` | Initialize a drive as a Rekordbox USB |
| POST | `/api/usb/rename` | Rename a USB device profile |
| GET | `/api/usb/settings` | Get USB sync global settings |
| POST | `/api/usb/settings` | Update USB sync global settings |

### System Endpoints
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/settings` | Load user settings (JSON) |
| POST | `/api/settings` | Save user settings |
| POST | `/api/system/heartbeat` | Keep-alive ping (called on startup) |
| POST | `/api/system/shutdown` | Graceful server shutdown |
| POST | `/api/system/restart` | Restart the backend process |
| POST | `/api/system/cleanup` | Clean temp files |
| POST | `/api/system/select_db` | Open file dialog to select Rekordbox DB |

---

## Core Config (`app/config.py`)

| Variable | Value | Description |
|----------|-------|-------------|
| `REKORDBOX_ROOT` | `%APPDATA%/Pioneer/rekordbox` | Pioneer Rekordbox database directory |
| `DB_FILENAME` | `master.db` | Rekordbox SQLite database filename |
| `FFMPEG_BIN` | `ffmpeg` | FFmpeg binary (must be in PATH) |
| `BACKUP_DIR` | `./backups` | Incremental backup storage |
| `EXPORT_DIR` | `./exports` | Audio export output |
| `LOG_DIR` | `./logs` | Application log files |
| `TEMP_DIR` | `./temp_uploads` | Temporary file processing |
| `MUSIC_DIR` | `./music` | Default music library root |
| `DB_KEY` | env: `REKORDBOX_DB_KEY` | Rekordbox SQLite encryption key |

`validate_audio_path(path_str)` in `main.py` — validates any file path against `ALLOWED_AUDIO_ROOTS` before I/O. Raises `ValueError` on sandbox violation.

---

## Business Logic Modules (`app/services.py`)

All classes are instantiated on import; most methods are instance methods unless noted.

| Class | Key Methods | Purpose |
|-------|------------|---------|
| `XMLProcessor` | `clean_xml(path)`, `create_artist_playlists()`, `create_label_playlists()` | Clean/transform Rekordbox XML (strip tags, normalize, create derived playlists) |
| `SystemGuard` | `is_rekordbox_running() → bool`, `create_backup()` | Check if Rekordbox process is running before writes; create pre-modification backups |
| `AudioEngine` | `convert(src, dst, format)`, `render(params)`, `slice(path, positions)` | FFmpeg wrapper — format conversion, render exports, slice at beat positions |
| `FileManager` | `copy(src, dst)`, `delete(path)`, `compress(path)` | File I/O operations (copy/delete/compress) |
| `LibraryTools` | `extract_metadata(path)`, `batch_update(ids, fields)` | Track metadata extraction, batch metadata operations |
| `SettingsManager` | `load() → dict`, `save(settings)` | User preferences persistence (JSON file) |
| `MetadataManager` | `read(path)`, `write(path, fields)` | Read/write embedded audio metadata tags |
| `SystemCleaner` | `clean_temp()`, `clean_expired_caches()` | Remove temp files and expired analysis caches |
| `BeatAnalyzer` | `analyze(path) → {bpm, key, confidence}` | BPM/key analysis wrapper (delegates to `AnalysisEngine`) |
| `ImportManager` | `import_file(path)`, `import_url(url)` | Import tracks from filesystem or URL into library |
| `ProjectManager` | `save(name, state)`, `load(name) → state`, `list() → [names]`, `delete(name)` | `.rbep` non-destructive edit project CRUD |

---

## Database Modules

### `app/database.py` — `RekordboxXMLDB`
XML-based library (default mode). In-memory dict cache for fast lookups. Also contains `RekordboxDB` for direct SQLite via rbox.

| Method | Returns | Description |
|--------|---------|-------------|
| `load_xml(path)` | None | Parse XML into memory cache |
| `get_tracks(filters?)` | `[Track]` | All tracks, optionally filtered |
| `get_playlists()` | `[Playlist]` | All playlists with track ID lists |
| `get_playlist_tracks(pid)` | `[Track]` | Tracks in a specific playlist |
| `get_track_details(tid)` | `Track` | Single track by ID |
| `get_all_labels()` / `get_all_albums()` | `[str]` | Label/album lists for filtering |
| `get_tracks_by_artist/label/album(id)` | `[Track]` | Filter tracks by grouping |
| `add_track(track_data)` | `str` (new ID) | Add track to XML library |
| `delete_track(tid)` | `bool` | Remove track from XML |
| `save_xml()` | None | Write current state back to XML file |
| `save_track_cues(tid, cues)` | `bool` | Persist cue points |
| `save_track_beatgrid(tid, grid)` | `bool` | Persist beatgrid |
| `get_track_cues(tid)` | `[Cue]` | Read stored cues |
| `get_track_beatgrid(tid)` | `[Beat]` | Read stored beatgrid |
| `update_tracks_metadata(ids, fields)` | `bool` | Batch metadata update |

### `app/live_database.py` — `LiveRekordboxDB`
Direct SQLite access (live mode). Thread-safe via locks. Auto-backup on write.

| Method | Description |
|--------|-------------|
| `get_tracks()` | Query `master.db` directly |
| `update_track(id, fields)` | Write to SQLite (**requires Rekordbox to be closed**) |
| `get_analysis_writer()` | Lazy-create and return `AnalysisDBWriter` instance bound to this DB |
| `get_unanalyzed_track_ids()` | Return list of track IDs with BPM=0 (not yet analyzed) |
| `_load_beatgrids_from_anlz()` | Batch-loads PQTZ beatgrids via `SafeAnlzParser.load_all_beatgrids` (subprocess-isolated, bisecting). Runs on a daemon thread spawned by `_start_beatgrid_background_load` after `loaded=True` so a slow / panicking rbox call cannot block library init |
| `_start_beatgrid_background_load()` | Spawns the `anlz-beatgrid-loader` daemon thread that runs `_load_beatgrids_from_anlz` out of band |

### `app/anlz_safe.py` — `SafeAnlzParser`
Process-isolated wrapper around `rbox.MasterDb` + `rbox.Anlz`. Defends
against known panics in `rbox` 0.1.5 (`masterdb/database.rs:1162`
`unwrap()` on `None`) that abort the whole Python process on malformed
ANLZ rows. The panic site is in `MasterDb` itself, so even a plain
`get_content_anlz_paths(tid)` call can crash the backend — the
subprocess therefore handles **the entire iteration**, not just
`rbox.Anlz()`.

| Layer | Purpose |
|-------|---------|
| `_validate_anlz_header(path)` | Fast pre-check: file size ≥ 28 bytes + `PMAI` magic. Rejects truncated / non-ANLZ files before rbox sees them. |
| `ProcessPoolExecutor(max_workers=1)` | All rbox calls run in a subprocess. A panic kills only the worker; parent respawns it (`BrokenExecutor` handler). |
| Batch + bisect | `load_all_beatgrids` chunks tracks (default 500/chunk). On worker crash the chunk is bisected to identify and blacklist the offending track id (~log₂N restarts). |
| `_bad_ids` cache | Track ids that panic / time out / fail header check are skipped for the rest of the session. |
| `PER_CHUNK_TIMEOUT_S = 60.0` | Hung worker is killed and respawned; that chunk is dropped (no bisect — bisecting a hang would just hang again). |
| `MAX_PANICS_PER_RUN = 32` | Hard ceiling on subprocess restarts to protect against pathological DBs where every other row panics. |

| Method | Returns | Description |
|--------|---------|-------------|
| `load_all_beatgrids(db_path, track_ids, chunk_size=500)` | `dict[str, list[dict]]` | Batch-load PQTZ for every requested track id. Worker opens its own MasterDb. Used by `LiveRekordboxDB._load_beatgrids_from_anlz`. |
| `parse_pqtz(track_id, dat_path)` | `list[dict] \| None` | Single-file PQTZ extract for ad-hoc lookups; `None` on any failure. |
| `stats` | `dict` | `{bad_ids, panics, worker_alive}` for diagnostics. |
| `shutdown()` | None | Tear down the worker (idempotent). |

**Load flow**: `LiveRekordboxDB.load()` finishes synchronous init
(metadata, tracks, playlists, cues), marks `loaded=True`, and **then**
spawns a daemon thread (`_start_beatgrid_background_load`) that calls
`_load_beatgrids_from_anlz` → `SafeAnlzParser.load_all_beatgrids`. The
UI sees tracks immediately; beatgrids fill in within seconds without
ever blocking the load path.

---

## Analysis Engine (`app/analysis_engine.py`) — `AnalysisEngine`

Async DSP pipeline using `ProcessPoolExecutor`. All class methods (no instance needed).

| Method | Returns | Description |
|--------|---------|-------------|
| `AnalysisEngine.submit(task_id, file_path)` | `{ task_id, status: "pending" }` | Queue a track for analysis in background pool |
| `AnalysisEngine.get_status(task_id)` | `{ status, bpm, key, confidence, beatgrid }` | Poll task result. status: `pending|done|error` |
| `AnalysisEngine.analyze_sync(file_path)` | `{ bpm, key, confidence, beatgrid, anlz }` | Synchronous analysis (blocks; use for scripting only) |
| `run_full_analysis(file_path)` | full result dict | Top-level free function — single call returns everything needed for ANLZ writing |

Algorithms: madmom RNN beat tracking (librosa fallback), essentia KeyExtractor (K-S/Temperley ensemble fallback), 3-band Butterworth crossover (200Hz/2500Hz) for waveform generation.

Waveform outputs: PWAV (400 mono preview), PWV2 (100 tiny), PWV3 (detail@150fps), PWV4 (1200×6 color preview), PWV5 (color detail u16), PWV6 (1200×[lo,mi,hi] 3-band preview), PWV7 (N×[lo,mi,hi] 3-band detail@150fps).

---

## ANLZ Writer (`app/anlz_writer.py`)

Writes Rekordbox-compatible binary ANLZ files (.DAT, .EXT, .2EX). All output is validated by rbox.

| Function | Description |
|----------|-------------|
| `write_anlz_files(anlz_dir, track_path, analysis_result)` | Main entry point — writes all 3 files from `run_full_analysis()` output. Returns `{"dat": path, "ext": path, "2ex": path}` |
| `build_dat(track_path, beats, pvbr, pwav, pwv2)` | Build .DAT bytes: PPTH + PVBR + PQTZ + PWAV + PWV2 + PCOB×2 |
| `build_ext(track_path, beats, pwv3, pwv5, pwv4)` | Build .EXT bytes: PPTH + PWV3 + PCOB×2 + PCO2×2 + PWV5 + PWV4 |
| `build_2ex(track_path, pwv7, pwv6)` | Build .2EX bytes: PPTH + PWV7 + PWV6 + PWVC |

**Tag formats** (all big-endian, rbox-validated):
- PQTZ entries: `[beat_number(u16), tempo×100(u16), time_ms(u32)]`
- PCOB: 24-byte header with `0xFFFFFFFF` sentinel
- PCO2: `list_type` is u32 (not u16)
- PWV5: header field +20 must be `0x00960305`
- PWV6: hdr_len=20, `entry_size(u32)=3` before `entry_count`
- PWV7: hdr_len=24, `entry_size(u32)=3`, data is `[lo, mid, hi]` per entry

---

## Analysis-to-DB Orchestrator (`app/analysis_db_writer.py`) — `AnalysisDBWriter`

Ties analysis → ANLZ files → master.db in a single pipeline. **Requires live DB mode and Rekordbox closed.**

| Method | Description |
|--------|-------------|
| `analyze_and_save(track_id, force=False)` | Full pipeline for single track: analyze → write ANLZ → update BPM/key/analysed in master.db |
| `analyze_batch(track_ids, force=False)` | Generator — yields `{track_id, status, progress, bpm, key, error}` dicts as each track completes |
| `get_unanalyzed_tracks()` | Returns list of track dicts with `bpm=0` or missing ANLZ files |

---

## SoundCloud (`app/soundcloud_api.py`)

| Class / Exception | Purpose |
|------------------|---------|
| `SoundCloudPlaylistAPI` | SC unofficial v2 API client: `fetch_playlists(token)`, `fetch_likes(token)`, `get_me(token)`. Handles dynamic `client_id` scraping, Cloudflare fallback, exponential backoff on 429, full pagination |
| `SoundCloudSyncEngine` | `match_to_library(sc_tracks, local_tracks) → [MatchResult]` — fuzzy title/artist matching (jaro-winkler), duration tiebreaker, confidence scoring |
| `AuthExpiredError` | Raised when SC token is expired → frontend should trigger re-auth via `login_to_soundcloud` Tauri command |
| `RateLimitError` | Raised on 429 → includes `retry_after` seconds |

---

## Download Registry (`app/download_registry.py`)

SQLite-based deduplication + analysis history log. DB at `{MUSIC_DIR}/download_registry.db`.

| Function | Returns | Description |
|----------|---------|-------------|
| `init_registry()` | None | Create schema (call once on startup) |
| `is_already_downloaded(sc_track_id)` | bool | O(1) dedup check by SC track ID |
| `find_by_hash(sha256)` | `dict \| None` | Content-based dedup by SHA-256 |
| `register_download(**kwargs)` | bool | UPSERT download record (idempotent) |
| `update_analysis(**kwargs)` | bool | Store BPM/key results, mark 'analyzed' |
| `mark_failed(sc_track_id, error)` | None | Mark as permanently failed |
| `delete_entry(sc_track_id)` | bool | Remove entry (allows re-download) |
| `get_history(**filters)` | `[dict]` | Paginated history, newest-first |
| `get_stats()` | dict | Aggregate counts + date range |
| `get_current_device_id()` | str | Stable UUID for this machine |
| `compute_sha256(path)` | `str \| None` | Stream-hash a file for content dedup |

Device ID: stored as `{MUSIC_DIR}/.rb_device_id`. Not hardware-tied.

---

## SoundCloud Downloader (`app/soundcloud_downloader.py`)

Dedup-aware downloader with two-stage acquisition — same legal surface as the
SC web player itself.

**Acquisition order:**
1. **Official `/tracks/{id}/download`** (preferred) — used when `downloadable=True`,
   returns the creator's original upload.
2. **Fallback: v2 `media.transcodings[]`** — signed CDN stream same as web-player:
   - `progressive` → direct HTTP stream (MP3)
   - `hls` → ffmpeg `-c copy` mux to `.m4a` (no re-encode)

**Legal boundaries** (enforced in `_resolve_stream_via_transcodings`):
- Skip `snipped: true` transcodings (= 30s paywall previews)
- Skip on 401/403 from transcoding-signing (no access)
- Skip when `transcodings[]` empty (private/removed)
- Only use `hq` (Go+) when SC itself returns it — never probe for paid quality
- HLS mux uses `-c copy` (repack only, no re-encode, no DRM touched)

**Download flow:**
1. Dedup gate: reject if `is_already_downloaded(sc_track_id)` → True
2. Register as 'downloading' in registry (blocks parallel duplicates)
3. Resolve source URL (official → transcodings fallback)
4. Download by protocol (progressive=`_stream_file_to_temp`, hls=`_download_hls_to_temp`)
5. Move to `SoundCloud/{Artist}/{Title}.ext`
6. SHA-256 hash → content dedup check
7. Register as 'downloaded'
8. Background thread: analyze (BPM/key) → import → auto-sort into SC playlist

| Method / Function | Description |
|-------------------|-------------|
| `download_track(**kwargs)` | Start download; returns task_id immediately |
| `get_task_status(task_id)` | Returns task dict or None |
| `cleanup_processes()` | atexit hook (no-op; no subprocesses held) |
| `_resolve_official_download_url(id, token)` | v1 `/tracks/{id}/download` resolver |
| `_resolve_stream_via_transcodings(id, token)` | v2 transcodings[] resolver with legal gates |
| `_stream_file_to_temp(url, token)` | Progressive HTTP download to temp |
| `_download_hls_to_temp(m3u8, token, mime)` | HLS segment download + ffmpeg `-c copy` mux |

---

## USB Manager (`app/usb_manager.py`)

| Class | Key Methods | Purpose |
|-------|------------|---------|
| `UsbDetector` | `scan() → [Device]`, `is_rekordbox_usb(drive)`, `initialize_usb(drive)` | Detect and validate Rekordbox USB drives, initialize new drives |
| `UsbProfileManager` | `get_profiles()`, `get_profile(id)`, `save_profile(p)`, `delete_profile(id)`, `get_settings()`, `save_settings(s)`, `get_usb_contents(id)` | Persistent sync profile CRUD (which playlists → which drive) |
| `UsbSyncEngine` | `calculate_diff()`, `sync_collection(profile)`, `sync_playlists(profile, ids)`, `sync_metadata(profile)`, `_sync_library_legacy(profile, ids)` | Incremental sync with lock-file concurrency, diff calculation, XML export w/ control-char sanitization |

**`UsbSyncEngine` notes**:
- Drive letter normalization: bare `"E:"` → `"E:\\"` to ensure absolute paths in file URLs
- XML safety: `_xml_safe()` strips ASCII control chars (0x00-0x1F except tab/LF/CR) from Rekordbox metadata before writing — prevents ElementTree from writing unparseable XML
- Filename safety: `_clean_filename()` strips trailing dots/spaces and rejects Windows reserved names (CON/PRN/AUX/NUL/COM1-9/LPT1-9). Without this, Windows silently drops trailing dots at mkdir time and later writes to the requested path fail with ENOENT.
- Copy-error classification: only real disconnects — `winerror` in `(21, 31, 1167, 3)` OR `self.usb_root.exists()` returning False — abort the batch. Plain ENOENT on a single bad path is logged and skipped so one bad track doesn't kill a 3000-track sync.
- Uses file lock (`.rbep_sync_lock`) to prevent concurrent syncs
- All sync methods are generators: yield `{ stage, message, progress }` events; `stage="complete"` or `stage="error"` on finish

---

## Backup Engine (`app/backup_engine.py`) — `BackupEngine`

Git-like incremental backup (~95% smaller than full copies via compressed JSON diffs).

| Method | Returns | Description |
|--------|---------|-------------|
| `commit()` | `str` (commit hash) | Diff vs HEAD, compress changeset, update HEAD |
| `get_timeline()` | `[Commit]` | All commits with timestamp, hash, summary |
| `restore(commit_id)` | `bool` | Roll back library to a specific commit |

---

## Other Modules

| Module | Class / Function | Purpose |
|--------|-----------------|---------|
| `app/rbep_parser.py` | `RbepSerializer` | Parse + serialize `.rbep` XML: volume envelopes, hot cues, memory cues, beatgrids, tempo maps. Entry points: `parse_project(path)`, `serialize(state, path)` |
| `app/rekordbox_export.py` | `export_track_to_xml(analysis_result)` | Convert `AnalysisEngine` output → Rekordbox XML `TRACK` element with `TEMPO` nodes and `POSITION_MARK` cues |
| `app/rekordbox_bridge.py` | `export_selection(track_ids, dest_path)`, `import_xml(src_path)` | High-level bridge: export selected tracks → XML; import from XML |
| `app/xml_generator.py` | `RekordboxXML` | Generate valid `DJ_PLAYLISTS` XML: `add_track(track)`, `add_playlist(name, tracks)`, `write(path)` |
| `app/sidecar.py` | `SidecarStorage` | Persist artist metadata (SC links, custom fields) in `app_data.json`. Methods: `get(artist_id)`, `set(artist_id, data)` |
| `app/batch_worker.py` | CLI tool | Batch track comment/tag update via rbox `MasterDb`. Run directly: `python -m app.batch_worker --help` |

---

## Response Envelope (all endpoints)

```python
# Success
{"status": "ok", "data": ...}

# Error
{"status": "error", "message": "Human-readable description", "code": "ERROR_CODE"}
```

**Error codes**:
| Code | Meaning |
|------|---------|
| `REKORDBOX_RUNNING` | Can't write — Rekordbox is open |
| `PATH_SANDBOX_VIOLATION` | Path outside `ALLOWED_AUDIO_ROOTS` |
| `AUTH_EXPIRED` | SoundCloud auth token expired |
| `RATE_LIMITED` | SC API rate limit (429) |
| `FILE_NOT_FOUND` | Audio file missing from disk |
| `ANALYSIS_PENDING` | Task still running |
| `ANALYSIS_FAILED` | Analysis task failed |
| `USB_LOCKED` | Another sync is in progress |
