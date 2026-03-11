use tauri::{command, Emitter};
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
pub async fn get_3band_waveform(path: String) -> Result<serde_json::Value, String> {
    // Computes FFT and analysis in background
    tokio::task::spawn_blocking(move || {
        let (mut format, mut decoder, track_id, sample_rate) = crate::audio::engine::AudioEngine::load_file(&path)?;
        
        // Fully decode for analysis (simpler for prototype)
        let mut source_samples: Vec<f32> = Vec::new();
        let mut sample_buf: Option<symphonia::core::audio::SampleBuffer<f32>> = None;

        while let Ok(packet) = format.next_packet() {
            if packet.track_id() != track_id { continue; }
            if let Ok(decoded) = decoder.decode(&packet) {
                if sample_buf.is_none() {
                    use symphonia::core::audio::Signal;
                    sample_buf = Some(symphonia::core::audio::SampleBuffer::<f32>::new(decoded.capacity() as u64, *decoded.spec()));
                }
                if let Some(buf) = &mut sample_buf {
                    buf.copy_interleaved_ref(decoded);
                    source_samples.extend_from_slice(buf.samples());
                }
            }
        }

        let waveform = analysis::compute_waveform(&path)?;
        let bpm = analysis::estimate_bpm(&source_samples, sample_rate);
        let key = analysis::detect_key(&source_samples, sample_rate);

        Ok(serde_json::json!({
            "waveform": waveform, // Array of u8
            "bpm": bpm,
            "key": key
        }))
    }).await.map_err(|e| e.to_string())?
}

use crate::audio::export::{ProjectState, render_project};

#[command]
pub async fn start_project_export(
    app: tauri::AppHandle,
    project_state: ProjectState,
) -> Result<String, String> {
    // Req 8: Async Export
    tokio::task::spawn_blocking(move || {
        let res = render_project(project_state, |p, msg| {
            let _ = app.emit("export-progress", serde_json::json!({ 
                "progress": p, 
                "message": msg 
            }));
        });

        match res {
            Ok(msg) => {
                let _ = app.emit("export-success", serde_json::json!({ "message": msg }));
            }
            Err(e) => {
                let _ = app.emit("export-error", serde_json::json!({ "error": e }));
            }
        }
    });

    Ok("Export started in background...".to_string())
}
