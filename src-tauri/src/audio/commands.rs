use tauri::command;
use crate::audio::analysis;
use crate::audio::engine::AudioController;
use std::sync::Mutex;

// Global state holding the playback controller
pub struct AudioCommandState(pub Mutex<AudioController>);

#[command]
pub async fn load_audio(
    state: tauri::State<'_, AudioCommandState>,
    path: String,
) -> Result<String, String> {
    let mut engine = state.0.lock().map_err(|_| "Lock poisoned")?;
    engine.load_and_play(&path)?;
    Ok(format!("Playing: {}", path))
}

#[command]
pub async fn get_waveform(path: String) -> Result<Vec<u8>, String> {
    // Computes FFT in background, sending raw Vec<u8> back
    // Tauri v2 transparently sends this as UInt8Array (Req 14)
    tokio::task::spawn_blocking(move || {
        analysis::compute_waveform(path)
    }).await.map_err(|e| e.to_string())?
}
