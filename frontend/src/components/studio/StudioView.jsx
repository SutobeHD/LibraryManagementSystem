/**
 * StudioView — efficiency-focused DJ editor screen (Melodex design handoff).
 *
 * A dense single-track editor: large section-colored master waveform, overview
 * minimap, 16 hot-cue pads, beat-nav + loop controls, and a tight track table
 * with inline waveform previews. Self-contained and presentational — it ships
 * with the design's sample catalogue (see studioData.js).
 */
import React from 'react';
import {
    STUDIO_THEME as T,
    SECTIONS,
    SECTION_COLORS,
    HOT_CUES,
    STUDIO_TRACKS as TRACKS,
    STUDIO_PLAYLISTS as PLAYLISTS,
    keyColor as kc,
    fmt,
    hexA,
} from './studioData';
import { drawMasterWave, drawMiniWave, drawRowWave } from './studioWaveform';

// ─── Canvas wrappers ─────────────────────────────────────────────────────────
function MasterWave({ seed, playhead, height }) {
    const ref = React.useRef(null);
    const live = React.useRef({ seed, playhead, height });
    live.current = { seed, playhead, height };
    React.useEffect(() => {
        drawMasterWave(ref.current, seed, playhead, height);
    }, [seed, playhead, height]);
    React.useEffect(() => {
        const el = ref.current?.parentElement;
        if (!el) return undefined;
        const ro = new ResizeObserver(() => {
            const p = live.current;
            drawMasterWave(ref.current, p.seed, p.playhead, p.height);
        });
        ro.observe(el);
        return () => ro.disconnect();
    }, []);
    return <canvas ref={ref} style={{ display: 'block', width: '100%', height }} />;
}

function MiniWave({ seed, playhead, height }) {
    const ref = React.useRef(null);
    const live = React.useRef({ seed, playhead, height });
    live.current = { seed, playhead, height };
    React.useEffect(() => {
        drawMiniWave(ref.current, seed, playhead, height);
    }, [seed, playhead, height]);
    React.useEffect(() => {
        const el = ref.current?.parentElement;
        if (!el) return undefined;
        const ro = new ResizeObserver(() => {
            const p = live.current;
            drawMiniWave(ref.current, p.seed, p.playhead, p.height);
        });
        ro.observe(el);
        return () => ro.disconnect();
    }, []);
    return <canvas ref={ref} style={{ display: 'block', width: '100%', height }} />;
}

function RowWave({ seed, playhead = 0, width = 170, height = 26 }) {
    const ref = React.useRef(null);
    React.useEffect(() => {
        drawRowWave(ref.current, seed, playhead, width, height);
    }, [seed, playhead, width, height]);
    return <canvas ref={ref} style={{ display: 'block' }} />;
}

// ─── Icons ───────────────────────────────────────────────────────────────────
const I = {
    play: (s = 11) => <svg width={s} height={s} viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3" /></svg>,
    pause: (s = 11) => <svg width={s} height={s} viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16" /><rect x="14" y="4" width="4" height="16" /></svg>,
    search: (s = 11) => <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" /></svg>,
    triR: (s = 8) => <svg width={s} height={s} viewBox="0 0 24 24" fill="currentColor"><polygon points="8 5 19 12 8 19 8 5" /></svg>,
    triD: (s = 8) => <svg width={s} height={s} viewBox="0 0 24 24" fill="currentColor"><polygon points="5 8 19 8 12 19 5 8" /></svg>,
    playlist: (s = 12) => <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="3" y1="6" x2="14" y2="6" /><line x1="3" y1="12" x2="14" y2="12" /><line x1="3" y1="18" x2="10" y2="18" /><path d="M21 7v9.5a2.5 2.5 0 1 1-2.5-2.5 2.5 2.5 0 0 1 2.5 2.5" fill="currentColor" stroke="none" /></svg>,
    sparkles: (s = 12) => <svg width={s} height={s} viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l1.3 3.7L17 7l-3.7 1.3L12 12l-1.3-3.7L7 7l3.7-1.3z" /><path d="M19 13l.8 2.2 2.2.8-2.2.8L19 19l-.8-2.2-2.2-.8 2.2-.8z" /><path d="M5 15l.7 1.9 1.9.7-1.9.7L5 20.2l-.7-1.9-1.9-.7 1.9-.7z" /></svg>,
    folderO: (s = 12, c = 'currentColor') => <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke={c} strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z" /></svg>,
    plus: (s = 10) => <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>,
    lock: (s = 11) => <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><rect x="3" y="11" width="18" height="11" rx="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></svg>,
};

/** Three staggered equalizer bars — playing indicator. */
function Bars() {
    return (
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: 1.5, height: 11 }}>
            {[3, 10, 6].map((h, i) => (
                <div
                    key={i}
                    style={{
                        width: 2,
                        height: h,
                        borderRadius: 1,
                        background: T.green,
                        transformOrigin: 'bottom',
                        animation: `barBounce .85s ${i * 0.18}s ease-in-out infinite alternate`,
                    }}
                />
            ))}
        </div>
    );
}

// ═══ SIDEBAR (playlists) ═════════════════════════════════════════════════════
function PlaylistRow({ p, indent = 10, active, onClick, accent = false }) {
    const [hov, setHov] = React.useState(false);
    const isSmart = !!p.smart;
    const iconColor = accent || active ? T.amber : isSmart ? T.purple : T.text2;
    const labelColor = active
        ? T.amber
        : accent || p.active || isSmart
          ? T.text0
          : hov
            ? T.text0
            : T.text1;
    return (
        <div
            onClick={onClick}
            onMouseEnter={() => setHov(true)}
            onMouseLeave={() => setHov(false)}
            style={{
                display: 'flex',
                alignItems: 'center',
                height: 23,
                paddingLeft: indent,
                paddingRight: 8,
                gap: 6,
                cursor: 'pointer',
                background: active ? T.amberBg : hov ? 'rgba(255,255,255,0.025)' : 'transparent',
                borderLeft: active ? `2px solid ${T.amber}` : '2px solid transparent',
            }}
        >
            <span
                style={{
                    color: iconColor,
                    display: 'flex',
                    flexShrink: 0,
                    opacity: p.active || active || isSmart ? 1 : 0.85,
                }}
            >
                {isSmart ? I.sparkles(12) : I.playlist(12)}
            </span>
            <span
                style={{
                    flex: 1,
                    fontSize: 11,
                    fontWeight: active || p.active || isSmart ? 600 : 400,
                    color: labelColor,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                }}
            >
                {p.label}
            </span>
            {isSmart && (
                <span
                    style={{
                        fontFamily: 'JetBrains Mono, monospace',
                        fontSize: 8,
                        fontWeight: 700,
                        letterSpacing: '.12em',
                        color: T.purple,
                        marginRight: 4,
                    }}
                >
                    SMART
                </span>
            )}
            {p.count != null && (
                <span
                    style={{
                        fontFamily: 'JetBrains Mono, monospace',
                        fontSize: 9,
                        color: active ? T.amberD : T.text3,
                    }}
                >
                    {p.count}
                </span>
            )}
        </div>
    );
}

function StudioSidebar({ active, setActive, collapsed, setCollapsed }) {
    const [open, setOpen] = React.useState({
        'Full Playlists': true,
        'Show Playlists': true,
        Archive: false,
    });

    if (collapsed) {
        return (
            <div
                style={{
                    width: 36,
                    height: '100%',
                    background: T.bg1,
                    borderRight: `1px solid ${T.border}`,
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    padding: '8px 0',
                    gap: 6,
                    flexShrink: 0,
                }}
            >
                <button
                    onClick={() => setCollapsed(false)}
                    title="Expand"
                    style={{ width: 24, height: 24, display: 'flex', alignItems: 'center', justifyContent: 'center', color: T.text2, borderRadius: 3 }}
                >
                    {I.triR(10)}
                </button>
                <div style={{ flex: 1 }} />
                <div
                    style={{
                        writingMode: 'vertical-rl',
                        transform: 'rotate(180deg)',
                        fontSize: 10,
                        fontWeight: 700,
                        letterSpacing: '.2em',
                        color: T.text3,
                        textTransform: 'uppercase',
                    }}
                >
                    Playlists · 24
                </div>
            </div>
        );
    }

    let lastHeader = '';
    return (
        <div
            style={{
                width: 240,
                height: '100%',
                background: T.bg1,
                borderRight: `1px solid ${T.border}`,
                display: 'flex',
                flexDirection: 'column',
                flexShrink: 0,
                userSelect: 'none',
            }}
        >
            {/* Editor-header strip (Blender-style lighter header) */}
            <div
                style={{
                    height: 26,
                    background: T.bg2,
                    borderBottom: `1px solid ${T.border}`,
                    display: 'flex',
                    alignItems: 'center',
                    padding: '0 8px',
                    gap: 6,
                    flexShrink: 0,
                }}
            >
                <div
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 4,
                        height: 18,
                        padding: '0 6px',
                        background: T.bg3,
                        border: `1px solid ${T.border2}`,
                        borderRadius: 2,
                    }}
                >
                    <span style={{ color: T.amber, display: 'flex' }}>{I.playlist(11)}</span>
                    <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 9.5, color: T.text1, fontWeight: 600, letterSpacing: 0.3 }}>
                        Playlists
                    </span>
                    <span style={{ color: T.text2, marginLeft: 2, display: 'flex' }}>{I.triD(7)}</span>
                </div>
                <div style={{ flex: 1 }} />
                <button onClick={() => setCollapsed(true)} title="Collapse" style={{ color: T.text2, padding: 2, display: 'flex', transform: 'rotate(180deg)' }}>
                    {I.triR(9)}
                </button>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', padding: '6px 10px', gap: 6, flexShrink: 0 }}>
                <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: '.1em', color: T.text2, textTransform: 'uppercase' }}>
                    Playlists
                </span>
                <div style={{ flex: 1 }} />
                <button style={{ color: T.text2, padding: 2, display: 'flex', alignItems: 'center' }} title="New folder">
                    {I.folderO(11, T.text2)}
                </button>
                <button style={{ color: T.text2, padding: 2, display: 'flex', alignItems: 'center' }} title="New playlist">
                    {I.plus(10)}
                </button>
            </div>

            <div style={{ flex: 1, overflowY: 'auto' }}>
                <PlaylistRow p={PLAYLISTS[0]} indent={6} active={active === PLAYLISTS[0].id} onClick={() => setActive(PLAYLISTS[0].id)} accent />
                {PLAYLISTS.slice(1).map((p) => {
                    if (p.type === 'header') {
                        lastHeader = p.label;
                        return (
                            <div
                                key={p.id}
                                onClick={() => setOpen((o) => ({ ...o, [p.label]: !o[p.label] }))}
                                style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '7px 8px 4px', cursor: 'pointer' }}
                            >
                                <span style={{ color: T.text2, display: 'flex' }}>{open[p.label] ? I.triD(7) : I.triR(7)}</span>
                                <span style={{ color: T.amber, display: 'flex', marginLeft: 1 }}>{I.folderO(12, T.amber)}</span>
                                <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 9.5, fontWeight: 700, color: T.text1, letterSpacing: '.12em', textTransform: 'uppercase' }}>
                                    {p.label}
                                </span>
                            </div>
                        );
                    }
                    if (!open[lastHeader]) return null;
                    return <PlaylistRow key={p.id} p={p} indent={22} active={active === p.id} onClick={() => setActive(p.id)} />;
                })}
                <div style={{ height: 30 }} />
            </div>

            {/* Sidebar search */}
            <div style={{ padding: '6px 8px', borderTop: `1px solid ${T.border}`, background: T.bg1, flexShrink: 0 }}>
                <div
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 6,
                        background: T.bg3,
                        border: `1px solid ${T.border2}`,
                        borderRadius: 3,
                        padding: '3px 8px',
                        height: 24,
                    }}
                >
                    <span style={{ fontSize: 8, fontWeight: 700, color: T.text2, letterSpacing: '.1em' }}>SEARCH:</span>
                    <input
                        placeholder="search tracks in playlist"
                        style={{ background: 'none', border: 'none', outline: 'none', fontSize: 10.5, color: T.text1, flex: 1, fontFamily: 'DM Sans, sans-serif' }}
                    />
                    <span style={{ color: T.amber, display: 'flex' }}>{I.search(10)}</span>
                </div>
            </div>
        </div>
    );
}

// ═══ TOP BAR ═════════════════════════════════════════════════════════════════
function SliderCtl({ label, value, accent = false, width = 80 }) {
    const [v, setV] = React.useState(value);
    return (
        <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <span style={{ fontSize: 8, fontWeight: 700, color: T.text2, letterSpacing: '.12em' }}>{label}</span>
            <div style={{ position: 'relative', width, height: 14, display: 'flex', alignItems: 'center' }}>
                <div style={{ position: 'absolute', left: 0, right: 0, top: '50%', transform: 'translateY(-50%)', height: 3, background: T.bg3, borderRadius: 2, border: `1px solid ${T.border2}` }} />
                <div
                    style={{
                        position: 'absolute',
                        left: 0,
                        top: '50%',
                        transform: 'translateY(-50%)',
                        height: 3,
                        width: `${v * 100}%`,
                        background: accent ? T.amber : T.text1,
                        borderRadius: 2,
                        boxShadow: accent ? `0 0 6px ${T.amberGl}` : 'none',
                    }}
                />
                <div
                    style={{
                        position: 'absolute',
                        left: `${v * 100}%`,
                        top: '50%',
                        transform: 'translate(-50%,-50%)',
                        width: 9,
                        height: 9,
                        borderRadius: '50%',
                        background: accent ? T.amberL : T.text1,
                        border: `1px solid ${T.bg0}`,
                        pointerEvents: 'none',
                    }}
                />
                <input
                    type="range"
                    min="0"
                    max="1"
                    step="0.01"
                    value={v}
                    onChange={(e) => setV(parseFloat(e.target.value))}
                    style={{ position: 'absolute', inset: 0, width: '100%', height: 14, opacity: 0, cursor: 'pointer', margin: 0, padding: 0 }}
                />
            </div>
            {!accent && (
                <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 9, color: T.text2, minWidth: 18, textAlign: 'right' }}>
                    {Math.round(v * 100)}
                </span>
            )}
        </div>
    );
}

function StatChip({ label, value, color }) {
    return (
        <div
            style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                padding: '2px 10px',
                background: T.bg3,
                border: `1px solid ${T.border2}`,
                borderRadius: 3,
            }}
        >
            <span style={{ fontSize: 8, fontWeight: 700, color: T.text2, letterSpacing: '.12em' }}>{label}</span>
            <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 13, fontWeight: 700, color, lineHeight: 1 }}>{value}</span>
        </div>
    );
}

function TopBar({ track, playing, setPlaying, bpm }) {
    return (
        <div
            style={{
                height: 42,
                background: T.bg2,
                borderBottom: `1px solid ${T.border}`,
                display: 'flex',
                alignItems: 'center',
                padding: '0 12px',
                gap: 14,
                flexShrink: 0,
                minWidth: 1180,
            }}
        >
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 220, flexShrink: 0 }}>
                <button
                    onClick={() => setPlaying((p) => !p)}
                    style={{
                        width: 28,
                        height: 28,
                        borderRadius: '50%',
                        background: playing ? T.amber : T.bg4,
                        color: playing ? T.bg0 : T.text0,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        flexShrink: 0,
                        boxShadow: playing ? `0 0 12px ${T.amberGl}` : 'none',
                    }}
                >
                    {playing ? I.pause(12) : I.play(11)}
                </button>
                <div style={{ minWidth: 0, maxWidth: 220 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <span style={{ fontSize: 12, fontWeight: 600, color: T.text0, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                            {track.Title}
                        </span>
                        {playing && <Bars />}
                    </div>
                    <div style={{ fontSize: 10, color: T.text2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', marginTop: 1 }}>
                        {track.Artist}
                    </div>
                </div>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
                <StatChip label="BPM" value={bpm.toFixed(2)} color={T.amber} />
                <StatChip label="KEY" value={track.Key} color={kc(track.Key)} />
                <StatChip label="TIME" value={fmt(track.TotalTime)} color={T.text1} />
                <StatChip label="FMT" value={`${track.fmt}·${track.bitrate}`} color={T.text1} />
            </div>

            <div style={{ flex: 1 }} />

            <div style={{ display: 'flex', alignItems: 'center', gap: 14, flexShrink: 0 }}>
                <SliderCtl label="VOL" value={0.78} />
                <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                    <span style={{ fontSize: 8, fontWeight: 700, color: T.text2, letterSpacing: '.12em' }}>CUE OUTPUT</span>
                    <div
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: 4,
                            height: 18,
                            padding: '0 6px',
                            background: T.bg3,
                            border: `1px solid ${T.border2}`,
                            borderRadius: 2,
                            cursor: 'pointer',
                        }}
                    >
                        <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 10, color: T.text1, fontWeight: 600 }}>OUT 1/2</span>
                        <span style={{ color: T.text2, display: 'flex' }}>{I.triD(7)}</span>
                    </div>
                </div>
                <SliderCtl label="ZOOM" value={0.55} accent width={70} />
                <button title="Lock view" style={{ color: T.text2, padding: 4, display: 'flex' }}>{I.lock(13)}</button>
            </div>
        </div>
    );
}

// ═══ WAVEFORM PANEL ══════════════════════════════════════════════════════════
function CuePad({ c }) {
    if (!c.set) {
        return (
            <button
                style={{
                    height: 30,
                    background: T.bg3,
                    border: `1px dashed ${T.border3}`,
                    borderRadius: 2,
                    color: T.text3,
                    fontFamily: 'JetBrains Mono, monospace',
                    fontSize: 9,
                    fontWeight: 700,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                }}
            >
                <span style={{ fontSize: 9, opacity: 0.7 }}>{c.n}</span>
            </button>
        );
    }
    const col = SECTION_COLORS[c.ci];
    return (
        <button
            style={{
                height: 30,
                background: hexA(col, 0.16),
                border: `1px solid ${hexA(col, 0.55)}`,
                borderRadius: 2,
                color: col,
                fontFamily: 'JetBrains Mono, monospace',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                padding: '0 2px',
                lineHeight: 1.1,
                boxShadow: `inset 0 -2px 0 ${hexA(col, 0.4)}`,
            }}
        >
            <span style={{ fontSize: 8, fontWeight: 700, letterSpacing: '.04em', opacity: 0.85 }}>{c.n}</span>
            <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: '.02em' }}>{c.label}</span>
        </button>
    );
}

const NAV_BTNS = [
    { l: 'GRID', w: 78 },
    { l: '⇤', tip: 'previous cue', w: 32 },
    { l: '⇥', tip: 'next cue', w: 32 },
    { l: '− BAR', w: 64 },
    { l: '+ BAR', w: 64 },
    { l: '− BEAT', w: 64 },
    { l: '+ BEAT', w: 64 },
];
const LOOP_OPS = ['IN', 'OUT', '÷2', '×2', 'RELOOP'];
const LOOP_BARS = ['1/4', '1/2', '1', '2', '4', '8', '16', '32'];

function WaveformPanel({ track, playing, playhead, setPlayhead }) {
    const seek = (e) => {
        const r = e.currentTarget.getBoundingClientRect();
        setPlayhead(Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)));
    };
    return (
        <div style={{ flexShrink: 0, background: T.bg1, borderBottom: `1px solid ${T.border}` }}>
            {/* Master waveform */}
            <div
                style={{ height: 152, background: T.bg0, borderBottom: `1px solid ${T.border}`, position: 'relative', cursor: 'crosshair' }}
                onClick={seek}
            >
                <MasterWave seed={track.seed} playhead={playhead} height={152} />
                <div style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}>
                    {SECTIONS.map((s, i) => {
                        const lx = (((s.start + s.end) / 2 / 128) * 100).toFixed(3);
                        return (
                            <div
                                key={i}
                                style={{
                                    position: 'absolute',
                                    left: `${lx}%`,
                                    bottom: 6,
                                    transform: 'translateX(-50%)',
                                    padding: '1px 6px',
                                    background: 'rgba(8,9,12,0.7)',
                                    border: `1px solid ${hexA(SECTION_COLORS[s.ci], 0.55)}`,
                                    borderRadius: 2,
                                    fontSize: 8.5,
                                    fontWeight: 700,
                                    letterSpacing: '.08em',
                                    color: SECTION_COLORS[s.ci],
                                    textTransform: 'uppercase',
                                    whiteSpace: 'nowrap',
                                }}
                            >
                                {s.label}
                            </div>
                        );
                    })}
                </div>
            </div>

            {/* Minimap overview */}
            <div style={{ height: 30, background: T.bg0, borderBottom: `1px solid ${T.border}`, display: 'flex' }}>
                <div style={{ flex: 1, position: 'relative', cursor: 'pointer' }} onClick={seek}>
                    <MiniWave seed={track.seed} playhead={playhead} height={30} />
                    <div
                        style={{
                            position: 'absolute',
                            top: 0,
                            bottom: 0,
                            left: `${Math.max(0, playhead * 100 - 12)}%`,
                            width: '24%',
                            border: `1px solid ${T.amberL}`,
                            background: 'rgba(255,202,106,0.10)',
                            pointerEvents: 'none',
                        }}
                    />
                </div>
                <div
                    style={{ width: 38, background: T.bg2, borderLeft: `1px solid ${T.border}`, display: 'flex', alignItems: 'center', justifyContent: 'center', color: T.text2, cursor: 'pointer' }}
                    title="Lock view"
                >
                    {I.lock(11)}
                </div>
            </div>

            {/* Cue pad row */}
            <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', background: T.bg1 }}>
                <div style={{ padding: '6px 8px', borderRight: `1px solid ${T.border}`, display: 'flex', alignItems: 'center', gap: 4 }}>
                    <button
                        style={{
                            width: 24,
                            height: 22,
                            borderRadius: 3,
                            background: playing ? T.amber : T.bg3,
                            color: playing ? T.bg0 : T.text1,
                            border: `1px solid ${playing ? T.amber : T.border2}`,
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                        }}
                    >
                        {playing ? I.pause(10) : I.play(10)}
                    </button>
                </div>
                <div style={{ padding: '6px 8px', display: 'grid', gridTemplateColumns: 'repeat(16, 1fr)', gap: 4 }}>
                    {HOT_CUES.map((c) => (
                        <CuePad key={c.n} c={c} />
                    ))}
                </div>
            </div>

            {/* Beat nav + loop controls */}
            <div style={{ display: 'flex', alignItems: 'center', padding: '4px 6px 6px', gap: 4, borderTop: `1px solid ${T.border}`, background: T.bg1, flexWrap: 'wrap' }}>
                {NAV_BTNS.map((b, i) => (
                    <button
                        key={i}
                        title={b.tip}
                        style={{
                            height: 24,
                            minWidth: b.w,
                            padding: '0 8px',
                            background: T.bg3,
                            border: `1px solid ${T.border2}`,
                            borderRadius: 2,
                            fontFamily: 'JetBrains Mono, monospace',
                            fontSize: 10,
                            fontWeight: 600,
                            color: T.text1,
                            letterSpacing: '.04em',
                        }}
                    >
                        {b.l}
                    </button>
                ))}
                <div style={{ flex: 1 }} />

                {/* Loop op cluster */}
                <div style={{ display: 'flex', alignItems: 'center', height: 24, background: T.bg3, border: `1px solid ${T.border2}`, borderRadius: 2, overflow: 'hidden', marginRight: 6 }}>
                    {LOOP_OPS.map((op, i) => (
                        <button
                            key={op}
                            style={{
                                height: '100%',
                                padding: '0 8px',
                                fontFamily: 'JetBrains Mono, monospace',
                                fontSize: 10,
                                fontWeight: 700,
                                color: T.text1,
                                letterSpacing: '.04em',
                                borderRight: i < LOOP_OPS.length - 1 ? `1px solid ${T.border2}` : 'none',
                            }}
                        >
                            {op}
                        </button>
                    ))}
                </div>

                {/* Bar-length segmented picker */}
                <div style={{ display: 'flex', alignItems: 'center', height: 24, background: T.bg3, border: `1px solid ${T.border2}`, borderRadius: 2, overflow: 'hidden', marginRight: 6 }}>
                    <span style={{ height: '100%', padding: '0 8px', display: 'flex', alignItems: 'center', fontFamily: 'JetBrains Mono, monospace', fontSize: 9, fontWeight: 700, color: T.text2, letterSpacing: '.1em', borderRight: `1px solid ${T.border2}` }}>
                        BARS
                    </span>
                    {LOOP_BARS.map((v) => {
                        const a = v === '8';
                        return (
                            <button
                                key={v}
                                title={`Loop ${v} bars`}
                                style={{
                                    height: '100%',
                                    minWidth: 26,
                                    padding: '0 6px',
                                    background: a ? 'rgba(232,92,127,0.15)' : 'transparent',
                                    borderRight: `1px solid ${T.border2}`,
                                    fontFamily: 'JetBrains Mono, monospace',
                                    fontSize: 10,
                                    fontWeight: a ? 700 : 500,
                                    color: a ? '#E85C7F' : T.text1,
                                    letterSpacing: '.02em',
                                    boxShadow: a ? 'inset 0 -2px 0 #E85C7F' : 'none',
                                }}
                            >
                                {v}
                            </button>
                        );
                    })}
                </div>

                {/* Active loop chip */}
                <button
                    style={{
                        height: 24,
                        padding: '0 10px',
                        background: 'rgba(232,92,127,0.12)',
                        border: '1px solid rgba(232,92,127,0.45)',
                        borderRadius: 2,
                        fontFamily: 'JetBrains Mono, monospace',
                        fontSize: 10,
                        fontWeight: 700,
                        color: '#E85C7F',
                        letterSpacing: '.04em',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 5,
                        marginRight: 6,
                    }}
                >
                    <span
                        className="animate-pulse"
                        style={{ width: 6, height: 6, borderRadius: '50%', background: '#E85C7F', boxShadow: '0 0 6px rgba(232,92,127,0.6)' }}
                    />
                    LOOP · 8 BARS
                </button>

                {['QUANT', 'SYNC'].map((b) => (
                    <button
                        key={b}
                        style={{
                            height: 24,
                            padding: '0 10px',
                            background: T.bg3,
                            border: `1px solid ${T.border2}`,
                            borderRadius: 2,
                            fontFamily: 'JetBrains Mono, monospace',
                            fontSize: 10,
                            fontWeight: 600,
                            color: T.text1,
                        }}
                    >
                        {b}
                    </button>
                ))}
            </div>
        </div>
    );
}

// ═══ TRACK TABLE ═════════════════════════════════════════════════════════════
const COLS = [
    { k: 'Art', label: 'Art', w: 36, sort: false },
    { k: 'Preview', label: 'Preview', w: 180, sort: false },
    { k: 'Title', label: 'Title', sort: true },
    { k: 'Artist', label: 'Artist', w: 200, sort: true },
    { k: 'BPM', label: 'BPM', w: 62, sort: true, align: 'right' },
    { k: 'Key', label: 'Key', w: 62, sort: true, align: 'center' },
    { k: 'TotalTime', label: 'Time', w: 54, sort: true, align: 'right' },
    { k: 'path', label: 'File Location', w: 430, sort: true },
];

function TrackTable({ tracks, playId, onPlay, onSelect, selectedId }) {
    const [sk, setSk] = React.useState('BPM');
    const [sd, setSd] = React.useState('asc');
    const toggle = (k) => (sk === k ? setSd((d) => (d === 'asc' ? 'desc' : 'asc')) : (setSk(k), setSd('asc')));

    const sorted = React.useMemo(() => {
        return [...tracks].sort((a, b) => {
            let av = a[sk];
            let bv = b[sk];
            if (typeof av === 'number') return sd === 'asc' ? av - bv : bv - av;
            av = String(av || '').toLowerCase();
            bv = String(bv || '').toLowerCase();
            return sd === 'asc' ? (av > bv ? 1 : -1) : av < bv ? 1 : -1;
        });
    }, [tracks, sk, sd]);

    const thBase = {
        padding: '0 8px',
        height: 24,
        fontSize: 9,
        fontWeight: 700,
        textTransform: 'uppercase',
        letterSpacing: '.09em',
        background: T.bg2,
        borderBottom: `1px solid ${T.border2}`,
        borderRight: `1px solid ${T.border}`,
        position: 'sticky',
        top: 0,
        whiteSpace: 'nowrap',
    };

    return (
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, background: T.bg0 }}>
            <div style={{ flex: 1, overflow: 'auto', minHeight: 0 }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', tableLayout: 'fixed', minWidth: 1200 }}>
                    <colgroup>
                        {COLS.map((c) => (
                            <col key={c.k} style={c.w ? { width: c.w } : undefined} />
                        ))}
                    </colgroup>
                    <thead>
                        <tr>
                            {COLS.map((c) => (
                                <th
                                    key={c.k}
                                    onClick={c.sort ? () => toggle(c.k) : undefined}
                                    style={{
                                        ...thBase,
                                        textAlign: c.align || 'left',
                                        color: c.sort && sk === c.k ? T.amber : T.text2,
                                        cursor: c.sort ? 'pointer' : 'default',
                                        userSelect: 'none',
                                    }}
                                >
                                    {c.label}
                                    {c.sort && sk === c.k && (
                                        <span style={{ marginLeft: 3, fontSize: 8, color: T.amber }}>{sd === 'asc' ? '▲' : '▼'}</span>
                                    )}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {sorted.map((t, i) => {
                            const isSel = selectedId === t.id;
                            const isPlay = playId === t.id;
                            const restBg = i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.012)';
                            return (
                                <tr
                                    key={t.id}
                                    onClick={() => onSelect(t)}
                                    onDoubleClick={() => onPlay(t)}
                                    style={{
                                        background: isSel ? T.amberBg : restBg,
                                        borderBottom: `1px solid ${T.border}`,
                                        cursor: 'pointer',
                                        height: 32,
                                    }}
                                    onMouseEnter={(e) => {
                                        if (!isSel) e.currentTarget.style.background = 'rgba(255,255,255,0.035)';
                                    }}
                                    onMouseLeave={(e) => {
                                        if (!isSel) e.currentTarget.style.background = restBg;
                                    }}
                                >
                                    <td style={{ padding: '2px 4px', borderRight: `1px solid ${T.border}` }}>
                                        <div
                                            style={{
                                                width: 28,
                                                height: 28,
                                                background: T.bg3,
                                                border: `1px solid ${T.border2}`,
                                                borderRadius: 2,
                                                display: 'flex',
                                                alignItems: 'center',
                                                justifyContent: 'center',
                                                color: T.text3,
                                                fontFamily: 'JetBrains Mono, monospace',
                                                fontSize: 8,
                                                fontWeight: 700,
                                            }}
                                        >
                                            {isPlay ? <Bars /> : t.Title.slice(0, 2).toUpperCase()}
                                        </div>
                                    </td>
                                    <td style={{ padding: '2px 4px', borderRight: `1px solid ${T.border}`, overflow: 'hidden' }}>
                                        <RowWave seed={t.seed} playhead={isSel && isPlay ? 0.34 : 0} width={170} height={26} />
                                    </td>
                                    <td
                                        style={{
                                            padding: '0 8px',
                                            fontSize: 11,
                                            fontWeight: isSel ? 600 : 500,
                                            color: isSel ? T.amber : T.text0,
                                            overflow: 'hidden',
                                            textOverflow: 'ellipsis',
                                            whiteSpace: 'nowrap',
                                            borderRight: `1px solid ${T.border}`,
                                        }}
                                    >
                                        {t.Title}
                                    </td>
                                    <td style={{ padding: '0 8px', fontSize: 11, color: T.text1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', borderRight: `1px solid ${T.border}` }}>
                                        {t.Artist}
                                    </td>
                                    <td style={{ padding: '0 8px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', fontSize: 11, color: T.amber, fontWeight: 600, borderRight: `1px solid ${T.border}` }}>
                                        {t.BPM?.toFixed(1)}
                                    </td>
                                    <td style={{ padding: '0 4px', textAlign: 'center', borderRight: `1px solid ${T.border}` }}>
                                        <span
                                            style={{
                                                display: 'inline-block',
                                                padding: '1px 5px',
                                                borderRadius: 2,
                                                fontSize: 9,
                                                fontWeight: 700,
                                                fontFamily: 'JetBrains Mono, monospace',
                                                color: kc(t.Key),
                                                background: hexA(kc(t.Key), 0.14),
                                                border: `1px solid ${hexA(kc(t.Key), 0.38)}`,
                                            }}
                                        >
                                            {t.Key}
                                        </span>
                                    </td>
                                    <td style={{ padding: '0 8px', textAlign: 'right', fontFamily: 'JetBrains Mono, monospace', fontSize: 10, color: T.text2, borderRight: `1px solid ${T.border}` }}>
                                        {fmt(t.TotalTime)}
                                    </td>
                                    <td style={{ padding: '0 8px', fontFamily: 'JetBrains Mono, monospace', fontSize: 10, color: T.text2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                        {t.path}
                                    </td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </div>
        </div>
    );
}

// ═══ STATUS BAR ══════════════════════════════════════════════════════════════
function StatusBar({ trackCount, totalSeconds, selectedTrack, playing }) {
    const totalHrs = Math.floor(totalSeconds / 3600);
    const totalMin = Math.floor((totalSeconds % 3600) / 60);
    const item = (label, value) => (
        <span>
            <span style={{ color: T.text3 }}>{label}</span> {value}
        </span>
    );
    return (
        <div
            style={{
                height: 22,
                background: T.bg2,
                borderTop: `1px solid ${T.border}`,
                display: 'flex',
                alignItems: 'center',
                padding: '0 10px',
                gap: 14,
                flexShrink: 0,
                fontSize: 10,
                fontFamily: 'JetBrains Mono, monospace',
                color: T.text2,
            }}
        >
            <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                <span
                    style={{
                        width: 5,
                        height: 5,
                        borderRadius: '50%',
                        background: playing ? T.green : T.text3,
                        boxShadow: playing ? `0 0 4px ${T.green}` : 'none',
                    }}
                />
                {playing ? 'PLAYING' : 'IDLE'}
            </span>
            <span style={{ color: T.border3 }}>│</span>
            {item('tracks', trackCount)}
            {item('total', `${totalHrs}h ${totalMin}m`)}
            {item('analyzed', `${trackCount}/${trackCount}`)}
            <span style={{ color: T.border3 }}>│</span>
            {item('sel', selectedTrack?.Title?.slice(0, 28) || '—')}
            <div style={{ flex: 1 }} />
            {item('buf', '256 / 44.1k')}
            {item('out', '1/2')}
            <span style={{ color: T.green }}>● LINK</span>
        </div>
    );
}

// ═══ STUDIO VIEW ═════════════════════════════════════════════════════════════
export default function StudioView() {
    const nowPlaying = React.useMemo(() => TRACKS.find((t) => t.selected) || TRACKS[17], []);
    const [activePlaylist, setActivePlaylist] = React.useState('dtc');
    const [selected, setSelected] = React.useState(nowPlaying);
    const [playing, setPlaying] = React.useState(true);
    const [playhead, setPlayhead] = React.useState(0.34);
    const [bpm] = React.useState(137.0);
    const [collapsed, setCollapsed] = React.useState(false);

    // Auto-advance playhead while playing.
    React.useEffect(() => {
        if (!playing) return undefined;
        const iv = setInterval(() => setPlayhead((p) => (p + 0.0015 > 1 ? 0 : p + 0.0015)), 80);
        return () => clearInterval(iv);
    }, [playing]);

    const totalSec = React.useMemo(() => TRACKS.reduce((s, t) => s + (t.TotalTime || 0), 0), []);

    return (
        <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: T.bg0, color: T.text1 }}>
            <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
                <StudioSidebar
                    active={activePlaylist}
                    setActive={setActivePlaylist}
                    collapsed={collapsed}
                    setCollapsed={setCollapsed}
                />
                <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0, overflowX: 'auto' }}>
                    <TopBar track={selected} playing={playing} setPlaying={setPlaying} bpm={bpm} />
                    <WaveformPanel track={selected} playing={playing} playhead={playhead} setPlayhead={setPlayhead} />
                    <TrackTable
                        tracks={TRACKS}
                        playId={playing ? selected.id : null}
                        selectedId={selected.id}
                        onSelect={(t) => setSelected(t)}
                        onPlay={(t) => {
                            setSelected(t);
                            setPlaying(true);
                            setPlayhead(0);
                        }}
                    />
                </div>
            </div>
            <StatusBar trackCount={TRACKS.length} totalSeconds={totalSec} selectedTrack={selected} playing={playing} />
        </div>
    );
}
