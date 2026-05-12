# src-tauri/ INDEX — Rust/Tauri Desktop Wrapper

> Module and command map for the Rust backend. Update when adding commands or modules.
> Last updated: 2026-04-06

---

## Entry Points

| File | Purpose |
|------|---------|
| `src-tauri/src/main.rs` | App initialization, splashscreen lifecycle, top-level Tauri commands: `close_splashscreen`, `login_to_soundcloud`, `export_to_soundcloud`. Registers `AudioCommandState` with `.manage()` |
| `src-tauri/src/soundcloud_client.rs` | SoundCloud OAuth 2.1 + PKCE implementation. `Track` struct. Functions: `get_auth_url()`, `wait_for_callback()`, `exchange_code_for_token()` |

---

## Audio Module (`src-tauri/src/audio/`)

| File | Struct / Key Items | Key Responsibilities |
|------|-------------------|----------------------|
| `audio/mod.rs` | Module re-exports | Aggregates all audio submodules for `main.rs` |
| `audio/engine.rs` | `AudioEngine`, `AudioController` | Memory-mapped file loading (memmap2, zero-copy). Symphonia codec support: MP3, FLAC, WAV, ALAC, ISOMP4. Decoder abstraction over format readers |
| `audio/playback.rs` | `PlaybackEngine` | CPAL device-agnostic audio output stream. ringbuf lock-free producer/consumer sample queue. Stream init + error recovery (`StreamError::DeviceNotAvailable`). The `cpal::Stream` (`!Send` on Windows) is confined to a dedicated audio thread — built, played and dropped inside that thread — so `PlaybackEngine` is `Send + Sync` via the auto-derived bounds without any `unsafe impl`. Control crosses the boundary via `Arc<AtomicBool>` flags (`is_playing`, `shutdown`); init success/failure comes back through a one-shot `mpsc` channel. |
| `audio/commands.rs` | `AudioCommandState`, Tauri IPC handlers | `load_audio`, `get_3band_waveform`, `start_project_export` — all return `Result<T, String>`. Owns `Arc<Mutex<AudioEngine>>` and `Arc<Mutex<PlaybackEngine>>` |
| `audio/analysis.rs` | `compute_waveform()`, `estimate_bpm()`, `detect_key()`, `hz_to_bin()` | RustFFT-based waveform computation. 3-band frequency split with **Hz-based band boundaries** (20-250-4000-20000 Hz, sample-rate-correct via `hz_to_bin()` — previously hardcoded bin indices broke at non-44.1k sample rates). BPM tempo detection. **`detect_key()` implements Krumhansl-Schmuckler pitch-class-profile correlation** over 4096-sample Hann-windowed FFT frames (50% hop, 65 Hz–5 kHz range): builds a 12-bin chromagram, L2-normalises, Pearson-correlates against all 24 rotations of the Krumhansl-Kessler major/minor profiles, returns the winning tonic in Camelot notation (e.g. `"8B"` = C major, `"8A"` = A minor; minor keys share the wheel number of their relative major). Returns `""` on empty input or silence. Python (`app/analysis_engine.py` / Essentia) remains the higher-accuracy reference path; the Rust implementation lets the native pipeline stand alone without round-tripping to the backend. |
| `audio/export.rs` | `render_project()`, `AudioRegion`, `ProjectState`, `Fade` | Offline audio synthesis / project render to WAV (hound) or MP3 |
| `audio/metadata.rs` | tag read/write functions | ID3 (MP3), FLAC, ALAC, AIFF metadata via lofty crate |

---

## Tauri IPC Commands

All commands registered via `tauri::Builder::default().invoke_handler(tauri::generate_handler![...])`.

### App Commands (`src-tauri/src/main.rs`)

| Command | Parameters | Returns | Description |
|---------|-----------|---------|-------------|
| `close_splashscreen` | `window: tauri::Window` | `void` | Closes splashscreen window, shows main window |
| `login_to_soundcloud` | `app: tauri::AppHandle` | `Result<String, String>` | Full PKCE OAuth flow: get auth URL → open browser → wait for callback → exchange code → return access token string |
| `export_to_soundcloud` | `app: tauri::AppHandle, playlist_name: String, tracks: Vec<ExportTrack>` | `Result<String, String>` | Export a playlist to SoundCloud (requires prior auth) |

`ExportTrack` struct: `{ artist: String, title: String, duration_ms: u64 }`

### Audio Commands (`src-tauri/src/audio/commands.rs`)

| Command | Parameters | Returns | Description |
|---------|-----------|---------|-------------|
| `load_audio` | `path: String, state: State<AudioCommandState>, app: AppHandle` | `Result<AudioInfo, String>` | Load audio file via memory map, validate path + extension, initialize playback engine |
| `get_3band_waveform` | `path: String, state: State<AudioCommandState>` | `Result<WaveformData, String>` | Compute FFT → 3-band frequency arrays for waveform display |
| `start_project_export` | `params: ExportParams, state: State<AudioCommandState>, app: AppHandle` | `Result<(), String>` | Start async export; emits `export_progress` events as it runs |
| `list_audio_devices` | _(none)_ | `Result<Vec<String>, String>` | Enumerate CPAL output devices; first entry is always `"System Default"`. Uses `spawn_blocking` to avoid blocking async runtime |

`WaveformData` shape:
```rust
pub struct WaveformData {
    pub low: Vec<f32>,    // 20–300 Hz (bass / kick)
    pub mid: Vec<f32>,    // 300 Hz–4 kHz (mids / snare)
    pub high: Vec<f32>,   // 4 kHz–20 kHz (hi-hats / presence)
    pub peaks: Vec<f32>,  // Overall peak envelope
}
```

`AudioCommandState` (shared state registered via `.manage()`):
```rust
pub struct AudioCommandState {
    pub engine: Arc<Mutex<AudioEngine>>,
    pub playback: Arc<Mutex<PlaybackEngine>>,
}
```

---

## Tauri Events

Events emitted by Rust → frontend listens with `listen('event_name', handler)`.

| Event | Payload | Emitted From | When |
|-------|---------|-------------|------|
| `export_progress` | `{ percent: u8, message: String }` | `audio/commands.rs` | During audio export (`start_project_export`) |
| `sc-login-progress` | `{ stage: String, message: String }` | `main.rs` | During `login_to_soundcloud` OAuth stages |

**Note**: The frontend event name for SC OAuth is `sc-login-progress` (with hyphens), not `oauth_progress`.

---

## SoundCloud OAuth Flow (`src-tauri/src/soundcloud_client.rs`)

Implements OAuth 2.1 + PKCE:

1. `get_auth_url()` — generate `code_verifier` (random bytes) + `code_challenge` (SHA256 → base64url). Returns `(auth_url, code_verifier)`
2. `open::that(&auth_url)` — opens system browser for user login
3. `wait_for_callback()` — spawns one-shot local HTTP server on a random port. Blocks until SC redirects back with `?code=...`. Returns the authorization code
4. `exchange_code_for_token(&code, &code_verifier)` — POST to SC token endpoint with code + verifier → returns access token string
5. Token is returned to frontend as plain string; frontend sends it to `POST /api/soundcloud/auth-token` for the Python backend to store

**Never log the token** — only log `token_received: true/false`.

---

## Key Rust Dependencies (`src-tauri/Cargo.toml`)

| Crate | Version | Purpose |
|-------|---------|---------|
| `tauri` | 2.2 | Desktop framework, window management, Tauri IPC |
| `tauri-plugin-shell` | — | `open::that()` — open URLs in system browser |
| `cpal` | — | Cross-platform audio output (device abstraction) |
| `symphonia` | — | Audio decoding: MP3, FLAC, WAV, ALAC, ISOMP4 |
| `rustfft` | — | FFT computation for waveform analysis |
| `rubato` | — | Sample rate conversion (resampling) |
| `ringbuf` | — | Lock-free ring buffer for audio sample queue |
| `crossbeam-channel` | — | Multi-producer/consumer channels for audio threads |
| `memmap2` | — | Memory-mapped file reading (zero-copy) |
| `hound` | — | WAV file read/write |
| `lofty` | — | Audio metadata: ID3, FLAC, ALAC, AIFF tags |
| `sha2` | — | SHA256 for PKCE code challenge |
| `base64` | — | Base64url encoding for PKCE |
| `rand` | — | Cryptographic random for PKCE code verifier |
| `tokio` | — | Async runtime |
| `serde` / `serde_json` | — | Serialization for IPC types and payloads |
| `reqwest` | — | HTTP client for OAuth token exchange |
| `open` | — | Open URLs in system browser |
| `log` | 0.4 | Logging facade. `log::info!`, `log::warn!`, `log::error!`. Backend is `env_logger` (initialised at the top of `fn main()` with `LevelFilter::Info`, RUST_LOG-overridable). The crate has zero `println!` / `eprintln!` outside `#[cfg(test)]` except one documented fatal-exit path in `main.rs`. |
| `env_logger` | 0.11 | Logger backend for the `log` facade. Writes to stderr with timestamps + module path. |

---

## Capabilities (`src-tauri/capabilities/main.json`)

Minimum required permissions:
- `core:default` — standard window/event APIs
- `shell:allow-open` — open URLs in system browser (required for OAuth)

Add new permissions only when required. Document the reason in a comment in the JSON file.

---

## Coding Rules for This Layer

### Never Panic in Production
```rust
// ALL Tauri commands must return Result<T, String>
#[tauri::command]
pub async fn my_command(state: tauri::State<'_, AudioCommandState>) -> Result<MyType, String> {
    let engine = state.engine.lock()
        .map_err(|e| format!("Lock poisoned: {e}"))?;  // handle poisoning
    engine.do_thing().map_err(|e| e.to_string())        // map errors to String
}
// No .unwrap(), no .expect() without a documented invariant reason
```

### Audio Callback Thread
- Never block the audio callback thread — use `try_push`/`try_pop` on ringbuf
- Handle `StreamError::DeviceNotAvailable` by emitting a frontend event, not panicking

### FFT Band Frequencies
```rust
// Standard 3-band split used throughout the codebase (boundaries are
// constants in `src-tauri/src/audio/analysis.rs`):
// Low:  20 Hz   – 250 Hz  (bass / kick)
// Mid:  250 Hz  – 4 kHz   (mids / vocals / snare)
// High: 4 kHz   – 20 kHz  (hi-hats / cymbals / presence / air)
//
// Always convert Hz → FFT bin via `hz_to_bin(hz, frame_size, sample_rate)`
// — never hardcode bin indices; they shift with the source's sample rate.
```

### Clippy
```bash
cd src-tauri && cargo clippy -- -D warnings
# Must be clean — all warnings treated as errors
# Never use #[allow(...)] without a documented reason
```

---

## Build Commands

```bash
# Dev mode (hot-reload frontend + Rust rebuild on change)
npm run tauri dev

# Production build
npm run tauri build

# Clippy lint (must pass before commit)
cd src-tauri && cargo clippy -- -D warnings

# Tests
cd src-tauri && cargo test
```


---

## Audio Fingerprinting (`src-tauri/src/audio/fingerprint.rs`) — NEW 2026-05-04

Chromaprint-style acoustic fingerprinting for duplicate detection.

### Algorithm
1. Decode audio via Symphonia → mono f32 samples
2. Resample to 11025 Hz (nearest-neighbour)
3. Sliding 128 ms frames (50% overlap) → 32-band Mel spectrogram via Goertzel
4. Temporal gradient of band energy differences → 1 bit per band per frame → u32 word
5. Hamming distance comparison → similarity 0.0–1.0

### Public Functions
| Function | Signature | Notes |
|----------|-----------|-------|
| `hamming_similarity` | `(a: &[u32], b: &[u32]) -> Option<f32>` | Returns None if < 4 words |

### Tauri Commands
| Command | Signature | Events |
|---------|-----------|--------|
| `fingerprint_track` | `(path: String) -> Result<Vec<u32>, String>` | none |
| `fingerprint_batch` | `(paths: Vec<String>, window: Window) -> Result<HashMap<String, Vec<u32>>, String>` | emits `fingerprint_progress: {done, total, current_path}` |

Registered in `src-tauri/src/main.rs` invoke handler.
