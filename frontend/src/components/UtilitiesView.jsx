/**
 * UtilitiesView — Library-Verwaltungs-Tools
 *
 * Zwei Sub-Tabs:
 *   • Tools         — Phrase Cues, Duplicate Finder, XML Cleaner, Format Converter
 *   • Library Health — Low Quality / Lost / No Artwork (vorher in Insights)
 *
 * "Insights" ist jetzt für DJ-Analytics reserviert (Genre-Verteilung, BPM-Histogramm, etc.).
 */

import React, { useState, useEffect, useMemo, Suspense, lazy } from 'react';
import {
    Layers, Copy, FileCode, RefreshCw, ArrowLeft, Loader2, Wrench,
    Activity, TrendingDown, PlayCircle, ImageOff, Search, AlertCircle, Music
} from 'lucide-react';
import api from '../api/api';
import TrackTable from './TrackTable';

const PhraseGeneratorView = lazy(() => import('./PhraseGeneratorView'));
const DuplicateView       = lazy(() => import('./DuplicateView'));
const XmlCleanView        = lazy(() => import('./XmlCleanView'));

const TOOLS = [
    { id: 'phrase',     icon: Layers,    title: 'Phrase Cues Generator',   desc: 'Generate phrase markers and auto-cue points from beat analysis', color: 'text-amber2' },
    { id: 'duplicates', icon: Copy,      title: 'Duplicate Finder',        desc: 'Find acoustic duplicates using fingerprint analysis',           color: 'text-teal-400' },
    { id: 'xml',        icon: FileCode,  title: 'XML Cleaner',             desc: 'Validate and clean Rekordbox XML exports',                      color: 'text-blue-400' },
    { id: 'converter',  icon: RefreshCw, title: 'Mass Format Converter',   desc: 'Batch convert audio files between formats',                     color: 'text-orange-400' },
];

const HEALTH_TABS = [
    { id: 'low_quality', label: 'Low Quality', icon: TrendingDown, color: 'text-amber-400',   tip: 'Replace these with high-quality AIFF or FLAC for better sound system performance.' },
    { id: 'lost',        label: 'Lost Tracks', icon: PlayCircle,   color: 'text-rose-400',    tip: 'Tracks that haven\'t been played yet — move to a "New Music" playlist for review.' },
    { id: 'no_artwork',  label: 'No Cover',    icon: ImageOff,     color: 'text-ink-secondary', tip: 'Tracks missing artwork — useful to fix before exporting to USB.' },
];

const UtilitiesView = ({ onSelectTrack, onEditTrack, onPlayTrack, libraryStatus }) => {
    const [section, setSection]       = useState('tools');     // 'tools' | 'health'
    const [activeTool, setActiveTool] = useState(null);

    // ── Library Health state ─────────────────────────────────────────────────────
    const [healthTab, setHealthTab] = useState('low_quality');
    const [tracks, setTracks]       = useState([]);
    const [loading, setLoading]     = useState(false);
    const [searchTerm, setSearchTerm] = useState('');

    useEffect(() => {
        if (section !== 'health' || !libraryStatus?.loaded) return;
        setLoading(true);
        const endpoint = `/api/insights/${healthTab}`;
        api.get(endpoint)
            .then(res => { setTracks(res.data || []); setLoading(false); })
            .catch(err => { console.error('[Utilities/Health] load failed', err); setLoading(false); });
    }, [section, healthTab, libraryStatus?.loaded]);

    const filteredTracks = useMemo(() => {
        if (!searchTerm) return tracks;
        const q = searchTerm.toLowerCase();
        return tracks.filter(t =>
            (t.Title  && t.Title.toLowerCase().includes(q)) ||
            (t.Artist && t.Artist.toLowerCase().includes(q))
        );
    }, [tracks, searchTerm]);

    // ── Tool drill-in ────────────────────────────────────────────────────────────
    if (activeTool) {
        return (
            <div className="h-full flex flex-col">
                <div className="px-6 py-3 border-b border-line-subtle flex items-center gap-3">
                    <button
                        onClick={() => setActiveTool(null)}
                        className="p-1.5 hover:bg-mx-hover rounded-mx-sm transition-colors text-ink-muted hover:text-ink-primary"
                    >
                        <ArrowLeft size={16} />
                    </button>
                    <span className="text-[13px] font-medium text-ink-primary">
                        {TOOLS.find(t => t.id === activeTool)?.title}
                    </span>
                </div>
                <div className="flex-1 overflow-hidden">
                    <Suspense fallback={<div className="flex items-center justify-center h-full"><Loader2 className="animate-spin text-amber2" size={24} /></div>}>
                        {activeTool === 'phrase'     && <PhraseGeneratorView />}
                        {activeTool === 'duplicates' && <DuplicateView />}
                        {activeTool === 'xml'        && <XmlCleanView />}
                        {activeTool === 'converter'  && <ConverterPlaceholder />}
                    </Suspense>
                </div>
            </div>
        );
    }

    // ── Hub ──────────────────────────────────────────────────────────────────────
    const currentHealth = HEALTH_TABS.find(h => h.id === healthTab);

    return (
        <div className="h-full flex flex-col bg-mx-deepest animate-fade-in">
            {/* Header */}
            <div className="px-6 py-4 border-b border-line-subtle flex items-center justify-between">
                <div className="flex items-center gap-3">
                    <div className="p-2.5 bg-amber2/10 rounded-mx-md border border-amber2-dim">
                        <Wrench size={20} className="text-amber2" />
                    </div>
                    <div>
                        <h1 className="text-[20px] font-semibold tracking-tight">Utilities</h1>
                        <p className="text-tiny text-ink-muted">Manage and clean your library</p>
                    </div>
                </div>
                <div className="flex bg-mx-input p-1 rounded-mx-sm border border-line-subtle">
                    <SectionTab active={section === 'tools'}  onClick={() => setSection('tools')}  icon={<Wrench   size={13} />} label="Tools" />
                    <SectionTab active={section === 'health'} onClick={() => setSection('health')} icon={<Activity size={13} />} label="Library Health" />
                </div>
            </div>

            {/* Body */}
            <div className="flex-1 overflow-hidden">
                {section === 'tools' ? (
                    <div className="overflow-y-auto h-full p-6">
                        <div className="grid grid-cols-2 gap-4 max-w-3xl">
                            {TOOLS.map(tool => {
                                const Icon = tool.icon;
                                const disabled = tool.id === 'converter';
                                return (
                                    <button
                                        key={tool.id}
                                        onClick={() => !disabled && setActiveTool(tool.id)}
                                        className={`mx-card p-5 text-left transition-all hover:border-amber2/40 hover:bg-mx-hover group ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
                                    >
                                        <div className="flex items-start gap-3">
                                            <div className="p-2 bg-mx-input rounded-mx-sm border border-line-subtle group-hover:border-line-default">
                                                <Icon size={18} className={tool.color} />
                                            </div>
                                            <div className="flex-1 min-w-0">
                                                <div className="text-[13px] font-semibold text-ink-primary mb-1">{tool.title}</div>
                                                <div className="text-[11px] text-ink-muted leading-relaxed">{tool.desc}</div>
                                                {disabled && (
                                                    <span className="inline-block mt-2 text-[9px] font-semibold uppercase tracking-wider text-amber2 bg-amber2/10 px-2 py-0.5 rounded-mx-xs border border-amber2/20">
                                                        Coming Soon
                                                    </span>
                                                )}
                                            </div>
                                        </div>
                                    </button>
                                );
                            })}
                        </div>
                    </div>
                ) : (
                    <div className="h-full flex flex-col p-6">
                        {/* Health header — sub-tabs + search */}
                        <div className="flex items-center justify-between mb-4">
                            <div className="flex bg-mx-input p-1 rounded-mx-sm border border-line-subtle">
                                {HEALTH_TABS.map(t => (
                                    <button
                                        key={t.id}
                                        onClick={() => setHealthTab(t.id)}
                                        className={`px-3 py-1.5 rounded-mx-xs text-[11px] font-semibold flex items-center gap-1.5 transition-all ${
                                            healthTab === t.id
                                                ? 'bg-amber2/15 text-amber2'
                                                : 'text-ink-muted hover:text-ink-secondary'
                                        }`}
                                    >
                                        <t.icon size={12} className={healthTab === t.id ? 'text-amber2' : t.color} />
                                        {t.label}
                                    </button>
                                ))}
                            </div>
                            <div className="relative w-64">
                                <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" />
                                <input
                                    className="input-glass w-full pl-9 text-tiny"
                                    placeholder="Search results..."
                                    value={searchTerm}
                                    onChange={e => setSearchTerm(e.target.value)}
                                />
                            </div>
                        </div>

                        {/* Summary bar */}
                        <div className="mx-card px-4 py-2 mb-3 flex items-center justify-between">
                            <div className="flex items-center gap-2">
                                <currentHealth.icon size={14} className={currentHealth.color} />
                                <span className="text-[11px] font-semibold text-ink-primary">{currentHealth.label}</span>
                            </div>
                            <span className="font-mono text-tiny text-amber2">{tracks.length} tracks</span>
                        </div>

                        {/* Track list */}
                        <div className="flex-1 mx-card overflow-hidden">
                            {loading ? (
                                <div className="h-full flex items-center justify-center">
                                    <Loader2 className="animate-spin text-amber2" size={24} />
                                </div>
                            ) : tracks.length === 0 ? (
                                <div className="h-full flex flex-col items-center justify-center text-ink-muted">
                                    <Music size={48} className="mb-3 opacity-20" />
                                    <p className="text-[12px] font-medium text-ink-secondary">All clean!</p>
                                    <p className="text-tiny text-ink-placeholder mt-1">No tracks match this filter.</p>
                                </div>
                            ) : (
                                <div className="h-full overflow-y-auto p-2">
                                    <TrackTable
                                        tracks={filteredTracks}
                                        onSelectTrack={onSelectTrack}
                                        onEditTrack={onEditTrack}
                                        onPlay={onPlayTrack}
                                        playlistId={`UTIL_HEALTH_${healthTab.toUpperCase()}`}
                                        variant="minimal"
                                    />
                                </div>
                            )}
                        </div>

                        {/* Tip */}
                        <div className="mt-3 px-3 py-2 bg-amber2/5 border border-amber2/15 rounded-mx-sm flex items-center gap-2">
                            <AlertCircle size={13} className="text-amber2 shrink-0" />
                            <p className="text-tiny text-ink-secondary leading-relaxed">{currentHealth.tip}</p>
                        </div>
                    </div>
                )}
            </div>
        </div>
    );
};

const SectionTab = ({ active, onClick, icon, label }) => (
    <button
        onClick={onClick}
        className={`px-3 py-1.5 rounded-mx-xs text-[11px] font-semibold flex items-center gap-1.5 transition-all ${
            active ? 'bg-amber2/15 text-amber2' : 'text-ink-muted hover:text-ink-secondary'
        }`}
    >
        {icon}
        {label}
    </button>
);

const ConverterPlaceholder = () => (
    <div className="flex items-center justify-center h-full text-ink-muted">
        <div className="text-center">
            <RefreshCw size={40} className="mx-auto mb-3 text-ink-placeholder" />
            <p className="text-[13px] font-medium">Mass Format Converter</p>
            <p className="text-tiny text-ink-muted mt-1">Coming in a future update</p>
        </div>
    </div>
);

export default UtilitiesView;
