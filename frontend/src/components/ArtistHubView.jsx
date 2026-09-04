import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'react-hot-toast';
import {
    ArrowLeft,
    Cloud,
    Loader2,
    Plus,
    RefreshCw,
    RotateCw,
    Search,
    Star,
    User,
} from 'lucide-react';
import api from '../api/api';
import TrackTable from './TrackTable';
import { confirmModal } from './ConfirmModal';

/**
 * ArtistHubView — the Artists tab. Left: curated favourites (link state, sync
 * mode, per-artist Update). Right: suggestions — the Tier-1 local backlog plus
 * the SoundCloud discovery tab.
 *
 * Milestone boundary: everything SoundCloud (per-artist Update, Update all,
 * discovery) is M2 of `docs/research/implement/inprogress_library-artist-hub.md`
 * and is NOT built. Those controls render disabled with the reason spelled out
 * rather than hidden or stubbed, so the view never implies a sync happened.
 */

const SYNC_MODES = [
    { id: 'auto', label: 'Auto' },
    { id: 'review', label: 'Review' },
    { id: 'off', label: 'Off' },
];

const SC_PENDING_REASON =
    'SoundCloud sync is not built yet — this arrives in a later step of the artist-hub plan.';

const MAX_INITIALS = 2;

const initialsOf = (name) =>
    String(name || '?')
        .split(/\s+/)
        .filter(Boolean)
        .slice(0, MAX_INITIALS)
        .map((part) => part[0].toUpperCase())
        .join('') || '?';

const artworkUrl = (path) =>
    `${api.defaults.baseURL || ''}/api/artwork?path=${encodeURIComponent(path)}`;

const ArtistAvatar = ({ name, artwork, small = false }) => {
    const box = small ? 'w-8 h-8 text-[10px]' : 'w-10 h-10 text-[12px]';
    return (
        <div
            className={`${box} rounded-full bg-mx-shell border border-white/5 flex items-center justify-center overflow-hidden shrink-0 font-bold text-ink-secondary`}
        >
            {artwork ? (
                <img
                    src={artworkUrl(artwork)}
                    alt={name}
                    className="w-full h-full object-cover"
                    loading="lazy"
                    onError={(e) => {
                        e.target.style.display = 'none';
                    }}
                />
            ) : (
                initialsOf(name)
            )}
        </div>
    );
};

const ScLinkChip = ({ linked }) =>
    linked ? (
        <span className="flex items-center gap-1.5 px-2 py-[3px] rounded-mx-xs text-[10px] text-ok bg-ok/[0.07] border border-ok/30 whitespace-nowrap">
            <span className="w-1.5 h-1.5 rounded-full bg-ok" />
            SC linked
        </span>
    ) : (
        <span className="flex items-center gap-1.5 px-2 py-[3px] rounded-mx-xs text-[10px] text-ink-muted bg-mx-card border border-line-subtle whitespace-nowrap">
            <span className="w-1.5 h-1.5 rounded-full bg-ink-placeholder" />
            not linked
        </span>
    );

const SyncModeControl = ({ value, onChange }) => (
    <div className="inline-flex rounded-mx-sm overflow-hidden border border-line-subtle bg-mx-input">
        {SYNC_MODES.map((m) => {
            const on = (value || 'off') === m.id;
            return (
                <button
                    key={m.id}
                    type="button"
                    title={`Sync mode: ${m.label}`}
                    onClick={(e) => {
                        e.stopPropagation();
                        onChange(m.id);
                    }}
                    className={`px-2 py-[3px] text-[10px] border-r border-line-subtle last:border-r-0 transition-colors ${
                        on
                            ? 'bg-amber2/10 text-amber2 font-semibold'
                            : 'text-ink-muted hover:text-ink-secondary hover:bg-mx-hover'
                    }`}
                >
                    {m.label}
                </button>
            );
        })}
    </div>
);

const PanelHead = ({ label, right }) => (
    <div className="flex items-center gap-2 px-3.5 py-2.5 border-b border-line-subtle">
        <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-ink-muted">
            {label}
        </span>
        <div className="flex-1" />
        {right}
    </div>
);

const EmptyHint = ({ children }) => (
    <div className="px-3 py-8 text-center text-[12px] text-ink-muted">{children}</div>
);

const HUB_SEARCH_DEBOUNCE_MS = 250;

const ArtistHubView = ({ active, onSelectTrack, onEditTrack, onPlayTrack, libraryStatus }) => {
    const [favourites, setFavourites] = useState([]);
    const [backlog, setBacklog] = useState([]);
    const [backlogTotal, setBacklogTotal] = useState(0);
    const [isLoading, setIsLoading] = useState(false);
    const [hubRequested, setHubRequested] = useState(false);
    const [searchTerm, setSearchTerm] = useState('');
    const [trackFilter, setTrackFilter] = useState('');
    const [selected, setSelected] = useState(null);
    const [tracks, setTracks] = useState([]);
    const [tracksLoading, setTracksLoading] = useState(false);
    const [busyId, setBusyId] = useState(null);

    // name → library artist id (`art_N`). The ids are list indexes rebuilt on
    // every library load, so this cache is dropped whenever the library reloads.
    const libraryIndexRef = useRef(null);

    const loadHub = useCallback(async (query = '') => {
        setIsLoading(true);
        try {
            // The backlog is truncated server-side. Filtering only the rows we already
            // hold would silently hide every artist ranked below the limit, so the
            // search term goes to the server and is applied before truncation.
            const res = await api.get('/api/artists/hub', { params: query ? { q: query } : {} });
            setFavourites(res.data?.favourites ?? []);
            setBacklog(res.data?.backlog ?? []);
            setBacklogTotal(res.data?.backlog_total ?? (res.data?.backlog ?? []).length);
        } catch (e) {
            console.error('[ArtistHub] failed to load the hub', e);
            toast.error('Failed to load the artist hub');
        } finally {
            setIsLoading(false);
        }
    }, []);

    useEffect(() => {
        libraryIndexRef.current = null;
        setSelected(null);
        setTracks([]);
        setHubRequested(false);
    }, [libraryStatus?.loaded]);

    // The view stays mounted behind the other library tabs, so the fetch waits
    // for the tab to actually be shown instead of firing on every app boot.
    useEffect(() => {
        if (!active || hubRequested) return;
        setHubRequested(true);
        loadHub();
    }, [active, hubRequested, loadHub]);

    // Re-query the server as the search term changes, debounced so typing does not
    // fire a request per keystroke.
    useEffect(() => {
        if (!active || !hubRequested) return undefined;
        const handle = setTimeout(() => loadHub(searchTerm.trim()), HUB_SEARCH_DEBOUNCE_MS);
        return () => clearTimeout(handle);
    }, [active, hubRequested, searchTerm, loadHub]);

    const libraryArtistIndex = useCallback(async () => {
        if (libraryIndexRef.current) return libraryIndexRef.current;
        const res = await api.get('/api/artists');
        const index = new Map();
        (res.data ?? []).forEach((a) => {
            if (a?.name) index.set(String(a.name).toLowerCase(), a.id);
        });
        libraryIndexRef.current = index;
        return index;
    }, []);

    // Drill-in keeps the old behaviour: the artist's local tracks in the shared
    // TrackTable. A hub row can fold several library spellings into one
    // collection, so every variant is fetched and the results de-duplicated.
    const openArtist = useCallback(
        async (row) => {
            setSelected(row);
            setTracks([]);
            setTrackFilter('');
            setTracksLoading(true);
            try {
                const index = await libraryArtistIndex();
                const names = row.library_names?.length ? row.library_names : [row.name];
                const ids = [
                    ...new Set(
                        names.map((n) => index.get(String(n).toLowerCase())).filter(Boolean)
                    ),
                ];
                const responses = await Promise.all(
                    ids.map((id) => api.get(`/api/artist/${encodeURIComponent(id)}/tracks`))
                );
                const seen = new Set();
                const merged = [];
                responses.forEach((res) => {
                    (res.data ?? []).forEach((t) => {
                        const key = t.id ?? t.ID;
                        if (key != null) {
                            if (seen.has(key)) return;
                            seen.add(key);
                        }
                        merged.push(t);
                    });
                });
                setTracks(merged);
            } catch (e) {
                console.error('[ArtistHub] failed to load artist tracks', e);
                toast.error(`Failed to load tracks for ${row.name}`);
            } finally {
                setTracksLoading(false);
            }
        },
        [libraryArtistIndex]
    );

    const addFavourite = useCallback(
        async (row) => {
            setBusyId(row.collection_id);
            try {
                await api.post('/api/artists/favourites', { name: row.name });
                toast.success(`${row.name} added to favourites`);
                await loadHub();
            } catch (e) {
                console.error('[ArtistHub] add favourite failed', e);
                toast.error(`Could not add ${row.name}`);
            } finally {
                setBusyId(null);
            }
        },
        [loadHub]
    );

    const removeFavourite = useCallback(
        async (row) => {
            const ok = await confirmModal({
                title: 'Remove favourite?',
                message: `Remove "${row.name}" from your favourite artists? The tracks stay untouched.`,
                confirmLabel: 'Remove',
            });
            if (!ok) return;
            setBusyId(row.collection_id);
            try {
                await api.delete(
                    `/api/artists/favourites/${encodeURIComponent(row.collection_id)}`
                );
                toast.success(`${row.name} removed from favourites`);
                await loadHub();
            } catch (e) {
                console.error('[ArtistHub] remove favourite failed', e);
                toast.error(`Could not remove ${row.name}`);
            } finally {
                setBusyId(null);
            }
        },
        [loadHub]
    );

    const changeSyncMode = useCallback(async (row, mode) => {
        if ((row.sync_mode || 'off') === mode) return;
        const previous = row.sync_mode;
        const patch = (value) =>
            setFavourites((rows) =>
                rows.map((r) =>
                    r.collection_id === row.collection_id ? { ...r, sync_mode: value } : r
                )
            );
        patch(mode);
        try {
            await api.post(`/api/artists/${encodeURIComponent(row.collection_id)}/sync-mode`, {
                mode,
            });
        } catch (e) {
            patch(previous);
            console.error('[ArtistHub] sync-mode change failed', e);
            toast.error(`Could not set the sync mode for ${row.name}`);
        }
    }, []);

    const filteredFavourites = useMemo(() => {
        const q = searchTerm.toLowerCase();
        if (!q) return favourites;
        return favourites.filter((r) => String(r.name).toLowerCase().includes(q));
    }, [favourites, searchTerm]);

    // Server-filtered already (see loadHub) — filtering again here would re-introduce
    // the bug this replaced.
    const filteredBacklog = backlog;

    const filteredTracks = useMemo(() => {
        const q = trackFilter.toLowerCase();
        if (!q) return tracks;
        return tracks.filter(
            (t) =>
                (t.Title && t.Title.toLowerCase().includes(q)) ||
                (t.Artist && t.Artist.toLowerCase().includes(q)) ||
                (t.Album && t.Album.toLowerCase().includes(q))
        );
    }, [tracks, trackFilter]);

    return (
        <div className="h-full flex flex-col p-4">
            {/* Header — back + artist name when one is open, else refresh + search */}
            <div className="flex justify-between items-center mb-4 gap-4">
                {selected ? (
                    <div className="flex items-center gap-4 min-w-0">
                        <button
                            onClick={() => setSelected(null)}
                            className="p-2 hover:bg-white/10 rounded-full transition-colors text-ink-secondary hover:text-white shrink-0"
                        >
                            <ArrowLeft size={22} />
                        </button>
                        <div className="min-w-0">
                            <h1 className="text-2xl font-bold text-white flex items-center gap-2.5 truncate">
                                <User size={26} className="text-amber2 shrink-0" />
                                <span className="truncate">{selected.name}</span>
                            </h1>
                            <p className="text-ink-secondary text-sm mt-0.5">
                                {filteredTracks.length} / {selected.track_count || tracks.length}{' '}
                                Tracks
                            </p>
                        </div>
                    </div>
                ) : (
                    <div />
                )}

                <div className="flex items-center gap-3 shrink-0">
                    {!selected && (
                        <button
                            onClick={loadHub}
                            disabled={isLoading}
                            className={`p-2 rounded-full transition-all border border-white/5 hover:bg-white/10 text-ink-secondary hover:text-amber2 ${
                                isLoading ? 'animate-spin opacity-50' : ''
                            }`}
                            title="Refresh the hub"
                        >
                            <RotateCw size={16} />
                        </button>
                    )}
                    <div className="relative group w-64">
                        <Search
                            size={16}
                            className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted group-focus-within:text-amber2 transition-colors"
                        />
                        <input
                            className="input-glass w-full pl-10 bg-black/20 text-sm rounded-full py-2"
                            placeholder={selected ? 'Search tracks...' : 'Search artists...'}
                            value={selected ? trackFilter : searchTerm}
                            onChange={(e) =>
                                selected
                                    ? setTrackFilter(e.target.value)
                                    : setSearchTerm(e.target.value)
                            }
                        />
                    </div>
                </div>
            </div>

            {selected ? (
                <div className="flex-1 min-h-0 overflow-y-auto pb-4 p-2">
                    {tracksLoading ? (
                        <div className="flex items-center justify-center gap-3 py-16 text-ink-muted text-[12px]">
                            <Loader2 size={18} className="animate-spin text-amber2" />
                            Loading tracks…
                        </div>
                    ) : tracks.length === 0 ? (
                        <EmptyHint>
                            No local tracks found for this artist in the loaded library.
                        </EmptyHint>
                    ) : (
                        <TrackTable
                            tracks={filteredTracks}
                            onSelectTrack={onSelectTrack}
                            onEditTrack={onEditTrack}
                            onPlay={onPlayTrack}
                            playlistId={`ARTISTS_${selected.collection_id}`}
                        />
                    )}
                </div>
            ) : (
                <div className="flex-1 min-h-0 grid grid-cols-1 xl:grid-cols-[1fr_400px] gap-4">
                    {/* Favourites */}
                    <div className="bg-mx-panel border border-line-subtle rounded-xl flex flex-col min-h-0 overflow-hidden">
                        <PanelHead
                            label={`Favourite artists · ${favourites.length}`}
                            right={
                                <button
                                    disabled
                                    title={SC_PENDING_REASON}
                                    className="flex items-center gap-1.5 px-2.5 py-1 rounded-mx-sm text-[11px] bg-mx-card border border-line-subtle text-ink-muted opacity-50 cursor-not-allowed"
                                >
                                    <RefreshCw size={12} />
                                    Update all
                                </button>
                            }
                        />

                        <div className="flex-1 min-h-0 overflow-y-auto p-3">
                            {isLoading && favourites.length === 0 ? (
                                <EmptyHint>Loading…</EmptyHint>
                            ) : filteredFavourites.length === 0 ? (
                                <EmptyHint>
                                    {favourites.length === 0
                                        ? 'No favourite artists yet — add one from the suggestions on the right.'
                                        : 'No favourite matches that search.'}
                                </EmptyHint>
                            ) : (
                                filteredFavourites.map((row) => {
                                    const aliases = (row.library_names?.length || 1) - 1;
                                    return (
                                        <div
                                            key={row.collection_id}
                                            role="button"
                                            tabIndex={0}
                                            onClick={() => openArtist(row)}
                                            onKeyDown={(e) => {
                                                if (e.key === 'Enter' || e.key === ' ') {
                                                    e.preventDefault();
                                                    openArtist(row);
                                                }
                                            }}
                                            className="flex items-center gap-3 px-3 py-2.5 mb-1.5 rounded-xl bg-mx-card/40 hover:bg-amber2/10 border border-white/5 hover:border-amber2/50 cursor-pointer transition-all"
                                        >
                                            <ArtistAvatar name={row.name} artwork={row.artwork} />
                                            <div className="flex-1 min-w-0">
                                                <div className="font-semibold text-[13px] text-ink-primary truncate">
                                                    {row.name}
                                                </div>
                                                <div className="mt-0.5 flex items-center gap-2 text-[11.5px] text-ink-muted flex-wrap">
                                                    <span className="font-mono">
                                                        {row.track_count} tracks
                                                    </span>
                                                    {aliases > 0 && (
                                                        <span>
                                                            · {aliases}{' '}
                                                            {aliases === 1 ? 'alias' : 'aliases'}{' '}
                                                            merged
                                                        </span>
                                                    )}
                                                </div>
                                            </div>
                                            <div className="flex items-center gap-2 shrink-0">
                                                <ScLinkChip linked={!!row.sc_linked} />
                                                <SyncModeControl
                                                    value={row.sync_mode}
                                                    onChange={(mode) => changeSyncMode(row, mode)}
                                                />
                                                <button
                                                    disabled
                                                    title={SC_PENDING_REASON}
                                                    onClick={(e) => e.stopPropagation()}
                                                    className="flex items-center gap-1.5 px-2.5 py-1 rounded-mx-sm text-[11px] bg-mx-card border border-line-subtle text-ink-muted opacity-50 cursor-not-allowed"
                                                >
                                                    <RefreshCw size={12} />
                                                    Update
                                                </button>
                                                <button
                                                    disabled={busyId === row.collection_id}
                                                    title="Remove from favourites"
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        removeFavourite(row);
                                                    }}
                                                    className="p-1.5 rounded-mx-sm text-amber2 hover:text-bad hover:bg-bad/10 transition-colors disabled:opacity-40"
                                                >
                                                    <Star size={14} fill="currentColor" />
                                                </button>
                                            </div>
                                        </div>
                                    );
                                })
                            )}
                        </div>

                        <div className="border-t border-line-subtle px-3.5 py-2.5 text-[11.5px] text-ink-muted leading-relaxed">
                            <b className="text-ink-secondary font-semibold">Auto</b> downloads new
                            tracks while the app is idle ·{' '}
                            <b className="text-ink-secondary font-semibold">Review</b> only lists
                            them · <b className="text-ink-secondary font-semibold">Off</b> never
                            syncs. The choice is stored now, but nothing acts on it yet:{' '}
                            <b className="text-ink-secondary font-semibold">
                                the SoundCloud sync behind Update, Update all and the modes is not
                                built
                            </b>{' '}
                            — it arrives in a later step, which is why those buttons are disabled.
                        </div>
                    </div>

                    {/* Suggestions */}
                    <div className="flex flex-col gap-4 min-h-0">
                        <div className="bg-mx-panel border border-line-subtle rounded-xl flex flex-col min-h-0 overflow-hidden">
                            <div className="flex items-stretch px-3 border-b border-line-subtle">
                                <button
                                    type="button"
                                    className="px-2.5 py-2 text-[12px] font-semibold text-ink-primary border-b-2 border-amber2"
                                >
                                    From your library
                                </button>
                                <button
                                    type="button"
                                    disabled
                                    title={SC_PENDING_REASON}
                                    className="flex items-center gap-1.5 px-2.5 py-2 text-[12px] text-ink-muted border-b-2 border-transparent opacity-50 cursor-not-allowed"
                                >
                                    Discover on SoundCloud
                                    <span className="px-1.5 py-[1px] rounded-mx-xs text-[9px] font-semibold uppercase tracking-wider bg-mx-card border border-line-subtle">
                                        Later
                                    </span>
                                </button>
                            </div>

                            <PanelHead
                                label={
                                    backlogTotal > backlog.length
                                        ? `Local backlog · top ${backlog.length} of ${backlogTotal} · ranked by owned tracks`
                                        : 'Local backlog · ranked by owned tracks'
                                }
                                right={
                                    <span className="font-mono text-[11px] text-ink-muted bg-black/20 rounded-full px-2 py-[2px]">
                                        0 network calls
                                    </span>
                                }
                            />

                            <div className="flex-1 min-h-0 overflow-y-auto p-3">
                                {isLoading && backlog.length === 0 ? (
                                    <EmptyHint>Loading…</EmptyHint>
                                ) : filteredBacklog.length === 0 ? (
                                    <EmptyHint>
                                        {libraryStatus?.loaded
                                            ? 'Nothing left to suggest from your library.'
                                            : 'Load a library to see suggestions.'}
                                    </EmptyHint>
                                ) : (
                                    filteredBacklog.map((row) => (
                                        <div
                                            key={row.collection_id}
                                            role="button"
                                            tabIndex={0}
                                            onClick={() => openArtist(row)}
                                            onKeyDown={(e) => {
                                                if (e.key === 'Enter' || e.key === ' ') {
                                                    e.preventDefault();
                                                    openArtist(row);
                                                }
                                            }}
                                            className="flex items-center gap-3 px-3 py-2 mb-1.5 rounded-xl bg-mx-card/40 hover:bg-amber2/10 border border-white/5 hover:border-amber2/50 cursor-pointer transition-all"
                                        >
                                            <ArtistAvatar
                                                name={row.name}
                                                artwork={row.artwork}
                                                small
                                            />
                                            <div className="flex-1 min-w-0">
                                                <div className="font-semibold text-[13px] text-ink-primary truncate">
                                                    {row.name}
                                                </div>
                                                <div className="mt-0.5 font-mono text-[11.5px] text-ink-muted">
                                                    {row.track_count} tracks
                                                </div>
                                            </div>
                                            <button
                                                disabled={busyId === row.collection_id}
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    addFavourite(row);
                                                }}
                                                title={`Add ${row.name} to favourites`}
                                                className="flex items-center gap-1.5 px-2.5 py-1 rounded-mx-sm text-[11px] bg-mx-card border border-line-subtle text-ink-primary hover:border-amber2/50 hover:text-amber2 transition-colors disabled:opacity-40 shrink-0"
                                            >
                                                {busyId === row.collection_id ? (
                                                    <Loader2 size={12} className="animate-spin" />
                                                ) : (
                                                    <Plus size={12} />
                                                )}
                                                Add
                                            </button>
                                        </div>
                                    ))
                                )}
                            </div>

                            <div className="border-t border-line-subtle px-3.5 py-2.5 text-[11.5px] text-ink-muted">
                                Artists you already own, most tracks first. Favourites are excluded.
                                No network calls.
                            </div>
                        </div>

                        <div className="rounded-xl border border-dashed border-line-subtle bg-mx-input/60 p-3.5 shrink-0">
                            <div className="flex items-center gap-2 mb-1.5">
                                <Cloud size={14} className="text-ink-muted" />
                                <span className="text-[12px] font-semibold text-ink-secondary">
                                    Discover on SoundCloud — not live yet
                                </span>
                            </div>
                            <p className="text-[11.5px] text-ink-muted leading-relaxed">
                                The SoundCloud half of the hub — linking an artist to their profile,
                                the missing-track diff, per-artist Update and one-hop discovery — is
                                a later milestone and is not implemented. The controls stay visible
                                but disabled so you can see what is coming; none of them shows
                                invented data or reports a sync that did not happen.
                            </p>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default ArtistHubView;
