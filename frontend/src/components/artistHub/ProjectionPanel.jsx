import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'react-hot-toast';
import { AlertTriangle, FolderTree, Loader2, RefreshCw } from 'lucide-react';

import {
    errorMessage,
    fetchProjectionStatus,
    isRekordboxRunning,
    syncProjection,
} from './artistHubApi';
import { formatNumber, pluralise } from './mergeCopy';

/**
 * ProjectionPanel — one compact row for the `Artists` folder inside Rekordbox:
 * what is projected right now, and the button that brings it up to date. The
 * details sit in the row's tooltip; the run's delta goes to the toast.
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

    const pending = Number(status?.pending) || 0;
    const meta = status
        ? `${folderName} · ${formatNumber(status?.projected)}/${formatNumber(status?.favourites)}${
              synced ? ` · ${relativeTime(synced)}` : ' · never synced'
          }`
        : '';
    const metaTitle = status
        ? [
              `Folder "${folderName}" — ${folderState}.`,
              `${formatNumber(status?.projected)} of ${pluralise(status?.favourites, 'favourite', 'favourites')} have a playlist${
                  pending ? `, ${formatNumber(pending)} pending` : ''
              }.`,
              `Last synced: ${synced ? relativeTime(synced) : 'never'}.`,
              report ? `Last run: ${deltaLine(report)}.` : '',
          ]
              .filter(Boolean)
              .join('\n')
        : '';

    return (
        <div className="px-3 py-2">
            <div className="flex items-center gap-2 min-w-0">
                <FolderTree size={13} className="text-amber2 shrink-0" />
                <span className="text-[11.5px] font-semibold text-ink-secondary shrink-0">
                    Rekordbox folder
                </span>
                <span
                    title={metaTitle || unavailable}
                    className="flex-1 min-w-0 truncate text-[11px] text-ink-muted font-mono"
                >
                    {loading && !status ? (
                        <Loader2 size={11} className="inline animate-spin text-amber2" />
                    ) : unavailable ? (
                        'status unavailable'
                    ) : (
                        <>
                            {meta}
                            {pending > 0 && (
                                <span className="text-amber2">
                                    {' '}
                                    · {formatNumber(pending)} pending
                                </span>
                            )}
                        </>
                    )}
                </span>
                <span
                    title={
                        running
                            ? 'Rekordbox is open — writing the folder needs it closed.'
                            : 'Rekordbox is closed — the folder can be written.'
                    }
                    className={`w-1.5 h-1.5 rounded-full shrink-0 ${running ? 'bg-amber2' : 'bg-ok'}`}
                />
                <button
                    type="button"
                    onClick={runSync}
                    disabled={syncing || !!unavailable}
                    title={
                        running
                            ? 'Close Rekordbox first — the folder is written into master.db.'
                            : 'Write one playlist per favourite into the Artists folder. Re-running updates in place — no duplicate folders or entries.'
                    }
                    className="flex items-center gap-1 px-2 py-0.5 rounded-mx-sm text-[11px] bg-mx-card border border-line-subtle text-ink-primary hover:border-amber2/50 hover:text-amber2 transition-colors disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
                >
                    {syncing ? (
                        <Loader2 size={11} className="animate-spin" />
                    ) : (
                        <RefreshCw size={11} />
                    )}
                    Write
                </button>
            </div>
            {blocked && (
                <div className="mt-1 flex items-start gap-1.5 text-[11px] text-ink-secondary">
                    <AlertTriangle size={12} className="mt-[1px] shrink-0 text-amber2" />
                    <span className="min-w-0">{blocked}</span>
                </div>
            )}
        </div>
    );
};

export default ProjectionPanel;
