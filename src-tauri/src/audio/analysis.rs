use rustfft::{num_complex::Complex, FftPlanner};
use crate::audio::engine::AudioEngine;
use symphonia::core::audio::{AudioBufferRef, Signal, SampleBuffer};
use std::path::Path;

pub fn compute_waveform<P: AsRef<Path>>(path: P) -> Result<Vec<u8>, String> {
    let (mut format, mut decoder, track_id, mut sample_rate) = AudioEngine::load_file(path)?;

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

fn calculate_energy(slice: &[Complex<f32>]) -> f32 {
    let sum: f32 = slice.iter().map(|c| c.norm_sqr()).sum();
    (sum / slice.len() as f32).sqrt() // RMS
}
