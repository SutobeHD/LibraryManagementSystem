/**
 * cuesReducer — hot cues, memory cues, and loops.
 *
 * Owns hotCues[8] (slots A-H, nullable), memoryCues[] (sorted by
 * time), loops[] (with startTime/endTime/active/colour), and
 * activeLoopIndex (-1 = none active).
 */

/**
 * Cues-domain reducer. Returns `state` unchanged for actions it
 * doesn't own — the barrel composes this with the other sub-reducers.
 *
 * @param {Object} state
 * @param {Object} action
 * @returns {Object}
 */
export function cuesReducer(state, action) {
    switch (action.type) {

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

        default:
            return state;
    }
}
