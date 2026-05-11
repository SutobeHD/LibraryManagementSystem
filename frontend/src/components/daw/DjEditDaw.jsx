/**
 * DjEditDaw — Root container for the DJ Edit DAW.
 *
 * Responsibilities (slim — heavy lifting lives in helpers under daw/):
 *   • Owns DAW state via useReducer(extendedReducer, …)
 *   • Loads / decodes / analyses audio for an active track
 *   • Drives the playhead animation + dead-reckoning sync
 *   • Wires transport / editing handlers used by both the toolbar and the
 *     keyboard-shortcut hook (split / ripple-delete / play / stop / jump-to /
 *     export / auto-cue)
 *   • Delegates project persistence to useDawProject,
 *     key-event handlers to useDawKeyhandlers, and keyboard binding +
 *     configurable shortcut loading to useDawShortcuts.
 *   • Renders <DawLayout> with the panel children wired up.
 */
import React, { useState, useReducer, useCallback, useEffect, useRef, lazy } from 'react';
import toast from 'react-hot-toast';

// Engine imports
import { createInitialState, dawReducer, snapToGrid } from '../../audio/DawState';
import * as DawEngine from '../../audio/DawEngine';

// UI imports
import DawToolbar from './DawToolbar';
import DawTimeline from './DawTimeline';
import DawControlStrip from './DawControlStrip';
import DawBrowser from './DawBrowser';
import WaveformOverview from './WaveformOverview';
import ExportModal from './ExportModal';
import DawLayout from './DawLayout';
import useDawProject from './useDawProject';
import useDawKeyhandlers from './useDawKeyhandlers';
import useDawShortcuts from './useDawShortcuts';
import useTrackLoader from './useTrackLoader';
import { log } from '../../utils/log';

const DawScrollbar = lazy(() => import('./DawScrollbar'));

// ─── EXTENDED REDUCER ──────────────────────────────────────────────────────────

function extendedReducer(state, action) {
    // Handle palette clips (not in core reducer)
    if (action.type === 'SET_PALETTE_CLIPS') {
        return { ...state, paletteClips: action.payload };
    }
    return dawReducer(state, action);
}

// ─── MAIN COMPONENT ────────────────────────────────────────────────────────────

const DjEditDaw = ({ track: initialTrack }) => {
    log.info('[DjEditDaw] Mounting with track:', initialTrack);
    const [state, dispatch] = useReducer(extendedReducer, null, () => createInitialState());

    // Diagnostic hook — exposes the live DAW state on `window.__dawState`
    // so the user can dump regions/clipboard from DevTools when debugging
    // visual-vs-audio mismatches. Read-only; mutations are not reflected.
    if (typeof window !== 'undefined') {
        window.__dawState = state;
        window.__dawDispatch = dispatch;
    }
    const [showExport, setShowExport] = useState(false);
    const [activeTrack, setActiveTrack] = useState(initialTrack);
    const [isLibraryCollapsed, setIsLibraryCollapsed] = useState(false);
    const animFrameRef = useRef(null);
    const hasInitialized = useRef(false);
    // When set (to a timeline-time number), the next regions-changed effect
    // will resume playback from that position with the freshly-mutated
    // regions array. Used by paste/duplicate to make audio reflect new
    // regions immediately instead of after the user manually re-pressing
    // play. Cleared once consumed.
    const pendingResumeAt = useRef(null);

    // ─── PROJECT PERSISTENCE (open / save / file dialog) ─────────────────
    const {
        fileInputRef,
        skipNextAutoLoad,
        handleSave,
        handleOpen,
        handleFileSelect,
        handleOpenProject,
    } = useDawProject({ state, dispatch, setActiveTrack });

    // Sync prop changes to internal state
    useEffect(() => {
        if (initialTrack) setActiveTrack(initialTrack);
    }, [initialTrack]);

    // ── LIFECYCLE CLEANUP ──
    useEffect(() => {
        return () => {
            log.info('[DjEditDaw] Unmounting, disposing DawEngine...');
            DawEngine.dispose();
        };
    }, []);

    // ── LOAD TRACK (audio decode + tempo map + waveform peaks) ──
    useTrackLoader({ activeTrack, dispatch, skipNextAutoLoad, hasInitialized });

    // ── PLAYHEAD ANIMATION + DEAD RECKONING SYNC ──
    useEffect(() => {
        let lastSyncTime = 0;
        const updatePlayhead = (timestamp) => {
            if (state.isPlaying) {
                // Throttle React state updates to ~15fps (66ms) — Canvas reads at 60fps directly
                if (timestamp - lastSyncTime > 66) {
                    const currentTime = DawEngine.getCurrentTime();
                    dispatch({ type: 'SET_PLAYHEAD', payload: currentTime });

                    // Dead Reckoning sync: store wall-clock + audio time so Timeline can interpolate
                    dispatch({
                        type: 'SET_DEAD_RECKONING_SYNC',
                        payload: {
                            lastSyncWallClock: performance.now(),
                            lastSyncAudioTime: currentTime,
                        },
                    });

                    lastSyncTime = timestamp;
                }
            }
            animFrameRef.current = requestAnimationFrame(updatePlayhead);
        };

        animFrameRef.current = requestAnimationFrame(updatePlayhead);
        return () => {
            if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
        };
    }, [state.isPlaying]);

    // ─── RESUME PLAYBACK AFTER MID-PLAYBACK PASTE / DUPLICATE ─────
    // The keyboard handler stops Web Audio + sets pendingResumeAt before
    // dispatching PASTE_INSERT or DUPLICATE_SELECTION. This effect then
    // fires after React commits the new regions array and re-schedules
    // playback with the fresh regions, starting from the captured time.
    // Without it, the audio engine would keep playing the source.start()
    // calls it had queued before the mutation — the user's reported
    // "audio von davor" symptom.
    useEffect(() => {
        const resumeAt = pendingResumeAt.current;
        if (resumeAt == null) return;
        pendingResumeAt.current = null;
        if (!state.sourceBuffer) return;
        DawEngine.playRegions(
            state.regions,
            state.sourceBuffer,
            resumeAt,
            state.loopEnabled ? state.loopEnd : null,
            () => dispatch({ type: 'SET_PLAYING', payload: false })
        );
        dispatch({ type: 'SET_PLAYING', payload: true });
    }, [state.regions]);

    // ── AUTO CUE ──
    const handleAutoCue = useCallback(() => {
        if (!state.project.bpm || state.totalDuration <= 0) {
            toast.error('BPM or track duration not set.');
            return;
        }

        const bpm = state.project.bpm || 128;
        const beatSec = 60 / bpm;
        const barSec = beatSec * 4;
        const intervalSec = barSec * 16; // 16 bars

        let count = 0;
        let time = intervalSec; // Start at first 16-bar mark

        while (time < state.totalDuration) {
            dispatch({
                type: 'ADD_MEMORY_CUE',
                payload: { time, label: `16 Bar ${count + 1}` }
            });
            time += intervalSec;
            count++;
        }

        if (count > 0) {
            toast.success(`Added ${count} memory cues at 16-bar intervals`);
        } else {
            toast.error('No space for 16-bar markers');
        }
    }, [state.project.bpm, state.totalDuration]);

    // ── TRANSPORT CONTROLS ──
    const handlePlay = useCallback(async () => {
        // EC6: race-condition guard — block play if buffer not yet decoded
        if (!state.sourceBuffer) {
            toast.error('Track still loading — please wait...', { id: 'play-guard', duration: 2000 });
            return;
        }

        await DawEngine.resumeContext();
        dispatch({ type: 'SET_PLAYING', payload: true });

        DawEngine.playRegions(
            state.regions,
            state.sourceBuffer,
            state.playhead,
            state.loopEnabled ? state.loopEnd : null,
            () => dispatch({ type: 'SET_PLAYING', payload: false })
        );
    }, [state.regions, state.sourceBuffer, state.playhead, state.loopEnabled, state.loopEnd]);

    const handleStop = useCallback(() => {
        DawEngine.stopPlayback();
        dispatch({ type: 'SET_PLAYING', payload: false });
    }, []);

    const handleJumpTo = useCallback((time) => {
        const wasPlaying = state.isPlaying;
        if (wasPlaying) {
            DawEngine.stopPlayback();
        }
        dispatch({ type: 'SET_PLAYHEAD', payload: time });
        if (wasPlaying) {
            // Restart playback from new position
            setTimeout(() => {
                DawEngine.playRegions(
                    state.regions,
                    state.sourceBuffer,
                    time,
                    null,
                    () => dispatch({ type: 'SET_PLAYING', payload: false })
                );
            }, 50);
        }
    }, [state.isPlaying, state.regions, state.sourceBuffer]);

    const handleLoadTrack = useCallback((track) => {
        setActiveTrack(track);
    }, []);

    const handleExport = useCallback(() => {
        if (!state.sourceBuffer || state.regions.length === 0) {
            toast.error('Nothing to export');
            return;
        }
        setShowExport(true);
    }, [state.sourceBuffer, state.regions]);

    // ── EDITING ACTIONS ──
    const handleSplit = useCallback(() => {
        // Snap playhead for split if enabled
        let splitTime = state.playhead;
        if (state.snapEnabled && !state.slipMode && state.bpm > 0) {
            const firstBeatSec = (state.tempoMap?.[0]?.positionMs || 0) / 1000;
            splitTime = snapToGrid(splitTime, state.bpm, state.snapDivision, firstBeatSec);
        }

        // Find region at playhead
        const region = state.regions.find(r =>
            splitTime > r.timelineStart && splitTime < r.timelineStart + r.duration
        );
        if (!region) {
            toast.error('No region at playhead');
            return;
        }

        dispatch({ type: 'PUSH_UNDO', payload: 'Split' });
        dispatch({
            type: 'SPLIT_REGION_AT',
            payload: { regionId: region.id, splitTime }
        });
        toast.success('Region split', { duration: 1500 });
    }, [state.regions, state.playhead, state.snapEnabled, state.slipMode, state.bpm, state.snapDivision, state.tempoMap]);

    const handleRippleDelete = useCallback(() => {
        if (state.selectedRegionIds.size === 0) {
            toast.error('No region selected');
            return;
        }

        dispatch({ type: 'PUSH_UNDO', payload: 'Ripple Delete' });
        for (const id of state.selectedRegionIds) {
            dispatch({ type: 'RIPPLE_DELETE', payload: id });
        }
        toast.success('Deleted', { duration: 1500 });
    }, [state.selectedRegionIds]);

    // ── REGION CLICK ──
    const handleRegionClick = useCallback((region, e) => {
        if (e.ctrlKey || e.metaKey) {
            dispatch({ type: 'TOGGLE_SELECT_REGION', payload: region.id });
        } else {
            dispatch({ type: 'SELECT_REGION', payload: region.id });
        }
    }, []);

    // ─── KEYBOARD SHORTCUTS ───────────────────────────────────────────────
    const { handlers: keyHandlers, onShiftDown, onShiftUp, onHotcue } = useDawKeyhandlers({
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
    });
    useDawShortcuts({ handlers: keyHandlers, onShiftDown, onShiftUp, onHotcue });

    // ── RENDER ──
    try {
        return (
            <DawLayout
                activeTrack={activeTrack}
                isLibraryCollapsed={isLibraryCollapsed}
                onOpen={handleOpen}
                toolbar={
                    <DawToolbar
                        state={state}
                        dispatch={dispatch}
                        onSave={handleSave}
                        onOpen={handleOpen}
                        onExport={handleExport}
                        onSplit={handleSplit}
                        onRippleDelete={handleRippleDelete}
                        onAutoCue={handleAutoCue}
                    />
                }
                overview={<WaveformOverview state={state} dispatch={dispatch} />}
                timeline={
                    <DawTimeline
                        state={state}
                        dispatch={dispatch}
                        onRegionClick={handleRegionClick}
                    />
                }
                scrollbar={<DawScrollbar state={state} dispatch={dispatch} />}
                controlStrip={
                    <DawControlStrip
                        state={state}
                        dispatch={dispatch}
                        onPlay={handlePlay}
                        onStop={handleStop}
                        onSplit={handleSplit}
                        onRippleDelete={handleRippleDelete}
                        onJumpTo={handleJumpTo}
                        onExport={() => setShowExport(true)}
                    />
                }
                browser={
                    <DawBrowser
                        onLoadTrack={handleLoadTrack}
                        onOpenProject={handleOpenProject}
                        isCollapsed={isLibraryCollapsed}
                        onToggleCollapse={() => setIsLibraryCollapsed(prev => !prev)}
                    />
                }
                exportModal={
                    showExport && (
                        <ExportModal
                            state={state}
                            onClose={() => setShowExport(false)}
                        />
                    )
                }
                fileInput={
                    <input
                        type="file"
                        ref={fileInputRef}
                        onChange={handleFileSelect}
                        accept=".rbep"
                        className="hidden"
                    />
                }
            />
        );
    } catch (err) {
        console.error('[DjEditDaw] Render Error:', err);
        return (
            <div className="flex items-center justify-center h-full text-red-500 bg-mx-deepest">
                <div className="text-center">
                    <h3 className="font-bold text-xl">DAW Render Error</h3>
                    <pre className="text-xs mt-2 text-left bg-black/50 p-4 rounded">{err.message}</pre>
                </div>
            </div>
        );
    }
};

export default DjEditDaw;
