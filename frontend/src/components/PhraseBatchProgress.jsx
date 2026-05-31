/**
 * PhraseBatchProgress — live progress panel for a phrase-cue batch.
 *
 * Renders the polled job dict: determinate bar, done/total, percent, ETA,
 * succeeded / skipped / failed counters, the current track, a cancel button
 * while running, and an expandable list of per-track skip/fail reasons.
 *
 * Melodex tokens (mx-*, ink-*, amber2).
 */

import { useState } from 'react';
import {
    Loader2, Check, X, AlertTriangle, ChevronDown, ChevronRight, Ban,
} from 'lucide-react';

function fmtEta(s) {
    if (s == null || !isFinite(s) || s <= 0) return '—';
    const m = Math.floor(s / 60);
    const sec = Math.round(s % 60);
    return m > 0 ? `${m}m ${sec}s` : `${sec}s`;
}

const Counter = ({ label, value, color }) => (
    <div className="flex flex-col items-center px-3">
        <span className={`text-[16px] font-bold font-mono ${color}`}>{value}</span>
        <span className="text-[9px] uppercase tracking-wider text-ink-muted">{label}</span>
    </div>
);

export default function PhraseBatchProgress({ progress, running, onCancel }) {
    const [showErrors, setShowErrors] = useState(false);
    if (!progress) return null;

    const {
        status,
        total = 0,
        done = 0,
        succeeded = 0,
        skipped = 0,
        failed = 0,
        percent = 0,
        current_track: current,
        eta_seconds: eta,
        errors = [],
        errors_truncated: truncated,
    } = progress;

    const pct = total ? Math.min(100, percent || (done / total) * 100) : 0;
    const isDone = status === 'done';
    const isCancelled = status === 'cancelled';
    const isError = status === 'error';

    return (
        <div className="mx-card rounded-mx-md p-4 space-y-4">
            {/* Status line */}
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-2 text-[13px] font-semibold">
                    {running && <Loader2 size={14} className="animate-spin text-amber2" />}
                    {isDone && <Check size={14} className="text-ok" />}
                    {isCancelled && <Ban size={14} className="text-ink-muted" />}
                    {isError && <AlertTriangle size={14} className="text-bad" />}
                    <span className="text-ink-primary">
                        {running && 'Processing…'}
                        {isDone && 'Batch complete'}
                        {isCancelled && 'Batch cancelled'}
                        {isError && 'Batch failed'}
                    </span>
                </div>
                <span className="font-mono text-[11px] text-amber2">
                    {done} / {total} · {pct.toFixed(0)}%
                </span>
            </div>

            {/* Progress bar */}
            <div className="w-full h-1.5 bg-line-subtle rounded-full overflow-hidden">
                <div
                    className={`h-full rounded-full transition-all duration-300 ${
                        isError ? 'bg-bad' : isCancelled ? 'bg-ink-muted' : 'bg-amber2'
                    }`}
                    style={{ width: `${pct}%` }}
                />
            </div>

            {/* Counters */}
            <div className="flex items-center justify-center divide-x divide-line-subtle">
                <Counter label="Written" value={succeeded} color="text-ok" />
                <Counter label="Skipped" value={skipped} color="text-ink-secondary" />
                <Counter label="Failed" value={failed} color={failed ? 'text-bad' : 'text-ink-muted'} />
                <Counter label="ETA" value={running ? fmtEta(eta) : '—'} color="text-ink-secondary" />
            </div>

            {/* Current track + cancel */}
            <div className="flex items-center gap-3 min-h-[24px]">
                {running && current && (
                    <p className="text-tiny text-ink-muted truncate flex-1">
                        <span className="text-ink-secondary">Now:</span>{' '}
                        {current.title || `Track ${current.id}`}
                    </p>
                )}
                {running && (
                    <button
                        onClick={onCancel}
                        className="ml-auto flex items-center gap-1.5 text-[11px] text-bad hover:text-bad/80 border border-bad/30 hover:bg-bad/5 rounded-mx-sm px-2.5 py-1 transition-colors shrink-0"
                    >
                        <X size={12} /> Cancel
                    </button>
                )}
            </div>

            {/* Error / skip detail */}
            {errors.length > 0 && (
                <div className="border-t border-line-subtle pt-2">
                    <button
                        onClick={() => setShowErrors((s) => !s)}
                        className="flex items-center gap-1.5 text-[11px] text-ink-muted hover:text-ink-secondary"
                    >
                        {showErrors ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                        {errors.length} skipped / failed{truncated ? ' (first 200)' : ''}
                    </button>
                    {showErrors && (
                        <div className="mt-2 space-y-0.5 max-h-48 overflow-y-auto">
                            {errors.map((e, i) => (
                                <div
                                    key={i}
                                    className="flex items-center gap-2 text-[10px] px-2 py-1 rounded-mx-xs hover:bg-mx-hover"
                                >
                                    <span className="text-ink-secondary truncate flex-1">
                                        {e.title || `Track ${e.track_id}`}
                                    </span>
                                    <span className="text-ink-muted font-mono shrink-0">{e.reason}</span>
                                </div>
                            ))}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
