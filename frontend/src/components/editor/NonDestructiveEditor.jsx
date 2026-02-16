/**
 * NonDestructiveEditor - Main component for the non-destructive audio editor
 * 
 * Combines all editor components:
 * - Timeline canvas with waveform/regions
 * - Toolbar with editing tools
 * - Palette for clip storage
 * - Playback controls
 */

import React, { useState, useCallback, useRef, useEffect, useMemo } from 'react';
import {
    Play, Pause, SkipBack, SkipForward, Scissors, Copy, Clipboard,
    ZoomIn, ZoomOut, Magnet, Trash2, Download, Undo2, Redo2,
    Grid3X3, Volume2, Loader2, Music, ChevronDown, Save, FolderOpen, X
} from 'lucide-react';
import api from '../../api/api';

import TimelineCanvas from './TimelineCanvas';
import Palette from './Palette';
import {
    createTimelineState,
    loadAudioSource,
    addRegion,
    removeRegion,
    updateRegion,
    setSelection,
    selectRegions,
    clearSelection,
    setPaletteSlot,
    findEmptyPaletteSlot,
    setPlayhead,
    toggleSnap,
    setSnapDivision,
    setZoom,
    pushHistory,
    undo,
    redo,
    snapToGrid as snapToGridFn
} from '../../audio/TimelineState';
import {
    createRegion,
    cloneRegion,
    splitRegion,
    moveRegion,
    setEnvelope
} from '../../audio/AudioRegion';

const NonDestructiveEditor = ({
    sourceUrl,
    sourcePath,
    track,
    bpm = 128,
    beatGrid = [],
    onRenderComplete,
    className = ''
}) => {
    const audioContextRef = useRef(null);
    const sourceBufferRef = useRef(null);
    const playerRef = useRef(null);
    const startTimeRef = useRef(0);
    const pauseTimeRef = useRef(0);

    const [state, setState] = useState(() =>
        createTimelineState({ bpm, beatGrid, zoom: 50 })
    );
    const [isLoading, setIsLoading] = useState(true);
    const [isPlaying, setIsPlaying] = useState(false);
    const [isRendering, setIsRendering] = useState(false);
    const [renderProgress, setRenderProgress] = useState(0);
    const [showLoadModal, setShowLoadModal] = useState(false);
    const [projectList, setProjectList] = useState([]);

    // Load audio source
    useEffect(() => {
        if (!sourceUrl) return;

        const loadAudio = async () => {
            setIsLoading(true);
            try {
                const ctx = new (window.AudioContext || window.webkitAudioContext)();
                audioContextRef.current = ctx;

                const response = await fetch(sourceUrl);
                const arrayBuffer = await response.arrayBuffer();
                const audioBuffer = await ctx.decodeAudioData(arrayBuffer);

                sourceBufferRef.current = audioBuffer;

                setState(prev => loadAudioSource(prev, audioBuffer, sourcePath));
                setIsLoading(false);
            } catch (error) {
                console.error('Failed to load audio:', error);
                setIsLoading(false);
            }
        };

        loadAudio();

        return () => {
            if (audioContextRef.current) {
                audioContextRef.current.close();
            }
        };
    }, [sourceUrl, sourcePath]);

    // Playback controls
    const handlePlay = useCallback(() => {
        if (!audioContextRef.current || !sourceBufferRef.current) return;

        const ctx = audioContextRef.current;
        if (ctx.state === 'suspended') ctx.resume();

        const source = ctx.createBufferSource();
        source.buffer = sourceBufferRef.current;
        source.connect(ctx.destination);

        const offset = pauseTimeRef.current || state.playhead;
        source.start(0, offset);
        startTimeRef.current = ctx.currentTime - offset;
        playerRef.current = source;

        setIsPlaying(true);
        setState(prev => ({ ...prev, isPlaying: true }));

        // Update playhead during playback
        const updatePlayhead = () => {
            if (!isPlaying) return;
            const currentTime = ctx.currentTime - startTimeRef.current;
            setState(prev => ({ ...prev, playhead: currentTime }));
            requestAnimationFrame(updatePlayhead);
        };
        requestAnimationFrame(updatePlayhead);

        source.onended = () => {
            setIsPlaying(false);
            setState(prev => ({ ...prev, isPlaying: false }));
        };
    }, [state.playhead]);

    const handlePause = useCallback(() => {
        if (playerRef.current) {
            playerRef.current.stop();
            pauseTimeRef.current = audioContextRef.current.currentTime - startTimeRef.current;
        }
        setIsPlaying(false);
        setState(prev => ({ ...prev, isPlaying: false }));
    }, []);

    const handleStop = useCallback(() => {
        if (playerRef.current) {
            playerRef.current.stop();
        }
        pauseTimeRef.current = 0;
        setIsPlaying(false);
        setState(prev => ({ ...prev, isPlaying: false, playhead: 0 }));
    }, []);

    // Region operations
    const handleRegionSelect = useCallback((regionId) => {
        setState(prev => selectRegions(prev, [regionId]));
    }, []);

    const handleRegionMove = useCallback((regionId, newStart) => {
        setState(prev => updateRegion(prev, regionId, { timelineStart: newStart }));
    }, []);

    const handleRegionResize = useCallback((regionId, side, delta) => {
        setState(prev => {
            const region = prev.regions.find(r => r.id === regionId);
            if (!region) return prev;

            if (side === 'left') {
                const newSourceStart = Math.max(0, region.sourceStart + delta);
                const newTimelineStart = region.timelineStart + delta;
                return updateRegion(prev, regionId, {
                    sourceStart: newSourceStart,
                    timelineStart: newTimelineStart
                });
            } else {
                const newSourceEnd = Math.min(
                    sourceBufferRef.current?.duration || region.sourceEnd,
                    region.sourceEnd + delta
                );
                return updateRegion(prev, regionId, { sourceEnd: newSourceEnd });
            }
        });
    }, []);

    const handleSplit = useCallback(() => {
        const selectedId = state.selectedRegionIds[0];
        if (!selectedId) return;

        const region = state.regions.find(r => r.id === selectedId);
        if (!region) return;

        const [left, right] = splitRegion(region, state.playhead);
        if (!right) return;

        setState(prev => {
            const newState = pushHistory(prev, { type: 'split', regionId: selectedId });
            const withoutOriginal = removeRegion(newState, selectedId);
            let final = addRegion(withoutOriginal, left);
            final = addRegion(final, right);
            return selectRegions(final, [right.id]);
        });
    }, [state.selectedRegionIds, state.regions, state.playhead]);

    const handleCopy = useCallback(() => {
        const selectedId = state.selectedRegionIds[0];
        if (!selectedId) return;

        const region = state.regions.find(r => r.id === selectedId);
        if (!region) return;

        const slotIndex = findEmptyPaletteSlot(state);
        if (slotIndex === -1) return; // All slots full

        setState(prev => setPaletteSlot(prev, slotIndex, cloneRegion(region)));
    }, [state.selectedRegionIds, state.regions, state]);

    const handleDelete = useCallback(() => {
        const selectedId = state.selectedRegionIds[0];
        if (!selectedId) return;

        setState(prev => {
            const newState = pushHistory(prev, { type: 'delete', regionId: selectedId });
            return removeRegion(newState, selectedId);
        });
    }, [state.selectedRegionIds]);

    const handleUndo = useCallback(() => {
        setState(prev => undo(prev));
    }, []);

    const handleRedo = useCallback(() => {
        setState(prev => redo(prev));
    }, []);

    // Project Persistence
    const handleSaveProject = useCallback(async () => {
        const name = prompt("Enter project name:", track?.Title || "Untitled Project");
        if (!name) return;

        // Serialize state: Remove AudioBuffers (circular/large)
        const serializableRegions = state.regions.map(r => {
            const { sourceBuffer, ...rest } = r;
            return rest;
        });

        const projectData = {
            version: 1,
            sourcePath,
            trackId: track?.id,
            bpm: state.bpm,
            beatGrid: state.beatGrid,
            zoom: state.zoom,
            snapEnabled: state.snapEnabled,
            snapDivision: state.snapDivision,
            regions: serializableRegions,
            paletteSlots: state.paletteSlots.map(slot => {
                if (!slot) return null;
                const { sourceBuffer, ...rest } = slot;
                return rest;
            })
        };

        try {
            await api.post('/api/projects/save', { name, data: projectData });
            alert("Project saved successfully!");
        } catch (error) {
            console.error(error);
            alert("Failed to save project.");
        }
    }, [state, sourcePath, track]);

    const handleLoadClick = useCallback(async () => {
        try {
            const res = await api.get('/api/projects');
            setProjectList(res.data);
            setShowLoadModal(true);
        } catch (e) { alert("Failed to list projects"); }
    }, []);

    const loadProject = async (prjName) => {
        try {
            setIsLoading(true);
            setShowLoadModal(false);
            const res = await api.get(`/api/projects/${prjName}`);
            const data = res.data;

            // 1. Check/Load Audio Source
            let buffer = sourceBufferRef.current;
            if (data.sourcePath !== sourcePath) {
                // Determine URL for sourcePath
                // Assuming standard stream URL format
                const url = `/api/stream?path=${encodeURIComponent(data.sourcePath)}`;
                const ctx = audioContextRef.current || new (window.AudioContext || window.webkitAudioContext)();
                if (!audioContextRef.current) audioContextRef.current = ctx;

                const resp = await fetch(url);
                const ab = await resp.arrayBuffer();
                buffer = await ctx.decodeAudioData(ab);
                sourceBufferRef.current = buffer;
            }

            // 2. Hydrate Regions with Buffer
            const hydratedRegions = data.regions.map(r => ({
                ...r,
                sourceBuffer: buffer,
                sourcePath: data.sourcePath
            }));

            const hydratedPalette = (data.paletteSlots || []).map(s => s ? ({
                ...s,
                sourceBuffer: buffer,
                sourcePath: data.sourcePath
            }) : null);

            // 3. Set State
            setState(prev => ({
                ...prev,
                regions: hydratedRegions,
                paletteSlots: hydratedPalette,
                bpm: data.bpm,
                beatGrid: data.beatGrid || [],
                zoom: data.zoom || 50,
                snapEnabled: data.snapEnabled,
                snapDivision: data.snapDivision || '1/4',
                playhead: 0,
                history: [],
                historyIndex: -1
            }));

            setIsLoading(false);
        } catch (e) {
            console.error(e);
            alert("Failed to load project: " + e.message);
            setIsLoading(false);
        }
    };

    // Palette handlers
    const handlePaletteSlotDrop = useCallback((slotIndex, regionData) => {
        // Create a proper region from the dropped data
        const region = createRegion({
            sourceBuffer: sourceBufferRef.current,
            sourcePath: sourcePath,
            sourceStart: regionData.sourceStart,
            sourceEnd: regionData.sourceEnd,
            timelineStart: regionData.timelineStart,
            name: regionData.name,
            color: regionData.color
        });

        setState(prev => setPaletteSlot(prev, slotIndex, region));
    }, [sourcePath]);

    const handlePaletteDragStart = useCallback((slotIndex, region) => {
        // Could track which slot is being dragged
    }, []);

    const handlePaletteSlotClear = useCallback((slotIndex) => {
        setState(prev => setPaletteSlot(prev, slotIndex, null));
    }, []);

    // Zoom handlers
    const handleZoomIn = useCallback(() => {
        setState(prev => setZoom(prev, prev.zoom + 20));
    }, []);

    const handleZoomOut = useCallback(() => {
        setState(prev => setZoom(prev, prev.zoom - 20));
    }, []);

    const handleZoomChange = useCallback((newZoom) => {
        setState(prev => setZoom(prev, newZoom));
    }, []);

    // Snap toggle
    const handleToggleSnap = useCallback(() => {
        setState(prev => toggleSnap(prev));
    }, []);

    // Selection change
    const handleSelectionChange = useCallback((start, end) => {
        setState(prev => setSelection(prev, start, end));
    }, []);

    // Playhead change
    const handlePlayheadChange = useCallback((time) => {
        pauseTimeRef.current = time;
        setState(prev => setPlayhead(prev, time));
    }, []);

    // Render / Export
    const handleRender = useCallback(async () => {
        if (!sourceBufferRef.current || state.regions.length === 0) return;

        setIsRendering(true);
        setRenderProgress(10);

        try {
            const sortedRegions = [...state.regions].sort(
                (a, b) => a.timelineStart - b.timelineStart
            );

            const totalDuration = Math.max(
                ...sortedRegions.map(r => r.timelineStart + (r.sourceEnd - r.sourceStart))
            );

            const sampleRate = sourceBufferRef.current.sampleRate;
            const channels = sourceBufferRef.current.numberOfChannels;
            const offlineCtx = new OfflineAudioContext(
                channels,
                Math.ceil(totalDuration * sampleRate),
                sampleRate
            );

            setRenderProgress(30);

            for (const region of sortedRegions) {
                const source = offlineCtx.createBufferSource();
                source.buffer = region.sourceBuffer;

                // Create gain node for envelope
                const gainNode = offlineCtx.createGain();

                const regionStart = region.timelineStart;
                const regionDuration = region.sourceEnd - region.sourceStart;
                const regionEnd = regionStart + regionDuration;

                // Apply fade-in
                gainNode.gain.setValueAtTime(0, regionStart);
                gainNode.gain.linearRampToValueAtTime(
                    region.gain,
                    regionStart + region.fadeInDuration
                );

                // Steady gain
                gainNode.gain.setValueAtTime(
                    region.gain,
                    regionEnd - region.fadeOutDuration
                );

                // Fade-out
                gainNode.gain.linearRampToValueAtTime(0, regionEnd);

                source.connect(gainNode);
                gainNode.connect(offlineCtx.destination);

                source.start(regionStart, region.sourceStart, regionDuration);
            }

            setRenderProgress(60);

            const renderedBuffer = await offlineCtx.startRendering();

            setRenderProgress(90);

            // Convert to WAV blob
            const wavBlob = bufferToWave(renderedBuffer, renderedBuffer.length);

            // Create download link
            const url = URL.createObjectURL(wavBlob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${track?.Title || 'Rendered'}_Edit_${Date.now()}.wav`;
            a.click();
            URL.revokeObjectURL(url);

            setRenderProgress(100);
            setTimeout(() => {
                setIsRendering(false);
                setRenderProgress(0);
            }, 500);

            onRenderComplete?.(wavBlob);
        } catch (error) {
            console.error('Render failed:', error);
            setIsRendering(false);
            setRenderProgress(0);
        }
    }, [state.regions, track, onRenderComplete]);

    // Buffer to WAV conversion
    function bufferToWave(abuffer, len) {
        const numOfChan = abuffer.numberOfChannels;
        const length = len * numOfChan * 2 + 44;
        const buffer = new ArrayBuffer(length);
        const view = new DataView(buffer);
        const channels = [];
        let offset = 0;
        let pos = 0;

        function setUint16(data) { view.setUint16(pos, data, true); pos += 2; }
        function setUint32(data) { view.setUint32(pos, data, true); pos += 4; }

        setUint32(0x46464952); // "RIFF"
        setUint32(length - 8);
        setUint32(0x45564157); // "WAVE"
        setUint32(0x20746d66); // "fmt "
        setUint32(16);
        setUint16(1);
        setUint16(numOfChan);
        setUint32(abuffer.sampleRate);
        setUint32(abuffer.sampleRate * 2 * numOfChan);
        setUint16(numOfChan * 2);
        setUint16(16);
        setUint32(0x61746164); // "data"
        setUint32(length - pos - 4);

        for (let i = 0; i < abuffer.numberOfChannels; i++)
            channels.push(abuffer.getChannelData(i));

        while (pos < len) {
            for (let i = 0; i < numOfChan; i++) {
                let sample = Math.max(-1, Math.min(1, channels[i][pos]));
                sample = (0.5 + sample < 0 ? sample * 32768 : sample * 32767) | 0;
                view.setInt16(44 + offset, sample, true);
                offset += 2;
            }
            pos++;
        }

        return new Blob([buffer], { type: 'audio/wav' });
    }

    // Time formatting
    const formatTime = (s) => {
        const m = Math.floor(s / 60);
        const sec = Math.floor(s % 60);
        const ms = Math.floor((s % 1) * 100);
        return `${m}:${sec.toString().padStart(2, '0')}.${ms.toString().padStart(2, '0')}`;
    };

    if (isLoading) {
        return (
            <div className={`flex items-center justify-center h-full bg-black ${className}`}>
                <Loader2 className="w-8 h-8 text-cyan-400 animate-spin" />
                <span className="ml-3 text-slate-400">Loading audio...</span>
            </div>
        );
    }

    return (
        <div className={`flex flex-col h-full bg-[#0a0a0a] text-white ${className}`}>
            {/* Render overlay */}
            {isRendering && (
                <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/90 backdrop-blur-md">
                    <div className="w-80 p-8 rounded-2xl bg-slate-900/80 border border-cyan-500/20 flex flex-col items-center">
                        <Loader2 size={48} className="text-cyan-400 animate-spin mb-6" />
                        <h3 className="text-xl font-bold mb-2">Rendering Audio</h3>
                        <p className="text-slate-400 text-sm mb-6">Applying edits and effects...</p>
                        <div className="w-full h-2 bg-white/5 rounded-full overflow-hidden mb-2">
                            <div
                                className="h-full bg-gradient-to-r from-cyan-500 to-blue-600 transition-all duration-300"
                                style={{ width: `${renderProgress}%` }}
                            />
                        </div>
                        <div className="text-xs font-mono text-cyan-500">{renderProgress}% COMPLETE</div>
                    </div>
                </div>
            )}

            {/* Top Toolbar */}
            <div className="h-12 bg-[#111] border-b border-white/5 px-4 flex items-center justify-between">
                <div className="flex items-center gap-4">
                    {/* Track info */}
                    <div className="flex items-center gap-2">
                        <Music size={14} className="text-cyan-400" />
                        <span className="text-sm font-bold text-white truncate max-w-[200px]">
                            {track?.Title || 'Untitled'}
                        </span>
                    </div>

                    {/* BPM */}
                    <div className="text-xs bg-black/30 px-2 py-1 rounded border border-white/5">
                        <span className="text-slate-500">BPM</span>
                        <span className="ml-2 text-cyan-400 font-mono">{state.bpm.toFixed(1)}</span>
                    </div>
                </div>

                {/* Project Controls */}
                <div className="flex items-center gap-1 mr-4 border-r border-white/10 pr-4">
                    <button onClick={handleSaveProject} className="p-2 hover:bg-white/5 rounded text-slate-400 hover:text-green-400" title="Save Project">
                        <Save size={16} />
                    </button>
                    <button onClick={handleLoadClick} className="p-2 hover:bg-white/5 rounded text-slate-400 hover:text-cyan-400" title="Open Project">
                        <FolderOpen size={16} />
                    </button>
                </div>

                {/* Time display */}
                <div className="text-sm font-mono text-white/80 bg-black/30 px-3 py-1 rounded">
                    {formatTime(state.playhead)}
                </div>
            </div>

            {/* Main Content */}
            <div className="flex flex-1 overflow-hidden">
                {/* Timeline Area */}
                <div className="flex-1 flex flex-col">
                    {/* Edit Toolbar */}
                    <div className="h-10 bg-[#0f0f0f] border-b border-white/5 px-4 flex items-center gap-2">
                        {/* Transport */}
                        <div className="flex items-center gap-1 mr-4">
                            <button
                                onClick={handleStop}
                                className="p-2 hover:bg-white/5 rounded text-slate-400 hover:text-white"
                            >
                                <SkipBack size={16} />
                            </button>
                            <button
                                onClick={isPlaying ? handlePause : handlePlay}
                                className="p-2 hover:bg-white/5 rounded text-slate-400 hover:text-white"
                            >
                                {isPlaying ? <Pause size={16} /> : <Play size={16} />}
                            </button>
                        </div>

                        <div className="w-px h-6 bg-white/10" />

                        {/* Edit tools */}
                        <button
                            onClick={handleSplit}
                            className="p-2 hover:bg-white/5 rounded text-slate-400 hover:text-white"
                            title="Split at playhead (S)"
                        >
                            <Scissors size={16} />
                        </button>
                        <button
                            onClick={handleCopy}
                            className="p-2 hover:bg-white/5 rounded text-slate-400 hover:text-white"
                            title="Copy to palette (C)"
                        >
                            <Copy size={16} />
                        </button>
                        <button
                            onClick={handleDelete}
                            className="p-2 hover:bg-white/5 rounded text-slate-400 hover:text-red-400"
                            title="Delete selected (Del)"
                        >
                            <Trash2 size={16} />
                        </button>

                        <div className="w-px h-6 bg-white/10" />

                        {/* Snap toggle */}
                        <button
                            onClick={handleToggleSnap}
                            className={`p-2 rounded transition-all ${state.snapEnabled
                                ? 'bg-cyan-500/20 text-cyan-400'
                                : 'hover:bg-white/5 text-slate-500'
                                }`}
                            title="Snap to grid (Q)"
                        >
                            <Magnet size={16} />
                        </button>

                        {/* Snap division */}
                        {state.snapEnabled && (
                            <select
                                value={state.snapDivision}
                                onChange={(e) => setState(prev =>
                                    setSnapDivision(prev, e.target.value)
                                )}
                                className="bg-black/30 text-xs text-slate-300 border border-white/10 rounded px-2 py-1"
                            >
                                <option value="1/1">1 Bar</option>
                                <option value="1/2">1/2</option>
                                <option value="1/4">1/4</option>
                                <option value="1/8">1/8</option>
                                <option value="1/16">1/16</option>
                            </select>
                        )}

                        <div className="flex-1" />

                        {/* Zoom */}
                        <button
                            onClick={handleZoomOut}
                            className="p-2 hover:bg-white/5 rounded text-slate-400 hover:text-white"
                        >
                            <ZoomOut size={16} />
                        </button>
                        <div className="text-xs text-slate-500 w-12 text-center">
                            {state.zoom}x
                        </div>
                        <button
                            onClick={handleZoomIn}
                            className="p-2 hover:bg-white/5 rounded text-slate-400 hover:text-white"
                        >
                            <ZoomIn size={16} />
                        </button>

                        <div className="w-px h-6 bg-white/10" />

                        {/* Undo/Redo */}
                        <button
                            onClick={handleUndo}
                            disabled={state.historyIndex < 0}
                            className="p-2 hover:bg-white/5 rounded text-slate-400 hover:text-white disabled:opacity-30"
                        >
                            <Undo2 size={16} />
                        </button>
                        <button
                            onClick={handleRedo}
                            disabled={state.historyIndex >= state.history.length - 1}
                            className="p-2 hover:bg-white/5 rounded text-slate-400 hover:text-white disabled:opacity-30"
                        >
                            <Redo2 size={16} />
                        </button>

                        <div className="w-px h-6 bg-white/10" />

                        {/* Render */}
                        <button
                            onClick={handleRender}
                            className="flex items-center gap-2 px-4 py-1.5 bg-gradient-to-r from-cyan-600 to-blue-600 rounded-lg text-sm font-bold hover:from-cyan-500 hover:to-blue-500 transition-all"
                        >
                            <Download size={14} />
                            Render
                        </button>
                    </div>

                    {/* Timeline Canvas */}
                    <div className="flex-1 overflow-hidden">
                        <TimelineCanvas
                            state={state}
                            onRegionSelect={handleRegionSelect}
                            onRegionMove={handleRegionMove}
                            onRegionResize={handleRegionResize}
                            onRegionSplit={handleSplit}
                            onSelectionChange={handleSelectionChange}
                            onPlayheadChange={handlePlayheadChange}
                            onZoomChange={handleZoomChange}
                        />
                    </div>
                </div>

                {/* Palette Sidebar */}
                <div className="w-36 border-l border-white/5 bg-[#0f0f0f]">
                    <Palette
                        slots={state.paletteSlots}
                        onSlotDrop={handlePaletteSlotDrop}
                        onSlotDragStart={handlePaletteDragStart}
                        onSlotClear={handlePaletteSlotClear}
                    />
                </div>
            </div>
        </div >
    );
};

export default NonDestructiveEditor;
