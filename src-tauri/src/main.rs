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
        Ok(path) => println!("[RB Editor] Found .env at: {:?}", path),
        Err(_) => println!("[RB Editor] No .env file found. Using system environment variables."),
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
                println!("Debug mode detected: Skipping sidecar spawn. Ensure the backend is running manually on port 8000.");
            }

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
