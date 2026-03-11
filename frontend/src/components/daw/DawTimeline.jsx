/**
 * DawTimeline — High-performance Canvas-based timeline for the DJ Edit DAW
 * 
 * Renders multiple layers on a single canvas using requestAnimationFrame:
 * 1. Grid Layer (beat lines, bar lines, phrase markers)
 * 2. Waveform Layer (3-Band RGB)
 * 3. Cue & Loop Layer (hot cues, memory cues, loops)
 * 4. Region boundaries
 * 5. Selection highlight
 * 6. Playhead
 * 
 * Performance: All drawing state is stored in refs, decoupled from React renders.
 */

import React, { useRef, useEffect, useCallback, useMemo } from 'react';
import AudioBandAnalyzer from '../../utils/AudioBandAnalyzer';
import { snapToGrid } from '../../audio/DawState';

// ─── COLORS ────────────────────────────────────────────────────────────────────

const RULER_HEIGHT = 22;

const COLORS = {
    background: '#0c0f1a',
    rulerBg: '#0a0d16',
    rulerText: 'rgba(255,255,255,0.5)',
    rulerLine: 'rgba(255,255,255,0.1)',
    gridBar: 'rgba(239, 68, 68, 0.4)',     // Red for Bar Start (Rekordbox style)
    gridBeat: 'rgba(255, 255, 255, 0.1)',  // Subtler white for beats
    gridSub: 'rgba(255, 255, 255, 0.03)',
    phraseMarker: '#F87171',               // Reddish for 16-bar phrase
    phraseLabel: 'rgba(248, 113, 113, 0.9)',
    playhead: '#ffffff',
    playheadGlow: 'rgba(255,255,255,0.3)',
    selectionFill: 'rgba(56, 189, 248, 0.12)',
    selectionBorder: 'rgba(56, 189, 248, 0.5)',
    regionBorder: 'rgba(255,255,255,0.15)',
    regionSelectedBorder: '#38bdf8',
    lowBand: 'rgba(0, 153, 255, 0.85)',    // Blue
    midBand: 'rgba(255, 153, 0, 0.85)',    // Orange
    highBand: 'rgba(255, 255, 255, 0.85)', // White
    cueLine: '#22c55e',
    memoryCue: '#ef4444',
    loopFill: 'rgba(251, 146, 60, 0.12)',
    loopBorder: 'rgba(251, 146, 60, 0.6)',
};

// ─── PEAK CACHE ────────────────────────────────────────────────────────────────

/** Cached band peaks at different zoom levels (LOD) */
const peakCacheMap = new Map();

function getPeakCacheKey(bufferId, samplesPerPixel) {
    return `${bufferId}-${samplesPerPixel}`;
}

// ─── COMPONENT ─────────────────────────────────────────────────────────────────

const DawTimeline = React.memo(({
    state,
    dispatch,
    canvasHeight = 280,
    onRegionClick,
    onTimelineClick,
    onContextMenu,
}) => {
    const canvasRef = useRef(null);
    const containerRef = useRef(null);
    const animFrameRef = useRef(null);
    const resizeObserverRef = useRef(null);
    const isDragging = useRef(false);
    const dragStartTime = useRef(0);

    // Mutable drawing state (decoupled from React)
    const drawState = useRef({
        width: 0,
        height: canvasHeight,
        dpr: window.devicePixelRatio || 1,
        zoom: 100,
        scrollX: -20, // Initial margin
        playhead: 0,
        isPlaying: false,
        regions: [],
        selectedIds: new Set(),
        bpm: 128,
        firstBeatSec: 0,
        totalDuration: 0,
        hotCues: [],
        memoryCues: [],
        loops: [],
        activeLoopIndex: -1,
        snapEnabled: true,
        snapDivision: '1/4',
        slipMode: false,
        selectionRange: null,
        bandPeaks: null,
        fallbackPeaks: null,
        needsRedraw: true,
        lastFrameTime: 0,
        frameCount: 0,
        lodLevel: 1,  // 1 = full detail, 2 = half, 4 = quarter
    });

    // Sync React state → mutable draw state
    useEffect(() => {
        const ds = drawState.current;
        ds.zoom = state.zoom;
        ds.scrollX = state.scrollX;
        ds.playhead = state.playhead;
        ds.isPlaying = state.isPlaying;
        ds.regions = state.regions;
        ds.selectedIds = state.selectedRegionIds;
        // Grid
        ds.bpm = state.bpm;
        ds.snapDivision = state.snapDivision;
        ds.gridOffsetSec = state.gridOffsetSec;
        ds.firstBeatSec = ((state.tempoMap?.[0]?.positionMs || 0) / 1000) + (state.gridOffsetSec || 0);
        ds.totalDuration = state.totalDuration;
        ds.hotCues = state.hotCues;
        ds.memoryCues = state.memoryCues;
        ds.loops = state.loops;
        ds.activeLoopIndex = state.activeLoopIndex;
        ds.snapEnabled = state.snapEnabled;
        ds.snapDivision = state.snapDivision || '1/4';
        ds.slipMode = state.slipMode || false;
        ds.waveformStyle = state.waveformStyle || 'detail';
        ds.selectionRange = state.selectionRange;
        ds.bandPeaks = state.bandPeaks;
        ds.fallbackPeaks = state.fallbackPeaks || null;
        ds.needsRedraw = true;
    }, [state]);

    // ── RESIZE HANDLER ──
    useEffect(() => {
        const container = containerRef.current;
        if (!container) return;

        const handleResize = () => {
            const rect = container.getBoundingClientRect();
            const ds = drawState.current;
            ds.width = rect.width;
            ds.height = canvasHeight;
            ds.dpr = window.devicePixelRatio || 1;

            const canvas = canvasRef.current;
            if (canvas) {
                canvas.width = ds.width * ds.dpr;
                canvas.height = ds.height * ds.dpr;
                canvas.style.width = `${ds.width}px`;
                canvas.style.height = `${ds.height}px`;
            }
            ds.needsRedraw = true;
        };

        resizeObserverRef.current = new ResizeObserver(handleResize);
        resizeObserverRef.current.observe(container);
        handleResize();

        return () => {
            resizeObserverRef.current?.disconnect();
        };
    }, [canvasHeight]);

    // ── MAIN RENDER LOOP ──
    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;
        const ctx = canvas.getContext('2d');

        const renderFrame = (timestamp) => {
            const ds = drawState.current;

            // LOD: Measure frame time
            if (ds.lastFrameTime > 0) {
                const delta = timestamp - ds.lastFrameTime;
                if (delta > 20) { // Below 50fps
                    ds.lodLevel = Math.min(4, ds.lodLevel + 1);
                } else if (delta < 14 && ds.lodLevel > 1) {
                    ds.lodLevel = Math.max(1, ds.lodLevel - 1);
                }
            }
            ds.lastFrameTime = timestamp;

            // Only redraw when needed (or during playback)
            if (ds.needsRedraw || ds.isPlaying) {
                drawTimeline(ctx, ds);
                ds.needsRedraw = false;
            }

            animFrameRef.current = requestAnimationFrame(renderFrame);
        };

        animFrameRef.current = requestAnimationFrame(renderFrame);

        return () => {
            if (animFrameRef.current) {
                cancelAnimationFrame(animFrameRef.current);
            }
        };
    }, []);

    // ── MOUSE HANDLERS ──
    const handleMouseDown = useCallback((e) => {
        const canvas = canvasRef.current;
        if (!canvas) return;

        const rect = canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        const ds = drawState.current;

        // Convert pixel to time
        let time = (x + ds.scrollX) / ds.zoom;

        // Grid snap on click
        if (ds.snapEnabled && !ds.slipMode && ds.bpm > 0) {
            time = snapToGrid(time, ds.bpm, ds.snapDivision, ds.firstBeatSec);
        }

        if (e.button === 0) {
            // Always set playhead to where user clicked
            dispatch({ type: 'SET_PLAYHEAD', payload: Math.max(0, time) });

            // Clear previous region selection to avoid "blacking out" everything
            // dispatch({ type: 'CLEAR_SELECTION' }); 
            // Note: If user wants to multiselect, use Shift/Ctrl. simplified for now.

            // Start drag for selection range
            isDragging.current = true;
            dragStartTime.current = time;

            // Check for region click
            // Find region under mouse
            // Note: Render order is usually start to end, but for hit test we might want top-most (if overlapping)
            // For now, find first match
            const clickedRegion = ds.regions.find(r => {
                const rx = (r.timelineStart * ds.zoom) - ds.scrollX;
                const rw = r.duration * ds.zoom;
                // Simple hit test (assuming single track for now or handling y in future)
                // Since this is a single timeline canvas, we check if x is within region horizontal bounds
                return x >= rx && x <= rx + rw;
            });

            if (clickedRegion) {
                if (e.ctrlKey) {
                    dispatch({ type: 'TOGGLE_SELECT_REGION', payload: clickedRegion.id });
                } else {
                    dispatch({ type: 'SELECT_REGION', payload: clickedRegion.id });
                }
            } else {
                // Clicked empty space
                if (!e.ctrlKey) {
                    dispatch({ type: 'SET_SELECTION_RANGE', payload: { start: time, end: time } });
                    // Only clear region selection if we are strictly creating a new range
                    dispatch({ type: 'CLEAR_SELECTION' });
                }
            }

            // Set selection start (always update playhead/range start)
            if (!clickedRegion) {
                dispatch({ type: 'SET_SELECTION_RANGE', payload: { start: time, end: time } });
            }
        } else if (e.button === 2) {
            if (onContextMenu) onContextMenu(time, e);
        }
    }, [dispatch, onRegionClick, onTimelineClick, onContextMenu]);

    const handleMouseMove = useCallback((e) => {
        if (!isDragging.current) return;
        const canvas = canvasRef.current;
        if (!canvas) return;

        const rect = canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const ds = drawState.current;
        let time = (x + ds.scrollX) / ds.zoom;

        // Grid snap on drag
        if (ds.snapEnabled && !ds.slipMode && ds.bpm > 0) {
            time = snapToGrid(time, ds.bpm, ds.snapDivision, ds.firstBeatSec);
        }

        const start = Math.min(dragStartTime.current, time);
        const end = Math.max(dragStartTime.current, time);

        if (Math.abs(end - start) > 0.01) {
            dispatch({ type: 'SET_SELECTION_RANGE', payload: { start, end } });
        }
    }, [dispatch]);

    const handleMouseUp = useCallback(() => {
        isDragging.current = false;
    }, []);

    const handleWheel = useCallback((e) => {
        e.preventDefault();
        const ds = drawState.current;

        if (e.ctrlKey || e.metaKey) {
            // Zoom
            const rect = canvasRef.current.getBoundingClientRect();
            const mouseX = e.clientX - rect.left;
            const timeBefore = (mouseX + ds.scrollX) / ds.zoom;

            const zoomDelta = e.deltaY > 0 ? 0.85 : 1.18;
            const newZoom = Math.max(10, Math.min(2000, ds.zoom * zoomDelta));

            dispatch({ type: 'SET_ZOOM', payload: newZoom });

            // Keep mouse position stable
            const newScrollX = timeBefore * newZoom - mouseX;
            dispatch({ type: 'SET_SCROLL_X', payload: Math.max(-200, newScrollX) });
        } else {
            // Horizontal scroll
            const scrollDelta = e.deltaY * 2;
            dispatch({ type: 'SET_SCROLL_X', payload: Math.max(-200, ds.scrollX + scrollDelta) });
        }
    }, [dispatch]);

    return (
        <div
            ref={containerRef}
            className="relative w-full select-none"
            style={{ height: canvasHeight }}
        >
            <canvas
                ref={canvasRef}
                className="absolute inset-0 cursor-crosshair"
                onMouseDown={handleMouseDown}
                onMouseMove={handleMouseMove}
                onMouseUp={handleMouseUp}
                onMouseLeave={handleMouseUp}
                onWheel={handleWheel}
                onContextMenu={(e) => e.preventDefault()}
            />
        </div>
    );
});

// ─── DRAWING FUNCTIONS ─────────────────────────────────────────────────────────

function drawTimeline(ctx, ds) {
    const { width, height, dpr, zoom, scrollX } = ds;
    if (width <= 0 || height <= 0) return;

    ctx.save();
    ctx.scale(dpr, dpr);

    // Clear
    ctx.fillStyle = COLORS.background;
    ctx.fillRect(0, 0, width, height);

    // Visible time range
    const startTime = scrollX / zoom;
    const endTime = (scrollX + width) / zoom;

    // Draw layers (order matters)
    drawGrid(ctx, ds, startTime, endTime);
    drawPhraseMarkers(ctx, ds, startTime, endTime);
    drawWaveforms(ctx, ds, startTime, endTime);
    drawLoops(ctx, ds, startTime, endTime);
    drawRegionBoundaries(ctx, ds, startTime, endTime);
    drawSelectionRange(ctx, ds, startTime, endTime);
    drawCueMarkers(ctx, ds, startTime, endTime);
    drawRuler(ctx, ds, startTime, endTime);
    drawPlayhead(ctx, ds);

    ctx.restore();
}

function drawGrid(ctx, ds, startTime, endTime) {
    const { width, height, zoom, scrollX, bpm, firstBeatSec } = ds;
    if (!bpm || bpm <= 0) return;

    const beatDuration = 60 / bpm;
    const barDuration = beatDuration * 4;

    // Determine grid resolution based on zoom
    let gridUnit = beatDuration;
    let isBarLevel = false;
    let isSubBeat = false;

    const pixelsPerBeat = beatDuration * zoom;

    if (pixelsPerBeat < 8) {
        // Very zoomed out → show bars only
        gridUnit = barDuration;
        isBarLevel = true;
    } else if (pixelsPerBeat > 60) {
        // Zoomed in → show sub-beats
        gridUnit = beatDuration / 4;  // 1/16th
        isSubBeat = true;
    }

    // Find first grid line
    const firstBeat = Math.floor((startTime - firstBeatSec) / gridUnit) * gridUnit + firstBeatSec;

    ctx.lineWidth = 1;

    for (let t = firstBeat; t <= endTime; t += gridUnit) {
        if (t < 0) continue;
        const x = Math.round(t * zoom - scrollX) + 0.5;
        if (x < -1 || x > width + 1) continue;

        // Determine line style
        const beatNum = Math.round((t - firstBeatSec) / beatDuration);

        if (beatNum % 4 === 0) {
            // Bar line
            ctx.strokeStyle = COLORS.gridBar;
        } else if (isSubBeat) {
            const subBeatNum = Math.round((t - firstBeatSec) / (beatDuration / 4));
            if (subBeatNum % 4 === 0) {
                ctx.strokeStyle = COLORS.gridBeat;
            } else {
                ctx.strokeStyle = COLORS.gridSub;
            }
        } else {
            ctx.strokeStyle = COLORS.gridBeat;
        }

        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, height);
        ctx.stroke();
    }
}

function drawPhraseMarkers(ctx, ds, startTime, endTime) {
    const { width, height, zoom, scrollX, bpm, firstBeatSec } = ds;
    if (!bpm || bpm <= 0) return;

    const beatDuration = 60 / bpm;
    const phraseDuration = beatDuration * 64; // 16 bars = 64 beats

    const firstPhrase = Math.floor((startTime - firstBeatSec) / phraseDuration) * phraseDuration + firstBeatSec;

    ctx.lineWidth = 2;
    ctx.strokeStyle = COLORS.phraseMarker; // Reddish
    ctx.fillStyle = COLORS.phraseLabel;
    ctx.font = 'bold 10px Inter, system-ui, sans-serif';
    ctx.textAlign = 'center'; // Center align label

    // Draw dashed line with label
    ctx.setLineDash([5, 5]);

    for (let t = firstPhrase; t <= endTime; t += phraseDuration) {
        if (t < 0) continue;
        const x = Math.round(t * zoom - scrollX) + 0.5;
        if (x < -1 || x > width + 1) continue;

        ctx.beginPath();
        ctx.moveTo(x, RULER_HEIGHT); // Start below ruler
        ctx.lineTo(x, height);
        ctx.stroke();

        // Label with background for visibility
        const phraseNum = Math.round((t - firstBeatSec) / phraseDuration) + 1;
        const label = `16 Bar (${phraseNum})`;

        ctx.save();
        ctx.fillStyle = 'rgba(0,0,0,0.7)';
        ctx.fillRect(x - 30, RULER_HEIGHT + 2, 60, 14); // Background pill
        ctx.restore();

        ctx.fillStyle = COLORS.phraseLabel;
        ctx.fillText(label, x, RULER_HEIGHT + 12);

        // Triangle marker at top
        ctx.beginPath();
        ctx.moveTo(x - 5, RULER_HEIGHT);
        ctx.lineTo(x + 5, RULER_HEIGHT);
        ctx.lineTo(x, RULER_HEIGHT + 6);
        ctx.fill();
    }

    ctx.setLineDash([]);
}

function drawWaveforms(ctx, ds, startTime, endTime) {
    const { width, height, zoom, scrollX, regions, bandPeaks, fallbackPeaks, totalDuration, lodLevel } = ds;

    // Need either band peaks or fallback peaks
    const hasBandPeaks = bandPeaks && bandPeaks.low && bandPeaks.low.length > 0;
    const hasFallback = fallbackPeaks && fallbackPeaks.length > 0;
    if (!hasBandPeaks && !hasFallback) return;
    if (totalDuration <= 0) return;

    // Offset below ruler
    const waveTop = RULER_HEIGHT;
    const waveHeight = height - RULER_HEIGHT;
    const centerY = waveTop + waveHeight / 2;
    const maxAmp = waveHeight * 0.42;

    // For each region, draw its portion of the waveform
    for (const region of regions) {
        const regionEnd = region.timelineStart + region.duration;

        // Skip if not visible
        if (regionEnd < startTime || region.timelineStart > endTime) continue;

        // Calculate visible pixel range for this region
        const regionStartPx = Math.max(0, region.timelineStart * zoom - scrollX);
        const regionEndPx = Math.min(width, regionEnd * zoom - scrollX);

        if (regionEndPx <= regionStartPx) continue;

        if (hasBandPeaks) {
            // Draw 3-band RGB waveform
            const isBassOnly = ds.waveformStyle === 'bass';

            const bands = isBassOnly ? [
                { peaks: bandPeaks.low, color: COLORS.lowBand }
            ] : [
                { peaks: bandPeaks.low, color: COLORS.lowBand },
                { peaks: bandPeaks.mid, color: COLORS.midBand },
                { peaks: bandPeaks.high, color: COLORS.highBand },
            ];

            for (const band of bands) {
                if (!band.peaks || band.peaks.length === 0) continue;
                drawBandForRegion(ctx, band.peaks, band.color, region, regionStartPx, regionEndPx, scrollX, zoom, totalDuration, centerY, maxAmp, lodLevel, ds.waveformStyle);
            }
        } else {
            // Fallback: simple white waveform
            drawBandForRegion(ctx, fallbackPeaks, 'rgba(255,255,255,0.6)', region, regionStartPx, regionEndPx, scrollX, zoom, totalDuration, centerY, maxAmp, lodLevel, ds.waveformStyle);
        }
    }
}

function drawBandForRegion(ctx, peaks, color, region, regionStartPx, regionEndPx, scrollX, zoom, totalDuration, centerY, maxAmp, lodLevel, style) {
    if (style === 'liquid') {
        const isMonoFallback = peaks.length < totalDuration * 5; // Heuristic
        ctx.fillStyle = color;
        ctx.beginPath();

        const step = Math.max(2, lodLevel * 2); // Sample every 2-8 pixels for smoothing
        const sampling = 2; // Sample 2 peaks per step

        // Move to start
        ctx.moveTo(Math.floor(regionStartPx), centerY);

        // --- Draw Top Edge ---
        for (let px = Math.floor(regionStartPx); px < regionEndPx; px += step) {
            const time = (px + scrollX) / zoom;
            const regionLocalTime = time - region.timelineStart;
            const sourceTime = region.sourceStart + regionLocalTime;
            const peakIndex = Math.floor(sourceTime / totalDuration * peaks.length);

            if (peakIndex >= 0 && peakIndex < peaks.length) {
                const peak = peaks[peakIndex];
                const y = centerY - (peak.max * maxAmp);

                // Use quadratic curve for smoothing if not the first point
                if (px === Math.floor(regionStartPx)) {
                    ctx.lineTo(px, y);
                } else {
                    const prevPx = px - step;
                    const prevTime = (prevPx + scrollX) / zoom;
                    const prevSourceTime = region.sourceStart + (prevTime - region.timelineStart);
                    const prevPeakIdx = Math.floor(prevSourceTime / totalDuration * peaks.length);
                    const prevPeak = peaks[prevPeakIdx] || peak;
                    const prevY = centerY - (prevPeak.max * maxAmp);

                    const midX = (prevPx + px) / 2;
                    const midY = (prevY + y) / 2;
                    ctx.quadraticCurveTo(prevPx, prevY, midX, midY);
                }
            }
        }

        // --- Draw Bottom Edge (reverse) ---
        for (let px = Math.ceil(regionEndPx); px >= Math.floor(regionStartPx); px -= step) {
            const time = (px + scrollX) / zoom;
            const regionLocalTime = time - region.timelineStart;
            const sourceTime = region.sourceStart + regionLocalTime;
            const peakIndex = Math.floor(sourceTime / totalDuration * peaks.length);

            if (peakIndex >= 0 && peakIndex < peaks.length) {
                const peak = peaks[peakIndex];
                const y = centerY - (peak.min * maxAmp); // min is negative, so centerY - negative = lower

                if (px === Math.ceil(regionEndPx)) {
                    ctx.lineTo(px, y);
                } else {
                    const prevPx = px + step;
                    const prevTime = (prevPx + scrollX) / zoom;
                    const prevSourceTime = region.sourceStart + (prevTime - region.timelineStart);
                    const prevPeakIdx = Math.floor(prevSourceTime / totalDuration * peaks.length);
                    const prevPeak = peaks[prevPeakIdx] || peak;
                    const prevY = centerY - (prevPeak.min * maxAmp);

                    const midX = (prevPx + px) / 2;
                    const midY = (prevY + y) / 2;
                    ctx.quadraticCurveTo(prevPx, prevY, midX, midY);
                }
            }
        }

        ctx.closePath();
        ctx.fill();
    } else {
        // DETAIL STYLE: Bars
        ctx.strokeStyle = color;
        ctx.lineCap = 'round';

        const barWidth = 3;
        const gap = 1;
        const step = Math.max(barWidth + gap, lodLevel);

        ctx.lineWidth = barWidth;
        ctx.beginPath();

        const regionStartTimePx = region.timelineStart * zoom;

        // Adjust start px to align with step grid relative to region start
        let px = Math.floor(regionStartPx);

        for (; px < regionEndPx; px += step) {
            const time = (px + scrollX) / zoom;
            const regionLocalTime = time - region.timelineStart;
            const sourceTime = region.sourceStart + regionLocalTime;

            const peakIndex = Math.floor(sourceTime / totalDuration * peaks.length);
            if (peakIndex < 0 || peakIndex >= peaks.length) continue;

            const peak = peaks[peakIndex];
            const h = (peak.max - peak.min) * maxAmp;
            if (h < 1) continue; // Skip silence

            const y1 = centerY + peak.min * maxAmp;
            const y2 = centerY + peak.max * maxAmp;

            ctx.moveTo(px + barWidth / 2, y1);
            ctx.lineTo(px + barWidth / 2, y2);
        }

        ctx.stroke();
    }
}

function drawRegionBoundaries(ctx, ds, startTime, endTime) {
    const { width, height, zoom, scrollX, regions, selectedIds } = ds;

    for (const region of regions) {
        const regionEnd = region.timelineStart + region.duration;
        if (regionEnd < startTime || region.timelineStart > endTime) continue;

        const x1 = region.timelineStart * zoom - scrollX;
        const x2 = regionEnd * zoom - scrollX;
        const isSelected = selectedIds.has(region.id);

        // Region background (subtle)
        if (isSelected) {
            ctx.fillStyle = COLORS.selectionFill;
            ctx.fillRect(x1, 0, x2 - x1, height);
        }

        // Left edge
        ctx.strokeStyle = isSelected ? COLORS.regionSelectedBorder : COLORS.regionBorder;
        ctx.lineWidth = isSelected ? 2 : 1;
        ctx.beginPath();
        ctx.moveTo(Math.round(x1) + 0.5, 0);
        ctx.lineTo(Math.round(x1) + 0.5, height);
        ctx.stroke();

        // Right edge
        ctx.beginPath();
        ctx.moveTo(Math.round(x2) + 0.5, 0);
        ctx.lineTo(Math.round(x2) + 0.5, height);
        ctx.stroke();
    }
}

function drawSelectionRange(ctx, ds, startTime, endTime) {
    const { width, height, zoom, scrollX, selectionRange } = ds;
    if (!selectionRange) return;

    const { start, end } = selectionRange;
    if (end <= start) return;
    if (end < startTime || start > endTime) return;

    const x1 = Math.round(start * zoom - scrollX);
    const x2 = Math.round(end * zoom - scrollX);

    if (x2 < 0 || x1 > width) return;

    // Fill
    ctx.fillStyle = COLORS.selectionFill;
    ctx.fillRect(x1, 0, x2 - x1, height);

    // Border
    ctx.strokeStyle = COLORS.selectionBorder;
    ctx.lineWidth = 1;
    ctx.strokeRect(x1 + 0.5, 0.5, x2 - x1, height - 1);
}

function drawCueMarkers(ctx, ds, startTime, endTime) {
    const { width, height, zoom, scrollX, hotCues, memoryCues } = ds;

    // Hot cues
    for (let i = 0; i < hotCues.length; i++) {
        const cue = hotCues[i];
        if (!cue) continue;

        const x = Math.round(cue.time * zoom - scrollX) + 0.5;
        if (x < -10 || x > width + 10) continue;

        const color = `rgb(${cue.red},${cue.green},${cue.blue})`;

        // Vertical line
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, height);
        ctx.stroke();

        // Flag triangle at top
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x + 14, 0);
        ctx.lineTo(x + 14, 10);
        ctx.lineTo(x + 4, 16);
        ctx.lineTo(x, 16);
        ctx.closePath();
        ctx.fill();

        // Label
        ctx.fillStyle = '#000';
        ctx.font = 'bold 9px Inter, system-ui, sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText(String.fromCharCode(65 + i), x + 3, 12);
    }

    // Memory cues
    for (const mem of memoryCues) {
        const x = Math.round(mem.time * zoom - scrollX) + 0.5;
        if (x < -10 || x > width + 10) continue;

        const color = `rgb(${mem.red || 255},${mem.green || 0},${mem.blue || 0})`;

        // Small triangle marker
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.moveTo(x - 5, 0);
        ctx.lineTo(x + 5, 0);
        ctx.lineTo(x, 8);
        ctx.closePath();
        ctx.fill();

        // Short line
        ctx.strokeStyle = color;
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(x, 8);
        ctx.lineTo(x, height);
        ctx.stroke();
        ctx.setLineDash([]);
    }
}

function drawLoops(ctx, ds, startTime, endTime) {
    const { width, height, zoom, scrollX, loops, activeLoopIndex } = ds;

    for (let i = 0; i < loops.length; i++) {
        const loop = loops[i];
        const x1 = loop.startTime * zoom - scrollX;
        const x2 = loop.endTime * zoom - scrollX;

        if (x2 < 0 || x1 > width) continue;

        const isActive = i === activeLoopIndex;
        const color = `rgb(${loop.red || 251},${loop.green || 146},${loop.blue || 60})`;

        // Shaded area
        ctx.fillStyle = isActive
            ? `rgba(${loop.red || 251},${loop.green || 146},${loop.blue || 60}, 0.18)`
            : COLORS.loopFill;
        ctx.fillRect(x1, 0, x2 - x1, height);

        // Borders
        ctx.strokeStyle = isActive ? color : COLORS.loopBorder;
        ctx.lineWidth = isActive ? 2 : 1;

        ctx.beginPath();
        ctx.moveTo(Math.round(x1) + 0.5, 0);
        ctx.lineTo(Math.round(x1) + 0.5, height);
        ctx.stroke();

        ctx.beginPath();
        ctx.moveTo(Math.round(x2) + 0.5, 0);
        ctx.lineTo(Math.round(x2) + 0.5, height);
        ctx.stroke();

        // Loop label at top
        ctx.fillStyle = color;
        ctx.font = '8px Inter, system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(loop.name || `Loop ${i + 1}`, (x1 + x2) / 2, 10);

        // Bracket markers
        ctx.fillStyle = color;
        // Left bracket
        ctx.fillRect(x1, 0, 3, 20);
        // Right bracket
        ctx.fillRect(x2 - 3, 0, 3, 20);
    }
}

function drawPlayhead(ctx, ds) {
    const { width, height, zoom, scrollX, playhead } = ds;

    const x = Math.round(playhead * zoom - scrollX) + 0.5;
    if (x < -1 || x > width + 1) return;

    // Glow
    ctx.strokeStyle = COLORS.playheadGlow;
    ctx.lineWidth = 5;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, height);
    ctx.stroke();

    // Main line
    ctx.strokeStyle = COLORS.playhead;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, height);
    ctx.stroke();

    // Position triangle at top
    ctx.fillStyle = COLORS.playhead;
    ctx.beginPath();
    ctx.moveTo(x - 6, 0);
    ctx.lineTo(x + 6, 0);
    ctx.lineTo(x, 8);
    ctx.closePath();
    ctx.fill();
}

function drawRuler(ctx, ds, startTime, endTime) {
    const { width, zoom, scrollX, bpm, firstBeatSec } = ds;

    // Ruler background
    ctx.fillStyle = COLORS.rulerBg;
    ctx.fillRect(0, 0, width, RULER_HEIGHT);

    // Bottom border
    ctx.strokeStyle = COLORS.rulerLine;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, RULER_HEIGHT + 0.5);
    ctx.lineTo(width, RULER_HEIGHT + 0.5);
    ctx.stroke();

    if (!bpm || bpm <= 0) return;

    const beatDuration = 60 / bpm;
    const barDuration = beatDuration * 4;
    const pixelsPerBar = barDuration * zoom;

    // Determine label spacing based on zoom
    let labelInterval = barDuration;
    if (pixelsPerBar < 40) labelInterval = barDuration * 4;  // Every 4 bars
    if (pixelsPerBar < 15) labelInterval = barDuration * 16; // Every 16 bars

    const firstLabel = Math.floor((startTime - firstBeatSec) / labelInterval) * labelInterval + firstBeatSec;

    ctx.fillStyle = COLORS.rulerText;
    ctx.font = '9px Inter, system-ui, sans-serif';
    ctx.textAlign = 'center';

    for (let t = firstLabel; t <= endTime; t += labelInterval) {
        if (t < 0) continue;
        const x = Math.round(t * zoom - scrollX);
        if (x < -30 || x > width + 30) continue;

        // Tick mark
        ctx.strokeStyle = COLORS.rulerText;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(x + 0.5, RULER_HEIGHT - 6);
        ctx.lineTo(x + 0.5, RULER_HEIGHT);
        ctx.stroke();

        // Time label (mm:ss)
        const mins = Math.floor(t / 60);
        const secs = Math.floor(t % 60);
        ctx.fillText(`${mins}:${secs.toString().padStart(2, '0')}`, x, RULER_HEIGHT - 8);
    }
}



DawTimeline.displayName = 'DawTimeline';

export default DawTimeline;
