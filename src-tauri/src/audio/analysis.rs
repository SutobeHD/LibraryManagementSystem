use rustfft::{num_complex::Complex, FftPlanner};
use crate::audio::engine::AudioEngine;
use symphonia::core::audio::SampleBuffer;
use std::path::Path;

// Fixed 3-band frequency boundaries in Hz. Same convention as the Python
// analysis engine and the rust-index docs.
const BAND_LOW_HZ_MIN: f32  = 20.0;
const BAND_LOW_HZ_MAX: f32  = 250.0;
const BAND_MID_HZ_MAX: f32  = 4000.0;
const BAND_HIGH_HZ_MAX: f32 = 20000.0;

/// Map an audio frequency in Hz to the matching FFT bin index for the given
/// frame size and sample rate. Bin spacing is `sample_rate / frame_size`.
///
/// The result is clamped to `[0, frame_size / 2]` so it can be used as a
/// slice bound on the FFT output without ever indexing past Nyquist.
fn hz_to_bin(hz: f32, frame_size: usize, sample_rate: u32) -> usize {
    if sample_rate == 0 || frame_size == 0 {
        return 0;
    }
    let bin = (hz * frame_size as f32 / sample_rate as f32).round() as i64;
    bin.clamp(0, (frame_size / 2) as i64) as usize
}

pub fn compute_waveform<P: AsRef<Path>>(path: P) -> Result<Vec<u8>, String> {
    let (mut format, mut decoder, track_id, sample_rate) = AudioEngine::load_file(path)?;

    let mut planner = FftPlanner::new();
    // 1024 samples per frame
    let frame_size = 1024;
    let fft_plan = planner.plan_fft_forward(frame_size);

    // Precompute bin edges in Hz space — sample-rate-correct across 44.1k,
    // 48k, 96k, 192k, etc. The previous hardcoded `[1..10] / [10..100] /
    // [100..400]` ranges silently mapped to wildly different frequencies on
    // anything other than 44.1 kHz, so high-SR tracks looked all-mid.
    //
    // `.max()` chains keep band ordering valid even on pathologically low
    // sample rates where the upper bound falls below the lower bound.
    let low_start = hz_to_bin(BAND_LOW_HZ_MIN, frame_size, sample_rate).max(1);
    let low_end   = hz_to_bin(BAND_LOW_HZ_MAX, frame_size, sample_rate).max(low_start);
    let mid_end   = hz_to_bin(BAND_MID_HZ_MAX, frame_size, sample_rate).max(low_end);
    let high_end  = hz_to_bin(BAND_HIGH_HZ_MAX, frame_size, sample_rate).max(mid_end);

    let mut binary_payload = Vec::new();
    let mut sample_buf: Option<SampleBuffer<f32>> = None;
    let mut chunk_buffer = Vec::with_capacity(frame_size);

    loop {
        let packet = match format.next_packet() {
            Ok(p) => p,
            Err(_) => break, // Reached end of file
        };

        if packet.track_id() != track_id { continue; }

        match decoder.decode(&packet) {
            Ok(decoded) => {
                if sample_buf.is_none() {
                    sample_buf = Some(SampleBuffer::<f32>::new(decoded.capacity() as u64, *decoded.spec()));
                }

                if let Some(buf) = &mut sample_buf {
                    buf.copy_interleaved_ref(decoded);
                    for &sample in buf.samples() {
                        chunk_buffer.push(sample);

                        if chunk_buffer.len() == frame_size {
                            // Run FFT
                            let mut buffer: Vec<Complex<f32>> = chunk_buffer
                                .iter()
                                .map(|&x| Complex { re: x, im: 0.0 })
                                .collect();

                            fft_plan.process(&mut buffer);

                            // Compute Low / Mid / High band RMS energy using
                            // Hz-derived bin slices.
                            let low_energy  = calculate_energy(&buffer[low_start..low_end]);
                            let mid_energy  = calculate_energy(&buffer[low_end..mid_end]);
                            let high_energy = calculate_energy(&buffer[mid_end..high_end]);

                            // Compress into u8 (0-255) to save space
                            binary_payload.push((low_energy * 255.0).clamp(0.0, 255.0) as u8);
                            binary_payload.push((mid_energy * 255.0).clamp(0.0, 255.0) as u8);
                            binary_payload.push((high_energy * 255.0).clamp(0.0, 255.0) as u8);

                            chunk_buffer.clear();
                        }
                    }
                }
            }
            Err(_) => break, // EOF or fatal error
        }
    }

    Ok(binary_payload)
}

/// Simplified BPM Analysis using energy peaks
pub fn estimate_bpm(samples: &[f32], sample_rate: u32) -> f32 {
    let channels = 2; // Assuming stereo
    let window_size = (sample_rate as f32 * 0.05) as usize; // 50ms window
    let mut energies = Vec::new();

    for i in (0..samples.len()).step_by(window_size * channels) {
        let end = (i + window_size * channels).min(samples.len());
        let energy: f32 = samples[i..end].iter().map(|&x| x * x).sum();
        energies.push(energy);
    }

    // Identify peaks in energy
    let mut peaks = Vec::new();
    for i in 1..energies.len()-1 {
        if energies[i] > energies[i-1] && energies[i] > energies[i+1] {
            peaks.push(i);
        }
    }

    // Rough estimate of average peak distance
    if peaks.len() < 2 { return 120.0; }
    let mut sum_diff = 0;
    for i in 1..peaks.len() {
        sum_diff += peaks[i] - peaks[i-1];
    }
    let avg_diff_windows = sum_diff as f32 / (peaks.len() - 1) as f32;
    let avg_diff_seconds = avg_diff_windows * 0.05;
    
    let bpm = 60.0 / avg_diff_seconds;
    // Snap to sensible range
    if bpm < 60.0 { bpm * 2.0 } else if bpm > 180.0 { bpm / 2.0 } else { bpm }
}

/// Placeholder for Musical Key Analysis (e.g., Camelot)
pub fn detect_key(_samples: &[f32], _sample_rate: u32) -> String {
    // Real chroma-analysis would take more space. Returning a placeholder that mimics the API.
    "8A".to_string() // Camelot 8A (Am)
}

fn calculate_energy(slice: &[Complex<f32>]) -> f32 {
    if slice.is_empty() {
        return 0.0;
    }
    let sum: f32 = slice.iter().map(|c| c.norm_sqr()).sum();
    (sum / slice.len() as f32).sqrt() // RMS
}

#[cfg(test)]
mod tests {
    use super::hz_to_bin;

    #[test]
    fn hz_to_bin_maps_44k1() {
        // 44.1 kHz / 1024-sample frame → 43.07 Hz per bin
        assert_eq!(hz_to_bin(20.0, 1024, 44100), 0);
        assert_eq!(hz_to_bin(250.0, 1024, 44100), 6);
        assert_eq!(hz_to_bin(4000.0, 1024, 44100), 93);
        assert_eq!(hz_to_bin(20000.0, 1024, 44100), 464);
    }

    #[test]
    fn hz_to_bin_clamps_to_nyquist() {
        // Anything past Nyquist must clamp to frame_size / 2
        assert_eq!(hz_to_bin(30000.0, 1024, 44100), 512);
        assert_eq!(hz_to_bin(1_000_000.0, 1024, 44100), 512);
    }

    #[test]
    fn hz_to_bin_handles_zero_inputs() {
        assert_eq!(hz_to_bin(440.0, 1024, 0), 0);
        assert_eq!(hz_to_bin(440.0, 0, 44100), 0);
    }

    #[test]
    fn hz_to_bin_tracks_sample_rate() {
        // Same Hz should map to roughly half the bin index at double SR.
        let a = hz_to_bin(4000.0, 1024, 44100);
        let b = hz_to_bin(4000.0, 1024, 88200);
        assert!((a as i64 - 2 * b as i64).abs() <= 1);
    }
}
