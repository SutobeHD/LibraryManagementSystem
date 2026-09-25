import { useEffect, useRef } from 'react';
import { WAVEFORM_STYLE_PRESETS, DEFAULT_WAVEFORM_STYLE } from '../../config/constants';

// Owns the slave WaveSurfer instances that render the LOW/MID/HIGH bands, plus the RAF sync
// loop that keeps their scroll & time aligned with the master wavesurfer. Mode 'blue' tears
// them down and restores the master colours.
export default function useMultibandLayers({
    wavesurfer,
    waveLowRef,
    waveMidRef,
    waveHighRef,
    visualMode,
    visualStyle,
    multibandBuffers,
    zoom,
    trackBlobUrl,
}) {
    const wsLow = useRef(null);
    const wsMid = useRef(null);
    const wsHigh = useRef(null);

    // Manage Multi-Band Instances
    useEffect(() => {
        if (!wavesurfer.current) return;

        const cleanupSlaves = () => {
            // Revoke object URLs to avoid memory leaks?
            // Not strictly necessary as refs are destroyed, but good practice.
            wsLow.current?.destroy(); wsLow.current = null;
            wsMid.current?.destroy(); wsMid.current = null;
            wsHigh.current?.destroy(); wsHigh.current = null;
        };

        const initLayers = async () => {
            // If Blue Mode, cleanup slaves and restore Main
            if (visualMode === 'blue') {
                cleanupSlaves();
                wavesurfer.current.setOptions({
                    waveColor: 'rgba(59, 130, 246, 0.8)',
                    progressColor: 'rgba(59, 130, 246, 0.8)',
                    cursorColor: 'rgba(255, 255, 255, 0.5)'
                });
                return;
            }

            if (!multibandBuffers || !waveLowRef.current || !waveMidRef.current || !waveHighRef.current) return;

            // Always cleanup old slaves when switching modes (colors differ)
            cleanupSlaves();

            // Colours come from the active style preset (Rekordbox / Mixxx /
            // Traktor / RGB Mix). `visualMode` still chooses the layering
            // approach (stacked vs additive); the preset chooses the actual
            // RGB values used for each band. Falling back to Rekordbox keeps
            // existing callers safe.
            const stylePresetId = visualStyle || DEFAULT_WAVEFORM_STYLE;
            const stylePreset =
                WAVEFORM_STYLE_PRESETS[stylePresetId] ||
                WAVEFORM_STYLE_PRESETS[DEFAULT_WAVEFORM_STYLE];
            const colLow  = stylePreset.threeBand.low;
            const colMid  = stylePreset.threeBand.mid;
            const colHigh = stylePreset.threeBand.high;

            // Hide Main Waveform (keep interaction)
            wavesurfer.current.setOptions({
                waveColor: 'transparent',
                progressColor: 'transparent',
                cursorColor: 'rgba(255, 255, 255, 0.5)',
            });

            const WaveSurfer = (await import('wavesurfer.js')).default;

            const options = {
                height: 128,
                cursorColor: 'transparent',
                interact: false,
                hideScrollbar: true,
                minPxPerSec: zoom,
                autoScroll: false,
                autoCenter: false,
                fillParent: false,
                barWidth: undefined,
            };

            // Create fresh instances with correct colors
            wsLow.current = WaveSurfer.create({ ...options, container: waveLowRef.current, waveColor: colLow, progressColor: colLow });
            wsMid.current = WaveSurfer.create({ ...options, container: waveMidRef.current, waveColor: colMid, progressColor: colMid });
            wsHigh.current = WaveSurfer.create({ ...options, container: waveHighRef.current, waveColor: colHigh, progressColor: colHigh });

            // Load Blobs
            const loadBlob = (ws, blob) => {
                // Apply Zoom/Time once ready
                ws.once('ready', () => {
                    if (ws && !ws.isDestroyed) {
                        ws.zoom(zoom);
                        ws.setTime(wavesurfer.current.getCurrentTime());
                    }
                });
                const url = trackBlobUrl(URL.createObjectURL(blob));
                ws.load(url);
            };

            if (wsLow.current) loadBlob(wsLow.current, multibandBuffers.low);
            if (wsMid.current) loadBlob(wsMid.current, multibandBuffers.mid);
            if (wsHigh.current) loadBlob(wsHigh.current, multibandBuffers.high);

            // Initial Sync (Might be too early, but good backup)
            const t = wavesurfer.current.getCurrentTime();
            [wsLow, wsMid, wsHigh].forEach(ws => {
                if (ws.current) {
                    // ws.current.setTime(t); // Removed here, moved to ready
                    // ws.current.zoom(zoom);
                }
            });
        };

        initLayers();

        // ---------------------------------------------------------
        // FORCE SYNC LOOP (RAF) — only runs when needed
        // ---------------------------------------------------------
        // Only run sync loop when in multi-band mode AND playing (saves CPU)
        if (visualMode === 'blue') return;

        let rafId;
        let lastSyncTime = -1;
        let lastSyncScroll = -1;

        const loop = () => {
            if (wavesurfer.current && !wavesurfer.current.isDestroyed) {
                const master = wavesurfer.current;
                const wrapper = master.getWrapper();
                const scrollEl = wrapper?.parentElement;

                if (scrollEl && master.getDuration() > 0) {
                    const time = master.getCurrentTime();
                    const dur = master.getDuration();
                    const totalWidth = scrollEl.scrollWidth;
                    const containerWidth = scrollEl.clientWidth;

                    // Smooth centering only during playback (saves DOM writes when paused)
                    if (master.isPlaying()) {
                        const cursorPx = (time / dur) * totalWidth;
                        const targetScroll = cursorPx - containerWidth / 2;
                        scrollEl.scrollLeft = Math.max(0, Math.min(targetScroll, totalWidth - containerWidth));
                    }

                    const scroll = scrollEl.scrollLeft;

                    // Skip update if nothing changed (cheap noop check)
                    const timeChanged = Math.abs(time - lastSyncTime) > 0.01;
                    const scrollChanged = scroll !== lastSyncScroll;
                    if (timeChanged || scrollChanged) {
                        lastSyncTime = time;
                        lastSyncScroll = scroll;

                        // Sync Slaves
                        [wsLow, wsMid, wsHigh].forEach(ws => {
                            if (ws.current && !ws.current.isDestroyed) {
                                if (Math.abs(ws.current.getCurrentTime() - time) > 0.05) {
                                    ws.current.setTime(time);
                                }
                                const childWrapper = ws.current.getWrapper();
                                const childScroll = childWrapper?.parentElement;
                                if (childScroll && childScroll.scrollLeft !== scroll) {
                                    childScroll.scrollLeft = scroll;
                                }
                            }
                        });
                    }
                }
            }
            rafId = requestAnimationFrame(loop);
        };
        loop();

        return () => {
            if (rafId) cancelAnimationFrame(rafId);
        };
    }, [visualMode, visualStyle, multibandBuffers, zoom, wavesurfer, waveLowRef, waveMidRef, waveHighRef, trackBlobUrl]); // re-run on zoom or style to recalc widths + colours

    // Sync zoom to slaves when state changes
    useEffect(() => {
        [wsLow, wsMid, wsHigh].forEach(ws => {
            if (ws.current && !ws.current.isDestroyed) {
                ws.current.zoom(zoom);
            }
        });
    }, [zoom]);
}
