/**
 * WaveformMiniCanvas — Reusable lightweight canvas waveform renderer
 *
 * Shared across WaveformOverview (DAW mini-map), track row previews,
 * and any other context needing a compact waveform display.
 *
 * Features:
 * - 3-band CDJ-style colors (Low=Red, Mid=Green, High=Blue)
 * - Falls back to mono peaks if band data unavailable
 * - Optional playhead line
 * - Optional viewport highlight window (for overview mini-map use)
 * - ResizeObserver-aware: redraws on container resize
 * - DPR-aware: crisp on retina/high-DPI screens
 *
 * Usage:
 *   <WaveformMiniCanvas
 *     peaks={fallbackPeaks}           // mono [{min, max}]
 *     bandPeaks={bandPeaks}           // { low, mid, high } (optional, preferred)
 *     totalDuration={totalDuration}   // seconds
 *     playhead={playheadSec}          // optional
 *     viewportStart={startSec}        // optional: start of highlighted region
 *     viewportEnd={endSec}            // optional: end of highlighted region
 *     height={44}                     // px (default 44)
 *     style={{}}                      // optional container style overrides
 *     className=""                    // optional container class
 *   />
 */

import React, { useRef, useEffect, useCallback } from 'react';

// ─── COLORS (CDJ-style, matches DawTimeline) ────────────────────────────────────
const COLORS = {
    bg: '#080b14',
    // 3-Band — same palette as DawTimeline
    low:      { fill: 'rgba(255,32,64,0.85)',  stroke: 'rgba(255,60,90,0.6)' },
    mid:      { fill: 'rgba(0,210,110,0.80)',  stroke: 'rgba(0,230,120,0.55)' },
    high:     { fill: 'rgba(0,145,255,0.80)',  stroke: 'rgba(30,160,255,0.55)' },
    // Mono fallback
    mono:     { fill: 'rgba(56,189,248,0.55)', stroke: 'rgba(99,210,255,0.9)' },
    // Viewport overlay
    viewport: 'rgba(56,189,248,0.12)',
    viewportBorder: 'rgba(56,189,248,0.75)',
    // Playhead
    playhead: 'rgba(255,255,255,0.95)',
    // Bottom border
    border: 'rgba(255,255,255,0.05)',
};

const DEFAULT_HEIGHT = 44;

const WaveformMiniCanvas = React.memo(({
    peaks,
    bandPeaks,
    totalDuration = 0,
    playhead = null,
    viewportStart = null,
    viewportEnd = null,
    height = DEFAULT_HEIGHT,
    style,
    className = '',
    onClick,
}) => {
    const canvasRef = useRef(null);
    const containerRef = useRef(null);

    // ── DRAW ──────────────────────────────────────────────────────────────────────
    const draw = useCallback(() => {
        const canvas = canvasRef.current;
        const container = containerRef.current;
        if (!canvas || !container) return;

        const dpr = window.devicePixelRatio || 1;
        const w = container.clientWidth;
        const h = height;

        // Resize backing store if needed
        if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
            canvas.width = Math.round(w * dpr);
            canvas.height = Math.round(h * dpr);
            canvas.style.width = `${w}px`;
            canvas.style.height = `${h}px`;
        }

        const ctx = canvas.getContext('2d');
        ctx.save();
        ctx.scale(dpr, dpr);

        // ── Background ───────────────────────────────────────────────────────────
        ctx.fillStyle = COLORS.bg;
        ctx.fillRect(0, 0, w, h);

        const centerY = h / 2;
        const maxAmp = h * 0.42;

        // ── Waveform ─────────────────────────────────────────────────────────────
        if (totalDuration > 0) {
            const hasBands = bandPeaks && (bandPeaks.low || bandPeaks.mid || bandPeaks.high);

            if (hasBands) {
                // 3-Band rendering: draw each band additively
                const bands = [
                    { data: bandPeaks.low,  color: COLORS.low },
                    { data: bandPeaks.mid,  color: COLORS.mid },
                    { data: bandPeaks.high, color: COLORS.high },
                ];
                ctx.globalCompositeOperation = 'screen';
                for (const { data, color } of bands) {
                    if (!data?.length) continue;
                    ctx.beginPath();
                    ctx.strokeStyle = color.stroke;
                    ctx.lineWidth = 1;
                    for (let px = 0; px < w; px++) {
                        const idx = Math.floor((px / w) * data.length);
                        const peak = data[Math.min(idx, data.length - 1)];
                        if (!peak || isNaN(peak.max) || isNaN(peak.min)) continue;
                        const y1 = centerY + peak.min * maxAmp;
                        const y2 = centerY + peak.max * maxAmp;
                        ctx.moveTo(px + 0.5, y1);
                        ctx.lineTo(px + 0.5, y2);
                    }
                    ctx.stroke();
                }
                ctx.globalCompositeOperation = 'source-over';
            } else if (peaks?.length) {
                // Mono fallback
                ctx.beginPath();
                ctx.strokeStyle = COLORS.mono.stroke;
                ctx.lineWidth = 1;
                for (let px = 0; px < w; px++) {
                    const idx = Math.floor((px / w) * peaks.length);
                    const peak = peaks[Math.min(idx, peaks.length - 1)];
                    if (!peak || isNaN(peak.max) || isNaN(peak.min)) continue;
                    const y1 = centerY + peak.min * maxAmp;
                    const y2 = centerY + peak.max * maxAmp;
                    ctx.moveTo(px + 0.5, y1);
                    ctx.lineTo(px + 0.5, y2);
                }
                ctx.stroke();
            }
        }

        // ── Viewport highlight ────────────────────────────────────────────────────
        if (viewportStart !== null && viewportEnd !== null && totalDuration > 0) {
            const vx1 = Math.max(0, (viewportStart / totalDuration) * w);
            const vx2 = Math.min(w, (viewportEnd / totalDuration) * w);
            const vw = Math.max(4, vx2 - vx1);
            ctx.fillStyle = COLORS.viewport;
            ctx.fillRect(vx1, 0, vw, h);
            ctx.strokeStyle = COLORS.viewportBorder;
            ctx.lineWidth = 1.5;
            ctx.strokeRect(vx1 + 0.75, 0.75, vw - 1.5, h - 1.5);
        }

        // ── Playhead ─────────────────────────────────────────────────────────────
        if (playhead !== null && playhead >= 0 && totalDuration > 0) {
            const phX = (playhead / totalDuration) * w;
            ctx.strokeStyle = COLORS.playhead;
            ctx.lineWidth = 1.5;
            ctx.beginPath();
            ctx.moveTo(phX + 0.5, 0);
            ctx.lineTo(phX + 0.5, h);
            ctx.stroke();
        }

        // ── Bottom border ────────────────────────────────────────────────────────
        ctx.strokeStyle = COLORS.border;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(0, h - 0.5);
        ctx.lineTo(w, h - 0.5);
        ctx.stroke();

        ctx.restore();
    }, [peaks, bandPeaks, totalDuration, playhead, viewportStart, viewportEnd, height]);

    // Redraw on data change
    useEffect(() => { draw(); }, [draw]);

    // ResizeObserver for container width changes
    useEffect(() => {
        const container = containerRef.current;
        if (!container) return;
        const ro = new ResizeObserver(() => draw());
        ro.observe(container);
        return () => ro.disconnect();
    }, [draw]);

    // Empty state
    if (!totalDuration || totalDuration <= 0) {
        return (
            <div
                ref={containerRef}
                className={`w-full flex items-center justify-center ${className}`}
                style={{ height, background: COLORS.bg, ...style }}
            >
                <span className="text-[8px] text-ink-placeholder uppercase tracking-widest font-bold select-none">
                    No Waveform
                </span>
            </div>
        );
    }

    return (
        <div
            ref={containerRef}
            className={`w-full relative select-none overflow-hidden ${className}`}
            style={{ height, ...style }}
            onClick={onClick}
        >
            <canvas
                ref={canvasRef}
                className="absolute inset-0"
                style={{ cursor: onClick ? 'pointer' : 'default' }}
            />
        </div>
    );
});

WaveformMiniCanvas.displayName = 'WaveformMiniCanvas';

export default WaveformMiniCanvas;
