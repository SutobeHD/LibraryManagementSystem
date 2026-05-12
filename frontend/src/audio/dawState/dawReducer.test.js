/**
 * Tests for the composed dawReducer (DawState.js barrel) — Phase 4B split.
 *
 * Uses Node's built-in test runner. From the project root:
 *
 *   node --import ./frontend/src/audio/dawState/dawReducer.test.resolver.mjs \
 *        --test frontend/src/audio/dawState/dawReducer.test.js
 *
 * The resolver hook (`.resolver.mjs` + `.resolver-impl.mjs`) lets raw
 * Node load the Vite-style extensionless imports the sub-reducers use
 * (`from './helpers'` etc.). The reducer function under test is
 * recomposed locally with the same innermost-first ordering the
 * barrel uses — that's the contract we want to pin.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { createInitialState } from '../dawState/helpers.js';
import { regionsReducer } from '../dawState/regions.js';
import { transportReducer } from '../dawState/transport.js';
import { selectionReducer } from '../dawState/selection.js';
import { cuesReducer } from '../dawState/cues.js';
import { historyReducer } from '../dawState/history.js';

// Mirror DawState.js exactly — innermost-first composition.
function dawReducer(state, action) {
    return regionsReducer(
        transportReducer(
            selectionReducer(
                cuesReducer(historyReducer(state, action), action),
                action,
            ),
            action,
        ),
        action,
    );
}

// ---------------------------------------------------------------------------
// createInitialState shape
// ---------------------------------------------------------------------------

test('createInitialState returns the expected shape', () => {
    const s = createInitialState();

    // Collections start empty / default
    assert.deepEqual(s.regions, []);
    assert.equal(s.hotCues.length, 8);
    assert.ok(s.hotCues.every(c => c === null), 'hotCues should be all null');
    assert.deepEqual(s.memoryCues, []);
    assert.deepEqual(s.loops, []);
    assert.ok(s.selectedRegionIds instanceof Set, 'selectedRegionIds is a Set');
    assert.equal(s.selectedRegionIds.size, 0);
    assert.deepEqual(s.undoStack, []);
    assert.deepEqual(s.redoStack, []);

    // Numeric defaults
    assert.equal(s.bpm, 128);
    assert.equal(s.playhead, 0);
    assert.equal(s.isPlaying, false);
    assert.equal(s.zoom, 100);

    // Project meta
    assert.equal(s.project.dirty, false);
    assert.equal(s.activeTool, 'select');
    assert.equal(s.snapEnabled, true);
});

test('createInitialState honours overrides', () => {
    const s = createInitialState({ bpm: 140, playhead: 5 });
    assert.equal(s.bpm, 140);
    assert.equal(s.playhead, 5);
    // Untouched defaults still present:
    assert.equal(s.isPlaying, false);
});

// ---------------------------------------------------------------------------
// ADD_REGION
// ---------------------------------------------------------------------------

test('ADD_REGION appends a normalized region', () => {
    const s = createInitialState();
    const next = dawReducer(s, {
        type: 'ADD_REGION',
        payload: {
            id: 'r1',
            timelineStart: 0,
            duration: 2,
            sourceStart: 0,
            sourceDuration: 2,
        },
    });
    assert.equal(next.regions.length, 1);
    assert.equal(next.regions[0].id, 'r1');
    assert.equal(next.regions[0].timelineEnd, 2);
    // dirty flag must be flipped after a content edit:
    assert.equal(next.project.dirty, true);
});

test('ADD_REGION with zero duration drops the region', () => {
    const s = createInitialState();
    const next = dawReducer(s, {
        type: 'ADD_REGION',
        payload: { id: 'zero', timelineStart: 0, duration: 0 },
    });
    // normalizeRegion returns null for duration<=0, then the reducer
    // short-circuits and returns the input state unchanged.
    assert.equal(next.regions.length, 0);
});

// ---------------------------------------------------------------------------
// SET_PLAYHEAD / SET_BPM
// ---------------------------------------------------------------------------

test('SET_PLAYHEAD updates playhead', () => {
    const s = createInitialState();
    const next = dawReducer(s, { type: 'SET_PLAYHEAD', payload: 5.0 });
    assert.equal(next.playhead, 5.0);
});

test('SET_PLAYHEAD clamps negative values to 0', () => {
    const s = createInitialState();
    const next = dawReducer(s, { type: 'SET_PLAYHEAD', payload: -3 });
    assert.equal(next.playhead, 0);
});

test('SET_BPM updates BPM', () => {
    const s = createInitialState();
    const next = dawReducer(s, { type: 'SET_BPM', payload: 130 });
    assert.equal(next.bpm, 130);
});

// ---------------------------------------------------------------------------
// Undo / Redo
// ---------------------------------------------------------------------------

test('PUSH_UNDO then UNDO restores the prior region state', () => {
    const s0 = createInitialState();

    // Snapshot the empty state to undoStack:
    const s1 = dawReducer(s0, { type: 'PUSH_UNDO', payload: 'add region' });
    assert.equal(s1.undoStack.length, 1);

    // Now mutate — add a region:
    const s2 = dawReducer(s1, {
        type: 'ADD_REGION',
        payload: { id: 'r1', timelineStart: 0, duration: 1, sourceDuration: 1 },
    });
    assert.equal(s2.regions.length, 1);

    // UNDO should restore regions to []:
    const s3 = dawReducer(s2, { type: 'UNDO' });
    assert.equal(s3.regions.length, 0);
    // The previous "current" goes onto redoStack:
    assert.equal(s3.redoStack.length, 1);
    // And undoStack is now empty:
    assert.equal(s3.undoStack.length, 0);
});

test('UNDO with empty undoStack is a no-op', () => {
    const s = createInitialState();
    const next = dawReducer(s, { type: 'UNDO' });
    assert.equal(next, s, 'state should be returned unchanged');
});

// ---------------------------------------------------------------------------
// Unknown action — must not throw and must return state unchanged.
// (Note: the DawState.js barrel emits a console.warn for unknown actions,
// but the SUB-REDUCERS we compose here all pass through silently. The
// composition is otherwise byte-for-byte the same.)
// ---------------------------------------------------------------------------

test('unknown action type does not throw and returns state unchanged', () => {
    const s = createInitialState();
    const next = dawReducer(s, { type: 'NOPE_NOT_A_REAL_ACTION', payload: 42 });
    // Each sub-reducer hits its default branch and returns the same state ref.
    assert.equal(next, s);
});
