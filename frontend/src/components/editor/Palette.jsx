/**
 * Palette - Drag & Drop clipboard for audio regions
 * 
 * A side panel with slots for storing region copies.
 * Drag from timeline to palette to store.
 * Drag from palette to timeline to clone.
 */

import React, { useRef, useEffect, useState } from 'react';
import { Clipboard, X, Volume2 } from 'lucide-react';

const PaletteSlot = ({
    region,
    slotIndex,
    onDrop,
    onDragStart,
    onClear
}) => {
    const canvasRef = useRef(null);
    const [isDragOver, setIsDragOver] = useState(false);

    // Draw mini waveform preview
    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas || !region?.sourceBuffer) return;

        const ctx = canvas.getContext('2d');
        const w = canvas.width;
        const h = canvas.height;

        ctx.clearRect(0, 0, w, h);

        // Draw mini waveform
        const buffer = region.sourceBuffer;
        const channelData = buffer.getChannelData(0);
        const sampleRate = buffer.sampleRate;

        const startSample = Math.floor(region.sourceStart * sampleRate);
        const endSample = Math.floor(region.sourceEnd * sampleRate);
        const samplesPerPixel = (endSample - startSample) / w;

        ctx.fillStyle = region.color || '#3b82f6';
        const centerY = h / 2;
        const maxAmplitude = h / 2 * 0.9;

        for (let x = 0; x < w; x++) {
            const sampleStart = startSample + Math.floor(x * samplesPerPixel);
            const sampleEnd = Math.min(sampleStart + Math.floor(samplesPerPixel), channelData.length);

            let min = 0, max = 0;
            for (let i = sampleStart; i < sampleEnd; i++) {
                const sample = channelData[i] || 0;
                if (sample < min) min = sample;
                if (sample > max) max = sample;
            }

            const barHeight = (max - min) * maxAmplitude;
            ctx.fillRect(x, centerY - barHeight / 2, 1, barHeight || 1);
        }
    }, [region]);

    const handleDragOver = (e) => {
        e.preventDefault();
        setIsDragOver(true);
    };

    const handleDragLeave = () => {
        setIsDragOver(false);
    };

    const handleDrop = (e) => {
        e.preventDefault();
        setIsDragOver(false);

        const regionData = e.dataTransfer.getData('application/region');
        if (regionData) {
            onDrop?.(slotIndex, JSON.parse(regionData));
        }
    };

    const handleDragStart = (e) => {
        if (!region) return;

        e.dataTransfer.setData('application/region', JSON.stringify(region));
        e.dataTransfer.setData('source', 'palette');
        onDragStart?.(slotIndex, region);
    };

    return (
        <div
            className={`
                relative aspect-square rounded-lg border-2 transition-all duration-200
                ${region
                    ? 'bg-slate-800/50 border-white/10 cursor-grab'
                    : 'bg-slate-900/30 border-dashed border-white/5'
                }
                ${isDragOver ? 'border-cyan-400 bg-cyan-400/10 scale-105' : ''}
                hover:border-white/20
            `}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            draggable={!!region}
            onDragStart={handleDragStart}
        >
            {region ? (
                <>
                    {/* Mini waveform */}
                    <canvas
                        ref={canvasRef}
                        width={64}
                        height={48}
                        className="absolute inset-1 w-[calc(100%-8px)] h-[calc(100%-24px)] rounded"
                    />

                    {/* Duration label */}
                    <div className="absolute bottom-1 left-1 right-1 flex items-center justify-between px-1">
                        <span className="text-[8px] font-mono text-white/60">
                            {region.duration.toFixed(1)}s
                        </span>
                        <button
                            onClick={(e) => {
                                e.stopPropagation();
                                onClear?.(slotIndex);
                            }}
                            className="p-0.5 hover:bg-red-500/20 rounded text-white/40 hover:text-red-400"
                        >
                            <X size={10} />
                        </button>
                    </div>

                    {/* Slot number */}
                    <div className="absolute top-1 left-1 w-4 h-4 rounded bg-black/50 flex items-center justify-center text-[9px] font-bold text-white/60">
                        {slotIndex + 1}
                    </div>
                </>
            ) : (
                <div className="absolute inset-0 flex items-center justify-center">
                    <span className="text-[10px] text-white/20 font-bold">{slotIndex + 1}</span>
                </div>
            )}
        </div>
    );
};

const Palette = ({
    slots = Array(8).fill(null),
    onSlotDrop,
    onSlotDragStart,
    onSlotClear,
    className = ''
}) => {
    return (
        <div className={`flex flex-col gap-3 p-3 ${className}`}>
            {/* Header */}
            <div className="flex items-center gap-2 text-[10px] font-bold text-slate-500 uppercase tracking-widest">
                <Clipboard size={12} />
                <span>Palette</span>
            </div>

            {/* Slots grid */}
            <div className="grid grid-cols-2 gap-2">
                {slots.map((region, index) => (
                    <PaletteSlot
                        key={index}
                        region={region}
                        slotIndex={index}
                        onDrop={onSlotDrop}
                        onDragStart={onSlotDragStart}
                        onClear={onSlotClear}
                    />
                ))}
            </div>

            {/* Usage hint */}
            <div className="text-[9px] text-slate-600 text-center">
                Drag clips here to store
            </div>
        </div>
    );
};

export default Palette;
