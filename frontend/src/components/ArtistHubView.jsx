import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'react-hot-toast';
import {
    ArrowLeft,
    Cloud,
    Copy,
    GitMerge,
    ListMusic,
    Loader2,
    Plus,
    RefreshCw,
    RotateCw,
    Search,
    Star,
    StarOff,
    User,
} from 'lucide-react';
import api from '../api/api';
import TrackTable from './TrackTable';
import { confirmModal } from './ConfirmModal';
import { useContextMenu } from './shared/ContextMenu';
import MergeDialog from './artistHub/MergeDialog';
import ProjectionPanel from './artistHub/ProjectionPanel';
import { fetchMergeCandidates } from './artistHub/artistHubApi';

/**
 * ArtistHubView — the Artists tab. Left: curated favourites (link state, sync
 * mode, per-artist Update). Right: a three-tab panel — the Tier-1 local backlog,
 * the complete "All artists" list, and the SoundCloud discovery tab.
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

const SUGGEST_TAB_BACKLOG = 'backlog';
const SUGGEST_TAB_ALL = 'all';

const BROWSE_SORTS = [
    { id: 'name', label: 'A–Z' },
    { id: 'tracks', label: 'Most tracks' },
];

// One page of GET /api/artists/browse. Matches the route's own default so the
// first page is never shorter than what "Load more" then pages past.
const ARTIST_BROWSE_PAGE_SIZE = 100;

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

const Segmented = ({ options, value, onChange, titleFor }) => (
    <div className="inline-flex rounded-mx-sm overflow-hidden border border-line-subtle bg-mx-input">
        {options.map((option) => {
            const on = value === option.id;
            return (
                <button
                    key={option.id}
                    type="button"
                    title={titleFor ? titleFor(option) : option.label}
                    onClick={(e) => {
                        e.stopPropagation();
                        onChange(option.id);
                    }}
                    className={`px-2 py-[3px] text-[10px] border-r border-line-subtle last:border-r-0 transition-colors ${
                        on
                            ? 'bg-amber2/10 text-amber2 font-semibold'
                            : 'text-ink-muted hover:text-ink-secondary hover:bg-mx-hover'
                    }`}
                >
                    {option.label}
                </button>
            );
        })}
    </div>
);

const SyncModeControl = ({ value, onChange }) => (
    <Segmented
        options={SYNC_MODES}
        value={value || 'off'}
        onChange={onChange}
        titleFor={(mode) => `Sync mode: ${mode.label}`}
    />
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

const AliasNote = ({ names }) => {
    const aliases = (names?.length || 1) - 1;
    if (aliases <= 0) return null;
    return (
        <span>
            · {aliases} {aliases === 1 ? 'alias' : 'aliases'} merged
        </span>
    );
};

/** One row of the right-hand panel. `action` is the trailing control (Add / star). */
const SuggestionRow = ({ row, onOpen, action, onContextMenu }) => (
    <div
        role="button"
        tabIndex={0}
        onClick={() => onOpen(row)}
        onContextMenu={(e) => onContextMenu?.(e, row)}
        onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onOpen(row);
            }
        }}
        className="flex items-center gap-3 px-3 py-2 mb-1.5 rounded-xl bg-mx-card/40 hover:bg-amber2/10 border border-white/5 hover:border-amber2/50 cursor-pointer transition-all"
    >
        <ArtistAvatar name={row.name} artwork={row.artwork} small />
        <div className="flex-1 min-w-0">
            <div className="font-semibold text-[13px] text-ink-primary truncate">{row.name}</div>
            <div className="mt-0.5 flex items-center gap-2 text-[11.5px] text-ink-muted flex-wrap">
                <span className="font-mono">{row.track_count} tracks</span>
                <AliasNote names={row.library_names} />
            </div>
        </div>
        {action}
    </div>
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
    const [suggestTab, setSuggestTab] = useState(SUGGEST_TAB_BACKLOG);
    const [browseRows, setBrowseRows] = useState([]);
    const [browseTotal, setBrowseTotal] = useState(0);
    const [browseSort, setBrowseSort] = useState(BROWSE_SORTS[0].id);
    const [browseLoading, setBrowseLoading] = useState(false);
    const [browseAppending, setBrowseAppending] = useState(false);
    const [browseError, setBrowseError] = useState(false);
    const [mergeOpen, setMergeOpen] = useState(false);
    const [mergeSeed, setMergeSeed] = useState(null);
    // null = not scanned (or the scan failed) — the affordance stays honest about
    // not knowing instead of rendering a confident "0".
    const [duplicateCount, setDuplicateCount] = useState(null);
    // Bumped whenever something the Rekordbox projection mirrors has changed
    // (a favourite, a merge), so the panel re-reads its state instead of drifting.
    const [projectionToken, setProjectionToken] = useState(0);

    // name → library artist id (`art_N`). The ids are list indexes rebuilt on
    // every library load, so this cache is dropped whenever the library reloads.
    const libraryIndexRef = useRef(null);

    // Browse requests are debounced and "Load more" runs against a moving offset,
    // so a slow earlier response must not overwrite a newer list.
    const browseSeqRef = useRef(0);

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

    // Ambient badge: a failed scan must not toast — the user did not ask for it.
    const loadDuplicateCount = useCallback(async () => {
        try {
            const groups = await fetchMergeCandidates();
            setDuplicateCount(groups.length);
        } catch (e) {
            console.error('[ArtistHub] duplicate scan failed', e);
            setDuplicateCount(null);
        }
    }, []);

    const loadBrowse = useCallback(async ({ query, sort, offset, append }) => {
        const seq = (browseSeqRef.current += 1);
        if (append) {
            setBrowseAppending(true);
        } else {
            setBrowseLoading(true);
            setBrowseAppending(false);
        }
        try {
            const res = await api.get('/api/artists/browse', {
                params: { q: query, sort, limit: ARTIST_BROWSE_PAGE_SIZE, offset },
            });
            if (browseSeqRef.current !== seq) return;
            const rows = res.data?.artists ?? [];
            setBrowseRows((current) => (append ? [...current, ...rows] : rows));
            setBrowseTotal((current) => {
                const total = res.data?.total;
                if (typeof total === 'number') return total;
                return append ? current : rows.length;
            });
            setBrowseError(false);
        } catch (e) {
            if (browseSeqRef.current !== seq) return;
            console.error('[ArtistHub] failed to load the artist list', e);
            toast.error('Failed to load the artist list');
            // An empty list after a failure must not read as "you own no artists".
            setBrowseError(true);
            if (!append) {
                setBrowseRows([]);
                setBrowseTotal(0);
            }
        } finally {
            if (browseSeqRef.current === seq) {
                setBrowseLoading(false);
                setBrowseAppending(false);
            }
        }
    }, []);

    useEffect(() => {
        libraryIndexRef.current = null;
        setSelected(null);
        setTracks([]);
        setHubRequested(false);
        setBrowseRows([]);
        setBrowseTotal(0);
        setDuplicateCount(null);
    }, [libraryStatus?.loaded]);

    // The view stays mounted behind the other library tabs, so the fetch waits
    // for the tab to actually be shown instead of firing on every app boot.
    useEffect(() => {
        if (!active || hubRequested) return;
        setHubRequested(true);
        loadHub();
        loadDuplicateCount();
    }, [active, hubRequested, loadHub, loadDuplicateCount]);

    // Re-query the server as the search term changes, debounced so typing does not
    // fire a request per keystroke.
    useEffect(() => {
        if (!active || !hubRequested) return undefined;
        const handle = setTimeout(() => loadHub(searchTerm.trim()), HUB_SEARCH_DEBOUNCE_MS);
        return () => clearTimeout(handle);
    }, [active, hubRequested, searchTerm, loadHub]);

    // "All artists" pages server-side too: the term, the sort and the first page
    // all go to the server, so nothing is filtered a second time in the browser.
    useEffect(() => {
        if (!active || suggestTab !== SUGGEST_TAB_ALL) return undefined;
        setBrowseLoading(true);
        const handle = setTimeout(
            () =>
                loadBrowse({
                    query: searchTerm.trim(),
                    sort: browseSort,
                    offset: 0,
                    append: false,
                }),
            HUB_SEARCH_DEBOUNCE_MS
        );
        return () => clearTimeout(handle);
        // libraryStatus.loaded belongs here: the reset effect clears the rows when the
        // library state flips, and without this dep nothing refetches — the panel then
        // claims "no artists" for a library that is full of them.
    }, [active, suggestTab, searchTerm, browseSort, libraryStatus?.loaded, loadBrowse]);

    // The refresh button must not hand its click event to `loadHub` as a query.
    const refreshPanels = useCallback(() => {
        loadHub(searchTerm.trim());
        loadDuplicateCount();
        setProjectionToken((n) => n + 1);
        if (suggestTab === SUGGEST_TAB_ALL) {
            loadBrowse({ query: searchTerm.trim(), sort: browseSort, offset: 0, append: false });
        }
    }, [browseSort, loadBrowse, loadDuplicateCount, loadHub, searchTerm, suggestTab]);

    const openMergeDialog = useCallback((seed = null) => {
        setMergeSeed(seed);
        setMergeOpen(true);
    }, []);

    // A merge (or a revert) rewrites artist rows, so every cached view of them is
    // stale: the name→`art_N` index, the browse page, the hub and the projection.
    const handleMergeApplied = useCallback(() => {
        libraryIndexRef.current = null;
        setSelected(null);
        setTracks([]);
        setProjectionToken((n) => n + 1);
        loadHub(searchTerm.trim());
        loadDuplicateCount();
        if (suggestTab === SUGGEST_TAB_ALL) {
            loadBrowse({ query: searchTerm.trim(), sort: browseSort, offset: 0, append: false });
        }
    }, [browseSort, loadBrowse, loadDuplicateCount, loadHub, searchTerm, suggestTab]);

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

    // The three panes show the same artists from different angles, so a favourite
    // change in one of them is written into the browse rows too instead of waiting
    // for a reload — the star must never disagree with the favourites pane.
    const patchBrowseRow = useCallback((collectionId, patch) => {
        setBrowseRows((rows) =>
            rows.map((r) => (r.collection_id === collectionId ? { ...r, ...patch } : r))
        );
    }, []);

    // Both mutators report success as a boolean instead of throwing: the star
    // toggle needs the verdict to roll its optimistic flip back, and the plain
    // buttons have nothing to add to the toast a failure already raised.
    const addFavourite = useCallback(
        async (row) => {
            setBusyId(row.collection_id);
            try {
                // By name, not by id: a backlog/browse row can name an artist the
                // sidecar has never stored, and only the name path creates it.
                const res = await api.post('/api/artists/favourites', { name: row.name });
                const cid = res.data?.collection_id || row.collection_id;
                patchBrowseRow(row.collection_id, { is_favourite: true, collection_id: cid });
                toast.success(`${row.name} added to favourites`);
                setProjectionToken((n) => n + 1);
                await loadHub(searchTerm.trim());
                return true;
            } catch (e) {
                console.error('[ArtistHub] add favourite failed', e);
                toast.error(`Could not add ${row.name}`);
                return false;
            } finally {
                setBusyId(null);
            }
        },
        [loadHub, patchBrowseRow, searchTerm]
    );

    const dropFavourite = useCallback(
        async (row) => {
            setBusyId(row.collection_id);
            try {
                await api.delete(
                    `/api/artists/favourites/${encodeURIComponent(row.collection_id)}`
                );
                patchBrowseRow(row.collection_id, { is_favourite: false });
                toast.success(`${row.name} removed from favourites`);
                setProjectionToken((n) => n + 1);
                await loadHub(searchTerm.trim());
                return true;
            } catch (e) {
                console.error('[ArtistHub] remove favourite failed', e);
                toast.error(`Could not remove ${row.name}`);
                return false;
            } finally {
                setBusyId(null);
            }
        },
        [loadHub, patchBrowseRow, searchTerm]
    );

    const removeFavourite = useCallback(
        async (row) => {
            const ok = await confirmModal({
                title: 'Remove favourite?',
                message: `Remove "${row.name}" from your favourite artists? The tracks stay untouched.`,
                confirmLabel: 'Remove',
            });
            if (!ok) return;
            await dropFavourite(row);
        },
        [dropFavourite]
    );

    // Star toggle in "All artists": flips optimistically, rolls back on failure.
    // No confirm dialog — a toggle is undone by clicking it again, and the left
    // pane's Remove keeps its confirm because it is a one-way button.
    const toggleBrowseFavourite = useCallback(
        async (row) => {
            const next = !row.is_favourite;
            patchBrowseRow(row.collection_id, { is_favourite: next });
            const ok = await (next ? addFavourite(row) : dropFavourite(row));
            if (!ok) patchBrowseRow(row.collection_id, { is_favourite: !next });
        },
        [addFavourite, dropFavourite, patchBrowseRow]
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

    const artistMenu = useContextMenu();

    const copyArtistName = useCallback(async (name) => {
        try {
            await navigator.clipboard.writeText(name);
            toast.success(`Kopiert: ${name}`);
        } catch (err) {
            console.error('[ArtistHubView] clipboard write failed', err);
            toast.error('Zwischenablage nicht verfügbar');
        }
    }, []);

    const openArtistMenu = useCallback(
        (e, row) => {
            const isFav =
                !!row.is_favourite || favourites.some((f) => f.collection_id === row.collection_id);
            const items = [
                {
                    id: 'open',
                    label: 'Tracks anzeigen',
                    icon: ListMusic,
                    onSelect: () => openArtist(row),
                },
                isFav
                    ? {
                          id: 'unfav',
                          label: 'Aus Favoriten entfernen',
                          icon: StarOff,
                          danger: true,
                          onSelect: () => removeFavourite(row),
                      }
                    : {
                          id: 'fav',
                          label: 'Zu Favoriten hinzufügen',
                          icon: Star,
                          onSelect: () => addFavourite(row),
                      },
                ...(isFav
                    ? [
                          { separator: true },
                          ...SYNC_MODES.map((mode) => ({
                              id: `sync-${mode.id}`,
                              label: `Sync: ${mode.label}`,
                              hint: row.sync_mode === mode.id ? '✓' : undefined,
                              disabled: row.sync_mode === mode.id,
                              onSelect: () => changeSyncMode(row, mode.id),
                          })),
                      ]
                    : []),
                { separator: true },
                {
                    id: 'merge',
                    label: 'Schreibweisen zusammenführen…',
                    icon: GitMerge,
                    onSelect: () => openMergeDialog(row.name),
                },
                {
                    id: 'sc-update',
                    label: 'Von SoundCloud aktualisieren',
                    icon: Cloud,
                    disabled: true,
                    hint: 'später',
                },
                {
                    id: 'copy',
                    label: 'Namen kopieren',
                    icon: Copy,
                    onSelect: () => copyArtistName(row.name),
                },
            ];
            artistMenu.open(e, items, row.name);
        },
        [
            artistMenu,
            favourites,
            openArtist,
            addFavourite,
            removeFavourite,
            changeSyncMode,
            copyArtistName,
            openMergeDialog,
        ]
    );

    const filteredFavourites = useMemo(() => {
        const q = searchTerm.toLowerCase();
        if (!q) return favourites;
        return favourites.filter((r) => String(r.name).toLowerCase().includes(q));
    }, [favourites, searchTerm]);

    // Server-filtered already (see loadHub) — filtering again here would re-introduce
    // the bug this replaced.
    const filteredBacklog = backlog;

    const showAllArtists = suggestTab === SUGGEST_TAB_ALL;

    const suggestTabClass = (id) =>
        `px-2.5 py-2 text-[12px] border-b-2 transition-colors ${
            suggestTab === id
                ? 'font-semibold text-ink-primary border-amber2'
                : 'text-ink-muted border-transparent hover:text-ink-secondary'
        }`;

    const loadMoreArtists = useCallback(
        () =>
            loadBrowse({
                query: searchTerm.trim(),
                sort: browseSort,
                offset: browseRows.length,
                append: true,
            }),
        [browseRows.length, browseSort, loadBrowse, searchTerm]
    );

    const browseEmptyHint = useMemo(() => {
        if (browseError) return 'Could not load the artist list — refresh to try again.';
        if (!libraryStatus?.loaded) return 'Load a library to browse your artists.';
        return searchTerm.trim()
            ? 'No artist in your library matches that search.'
            : 'The loaded library has no artists.';
    }, [browseError, libraryStatus?.loaded, searchTerm]);

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
                            onClick={() => openMergeDialog(null)}
                            title={
                                duplicateCount === null
                                    ? 'Open the merge screen — the duplicate scan has not run'
                                    : duplicateCount > 0
                                      ? `${duplicateCount} artist${
                                            duplicateCount === 1 ? '' : 's'
                                        } spelled more than one way — review and merge`
                                      : 'No duplicate spellings found — opens the merge screen and its run history'
                            }
                            className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-mx-sm text-[11px] border transition-colors ${
                                duplicateCount > 0
                                    ? 'bg-amber2/10 border-amber2/40 text-amber2 hover:bg-amber2/20'
                                    : 'bg-mx-card border-line-subtle text-ink-muted hover:text-ink-secondary'
                            }`}
                        >
                            <GitMerge size={13} />
                            {duplicateCount === null
                                ? 'Duplicates'
                                : duplicateCount > 0
                                  ? `Duplicates · ${duplicateCount}`
                                  : 'No duplicates'}
                        </button>
                    )}
                    {!selected && (
                        <button
                            onClick={refreshPanels}
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
                                    return (
                                        <div
                                            key={row.collection_id}
                                            role="button"
                                            tabIndex={0}
                                            onClick={() => openArtist(row)}
                                            onContextMenu={(e) => openArtistMenu(e, row)}
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
                                                    <AliasNote names={row.library_names} />
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
                                    onClick={() => setSuggestTab(SUGGEST_TAB_BACKLOG)}
                                    className={suggestTabClass(SUGGEST_TAB_BACKLOG)}
                                >
                                    From your library
                                </button>
                                <button
                                    type="button"
                                    onClick={() => setSuggestTab(SUGGEST_TAB_ALL)}
                                    className={suggestTabClass(SUGGEST_TAB_ALL)}
                                >
                                    All artists
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

                            {showAllArtists ? (
                                <PanelHead
                                    label={
                                        browseTotal > browseRows.length
                                            ? `All artists · showing ${browseRows.length} of ${browseTotal}`
                                            : `All artists · ${browseTotal}`
                                    }
                                    right={
                                        <Segmented
                                            options={BROWSE_SORTS}
                                            value={browseSort}
                                            onChange={setBrowseSort}
                                            titleFor={(option) => `Sort: ${option.label}`}
                                        />
                                    }
                                />
                            ) : (
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
                            )}

                            <div className="flex-1 min-h-0 overflow-y-auto p-3">
                                {showAllArtists ? (
                                    <>
                                        {browseLoading && browseRows.length === 0 ? (
                                            <EmptyHint>Loading…</EmptyHint>
                                        ) : browseRows.length === 0 ? (
                                            <EmptyHint>{browseEmptyHint}</EmptyHint>
                                        ) : (
                                            browseRows.map((row) => (
                                                <SuggestionRow
                                                    key={row.collection_id}
                                                    row={row}
                                                    onOpen={openArtist}
                                                    onContextMenu={openArtistMenu}
                                                    action={
                                                        <button
                                                            type="button"
                                                            disabled={busyId === row.collection_id}
                                                            aria-pressed={!!row.is_favourite}
                                                            title={
                                                                row.is_favourite
                                                                    ? `Remove ${row.name} from favourites`
                                                                    : `Add ${row.name} to favourites`
                                                            }
                                                            onClick={(e) => {
                                                                e.stopPropagation();
                                                                toggleBrowseFavourite(row);
                                                            }}
                                                            className={`p-1.5 rounded-mx-sm transition-colors disabled:opacity-40 shrink-0 hover:bg-amber2/10 ${
                                                                row.is_favourite
                                                                    ? 'text-amber2'
                                                                    : 'text-ink-muted hover:text-amber2'
                                                            }`}
                                                        >
                                                            {busyId === row.collection_id ? (
                                                                <Loader2
                                                                    size={14}
                                                                    className="animate-spin"
                                                                />
                                                            ) : (
                                                                <Star
                                                                    size={14}
                                                                    fill={
                                                                        row.is_favourite
                                                                            ? 'currentColor'
                                                                            : 'none'
                                                                    }
                                                                />
                                                            )}
                                                        </button>
                                                    }
                                                />
                                            ))
                                        )}
                                        {browseRows.length > 0 &&
                                            browseTotal > browseRows.length && (
                                                <button
                                                    type="button"
                                                    disabled={browseAppending}
                                                    onClick={loadMoreArtists}
                                                    className="w-full flex items-center justify-center gap-1.5 px-2.5 py-2 mt-1 rounded-mx-sm text-[11px] bg-mx-card border border-line-subtle text-ink-primary hover:border-amber2/50 hover:text-amber2 transition-colors disabled:opacity-40"
                                                >
                                                    {browseAppending && (
                                                        <Loader2
                                                            size={12}
                                                            className="animate-spin"
                                                        />
                                                    )}
                                                    Load more · {browseTotal - browseRows.length}{' '}
                                                    left
                                                </button>
                                            )}
                                    </>
                                ) : isLoading && backlog.length === 0 ? (
                                    <EmptyHint>Loading…</EmptyHint>
                                ) : filteredBacklog.length === 0 ? (
                                    <EmptyHint>
                                        {libraryStatus?.loaded
                                            ? 'Nothing left to suggest from your library.'
                                            : 'Load a library to see suggestions.'}
                                    </EmptyHint>
                                ) : (
                                    filteredBacklog.map((row) => (
                                        <SuggestionRow
                                            key={row.collection_id}
                                            row={row}
                                            onOpen={openArtist}
                                            onContextMenu={openArtistMenu}
                                            action={
                                                <button
                                                    type="button"
                                                    disabled={busyId === row.collection_id}
                                                    onClick={(e) => {
                                                        e.stopPropagation();
                                                        addFavourite(row);
                                                    }}
                                                    title={`Add ${row.name} to favourites`}
                                                    className="flex items-center gap-1.5 px-2.5 py-1 rounded-mx-sm text-[11px] bg-mx-card border border-line-subtle text-ink-primary hover:border-amber2/50 hover:text-amber2 transition-colors disabled:opacity-40 shrink-0"
                                                >
                                                    {busyId === row.collection_id ? (
                                                        <Loader2
                                                            size={12}
                                                            className="animate-spin"
                                                        />
                                                    ) : (
                                                        <Plus size={12} />
                                                    )}
                                                    Add
                                                </button>
                                            }
                                        />
                                    ))
                                )}
                            </div>

                            <div className="border-t border-line-subtle px-3.5 py-2.5 text-[11.5px] text-ink-muted">
                                {showAllArtists
                                    ? 'Every artist in the loaded library. Search and sort run on the server, so nothing below the loaded page is hidden from a search. The star adds or removes a favourite — the pane on the left follows.'
                                    : 'Artists you already own, most tracks first. Favourites are excluded. No network calls.'}
                            </div>
                        </div>

                        <ProjectionPanel refreshToken={projectionToken} />

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
            {mergeOpen && (
                <MergeDialog
                    seedName={mergeSeed}
                    onClose={() => setMergeOpen(false)}
                    onApplied={handleMergeApplied}
                />
            )}
            {artistMenu.node}
        </div>
    );
};

export default ArtistHubView;
