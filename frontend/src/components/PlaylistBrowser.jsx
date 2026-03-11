import React, { useState, useEffect, useRef } from 'react';
import api from '../api/api';
import { useToast } from './ToastContext';
import { Folder, ListMusic, ChevronRight, ChevronDown, Music, Database, Settings, Plus, Sparkles, RotateCw, MoreVertical, Edit2, Trash2, FolderPlus, ArrowRightLeft, X, Upload, Star, Tag, GripVertical, Library, Disc } from 'lucide-react';
import TrackTable from './TrackTable';
import SoundCloudProgressModal from './SoundCloudProgressModal';
import RenameModal from './RenameModal';

const PlaylistNode = ({ node, level = 0, onSelect, onContextMenu, onMoveNode, isEditMode, onRename, selectedId }) => {
    const [open, setOpen] = useState(level < 1);
    const [dragOver, setDragOver] = useState(null); // "top", "center", "bottom"
    const isFolder = node.Type === "0";
    const isIntelligent = node.Type === "4";
    const isRegularPlaylist = node.Type === "1";

    const handleContextMenu = (e) => {
        e.preventDefault();
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
        <div>
            <div
                className={`flex items-center gap-2 px-3 py-1.5 cursor-pointer transition-all duration-150 group relative
                    ${isSelected ? 'bg-cyan-500/15 text-white' : 'text-slate-400 hover:text-slate-200 hover:bg-white/5'}
                    ${dragOver === "center" ? 'ring-1 ring-cyan-400 bg-cyan-500/10' : ''}
                `}
                style={{ paddingLeft: `${12 + level * 16}px` }}
                onClick={() => {
                    if (isFolder) setOpen(!open);
                    else onSelect(node);
                }}
                onContextMenu={handleContextMenu}
                draggable={isEditMode && !isIntelligent}
                onDragStart={handleDragStart}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
            >
                {dragOver === "top" && <div className="absolute top-0 left-0 right-0 h-0.5 bg-cyan-400 z-10" />}
                {dragOver === "bottom" && <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-cyan-400 z-10" />}

                {isEditMode && !isIntelligent && (
                    <GripVertical size={12} className="text-slate-600 shrink-0 cursor-grab" />
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
                        <ListMusic size={14} className="text-cyan-400/60 shrink-0" />
                    </>
                )}

                <span className={`text-[13px] truncate flex-1 ${isIntelligent ? 'text-purple-300' : ''} ${isSelected ? 'font-semibold' : ''}`}>
                    {node.Name}
                </span>

                {isIntelligent && (
                    <span className="text-[9px] text-purple-500/60 font-bold uppercase tracking-wider shrink-0">Smart</span>
                )}

                {isEditMode && !isIntelligent && (
                    <button
                        onClick={(e) => { e.stopPropagation(); onRename(node); }}
                        className="opacity-0 group-hover:opacity-100 p-1 hover:bg-white/10 rounded transition-all shrink-0"
                    >
                        <Edit2 size={11} className="text-slate-500" />
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
                    isEditMode={isEditMode}
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
    const [isEditMode, setIsEditMode] = useState(false);
    const [scExporting, setScExporting] = useState(false);
    const [showScProgress, setShowScProgress] = useState(false);
    const [renameNode, setRenameNode] = useState(null);
    const [collectionSearch, setCollectionSearch] = useState('');
    const [playlistSearch, setPlaylistSearch] = useState('');
    const [displayTracks, setDisplayTracks] = useState([]);
    const toggleEditMode = () => setIsEditMode(!isEditMode);

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
        setContextMenu({ x: e.clientX, y: e.clientY, node });
        setTrackMenu(null);
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
        const handleClick = () => { setContextMenu(null); };
        window.addEventListener('click', handleClick);
        return () => window.removeEventListener('click', handleClick);
    }, []);

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
            <div className="flex h-full flex-col items-center justify-center text-slate-500 bg-slate-950/50">
                <Database size={64} className="mb-6 opacity-30 text-cyan-400" />
                <h2 className="text-2xl font-bold text-white mb-2">Library Empty</h2>
                <div className="flex flex-col items-center">
                    <p className="max-w-md text-center mb-8">No playlists found. Please try refreshing or check your database connection.</p>
                    <button
                        onClick={loadTree}
                        className="px-6 py-2 bg-cyan-600 hover:bg-cyan-500 rounded-full font-bold text-white transition-all shadow-lg shadow-cyan-500/20"
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
                className="border-r border-white/5 overflow-y-auto bg-slate-950/30 backdrop-blur-md flex flex-col shrink-0 relative"
                style={{ width: '280px' }}
            >
                {/* Sidebar Header */}
                <div className="sticky top-0 bg-slate-950/90 z-10 border-b border-white/5 backdrop-blur-xl shrink-0">
                    <div className="flex justify-between items-center px-3 py-3">
                        <h3 className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Library</h3>
                        <div className="flex gap-0.5">
                            <button
                                onClick={toggleEditMode}
                                className={`p-1.5 rounded transition-all ${isEditMode ? 'bg-amber-500/20 text-amber-400' : 'hover:bg-white/5 text-slate-500'}`}
                                title={isEditMode ? "Exit Edit Mode" : "Enter Edit Mode"}
                            >
                                <Edit2 size={12} />
                            </button>
                            <button onClick={loadTree} className="p-1.5 hover:bg-white/5 rounded text-slate-500" title="Refresh">
                                <RotateCw size={12} className={loading ? 'animate-spin' : ''} />
                            </button>
                            <button onClick={handleCreatePlaylist} className="p-1.5 hover:bg-white/5 rounded text-cyan-500" title="New Playlist">
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
                        ${showCollection ? 'bg-cyan-500/10 text-white' : 'text-slate-400 hover:text-slate-200 hover:bg-white/5'}`}
                    onClick={handleSelectCollection}
                >
                    <div className={`p-1.5 rounded-lg ${showCollection ? 'bg-cyan-500/20' : 'bg-white/5'}`}>
                        <Database size={14} className="text-cyan-400" />
                    </div>
                    <div className="flex-1 min-w-0">
                        <div className="text-[13px] font-semibold truncate">Collection</div>
                        <div className="text-[10px] text-slate-500 font-mono">{allTracks.length} tracks</div>
                    </div>
                </div>

                {/* Playlist Tree */}
                <div className="px-1 pt-2 pb-1">
                    <div className="text-[9px] font-bold text-slate-600 uppercase tracking-widest px-2 mb-1">Playlists</div>
                </div>
                <div
                    className="flex-1 overflow-y-auto pb-4"
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
                            isEditMode={isEditMode}
                            onRename={handleRename}
                            selectedId={selectedPlaylist?.ID}
                        />
                    ))}
                </div>

                {/* Playlist Context Menu */}
                {contextMenu && (
                    <div
                        className="fixed z-[100] bg-slate-900/95 border border-white/10 rounded-xl shadow-2xl py-1.5 min-w-[180px] animate-fade-in backdrop-blur-xl"
                        style={{ top: contextMenu.y, left: contextMenu.x }}
                    >
                        {contextMenu.node.Type !== "4" && (
                            <>
                                <button onClick={() => handleRename(contextMenu.node)} className="w-full flex items-center gap-3 px-4 py-2 hover:bg-white/5 text-sm transition-colors text-slate-300">
                                    <Edit2 size={14} className="text-slate-500" /> Rename
                                </button>
                                <button onClick={() => handleDelete(contextMenu.node)} className="w-full flex items-center gap-3 px-4 py-2 hover:bg-white/5 text-sm transition-colors text-red-400">
                                    <Trash2 size={14} /> Delete
                                </button>
                                <div className="h-px bg-white/5 my-1" />
                            </>
                        )}
                        <button onClick={handleCreateFolder} className="w-full flex items-center gap-3 px-4 py-2 hover:bg-white/5 text-sm transition-colors text-amber-500">
                            <FolderPlus size={14} /> New Folder
                        </button>
                        <button onClick={handleCreatePlaylist} className="w-full flex items-center gap-3 px-4 py-2 hover:bg-white/5 text-sm transition-colors text-cyan-400">
                            <Plus size={14} /> New Playlist
                        </button>
                    </div>
                )}

            </div>

            {/* MAIN CONTENT AREA */}
            <div className="flex-1 bg-transparent flex flex-col overflow-hidden relative">
                {(selectedPlaylist || showCollection) ? (
                    <div className="flex-1 overflow-y-auto flex flex-col">
                        {/* Header */}
                        <div className="p-5 border-b border-white/5 bg-slate-900/40 backdrop-blur-xl flex justify-between items-end shrink-0">
                            <div className="flex items-center gap-4">
                                <div className={`p-2.5 rounded-xl ${showCollection ? 'bg-cyan-500/15' : isIntelligentSelected ? 'bg-purple-500/15' : 'bg-slate-800'}`}>
                                    {showCollection ? <Database size={24} className="text-cyan-400" /> :
                                        isIntelligentSelected ? <Sparkles size={24} className="text-purple-400" /> :
                                            <ListMusic size={24} className="text-cyan-400" />}
                                </div>
                                <div>
                                    <h1 className="text-2xl font-bold text-white tracking-tight flex items-center gap-2">
                                        {currentViewTitle}
                                        {isIntelligentSelected && <span className="text-xs bg-purple-500/20 text-purple-400 px-2 py-0.5 rounded-full font-bold uppercase tracking-wider">Intelligent</span>}
                                    </h1>
                                    <p className="text-slate-500 font-mono text-xs mt-0.5">
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
                                        className="bg-slate-900/60 border border-white/5 rounded-lg py-1.5 pl-3 pr-3 text-xs text-slate-300 focus:outline-none focus:border-cyan-500/50 w-48 transition-all"
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
                                            className="flex items-center gap-1.5 px-3 py-1.5 bg-slate-800 hover:bg-slate-700 rounded-lg text-xs font-bold transition-all border border-white/5 disabled:opacity-30"
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
                                <div className="text-cyan-400 animate-pulse flex flex-col items-center">
                                    <div className="w-10 h-10 border-4 border-cyan-400 border-t-transparent rounded-full animate-spin mb-4"></div>
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
                    <div className="flex-1 flex flex-col items-center justify-center text-slate-500">
                        <ListMusic size={64} className="mb-6 opacity-20" />
                        <p className="text-xl font-light text-slate-500">Select a playlist to view tracks</p>
                    </div>
                )}
            </div>

            <SoundCloudProgressModal isOpen={showScProgress} onClose={() => setShowScProgress(false)} />
        </div>
    );
};

export default PlaylistBrowser;
