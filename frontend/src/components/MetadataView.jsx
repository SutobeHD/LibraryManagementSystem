import React, { useState, useEffect, useMemo, useDeferredValue } from 'react';
import { toast } from 'react-hot-toast';
import api from '../api/api';
import TrackTable from './TrackTable';
import PlaylistBrowser from './PlaylistBrowser';
import { promptModal } from './PromptModal';
import { Search, User, ArrowLeft, Tag, Disc, GitMerge, Music, List, RotateCw } from 'lucide-react';

const MetadataView = ({ onSelectTrack, onEditTrack, onPlayTrack, libraryStatus }) => {
  // Default to 'playlists' — removed separate 'tracks' tab since Collection is now inside PlaylistBrowser
  const [activeTab, setActiveTab] = useState('playlists');
  const [items, setItems] = useState([]);
  const [selectedItem, setSelectedItem] = useState(null);
  const [tracks, setTracks] = useState([]);
  const [searchTerm, setSearchTerm] = useState("");
  const [trackFilter, setTrackFilter] = useState("");
  // Deferred so typing in the search box stays responsive — the O(n)
  // filters below run at lower priority instead of on every keystroke.
  const deferredSearchTerm = useDeferredValue(searchTerm);
  const deferredTrackFilter = useDeferredValue(trackFilter);

  const [isLoading, setIsLoading] = useState(false);

  const loadItems = () => {
    if (!libraryStatus?.loaded) return;
    if (activeTab === 'playlists') return; // PlaylistBrowser handles its own loading

    setIsLoading(true);
    let endpoint = '';
    if (activeTab === 'artists') endpoint = '/api/artists';
    else if (activeTab === 'labels') endpoint = '/api/labels';
    else if (activeTab === 'albums') endpoint = '/api/albums';

    if (endpoint) {
      api.get(endpoint).then(res => {
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
    setItems([]);
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
    return items.filter(a => a.name.toLowerCase().includes(deferredSearchTerm.toLowerCase()));
  }, [items, deferredSearchTerm]);

  const filteredTracks = useMemo(() => {
    const q = (selectedItem ? deferredTrackFilter : deferredSearchTerm).toLowerCase();
    if (!q) return tracks;
    return tracks.filter(t =>
      (t.Title && t.Title.toLowerCase().includes(q)) ||
      (t.Artist && t.Artist.toLowerCase().includes(q)) ||
      (t.Album && t.Album.toLowerCase().includes(q))
    );
  }, [tracks, deferredTrackFilter, deferredSearchTerm, selectedItem]);

  const handleMerge = async (sourceName) => {
    const targetName = await promptModal({
      title: 'Merge variations',
      message: `Merge all variations of "${sourceName}" into which name?`,
      defaultValue: sourceName,
    });
    if (!targetName || targetName === sourceName) return;

    try {
      await api.post('/api/metadata/merge', {
        category: activeTab,
        source_name: sourceName,
        target_name: targetName
      });
      loadItems();
    } catch (e) {
      toast.error("Merge failed");
    }
  };

  // When in playlists tab, render PlaylistBrowser full-height without extra chrome
  if (activeTab === 'playlists' && !selectedItem) {
    return (
      <div className="h-full flex flex-col">
        {/* Minimal tab bar */}
        <div className="flex justify-between items-center px-4 py-3 border-b border-white/5 bg-mx-deepest/30 backdrop-blur-md shrink-0">
          <div className="flex items-center gap-6">
            <h1 className="text-xl font-bold text-white flex items-center gap-2">
              <Music size={20} className="text-amber2" />
              Library
            </h1>
            <div className="flex bg-black/40 p-0.5 rounded-lg border border-white/5">
              {[
                { id: 'playlists', icon: List, label: 'Playlists' },
                { id: 'artists', icon: User, label: 'Artists' },
                { id: 'labels', icon: Tag, label: 'Labels' },
                { id: 'albums', icon: Disc, label: 'Albums' }
              ].map(tab => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`px-3 py-1.5 rounded-md text-[10px] font-bold uppercase tracking-wider transition-all flex items-center gap-1.5 ${activeTab === tab.id ? 'bg-amber2 text-white shadow-lg' : 'text-ink-muted hover:text-ink-primary'}`}
                >
                  <tab.icon size={11} />
                  {tab.label}
                </button>
              ))}
            </div>
          </div>
        </div>
        {/* PlaylistBrowser fills the remaining space */}
        <div className="flex-1 overflow-hidden">
          <PlaylistBrowser
            onSelectTrack={onSelectTrack}
            onEditTrack={onEditTrack}
            onPlayTrack={onPlayTrack}
            libraryStatus={libraryStatus}
          />
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col p-4">
      {/* Tab Switcher & Header */}
      <div className="flex justify-between items-center mb-6">
        {selectedItem ? (
          <div className="flex items-center gap-4">
            <button
              onClick={() => setSelectedItem(null)}
              className="p-2 hover:bg-white/10 rounded-full transition-colors text-ink-secondary hover:text-white"
            >
              <ArrowLeft size={24} />
            </button>
            <div>
              <h1 className="text-4xl font-bold text-white flex items-center gap-3">
                {activeTab === 'artists' ? <User size={32} className="text-amber2" /> :
                  activeTab === 'labels' ? <Tag size={32} className="text-purple-400" /> :
                    <Disc size={32} className="text-amber-400" />}
                {selectedItem.name}
              </h1>
              <p className="text-ink-secondary text-sm mt-1">{filteredTracks.length} / {selectedItem.track_count || tracks.length} Tracks</p>
            </div>
          </div>
        ) : (
          <div className="flex items-center gap-8">
            <h1 className="text-4xl font-bold text-white flex items-center gap-3">
              <Music size={32} className="text-amber2" />
              Library
            </h1>
            <div className="flex bg-black/40 p-1 rounded-xl border border-white/5">
              {[
                { id: 'playlists', icon: List, label: 'Playlists' },
                { id: 'artists', icon: User, label: 'Artists' },
                { id: 'labels', icon: Tag, label: 'Labels' },
                { id: 'albums', icon: Disc, label: 'Albums' }
              ].map(tab => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`px-4 py-2 rounded-lg text-[10px] font-bold uppercase tracking-wider transition-all flex items-center gap-2 ${activeTab === tab.id ? 'bg-amber2 text-white shadow-lg' : 'text-ink-muted hover:text-ink-primary'}`}
                >
                  <tab.icon size={12} />
                  {tab.label}
                </button>
              ))}
            </div>
          </div>
        )}

        <div className="flex items-center gap-3">
          <button
            onClick={loadItems}
            disabled={isLoading}
            className={`p-2 rounded-full transition-all border border-white/5 hover:bg-white/10 text-ink-secondary hover:text-amber2 ${isLoading ? 'animate-spin opacity-50' : ''}`}
            title="Refresh View"
          >
            <RotateCw size={16} />
          </button>
          <div className="relative group w-64">
            <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted group-focus-within:text-amber2 transition-colors" />
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
      <div className="flex-1 overflow-hidden relative">
        {selectedItem ? (
          <div className="absolute inset-0 overflow-y-auto pb-4 p-2">
            <TrackTable
              tracks={filteredTracks}
              onSelectTrack={onSelectTrack}
              onEditTrack={onEditTrack}
              onPlay={onPlayTrack}
              playlistId={`${activeTab.toUpperCase()}_${selectedItem.id}`}
            />
          </div>
        ) : (
          <div className="p-4 grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4 overflow-y-auto h-full pb-20">
            {filteredItems.map(a => (
              <div
                key={a.id}
                onClick={() => handleSelect(a)}
                className="bg-mx-card/40 hover:bg-amber2/10 border border-white/5 hover:border-amber2/50 p-6 rounded-xl cursor-pointer transition-all group flex flex-col items-center justify-center text-center gap-2 relative"
              >
                <button
                  onClick={(e) => { e.stopPropagation(); handleMerge(a.name); }}
                  className="absolute top-2 right-2 p-2 rounded-lg bg-black/40 text-ink-muted hover:text-amber2 opacity-0 group-hover:opacity-100 transition-all border border-white/5"
                  title="Merge/Rename"
                >
                  <GitMerge size={14} />
                </button>

                <div className="w-16 h-16 rounded-full bg-mx-shell flex items-center justify-center mb-2 group-hover:scale-110 transition-transform shadow-lg overflow-hidden relative border border-white/5">
                  {a.Artwork ? (
                    <img
                      src={`${api.defaults.baseURL || ''}/api/artwork?path=${encodeURIComponent(a.Artwork)}`}
                      alt={a.name}
                      className="w-full h-full object-cover"
                      loading="lazy"
                      onError={(e) => e.target.style.display = 'none'}
                    />
                  ) : (
                    activeTab === 'artists' ? <User size={32} className="text-ink-muted" /> :
                      activeTab === 'labels' ? <Tag size={32} className="text-ink-muted" /> :
                        <Disc size={32} className="text-ink-muted" />
                  )}
                </div>
                <div className="font-bold text-ink-primary group-hover:text-white truncate w-full">{a.name}</div>
                <div className="text-xs text-ink-muted font-mono bg-black/20 px-2 py-1 rounded-full">{a.track_count} Tracks</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default MetadataView;
