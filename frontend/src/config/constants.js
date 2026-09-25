// Frontend-wide constants. Centralised so a magic number doesn't drift
// between the place that sets it and the place that depends on it.
//
// All durations are milliseconds unless the name says otherwise.

// Heartbeat ping cadence — every 5 s the frontend POSTs /api/system/heartbeat
// so the backend knows the UI is alive and so we can pick up a freshly-issued
// session token. Used by both `main.jsx` (boot loop) and the folder-watcher
// status refresh in `SettingsView.jsx`.
export const HEARTBEAT_INTERVAL_MS = 5000;

// Polling cadence for the library load-status check during boot. Faster than
// the heartbeat because we want the splash to clear the moment the DB lands.
export const LIBRARY_STATUS_INTERVAL_MS = 1000;

// Axios timeout for server-side audio render (/api/audio/render → FFmpeg).
// Large stems / MP3 encodes take real time; 3 minutes is the upper bound
// before we declare the render hung.
export const RENDER_API_TIMEOUT_MS = 180000;

// Delay before we revoke a generated blob: URL after triggering a download.
// Browsers occasionally fetch the same URL twice (preview + download), so
// holding it for a few seconds avoids a "Network error" on the second hit.
export const BLOB_URL_REVOKE_DELAY_MS = 5000;

// Duration for long-form error toasts that the user needs time to read
// (full failure paths in DAW / export). The react-hot-toast default is
// 4 s — bumped to 5 s here so a multi-line message has reading room.
export const TOAST_DURATION_LONG_MS = 5000;

// Axios timeout for the synchronous audio-import endpoint
// (/api/audio/import → full analysis pipeline: copy + decode + BPM +
// key + ANLZ write). Large WAV files (>30 MB) routinely take 30–60 s.
// `0` disables the timeout completely — we trust the backend to either
// finish or return an explicit error.
//
// Kept for backwards-compat: as of the async-import refactor the endpoint
// returns 202-style {task_id} immediately and the frontend polls
// /api/import/tasks, so the timeout is no longer load-bearing.
export const AUDIO_IMPORT_TIMEOUT_MS = 0;

// Poll cadence for /api/import/tasks while one or more uploaded files are
// still being analysed in the background. 1 s feels live without spamming
// the backend; the import_tracker snapshot is cheap (in-memory dict copy).
export const IMPORT_TASK_POLL_INTERVAL_MS = 1000;

// --- WaveformEditor extension feature flags ---
// Gate each panel of the cue/loop/beatgrid/metadata editor while it is
// being rolled out slice by slice. All default false in production;
// flipped on per-slice during beta. See
// docs/research/implement/inprogress_waveform-editor-extensions.md.
export const FEATURE_CUE_PANEL = false;
export const FEATURE_LOOP_PANEL = false;
export const FEATURE_BEATGRID_PANEL = false;
export const FEATURE_METADATA_PANEL = false;

// 8 CDJ memory-cue colors (Pioneer fixed palette). The `id` is the
// CDJ-internal palette index; the `hex` is an approximation for UI
// rendering. CDJs render the same palette index in hardware regardless
// of the RGB we ship, but RGB is also stored in ANLZ PCP2 for off-CDJ
// players that respect the explicit value.
export const CDJ_MEMORY_COLORS = [
    { id: 1, name: 'Pink',   hex: '#FF7BAA' },
    { id: 2, name: 'Red',    hex: '#FF3F3F' },
    { id: 3, name: 'Orange', hex: '#FF9F45' },
    { id: 4, name: 'Yellow', hex: '#FFD93F' },
    { id: 5, name: 'Green',  hex: '#4FCB6B' },
    { id: 6, name: 'Aqua',   hex: '#3FE0D6' },
    { id: 7, name: 'Blue',   hex: '#4FA6FF' },
    { id: 8, name: 'Purple', hex: '#A874E3' },
];

// Waveform style presets. Each preset bundles a layering mode
// (`3band` stacked or `rgb` additive-blend) with a 3-band colour set
// plus the down-beat colour, so the user can switch the visual
// language of the editor with one click. `rekordbox` is the default.
//
// To add a new preset (e.g. Serato), copy one of the existing entries,
// rename the key, and pick the four colour values. No further plumbing
// needed — `useMultibandLayers` and `WaveformCanvas` consume the map
// directly.
export const WAVEFORM_STYLE_PRESETS = {
    rekordbox: {
        label: 'Rekordbox',
        mode: '3band',
        threeBand: {
            low:  'rgba(59, 130, 246, 1.0)',   // blue
            mid:  'rgba(250, 204, 21, 1.0)',   // yellow
            high: 'rgba(34, 211, 238, 1.0)',   // cyan
        },
        downbeat: 'rgba(255, 165, 0, 0.85)',
    },
    mixxx: {
        label: 'Mixxx',
        mode: '3band',
        threeBand: {
            low:  'rgba(34, 197, 94, 1.0)',    // green
            mid:  'rgba(168, 85, 247, 1.0)',   // purple
            high: 'rgba(244, 114, 182, 1.0)',  // pink
        },
        downbeat: 'rgba(255, 220, 30, 0.85)',
    },
    traktor: {
        label: 'Traktor',
        mode: '3band',
        threeBand: {
            low:  'rgba(245, 158, 11, 1.0)',   // amber
            mid:  'rgba(229, 231, 235, 0.9)',  // soft white
            high: 'rgba(56, 189, 248, 1.0)',   // sky
        },
        downbeat: 'rgba(0, 200, 255, 0.85)',
    },
    rgbAdditive: {
        label: 'RGB Mix',
        mode: 'rgb',
        threeBand: {
            low:  'rgba(220, 38, 38, 1.0)',
            mid:  'rgba(34, 197, 94, 1.0)',
            high: 'rgba(37, 99, 235, 1.0)',
        },
        downbeat: 'rgba(255, 165, 0, 0.85)',
    },
};

export const DEFAULT_WAVEFORM_STYLE = 'rekordbox';

// 16 Rekordbox hot-cue surface colors — the subset of the 64-color
// internal palette that Rekordbox UI exposes for hot cues. Approximate
// hex values; exact CDJ rendering uses the palette `id` lookup.
export const HOT_CUE_SURFACE_COLORS = [
    { id: 1,  hex: '#16C172' },
    { id: 2,  hex: '#22B6E0' },
    { id: 3,  hex: '#4A9EFF' },
    { id: 4,  hex: '#9B6BFF' },
    { id: 5,  hex: '#E456D9' },
    { id: 6,  hex: '#FF4F8A' },
    { id: 7,  hex: '#FF7155' },
    { id: 8,  hex: '#FFA63E' },
    { id: 9,  hex: '#FFE03E' },
    { id: 10, hex: '#C7E03E' },
    { id: 11, hex: '#7CE03E' },
    { id: 12, hex: '#3EE07C' },
    { id: 13, hex: '#3EE0C7' },
    { id: 14, hex: '#789EA6' },
    { id: 15, hex: '#C5C9CC' },
    { id: 16, hex: '#888B8C' },
];
