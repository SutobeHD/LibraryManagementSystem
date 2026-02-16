import React, { useState, useEffect, useMemo } from 'react';
import { toast } from 'react-hot-toast';
import api from '../api/api';
import TrackTable from './TrackTable';
import PlaylistBrowser from './PlaylistBrowser';
import { Search, User, ArrowLeft, Tag, Disc, GitMerge, Music, List, RotateCw } from 'lucide-react';

const MetadataView = ({ onSelectTrack, onEditTrack, onPlayTrack, libraryStatus }) => {
  const [activeTab, setActiveTab] = useState('tracks'); // 'tracks', 'playlists', 'artists', 'labels', 'albums'
  const [items, setItems] = useState([]);
  const [selectedItem, setSelectedItem] = useState(null);
  const [tracks, setTracks] = useState([]);
  const [searchTerm, setSearchTerm] = useState("");
  const [trackFilter, setTrackFilter] = useState("");

  const [isLoading, setIsLoading] = useState(false);

  const loadItems = () => {
    if (!libraryStatus?.loaded) return;
    if (activeTab === 'playlists') return;

    setIsLoading(true);
    let endpoint = '';
    if (activeTab === 'tracks') endpoint = '/api/library/tracks';
    else if (activeTab === 'artists') endpoint = '/api/artists';
    else if (activeTab === 'labels') endpoint = '/api/labels';
    else if (activeTab === 'albums') endpoint = '/api/albums';

    if (endpoint) {
      api.get(endpoint).then(res => {
        console.log(`[MetadataView] Loaded ${activeTab}:`, res.data.length, "items");
        if (activeTab === 'tracks') setTracks(res.data);
        else setItems(res.data);
      }).catch(e => {
        console.error("Failed to load items", e);
        toast.error(`Failed to load ${activeTab}`);
      }).finally(() => setIsLoading(false));
    } else {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    setItems([]); // Clear previous items to avoid confusion
    if (activeTab === 'tracks') {
      // Don't clear tracks immediately to prevent flash if we can avoid it, 
      // but user reported stale data. Let's clear it if we are entering tracks mode from elsewhere
      // Actually, improved loadItems logic handles it.
    }
    loadItems();
    setSelectedItem(null);
    setSearchTerm("");
    setTrackFilter("");
  }, [activeTab, libraryStatus?.loaded]);

  const handleSelect = (item) => {
    setSelectedItem(item);
    let type = activeTab.slice(0, -1); // artist, label, album
    api.get(`/api/${type}/${item.id}/tracks`).then(res => setTracks(res.data));
  };

  const filteredItems = useMemo(() => {
    return items.filter(a => a.name.toLowerCase().includes(searchTerm.toLowerCase()));
  }, [items, searchTerm]);

  const filteredTracks = useMemo(() => {
    const q = (selectedItem ? trackFilter : searchTerm).toLowerCase();
    if (!q) return tracks;
    return tracks.filter(t =>
      (t.Title && t.Title.toLowerCase().includes(q)) ||
      (t.Artist && t.Artist.toLowerCase().includes(q)) ||
      (t.Album && t.Album.toLowerCase().includes(q))
    );
  }, [tracks, trackFilter, searchTerm, selectedItem]);

  const handleMerge = async (sourceName) => {
    const targetName = prompt(`Merge all variations of "${sourceName}" into which name?`, sourceName);
    if (!targetName || targetName === sourceName) return;

    try {
      await api.post('/api/metadata/merge', {
        category: activeTab,
        source_name: sourceName,
        target_name: targetName
      });
      loadItems();
    } catch (e) {
      alert("Merge failed");
    }
  };

  return (
    <div className="h-full flex flex-col bg-slate-950/20 p-4">
      {/* Tab Switcher & Header */}
      <div className="flex justify-between items-center mb-6">
        {selectedItem ? (
          <div className="flex items-center gap-4">
            <button
              onClick={() => setSelectedItem(null)}
              className="p-2 hover:bg-white/10 rounded-full transition-colors text-slate-400 hover:text-white"
            >
              <ArrowLeft size={24} />
            </button>
            <div>
              <h1 className="text-4xl font-bold text-white flex items-center gap-3">
                {activeTab === 'artists' ? <User size={32} className="text-cyan-400" /> :
                  activeTab === 'labels' ? <Tag size={32} className="text-purple-400" /> :
                    <Disc size={32} className="text-amber-400" />}
                {selectedItem.name}
              </h1>
              <p className="text-slate-400 text-sm mt-1">{filteredTracks.length} / {selectedItem.track_count || tracks.length} Tracks</p>
            </div>
          </div>
        ) : (
          <div className="flex items-center gap-8">
            <h1 className="text-4xl font-bold text-white flex items-center gap-3">
              <Music size={32} className="text-cyan-400" />
              Library
            </h1>
            <div className="flex bg-black/40 p-1 rounded-xl border border-white/5">
              {[
                { id: 'tracks', icon: Music },
                { id: 'playlists', icon: List },
                { id: 'artists', icon: User },
                { id: 'labels', icon: Tag },
                { id: 'albums', icon: Disc }
              ].map(tab => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`px-4 py-2 rounded-lg text-[10px] font-bold uppercase tracking-wider transition-all flex items-center gap-2 ${activeTab === tab.id ? 'bg-cyan-500 text-white shadow-lg' : 'text-slate-500 hover:text-slate-300'}`}
                >
                  <tab.icon size={12} />
                  {tab.id}
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="flex items-center gap-3">
          <button
            onClick={loadItems}
            disabled={isLoading}
            className={`p-2 rounded-full transition-all border border-white/5 hover:bg-white/10 text-slate-400 hover:text-cyan-400 ${isLoading ? 'animate-spin opacity-50' : ''}`}
            title="Refresh View"
          >
            <RotateCw size={16} />
          </button>
          <div className="relative group w-64">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500 group-focus-within:text-cyan-400 transition-colors" />
            <input
              className="input-glass w-full pl-10 bg-black/20 text-sm rounded-full py-2"
              placeholder={selectedItem ? "Search tracks..." : `Search ${activeTab}...`}
              value={selectedItem ? trackFilter : searchTerm}
              onChange={e => selectedItem ? setTrackFilter(e.target.value) : setSearchTerm(e.target.value)}
            />
          </div>
        </div>
      </div>

      {/* Content Area */}
      <div className="flex-1 overflow-hidden bg-slate-900/40 rounded-xl shadow-inner border border-white/5 relative">
        {activeTab === 'playlists' ? (
          <div className="absolute inset-0 overflow-hidden">
            <PlaylistBrowser onSelectTrack={onSelectTrack} onEditTrack={onEditTrack} onPlayTrack={onPlayTrack} />
          </div>
        ) : selectedItem || activeTab === 'tracks' ? (
          <div className="absolute inset-0 overflow-y-auto pb-4 p-2">
            <TrackTable
              tracks={filteredTracks}
              onSelectTrack={onSelectTrack}
              onEditTrack={onEditTrack}
              onPlay={onPlayTrack}
              playlistId={activeTab === 'tracks' ? 'ALL_TRACKS' : `${activeTab.toUpperCase()}_${selectedItem.id}`}
            />
          </div>
        ) : (
          <div className="p-4 grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4 overflow-y-auto h-full pb-20">
            {filteredItems.map(a => (
              <div
                key={a.id}
                onClick={() => handleSelect(a)}
                className="bg-slate-800/40 hover:bg-cyan-500/10 border border-white/5 hover:border-cyan-500/50 p-6 rounded-xl cursor-pointer transition-all group flex flex-col items-center justify-center text-center gap-2 relative"
              >
                <button
                  onClick={(e) => { e.stopPropagation(); handleMerge(a.name); }}
                  className="absolute top-2 right-2 p-2 rounded-lg bg-black/40 text-slate-500 hover:text-cyan-400 opacity-0 group-hover:opacity-100 transition-all border border-white/5"
                  title="Merge/Rename"
                >
                  <GitMerge size={14} />
                </button>

                <div className="w-16 h-16 rounded-full bg-slate-900 flex items-center justify-center mb-2 group-hover:scale-110 transition-transform shadow-lg overflow-hidden relative border border-white/5">
                  {a.Artwork ? (
                    <img
                      src={`${api.defaults.baseURL || ''}/api/artwork?path=${encodeURIComponent(a.Artwork)}`}
                      alt={a.name}
                      className="w-full h-full object-cover"
                      loading="lazy"
                      onError={(e) => e.target.style.display = 'none'}
                    />
                  ) : (
                    activeTab === 'artists' ? <User size={32} className="text-slate-500" /> :
                      activeTab === 'labels' ? <Tag size={32} className="text-slate-500" /> :
                        <Disc size={32} className="text-slate-500" />
                  )}
                </div>
                <div className="font-bold text-slate-200 group-hover:text-white truncate w-full">{a.name}</div>
                <div className="text-xs text-slate-500 font-mono bg-black/20 px-2 py-1 rounded-full">{a.track_count} Tracks</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default MetadataView;

