# frontend/src INDEX

> Component and module map for the React frontend. Update this when adding/removing/renaming files.
> Last updated: 2026-09-05

---

## Entry Point

| File | Purpose |
|------|---------|
| `main.jsx` | App root — single unified top bar (brand + workspace tabs + library status + Settings/Exit). Workspaces: Library · Audio Import · Ranking · Editor · Sync · Utilities. Per-workspace views render in an in-content `WorkspaceNav` strip (shown when a workspace has >1 view); the Library strip carries metadata modes (Playlists/Artists/Labels/Albums) as `lib-<mode>` tabs — `lib-artists` renders `ArtistHubView`, the other `lib-*` tabs render `MetadataView` — the Utilities strip carries one flat tab per tool + per Library-Health filter (Phrase Cues / Duplicates / XML Cleaner / Converter / Low Quality / Lost / No Cover, as `util-<mode>`) plus Insights. Mode picker, error boundary, lazy-loaded tab router (Suspense), heartbeat + library-status polling, session-token injection. |
| `utils/log.js` | Dev-only logger; `log.debug` / `log.info` no-op in production via Vite's `import.meta.env.DEV` guard. `log.warn` / `log.error` always pass through. |
| `config/constants.js` | Frontend-wide tunables: `HEARTBEAT_INTERVAL_MS`, `LIBRARY_STATUS_INTERVAL_MS`, `RENDER_API_TIMEOUT_MS`, `BLOB_URL_REVOKE_DELAY_MS`, `TOAST_DURATION_LONG_MS`, `AUDIO_IMPORT_TIMEOUT_MS`, `IMPORT_TASK_POLL_INTERVAL_MS`, `ARTIST_MERGE_POLL_INTERVAL_MS`, `ARTIST_MERGE_MAX_POLL_FAILURES`, `ARTIST_LONG_OP_TIMEOUT_MS`. |

---

## API Layer

| File | Purpose |
|------|---------|
| `api/api.js` | **Central Axios instance — always import from here, never use raw `fetch()`.** 10s timeout, session-token injection, 401 silent refresh with request queue (prevents parallel re-auth), 429 exponential backoff, HttpOnly cookie support, automatic Tauri-context detection. |

---

## Audio Engine / DAW State

All DAW state is managed in this directory. Do NOT duplicate in component-local state.

| File | Purpose |
|------|---------|
| `audio/DawState.js` | **Barrel module** — composes the five sub-reducers under `dawState/` into the public `dawReducer` and re-exports helpers (`createInitialState`, `snapToGrid`, `cuePointsToState`, `stateToCuePoints`, `HOT_CUE_COLORS`). Surface is bit-for-bit identical to the pre-split monolith. |
| `audio/DawEngine.js` | Web Audio API playback engine — `DawEngine` class managing `AudioContext` lifecycle, multi-source scheduling, region-based playback (play/pause/stop/seek), tempo-aware seeking. |
| `audio/TimelineState.js` | Non-destructive editor's timeline state (regions, markers, beat grid, playhead, selection range, zoom). Exposes `loadAudioSource`, `setSnapDivision`, `addRegion`/`removeRegion`/`updateRegion`, etc. Used by `NonDestructiveEditor`, not the DAW. |
| `audio/RbepSerializer.js` | `.rbep` project file XML parser/serializer with tempo-map handling. Exports `parseRbep`, `buildTempoMap`, `saveRbepFile`. Bidirectional beat↔seconds conversion via tempo maps. |
| `audio/AudioRegion.js` | Non-destructive region data model — region creation/normalisation helpers (`createRegion`) plus gain/fade/start/end-offset metadata. |
| `audio/dawState/helpers.js` | Pure helpers + `createInitialState` factory: `getSnapUnit`, `snapToGrid`, `getPositionInfo`, `normalizeRegion(s)`, `HOT_CUE_COLORS`, `stateToCuePoints`, `cuePointsToState`. Shared by every sub-reducer. |
| `audio/dawState/regions.js` | `regionsReducer` — region create/split/move/delete/resize, clipboard (`COPY_SELECTION`, `PASTE_INSERT`, `DUPLICATE_SELECTION`), volume-envelope writes. Also handles cross-cutting selection-set updates that are part of region mutations. |
| `audio/dawState/transport.js` | `transportReducer` — playhead, BPM, tempo maps, zoom/scroll, snap-grid, edit-mode/tool, project + track meta, source buffer + peaks. Catch-all for non-region "shell" actions. |
| `audio/dawState/selection.js` | `selectionReducer` — `selectedRegionIds` Set and `selectionRange` (time-range). Pure selection actions only; region-mutation side effects live in `regions.js`. |
| `audio/dawState/cues.js` | `cuesReducer` — hot cues `[0..7]`, memory cues (time-sorted), loops with `active`/`colour`, plus `activeLoopIndex`. |
| `audio/dawState/history.js` | `historyReducer` — `PUSH_UNDO` / `UNDO` / `REDO` full-state snapshots (deep clone via JSON round-trip) plus `HYDRATE` (project-load reset). Restores clear the selection set. |

---

## Utilities

| File | Purpose |
|------|---------|
| `utils/log.js` | Dev-only logger (see Entry Point above). |
| `utils/AudioBandAnalyzer.js` | Splits an `AudioBuffer` into 3 frequency bands (lowpass 400 Hz, bandpass 400–2000 Hz, highpass 2000 Hz) via `OfflineAudioContext`. Also generates multi-resolution (r1/r2/r4 LOD) peak arrays for zoom-adaptive rendering, plus `bufferToWav` PCM-WAV exporter. |

---

## Feature Views — Lazy-Loaded Tabs (`components/*.jsx`)

> Every view here is `lazy()`-imported from `main.jsx` and rendered inside `<Suspense>` + a per-tab `ErrorBoundary`.

| File | Purpose | Key API calls |
|------|---------|--------------|
| `components/MetadataView.jsx` | Library browser — mode (`playlists`/`labels`/`albums`) driven by the `mode` prop from the Library workspace nav (no own title/tab bar). Playlists → `PlaylistBrowser`; labels/albums → item grid → `TrackTable`. `lib-artists` is **not** its route any more (see `ArtistHubView`); `main.jsx` holds the last non-artist mode so it doesn't reload behind the hub. The GitMerge hover button still opens the alias-only `POST /api/metadata/merge` for labels/albums, but in `artists` mode it hands over to `artistHub/MergeDialog` (real `master.db` merge, previewed + journalled) instead. Routes to: `lib-playlists\|labels\|albums`. | `GET /api/labels\|albums`, `GET /api/{type}/{id}/tracks`, `POST /api/metadata/merge` |
| `components/ArtistHubView.jsx` | **Artist Hub** — the Artists tab. Left pane: favourites (avatar, canonical name, local track count, SC-link chip, Auto/Review/Off segmented control, per-artist Update, un-favourite). Right pane: three-tab panel — "From your library" = Tier-1 backlog (owned artists by track count desc, favourites excluded, Add button); "All artists" = the complete library artist list from `GET /api/artists/browse`, server-side search + A–Z / most-tracks sort, per-row star that toggles the favourite optimistically (rolls back + toasts on failure) and refreshes the favourites pane and the backlog with it, `showing N of M` header + Load more paging (never silently truncated); "Discover on SoundCloud" **renders disabled** — SoundCloud sync is a later milestone, and Update / Update all are disabled for the same reason with the reason stated in the panel, never stubbed. Clicking any row drills into that artist's local tracks in the shared `TrackTable` (library names resolved via `GET /api/artists`, alias variants fetched and de-duplicated). A **Duplicates · N** button in the header (and a per-row context-menu entry, seeded with that artist) opens `artistHub/MergeDialog`; `artistHub/ProjectionPanel` sits under the suggestion panel and owns the Rekordbox `Artists` folder. A merge, a revert or a favourite change invalidates the cached artist index and re-reads hub, browse, duplicate count and projection state. Routes to: `lib-artists`. | `GET /api/artists/hub`, `GET /api/artists/browse`, `POST /api/artists/favourites`, `DELETE /api/artists/favourites/{collection_id}`, `POST /api/artists/{collection_id}/sync-mode`, `GET /api/artists`, `GET /api/artist/{id}/tracks`, `GET /api/artists/merge/candidates` (badge) — merge + projection calls via `artistHub/artistHubApi.js` |
| `components/RankingView.jsx` | Ranking-mode view: per-track hot-cue / tag / quality controls with embedded `WaveformEditor` in `simpleMode`. Routes to: `ranking`. | `GET /api/library/tracks` |
| `components/InsightsView.jsx` | DJ-style analytics dashboard — BPM histogram, Camelot key wheel, genre breakdown, most-played tracks, library composition (energy/format/era). Routes to: `insights`. | `GET /api/insights/bpm_distribution` (+ others) |
| `components/ImportView.jsx` | Audio import wizard — drag-drop or filesystem picker, scan + analyse, watcher integration. Routes to: `import`. | `POST /api/audio/import` |
| `components/XmlCleanView.jsx` | Rekordbox XML cleaning: drag-drop a file, scan, fix encoding/dead refs. Routes to: `xml`. | `POST /api/xml/clean` |
| `components/UsbView.jsx` | USB device manager **container** — owns device-selection state, sync settings, API polling, modals. Layout-only; per-panel logic moved to `components/usb/*`. Routes to: `usb`. | `GET /api/usb/devices`, `GET /api/usb/diff/{id}`, `POST /api/usb/sync` |
| `components/UsbSettingsView.jsx` | Edits `MYSETTING.DAT` / `MYSETTING2.DAT` / `DJMMYSETTING.DAT` per-stick — CDJ + DJM hardware prefs (auto-cue level, jog mode, fader curves). Schema fetched live from backend. Routes to: `usb-settings`. | `GET /api/usb/cdj_settings/schema`, `POST /api/usb/cdj_settings/save` |
| `components/SoundCloudView.jsx` | SC track search + downloader, OAuth login indicator, per-task progress. Routes to: `soundcloud`. | `GET /api/soundcloud/me`, `POST /api/soundcloud/download`, `scLogin()` (api.js → `invoke('login_to_soundcloud', { mode })`) |
| `components/SoundCloudSyncView.jsx` | Match SC library tracks to local library, preview match-confidence in inspector, trigger downloads. Routes to: `sc-sync`. | `POST /api/soundcloud/preview-matches`, `POST /api/soundcloud/sync` |
| `components/DownloadManagerView.jsx` | Full download manager — per-task stage timeline (Queued → Downloading → Analyzing → ANLZ → Sorting → Completed) for both local-import and SC tasks. Routes to: `downloads`. | `GET /api/import/tasks`, `GET /api/soundcloud/tasks` |
| `components/UtilitiesView.jsx` | **Router on `mode`** (from the workspace nav, no inner grid/toggle). Tools: lazy-loads `PhraseGeneratorView` / `DuplicateView` / `XmlCleanView` / Converter-placeholder. Health: `low_quality`/`lost`/`no_artwork` → track list. Routes to: `util-<mode>` (phrase/duplicates/xml/converter/low_quality/lost/no_artwork). | `GET /api/insights/low_quality`, `GET /api/insights/no_artwork`, `GET /api/insights/lost` |
| `components/PhraseGeneratorView.jsx` | Phrase & Auto-Cue Generator — **batch over a scope** (`PhraseScopePicker`) + config (8/16/32-bar phrase length, downbeat-align toggle, bar-marker toggle) + Generate (always direct, no preview) + live progress (`PhraseBatchProgress` via `usePhraseBatch`). Writes phrase markers as MEMORY cues. Lazy-loaded inside `UtilitiesView`. | `POST /api/phrase/batch/start`, `GET /api/phrase/batch/status`, `POST /api/phrase/batch/cancel` |
| `components/DuplicateView.jsx` | Acoustic duplicate finder + merge UI — group list (similarity badge), per-track radio for master selection, "Auto" picks highest-bitrate, merge play-counts option. Lazy-loaded inside `UtilitiesView`. | `POST /api/duplicates/scan`, `GET /api/duplicates/results`, `POST /api/duplicates/merge` |
| `components/SettingsView.jsx` | Tabbed preferences panel **container** — owns merged `settings` state and active-tab pointer; loads on mount (`GET /api/settings`) and saves on demand (`POST /api/settings`). Each tab body lives in `components/settings/*`. Routes to: `settings`. | `GET /api/settings`, `POST /api/settings` |
| `components/WaveformEditor.jsx` | Standalone WaveSurfer.js editor used by `RankingView` (`simpleMode`). Slim orchestrator that composes the hooks + sub-components under `components/waveform/`. Exposes ref API: `stop()`, `setTime(t)`, `getCurrentTime()`, `playPause()`; fires `onPlayPause(bool)` on play/pause/finish. |

> Legacy reference: `components/LibraryView.jsx` and `components/ToolsView.jsx` still ship but are not lazy-mounted from `main.jsx` — they remain importable for reuse. `LibraryView` is a minimal Camelot-coloured `TrackTable` wrapper; `ToolsView` is the older batch-tools hub superseded by `UtilitiesView`.

---

## Shared UI Components (`components/*.jsx`)

Non-lazy components used by feature views.

| File | Purpose |
|------|---------|
| `components/ToastContext.jsx` | **Toast notification provider** — wraps app, exposes `useToast()` → `toast.success()`, `toast.error()`, `toast.info()`. Used alongside `react-hot-toast`. Never use `alert()`. |
| `components/ConfirmModal.jsx` | Promise-based replacement for `window.confirm()`. Renders `<ConfirmModalRoot />` once in `main.jsx`; call `confirmModal({ title, message, confirmLabel, danger })` from anywhere → resolves `true` on confirm, `false` on cancel/Escape/click-outside. |
| `components/PromptModal.jsx` | Promise-based replacement for `window.prompt()`. Renders `<PromptModalRoot />` once in `main.jsx`; call `promptModal({ title, message, defaultValue, placeholder })` → resolves to entered string or `null`. |
| `components/RenameModal.jsx` | Inline rename dialog modal. Props: `isOpen`, `onClose`, `onConfirm(newName)`, `initialValue`, `title`. |
| `components/BatchEditBar.jsx` | Batch editing toolbar — rating, colour label, mass save. Rendered by `MetadataView`/`PlaylistBrowser` when tracks are selected. |
| `components/ImportProgressBanner.jsx` | Sticky bottom-of-screen progress banner — aggregates `/api/import/tasks` + `/api/soundcloud/tasks` every 1.5s, shows aggregate % + current track + stage. Click → opens Downloads tab. Auto-hides when no active tasks. |
| `components/MatchInspectorModal.jsx` | SoundCloud sync match inspector — per-track match score, status icon (matched/unmatched/dead), confidence bar. Used inside `SoundCloudSyncView`. |
| `components/PhraseScopePicker.jsx` | Phrase-batch scope picker — Single / Playlist / Selection / Collection modes; self-contained multi-select checklist (`TrackTable` has none). Props: `onScopeChange({ scope, valid, count, mode })` (pass a stable handler). Emits a backend `scope` object: `{kind:'single', track_id}` / `{kind:'playlist', playlist_id}` / `{kind:'selection', track_ids[]}` / `{kind:'collection'}`. Used by `PhraseGeneratorView`. API: `GET /api/library/tracks`, `GET /api/playlists/tree`, `GET /api/playlist/{id}/tracks`. |
| `components/PhraseBatchProgress.jsx` | Phrase-batch live progress panel — determinate bar, done/total, %, ETA, written/skipped/failed counters, current track, cancel button (while running), expandable per-track skip/fail reason list. Props: `progress` (polled job dict), `running`, `onCancel`. Pure presentation. Used by `PhraseGeneratorView`. |
| `components/usePhraseBatch.js` | **Hook** — start + poll a phrase-cue batch (mirrors `DuplicateView`). `start(payload)` POSTs `/api/phrase/batch/start`, then polls `/status` every 1500 ms until terminal (`done`/`error`/`cancelled`); `cancel()` POSTs `/cancel`. Returns `{ progress, running, error, start, cancel, reset }`. API: `POST /api/phrase/batch/start`, `GET /api/phrase/batch/status`, `POST /api/phrase/batch/cancel`. |
| `components/Player.jsx` | Compact mini player at screen bottom — play/pause, volume (persisted in `localStorage`), amber mirror-waveform scrubber (click + drag seek), streaming via `GET /api/stream`. |
| `components/PlaylistBrowser.jsx` | Rekordbox playlist tree — expand/collapse, drag-reorder, smart-playlist editing, context menu, rename, "Move to" picker. Used inside `MetadataView`. |
| `components/SmartPlaylistEditor.jsx` | Rule-based smart playlist editor — field/operator/value rows, AND/OR combinator, live preview. Modal dialog. |
| `components/SoundCloudProgressModal.jsx` | OAuth + download progress overlay used by SC views — stage label, current track, percentage, cancel button. |
| `components/TrackTable.jsx` | **Reusable sortable track table** — Camelot wheel colours, BPM/key display, multi-select, configurable columns, drag-reorder. Used inside `LibraryView`, `MetadataView`, `RankingView`, `UtilitiesView`. |
| `components/LibraryView.jsx` | Minimal track-browser wrapper around `TrackTable` (legacy; superseded as the default `library` route by `MetadataView`). |
| `components/ToolsView.jsx` | Legacy batch-tools hub (duplicates, rename, batch comments). Functionality moved to `UtilitiesView`; kept for direct imports. |
| `components/shared/ContextMenu.jsx` | **Reusable right-click menu** — portal popup (viewport-clamped, Esc / click-outside / scroll closes) + `useContextMenu()` hook. Items: `{ id, label, icon, onSelect, disabled, danger, hint, separator }`. Every menu carries `data-context-menu="true"` so the global fallback yields to it. |
| `components/shared/GlobalContextMenu.jsx` | **App-wide right-click policy** — kills the WebView's native menu in the capture phase everywhere, then offers a real menu where the app has none: cut/copy/paste/select-all/clear on text fields (with selection restore, since a right-click collapses it), copy on a text selection, nothing otherwise. Mounted once next to `ConfirmModalRoot` in `main.jsx`. |
| `components/shared/WaveformMiniCanvas.jsx` | **Reusable canvas waveform renderer** — CDJ-style 3-band colours (Low=Red, Mid=Green, High=Blue, screen blend), mono fallback, optional playhead line + viewport-window highlight. DPR + ResizeObserver-aware. Used by `WaveformOverview`. |
| `components/shared/seededWaveform.js` | **Deterministic pseudo-waveform** — seed → song-shaped RMS+peak envelope → mirrored amber bar canvas (`drawSeededWave`). Used by `Player` where decoded audio peaks are unavailable. |

---

## Artist Hub Sub-Components (`components/artistHub/`)

Everything the Artists tab needs beyond the list itself. `MergeDialog` is also mounted by `MetadataView` (its GitMerge button hands the artist mode over here).

| File | Purpose |
|------|---------|
| `components/artistHub/artistHubApi.js` | **Transport for the merge + projection routes.** Request shapes in one place, plus `pollArtistJob` — apply / revert / projection-sync all return `{status:'ok', data:{job_id, total}}` and are polled on `GET /api/artists/jobs/{job_id}` until `done` (poll cadence + failure budget from `config/constants.js`; the POSTs disable the axios timeout because they run under the `master.db` write lock). `isRekordboxRunning(error)` separates the "Rekordbox holds the library" 409 from the "an artist-hub job is already running" 409, and `errorMessage()` turns either into a sentence. API: `GET /api/artists/merge/candidates\|runs`, `POST /api/artists/merge/preview\|apply\|revert/{run_id}`, `GET /api/artists/jobs/{job_id}`, `GET /api/artists/projection/status`, `POST /api/artists/projection/sync`. |
| `components/artistHub/mergeCopy.js` | **Pure copy builders for the merge dialog** (no React, no network, unit-tested). Builds the dry-run line, the three mandatory effect sentences (master.db rows · audio-file tags · USB folders), the compound-credit warning, the orphan warning, the `confirmModal` body and the post-run / post-revert summaries. Rule: never invent a figure the preview did not report — no `bytes_local_source` ⇒ the sentence says tracks, not a guessed size; `files_measured: false` and `counts_exact: false` are stated rather than smoothed over. |
| `components/artistHub/mergeCopy.test.js` | `node --test frontend/src/components/artistHub/mergeCopy.test.js` — 11 cases over the copy builders, incl. the "no bytes ⇒ say tracks" rule and the full confirm body. |
| `components/artistHub/MergeDialog.jsx` | **The merge screen** (modal, `z-[200]` so `confirmModal` sits above it). Two tabs: **Duplicates** — detected variant groups, expandable, radio canonical picker defaulting to the backend suggestion, dry-run line, the three effect rows, the USB folder chips (`Contents/<variant>` → `Contents/<canonical>`), unchecked opt-in "also remove the now-empty artist entries" with its collateral spelled out, and a `confirmModal` that repeats all of it before anything is written; the apply then runs as a job with a live progress row. **History** — the merge journal (`run_id`, timestamp, canonical ← absorbed spellings, status) with a per-run Revert (confirmed, job-polled, reports an incomplete revert as such). Props: `seedName` (jump to that artist's group), `onClose`, `onApplied`. |
| `components/artistHub/ProjectionPanel.jsx` | **Rekordbox `Artists` folder state + Sync now.** Shows folder name and whether it exists (adopted / missing / not created yet), projected playlists vs favourites, last-synced (relative), and a Rekordbox open/closed chip. After a run it prints the delta the backend returned (`+N playlists · N adopted/updated · +N/−N tracks · elapsed`, or "already up to date — nothing to write"), never a generic success. A 409 renders as a plain "close Rekordbox" sentence, a failed status read degrades to one muted line. Props: `refreshToken` (bumped by the hub on favourite/merge changes). |

---

## Settings Sub-Components (`components/settings/`)

| File | Purpose |
|------|---------|
| `components/settings/SettingsControls.jsx` | **Shared field primitives** — `Toggle`, `Section`, `Field`, `Select`, `KeyCapture` (shortcut capture button). Every other settings tab consumes these. |
| `components/settings/SettingsLibrary.jsx` | DB connection mode, watched folders, library filter; owns local watcher-status polling (1× heartbeat interval). |
| `components/settings/SettingsExport.jsx` | Default export folder, format/bitrate/sample-rate defaults, Rekordbox bridge target path. |
| `components/settings/SettingsUsb.jsx` | Per-stick USB profile CRUD (label, type, audio format). Loads profiles lazily. |
| `components/settings/SettingsAudio.jsx` | CPAL output device picker — enumerates `list_audio_devices` Tauri command (desktop only). |
| `components/settings/SettingsAnalysis.jsx` | Analysis quality preset (Fast librosa / Standard madmom / Thorough ensemble), ranking filter, insight thresholds. |
| `components/settings/SettingsAppearance.jsx` | Waveform band-colour customisation (blue / RGB / 3band / custom), locale picker. |
| `components/settings/SettingsShortcuts.jsx` | Configurable DAW keyboard shortcut bindings (14 actions) via `KeyCapture`. |
| `components/settings/SettingsNetwork.jsx` | HTTP proxy, SoundCloud sync target, backend restart. Hidden "expert" toggle (5× click on muted dot reveals aggressive-download switch). |

---

## USB Sub-Components (`components/usb/`)

| File | Purpose |
|------|---------|
| `components/usb/UsbControls.jsx` | **Shared helpers + compatibility tables** — `FS_COMPAT`, `FS_NOTES`, `CDJ_TARGETS`, `USB_TYPES`, plus `normalizeFs` / `worstCdjStatus` / `formatBytes` / `formatDate`, plus visual primitives (`StatusIcon`, `Toggle`, `PillBtn`, `PillTab`, `Row`, `SpaceBar`) and playlist helpers (`PlaylistTreeNode`, `UsbLibraryTree`, `getDescendantIds`). |
| `components/usb/UsbDeviceList.jsx` | Left-rail list of registered + connected USB drives — each card shows a disk-usage bar. Selection state owned by container. |
| `components/usb/UsbSyncPanel.jsx` | Main right-pane: header, compat matrix (PC + CDJ-3000/NXS2/NXS/older), Non-Rekordbox empty state, storage bar, sync source toggle, ecosystem picker, sync controls + progress, settings card, drive actions, danger zone (delete profile, reset, format wizard), stats footer. |
| `components/usb/UsbProfileEditor.jsx` | Playlist picker (checkbox tree from PC playlist tree) + USB-library viewer (newer `library_one` / legacy `library_legacy` formats). Owns its expanded-node + selected-playlist + search state. |
| `components/usb/UsbFormatWizard.jsx` | Destructive FAT32 / exFAT re-format modal — two-step backend protocol (`POST /api/usb/format/preview` → `POST /api/usb/format/confirm`). Confirm phrase + checkbox required. |
| `components/usb/MetadataSyncPanel.jsx` | Collapsible per-device metadata sync controls (smart vs. manual, PC ↔ USB main source, per-category toggles: play counts, ratings, tags, color labels, hot cues, memory cues, beat grids). UI-only for now. |
| `components/usb/PlayCountSync.jsx` | Collapsible play-count diff panel — auto-resolved summary + per-track strategy dropdown (`take_max`/`take_pc`/`take_usb`/`sum`), triple-confirm commit. |

---

## Editor (Non-Destructive) (`components/editor/`)

| File | Purpose |
|------|---------|
| `components/editor/NonDestructiveEditor.jsx` | Slim container — owns TimelineState + composes child components and hooks. |
| `components/editor/EditorToolbar.jsx` | Top + edit toolbars (h-12 header: track info, BPM/key/LUFS badges, save/load, time; h-10 edit row: transport, edit tools, snap, grid mode, zoom, undo/redo, render). Pure presentation. |
| `components/editor/TimelineCanvas.jsx` | Canvas renderer — waveform, beat grid, regions (`RegionBlock`), playhead with smooth RAF animation. Debounces resize at 150ms. |
| `components/editor/RegionBlock.jsx` | Individual region UI block — waveform thumbnail, envelope overlay, drag/resize/edit handle interactions. |
| `components/editor/EnvelopeOverlay.jsx` | Interactive envelope editor — draggable nodes for fade-in (left), fade-out (right), gain level (centre). |
| `components/editor/EditorBrowser.jsx` | File browser sidebar — searchable library list for loading audio source files. |
| `components/editor/Palette.jsx` | Drag-and-drop region clipboard (sidebar slots). Drag from timeline to store, drag back to clone. |
| `components/editor/useEditorPlayback.js` | Audio loading + Web Audio playback engine + render/export hook. Owns `audioContextRef`, `sourceBufferRef`, `playerRef`, `startTimeRef`, `pauseTimeRef`, plus `isLoading`/`isPlaying`/`isRendering`/`renderProgress`. Handles seamless seek and offline WAV render. |
| `components/editor/useEditorPersistence.js` | `.rbep` project save / list / load via `/api/projects/*`. Reuses playback refs to re-decode loaded projects into the existing `AudioContext`. |
| `components/editor/useEditorRegions.js` | Region / palette / marker / zoom / snap / grid handlers — thin wrappers around `TimelineState` + `AudioRegion` mutators. |
| `components/editor/useEditorKeyboard.js` | Global keydown shortcuts (m/l/f/o/s/c/1-8/Delete/q/g). Ignores input-focused targets. |
| `components/editor/index.js` | Barrel re-exports for non-destructive editor components. |

---

## DAW Editor (`components/daw/`)

Main 4-panel DJ Edit DAW. `DjEditDaw` is the root orchestrator.

| File | Purpose |
|------|---------|
| `components/daw/DjEditDaw.jsx` | **Root DAW orchestrator** — owns DAW state via `useReducer(dawReducer)`, drives playhead animation + dead-reckoning sync, wires transport/editing handlers (split, ripple-delete, play, stop, jump-to, export, auto-cue), delegates persistence to `useDawProject`, key events to `useDawKeyhandlers`, shortcut binding to `useDawShortcuts`, track loading to `useTrackLoader`. Renders `<DawLayout>`. |
| `components/daw/DawLayout.jsx` | Pure presentational slot-style layout shell — toolbar / overview / timeline (or empty state) / scrollbar / controlStrip / browser. Receives nodes as props. |
| `components/daw/DawToolbar.jsx` | Top toolbar — project name (inline edit), save/open/export buttons, split / ripple-delete, undo/redo, auto-cue, BPM display. Right-side track info capped to 35% width. |
| `components/daw/DawTimeline.jsx` | Thin wrapper around 3 timeline hooks below. Layered-canvas timeline (cached waveform bitmap + live grid/cues/loops/selection + 60fps playhead/phase-meter). Selects rendering path via `state.waveformStyle` ('3band' / 'liquid' / 'mono' / 'bass'). |
| `components/daw/DawControlStrip.jsx` | Unified control bar below the timeline: [Transport] | [Edit Tools] | [Hot Cues + Loop Controls]. Merges old DawTransport + Toolbar edit tools + PerformancePanel. |
| `components/daw/DawBrowser.jsx` | Left-panel browser — searchable library list + recent `.rbep` projects + palette tab. Collapsible. |
| `components/daw/DawScrollbar.jsx` | Custom horizontal scrollbar synchronised with timeline `scrollX`. Uses `programmaticScroll` ref to avoid the self-dispatch feedback loop. |
| `components/daw/WaveformOverview.jsx` | Full-track mini-map with draggable viewport window. Delegates drawing to `WaveformMiniCanvas`; click/drag dispatches `SET_SCROLL_X`. |
| `components/daw/ExportModal.jsx` | Project export modal — output folder picker (`tauri-plugin-dialog`), format selector (WAV / MP3 320 / FLAC), normalisation toggle. WAV rendered in-browser via `DawEngine.renderTimeline`; MP3/FLAC via `/api/audio/render`. Progress bar with success/error states. |
| `components/daw/useDawProject.js` | Project persistence hook — owns `fileInputRef` + `skipNextAutoLoad` ref. Exposes `handleSave` / `handleOpen` / `handleFileSelect` / `handleOpenProject` and the `buildProjectFromState` helper. |
| `components/daw/useDawShortcuts.js` | Keyboard-shortcut binding hook — owns `shortcutsRef` (loaded from `/api/settings` key `shortcuts`, merged onto defaults), `matches(e, combo)` helper that resolves `Ctrl+Shift+Z`-style strings, plus the window `keydown` / `keyup` listener wiring. |
| `components/daw/useDawKeyhandlers.js` | Pure key-event handlers map (action-name → handler) — cut/copy/paste/delete/undo/redo/zoom/scrub/jump-to-start-end/save/open. Also returns `onShiftDown`/`onShiftUp` (slip-mode) and `onHotcue` (1..8 jump). |
| `components/daw/useTrackLoader.js` | Effect hook that hydrates DAW state when `activeTrack` changes — decodes audio, builds tempo map, creates a single full-track region, generates peaks (prefers backend 3-band waveform via `/api/audio/3band`, falls back to client-side BiquadFilter LOD). Honours `skipNextAutoLoad`. |

### DAW Timeline (`components/daw/timeline/`)

| File | Purpose |
|------|---------|
| `components/daw/timeline/useTimelineLayout.js` | Layout / sizing hook — ResizeObserver subscription, DPR-aware canvas backing-store + CSS size, debounced resize handling, dynamic-vs-fixed canvas-height mode. Flips `needsWaveformRebuild` + `needsRedraw` on the shared draw-state ref. |
| `components/daw/timeline/useTimelineRender.js` | Rendering hook — state→ref sync, RAF loop (auto-follow scroll, LOD hysteresis, bitmap rebuild, draw), OffscreenCanvas waveform bitmap cache + invalidation key, all draw functions (grid, regions, cues, loops, playhead, ruler, phase meter), all band-specific waveform renderers. Exports `RULER_HEIGHT` / `PHASE_METER_HEIGHT`. |
| `components/daw/timeline/useTimelineEvents.js` | Event-handler hook — cue-flag hit-testing, mouse down/move/up (click-to-place-cue, drag-to-reposition, region selection, selection-range drag), wheel handler (scroll + ctrl/cmd-scroll zoom anchored at cursor), drag-state refs. Returns the `{ onMouseDown, onMouseMove, onMouseUp, onWheel }` map for the canvas. |

---

## Waveform Editor (`components/waveform/`)

Composed by `components/WaveformEditor.jsx` (the standalone editor used in `RankingView`).

| File | Purpose |
|------|---------|
| `components/waveform/WaveformCanvas.jsx` | Canvas-based beatgrid renderer + WaveSurfer mount points (main + overview + 3-band layers). Receives refs from orchestrator. Floating overlays slotted via `children`. |
| `components/waveform/WaveformControls.jsx` | Top toolbars — header, project select, hot-cue strip, transport, volume, viz toggle, grid shift, drop detection, metadata bar. Render-progress overlay. Pure presentational. |
| `components/waveform/WaveformOverlays.jsx` | Cue markers, beat-selection region, cut/insert/delete regions, drop marker, loop region (WaveSurfer Regions plugin side effects), plus floating cuts-summary panel. |
| `components/waveform/WaveformSimpleView.jsx` | Stripped-down view used by `RankingView` (`simpleMode=true`) — overview + main waveform + 3-band layers + mode-toggle. No toolbar. |
| `components/waveform/WaveformZoom.jsx` | Floating zoom controls overlay (Zoom +/− buttons, `px/s` indicator). |
| `components/waveform/WaveformErrorBoundary.jsx` | Error boundary preventing WaveSurfer / decode crashes from white-screening the app. Includes "Retry" button. |
| `components/waveform/ConfirmModal.jsx` | Themed in-editor replacement for `window.confirm()`. **Not** the same as `components/ConfirmModal.jsx` — this one is local to the WaveformEditor and takes a `{modal, setModal}` prop pair. |
| `components/waveform/useWaveSurfer.js` | Master WaveSurfer + Overview lifecycle hook — mount-once init (registers Regions + Timeline plugins, event listeners), per-track load + state reset on `fullTrack.path` / `blobUrl` change, playback sync, zoom sync. Reads cross-frame mutable state via refs owned by the orchestrator. |
| `components/waveform/useWaveformInteractions.js` | Imperative editing + hotkey wiring hook. Returns a handler bag (cuts, hot cues, loop, history, snap, zoom, save, etc.) + `react-hotkeys-hook` registrations. Exports `HOT_CUE_COLORS`, `ZOOM_MIN`/`MAX`/`STEP`. |
| `components/waveform/useMultibandLayers.js` | Slave WaveSurfer instances for LOW/MID/HIGH bands + RAF sync loop keeping their scroll & time aligned with the master. `'blue'` mode tears them down. |
| `components/waveform/useVisualPreview.js` | Debounced non-destructive preview rebuild — when `cuts` changes, splice the AudioBuffer and reload master WaveSurfer with the spliced version. Skips while `bufferReady=false`. Generation counter ignores stale results. |
| `components/waveform/useEditPersistence.js` | `localStorage` auto-save (500ms debounce) + restore for per-track edits (cuts + hot cues), keyed by `track.id`. Only restores into empty session state. |
| `components/waveform/computeBeats.js` | Builds the beat array for grid rendering + snap-to-grid. Respects per-segment BPM changes in `beatGrid`; falls back to even spacing when no grid exists. |
| `components/waveform/persistence.js` | `localStorage` helpers — `loadEditsForTrack` / `saveEditsForTrack` / `clearEditsForTrack` with versioning. |
| `components/waveform/previewBuffer.js` | Shared decode `AudioContext` + insert-slice cache (LRU, max 32). Exports `buildPreviewBuffer(originalBuffer, cuts, originalDuration, originalPath)` and `bufferToWave`. |

---

## Tauri IPC Commands (called via `invoke()`)

> Actual command names in `src-tauri/src/main.rs`:

| Command | Parameters | Returns | Defined in |
|---------|-----------|---------|-----------|
| `load_audio` | `{ path: string }` | `Result<AudioInfo, String>` | `src-tauri/src/audio/commands.rs` |
| `get_3band_waveform` | `{ path: string }` | `{ low: f32[], mid: f32[], high: f32[], peaks: f32[] }` | `src-tauri/src/audio/commands.rs` |
| `start_project_export` | `{ params: ExportParams }` | `void` (emits events) | `src-tauri/src/audio/commands.rs` |
| `login_to_soundcloud` | `{ mode?: 'gui' \| 'browser' }` | `Result<String, String>` (access token) | `src-tauri/src/main.rs` |
| `export_to_soundcloud` | `{ playlist_name: string, tracks: ExportTrack[], mode?: 'gui' \| 'browser' }` | `Result<String, String>` | `src-tauri/src/main.rs` |
| `list_audio_devices` | `{}` | `Result<string[], String>` | `src-tauri/src/main.rs` |
| `close_splashscreen` | `{}` | `void` | `src-tauri/src/main.rs` |

Tauri events — listen with `listen('event_name', handler)`:
- `export_progress` → `{ percent: number, message: string }` — emitted during audio export
- `sc-login-progress` → `{ stage: string, message: string }` — emitted during SC OAuth flow

---

## Component Requirements (MANDATORY for all new components)

```jsx
// Every component fetching data MUST have:
const [loading, setLoading] = useState(false);
const [error, setError] = useState(null);

if (loading) return <Spinner />;
if (error) return <ErrorMessage message={error} />;
```

Every new view must be added to the lazy-load tab router in `main.jsx`.

---

## Logging Pattern (use in every component)

Use the shared dev-only logger from `utils/log.js`:

```javascript
import { log } from '../utils/log';   // adjust depth to "../../utils/log" etc.

// Usage:
log.debug('Waveform cache miss', { trackId });
log.info('Component mounted', { trackCount: tracks.length });
log.warn('Retrying after 500', { attempt });
log.error('API call failed', { endpoint, status, error: err.message });
```

`log.debug` and `log.info` are silenced in production builds via Vite's `import.meta.env.DEV` guard, so verbose component traces stay out of the shipped bundle while still being available during `npm run dev`. `log.warn` and `log.error` always pass through — those signals matter in production too.

The old `const log = (level, msg, data) => console[level](...)` per-file boilerplate is deprecated; replace it on touch.
