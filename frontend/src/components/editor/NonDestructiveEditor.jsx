/**
 * NonDestructiveEditor - Main component for the non-destructive audio editor
 *
 * Slim container: owns TimelineState + composes child components and hooks.
 *
 * Splits:
 * - useEditorPlayback   : audio loading, playback engine, render/export
 * - useEditorPersistence: .rbep save/list/load
 * - useEditorRegions    : region/palette/marker/zoom/snap/grid handlers
 * - useEditorKeyboard   : global hotkeys (markers, split, copy, delete, ...)
 * - EditorToolbar       : top/edit toolbars (transport, edit tools, render)
 * - TimelineCanvas      : waveform + regions + cursor
 * - Palette             : clip storage sidebar
 */

import React, { useState } from 'react';
import { Loader2, FolderOpen, X } from 'lucide-react';

import TimelineCanvas from './TimelineCanvas';
import Palette from './Palette';
import EditorToolbar from './EditorToolbar';
import useEditorPlayback from './useEditorPlayback';
import useEditorPersistence from './useEditorPersistence';
import useEditorRegions from './useEditorRegions';
import useEditorKeyboard from './useEditorKeyboard';

import { createTimelineState } from '../../audio/TimelineState';

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
    const [state, setState] = useState(() =>
        createTimelineState({ bpm, beatGrid, phrases, zoom: 50 })
    );

    // Playback / audio engine (owns refs + loading + transport + render)
    const {
        audioContextRef,
        sourceBufferRef,
        isLoading,
        setIsLoading,
        isPlaying,
        isRendering,
        renderProgress,
        handlePlay,
        handlePause,
        handleStop,
        handlePlayheadChange,
        handleRender,
    } = useEditorPlayback({
        sourceUrl,
        sourcePath,
        state,
        setState,
        track,
        onRenderComplete,
    });

    // Project persistence (.rbep save / list / load)
    const {
        showLoadModal,
        setShowLoadModal,
        projectList,
        handleSaveProject,
        handleLoadClick,
        loadProject,
    } = useEditorPersistence({
        state,
        setState,
        sourcePath,
        track,
        audioContextRef,
        sourceBufferRef,
        setIsLoading,
    });

    // Region / palette / marker / zoom / grid handlers
    const {
        handleRegionSelect,
        handleRegionMove,
        handleRegionResize,
        handleSplit,
        handleCopy,
        handleDelete,
        handleUndo,
        handleRedo,
        handlePaletteSlotDrop,
        handleTimelineDrop,
        handlePaletteDragStart,
        handlePaletteSlotClear,
        handleZoomIn,
        handleZoomOut,
        handleZoomChange,
        handleToggleSnap,
        handleSelectionChange,
        addMarker,
        handleNormalize,
        handleGridAdjust,
        toggleGridMode,
        handleSaveGrid,
    } = useEditorRegions({
        state,
        setState,
        sourcePath,
        sourceBufferRef,
        track,
    });

    // Keyboard shortcuts
    useEditorKeyboard({
        addMarker,
        handleSplit,
        handleCopy,
        handleDelete,
        handleToggleSnap,
        toggleGridMode,
    });

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

            {/* Top Toolbar (header + edit row) */}
            <EditorToolbar
                state={state}
                setState={setState}
                track={track}
                camelot={camelot}
                loudness={loudness}
                peak={peak}
                isPlaying={isPlaying}
                handlePlay={handlePlay}
                handlePause={handlePause}
                handleStop={handleStop}
                handleSplit={handleSplit}
                handleCopy={handleCopy}
                handleDelete={handleDelete}
                handleToggleSnap={handleToggleSnap}
                toggleGridMode={toggleGridMode}
                handleSaveGrid={handleSaveGrid}
                handleZoomIn={handleZoomIn}
                handleZoomOut={handleZoomOut}
                handleUndo={handleUndo}
                handleRedo={handleRedo}
                handleRender={handleRender}
                handleNormalize={handleNormalize}
                handleSaveProject={handleSaveProject}
                handleLoadClick={handleLoadClick}
                formatTime={formatTime}
            />

            {/* Main Content */}
            <div className="flex flex-1 overflow-hidden">
                {/* Timeline Area */}
                <div className="flex-1 flex flex-col">
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
        </div>
    );
};

export default NonDestructiveEditor;
