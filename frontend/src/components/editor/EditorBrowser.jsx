
import React, { useState, useEffect, useMemo } from 'react';
import { Search, Music, Disc, User, Play, Plus, X, ListMusic } from 'lucide-react';
import api from '../../api/api';

const EditorBrowser = ({ onLoadTrack, onClose }) => {
    const [searchTerm, setSearchTerm] = useState("");
    const [tracks, setTracks] = useState([]);
    const [loading, setLoading] = useState(false);
    const [filteredTracks, setFilteredTracks] = useState([]);

    useEffect(() => {
        loadLibrary();
    }, []);

    const loadLibrary = async () => {
        setLoading(true);
        try {
            const res = await api.get('/api/library/tracks');
            // Ensure we have an array
            const data = Array.isArray(res.data) ? res.data : [];
            setTracks(data);
        } catch (e) {
            console.error("Failed to load library", e);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        if (!searchTerm) {
            setFilteredTracks(tracks.slice(0, 100)); // Limit initial view for perf
            return;
        }
        const lower = searchTerm.toLowerCase();
        const filtered = tracks.filter(t =>
            (t.Title?.toLowerCase() || "").includes(lower) ||
            (t.Artist?.toLowerCase() || "").includes(lower)
        );
        setFilteredTracks(filtered.slice(0, 100));
    }, [searchTerm, tracks]);

    return (
        <div className="h-full flex flex-col bg-mx-shell/95 backdrop-blur-xl border-r border-white/10 w-80 flex-shrink-0 transition-all">
            {/* Header */}
            <div className="p-4 border-b border-white/5 flex items-center justify-between">
                <div className="flex items-center gap-2 text-amber2">
                    <ListMusic size={20} />
                    <span className="font-bold tracking-tight">Library Browser</span>
                </div>
                {onClose && (
                    <button onClick={onClose} className="p-1 hover:bg-white/10 rounded-full text-ink-secondary hover:text-white">
                        <X size={16} />
                    </button>
                )}
            </div>

            {/* Search */}
            <div className="p-3">
                <div className="relative group">
                    <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted group-focus-within:text-amber2 transition-colors" />
                    <input
                        type="text"
                        placeholder="Search tracks..."
                        value={searchTerm}
                        onChange={e => setSearchTerm(e.target.value)}
                        className="w-full bg-black/40 border border-white/10 rounded-xl py-2 pl-9 pr-3 text-xs text-white placeholder:text-ink-placeholder focus:outline-none focus:border-amber2/50 focus:ring-1 focus:ring-amber2/50 transition-all"
                    />
                </div>
            </div>

            {/* Track List */}
            <div className="flex-1 overflow-y-auto min-h-0 p-2 space-y-1 custom-scrollbar">
                {loading ? (
                    <div className="text-center py-8 text-ink-muted text-xs animate-pulse">Loading library...</div>
                ) : filteredTracks.length === 0 ? (
                    <div className="text-center py-8 text-ink-placeholder text-xs">No tracks found</div>
                ) : (
                    filteredTracks.map(track => (
                        <div
                            key={track.ID || track.id}
                            className="group flex items-center gap-3 p-2 rounded-lg hover:bg-white/5 cursor-pointer border border-transparent hover:border-white/5 transition-all"
                            onDoubleClick={() => onLoadTrack(track)}
                            draggable
                            onDragStart={(e) => {
                                e.dataTransfer.setData('application/json', JSON.stringify(track));
                                e.dataTransfer.effectAllowed = 'copy';
                            }}
                        >
                            {/* Artwork / Icon */}
                            <div className="w-10 h-10 rounded bg-mx-card flex items-center justify-center flex-shrink-0 overflow-hidden relative">
                                {track.Artwork ? (
                                    <img src={`/api/artwork/${track.Artwork}`} alt="" className="w-full h-full object-cover" loading="lazy" />
                                ) : (
                                    <Disc size={16} className="text-ink-placeholder" />
                                )}
                                <div className="absolute inset-0 bg-black/60 opacity-0 group-hover:opacity-100 flex items-center justify-center transition-opacity">
                                    <Play size={16} className="text-white fill-white" />
                                </div>
                            </div>

                            {/* Info */}
                            <div className="flex-1 min-w-0">
                                <div className="text-xs font-bold text-ink-primary truncate group-hover:text-amber2 transition-colors">
                                    {track.Title || "Untitled"}
                                </div>
                                <div className="text-[10px] text-ink-muted truncate flex items-center gap-1">
                                    <User size={10} />
                                    {track.Artist || "Unknown Artist"}
                                </div>
                            </div>

                            {/* Add Button */}
                            <button
                                onClick={(e) => { e.stopPropagation(); onLoadTrack(track); }}
                                className="p-1.5 rounded-md hover:bg-amber2 text-ink-placeholder hover:text-white opacity-0 group-hover:opacity-100 transition-all"
                                title="Load into Editor"
                            >
                                <Plus size={14} />
                            </button>
                        </div>
                    ))
                )}
            </div>

            {/* Footer Status */}
            <div className="p-2 border-t border-white/5 text-[10px] text-ink-placeholder text-center">
                Double-click to load
            </div>
        </div>
    );
};

export default EditorBrowser;
