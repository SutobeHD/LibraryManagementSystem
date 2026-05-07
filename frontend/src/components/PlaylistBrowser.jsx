import React, { useState, useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import api from '../api/api';
import { useToast } from './ToastContext';
import { Folder, ListMusic, ChevronRight, ChevronDown, Music, Database, Settings, Plus, Sparkles, RotateCw, MoreVertical, Edit2, Trash2, FolderPlus, ArrowRightLeft, X, Upload, Star, Tag, GripVertical, Library, Disc } from 'lucide-react';
import TrackTable from './TrackTable';
import SoundCloudProgressModal from './SoundCloudProgressModal';
import RenameModal from './RenameModal';
import SmartPlaylistEditor from './SmartPlaylistEditor';

const PlaylistNode = ({ node, level = 0, onSelect, onContextMenu, onMoveNode, onRename, selectedId }) => {
    const [open, setOpen] = useState(level < 1);
    const [dragOver, setDragOver] = useState(null); // "top", "center", "bottom"
    const isFolder = node.Type === "0";
    const isIntelligent = node.Type === "4";
    const isRegularPlaylist = node.Type === "1";

    const handleContextMenu = (e) => {
        e.preventDefault();
        e.stopPropagation();
        onContextMenu(e, node);
    };

    const handleDragStart = (e) => {
        if (isIntelligent) { e.preventDefault(); return; }
        e.dataTransfer.setData("application/json", JSON.stringify({ id: node.ID, type: node.Type }));
        e.dataTransfer.effectAllowed = "move";
    };

    const handleDragOver = (e) => {
        if (isIntelligent) return;
        e.preventDefault();
        e.stopPropagation();
        const rect = e.currentTarget.getBoundingClientRect();
        const y = e.clientY - rect.top;
        const h = rect.height;
        if (y < h * 0.25) setDragOver("top");
        else if (y > h * 0.75) setDragOver("bottom");
        else setDragOver("center");
        e.dataTransfer.dropEffect = "move";
    };

    const handleDragLeave = () => setDragOver(null);

    const handleDrop = (e) => {
        e.preventDefault();
        e.stopPropagation();
        setDragOver(null);
        try {
            const data = JSON.parse(e.dataTransfer.getData("application/json"));
            if (!data.id || data.id === node.ID) return;
            const position = dragOver === "top" ? "before" : dragOver === "bottom" ? "after" : "inside";
            if (onMoveNode) onMoveNode(data.id, node.ID, position);
        } catch (err) { console.error("Drop failed", err); }
    };

    const isSelected = selectedId === node.ID;

    return (
        <div data-pl-row={node.ID}>
            <div
                data-pl-id={node.ID}
                className={`flex items-center gap-2 px-3 py-1.5 cursor-pointer transition-all duration-150 group relative
                    ${isSelected ? 'bg-amber2/15 text-white' : 'text-ink-secondary hover:text-ink-primary hover:bg-white/5'}
                    ${dragOver === "center" ? 'ring-1 ring-amber2 bg-amber2/10' : ''}
                `}
                style={{ paddingLeft: `${12 + level * 16}px` }}
                onClick={() => {
                    if (isFolder) setOpen(!open);
                    else onSelect(node);
                }}
                onContextMenu={handleContextMenu}
                onAuxClick={(e) => { if (e.button === 2) handleContextMenu(e); }}
                draggable={!isIntelligent}
                onDragStart={handleDragStart}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
            >
                {dragOver === "top" && <div className="absolute top-0 left-0 right-0 h-0.5 bg-amber2 z-10" />}
                {dragOver === "bottom" && <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-amber2 z-10" />}

                {!isIntelligent && (
                    <GripVertical size={12} className="text-ink-placeholder/40 group-hover:text-ink-placeholder shrink-0 cursor-grab" />
                )}

                {isFolder ? (
                    <>
                        {open ? <ChevronDown size={14} className="text-amber-500 shrink-0" /> : <ChevronRight size={14} className="text-amber-500/60 shrink-0" />}
                        <Folder size={14} className="text-amber-500 shrink-0" />
                    </>
                ) : isIntelligent ? (
                    <>
                        <Sparkles size={14} className="text-purple-400 shrink-0" />
                    </>
                ) : (
                    <>
                        <ListMusic size={14} className="text-amber2/60 shrink-0" />
                    </>
                )}

                <span className={`text-[13px] truncate flex-1 ${isIntelligent ? 'text-purple-300' : ''} ${isSelected ? 'font-semibold' : ''}`}>
                    {node.Name}
                </span>

                {isIntelligent && (
                    <span className="text-[9px] text-purple-500/60 font-bold uppercase tracking-wider shrink-0">Smart</span>
                )}

                {!isIntelligent && (
                    <button
                        onClick={(e) => { e.stopPropagation(); onRename(node); }}
                        className="opacity-0 group-hover:opacity-100 p-1 hover:bg-white/10 rounded transition-all shrink-0"
                    >
                        <Edit2 size={11} className="text-ink-muted" />
                    </button>
                )}
            </div>
            {isFolder && open && node.Children && node.Children.map(child => (
                <PlaylistNode
                    key={child.ID}
                    node={child}
                    level={level + 1}
                    onSelect={onSelect}
                    onContextMenu={onContextMenu}
                    onMoveNode={onMoveNode}
                    onRename={onRename}
                    selectedId={selectedId}
                />
            ))}
        </div>
    );
};

const PlaylistBrowser = ({ onSelectTrack, onEditTrack, onPlayTrack, libraryStatus }) => {
    const toast = useToast();
    const [tree, setTree] = useState([]);
    const [selectedPlaylist, setSelectedPlaylist] = useState(null);
    const [showCollection, setShowCollection] = useState(false);
    const [tracks, setTracks] = useState([]);
    const [allTracks, setAllTracks] = useState([]);
    const [loading, setLoading] = useState(false);
    const [dbLoaded, setDbLoaded] = useState(true);
    const [isProcessing, setIsProcessing] = useState(false);
    const [contextMenu, setContextMenu] = useState(null);
    const [showSmartEditor, setShowSmartEditor] = useState(false);
    const [smartEditorParent, setSmartEditorParent] = useState("ROOT");
    const [smartEditorEditing, setSmartEditorEditing] = useState(null);
    const [scExporting, setScExporting] = useState(false);
    const [showScProgress, setShowScProgress] = useState(false);
    const [renameNode, setRenameNode] = useState(null);
    const [collectionSearch, setCollectionSearch] = useState('');
    const [playlistSearch, setPlaylistSearch] = useState('');
    const [displayTracks, setDisplayTracks] = useState([]);

    // Flatten tree to get all non-folder, non-intelligent playlists for "Add to Playlist" submenu
    const flattenPlaylists = (nodes) => {
        let result = [];
        for (const n of nodes) {
            if (n.Type === "1") result.push(n);
            if (n.Children) result = result.concat(flattenPlaylists(n.Children));
        }
        return result;
    };
    const allPlaylists = flattenPlaylists(tree);

    const loadTree = () => {
        setLoading(true);
        api.get('/api/playlists/tree')
            .then(res => {
                if (Array.isArray(res.data)) {
                    setDbLoaded(true);
                    setTree(res.data);
                } else {
                    setDbLoaded(false);
                }
            })
            .catch(err => {
                console.error("Failed to load playlist tree:", err);
                setDbLoaded(false);
            })
            .finally(() => setLoading(false));
    };

    const loadAllTracks = () => {
        api.get('/api/library/tracks')
            .then(res => {
                if (Array.isArray(res.data)) setAllTracks(res.data);
            })
            .catch(err => console.error("Failed to load all tracks", err));
    };

    useEffect(() => {
        if (libraryStatus?.loaded) {
            loadTree();
            loadAllTracks();
        }
    }, [libraryStatus?.loaded]);

    useEffect(() => {
        if (libraryStatus?.loaded) {
            loadTree();
            loadAllTracks();
        }
    }, []);

    const handleSelectCollection = () => {
        setSelectedPlaylist(null);
        setShowCollection(true);
        setPlaylistSearch('');
    };

    const handleSelect = (node) => {
        setSelectedPlaylist(node);
        setShowCollection(false);
        setLoading(true);
        setPlaylistSearch('');
        api.get(`/api/playlist/${node.ID}/tracks?_=${Date.now()}`).then(res => {
            setTracks(res.data);
            setLoading(false);
        });
    };

    const handleSmartPlaylists = async () => {
        setIsProcessing(true);
        try {
            await api.post('/api/library/smart-playlists', { artist_threshold: 3, label_threshold: 3 });
            loadTree();
            toast.success("Smart Playlists generated!");
        } catch (err) {
            toast.error("Failed to generate smart playlists.");
        } finally {
            setIsProcessing(false);
        }
    };

    const handleCleanTitles = async () => {
        const currentTracks = showCollection ? filteredCollectionTracks : tracks;
        if (!currentTracks.length) return;
        setIsProcessing(true);
        try {
            const trackIds = currentTracks.map(t => t.id);
            const res = await api.post('/api/library/clean-titles', { track_ids: trackIds });
            toast.success(`Cleaned ${res.data.success.length} titles!`);
            if (selectedPlaylist) handleSelect(selectedPlaylist);
            else loadAllTracks();
        } catch (err) {
            toast.error("Cleanup failed.");
        } finally {
            setIsProcessing(false);
        }
    };

    const handleCreatePlaylist = async () => {
        const name = prompt("Enter playlist name:");
        if (!name) return;
        try {
            const parentId = contextMenu?.node?.Type === "0" ? contextMenu.node.ID : (selectedPlaylist?.Type === "0" ? selectedPlaylist.ID : "ROOT");
            await api.post('/api/playlists/create', { name, parent_id: parentId });
            loadTree();
            toast.success("Playlist created!");
            setContextMenu(null);
        } catch (err) {
            toast.error("Failed to create playlist.");
        }
    };

    const handleCreateFolder = async () => {
        const name = prompt("Enter folder name:");
        if (!name) return;
        try {
            const parentId = contextMenu?.node?.Type === "0" ? contextMenu.node.ID : (selectedPlaylist?.Type === "0" ? selectedPlaylist.ID : "ROOT");
            await api.post('/api/playlists/create', { name, type: "0", parent_id: parentId });
            loadTree();
            toast.success("Folder created!");
            setContextMenu(null);
        } catch (err) {
            toast.error("Failed to create folder.");
        }
    };

    const handleRename = (node) => {
        setRenameNode(node);
        setContextMenu(null);
    };

    const confirmRename = async (newName) => {
        if (!renameNode || !newName || newName === renameNode.Name) {
            setRenameNode(null);
            return;
        }
        try {
            await api.post('/api/playlists/rename', { pid: renameNode.ID, name: newName });
            loadTree();
            toast.success("Renamed successfully");
        } catch (err) { toast.error("Failed to rename."); }
        setRenameNode(null);
    };

    const handleDuplicate = async (node) => {
        try {
            const newName = `${node.Name} (Kopie)`;
            if (node.Type === "4") {
                await api.post('/api/playlists/smart/create', {
                    name: newName,
                    parent_id: node.ParentID || 'ROOT',
                    criteria: node.SmartList || {},
                });
            } else {
                // Normal playlist or folder: create + copy tracks
                const res = await api.post('/api/playlists/create', {
                    name: newName, parent_id: node.ParentID || 'ROOT',
                    type: node.Type === '0' ? '0' : '1',
                });
                const newId = res.data?.id;
                if (newId && node.Type === '1') {
                    const tracks = await api.get(`/api/playlist/${node.ID}/tracks`);
                    for (const t of (tracks.data || [])) {
                        const tid = t.id || t.ID;
                        if (tid) await api.post('/api/playlists/add-track', { pid: newId, track_id: String(tid) });
                    }
                }
            }
            loadTree();
            toast.success(`"${node.Name}" dupliziert`);
        } catch (e) {
            toast.error('Duplizieren fehlgeschlagen');
        }
        setContextMenu(null);
    };

    const handleDelete = async (node) => {
        if (!confirm(`Delete "${node.Name}"? This cannot be undone.`)) return;
        try {
            await api.post('/api/playlists/delete', { pid: node.ID });
            loadTree();
            if (selectedPlaylist?.ID === node.ID) {
                setSelectedPlaylist(null);
                setShowCollection(true);
            }
            toast.success(`"${node.Name}" deleted.`);
        } catch (err) { toast.error("Failed to delete."); }
        setContextMenu(null);
    };

    const handleRemoveTrack = async (trackId) => {
        if (!selectedPlaylist) return;
        try {
            await api.post('/api/playlists/remove-track', { pid: selectedPlaylist.ID, track_id: trackId });
            handleSelect(selectedPlaylist);
            toast.success("Track removed from playlist.");
        } catch (err) { toast.error("Failed to remove track."); }
    };

    const handleDeleteFromCollection = async (trackId) => {
        if (!confirm("Delete this track from the entire collection? This cannot be undone.")) return;
        try {
            await api.delete(`/api/track/${trackId}`);
            toast.success("Track deleted from library.");
            if (selectedPlaylist) handleSelect(selectedPlaylist);
            loadAllTracks();
            loadTree();
        } catch (err) {
            toast.error("Failed to delete track.");
        }
    };

    const handleAddToPlaylist = async (playlistId, trackId) => {
        try {
            await api.post('/api/playlists/add-track', { pid: playlistId, track_id: trackId });
            toast.success("Track added to playlist!");
            if (selectedPlaylist?.ID === playlistId) handleSelect(selectedPlaylist);
        } catch (err) {
            toast.error("Failed to add track to playlist.");
        }
    };

    const handleMoveNode = async (sourceId, targetId, position = "inside") => {
        try {
            let actualParentId = "ROOT";

            if (position === "inside") {
                actualParentId = targetId;
            } else {
                // Sibling move: inherit target's parent
                const findParent = (nodes, tid) => {
                    for (const n of nodes) {
                        if (n.Children && n.Children.some(c => c.ID === tid)) return n.ID;
                        if (n.Children) {
                            const found = findParent(n.Children, tid);
                            if (found) return found;
                        }
                    }
                    return "ROOT";
                };
                actualParentId = findParent(tree, targetId);
            }

            await api.post('/api/playlists/move', {
                pid: sourceId,
                parent_id: actualParentId,
                target_id: targetId,
                position: position
            });
            loadTree();
            toast.success("Item moved successfully!");
        } catch (err) { toast.error("Failed to move item."); }
    };

    const handleSync = async () => {
        setIsProcessing(true);
        try {
            await api.post('/api/library/sync');
            toast.success("Changes committed and synced!");
            loadTree();
        } catch (err) {
            toast.error("Sync failed.");
        } finally {
            setIsProcessing(false);
        }
    };

    const onPlaylistContextMenu = (e, node) => {
        e.preventDefault();
        e.stopPropagation();
        setContextMenu({ x: e.clientX, y: e.clientY, node });
    };


    const handleExportSoundCloud = async () => {
        if (!selectedPlaylist || !tracks.length) return;
        setScExporting(true);
        setShowScProgress(true);
        try {
            const isTauri = !!(window.__TAURI_INTERNALS__ || window.__TAURI_METADATA__ || window.__TAURI__);
            if (!isTauri) {
                toast.error('SoundCloud export is only available in the desktop app.');
                return;
            }
            const { invoke } = await import('@tauri-apps/api/core');
            const exportTracks = displayTracks.length > 0 ? displayTracks : tracks;
            const scTracks = exportTracks.map(t => ({
                artist: t.Artist || '',
                title: t.Title || '',
                duration_ms: Math.round((t.TotalTime || 0) * 1000)
            }));
            const result = await invoke('export_to_soundcloud', {
                playlistName: selectedPlaylist.Name,
                tracks: scTracks,
            });
            toast.success(result);
        } catch (err) {
            toast.error(`SoundCloud export failed: ${err}`);
        } finally {
            setScExporting(false);
            setShowScProgress(false);
        }
    };

    useEffect(() => {
        // Close context menu only on LEFT-click (button 0) outside the menu.
        const handleMouseDown = (e) => {
            if (e.button !== 0) return;
            const menu = e.target.closest && e.target.closest('[data-context-menu="true"]');
            if (menu) return;
            setContextMenu(null);
        };
        window.addEventListener('mousedown', handleMouseDown);
        return () => window.removeEventListener('mousedown', handleMouseDown);
    }, []);

    // ── FAILSAFE: document-level contextmenu listener ────────────────────
    // React's per-node onContextMenu sometimes silently fails inside Tauri
    // WebView2 when an ancestor toggles draggable mid-render. We catch
    // contextmenu events at the document and resolve the right node from a
    // data-pl-id attribute. Works regardless of React reconciliation timing.
    useEffect(() => {
        const handleDocCtx = (e) => {
            // 1. Track-row right-click handled by TrackTable's own listener — skip
            if (e.target.closest && e.target.closest('[data-track-row]')) return;
            const cell = e.target.closest && e.target.closest('[data-pl-id]');
            if (!cell) return;
            const id = cell.getAttribute('data-pl-id');
            // Walk current tree to resolve the full node object
            const findInTree = (nodes) => {
                for (const n of nodes || []) {
                    if (String(n.ID) === id) return n;
                    const hit = findInTree(n.Children);
                    if (hit) return hit;
                }
                return null;
            };
            const node = findInTree(tree);
            if (!node) return;
            e.preventDefault();
            e.stopPropagation();
            setContextMenu({ x: e.clientX, y: e.clientY, node });
        };
        document.addEventListener('contextmenu', handleDocCtx, true);  // capture phase
        return () => document.removeEventListener('contextmenu', handleDocCtx, true);
    }, [tree]);

    // Filtered collection tracks
    const filteredCollectionTracks = React.useMemo(() => {
        if (!collectionSearch) return allTracks;
        const q = collectionSearch.toLowerCase();
        return allTracks.filter(t =>
            (t.Title && t.Title.toLowerCase().includes(q)) ||
            (t.Artist && t.Artist.toLowerCase().includes(q)) ||
            (t.Album && t.Album.toLowerCase().includes(q))
        );
    }, [allTracks, collectionSearch]);

    // Filtered playlist tracks
    const filteredPlaylistTracks = React.useMemo(() => {
        if (!playlistSearch) return tracks;
        const q = playlistSearch.toLowerCase();
        return tracks.filter(t =>
            (t.Title && t.Title.toLowerCase().includes(q)) ||
            (t.Artist && t.Artist.toLowerCase().includes(q)) ||
            (t.Album && t.Album.toLowerCase().includes(q))
        );
    }, [tracks, playlistSearch]);

    if (!loading && tree.length === 0 && !dbLoaded) {
        return (
            <div className="flex h-full flex-col items-center justify-center text-ink-muted bg-mx-deepest/50">
                <Database size={64} className="mb-6 opacity-30 text-amber2" />
                <h2 className="text-2xl font-bold text-white mb-2">Library Empty</h2>
                <div className="flex flex-col items-center">
                    <p className="max-w-md text-center mb-8">No playlists found. Please try refreshing or check your database connection.</p>
                    <button
                        onClick={loadTree}
                        className="px-6 py-2 bg-amber2 hover:bg-amber2 rounded-full font-bold text-white transition-all shadow-lg shadow-amber2/20"
                    >
                        <RotateCw size={16} className="mr-2 inline" />
                        Refresh Library
                    </button>
                </div>
            </div>
        )
    }

    // Determine what to show in the main content area
    const currentViewTracks = showCollection ? filteredCollectionTracks : filteredPlaylistTracks;
    const currentViewTitle = showCollection ? "Collection" : selectedPlaylist?.Name || "";
    const currentViewCount = showCollection ? allTracks.length : tracks.length;
    const isIntelligentSelected = selectedPlaylist?.Type === "4";

    return (
        <div className="flex h-full relative">
            <RenameModal
                isOpen={!!renameNode}
                initialValue={renameNode?.Name}
                onClose={() => setRenameNode(null)}
                onConfirm={confirmRename}
                title={`Rename ${renameNode?.Type === "0" ? "Folder" : "Playlist"}`}
            />
            {/* SIDEBAR */}
            <div
                className="border-r border-white/5 overflow-y-auto bg-mx-deepest/30 backdrop-blur-md flex flex-col shrink-0 relative"
                style={{ width: '280px' }}
            >
                {/* Sidebar Header */}
                <div className="sticky top-0 bg-mx-deepest/90 z-10 border-b border-white/5 backdrop-blur-xl shrink-0">
                    <div className="flex justify-between items-center px-3 py-3">
                        <h3 className="text-[10px] font-bold text-ink-muted uppercase tracking-widest">Library</h3>
                        <div className="flex gap-0.5">
                            <button onClick={loadTree} className="p-1.5 hover:bg-white/5 rounded text-ink-muted" title="Refresh">
                                <RotateCw size={12} className={loading ? 'animate-spin' : ''} />
                            </button>
                            <button onClick={handleCreatePlaylist} className="p-1.5 hover:bg-white/5 rounded text-amber2" title="New Playlist">
                                <Plus size={12} />
                            </button>
                            <button onClick={handleCreateFolder} className="p-1.5 hover:bg-white/5 rounded text-amber-500" title="New Folder">
                                <FolderPlus size={12} />
                            </button>
                        </div>
                    </div>
                </div>

                {/* Collection Node */}
                <div
                    className={`flex items-center gap-2.5 px-3 py-2.5 cursor-pointer transition-all border-b border-white/5
                        ${showCollection ? 'bg-amber2/10 text-white' : 'text-ink-secondary hover:text-ink-primary hover:bg-white/5'}`}
                    onClick={handleSelectCollection}
                    onContextMenu={(e) => {
                        // Treat collection like a virtual ROOT node so the
                        // create / smart / folder actions are reachable here too.
                        e.preventDefault();
                        e.stopPropagation();
                        setContextMenu({
                            x: e.clientX, y: e.clientY,
                            node: { ID: "ROOT", Name: "Collection", Type: "0", ParentID: null }
                        });
                    }}
                >
                    <div className={`p-1.5 rounded-lg ${showCollection ? 'bg-amber2/20' : 'bg-white/5'}`}>
                        <Database size={14} className="text-amber2" />
                    </div>
                    <div className="flex-1 min-w-0">
                        <div className="text-[13px] font-semibold truncate">Collection</div>
                        <div className="text-[10px] text-ink-muted font-mono">{allTracks.length} tracks</div>
                    </div>
                </div>

                {/* Playlist Tree */}
                <div className="px-1 pt-2 pb-1">
                    <div className="text-[9px] font-bold text-ink-placeholder uppercase tracking-widest px-2 mb-1">Playlists</div>
                </div>
                <div
                    className="flex-1 overflow-y-auto pb-4"
                    onContextMenu={(e) => {
                        // Right-click on empty area inside the tree → ROOT-level options
                        if (e.target === e.currentTarget) {
                            e.preventDefault();
                            setContextMenu({
                                x: e.clientX, y: e.clientY,
                                node: { ID: "ROOT", Name: "Library", Type: "0", ParentID: null }
                            });
                        }
                    }}
                    onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; }}
                    onDrop={(e) => {
                        e.preventDefault();
                        try {
                            const data = JSON.parse(e.dataTransfer.getData("application/json"));
                            if (data.id && handleMoveNode) {
                                handleMoveNode(data.id, "ROOT", "inside");
                            }
                        } catch (err) { console.error("Drop failed", err); }
                    }}
                >
                    {tree.map(n => (
                        <PlaylistNode
                            key={n.ID}
                            node={n}
                            onSelect={handleSelect}
                            onContextMenu={onPlaylistContextMenu}
                            onMoveNode={handleMoveNode}
                            onRename={handleRename}
                            selectedId={selectedPlaylist?.ID}
                        />
                    ))}
                </div>

                {/* Playlist Context Menu — rendered via portal to escape any
                    overflow/z-index/transform contexts of the tree container. */}
                {contextMenu && createPortal((
                    <div
                        data-context-menu="true"
                        className="bg-mx-shell border border-white/20 rounded-xl shadow-2xl py-1.5 min-w-[220px] animate-fade-in"
                        style={{
                            position: 'fixed',
                            top: Math.min(contextMenu.y, window.innerHeight - 320),
                            left: Math.min(contextMenu.x, window.innerWidth - 230),
                            zIndex: 99999,
                            backdropFilter: 'blur(12px)',
                        }}
                    >
                        <div className="mx-caption px-3 py-1.5 border-b border-white/5 truncate text-[10px]">
                            {contextMenu.node.Name}
                        </div>

                        {/* Type=1 (playlist) and Type=4 (smart) — both have tracks */}
                        {(contextMenu.node.Type === "1" || contextMenu.node.Type === "4") && (
                            <button onClick={() => { handleSelect(contextMenu.node); setContextMenu(null); }} className="w-full flex items-center gap-3 px-4 py-2 hover:bg-white/5 text-sm transition-colors text-ink-primary">
                                <ListMusic size={14} className="text-amber2" /> Tracks anzeigen
                            </button>
                        )}

                        {/* Smart-Playlist edit (Type=4 only) */}
                        {contextMenu.node.Type === "4" && (
                            <button onClick={() => { setSmartEditorEditing({ id: contextMenu.node.ID, name: contextMenu.node.Name, criteria: contextMenu.node.SmartList || {} }); setShowSmartEditor(true); setContextMenu(null); }} className="w-full flex items-center gap-3 px-4 py-2 hover:bg-white/5 text-sm transition-colors text-purple-300">
                                <Sparkles size={14} /> Bedingungen bearbeiten
                            </button>
                        )}

                        {/* Rename / Delete — supported for all node types */}
                        <button onClick={() => handleRename(contextMenu.node)} className="w-full flex items-center gap-3 px-4 py-2 hover:bg-white/5 text-sm transition-colors text-ink-primary">
                            <Edit2 size={14} className="text-ink-muted" /> Umbenennen
                        </button>
                        <button onClick={() => handleDuplicate(contextMenu.node)} className="w-full flex items-center gap-3 px-4 py-2 hover:bg-white/5 text-sm transition-colors text-cyan-300">
                            <Plus size={14} /> Duplizieren
                        </button>
                        <button onClick={() => handleDelete(contextMenu.node)} className="w-full flex items-center gap-3 px-4 py-2 hover:bg-white/5 text-sm transition-colors text-red-400">
                            <Trash2 size={14} /> Löschen
                        </button>

                        <div className="h-px bg-white/5 my-1" />

                        <button onClick={handleCreateFolder} className="w-full flex items-center gap-3 px-4 py-2 hover:bg-white/5 text-sm transition-colors text-amber-500">
                            <FolderPlus size={14} /> Neuer Ordner
                        </button>
                        <button onClick={handleCreatePlaylist} className="w-full flex items-center gap-3 px-4 py-2 hover:bg-white/5 text-sm transition-colors text-amber2">
                            <Plus size={14} /> Neue Playlist
                        </button>
                        <button onClick={() => { setSmartEditorParent(contextMenu?.node?.Type === '0' ? contextMenu.node.ID : 'ROOT'); setShowSmartEditor(true); setContextMenu(null); }} className="w-full flex items-center gap-3 px-4 py-2 hover:bg-white/5 text-sm transition-colors text-purple-400">
                            <Sparkles size={14} /> Neue Smart-Playlist
                        </button>
                    </div>
                ), document.body)}

                {showSmartEditor && (
                    <SmartPlaylistEditor
                        parentId={smartEditorParent}
                        existing={smartEditorEditing}
                        onClose={() => { setShowSmartEditor(false); setSmartEditorEditing(null); }}
                        onSaved={() => { setShowSmartEditor(false); setSmartEditorEditing(null); loadTree(); }}
                    />
                )}

            </div>

            {/* MAIN CONTENT AREA */}
            <div className="flex-1 bg-transparent flex flex-col overflow-hidden relative">
                {(selectedPlaylist || showCollection) ? (
                    <div className="flex-1 overflow-y-auto flex flex-col">
                        {/* Header */}
                        <div className="p-5 border-b border-white/5 bg-mx-shell/40 backdrop-blur-xl flex justify-between items-end shrink-0">
                            <div className="flex items-center gap-4">
                                <div className={`p-2.5 rounded-xl ${showCollection ? 'bg-amber2/15' : isIntelligentSelected ? 'bg-purple-500/15' : 'bg-mx-card'}`}>
                                    {showCollection ? <Database size={24} className="text-amber2" /> :
                                        isIntelligentSelected ? <Sparkles size={24} className="text-purple-400" /> :
                                            <ListMusic size={24} className="text-amber2" />}
                                </div>
                                <div>
                                    <h1 className="text-2xl font-bold text-white tracking-tight flex items-center gap-2">
                                        {currentViewTitle}
                                        {isIntelligentSelected && <span className="text-xs bg-purple-500/20 text-purple-400 px-2 py-0.5 rounded-full font-bold uppercase tracking-wider">Intelligent</span>}
                                    </h1>
                                    <p className="text-ink-muted font-mono text-xs mt-0.5">
                                        {currentViewTracks.length}{currentViewTracks.length !== currentViewCount ? ` / ${currentViewCount}` : ''} TRACKS
                                    </p>
                                </div>
                            </div>

                            <div className="flex items-center gap-2">
                                {/* Search */}
                                <div className="relative group">
                                    <input
                                        type="text"
                                        placeholder="Search..."
                                        value={showCollection ? collectionSearch : playlistSearch}
                                        onChange={(e) => showCollection ? setCollectionSearch(e.target.value) : setPlaylistSearch(e.target.value)}
                                        className="bg-mx-shell/60 border border-white/5 rounded-lg py-1.5 pl-3 pr-3 text-xs text-ink-primary focus:outline-none focus:border-amber2/50 w-48 transition-all"
                                    />
                                </div>
                                {selectedPlaylist && !isIntelligentSelected && (
                                    <>
                                        <button
                                            onClick={handleExportSoundCloud}
                                            disabled={scExporting || !tracks.length}
                                            className="flex items-center gap-1.5 px-3 py-1.5 bg-gradient-to-r from-orange-600 to-orange-500 hover:from-orange-500 hover:to-orange-400 rounded-lg text-xs font-bold transition-all border border-orange-400/20 shadow-lg shadow-orange-500/10 disabled:opacity-30 text-white"
                                        >
                                            <Upload size={12} className={scExporting ? 'animate-pulse' : ''} />
                                            {scExporting ? 'Exporting...' : 'SoundCloud'}
                                        </button>
                                        <button
                                            onClick={handleCleanTitles}
                                            disabled={isProcessing || !tracks.length}
                                            className="flex items-center gap-1.5 px-3 py-1.5 bg-mx-card hover:bg-mx-hover rounded-lg text-xs font-bold transition-all border border-white/5 disabled:opacity-30"
                                        >
                                            <Edit2 size={12} className="text-orange-400" />
                                            Clean
                                        </button>
                                    </>
                                )}
                            </div>
                        </div>

                        {/* Track Table */}
                        {loading ? (
                            <div className="flex-1 flex items-center justify-center">
                                <div className="text-amber2 animate-pulse flex flex-col items-center">
                                    <div className="w-10 h-10 border-4 border-amber2 border-t-transparent rounded-full animate-spin mb-4"></div>
                                    <span className="text-sm font-medium">Loading tracks...</span>
                                </div>
                            </div>
                        ) : (
                            <div className="flex-1 overflow-hidden flex flex-col p-3 pt-1">
                                <TrackTable
                                    tracks={currentViewTracks}
                                    onSelectTrack={onSelectTrack}
                                    onEditTrack={onEditTrack}
                                    onPlay={onPlayTrack}
                                    variant="minimal"
                                    onSortedTracksChange={setDisplayTracks}
                                    onReorder={selectedPlaylist && !isIntelligentSelected ? (trackId, newIndex) => {
                                        api.post('/api/playlists/reorder', { pid: selectedPlaylist.ID, track_id: trackId, target_index: newIndex })
                                            .then(() => {
                                                toast.success("Track reordered");
                                                handleSelect(selectedPlaylist);
                                            })
                                            .catch(() => toast.error("Reorder failed"));
                                    } : undefined}
                                    onRemove={selectedPlaylist && !isIntelligentSelected ? handleRemoveTrack : undefined}
                                    onDelete={handleDeleteFromCollection}
                                    onAddToPlaylist={handleAddToPlaylist}
                                    availablePlaylists={allPlaylists}
                                    playlistId={showCollection ? "COLLECTION" : selectedPlaylist?.ID}
                                />
                            </div>
                        )}
                    </div>
                ) : (
                    <div className="flex-1 flex flex-col items-center justify-center text-ink-muted">
                        <ListMusic size={64} className="mb-6 opacity-20" />
                        <p className="text-xl font-light text-ink-muted">Select a playlist to view tracks</p>
                    </div>
                )}
            </div>

            <SoundCloudProgressModal isOpen={showScProgress} onClose={() => setShowScProgress(false)} />
        </div>
    );
};

export default PlaylistBrowser;
