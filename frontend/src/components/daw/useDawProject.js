/**
 * useDawProject — Project persistence hook for the DJ Edit DAW
 *
 * Owns:
 *   • File input ref used by the hidden <input type="file" />
 *   • `skipNextAutoLoad` ref so the activeTrack effect can be bypassed when
 *     a .rbep project has already hydrated regions + audio.
 *   • Open / save / file-select handlers and the buildProjectFromState helper.
 *
 * Exposes handlers consumed by the toolbar and keyboard shortcuts:
 *   handleSave, handleOpen, handleFileSelect, handleOpenProject
 *
 * The hook does NOT manage <input> rendering — the container is still
 * responsible for mounting the hidden file input and wiring fileInputRef.
 */
import { useCallback, useRef } from 'react';
import toast from 'react-hot-toast';

import * as DawEngine from '../../audio/DawEngine';
import { createInitialState, cuePointsToState, stateToCuePoints } from '../../audio/DawState';
import { parseRbep, buildTempoMap, saveRbepFile } from '../../audio/RbepSerializer';
import AudioBandAnalyzer from '../../utils/AudioBandAnalyzer';
import { promptModal } from '../PromptModal';
import { TOAST_DURATION_LONG_MS } from '../../config/constants';

/**
 * Build a serialisable project object from current DAW state.
 * Moved out of the container because it's only used by handleSave.
 */
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

export default function useDawProject({ state, dispatch, setActiveTrack }) {
    const fileInputRef = useRef(null);

    // Set to true when handleFileSelect has loaded a .rbep project — tells the
    // activeTrack loadTrack useEffect to skip re-initializing the regions/audio,
    // so it doesn't overwrite the 9 parsed regions with a single default region.
    const skipNextAutoLoad = useRef(false);

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
    }, [dispatch, setActiveTrack]);

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
    }, [state, dispatch]);

    const handleOpenProject = useCallback((_filepath) => {
        handleOpen();
    }, [handleOpen]);

    return {
        fileInputRef,
        skipNextAutoLoad,
        handleSave,
        handleOpen,
        handleFileSelect,
        handleOpenProject,
    };
}
