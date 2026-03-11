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
        <div className="h-11 bg-slate-900/60 border-b border-white/5 flex items-center px-4 gap-3 shrink-0 backdrop-blur-xl">
            {/* Project info */}
            <div className="flex items-center gap-2 min-w-0 mr-4">
                <FileAudio size={14} className="text-cyan-400 shrink-0" />
                {isEditingName ? (
                    <input
                        type="text"
                        value={tempName}
                        onChange={handleNameChange}
                        onBlur={handleNameBlur}
                        onKeyDown={handleNameKeyDown}
                        autoFocus
                        className="bg-slate-800 text-sm font-semibold text-white px-1 py-0.5 rounded border border-cyan-500/50 focus:outline-none min-w-[200px]"
                    />
                ) : (
                    <span
                        className="text-sm font-semibold text-white truncate max-w-[300px] cursor-text hover:text-cyan-100 transition-colors"
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

            {/* Global Info */}
            <div className="flex items-center gap-4 mr-6">
                <div className="flex flex-col">
                    <span className="text-[10px] text-slate-500 uppercase tracking-widest font-bold">BPM</span>
                    <span className="text-xs text-cyan-400 font-mono font-bold leading-none">{bpm?.toFixed(1) || '---'}</span>
                </div>
                <div className="flex flex-col">
                    <span className="text-[10px] text-slate-500 uppercase tracking-widest font-bold">Quantize</span>
                    <span className={`text-xs font-bold leading-none ${snapEnabled ? 'text-cyan-400' : 'text-slate-600'}`}>
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
            <div className="flex-1" />

            {/* Track info */}
            {state.trackMeta.title && (
                <div className="flex items-center gap-2 text-right min-w-0">
                    <div className="truncate">
                        <span className="text-xs text-slate-400 truncate">
                            {state.trackMeta.artist}
                        </span>
                        <span className="text-xs text-slate-600 mx-1">—</span>
                        <span className="text-xs text-slate-300 font-medium truncate">
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
        className={`p-2 rounded-lg transition-all text-xs ${disabled
            ? 'text-slate-600 cursor-not-allowed opacity-50'
            : danger
                ? 'text-slate-400 hover:text-red-400 hover:bg-red-500/10'
                : accent
                    ? 'text-cyan-400 hover:bg-cyan-500/15'
                    : 'text-slate-400 hover:text-white hover:bg-white/5'
            }`}
        title={label}
    >
        {icon}
    </button>
));

DawToolbar.displayName = 'DawToolbar';
ToolBtn.displayName = 'ToolBtn';

export default DawToolbar;
