import React from 'react';
import { ZoomIn, ZoomOut } from 'lucide-react';
import { ZOOM_MIN, ZOOM_MAX, ZOOM_STEP } from './useWaveformInteractions';

// Floating zoom controls overlay — sits absolutely positioned over the detail container.
// Stepped via the +/- buttons (also accessible by Ctrl/Cmd +/- hotkeys handled in the hook).
export default function WaveformZoom({ zoom, setZoom }) {
    return (
        <div className="absolute bottom-4 left-4 flex gap-2 z-50">
            <button
                onClick={() => setZoom(prev => Math.max(ZOOM_MIN, prev - ZOOM_STEP))}
                className="p-1 bg-black/60 border border-white/10 rounded pointer-events-auto"
                title="Zoom Out"
            >
                <ZoomOut size={12} />
            </button>
            <button
                onClick={() => setZoom(prev => Math.min(ZOOM_MAX, prev + ZOOM_STEP))}
                className="p-1 bg-black/60 border border-white/10 rounded pointer-events-auto"
                title="Zoom In"
            >
                <ZoomIn size={12} />
            </button>
            <div className="px-2 py-1 bg-black/60 border border-white/10 rounded text-[9px] font-mono text-ink-muted pointer-events-none">
                {zoom}px/s
            </div>
        </div>
    );
}
