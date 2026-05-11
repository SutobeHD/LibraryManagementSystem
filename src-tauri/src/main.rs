// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
mod soundcloud_client;
mod audio;

use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::CommandEvent;
use serde::Deserialize;
use soundcloud_client::Track;
use tauri::{Emitter, Manager};
use audio::commands::{load_audio, get_3band_waveform, start_project_export, list_audio_devices, AudioCommandState};
use audio::fingerprint::{fingerprint_track, fingerprint_batch};
use audio::engine::AudioController;
use std::sync::Mutex;

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
            if !p.pop() { break; }
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
) -> Option<std::process::Child> {
    use std::process::{Command, Stdio};
    use std::io::{BufRead, BufReader};

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
                std::thread::spawn(move || {
                    for line in BufReader::new(stdout).lines().flatten() {
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
fn spawn_dev_backend(app: &tauri::AppHandle) {
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
        log::info!("[backend] Spawning python -m app.main from {}", root.display());
        backend = spawn_child("backend", "python", &["-m", "app.main"], &root);
    }

    // Vite dev server (port 5173)
    if is_port_busy(5173) {
        log::info!("[vite] Port 5173 in use — skipping spawn.");
    } else {
        let frontend = root.join("frontend");
        if frontend.join("package.json").exists() {
            log::info!("[vite] Spawning npm run dev from {}", frontend.display());
            // npm on Windows is a .cmd shim → run via cmd.exe
            #[cfg(target_os = "windows")]
            {
                vite = spawn_child("vite", "cmd.exe", &["/c", "npm", "run", "dev"], &frontend);
            }
            #[cfg(not(target_os = "windows"))]
            {
                vite = spawn_child("vite", "npm", &["run", "dev"], &frontend);
            }
        } else {
            log::warn!("[vite] frontend/package.json missing — skipping.");
        }
    }

    app.manage(DevBackendChild(Mutex::new(DevChildren { backend, vite })));
}

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

#[tauri::command]
async fn login_to_soundcloud(app: tauri::AppHandle) -> Result<String, String> {
    // Step 1: Generate auth URL with PKCE
    let (auth_url, code_verifier) = soundcloud_client::get_auth_url()
        .map_err(|e| format!("Configuration error: {}", e))?;
    log::info!("[SoundCloud] Opening browser for login...");
    
    // Emit event: auth started
    let _ = app.emit("sc-login-progress", serde_json::json!({ "stage": "auth", "message": "Opening browser for login..." }));
    
    if let Err(e) = open::that(&auth_url) {
        return Err(format!("Could not open browser: {}", e));
    }

    // Step 2: Wait for OAuth callback
    let _ = app.emit("sc-login-progress", serde_json::json!({ "stage": "auth", "message": "Waiting for authorization..." }));
    let code = tokio::task::spawn_blocking(soundcloud_client::wait_for_callback)
        .await
        .map_err(|e| format!("Task join error: {}", e))?
        .map_err(|e| format!("Callback error: {}", e))?;

    // Step 3: Exchange code for access token
    let _ = app.emit("sc-login-progress", serde_json::json!({ "stage": "auth", "message": "Exchanging code for token..." }));
    let token = soundcloud_client::exchange_code_for_token(&code, &code_verifier)
        .await
        .map_err(|e| format!("Token exchange failed: {}", e))?;
    
    log::info!("[SoundCloud] ✓ Authorization successful.");
    let _ = app.emit("sc-login-progress", serde_json::json!({ "stage": "done", "message": "Authorization successful." }));
    
    Ok(token)
}

#[derive(Deserialize)]
struct ExportTrack {
    artist: String,
    title: String,
    duration_ms: u64,
}

#[tauri::command]
async fn export_to_soundcloud(app: tauri::AppHandle, playlist_name: String, tracks: Vec<ExportTrack>) -> Result<String, String> {
    let sc_tracks: Vec<Track> = tracks
        .into_iter()
        .map(|t| Track {
            artist: t.artist,
            title: t.title,
            duration_ms: t.duration_ms,
        })
        .collect();

    // Step 1: Generate auth URL with PKCE
    let (auth_url, code_verifier) = soundcloud_client::get_auth_url()
        .map_err(|e| format!("Configuration error: {}", e))?;
    log::info!("[SoundCloud] Opening browser for login...");
    
    // Emit event: auth started
    let _ = app.emit("sc-export-progress", serde_json::json!({ "stage": "auth", "message": "Opening browser for login..." }));
    
    if let Err(e) = open::that(&auth_url) {
        return Err(format!("Could not open browser: {}", e));
    }

    // Step 2: Wait for OAuth callback (blocking listener on 127.0.0.1:5001)
    let _ = app.emit("sc-export-progress", serde_json::json!({ "stage": "auth", "message": "Waiting for authorization..." }));
    let code = tokio::task::spawn_blocking(soundcloud_client::wait_for_callback)
        .await
        .map_err(|e| format!("Task join error: {}", e))?
        .map_err(|e| format!("Callback error: {}", e))?;

    // Step 3: Exchange code for access token
    let _ = app.emit("sc-export-progress", serde_json::json!({ "stage": "auth", "message": "Exchanging code for token..." }));
    let token = soundcloud_client::exchange_code_for_token(&code, &code_verifier)
        .await
        .map_err(|e| format!("Token exchange failed: {}", e))?;
    log::info!("[SoundCloud] ✓ Access token received.");

    // Step 4: Search tracks and create playlist
    // Step 4: Search tracks and create playlist
    let result = soundcloud_client::search_and_create_playlist(&token, &playlist_name, sc_tracks, Some(app))
        .await
        .map_err(|e| format!("Playlist creation failed: {}", e))?;

    if result.failed_tracks.is_empty() {
        Ok(format!("Playlist '{}' exported to SoundCloud! (All {} tracks)", playlist_name, result.success_count))
    } else {
        // Return a detailed report of failures
        let failed_list = result.failed_tracks.join("\n- ");
        Ok(format!("Exported {} tracks.\n\nFailed to find {} tracks:\n- {}", 
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
        Err(_) => log::info!("[LibraryManagementSystem] No .env file found. Using system environment variables."),
    }
    
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .manage(AudioCommandState(Mutex::new(AudioController::default())))
        .invoke_handler(tauri::generate_handler![
            close_splashscreen, 
            login_to_soundcloud, 
            export_to_soundcloud,
            load_audio,
            get_3band_waveform,
            list_audio_devices,
            start_project_export,
            fingerprint_track,
            fingerprint_batch
        ])
        .setup(|app| {
            #[cfg(not(debug_assertions))]
            {
                let shell = app.shell();
                let sidecar_command = shell.sidecar("rb-backend")
                    .map_err(|e| format!("failed to create sidecar command: {}", e))?;

                let (mut rx, child) = sidecar_command
                    .spawn()
                    .map_err(|e| format!("failed to spawn sidecar: {}", e))?;

                tauri::async_runtime::spawn(async move {
                    // Keep the child alive in this scope
                    let _child = child;
                    loop {
                        match rx.recv().await {
                            Some(event) => {
                                match event {
                                    CommandEvent::Stdout(line) => {
                                        log::info!("backend: {}", String::from_utf8_lossy(&line).trim());
                                    }
                                    CommandEvent::Stderr(line) => {
                                        log::warn!("backend-error: {}", String::from_utf8_lossy(&line).trim());
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
                spawn_dev_backend(&app.handle());
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
