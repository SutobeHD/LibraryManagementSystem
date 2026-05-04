//! fingerprint.rs — Acoustic Fingerprinting for Duplicate Detection
//!
//! Implements a lightweight Chromaprint-style audio fingerprint:
//!   1. Decode audio via Symphonia (reuses engine.rs decode path)
//!   2. Downsample to 11025 Hz mono via averaging
//!   3. Compute 32-band Mel spectrogram over 128-ms sliding windows
//!   4. Quantize energy differences across adjacent bands/frames into u32 hash words
//!   5. Compare fingerprints with Hamming distance → similarity 0.0–1.0
//!
//! # Design constraints
//! - No network access, no external process
//! - Must work offline on all Symphonia-supported formats
//! - Progress is emitted via Tauri events so the UI can show a progress bar
//!
//! # Tauri commands exposed
//! - `fingerprint_track(path)` → `Vec<u32>`
//! - `fingerprint_batch(paths, window)` → `HashMap<String, Vec<u32>>`
//!   Emits `"fingerprint_progress"` events: `{done: usize, total: usize}`

use std::collections::HashMap;
use log::{debug, error, info, warn};
use serde::Serialize;
use tauri::Emitter;
use symphonia::core::audio::SampleBuffer;
use symphonia::core::codecs::DecoderOptions;
use symphonia::core::formats::FormatOptions;
use symphonia::core::io::MediaSourceStream;
use symphonia::core::meta::MetadataOptions;
use symphonia::core::probe::Hint;

// ─────────────────────────────────────────────────────────────────────────────
//  Constants
// ─────────────────────────────────────────────────────────────────────────────

/// Target sample rate for fingerprint analysis (11025 Hz — low SR is sufficient).
const TARGET_SR: usize = 11025;

/// Number of Mel filter banks.
const N_MELS: usize = 32;

/// Window size in samples at TARGET_SR (128 ms).
const FRAME_SIZE: usize = 1408; // ≈ 128 ms @ 11025 Hz

/// Hop between consecutive frames (50% overlap).
const HOP_SIZE: usize = FRAME_SIZE / 2;

/// Minimum fingerprint length to consider two fingerprints comparable.
const MIN_FP_LEN: usize = 4;

// ─────────────────────────────────────────────────────────────────────────────
//  Decode and resample helpers
// ─────────────────────────────────────────────────────────────────────────────

/// Decode an audio file to mono f32 samples at TARGET_SR.
///
/// Uses Symphonia for decoding (supports MP3, FLAC, WAV, AIFF, ALAC, M4A).
/// Resamples by simple linear decimation when the source SR is an integer
/// multiple of TARGET_SR; otherwise uses nearest-neighbour (fast, sufficient
/// for fingerprinting — we don't need high fidelity).
///
/// # Errors
/// Returns `Err(String)` if the file cannot be opened or decoded.
fn decode_to_mono_11k(path: &str) -> Result<Vec<f32>, String> {
    use std::fs::File;

    debug!("fingerprint: decoding {}", path);

    let file = File::open(path).map_err(|e| format!("Cannot open file '{}': {}", path, e))?;
    let mss = MediaSourceStream::new(Box::new(file), Default::default());

    let mut hint = Hint::new();
    if let Some(ext) = std::path::Path::new(path).extension().and_then(|s| s.to_str()) {
        hint.with_extension(ext);
    }

    let probed = symphonia::default::get_probe()
        .format(
            &hint,
            mss,
            &FormatOptions::default(),
            &MetadataOptions::default(),
        )
        .map_err(|e| format!("Probe failed for '{}': {}", path, e))?;

    let mut format = probed.format;
    let track = format
        .default_track()
        .ok_or_else(|| format!("No default track in '{}'", path))?;

    let track_id = track.id;
    let codec_params = track.codec_params.clone();
    let source_sr = codec_params.sample_rate.unwrap_or(44100) as usize;
    let source_channels = codec_params.channels.map(|c| c.count()).unwrap_or(2);

    let mut decoder = symphonia::default::get_codecs()
        .make(&codec_params, &DecoderOptions::default())
        .map_err(|e| format!("Codec init failed for '{}': {}", path, e))?;

    let mut raw_samples: Vec<f32> = Vec::with_capacity(source_sr * 30); // pre-alloc 30s

    // Decode packets
    loop {
        let packet = match format.next_packet() {
            Ok(p) => p,
            Err(_) => break, // end of stream or decode error — stop gracefully
        };
        if packet.track_id() != track_id {
            continue;
        }
        let decoded = match decoder.decode(&packet) {
            Ok(d) => d,
            Err(e) => {
                warn!("fingerprint: decode error on packet — {}", e);
                continue;
            }
        };

        // Convert to f32 sample buffer
        let spec = *decoded.spec();
        let mut sample_buf: SampleBuffer<f32> =
            SampleBuffer::new(decoded.capacity() as u64, spec);
        sample_buf.copy_interleaved_ref(decoded);

        // Mix down to mono: average across channels
        let samples = sample_buf.samples();
        let ch = source_channels.max(1);
        for frame_start in (0..samples.len()).step_by(ch) {
            let mono = samples[frame_start..frame_start + ch.min(samples.len() - frame_start)]
                .iter()
                .sum::<f32>()
                / ch as f32;
            raw_samples.push(mono);
        }

        // Safety cap: only fingerprint up to 5 minutes (sufficient for dedup)
        if raw_samples.len() >= source_sr * 300 {
            break;
        }
    }

    debug!(
        "fingerprint: decoded {} mono samples @ {}Hz from '{}'",
        raw_samples.len(),
        source_sr,
        path
    );

    if raw_samples.is_empty() {
        return Err(format!("No audio decoded from '{}'", path));
    }

    // Resample to TARGET_SR (11025 Hz) via decimation / linear interpolation
    let resampled = resample_mono(&raw_samples, source_sr, TARGET_SR);

    debug!(
        "fingerprint: resampled to {} samples @ {}Hz",
        resampled.len(),
        TARGET_SR
    );

    Ok(resampled)
}

/// Simple sample-rate conversion: nearest-neighbour for speed.
/// Sufficient for fingerprinting (we don't care about audio quality here).
fn resample_mono(input: &[f32], src_sr: usize, dst_sr: usize) -> Vec<f32> {
    if src_sr == dst_sr {
        return input.to_vec();
    }
    let ratio = src_sr as f64 / dst_sr as f64;
    let out_len = (input.len() as f64 / ratio).ceil() as usize;
    let mut out = Vec::with_capacity(out_len);
    for i in 0..out_len {
        let src_idx = ((i as f64 * ratio) as usize).min(input.len() - 1);
        out.push(input[src_idx]);
    }
    out
}

// ─────────────────────────────────────────────────────────────────────────────
//  Mel spectrogram
// ─────────────────────────────────────────────────────────────────────────────

/// Compute Mel filterbank energies for a single frame of samples.
///
/// Uses a triangular filterbank spanning 0–4000 Hz (fingerprint-relevant range).
/// No FFT library used — we compute a simple DFT-like energy estimate per band
/// using cosine correlation (Goertzel-style) for the N_MELS centre frequencies.
/// This is not a full FFT Mel spectrogram but sufficient for fingerprint hashing.
fn mel_frame_energies(frame: &[f32]) -> [f32; N_MELS] {
    let _n = frame.len();
    let mut energies = [0.0f32; N_MELS];

    // Mel scale: linearly spaced in Mel domain from 80–4000 Hz
    let mel_min = hz_to_mel(80.0);
    let mel_max = hz_to_mel(4000.0);

    for (k, e) in energies.iter_mut().enumerate() {
        let mel_centre = mel_min + (mel_max - mel_min) * (k as f64 / (N_MELS - 1) as f64);
        let freq_hz = mel_to_hz(mel_centre);
        // Goertzel energy at this frequency
        let omega = 2.0 * std::f64::consts::PI * freq_hz / TARGET_SR as f64;
        let coeff = 2.0 * omega.cos() as f32;
        let (mut s1, mut s2) = (0.0f32, 0.0f32);
        for &x in frame {
            let s0 = x + coeff * s1 - s2;
            s2 = s1;
            s1 = s0;
        }
        // Energy = magnitude squared
        *e = s1 * s1 + s2 * s2 - coeff * s1 * s2;
    }

    energies
}

fn hz_to_mel(hz: f64) -> f64 {
    2595.0 * (1.0 + hz / 700.0).log10()
}

fn mel_to_hz(mel: f64) -> f64 {
    700.0 * (10.0_f64.powf(mel / 2595.0) - 1.0)
}

// ─────────────────────────────────────────────────────────────────────────────
//  Fingerprint generation
// ─────────────────────────────────────────────────────────────────────────────

/// Generate a fingerprint as a Vec<u32> from decoded mono samples.
///
/// Algorithm (Chromaprint-style sub-fingerprint):
///   For each overlapping frame:
///     1. Compute N_MELS Mel-band energies
///     2. Compute energy differences across adjacent bands (d[k] = E[k] - E[k-1])
///     3. Compare differences between consecutive frames (temporal gradient)
///     4. Pack 32 binary comparisons into one u32 hash word
///
/// Returns one u32 per frame where the temporal gradient is valid (frame ≥ 1).
fn samples_to_fingerprint(samples: &[f32]) -> Vec<u32> {
    if samples.len() < FRAME_SIZE {
        return Vec::new();
    }

    let frame_count = (samples.len() - FRAME_SIZE) / HOP_SIZE + 1;
    let mut mel_frames: Vec<[f32; N_MELS]> = Vec::with_capacity(frame_count);

    for i in 0..frame_count {
        let start = i * HOP_SIZE;
        let end = (start + FRAME_SIZE).min(samples.len());
        let frame = &samples[start..end];
        mel_frames.push(mel_frame_energies(frame));
    }

    // Compute sub-fingerprints from adjacent frame differences
    let mut fingerprint: Vec<u32> = Vec::with_capacity(frame_count.saturating_sub(1));

    for i in 1..mel_frames.len() {
        let prev = &mel_frames[i - 1];
        let curr = &mel_frames[i];

        // Temporal gradient: diff of energy diffs
        let mut word: u32 = 0;
        for k in 0..N_MELS.min(32) {
            let d_curr = curr[k] - if k > 0 { curr[k - 1] } else { 0.0 };
            let d_prev = prev[k] - if k > 0 { prev[k - 1] } else { 0.0 };
            if d_curr > d_prev {
                word |= 1 << k;
            }
        }
        fingerprint.push(word);
    }

    fingerprint
}

// ─────────────────────────────────────────────────────────────────────────────
//  Similarity
// ─────────────────────────────────────────────────────────────────────────────

/// Compute similarity between two fingerprints using Hamming distance.
///
/// Aligns the fingerprints at the start and compares the overlapping portion.
/// Returns a similarity score in [0.0, 1.0] where 1.0 = identical.
///
/// # Returns
/// `None` if either fingerprint is too short to compare reliably.
pub fn hamming_similarity(a: &[u32], b: &[u32]) -> Option<f32> {
    let len = a.len().min(b.len());
    if len < MIN_FP_LEN {
        return None;
    }
    // Compare the first `len` words
    let total_bits = len * 32;
    let matching_bits: usize = a
        .iter()
        .zip(b.iter())
        .map(|(&x, &y)| (x ^ y).count_ones() as usize)
        .sum();
    let different_bits = matching_bits;
    let similarity = 1.0 - (different_bits as f32 / total_bits as f32);
    Some(similarity)
}

// ─────────────────────────────────────────────────────────────────────────────
//  Tauri commands
// ─────────────────────────────────────────────────────────────────────────────

/// Progress event payload emitted during batch fingerprinting.
#[derive(Clone, Serialize)]
pub struct FingerprintProgress {
    pub done: usize,
    pub total: usize,
    pub current_path: String,
}

/// Compute the acoustic fingerprint for a single audio file.
///
/// # Errors
/// Returns `Err(String)` if the file cannot be decoded.
#[tauri::command]
pub async fn fingerprint_track(path: String) -> Result<Vec<u32>, String> {
    info!("fingerprint_track: {}", path);

    let result = tokio::task::spawn_blocking(move || {
        let samples = decode_to_mono_11k(&path)?;
        let fp = samples_to_fingerprint(&samples);
        info!("fingerprint_track: {} → {} fp words", path, fp.len());
        Ok(fp)
    })
    .await
    .map_err(|e| format!("Task join error: {}", e))?;

    result
}

/// Compute fingerprints for a batch of audio files, emitting progress events.
///
/// Emits `"fingerprint_progress"` event after each file with `{done, total, current_path}`.
///
/// # Errors
/// Returns `Err(String)` if the Tauri window handle cannot emit events.
/// Individual file failures are logged and skipped (result map omits them).
#[tauri::command]
pub async fn fingerprint_batch(
    paths: Vec<String>,
    window: tauri::Window,
) -> Result<HashMap<String, Vec<u32>>, String> {
    let total = paths.len();
    info!("fingerprint_batch: {} files", total);

    let mut results: HashMap<String, Vec<u32>> = HashMap::new();

    for (done, path) in paths.iter().enumerate() {
        let path_clone = path.clone();

        // Emit progress before processing this file
        let _ = window.emit(
            "fingerprint_progress",
            FingerprintProgress {
                done,
                total,
                current_path: path.clone(),
            },
        );

        // Run decoding + fingerprinting in blocking thread pool
        let fp_result = tokio::task::spawn_blocking(move || {
            let samples = decode_to_mono_11k(&path_clone)?;
            Ok::<Vec<u32>, String>(samples_to_fingerprint(&samples))
        })
        .await
        .map_err(|e| format!("Task join error: {}", e))?;

        match fp_result {
            Ok(fp) => {
                debug!("fingerprint_batch: {} → {} words", path, fp.len());
                results.insert(path.clone(), fp);
            }
            Err(e) => {
                error!("fingerprint_batch: failed for '{}' — {}", path, e);
                // Continue with remaining files
            }
        }
    }

    // Final progress event
    let _ = window.emit(
        "fingerprint_progress",
        FingerprintProgress {
            done: total,
            total,
            current_path: String::new(),
        },
    );

    info!("fingerprint_batch: completed {}/{} files", results.len(), total);
    Ok(results)
}
