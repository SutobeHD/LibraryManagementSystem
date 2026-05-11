import { useCallback } from 'react';
import { useHotkeys } from 'react-hotkeys-hook';
import api from '../../api/api';
import { log } from '../../utils/log';

const ZOOM_MIN = 50;
const ZOOM_MAX = 800;
const ZOOM_STEP = 50;

const HOT_CUE_COLORS = [
    '#2ecc71', '#e67e22', '#f1c40f', '#3498db',
    '#fd79a8', '#00d2d3', '#a29bfe', '#ff7675',
];

// Imperative editing + hotkey wiring extracted from WaveformEditor.
// Returns handler bag + bound hotkeys (the hotkey calls are side-effects of the hook).
// Caller owns all state (cuts, hotCues, loop, history) — this hook only produces actions.
export default function useWaveformInteractions({
    wavesurfer,
    fullTrack,
    track,
    duration,
    currentTime,
    setCurrentTime,
    cuts,
    setCuts,
    hotCues,
    setHotCues,
    loopIn,
    setLoopIn,
    loopOut,
    setLoopOut,
    setIsLooping,
    beatGrid,
    setBeatGrid,
    dropTime,
    setDropTime,
    setBpm,
    history,
    setHistory,
    historyIdx,
    setHistoryIdx,
    clipboard,
    setClipboard,
    setZoom,
    showConfirm,
    pushHistory,
    formatTime,
    trackBlobUrl,
    setFullTrack,
    setHistory: _setHistory,
    setHistoryIdx: _setHistoryIdx,
    setIsRendering,
    setRenderProgress,
    simpleMode,
    toast,
    setIsDragOver,
}) {
    // --- File drop (load local audio) ---
    const handleFileDrop = useCallback((file) => {
        if (!file) return;
        if (!file.type.startsWith('audio/') && !/\.(wav|mp3|flac|aac|ogg|m4a)$/i.test(file.name)) {
            toast.error('Unsupported file type — drop an audio file.');
            return;
        }
        const url = trackBlobUrl(URL.createObjectURL(file));
        const synthetic = {
            id: `local-${Date.now()}`,
            Title: file.name.replace(/\.[^/.]+$/, ''),
            Artist: 'Local file',
            path: url,
            BPM: 0,
        };
        setFullTrack(synthetic);
        // Reset everything for new track
        setLoopIn(null); setLoopOut(null); setIsLooping(false);
        setCuts([]); setHotCues([]); setBeatGrid([]);
        setHistory([]); setHistoryIdx(-1);
        // Force load with the new blob URL
        if (wavesurfer.current) {
            wavesurfer.current.load(url);
        }
        toast.success(`Loaded: ${file.name}`);
    }, [toast, trackBlobUrl, setFullTrack, setLoopIn, setLoopOut, setIsLooping, setCuts, setHotCues, setBeatGrid, setHistory, setHistoryIdx, wavesurfer]);

    // --- Hot Cues ---
    const handleSetHotCue = useCallback((num) => {
        if (!wavesurfer.current) return;
        const time = wavesurfer.current.getCurrentTime();
        const existing = hotCues.find(c => c.HotCueNum === num);

        const newCue = {
            ID: `cue-${Date.now()}`,
            HotCueNum: num,
            InPoint: time,
            Name: `Hot Cue ${String.fromCharCode(64 + num)}`,
            Color: HOT_CUE_COLORS[num - 1]
        };

        const apply = () => setHotCues(prev => {
            const without = prev.filter(c => c.HotCueNum !== num);
            return [...without, newCue];
        });

        // Existing cue: ask before overwrite (skip if same time within 100ms = re-click)
        if (existing && Math.abs(existing.InPoint - time) > 0.1) {
            showConfirm({
                title: `Overwrite Hot Cue ${String.fromCharCode(64 + num)}?`,
                message: `Replace existing cue at ${formatTime(existing.InPoint)} with new position ${formatTime(time)}?`,
                confirmLabel: 'Overwrite',
                onConfirm: apply,
            });
        } else {
            apply();
        }
    }, [hotCues, setHotCues, wavesurfer, showConfirm, formatTime]);

    const handleJumpHotCue = useCallback((num) => {
        const cue = hotCues.find(c => c.HotCueNum === num);
        if (cue && wavesurfer.current) {
            wavesurfer.current.setTime(cue.InPoint);
            setCurrentTime(cue.InPoint);
        }
    }, [hotCues, wavesurfer, setCurrentTime]);

    const handleDeleteHotCue = useCallback((num) => {
        setHotCues(prev => prev.filter(c => c.HotCueNum !== num));
    }, [setHotCues]);

    const jumpToCue = useCallback((time) => {
        if (wavesurfer.current) {
            wavesurfer.current.setTime(time);
            setCurrentTime(time);
        }
    }, [wavesurfer, setCurrentTime]);

    // --- Loop in/out ---
    const handleSetLoopIn = useCallback(() => setLoopIn(wavesurfer.current.getCurrentTime()), [setLoopIn, wavesurfer]);
    const handleSetLoopOut = useCallback(() => {
        const time = wavesurfer.current.getCurrentTime();
        if (loopIn !== null && time > loopIn) {
            setLoopOut(time);
            setIsLooping(true);
        }
    }, [loopIn, setLoopOut, setIsLooping, wavesurfer]);

    // --- Cue / Grid persistence ---
    const handleSaveCues = useCallback(async () => {
        if (!track) return;
        try {
            await api.post('/api/track/cues/save', { track_id: track.id, cues: hotCues });
            toast.success('Cues saved successfully!');
        } catch (err) { toast.error('Failed to save cues.'); }
    }, [track, hotCues, toast]);

    const handleGridShift = useCallback((delta) => {
        if (!beatGrid || beatGrid.length === 0) return;
        const newGrid = beatGrid.map(b => ({ ...b, time: b.time + delta }));
        setBeatGrid(newGrid);
        if (dropTime) setDropTime(prev => prev + delta);
        toast.info(`Grid shifted ${delta > 0 ? '+' : ''}${(delta * 1000).toFixed(0)}ms`);
    }, [beatGrid, setBeatGrid, dropTime, setDropTime, toast]);

    const handleSaveGrid = useCallback(async () => {
        if (!track) return;
        try {
            await api.post('/api/track/grid/save', { track_id: track.id, beat_grid: beatGrid });
            toast.success('Beat Grid saved!');
        } catch (err) { toast.error('Failed to save grid.'); }
    }, [track, beatGrid, toast]);

    const handleDetectDrop = useCallback(async () => {
        if (!fullTrack?.path) return;
        toast.info('Analyzing audio for drop...');
        try {
            const res = await api.post(`/api/track/${track.id}/analyze`);
            if (res.data.dropTime) {
                setDropTime(res.data.dropTime);
                setBpm(res.data.bpm);
                if (res.data.beats) setBeatGrid(res.data.beats);
                toast.success(`Drop detected at ${res.data.dropTime.toFixed(2)}s!`);
                wavesurfer.current?.setTime(res.data.dropTime);
            }
        } catch (err) {
            toast.error('Drop detection failed.');
        }
    }, [fullTrack, track, setDropTime, setBpm, setBeatGrid, toast, wavesurfer]);

    // --- Render / Export ---
    const handleRender = useCallback(async (inputCuts, customName = null) => {
        if (!fullTrack?.path || !duration) {
            toast.error('No track loaded or duration unknown.');
            return;
        }

        // Build segments to KEEP by inverting DELETE cuts
        let segments = [];

        // If no cuts or inputCuts is an Event object (button click), export full track
        if (!inputCuts || !Array.isArray(inputCuts) || inputCuts.length === 0) {
            segments = [{ start: 0, end: duration, src: fullTrack.path }];
        } else {
            // Sort delete cuts by start time
            const deleteCuts = inputCuts
                .filter(c => c.type === 'delete')
                .sort((a, b) => a.start - b.start);

            if (deleteCuts.length === 0) {
                // No delete cuts, export full track
                segments = [{ start: 0, end: duration, src: fullTrack.path }];
            } else {
                // Build keep segments by excluding deleted ranges
                let lastPos = 0;
                deleteCuts.forEach(cut => {
                    if (cut.start > lastPos) {
                        segments.push({ start: lastPos, end: cut.start, src: fullTrack.path });
                    }
                    lastPos = Math.max(lastPos, cut.end);
                });
                // Add remaining section after last delete
                if (lastPos < duration) {
                    segments.push({ start: lastPos, end: duration, src: fullTrack.path });
                }
            }

            // Handle insert cuts (paste/copy operations) - these add segments from source
            const insertCuts = inputCuts.filter(c => c.type === 'insert' && c.src);
            insertCuts.forEach(cut => {
                // Inserts paste audio from another source at a position
                // For now, we add them as separate segments
                if (cut.start !== undefined && cut.end !== undefined && cut.src) {
                    segments.push({ start: cut.start, end: cut.end, src: cut.src });
                }
            });
        }

        if (segments.length === 0) {
            toast.error('No valid segments to export.');
            return;
        }

        setIsRendering(true);
        setRenderProgress(10);
        try {
            const outputName = customName || `${fullTrack.Title || track?.Title || 'Track'}_Edit_${Date.now()}.wav`;
            const payload = {
                source_path: fullTrack.path,
                filename: fullTrack.Title || track?.Title || 'Track',
                cuts: segments,
                output_name: outputName,
                fade_in: false,
                fade_out: false
            };
            log.debug('Render Payload:', payload);
            setRenderProgress(30);
            const res = await api.post('/api/audio/render', payload);
            setRenderProgress(100);
            setTimeout(() => {
                setIsRendering(false);
                setRenderProgress(0);
                toast.success('Render Complete! File saved to exports folder.');
                if (res.data.track_id) {
                    toast.info('New track added to library.');
                }
            }, 500);
        } catch (err) {
            console.error('Render failed', err);
            toast.error('Render Failed: ' + (err.response?.data?.detail || err.message));
            setIsRendering(false);
        }
    }, [fullTrack, track, duration, toast, setIsRendering, setRenderProgress]);

    // --- Clipboard / Insert / Delete ---
    const handleCopy = useCallback(() => {
        if (!wavesurfer.current) {
            toast.error('Waveform not loaded.');
            return;
        }
        const regions = wavesurfer.current.plugins?.find(p => p.getRegions);
        if (!regions) {
            toast.error('Regions plugin not available.');
            return;
        }
        const selection = regions.getRegions()?.find(r => r.id === 'selection-range');
        if (!selection) {
            toast.error('No selection. Click on waveform to create a selection first.');
            return;
        }
        if (!fullTrack?.path) {
            toast.error('No track path available.');
            return;
        }
        setClipboard({
            duration: selection.end - selection.start,
            start: selection.start,
            end: selection.end,
            source_path: fullTrack.path
        });
        toast.success(`Copied ${(selection.end - selection.start).toFixed(2)}s section!`);
    }, [wavesurfer, fullTrack, setClipboard, toast]);

    const handlePaste = useCallback(() => {
        if (!clipboard) {
            toast.error('Clipboard empty. Use COPY first.');
            return;
        }
        const pSize = clipboard.duration;
        const pAt = currentTime;

        if (!clipboard.start && clipboard.start !== 0) {
            toast.error('No audio segment in clipboard.');
            return;
        }

        const newCut = {
            start: clipboard.start,
            end: clipboard.end,
            id: `cut-${Date.now()}`,
            type: 'insert',
            src: clipboard.source_path,
            insertAt: pAt,
            gap: pSize
        };

        setCuts(prev => [...prev, newCut]);
        pushHistory({ type: 'add_cut', data: newCut });
        toast.success(`Segment pasted at ${pAt.toFixed(2)}s.`);
        // Preview rebuild handled by debounced effect
    }, [clipboard, currentTime, setCuts, pushHistory, toast]);

    const handleInsert = useCallback(() => {
        const regions = wavesurfer.current?.plugins?.find(p => p.getRegions);
        const selection = regions?.getRegions()?.find(r => r.id === 'selection-range');
        if (!selection) {
            toast.error('No selection. Click and drag on waveform to select a region.');
            return;
        }

        const newCut = {
            start: selection.start,
            end: selection.end,
            id: `insert-${Date.now()}`,
            type: 'insert',
            insertAt: currentTime,
            gap: selection.end - selection.start
        };

        setCuts(prev => [...prev, newCut]);
        pushHistory({ type: 'add_cut', data: newCut });
        toast.info('Insert region marked.');
        // Preview handled by debounced effect
    }, [currentTime, setCuts, pushHistory, wavesurfer, toast]);

    const handleDelete = useCallback(() => {
        const regions = wavesurfer.current?.plugins?.find(p => p.getRegions);
        const selection = regions?.getRegions()?.find(r => r.id === 'selection-range');
        if (!selection) {
            toast.error('No selection. Click and drag on waveform to select a region.');
            return;
        }

        const newCut = {
            start: selection.start,
            end: selection.end,
            id: `delete-${Date.now()}`,
            type: 'delete'
        };

        setCuts(prev => [...prev, newCut]);
        pushHistory({ type: 'add_cut', data: newCut });
        toast.info('Section marked for deletion.');
        // Preview handled by debounced effect
    }, [setCuts, pushHistory, wavesurfer, toast]);

    const handleApplyAllEdits = useCallback(async () => {
        if (!fullTrack?.path || !duration) return;

        const deleteCuts = cuts.filter(c => c.type === 'delete').sort((a, b) => a.start - b.start);
        if (deleteCuts.length === 0) {
            toast.error('No delete regions found. Mark some sections with DELETE first.');
            return;
        }

        const keepSegments = [];
        let lastPos = 0;

        deleteCuts.forEach(cut => {
            if (cut.start > lastPos) {
                keepSegments.push({ start: lastPos, end: cut.start, src: fullTrack.path });
            }
            lastPos = Math.max(lastPos, cut.end);
        });

        if (lastPos < duration) {
            keepSegments.push({ start: lastPos, end: duration, src: fullTrack.path });
        }

        showConfirm({
            title: 'Apply All Edits?',
            message: `Render track without ${deleteCuts.length} deleted section${deleteCuts.length === 1 ? '' : 's'}?`,
            confirmLabel: 'Render',
            onConfirm: () => handleRender(keepSegments, `${fullTrack.Title}_Edited.wav`),
        });
    }, [fullTrack, duration, cuts, toast, showConfirm, handleRender]);

    // --- History (undo/redo/clear) ---
    const handleClear = useCallback(() => {
        if (cuts.length === 0) return;
        pushHistory({ type: 'clear_cuts', data: cuts });
        setCuts([]);
        // Preview rebuild via debounced effect
    }, [cuts, setCuts, pushHistory]);

    const handleUndo = useCallback(() => {
        if (historyIdx < 0) return;
        const last = history[historyIdx];
        if (last.type === 'add_cut') setCuts(prev => prev.filter(c => c.id !== last.data.id));
        if (last.type === 'clear_cuts') setCuts(last.data);
        setHistoryIdx(prev => prev - 1);
        // Preview rebuild via debounced effect
    }, [history, historyIdx, setCuts, setHistoryIdx]);

    const handleRedo = useCallback(() => {
        if (historyIdx >= history.length - 1) return;
        const next = history[historyIdx + 1];
        if (next.type === 'add_cut') setCuts(prev => [...prev, next.data]);
        if (next.type === 'clear_cuts') setCuts([]);
        setHistoryIdx(prev => prev + 1);
    }, [history, historyIdx, setCuts, setHistoryIdx]);

    // --- Generic skip handler used by left/right hotkeys ---
    const skip = useCallback((amount) => {
        if (wavesurfer.current) {
            const time = wavesurfer.current.getCurrentTime();
            wavesurfer.current.setTime(Math.min(duration, Math.max(0, time + amount)));
        }
    }, [wavesurfer, duration]);

    // --- Hotkeys ---
    useHotkeys('left', (e) => { e.preventDefault(); skip(-10); }, [duration, skip]);
    useHotkeys('right', (e) => { e.preventDefault(); skip(10); }, [duration, skip]);
    useHotkeys('space', (e) => {
        if (simpleMode) return; // Ranking mode uses space for 'Next', so we ignore it here
        e.preventDefault();
        if (wavesurfer.current) wavesurfer.current.playPause();
    }, [simpleMode]);

    // Edit hotkeys — only active in full mode (simpleMode is ranking, conflicts with shortcuts)
    const editHotkeyOpts = { enabled: !simpleMode, preventDefault: true, enableOnFormTags: false };
    useHotkeys('ctrl+c, meta+c', () => handleCopy(), editHotkeyOpts, [handleCopy]);
    useHotkeys('ctrl+v, meta+v', () => handlePaste(), editHotkeyOpts, [handlePaste]);
    useHotkeys('i', () => handleInsert(), editHotkeyOpts, [handleInsert]);
    useHotkeys('delete, backspace', () => handleDelete(), editHotkeyOpts, [handleDelete]);
    useHotkeys('ctrl+z, meta+z', () => handleUndo(), editHotkeyOpts, [handleUndo]);
    useHotkeys('ctrl+shift+z, meta+shift+z, ctrl+y, meta+y', () => handleRedo(), editHotkeyOpts, [handleRedo]);
    useHotkeys('ctrl+e, meta+e', () => handleRender(cuts), editHotkeyOpts, [handleRender, cuts]);
    useHotkeys('ctrl+s, meta+s', () => handleSaveCues(), editHotkeyOpts, [handleSaveCues]);
    // Zoom shortcuts
    useHotkeys('ctrl+plus, meta+plus, ctrl+equal, meta+equal', () => setZoom(p => Math.min(ZOOM_MAX, p + ZOOM_STEP)), editHotkeyOpts);
    useHotkeys('ctrl+minus, meta+minus', () => setZoom(p => Math.max(ZOOM_MIN, p - ZOOM_STEP)), editHotkeyOpts);
    // Loop in/out
    useHotkeys('l', () => loopIn === null ? handleSetLoopIn() : handleSetLoopOut(), editHotkeyOpts, [loopIn, handleSetLoopIn, handleSetLoopOut]);
    useHotkeys('shift+l', () => { setLoopIn(null); setLoopOut(null); setIsLooping(false); }, editHotkeyOpts);
    // Hot Cues: 1-8 jump, Shift+1-8 set
    useHotkeys('1,2,3,4,5,6,7,8', (e, h) => {
        const num = parseInt(h.keys?.[0] ?? e.key, 10);
        if (num >= 1 && num <= 8) handleJumpHotCue(num);
    }, editHotkeyOpts, [handleJumpHotCue]);
    useHotkeys('shift+1,shift+2,shift+3,shift+4,shift+5,shift+6,shift+7,shift+8', (e, h) => {
        const num = parseInt((h.keys?.[0] ?? e.key).replace('shift+', ''), 10);
        if (num >= 1 && num <= 8) handleSetHotCue(num);
    }, editHotkeyOpts, [handleSetHotCue]);

    return {
        handleFileDrop,
        handleSetHotCue,
        handleJumpHotCue,
        handleDeleteHotCue,
        jumpToCue,
        handleSetLoopIn,
        handleSetLoopOut,
        handleSaveCues,
        handleGridShift,
        handleSaveGrid,
        handleDetectDrop,
        handleRender,
        handleCopy,
        handlePaste,
        handleInsert,
        handleDelete,
        handleApplyAllEdits,
        handleClear,
        handleUndo,
        handleRedo,
        skip,
    };
}

export { HOT_CUE_COLORS, ZOOM_MIN, ZOOM_MAX, ZOOM_STEP };
