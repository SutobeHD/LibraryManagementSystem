use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc;
use std::thread;
use std::time::Duration;

use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use cpal::{OutputCallbackInfo, StreamError};
use ringbuf::{SharedRb, consumer::Consumer};

/// Audio output engine.
///
/// The `cpal::Stream` is `!Send` on Windows because it owns COM/WASAPI
/// handles (`IAudioClient`, `IAudioRenderClient`). Instead of asserting
/// `Send + Sync` manually with an `unsafe impl` (the historical
/// workaround), the Stream is now confined to a dedicated audio thread —
/// it is built, played and dropped inside that thread and never crosses
/// a thread boundary. Every field in this struct is `Send + Sync` on its
/// own, so the auto-derived bounds are correct and Tauri can store the
/// engine in `Mutex<AudioController>` safely.
pub struct PlaybackEngine {
    is_playing: Arc<AtomicBool>,
    audio_thread: Option<thread::JoinHandle<()>>,
    shutdown: Arc<AtomicBool>,
}

impl PlaybackEngine {
    pub fn new() -> Self {
        Self {
            is_playing: Arc::new(AtomicBool::new(false)),
            audio_thread: None,
            shutdown: Arc::new(AtomicBool::new(false)),
        }
    }

    /// Initializes the CPAL stream and returns the sample rate of the device.
    /// The consumer receives samples (f32) from the decoding thread.
    ///
    /// The actual `cpal::Stream` is built and driven on a dedicated audio
    /// thread; this function blocks only long enough for the spawned
    /// thread to report success or failure through a one-shot channel.
    pub fn start_stream(
        &mut self,
        consumer: Consumer<f32, Arc<SharedRb<f32, Vec<std::mem::MaybeUninit<f32>>>>>,
    ) -> Result<u32, String> {
        // Stop any previous audio thread before starting a new one.
        self.stop_audio_thread();

        // Query device config in the caller's thread — these handles are
        // short-lived and stay here; only the Stream itself must be
        // thread-confined.
        let host = cpal::default_host();
        let device = host
            .default_output_device()
            .ok_or("No default output device available")?;

        let config = device
            .default_output_config()
            .map_err(|e| format!("Failed to get default output config: {}", e))?;

        let sample_rate = config.sample_rate().0;

        // Fresh shutdown flag for this stream session.
        self.shutdown = Arc::new(AtomicBool::new(false));
        let shutdown = Arc::clone(&self.shutdown);

        let is_playing = Arc::clone(&self.is_playing);
        is_playing.store(true, Ordering::SeqCst);
        let is_playing_cb = Arc::clone(&is_playing);

        // One-shot init handshake — the spawned thread reports whether
        // stream construction + `play()` succeeded.
        let (init_tx, init_rx) = mpsc::channel::<Result<(), String>>();

        let stream_config: cpal::StreamConfig = config.clone().into();
        let sample_format = config.sample_format();

        let handle = thread::Builder::new()
            .name("audio-output".to_string())
            .spawn(move || {
                let mut consumer = consumer;

                let err_fn = |err: StreamError| {
                    // Req 1: Device Disconnects
                    log::error!("an error occurred on stream: {}", err);
                    // In a full implementation, we would emit an event to Tauri here.
                };

                // We only support f32 natively for simplicity, which is what
                // Symphonia can output. Other sample formats are rejected.
                let build_result = match sample_format {
                    cpal::SampleFormat::F32 => device.build_output_stream(
                        &stream_config,
                        move |data: &mut [f32], _: &OutputCallbackInfo| {
                            if !is_playing_cb.load(Ordering::SeqCst) {
                                data.fill(0.0);
                                return;
                            }

                            // Pull from ring buffer (Req 8).
                            let read = consumer.pop_slice(data);

                            // Req 2: Buffer Underruns (pad with zeros if underrun)
                            if read < data.len() {
                                data[read..].fill(0.0);
                            }
                        },
                        err_fn,
                        None,
                    ),
                    _ => Err(cpal::BuildStreamError::StreamConfigNotSupported),
                };

                let stream = match build_result {
                    Ok(s) => s,
                    Err(e) => {
                        let _ = init_tx.send(Err(format!("Failed to build output stream: {}", e)));
                        return;
                    }
                };

                if let Err(e) = stream.play() {
                    let _ = init_tx.send(Err(format!("Failed to play stream: {}", e)));
                    return;
                }

                // Init succeeded — unblock the caller.
                let _ = init_tx.send(Ok(()));

                // Keep the Stream alive on this thread until shutdown is
                // requested. Dropping `stream` at the end of scope pauses
                // and releases the underlying WASAPI / device handles.
                while !shutdown.load(Ordering::SeqCst) {
                    thread::sleep(Duration::from_millis(100));
                }

                drop(stream);
            })
            .map_err(|e| format!("Failed to spawn audio thread: {}", e))?;

        // Block until the audio thread reports init success or failure.
        match init_rx.recv() {
            Ok(Ok(())) => {
                self.audio_thread = Some(handle);
                Ok(sample_rate)
            }
            Ok(Err(e)) => {
                // Thread reported a build/play error and exited; join it.
                let _ = handle.join();
                Err(e)
            }
            Err(_) => {
                // Thread panicked before sending — join to clean up.
                let _ = handle.join();
                Err("Audio thread terminated before initialisation".to_string())
            }
        }
    }

    pub fn pause(&self) {
        self.is_playing.store(false, Ordering::SeqCst);
    }

    pub fn resume(&self) {
        self.is_playing.store(true, Ordering::SeqCst);
    }

    /// Signal the audio thread to stop and join it.
    fn stop_audio_thread(&mut self) {
        if let Some(handle) = self.audio_thread.take() {
            self.shutdown.store(true, Ordering::SeqCst);
            let _ = handle.join();
        }
    }
}

// Req 7: Zombie Threads — automatically stop the audio thread on drop.
// Dropping the Stream inside the spawned thread pauses the WASAPI device.
impl Drop for PlaybackEngine {
    fn drop(&mut self) {
        self.stop_audio_thread();
    }
}
