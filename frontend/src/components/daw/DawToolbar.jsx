/**
 * DawToolbar — Top toolbar for the DJ Edit DAW
 * 
 * Displays: Project name, save/open/export buttons, editing tools, undo/redo.
 */

import React, { useCallback } from 'react';
import { Save, FolderOpen, Download, Scissors, Trash2, Undo2, Redo2, FileAudio, Hash } from 'lucide-react';

const DawToolbar = React.memo(({ state, dispatch, onSave, onOpen, onExport, onSplit, onRippleDelete, onAutoCue }) => {
    const isDirty = state.project.dirty;
    const bpm = state.bpm;
    const snapEnabled = state.snapEnabled;

    const [isEditingName, setIsEditingName] = React.useState(false);
    const [tempName, setTempName] = React.useState(state.project.name || 'Untitled Project');

    const handleNameDoubleClick = useCallback(() => {
        setTempName(state.project.name || 'Untitled Project');
        setIsEditingName(true);
    }, [state.project.name]);

    const handleNameChange = useCallback((e) => {
        setTempName(e.target.value);
    }, []);

    const handleNameBlur = useCallback(() => {
        setIsEditingName(false);
        if (tempName.trim() !== state.project.name) {
            dispatch({
                type: 'SET_PROJECT',
                payload: { name: tempName.trim() || 'Untitled Project', dirty: true }
            });
        }
    }, [tempName, state.project.name, dispatch]);

    const handleNameKeyDown = useCallback((e) => {
        if (e.key === 'Enter') handleNameBlur();
        if (e.key === 'Escape') {
            setTempName(state.project.name || 'Untitled Project');
            setIsEditingName(false);
        }
    }, [handleNameBlur, state.project.name]);

    return (
        <div className="h-11 bg-mx-shell/60 border-b border-white/5 flex items-center px-4 gap-3 shrink-0 backdrop-blur-xl">
            {/* Project info */}
            <div className="flex items-center gap-2 min-w-0 mr-4">
                <FileAudio size={14} className="text-amber2 shrink-0" />
                {isEditingName ? (
                    <input
                        type="text"
                        value={tempName}
                        onChange={handleNameChange}
                        onBlur={handleNameBlur}
                        onKeyDown={handleNameKeyDown}
                        autoFocus
                        className="bg-mx-card text-sm font-semibold text-white px-1 py-0.5 rounded border border-amber2/50 focus:outline-none min-w-[200px]"
                    />
                ) : (
                    <span
                        className="text-sm font-semibold text-white truncate max-w-[300px] cursor-text hover:text-amber2-hover transition-colors"
                        onDoubleClick={handleNameDoubleClick}
                        title="Double-click to rename"
                    >
                        {state.project.name || 'Untitled Project'}
                    </span>
                )}
                {isDirty && (
                    <span className="w-2 h-2 rounded-full bg-amber-400 shrink-0 animate-pulse" title="Unsaved changes" />
                )}
            </div>

            {/* Global Info — Studio stat chips */}
            <div className="flex items-center gap-1.5 mr-4">
                <div className="flex flex-col items-center px-2.5 py-0.5 bg-mx-card border border-white/10 rounded-sm">
                    <span className="text-[8px] text-ink-muted uppercase tracking-[0.12em] font-bold">BPM</span>
                    <span className="text-[13px] text-amber2 font-mono font-bold leading-none">{bpm?.toFixed(1) || '---'}</span>
                </div>
                <div className="flex flex-col items-center px-2.5 py-0.5 bg-mx-card border border-white/10 rounded-sm">
                    <span className="text-[8px] text-ink-muted uppercase tracking-[0.12em] font-bold">Quant</span>
                    <span className={`text-[13px] font-mono font-bold leading-none ${snapEnabled ? 'text-amber2' : 'text-ink-placeholder'}`}>
                        {snapEnabled ? 'ON' : 'OFF'}
                    </span>
                </div>
            </div>

            {/* Divider */}
            <div className="w-px h-5 bg-white/10" />

            {/* File operations */}
            <div className="flex items-center gap-1">
                <ToolBtn icon={<FolderOpen size={14} />} label="Open Project (Ctrl+O)" onClick={onOpen} />
                <ToolBtn icon={<Save size={14} />} label="Save Project (Ctrl+S)" onClick={onSave} accent={isDirty} />
                <ToolBtn icon={<Download size={14} />} label="Export Audio" onClick={onExport} />
            </div>

            {/* Divider */}
            <div className="w-px h-5 bg-white/10" />

            {/* Auto Tools */}
            <div className="flex items-center gap-1">
                <ToolBtn icon={<Hash size={14} />} label="Auto-Generate 16-Bar Markers" onClick={onAutoCue} />
            </div>

            {/* Divider */}
            <div className="w-px h-5 bg-white/10" />

            {/* Removed Edit Tools & Undo/Redo (moved to Control Strip) */}

            {/* Spacer */}
            <div className="flex-1 min-w-4" />

            {/* Track info — single-line, capped to 35% of toolbar so it can't
                collapse to "Ti..." but also can't crowd the buttons on narrow
                windows. `flex-shrink min-w-0` lets the inner ellipsis trigger
                instead of truncating the parent's box. */}
            {state.trackMeta.title && (
                <div
                    className="flex items-center text-right min-w-0 shrink"
                    style={{ maxWidth: '35%' }}
                    title={`${state.trackMeta.artist || ''} — ${state.trackMeta.title || ''}`}
                >
                    <div className="truncate text-xs">
                        <span className="text-ink-secondary">
                            {state.trackMeta.artist}
                        </span>
                        <span className="text-ink-placeholder mx-1">—</span>
                        <span className="text-ink-primary font-medium">
                            {state.trackMeta.title}
                        </span>
                    </div>
                </div>
            )}
        </div>
    );
});

const ToolBtn = React.memo(({ icon, label, onClick, disabled, accent, danger }) => (
    <button
        onClick={onClick}
        disabled={disabled}
        className={`h-7 w-7 flex items-center justify-center rounded-sm border transition-all ${disabled
            ? 'text-ink-placeholder cursor-not-allowed opacity-40 border-white/5'
            : danger
                ? 'bg-mx-card border-white/10 text-ink-secondary hover:text-bad hover:border-bad/40'
                : accent
                    ? 'bg-amber2/15 border-amber2/40 text-amber2'
                    : 'bg-mx-card border-white/10 text-ink-secondary hover:text-white hover:border-white/20'
            }`}
        title={label}
    >
        {icon}
    </button>
));

DawToolbar.displayName = 'DawToolbar';
ToolBtn.displayName = 'ToolBtn';

export default DawToolbar;
