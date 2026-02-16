/**
 * EnvelopeOverlay - Interactive envelope editor for audio regions
 * 
 * Provides draggable nodes for:
 * - Fade-in duration (left edge)
 * - Fade-out duration (right edge)
 * - Gain level (center line)
 */

import React, { useRef, useState, useCallback } from 'react';

const EnvelopeOverlay = ({
    region,
    width,
    height = 200,
    onFadeInChange,
    onFadeOutChange,
    onGainChange
}) => {
    const containerRef = useRef(null);
    const [activeNode, setActiveNode] = useState(null);
    const [isDragging, setIsDragging] = useState(false);

    const { fadeInDuration, fadeOutDuration, gain, duration } = region;

    // Convert time to pixels
    const fadeInPx = (fadeInDuration / duration) * width;
    const fadeOutPx = (fadeOutDuration / duration) * width;
    const gainY = 20 + (1 - gain) * 40; // Gain line Y position (higher gain = lower Y)

    const handleMouseDown = useCallback((e, node) => {
        e.stopPropagation();
        setActiveNode(node);
        setIsDragging(true);

        const handleMouseMove = (e) => {
            if (!containerRef.current) return;

            const rect = containerRef.current.getBoundingClientRect();
            const x = e.clientX - rect.left;
            const y = e.clientY - rect.top;

            if (node === 'fadeIn') {
                const newFadeIn = Math.max(0, Math.min(duration / 2, (x / width) * duration));
                onFadeInChange?.(newFadeIn);
            } else if (node === 'fadeOut') {
                const newFadeOut = Math.max(0, Math.min(duration / 2, ((width - x) / width) * duration));
                onFadeOutChange?.(newFadeOut);
            } else if (node === 'gain') {
                const newGain = Math.max(0, Math.min(2, 1 - (y - 20) / 40));
                onGainChange?.(newGain);
            }
        };

        const handleMouseUp = () => {
            setIsDragging(false);
            setActiveNode(null);
            window.removeEventListener('mousemove', handleMouseMove);
            window.removeEventListener('mouseup', handleMouseUp);
        };

        window.addEventListener('mousemove', handleMouseMove);
        window.addEventListener('mouseup', handleMouseUp);
    }, [duration, width, onFadeInChange, onFadeOutChange, onGainChange]);

    return (
        <div
            ref={containerRef}
            className="absolute inset-0 pointer-events-none"
            style={{ height: `${height}px` }}
        >
            {/* Envelope line SVG */}
            <svg
                className="absolute inset-0 w-full h-full overflow-visible"
                style={{ height: '60px', top: '0' }}
            >
                {/* Envelope path */}
                <path
                    d={`
                        M 0,60
                        L ${fadeInPx},${gainY}
                        L ${width - fadeOutPx},${gainY}
                        L ${width},60
                    `}
                    fill="none"
                    stroke="rgba(255, 255, 255, 0.6)"
                    strokeWidth="2"
                    strokeLinecap="round"
                />

                {/* Fill under envelope */}
                <path
                    d={`
                        M 0,60
                        L ${fadeInPx},${gainY}
                        L ${width - fadeOutPx},${gainY}
                        L ${width},60
                        L ${width},60
                        L 0,60
                        Z
                    `}
                    fill="url(#envelope-gradient)"
                    opacity="0.3"
                />

                {/* Gradient definition */}
                <defs>
                    <linearGradient id="envelope-gradient" x1="0%" y1="0%" x2="0%" y2="100%">
                        <stop offset="0%" stopColor="#22d3ee" stopOpacity="0.5" />
                        <stop offset="100%" stopColor="#22d3ee" stopOpacity="0" />
                    </linearGradient>
                </defs>
            </svg>

            {/* Fade-in node */}
            <div
                className={`
                    absolute pointer-events-auto cursor-ew-resize
                    w-4 h-4 rounded-full border-2 
                    transition-all duration-150
                    ${activeNode === 'fadeIn'
                        ? 'bg-cyan-400 border-white scale-125'
                        : 'bg-white/80 border-cyan-400 hover:bg-cyan-400'
                    }
                `}
                style={{
                    left: `${fadeInPx - 8}px`,
                    top: `${gainY - 8}px`
                }}
                onMouseDown={(e) => handleMouseDown(e, 'fadeIn')}
            />

            {/* Gain node (center) */}
            <div
                className={`
                    absolute pointer-events-auto cursor-ns-resize
                    w-5 h-5 rounded-full border-2 
                    transition-all duration-150
                    ${activeNode === 'gain'
                        ? 'bg-yellow-400 border-white scale-125'
                        : 'bg-yellow-400/80 border-yellow-300 hover:bg-yellow-400'
                    }
                `}
                style={{
                    left: `${width / 2 - 10}px`,
                    top: `${gainY - 10}px`
                }}
                onMouseDown={(e) => handleMouseDown(e, 'gain')}
            >
                <span className="absolute -bottom-5 left-1/2 -translate-x-1/2 text-[8px] font-bold text-yellow-400 whitespace-nowrap">
                    {(gain * 100).toFixed(0)}%
                </span>
            </div>

            {/* Fade-out node */}
            <div
                className={`
                    absolute pointer-events-auto cursor-ew-resize
                    w-4 h-4 rounded-full border-2 
                    transition-all duration-150
                    ${activeNode === 'fadeOut'
                        ? 'bg-cyan-400 border-white scale-125'
                        : 'bg-white/80 border-cyan-400 hover:bg-cyan-400'
                    }
                `}
                style={{
                    left: `${width - fadeOutPx - 8}px`,
                    top: `${gainY - 8}px`
                }}
                onMouseDown={(e) => handleMouseDown(e, 'fadeOut')}
            />
        </div>
    );
};

export default EnvelopeOverlay;
