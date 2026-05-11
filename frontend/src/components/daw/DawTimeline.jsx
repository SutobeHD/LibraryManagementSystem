/**
 * DawTimeline — Layered Canvas Timeline with Path2D Smooth Waveform
 *
 * Architecture: 3 conceptual layers rendered to one canvas via OffscreenCanvas caching
 *
 *  Layer 0 [CACHED]  — Static waveform bitmap (OffscreenCanvas, only re-renders on data/zoom change)
 *  Layer 1 [LIVE]    — Grid, cues, loops, region boundaries, selection (redraws on interaction)
 *  Layer 2 [60FPS]   — Playhead + phase meter (always redraws, tiny cost)
 *
 * Waveform: Path2D smooth Bezier silhouette — upper & lower contours joined into filled shape.
 * Colors: CDJ-style 3-band vertical gradients (Low=Red, Mid=Green, High=Blue).
 *
 * This is a thin wrapper. The heavy lifting sits in three colocated hooks:
 *   - useTimelineLayout  — DPR + ResizeObserver wiring
 *   - useTimelineRender  — state-sync, RAF loop, bitmap cache, all draw functions
 *   - useTimelineEvents  — mouse + wheel handlers
 *
 * Phase Meter — 8px beat-phase indicator strip at canvas bottom
 * Gradient fills — vertical linear gradient per band
 * OffscreenCanvas — waveform cache invalidated by zoom/data key
 */

import React, { useRef } from 'react';
import { useTimelineLayout } from './timeline/useTimelineLayout';
import { useTimelineRender } from './timeline/useTimelineRender';
import { useTimelineEvents } from './timeline/useTimelineEvents';

// ─── COMPONENT ──────────────────────────────────────────────────────────────────

const DawTimeline = React.memo(({
    state,
    dispatch,
    canvasHeight = null, // null = fill container (preferred). Number = fixed pixel height
    minCanvasHeight = 200, // floor when filling container (avoid degenerate state during layout)
    onRegionClick,
    onContextMenu,
}) => {
    const canvasRef    = useRef(null);
    const containerRef = useRef(null);
    const goodFramesRef = useRef(0);

    // Mutable draw state — decoupled from React renders. Lives on a ref so
    // it survives across renders without retriggering the RAF loop.
    const ds = useRef({
        // height starts at minimum; resize observer takes over on mount.
        width: 0, height: canvasHeight ?? minCanvasHeight, dpr: window.devicePixelRatio || 1,
        zoom: 100, scrollX: 0, playhead: 0, isPlaying: false,
        regions: [], selectedIds: new Set(),
        bpm: 128, firstBeatSec: 0, totalDuration: 0,
        // CRITICAL: peaks are generated from the SOURCE AudioBuffer, so
        // peak-index calculations MUST use the source audio duration —
        // NOT `totalDuration`, which can be a longer/shorter edit timeline
        // in .rbep projects (regions rearrange / repeat the source). Mixing
        // the two yields a waveform whose samples are off by the ratio
        // `totalDuration / sourceDuration` (visual drift vs. playback).
        sourceDuration: 0,
        hotCues: [], memoryCues: [], loops: [], activeLoopIndex: -1,
        snapEnabled: true, snapDivision: '1/4', slipMode: false,
        selectionRange: null, bandPeaks: null, fallbackPeaks: null,
        waveformStyle: 'liquid',
        needsRedraw: true, needsWaveformRebuild: true,
        lastFrameTime: 0, lodLevel: 1,
        ghostCueX: null, deadReckoning: { lastSyncWallClock: 0, lastSyncAudioTime: 0 },
    });

    // Layout layer — owns ResizeObserver + DPR-aware canvas sizing.
    useTimelineLayout({ containerRef, canvasRef, ds, canvasHeight, minCanvasHeight });

    // Render layer — owns state-sync, RAF loop, draw functions.
    useTimelineRender({ state, dispatch, canvasRef, ds, goodFramesRef });

    // Event layer — returns DOM handlers attached below.
    const handlers = useTimelineEvents({ dispatch, canvasRef, ds, onContextMenu });

    // When canvasHeight is null → fill the parent (h-full); when it's a number,
    // pin to that exact pixel height for back-compat with fixed-height callers.
    const containerStyle = canvasHeight != null ? { height: canvasHeight } : undefined;
    const containerClass = canvasHeight != null
        ? 'relative w-full select-none'
        : 'relative w-full h-full select-none';

    return (
        <div ref={containerRef} className={containerClass} style={containerStyle}>
            <canvas
                ref={canvasRef}
                className='absolute inset-0 cursor-crosshair'
                onMouseDown={handlers.onMouseDown}
                onMouseMove={handlers.onMouseMove}
                onMouseUp={handlers.onMouseUp}
                onMouseLeave={handlers.onMouseUp}
                onWheel={handlers.onWheel}
                onContextMenu={(e) => e.preventDefault()}
            />
        </div>
    );
});

DawTimeline.displayName = 'DawTimeline';

export default DawTimeline;
