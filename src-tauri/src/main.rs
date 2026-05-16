// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
mod audio;
mod soundcloud_client;

use audio::commands::{
    get_3band_waveform, list_audio_devices, load_audio, start_project_export, AudioCommandState,
};
use audio::engine::AudioController;
use audio::fingerprint::{fingerprint_batch, fingerprint_track};
use serde::Deserialize;
use soundcloud_client::Track;
use std::sync::{Arc, Mutex};
use tauri::{Emitter, Manager, State};
use tauri_plugin_shell::process::CommandEvent;
use tauri_plugin_shell::ShellExt;

/// Shared boot-time session token captured from the Python sidecar's stdout.
///
/// The sidecar prints ``LMS_TOKEN=<value>`` as its very first line at boot
/// (see ``app/auth.py``). Both the dev-mode (``spawn_child``) and prod-mode
/// (``shell.sidecar``) stdout readers watch for that prefix, store the value
/// here, and **drop the line from log forwarding** so it never lands in
/// Tauri's log file. The frontend reads the value via the ``get_session_token``
/// IPC command and attaches it as ``Authorization: Bearer <value>`` on every
/// HTTP call to the sidecar.
///
/// Wrapped in ``Arc<Mutex<String>>`` (not bare ``Mutex<String>``) so the
/// reader threads -- spawned with ``std::thread::spawn`` (dev) and
/// ``tauri::async_runtime::spawn`` (prod) -- can each hold their own clone
/// for the lifetime of the sidecar process. Empty string == not-yet-captured;
/// ``get_session_token`` returns ``Err("token-not-ready")`` while empty.
struct SessionToken(Arc<Mutex<String>>);

/// Return the captured Python-sidecar session token to the frontend.
///
/// The frontend's ``api.js`` bootstrap polls this on app boot before firing
/// any axios call. Returns the URL-safe base64 string (no quoting / padding
/// concerns) or a token-not-ready error if the sidecar hasn't yet printed
/// its ``LMS_TOKEN=`` banner line.
///
/// # Errors
/// - ``"token-not-ready"`` if the stdout reader has not yet captured the
///   banner line. Callers MUST retry (the sidecar normally prints within
///   the first ~50 ms of import time, but cold-start can push that out
///   under heavy disk IO).
/// - ``"state-lock-poisoned"`` if a prior holder of the Mutex panicked.
///   Not recoverable -- the user must restart the app.
#[tauri::command]
fn get_session_token(state: State<SessionToken>) -> Result<String, String> {
    let guard = state
        .0
        .lock()
        .map_err(|_| "state-lock-poisoned".to_string())?;
    if guard.is_empty() {
        Err("token-not-ready".to_string())
    } else {
        Ok(guard.clone())
    }
}

/// Inspect one stdout line for the ``LMS_TOKEN=`` boot banner.
///
/// Returns ``true`` when the line carries the token (caller MUST drop it
/// from log forwarding so the value never reaches ``log::info!``).
/// Returns ``false`` for every other line, including subsequent ones --
/// the banner is printed exactly once at sidecar boot and we never
/// overwrite a captured value.
fn try_capture_token(line: &str, token: &Arc<Mutex<String>>) -> bool {
    let Some(value) = line.strip_prefix("LMS_TOKEN=") else {
        return false;
    };
    // .lock() poisoning is non-recoverable; we just skip the capture in that
    // case -- the frontend will keep getting "token-not-ready" until the
    // process restarts, which surfaces the problem to the user.
    if let Ok(mut guard) = token.lock() {
        // Only capture the FIRST banner we see -- prevents a malicious or
        // mis-written downstream line of the same prefix from clobbering
        // the real boot token.
        if guard.is_empty() {
            *guard = value.trim().to_string();
        }
    }
    true
}

#[cfg(debug_assertions)]
struct DevChildren {
    backend: Option<std::process::Child>,
    vite: Option<std::process::Child>,
}

#[cfg(debug_assertions)]
struct DevBackendChild(Mutex<DevChildren>);

#[cfg(debug_assertions)]
fn find_repo_root() -> Option<std::path::PathBuf> {
    let exe = std::env::current_exe().ok()?;
    let mut p = exe.parent()?.to_path_buf();
    for _ in 0..8 {
        if p.join("app").join("main.py").exists() {
            return Some(p);
        }
        p = p.parent()?.to_path_buf();
    }
    if let Ok(cwd) = std::env::current_dir() {
        let mut p = cwd;
        for _ in 0..8 {
            if p.join("app").join("main.py").exists() {
                return Some(p);
            }
            if !p.pop() {
                break;
            }
        }
    }
    None
}

#[cfg(debug_assertions)]
fn is_port_busy(port: u16) -> bool {
    use std::net::TcpStream;
    use std::time::Duration;
    let addr = format!("127.0.0.1:{}", port);
    if let Ok(sock) = addr.parse() {
        TcpStream::connect_timeout(&sock, Duration::from_millis(200)).is_ok()
    } else {
        false
    }
}

#[cfg(debug_assertions)]
fn spawn_child(
    label: &'static str,
    program: &str,
    args: &[&str],
    cwd: &std::path::Path,
    // None => not a sidecar we expect to print LMS_TOKEN= (e.g. vite).
    // Some(token) => watch the first line that starts with LMS_TOKEN= and
    // capture the value into the shared state, dropping that one line
    // from log::info! forwarding so the token never lands in Tauri's log.
    token_capture: Option<Arc<Mutex<String>>>,
) -> Option<std::process::Child> {
    use std::io::{BufRead, BufReader};
    use std::process::{Command, Stdio};

    let mut cmd = Command::new(program);
    cmd.args(args)
        .current_dir(cwd)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    #[cfg(target_os = "windows")]
    {
        use std::os::windows::process::CommandExt;
        cmd.creation_flags(0x08000000); // CREATE_NO_WINDOW
    }

    match cmd.spawn() {
        Ok(mut child) => {
            if let Some(stdout) = child.stdout.take() {
                let lbl = label;
                let capture = token_capture.clone();
                std::thread::spawn(move || {
                    for line in BufReader::new(stdout).lines().flatten() {
                        // Token-capture path: if this is the LMS_TOKEN=
                        // banner line, swallow it (do NOT log::info!) so
                        // the token value can't reach the Tauri log file.
                        if let Some(ref tok) = capture {
                            if try_capture_token(&line, tok) {
                                continue;
                            }
                        }
                        log::info!("[{}] {}", lbl, line);
                    }
                });
            }
            if let Some(stderr) = child.stderr.take() {
                let lbl = label;
                std::thread::spawn(move || {
                    for line in BufReader::new(stderr).lines().flatten() {
                        log::warn!("[{}-err] {}", lbl, line);
                    }
                });
            }
            Some(child)
        }
        Err(e) => {
            log::error!("[{}] Failed to spawn {}: {}", label, program, e);
            None
        }
    }
}

#[cfg(debug_assertions)]
fn spawn_dev_backend(app: &tauri::AppHandle, token: Arc<Mutex<String>>) {
    use tauri::Manager;

    let root = match find_repo_root() {
        Some(r) => r,
        None => {
            log::warn!("[dev-spawn] Could not locate app/main.py — skipping auto-spawn.");
            return;
        }
    };

    let mut backend: Option<std::process::Child> = None;
    let mut vite: Option<std::process::Child> = None;

    // Backend (port 8000)
    if is_port_busy(8000) {
        log::info!("[backend] Port 8000 in use — skipping spawn.");
    } else {
        log::info!(
            "[backend] Spawning python -m app.main from {}",
            root.display()
        );
        backend = spawn_child(
            "backend",
            "python",
            &["-m", "app.main"],
            &root,
            Some(token.clone()),
        );
    }

    // Vite dev server (port 5173) -- never emits LMS_TOKEN=, no capture needed.
    if is_port_busy(5173) {
        log::info!("[vite] Port 5173 in use — skipping spawn.");
    } else {
        let frontend = root.join("frontend");
        if frontend.join("package.json").exists() {
            log::info!("[vite] Spawning npm run dev from {}", frontend.display());
            // npm on Windows is a .cmd shim → run via cmd.exe
            #[cfg(target_os = "windows")]
            {
                vite = spawn_child(
                    "vite",
                    "cmd.exe",
                    &["/c", "npm", "run", "dev"],
                    &frontend,
                    None,
                );
            }
            #[cfg(not(target_os = "windows"))]
            {
                vite = spawn_child("vite", "npm", &["run", "dev"], &frontend, None);
            }
        } else {
            log::warn!("[vite] frontend/package.json missing — skipping.");
        }
    }

    app.manage(DevBackendChild(Mutex::new(DevChildren { backend, vite })));
}

/// Close the splashscreen and reveal the main window.
///
/// Called by the frontend once the React shell has finished hydrating.
/// Both windows are looked up by label (`"splashscreen"`, `"main"`); a
/// missing window is silently ignored so the command can't fail and
/// therefore returns `()` rather than `Result<_, _>`.
#[tauri::command]
fn close_splashscreen(window: tauri::Window) {
    // Close splashscreen — use .ok() to avoid panic if window doesn't exist
    if let Some(splashscreen) = window.get_webview_window("splashscreen") {
        let _ = splashscreen.close();
    }
    // Show main window
    if let Some(main) = window.get_webview_window("main") {
        let _ = main.show();
    }
}

/// Drive the SoundCloud OAuth 2.1 + PKCE handshake to completion.
///
/// Emits three `{stage: "auth", message: ...}` progress events on
/// `progress_event` as the flow advances (opening browser → waiting →
/// exchanging code) and returns the access token on success. Callers
/// that need a terminal "done" event must emit it themselves after this
/// returns — login and export use different final-stage payloads.
///
/// # Errors
/// - "Configuration error" if `SC_CLIENT_ID` / `SC_CLIENT_SECRET` are missing
/// - "Could not open browser" if the OS browser launcher fails
/// - "Task join error" / "Callback error" if the local HTTP listener fails
/// - "Token exchange failed" if SoundCloud rejects the auth code
async fn ensure_oauth_token(
    app: &tauri::AppHandle,
    progress_event: &str,
) -> Result<String, String> {
    // Step 1: Generate auth URL with PKCE
    let (auth_url, code_verifier) =
        soundcloud_client::get_auth_url().map_err(|e| format!("Configuration error: {}", e))?;
    log::info!("[SoundCloud] Opening browser for login...");

    // Emit event: auth started
    let _ = app.emit(
        progress_event,
        serde_json::json!({
            "stage": "auth", "message": "Opening browser for login..."
        }),
    );

    if let Err(e) = open::that(&auth_url) {
        return Err(format!("Could not open browser: {}", e));
    }

    // Step 2: Wait for OAuth callback
    let _ = app.emit(
        progress_event,
        serde_json::json!({
            "stage": "auth", "message": "Waiting for authorization..."
        }),
    );
    let code = tokio::task::spawn_blocking(soundcloud_client::wait_for_callback)
        .await
        .map_err(|e| format!("Task join error: {}", e))?
        .map_err(|e| format!("Callback error: {}", e))?;

    // Step 3: Exchange code for access token
    let _ = app.emit(
        progress_event,
        serde_json::json!({
            "stage": "auth", "message": "Exchanging code for token..."
        }),
    );
    let token = soundcloud_client::exchange_code_for_token(&code, &code_verifier)
        .await
        .map_err(|e| format!("Token exchange failed: {}", e))?;

    Ok(token)
}

/// Run the full SoundCloud OAuth 2.1 + PKCE flow and return the access token.
///
/// Delegates to `ensure_oauth_token` for the actual handshake, then emits a
/// final `{stage: "done", message: "Authorization successful."}` on
/// `sc-login-progress` so the frontend knows it's safe to call subsequent
/// SC endpoints.
///
/// # Errors
/// Propagates every variant from `ensure_oauth_token`.
#[tauri::command]
async fn login_to_soundcloud(app: tauri::AppHandle) -> Result<String, String> {
    let token = ensure_oauth_token(&app, "sc-login-progress").await?;

    log::info!("[SoundCloud] ✓ Authorization successful.");
    let _ = app.emit(
        "sc-login-progress",
        serde_json::json!({
            "stage": "done", "message": "Authorization successful."
        }),
    );

    Ok(token)
}

#[derive(Deserialize)]
struct ExportTrack {
    artist: String,
    title: String,
    duration_ms: u64,
}

/// Create a SoundCloud playlist from `tracks` and return a summary string.
///
/// Delegates the OAuth handshake to `ensure_oauth_token`, then searches SC
/// for each `(artist, title)` pair using a duration heuristic. Tracks that
/// didn't match are listed in the returned summary.
///
/// Stages emitted on the `sc-export-progress` event:
/// - `auth`: OAuth flow (three sub-stages from `ensure_oauth_token`)
/// - `searching`: per-track lookup `{current, total, message, trackName}`
/// - `creating`: final playlist POST
///
/// # Errors
/// - All `ensure_oauth_token` errors are propagated
/// - "Playlist creation failed (...)" if SoundCloud rejects the create
/// - "No tracks were found on SoundCloud" if every search came back empty
#[tauri::command]
async fn export_to_soundcloud(
    app: tauri::AppHandle,
    playlist_name: String,
    tracks: Vec<ExportTrack>,
) -> Result<String, String> {
    let sc_tracks: Vec<Track> = tracks
        .into_iter()
        .map(|t| Track {
            artist: t.artist,
            title: t.title,
            duration_ms: t.duration_ms,
        })
        .collect();

    let token = ensure_oauth_token(&app, "sc-export-progress").await?;
    log::info!("[SoundCloud] ✓ Access token received.");

    // Step 4: Search tracks and create playlist
    let result =
        soundcloud_client::search_and_create_playlist(&token, &playlist_name, sc_tracks, Some(app))
            .await
            .map_err(|e| format!("Playlist creation failed: {}", e))?;

    if result.failed_tracks.is_empty() {
        Ok(format!(
            "Playlist '{}' exported to SoundCloud! (All {} tracks)",
            playlist_name, result.success_count
        ))
    } else {
        // Return a detailed report of failures
        let failed_list = result.failed_tracks.join("\n- ");
        Ok(format!(
            "Exported {} tracks.\n\nFailed to find {} tracks:\n- {}",
            result.success_count,
            result.failed_tracks.len(),
            failed_list
        ))
    }
}

fn main() {
    // Initialise the global logger backend (stderr, default INFO level).
    // Without this every `log::info!` / `log::warn!` / `log::error!` macro
    // elsewhere in the crate would be a no-op. RUST_LOG env var overrides
    // the default — e.g. `RUST_LOG=debug` for verbose dev builds.
    env_logger::Builder::new()
        .filter_level(log::LevelFilter::Info)
        .parse_default_env()
        .init();

    // Robust .env loading: search in current and parent dirs
    match dotenvy::dotenv() {
        Ok(path) => log::info!("[LibraryManagementSystem] Found .env at: {:?}", path),
        Err(_) => log::info!(
            "[LibraryManagementSystem] No .env file found. Using system environment variables."
        ),
    }

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .manage(AudioCommandState(Mutex::new(AudioController::default())))
        .manage(SessionToken(Arc::new(Mutex::new(String::new()))))
        .invoke_handler(tauri::generate_handler![
            close_splashscreen,
            login_to_soundcloud,
            export_to_soundcloud,
            load_audio,
            get_3band_waveform,
            list_audio_devices,
            start_project_export,
            fingerprint_track,
            fingerprint_batch,
            get_session_token
        ])
        .setup(|app| {
            // Both spawn paths feed into the same shared SessionToken state
            // registered above. We pull a clone of the Arc out of the
            // managed state so the per-spawn-thread closures own their own
            // handle for the lifetime of the sidecar process.
            let token_state: State<SessionToken> = app.state::<SessionToken>();
            let token_handle: Arc<Mutex<String>> = token_state.0.clone();

            #[cfg(not(debug_assertions))]
            {
                let shell = app.shell();
                let sidecar_command = shell
                    .sidecar("rb-backend")
                    .map_err(|e| format!("failed to create sidecar command: {}", e))?;

                let (mut rx, child) = sidecar_command
                    .spawn()
                    .map_err(|e| format!("failed to spawn sidecar: {}", e))?;

                let token_for_loop = token_handle.clone();
                tauri::async_runtime::spawn(async move {
                    // Keep the child alive in this scope
                    let _child = child;
                    loop {
                        match rx.recv().await {
                            Some(event) => {
                                match event {
                                    CommandEvent::Stdout(line) => {
                                        let text = String::from_utf8_lossy(&line);
                                        let trimmed = text.trim();
                                        // Detect-and-drop the LMS_TOKEN= banner BEFORE
                                        // forwarding the line to log::info!, so the
                                        // token value can't reach Tauri's log file.
                                        if try_capture_token(trimmed, &token_for_loop) {
                                            continue;
                                        }
                                        log::info!("backend: {}", trimmed);
                                    }
                                    CommandEvent::Stderr(line) => {
                                        log::warn!(
                                            "backend-error: {}",
                                            String::from_utf8_lossy(&line).trim()
                                        );
                                    }
                                    CommandEvent::Error(err) => {
                                        log::error!("backend-critical: {}", err);
                                    }
                                    _ => {}
                                }
                            }
                            None => break,
                        }
                    }
                });
            }

            #[cfg(debug_assertions)]
            {
                spawn_dev_backend(&app.handle(), token_handle);
            }

            Ok(())
        })
        .build(tauri::generate_context!())
        .unwrap_or_else(|err| {
            // Last-resort fatal exit path. We deliberately use `eprintln!`
            // rather than `log::error!` here — the logger backend may have
            // failed to come up, or its sink could be the very thing that
            // crashed the Builder. Writing directly to stderr is the most
            // reliable channel we have to surface the error before the
            // process exits non-zero. This is the only println/eprintln
            // outside `#[cfg(test)]` in the crate, by design.
            eprintln!("[fatal] error while building tauri application: {err}");
            std::process::exit(1);
        })
        .run(|_app_handle, _event| {
            #[cfg(debug_assertions)]
            {
                if let tauri::RunEvent::Exit = _event {
                    use tauri::Manager;
                    if let Some(state) = _app_handle.try_state::<DevBackendChild>() {
                        if let Ok(mut guard) = state.0.lock() {
                            if let Some(mut child) = guard.backend.take() {
                                let _ = child.kill();
                                log::info!("[backend] Killed on app exit.");
                            }
                            if let Some(mut child) = guard.vite.take() {
                                let _ = child.kill();
                                log::info!("[vite] Killed on app exit.");
                            }
                        }
                    }
                }
            }
        });
}
