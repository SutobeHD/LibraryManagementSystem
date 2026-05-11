import React from 'react';
import {
    Play, Pause, SkipBack, Scissors, Plus, Trash2, Download,
    ChevronLeft, ChevronRight,
    Disc, ScanLine, Loader2,
    RotateCcw, RotateCw, Clipboard, ListPlus, Save, Infinity, X, Target, Zap, Layers,
    Volume2, VolumeX,
} from 'lucide-react';
import { HOT_CUE_COLORS } from './useWaveformInteractions';

// Top toolbars — header, project select, hot-cue strip, transport, volume, viz toggle,
// grid shift, drop detection, metadata bar. Plus the render-progress overlay.
// Owns no state — orchestrator passes everything in.
export default function WaveformControls({
    fullTrack,
    showBrowser,
    setShowBrowser,
    isQuantized,
    setIsQuantized,
    selectedProject,
    setSelectedProject,
    projectList,
    hotCues,
    handleSetHotCue,
    handleJumpHotCue,
    handleDeleteHotCue,
    jumpToCue,
    formatTime,
    wavesurfer,
    isPlaying,
    internalVolume,
    setInternalVolume,
    visualMode,
    handleToggleVisualMode,
    handleGridShift,
    handleSaveGrid,
    handleDetectDrop,
    currentTime,
    duration,
    bpm,
    isRendering,
    renderProgress,
}) {
    return (
        <>
            {isRendering && (
                <div className="absolute inset-0 z-[100] flex flex-col items-center justify-center bg-black/90 backdrop-blur-md animate-fade-in">
                    <div className="w-80 p-8 glass-panel border border-amber2/20 rounded-2xl flex flex-col items-center">
                        <Loader2 size={48} className="text-amber2 animate-spin mb-6" />
                        <h3 className="text-xl font-bold text-white mb-2">Rendering Audio</h3>
                        <p className="text-ink-secondary text-sm mb-6">Processing insertion and effects...</p>

                        <div className="w-full h-2 bg-white/5 rounded-full overflow-hidden mb-2">
                            <div
                                className="h-full bg-gradient-to-r from-amber2 to-amber2-press transition-all duration-300"
                                style={{ width: `${renderProgress}%` }}
                            />
                        </div>
                        <div className="text-[10px] font-mono text-amber2 tracking-widest">{renderProgress}% COMPLETE</div>
                    </div>
                </div>
            )}
            {/* Top Toolbar - Purely for Project status now */}
            <div className="rb-header">
                <div className="flex items-center gap-6">
                    <div className="flex items-center gap-3">
                        <span className="text-ink-muted font-bold tracking-tight">RB EDITOR PRO</span>
                    </div>
                    <div className="bg-[#1a1a1a] h-6 px-4 flex items-center rounded border border-white/5 font-bold text-amber2 text-[10px]">
                        EDIT MODE
                    </div>
                </div>
                <div className="flex items-center gap-4">
                    <button
                        onClick={() => setShowBrowser(!showBrowser)}
                        className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border text-[10px] font-bold transition-all ${showBrowser ? 'bg-amber2/20 border-amber2/30 text-amber2' : 'bg-[#1a1a1a] border-white/5 text-ink-muted'}`}
                    >
                        <ListPlus size={14} /> BROWSER
                    </button>
                    <button
                        onClick={() => setIsQuantized(prev => !prev)}
                        className={`flex items-center gap-2 text-[10px] font-mono transition-colors ${isQuantized ? 'text-amber2' : 'text-ink-muted hover:text-ink-secondary'}`}
                        title={`Beat snap is ${isQuantized ? 'ON' : 'OFF'} — click to toggle (Q)`}
                    >
                        <ScanLine size={12} />
                        <span>GRID LOCK: {isQuantized ? 'ON' : 'OFF'}</span>
                    </button>
                </div>
            </div>

            {/* Sub-Header / Project Bar */}
            <div className="h-10 bg-[#111] border-b border-white/5 px-4 flex items-center justify-between flex-shrink-0">
                <div className="flex items-center gap-4">
                    <select
                        value={selectedProject}
                        onChange={(e) => setSelectedProject(e.target.value)}
                        className="bg-[#050505] text-ink-primary font-bold outline-none text-xs border border-white/5 rounded px-2 py-1 max-w-[150px]"
                    >
                        <option value="">New Project</option>
                        {projectList.map(p => <option key={p.path} value={p.path}>{p.name}.prj</option>)}
                    </select>
                </div>
                <div className="flex items-center gap-4">
                    {/* Rekordbox-style hot-cue strip: always shows all 8 slots */}
                    <div className="flex items-center gap-1 mr-2 bg-black/40 px-1.5 py-1 rounded border border-white/5">
                        {[1, 2, 3, 4, 5, 6, 7, 8].map(num => {
                            const cue = hotCues.find(c => c.HotCueNum === num);
                            const letter = String.fromCharCode(64 + num);
                            const color = HOT_CUE_COLORS[num - 1];
                            return (
                                <button
                                    key={num}
                                    onClick={() => cue ? jumpToCue(cue.InPoint) : handleSetHotCue(num)}
                                    onContextMenu={(e) => {
                                        e.preventDefault();
                                        if (cue) handleDeleteHotCue(num);
                                        else handleSetHotCue(num);
                                    }}
                                    title={cue
                                        ? `Hot Cue ${letter} @ ${formatTime(cue.InPoint)} • Click to jump • Right-click to delete • Shift+${num} to overwrite`
                                        : `Empty slot ${letter} • Click or Shift+${num} to set at current time`}
                                    className={`relative w-7 h-7 rounded flex flex-col items-center justify-center font-bold text-[10px] transition-all hover:scale-105 ${cue ? 'text-white shadow-md' : 'bg-white/5 text-white/30 border border-white/10 hover:bg-white/10 hover:text-white/60'}`}
                                    style={cue ? { backgroundColor: color, boxShadow: `0 0 8px ${color}40` } : {}}
                                >
                                    <span className="leading-none">{letter}</span>
                                    {cue && (
                                        <span className="text-[7px] font-mono opacity-80 leading-none mt-0.5">{Math.floor(cue.InPoint / 60)}:{(Math.floor(cue.InPoint % 60)).toString().padStart(2, '0')}</span>
                                    )}
                                </button>
                            );
                        })}
                    </div>

                    <div className="flex items-center bg-[#050505] px-2 py-1 rounded border border-white/5 gap-2">
                        <button onClick={() => wavesurfer.current?.stop()} className="rb-transport-btn" title="Stop"><SkipBack size={12} /></button>
                        <button onClick={() => wavesurfer.current?.playPause()} className="rb-transport-btn" title="Play / Pause (Space)">
                            {isPlaying ? <Pause size={14} className="text-orange-500" /> : <Play size={14} />}
                        </button>
                    </div>

                    {/* Volume Slider */}
                    <div className="flex items-center bg-[#050505] h-8 px-2 rounded border border-white/5 gap-2" title={`Volume: ${Math.round(internalVolume * 100)}%`}>
                        <button
                            onClick={() => setInternalVolume(prev => prev > 0 ? 0 : 0.8)}
                            className="text-ink-muted hover:text-white transition-colors"
                            title={internalVolume > 0 ? 'Mute' : 'Unmute'}
                        >
                            {internalVolume > 0 ? <Volume2 size={14} /> : <VolumeX size={14} className="text-orange-500" />}
                        </button>
                        <input
                            type="range"
                            min="0"
                            max="1"
                            step="0.01"
                            value={internalVolume}
                            onChange={(e) => setInternalVolume(parseFloat(e.target.value))}
                            className="w-20 h-1 accent-amber2 cursor-pointer"
                        />
                        <span className="text-[9px] font-mono text-ink-muted w-6 text-right">{Math.round(internalVolume * 100)}</span>
                    </div>

                    <div onClick={handleToggleVisualMode} className={`flex items-center h-8 px-3 rounded border border-white/5 gap-2 cursor-pointer transition-all ${visualMode !== 'blue' ? 'bg-indigo-500/20 border-indigo-500/30' : 'bg-black'}`}>
                        <Layers size={12} className={visualMode !== 'blue' ? 'text-indigo-400' : 'text-ink-muted'} />
                        <span className={`text-[10px] uppercase font-bold ${visualMode !== 'blue' ? 'text-indigo-400' : 'text-ink-muted'}`}>{visualMode}</span>
                    </div>

                    <div onClick={() => setIsQuantized(!isQuantized)} className={`flex items-center h-8 px-3 rounded border border-white/5 gap-2 cursor-pointer transition-all ${isQuantized ? 'bg-amber2/10 border-amber2/30' : 'bg-black'}`}>
                        <RotateCcw size={12} className={isQuantized ? 'text-amber2' : 'text-orange-500'} />
                        <span className={`text-[10px] uppercase font-bold ${isQuantized ? 'text-amber2' : 'text-ink-muted'}`}>Q : {isQuantized ? 'ON' : 'AUTO'}</span>
                    </div>

                    <div className="flex items-center gap-1 bg-[#050505] px-2 py-1 rounded border border-white/5">
                        <span className="text-[9px] text-ink-muted font-bold mr-2">GRID</span>
                        <button onClick={() => handleGridShift(-0.01)} className="p-1 hover:bg-white/5 rounded text-ink-secondary hover:text-white" title="-10ms"><ChevronLeft size={12} /></button>
                        <button onClick={() => handleSaveGrid()} className="p-1 hover:bg-white/5 rounded text-amber2 hover:text-amber2" title="Save Grid"><Save size={12} /></button>
                        <button onClick={() => handleGridShift(0.01)} className="p-1 hover:bg-white/5 rounded text-ink-secondary hover:text-white" title="+10ms"><ChevronRight size={12} /></button>
                    </div>

                    <button
                        onClick={handleDetectDrop}
                        className="flex items-center h-8 px-3 rounded border border-red-500/30 bg-red-500/10 gap-2 cursor-pointer transition-all hover:bg-red-500/20"
                        title="Detect Drop (Re-analyze)"
                    >
                        <Zap size={12} className="text-red-400" />
                        <span className="text-[10px] uppercase font-bold text-red-400">DROP</span>
                    </button>
                </div>
            </div>

            {/* Metadata Bar */}
            <div className="h-12 flex items-center justify-between px-6 bg-black border-b border-white/5">
                <div className="flex items-center gap-4">
                    <div className="rb-metadata-value !text-amber2 bg-amber2/20 px-2 rounded border border-amber2/20 uppercase">
                        {visualMode} MODE
                    </div>
                    <div className="flex items-center gap-4">
                        <div className="w-8 h-8 bg-amber2/20 flex items-center justify-center rounded border border-amber2/20">
                            <Disc size={20} className="text-amber2" />
                        </div>
                        <div>
                            <div className="text-sm font-bold truncate max-w-[200px]">{fullTrack?.Title || 'No Track'}</div>
                            <div className="text-[10px] text-ink-muted truncate">{fullTrack?.Artist || 'Unknown Artist'}</div>
                        </div>
                    </div>
                </div>
                <div className="rb-metadata-box">
                    <span>TIME <span className="rb-metadata-value">{fullTrack ? `${formatTime(currentTime)} / ${formatTime(duration)}` : '--:--.--'}</span></span>
                    <span>KEY <span className="rb-metadata-value">{fullTrack?.Key || '—'}</span></span>
                    <span>BPM <span className="rb-metadata-value">{fullTrack && bpm ? bpm.toFixed(2) : '—'}</span></span>
                </div>
            </div>
        </>
    );
}

// Bottom-panel cluster: Loops, Beat Select, Hot Cues, Edit Tools. Rendered after the canvas.
export function WaveformBottomPanels({
    isLooping,
    loopIn,
    loopOut,
    setLoopIn,
    setLoopOut,
    setIsLooping,
    handleSetLoopIn,
    handleSetLoopOut,
    selectedBeats,
    setSelectedBeats,
    bpm,
    hotCues,
    handleSetHotCue,
    handleJumpHotCue,
    handleDeleteHotCue,
    handleSaveCues,
    handleCopy,
    handlePaste,
    handleInsert,
    handleDelete,
    handleClear,
    handleUndo,
    handleRedo,
    handleRender,
    formatTime,
    cuts,
    history,
    historyIdx,
}) {
    return (
        <div className="flex bg-[#0a0a0a] border-t border-white/5 h-80 overflow-hidden">
            {/* Column 1: Loops & Beat Select */}
            <div className="w-1/2 border-r border-white/5 flex flex-col p-2 bg-[#050505]">
                {/* Loops Top */}
                <div className="flex-1 border-b border-white/5 p-2 flex flex-col">
                    <div className="rb-panel-title !bg-transparent !p-0 mb-3 flex items-center justify-between">
                        <span className="flex items-center gap-2">
                            <Infinity size={12} className={isLooping ? 'text-green-400 animate-pulse' : 'text-amber-500'} /> Loops
                        </span>
                        {loopIn !== null && loopOut !== null && (
                            <span className="text-[9px] font-mono text-amber-400">
                                {formatTime(loopOut - loopIn)} {isLooping ? '• ACTIVE' : '• PAUSED'}
                            </span>
                        )}
                    </div>
                    <div className="flex gap-2">
                        <button
                            onClick={handleSetLoopIn}
                            title="Set loop in point at current time (L)"
                            className={`flex-1 h-12 border font-bold rounded flex flex-col items-center justify-center gap-0.5 text-xs transition-colors ${loopIn !== null ? 'bg-amber-500/20 border-amber-500/50 text-amber-400' : 'bg-mx-card/40 hover:bg-mx-hover/40 border-amber-500/30 text-amber-500'}`}
                        >
                            <span>LOOP IN</span>
                            {loopIn !== null && <span className="text-[9px] font-mono opacity-80">{formatTime(loopIn)}</span>}
                        </button>
                        <button
                            onClick={handleSetLoopOut}
                            title="Set loop out point at current time (L)"
                            className={`flex-1 h-12 border font-bold rounded flex flex-col items-center justify-center gap-0.5 text-xs transition-colors ${loopOut !== null ? 'bg-amber-500/20 border-amber-500/50 text-amber-400' : 'bg-mx-card/40 hover:bg-mx-hover/40 border-amber-500/30 text-amber-500'}`}
                        >
                            <span>LOOP OUT</span>
                            {loopOut !== null && <span className="text-[9px] font-mono opacity-80">{formatTime(loopOut)}</span>}
                        </button>
                        <button
                            onClick={() => { setLoopIn(null); setLoopOut(null); setIsLooping(false); }}
                            disabled={loopIn === null && loopOut === null}
                            title="Clear loop (Shift+L)"
                            className="w-12 h-12 bg-mx-card/20 border border-white/5 text-ink-muted rounded flex items-center justify-center disabled:opacity-30 hover:bg-mx-card/40"
                        >
                            <X size={14} />
                        </button>
                    </div>
                </div>
                {/* Beat Select Bottom */}
                <div className="flex-1 p-2 flex flex-col">
                    <div className="rb-panel-title !bg-transparent !p-0 mb-3 flex items-center justify-between">
                        <span>Beat Select</span>
                        {bpm > 0 && (
                            <span className="text-[9px] font-mono text-ink-muted">
                                {(selectedBeats * 60 / bpm).toFixed(2)}s @ {bpm.toFixed(0)} BPM
                            </span>
                        )}
                    </div>
                    <div className="grid grid-cols-4 gap-1.5 overflow-y-auto">
                        {[1, 2, 4, 8, 16, 32, 64, 128].map(b => {
                            const seconds = bpm > 0 ? (b * 60 / bpm).toFixed(2) : '—';
                            return (
                                <button
                                    key={b}
                                    onClick={() => setSelectedBeats(b)}
                                    title={`Select ${b} beat${b === 1 ? '' : 's'} (${seconds}s @ ${bpm.toFixed(0)} BPM)`}
                                    className={`h-9 text-[11px] font-bold border rounded transition-all ${selectedBeats === b ? 'bg-amber2/20 border-amber2 text-amber2' : 'bg-[#1a1a1a] border-white/5 text-ink-muted hover:border-white/15'}`}
                                >
                                    {b} BEAT
                                </button>
                            );
                        })}
                    </div>
                </div>
            </div>

            {/* Column 2: Hot Cues & Edit Actions */}
            <div className="w-1/2 flex flex-col p-2 bg-[#050505]">
                {/* Hot Cues Top */}
                <div className="flex-1 border-b border-white/5 p-2 flex flex-col overflow-hidden">
                    <div className="rb-panel-title !bg-transparent !p-0 mb-3 flex items-center gap-2">
                        <Target size={12} className="text-orange-400" /> Hot Cues
                    </div>
                    <div className="grid grid-cols-4 gap-2 flex-1 overflow-y-auto pr-1">
                        {[1, 2, 3, 4, 5, 6, 7, 8].map(num => {
                            const cue = hotCues.find(c => c.HotCueNum === num);
                            return (
                                <button
                                    key={num}
                                    onClick={() => cue ? handleJumpHotCue(num) : handleSetHotCue(num)}
                                    onContextMenu={(e) => {
                                        e.preventDefault();
                                        if (cue) handleDeleteHotCue(num);
                                        else handleSetHotCue(num);
                                    }}
                                    title={cue ? `Jump to ${formatTime(cue.InPoint)} • Right-click to delete • Shift+${num} to overwrite` : `Set Hot Cue ${String.fromCharCode(64 + num)} (Shift+${num})`}
                                    className={`h-16 rounded border-2 flex flex-col items-center justify-center font-bold transition-all relative group ${cue
                                        ? 'text-white border-white/20 cursor-pointer'
                                        : 'bg-mx-card/30 border-white/5 text-ink-placeholder'
                                        }`}
                                    style={cue ? { backgroundColor: HOT_CUE_COLORS[num - 1] } : {}}
                                >
                                    <span className="text-xl">{(String.fromCharCode(64 + num))}</span>
                                    {cue && (
                                        <div className="absolute top-1 right-1">
                                            <Target size={10} className="text-white/50" />
                                        </div>
                                    )}
                                    {cue && (
                                        <span className="absolute bottom-0.5 left-1/2 -translate-x-1/2 text-[8px] font-mono opacity-70">{formatTime(cue.InPoint)}</span>
                                    )}
                                    {!cue && <Plus size={12} className="opacity-0 group-hover:opacity-100 transition-opacity" />}
                                </button>
                            );
                        })}
                    </div>
                    <button onClick={handleSaveCues} className="mt-2 h-7 bg-amber2/20 border border-amber2/30 text-amber2 text-[10px] font-bold rounded flex items-center justify-center gap-2">
                        <Save size={12} /> SAVE TO XML
                    </button>
                </div>

                {/* Edit Actions Bottom */}
                <div className="flex-1 p-2 flex flex-col justify-end">
                    <div className="rb-panel-title !bg-transparent !p-0 mb-3 text-ink-secondary uppercase tracking-tighter">Edit Tools</div>
                    <div className="grid grid-cols-4 gap-2">
                        <button onClick={handleCopy} className="rb-tool-btn !py-2" title="Copy selection (Ctrl+C)"><Clipboard size={14} />COPY</button>
                        <button onClick={handlePaste} className="rb-tool-btn !py-2" title="Paste at cursor (Ctrl+V)"><Clipboard size={14} />PASTE</button>
                        <button onClick={handleInsert} className="rb-tool-btn !py-2" title="Insert silence (I)"><ListPlus size={14} />INSERT</button>
                        <button onClick={handleDelete} className="rb-tool-btn !py-2" title="Delete selection (Del)"><Trash2 size={14} />DELETE</button>
                        <button onClick={handleClear} className="rb-tool-btn !py-2 text-orange-400" title="Clear all edits"><Scissors size={14} />CLEAR</button>
                        <button onClick={handleUndo} disabled={historyIdx < 0} className="rb-tool-btn !py-2 disabled:opacity-20" title="Undo (Ctrl+Z)"><RotateCcw size={14} />UNDO</button>
                        <button onClick={handleRedo} disabled={historyIdx >= history.length - 1} className="rb-tool-btn !py-2 disabled:opacity-20" title="Redo (Ctrl+Shift+Z)"><RotateCw size={14} />REDO</button>
                        <button onClick={() => handleRender(cuts)} className="rb-tool-btn !py-2 text-amber2 border-amber2/10" title="Export edited audio (Ctrl+E)"><Download size={14} />EXPORT</button>
                    </div>
                </div>
            </div>
        </div>
    );
}
