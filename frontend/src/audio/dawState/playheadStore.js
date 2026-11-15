/**
 * playheadStore — live transport position, kept outside the DAW reducer.
 *
 * The reducer's `playhead` is the parked cursor: it changes on seek,
 * stop and hydrate only. While playing, the position advances ~15x/s;
 * routing that through the reducer gave every memoised DAW child a new
 * `state` per tick and re-rendered the whole tree. This store holds the
 * live value instead, so only its subscribers (time display, overview
 * line) re-render.
 *
 * Shape fits React's `useSyncExternalStore(store.subscribe, store.getTime)`.
 * No React / DawEngine import here — the audio clock is injected via
 * `readClock`, which keeps the logic testable under plain node:test.
 */

/** Interval between published playback ticks (ms) — ~15 Hz. */
export const PLAYHEAD_TICK_MS = 66;

/**
 * @param {Object}   [opts]
 * @param {number}   [opts.initialTime=0]  parked position (seconds)
 * @param {Function} [opts.readClock]      () => number|null — live audio time
 *                                         while the engine plays, null otherwise
 * @returns {{
 *   getTime: () => number,
 *   getLiveTime: () => number,
 *   getDeadReckoning: () => { lastSyncWallClock: number, lastSyncAudioTime: number },
 *   setTime: (t: number) => void,
 *   tick: (wallClock: number) => boolean,
 *   subscribe: (listener: Function) => Function,
 * }}
 */
export function createPlayheadStore({ initialTime = 0, readClock = () => null } = {}) {
    let time = Math.max(0, initialTime);
    let deadReckoning = { lastSyncWallClock: 0, lastSyncAudioTime: time };
    const listeners = new Set();

    const publish = (next) => {
        if (next === time) return;
        time = next;
        for (const listener of listeners) listener();
    };

    return {
        /** Last published position — the useSyncExternalStore snapshot. */
        getTime: () => time,

        /**
         * Exact position for event handlers (set hot cue, loop in/out,
         * split, paste). Reads the audio clock while it runs, so a click
         * between two ticks does not land up to one tick late.
         */
        getLiveTime: () => {
            const live = readClock();
            return live == null ? time : Math.max(0, live);
        },

        /** Wall-clock + audio time of the last playback tick. */
        getDeadReckoning: () => deadReckoning,

        /** Parked position (seek, stop, hydrate). */
        setTime: (t) => publish(Math.max(0, t)),

        /**
         * Playback tick: publish the audio clock. Returns false (and
         * changes nothing) when the clock is not running — the engine
         * reports its start offset, not the stop position, once stopped.
         */
        tick: (wallClock) => {
            const live = readClock();
            if (live == null) return false;
            const next = Math.max(0, live);
            deadReckoning = { lastSyncWallClock: wallClock, lastSyncAudioTime: next };
            publish(next);
            return true;
        },

        subscribe: (listener) => {
            listeners.add(listener);
            return () => listeners.delete(listener);
        },
    };
}
