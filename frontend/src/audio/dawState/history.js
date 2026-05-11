/**
 * historyReducer — undo / redo full-state snapshots + HYDRATE.
 *
 * Snapshots capture regions + hotCues + memoryCues + loops via deep
 * clone (JSON round-trip) so the user can revert structural edits
 * without losing their cue/loop work. UNDO/REDO also clear the
 * selection set — restored regions have different ids than whatever
 * the user was holding, so keeping selections would be stale.
 *
 * HYDRATE lives here too because loading a project is conceptually a
 * full-state reset: both stacks are cleared and the selection set is
 * wiped, just like an UNDO/REDO transition.
 */

import { normalizeRegions } from './helpers';

/**
 * History-domain reducer. Returns `state` unchanged for actions it
 * doesn't own — the barrel composes this with the other sub-reducers.
 *
 * @param {Object} state
 * @param {Object} action
 * @returns {Object}
 */
export function historyReducer(state, action) {
    switch (action.type) {

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
            return state;
    }
}
