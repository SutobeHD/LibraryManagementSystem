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

import React, { useState, useReducer, useCallback, useEffect, useRef, useMemo, lazy, Suspense } from 'react';
import toast from 'react-hot-toast';
import { Music } from 'lucide-react';

// Engine imports
import { createInitialState, dawReducer, snapToGrid, cuePointsToState, stateToCuePoints, getPositionInfo } from '../../audio/DawState';
import * as DawEngine from '../../audio/DawEngine';
import RbepSerializer from '../../audio/RbepSerializer';
const DawScrollbar = lazy(() => import('./DawScrollbar'));
import { parseRbep, serializeRbep, buildTempoMap, loadRbepFile, saveRbepFile } from '../../audio/RbepSerializer';
import AudioBandAnalyzer from '../../utils/AudioBandAnalyzer';
import api from '../../api/api';
import { promptModal } from '../PromptModal';

// UI imports
import DawToolbar from './DawToolbar';
import DawTimeline from './DawTimeline';
import DawControlStrip from './DawControlStrip';
import DawBrowser from './DawBrowser';
import WaveformOverview from './WaveformOverview';
import ExportModal from './ExportModal';
import { log } from '../../utils/log';
import { TOAST_DURATION_LONG_MS } from '../../config/constants';

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
    const [isLoading, setIsLoading] = useState(false);
    const [loadProgress, setLoadProgress] = useState(0);
    const [isLibraryCollapsed, setIsLibraryCollapsed] = useState(false);
    const fileInputRef = useRef(null);
    const animFrameRef = useRef(null);
    const hasInitialized = useRef(false);
    // Set to true when handleFileSelect has loaded a .rbep project — tells the
    // activeTrack loadTrack useEffect to skip re-initializing the regions/audio,
    // so it doesn't overwrite the 9 parsed regions with a single default region.
    const skipNextAutoLoad = useRef(false);
    // When set (to a timeline-time number), the next regions-changed effect
    // will resume playback from that position with the freshly-mutated
    // regions array. Used by paste/duplicate to make audio reflect new
    // regions immediately instead of after the user manually re-pressing
    // play. Cleared once consumed.
    const pendingResumeAt = useRef(null);

    // Configurable keyboard shortcuts — loaded from /api/settings on mount.
    // Stored in a ref (not state) so the keydown handler closure always reads
    // the latest value without needing to be re-registered on every settings change.
    const shortcutsRef = useRef({
        play_pause: 'Space',   jump_start: 'Home',      jump_end: 'End',
        scrub_back: 'ArrowLeft', scrub_fwd: 'ArrowRight',
        split: 'Ctrl+E',       delete: 'Delete',
        undo: 'Ctrl+Z',        redo: 'Ctrl+Shift+Z',
        copy: 'Ctrl+C',        paste: 'Ctrl+V',
        duplicate: 'Ctrl+D',   save: 'Ctrl+S',          open: 'Ctrl+O',
    });

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

    // ── LOAD TRACK ──
    useEffect(() => {
        if (!activeTrack) return;

        // Skip auto-load if the track was just hydrated from a .rbep project file.
        // handleFileSelect has already loaded the audio, parsed 9 edit regions, and
        // dispatched HYDRATE — running loadTrack() here would overwrite those regions
        // with a single default full-track region, making the export equal the original.
        if (skipNextAutoLoad.current) {
            skipNextAutoLoad.current = false;
            log.debug('[DjEditDaw] Skipping auto-load — regions already hydrated from .rbep');
            return;
        }

        const loadTrack = async () => {
            try {
                DawEngine.getAudioContext();

                const track = activeTrack;
                // /api/library/tracks returns rekordbox tracks with `path`
                // (lowercase). Older .rbep paths used `FilePath`/`filepath`/
                // `Location`. Try all four so library-list double-clicks
                // actually load instead of silently warning.
                const filepath = track.FilePath || track.filepath || track.Location || track.path;
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
                        id: track.TrackID || track.ID || track.id || '',
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

                // Generate waveform peaks for visualization
                toast.loading('Analyzing waveform...', { id: 'daw-load' });

                // Peak resolution targets — base count of `targetPeaks` peaks
                // across the full source audio. 16 000 ≈ 40 peaks/sec for a
                // 400s track — 4× the previous 4 000 base while still
                // generating in <5s in a browser via Web Audio OfflineContext.
                // 32k was tried but the BiquadFilter offline rendering of 3
                // band chains over a 408s buffer (~18M samples * 3) hung the
                // main thread for too long. The LOD pyramid below decimates
                // this base into r2/r4 for zoomed-out views.
                const targetPeaks   = 16000;
                const samplesPerPixel = Math.ceil(audioBuffer.length / targetPeaks);

                // 1. Always generate mono fallback peaks first (instant, guaranteed)
                try {
                    const fallback = AudioBandAnalyzer.generatePeaks(audioBuffer, samplesPerPixel);
                    dispatch({ type: 'SET_FALLBACK_PEAKS', payload: fallback });
                } catch (err) {
                    console.warn('[DjEditDaw] Fallback peaks failed:', err);
                }

                // 2. Try backend 3-band waveform (Butterworth, Rekordbox-quality)
                let usedBackendWaveform = false;
                try {
                    // pps (peaks-per-second) — derived from targetPeaks so
                    // backend matches client-side resolution.
                    const pps = Math.max(30, Math.ceil(targetPeaks / audioBuffer.duration));
                    const resp = await api.get('/api/audio/waveform', {
                        params: { path: filepath, pps },
                        timeout: 15000,
                    });
                    if (resp.data?.low?.length > 0) {
                        const bandPeaks = convertBackendWaveform(resp.data);
                        // Backend returns single-resolution arrays — wrap into
                        // LOD shape so the renderer's LOD-aware code path
                        // (r1/r2/r4) works. We synthesise r2/r4 by decimating
                        // r1 client-side.
                        bandPeaks.lod = {
                            r1: { low: bandPeaks.low, mid: bandPeaks.mid, high: bandPeaks.high },
                            r2: {
                                low:  AudioBandAnalyzer._decimatePeaks(bandPeaks.low,  2),
                                mid:  AudioBandAnalyzer._decimatePeaks(bandPeaks.mid,  2),
                                high: AudioBandAnalyzer._decimatePeaks(bandPeaks.high, 2),
                            },
                            r4: {
                                low:  AudioBandAnalyzer._decimatePeaks(bandPeaks.low,  4),
                                mid:  AudioBandAnalyzer._decimatePeaks(bandPeaks.mid,  4),
                                high: AudioBandAnalyzer._decimatePeaks(bandPeaks.high, 4),
                            },
                        };
                        dispatch({ type: 'SET_BAND_PEAKS', payload: bandPeaks });
                        usedBackendWaveform = true;
                    }
                } catch (err) {
                    console.warn('[DjEditDaw] Backend waveform unavailable, falling back to client-side:', err.message);
                }

                // 3. Fallback: client-side band splitting with multi-resolution
                // LOD (BiquadFilter — less accurate than backend Butterworth
                // but always available). Returns { low, mid, high, mono, lod }.
                if (!usedBackendWaveform) {
                    try {
                        const bandPeaks = await AudioBandAnalyzer.generateMultiResolutionPeaks(
                            audioBuffer,
                            samplesPerPixel,
                        );
                        dispatch({ type: 'SET_BAND_PEAKS', payload: bandPeaks });
                    } catch (err) {
                        console.warn('[DjEditDaw] Band peaks failed, using mono fallback:', err);
                    }
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

                // BUGFIX: The .rbep edit timeline can be LONGER (or shorter) than the source audio
                // because edit projects rearrange/repeat sections. Compute timeline duration from
                // the maximum region timelineEnd — falling back to source audio duration only if
                // no regions exist. Without this, totalDuration was being set to the source song
                // length (e.g. 6:49 for VELVET SHUFFLE) instead of the edit length (e.g. 8:01),
                // causing the timeline UI, playhead, and export to be clipped to the wrong length.
                const editTimelineEnd = (trackData.regions && trackData.regions.length > 0)
                    ? trackData.regions.reduce((max, r) => Math.max(max, r.timelineEnd || 0), 0)
                    : audioBuffer.duration;

                // BUGFIX: parseRbep returns project.info (not project.header), so the previous
                // `project.header?.bpm` always returned undefined and BPM defaulted to 128.
                // The actual track BPM is parsed from <edit><bpm><section bpm="..."/> into
                // trackData.bpm (defaults to 128 in RbepSerializer if absent).
                const projectName = project.info?.name || file.name.replace('.rbep', '') || 'Untitled Project';
                const projectBpm = parseFloat(trackData.bpm || 128);
                newState.project = {
                    name: projectName,
                    filepath: null, // We don't know the full path from browser input
                    dirty: false,
                    bpm: projectBpm,
                    quantize: project.info?.quantize === 'ON'
                };

                // Set Track info — keep `duration` as source-audio length (used for waveform
                // mapping), but the timeline-level totalDuration is the edit length.
                newState.trackMeta = {
                    ...trackData.song,
                    duration: audioBuffer.duration
                };
                newState.totalDuration = editTimelineEnd;
                newState.bpm = projectBpm;
                newState.sourceBuffer = audioBuffer;

                // Generate waveform peaks — matches loadTrack path (32k base
                // peaks, multi-resolution LOD). The peak arrays index against
                // the SOURCE audio length (audioBuffer.duration), NOT the
                // edit timeline — this is critical for .rbep projects whose
                // editTimelineEnd can differ from audioBuffer.duration.
                const samplesPerPixel = Math.ceil(audioBuffer.length / 16000);
                const fallback = AudioBandAnalyzer.generatePeaks(audioBuffer, samplesPerPixel);
                newState.fallbackPeaks = fallback;
                try {
                    const bandPeaks = await AudioBandAnalyzer.generateMultiResolutionPeaks(
                        audioBuffer,
                        samplesPerPixel,
                    );
                    newState.bandPeaks = bandPeaks;
                } catch (err) {
                    console.warn('[DjEditDaw] Band peaks failed during open, using fallback:', err);
                }


                // BUGFIX: Prefer the project's <mastergrid> as the timeline tempo map (it
                // reflects the edited timeline's beat positions, e.g. 1284 beats / 481.5s for
                // VELVET SHUFFLE). Fall back to the per-track <songgrid>/orggrid, then to a
                // synthesized constant-BPM map sized to the edit length.
                newState.tempoMap = (project.mastergrid?.beats?.length > 0
                    ? project.mastergrid.beats
                    : (trackData.songTempoMap?.length > 0
                        ? trackData.songTempoMap
                        : buildTempoMap(newState.project.bpm, 0, newState.totalDuration * 1000)));

                // BUGFIX: parseRbep stores cue points in `cuePoints` (not `positionMarks`).
                // Using the wrong property name silently dropped all hot/memory cues + loops.
                const { hotCues, memoryCues, loops } = cuePointsToState(trackData.cuePoints || []);
                newState.hotCues = hotCues;
                newState.memoryCues = memoryCues;
                newState.loops = loops;

                // Set regions
                newState.regions = trackData.regions || [];

                // Convert .rbep volume sections (beat-indexed) to seconds for export
                // The parser stores volume as { startBeat, endBeat, vol } — we need seconds
                if (trackData.volume && trackData.volume.length > 0) {
                    const timelineTempoMap = newState.tempoMap;
                    newState.volumeData = trackData.volume.map(v => ({
                        startSec: timelineTempoMap.length > 0
                            ? (timelineTempoMap[Math.min(Math.floor(v.startBeat), timelineTempoMap.length - 1)]?.positionMs || 0) / 1000
                            : v.startBeat * (60 / newState.bpm),
                        endSec: timelineTempoMap.length > 0
                            ? (timelineTempoMap[Math.min(Math.floor(v.endBeat), timelineTempoMap.length - 1)]?.positionMs || 0) / 1000
                            : v.endBeat * (60 / newState.bpm),
                        vol: v.vol,
                    }));
                }

                // Resume context and play (optional)
                await DawEngine.resumeContext();

                dispatch({ type: 'HYDRATE', payload: newState });
                // Prevent the activeTrack useEffect from re-initializing audio + regions.
                // Without this flag, the useEffect would replace the 9 parsed regions
                // with a single default region spanning the full source (= original song).
                skipNextAutoLoad.current = true;
                setActiveTrack(newState.trackMeta);
                toast.success(`Opened: ${projectName}`, { id: 'daw-open' });

            } catch (err) {
                console.error(err);
                if (err.message.includes('fetch')) {
                    // If fetch failed, it might be backend or path issue
                    toast.error(`Failed to load: ${err.message} (${audioPath || 'Unknown Path'})`, { id: 'daw-open', duration: TOAST_DURATION_LONG_MS });
                } else {
                    toast.error(`Failed to open project: ${err.message}`, { id: 'daw-open', duration: TOAST_DURATION_LONG_MS });
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

    // ── PROJECT OPERATIONS ──
    const handleSave = useCallback(async () => {
        try {
            // Prompt for name if missing or untitiled
            let projectName = state.project.name || 'Untitled Project';
            if (!state.project.name || state.project.name === 'Untitled Project') {
                const name = await promptModal({
                    title: 'Save project',
                    message: 'Enter project name:',
                    defaultValue: projectName,
                });
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

    // ── Load configurable shortcuts from settings on mount ───────────────────
    useEffect(() => {
        api.get('/api/settings')
            .then(res => {
                const saved = res.data?.shortcuts;
                if (saved && typeof saved === 'object') {
                    shortcutsRef.current = { ...shortcutsRef.current, ...saved };
                }
            })
            .catch(() => {}); // non-fatal — defaults remain in ref
    }, []);

    // ── KEYBOARD SHORTCUTS (EC8: capture all DAW-relevant keys) ──
    // Uses shortcutsRef for configurable bindings; ref lookup is always current
    // even though this effect only re-registers when action handlers change.
    useEffect(() => {
        /**
         * Returns true if a KeyboardEvent matches a combo string.
         * Combo format: ['Ctrl+']['Shift+']['Alt+']key
         * key is matched against both e.code (e.g. 'Space') and e.key (e.g. 'ArrowLeft').
         */
        const matches = (e, combo) => {
            if (!combo) return false;
            const parts   = combo.split('+');
            const key     = parts[parts.length - 1];
            const ctrl    = parts.includes('Ctrl');
            const shift   = parts.includes('Shift');
            const alt     = parts.includes('Alt');
            if (e.ctrlKey !== ctrl || e.shiftKey !== shift || e.altKey !== alt) return false;
            return e.code === key || e.key === key;
        };

        const sc = () => shortcutsRef.current; // alias for brevity

        const handleKeyDown = (e) => {
            if (e.target.closest('input, select, textarea')) return;

            // Play / Pause
            if (matches(e, sc().play_pause)) {
                e.preventDefault();
                if (state.isPlaying) handleStop(); else handlePlay();
                return;
            }

            // Jump to Start
            if (matches(e, sc().jump_start)) {
                e.preventDefault();
                dispatch({ type: 'SET_PLAYHEAD', payload: 0 });
                dispatch({ type: 'SET_SCROLL_X', payload: 0 });
                return;
            }

            // Jump to End
            if (matches(e, sc().jump_end)) {
                e.preventDefault();
                dispatch({ type: 'SET_PLAYHEAD', payload: state.totalDuration });
                return;
            }

            // Scrub Back (1 beat; Shift = 1 bar)
            if (matches(e, sc().scrub_back) && !e.ctrlKey) {
                e.preventDefault();
                const beatSec = state.bpm > 0 ? 60 / state.bpm : 0.5;
                const delta = e.shiftKey ? beatSec * 4 : beatSec;
                dispatch({ type: 'SET_PLAYHEAD', payload: Math.max(0, state.playhead - delta) });
                return;
            }

            // Scrub Forward (1 beat; Shift = 1 bar)
            if (matches(e, sc().scrub_fwd) && !e.ctrlKey) {
                e.preventDefault();
                const beatSec = state.bpm > 0 ? 60 / state.bpm : 0.5;
                const delta = e.shiftKey ? beatSec * 4 : beatSec;
                dispatch({ type: 'SET_PLAYHEAD', payload: Math.min(state.totalDuration, state.playhead + delta) });
                return;
            }

            // Split region
            if (matches(e, sc().split)) { e.preventDefault(); handleSplit(); return; }

            // Ripple Delete
            if (matches(e, sc().delete)) { e.preventDefault(); handleRippleDelete(); return; }

            // Undo (must check redo first — redo has Shift modifier)
            if (matches(e, sc().redo))  { e.preventDefault(); dispatch({ type: 'REDO' }); return; }
            if (matches(e, sc().undo))  { e.preventDefault(); dispatch({ type: 'UNDO' }); return; }

            // Copy
            if (matches(e, sc().copy)) {
                e.preventDefault();
                dispatch({ type: 'COPY_SELECTION' });
                toast.success('Copied to clipboard');
                return;
            }

            // Paste / Duplicate — must reschedule playback if running.
            // Web Audio's source.start() calls are queued at playRegions
            // time and don't pick up regions added afterward. Without the
            // restart, the user keeps hearing the OLD scheduled audio
            // across the paste point ("audio von davor"). We mark the
            // intent to resume; a useEffect on state.regions runs after
            // the reducer commits and re-schedules with the fresh array.
            if (matches(e, sc().paste)) {
                e.preventDefault();
                if (state.isPlaying) {
                    pendingResumeAt.current = DawEngine.getCurrentTime();
                    DawEngine.stopPlayback();
                }
                dispatch({ type: 'PASTE_INSERT' });
                toast.success('Pasted insert');
                return;
            }

            if (matches(e, sc().duplicate)) {
                e.preventDefault();
                if (state.isPlaying) {
                    pendingResumeAt.current = DawEngine.getCurrentTime();
                    DawEngine.stopPlayback();
                }
                dispatch({ type: 'DUPLICATE_SELECTION' });
                toast.success('Duplicated selection');
                return;
            }

            // Save
            if (matches(e, sc().save)) { e.preventDefault(); handleSave(); return; }

            // Open
            if (matches(e, sc().open)) { e.preventDefault(); handleOpen(); return; }

            // Shift (held) — Slip mode
            if (e.key === 'Shift') {
                dispatch({ type: 'SET_SLIP_MODE', payload: true });
                return;
            }

            // 1–8 — Hot cue jump
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
            <div className="flex flex-col h-full bg-mx-deepest text-white overflow-hidden">
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
                <div className="flex-1 flex flex-col overflow-hidden relative min-h-0">
                    {/* Waveform Overview Mini-Map (always shown, placeholder when no track) */}
                    <WaveformOverview state={state} dispatch={dispatch} />

                    {activeTrack ? (
                        // min-h-0 lets this flex child shrink/grow correctly so
                        // DawTimeline's ResizeObserver picks up the real available
                        // height instead of staying pinned at its default.
                        <div className="flex-1 relative min-h-0">
                            <DawTimeline
                                state={state}
                                dispatch={dispatch}
                                onRegionClick={handleRegionClick}
                            />
                            {/* Scrollbar Overlay at bottom of timeline area */}
                            <div className="absolute bottom-0 left-0 right-0 z-10">
                                <DawScrollbar state={state} dispatch={dispatch} />
                            </div>
                        </div>
                    ) : (
                        /* Empty State */
                        <div className="flex-1 flex flex-col items-center justify-center bg-mx-deepest/50">
                            <Music size={48} className="text-slate-800 mb-4" />
                            <h2 className="text-lg font-semibold text-ink-muted">No Project Loaded</h2>
                            <p className="text-sm text-ink-placeholder mt-2 mb-6">Select a track from the library below to start editing</p>
                            <div className="flex gap-3">
                                <button
                                    onClick={handleOpen}
                                    className="px-4 py-2 bg-mx-card hover:bg-mx-hover rounded-lg text-sm text-white transition-colors border border-white/5"
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
                    onExport={() => setShowExport(true)}
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

                {/* Export Modal */}
                {showExport && (
                    <ExportModal
                        state={state}
                        onClose={() => setShowExport(false)}
                    />
                )}

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
            <div className="flex items-center justify-center h-full text-red-500 bg-mx-deepest">
                <div className="text-center">
                    <h3 className="font-bold text-xl">DAW Render Error</h3>
                    <pre className="text-xs mt-2 text-left bg-black/50 p-4 rounded">{err.message}</pre>
                </div>
            </div>
        );
    }
};

// ─── HELPERS ───────────────────────────────────────────────────────────────────

/**
 * Convert backend waveform data ({low, mid, high} float arrays 0-1)
 * into the {min, max} peak format that DawTimeline expects.
 * Backend Butterworth 4th-order filters produce higher quality than client-side BiquadFilter.
 */
function convertBackendWaveform(data) {
    const toPeaks = (arr) =>
        arr.map(v => ({ min: -Math.abs(v), max: Math.abs(v) }));

    return {
        low:  toPeaks(data.low),
        mid:  toPeaks(data.mid),
        high: toPeaks(data.high),
    };
}

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
