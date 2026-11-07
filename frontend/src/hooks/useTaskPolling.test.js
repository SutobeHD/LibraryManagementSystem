/**
 * node:test for the shared task-polling store (refcount, back-off, pause, kick).
 *
 *   node --import ./frontend/src/audio/dawState/dawReducer.test.resolver.mjs \
 *        --test frontend/src/hooks/useTaskPolling.test.js
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
    createTaskPollingStore,
    isAnyTaskRunning,
    isTaskStartRequest,
    TASK_POLL_ACTIVE_MS,
    TASK_POLL_IDLE_MS,
    TASK_POLL_KICK_WINDOW_MS,
} from './useTaskPolling';

const flush = () => new Promise((resolve) => setImmediate(resolve));

function fakeClock() {
    let t = 0;
    let seq = 0;
    const timers = new Map();
    return {
        now: () => t,
        setTimer: (fn, ms) => {
            seq += 1;
            timers.set(seq, { at: t + ms, fn });
            return seq;
        },
        clearTimer: (id) => timers.delete(id),
        pendingDelays: () => [...timers.values()].map((x) => x.at - t),
        async advance(ms) {
            const end = t + ms;
            for (;;) {
                let next = null;
                for (const [id, timer] of timers) {
                    if (timer.at <= end && (!next || timer.at < next[1].at)) next = [id, timer];
                }
                if (!next) break;
                timers.delete(next[0]);
                t = next[1].at;
                next[1].fn();
                await flush();
            }
            t = end;
            await flush();
        },
    };
}

const RUNNING = { a: { status: 'Downloading' } };
const DONE = { a: { status: 'Completed' } };

function setup({ responses = {}, hidden = false } = {}) {
    const clock = fakeClock();
    const calls = [];
    const state = { hidden, responses };
    const store = createTaskPollingStore({
        fetcher: async (url) => {
            calls.push({ url, at: clock.now() });
            const r = state.responses[url];
            if (r instanceof Error) throw r;
            return typeof r === 'function' ? r() : (r ?? {});
        },
        setTimer: clock.setTimer,
        clearTimer: clock.clearTimer,
        now: clock.now,
        isHidden: () => state.hidden,
    });
    return { store, clock, calls, state };
}

test('first subscriber polls immediately, idle cadence follows', async () => {
    const { store, clock, calls } = setup({ responses: { '/t': DONE } });
    store.subscribe('/t', () => {});
    await flush();
    assert.equal(calls.length, 1);
    assert.deepEqual(clock.pendingDelays(), [TASK_POLL_IDLE_MS]);
    await clock.advance(TASK_POLL_IDLE_MS - 1);
    assert.equal(calls.length, 1);
    await clock.advance(1);
    assert.equal(calls.length, 2);
});

test('subscribers share one poller and one request', async () => {
    const { store, clock, calls } = setup({ responses: { '/t': DONE } });
    let a = 0;
    let b = 0;
    store.subscribe('/t', () => (a += 1));
    await flush();
    store.subscribe('/t', () => (b += 1));
    await flush();
    assert.equal(calls.length, 1, 'fresh data → no extra request for the 2nd subscriber');
    assert.equal(store.size(), 1);
    await clock.advance(TASK_POLL_IDLE_MS);
    assert.equal(calls.length, 2);
    assert.equal(a, 2);
    assert.equal(b, 1);
});

test('late subscriber to stale data polls at once', async () => {
    const { store, clock, calls } = setup({ responses: { '/t': DONE } });
    store.subscribe('/t', () => {});
    await flush();
    await clock.advance(TASK_POLL_ACTIVE_MS);
    store.subscribe('/t', () => {});
    await flush();
    assert.equal(calls.length, 2);
});

test('running task → fast cadence, back to idle once terminal', async () => {
    const { store, clock, calls, state } = setup({ responses: { '/t': RUNNING } });
    store.subscribe('/t', () => {});
    await flush();
    assert.deepEqual(clock.pendingDelays(), [TASK_POLL_ACTIVE_MS]);
    await clock.advance(TASK_POLL_ACTIVE_MS * 2);
    assert.equal(calls.length, 3);
    state.responses['/t'] = DONE;
    await clock.advance(TASK_POLL_ACTIVE_MS);
    assert.equal(calls.length, 4);
    assert.deepEqual(clock.pendingDelays(), [TASK_POLL_IDLE_MS]);
});

test('custom isActive predicate drives the cadence', async () => {
    const { store, clock } = setup({ responses: { '/b': { finished: false } } });
    store.subscribe(
        '/b',
        () => {},
        (d) => !d?.finished
    );
    await flush();
    assert.deepEqual(clock.pendingDelays(), [TASK_POLL_ACTIVE_MS]);
});

test('last unsubscribe stops polling and drops the poller', async () => {
    const { store, clock, calls } = setup({ responses: { '/t': RUNNING } });
    const off1 = store.subscribe('/t', () => {});
    const off2 = store.subscribe('/t', () => {});
    await flush();
    off1();
    assert.equal(store.size(), 1);
    off2();
    off2(); // idempotent
    assert.equal(store.size(), 0);
    assert.deepEqual(clock.pendingDelays(), []);
    await clock.advance(TASK_POLL_IDLE_MS * 3);
    assert.equal(calls.length, 1);
});

test('unsubscribe while a poll is in flight leaves no timer behind', async () => {
    const { store, clock } = setup({ responses: { '/t': RUNNING } });
    const off = store.subscribe('/t', () => {});
    off();
    await flush();
    assert.deepEqual(clock.pendingDelays(), []);
    assert.equal(store.size(), 0);
});

test('hidden document pauses polling; visible again polls at once', async () => {
    const { store, clock, calls, state } = setup({ responses: { '/t': RUNNING }, hidden: true });
    store.subscribe('/t', () => {});
    await flush();
    assert.equal(calls.length, 0);
    assert.deepEqual(clock.pendingDelays(), []);
    state.hidden = false;
    store.handleVisibilityChange();
    await flush();
    assert.equal(calls.length, 1);
    state.hidden = true;
    store.handleVisibilityChange();
    assert.deepEqual(clock.pendingDelays(), []);
    await clock.advance(TASK_POLL_IDLE_MS * 2);
    assert.equal(calls.length, 1);
});

test('kick polls now and holds the fast cadence for the kick window', async () => {
    const { store, clock, calls } = setup({ responses: { '/t': DONE } });
    store.subscribe('/t', () => {});
    await flush();
    await clock.advance(TASK_POLL_ACTIVE_MS);
    store.kick();
    await flush();
    assert.equal(calls.length, 2);
    assert.deepEqual(clock.pendingDelays(), [TASK_POLL_ACTIVE_MS]);
    // Fast polls land every ACTIVE_MS until the window closes; the poll that
    // lands on the window edge re-arms at the idle cadence.
    await clock.advance(TASK_POLL_KICK_WINDOW_MS);
    assert.equal(calls.length, 2 + TASK_POLL_KICK_WINDOW_MS / TASK_POLL_ACTIVE_MS);
    assert.deepEqual(clock.pendingDelays(), [TASK_POLL_IDLE_MS]);
});

test('kick during an in-flight poll queues exactly one follow-up', async () => {
    let release;
    const { store, calls, state } = setup();
    state.responses['/t'] = () =>
        new Promise((resolve) => {
            release = () => resolve(DONE);
        });
    store.subscribe('/t', () => {});
    await flush();
    store.kick();
    store.kick();
    assert.equal(calls.length, 1, 'no concurrent request');
    release();
    await flush();
    assert.equal(calls.length, 2);
    release();
    await flush();
    assert.equal(calls.length, 2);
});

test('failed poll keeps the last good data and exposes the error', async () => {
    const { store, clock, state } = setup({ responses: { '/t': RUNNING } });
    store.subscribe('/t', () => {});
    await flush();
    state.responses['/t'] = new Error('backend busy');
    await clock.advance(TASK_POLL_ACTIVE_MS);
    const s = store.getState('/t');
    assert.deepEqual(s.data, RUNNING);
    assert.equal(s.error.message, 'backend busy');
});

test('refresh resolves with the fresh state', async () => {
    const { store, state } = setup({ responses: { '/t': DONE } });
    store.subscribe('/t', () => {});
    await flush();
    state.responses['/t'] = RUNNING;
    const s = await store.refresh('/t');
    assert.deepEqual(s.data, RUNNING);
});

test('isAnyTaskRunning treats only end states as idle', () => {
    assert.equal(isAnyTaskRunning(undefined), false);
    assert.equal(isAnyTaskRunning({}), false);
    assert.equal(isAnyTaskRunning(DONE), false);
    assert.equal(
        isAnyTaskRunning({ a: { status: 'Linked' }, b: { status: 'Analysis Failed' } }),
        false
    );
    assert.equal(isAnyTaskRunning({ a: { status: 'Tagging' } }), true);
    assert.equal(isAnyTaskRunning({ a: { status: 'Queued' }, b: { status: 'Failed' } }), true);
});

test('isTaskStartRequest matches task-starting mutations only', () => {
    assert.equal(isTaskStartRequest({ method: 'post', url: '/api/soundcloud/download' }), true);
    assert.equal(
        isTaskStartRequest({ method: 'post', url: '/api/soundcloud/download-playlist' }),
        true
    );
    assert.equal(isTaskStartRequest({ method: 'post', url: '/api/library/import-paths' }), true);
    assert.equal(isTaskStartRequest({ method: 'get', url: '/api/soundcloud/download' }), false);
    assert.equal(isTaskStartRequest({ method: 'post', url: '/api/system/heartbeat' }), false);
    assert.equal(isTaskStartRequest(undefined), false);
});
