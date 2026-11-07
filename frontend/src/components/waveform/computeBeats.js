import { expandBeatGrid } from '../../audio/beatGrid';

// Builds the beat array used for grid rendering + snap-to-grid. Follows the Rekordbox
// grid (per-segment BPM, bar position); falls back to even spacing when no grid exists.
export default function computeBeats(beatGrid, bpm, duration) {
    if (!duration || !bpm) return [];

    const real = expandBeatGrid(beatGrid, duration);
    if (real.length > 0) {
        let barNum = 1;
        return real.map((b, i) => {
            if (i > 0 && b.beat === 1) barNum++;
            return { time: b.time, barNum, isDownbeat: b.beat === 1 };
        });
    }

    const result = [];
    let t = 0;
    let beatCount = 0;
    while (t < duration) {
        result.push({
            time: t,
            barNum: Math.floor(beatCount / 4) + 1,
            isDownbeat: beatCount % 4 === 0,
        });
        t += 60 / bpm;
        beatCount++;
    }
    return result;
}
