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
    snapToGrid = (t) => t,
    pixelsPerSecond = 50
}) => {
    const canvasRef = useRef(null);
    const containerRef = useRef(null);
    const isDragging = useRef(false);
    const dragStartX = useRef(0);
    const dragStartTime = useRef(0);
    const resizeMode = useRef(null); // 'left', 'right', null

    const [multibandData, setMultibandData] = React.useState(null);
    const [isProcessing, setIsProcessing] = React.useState(false);

    // Fetch multi-band waveform data
    useEffect(() => {
        if (!region.sourcePath) return;

        const fetchWaveform = async () => {
            setIsProcessing(true);
            try {
                const response = await fetch(`/api/audio/waveform?path=${encodeURIComponent(region.sourcePath)}&pps=${pixelsPerSecond}`);
                const data = await response.json();
                setMultibandData(data);
            } catch (err) {
                console.error("Failed to fetch multiband waveform:", err);
            }
            setIsProcessing(false);
        };

        fetchWaveform();
    }, [region.sourcePath, pixelsPerSecond]);

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

        // Clear canvas and draw background
        ctx.fillStyle = '#050505';
        ctx.fillRect(0, 0, width, containerHeight);

        // Check compatibility
        const hasBuffer = !!region.sourceBuffer;
        if (!hasBuffer) {
            // Render basic placeholder if buffer is missing (shouldn't happen in live mode)
            ctx.fillStyle = '#1a1a1a';
            ctx.fillRect(0, 0, width, containerHeight);
            ctx.fillStyle = '#333';
            ctx.fillText("No Audio Buffer", 10, 20);
            return;
        }

        const hasMultiband = multibandData &&
            multibandData.low &&
            multibandData.low.length > 0;

        if (hasMultiband) {
            drawMultibandWaveform(ctx, width, containerHeight, region, multibandData);
        } else {
            drawStandardWaveform(ctx, width, containerHeight, region);
        }

        // Draw envelope line
        drawEnvelope(ctx, width, containerHeight, region);

    }, [region, width, containerHeight, zoom, multibandData]);

    // Standard single-band waveform
    function drawStandardWaveform(ctx, width, containerHeight, region) {
        const buffer = region.sourceBuffer;
        const channelData = buffer.getChannelData(0);
        const sampleRate = buffer.sampleRate;

        const startSample = Math.floor(region.sourceStart * sampleRate);
        const endSample = Math.floor(region.sourceEnd * sampleRate);
        const samplesPerPixel = (endSample - startSample) / width;

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

            const envelopeGain = calculateEnvelopeGain(x / width * region.duration, region.duration, region.fadeInDuration, region.fadeOutDuration, region.gain);
            const yTop = centerY - max * envelopeGain * maxAmplitude;
            if (x === 0) ctx.moveTo(x, yTop); else ctx.lineTo(x, yTop);
        }

        for (let x = width - 1; x >= 0; x--) {
            const sampleStart = startSample + Math.floor(x * samplesPerPixel);
            const sampleEnd = Math.min(sampleStart + Math.floor(samplesPerPixel), channelData.length);
            let min = 0;
            for (let i = sampleStart; i < sampleEnd; i++) {
                const sample = channelData[i] || 0;
                if (sample < min) min = sample;
            }
            const envelopeGain = calculateEnvelopeGain(x / width * region.duration, region.duration, region.fadeInDuration, region.fadeOutDuration, region.gain);
            const yBottom = centerY - min * envelopeGain * maxAmplitude;
            ctx.lineTo(x, yBottom);
        }
        ctx.closePath();
        ctx.fill();
        ctx.stroke();
    }

    // Professional 3-band RGB waveform
    function drawMultibandWaveform(ctx, width, containerHeight, region, data) {
        const centerY = containerHeight / 2;
        const maxAmplitude = (containerHeight / 2) * 0.9;

        const { low, mid, high } = data;
        const totalPoints = low.length;

        // Calculate offset into the full data based on region's start within the source
        // backend pps = 50 (assumed or passed)
        const pps = pixelsPerSecond || 50;
        const startIdx = Math.floor(region.sourceStart * pps);
        const endIdx = Math.floor(region.sourceEnd * pps);
        const pointsInRegion = endIdx - startIdx;

        const step = pointsInRegion / width;

        for (let x = 0; x < width; x++) {
            const dataIdx = startIdx + Math.floor(x * step);
            if (dataIdx >= totalPoints) break;

            const l = low[dataIdx] || 0;
            const m = mid[dataIdx] || 0;
            const h = high[dataIdx] || 0;

            const envelopeGain = calculateEnvelopeGain(x / width * region.duration, region.duration, region.fadeInDuration, region.fadeOutDuration, region.gain);

            // RGB Mix: Red (Low), Yellow/Green (Mid), Cyan/Blue (High)
            // Composite amplitude
            const totalAmp = (l + m + h) * envelopeGain * maxAmplitude;

            // Pro Color logic - Rekordbox-style (Red-Low, Amber-Mid, Blue-High)
            const r = Math.min(255, Math.floor(l * 255 + m * 180));
            const g = Math.min(255, Math.floor(m * 220 + h * 50));
            const b = Math.min(255, Math.floor(h * 255 + m * 40));

            ctx.fillStyle = `rgb(${r}, ${g}, ${b})`;

            // Draw a vertical slice
            const yStart = centerY - totalAmp / 2;
            ctx.fillRect(x, yStart, 1, Math.max(1, totalAmp));

            // Add a subtle additive overlay to make high energy transients 'pop'
            if (h > 0.6 || l > 0.8) {
                ctx.fillStyle = 'rgba(255, 255, 255, 0.15)';
                ctx.fillRect(x, yStart, 1, Math.max(1, totalAmp));
            }
        }
    }

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
        // Remove stopPropagation to allow playhead placement on regions
        // e.stopPropagation(); 
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
