import React, { useState, useMemo, useEffect } from 'react';
import { Music, Star, X, Check, ChevronDown, ChevronUp, ChevronRight, Image as ImageIcon, Scissors, Trash2, Play, Plus, ListMusic, FolderOpen, Copy, Info, Tag } from 'lucide-react';
import api from '../api/api';
import toast from 'react-hot-toast';
import { confirmModal } from './ConfirmModal';
import { promptModal } from './PromptModal';
import { log } from '../utils/log';
import { useVirtualRows } from '../hooks/useVirtualRows';

// Fixed row height (px). The artwork cell (36px) + p-1 padding is the
// tallest content; enforced per <tr> so the virtualizer math is exact.
const ROW_HEIGHT = 44;

const DEFAULT_COLUMNS = [
    { id: 'index', label: '#', width: '32px', align: 'right', fixed: true },
    { id: 'preview', label: 'Prev', width: '40px', align: 'center', fixed: true },
    { id: 'artwork', label: 'Art', width: '48px', align: 'center' },
    { id: 'Title', label: 'Title', width: '25%', sortable: true },
    { id: 'Artist', label: 'Artist', width: '20%', sortable: true },
    { id: 'Album', label: 'Album', width: '20%', sortable: true },
    { id: 'BPM', label: 'BPM', width: '48px', align: 'center', sortable: true },
    { id: 'Key', label: 'Key', width: '64px', align: 'center', sortable: true },
    { id: 'Rating', label: 'Rating', width: '64px', align: 'center', sortable: true },
    { id: 'Color', label: 'C', width: '32px', align: 'center' },
    { id: 'Bitrate', label: 'kbps', width: '64px', align: 'center', sortable: true },
    { id: 'PlayCount', label: 'Plays', width: '48px', align: 'center', sortable: true },
    { id: 'Composer', label: 'Composer', width: '150px', sortable: true },
    { id: 'Remixer', label: 'Remixer', width: '150px', sortable: true },
    { id: 'TotalTime', label: 'Time', width: '64px', align: 'center', sortable: true },
    { id: 'DateAdded', label: 'Date Added', width: '96px', align: 'right' },
    { id: 'actions', label: '', width: '40px', align: 'right', fixed: true }
];

const CAMELOT_COLORS = {
    // Camelot
    '1A': '#1DB954', '1B': '#1DB954', '2A': '#39D353', '2B': '#39D353',
    '3A': '#A6E22E', '3B': '#A6E22E', '4A': '#E6DB74', '4B': '#E6DB74',
    '5A': '#FD971F', '5B': '#FD971F', '6A': '#F92672', '6B': '#F92672',
    '7A': '#AE81FF', '7B': '#AE81FF', '8A': '#66D9EF', '8B': '#66D9EF',
    '9A': '#2AC1BC', '9B': '#2AC1BC', '10A': '#00A8FF', '10B': '#00A8FF',
    '11A': '#0097E6', '11B': '#0097E6', '12A': '#3E2479', '12B': '#3E2479',
    // Traditional mapping
    'ABM': '#1DB954', 'G#M': '#1DB954', 'B': '#1DB954',
    'EBM': '#39D353', 'D#M': '#39D353', 'GB': '#39D353', 'F#': '#39D353',
    'BBM': '#A6E22E', 'A#M': '#A6E22E', 'DB': '#A6E22E', 'C#': '#A6E22E',
    'FM': '#E6DB74', 'AB': '#E6DB74', 'G#': '#E6DB74',
    'CM': '#FD971F', 'EB': '#FD971F', 'D#': '#FD971F',
    'GM': '#F92672', 'BB': '#F92672', 'A#': '#F92672',
    'DM': '#AE81FF', 'F': '#AE81FF',
    'AM': '#66D9EF', 'C': '#66D9EF',
    'EM': '#2AC1BC', 'G': '#2AC1BC',
    'BM': '#00A8FF', 'D': '#00A8FF',
    'F#M': '#0097E6', 'GBM': '#0097E6', 'A': '#0097E6',
    'DBM': '#3E2479', 'C#M': '#3E2479', 'E': '#3E2479'
};

const getKeyColor = (key) => {
    if (!key) return null;
    const cleanKey = key.trim().toUpperCase();
    return CAMELOT_COLORS[cleanKey] || '#888';
};

const TrackTable = ({ tracks = [], onSelectTrack, onEditTrack, onPlay, onReorder, onRemove, onDelete, onAddToPlaylist, availablePlaylists = [], playlistId, customColumns, variant = 'default', onSortedTracksChange }) => {
    const [sortConfig, setSortConfig] = useState({ key: null, direction: 'asc' });
    const [visibleColumns, setVisibleColumns] = useState(() => {
        const saved = localStorage.getItem('track_table_columns');
        return saved ? JSON.parse(saved) : DEFAULT_COLUMNS.map(c => c.id);
    });
    const [headerMenu, setHeaderMenu] = useState(null);
    const [contextMenu, setContextMenu] = useState(null);

    useEffect(() => {
        localStorage.setItem('track_table_columns', JSON.stringify(visibleColumns));
    }, [visibleColumns]);

    const handleSort = (key) => {
        setSortConfig(prev => {
            if (prev.key !== key) return { key, direction: 'asc' };
            if (prev.direction === 'asc') return { key, direction: 'desc' };
            return { key: null, direction: 'asc' };
        });
    };

    const sortedTracks = useMemo(() => {
        if (!sortConfig.key) return tracks;

        return [...tracks].sort((a, b) => {
            let aVal = a[sortConfig.key];
            let bVal = b[sortConfig.key];

            // Handle numeric values (BPM, Rating, etc)
            if (typeof aVal === 'number' && typeof bVal === 'number') {
                return sortConfig.direction === 'asc' ? aVal - bVal : bVal - aVal;
            }

            // Fallback to string comparison
            aVal = String(aVal || "").toLowerCase();
            bVal = String(bVal || "").toLowerCase();

            if (aVal < bVal) return sortConfig.direction === 'asc' ? -1 : 1;
            if (aVal > bVal) return sortConfig.direction === 'asc' ? 1 : -1;
            return 0;
        });
    }, [tracks, sortConfig]);

    useEffect(() => {
        if (onSortedTracksChange) {
            onSortedTracksChange(sortedTracks);
        }
    }, [sortedTracks, onSortedTracksChange]);

    // Virtualize: render only the rows in/near the viewport. Without this,
    // a 100k-track library mounts 100k <tr> nodes and freezes the browser.
    const { scrollRef, startIndex, endIndex, padTop, padBottom } = useVirtualRows({
        rowCount: sortedTracks.length,
        rowHeight: ROW_HEIGHT,
    });
    const visibleTracks = sortedTracks.slice(startIndex, endIndex);

    const toggleColumn = (colId) => {
        setVisibleColumns(prev => {
            if (prev.includes(colId)) return prev.filter(c => c !== colId);
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

    const formatTime = (seconds) => {
        if (!seconds) return '-';
        const m = Math.floor(seconds / 60);
        const s = Math.floor(seconds % 60);
        return `${m}:${s.toString().padStart(2, '0')}`;
    };

    const openSoundCloud = (track) => {
        if (!track) return;
        const query = encodeURIComponent(`${track.Artist} ${track.Title}`);
        window.open(`https://soundcloud.com/search?q=${query}`, '_blank');
    };

    return (
        <div ref={scrollRef} className={`h-full overflow-auto relative ${variant === 'default' ? 'bg-mx-shell border border-line-subtle rounded-mx-md mx-2 mb-2 pb-20' : ''}`}>
            <table className="w-full text-left border-collapse min-w-[800px] table-fixed">
                <thead className="sticky top-0 z-10 select-none" style={{ background: 'var(--mx-shell)', borderBottom: '1px solid var(--line-subtle)' }}>
                    <tr onContextMenu={(e) => {
                        e.preventDefault();
                        setHeaderMenu({ x: e.clientX, y: e.clientY });
                        setContextMenu(null);
                    }}>
                        {DEFAULT_COLUMNS.map(col => {
                            if (!visibleColumns.includes(col.id)) return null;
                            return (
                                <th
                                    key={col.id}
                                    style={{ width: col.width, textAlign: col.align || 'left' }}
                                    onClick={() => col.sortable && handleSort(col.id)}
                                    className={`p-2 text-[10px] font-semibold text-ink-muted uppercase tracking-wider ${col.sortable ? 'cursor-pointer hover:text-amber2 transition-colors' : ''}`}
                                >
                                    <div className="flex items-center gap-1 justify-between">
                                        <span className={col.align === 'center' ? 'mx-auto' : (col.align === 'right' ? 'ml-auto' : '')}>{col.label}</span>
                                        {sortConfig.key === col.id && (
                                            sortConfig.direction === 'asc' ? <ChevronUp size={10} /> : <ChevronDown size={10} />
                                        )}
                                    </div>
                                </th>
                            );
                        })}
                        {customColumns && customColumns.map(col => (
                            <th key={col.id} style={{ width: col.width }} className="p-2 text-[10px] font-semibold text-ink-muted uppercase tracking-wider text-center">{col.label}</th>
                        ))}
                    </tr>
                </thead>
                <tbody>
                    {padTop > 0 && (
                        <tr aria-hidden="true" style={{ height: padTop }}>
                            <td colSpan={99} className="p-0 border-0" />
                        </tr>
                    )}
                    {visibleTracks.map((t, i) => {
                        const index = startIndex + i;
                        return (
                        <tr
                            key={t.id || index}
                            onClick={() => onSelectTrack && onSelectTrack(t)}
                            onDoubleClick={() => onPlay ? onPlay(t) : (onEditTrack && onEditTrack(t))}
                            onContextMenu={(e) => {
                                e.preventDefault();
                                setContextMenu({ x: e.clientX, y: e.clientY, track: t });
                                setHeaderMenu(null);
                            }}
                            className="group transition-colors cursor-pointer text-[12px] hover:bg-mx-hover"
                            style={{ height: ROW_HEIGHT, borderBottom: '1px solid var(--line-subtle)' }}
                            draggable={!!onReorder}
                            onDragStart={(e) => {
                                if (onReorder) {
                                    e.dataTransfer.setData("application/json", JSON.stringify({ type: 'track', playlistId, trackId: t.id, index }));
                                    e.dataTransfer.effectAllowed = "move";
                                }
                            }}
                            onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; }}
                            onDrop={(e) => {
                                e.preventDefault();
                                try {
                                    const data = JSON.parse(e.dataTransfer.getData("application/json"));
                                    if (onReorder && data.type === 'track' && data.playlistId === playlistId && data.trackId !== t.id) {
                                        onReorder(data.trackId, index);
                                    }
                                } catch (err) {
                                    // Drop payload wasn't our JSON shape (e.g. native OS drag) — ignore.
                                    log.debug('TrackTable drop JSON parse failed', err);
                                }
                            }}
                        >
                            {visibleColumns.includes('index') && (
                                <td className="p-1 font-mono text-ink-muted text-right pr-2 text-[11px]">{index + 1}</td>
                            )}
                            {visibleColumns.includes('preview') && (
                                <td
                                    className="p-1 text-center opacity-50 hover:opacity-100 cursor-pointer hover:text-amber2"
                                    onClick={(e) => { e.stopPropagation(); onPlay && onPlay(t); }}
                                >
                                    <Play size={12} className="mx-auto fill-current" />
                                </td>
                            )}
                            {visibleColumns.includes('artwork') && (
                                <td className="p-1 px-2 text-center w-[48px]">
                                    {t.Artwork ? (
                                        <div className="w-9 h-9 rounded-mx-sm overflow-hidden mx-auto bg-mx-card border border-line-subtle relative group-hover:scale-105 transition-transform">
                                            <img
                                                src={`${api.defaults.baseURL || ''}/api/artwork?path=${encodeURIComponent(t.Artwork)}`}
                                                alt={t.Title}
                                                className="w-full h-full object-cover"
                                                loading="lazy"
                                                onError={(e) => {
                                                    e.target.style.display = 'none';
                                                    e.target.parentElement.classList.add('flex', 'items-center', 'justify-center');
                                                    if (!e.target.parentElement.querySelector('svg')) {
                                                        e.target.parentElement.innerHTML = '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="text-slate-700"><rect width="18" height="18" x="3" y="3" rx="2" ry="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/></svg>';
                                                    }
                                                }}
                                            />
                                        </div>
                                    ) : (
                                        <div className="w-9 h-9 bg-mx-card rounded-mx-sm border border-line-subtle flex items-center justify-center mx-auto text-ink-placeholder">
                                            <ImageIcon size={14} />
                                        </div>
                                    )}
                                </td>
                            )}
                            {visibleColumns.includes('Title') && (
                                <td className="p-1 px-2 font-medium text-ink-primary group-hover:text-amber2 transition-colors truncate" title={t.Title}>{t.Title}</td>
                            )}
                            {visibleColumns.includes('Artist') && (
                                <td className="p-1 text-ink-secondary truncate" title={t.Artist}>{t.Artist}</td>
                            )}
                            {visibleColumns.includes('Album') && (
                                <td className="p-1 text-ink-muted truncate" title={t.Album}>{t.Album || '-'}</td>
                            )}
                            {visibleColumns.includes('BPM') && (
                                <td className="p-1 text-amber2 text-center font-mono">{t.BPM ? parseFloat(t.BPM).toFixed(2) : '-'}</td>
                            )}
                            {visibleColumns.includes('Key') && (
                                <td className="p-1 text-center font-mono font-bold">
                                    <span
                                        className="px-2 py-0.5 rounded-full text-[9px] shadow-lg"
                                        style={{
                                            backgroundColor: `${getKeyColor(t.Key)}22`, // 22 is ~13% opacity
                                            color: getKeyColor(t.Key),
                                            border: `1px solid ${getKeyColor(t.Key)}44`
                                        }}
                                    >
                                        {t.Key || '-'}
                                    </span>
                                </td>
                            )}
                            {visibleColumns.includes('Color') && (
                                <td className="p-1 text-center">
                                    <ColorDot
                                        track={t}
                                        onChange={(newColor) => {
                                            api.patch('/api/tracks/batch', {
                                                track_ids: [t.id || t.ID],
                                                updates: { ColorID: newColor }
                                            }).then(() => { t.ColorID = String(newColor); }).catch(() => toast.error('Color speichern fehlgeschlagen'));
                                        }}
                                    />
                                </td>
                            )}
                            {visibleColumns.includes('Rating') && (
                                <td className="p-1 text-center">
                                    <div className="flex justify-center gap-0.5 opacity-40 group-hover:opacity-100">
                                        {[1, 2, 3, 4, 5].map(star => (
                                            <Star
                                                key={star}
                                                size={11}
                                                fill={star <= (t.Rating || 0) ? "currentColor" : "none"}
                                                className={`cursor-pointer transition-transform hover:scale-125 ${
                                                    star <= (t.Rating || 0) ? "text-amber2" : "text-ink-placeholder hover:text-amber2/60"
                                                }`}
                                                onClick={(e) => {
                                                    e.stopPropagation();
                                                    // Toggle: clicking the current rating clears it
                                                    const newRating = (t.Rating || 0) === star ? 0 : star;
                                                    api.patch('/api/tracks/batch', {
                                                        track_ids: [t.id || t.ID],
                                                        updates: { Rating: newRating }
                                                    }).then(() => {
                                                        // Optimistic local update so the UI reacts immediately
                                                        t.Rating = newRating;
                                                    }).catch(() => toast.error('Rating speichern fehlgeschlagen'));
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
                                { id: 'Remixer', value: t.Remixer }
                            ].map(field => visibleColumns.includes(field.id) && (
                                <td key={field.id} className={`p-1 truncate ${field.id === 'Bitrate' || field.id === 'PlayCount' ? 'text-center font-mono text-ink-secondary' : 'text-ink-muted'}`} title={field.value}>
                                    {field.value || '-'}
                                </td>
                            ))}
                            {visibleColumns.includes('TotalTime') && (
                                <td className="p-1 text-ink-secondary text-center font-mono">{formatTime(t.TotalTime)}</td>
                            )}
                            {visibleColumns.includes('DateAdded') && (
                                <td className="p-1 text-ink-muted text-right pr-2 text-[10px] font-mono">{t.DateAdded || '-'}</td>
                            )}
                            {customColumns && customColumns.map(col => (
                                <td key={col.id} className="p-1">{col.render ? col.render(t) : '-'}</td>
                            ))}
                            {visibleColumns.includes('actions') && (
                                <td className="p-1 text-right pr-4">
                                    {onRemove && (
                                        <button
                                            onClick={(e) => { e.stopPropagation(); onRemove(t.id); }}
                                            className="p-1 px-2 hover:bg-bad/10 rounded-mx-sm text-bad/60 hover:text-bad transition-all opacity-0 group-hover:opacity-100"
                                        >
                                            <X size={12} />
                                        </button>
                                    )}
                                </td>
                            )}
                        </tr>
                        );
                    })}
                    {padBottom > 0 && (
                        <tr aria-hidden="true" style={{ height: padBottom }}>
                            <td colSpan={99} className="p-0 border-0" />
                        </tr>
                    )}
                </tbody>
            </table>

            {/* Column Menu */}
            {headerMenu && (
                <div
                    className="fixed z-[100] bg-mx-panel border border-line-default rounded-mx-md shadow-mx-lg py-1.5 min-w-[160px] animate-fade-in"
                    style={{ top: headerMenu.y, left: headerMenu.x }}
                    onClick={(e) => e.stopPropagation()}
                >
                    <div className="mx-caption px-3 py-1.5 border-b border-line-subtle mb-1">Toggle Columns</div>
                    {DEFAULT_COLUMNS.map(col => {
                        if (col.fixed) return null;
                        return (
                            <button
                                key={col.id}
                                onClick={() => toggleColumn(col.id)}
                                className="w-full flex items-center justify-between px-3 py-1.5 hover:bg-mx-hover text-[12px] text-ink-secondary hover:text-ink-primary transition-colors"
                            >
                                <span>{col.label}</span>
                                {visibleColumns.includes(col.id) && <Check size={12} className="text-amber2" />}
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
                />
            )
            }
        </div >
    );
};

// Pioneer color palette — IDs 0-8 (None, Pink, Red, Orange, Yellow, Green, Aqua, Blue, Purple)
const PIONEER_COLORS = [
    { id: '0', name: 'Keine', hex: 'transparent', border: 'var(--line-default)' },
    { id: '1', name: 'Pink',   hex: '#ff007f' },
    { id: '2', name: 'Red',    hex: '#ff0000' },
    { id: '3', name: 'Orange', hex: '#ff7f00' },
    { id: '4', name: 'Yellow', hex: '#ffd700' },
    { id: '5', name: 'Green',  hex: '#00d000' },
    { id: '6', name: 'Aqua',   hex: '#00c8ff' },
    { id: '7', name: 'Blue',   hex: '#0070ff' },
    { id: '8', name: 'Purple', hex: '#a000ff' },
];

const ColorDot = ({ track, onChange }) => {
    const [open, setOpen] = useState(false);
    const ref = React.useRef(null);
    const cur = String(track.ColorID || '0');
    const color = PIONEER_COLORS.find(c => c.id === cur) || PIONEER_COLORS[0];

    useEffect(() => {
        if (!open) return;
        const onDoc = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
        document.addEventListener('mousedown', onDoc);
        return () => document.removeEventListener('mousedown', onDoc);
    }, [open]);

    return (
        <div className="relative inline-block" ref={ref}>
            <button
                onClick={(e) => { e.stopPropagation(); setOpen(v => !v); }}
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
                    {PIONEER_COLORS.map(c => (
                        <button
                            key={c.id}
                            onClick={(e) => {
                                e.stopPropagation();
                                onChange(c.id);
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

const TrackContextMenuPopup = ({ contextMenu, onEditTrack, onPlay, openSoundCloud, onRemove, onDelete, onAddToPlaylist, availablePlaylists, setContextMenu }) => {
    const [showAddSubmenu, setShowAddSubmenu] = useState(false);
    const [pSearch, setPSearch] = useState("");
    const closeTimer = React.useRef(null);
    React.useEffect(() => () => { if (closeTimer.current) clearTimeout(closeTimer.current); }, []);
    const t = contextMenu.track;
    const trackPath = t.path || t.Path || t.Location || "";

    const handleReveal = async () => {
        try {
            await api.post('/api/file/reveal', { path: trackPath });
        } catch (e) { toast.error('Konnte Datei nicht im Explorer öffnen'); }
        setContextMenu(null);
    };
    const handleCopy = () => {
        const text = `${t.Artist || '?'} - ${t.Title || '?'}`;
        navigator.clipboard.writeText(text).then(
            () => toast.success(`Kopiert: ${text}`),
            () => toast.error('Clipboard-Zugriff verweigert'),
        );
        setContextMenu(null);
    };
    const handleEditMeta = async () => {
        const newBpm = await promptModal({
            title: 'Edit BPM',
            message: 'BPM:',
            defaultValue: String(Math.round(t.BPM || 0)),
        });
        if (newBpm === null) { setContextMenu(null); return; }
        const newKey = await promptModal({
            title: 'Edit Key',
            message: 'Key (z.B. Am, 8A):',
            defaultValue: t.Key || '',
        });
        if (newKey === null) { setContextMenu(null); return; }
        try {
            await api.patch('/api/tracks/batch', {
                track_ids: [t.id || t.ID],
                updates: { BPM: parseFloat(newBpm) || 0, Key: newKey },
            });
            toast.success('Metadaten aktualisiert');
        } catch (e) { toast.error('Update fehlgeschlagen: ' + (e.response?.data?.detail || e.message)); }
        setContextMenu(null);
    };

    return (
        <div
            className="fixed z-[100] bg-mx-panel border border-line-default rounded-mx-md shadow-mx-lg min-w-[220px] animate-fade-in overflow-visible"
            style={{ top: contextMenu.y, left: contextMenu.x }}
            onClick={(e) => e.stopPropagation()}
        >
            <div className="mx-caption px-3 py-2 border-b border-line-subtle truncate max-w-[260px]">
                {t.Title}
            </div>
            {onPlay && (
                <button
                    onClick={() => { onPlay(t); setContextMenu(null); }}
                    className="w-full flex items-center gap-3 px-4 py-2 hover:bg-mx-hover text-[12px] text-ink-secondary hover:text-amber2 transition-colors text-left"
                >
                    <Play size={14} fill="currentColor" /> Abspielen
                </button>
            )}
            <button
                onClick={() => { onEditTrack && onEditTrack(t); setContextMenu(null); }}
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
                onClick={() => { openSoundCloud(t); setContextMenu(null); }}
                className="w-full flex items-center gap-3 px-4 py-2 hover:bg-[#ff5500]/10 text-[12px] text-ink-secondary hover:text-[#ff5500] transition-colors text-left"
            >
                <div className="w-3.5 h-3.5 bg-current mask-soundcloud" style={{ maskImage: 'url(https://a-v2.sndcdn.com/assets/images/sc-icons/ios-a62dfc8f.svg)', WebkitMaskImage: 'url(https://a-v2.sndcdn.com/assets/images/sc-icons/ios-a62dfc8f.svg)' }}></div>
                Auf SoundCloud öffnen
            </button>

            {/* Add to Playlist */}
            {onAddToPlaylist && availablePlaylists.length > 0 && (
                <>
                    <div className="h-px bg-line-subtle" />
                    <div
                        className="relative"
                        onMouseEnter={() => {
                            if (closeTimer.current) { clearTimeout(closeTimer.current); closeTimer.current = null; }
                            setShowAddSubmenu(true);
                        }}
                        onMouseLeave={() => {
                            // Delayed close so the cursor can travel into the submenu
                            closeTimer.current = setTimeout(() => setShowAddSubmenu(false), 250);
                        }}
                    >
                        <button
                            onClick={() => setShowAddSubmenu(v => !v)}
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
                                    if (closeTimer.current) { clearTimeout(closeTimer.current); closeTimer.current = null; }
                                    setShowAddSubmenu(true);
                                }}
                                onMouseLeave={() => {
                                    closeTimer.current = setTimeout(() => setShowAddSubmenu(false), 200);
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
                                    .filter(pl => !pSearch || (pl.Name || '').toLowerCase().includes(pSearch.toLowerCase()))
                                    .map(pl => (
                                        <button
                                            key={pl.ID}
                                            onClick={() => {
                                                onAddToPlaylist(pl.ID, contextMenu.track.id || contextMenu.track.ID);
                                                setContextMenu(null);
                                            }}
                                            className="w-full flex items-center gap-2 px-4 py-1.5 hover:bg-mx-hover text-[12px] text-ink-secondary hover:text-ink-primary transition-colors truncate"
                                        >
                                            <ListMusic size={12} className="text-amber2/60 shrink-0" />
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

export default TrackTable;
