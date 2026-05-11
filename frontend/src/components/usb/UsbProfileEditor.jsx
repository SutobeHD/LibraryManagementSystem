/**
 * UsbProfileEditor — playlist selection + USB-library contents browser.
 *
 * Two cards stacked vertically:
 *   1. "Select Playlists" — checkbox tree built from the PC playlist tree
 *      passed in via props. Toggling a folder selects/deselects everything
 *      underneath.
 *   2. "USB Library" — sidebar of playlists parsed from the stick's
 *      rekordbox.xml plus a flat track table. Switchable between the
 *      newer (library_one) and legacy (library_legacy) formats.
 *
 * State is intentionally local to this component:
 *   • the expanded/collapsed playlist tree state (per node)
 *   • the selectedPlaylist in the contents viewer
 *   • the search box in the contents viewer
 *
 * All mutations (toggling a sync_playlists entry, switching active library)
 * fan up to the container via callbacks.
 */
import React, { useMemo, useState } from 'react';
import {
    Database, ChevronDown, ChevronRight, ListMusic, Loader2, Music,
} from 'lucide-react';
import { PlaylistTreeNode, PillTab } from './UsbControls';

// ────────────────────────────────────────────────────────────────────
//  USB-side playlist tree node (inside contents viewer)
// ────────────────────────────────────────────────────────────────────

const UsbPlaylistTreeNode = ({ node, onSelect, selectedName }) => {
    const [open, setOpen] = useState(true);
    const isFolder = node.type === '0';
    const isSelected = selectedName === node.name;
    return (
        <div>
            <button
                onClick={() => isFolder ? setOpen(o => !o) : onSelect(node)}
                className={`w-full text-left flex items-center gap-2 px-3 py-1 transition-colors ${
                    isSelected ? 'bg-amber2/15 text-amber2' : 'text-ink-secondary hover:bg-white/5'
                }`}
                title={node.name}
            >
                {isFolder ? (
                    open ? <ChevronDown size={10} className="text-amber-500/60" /> : <ChevronRight size={10} className="text-amber-500/60" />
                ) : (
                    <ListMusic size={10} className="text-amber2/50" />
                )}
                <span className="text-[11px] flex-1 truncate">{node.name}</span>
                {!isFolder && (
                    <span className="text-[10px] text-ink-muted font-mono">{(node.track_keys || []).length}</span>
                )}
            </button>
            {isFolder && open && (node.children || []).map((c, i) => (
                <div key={i} style={{ paddingLeft: 12 }}>
                    <UsbPlaylistTreeNode node={c} onSelect={onSelect} selectedName={selectedName} />
                </div>
            ))}
        </div>
    );
};

// ────────────────────────────────────────────────────────────────────
//  USB Library panel — contents viewer (sidebar + flat table)
// ────────────────────────────────────────────────────────────────────

/**
 * USB-Library panel — renders the stick like a normal music library:
 *   sidebar = playlist tree (parsed from PIONEER/rekordbox.xml <PLAYLISTS>)
 *   main    = flat track table (filterable)
 *
 * Falls back gracefully when the stick has tracks but no playlist tree
 * (e.g. exportLibrary.db that we couldn't decrypt) — then it's just the
 * flat track table.
 */
const UsbLibraryPanel = ({ usbTracks, activeLibrary, setActiveLibrary, loadingContents }) => {
    const [selectedPlaylist, setSelectedPlaylist] = useState(null);
    const [search, setSearch] = useState('');

    const flatKey = activeLibrary === 'library_one' ? 'library_one_flat' : 'library_legacy_flat';
    const allTracks = usbTracks[flatKey] || [];
    const playlists = activeLibrary === 'library_legacy' ? (usbTracks.library_legacy_playlists || []) : [];

    // Build minimal id-set from selected playlist (track_keys point at TrackID)
    const filteredTracks = useMemo(() => {
        let list = allTracks;
        if (selectedPlaylist) {
            const keep = new Set((selectedPlaylist.track_keys || []).map(String));
            list = list.filter(t => keep.has(String(t.ID)));
        }
        if (search) {
            const q = search.toLowerCase();
            list = list.filter(t =>
                (t.Title || '').toLowerCase().includes(q) ||
                (t.ArtistName || '').toLowerCase().includes(q) ||
                (t.Album || '').toLowerCase().includes(q)
            );
        }
        return list;
    }, [allTracks, selectedPlaylist, search]);

    // Tree structure: type "0" = folder, "1" = playlist, "4" = smart
    const playlistTree = useMemo(() => {
        // Flatten parent strings into a 2-level grouped list (folder → playlists).
        const folders = playlists.filter(p => p.type === '0');
        const leaves = playlists.filter(p => p.type !== '0');
        const tree = [
            ...folders.map(f => ({
                ...f,
                children: leaves.filter(l => l.parent === f.name),
            })),
            // Top-level playlists (parent="ROOT" or no matching folder)
            ...leaves.filter(l => l.parent === 'ROOT' || !folders.find(f => f.name === l.parent)),
        ];
        return tree;
    }, [playlists]);

    const formatBPM = (b) => b ? (b / 100).toFixed(1) : '—';
    const formatDur = (sec) => {
        if (!sec) return '—';
        const m = Math.floor(sec / 60), s = sec % 60;
        return `${m}:${String(s).padStart(2, '0')}`;
    };

    return (
        <div className="mx-card overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 border-b border-line-subtle">
                <div className="flex items-center gap-2">
                    <Database size={12} className="text-amber2" />
                    <span className="mx-caption">USB Library</span>
                    <span className="text-[10px] text-ink-muted font-mono">
                        · {allTracks.length} tracks{playlists.length ? ` · ${playlists.length} playlists` : ''}
                    </span>
                </div>
                <div className="flex gap-2 items-center">
                    <input
                        value={search}
                        onChange={e => setSearch(e.target.value)}
                        placeholder="Suchen…"
                        className="px-2 py-1 bg-mx-input border border-line-subtle rounded text-tiny w-40"
                    />
                    <div className="flex gap-1 bg-mx-input p-0.5 rounded-mx-sm border border-line-subtle">
                        <PillTab active={activeLibrary === 'library_one'} onClick={() => { setActiveLibrary('library_one'); setSelectedPlaylist(null); }}>One</PillTab>
                        <PillTab active={activeLibrary === 'library_legacy'} onClick={() => { setActiveLibrary('library_legacy'); setSelectedPlaylist(null); }}>Legacy</PillTab>
                    </div>
                </div>
            </div>

            {loadingContents ? (
                <div className="p-12 flex flex-col items-center gap-3 text-ink-muted text-tiny">
                    <Loader2 size={20} className="animate-spin text-amber2" />
                    Reading USB database…
                </div>
            ) : allTracks.length === 0 ? (
                <div className="p-12 flex flex-col items-center gap-2 text-ink-placeholder text-center">
                    <Music size={28} strokeWidth={1.2} />
                    <p className="text-tiny">No tracks in {activeLibrary === 'library_one' ? 'Newer' : 'Legacy'} format</p>
                    <p className="text-[10px]">Run sync to populate</p>
                </div>
            ) : (
                <div className="flex" style={{ maxHeight: 500 }}>
                    {/* Playlist sidebar */}
                    {activeLibrary === 'library_legacy' && playlists.length > 0 && (
                        <div className="w-56 border-r border-line-subtle overflow-y-auto py-1 shrink-0">
                            <button
                                onClick={() => setSelectedPlaylist(null)}
                                className={`w-full text-left flex items-center gap-2 px-3 py-1.5 transition-colors ${
                                    !selectedPlaylist ? 'bg-amber2/10 text-amber2' : 'text-ink-secondary hover:bg-white/5'
                                }`}
                            >
                                <Database size={11} />
                                <span className="text-[11px] font-semibold flex-1">All Tracks</span>
                                <span className="text-[10px] text-ink-muted font-mono">{allTracks.length}</span>
                            </button>
                            {playlistTree.map((node, i) => (
                                <UsbPlaylistTreeNode
                                    key={i}
                                    node={node}
                                    selected={selectedPlaylist?.name === node.name}
                                    onSelect={setSelectedPlaylist}
                                    selectedName={selectedPlaylist?.name}
                                />
                            ))}
                        </div>
                    )}

                    {/* Track list */}
                    <div className="flex-1 overflow-y-auto">
                        <table className="w-full text-tiny">
                            <thead className="sticky top-0 bg-mx-shell border-b border-line-subtle">
                                <tr className="text-ink-muted text-[10px] uppercase tracking-wider">
                                    <th className="text-left px-3 py-2 font-semibold">Title</th>
                                    <th className="text-left px-3 py-2 font-semibold">Artist</th>
                                    <th className="text-left px-3 py-2 font-semibold">Album</th>
                                    <th className="text-center px-2 py-2 font-semibold w-14">BPM</th>
                                    <th className="text-center px-2 py-2 font-semibold w-12">Key</th>
                                    <th className="text-right px-3 py-2 font-semibold w-14">Time</th>
                                </tr>
                            </thead>
                            <tbody>
                                {filteredTracks.map((t, i) => (
                                    <tr key={i} className="border-b border-line-subtle/30 hover:bg-mx-hover transition-colors">
                                        <td className="px-3 py-1.5 text-ink-primary truncate max-w-[280px]" title={t.Title}>{t.Title || '—'}</td>
                                        <td className="px-3 py-1.5 text-ink-secondary truncate max-w-[200px]">{t.ArtistName || '—'}</td>
                                        <td className="px-3 py-1.5 text-ink-muted truncate max-w-[180px]">{t.Album || '—'}</td>
                                        <td className="px-2 py-1.5 text-center font-mono text-amber2">{formatBPM(t.BPM)}</td>
                                        <td className="px-2 py-1.5 text-center font-mono text-blue-300">{t.Key || '—'}</td>
                                        <td className="px-3 py-1.5 text-right text-ink-muted font-mono">{formatDur(t.TotalTime)}</td>
                                    </tr>
                                ))}
                                {filteredTracks.length === 0 && (
                                    <tr><td colSpan={6} className="px-3 py-8 text-center text-ink-placeholder text-[11px]">
                                        Keine Tracks {selectedPlaylist ? `in "${selectedPlaylist.name}"` : ''}{search ? ` für "${search}"` : ''}
                                    </td></tr>
                                )}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}
        </div>
    );
};

// ────────────────────────────────────────────────────────────────────
//  Public — playlist picker + USB library viewer
// ────────────────────────────────────────────────────────────────────

const UsbProfileEditor = ({
    playlistTree,
    selectedPlaylistIds,
    onTogglePlaylist,
    usbTracks,
    activeLibrary,
    setActiveLibrary,
    loadingContents,
}) => {
    return (
        <>
            {/* Playlist selection — ABOVE contents */}
            <div className="mx-card p-4">
                <div className="flex items-center justify-between mb-3">
                    <span className="mx-caption">Select Playlists</span>
                    <span className="text-[10px] font-mono text-amber2">
                        {selectedPlaylistIds.length} selected
                    </span>
                </div>
                <div className="max-h-64 overflow-y-auto pr-1 -mx-1">
                    {playlistTree.length > 0 ? playlistTree.map(node => (
                        <PlaylistTreeNode
                            key={node.ID}
                            node={node}
                            selectedIds={selectedPlaylistIds}
                            onToggle={onTogglePlaylist}
                        />
                    )) : (
                        <p className="text-ink-placeholder text-tiny text-center py-4">No playlists loaded</p>
                    )}
                </div>
            </div>

            {/* USB Library — playlist sidebar + flat track list */}
            <UsbLibraryPanel
                usbTracks={usbTracks}
                activeLibrary={activeLibrary}
                setActiveLibrary={setActiveLibrary}
                loadingContents={loadingContents}
            />
        </>
    );
};

export default UsbProfileEditor;
