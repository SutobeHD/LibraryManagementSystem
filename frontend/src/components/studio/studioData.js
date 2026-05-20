/**
 * Studio view — sample catalogue, theme + shared helpers.
 *
 * The Studio is a self-contained efficiency-editor screen ported from the
 * Melodex design handoff. It ships with the design's sample data; wiring it
 * to the live library + audio analysis is a follow-up.
 */

// Blender-inspired warm dark-gray palette — deliberately lighter/warmer than
// the near-black Melodex shell so the editor reads as its own workspace.
export const STUDIO_THEME = {
    bg0: '#1c1d20', bg1: '#2a2c30', bg2: '#3a3c42', bg3: '#2f3137', bg4: '#45474d',
    border: '#161719', border2: '#4a4c52', border3: '#5e6068',
    text0: '#e0e2e6', text1: '#a4a6ac', text2: '#75787e', text3: '#4a4c52',
    amber: '#F5A623', amberD: '#C8841A', amberL: '#FFCA6A',
    amberBg: 'rgba(245,166,35,0.12)', amberGl: 'rgba(245,166,35,0.30)',
    green: '#3DD68C', red: '#E85C4A', blue: '#4A9EE8', purple: '#9B6FE8',
};

// Waveform region colors — intro / verse / break / build / drop / outro.
export const SECTION_COLORS = ['#E8C86A', '#9B6FE8', '#E8E2D6', '#E85FB0', '#FF9166', '#E85C7F'];

export const SECTIONS = [
    { start: 0, end: 21, ci: 0, label: 'Intro' },
    { start: 21, end: 42, ci: 1, label: 'Verse' },
    { start: 42, end: 64, ci: 2, label: 'Break' },
    { start: 64, end: 85, ci: 3, label: 'Build' },
    { start: 85, end: 107, ci: 4, label: 'Drop' },
    { start: 107, end: 128, ci: 5, label: 'Outro' },
];

export const TOTAL_BARS = SECTIONS[SECTIONS.length - 1].end;

// 16 hot-cue pads — six set, ten empty.
export const HOT_CUES = [
    { n: 1, ci: 0, label: 'Intro', bar: 0, set: true },
    { n: 2, ci: 1, label: 'Vers 1', bar: 16, set: true },
    { n: 3, ci: 2, label: 'Brk', bar: 42, set: true },
    { n: 4, ci: 3, label: 'Bld', bar: 64, set: true },
    { n: 5, ci: 4, label: 'Drop', bar: 85, set: true },
    { n: 6, ci: 5, label: 'Out', bar: 107, set: true },
    { n: 7, set: false }, { n: 8, set: false }, { n: 9, set: false }, { n: 10, set: false },
    { n: 11, set: false }, { n: 12, set: false }, { n: 13, set: false }, { n: 14, set: false },
    { n: 15, set: false }, { n: 16, set: false },
];

export const STUDIO_TRACKS = [
    { id: 1, Title: 'Cascade Drift', Artist: 'Nolan Frey', BPM: 134.0, Key: 'Am', TotalTime: 227, seed: 7, bitrate: 320, fmt: 'AIFF', path: '/Users/alex/Dropbox/Library/DrivingTechno/Nolan Frey — Cascade Drift.aiff' },
    { id: 2, Title: '10000 Nodes', Artist: 'Peter Van Hoesen', BPM: 134.0, Key: 'Fm', TotalTime: 252, seed: 13, bitrate: 320, fmt: 'AIFF', path: '/Users/alex/Dropbox/Library/DrivingTechno/Peter Van Hoesen — 10000 Nodes.aiff' },
    { id: 3, Title: 'Angry Teleprinter', Artist: 'Marcal', BPM: 135.0, Key: 'G', TotalTime: 178, seed: 5, bitrate: 320, fmt: 'AIFF', path: '/Users/alex/Dropbox/Library/DrivingTechno/Marcal — Angry Teleprinter.aiff' },
    { id: 4, Title: "Don't Come and Find Me", Artist: 'Setaoc Mass', BPM: 135.0, Key: 'Dm', TotalTime: 321, seed: 3, bitrate: 320, fmt: 'AIFF', path: "/Users/alex/Dropbox/Library/DrivingTechno/Setaoc Mass — Don't Come and Find Me.aiff" },
    { id: 5, Title: 'Lux', Artist: 'Jurgen Degener', BPM: 135.0, Key: 'C', TotalTime: 182, seed: 19, bitrate: 320, fmt: 'AIFF', path: '/Users/alex/Dropbox/Library/DrivingTechno/Jurgen Degener — Lux.aiff' },
    { id: 6, Title: 'Object 0982 (Flug Rmx)', Artist: 'MODIG', BPM: 135.0, Key: 'F#m', TotalTime: 368, seed: 11, bitrate: 320, fmt: 'AIFF', path: '/Users/alex/Dropbox/Library/DrivingTechno/MODIG — Object 0982.aiff' },
    { id: 7, Title: "I Am (Jackin' Cut)", Artist: 'S-file', BPM: 135.0, Key: 'D', TotalTime: 209, seed: 17, bitrate: 320, fmt: 'AIFF', path: '/Users/alex/Dropbox/Library/DrivingTechno/S-file — I Am.aiff' },
    { id: 8, Title: 'Rollercoaster', Artist: 'Rudy Ripani', BPM: 135.0, Key: 'Bm', TotalTime: 284, seed: 23, bitrate: 320, fmt: 'AIFF', path: '/Users/alex/Dropbox/Library/DrivingTechno/Rudy Ripani — Rollercoaster.aiff' },
    { id: 9, Title: 'VERMILLION 01', Artist: 'Rødhåd, Ignez', BPM: 135.0, Key: 'E', TotalTime: 151, seed: 31, bitrate: 320, fmt: 'AIFF', path: '/Users/alex/Dropbox/Library/DrivingTechno/Rødhåd, Ignez — VERMILLION 01.aiff' },
    { id: 10, Title: 'Ad Infinitum (Mulero)', Artist: 'Ribé', BPM: 135.0, Key: 'Cm', TotalTime: 422, seed: 37, bitrate: 320, fmt: 'AIFF', path: '/Users/alex/Dropbox/Library/DrivingTechno/Ribé — Ad Infinitum.aiff' },
    { id: 11, Title: 'Changa', Artist: 'Rene Wise', BPM: 135.0, Key: 'F', TotalTime: 165, seed: 41, bitrate: 320, fmt: 'AIFF', path: '/Users/alex/Dropbox/Library/DrivingTechno/Rene Wise — Changa.aiff' },
    { id: 12, Title: 'Afterglow', Artist: 'Pfirter', BPM: 135.0, Key: 'Am', TotalTime: 238, seed: 43, bitrate: 320, fmt: 'AIFF', path: '/Users/alex/Dropbox/Library/DrivingTechno/Pfirter — Afterglow.aiff' },
    { id: 13, Title: 'Seekwhensir', Artist: 'Uncertain, Skov Bowden', BPM: 136.0, Key: 'Fm', TotalTime: 240, seed: 47, bitrate: 320, fmt: 'AIFF', path: '/Users/alex/Dropbox/Library/DrivingTechno/Uncertain — Seekwhensir.aiff' },
    { id: 14, Title: 'Friction', Artist: 'Ramon Tapia, G. Zani', BPM: 136.0, Key: 'G', TotalTime: 215, seed: 53, bitrate: 320, fmt: 'AIFF', path: '/Users/alex/Dropbox/Library/DrivingTechno/Ramon Tapia — Friction.aiff' },
    { id: 15, Title: 'Circular', Artist: 'Ramon Tapia', BPM: 136.0, Key: 'Dm', TotalTime: 198, seed: 59, bitrate: 320, fmt: 'AIFF', path: '/Users/alex/Dropbox/Library/DrivingTechno/Ramon Tapia — Circular.aiff' },
    { id: 16, Title: 'Tu mirada', Artist: 'Pfirter', BPM: 136.0, Key: 'C', TotalTime: 225, seed: 61, bitrate: 320, fmt: 'AIFF', path: '/Users/alex/Dropbox/Library/DrivingTechno/Pfirter — Tu mirada.aiff' },
    { id: 17, Title: 'Silvery', Artist: 'MBM, Synthlab', BPM: 137.0, Key: 'F#m', TotalTime: 262, seed: 67, bitrate: 320, fmt: 'AIFF', path: '/Users/alex/Dropbox/Library/DrivingTechno/MBM — Silvery.aiff' },
    { id: 18, Title: 'Live For Yesterday', Artist: 'Marco Bailey, Sigvard', BPM: 137.0, Key: 'D', TotalTime: 309, seed: 71, bitrate: 320, fmt: 'AIFF', path: '/Users/alex/Dropbox/Library/DrivingTechno/Marco Bailey — Live For Yesterday.aiff', selected: true },
    { id: 19, Title: 'Technique', Artist: 'Setaoc Mass', BPM: 137.0, Key: 'Bm', TotalTime: 278, seed: 73, bitrate: 320, fmt: 'AIFF', path: '/Users/alex/Dropbox/Library/DrivingTechno/Setaoc Mass — Technique.aiff' },
    { id: 20, Title: 'Driving in Circles', Artist: 'Setaoc Mass', BPM: 137.0, Key: 'E', TotalTime: 266, seed: 79, bitrate: 320, fmt: 'AIFF', path: '/Users/alex/Dropbox/Library/DrivingTechno/Setaoc Mass — Driving in Circles.aiff' },
    { id: 21, Title: 'Engine', Artist: 'Uncertain', BPM: 137.0, Key: 'Cm', TotalTime: 251, seed: 83, bitrate: 320, fmt: 'AIFF', path: '/Users/alex/Dropbox/Library/DrivingTechno/Uncertain — Engine.aiff' },
    { id: 22, Title: 'Manta Ray', Artist: 'Marcal', BPM: 137.0, Key: 'F', TotalTime: 242, seed: 89, bitrate: 320, fmt: 'AIFF', path: '/Users/alex/Dropbox/Library/DrivingTechno/Marcal — Manta Ray.aiff' },
];

export const STUDIO_PLAYLISTS = [
    { id: 'cue', label: 'CUE Analysis Playlist', icon: 'star', count: 6 },
    { id: '_h1', type: 'header', label: 'Full Playlists' },
    { id: 'off', label: 'Offtempo', count: 142, smart: true },
    { id: 'cls', label: 'Classic Techno', count: 318 },
    { id: 'tp', label: 'Testpilot', count: 67 },
    { id: 'bs', label: 'BSOD', count: 24, smart: true },
    { id: 'wtf', label: 'WTF', count: 91, smart: true },
    { id: 'mel', label: 'Melodic Techno', count: 184 },
    { id: 'fth', label: 'Funky Tech House', count: 212 },
    { id: 'dtc', label: 'Driving Techno', count: 228, active: true },
    { id: 'mc', label: 'McTechno', count: 46, smart: true },
    { id: 'min', label: 'Minimal Techno', count: 108 },
    { id: 'dnb', label: 'DnB', count: 33, smart: true },
    { id: 'kx5', label: 'Kx5', count: 19 },
    { id: 'dm5', label: 'deadmau5', count: 142 },
    { id: 'acc', label: 'Accapellas', count: 58 },
    { id: 'int', label: 'Interludes', count: 21 },
    { id: 'stm', label: 'Stems', count: 312, smart: true },
    { id: '_h2', type: 'header', label: 'Show Playlists' },
    { id: 'tst', label: 'TEST Playlist', count: 11 },
    { id: '_h3', type: 'header', label: 'Archive' },
    { id: 'ar1', label: '2024 Sets', count: 88 },
    { id: 'ar2', label: '2023 Sets', count: 124, smart: true },
];

// Camelot key colors.
const KEY_COLORS = {
    Am: '#1DB954', Fm: '#39D353', G: '#2AC1BC', Dm: '#AE81FF', C: '#66D9EF',
    'F#m': '#0097E6', D: '#00A8FF', Bm: '#6366f1', E: '#8B5CF6', Cm: '#F92672',
    F: '#AE81FF', Bb: '#FD971F', Ab: '#E6DB74',
};
export const keyColor = (k) => (k ? KEY_COLORS[k.trim()] || '#5a5c60' : '#5a5c60');

export const fmt = (s) =>
    s ? `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}` : '–';

/** hex + alpha → rgba() string. */
export function hexA(hex, a) {
    const h = hex.replace('#', '');
    const r = parseInt(h.slice(0, 2), 16);
    const g = parseInt(h.slice(2, 4), 16);
    const b = parseInt(h.slice(4, 6), 16);
    return `rgba(${r},${g},${b},${a})`;
}

/** Lighten (p>0) or darken (p<0) a hex color by a fraction. */
export function shade(hex, p) {
    const h = hex.replace('#', '');
    let r = parseInt(h.slice(0, 2), 16);
    let g = parseInt(h.slice(2, 4), 16);
    let b = parseInt(h.slice(4, 6), 16);
    r = Math.max(0, Math.min(255, Math.round(r * (1 + p))));
    g = Math.max(0, Math.min(255, Math.round(g * (1 + p))));
    b = Math.max(0, Math.min(255, Math.round(b * (1 + p))));
    return '#' + [r, g, b].map((x) => x.toString(16).padStart(2, '0')).join('');
}

/** Section-color index for a 0..1 position along the track. */
export function sectionAt(barRatio) {
    const bar = barRatio * TOTAL_BARS;
    for (const s of SECTIONS) if (bar >= s.start && bar < s.end) return s.ci;
    return SECTIONS[SECTIONS.length - 1].ci;
}
