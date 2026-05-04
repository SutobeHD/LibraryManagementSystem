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
    { id: 'vinyl', name: 'Vinyl Grooves', desc: 'Dark abstract record grooves' },
    { id: 'grid', name: 'DAW Grid', desc: 'Minimal dark grid pattern' },
    { id: 'bokeh', name: 'Bokeh Lights', desc: 'Blurred LED mixer lights' },
    { id: 'waveform', name: 'Audio Waveform', desc: 'Subtle waveform watermark' },
    { id: 'mesh', name: 'Mesh Gradient', desc: 'Turquoise/dark blue gradient' },
];

const DesignView = () => {
    const [activeSection, setActiveSection] = useState('mockup');
    const [activeMockup, setActiveMockup] = useState('stems');
    const [activeBackground, setActiveBackground] = useState('mesh');
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
    const bgStyles = {
        vinyl: { background: 'radial-gradient(circle at 50% 50%, #1a1a1a 0%, #0a0a0a 30%, #111 31%, #0a0a0a 60%, #111 61%, #0a0a0a 100%)' },
        grid: { backgroundImage: 'repeating-linear-gradient(0deg, transparent, transparent 39px, rgba(255,255,255,0.03) 39px, rgba(255,255,255,0.03) 40px), repeating-linear-gradient(90deg, transparent, transparent 39px, rgba(255,255,255,0.03) 39px, rgba(255,255,255,0.03) 40px)', background: '#0a0a0a' },
        bokeh: { background: 'radial-gradient(ellipse at 20% 50%, rgba(45,212,191,0.08) 0%, transparent 50%), radial-gradient(ellipse at 80% 30%, rgba(245,158,11,0.06) 0%, transparent 40%), radial-gradient(ellipse at 60% 80%, rgba(129,140,248,0.05) 0%, transparent 45%), #0a0a0a' },
        waveform: { backgroundImage: 'url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' width=\'400\' height=\'100\' viewBox=\'0 0 400 100\'%3E%3Cpath d=\'M0,50 C50,20 100,80 150,50 C200,20 250,80 300,50 C350,20 400,80 400,50\' stroke=\'rgba(255,255,255,0.03)\' fill=\'none\' stroke-width=\'1\'/%3E%3C/svg%3E")', backgroundRepeat: 'repeat', backgroundColor: '#0a0a0a' },
        mesh: { background: 'conic-gradient(from 180deg at 50% 50%, #0a1628 0deg, #0d1f3c 90deg, #091a2a 180deg, #0b1e35 270deg, #0a1628 360deg)' },
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
                        <span className="text-[13px] font-semibold text-ink-primary/60">RB Editor Pro</span>
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
