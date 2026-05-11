/**
 * MetadataSyncPanel — collapsible per-device metadata sync controls.
 *
 * UI-only for now (no backend wired). Lets the user pick a sync mode
 * (smart vs. manual), the main source (PC vs. USB) when manual, and
 * which categories of metadata to push.
 */
import React, { useState } from 'react';
import {
    ChevronDown, ChevronRight, ArrowUpDown, Zap, Database, Usb,
} from 'lucide-react';

const METADATA_CATEGORIES = [
    { id: 'play_counts', label: 'Play Counts', desc: 'Play count and last played date' },
    { id: 'ratings', label: 'Ratings', desc: 'Star ratings (0-5)' },
    { id: 'tags', label: 'Tags & Comments', desc: 'Comment field and custom tags' },
    { id: 'color', label: 'Color Labels', desc: 'Track color assignments' },
    { id: 'hot_cues', label: 'Hot Cues', desc: 'Hot cue points (A-H)' },
    { id: 'memory_cues', label: 'Memory Cues', desc: 'Memory cue and loop points' },
    { id: 'beat_grids', label: 'Beat Grids', desc: 'Beat grid and BPM data' },
];

const MetadataSyncPanel = ({ device }) => {
    const [open, setOpen] = useState(false);
    const [syncMode, setSyncMode] = useState('smart');
    const [mainSource, setMainSource] = useState('pc');
    const [categories, setCategories] = useState(
        METADATA_CATEGORIES.reduce((acc, c) => ({ ...acc, [c.id]: true }), {})
    );

    const toggleCategory = (id) => {
        setCategories(prev => ({ ...prev, [id]: !prev[id] }));
    };

    return (
        <div className="mx-card rounded-mx-md">
            <button
                className="w-full flex items-center justify-between px-4 py-3 hover:bg-mx-hover rounded-mx-md transition-colors"
                onClick={() => setOpen(o => !o)}
            >
                <div className="flex items-center gap-2">
                    <ArrowUpDown size={14} className="text-teal-400" />
                    <span className="text-[12px] font-semibold text-ink-primary">Metadata Sync</span>
                </div>
                {open ? <ChevronDown size={14} className="text-ink-muted" /> : <ChevronRight size={14} className="text-ink-muted" />}
            </button>

            {open && (
                <div className="px-4 pb-4 border-t border-line-subtle pt-3 space-y-3">
                    {/* Sync Mode */}
                    <div className="grid grid-cols-2 gap-2">
                        <button
                            onClick={() => setSyncMode('smart')}
                            className={`flex items-center gap-2 p-2.5 rounded-mx-sm border transition-all text-left ${
                                syncMode === 'smart'
                                    ? 'bg-amber2/10 border-amber2/50 text-amber2'
                                    : 'bg-mx-input border-line-subtle text-ink-secondary hover:bg-mx-hover'
                            }`}
                        >
                            <Zap size={13} />
                            <div>
                                <div className="text-[11px] font-semibold">Smart</div>
                                <div className="text-[9px] text-ink-muted">Auto-detect newest</div>
                            </div>
                        </button>
                        <button
                            onClick={() => setSyncMode('manual')}
                            className={`flex items-center gap-2 p-2.5 rounded-mx-sm border transition-all text-left ${
                                syncMode === 'manual'
                                    ? 'bg-amber2/10 border-amber2/50 text-amber2'
                                    : 'bg-mx-input border-line-subtle text-ink-secondary hover:bg-mx-hover'
                            }`}
                        >
                            <ArrowUpDown size={13} />
                            <div>
                                <div className="text-[11px] font-semibold">Manual</div>
                                <div className="text-[9px] text-ink-muted">Pick main source</div>
                            </div>
                        </button>
                    </div>

                    {/* Manual source picker */}
                    {syncMode === 'manual' && (
                        <div className="grid grid-cols-2 gap-2">
                            <button
                                onClick={() => setMainSource('pc')}
                                className={`flex items-center gap-2 p-2 rounded-mx-xs border transition-all text-[11px] font-medium ${
                                    mainSource === 'pc' ? 'bg-teal-400/10 border-teal-400/50 text-teal-400' : 'border-line-subtle text-ink-muted hover:bg-mx-hover'
                                }`}
                            >
                                <Database size={12} /> PC is Main
                            </button>
                            <button
                                onClick={() => setMainSource('usb')}
                                className={`flex items-center gap-2 p-2 rounded-mx-xs border transition-all text-[11px] font-medium ${
                                    mainSource === 'usb' ? 'bg-teal-400/10 border-teal-400/50 text-teal-400' : 'border-line-subtle text-ink-muted hover:bg-mx-hover'
                                }`}
                            >
                                <Usb size={12} /> USB is Main
                            </button>
                        </div>
                    )}

                    {/* Categories */}
                    <div className="space-y-0.5">
                        <div className="text-[10px] text-ink-muted uppercase tracking-wider font-semibold mb-1.5">Sync Categories</div>
                        {METADATA_CATEGORIES.map(cat => (
                            <label
                                key={cat.id}
                                className="flex items-center justify-between p-1.5 rounded-mx-xs hover:bg-mx-hover cursor-pointer transition-all"
                            >
                                <div className="flex flex-col">
                                    <span className="text-[11px] text-ink-primary">{cat.label}</span>
                                    <span className="text-[9px] text-ink-muted">{cat.desc}</span>
                                </div>
                                <input
                                    type="checkbox"
                                    checked={categories[cat.id]}
                                    onChange={() => toggleCategory(cat.id)}
                                    className="accent-amber2 w-3.5 h-3.5"
                                />
                            </label>
                        ))}
                    </div>

                    {/* Action */}
                    <button className="btn-primary text-[11px] py-1.5 px-3 flex items-center gap-1.5 w-full justify-center">
                        <ArrowUpDown size={11} /> Sync Metadata to {device?.label || 'USB'}
                    </button>
                </div>
            )}
        </div>
    );
};

export default MetadataSyncPanel;
