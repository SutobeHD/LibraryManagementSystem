import React, { useState, useEffect, useMemo } from 'react';
import api from '../api/api';
import TrackTable from './TrackTable';
import { Database, RotateCw, Search } from 'lucide-react';

const LibraryView = ({ onSelectTrack }) => {
    const [tracks, setTracks] = useState([]);
    const [loading, setLoading] = useState(false);
    const [searchQuery, setSearchQuery] = useState('');

    const loadTracks = () => {
        setLoading(true);
        api.get('/api/library/tracks')
            .then(res => {
                if (Array.isArray(res.data)) {
                    setTracks(res.data);
                }
            })
            .catch(err => console.error("Failed to load tracks", err))
            .finally(() => setLoading(false));
    };

    useEffect(() => {
        loadTracks();
    }, []);

    const filteredTracks = useMemo(() => {
        if (!searchQuery) return tracks;
        const q = searchQuery.toLowerCase();
        return tracks.filter(t =>
            (t.Title && t.Title.toLowerCase().includes(q)) ||
            (t.Artist && t.Artist.toLowerCase().includes(q)) ||
            (t.Album && t.Album.toLowerCase().includes(q))
        );
    }, [tracks, searchQuery]);

    return (
        <div className="flex h-full flex-col">
            <div className="p-4 border-b border-white/5 bg-slate-950/30 backdrop-blur-md flex items-center justify-between">
                <div className="flex items-center gap-4">
                    <div className="p-2 bg-gradient-to-br from-cyan-500/20 to-blue-500/20 rounded-lg border border-cyan-500/30">
                        <Database size={20} className="text-cyan-400" />
                    </div>
                    <div>
                        <h1 className="text-xl font-bold text-white tracking-tight">Library Tracks</h1>
                        <p className="text-xs text-slate-500 font-mono uppercase tracking-widest">{filteredTracks.length} / {tracks.length} TRACKS</p>
                    </div>
                </div>

                <div className="flex items-center gap-3">
                    <div className="relative group">
                        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 group-focus-within:text-cyan-400 transition-colors" />
                        <input
                            type="text"
                            placeholder="Search library..."
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            className="bg-slate-900/50 border border-white/5 rounded-full py-1.5 pl-9 pr-4 text-sm text-slate-300 focus:outline-none focus:border-cyan-500/50 focus:ring-1 focus:ring-cyan-500/50 w-64 transition-all"
                        />
                    </div>
                    <button
                        onClick={loadTracks}
                        className="p-2 hover:bg-white/5 rounded-lg text-slate-400 hover:text-cyan-400 transition-colors"
                        title="Refresh Library"
                    >
                        <RotateCw size={18} className={loading ? 'animate-spin' : ''} />
                    </button>
                </div>
            </div>

            {loading && tracks.length === 0 ? (
                <div className="flex-1 flex items-center justify-center">
                    <div className="flex flex-col items-center gap-4 animate-pulse">
                        <div className="w-12 h-12 rounded-full border-4 border-cyan-500/30 border-t-cyan-500 animate-spin"></div>
                        <span className="text-slate-500 font-medium">Loading library...</span>
                    </div>
                </div>
            ) : (
                <div className="flex-1 overflow-hidden p-4 pt-2">
                    <TrackTable
                        tracks={filteredTracks}
                        onSelectTrack={onSelectTrack}
                        playlistId="LIBRARY"
                    />
                </div>
            )}
        </div>
    );
};

export default LibraryView;
