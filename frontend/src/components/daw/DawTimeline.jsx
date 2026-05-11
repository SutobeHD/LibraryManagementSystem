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
 * All ECs from Phase 1 preserved. New additions:
 *   Phase Meter — 8px beat-phase indicator strip at canvas bottom
 *   Gradient fills — vertical linear gradient per band
 *   OffscreenCanvas — waveform cache invalidated by zoom/data key
 */

import React, { useRef, useEffect, useCallback } from 'react';
import { snapToGrid } from '../../audio/DawState';
import * as DawEngine from '../../audio/DawEngine';

// ─── CONSTANTS ──────────────────────────────────────────────────────────────────

const RULER_HEIGHT = 22;
const PHASE_METER_HEIGHT = 8;

// ─── COLORS ─────────────────────────────────────────────────────────────────────

const COLORS = {
    background: '#090c17',
    rulerBg: '#070a12',
    rulerText: 'rgba(255,255,255,0.45)',
    rulerLine: 'rgba(255,255,255,0.08)',
    rulerTick: 'rgba(255,255,255,0.28)',
    gridBar: 'rgba(239, 68, 68, 0.35)',
    gridBeat: 'rgba(255, 255, 255, 0.08)',
    gridSub: 'rgba(255, 255, 255, 0.025)',
    phraseMarker: '#F87171',
    phraseLabel: 'rgba(248, 113, 113, 0.9)',
    playhead: '#ffffff',
    playheadGlow: 'rgba(255,255,255,0.22)',
    playheadGlow2: 'rgba(255,255,255,0.07)',
    selectionFill: 'rgba(56, 189, 248, 0.09)',
    selectionBorder: 'rgba(56, 189, 248, 0.45)',
    regionBorder: 'rgba(255,255,255,0.12)',
    regionSelectedBorder: '#38bdf8',
    // CDJ 3-Band: Low=Red, Mid=Green, High=Blue
    low: { top: 'rgba(255,32,64,0.92)', bot: 'rgba(140,0,20,0.18)' },
    mid: { top: 'rgba(0,220,120,0.88)', bot: 'rgba(0,100,45,0.18)' },
    high: { top: 'rgba(0,148,255,0.88)', bot: 'rgba(0,40,160,0.18)' },
    fallback: { top: 'rgba(180,180,200,0.72)', bot: 'rgba(60,60,80,0.18)' },
    memoryCueDash: 'rgba(239,68,68,0.55)',
    loopFill: 'rgba(251, 146, 60, 0.09)',
    loopBorder: 'rgba(251, 146, 60, 0.52)',
    ghostCue: 'rgba(255,255,255,0.38)',
    phaseMeterBg: 'rgba(255,255,255,0.04)',
    phaseMeterFill: 'rgba(0,229,255,0.85)',
    phaseMeterLate: 'rgba(255,145,0,0.85)',
};

// ─── MODULE-LEVEL CACHE ─────────────────────────────────────────────────────────

const peakCacheMap = new Map(); // legacy compat

// ─── GRADIENT FACTORY (per draw, cached per canvas height) ──────────────────────

function makeBandGradient(ctx, centerY, maxAmp, bandKey) {
    const c = COLORS[bandKey];
    const top = centerY - maxAmp;
    const bot = centerY + maxAmp;
    const g = ctx.createLinearGradient(0, top, 0, bot);
    g.addColorStop(0,   c.top);
    g.addColorStop(0.5, c.top.replace('0.92', '0.55').replace('0.88', '0.50'));
    g.addColorStop(1,   c.bot);
    return g;
}

// ─── COMPONENT ──────────────────────────────────────────────────────────────────

const DawTimeline = React.memo(({
    state,
    dispatch,
    canvasHeight = null, // null = fill container (preferred). Number = fixed pixel height
    minCanvasHeight = 200, // floor when filling container (avoid degenerate state during layout)
    onRegionClick,
    onContextMenu,
}) => {
    const canvasRef       = useRef(null);
    const containerRef    = useRef(null);
    const animFrameRef    = useRef(null);
    const resizeTimerRef  = useRef(null);
    const roRef           = useRef(null);
    const isDragging      = useRef(false);
    const dragStartTime   = useRef(0);
    const draggingCue     = useRef(null);
    const goodFrames      = useRef(0);

    // OffscreenCanvas waveform cache
    const waveformBitmap  = useRef(null); // ImageBitmap
    const waveformKey     = useRef('');   // invalidation key

    // Mutable draw state — decoupled from React renders
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

    // ── SYNC REACT → DRAW STATE ──────────────────────────────────────────────────
    useEffect(() => {
        const d = ds.current;
        // dispatch is needed by the RAF loop to keep state.scrollX in sync
        // with the smoothly auto-following d.scrollX during playback.
        d.dispatch = dispatch;
        d.zoom = state.zoom;

        if (!state.isPlaying || Math.abs(d.scrollX - state.scrollX) > window.innerWidth * 0.5) {
            d.scrollX = state.scrollX;
        }
        if (!state.isPlaying) d.playhead = state.playhead;

        d.isPlaying   = state.isPlaying;
        d.regions     = state.regions;
        d.selectedIds = state.selectedRegionIds;
        d.bpm         = state.bpm;
        d.snapDivision = state.snapDivision || '1/4';
        d.firstBeatSec = ((state.tempoMap?.[0]?.positionMs || 0) / 1000) + (state.gridOffsetSec || 0);
        d.totalDuration = state.totalDuration;
        // Source duration drives peak indexing. AudioBuffer wins (most
        // authoritative). trackMeta.duration is set in handleFileSelect for
        // .rbep loads. totalDuration is the last-resort fallback for simple
        // track-loads where source == timeline.
        d.sourceDuration = state.sourceBuffer?.duration
            || state.trackMeta?.duration
            || state.totalDuration;
        d.hotCues      = state.hotCues;
        d.memoryCues   = state.memoryCues;
        d.loops        = state.loops;
        d.activeLoopIndex = state.activeLoopIndex;
        d.snapEnabled  = state.snapEnabled;
        d.slipMode     = state.slipMode || false;
        d.waveformStyle = state.waveformStyle || '3band';
        d.selectionRange = state.selectionRange;

        // Detect waveform data change → force rebuild. scrollX is included so manual
        // scroll/zoom triggers a rebuild (the bitmap covers only the visible window).
        // regionsSig is critical: insert/paste/move/delete of regions changes the
        // bitmap content but leaves zoom/scroll/peaks/style untouched, so without
        // a per-region signature here the cached bitmap would show the OLD region
        // layout while audio plays the NEW one — visible as "gap where audio
        // continues through". Hash uses timelineStart + duration + sourceStart so
        // any structural mutation triggers a rebuild; length-only would miss
        // in-place edits (drag, trim).
        let regionsSig = state.regions?.length || 0;
        if (state.regions?.length) {
            let h = 0;
            for (const r of state.regions) {
                const sample = ((r.timelineStart || 0) + (r.duration || 0) + (r.sourceStart || 0)) * 1000;
                h = ((h << 5) - h + Math.floor(sample)) | 0;
            }
            regionsSig = `${state.regions.length}:${h}`;
        }
        const newKey = `${state.totalDuration?.toFixed(2)}-${state.zoom?.toFixed(0)}-${Math.round(d.scrollX)}-${d.lodLevel}-${!!state.bandPeaks}-${!!state.fallbackPeaks}-${state.waveformStyle}-${regionsSig}`;
        if (newKey !== waveformKey.current) {
            d.needsWaveformRebuild = true;
            waveformKey.current = newKey;
        }

        d.bandPeaks    = state.bandPeaks;
        d.fallbackPeaks = state.fallbackPeaks || null;
        d.deadReckoning = state.deadReckoning || { lastSyncWallClock: 0, lastSyncAudioTime: 0 };
        d.needsRedraw  = true;
    }, [state]);

    // ── RESIZE HANDLER (EC1 debounce, EC7 DPR) ───────────────────────────────────
    useEffect(() => {
        const container = containerRef.current;
        if (!container) return;

        const apply = () => {
            const rect = container.getBoundingClientRect();
            const d = ds.current;
            d.dpr   = window.devicePixelRatio || 1;
            d.width = rect.width;
            // Dynamic-height mode: derive from container so the timeline
            // expands into whatever vertical space DjEditDaw's flex layout
            // hands it. Fixed-height callers can still pass a `canvasHeight`
            // number. `minCanvasHeight` guards against rare cases where the
            // container reports 0 mid-mount (e.g., display:none ancestor).
            d.height = canvasHeight ?? Math.max(minCanvasHeight, rect.height);
            const canvas = canvasRef.current;
            if (canvas) {
                canvas.width  = Math.round(d.width  * d.dpr);
                canvas.height = Math.round(d.height * d.dpr);
                canvas.style.width  = `${d.width}px`;
                canvas.style.height = `${d.height}px`;
            }
            d.needsWaveformRebuild = true;
            d.needsRedraw = true;
        };

        const onResize = () => {
            clearTimeout(resizeTimerRef.current);
            resizeTimerRef.current = setTimeout(apply, 16); // EC1
        };

        roRef.current = new ResizeObserver(onResize);
        roRef.current.observe(container);
        apply();

        return () => {
            roRef.current?.disconnect();
            clearTimeout(resizeTimerRef.current);
        };
    }, [canvasHeight, minCanvasHeight]);

    // ── MAIN RAF LOOP ─────────────────────────────────────────────────────────────
    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;
        const ctx = canvas.getContext('2d', { alpha: false });

        const frame = (ts) => {
            const d = ds.current;

            // Smooth auto-follow during playback. The previous threshold
            // approach (jump scrollX by 40% when playhead crosses 70%)
            // produced a visible jerk every few seconds AND left the
            // scrollbar's state.scrollX out of sync — so when playback
            // stopped, the waveform snapped back to the saved scroll
            // position. Both visible as the user-reported "scroll bar
            // grows then springs back".
            //
            // New behavior: each frame, lerp d.scrollX toward a target
            // that keeps the playhead 30% from the left edge. Smooth
            // linear interpolation (factor 0.18) catches up over ~6
            // frames (~100ms) without per-frame jumps. Bitmap is only
            // rebuilt when the smoothed scrollX drifts beyond a
            // tolerance — keeps RAF fast.
            if (d.isPlaying) {
                d.playhead = DawEngine.getCurrentTime();
                const phPx = d.playhead * d.zoom;
                const targetScroll = Math.max(0, phPx - d.width * 0.3);
                const delta = targetScroll - d.scrollX;
                if (Math.abs(delta) > 0.5) {
                    // Linear lerp; no easing needed at this rate
                    d.scrollX += delta * 0.18;
                    // Rebuild bitmap when the scroll delta exceeds the
                    // safe overscan range. drawFrame translates the
                    // bitmap by (lastBuiltScrollX - scrollX) so smaller
                    // deltas remain visually continuous without rebuild;
                    // we only rebuild when the bitmap's right edge would
                    // start uncovering the view (≈100 px of headroom
                    // here, leaving a thin un-translated strip that
                    // disappears on the next rebuild). The actual
                    // lastBuiltScrollX update happens at the rebuild
                    // site below — setting it here would tell the
                    // translation code that the bitmap was already
                    // re-anchored before it actually was.
                    if (Math.abs(d.scrollX - (d.lastBuiltScrollX || 0)) > 100) {
                        d.needsWaveformRebuild = true;
                    }
                }
                // Push state.scrollX in sync periodically so the scrollbar
                // tracks the waveform AND so playback stop doesn't snap
                // the view back to the pre-play scroll position.
                d.scrollSyncAccum = (d.scrollSyncAccum || 0) + 1;
                if (d.scrollSyncAccum >= 12) {  // ~5 dispatches/sec at 60fps
                    d.scrollSyncAccum = 0;
                    if (d.dispatch) d.dispatch({ type: 'SET_SCROLL_X', payload: d.scrollX });
                }
            }

            // LOD hysteresis (EC25)
            if (d.lastFrameTime > 0) {
                const delta = ts - d.lastFrameTime;
                if (delta > 22) {
                    goodFrames.current = 0;
                    d.lodLevel = Math.min(4, d.lodLevel + 1);
                    d.needsWaveformRebuild = true;
                } else if (delta < 15) {
                    goodFrames.current++;
                    if (goodFrames.current >= 60) {
                        goodFrames.current = 0;
                        const prev = d.lodLevel;
                        d.lodLevel = Math.max(1, d.lodLevel - 1);
                        if (d.lodLevel !== prev) d.needsWaveformRebuild = true;
                    }
                }
            }
            d.lastFrameTime = ts;

            // Rebuild static waveform bitmap when needed. Stamp the
            // scrollX it was built for so drawFrame can translate the
            // bitmap by the live-vs-built delta (smooth scroll without
            // forcing a per-frame rebuild).
            if (d.needsWaveformRebuild && d.width > 0) {
                waveformBitmap.current = buildWaveformBitmap(d);
                d.lastBuiltScrollX = d.scrollX;
                d.needsWaveformRebuild = false;
                d.needsRedraw = true;
            }

            if (d.needsRedraw || d.isPlaying) {
                drawFrame(ctx, d, waveformBitmap.current);
                d.needsRedraw = false;
            }

            animFrameRef.current = requestAnimationFrame(frame);
        };

        animFrameRef.current = requestAnimationFrame(frame);
        return () => {
            cancelAnimationFrame(animFrameRef.current);
            peakCacheMap.clear(); // EC10
            waveformBitmap.current = null;
        };
    }, []);

    // ── HIT TEST CUE FLAGS ────────────────────────────────────────────────────────
    const hitTestCue = useCallback((x, y, d) => {
        for (let i = 0; i < d.hotCues.length; i++) {
            const cue = d.hotCues[i];
            if (!cue) continue;
            const cx = Math.round(cue.time * d.zoom - d.scrollX);
            if (x >= cx && x <= cx + 14 && y >= 0 && y <= 16) {
                return { type: 'hot', index: i };
            }
        }
        for (let i = 0; i < d.memoryCues.length; i++) {
            const mem = d.memoryCues[i];
            const cx = Math.round(mem.time * d.zoom - d.scrollX);
            if (Math.abs(x - cx) <= 6 && y >= RULER_HEIGHT && y <= RULER_HEIGHT + 10) {
                return { type: 'memory', index: i };
            }
        }
        return null;
    }, []);

    // ── MOUSE HANDLERS ─────────────────────────────────────────────────────────────
    const handleMouseDown = useCallback((e) => {
        const canvas = canvasRef.current;
        if (!canvas) return;
        const rect  = canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;
        const d = ds.current;
        let time = (x + d.scrollX) / d.zoom;

        if (d.snapEnabled && !d.slipMode && d.bpm > 0) {
            time = snapToGrid(time, d.bpm, d.snapDivision, d.firstBeatSec);
        }

        if (e.button === 0) {
            const cueHit = hitTestCue(x, y, d);
            if (cueHit) { draggingCue.current = cueHit; d.ghostCueX = x; return; }

            dispatch({ type: 'SET_PLAYHEAD', payload: Math.max(0, time) });
            isDragging.current = true;
            dragStartTime.current = time;

            const clickedRegion = d.regions.find(r => {
                const rx = r.timelineStart * d.zoom - d.scrollX;
                return x >= rx && x <= rx + r.duration * d.zoom;
            });

            if (clickedRegion) {
                dispatch({ type: e.ctrlKey ? 'TOGGLE_SELECT_REGION' : 'SELECT_REGION', payload: clickedRegion.id });
            } else {
                if (!e.ctrlKey) {
                    dispatch({ type: 'SET_SELECTION_RANGE', payload: { start: time, end: time } });
                    dispatch({ type: 'CLEAR_SELECTION' });
                }
            }
        } else if (e.button === 2 && onContextMenu) {
            onContextMenu(time, e);
        }
    }, [dispatch, onContextMenu, hitTestCue]);

    const handleMouseMove = useCallback((e) => {
        const canvas = canvasRef.current;
        if (!canvas) return;
        const rect = canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const d = ds.current;

        if (draggingCue.current) { d.ghostCueX = x; d.needsRedraw = true; return; }
        if (!isDragging.current) return;

        let time = (x + d.scrollX) / d.zoom;
        if (d.snapEnabled && !d.slipMode && d.bpm > 0) {
            time = snapToGrid(time, d.bpm, d.snapDivision, d.firstBeatSec);
        }
        const start = Math.min(dragStartTime.current, time);
        const end   = Math.max(dragStartTime.current, time);
        if (Math.abs(end - start) > 0.01) {
            dispatch({ type: 'SET_SELECTION_RANGE', payload: { start, end } });
        }
    }, [dispatch]);

    const handleMouseUp = useCallback((e) => {
        const canvas = canvasRef.current;
        if (draggingCue.current && canvas) {
            const rect = canvas.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const d = ds.current;
            let time = Math.max(0, Math.min(d.totalDuration, (x + d.scrollX) / d.zoom));
            if (d.snapEnabled && d.bpm > 0) time = snapToGrid(time, d.bpm, d.snapDivision, d.firstBeatSec);

            const { type, index } = draggingCue.current;
            if (type === 'hot') {
                const cue = d.hotCues[index];
                if (cue) dispatch({ type: 'SET_HOT_CUE', payload: { index, cue: { ...cue, time } } });
            } else {
                const mem = d.memoryCues[index];
                if (mem) {
                    dispatch({ type: 'REMOVE_MEMORY_CUE', payload: index });
                    dispatch({ type: 'ADD_MEMORY_CUE', payload: { ...mem, time } });
                }
            }
            draggingCue.current = null;
            d.ghostCueX = null;
            d.needsRedraw = true;
        }
        isDragging.current = false;
    }, [dispatch]);

    const handleWheel = useCallback((e) => {
        e.preventDefault();
        const d = ds.current;
        if (e.ctrlKey || e.metaKey) {
            const rect = canvasRef.current.getBoundingClientRect();
            const mouseX = e.clientX - rect.left;
            const timeBefore = (mouseX + d.scrollX) / d.zoom;
            const zoomDelta = e.deltaY > 0 ? 0.85 : 1.18;
            const newZoom = Math.max(10, Math.min(2000, d.zoom * zoomDelta));
            dispatch({ type: 'SET_ZOOM', payload: newZoom });
            dispatch({ type: 'SET_SCROLL_X', payload: Math.max(0, timeBefore * newZoom - mouseX) });
        } else {
            dispatch({ type: 'SET_SCROLL_X', payload: Math.max(0, d.scrollX + (e.deltaY || e.deltaX) * 2) });
        }
    }, [dispatch]);

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

// ═══════════════════════════════════════════════════════════════════════════════
// OFFSCREEN CANVAS — BUILD STATIC WAVEFORM BITMAP
// ═══════════════════════════════════════════════════════════════════════════════

function buildWaveformBitmap(d) {
    const { width, height, dpr, zoom, scrollX, regions, bandPeaks, fallbackPeaks, sourceDuration, lodLevel, waveformStyle } = d;
    if (width <= 0 || height <= 0) return null;

    const hasBand  = bandPeaks && (bandPeaks.low?.length > 0 || bandPeaks.lod?.r1?.low?.length > 0);
    const hasMono  = fallbackPeaks && fallbackPeaks.length > 0;
    if (!hasBand && !hasMono) return null;
    // sourceDuration is the audio-buffer length the peaks were generated
    // from. Without it, peak-index calculations would mis-stretch the
    // waveform across the edit timeline (.rbep projects).
    if (!sourceDuration || sourceDuration <= 0) return null;

    const oc = new OffscreenCanvas(Math.round(width * dpr), Math.round(height * dpr));
    const ctx = oc.getContext('2d', { alpha: true });
    ctx.scale(dpr, dpr);

    // Transparent background (painted over the main canvas bg)
    ctx.clearRect(0, 0, width, height);

    const waveTop = RULER_HEIGHT;
    const waveBot = height - PHASE_METER_HEIGHT;
    const waveH   = waveBot - waveTop;
    const centerY = waveTop + waveH / 2;
    const maxAmp  = waveH * 0.44;

    // Pick LOD peaks
    let activePeaks = {};
    if (hasBand) {
        if (bandPeaks.lod) {
            const lodKey = lodLevel >= 4 ? 'r4' : lodLevel >= 2 ? 'r2' : 'r1';
            activePeaks = bandPeaks.lod[lodKey];
        } else {
            activePeaks = bandPeaks;
        }
    }

    const startTime = scrollX / zoom;
    const endTime   = (scrollX + width) / zoom;

    for (const region of regions) {
        if (!region.duration || region.duration <= 0) continue; // EC16
        const regionEnd = region.timelineStart + region.duration;
        if (regionEnd < startTime || region.timelineStart > endTime) continue;

        const rStartPx = Math.max(0,     region.timelineStart * zoom - scrollX);
        const rEndPx   = Math.min(width, regionEnd            * zoom - scrollX);
        if (rEndPx <= rStartPx) continue;

        // Style dispatcher:
        //   '3band' (default) → per-pixel RGB composition (Rekordbox-style:
        //                       hue encodes band dominance, height encodes
        //                       overall amplitude — bands don't occlude).
        //   'liquid'          → smooth Path2D bezier silhouette per band
        //                       (legacy; bands stack with alpha so the
        //                       top-most one tends to dominate).
        //   'mono'            → silhouette of mono fallback peaks.
        //   'bass'            → silhouette of LOW band only.
        if (waveformStyle === 'mono' && hasMono) {
            drawSmoothBandPath(ctx, fallbackPeaks, 'fallback', region, rStartPx, rEndPx, scrollX, zoom, sourceDuration, centerY, maxAmp, lodLevel, width, height);
        } else if (waveformStyle === 'bass' && hasBand && activePeaks.low?.length) {
            drawSmoothBandPath(ctx, activePeaks.low, 'low', region, rStartPx, rEndPx, scrollX, zoom, sourceDuration, centerY, maxAmp, lodLevel, width, height);
        } else if (waveformStyle === 'liquid' && hasBand && activePeaks) {
            for (const bk of ['low', 'mid', 'high']) {
                const p = activePeaks[bk];
                if (!p?.length) continue;
                drawSmoothBandPath(ctx, p, bk, region, rStartPx, rEndPx, scrollX, zoom, sourceDuration, centerY, maxAmp, lodLevel, width, height);
            }
        } else if (hasBand && activePeaks.low?.length && activePeaks.mid?.length && activePeaks.high?.length) {
            // Default '3band' (and any unknown style with band data available)
            // → Mixxx-style stacked colour zones (low/mid/high as discrete
            // vertical bands from center outward, asymmetric min/max envelope).
            drawMixxxFilteredWaveform(ctx, activePeaks, region, rStartPx, rEndPx, scrollX, zoom, sourceDuration, centerY, maxAmp);
        } else if (hasMono) {
            drawSmoothBandPath(ctx, fallbackPeaks, 'fallback', region, rStartPx, rEndPx, scrollX, zoom, sourceDuration, centerY, maxAmp, lodLevel, width, height);
        }
    }

    ctx.resetTransform();
    return oc.transferToImageBitmap();
}

// ═══════════════════════════════════════════════════════════════════════════════
// MIXXX-STYLE 3-BAND STACKED FILTERED WAVEFORM (SMOOTH POLYGON RENDERER)
// ═══════════════════════════════════════════════════════════════════════════════
//
// Inspired by Mixxx's WaveformRendererFilteredSignal. Three bands stacked
// outward from the centerline produce a layered envelope where the colour
// at any height tells you the spectral content there:
//
//   ┌─ HIGH (blue)  outermost — hi-hats, cymbals, air
//   ├─ MID  (green) middle    — vocals, instruments
//   ├─ LOW  (red)   innermost — kick, bass body
//   ── centerline ────────────────────────────────────────
//   ├─ LOW  (red)
//   ├─ MID  (green)
//   └─ HIGH (blue)
//
// Asymmetric: positive peaks (max) drive the top half, negative peaks
// (min) drive the bottom half. Real audio is rarely symmetric, so an
// asymmetric envelope preserves the natural stem/transient shape.
//
// SMOOTHING — three layers of defence against the "blocky comb" look:
//
//   1. Sampling stride of 1-2 px depending on peak density (avoids
//      single-pixel spikes when one peak covers many pixels)
//   2. Light 1-2-1 horizontal smoothing kernel on every band/direction
//      array (suppresses isolated bumps without blurring transients —
//      coefficients sum to 1, no DC shift)
//   3. Quadratic Bezier curves via Path2D between adjacent samples
//      using midpoint control points (the curve passes through every
//      midpoint, with each original sample acting as a control vertex)
//
// Each band is rendered as a filled Path2D POLYGON, not column-by-column
// rectangles — adjacent columns are connected by curves so the silhouette
// flows continuously, like a real waveform display.
// ═══════════════════════════════════════════════════════════════════════════════

const MIXXX_COLORS = {
    // RGB values — saturated CDJ-style. Picked for contrast against the
    // #090c17 background. Alpha left to ctx (1.0).
    low:  [255, 70, 90],     // red — bass / kick / sub
    mid:  [70, 220, 130],    // green — vocals / instruments
    high: [70, 150, 255],    // blue — hi-hats / cymbals / air
};

function drawMixxxFilteredWaveform(ctx, bandPeaks, region, rStartPx, rEndPx, scrollX, zoom, sourceDuration, centerY, maxAmp) {
    const low  = bandPeaks.low;
    const mid  = bandPeaks.mid;
    const high = bandPeaks.high;
    if (!low?.length || !mid?.length || !high?.length) return;
    if (sourceDuration <= 0) return;

    const peakLen = Math.min(low.length, mid.length, high.length);
    const startPx = Math.max(0, Math.floor(rStartPx));
    const endPx   = Math.ceil(rEndPx);
    if (endPx <= startPx) return;

    const pxToPeakRatio = peakLen / (sourceDuration * zoom);

    // Per-band gain — calibrated so that a loud track fills ~80% of the
    // silhouette area without clipping. BiquadFilter resonance allows
    // individual band peaks slightly above 1.0, but the SUM of three bands
    // is rarely > 2.0 in practice. Scale so 2.0 ≈ maxAmp.
    const BAND_GAIN = 0.5;
    const GAMMA = 1.1;

    // ── PASS 1: gather band amplitudes per pixel column ──
    // Sampling stride: 1 px gives the most detail; we widen to 2 px at
    // narrow per-band ratios so the smoothed curve doesn't get drowned by
    // single-pixel noise. Both top (positive peak) and bottom (negative
    // peak) are sampled — asymmetric envelope.
    const STRIDE = pxToPeakRatio > 0.5 ? 1 : 2;
    const sampleCount = Math.ceil((endPx - startPx) / STRIDE) + 1;
    // Flat typed arrays — one entry per sample column.
    const sX  = new Float32Array(sampleCount);
    const slT = new Float32Array(sampleCount);  // low top  height (px)
    const smT = new Float32Array(sampleCount);  // mid top  height (px)
    const shT = new Float32Array(sampleCount);  // high top height (px)
    const slB = new Float32Array(sampleCount);  // low bot  height (px)
    const smB = new Float32Array(sampleCount);  // mid bot  height (px)
    const shB = new Float32Array(sampleCount);  // high bot height (px)
    let n = 0;

    for (let px = startPx; px <= endPx; px += STRIDE) {
        const time    = (px + scrollX) / zoom;
        const srcTime = region.sourceStart + (time - region.timelineStart);
        if (srcTime < 0 || srcTime > sourceDuration) {
            sX[n] = px;
            // explicit zero — Float32Array is already zero-initialised
            n++;
            continue;
        }

        const fIdx0 = (srcTime / sourceDuration) * peakLen;
        const fIdx1 = fIdx0 + Math.max(1, pxToPeakRatio);
        const idx0  = Math.floor(fIdx0);
        const idx1  = Math.min(peakLen - 1, Math.ceil(fIdx1));

        let lowPos = 0, midPos = 0, highPos = 0;
        let lowNeg = 0, midNeg = 0, highNeg = 0;
        for (let i = idx0; i <= idx1; i++) {
            const lp = low[i]; const mp = mid[i]; const hp = high[i];
            if (!lp || !mp || !hp) continue;
            if (lp.max > lowPos)   lowPos  = lp.max;
            if (mp.max > midPos)   midPos  = mp.max;
            if (hp.max > highPos)  highPos = hp.max;
            const ln = -lp.min, mn = -mp.min, hn = -hp.min;
            if (ln > lowNeg)  lowNeg  = ln;
            if (mn > midNeg)  midNeg  = mn;
            if (hn > highNeg) highNeg = hn;
        }

        const scale = maxAmp * BAND_GAIN;
        sX[n]  = px;
        slT[n] = Math.pow(Math.min(1, lowPos),  GAMMA) * scale;
        smT[n] = Math.pow(Math.min(1, midPos),  GAMMA) * scale;
        shT[n] = Math.pow(Math.min(1, highPos), GAMMA) * scale;
        slB[n] = Math.pow(Math.min(1, lowNeg),  GAMMA) * scale;
        smB[n] = Math.pow(Math.min(1, midNeg),  GAMMA) * scale;
        shB[n] = Math.pow(Math.min(1, highNeg), GAMMA) * scale;
        n++;
    }
    if (n < 2) return;

    // ── PASS 2: light 1-2-1 horizontal smoothing on each band/direction ──
    // Removes single-pixel spikes so the polygon's bezier curve flows
    // continuously instead of jagging at every sample. We re-use the
    // sample arrays in-place after copying via slice.
    const smooth = (arr) => {
        if (n < 3) return arr;
        const out = new Float32Array(n);
        out[0] = arr[0];
        out[n - 1] = arr[n - 1];
        for (let i = 1; i < n - 1; i++) {
            out[i] = arr[i - 1] * 0.25 + arr[i] * 0.5 + arr[i + 1] * 0.25;
        }
        return out;
    };
    const sLT = smooth(slT), sMT = smooth(smT), sHT = smooth(shT);
    const sLB = smooth(slB), sMB = smooth(smB), sHB = smooth(shB);

    // ── PASS 3: build & fill 6 smooth polygons (3 top, 3 bottom) ──
    // Each band's polygon spans the row between its inner edge (closer to
    // centerline) and its outer edge. Inner edges are CUMULATIVE — mid's
    // inner edge sits on top of low's outer edge, etc. This gives the
    // stacked-band look (red core, green mantle, blue tip).
    const colLow  = `rgb(${MIXXX_COLORS.low[0]},${MIXXX_COLORS.low[1]},${MIXXX_COLORS.low[2]})`;
    const colMid  = `rgb(${MIXXX_COLORS.mid[0]},${MIXXX_COLORS.mid[1]},${MIXXX_COLORS.mid[2]})`;
    const colHigh = `rgb(${MIXXX_COLORS.high[0]},${MIXXX_COLORS.high[1]},${MIXXX_COLORS.high[2]})`;

    // ── TOP HALF ──
    // low: inner = centerY, outer = centerY - lT
    fillSmoothBand(ctx, sX, n, (i) => centerY,                          (i) => centerY - sLT[i],                        colLow);
    // mid: inner = centerY - lT, outer = centerY - lT - mT
    fillSmoothBand(ctx, sX, n, (i) => centerY - sLT[i],                 (i) => centerY - sLT[i] - sMT[i],               colMid);
    // high: inner = centerY - lT - mT, outer = centerY - lT - mT - hT
    fillSmoothBand(ctx, sX, n, (i) => centerY - sLT[i] - sMT[i],        (i) => centerY - sLT[i] - sMT[i] - sHT[i],      colHigh);

    // ── BOTTOM HALF (mirrored) ──
    fillSmoothBand(ctx, sX, n, (i) => centerY,                          (i) => centerY + sLB[i],                        colLow);
    fillSmoothBand(ctx, sX, n, (i) => centerY + sLB[i],                 (i) => centerY + sLB[i] + sMB[i],               colMid);
    fillSmoothBand(ctx, sX, n, (i) => centerY + sLB[i] + sMB[i],        (i) => centerY + sLB[i] + sMB[i] + sHB[i],      colHigh);
}

/**
 * Fill a horizontal band whose vertical span is defined by two y-curves
 * (inner and outer). Uses quadraticCurveTo with midpoint control points
 * to smoothly connect adjacent sample columns — same trick Mixxx and
 * Rekordbox use to avoid the "comb" look that 1-px rectangles produce.
 *
 * @param {CanvasRenderingContext2D} ctx
 * @param {Float32Array} xs           pixel positions, length n
 * @param {number} n                  number of valid samples
 * @param {(i:number)=>number} yInner inner-edge y (closer to centerline)
 * @param {(i:number)=>number} yOuter outer-edge y (farther from centerline)
 * @param {string} fillStyle
 */
function fillSmoothBand(ctx, xs, n, yInner, yOuter, fillStyle) {
    // Skip the polygon entirely if the band is fully collapsed (would
    // otherwise emit zero-area paths that still cost fill time).
    let maxThickness = 0;
    for (let i = 0; i < n; i++) {
        const t = Math.abs(yOuter(i) - yInner(i));
        if (t > maxThickness) maxThickness = t;
        if (maxThickness > 0.5) break;
    }
    if (maxThickness < 0.5) return;

    const path = new Path2D();

    // Outer edge — left to right, smoothed.
    // Move to first outer point.
    path.moveTo(xs[0], yOuter(0));
    // Quadratic bezier through each subsequent point using the previous
    // point as the control and the midpoint as the new endpoint. This is
    // the standard "midpoint Catmull-Rom-ish" smoothing technique.
    for (let i = 1; i < n; i++) {
        const mx = (xs[i - 1] + xs[i]) * 0.5;
        const my = (yOuter(i - 1) + yOuter(i)) * 0.5;
        path.quadraticCurveTo(xs[i - 1], yOuter(i - 1), mx, my);
    }
    // Anchor to the last outer point so the right edge isn't curved off
    path.lineTo(xs[n - 1], yOuter(n - 1));

    // Drop down/up to the inner edge at the right end
    path.lineTo(xs[n - 1], yInner(n - 1));

    // Inner edge — right to left, smoothed in the same way
    for (let i = n - 2; i >= 0; i--) {
        const mx = (xs[i + 1] + xs[i]) * 0.5;
        const my = (yInner(i + 1) + yInner(i)) * 0.5;
        path.quadraticCurveTo(xs[i + 1], yInner(i + 1), mx, my);
    }
    path.lineTo(xs[0], yInner(0));

    path.closePath();
    ctx.fillStyle = fillStyle;
    ctx.fill(path);
}

// ─── SMOOTH PATH2D BAND SILHOUETTE ──────────────────────────────────────────────

function drawSmoothBandPath(ctx, peaks, bandKey, region, rStartPx, rEndPx, scrollX, zoom, sourceDuration, centerY, maxAmp, lodLevel, width, height) {
    const widthPx = Math.max(1, Math.ceil(rEndPx) - Math.floor(rStartPx));
    // Sample density. Cap step so even narrow regions get >= 3 samples —
    // otherwise small pasted clips (e.g., 8 px wide at LOD 4 with step=8)
    // render with < 2 points and the early-return below skips them
    // entirely. Audio plays but waveform is invisible — visible as a
    // "missing region with audio still playing" gap.
    const baseStep = Math.max(2, lodLevel * 2);
    const step = Math.min(baseStep, Math.max(1, Math.floor(widthPx / 3)));
    const pts  = [];

    const samplePixel = (px) => {
        const time     = (px + scrollX) / zoom;
        const srcTime  = region.sourceStart + (time - region.timelineStart);
        // BUG FIX 2026-05-11: was `srcTime / totalDuration` — `totalDuration`
        // is the edit-timeline length, which can differ from the source
        // audio length in .rbep projects whose regions rearrange or repeat
        // sections. Peaks are indexed against the source audio, so we must
        // divide by sourceDuration. Symptom of the old bug: waveform
        // sample-positions drifted by the ratio (totalDur / sourceDur);
        // visible as "waveform doesn't match audio" during playback.
        const rawIdx   = (srcTime / sourceDuration) * peaks.length;
        const idx      = Math.floor(rawIdx);
        const frac     = rawIdx - idx;

        if (idx < 0 || idx >= peaks.length) return null;
        const p0 = peaks[idx];
        const p1 = idx + 1 < peaks.length ? peaks[idx + 1] : p0;
        if (!p0 || isNaN(p0.max) || isNaN(p0.min)) return null;

        const iMax = p0.max + (p1.max - p0.max) * frac;
        const iMin = p0.min + (p1.min - p0.min) * frac;
        return { px, yTop: centerY - iMax * maxAmp, yBot: centerY - iMin * maxAmp };
    };

    // Sample peak data across visible region pixels
    const startPx = Math.floor(rStartPx);
    const endPx = Math.ceil(rEndPx);
    for (let px = startPx; px <= endPx; px += step) {
        const pt = samplePixel(px);
        if (pt) pts.push(pt);
    }
    // Always sample exactly at the right edge so very narrow regions
    // get the second point they need to render. Without this, rounding
    // can leave the rightmost pixel un-sampled and a thin pasted clip
    // still falls below the < 2 threshold.
    if (pts.length === 0 || pts[pts.length - 1].px < endPx) {
        const tail = samplePixel(endPx);
        if (tail) pts.push(tail);
    }

    if (pts.length < 2) {
        // Last-resort fallback: draw a thin centerline strip so the user
        // sees SOMETHING where the region is, instead of silent emptiness.
        // Happens when a region is so narrow that only one sample point
        // could be extracted (e.g., 1-pixel wide region after drag).
        if (pts.length === 1) {
            const c = COLORS[bandKey] || COLORS.fallback;
            ctx.fillStyle = c.top;
            ctx.fillRect(pts[0].px, pts[0].yTop, 1, pts[0].yBot - pts[0].yTop);
        }
        return;
    }

    // Build gradient for this band
    const grad = ctx.createLinearGradient(0, centerY - maxAmp, 0, centerY + maxAmp);
    const c = COLORS[bandKey] || COLORS.fallback;
    grad.addColorStop(0,    c.top);
    grad.addColorStop(0.45, c.top.includes('0.92') ? c.top.replace('0.92', '0.60') : c.top.replace('0.88', '0.55'));
    grad.addColorStop(1,    c.bot);

    // Draw filled silhouette using Path2D with smooth quadratic bezier
    const path = new Path2D();

    // Start at left edge, centerline
    path.moveTo(pts[0].px, centerY);

    // Upper contour (forward)
    path.lineTo(pts[0].px, pts[0].yTop);
    for (let i = 1; i < pts.length; i++) {
        const prev = pts[i - 1];
        const curr = pts[i];
        const mx   = (prev.px + curr.px) / 2;
        path.quadraticCurveTo(prev.px, prev.yTop, mx, (prev.yTop + curr.yTop) / 2);
    }
    // Cap right edge
    path.lineTo(pts[pts.length - 1].px, pts[pts.length - 1].yTop);
    path.lineTo(pts[pts.length - 1].px, pts[pts.length - 1].yBot);

    // Lower contour (reverse)
    for (let i = pts.length - 2; i >= 0; i--) {
        const curr = pts[i + 1];
        const prev = pts[i];
        const mx   = (prev.px + curr.px) / 2;
        path.quadraticCurveTo(curr.px, curr.yBot, mx, (curr.yBot + prev.yBot) / 2);
    }

    path.lineTo(pts[0].px, pts[0].yBot);
    path.closePath();

    ctx.fillStyle = grad;
    ctx.fill(path);

    // Thin bright top highlight stroke for crispness
    const highlightPath = new Path2D();
    highlightPath.moveTo(pts[0].px, pts[0].yTop);
    for (let i = 1; i < pts.length; i++) {
        const prev = pts[i - 1];
        const curr = pts[i];
        const mx = (prev.px + curr.px) / 2;
        highlightPath.quadraticCurveTo(prev.px, prev.yTop, mx, (prev.yTop + curr.yTop) / 2);
    }
    ctx.strokeStyle = c.top;
    ctx.lineWidth = 0.8;
    ctx.stroke(highlightPath);
}

// ═══════════════════════════════════════════════════════════════════════════════
// MAIN FRAME DRAW — composites bitmap + live layers
// ═══════════════════════════════════════════════════════════════════════════════

function drawFrame(ctx, d, bitmap) {
    const { width, height, dpr } = d;
    if (width <= 0 || height <= 0) return;

    ctx.save();
    ctx.scale(dpr, dpr);

    // ── BG ──
    ctx.fillStyle = COLORS.background;
    ctx.fillRect(0, 0, width, height);

    const startTime = d.scrollX / d.zoom;
    const endTime   = (d.scrollX + d.width) / d.zoom;

    // ── LAYER 0: Waveform bitmap ──
    // Translate the bitmap by the delta between the scrollX it was built
    // for (d.lastBuiltScrollX) and the LIVE d.scrollX. Without this offset
    // the bitmap stays anchored to (0, 0) showing the OLD scroll position
    // even as d.scrollX smoothly advances — the playhead, drawn against
    // the live scrollX, then visibly leads the waveform by 0..24 px (the
    // rebuild threshold). The drift is non-constant (resets every rebuild)
    // and produces the user-reported "visuelles geht voraus, nicht
    // konstant" + "ruckelt" symptoms.
    if (bitmap) {
        const offset = (d.lastBuiltScrollX || 0) - d.scrollX;
        ctx.drawImage(bitmap, offset, 0, width, height);
    }

    // ── LAYER 1: Grid + interactive ──
    drawGrid(ctx, d, startTime, endTime);
    drawPhraseMarkers(ctx, d, startTime, endTime);
    drawLoops(ctx, d, startTime, endTime);
    drawRegionBoundaries(ctx, d, startTime, endTime);
    drawSelectionRange(ctx, d, startTime, endTime);
    drawCueMarkers(ctx, d, startTime, endTime);
    drawRuler(ctx, d, startTime, endTime);

    // ── LAYER 2: Playhead + Phase Meter ──
    drawPlayhead(ctx, d);
    drawPhaseMeter(ctx, d);

    ctx.restore();
}

// ─── GRID ────────────────────────────────────────────────────────────────────────

function drawGrid(ctx, d, startTime, endTime) {
    const { width, height, zoom, scrollX, bpm, firstBeatSec } = d;
    if (!bpm || bpm <= 0) return;

    const beatDur = 60 / bpm;
    const barDur  = beatDur * 4;
    const ppb     = beatDur * zoom;

    let gridUnit = beatDur;
    if (ppb < 8)  { gridUnit = barDur; }
    else if (ppb > 60) { gridUnit = beatDur / 4; }

    const first = Math.floor((startTime - firstBeatSec) / gridUnit) * gridUnit + firstBeatSec;
    const waveBot = height - PHASE_METER_HEIGHT;
    ctx.lineWidth = 1;

    for (let t = first; t <= endTime + gridUnit; t += gridUnit) {
        if (t < 0) continue;
        const x = Math.round(t * zoom - scrollX) + 0.5;
        if (x < -1 || x > width + 1) continue;

        const beatNum = Math.round((t - firstBeatSec) / beatDur);
        ctx.strokeStyle = beatNum % 4 === 0 ? COLORS.gridBar :
            ppb > 60 ? (Math.round((t - firstBeatSec) / (beatDur / 4)) % 4 === 0 ? COLORS.gridBeat : COLORS.gridSub)
                     : COLORS.gridBeat;

        ctx.beginPath();
        ctx.moveTo(x, RULER_HEIGHT);
        ctx.lineTo(x, waveBot);
        ctx.stroke();
    }
}

// ─── PHRASE MARKERS ─────────────────────────────────────────────────────────────

function drawPhraseMarkers(ctx, d, startTime, endTime) {
    const { width, height, zoom, scrollX, bpm, firstBeatSec } = d;
    if (!bpm || bpm <= 0) return;

    const beatDur    = 60 / bpm;
    const phraseDur  = beatDur * 64;
    const firstP     = Math.floor((startTime - firstBeatSec) / phraseDur) * phraseDur + firstBeatSec;
    const waveBot    = height - PHASE_METER_HEIGHT;

    ctx.lineWidth = 1.5;
    ctx.setLineDash([4, 4]);

    for (let t = firstP; t <= endTime + phraseDur; t += phraseDur) {
        if (t < 0) continue;
        const x = Math.round(t * zoom - scrollX) + 0.5;
        if (x < -1 || x > width + 1) continue;

        ctx.strokeStyle = COLORS.phraseMarker;
        ctx.beginPath();
        ctx.moveTo(x, RULER_HEIGHT);
        ctx.lineTo(x, waveBot);
        ctx.stroke();

        const num = Math.round((t - firstBeatSec) / phraseDur) + 1;
        ctx.save();
        ctx.fillStyle = 'rgba(0,0,0,0.6)';
        ctx.fillRect(x - 18, RULER_HEIGHT + 2, 36, 11);
        ctx.restore();
        ctx.fillStyle = COLORS.phraseLabel;
        ctx.font = 'bold 8px Inter, system-ui, sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(`16B·${num}`, x, RULER_HEIGHT + 10);

        // Small triangle
        ctx.fillStyle = COLORS.phraseMarker;
        ctx.beginPath();
        ctx.moveTo(x - 4, RULER_HEIGHT);
        ctx.lineTo(x + 4, RULER_HEIGHT);
        ctx.lineTo(x, RULER_HEIGHT + 5);
        ctx.fill();
    }
    ctx.setLineDash([]);
}

// ─── REGION BOUNDARIES ──────────────────────────────────────────────────────────

function drawRegionBoundaries(ctx, d, startTime, endTime) {
    const { width, height, zoom, scrollX, regions, selectedIds } = d;
    const waveBot = height - PHASE_METER_HEIGHT;

    for (const region of regions) {
        if (!region.duration || region.duration <= 0) continue;
        const regionEnd = region.timelineStart + region.duration;
        if (regionEnd < startTime || region.timelineStart > endTime) continue;

        const x1 = region.timelineStart * zoom - scrollX;
        const x2 = regionEnd            * zoom - scrollX;
        const sel = selectedIds.has(region.id);

        if (sel) {
            ctx.fillStyle = COLORS.selectionFill;
            ctx.fillRect(x1, RULER_HEIGHT, x2 - x1, waveBot - RULER_HEIGHT);
        }
        ctx.strokeStyle = sel ? COLORS.regionSelectedBorder : COLORS.regionBorder;
        ctx.lineWidth = sel ? 2 : 1;
        ctx.beginPath(); ctx.moveTo(Math.round(x1) + 0.5, RULER_HEIGHT); ctx.lineTo(Math.round(x1) + 0.5, waveBot); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(Math.round(x2) + 0.5, RULER_HEIGHT); ctx.lineTo(Math.round(x2) + 0.5, waveBot); ctx.stroke();
    }
}

// ─── SELECTION RANGE ────────────────────────────────────────────────────────────

function drawSelectionRange(ctx, d, startTime, endTime) {
    const { width, height, zoom, scrollX, selectionRange } = d;
    if (!selectionRange) return;
    const { start, end } = selectionRange;
    if (end <= start || end < startTime || start > endTime) return;

    const x1 = Math.round(start * zoom - scrollX);
    const x2 = Math.round(end   * zoom - scrollX);
    const waveBot = height - PHASE_METER_HEIGHT;

    if (x2 < 0 || x1 > width) return;

    ctx.fillStyle = COLORS.selectionFill;
    ctx.fillRect(x1, RULER_HEIGHT, x2 - x1, waveBot - RULER_HEIGHT);
    ctx.strokeStyle = COLORS.selectionBorder;
    ctx.lineWidth = 1;
    ctx.strokeRect(x1 + 0.5, RULER_HEIGHT + 0.5, x2 - x1, waveBot - RULER_HEIGHT - 1);
}

// ─── CUE MARKERS (EC5 collision) ────────────────────────────────────────────────

function drawCueMarkers(ctx, d, startTime, endTime) {
    const { width, height, zoom, scrollX, hotCues, memoryCues, ghostCueX } = d;
    const waveBot = height - PHASE_METER_HEIGHT;

    // Sort by X, stagger overlapping labels (EC5)
    const items = [];
    for (let i = 0; i < hotCues.length; i++) {
        const cue = hotCues[i];
        if (!cue) continue;
        const x = Math.round(cue.time * zoom - scrollX) + 0.5;
        if (x < -10 || x > width + 10) continue;
        items.push({ i, x, cue });
    }
    items.sort((a, b) => a.x - b.x);

    const rows = [];
    for (const item of items) {
        let row = 0;
        while (rows[row] !== undefined && item.x - rows[row] < 20) row++;
        rows[row] = item.x;
        item.row = row;
    }

    for (const { i, x, cue, row } of items) {
        const color  = `rgb(${cue.red},${cue.green},${cue.blue})`;
        const labelY = row * 14;

        // Full-height vertical line
        ctx.strokeStyle = color + 'cc';
        ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.moveTo(x, RULER_HEIGHT); ctx.lineTo(x, waveBot); ctx.stroke();

        // Flag shape
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.moveTo(x, labelY);
        ctx.lineTo(x + 13, labelY);
        ctx.lineTo(x + 13, labelY + 10);
        ctx.lineTo(x + 3, labelY + 15);
        ctx.lineTo(x, labelY + 15);
        ctx.closePath();
        ctx.fill();

        // Label letter
        ctx.fillStyle = '#000';
        ctx.font = 'bold 7px Inter, system-ui, sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText(String.fromCharCode(65 + i), x + 2, labelY + 10);

        // Cue name below flag (if non-default)
        if (cue.name && cue.name !== String.fromCharCode(65 + i)) {
            ctx.fillStyle = color;
            ctx.font = '7px Inter, system-ui, sans-serif';
            ctx.fillText(cue.name.slice(0, 8), x + 16, labelY + 9);
        }
    }

    // Memory cues
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
        ctx.beginPath(); ctx.moveTo(x, RULER_HEIGHT + 8); ctx.lineTo(x, waveBot); ctx.stroke();
        ctx.setLineDash([]);
    }

    // Ghost cue during drag (EC3)
    if (ghostCueX !== null) {
        ctx.strokeStyle = COLORS.ghostCue;
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 4]);
        ctx.beginPath(); ctx.moveTo(ghostCueX + 0.5, RULER_HEIGHT); ctx.lineTo(ghostCueX + 0.5, waveBot); ctx.stroke();
        ctx.setLineDash([]);
    }
}

// ─── LOOPS ───────────────────────────────────────────────────────────────────────

function drawLoops(ctx, d, startTime, endTime) {
    const { width, height, zoom, scrollX, loops, activeLoopIndex } = d;
    const waveBot = height - PHASE_METER_HEIGHT;

    for (let i = 0; i < loops.length; i++) {
        const loop = loops[i];
        if (loop.startTime == null) continue;
        const x1 = loop.startTime * zoom - scrollX;
        const x2 = (loop.endTime ?? loop.startTime + 4) * zoom - scrollX;
        if (x2 < 0 || x1 > width) continue;

        const active = i === activeLoopIndex;
        const color  = `rgb(${loop.red ?? 251},${loop.green ?? 146},${loop.blue ?? 60})`;

        ctx.fillStyle = active ? `rgba(${loop.red ?? 251},${loop.green ?? 146},${loop.blue ?? 60},0.14)` : COLORS.loopFill;
        ctx.fillRect(x1, RULER_HEIGHT, x2 - x1, waveBot - RULER_HEIGHT);

        ctx.strokeStyle = active ? color : COLORS.loopBorder;
        ctx.lineWidth   = active ? 2 : 1;
        ctx.beginPath(); ctx.moveTo(Math.round(x1) + 0.5, RULER_HEIGHT); ctx.lineTo(Math.round(x1) + 0.5, waveBot); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(Math.round(x2) + 0.5, RULER_HEIGHT); ctx.lineTo(Math.round(x2) + 0.5, waveBot); ctx.stroke();

        if (x2 - x1 > 20) {
            ctx.fillStyle = color;
            ctx.font = '7px Inter, system-ui, sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText(loop.name || `L${i + 1}`, (x1 + x2) / 2, RULER_HEIGHT + 9);
        }
        ctx.fillStyle = color;
        ctx.fillRect(Math.round(x1), RULER_HEIGHT, 3, 14);
        ctx.fillRect(Math.round(x2) - 3, RULER_HEIGHT, 3, 14);
    }
}

// ─── PLAYHEAD ────────────────────────────────────────────────────────────────────

function drawPlayhead(ctx, d) {
    const { width, height, zoom, scrollX, playhead } = d;
    const x = Math.round(playhead * zoom - scrollX) + 0.5;
    if (x < -2 || x > width + 2) return;

    const waveBot = height - PHASE_METER_HEIGHT;

    // Glow layers
    ctx.strokeStyle = COLORS.playheadGlow2; ctx.lineWidth = 9;
    ctx.beginPath(); ctx.moveTo(x, RULER_HEIGHT); ctx.lineTo(x, waveBot); ctx.stroke();
    ctx.strokeStyle = COLORS.playheadGlow;   ctx.lineWidth = 3;
    ctx.beginPath(); ctx.moveTo(x, RULER_HEIGHT); ctx.lineTo(x, waveBot); ctx.stroke();

    // Main line (full height, above ruler)
    ctx.strokeStyle = COLORS.playhead; ctx.lineWidth = 1.2;
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, waveBot); ctx.stroke();

    // Triangle at top
    ctx.fillStyle = COLORS.playhead;
    ctx.beginPath();
    ctx.moveTo(x - 6, 0); ctx.lineTo(x + 6, 0); ctx.lineTo(x, 9);
    ctx.closePath(); ctx.fill();
}

// ─── PHASE METER ─────────────────────────────────────────────────────────────────
// 8px strip at canvas bottom showing beat phase — pulses every beat

function drawPhaseMeter(ctx, d) {
    const { width, height, zoom, bpm, playhead } = d;
    if (!bpm || bpm <= 0) return;

    const y = height - PHASE_METER_HEIGHT;

    // Background
    ctx.fillStyle = COLORS.phaseMeterBg;
    ctx.fillRect(0, y, width, PHASE_METER_HEIGHT);

    const beatDur = 60 / bpm;
    const phase   = (playhead % beatDur) / beatDur; // 0..1

    // Fill color: cyan → orange as approaching next beat
    const r = Math.round(phase * 255);
    const g = Math.round((1 - phase) * 229);
    const fillColor = phase < 0.75 ? COLORS.phaseMeterFill : COLORS.phaseMeterLate;

    ctx.fillStyle = fillColor;
    ctx.fillRect(0, y + 1, width * phase, PHASE_METER_HEIGHT - 2);

    // Bright flash at beat boundary (phase near 0)
    if (phase < 0.05) {
        ctx.fillStyle = 'rgba(255,255,255,0.6)';
        ctx.fillRect(0, y + 1, width * 0.15, PHASE_METER_HEIGHT - 2);
    }

    // Beat tick marks
    const barDur = beatDur * 4;
    const firstBeat = Math.floor(playhead / beatDur) * beatDur - beatDur * 2;
    for (let bt = firstBeat; bt < playhead + beatDur * 8; bt += beatDur) {
        const phaseOfBt = ((bt % barDur) / barDur);
        const bx = phaseOfBt * width;
        ctx.fillStyle = bt % barDur < 0.001 ? 'rgba(255,60,60,0.8)' : 'rgba(255,255,255,0.2)';
        ctx.fillRect(bx, y, 1, PHASE_METER_HEIGHT);
    }
}

// ─── RULER ─────────────────────────────────────────────────────────────────────────

function drawRuler(ctx, d, startTime, endTime) {
    const { width, zoom, scrollX, bpm, firstBeatSec } = d;

    ctx.fillStyle = COLORS.rulerBg;
    ctx.fillRect(0, 0, width, RULER_HEIGHT);

    ctx.strokeStyle = COLORS.rulerLine; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(0, RULER_HEIGHT - 0.5); ctx.lineTo(width, RULER_HEIGHT - 0.5); ctx.stroke();

    if (!bpm || bpm <= 0) return;

    const beatDur = 60 / bpm;
    const barDur  = beatDur * 4;
    const ppb     = barDur * zoom;

    let labelInt = barDur;
    if (ppb < 40)  labelInt = barDur * 4;
    if (ppb < 15)  labelInt = barDur * 16;

    const first = Math.floor((startTime - firstBeatSec) / labelInt) * labelInt + firstBeatSec;

    ctx.font = '8px Inter, system-ui, sans-serif';
    ctx.textAlign = 'center';

    for (let t = first; t <= endTime + labelInt; t += labelInt) {
        if (t < 0) continue;
        const x = Math.round(t * zoom - scrollX);
        if (x < -40 || x > width + 40) continue;

        ctx.strokeStyle = COLORS.rulerTick; ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(x + 0.5, RULER_HEIGHT - 5); ctx.lineTo(x + 0.5, RULER_HEIGHT - 1); ctx.stroke();

        const mins = Math.floor(t / 60);
        const secs = Math.floor(t % 60);
        ctx.fillStyle = COLORS.rulerText;
        ctx.fillText(`${mins}:${secs.toString().padStart(2, '0')}`, x, RULER_HEIGHT - 7);
    }
}

DawTimeline.displayName = 'DawTimeline';

export default DawTimeline;
