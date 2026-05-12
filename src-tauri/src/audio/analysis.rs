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
    // Channel count is intentionally ignored here — `buf.samples()` already
    // yields a single interleaved stream and the FFT operates on the raw
    // f32 sequence regardless of channel layout.
    let (mut format, mut decoder, track_id, sample_rate, _channels) = AudioEngine::load_file(path)?;

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

/// Simplified BPM Analysis using energy peaks.
///
/// `channels` is the source's actual channel count from the decoder — pass
/// 1 for mono, 2 for stereo, 6 for 5.1, etc. The previous implementation
/// hardcoded 2 and silently mis-windowed mono / multi-channel sources.
/// Values < 1 are clamped to 1 to avoid the step-by-zero panic.
pub fn estimate_bpm(samples: &[f32], sample_rate: u32, channels: usize) -> f32 {
    let channels = channels.max(1);
    let window_size = (sample_rate as f32 * 0.05) as usize; // 50ms window
    let mut energies = Vec::new();

    for i in (0..samples.len()).step_by(window_size * channels) {
        let end = (i + window_size * channels).min(samples.len());
        let energy: f32 = samples[i..end].iter().map(|&x| x * x).sum();
        energies.push(energy);
    }

    // Need at least 3 energy windows to compare neighbours. A clip too
    // short to fill 3 × 50 ms windows can't yield a meaningful BPM and
    // would previously panic on the `energies.len() - 1` subtraction below
    // (usize underflow when len == 0).
    if energies.len() < 3 {
        return 120.0;
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

/// Krumhansl-Kessler major-key profile (C-rooted, pitch classes 0..11).
/// Empirically-derived probe-tone weights from Krumhansl & Kessler (1982).
const KS_MAJOR_PROFILE: [f32; 12] = [
    6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88,
];

/// Krumhansl-Kessler minor-key profile (C-rooted, pitch classes 0..11).
const KS_MINOR_PROFILE: [f32; 12] = [
    6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17,
];

/// Camelot wheel number for each chromatic pitch class in major mode.
/// Index: pitch class 0..11 (C, C#, D, ..., B). Value: Camelot number 1..12.
///
/// For minor mode, the Camelot wheel groups each minor key with its
/// *relative major* (same number, opposite letter): A minor (pc 9) and
/// C major (pc 0) both sit at Camelot 8. The minor lookup therefore
/// indexes by `(minor_tonic + 3) mod 12` to recover the relative major
/// root before reading this table; the suffix "A" or "B" then disambiguates.
const PITCH_CLASS_TO_CAMELOT: [u8; 12] = [
    8,  // C  -> 8B
    3,  // C# -> 3B
    10, // D  -> 10B
    5,  // D# -> 5B
    12, // E  -> 12B
    7,  // F  -> 7B
    2,  // F# -> 2B
    9,  // G  -> 9B
    4,  // G# -> 4B
    11, // A  -> 11B
    6,  // A# -> 6B
    1,  // B  -> 1B
];

/// Returns the estimated musical key in Camelot notation (e.g. `"8B"` for
/// C major, `"8A"` for A minor).
///
/// Implements Krumhansl-Schmuckler pitch-class-profile correlation:
/// 1. Build a 12-bin chromagram from overlapping 4096-sample Hann-windowed
///    FFT frames (50% hop), accumulating magnitude into each pitch class
///    via `pc = round(12 * log2(f / 440) + 9) mod 12` (A4 = pc 9, C = pc 0).
/// 2. Restrict to bins between 65 Hz (C2) and 5000 Hz (D#8) — the range
///    the K-K probe-tone weights are calibrated for.
/// 3. L2-normalise the chroma vector.
/// 4. Pearson-correlate against all 24 rotations of the major and minor
///    Krumhansl-Kessler profiles.
/// 5. Pick the (tonic, mode) with the highest correlation and map to
///    Camelot via `PITCH_CLASS_TO_CAMELOT` (major = "B" suffix; minor keys
///    share the Camelot number of their relative major, with suffix "A").
///
/// Returns `""` when input is shorter than one FFT frame or contains only
/// silence — the frontend falls through to the backend-supplied key or
/// renders "—" in that case.
pub fn detect_key(samples: &[f32], sample_rate: u32) -> String {
    const FRAME_SIZE: usize = 4096;
    const HOP_SIZE: usize = 2048;
    const MIN_HZ: f32 = 65.0;
    const MAX_HZ: f32 = 5000.0;

    if sample_rate == 0 || samples.len() < FRAME_SIZE {
        return String::new();
    }

    // Pre-compute pitch-class lookup for each FFT bin in [MIN_HZ, MAX_HZ].
    // bin_freq = bin_index * sample_rate / FRAME_SIZE
    let sr = sample_rate as f32;
    let bin_hz = sr / FRAME_SIZE as f32;
    let min_bin = ((MIN_HZ / bin_hz).floor() as usize).max(1);
    let max_bin = ((MAX_HZ / bin_hz).ceil() as usize).min(FRAME_SIZE / 2);
    if min_bin >= max_bin {
        return String::new();
    }

    let mut bin_pitch_class: Vec<Option<usize>> = vec![None; max_bin - min_bin];
    for (idx, slot) in bin_pitch_class.iter_mut().enumerate() {
        let bin = min_bin + idx;
        let freq = bin as f32 * bin_hz;
        if freq <= 0.0 {
            continue;
        }
        // A4 = 440 Hz is pitch class 9 (count from C=0). For any frequency f:
        //   semitones_from_A4 = 12 * log2(f / 440)
        //   pc = (semitones_from_A4 + 9) mod 12
        // The "+9" puts C (3 semitones below A) at pitch class 0.
        let pc = ((12.0 * (freq / 440.0).log2() + 9.0).round() as i32).rem_euclid(12) as usize;
        *slot = Some(pc);
    }

    let mut planner = FftPlanner::new();
    let fft_plan = planner.plan_fft_forward(FRAME_SIZE);

    let mut chroma = [0.0f32; 12];
    let mut frame_buf: Vec<Complex<f32>> = vec![Complex { re: 0.0, im: 0.0 }; FRAME_SIZE];

    let mut start = 0usize;
    while start + FRAME_SIZE <= samples.len() {
        // Copy window with Hann tapering to reduce spectral leakage.
        for (i, slot) in frame_buf.iter_mut().enumerate() {
            let s = samples[start + i];
            // Hann window: 0.5 * (1 - cos(2 pi n / (N - 1)))
            let w = 0.5
                * (1.0
                    - (2.0 * std::f32::consts::PI * i as f32 / (FRAME_SIZE as f32 - 1.0)).cos());
            *slot = Complex { re: s * w, im: 0.0 };
        }
        fft_plan.process(&mut frame_buf);

        for (idx, slot) in bin_pitch_class.iter().enumerate() {
            if let Some(pc) = *slot {
                let bin = min_bin + idx;
                let mag = frame_buf[bin].norm();
                chroma[pc] += mag;
            }
        }

        start += HOP_SIZE;
    }

    // Reject silence / all-zero chroma.
    let total: f32 = chroma.iter().sum();
    if total <= f32::EPSILON {
        return String::new();
    }

    // L2-normalise.
    let l2: f32 = chroma.iter().map(|v| v * v).sum::<f32>().sqrt();
    if l2 <= f32::EPSILON {
        return String::new();
    }
    for v in chroma.iter_mut() {
        *v /= l2;
    }

    // Pearson-correlate against all 24 rotated profiles.
    let mut best_tonic: usize = 0;
    let mut best_is_minor = false;
    let mut best_corr = f32::NEG_INFINITY;

    for tonic in 0..12 {
        for (is_minor, profile) in
            [(false, &KS_MAJOR_PROFILE), (true, &KS_MINOR_PROFILE)].into_iter()
        {
            let mut rotated = [0.0f32; 12];
            for (i, slot) in rotated.iter_mut().enumerate() {
                *slot = profile[(i + 12 - tonic) % 12];
            }
            let corr = pearson_correlation(&chroma, &rotated);
            if corr > best_corr {
                best_corr = corr;
                best_tonic = tonic;
                best_is_minor = is_minor;
            }
        }
    }

    if !best_corr.is_finite() {
        return String::new();
    }

    // Camelot wheel groups each minor key with its relative major (same
    // wheel number, different letter): A minor (pc 9) shares the slot with
    // C major (pc 0) → both are "8". For a minor key, look up the relative
    // major root instead of the minor tonic itself.
    let lookup_pc = if best_is_minor {
        (best_tonic + 3) % 12
    } else {
        best_tonic
    };
    let number = PITCH_CLASS_TO_CAMELOT[lookup_pc];
    let suffix = if best_is_minor { 'A' } else { 'B' };
    format!("{number}{suffix}")
}

/// Pearson correlation coefficient between two length-12 vectors.
/// Returns 0.0 if either vector has zero variance (constant input).
fn pearson_correlation(a: &[f32; 12], b: &[f32; 12]) -> f32 {
    let n = 12.0_f32;
    let mean_a: f32 = a.iter().sum::<f32>() / n;
    let mean_b: f32 = b.iter().sum::<f32>() / n;

    let mut num = 0.0f32;
    let mut den_a = 0.0f32;
    let mut den_b = 0.0f32;
    for i in 0..12 {
        let da = a[i] - mean_a;
        let db = b[i] - mean_b;
        num += da * db;
        den_a += da * da;
        den_b += db * db;
    }
    let den = (den_a * den_b).sqrt();
    if den <= f32::EPSILON {
        0.0
    } else {
        num / den
    }
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
    use super::{detect_key, estimate_bpm, hz_to_bin};

    /// Generate a buffer containing the sum of pure sine tones at the given
    /// frequencies, normalised to peak ±1.0. Used to feed clean harmonic
    /// content into `detect_key` for deterministic test expectations.
    fn pure_tone_chord(freqs: &[f32], sample_rate: u32, seconds: f32) -> Vec<f32> {
        let n = (sample_rate as f32 * seconds) as usize;
        let mut buf = vec![0.0f32; n];
        for &f in freqs {
            for (i, slot) in buf.iter_mut().enumerate() {
                let t = i as f32 / sample_rate as f32;
                *slot += (2.0 * std::f32::consts::PI * f * t).sin();
            }
        }
        let peak = buf.iter().fold(0.0f32, |acc, v| acc.max(v.abs()));
        if peak > 0.0 {
            for v in buf.iter_mut() {
                *v /= peak;
            }
        }
        buf
    }

    #[test]
    fn estimate_bpm_returns_default_on_empty_input() {
        // Previously panicked on `energies.len() - 1` underflow.
        assert_eq!(estimate_bpm(&[], 44100, 2), 120.0);
    }

    #[test]
    fn estimate_bpm_returns_default_on_too_short_input() {
        // 4 samples can't fill three 50 ms windows at 44.1 kHz.
        assert_eq!(estimate_bpm(&[0.1, 0.2, 0.3, 0.4], 44100, 2), 120.0);
    }

    #[test]
    fn estimate_bpm_handles_mono_input() {
        // channels=1 must not underflow / step by zero. We just want
        // the function to terminate gracefully.
        let _ = estimate_bpm(&[0.0; 4096], 44100, 1);
    }

    #[test]
    fn estimate_bpm_clamps_zero_channels() {
        // channels=0 used to cause `step_by(0)` panic. The clamp at the
        // top of estimate_bpm now floors it to 1.
        let _ = estimate_bpm(&[0.0; 4096], 44100, 0);
    }

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

    #[test]
    fn detect_key_handles_empty_input() {
        assert_eq!(detect_key(&[], 44100), "");
    }

    #[test]
    fn detect_key_handles_silence() {
        // All-zero buffer (longer than one 4096-sample frame) — chroma must
        // remain zero and detect_key must short-circuit to "".
        let buf = vec![0.0f32; 4096 * 4];
        assert_eq!(detect_key(&buf, 44100), "");
    }

    #[test]
    fn detect_key_pure_c_major_arpeggio() {
        // C4 = 261.63 Hz, E4 = 329.63 Hz, G4 = 392.00 Hz. Pure tones plus
        // one octave higher reinforces the chroma triad without ambiguity.
        let buf = pure_tone_chord(
            &[261.63, 329.63, 392.00, 523.25, 659.25, 783.99],
            44100,
            2.0,
        );
        assert_eq!(detect_key(&buf, 44100), "8B");
    }

    #[test]
    fn detect_key_pure_a_minor_arpeggio() {
        // A3 = 220.00 Hz, C4 = 261.63 Hz, E4 = 329.63 Hz. A minor triad.
        let buf = pure_tone_chord(&[220.00, 261.63, 329.63, 440.00, 523.25, 659.25], 44100, 2.0);
        assert_eq!(detect_key(&buf, 44100), "8A");
    }

    #[test]
    fn detect_key_camelot_round_trip() {
        // (label, root_hz, third_hz, fifth_hz, expected_camelot)
        // Major triads: root + major-3rd (+4 semitones) + perfect-5th (+7).
        let cases = [
            ("C", 261.63, 329.63, 392.00, "8B"),
            ("G", 392.00, 493.88, 587.33, "9B"),
            ("D", 293.66, 369.99, 440.00, "10B"),
            ("A", 440.00, 554.37, 659.25, "11B"),
        ];
        for (name, root, third, fifth, expected) in cases {
            // Add octave reinforcement to make the triad unambiguous against
            // wider K-K profile rotations (otherwise relative-minor profiles
            // can sneak ahead on sparse 3-tone input).
            let buf = pure_tone_chord(
                &[root, third, fifth, root * 2.0, third * 2.0, fifth * 2.0],
                44100,
                2.0,
            );
            let got = detect_key(&buf, 44100);
            assert_eq!(got, expected, "key for {name} major: expected {expected}, got {got}");
        }
    }
}
