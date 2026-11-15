/**
 * usePlayheadClock — owns the live playhead store for one DAW instance.
 *
 *   • Parked: mirrors the reducer's `playhead` into the store.
 *   • Playing: a RAF loop publishes DawEngine time every PLAYHEAD_TICK_MS
 *     straight into the store — no reducer dispatch, so the memoised DAW
 *     children do not re-render per tick.
 *
 * usePlayheadTime subscribes one component to the store; use it only in
 * the small leaf that actually shows the time.
 */
import { useEffect, useLayoutEffect, useState, useSyncExternalStore } from 'react';

import * as DawEngine from '../../audio/DawEngine';
import { createPlayheadStore, PLAYHEAD_TICK_MS } from '../../audio/dawState/playheadStore';

const readEngineClock = () => (DawEngine.isPlaying() ? DawEngine.getCurrentTime() : null);

/**
 * @param {Object}  args
 * @param {boolean} args.isPlaying  reducer `isPlaying`
 * @param {number}  args.playhead   reducer `playhead` (parked position)
 * @returns {ReturnType<typeof createPlayheadStore>} stable store instance
 */
export function usePlayheadClock({ isPlaying, playhead }) {
    const [store] = useState(() =>
        createPlayheadStore({ initialTime: playhead, readClock: readEngineClock })
    );

    // Layout effect: the time display must not paint one frame of the old
    // value after a seek.
    useLayoutEffect(() => {
        if (!isPlaying) store.setTime(playhead);
    }, [store, isPlaying, playhead]);

    useEffect(() => {
        if (!isPlaying) return undefined;
        let frame = 0;
        let lastTick = 0;
        const loop = (ts) => {
            if (ts - lastTick > PLAYHEAD_TICK_MS && store.tick(performance.now())) {
                lastTick = ts;
            }
            frame = requestAnimationFrame(loop);
        };
        frame = requestAnimationFrame(loop);
        return () => cancelAnimationFrame(frame);
    }, [store, isPlaying]);

    return store;
}

/**
 * Subscribe a component to the live playhead (seconds).
 * @param {ReturnType<typeof createPlayheadStore>} store
 * @returns {number}
 */
export function usePlayheadTime(store) {
    return useSyncExternalStore(store.subscribe, store.getTime);
}
