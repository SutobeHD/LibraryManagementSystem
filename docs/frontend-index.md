# frontend/src INDEX

> Component and module map for the React frontend. Update this when adding/removing/renaming files.
> Last updated: 2026-04-06

---

## Entry Point

| File | Purpose |
|------|---------|
| `frontend/src/main.jsx` | App root — lazy-loaded tab views (Suspense), session token init on startup, global error boundary, tab-based router |

---

## API Layer

| File | Purpose |
|------|---------|
| `frontend/src/api/api.js` | **Central Axios instance — always import from here, never use raw `fetch()`.** Configured with: 10s timeout, session token header injection, 401 silent refresh with request queue (prevents parallel re-auth), 429 exponential backoff, HttpOnly cookie support, automatic Tauri context detection |

---

## Audio State (DAW Logic)

All DAW state is managed in this directory. Do NOT duplicate in component-local state.

| File | Purpose | Key Exports |
|------|---------|-------------|
| `frontend/src/audio/DawState.js` | **Central immutable DAW state reducer** | `dawReducer(state, action)` — handles regions, cues, loops, transport. `cuePointsToState()` — converts raw cue data. `snapToGrid()` — beat-snapping helper. Full undo/redo via full-state snapshots |
| `frontend/src/audio/DawEngine.js` | Web Audio API playback engine | `DawEngine` class — manages `AudioContext` lifecycle, multi-source scheduling, region-based playback (play, pause, stop, seek) |
| `frontend/src/audio/TimelineState.js` | Timeline position + selection tracking | `TimelineState` — regions, markers, beat grid, playback position, selection range, zoom helpers |
| `frontend/src/audio/RbepSerializer.js` | `.rbep` project file parser/serializer | `RbepSerializer` — bidirectional XML parse/serialize, beat↔seconds conversion using tempo maps, `POSITION_MARK` cue handling |
| `frontend/src/audio/AudioRegion.js` | Non-destructive region data model | `AudioRegion` class — references source file portion with metadata: gain, fades, start/end offset |

---

## Utilities

| File | Purpose |
|------|---------|
| `frontend/src/utils/AudioBandAnalyzer.js` | Splits a waveform array into low/mid/high frequency bands for 3-band visualization |

---

## Feature Views — Lazy-Loaded Tabs (`frontend/src/components/`)

> **Important**: All component files live in `frontend/src/components/`, not in `frontend/src/` directly.

| File | Purpose | Key API calls |
|------|---------|--------------|
| `components/LibraryView.jsx` | Main track browser with search/filter controls | `GET /api/library/tracks`, `GET /api/artists`, `GET /api/genres` |
| `components/PlaylistBrowser.jsx` | Rekordbox playlist tree navigation (expand/collapse) | `GET /api/playlists/tree` |
| `components/MetadataView.jsx` | Track metadata editor: title, artist, album, genre, comments | `POST /api/track/{tid}`, `PATCH /api/tracks/batch` |
| `components/TrackTable.jsx` | **Reusable** sortable track table — Camelot wheel colors, BPM/key display, multi-select. Used inside LibraryView and playlist views | (data passed as prop) |
| `components/Player.jsx` | Compact audio player: play/pause, volume, seek progress bar, streaming support | `GET /api/stream?path=...` |
| `components/SoundCloudView.jsx` | SC track search, preview, SC account display | `GET /api/soundcloud/me`, `GET /api/soundcloud/playlists` |
| `components/SoundCloudSyncView.jsx` | SC sync: match SC tracks to local library, trigger download. Shows inspector panel with match confidence | `POST /api/soundcloud/preview-matches`, `POST /api/soundcloud/sync`, `POST /api/soundcloud/download` |
| `components/SoundCloudProgressModal.jsx` | Download progress overlay: per-track status, ETA, cancel | `GET /api/soundcloud/task/{task_id}` |
| `components/UsbView.jsx` | USB device manager: detect drives, manage sync profiles, run sync, view diff | `GET /api/usb/devices`, `GET /api/usb/diff/{id}`, `POST /api/usb/sync` |
| `components/BackupManager.jsx` | Library backup/restore: snapshot timeline, create/restore, view diffs | `GET /api/library/backups`, `POST /api/library/backup`, `POST /api/library/restore` |
| `components/XmlCleanView.jsx` | Rekordbox XML cleaning: remove tags, fix encoding | `POST /api/xml/clean` |
| `components/InsightsView.jsx` | Library analytics: low quality tracks, missing artwork, lost files, bitrate stats | `GET /api/insights/low_quality`, `GET /api/insights/no_artwork`, `GET /api/insights/lost` |
| `components/RankingView.jsx` | Track ranking by quality metrics (bitrate, artwork, analysis status) | `GET /api/library/tracks` |
| `components/ImportView.jsx` | Import wizard: add tracks from filesystem or URL | `POST /api/audio/import` |
| `components/SettingsView.jsx` | **8-tab preferences panel**: Library (watched folders + scan), Backup (auto-interval), Export (bitrate/sample-rate defaults), Audio (CPAL output device via `list_audio_devices` Tauri cmd), Analysis (quality preset), Appearance (waveform band colors + locale), Shortcuts (14 configurable hotkeys via `KeyCapture` component), Network (HTTP proxy). Inner helper components: `Toggle`, `Section`, `Field`, `KeyCapture` | `GET /api/settings`, `POST /api/settings`, `POST /api/library/scan-folder`, `invoke('list_audio_devices')` |
| `components/ToolsView.jsx` | Batch tools: clean titles, find duplicates, batch comments, rename | `GET /api/tools/duplicates`, `POST /api/tools/batch-comment`, `POST /api/library/clean-titles` |
| `components/DesignView.jsx` | UI theme/palette preview and customization |  |
| `components/WaveformEditor.jsx` | Full waveform editor (WaveSurfer.js). Used in RankingView (`simpleMode`) and standalone. Exposes ref API: `stop()`, `setTime(t)`, `getCurrentTime()`, `playPause()`. Fires `onPlayPause(bool)` on play/pause/finish events | — |

---

## Shared UI Components (`frontend/src/components/`)

| File | Purpose | Usage |
|------|---------|-------|
| `components/ToastContext.jsx` | **Toast notification provider** — wrap app with this, then `useToast()` → `toast.success()`, `toast.error()`, `toast.info()`. Never use `alert()` | Import `useToast` in any component needing notifications |
| `components/BatchEditBar.jsx` | Batch editing toolbar: operates on a set of selected track IDs | Rendered by LibraryView when tracks are selected |
| `components/RenameModal.jsx` | Rename dialog modal | Props: `isOpen: bool`, `onConfirm(newName)`, `onCancel()`, `currentName: string` |
| `components/shared/WaveformMiniCanvas.jsx` | **Reusable canvas waveform renderer** — CDJ-style 3-band colors (Low=Red, Mid=Green, High=Blue via screen blend), falls back to mono. Props: `peaks`, `bandPeaks`, `totalDuration`, `playhead`, `viewportStart/End`, `height`. DPR-aware, ResizeObserver-reactive. Used by WaveformOverview | Any component needing compact waveform display |

---

## DAW Editor Views (`frontend/src/components/daw/`)

Main 4-panel DAW editor. `DjEditDaw` is the root; all others are children.

| File | Purpose | Key Props / State |
|------|---------|------------------|
| `daw/DjEditDaw.jsx` | **Root DAW container** — orchestrates all 4 panels, owns top-level DAW state via `dawReducer`. Configurable hotkeys via `shortcutsRef` (loads `settings.shortcuts` from API on mount); `matches(e, combo)` helper resolves `'Ctrl+Shift+Z'`-style strings. Timeline area wraps `DawTimeline` in `flex-1 relative min-h-0` so the canvas can fill available vertical space (no longer hardcoded to 300 px) | Loads `.rbep` project; distributes state to children |
| `daw/DawToolbar.jsx` | Toolbar: save/open/export/edit-mode toggle buttons. Right-side track info capped to `maxWidth: '35%'` with `title=` tooltip so the artist+title row stays readable without crowding the tool buttons on narrow windows | Callbacks: `onSave`, `onOpen`, `onExport`, `onModeChange` |
| `daw/DawTimeline.jsx` | Waveform canvas + interactive cue/beatgrid editing (click to place cues, drag to reposition). **Dynamic height**: when `canvasHeight` prop is omitted/null the canvas fills its container via ResizeObserver (`Math.max(minCanvasHeight, rect.height)`); pass a number for fixed-pixel mode. **Rendering paths** (selected by `state.waveformStyle`): `'3band'` (default) → `drawMixxxFilteredWaveform()` Rekordbox-style 3-band: envelope height = `max(low,mid,high) * maxAmp` (single continuous silhouette), inner colour slices = each band's share of the total (`band/sum * envelope`). 6 smooth Path2D polygons (3 top + 3 bottom, asymmetric min/max envelope). Colours: orange-red LOW (255,80,40), emerald MID (70,230,100), sky-blue HIGH (60,180,255). Three smoothing layers: 1-2 px sampling stride, 1-2-1 horizontal kernel, quadratic-bezier mid-point Path2D curves. γ=0.9. `'liquid'` → stacked Path2D bezier silhouettes (legacy); `'mono'` → silhouette of mono fallback; `'bass'` → silhouette of LOW band only. **Critical**: peak-index calculation uses `sourceDuration` (audio buffer length), NOT `totalDuration` (edit timeline) — required for .rbep projects where regions rearrange the source | Props: `state`, `dispatch`, `canvasHeight?`, `minCanvasHeight?`, `onRegionClick`, `onContextMenu` |
| `daw/DawBrowser.jsx` | Left-panel track library sidebar for loading tracks into DAW | Calls `GET /api/library/tracks`; emits selected track to parent |
| `daw/DawControlStrip.jsx` | Playback transport, BPM display, snap-to-grid toggle, key display | Props: `bpm`, `key`, `snapEnabled`, playback state |
| `daw/DawScrollbar.jsx` | Custom horizontal scrollbar for timeline navigation | Props: `scrollPos`, `viewportWidth`, `totalWidth`, `onChange` |
| `daw/WaveformOverview.jsx` | Mini-map waveform — delegates canvas drawing to `WaveformMiniCanvas`. Click/drag dispatches `SET_SCROLL_X` + `SET_PLAYHEAD` | Props: `state`, `dispatch` |
| `daw/ExportModal.jsx` | Export dialog: region range, format, fade settings | Props: `isOpen`, `onExport(params)`, `onCancel` |

---

## Non-Destructive Editor (`frontend/src/components/editor/`)

| File | Purpose |
|------|---------|
| `editor/NonDestructiveEditor.jsx` | Main editor container — regions, cues, loops, envelope editing. Uses `DawState.js` reducer |
| `editor/TimelineCanvas.jsx` | Canvas renderer for regions, beat grid, markers, playhead. Uses `requestAnimationFrame` for smooth animation. Debounces resize at 150ms |
| `editor/RegionBlock.jsx` | Individual region UI block with drag/resize/edit handle interactions |
| `editor/EnvelopeOverlay.jsx` | Volume envelope editor overlay — draw and edit fade curves on canvas |
| `editor/EditorBrowser.jsx` | File browser sidebar for loading audio source files |
| `editor/Palette.jsx` | Right-side palette: clip library and editing tools |
| `editor/index.js` | Module re-exports for all editor components |

---

## Frontend Config Files

| File | Purpose |
|------|---------|
| `frontend/package.json` | Deps: React 18, Vite 7.x, Tailwind CSS, WaveSurfer.js, `@tauri-apps/api` v2, axios, Lucide icons |
| `frontend/vite.config.js` | Dev server port 5173; `/api` proxy → `localhost:8000`; Tauri integration |
| `frontend/tailwind.config.js` | Design system: glassmorphism, custom slate tones |
| `frontend/postcss.config.js` | Tailwind + Autoprefixer |

---

## Tauri IPC Commands (called via `invoke()`)

> **Correction vs. old docs**: The actual command names in `src-tauri/src/main.rs` are:

| Command | Parameters | Returns | Defined in |
|---------|-----------|---------|-----------|
| `load_audio` | `{ path: string }` | `Result<AudioInfo, String>` | `src-tauri/src/audio/commands.rs` |
| `get_3band_waveform` | `{ path: string }` | `{ low: f32[], mid: f32[], high: f32[], peaks: f32[] }` | `src-tauri/src/audio/commands.rs` |
| `start_project_export` | `{ params: ExportParams }` | `void` (emits events) | `src-tauri/src/audio/commands.rs` |
| `login_to_soundcloud` | `{}` | `Result<String, String>` (access token) | `src-tauri/src/main.rs` |
| `export_to_soundcloud` | `{ playlist_name: string, tracks: ExportTrack[] }` | `Result<String, String>` | `src-tauri/src/main.rs` |
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

```javascript
// At module level — replace ComponentName
const log = (level, msg, data) =>
  console[level](`[ComponentName] ${msg}`, data !== undefined ? data : '');

// Usage:
log('info', 'Component mounted', { trackCount: tracks.length });
log('warn', 'Waveform cache miss', { trackId });
log('error', 'API call failed', { endpoint, status, error: err.message });
```


---

## New Views (2026-05-04)

### `PhraseGeneratorView.jsx`
Route: `phrase` tab in Editor group.

| Element | Description |
|---------|-------------|
| Track selector | Searchable inline picker (loads `/api/library/tracks`) |
| Phrase length | 8/16/32 bars radio cards |
| Generate button | POST `/api/phrase/generate` → preview list |
| CueRow | Shows position_ms, label, type (amber=phrase / grey=bar) |
| Commit button | POST `/api/phrase/commit` → success state |

State: `selectedTrack`, `phraseLength`, `cues`, `generating`, `committing`, `committed`, `genError`, `genWarning`.

### `DuplicateView.jsx`
Route: `duplicates` tab in Editor group.

| Element | Description |
|---------|-------------|
| Scan Library | POST `/api/duplicates/scan` → poll `job_id` via GET `/api/duplicates/results` |
| Group list (left) | Similarity badge + rep track title |
| GroupDetail (right) | Horizontal `TrackCard` cards per track |
| TrackCard | format, bitrate, size_mb, play_count; radio button = master |
| Auto button | Selects highest-bitrate track as master |
| Merge button | POST `/api/duplicates/merge` |

State: `scanning`, `scanProgress`, `groups`, `selectedGroupIdx`, `scanError`. Poll via `setInterval` ref.

### `UsbView.jsx` (modified)
Added `PlayCountSync` collapsible section rendered for connected rekordbox devices.

| Element | Description |
|---------|-------------|
| Analyse Counts | GET `/api/usb/playcount/diff` |
| Conflict table | Per-track strategy dropdown (take_max/take_pc/take_usb/sum) |
| Set All to MAX | Sets all strategies to take_max |
| Write Sync | Triple-confirm → POST `/api/usb/playcount/resolve` |
