/**
 * WaveformOverview — Full-track mini-map with draggable viewport window
 *
 * Renders a downsampled mono/3-band waveform of the entire track via WaveformMiniCanvas.
 * Shows the currently visible portion as a semi-transparent viewport window.
 * Clicking/dragging pans the main timeline by dispatching SET_SCROLL_X.
 *
 * Performance: the minimap canvas redraws only on data / viewport change.
 * The playhead line is a separate overlay subscribed to the live playhead
 * store, so playback ticks move one div instead of repainting the peaks.
 */

import React, { useRef, useCallback, useEffect } from 'react';
import WaveformMiniCanvas from '../shared/WaveformMiniCanvas';
import { usePlayheadTime } from './usePlayheadClock';

const OVERVIEW_HEIGHT = 44;
// Same look as WaveformMiniCanvas' own playhead stroke.
const OVERVIEW_PLAYHEAD_COLOR = 'rgba(255,255,255,0.95)';
const OVERVIEW_PLAYHEAD_WIDTH_PX = 1.5;

const OverviewPlayhead = React.memo(({ playheadStore, totalDuration }) => {
    const playhead = usePlayheadTime(playheadStore);
    if (!(totalDuration > 0) || playhead < 0) return null;
    return (
        <div
            className="absolute top-0 bottom-0 pointer-events-none"
            style={{
                left: `${(playhead / totalDuration) * 100}%`,
                width: OVERVIEW_PLAYHEAD_WIDTH_PX,
                background: OVERVIEW_PLAYHEAD_COLOR,
            }}
        />
    );
});

OverviewPlayhead.displayName = 'OverviewPlayhead';

// `view` = the sliced reducer fields this component draws — never the
// whole DAW state, so React.memo holds during playback.
const WaveformOverview = React.memo(({ playheadStore, dispatch, ...view }) => {
    const containerRef = useRef(null);
    const isDragging = useRef(false);

    const { fallbackPeaks, bandPeaks, totalDuration, zoom, scrollX } = view;

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
    const timeFromClientX = useCallback(
        (clientX) => {
            const container = containerRef.current;
            if (!container || totalDuration <= 0) return 0;
            const rect = container.getBoundingClientRect();
            const relX = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
            return relX * totalDuration;
        },
        [totalDuration]
    );

    const scrollToTime = useCallback(
        (centerTimeSec) => {
            const container = containerRef.current;
            if (!container) return;
            const w = container.clientWidth;
            const secondsVisible = w / zoom;
            const newScrollX = centerTimeSec * zoom - (secondsVisible / 2) * zoom;
            dispatch({ type: 'SET_SCROLL_X', payload: Math.max(0, newScrollX) });
        },
        [zoom, dispatch]
    );

    const handleClick = useCallback(
        (e) => {
            const clickTime = timeFromClientX(e.clientX);
            // Scroll viewport AND move playhead so the middle timeline stays in sync
            dispatch({ type: 'SET_PLAYHEAD', payload: clickTime });
            scrollToTime(clickTime);
        },
        [timeFromClientX, scrollToTime, dispatch]
    );

    const handleMouseDown = useCallback(
        (e) => {
            e.preventDefault();
            isDragging.current = true;
            const clickTime = timeFromClientX(e.clientX);
            dispatch({ type: 'SET_PLAYHEAD', payload: clickTime });
            scrollToTime(clickTime);
        },
        [timeFromClientX, scrollToTime, dispatch]
    );

    const handleMouseMove = useCallback(
        (e) => {
            if (!isDragging.current) return;
            e.preventDefault();
            const clickTime = timeFromClientX(e.clientX);
            dispatch({ type: 'SET_PLAYHEAD', payload: clickTime });
            scrollToTime(clickTime);
        },
        [timeFromClientX, scrollToTime, dispatch]
    );

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

    // No track — render nothing (the timeline area shows its own "No Project
    // Loaded" empty state; an empty overview band just looks broken).
    if (!totalDuration || totalDuration <= 0) {
        return null;
    }

    return (
        <div
            ref={containerRef}
            className="w-full shrink-0 relative select-none overflow-hidden"
            style={{
                height: OVERVIEW_HEIGHT,
                borderBottom: '1px solid rgba(255,255,255,0.06)',
                cursor: 'crosshair',
            }}
            onMouseDown={handleMouseDown}
        >
            <WaveformMiniCanvas
                peaks={fallbackPeaks}
                bandPeaks={bandPeaks}
                totalDuration={totalDuration}
                playhead={null}
                viewportStart={viewportStart}
                viewportEnd={viewportEnd}
                height={OVERVIEW_HEIGHT}
                className="absolute inset-0"
            />
            <OverviewPlayhead playheadStore={playheadStore} totalDuration={totalDuration} />
            {/* Label */}
            <div className="absolute left-2 top-0.5 text-[8px] text-ink-placeholder font-bold uppercase tracking-widest pointer-events-none select-none z-10">
                OVERVIEW
            </div>
        </div>
    );
});

WaveformOverview.displayName = 'WaveformOverview';

export default WaveformOverview;
