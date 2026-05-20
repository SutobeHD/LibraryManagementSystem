/**
 * Studio waveform — section-shaped amplitude generation + canvas painters.
 *
 * studioAmps builds { rms, peak } envelopes shaped by SECTIONS so verses,
 * breaks and drops actually look different. The three painters render the
 * master view, the overview minimap and the dense per-row preview.
 */
import {
    SECTIONS,
    SECTION_COLORS,
    TOTAL_BARS,
    STUDIO_THEME as T,
    hexA,
    shade,
    sectionAt,
} from './studioData';

// Per-section RMS energy target — intro quiet → drop loud.
const ENERGY = [0.45, 0.62, 0.3, 0.55, 0.92, 0.55];
const ampCache = {};

/** Deterministic, section-shaped { rms, peak } arrays for a seed. */
export function studioAmps(seed, n = 720) {
    const key = `${seed}_${n}`;
    if (ampCache[key]) return ampCache[key];

    let s = seed || 1;
    const rng = () => {
        s = (Math.imul(s, 1664525) + 1013904223) | 0;
        return (s >>> 0) / 0xffffffff;
    };

    const rms = new Array(n);
    for (let i = 0; i < n; i++) {
        const t = i / n;
        const bar = t * TOTAL_BARS;
        const sec =
            SECTIONS.find((x) => bar >= x.start && bar < x.end) || SECTIONS[SECTIONS.length - 1];
        const e = ENERGY[sec.ci];
        const local = (bar - sec.start) / (sec.end - sec.start);
        let ramp = 1;
        if (sec.ci === 3) ramp = 0.65 + 0.4 * local; // build ramps up
        if (sec.ci === 2) ramp = 0.6 + 0.4 * Math.sin(local * Math.PI); // break dips
        if (sec.ci === 4) ramp = 1 - 0.05 * Math.sin(local * Math.PI * 4); // drop pulses
        if (sec.ci === 0) ramp = Math.min(1, 0.4 + local * 1.4); // intro ramps in
        if (sec.ci === 5) ramp = 1 - local * 0.6; // outro fades
        const wave =
            0.5 + 0.18 * Math.sin(t * Math.PI * 9 + seed) + 0.08 * Math.sin(t * Math.PI * 23 + seed * 1.3);
        rms[i] = Math.max(0.03, Math.min(1, e * ramp * wave + 0.04 * rng()));
    }
    for (let p = 0; p < 4; p++)
        for (let i = 2; i < n - 2; i++)
            rms[i] = (rms[i - 2] + rms[i - 1] * 2 + rms[i] * 3 + rms[i + 1] * 2 + rms[i + 2]) / 10;

    const peak = new Array(n);
    for (let i = 0; i < n; i++) {
        const beat = i % 4 === 0 ? 0.18 : 0;
        const accent = i % 16 === 0 ? 0.12 : 0;
        const noise = rng() < 0.06 ? 0.18 * rng() : 0.05 * rng();
        peak[i] = Math.max(0.05, Math.min(1, rms[i] + beat + accent + noise));
    }
    for (let i = 1; i < n - 1; i++) peak[i] = (peak[i - 1] + peak[i] * 2 + peak[i + 1]) / 4;

    const out = { rms, peak };
    ampCache[key] = out;
    return out;
}

function roundRect(ctx, x, y, w, h, r) {
    if (w <= 0 || h <= 0) return;
    r = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
    ctx.fill();
}

/** Large master waveform — colored section bands, beat markers, loop, playhead. */
export function drawMasterWave(canvas, seed, playhead, height) {
    if (!canvas?.parentElement) return;
    const a = studioAmps(seed, 1440);
    const dpr = window.devicePixelRatio || 1;
    const W0 = canvas.parentElement.clientWidth;
    if (!W0) return;
    canvas.width = W0 * dpr;
    canvas.height = height * dpr;
    canvas.style.width = `${W0}px`;
    canvas.style.height = `${height}px`;
    const ctx = canvas.getContext('2d');
    const W = canvas.width;
    const H = canvas.height;
    const mid = H / 2;
    ctx.clearRect(0, 0, W, H);

    ctx.fillStyle = T.bg0;
    ctx.fillRect(0, 0, W, H);

    // Section tint bands behind the wave
    SECTIONS.forEach((s) => {
        const x0 = (s.start / TOTAL_BARS) * W;
        const x1 = (s.end / TOTAL_BARS) * W;
        const g = ctx.createLinearGradient(0, 0, 0, H);
        g.addColorStop(0, hexA(SECTION_COLORS[s.ci], 0.05));
        g.addColorStop(0.5, hexA(SECTION_COLORS[s.ci], 0.1));
        g.addColorStop(1, hexA(SECTION_COLORS[s.ci], 0.05));
        ctx.fillStyle = g;
        ctx.fillRect(x0, 0, x1 - x0, H);
    });

    // Waveform bars — RMS body + peak cap, mirrored
    const gapPx = 1.0;
    const slot = (2.0 + gapPx) * dpr;
    const bars = Math.min(a.rms.length, Math.max(60, Math.floor(W / slot)));
    const bw = Math.max(1 * dpr, Math.floor(W / bars - gapPx * dpr));
    const radius = Math.min(bw / 2, 1.5 * dpr);
    const step = a.rms.length / bars;

    for (let b = 0; b < bars; b++) {
        const i0 = Math.floor(b * step);
        const i1 = Math.max(i0 + 1, Math.floor((b + 1) * step));
        let p = 0;
        let r = 0;
        let c2 = 0;
        for (let i = i0; i < i1; i++) {
            if (a.peak[i] > p) p = a.peak[i];
            r += a.rms[i];
            c2++;
        }
        r /= Math.max(1, c2);

        const t = (b + 0.5) / bars;
        const color = SECTION_COLORS[sectionAt(t)];
        const played = t < playhead;
        const x = Math.round(b * (W / bars));
        const peakH = Math.max(1.5 * dpr, p * mid * 0.92);
        const rmsH = Math.max(1 * dpr, r * mid * 0.55);

        if (played) {
            ctx.fillStyle = hexA(color, 0.55);
            roundRect(ctx, x, mid - peakH, bw, peakH * 2, radius);
            const grd = ctx.createLinearGradient(0, mid - rmsH, 0, mid + rmsH);
            grd.addColorStop(0, shade(color, 0.25));
            grd.addColorStop(0.5, color);
            grd.addColorStop(1, shade(color, 0.25));
            ctx.fillStyle = grd;
            roundRect(ctx, x, mid - rmsH, bw, rmsH * 2, radius);
        } else {
            ctx.fillStyle = hexA(color, 0.22);
            roundRect(ctx, x, mid - peakH, bw, peakH * 2, radius);
            ctx.fillStyle = hexA(shade(color, -0.1), 0.45);
            roundRect(ctx, x, mid - rmsH, bw, rmsH * 2, radius);
        }
    }

    // Center axis
    ctx.fillStyle = 'rgba(255,255,255,0.06)';
    ctx.fillRect(0, Math.floor(mid), W, Math.max(1, dpr * 0.5));

    // Beat / bar markers + section chips
    const barW = W / TOTAL_BARS;
    ctx.font = `${10 * dpr}px "JetBrains Mono", monospace`;
    ctx.textBaseline = 'top';
    for (let b = 0; b <= TOTAL_BARS; b++) {
        const x = Math.round(b * barW);
        ctx.fillStyle = b % 4 === 0 ? 'rgba(255,255,255,0.10)' : 'rgba(255,255,255,0.03)';
        ctx.fillRect(x, H - 12 * dpr, dpr, 6 * dpr);
        if (b % 4 === 0 && b < TOTAL_BARS) {
            const sec = SECTIONS.find((s) => s.start === b);
            if (sec) {
                ctx.fillStyle = SECTION_COLORS[sec.ci];
                roundRect(ctx, x, 3 * dpr, 5 * dpr, 5 * dpr, 1.5 * dpr);
            }
            ctx.fillStyle = 'rgba(255,255,255,0.42)';
            ctx.fillText(String(b + 117), x + 4 * dpr, H - 11 * dpr);
        }
    }

    // Loop region highlight (bars 64..85 — Build)
    const loopStart = 64 * barW;
    const loopEnd = 85 * barW;
    ctx.fillStyle = 'rgba(232,92,127,0.08)';
    ctx.fillRect(loopStart, 0, loopEnd - loopStart, H);
    ctx.strokeStyle = 'rgba(232,92,127,0.45)';
    ctx.setLineDash([4 * dpr, 3 * dpr]);
    ctx.lineWidth = dpr;
    ctx.strokeRect(loopStart + 0.5 * dpr, 0.5 * dpr, loopEnd - loopStart - dpr, H - dpr);
    ctx.setLineDash([]);

    // Playhead — halo + hard line + carets
    const px = Math.round(playhead * W);
    const halo = ctx.createLinearGradient(px - 22 * dpr, 0, px + 22 * dpr, 0);
    halo.addColorStop(0, 'rgba(245,166,35,0)');
    halo.addColorStop(0.5, 'rgba(255,202,106,0.22)');
    halo.addColorStop(1, 'rgba(245,166,35,0)');
    ctx.fillStyle = halo;
    ctx.fillRect(px - 22 * dpr, 0, 44 * dpr, H);
    ctx.fillStyle = '#FFE3A8';
    ctx.fillRect(px - Math.floor(dpr / 2), 0, Math.max(1, dpr), H);
    ctx.fillStyle = T.amber;
    ctx.beginPath();
    ctx.moveTo(px, 9 * dpr);
    ctx.lineTo(px - 6 * dpr, 0);
    ctx.lineTo(px + 6 * dpr, 0);
    ctx.closePath();
    ctx.fill();
    ctx.beginPath();
    ctx.moveTo(px, H - 9 * dpr);
    ctx.lineTo(px - 6 * dpr, H);
    ctx.lineTo(px + 6 * dpr, H);
    ctx.closePath();
    ctx.fill();
}

/** Overview minimap — bucketed section-colored bars + playhead tick. */
export function drawMiniWave(canvas, seed, playhead, height, dense = true) {
    if (!canvas?.parentElement) return;
    const a = studioAmps(seed, dense ? 720 : 320);
    const dpr = window.devicePixelRatio || 1;
    const W0 = canvas.parentElement.clientWidth;
    if (!W0) return;
    canvas.width = W0 * dpr;
    canvas.height = height * dpr;
    canvas.style.width = `${W0}px`;
    canvas.style.height = `${height}px`;
    const ctx = canvas.getContext('2d');
    const W = canvas.width;
    const H = canvas.height;
    const mid = H / 2;
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = T.bg0;
    ctx.fillRect(0, 0, W, H);

    SECTIONS.forEach((s) => {
        const x0 = (s.start / TOTAL_BARS) * W;
        const x1 = (s.end / TOTAL_BARS) * W;
        ctx.fillStyle = hexA(SECTION_COLORS[s.ci], 0.14);
        ctx.fillRect(x0, 0, x1 - x0, H);
    });

    const bars = Math.max(40, Math.min(a.rms.length, Math.floor(W / (2 * dpr))));
    const bw = Math.max(1 * dpr, Math.floor(W / bars) - dpr);
    const step = a.rms.length / bars;
    for (let b = 0; b < bars; b++) {
        const i0 = Math.floor(b * step);
        const i1 = Math.max(i0 + 1, Math.floor((b + 1) * step));
        let p = 0;
        for (let i = i0; i < i1; i++) if (a.peak[i] > p) p = a.peak[i];
        const t = (b + 0.5) / bars;
        const h = Math.max(1 * dpr, p * mid * 0.9);
        const x = Math.round(b * (W / bars));
        ctx.fillStyle = hexA(SECTION_COLORS[sectionAt(t)], 0.95);
        ctx.fillRect(x, mid - h, bw, h * 2);
    }

    if (playhead > 0) {
        const px = Math.round(playhead * W);
        ctx.fillStyle = T.amberL;
        ctx.fillRect(px - Math.floor(dpr / 2), 0, Math.max(1, dpr), H);
    }
}

/** Tiny per-row preview — fixed pixel size, section-colored bars. */
export function drawRowWave(canvas, seed, playhead, width, height) {
    if (!canvas) return;
    const a = studioAmps(seed, 360);
    const dpr = window.devicePixelRatio || 1;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    const ctx = canvas.getContext('2d');
    const W = canvas.width;
    const H = canvas.height;
    const mid = H / 2;
    ctx.clearRect(0, 0, W, H);

    SECTIONS.forEach((s) => {
        const x0 = (s.start / TOTAL_BARS) * W;
        const x1 = (s.end / TOTAL_BARS) * W;
        ctx.fillStyle = hexA(SECTION_COLORS[s.ci], 0.2);
        ctx.fillRect(x0, 0, x1 - x0, H);
    });

    const bars = Math.max(40, Math.min(a.rms.length, Math.floor(W / (1.6 * dpr))));
    const bw = Math.max(1 * dpr, Math.floor(W / bars) - 1 * dpr);
    const step = a.rms.length / bars;
    for (let b = 0; b < bars; b++) {
        const i0 = Math.floor(b * step);
        const i1 = Math.max(i0 + 1, Math.floor((b + 1) * step));
        let p = 0;
        for (let i = i0; i < i1; i++) if (a.peak[i] > p) p = a.peak[i];
        const t = (b + 0.5) / bars;
        const h = Math.max(1 * dpr, p * mid * 0.88);
        const x = Math.round(b * (W / bars));
        ctx.fillStyle = hexA(SECTION_COLORS[sectionAt(t)], 0.95);
        ctx.fillRect(x, mid - h, bw, h * 2);
    }

    if (playhead > 0) {
        const px = Math.round(playhead * W);
        ctx.fillStyle = T.amberL;
        ctx.fillRect(px - Math.floor(dpr / 2), 0, Math.max(1, dpr), H);
    }
}
