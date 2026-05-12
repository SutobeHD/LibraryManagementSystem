/**
 * useTrackEditorState — shared state for the cue / loop / beatgrid /
 * metadata editor surfaces (WaveformEditor + DjEditDaw).
 *
 * Context + useReducer pattern (matches frontend/src/components/ToastContext.jsx
 * style). State is filled slice by slice during the
 * waveform-editor-extensions implementation:
 *
 *   - Slice 1: cues + hotCues  <-- CURRENT
 *   - Slice 2: loops
 *   - Slice 3: beatgrid
 *   - Slice 4: metadata
 *   - Slice 5: history (persistent 3-step undo)
 *
 * See docs/research/implement/inprogress_waveform-editor-extensions.md.
 */

import { createContext, useCallback, useContext, useReducer } from 'react';

const TrackEditorContext = createContext(null);

const initialState = {
    // Slice 1
    hotCues: [],   // [{ number 1..8, time_ms, color_id, color_rgb, name, status, type:'hot_cue' }, ...]
    cues: [],      // memory cues — [{ id, time_ms, color_id, color_rgb, name, status, type:'memory_cue' }, ...]
    // Slice 2
    loops: [],
    // Slice 3
    beatgrid: [],
    // Slice 4
    metadata: null,
    // Slice 5
    history: [],
    historyIdx: -1,
};

const ACTIONS = {
    LOAD_CUES: 'LOAD_CUES',
    SET_HOT_CUE: 'SET_HOT_CUE',
    DELETE_HOT_CUE: 'DELETE_HOT_CUE',
    SET_MEMORY_CUE: 'SET_MEMORY_CUE',
    DELETE_MEMORY_CUE: 'DELETE_MEMORY_CUE',
    UPDATE_HOT_CUE_FIELDS: 'UPDATE_HOT_CUE_FIELDS',
    UPDATE_MEMORY_CUE_FIELDS: 'UPDATE_MEMORY_CUE_FIELDS',
};

function reducer(state, action) {
    switch (action.type) {
        case ACTIONS.LOAD_CUES:
            return {
                ...state,
                hotCues: action.payload.hotCues || [],
                cues: action.payload.cues || [],
            };
        case ACTIONS.SET_HOT_CUE: {
            const cue = action.payload;
            const filtered = state.hotCues.filter((c) => c.number !== cue.number);
            return {
                ...state,
                hotCues: [...filtered, cue].sort((a, b) => a.number - b.number),
            };
        }
        case ACTIONS.DELETE_HOT_CUE:
            return {
                ...state,
                hotCues: state.hotCues.filter((c) => c.number !== action.payload.number),
            };
        case ACTIONS.SET_MEMORY_CUE: {
            const cue = action.payload;
            const filtered = state.cues.filter((c) => c.id !== cue.id);
            return {
                ...state,
                cues: [...filtered, cue].sort((a, b) => a.time_ms - b.time_ms),
            };
        }
        case ACTIONS.DELETE_MEMORY_CUE:
            return {
                ...state,
                cues: state.cues.filter((c) => c.id !== action.payload.id),
            };
        case ACTIONS.UPDATE_HOT_CUE_FIELDS:
            return {
                ...state,
                hotCues: state.hotCues.map((c) =>
                    c.number === action.payload.number ? { ...c, ...action.payload.fields } : c,
                ),
            };
        case ACTIONS.UPDATE_MEMORY_CUE_FIELDS:
            return {
                ...state,
                cues: state.cues.map((c) =>
                    c.id === action.payload.id ? { ...c, ...action.payload.fields } : c,
                ),
            };
        default:
            return state;
    }
}

export function TrackEditorProvider({ children }) {
    const [state, dispatch] = useReducer(reducer, initialState);

    const loadCues = useCallback(
        ({ hotCues, cues }) =>
            dispatch({ type: ACTIONS.LOAD_CUES, payload: { hotCues, cues } }),
        [],
    );
    const setHotCue = useCallback(
        (cue) => dispatch({ type: ACTIONS.SET_HOT_CUE, payload: cue }),
        [],
    );
    const deleteHotCue = useCallback(
        (number) => dispatch({ type: ACTIONS.DELETE_HOT_CUE, payload: { number } }),
        [],
    );
    const setMemoryCue = useCallback(
        (cue) => dispatch({ type: ACTIONS.SET_MEMORY_CUE, payload: cue }),
        [],
    );
    const deleteMemoryCue = useCallback(
        (id) => dispatch({ type: ACTIONS.DELETE_MEMORY_CUE, payload: { id } }),
        [],
    );
    const updateHotCueFields = useCallback(
        (number, fields) =>
            dispatch({ type: ACTIONS.UPDATE_HOT_CUE_FIELDS, payload: { number, fields } }),
        [],
    );
    const updateMemoryCueFields = useCallback(
        (id, fields) =>
            dispatch({ type: ACTIONS.UPDATE_MEMORY_CUE_FIELDS, payload: { id, fields } }),
        [],
    );

    const value = {
        state,
        dispatch,
        loadCues,
        setHotCue,
        deleteHotCue,
        setMemoryCue,
        deleteMemoryCue,
        updateHotCueFields,
        updateMemoryCueFields,
    };

    return (
        <TrackEditorContext.Provider value={value}>{children}</TrackEditorContext.Provider>
    );
}

export default function useTrackEditorState() {
    const ctx = useContext(TrackEditorContext);
    if (!ctx) {
        throw new Error('useTrackEditorState must be used inside <TrackEditorProvider>');
    }
    return ctx;
}
