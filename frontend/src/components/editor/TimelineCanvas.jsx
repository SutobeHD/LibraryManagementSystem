/**
 * TimelineCanvas - Main editing canvas for the non-destructive audio editor
 * 
 * Features:
 * - Zoomable timeline with beat grid overlay
 * - Region blocks with waveform and envelope
 * - Playhead with smooth animation
 * - Selection/split tools
 * - Snap to grid
 */

import React, { useRef, useEffect, useState, useCallback, useMemo } from 'react';
import RegionBlock from './RegionBlock';
import { snapToGrid } from '../../audio/TimelineState';

const TimelineCanvas = ({
    state,                    // TimelineState object
    onRegionSelect,
    onRegionMove,
    onRegionResize,
    onRegionSplit,
    onVolumeChange,
    onGridAdjust,
    onSelectionChange,
    onPlayheadChange,
    onZoomChange,
    containerHeight = 240
}) => {
    const containerRef = useRef(null);
    const gridCanvasRef = useRef(null);
    const rulerCanvasRef = useRef(null);
    const playheadRef = useRef(null);
    const animationRef = useRef(null);

    const [viewportWidth, setViewportWidth] = useState(0);
    const [isSelecting, setIsSelecting] = useState(false);
    const [selectionStart, setSelectionStart] = useState(0);
    const [isDraggingGrid, setIsDraggingGrid] = useState(false);
    const [gridDragStart, setGridDragStart] = useState(0);

    const {
        regions,
        zoom,
        bpm,
        beatGrid,
        playhead,
        isPlaying,
        selection,
        snapEnabled,
        snapDivision,
        gridOffset,
        phrases
    } = state;

    // Calculate timeline dimensions
    const totalDuration = useMemo(() => {
        if (regions.length === 0) return 60; // Default 60s
        return Math.max(60, ...regions.map(r => r.timelineStart + r.duration)) + 10;
    }, [regions]);

    const timelineWidth = totalDuration * zoom;

    // Resize observer
    useEffect(() => {
        const container = containerRef.current;
        if (!container) return;

        const observer = new ResizeObserver((entries) => {
            setViewportWidth(entries[0].contentRect.width);
        });
        observer.observe(container);

        return () => observer.disconnect();
    }, []);

    // Draw beat grid
    useEffect(() => {
        const canvas = gridCanvasRef.current;
        if (!canvas) return;

        const ctx = canvas.getContext('2d');
        const dpr = window.devicePixelRatio || 1;

        canvas.width = timelineWidth * dpr;
        canvas.height = containerHeight * dpr;
        canvas.style.width = `${timelineWidth}px`;
        canvas.style.height = `${containerHeight}px`;
        ctx.scale(dpr, dpr);

        ctx.clearRect(0, 0, timelineWidth, containerHeight);

        // Calculate beats
        const useManualGrid = beatGrid && beatGrid.length > 0;

        if (useManualGrid) {
            // DYNAMIC GRID: Render based on detected beats
            beatGrid.forEach((beat, i) => {
                const x = beat.time * zoom;
                if (x < 0 || x > timelineWidth) return;

                const isDownbeat = beat.beat === 1;
                const isPhrase = i % 16 === 0;

                if (isPhrase) {
                    ctx.strokeStyle = 'rgba(234, 179, 8, 0.5)';
                    ctx.lineWidth = 2;
                } else if (isDownbeat) {
                    ctx.strokeStyle = 'rgba(239, 68, 68, 0.4)';
                    ctx.lineWidth = 1.5;
                } else {
                    ctx.strokeStyle = 'rgba(255, 255, 255, 0.08)';
                    ctx.lineWidth = 1;
                }

                ctx.beginPath();
                ctx.moveTo(x, 0);
                ctx.lineTo(x, containerHeight);
                ctx.stroke();

                if (isDownbeat) {
                    ctx.fillStyle = 'rgba(255, 255, 255, 0.3)';
                    ctx.font = '10px Inter, sans-serif';
                    ctx.fillText(`${Math.floor(i / 4) + 1}`, x + 3, 12);
                }
            });
        } else {
            // STATIC GRID: Original mathematical loop
            const beatDuration = 60 / bpm;
            const numBeats = Math.ceil(totalDuration / beatDuration);

            for (let i = 0; i < numBeats; i++) {
                const time = gridOffset + (i * beatDuration);
                const x = time * zoom;
                if (x < 0 || x > timelineWidth) continue;

                const isDownbeat = i % 4 === 0;
                const isPhrase = i % 16 === 0;

                if (isPhrase) {
                    ctx.strokeStyle = 'rgba(234, 179, 8, 0.4)';
                    ctx.lineWidth = 2;
                } else if (isDownbeat) {
                    ctx.strokeStyle = 'rgba(239, 68, 68, 0.3)';
                    ctx.lineWidth = 1.5;
                } else {
                    ctx.strokeStyle = 'rgba(255, 255, 255, 0.08)';
                    ctx.lineWidth = 1;
                }

                ctx.beginPath();
                ctx.moveTo(x, 0);
                ctx.lineTo(x, containerHeight);
                ctx.stroke();

                if (isDownbeat) {
                    ctx.fillStyle = 'rgba(255, 255, 255, 0.25)';
                    ctx.font = '10px Inter, sans-serif';
                    ctx.fillText(`${Math.floor(i / 4) + 1}`, x + 3, 12);
                }
            }
        }
    }, [zoom, bpm, gridOffset, totalDuration, timelineWidth, containerHeight, beatGrid]);

    // Draw time ruler
    useEffect(() => {
        const canvas = rulerCanvasRef.current;
        if (!canvas) return;

        const ctx = canvas.getContext('2d');
        const dpr = window.devicePixelRatio || 1;
        const rulerHeight = 24;

        canvas.width = timelineWidth * dpr;
        canvas.height = rulerHeight * dpr;
        canvas.style.width = `${timelineWidth}px`;
        canvas.style.height = `${rulerHeight}px`;
        ctx.scale(dpr, dpr);

        ctx.clearRect(0, 0, timelineWidth, rulerHeight);

        // Background
        ctx.fillStyle = 'rgba(0, 0, 0, 0.3)';
        ctx.fillRect(0, 0, timelineWidth, rulerHeight);

        // Time markers
        const pixelsPerSecond = zoom;
        let interval = 1; // 1 second

        // Adjust interval based on zoom
        if (pixelsPerSecond < 20) interval = 10;
        else if (pixelsPerSecond < 50) interval = 5;
        else if (pixelsPerSecond > 150) interval = 0.5;

        ctx.fillStyle = 'rgba(255, 255, 255, 0.5)';
        ctx.font = '9px Inter, sans-serif';

        for (let t = 0; t < totalDuration; t += interval) {
            const x = t * zoom;

            // Major tick
            ctx.strokeStyle = 'rgba(255, 255, 255, 0.3)';
            ctx.beginPath();
            ctx.moveTo(x, rulerHeight - 8);
            ctx.lineTo(x, rulerHeight);
            ctx.stroke();

            // Time label
            const minutes = Math.floor(t / 60);
            const seconds = Math.floor(t % 60);
            const label = `${minutes}:${seconds.toString().padStart(2, '0')}`;
            ctx.fillText(label, x + 2, rulerHeight - 10);
        }
    }, [zoom, totalDuration, timelineWidth]);

    // Animate playhead
    useEffect(() => {
        if (!isPlaying) return;

        const animate = () => {
            if (playheadRef.current && state.playhead !== undefined) {
                playheadRef.current.style.left = `${state.playhead * zoom}px`;
            }
            animationRef.current = requestAnimationFrame(animate);
        };

        animationRef.current = requestAnimationFrame(animate);
        return () => {
            if (animationRef.current) cancelAnimationFrame(animationRef.current);
        };
    }, [isPlaying, zoom, state.playhead]);

    // Snap helper
    const snapTime = useCallback((time) => {
        return snapToGrid(state, time);
    }, [state]);

    // Mouse handlers for selection and playhead
    const handleMouseDown = useCallback((e) => {
        if (e.button !== 0) return;

        const rect = containerRef.current.getBoundingClientRect();
        const scrollLeft = containerRef.current.scrollLeft;
        const x = e.clientX - rect.left + scrollLeft;
        const time = x / zoom;

        // Check if shift is held for selection
        if (e.shiftKey) {
            setIsSelecting(true);
            setSelectionStart(time);
        } else if (state.editMode === 'grid') {
            setIsDraggingGrid(true);
            setGridDragStart(time);
        } else {
            // Click to set playhead
            const snappedTime = snapEnabled ? snapTime(time) : time;
            onPlayheadChange?.(snappedTime);
        }
    }, [zoom, snapEnabled, snapTime, onPlayheadChange, state.editMode]);

    const handleMouseMove = useCallback((e) => {
        if (isDraggingGrid) {
            const rect = containerRef.current.getBoundingClientRect();
            const scrollLeft = containerRef.current.scrollLeft;
            const x = e.clientX - rect.left + scrollLeft;
            const time = x / zoom;
            const delta = time - gridDragStart;
            onGridAdjust?.(delta);
            setGridDragStart(time);
            return;
        }

        if (!isSelecting || selectionStart === null) return;

        const rect = containerRef.current.getBoundingClientRect();
        const scrollLeft = containerRef.current.scrollLeft;
        const x = e.clientX - rect.left + scrollLeft;
        const time = x / zoom;

        onSelectionChange?.(selectionStart, time);
    }, [isSelecting, selectionStart, zoom, onSelectionChange, isDraggingGrid, gridDragStart, onGridAdjust]);

    const handleMouseUp = useCallback(() => {
        setIsSelecting(false);
        setIsDraggingGrid(false);
    }, []);

    // Drop handler for palette items
    const handleDragOver = useCallback((e) => {
        e.preventDefault();
        e.dataTransfer.dropEffect = 'copy';
    }, []);

    const handleDrop = useCallback((e) => {
        e.preventDefault();
        const regionAndSource = e.dataTransfer.getData('application/region');
        if (!regionAndSource) return;

        try {
            const regionData = JSON.parse(regionAndSource);

            // Calculate drop time
            const rect = containerRef.current.getBoundingClientRect();
            const scrollLeft = containerRef.current.scrollLeft;
            const x = e.clientX - rect.left + scrollLeft;
            const time = x / zoom;

            // Snap if enabled
            const snappedTime = snapEnabled ? snapTime(time) : time;

            onRegionDrop?.(regionData, snappedTime);
        } catch (err) {
            console.error("Drop failed", err);
        }
    }, [zoom, snapEnabled, snapTime, onRegionDrop]);

    // Wheel for zoom
    const handleWheel = useCallback((e) => {
        if (e.ctrlKey || e.metaKey) {
            e.preventDefault();

            const rect = containerRef.current.getBoundingClientRect();
            const mouseX = e.clientX - rect.left;
            const scrollLeft = containerRef.current.scrollLeft;
            const mouseTime = (mouseX + scrollLeft) / zoom;

            // Geometric zoom for smoother experience
            const factor = e.deltaY > 0 ? 0.85 : 1.17;
            const newZoom = Math.max(10, Math.min(2000, zoom * factor));

            // Calculate new scroll position to keep mouseTime at the same mouseX
            const newScrollLeft = (mouseTime * newZoom) - mouseX;

            onZoomChange?.(newZoom);

            // Directly adjust scroll to keep it smooth
            requestAnimationFrame(() => {
                if (containerRef.current) {
                    containerRef.current.scrollLeft = newScrollLeft;
                }
            });
        }
    }, [zoom, onZoomChange]);

    return (
        <div className="flex flex-col w-full h-full bg-[#0a0a0a] select-none">
            {/* Time Ruler */}
            <div className="relative h-6 overflow-hidden border-b border-white/5">
                <div
                    className="absolute h-full"
                    style={{ width: `${timelineWidth}px` }}
                >
                    <canvas ref={rulerCanvasRef} className="absolute inset-0" />
                </div>
            </div>

            {/* Main Canvas Area */}
            <div
                ref={containerRef}
                className="relative flex-1 overflow-x-auto overflow-y-hidden cursor-crosshair"
                onMouseDown={handleMouseDown}
                onMouseMove={handleMouseMove}
                onMouseUp={handleMouseUp}
                onMouseLeave={handleMouseUp}
                onWheel={handleWheel}
                onDragOver={handleDragOver}
                onDrop={handleDrop}
            >
                <div
                    className="relative h-full"
                    style={{
                        width: `${timelineWidth}px`,
                        minWidth: '100%'
                    }}
                >
                    {/* Beat Grid Canvas */}
                    <canvas
                        ref={gridCanvasRef}
                        className="absolute inset-0 pointer-events-none"
                    />

                    {/* Selection Highlight */}
                    {selection && (
                        <div
                            className="absolute top-0 bottom-0 bg-amber2/20 border-l-2 border-r-2 border-amber2/50 pointer-events-none"
                            style={{
                                left: `${selection.start * zoom}px`,
                                width: `${(selection.end - selection.start) * zoom}px`
                            }}
                        />
                    )}

                    {/* Regions */}
                    <div className="absolute inset-0" style={{ top: '20px', bottom: '20px' }}>
                        {regions.map((region) => (
                            <RegionBlock
                                key={region.id}
                                region={region}
                                zoom={zoom}
                                containerHeight={containerHeight - 40}
                                isSelected={state.selectedRegionIds?.includes(region.id)}
                                onSelect={onRegionSelect}
                                onMove={onRegionMove}
                                onResize={onRegionResize}
                                snapToGrid={snapTime}
                            />
                        ))}
                    </div>

                    {/* Markers (Cues, Loops) */}
                    {state.markers?.map((marker, idx) => {
                        const x = marker.Start * zoom;
                        if (x < 0 || x > timelineWidth) return null;

                        const isLoop = String(marker.Type) === "4";
                        const isHotCue = marker.Num >= 0 && marker.Num <= 7;

                        if (isLoop && marker.End) {
                            const width = (marker.End - marker.Start) * zoom;
                            return (
                                <div
                                    key={`loop-${idx}`}
                                    className="absolute top-0 bottom-0 bg-green-500/20 border-l-2 border-r-2 border-green-400 overflow-hidden pointer-events-none"
                                    style={{ left: `${x}px`, width: `${width}px` }}
                                >
                                    <div className="absolute top-0 left-0 p-1 text-[8px] font-bold text-green-400 bg-black/60">LOOP</div>
                                </div>
                            );
                        }

                        // Standard Cue or Hot Cue
                        const color = isHotCue ? "#f59e0b" : "#ef4444";
                        const label = isHotCue ? `H${String.fromCharCode(65 + marker.Num)}` : "M";

                        return (
                            <div
                                key={`marker-${idx}`}
                                className="absolute top-0 bottom-0 pointer-events-none"
                                style={{ left: `${x}px`, width: '1px' }}
                            >
                                <div
                                    className="absolute top-0 left-[-6px] w-0 h-0"
                                    style={{
                                        borderLeft: '6px solid transparent',
                                        borderRight: '6px solid transparent',
                                        borderTop: `8px solid ${color}`
                                    }}
                                />
                                <div className="absolute h-full w-px" style={{ backgroundColor: color, opacity: 0.3 }} />
                                <div className="absolute top-8 left-1 px-1 bg-black/80 text-[8px] font-bold rounded" style={{ color: color }}>
                                    {label}
                                </div>
                            </div>
                        );
                    })}

                    {/* Playhead */}
                    <div
                        ref={playheadRef}
                        className="absolute top-0 bottom-0 w-0.5 bg-amber2 z-30 pointer-events-none"
                        style={{
                            left: `${playhead * zoom}px`,
                            boxShadow: '0 0 10px rgba(34, 211, 238, 0.5)'
                        }}
                    >
                        {/* Playhead triangle */}
                        <div
                            className="absolute -top-0 left-1/2 -translate-x-1/2 w-0 h-0"
                            style={{
                                borderLeft: '6px solid transparent',
                                borderRight: '6px solid transparent',
                                borderTop: '8px solid #22d3ee'
                            }}
                        />
                    </div>

                    {/* Phrase Tracks (Bottom) */}
                    <div className="absolute bottom-0 left-0 right-0 h-6 bg-black/40 border-t border-white/5 z-40">
                        {phrases?.map((phrase, idx) => {
                            const x = phrase.start * zoom;
                            const w = (phrase.end - phrase.start) * zoom;
                            return (
                                <div
                                    key={`phrase-${idx}`}
                                    className="absolute top-0 h-full border-r border-white/10 flex items-center px-1 group"
                                    style={{
                                        left: `${x}px`,
                                        width: `${w}px`,
                                        backgroundColor: `${phrase.color || '#3b82f6'}10`
                                    }}
                                    title={`${phrase.name} (${phrase.start.toFixed(2)}s - ${phrase.end.toFixed(2)}s)`}
                                >
                                    <span className="text-[9px] font-bold text-white/30 group-hover:text-white/60 truncate uppercase tracking-tighter">
                                        {phrase.name}
                                    </span>
                                </div>
                            );
                        })}
                    </div>
                </div>
            </div>

            {/* Dimmed overlay when selection is active */}
            {selection && (
                <>
                    <div
                        className="absolute inset-y-0 left-0 bg-black/30 pointer-events-none"
                        style={{ width: `${selection.start * zoom}px` }}
                    />
                    <div
                        className="absolute inset-y-0 right-0 bg-black/30 pointer-events-none"
                        style={{
                            left: `${selection.end * zoom}px`,
                            right: 0
                        }}
                    />
                </>
            )}
        </div>
    );
};

export default TimelineCanvas;
