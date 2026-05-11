import React, { useEffect } from 'react';
import { Loader2, Music, Upload } from 'lucide-react';
import { log } from '../../utils/log';

// Canvas-based beatgrid renderer + WaveSurfer mount points (main + overview + 3-band layers).
// Receives refs from the orchestrator so WaveSurfer keeps a stable mount target.
// Floating overlays (cuts summary, zoom buttons, etc.) are slotted via children so
// they sit inside .rb-detail-container and stack with z-index over the wave divs.
export default function WaveformCanvas({
    waveformRef,
    overviewRef,
    beatCanvasRef,
    waveLowRef,
    waveMidRef,
    waveHighRef,
    wavesurfer,
    visualMode,
    streaming,
    loading,
    isDragOver,
    onDragEnter,
    onDragOver,
    onDragLeave,
    onDrop,
    beats,
    duration,
    bpm,
    zoom,
    children,
}) {
    // 1. Grid Rendering Effect — Canvas-based (1 element vs 1000+ regions)
    useEffect(() => {
        if (!wavesurfer.current || !duration || !beats?.length || !beatCanvasRef.current) return;

        const canvas = beatCanvasRef.current;
        const wrapper = wavesurfer.current.getWrapper();
        const scrollEl = wrapper?.parentElement;
        if (!scrollEl) return;

        let rafPending = false;

        const drawGrid = () => {
            rafPending = false;
            const ctx = canvas.getContext('2d');
            const dpr = window.devicePixelRatio || 1;
            const w = scrollEl.clientWidth;
            const h = scrollEl.clientHeight;
            if (!w || !h) return;

            canvas.width = w * dpr;
            canvas.height = h * dpr;
            canvas.style.width = `${w}px`;
            canvas.style.height = `${h}px`;
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
            ctx.clearRect(0, 0, w, h);

            const pxPerSec = scrollEl.scrollWidth / duration;
            const scrollLeft = scrollEl.scrollLeft;
            const startTime = scrollLeft / pxPerSec - 0.5;
            const endTime = (scrollLeft + w) / pxPerSec + 0.5;

            // Adaptive density: skip non-downbeats at low zoom
            const pxPerBeat = pxPerSec * (60 / bpm);
            const showAllBeats = pxPerBeat >= 12;

            for (let i = 0; i < beats.length; i++) {
                const b = beats[i];
                if (b.time < startTime || b.time > endTime) continue;
                if (!showAllBeats && !b.isDownbeat) continue;

                const x = Math.round(b.time * pxPerSec - scrollLeft) + 0.5;

                if (b.isDownbeat) {
                    // Vertical line
                    ctx.strokeStyle = 'rgba(255, 255, 255, 0.22)';
                    ctx.lineWidth = 1;
                    ctx.beginPath();
                    ctx.moveTo(x, 0);
                    ctx.lineTo(x, h);
                    ctx.stroke();

                    // Top triangle
                    ctx.fillStyle = 'rgba(255, 60, 60, 0.95)';
                    ctx.beginPath();
                    ctx.moveTo(x - 4, 0);
                    ctx.lineTo(x + 4, 0);
                    ctx.lineTo(x, 5);
                    ctx.closePath();
                    ctx.fill();

                    // Bottom triangle
                    ctx.beginPath();
                    ctx.moveTo(x - 4, h);
                    ctx.lineTo(x + 4, h);
                    ctx.lineTo(x, h - 5);
                    ctx.closePath();
                    ctx.fill();

                    // Bar number
                    ctx.fillStyle = 'rgba(255, 255, 255, 0.55)';
                    ctx.font = 'bold 10px ui-monospace, Menlo, monospace';
                    ctx.fillText(String(b.barNum), x + 4, 12);
                } else {
                    ctx.strokeStyle = 'rgba(255, 255, 255, 0.06)';
                    ctx.lineWidth = 1;
                    ctx.beginPath();
                    ctx.moveTo(x, 0);
                    ctx.lineTo(x, h);
                    ctx.stroke();
                }
            }
        };

        const scheduleDraw = () => {
            if (rafPending) return;
            rafPending = true;
            requestAnimationFrame(drawGrid);
        };

        drawGrid();
        // Schedule extra redraws after WaveSurfer applies zoom (async DOM update)
        const t1 = setTimeout(scheduleDraw, 50);
        const t2 = setTimeout(scheduleDraw, 200);

        scrollEl.addEventListener('scroll', scheduleDraw, { passive: true });
        const ro = new ResizeObserver(scheduleDraw);
        ro.observe(scrollEl);

        // Listen to WaveSurfer zoom event for accurate redraw timing
        const zoomHandler = () => scheduleDraw();
        wavesurfer.current.on('zoom', zoomHandler);

        return () => {
            clearTimeout(t1);
            clearTimeout(t2);
            scrollEl.removeEventListener('scroll', scheduleDraw);
            ro.disconnect();
            try { wavesurfer.current?.un('zoom', zoomHandler); } catch (e) { log.debug('WaveformEditor zoom listener cleanup failed', e); }
        };
    }, [beats, zoom, duration, bpm, wavesurfer, beatCanvasRef]);

    return (
        <div className="flex-1 flex flex-col bg-black">
            {/* Overview */}
            <div ref={overviewRef} className="rb-overview-container" />

            {/* Detail View */}
            <div
                className={`rb-detail-container relative transition-all ${isDragOver ? 'ring-2 ring-amber2 ring-inset' : ''}`}
                onDragEnter={onDragEnter}
                onDragOver={onDragOver}
                onDragLeave={onDragLeave}
                onDrop={onDrop}
            >
                {streaming ? (
                    <div className="absolute inset-0 z-[60] flex flex-col items-center justify-center bg-black/40 backdrop-blur-sm">
                        <div className="bg-mx-shell/80 p-8 rounded-2xl border border-white/10 flex flex-col items-center gap-4 shadow-2xl">
                            <div className="w-16 h-16 bg-amber-500/20 rounded-full flex items-center justify-center border border-amber-500/30">
                                <Music size={32} className="text-amber-500" />
                            </div>
                            <div className="text-center">
                                <h3 className="text-lg font-bold text-white mb-1 tracking-tight">Stream Not Supported</h3>
                                <p className="text-sm text-ink-secondary max-w-[240px] leading-relaxed">
                                    Cloud and subscription tracks (SoundCloud, Spotify, etc.) cannot be analyzed or edited directly.
                                </p>
                            </div>
                            <div className="flex gap-2 mt-2">
                                <span className="px-3 py-1 bg-amber-500/10 text-amber-500 text-[10px] font-bold rounded-full border border-amber-500/20 uppercase tracking-widest">
                                    Restricted
                                </span>
                            </div>
                        </div>
                    </div>
                ) : (
                    loading && (
                        <div className="absolute inset-0 z-50 flex flex-col items-center justify-center bg-black/60 backdrop-blur-md">
                            <Loader2 className="w-12 h-12 text-amber2 animate-spin mb-4" />
                            <div className="text-amber2 font-bold uppercase tracking-widest text-xs animate-pulse">Loading Audio...</div>
                            <div className="text-[10px] text-ink-muted mt-2">Decoding high-fidelity waveform buffer</div>
                        </div>
                    )
                )}

                <div ref={waveformRef} className={`w-full h-full ws-wave-freq relative z-40
                    ${visualMode === 'blue' ? 'filter grayscale-[1] sepia-[1] hue-rotate-[190deg] saturate-[3] brightness-[0.8]' : ''}
                    ${streaming ? 'opacity-20 pointer-events-none' : ''}
                `} />

                {/* Canvas-based Beat Grid (replaces 1000+ Region DOM nodes) */}
                {!streaming && (
                    <canvas ref={beatCanvasRef} className="absolute top-0 left-0 z-[45] pointer-events-none" />
                )}

                {/* Multi-Band Layers (Real Waveforms) */}
                {!streaming && (visualMode === 'rgb' || visualMode === '3band') && (
                    <>
                        {/* Stacking: High (Top) > Mid > Low (Bottom) */}
                        {/* High Band (Highs) */}
                        <div ref={waveHighRef} className={`absolute inset-0 z-30 pointer-events-none opacity-100 ${visualMode === 'rgb' ? 'mix-blend-screen' : 'mix-blend-normal'}`} />
                        {/* Mid Band (Mids) */}
                        <div ref={waveMidRef} className={`absolute inset-0 z-20 pointer-events-none opacity-100 ${visualMode === 'rgb' ? 'mix-blend-screen' : 'mix-blend-normal'}`} />
                        {/* Low Band (Bass) */}
                        <div ref={waveLowRef} className={`absolute inset-0 z-10 pointer-events-none opacity-100 ${visualMode === 'rgb' ? 'mix-blend-screen' : 'mix-blend-normal'}`} />
                    </>
                )}

                {/* Drop Zone Overlay — visual feedback while dragging audio file */}
                {isDragOver && (
                    <div className="absolute inset-0 z-[80] flex items-center justify-center bg-black/70 backdrop-blur-sm pointer-events-none">
                        <div className="flex flex-col items-center gap-3 p-6 border-2 border-dashed border-amber2 rounded-2xl bg-amber2/10">
                            <Upload size={48} className="text-amber2 animate-bounce" />
                            <div className="text-amber2 font-bold uppercase tracking-widest text-sm">Drop audio file to load</div>
                            <div className="text-[10px] text-ink-muted">.wav  .mp3  .flac  .aac  .ogg  .m4a</div>
                        </div>
                    </div>
                )}

                {/* Slot: zoom controls, cuts summary, etc. — orchestrator passes WaveformZoom + WaveformOverlays here. */}
                {children}
            </div>
        </div>
    );
}
