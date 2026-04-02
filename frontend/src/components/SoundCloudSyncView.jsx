import React, { useState, useEffect, useCallback } from 'react';
import {
    Cloud, RefreshCw, ListMusic, Music, Heart, Check, X, Loader2,
    ArrowUpDown, Download, Merge, CheckSquare, Square, ChevronDown,
    ChevronRight, Globe, Lock, Clock, AlertTriangle, Zap, Search, LogIn
} from 'lucide-react';
import api from '../api/api';
import toast from 'react-hot-toast';
import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';

const formatDuration = (ms) => {
    if (!ms) return '0:00';
    const mins = Math.floor(ms / 60000);
    const secs = Math.floor((ms % 60000) / 1000);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
};

const formatTotalDuration = (ms) => {
    if (!ms) return '0 min';
    const hrs = Math.floor(ms / 3600000);
    const mins = Math.floor((ms % 3600000) / 60000);
    if (hrs > 0) return `${hrs}h ${mins}m`;
    return `${mins} min`;
};

const PlaylistCard = ({ playlist, selected, onToggle, onSync, syncing }) => {
    const [expanded, setExpanded] = useState(false);
    const isLikes = playlist.is_likes;
    const artworkUrl = playlist.artwork_url?.replace('-large', '-t300x300') || null;

    return (
        <div className={`glass-panel rounded-2xl border transition-all ${selected ? 'border-orange-500/40 bg-orange-500/5 ring-1 ring-orange-500/20' : 'border-white/5 hover:border-white/10'
            }`}>
            <div className="p-4">
                <div className="flex items-start gap-4">
                    {/* Artwork */}
                    <div className="relative w-20 h-20 rounded-xl overflow-hidden bg-white/5 shrink-0 group">
                        {artworkUrl ? (
                            <img src={artworkUrl} alt="" className="w-full h-full object-cover" loading="lazy" />
                        ) : (
                            <div className="w-full h-full flex items-center justify-center">
                                {isLikes ? <Heart size={28} className="text-red-400" /> : <ListMusic size={28} className="text-orange-400/40" />}
                            </div>
                        )}
                        <button
                            onClick={() => onToggle(playlist.id)}
                            className="absolute inset-0 bg-black/40 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center"
                        >
                            {selected ? (
                                <Check size={24} className="text-orange-400" />
                            ) : (
                                <Square size={24} className="text-white/60" />
                            )}
                        </button>
                    </div>

                    {/* Info */}
                    <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                            <h3 className="text-sm font-bold text-white truncate">{playlist.title}</h3>
                            {playlist.is_public === false && <Lock size={12} className="text-slate-500 shrink-0" />}
                            {isLikes && <Heart size={12} className="text-red-400 fill-red-400 shrink-0" />}
                        </div>

                        <div className="flex items-center gap-3 text-[10px] text-slate-500">
                            <span className="flex items-center gap-1">
                                <Music size={10} /> {playlist.track_count} tracks
                            </span>
                            <span className="flex items-center gap-1">
                                <Clock size={10} /> {formatTotalDuration(playlist.duration)}
                            </span>
                        </div>

                        {/* Action buttons */}
                        <div className="flex items-center gap-2 mt-3">
                            <button
                                onClick={() => onToggle(playlist.id)}
                                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[10px] font-bold transition-all ${selected
                                    ? 'bg-orange-500/20 text-orange-400 border border-orange-500/30'
                                    : 'bg-white/5 text-slate-400 border border-white/10 hover:bg-white/10'
                                    }`}
                            >
                                {selected ? <Check size={10} /> : <Square size={10} />}
                                {selected ? 'Selected' : 'Select'}
                            </button>

                            <button
                                onClick={() => onSync([playlist])}
                                disabled={syncing}
                                className="flex items-center gap-1.5 px-3 py-1.5 bg-cyan-500/10 hover:bg-cyan-500/20 text-cyan-400 rounded-lg text-[10px] font-bold border border-cyan-500/20 transition-all disabled:opacity-30"
                            >
                                {syncing ? <Loader2 size={10} className="animate-spin" /> : <ArrowUpDown size={10} />}
                                Sync
                            </button>

                            <button
                                onClick={() => setExpanded(!expanded)}
                                className="flex items-center gap-1 px-2 py-1.5 text-slate-500 hover:text-slate-300 text-[10px] transition-colors"
                            >
                                {expanded ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
                                Tracks
                            </button>
                        </div>
                    </div>
                </div>
            </div>

            {/* Expanded track list */}
            {expanded && (
                <div className="border-t border-white/5 px-4 py-3 max-h-48 overflow-y-auto">
                    {(playlist.tracks || []).length === 0 ? (
                        <p className="text-[10px] text-slate-600 text-center py-4">No track preview available</p>
                    ) : (
                        <div className="space-y-1">
                            {playlist.tracks.slice(0, 30).map((track, i) => (
                                <div key={track?.id || i} className="flex items-center gap-2 py-1 group">
                                    <span className="text-[9px] text-slate-600 w-5 text-right tabular-nums">{i + 1}</span>
                                    <div className="flex-1 min-w-0">
                                        <div className="text-[11px] text-slate-300 truncate">{track?.title || 'Unknown Track'}</div>
                                        <div className="text-[9px] text-slate-500 truncate">{track?.artist || 'Unknown Artist'}</div>
                                    </div>
                                    <span className="text-[9px] text-slate-600 tabular-nums">{formatDuration(track?.duration || 0)}</span>
                                </div>
                            ))}
                            {playlist.tracks.length > 30 && (
                                <div className="text-[10px] text-slate-600 text-center pt-2">
                                    + {playlist.tracks.length - 30} more tracks
                                </div>
                            )}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
};

const SoundCloudSyncView = () => {
    const [playlists, setPlaylists] = useState([]);
    const [likes, setLikes] = useState(null);
    const [loading, setLoading] = useState(false);
    const [syncing, setSyncing] = useState(false);
    const [selectedIds, setSelectedIds] = useState(new Set());
    const [syncResults, setSyncResults] = useState(null);
    const [filter, setFilter] = useState('');
    const [mergeMode, setMergeMode] = useState(false);
    const [mergeName, setMergeName] = useState('');
    const [isLoggingIn, setIsLoggingIn] = useState(false);
    const [loginMessage, setLoginMessage] = useState('');
    const [authRequired, setAuthRequired] = useState(false); // true → show login screen

    // Criterion 10: isBusy ref prevents double-execution on rapid clicks
    const isBusy = React.useRef(false);

    const showLoginScreen = () => {
        setPlaylists([]);
        setLikes(null);
        setAuthRequired(true);
    };

    const fetchPlaylists = useCallback(async () => {
        if (isBusy.current) return; // race guard
        isBusy.current = true;
        setLoading(true);
        try {
            const res = await api.get('/api/soundcloud/playlists');

            // EC: Unexpected backend error response format { status: "error", message: "..." }
            if (res.data?.status === 'error' || res.data?.message) {
                throw new Error(res.data.message || 'Backend returned an error format');
            }

            // DoD proof: log the raw payload in DevTools so we can confirm mapping works.
            console.log('[SC] fetchPlaylists raw response:', res.data);

            // EC4/EC1: Null-payload guard. SC API can return empty collections `[]` 
            // instead of failing. We must map safely.
            const pls = Array.isArray(res.data?.playlists) ? res.data.playlists : [];
            const lks = res.data?.likes ?? null;

            console.log(`[SC] Loaded ${pls.length} playlists, likes: ${lks?.track_count ?? 0} tracks`);
            console.log('Mapped Playlists for UI:', pls); // Required DoD Proof

            setPlaylists(pls);
            setLikes(lks);
            setAuthRequired(false);

        } catch (e) {
            const status   = e.response?.status;
            const detail   = e.response?.data?.detail || e.message || 'Unknown error';

            console.error('[SC] fetchPlaylists error:', status, detail);

            // EC2: Token expiry — backend returns 401 with detail="auth_expired"
            if (status === 401 || detail === 'auth_expired' || detail?.toLowerCase().includes('auth')) {
                showLoginScreen();

            // EC3: Rate limited — show a friendly message, don't clear auth state
            } else if (status === 429) {
                toast.error('SoundCloud Rate Limit erreicht. Bitte kurz warten und nochmal versuchen.');

            } else {
                toast.error('Fehler beim Laden der Playlisten: ' + detail);
            }
        } finally {
            setLoading(false);
            isBusy.current = false;
        }
    }, []);

    useEffect(() => {
        fetchPlaylists();

        // Listen to native auth events from Tauri
        const unlisten = listen('sc-login-progress', (event) => {
            setLoginMessage(event.payload?.message || '');
        });

        return () => { unlisten.then(f => f()); };
    }, [fetchPlaylists]);

    const handleLogin = async () => {
        if (isBusy.current) return;
        isBusy.current = true;
        setIsLoggingIn(true);
        setLoginMessage('Initializing secure login...');
        try {
            // Criterion 1 & 4: invoke only exists in Tauri desktop context
            const token = await invoke('login_to_soundcloud');

            setLoginMessage('Saving credentials securely...');
            await api.post('/api/soundcloud/auth-token', { token });
            toast.success('SoundCloud Login erfolgreich!');
            setAuthRequired(false);
            await fetchPlaylists();
        } catch (e) {
            const errStr = String(e);
            // Criterion 4: Detect Tauri-unavailability specifically — don't leak raw TypeErrors
            if (errStr.includes('invoke') || errStr.includes('TAURI') || errStr.includes('undefined')) {
                toast.error('Login ist nur in der Desktop-App verfügbar, nicht im Browser.');
            } else {
                toast.error(`Login fehlgeschlagen: ${errStr}`);
            }
        } finally {
            setIsLoggingIn(false);
            setLoginMessage('');
            isBusy.current = false;
        }
    };

    const toggleSelect = (id) => {
        setSelectedIds(prev => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id); else next.add(id);
            return next;
        });
    };

    const selectAll = () => {
        const allIds = new Set(playlists.map(p => p.id));
        if (likes) allIds.add(likes.id);
        setSelectedIds(allIds);
    };

    const deselectAll = () => setSelectedIds(new Set());

    const handleSync = async (specificPlaylists = null) => {
        if (isBusy.current || syncing) return; // race guard
        isBusy.current = true;
        setSyncing(true);
        setSyncResults(null);
        try {
            let res;
            if (specificPlaylists) {
                const ids = specificPlaylists.map(p => p.id).filter(id => id !== 'likes');
                const includeLikes = specificPlaylists.some(p => p.is_likes);
                res = await api.post('/api/soundcloud/sync', { playlist_ids: ids, include_likes: includeLikes });
            } else {
                const ids = [...selectedIds].filter(id => id !== 'likes');
                const includeLikes = selectedIds.has('likes');
                res = await api.post('/api/soundcloud/sync', { playlist_ids: ids, include_likes: includeLikes });
            }
            setSyncResults(res.data.results);
            toast.success(res.data.message || 'Sync erfolgreich!');
        } catch (e) {
            const status = e.response?.status;
            const detail = e.response?.data?.detail || e.message;
            if (status === 409) {
                toast.error('Sync läuft bereits. Bitte warten.');
            } else if (status === 401 || detail === 'auth_expired') {
                // Criterion 5: Mid-session token expiry
                toast.error('Session abgelaufen. Bitte neu anmelden.');
                showLoginScreen();
            } else {
                toast.error('Sync fehlgeschlagen: ' + detail);
            }
        } finally {
            setSyncing(false);
            isBusy.current = false;
        }
    };

    const handleSyncAll = async () => {
        if (isBusy.current || syncing) return;
        isBusy.current = true;
        setSyncing(true);
        setSyncResults(null);
        try {
            const res = await api.post('/api/soundcloud/sync-all');
            setSyncResults(res.data.results);
            toast.success(res.data.message || 'Alle Playlisten synchronisiert!');
        } catch (e) {
            const status = e.response?.status;
            const detail = e.response?.data?.detail || e.message;
            if (status === 409) {
                toast.error('Sync läuft bereits. Bitte warten.');
            } else if (status === 401 || detail === 'auth_expired') {
                toast.error('Session abgelaufen. Bitte neu anmelden.');
                showLoginScreen();
            } else {
                toast.error('Sync-All fehlgeschlagen: ' + detail);
            }
        } finally {
            setSyncing(false);
            isBusy.current = false;
        }
    };

    const handleMerge = async () => {
        if (!mergeName.trim()) { toast.error('Bitte gib einen Namen ein'); return; }
        if (selectedIds.size < 2) { toast.error('Wähle mindestens 2 Playlisten'); return; }
        if (isBusy.current || syncing) return;
        isBusy.current = true;
        setSyncing(true);
        try {
            const ids = [...selectedIds].filter(id => id !== 'likes');
            const res = await api.post('/api/soundcloud/merge', { playlist_ids: ids, merged_name: mergeName });
            toast.success(res.data.message || 'Playlisten zusammengeführt!');
            setMergeMode(false);
            setMergeName('');
            setSelectedIds(new Set());
        } catch (e) {
            const status = e.response?.status;
            const detail = e.response?.data?.detail || e.message;
            if (status === 409) {
                toast.error('Eine andere Operation läuft bereits.');
            } else {
                toast.error('Zusammenführen fehlgeschlagen: ' + detail);
            }
        } finally {
            setSyncing(false);
            isBusy.current = false;
        }
    };

    const allPlaylists = [...playlists];
    if (likes) allPlaylists.unshift(likes);

    const filtered = filter
        ? allPlaylists.filter(p => p.title.toLowerCase().includes(filter.toLowerCase()))
        : allPlaylists;

    return (
        <div className="h-full flex flex-col bg-transparent text-white overflow-hidden animate-fade-in">
            {/* Header */}
            <div className="p-6 pb-4 border-b border-white/5">
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-4">
                        <div className="p-3 bg-orange-500/20 rounded-xl border border-orange-500/30">
                            <Cloud size={28} className="text-orange-400" />
                        </div>
                        <div>
                            <h1 className="text-2xl font-black italic tracking-tighter uppercase">SoundCloud Manager</h1>
                            <p className="text-slate-500 text-sm">
                                {playlists.length} Playlisten · {likes?.track_count || 0} Likes
                            </p>
                        </div>
                    </div>
                    <div className="flex items-center gap-2">
                        <button
                            onClick={handleSyncAll}
                            disabled={syncing || allPlaylists.length === 0}
                            className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-orange-500/20 to-red-500/20 hover:from-orange-500/30 hover:to-red-500/30 text-orange-400 rounded-xl text-sm font-bold border border-orange-500/30 transition-all disabled:opacity-30"
                        >
                            {syncing ? <Loader2 size={16} className="animate-spin" /> : <ArrowUpDown size={16} />}
                            Alle Synchronisieren
                        </button>
                        <button
                            onClick={fetchPlaylists}
                            disabled={loading}
                            className="flex items-center gap-2 px-4 py-2 bg-white/5 hover:bg-white/10 rounded-xl text-sm font-bold border border-white/10 transition-all"
                        >
                            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} /> Aktualisieren
                        </button>
                    </div>
                </div>

                {/* Toolbar */}
                <div className="flex items-center gap-3 mt-4">
                    {/* Search */}
                    <div className="flex-1 relative">
                        <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
                        <input
                            type="text"
                            placeholder="Playlisten suchen..."
                            value={filter}
                            onChange={(e) => setFilter(e.target.value)}
                            className="w-full pl-9 pr-3 py-2 bg-white/5 border border-white/10 rounded-xl text-sm text-white placeholder:text-slate-600 focus:outline-none focus:border-orange-500/30"
                        />
                    </div>

                    {/* Selection controls */}
                    <div className="flex items-center gap-1.5">
                        <button
                            onClick={selectAll}
                            className="flex items-center gap-1 px-3 py-2 bg-white/5 hover:bg-white/10 rounded-lg text-[10px] font-bold text-slate-400 border border-white/10 transition-all"
                        >
                            <CheckSquare size={12} /> Alle
                        </button>
                        <button
                            onClick={deselectAll}
                            className="flex items-center gap-1 px-3 py-2 bg-white/5 hover:bg-white/10 rounded-lg text-[10px] font-bold text-slate-400 border border-white/10 transition-all"
                        >
                            <X size={12} /> Keine
                        </button>
                    </div>

                    {/* Selected actions */}
                    {selectedIds.size > 0 && (
                        <div className="flex items-center gap-2 pl-2 border-l border-white/10">
                            <span className="text-[10px] text-orange-400 font-bold">{selectedIds.size} ausgewählt</span>
                            <button
                                onClick={() => handleSync()}
                                disabled={syncing}
                                className="flex items-center gap-1.5 px-3 py-2 bg-cyan-500/15 hover:bg-cyan-500/25 text-cyan-400 rounded-lg text-[10px] font-bold border border-cyan-500/20 transition-all disabled:opacity-30"
                            >
                                <ArrowUpDown size={12} /> Sync Auswahl
                            </button>
                            <button
                                onClick={() => setMergeMode(!mergeMode)}
                                className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-[10px] font-bold border transition-all ${mergeMode
                                    ? 'bg-purple-500/15 text-purple-400 border-purple-500/30'
                                    : 'bg-white/5 text-slate-400 border-white/10 hover:bg-white/10'
                                    }`}
                            >
                                <Merge size={12} /> Zusammenführen
                            </button>
                        </div>
                    )}
                </div>

                {/* Merge panel */}
                {mergeMode && selectedIds.size >= 2 && (
                    <div className="mt-3 p-3 bg-purple-500/10 border border-purple-500/20 rounded-xl flex items-center gap-3">
                        <Merge size={16} className="text-purple-400 shrink-0" />
                        <input
                            type="text"
                            placeholder="Name der zusammengeführten Playlist..."
                            value={mergeName}
                            onChange={(e) => setMergeName(e.target.value)}
                            className="flex-1 px-3 py-1.5 bg-white/5 border border-white/10 rounded-lg text-sm text-white placeholder:text-slate-600 focus:outline-none focus:border-purple-500/30"
                        />
                        <button
                            onClick={handleMerge}
                            disabled={syncing || !mergeName.trim()}
                            className="flex items-center gap-1.5 px-4 py-1.5 bg-purple-500 hover:bg-purple-400 text-white rounded-lg text-xs font-bold transition-all disabled:opacity-30"
                        >
                            {syncing ? <Loader2 size={12} className="animate-spin" /> : <Merge size={12} />}
                            Zusammenführen
                        </button>
                    </div>
                )}
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto p-6">
                {loading && allPlaylists.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-full">
                        <Loader2 size={32} className="animate-spin text-orange-400 mb-4" />
                        <span className="text-slate-500 text-sm">Lade SoundCloud Playlisten...</span>
                    </div>
                ) : authRequired ? (
                    <div className="flex flex-col items-center justify-center h-full text-center">
                        <Cloud size={48} className="text-slate-700 mb-4" />
                        <h2 className="text-xl font-bold text-slate-400 mb-2">Login Required</h2>
                        <p className="text-slate-600 text-sm max-w-md mb-8">
                            Bitte authentifiziere dich bei SoundCloud, um deine Playlisten und Likes zu laden.
                        </p>

                        <button
                            onClick={handleLogin}
                            disabled={isLoggingIn}
                            className={`flex flex-col items-center justify-center gap-2 px-10 py-4 ${isLoggingIn ? 'bg-orange-500/20' : 'bg-gradient-to-r from-orange-500 to-red-500 hover:from-orange-400 hover:to-red-400'} rounded-2xl text-white font-black uppercase tracking-tight shadow-xl shadow-orange-500/10 transition-all`}
                        >
                            <div className="flex items-center gap-3">
                                {isLoggingIn ? <Loader2 size={20} className="animate-spin" /> : <LogIn size={20} />}
                                {isLoggingIn ? 'Authenticating...' : 'Login with SoundCloud'}
                            </div>
                            {isLoggingIn && loginMessage && (
                                <span className="text-[10px] text-orange-200 uppercase tracking-widest">{loginMessage}</span>
                            )}
                        </button>
                    </div>
                ) : (
                    <>
                        {/* Sync Results */}
                        {syncResults && (
                            <div className="mb-6 glass-panel rounded-2xl p-4 border border-emerald-500/20 bg-emerald-500/5">
                                <h3 className="text-sm font-bold text-emerald-400 mb-3 flex items-center gap-2">
                                    <Check size={16} /> Sync Ergebnisse
                                </h3>
                                <div className="space-y-2">
                                    {syncResults.map((r, i) => (
                                        <div key={i} className="flex items-center justify-between text-xs py-1.5 border-b border-white/5 last:border-0">
                                            <span className="text-slate-300 font-medium truncate mr-4">{r.playlist_title}</span>
                                            <div className="flex items-center gap-3 shrink-0">
                                                <span className="text-emerald-400">+{r.added} hinzugefügt</span>
                                                <span className="text-cyan-400">{r.matched} erkannt</span>
                                                <span className="text-slate-600">{r.unmatched} nicht gefunden</span>
                                            </div>
                                        </div>
                                    ))}
                                </div>
                                <button
                                    onClick={() => setSyncResults(null)}
                                    className="mt-3 text-[10px] text-slate-500 hover:text-slate-300 transition-colors"
                                >
                                    Ergebnisse schließen
                                </button>
                            </div>
                        )}

                        {/* Playlist Grid */}
                        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                            {filtered.map(pl => (
                                <PlaylistCard
                                    key={pl.id}
                                    playlist={pl}
                                    selected={selectedIds.has(pl.id)}
                                    onToggle={toggleSelect}
                                    onSync={handleSync}
                                    syncing={syncing}
                                />
                            ))}
                        </div>

                        {filtered.length === 0 && filter && (
                            <div className="text-center py-12">
                                <Search size={32} className="text-slate-700 mx-auto mb-3" />
                                <p className="text-slate-500 text-sm">Keine Playlisten für "{filter}" gefunden</p>
                            </div>
                        )}
                    </>
                )}
            </div>
        </div>
    );
};

export default SoundCloudSyncView;
