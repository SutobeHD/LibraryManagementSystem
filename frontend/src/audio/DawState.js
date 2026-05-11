/**
 * DawState — Central state management for the DJ Edit DAW
 *
 * Uses an immutable reducer pattern for predictable state updates.
 * Includes undo/redo via full-state snapshots of the regions array.
 * Manages regions, cue points, loops, selection, transport, and project metadata.
 */

import { log } from '../utils/log';

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

// ─── REDUCER ───────────────────────────────────────────────────────────────────

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
function normalizeRegion(r) {
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

function normalizeRegions(regions) {
    if (!Array.isArray(regions)) return [];
    const out = [];
    for (const r of regions) {
        const n = normalizeRegion(r);
        if (n) out.push(n);
    }
    return out;
}

/**
 * DAW state reducer. All state changes go through here.
 *
 * @param {Object} state - Current state
 * @param {Object} action - { type, payload }
 * @returns {Object} New state
 */
export function dawReducer(state, action) {
    switch (action.type) {

        // ── Project ──────────────────────────
        case 'SET_PROJECT':
            return { ...state, project: { ...state.project, ...action.payload } };

        case 'SET_TRACK_META':
            return { ...state, trackMeta: { ...state.trackMeta, ...action.payload } };

        case 'MARK_DIRTY':
            return { ...state, project: { ...state.project, dirty: true } };

        case 'MARK_CLEAN':
            return { ...state, project: { ...state.project, dirty: false } };

        // ── Audio ────────────────────────────
        case 'SET_SOURCE_BUFFER':
            return {
                ...state,
                sourceBuffer: action.payload.buffer,
                totalDuration: action.payload.buffer?.duration || 0,
            };

        case 'SET_BAND_PEAKS':
            return { ...state, bandPeaks: action.payload };

        case 'SET_FALLBACK_PEAKS':
            return { ...state, fallbackPeaks: action.payload };

        // ── Tempo ────────────────────────────
        case 'SET_BPM':
            return { ...state, bpm: action.payload };

        case 'SET_TEMPO_MAP':
            return { ...state, tempoMap: action.payload };

        case 'SET_MASTER_TEMPO_MAP':
            return { ...state, masterTempoMap: action.payload };

        // ── Regions ──────────────────────────
        case 'SET_REGIONS':
            return {
                ...state,
                regions: normalizeRegions(action.payload),
                project: { ...state.project, dirty: true },
            };

        case 'ADD_REGION': {
            const normalized = normalizeRegion(action.payload);
            if (!normalized) return state;
            const newRegions = [...state.regions, normalized]
                .sort((a, b) => a.timelineStart - b.timelineStart);
            return {
                ...state,
                regions: newRegions,
                project: { ...state.project, dirty: true },
            };
        }

        case 'REMOVE_REGION': {
            const filtered = state.regions.filter(r => r.id !== action.payload);
            return {
                ...state,
                regions: filtered,
                selectedRegionIds: (() => {
                    const s = new Set(state.selectedRegionIds);
                    s.delete(action.payload);
                    return s;
                })(),
                project: { ...state.project, dirty: true },
            };
        }

        case 'UPDATE_REGION': {
            const { id, updates } = action.payload;
            const updatedRegions = state.regions.map(r =>
                r.id === id ? (normalizeRegion({ ...r, ...updates }) || r) : r
            );
            return {
                ...state,
                regions: updatedRegions,
                project: { ...state.project, dirty: true },
            };
        }

        case 'SPLIT_REGION_AT': {
            const { regionId, splitTime } = action.payload;
            const region = state.regions.find(r => r.id === regionId);
            if (!region) return state;

            // Validate split point
            if (splitTime <= region.timelineStart || splitTime >= region.timelineStart + region.duration) {
                return state;
            }

            const relativeOffset = splitTime - region.timelineStart;
            const sourceSplitPoint = region.sourceStart + relativeOffset;

            const leftRegion = {
                ...region,
                id: crypto.randomUUID(),
                sourceEnd: sourceSplitPoint,
                duration: relativeOffset,
                sourceDuration: relativeOffset,
            };

            const rightDuration = region.duration - relativeOffset;
            const rightRegion = {
                ...region,
                id: crypto.randomUUID(),
                sourceStart: sourceSplitPoint,
                timelineStart: splitTime,
                duration: rightDuration,
                sourceDuration: rightDuration,
                // Clear stored beat values since they're invalidated
                _beatStart: undefined,
                _beatEnd: undefined,
                _songBeatStart: undefined,
                _songBeatEnd: undefined,
            };

            const newRegions = normalizeRegions(
                state.regions
                    .filter(r => r.id !== regionId)
                    .concat([leftRegion, rightRegion])
            ).sort((a, b) => a.timelineStart - b.timelineStart);

            return {
                ...state,
                regions: newRegions,
                selectedRegionIds: new Set(),
                project: { ...state.project, dirty: true },
            };
        }

        case 'RIPPLE_DELETE': {
            const deleteId = action.payload;
            const deleteRegion = state.regions.find(r => r.id === deleteId);
            if (!deleteRegion) return state;

            const gap = deleteRegion.duration;
            const deleteStart = deleteRegion.timelineStart;

            const newRegions = state.regions
                .filter(r => r.id !== deleteId)
                .map(r => {
                    if (r.timelineStart > deleteStart) {
                        return {
                            ...r,
                            timelineStart: r.timelineStart - gap,
                            timelineEnd: (r.timelineStart - gap) + r.duration,
                            _beatStart: undefined,
                            _beatEnd: undefined,
                        };
                    }
                    return r;
                });

            return {
                ...state,
                regions: newRegions,
                selectedRegionIds: new Set(),
                project: { ...state.project, dirty: true },
            };
        }

        // ── Clipboard / Editing ──────────────
        case 'COPY_SELECTION': {
            log.debug('Reducer: COPY_SELECTION', {
                selectedIds: Array.from(state.selectedRegionIds),
                range: state.selectionRange
            });

            let regionsToCopy = [];
            let copyStart = 0;
            // Total span of the user's selection. When a time-range was
            // selected this MUST equal range.end - range.start, even if
            // the regions inside don't fully cover the range. Otherwise
            // PASTE_INSERT's ripple shift falls short by the trailing
            // (or leading) empty space and the next region snuggles up
            // against the paste — the visible "missing half between two
            // region lines" the user reported.
            let clipboardSpan = 0;

            // 1. Check for Time Selection Range
            if (state.selectionRange && Math.abs(state.selectionRange.end - state.selectionRange.start) > 0.001) {
                const { start, end } = state.selectionRange;
                copyStart = start;
                clipboardSpan = end - start;

                // Find regions intersecting the selection range
                const intersecting = state.regions.filter(r =>
                    r.timelineStart < end && (r.timelineStart + r.duration) > start
                );

                regionsToCopy = intersecting.map(r => {
                    const intersectStart = Math.max(r.timelineStart, start);
                    const intersectEnd = Math.min(r.timelineStart + r.duration, end);
                    const newDuration = intersectEnd - intersectStart;

                    // Calculate new source start based on where the intersection starts relative to region start
                    const offsetFromRegionStart = intersectStart - r.timelineStart;
                    const newSourceStart = r.sourceStart + offsetFromRegionStart;

                    return {
                        ...r,
                        id: crypto.randomUUID(), // New ID for clipboard item
                        timelineStart: intersectStart,
                        duration: newDuration,
                        sourceStart: newSourceStart,
                        // sourceEnd MUST track sourceStart — without this the
                        // clipboard inherits the original region's sourceEnd
                        // (which still points at the old, larger boundary).
                        // DawEngine's playRegions falls back to sourceEnd
                        // when sourceDuration is missing, and the offline
                        // export renderer uses sourceEnd directly. A stale
                        // sourceEnd makes small clipped sections play extra
                        // audio past the visible region edge (audible as
                        // ghost content beyond the displayed waveform).
                        sourceEnd: newSourceStart + newDuration,
                        sourceDuration: newDuration,
                        _beatStart: undefined, _beatEnd: undefined
                    };
                });
            } else {
                // 2. Fallback: Copy whole selected regions
                regionsToCopy = state.regions.filter(r => state.selectedRegionIds.has(r.id));
                if (regionsToCopy.length > 0) {
                    regionsToCopy.sort((a, b) => a.timelineStart - b.timelineStart);
                    copyStart = regionsToCopy[0].timelineStart;
                    // For whole-region selection, span = first start → last end
                    const lastEnd = regionsToCopy.reduce(
                        (acc, r) => Math.max(acc, r.timelineStart + r.duration),
                        copyStart
                    );
                    clipboardSpan = lastEnd - copyStart;
                }
            }

            if (regionsToCopy.length === 0) return state;

            // Sort by time
            regionsToCopy.sort((a, b) => a.timelineStart - b.timelineStart);

            // Normalize to 0 offset relative to copy start
            const clipboardData = regionsToCopy.map(r => ({
                ...r,
                _offset: r.timelineStart - copyStart
            }));

            return { ...state, clipboard: clipboardData, clipboardSpan };
        }

        case 'PASTE_INSERT': {
            log.debug('Reducer: PASTE_INSERT', state.clipboard);
            if (state.clipboard.length === 0) return state;

            const EPSILON = 0.001;
            const rawInsertTime = state.playhead;

            // Snap insertTime to the previous region's END if the playhead
            // sits in dead space (no region under it). Rekordbox's editor
            // does the same — clicking past the last clip and pasting
            // attaches the new clip flush against the existing content
            // rather than leaving a leading silence gap. Only snaps
            // FORWARD-LOOKING (no jump backwards across a real gap that
            // the user might want to span).
            const sortedExisting = [...state.regions].sort(
                (a, b) => a.timelineStart - b.timelineStart
            );
            const containing = sortedExisting.find(r =>
                rawInsertTime > r.timelineStart - EPSILON &&
                rawInsertTime < r.timelineStart + r.duration - EPSILON
            );
            let insertTime = rawInsertTime;
            if (!containing) {
                let prevEnd = 0;
                for (const r of sortedExisting) {
                    const rEnd = r.timelineStart + r.duration;
                    if (rEnd <= rawInsertTime + EPSILON && rEnd > prevEnd) {
                        prevEnd = rEnd;
                    }
                }
                if (prevEnd > 0 && prevEnd < rawInsertTime - EPSILON) {
                    insertTime = prevEnd;
                }
            }

            let tempRegions = [...state.regions];

            // 1. Check if we need to split a region at insertTime
            const intersectIdx = tempRegions.findIndex(r =>
                insertTime > r.timelineStart + EPSILON &&
                insertTime < r.timelineStart + r.duration - EPSILON
            );

            if (intersectIdx !== -1) {
                const r = tempRegions[intersectIdx];
                const relativeOffset = insertTime - r.timelineStart;
                const sourceSplitPoint = r.sourceStart + relativeOffset;

                // Create Left Part (ends at insertTime)
                const leftRegion = {
                    ...r,
                    id: crypto.randomUUID(),
                    duration: relativeOffset,
                    sourceDuration: relativeOffset,
                    sourceEnd: sourceSplitPoint,
                    _beatStart: undefined, _beatEnd: undefined // Invalidate beat cache
                };

                // Create Right Part (starts at insertTime)
                const rightRegion = {
                    ...r,
                    id: crypto.randomUUID(),
                    timelineStart: insertTime,
                    sourceStart: sourceSplitPoint,
                    duration: r.duration - relativeOffset,
                    sourceDuration: r.duration - relativeOffset,
                    _beatStart: undefined, _beatEnd: undefined
                };

                // Replace original with Left and Right
                tempRegions.splice(intersectIdx, 1, leftRegion, rightRegion);
            }

            // 2. Pack the clipboard items contiguously at insertTime —
            // collapse any internal gaps the original selection had. The
            // user's "the gap remains in the paste" complaint comes from
            // the previous behaviour of preserving _offset (which encoded
            // the position INSIDE the original selection, gaps included).
            // For a single-region clipboard this changes nothing.
            const sortedClip = [...state.clipboard].sort(
                (a, b) => (a._offset ?? 0) - (b._offset ?? 0)
            );
            let cursor = insertTime;
            const pastedRegions = sortedClip.map(r => {
                const placed = {
                    ...r,
                    id: crypto.randomUUID(),
                    timelineStart: cursor,
                    timelineEnd: cursor + r.duration,
                    _offset: undefined,
                };
                cursor += r.duration;
                return placed;
            });
            const pastedSpan = cursor - insertTime;

            log.debug('Reducer: PASTE_INSERT debug', {
                rawInsertTime,
                insertTime,
                pastedSpan,
                intersectIdx,
                regionCount: tempRegions.length,
            });

            // 3. Ripple Shift: Move everything >= insertTime to the right
            //    by EXACTLY the packed paste span. Using pastedSpan rather
            //    than the original clipboardSpan keeps the next region
            //    flush against the last pasted item.
            const shiftedRegions = tempRegions.map(r => {
                if (r.timelineStart >= insertTime - 0.0001) {
                    return { ...r, timelineStart: r.timelineStart + pastedSpan };
                }
                return r;
            });

            const finalRegions = normalizeRegions(
                [...shiftedRegions, ...pastedRegions]
            ).sort((a, b) => a.timelineStart - b.timelineStart);

            return {
                ...state,
                regions: finalRegions,
                selectedRegionIds: new Set(pastedRegions.map(r => r.id)),
                project: { ...state.project, dirty: true },
            };
        }

        case 'DUPLICATE_SELECTION': {
            log.debug('Reducer: DUPLICATE_SELECTION', state.selectedRegionIds);
            const selectedRegions = state.regions.filter(r => state.selectedRegionIds.has(r.id));
            if (selectedRegions.length === 0) return state;

            const sorted = [...selectedRegions].sort((a, b) => a.timelineStart - b.timelineStart);
            const startT = sorted[0].timelineStart;
            const endT = sorted[sorted.length - 1].timelineStart + sorted[sorted.length - 1].duration;
            const duration = endT - startT;

            const duplicates = selectedRegions.map(r => ({
                ...r,
                id: crypto.randomUUID(),
                timelineStart: r.timelineStart + duration,
                timelineEnd: r.timelineStart + duration + r.duration
            }));

            const finalRegions = normalizeRegions(
                [...state.regions, ...duplicates]
            ).sort((a, b) => a.timelineStart - b.timelineStart);

            return {
                ...state,
                regions: finalRegions,
                selectedRegionIds: new Set(duplicates.map(r => r.id)),
                project: { ...state.project, dirty: true },
            };
        }

        // ── Selection ────────────────────────
        case 'SELECT_REGION':
            return {
                ...state,
                selectedRegionIds: new Set([action.payload]),
            };

        case 'TOGGLE_SELECT_REGION': {
            const newSet = new Set(state.selectedRegionIds);
            if (newSet.has(action.payload)) {
                newSet.delete(action.payload);
            } else {
                newSet.add(action.payload);
            }
            return { ...state, selectedRegionIds: newSet };
        }

        case 'CLEAR_SELECTION':
            return {
                ...state,
                selectedRegionIds: new Set(),
                selectionRange: null,
            };

        case 'SET_SELECTION_RANGE':
            return { ...state, selectionRange: action.payload };

        // ── Cue Points ───────────────────────
        case 'SET_HOT_CUE': {
            const { index, cue } = action.payload;  // index: 0-7
            const newHotCues = [...state.hotCues];
            newHotCues[index] = cue;
            return {
                ...state,
                hotCues: newHotCues,
                project: { ...state.project, dirty: true },
            };
        }

        case 'DELETE_HOT_CUE': {
            const newHotCues = [...state.hotCues];
            newHotCues[action.payload] = null;
            return {
                ...state,
                hotCues: newHotCues,
                project: { ...state.project, dirty: true },
            };
        }

        case 'ADD_MEMORY_CUE':
            return {
                ...state,
                memoryCues: [...state.memoryCues, action.payload]
                    .sort((a, b) => a.time - b.time),
                project: { ...state.project, dirty: true },
            };

        case 'REMOVE_MEMORY_CUE':
            return {
                ...state,
                memoryCues: state.memoryCues.filter((_, i) => i !== action.payload),
                project: { ...state.project, dirty: true },
            };

        // ── Loops ────────────────────────────
        case 'ADD_LOOP':
            return {
                ...state,
                loops: [...state.loops, action.payload],
                project: { ...state.project, dirty: true },
            };

        case 'REMOVE_LOOP':
            return {
                ...state,
                loops: state.loops.filter((_, i) => i !== action.payload),
                activeLoopIndex: state.activeLoopIndex === action.payload ? -1 : state.activeLoopIndex,
                project: { ...state.project, dirty: true },
            };

        case 'SET_ACTIVE_LOOP':
            return { ...state, activeLoopIndex: action.payload };

        case 'UPDATE_LOOP': {
            const { index: loopIdx, updates: loopUpdates } = action.payload;
            const newLoops = [...state.loops];
            newLoops[loopIdx] = { ...newLoops[loopIdx], ...loopUpdates };
            return {
                ...state,
                loops: newLoops,
                project: { ...state.project, dirty: true },
            };
        }

        // ── Transport ────────────────────────
        case 'SET_PLAYHEAD':
            return { ...state, playhead: Math.max(0, action.payload) };

        case 'SET_PLAYING':
            return { ...state, isPlaying: action.payload };

        // ── Dead Reckoning ───────────────────
        case 'SET_DEAD_RECKONING_SYNC':
            return { ...state, deadReckoning: { ...state.deadReckoning, ...action.payload } };

        case 'TOGGLE_LOOP':
            return { ...state, loopEnabled: !state.loopEnabled };

        case 'SET_LOOP_RANGE':
            return {
                ...state,
                loopStart: action.payload.start,
                loopEnd: action.payload.end,
                loopEnabled: true,
            };

        // ── View ─────────────────────────────
        case 'SET_ZOOM':
            return { ...state, zoom: Math.max(10, Math.min(2000, action.payload)) };

        case 'SET_SCROLL_X':
            return { ...state, scrollX: Math.max(-200, action.payload) };

        case 'SET_WAVEFORM_STYLE':
            return { ...state, waveformStyle: action.payload };

        case 'SHIFT_GRID': {
            const delta = action.payload; // seconds
            return {
                ...state,
                gridOffsetSec: (state.gridOffsetSec || 0) + delta,
                project: { ...state.project, dirty: true }
            };
        }

        case 'ADJUST_BPM': {
            const delta = action.payload; // bpm
            return {
                ...state,
                bpm: Math.max(1, (state.bpm || 120) + delta),
                project: { ...state.project, dirty: true }
            };
        }

        case 'TOGGLE_SNAP':
            return { ...state, snapEnabled: !state.snapEnabled };

        case 'SET_SNAP_DIVISION':
            return { ...state, snapDivision: action.payload };

        case 'SET_SLIP_MODE':
            return { ...state, slipMode: action.payload };

        case 'SET_TOOL':
            return { ...state, activeTool: action.payload };

        // ── Volume ───────────────────────────
        case 'SET_VOLUME_DATA':
            return { ...state, volumeData: action.payload };

        // ── History (Undo/Redo) ──────────────
        case 'PUSH_UNDO': {
            const snapshot = {
                regions: JSON.parse(JSON.stringify(state.regions)),
                hotCues: JSON.parse(JSON.stringify(state.hotCues)),
                memoryCues: JSON.parse(JSON.stringify(state.memoryCues)),
                loops: JSON.parse(JSON.stringify(state.loops)),
                label: action.payload || 'Edit',
            };
            const newUndoStack = [...state.undoStack, snapshot];
            if (newUndoStack.length > state.maxHistory) {
                newUndoStack.shift();
            }
            return {
                ...state,
                undoStack: newUndoStack,
                redoStack: [],  // Clear redo on new action
            };
        }

        case 'UNDO': {
            if (state.undoStack.length === 0) return state;
            const snapshot = state.undoStack[state.undoStack.length - 1];

            // Push current state to redo
            const currentSnapshot = {
                regions: JSON.parse(JSON.stringify(state.regions)),
                hotCues: JSON.parse(JSON.stringify(state.hotCues)),
                memoryCues: JSON.parse(JSON.stringify(state.memoryCues)),
                loops: JSON.parse(JSON.stringify(state.loops)),
                label: snapshot.label,
            };

            return {
                ...state,
                regions: snapshot.regions,
                hotCues: snapshot.hotCues,
                memoryCues: snapshot.memoryCues,
                loops: snapshot.loops,
                undoStack: state.undoStack.slice(0, -1),
                redoStack: [...state.redoStack, currentSnapshot],
                selectedRegionIds: new Set(),
                project: { ...state.project, dirty: true },
            };
        }

        case 'REDO': {
            if (state.redoStack.length === 0) return state;
            const snapshot = state.redoStack[state.redoStack.length - 1];

            // Push current state to undo
            const currentSnapshot = {
                regions: JSON.parse(JSON.stringify(state.regions)),
                hotCues: JSON.parse(JSON.stringify(state.hotCues)),
                memoryCues: JSON.parse(JSON.stringify(state.memoryCues)),
                loops: JSON.parse(JSON.stringify(state.loops)),
                label: snapshot.label,
            };

            return {
                ...state,
                regions: snapshot.regions,
                hotCues: snapshot.hotCues,
                memoryCues: snapshot.memoryCues,
                loops: snapshot.loops,
                undoStack: [...state.undoStack, currentSnapshot],
                redoStack: state.redoStack.slice(0, -1),
                selectedRegionIds: new Set(),
                project: { ...state.project, dirty: true },
            };
        }

        // ── Hydrate (load entire project state) ──
        case 'HYDRATE':
            // Loaded projects (.rbep / saved DAW state) routinely have stale
            // sourceEnd / mismatched sourceDuration left over by older
            // codepaths or third-party tools. Normalising on hydrate fixes
            // those at load time so the user can't carry old corruption
            // forward indefinitely.
            return {
                ...state,
                ...action.payload,
                regions: normalizeRegions(action.payload.regions || state.regions),
                undoStack: [],
                redoStack: [],
                selectedRegionIds: new Set(),
                project: { ...state.project, ...action.payload.project, dirty: false },
            };

        default:
            console.warn('[DawState] Unknown action:', action.type);
            return state;
    }
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

export default {
    createInitialState,
    dawReducer,
    getSnapUnit,
    snapToGrid,
    getPositionInfo,
    HOT_CUE_COLORS,
    stateToCuePoints,
    cuePointsToState,
};
