/**
 * DawState helpers — pure utilities and the initial-state factory.
 *
 * These functions don't touch state directly; they're shared by the
 * sub-reducers and consumed by UI components (snap math, cue
 * conversion to/from .rbep POSITION_MARK records).
 */

// ─── INITIAL STATE ─────────────────────────────────────────────────────────────

/**
 * Create the initial DAW state.
 * @param {Object} [overrides] - Optional property overrides
 * @returns {Object} DAW state
 */
export function createInitialState(overrides = {}) {
    return {
        // Project metadata
        project: {
            name: '',
            filepath: '',
            dirty: false,
        },

        // Track info
        trackMeta: {
            title: '',
            artist: '',
            album: '',
            filepath: '',
            id: '',
            uuid: '',
        },

        // Audio
        sourceBuffer: null,  // AudioBuffer (not serialized)
        bandPeaks: null,     // { low, mid, high } peak arrays (not serialized)
        fallbackPeaks: null, // Simple mono peaks array (fallback when band splitting fails)
        totalDuration: 0,    // Source track duration in seconds

        // Tempo
        bpm: 128,
        tempoMap: [],        // [{index, bpm, positionMs}] from song grid
        gridOffsetSec: 0,    // Manual grid shift (seconds)
        masterTempoMap: [],  // [{index, bpm, positionMs}] for the edit timeline
        firstBeatMs: 0,

        // Regions (the core edit data)
        regions: [],

        // Volume automation
        volumeData: [],

        // Selection
        selectedRegionIds: new Set(),
        selectionRange: null,  // { start, end } in seconds

        // Cue Points & Loops
        hotCues: Array(8).fill(null),  // [A-H], each: { name, time, red, green, blue } or null
        memoryCues: [],                // [{ name, time, red, green, blue }]
        loops: [],                     // [{ name, startTime, endTime, active, red, green, blue }]
        activeLoopIndex: -1,           // Index of the active loop in loops array

        // Transport / Playback
        playhead: 0,       // Current playhead position (seconds)
        isPlaying: false,
        loopEnabled: false,
        loopStart: 0,
        loopEnd: 0,

        // Dead Reckoning — interpolate playhead between IPC sync frames
        deadReckoning: {
            lastSyncWallClock: 0,   // performance.now() at last Tauri sync
            lastSyncAudioTime: 0,   // audio time (seconds) at last sync
        },

        // View state
        zoom: 100,         // Pixels per second
        scrollX: 0,        // Horizontal scroll offset in pixels
        snapEnabled: true,
        snapDivision: '1/4',  // '1/4' | '1/8' | '1/16' | '1/32'
        slipMode: false,      // When true, snap is temporarily disabled
        waveformStyle: '3band', // '3band' (Rekordbox CDJ) | 'mono' | 'bass'

        // History (undo/redo)
        undoStack: [],     // Array of { regions, hotCues, memoryCues, loops, label }
        redoStack: [],
        maxHistory: 50,

        // UI state
        activeTool: 'select',  // 'select' | 'split' | 'trim'
        clipboard: [],         // Array of regions to paste
        clipboardSpan: 0,      // Total span of last copy (selection-range width)

        ...overrides,
    };
}

// ─── REGION NORMALISATION ──────────────────────────────────────────────────────

/**
 * Coerce a region into a self-consistent state. Many mutation paths
 * (drag, resize, project hydration, third-party tooling that wrote
 * .rbep files) leave one of duration/sourceDuration/sourceEnd stale
 * relative to the others — the export renderer trusts sourceDuration,
 * the playback engine prefers sourceDuration but falls back to
 * sourceEnd, and the timeline visual reads timelineStart + duration.
 * Mismatches manifest as audio cutting out before the visible region
 * ends, audio bleeding past the visible right edge, or export
 * sounding pitch-shifted vs. live playback. Normalising at every
 * dispatch makes those classes of bug structurally impossible.
 *
 * Rules (in priority order):
 *   1. duration > 0 (drop region if zero/negative)
 *   2. sourceStart defaults to 0
 *   3. sourceDuration mirrors duration (1:1 native-rate playback);
 *      if a caller already set a DIFFERENT sourceDuration we keep it
 *      and warn — that's intentional time-stretching, rare for cut/
 *      paste workflows but legal for tempo-locked .rbep imports
 *   4. sourceEnd is always sourceStart + sourceDuration
 *   5. timelineEnd is always timelineStart + duration
 */
export function normalizeRegion(r) {
    if (!r) return r;
    const duration = Math.max(0, r.duration || 0);
    if (duration === 0) return null;  // caller will filter
    const timelineStart = Math.max(0, r.timelineStart || 0);
    const sourceStart = Math.max(0, r.sourceStart || 0);
    let sourceDuration = r.sourceDuration;
    if (sourceDuration == null || sourceDuration <= 0) {
        // Fall back to sourceEnd-derived duration if available, else mirror timeline
        if (r.sourceEnd != null && r.sourceEnd > sourceStart) {
            sourceDuration = r.sourceEnd - sourceStart;
        } else {
            sourceDuration = duration;
        }
    }
    // If the caller's intent was time-stretching (explicit mismatch by
    // > 1ms), let it through but log so we can see this in the console
    // when debugging weird playback. Cut/paste produces match.
    if (Math.abs(sourceDuration - duration) > 0.001) {
        console.warn(
            '[normalizeRegion] sourceDuration != duration — keeping as time-stretch',
            { id: r.id, timelineStart, duration, sourceDuration }
        );
    }
    return {
        ...r,
        timelineStart,
        duration,
        timelineEnd: timelineStart + duration,
        sourceStart,
        sourceDuration,
        sourceEnd: sourceStart + sourceDuration,
    };
}

export function normalizeRegions(regions) {
    if (!Array.isArray(regions)) return [];
    const out = [];
    for (const r of regions) {
        const n = normalizeRegion(r);
        if (n) out.push(n);
    }
    return out;
}

// ─── GRID SNAP UTILITIES ───────────────────────────────────────────────────────

/**
 * Calculate the snap unit in seconds for a given BPM and division.
 *
 * @param {number} bpm
 * @param {string} division - '1/4', '1/8', '1/16', '1/32'
 * @returns {number} Snap unit in seconds
 */
export function getSnapUnit(bpm, division = '1/4') {
    if (!bpm || bpm <= 0) return 0.5;

    const beatDuration = 60 / bpm;  // One quarter note

    switch (division) {
        case '1/1': return beatDuration * 4;   // Whole bar
        case '1/2': return beatDuration * 2;   // Half
        case '1/4': return beatDuration;       // Quarter
        case '1/8': return beatDuration / 2;   // Eighth
        case '1/16': return beatDuration / 4;  // Sixteenth
        case '1/32': return beatDuration / 8;  // Thirty-second
        default: return beatDuration;
    }
}

/**
 * Snap a time value to the nearest grid position.
 *
 * @param {number} time - Time in seconds
 * @param {number} bpm
 * @param {string} division
 * @param {number} [offset=0] - Grid offset in seconds (first beat position)
 * @returns {number} Snapped time
 */
export function snapToGrid(time, bpm, division = '1/4', offset = 0) {
    const unit = getSnapUnit(bpm, division);
    if (unit <= 0) return time;

    const adjustedTime = time - offset;
    const snapped = Math.round(adjustedTime / unit) * unit;
    return Math.max(0, snapped + offset);
}

/**
 * Get the beat number at a given time.
 *
 * @param {number} time - Time in seconds
 * @param {number} bpm
 * @param {number} [offset=0]
 * @returns {{ bar: number, beat: number, subdivision: number }}
 */
export function getPositionInfo(time, bpm, offset = 0) {
    if (!bpm || bpm <= 0) return { bar: 1, beat: 1, subdivision: 0 };

    const beatDuration = 60 / bpm;
    const adjustedTime = time - offset;
    const totalBeats = adjustedTime / beatDuration;

    const bar = Math.floor(totalBeats / 4) + 1;
    const beat = Math.floor(totalBeats % 4) + 1;
    const subdivision = (totalBeats % 1) * 4;

    return { bar, beat, subdivision: Math.floor(subdivision) };
}

// ─── HOT CUE COLORS ───────────────────────────────────────────────────────────

/**
 * Default hot cue colors (matching Rekordbox CDJ color scheme)
 */
export const HOT_CUE_COLORS = [
    { red: 40, green: 255, blue: 0, label: 'Green' },       // A
    { red: 0, green: 200, blue: 255, label: 'Cyan' },       // B
    { red: 60, green: 100, blue: 255, label: 'Blue' },      // C
    { red: 200, green: 100, blue: 255, label: 'Purple' },   // D
    { red: 255, green: 50, blue: 120, label: 'Pink' },      // E
    { red: 255, green: 100, blue: 0, label: 'Orange' },     // F
    { red: 255, green: 220, blue: 0, label: 'Yellow' },     // G
    { red: 255, green: 0, blue: 0, label: 'Red' },          // H
];

/**
 * Helper: Convert cue points from DAW state to POSITION_MARK format for .rbep serialization
 */
export function stateToCuePoints(hotCues, memoryCues, loops) {
    const points = [];

    // Hot cues → Type 0
    for (let i = 0; i < hotCues.length; i++) {
        const cue = hotCues[i];
        if (!cue) continue;
        points.push({
            name: cue.name || `Cue ${String.fromCharCode(65 + i)}`,
            type: 0,
            start: cue.time,
            end: null,
            num: i,
            red: cue.red ?? HOT_CUE_COLORS[i].red,
            green: cue.green ?? HOT_CUE_COLORS[i].green,
            blue: cue.blue ?? HOT_CUE_COLORS[i].blue,
        });
    }

    // Memory cues → Type 0 (Num = -1)
    for (const mem of memoryCues) {
        points.push({
            name: mem.name || 'Memory',
            type: 0,
            start: mem.time,
            end: null,
            num: -1,
            red: mem.red ?? 255,
            green: mem.green ?? 0,
            blue: mem.blue ?? 0,
        });
    }

    // Loops → Type 4
    for (let i = 0; i < loops.length; i++) {
        const loop = loops[i];
        points.push({
            name: loop.name || `Loop ${i + 1}`,
            type: 4,
            start: loop.startTime,
            end: loop.endTime,
            num: i,
            red: loop.red ?? 255,
            green: loop.green ?? 100,
            blue: loop.blue ?? 0,
        });
    }

    return points;
}

/**
 * Helper: Convert POSITION_MARK cue points from .rbep to DAW state format
 */
export function cuePointsToState(cuePoints = []) {
    const hotCues = Array(8).fill(null);
    const memoryCues = [];
    const loops = [];

    for (const cp of cuePoints) {
        if (cp.type === 0) {
            // Cue point
            if (cp.num >= 0 && cp.num < 8) {
                // Hot cue
                hotCues[cp.num] = {
                    name: cp.name,
                    time: cp.start,
                    red: cp.red,
                    green: cp.green,
                    blue: cp.blue,
                };
            } else {
                // Memory cue
                memoryCues.push({
                    name: cp.name,
                    time: cp.start,
                    red: cp.red,
                    green: cp.green,
                    blue: cp.blue,
                });
            }
        } else if (cp.type === 4) {
            // Loop
            loops.push({
                name: cp.name,
                startTime: cp.start,
                endTime: cp.end ?? cp.start + 4,
                active: false,
                red: cp.red,
                green: cp.green,
                blue: cp.blue,
            });
        }
    }

    return { hotCues, memoryCues, loops };
}
