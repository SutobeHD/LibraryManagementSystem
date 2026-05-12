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
    // Slice 2 — loops
    LOAD_LOOPS: 'LOAD_LOOPS',
    SET_LOOP: 'SET_LOOP',
    DELETE_LOOP: 'DELETE_LOOP',
    SET_ACTIVE_LOOP: 'SET_ACTIVE_LOOP',
    UPDATE_LOOP_FIELDS: 'UPDATE_LOOP_FIELDS',
    // Slice 3 — beatgrid
    LOAD_BEATGRID: 'LOAD_BEATGRID',
    ANCHOR_SHIFT: 'ANCHOR_SHIFT',
    SET_BPM: 'SET_BPM',
    UPDATE_BEAT: 'UPDATE_BEAT',
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
        case ACTIONS.LOAD_LOOPS:
            return { ...state, loops: action.payload.loops || [] };
        case ACTIONS.SET_LOOP: {
            const loop = action.payload;
            const filtered = state.loops.filter((l) => l.id !== loop.id);
            return {
                ...state,
                loops: [...filtered, loop].sort((a, b) => a.time_ms - b.time_ms),
            };
        }
        case ACTIONS.DELETE_LOOP:
            return {
                ...state,
                loops: state.loops.filter((l) => l.id !== action.payload.id),
            };
        case ACTIONS.SET_ACTIVE_LOOP:
            // Only one loop may be active per track (Q5 — CDJ active-loop).
            return {
                ...state,
                loops: state.loops.map((l) => ({
                    ...l,
                    status: l.id === action.payload.id ? 4 : 0,
                })),
            };
        case ACTIONS.UPDATE_LOOP_FIELDS:
            return {
                ...state,
                loops: state.loops.map((l) =>
                    l.id === action.payload.id ? { ...l, ...action.payload.fields } : l,
                ),
            };
        case ACTIONS.LOAD_BEATGRID:
            return { ...state, beatgrid: action.payload.beatgrid || [] };
        case ACTIONS.ANCHOR_SHIFT: {
            const dt = action.payload.delta_ms;
            return {
                ...state,
                beatgrid: state.beatgrid.map((b) => ({ ...b, time_ms: b.time_ms + dt })),
            };
        }
        case ACTIONS.SET_BPM: {
            // Regenerate beats from the existing anchor at the new BPM.
            // Preserves beat count and downbeat phase.
            const anchorMs = state.beatgrid[0]?.time_ms || 0;
            const count = state.beatgrid.length;
            if (count === 0) return state;
            const beatMs = (60 / Math.max(60, action.payload.bpm)) * 1000;
            const tempoCents = Math.round(action.payload.bpm * 100);
            const newGrid = Array.from({ length: count }, (_, i) => ({
                beat_number: (i % 4) + 1,
                time_ms: Math.round(anchorMs + i * beatMs),
                tempo: tempoCents,
            }));
            return { ...state, beatgrid: newGrid };
        }
        case ACTIONS.UPDATE_BEAT:
            return {
                ...state,
                beatgrid: state.beatgrid.map((b, i) =>
                    i === action.payload.index ? { ...b, ...action.payload.fields } : b,
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

    // Slice 2 — loop action creators
    const loadLoops = useCallback(
        ({ loops }) => dispatch({ type: ACTIONS.LOAD_LOOPS, payload: { loops } }),
        [],
    );
    const setLoop = useCallback(
        (loop) => dispatch({ type: ACTIONS.SET_LOOP, payload: loop }),
        [],
    );
    const deleteLoop = useCallback(
        (id) => dispatch({ type: ACTIONS.DELETE_LOOP, payload: { id } }),
        [],
    );
    const setActiveLoop = useCallback(
        (id) => dispatch({ type: ACTIONS.SET_ACTIVE_LOOP, payload: { id } }),
        [],
    );
    const updateLoopFields = useCallback(
        (id, fields) =>
            dispatch({ type: ACTIONS.UPDATE_LOOP_FIELDS, payload: { id, fields } }),
        [],
    );

    // Slice 3 — beatgrid action creators
    const loadBeatgrid = useCallback(
        ({ beatgrid }) =>
            dispatch({ type: ACTIONS.LOAD_BEATGRID, payload: { beatgrid } }),
        [],
    );
    const anchorShift = useCallback(
        (delta_ms) =>
            dispatch({ type: ACTIONS.ANCHOR_SHIFT, payload: { delta_ms } }),
        [],
    );
    const setBpm = useCallback(
        (bpm) => dispatch({ type: ACTIONS.SET_BPM, payload: { bpm } }),
        [],
    );
    const updateBeat = useCallback(
        (index, fields) =>
            dispatch({ type: ACTIONS.UPDATE_BEAT, payload: { index, fields } }),
        [],
    );

    const value = {
        state,
        dispatch,
        // Slice 1 — cues
        loadCues,
        setHotCue,
        deleteHotCue,
        setMemoryCue,
        deleteMemoryCue,
        updateHotCueFields,
        updateMemoryCueFields,
        // Slice 2 — loops
        loadLoops,
        setLoop,
        deleteLoop,
        setActiveLoop,
        updateLoopFields,
        // Slice 3 — beatgrid
        loadBeatgrid,
        anchorShift,
        setBpm,
        updateBeat,
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
