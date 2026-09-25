/**
 * playheadStore — lightweight external store for the live playback head.
 *
 * Why this exists
 * ---------------
 * During playback the DAW playhead advances ~60×/s. If that value lived
 * in the DAW `useReducer` state, every tick would produce a new `state`
 * object and re-render the ENTIRE DjEditDaw tree — toolbar, timeline,
 * control strip, and the `useTimelineRender` sync effect that hashes all
 * regions. That per-tick full-tree re-render was the dominant cause of
 * the "es ruckelt sehr" stutter.
 *
 * Instead the live playhead lives here, OUTSIDE React's reducer. The RAF
 * loop in DjEditDaw pushes ticks via `setLivePlayhead()`; only the small
 * chrome components that actually DISPLAY the time (DawControlStrip's
 * readout) subscribe via `useLivePlayhead()` and re-render — in
 * isolation, never the whole tree.
 *
 * The canvas (`useTimelineRender`) does not touch this store at all — it
 * already reads `DawEngine.getCurrentTime()` directly at 60fps. The DAW
 * reducer's `state.playhead` is still the source of truth while PAUSED
 * (scrub / jump / "set cue at current position"); it is synced once, on
 * the play→stop transition, by an effect in DjEditDaw.
 */

import { useSyncExternalStore } from 'react';

let _playhead = 0;
const _listeners = new Set();

/** Push a new live playhead time (seconds). No-op if unchanged. */
export function setLivePlayhead(seconds) {
    if (seconds === _playhead) return;
    _playhead = seconds;
    for (const fn of _listeners) fn();
}

/** Current live playhead time (seconds). Safe to call outside React. */
export function getLivePlayhead() {
    return _playhead;
}

function subscribe(listener) {
    _listeners.add(listener);
    return () => _listeners.delete(listener);
}

/**
 * React hook — returns the live playhead time (seconds) and re-renders
 * the calling component whenever it advances.
 *
 * Use ONLY in small chrome components (the transport readout). Never put
 * this in the canvas render path — the canvas reads getCurrentTime()
 * directly and must not be coupled to React re-renders.
 */
export function useLivePlayhead() {
    return useSyncExternalStore(subscribe, getLivePlayhead, getLivePlayhead);
}
