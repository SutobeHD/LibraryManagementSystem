/**
 * selectionReducer — region selection set and time-range selection.
 *
 * Owns selectedRegionIds (Set) and selectionRange ({ start, end } or
 * null). Note that selection writes ALSO happen as side effects of
 * region mutations (REMOVE_REGION, SPLIT_REGION_AT, RIPPLE_DELETE,
 * PASTE_INSERT, DUPLICATE_SELECTION) — those are handled in
 * regionsReducer, not here, because the selection update is part of
 * the region-mutation atomic transaction.
 */

/**
 * Selection-domain reducer. Returns `state` unchanged for actions it
 * doesn't own — the barrel composes this with the other sub-reducers.
 *
 * @param {Object} state
 * @param {Object} action
 * @returns {Object}
 */
export function selectionReducer(state, action) {
    switch (action.type) {

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

        default:
            return state;
    }
}
