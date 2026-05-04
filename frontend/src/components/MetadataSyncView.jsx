import React, { useState } from 'react';
import { ArrowRightLeft, Monitor, Usb, Zap, Loader2 } from 'lucide-react';

const METADATA_CATEGORIES = [
    { id: 'play_counts', label: 'Play Counts', desc: 'Track play count and last played date' },
    { id: 'ratings', label: 'Ratings', desc: 'Star ratings (0-5)' },
    { id: 'tags', label: 'Tags & Comments', desc: 'Comment field and custom tags' },
    { id: 'color', label: 'Color Labels', desc: 'Track color assignments' },
    { id: 'hot_cues', label: 'Hot Cues', desc: 'Hot cue points (A-H)' },
    { id: 'memory_cues', label: 'Memory Cues', desc: 'Memory cue and loop points' },
    { id: 'beat_grids', label: 'Beat Grids', desc: 'Beat grid and BPM data' },
];

const MetadataSyncView = () => {
    const [syncMode, setSyncMode] = useState('smart');
    const [mainSource, setMainSource] = useState('pc');
    const [categories, setCategories] = useState(
        METADATA_CATEGORIES.reduce((acc, c) => ({ ...acc, [c.id]: true }), {})
    );

    const toggleCategory = (id) => {
        setCategories(prev => ({ ...prev, [id]: !prev[id] }));
    };

    return (
        <div className="h-full flex flex-col bg-mx-deepest animate-fade-in">
            <div className="px-6 py-4 border-b border-line-subtle">
                <div className="flex items-center gap-3">
                    <div className="p-2.5 bg-amber2/10 rounded-mx-md border border-amber2-dim">
                        <ArrowRightLeft size={20} className="text-amber2" />
                    </div>
                    <div>
                        <h1 className="text-[20px] font-semibold tracking-tight">Metadata Sync</h1>
                        <p className="text-tiny text-ink-muted">Synchronize metadata between PC library and USB devices</p>
                    </div>
                </div>
            </div>

            <div className="flex-1 overflow-y-auto p-6">
                <div className="max-w-2xl space-y-5">
                    {/* Sync Mode */}
                    <div className="mx-card p-4">
                        <div className="mx-caption mb-3">Sync Mode</div>
                        <div className="grid grid-cols-2 gap-2">
                            <button
                                onClick={() => setSyncMode('smart')}
                                className={`flex items-center gap-2.5 p-3 rounded-mx-sm border transition-all text-left ${
                                    syncMode === 'smart'
                                        ? 'bg-amber2/10 border-amber2/50 text-amber2'
                                        : 'bg-mx-input border-line-subtle text-ink-secondary hover:bg-mx-hover'
                                }`}
                            >
                                <Zap size={16} />
                                <div>
                                    <div className="text-[12px] font-semibold">Smart Mode</div>
                                    <div className="text-[10px] text-ink-muted">Auto-detect newest data</div>
                                </div>
                            </button>
                            <button
                                onClick={() => setSyncMode('manual')}
                                className={`flex items-center gap-2.5 p-3 rounded-mx-sm border transition-all text-left ${
                                    syncMode === 'manual'
                                        ? 'bg-amber2/10 border-amber2/50 text-amber2'
                                        : 'bg-mx-input border-line-subtle text-ink-secondary hover:bg-mx-hover'
                                }`}
                            >
                                <ArrowRightLeft size={16} />
                                <div>
                                    <div className="text-[12px] font-semibold">Manual</div>
                                    <div className="text-[10px] text-ink-muted">You pick the main source</div>
                                </div>
                            </button>
                        </div>

                        {syncMode === 'smart' && (
                            <div className="mt-3 p-2.5 bg-mx-input rounded-mx-sm border border-line-subtle text-[11px] text-ink-muted">
                                Smart mode compares timestamps and takes the most recent value for each field. Conflicts are resolved by taking the higher/newer value.
                            </div>
                        )}
                    </div>

                    {/* Main Source (Manual mode) */}
                    {syncMode === 'manual' && (
                        <div className="mx-card p-4">
                            <div className="mx-caption mb-3">Main Source</div>
                            <div className="grid grid-cols-2 gap-2">
                                <button
                                    onClick={() => setMainSource('pc')}
                                    className={`flex items-center gap-2.5 p-3 rounded-mx-sm border transition-all ${
                                        mainSource === 'pc'
                                            ? 'bg-amber2/10 border-amber2/50 text-amber2'
                                            : 'bg-mx-input border-line-subtle text-ink-secondary hover:bg-mx-hover'
                                    }`}
                                >
                                    <Monitor size={16} />
                                    <div className="text-[12px] font-semibold">PC is Main</div>
                                </button>
                                <button
                                    onClick={() => setMainSource('usb')}
                                    className={`flex items-center gap-2.5 p-3 rounded-mx-sm border transition-all ${
                                        mainSource === 'usb'
                                            ? 'bg-amber2/10 border-amber2/50 text-amber2'
                                            : 'bg-mx-input border-line-subtle text-ink-secondary hover:bg-mx-hover'
                                    }`}
                                >
                                    <Usb size={16} />
                                    <div className="text-[12px] font-semibold">USB is Main</div>
                                </button>
                            </div>
                            <p className="text-[10px] text-ink-muted mt-2">
                                {mainSource === 'pc'
                                    ? 'PC data will overwrite USB data for selected categories.'
                                    : 'USB data will overwrite PC data for selected categories.'}
                            </p>
                        </div>
                    )}

                    {/* Categories */}
                    <div className="mx-card p-4">
                        <div className="mx-caption mb-3">Metadata to Sync</div>
                        <div className="space-y-0.5">
                            {METADATA_CATEGORIES.map(cat => (
                                <label
                                    key={cat.id}
                                    className="flex items-center justify-between p-2.5 rounded-mx-sm hover:bg-mx-hover cursor-pointer transition-all"
                                >
                                    <div className="flex flex-col">
                                        <span className="text-[12px] text-ink-primary font-medium">{cat.label}</span>
                                        <span className="text-[10px] text-ink-muted">{cat.desc}</span>
                                    </div>
                                    <input
                                        type="checkbox"
                                        checked={categories[cat.id]}
                                        onChange={() => toggleCategory(cat.id)}
                                        className="accent-amber2 w-4 h-4"
                                    />
                                </label>
                            ))}
                        </div>
                    </div>

                    {/* Action */}
                    <div className="flex items-center gap-3">
                        <button
                            disabled
                            className="btn-primary flex items-center gap-2 opacity-50 cursor-not-allowed"
                        >
                            <ArrowRightLeft size={14} /> Start Metadata Sync
                        </button>
                        <span className="text-[10px] text-ink-muted">Select a USB device in USB Export first</span>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default MetadataSyncView;
