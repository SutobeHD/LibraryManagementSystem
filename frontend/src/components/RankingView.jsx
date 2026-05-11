import React, { useState, useEffect } from 'react';
import api from '../api/api';
import { log } from '../utils/log';
import { Star, Zap, SkipForward, SkipBack, Folder, ChevronRight, ChevronDown, Tag, Disc, PlayCircle, Pause, Play, ListMusic, Save, Search, Filter, ArrowRight, ArrowLeft, Check, Hash, User, Volume2 } from 'lucide-react';
import WaveformEditor from './WaveformEditor';
import { useHotkeys } from 'react-hotkeys-hook';
import { toast } from 'react-hot-toast';

const TAG_CATEGORIES = {
    "Genre": ["House", "Hard Techno", "Schranz", "Trance", "Hardgroove", "Groove", "Raw"],
    "Subgenre": ["Acid", "Industrial", "Minimal", "Tribal", "Hard"],
    "Components": ["Synth", "Vocal", "Beat", "Dark", "Emotional", "Melodic", "Acid", "Groove", "Bounce", "Hypnotic", "Minimal", "Fun", "euphoric", "fluid"],
    "Type": ["relaxed", "progressiv", "Build up", "Peak Time", "Build down"]
};

const PlaylistNode = ({ node, level = 0, onSelect }) => {
    const [isOpen, setIsOpen] = useState(false);
    // Backend returns 'Children' (uppercase)
    const children = node.Children || [];
    const hasChildren = children.length > 0;

    return (
        <div>
            <div onClick={() => hasChildren ? setIsOpen(!isOpen) : onSelect(node)} className="flex items-center gap-2 py-2 pr-2 cursor-pointer hover:bg-white/5 text-ink-secondary hover:text-white select-none transition-colors rounded-r-xl mr-2" style={{ paddingLeft: `${level * 16 + 12}px` }}>
                {hasChildren ? (isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />) : <span className="w-3.5"></span>}
                {node.Type === "0" ?
                    <Folder size={16} className="text-amber-500 shrink-0" /> :
                    <ListMusic size={16} className="text-amber2 shrink-0" />
                }
                <span className="truncate text-sm">{node.Name}</span>
            </div>
            {isOpen && hasChildren && <div className="border-l border-white/5 ml-4">{children.map(c => <PlaylistNode key={c.ID} node={c} level={level} onSelect={onSelect} />)}</div>}
        </div>
    );
};

const COLORS = [
    { id: 0, hex: 'transparent', name: 'None' }, { id: 1, hex: '#db2777', name: 'Pink' },
    { id: 2, hex: '#dc2626', name: 'Red' }, { id: 3, hex: '#ea580c', name: 'Orange' },
    { id: 4, hex: '#ca8a04', name: 'Yellow' }, { id: 5, hex: '#16a34a', name: 'Green' },
    { id: 6, hex: '#06b6d4', name: 'Aqua' }, { id: 7, hex: '#2563eb', name: 'Blue' },
    { id: 8, hex: '#7c3aed', name: 'Purple' }
];

const RankingView = ({ libraryStatus, appMode }) => {
    const [tree, setTree] = useState([]);
    const [selectedPlaylist, setSelectedPlaylist] = useState(null);
    const [queue, setQueue] = useState([]);
    const [currentIndex, setCurrentIndex] = useState(0);
    const [currentTrack, setCurrentTrack] = useState(null);
    const [genres, setGenres] = useState([]);
    const [isPlaying, setIsPlaying] = useState(true); // Auto-play default
    const isMountedRef = React.useRef(true);
    const wavesurferRef = React.useRef(null);

    useEffect(() => {
        isMountedRef.current = true;
        // Ensure any other global audio is paused? 
        // For now, we assume WaveformEditor stops itself or we need a global context.
        // Let's just create a DOM event to pause others? 
        const audioElements = document.querySelectorAll('audio');
        audioElements.forEach(a => a.pause());
        return () => {
            isMountedRef.current = false;
            // Force stop
            if (wavesurferRef.current && wavesurferRef.current.stop) {
                try { wavesurferRef.current.stop(); } catch (e) { }
            }
        };
    }, []);

    // Track State
    const [rating, setRating] = useState(0);
    const [colorId, setColorId] = useState(0);
    const [comment, setComment] = useState("");
    const [genre, setGenre] = useState("");
    // MyTag (live mode only — falls silently to no-op in xml mode)
    const [allMyTags, setAllMyTags] = useState([]);    // [{id, name}]
    const [trackMyTagIds, setTrackMyTagIds] = useState([]);
    const [newMyTagName, setNewMyTagName] = useState("");
    const myTagSupported = appMode === 'live' || libraryStatus?.mode === 'live';
    const [volume, setVolumeState] = useState(() => {
        const saved = localStorage.getItem('rb_volume');
        return saved !== null ? parseFloat(saved) : 1;
    });
    const setVolume = (v) => { setVolumeState(v); localStorage.setItem('rb_volume', String(v)); };

    useHotkeys('space', (e) => {
        if (currentTrack) {
            e.preventDefault();
            saveAndNext();
        }
    }, [currentTrack, rating, colorId, comment, genre, currentIndex, queue]);

    useEffect(() => {
        if (libraryStatus?.loaded) {
            api.get('/api/playlists/tree').then(res => {
                setTree(res.data);
                log.debug("[RankingView] Loaded tree:", res.data);
                if (res.data.length === 0) console.warn("[RankingView] Warning: Tree is empty!");
            }).catch(err => console.error("[RankingView] Failed to load tree:", err));
            api.get('/api/genres').then(res => setGenres(res.data));
        }
    }, [libraryStatus?.loaded]);

    // Source State
    const [sourceMode, setSourceMode] = useState('playlist'); // 'playlist', 'artist', 'label', 'album'
    const [sourceItems, setSourceItems] = useState([]);
    const [filteredItems, setFilteredItems] = useState([]);
    const [searchTerm, setSearchTerm] = useState("");

    useEffect(() => {
        if (!libraryStatus?.loaded) return;
        setSearchTerm("");
        if (sourceMode === 'playlist') {
            api.get('/api/playlists/tree').then(res => setTree(res.data));
        } else {
            const endpoint = sourceMode === 'artist' ? '/api/artists' :
                sourceMode === 'label' ? '/api/labels' : '/api/albums';
            api.get(endpoint).then(res => setSourceItems(res.data));
        }
    }, [sourceMode, libraryStatus?.loaded]);

    useEffect(() => {
        if (sourceMode === 'playlist') return;
        setFilteredItems(sourceItems.filter(i => i.name.toLowerCase().includes(searchTerm.toLowerCase())));
    }, [sourceItems, searchTerm, sourceMode]);

    const loadTrack = (track) => {
        if (!track) return;
        setCurrentTrack(track);
        setRating(track.Rating || 0);
        setColorId(track.ColorID || 0);
        setComment(track.Comment || "");
        setGenre(track.Genre || "");
        setIsPlaying(true);
        // Load this track's MyTag assignments (live mode only).
        if (myTagSupported && track.ID) {
            api.get(`/api/track/${encodeURIComponent(track.ID)}/mytags`)
                .then(res => setTrackMyTagIds((res.data || []).map(t => String(t.id))))
                .catch(() => setTrackMyTagIds([]));
        } else {
            setTrackMyTagIds([]);
        }
    };

    // Pull the global MyTag list once when entering live mode.
    useEffect(() => {
        if (!myTagSupported) { setAllMyTags([]); return; }
        api.get('/api/mytags')
            .then(res => setAllMyTags(Array.isArray(res.data) ? res.data : []))
            .catch(() => setAllMyTags([]));
    }, [myTagSupported]);

    const toggleMyTag = (tagId) => {
        const id = String(tagId);
        setTrackMyTagIds(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]);
    };

    const createMyTag = async () => {
        const name = newMyTagName.trim();
        if (!name) return;
        try {
            const res = await api.post('/api/mytags', { name });
            const newTag = { id: String(res.data.id), name: res.data.name };
            setAllMyTags(prev => [...prev, newTag]);
            setTrackMyTagIds(prev => [...prev, newTag.id]);
            setNewMyTagName("");
            toast.success(`MyTag "${name}" created`);
        } catch (e) {
            toast.error(e.response?.data?.detail || 'Could not create MyTag');
        }
    };

    const handleServiceMark = () => {
        // Toggle service mark (e.g. Star rating 5 + Color 2?)
        // For now, let's assume it marks it 5 stars and red color
        setRating(5);
        setColorId(2);
    };

    const saveAndNext = async () => {
        if (!currentTrack) return;

        const payload = {
            Rating: rating,
            ColorID: colorId,
            Comment: comment,
            Genre: genre
        };

        try {
            log.debug("Saving track...", currentTrack);
            if (!currentTrack.ID) console.warn("Track ID is missing!");
            await api.post(`/api/track/${encodeURIComponent(currentTrack.ID)}`, payload);
            // Persist MyTags too (live mode); failure is non-fatal.
            if (myTagSupported) {
                try {
                    await api.post(`/api/track/${encodeURIComponent(currentTrack.ID)}/mytags`,
                                   { tag_ids: trackMyTagIds });
                } catch (tagErr) {
                    console.warn('MyTag save failed:', tagErr);
                    toast(tagErr.response?.data?.detail || 'MyTag save failed', { icon: '⚠️' });
                }
            }
            toast.success("Saved");
        } catch (e) {
            console.error("Save failed:", e);
            toast.error("Failed to save: " + (e.response?.data?.detail || e.message));

            // Temporary: Advance anyway to prevent getting stuck if backend is failing
            // return; 
        }
        const nextIdx = currentIndex + 1;
        if (nextIdx < queue.length) {
            setCurrentIndex(nextIdx);
            loadTrack(queue[nextIdx]);
        } else {
            setCurrentTrack(null);
            setCurrentIndex(queue.length);
        }
    };

    const handleSelectSource = (item) => {
        setSelectedPlaylist(item);
        setIsPlaying(false);
        setCurrentTrack(null);
        setQueue([]);

        let endpoint = '';
        if (sourceMode === 'playlist') endpoint = `/api/playlist/${item.ID}/tracks`;
        else if (sourceMode === 'artist') endpoint = `/api/artist/${item.id}/tracks`;
        else if (sourceMode === 'label') endpoint = `/api/label/${item.id}/tracks`;
        else if (sourceMode === 'album') endpoint = `/api/album/${item.id}/tracks`;

        api.get(endpoint).then(async res => {
            if (!isMountedRef.current) return;

            // Get filter settings
            const settingsRes = await api.get('/api/settings');
            const filterMode = settingsRes.data.ranking_filter_mode || 'all';

            let tracks = res.data;
            if (filterMode === 'unrated') {
                tracks = tracks.filter(t => !t.Rating || t.Rating === 0);
            } else if (filterMode === 'untagged') {
                tracks = tracks.filter(t => !t.Comment || t.Comment.trim() === "");
            }

            setQueue(tracks);
            setCurrentIndex(0);
            if (tracks.length > 0) loadTrack(tracks[0]);
            else toast.error("No tracks found matching your filter criteria.");
        }).catch(err => {
            console.error("Failed to load source tracks", err);
            toast.error("Source list failed to load");
        });
    };

    if (!selectedPlaylist) {
        return (
            <div className="flex h-full relative">
                <div className="w-80 bg-mx-shell/50 border-r border-white/5 flex flex-col backdrop-blur-md">
                    <div className="p-4 border-b border-white/5">
                        <h2 className="text-ink-muted font-bold uppercase text-[10px] mb-4 tracking-widest">Select Source</h2>
                        <div className="flex bg-black/40 p-1 rounded-lg border border-white/5 mb-4">
                            {['playlist', 'artist', 'label', 'album'].map(mode => (
                                <button
                                    key={mode}
                                    onClick={() => setSourceMode(mode)}
                                    className={`flex-1 py-1.5 rounded-md text-[10px] font-bold uppercase tracking-wider transition-all ${sourceMode === mode ? 'bg-amber2 text-white shadow-lg' : 'text-ink-muted hover:text-ink-primary'}`}
                                >
                                    {mode.charAt(0).toUpperCase() + mode.slice(1)}
                                </button>
                            ))}
                        </div>
                        {sourceMode !== 'playlist' && (
                            <div className="relative group">
                                <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" />
                                <input
                                    className="input-glass w-full pl-9 py-1.5 text-xs"
                                    placeholder={`Filter ${sourceMode}s...`}
                                    value={searchTerm}
                                    onChange={e => setSearchTerm(e.target.value)}
                                />
                            </div>
                        )}
                    </div>

                    <div className="flex-1 overflow-y-auto p-2 space-y-1">
                        {sourceMode === 'playlist' ? (
                            tree.map(n => <PlaylistNode key={n.ID} node={n} onSelect={handleSelectSource} />)
                        ) : (
                            filteredItems.map(item => (
                                <div
                                    key={item.id}
                                    onClick={() => handleSelectSource(item)}
                                    className="flex items-center gap-3 p-3 rounded-xl hover:bg-white/5 cursor-pointer group transition-all border border-transparent hover:border-white/5"
                                >
                                    <div className="w-8 h-8 rounded-full bg-mx-card flex items-center justify-center text-ink-muted group-hover:text-amber2 group-hover:bg-amber2/10 transition-colors">
                                        {sourceMode === 'artist' ? <User size={14} /> : sourceMode === 'label' ? <Tag size={14} /> : <Disc size={14} />}
                                    </div>
                                    <div className="flex-1 min-w-0">
                                        <div className="text-sm font-medium text-ink-primary group-hover:text-white truncate">{item.name}</div>
                                        <div className="text-[10px] text-ink-placeholder group-hover:text-ink-muted">{item.track_count} tracks</div>
                                    </div>
                                    <ChevronRight size={14} className="text-ink-placeholder group-hover:text-amber2 opacity-0 group-hover:opacity-100 transition-all" />
                                </div>
                            ))
                        )}
                    </div>
                </div>
                <div className="flex-1 flex items-center justify-center text-ink-muted flex-col bg-transparent">
                    <Zap size={80} className="mb-6 opacity-10" />
                    <p className="text-xl font-light text-ink-secondary">Select a source to start power ranking</p>
                </div>
            </div>
        );
    }

    return (
        <div className="h-full flex flex-col bg-transparent overflow-hidden relative">
            <div className="absolute top-0 w-full h-1 bg-mx-card">
                <div className="h-full bg-amber2 transition-all duration-300 shadow-[0_0_10px_#06b6d4]" style={{ width: `${((currentIndex + 1) / queue.length) * 100}%` }}></div>
            </div>

            <div className="bg-mx-shell/80 p-4 border-b border-white/5 flex justify-between items-center shrink-0 z-10 backdrop-blur-md">
                <h2 className="text-xl font-bold flex items-center gap-2 text-white"><Zap className="text-yellow-400" size={20} /> {selectedPlaylist.Name}</h2>
                <div className="flex items-center gap-4">
                    <div className="text-ink-secondary text-sm font-mono bg-black/20 px-3 py-1 rounded-full border border-white/5">Track {currentIndex + 1} / {queue.length}</div>
                    <button onClick={() => setSelectedPlaylist(null)} className="text-xs text-amber2 hover:text-white uppercase font-bold tracking-widest hover:underline border border-amber2/30 px-3 py-1 rounded-full hover:bg-amber2/10 transition-colors">Exit Full Screen</button>
                </div>
            </div>

            {currentTrack ? (
                <div className="flex-1 overflow-y-auto p-4 flex flex-col items-center relative custom-scrollbar">
                    {/* Cleaned-up wrapper: no triple-stacked glass card. Content sits flat on
                        the shell, separated only by the existing background and a single
                        bottom hairline. */}
                    <div className="w-full max-w-[1400px] relative z-10 animate-slide-up px-2 md:px-6 py-6 mb-20">
                        {/* Header */}
                        <div className="flex justify-between items-start mb-6 pb-5 border-b border-line-subtle gap-8">
                            <div className="flex-1 min-w-0">
                                <h1 className="text-4xl md:text-5xl font-bold text-ink-primary mb-2 leading-tight tracking-tight truncate" title={currentTrack.Title}>
                                    {currentTrack.Title}
                                </h1>
                                <p className="text-2xl md:text-3xl text-amber2 font-light truncate" title={currentTrack.Artist}>
                                    {currentTrack.Artist || "Unknown Artist"}
                                </p>
                            </div>
                            <div className="text-right shrink-0">
                                <div className="text-6xl font-mono text-ink-muted font-bold tracking-tighter">
                                    {Math.round(currentTrack.BPM)} <span className="text-xl text-ink-placeholder">BPM</span>
                                </div>
                            </div>
                        </div>

                        {/* Waveform — own clean container, no overlapping controls */}
                        <div className="h-56 mb-3 rounded-mx-md overflow-hidden border border-line-subtle bg-mx-deepest/60 shrink-0">
                            <WaveformEditor
                                ref={wavesurferRef}
                                track={currentTrack}
                                simpleMode={true}
                                isPlayingExternal={isPlaying}
                                onPlayPause={setIsPlaying}
                                volume={volume}
                            />
                        </div>

                        {/* Transport — separate row, flat against the shell */}
                        <div className="flex items-center justify-between gap-4 mb-10 px-1">
                            <div className="flex items-center gap-4">
                                <button
                                    onClick={() => {
                                        const prev = currentIndex - 1;
                                        if (prev >= 0) { setIsPlaying(true); setCurrentIndex(prev); loadTrack(queue[prev]); }
                                    }}
                                    className="text-ink-muted hover:text-ink-primary p-2 transition-colors"
                                    title="Previous track"
                                >
                                    <SkipBack size={22} />
                                </button>

                                <button
                                    onClick={() => setIsPlaying(!isPlaying)}
                                    className="bg-amber2 text-mx-deepest rounded-full p-3.5 hover:bg-amber2-hover transition-colors"
                                    title={isPlaying ? 'Pause' : 'Play'}
                                >
                                    {isPlaying ? <Pause size={22} fill="currentColor" /> : <Play size={22} fill="currentColor" className="ml-0.5" />}
                                </button>

                                <button
                                    onClick={() => {
                                        if (wavesurferRef.current) {
                                            wavesurferRef.current.setTime(wavesurferRef.current.getCurrentTime() + 10);
                                        }
                                    }}
                                    className="text-ink-muted hover:text-ink-primary p-2 transition-colors"
                                    title="Skip forward 10s"
                                >
                                    <SkipForward size={22} />
                                </button>
                            </div>

                            <div className="flex items-center gap-2 group/vol">
                                <Volume2 size={16} className="text-ink-muted group-hover/vol:text-ink-secondary transition-colors" />
                                <input
                                    type="range" min="0" max="1" step="0.01"
                                    value={volume}
                                    onChange={e => setVolume(parseFloat(e.target.value))}
                                    className="w-32 h-1 bg-mx-input rounded-full appearance-none cursor-pointer accent-amber2 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-amber2 transition-all"
                                />
                            </div>
                        </div>

                        <div className="grid grid-cols-2 gap-10">
                            {/* Left Column: Rating & Color — flat, hairline-separated rows */}
                            <div className="space-y-6">
                                <div className="py-4 border-b border-line-subtle">
                                    <div className="flex justify-between items-center mb-4">
                                        <label className="mx-caption">Rate Track</label>
                                        <button onClick={handleServiceMark} className="px-3 py-1 text-[10px] font-bold uppercase tracking-wider rounded-mx-sm bg-mx-input border border-line-subtle text-ink-secondary hover:text-amber2 hover:border-amber2/40 hover:bg-amber2/5 transition-colors">
                                            Mark as Service
                                        </button>
                                    </div>
                                    <div className="flex gap-2 justify-between">
                                        {[1, 2, 3, 4, 5].map(star => (
                                            <button key={star} onClick={() => setRating(star)} className="transition-transform hover:scale-110 focus:outline-none">
                                                <Star size={32} className={`transition-colors duration-200 ${rating >= star ? "text-amber2 fill-amber2" : "text-ink-placeholder hover:text-ink-muted"}`} />
                                            </button>
                                        ))}
                                    </div>
                                </div>

                                <div className="py-4">
                                    <label className="mx-caption mb-4 block">Color Code</label>
                                    <div className="flex gap-3 flex-wrap items-center">
                                        {COLORS.slice(1).map(c => (
                                            <button
                                                key={c.id}
                                                onClick={() => setColorId(c.id)}
                                                className={`w-7 h-7 rounded-full border-2 transition-all hover:scale-110 ${colorId === c.id ? 'border-ink-primary scale-110 ring-1 ring-amber2/40' : 'border-transparent opacity-75 hover:opacity-100'}`}
                                                style={{ backgroundColor: c.hex }}
                                                title={c.name}
                                            />
                                        ))}
                                        <button onClick={() => setColorId(0)} className="text-[10px] text-ink-muted hover:text-ink-secondary self-center ml-2 uppercase tracking-widest">Clear</button>
                                    </div>
                                </div>
                            </div>

                            {/* Right Column: Metadata */}
                            <div className="space-y-6">
                                <div>
                                    <label className="text-[10px] font-bold text-ink-muted uppercase mb-2 flex items-center gap-2 tracking-widest"><Disc size={12} /> Genre</label>
                                    <input
                                        list="genres"
                                        value={genre}
                                        onChange={e => setGenre(e.target.value)}
                                        placeholder="Select or type new..."
                                        className="input-glass w-full text-lg"
                                    />
                                    <datalist id="genres">
                                        {genres.map(g => <option key={g.id} value={g.name} />)}
                                    </datalist>
                                </div>
                                <div>
                                    <div>
                                        <label className="text-[10px] font-bold text-ink-muted uppercase mb-2 flex items-center justify-between tracking-widest">
                                            <div className="flex items-center gap-2"><Tag size={12} /> Tags & Comments</div>
                                        </label>

                                        {/* MyTags Module */}
                                        <div className="space-y-4 mb-4 max-h-[400px] overflow-y-auto pr-2 custom-scrollbar">
                                            {Object.entries(TAG_CATEGORIES).map(([category, tags]) => (
                                                <div key={category}>
                                                    <div className="text-[9px] font-black text-ink-placeholder uppercase tracking-[0.2em] mb-2 px-1">{category}</div>
                                                    <div className="flex flex-wrap gap-1.5">
                                                        {tags.map(tag => {
                                                            const isActive = comment.includes(tag);
                                                            return (
                                                                <button
                                                                    key={tag}
                                                                    onClick={() => {
                                                                        if (isActive) {
                                                                            setComment(prev => prev.replace(new RegExp(`${tag},? ?`, 'g'), '').replace(/, $/, '').trim());
                                                                        } else {
                                                                            setComment(prev => (prev ? `${prev}, ${tag}` : tag));
                                                                        }
                                                                    }}
                                                                    className={`px-2.5 py-1 rounded-md text-[10px] font-bold border transition-all ${isActive
                                                                        ? 'bg-amber2/20 border-amber2 text-amber2 shadow-[0_0_10px_rgba(6,182,212,0.2)]'
                                                                        : 'bg-black/20 border-white/5 text-ink-muted hover:border-white/20 hover:text-ink-primary'
                                                                        }`}
                                                                >
                                                                    {tag}
                                                                </button>
                                                            );
                                                        })}
                                                    </div>
                                                </div>
                                            ))}
                                        </div>

                                        <textarea
                                            value={comment}
                                            onChange={e => setComment(e.target.value)}
                                            placeholder="Add specific tags..."
                                            className="input-glass w-full h-24 resize-none text-sm"
                                        />
                                    </div>
                                </div>

                                {/* Pioneer "My Tag" — only available in Live (master.db) mode */}
                                {myTagSupported && (
                                    <div>
                                        <label className="text-[10px] font-bold text-ink-muted uppercase mb-2 flex items-center gap-2 tracking-widest">
                                            <Tag size={12} /> Pioneer My Tag
                                            <span className="ml-auto text-[9px] text-ink-placeholder normal-case tracking-normal">writes to master.db</span>
                                        </label>
                                        <div className="flex flex-wrap gap-1.5 mb-3 max-h-32 overflow-y-auto custom-scrollbar pr-1">
                                            {allMyTags.length === 0 && (
                                                <span className="text-[11px] text-ink-placeholder italic">No My Tags defined yet — create one below.</span>
                                            )}
                                            {allMyTags.map(t => {
                                                const active = trackMyTagIds.includes(String(t.id));
                                                return (
                                                    <button
                                                        key={t.id}
                                                        type="button"
                                                        onClick={() => toggleMyTag(t.id)}
                                                        className={`px-2.5 py-1 rounded-md text-[10px] font-bold border transition-all ${active
                                                            ? 'bg-emerald-500/20 border-emerald-400 text-emerald-300'
                                                            : 'bg-black/20 border-white/5 text-ink-muted hover:border-white/20 hover:text-ink-primary'}`}
                                                    >
                                                        {t.name}
                                                    </button>
                                                );
                                            })}
                                        </div>
                                        <div className="flex gap-2">
                                            <input
                                                type="text"
                                                value={newMyTagName}
                                                onChange={e => setNewMyTagName(e.target.value)}
                                                onKeyDown={e => e.key === 'Enter' && createMyTag()}
                                                placeholder="New My Tag name…"
                                                className="input-glass flex-1 text-xs"
                                            />
                                            <button
                                                type="button"
                                                onClick={createMyTag}
                                                disabled={!newMyTagName.trim()}
                                                className="px-3 py-1.5 rounded-md text-[10px] font-bold bg-emerald-500/20 border border-emerald-400/40 text-emerald-300 hover:bg-emerald-500/30 disabled:opacity-30"
                                            >
                                                + Add
                                            </button>
                                        </div>
                                    </div>
                                )}
                            </div>

                        </div>

                        {/* Footer: Persistent Save & Next Actions */}
                        <div className="mt-8 flex justify-center items-center pb-8">
                            <button
                                onClick={saveAndNext}
                                className="group relative px-16 py-6 bg-amber2 hover:bg-amber2 rounded-2xl font-black text-2xl uppercase tracking-widest text-black shadow-[0_0_40px_rgba(6,182,212,0.4)] hover:shadow-[0_0_60px_rgba(6,182,212,0.6)] transform transition-all hover:-translate-y-1 hover:scale-105 active:scale-95 flex items-center gap-4"
                            >
                                <span className="relative z-10">Save & Next</span>
                                <ArrowRight size={32} className="relative z-10 group-hover:translate-x-2 transition-transform" />
                                <div className="absolute inset-0 rounded-2xl bg-gradient-to-r from-transparent via-white/20 to-transparent translate-x-[-100%] group-hover:animate-shimmer" />
                            </button>
                        </div>
                    </div>
                </div>
            ) : (
                <div className="flex-1 flex items-center justify-center text-white flex-col animate-fade-in">
                    {queue.length > 0 && currentIndex < queue.length ? (
                        // Loading State
                        <div className="flex flex-col items-center">
                            <div className="w-16 h-16 border-4 border-amber2 border-t-transparent rounded-full animate-spin mb-6"></div>
                            <h2 className="text-2xl font-bold mb-2">Loading Track...</h2>
                        </div>
                    ) : (
                        // Actually Completed State
                        <div className="flex flex-col items-center">
                            <div className="w-24 h-24 bg-green-500/20 rounded-full flex items-center justify-center mb-6 shadow-[0_0_30px_rgba(34,197,94,0.2)]">
                                <Zap size={48} className="text-green-500" fill="currentColor" />
                            </div>
                            <h2 className="text-4xl font-bold mb-2">Queue Completed!</h2>
                            <p className="text-ink-secondary">All tracks have been processed.</p>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};

export default RankingView;
