/**
 * PlayCountSync — collapsible section inside UsbView.
 *
 * Shows auto-resolved count summary and a conflict table with per-track
 * strategy dropdowns. Two-step commit: "Review" → "Write Sync".
 *
 * Props:
 *   usbRoot     — root path of the mounted USB drive (e.g. "E:\")
 *   usbXmlPath  — path to the Rekordbox XML on the USB
 */
import React, { useState } from 'react';
import {
    ArrowUpDown, RefreshCw, Loader2, AlertTriangle, ChevronDown, ChevronRight,
} from 'lucide-react';
import api from '../../api/api';

const PlayCountSync = ({ usbRoot, usbXmlPath }) => {
    const [open, setOpen] = useState(false);
    const [loading, setLoading] = useState(false);
    const [diffData, setDiffData] = useState(null);  // {auto, conflicts, last_sync_ts}
    const [error, setError] = useState(null);
    const [strategies, setStrategies] = useState({});  // {track_id: strategy}
    const [committing, setCommitting] = useState(false);
    const [commitResult, setCommitResult] = useState(null);
    const [confirmStep, setConfirmStep] = useState(0);  // 0=idle 1=confirm 2=confirmed

    const log = (level, msg, data) =>
        console[level]?.(`[PlayCountSync] ${msg}`, data ?? '');

    const fetchDiff = async () => {
        if (!usbRoot || !usbXmlPath) {
            setError('USB root or XML path not set. Select a USB device first.');
            return;
        }
        setLoading(true);
        setError(null);
        setDiffData(null);
        setCommitResult(null);
        setConfirmStep(0);
        log('info', 'fetchDiff', { usbRoot, usbXmlPath });
        try {
            const res = await api.get('/api/usb/playcount/diff', {
                params: { usb_root: usbRoot, usb_xml_path: usbXmlPath },
            });
            if (res.data?.status !== 'ok') throw new Error(res.data?.message || 'Unknown error');
            const data = res.data.data;
            setDiffData(data);
            // Default strategy for every conflict: take_max
            const initStrategies = {};
            (data.conflicts || []).forEach(c => { initStrategies[c.track_id] = 'take_max'; });
            setStrategies(initStrategies);
            log('info', 'diff loaded', { auto: data.auto?.length, conflicts: data.conflicts?.length });
        } catch (e) {
            log('error', 'fetchDiff failed', e);
            setError(e.message || 'Failed to load diff');
        } finally {
            setLoading(false);
        }
    };

    const setAllMax = () => {
        const next = {};
        (diffData?.conflicts || []).forEach(c => { next[c.track_id] = 'take_max'; });
        setStrategies(next);
    };

    const handleCommit = async () => {
        if (confirmStep === 0) { setConfirmStep(1); return; }
        if (confirmStep === 1) { setConfirmStep(2); return; }

        // Step 2 — actually commit
        setCommitting(true);
        setError(null);
        log('info', 'committing resolutions');
        try {
            const resolutions = (diffData?.conflicts || []).map(c => ({
                track_id: c.track_id,
                strategy: strategies[c.track_id] || 'take_max',
                pc_count: c.pc_count,
                usb_count: c.usb_count,
                pc_last_played: c.pc_last_played,
                usb_last_played: c.usb_last_played,
            }));
            const res = await api.post('/api/usb/playcount/resolve', {
                resolutions,
                usb_root: usbRoot,
                usb_xml_path: usbXmlPath,
            });
            if (res.data?.status !== 'ok') throw new Error(res.data?.message || 'Commit failed');
            setCommitResult(res.data.data);
            setConfirmStep(0);
            log('info', 'commit result', res.data.data);
        } catch (e) {
            log('error', 'commit failed', e);
            setError(e.message || 'Commit failed');
            setConfirmStep(0);
        } finally {
            setCommitting(false);
        }
    };

    const formatTs = (ts) => {
        if (!ts || ts === 0) return 'Never';
        return new Date(ts * 1000).toLocaleDateString();
    };

    return (
        <div className="mx-card rounded-mx-md mt-4">
            {/* Header toggle */}
            <button
                className="w-full flex items-center justify-between px-4 py-3 hover:bg-mx-hover rounded-mx-md transition-colors"
                onClick={() => setOpen(o => !o)}
                aria-expanded={open}
            >
                <div className="flex items-center gap-2">
                    <ArrowUpDown size={14} className="text-amber2" />
                    <span className="text-[12px] font-semibold text-ink-primary">Play Count Sync</span>
                </div>
                {open ? <ChevronDown size={14} className="text-ink-muted" /> : <ChevronRight size={14} className="text-ink-muted" />}
            </button>

            {open && (
                <div className="px-4 pb-4 border-t border-line-subtle pt-3 space-y-3">
                    {/* Controls row */}
                    <div className="flex items-center gap-2">
                        <button
                            onClick={fetchDiff}
                            disabled={loading}
                            className="btn-primary text-[11px] py-1.5 px-3 flex items-center gap-1.5"
                        >
                            {loading ? <Loader2 size={11} className="animate-spin" /> : <RefreshCw size={11} />}
                            Analyse Counts
                        </button>
                        {diffData?.last_sync_ts !== undefined && (
                            <span className="text-[10px] text-ink-muted font-mono">
                                Last sync: {formatTs(diffData.last_sync_ts)}
                            </span>
                        )}
                    </div>

                    {/* Error */}
                    {error && (
                        <div className="text-bad text-[11px] bg-bad/5 border border-bad/20 rounded-mx-sm px-3 py-2 flex items-center gap-2">
                            <AlertTriangle size={12} /> {error}
                        </div>
                    )}

                    {/* Commit result */}
                    {commitResult && (
                        <div className="text-ok text-[11px] bg-ok/5 border border-ok/20 rounded-mx-sm px-3 py-2">
                            Sync written — {commitResult.committed} track(s) updated.
                            {(commitResult.errors || []).length > 0 && (
                                <span className="text-amber2 ml-2">{commitResult.errors.length} warning(s)</span>
                            )}
                        </div>
                    )}

                    {diffData && (
                        <>
                            {/* Auto-resolved summary */}
                            <div className="flex items-center gap-4 text-[11px] font-mono">
                                <span className="text-ink-secondary">
                                    Auto: <span className="text-ok font-semibold">{(diffData.auto || []).length}</span>
                                </span>
                                <span className="text-ink-secondary">
                                    Conflicts: <span className={diffData.conflicts?.length > 0 ? 'text-amber2 font-semibold' : 'text-ok font-semibold'}>
                                        {(diffData.conflicts || []).length}
                                    </span>
                                </span>
                            </div>

                            {/* Conflict table */}
                            {(diffData.conflicts || []).length > 0 && (
                                <div className="space-y-2">
                                    <div className="flex items-center justify-between">
                                        <span className="text-[10px] uppercase tracking-wider text-ink-muted font-semibold">Conflicts</span>
                                        <button
                                            onClick={setAllMax}
                                            className="text-[10px] text-amber2 hover:underline"
                                        >
                                            Set All to MAX
                                        </button>
                                    </div>

                                    <div className="border border-line-subtle rounded-mx-sm overflow-hidden">
                                        {/* Table header */}
                                        <div className="grid grid-cols-[1fr_72px_72px_120px] gap-1 px-3 py-1.5 bg-mx-base text-[10px] text-ink-muted font-semibold uppercase tracking-wider border-b border-line-subtle">
                                            <span>Track</span>
                                            <span className="text-right">PC</span>
                                            <span className="text-right">USB</span>
                                            <span className="text-center">Strategy</span>
                                        </div>
                                        {/* Rows */}
                                        <div className="max-h-56 overflow-y-auto divide-y divide-line-subtle">
                                            {diffData.conflicts.map(c => (
                                                <div
                                                    key={c.track_id}
                                                    className="grid grid-cols-[1fr_72px_72px_120px] gap-1 px-3 py-2 items-center hover:bg-mx-hover"
                                                >
                                                    <div className="min-w-0">
                                                        <p className="text-[11px] text-ink-primary truncate">{c.title || c.track_id}</p>
                                                        {c.artist && <p className="text-[10px] text-ink-muted truncate">{c.artist}</p>}
                                                    </div>
                                                    <span className="text-right text-[11px] font-mono text-info">{c.pc_count}</span>
                                                    <span className="text-right text-[11px] font-mono text-amber2">{c.usb_count}</span>
                                                    <select
                                                        value={strategies[c.track_id] || 'take_max'}
                                                        onChange={e => setStrategies(s => ({ ...s, [c.track_id]: e.target.value }))}
                                                        className="input-glass text-[10px] py-0.5 px-1.5 rounded-mx-xs"
                                                    >
                                                        <option value="take_max">Take MAX</option>
                                                        <option value="take_pc">Take PC</option>
                                                        <option value="take_usb">Take USB</option>
                                                        <option value="sum">Sum Both</option>
                                                    </select>
                                                </div>
                                            ))}
                                        </div>
                                    </div>

                                    {/* Commit button — double-confirm */}
                                    <div className="flex items-center gap-2 pt-1">
                                        {confirmStep === 0 && (
                                            <button onClick={handleCommit} className="btn-secondary text-[11px] py-1.5 px-3">
                                                Write Sync
                                            </button>
                                        )}
                                        {confirmStep === 1 && (
                                            <>
                                                <span className="text-amber2 text-[11px]">This will modify both PC DB and USB XML.</span>
                                                <button onClick={handleCommit} className="btn-secondary text-[11px] py-1.5 px-3">
                                                    Confirm
                                                </button>
                                                <button onClick={() => setConfirmStep(0)} className="text-[10px] text-ink-muted hover:text-ink-secondary">
                                                    Cancel
                                                </button>
                                            </>
                                        )}
                                        {confirmStep === 2 && (
                                            <>
                                                <span className="text-bad text-[11px] font-semibold">Last chance — this cannot be undone.</span>
                                                <button onClick={handleCommit} disabled={committing} className="btn-primary text-[11px] py-1.5 px-3 flex items-center gap-1.5">
                                                    {committing ? <Loader2 size={11} className="animate-spin" /> : null}
                                                    Write Now
                                                </button>
                                                <button onClick={() => setConfirmStep(0)} className="text-[10px] text-ink-muted hover:text-ink-secondary">
                                                    Cancel
                                                </button>
                                            </>
                                        )}
                                    </div>
                                </div>
                            )}

                            {(diffData.conflicts || []).length === 0 && (
                                <p className="text-ok text-[11px]">No conflicts — all play counts auto-resolved.</p>
                            )}
                        </>
                    )}
                </div>
            )}
        </div>
    );
};

export default PlayCountSync;
