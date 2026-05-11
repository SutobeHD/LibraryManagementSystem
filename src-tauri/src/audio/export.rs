use serde::{Deserialize, Serialize};

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct Fade {
    pub start: f32, // Fade start time relative to the region (in seconds)
    pub end: f32,   // Fade end time relative to the region (in seconds)
    pub shape: String, // e.g., "linear", "exponential"
}

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct AudioRegion {
    pub id: String,
    pub start: f32,        // Start of the region in the source file (seconds)
    pub end: f32,          // End of the region in the source file (seconds)
    pub track_start: f32,  // Where this region is placed on the timeline (seconds)
    pub track_end: f32,    // Where this region ends on the timeline (seconds)
    pub gain: f32,         // Gain applied to this specific region (multiplier)
    pub fade_in: Option<Fade>,
    pub fade_out: Option<Fade>,
}

#[derive(Debug, Deserialize, Serialize, Clone)]
pub struct ProjectState {
    pub source_file: String, // Absolute path to the original audio file
    pub output_file: String, // Absolute path to the desired output file
    pub regions: Vec<AudioRegion>,
    pub master_gain: f32,
    pub normalize: bool,
}

use crate::audio::engine::AudioEngine;
use symphonia::core::audio::SampleBuffer;

pub fn render_project<F>(state: ProjectState, progress: F) -> Result<String, String> 
where F: Fn(f32, &str) {
    progress(0.05, "Decoding source file...");
    // 1. Decode original file into memory (f32)
    let (mut format, mut decoder, track_id, sample_rate) = AudioEngine::load_file(&state.source_file)?;
    
    // We will decode the ENTIRE source file into a single massive float buffer first.
    // (Optimization for future: stream only needed chunks. But for DJ mixes, full decode is fine thanks to mmap)
    let mut source_samples: Vec<f32> = Vec::new();
    let mut sample_buf: Option<SampleBuffer<f32>> = None;

    loop {
        let packet = match format.next_packet() {
            Ok(p) => p,
            Err(_) => break, // EOF
        };
        if packet.track_id() != track_id { continue; }
        
        if let Ok(decoded) = decoder.decode(&packet) {
            if sample_buf.is_none() {
                sample_buf = Some(SampleBuffer::<f32>::new(decoded.capacity() as u64, *decoded.spec()));
            }
            if let Some(buf) = &mut sample_buf {
                buf.copy_interleaved_ref(decoded);
                source_samples.extend_from_slice(buf.samples());
            }
        }
    }

    // Default to stereo = 2
    let channels = 2;

    progress(0.40, "Preparing timeline...");
    // 2. Calculate the total timeline length based on regions.
    //
    // `track_end` is clamped to >= 0 per region so a stray negative value
    // (e.g. uninitialised f32 ending up at -0.0 after a transform) can't
    // pull the whole timeline negative. We then check finiteness once and
    // do the f32→usize cast through `i64` + `usize::try_from` so an
    // attacker-controlled or runaway project state can't crash the
    // exporter with a UB cast on 32-bit hosts.
    let max_timeline_end = state.regions
        .iter()
        .map(|r| r.track_end.max(0.0))
        .fold(0.0_f32, f32::max);

    if !max_timeline_end.is_finite() {
        return Err(format!(
            "timeline contains non-finite track_end: {}", max_timeline_end,
        ));
    }

    // f64 for the multiplication so we don't lose precision on long
    // (>>16.7 M sample) timelines.
    let total_samples_f = (max_timeline_end as f64)
        * (sample_rate as f64)
        * (channels as f64);
    let total_samples = usize::try_from(total_samples_f.round() as i64)
        .map_err(|_| format!(
            "total_samples out of usize range: {} (max_timeline_end={}, sample_rate={}, channels={})",
            total_samples_f, max_timeline_end, sample_rate, channels,
        ))?;

    // 3. Create the 32-bit mixing buffer initialized to silence
    let mut mix_buffer: Vec<f32> = vec![0.0; total_samples];

    // 4. Apply Regions & Fades
    progress(0.50, "Mixing regions...");
    for region in &state.regions {
        // Validate region bounds upfront. A region with `end <= start` or
        // non-finite times would later cause a usize underflow on
        // `re_samples - rs_samples` and crash the export. Refuse it
        // explicitly so the caller can fix the timeline state.
        if !region.start.is_finite()
            || !region.end.is_finite()
            || !region.track_start.is_finite()
            || region.start < 0.0
            || region.track_start < 0.0
            || region.end <= region.start
        {
            return Err(format!(
                "invalid region {:?}: start={} end={} track_start={}",
                region.id, region.start, region.end, region.track_start,
            ));
        }

        let rs_samples = (region.start * sample_rate as f32) as usize * channels;
        let re_samples = (region.end * sample_rate as f32) as usize * channels;
        let ts_samples = (region.track_start * sample_rate as f32) as usize * channels;

        // `saturating_sub` for all three legs — even with the up-front
        // validation, `rs_samples > source_samples.len()` is possible when
        // a region points past the end of the decoded source, and we'd
        // rather silently clip the slice than panic on usize underflow.
        let slice_len = [
            re_samples.saturating_sub(rs_samples),
            mix_buffer.len().saturating_sub(ts_samples),
            source_samples.len().saturating_sub(rs_samples),
        ]
        .into_iter()
        .min()
        .unwrap_or(0);

        let fade_in_samples = region.fade_in.as_ref().map_or(0, |f| (f.end * sample_rate as f32) as usize * channels);
        let fade_out_samples = region.fade_out.as_ref().map_or(0, |f| (f.end * sample_rate as f32) as usize * channels);

        for i in (0..slice_len).step_by(channels) {
            let mut region_gain = region.gain;

            // Apply Fade In
            if i < fade_in_samples && fade_in_samples > 0 {
                region_gain *= i as f32 / fade_in_samples as f32; // Linear fade
            }

            // Apply Fade Out
            if slice_len > fade_out_samples && i > slice_len - fade_out_samples {
                let fade_pos = slice_len - i;
                region_gain *= fade_pos as f32 / fade_out_samples as f32; // Linear fade
            }

            // Add to timeline
            let t_idx = ts_samples + i;
            let s_idx = rs_samples + i;
            
            for ch in 0..channels {
                if t_idx + ch < mix_buffer.len() && s_idx + ch < source_samples.len() {
                    mix_buffer[t_idx + ch] += source_samples[s_idx + ch] * region_gain;
                }
            }
        }
    }

    // 5. Normalization (Req 5)
    if state.normalize {
        progress(0.70, "Normalizing audio...");
        let max_peak = mix_buffer.iter().map(|s| s.abs()).fold(0.0_f32, f32::max);
        if max_peak > 0.0 {
            let headroom = 0.98; // -0.17 dBFS
            let scale = headroom / max_peak;
            for sample in &mut mix_buffer {
                *sample *= scale;
            }
        }
    }

    // 6. Master Gain
    for sample in &mut mix_buffer {
        *sample *= state.master_gain;
    }

    // 7. WAV Encoding (Hound)
    let spec = hound::WavSpec {
        channels: channels as u16,
        sample_rate: sample_rate,
        bits_per_sample: 32,
        sample_format: hound::SampleFormat::Float,
    };

    let mut writer = hound::WavWriter::create(&state.output_file, spec)
        .map_err(|e| format!("WAV write error: {}", e))?;

    let total_len = mix_buffer.len();
    for (i, sample) in mix_buffer.into_iter().enumerate() {
        if i % 100000 == 0 {
            let p = 0.80 + (i as f32 / total_len as f32) * 0.15;
            progress(p, "Encoding WAV...");
        }
        // hard-clipping prevention
        let clamped = sample.clamp(-1.0, 1.0);
        writer.write_sample(clamped).map_err(|e| format!("Sample write: {}", e))?;
    }
    writer.finalize().map_err(|e| format!("WAV finalize: {}", e))?;

    // 8. Metadata Injection (Req 2)
    progress(0.98, "Injecting metadata...");
    if let Err(e) = crate::audio::metadata::copy_metadata(&state.source_file, &state.output_file) {
        eprintln!("Metadata injection failed: {}", e);
        // We don't fail the whole export if just metadata fails, but we log it
    }

    progress(1.0, "Export complete.");
    Ok(format!("Exported tightly to {}", state.output_file))
}
