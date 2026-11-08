/**
 * useTaskPolling — one shared poller per endpoint for background-task status.
 *
 * Replaces the per-component setInterval loops that each polled
 * /api/soundcloud/tasks and /api/import/tasks every 1.5–3 s, forever, on every
 * tab (≈3.5 req/s while nothing ran). Rules:
 *   - one poller per endpoint, refcounted: the global progress banner and the
 *     open view share a single request instead of each firing their own
 *   - TASK_POLL_ACTIVE_MS while any subscriber's isActive(data) holds,
 *     TASK_POLL_IDLE_MS otherwise
 *   - the first subscriber (or one that arrives to stale data) polls at once
 *   - zero subscribers → timer cleared, poller dropped
 *   - document.hidden → timers paused; visible again → immediate poll
 *   - a request that starts tasks (see TASK_START_URL_PREFIXES) kicks every
 *     poller: immediate poll + fast cadence for TASK_POLL_KICK_WINDOW_MS, so a
 *     new download/import reaches the banner within one fast interval even
 *     though the idle cadence is far slower
 *
 * A failed poll keeps the last good data (and exposes `error`): one dropped
 * request — normal while the backend holds the DB write lock — must not flash
 * the progress banner away.
 *
 * The store is plain JS (createTaskPollingStore) so node:test can drive it with
 * a fake clock; connectTaskPolling(api) wires the app's axios instance in once
 * at boot (main.jsx) — this module never imports api.js itself.
 */
import { useCallback, useRef, useSyncExternalStore } from 'react';

export const TASK_POLL_ACTIVE_MS = 1500;
export const TASK_POLL_IDLE_MS = 10000;
export const TASK_POLL_KICK_WINDOW_MS = 6000;

export const SC_TASKS_ENDPOINT = '/api/soundcloud/tasks';
export const IMPORT_TASKS_ENDPOINT = '/api/import/tasks';

// End states of import_tracker + SoundCloud downloader tasks. Anything else
// (Queued, Downloading, Tagging, Analyzing, …) counts as running.
export const TERMINAL_TASK_STATES = new Set([
    'Completed',
    'Failed',
    'Error',
    'Analysis Failed',
    'Skipped',
    'Linked',
    'Duplicate',
]);

// Mutating requests that register import / download tasks on the backend.
export const TASK_START_URL_PREFIXES = [
    '/api/soundcloud/download', // + /download-playlist
    '/api/soundcloud/sync', // + /sync-all
    '/api/audio/import',
    '/api/library/import-paths',
    '/api/library/format-swap/execute',
];

const EMPTY_STATE = Object.freeze({ data: undefined, error: null, updatedAt: 0 });

/** True when a `{ id: task }` snapshot holds at least one non-terminal task. */
export const isAnyTaskRunning = (snapshot) =>
    !!snapshot &&
    typeof snapshot === 'object' &&
    Object.values(snapshot).some((t) => !!t && !TERMINAL_TASK_STATES.has(t.status));

/** True for a successful non-GET axios request config that starts tasks. */
export const isTaskStartRequest = (config) => {
    if (!config || typeof config.url !== 'string') return false;
    if (String(config.method || 'get').toLowerCase() === 'get') return false;
    return TASK_START_URL_PREFIXES.some((prefix) => config.url.startsWith(prefix));
};

const notConnected = () => Promise.reject(new Error('task polling not connected'));

/**
 * Framework-free poller registry. All timing and I/O is injected so tests can
 * run it on a fake clock.
 */
export function createTaskPollingStore({
    fetcher = notConnected,
    setTimer = (fn, ms) => setTimeout(fn, ms),
    clearTimer = (id) => clearTimeout(id),
    now = () => Date.now(),
    isHidden = () => false,
} = {}) {
    let fetchFn = fetcher;
    const pollers = new Map();

    const computeActive = (p) => {
        for (const sub of p.subs) {
            if (sub.isActive(p.state.data)) return true;
        }
        return false;
    };

    const cancelTimer = (p) => {
        if (p.timer !== null) {
            clearTimer(p.timer);
            p.timer = null;
        }
    };

    const settleWaiters = (p) => {
        const waiters = p.waiters;
        p.waiters = [];
        waiters.forEach((resolve) => resolve(p.state));
    };

    const schedule = (p) => {
        cancelTimer(p);
        if (p.inFlight || p.subs.size === 0 || isHidden()) return;
        const fast = p.active || now() < p.fastUntil;
        p.timer = setTimer(
            () => {
                p.timer = null;
                poll(p);
            },
            fast ? TASK_POLL_ACTIVE_MS : TASK_POLL_IDLE_MS
        );
    };

    // Reschedule only when the cadence changed or nothing is pending —
    // re-arming on every subscriber change would keep pushing the poll back.
    const retune = (p, wasActive) => {
        if (p.inFlight) return;
        if (p.timer === null || p.active !== wasActive) schedule(p);
    };

    async function poll(p) {
        if (p.inFlight) {
            // The in-flight response may predate whatever triggered this call.
            p.again = true;
            return;
        }
        cancelTimer(p);
        p.inFlight = true;
        let next;
        try {
            const data = await fetchFn(p.endpoint);
            next = { data, error: null, updatedAt: now() };
        } catch (error) {
            next = { ...p.state, error };
        }
        p.inFlight = false;
        if (pollers.get(p.endpoint) !== p) return; // last subscriber left meanwhile
        p.state = next;
        p.active = computeActive(p);
        p.subs.forEach((sub) => sub.listener());
        if (p.again) {
            p.again = false;
            poll(p);
            return;
        }
        settleWaiters(p);
        schedule(p);
    }

    const subscribe = (endpoint, listener, isActive = isAnyTaskRunning) => {
        let p = pollers.get(endpoint);
        const isNew = !p;
        if (isNew) {
            p = {
                endpoint,
                subs: new Set(),
                state: EMPTY_STATE,
                timer: null,
                inFlight: false,
                again: false,
                active: false,
                fastUntil: 0,
                waiters: [],
            };
            pollers.set(endpoint, p);
        }
        const sub = { listener, isActive };
        p.subs.add(sub);
        const wasActive = p.active;
        p.active = computeActive(p);
        const stale = now() - p.state.updatedAt >= TASK_POLL_ACTIVE_MS;
        if (!isHidden() && (isNew || stale)) poll(p);
        else retune(p, wasActive);

        return () => {
            if (!p.subs.delete(sub)) return;
            if (p.subs.size > 0) {
                const before = p.active;
                p.active = computeActive(p);
                retune(p, before);
                return;
            }
            cancelTimer(p);
            pollers.delete(endpoint);
            settleWaiters(p);
        };
    };

    const getState = (endpoint) => pollers.get(endpoint)?.state ?? EMPTY_STATE;

    /** Poll now; resolves with the poller state once that poll has landed. */
    const refresh = (endpoint) => {
        const p = pollers.get(endpoint);
        if (!p) return Promise.resolve(EMPTY_STATE);
        return new Promise((resolve) => {
            p.waiters.push(resolve);
            poll(p);
        });
    };

    const kick = () => {
        const until = now() + TASK_POLL_KICK_WINDOW_MS;
        pollers.forEach((p) => {
            p.fastUntil = until;
            if (!isHidden()) poll(p);
        });
    };

    const handleVisibilityChange = () => {
        const hidden = isHidden();
        pollers.forEach((p) => {
            if (hidden) cancelTimer(p);
            else poll(p);
        });
    };

    const configure = ({ fetcher: nextFetcher } = {}) => {
        if (nextFetcher) fetchFn = nextFetcher;
    };

    return {
        subscribe,
        getState,
        refresh,
        kick,
        handleVisibilityChange,
        configure,
        size: () => pollers.size,
    };
}

const defaultStore = createTaskPollingStore({
    isHidden: () => typeof document !== 'undefined' && document.hidden === true,
});

let connected = false;

/**
 * Wire the shared store to the app's axios instance. Call once at boot:
 * sets the fetcher, kicks the pollers after task-starting requests, and pauses
 * polling while the window is hidden.
 */
export function connectTaskPolling(apiInstance) {
    if (connected) return;
    connected = true;
    defaultStore.configure({ fetcher: (url) => apiInstance.get(url).then((res) => res.data) });
    apiInstance.interceptors.response.use((res) => {
        if (isTaskStartRequest(res?.config)) defaultStore.kick();
        return res;
    });
    if (typeof document !== 'undefined') {
        document.addEventListener('visibilitychange', defaultStore.handleVisibilityChange);
    }
}

/**
 * Subscribe a component to the shared poller for `endpoint`. Pass a falsy
 * endpoint to stay unsubscribed (no request). `isActive(data)` decides the
 * fast cadence; it defaults to "any non-terminal task in a { id: task } map".
 *
 * @returns {{ data: any, error: Error|null, updatedAt: number, refresh: () => Promise<object> }}
 */
export function useTaskPolling(endpoint, { isActive = isAnyTaskRunning } = {}) {
    // Read through a ref so an inline predicate does not resubscribe every render.
    const isActiveRef = useRef(isActive);
    isActiveRef.current = isActive;

    const subscribe = useCallback(
        (onChange) =>
            endpoint
                ? defaultStore.subscribe(endpoint, onChange, (data) => isActiveRef.current(data))
                : () => {},
        [endpoint]
    );
    const getSnapshot = useCallback(
        () => (endpoint ? defaultStore.getState(endpoint) : EMPTY_STATE),
        [endpoint]
    );
    const state = useSyncExternalStore(subscribe, getSnapshot);
    const refresh = useCallback(
        () => (endpoint ? defaultStore.refresh(endpoint) : Promise.resolve(EMPTY_STATE)),
        [endpoint]
    );

    return { data: state.data, error: state.error, updatedAt: state.updatedAt, refresh };
}
