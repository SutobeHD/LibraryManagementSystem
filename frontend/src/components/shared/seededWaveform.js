/**
 * seededWaveform — deterministic pseudo-waveform generator + painter.
 *
 * Builds a song-shaped amplitude envelope (intro / build / drop / breakdown /
 * outro) from an integer seed and paints it as a mirrored RMS + peak bar
 * waveform. Used where real decoded audio peaks are unavailable — the player
 * scrubber and Studio track previews — so a given track always renders the
 * same shape across sessions.
 */

// Played-portion gradient — project amber tokens (#E8A42A / #F5C860).
const PLAYED_EDGE = '#F5C860';
const PLAYED_CORE = '#E8A42A';

const ampCache = {};

/** FNV-1a string hash → non-zero uint32 seed. */
export function hashSeed(input) {
    const str = String(input ?? '');
    let h = 2166136261;
    for (let i = 0; i < str.length; i++) {
        h ^= str.charCodeAt(i);
        h = Math.imul(h, 16777619);
    }
    return (h >>> 0) || 1;
}

/** Deterministic { rms, peak } amplitude arrays for a seed. Cached per seed+n. */
export function waveAmps(seed, n = 180) {
    const key = `${seed}_${n}`;
    if (ampCache[key]) return ampCache[key];

    let s = seed || 1;
    const rng = () => {
        s = (Math.imul(s, 1664525) + 1013904223) | 0;
        return (s >>> 0) / 0xffffffff;
    };
    const env = (i) => {
        const t = i / n;
        const intro = Math.min(1, t * 8);
        const outro = Math.min(1, (1 - t) * 6);
        const drop = t > 0.22 && t < 0.55 ? 1 : t > 0.7 ? 0.92 : 0.7;
        const breakdown = t > 0.55 && t < 0.68 ? 0.45 : 1;
        return intro * outro * drop * breakdown;
    };

    const rms = Array.from({ length: n }, (_, i) => {
        const t = i / n;
        const base =
            0.5 +
            0.22 * Math.sin(t * Math.PI * 3.1 + seed * 0.7) +
            0.12 * Math.sin(t * Math.PI * 7.3 + seed * 1.3);
        return Math.max(0.04, Math.min(1, env(i) * (base + 0.05 * rng())));
    });
    for (let p = 0; p < 4; p++)
        for (let i = 2; i < rms.length - 2; i++)
            rms[i] =
                (rms[i - 2] + rms[i - 1] * 2 + rms[i] * 3 + rms[i + 1] * 2 + rms[i + 2]) / 10;

    const peak = rms.map((v) => {
        const transient = rng() < 0.08 ? 0.18 + 0.22 * rng() : 0.04 + 0.08 * rng();
        return Math.max(0.06, Math.min(1, v + transient));
    });
    for (let i = 1; i < peak.length - 1; i++)
        peak[i] = (peak[i - 1] + peak[i] * 2 + peak[i + 1]) / 4;

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

/**
 * Paint a seeded waveform onto `canvas`, sized to its parent's width.
 * `playhead` is 0..1; bars before it render amber, the rest muted slate.
 */
export function drawSeededWave(canvas, amps, playhead = 0, height = 28) {
    if (!canvas?.parentElement) return;
    const dpr = window.devicePixelRatio || 1;
    const cssW = canvas.parentElement.clientWidth;
    if (!cssW) return;

    canvas.width = cssW * dpr;
    canvas.height = height * dpr;
    canvas.style.width = `${cssW}px`;
    canvas.style.height = `${height}px`;

    const ctx = canvas.getContext('2d');
    const W = canvas.width;
    const H = canvas.height;
    const { rms, peak } = amps;
    const n = rms.length;
    const gap = 1 * dpr;
    const bars = Math.max(40, Math.min(n, Math.floor(W / (3 * dpr))));
    const bw = Math.max(1 * dpr, Math.floor(W / bars - gap));
    const mid = H / 2;

    ctx.clearRect(0, 0, W, H);

    // Center axis — barely-there
    ctx.fillStyle = 'rgba(255,255,255,0.04)';
    ctx.fillRect(0, Math.floor(mid), W, Math.max(1, dpr * 0.5));

    const step = n / bars;
    for (let b = 0; b < bars; b++) {
        const i0 = Math.floor(b * step);
        const i1 = Math.max(i0 + 1, Math.floor((b + 1) * step));
        let p = 0;
        let r = 0;
        let c = 0;
        for (let i = i0; i < i1; i++) {
            if (peak[i] > p) p = peak[i];
            r += rms[i];
            c++;
        }
        r /= Math.max(1, c);

        const x = Math.round(b * (W / bars));
        const played = (b + 0.5) / bars < playhead;
        const peakH = Math.max(1.5 * dpr, p * mid * 0.92);
        const rmsH = Math.max(1 * dpr, r * mid * 0.62);
        const radius = Math.min(bw / 2, 1.5 * dpr);

        if (played) {
            ctx.fillStyle = 'rgba(232,164,42,0.42)';
            roundRect(ctx, x, mid - peakH, bw, peakH * 2, radius);
            const g = ctx.createLinearGradient(0, mid - rmsH, 0, mid + rmsH);
            g.addColorStop(0, PLAYED_EDGE);
            g.addColorStop(0.5, PLAYED_CORE);
            g.addColorStop(1, PLAYED_EDGE);
            ctx.fillStyle = g;
            roundRect(ctx, x, mid - rmsH, bw, rmsH * 2, radius);
        } else {
            ctx.fillStyle = 'rgba(154,158,166,0.22)';
            roundRect(ctx, x, mid - peakH, bw, peakH * 2, radius);
            ctx.fillStyle = 'rgba(192,196,204,0.42)';
            roundRect(ctx, x, mid - rmsH, bw, rmsH * 2, radius);
        }
    }

    // Playhead — hard line + soft halo + cap dots
    if (playhead > 0 && playhead < 1) {
        const px = Math.round(playhead * W);
        const halo = ctx.createLinearGradient(px - 14 * dpr, 0, px + 14 * dpr, 0);
        halo.addColorStop(0, 'rgba(232,164,42,0)');
        halo.addColorStop(0.5, 'rgba(245,200,96,0.18)');
        halo.addColorStop(1, 'rgba(232,164,42,0)');
        ctx.fillStyle = halo;
        ctx.fillRect(px - 14 * dpr, 0, 28 * dpr, H);

        ctx.fillStyle = '#FFE3A8';
        ctx.fillRect(px - Math.floor(dpr / 2), 0, Math.max(1, dpr), H);

        ctx.fillStyle = PLAYED_EDGE;
        ctx.beginPath();
        ctx.arc(px, 2 * dpr, 2 * dpr, 0, Math.PI * 2);
        ctx.fill();
        ctx.beginPath();
        ctx.arc(px, H - 2 * dpr, 2 * dpr, 0, Math.PI * 2);
        ctx.fill();
    }
}
