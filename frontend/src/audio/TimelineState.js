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

        // Beat grid
        bpm: options.bpm || 120,
        beatGrid: options.beatGrid || [],
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
        editMode: 'select',           // 'select', 'cut', 'draw'
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

    const snapUnit = getSnapUnit(state.bpm, state.snapDivision);
    const offset = state.gridOffset;

    // Adjust for grid offset, snap, then add offset back
    const adjustedTime = time - offset;
    const snappedTime = Math.round(adjustedTime / snapUnit) * snapUnit;
    return Math.max(0, snappedTime + offset);
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
        regions: state.regions.map(r =>
            r.id === regionId ? { ...r, ...updates } : r
        )
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
 * Push to history for undo
 * 
 * @param {TimelineState} state 
 * @param {Object} action 
 * @returns {TimelineState}
 */
export function pushHistory(state, action) {
    const newHistory = state.history.slice(0, state.historyIndex + 1);
    newHistory.push({
        ...action,
        timestamp: Date.now(),
        regions: JSON.parse(JSON.stringify(state.regions)) // Deep copy
    });

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
