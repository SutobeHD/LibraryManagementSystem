// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
mod soundcloud_client;
mod audio;

use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use serde::Deserialize;
use soundcloud_client::Track;
use tauri::{Emitter, Manager, RunEvent};
use audio::commands::{load_audio, get_3band_waveform, start_project_export, list_audio_devices, AudioCommandState};
use audio::fingerprint::{fingerprint_track, fingerprint_batch};
use audio::engine::AudioController;
use std::sync::{Arc, Mutex};

/// Shared holder for the Python sidecar's process handle. We stash it here
/// at spawn-time so the `RunEvent::Exit` handler can kill it when Tauri
/// shuts down — otherwise (especially on Windows) the FastAPI process
/// keeps running after the user closes the app window.
struct BackendChildState(Arc<Mutex<Option<CommandChild>>>);

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
    println!("[SoundCloud] Opening browser for login...");
    
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
    
    println!("[SoundCloud] ✓ Authorization successful.");
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
    println!("[SoundCloud] Opening browser for login...");
    
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
    println!("[SoundCloud] ✓ Access token received.");

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
    // Robust .env loading: search in current and parent dirs
    match dotenvy::dotenv() {
        Ok(path) => println!("[LibraryManagementSystem] Found .env at: {:?}", path),
        Err(_) => println!("[LibraryManagementSystem] No .env file found. Using system environment variables."),
    }
    
    let backend_child: Arc<Mutex<Option<CommandChild>>> = Arc::new(Mutex::new(None));
    let backend_child_for_setup = backend_child.clone();

    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .manage(AudioCommandState(Mutex::new(AudioController::default())))
        .manage(BackendChildState(backend_child.clone()))
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
        .setup(move |app| {
            #[cfg(not(debug_assertions))]
            {
                let shell = app.shell();
                let sidecar_command = shell.sidecar("rb-backend")
                    .map_err(|e| format!("failed to create sidecar command: {}", e))?;

                let (mut rx, child) = sidecar_command
                    .spawn()
                    .map_err(|e| format!("failed to spawn sidecar: {}", e))?;

                // Stash the child in shared state so the exit handler can
                // kill it when the Tauri app shuts down.
                if let Ok(mut slot) = backend_child_for_setup.lock() {
                    *slot = Some(child);
                }

                tauri::async_runtime::spawn(async move {
                    loop {
                        match rx.recv().await {
                            Some(event) => {
                                match event {
                                    CommandEvent::Stdout(line) => {
                                        println!("backend: {}", String::from_utf8_lossy(&line).trim());
                                    }
                                    CommandEvent::Stderr(line) => {
                                        eprintln!("backend-error: {}", String::from_utf8_lossy(&line).trim());
                                    }
                                    CommandEvent::Error(err) => {
                                        eprintln!("backend-critical: {}", err);
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
                let _ = &backend_child_for_setup; // silence unused-warning in dev builds
                println!("Debug mode detected: Skipping sidecar spawn. Ensure the backend is running manually on port 8000.");
            }

            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    // Tear-down: kill the backend sidecar BEFORE the Tauri process itself
    // exits. Both `ExitRequested` (close-button / quit menu) and `Exit`
    // (final teardown) fire — we handle both so the child dies even if the
    // app is force-quit through the OS.
    app.run(move |app_handle, event| {
        match event {
            RunEvent::ExitRequested { .. } | RunEvent::Exit => {
                if let Some(state) = app_handle.try_state::<BackendChildState>() {
                    if let Ok(mut slot) = state.0.lock() {
                        if let Some(child) = slot.take() {
                            println!("Shutting down backend sidecar (pid={})...", child.pid());
                            if let Err(e) = child.kill() {
                                eprintln!("Failed to kill backend sidecar: {}", e);
                            }
                        }
                    }
                }
            }
            _ => {}
        }
    });
}
