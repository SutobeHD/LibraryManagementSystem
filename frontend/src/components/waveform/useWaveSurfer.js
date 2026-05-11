import { useEffect } from 'react';

// Owns the master WaveSurfer + Overview lifecycle:
//  - mount-once init (registers regions/timeline plugins, all event listeners)
//  - per-track load + state reset when fullTrack.path / blobUrl changes
//  - playback sync when isPlaying / isPlayingExternal changes
//  - zoom sync (master WaveSurfer .zoom() on state change)
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
    setMultibandBuffers,
    setCurrentTime,
    setSelectionStart,
    setZoom,
    setInternalPlaying,
    setLoopIn,
    setLoopOut,
    setIsLooping,
    setCuts,
    setHotCues,
    setBeatGrid,
    setHistory,
    setHistoryIdx,
    setClipboard,
    toast,
}) {
    // --- 1. Initialization Effect (Run Once or on strict teardown) ---
    useEffect(() => {
        const initWaveSurfer = async () => {
            const WaveSurfer = (await import('wavesurfer.js')).default;
            const RegionsPlugin = (await import('wavesurfer.js/dist/plugins/regions.esm.js')).default;
            const TimelinePlugin = (await import('wavesurfer.js/dist/plugins/timeline.esm.js')).default;

            if (!isMountedRef.current || wavesurfer.current) return; // Prevent double init
            if (streaming) return; // Don't init WS for streaming tracks

            // 1. Overview Waveform
            overviewWs.current = WaveSurfer.create({
                container: overviewRef.current,
                waveColor: '#444',
                progressColor: '#ff9800',
                height: 48,
                interact: true,
                cursorWidth: 1,
                cursorColor: '#fff',
                plugins: [TimelinePlugin.create({ container: overviewRef.current, height: 10, fontSize: 8 })]
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
                backend: 'WebAudio'
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
                    wavesurfer.current.play().catch(e => console.warn('Autoplay blocked:', e));
                }
                // Capture Original Buffer + reset multiband state for new track
                const buffer = wavesurfer.current.getDecodedData();
                if (buffer) {
                    originalBufferRef.current = buffer;
                    setMultibandBuffers(null);
                    setBufferReady(true);
                }
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
                if (isLoopingRef.current && loopInRef.current !== null && loopOutRef.current !== null) {
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

            // Trigger initial load if track is already present (optimization for race conditions)
            if (fullTrack?.path || blobUrl) {
                const loadUrl = blobUrl || `/api/stream?path=${encodeURIComponent(fullTrack.path)}`;
                wavesurfer.current.load(loadUrl);
                overviewWs.current.load(loadUrl);
            }
        };

        initWaveSurfer();

        // Cleanup on Unmount
        return () => {
            try {
                if (wavesurfer.current) {
                    wavesurfer.current.un('audioprocess');
                    wavesurfer.current.un('interaction');
                    wavesurfer.current.stop();
                    wavesurfer.current.destroy();
                }
                if (overviewWs.current) overviewWs.current.destroy();
            } catch (e) { console.warn('WaveSurfer cleanup error', e); }
            wavesurfer.current = null;
            overviewWs.current = null;
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []); // Run once on mount

    // --- 2. Track Loading Effect (Runs when track changes) ---
    useEffect(() => {
        if (!wavesurfer.current || !overviewWs.current) return;
        if (!fullTrack?.path && !blobUrl) return;
        if (!isVisible) return;
        if (streaming) {
            setLoading(false);
            setBufferReady(false);
            return;
        }

        const url = blobUrl || `/api/stream?path=${encodeURIComponent(fullTrack.path)}`;

        // AbortController: if user switches tracks rapidly, abort the old load
        const controller = new AbortController();
        const signal = controller.signal;

        setLoading(true);
        setBufferReady(false);
        setMultibandBuffers(null);
        originalBufferRef.current = null; // CRITICAL: reset stale buffer ref
        // Clear Regions/Cues from previous track
        const regions = wavesurfer.current.plugins.find(p => p.getRegions);
        if (regions) regions.clearRegions();

        // Revoke blob URLs from previous track's preview rebuilds
        revokeAllBlobUrls();

        // Guard against races: only apply load if not aborted
        if (!signal.aborted) {
            wavesurfer.current.load(url);
            overviewWs.current.load(url);
        }

        // Reset State
        setLoopIn(null);
        setLoopOut(null);
        setIsLooping(false);
        setCuts([]);
        setHotCues([]);
        setBeatGrid([]);
        setHistory([]);
        setHistoryIdx(-1);
        setClipboard(null);

        return () => controller.abort();
    }, [fullTrack?.path, blobUrl, streaming, isVisible, revokeAllBlobUrls, wavesurfer, overviewWs, originalBufferRef, setLoading, setBufferReady, setMultibandBuffers, setLoopIn, setLoopOut, setIsLooping, setCuts, setHotCues, setBeatGrid, setHistory, setHistoryIdx, setClipboard]);

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
            wavesurfer.current.play().catch(() => { });
        } else if (isPlayingExternal === false) {
            wavesurfer.current.pause();
        }
    }, [isPlayingExternal, wavesurfer]);
}
