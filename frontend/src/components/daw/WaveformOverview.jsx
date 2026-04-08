/**
 * WaveformOverview — Full-track mini-map with draggable viewport window
 *
 * Renders a downsampled mono/3-band waveform of the entire track via WaveformMiniCanvas.
 * Shows the currently visible portion as a semi-transparent viewport window.
 * Clicking/dragging pans the main timeline by dispatching SET_SCROLL_X.
 *
 * Performance: redraws only on data change (no RAF loop needed).
 */

import React, { useRef, useCallback, useEffect } from 'react';
import WaveformMiniCanvas from '../shared/WaveformMiniCanvas';

const OVERVIEW_HEIGHT = 44;

const WaveformOverview = React.memo(({ state, dispatch }) => {
    const containerRef = useRef(null);
    const isDragging = useRef(false);

    const {
        fallbackPeaks,
        bandPeaks,
        totalDuration,
        zoom,
        scrollX,
        playhead,
    } = state;

    // ── Viewport window calculation ────────────────────────────────────────────
    // Convert scroll/zoom from DAW pixel space to time-space for WaveformMiniCanvas
    const getViewportTimes = useCallback(() => {
        const container = containerRef.current;
        if (!container || totalDuration <= 0) return { start: null, end: null };
        const w = container.clientWidth;
        const secondsVisible = w / zoom;
        const viewStartSec = scrollX / zoom;
        const viewEndSec = viewStartSec + secondsVisible;
        return { start: viewStartSec, end: viewEndSec };
    }, [zoom, scrollX, totalDuration]);

    const { start: viewportStart, end: viewportEnd } = getViewportTimes();

    // ── Click/drag → scroll main timeline ─────────────────────────────────────
    const timeFromClientX = useCallback((clientX) => {
        const container = containerRef.current;
        if (!container || totalDuration <= 0) return 0;
        const rect = container.getBoundingClientRect();
        const relX = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
        return relX * totalDuration;
    }, [totalDuration]);

    const scrollToTime = useCallback((centerTimeSec) => {
        const container = containerRef.current;
        if (!container) return;
        const w = container.clientWidth;
        const secondsVisible = w / zoom;
        const newScrollX = centerTimeSec * zoom - (secondsVisible / 2) * zoom;
        dispatch({ type: 'SET_SCROLL_X', payload: Math.max(0, newScrollX) });
    }, [zoom, dispatch]);

    const handleClick = useCallback((e) => {
        const clickTime = timeFromClientX(e.clientX);
        // Scroll viewport AND move playhead so the middle timeline stays in sync
        dispatch({ type: 'SET_PLAYHEAD', payload: clickTime });
        scrollToTime(clickTime);
    }, [timeFromClientX, scrollToTime, dispatch]);

    const handleMouseDown = useCallback((e) => {
        e.preventDefault();
        isDragging.current = true;
        const clickTime = timeFromClientX(e.clientX);
        dispatch({ type: 'SET_PLAYHEAD', payload: clickTime });
        scrollToTime(clickTime);
    }, [timeFromClientX, scrollToTime, dispatch]);

    const handleMouseMove = useCallback((e) => {
        if (!isDragging.current) return;
        e.preventDefault();
        const clickTime = timeFromClientX(e.clientX);
        dispatch({ type: 'SET_PLAYHEAD', payload: clickTime });
        scrollToTime(clickTime);
    }, [timeFromClientX, scrollToTime, dispatch]);

    const handleMouseUp = useCallback(() => {
        isDragging.current = false;
    }, []);

    useEffect(() => {
        window.addEventListener('mousemove', handleMouseMove);
        window.addEventListener('mouseup', handleMouseUp);
        return () => {
            window.removeEventListener('mousemove', handleMouseMove);
            window.removeEventListener('mouseup', handleMouseUp);
        };
    }, [handleMouseMove, handleMouseUp]);

    // No track — show placeholder
    if (!totalDuration || totalDuration <= 0) {
        return (
            <div
                className="w-full shrink-0 flex items-center justify-center"
                style={{ height: OVERVIEW_HEIGHT, background: '#080b14', borderBottom: '1px solid rgba(255,255,255,0.05)' }}
            >
                <span className="text-[9px] text-slate-600 uppercase tracking-widest font-bold">Overview — No Track Loaded</span>
            </div>
        );
    }

    return (
        <div
            ref={containerRef}
            className="w-full shrink-0 relative select-none overflow-hidden"
            style={{ height: OVERVIEW_HEIGHT, borderBottom: '1px solid rgba(255,255,255,0.06)', cursor: 'crosshair' }}
            onMouseDown={handleMouseDown}
        >
            <WaveformMiniCanvas
                peaks={fallbackPeaks}
                bandPeaks={bandPeaks}
                totalDuration={totalDuration}
                playhead={playhead}
                viewportStart={viewportStart}
                viewportEnd={viewportEnd}
                height={OVERVIEW_HEIGHT}
                className="absolute inset-0"
            />
            {/* Label */}
            <div className="absolute left-2 top-0.5 text-[8px] text-slate-600 font-bold uppercase tracking-widest pointer-events-none select-none z-10">
                OVERVIEW
            </div>
        </div>
    );
});

WaveformOverview.displayName = 'WaveformOverview';

export default WaveformOverview;
