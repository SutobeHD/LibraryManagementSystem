/**
 * CuePanel — hot-cue pad grid + memory-cue list + color picker + comment input.
 *
 * Surface-agnostic: reads from the useTrackEditorState hook. Mounted in
 * WaveformEditor and DjEditDaw behind FEATURE_CUE_PANEL.
 *
 * Slice 1 of waveform-editor-extensions. See
 * docs/research/implement/inprogress_waveform-editor-extensions.md.
 */

import { useCallback, useEffect, useState } from 'react';
import { Plus, RotateCcw, Save, Trash2 } from 'lucide-react';
import api from '../../../api/api';
import { useToast } from '../../ToastContext';
import { log } from '../../../utils/log';
import useTrackEditorState from '../state/useTrackEditorState';
import { CDJ_MEMORY_COLORS, HOT_CUE_SURFACE_COLORS } from '../../../config/constants';

export default function CuePanel({ track, currentTime = 0, onAudition = null }) {
    const toast = useToast();
    const {
        state,
        loadCues,
        setHotCue,
        deleteHotCue,
        setMemoryCue,
        deleteMemoryCue,
        updateMemoryCueFields,
        undo,
        canUndo,
    } = useTrackEditorState();

    const { hotCues, cues } = state;
    const [activeColorEdit, setActiveColorEdit] = useState(null);
    const [isSaving, setIsSaving] = useState(false);

    useEffect(() => {
        if (!track?.id) return;
        let cancelled = false;
        (async () => {
            try {
                const resp = await api.get(`/api/track/${track.id}/cues`);
                if (cancelled) return;
                const all = Array.isArray(resp.data) ? resp.data : resp.data?.cues || [];
                const hot = [];
                const mem = [];
                for (const c of all) {
                    const norm = normaliseCue(c);
                    if (norm.type === 'hot_cue') hot.push(norm);
                    else mem.push(norm);
                }
                loadCues({ hotCues: hot, cues: mem });
            } catch (err) {
                log.warn('[CuePanel] failed to load cues', err);
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [track?.id, loadCues]);

    const handleSave = useCallback(async () => {
        if (!track?.id) return;
        setIsSaving(true);
        try {
            const payload = [
                ...hotCues.map((c) => ({ ...c, type: 'hot_cue' })),
                ...cues.map((c) => ({ ...c, type: 'memory_cue' })),
            ];
            await api.post('/api/track/cues/save', { track_id: track.id, cues: payload });
            toast.success(`Saved ${payload.length} cues`);
        } catch (err) {
            log.error('[CuePanel] save failed', err);
            toast.error('Failed to save cues');
        } finally {
            setIsSaving(false);
        }
    }, [track?.id, hotCues, cues, toast]);

    const handleHotPadClick = (slot) => {
        const existing = hotCues.find((c) => c.number === slot);
        if (existing) {
            // Slice 5: click on an occupied pad auditions the cue. The
            // trash icon (top-right of the pad) still deletes.
            if (typeof onAudition === 'function') {
                onAudition(existing.time_ms);
            }
            return;
        }
        setHotCue({
            number: slot,
            type: 'hot_cue',
            time_ms: Math.round((currentTime || 0) * 1000),
            color_id: 1,
            color_rgb: hexToRgb(HOT_CUE_SURFACE_COLORS[0].hex),
            name: '',
            status: 0,
        });
    };

    return (
        <div className="bg-[#1a1a1a] border border-white/5 rounded-lg p-3 my-2">
            <div className="flex items-center justify-between mb-3">
                <h3 className="text-[11px] font-bold tracking-wider text-amber2">CUES</h3>
                <div className="flex gap-2">
                    <button
                        onClick={undo}
                        disabled={!canUndo}
                        title="Undo last change (up to 3 steps; persists across reload)"
                        className="flex items-center gap-1 px-2 py-1 bg-white/5 border border-white/10 text-[10px] text-ink-muted hover:text-white rounded disabled:opacity-30 disabled:cursor-not-allowed"
                    >
                        <RotateCcw size={10} /> UNDO
                    </button>
                    <button
                        onClick={handleSave}
                        disabled={isSaving}
                        className="flex items-center gap-1.5 px-3 py-1 bg-amber2/20 border border-amber2/30 text-amber2 text-[10px] font-bold rounded hover:bg-amber2/30 disabled:opacity-50"
                    >
                        <Save size={12} />
                        {isSaving ? 'SAVING...' : 'SAVE'}
                    </button>
                </div>
            </div>

            {/* Hot-cue 8-pad grid */}
            <div className="grid grid-cols-8 gap-1.5 mb-3">
                {Array.from({ length: 8 }, (_, i) => i + 1).map((slot) => {
                    const cue = hotCues.find((c) => c.number === slot);
                    const colorHex = cue
                        ? HOT_CUE_SURFACE_COLORS.find((c) => c.id === cue.color_id)?.hex ||
                          HOT_CUE_SURFACE_COLORS[0].hex
                        : null;
                    return (
                        <button
                            key={slot}
                            onClick={() => handleHotPadClick(slot)}
                            className="h-16 rounded flex flex-col items-center justify-center gap-0.5 text-[10px] font-bold border border-white/10 transition-all hover:border-white/30 hover:scale-[1.02] relative overflow-hidden"
                            style={{
                                backgroundColor: cue ? colorHex : '#1f1f1f',
                                color: cue ? '#000' : '#666',
                            }}
                            title={
                                cue
                                    ? `Hot cue ${String.fromCharCode(64 + slot)} @ ${formatTime(cue.time_ms / 1000)} — click to audition`
                                    : `Set hot cue ${String.fromCharCode(64 + slot)} at ${formatTime(currentTime)}`
                            }
                        >
                            <span className="text-[15px] leading-none">
                                {String.fromCharCode(64 + slot)}
                            </span>
                            {cue && (
                                <span className="text-[8px] font-mono opacity-70 leading-none">
                                    {formatTime(cue.time_ms / 1000)}
                                </span>
                            )}
                            {cue && (
                                <span
                                    onClick={(e) => {
                                        e.stopPropagation();
                                        deleteHotCue(slot);
                                    }}
                                    className="absolute top-0 right-0 p-0.5 text-black/60 hover:text-black"
                                >
                                    <Trash2 size={10} />
                                </span>
                            )}
                        </button>
                    );
                })}
            </div>

            {/* Memory-cue list */}
            <div>
                <div className="flex items-center justify-between mb-2">
                    <span className="text-[10px] font-bold text-ink-muted">MEMORY CUES</span>
                    <button
                        onClick={() =>
                            setMemoryCue({
                                id: `mem-${Date.now()}`,
                                type: 'memory_cue',
                                time_ms: Math.round((currentTime || 0) * 1000),
                                color_id: 5,
                                color_rgb: hexToRgb(CDJ_MEMORY_COLORS[4].hex),
                                name: '',
                                status: 0,
                            })
                        }
                        className="flex items-center gap-1 px-2 py-0.5 bg-white/5 border border-white/10 text-[9px] text-ink-muted hover:text-white rounded"
                    >
                        <Plus size={10} /> ADD AT {formatTime(currentTime)}
                    </button>
                </div>

                <div className="space-y-1 max-h-40 overflow-y-auto">
                    {cues.length === 0 && (
                        <div className="text-[10px] text-ink-muted text-center py-2">
                            No memory cues yet
                        </div>
                    )}
                    {cues.map((cue) => {
                        const colorHex =
                            CDJ_MEMORY_COLORS.find((c) => c.id === cue.color_id)?.hex ||
                            CDJ_MEMORY_COLORS[4].hex;
                        return (
                            <div
                                key={cue.id}
                                className="flex items-center gap-2 px-2 py-1 bg-[#1f1f1f] border border-white/5 rounded"
                            >
                                <div
                                    className="w-3 h-3 rounded-sm cursor-pointer flex-shrink-0"
                                    style={{ backgroundColor: colorHex }}
                                    onClick={() =>
                                        setActiveColorEdit(activeColorEdit === cue.id ? null : cue.id)
                                    }
                                    title="Click to change color"
                                />
                                <span className="text-[10px] font-mono text-ink-secondary w-14 flex-shrink-0">
                                    {formatTime(cue.time_ms / 1000)}
                                </span>
                                <input
                                    type="text"
                                    value={cue.name || ''}
                                    onChange={(e) =>
                                        updateMemoryCueFields(cue.id, { name: e.target.value })
                                    }
                                    placeholder="Comment..."
                                    className="flex-1 bg-transparent text-[10px] text-white outline-none border-b border-transparent focus:border-amber2/50"
                                />
                                <button
                                    onClick={() => deleteMemoryCue(cue.id)}
                                    className="text-ink-muted hover:text-red-400"
                                >
                                    <Trash2 size={10} />
                                </button>
                            </div>
                        );
                    })}
                </div>

                {activeColorEdit && (
                    <div className="mt-2 p-2 bg-[#0f0f0f] border border-white/10 rounded">
                        <div className="text-[9px] text-ink-muted mb-1.5">CDJ COLOR</div>
                        <div className="flex gap-1">
                            {CDJ_MEMORY_COLORS.map((c) => (
                                <button
                                    key={c.id}
                                    onClick={() => {
                                        updateMemoryCueFields(activeColorEdit, {
                                            color_id: c.id,
                                            color_rgb: hexToRgb(c.hex),
                                        });
                                        setActiveColorEdit(null);
                                    }}
                                    className="w-6 h-6 rounded border border-white/10 hover:border-white/30 transition-all"
                                    style={{ backgroundColor: c.hex }}
                                    title={c.name}
                                />
                            ))}
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
}

// --- helpers -------------------------------------------------------------

function normaliseCue(c) {
    // Accept backend shape {ID, Type, InMsec, Num, Comment} (rbox-loaded)
    // OR new shape {id, type, time_ms, ...} (sidecar / new writes).
    if (c.ID !== undefined) {
        return {
            id: String(c.ID),
            type: c.Num > 0 ? 'hot_cue' : 'memory_cue',
            number: c.Num || 0,
            time_ms: c.InMsec || 0,
            name: c.Comment || '',
            color_id: 0,
            color_rgb: [0, 0, 0],
            status: c.Type === 4 ? 4 : 0,
        };
    }
    return {
        id: c.id || `cue-${Date.now()}-${Math.random()}`,
        type: c.type || 'memory_cue',
        number: c.number || 0,
        time_ms: c.time_ms || 0,
        name: c.name || '',
        color_id: c.color_id || 0,
        color_rgb: c.color_rgb || [0, 0, 0],
        status: c.status || 0,
    };
}

function hexToRgb(hex) {
    const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex);
    return m ? [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)] : [0, 0, 0];
}

function formatTime(seconds) {
    if (!isFinite(seconds)) return '0:00';
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
}
