import React, { useState } from 'react';
import { Sparkles, Music, Zap, Layers, Grid3X3, Disc, Play, Activity, Settings, Search, List, ChevronRight, LayoutGrid, Type, Waves } from 'lucide-react';

const DesignView = () => {
    const [activeConcept, setActiveConcept] = useState('sonic');

    const concepts = {
        // --- PHASE 1: BRAND FOCUS ---
        sonic: { id: 'sonic', name: 'Sonic Pulse icons', description: 'Cyberpunk Neon. Glowing accents and fluid gradients.', color: 'from-blue-500 to-pink-500', accent: 'text-pink-500', bg: 'bg-mx-deepest', panel: 'bg-mx-shell/60 border-blue-500/20 shadow-[0_0_15px_rgba(59,130,246,0.1)]', btn: 'bg-gradient-to-r from-blue-600 to-pink-600 hover:from-blue-500 hover:to-pink-500', layout: 'standard' },
        golden: { id: 'golden', name: 'Golden Vinyl', description: 'Classic Premium. Luxury black and gold aesthetic.', color: 'from-amber-600 to-yellow-400', accent: 'text-amber-500', bg: 'bg-[#0a0a0a]', panel: 'bg-[#121212] border-amber-500/30 shadow-2xl', btn: 'bg-amber-600 hover:bg-amber-500 text-black font-bold uppercase tracking-wider', layout: 'standard' },
        spectral: { id: 'spectral', name: 'Spectral Prism', description: 'Technical Analytical. Clean data-heavy look.', color: 'from-slate-400 to-slate-200', accent: 'text-amber2', bg: 'bg-[#131b26]', panel: 'bg-[#1c2633] border-line-default', btn: 'bg-mx-hover hover:bg-slate-600 border border-slate-500 text-white', layout: 'standard' },
        liquid: { id: 'liquid', name: 'Liquid Sound', description: 'Glassmorphism Aqua. Translucent layers and heavy blur.', color: 'from-amber2 to-blue-400', accent: 'text-amber2-hover', bg: 'bg-mx-deepest', panel: 'bg-white/5 backdrop-blur-2xl border-white/10 shadow-xl', btn: 'bg-amber2/80 hover:bg-amber2 backdrop-blur-md border border-white/20', layout: 'standard' },
        monogram: { id: 'monogram', name: 'Monogram Box', description: 'Enterprise Pro. Structured grid-based layout.', color: 'from-emerald-500 to-teal-600', accent: 'text-emerald-400', bg: 'bg-[#020617]', panel: 'bg-[#0f172a] border-emerald-500/20', btn: 'bg-emerald-600 hover:bg-emerald-500 text-white rounded-none border-b-4 border-emerald-800', layout: 'standard' },

        // --- PHASE 2: LAYOUT FOCUS ---
        legacy: { id: 'legacy', name: 'Legacy Pro', description: 'Industry Standard. Dense layout following Rekordbox workflow.', color: 'from-slate-700 to-slate-500', accent: 'text-blue-400', bg: 'bg-[#000000]', panel: 'bg-[#121212] border-white/10', btn: 'bg-[#2a2a2a] border border-white/20 hover:bg-[#333] text-[10px] uppercase font-bold', layout: 'legacy' },
        modular: { id: 'modular', name: 'Modular Rack', description: 'Customizable Studio. Hardware-style racks.', color: 'from-orange-500 to-red-600', accent: 'text-orange-500', bg: 'bg-[#0f0f0f]', panel: 'bg-[#181818] border-l-4 border-l-orange-500 shadow-xl', btn: 'bg-orange-600 hover:bg-orange-500 text-white rounded-sm font-bold', layout: 'modular' },
        stream: { id: 'stream', name: 'Horizontal Stream', description: 'Cinematic Flow. Focus on full-width waveforms.', color: 'from-amber2 to-amber2-press', accent: 'text-amber2', bg: 'bg-mx-deepest', panel: 'bg-white/5 backdrop-blur-xl border-y border-white/5', btn: 'bg-transparent border border-amber2 text-amber2 hover:bg-amber2 hover:text-white', layout: 'stream' },
        focused: { id: 'focused', name: 'Focused Deck', description: 'Single Deck Focus. Spotlight-style layout.', color: 'from-indigo-500 to-violet-600', accent: 'text-indigo-400', bg: 'bg-black', panel: 'bg-indigo-950/10 border border-indigo-500/20 rounded-[50px]', btn: 'bg-indigo-600 hover:bg-indigo-500 rounded-full shadow-lg shadow-indigo-500/20', layout: 'focused' },
        discovery: { id: 'discovery', name: 'Discovery Graph', description: 'Non-linear Explorer. Futuristic node-based browsing.', color: 'from-fuchsia-500 to-pink-600', accent: 'text-fuchsia-400', bg: 'bg-[#050510]', panel: 'bg-white/5 border border-fuchsia-500/20 shadow-[0_0_20px_rgba(217,70,239,0.1)]', btn: 'bg-fuchsia-600 hover:bg-fuchsia-500 text-white', layout: 'discovery' },

        // --- PHASE 3: LIBRARY FOCUS (NEW) ---
        authentic: { id: 'authentic', name: 'Authentic Crate', description: 'The Real Deal. High-density table view with Rekordbox 7 precise styling.', color: 'from-zinc-400 to-zinc-600', accent: 'text-blue-500', bg: 'bg-[#1a1a1a]', panel: 'bg-[#111] border-zinc-800', btn: 'bg-[#222] border-zinc-700 text-zinc-300 hover:bg-[#333]', layout: 'lib_table' },
        canvas: { id: 'canvas', name: 'Visual Canvas', description: 'Artwork First. Grid-based library for visual-heavy collections.', color: 'from-rose-500 to-orange-500', accent: 'text-rose-400', bg: 'bg-[#0f0f0f]', panel: 'bg-transparent border-none', btn: 'bg-rose-600 hover:bg-rose-500 rounded-full', layout: 'lib_grid' },
        minimal: { id: 'minimal', name: 'Streamline List', description: 'Distraction Free. Modern, high-whitespace minimalist list.', color: 'from-slate-200 to-slate-400', accent: 'text-blue-600', bg: 'bg-white text-slate-900', panel: 'bg-slate-50 border-slate-200', btn: 'bg-mx-shell text-white hover:bg-mx-card rounded-lg', layout: 'lib_minimal' },
        sonic_list: { id: 'sonic_list', name: 'Sonic Row', description: 'Visual Audio. Every track row includes an integrated waveform.', color: 'from-amber2 to-emerald-400', accent: 'text-emerald-500', bg: 'bg-[#050c14]', panel: 'bg-[#0a1622] border-emerald-500/10', btn: 'bg-emerald-600 hover:bg-emerald-500', layout: 'lib_waveform' },
        editorial: { id: 'editorial', name: 'Editorial Vibe', description: 'Magazine Style. Bold typography and curated aesthetic.', color: 'from-purple-600 to-indigo-600', accent: 'text-purple-400', bg: 'bg-[#0a0510]', panel: 'bg-white/5 border-purple-500/20', btn: 'bg-purple-600 hover:bg-purple-500 italic font-black', layout: 'lib_editorial' }
    };

    const concept = concepts[activeConcept];

    const renderPreview = () => {
        // Phase 2 Layouts
        if (concept.layout === 'legacy') return <LegacyPreview concept={concept} />;
        if (concept.layout === 'modular') return <ModularPreview concept={concept} />;
        if (concept.layout === 'stream') return <StreamPreview concept={concept} />;
        if (concept.layout === 'focused') return <FocusedPreview concept={concept} />;
        if (concept.layout === 'discovery') return <DiscoveryPreview concept={concept} />;

        // Phase 3 Library Styles
        if (concept.layout === 'lib_table') return <LibTablePreview concept={concept} />;
        if (concept.layout === 'lib_grid') return <LibGridPreview concept={concept} />;
        if (concept.layout === 'lib_minimal') return <LibMinimalPreview concept={concept} />;
        if (concept.layout === 'lib_waveform') return <LibWaveformPreview concept={concept} />;
        if (concept.layout === 'lib_editorial') return <LibEditorialPreview concept={concept} />;

        // Phase 1 Standard (Original)
        return (
            <div className="space-y-12">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                    <div className={`p-8 rounded-3xl border ${concept.panel}`}>
                        <h3 className="text-xs font-bold uppercase tracking-widest text-ink-muted mb-6">Component Preview</h3>
                        <div className="space-y-6">
                            <div className="flex flex-wrap gap-4">
                                <button className={`px-6 py-2.5 rounded-lg transition-all ${concept.btn}`}>Primary Action</button>
                                <button className="px-6 py-2.5 rounded-lg bg-white/5 border border-white/10 text-white font-medium">Ghost State</button>
                            </div>
                            <div className="relative">
                                <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-ink-muted" size={18} />
                                <input type="text" placeholder="Search library..." className="w-full bg-black/40 border border-white/5 rounded-xl py-3 pl-12 pr-4" readOnly />
                            </div>
                            <div className="space-y-2">
                                <div className="flex justify-between text-[10px] font-bold text-ink-muted uppercase"><span>Analyzing Audio</span><span>75%</span></div>
                                <div className="w-full h-2 bg-white/5 rounded-full overflow-hidden">
                                    <div className={`h-full bg-gradient-to-r ${concept.color}`} style={{ width: '75%' }}></div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        );
    };

    return (
        <div className={`flex h-full w-full ${concept.bg.includes('white') ? 'bg-slate-50 text-slate-900' : 'bg-mx-deepest text-white'} overflow-hidden animate-fade-in font-sans`}>
            {/* Design Sidebar */}
            <div className={`w-72 border-r ${concept.bg.includes('white') ? 'border-slate-200 bg-white' : 'border-white/5 bg-black/40'} p-6 flex flex-col gap-6 shrink-0 h-full overflow-y-auto`}>
                <div>
                    <h2 className="text-2xl font-black italic tracking-tighter uppercase mb-2 flex items-center gap-2">
                        <Sparkles className="text-amber2" />
                        Design Lab
                    </h2>
                    <p className="text-ink-muted text-[10px] font-black uppercase tracking-widest italic">Phase 3: Library Evolution</p>
                </div>

                <div className="flex flex-col gap-2">
                    {Object.values(concepts).map(c => (
                        <button
                            key={c.id}
                            onClick={() => setActiveConcept(c.id)}
                            className={`flex flex-col text-left p-4 rounded-xl transition-all border ${activeConcept === c.id
                                ? (concept.bg.includes('white') ? 'bg-blue-50 border-blue-200 shadow-md' : 'bg-white/5 border-white/20 shadow-lg scale-[1.02]')
                                : 'border-transparent hover:bg-white/5 text-ink-muted'
                                }`}
                        >
                            <span className={`text-sm font-bold ${activeConcept === c.id ? (concept.bg.includes('white') ? 'text-blue-600' : 'text-white') : ''}`}>{c.name}</span>
                            <div className={`h-1 w-12 mt-2 bg-gradient-to-r ${c.color} rounded-full`}></div>
                        </button>
                    ))}
                </div>
            </div>

            {/* Preview Stage */}
            <div className={`flex-1 p-12 overflow-y-auto transition-colors duration-700 ${concept.bg}`}>
                <div className="max-w-5xl mx-auto flex flex-col gap-12">
                    <div className="flex items-center justify-between">
                        <div>
                            <span className={`text-[10px] font-black uppercase tracking-[0.4em] mb-2 block ${concept.accent}`}>Concept Preview</span>
                            <h1 className="text-5xl font-black tracking-tight">{concept.name}</h1>
                            <p className="mt-4 text-ink-muted text-lg max-w-2xl font-bold italic">{concept.description}</p>
                        </div>
                        <div className={`w-24 h-24 rounded-3xl bg-gradient-to-br ${concept.color} flex items-center justify-center shadow-2xl shrink-0`}>
                            <Music size={48} className="text-white" />
                        </div>
                    </div>

                    <div className="min-h-[600px] flex flex-col gap-8">
                        {renderPreview()}
                    </div>

                    <div className="flex justify-center pt-8 border-t border-black/5 pb-24">
                        <button className={`flex items-center gap-3 px-12 py-4 rounded-full font-black text-xl uppercase tracking-tighter italic transition-all active:scale-95 shadow-xl ${concept.btn}`}>
                            <Sparkles /> Use This Identity
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
};

// --- PREVIEW COMPONENTS (PHASE 2 & 3) ---

const LibTablePreview = ({ concept }) => (
    <div className="flex flex-col h-full bg-[#111] border border-zinc-800 rounded-lg overflow-hidden font-sans text-[12px]">
        <div className="h-10 border-b border-zinc-800 bg-[#1a1a1a] flex items-center px-4 gap-6 text-zinc-500 font-bold uppercase tracking-wider text-[10px]">
            <div className="w-8 shrink-0">#</div>
            <div className="flex-1">Title</div>
            <div className="w-48">Artist</div>
            <div className="w-24">BPM</div>
            <div className="w-24">Key</div>
            <div className="w-32">Comment</div>
        </div>
        <div className="flex-1 overflow-y-auto bg-black">
            {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map(i => (
                <div key={i} className={`h-9 flex items-center px-4 gap-6 border-b border-zinc-900/50 hover:bg-zinc-800/40 cursor-pointer ${i === 2 ? 'bg-blue-900/20 text-blue-400' : 'text-zinc-300'}`}>
                    <div className="w-8 shrink-0 font-mono opacity-40">{i}</div>
                    <div className="flex-1 font-bold truncate">Professional Master Track {i}</div>
                    <div className="w-48 truncate opacity-60 italic">World Class Producer</div>
                    <div className="w-24 font-mono">124.00</div>
                    <div className="w-24 font-mono text-emerald-500">4A</div>
                    <div className="w-32 text-zinc-600 truncate text-[10px]">Good for opening set...</div>
                </div>
            ))}
        </div>
        <div className="h-7 bg-[#111] border-t border-zinc-800 flex items-center px-4 justify-between text-[9px] font-black text-zinc-500">
            <div className="flex gap-4"><span>COLLECTION LOADED</span><span className="text-blue-500">LINK: ON</span></div>
            <div>3369 TRACKS FOUND</div>
        </div>
    </div>
);

const LibGridPreview = ({ concept }) => (
    <div className="grid grid-cols-4 gap-6">
        {[1, 2, 3, 4, 1, 2, 3, 4].map(i => (
            <div key={i} className="group relative aspect-square rounded-2xl overflow-hidden bg-zinc-900 shadow-2xl transition-all hover:scale-105">
                <div className={`absolute inset-0 bg-gradient-to-br ${concept.color} opacity-20`}></div>
                <div className="absolute inset-0 flex items-center justify-center">
                    <Music size={48} className="text-white opacity-10 group-hover:opacity-100 group-hover:scale-110 transition-all duration-500" />
                </div>
                <div className="absolute inset-x-0 bottom-0 p-6 bg-gradient-to-t from-black via-black/80 to-transparent">
                    <p className="font-black italic uppercase tracking-tighter text-lg leading-none mb-1">Album Title {i}</p>
                    <p className="text-[10px] font-black uppercase tracking-[0.2em] text-rose-500">Techno Collective</p>
                </div>
            </div>
        ))}
    </div>
);

const LibMinimalPreview = ({ concept }) => (
    <div className="bg-white rounded-3xl shadow-2xl p-8 border border-slate-200">
        <div className="flex justify-between items-center mb-8 pb-8 border-b border-slate-100">
            <h2 className="text-3xl font-black tracking-tight text-slate-800 uppercase italic">Collection</h2>
            <div className="flex gap-4">
                <Search size={20} className="text-ink-secondary" />
                <Settings size={20} className="text-ink-secondary" />
            </div>
        </div>
        <div className="space-y-2">
            {[1, 2, 3, 4, 5, 6].map(i => (
                <div key={i} className={`flex items-center gap-6 p-4 rounded-xl transition-all cursor-pointer ${i === 1 ? 'bg-slate-50 shadow-sm' : 'hover:bg-slate-50/50 grayscale opacity-60 hover:grayscale-0 hover:opacity-100'}`}>
                    <div className="w-12 h-12 rounded-lg bg-slate-200 flex items-center justify-center shrink-0">
                        <Disc size={24} className="text-ink-secondary" />
                    </div>
                    <div className="flex-1">
                        <p className="font-bold text-slate-800">Minimal Track Title {i}</p>
                        <p className="text-xs font-medium text-ink-secondary">Streamline Artist</p>
                    </div>
                    <div className="text-right">
                        <p className="font-mono text-sm font-bold text-blue-600">6A</p>
                        <p className="text-[10px] font-black text-ink-secondary">122 BPM</p>
                    </div>
                    <ChevronRight size={18} className="text-ink-primary" />
                </div>
            ))}
        </div>
    </div>
);

const LibWaveformPreview = ({ concept }) => (
    <div className="flex flex-col gap-4">
        {[1, 2, 3, 4, 5].map(i => (
            <div key={i} className={`group bg-[#0a1622] rounded-2xl border border-emerald-500/10 p-4 flex items-center gap-6 hover:border-emerald-500/40 transition-all`}>
                <div className="w-12 h-12 rounded-xl bg-emerald-500/20 flex items-center justify-center shrink-0">
                    <Play size={24} className="text-emerald-500 fill-emerald-500" />
                </div>
                <div className="w-48">
                    <p className="font-black italic uppercase text-sm truncate leading-none mb-1">Frequency Track {i}</p>
                    <p className="text-[9px] font-black uppercase text-ink-muted tracking-widest">Oscillator X</p>
                </div>
                <div className="flex-1 h-12 bg-black/40 rounded-lg relative overflow-hidden">
                    <div className="absolute inset-0 flex items-center gap-px px-4">
                        {[...Array(40)].map((_, idx) => (
                            <div key={idx} className={`w-1 bg-emerald-500/30 rounded-full transition-all group-hover:bg-emerald-500/60`}
                                style={{ height: `${20 + Math.random() * 80}%` }}></div>
                        ))}
                    </div>
                </div>
                <div className="w-20 text-right shrink-0">
                    <p className="font-mono text-xs font-bold text-emerald-500">128.0</p>
                    <p className="text-[9px] font-black text-ink-muted">4:25</p>
                </div>
            </div>
        ))}
    </div>
);

const LibEditorialPreview = ({ concept }) => (
    <div className="columns-2 gap-8">
        {[1, 2, 3, 4, 5, 6].map(i => (
            <div key={i} className="mb-8 p-10 bg-white/5 border border-purple-500/10 rounded-[40px] break-inside-avoid group hover:border-purple-500/50 transition-all">
                <div className="flex justify-between items-start mb-6">
                    <span className="text-[10px] font-black uppercase tracking-[0.4em] text-purple-500 italic">Highly Recommended</span>
                    <Disc size={24} className="opacity-20 group-hover:opacity-100 group-hover:rotate-180 transition-all duration-1000" />
                </div>
                <h3 className="text-4xl font-black italic tracking-tighter uppercase leading-none mb-4">Magazine Title {i}</h3>
                <p className="text-ink-muted text-sm font-bold leading-relaxed mb-8">A deep exploration of minimal textures and syncopated rhythms from the Berlin underground.</p>
                <div className="flex items-center gap-4">
                    <button className="bg-purple-600 px-6 py-2 rounded-full text-[10px] font-black uppercase italic tracking-widest">Listen Now</button>
                    <span className="text-xs font-mono opacity-40">ITEM-00{i}-X</span>
                </div>
            </div>
        ))}
    </div>
);

// --- REUSED PHASE 2 COMPONENTS ---
const LegacyPreview = ({ concept }) => (
    <div className="flex flex-col h-full border border-white/10 overflow-hidden text-[11px] font-sans bg-black">
        <div className="grid grid-cols-2 h-40 border-b border-white/10 gap-x-px bg-white/5">
            {[1, 2].map(i => (
                <div key={i} className="p-4 flex flex-col justify-between border-r border-white/5">
                    <div className="flex justify-between items-start">
                        <div className="flex items-center gap-3"><div className={`w-10 h-10 ${concept.color} bg-opacity-20 flex items-center justify-center rounded-lg border border-white/5`}><Disc size={20} className={concept.accent} /></div><div><p className="font-bold text-sm">Track {i}</p><p className="text-ink-muted text-[10px] uppercase font-bold tracking-widest">Artist Name</p></div></div>
                        <p className={`font-mono text-xl ${concept.accent}`}>128.00</p>
                    </div>
                    <div className="space-y-2"><div className="flex justify-between text-[8px] opacity-40 uppercase font-black"><span>0:00.0</span><span>Remaining 4:32.1</span></div><div className="flex items-center gap-2"><Play size={12} className={concept.accent} fill="currentColor" /><div className="flex-1 h-12 bg-black/60 relative rounded overflow-hidden"><div className={`absolute top-1/2 left-0 -translate-y-1/2 w-full h-8 bg-gradient-to-r ${concept.color} opacity-40`}></div></div></div></div>
                </div>
            ))}
        </div>
        <div className="flex-1 flex min-h-0">
            <div className="w-48 border-r border-white/10 p-4 space-y-2 opacity-60 bg-[#050505]"><p className="font-bold flex items-center gap-2 uppercase text-[9px] mb-4 text-ink-secondary tracking-widest"><List size={12} /> Library Tree</p><p className="bg-white/5 p-2 rounded text-blue-400 font-bold">ALL TRACKS</p><p className="p-2 hover:bg-white/5 rounded">PLAYLIST COLLECTION</p></div>
            <div className="flex-1 p-4 bg-black"><table className="w-full text-left"><thead><tr className="border-b border-white/10 text-ink-muted text-[9px] uppercase font-black tracking-widest"><th className="pb-2">Title</th><th className="pb-2">Artist</th><th className="pb-2">BPM</th></tr></thead><tbody className="opacity-80">{[1, 2, 3, 4].map(i => (<tr key={i} className={`border-b border-white/5 hover:bg-white/5 cursor-pointer ${i === 1 ? 'bg-blue-500/10 text-blue-400' : ''}`}><td className="py-2 font-bold">Masterpiece {i}</td><td className="py-2 opacity-50">Producer X</td><td className="py-2 font-mono">124.0</td></tr>))}</tbody></table></div>
        </div>
        <div className="h-8 bg-[#0a0a0a] flex items-center px-4 justify-between border-t border-white/10 text-[9px] font-bold text-zinc-500"><span>REKORDBOX LINK ACTIVE</span><span>3,369 ITEMS LOADED</span></div>
    </div>
);

const ModularPreview = ({ concept }) => (
    <div className="grid grid-cols-6 grid-rows-4 h-full gap-4 p-4 bg-[#050505]">
        <div className={`col-span-4 row-span-2 ${concept.panel} flex flex-col p-6 rounded-2xl relative overflow-hidden`}><div className="flex-1 flex items-center justify-center"><Activity size={80} className={`${concept.accent} opacity-20 absolute`} /><div className="w-full h-24 bg-black/40 rounded-xl border border-white/5"></div></div></div>
        <div className={`col-span-2 row-span-2 ${concept.panel} p-6 rounded-2xl flex flex-col`}><div className="grid grid-cols-2 gap-4 flex-1">{[1, 2, 3, 4].map(i => (<div key={i} className="bg-black/40 rounded-xl border border-white/5 p-2 group flex flex-col items-center justify-center"><div className="w-12 h-12 rounded-full border-4 border-line-subtle relative shadow-inner"><div className="absolute top-0 left-1/2 -translate-x-1/2 w-1 h-5 bg-orange-500 rounded-full"></div></div></div>))}</div></div>
        <div className={`col-span-6 row-span-2 ${concept.panel} p-6 rounded-2xl flex gap-6 overflow-x-auto overflow-hidden`}>{[1, 2, 3, 4].map(i => (<div key={i} className="w-40 h-28 bg-black/60 flex-shrink-0 rounded-xl border border-white/5 p-4 flex flex-col justify-between"><Disc size={20} className="opacity-10" /><span className="font-black italic text-xs uppercase tracking-tighter">Crate {i}</span></div>))}</div>
    </div>
);

const StreamPreview = ({ concept }) => (
    <div className="flex flex-col h-full bg-[#050510] font-sans">
        <div className="h-16 bg-black/40 backdrop-blur-md flex items-center px-10 justify-between border-b border-white/5"><div className="flex items-center gap-6"><span className="font-black italic uppercase tracking-tighter text-2xl">SONIC FLOW / MANAGER</span></div></div>
        <div className="flex-1 p-10 flex flex-col gap-10 overflow-y-auto">
            <div className={`h-48 rounded-[40px] ${concept.panel} p-10 flex flex-col justify-center relative overflow-hidden`}><div className="w-full h-10 bg-black/40 rounded-2xl relative overflow-hidden border border-white/5"><div className={`absolute top-1/2 left-0 w-full h-[2px] bg-white/5`}></div><div className={`absolute top-0 bottom-0 left-1/2 w-px bg-amber2 shadow-[0_0_15px_rgba(34,211,238,1)]`}></div></div></div>
            <div className="grid grid-cols-4 gap-8">{[1, 2, 3, 4].map(i => (<div key={i} className={`aspect-video rounded-[32px] ${concept.panel} p-6 flex flex-col justify-between hover:scale-[1.05] transition-transform`}><Play size={16} className={concept.accent} /><div><span className="font-black italic text-base uppercase tracking-tight block">Session 00{i}</span></div></div>))}</div>
        </div>
    </div>
);

const FocusedPreview = ({ concept }) => (
    <div className="flex items-center justify-center h-full relative overflow-hidden bg-black font-sans">
        <div className={`absolute w-[800px] h-[800px] bg-gradient-to-br ${concept.color} opacity-5 rounded-full blur-[160px]`}></div>
        <div className={`w-[450px] h-[450px] ${concept.panel} flex flex-col items-center justify-center p-16 text-center shadow-2xl relative z-10 overflow-hidden`}>
            <div className={`w-28 h-28 rounded-full bg-gradient-to-br ${concept.color} flex items-center justify-center mb-10 shadow-xl`}><Disc size={56} className="text-white animate-spin-slow" /></div>
            <h2 className="text-3xl font-black italic tracking-tighter uppercase mb-3 relative z-10">Studio Spotlight</h2>
            <button className={`mt-10 px-12 py-4 rounded-full font-black uppercase text-sm tracking-[0.3em] italic shadow-2xl ${concept.btn}`}>Start Session</button>
        </div>
    </div>
);

const DiscoveryPreview = ({ concept }) => (
    <div className="h-full relative overflow-hidden flex items-center justify-center font-sans bg-[#02020a]">
        <div className="relative z-10 w-full h-full p-16 flex flex-col">
            <div className="flex justify-between items-start mb-16"><div><h2 className="text-6xl font-black italic tracking-tighter uppercase leading-none">NEURAL MAP</h2></div></div>
            <div className="relative flex-1 flex items-center justify-center">
                <div className="absolute w-[500px] h-[500px] border border-fuchsia-500/5 rounded-full animate-spin-slow"></div>
                {[{ top: '30%', left: '80%', size: 64, label: 'DARK' }, { bottom: '10%', right: '15%', size: 80, label: 'EXPERIMENTAL' },].map((node, i) => (
                    <div key={i} className={`absolute bg-fuchsia-600 rounded-full shadow-[0_0_30px_rgba(217,70,239,0.4)] border-4 border-white/10 flex items-center justify-center group cursor-pointer hover:scale-125 transition-all duration-500`}
                        style={{ top: node.top, bottom: node.bottom, left: node.left, right: node.right, width: node.size, height: node.size }}>
                    </div>
                ))}
                <div className="text-center relative z-20"><Activity size={180} className="text-fuchsia-400 opacity-5 animate-pulse" /><p className="text-2xl font-black italic tracking-tighter uppercase mb-1">Mapping Collection</p></div>
            </div>
        </div>
    </div>
);

export default DesignView;
