/**
 * InsightsView — DJ-Style Analytics Dashboard
 *
 * Datenbasierte Einblicke in den eigenen DJ-Stil und die Library:
 *  • BPM-Verteilung (Histogramm)
 *  • Key-Verteilung (Camelot Wheel)
 *  • Genre-Stats (Top-Genres + Anteile)
 *  • Most Played Tracks
 *  • Library Composition (Energy, Format, Era)
 *
 * Library-Health (low-quality / lost / no-artwork) wurde zu "Utilities → Library Health"
 * verschoben — das ist Verwaltung, nicht Analytics.
 *
 * Backend-Endpoints (zum Teil noch zu implementieren):
 *  GET /api/insights/bpm_distribution
 *  GET /api/insights/key_distribution
 *  GET /api/insights/genre_stats
 *  GET /api/insights/top_played
 *  GET /api/insights/composition
 */

import React, { useState, useEffect, useMemo } from 'react';
import api from '../api/api';
import {
    BarChart3, Music, Disc, Activity, Flame, Loader2, AlertCircle,
    TrendingUp, Hash, Calendar, Volume2
} from 'lucide-react';

const InsightsView = ({ libraryStatus }) => {
    const [stats, setStats]     = useState(null);
    const [loading, setLoading] = useState(false);
    const [error, setError]     = useState(null);

    useEffect(() => {
        if (!libraryStatus?.loaded) return;
        setLoading(true);
        setError(null);
        // Aggregierter Endpoint — fällt auf Library-Daten zurück wenn nicht implementiert
        api.get('/api/insights/dj_stats')
            .then(res => { setStats(res.data); setLoading(false); })
            .catch(err => {
                console.warn('[Insights] dj_stats endpoint not available, using library fallback', err);
                // Fallback: aus Library-Daten ableiten
                api.get('/api/library/tracks')
                    .then(r => {
                        setStats(deriveStatsFromTracks(r.data || []));
                        setLoading(false);
                    })
                    .catch(e => {
                        setError(e.message);
                        setLoading(false);
                    });
            });
    }, [libraryStatus?.loaded]);

    if (!libraryStatus?.loaded) {
        return (
            <div className="h-full flex items-center justify-center text-ink-muted">
                <div className="text-center">
                    <BarChart3 size={48} className="mx-auto mb-3 opacity-30" />
                    <p className="text-[13px] font-medium">Load a library to see insights</p>
                </div>
            </div>
        );
    }

    if (loading) {
        return (
            <div className="h-full flex items-center justify-center">
                <Loader2 className="animate-spin text-amber2" size={28} />
            </div>
        );
    }

    if (error || !stats) {
        return (
            <div className="h-full flex items-center justify-center text-ink-muted">
                <div className="text-center max-w-sm">
                    <AlertCircle size={36} className="mx-auto mb-3 text-amber2" />
                    <p className="text-[13px] font-medium text-ink-secondary">Could not load insights</p>
                    <p className="text-tiny text-ink-placeholder mt-1">{error || 'No data available'}</p>
                </div>
            </div>
        );
    }

    return (
        <div className="h-full flex flex-col bg-mx-deepest animate-fade-in">
            {/* Header */}
            <div className="px-6 py-4 border-b border-line-subtle">
                <div className="flex items-center gap-3">
                    <div className="p-2.5 bg-amber2/10 rounded-mx-md border border-amber2-dim">
                        <BarChart3 size={20} className="text-amber2" />
                    </div>
                    <div>
                        <h1 className="text-[20px] font-semibold tracking-tight">Insights</h1>
                        <p className="text-tiny text-ink-muted">Your DJ style and library composition</p>
                    </div>
                </div>
            </div>

            {/* Body */}
            <div className="flex-1 overflow-y-auto p-6 space-y-4">
                {/* KPI Strip */}
                <div className="grid grid-cols-4 gap-3">
                    <KpiCard icon={Music}     label="Total Tracks"  value={stats.totalTracks}  color="amber2" />
                    <KpiCard icon={TrendingUp} label="Avg BPM"      value={stats.avgBpm}        color="amber2" />
                    <KpiCard icon={Hash}      label="Unique Keys"   value={stats.uniqueKeys}    color="teal-400" />
                    <KpiCard icon={Disc}      label="Top Genre"     value={stats.topGenre}      color="rose-400" small />
                </div>

                {/* BPM Histogram */}
                <Panel title="BPM Distribution" icon={Activity}>
                    <BarHistogram data={stats.bpmHistogram} unit="BPM" color="rgba(232,164,42,0.7)" />
                </Panel>

                {/* Key Distribution */}
                <Panel title="Key Distribution (Camelot)" icon={Hash}>
                    <KeyGrid keys={stats.keyDistribution} />
                </Panel>

                {/* Genre Stats */}
                <Panel title="Top Genres" icon={Disc}>
                    <GenreList genres={stats.genreStats} />
                </Panel>

                {/* Most Played */}
                {stats.topPlayed && stats.topPlayed.length > 0 && (
                    <Panel title="Most Played" icon={Flame}>
                        <TopPlayedList tracks={stats.topPlayed} />
                    </Panel>
                )}
            </div>
        </div>
    );
};

// ─── DERIVED STATS (Fallback) ──────────────────────────────────────────────────

function deriveStatsFromTracks(tracks) {
    const totalTracks = tracks.length;
    const bpms        = tracks.map(t => parseFloat(t.AverageBpm || t.BPM || 0)).filter(b => b > 0);
    const avgBpm      = bpms.length ? Math.round(bpms.reduce((s, b) => s + b, 0) / bpms.length) : 0;

    // Genre stats
    const genreCounts = {};
    for (const t of tracks) {
        const g = (t.Genre || 'Unknown').trim() || 'Unknown';
        genreCounts[g] = (genreCounts[g] || 0) + 1;
    }
    const genreStats = Object.entries(genreCounts)
        .sort(([, a], [, b]) => b - a)
        .slice(0, 10)
        .map(([name, count]) => ({ name, count, pct: Math.round((count / totalTracks) * 100) }));

    // Key stats
    const keyCounts = {};
    for (const t of tracks) {
        const k = (t.Tonality || t.Key || '').trim();
        if (k) keyCounts[k] = (keyCounts[k] || 0) + 1;
    }
    const uniqueKeys = Object.keys(keyCounts).length;
    const keyDistribution = Object.entries(keyCounts).map(([key, count]) => ({ key, count }));

    // BPM histogram (5 BPM bins, 60-200)
    const bins = {};
    for (const b of bpms) {
        const bin = Math.floor(b / 5) * 5;
        bins[bin] = (bins[bin] || 0) + 1;
    }
    const bpmHistogram = Object.entries(bins)
        .map(([bin, count]) => ({ label: `${bin}`, value: count }))
        .sort((a, b) => parseInt(a.label) - parseInt(b.label));

    // Top played
    const topPlayed = [...tracks]
        .filter(t => parseInt(t.PlayCount || 0) > 0)
        .sort((a, b) => parseInt(b.PlayCount || 0) - parseInt(a.PlayCount || 0))
        .slice(0, 10)
        .map(t => ({
            title:  t.Title  || 'Untitled',
            artist: t.Artist || 'Unknown',
            plays:  parseInt(t.PlayCount || 0),
            bpm:    parseFloat(t.AverageBpm || t.BPM || 0),
            key:    t.Tonality || t.Key || '',
        }));

    return {
        totalTracks,
        avgBpm,
        uniqueKeys,
        topGenre: genreStats[0]?.name || '—',
        bpmHistogram,
        keyDistribution,
        genreStats,
        topPlayed,
    };
}

// ─── COMPONENTS ────────────────────────────────────────────────────────────────

const KpiCard = ({ icon: Icon, label, value, color, small }) => (
    <div className="mx-card p-3">
        <div className="flex items-center gap-2 mb-1">
            <Icon size={12} className={`text-${color}`} />
            <span className="text-[9px] font-bold text-ink-muted uppercase tracking-widest">{label}</span>
        </div>
        <div className={`font-mono font-bold text-ink-primary ${small ? 'text-[14px]' : 'text-[22px]'} truncate`}>
            {value || '—'}
        </div>
    </div>
);

const Panel = ({ title, icon: Icon, children }) => (
    <div className="mx-card p-4">
        <div className="flex items-center gap-2 mb-3">
            <Icon size={13} className="text-amber2" />
            <span className="text-[11px] font-bold text-ink-muted uppercase tracking-widest">{title}</span>
        </div>
        {children}
    </div>
);

const BarHistogram = ({ data, unit, color }) => {
    if (!data || data.length === 0) return <Empty />;
    const max = Math.max(...data.map(d => d.value));
    return (
        <div className="flex items-end gap-1 h-32">
            {data.map(d => (
                <div key={d.label} className="flex-1 flex flex-col items-center justify-end gap-1 group">
                    <div
                        className="w-full rounded-t-sm transition-all group-hover:brightness-125"
                        style={{
                            height:     `${(d.value / max) * 100}%`,
                            background: color,
                            minHeight:  d.value > 0 ? '2px' : '0',
                        }}
                        title={`${d.label} ${unit}: ${d.value} tracks`}
                    />
                    <span className="text-[9px] font-mono text-ink-muted">{d.label}</span>
                </div>
            ))}
        </div>
    );
};

const KeyGrid = ({ keys }) => {
    if (!keys || keys.length === 0) return <Empty />;
    const max = Math.max(...keys.map(k => k.count));
    return (
        <div className="grid grid-cols-6 gap-2">
            {keys.slice(0, 24).map(k => (
                <div
                    key={k.key}
                    className="px-2 py-1.5 rounded-mx-sm border border-line-subtle bg-mx-input flex items-center justify-between"
                    style={{
                        background: `linear-gradient(90deg, rgba(232,164,42,${0.08 + 0.32 * (k.count / max)}) 0%, transparent 100%)`,
                    }}
                >
                    <span className="text-[11px] font-mono text-ink-primary">{k.key}</span>
                    <span className="text-[10px] font-mono text-ink-muted">{k.count}</span>
                </div>
            ))}
        </div>
    );
};

const GenreList = ({ genres }) => {
    if (!genres || genres.length === 0) return <Empty />;
    return (
        <div className="space-y-1.5">
            {genres.map(g => (
                <div key={g.name} className="flex items-center gap-2">
                    <div className="w-32 truncate text-[11px] text-ink-primary font-medium">{g.name}</div>
                    <div className="flex-1 h-2 bg-mx-input rounded-full overflow-hidden">
                        <div
                            className="h-full bg-amber2/70 rounded-full"
                            style={{ width: `${g.pct}%` }}
                        />
                    </div>
                    <div className="w-20 text-right">
                        <span className="text-[10px] font-mono text-ink-secondary">{g.count}</span>
                        <span className="text-[9px] font-mono text-ink-muted ml-1">({g.pct}%)</span>
                    </div>
                </div>
            ))}
        </div>
    );
};

const TopPlayedList = ({ tracks }) => (
    <div className="space-y-1">
        {tracks.map((t, i) => (
            <div key={i} className="flex items-center gap-2 px-2 py-1.5 rounded-mx-sm hover:bg-mx-hover transition-colors">
                <span className="w-6 text-[10px] font-mono text-ink-muted text-right">#{i + 1}</span>
                <div className="flex-1 min-w-0">
                    <div className="text-[11px] font-medium text-ink-primary truncate">{t.title}</div>
                    <div className="text-[10px] text-ink-muted truncate">{t.artist}</div>
                </div>
                {t.bpm > 0 && <span className="text-[10px] font-mono text-ink-secondary">{Math.round(t.bpm)} BPM</span>}
                {t.key && <span className="text-[10px] font-mono text-amber2 px-1.5 py-0.5 bg-amber2/10 rounded">{t.key}</span>}
                <span className="flex items-center gap-1 text-[10px] font-mono text-ink-secondary w-12 justify-end">
                    <Volume2 size={10} /> {t.plays}
                </span>
            </div>
        ))}
    </div>
);

const Empty = () => (
    <div className="text-center py-6 text-ink-placeholder text-tiny">No data available</div>
);

export default InsightsView;
