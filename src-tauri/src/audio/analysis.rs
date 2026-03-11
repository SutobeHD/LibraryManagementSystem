use rustfft::{num_complex::Complex, FftPlanner};
use crate::audio::engine::AudioEngine;
use symphonia::core::audio::SampleBuffer;
use std::path::Path;

pub fn compute_waveform<P: AsRef<Path>>(path: P) -> Result<Vec<u8>, String> {
    let (mut format, mut decoder, track_id, _sample_rate) = AudioEngine::load_file(path)?;

    let mut planner = FftPlanner::new();
    // 1024 samples per frame
    let frame_size = 1024;
    let fft_plan = planner.plan_fft_forward(frame_size);

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
                            
                            // Compute Low, Mid, High band RMS/Energy
                            let low_energy = calculate_energy(&buffer[1..10]);
                            let mid_energy = calculate_energy(&buffer[10..100]);
                            let high_energy = calculate_energy(&buffer[100..400]);

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
    let sum: f32 = slice.iter().map(|c| c.norm_sqr()).sum();
    (sum / slice.len() as f32).sqrt() // RMS
}
