/**
 * Rekordbox beat-grid helpers shared by the DAW and the waveform editor.
 *
 * GET /api/track/{id}/beatgrid answers `[{ time, bpm, beat }]` — `time` in
 * seconds, `beat` = position in the 4/4 bar (1-4). ANLZ grids carry one entry
 * per beat; XML grids carry one per tempo change (TEMPO Inizio/Bpm/Battito).
 * Both shapes go through expandBeatGrid, which yields one entry per beat.
 */

const BEATS_PER_BAR = 4;

/** Valid entries only, sorted by time. `beat` is null when unknown. */
export function normalizeBeatGrid(raw) {
    if (!Array.isArray(raw)) return [];
    const out = [];
    for (const entry of raw) {
        const time = Number(entry?.time);
        const bpm = Number(entry?.bpm);
        if (!Number.isFinite(time) || time < 0 || !Number.isFinite(bpm) || bpm <= 0) continue;
        const beat = Number(entry?.beat);
        out.push({
            time,
            bpm,
            beat: Number.isInteger(beat) && beat >= 1 && beat <= BEATS_PER_BAR ? beat : null,
        });
    }
    return out.sort((a, b) => a.time - b.time);
}

/**
 * One `{ time, bpm, beat }` per beat from the first grid entry to `durationSec`.
 * Each entry starts a segment at its own BPM; a beat closer than half a beat
 * to the next entry is left out so per-beat grids don't double up.
 */
export function expandBeatGrid(grid, durationSec) {
    const anchors = normalizeBeatGrid(grid);
    if (anchors.length === 0 || !(durationSec > 0)) return [];

    const beats = [];
    let beat = anchors[0].beat ?? 1;
    for (let i = 0; i < anchors.length; i++) {
        const anchor = anchors[i];
        if (anchor.time >= durationSec) break;
        if (anchor.beat !== null) beat = anchor.beat;
        const step = 60 / anchor.bpm;
        const next = anchors[i + 1];
        const end = next ? Math.min(next.time - step / 2, durationSec) : durationSec;
        const count = Math.max(1, Math.ceil((end - anchor.time) / step));
        for (let k = 0; k < count; k++) {
            beats.push({ time: anchor.time + k * step, bpm: anchor.bpm, beat });
            beat = (beat % BEATS_PER_BAR) + 1;
        }
    }
    return beats;
}

/** DAW tempo map `[{ index, bpm, positionMs, beat }]` from a Rekordbox grid. */
export function beatGridToTempoMap(grid, durationSec) {
    return expandBeatGrid(grid, durationSec).map((b, index) => ({
        index,
        bpm: b.bpm,
        positionMs: Math.round(b.time * 1e6) / 1e3,
        beat: b.beat,
    }));
}

/**
 * Seconds the DAW lays its constant-BPM grid from: the first downbeat, so bar
 * lines sit where Rekordbox has them. Maps without bar info (.rbep, synthesised)
 * anchor on their first beat.
 */
export function gridAnchorSec(tempoMap) {
    if (!tempoMap?.length) return 0;
    const downbeat = tempoMap.slice(0, BEATS_PER_BAR).find((b) => b.beat === 1);
    return (downbeat ?? tempoMap[0]).positionMs / 1000;
}
