/**
 * DawToolbar — Top toolbar for the DJ Edit DAW
 * 
 * Displays: Project name, save/open/export buttons, editing tools, undo/redo.
 */

import React, { useCallback } from 'react';
import { Save, FolderOpen, Download, Scissors, Trash2, Undo2, Redo2, FileAudio, Hash, Palette, Activity, Zap } from 'lucide-react';
import { COLOR_PRESETS, DEFAULT_COLOR_PRESET } from './timeline/useTimelineRender';

// Render-mode options surfaced in the toolbar. The keys match the
// strings consumed by `useTimelineRender.js:buildWaveformBitmap`.
const WAVEFORM_STYLE_OPTIONS = [
    { id: '3band',  label: '3-Band envelope' },
    { id: 'liquid', label: 'Liquid (smooth bezier per band)' },
    { id: 'mono',   label: 'Mono silhouette' },
    { id: 'bass',   label: 'Bass only' },
];

const DawToolbar = React.memo(({
    state, dispatch,
    onSave, onOpen, onExport, onSplit, onRippleDelete, onAutoCue,
    colorPreset, onSelectColorPreset,
    waveformStyle, onSelectWaveformStyle,
    forceMaxDetail, onToggleMaxDetail,
}) => {
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

    const activeColorPreset = colorPreset || DEFAULT_COLOR_PRESET;
    const activeWaveformStyle = waveformStyle || '3band';

    return (
        <div className="h-11 bg-mx-shell/60 border-b border-white/5 flex items-center px-4 gap-3 shrink-0 backdrop-blur-xl">
            {/* Style-preset selector — switches the band colours of the
                3-band waveform and the down-beat colour. Drives
                state.colorPreset → useTimelineRender's bitmap rebuild. */}
            {typeof onSelectColorPreset === 'function' && (
                <div className="flex items-center gap-1.5 mr-1" title="Waveform colour preset">
                    <Palette size={12} className="text-ink-muted" />
                    <select
                        value={activeColorPreset}
                        onChange={(e) => onSelectColorPreset(e.target.value)}
                        className="h-7 px-2 rounded border border-white/5 bg-mx-card text-ink-secondary hover:text-white text-[10px] uppercase font-bold cursor-pointer focus:outline-none focus:ring-1 focus:ring-amber2/40"
                    >
                        {Object.entries(COLOR_PRESETS).map(([id, preset]) => (
                            <option key={id} value={id}>{preset.label}</option>
                        ))}
                    </select>
                </div>
            )}

            {/* Render-mode selector — controls which drawing strategy the
                offscreen-canvas bitmap builder uses. Independent from
                colour preset. */}
            {typeof onSelectWaveformStyle === 'function' && (
                <div className="flex items-center gap-1.5 mr-1" title="Render mode (drawing strategy)">
                    <Activity size={12} className="text-ink-muted" />
                    <select
                        value={activeWaveformStyle}
                        onChange={(e) => onSelectWaveformStyle(e.target.value)}
                        className="h-7 px-2 rounded border border-white/5 bg-mx-card text-ink-secondary hover:text-white text-[10px] uppercase font-bold cursor-pointer focus:outline-none focus:ring-1 focus:ring-amber2/40"
                    >
                        {WAVEFORM_STYLE_OPTIONS.map(opt => (
                            <option key={opt.id} value={opt.id}>{opt.label}</option>
                        ))}
                    </select>
                </div>
            )}

            {/* HD-detail toggle — pins LOD to 1 (max sampling density).
                CPU heavier but pixel-accurate. */}
            {typeof onToggleMaxDetail === 'function' && (
                <button
                    onClick={onToggleMaxDetail}
                    title={forceMaxDetail
                        ? 'HD detail ON — LOD pinned to 1 (full sampling density). Click to disable.'
                        : 'HD detail OFF — adaptive LOD (saves CPU). Click to force max detail.'}
                    className={`h-7 px-2 mr-2 rounded border text-[10px] uppercase font-bold flex items-center gap-1 transition-all ${
                        forceMaxDetail
                            ? 'bg-amber2/20 border-amber2/40 text-amber2'
                            : 'bg-mx-card border-white/5 text-ink-muted hover:text-white'
                    }`}
                >
                    <Zap size={12} /> HD
                </button>
            )}

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

            {/* Global Info */}
            <div className="flex items-center gap-4 mr-6">
                <div className="flex flex-col">
                    <span className="text-[10px] text-ink-muted uppercase tracking-widest font-bold">BPM</span>
                    <span className="text-xs text-amber2 font-mono font-bold leading-none">{bpm?.toFixed(1) || '---'}</span>
                </div>
                <div className="flex flex-col">
                    <span className="text-[10px] text-ink-muted uppercase tracking-widest font-bold">Quantize</span>
                    <span className={`text-xs font-bold leading-none ${snapEnabled ? 'text-amber2' : 'text-ink-placeholder'}`}>
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
        className={`p-2 rounded-lg transition-all text-xs ${disabled
            ? 'text-ink-placeholder cursor-not-allowed opacity-50'
            : danger
                ? 'text-ink-secondary hover:text-red-400 hover:bg-red-500/10'
                : accent
                    ? 'text-amber2 hover:bg-amber2/15'
                    : 'text-ink-secondary hover:text-white hover:bg-white/5'
            }`}
        title={label}
    >
        {icon}
    </button>
));

DawToolbar.displayName = 'DawToolbar';
ToolBtn.displayName = 'ToolBtn';

export default DawToolbar;
