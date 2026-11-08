import { useEffect, useRef } from 'react';
import { log } from '../../utils/log';

// RGB: strong but not neon — screen blending brightens them. 3Band: classic Rekordbox
// Blue (Low) + Amber (Mid) + White (High).
const BAND_COLORS = {
    rgb: {
        low: 'rgba(210, 0, 0, 1.0)',
        mid: 'rgba(0, 190, 0, 1.0)',
        high: 'rgba(0, 80, 255, 1.0)',
    },
    '3band': {
        low: 'rgba(0, 100, 255, 1.0)',
        mid: 'rgba(255, 160, 0, 1.0)',
        high: 'rgba(255, 255, 255, 1.0)',
    },
};

const MASTER_VISIBLE = {
    waveColor: 'rgba(59, 130, 246, 0.8)',
    progressColor: 'rgba(59, 130, 246, 0.8)',
    cursorColor: 'rgba(255, 255, 255, 0.5)',
};
// Master stays on top for interaction + cursor, its own waveform is hidden under the bands.
const MASTER_HIDDEN = {
    waveColor: 'transparent',
    progressColor: 'transparent',
    cursorColor: 'rgba(255, 255, 255, 0.5)',
};

const SLAVE_OPTIONS = {
    height: 128,
    cursorColor: 'transparent',
    interact: false,
    hideScrollbar: true,
    autoScroll: false,
    autoCenter: false,
    fillParent: false,
    barWidth: undefined,
};

// Owns the slave WaveSurfer instances that render the LOW/MID/HIGH bands, plus the RAF sync
// loop that keeps their scroll & time aligned with the master wavesurfer.
//
// `bandPeaks` = { low, mid, high: Float32Array, duration } — precomputed envelopes (backend
// /api/audio/waveform). Slaves render them directly via load('', peaks, duration): no audio
// fetch, no decode. While peaks are pending the slaves are torn down (no stale bands from the
// previous track); with `bandsUnavailable` (or mode 'blue') the master shows its own waveform.
export default function useMultibandLayers({
    wavesurfer,
    waveLowRef,
    waveMidRef,
    waveHighRef,
    visualMode,
    bandPeaks,
    bandsUnavailable,
    zoom,
}) {
    const wsLow = useRef(null);
    const wsMid = useRef(null);
    const wsHigh = useRef(null);
    const masterHiddenRef = useRef(false);
    const zoomRef = useRef(zoom);

    // Sync zoom to slaves when state changes (declared first so zoomRef is fresh below)
    useEffect(() => {
        zoomRef.current = zoom;
        [wsLow, wsMid, wsHigh].forEach((ws) => {
            if (ws.current && !ws.current.isDestroyed && ws.current.getDecodedData()) {
                ws.current.zoom(zoom);
            }
        });
    }, [zoom]);

    useEffect(() => {
        const master = wavesurfer.current;
        if (!master) return;

        const cleanupSlaves = () => {
            wsLow.current?.destroy();
            wsLow.current = null;
            wsMid.current?.destroy();
            wsMid.current = null;
            wsHigh.current?.destroy();
            wsHigh.current = null;
        };
        // setOptions() re-renders the whole master waveform — only call it on an actual change.
        const setMasterHidden = (hidden) => {
            if (masterHiddenRef.current === hidden) return;
            masterHiddenRef.current = hidden;
            master.setOptions(hidden ? MASTER_HIDDEN : MASTER_VISIBLE);
        };

        const colors = BAND_COLORS[visualMode];
        if (!colors || bandsUnavailable) {
            cleanupSlaves();
            setMasterHidden(false);
            return;
        }
        if (!bandPeaks || !waveLowRef.current || !waveMidRef.current || !waveHighRef.current) {
            cleanupSlaves();
            return;
        }

        let cancelled = false;
        let rafId = null;

        const initLayers = async () => {
            const WaveSurfer = (await import('wavesurfer.js')).default;
            if (cancelled || master.isDestroyed) return;
            cleanupSlaves();
            setMasterHidden(true);

            const make = (container, color, peaks) => {
                const ws = WaveSurfer.create({
                    ...SLAVE_OPTIONS,
                    minPxPerSec: zoomRef.current,
                    container,
                    waveColor: color,
                    progressColor: color,
                });
                ws.once('ready', () => {
                    if (!ws.isDestroyed && wavesurfer.current)
                        ws.setTime(wavesurfer.current.getCurrentTime());
                });
                ws.load('', [peaks], bandPeaks.duration).catch((e) =>
                    log.warn('[useMultibandLayers] band render failed', e)
                );
                return ws;
            };
            wsLow.current = make(waveLowRef.current, colors.low, bandPeaks.low);
            wsMid.current = make(waveMidRef.current, colors.mid, bandPeaks.mid);
            wsHigh.current = make(waveHighRef.current, colors.high, bandPeaks.high);

            // FORCE SYNC LOOP (RAF) — keeps slave time + scroll locked to the master
            let lastSyncTime = -1;
            let lastSyncScroll = -1;
            const loop = () => {
                if (cancelled) return;
                if (wavesurfer.current && !wavesurfer.current.isDestroyed) {
                    const m = wavesurfer.current;
                    const scrollEl = m.getWrapper()?.parentElement;

                    if (scrollEl && m.getDuration() > 0) {
                        const time = m.getCurrentTime();
                        const dur = m.getDuration();
                        const totalWidth = scrollEl.scrollWidth;
                        const containerWidth = scrollEl.clientWidth;

                        // Smooth centering only during playback (saves DOM writes when paused)
                        if (m.isPlaying()) {
                            const cursorPx = (time / dur) * totalWidth;
                            const targetScroll = cursorPx - containerWidth / 2;
                            scrollEl.scrollLeft = Math.max(
                                0,
                                Math.min(targetScroll, totalWidth - containerWidth)
                            );
                        }

                        const scroll = scrollEl.scrollLeft;

                        // Skip update if nothing changed (cheap noop check)
                        const timeChanged = Math.abs(time - lastSyncTime) > 0.01;
                        const scrollChanged = scroll !== lastSyncScroll;
                        if (timeChanged || scrollChanged) {
                            lastSyncTime = time;
                            lastSyncScroll = scroll;

                            [wsLow, wsMid, wsHigh].forEach((ws) => {
                                if (ws.current && !ws.current.isDestroyed) {
                                    if (Math.abs(ws.current.getCurrentTime() - time) > 0.05) {
                                        ws.current.setTime(time);
                                    }
                                    const childScroll = ws.current.getWrapper()?.parentElement;
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
        };

        initLayers();

        return () => {
            cancelled = true;
            if (rafId) cancelAnimationFrame(rafId);
            cleanupSlaves();
        };
    }, [visualMode, bandPeaks, bandsUnavailable, wavesurfer, waveLowRef, waveMidRef, waveHighRef]);
}
