import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'react-hot-toast';
import {
    AlertTriangle,
    ChevronDown,
    ChevronRight,
    Database,
    FileAudio,
    GitMerge,
    HardDrive,
    History,
    Loader2,
    RotateCcw,
    Undo2,
    X,
} from 'lucide-react';

import { confirmModal } from '../ConfirmModal';
import {
    applyMerge,
    errorMessage,
    fetchMergeCandidates,
    fetchMergePreview,
    fetchMergeRuns,
    isRekordboxRunning,
    revertMergeRun,
} from './artistHubApi';
import {
    JOURNAL_NOTE,
    ORPHAN_WARNING_LINE,
    applySummary,
    compoundWarning,
    confirmMessage,
    dryRunLine,
    formatNumber,
    mergeEffects,
    pluralise,
    revertSummary,
} from './mergeCopy';

/**
 * MergeDialog — detected duplicate-artist groups, what a merge would do, and the
 * journal that takes it back.
 *
 * Three rules this dialog exists to keep (see
 * `docs/research/implement/inprogress_library-artist-hub.md`, blocker 4):
 *  1. Nothing is written until an explicit confirm, and the confirm states ALL
 *     three effects — master.db rows, audio-file tags, USB folder moves.
 *  2. Orphan removal is opt-in, unchecked, with its collateral spelled out.
 *  3. A merge is only honestly "revertable" if the user can reach the run list,
 *     so the History tab is part of the same dialog, not a hidden route.
 *
 * Copy lives in `mergeCopy.js` (pure + tested); transport in `artistHubApi.js`.
 */

const TAB_GROUPS = 'groups';
const TAB_HISTORY = 'history';

const RUN_REVERTED = 'reverted';

const EFFECT_ICON = { db: Database, files: FileAudio, usb: HardDrive };

// Long lists of skipped files help nobody inside a dialog — the run stays in the
// journal with the full record.
const MAX_SKIPPED_SHOWN = 5;
const MAX_USB_FOLDERS_SHOWN = 6;

const PERCENT_MAX = 100;

const STATUS_STYLE = {
    completed: 'text-ok bg-ok/[0.07] border-ok/30',
    reverted: 'text-ink-muted bg-mx-card border-line-subtle',
    revert_partial: 'text-amber2 bg-amber2/10 border-amber2/40',
    failed: 'text-bad bg-bad/10 border-bad/40',
    in_progress: 'text-info bg-info/10 border-info/40',
};

const runTime = (iso) => {
    if (!iso) return '—';
    const parsed = new Date(iso);
    return Number.isNaN(parsed.getTime()) ? String(iso) : parsed.toLocaleString();
};

const previewKey = (groupId, canonical) => `${groupId}::${canonical}`;

const Chip = ({ children, tone = 'muted' }) => (
    <span
        className={`px-2 py-[3px] rounded-mx-xs text-[10px] whitespace-nowrap border ${
            tone === 'amber'
                ? 'text-amber2 bg-amber2/10 border-amber2/40'
                : 'text-ink-muted bg-mx-card border-line-subtle'
        }`}
    >
        {children}
    </span>
);

const Callout = ({ icon: Icon, tone, title, children }) => (
    <div
        className={`flex gap-2.5 p-3 rounded-xl border ${
            tone === 'warn'
                ? 'bg-amber2/[0.07] border-amber2/30'
                : 'bg-mx-card/60 border-line-subtle'
        }`}
    >
        <Icon
            size={15}
            className={`mt-[1px] shrink-0 ${tone === 'warn' ? 'text-amber2' : 'text-ink-muted'}`}
        />
        <div className="min-w-0">
            {title && (
                <div className="text-[12px] font-semibold text-ink-primary mb-0.5">{title}</div>
            )}
            <div className="text-[11.5px] text-ink-secondary leading-relaxed">{children}</div>
        </div>
    </div>
);

const MergeDialog = ({ seedName, onClose, onApplied }) => {
    const [tab, setTab] = useState(TAB_GROUPS);
    const [candidates, setCandidates] = useState([]);
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState('');
    const [expanded, setExpanded] = useState(null);
    const [canonicalBy, setCanonicalBy] = useState({});
    const [orphansBy, setOrphansBy] = useState({});
    const [previewBy, setPreviewBy] = useState({});
    const [previewErrorBy, setPreviewErrorBy] = useState({});
    const [previewLoadingKey, setPreviewLoadingKey] = useState(null);
    const [applyingId, setApplyingId] = useState(null);
    const [progress, setProgress] = useState(null);
    const [lastResult, setLastResult] = useState(null);
    const [runs, setRuns] = useState(null);
    const [runsLoading, setRunsLoading] = useState(false);
    const [revertingId, setRevertingId] = useState(null);
    const [blocked, setBlocked] = useState('');
    const [seedMiss, setSeedMiss] = useState('');

    // The dialog can be closed while a run is still going; the poll must not
    // write into an unmounted component (and the run itself keeps going).
    const closedRef = useRef(false);
    // confirmModal owns Escape while it is open — ours must not fire underneath.
    const confirmOpenRef = useRef(false);
    const previewCacheRef = useRef({});
    const previewInFlightRef = useRef(new Set());
    const seedAppliedRef = useRef(false);

    useEffect(
        () => () => {
            closedRef.current = true;
        },
        []
    );

    const loadCandidates = useCallback(async () => {
        setLoading(true);
        try {
            const rows = await fetchMergeCandidates();
            if (closedRef.current) return;
            setCandidates(rows);
            setLoadError('');
        } catch (e) {
            console.error('[MergeDialog] failed to load merge candidates', e);
            if (closedRef.current) return;
            setCandidates([]);
            setLoadError(errorMessage(e, 'Could not load the duplicate-artist groups.'));
        } finally {
            if (!closedRef.current) setLoading(false);
        }
    }, []);

    const loadRuns = useCallback(async () => {
        setRunsLoading(true);
        try {
            const rows = await fetchMergeRuns();
            if (!closedRef.current) setRuns(rows);
        } catch (e) {
            console.error('[MergeDialog] failed to load the merge journal', e);
            if (!closedRef.current) {
                setRuns([]);
                toast.error(errorMessage(e, 'Could not load the merge history.'));
            }
        } finally {
            if (!closedRef.current) setRunsLoading(false);
        }
    }, []);

    useEffect(() => {
        loadCandidates();
    }, [loadCandidates]);

    useEffect(() => {
        if (tab === TAB_HISTORY && runs === null && !runsLoading) loadRuns();
    }, [tab, runs, runsLoading, loadRuns]);

    // Opened from an artist row / the GitMerge button: jump straight to that
    // artist's group instead of making the user find it in the list. A name with
    // no group is said out loud — silently showing the full list would read as
    // "here are your duplicates for X", which is the opposite of the truth.
    useEffect(() => {
        if (seedAppliedRef.current || !seedName || loading) return;
        seedAppliedRef.current = true;
        const wanted = String(seedName).toLowerCase();
        const hit = candidates.find((c) =>
            (c.variants ?? []).some((v) => String(v.name).toLowerCase() === wanted)
        );
        if (hit) setExpanded(hit.group_id);
        else if (candidates.length > 0) setSeedMiss(String(seedName));
    }, [seedName, candidates, loading]);

    const canonicalFor = useCallback(
        (group) =>
            canonicalBy[group.group_id] ??
            group.suggested_canonical ??
            group.variants?.[0]?.name ??
            '',
        [canonicalBy]
    );

    const loadPreview = useCallback(async (group, canonical) => {
        const key = previewKey(group.group_id, canonical);
        if (previewCacheRef.current[key] || previewInFlightRef.current.has(key)) return;
        previewInFlightRef.current.add(key);
        setPreviewLoadingKey(key);
        try {
            const data = await fetchMergePreview({
                names: (group.variants ?? []).map((v) => v.name),
                canonical,
            });
            previewCacheRef.current[key] = data;
            if (!closedRef.current) {
                setPreviewBy((prev) => ({ ...prev, [key]: data }));
                setPreviewErrorBy((prev) => ({ ...prev, [key]: '' }));
            }
        } catch (e) {
            console.error('[MergeDialog] preview failed', e);
            if (!closedRef.current) {
                setPreviewErrorBy((prev) => ({
                    ...prev,
                    [key]: errorMessage(e, 'Could not compute what this merge would do.'),
                }));
            }
        } finally {
            previewInFlightRef.current.delete(key);
            if (!closedRef.current) {
                setPreviewLoadingKey((current) => (current === key ? null : current));
            }
        }
    }, []);

    const expandedGroup = useMemo(
        () => candidates.find((c) => c.group_id === expanded) ?? null,
        [candidates, expanded]
    );

    useEffect(() => {
        if (!expandedGroup) return;
        loadPreview(expandedGroup, canonicalFor(expandedGroup));
    }, [expandedGroup, canonicalFor, loadPreview]);

    const close = useCallback(() => {
        closedRef.current = true;
        onClose?.();
    }, [onClose]);

    useEffect(() => {
        const onKey = (e) => {
            if (e.key !== 'Escape' || confirmOpenRef.current || applyingId || revertingId) return;
            e.stopPropagation();
            close();
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [close, applyingId, revertingId]);

    const runMerge = useCallback(
        async (group) => {
            const canonical = canonicalFor(group);
            const key = previewKey(group.group_id, canonical);
            const preview = previewBy[key];
            if (!preview) return;
            const deleteOrphans = !!orphansBy[group.group_id];

            confirmOpenRef.current = true;
            const ok = await confirmModal({
                title: `Merge into "${canonical}"?`,
                message: confirmMessage(preview, { deleteOrphans }),
                confirmLabel: `Merge ${formatNumber(preview.tracks_to_rewrite)} tracks`,
                cancelLabel: 'Cancel',
                danger: true,
            });
            confirmOpenRef.current = false;
            if (!ok) return;

            setBlocked('');
            setLastResult(null);
            setApplyingId(group.group_id);
            setProgress(null);
            try {
                const result = await applyMerge(
                    {
                        names: (group.variants ?? []).map((v) => v.name),
                        canonical,
                        deleteOrphans,
                    },
                    {
                        onProgress: (job) => {
                            if (!closedRef.current) setProgress(job);
                        },
                        isCancelled: () => closedRef.current,
                    }
                );
                if (closedRef.current || !result) return;
                setLastResult(result);
                previewCacheRef.current = {};
                setPreviewBy({});
                if (result.aborted) {
                    toast.error(
                        result.abort_reason === 'rekordbox_running'
                            ? 'Merge stopped: Rekordbox was opened mid-run. Close it and re-run — the part that ran is journalled.'
                            : `Merge stopped early — ${applySummary(result)}`
                    );
                } else {
                    toast.success(`Merged into "${canonical}" — ${applySummary(result)}`);
                }
                setRuns(null);
                await loadCandidates();
                onApplied?.(result);
            } catch (e) {
                console.error('[MergeDialog] merge apply failed', e);
                if (closedRef.current) return;
                const message = errorMessage(e, 'The merge failed. Nothing further was written.');
                if (isRekordboxRunning(e)) setBlocked(message);
                toast.error(message);
            } finally {
                if (!closedRef.current) {
                    setApplyingId(null);
                    setProgress(null);
                }
            }
        },
        [canonicalFor, previewBy, orphansBy, loadCandidates, onApplied]
    );

    const runRevert = useCallback(
        async (run) => {
            confirmOpenRef.current = true;
            const ok = await confirmModal({
                title: 'Revert this merge?',
                message: [
                    `Replays run ${run.run_id} backwards: every track it rewrote goes back to the artist it had before${
                        run.canonical ? ` "${run.canonical}"` : ''
                    }, and the file tags are restored from the journalled pre-image.`,
                    '',
                    run.delete_orphans
                        ? 'This run also deleted artist entries. They come back under a NEW id — the Remixer / Composer links it cleared cannot be restored.'
                        : 'Rekordbox must be closed.',
                ].join('\n'),
                confirmLabel: 'Revert',
                cancelLabel: 'Keep',
                danger: true,
            });
            confirmOpenRef.current = false;
            if (!ok) return;

            setBlocked('');
            setRevertingId(run.run_id);
            try {
                const result = await revertMergeRun(run.run_id, {
                    isCancelled: () => closedRef.current,
                });
                if (closedRef.current || !result) return;
                previewCacheRef.current = {};
                setPreviewBy({});
                const summary = revertSummary(result);
                if (result?.complete === false) toast.error(summary);
                else toast.success(summary);
                await loadRuns();
                await loadCandidates();
                onApplied?.(result);
            } catch (e) {
                console.error('[MergeDialog] revert failed', e);
                if (closedRef.current) return;
                const message = errorMessage(e, 'The revert failed. The run stays in the journal.');
                if (isRekordboxRunning(e)) setBlocked(message);
                toast.error(message);
            } finally {
                if (!closedRef.current) setRevertingId(null);
            }
        },
        [loadRuns, loadCandidates, onApplied]
    );

    const openHistory = useCallback(() => setTab(TAB_HISTORY), []);

    const anyJob = !!applyingId || !!revertingId;

    const tabClass = (id) =>
        `flex items-center gap-1.5 px-3 py-2 text-[12px] border-b-2 transition-colors ${
            tab === id
                ? 'font-semibold text-ink-primary border-amber2'
                : 'text-ink-muted border-transparent hover:text-ink-secondary'
        }`;

    const renderGroup = (group) => {
        const isOpen = expanded === group.group_id;
        const canonical = canonicalFor(group);
        const key = previewKey(group.group_id, canonical);
        const preview = previewBy[key];
        const previewError = previewErrorBy[key];
        const busy = applyingId === group.group_id;
        // One artist-hub job at a time server-side — disable every start while
        // any is running instead of letting the backend answer with a 409.
        const locked = anyJob && !busy;
        const variants = group.variants ?? [];

        if (!isOpen) {
            return (
                <div
                    key={group.group_id}
                    className="flex items-center gap-3 px-3 py-2.5 mb-1.5 rounded-xl bg-mx-card/40 border border-white/5"
                >
                    <ChevronRight size={14} className="text-ink-muted shrink-0" />
                    <div className="min-w-0 flex-1">
                        <div className="font-mono text-[12.5px] text-ink-primary truncate">
                            {variants.map((v) => v.name).join('  /  ')}
                        </div>
                        <div className="mt-0.5 text-[11.5px] text-ink-muted">
                            {pluralise(variants.length, 'variant', 'variants')} ·{' '}
                            {pluralise(group.total_tracks, 'track', 'tracks')}
                        </div>
                    </div>
                    <button
                        type="button"
                        onClick={() => setExpanded(group.group_id)}
                        className="px-2.5 py-1 rounded-mx-sm text-[11px] bg-mx-card border border-line-subtle text-ink-primary hover:border-amber2/50 hover:text-amber2 transition-colors shrink-0"
                    >
                        Review
                    </button>
                </div>
            );
        }

        return (
            <div
                key={group.group_id}
                className="mb-3 rounded-xl bg-mx-panel border border-amber2/30 overflow-hidden"
            >
                <button
                    type="button"
                    onClick={() => setExpanded(null)}
                    className="w-full flex items-center gap-2 px-3.5 py-2.5 border-b border-line-subtle text-left hover:bg-white/[0.03] transition-colors"
                >
                    <ChevronDown size={14} className="text-amber2 shrink-0" />
                    <span className="text-[12px] font-semibold text-ink-primary">
                        {pluralise(variants.length, 'variant', 'variants')} ·{' '}
                        {pluralise(group.total_tracks, 'track', 'tracks')}
                    </span>
                    <span className="flex-1" />
                    <Chip>fold key · {group.key}</Chip>
                </button>

                <div className="p-3.5">
                    <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-ink-muted mb-1.5">
                        Canonical name
                    </div>
                    {variants.map((variant) => {
                        const on = variant.name === canonical;
                        return (
                            <label
                                key={variant.name}
                                className={`flex items-center gap-3 px-3 py-2 mb-1.5 rounded-xl border cursor-pointer transition-colors ${
                                    on
                                        ? 'bg-amber2/10 border-amber2/50'
                                        : 'bg-mx-card/40 border-white/5 hover:border-amber2/30'
                                }`}
                            >
                                <input
                                    type="radio"
                                    name={`canonical-${group.group_id}`}
                                    checked={on}
                                    disabled={busy}
                                    onChange={() =>
                                        setCanonicalBy((prev) => ({
                                            ...prev,
                                            [group.group_id]: variant.name,
                                        }))
                                    }
                                    className="accent-amber2"
                                />
                                <span className="font-mono text-[12.5px] text-ink-primary flex-1 min-w-0 truncate">
                                    {variant.name}
                                </span>
                                <Chip tone={on ? 'amber' : 'muted'}>
                                    {pluralise(
                                        variant.track_count ?? variant.tracks,
                                        'track',
                                        'tracks'
                                    )}
                                </Chip>
                            </label>
                        );
                    })}

                    {previewError ? (
                        <div className="mt-2">
                            <Callout icon={AlertTriangle} tone="warn" title="No dry run">
                                {previewError}
                            </Callout>
                        </div>
                    ) : !preview ? (
                        <div className="flex items-center gap-2 py-4 text-[12px] text-ink-muted">
                            <Loader2 size={14} className="animate-spin text-amber2" />
                            {previewLoadingKey === key
                                ? 'Computing the dry run…'
                                : 'Waiting for the dry run…'}
                        </div>
                    ) : (
                        <>
                            <div className="mt-3 px-3 py-2 rounded-xl bg-amber2/10 border border-amber2/40">
                                <div className="text-[13px] font-semibold text-amber2">
                                    {dryRunLine(preview)}
                                </div>
                                <div className="text-[11px] text-ink-muted mt-0.5">
                                    Dry run — nothing is written until you confirm.
                                </div>
                            </div>

                            <div className="mt-3 grid gap-1.5">
                                {mergeEffects(preview).map((effect) => {
                                    const Icon = EFFECT_ICON[effect.id];
                                    return (
                                        <div
                                            key={effect.id}
                                            className="flex gap-2.5 px-3 py-2 rounded-xl bg-mx-card/40 border border-white/5"
                                        >
                                            <Icon
                                                size={14}
                                                className="mt-[2px] shrink-0 text-ink-muted"
                                            />
                                            <span className="text-[11.5px] text-ink-secondary leading-relaxed">
                                                {effect.text}
                                            </span>
                                        </div>
                                    );
                                })}
                            </div>

                            {(preview.usb?.folders_to_merge ?? []).length > 0 && (
                                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                                    {(preview.usb.folders_to_merge ?? [])
                                        .slice(0, MAX_USB_FOLDERS_SHOWN)
                                        .map((folder) => (
                                            <span
                                                key={folder.folder}
                                                className="font-mono text-[10px] text-ink-muted bg-black/25 rounded-mx-xs px-2 py-[3px]"
                                            >
                                                {folder.folder}
                                            </span>
                                        ))}
                                    <span className="text-[10px] text-ink-muted">
                                        →{' '}
                                        <span className="font-mono text-amber2">
                                            {preview.usb.canonical_folder}
                                        </span>
                                    </span>
                                </div>
                            )}

                            {compoundWarning(preview) && (
                                <div className="mt-2">
                                    <Callout
                                        icon={AlertTriangle}
                                        tone="warn"
                                        title="Shared credits are flattened"
                                    >
                                        {compoundWarning(preview)}
                                    </Callout>
                                </div>
                            )}

                            <label className="mt-3 flex items-start gap-2.5 px-3 py-2 rounded-xl bg-mx-card/40 border border-white/5 cursor-pointer">
                                <input
                                    type="checkbox"
                                    checked={!!orphansBy[group.group_id]}
                                    disabled={busy}
                                    onChange={(e) =>
                                        setOrphansBy((prev) => ({
                                            ...prev,
                                            [group.group_id]: e.target.checked,
                                        }))
                                    }
                                    className="mt-[2px] accent-amber2"
                                />
                                <span className="min-w-0">
                                    <span className="text-[12px] text-ink-primary">
                                        Also remove the now-empty artist entries (
                                        {formatNumber(preview.orphans_after)})
                                    </span>
                                    <span className="block text-[11px] text-ink-muted leading-relaxed mt-0.5">
                                        {ORPHAN_WARNING_LINE}
                                    </span>
                                </span>
                            </label>

                            <div className="mt-2">
                                <Callout icon={Undo2} title="Journalled and revertable">
                                    {JOURNAL_NOTE}{' '}
                                    <button
                                        type="button"
                                        onClick={openHistory}
                                        className="text-amber2 hover:underline"
                                    >
                                        Open the run list
                                    </button>
                                    .
                                </Callout>
                            </div>

                            {busy && (
                                <div className="mt-3">
                                    <div className="flex items-center justify-between text-[11px] text-ink-muted mb-1">
                                        <span>
                                            Merging under the database lock — Rekordbox must stay
                                            closed.
                                        </span>
                                        <span className="font-mono">
                                            {formatNumber(progress?.done ?? 0)} /{' '}
                                            {formatNumber(
                                                progress?.total ?? preview.tracks_to_rewrite
                                            )}
                                        </span>
                                    </div>
                                    {/* The engine runs as one atomic pass and reports 0 → total
                                        at the end, so a percentage bar would sit at 0 and read as
                                        hung. Pulse until a real figure arrives. */}
                                    <div className="h-1.5 rounded-full bg-white/10 overflow-hidden">
                                        <div
                                            className={`h-full bg-amber2 transition-all ${
                                                Number(progress?.percent) > 0
                                                    ? ''
                                                    : 'w-1/3 animate-pulse'
                                            }`}
                                            style={
                                                Number(progress?.percent) > 0
                                                    ? {
                                                          width: `${Math.min(
                                                              PERCENT_MAX,
                                                              Number(progress.percent)
                                                          )}%`,
                                                      }
                                                    : undefined
                                            }
                                        />
                                    </div>
                                </div>
                            )}

                            <div className="mt-3.5 flex justify-end gap-2">
                                <button
                                    type="button"
                                    onClick={() => setExpanded(null)}
                                    disabled={busy}
                                    className="px-3 py-1.5 rounded-mx-sm text-[12px] text-ink-secondary hover:text-white transition-colors disabled:opacity-40"
                                >
                                    Skip group
                                </button>
                                <button
                                    type="button"
                                    onClick={() => runMerge(group)}
                                    disabled={busy || locked || !preview.tracks_to_rewrite}
                                    title={
                                        preview.tracks_to_rewrite
                                            ? undefined
                                            : 'Nothing to rewrite — every track already points at this name.'
                                    }
                                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-mx-sm text-[12px] font-semibold bg-amber2 text-black hover:brightness-110 transition-all disabled:opacity-40"
                                >
                                    {busy ? (
                                        <Loader2 size={13} className="animate-spin" />
                                    ) : (
                                        <GitMerge size={13} />
                                    )}
                                    Merge {formatNumber(preview.tracks_to_rewrite)} tracks
                                </button>
                            </div>
                        </>
                    )}
                </div>
            </div>
        );
    };

    const renderRun = (run) => {
        const busy = revertingId === run.run_id;
        const locked = anyJob && !busy;
        const reverted = run.status === RUN_REVERTED;
        return (
            <div
                key={run.run_id}
                className="flex items-center gap-3 px-3 py-2.5 mb-1.5 rounded-xl bg-mx-card/40 border border-white/5"
            >
                <div className="min-w-0 flex-1">
                    <div className="text-[12.5px] text-ink-primary truncate">
                        <span className="font-semibold">{run.canonical || 'Artist merge'}</span>
                        {run.absorbing?.length > 0 && (
                            <span className="text-ink-muted font-mono">
                                {' '}
                                ← {run.absorbing.join(', ')}
                            </span>
                        )}
                    </div>
                    <div className="mt-0.5 flex items-center gap-2 text-[11px] text-ink-muted flex-wrap">
                        <span>{runTime(run.created_at)}</span>
                        <span className="font-mono">
                            {pluralise(run.tracks ?? run.mutation_count, 'row', 'rows')}
                        </span>
                        <span className="font-mono opacity-60">{run.run_id}</span>
                    </div>
                </div>
                <span
                    className={`px-2 py-[3px] rounded-mx-xs text-[10px] border whitespace-nowrap ${
                        STATUS_STYLE[run.status] ?? STATUS_STYLE.reverted
                    }`}
                >
                    {run.status}
                </span>
                <button
                    type="button"
                    onClick={() => runRevert(run)}
                    disabled={busy || locked || reverted}
                    title={
                        reverted ? 'Already reverted' : 'Replay this run backwards and restore it'
                    }
                    className="flex items-center gap-1.5 px-2.5 py-1 rounded-mx-sm text-[11px] bg-mx-card border border-line-subtle text-ink-primary hover:border-amber2/50 hover:text-amber2 transition-colors disabled:opacity-40 shrink-0"
                >
                    {busy ? (
                        <Loader2 size={12} className="animate-spin" />
                    ) : (
                        <RotateCcw size={12} />
                    )}
                    Revert
                </button>
            </div>
        );
    };

    return (
        <div
            className="fixed inset-0 z-[200] flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm"
            onMouseDown={(e) => {
                if (e.target === e.currentTarget && !applyingId && !revertingId) close();
            }}
        >
            <div className="w-full max-w-4xl max-h-[88vh] flex flex-col bg-mx-deepest border border-white/10 rounded-2xl shadow-2xl overflow-hidden">
                <div className="flex items-start justify-between gap-4 px-5 py-4 border-b border-white/5">
                    <div className="flex items-center gap-2.5 min-w-0">
                        <GitMerge size={18} className="text-amber2 shrink-0" />
                        <div className="min-w-0">
                            <h2 className="text-[15px] font-bold text-white">Merge artists</h2>
                            <p className="text-[11.5px] text-ink-muted mt-0.5">
                                Detection is automatic — a merge is never applied without this
                                confirm, and every run stays revertable.
                            </p>
                        </div>
                    </div>
                    <button
                        type="button"
                        onClick={close}
                        disabled={!!applyingId || !!revertingId}
                        aria-label="Close"
                        className="text-ink-secondary hover:text-white transition-colors disabled:opacity-40"
                    >
                        <X size={18} />
                    </button>
                </div>

                <div className="flex items-stretch px-4 border-b border-line-subtle">
                    <button
                        type="button"
                        onClick={() => setTab(TAB_GROUPS)}
                        className={tabClass(TAB_GROUPS)}
                    >
                        Duplicates
                        <span className="px-1.5 py-[1px] rounded-mx-xs text-[10px] font-mono bg-mx-card border border-line-subtle">
                            {loading ? '…' : candidates.length}
                        </span>
                    </button>
                    <button
                        type="button"
                        onClick={() => setTab(TAB_HISTORY)}
                        className={tabClass(TAB_HISTORY)}
                    >
                        <History size={13} />
                        History
                        {runs !== null && (
                            <span className="px-1.5 py-[1px] rounded-mx-xs text-[10px] font-mono bg-mx-card border border-line-subtle">
                                {runs.length}
                            </span>
                        )}
                    </button>
                </div>

                {blocked && (
                    <div className="px-4 pt-3">
                        <Callout icon={AlertTriangle} tone="warn" title="Rekordbox is open">
                            {blocked}
                        </Callout>
                    </div>
                )}

                {lastResult && tab === TAB_GROUPS && (
                    <div className="px-4 pt-3">
                        <Callout
                            icon={Undo2}
                            tone={lastResult.aborted ? 'warn' : 'plain'}
                            title={`Last run · ${lastResult.run_id}`}
                        >
                            {applySummary(lastResult)}{' '}
                            {(lastResult.files_skipped ?? []).length > 0 && (
                                <span className="block mt-1 font-mono text-[10.5px] text-ink-muted">
                                    {(lastResult.files_skipped ?? [])
                                        .slice(0, MAX_SKIPPED_SHOWN)
                                        .map((f) => `${f.path} (${f.reason})`)
                                        .join(' · ')}
                                </span>
                            )}
                            <button
                                type="button"
                                onClick={openHistory}
                                className="text-amber2 hover:underline"
                            >
                                Revert it in History
                            </button>
                            .
                        </Callout>
                    </div>
                )}

                <div className="flex-1 min-h-0 overflow-y-auto p-4">
                    {tab === TAB_GROUPS ? (
                        loading ? (
                            <div className="flex items-center justify-center gap-2 py-16 text-[12px] text-ink-muted">
                                <Loader2 size={16} className="animate-spin text-amber2" />
                                Scanning your artists for duplicate spellings…
                            </div>
                        ) : loadError ? (
                            <Callout icon={AlertTriangle} tone="warn" title="Nothing scanned">
                                {loadError}
                            </Callout>
                        ) : candidates.length === 0 ? (
                            <div className="py-12 text-center text-[12px] text-ink-muted">
                                No duplicate artist spellings found. Casing, punctuation, `&`/`and`,
                                whitespace and smart quotes are all folded — nothing in this library
                                collides.
                            </div>
                        ) : (
                            <>
                                {seedMiss && (
                                    <div className="mb-2.5 px-3 py-2 rounded-xl bg-mx-card/40 border border-white/5 text-[11.5px] text-ink-muted">
                                        “{seedMiss}” is spelled only one way in your library — no
                                        merge group for it. The other detected groups are below.
                                    </div>
                                )}
                                {candidates.map(renderGroup)}
                            </>
                        )
                    ) : runsLoading || runs === null ? (
                        <div className="flex items-center justify-center gap-2 py-16 text-[12px] text-ink-muted">
                            <Loader2 size={16} className="animate-spin text-amber2" />
                            Loading the merge journal…
                        </div>
                    ) : runs.length === 0 ? (
                        <div className="py-12 text-center text-[12px] text-ink-muted">
                            No merge has run yet. Every one that does lands here with its pre-image,
                            and can be replayed backwards from this list.
                        </div>
                    ) : (
                        runs.map(renderRun)
                    )}
                </div>
            </div>
        </div>
    );
};

export default MergeDialog;
