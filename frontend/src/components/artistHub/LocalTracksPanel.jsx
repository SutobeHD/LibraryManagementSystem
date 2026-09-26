import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactDOM from 'react-dom';
import { toast } from 'react-hot-toast';
import { Loader2, Plus, RotateCcw, Search, Tag, Undo2, UserX, X } from 'lucide-react';

import TrackTable from '../TrackTable';
import { ARTIST_ASSIGN_SEARCH_DEBOUNCE_MS } from '../../config/constants';
import { linksErrorMessage, searchAssignCandidates } from './artistLinksApi';
import {
    ASSIGNABLE_ROLES,
    LOCAL_FILTERS,
    LOCAL_ROLE_LABEL,
    filterLocalTracks,
    localFilterCount,
    localRoleTitle,
    localSummaryLine,
} from './linksCopy';
import { formatNumber, pluralise } from './mergeCopy';

/**
 * LocalTracksPanel — the "in your library" half of the artist page (owner refinement
 * 2026-09-26): every track that is theirs, grouped by role — their tracks, their
 * remixes of other people's tracks, remixes of theirs by others, features — and why
 * each one counts (Artist field, Remixer field, a credit in the title, or you).
 *
 * Nothing is recounted here: the counts on the filters come from the payload
 * (`app/artist_store/attribution.py::local_tracks`), the same answer the Rekordbox
 * projection mirrors into the artist's playlist. Right-click a row to re-role it or to
 * take it away from the artist; "Add tracks" searches the library for the rest.
 */

const ROLE_COLUMN_WIDTH = '118px';

// The half-width panel fits these; the header menu adds more, saved under its own key.
const ARTIST_TABLE_COLUMNS_KEY = 'artist_track_table_columns';
const ARTIST_TABLE_COLUMNS = ['index', 'preview', 'Title', 'Artist', 'BPM', 'Key', 'TotalTime'];

const trackIdOf = (t) => t?.id ?? t?.ID;

const RoleBadge = ({ track }) => {
    const role = track?.artist_role;
    if (!role) return null;
    const manual = role.source === 'manual';
    return (
        <span
            title={localRoleTitle(track)}
            className={`inline-block max-w-full truncate px-1.5 py-[1px] rounded-mx-xs text-[10px] border ${
                manual
                    ? 'text-amber2 bg-amber2/10 border-amber2/40'
                    : role.confidence === 'high'
                      ? 'text-ink-secondary bg-mx-card border-line-subtle'
                      : 'text-ink-muted border-dashed border-line-subtle'
            }`}
        >
            {LOCAL_ROLE_LABEL[role.role] || role.role}
        </span>
    );
};

const ROLE_COLUMNS = [
    {
        id: 'artist_role',
        label: 'Role',
        width: ROLE_COLUMN_WIDTH,
        render: (track) => <RoleBadge track={track} />,
    },
];

const FilterChip = ({ active, onClick, children, title }) => (
    <button
        type="button"
        title={title}
        onClick={onClick}
        className={`px-2 py-[3px] rounded-mx-xs text-[10px] border transition-colors ${
            active
                ? 'bg-amber2/10 text-amber2 border-amber2/40 font-semibold'
                : 'bg-mx-input text-ink-muted border-line-subtle hover:text-ink-secondary'
        }`}
    >
        {children}
    </button>
);

/** "Add tracks": search the library, add rows under a role. Stays open for several. */
const AddTracksDialog = ({ artist, onAssign, onClose }) => {
    const [query, setQuery] = useState('');
    const [role, setRole] = useState(ASSIGNABLE_ROLES[0]);
    const [result, setResult] = useState(null);
    const [loading, setLoading] = useState(false);
    const [pending, setPending] = useState(null);
    const seqRef = useRef(0);
    const inputRef = useRef(null);

    useEffect(() => {
        const handle = setTimeout(() => inputRef.current?.focus(), 0);
        return () => clearTimeout(handle);
    }, []);

    useEffect(() => {
        const text = query.trim();
        const seq = (seqRef.current += 1);
        if (!text) {
            setResult(null);
            setLoading(false);
            return undefined;
        }
        setLoading(true);
        const handle = setTimeout(async () => {
            try {
                const payload = await searchAssignCandidates(artist.collection_id, text);
                if (seqRef.current === seq) setResult(payload);
            } catch (e) {
                if (seqRef.current !== seq) return;
                console.error('[LocalTracksPanel] library search failed', e);
                toast.error(linksErrorMessage(e, 'Could not search the library.'));
            } finally {
                if (seqRef.current === seq) setLoading(false);
            }
        }, ARTIST_ASSIGN_SEARCH_DEBOUNCE_MS);
        return () => clearTimeout(handle);
    }, [artist.collection_id, query]);

    const add = useCallback(
        async (row) => {
            setPending(row.id);
            const updated = await onAssign(row.id, { action: 'assign', role });
            setPending(null);
            if (!updated) return;
            setResult((current) =>
                current
                    ? {
                          ...current,
                          tracks: current.tracks.map((t) =>
                              t.id === row.id
                                  ? { ...t, excluded: false, artist_role: updated.artist_role }
                                  : t
                          ),
                      }
                    : current
            );
        },
        [onAssign, role]
    );

    return ReactDOM.createPortal(
        <div
            className="fixed inset-0 z-[300] flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in"
            onMouseDown={(e) => {
                if (e.target === e.currentTarget) onClose();
            }}
            onKeyDown={(e) => {
                if (e.key === 'Escape') onClose();
            }}
        >
            <div className="bg-mx-shell border border-white/10 rounded-xl p-5 w-[40rem] max-w-[94vw] shadow-2xl">
                <div className="flex justify-between items-start gap-3 mb-3">
                    <div>
                        <h3 className="text-lg font-bold text-white">
                            Add tracks to {artist.name}
                        </h3>
                        <p className="text-[12px] text-ink-muted mt-0.5">
                            For tracks their credits do not name — a white label, an edit tagged
                            with the uploader. They land in the artist page and their Rekordbox
                            playlist.
                        </p>
                    </div>
                    <button
                        type="button"
                        onClick={onClose}
                        className="text-ink-secondary hover:text-white"
                        aria-label="Close"
                    >
                        <X size={20} />
                    </button>
                </div>

                <div className="flex items-center gap-2 mb-2">
                    <div className="relative flex-1">
                        <Search
                            size={14}
                            className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted"
                        />
                        <input
                            ref={inputRef}
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                            placeholder="Search title, artist or remixer…"
                            className="input-glass w-full pl-9 text-sm"
                        />
                    </div>
                    <select
                        value={role}
                        onChange={(e) => setRole(e.target.value)}
                        className="input-glass text-[12px] py-1.5"
                        title="The role new rows are added with"
                    >
                        {ASSIGNABLE_ROLES.map((value) => (
                            <option key={value} value={value}>
                                as {LOCAL_ROLE_LABEL[value]}
                            </option>
                        ))}
                    </select>
                </div>

                <div className="h-72 overflow-y-auto rounded-mx-sm border border-line-subtle bg-mx-input/60">
                    {loading && !result ? (
                        <div className="flex items-center justify-center gap-2 h-full text-[12px] text-ink-muted">
                            <Loader2 size={14} className="animate-spin text-amber2" /> Searching…
                        </div>
                    ) : !result ? (
                        <div className="flex items-center justify-center h-full text-[12px] text-ink-muted">
                            Type to search your library.
                        </div>
                    ) : result.tracks.length === 0 ? (
                        <div className="flex items-center justify-center h-full text-[12px] text-ink-muted">
                            Nothing in the library matches that.
                        </div>
                    ) : (
                        <>
                            {result.tracks.map((row) => (
                                <div
                                    key={row.id}
                                    className="flex items-center gap-2 px-3 py-1.5 text-[12px] border-b border-white/5"
                                >
                                    <div className="flex-1 min-w-0">
                                        <div className="text-ink-primary truncate">
                                            {row.Title || '—'}
                                        </div>
                                        <div className="text-[11px] text-ink-muted truncate">
                                            {row.Artist || '—'}
                                            {row.Remixer ? ` · remixer ${row.Remixer}` : ''}
                                        </div>
                                    </div>
                                    {row.artist_role ? (
                                        <RoleBadge track={row} />
                                    ) : row.excluded ? (
                                        <span className="text-[10px] text-bad">excluded</span>
                                    ) : null}
                                    <button
                                        type="button"
                                        onClick={() => add(row)}
                                        disabled={pending === row.id}
                                        className="flex items-center gap-1 px-2 py-1 rounded-mx-sm text-[11px] border bg-mx-card border-line-subtle text-ink-primary hover:border-amber2/50 hover:text-amber2 transition-colors disabled:opacity-40"
                                    >
                                        {pending === row.id ? (
                                            <Loader2 size={11} className="animate-spin" />
                                        ) : (
                                            <Plus size={11} />
                                        )}
                                        {row.artist_role ? 'Set role' : 'Add'}
                                    </button>
                                </div>
                            ))}
                            {result.total > result.tracks.length && (
                                <div className="px-3 py-2 text-[11px] text-ink-muted">
                                    Showing {formatNumber(result.tracks.length)} of{' '}
                                    {formatNumber(result.total)} — narrow the search.
                                </div>
                            )}
                        </>
                    )}
                </div>
            </div>
        </div>,
        document.body
    );
};

const ExcludedList = ({ rows, onRestore, busyId }) => (
    <div className="h-full overflow-y-auto p-3">
        {rows.map((row) => (
            <div
                key={row.track_id}
                className="flex items-center gap-3 px-3 py-2 mb-1.5 rounded-xl bg-mx-card/40 border border-white/5"
            >
                <div className="flex-1 min-w-0">
                    <div className="text-[13px] text-ink-primary truncate">{row.title || '—'}</div>
                    <div className="text-[11.5px] text-ink-muted truncate">
                        {row.artist || '—'}
                        {row.would_be
                            ? ` · would count as ${LOCAL_ROLE_LABEL[row.would_be.role] || row.would_be.role}`
                            : ''}
                    </div>
                </div>
                <button
                    type="button"
                    onClick={() => onRestore(row.track_id)}
                    disabled={busyId === row.track_id}
                    className="flex items-center gap-1.5 px-2.5 py-1 rounded-mx-sm text-[11px] border bg-mx-card border-line-subtle text-ink-primary hover:border-amber2/50 hover:text-amber2 transition-colors disabled:opacity-40"
                >
                    <Undo2 size={12} /> Restore
                </button>
            </div>
        ))}
    </div>
);

const LocalTracksPanel = ({
    artist,
    local,
    loading,
    trackFilter,
    onSelectTrack,
    onEditTrack,
    onPlayTrack,
    onAssign,
}) => {
    const [filter, setFilter] = useState('all');
    const [showExcluded, setShowExcluded] = useState(false);
    const [addOpen, setAddOpen] = useState(false);
    const [busyId, setBusyId] = useState(null);

    useEffect(() => {
        setFilter('all');
        setShowExcluded(false);
        setAddOpen(false);
    }, [artist?.collection_id]);

    const allTracks = useMemo(() => local?.tracks ?? [], [local]);
    const excluded = useMemo(() => local?.excluded ?? [], [local]);

    const visible = useMemo(() => {
        const byRole = filterLocalTracks(allTracks, filter);
        const q = String(trackFilter || '').toLowerCase();
        if (!q) return byRole;
        return byRole.filter(
            (t) =>
                (t.Title && t.Title.toLowerCase().includes(q)) ||
                (t.Artist && t.Artist.toLowerCase().includes(q)) ||
                (t.Remixer && t.Remixer.toLowerCase().includes(q)) ||
                (t.Album && t.Album.toLowerCase().includes(q))
        );
    }, [allTracks, filter, trackFilter]);

    useEffect(() => {
        if (showExcluded && excluded.length === 0) setShowExcluded(false);
    }, [excluded.length, showExcluded]);

    const act = useCallback(
        async (trackId, change) => {
            setBusyId(trackId);
            try {
                return await onAssign(trackId, change);
            } finally {
                setBusyId(null);
            }
        },
        [onAssign]
    );

    const contextActions = useCallback(
        (track) => {
            const role = track?.artist_role;
            const id = trackIdOf(track);
            const items = ASSIGNABLE_ROLES.filter(
                (value) => !(role?.source === 'manual' && role?.role === value)
            ).map((value) => ({
                id: `role-${value}`,
                label: `Rolle: ${LOCAL_ROLE_LABEL[value]}`,
                icon: Tag,
                onSelect: () => act(id, { action: 'assign', role: value }),
            }));
            if (role?.source === 'manual') {
                items.push({
                    id: 'clear',
                    label: 'Zuordnung zurücksetzen (automatisch)',
                    icon: RotateCcw,
                    onSelect: () => act(id, { action: 'clear' }),
                });
            }
            items.push({
                id: 'exclude',
                label: `Nicht von ${artist?.name || 'diesem Artist'}`,
                icon: UserX,
                danger: true,
                onSelect: () => act(id, { action: 'exclude' }),
            });
            return items;
        },
        [act, artist?.name]
    );

    const total = localFilterCount(local, 'all');
    const summary = localSummaryLine(local);
    const aliases = (local?.library_names?.length || artist?.library_names?.length || 1) - 1;

    return (
        <div className="bg-mx-panel border border-line-subtle rounded-xl flex flex-col min-h-0 overflow-hidden">
            <div className="flex items-center gap-2 px-3.5 py-2.5 border-b border-line-subtle">
                <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-ink-muted">
                    In your library · {formatNumber(total)}
                </span>
                <span className="flex-1" />
                {aliases > 0 && (
                    <span
                        title={(local?.library_names || artist?.library_names || []).join(' · ')}
                        className="px-2 py-[3px] rounded-mx-xs text-[10px] border text-ink-muted bg-mx-card border-line-subtle"
                    >
                        {pluralise(aliases, 'alias', 'aliases')} merged
                    </span>
                )}
                <button
                    type="button"
                    onClick={() => setAddOpen(true)}
                    disabled={!local || local.library_loaded === false}
                    title="Search the library for tracks their credits do not name"
                    className="flex items-center gap-1.5 px-2.5 py-1 rounded-mx-sm text-[11px] border bg-mx-card border-line-subtle text-ink-primary hover:border-amber2/50 hover:text-amber2 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                >
                    <Plus size={12} /> Add tracks
                </button>
            </div>

            <div className="flex flex-wrap gap-1 px-3.5 py-2 border-b border-line-subtle">
                {LOCAL_FILTERS.map((entry) => {
                    const count = localFilterCount(local, entry.key);
                    if (entry.key !== 'all' && count === 0) return null;
                    return (
                        <FilterChip
                            key={entry.key}
                            active={!showExcluded && filter === entry.key}
                            onClick={() => {
                                setShowExcluded(false);
                                setFilter(entry.key);
                            }}
                        >
                            {entry.label} ({formatNumber(count)})
                        </FilterChip>
                    );
                })}
                {excluded.length > 0 && (
                    <FilterChip
                        active={showExcluded}
                        onClick={() => setShowExcluded((v) => !v)}
                        title="Tracks you took away from this artist"
                    >
                        Excluded ({formatNumber(excluded.length)})
                    </FilterChip>
                )}
            </div>
            {summary && (
                <div className="px-3.5 py-1.5 border-b border-line-subtle text-[11px] text-ink-muted">
                    {summary}
                </div>
            )}

            <div className="flex-1 min-h-0">
                {loading && !local ? (
                    <div className="flex items-center justify-center gap-3 py-16 text-ink-muted text-[12px]">
                        <Loader2 size={18} className="animate-spin text-amber2" />
                        Loading tracks…
                    </div>
                ) : showExcluded ? (
                    <ExcludedList
                        rows={excluded}
                        busyId={busyId}
                        onRestore={(id) => act(id, { action: 'clear' })}
                    />
                ) : visible.length === 0 ? (
                    <div className="px-4 py-8 text-center text-[12px] text-ink-muted leading-relaxed">
                        {local?.library_loaded === false
                            ? 'Load a library to see which tracks are theirs.'
                            : total === 0
                              ? 'No track in the loaded library names this artist — as artist, remixer or feature. Use "Add tracks" for the ones their credits miss.'
                              : 'No track matches this filter.'}
                    </div>
                ) : (
                    <TrackTable
                        tracks={visible}
                        onSelectTrack={onSelectTrack}
                        onEditTrack={onEditTrack}
                        onPlay={onPlayTrack}
                        playlistId={`ARTISTS_${artist.collection_id}`}
                        variant="embedded"
                        customColumns={ROLE_COLUMNS}
                        contextActions={contextActions}
                        columnsStorageKey={ARTIST_TABLE_COLUMNS_KEY}
                        defaultColumnIds={ARTIST_TABLE_COLUMNS}
                    />
                )}
            </div>

            {addOpen && (
                <AddTracksDialog artist={artist} onAssign={act} onClose={() => setAddOpen(false)} />
            )}
        </div>
    );
};

export default LocalTracksPanel;
