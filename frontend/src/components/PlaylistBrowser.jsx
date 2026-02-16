import React, { useState, useEffect, useRef } from 'react';
import api from '../api/api';
import { useToast } from './ToastContext';
import { Folder, ListMusic, ChevronRight, ChevronDown, Music, Database, Settings, Plus, Sparkles, RotateCw, Scissors, MoreVertical, Edit2, Trash2, FolderPlus, ArrowRightLeft, X, Upload, Star, Tag, GripVertical } from 'lucide-react';
import TrackTable from './TrackTable';
import SoundCloudProgressModal from './SoundCloudProgressModal';
import RenameModal from './RenameModal';

const PlaylistNode = ({ node, level = 0, onSelect, onContextMenu, onMoveNode, isEditMode, onRename }) => {
    const [isOpen, setIsOpen] = useState(level === 0);
    const hasChildren = node.children && node.children.length > 0;
    const ref = useRef(null);
    const [dropPos, setDropPos] = useState(null); // 'before', 'inside', 'after'

    const handleContextMenu = (e) => {
        e.preventDefault();
        onContextMenu(e, node);
    };

    const handleDragStart = (e) => {
        if (node.ID) {
            e.dataTransfer.setData("application/json", JSON.stringify({ id: node.ID, type: node.Type }));
            e.dataTransfer.effectAllowed = "move";
        }
    };

    const handleDragOver = (e) => {
        e.preventDefault();
        e.stopPropagation();

        if (!ref.current) return;
        const rect = ref.current.getBoundingClientRect();
        const y = e.clientY - rect.top;
        const h = rect.height;

        // Thresholds
        if (node.Type === "0") { // Folder: allow inside
            const edgeThreshold = h * 0.25;
            if (y < edgeThreshold) setDropPos('before');
            else if (y > h - edgeThreshold) setDropPos('after');
            else setDropPos('inside');
        } else { // File: only before/after
            if (y < h / 2) setDropPos('before');
            else setDropPos('after');
        }

        e.dataTransfer.dropEffect = "move";
    };

    const handleDragLeave = () => setDropPos(null);

    const handleDrop = (e) => {
        e.preventDefault();
        e.stopPropagation();

        try {
            const data = JSON.parse(e.dataTransfer.getData("application/json"));
            if (data.id && data.id !== node.ID && onMoveNode) {
                const pos = dropPos || 'inside';
                // If dropping 'inside' a file, treated as 'after' or ignore? 
                // Logic above ensures non-folders don't get 'inside'
                onMoveNode(data.id, node.ID, pos);
            }
        } catch (err) { console.error("Drop failed", err); }
        setDropPos(null);
    };

    // Visual Styles
    let dropStyle = "";
    if (dropPos === 'before') dropStyle = "border-t-2 border-t-cyan-500 z-50";
    else if (dropPos === 'after') dropStyle = "border-b-2 border-b-cyan-500 z-50";
    else if (dropPos === 'inside') dropStyle = "bg-cyan-500/20 ring-1 ring-cyan-500/50";

    return (
        <div className="select-none animate-fade-in relative group" ref={ref}>
            <div
                onClick={() => onSelect(node)}
                onDoubleClick={(e) => { e.stopPropagation(); if (onRename) onRename(node); }}
                onContextMenu={handleContextMenu}
                draggable={true}
                onDragStart={handleDragStart}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                className={`flex items-center gap-1 py-1.5 pr-2 hover:bg-white/5 text-slate-400 hover:text-white transition-all rounded-r-xl mr-2 border-l-2 border-transparent hover:border-cyan-400 cursor-pointer ${dropStyle}`}
                style={{ paddingLeft: `${level * 12 + 4}px` }}
            >
                {/* Grip Handle */}
                {isEditMode && (
                    <div className="mr-1 text-slate-600 cursor-grab active:cursor-grabbing">
                        <GripVertical size={14} />
                    </div>
                )}

                {/* Toggle Button */}
                <div
                    onClick={(e) => { e.stopPropagation(); setIsOpen(!isOpen); }}
                    className={`p-0.5 rounded hover:bg-white/10 text-slate-500 transition-colors flex items-center justify-center ${!hasChildren ? 'invisible' : ''}`}
                    style={{ width: '20px', height: '20px' }}
                >
                    <ChevronRight size={14} className={`transition-transform duration-200 ${isOpen ? 'rotate-90' : ''}`} />
                </div>

                {/* Icon */}
                {node.Type === "1" ?
                    <Folder size={16} className="text-amber-500 shrink-0" /> :
                    <ListMusic size={16} className="text-cyan-400 shrink-0" />
                }

                {/* Name */}
                <span className={`truncate text-sm ${node.Type !== "0" && 'font-medium'}`} title={node.Name}>
                    {node.Name}
                    {!hasChildren && node.Count !== undefined && node.Type !== "0" && (
                        <span className="opacity-50 text-xs ml-2 font-mono">
                            ({node.Count})
                        </span>
                    )}
                </span>

                <button
                    onClick={(e) => { e.stopPropagation(); onContextMenu(e, node); }}
                    className="ml-auto opacity-0 group-hover:opacity-100 p-1 hover:bg-white/10 rounded transition-all shrink-0"
                >
                    <MoreVertical size={12} />
                </button>
            </div>
            {isOpen && hasChildren && <div className="border-l border-white/5 ml-4">{node.children.map(c => <PlaylistNode key={c.ID} node={c} level={level + 1} onSelect={onSelect} onContextMenu={onContextMenu} onMoveNode={onMoveNode} isEditMode={isEditMode} onRename={onRename} />)}</div>}
        </div>
    );
};

const PlaylistBrowser = ({ onSelectTrack, onEditTrack, onPlayTrack, libraryStatus }) => {
    const toast = useToast();
    const [tree, setTree] = useState([]);
    const [selectedPlaylist, setSelectedPlaylist] = useState(null);
    const [tracks, setTracks] = useState([]);
    const [loading, setLoading] = useState(false);
    const [dbLoaded, setDbLoaded] = useState(true);
    const [isProcessing, setIsProcessing] = useState(false);
    const [contextMenu, setContextMenu] = useState(null);
    const [trackMenu, setTrackMenu] = useState(null);
    const [isEditMode, setIsEditMode] = useState(false);
    const [scExporting, setScExporting] = useState(false);
    const [showScProgress, setShowScProgress] = useState(false);
    const [sidebarWidth, setSidebarWidth] = useState(320);
    const [isResizing, setIsResizing] = useState(false);
    const [renameNode, setRenameNode] = useState(null);
    const toggleEditMode = () => setIsEditMode(!isEditMode);


    const loadTree = () => {
        setLoading(true);
        api.get('/api/playlists/tree')
            .then(res => {
                console.log("Playlist Tree Data:", res.data);
                if (Array.isArray(res.data)) {
                    console.log("Playlist Tree:", res.data);
                    if (res.data.length === 0) {
                        console.warn("Playlist tree is empty.");
                    }
                    setDbLoaded(true);
                    setTree(res.data);
                }
                else {
                    console.error("Invalid playlist data:", res.data);
                    setDbLoaded(false);
                }
            })
            .catch(err => {
                console.error("Failed to load playlist tree:", err);
                setDbLoaded(false);
            })
            .finally(() => setLoading(false));
    };

    useEffect(() => {
        if (libraryStatus?.loaded) {
            loadTree();
        }
    }, [libraryStatus?.loaded]);

    // Force reload on mount to ensure fresh data (User request)
    useEffect(() => {
        if (libraryStatus?.loaded) {
            loadTree();
        }
    }, []);

    const handleSelect = (node) => {
        setSelectedPlaylist(node);
        setLoading(true);
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
        if (!tracks.length) return;
        setIsProcessing(true);
        try {
            const trackIds = tracks.map(t => t.id);
            const res = await api.post('/api/library/clean-titles', { track_ids: trackIds });
            toast.success(`Cleaned ${res.data.success.length} titles!`);
            handleSelect(selectedPlaylist); // Refresh tracks
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
            await api.post('/api/playlists/create', { name, parent_id: selectedPlaylist?.Type === "0" ? selectedPlaylist.ID : "ROOT" });
            loadTree();
        } catch (err) {
            alert("Failed to create playlist.");
        }
    };

    const handleCreateFolder = async () => {
        const name = prompt("Enter folder name:");
        if (!name) return;
        try {
            await api.post('/api/playlists/create', { name, type: "0", parent_id: selectedPlaylist?.Type === "0" ? selectedPlaylist.ID : "ROOT" });
            loadTree();
            toast.success("Folder created!");
        } catch (err) {
            toast.error("Failed to create folder.");
        }
    };

    const handleRename = (node) => {
        setRenameNode(node);
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
        if (!confirm(`Delete ${node.Name}?`)) return;
        try {
            await api.post('/api/playlists/delete', { pid: node.ID });
            loadTree();
            if (selectedPlaylist?.ID === node.ID) setSelectedPlaylist(null);
        } catch (err) { toast.error("Failed to delete."); }
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
        try {
            await api.delete(`/api/track/${trackId}`);
            toast.success("Track deleted from library.");
            // Refresh current playlist view if applicable
            if (selectedPlaylist) handleSelect(selectedPlaylist);
            // Optionally reload tree if needed (e.g. if it affects counts)
            loadTree();
        } catch (err) {
            console.error("Delete failed", err);
            toast.error("Failed to delete track.");
        }
    };

    const handleMoveNode = async (sourceId, targetId, position = "inside") => {
        try {
            // targetId is the Node we dropped on.
            // If position is "inside", parent_id = targetId.
            // If position is "before"/"after", parent_id = targetId's parent (but backend handles this via target_id + position).
            // We'll pass both to backend and let it decide.

            await api.post('/api/playlists/move', {
                pid: sourceId,
                parent_id: position === "inside" ? targetId : "ROOT", // Default, backend overrides if target_id present
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
    };

    const onTrackContextMenu = (e, track) => {
        e.preventDefault();
        setTrackMenu({ x: e.clientX, y: e.clientY, track });
    };

    const handleExportSoundCloud = async () => {
        if (!selectedPlaylist || !tracks.length) return;
        setScExporting(true);
        setShowScProgress(true); // Show modal
        try {
            const isTauri = !!(window.__TAURI_INTERNALS__ || window.__TAURI_METADATA__ || window.__TAURI__);
            if (!isTauri) {
                toast.error('SoundCloud export is only available in the desktop app.');
                return;
            }
            const { invoke } = await import('@tauri-apps/api/core');
            const scTracks = tracks.map(t => ({
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
            console.error('[SoundCloud Export]', err);
            toast.error(`SoundCloud export failed: ${err}`);
        } finally {
            setScExporting(false);
            setShowScProgress(false); // Hide modal
        }
    };

    useEffect(() => {
        const handleClick = () => { setContextMenu(null); setTrackMenu(null); };
        window.addEventListener('click', handleClick);
        return () => window.removeEventListener('click', handleClick);
    }, []);

    if (!loading && tree.length === 0) {
        return (
            <div className="flex h-full flex-col items-center justify-center text-slate-500 bg-slate-950/50">
                <Database size={64} className="mb-6 opacity-30 text-cyan-400" />
                <h2 className="text-2xl font-bold text-white mb-2">Library Empty</h2>
                {libraryStatus?.mode === 'xml' ? (
                    <p className="max-w-md text-center mb-8">No playlists found. Please go to the <strong>XML Automator</strong> to scan your `rekordbox.xml` file.</p>
                ) : (
                    <div className="flex flex-col items-center">
                        <p className="max-w-md text-center mb-8">No playlists found. Please try refreshing.</p>
                        <button
                            onClick={loadTree}
                            className="px-6 py-2 bg-cyan-600 hover:bg-cyan-500 rounded-full font-bold text-white transition-all shadow-lg shadow-cyan-500/20"
                        >
                            <RotateCw size={16} className="mr-2 inline" />
                            Refresh Library
                        </button>
                    </div>
                )}
            </div>
        )
    }

    return (
        <div className="flex h-full relative">
            <RenameModal
                isOpen={!!renameNode}
                initialValue={renameNode?.Name}
                onClose={() => setRenameNode(null)}
                onConfirm={confirmRename}
                title={`Rename ${renameNode?.Type === "0" ? "Folder" : "Playlist"}`}
            />
            <div
                className="border-r border-white/5 overflow-y-auto bg-slate-950/30 backdrop-blur-md flex flex-col shrink-0 relative"
                style={{ width: '320px' }}
            >
                <div className="sticky top-0 bg-slate-950/90 z-10 border-b border-white/5 backdrop-blur-xl shrink-0">
                    <div className="flex justify-between items-center px-4 py-4">
                        <h3 className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Library</h3>
                        <div className="flex gap-1">
                            <button
                                onClick={toggleEditMode}
                                className={`p-1.5 rounded transition-all ${isEditMode ? 'bg-amber-500/20 text-amber-400' : 'hover:bg-white/5 text-slate-400'}`}
                                title={isEditMode ? "Exit Edit Mode" : "Enter Edit Mode"}
                            >
                                <Edit2 size={14} />
                            </button>
                            <button onClick={loadTree} className="p-1.5 hover:bg-white/5 rounded text-slate-400" title="Refresh">
                                <RotateCw size={14} className={loading ? 'animate-spin' : ''} />
                            </button>
                            <button onClick={handleCreatePlaylist} className="p-1.5 hover:bg-white/5 rounded text-cyan-400" title="New Playlist">
                                <Plus size={14} />
                            </button>
                            <button onClick={handleCreateFolder} className="p-1.5 hover:bg-white/5 rounded text-amber-400" title="New Folder">
                                <FolderPlus size={14} />
                            </button>
                            <button onClick={handleSmartPlaylists} disabled={isProcessing} className="p-1.5 hover:bg-white/5 rounded text-amber-500 transition-all disabled:opacity-30" title="Generate Smart Playlists">
                                <Sparkles size={14} className={isProcessing ? 'animate-spin' : ''} />
                            </button>
                        </div>
                    </div>
                </div>
                <div
                    className="flex-1 overflow-y-auto pb-4"
                    onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; }}
                    onDrop={(e) => {
                        e.preventDefault();
                        try {
                            const data = JSON.parse(e.dataTransfer.getData("application/json"));
                            // If dropping on background, move to ROOT
                            // Ensure we aren't dropping ROOT on ROOT check?
                            if (data.id && handleMoveNode) {
                                handleMoveNode(data.id, "ROOT", "inside");
                            }
                        } catch (err) { console.error("Drop failed", err); }
                    }}
                >
                    {tree.map(n => <PlaylistNode key={n.ID} node={n} onSelect={handleSelect} onContextMenu={onPlaylistContextMenu} onMoveNode={handleMoveNode} isEditMode={isEditMode} onRename={handleRename} />)}
                </div>

                {/* Playlist Context Menu */}
                {contextMenu && (
                    <div
                        className="fixed z-[100] bg-slate-900 border border-white/10 rounded-lg shadow-2xl py-2 min-w-[160px] animate-fade-in backdrop-blur-xl"
                        style={{ top: contextMenu.y, left: contextMenu.x }}
                    >
                        <button onClick={() => handleRename(contextMenu.node)} className="w-full flex items-center gap-3 px-4 py-2 hover:bg-white/5 text-sm transition-colors text-slate-300">
                            <Edit2 size={14} /> Rename
                        </button>
                        <button onClick={() => handleDelete(contextMenu.node)} className="w-full flex items-center gap-3 px-4 py-2 hover:bg-white/5 text-sm transition-colors text-red-400">
                            <Trash2 size={14} /> Delete
                        </button>
                        <div className="h-px bg-white/5 my-1" />
                        <button onClick={handleCreateFolder} className="w-full flex items-center gap-3 px-4 py-2 hover:bg-white/5 text-sm transition-colors text-amber-500">
                            <FolderPlus size={14} /> New Folder
                        </button>
                        <button onClick={handleCreatePlaylist} className="w-full flex items-center gap-3 px-4 py-2 hover:bg-white/5 text-sm transition-colors text-cyan-400">
                            <Plus size={14} /> New Playlist
                        </button>
                    </div>
                )}

                {/* Track Context Menu */}
                {trackMenu && (
                    <div
                        className="fixed z-[100] bg-slate-900 border border-white/10 rounded-lg shadow-2xl py-2 min-w-[160px] animate-fade-in backdrop-blur-xl"
                        style={{ top: trackMenu.y, left: trackMenu.x }}
                    >
                        <button onClick={() => { onSelectTrack(trackMenu.track); setTrackMenu(null); }} className="w-full flex items-center gap-3 px-4 py-2 hover:bg-white/5 text-sm transition-colors text-cyan-400">
                            <Scissors size={14} /> Edit in Waveform
                        </button>
                        <button onClick={() => { onSelectTrack(trackMenu.track); setTrackMenu(null); }} className="w-full flex items-center gap-3 px-4 py-2 hover:bg-white/5 text-sm transition-colors text-slate-400">
                            <Music size={14} /> Quick Preview
                        </button>
                        <button onClick={() => handleRemoveTrack(trackMenu.track.id)} className="w-full flex items-center gap-3 px-4 py-2 hover:bg-white/5 text-sm transition-colors text-red-400">
                            <Trash2 size={14} /> Remove from Playlist
                        </button>
                    </div>
                )}
            </div>
            <div className="flex-1 bg-transparent flex flex-col overflow-hidden relative">
                {selectedPlaylist ? (
                    <div className="flex-1 overflow-y-auto p-4 flex flex-col">
                        <div className="p-6 border-b border-white/5 bg-slate-800/40 backdrop-blur-xl mb-4 rounded-xl shadow-lg mx-2 mt-2 border border-white/5 flex justify-between items-end">
                            <div>
                                <h1 className="text-3xl font-bold text-white mb-1 drop-shadow-md flex items-center gap-3">
                                    <ListMusic size={28} className="text-cyan-400" />
                                    {selectedPlaylist.Name}
                                </h1>
                                <p className="text-slate-400 font-mono text-xs">{tracks.length} TRACKS</p>
                            </div>

                            {/* Header Row for Tracks */}
                            <div className="hidden">
                                {/* Can add a header row if desired, but user just asked for columns */}
                            </div>

                            <div className="flex gap-2">
                                <button
                                    onClick={handleExportSoundCloud}
                                    disabled={scExporting || !tracks.length}
                                    className="flex items-center gap-2 px-3 py-1.5 bg-gradient-to-r from-orange-600 to-orange-500 hover:from-orange-500 hover:to-orange-400 rounded-lg text-xs font-bold transition-all border border-orange-400/20 shadow-lg shadow-orange-500/10 disabled:opacity-30 text-white"
                                >
                                    <Upload size={14} className={scExporting ? 'animate-pulse' : ''} />
                                    {scExporting ? 'Exporting...' : 'Export to SoundCloud'}
                                </button>
                                <button
                                    onClick={handleCleanTitles}
                                    disabled={isProcessing || !tracks.length}
                                    className="flex items-center gap-2 px-3 py-1.5 bg-slate-700 hover:bg-slate-600 rounded-lg text-xs font-bold transition-all border border-white/5 disabled:opacity-30"
                                >
                                    <Scissors size={14} className="text-orange-400" />
                                    Clean Titles
                                </button>
                            </div>
                        </div>

                        {loading ? (
                            <div className="flex-1 flex items-center justify-center">
                                <div className="text-cyan-400 animate-pulse flex flex-col items-center">
                                    <div className="w-10 h-10 border-4 border-cyan-400 border-t-transparent rounded-full animate-spin mb-4"></div>
                                    <span className="text-lg font-medium">Loading tracks...</span>
                                </div>
                            </div>
                        ) : (
                            <div className="flex-1 overflow-hidden flex flex-col">
                                <TrackTable
                                    tracks={tracks}
                                    onSelectTrack={onSelectTrack}
                                    onEditTrack={onEditTrack}
                                    onPlay={onPlayTrack}
                                    // Actually, PlaylistBrowser receives `onSelectTrack` which might represent "Edit" or "Select".
                                    // In App.jsx, `onSelectTrack` passed to `MetadataView` -> `PlaylistBrowser` was `handleTrackSelect` (Select Only).
                                    // Users double clicking in Playlist should Edit.
                                    // `PlaylistBrowser` accepts ONLY `onSelectTrack`. 
                                    // I should update `PlaylistBrowser` props to accept `onEditTrack`.
                                    variant="minimal"
                                    onReorder={(trackId, newIndex) => {
                                        api.post('/api/playlists/reorder', { pid: selectedPlaylist.ID, track_id: trackId, target_index: newIndex })
                                            .then(() => {
                                                toast.success("Track reordered");
                                                handleSelect(selectedPlaylist);
                                            })
                                            .catch(() => toast.error("Reorder failed"));
                                    }}
                                    onRemove={handleRemoveTrack}
                                    onDelete={handleDeleteFromCollection}
                                    playlistId={selectedPlaylist.ID}
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
