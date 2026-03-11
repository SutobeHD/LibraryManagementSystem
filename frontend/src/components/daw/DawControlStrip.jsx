/**
 * DawControlStrip — Unified control bar below the timeline
 * 
 * Layout: [Transport] | [Edit Tools] | [Hot Cues + Loop Controls]
 * 
 * Merges functionality from DawTransport + DawToolbar edit tools + PerformancePanel
 */

import React, { useCallback, useMemo } from 'react';
import {
    Play, Pause, Square, SkipBack, Repeat,
    Scissors, Trash2, Undo2, Redo2,
    Magnet, Grid3X3,
    ArrowDownToLine, ArrowUpFromLine, X, Plus,
    Activity, BarChart3, Waves,
    Copy, Clipboard, Files,
    ChevronsLeft, ChevronsRight, Minus
} from 'lucide-react';
import { getPositionInfo, HOT_CUE_COLORS, snapToGrid } from '../../audio/DawState';

const DawControlStrip = React.memo(({
    state,
    dispatch,
    onPlay,
    onStop,
    onSplit,
    onRippleDelete,
    onJumpTo,
}) => {
    const {
        isPlaying, playhead, bpm, totalDuration, zoom,
        snapEnabled, snapDivision, slipMode, loopEnabled,
        hotCues, loops, activeLoopIndex,
        undoStack, redoStack, selectedRegionIds, waveformStyle, clipboard,
        gridOffsetSec
    } = state;
    const firstBeatSec = ((state.tempoMap?.[0]?.positionMs || 0) / 1000) + (gridOffsetSec || 0);

    const hasSelection = selectedRegionIds && selectedRegionIds.size > 0;
    const canUndo = undoStack.length > 0;
    const canRedo = redoStack.length > 0;

    console.log('ControlStrip Render:', {
        selectedCount: selectedRegionIds?.size,
        hasSelection,
        clipboardLen: clipboard?.length
    });

    // ── FORMAT ──
    const formatTime = useCallback((seconds) => {
        if (!seconds || seconds < 0) return '00:00.0';
        const m = Math.floor(seconds / 60);
        const s = seconds % 60;
        return `${m.toString().padStart(2, '0')}:${s.toFixed(1).padStart(4, '0')}`;
    }, []);

    const posInfo = useMemo(() => getPositionInfo(playhead, bpm), [playhead, bpm]);

    // ── TRANSPORT ──
    const handleGoToStart = useCallback(() => {
        dispatch({ type: 'SET_PLAYHEAD', payload: 0 });
    }, [dispatch]);

    const handleLoopToggle = useCallback(() => {
        dispatch({ type: 'TOGGLE_LOOP' });
    }, [dispatch]);

    // ── SNAP ──
    const handleSnapToggle = useCallback(() => {
        dispatch({ type: 'TOGGLE_SNAP' });
    }, [dispatch]);

    const handleDivisionChange = useCallback((e) => {
        dispatch({ type: 'SET_SNAP_DIVISION', payload: e.target.value });
    }, [dispatch]);

    const handleZoomChange = useCallback((e) => {
        dispatch({ type: 'SET_ZOOM', payload: parseFloat(e.target.value) });
    }, [dispatch]);

    // ── UNDO/REDO ──
    const handleUndo = useCallback(() => dispatch({ type: 'UNDO' }), [dispatch]);
    const handleRedo = useCallback(() => dispatch({ type: 'REDO' }), [dispatch]);

    // ── HOT CUES ──
    const handleHotCueClick = useCallback((index) => {
        const cue = hotCues[index];
        if (cue) {
            onJumpTo?.(cue.time);
        } else {
            let time = playhead;
            if (snapEnabled) time = snapToGrid(time, bpm, snapDivision, firstBeatSec);
            dispatch({
                type: 'SET_HOT_CUE',
                payload: {
                    index,
                    cue: {
                        name: String.fromCharCode(65 + index),
                        time,
                        red: HOT_CUE_COLORS[index].red,
                        green: HOT_CUE_COLORS[index].green,
                        blue: HOT_CUE_COLORS[index].blue,
                    },
                },
            });
        }
    }, [hotCues, playhead, bpm, snapEnabled, snapDivision, firstBeatSec, dispatch, onJumpTo]);

    const handleDeleteHotCue = useCallback((index, e) => {
        e.stopPropagation();
        dispatch({ type: 'PUSH_UNDO', payload: `Delete Hot Cue ${String.fromCharCode(65 + index)}` });
        dispatch({ type: 'DELETE_HOT_CUE', payload: index });
    }, [dispatch]);

    // ── LOOP ──
    const handleLoopIn = useCallback(() => {
        let time = playhead;
        if (snapEnabled) time = snapToGrid(time, bpm, snapDivision, firstBeatSec);
        dispatch({ type: 'PUSH_UNDO', payload: 'Set Loop In' });
        if (loops.length === 0 || loops[loops.length - 1].endTime != null) {
            dispatch({
                type: 'ADD_LOOP',
                payload: { name: `Loop ${loops.length + 1}`, startTime: time, endTime: null, active: false, red: 251, green: 146, blue: 60 },
            });
        } else {
            dispatch({ type: 'UPDATE_LOOP', payload: { index: loops.length - 1, updates: { startTime: time } } });
        }
    }, [playhead, bpm, snapEnabled, snapDivision, firstBeatSec, loops, dispatch]);

    const handleLoopOut = useCallback(() => {
        let time = playhead;
        if (snapEnabled) time = snapToGrid(time, bpm, snapDivision, firstBeatSec);
        if (loops.length > 0) {
            const lastLoop = loops[loops.length - 1];
            if (lastLoop.endTime == null && time > lastLoop.startTime) {
                dispatch({ type: 'UPDATE_LOOP', payload: { index: loops.length - 1, updates: { endTime: time, active: true } } });
                dispatch({ type: 'SET_ACTIVE_LOOP', payload: loops.length - 1 });
            }
        }
    }, [playhead, bpm, snapEnabled, snapDivision, firstBeatSec, loops, dispatch]);

    const handleShiftGrid = useCallback((delta) => {
        dispatch({ type: 'SHIFT_GRID', payload: delta });
    }, [dispatch]);

    const handleAdjustBpm = useCallback((delta) => {
        dispatch({ type: 'ADJUST_BPM', payload: delta });
    }, [dispatch]);

    const handleWaveformCycle = useCallback(() => {
        const styles = ['detail', 'liquid', 'bass'];
        const nextIdx = (styles.indexOf(waveformStyle) + 1) % styles.length;
        dispatch({ type: 'SET_WAVEFORM_STYLE', payload: styles[nextIdx] });
    }, [waveformStyle, dispatch]);



    return (
        <div className="bg-slate-900/80 border-t border-white/5 flex items-center shrink-0 backdrop-blur-xl overflow-hidden">
            {/* ── TRANSPORT ── */}
            <div className="flex items-center gap-0.5 px-3 py-1.5 border-r border-white/5">
                <TBtn onClick={handleGoToStart} title="Go to Start">
                    <SkipBack size={14} />
                </TBtn>
                <button
                    onClick={isPlaying ? onStop : onPlay}
                    className={`p-2 rounded-lg transition-all ${isPlaying
                        ? 'bg-cyan-500/20 text-cyan-400 hover:bg-cyan-500/30'
                        : 'bg-white/5 text-white hover:bg-white/10'
                        }`}
                    title={isPlaying ? 'Pause (Space)' : 'Play (Space)'}
                >
                    {isPlaying ? <Pause size={16} /> : <Play size={16} />}
                </button>
                <TBtn onClick={onStop} title="Stop">
                    <Square size={14} />
                </TBtn>
                <TBtn onClick={handleLoopToggle} active={loopEnabled} title="Loop">
                    <Repeat size={14} />
                </TBtn>
            </div>

            {/* ── TIME ── */}
            <div className="flex items-center gap-3 px-3 border-r border-white/5">
                <div className="flex flex-col items-center min-w-[80px]">
                    <span className="text-sm font-mono font-bold text-white tracking-tight leading-none">
                        {formatTime(playhead)}
                    </span>
                    <span className="text-[8px] text-slate-500 font-mono uppercase tracking-wider">
                        Bar {posInfo.bar} · Beat {posInfo.beat}
                    </span>
                </div>
                <div className="flex flex-col items-center">
                    <div className="flex items-center gap-1">
                        <button onClick={() => handleAdjustBpm(-0.1)} className="text-[10px] text-slate-600 hover:text-white"><Minus size={10} /></button>
                        <span className="text-xs font-mono font-bold text-cyan-400 leading-none">
                            {bpm?.toFixed(1) || '---'}
                        </span>
                        <button onClick={() => handleAdjustBpm(0.1)} className="text-[10px] text-slate-600 hover:text-white"><Plus size={10} /></button>
                    </div>
                    <span className="text-[8px] text-slate-500 uppercase tracking-wider">BPM</span>
                </div>
            </div>

            {/* ── GRID EDIT ── */}
            <div className="flex items-center gap-0.5 px-3 border-r border-white/5">
                <TBtn onClick={() => handleShiftGrid(-0.01)} title="Shift Grid Left">
                    <ChevronsLeft size={14} />
                </TBtn>
                <span className="text-[8px] text-slate-500 font-bold uppercase w-8 text-center leading-tight">Grid<br />Shift</span>
                <TBtn onClick={() => handleShiftGrid(0.01)} title="Shift Grid Right">
                    <ChevronsRight size={14} />
                </TBtn>
            </div>

            {/* ── EDIT TOOLS ── */}
            <div className="flex items-center gap-0.5 px-3 border-r border-white/5">
                <TBtn onClick={onSplit} title="Split (Ctrl+E)">
                    <Scissors size={14} />
                </TBtn>
                <TBtn onClick={onRippleDelete} disabled={!hasSelection} danger title="Delete (Del)">
                    <Trash2 size={14} />
                </TBtn>
                <div className="w-px h-4 bg-white/10 mx-1" />
                <TBtn onClick={handleUndo} disabled={!canUndo} title="Undo (Ctrl+Z)">
                    <Undo2 size={14} />
                </TBtn>
                <TBtn onClick={handleRedo} disabled={!canRedo} title="Redo (Ctrl+Shift+Z)">
                    <Redo2 size={14} />
                </TBtn>
                <div className="w-px h-4 bg-white/10 mx-1" />
                <TBtn onClick={() => dispatch({ type: 'COPY_SELECTION' })} disabled={!hasSelection} title="Copy (Ctrl+C)">
                    <Copy size={14} />
                </TBtn>
                <TBtn onClick={() => dispatch({ type: 'PASTE_INSERT' })} disabled={state.clipboard?.length === 0} title="Paste Insert (Ctrl+V)">
                    <Clipboard size={14} />
                </TBtn>
                <TBtn onClick={() => dispatch({ type: 'DUPLICATE_SELECTION' })} disabled={!hasSelection} title="Duplicate (Ctrl+D)">
                    <Files size={14} />
                </TBtn>
            </div>

            {/* ── SNAP + ZOOM ── */}
            <div className="flex items-center gap-1.5 px-3 border-r border-white/5">
                <button
                    onClick={handleSnapToggle}
                    className={`flex items-center gap-1 px-2 py-1 rounded text-[10px] font-bold uppercase tracking-wider transition-all ${snapEnabled
                        ? 'bg-cyan-500/15 text-cyan-400 border border-cyan-500/30'
                        : 'bg-white/5 text-slate-500 border border-white/5'
                        }`}
                    title="Toggle Snap"
                >
                    <Magnet size={10} />
                    Q
                </button>
                <select
                    value={snapDivision}
                    onChange={handleDivisionChange}
                    className="bg-slate-800 border border-white/10 text-[10px] text-slate-300 rounded px-1.5 py-1 appearance-none cursor-pointer focus:outline-none"
                >
                    <option value="1/1">Bar</option>
                    <option value="1/2">1/2</option>
                    <option value="1/4">Beat</option>
                    <option value="1/8">1/8</option>
                    <option value="1/16">1/16</option>
                </select>
                <div className="w-px h-4 bg-white/10 mx-0.5" />
                <Grid3X3 size={12} className="text-slate-500" />
                <input
                    type="range" min="10" max="2000" value={zoom}
                    onChange={handleZoomChange}
                    className="w-16 h-1 bg-slate-700 rounded-full appearance-none cursor-pointer accent-cyan-500"
                />
                <span className="text-[9px] text-slate-500 font-mono w-6">{Math.round(zoom)}</span>

                <div className="w-px h-4 bg-white/10 mx-0.5" />
                <TBtn
                    onClick={handleWaveformCycle}
                    title={`Waveform Style: ${waveformStyle === 'liquid' ? 'Smooth' : waveformStyle === 'bass' ? 'Bass Only' : 'Bars'}`}
                    active={waveformStyle !== 'detail'}
                >
                    {waveformStyle === 'liquid' ? <Activity size={13} /> : waveformStyle === 'bass' ? <Waves size={13} /> : <BarChart3 size={13} />}
                </TBtn>
            </div>

            {/* ── HOT CUES (A-H) ── */}
            <div className="flex items-center gap-0.5 px-2 border-r border-white/5">
                {hotCues.map((cue, i) => (
                    <button
                        key={i}
                        onClick={() => handleHotCueClick(i)}
                        onContextMenu={(e) => { e.preventDefault(); if (cue) handleDeleteHotCue(i, e); }}
                        className={`relative w-7 h-7 rounded text-[10px] font-bold transition-all ${cue
                            ? 'text-slate-900 shadow-sm hover:brightness-110'
                            : 'bg-slate-800/60 text-slate-600 hover:bg-slate-700/60 border border-white/5'
                            }`}
                        style={cue ? { backgroundColor: `rgb(${cue.red},${cue.green},${cue.blue})` } : undefined}
                        title={cue ? `${cue.name} — ${formatTime(cue.time)} (Right-click to delete)` : `Set Hot Cue ${String.fromCharCode(65 + i)}`}
                    >
                        {String.fromCharCode(65 + i)}
                    </button>
                ))}
            </div>

            {/* ── LOOP CONTROLS ── */}
            <div className="flex items-center gap-0.5 px-2">
                <TBtn onClick={handleLoopIn} title="Loop In">
                    <ArrowDownToLine size={13} />
                </TBtn>
                <TBtn onClick={handleLoopOut} title="Loop Out">
                    <ArrowUpFromLine size={13} />
                </TBtn>
                {loops.length > 0 && activeLoopIndex >= 0 && (
                    <TBtn onClick={() => dispatch({ type: 'REMOVE_LOOP', payload: activeLoopIndex })} danger title="Delete Loop">
                        <X size={13} />
                    </TBtn>
                )}
            </div>
        </div>
    );
});

// Small transport-style button
const TBtn = React.memo(({ onClick, children, disabled, active, danger, title }) => (
    <button
        onClick={onClick}
        disabled={disabled}
        className={`p-1.5 rounded-lg transition-colors text-xs ${disabled
            ? 'text-slate-700 cursor-not-allowed opacity-50'
            : active
                ? 'text-amber-400 bg-amber-500/10'
                : danger
                    ? 'text-slate-400 hover:text-red-400 hover:bg-red-500/10'
                    : 'text-slate-400 hover:text-white hover:bg-white/5'
            }`}
        title={title}
    >
        {children}
    </button>
));

DawControlStrip.displayName = 'DawControlStrip';
TBtn.displayName = 'TBtn';

export default DawControlStrip;
