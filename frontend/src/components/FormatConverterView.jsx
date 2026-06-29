/**
 * FormatConverterView — Library-wide audio format converter UI.
 *
 * Backend: app/library_format_swap.py + /api/library/format-swap/* routes.
 * Research: docs/research/research/evaluated_library-format-converter.md
 *           (Option A: full shared engine, AIFF/FLAC/WAV/MP3 targets).
 *
 * Flow:
 *   1. User picks scope (playlist-id | all m4a | path-prefix) + target format.
 *   2. Dry-Run → preview: track count, source MB, estimated target MB, disk
 *      pre-flight (1.5x hard / 1.2x warn margin).
 *   3. Confirm-Modal warning ("Rekordbox must be closed!"), then Execute.
 *   4. Poll /api/library/format-swap/batch/{batch_id} + import_tracker for
 *      per-track progress.
 *   5. Manifests panel allows rollback of any prior batch.
 */

import React, { useState, useEffect, useCallback } from 'react';
import {
    RefreshCw, Loader2, AlertTriangle, CheckCircle2, FileAudio, HardDrive,
    PlayCircle, Undo2, FileText,
} from 'lucide-react';
import api from '../api/api';
import { useToast } from './ToastContext';
import { confirmModal } from './ConfirmModal';
import ScopeBucketPicker from './format-swap/ScopeBucketPicker';

const TARGETS = [
    { value: 'aiff', label: 'AIFF (uncompressed PCM)' },
    { value: 'flac', label: 'FLAC (lossless compressed)' },
    { value: 'wav', label: 'WAV (uncompressed PCM)' },
    { value: 'mp3', label: 'MP3 (LAME -q:a 0, lossy)' },
];

const FormatConverterView = () => {
    const toast = useToast();

    // ── Scope + target form ──────────────────────────────────────────────────
    const [target, setTarget] = useState('aiff');
    // Scope picker owns its own state internally; this is the wire-ready payload
    // (or null when invalid). bucket default = 'subset' since that matches the
    // common case "convert a meaningful slice of the library" better than "find
    // one track ID".
    const [scopeValue, setScopeValue] = useState({ bucket: 'subset', scope: null, isValid: false });

    // ── Dry-run state ─────────────────────────────────────────────────────────
    const [dryLoading, setDryLoading] = useState(false);
    const [dryResult, setDryResult] = useState(null);

    // ── Execute state ─────────────────────────────────────────────────────────
    const [batchId, setBatchId] = useState(null);
    const [batchStatus, setBatchStatus] = useState(null);

    // ── Manifests / rollback ──────────────────────────────────────────────────
    const [manifests, setManifests] = useState([]);
    const [rollbackTarget, setRollbackTarget] = useState('');
    const [rollbackLoading, setRollbackLoading] = useState(false);

    // Stable callback — picker fires on every sub-change. We clear dryResult
    // so the existing dry-run gating logic stays accurate without each picker
    // needing to know about it.
    const handleScopeChange = useCallback((next) => {
        setScopeValue(next);
        setDryResult(null);
    }, []);

    const buildScope = useCallback(() => scopeValue?.scope || null, [scopeValue]);
    const scopeIsValid = !!scopeValue?.isValid;

    // ── Dry-run ───────────────────────────────────────────────────────────────
    const runDryRun = async () => {
        const scope = buildScope();
        if (!scope) {
            toast.error('Pick a scope first.');
            return;
        }
        setDryLoading(true);
        setDryResult(null);
        try {
            const res = await api.post('/api/library/format-swap/dry-run', {
                target,
                scope,
            });
            setDryResult(res.data);
            if (res.data.error) {
                toast.error(`Dry-run: ${res.data.error}`);
            } else if (res.data.warning) {
                toast.warning ? toast.warning(res.data.warning) : toast.info(res.data.warning);
            } else if (res.data.tracks.length === 0) {
                toast.info('Nothing to convert in this scope.');
            } else {
                toast.success(`${res.data.tracks.length} tracks would be converted.`);
            }
        } catch (err) {
            console.error('[FormatConverter] dry-run failed', err);
            toast.error(`Dry-run failed: ${err.response?.data?.detail || err.message}`);
        } finally {
            setDryLoading(false);
        }
    };

    // ── Execute (with Confirm-Modal warning) ──────────────────────────────────
    const runExecute = async () => {
        if (!dryResult || dryResult.tracks.length === 0) {
            toast.error('Run dry-run first to confirm scope.');
            return;
        }
        if (!dryResult.drive_check_pass) {
            toast.error('Disk-space check failed. Free space and re-run.');
            return;
        }
        const ok = await confirmModal({
            title: `Convert ${dryResult.tracks.length} tracks to ${target.toUpperCase()}?`,
            message: [
                `Source: ${dryResult.total_source_mb} MB`,
                `Target: ~${dryResult.estimated_target_mb} MB`,
                `Disk free: ${dryResult.drive_free_mb} MB`,
                '',
                'Rekordbox MUST be closed. Originals will be renamed to .backup-<ts>',
                'for rollback. Cues, beatgrid, hot cues, memory cues and playlist',
                'membership will be preserved via content_id row mutation.',
            ].join('\n'),
            confirmLabel: 'Start Conversion',
            danger: true,
        });
        if (!ok) return;

        const scope = buildScope();
        if (!scope) {
            toast.error('Scope no longer valid — re-pick.');
            return;
        }
        try {
            const res = await api.post('/api/library/format-swap/execute', {
                target,
                scope,
                trigger: 'user_format_pick',
            });
            setBatchId(res.data.batch_id);
            setBatchStatus({ tracks_planned: dryResult.tracks.length, tracks_converted: 0, tracks_failed: 0, finished: false });
            toast.success(`Batch started: ${res.data.batch_id}`);
        } catch (err) {
            console.error('[FormatConverter] execute failed', err);
            toast.error(`Execute failed: ${err.response?.data?.detail || err.message}`);
        }
    };

    // ── Poll batch status while running ──────────────────────────────────────
    useEffect(() => {
        if (!batchId) return;
        let cancelled = false;
        const tick = async () => {
            try {
                const res = await api.get(`/api/library/format-swap/batch/${batchId}`);
                if (cancelled) return;
                setBatchStatus(res.data);
                if (res.data.finished) {
                    if (res.data.error) {
                        toast.error(`Batch ${batchId}: ${res.data.error}`);
                    } else if (res.data.aborted) {
                        toast.warning ? toast.warning(`Batch ${batchId} aborted (${res.data.tracks_converted}/${res.data.tracks_planned})`) : toast.info(`Batch aborted.`);
                    } else {
                        toast.success(`Batch done: ${res.data.tracks_converted}/${res.data.tracks_planned} converted, ${res.data.tracks_failed} failed.`);
                    }
                    // Refresh manifest list after a batch finishes
                    fetchManifests();
                }
            } catch (err) {
                console.error('[FormatConverter] batch poll failed', err);
            }
        };
        tick();
        const id = setInterval(tick, 1500);
        return () => { cancelled = true; clearInterval(id); };
    }, [batchId]);

    // ── Manifest list + rollback ──────────────────────────────────────────────
    const fetchManifests = useCallback(async () => {
        try {
            const res = await api.get('/api/library/format-swap/manifests');
            setManifests(res.data.manifests || []);
        } catch (err) {
            console.error('[FormatConverter] manifests load failed', err);
        }
    }, []);

    useEffect(() => { fetchManifests(); }, [fetchManifests]);

    const runRollback = async () => {
        if (!rollbackTarget) {
            toast.error('Pick a manifest to roll back.');
            return;
        }
        const m = manifests.find(x => x.filename === rollbackTarget);
        const ok = await confirmModal({
            title: 'Roll back this batch?',
            message: [
                `Manifest: ${rollbackTarget}`,
                `Tracks: ${m?.tracks ?? '?'}`,
                '',
                'This restores master.db + WAL + SHM from snapshot and renames',
                '.backup-<ts> files back to their originals. Converted target',
                'files (.aiff / .flac / etc.) will be deleted.',
                '',
                'Rekordbox MUST be closed.',
            ].join('\n'),
            confirmLabel: 'Rollback',
            danger: true,
        });
        if (!ok) return;
        setRollbackLoading(true);
        try {
            const res = await api.post('/api/library/format-swap/rollback', {
                manifest_filename: rollbackTarget,
            });
            toast.success(`Rolled back: ${res.data.audio_restored} files, ${res.data.target_deleted} targets removed.`);
            await fetchManifests();
            setRollbackTarget('');
        } catch (err) {
            console.error('[FormatConverter] rollback failed', err);
            toast.error(`Rollback failed: ${err.response?.data?.detail || err.message}`);
        } finally {
            setRollbackLoading(false);
        }
    };

    const progressPct = batchStatus && batchStatus.tracks_planned > 0
        ? Math.round(((batchStatus.tracks_converted + batchStatus.tracks_failed) / batchStatus.tracks_planned) * 100)
        : 0;

    return (
        <div className="h-full overflow-y-auto bg-mx-deepest p-6 animate-fade-in">
            <div className="max-w-4xl mx-auto space-y-6">
                {/* Header */}
                <div className="flex items-center gap-2.5">
                    <div className="p-2 bg-amber2/10 rounded-mx-md border border-amber2-dim">
                        <RefreshCw size={18} className="text-amber2" />
                    </div>
                    <div>
                        <h1 className="text-[18px] font-semibold tracking-tight">Mass Format Converter</h1>
                        <span className="font-mono text-tiny text-amber2">
                            content_id row-mutate · cues/beatgrid preserved · master.db snapshot + rollback
                        </span>
                    </div>
                </div>

                {/* Warning — Rekordbox must be closed */}
                <div className="mx-card p-4 flex items-start gap-3 border-l-4 border-amber2">
                    <AlertTriangle size={18} className="text-amber2 shrink-0 mt-0.5" />
                    <div className="text-tiny text-ink-secondary leading-relaxed">
                        <strong className="text-ink-primary">Rekordbox must be closed</strong> while a batch
                        runs (writes to <code className="font-mono">master.db</code> are gated).
                        Originals are renamed to <code className="font-mono">.backup-&lt;ts&gt;</code>
                        for rollback — they stay on disk until you delete them manually.
                    </div>
                </div>

                {/* Scope + Target form */}
                <div className="mx-card p-5 space-y-4">
                    <h2 className="text-[14px] font-semibold">Scope &amp; target</h2>

                    <div>
                        <label className="block text-tiny text-ink-muted mb-1.5">Target format</label>
                        <select
                            className="input-glass w-full text-[13px]"
                            value={target}
                            onChange={e => { setTarget(e.target.value); setDryResult(null); }}
                        >
                            {TARGETS.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
                        </select>
                    </div>

                    <div>
                        <label className="block text-tiny text-ink-muted mb-1.5">Scope</label>
                        <ScopeBucketPicker value={scopeValue} onChange={handleScopeChange} />
                    </div>

                    <div className="flex gap-2 pt-2">
                        <button
                            className="px-3 py-2 text-tiny font-medium bg-amber2/10 hover:bg-amber2/20 disabled:opacity-40 border border-amber2/30 rounded-mx-sm transition-colors"
                            onClick={runDryRun}
                            disabled={!scopeIsValid || dryLoading || batchStatus?.finished === false}
                        >
                            {dryLoading ? (<><Loader2 size={12} className="inline mr-1.5 animate-spin" />Probing…</>) : 'Dry-run preview'}
                        </button>
                        <button
                            className="px-3 py-2 text-tiny font-medium bg-rose-500/10 hover:bg-rose-500/20 disabled:opacity-30 border border-rose-500/30 text-rose-300 rounded-mx-sm transition-colors"
                            onClick={runExecute}
                            disabled={!dryResult || dryResult.tracks.length === 0 || !dryResult.drive_check_pass || batchStatus?.finished === false}
                        >
                            <PlayCircle size={12} className="inline mr-1.5" />Execute
                        </button>
                    </div>
                </div>

                {/* Dry-run preview */}
                {dryResult && (
                    <div className="mx-card p-5 space-y-3">
                        <h2 className="text-[14px] font-semibold flex items-center gap-2">
                            <FileAudio size={14} className="text-amber2" /> Dry-run preview
                        </h2>
                        <div className="grid grid-cols-4 gap-3 text-tiny">
                            <div>
                                <div className="text-ink-muted">Tracks</div>
                                <div className="font-mono text-[16px] text-ink-primary">{dryResult.tracks.length}</div>
                            </div>
                            <div>
                                <div className="text-ink-muted">Source</div>
                                <div className="font-mono text-[16px] text-ink-primary">{dryResult.total_source_mb} MB</div>
                            </div>
                            <div>
                                <div className="text-ink-muted">~ Target</div>
                                <div className="font-mono text-[16px] text-ink-primary">{dryResult.estimated_target_mb} MB</div>
                            </div>
                            <div>
                                <div className="text-ink-muted flex items-center gap-1"><HardDrive size={10} /> Free</div>
                                <div className={`font-mono text-[16px] ${dryResult.drive_check_pass ? 'text-emerald-300' : 'text-rose-300'}`}>
                                    {dryResult.drive_free_mb} MB
                                </div>
                            </div>
                        </div>
                        {(dryResult.warning || dryResult.error) && (
                            <div className={`text-tiny p-2 rounded-mx-sm ${dryResult.error ? 'bg-rose-500/10 text-rose-200 border border-rose-500/30' : 'bg-amber2/10 text-amber2 border border-amber2/30'}`}>
                                {dryResult.error || dryResult.warning}
                            </div>
                        )}
                        {dryResult.tracks.length > 0 && (
                            <details className="text-tiny">
                                <summary className="cursor-pointer text-ink-muted hover:text-ink-primary">
                                    Show {Math.min(dryResult.tracks.length, 10)} of {dryResult.tracks.length} affected files
                                </summary>
                                <ul className="font-mono text-[11px] mt-2 space-y-0.5 max-h-48 overflow-y-auto">
                                    {dryResult.tracks.slice(0, 50).map(t => (
                                        <li key={t.content_id} className="truncate text-ink-secondary">
                                            <span className="text-ink-muted">[{t.content_id}]</span> {t.source}
                                        </li>
                                    ))}
                                    {dryResult.tracks.length > 50 && (
                                        <li className="text-ink-muted">... +{dryResult.tracks.length - 50} more</li>
                                    )}
                                </ul>
                            </details>
                        )}
                    </div>
                )}

                {/* Batch progress */}
                {batchStatus && (
                    <div className="mx-card p-5 space-y-3">
                        <h2 className="text-[14px] font-semibold flex items-center gap-2">
                            {batchStatus.finished ? (
                                <CheckCircle2 size={14} className={batchStatus.error || batchStatus.aborted ? 'text-rose-400' : 'text-emerald-400'} />
                            ) : (
                                <Loader2 size={14} className="text-amber2 animate-spin" />
                            )}
                            Batch <code className="font-mono text-[11px]">{batchId}</code>
                            {batchStatus.finished && (
                                <span className="text-tiny text-ink-muted ml-1">
                                    ({batchStatus.error ? 'error' : batchStatus.aborted ? 'aborted' : 'done'})
                                </span>
                            )}
                        </h2>
                        <div className="space-y-2">
                            <div className="h-2 bg-mx-deeper rounded-full overflow-hidden">
                                <div
                                    className="h-full bg-amber2 transition-all duration-300"
                                    style={{ width: `${progressPct}%` }}
                                />
                            </div>
                            <div className="grid grid-cols-4 gap-3 text-tiny font-mono">
                                <div><span className="text-ink-muted">Planned: </span><span className="text-ink-primary">{batchStatus.tracks_planned}</span></div>
                                <div><span className="text-ink-muted">Done: </span><span className="text-emerald-300">{batchStatus.tracks_converted}</span></div>
                                <div><span className="text-ink-muted">Failed: </span><span className="text-rose-300">{batchStatus.tracks_failed}</span></div>
                                <div><span className="text-ink-muted">{progressPct}%</span></div>
                            </div>
                            {batchStatus.error && (
                                <div className="text-tiny p-2 rounded-mx-sm bg-rose-500/10 text-rose-200 border border-rose-500/30">
                                    {batchStatus.error}
                                </div>
                            )}
                            {batchStatus.manifest_path && (
                                <div className="text-tiny text-ink-muted font-mono truncate">
                                    Manifest: {batchStatus.manifest_path}
                                </div>
                            )}
                        </div>
                    </div>
                )}

                {/* Rollback panel */}
                <div className="mx-card p-5 space-y-3">
                    <h2 className="text-[14px] font-semibold flex items-center gap-2">
                        <Undo2 size={14} className="text-amber2" /> Rollback prior batch
                    </h2>
                    {manifests.length === 0 ? (
                        <p className="text-tiny text-ink-muted">No prior batches found.</p>
                    ) : (
                        <>
                            <select
                                className="input-glass w-full text-[13px] font-mono"
                                value={rollbackTarget}
                                onChange={e => setRollbackTarget(e.target.value)}
                            >
                                <option value="">Pick a manifest…</option>
                                {manifests.map(m => (
                                    <option key={m.filename} value={m.filename}>
                                        {m.timestamp} · {m.target} · {m.tracks} tracks · {m.scope_kind}
                                    </option>
                                ))}
                            </select>
                            <button
                                className="px-3 py-2 text-tiny font-medium bg-rose-500/10 hover:bg-rose-500/20 disabled:opacity-40 border border-rose-500/30 text-rose-300 rounded-mx-sm transition-colors"
                                onClick={runRollback}
                                disabled={!rollbackTarget || rollbackLoading}
                            >
                                {rollbackLoading ? (<><Loader2 size={12} className="inline mr-1.5 animate-spin" />Rolling back…</>) : (<><Undo2 size={12} className="inline mr-1.5" />Rollback this batch</>)}
                            </button>
                            <p className="text-tiny text-ink-placeholder">
                                <FileText size={10} className="inline mr-1" />
                                Manifests live under <code className="font-mono">%APPDATA%/MusicLibraryManager/format-swap-backups/</code>.
                            </p>
                        </>
                    )}
                </div>
            </div>
        </div>
    );
};

export default FormatConverterView;
