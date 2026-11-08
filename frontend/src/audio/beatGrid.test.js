/**
 * Beat-grid helpers + the waveform editor's computeBeats.
 *
 * Plain suite (CI runs it without a resolver), so the import chain carries `.js`:
 *   node --test frontend/src/audio/beatGrid.test.js
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
    normalizeBeatGrid,
    expandBeatGrid,
    beatGridToTempoMap,
    gridAnchorSec,
} from './beatGrid.js';
import computeBeats from '../components/waveform/computeBeats.js';

// First beats of a real ANLZ grid (track 127448057, 140 BPM): one entry per beat.
const ANLZ = [
    { time: 0.031, bpm: 140.0, beat: 1 },
    { time: 0.46, bpm: 140.0, beat: 2 },
    { time: 0.888, bpm: 140.0, beat: 3 },
    { time: 1.317, bpm: 140.0, beat: 4 },
];

const times = (beats) => beats.map((b) => Math.round(b.time * 1000) / 1000);

test('normalizeBeatGrid keeps valid entries, sorted, and nulls an unknown bar position', () => {
    assert.deepEqual(normalizeBeatGrid(null), []);
    assert.deepEqual(normalizeBeatGrid({ time: 1 }), []);
    assert.deepEqual(
        normalizeBeatGrid([
            { time: 2, bpm: 120, beat: 2 },
            { time: 'x', bpm: 120 },
            { time: -1, bpm: 120 },
            { time: 1, bpm: 0 },
            { time: 0.5, bpm: '128', beat: 7 },
        ]),
        [
            { time: 0.5, bpm: 128, beat: null },
            { time: 2, bpm: 120, beat: 2 },
        ]
    );
});

test('a per-beat ANLZ grid comes back beat for beat, without doubles', () => {
    const beats = expandBeatGrid(ANLZ, 1.5);
    assert.deepEqual(times(beats), [0.031, 0.46, 0.888, 1.317]);
    assert.deepEqual(
        beats.map((b) => b.beat),
        [1, 2, 3, 4]
    );
});

test('the last grid entry is extended to the end of the track', () => {
    const beats = expandBeatGrid(ANLZ, 3);
    const step = 60 / 140;
    assert.equal(beats.length, 7);
    assert.ok(Math.abs(beats[6].time - (1.317 + 3 * step)) < 1e-9);
    assert.deepEqual(
        beats.slice(4).map((b) => b.beat),
        [1, 2, 3]
    );
});

test('a sparse XML grid (one TEMPO per tempo change) is filled in per beat', () => {
    const beats = expandBeatGrid([{ time: 0.5, bpm: 120, beat: 1 }], 3);
    assert.deepEqual(times(beats), [0.5, 1, 1.5, 2, 2.5]);
    assert.deepEqual(
        beats.map((b) => b.beat),
        [1, 2, 3, 4, 1]
    );
});

test('a tempo change starts a new segment at its own BPM', () => {
    const beats = expandBeatGrid(
        [
            { time: 0, bpm: 120, beat: 1 },
            { time: 2, bpm: 60, beat: 1 },
        ],
        5
    );
    assert.deepEqual(times(beats), [0, 0.5, 1, 1.5, 2, 3, 4]);
    assert.deepEqual(
        beats.map((b) => b.bpm),
        [120, 120, 120, 120, 60, 60, 60]
    );
});

test('a grid that starts mid-bar keeps the Rekordbox bar position', () => {
    const beats = expandBeatGrid([{ time: 0.021, bpm: 160, beat: 3 }], 2);
    assert.deepEqual(
        beats.slice(0, 4).map((b) => b.beat),
        [3, 4, 1, 2]
    );
});

test('no grid or no duration expands to nothing', () => {
    assert.deepEqual(expandBeatGrid([], 10), []);
    assert.deepEqual(expandBeatGrid(ANLZ, 0), []);
    assert.deepEqual(expandBeatGrid(ANLZ, undefined), []);
});

test('beatGridToTempoMap yields the DAW tempo-map shape with ms positions', () => {
    const map = beatGridToTempoMap(ANLZ, 1.5);
    assert.deepEqual(map, [
        { index: 0, bpm: 140, positionMs: 31, beat: 1 },
        { index: 1, bpm: 140, positionMs: 460, beat: 2 },
        { index: 2, bpm: 140, positionMs: 888, beat: 3 },
        { index: 3, bpm: 140, positionMs: 1317, beat: 4 },
    ]);
});

test('gridAnchorSec picks the first downbeat, else the first beat', () => {
    assert.equal(gridAnchorSec([]), 0);
    assert.equal(gridAnchorSec(undefined), 0);
    assert.equal(gridAnchorSec(beatGridToTempoMap(ANLZ, 1.5)), 0.031);
    const midBar = beatGridToTempoMap([{ time: 0.418, bpm: 143, beat: 2 }], 5);
    assert.ok(Math.abs(gridAnchorSec(midBar) - (0.418 + 3 * (60 / 143))) < 1e-6);
    // .rbep / buildTempoMap entries carry no bar position.
    assert.equal(gridAnchorSec([{ index: 0, bpm: 128, positionMs: 250 }]), 0.25);
});

test('computeBeats follows the Rekordbox grid, bars included', () => {
    const beats = computeBeats([{ time: 0.021, bpm: 160, beat: 3 }], 160, 3);
    assert.equal(beats[0].time, 0.021);
    assert.deepEqual(
        beats.slice(0, 7).map((b) => [b.barNum, b.isDownbeat]),
        [
            [1, false],
            [1, false],
            [2, true],
            [2, false],
            [2, false],
            [2, false],
            [3, true],
        ]
    );
});

test('computeBeats falls back to even spacing from 0 without a grid', () => {
    const beats = computeBeats([], 120, 2);
    assert.deepEqual(times(beats), [0, 0.5, 1, 1.5]);
    assert.deepEqual(
        beats.map((b) => b.isDownbeat),
        [true, false, false, false]
    );
    assert.deepEqual(computeBeats([], 0, 2), []);
});
