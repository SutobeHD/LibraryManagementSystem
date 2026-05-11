/**
 * useTimelineEvents — Event-handler layer for DawTimeline
 *
 * Owns:
 *  - Hit-testing for cue flags (hot + memory)
 *  - Mouse down/move/up handlers (click-to-place-cue, drag-to-reposition,
 *    region selection, selection-range drag)
 *  - Wheel handler (scroll + ctrl/cmd-scroll zoom anchored at the cursor)
 *  - Drag-state refs (isDragging, dragStartTime, draggingCue)
 *
 * Returns a `handlers` object the wrapper attaches to <canvas>.
 */

import { useCallback, useRef } from 'react';
import { snapToGrid } from '../../../audio/DawState';
import { RULER_HEIGHT } from './useTimelineRender';

/**
 * @param {Object}   args
 * @param {Function} args.dispatch         DAW dispatch
 * @param {Object}   args.canvasRef        ref to <canvas>
 * @param {Object}   args.ds               mutable draw-state ref (ds.current)
 * @param {Function} [args.onContextMenu]  right-click handler (time, event)
 * @returns {{onMouseDown:Function, onMouseMove:Function, onMouseUp:Function, onWheel:Function}}
 */
export function useTimelineEvents({ dispatch, canvasRef, ds, onContextMenu }) {
    const isDragging    = useRef(false);
    const dragStartTime = useRef(0);
    const draggingCue   = useRef(null);

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
    }, [canvasRef, ds, dispatch, onContextMenu, hitTestCue]);

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
    }, [canvasRef, ds, dispatch]);

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
    }, [canvasRef, ds, dispatch]);

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
    }, [canvasRef, ds, dispatch]);

    return {
        onMouseDown: handleMouseDown,
        onMouseMove: handleMouseMove,
        onMouseUp:   handleMouseUp,
        onWheel:     handleWheel,
    };
}
