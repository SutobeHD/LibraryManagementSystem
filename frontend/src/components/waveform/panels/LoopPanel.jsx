/**
 * LoopPanel — saved loops with active-loop toggle, numerator/denominator,
 * color, and comment.
 *
 * Surface-agnostic: reads from useTrackEditorState. Mounted in
 * WaveformEditor and DjEditDaw behind FEATURE_LOOP_PANEL.
 *
 * Q5 invariant: exactly one loop per track can be active at a time.
 * The reducer's SET_ACTIVE_LOOP enforces this; setActiveLoop(null)
 * clears all.
 *
 * Slice 2 of waveform-editor-extensions.
 */

import { useCallback, useEffect, useState } from 'react';
import { CheckCircle2, Circle, Plus, Repeat, Save, Trash2 } from 'lucide-react';
import api from '../../../api/api';
import { useToast } from '../../ToastContext';
import { log } from '../../../utils/log';
import useTrackEditorState from '../state/useTrackEditorState';
import { CDJ_MEMORY_COLORS } from '../../../config/constants';

const DEFAULT_LOOP_BEATS = 4;

export default function LoopPanel({ track, currentTime = 0, bpm = 128 }) {
    const toast = useToast();
    const {
        state,
        loadLoops,
        setLoop,
        deleteLoop,
        setActiveLoop,
        updateLoopFields,
    } = useTrackEditorState();

    const { loops } = state;
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
                const loopEntries = all
                    .filter(
                        (c) =>
                            c.loop_len_ms > 0 ||
                            c.type === 'hot_loop' ||
                            c.type === 'memory_loop',
                    )
                    .map(normaliseLoop);
                loadLoops({ loops: loopEntries });
            } catch (err) {
                log.warn('[LoopPanel] failed to load loops', err);
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [track?.id, loadLoops]);

    const handleSave = useCallback(async () => {
        if (!track?.id) return;
        setIsSaving(true);
        try {
            // Merge with existing non-loop cues so we don't clobber them.
            const resp = await api.get(`/api/track/${track.id}/cues`);
            const existing = Array.isArray(resp.data) ? resp.data : resp.data?.cues || [];
            const nonLoops = existing.filter(
                (c) =>
                    !(c.loop_len_ms > 0) &&
                    c.type !== 'hot_loop' &&
                    c.type !== 'memory_loop',
            );
            const loopPayload = loops.map((l) => ({
                ...l,
                type: l.type || (l.number > 0 ? 'hot_loop' : 'memory_loop'),
            }));
            const merged = [...nonLoops, ...loopPayload];
            await api.post('/api/track/cues/save', {
                track_id: track.id,
                cues: merged,
            });
            toast.success(`Saved ${loopPayload.length} loops`);
        } catch (err) {
            log.error('[LoopPanel] save failed', err);
            toast.error('Failed to save loops');
        } finally {
            setIsSaving(false);
        }
    }, [track?.id, loops, toast]);

    const handleAddLoop = () => {
        const startMs = Math.round((currentTime || 0) * 1000);
        const beatMs = (60 / Math.max(60, bpm)) * 1000;
        const lengthMs = Math.round(beatMs * DEFAULT_LOOP_BEATS);
        setLoop({
            id: `loop-${Date.now()}`,
            type: 'memory_loop',
            time_ms: startMs,
            loop_len_ms: lengthMs,
            loop_numerator: DEFAULT_LOOP_BEATS,
            loop_denominator: 1,
            color_id: 5,
            color_rgb: hexToRgb(CDJ_MEMORY_COLORS[4].hex),
            name: '',
            status: 0,
        });
    };

    return (
        <div className="bg-[#1a1a1a] border border-white/5 rounded-lg p-3 my-2">
            <div className="flex items-center justify-between mb-3">
                <h3 className="text-[11px] font-bold tracking-wider text-amber2">LOOPS</h3>
                <div className="flex gap-2">
                    <button
                        onClick={handleAddLoop}
                        className="flex items-center gap-1 px-2 py-1 bg-white/5 border border-white/10 text-[10px] text-ink-muted hover:text-white rounded"
                    >
                        <Plus size={10} /> ADD AT {formatTime(currentTime)}
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

            <div className="space-y-1 max-h-48 overflow-y-auto">
                {loops.length === 0 && (
                    <div className="text-[10px] text-ink-muted text-center py-3">
                        No loops yet
                    </div>
                )}
                {loops.map((loop) => {
                    const colorHex =
                        CDJ_MEMORY_COLORS.find((c) => c.id === loop.color_id)?.hex ||
                        CDJ_MEMORY_COLORS[4].hex;
                    const isActive = loop.status === 4;
                    const lengthBeats =
                        loop.loop_numerator || lengthFromMs(loop.loop_len_ms, bpm);
                    return (
                        <div
                            key={loop.id}
                            className="flex items-center gap-2 px-2 py-1 bg-[#1f1f1f] border border-white/5 rounded"
                        >
                            <button
                                onClick={() => setActiveLoop(isActive ? null : loop.id)}
                                title={
                                    isActive
                                        ? 'Active loop (auto-engages on track load)'
                                        : 'Set as active loop'
                                }
                                className={
                                    isActive
                                        ? 'text-amber2'
                                        : 'text-ink-muted hover:text-white'
                                }
                            >
                                {isActive ? (
                                    <CheckCircle2 size={12} />
                                ) : (
                                    <Circle size={12} />
                                )}
                            </button>
                            <div
                                className="w-3 h-3 rounded-sm cursor-pointer flex-shrink-0"
                                style={{ backgroundColor: colorHex }}
                                onClick={() =>
                                    setActiveColorEdit(
                                        activeColorEdit === loop.id ? null : loop.id,
                                    )
                                }
                                title="Click to change color"
                            />
                            <span className="text-[10px] font-mono text-ink-secondary w-14 flex-shrink-0">
                                {formatTime(loop.time_ms / 1000)}
                            </span>
                            <span className="text-[10px] text-ink-muted flex items-center gap-1 w-14 flex-shrink-0">
                                <Repeat size={10} />
                                {lengthBeats}/{loop.loop_denominator || 1}
                            </span>
                            <input
                                type="text"
                                value={loop.name || ''}
                                onChange={(e) =>
                                    updateLoopFields(loop.id, { name: e.target.value })
                                }
                                placeholder="Comment..."
                                className="flex-1 bg-transparent text-[10px] text-white outline-none border-b border-transparent focus:border-amber2/50"
                            />
                            <button
                                onClick={() => deleteLoop(loop.id)}
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
                                    updateLoopFields(activeColorEdit, {
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
    );
}

// --- helpers -------------------------------------------------------------

function normaliseLoop(c) {
    return {
        id: c.id || `loop-${Date.now()}-${Math.random()}`,
        type: c.type || (c.Num > 0 ? 'hot_loop' : 'memory_loop'),
        number: c.number || c.Num || 0,
        time_ms: c.time_ms || c.InMsec || 0,
        loop_len_ms: c.loop_len_ms || 0,
        loop_numerator: c.loop_numerator || 0,
        loop_denominator: c.loop_denominator || 1,
        name: c.name || c.Comment || '',
        color_id: c.color_id || 0,
        color_rgb: c.color_rgb || [0, 0, 0],
        status: c.status || (c.Type === 4 ? 4 : 0),
    };
}

function hexToRgb(hex) {
    const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex);
    return m
        ? [parseInt(m[1], 16), parseInt(m[2], 16), parseInt(m[3], 16)]
        : [0, 0, 0];
}

function formatTime(seconds) {
    if (!isFinite(seconds)) return '0:00';
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
}

function lengthFromMs(loopLenMs, bpm) {
    const beatMs = (60 / Math.max(60, bpm)) * 1000;
    return Math.round(loopLenMs / beatMs);
}
