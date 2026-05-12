/**
 * useTrackEditorState — shared state for the cue / loop / beatgrid /
 * metadata editor surfaces (WaveformEditor + DjEditDaw).
 *
 * Context + useReducer pattern (matches frontend/src/components/ToastContext.jsx
 * style). State is filled slice by slice during the
 * waveform-editor-extensions implementation:
 *
 *   - Slice 1: cues + hotCues
 *   - Slice 2: loops
 *   - Slice 3: beatgrid
 *   - Slice 4: metadata
 *   - Slice 5: history (persistent 3-step undo)
 *
 * See docs/research/implement/inprogress_waveform-editor-extensions.md.
 */

import { createContext, useContext, useReducer } from 'react';

const TrackEditorContext = createContext(null);

const initialState = {
    // Slice 1 — filled later
    hotCues: [],
    cues: [],
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

function reducer(state, _action) {
    // Actions are added slice by slice. For now the reducer is a no-op so
    // the provider mounts cleanly without producing dead-action warnings.
    return state;
}

export function TrackEditorProvider({ children }) {
    const [state, dispatch] = useReducer(reducer, initialState);
    return (
        <TrackEditorContext.Provider value={{ state, dispatch }}>
            {children}
        </TrackEditorContext.Provider>
    );
}

export default function useTrackEditorState() {
    const ctx = useContext(TrackEditorContext);
    if (!ctx) {
        throw new Error('useTrackEditorState must be used inside <TrackEditorProvider>');
    }
    return ctx;
}
