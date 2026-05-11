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
import toast from 'react-hot-toast';
import {
    Play, Pause, SkipBack, SkipForward, Scissors, Copy, Clipboard,
    ZoomIn, ZoomOut, Magnet, Trash2, Download, Undo2, Redo2,
    Grid3X3, Volume2, Loader2, Music, ChevronDown, Save, FolderOpen, X
} from 'lucide-react';
import api from '../../api/api';
import { promptModal } from '../PromptModal';
import { log } from '../../utils/log';

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
    shiftGrid,
    adjustBPM,
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
    camelot = '',
    loudness = 0,
    peak = 0,
    beatGrid = [],
    phrases = [],
    onRenderComplete,
    className = ''
}) => {
    const audioContextRef = useRef(null);
    const sourceBufferRef = useRef(null);
    const playerRef = useRef(null);
    const startTimeRef = useRef(0);
    const pauseTimeRef = useRef(0);

    const [state, setState] = useState(() =>
        createTimelineState({ bpm, beatGrid, phrases, zoom: 50 })
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
        const name = await promptModal({
            title: 'Save project',
            message: 'Enter project name:',
            defaultValue: track?.Title || "Untitled Project",
        });
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
            markers: state.markers,
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
            toast.success("Project saved successfully!");
        } catch (error) {
            console.error(error);
            toast.error("Failed to save project.");
        }
    }, [state, sourcePath, track]);

    const handleLoadClick = useCallback(async () => {
        try {
            const res = await api.get('/api/projects/rbep/list');
            setProjectList(res.data || []);
            setShowLoadModal(true);
        } catch (e) { toast.error("Failed to list projects"); }
    }, []);

    const loadProject = async (prjName) => {
        try {
            setIsLoading(true);
            setShowLoadModal(false);
            const res = await api.get(`/api/projects/rbep/${encodeURIComponent(prjName)}`);
            const data = res.data;

            if (!data.tracks || data.tracks.length === 0) {
                toast.error('Project has no tracks');
                setIsLoading(false);
                return;
            }

            const firstTrack = data.tracks[0];
            const trackPath = firstTrack.filepath;

            // 1. Load audio source from the track's filepath
            let buffer = sourceBufferRef.current;
            if (trackPath && trackPath !== sourcePath) {
                const url = `/api/stream?path=${encodeURIComponent(trackPath)}`;
                const ctx = audioContextRef.current || new (window.AudioContext || window.webkitAudioContext)();
                if (!audioContextRef.current) audioContextRef.current = ctx;

                const resp = await fetch(url);
                const ab = await resp.arrayBuffer();
                buffer = await ctx.decodeAudioData(ab);
                sourceBufferRef.current = buffer;
            }

            // 2. Convert RBEP edit data into timeline regions
            const regions = [];
            const edit = firstTrack.edit;
            if (edit && edit.volume && edit.volume.length > 0) {
                edit.volume.forEach((vol, i) => {
                    regions.push(createRegion({
                        sourceBuffer: buffer,
                        sourcePath: trackPath,
                        sourceStart: vol.start,
                        sourceEnd: vol.end,
                        timelineStart: vol.start,
                        name: `Volume ${i + 1}`,
                        color: vol.vol < 1.0 ? '#f59e0b' : '#06b6d4',
                        gain: vol.vol
                    }));
                });
            } else if (firstTrack.position) {
                // Create a single region from position data
                const pos = firstTrack.position;
                regions.push(createRegion({
                    sourceBuffer: buffer,
                    sourcePath: trackPath,
                    sourceStart: pos.songStart || pos.start || 0,
                    sourceEnd: pos.songEnd || pos.end || (buffer?.duration || 0),
                    timelineStart: 0,
                    name: firstTrack.title || data.name,
                    color: '#06b6d4'
                }));
            }

            // 3. Extract beat grid from RBEP
            const rbepBeatGrid = (firstTrack.beatGrid || []).map(b => ({
                index: b.index,
                bpm: b.bpm,
                position: b.position / 1000  // Convert ms to seconds
            }));

            // 4. Set state with loaded project data
            setState(prev => ({
                ...prev,
                regions: regions.length > 0 ? regions : prev.regions,
                markers: data.markers || firstTrack.positionMarks || [],
                bpm: firstTrack.bpm || (edit?.bpm?.[0]?.bpm) || prev.bpm,
                beatGrid: rbepBeatGrid.length > 0 ? rbepBeatGrid : prev.beatGrid,
                zoom: 50,
                snapEnabled: true,
                snapDivision: '1/4',
                playhead: 0,
                history: [],
                historyIndex: -1
            }));

            setIsLoading(false);
        } catch (e) {
            console.error(e);
            toast.error("Failed to load project: " + e.message);
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

    // Handle drop onto timeline from palette
    const handleTimelineDrop = useCallback((regionData, time) => {
        if (!sourceBufferRef.current) return;

        // Create new region from the dropped data + current source buffer
        const newRegion = createRegion({
            sourceBuffer: sourceBufferRef.current,
            sourcePath: sourcePath,
            sourceStart: regionData.sourceStart,
            sourceEnd: regionData.sourceEnd,
            timelineStart: time,
            name: regionData.name,
            color: regionData.color
        });

        setState(prev => {
            const newState = pushHistory(prev, { type: 'add', regionId: newRegion.id });
            return addRegion(newState, newRegion);
        });
    }, [sourcePath]);

    const handlePaletteDragStart = useCallback((slotIndex, region) => {
        // Could track which slot is being dragged
    }, []);

    const handlePaletteSlotClear = useCallback((slotIndex) => {
        setState(prev => setPaletteSlot(prev, slotIndex, null));
    }, []);

    // Zoom handlers
    const handleZoomIn = useCallback(() => {
        setState(prev => setZoom(prev, Math.min(2000, prev.zoom * 1.5)));
    }, []);

    const handleZoomOut = useCallback(() => {
        setState(prev => setZoom(prev, Math.max(10, prev.zoom / 1.5)));
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

    // Marker operations
    const addMarker = useCallback((type, num = -1) => {
        const time = state.playhead;
        const newMarker = {
            Name: type === 4 ? "LOOP" : (num >= 0 ? `HOT CUE ${String.fromCharCode(65 + num)}` : "MEMORY CUE"),
            Type: type,
            Start: time,
            Num: num,
            Red: type === 4 ? 0 : 239,
            Green: type === 4 ? 255 : 68,
            Blue: type === 4 ? 0 : 68
        };

        if (type === 4 && state.selection) {
            newMarker.Start = state.selection.start;
            newMarker.End = state.selection.end;
        }

        setState(prev => ({
            ...prev,
            markers: [...(prev.markers || []), newMarker]
        }));
    }, [state.playhead, state.selection]);

    const handleNormalize = useCallback(() => {
        // Placeholder for normalization logic
        log.debug("Normalize clicked!");
        // This would typically involve analyzing the audio buffer and applying gain
        // to reach a target loudness/peak level.
        // For now, it's just a console log.
    }, []);

    const handleGridAdjust = useCallback((delta) => {
        setState(prev => shiftGrid(prev, delta));
    }, []);

    const toggleGridMode = useCallback(() => {
        const newMode = state.editMode === 'grid' ? 'select' : 'grid';
        setState(prev => ({ ...prev, editMode: newMode }));
    }, [state.editMode]);

    const handleSaveGrid = useCallback(async () => {
        if (!track?.id) return;
        try {
            const response = await fetch('/api/track/grid/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    track_id: track.id,
                    beat_grid: state.beatGrid
                })
            });
            if (response.ok) {
                log.debug("Grid saved successfully");
            }
        } catch (err) {
            console.error("Failed to save grid:", err);
        }
    }, [track?.id, state.beatGrid]);

    // Keyboard shortcuts
    useEffect(() => {
        const handleKeyDown = (e) => {
            if (e.target.tagName === 'INPUT') return;

            switch (e.key.toLowerCase()) {
                case 'm': addMarker(0, -1); break; // Memory Cue
                case 'l': addMarker(4, -1); break; // Loop
                case '1': addMarker(0, 0); break;  // Hot Cue A
                case '2': addMarker(0, 1); break;  // Hot Cue B
                case '3': addMarker(0, 2); break;
                case '4': addMarker(0, 3); break;
                case '5': addMarker(0, 4); break;
                case '6': addMarker(0, 5); break;
                case '7': addMarker(0, 6); break;
                case '8': addMarker(0, 7); break;
                case 'f': addMarker(1, -1); break; // Fade In
                case 'o': addMarker(2, -1); break; // Fade Out
                case 's': handleSplit(); break;
                case 'c': handleCopy(); break;
                case 'delete': handleDelete(); break;
                case 'q': handleToggleSnap(); break;
                case 'g': toggleGridMode(); break; // Toggle Grid Edit Mode
            }
        };

        window.addEventListener('keydown', handleKeyDown);
        return () => window.removeEventListener('keydown', handleKeyDown);
    }, [addMarker, handleSplit, handleCopy, handleDelete, handleToggleSnap, toggleGridMode]);

    // Playhead change
    const handlePlayheadChange = useCallback((time) => {
        pauseTimeRef.current = time;
        setState(prev => ({ ...prev, playhead: time }));

        // Seamless-seek if playing
        if (isPlaying && playerRef.current && audioContextRef.current && sourceBufferRef.current) {
            try {
                // Prevent onended from stopping playback during seek
                playerRef.current.onended = null;
                playerRef.current.stop();
            } catch (e) { /* Ignore if already stopped */ }

            const ctx = audioContextRef.current;
            const source = ctx.createBufferSource();
            source.buffer = sourceBufferRef.current;
            source.connect(ctx.destination);

            source.start(0, time);
            startTimeRef.current = ctx.currentTime - time;
            playerRef.current = source;

            // Restore onended
            source.onended = () => {
                setIsPlaying(false);
                setState(prev => ({ ...prev, isPlaying: false }));
            };
        }
    }, [isPlaying]);

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
                <Loader2 className="w-8 h-8 text-amber2 animate-spin" />
                <span className="ml-3 text-ink-secondary">Loading audio...</span>
            </div>
        );
    }

    return (
        <div className={`flex flex-col h-full bg-[#0a0a0a] text-white ${className}`}>
            {/* Project Browser Modal */}
            {showLoadModal && (
                <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm">
                    <div className="w-96 max-h-[70vh] bg-[#111] rounded-2xl border border-white/10 shadow-2xl flex flex-col">
                        <div className="flex items-center justify-between p-4 border-b border-white/5">
                            <h3 className="text-lg font-bold flex items-center gap-2">
                                <FolderOpen size={18} className="text-amber2" />
                                Open RBEP Project
                            </h3>
                            <button onClick={() => setShowLoadModal(false)} className="p-1 hover:bg-white/10 rounded text-ink-secondary">
                                <X size={16} />
                            </button>
                        </div>
                        <div className="flex-1 overflow-y-auto p-2">
                            {projectList.length === 0 ? (
                                <p className="text-ink-muted text-sm text-center py-8">No .rbep projects found</p>
                            ) : projectList.map(prj => (
                                <button
                                    key={prj.name}
                                    onClick={() => loadProject(prj.name)}
                                    className="w-full text-left p-3 rounded-xl hover:bg-white/5 border border-transparent hover:border-amber2/20 transition-all group"
                                >
                                    <div className="font-bold text-sm text-white group-hover:text-amber2 transition-colors">{prj.name}</div>
                                    <div className="text-[10px] text-ink-muted mt-0.5 flex items-center gap-3">
                                        <span>{(prj.size / 1024).toFixed(1)} KB</span>
                                        <span>·</span>
                                        <span>{new Date(prj.modified * 1000).toLocaleDateString()}</span>
                                    </div>
                                </button>
                            ))}
                        </div>
                    </div>
                </div>
            )}

            {/* Render overlay */}
            {isRendering && (
                <div className="absolute inset-0 z-50 flex items-center justify-center bg-black/90 backdrop-blur-md">
                    <div className="w-80 p-8 rounded-2xl bg-mx-shell/80 border border-amber2/20 flex flex-col items-center">
                        <Loader2 size={48} className="text-amber2 animate-spin mb-6" />
                        <h3 className="text-xl font-bold mb-2">Rendering Audio</h3>
                        <p className="text-ink-secondary text-sm mb-6">Applying edits and effects...</p>
                        <div className="w-full h-2 bg-white/5 rounded-full overflow-hidden mb-2">
                            <div
                                className="h-full bg-gradient-to-r from-amber2 to-amber2-press transition-all duration-300"
                                style={{ width: `${renderProgress}%` }}
                            />
                        </div>
                        <div className="text-xs font-mono text-amber2">{renderProgress}% COMPLETE</div>
                    </div>
                </div>
            )}

            {/* Top Toolbar */}
            <div className="h-12 bg-[#111] border-b border-white/5 px-4 flex items-center justify-between">
                <div className="flex items-center gap-4">
                    {/* Track info */}
                    <div className="flex items-center gap-2">
                        <Music size={14} className="text-amber2" />
                        <span className="text-sm font-bold text-white truncate max-w-[200px]">
                            {track?.Title || 'Untitled'}
                        </span>
                    </div>

                    {/* BPM & Key */}
                    <div className="flex gap-1">
                        <div className="text-xs bg-black/30 px-2 py-1 rounded border border-white/5">
                            <span className="text-ink-muted">BPM</span>
                            <span className="ml-2 text-amber2 font-mono">{state.bpm.toFixed(1)}</span>
                        </div>
                        {camelot && (
                            <div className="text-xs bg-black/30 px-2 py-1 rounded border border-white/5">
                                <span className="text-ink-muted">KEY</span>
                                <span className="ml-2 text-purple-400 font-mono">{camelot}</span>
                            </div>
                        )}
                        {loudness !== 0 && (
                            <div className="text-xs bg-black/30 px-2 py-1 rounded border border-white/5 flex items-center gap-2 group cursor-help" title={`Peak: ${(20 * Math.log10(peak || 1e-6)).toFixed(1)} dBFS`}>
                                <span className="text-ink-muted">LUFS</span>
                                <span className={`font-mono ${loudness > -9 ? 'text-red-400' : 'text-emerald-400'}`}>
                                    {loudness.toFixed(1)}
                                </span>
                                <button
                                    onClick={handleNormalize}
                                    className="ml-1 opacity-0 group-hover:opacity-100 text-[10px] bg-white/10 hover:bg-white/20 px-1 rounded transition-all"
                                >
                                    NORM
                                </button>
                            </div>
                        )}
                    </div>
                </div>

                {/* Project Controls */}
                <div className="flex items-center gap-1 mr-4 border-r border-white/10 pr-4">
                    <button onClick={handleSaveProject} className="p-2 hover:bg-white/5 rounded text-ink-secondary hover:text-green-400" title="Save Project">
                        <Save size={16} />
                    </button>
                    <button onClick={handleLoadClick} className="p-2 hover:bg-white/5 rounded text-ink-secondary hover:text-amber2" title="Open Project">
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
                                className="p-2 hover:bg-white/5 rounded text-ink-secondary hover:text-white"
                            >
                                <SkipBack size={16} />
                            </button>
                            <button
                                onClick={isPlaying ? handlePause : handlePlay}
                                className="p-2 hover:bg-white/5 rounded text-ink-secondary hover:text-white"
                            >
                                {isPlaying ? <Pause size={16} /> : <Play size={16} />}
                            </button>
                        </div>

                        <div className="w-px h-6 bg-white/10" />

                        {/* Edit tools */}
                        <button
                            onClick={handleSplit}
                            className="p-2 hover:bg-white/5 rounded text-ink-secondary hover:text-white"
                            title="Split at playhead (S)"
                        >
                            <Scissors size={16} />
                        </button>
                        <button
                            onClick={handleCopy}
                            className="p-2 hover:bg-white/5 rounded text-ink-secondary hover:text-white"
                            title="Copy to palette (C)"
                        >
                            <Copy size={16} />
                        </button>
                        <button
                            onClick={handleDelete}
                            className="p-2 hover:bg-white/5 rounded text-ink-secondary hover:text-red-400"
                            title="Delete selected (Del)"
                        >
                            <Trash2 size={16} />
                        </button>

                        <div className="w-px h-6 bg-white/10" />

                        {/* Snap toggle */}
                        <button
                            onClick={handleToggleSnap}
                            className={`p-2 rounded transition-all ${state.snapEnabled
                                ? 'bg-amber2/20 text-amber2'
                                : 'hover:bg-white/5 text-ink-muted'
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
                                className="bg-black/30 text-xs text-ink-primary border border-white/10 rounded px-2 py-1"
                            >
                                <option value="1/1">1 Bar</option>
                                <option value="1/2">1/2</option>
                                <option value="1/4">1/4</option>
                                <option value="1/8">1/8</option>
                                <option value="1/16">1/16</option>
                            </select>
                        )}

                        {/* Grid Mode Toggle */}
                        <div className="flex bg-black/20 p-0.5 rounded border border-white/5">
                            <button
                                onClick={toggleGridMode}
                                className={`p-1.5 rounded transition-all ${state.editMode === 'grid' ? 'bg-amber2/20 text-amber2' : 'text-ink-secondary hover:text-white'}`}
                                title="Grid Editing Mode"
                            >
                                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 17V7m0 10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h2a2 2 0 012 2m0 10a2 2 0 002 2h2a2 2 0 002-2V7a2 2 0 00-2-2h-2a2 2 0 00-2 2" />
                                </svg>
                            </button>
                            {state.editMode === 'grid' && (
                                <button
                                    onClick={handleSaveGrid}
                                    className="px-2 text-[10px] font-bold text-amber2 hover:text-white transition-colors"
                                >
                                    SAVE
                                </button>
                            )}
                        </div>
                        <div className="flex-1" />

                        {/* Zoom */}
                        <button
                            onClick={handleZoomOut}
                            className="p-2 hover:bg-white/5 rounded text-ink-secondary hover:text-white"
                        >
                            <ZoomOut size={16} />
                        </button>
                        <div className="text-xs text-ink-muted w-12 text-center">
                            {state.zoom}x
                        </div>
                        <button
                            onClick={handleZoomIn}
                            className="p-2 hover:bg-white/5 rounded text-ink-secondary hover:text-white"
                        >
                            <ZoomIn size={16} />
                        </button>

                        <div className="w-px h-6 bg-white/10" />

                        {/* Undo/Redo */}
                        <button
                            onClick={handleUndo}
                            disabled={state.historyIndex < 0}
                            className="p-2 hover:bg-white/5 rounded text-ink-secondary hover:text-white disabled:opacity-30"
                        >
                            <Undo2 size={16} />
                        </button>
                        <button
                            onClick={handleRedo}
                            disabled={state.historyIndex >= state.history.length - 1}
                            className="p-2 hover:bg-white/5 rounded text-ink-secondary hover:text-white disabled:opacity-30"
                        >
                            <Redo2 size={16} />
                        </button>

                        <div className="w-px h-6 bg-white/10" />

                        {/* Render */}
                        <button
                            onClick={handleRender}
                            className="flex items-center gap-2 px-4 py-1.5 bg-gradient-to-r from-amber2 to-amber2-press rounded-lg text-sm font-bold hover:from-amber2 hover:to-amber2-press transition-all"
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
                            onGridAdjust={handleGridAdjust}
                            onSelectionChange={handleSelectionChange}
                            onPlayheadChange={handlePlayheadChange}
                            onZoomChange={handleZoomChange}
                            onRegionDrop={handleTimelineDrop}
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
