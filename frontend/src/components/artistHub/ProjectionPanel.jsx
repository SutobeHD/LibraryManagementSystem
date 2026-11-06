import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'react-hot-toast';
import { AlertTriangle, Clock, FolderTree, Loader2, RefreshCw } from 'lucide-react';

import {
    errorMessage,
    fetchProjectionStatus,
    isRekordboxRunning,
    syncProjection,
} from './artistHubApi';
import { formatNumber, pluralise } from './mergeCopy';

/**
 * ProjectionPanel — the `Artists` folder inside Rekordbox: what is projected
 * right now, and the button that brings it up to date.
 *
 * Two things it must not do: claim a sync happened when the backend refused
 * (Rekordbox open ⇒ 409, rendered as a sentence, not as a raw error), and report
 * "synced ✓" without the delta — a projection run that created nothing and moved
 * no tracks looks identical to a broken one unless the numbers are shown.
 *
 * Status/report shapes: `app/artist_store/projection.py::status` / `::sync`.
 */

const HOUR_MS = 3_600_000;
const DAY_MS = 24 * HOUR_MS;
const MINUTE_MS = 60_000;

const relativeTime = (iso) => {
    if (!iso) return null;
    const parsed = new Date(iso);
    if (Number.isNaN(parsed.getTime())) return String(iso);
    const delta = Date.now() - parsed.getTime();
    if (delta < MINUTE_MS) return 'just now';
    if (delta < HOUR_MS) return `${Math.round(delta / MINUTE_MS)} min ago`;
    if (delta < DAY_MS) return `${Math.round(delta / HOUR_MS)} h ago`;
    return parsed.toLocaleDateString();
};

const lastSyncedAt = (status) => {
    const stamps = (status?.artists ?? [])
        .map((a) => a.last_projected_at)
        .filter(Boolean)
        .sort();
    return stamps.length ? stamps[stamps.length - 1] : null;
};

/** The delta line. Built from the report only — never a generic "done". */
const deltaLine = (report) => {
    if (!report) return '';
    const parts = [];
    const created = Number(report.playlists_created) || 0;
    const adopted = Number(report.playlists_adopted) || 0;
    const updated = Number(report.playlists_updated) || 0;
    const added = Number(report.tracks_added) || 0;
    const removed = Number(report.tracks_removed) || 0;
    if (created) parts.push(`+${formatNumber(created)} playlist${created === 1 ? '' : 's'}`);
    if (adopted) parts.push(`${formatNumber(adopted)} adopted`);
    if (updated) parts.push(`${formatNumber(updated)} updated`);
    if (added) parts.push(`+${formatNumber(added)} tracks`);
    if (removed) parts.push(`−${formatNumber(removed)} tracks`);
    if (parts.length === 0) parts.push('already up to date — nothing to write');
    return parts.join(' · ');
};

const KeyValue = ({ label, children }) => (
    <div className="flex items-baseline justify-between gap-3 py-[3px] text-[11.5px]">
        <span className="text-ink-muted shrink-0">{label}</span>
        <span className="text-ink-secondary text-right min-w-0 truncate">{children}</span>
    </div>
);

const ProjectionPanel = ({ refreshToken }) => {
    const [status, setStatus] = useState(null);
    const [loading, setLoading] = useState(true);
    const [unavailable, setUnavailable] = useState('');
    const [syncing, setSyncing] = useState(false);
    const [report, setReport] = useState(null);
    const [blocked, setBlocked] = useState('');

    const closedRef = useRef(false);
    useEffect(
        () => () => {
            closedRef.current = true;
        },
        []
    );

    const loadStatus = useCallback(async () => {
        setLoading(true);
        try {
            const data = await fetchProjectionStatus();
            if (closedRef.current) return;
            setStatus(data);
            setUnavailable('');
        } catch (e) {
            // Ambient panel — a failure here degrades to a line, never a toast.
            console.error('[ProjectionPanel] failed to load the projection status', e);
            if (closedRef.current) return;
            setStatus(null);
            setUnavailable(errorMessage(e, 'The Rekordbox projection status is unavailable.'));
        } finally {
            if (!closedRef.current) setLoading(false);
        }
    }, []);

    useEffect(() => {
        loadStatus();
    }, [loadStatus, refreshToken]);

    const runSync = useCallback(async () => {
        setSyncing(true);
        setBlocked('');
        try {
            const data = await syncProjection({ isCancelled: () => closedRef.current });
            if (closedRef.current || !data) return;
            setReport(data);
            const summary = deltaLine(data);
            if (data?.aborted) {
                toast.error(`Sync stopped before it finished — ${summary}`);
            } else if ((data?.errors ?? []).length > 0) {
                toast.error(`${summary} · ${pluralise(data.errors.length, 'error', 'errors')}`);
            } else {
                toast.success(`Rekordbox folder synced — ${summary}`);
            }
            await loadStatus();
        } catch (e) {
            console.error('[ProjectionPanel] projection sync failed', e);
            if (closedRef.current) return;
            const message = errorMessage(e, 'The Rekordbox sync failed.');
            setBlocked(message);
            // The 409 is a plain instruction, not an error dump.
            if (isRekordboxRunning(e)) toast.error(message);
            else toast.error(`Sync failed — ${message}`);
        } finally {
            if (!closedRef.current) setSyncing(false);
        }
    }, [loadStatus]);

    const running = !!status?.rekordbox_running;
    const folderName = status?.folder_name || 'Artists';
    const synced = lastSyncedAt(status);
    const folderState = !status?.folder_id
        ? 'not created yet — the first sync creates it'
        : status.folder_exists
          ? 'in your collection'
          : 'missing in Rekordbox — the next sync re-creates it';

    return (
        <div className="bg-mx-panel border border-line-subtle rounded-xl shrink-0 overflow-hidden">
            <div className="flex items-center gap-2 px-3.5 py-2.5 border-b border-line-subtle">
                <FolderTree size={14} className="text-amber2 shrink-0" />
                <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-ink-muted">
                    Rekordbox folder
                </span>
                <div className="flex-1" />
                <span
                    className={`flex items-center gap-1.5 px-2 py-[3px] rounded-mx-xs text-[10px] border whitespace-nowrap ${
                        running
                            ? 'text-amber2 bg-amber2/10 border-amber2/40'
                            : 'text-ok bg-ok/[0.07] border-ok/30'
                    }`}
                >
                    <span
                        className={`w-1.5 h-1.5 rounded-full ${running ? 'bg-amber2' : 'bg-ok'}`}
                    />
                    {running ? 'Rekordbox open' : 'Rekordbox closed'}
                </span>
            </div>

            <div className="p-3.5">
                {loading && !status ? (
                    <div className="flex items-center gap-2 py-2 text-[11.5px] text-ink-muted">
                        <Loader2 size={13} className="animate-spin text-amber2" />
                        Reading the projection state…
                    </div>
                ) : unavailable ? (
                    <p className="text-[11.5px] text-ink-muted leading-relaxed">{unavailable}</p>
                ) : (
                    <>
                        <KeyValue label="Folder">
                            <span className="font-mono text-ink-primary">{folderName}</span> ·{' '}
                            {folderState}
                        </KeyValue>
                        <KeyValue label="Artist playlists">
                            {formatNumber(status?.projected)} of{' '}
                            {pluralise(status?.favourites, 'favourite', 'favourites')}
                            {status?.pending > 0 && (
                                <span className="text-amber2">
                                    {' '}
                                    · {formatNumber(status.pending)} pending
                                </span>
                            )}
                        </KeyValue>
                        <KeyValue label="Last synced">
                            {synced ? (
                                <span className="inline-flex items-center gap-1.5">
                                    <Clock size={11} className="text-ink-muted" />
                                    {relativeTime(synced)}
                                </span>
                            ) : (
                                'never'
                            )}
                        </KeyValue>

                        <button
                            type="button"
                            onClick={runSync}
                            disabled={syncing}
                            className="mt-3 w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-mx-sm text-[12px] font-semibold bg-amber2 text-black hover:brightness-110 transition-all disabled:opacity-40"
                        >
                            {syncing ? (
                                <Loader2 size={13} className="animate-spin" />
                            ) : (
                                <RefreshCw size={13} />
                            )}
                            {syncing ? 'Syncing…' : 'Sync now'}
                        </button>

                        {report && !blocked && (
                            <div className="mt-2.5 px-3 py-2 rounded-xl bg-mx-card/50 border border-white/5">
                                <div className="text-[11.5px] text-ink-primary">
                                    {deltaLine(report)}
                                </div>
                                <div className="mt-0.5 text-[10.5px] text-ink-muted">
                                    {report.adopted
                                        ? `Folder adopted, not recreated · `
                                        : report.created
                                          ? `Folder created · `
                                          : ''}
                                    {pluralise(report.artists, 'artist', 'artists')} ·{' '}
                                    {Number(report.elapsed_s || 0).toFixed(1)} s
                                    {(report.skipped ?? []).length > 0 &&
                                        ` · ${formatNumber((report.skipped ?? []).length)} skipped`}
                                    {(report.errors ?? []).length > 0 &&
                                        ` · ${formatNumber((report.errors ?? []).length)} failed`}
                                </div>
                            </div>
                        )}

                        {blocked && (
                            <div className="mt-2.5 flex gap-2 px-3 py-2 rounded-xl bg-amber2/[0.07] border border-amber2/30">
                                <AlertTriangle
                                    size={14}
                                    className="mt-[1px] shrink-0 text-amber2"
                                />
                                <p className="text-[11.5px] text-ink-secondary leading-relaxed">
                                    {blocked}
                                </p>
                            </div>
                        )}
                    </>
                )}
            </div>

            <div className="border-t border-line-subtle px-3.5 py-2.5 text-[11px] text-ink-muted leading-relaxed">
                One flat folder, one playlist per favourite — what the CDJ reads. Re-running the
                sync updates in place: no duplicate folders, no duplicate entries. Writing needs
                Rekordbox closed.
            </div>
        </div>
    );
};

export default ProjectionPanel;
