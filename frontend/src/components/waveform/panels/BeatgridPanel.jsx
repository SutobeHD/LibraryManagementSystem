/**
 * BeatgridPanel — beatgrid editor with three modes: anchor-shift,
 * tap-BPM, per-beat (read-only display in Slice 3).
 *
 * Surface-agnostic: reads from useTrackEditorState. Mounted in
 * WaveformEditor and DjEditDaw behind FEATURE_BEATGRID_PANEL.
 *
 * Q7: full editing modes available with anchor-shift as the default
 * tab. Per-beat inline editing is read-only in Slice 3; a future slice
 * can add inline numeric editing or drag-on-beat in WaveformCanvas.
 *
 * Slice 3 of waveform-editor-extensions.
 */

import { useCallback, useEffect, useState } from 'react';
import { RotateCcw, Save } from 'lucide-react';
import api from '../../../api/api';
import { useToast } from '../../ToastContext';
import { log } from '../../../utils/log';
import useTrackEditorState from '../state/useTrackEditorState';

const MODES = [
    { key: 'anchor', label: 'Anchor Shift' },
    { key: 'tap', label: 'Tap BPM' },
    { key: 'perbeat', label: 'Per-Beat' },
];

export default function BeatgridPanel({ track, bpm = 128, beatGrid: initialBeatGrid }) {
    const toast = useToast();
    const { state, loadBeatgrid, anchorShift, setBpm } = useTrackEditorState();
    const { beatgrid } = state;

    const [mode, setMode] = useState('anchor');
    const [shiftMs, setShiftMs] = useState(0);
    const [tapTimes, setTapTimes] = useState([]);
    const [computedBpm, setComputedBpm] = useState(null);
    const [isSaving, setIsSaving] = useState(false);

    // Seed beatgrid into the hook from the WaveformEditor's useState-bag
    // on first mount. Fetch the persisted override afterwards so a
    // previous save wins over the analysis-time grid.
    useEffect(() => {
        if (!track?.id) return;
        let cancelled = false;
        (async () => {
            // Fall back to the prop on first mount
            if (beatgrid.length === 0 && initialBeatGrid && initialBeatGrid.length > 0) {
                loadBeatgrid({ beatgrid: initialBeatGrid.map(normaliseBeat) });
            }
            try {
                const resp = await api.get(`/api/track/${track.id}/cues`);
                if (cancelled) return;
                // The grid endpoint isn't a GET yet (POST-only saver). Skip
                // remote-load for slice 3; the hook is seeded from the prop
                // which is the latest in-memory grid from the WaveformEditor.
                void resp;
            } catch (err) {
                log.warn('[BeatgridPanel] grid load skipped', err);
            }
        })();
        return () => {
            cancelled = true;
        };
    }, [track?.id, initialBeatGrid, beatgrid.length, loadBeatgrid]);

    const handleApplyShift = () => {
        if (shiftMs === 0) return;
        anchorShift(shiftMs);
        toast.info(`Beatgrid shifted ${shiftMs > 0 ? '+' : ''}${shiftMs}ms`);
        setShiftMs(0);
    };

    const handleTap = () => {
        const now = performance.now();
        setTapTimes((prev) => {
            // Reset if last tap was > 2s ago
            if (prev.length > 0 && now - prev[prev.length - 1] > 2000) {
                return [now];
            }
            const next = [...prev, now];
            if (next.length >= 4) {
                const intervals = [];
                for (let i = 1; i < next.length; i++) {
                    intervals.push(next[i] - next[i - 1]);
                }
                const avgMs = intervals.reduce((a, b) => a + b, 0) / intervals.length;
                setComputedBpm(Math.round((60000 / avgMs) * 10) / 10);
            }
            return next;
        });
    };

    const handleApplyBpm = () => {
        if (!computedBpm) return;
        setBpm(computedBpm);
        toast.success(`Beatgrid regenerated at ${computedBpm} BPM`);
        setTapTimes([]);
        setComputedBpm(null);
    };

    const handleReset = () => {
        setTapTimes([]);
        setComputedBpm(null);
    };

    const handleSave = useCallback(async () => {
        if (!track?.id || beatgrid.length === 0) return;
        setIsSaving(true);
        try {
            await api.post('/api/track/grid/save', {
                track_id: track.id,
                beat_grid: beatgrid,
            });
            toast.success(`Saved ${beatgrid.length} beats`);
        } catch (err) {
            log.error('[BeatgridPanel] save failed', err);
            toast.error('Failed to save beatgrid');
        } finally {
            setIsSaving(false);
        }
    }, [track?.id, beatgrid, toast]);

    return (
        <div className="bg-[#1a1a1a] border border-white/5 rounded-lg p-3 my-2">
            <div className="flex items-center justify-between mb-3">
                <h3 className="text-[11px] font-bold tracking-wider text-amber2">
                    BEATGRID
                    <span className="ml-2 text-ink-muted font-normal">
                        {beatgrid.length} beats @ {bpm.toFixed(2)} BPM
                    </span>
                </h3>
                <button
                    onClick={handleSave}
                    disabled={isSaving || beatgrid.length === 0}
                    className="flex items-center gap-1.5 px-3 py-1 bg-amber2/20 border border-amber2/30 text-amber2 text-[10px] font-bold rounded hover:bg-amber2/30 disabled:opacity-50"
                >
                    <Save size={12} />
                    {isSaving ? 'SAVING...' : 'SAVE'}
                </button>
            </div>

            {/* Mode tabs */}
            <div className="flex gap-1 mb-3 border-b border-white/5">
                {MODES.map((m) => (
                    <button
                        key={m.key}
                        onClick={() => setMode(m.key)}
                        className={`px-3 py-1 text-[10px] font-bold uppercase border-b-2 transition-all ${
                            mode === m.key
                                ? 'text-amber2 border-amber2'
                                : 'text-ink-muted border-transparent hover:text-white'
                        }`}
                    >
                        {m.label}
                    </button>
                ))}
            </div>

            {/* Anchor shift */}
            {mode === 'anchor' && (
                <div>
                    <div className="text-[10px] text-ink-muted mb-2">
                        Shift all beats by Δms. Useful when the grid is offset by a constant amount.
                    </div>
                    <div className="flex items-center gap-2">
                        <button
                            onClick={() => setShiftMs((v) => v - 10)}
                            className="px-2 py-1 bg-white/5 border border-white/10 text-[10px] text-white rounded"
                        >
                            -10
                        </button>
                        <input
                            type="number"
                            value={shiftMs}
                            onChange={(e) => setShiftMs(parseInt(e.target.value, 10) || 0)}
                            className="flex-1 bg-[#0f0f0f] border border-white/10 text-[10px] text-white px-2 py-1 rounded text-center font-mono"
                        />
                        <button
                            onClick={() => setShiftMs((v) => v + 10)}
                            className="px-2 py-1 bg-white/5 border border-white/10 text-[10px] text-white rounded"
                        >
                            +10
                        </button>
                        <button
                            onClick={handleApplyShift}
                            disabled={shiftMs === 0}
                            className="px-3 py-1 bg-amber2/20 border border-amber2/30 text-amber2 text-[10px] font-bold rounded hover:bg-amber2/30 disabled:opacity-50"
                        >
                            APPLY
                        </button>
                    </div>
                </div>
            )}

            {/* Tap BPM */}
            {mode === 'tap' && (
                <div>
                    <div className="text-[10px] text-ink-muted mb-2">
                        Tap 4+ times on the beat. Computed BPM = 60000 / avg interval ms.
                    </div>
                    <div className="flex items-center gap-2">
                        <button
                            onClick={handleTap}
                            className="flex-1 py-3 bg-amber2/10 border border-amber2/30 text-amber2 text-[14px] font-bold rounded hover:bg-amber2/20 active:bg-amber2/30"
                        >
                            TAP ({tapTimes.length})
                        </button>
                        {computedBpm !== null && (
                            <>
                                <span className="text-[12px] font-mono text-white">
                                    {computedBpm.toFixed(1)} BPM
                                </span>
                                <button
                                    onClick={handleApplyBpm}
                                    className="px-3 py-1 bg-amber2/20 border border-amber2/30 text-amber2 text-[10px] font-bold rounded"
                                >
                                    APPLY
                                </button>
                            </>
                        )}
                        <button
                            onClick={handleReset}
                            className="px-2 py-1 bg-white/5 border border-white/10 text-[10px] text-ink-muted rounded"
                            title="Reset taps"
                        >
                            <RotateCcw size={10} />
                        </button>
                    </div>
                </div>
            )}

            {/* Per-Beat (read-only in Slice 3) */}
            {mode === 'perbeat' && (
                <div>
                    <div className="text-[10px] text-ink-muted mb-2">
                        Per-beat overview. Showing first 50 of {beatgrid.length} beats.
                        Inline editing comes in a follow-up slice.
                    </div>
                    <div className="space-y-0.5 max-h-40 overflow-y-auto font-mono text-[10px]">
                        {beatgrid.slice(0, 50).map((b, i) => (
                            <div key={i} className="flex items-center gap-2 py-0.5">
                                <span className="w-8 text-ink-muted">#{i + 1}</span>
                                <span className="w-4 text-amber2">{b.beat_number || 1}</span>
                                <span className="text-white">
                                    {((b.time_ms || 0) / 1000).toFixed(3)}s
                                </span>
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
}

function normaliseBeat(b) {
    return {
        beat_number: b.beat_number || b.beatNumber || (b.isDownbeat ? 1 : 2),
        time_ms: b.time_ms !== undefined ? b.time_ms : Math.round((b.time || 0) * 1000),
        tempo: b.tempo || 0,
    };
}
