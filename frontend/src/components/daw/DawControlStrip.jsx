/**
 * DawControlStrip — Unified control bar below the timeline
 * 
 * Layout: [Transport] | [Edit Tools] | [Hot Cues + Loop Controls]
 * 
 * Merges functionality from DawTransport + DawToolbar edit tools + PerformancePanel
 */

import React, { useCallback, useMemo, useState } from 'react';
import {
    Play, Pause, Square, SkipBack, Repeat,
    Scissors, Trash2, Undo2, Redo2,
    Magnet, Grid3X3,
    ArrowDownToLine, ArrowUpFromLine, X, Plus,
    Activity, BarChart3, Waves,
    Copy, Clipboard, Files,
    ChevronsLeft, ChevronsRight, Minus,
    Download, Crosshair
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
    onExport,
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

    // ── TIME MODE TOGGLE (Elapsed ↔ Remaining) ──
    const [timeMode, setTimeMode] = useState('elapsed'); // 'elapsed' | 'remaining'
    const toggleTimeMode = useCallback(() => setTimeMode(m => m === 'elapsed' ? 'remaining' : 'elapsed'), []);

    // ── ADAPTIVE ZOOM-TO-PLAYHEAD ──
    const handleZoomToPlayhead = useCallback(() => {
        const containerWidth = window.innerWidth * 0.6; // rough estimate of timeline width
        const newScrollX = Math.max(0, state.playhead * state.zoom - containerWidth * 0.5);
        dispatch({ type: 'SET_SCROLL_X', payload: newScrollX });
    }, [state.playhead, state.zoom, dispatch]);


    // ── FORMAT ──
    const formatTime = useCallback((seconds) => {
        if (!seconds || seconds < 0) return '00:00.0';
        const m = Math.floor(seconds / 60);
        const s = seconds % 60;
        return `${m.toString().padStart(2, '0')}:${s.toFixed(1).padStart(4, '0')}`;
    }, []);

    const formatRemaining = useCallback((seconds) => {
        const rem = Math.max(0, (totalDuration || 0) - seconds);
        const m = Math.floor(rem / 60);
        const s = rem % 60;
        return `-${m.toString().padStart(2, '0')}:${s.toFixed(1).padStart(4, '0')}`;
    }, [totalDuration]);

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
        const styles = ['3band', 'mono', 'bass'];
        const nextIdx = (styles.indexOf(waveformStyle) + 1) % styles.length;
        dispatch({ type: 'SET_WAVEFORM_STYLE', payload: styles[nextIdx] });
    }, [waveformStyle, dispatch]);



    return (
        <div className="bg-mx-shell/80 border-t border-white/5 flex flex-col shrink-0 overflow-hidden">

            {/* ── ROW 1 — transport · time / BPM chips ── */}
            <div className="flex items-center gap-3 px-3 py-2 border-b border-white/5">
                {/* Transport */}
                <div className="flex items-center gap-1.5 shrink-0">
                    <TBtn onClick={handleGoToStart} title="Go to Start">
                        <SkipBack size={14} />
                    </TBtn>
                    <button
                        onClick={isPlaying ? onStop : onPlay}
                        className={`w-9 h-9 rounded-full flex items-center justify-center transition-all ${isPlaying
                            ? 'bg-amber2 text-mx-deepest'
                            : 'bg-mx-hover text-white hover:bg-mx-card border border-white/10'
                            }`}
                        style={isPlaying ? { boxShadow: '0 0 12px var(--amber-glow)' } : undefined}
                        title={isPlaying ? 'Pause (Space)' : 'Play (Space)'}
                    >
                        {isPlaying ? <Pause size={16} /> : <Play size={16} fill="currentColor" />}
                    </button>
                    <TBtn onClick={onStop} title="Stop">
                        <Square size={14} />
                    </TBtn>
                    <TBtn onClick={handleLoopToggle} active={loopEnabled} title="Loop">
                        <Repeat size={14} />
                    </TBtn>
                </div>

                {/* Time + BPM — Studio stat chips */}
                <div className="flex items-stretch gap-1.5 shrink-0">
                    <div
                        onClick={toggleTimeMode}
                        title="Click to toggle Elapsed / Remaining"
                        className="flex flex-col items-center justify-center px-3 py-1 bg-mx-card border border-white/10 rounded-sm cursor-pointer select-none min-w-[92px]"
                    >
                        <span className={`text-[13px] font-mono font-bold leading-none ${timeMode === 'remaining' ? 'text-amber2-hover' : 'text-white'}`}>
                            {timeMode === 'remaining' ? formatRemaining(playhead) : formatTime(playhead)}
                        </span>
                        <span className="text-[8px] text-ink-muted font-mono uppercase tracking-wider mt-1">
                            {timeMode === 'remaining' ? 'Remaining' : `Bar ${posInfo.bar} · Beat ${posInfo.beat}`}
                        </span>
                    </div>
                    <div className="flex flex-col items-center justify-center px-2 py-1 bg-mx-card border border-white/10 rounded-sm">
                        <div className="flex items-center gap-1">
                            <button onClick={() => handleAdjustBpm(-0.1)} className="text-ink-placeholder hover:text-white"><Minus size={9} /></button>
                            <span className="text-[13px] font-mono font-bold text-amber2 leading-none">{bpm?.toFixed(1) || '---'}</span>
                            <button onClick={() => handleAdjustBpm(0.1)} className="text-ink-placeholder hover:text-white"><Plus size={9} /></button>
                        </div>
                        <span className="text-[8px] text-ink-muted uppercase tracking-wider mt-1">BPM</span>
                    </div>
                </div>

            </div>

            {/* ── ROW 2 — 16 hot-cue pads (A–P), full width ── */}
            <div className="flex items-stretch gap-1 px-3 py-2 border-b border-white/5">
                {hotCues.map((cue, i) => {
                    const letter = String.fromCharCode(65 + i);
                    if (!cue) {
                        return (
                            <button
                                key={i}
                                onClick={() => handleHotCueClick(i)}
                                className="flex-1 h-9 rounded-sm flex items-center justify-center text-[10px] font-bold font-mono text-ink-placeholder bg-mx-card/60 border border-dashed border-white/10 hover:bg-mx-hover/60 transition-all"
                                title={`Set Hot Cue ${letter}`}
                            >
                                {letter}
                            </button>
                        );
                    }
                    return (
                        <button
                            key={i}
                            onClick={() => handleHotCueClick(i)}
                            onContextMenu={(e) => { e.preventDefault(); handleDeleteHotCue(i, e); }}
                            className="flex-1 h-9 rounded-sm flex flex-col items-center justify-center font-mono leading-none transition-all hover:brightness-110"
                            style={{
                                background: `rgb(${cue.red} ${cue.green} ${cue.blue} / 0.18)`,
                                border: `1px solid rgb(${cue.red} ${cue.green} ${cue.blue} / 0.55)`,
                                color: `rgb(${cue.red},${cue.green},${cue.blue})`,
                                boxShadow: `inset 0 -2px 0 rgb(${cue.red} ${cue.green} ${cue.blue} / 0.4)`,
                            }}
                            title={`${cue.name} — ${formatTime(cue.time)} (Right-click to delete)`}
                        >
                            <span className="text-[8px] font-bold opacity-80">{letter}</span>
                            <span className="text-[9px] font-bold">{formatTime(cue.time)}</span>
                        </button>
                    );
                })}
            </div>

            {/* ── ROW 3 — beat grid · edit tools · snap/zoom · loop · export ── */}
            <div className="flex items-center gap-2 px-3 py-1.5">
                {/* Grid shift */}
                <div className="flex items-center gap-0.5">
                    <TBtn onClick={() => handleShiftGrid(-0.01)} title="Shift Grid Left">
                        <ChevronsLeft size={14} />
                    </TBtn>
                    <span className="text-[8px] text-ink-muted font-bold uppercase tracking-wider px-1 text-center leading-tight">Grid<br />Shift</span>
                    <TBtn onClick={() => handleShiftGrid(0.01)} title="Shift Grid Right">
                        <ChevronsRight size={14} />
                    </TBtn>
                </div>

                <div className="w-px h-5 bg-white/10" />

                {/* Edit tools */}
                <div className="flex items-center gap-0.5">
                    <TBtn onClick={onSplit} title="Split (Ctrl+E)">
                        <Scissors size={14} />
                    </TBtn>
                    <TBtn onClick={onRippleDelete} disabled={!hasSelection} danger title="Delete (Del)">
                        <Trash2 size={14} />
                    </TBtn>
                    <TBtn onClick={handleUndo} disabled={!canUndo} title="Undo (Ctrl+Z)">
                        <Undo2 size={14} />
                    </TBtn>
                    <TBtn onClick={handleRedo} disabled={!canRedo} title="Redo (Ctrl+Shift+Z)">
                        <Redo2 size={14} />
                    </TBtn>
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

                <div className="w-px h-5 bg-white/10" />

                {/* Snap + zoom */}
                <div className="flex items-center gap-1.5">
                    <button
                        onClick={handleSnapToggle}
                        className={`flex items-center gap-1 h-7 px-2 rounded-sm border text-[10px] font-bold uppercase tracking-wider transition-all ${snapEnabled
                            ? 'bg-amber2/15 text-amber2 border-amber2/40'
                            : 'bg-mx-card text-ink-muted border-white/10'
                            }`}
                        title="Toggle Snap"
                    >
                        <Magnet size={10} />
                        Q
                    </button>
                    <select
                        value={snapDivision}
                        onChange={handleDivisionChange}
                        className="h-7 bg-mx-card border border-white/10 text-[10px] text-ink-primary rounded-sm px-1.5 appearance-none cursor-pointer focus:outline-none"
                    >
                        <option value="1/1">Bar</option>
                        <option value="1/2">1/2</option>
                        <option value="1/4">Beat</option>
                        <option value="1/8">1/8</option>
                        <option value="1/16">1/16</option>
                    </select>
                    <Grid3X3 size={12} className="text-ink-muted" />
                    <input
                        type="range" min="10" max="2000" value={zoom}
                        onChange={handleZoomChange}
                        className="w-20 h-1 bg-mx-hover rounded-full appearance-none cursor-pointer accent-amber2"
                    />
                    <span className="text-[9px] text-ink-muted font-mono w-7">{Math.round(zoom)}</span>
                    <TBtn
                        onClick={handleWaveformCycle}
                        title={`Waveform: ${waveformStyle === '3band' ? '3-Band (Rekordbox)' : waveformStyle === 'bass' ? 'Bass Only' : 'Mono'}`}
                        active={waveformStyle !== '3band'}
                    >
                        {waveformStyle === '3band' ? <BarChart3 size={13} /> : waveformStyle === 'bass' ? <Waves size={13} /> : <Activity size={13} />}
                    </TBtn>
                </div>

                <div className="w-px h-5 bg-white/10" />

                {/* Loop */}
                <div className="flex items-center gap-0.5">
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

                <div className="flex-1" />

                {/* Right — zoom-to-playhead + export */}
                <TBtn onClick={handleZoomToPlayhead} title="Center view on playhead">
                    <Crosshair size={13} />
                </TBtn>
                {onExport && (
                    <button
                        onClick={onExport}
                        title="Export Project"
                        className="flex items-center gap-1.5 h-7 px-3 rounded-sm bg-amber2/15 border border-amber2/40 text-amber2 text-[10px] font-bold font-mono uppercase tracking-wider transition-all hover:bg-amber2/25"
                    >
                        <Download size={11} />
                        Export
                    </button>
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
        className={`h-7 w-7 flex items-center justify-center rounded-sm border transition-colors ${disabled
            ? 'text-ink-placeholder cursor-not-allowed opacity-40 border-white/5'
            : active
                ? 'bg-amber2/15 border-amber2/50 text-amber2'
                : danger
                    ? 'bg-mx-card border-white/10 text-ink-secondary hover:text-bad hover:border-bad/40'
                    : 'bg-mx-card border-white/10 text-ink-secondary hover:text-white hover:border-white/20'
            }`}
        title={title}
    >
        {children}
    </button>
));

DawControlStrip.displayName = 'DawControlStrip';
TBtn.displayName = 'TBtn';

export default DawControlStrip;
