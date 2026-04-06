import React, { useState, useEffect } from 'react';
import { X, Check, AlertTriangle, Skull, Search, ChevronRight, Download, Loader2 } from 'lucide-react';
import api from '../api/api';
import toast from 'react-hot-toast';

const ScoreBar = ({ score }) => {
    const pct = Math.round(score * 100);
    const color = score >= 0.9 ? 'bg-emerald-500' : score >= 0.75 ? 'bg-amber-500' : 'bg-orange-500';
    return (
        <div className="flex items-center gap-1.5 shrink-0">
            <div className="w-16 h-1.5 bg-white/10 rounded-full overflow-hidden">
                <div className={`h-full ${color} rounded-full`} style={{ width: `${pct}%` }} />
            </div>
            <span className="text-[9px] text-slate-500 tabular-nums w-8">{pct}%</span>
        </div>
    );
};

const STATUS_ICON = {
    matched:   <Check size={10} className="text-emerald-400 shrink-0" />,
    unmatched: <AlertTriangle size={10} className="text-amber-400 shrink-0" />,
    dead:      <Skull size={10} className="text-slate-600 shrink-0" />,
};

const STATUS_LABEL = {
    matched:   'Erkannt',
    unmatched: 'Nicht gefunden',
    dead:      'Gelöscht / Privat',
};

/**
 * MatchInspectorModal
 * Loads preview-matches for a given SoundCloud playlist and displays them
 * in a searchable, filterable table. No DB writes happen here.
 *
 * Props:
 *   playlist  – { id, title, is_likes } – the SC playlist to inspect
 *   onClose   – () => void
 *   onSync    – (playlist) => void — called when user clicks "Sync Now"
 */
const MatchInspectorModal = ({ playlist, onClose, onSync }) => {
    const [loading, setLoading] = useState(true);
    const [data, setData]       = useState(null);
    const [filter, setFilter]   = useState('');
    const [statusFilter, setStatusFilter] = useState('all'); // all | matched | unmatched | dead
    const [downloadingUrl, setDownloadingUrl] = useState(null);

    const handleDownload = async (url, title) => {
        try {
            setDownloadingUrl(url);
            await api.post('/api/soundcloud/download', { url, title });
            toast.success('Download in die Warteschlange eingereiht');
        } catch (e) {
            toast.error('Download-Fehler: ' + (e.response?.data?.detail || e.message));
        } finally {
            setDownloadingUrl(null);
        }
    };

    useEffect(() => {
        if (!playlist) return;
        setLoading(true);
        api.post('/api/soundcloud/preview-matches', {
            playlist_id: playlist.id === 'likes' ? 0 : playlist.id,
            is_likes: !!playlist.is_likes,
        })
            .then(r => { setData(r.data); setLoading(false); })
            .catch(e => {
                toast.error('Inspector konnte Matches nicht laden: ' + (e.response?.data?.detail || e.message));
                setLoading(false);
            });
    }, [playlist]);

    if (!playlist) return null;

    const matches = data?.matches || [];
    const visible = matches.filter(m => {
        if (statusFilter !== 'all' && m.status !== statusFilter) return false;
        if (!filter) return true;
        const q = filter.toLowerCase();
        return (
            m.sc_title?.toLowerCase().includes(q) ||
            m.sc_artist?.toLowerCase().includes(q) ||
            m.local_title?.toLowerCase().includes(q) ||
            m.local_artist?.toLowerCase().includes(q)
        );
    });

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center p-4"
            style={{ background: 'rgba(0,0,0,0.75)', backdropFilter: 'blur(4px)' }}
            onClick={(e) => e.target === e.currentTarget && onClose()}
        >
            <div className="w-full max-w-3xl max-h-[85vh] flex flex-col bg-slate-950 border border-white/10 rounded-2xl shadow-2xl overflow-hidden">

                {/* Header */}
                <div className="flex items-center justify-between px-5 py-4 border-b border-white/5">
                    <div>
                        <h2 className="text-sm font-black text-white italic uppercase tracking-tight">
                            Match Inspector
                        </h2>
                        <p className="text-[11px] text-slate-500 mt-0.5 truncate">
                            {playlist.title}
                        </p>
                    </div>
                    <button onClick={onClose} className="p-1.5 hover:bg-white/5 rounded-lg text-slate-500 hover:text-white transition-colors">
                        <X size={16} />
                    </button>
                </div>

                {loading ? (
                    <div className="flex-1 flex items-center justify-center py-16">
                        <div className="flex flex-col items-center gap-3">
                            <div className="w-8 h-8 border-2 border-orange-500/30 border-t-orange-500 rounded-full animate-spin" />
                            <span className="text-slate-500 text-xs">Analysiere Matches...</span>
                        </div>
                    </div>
                ) : (
                    <>
                        {/* Stats bar */}
                        {data && (
                            <div className="flex items-center gap-4 px-5 py-3 border-b border-white/5 bg-white/2">
                                <span className="text-[10px] text-slate-500">{data.total} Tracks</span>
                                <span className="flex items-center gap-1 text-[10px] text-emerald-400">
                                    <Check size={10} /> {data.matched} erkannt
                                </span>
                                <span className="flex items-center gap-1 text-[10px] text-amber-400">
                                    <AlertTriangle size={10} /> {data.unmatched} nicht gefunden
                                </span>
                                {data.dead > 0 && (
                                    <span className="flex items-center gap-1 text-[10px] text-slate-600">
                                        <Skull size={10} /> {data.dead} gelöscht
                                    </span>
                                )}
                                <div className="flex-1" />
                                <button
                                    onClick={() => { onSync([playlist]); onClose(); }}
                                    className="flex items-center gap-1.5 px-3 py-1.5 bg-gradient-to-r from-orange-500 to-red-500 hover:from-orange-400 hover:to-red-400 text-white rounded-lg text-[10px] font-bold transition-all"
                                >
                                    <Check size={10} /> Jetzt Syncen
                                </button>
                            </div>
                        )}

                        {/* Filter row */}
                        <div className="flex items-center gap-2 px-5 py-2 border-b border-white/5">
                            <div className="relative flex-1">
                                <Search size={12} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
                                <input
                                    type="text"
                                    placeholder="Track suchen..."
                                    value={filter}
                                    onChange={e => setFilter(e.target.value)}
                                    className="w-full pl-8 pr-3 py-1.5 bg-white/4 border border-white/10 rounded-lg text-[11px] text-white placeholder:text-slate-600 focus:outline-none focus:border-orange-500/30"
                                />
                            </div>
                            {['all', 'matched', 'unmatched', 'dead'].map(s => (
                                <button
                                    key={s}
                                    onClick={() => setStatusFilter(s)}
                                    className={`px-2.5 py-1.5 rounded-lg text-[9px] font-bold uppercase tracking-wider transition-all ${
                                        statusFilter === s
                                            ? 'bg-orange-500/20 text-orange-400 border border-orange-500/30'
                                            : 'bg-white/4 text-slate-500 border border-white/8 hover:bg-white/8'
                                    }`}
                                >
                                    {s === 'all' ? 'Alle' : STATUS_LABEL[s]}
                                </button>
                            ))}
                        </div>

                        {/* Track table */}
                        <div className="flex-1 overflow-y-auto">
                            {visible.length === 0 ? (
                                <div className="flex items-center justify-center py-12 text-slate-600 text-xs">
                                    Keine Tracks gefunden
                                </div>
                            ) : (
                                <div className="divide-y divide-white/3">
                                    {visible.map((m, i) => (
                                        <div
                                            key={i}
                                            className={`grid grid-cols-[auto_1fr_auto_1fr_auto] items-center gap-3 px-5 py-2.5 group hover:bg-white/2 transition-colors ${
                                                m.status === 'dead' ? 'opacity-40' : ''
                                            }`}
                                        >
                                            {/* Status icon */}
                                            {STATUS_ICON[m.status]}

                                            {/* SC track */}
                                            <div className="min-w-0">
                                                <a
                                                    href={m.sc_url || '#'}
                                                    target="_blank"
                                                    rel="noreferrer"
                                                    className="text-[11px] text-slate-200 hover:text-orange-400 truncate block transition-colors"
                                                >
                                                    {m.sc_title || '—'}
                                                </a>
                                                <span className="text-[9px] text-slate-500 truncate">{m.sc_artist}</span>
                                            </div>

                                            {/* Arrow + Score */}
                                            <div className="flex flex-col items-center gap-0.5 shrink-0">
                                                <ChevronRight size={10} className="text-slate-700" />
                                                {m.status === 'matched' && <ScoreBar score={m.score} />}
                                            </div>

                                            {/* Local track */}
                                            <div className="min-w-0">
                                                {m.local_title ? (
                                                    <>
                                                        <div className="text-[11px] text-emerald-300 truncate">{m.local_title}</div>
                                                        <div className="text-[9px] text-slate-500 truncate">{m.local_artist}</div>
                                                    </>
                                                ) : (
                                                    <span className="text-[10px] text-slate-600 italic">
                                                        {m.status === 'dead' ? 'Gelöscht / Privat' : 'Nicht in Library'}
                                                    </span>
                                                )}
                                            </div>

                                            {/* Local ID badge or Download button */}
                                            <div className="shrink-0 flex items-center justify-end min-w-[60px]">
                                                {m.local_id && (
                                                    <span className="text-[8px] text-slate-700 font-mono shrink-0">#{m.local_id}</span>
                                                )}
                                                {m.status === 'unmatched' && m.sc_url && (
                                                    <button
                                                        onClick={() => handleDownload(m.sc_url, m.sc_title)}
                                                        disabled={downloadingUrl === m.sc_url}
                                                        className="p-1.5 bg-orange-500/10 hover:bg-orange-500/20 text-orange-400 rounded-lg transition-colors border border-orange-500/20 disabled:opacity-50"
                                                        title="Track herunterladen"
                                                    >
                                                        {downloadingUrl === m.sc_url ? (
                                                            <Loader2 size={12} className="animate-spin" />
                                                        ) : (
                                                            <Download size={12} />
                                                        )}
                                                    </button>
                                                )}
                                            </div>
                                        </div>
                                    ))}
                                </div>
                            )}
                        </div>
                    </>
                )}
            </div>
        </div>
    );
};

export default MatchInspectorModal;
