import React, { memo, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import {
    Star,
    X,
    Check,
    ChevronDown,
    ChevronUp,
    ChevronRight,
    Image as ImageIcon,
    Scissors,
    Trash2,
    Play,
    Plus,
    ListMusic,
    FolderOpen,
    Copy,
    Tag,
    UserPlus,
    Activity,
} from 'lucide-react';
import api from '../api/api';
import toast from 'react-hot-toast';
import { confirmModal } from './ConfirmModal';
import { promptModal } from './PromptModal';
import { assignArtistModal } from './artistHub/AssignArtistModal';
import { log } from '../utils/log';
import { ANALYZE_FULL_TIMEOUT_MS, TRACK_TABLE_TEXT_COL_MIN_PX } from '../config/constants';
import { askAnalysisDepth } from './analysisDepth';
import { openExternal } from '../utils/openExternal';
import { useVirtualRows } from '../hooks/useVirtualRows';

const DEFAULT_COLUMNS = [
    { id: 'index', label: '#', width: '32px', align: 'right', fixed: true },
    { id: 'preview', label: 'Prev', width: '40px', align: 'center', fixed: true },
    { id: 'artwork', label: 'Art', width: '48px', align: 'center' },
    { id: 'Title', label: 'Title', width: '25%', sortable: true },
    { id: 'Artist', label: 'Artist', width: '20%', sortable: true },
    { id: 'Album', label: 'Album', width: '20%', sortable: true },
    { id: 'BPM', label: 'BPM', width: '48px', align: 'center', sortable: true },
    { id: 'Key', label: 'Key', width: '64px', align: 'center', sortable: true },
    { id: 'Color', label: 'C', width: '32px', align: 'center' },
    { id: 'Rating', label: 'Rating', width: '64px', align: 'center', sortable: true },
    { id: 'Bitrate', label: 'kbps', width: '64px', align: 'center', sortable: true },
    { id: 'PlayCount', label: 'Plays', width: '48px', align: 'center', sortable: true },
    { id: 'Composer', label: 'Composer', width: '150px', sortable: true },
    { id: 'Remixer', label: 'Remixer', width: '150px', sortable: true },
    { id: 'TotalTime', label: 'Time', width: '64px', align: 'center', sortable: true },
    { id: 'DateAdded', label: 'Date Added', width: '96px', align: 'right' },
    { id: 'actions', label: '', width: '40px', align: 'right', fixed: true },
];

const CAMELOT_COLORS = {
    // Camelot
    '1A': '#1DB954',
    '1B': '#1DB954',
    '2A': '#39D353',
    '2B': '#39D353',
    '3A': '#A6E22E',
    '3B': '#A6E22E',
    '4A': '#E6DB74',
    '4B': '#E6DB74',
    '5A': '#FD971F',
    '5B': '#FD971F',
    '6A': '#F92672',
    '6B': '#F92672',
    '7A': '#AE81FF',
    '7B': '#AE81FF',
    '8A': '#66D9EF',
    '8B': '#66D9EF',
    '9A': '#2AC1BC',
    '9B': '#2AC1BC',
    '10A': '#00A8FF',
    '10B': '#00A8FF',
    '11A': '#0097E6',
    '11B': '#0097E6',
    '12A': '#3E2479',
    '12B': '#3E2479',
    // Traditional mapping
    ABM: '#1DB954',
    'G#M': '#1DB954',
    B: '#1DB954',
    EBM: '#39D353',
    'D#M': '#39D353',
    GB: '#39D353',
    'F#': '#39D353',
    BBM: '#A6E22E',
    'A#M': '#A6E22E',
    DB: '#A6E22E',
    'C#': '#A6E22E',
    FM: '#E6DB74',
    AB: '#E6DB74',
    'G#': '#E6DB74',
    CM: '#FD971F',
    EB: '#FD971F',
    'D#': '#FD971F',
    GM: '#F92672',
    BB: '#F92672',
    'A#': '#F92672',
    DM: '#AE81FF',
    F: '#AE81FF',
    AM: '#66D9EF',
    C: '#66D9EF',
    EM: '#2AC1BC',
    G: '#2AC1BC',
    BM: '#00A8FF',
    D: '#00A8FF',
    'F#M': '#0097E6',
    GBM: '#0097E6',
    A: '#0097E6',
    DBM: '#3E2479',
    'C#M': '#3E2479',
    E: '#3E2479',
};

const getKeyColor = (key) => {
    if (!key) return null;
    const cleanKey = key.trim().toUpperCase();
    return CAMELOT_COLORS[cleanKey] || '#888';
};

const formatTime = (seconds) => {
    if (!seconds) return '-';
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
};

const trackIdOf = (t) => t.id || t.ID;

// The Rekordbox skin stripes rows with :nth-child(even); an even window start keeps
// each track's stripe while the window slides.
const ROW_PARITY = 2;

const ROW_STYLE = { borderBottom: '1px solid var(--line-subtle)' };
const SPACER_CELL_STYLE = { padding: 0, border: 0 };
const NO_OVERRIDES = new Map();

// Local edits (rating, colour, BPM/Key) live in an id -> {base, fields, merged} map
// instead of being written into the `tracks` prop objects. `base` is the prop object
// the edit was made on: once the parent hands over a fresh object for that id (a
// reload), the server copy wins and the override is dropped.
const MERGED_BASE = new WeakMap();

const baseOf = (track) => MERGED_BASE.get(track) || track;

function withOverride(map, base, fields) {
    const id = trackIdOf(base);
    const cur = map.get(id);
    const nextFields = { ...(cur && cur.base === base ? cur.fields : null), ...fields };
    for (const k of Object.keys(nextFields)) {
        if (nextFields[k] === base[k]) delete nextFields[k];
    }
    const next = new Map(map);
    if (Object.keys(nextFields).length === 0) {
        next.delete(id);
    } else {
        const merged = { ...base, ...nextFields };
        MERGED_BASE.set(merged, base);
        next.set(id, { base, fields: nextFields, merged });
    }
    return next;
}

const sameItems = (a, b) => {
    if (a === b) return true;
    if (!a || !b || a.length !== b.length) return false;
    for (let i = 0; i < a.length; i += 1) {
        if (a[i] !== b[i]) return false;
    }
    return true;
};

const allowDrop = (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
};

const TrackTable = ({
    tracks = [],
    onSelectTrack,
    onEditTrack,
    onPlay,
    onReorder,
    onRemove,
    onDelete,
    onAddToPlaylist,
    availablePlaylists = [],
    playlistId,
    customColumns,
    variant = 'default',
    onSortedTracksChange,
    contextActions,
    // A narrow embedding (the artist page's half-width panel) keeps its own column set:
    // the table is `table-fixed`, so the global all-columns default squeezes the
    // percentage columns — Title, Artist — to nothing there.
    columnsStorageKey = 'track_table_columns',
    defaultColumnIds,
}) => {
    const [sortConfig, setSortConfig] = useState({ key: null, direction: 'asc' });
    const [selectedKey, setSelectedKey] = useState(null);
    const [visibleColumns, setVisibleColumns] = useState(() => {
        const fallback = defaultColumnIds ?? DEFAULT_COLUMNS.map((c) => c.id);
        try {
            const saved = localStorage.getItem(columnsStorageKey);
            return saved ? JSON.parse(saved) : fallback;
        } catch (err) {
            console.warn('[TrackTable] saved column set unreadable', err);
            return fallback;
        }
    });
    const [headerMenu, setHeaderMenu] = useState(null);
    const [contextMenu, setContextMenu] = useState(null);
    const [overrides, setOverrides] = useState(NO_OVERRIDES);

    useEffect(() => {
        try {
            localStorage.setItem(columnsStorageKey, JSON.stringify(visibleColumns));
        } catch (err) {
            console.warn('[TrackTable] column set not saved', err);
        }
    }, [columnsStorageKey, visibleColumns]);

    const handleSort = (key) => {
        setSortConfig((prev) => {
            if (prev.key !== key) return { key, direction: 'asc' };
            if (prev.direction === 'asc') return { key, direction: 'desc' };
            return { key: null, direction: 'asc' };
        });
    };

    // One Set per column change — memoised rows compare it by identity.
    const visible = useMemo(() => new Set(visibleColumns), [visibleColumns]);

    // table-fixed gives %-width columns only what the px columns leave over; with many
    // columns visible Title/Artist/Album shrank to nothing. A min width from the visible
    // columns makes the container scroll horizontally instead.
    const minTableWidth = useMemo(() => {
        const px = (w) =>
            typeof w === 'string' && w.endsWith('px')
                ? parseInt(w, 10)
                : TRACK_TABLE_TEXT_COL_MIN_PX;
        const own = DEFAULT_COLUMNS.filter((c) => visible.has(c.id));
        return [...own, ...(customColumns || [])].reduce((sum, c) => sum + px(c.width), 0);
    }, [visible, customColumns]);

    const colCount = useMemo(
        () =>
            DEFAULT_COLUMNS.reduce((n, c) => n + (visible.has(c.id) ? 1 : 0), 0) +
            (customColumns?.length || 0),
        [visible, customColumns]
    );

    const sortedTracks = useMemo(() => {
        const { key, direction } = sortConfig;
        if (!key) return tracks;
        const dir = direction === 'asc' ? 1 : -1;

        // Sort keys computed once per track, not twice per comparison (20k tracks ≈ 600k
        // comparisons). Same order as before: numeric when both values are numbers,
        // else lower-cased string compare; Array.prototype.sort is stable.
        const decorated = tracks.map((t) => {
            const v = t[key];
            return {
                t,
                num: typeof v === 'number' ? v : null,
                str: String(v || '').toLowerCase(),
            };
        });
        decorated.sort((a, b) => {
            if (a.num !== null && b.num !== null) return (a.num - b.num) * dir;
            if (a.str < b.str) return -dir;
            if (a.str > b.str) return dir;
            return 0;
        });
        return decorated.map((d) => d.t);
    }, [tracks, sortConfig]);

    // Report the displayed order only when it really changed — not on every render a
    // caller's inline callback or a same-content array would otherwise trigger.
    const sortedCbRef = useRef(onSortedTracksChange);
    useLayoutEffect(() => {
        sortedCbRef.current = onSortedTracksChange;
    });
    const lastSentRef = useRef(null);
    const hasSortedCb = !!onSortedTracksChange;
    useEffect(() => {
        if (!hasSortedCb || sameItems(lastSentRef.current, sortedTracks)) return;
        lastSentRef.current = sortedTracks;
        sortedCbRef.current?.(sortedTracks);
    }, [sortedTracks, hasSortedCb]);

    // Drop overrides whose prop object is gone (list reloaded or the track left it).
    useEffect(() => {
        setOverrides((prev) => {
            if (prev.size === 0) return prev;
            const present = new Set(tracks);
            const next = new Map();
            prev.forEach((entry, id) => {
                if (present.has(entry.base)) next.set(id, entry);
            });
            return next.size === prev.size ? prev : next;
        });
    }, [tracks]);

    const toggleColumn = (colId) => {
        setVisibleColumns((prev) => {
            if (prev.includes(colId)) return prev.filter((c) => c !== colId);
            return [...prev, colId];
        });
    };

    // Close menu on click outside
    useEffect(() => {
        const handleClick = () => {
            setHeaderMenu(null);
            setContextMenu(null);
        };
        window.addEventListener('click', handleClick);
        return () => window.removeEventListener('click', handleClick);
    }, []);

    // window.open is refused inside the desktop app; openExternal goes through the
    // shell plugin there and falls back to a new tab in the browser.
    const openSoundCloud = (track) => {
        if (!track) return;
        const query = encodeURIComponent(`${track.Artist} ${track.Title}`);
        openExternal(`https://soundcloud.com/search?q=${query}`).catch((err) => {
            console.error('[TrackTable] opening SoundCloud failed', err);
            toast.error('Konnte SoundCloud nicht öffnen');
        });
    };

    // Row handlers are created once and read the current props through a ref, so the
    // memoised rows never re-render because a parent passed a fresh inline callback.
    const latest = useRef({});
    useLayoutEffect(() => {
        latest.current = { onSelectTrack, onEditTrack, onPlay, onReorder, onRemove, playlistId };
    });

    const rowActions = useMemo(() => {
        const applyLocal = (track, fields) => {
            const base = baseOf(track);
            if (trackIdOf(base) == null) return;
            setOverrides((m) => withOverride(m, base, fields));
        };

        // Shown at once; rolled back if the save fails and no newer edit replaced it.
        const persist = (track, fields, label) => {
            const base = baseOf(track);
            const id = trackIdOf(base);
            const previous = {};
            for (const k of Object.keys(fields)) previous[k] = track[k];
            applyLocal(track, fields);
            api.patch('/api/tracks/batch', { track_ids: [id], updates: fields }).catch((err) => {
                console.error(`[TrackTable] ${label} save failed`, err);
                setOverrides((m) => {
                    const cur = m.get(id);
                    if (!cur || cur.base !== base) return m;
                    const rollback = {};
                    for (const k of Object.keys(fields)) {
                        const now = k in cur.fields ? cur.fields[k] : base[k];
                        if (now === fields[k]) rollback[k] = previous[k];
                    }
                    return Object.keys(rollback).length ? withOverride(m, base, rollback) : m;
                });
                toast.error(`${label} speichern fehlgeschlagen`);
            });
        };

        return {
            select(track, key) {
                setSelectedKey(key);
                latest.current.onSelectTrack?.(track);
            },
            activate(track) {
                const { onPlay: play, onEditTrack: edit } = latest.current;
                if (play) play(track);
                else edit?.(track);
            },
            play(track) {
                latest.current.onPlay?.(track);
            },
            openMenu(e, track) {
                e.preventDefault();
                setContextMenu({ x: e.clientX, y: e.clientY, track });
                setHeaderMenu(null);
            },
            dragStart(e, track, index) {
                if (!latest.current.onReorder) return;
                e.dataTransfer.setData(
                    'application/json',
                    JSON.stringify({
                        type: 'track',
                        playlistId: latest.current.playlistId,
                        trackId: track.id,
                        index,
                    })
                );
                e.dataTransfer.effectAllowed = 'move';
            },
            drop(e, track, index) {
                e.preventDefault();
                const { onReorder: reorder, playlistId: pid } = latest.current;
                try {
                    const data = JSON.parse(e.dataTransfer.getData('application/json'));
                    if (
                        reorder &&
                        data.type === 'track' &&
                        data.playlistId === pid &&
                        data.trackId !== track.id
                    ) {
                        reorder(data.trackId, index);
                    }
                } catch (err) {
                    // Drop payload wasn't our JSON shape (e.g. native OS drag) — ignore.
                    log.debug('TrackTable drop JSON parse failed', err);
                }
            },
            remove(track) {
                latest.current.onRemove?.(track.id);
            },
            rate(track, star) {
                // Toggle: clicking the current rating clears it
                const newRating = (track.Rating || 0) === star ? 0 : star;
                persist(track, { Rating: newRating }, 'Rating');
            },
            color(track, colorId) {
                persist(track, { ColorID: String(colorId) }, 'Color');
            },
            // Saved elsewhere (context-menu BPM/Key edit) — just show it.
            patched: applyLocal,
        };
    }, []);

    const { scrollRef, bodyRef, start, end, offsetTop, offsetBottom } = useVirtualRows({
        rowCount: sortedTracks.length,
        align: ROW_PARITY,
        resetKey: playlistId,
    });

    const canReorder = !!onReorder;
    const canRemove = !!onRemove;
    const rows = [];
    for (let index = start; index < end; index += 1) {
        const t = sortedTracks[index];
        const key = t.id || index;
        const ov = overrides.size ? overrides.get(trackIdOf(t)) : undefined;
        rows.push(
            <TrackRow
                key={key}
                track={ov && ov.base === t ? ov.merged : t}
                index={index}
                rowKey={key}
                selected={selectedKey === key}
                visible={visible}
                customColumns={customColumns}
                canReorder={canReorder}
                canRemove={canRemove}
                actions={rowActions}
            />
        );
    }

    return (
        <div
            ref={scrollRef}
            className={`track-table h-full overflow-auto relative ${variant === 'default' ? 'bg-mx-shell border border-line-subtle rounded-mx-md mx-2 mb-2 pb-20' : ''}`}
            // Spacer heights change as the window slides; browser scroll anchoring would
            // "correct" scrollTop against that and make the list jump.
            style={{ overflowAnchor: 'none' }}
        >
            <table
                className="w-full text-left border-collapse table-fixed"
                style={{ minWidth: Math.max(800, minTableWidth) }}
            >
                <thead
                    className="tt-head sticky top-0 z-10 select-none"
                    style={{
                        background: 'var(--mx-shell)',
                        borderBottom: '1px solid var(--line-subtle)',
                    }}
                >
                    <tr
                        onContextMenu={(e) => {
                            e.preventDefault();
                            setHeaderMenu({ x: e.clientX, y: e.clientY });
                            setContextMenu(null);
                        }}
                    >
                        {DEFAULT_COLUMNS.map((col) => {
                            if (!visible.has(col.id)) return null;
                            return (
                                <th
                                    key={col.id}
                                    style={{ width: col.width, textAlign: col.align || 'left' }}
                                    onClick={() => col.sortable && handleSort(col.id)}
                                    className={`tt-th p-2 text-[10px] font-semibold text-ink-muted uppercase tracking-wider ${col.sortable ? 'cursor-pointer hover:text-amber2 transition-colors' : ''} ${sortConfig.key === col.id ? 'tt-sorted' : ''}`}
                                >
                                    <div className="flex items-center gap-1 justify-between">
                                        <span
                                            className={
                                                col.align === 'center'
                                                    ? 'mx-auto'
                                                    : col.align === 'right'
                                                      ? 'ml-auto'
                                                      : ''
                                            }
                                        >
                                            {col.label}
                                        </span>
                                        {sortConfig.key === col.id &&
                                            (sortConfig.direction === 'asc' ? (
                                                <ChevronUp size={10} />
                                            ) : (
                                                <ChevronDown size={10} />
                                            ))}
                                    </div>
                                </th>
                            );
                        })}
                        {customColumns &&
                            customColumns.map((col) => (
                                <th
                                    key={col.id}
                                    style={{ width: col.width }}
                                    className="tt-th p-2 text-[10px] font-semibold text-ink-muted uppercase tracking-wider text-center"
                                >
                                    {col.label}
                                </th>
                            ))}
                    </tr>
                </thead>
                {/* Spacers live in their own row groups so the rows' :nth-child count
                    starts at the first mounted track. */}
                {offsetTop > 0 && (
                    <tbody aria-hidden="true">
                        <tr style={{ height: offsetTop }}>
                            <td colSpan={colCount} style={SPACER_CELL_STYLE} />
                        </tr>
                    </tbody>
                )}
                <tbody ref={bodyRef}>{rows}</tbody>
                {offsetBottom > 0 && (
                    <tbody aria-hidden="true">
                        <tr style={{ height: offsetBottom }}>
                            <td colSpan={colCount} style={SPACER_CELL_STYLE} />
                        </tr>
                    </tbody>
                )}
            </table>

            {/* Column Menu */}
            {headerMenu && (
                <div
                    className="fixed z-[100] bg-mx-panel border border-line-default rounded-mx-md shadow-mx-lg py-1.5 min-w-[160px] animate-fade-in"
                    style={{ top: headerMenu.y, left: headerMenu.x }}
                    onClick={(e) => e.stopPropagation()}
                >
                    <div className="mx-caption px-3 py-1.5 border-b border-line-subtle mb-1">
                        Toggle Columns
                    </div>
                    {DEFAULT_COLUMNS.map((col) => {
                        if (col.fixed) return null;
                        return (
                            <button
                                key={col.id}
                                onClick={() => toggleColumn(col.id)}
                                className="w-full flex items-center justify-between px-3 py-1.5 hover:bg-mx-hover text-[12px] text-ink-secondary hover:text-ink-primary transition-colors"
                            >
                                <span>{col.label}</span>
                                {visible.has(col.id) && <Check size={12} className="text-amber2" />}
                            </button>
                        );
                    })}
                </div>
            )}

            {/* Context Menu */}
            {contextMenu && (
                <TrackContextMenuPopup
                    contextMenu={contextMenu}
                    onEditTrack={onEditTrack}
                    onPlay={onPlay}
                    openSoundCloud={openSoundCloud}
                    onRemove={onRemove}
                    onDelete={onDelete}
                    onAddToPlaylist={onAddToPlaylist}
                    availablePlaylists={availablePlaylists}
                    setContextMenu={setContextMenu}
                    contextActions={contextActions}
                    onPatched={rowActions.patched}
                />
            )}
        </div>
    );
};

const ArtworkCell = ({ path, title }) => {
    // Remember which path failed, so a row reused for another track tries again.
    const [failedPath, setFailedPath] = useState(null);
    if (!path || failedPath === path) {
        return (
            <div className="tt-art w-9 h-9 bg-mx-card rounded-mx-sm border border-line-subtle flex items-center justify-center mx-auto text-ink-placeholder">
                <ImageIcon size={14} />
            </div>
        );
    }
    return (
        <div className="tt-art w-9 h-9 rounded-mx-sm overflow-hidden mx-auto bg-mx-card border border-line-subtle relative group-hover:scale-105 transition-transform">
            <img
                src={`${api.defaults.baseURL || ''}/api/artwork?path=${encodeURIComponent(path)}`}
                alt={title}
                className="w-full h-full object-cover"
                loading="lazy"
                onError={() => setFailedPath(path)}
            />
        </div>
    );
};

const RATING_STARS = [1, 2, 3, 4, 5];

// One row. Memoised: it re-renders only when its own track object, position,
// selection or the column set changes — handlers come from a stable `actions` object.
const TrackRow = memo(function TrackRow({
    track: t,
    index,
    rowKey,
    selected,
    visible,
    customColumns,
    canReorder,
    canRemove,
    actions,
}) {
    return (
        <tr
            onClick={() => actions.select(t, rowKey)}
            onDoubleClick={() => actions.activate(t)}
            onContextMenu={(e) => actions.openMenu(e, t)}
            className={`tt-row group transition-colors cursor-pointer text-[12px] hover:bg-mx-hover ${selected ? 'tt-selected' : ''}`}
            style={ROW_STYLE}
            draggable={canReorder}
            onDragStart={(e) => actions.dragStart(e, t, index)}
            onDragOver={allowDrop}
            onDrop={(e) => actions.drop(e, t, index)}
        >
            {visible.has('index') && (
                <td className="tt-num p-1 font-mono text-ink-muted text-right pr-2 text-[11px]">
                    {index + 1}
                </td>
            )}
            {visible.has('preview') && (
                <td
                    className="p-1 text-center opacity-50 hover:opacity-100 cursor-pointer hover:text-amber2"
                    onClick={(e) => {
                        e.stopPropagation();
                        actions.play(t);
                    }}
                >
                    <Play size={12} className="mx-auto fill-current" />
                </td>
            )}
            {visible.has('artwork') && (
                <td className="p-1 px-2 text-center w-[48px]">
                    <ArtworkCell path={t.Artwork} title={t.Title} />
                </td>
            )}
            {visible.has('Title') && (
                <td
                    className="tt-title p-1 px-2 font-medium text-ink-primary group-hover:text-amber2 transition-colors truncate"
                    title={t.Title}
                >
                    {t.Title}
                </td>
            )}
            {visible.has('Artist') && (
                <td className="p-1 text-ink-secondary truncate" title={t.Artist}>
                    {t.Artist}
                </td>
            )}
            {visible.has('Album') && (
                <td className="p-1 text-ink-muted truncate" title={t.Album}>
                    {t.Album || '-'}
                </td>
            )}
            {visible.has('BPM') && (
                <td className="tt-bpm p-1 text-amber2 text-center font-mono">
                    {t.BPM ? parseFloat(t.BPM).toFixed(2) : '-'}
                </td>
            )}
            {visible.has('Key') && (
                <td className="p-1 text-center font-mono font-bold">
                    <span
                        className="tt-key-badge px-2 py-0.5 rounded-full text-[9px] shadow-lg"
                        style={{
                            backgroundColor: `${getKeyColor(t.Key)}22`, // 22 is ~13% opacity
                            color: getKeyColor(t.Key),
                            border: `1px solid ${getKeyColor(t.Key)}44`,
                        }}
                    >
                        {t.Key || '-'}
                    </span>
                </td>
            )}
            {visible.has('Color') && (
                <td className="p-1 text-center">
                    <ColorDot colorId={t.ColorID} onPick={(c) => actions.color(t, c)} />
                </td>
            )}
            {visible.has('Rating') && (
                <td className="p-1 text-center">
                    <div className="tt-rating flex justify-center gap-0.5 opacity-40 group-hover:opacity-100">
                        {RATING_STARS.map((star) => (
                            <Star
                                key={star}
                                size={11}
                                fill={star <= (t.Rating || 0) ? 'currentColor' : 'none'}
                                className={`cursor-pointer transition-transform hover:scale-125 ${
                                    star <= (t.Rating || 0)
                                        ? 'text-amber2'
                                        : 'text-ink-placeholder hover:text-amber2/60'
                                }`}
                                onClick={(e) => {
                                    e.stopPropagation();
                                    actions.rate(t, star);
                                }}
                            />
                        ))}
                    </div>
                </td>
            )}
            {[
                { id: 'Bitrate', value: t.Bitrate || '-' },
                { id: 'PlayCount', value: t.PlayCount || '-' },
                { id: 'Composer', value: t.Composer },
                { id: 'Remixer', value: t.Remixer },
            ].map(
                (field) =>
                    visible.has(field.id) && (
                        <td
                            key={field.id}
                            className={`p-1 truncate ${field.id === 'Bitrate' || field.id === 'PlayCount' ? 'text-center font-mono text-ink-secondary' : 'text-ink-muted'}`}
                            title={field.value}
                        >
                            {field.value || '-'}
                        </td>
                    )
            )}
            {visible.has('TotalTime') && (
                <td className="tt-time p-1 text-ink-secondary text-center font-mono">
                    {formatTime(t.TotalTime)}
                </td>
            )}
            {visible.has('DateAdded') && (
                <td className="p-1 text-ink-muted text-right pr-2 text-[10px] font-mono">
                    {t.DateAdded || '-'}
                </td>
            )}
            {customColumns &&
                customColumns.map((col) => (
                    <td key={col.id} className="p-1">
                        {col.render ? col.render(t) : '-'}
                    </td>
                ))}
            {visible.has('actions') && (
                <td className="p-1 text-right pr-4">
                    {canRemove && (
                        <button
                            onClick={(e) => {
                                e.stopPropagation();
                                actions.remove(t);
                            }}
                            className="p-1 px-2 hover:bg-bad/10 rounded-mx-sm text-bad/60 hover:text-bad transition-all opacity-0 group-hover:opacity-100"
                        >
                            <X size={12} />
                        </button>
                    )}
                </td>
            )}
        </tr>
    );
});

// Pioneer color palette — IDs 0-8 (None, Pink, Red, Orange, Yellow, Green, Aqua, Blue, Purple)
const PIONEER_COLORS = [
    { id: '0', name: 'Keine', hex: 'transparent', border: 'var(--line-default)' },
    { id: '1', name: 'Pink', hex: '#ff007f' },
    { id: '2', name: 'Red', hex: '#ff0000' },
    { id: '3', name: 'Orange', hex: '#ff7f00' },
    { id: '4', name: 'Yellow', hex: '#ffd700' },
    { id: '5', name: 'Green', hex: '#00d000' },
    { id: '6', name: 'Aqua', hex: '#00c8ff' },
    { id: '7', name: 'Blue', hex: '#0070ff' },
    { id: '8', name: 'Purple', hex: '#a000ff' },
];

const ColorDot = ({ colorId, onPick }) => {
    const [open, setOpen] = useState(false);
    const ref = React.useRef(null);
    const cur = String(colorId || '0');
    const color = PIONEER_COLORS.find((c) => c.id === cur) || PIONEER_COLORS[0];

    useEffect(() => {
        if (!open) return;
        const onDoc = (e) => {
            if (ref.current && !ref.current.contains(e.target)) setOpen(false);
        };
        document.addEventListener('mousedown', onDoc);
        return () => document.removeEventListener('mousedown', onDoc);
    }, [open]);

    return (
        <div className="relative inline-block" ref={ref}>
            <button
                onClick={(e) => {
                    e.stopPropagation();
                    setOpen((v) => !v);
                }}
                title={`Farbe: ${color.name}`}
                className="w-3.5 h-3.5 rounded-full border-2 transition-transform hover:scale-125"
                style={{
                    background: color.hex,
                    borderColor: color.id === '0' ? 'var(--ink-placeholder)' : color.hex,
                    boxShadow: color.id === '0' ? 'none' : `0 0 4px ${color.hex}80`,
                }}
            />
            {open && (
                <div
                    className="absolute top-5 left-1/2 -translate-x-1/2 z-50 flex gap-1 p-1.5 bg-mx-shell border border-white/15 rounded-lg shadow-2xl"
                    onClick={(e) => e.stopPropagation()}
                >
                    {PIONEER_COLORS.map((c) => (
                        <button
                            key={c.id}
                            onClick={(e) => {
                                e.stopPropagation();
                                onPick(c.id);
                                setOpen(false);
                            }}
                            title={c.name}
                            className={`w-4 h-4 rounded-full border-2 transition-transform hover:scale-125 ${cur === c.id ? 'ring-2 ring-white' : ''}`}
                            style={{
                                background: c.hex,
                                borderColor: c.id === '0' ? 'var(--ink-placeholder)' : c.hex,
                            }}
                        />
                    ))}
                </div>
            )}
        </div>
    );
};

const TrackContextMenuPopup = ({
    contextMenu,
    onEditTrack,
    onPlay,
    openSoundCloud,
    onRemove,
    onDelete,
    onAddToPlaylist,
    availablePlaylists,
    setContextMenu,
    contextActions,
    onPatched,
}) => {
    const [showAddSubmenu, setShowAddSubmenu] = useState(false);
    const [pSearch, setPSearch] = useState('');
    const closeTimer = React.useRef(null);
    React.useEffect(
        () => () => {
            if (closeTimer.current) clearTimeout(closeTimer.current);
        },
        []
    );
    const t = contextMenu.track;
    const trackPath = t.path || t.Path || t.Location || '';
    // `contextActions` is an array, or a function of the track for per-row items.
    const extraActions =
        (typeof contextActions === 'function' ? contextActions(t) : contextActions) || [];

    const handleReveal = async () => {
        try {
            await api.post('/api/file/reveal', { path: trackPath });
        } catch (e) {
            toast.error('Konnte Datei nicht im Explorer öffnen');
        }
        setContextMenu(null);
    };
    const handleCopy = () => {
        const text = `${t.Artist || '?'} - ${t.Title || '?'}`;
        navigator.clipboard.writeText(text).then(
            () => toast.success(`Kopiert: ${text}`),
            () => toast.error('Clipboard-Zugriff verweigert')
        );
        setContextMenu(null);
    };
    const handleEditMeta = async () => {
        const newBpm = await promptModal({
            title: 'Edit BPM',
            message: 'BPM:',
            defaultValue: String(Math.round(t.BPM || 0)),
        });
        if (newBpm === null) {
            setContextMenu(null);
            return;
        }
        const newKey = await promptModal({
            title: 'Edit Key',
            message: 'Key (z.B. Am, 8A):',
            defaultValue: t.Key || '',
        });
        if (newKey === null) {
            setContextMenu(null);
            return;
        }
        const updates = { BPM: parseFloat(newBpm) || 0, Key: newKey };
        try {
            await api.patch('/api/tracks/batch', {
                track_ids: [t.id || t.ID],
                updates,
            });
            onPatched?.(t, updates);
            toast.success('Metadaten aktualisiert');
        } catch (e) {
            toast.error('Update fehlgeschlagen: ' + (e.response?.data?.detail || e.message));
        }
        setContextMenu(null);
    };
    const handleAnalyze = async () => {
        setContextMenu(null);
        const id = t.id || t.ID;
        const depth = await askAnalysisDepth({
            subject: `${t.Artist || '?'} - ${t.Title || '?'}`,
        });
        if (!depth) return;
        const toastId = toast.loading(`Analysiere: ${t.Title || id}`);
        try {
            const res = await api.post(
                `/api/track/${id}/analyze-full`,
                { depth },
                { timeout: ANALYZE_FULL_TIMEOUT_MS }
            );
            const data = res.data?.data || {};
            const updates = {};
            if (data.bpm) updates.BPM = data.bpm;
            if (data.key) updates.Key = data.key;
            if (Object.keys(updates).length) onPatched?.(t, updates);
            toast.success(`Analyse fertig: ${data.bpm ?? '?'} BPM, ${data.key ?? '?'}`, {
                id: toastId,
            });
        } catch (e) {
            toast.error('Analyse fehlgeschlagen: ' + (e.response?.data?.detail || e.message), {
                id: toastId,
            });
        }
    };

    return (
        <div
            data-context-menu="true"
            className="fixed z-[100] bg-mx-panel border border-line-default rounded-mx-md shadow-mx-lg min-w-[220px] animate-fade-in overflow-visible"
            style={{ top: contextMenu.y, left: contextMenu.x }}
            onClick={(e) => e.stopPropagation()}
        >
            <div className="mx-caption px-3 py-2 border-b border-line-subtle truncate max-w-[260px]">
                {t.Title}
            </div>
            {onPlay && (
                <button
                    onClick={() => {
                        onPlay(t);
                        setContextMenu(null);
                    }}
                    className="w-full flex items-center gap-3 px-4 py-2 hover:bg-mx-hover text-[12px] text-ink-secondary hover:text-amber2 transition-colors text-left"
                >
                    <Play size={14} fill="currentColor" /> Abspielen
                </button>
            )}
            <button
                onClick={() => {
                    onEditTrack && onEditTrack(t);
                    setContextMenu(null);
                }}
                className="w-full flex items-center gap-3 px-4 py-2 hover:bg-mx-hover text-[12px] text-ink-secondary hover:text-amber2 transition-colors text-left"
            >
                <Scissors size={14} /> Im Waveform-Editor öffnen
            </button>
            <button
                onClick={handleEditMeta}
                className="w-full flex items-center gap-3 px-4 py-2 hover:bg-mx-hover text-[12px] text-ink-secondary hover:text-blue-400 transition-colors text-left"
            >
                <Tag size={14} /> Metadaten (BPM/Key)
            </button>
            <button
                onClick={handleAnalyze}
                disabled={!trackPath}
                className="w-full flex items-center gap-3 px-4 py-2 hover:bg-mx-hover text-[12px] text-ink-secondary hover:text-amber2 transition-colors text-left disabled:opacity-30"
            >
                <Activity size={14} /> Analysieren…
            </button>
            <button
                onClick={handleReveal}
                disabled={!trackPath}
                className="w-full flex items-center gap-3 px-4 py-2 hover:bg-mx-hover text-[12px] text-ink-secondary hover:text-cyan-400 transition-colors text-left disabled:opacity-30"
            >
                <FolderOpen size={14} /> Im Explorer zeigen
            </button>
            <button
                onClick={handleCopy}
                className="w-full flex items-center gap-3 px-4 py-2 hover:bg-mx-hover text-[12px] text-ink-secondary hover:text-ink-primary transition-colors text-left"
            >
                <Copy size={14} /> "Artist – Title" kopieren
            </button>
            <div className="h-px bg-line-subtle" />
            <button
                onClick={() => {
                    openSoundCloud(t);
                    setContextMenu(null);
                }}
                className="w-full flex items-center gap-3 px-4 py-2 hover:bg-[#ff5500]/10 text-[12px] text-ink-secondary hover:text-[#ff5500] transition-colors text-left"
            >
                <div
                    className="w-3.5 h-3.5 bg-current mask-soundcloud"
                    style={{
                        maskImage:
                            'url(https://a-v2.sndcdn.com/assets/images/sc-icons/ios-a62dfc8f.svg)',
                        WebkitMaskImage:
                            'url(https://a-v2.sndcdn.com/assets/images/sc-icons/ios-a62dfc8f.svg)',
                    }}
                ></div>
                Auf SoundCloud öffnen
            </button>
            <button
                onClick={() => {
                    setContextMenu(null);
                    assignArtistModal({ track: t });
                }}
                disabled={t.id == null && t.ID == null}
                className="w-full flex items-center gap-3 px-4 py-2 hover:bg-mx-hover text-[12px] text-ink-secondary hover:text-amber2 transition-colors text-left disabled:opacity-30"
            >
                <UserPlus size={14} /> Artist zuordnen…
            </button>

            {/* View-specific actions (e.g. the artist page's exclude / re-role) */}
            {extraActions.length > 0 && (
                <>
                    <div className="h-px bg-line-subtle" />
                    {extraActions.map((action) => {
                        const Icon = action.icon;
                        return (
                            <button
                                key={action.id}
                                disabled={action.disabled}
                                title={action.title}
                                onClick={() => {
                                    setContextMenu(null);
                                    action.onSelect(t);
                                }}
                                className={`w-full flex items-center gap-3 px-4 py-2 hover:bg-mx-hover text-[12px] transition-colors text-left disabled:opacity-30 ${
                                    action.danger
                                        ? 'text-ink-secondary hover:text-bad'
                                        : 'text-ink-secondary hover:text-amber2'
                                }`}
                            >
                                {Icon ? <Icon size={14} /> : <span className="w-[14px]" />}
                                {action.label}
                            </button>
                        );
                    })}
                </>
            )}

            {/* Add to Playlist */}
            {onAddToPlaylist && availablePlaylists.length > 0 && (
                <>
                    <div className="h-px bg-line-subtle" />
                    <div
                        className="relative"
                        onMouseEnter={() => {
                            if (closeTimer.current) {
                                clearTimeout(closeTimer.current);
                                closeTimer.current = null;
                            }
                            setShowAddSubmenu(true);
                        }}
                        onMouseLeave={() => {
                            // Delayed close so the cursor can travel into the submenu
                            closeTimer.current = setTimeout(() => setShowAddSubmenu(false), 250);
                        }}
                    >
                        <button
                            onClick={() => setShowAddSubmenu((v) => !v)}
                            className="w-full flex items-center gap-3 px-4 py-2 hover:bg-mx-hover text-[12px] text-ink-secondary hover:text-ok transition-colors text-left"
                        >
                            <Plus size={14} className="text-ok" /> Add to Playlist
                            <ChevronRight size={12} className="ml-auto text-ink-muted" />
                        </button>
                        {showAddSubmenu && (
                            <div
                                className="absolute left-full top-0 -ml-px bg-mx-panel border border-line-default rounded-mx-md shadow-mx-lg py-1 min-w-[200px] max-h-[320px] overflow-y-auto z-[110]"
                                style={{ paddingLeft: 4, marginLeft: -2 }}
                                onMouseEnter={() => {
                                    if (closeTimer.current) {
                                        clearTimeout(closeTimer.current);
                                        closeTimer.current = null;
                                    }
                                    setShowAddSubmenu(true);
                                }}
                                onMouseLeave={() => {
                                    closeTimer.current = setTimeout(
                                        () => setShowAddSubmenu(false),
                                        200
                                    );
                                }}
                            >
                                <input
                                    type="text"
                                    value={pSearch}
                                    onChange={(e) => setPSearch(e.target.value)}
                                    placeholder="Suchen…"
                                    autoFocus
                                    className="w-full px-3 py-1.5 mb-1 bg-mx-card border-b border-line-subtle text-[11px] text-ink-primary focus:outline-none"
                                    onClick={(e) => e.stopPropagation()}
                                />
                                {availablePlaylists
                                    .filter(
                                        (pl) =>
                                            !pSearch ||
                                            (pl.Name || '')
                                                .toLowerCase()
                                                .includes(pSearch.toLowerCase())
                                    )
                                    .map((pl) => (
                                        <button
                                            key={pl.ID}
                                            onClick={() => {
                                                onAddToPlaylist(
                                                    pl.ID,
                                                    contextMenu.track.id || contextMenu.track.ID
                                                );
                                                setContextMenu(null);
                                            }}
                                            className="w-full flex items-center gap-2 px-4 py-1.5 hover:bg-mx-hover text-[12px] text-ink-secondary hover:text-ink-primary transition-colors truncate"
                                        >
                                            <ListMusic
                                                size={12}
                                                className="text-amber2/60 shrink-0"
                                            />
                                            <span className="truncate">{pl.Name}</span>
                                        </button>
                                    ))}
                            </div>
                        )}
                    </div>
                </>
            )}

            {/* Remove from Playlist */}
            {onRemove && (
                <>
                    <div className="h-px bg-line-subtle" />
                    <button
                        onClick={() => {
                            onRemove(contextMenu.track.id || contextMenu.track.ID);
                            setContextMenu(null);
                        }}
                        className="w-full flex items-center gap-3 px-4 py-2 hover:bg-amber2/10 text-[12px] text-ink-secondary hover:text-amber2 transition-colors text-left"
                    >
                        <X size={14} /> Remove from Playlist
                    </button>
                </>
            )}

            {/* Delete from Collection */}
            {onDelete && (
                <>
                    <div className="h-px bg-line-subtle" />
                    <button
                        onClick={async () => {
                            const ok = await confirmModal({
                                title: 'Delete track permanently?',
                                message: `Are you sure you want to PERMANENTLY delete "${contextMenu.track.Title}" from the library?`,
                                confirmLabel: 'Delete',
                                danger: true,
                            });
                            if (ok) {
                                onDelete(contextMenu.track.id || contextMenu.track.ID);
                            }
                            setContextMenu(null);
                        }}
                        className="w-full flex items-center gap-3 px-4 py-2 hover:bg-bad/10 text-[12px] text-ink-secondary hover:text-bad transition-colors text-left"
                    >
                        <Trash2 size={14} /> Delete from Collection
                    </button>
                </>
            )}
        </div>
    );
};

export default memo(TrackTable);
