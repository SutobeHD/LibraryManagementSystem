/**
 * useDawKeyhandlers — Pure key-event handlers for the DJ Edit DAW.
 *
 * Returns a map keyed by shortcut-action name (matches the keys in
 * `shortcutsRef`). Each handler receives the original KeyboardEvent and
 * performs the action: cut/copy/paste/delete/undo/redo/zoom, transport scrub,
 * jump-to-start/end, save/open, etc.
 *
 * Also returns:
 *   onShiftDown / onShiftUp — slip-mode toggle
 *   onHotcue                — hot-cue jump for keys 1..8
 *
 * Cross-hook deps:
 *   • Transport handlers (play/stop/split/rippleDelete/jumpTo) are injected
 *     so they can be re-used from the toolbar as well.
 *   • `pendingResumeAt` ref is injected from the container so the
 *     resume-playback effect on state.regions can pick up the captured time
 *     after PASTE_INSERT / DUPLICATE_SELECTION dispatches.
 */
import { useMemo } from 'react';
import toast from 'react-hot-toast';

import * as DawEngine from '../../audio/DawEngine';

export default function useDawKeyhandlers({
    state,
    dispatch,
    pendingResumeAt,
    handlePlay,
    handleStop,
    handleSplit,
    handleRippleDelete,
    handleSave,
    handleOpen,
    handleJumpTo,
}) {
    return useMemo(() => {
        // ─── Action handlers (keyed by shortcut name) ─────────────────────
        const handlers = {
            play_pause: (e) => {
                e.preventDefault();
                if (state.isPlaying) handleStop(); else handlePlay();
            },

            jump_start: (e) => {
                e.preventDefault();
                dispatch({ type: 'SET_PLAYHEAD', payload: 0 });
                dispatch({ type: 'SET_SCROLL_X', payload: 0 });
            },

            jump_end: (e) => {
                e.preventDefault();
                dispatch({ type: 'SET_PLAYHEAD', payload: state.totalDuration });
            },

            scrub_back: (e) => {
                if (e.ctrlKey) return; // let ctrl+arrow pass through
                e.preventDefault();
                const beatSec = state.bpm > 0 ? 60 / state.bpm : 0.5;
                const delta = e.shiftKey ? beatSec * 4 : beatSec;
                dispatch({ type: 'SET_PLAYHEAD', payload: Math.max(0, state.playhead - delta) });
            },

            scrub_fwd: (e) => {
                if (e.ctrlKey) return;
                e.preventDefault();
                const beatSec = state.bpm > 0 ? 60 / state.bpm : 0.5;
                const delta = e.shiftKey ? beatSec * 4 : beatSec;
                dispatch({ type: 'SET_PLAYHEAD', payload: Math.min(state.totalDuration, state.playhead + delta) });
            },

            split: (e) => { e.preventDefault(); handleSplit(); },

            delete: (e) => { e.preventDefault(); handleRippleDelete(); },

            // Undo / Redo (caller must dispatch redo first because its combo
            // is the same key as undo with an additional Shift modifier).
            undo: (e) => { e.preventDefault(); dispatch({ type: 'UNDO' }); },
            redo: (e) => { e.preventDefault(); dispatch({ type: 'REDO' }); },

            copy: (e) => {
                e.preventDefault();
                dispatch({ type: 'COPY_SELECTION' });
                toast.success('Copied to clipboard');
            },

            // Paste / Duplicate — must reschedule playback if running.
            // Web Audio's source.start() calls are queued at playRegions
            // time and don't pick up regions added afterward. Without the
            // restart, the user keeps hearing the OLD scheduled audio
            // across the paste point ("audio von davor"). We mark the
            // intent to resume; a useEffect on state.regions runs after
            // the reducer commits and re-schedules with the fresh array.
            paste: (e) => {
                e.preventDefault();
                if (state.isPlaying) {
                    pendingResumeAt.current = DawEngine.getCurrentTime();
                    DawEngine.stopPlayback();
                }
                dispatch({ type: 'PASTE_INSERT' });
                toast.success('Pasted insert');
            },

            duplicate: (e) => {
                e.preventDefault();
                if (state.isPlaying) {
                    pendingResumeAt.current = DawEngine.getCurrentTime();
                    DawEngine.stopPlayback();
                }
                dispatch({ type: 'DUPLICATE_SELECTION' });
                toast.success('Duplicated selection');
            },

            save: (e) => { e.preventDefault(); handleSave(); },

            open: (e) => { e.preventDefault(); handleOpen(); },
        };

        // ─── Slip-mode toggle (Shift held) ───────────────────────────────
        const onShiftDown = () => dispatch({ type: 'SET_SLIP_MODE', payload: true });
        const onShiftUp   = () => dispatch({ type: 'SET_SLIP_MODE', payload: false });

        // ─── Hot-cue jump (numeric keys 1..8) ────────────────────────────
        const onHotcue = (num) => {
            const cue = state.hotCues[num - 1];
            if (cue) handleJumpTo(cue.time);
        };

        return { handlers, onShiftDown, onShiftUp, onHotcue };
    }, [
        state.isPlaying, state.totalDuration, state.bpm, state.playhead, state.hotCues,
        dispatch, pendingResumeAt,
        handlePlay, handleStop, handleSplit, handleRippleDelete, handleSave, handleOpen, handleJumpTo,
    ]);
}
