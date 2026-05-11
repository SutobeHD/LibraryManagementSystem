/**
 * useTimelineLayout — Layout / sizing layer for DawTimeline
 *
 * Owns:
 *  - ResizeObserver subscription on the container
 *  - DPR-aware canvas pixel sizing (backing store + CSS size)
 *  - Debounced resize handling (EC1) + DPR awareness (EC7)
 *  - Dynamic vs. fixed canvas-height mode
 *
 * After every layout pass we flip `needsWaveformRebuild` + `needsRedraw`
 * on the shared draw-state ref so the render loop picks the change up
 * on its next frame.
 */

import { useEffect, useRef } from 'react';

/**
 * @param {Object} args
 * @param {Object} args.containerRef       ref to the outer <div>
 * @param {Object} args.canvasRef          ref to the <canvas>
 * @param {Object} args.ds                 mutable draw-state ref (ds.current)
 * @param {number|null} args.canvasHeight  null = fill container, number = fixed pixel height
 * @param {number} args.minCanvasHeight    floor used in fill-container mode
 */
export function useTimelineLayout({ containerRef, canvasRef, ds, canvasHeight, minCanvasHeight }) {
    const resizeTimerRef = useRef(null);
    const roRef          = useRef(null);

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
    }, [canvasHeight, minCanvasHeight, canvasRef, containerRef, ds]);
}
