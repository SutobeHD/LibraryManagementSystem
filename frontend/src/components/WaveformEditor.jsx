import React, { useRef, useEffect, useState, useCallback, useMemo, forwardRef, useImperativeHandle } from 'react';
import AudioBandAnalyzer from '../utils/AudioBandAnalyzer';
import api from '../api/api';
import { log } from '../utils/log';
import { useToast } from './ToastContext';
import EditorBrowser from './editor/EditorBrowser';
import WaveformCanvas from './waveform/WaveformCanvas';
import WaveformControls, { WaveformBottomPanels } from './waveform/WaveformControls';
import WaveformOverlays from './waveform/WaveformOverlays';
import WaveformZoom from './waveform/WaveformZoom';
import WaveformSimpleView from './waveform/WaveformSimpleView';
import WaveformErrorBoundary from './waveform/WaveformErrorBoundary';
import ConfirmModal from './waveform/ConfirmModal';
import useWaveformInteractions from './waveform/useWaveformInteractions';
import useWaveSurfer from './waveform/useWaveSurfer';
import useMultibandLayers from './waveform/useMultibandLayers';
import useVisualPreview from './waveform/useVisualPreview';
import useEditPersistence from './waveform/useEditPersistence';
import computeBeats from './waveform/computeBeats';

const ZOOM_DEFAULT = 200;

const WaveformEditorInner = forwardRef(({ track, blobUrl = null, simpleMode = false, isPlayingExternal = null, onPlayPause = null, volume = 1 }, ref) => {
    const toast = useToast();
    const waveformRef = useRef(null);
    const overviewRef = useRef(null);
    const wavesurfer = useRef(null);
    const overviewWs = useRef(null);
    const isMountedRef = useRef(true);
    const originalBufferRef = useRef(null); // Cache original audio for non-destructive preview
    const onPlayPauseRef = useRef(onPlayPause); // Ref to avoid stale closure in wavesurfer event handlers
    const isPlayingExternalRef = useRef(isPlayingExternal);
    const beatCanvasRef = useRef(null);
    const [isVisible, setIsVisible] = useState(false);

    // Keep refs in sync with latest props
    useEffect(() => { onPlayPauseRef.current = onPlayPause; }, [onPlayPause]);
    useEffect(() => { isPlayingExternalRef.current = isPlayingExternal; }, [isPlayingExternal]);

    useEffect(() => {
        const observer = new IntersectionObserver(
            ([entry]) => {
                if (entry.isIntersecting) {
                    setIsVisible(true);
                    observer.disconnect(); // Execute once
                }
            },
            { threshold: 0.1 }
        );
        if (waveformRef.current) observer.observe(waveformRef.current);
        else if (overviewRef.current) observer.observe(overviewRef.current);
        return () => observer.disconnect();
    }, []);

    useEffect(() => {
        isMountedRef.current = true;
        return () => { isMountedRef.current = false; };
    }, []);

    // Volume Control — local state, defaults to prop, can be overridden by user
    const [internalVolume, setInternalVolume] = useState(volume);
    useEffect(() => { setInternalVolume(volume); }, [volume]);
    useEffect(() => {
        if (wavesurfer.current) wavesurfer.current.setVolume(internalVolume);
    }, [internalVolume]);

    const [internalPlaying, setInternalPlaying] = useState(false);
    const isPlaying = isPlayingExternal !== undefined ? isPlayingExternal : internalPlaying;

    const [currentTime, setCurrentTime] = useState(0);
    const [duration, setDuration] = useState(0);
    const [loading, setLoading] = useState(false);
    const [bpm, setBpm] = useState(track?.BPM || 128);
    const [beatGrid, setBeatGrid] = useState([]);
    const [zoom, setZoom] = useState(ZOOM_DEFAULT);
    const [fullTrack, setFullTrack] = useState(track?.path ? track : null);

    const [selectedBeats, setSelectedBeats] = useState(1);
    const [isQuantized, setIsQuantized] = useState(true);
    const [selectionStart, setSelectionStart] = useState(0);
    const [clipboard, setClipboard] = useState(null);
    const [dropTime, setDropTime] = useState(null);
    const [hotCues, setHotCues] = useState([]);
    const [loopIn, setLoopIn] = useState(null);
    const [loopOut, setLoopOut] = useState(null);
    const [isLooping, setIsLooping] = useState(false);
    const [visualMode, setVisualMode] = useState('blue'); // 'blue', 'rgb', '3band'
    const [multibandBuffers, setMultibandBuffers] = useState(null);
    const [analyzing, setAnalyzing] = useState(false);
    const [bufferReady, setBufferReady] = useState(false);
    const [cuts, setCuts] = useState([]);
    const [history, setHistory] = useState([]);
    const [historyIdx, setHistoryIdx] = useState(-1);
    const [projectList, setProjectList] = useState([]);
    const [selectedProject, setSelectedProject] = useState('');
    const [isRendering, setIsRendering] = useState(false);
    const [renderProgress, setRenderProgress] = useState(0);
    const [showBrowser, setShowBrowser] = useState(false);
    const [confirmModal, setConfirmModal] = useState(null); // { title, message, onConfirm, confirmLabel }
    const [isDragOver, setIsDragOver] = useState(false);
    const showConfirm = useCallback((opts) => setConfirmModal(opts), []);

    // Refs for multi-band layers (slave WaveSurfer instances live inside useMultibandLayers)
    const waveLowRef = useRef(null);
    const waveMidRef = useRef(null);
    const waveHighRef = useRef(null);

    // Track Blob-URLs for cleanup (memory leak prevention)
    const blobUrlsRef = useRef([]);
    const trackBlobUrl = useCallback((url) => {
        blobUrlsRef.current.push(url);
        return url;
    }, []);
    const revokeAllBlobUrls = useCallback(() => {
        blobUrlsRef.current.forEach(u => { try { URL.revokeObjectURL(u); } catch (e) { log.debug('WaveformEditor revokeObjectURL failed', e); } });
        blobUrlsRef.current = [];
    }, []);
    useEffect(() => () => revokeAllBlobUrls(), [revokeAllBlobUrls]);

    // Fetch Global Settings on mount
    useEffect(() => {
        (async () => {
            try {
                const res = await api.get('/api/settings');
                if (res.data.waveform_visual_mode) setVisualMode(res.data.waveform_visual_mode);
            } catch (e) { console.warn('Failed to load waveform settings', e); }
        })();
    }, []);

    // Analyze Audio when needed (decode the 3 EQ-band buffers)
    useEffect(() => {
        const analyze = async () => {
            if ((visualMode === 'rgb' || visualMode === '3band') && !multibandBuffers && originalBufferRef.current && !analyzing) {
                setAnalyzing(true);
                try {
                    const bands = await AudioBandAnalyzer.splitBands(originalBufferRef.current);
                    const lowBlob = AudioBandAnalyzer.bufferToWav(bands.low);
                    const midBlob = AudioBandAnalyzer.bufferToWav(bands.mid);
                    const highBlob = AudioBandAnalyzer.bufferToWav(bands.high);
                    setMultibandBuffers({ low: lowBlob, mid: midBlob, high: highBlob });
                } catch (e) {
                    console.error('Analysis Failed', e);
                    toast.error('Waveform Analysis Failed');
                } finally {
                    setAnalyzing(false);
                }
            }
        };
        analyze();
    }, [visualMode, multibandBuffers, bufferReady]);

    // Slave-band lifecycle + RAF sync loop
    useMultibandLayers({ wavesurfer, waveLowRef, waveMidRef, waveHighRef, visualMode, multibandBuffers, zoom, trackBlobUrl });

    const handleToggleVisualMode = async () => {
        const modes = ['blue', 'rgb', '3band'];
        const next = modes[(modes.indexOf(visualMode) + 1) % modes.length];
        setVisualMode(next);
        try {
            const curr = await api.get('/api/settings');
            await api.post('/api/settings', { ...curr.data, waveform_visual_mode: next });
            toast.success(`Mode saved: ${next.toUpperCase()}`);
        } catch (e) { console.warn('Failed to save mode', e); }
    };

    // History helper — caps at 50 entries to prevent unbounded memory growth
    const HISTORY_LIMIT = 50;
    const pushHistory = useCallback((entry) => {
        setHistory(prev => {
            const truncated = prev.slice(0, historyIdx + 1);
            const next = [...truncated, entry];
            return next.length > HISTORY_LIMIT ? next.slice(next.length - HISTORY_LIMIT) : next;
        });
        setHistoryIdx(prev => Math.min(prev + 1, HISTORY_LIMIT - 1));
    }, [historyIdx]);

    // Auto-open browser if no track is loaded
    useEffect(() => {
        if (!fullTrack && !loading && !track) setShowBrowser(true);
    }, [fullTrack, loading, track]);

    // Refs for loop state (accessible in audioprocess callback)
    const loopInRef = useRef(loopIn);
    const loopOutRef = useRef(loopOut);
    const isLoopingRef = useRef(isLooping);
    const beatsRef = useRef([]); // Initialize empty to avoid ReferenceError
    const isQuantizedRef = useRef(isQuantized);
    useEffect(() => { loopInRef.current = loopIn; }, [loopIn]);
    useEffect(() => { loopOutRef.current = loopOut; }, [loopOut]);
    useEffect(() => { isLoopingRef.current = isLooping; }, [isLooping]);
    useEffect(() => { isQuantizedRef.current = isQuantized; }, [isQuantized]);

    useEffect(() => { api.get('/api/projects').then(res => setProjectList(res.data)); }, []);

    useEffect(() => {
        if (track?.id && !track?.path) {
            setLoading(true);
            api.get(`/api/track/${track.id}`).then(res => {
                setFullTrack(res.data);
                if (res.data.BPM) setBpm(parseFloat(res.data.BPM));
                if (res.data.beatGrid) setBeatGrid(res.data.beatGrid);
                if (res.data.dropTime) setDropTime(parseFloat(res.data.dropTime));
                setLoading(false);
            }).catch(() => setLoading(false));
        } else {
            setFullTrack(track);
            setLoading(false);
        }
    }, [track, track?.id]);

    useImperativeHandle(ref, () => ({
        setTime: (time) => wavesurfer.current?.setTime(time),
        getCurrentTime: () => wavesurfer.current?.getCurrentTime() || 0,
        playPause: () => wavesurfer.current?.playPause(),
        stop: () => wavesurfer.current?.stop()
    }));

    const loadTrack = useCallback((t) => {
        if (!t) return;
        const trackData = { ...t };
        // Polyfill path if missing (e.g. from raw DB scan)
        if (!trackData.path) {
            if (trackData.Path) trackData.path = trackData.Path;
            else if (trackData.FolderPath && trackData.FileNameL) {
                const folder = trackData.FolderPath.replace(/^localhost\//, '');
                trackData.path = `${folder}/${trackData.FileNameL}`.replace(/\\/g, '/');
            }
        }
        setFullTrack(trackData);
        // Reset state
        if (wavesurfer.current) {
            wavesurfer.current.stop();
            wavesurfer.current.setTime(0);
        }
        setLoopIn(null);
        setLoopOut(null);
        setIsLooping(false);
        setCuts([]);
        setHotCues([]);
        setBeatGrid([]);
    }, []);

    const beats = useMemo(() => computeBeats(beatGrid, bpm, duration), [beatGrid, bpm, duration]);
    useEffect(() => { beatsRef.current = beats; }, [beats]);

    const streaming = useMemo(() => {
        const path = fullTrack?.path || fullTrack?.Path || '';
        return path.startsWith('soundcloud:') || path.startsWith('spotify:') || path.startsWith('tidal:') || path.startsWith('beatport:');
    }, [fullTrack]);

    // Master WaveSurfer lifecycle + track loading + playback/zoom sync (init effect lives here)
    useWaveSurfer({
        wavesurfer, overviewWs, waveformRef, overviewRef, originalBufferRef, isMountedRef,
        isPlayingExternalRef, isQuantizedRef, beatsRef, loopInRef, loopOutRef, isLoopingRef, onPlayPauseRef,
        fullTrack, blobUrl, streaming, isVisible, simpleMode, zoom, isPlaying, isPlayingExternal,
        revokeAllBlobUrls,
        setDuration, setLoading, setBufferReady, setMultibandBuffers, setCurrentTime, setSelectionStart, setZoom, setInternalPlaying,
        setLoopIn, setLoopOut, setIsLooping, setCuts, setHotCues, setBeatGrid, setHistory, setHistoryIdx, setClipboard,
        toast,
    });

    const formatTime = useCallback((s) => {
        const m = Math.floor(s / 60);
        const sec = Math.floor(s % 60);
        const ms = Math.floor((s % 1) * 100);
        return `${m}:${sec.toString().padStart(2, '0')}.${ms.toString().padStart(2, '0')}`;
    }, []);

    // --- Imperative interactions (hotkeys + handlers extracted to hook) ---
    const interactions = useWaveformInteractions({
        wavesurfer, fullTrack, track, duration, currentTime, setCurrentTime,
        cuts, setCuts, hotCues, setHotCues, loopIn, setLoopIn, loopOut, setLoopOut, setIsLooping,
        beatGrid, setBeatGrid, dropTime, setDropTime, setBpm,
        history, setHistory, historyIdx, setHistoryIdx, clipboard, setClipboard, setZoom,
        showConfirm, pushHistory, formatTime, trackBlobUrl, setFullTrack,
        setIsRendering, setRenderProgress, simpleMode, toast, setIsDragOver,
    });

    // Debounced non-destructive preview rebuild when cuts change
    useVisualPreview({ wavesurfer, originalBufferRef, isMountedRef, blobUrl, fullTrack, duration, bufferReady, cuts, trackBlobUrl, toast });

    // localStorage auto-save + restore
    useEditPersistence({ fullTrack, bufferReady, cuts, hotCues, setCuts, setHotCues, toast });

    // Drag handlers for the canvas drop zone
    const onDragEnter = useCallback((e) => { e.preventDefault(); e.stopPropagation(); setIsDragOver(true); }, []);
    const onDragOver = useCallback((e) => { e.preventDefault(); e.stopPropagation(); e.dataTransfer.dropEffect = 'copy'; }, []);
    const onDragLeave = useCallback((e) => {
        e.preventDefault(); e.stopPropagation();
        if (!e.currentTarget.contains(e.relatedTarget)) setIsDragOver(false);
    }, []);
    const onDrop = useCallback((e) => {
        e.preventDefault(); e.stopPropagation();
        setIsDragOver(false);
        const file = e.dataTransfer.files?.[0];
        if (file) interactions.handleFileDrop(file);
    }, [interactions]);

    if (loading && !fullTrack) return <div className="flex h-full items-center justify-center text-ink-muted bg-black">Loading...</div>;

    if (simpleMode) {
        return (
            <WaveformSimpleView
                overviewRef={overviewRef}
                waveformRef={waveformRef}
                waveLowRef={waveLowRef}
                waveMidRef={waveMidRef}
                waveHighRef={waveHighRef}
                visualMode={visualMode}
                analyzing={analyzing}
                handleToggleVisualMode={handleToggleVisualMode}
            />
        );
    }

    return (
        <div className="rb-edit-container relative">
            <WaveformControls
                fullTrack={fullTrack}
                showBrowser={showBrowser} setShowBrowser={setShowBrowser}
                isQuantized={isQuantized} setIsQuantized={setIsQuantized}
                selectedProject={selectedProject} setSelectedProject={setSelectedProject}
                projectList={projectList}
                hotCues={hotCues}
                handleSetHotCue={interactions.handleSetHotCue}
                handleJumpHotCue={interactions.handleJumpHotCue}
                handleDeleteHotCue={interactions.handleDeleteHotCue}
                jumpToCue={interactions.jumpToCue}
                formatTime={formatTime}
                wavesurfer={wavesurfer}
                isPlaying={isPlaying}
                internalVolume={internalVolume} setInternalVolume={setInternalVolume}
                visualMode={visualMode} handleToggleVisualMode={handleToggleVisualMode}
                handleGridShift={interactions.handleGridShift}
                handleSaveGrid={interactions.handleSaveGrid}
                handleDetectDrop={interactions.handleDetectDrop}
                currentTime={currentTime} duration={duration} bpm={bpm}
                isRendering={isRendering} renderProgress={renderProgress}
            />

            {showBrowser && (
                <div className="absolute left-0 top-[88px] bottom-0 z-[60] shadow-2xl flex animate-slide-in-left">
                    <EditorBrowser onLoadTrack={loadTrack} onClose={() => setShowBrowser(false)} />
                </div>
            )}

            <WaveformCanvas
                waveformRef={waveformRef} overviewRef={overviewRef} beatCanvasRef={beatCanvasRef}
                waveLowRef={waveLowRef} waveMidRef={waveMidRef} waveHighRef={waveHighRef}
                wavesurfer={wavesurfer}
                visualMode={visualMode} streaming={streaming} loading={loading}
                isDragOver={isDragOver}
                onDragEnter={onDragEnter} onDragOver={onDragOver} onDragLeave={onDragLeave} onDrop={onDrop}
                beats={beats} duration={duration} bpm={bpm} zoom={zoom}
            >
                <WaveformOverlays
                    wavesurfer={wavesurfer} overviewWs={overviewWs}
                    duration={duration} simpleMode={simpleMode}
                    bpm={bpm} beats={beats}
                    selectionStart={selectionStart} selectedBeats={selectedBeats} isQuantized={isQuantized}
                    cuts={cuts} setCuts={setCuts} setCurrentTime={setCurrentTime}
                    dropTime={dropTime} hotCues={hotCues}
                    loopIn={loopIn} loopOut={loopOut}
                    handleClear={interactions.handleClear}
                />
                <WaveformZoom zoom={zoom} setZoom={setZoom} />
            </WaveformCanvas>

            <WaveformBottomPanels
                isLooping={isLooping} loopIn={loopIn} loopOut={loopOut}
                setLoopIn={setLoopIn} setLoopOut={setLoopOut} setIsLooping={setIsLooping}
                handleSetLoopIn={interactions.handleSetLoopIn} handleSetLoopOut={interactions.handleSetLoopOut}
                selectedBeats={selectedBeats} setSelectedBeats={setSelectedBeats}
                bpm={bpm}
                hotCues={hotCues}
                handleSetHotCue={interactions.handleSetHotCue}
                handleJumpHotCue={interactions.handleJumpHotCue}
                handleDeleteHotCue={interactions.handleDeleteHotCue}
                handleSaveCues={interactions.handleSaveCues}
                handleCopy={interactions.handleCopy} handlePaste={interactions.handlePaste}
                handleInsert={interactions.handleInsert} handleDelete={interactions.handleDelete}
                handleClear={interactions.handleClear}
                handleUndo={interactions.handleUndo} handleRedo={interactions.handleRedo}
                handleRender={interactions.handleRender}
                formatTime={formatTime}
                cuts={cuts} history={history} historyIdx={historyIdx}
            />

            <ConfirmModal modal={confirmModal} setModal={setConfirmModal} />
        </div>
    );
});

// Public export wraps the inner component in an ErrorBoundary so a WaveSurfer
// or decode crash doesn't take the whole app down.
const WaveformEditor = forwardRef((props, ref) => (
    <WaveformErrorBoundary>
        <WaveformEditorInner {...props} ref={ref} />
    </WaveformErrorBoundary>
));

export default WaveformEditor;
