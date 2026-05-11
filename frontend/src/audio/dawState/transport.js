/**
 * transportReducer — playhead, BPM, zoom/scroll, snap-grid, edit-mode,
 * project metadata, and audio-source actions.
 *
 * Owns playback transport state (playhead, isPlaying, dead-reckoning
 * sync, loop range), tempo (BPM, tempo maps, grid offset), view state
 * (zoom, scroll, waveform style, snap, active tool), and the
 * non-region "shell" actions (project meta, track meta, source
 * buffer, peaks). These were grouped together because none of them
 * touch regions/cues/loops/selection/history.
 */

/**
 * Transport-domain reducer. Returns `state` unchanged for actions it
 * doesn't own — the barrel composes this with the other sub-reducers.
 *
 * @param {Object} state
 * @param {Object} action
 * @returns {Object}
 */
export function transportReducer(state, action) {
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

        default:
            return state;
    }
}
