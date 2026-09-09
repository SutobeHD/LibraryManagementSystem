# FILE_MAP.md — LibraryManagementSystem

> **Read this first.** One-line-per-file map of the entire codebase. Use this to find the right file for any task without searching blindly.
> Last updated: 2026-05-17

---

## Root

| File | Purpose |
|------|---------|
| `CLAUDE.md` | AI agent coding rules, principles, mandatory post-edit workflow |
| `package.json` | Root npm scripts: `dev:full` (starts all), `tauri dev`, `tauri build` |
| `requirements.txt` | Python deps: FastAPI, uvicorn, psutil, requests, sqlalchemy, librosa, scipy, numba, keyring, python-dotenv, soundfile, lameenc, numpy, rbox, madmom, essentia, **platformdirs** (added for `app/auth.py` cross-platform `user_data_dir` — session-token file lives at `%APPDATA%/MusicLibraryManager/.session-token` on Windows / `~/Library/Application Support/MusicLibraryManager/` on macOS / `$XDG_DATA_HOME/MusicLibraryManager/` on Linux) |
| `pyproject.toml` | Python tooling config (ruff + black + mypy) |
| `README.md` | Project overview, features, tech stack, setup instructions |
| `docs/HANDOVER.md` | Cleanup-protocol used by Phase 1-5 cleanup work |

---

## app/ — Python FastAPI Backend

| File | Purpose |
|------|---------|
| `app/main.py` | **All API routes** — see backend-index.md for full route list. Also contains `validate_audio_path()` (uses `Path.is_relative_to` against resolved roots — no startswith), request models, startup event, CORS config (explicit method whitelist), global error handlers, `_db_write_lock` (RLock serialising rbox writers). **Phase-1 Bearer-token auth (commits `1c7d410..f90f5f8` + `8498937`)**: every POST/PUT/PATCH/DELETE route declares `dependencies=[Depends(require_session)]` from `app/auth.py` — 84 of 85 mutation routes gated; `POST /api/system/heartbeat` is the only intentional exception (loopback healthcheck, body-less, no token leak). The earlier `SHUTDOWN_TOKEN` + `POST /api/system/init-token` query-string scheme was DELETED in commit `7dfdef5` — `require_session` is now the single auth axis for shutdown/restart and every other mutation. `_get_or_create_profile()` refreshes `drive` + `filesystem` from live scan on every call so `UsbSyncEngine` picks the correct path-length limit (exFAT=255 vs FAT32=240). |
| `app/auth.py` | **NEW** Bearer-token auth module. Self-generates the session token at sidecar boot (`secrets.token_urlsafe(32)`, main process only — worker subprocesses get empty string), emits it once as `LMS_TOKEN=<value>\n` on stdout (captured + scrubbed by Tauri Rust supervisor in `src-tauri/src/main.rs`), persists to `<user_data_dir>/MusicLibraryManager/.session-token` via `platformdirs` (browser-dev fallback path; Vite dev-middleware re-exposes it at `GET /dev-token`). Exposes `require_session(authorization)` FastAPI dependency — parses `Authorization: Bearer <token>`, strips whitespace, calls `safe_compare` against `SESSION_TOKEN`, raises `HTTPException(401, "Unauthorized")` on any failure. **MUST NOT log the token at any level** — not INFO, not DEBUG, not redacted. Best-effort `chmod 0o600` on POSIX (NTFS silently rejects, non-fatal). Token rotates only on sidecar process restart (Phase-1 policy). |
| `app/security_compare.py` | **NEW** Constant-time equality helper. `safe_compare(presented, expected)` wraps `secrets.compare_digest` with input validation so callers never have to hand-roll the `isinstance` / `isascii` / length-equal pre-checks the primitive otherwise requires. Returns `False` (never raises) for the 5 fragility cases from the audit's behavior matrix: (1) non-`(str\|bytes)` inputs, (2) non-ASCII `str` presented, (3) non-ASCII `str` expected, (4) mixed `str`/`bytes`, (5) length mismatch. Trust direction is part of the public contract — `presented` is request-side (untrusted), `expected` is server-side (canonical). Consumed by `app/auth.py:require_session`. See `docs/research/research/evaluated_security-secrets-compare-digest-codebase-audit.md` Findings #2. |
| `app/rate_limit.py` | **NEW** In-process token-bucket rate limiter. `TokenBucket(steady_per_min, burst)` — monotonic-clock refill, `take()` → `(allowed, retry_after_s)`. `BucketStore` — process-wide RLock-guarded dict, lazy purge (60s sweep interval, 600s idle TTL). `make_key(request, mode)` — loopback IPs (`127.0.0.1`/`::1`) short-circuit to `"__whitelist__"` sentinel; `mode` ∈ `{"ip", "bearer", "both"}` (bearer hashed sha256[:16] so we never key by raw token). `rate_limit(steady, burst, key_mode)` decorator — wraps an async FastAPI handler, raises `HTTPException(429, {"error":"rate_limited","retry_after_s":int})` + `Retry-After` header on bucket-empty. Per the Recommendation block of `docs/research/research/evaluated_security-rate-limit-design.md` (Option B), the decorator is currently applied to the 3 HIGH-tier routes: `POST /api/system/shutdown`, `POST /api/system/restart`, `POST /api/soundcloud/auth-token` (all `steady=5.0, burst=10, key_mode="both"`). Decorator order: `@app.post(...)` outermost → `@rate_limit(...)` inner → `Depends(require_session)` via `dependencies=` kwarg, so 401 fires before the bucket is touched. Remaining MEDIUM/LOW-tier wiring is Phase-2 work. |
| `app/config.py` | Path constants: `REKORDBOX_ROOT`, `DB_FILENAME`, `FFMPEG_BIN`, `EXPORT_DIR`, `LOG_DIR`, `TEMP_DIR`, `MUSIC_DIR`, `DB_KEY` |
| `app/services.py` | 10 business logic classes: `XMLProcessor`, `SystemGuard`, `AudioEngine` (FFmpeg), `FileManager`, `LibraryTools`, `SettingsManager`, `MetadataManager`, `BeatAnalyzer`, `ImportManager` (reads native tags via `audio_tags.read_tags` then falls back to `Artist - Title` filename split — no longer hardcodes "New Import"/"Imported"), `ProjectManager`. `LibraryTools.generate_smart_playlists` builds **labels only** — the retired `By Artist` branch grouped on the raw `track["Artist"]` string (so `boys noize` and `Boys Noize` became two folders) and created unconditionally (so every re-run duplicated every playlist). The `Artists` folder now belongs to `app/artist_store/projection.py`, which is alias-aware, id-mapped and idempotent. `artist_threshold` is still accepted for call compatibility and ignored; the report's `legacy_by_artist` names a leftover folder from the old generator without deleting it — the user's playlists are theirs. |
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
| `app/usb_manager.py` | `UsbDetector` (scan, initialize_usb), `UsbProfileManager` (CRUD for sync profiles + `usb_write_legacy_pdb` setting), `UsbSyncEngine` (sync_collection, sync_playlists default `["library_one", "library_legacy"]`, sync_metadata — lock-file concurrency, XML export w/ control-char sanitization `_xml_safe()`, drive-letter path normalization). `_sync_library_one(profile, playlist_ids)` passes `_get_safe_dest_path` as `dest_resolver` AND `playlist_filter=playlist_ids` to OneLibraryUsbWriter, AND reads `UsbProfileManager.get_settings()["usb_write_legacy_pdb"]` (default False) → when False the legacy PDB writer is skipped (avoids Rekordbox-7 "Device library is corrupted" dialog caused by the still-mismatched PDB structure). `_clean_filename` strips trailing dots/spaces + reserved names (Windows silently drops them). Copy error handler: only real disconnects (drive root missing) abort batch; ENOENT on a single bad filename skips that track and continues. |
| `app/usb_one_library.py` | `OneLibraryUsbWriter` — writes `PIONEER/rekordbox/exportLibrary.db` so Rekordbox 6/7 auto-detects the stick. **Template-based approach** (rbox 0.1.7 workaround): copies bundled `app/templates/exportLibrary_template.db` onto the USB, then mutates its placeholder content rows via `update_content` to populate user data. rbox's `create_content` is fundamentally broken (raises "Unexpected null for non-null column" on every call, and no Python-level NewContent constructor exists) — the template approach bypasses it. Other `create_*` calls (image/artist/album/genre/key/label/playlist) work normally. Hard cap = template's slot count (16 from F: drive baseline); overflow tracks fall through to legacy XML. Optional `dest_resolver` reuses legacy `<USB>/PIONEER/Contents/<Artist>/<Album>/file` tree. `sync(..., playlist_filter=None, write_pdb=True)` restricts both tracks AND playlist tree to the given playlist IDs (their folder ancestors are kept so deeply nested entries still have a valid parent path). When `write_pdb=False` the legacy PDB writer is skipped AND any stale `export.pdb` / `exportExt.pdb` already on the stick are deleted — required because Rekordbox 7 still reads the legacy PDB if present. `_write_pdb_from_db` mirrors whatever ends up in OneLibrary into `export.pdb` / `exportExt.pdb`, so playlist filter applies to both formats automatically. **WAL flush at end of `sync()`** (inline `del db; gc.collect(); time.sleep(0.5)` followed by `_reopen_for_recovery()`): rbox 0.1.7 exposes no `close()`/`commit()`/PRAGMA — letting the handle fall out of scope leaves up to 400 KB of unmerged WAL frames. The `del` MUST run in `sync()`'s scope (not inside a helper that takes `db` as a parameter — that only drops the local binding, leaving the outer ref alive in the generator frame). Verified by `tests/test_onelibrary_wal_flush.py` — WAL = 0 bytes after the cycle. Replaces an earlier 1100-cycle dummy `update_content` loop that relied on SQLite's PASSIVE auto-checkpoint and never truncated the WAL file. **Stage 1b — folder relocation:** when only the artist folder changed (an Artist-Hub merge renames `boys noize` to `Boys Noize`), the existing file is MOVED instead of re-copied; a case-only change needs the two-step rename on Windows, whose filesystem is case-insensitive. **Both relocation branches require a content fingerprint** — `sha1(size + first 64 KiB + last 64 KiB)`, `None` on `OSError` — and an unreadable file counts as *not proven*: matching on filename + byte count alone also matches a re-exported version belonging to a track outside this sync, and the copy phase (which also compares sizes) would then see nothing to repair, leaving the wrong audio at the destination with the moved file's own row dangling. The identical-size collision branch **deletes from the stick**, so it carries the same gate: same name plus same size is not proof of the same recording. **`sync()`'s own Stage-1b call path has no regression test** — `tests/test_usb_relocate.py` covers the relocation helpers directly. Back the stick up before the first real run. |
| `app/templates/build_template.py` | CLI tool: `python -m app.templates.build_template <path_to_rekordbox_stick>` — derives a clean+anonymised exportLibrary template from any Rekordbox-exported USB stick. Strips playlist tree + my_tags + name fields on artists/albums/labels/keys/genres/images, but keeps the content-row count as our placeholder slot count. |
| `app/templates/exportLibrary_template.db` | Anonymised OneLibrary template (16 placeholder content rows). Used by `OneLibraryUsbWriter.sync` as the writeable base — bypasses rbox 0.1.7's broken `OneLibrary.create()`. Rebuild from a Rekordbox-exported stick with more tracks for higher track caps. |
| `app/usb_mysettings.py` | CDJ + DJM hardware-settings writer for `<USB>/PIONEER/MYSETTING.DAT`, `MYSETTING2.DAT`, `DJMMYSETTING.DAT`. 42 editable fields total (22 player + 7 player-extended + 13 mixer). Uses `pyrekordbox.MySettingFile`/`MySetting2File`/`DjmMySettingFile`. Public API: `get_schema()` (JSON for frontend dropdowns), `read_settings(usb_root)`, `write_settings(usb_root, values)`, `write_defaults(usb_root)`. Auto-seeded on every sync via `UsbSyncEngine._ensure_usb_structure`. API routes: `GET /api/usb/mysettings/schema`, `GET /api/usb/mysettings/{device_id}`, `POST /api/usb/mysettings`. |
| `app/usb_artwork.py` | Cover-art extraction + bucketed write. `get_artwork_bytes(audio_path)` reads embedded ID3 APIC / FLAC Picture / MP4 covr atom, falls back to `cover.jpg` sidecar. `write_artwork_pair(audio_path, image_id, pioneer_dir)` resizes via Pillow to small (~80×80) + medium (~500×500) JPEGs and drops them at `PIONEER/Artwork/<bucket>/a<id>.jpg` + `_m.jpg`. Bucket = `image_id // 1000` zero-padded. `usb_relative_path(image_id)` returns the `/PIONEER/Artwork/...` URL stored in OneLibrary's `image.path` field. |
| `app/usb_pdb.py` | Full `export.pdb` + `exportExt.pdb` writer (legacy CDJ DeviceLibrary). Implements the Crate Digger spec from scratch: file header, 20-table directory, 4 KiB pages with bit-packed row count + reverse-order row index footer, DeviceSQL string encoder (short ASCII / long UTF-16-LE). Row encoders for tracks (djmdContent 0x00, 0x88-byte fixed header + 21 string offsets), **genres (0x01: `<I id>` + DeviceSQL — no constant)**, **artists (0x02 far-name 0x0060: 10-byte header `<HHIBB>`)**, **albums (0x03 far-name 0x0080: 22-byte header `<HHIIIIBB>`)**, labels (0x04: `<I id>` + DeviceSQL), **keys (0x05: `<II id, id_mirror>` + DeviceSQL — mirror = id, not 1)**, **colors (0x06: 8-byte header `<IBBH>` with id mirror)**, playlist tree (0x07), playlist entries (0x08), **artwork (0x0D: `<I id>` + DeviceSQL path, padded align=4)** — pulls from OneLibrary's image table via `_write_pdb_from_db()` so legacy CDJs see the same cover art as Rekordbox 7. All row encoders verified BYTE-IDENTICAL to F: drive Pioneer reference via `python -c "from app.usb_pdb import encode_*_row"` test. exportExt.pdb has its own 5-table directory: tags (0x03 subtype 0x0684 far-name with category folder support), tag_tracks (0x04 16-byte association rows). Public API: `write_export_pdb(usb_root, contents, artists, albums, keys, genres, labels, playlists, playlist_entries)`, `write_export_ext_pdb(usb_root, tags, tag_categories, tag_track_links)`. Linear-scan only — no functional B-tree indices (heap is structured but always 0 entries). Works for libraries ≤ ~500 tracks. **Anti-corruption fixes (verified vs. F: drive byte-by-byte)**: (1) Per-table `empty_candidate` — 20 contiguous all-zero blank pages appended after data/index pages, each table descriptor's `empty_candidate` points at its own dedicated blank. Sharing one global blank across all 20 tables made Rekordbox 7 flag "Device library is corrupted". (2) Chain terminator `next_page` patched from 0 → that table's OWN blank page index. (3) Header `@0x10`=4 (was 5), `@0x14`=`page_seq + 1` (was hardcoded 128). (4) Row encoders fixed: 5 encoders (genre/key/label/artist/album/color) had wrong header layouts; verified byte-identical to F: drive samples now. (5) `free_size` formula uses EFFECTIVE footer size `(full_groups × 36) + (2 × partial_rows + 4)` instead of physical 36-byte block size — Rekordbox checks page accounting against this. Verified across F: pages 4 (1 row), 6 (14), 8 (16), 12 (10), 14 (8), 18 (16), 34 (27 multi-group). (6) Data-page header tx_count/tx_idx: single-group → `(1, n-1)`, multi-group → `(n, 0)`. (7) Row footer block[34:36] = `1 << (rows_in_group - 1)` (last-row bit position). (8) Data-page flag `0x34` for tracks (bit 0x10), `0x24` for other tables. (9) Index-page heap: 24-byte structured prefix + `0x1FFFFFF8` sentinel padding. (10) Empty tables = single index page (first==last). Regression test in `tests/test_pdb_structure.py` verifies all structural invariants. |
| `app/rekordbox_export.py` | Converts `AnalysisEngine` results → Rekordbox XML `TRACK` elements with `TEMPO` nodes and `POSITION_MARK` cues |
| `app/rekordbox_bridge.py` | High-level: export selected tracks → Rekordbox XML; import from XML exports |
| `app/rbep_parser.py` | Parses `.rbep` (Rekordbox Editor Project) XML. Real-format aware: `<filepath>` directly under `<song>`, `<edit>` directly under `<track>`, `<position>/<data>/<section>` collected as a list (not a single object). Exposes `positions[]` and `editEndBeats` for timeline duration. Volume envelopes, BPM maps, hot cues, memory cues, beat grids |
| `app/xml_generator.py` | `RekordboxXML` — generates valid `DJ_PLAYLISTS` XML from Python track data with dynamic/static beatgrids and cue points |
| `app/sidecar.py` | `SidecarStorage` — persists artist metadata (SoundCloud links, custom fields) in `app_data.json` sidecar file |
| `app/batch_worker.py` | CLI tool for batch track metadata updates (comments/tags) using rbox `MasterDb` — find/replace/append/set operations |
| `app/playcount_sync.py` | **NEW** USB Play-Count Sync engine: `load_usb_sync_meta`, `save_usb_sync_meta`, `diff_playcounts` (three-way diff), `resolve_playcounts` (commits to PC DB + USB XML), `read_usb_xml_playcounts`. API: `GET /api/usb/playcount/diff`, `POST /api/usb/playcount/resolve` |
| `app/phrase_generator.py` | Phrase & Auto-Cue Generator: `extract_beats_from_db`, `detect_first_downbeat` (librosa low-band energy), `generate_phrase_cues` (phrase/bar markers), `phrase_cues_to_memory_dicts`, `resolve_anlz_dir`, `commit_phrase_cues(track_id, cues, db_path, *, include_bar_markers=False)` — writes phrase markers as Rekordbox **MEMORY cues** into the track's existing ANLZ via `anlz_cue_patch.patch_memory_cues` (non-destructive; beat grid + waveform + hot cues preserved). Raises `PhraseNotAnalysedError` if no ANLZ. (Old broken `commit_cues_to_db` / rbox `set_hot_cues` removed.) API: `POST /api/phrase/generate`, `POST /api/phrase/commit`, `POST /api/phrase/batch/{start,cancel}`, `GET /api/phrase/batch/status` |
| `app/anlz_cue_patch.py` | **NEW** Non-destructive memory-cue patcher for an existing ANLZ. `patch_memory_cues(anlz_dir, memory_cues, *, backup=True)` walks the PMAI tag chain and replaces ONLY the memory-cue (`cue_type==0`) PCOB/PCO2 tags, carrying every other tag (PQTZ beat grid, PWAV/PWV* waveforms, hot-cue PCOB, PSSI) through byte-for-byte, recomputing the PMAI length, backing up originals first. Reuses `anlz_writer`'s tag builders so output is byte-identical. Helpers: `_walk_tags`, `_patch_one_file`. Idempotent across re-runs. |
| `app/soundcloud_auth.py` | **NEW** SoundCloud OAuth token store + silent refresh — the persistent login. Keyring entry `sc_oauth` holds ONE JSON blob (`access_token`, `refresh_token`, `expires_at`, `obtained_at`, `scope`) so a store is a single atomic `set_password`; the legacy bare `sc_token` entry is mirrored on every store, because ten `keyring.get_password(..., "sc_token")` readers in `app/main.py` predate this module. **Blob wins when both exist**, legacy-only is still honoured (nobody gets logged out by the upgrade). `get_access_token(min_ttl_s=120)` refreshes behind the call; `refresh()` is single-flight behind a module-private lock and re-reads the blob inside it — SoundCloud rotates the refresh token on every use, so two concurrent refreshes would burn each other's. Exactly two failure classes: `AuthExpiredError` (token endpoint said 400/401 — both entries cleared, user must press Login) and `TransientRefreshError` (network / 5xx / 429 / malformed — blob kept untouched). Only ever talks to `secure.soundcloud.com/oauth/token`, never to the API. **Never log the token** — same rule as `SESSION_TOKEN`. Known untested risk: Windows Credential Manager caps a secret at 1280 UTF-16 chars; the blob is far below that but has not been measured against a long-scope response. |
| `app/artist_store/schema.py` | Sidecar DB (`artists.db`) + migration runner for the Artist Hub. Owns what Rekordbox has no place for: favourite collections, the alias groups a merge collapses, the SoundCloud binding, per-collection sync state, the `collection -> Rekordbox playlist` id-map, the catalogue TTL cache. **Not `master.db`** — writes serialise on a module-private lock and `app/database.py:_db_write_lock` is never taken from here (that one belongs to rbox). Feature rollback = `rm artists.db`; no library data lives here. Pattern mirrors `app/auth_db.py` (platformdirs path, per-thread connection, WAL + `synchronous=NORMAL`) and `app/variant_schema.py` (`SCHEMA_VERSION` + step-walking `migrate()` with a downgrade guard). `kind` is generic on purpose — label / genre / setlist are the same rows with a different `kind`, which is why `(kind, sort_key)` is indexed. Route-free by design. |
| `app/artist_store/registry.py` | Library artists into store collections, favourites, Tier-1 backlog. **Bridges on the NAME, never on the UI's `art_{i}` ids** — those are positions in a list rebuilt on every library load (`app/live_database.py:_finalize_ui_metadata`). Splitting/normalising is NOT redone here: `_split_artists` / `_normalize_artist_name` already ran at load time and their output *is* `db.artists`; a second normaliser would drift from the first. Only `resolve_library_artists` + the favourite mutators write — `hub` / `backlog` / `browse` / `list_favourite_artists` are pure reads, so the Tier-1 backlog makes **zero** network calls. |
| `app/artist_store/merge.py` | Duplicate-artist detection, preview, apply, revert — the Original Idea's "mehrfache Kuenstler vom gleichen durch Kleinschreibung". **Deterministic folds only, never fuzzy matching**: a false merge repoints tracks onto the wrong artist and, once the variant rows are gone, the groups cannot be told apart again. `fold_key` folds case, whitespace runs, `.`/`-`/`_`/unicode dashes to a space, apostrophes deleted, `&` to `and`. An initialism (`M.A.N.D.Y.` vs `MANDY`) or a typo deliberately stays separate — missing a group costs a click, merging two real artists costs data. `candidates` / `preview` / `preview_many` write **nothing** (not `master.db`, not the audio files, not the sidecar). `apply` + `revert` are the only mutating entry points and both journal every row into the metadata-fixer undo log under one `run_id`. Apply writes `master.db` **and** rewrites the audio file tags (owner decision 2026-09-04). Uses `update_content(item)` — NOT `update_content_artist`, which leaves `rb_local_usn` stale (measured against an owner-approved `master.db` copy). |
| `app/artist_store/identity.py` | Name-based, remix-aware track roles + the identity table. Owner decision 2026-09-08: most of a label-signed artist's catalogue is uploaded by labels, promo channels and DJs, so uploader-URN equality alone misses most of it — the artist is identified by **name** (title artist prefix, uploader name, remixer credit), with the URN kept as the *highest-confidence* signal rather than the only one. Roles: `primary`, `remixer` (**their music — a DJ wants their own remixes**), `remixed_by_other`, `featured`, `uncertain`. Name comparison is `merge.fold_key` — no edit distance; a near-spelling lands in `uncertain` with the spelling shown, never in `primary`. Remix rules that go wrong elsewhere: `Overdrive (Boys Noize Remix)` is `remixer`; `Boys Noize - Overdrive (Erol Alkan Remix)` is `remixed_by_other`; `(Extended Mix)` is `primary`; a name appearing ONLY inside `(X Remix)` is never `primary`. `auto_queue_eligible()` additionally refuses anything matched **only** on the uploader name — a promo channel's name is not a credit. |
| `app/artist_store/catalogue.py` | Classify an artist's SoundCloud tracks + diff against the library. Three separable jobs: `classify` (mix/set gate, then the `identity.py` role buckets), `diff` ("do I already own this?" — reuses `app/external_track_match.py` `parse_version_tag` / `extract_title_stem` / `fuzzy_match_with_score` behind a **derivation gate** so a remix/VIP never collapses onto the original it derives from; a bare parenthetical like `(Remix)` counts as a derivation), `catalogue` (ties the two over the sidecar TTL cache — the **fetched catalogue** is cached, never the diff, because the local side changes whenever the library does). **Never sees the OAuth token**: the fetch callable is supplied by the caller, so there is nothing here to log or key on. Pure + stdlib apart from the sidecar schema — no HTTP, no `master.db`, no rbox. |
| `app/artist_store/projection.py` | Mirrors favourite collections into Rekordbox: one flat `Artists` folder at the library root, one playlist per favourite, each holding that collection's local tracks **including every alias variant** (a merged artist projects as ONE playlist). Three measured facts shape it (Findings waves 4+5, reproducible via `scripts/dev/rbox_artist_merge_probe.py`): (1) `djmdPlaylist` has **no** uniqueness on `(Name, ParentID)` or `UUID` — creating the same folder twice yields two siblings and `get_playlist_by_path` silently returns the first, so the sidecar owns the id-map and a name lookup happens exactly once (to adopt something pre-existing); (2) rbox mints a fresh UUID per create and bumps the USN itself (+2/node) — neither is a re-run key; (3) rbox maintains `masterPlaylists6.xml` beside `master.db` and **silently skips** that update when the file is absent, so playlists written in that state vanish from Rekordbox on the next restart — a missing XML path **refuses the run** rather than half-projecting. Diff-in-place, never delete-and-recreate: re-syncing an unchanged artist performs **zero** `master.db` writes. All writes go through the `RekordboxDB` facade (which holds `_db_write_lock`); `db.active_db` is never touched. |
| `app/artist_store/discovery.py` | Tier-2 suggestions — artists the user does **not** have yet, seeded from the favourites. Two tiers: (1) `GET /users/{urn}/related` **once per linked favourite, one hop** — `related()` is never called on a result, because a transitive crawl is exactly what the ToU guardrails forbid; the returned User objects already carry `track_count` / `followers_count`, so ranking costs no follow-up call. (2) Uploader co-occurrence over catalogue payloads already cached in the sidecar — **zero network calls**, and the only source when tier 1 was empty, failed or never queried. A 404 (deleted / private / renamed account) is a normal outcome, never an error. **Per-source state is reported, and an abort outranks a partial success**: a walk that answered for one seed and was then stopped by a 429 or an expired session reports `failed`, not `ok` — otherwise the UI claims "both sources answered and turned up nobody" about favourites that were never asked. Every run holds a hard `soundcloud_api.CallBudget`; one is created when the caller supplies none, so an unbudgeted crawl is unreachable. Credentials never live here — the caller passes a resolved token. |
| `app/artist_store/sync.py` | The idle signal + the background catalogue refresh. **The idle signal** did not exist anywhere, so it is *composed* from the trackers that do: phrase batch, artist jobs, duplicate scan, SoundCloud downloader, local-import tracker, and the single-flight locks guarding USB sync / merge / projection / batch download. `is_idle()` returns `(bool, reason)` so the log and the UI can say **why** a pass did not run. Every probe **fails closed** — an exception, an unknown job status or an unreadable tracker means *busy*. One load path is genuinely unobservable and is named rather than hidden: `POST /api/library/analyze-batch` streams NDJSON and keeps no job record, so `idle_report()` lists it under `unobservable` and `register_probe()` is the hook to close that gap. **The background pass** refreshes every favourite whose mode is `auto` or `review` through the *caller's* refresher — the same route body the manual Update button uses, never a second fetcher — oldest-last-synced first, under **one** shared `CallBudget`, re-checking idle between artists; `off` is skipped without a call. It **never downloads and never queues**: `downloads_queued` is in the run record and is always `0` so the invariant is observable, not merely asserted. Off by default (`artist_background_sync`). No HTTP, no credentials, no `master.db` here — the refresher owns all three. **Known limit:** the call budget is per pass, not per day. |
| `app/artist_store/__init__.py` | Package init for the Artist-Hub sidecar (`artists.db`). |
| `app/__init__.py` | Package init (empty) |

---

## frontend/src/ — React Frontend

### Core

| File | Purpose |
|------|---------|
| `frontend/src/main.jsx` | App root: lazy-loaded tab views, session token init, global error boundary, tab router. **Unified TopBar** — brand + workspace tabs (Library / Audio Import / Ranking / Editor / Sync / Utilities) + library status + Settings/Exit. Per-workspace views in an in-content `WorkspaceNav` strip (Library → Playlists/Artists/Labels/Albums `lib-*`; Utilities → one flat tab per tool + per Library-Health filter via `util-*`, + Insights). DotGridBackdrop for selection/loading screens (24px radial dots, amber2, no gradient blur). |
| `frontend/src/api/api.js` | **Central Axios instance** — always use this. Phase-1 Bearer-token bootstrap: at module load, `_bootstrap()` races (1) Tauri IPC `get_session_token` (when running in Tauri) → (2) browser-dev fallback `GET /dev-token` (Vite dev-middleware reads the on-disk `.session-token`). Resolves into `setSessionToken(token)` from `authStore.js`; on hard failure flips `_authBootstrapFailed=true` and surfaces a persistent toast (`id: 'auth-bootstrap-failed'`). The bootstrap promise is exposed via `setBootstrapPromise()` so any view can `await` it. Request interceptor blocks on the bootstrap promise the FIRST time through, then attaches `Authorization: Bearer ${token}` to every request. Also: 401 refresh queue, 429 exponential backoff, HttpOnly cookie support, 10s default timeout (disabled for long-running calls like `/api/usb/sync` via `{ timeout: 0 }`), Tauri context detection. |
| `frontend/src/store/authStore.js` | **NEW** Tiny module-level auth state shared across the frontend. `setSessionToken(token)` / `getSessionToken()` — current Bearer token (set by `api.js` bootstrap). `setBootstrapFailed(flag)` / `isAuthBootstrapFailed()` — flag flips true if both bootstrap paths fail (corrupted token file, IPC unregistered, fresh dev clone with no sidecar). Mutation UI is expected to disable itself when set so the user doesn't fire writes that will only 401. Read-only views stay functional. `setBootstrapPromise(p)` / `getBootstrapPromise()` — stash the bootstrap promise so anything awaiting initial token-fetch (e.g. `main.jsx` top-level effect) doesn't re-run the IPC handshake. |
| `frontend/vite.config.js` | Vite: React plugin, `/api` proxy → localhost:8000, Tauri integration. **NEW `devTokenPlugin`** — registers `GET /dev-token` middleware that reads the on-disk `.session-token` file from the cross-platform user-data dir (`%APPDATA%/MusicLibraryManager/.session-token` on Windows, `~/Library/Application Support/MusicLibraryManager/` on macOS, `$XDG_DATA_HOME/MusicLibraryManager/` on Linux) and returns the token as `text/plain`. Returns 404 if the file is missing (start the sidecar first) or empty. Exists so the browser-dev path (running `npm run dev:full` outside Tauri) can pick up the Phase-1 Bearer token without the Rust supervisor's stdout reader. |
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
| `frontend/src/components/PlaylistBrowser.jsx` | Rekordbox playlist tree navigation, calls `GET /api/playlists/tree`. The smart-playlist button generates **labels only** (threshold from `SMART_PLAYLIST_LABEL_THRESHOLD`) — it no longer claims to generate artists, because the `Artists` folder is the Artist Hub's projection. |
| `frontend/src/components/MetadataView.jsx` | Track metadata editor: title, artist, album, genre, comments, calls `POST /api/track/{tid}` |
| `frontend/src/components/TrackTable.jsx` | Reusable sortable track table with Camelot wheel colors, BPM/key display, multi-select |
| `frontend/src/components/Player.jsx` | Compact audio player with play/pause, volume, amber mirror-waveform scrubber (click + drag seek), stream via `GET /api/stream` |
| `frontend/src/components/SoundCloudView.jsx` | SC track search and preview interface |
| `frontend/src/components/SoundCloudSyncView.jsx` | SC sync: match SC tracks to library, trigger download, preview matches |
| `frontend/src/components/SoundCloudProgressModal.jsx` | Download progress overlay with per-track status |
| `frontend/src/components/UsbView.jsx` | USB device manager — filters USB sticks only (no system/fixed drives). Main Sync Source toggle (PC/USB), Target Ecosystem card, dynamic storage bar colors, Eject in header, Playlists above Contents. Compat matrix: orange AlertTriangle for wrong-format, red X for incompat. ETA placeholder. Includes inline collapsible MetadataSyncPanel (smart/manual sync modes, category checkboxes). Sub-components: `Toggle`, `PillBtn`, `PillTab`, `Row`, `SpaceBar`, `PlaylistTreeNode`, `UsbLibraryTree`, `PlayCountSync`, `MetadataSyncPanel` |
| `frontend/src/components/UsbSettingsView.jsx` | CDJ + DJM hardware-settings editor (writes `PIONEER/MYSETTING.DAT`, `MYSETTING2.DAT`, `DJMMYSETTING.DAT`). Device picker → 3 file tabs (Player / Player Extended / Mixer) → groups → labelled dropdown per field. Fetches schema dynamically from `/api/usb/mysettings/schema` (no hardcoded enum tables — keeps frontend in lock-step with pyrekordbox). Reset-to-defaults + dirty-state guard on device switch. |
| `frontend/src/components/XmlCleanView.jsx` | Rekordbox XML cleanup/validation tool, calls `POST /api/xml/clean` |
| `frontend/src/components/InsightsView.jsx` | Library analytics: low quality, no artwork, lost tracks, bitrate stats |
| `frontend/src/components/RankingView.jsx` | Track ranking/sorting by quality metrics |
| `frontend/src/components/ImportView.jsx` | Two-panel import: left drop zone + file list, right settings panel (Library Quality Analyzer, Format Conversion with all audio formats, Safe Deletion Protocol with backup toggle) |
| `frontend/src/components/SettingsView.jsx` | **Tabbed** preferences panel (8 tabs): Library, Export, USB Profiles, Audio (CPAL device), Analysis (quality + `artist_view_threshold`), Appearance (band colors + locale), Shortcuts (key capture), Network (proxy, SoundCloud sync, `artist_background_sync`). Calls `GET/POST /api/settings`. **Save is disabled until the GET actually succeeds** (`loaded` flag + a Retry banner): the GET shares the global 10 s axios timeout, and swallowing its failure left the form showing `DEFAULTS` while the backend held real values — Save then POSTs the whole object and wipes every stored setting. |
| `frontend/src/components/ToolsView.jsx` | Batch operations: rename, clean titles, find duplicates, batch comments |
| `frontend/src/components/UtilitiesView.jsx` | Router on `mode` (from workspace nav): each tool (Phrase Cues / Duplicates / XML Cleaner / Converter-placeholder) + each Library-Health filter (Low Quality / Lost / No Cover) is its own `util-<mode>` tab — no inner grid/toggle |
| `frontend/src/components/WaveformEditor.jsx` | Legacy waveform editor (superseded by `DjEditDaw`) |
| `frontend/src/components/PhraseGeneratorView.jsx` | Phrase & Auto-Cue Generator (**batch**): `PhraseScopePicker` (Single/Playlist/Selection/Collection) + config (phrase length 8/16/32, downbeat-align toggle, bar-marker toggle) + Generate (always direct) + `PhraseBatchProgress` via `usePhraseBatch`. Writes phrase markers as MEMORY cues. POST `/api/phrase/batch/start`, GET `/api/phrase/batch/status`, POST `/api/phrase/batch/cancel` |
| `frontend/src/components/PhraseScopePicker.jsx` | **NEW** Phrase-batch scope picker — Single/Playlist/Selection/Collection; self-contained multi-select checklist. `onScopeChange({scope,valid,count,mode})` emits a backend `scope` object. Loads `GET /api/library/tracks`, `GET /api/playlists/tree`, `GET /api/playlist/{id}/tracks` |
| `frontend/src/components/PhraseBatchProgress.jsx` | **NEW** Phrase-batch live progress panel — bar, done/total, %, ETA, written/skipped/failed, current track, cancel, expandable skip/fail reason list. Props: `progress`, `running`, `onCancel`. Pure presentation |
| `frontend/src/components/usePhraseBatch.js` | **NEW** Hook: start + poll a phrase-cue batch (mirrors `DuplicateView`). POST start → poll `/status` @1500 ms → terminal. Returns `{progress, running, error, start, cancel, reset}` |
| `frontend/src/components/DuplicateView.jsx` | **NEW** Acoustic Duplicate Finder: scan library, group by fingerprint similarity, left group list + right card detail panel, master selection, merge play counts, POST /api/duplicates/merge |
| `frontend/src/components/ArtistHubView.jsx` | **NEW** Artist Hub — favourites, the browse column of every library artist (so favourites can be picked), merge candidates, the Rekordbox projection panel and the Discover tab. The lowercase name index keeps **every** matching artist id per folded name, not just the last one — collapsing them silently dropped tracks from the count (Klangkuenstler showed 7 of 15). |

### Artist Hub (`artistHub/`)

Every user-visible sentence lives in a `*Copy.js` module with its own `node --test` file. Reason, recorded because it happened three times: this screen shipped controls that read as live while nothing behind them worked, so each sentence is derived from a real payload field and tested on its own — an empty list may only read as "nothing found" when the payload proves every source actually answered.

| File | Purpose |
|------|---------|
| `frontend/src/components/artistHub/ArtistDetail.jsx` | One artist: local tracks, the SoundCloud catalogue split by role, the missing list (own vs remixes by others), per-track pin/queue, the manual "Link SoundCloud profile" flow and the per-artist Update button |
| `frontend/src/components/artistHub/MergeDialog.jsx` | Merge preview + apply + revert for one fold group — shows what would be repointed and which audio files get retagged before anything is written |
| `frontend/src/components/artistHub/ProjectionPanel.jsx` | The `Artists` folder inside Rekordbox: what is projected right now, and the button that brings it up to date |
| `frontend/src/components/artistHub/artistHubApi.js` | The merge + projection half of the Hub's HTTP surface |
| `frontend/src/components/artistHub/artistCatalogueApi.js` | The SoundCloud half — link, catalogue, download queue |
| `frontend/src/components/artistHub/artistDiscoveryApi.js` | The discovery + background-sync half — `/api/artists/discover`, `/api/artists/sync/status`, `/api/artists/sync/run` |
| `frontend/src/components/artistHub/useArtistCatalogue.js` | Catalogue state + the optimistic half of a pin (move a row into the bucket its new role renders in) |
| `frontend/src/components/artistHub/useArtistDetailActions.js` | The click handlers of the artist detail view |
| `frontend/src/components/artistHub/catalogueCopy.js` | Sentences the artist-detail view has to say out loud — a count the payload never measured (`null`) is not printed as `0` |
| `frontend/src/components/artistHub/mergeCopy.js` | Sentences the merge dialog has to say out loud |
| `frontend/src/components/artistHub/discoveryCopy.js` | Sentences for the Discover tab + the background-sync line. `relatedNote` reads the payload's own `reason` — it must not hardcode the call cap, since a 429 and an expired session leave seeds unasked too. A run that did not happen is reported by its reason, never as a sync |
| `frontend/src/components/artistHub/catalogueCopy.test.js`, `mergeCopy.test.js`, `discoveryCopy.test.js` | `node --test` — pure copy builders, no DOM, no resolver needed (imports carry explicit `.js`) |

### Shared UI Components

| File | Purpose |
|------|---------|
| `frontend/src/components/ToastContext.jsx` | Toast notification provider — `useToast()` → `toast.success/error/info()` — never use `alert()` |
| `frontend/src/components/BatchEditBar.jsx` | Batch editing toolbar for multi-track operations (operates on selection) |
| `frontend/src/components/RenameModal.jsx` | Modal dialog for renaming items, props: `isOpen`, `onConfirm`, `currentName` |
| `frontend/src/components/shared/seededWaveform.js` | Deterministic pseudo-waveform generator + painter — seed → song-shaped RMS+peak envelope → mirrored amber bar canvas. Used by `Player`. |

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
| `src-tauri/src/main.rs` | App init, splashscreen, Tauri commands: `close_splashscreen`, `login_to_soundcloud` (PKCE OAuth; `mode` picks the consent surface — in-app `sc-oauth` webview window by default, OS browser on `"browser"`), `export_to_soundcloud`, **`get_session_token`** (Phase-1 auth IPC). Registers `AudioCommandState` + `SessionToken(Arc<Mutex<String>>)`. **LMS_TOKEN stdout capture**: both shell-sidecar spawn paths feed every line through a reader thread that calls `try_capture_token(line)` — first line matching `^LMS_TOKEN=` is stripped of the prefix, stored in the shared `SessionToken` mutex, and **dropped from the forwarded log stream** so the token never reaches `log::info!` / `log/app.log`. All other lines forward to the normal log channel. The frontend reads the value via the `get_session_token` IPC (returns `"token-not-ready"` until the reader catches the banner). Browser-dev path doesn't use this — it reads the token from the on-disk `.session-token` file via the Vite dev-middleware instead. |
| `src-tauri/src/soundcloud_client.rs` | SC OAuth 2.1 + PKCE: `get_auth_url()`, `bind_callback_listener()` + `accept_callback()` (one-shot HTTP server, split so the caller binds **before** opening the consent page and can unblock a pending `accept()` by connecting to `callback_port()`), `exchange_code_for_token()`. Also contains `Track` struct |
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
| `scripts/dev/phrase_spike.py` | Manual P0 verification: patches phrase memory cues into one real track's ANLZ (timestamped `.bak-*` first; `--restore` rolls back) to confirm whether Rekordbox shows ANLZ memory cues for already-imported tracks. Never writes `master.db`. Run from repo root: `python scripts/dev/phrase_spike.py --track-id N` |

---

## docs/

### Navigation + reference

| File | Purpose |
|------|---------|
| `docs/FILE_MAP.md` | **This file** — master project navigation map, one-line-per-file |
| `docs/architecture.md` | System architecture, data flows (8 flows), security model, performance characteristics |
| `docs/frontend-index.md` | React component index: props, key functions, Tauri IPC calls |
| `docs/backend-index.md` | All 147 FastAPI routes grouped by feature + Python class/method index |
| `docs/rust-index.md` | Tauri commands, Rust module index, event system, crate list |
| `docs/SECURITY.md` | Dependency hardening (Schicht A), threat model, accepted risks |
| `docs/NAMING_MAP.md` | Mapping doc for v0.0.2 rename refactor — kept for audit trail |
| `docs/PROJECT_OVERVIEW.md` | High-level overview (duplicates parts of architecture.md — kept for first-skim) |
| `docs/DOWNLOAD_EVALUATION.md` | SoundCloud track download evaluation notes (research artifact) |
| `docs/HANDOVER.md` | Multi-phase mission briefing (Slopcode-Cleanup) with DoD, status reporting, escalation rules — pattern doc for handing work to fresh AI instances |
| `docs/e2e-testing.md` | E2E interaction workflows: (A) Web Preview via `mcp__Claude_Preview__*` on Vite :5173 + FastAPI :8000, (B) Tauri WebDriver via `tauri-driver` + `msedgedriver`. Channel-picker, Selenium cheatsheet, native-dialog caveats |
| `docs/index.html` | Static HTML viewer for the markdown index docs (not auto-generated) |

### Research & Implementation Pipeline (`docs/research/`)

Feature lifecycle: `research/` → `implement/` → `archived/`. State lives in folder + filename prefix.

| File | Purpose |
|------|---------|
| `docs/research/README.md` | Pipeline rules: stages, prefixes (`idea_`, `exploring_`, `evaluated_`, `parked_`, `draftplan_`, `review_`, `accepted_`, `inprogress_`, `blocked_`, `implemented_`, `superseded_`, `abandoned_`), transition workflow, AI-assistant rules |
| `docs/research/_INDEX.md` | Live dashboard mirroring the file system — update on every `git mv` |
| `docs/research/_TEMPLATE.md` | Copy-on-start template for a new research topic |
| `docs/research/research/exploring_recommender-rules-baseline.md` | Active: BPM/Key/Genre/MyTag/Energy ranking + Camelot harmonic mixing (local + SC modes) |
| `docs/research/research/exploring_recommender-taste-llm-audio.md` | Active: LLM/embedding-based recommender learning from listening behaviour + audio features |
| `docs/research/implement/.gitkeep` | Placeholder; in-flight implementation docs land here |
| `docs/research/archived/.gitkeep` | Placeholder; terminal-state docs land here |

---

## tests/ — Python pytest suite

Only rows added / changed in Phase-1 auth hardening are listed here. Full suite has 200+ tests covering DB / USB / ANLZ / SoundCloud / audio paths.

| File | Purpose |
|------|---------|
| `tests/conftest.py` | **NEW** Pytest fixtures shared across the suite. Headline export: autouse `auth_token` fixture — monkeypatches `app.auth.SESSION_TOKEN` to a known constant (`TEST_SESSION_TOKEN`, length-matched to a real `secrets.token_urlsafe(32)`) AND returns a ready-to-use `{"Authorization": "Bearer <token>"}` header dict so gated-route tests stay short. Tests marked `@pytest.mark.no_auth` opt OUT of the monkeypatch and get the real boot-time token's header instead — used by `test_auth.py` to exercise the genuine 401 branch against a token the test doesn't know. Registers the `no_auth` marker so `--strict-markers` is happy. Importing the module top-level triggers boot-time token generation in `app/auth.py` — intentional, so the suite boots auth exactly once and the FastAPI app graph imports cleanly. |
| `tests/test_auth.py` | **NEW** 20 cases covering the Bearer-parsing edge-case matrix in `app/auth.py:require_session`. Asserts: 401 on missing header, wrong scheme, wrong token, length mismatch, empty value, whitespace-only value, scheme-only no creds, vtab/DEL in token; 2xx on correct Bearer, scheme case-insensitivity, leading/trailing whitespace; heartbeat response has no token field; `/api/system/init-token` is now 404 (deleted); shutdown/restart 401 without Bearer; OPTIONS preflight short-circuits before auth; heartbeat with Bearer header still 2xx. |
| `tests/test_security_compare.py` | **NEW** 17 cases covering the `safe_compare` fragility matrix from `app/security_compare.py`. Asserts: equal str / equal bytes return True; unequal-same-length / length-mismatch return False; empty inputs handled; non-ASCII str returns False (presented / expected / both); mixed str/bytes returns False; non-(str\|bytes) inputs (int / list / None / dict) return False on either side; both-None returns False. |
| `tests/test_rate_limit.py` | **NEW** 7 cases covering `app/rate_limit.py` token-bucket. Asserts: bucket refills at the configured steady rate; burst capacity respected on initial cold start; loopback IPs short-circuit via `_WHITELIST_SENTINEL`; `BucketStore` lazy-purges fully-refilled idle entries; concurrent `take()` under RLock cannot over-spend; `Retry-After` header populated on 429; **auth fires before the rate-limit decorator body runs** (so a missing Bearer header returns 401 without consuming a token). |

---

## tests/e2e/ — Tauri WebDriver Tests

| File | Purpose |
|------|---------|
| `tests/e2e/package.json` | Mocha + selenium-webdriver. Scripts: `test` (smoke), `test:all` (glob) |
| `tests/e2e/smoke.test.js` | Boot test: connects to `tauri-driver` @ 127.0.0.1:4444, launches the built `Music Library Manager.exe`, asserts Select Mode renders + Rekordbox Live click advances UI. Override exe path via `TAURI_APP_BIN` env |
| `tests/e2e/run-driver.ps1` | Launches `tauri-driver --port 4444 --native-driver %USERPROFILE%\.tauri-webdriver\msedgedriver.exe`. Keep terminal open while tests run |
| `tests/e2e/.gitignore` | Excludes `node_modules/`, `package-lock.json` |

External binaries (not in repo):
- `%USERPROFILE%\.cargo\bin\tauri-driver.exe` (install: `cargo install tauri-driver --locked`)
- `%USERPROFILE%\.tauri-webdriver\msedgedriver.exe` (must match WebView2 runtime version — currently 147.0.3912.98)

---

## .claude/ — Claude Code agent configuration

Team-shared agent setup for [Claude Code](https://claude.com/claude-code). Committed to repo so every contributor gets the same allowlist + commands + agents.

### Root config

| File | Purpose |
|------|---------|
| `CLAUDE.md` | **Agent operating manual** — stack overview, build/dev/test commands, coding rules, autonomy boundaries, commit strategy (intensive atomic), git-sync heuristic, research-first rule, self-correction loop with research-lifecycle graduation |
| `.claude/settings.json` | Committed permission allowlist (~70 patterns): npm/pip/pytest/cargo/git-read/gh-read/git-commit + git-fetch/pull-ff-only/branch-switching in `allow`; rm/force-push/.env-writes/master.db-writes in `deny`; push/merge/new-deps in `ask`. Env: `PYTHONDONTWRITEBYTECODE=1`, `PYTHONUNBUFFERED=1` |
| `.claude/settings.local.json.example` | Template for per-machine overrides (e.g. local FFmpeg path). Copy to `.claude/settings.local.json` (gitignored) |

### Slash commands (`.claude/commands/`)

| File | Triggers | Purpose |
|------|----------|---------|
| `.claude/commands/dev-full.md` | `/dev-full` | Start backend (:8000) + frontend (:5173) concurrently |
| `.claude/commands/tauri-dev.md` | `/tauri-dev` | Launch full Tauri desktop app (Rust + Python sidecar + React) |
| `.claude/commands/tauri-build.md` | `/tauri-build` | Production desktop build → `.msi` / `.exe` installers |
| `.claude/commands/test-py.md` | `/test-py [pattern]` | Run pytest with optional filter; reports failing tests with first stack-frame |
| `.claude/commands/audit.md` | `/audit` | npm audit + lockfile-lint + platform security-audit script |
| `.claude/commands/sync-docs.md` | `/sync-docs [subsystem]` | Reconcile `FILE_MAP.md` + index docs against current code via `doc-syncer` |
| `.claude/commands/route-add.md` | `/route-add <METHOD> <path> <purpose>` | Guided FastAPI route scaffold with auth/lock/model boilerplate via `route-architect` |
| `.claude/commands/full-check.md` | `/full-check` | All quality gates: ruff + pytest + cargo check/fmt/clippy + npm build + audit |
| `.claude/commands/sync-check.md` | `/sync-check` | git fetch + 1-line verdict on local-vs-origin drift + open PRs |
| `.claude/commands/commit.md` | `/commit [hint]` | Stage + atomic commit with Conventional-Commits message; auto-splits unrelated changes |
| `.claude/commands/research-new.md` | `/research-new <slug>` | Scaffold new research topic from `_TEMPLATE.md` into `docs/research/research/idea_<slug>.md` + update `_INDEX.md` |

### Subagents (`.claude/agents/`)

| File | Use when | Tools |
|------|----------|-------|
| `.claude/agents/doc-syncer.md` | Sync `FILE_MAP.md` / backend/frontend/rust-index.md + `docs/research/_INDEX.md` against code + research-folder filesystem | Read, Edit, Glob, Grep, Bash |
| `.claude/agents/route-architect.md` | Design new FastAPI route(s) including `_db_write_lock`, `X-Session-Token`, Pydantic models, error handling | Read, Edit, Grep, Glob, Bash |
| `.claude/agents/audio-stack-reviewer.md` | Review Python DSP (`analysis_engine`, `anlz_writer`, `usb_pdb`) or Rust audio (`src-tauri/src/audio/`) for realtime correctness + byte-layout invariants | Read, Grep, Glob, Bash |
| `.claude/agents/test-runner.md` | Run pytest / cargo test / frontend tests, parse output, surface first failure with file:line, suggest fix or escalate | Read, Bash, Grep |
| `.claude/agents/e2e-tester.md` | Drive the actual app via `preview_*` tools (web preview) or Tauri WebDriver. Navigate, click, fill, screenshot, capture console+network logs | All preview tools, Read, Bash |

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
| Change toast/notifications | `frontend/src/components/ToastContext.jsx` |
| Change app settings | `app/config.py` (paths) or `app/services.py:SettingsManager` |
