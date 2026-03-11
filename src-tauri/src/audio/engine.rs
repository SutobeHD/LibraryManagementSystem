use std::fs::File;
use std::io::Cursor;
use std::path::Path;
use std::sync::Arc;

use memmap2::MmapOptions;
use symphonia::core::codecs::{Decoder, DecoderOptions};
use symphonia::core::errors::Error as SymphoniaError;
use symphonia::core::formats::{FormatOptions, FormatReader};
use symphonia::core::io::MediaSourceStream;
use symphonia::core::meta::MetadataOptions;
use symphonia::core::probe::Hint;

pub struct AudioEngine {
    // We'll store the decoder and format reader here later
    // For now, this struct represents the core audio processing
}

impl AudioEngine {
    pub fn new() -> Self {
        AudioEngine {}
    }

    /// Load and decode an audio file using memory mapping.
    pub fn load_file<P: AsRef<Path>>(path: P) -> Result<(Box<dyn FormatReader>, Box<dyn Decoder>, u32, u32), String> {
        let file_path = path.as_ref();
        
        // 1. Open the file
        let file = File::open(file_path).map_err(|e| format!("Failed to open file (Permissions/Exists): {}", e))?;
        
        // 2. Memory map the file for zero-copy loading (Req 3)
        // Safety: Mmap represents a live view of the file. It is generally safe unless
        // another process truncates the file while we are reading it.
        let mmap = unsafe { 
            MmapOptions::new()
                .map(&file)
                .map_err(|e| format!("Failed to mmap file: {}", e))? 
        };
        
        // 3. Wrap mmap in a Cursor to satisfy Read + Seek
        // We use Arc to enable easy sharing or keeping the mmap alive if needed,
        // but MediaSourceStream takes ownership of the source. Symphonia expects a `MediaSource`.
        // A cursor over an owned `mmap` works if we wrap it properly. Since `mmap` derefs to `[u8]`,
        // `Cursor<Mmap>` implements Read and Seek!
        let cursor = Cursor::new(mmap);
        let mss = MediaSourceStream::new(Box::new(cursor), Default::default());

        // 4. Probe the media format
        let mut hint = Hint::new();
        if let Some(ext) = file_path.extension().and_then(|e| e.to_str()) {
            hint.with_extension(ext);
        }

        let meta_opts: MetadataOptions = Default::default();
        let fmt_opts: FormatOptions = Default::default();

        let probed = symphonia::default::get_probe()
            .format(&hint, mss, &fmt_opts, &meta_opts)
            .map_err(|e| format!("Failed to probe format: {}", e))?;

        let format = probed.format;

        // 5. Find the first audio track
        let track = format
            .tracks()
            .iter()
            .find(|t| t.codec_params.codec != symphonia::core::codecs::CODEC_TYPE_NULL)
            .ok_or_else(|| "No supported audio track found".to_string())?;

        let track_id = track.id;
        let sample_rate = track.codec_params.sample_rate.unwrap_or(44100);

        let dec_opts: DecoderOptions = Default::default();
        let decoder = symphonia::default::get_codecs()
            .make(&track.codec_params, &dec_opts)
            .map_err(|e| format!("Failed to create decoder: {}", e))?;

        Ok((format, decoder, track_id, sample_rate))
    }
}

use crate::audio::playback::PlaybackEngine;
use ringbuf::HeapRb;
use std::thread;
use std::sync::atomic::{AtomicBool, Ordering};

pub struct AudioController {
    playback: PlaybackEngine,
    stop_signal: Arc<AtomicBool>,
}

impl AudioController {
    pub fn default() -> Self {
        Self {
            playback: PlaybackEngine::new(),
            stop_signal: Arc::new(AtomicBool::new(false)),
        }
    }

    pub fn load_and_play<P: AsRef<Path>>(&mut self, path: P) -> Result<(), String> {
        // Stop any ongoing playback
        self.stop_signal.store(true, Ordering::SeqCst);
        self.playback.pause();

        let (mut format, mut decoder, track_id, sample_rate) = AudioEngine::load_file(path)?;

        // Create ringbuffer for holding 1 second of audio (e.g. 44100 * 2 channels)
        // Adjust for stereo
        let capacity = (sample_rate * 2) as usize; 
        let rb = HeapRb::<f32>::new(capacity);
        let (mut producer, consumer) = rb.split();

        // Start playback pulling from the consumer
        let device_sr = self.playback.start_stream(consumer)?;

        // Inform decoder about potential sample rate mismatch (Req 5 placeholder/log)
        if sample_rate != device_sr {
            println!("Warning: File SR {} != Device SR {}. Resampling needed.", sample_rate, device_sr);
            // We should use rubato here, but sticking to basic decode loop for now.
        }

        self.stop_signal = Arc::new(AtomicBool::new(false));
        let stop_signal = Arc::clone(&self.stop_signal);

        // Spawn decoder thread (Req 8)
        thread::spawn(move || {
            use symphonia::core::audio::SampleBuffer;
            // Default 2 channels, f32
            let mut sample_buf: Option<SampleBuffer<f32>> = None;
            
            loop {
                if stop_signal.load(Ordering::SeqCst) {
                    break; // User requested stop or new file loaded
                }

                // If ring buffer is mostly full, wait a bit to avoid crackl/spin (Req 9)
                if producer.len() > producer.capacity() - 4096 {
                    thread::sleep(std::time::Duration::from_millis(5));
                    continue;
                }

                let packet = match format.next_packet() {
                    Ok(p) => p,
                    Err(SymphoniaError::IoError(e)) if e.kind() == std::io::ErrorKind::UnexpectedEof => {
                        println!("End of stream reached.");
                        break;
                    }
                    Err(e) => {
                        eprintln!("Decoding error: {}", e);
                        break;
                    }
                };

                if packet.track_id() != track_id { continue; }

                match decoder.decode(&packet) {
                    Ok(decoded) => {
                        // Setup sample buffer if not instantiated
                        if sample_buf.is_none() {
                            let spec = *decoded.spec();
                            let duration = decoded.capacity() as u64;
                            sample_buf = Some(SampleBuffer::<f32>::new(duration, spec));
                        }

                        if let Some(buf) = &mut sample_buf {
                            buf.copy_interleaved_ref(decoded);
                            let samples = buf.samples();
                            // Push samples into ringbuf
                            let mut written = 0;
                            while written < samples.len() {
                                let pushed = producer.push_slice(&samples[written..]);
                                written += pushed;
                                if pushed == 0 {
                                    // Ringbuf full, back off
                                    if stop_signal.load(Ordering::SeqCst) { break; }
                                    thread::sleep(std::time::Duration::from_millis(2));
                                }
                            }
                        }
                    }
                    Err(e) => {
                        eprintln!("Decode error: {}", e);
                    }
                }
            }
        });

        Ok(())
    }

    /// Flushes the audio stream and jumps to a specific timestamp (Req 6)
    pub fn seek(&self, position_secs: f64) {
        // To implement seek fully we would need to pass a message to the decoder thread 
        // to call format.seek(). For now, we will just pause the engine.
        // In a true implementation, we'd use a crossbeam channel to instruct the background thread.
        self.playback.pause();
        println!("Seek requested to {}s. (Decoder IPC not fully wired in prototype)", position_secs);
        self.playback.resume();
    }
}

