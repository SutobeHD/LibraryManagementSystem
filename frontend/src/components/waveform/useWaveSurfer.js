// Owns the master WaveSurfer + overview lifecycle: one fetch + one decode per track.
import { useCallback, useEffect, useRef } from 'react';
import api from '../../api/api';
import { log } from '../../utils/log';

// Overview strip resolution — wavesurfer's own exportPeaks() default; enough for a 4K-wide strip.
export const OVERVIEW_PEAK_COUNT = 8000;

export const streamUrlFor = (path) =>
    `${api.defaults.baseURL || ''}/api/stream?path=${encodeURIComponent(path)}`;

// Max |sample| per bucket, per channel. One pass over the decoded audio, no allocation per bucket
// (wavesurfer's exportPeaks() slices a copy for every bucket).
function computeOverviewPeaks(audioBuffer, count) {
    const peaks = [];
    const channels = Math.min(2, audioBuffer.numberOfChannels);
    for (let c = 0; c < channels; c++) {
        const data = audioBuffer.getChannelData(c);
        const out = new Float32Array(count);
        const bucket = data.length / count;
        for (let i = 0; i < count; i++) {
            const end = Math.min(data.length, Math.ceil((i + 1) * bucket));
            let max = 0;
            for (let j = Math.floor(i * bucket); j < end; j++) {
                const v = data[j] < 0 ? -data[j] : data[j];
                if (v > max) max = v;
            }
            out[i] = max;
        }
        peaks.push(out);
    }
    return peaks;
}

// Channel views of the decoded buffer for wavesurfer's renderer. Decoder.createBuffer() rescales
// IN PLACE when channel 0 leaves [-1, 1] (inter-sample overs of loud masters) — that would turn
// down the playback buffer, so hand it copies in that case.
function renderChannels(audioBuffer) {
    const channels = [];
    for (let c = 0; c < audioBuffer.numberOfChannels; c++)
        channels.push(audioBuffer.getChannelData(c));
    const first = channels[0];
    for (let i = 0; i < first.length; i++) {
        if (first[i] > 1 || first[i] < -1) return channels.map((ch) => ch.slice());
    }
    return channels;
}

// wavesurfer's WebAudio backend decodes every file twice: once in its WebAudioPlayer (playback)
// and once in Decoder.decode() (rendering). We decode once on the player's own AudioContext, render
// from those channels and hand the same AudioBuffer to the player. Relies on WebAudioPlayer's
// `audioContext` / `buffer` fields (wavesurfer.js 7.12.x, pinned) — when they are missing we fall
// back to the stock double-decoding load(url).
function canShareDecode(player) {
    return typeof player?.audioContext?.decodeAudioData === 'function' && 'buffer' in player;
}

// Owns the master WaveSurfer + Overview lifecycle:
//  - mount-once init (registers regions/timeline plugins, all event listeners)
//  - per-track load + state reset when fullTrack.path / blobUrl changes
//    (not the beat grid — WaveformEditor loads it per track id)
//  - playback sync when isPlaying / isPlayingExternal changes
//  - zoom sync (master WaveSurfer .zoom() on state change)
//
// Per track: ONE fetch + ONE decode. The overview is fed peaks derived from that decode instead of
// loading (fetching + decoding) the stream a second time.
//
// All cross-frame mutable state (loop refs, beats ref, isQuantized ref) is owned by the
// orchestrator and read through refs so the closure here stays stable.
export default function useWaveSurfer({
    wavesurfer,
    overviewWs,
    waveformRef,
    overviewRef,
    originalBufferRef,
    isMountedRef,
    isPlayingExternalRef,
    isQuantizedRef,
    beatsRef,
    loopInRef,
    loopOutRef,
    isLoopingRef,
    onPlayPauseRef,
    fullTrack,
    blobUrl,
    streaming,
    isVisible,
    simpleMode,
    zoom,
    isPlaying,
    isPlayingExternal,
    revokeAllBlobUrls,
    setDuration,
    setLoading,
    setBufferReady,
    setCurrentTime,
    setSelectionStart,
    setZoom,
    setInternalPlaying,
    setLoopIn,
    setLoopOut,
    setIsLooping,
    setCuts,
    setHotCues,
    setHistory,
    setHistoryIdx,
    setClipboard,
    toast,
}) {
    // { url, controller } of the load in flight / last loaded. Dedupes the init-time load against
    // the track-loading effect re-running for the same track (e.g. when isVisible flips).
    const activeLoadRef = useRef(null);
    // Current track URL for the async init to pick up (the track-loading effect may run before
    // WaveSurfer exists). Like the old init-time load it ignores isVisible.
    const pendingUrlRef = useRef(null);

    const loadTrackAudio = useCallback(
        async (url, signal) => {
            const ws = wavesurfer.current;
            const overview = overviewWs.current;
            if (!ws || !overview) return;
            const player = ws.getMediaElement();
            // Stop the previous track now — the fetch + decode below can take a while.
            if (ws.isPlaying()) ws.pause();

            // The overview has no audio source of its own, so nothing resets its progress on a new
            // track — align it with the master after loading the peaks.
            const feedOverview = async (decoded) => {
                await overview.load(
                    '',
                    computeOverviewPeaks(decoded, OVERVIEW_PEAK_COUNT),
                    decoded.duration
                );
                overview.setTime(ws.getCurrentTime());
            };

            if (!canShareDecode(player)) {
                try {
                    await ws.load(url);
                    if (signal.aborted) return;
                    await feedOverview(ws.getDecodedData());
                } catch (e) {
                    if (!signal.aborted) log.warn('[useWaveSurfer] stock load failed', e);
                }
                return;
            }

            let audioBuffer;
            try {
                const res = await fetch(url, { signal });
                if (!res.ok) throw new Error(`stream HTTP ${res.status}`);
                const arrayBuffer = await res.arrayBuffer();
                if (signal.aborted) return;
                audioBuffer = await player.audioContext.decodeAudioData(arrayBuffer);
            } catch (e) {
                if (signal.aborted || e?.name === 'AbortError') return;
                console.error('[useWaveSurfer] track load failed', e);
                if (isMountedRef.current) {
                    setLoading(false);
                    toast.error('Audio Error: ' + (e.message || e));
                }
                return;
            }
            if (signal.aborted || !isMountedRef.current || wavesurfer.current !== ws) return;

            originalBufferRef.current = audioBuffer;
            // 'decode' fires after load('') has emptied the player's source and before 'ready' (which
            // may auto-play), so the player gets its buffer exactly in between.
            ws.once('decode', () => {
                player.buffer = audioBuffer;
                player.currentTime = 0;
            });
            try {
                await ws.load('', renderChannels(audioBuffer), audioBuffer.duration);
            } catch (e) {
                // 'error' listener already toasts.
                log.debug('[useWaveSurfer] master load rejected', e);
                return;
            }
            if (signal.aborted || overviewWs.current !== overview) return;
            try {
                await feedOverview(audioBuffer);
            } catch (e) {
                log.warn('[useWaveSurfer] overview render failed', e);
            }
        },
        [wavesurfer, overviewWs, originalBufferRef, isMountedRef, setLoading, toast]
    );

    // Aborts the previous track's load. No-op when `url` is already loading / loaded.
    const startLoad = useCallback(
        (url) => {
            if (activeLoadRef.current?.url === url) return;
            activeLoadRef.current?.controller.abort();
            const controller = new AbortController();
            activeLoadRef.current = { url, controller };
            loadTrackAudio(url, controller.signal);
        },
        [loadTrackAudio]
    );

    // --- 1. Initialization Effect (Run Once or on strict teardown) ---
    useEffect(() => {
        const initWaveSurfer = async () => {
            const WaveSurfer = (await import('wavesurfer.js')).default;
            const RegionsPlugin = (await import('wavesurfer.js/dist/plugins/regions.esm.js'))
                .default;
            const TimelinePlugin = (await import('wavesurfer.js/dist/plugins/timeline.esm.js'))
                .default;

            if (!isMountedRef.current || wavesurfer.current) return; // Prevent double init
            if (streaming) return; // Don't init WS for streaming tracks

            // 1. Overview Waveform — peaks only, never loads audio itself
            overviewWs.current = WaveSurfer.create({
                container: overviewRef.current,
                waveColor: '#444',
                progressColor: '#ff9800',
                height: 48,
                interact: true,
                cursorWidth: 1,
                cursorColor: '#fff',
                plugins: [
                    TimelinePlugin.create({
                        container: overviewRef.current,
                        height: 10,
                        fontSize: 8,
                    }),
                ],
            });

            // 2. Detailed Waveform
            wavesurfer.current = WaveSurfer.create({
                container: waveformRef.current,
                waveColor: 'rgba(59, 130, 246, 0.8)',
                progressColor: 'rgba(59, 130, 246, 0.8)',
                cursorColor: '#00ccff',
                cursorWidth: 2,
                height: simpleMode ? 180 : 280,
                minPxPerSec: zoom,
                autoScroll: false,
                autoCenter: false,
                fillParent: false,
                hideScrollbar: true,
                normalize: true,
                backend: 'WebAudio',
            });

            // Initialize Plugins
            wavesurfer.current.registerPlugin(RegionsPlugin.create());
            overviewWs.current.registerPlugin(RegionsPlugin.create());

            // --- Event Listeners ---
            wavesurfer.current.on('ready', () => {
                if (!isMountedRef.current) return;
                setDuration(wavesurfer.current.getDuration());
                setLoading(false);
                // Check if we should auto-play (use ref to get current value, not stale closure)
                if (isPlayingExternalRef.current) {
                    wavesurfer.current.play().catch((e) => console.warn('Autoplay blocked:', e));
                }
                // The track loader stores the real AudioBuffer before load. Preview reloads
                // (spliced audio) fire 'ready' too and must not replace the original.
                if (!originalBufferRef.current)
                    originalBufferRef.current = wavesurfer.current.getDecodedData();
                if (originalBufferRef.current) setBufferReady(true);
            });

            // Throttled currentTime updates: ref every frame, state every ~100ms.
            // Avoids 60Hz re-renders of the entire component during playback.
            let lastStateUpdate = 0;
            wavesurfer.current.on('audioprocess', () => {
                if (!isMountedRef.current) return;
                const time = wavesurfer.current.getCurrentTime();

                // Throttled state update for visible time-display only
                const now = performance.now();
                if (now - lastStateUpdate > 100) {
                    lastStateUpdate = now;
                    setCurrentTime(time);
                }

                if (overviewWs.current && overviewWs.current.getDuration() > 0) {
                    const dur = wavesurfer.current.getDuration();
                    if (dur > 0) overviewWs.current.seekTo(time / dur);
                }

                // LOOP PLAYBACK LOGIC (every frame for accuracy)
                if (
                    isLoopingRef.current &&
                    loopInRef.current !== null &&
                    loopOutRef.current !== null
                ) {
                    if (time >= loopOutRef.current) {
                        wavesurfer.current.setTime(loopInRef.current);
                    }
                }
            });

            wavesurfer.current.on('zoom', (px) => {
                if (!isMountedRef.current) return;
                setZoom(px);
            });

            wavesurfer.current.on('interaction', () => {
                let time = wavesurfer.current.getCurrentTime();

                // Snap to Grid
                if (isQuantizedRef.current && beatsRef.current.length > 0) {
                    const b = beatsRef.current;
                    const nearest = b.reduce((prev, curr) =>
                        Math.abs(curr.time - time) < Math.abs(prev.time - time) ? curr : prev
                    );
                    // Only snap if within 0.2s to avoid jumping too far?
                    // Or hard snap? User asked for snap. Hard snap is better for "Beat Grids".
                    time = nearest.time;
                    wavesurfer.current.setTime(time);
                }

                setCurrentTime(time);
                setSelectionStart(time);
            });

            wavesurfer.current.on('error', (e) => {
                console.error('WaveSurfer Error:', e);
                toast.error('Audio Error: ' + (e.message || e));
            });

            // Notify parent of play/pause/finish state changes (needed by RankingView)
            wavesurfer.current.on('play', () => {
                if (!isMountedRef.current) return;
                setInternalPlaying(true);
                onPlayPauseRef.current?.(true);
            });
            wavesurfer.current.on('pause', () => {
                if (!isMountedRef.current) return;
                setInternalPlaying(false);
                onPlayPauseRef.current?.(false);
            });
            wavesurfer.current.on('finish', () => {
                if (!isMountedRef.current) return;
                setInternalPlaying(false);
                onPlayPauseRef.current?.(false);
            });

            // Sync Overview Clicks
            overviewWs.current.on('click', (rel) => {
                if (wavesurfer.current) wavesurfer.current.seekTo(rel);
            });

            // The track-loading effect ran before WaveSurfer existed — pick up its track now.
            if (pendingUrlRef.current) startLoad(pendingUrlRef.current);
        };

        initWaveSurfer();

        // Cleanup on Unmount
        return () => {
            activeLoadRef.current?.controller.abort();
            activeLoadRef.current = null;
            try {
                if (wavesurfer.current) {
                    wavesurfer.current.un('audioprocess');
                    wavesurfer.current.un('interaction');
                    wavesurfer.current.stop();
                    wavesurfer.current.destroy();
                }
                if (overviewWs.current) overviewWs.current.destroy();
            } catch (e) {
                console.warn('WaveSurfer cleanup error', e);
            }
            wavesurfer.current = null;
            overviewWs.current = null;
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []); // Run once on mount

    // --- 2. Track Loading Effect (Runs when track changes) ---
    useEffect(() => {
        const hasSource = !!(fullTrack?.path || blobUrl);
        const url = hasSource ? blobUrl || streamUrlFor(fullTrack.path) : null;
        pendingUrlRef.current = hasSource && !streaming ? url : null;

        if (!wavesurfer.current || !overviewWs.current) return;
        if (!hasSource) return;
        if (!isVisible) return;
        if (streaming) {
            setLoading(false);
            setBufferReady(false);
            return;
        }
        if (activeLoadRef.current?.url === url) return; // already loading / loaded

        setLoading(true);
        setBufferReady(false);
        originalBufferRef.current = null; // CRITICAL: reset stale buffer ref
        // Clear Regions/Cues from previous track
        const regions = wavesurfer.current.plugins.find((p) => p.getRegions);
        if (regions) regions.clearRegions();

        // Revoke blob URLs from previous track's preview rebuilds
        revokeAllBlobUrls();

        startLoad(url);

        // Reset State
        setLoopIn(null);
        setLoopOut(null);
        setIsLooping(false);
        setCuts([]);
        setHotCues([]);
        setHistory([]);
        setHistoryIdx(-1);
        setClipboard(null);
    }, [
        fullTrack?.path,
        blobUrl,
        streaming,
        isVisible,
        startLoad,
        revokeAllBlobUrls,
        wavesurfer,
        overviewWs,
        originalBufferRef,
        setLoading,
        setBufferReady,
        setLoopIn,
        setLoopOut,
        setIsLooping,
        setCuts,
        setHotCues,
        setHistory,
        setHistoryIdx,
        setClipboard,
    ]);

    // Master playback sync (used when isPlaying is local state)
    useEffect(() => {
        if (!wavesurfer.current || isPlaying === undefined) return;
        if (isPlaying && !wavesurfer.current.isPlaying()) {
            wavesurfer.current.play();
        } else if (!isPlaying && wavesurfer.current.isPlaying()) {
            wavesurfer.current.pause();
        }
    }, [isPlaying, wavesurfer]);

    // Sync zoom (master)
    useEffect(() => {
        if (wavesurfer.current) wavesurfer.current.zoom(zoom);
    }, [zoom, wavesurfer]);

    // Sync playback state with external prop (Ranking Mode)
    useEffect(() => {
        if (!wavesurfer.current) return;
        if (isPlayingExternal === true) {
            wavesurfer.current.play().catch(() => {});
        } else if (isPlayingExternal === false) {
            wavesurfer.current.pause();
        }
    }, [isPlayingExternal, wavesurfer]);
}
