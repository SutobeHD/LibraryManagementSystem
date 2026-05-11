use tauri::{command, Emitter};
use crate::audio::analysis;
use crate::audio::engine::AudioController;
use std::sync::Mutex;

// Global state holding the playback controller
pub struct AudioCommandState(pub Mutex<AudioController>);

/// Memory-map an audio file and start playback through the CPAL output stream.
///
/// The decoder selection happens lazily on the audio thread — this command
/// just verifies the file is loadable and primes the playback engine. The
/// frontend should consider playback "started" once this returns Ok.
///
/// # Errors
/// - `"Lock poisoned"` if the shared `AudioController` mutex was poisoned
///   by a panic in another thread
/// - Symphonia / I/O failures (no supported codec, file unreadable, ...)
///   are propagated as their stringified form
#[command]
pub async fn load_audio(
    state: tauri::State<'_, AudioCommandState>,
    path: String,
) -> Result<String, String> {
    let mut engine = state.0.lock().map_err(|_| "Lock poisoned")?;
    engine.load_and_play(&path)?;
    Ok(format!("Playing: {}", path))
}

/// Compute a 3-band FFT waveform plus BPM and key estimate for one file.
///
/// Runs on the blocking thread pool (`tokio::task::spawn_blocking`) because
/// the function fully decodes the file into memory for analysis. Returns
/// a JSON object:
/// ```json
/// { "waveform": [u8; ...], "bpm": f32, "key": String }
/// ```
/// `waveform` is the 3-byte-per-frame low/mid/high RMS energy array from
/// `analysis::compute_waveform`. `key` is currently empty — real key
/// detection lives in the Python backend (see analysis.rs:detect_key).
///
/// # Errors
/// - Task join errors if the blocking task panics
/// - Symphonia decode errors are propagated as stringified form
#[command]
pub async fn get_3band_waveform(path: String) -> Result<serde_json::Value, String> {
    // Computes FFT and analysis in background
    tokio::task::spawn_blocking(move || {
        let (mut format, mut decoder, track_id, sample_rate, channels) =
            crate::audio::engine::AudioEngine::load_file(&path)?;

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
        let bpm = analysis::estimate_bpm(&source_samples, sample_rate, channels);
        let key = analysis::detect_key(&source_samples, sample_rate);

        Ok(serde_json::json!({
            "waveform": waveform, // Array of u8
            "bpm": bpm,
            "key": key
        }))
    }).await.map_err(|e| e.to_string())?
}

/// List all available audio output device names on this machine.
///
/// Uses CPAL's default host to enumerate output devices. Returns a list of
/// human-readable device names the user can choose from in Settings.
/// The first entry is always "System Default" (empty string mapped to CPAL's default).
///
/// # Errors
/// Returns `Err(String)` if the CPAL host fails to enumerate devices.
#[command]
pub async fn list_audio_devices() -> Result<Vec<String>, String> {
    use cpal::traits::{DeviceTrait, HostTrait};
    tokio::task::spawn_blocking(|| {
        let host = cpal::default_host();
        let devices = host
            .output_devices()
            .map_err(|e| format!("Failed to enumerate audio output devices: {}", e))?;
        let mut names = vec!["System Default".to_string()];
        for device in devices {
            match device.name() {
                Ok(name) => names.push(name),
                Err(e) => log::warn!("Skipping device with unreadable name: {}", e),
            }
        }
        log::info!("[Audio] Enumerated {} output devices", names.len());
        Ok(names)
    })
    .await
    .map_err(|e| e.to_string())?
}

use crate::audio::export::{ProjectState, render_project};

/// Render a non-destructive DAW project to disk asynchronously.
///
/// This command returns immediately with a started-confirmation message;
/// the actual mixdown runs on the blocking thread pool. Progress is
/// reported on the `export-progress` event (`{progress: f32, message:
/// String}`) and the terminal status arrives on either `export-success`
/// (`{message: String}`) or `export-error` (`{error: String}`).
///
/// # Errors
/// This command itself only returns Err synchronously if Tauri can't
/// spawn the blocking task. Render-time failures (invalid region bounds,
/// total_samples overflow, WAV write errors, …) are surfaced via the
/// `export-error` event rather than the Result return value.
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
