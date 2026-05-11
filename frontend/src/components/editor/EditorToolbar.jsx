/**
 * EditorToolbar - Top toolbar + edit toolbar for NonDestructiveEditor.
 *
 * Renders two stacked rows:
 *  1. h-12 header: track info, BPM/Key/LUFS badges, save/load buttons, time
 *  2. h-10 edit row: transport, edit tools, snap, grid mode, zoom, undo/redo, render
 *
 * Pure presentation; all state/handlers come in via props.
 */

import React from 'react';
import {
    Play, Pause, SkipBack, Scissors, Copy, ZoomIn, ZoomOut, Magnet,
    Trash2, Download, Undo2, Redo2, Music, Save, FolderOpen,
} from 'lucide-react';
import { setSnapDivision } from '../../audio/TimelineState';

const EditorToolbar = ({
    // State for read-only display
    state,
    setState,
    track,
    camelot,
    loudness,
    peak,
    // Transport
    isPlaying,
    handlePlay,
    handlePause,
    handleStop,
    // Edit ops
    handleSplit,
    handleCopy,
    handleDelete,
    handleToggleSnap,
    toggleGridMode,
    handleSaveGrid,
    handleZoomIn,
    handleZoomOut,
    handleUndo,
    handleRedo,
    handleRender,
    handleNormalize,
    // Persistence
    handleSaveProject,
    handleLoadClick,
    // Time formatter
    formatTime,
}) => {
    return (
        <>
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
        </>
    );
};

export default EditorToolbar;
