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
export const AUDIO_IMPORT_TIMEOUT_MS = 0;
