/**
 * TimelineState - State management for the non-destructive audio editor
 * 
 * Manages all timeline state including regions, playback, selection,
 * palette clips, and editing state.
 */

import { createRegion, sortRegionsByPosition, calculateTimelineDuration } from './AudioRegion';

/**
 * Create initial timeline state
 * 
 * @param {Object} options - Initial configuration
 * @returns {TimelineState}
 */
export function createTimelineState(options = {}) {
    return {
        // Audio data
        sourceBuffer: null,           // Original AudioBuffer
        sourcePath: null,             // Path to source file
        sampleRate: 44100,            // Audio sample rate

        // Regions (the clips on the timeline)
        regions: [],                  // AudioRegion[]

        // Markers (Cues, Loops, Fades)
        markers: options.markers || [], // Marker[]

        // Beat grid & Phrases (Analysis)
        bpm: options.bpm || 120,
        beatGrid: options.beatGrid || [],
        phrases: options.phrases || [],
        gridOffset: 0,                // Offset in seconds for grid alignment

        // Playback
        isPlaying: false,
        playhead: 0,                  // Current playback position (seconds)

        // Zoom & scroll
        zoom: options.zoom || 50,     // Pixels per second
        scrollX: 0,                   // Horizontal scroll position

        // Selection
        selection: null,              // { start, end } or null
        selectedRegionIds: [],        // IDs of selected regions

        // Snap to grid
        snapEnabled: true,
        snapDivision: '1/4',          // '1/4', '1/8', '1/16', '1/32'

        // Palette (visual clipboard)
        paletteSlots: Array(8).fill(null),  // 8 slots for region clones

        // History for undo/redo
        history: [],
        historyIndex: -1,

        // UI state
        editMode: options.editMode || 'select', // 'select', 'cut', 'draw', 'grid'
        isRendering: false,
        renderProgress: 0
    };
}

/**
 * Calculate the beat duration based on BPM and division
 * 
 * @param {number} bpm - Beats per minute
 * @param {string} division - Snap division ('1/4', '1/8', '1/16', '1/32')
 * @returns {number} - Duration in seconds
 */
export function getSnapUnit(bpm, division) {
    const beatDuration = 60 / bpm;
    const divisionMap = {
        '1/1': beatDuration * 4,    // Whole bar
        '1/2': beatDuration * 2,    // Half bar
        '1/4': beatDuration,        // Quarter note (1 beat)
        '1/8': beatDuration / 2,    // Eighth note
        '1/16': beatDuration / 4,   // Sixteenth note
        '1/32': beatDuration / 8    // Thirty-second note
    };
    return divisionMap[division] || beatDuration;
}

/**
 * Snap a time value to the nearest grid position
 * 
 * @param {TimelineState} state - Current timeline state
 * @param {number} time - Time value to snap
 * @returns {number} - Snapped time value
 */
export function snapToGrid(state, time) {
    if (!state.snapEnabled) return time;

    // Support for Dynamic/Variable Grid
    if (state.beatGrid && state.beatGrid.length > 0) {
        // Find the nearest beat in the processed grid
        let closestBeat = state.beatGrid[0];
        let minDist = Math.abs(time - closestBeat.time);

        for (let i = 1; i < state.beatGrid.length; i++) {
            const dist = Math.abs(time - state.beatGrid[i].time);
            if (dist < minDist) {
                minDist = dist;
                closestBeat = state.beatGrid[i];
            } else if (state.beatGrid[i].time > time + 1.0) {
                break; // Optimized exit
            }
        }

        const beatDuration = 60 / closestBeat.bpm;
        const division = state.snapDivision || '1/4';
        const snapUnit = getSnapUnit(closestBeat.bpm, division);

        // Offset relative to the closest beat
        const offset = time - closestBeat.time;
        const snappedOffset = Math.round(offset / snapUnit) * snapUnit;
        return Math.max(0, closestBeat.time + snappedOffset);
    }

    // Fallback for static grid
    const snapUnit = getSnapUnit(state.bpm, state.snapDivision);
    const adjustedTime = time - state.gridOffset;
    const snappedTime = Math.round(adjustedTime / snapUnit) * snapUnit;
    return Math.max(0, snappedTime + state.gridOffset);
}

/**
 * Load audio source into timeline and create initial region
 * 
 * @param {TimelineState} state - Current state
 * @param {AudioBuffer} buffer - Audio buffer
 * @param {string} path - File path
 * @returns {TimelineState}
 */
export function loadAudioSource(state, buffer, path) {
    const initialRegion = createRegion({
        sourceBuffer: buffer,
        sourcePath: path,
        sourceStart: 0,
        sourceEnd: buffer.duration,
        timelineStart: 0,
        name: 'Main Track'
    });

    return {
        ...state,
        sourceBuffer: buffer,
        sourcePath: path,
        sampleRate: buffer.sampleRate,
        regions: [initialRegion]
    };
}

/**
 * Add a region to the timeline
 * 
 * @param {TimelineState} state 
 * @param {AudioRegion} region 
 * @returns {TimelineState}
 */
export function addRegion(state, region) {
    return {
        ...state,
        regions: [...state.regions, region]
    };
}

/**
 * Remove a region from the timeline
 * 
 * @param {TimelineState} state 
 * @param {string} regionId 
 * @returns {TimelineState}
 */
export function removeRegion(state, regionId) {
    return {
        ...state,
        regions: state.regions.filter(r => r.id !== regionId),
        selectedRegionIds: state.selectedRegionIds.filter(id => id !== regionId)
    };
}

/**
 * Update a region in the timeline
 * 
 * @param {TimelineState} state 
 * @param {string} regionId 
 * @param {Partial<AudioRegion>} updates 
 * @returns {TimelineState}
 */
export function updateRegion(state, regionId, updates) {
    return {
        ...state,
        regions: state.regions.map(r => {
            if (r.id !== regionId) return r;

            // Merge updates to get potential new state
            // valid properties: sourceStart, sourceEnd, timelineStart
            const next = { ...r, ...updates };

            // Recalculate dependent properties if inputs changed
            // This is necessary because we removed getters in AudioRegion.js to avoid spread-flattening
            if ('sourceStart' in updates || 'sourceEnd' in updates) {
                next.duration = next.sourceEnd - next.sourceStart;
            }

            // Recalculate timelineEnd if duration or timelineStart changed
            // Note: duration might have changed above
            if ('timelineStart' in updates || 'sourceStart' in updates || 'sourceEnd' in updates) {
                next.timelineEnd = next.timelineStart + next.duration;
            }

            return next;
        })
    };
}

/**
 * Set selection range
 * 
 * @param {TimelineState} state 
 * @param {number|null} start 
 * @param {number|null} end 
 * @returns {TimelineState}
 */
export function setSelection(state, start, end) {
    if (start === null || end === null) {
        return { ...state, selection: null };
    }
    return {
        ...state,
        selection: { start: Math.min(start, end), end: Math.max(start, end) }
    };
}

/**
 * Select regions by ID
 * 
 * @param {TimelineState} state 
 * @param {string[]} regionIds 
 * @param {boolean} [addToSelection=false] 
 * @returns {TimelineState}
 */
export function selectRegions(state, regionIds, addToSelection = false) {
    const newSelection = addToSelection
        ? [...new Set([...state.selectedRegionIds, ...regionIds])]
        : regionIds;

    return {
        ...state,
        selectedRegionIds: newSelection,
        regions: state.regions.map(r => ({
            ...r,
            isSelected: newSelection.includes(r.id)
        }))
    };
}

/**
 * Clear all selections
 * 
 * @param {TimelineState} state 
 * @returns {TimelineState}
 */
export function clearSelection(state) {
    return {
        ...state,
        selection: null,
        selectedRegionIds: [],
        regions: state.regions.map(r => ({ ...r, isSelected: false }))
    };
}

/**
 * Add region to palette slot
 * 
 * @param {TimelineState} state 
 * @param {number} slotIndex 
 * @param {AudioRegion|null} region 
 * @returns {TimelineState}
 */
export function setPaletteSlot(state, slotIndex, region) {
    if (slotIndex < 0 || slotIndex >= state.paletteSlots.length) {
        return state;
    }

    const newSlots = [...state.paletteSlots];
    newSlots[slotIndex] = region;

    return {
        ...state,
        paletteSlots: newSlots
    };
}

/**
 * Find first empty palette slot
 * 
 * @param {TimelineState} state 
 * @returns {number} - Slot index or -1 if all full
 */
export function findEmptyPaletteSlot(state) {
    return state.paletteSlots.findIndex(slot => slot === null);
}

/**
 * Set playhead position
 * 
 * @param {TimelineState} state 
 * @param {number} position 
 * @returns {TimelineState}
 */
export function setPlayhead(state, position) {
    return {
        ...state,
        playhead: Math.max(0, position)
    };
}

/**
 * Toggle snap to grid
 * 
 * @param {TimelineState} state 
 * @returns {TimelineState}
 */
export function toggleSnap(state) {
    return {
        ...state,
        snapEnabled: !state.snapEnabled
    };
}

/**
 * Set snap division
 * 
 * @param {TimelineState} state 
 * @param {string} division 
 * @returns {TimelineState}
 */
export function setSnapDivision(state, division) {
    return {
        ...state,
        snapDivision: division
    };
}

/**
 * Set zoom level
 * 
 * @param {TimelineState} state 
 * @param {number} zoom - Pixels per second
 * @returns {TimelineState}
 */
export function setZoom(state, zoom) {
    return {
        ...state,
        zoom: Math.max(10, Math.min(500, zoom))
    };
}

/**
 * Shift the entire beat grid by an offset
 * 
 * @param {TimelineState} state 
 * @param {number} offsetSeconds 
 * @returns {TimelineState}
 */
export function shiftGrid(state, offsetSeconds) {
    if (!state.beatGrid || state.beatGrid.length === 0) {
        return {
            ...state,
            gridOffset: state.gridOffset + offsetSeconds
        };
    }

    return {
        ...state,
        beatGrid: state.beatGrid.map(beat => ({
            ...beat,
            time: Math.max(0, beat.time + offsetSeconds)
        })),
        gridOffset: state.gridOffset + offsetSeconds
    };
}

/**
 * Adjust BPM (stretch/contract grid)
 * 
 * @param {TimelineState} state 
 * @param {number} newBpm 
 * @returns {TimelineState}
 */
export function adjustBPM(state, newBpm) {
    if (newBpm <= 0) return state;

    // If we have a beat grid, we need to recalculate times
    // This assumes a constant BPM for now for simplicity in manual editing
    if (state.beatGrid && state.beatGrid.length > 0) {
        const firstBeatTime = state.beatGrid[0].time;
        const beatDuration = 60 / newBpm;

        return {
            ...state,
            bpm: newBpm,
            beatGrid: state.beatGrid.map((beat, i) => ({
                ...beat,
                bpm: newBpm,
                time: firstBeatTime + (i * beatDuration)
            }))
        };
    }

    return {
        ...state,
        bpm: newBpm
    };
}

/**
 * Push to history for undo
 * 
 * @param {TimelineState} state 
 * @param {Object} action 
 * @returns {TimelineState}
 */
export function pushHistory(state, action) {
    const MAX_HISTORY = 50;
    let newHistory = state.history.slice(0, state.historyIndex + 1);

    // Create snapshot of regions
    // We utilize shallow copy to preserve AudioBuffer references (which are not serializable)
    // while ensuring the array structure is independent.
    const regionsSnapshot = state.regions.map(r => ({ ...r }));

    newHistory.push({
        ...action,
        timestamp: Date.now(),
        regions: regionsSnapshot
    });

    // Limit history size
    if (newHistory.length > MAX_HISTORY) {
        newHistory = newHistory.slice(newHistory.length - MAX_HISTORY);
    }

    return {
        ...state,
        history: newHistory,
        historyIndex: newHistory.length - 1
    };
}

/**
 * Undo last action
 * 
 * @param {TimelineState} state 
 * @returns {TimelineState}
 */
export function undo(state) {
    if (state.historyIndex < 0) return state;

    const previousState = state.history[state.historyIndex];
    return {
        ...state,
        regions: previousState.regions,
        historyIndex: state.historyIndex - 1
    };
}

/**
 * Redo undone action
 * 
 * @param {TimelineState} state 
 * @returns {TimelineState}
 */
export function redo(state) {
    if (state.historyIndex >= state.history.length - 1) return state;

    const nextState = state.history[state.historyIndex + 1];
    return {
        ...state,
        regions: nextState.regions,
        historyIndex: state.historyIndex + 1
    };
}

/**
 * Get timeline duration (end of last region)
 * 
 * @param {TimelineState} state 
 * @returns {number}
 */
export function getTimelineDuration(state) {
    return calculateTimelineDuration(state.regions);
}

/**
 * Get sorted regions
 * 
 * @param {TimelineState} state 
 * @returns {AudioRegion[]}
 */
export function getSortedRegions(state) {
    return sortRegionsByPosition(state.regions);
}

export default {
    createTimelineState,
    getSnapUnit,
    snapToGrid,
    loadAudioSource,
    addRegion,
    removeRegion,
    updateRegion,
    setSelection,
    selectRegions,
    clearSelection,
    setPaletteSlot,
    findEmptyPaletteSlot,
    setPlayhead,
    toggleSnap,
    setSnapDivision,
    setZoom,
    pushHistory,
    undo,
    redo,
    getTimelineDuration,
    getSortedRegions
};
