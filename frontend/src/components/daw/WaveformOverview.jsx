/**
 * WaveformOverview — Full-track mini-map with draggable viewport window
 *
 * Renders a downsampled mono waveform of the entire track.
 * Shows the currently visible portion as a semi-transparent viewport window.
 * Clicking/dragging pans the main timeline by dispatching SET_SCROLL_X.
 *
 * Performance: redraws only on data change (no RAF loop needed).
 */

import React, { useRef, useEffect, useCallback } from 'react';

const OVERVIEW_HEIGHT = 44;

const COLORS = {
    bg: '#080b14',
    waveform: 'rgba(56, 189, 248, 0.5)',
    waveformPeak: 'rgba(99, 210, 255, 0.9)',
    viewport: 'rgba(56, 189, 248, 0.12)',
    viewportBorder: 'rgba(56, 189, 248, 0.7)',
    playhead: 'rgba(255, 255, 255, 0.9)',
};

const WaveformOverview = React.memo(({ state, dispatch }) => {
    const canvasRef = useRef(null);
    const containerRef = useRef(null);
    const isDragging = useRef(false);
    const dragStartOffsetX = useRef(0); // mouse X relative to viewport window start

    const {
        fallbackPeaks,
        bandPeaks,
        totalDuration,
        zoom,
        scrollX,
        playhead,
    } = state;

    // ── DRAW ──────────────────────────────────────────────────────────────────
    const draw = useCallback(() => {
        const canvas = canvasRef.current;
        const container = containerRef.current;
        if (!canvas || !container) return;

        const dpr = window.devicePixelRatio || 1;
        const w = container.clientWidth;
        const h = OVERVIEW_HEIGHT;

        // Resize canvas if needed
        if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
            canvas.width = Math.round(w * dpr);
            canvas.height = Math.round(h * dpr);
            canvas.style.width = `${w}px`;
            canvas.style.height = `${h}px`;
        }

        const ctx = canvas.getContext('2d');
        ctx.save();
        ctx.scale(dpr, dpr);

        // Background
        ctx.fillStyle = COLORS.bg;
        ctx.fillRect(0, 0, w, h);

        // Waveform — use band low peaks for color, fallback for mono
        const peaks = bandPeaks?.low || fallbackPeaks;
        if (peaks && peaks.length > 0 && totalDuration > 0) {
            const centerY = h / 2;
            const maxAmp = h * 0.42;

            ctx.beginPath();
            ctx.strokeStyle = COLORS.waveform;
            ctx.lineWidth = 1;

            for (let px = 0; px < w; px++) {
                const t = (px / w) * totalDuration;
                const peakIdx = Math.floor((t / totalDuration) * peaks.length);
                if (peakIdx < 0 || peakIdx >= peaks.length) continue;
                const peak = peaks[peakIdx];
                if (!peak || isNaN(peak.max) || isNaN(peak.min)) continue;

                const y1 = centerY + peak.min * maxAmp;
                const y2 = centerY + peak.max * maxAmp;
                ctx.moveTo(px + 0.5, y1);
                ctx.lineTo(px + 0.5, y2);
            }
            ctx.stroke();
        }

        // Viewport window
        if (totalDuration > 0) {
            const secondsVisible = w / zoom; // seconds visible in main timeline
            const viewStartSec = scrollX / zoom;
            const viewEndSec = viewStartSec + secondsVisible;

            const vx1 = Math.max(0, (viewStartSec / totalDuration) * w);
            const vx2 = Math.min(w, (viewEndSec / totalDuration) * w);
            const vw = Math.max(4, vx2 - vx1);

            ctx.fillStyle = COLORS.viewport;
            ctx.fillRect(vx1, 0, vw, h);

            ctx.strokeStyle = COLORS.viewportBorder;
            ctx.lineWidth = 1.5;
            ctx.strokeRect(vx1 + 0.75, 0.75, vw - 1.5, h - 1.5);
        }

        // Playhead dot on overview
        if (playhead >= 0 && totalDuration > 0) {
            const phX = (playhead / totalDuration) * w;
            ctx.strokeStyle = COLORS.playhead;
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            ctx.moveTo(phX + 0.5, 0);
            ctx.lineTo(phX + 0.5, h);
            ctx.stroke();
        }

        // Bottom border line
        ctx.strokeStyle = 'rgba(255,255,255,0.05)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(0, h - 0.5);
        ctx.lineTo(w, h - 0.5);
        ctx.stroke();

        ctx.restore();
    }, [fallbackPeaks, bandPeaks, totalDuration, zoom, scrollX, playhead]);

    // Redraw on any relevant state change
    useEffect(() => {
        draw();
    }, [draw]);

    // ResizeObserver for width changes
    useEffect(() => {
        const container = containerRef.current;
        if (!container) return;
        const ro = new ResizeObserver(() => draw());
        ro.observe(container);
        return () => ro.disconnect();
    }, [draw]);

    // ── MOUSE INTERACTION ─────────────────────────────────────────────────────
    const timeFromX = useCallback((clientX) => {
        const canvas = canvasRef.current;
        if (!canvas || totalDuration <= 0) return 0;
        const rect = canvas.getBoundingClientRect();
        const relX = (clientX - rect.left) / rect.width;
        return relX * totalDuration;
    }, [totalDuration]);

    const scrollToTime = useCallback((centerTimeSec) => {
        const canvas = canvasRef.current;
        if (!canvas) return;
        const w = canvas.getBoundingClientRect().width;
        const secondsVisible = w / zoom;
        const newScrollX = centerTimeSec * zoom - (secondsVisible / 2) * zoom;
        dispatch({ type: 'SET_SCROLL_X', payload: Math.max(0, newScrollX) });
    }, [zoom, dispatch]);

    const handleMouseDown = useCallback((e) => {
        e.preventDefault();
        isDragging.current = true;

        // Calculate which "part" of the viewport window was clicked
        const clickTime = timeFromX(e.clientX);
        const viewCenterSec = (scrollX + (canvasRef.current?.getBoundingClientRect().width / 2) / zoom * zoom) / zoom;
        dragStartOffsetX.current = clickTime; // store click time

        scrollToTime(clickTime);
    }, [timeFromX, scrollToTime, scrollX, zoom]);

    const handleMouseMove = useCallback((e) => {
        if (!isDragging.current) return;
        e.preventDefault();
        const clickTime = timeFromX(e.clientX);
        scrollToTime(clickTime);
    }, [timeFromX, scrollToTime]);

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
        >
            <canvas
                ref={canvasRef}
                className="absolute inset-0"
                onMouseDown={handleMouseDown}
            />
            {/* Label */}
            <div className="absolute left-2 top-0.5 text-[8px] text-slate-600 font-bold uppercase tracking-widest pointer-events-none select-none">
                OVERVIEW
            </div>
        </div>
    );
});

WaveformOverview.displayName = 'WaveformOverview';

export default WaveformOverview;
