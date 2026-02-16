import React, { useState, useEffect, useMemo } from 'react';
import api from '../api/api';
import TrackTable from './TrackTable';
import { Search, Activity, Trash2, AlertCircle, PlayCircle, Layers, TrendingDown, Music, ImageOff } from 'lucide-react';

const InsightsView = ({ onSelectTrack, onEditTrack, onPlayTrack, libraryStatus }) => {
    const [activeTab, setActiveTab] = useState('low_quality'); // 'low_quality', 'lost'
    const [tracks, setTracks] = useState([]);
    const [loading, setLoading] = useState(false);
    const [searchTerm, setSearchTerm] = useState("");

    const loadData = () => {
        if (!libraryStatus?.loaded) return;
        setLoading(true);
        let endpoint = '/api/insights/low_quality';
        if (activeTab === 'lost') endpoint = '/api/insights/lost';
        if (activeTab === 'no_artwork') endpoint = '/api/insights/no_artwork';
        api.get(endpoint).then(res => {
            setTracks(res.data);
            setLoading(false);
        }).catch(err => {
            console.error("Failed to load insights", err);
            setLoading(false);
        });
    };

    useEffect(() => {
        loadData();
    }, [activeTab, libraryStatus?.loaded]);

    const filteredTracks = useMemo(() => {
        if (!searchTerm) return tracks;
        const q = searchTerm.toLowerCase();
        return tracks.filter(t =>
            (t.Title && t.Title.toLowerCase().includes(q)) ||
            (t.Artist && t.Artist.toLowerCase().includes(q))
        );
    }, [tracks, searchTerm]);

    return (
        <div className="h-full flex flex-col bg-slate-950/20 p-6">
            {/* Header */}
            <div className="flex justify-between items-center mb-8">
                <div className="flex items-center gap-6">
                    <h1 className="text-4xl font-bold text-white flex items-center gap-3">
                        <Activity size={32} className="text-cyan-400" />
                        Library Insights
                    </h1>

                    <div className="flex bg-black/40 p-1 rounded-xl border border-white/5">
                        {[
                            { id: 'low_quality', label: 'Low Quality', icon: TrendingDown, color: 'text-amber-400' },
                            { id: 'lost', label: 'Lost Tracks', icon: PlayCircle, color: 'text-rose-400' },
                            { id: 'no_artwork', label: 'No Cover', icon: ImageOff, color: 'text-slate-400' }
                        ].map(tab => (
                            <button
                                key={tab.id}
                                onClick={() => setActiveTab(tab.id)}
                                className={`px-4 py-2 rounded-lg text-sm font-bold uppercase tracking-wider transition-all flex items-center gap-2 ${activeTab === tab.id ? 'bg-cyan-500 text-white shadow-lg' : 'text-slate-500 hover:text-slate-300'}`}
                            >
                                <tab.icon size={14} className={activeTab === tab.id ? 'text-white' : tab.color} />
                                {tab.label}
                            </button>
                        ))}
                    </div>
                </div>

                <div className="relative group w-64">
                    <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 group-focus-within:text-cyan-400 transition-colors" />
                    <input
                        className="input-glass w-full pl-10 bg-black/20 text-sm rounded-full py-2"
                        placeholder="Search these results..."
                        value={searchTerm}
                        onChange={e => setSearchTerm(e.target.value)}
                    />
                </div>
            </div>

            {/* Summary Cards */}
            {!loading && (
                <div className="grid grid-cols-3 gap-4 mb-6">
                    <div className="bg-slate-900/40 border border-white/5 p-4 rounded-xl">
                        <div className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1">Total identified</div>
                        <div className="text-3xl font-mono font-bold text-white">{tracks.length}</div>
                    </div>
                    {activeTab === 'low_quality' && (
                        <div className="bg-amber-500/5 border border-amber-500/20 p-4 rounded-xl">
                            <div className="text-[10px] font-bold text-amber-500/60 uppercase tracking-widest mb-1">Quality Threshold</div>
                            <div className="text-3xl font-mono font-bold text-amber-400">{'<'} 320 kbps</div>
                        </div>
                    )}
                    {activeTab === 'lost' && (
                        <div className="bg-rose-500/5 border border-rose-500/20 p-4 rounded-xl">
                            <div className="text-[10px] font-bold text-rose-500/60 uppercase tracking-widest mb-1">Status</div>
                            <div className="text-3xl font-mono font-bold text-rose-400">Zero Plays</div>
                        </div>
                    )}
                    {activeTab === 'no_artwork' && (
                        <div className="bg-slate-800/20 border border-slate-700/50 p-4 rounded-xl">
                            <div className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1">Status</div>
                            <div className="text-3xl font-mono font-bold text-slate-400">Missing Art</div>
                        </div>
                    )}
                </div>
            )}

            {/* Content Area */}
            <div className="flex-1 overflow-hidden bg-slate-900/40 rounded-xl shadow-inner border border-white/5 relative">
                {loading ? (
                    <div className="flex h-full items-center justify-center">
                        <div className="flex flex-col items-center animate-pulse">
                            <Activity size={48} className="text-cyan-500 mb-4" />
                            <span className="text-slate-400 font-medium">Analyzing collection...</span>
                        </div>
                    </div>
                ) : tracks.length === 0 ? (
                    <div className="flex h-full flex-col items-center justify-center text-slate-500">
                        <Music size={64} className="mb-6 opacity-10" />
                        <h2 className="text-xl font-medium text-slate-400">Your library is clean!</h2>
                        <p className="text-slate-600 mt-2">No tracks found matching this filter.</p>
                    </div>
                ) : (
                    <div className="absolute inset-0 overflow-y-auto pb-4 p-2">
                        <TrackTable
                            tracks={filteredTracks}
                            onSelectTrack={onSelectTrack}
                            onEditTrack={onEditTrack}
                            onPlay={onPlayTrack}
                            playlistId={`INSIGHTS_${activeTab.toUpperCase()}`}
                            variant="minimal"
                        />
                    </div>
                )}
            </div>

            <div className="mt-4 p-4 bg-cyan-500/5 border border-cyan-500/10 rounded-xl flex items-center gap-3">
                <AlertCircle size={18} className="text-cyan-400 shrink-0" />
                <p className="text-xs text-slate-400 leading-relaxed">
                    {activeTab === 'low_quality'
                        ? "Tip: Consider replacing these tracks with high-quality AIFF or FLAC versions for better sound system performance."
                        : "Tip: These tracks haven't been played yet. Consider moving them to a 'New Music' playlist to give them a listen."}
                </p>
            </div>
        </div>
    );
};

export default InsightsView;
