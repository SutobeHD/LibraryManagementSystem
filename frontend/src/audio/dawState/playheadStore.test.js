/**
 * Tests for the live playhead store (playheadStore.js).
 *
 * Plain node:test — no resolver needed (the store has no imports):
 *
 *   node --test frontend/src/audio/dawState/playheadStore.test.js
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { createPlayheadStore, PLAYHEAD_TICK_MS } from './playheadStore.js';

const fakeClock = (initial = null) => {
    let value = initial;
    return {
        read: () => value,
        set: (v) => {
            value = v;
        },
    };
};

test('tick interval is ~15 Hz', () => {
    assert.ok(PLAYHEAD_TICK_MS > 50 && PLAYHEAD_TICK_MS < 100);
});

test('starts at the clamped initial time', () => {
    assert.equal(createPlayheadStore({ initialTime: 12.5 }).getTime(), 12.5);
    assert.equal(createPlayheadStore({ initialTime: -3 }).getTime(), 0);
    assert.equal(createPlayheadStore().getTime(), 0);
});

test('setTime publishes, clamps negatives, and notifies subscribers', () => {
    const store = createPlayheadStore();
    let calls = 0;
    store.subscribe(() => calls++);
    store.setTime(4);
    assert.equal(store.getTime(), 4);
    assert.equal(calls, 1);
    store.setTime(-1);
    assert.equal(store.getTime(), 0);
    assert.equal(calls, 2);
});

test('setTime with an unchanged value does not notify', () => {
    const store = createPlayheadStore({ initialTime: 7 });
    let calls = 0;
    store.subscribe(() => calls++);
    store.setTime(7);
    assert.equal(calls, 0);
});

test('unsubscribe stops notifications', () => {
    const store = createPlayheadStore();
    let calls = 0;
    const unsubscribe = store.subscribe(() => calls++);
    unsubscribe();
    store.setTime(1);
    assert.equal(calls, 0);
});

test('tick publishes the clock and stamps dead-reckoning sync', () => {
    const clock = fakeClock(10.25);
    const store = createPlayheadStore({ readClock: clock.read });
    let calls = 0;
    store.subscribe(() => calls++);
    assert.equal(store.tick(5000), true);
    assert.equal(store.getTime(), 10.25);
    assert.equal(calls, 1);
    assert.deepEqual(store.getDeadReckoning(), {
        lastSyncWallClock: 5000,
        lastSyncAudioTime: 10.25,
    });
});

test('tick is a no-op while the clock is stopped', () => {
    // A stopped DawEngine reports its start offset; publishing that would
    // jump the display back at the end of playback.
    const clock = fakeClock(null);
    const store = createPlayheadStore({ initialTime: 3, readClock: clock.read });
    let calls = 0;
    store.subscribe(() => calls++);
    assert.equal(store.tick(1000), false);
    assert.equal(store.getTime(), 3);
    assert.equal(calls, 0);
    assert.equal(store.getDeadReckoning().lastSyncWallClock, 0);
});

test('tick with an unchanged clock value restamps sync but does not notify', () => {
    const clock = fakeClock(2);
    const store = createPlayheadStore({ readClock: clock.read });
    store.tick(100);
    let calls = 0;
    store.subscribe(() => calls++);
    store.tick(200);
    assert.equal(calls, 0);
    assert.equal(store.getDeadReckoning().lastSyncWallClock, 200);
});

test('getLiveTime reads the running clock, else the published value', () => {
    const clock = fakeClock(null);
    const store = createPlayheadStore({ initialTime: 8, readClock: clock.read });
    assert.equal(store.getLiveTime(), 8);
    clock.set(9.4);
    // Live read is exact even before the next tick publishes it.
    assert.equal(store.getLiveTime(), 9.4);
    assert.equal(store.getTime(), 8);
    clock.set(-0.01);
    assert.equal(store.getLiveTime(), 0);
});

test('snapshot is a primitive, stable between publishes (useSyncExternalStore contract)', () => {
    const store = createPlayheadStore({ initialTime: 1.5 });
    assert.equal(typeof store.getTime(), 'number');
    assert.ok(Object.is(store.getTime(), store.getTime()));
});
