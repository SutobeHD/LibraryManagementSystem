/**
 * useEditorPersistence - .rbep project save / list / load
 *
 * Talks to backend endpoints:
 * - POST /api/projects/save
 * - GET  /api/projects/rbep/list
 * - GET  /api/projects/rbep/:name
 *
 * Takes shared refs from useEditorPlayback so loaded projects can re-decode
 * audio into the existing AudioContext / sourceBufferRef.
 */

import { useCallback, useState } from 'react';
import toast from 'react-hot-toast';
import api from '../../api/api';
import { promptModal } from '../PromptModal';
import { createRegion } from '../../audio/AudioRegion';

export default function useEditorPersistence({
    state,
    setState,
    sourcePath,
    track,
    audioContextRef,
    sourceBufferRef,
    setIsLoading,
}) {
    const [showLoadModal, setShowLoadModal] = useState(false);
    const [projectList, setProjectList] = useState([]);

    const handleSaveProject = useCallback(async () => {
        const name = await promptModal({
            title: 'Save project',
            message: 'Enter project name:',
            defaultValue: track?.Title || 'Untitled Project',
        });
        if (!name) return;

        // Serialize state: Remove AudioBuffers (circular/large)
        const serializableRegions = state.regions.map(r => {
            const { sourceBuffer, ...rest } = r;
            return rest;
        });

        const projectData = {
            version: 1,
            sourcePath,
            trackId: track?.id,
            bpm: state.bpm,
            beatGrid: state.beatGrid,
            markers: state.markers,
            zoom: state.zoom,
            snapEnabled: state.snapEnabled,
            snapDivision: state.snapDivision,
            regions: serializableRegions,
            paletteSlots: state.paletteSlots.map(slot => {
                if (!slot) return null;
                const { sourceBuffer, ...rest } = slot;
                return rest;
            })
        };

        try {
            await api.post('/api/projects/save', { name, data: projectData });
            toast.success('Project saved successfully!');
        } catch (error) {
            console.error(error);
            toast.error('Failed to save project.');
        }
    }, [state, sourcePath, track]);

    const handleLoadClick = useCallback(async () => {
        try {
            const res = await api.get('/api/projects/rbep/list');
            setProjectList(res.data || []);
            setShowLoadModal(true);
        } catch (e) { toast.error('Failed to list projects'); }
    }, []);

    const loadProject = useCallback(async (prjName) => {
        try {
            setIsLoading(true);
            setShowLoadModal(false);
            const res = await api.get(`/api/projects/rbep/${encodeURIComponent(prjName)}`);
            const data = res.data;

            if (!data.tracks || data.tracks.length === 0) {
                toast.error('Project has no tracks');
                setIsLoading(false);
                return;
            }

            const firstTrack = data.tracks[0];
            const trackPath = firstTrack.filepath;

            // 1. Load audio source from the track's filepath
            let buffer = sourceBufferRef.current;
            if (trackPath && trackPath !== sourcePath) {
                const url = `/api/stream?path=${encodeURIComponent(trackPath)}`;
                const ctx = audioContextRef.current || new (window.AudioContext || window.webkitAudioContext)();
                if (!audioContextRef.current) audioContextRef.current = ctx;

                const resp = await fetch(url);
                const ab = await resp.arrayBuffer();
                buffer = await ctx.decodeAudioData(ab);
                sourceBufferRef.current = buffer;
            }

            // 2. Convert RBEP edit data into timeline regions
            const regions = [];
            const edit = firstTrack.edit;
            if (edit && edit.volume && edit.volume.length > 0) {
                edit.volume.forEach((vol, i) => {
                    regions.push(createRegion({
                        sourceBuffer: buffer,
                        sourcePath: trackPath,
                        sourceStart: vol.start,
                        sourceEnd: vol.end,
                        timelineStart: vol.start,
                        name: `Volume ${i + 1}`,
                        color: vol.vol < 1.0 ? '#f59e0b' : '#06b6d4',
                        gain: vol.vol
                    }));
                });
            } else if (firstTrack.position) {
                // Create a single region from position data
                const pos = firstTrack.position;
                regions.push(createRegion({
                    sourceBuffer: buffer,
                    sourcePath: trackPath,
                    sourceStart: pos.songStart || pos.start || 0,
                    sourceEnd: pos.songEnd || pos.end || (buffer?.duration || 0),
                    timelineStart: 0,
                    name: firstTrack.title || data.name,
                    color: '#06b6d4'
                }));
            }

            // 3. Extract beat grid from RBEP
            const rbepBeatGrid = (firstTrack.beatGrid || []).map(b => ({
                index: b.index,
                bpm: b.bpm,
                position: b.position / 1000  // Convert ms to seconds
            }));

            // 4. Set state with loaded project data
            setState(prev => ({
                ...prev,
                regions: regions.length > 0 ? regions : prev.regions,
                markers: data.markers || firstTrack.positionMarks || [],
                bpm: firstTrack.bpm || (edit?.bpm?.[0]?.bpm) || prev.bpm,
                beatGrid: rbepBeatGrid.length > 0 ? rbepBeatGrid : prev.beatGrid,
                zoom: 50,
                snapEnabled: true,
                snapDivision: '1/4',
                playhead: 0,
                history: [],
                historyIndex: -1
            }));

            setIsLoading(false);
        } catch (e) {
            console.error(e);
            toast.error('Failed to load project: ' + e.message);
            setIsLoading(false);
        }
    }, [sourcePath, setState, audioContextRef, sourceBufferRef, setIsLoading]);

    return {
        showLoadModal,
        setShowLoadModal,
        projectList,
        handleSaveProject,
        handleLoadClick,
        loadProject,
    };
}
