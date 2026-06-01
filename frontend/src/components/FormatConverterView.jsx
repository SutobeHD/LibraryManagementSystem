import React, { useCallback, useEffect, useRef, useState } from 'react';
import { AlertTriangle, CheckCircle, FileAudio, RotateCcw, Zap } from 'lucide-react';
import { formatSwap, formatSwapRollback, formatSwapStatus } from '../api/api';
import { confirmModal } from './ConfirmModal';
import { useToast } from './ToastContext';

const TARGETS = ['AIFF', 'FLAC', 'WAV', 'MP3'];
const SCOPES = [
    { key: 'all_m4a', label: 'All m4a' },
    { key: 'playlist_id', label: 'Playlist' },
    { key: 'path', label: 'Folder' },
];
const POLL_MS = 1500;
const FINISHED = ['Completed', 'Aborted', 'Failed'];

const FormatConverterView = () => {
    const toast = useToast();
    const [target, setTarget] = useState('AIFF');
    const [scopeKey, setScopeKey] = useState('all_m4a');
    const [scopeValue, setScopeValue] = useState(''); // playlist id or folder path
    const [plan, setPlan] = useState(null);
    const [busy, setBusy] = useState(false);
    const [task, setTask] = useState(null);
    const pollRef = useRef(null);

    const buildScope = useCallback(() => {
        if (scopeKey === 'all_m4a') return { all_m4a: true };
        if (scopeKey === 'playlist_id') return { playlist_id: Number(scopeValue) };
        return { path: scopeValue };
    }, [scopeKey, scopeValue]);

    const scopeReady =
        scopeKey === 'all_m4a' ||
        (scopeKey === 'playlist_id' && scopeValue !== '' && !Number.isNaN(Number(scopeValue))) ||
        (scopeKey === 'path' && scopeValue.trim() !== '');

    const stopPolling = useCallback(() => {
        if (pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
        }
    }, []);

    useEffect(() => stopPolling, [stopPolling]);

    const runDryRun = async () => {
        if (!scopeReady) return;
        setBusy(true);
        setPlan(null);
        try {
            const res = await formatSwap({ scope: buildScope(), target, dry_run: true });
            setPlan(res.data.data);
        } catch (err) {
            console.error('[FormatConverter] dry-run failed', err);
            toast.error(
                err?.response?.data?.detail || 'Dry-run failed. Is the library loaded (live mode)?'
            );
        } finally {
            setBusy(false);
        }
    };

    const pollStatus = useCallback(
        (taskId) => {
            stopPolling();
            pollRef.current = setInterval(async () => {
                try {
                    const res = await formatSwapStatus(taskId);
                    const t = res.data.data;
                    setTask(t);
                    if (FINISHED.includes(t.status)) {
                        stopPolling();
                        if (t.status === 'Completed')
                            toast.success(`Converted ${t.converted} track(s).`);
                        else if (t.status === 'Aborted')
                            toast.error(`Aborted after ${t.converted} track(s).`);
                        else toast.error(t.error || 'Conversion failed.');
                    }
                } catch (err) {
                    console.error('[FormatConverter] status poll failed', err);
                    stopPolling();
                }
            }, POLL_MS);
        },
        [stopPolling, toast]
    );

    const startConvert = async () => {
        if (!plan || plan.convertible === 0) return;
        const ok = await confirmModal({
            title: `Convert ${plan.convertible} track(s) to ${target}?`,
            message:
                `Originals are kept as .backup-<timestamp> and the database is snapshotted first. ` +
                `Rekordbox must be closed; other library edits pause during the run.` +
                (plan.disk_warning ? ' ⚠ Disk space is borderline.' : ''),
            confirmLabel: 'Convert',
        });
        if (!ok) return;
        setBusy(true);
        setTask(null);
        try {
            const res = await formatSwap({ scope: buildScope(), target, dry_run: false });
            const taskId = res.data.data.task_id;
            setTask({
                id: taskId,
                status: 'Queued',
                progress: 0,
                total: plan.convertible,
                converted: 0,
            });
            pollStatus(taskId);
        } catch (err) {
            console.error('[FormatConverter] convert failed', err);
            toast.error(err?.response?.data?.detail || 'Could not start conversion.');
        } finally {
            setBusy(false);
        }
    };

    const rollback = async () => {
        if (!task?.manifest_id) return;
        const ok = await confirmModal({
            title: 'Roll back this conversion?',
            message:
                'Restores the Rekordbox database and the original audio files, deleting the converted ones.',
            confirmLabel: 'Roll back',
            danger: true,
        });
        if (!ok) return;
        try {
            const res = await formatSwapRollback(task.manifest_id);
            toast.success(`Rolled back ${res.data.data.restored_tracks} track(s).`);
            setTask(null);
            setPlan(null);
        } catch (err) {
            console.error('[FormatConverter] rollback failed', err);
            toast.error(err?.response?.data?.detail || 'Rollback failed.');
        }
    };

    const running = task && !FINISHED.includes(task.status);

    return (
        <div className="p-10 h-full overflow-y-auto text-white">
            <div className="max-w-3xl mx-auto flex flex-col gap-6">
                <header>
                    <h1 className="text-3xl font-bold flex items-center gap-3">
                        <FileAudio size={28} className="text-amber2" /> Format Converter
                    </h1>
                    <p className="text-ink-secondary mt-1">
                        Convert your library to another format while keeping cues, beatgrid,
                        hot/memory cues and playlists intact.
                    </p>
                </header>

                {/* Scope + target pickers */}
                <section className="bg-mx-card/60 border border-line-default rounded-2xl p-5 flex flex-col gap-4">
                    <div>
                        <div className="text-xs uppercase tracking-widest text-ink-muted mb-2">
                            1 · What to convert
                        </div>
                        <div className="flex gap-2 flex-wrap">
                            {SCOPES.map((s) => (
                                <button
                                    key={s.key}
                                    onClick={() => {
                                        setScopeKey(s.key);
                                        setScopeValue('');
                                        setPlan(null);
                                    }}
                                    className={`px-4 py-2 rounded-lg border text-sm transition-all ${
                                        scopeKey === s.key
                                            ? 'bg-amber2/20 border-amber2 text-amber2'
                                            : 'border-line-default text-ink-secondary hover:border-amber2/40'
                                    }`}
                                >
                                    {s.label}
                                </button>
                            ))}
                        </div>
                        {scopeKey === 'playlist_id' && (
                            <input
                                type="number"
                                value={scopeValue}
                                onChange={(e) => {
                                    setScopeValue(e.target.value);
                                    setPlan(null);
                                }}
                                placeholder="Playlist ID"
                                className="mt-3 w-full bg-mx-deepest border border-line-default rounded-lg px-3 py-2 text-sm"
                            />
                        )}
                        {scopeKey === 'path' && (
                            <input
                                type="text"
                                value={scopeValue}
                                onChange={(e) => {
                                    setScopeValue(e.target.value);
                                    setPlan(null);
                                }}
                                placeholder="Folder path (must be inside an allowed music root)"
                                className="mt-3 w-full bg-mx-deepest border border-line-default rounded-lg px-3 py-2 text-sm font-mono"
                            />
                        )}
                    </div>

                    <div>
                        <div className="text-xs uppercase tracking-widest text-ink-muted mb-2">
                            2 · Target format
                        </div>
                        <div className="flex gap-2">
                            {TARGETS.map((t) => (
                                <button
                                    key={t}
                                    onClick={() => {
                                        setTarget(t);
                                        setPlan(null);
                                    }}
                                    className={`px-4 py-2 rounded-lg border text-sm transition-all ${
                                        target === t
                                            ? 'bg-amber2/20 border-amber2 text-amber2'
                                            : 'border-line-default text-ink-secondary hover:border-amber2/40'
                                    }`}
                                >
                                    {t}
                                </button>
                            ))}
                        </div>
                    </div>

                    <div className="flex gap-3">
                        <button
                            onClick={runDryRun}
                            disabled={!scopeReady || busy || running}
                            className="px-5 py-2 rounded-lg border border-line-default text-sm hover:border-amber2/50 disabled:opacity-40"
                        >
                            Dry run / preview
                        </button>
                        <button
                            onClick={startConvert}
                            disabled={!plan || plan.convertible === 0 || busy || running}
                            className="px-5 py-2 rounded-lg btn-primary text-sm font-bold flex items-center gap-2 disabled:opacity-40"
                        >
                            <Zap size={16} /> Convert…
                        </button>
                    </div>
                </section>

                {/* Dry-run plan */}
                {plan && (
                    <section className="bg-mx-card/60 border border-line-default rounded-2xl p-5">
                        <div className="text-xs uppercase tracking-widest text-ink-muted mb-3">
                            Preview — {plan.scope}
                        </div>
                        {plan.disk_abort && (
                            <div className="mb-3 p-3 bg-red-900/40 border border-red-500/50 rounded-lg flex items-center gap-2 text-red-200">
                                <AlertTriangle size={18} /> Not enough free disk space — conversion
                                blocked.
                            </div>
                        )}
                        {plan.disk_warning && !plan.disk_abort && (
                            <div className="mb-3 p-3 bg-amber-900/30 border border-amber-500/50 rounded-lg flex items-center gap-2 text-amber-200">
                                <AlertTriangle size={18} /> Disk space is borderline — expect to
                                clean up after.
                            </div>
                        )}
                        <div className="grid grid-cols-4 gap-3 text-center">
                            <Stat label="Convertible" value={plan.convertible} />
                            <Stat label="Skipped" value={plan.skipped} />
                            <Stat label="Source" value={`${plan.source_mb} MB`} />
                            <Stat
                                label={`Est. ${target}`}
                                value={`${plan.estimated_target_mb} MB`}
                            />
                        </div>
                    </section>
                )}

                {/* Progress */}
                {task && (
                    <section className="bg-mx-card/60 border border-line-default rounded-2xl p-5">
                        <div className="flex items-center justify-between mb-2">
                            <span className="text-sm font-bold flex items-center gap-2">
                                {task.status === 'Completed' && (
                                    <CheckCircle size={18} className="text-green-400" />
                                )}
                                {task.status}
                            </span>
                            <span className="text-xs text-ink-muted">
                                {task.converted}/{task.total} done
                                {task.failed ? ` · ${task.failed} failed` : ''}
                            </span>
                        </div>
                        <div className="h-2 bg-mx-deepest rounded-full overflow-hidden border border-line-default">
                            <div
                                className="h-full bg-gradient-to-r from-amber2-press to-amber2 transition-all"
                                style={{ width: `${task.progress || 0}%` }}
                            />
                        </div>
                        {task.current_track && (
                            <div className="text-xs text-ink-muted mt-2 font-mono truncate">
                                {task.current_track}
                            </div>
                        )}
                        {task.beatgrid_preserved === false && (
                            <div className="text-xs text-amber-300 mt-2">
                                ⚠ Some sources may need re-analysis (beatgrid not bit-exact).
                            </div>
                        )}
                        {FINISHED.includes(task.status) && task.manifest_id && (
                            <button
                                onClick={rollback}
                                className="mt-4 px-4 py-2 rounded-lg border border-red-500/50 text-red-300 text-sm flex items-center gap-2 hover:bg-red-500/10"
                            >
                                <RotateCcw size={16} /> Roll back
                            </button>
                        )}
                    </section>
                )}
            </div>
        </div>
    );
};

const Stat = ({ label, value }) => (
    <div className="bg-mx-deepest/50 rounded-xl p-3 border border-white/5">
        <div className="text-ink-muted text-[10px] uppercase font-bold tracking-widest mb-1">
            {label}
        </div>
        <div className="text-lg font-mono text-amber2">{value}</div>
    </div>
);

export default FormatConverterView;
