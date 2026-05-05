import React, { useState } from 'react';
import { Sparkles, Music, Zap, Layers, Grid3X3, Disc, Play, Activity, Settings, Search, Sliders, Radio, Users, GitBranch, Keyboard, Monitor, Headphones, Mic2, Volume2, Check } from 'lucide-react';

const MOCKUPS = [
    { id: 'stems', name: 'AI Stem Separation', desc: 'Split tracks into Vocals, Drums, Bass, Melody' },
    { id: 'smart_playlist', name: 'Smart Playlist Builder', desc: 'Visual rule-based playlist editor' },
    { id: 'batch_tag', name: 'Advanced Batch Tagging', desc: 'Excel-like grid for mass metadata editing' },
    { id: 'set_planner', name: 'DJ Set Planner', desc: 'Visual timeline for energy flow planning' },
    { id: 'streaming', name: 'Streaming Service Hub', desc: 'Spotify, Beatport, Tidal integration' },
    { id: 'dvs', name: 'Vinyl/DVS Emulator', desc: 'Timecode vinyl calibration screen' },
    { id: 'collab', name: 'Cloud Collaboration', desc: 'Share cue points with other DJs' },
    { id: 'harmonic', name: 'Harmonic Mixing', desc: 'Automated transition point finder' },
    { id: 'routing', name: 'Audio Routing Matrix', desc: 'Professional I/O assignment grid' },
    { id: 'macros', name: 'Macro & Shortcut Manager', desc: 'MIDI controller and shortcut mapping' },
];

const BACKGROUNDS = [
    { id: 'beatgrid', name: 'Beat Grid', desc: 'Vertical bars, every 4th accented (4/4)' },
    { id: 'waveline', name: 'Wave Lines', desc: 'Horizontal sine strokes, tileable' },
    { id: 'cuemarks', name: 'Cue Markers', desc: 'Thin verticals with amber dot accents' },
    { id: 'spectrum', name: 'Spectrum Bars', desc: 'Staggered vertical lines, EQ feel' },
    { id: 'crosshatch', name: 'Diagonal Hatch', desc: 'Crossing diagonals, high contrast' },
    { id: 'circuit', name: 'Circuit Traces', desc: 'PCB lines + knob nodes, navy/teal/amber' },
    { id: 'constellation', name: 'Constellations', desc: 'Stars connected by thin lines' },
    { id: 'sunburst', name: 'Sunburst Grid', desc: 'Radial ray bursts on tiled grid' },
    { id: 'tribal', name: 'Tribal Zigzag', desc: 'Aztec/Maya stepped bands' },
    { id: 'notes', name: 'Note Glyphs', desc: 'Eighth-notes scattered on staff lines' },
    { id: 'boldstripes', name: 'Bold Stripes', desc: 'Thick vertical bars, mono' },
    { id: 'thickdiag', name: 'Thick Diagonals', desc: 'Heavy 45° lines, mono' },
    { id: 'arcs', name: 'Concentric Arcs', desc: 'Bold quarter arcs, vinyl reduction' },
    { id: 'chevron', name: 'Chevron', desc: 'Heavy V-shapes stacked' },
    { id: 'heavygrid', name: 'Heavy Grid', desc: 'Bold square grid, mono' },
    { id: 'wavecue', name: 'Wave + Cues', desc: 'Bold sine + vertical cue markers' },
    { id: 'pulsecue', name: 'Pulse + Cues', desc: 'Square wave with amber dot cues' },
    { id: 'waveseg', name: 'Segmented Wave', desc: 'Sine broken by vertical bars' },
    { id: 'doublewave', name: 'Dual Wave Cues', desc: 'Two phase-shifted waves + dots' },
    { id: 'stepwave', name: 'Stepped Wave', desc: 'Stair wave with cue verticals' },
];

const DesignView = () => {
    const [activeSection, setActiveSection] = useState('mockup');
    const [activeMockup, setActiveMockup] = useState('stems');
    const [activeBackground, setActiveBackground] = useState('beatgrid');
    const [selectedBg, setSelectedBg] = useState(localStorage.getItem('rb_bg_theme') || null);

    const applyBackground = (id) => {
        localStorage.setItem('rb_bg_theme', id);
        setSelectedBg(id);
    };

    return (
        <div className="flex h-full w-full bg-mx-deepest text-ink-primary overflow-hidden animate-fade-in font-sans">
            {/* Sidebar */}
            <div className="w-72 border-r border-line-subtle bg-mx-shell p-4 flex flex-col gap-4 shrink-0 h-full overflow-y-auto">
                <div>
                    <h2 className="text-[16px] font-bold tracking-tight flex items-center gap-2 mb-1">
                        <Sparkles size={16} className="text-amber2" />
                        Design Lab
                    </h2>
                    <p className="text-[10px] text-ink-muted">Feature concepts & themes</p>
                </div>

                {/* Mockups section */}
                <div>
                    <div className="mx-caption px-1 mb-2">Feature Mockups</div>
                    <div className="flex flex-col gap-1">
                        {MOCKUPS.map(m => (
                            <button
                                key={m.id}
                                onClick={() => { setActiveSection('mockup'); setActiveMockup(m.id); }}
                                className={`text-left p-2.5 rounded-mx-sm transition-all border ${
                                    activeSection === 'mockup' && activeMockup === m.id
                                        ? 'bg-amber2/10 border-amber2/30 text-amber2'
                                        : 'border-transparent hover:bg-mx-hover text-ink-secondary'
                                }`}
                            >
                                <div className="text-[11px] font-medium">{m.name}</div>
                                <div className="text-[9px] text-ink-muted mt-0.5">{m.desc}</div>
                            </button>
                        ))}
                    </div>
                </div>

                {/* Backgrounds section */}
                <div>
                    <div className="mx-caption px-1 mb-2">Backgrounds</div>
                    <div className="flex flex-col gap-1">
                        {BACKGROUNDS.map(bg => (
                            <button
                                key={bg.id}
                                onClick={() => { setActiveSection('background'); setActiveBackground(bg.id); }}
                                className={`text-left p-2.5 rounded-mx-sm transition-all border flex items-center justify-between ${
                                    activeSection === 'background' && activeBackground === bg.id
                                        ? 'bg-amber2/10 border-amber2/30 text-amber2'
                                        : 'border-transparent hover:bg-mx-hover text-ink-secondary'
                                }`}
                            >
                                <div>
                                    <div className="text-[11px] font-medium">{bg.name}</div>
                                    <div className="text-[9px] text-ink-muted mt-0.5">{bg.desc}</div>
                                </div>
                                {selectedBg === bg.id && <Check size={12} className="text-ok shrink-0" />}
                            </button>
                        ))}
                    </div>
                </div>
            </div>

            {/* Preview */}
            <div className="flex-1 overflow-y-auto p-8">
                {activeSection === 'mockup' && <MockupPreview id={activeMockup} />}
                {activeSection === 'background' && (
                    <BackgroundPreview id={activeBackground} onApply={applyBackground} isActive={selectedBg === activeBackground} />
                )}
            </div>
        </div>
    );
};

const MockupPreview = ({ id }) => {
    const mockup = MOCKUPS.find(m => m.id === id);
    return (
        <div className="max-w-4xl mx-auto">
            <div className="mb-6">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-amber2">Concept Preview</span>
                <h1 className="text-[28px] font-bold tracking-tight mt-1">{mockup?.name}</h1>
                <p className="text-[13px] text-ink-muted mt-1">{mockup?.desc}</p>
            </div>
            <div className="mx-card p-6 min-h-[500px]">
                {id === 'stems' && <StemsMockup />}
                {id === 'smart_playlist' && <SmartPlaylistMockup />}
                {id === 'batch_tag' && <BatchTagMockup />}
                {id === 'set_planner' && <SetPlannerMockup />}
                {id === 'streaming' && <StreamingMockup />}
                {id === 'dvs' && <DvsMockup />}
                {id === 'collab' && <CollabMockup />}
                {id === 'harmonic' && <HarmonicMockup />}
                {id === 'routing' && <RoutingMockup />}
                {id === 'macros' && <MacrosMockup />}
            </div>
        </div>
    );
};

const StemsMockup = () => (
    <div className="space-y-4">
        <div className="flex items-center gap-3 p-3 bg-mx-input rounded-mx-sm border border-line-subtle">
            <Music size={14} className="text-amber2" />
            <span className="text-[12px] font-medium">Selected: Deep House Track 001.wav</span>
            <span className="ml-auto text-[10px] font-mono text-ink-muted">4:32 · 124 BPM</span>
        </div>
        {['Vocals', 'Drums', 'Bass', 'Melody'].map((stem, i) => {
            const colors = ['#F87171', '#2DD4BF', '#F59E0B', '#818CF8'];
            return (
                <div key={stem} className="flex items-center gap-3 p-3 bg-mx-input rounded-mx-sm border border-line-subtle">
                    <div className="w-16 text-[11px] font-semibold" style={{ color: colors[i] }}>{stem}</div>
                    <div className="flex-1 h-8 bg-black/40 rounded overflow-hidden relative">
                        <div className="absolute inset-0 flex items-center gap-px px-2">
                            {[...Array(50)].map((_, j) => (
                                <div key={j} className="w-0.5 rounded-full" style={{ height: `${15 + Math.random() * 70}%`, background: colors[i], opacity: 0.5 }} />
                            ))}
                        </div>
                    </div>
                    <div className="flex items-center gap-2">
                        <button className="text-[9px] px-2 py-1 rounded border border-line-subtle text-ink-muted hover:text-ink-primary">S</button>
                        <button className="text-[9px] px-2 py-1 rounded border border-line-subtle text-ink-muted hover:text-ink-primary">M</button>
                        <input type="range" className="w-16 h-1 accent-amber2" defaultValue={80} />
                    </div>
                </div>
            );
        })}
        <button className="btn-primary mt-4">Start Separation</button>
    </div>
);

const SmartPlaylistMockup = () => (
    <div className="space-y-4">
        <div className="text-[11px] text-ink-muted mb-2">Rules (all must match):</div>
        {[
            { field: 'BPM', op: '>', value: '120' },
            { field: 'Key', op: '=', value: '8A' },
            { field: 'Genre', op: 'contains', value: 'Techno' },
        ].map((rule, i) => (
            <div key={i} className="flex items-center gap-2">
                <select className="input-glass text-[11px] py-1.5 px-2 w-28"><option>{rule.field}</option></select>
                <select className="input-glass text-[11px] py-1.5 px-2 w-24"><option>{rule.op}</option></select>
                <input className="input-glass text-[11px] py-1.5 px-2 flex-1" defaultValue={rule.value} readOnly />
                <button className="text-bad text-[11px] p-1">×</button>
            </div>
        ))}
        <button className="text-[11px] text-amber2 hover:underline">+ Add Rule</button>
        <div className="mt-4 p-3 bg-mx-input rounded-mx-sm border border-line-subtle">
            <span className="text-[11px] text-ink-muted">Preview: </span>
            <span className="text-[11px] font-mono text-ok">247 tracks match</span>
        </div>
    </div>
);

const BatchTagMockup = () => (
    <div className="overflow-x-auto">
        <table className="w-full text-[11px]">
            <thead>
                <tr className="border-b border-line-subtle text-[10px] text-ink-muted uppercase tracking-wider">
                    <th className="text-left py-2 px-2 w-8">#</th>
                    <th className="text-left py-2 px-2">Title</th>
                    <th className="text-left py-2 px-2">Artist</th>
                    <th className="text-left py-2 px-2">Genre</th>
                    <th className="text-left py-2 px-2">Comment</th>
                    <th className="text-left py-2 px-2 w-16">Rating</th>
                </tr>
            </thead>
            <tbody>
                {[1,2,3,4,5,6].map(i => (
                    <tr key={i} className="border-b border-line-subtle hover:bg-mx-hover">
                        <td className="py-2 px-2 text-ink-muted font-mono">{i}</td>
                        <td className="py-2 px-2"><input className="bg-transparent w-full outline-none text-ink-primary" defaultValue={`Track Title ${i}`} readOnly /></td>
                        <td className="py-2 px-2"><input className="bg-transparent w-full outline-none text-ink-secondary" defaultValue="Artist Name" readOnly /></td>
                        <td className="py-2 px-2"><input className="bg-transparent w-full outline-none text-ink-secondary" defaultValue="Tech House" readOnly /></td>
                        <td className="py-2 px-2"><input className="bg-transparent w-full outline-none text-ink-muted" defaultValue="Good opener" readOnly /></td>
                        <td className="py-2 px-2 text-amber2">★★★★☆</td>
                    </tr>
                ))}
            </tbody>
        </table>
        <div className="mt-3 flex gap-2">
            <button className="btn-secondary text-[10px]">Find & Replace</button>
            <button className="btn-secondary text-[10px]">Auto-Fill Genre</button>
        </div>
    </div>
);

const SetPlannerMockup = () => (
    <div className="space-y-4">
        <div className="flex items-center gap-2 text-[10px] text-ink-muted uppercase tracking-wider mb-2">
            <span>0:00</span><div className="flex-1 h-px bg-line-subtle" /><span>1:00:00</span>
        </div>
        <div className="relative h-40 bg-mx-input rounded-mx-sm border border-line-subtle overflow-hidden">
            <svg className="absolute inset-0 w-full h-full" preserveAspectRatio="none" viewBox="0 0 100 40">
                <path d="M0,35 C10,30 20,25 30,20 C40,15 50,10 60,5 C70,3 80,8 90,15 C95,20 100,25 100,30" stroke="#2DD4BF" strokeWidth="0.5" fill="none" opacity="0.6" />
                <path d="M0,35 C10,30 20,25 30,20 C40,15 50,10 60,5 C70,3 80,8 90,15 C95,20 100,25 100,30" fill="url(#energy)" opacity="0.1" />
                <defs><linearGradient id="energy" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#2DD4BF" /><stop offset="1" stopColor="transparent" /></linearGradient></defs>
            </svg>
            {[15, 30, 48, 65, 82].map((left, i) => (
                <div key={i} className="absolute top-1/2 -translate-y-1/2 h-6 w-12 bg-amber2/20 border border-amber2/40 rounded text-[8px] text-amber2 flex items-center justify-center" style={{ left: `${left}%` }}>
                    Track {i+1}
                </div>
            ))}
        </div>
        <div className="flex items-center gap-4 text-[10px] text-ink-muted">
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-teal-400" /> Energy Curve</span>
            <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-amber2/40" /> Track Blocks</span>
        </div>
    </div>
);

const StreamingMockup = () => (
    <div className="grid grid-cols-3 gap-4">
        {[
            { name: 'Spotify', color: '#1DB954', status: 'Connected', tracks: '3,247' },
            { name: 'Beatport', color: '#94D500', status: 'Connected', tracks: '891' },
            { name: 'Tidal', color: '#000000', status: 'Not connected', tracks: '—' },
        ].map(svc => (
            <div key={svc.name} className="p-4 bg-mx-input rounded-mx-sm border border-line-subtle">
                <div className="text-[13px] font-semibold mb-1" style={{ color: svc.color }}>{svc.name}</div>
                <div className="text-[10px] text-ink-muted mb-3">{svc.status}</div>
                <div className="text-[10px] font-mono text-ink-secondary">{svc.tracks} tracks</div>
                <button className="mt-3 text-[10px] btn-secondary w-full">{svc.status === 'Connected' ? 'Sync Now' : 'Connect'}</button>
            </div>
        ))}
    </div>
);

const DvsMockup = () => (
    <div className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
            <div className="p-4 bg-mx-input rounded-mx-sm border border-line-subtle text-center">
                <Disc size={48} className="mx-auto text-ink-muted mb-2 opacity-30" />
                <div className="text-[11px] font-semibold text-ink-primary">Deck A</div>
                <div className="text-[10px] text-ok mt-1">Signal: Good (92%)</div>
            </div>
            <div className="p-4 bg-mx-input rounded-mx-sm border border-line-subtle text-center">
                <Disc size={48} className="mx-auto text-ink-muted mb-2 opacity-30" />
                <div className="text-[11px] font-semibold text-ink-primary">Deck B</div>
                <div className="text-[10px] text-amber2 mt-1">Signal: Fair (67%)</div>
            </div>
        </div>
        <div className="flex gap-3">
            <div className="flex-1">
                <label className="text-[10px] text-ink-muted uppercase block mb-1">Timecode Type</label>
                <select className="input-glass w-full text-[11px] py-1.5 px-2"><option>Serato CV02.5</option></select>
            </div>
            <div className="flex-1">
                <label className="text-[10px] text-ink-muted uppercase block mb-1">Input Device</label>
                <select className="input-glass w-full text-[11px] py-1.5 px-2"><option>DDJ-1000 Ch 1/2</option></select>
            </div>
        </div>
    </div>
);

const CollabMockup = () => (
    <div className="space-y-4">
        <div className="flex items-center gap-3 mb-4">
            <div className="flex -space-x-2">
                {['bg-teal-500', 'bg-amber-500', 'bg-purple-500'].map((c, i) => (
                    <div key={i} className={`w-7 h-7 rounded-full ${c} border-2 border-mx-deepest flex items-center justify-center text-[9px] font-bold text-white`}>
                        {['TB', 'MK', 'DJ'][i]}
                    </div>
                ))}
            </div>
            <span className="text-[11px] text-ink-muted">3 collaborators</span>
            <button className="ml-auto btn-secondary text-[10px]">Invite</button>
        </div>
        <div className="space-y-2">
            {['Hot Cue A — Drop @ 1:32', 'Memory Cue — Breakdown', 'Hot Cue B — Build-up'].map((cue, i) => (
                <div key={i} className="flex items-center gap-3 p-2.5 bg-mx-input rounded-mx-sm border border-line-subtle">
                    <div className={`w-2 h-2 rounded-full ${['bg-teal-400', 'bg-amber-400', 'bg-purple-400'][i]}`} />
                    <span className="text-[11px] text-ink-primary flex-1">{cue}</span>
                    <span className="text-[9px] text-ink-muted">by {['TB', 'MK', 'DJ'][i]}</span>
                </div>
            ))}
        </div>
    </div>
);

const HarmonicMockup = () => (
    <div className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
            {['Track A', 'Track B'].map((label, i) => (
                <div key={label} className="p-4 bg-mx-input rounded-mx-sm border border-line-subtle">
                    <div className="text-[11px] font-semibold text-ink-primary mb-2">{label}</div>
                    <div className="text-[10px] text-ink-muted">Deep Dreams — Producer X</div>
                    <div className="mt-2 flex items-center gap-2">
                        <span className="text-[12px] font-mono font-bold" style={{ color: i === 0 ? '#2DD4BF' : '#818CF8' }}>
                            {i === 0 ? '8A' : '9A'}
                        </span>
                        <span className="text-[10px] text-ink-muted">{i === 0 ? '124' : '125'} BPM</span>
                    </div>
                </div>
            ))}
        </div>
        <div className="p-3 bg-ok/5 border border-ok/20 rounded-mx-sm flex items-center gap-2">
            <Check size={14} className="text-ok" />
            <span className="text-[11px] text-ok font-medium">Compatible — Adjacent keys (energy boost)</span>
        </div>
        <div className="text-[10px] text-ink-muted">Suggested transition point: 3:48 → 0:16 (16-bar mix)</div>
    </div>
);

const RoutingMockup = () => {
    const inputs = ['Master', 'Deck A', 'Deck B', 'Mic'];
    const outputs = ['Main L/R', 'Booth', 'Headphones', 'Record'];
    return (
        <div className="overflow-x-auto">
            <table className="text-[10px]">
                <thead>
                    <tr>
                        <th className="p-2" />
                        {outputs.map(o => <th key={o} className="p-2 text-ink-muted font-normal">{o}</th>)}
                    </tr>
                </thead>
                <tbody>
                    {inputs.map((inp, i) => (
                        <tr key={inp}>
                            <td className="p-2 text-ink-secondary font-medium">{inp}</td>
                            {outputs.map((_, j) => (
                                <td key={j} className="p-2 text-center">
                                    <div className={`w-4 h-4 rounded-full border mx-auto cursor-pointer transition-all ${
                                        (i === 0 && j === 0) || (i === 1 && j === 2) || (i === 0 && j === 3)
                                            ? 'bg-teal-400 border-teal-400'
                                            : 'border-line-default hover:border-ink-muted'
                                    }`} />
                                </td>
                            ))}
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
};

const MacrosMockup = () => (
    <div className="grid grid-cols-2 gap-4">
        <div>
            <div className="text-[10px] text-ink-muted uppercase tracking-wider mb-2">Commands</div>
            <div className="space-y-1">
                {['Play/Pause', 'Cue', 'Loop In', 'Loop Out', 'Sync', 'Filter'].map(cmd => (
                    <div key={cmd} className="p-2 bg-mx-input rounded-mx-xs border border-line-subtle text-[11px] text-ink-primary hover:bg-mx-hover cursor-pointer">{cmd}</div>
                ))}
            </div>
        </div>
        <div>
            <div className="text-[10px] text-ink-muted uppercase tracking-wider mb-2">Assigned Shortcuts</div>
            <div className="space-y-1">
                {[
                    { cmd: 'Play/Pause', key: 'Space' },
                    { cmd: 'Cue', key: 'MIDI CC#1' },
                    { cmd: 'Loop In', key: 'Ctrl+L' },
                ].map(m => (
                    <div key={m.cmd} className="p-2 bg-mx-input rounded-mx-xs border border-line-subtle flex justify-between items-center">
                        <span className="text-[11px] text-ink-primary">{m.cmd}</span>
                        <span className="text-[9px] font-mono text-amber2 bg-amber2/10 px-1.5 py-0.5 rounded">{m.key}</span>
                    </div>
                ))}
            </div>
            <button className="mt-3 btn-secondary text-[10px] w-full flex items-center justify-center gap-1">
                <Radio size={10} /> MIDI Learn
            </button>
        </div>
    </div>
);

const BackgroundPreview = ({ id, onApply, isActive }) => {
    const bg = BACKGROUNDS.find(b => b.id === id);
    // Tileable SVG line patterns. All on #0a0a0a, white/amber strokes for contrast.
    const bgStyles = {
        beatgrid: {
            backgroundColor: '#0a0a0a',
            backgroundImage: `url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='80' viewBox='0 0 160 80'><line x1='0.5' y1='0' x2='0.5' y2='80' stroke='%23f59e0b' stroke-opacity='0.35' stroke-width='1'/><line x1='40.5' y1='10' x2='40.5' y2='70' stroke='%23ffffff' stroke-opacity='0.08' stroke-width='1'/><line x1='80.5' y1='10' x2='80.5' y2='70' stroke='%23ffffff' stroke-opacity='0.08' stroke-width='1'/><line x1='120.5' y1='10' x2='120.5' y2='70' stroke='%23ffffff' stroke-opacity='0.08' stroke-width='1'/></svg>")`,
        },
        waveline: {
            backgroundColor: '#0a0a0a',
            backgroundImage: `url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='120' height='40' viewBox='0 0 120 40'><path d='M0 20 Q 30 4 60 20 T 120 20' fill='none' stroke='%23ffffff' stroke-opacity='0.1' stroke-width='1'/><path d='M0 20 Q 30 36 60 20 T 120 20' fill='none' stroke='%23ffffff' stroke-opacity='0.04' stroke-width='1'/></svg>")`,
        },
        cuemarks: {
            backgroundColor: '#0a0a0a',
            backgroundImage: `url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='100' height='100' viewBox='0 0 100 100'><line x1='0.5' y1='0' x2='0.5' y2='100' stroke='%23ffffff' stroke-opacity='0.06' stroke-width='1'/><circle cx='0.5' cy='20' r='1.6' fill='%23f59e0b' fill-opacity='0.55'/><line x1='50.5' y1='0' x2='50.5' y2='100' stroke='%23ffffff' stroke-opacity='0.06' stroke-width='1'/><circle cx='50.5' cy='70' r='1.6' fill='%2345d4bf' fill-opacity='0.45'/></svg>")`,
        },
        spectrum: {
            backgroundColor: '#0a0a0a',
            backgroundImage: `url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='60' height='60' viewBox='0 0 60 60'><line x1='6' y1='30' x2='6' y2='54' stroke='%23ffffff' stroke-opacity='0.12' stroke-width='1'/><line x1='14' y1='22' x2='14' y2='54' stroke='%23ffffff' stroke-opacity='0.12' stroke-width='1'/><line x1='22' y1='10' x2='22' y2='54' stroke='%23f59e0b' stroke-opacity='0.25' stroke-width='1'/><line x1='30' y1='18' x2='30' y2='54' stroke='%23ffffff' stroke-opacity='0.12' stroke-width='1'/><line x1='38' y1='28' x2='38' y2='54' stroke='%23ffffff' stroke-opacity='0.12' stroke-width='1'/><line x1='46' y1='14' x2='46' y2='54' stroke='%23ffffff' stroke-opacity='0.12' stroke-width='1'/><line x1='54' y1='34' x2='54' y2='54' stroke='%23ffffff' stroke-opacity='0.12' stroke-width='1'/></svg>")`,
        },
        crosshatch: {
            backgroundColor: '#0a0a0a',
            backgroundImage: `repeating-linear-gradient(45deg, transparent 0 11px, rgba(255,255,255,0.06) 11px 12px), repeating-linear-gradient(-45deg, transparent 0 11px, rgba(245,158,11,0.08) 11px 12px)`,
        },
        circuit: {
            backgroundColor: '#0a1628',
            backgroundImage: `url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='120' height='120' viewBox='0 0 120 120'><g fill='none' stroke-width='1'><path d='M0 30 H40 V60 H80 V20 H120' stroke='%2345d4bf' stroke-opacity='0.35'/><path d='M0 90 H30 V70 H70 V100 H120' stroke='%2345d4bf' stroke-opacity='0.25'/><path d='M20 0 V20 H60 V50' stroke='%23f59e0b' stroke-opacity='0.3'/><path d='M100 0 V40 H80' stroke='%23f59e0b' stroke-opacity='0.25'/><circle cx='40' cy='30' r='3' stroke='%2345d4bf' stroke-opacity='0.6'/><circle cx='40' cy='30' r='1' fill='%23f59e0b' fill-opacity='0.7'/><circle cx='80' cy='60' r='3' stroke='%2345d4bf' stroke-opacity='0.6'/><circle cx='80' cy='60' r='1' fill='%23f59e0b' fill-opacity='0.7'/><circle cx='30' cy='90' r='2.5' stroke='%23f59e0b' stroke-opacity='0.5'/><rect x='58' y='48' width='4' height='4' fill='%2345d4bf' fill-opacity='0.5'/></g></svg>")`,
        },
        constellation: {
            backgroundColor: '#0a1628',
            backgroundImage: `url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='200' height='200' viewBox='0 0 200 200'><g fill='none' stroke='%2345d4bf' stroke-opacity='0.25' stroke-width='0.6'><line x1='30' y1='40' x2='70' y2='60'/><line x1='70' y1='60' x2='110' y2='30'/><line x1='110' y1='30' x2='140' y2='70'/><line x1='140' y1='70' x2='170' y2='50'/><line x1='40' y1='130' x2='80' y2='150'/><line x1='80' y1='150' x2='130' y2='140'/><line x1='130' y1='140' x2='160' y2='170'/><line x1='70' y1='60' x2='80' y2='150'/></g><g fill='%23ffffff' fill-opacity='0.55'><circle cx='30' cy='40' r='1.2'/><circle cx='110' cy='30' r='1.2'/><circle cx='140' cy='70' r='1.2'/><circle cx='170' cy='50' r='1'/><circle cx='40' cy='130' r='1'/><circle cx='130' cy='140' r='1.2'/><circle cx='160' cy='170' r='1'/></g><g fill='%23f59e0b' fill-opacity='0.7'><circle cx='70' cy='60' r='1.4'/><circle cx='80' cy='150' r='1.4'/></g></svg>")`,
        },
        sunburst: {
            backgroundColor: '#0a1628',
            backgroundImage: `url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='140' height='140' viewBox='0 0 140 140'><g fill='none' stroke-width='0.8' transform='translate(70 70)'><line x1='0' y1='-30' x2='0' y2='-50' stroke='%23f59e0b' stroke-opacity='0.55'/><line x1='0' y1='30' x2='0' y2='50' stroke='%23f59e0b' stroke-opacity='0.55'/><line x1='-30' y1='0' x2='-50' y2='0' stroke='%23f59e0b' stroke-opacity='0.55'/><line x1='30' y1='0' x2='50' y2='0' stroke='%23f59e0b' stroke-opacity='0.55'/><line x1='-21' y1='-21' x2='-35' y2='-35' stroke='%2345d4bf' stroke-opacity='0.4'/><line x1='21' y1='-21' x2='35' y2='-35' stroke='%2345d4bf' stroke-opacity='0.4'/><line x1='-21' y1='21' x2='-35' y2='35' stroke='%2345d4bf' stroke-opacity='0.4'/><line x1='21' y1='21' x2='35' y2='35' stroke='%2345d4bf' stroke-opacity='0.4'/><circle cx='0' cy='0' r='6' stroke='%23f59e0b' stroke-opacity='0.6'/><circle cx='0' cy='0' r='2' fill='%23f59e0b' fill-opacity='0.5'/></g></svg>")`,
        },
        tribal: {
            backgroundColor: '#0a1628',
            backgroundImage: `url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='80' height='40' viewBox='0 0 80 40'><g fill='none' stroke-width='1'><polyline points='0,10 10,4 20,10 30,4 40,10 50,4 60,10 70,4 80,10' stroke='%2345d4bf' stroke-opacity='0.4'/><polyline points='0,20 10,14 20,20 30,14 40,20 50,14 60,20 70,14 80,20' stroke='%23f59e0b' stroke-opacity='0.35'/><polyline points='0,30 10,24 20,30 30,24 40,30 50,24 60,30 70,24 80,30' stroke='%2345d4bf' stroke-opacity='0.4'/></g></svg>")`,
        },
        boldstripes: {
            backgroundColor: '#0a1628',
            backgroundImage: `repeating-linear-gradient(90deg, transparent 0 56px, rgba(255,255,255,0.09) 56px 60px)`,
        },
        thickdiag: {
            backgroundColor: '#0a1628',
            backgroundImage: `repeating-linear-gradient(45deg, transparent 0 32px, rgba(255,255,255,0.08) 32px 36px)`,
        },
        arcs: {
            backgroundColor: '#0a1628',
            backgroundImage: `url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='160' viewBox='0 0 160 160'><g fill='none' stroke='%23ffffff' stroke-opacity='0.1' stroke-width='3'><circle cx='0' cy='160' r='40'/><circle cx='0' cy='160' r='80'/><circle cx='0' cy='160' r='120'/><circle cx='160' cy='0' r='40'/><circle cx='160' cy='0' r='80'/><circle cx='160' cy='0' r='120'/></g></svg>")`,
        },
        chevron: {
            backgroundColor: '#0a1628',
            backgroundImage: `url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='80' height='40' viewBox='0 0 80 40'><polyline points='0,30 40,10 80,30' fill='none' stroke='%23ffffff' stroke-opacity='0.1' stroke-width='3'/></svg>")`,
        },
        heavygrid: {
            backgroundColor: '#0a1628',
            backgroundImage: `repeating-linear-gradient(0deg, transparent 0 76px, rgba(255,255,255,0.09) 76px 80px), repeating-linear-gradient(90deg, transparent 0 76px, rgba(255,255,255,0.09) 76px 80px)`,
        },
        wavecue: {
            backgroundColor: '#0a1628',
            backgroundImage: `url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='80' viewBox='0 0 160 80'><path d='M0 40 Q 40 12 80 40 T 160 40' fill='none' stroke='%23ffffff' stroke-opacity='0.18' stroke-width='2.5'/><line x1='40' y1='8' x2='40' y2='72' stroke='%23ffffff' stroke-opacity='0.12' stroke-width='2'/><circle cx='40' cy='12' r='3' fill='%23f59e0b' fill-opacity='0.7'/><line x1='120' y1='8' x2='120' y2='72' stroke='%23ffffff' stroke-opacity='0.12' stroke-width='2'/><circle cx='120' cy='68' r='3' fill='%23f59e0b' fill-opacity='0.7'/></svg>")`,
        },
        pulsecue: {
            backgroundColor: '#0a1628',
            backgroundImage: `url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='80' viewBox='0 0 160 80'><path d='M0 50 H40 V30 H80 V50 H120 V30 H160' fill='none' stroke='%23ffffff' stroke-opacity='0.2' stroke-width='2.5'/><line x1='40' y1='10' x2='40' y2='70' stroke='%23ffffff' stroke-opacity='0.1' stroke-width='2'/><circle cx='40' cy='40' r='3.5' fill='%23f59e0b' fill-opacity='0.7'/><line x1='120' y1='10' x2='120' y2='70' stroke='%23ffffff' stroke-opacity='0.1' stroke-width='2'/><circle cx='120' cy='40' r='3.5' fill='%23f59e0b' fill-opacity='0.7'/></svg>")`,
        },
        waveseg: {
            backgroundColor: '#0a1628',
            backgroundImage: `url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='200' height='80' viewBox='0 0 200 80'><path d='M0 40 Q 25 20 50 40' fill='none' stroke='%23ffffff' stroke-opacity='0.18' stroke-width='2.5'/><path d='M70 40 Q 95 60 120 40 T 170 40' fill='none' stroke='%23ffffff' stroke-opacity='0.18' stroke-width='2.5'/><line x1='60' y1='12' x2='60' y2='68' stroke='%23f59e0b' stroke-opacity='0.55' stroke-width='2'/><line x1='180' y1='12' x2='180' y2='68' stroke='%23ffffff' stroke-opacity='0.15' stroke-width='2'/></svg>")`,
        },
        doublewave: {
            backgroundColor: '#0a1628',
            backgroundImage: `url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='80' viewBox='0 0 160 80'><path d='M0 32 Q 40 8 80 32 T 160 32' fill='none' stroke='%23ffffff' stroke-opacity='0.18' stroke-width='2.5'/><path d='M0 56 Q 40 80 80 56 T 160 56' fill='none' stroke='%23ffffff' stroke-opacity='0.1' stroke-width='2.5'/><circle cx='40' cy='8' r='3' fill='%23f59e0b' fill-opacity='0.7'/><circle cx='120' cy='80' r='3' fill='%23f59e0b' fill-opacity='0.5'/></svg>")`,
        },
        stepwave: {
            backgroundColor: '#0a1628',
            backgroundImage: `url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='80' viewBox='0 0 160 80'><path d='M0 56 H20 V44 H40 V32 H60 V20 H80 V32 H100 V44 H120 V56 H160' fill='none' stroke='%23ffffff' stroke-opacity='0.2' stroke-width='2.5'/><line x1='80' y1='6' x2='80' y2='74' stroke='%23ffffff' stroke-opacity='0.1' stroke-width='2'/><circle cx='80' cy='20' r='3.5' fill='%23f59e0b' fill-opacity='0.75'/></svg>")`,
        },
        notes: {
            backgroundColor: '#0a1628',
            backgroundImage: `url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='160' height='80' viewBox='0 0 160 80'><g stroke='%2345d4bf' stroke-opacity='0.18' stroke-width='0.6'><line x1='0' y1='20' x2='160' y2='20'/><line x1='0' y1='30' x2='160' y2='30'/><line x1='0' y1='40' x2='160' y2='40'/><line x1='0' y1='50' x2='160' y2='50'/><line x1='0' y1='60' x2='160' y2='60'/></g><g fill='%23f59e0b' fill-opacity='0.55'><ellipse cx='25' cy='50' rx='3' ry='2.2' transform='rotate(-20 25 50)'/><rect x='27.5' y='32' width='0.8' height='18' fill='%23f59e0b' fill-opacity='0.55'/><path d='M28 32 Q34 36 32 44' fill='none' stroke='%23f59e0b' stroke-opacity='0.55' stroke-width='0.8'/></g><g fill='%2345d4bf' fill-opacity='0.5'><ellipse cx='90' cy='40' rx='3' ry='2.2' transform='rotate(-20 90 40)'/><rect x='92.5' y='22' width='0.8' height='18' fill='%2345d4bf' fill-opacity='0.5'/><path d='M93 22 Q99 26 97 34' fill='none' stroke='%2345d4bf' stroke-opacity='0.5' stroke-width='0.8'/></g><g fill='%23f59e0b' fill-opacity='0.4'><ellipse cx='130' cy='55' rx='3' ry='2.2' transform='rotate(-20 130 55)'/><rect x='132.5' y='37' width='0.8' height='18' fill='%23f59e0b' fill-opacity='0.4'/></g></svg>")`,
        },
    };

    return (
        <div className="max-w-4xl mx-auto">
            <div className="mb-6">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-amber2">Background Theme</span>
                <h1 className="text-[28px] font-bold tracking-tight mt-1">{bg?.name}</h1>
                <p className="text-[13px] text-ink-muted mt-1">{bg?.desc}</p>
            </div>
            <div className="rounded-mx-lg overflow-hidden border border-line-subtle h-80 relative" style={bgStyles[id]}>
                <div className="absolute inset-0 flex items-center justify-center">
                    <div className="text-center">
                        <div className="flex items-end gap-[2px] justify-center mb-3">
                            {[14, 18, 22, 16, 10].map((h, i) => (
                                <div key={i} className="bg-amber2/60 rounded-[1.5px]" style={{ width: 3, height: h }} />
                            ))}
                        </div>
                        <span className="text-[13px] font-semibold text-ink-primary/60">LibraryManagementSystem</span>
                    </div>
                </div>
            </div>
            <div className="mt-4 flex items-center gap-3">
                <button
                    onClick={() => onApply(id)}
                    className={isActive ? 'btn-secondary flex items-center gap-2' : 'btn-primary flex items-center gap-2'}
                >
                    {isActive ? <><Check size={14} /> Active</> : <><Sparkles size={14} /> Use This Background</>}
                </button>
                {isActive && <span className="text-[10px] text-ok">Currently active</span>}
            </div>
        </div>
    );
};

export default DesignView;
