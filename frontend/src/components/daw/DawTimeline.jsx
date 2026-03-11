/**
 * DawTimeline — High-performance Canvas-based timeline for the DJ Edit DAW
 *
 * Renders multiple layers on a single canvas using requestAnimationFrame:
 * 1. Grid Layer (beat lines, bar lines, phrase markers)
 * 2. Waveform Layer (3-Band RGB, multi-resolution LOD)
 * 3. Cue & Loop Layer (hot cues, memory cues, loops)
 * 4. Region boundaries
 * 5. Selection highlight
 * 6. Playhead (with Dead Reckoning for butter-smooth 60fps)
 *
 * Edge Cases handled:
 *  EC1 — ResizeObserver debounced (no flicker)
 *  EC2 — Waveform LOD + zoom bi-linear interpolation at extreme zoom
 *  EC3 — Cue drag clamped to [0, totalDuration]
 *  EC5 — Marker label collision detection with Y-offset stagger
 *  EC7 — High-DPI (Retina) re-read on every resize
 *  EC9 — No ghosting: bg fillRect is first layer, ctx.save/restore symmetry
 *  EC10 — peakCacheMap.clear() called on unmount
 *  EC12 — NaN guard in peak drawing
 *  EC16 — Zero-duration region skipped
 *  EC25 — LOD level hysteresis (needs 60 consecutive good frames to improve)
 */

import React, { useRef, useEffect, useCallback } from 'react';
import { snapToGrid } from '../../audio/DawState';
import * as DawEngine from '../../audio/DawEngine';

// ─── COLORS ────────────────────────────────────────────────────────────────────

const RULER_HEIGHT = 22;

const COLORS = {
    background: '#0c0f1a',
    rulerBg: '#0a0d16',
    rulerText: 'rgba(255,255,255,0.5)',
    rulerLine: 'rgba(255,255,255,0.1)',
    rulerTick: 'rgba(255,255,255,0.3)',
    gridBar: 'rgba(239, 68, 68, 0.4)',
    gridBeat: 'rgba(255, 255, 255, 0.1)',
    gridSub: 'rgba(255, 255, 255, 0.03)',
    phraseMarker: '#F87171',
    phraseLabel: 'rgba(248, 113, 113, 0.9)',
    playhead: '#ffffff',
    playheadGlow: 'rgba(255,255,255,0.25)',
    playheadGlow2: 'rgba(255,255,255,0.08)',
    selectionFill: 'rgba(56, 189, 248, 0.10)',
    selectionBorder: 'rgba(56, 189, 248, 0.5)',
    regionBorder: 'rgba(255,255,255,0.14)',
    regionSelectedBorder: '#38bdf8',
    // 3-Band Rekordbox palette
    lowBand: 'rgba(0, 153, 255, 0.88)',
    midBand: 'rgba(255, 153, 0, 0.88)',
    highBand: 'rgba(255, 255, 255, 0.80)',
    cueLine: '#22c55e',
    memoryCue: '#ef4444',
    memoryCueDash: 'rgba(239,68,68,0.6)',
    loopFill: 'rgba(251, 146, 60, 0.10)',
    loopBorder: 'rgba(251, 146, 60, 0.55)',
    ghostCue: 'rgba(255,255,255,0.4)',
};

// ─── MODULE-LEVEL PEAK CACHE ────────────────────────────────────────────────────
// Key: `${bufferId}-${lodLevel}`, value: { low, mid, high } peak arrays
const peakCacheMap = new Map();

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
    const resizeTimerRef = useRef(null);
    const resizeObserverRef = useRef(null);
    const isDragging = useRef(false);
    const dragStartTime = useRef(0);
    const draggingCue = useRef(null); // { type: 'hot'|'memory', index: number }
    const goodFrameCount = useRef(0); // for LOD hysteresis (EC25)

    // Mutable drawing state (decoupled from React re-renders)
    const drawState = useRef({
        width: 0,
        height: canvasHeight,
        dpr: window.devicePixelRatio || 1,
        zoom: 100,
        scrollX: 0,
        playhead: 0,
        deadReckoning: { lastSyncWallClock: 0, lastSyncAudioTime: 0 },
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
        waveformStyle: 'detail',
        needsRedraw: true,
        lastFrameTime: 0,
        lodLevel: 1,  // 1 = full, 2 = half, 4 = quarter
        ghostCueX: null, // pixel X of cue being dragged
    });

    // Sync React state → mutable draw state
    useEffect(() => {
        const ds = drawState.current;
        ds.zoom = state.zoom;

        // Only accept React scroll overrides when paused OR heavily desynced
        if (!state.isPlaying || Math.abs(ds.scrollX - state.scrollX) > window.innerWidth * 0.5) {
            ds.scrollX = state.scrollX;
        }
        if (!state.isPlaying) {
            ds.playhead = state.playhead;
        }

        ds.isPlaying = state.isPlaying;
        ds.regions = state.regions;
        ds.selectedIds = state.selectedRegionIds;
        ds.bpm = state.bpm;
        ds.snapDivision = state.snapDivision || '1/4';
        ds.gridOffsetSec = state.gridOffsetSec;
        ds.firstBeatSec = ((state.tempoMap?.[0]?.positionMs || 0) / 1000) + (state.gridOffsetSec || 0);
        ds.totalDuration = state.totalDuration;
        ds.hotCues = state.hotCues;
        ds.memoryCues = state.memoryCues;
        ds.loops = state.loops;
        ds.activeLoopIndex = state.activeLoopIndex;
        ds.snapEnabled = state.snapEnabled;
        ds.slipMode = state.slipMode || false;
        ds.waveformStyle = state.waveformStyle || 'detail';
        ds.selectionRange = state.selectionRange;
        ds.bandPeaks = state.bandPeaks;
        ds.fallbackPeaks = state.fallbackPeaks || null;
        ds.deadReckoning = state.deadReckoning || { lastSyncWallClock: 0, lastSyncAudioTime: 0 };
        ds.needsRedraw = true;
    }, [state]);

    // ── RESIZE HANDLER (EC1 — debounced, EC7 — re-read dpr) ──
    useEffect(() => {
        const container = containerRef.current;
        if (!container) return;

        const applyResize = () => {
            const rect = container.getBoundingClientRect();
            const ds = drawState.current;
            ds.dpr = window.devicePixelRatio || 1; // EC7: re-read on every resize
            ds.width = rect.width;
            ds.height = canvasHeight;

            const canvas = canvasRef.current;
            if (canvas) {
                canvas.width = Math.round(ds.width * ds.dpr);
                canvas.height = Math.round(ds.height * ds.dpr);
                canvas.style.width = `${ds.width}px`;
                canvas.style.height = `${ds.height}px`;
            }
            ds.needsRedraw = true;
        };

        const handleResize = () => {
            // EC1: 16 ms debounce to prevent flicker during rapid resize
            clearTimeout(resizeTimerRef.current);
            resizeTimerRef.current = setTimeout(applyResize, 16);
        };

        resizeObserverRef.current = new ResizeObserver(handleResize);
        resizeObserverRef.current.observe(container);
        applyResize(); // initial, immediate

        return () => {
            resizeObserverRef.current?.disconnect();
            clearTimeout(resizeTimerRef.current);
        };
    }, [canvasHeight]);

    // ── MAIN RENDER LOOP ──
    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;
        const ctx = canvas.getContext('2d', { alpha: false }); // alpha:false = faster compositing

        const renderFrame = (timestamp) => {
            const ds = drawState.current;

            if (ds.isPlaying) {
                // ── Dead Reckoning (EC — Engineering Standard) ──
                // Use Web Audio clock directly — it's the most accurate source.
                // Between Tauri IPC sync frames, we use DawEngine.getCurrentTime()
                // which tracks wall-clock delta internally.
                ds.playhead = DawEngine.getCurrentTime();

                // Auto-scroll to keep playhead visible at ~70% of viewport
                const playheadPx = ds.playhead * ds.zoom;
                const limitRight = ds.scrollX + ds.width * 0.7;
                if (playheadPx > limitRight) {
                    ds.scrollX = Math.max(0, playheadPx - ds.width * 0.3);
                }
            }

            // ── LOD Adaptive Quality (EC25 — hysteresis) ──
            if (ds.lastFrameTime > 0) {
                const delta = timestamp - ds.lastFrameTime;
                if (delta > 22) {
                    // Frame took >22ms (< ~45 fps) → bump LOD down
                    goodFrameCount.current = 0;
                    ds.lodLevel = Math.min(4, ds.lodLevel + 1);
                } else if (delta < 15) {
                    // Frame was fast — only improve LOD after 60 consecutive good frames (hysteresis)
                    goodFrameCount.current++;
                    if (goodFrameCount.current >= 60) {
                        goodFrameCount.current = 0;
                        ds.lodLevel = Math.max(1, ds.lodLevel - 1);
                    }
                }
            }
            ds.lastFrameTime = timestamp;

            // Redraw if needed or playing
            if (ds.needsRedraw || ds.isPlaying) {
                drawTimeline(ctx, ds);
                ds.needsRedraw = false;
            }

            animFrameRef.current = requestAnimationFrame(renderFrame);
        };

        animFrameRef.current = requestAnimationFrame(renderFrame);

        return () => {
            if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
            // EC10: cleanup peak cache on unmount
            peakCacheMap.clear();
        };
    }, []);

    // ── MOUSE HANDLERS ──

    // Hit-test hot cue flag triangles (14×16 px bounding box)
    const hitTestCueFlag = useCallback((x, y, ds) => {
        for (let i = 0; i < ds.hotCues.length; i++) {
            const cue = ds.hotCues[i];
            if (!cue) continue;
            const cx = Math.round(cue.time * ds.zoom - ds.scrollX);
            if (x >= cx && x <= cx + 14 && y >= 0 && y <= 16) {
                return { type: 'hot', index: i };
            }
        }
        for (let i = 0; i < ds.memoryCues.length; i++) {
            const mem = ds.memoryCues[i];
            const cx = Math.round(mem.time * ds.zoom - ds.scrollX);
            if (x >= cx - 5 && x <= cx + 5 && y >= 0 && y <= 10) {
                return { type: 'memory', index: i };
            }
        }
        return null;
    }, []);

    const handleMouseDown = useCallback((e) => {
        const canvas = canvasRef.current;
        if (!canvas) return;

        const rect = canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        const ds = drawState.current;

        let time = (x + ds.scrollX) / ds.zoom;

        if (ds.snapEnabled && !ds.slipMode && ds.bpm > 0) {
            time = snapToGrid(time, ds.bpm, ds.snapDivision, ds.firstBeatSec);
        }

        if (e.button === 0) {
            // Check cue flag hit first (EC3)
            const cueHit = hitTestCueFlag(x, y, ds);
            if (cueHit) {
                draggingCue.current = cueHit;
                drawState.current.ghostCueX = x;
                return;
            }

            dispatch({ type: 'SET_PLAYHEAD', payload: Math.max(0, time) });

            isDragging.current = true;
            dragStartTime.current = time;

            const clickedRegion = ds.regions.find(r => {
                const rx = (r.timelineStart * ds.zoom) - ds.scrollX;
                const rw = r.duration * ds.zoom;
                return x >= rx && x <= rx + rw;
            });

            if (clickedRegion) {
                if (e.ctrlKey) {
                    dispatch({ type: 'TOGGLE_SELECT_REGION', payload: clickedRegion.id });
                } else {
                    dispatch({ type: 'SELECT_REGION', payload: clickedRegion.id });
                }
            } else {
                if (!e.ctrlKey) {
                    dispatch({ type: 'SET_SELECTION_RANGE', payload: { start: time, end: time } });
                    dispatch({ type: 'CLEAR_SELECTION' });
                }
            }

            if (!clickedRegion) {
                dispatch({ type: 'SET_SELECTION_RANGE', payload: { start: time, end: time } });
            }
        } else if (e.button === 2) {
            if (onContextMenu) onContextMenu(time, e);
        }
    }, [dispatch, onContextMenu, hitTestCueFlag]);

    const handleMouseMove = useCallback((e) => {
        const canvas = canvasRef.current;
        if (!canvas) return;
        const rect = canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const ds = drawState.current;

        // Cue drag (EC3)
        if (draggingCue.current) {
            ds.ghostCueX = x;
            ds.needsRedraw = true;
            return;
        }

        if (!isDragging.current) return;

        let time = (x + ds.scrollX) / ds.zoom;

        if (ds.snapEnabled && !ds.slipMode && ds.bpm > 0) {
            time = snapToGrid(time, ds.bpm, ds.snapDivision, ds.firstBeatSec);
        }

        const start = Math.min(dragStartTime.current, time);
        const end = Math.max(dragStartTime.current, time);

        if (Math.abs(end - start) > 0.01) {
            dispatch({ type: 'SET_SELECTION_RANGE', payload: { start, end } });
        }
    }, [dispatch]);

    const handleMouseUp = useCallback((e) => {
        const canvas = canvasRef.current;

        if (draggingCue.current && canvas) {
            const rect = canvas.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const ds = drawState.current;

            // EC3: clamp to valid range
            let time = Math.max(0, Math.min(ds.totalDuration, (x + ds.scrollX) / ds.zoom));
            if (ds.snapEnabled && ds.bpm > 0) {
                time = snapToGrid(time, ds.bpm, ds.snapDivision, ds.firstBeatSec);
            }

            const { type, index } = draggingCue.current;
            if (type === 'hot') {
                const cue = ds.hotCues[index];
                if (cue) {
                    dispatch({ type: 'SET_HOT_CUE', payload: { index, cue: { ...cue, time } } });
                }
            } else if (type === 'memory') {
                const mem = ds.memoryCues[index];
                if (mem) {
                    // Update memory cue by removing and re-adding at new time
                    dispatch({ type: 'REMOVE_MEMORY_CUE', payload: index });
                    dispatch({ type: 'ADD_MEMORY_CUE', payload: { ...mem, time } });
                }
            }

            draggingCue.current = null;
            drawState.current.ghostCueX = null;
            drawState.current.needsRedraw = true;
        }

        isDragging.current = false;
    }, [dispatch]);

    const handleWheel = useCallback((e) => {
        e.preventDefault();
        const ds = drawState.current;

        if (e.ctrlKey || e.metaKey) {
            // Zoom anchored at mouse position
            const rect = canvasRef.current.getBoundingClientRect();
            const mouseX = e.clientX - rect.left;
            const timeBefore = (mouseX + ds.scrollX) / ds.zoom;

            const zoomDelta = e.deltaY > 0 ? 0.85 : 1.18;
            const newZoom = Math.max(10, Math.min(2000, ds.zoom * zoomDelta));

            dispatch({ type: 'SET_ZOOM', payload: newZoom });

            // Keep mouse-anchored time stable
            const newScrollX = timeBefore * newZoom - mouseX;
            dispatch({ type: 'SET_SCROLL_X', payload: Math.max(0, newScrollX) });
        } else {
            // Horizontal scroll
            const scrollDelta = e.deltaY !== 0 ? e.deltaY * 2 : e.deltaX * 2;
            dispatch({ type: 'SET_SCROLL_X', payload: Math.max(0, ds.scrollX + scrollDelta) });
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
    const { width, height, dpr } = ds;
    if (width <= 0 || height <= 0) return;

    ctx.save();
    ctx.scale(dpr, dpr);

    // EC9: solid bg clear first, no ghosting
    ctx.fillStyle = COLORS.background;
    ctx.fillRect(0, 0, width, height);

    const startTime = ds.scrollX / ds.zoom;
    const endTime = (ds.scrollX + width) / ds.zoom;

    // Draw all layers in painter's order
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

// ── GRID ────────────────────────────────────────────────────────────────────────

function drawGrid(ctx, ds, startTime, endTime) {
    const { width, height, zoom, scrollX, bpm, firstBeatSec } = ds;
    if (!bpm || bpm <= 0) return;

    const beatDuration = 60 / bpm;
    const barDuration = beatDuration * 4;
    const pixelsPerBeat = beatDuration * zoom;

    let gridUnit = beatDuration;
    let isBarLevel = false;
    let isSubBeat = false;

    if (pixelsPerBeat < 8) {
        gridUnit = barDuration;
        isBarLevel = true;
    } else if (pixelsPerBeat > 60) {
        gridUnit = beatDuration / 4; // 1/16th
        isSubBeat = true;
    }

    const firstBeat = Math.floor((startTime - firstBeatSec) / gridUnit) * gridUnit + firstBeatSec;
    ctx.lineWidth = 1;

    for (let t = firstBeat; t <= endTime + gridUnit; t += gridUnit) {
        if (t < 0) continue;
        const x = Math.round(t * zoom - scrollX) + 0.5;
        if (x < -1 || x > width + 1) continue;

        const beatNum = Math.round((t - firstBeatSec) / beatDuration);

        if (beatNum % 4 === 0) {
            ctx.strokeStyle = COLORS.gridBar;
        } else if (isSubBeat) {
            const subBeatNum = Math.round((t - firstBeatSec) / (beatDuration / 4));
            ctx.strokeStyle = subBeatNum % 4 === 0 ? COLORS.gridBeat : COLORS.gridSub;
        } else {
            ctx.strokeStyle = COLORS.gridBeat;
        }

        ctx.beginPath();
        ctx.moveTo(x, RULER_HEIGHT);
        ctx.lineTo(x, height);
        ctx.stroke();
    }
}

// ── PHRASE MARKERS ──────────────────────────────────────────────────────────────

function drawPhraseMarkers(ctx, ds, startTime, endTime) {
    const { width, height, zoom, scrollX, bpm, firstBeatSec } = ds;
    if (!bpm || bpm <= 0) return;

    const beatDuration = 60 / bpm;
    const phraseDuration = beatDuration * 64; // 16 bars

    const firstPhrase = Math.floor((startTime - firstBeatSec) / phraseDuration) * phraseDuration + firstBeatSec;

    ctx.lineWidth = 2;
    ctx.strokeStyle = COLORS.phraseMarker;
    ctx.fillStyle = COLORS.phraseLabel;
    ctx.font = 'bold 9px Inter, system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.setLineDash([4, 4]);

    for (let t = firstPhrase; t <= endTime + phraseDuration; t += phraseDuration) {
        if (t < 0) continue;
        const x = Math.round(t * zoom - scrollX) + 0.5;
        if (x < -1 || x > width + 1) continue;

        ctx.beginPath();
        ctx.moveTo(x, RULER_HEIGHT);
        ctx.lineTo(x, height);
        ctx.stroke();

        const phraseNum = Math.round((t - firstBeatSec) / phraseDuration) + 1;
        const label = `16B·${phraseNum}`;

        ctx.save();
        ctx.fillStyle = 'rgba(0,0,0,0.6)';
        ctx.fillRect(x - 20, RULER_HEIGHT + 2, 40, 12);
        ctx.restore();

        ctx.fillStyle = COLORS.phraseLabel;
        ctx.fillText(label, x, RULER_HEIGHT + 11);

        // Triangle
        ctx.beginPath();
        ctx.moveTo(x - 5, RULER_HEIGHT);
        ctx.lineTo(x + 5, RULER_HEIGHT);
        ctx.lineTo(x, RULER_HEIGHT + 5);
        ctx.fill();
    }

    ctx.setLineDash([]);
}

// ── WAVEFORMS (3-Band RGB with LOD) ────────────────────────────────────────────

function drawWaveforms(ctx, ds, startTime, endTime) {
    const { width, height, zoom, scrollX, regions, bandPeaks, fallbackPeaks, totalDuration, lodLevel, waveformStyle } = ds;

    const hasBandPeaks = bandPeaks && bandPeaks.low && bandPeaks.low.length > 0;
    const hasFallback = fallbackPeaks && fallbackPeaks.length > 0;
    if (!hasBandPeaks && !hasFallback) return;
    if (totalDuration <= 0) return;

    const waveTop = RULER_HEIGHT;
    const waveHeight = height - RULER_HEIGHT;
    const centerY = waveTop + waveHeight / 2;
    const maxAmp = waveHeight * 0.42;

    // Pick LOD peaks (use lod sub-object if available, else use top-level)
    let activePeaks;
    if (hasBandPeaks) {
        if (bandPeaks.lod) {
            if (lodLevel >= 4) activePeaks = bandPeaks.lod.r4;
            else if (lodLevel >= 2) activePeaks = bandPeaks.lod.r2;
            else activePeaks = bandPeaks.lod.r1;
        } else {
            activePeaks = bandPeaks; // legacy format
        }
    }

    for (const region of regions) {
        // EC16: skip zero-duration regions
        if (!region.duration || region.duration <= 0) continue;

        const regionEnd = region.timelineStart + region.duration;
        if (regionEnd < startTime || region.timelineStart > endTime) continue;

        const regionStartPx = Math.max(0, region.timelineStart * zoom - scrollX);
        const regionEndPx = Math.min(width, regionEnd * zoom - scrollX);
        if (regionEndPx <= regionStartPx) continue;

        if (hasBandPeaks && activePeaks) {
            const isBassOnly = waveformStyle === 'bass';
            const bands = isBassOnly
                ? [{ peaks: activePeaks.low, color: COLORS.lowBand }]
                : [
                    { peaks: activePeaks.low, color: COLORS.lowBand },
                    { peaks: activePeaks.mid, color: COLORS.midBand },
                    { peaks: activePeaks.high, color: COLORS.highBand },
                ];

            for (const band of bands) {
                if (!band.peaks || band.peaks.length === 0) continue;
                drawBandForRegion(ctx, band.peaks, band.color, region, regionStartPx, regionEndPx,
                    scrollX, zoom, totalDuration, centerY, maxAmp, lodLevel, waveformStyle);
            }
        } else if (hasFallback) {
            drawBandForRegion(ctx, fallbackPeaks, 'rgba(255,255,255,0.55)', region, regionStartPx, regionEndPx,
                scrollX, zoom, totalDuration, centerY, maxAmp, lodLevel, waveformStyle);
        }
    }
}

function drawBandForRegion(ctx, peaks, color, region, regionStartPx, regionEndPx, scrollX, zoom, totalDuration, centerY, maxAmp, lodLevel, style) {
    // EC12: validate peaks array
    if (!peaks || peaks.length === 0) return;

    if (style === 'liquid') {
        ctx.fillStyle = color;
        ctx.beginPath();

        const step = Math.max(2, lodLevel * 2);

        ctx.moveTo(Math.floor(regionStartPx), centerY);

        // Top edge (forward)
        for (let px = Math.floor(regionStartPx); px < regionEndPx; px += step) {
            const time = (px + scrollX) / zoom;
            const regionLocalTime = time - region.timelineStart;
            const sourceTime = region.sourceStart + regionLocalTime;
            const rawIdx = (sourceTime / totalDuration) * peaks.length;
            const peakIndex = Math.floor(rawIdx);
            const frac = rawIdx - peakIndex; // EC2: bi-linear fraction

            if (peakIndex < 0 || peakIndex >= peaks.length) continue;
            const p0 = peaks[peakIndex];
            const p1 = peakIndex + 1 < peaks.length ? peaks[peakIndex + 1] : p0;
            if (!p0 || isNaN(p0.max)) continue; // EC12

            // EC2: interpolated max
            const interpMax = p0.max + (p1.max - p0.max) * frac;

            const y = centerY - (interpMax * maxAmp);
            if (px === Math.floor(regionStartPx)) {
                ctx.lineTo(px, y);
            } else {
                const prevPx = px - step;
                const prevTime = (prevPx + scrollX) / zoom;
                const prevLocal = prevTime - region.timelineStart;
                const prevIdx = Math.floor(((region.sourceStart + prevLocal) / totalDuration) * peaks.length);
                const prevPeak = peaks[prevIdx] || p0;
                const midX = (prevPx + px) / 2;
                const midY = (centerY - (prevPeak.max * maxAmp) + y) / 2;
                ctx.quadraticCurveTo(prevPx, centerY - (prevPeak.max * maxAmp), midX, midY);
            }
        }

        // Bottom edge (reverse)
        for (let px = Math.ceil(regionEndPx); px >= Math.floor(regionStartPx); px -= step) {
            const time = (px + scrollX) / zoom;
            const regionLocalTime = time - region.timelineStart;
            const sourceTime = region.sourceStart + regionLocalTime;
            const rawIdx = (sourceTime / totalDuration) * peaks.length;
            const peakIndex = Math.floor(rawIdx);
            const frac = rawIdx - peakIndex;

            if (peakIndex < 0 || peakIndex >= peaks.length) continue;
            const p0 = peaks[peakIndex];
            const p1 = peakIndex + 1 < peaks.length ? peaks[peakIndex + 1] : p0;
            if (!p0 || isNaN(p0.min)) continue;

            const interpMin = p0.min + (p1.min - p0.min) * frac;
            const y = centerY - (interpMin * maxAmp);

            if (px === Math.ceil(regionEndPx)) {
                ctx.lineTo(px, y);
            } else {
                const prevPx = px + step;
                const prevTime = (prevPx + scrollX) / zoom;
                const prevLocal = prevTime - region.timelineStart;
                const prevIdx = Math.floor(((region.sourceStart + prevLocal) / totalDuration) * peaks.length);
                const prevPeak = peaks[prevIdx] || p0;
                const midX = (prevPx + px) / 2;
                const midY = (centerY - (prevPeak.min * maxAmp) + y) / 2;
                ctx.quadraticCurveTo(prevPx, centerY - (prevPeak.min * maxAmp), midX, midY);
            }
        }

        ctx.closePath();
        ctx.fill();

    } else {
        // DETAIL STYLE: vertical bars
        ctx.strokeStyle = color;
        ctx.lineCap = 'round';

        const barWidth = 2;
        const gap = 1;
        const step = Math.max(barWidth + gap, lodLevel);

        ctx.lineWidth = barWidth;
        ctx.beginPath();

        for (let px = Math.floor(regionStartPx); px < regionEndPx; px += step) {
            const time = (px + scrollX) / zoom;
            const regionLocalTime = time - region.timelineStart;
            const sourceTime = region.sourceStart + regionLocalTime;

            const rawIdx = (sourceTime / totalDuration) * peaks.length;
            const peakIndex = Math.floor(rawIdx);
            const frac = rawIdx - peakIndex; // EC2

            if (peakIndex < 0 || peakIndex >= peaks.length) continue;

            const p0 = peaks[peakIndex];
            const p1 = peakIndex + 1 < peaks.length ? peaks[peakIndex + 1] : p0;
            if (!p0 || isNaN(p0.max) || isNaN(p0.min)) continue; // EC12

            // EC2: interpolated peak values at high zoom
            const interpMax = p0.max + (p1.max - p0.max) * frac;
            const interpMin = p0.min + (p1.min - p0.min) * frac;

            const h = (interpMax - interpMin) * maxAmp;
            if (h < 0.5) continue; // skip silence

            const y1 = centerY + interpMin * maxAmp;
            const y2 = centerY + interpMax * maxAmp;

            ctx.moveTo(px + barWidth / 2, y1);
            ctx.lineTo(px + barWidth / 2, y2);
        }

        ctx.stroke();
    }
}

// ── REGION BOUNDARIES ───────────────────────────────────────────────────────────

function drawRegionBoundaries(ctx, ds, startTime, endTime) {
    const { width, height, zoom, scrollX, regions, selectedIds } = ds;

    for (const region of regions) {
        if (!region.duration || region.duration <= 0) continue;
        const regionEnd = region.timelineStart + region.duration;
        if (regionEnd < startTime || region.timelineStart > endTime) continue;

        const x1 = region.timelineStart * zoom - scrollX;
        const x2 = regionEnd * zoom - scrollX;
        const isSelected = selectedIds.has(region.id);

        if (isSelected) {
            ctx.fillStyle = COLORS.selectionFill;
            ctx.fillRect(x1, RULER_HEIGHT, x2 - x1, height - RULER_HEIGHT);
        }

        ctx.strokeStyle = isSelected ? COLORS.regionSelectedBorder : COLORS.regionBorder;
        ctx.lineWidth = isSelected ? 2 : 1;

        ctx.beginPath();
        ctx.moveTo(Math.round(x1) + 0.5, RULER_HEIGHT);
        ctx.lineTo(Math.round(x1) + 0.5, height);
        ctx.stroke();

        ctx.beginPath();
        ctx.moveTo(Math.round(x2) + 0.5, RULER_HEIGHT);
        ctx.lineTo(Math.round(x2) + 0.5, height);
        ctx.stroke();
    }
}

// ── SELECTION RANGE ─────────────────────────────────────────────────────────────

function drawSelectionRange(ctx, ds, startTime, endTime) {
    const { width, height, zoom, scrollX, selectionRange } = ds;
    if (!selectionRange) return;

    const { start, end } = selectionRange;
    if (end <= start) return;
    if (end < startTime || start > endTime) return;

    const x1 = Math.round(start * zoom - scrollX);
    const x2 = Math.round(end * zoom - scrollX);

    if (x2 < 0 || x1 > width) return;

    ctx.fillStyle = COLORS.selectionFill;
    ctx.fillRect(x1, RULER_HEIGHT, x2 - x1, height - RULER_HEIGHT);

    ctx.strokeStyle = COLORS.selectionBorder;
    ctx.lineWidth = 1;
    ctx.strokeRect(x1 + 0.5, RULER_HEIGHT + 0.5, x2 - x1, height - RULER_HEIGHT - 1);
}

// ── CUE MARKERS (with collision detection, EC5) ─────────────────────────────────

function drawCueMarkers(ctx, ds, startTime, endTime) {
    const { width, height, zoom, scrollX, hotCues, memoryCues, ghostCueX } = ds;

    // ── EC5: collision detection for hot cue labels ──
    // Compute x positions, then stagger overlapping ones vertically
    const hotCuePositions = [];
    for (let i = 0; i < hotCues.length; i++) {
        const cue = hotCues[i];
        if (!cue) continue;
        const x = Math.round(cue.time * zoom - scrollX) + 0.5;
        if (x < -10 || x > width + 10) continue;
        hotCuePositions.push({ i, x, cue });
    }

    // Sort by x, detect collision (within 20px), assign row
    hotCuePositions.sort((a, b) => a.x - b.x);
    const rows = []; // rows[i] = last x that occupied this row

    for (const item of hotCuePositions) {
        let row = 0;
        while (rows[row] !== undefined && item.x - rows[row] < 20) {
            row++;
        }
        rows[row] = item.x;
        item.row = row;
    }

    // Draw hot cues
    for (const { i, x, cue, row } of hotCuePositions) {
        const color = `rgb(${cue.red},${cue.green},${cue.blue})`;
        const labelY = row * 14; // EC5: stagger by row height

        // Vertical line (full height)
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(x, RULER_HEIGHT);
        ctx.lineTo(x, height);
        ctx.stroke();

        // Flag triangle + box
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.moveTo(x, labelY);
        ctx.lineTo(x + 14, labelY);
        ctx.lineTo(x + 14, labelY + 10);
        ctx.lineTo(x + 4, labelY + 16);
        ctx.lineTo(x, labelY + 16);
        ctx.closePath();
        ctx.fill();

        // Label
        ctx.fillStyle = '#000';
        ctx.font = 'bold 8px Inter, system-ui, sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText(String.fromCharCode(65 + i), x + 3, labelY + 11);
    }

    // Draw memory cues
    for (const mem of memoryCues) {
        const x = Math.round(mem.time * zoom - scrollX) + 0.5;
        if (x < -10 || x > width + 10) continue;

        const color = `rgb(${mem.red ?? 255},${mem.green ?? 0},${mem.blue ?? 0})`;

        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.moveTo(x - 5, RULER_HEIGHT);
        ctx.lineTo(x + 5, RULER_HEIGHT);
        ctx.lineTo(x, RULER_HEIGHT + 8);
        ctx.closePath();
        ctx.fill();

        ctx.strokeStyle = COLORS.memoryCueDash;
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(x, RULER_HEIGHT + 8);
        ctx.lineTo(x, height);
        ctx.stroke();
        ctx.setLineDash([]);
    }

    // Ghost cue (being dragged) — EC3
    if (ghostCueX !== null) {
        ctx.strokeStyle = COLORS.ghostCue;
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 4]);
        ctx.beginPath();
        ctx.moveTo(ghostCueX + 0.5, 0);
        ctx.lineTo(ghostCueX + 0.5, height);
        ctx.stroke();
        ctx.setLineDash([]);
    }
}

// ── LOOPS ───────────────────────────────────────────────────────────────────────

function drawLoops(ctx, ds, startTime, endTime) {
    const { width, height, zoom, scrollX, loops, activeLoopIndex } = ds;

    for (let i = 0; i < loops.length; i++) {
        const loop = loops[i];
        if (!loop.startTime && loop.startTime !== 0) continue;
        const x1 = loop.startTime * zoom - scrollX;
        const x2 = (loop.endTime ?? loop.startTime + 4) * zoom - scrollX;

        if (x2 < 0 || x1 > width) continue;

        const isActive = i === activeLoopIndex;
        const color = `rgb(${loop.red ?? 251},${loop.green ?? 146},${loop.blue ?? 60})`;

        ctx.fillStyle = isActive
            ? `rgba(${loop.red ?? 251},${loop.green ?? 146},${loop.blue ?? 60}, 0.16)`
            : COLORS.loopFill;
        ctx.fillRect(x1, RULER_HEIGHT, x2 - x1, height - RULER_HEIGHT);

        ctx.strokeStyle = isActive ? color : COLORS.loopBorder;
        ctx.lineWidth = isActive ? 2 : 1;

        ctx.beginPath();
        ctx.moveTo(Math.round(x1) + 0.5, RULER_HEIGHT);
        ctx.lineTo(Math.round(x1) + 0.5, height);
        ctx.stroke();

        ctx.beginPath();
        ctx.moveTo(Math.round(x2) + 0.5, RULER_HEIGHT);
        ctx.lineTo(Math.round(x2) + 0.5, height);
        ctx.stroke();

        // Loop label
        if (x2 - x1 > 20) {
            ctx.fillStyle = color;
            ctx.font = '7px Inter, system-ui, sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText(loop.name || `L${i + 1}`, ((x1 + x2) / 2), RULER_HEIGHT + 9);
        }

        // Bracket handles
        ctx.fillStyle = color;
        ctx.fillRect(Math.round(x1), RULER_HEIGHT, 3, 16);
        ctx.fillRect(Math.round(x2) - 3, RULER_HEIGHT, 3, 16);
    }
}

// ── PLAYHEAD ─────────────────────────────────────────────────────────────────────

function drawPlayhead(ctx, ds) {
    const { width, height, zoom, scrollX, playhead } = ds;

    const x = Math.round(playhead * zoom - scrollX) + 0.5;
    if (x < -2 || x > width + 2) return;

    // Outer glow (wide)
    ctx.strokeStyle = COLORS.playheadGlow2;
    ctx.lineWidth = 9;
    ctx.beginPath();
    ctx.moveTo(x, RULER_HEIGHT);
    ctx.lineTo(x, height);
    ctx.stroke();

    // Inner glow
    ctx.strokeStyle = COLORS.playheadGlow;
    ctx.lineWidth = 3;
    ctx.beginPath();
    ctx.moveTo(x, RULER_HEIGHT);
    ctx.lineTo(x, height);
    ctx.stroke();

    // Main line
    ctx.strokeStyle = COLORS.playhead;
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, height);
    ctx.stroke();

    // Triangle at top
    ctx.fillStyle = COLORS.playhead;
    ctx.beginPath();
    ctx.moveTo(x - 6, 0);
    ctx.lineTo(x + 6, 0);
    ctx.lineTo(x, 9);
    ctx.closePath();
    ctx.fill();
}

// ── RULER ─────────────────────────────────────────────────────────────────────────

function drawRuler(ctx, ds, startTime, endTime) {
    const { width, zoom, scrollX, bpm, firstBeatSec } = ds;

    // Ruler background
    ctx.fillStyle = COLORS.rulerBg;
    ctx.fillRect(0, 0, width, RULER_HEIGHT);

    // Bottom border
    ctx.strokeStyle = COLORS.rulerLine;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, RULER_HEIGHT - 0.5);
    ctx.lineTo(width, RULER_HEIGHT - 0.5);
    ctx.stroke();

    if (!bpm || bpm <= 0) return;

    const beatDuration = 60 / bpm;
    const barDuration = beatDuration * 4;
    const pixelsPerBar = barDuration * zoom;

    let labelInterval = barDuration;
    if (pixelsPerBar < 40) labelInterval = barDuration * 4;
    if (pixelsPerBar < 15) labelInterval = barDuration * 16;

    const firstLabel = Math.floor((startTime - firstBeatSec) / labelInterval) * labelInterval + firstBeatSec;

    ctx.font = '8px Inter, system-ui, sans-serif';
    ctx.textAlign = 'center';

    for (let t = firstLabel; t <= endTime + labelInterval; t += labelInterval) {
        if (t < 0) continue;
        const x = Math.round(t * zoom - scrollX);
        if (x < -40 || x > width + 40) continue;

        // Tick
        ctx.strokeStyle = COLORS.rulerTick;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(x + 0.5, RULER_HEIGHT - 5);
        ctx.lineTo(x + 0.5, RULER_HEIGHT - 1);
        ctx.stroke();

        // Time label mm:ss
        const mins = Math.floor(t / 60);
        const secs = Math.floor(t % 60);
        ctx.fillStyle = COLORS.rulerText;
        ctx.fillText(`${mins}:${secs.toString().padStart(2, '0')}`, x, RULER_HEIGHT - 7);
    }
}

DawTimeline.displayName = 'DawTimeline';

export default DawTimeline;
