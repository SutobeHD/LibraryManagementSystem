import React, { useState, useEffect, useMemo } from 'react';
import api from '../api/api';
import {
    Download, CheckCircle, AlertTriangle, Loader2, Music, Sparkles,
    FolderInput, Activity, ListMusic, Clock, Trash2, Filter, TrendingUp,
    BarChart3, Zap,
} from 'lucide-react';

// Stage pipeline (in execution order) — covers BOTH SC-DL and local-import
const STAGES = [
    { key: 'Queued',           label: 'Queued',     icon: Clock,        color: 'text-ink-muted',    },
    { key: 'Starting',         label: 'Queued',     icon: Clock,        color: 'text-ink-muted',    },
    { key: 'Resolving',        label: 'Resolve',    icon: Activity,     color: 'text-cyan-400',     },
    { key: 'Downloading',      label: 'Download',   icon: Download,     color: 'text-orange-400',   },
    { key: 'Downloaded',       label: 'Downloaded', icon: CheckCircle,  color: 'text-orange-300',   },
    { key: 'Analyzing',        label: 'Analyse',    icon: BarChart3,    color: 'text-purple-400',   },
    { key: 'Importing',        label: 'Library',    icon: FolderInput,  color: 'text-blue-400',     },
    { key: 'ANLZ',             label: 'ANLZ',       icon: Sparkles,     color: 'text-cyan-300',     },
    { key: 'Sorting',          label: 'Playlist',   icon: ListMusic,    color: 'text-amber2',       },
    { key: 'Completed',        label: 'Fertig',     icon: CheckCircle,  color: 'text-emerald-400',  },
];

const FAILURE_STATES = new Set(['Failed', 'Error', 'Analysis Failed']);
// Successful end-states that aren't a fresh full pipeline run.
// "Skipped" = registry hit but no playlist target.
// "Linked"  = registry hit + linked into a SC_<…> playlist.
// "Duplicate" = SHA-256 matched an existing imported file.
const SKIP_STATES = new Set(['Skipped', 'Linked', 'Duplicate']);

const STATUS_LABELS = {
    Linked: 'Verlinkt',
    Skipped: 'Übersprungen',
    Duplicate: 'Duplikat',
    Importing: 'Importing',
    Sorting: 'Playlist',
    Analyzing: 'Analyse',
    Downloaded: 'Downloaded',
    Downloading: 'Download',
    Resolving: 'Resolve',
    Starting: 'Queued',
    Completed: 'Fertig',
    Failed: 'Fehler',
    Error: 'Fehler',
    'Analysis Failed': 'Analyse-Fehler',
};

const stageIndex = (status) => {
    const i = STAGES.findIndex(s => s.key === status);
    if (i >= 0) return i;
    // Skip-states map onto the playlist-link stage so the timeline still reads
    // "this got into a playlist" without a noisy 0-fallback.
    if (SKIP_STATES.has(status)) return STAGES.findIndex(s => s.key === 'Sorting');
    return 0;
};

const fmtDuration = (ms) => {
    if (!ms || ms < 0) return '—';
    const s = Math.floor(ms / 1000);
    if (s < 60) return `${s}s`;
    return `${Math.floor(s / 60)}m ${s % 60}s`;
};

const StagePipeline = ({ task }) => {
    const isFailed = FAILURE_STATES.has(task.status);
    const isSkip = SKIP_STATES.has(task.status);
    const isDone = task.status === 'Completed' || isSkip;
    const cur = stageIndex(task.status);

    const stageMap = useMemo(() => {
        const m = {};
        (task.stage_history || []).forEach(h => { m[h.stage] = h.ts; });
        return m;
    }, [task.stage_history]);

    return (
        <div className="flex items-stretch gap-1 mt-3 overflow-x-auto pb-1">
            {STAGES.map((s, i) => {
                const reached = i <= cur && !isFailed;
                const active = i === cur && !isFailed && !isDone;
                const ts = stageMap[s.key];
                const Icon = s.icon;
                return (
                    <div
                        key={s.key}
                        className={`flex-1 min-w-[60px] flex flex-col items-center gap-1 px-1 py-1.5 rounded transition-all
                            ${reached ? 'bg-white/5' : 'bg-mx-card/40 opacity-40'}
                            ${active ? 'ring-1 ring-amber2/40 bg-amber2/5' : ''}
                        `}
                    >
                        <Icon
                            size={12}
                            className={`${reached ? s.color : 'text-ink-placeholder'} ${active ? 'animate-pulse' : ''}`}
                        />
                        <span className={`text-[8px] uppercase tracking-wide ${reached ? 'text-ink-secondary' : 'text-ink-placeholder'}`}>
                            {s.label}
                        </span>
                        {ts && (
                            <span className="text-[7px] text-ink-placeholder font-mono">
                                {new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                            </span>
                        )}
                    </div>
                );
            })}
        </div>
    );
};

const TaskCard = ({ task }) => {
    const isFailed = FAILURE_STATES.has(task.status);
    const isSkip = SKIP_STATES.has(task.status);
    const isDone = task.status === 'Completed' || isSkip;
    const elapsed = task.start_time ? (Date.now() / 1000 - task.start_time) * 1000 : 0;

    return (
        <div className={`p-4 rounded-2xl border transition-all
            ${isFailed ? 'bg-red-500/5 border-red-500/30'
                : isDone ? 'bg-emerald-500/5 border-emerald-500/20'
                : 'bg-mx-card border-white/5 hover:border-white/10'}
        `}>
            <div className="flex items-start gap-3">
                <div className={`shrink-0 w-10 h-10 rounded-xl flex items-center justify-center
                    ${isFailed ? 'bg-red-500/10' : isDone ? 'bg-emerald-500/10' : 'bg-orange-500/10'}`}>
                    {isFailed ? <AlertTriangle size={18} className="text-red-400" />
                        : isDone ? <CheckCircle size={18} className="text-emerald-400" />
                        : <Loader2 size={18} className="text-orange-400 animate-spin" />}
                </div>
                <div className="flex-1 min-w-0">
                    <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0 flex-1">
                            <div className="flex items-center gap-2 mb-0.5">
                                {task._src === 'import' ? (
                                    <span className="px-1.5 py-0.5 rounded text-[8px] font-bold uppercase tracking-wider bg-blue-500/20 text-blue-300 border border-blue-500/30">Lokal</span>
                                ) : (
                                    <span className="px-1.5 py-0.5 rounded text-[8px] font-bold uppercase tracking-wider bg-orange-500/20 text-orange-300 border border-orange-500/30">SC</span>
                                )}
                                <h3 className="text-sm font-bold text-white truncate flex-1" title={task.title}>
                                    {task.title || '(unbekannt)'}
                                </h3>
                            </div>
                            <div className="flex items-center gap-2 text-[11px] text-ink-muted">
                                {task.artist && <span className="truncate max-w-[180px]">{task.artist}</span>}
                                {task.file_path && task._src === 'import' && (
                                    <span className="truncate max-w-[260px] font-mono text-[10px]" title={task.file_path}>
                                        {task.file_path.split(/[\\\/]/).slice(-2).join('/')}
                                    </span>
                                )}
                                {task.playlist_title && (
                                    <>
                                        <span className="text-ink-placeholder">·</span>
                                        <span className="flex items-center gap-1 text-amber2">
                                            <ListMusic size={10} />
                                            SC_{task.playlist_title}
                                        </span>
                                    </>
                                )}
                            </div>
                        </div>
                        <div className="text-right text-[10px] text-ink-muted shrink-0 flex flex-col items-end gap-0.5">
                            <span className={`font-bold uppercase tracking-wider ${
                                isFailed ? 'text-red-400'
                                    : task.status === 'Completed' ? 'text-emerald-400'
                                    : isSkip ? 'text-cyan-400'
                                    : 'text-amber2'
                            }`}>
                                {STATUS_LABELS[task.status] || task.status}
                            </span>
                            <span className="font-mono">{task.progress || 0}%</span>
                            <span className="font-mono text-ink-placeholder">{fmtDuration(elapsed)}</span>
                        </div>
                    </div>

                    {/* Progress bar */}
                    {!isFailed && (
                        <div className="w-full h-1 bg-white/5 rounded-full overflow-hidden mt-2.5">
                            <div
                                className={`h-full transition-all ${isDone ? 'bg-emerald-500' : 'bg-gradient-to-r from-orange-500 to-amber-400'}`}
                                style={{ width: `${task.progress || 0}%` }}
                            />
                        </div>
                    )}

                    {/* BPM/Key after analysis */}
                    {(task.bpm || task.key) && (
                        <div className="flex items-center gap-3 mt-2 text-[11px]">
                            {task.bpm && (
                                <span className="flex items-center gap-1 text-purple-300">
                                    <Zap size={10} /> {Math.round(task.bpm)} BPM
                                </span>
                            )}
                            {task.key && (
                                <span className="flex items-center gap-1 text-blue-300">
                                    <Music size={10} /> {task.key}
                                </span>
                            )}
                            {task.local_track_id && (
                                <span className="text-ink-muted text-[10px] font-mono">
                                    ID {task.local_track_id}
                                </span>
                            )}
                        </div>
                    )}

                    {/* Error message */}
                    {isFailed && task.error && (
                        <div className="mt-2 text-[11px] text-red-300 bg-red-500/10 border border-red-500/20 rounded-lg px-2 py-1.5">
                            {task.error}
                        </div>
                    )}

                    <StagePipeline task={task} />
                </div>
            </div>
        </div>
    );
};

const StatCard = ({ icon: Icon, label, value, color = 'text-amber2' }) => (
    <div className="flex-1 bg-mx-card border border-white/5 rounded-xl p-3">
        <div className="flex items-center gap-2 mb-1">
            <Icon size={12} className={color} />
            <span className="text-[10px] uppercase tracking-wider text-ink-muted">{label}</span>
        </div>
        <div className={`text-xl font-bold ${color} font-mono`}>{value}</div>
    </div>
);

const DownloadManagerView = () => {
    const [scTasks, setScTasks] = useState({});
    const [importTasks, setImportTasks] = useState({});
    const [source, setSource] = useState('all'); // all | soundcloud | import
    const [filter, setFilter] = useState('all'); // all | active | completed | failed
    const [autoRefresh, setAutoRefresh] = useState(true);

    const fetchTasks = async () => {
        try {
            const [sc, imp] = await Promise.all([
                api.get('/api/soundcloud/tasks').catch(() => ({ data: {} })),
                api.get('/api/import/tasks').catch(() => ({ data: {} })),
            ]);
            setScTasks(sc.data || {});
            setImportTasks(imp.data || {});
        } catch (e) { /* backend offline */ }
    };

    useEffect(() => {
        fetchTasks();
        if (!autoRefresh) return;
        const i = setInterval(fetchTasks, 1500);
        return () => clearInterval(i);
    }, [autoRefresh]);

    const merged = useMemo(() => {
        const sc = Object.values(scTasks).map(t => ({ ...t, _src: 'soundcloud' }));
        const imp = Object.values(importTasks).map(t => ({ ...t, _src: 'import' }));
        let combined = [];
        if (source === 'all' || source === 'soundcloud') combined = combined.concat(sc);
        if (source === 'all' || source === 'import') combined = combined.concat(imp);
        return combined.sort((a, b) => (b.start_time || 0) - (a.start_time || 0));
    }, [scTasks, importTasks, source]);

    const allTasks = merged;

    const stats = useMemo(() => {
        const active = allTasks.filter(t =>
            !FAILURE_STATES.has(t.status) && t.status !== 'Completed' && !SKIP_STATES.has(t.status)
        );
        const done = allTasks.filter(t => t.status === 'Completed' || SKIP_STATES.has(t.status));
        const failed = allTasks.filter(t => FAILURE_STATES.has(t.status));
        const totalSec = done.reduce((acc, t) => {
            const last = (t.stage_history || []).slice(-1)[0]?.ts;
            return acc + ((last && t.start_time) ? (last - t.start_time) : 0);
        }, 0);
        return {
            total: allTasks.length,
            active: active.length,
            done: done.length,
            failed: failed.length,
            avgDoneSec: done.length ? Math.round(totalSec / done.length) : 0,
        };
    }, [allTasks]);

    const visible = useMemo(() => {
        switch (filter) {
            case 'active':    return allTasks.filter(t =>
                !FAILURE_STATES.has(t.status) && t.status !== 'Completed' && !SKIP_STATES.has(t.status));
            case 'completed': return allTasks.filter(t => t.status === 'Completed' || SKIP_STATES.has(t.status));
            case 'failed':    return allTasks.filter(t => FAILURE_STATES.has(t.status));
            default:          return allTasks;
        }
    }, [allTasks, filter]);

    return (
        <div className="h-full flex flex-col bg-transparent text-white overflow-hidden">
            {/* Header */}
            <div className="px-6 pt-6 pb-3 border-b border-white/5">
                <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-3">
                        <div className="p-2.5 rounded-xl bg-orange-500/15">
                            <Download size={22} className="text-orange-400" />
                        </div>
                        <div>
                            <h1 className="text-2xl font-bold tracking-tight">Import Manager</h1>
                            <p className="text-xs text-ink-muted mt-0.5 font-mono">SoundCloud · Lokal → Analyse → Library → ANLZ</p>
                        </div>
                    </div>
                    <div className="flex items-center gap-2">
                        <button
                            onClick={() => setAutoRefresh(v => !v)}
                            className={`px-3 py-1.5 rounded-lg text-xs font-bold border transition-all ${
                                autoRefresh
                                    ? 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30'
                                    : 'bg-mx-card border-white/10 text-ink-muted hover:bg-white/5'
                            }`}
                        >
                            <Loader2 size={11} className={autoRefresh ? 'inline animate-spin mr-1' : 'inline mr-1'} />
                            {autoRefresh ? 'Live' : 'Pausiert'}
                        </button>
                        <button
                            onClick={fetchTasks}
                            className="px-3 py-1.5 rounded-lg text-xs font-bold bg-mx-card border border-white/10 hover:bg-white/5"
                        >
                            <Activity size={11} className="inline mr-1" /> Refresh
                        </button>
                    </div>
                </div>

                {/* Stats */}
                <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
                    <StatCard icon={BarChart3}     label="Gesamt"   value={stats.total}  color="text-amber2" />
                    <StatCard icon={Loader2}       label="Aktiv"    value={stats.active} color="text-orange-400" />
                    <StatCard icon={CheckCircle}   label="Fertig"   value={stats.done}   color="text-emerald-400" />
                    <StatCard icon={AlertTriangle} label="Fehler"   value={stats.failed} color="text-red-400" />
                    <StatCard icon={TrendingUp}    label="Ø Dauer"  value={`${stats.avgDoneSec}s`} color="text-purple-400" />
                </div>

                {/* Source + Filter pills */}
                <div className="flex flex-wrap items-center gap-2 mt-4">
                    <span className="text-[10px] uppercase tracking-wider text-ink-muted mr-1">Quelle</span>
                    {[
                        { id: 'all',        label: 'Alle' },
                        { id: 'soundcloud', label: 'SoundCloud' },
                        { id: 'import',     label: 'Lokal' },
                    ].map(s => (
                        <button
                            key={s.id}
                            onClick={() => setSource(s.id)}
                            className={`px-3 py-1 rounded-full text-[11px] font-bold transition-all border ${
                                source === s.id
                                    ? 'bg-cyan-500/20 text-cyan-300 border-cyan-500/40'
                                    : 'bg-mx-card border-white/10 text-ink-secondary hover:bg-white/5'
                            }`}
                        >
                            {s.label}
                        </button>
                    ))}
                    <Filter size={12} className="text-ink-muted ml-3" />
                    {[
                        { id: 'all',       label: 'Alle' },
                        { id: 'active',    label: 'Aktiv' },
                        { id: 'completed', label: 'Fertig' },
                        { id: 'failed',    label: 'Fehler' },
                    ].map(f => (
                        <button
                            key={f.id}
                            onClick={() => setFilter(f.id)}
                            className={`px-3 py-1 rounded-full text-[11px] font-bold transition-all border ${
                                filter === f.id
                                    ? 'bg-amber2/20 text-amber2 border-amber2/40'
                                    : 'bg-mx-card border-white/10 text-ink-secondary hover:bg-white/5'
                            }`}
                        >
                            {f.label}
                        </button>
                    ))}
                </div>
            </div>

            {/* Task list */}
            <div className="flex-1 overflow-y-auto p-6 space-y-3">
                {visible.length === 0 ? (
                    <div className="flex flex-col items-center justify-center h-full text-center">
                        <Sparkles size={40} className="text-ink-placeholder mb-3" />
                        <h3 className="text-lg font-bold text-ink-secondary">Keine {filter === 'all' ? '' : filter + ' '}Downloads</h3>
                        <p className="text-sm text-ink-muted mt-1 max-w-md">
                            Starte einen Download in der SoundCloud-Ansicht — er taucht hier mit Live-Pipeline-Tracking auf.
                        </p>
                    </div>
                ) : (
                    visible.map(t => <TaskCard key={t.id || t.sc_track_id} task={t} />)
                )}
            </div>
        </div>
    );
};

export default DownloadManagerView;
