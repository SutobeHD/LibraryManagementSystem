/**
 * DjEditDaw — Main container component for the DJ Edit DAW
 * 
 * Layout:
 * ┌──────────────────────────────────────────────────┐
 * │  Toolbar (project/save/open/export/edit tools)   │
 * ├──────────────────────────────────────────────────┤
 * │  Overview Mini-Map                               │
 * ├──────────────┬───────────────────────┬────────────┤
 * │              │                       │            │
 * │  Browser     │  Timeline Canvas      │  Palette   │
 * │              │  (waveform + grid)    │  Sidebar   │
 * │              │                       │            │
 * ├──────────────┴───────────────────────┴────────────┤
 * │  Performance Panel (hot cues, memory, loops)     │
 * ├──────────────────────────────────────────────────┤
 * │  Transport Bar (play/time/bpm/snap/zoom)         │
 * └──────────────────────────────────────────────────┘
 */

import React, { useReducer, useCallback, useEffect, useRef, useMemo, lazy, Suspense } from 'react';
import toast from 'react-hot-toast';
import { Music } from 'lucide-react';

// Engine imports
import { createInitialState, dawReducer, snapToGrid, cuePointsToState, stateToCuePoints, getPositionInfo } from '../../audio/DawState';
import * as DawEngine from '../../audio/DawEngine';
import RbepSerializer from '../../audio/RbepSerializer';
const DawScrollbar = lazy(() => import('./DawScrollbar'));
import { parseRbep, serializeRbep, buildTempoMap, loadRbepFile, saveRbepFile } from '../../audio/RbepSerializer';
import AudioBandAnalyzer from '../../utils/AudioBandAnalyzer';

// UI imports
import DawToolbar from './DawToolbar';
import DawTimeline from './DawTimeline';
import DawControlStrip from './DawControlStrip';
import DawBrowser from './DawBrowser';
import WaveformOverview from './WaveformOverview';

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
    console.log('[DjEditDaw] Mounting with track:', initialTrack);
    const [state, dispatch] = useReducer(extendedReducer, null, () => createInitialState());
    const [activeTrack, setActiveTrack] = React.useState(initialTrack);
    const [isLibraryCollapsed, setIsLibraryCollapsed] = React.useState(false);
    const fileInputRef = useRef(null);
    const animFrameRef = useRef(null);
    const hasInitialized = useRef(false);

    // Sync prop changes to internal state
    useEffect(() => {
        if (initialTrack) setActiveTrack(initialTrack);
    }, [initialTrack]);

    // ── LIFECYCLE CLEANUP ──
    useEffect(() => {
        return () => {
            console.log('[DjEditDaw] Unmounting, disposing DawEngine...');
            DawEngine.dispose();
        };
    }, []);

    // ── LOAD TRACK ──
    useEffect(() => {
        if (!activeTrack) return;

        const loadTrack = async () => {
            try {
                DawEngine.getAudioContext();

                const track = activeTrack;
                const filepath = track.FilePath || track.filepath || track.Location;
                if (!filepath) {
                    console.warn('[DjEditDaw] No filepath on track:', track);
                    return;
                }

                // Set track metadata
                dispatch({
                    type: 'SET_TRACK_META',
                    payload: {
                        title: track.Title || track.title || '',
                        artist: track.Artist || track.artist || '',
                        album: track.Album || track.album || '',
                        filepath,
                        id: track.TrackID || track.id || '',
                    }
                });

                dispatch({
                    type: 'SET_PROJECT',
                    payload: {
                        name: `${track.Title || track.title || 'Untitled'} (Edit)`,
                        filepath: '',
                        dirty: false,
                    }
                });

                // Load and decode audio
                toast.loading('Loading audio...', { id: 'daw-load' });
                const audioBuffer = await DawEngine.loadAudio(filepath);

                dispatch({ type: 'SET_SOURCE_BUFFER', payload: { buffer: audioBuffer } });

                // Set BPM and build tempo map
                const bpm = track.BPM || track.bpm || 128;
                dispatch({ type: 'SET_BPM', payload: bpm });

                const firstBeatMs = track.firstBeatMs || 0;
                const tempoMap = buildTempoMap(bpm, firstBeatMs, audioBuffer.duration * 1000);
                dispatch({ type: 'SET_TEMPO_MAP', payload: tempoMap });

                // Create initial region (entire track)
                const initialRegion = {
                    id: crypto.randomUUID(),
                    sourceFile: filepath,
                    sourceStart: 0,
                    sourceEnd: audioBuffer.duration,
                    sourceDuration: audioBuffer.duration,
                    timelineStart: 0,
                    timelineEnd: audioBuffer.duration,
                    duration: audioBuffer.duration,
                };
                dispatch({ type: 'SET_REGIONS', payload: [initialRegion] });

                // Generate band peaks for waveform visualization
                toast.loading('Analyzing waveform...', { id: 'daw-load' });

                // Always generate simple mono fallback peaks first (fast, guaranteed to work)
                const samplesPerPixel = Math.ceil(audioBuffer.length / 4000);
                try {
                    const fallback = AudioBandAnalyzer.generatePeaks(audioBuffer, samplesPerPixel);
                    dispatch({ type: 'SET_FALLBACK_PEAKS', payload: fallback });
                } catch (err) {
                    console.warn('[DjEditDaw] Fallback peaks failed:', err);
                }

                // Then try RGB band splitting (may fail on some audio)
                try {
                    const bandPeaks = await AudioBandAnalyzer.generateBandPeaks(audioBuffer, samplesPerPixel);
                    dispatch({ type: 'SET_BAND_PEAKS', payload: bandPeaks });
                } catch (err) {
                    console.warn('[DjEditDaw] Band peaks failed, using fallback:', err);
                }

                toast.success('Track loaded', { id: 'daw-load' });
                hasInitialized.current = true;

            } catch (err) {
                console.error('[DjEditDaw] Load failed:', err);
                toast.error(`Failed to load: ${err.message}`, { id: 'daw-load' });
            }
        };

        loadTrack();
    }, [activeTrack]);

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

    // ─── FILE OPERATIONS ───

    const handleOpen = useCallback(() => {
        if (fileInputRef.current) {
            fileInputRef.current.click();
        }
    }, []);

    const handleFileSelect = useCallback(async (e) => {
        const file = e.target.files[0];
        if (!file) return;

        // Reset input value to allow re-selecting same file
        e.target.value = null;

        const reader = new FileReader();
        reader.onload = async (ev) => {
            let audioPath = '';
            try {
                const xmlString = ev.target.result;
                toast.loading('Opening project...', { id: 'daw-open' });

                // Parse the XML content directly
                const project = parseRbep(xmlString);

                if (!project.tracks || project.tracks.length === 0) {
                    toast.error('No tracks in project', { id: 'daw-open' });
                    return;
                }

                const trackData = project.tracks[0];
                audioPath = trackData.song.filepath || trackData.song.Location;

                if (!audioPath) {
                    toast.error('Project track missing audio path', { id: 'daw-open' });
                    return;
                }

                // Load audio for the track
                const audioBuffer = await DawEngine.loadAudio(audioPath);

                // Hydrate state
                const newState = createInitialState();

                // Set Header info (Project Name, BPM, Quantize)
                // Note: file.name gives us the filename, but not full path. 
                // We'll use file.name as project name if header name is missing.
                const projectName = project.header?.name || file.name.replace('.rbep', '') || 'Untitled Project';
                newState.project = {
                    name: projectName,
                    filepath: null, // We don't know the full path from browser input
                    dirty: false,
                    bpm: parseFloat(project.header?.bpm || 128),
                    quantize: project.header?.quantize === 'ON'
                };

                // Set Track info
                newState.trackMeta = {
                    ...trackData.song,
                    duration: audioBuffer.duration
                };
                newState.totalDuration = audioBuffer.duration;
                newState.sourceBuffer = audioBuffer;

                // Generate waveform peaks
                // 1. Try to generate band peaks (expensive)
                // 2. Fallback to simple peaks
                const samplesPerPixel = Math.ceil(audioBuffer.length / 4000);
                const fallback = AudioBandAnalyzer.generatePeaks(audioBuffer, samplesPerPixel);
                newState.fallbackPeaks = fallback;
                // Trigger background band analysis? optional.
                try {
                    const bandPeaks = await AudioBandAnalyzer.generateBandPeaks(audioBuffer, samplesPerPixel);
                    newState.bandPeaks = bandPeaks;
                } catch (err) {
                    console.warn('[DjEditDaw] Band peaks failed during open, using fallback:', err);
                }


                // Set Tempo Map
                newState.tempoMap = project.tempoMap || buildTempoMap(newState.project.bpm, 0, newState.totalDuration * 1000);

                // Set Cues/Loops
                const { hotCues, memoryCues, loops } = cuePointsToState(trackData.positionMarks);
                newState.hotCues = hotCues;
                newState.memoryCues = memoryCues;
                newState.loops = loops;

                // Set regions
                newState.regions = trackData.regions || [];

                // Resume context and play (optional)
                await DawEngine.resumeContext();

                dispatch({ type: 'HYDRATE', payload: newState });
                setActiveTrack(newState.trackMeta);
                toast.success(`Opened: ${projectName}`, { id: 'daw-open' });

            } catch (err) {
                console.error(err);
                if (err.message.includes('fetch')) {
                    // If fetch failed, it might be backend or path issue
                    toast.error(`Failed to load: ${err.message} (${audioPath || 'Unknown Path'})`, { id: 'daw-open', duration: 5000 });
                } else {
                    toast.error(`Failed to open project: ${err.message}`, { id: 'daw-open', duration: 5000 });
                }
            }
        };
        reader.readAsText(file);
    }, []);

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

    const handleExport = useCallback(async () => {
        try {
            if (!state.sourceBuffer || state.regions.length === 0) {
                toast.error('Nothing to export');
                return;
            }

            toast.loading('Rendering audio...', { id: 'daw-export' });

            const rendered = await DawEngine.renderTimeline(
                state.regions,
                state.sourceBuffer,
                state.sourceBuffer.sampleRate,
                (progress) => {
                    if (progress >= 1) toast.loading('Encoding WAV...', { id: 'daw-export' });
                }
            );

            const wavBlob = DawEngine.audioBufferToWav(rendered);

            // Trigger download
            const url = URL.createObjectURL(wavBlob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${state.project.name || 'Export'}.wav`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);

            toast.success('Exported!', { id: 'daw-export' });
        } catch (err) {
            console.error('[DjEditDaw] Export failed:', err);
            toast.error(`Export failed: ${err.message}`, { id: 'daw-export' });
        }
    }, [state.sourceBuffer, state.regions, state.project.name]);


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

    // ── PROJECT OPERATIONS ──
    const handleSave = useCallback(async () => {
        try {
            // Prompt for name if missing or untitiled
            let projectName = state.project.name || 'Untitled Project';
            if (!state.project.name || state.project.name === 'Untitled Project') {
                const name = prompt('Enter project name:', projectName);
                if (!name) return; // User cancelled
                projectName = name;
                dispatch({
                    type: 'SET_PROJECT',
                    payload: { name: projectName, dirty: true }
                });
            }

            const project = buildProjectFromState(state);
            // If we have a filepath, use it. Otherwise construct one.
            // Using a simple archive/prj folder structure relative to backend run location
            const filepath = state.project.filepath || `archive/prj/${projectName}.rbep`;

            // Update project object with new name/path before saving
            project.header = { ...project.header, name: projectName };

            await saveRbepFile(project, filepath);
            dispatch({ type: 'MARK_CLEAN' });
            dispatch({ type: 'SET_PROJECT', payload: { name: projectName, filepath, dirty: false } });
            toast.success('Project saved');
        } catch (err) {
            console.error(err);
            toast.error(`Save failed: ${err.message}`);
        }
    }, [state]);

    const handleOpenProject = useCallback((filepath) => {
        handleOpen();
    }, [handleOpen]);

    // ── KEYBOARD SHORTCUTS (EC8: capture all DAW-relevant keys) ──
    useEffect(() => {
        const handleKeyDown = (e) => {
            if (e.target.closest('input, select, textarea')) return;

            // Space — Play/Pause
            if (e.code === 'Space') {
                e.preventDefault();
                if (state.isPlaying) handleStop();
                else handlePlay();
                return;
            }

            // Home — Jump to start
            if (e.key === 'Home') {
                e.preventDefault();
                dispatch({ type: 'SET_PLAYHEAD', payload: 0 });
                dispatch({ type: 'SET_SCROLL_X', payload: 0 });
                return;
            }

            // End — Jump to end
            if (e.key === 'End') {
                e.preventDefault();
                dispatch({ type: 'SET_PLAYHEAD', payload: state.totalDuration });
                return;
            }

            // ArrowLeft — Fine scrub backward (-1 beat)
            if (e.key === 'ArrowLeft' && !e.ctrlKey) {
                e.preventDefault();
                const beatSec = state.bpm > 0 ? 60 / state.bpm : 0.5;
                const delta = e.shiftKey ? beatSec * 4 : beatSec; // Shift = 1 bar
                dispatch({ type: 'SET_PLAYHEAD', payload: Math.max(0, state.playhead - delta) });
                return;
            }

            // ArrowRight — Fine scrub forward (+1 beat)
            if (e.key === 'ArrowRight' && !e.ctrlKey) {
                e.preventDefault();
                const beatSec = state.bpm > 0 ? 60 / state.bpm : 0.5;
                const delta = e.shiftKey ? beatSec * 4 : beatSec;
                dispatch({ type: 'SET_PLAYHEAD', payload: Math.min(state.totalDuration, state.playhead + delta) });
                return;
            }

            // Ctrl+E — Split
            if (e.ctrlKey && e.key.toLowerCase() === 'e') {
                e.preventDefault();
                handleSplit();
                return;
            }

            // Delete — Ripple Delete
            if (e.key === 'Delete') {
                e.preventDefault();
                handleRippleDelete();
                return;
            }

            // Ctrl+Z — Undo
            if (e.ctrlKey && !e.shiftKey && e.key.toLowerCase() === 'z') {
                e.preventDefault();
                dispatch({ type: 'UNDO' });
                return;
            }

            // Ctrl+Shift+Z — Redo
            if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === 'z') {
                e.preventDefault();
                dispatch({ type: 'REDO' });
                return;
            }

            // Ctrl+C — Copy
            if (e.ctrlKey && e.key.toLowerCase() === 'c') {
                e.preventDefault();
                dispatch({ type: 'COPY_SELECTION' });
                toast.success('Copied to clipboard');
                return;
            }

            // Ctrl+V — Paste (Insert)
            if (e.ctrlKey && e.key.toLowerCase() === 'v') {
                e.preventDefault();
                dispatch({ type: 'PASTE_INSERT' });
                toast.success('Pasted insert');
                return;
            }

            // Ctrl+D — Duplicate
            if (e.ctrlKey && e.key.toLowerCase() === 'd') {
                e.preventDefault();
                dispatch({ type: 'DUPLICATE_SELECTION' });
                toast.success('Duplicated selection');
                return;
            }

            // Ctrl+S — Save
            if (e.ctrlKey && e.key.toLowerCase() === 's') {
                e.preventDefault();
                handleSave();
                return;
            }

            // Ctrl+O — Open
            if (e.ctrlKey && e.key.toLowerCase() === 'o') {
                e.preventDefault();
                handleOpen();
                return;
            }

            // Shift (held) — Slip mode
            if (e.key === 'Shift') {
                dispatch({ type: 'SET_SLIP_MODE', payload: true });
                return;
            }

            // 1-8 — Hot cues
            const num = parseInt(e.key);
            if (num >= 1 && num <= 8 && !e.ctrlKey && !e.altKey) {
                const cue = state.hotCues[num - 1];
                if (cue) handleJumpTo(cue.time);
                return;
            }
        };

        const handleKeyUp = (e) => {
            if (e.key === 'Shift') {
                dispatch({ type: 'SET_SLIP_MODE', payload: false });
            }
        };

        window.addEventListener('keydown', handleKeyDown);
        window.addEventListener('keyup', handleKeyUp);
        return () => {
            window.removeEventListener('keydown', handleKeyDown);
            window.removeEventListener('keyup', handleKeyUp);
        };
    }, [state.isPlaying, state.hotCues, state.bpm, state.playhead, state.totalDuration,
        handlePlay, handleStop, handleSplit, handleRippleDelete, handleSave, handleOpen, handleJumpTo, dispatch]);


    // ── RENDER ──
    try {
        return (
            <div className="flex flex-col h-full bg-slate-950 text-white overflow-hidden">
                {/* Top Bar: Project Header */}
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

                {/* Middle: Overview + Timeline Area */}
                <div className="flex-1 flex flex-col overflow-hidden relative">
                    {/* Waveform Overview Mini-Map (always shown, placeholder when no track) */}
                    <WaveformOverview state={state} dispatch={dispatch} />

                    {activeTrack ? (
                        <div className="flex-1 relative">
                            <DawTimeline
                                state={state}
                                dispatch={dispatch}
                                canvasHeight={300}
                                onRegionClick={handleRegionClick}
                            />
                            {/* Scrollbar Overlay at bottom of timeline area */}
                            <div className="absolute bottom-0 left-0 right-0 z-10">
                                <DawScrollbar state={state} dispatch={dispatch} />
                            </div>
                        </div>
                    ) : (
                        /* Empty State */
                        <div className="flex-1 flex flex-col items-center justify-center bg-slate-950/50">
                            <Music size={48} className="text-slate-800 mb-4" />
                            <h2 className="text-lg font-semibold text-slate-500">No Project Loaded</h2>
                            <p className="text-sm text-slate-600 mt-2 mb-6">Select a track from the library below to start editing</p>
                            <div className="flex gap-3">
                                <button
                                    onClick={handleOpen}
                                    className="px-4 py-2 bg-slate-800 hover:bg-slate-700 rounded-lg text-sm text-white transition-colors border border-white/5"
                                >
                                    Open Project
                                </button>
                            </div>
                        </div>
                    )}
                </div>

                {/* Control Strip (Transport + Tools + Cues) */}
                <DawControlStrip
                    state={state}
                    dispatch={dispatch}
                    onPlay={handlePlay}
                    onStop={handleStop}
                    onSplit={handleSplit}
                    onRippleDelete={handleRippleDelete}
                    onJumpTo={handleJumpTo}
                />

                {/* Bottom: Library Browser (Collapsible/Resizable) */}
                <div
                    className={`border-t border-white/10 relative z-20 transition-all duration-300 ease-in-out shrink-0 overflow-hidden ${isLibraryCollapsed ? 'h-[32px]' : 'h-[240px]'
                        }`}
                >
                    <div className="h-full w-full">
                        <DawBrowser
                            onLoadTrack={handleLoadTrack}
                            onOpenProject={handleOpenProject}
                            isCollapsed={isLibraryCollapsed}
                            onToggleCollapse={() => setIsLibraryCollapsed(prev => !prev)}
                        />
                    </div>
                </div>

                {/* Hidden File Input for Open Dialog */}
                <input
                    type="file"
                    ref={fileInputRef}
                    onChange={handleFileSelect}
                    accept=".rbep"
                    className="hidden"
                />
            </div>
        );
    } catch (err) {
        console.error('[DjEditDaw] Render Error:', err);
        return (
            <div className="flex items-center justify-center h-full text-red-500 bg-slate-950">
                <div className="text-center">
                    <h3 className="font-bold text-xl">DAW Render Error</h3>
                    <pre className="text-xs mt-2 text-left bg-black/50 p-4 rounded">{err.message}</pre>
                </div>
            </div>
        );
    }
};

// ─── HELPERS ───────────────────────────────────────────────────────────────────

function buildProjectFromState(state) {
    const cuePoints = stateToCuePoints(state.hotCues, state.memoryCues, state.loops);

    return {
        info: { app: 'rekordbox', version: '1' },
        tracks: [{
            trackId: '1',
            song: {
                id: state.trackMeta.id || crypto.randomUUID(),
                uuid: state.trackMeta.uuid || crypto.randomUUID(),
                title: state.trackMeta.title,
                artist: state.trackMeta.artist,
                album: state.trackMeta.album,
                filepath: state.trackMeta.filepath,
            },
            cuePoints,
            regions: state.regions,
            volume: state.volumeData,
            bpm: state.bpm,
            songTempoMap: state.tempoMap,
            songGridInfo: state.tempoMap.length > 0 ? {
                length: state.tempoMap.length,
                bpm: state.bpm,
                indexOffset: 1,
            } : null,
        }],
        mastergrid: state.masterTempoMap.length > 0 ? {
            indexOffset: 1,
            beats: state.masterTempoMap,
        } : null,
    };
}

export default DjEditDaw;
