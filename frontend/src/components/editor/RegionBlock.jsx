/**
 * RegionBlock - Visual representation of an audio region on the timeline
 * 
 * Displays the waveform, envelope overlay, and handles for resize/move
 */

import React, { useRef, useEffect, useMemo, useCallback } from 'react';
import { GripVertical, Volume2, VolumeX } from 'lucide-react';

const RegionBlock = ({
    region,
    zoom,                    // pixels per second
    containerHeight = 200,
    onSelect,
    onMove,
    onResize,
    onFadeChange,
    onGainChange,
    isSelected = false,
    snapToGrid = (t) => t
}) => {
    const canvasRef = useRef(null);
    const containerRef = useRef(null);
    const isDragging = useRef(false);
    const dragStartX = useRef(0);
    const dragStartTime = useRef(0);
    const resizeMode = useRef(null); // 'left', 'right', null

    // Calculate pixel dimensions
    const width = region.duration * zoom;
    const left = region.timelineStart * zoom;

    // Draw waveform on canvas
    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas || !region.sourceBuffer) return;

        const ctx = canvas.getContext('2d');
        const dpr = window.devicePixelRatio || 1;

        // Set canvas size
        canvas.width = width * dpr;
        canvas.height = containerHeight * dpr;
        canvas.style.width = `${width}px`;
        canvas.style.height = `${containerHeight}px`;
        ctx.scale(dpr, dpr);

        // Clear canvas
        ctx.clearRect(0, 0, width, containerHeight);

        // Draw waveform
        const buffer = region.sourceBuffer;
        const channelData = buffer.getChannelData(0);
        const sampleRate = buffer.sampleRate;

        const startSample = Math.floor(region.sourceStart * sampleRate);
        const endSample = Math.floor(region.sourceEnd * sampleRate);
        const samplesPerPixel = (endSample - startSample) / width;

        // Gradient for waveform
        const gradient = ctx.createLinearGradient(0, 0, 0, containerHeight);
        gradient.addColorStop(0, region.color || '#3b82f6');
        gradient.addColorStop(0.5, adjustColor(region.color || '#3b82f6', -30));
        gradient.addColorStop(1, region.color || '#3b82f6');

        ctx.fillStyle = gradient;
        ctx.strokeStyle = adjustColor(region.color || '#3b82f6', 40);
        ctx.lineWidth = 0.5;

        const centerY = containerHeight / 2;
        const maxAmplitude = (containerHeight / 2) * 0.85;

        ctx.beginPath();

        for (let x = 0; x < width; x++) {
            const sampleStart = startSample + Math.floor(x * samplesPerPixel);
            const sampleEnd = Math.min(sampleStart + Math.floor(samplesPerPixel), channelData.length);

            let min = 0, max = 0;
            for (let i = sampleStart; i < sampleEnd; i++) {
                const sample = channelData[i] || 0;
                if (sample < min) min = sample;
                if (sample > max) max = sample;
            }

            // Apply envelope
            const envelopeGain = calculateEnvelopeGain(
                x / width * region.duration,
                region.duration,
                region.fadeInDuration,
                region.fadeOutDuration,
                region.gain
            );

            const scaledMin = min * envelopeGain;
            const scaledMax = max * envelopeGain;

            const yTop = centerY - scaledMax * maxAmplitude;
            const yBottom = centerY - scaledMin * maxAmplitude;

            if (x === 0) {
                ctx.moveTo(x, yTop);
            }
            ctx.lineTo(x, yTop);
        }

        // Draw bottom half (mirror)
        for (let x = width - 1; x >= 0; x--) {
            const sampleStart = startSample + Math.floor(x * samplesPerPixel);
            const sampleEnd = Math.min(sampleStart + Math.floor(samplesPerPixel), channelData.length);

            let min = 0;
            for (let i = sampleStart; i < sampleEnd; i++) {
                const sample = channelData[i] || 0;
                if (sample < min) min = sample;
            }

            const envelopeGain = calculateEnvelopeGain(
                x / width * region.duration,
                region.duration,
                region.fadeInDuration,
                region.fadeOutDuration,
                region.gain
            );

            const yBottom = centerY - min * envelopeGain * maxAmplitude;
            ctx.lineTo(x, yBottom);
        }

        ctx.closePath();
        ctx.fill();
        ctx.stroke();

        // Draw envelope line
        drawEnvelope(ctx, width, containerHeight, region);

    }, [region, width, containerHeight, zoom]);

    // Calculate envelope gain at a position
    function calculateEnvelopeGain(position, duration, fadeIn, fadeOut, gain) {
        let envelope = 1;

        // Fade in
        if (position < fadeIn && fadeIn > 0) {
            envelope = position / fadeIn;
        }
        // Fade out
        else if (position > duration - fadeOut && fadeOut > 0) {
            envelope = (duration - position) / fadeOut;
        }

        return envelope * gain;
    }

    // Draw envelope overlay
    function drawEnvelope(ctx, w, h, region) {
        const { fadeInDuration, fadeOutDuration, gain, duration } = region;
        const envelopeY = 15; // Top margin for envelope line
        const lineY = envelopeY + (1 - gain) * 20; // Gain affects line height

        ctx.strokeStyle = 'rgba(255, 255, 255, 0.8)';
        ctx.lineWidth = 2;
        ctx.beginPath();

        // Start point (fade in start)
        const fadeInPx = (fadeInDuration / duration) * w;
        const fadeOutPx = (fadeOutDuration / duration) * w;

        ctx.moveTo(0, envelopeY + 20);  // Start at 0 for fade-in
        ctx.lineTo(fadeInPx, lineY);    // Ramp up
        ctx.lineTo(w - fadeOutPx, lineY); // Steady
        ctx.lineTo(w, envelopeY + 20);  // Ramp down

        ctx.stroke();

        // Draw nodes
        ctx.fillStyle = '#fff';

        // Fade in node
        ctx.beginPath();
        ctx.arc(fadeInPx, lineY, 5, 0, Math.PI * 2);
        ctx.fill();

        // Fade out node  
        ctx.beginPath();
        ctx.arc(w - fadeOutPx, lineY, 5, 0, Math.PI * 2);
        ctx.fill();

        // Gain node (center)
        ctx.fillStyle = '#facc15';
        ctx.beginPath();
        ctx.arc(w / 2, lineY, 6, 0, Math.PI * 2);
        ctx.fill();
    }

    // Color adjustment helper
    function adjustColor(hex, amount) {
        const num = parseInt(hex.replace('#', ''), 16);
        const r = Math.min(255, Math.max(0, (num >> 16) + amount));
        const g = Math.min(255, Math.max(0, ((num >> 8) & 0x00FF) + amount));
        const b = Math.min(255, Math.max(0, (num & 0x0000FF) + amount));
        return `#${(r << 16 | g << 8 | b).toString(16).padStart(6, '0')}`;
    }

    // Mouse handlers for drag/resize
    const handleMouseDown = useCallback((e) => {
        e.stopPropagation();
        onSelect?.(region.id);

        const rect = containerRef.current.getBoundingClientRect();
        const relX = e.clientX - rect.left;

        // Check if clicking on resize handles
        if (relX < 10) {
            resizeMode.current = 'left';
        } else if (relX > width - 10) {
            resizeMode.current = 'right';
        } else {
            resizeMode.current = null;
        }

        isDragging.current = true;
        dragStartX.current = e.clientX;
        dragStartTime.current = region.timelineStart;

        window.addEventListener('mousemove', handleMouseMove);
        window.addEventListener('mouseup', handleMouseUp);
    }, [region, width, onSelect]);

    const handleMouseMove = useCallback((e) => {
        if (!isDragging.current) return;

        const deltaX = e.clientX - dragStartX.current;
        const deltaTime = deltaX / zoom;

        if (resizeMode.current === 'left') {
            onResize?.(region.id, 'left', snapToGrid(deltaTime));
        } else if (resizeMode.current === 'right') {
            onResize?.(region.id, 'right', snapToGrid(deltaTime));
        } else {
            const newStart = snapToGrid(dragStartTime.current + deltaTime);
            onMove?.(region.id, newStart);
        }
    }, [region, zoom, onMove, onResize, snapToGrid]);

    const handleMouseUp = useCallback(() => {
        isDragging.current = false;
        resizeMode.current = null;
        window.removeEventListener('mousemove', handleMouseMove);
        window.removeEventListener('mouseup', handleMouseUp);
    }, [handleMouseMove]);

    return (
        <div
            ref={containerRef}
            className={`
                absolute top-0 h-full rounded-lg overflow-hidden cursor-grab
                border-2 transition-all duration-150
                ${isSelected
                    ? 'border-cyan-400 shadow-lg shadow-cyan-400/30 z-20'
                    : 'border-white/10 hover:border-white/30 z-10'
                }
                ${region.isMuted ? 'opacity-40' : 'opacity-100'}
            `}
            style={{
                left: `${left}px`,
                width: `${Math.max(width, 20)}px`,
                background: `linear-gradient(180deg, ${region.color}20 0%, ${region.color}10 100%)`
            }}
            onMouseDown={handleMouseDown}
        >
            {/* Waveform canvas */}
            <canvas
                ref={canvasRef}
                className="absolute inset-0"
            />

            {/* Region name */}
            <div className="absolute top-1 left-2 text-[10px] font-bold text-white/80 truncate max-w-[calc(100%-16px)]">
                {region.name}
            </div>

            {/* Resize handles */}
            <div className="absolute left-0 top-0 bottom-0 w-2 cursor-ew-resize bg-white/0 hover:bg-white/20" />
            <div className="absolute right-0 top-0 bottom-0 w-2 cursor-ew-resize bg-white/0 hover:bg-white/20" />

            {/* Duration label */}
            <div className="absolute bottom-1 right-2 text-[9px] font-mono text-white/60">
                {region.duration.toFixed(2)}s
            </div>

            {/* Mute indicator */}
            {region.isMuted && (
                <div className="absolute inset-0 flex items-center justify-center">
                    <VolumeX size={24} className="text-white/50" />
                </div>
            )}
        </div>
    );
};

export default RegionBlock;
