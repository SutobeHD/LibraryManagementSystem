use std::sync::Arc;
use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use cpal::{Stream, OutputCallbackInfo, StreamError};
use ringbuf::{SharedRb, consumer::Consumer};
use std::sync::atomic::{AtomicBool, Ordering};

pub struct PlaybackEngine {
    stream: Option<Stream>,
    is_playing: Arc<AtomicBool>,
}

// SAFETY: `cpal::Stream` is `!Send` and `!Sync` on Windows because it owns
// COM/WASAPI handles (`IAudioClient`, `IAudioRenderClient`) that are
// apartment-bound at the COM ABI level. We assert `Send` + `Sync` manually
// because Tauri's command state — `Mutex<AudioController>` — requires
// `AudioController: Send`, and `AudioController` owns this struct.
//
// This is sound IN PRACTICE because:
//
// 1. CPAL's Windows backend initialises COM in MTA mode (`COINIT_MULTITHREADED`),
//    so the COM interfaces inside the Stream are callable from any thread.
// 2. Every mutating access goes through `Mutex<AudioController>` in
//    `src-tauri/src/audio/commands.rs`, serialising callers.
// 3. The only cross-thread use of the Stream's internals is CPAL's own audio
//    callback closure, which CPAL spawns + synchronises itself; nothing else
//    reaches into its captured state.
//
// This is STRUCTURALLY FRAGILE — a future CPAL backend with thread-bound
// state (e.g. an STA COM apartment, or some platforms' `AudioUnit`) would
// silently turn this into UB. The correct long-term fix is to confine the
// `Stream` to a dedicated audio thread and communicate via channels /
// `AtomicBool`, dropping the `unsafe impl` entirely.
//
// TODO(audio-thread-refactor): spawn a dedicated OS thread that owns the
// Stream; expose only `Send + Sync` control signals from `PlaybackEngine`.
// Tracked in docs/HANDOVER.md Phase 1.9.
unsafe impl Send for PlaybackEngine {}
unsafe impl Sync for PlaybackEngine {}

impl PlaybackEngine {
    pub fn new() -> Self {
        Self {
            stream: None,
            is_playing: Arc::new(AtomicBool::new(false)),
        }
    }

    /// Initializes the CPAL stream and returns the sample rate of the device.
    /// The consumer receives samples (f32) from the decoding thread.
    pub fn start_stream(
        &mut self,
        mut consumer: Consumer<f32, Arc<SharedRb<f32, Vec<std::mem::MaybeUninit<f32>>>>>,
    ) -> Result<u32, String> {
        let host = cpal::default_host();
        let device = host
            .default_output_device()
            .ok_or("No default output device available")?;

        let config = device
            .default_output_config()
            .map_err(|e| format!("Failed to get default output config: {}", e))?;

        let sample_rate = config.sample_rate().0;
        let channels = config.channels() as usize;

        let is_playing = Arc::clone(&self.is_playing);
        is_playing.store(true, Ordering::SeqCst);

        let err_fn = |err: StreamError| {
            // Req 1: Device Disconnects
            eprintln!("an error occurred on stream: {}", err);
            // In a full implementation, we would emit an event to Tauri here.
        };

        // We only support f32 natively for simplicity, which is what Symphonia can output.
        // We'll write to the output buffer directly.
        let stream = match config.sample_format() {
            cpal::SampleFormat::F32 => device.build_output_stream(
                &config.into(),
                move |data: &mut [f32], _: &OutputCallbackInfo| {
                    if !is_playing.load(Ordering::SeqCst) {
                        data.fill(0.0);
                        return;
                    }
                    
                    // Pull from ring buffer (Req 8).
                    let read = consumer.pop_slice(data);
                    
                    // Req 2: Buffer Underruns (pad with zeros if underrun)
                    if read < data.len() {
                        data[read..].fill(0.0);
                        // Optional: Log underrun to console for debugging
                    }
                },
                err_fn,
                None,
            ),
            _ => Err(cpal::BuildStreamError::StreamConfigNotSupported), // Skip handling i16/u16 for brevity in prototype, though easy to add
        }.map_err(|e| format!("Failed to build output stream: {}", e))?;

        stream.play().map_err(|e| format!("Failed to play stream: {}", e))?;
        self.stream = Some(stream);

        Ok(sample_rate)
    }

    pub fn pause(&self) {
        self.is_playing.store(false, Ordering::SeqCst);
    }

    pub fn resume(&self) {
        self.is_playing.store(true, Ordering::SeqCst);
    }
}

// Req 7: Zombie Threads - automatically stop stream on drop
impl Drop for PlaybackEngine {
    fn drop(&mut self) {
        if let Some(stream) = self.stream.take() {
            let _ = stream.pause();
        }
    }
}
