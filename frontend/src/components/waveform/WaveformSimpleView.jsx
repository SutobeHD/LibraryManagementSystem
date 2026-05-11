import React from 'react';

// Stripped-down view used by RankingView (simpleMode=true) — only overview + main waveform +
// 3-band layers + mode-toggle button. No toolbar/controls/panels.
export default function WaveformSimpleView({
    overviewRef,
    waveformRef,
    waveLowRef,
    waveMidRef,
    waveHighRef,
    visualMode,
    analyzing,
    handleToggleVisualMode,
}) {
    return (
        <div className="flex flex-col h-full w-full bg-[#030303] overflow-hidden relative group rounded-xl">
            {/* Top Section: Overview with more room */}
            <div className="h-12 w-full border-b border-white/10 relative bg-black/60 shrink-0 mb-2">
                <div ref={overviewRef} className="rb-overview-container !h-full !bg-transparent" />
            </div>

            {/* Main Section: Waveform with distinct 3-band coloring (Native Gradients) */}
            <div className="relative w-full flex-1 mt-1 bg-black overflow-hidden">
                {/* 3-Band / RGB Layers - Stacked for clarity (Top to Bottom: High -> Mid -> Low) */}
                {(visualMode === 'rgb' || visualMode === '3band') && (
                    <>
                        {/* High Band (Top) */}
                        <div ref={waveHighRef} className={`absolute inset-0 z-30 pointer-events-none opacity-100 ${visualMode === 'rgb' ? 'mix-blend-screen' : 'mix-blend-normal'}`} />
                        {/* Mid Band (Middle) */}
                        <div ref={waveMidRef} className={`absolute inset-0 z-20 pointer-events-none opacity-100 ${visualMode === 'rgb' ? 'mix-blend-screen' : 'mix-blend-normal'}`} />
                        {/* Low Band (Bottom) */}
                        <div ref={waveLowRef} className={`absolute inset-0 z-10 pointer-events-none opacity-100 ${visualMode === 'rgb' ? 'mix-blend-screen' : 'mix-blend-normal'}`} />
                    </>
                )}
                {/* Master Layer (Audio/Interaction) - Keep on top for interaction but transparent */}
                <div ref={waveformRef} className="absolute inset-0 z-40" />

                {analyzing && (
                    <div className="absolute inset-0 z-30 flex items-center justify-center bg-black/50 backdrop-blur-sm">
                        <span className="text-xs font-bold text-amber2 animate-pulse">ANALYZING 3-BAND...</span>
                    </div>
                )}
            </div>

            <div className="absolute bottom-4 right-4 flex items-center gap-3 z-50">
                <button
                    onClick={handleToggleVisualMode}
                    className="text-[10px] font-black text-white/50 hover:text-white hover:bg-black tracking-[0.2em] uppercase bg-black/80 px-3 py-1.5 rounded-lg border border-white/10 backdrop-blur-md shadow-2xl transition-all cursor-pointer"
                    title="Toggle Waveform Color"
                >
                    {visualMode.toUpperCase()}
                </button>
            </div>
        </div>
    );
}
