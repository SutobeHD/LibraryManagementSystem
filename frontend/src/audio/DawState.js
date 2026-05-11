/**
 * DawState — Central state management for the DJ Edit DAW.
 *
 * Barrel module: the actual reducer is split across one file per
 * domain in ./dawState/. This file composes them into the public
 * dawReducer and re-exports the helpers + initial-state factory the
 * rest of the codebase consumes. The exported surface (function
 * names, signatures, return shapes) is bit-for-bit identical to the
 * pre-split monolithic module.
 */

import { regionsReducer } from './dawState/regions';
import { transportReducer } from './dawState/transport';
import { selectionReducer } from './dawState/selection';
import { cuesReducer } from './dawState/cues';
import { historyReducer } from './dawState/history';
import {
    createInitialState, getSnapUnit, snapToGrid, getPositionInfo,
    HOT_CUE_COLORS, stateToCuePoints, cuePointsToState,
} from './dawState/helpers';

// Union of every action type owned by some sub-reducer. Used only to
// preserve the original reducer's "Unknown action" warning on stray
// dispatches — sub-reducers' switch statements are the source of truth.
const KNOWN_ACTIONS = new Set([
    'SET_PROJECT', 'SET_TRACK_META', 'MARK_DIRTY', 'MARK_CLEAN',
    'SET_SOURCE_BUFFER', 'SET_BAND_PEAKS', 'SET_FALLBACK_PEAKS',
    'SET_BPM', 'SET_TEMPO_MAP', 'SET_MASTER_TEMPO_MAP',
    'SET_PLAYHEAD', 'SET_PLAYING', 'SET_DEAD_RECKONING_SYNC',
    'TOGGLE_LOOP', 'SET_LOOP_RANGE', 'SET_ZOOM', 'SET_SCROLL_X',
    'SET_WAVEFORM_STYLE', 'SHIFT_GRID', 'ADJUST_BPM', 'TOGGLE_SNAP',
    'SET_SNAP_DIVISION', 'SET_SLIP_MODE', 'SET_TOOL', 'SET_REGIONS',
    'ADD_REGION', 'REMOVE_REGION', 'UPDATE_REGION', 'SPLIT_REGION_AT',
    'RIPPLE_DELETE', 'COPY_SELECTION', 'PASTE_INSERT',
    'DUPLICATE_SELECTION', 'SET_VOLUME_DATA', 'SELECT_REGION',
    'TOGGLE_SELECT_REGION', 'CLEAR_SELECTION', 'SET_SELECTION_RANGE',
    'SET_HOT_CUE', 'DELETE_HOT_CUE', 'ADD_MEMORY_CUE',
    'REMOVE_MEMORY_CUE', 'ADD_LOOP', 'REMOVE_LOOP', 'SET_ACTIVE_LOOP',
    'UPDATE_LOOP', 'PUSH_UNDO', 'UNDO', 'REDO', 'HYDRATE',
]);

/**
 * DAW state reducer. Composes per-domain reducers innermost-first
 * (history → cues → selection → transport → regions). Each
 * sub-reducer handles only its own action types and returns the state
 * unchanged otherwise, so passing the action through every layer is
 * safe. Cross-cutting writes (e.g. REMOVE_REGION dropping the id from
 * selectedRegionIds, UNDO restoring cues/loops alongside regions)
 * live inside the owning reducer's case so the transaction stays
 * atomic.
 */
export function dawReducer(state, action) {
    if (!KNOWN_ACTIONS.has(action.type)) {
        console.warn('[DawState] Unknown action:', action.type);
        return state;
    }
    return regionsReducer(transportReducer(selectionReducer(
        cuesReducer(historyReducer(state, action), action), action), action), action);
}

export {
    createInitialState, getSnapUnit, snapToGrid, getPositionInfo,
    HOT_CUE_COLORS, stateToCuePoints, cuePointsToState,
};

export default {
    createInitialState, dawReducer, getSnapUnit, snapToGrid,
    getPositionInfo, HOT_CUE_COLORS, stateToCuePoints, cuePointsToState,
};
