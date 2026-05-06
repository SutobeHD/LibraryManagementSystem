import React, { useRef, useEffect, useState, useMemo, useCallback, forwardRef, useImperativeHandle } from 'react';
import AudioBandAnalyzer from '../utils/AudioBandAnalyzer';
import api from '../api/api';
import { useToast } from './ToastContext';
import EditorBrowser from './editor/EditorBrowser';
import {
    Play, Pause, SkipBack, SkipForward, Scissors, Plus, Trash2, Download,
    ZoomIn, ZoomOut, Lock, Unlock, Repeat, ChevronLeft, ChevronRight,
    Grid3X3, Music, Clock, Disc, MousePointer, ScanLine, Sparkles, Loader2,
    RotateCcw, RotateCw, Copy, Clipboard, ListPlus, Terminal, Save, Infinity, X, Type, Target, Zap, Layers
} from 'lucide-react';
import { useHotkeys } from 'react-hotkeys-hook';

// Zoom range: minPxPerSec for WaveSurfer
const ZOOM_MIN = 50;
const ZOOM_MAX = 800;
const ZOOM_STEP = 50;
const ZOOM_DEFAULT = 200;

// --- Utility: Slice Audio Buffer for Instant Preview ---
// --- Utility: Build Preview Buffer (Async with Splicing) ---
const buildPreviewBuffer = async (originalBuffer, cuts, originalDuration, originalPath) => {
    // 1. Build Base Segments (Handle Deletes)
    const deleteCuts = cuts.filter(c => c.type === 'delete').sort((a, b) => a.start - b.start);
    let baseSegments = [];
    let lastPos = 0;

    deleteCuts.forEach(cut => {
        if (cut.start > lastPos) {
            baseSegments.push({
                src: 'ORIGINAL',
                start: lastPos,
                end: cut.start,
                duration: cut.start - lastPos
            });
        }
        lastPos = Math.max(lastPos, cut.end);
    });
    if (lastPos < originalDuration) {
        baseSegments.push({
            src: 'ORIGINAL',
            start: lastPos,
            end: originalDuration,
            duration: originalDuration - lastPos
        });
    }

    // Step A: Construct Base Buffer
    const baseTotalLen = baseSegments.reduce((sum, s) => sum + s.duration, 0);
    const sampleRate = originalBuffer.sampleRate;
    const channels = originalBuffer.numberOfChannels;

    // Create Base Buffer
    const baseFrames = Math.max(1, Math.floor(baseTotalLen * sampleRate));
    const baseCtx = new OfflineAudioContext(channels, baseFrames, sampleRate);
    const baseBuf = baseCtx.createBuffer(channels, baseFrames, sampleRate);

    // Fill Base Buffer
    let ptr = 0;
    for (let seg of baseSegments) {
        const segLen = Math.floor(seg.duration * sampleRate);
        const startFrame = Math.floor(seg.start * sampleRate);

        for (let c = 0; c < channels; c++) {
            const inData = originalBuffer.getChannelData(c);
            const outData = baseBuf.getChannelData(c);
            if (ptr + segLen <= baseBuf.length && startFrame + segLen <= originalBuffer.length) {
                outData.set(inData.subarray(startFrame, startFrame + segLen), ptr);
            }
        }
        ptr += segLen;
    }

    // 2. Inject Inserts
    // SORT DESCENDING by insertAt to avoid index invalidation during sequential splicing
    const inserts = cuts.filter(c => c.type === 'insert').sort((a, b) => b.insertAt - a.insertAt);

    let currentBuf = baseBuf;

    for (let ins of inserts) {
        // Fetch Insert Audio
        let insBuf = null;
        if (ins.src && ins.start !== undefined && ins.end !== undefined) {
            try {
                const sliceRes = await api.post('/api/audio/slice', { source_path: ins.src, start: ins.start, end: ins.end });
                const arrayBuf = await (await fetch(sliceRes.data.url)).arrayBuffer();
                const audioCtx = new AudioContext();
                insBuf = await audioCtx.decodeAudioData(arrayBuf);
                audioCtx.close();
            } catch (e) { console.error("Slice fetch failed", e); }
        }

        if (!insBuf) {
            const gapFrames = Math.floor((ins.gap || 1) * sampleRate);
            const ctx = new OfflineAudioContext(channels, gapFrames, sampleRate);
            insBuf = ctx.createBuffer(channels, gapFrames, sampleRate);
        }

        // Splice `insBuf` into `currentBuf` at `ins.insertAt`
        const splitFrame = Math.floor(ins.insertAt * sampleRate);
        const safeSplit = Math.max(0, Math.min(splitFrame, currentBuf.length));

        const newTotal = currentBuf.length + insBuf.length;
        const newCtx = new OfflineAudioContext(channels, newTotal, sampleRate);
        const newBuf = newCtx.createBuffer(channels, newTotal, sampleRate);

        for (let c = 0; c < channels; c++) {
            const cData = currentBuf.getChannelData(c);
            const iData = insBuf.getChannelData(c);
            const nData = newBuf.getChannelData(c);

            nData.set(cData.subarray(0, safeSplit), 0);
            nData.set(iData, safeSplit);
            if (safeSplit < currentBuf.length) {
                nData.set(cData.subarray(safeSplit), safeSplit + iData.length);
            }
        }
        currentBuf = newBuf;
    }

    return currentBuf;
};

// --- Helper: Buffer to Blob ---
const bufferToWave = (abuffer, len) => {
    let numOfChan = abuffer.numberOfChannels,
        length = len * numOfChan * 2 + 44,
        buffer = new ArrayBuffer(length),
        view = new DataView(buffer),
        channels = [], i, sample,
        offset = 0,
        pos = 0;

    // write WAVE header
    setUint32(0x46464952);                         // "RIFF"
    setUint32(length - 8);                         // file length - 8
    setUint32(0x45564157);                         // "WAVE"

    setUint32(0x20746d66);                         // "fmt " chunk
    setUint32(16);                                 // length = 16
    setUint16(1);                                  // PCM (uncompressed)
    setUint16(numOfChan);
    setUint32(abuffer.sampleRate);
    setUint32(abuffer.sampleRate * 2 * numOfChan); // avg. bytes/sec
    setUint16(numOfChan * 2);                      // block-align
    setUint16(16);                                 // 16-bit (hardcoded in this parser)

    setUint32(0x61746164);                         // "data" - chunk
    setUint32(length - pos - 4);                   // chunk length

    // write interleaved data
    for (i = 0; i < abuffer.numberOfChannels; i++)
        channels.push(abuffer.getChannelData(i));

    while (pos < len) {
        for (i = 0; i < numOfChan; i++) {             // interleave channels
            sample = Math.max(-1, Math.min(1, channels[i][pos])); // clamp
            sample = (0.5 + sample < 0 ? sample * 32768 : sample * 32767) | 0; // scale to 16-bit signed int
            view.setInt16(44 + offset, sample, true); // write 16-bit sample
            offset += 2;
        }
        pos++;
    }

    return new Blob([buffer], { type: "audio/wav" });

    function setUint16(data) { view.setUint16(pos, data, true); pos += 2; }
    function setUint32(data) { view.setUint32(pos, data, true); pos += 4; }
};


const HOT_CUE_COLORS = [
    '#2ecc71', '#e67e22', '#f1c40f', '#3498db',
    '#fd79a8', '#00d2d3', '#a29bfe', '#ff7675',
];

const WaveformEditor = forwardRef(({ track, blobUrl = null, simpleMode = false, isPlayingExternal = null, onPlayPause = null, volume = 1 }, ref) => {
    const toast = useToast();
    const waveformRef = useRef(null);
    const overviewRef = useRef(null);
    const wavesurfer = useRef(null);
    const overviewWs = useRef(null);
    const isMountedRef = useRef(true);
    const originalBufferRef = useRef(null); // Cache original audio for non-destructive preview
    const onPlayPauseRef = useRef(onPlayPause); // Ref to avoid stale closure in wavesurfer event handlers
    const isPlayingExternalRef = useRef(isPlayingExternal);
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

        if (waveformRef.current) {
            observer.observe(waveformRef.current);
        } else if (overviewRef.current) {
            observer.observe(overviewRef.current);
        }

        return () => observer.disconnect();
    }, []);

    useEffect(() => {
        isMountedRef.current = true;
        return () => { isMountedRef.current = false; };
    }, []);

    // Volume Control
    useEffect(() => {
        if (wavesurfer.current) {
            wavesurfer.current.setVolume(volume);
        }
    }, [volume]);

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

    // Refs for multi-band layers
    const waveLowRef = useRef(null);
    const waveMidRef = useRef(null);
    const waveHighRef = useRef(null);
    const wsLow = useRef(null);
    const wsMid = useRef(null);
    const wsHigh = useRef(null);

    // Track Blob-URLs for cleanup (memory leak prevention)
    const blobUrlsRef = useRef([]);
    const trackBlobUrl = useCallback((url) => {
        blobUrlsRef.current.push(url);
        return url;
    }, []);
    const revokeAllBlobUrls = useCallback(() => {
        blobUrlsRef.current.forEach(u => { try { URL.revokeObjectURL(u); } catch (e) { } });
        blobUrlsRef.current = [];
    }, []);

    // Revoke all blob URLs on unmount
    useEffect(() => () => revokeAllBlobUrls(), [revokeAllBlobUrls]);

    // Fetch Global Settings on mount
    useEffect(() => {
        const fetchSettings = async () => {
            try {
                const res = await api.get('/api/settings');
                if (res.data.waveform_visual_mode) {
                    setVisualMode(res.data.waveform_visual_mode);
                }
            } catch (e) { console.warn("Failed to load waveform settings", e); }
        };
        fetchSettings();
    }, []);

    // Analyze Audio when needed
    useEffect(() => {
        const analyze = async () => {
            if ((visualMode === 'rgb' || visualMode === '3band') && !multibandBuffers && originalBufferRef.current && !analyzing) {
                setAnalyzing(true);
                try {
                    const bands = await AudioBandAnalyzer.splitBands(originalBufferRef.current);
                    // Convert to Blobs immediately to allow standard loading
                    const lowBlob = AudioBandAnalyzer.bufferToWav(bands.low);
                    const midBlob = AudioBandAnalyzer.bufferToWav(bands.mid);
                    const highBlob = AudioBandAnalyzer.bufferToWav(bands.high);

                    setMultibandBuffers({ low: lowBlob, mid: midBlob, high: highBlob });
                } catch (e) {
                    console.error("Analysis Failed", e);
                    toast.error("Waveform Analysis Failed");
                } finally {
                    setAnalyzing(false);
                }
            }
        };
        analyze();
    }, [visualMode, multibandBuffers, bufferReady]);

    // Manage Multi-Band Instances
    useEffect(() => {
        if (!wavesurfer.current) return;

        const cleanupSlaves = () => {
            // Revoke object URLs to avoid memory leaks?
            // Not strictly necessary as refs are destroyed, but good practice.
            wsLow.current?.destroy(); wsLow.current = null;
            wsMid.current?.destroy(); wsMid.current = null;
            wsHigh.current?.destroy(); wsHigh.current = null;
        };

        const initLayers = async () => {
            // If Blue Mode, cleanup slaves and restore Main
            if (visualMode === 'blue') {
                cleanupSlaves();
                wavesurfer.current.setOptions({
                    waveColor: 'rgba(59, 130, 246, 0.8)',
                    progressColor: 'rgba(59, 130, 246, 0.8)',
                    cursorColor: 'rgba(255, 255, 255, 0.5)'
                });
                return;
            }

            if (!multibandBuffers || !waveLowRef.current || !waveMidRef.current || !waveHighRef.current) return;

            // Always cleanup old slaves when switching modes (colors differ)
            cleanupSlaves();

            // Colors — match Rekordbox exactly
            const isRGB = visualMode === 'rgb';
            // RGB: Balanced rich colors — screen blending brightens them, so we start with strong saturation
            // but not full 255 neon.
            // 3Band: Blue (Low) + Amber (Mid) + White (High) — classic Rekordbox
            const colLow = isRGB ? 'rgba(210, 0, 0, 1.0)' : 'rgba(0, 100, 255, 1.0)';
            const colMid = isRGB ? 'rgba(0, 190, 0, 1.0)' : 'rgba(255, 160, 0, 1.0)';
            const colHigh = isRGB ? 'rgba(0, 80, 255, 1.0)' : 'rgba(255, 255, 255, 1.0)';

            // Hide Main Waveform (keep interaction)
            wavesurfer.current.setOptions({
                waveColor: 'transparent',
                progressColor: 'transparent',
                cursorColor: 'rgba(255, 255, 255, 0.5)',
            });

            const WaveSurfer = (await import('wavesurfer.js')).default;

            const options = {
                height: 128,
                cursorColor: 'transparent',
                interact: false,
                hideScrollbar: true,
                minPxPerSec: zoom,
                autoScroll: false,
                autoCenter: false,
                fillParent: false,
                barWidth: undefined,
            };

            // Create fresh instances with correct colors
            wsLow.current = WaveSurfer.create({ ...options, container: waveLowRef.current, waveColor: colLow, progressColor: colLow });
            wsMid.current = WaveSurfer.create({ ...options, container: waveMidRef.current, waveColor: colMid, progressColor: colMid });
            wsHigh.current = WaveSurfer.create({ ...options, container: waveHighRef.current, waveColor: colHigh, progressColor: colHigh });

            // Load Blobs
            const loadBlob = (ws, blob) => {
                // Apply Zoom/Time once ready
                ws.once('ready', () => {
                    if (ws && !ws.isDestroyed) {
                        ws.zoom(zoom);
                        ws.setTime(wavesurfer.current.getCurrentTime());
                    }
                });
                const url = trackBlobUrl(URL.createObjectURL(blob));
                ws.load(url);
            };

            if (wsLow.current) loadBlob(wsLow.current, multibandBuffers.low);
            if (wsMid.current) loadBlob(wsMid.current, multibandBuffers.mid);
            if (wsHigh.current) loadBlob(wsHigh.current, multibandBuffers.high);

            // Initial Sync (Might be too early, but good backup)
            const t = wavesurfer.current.getCurrentTime();
            [wsLow, wsMid, wsHigh].forEach(ws => {
                if (ws.current) {
                    // ws.current.setTime(t); // Removed here, moved to ready
                    // ws.current.zoom(zoom);
                }
            });
        };

        initLayers();

        // ---------------------------------------------------------
        // FORCE SYNC LOOP (RAF) — only runs when needed
        // ---------------------------------------------------------
        // Only run sync loop when in multi-band mode AND playing (saves CPU)
        if (visualMode === 'blue') return;

        let rafId;
        let lastSyncTime = -1;
        let lastSyncScroll = -1;

        const loop = () => {
            if (wavesurfer.current && !wavesurfer.current.isDestroyed) {
                const master = wavesurfer.current;
                const wrapper = master.getWrapper();
                const scrollEl = wrapper?.parentElement;

                if (scrollEl && master.getDuration() > 0) {
                    const time = master.getCurrentTime();
                    const dur = master.getDuration();
                    const totalWidth = scrollEl.scrollWidth;
                    const containerWidth = scrollEl.clientWidth;

                    // Smooth centering only during playback (saves DOM writes when paused)
                    if (master.isPlaying()) {
                        const cursorPx = (time / dur) * totalWidth;
                        const targetScroll = cursorPx - containerWidth / 2;
                        scrollEl.scrollLeft = Math.max(0, Math.min(targetScroll, totalWidth - containerWidth));
                    }

                    const scroll = scrollEl.scrollLeft;

                    // Skip update if nothing changed (cheap noop check)
                    const timeChanged = Math.abs(time - lastSyncTime) > 0.01;
                    const scrollChanged = scroll !== lastSyncScroll;
                    if (timeChanged || scrollChanged) {
                        lastSyncTime = time;
                        lastSyncScroll = scroll;

                        // Sync Slaves
                        [wsLow, wsMid, wsHigh].forEach(ws => {
                            if (ws.current && !ws.current.isDestroyed) {
                                if (Math.abs(ws.current.getCurrentTime() - time) > 0.05) {
                                    ws.current.setTime(time);
                                }
                                const childWrapper = ws.current.getWrapper();
                                const childScroll = childWrapper?.parentElement;
                                if (childScroll && childScroll.scrollLeft !== scroll) {
                                    childScroll.scrollLeft = scroll;
                                }
                            }
                        });
                    }
                }
            }
            rafId = requestAnimationFrame(loop);
        };
        loop();

        return () => {
            if (rafId) cancelAnimationFrame(rafId);
        };
    }, [visualMode, multibandBuffers, zoom]); // re-run on zoom to recalc widths

    // Sync zoom to slaves when state changes
    useEffect(() => {
        [wsLow, wsMid, wsHigh].forEach(ws => {
            if (ws.current && !ws.current.isDestroyed) {
                ws.current.zoom(zoom);
            }
        });
    }, [zoom]);

    const handleToggleVisualMode = async () => {
        const modes = ['blue', 'rgb', '3band'];
        const next = modes[(modes.indexOf(visualMode) + 1) % modes.length];
        setVisualMode(next);

        // Save Global Setting
        try {
            // We need to fetch current settings first to not overwrite others?
            // Or just partial update? My backend expects full object usually.
            // But api/settings/save endpoint implementation in main.py takes SetReq.
            // I should modify SettingsView to expose a helper or just do a quick fetch-modify-save.
            const curr = await api.get('/api/settings');
            await api.post('/api/settings', { ...curr.data, waveform_visual_mode: next });
            toast.success(`Mode saved: ${next.toUpperCase()}`);
        } catch (e) { console.warn("Failed to save mode", e); }
    };
    const [cuts, setCuts] = useState([]);
    const [history, setHistory] = useState([]);
    const [historyIdx, setHistoryIdx] = useState(-1);
    const [projectList, setProjectList] = useState([]);
    const [selectedProject, setSelectedProject] = useState("");
    const [isRendering, setIsRendering] = useState(false);
    const [renderProgress, setRenderProgress] = useState(0);
    const [showBrowser, setShowBrowser] = useState(false);
    // Confirm-modal state (replaces native window.confirm)
    const [confirmModal, setConfirmModal] = useState(null); // { title, message, onConfirm, confirmLabel }
    const showConfirm = useCallback((opts) => setConfirmModal(opts), []);

    // Auto-open browser if no track is loaded
    useEffect(() => {
        if (!fullTrack && !loading && !track) {
            setShowBrowser(true);
        }
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

    useEffect(() => {
        api.get('/api/projects').then(res => setProjectList(res.data));
    }, []);

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
                // Construct path (simple concatenation, handles most cases)
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

    // Hotkeys
    const skip = (amount) => {
        if (wavesurfer.current) {
            const time = wavesurfer.current.getCurrentTime();
            wavesurfer.current.setTime(Math.min(duration, Math.max(0, time + amount)));
        }
    };

    useHotkeys('left', (e) => { e.preventDefault(); skip(-10); }, [duration]);
    useHotkeys('right', (e) => { e.preventDefault(); skip(10); }, [duration]);
    useHotkeys('space', (e) => {
        if (simpleMode) return; // Ranking mode uses space for 'Next', so we ignore it here
        e.preventDefault();
        if (wavesurfer.current) wavesurfer.current.playPause();
    }, [simpleMode]);

    const beats = React.useMemo(() => {
        if (!duration || !bpm) return [];
        const result = [];
        const beatDuration = 60 / bpm;

        // Use real grid if available
        if (beatGrid && beatGrid.length > 0) {
            const sortedGrid = [...beatGrid].sort((a, b) => a.time - b.time);
            let absoluteBeat = 0;
            for (let i = 0; i < sortedGrid.length; i++) {
                const current = sortedGrid[i];
                const segmentEnd = sortedGrid[i + 1] ? sortedGrid[i + 1].time : duration;
                const segBpm = current.bpm || bpm;
                const segBeatDur = 60 / segBpm;
                let t = current.time;
                while (t < segmentEnd - 0.005) {
                    result.push({
                        time: t,
                        barNum: Math.floor(absoluteBeat / 4) + 1,
                        isDownbeat: absoluteBeat % 4 === 0
                    });
                    t += segBeatDur;
                    absoluteBeat++;
                }
            }
        } else {
            let t = 0;
            let beatCount = 0;
            while (t < duration) {
                result.push({
                    time: t,
                    barNum: Math.floor(beatCount / 4) + 1,
                    isDownbeat: beatCount % 4 === 0
                });
                t += 60 / bpm;
                beatCount++;
            }
        }
        return result;
    }, [beatGrid, bpm, duration]);

    useEffect(() => { beatsRef.current = beats; }, [beats]);

    const isStreaming = (t) => {
        const path = t?.path || t?.Path || '';
        return path.startsWith('soundcloud:') || path.startsWith('spotify:') || path.startsWith('tidal:') || path.startsWith('beatport:');
    };

    const streaming = isStreaming(fullTrack);

    // --- 1. Initialization Effect (Run Once or on strict teardown) ---
    useEffect(() => {
        const initWaveSurfer = async () => {
            const WaveSurfer = (await import('wavesurfer.js')).default;
            const RegionsPlugin = (await import('wavesurfer.js/dist/plugins/regions.esm.js')).default;
            const TimelinePlugin = (await import('wavesurfer.js/dist/plugins/timeline.esm.js')).default;

            if (!isMountedRef.current || wavesurfer.current) return; // Prevent double init
            if (streaming) return; // Don't init WS for streaming tracks

            // 1. Overview Waveform
            overviewWs.current = WaveSurfer.create({
                container: overviewRef.current,
                waveColor: '#444',
                progressColor: '#ff9800',
                height: 48,
                interact: true,
                cursorWidth: 1,
                cursorColor: '#fff',
                plugins: [TimelinePlugin.create({ container: overviewRef.current, height: 10, fontSize: 8 })]
            });

            // 2. Detailed Waveform
            wavesurfer.current = WaveSurfer.create({
                container: waveformRef.current,
                waveColor: 'rgba(59, 130, 246, 0.8)',
                progressColor: 'rgba(59, 130, 246, 0.8)',
                cursorColor: '#00ccff',
                cursorWidth: 2,
                height: simpleMode ? 180 : 280,
                minPxPerSec: zoom,
                autoScroll: false,
                autoCenter: false,
                fillParent: false,
                hideScrollbar: true,
                normalize: true,
                backend: 'WebAudio'
            });

            // Initialize Plugins
            const regions = wavesurfer.current.registerPlugin(RegionsPlugin.create());
            const overviewRegions = overviewWs.current.registerPlugin(RegionsPlugin.create());

            // --- Event Listeners ---
            wavesurfer.current.on('ready', () => {
                if (!isMountedRef.current) return;
                setDuration(wavesurfer.current.getDuration());
                setLoading(false);
                // Check if we should auto-play (use ref to get current value, not stale closure)
                if (isPlayingExternalRef.current) {
                    wavesurfer.current.play().catch(e => console.warn("Autoplay blocked:", e));
                }
                // Capture Original Buffer + reset multiband state for new track
                const buffer = wavesurfer.current.getDecodedData();
                if (buffer) {
                    originalBufferRef.current = buffer;
                    setMultibandBuffers(null);
                    setBufferReady(true);
                }
            });

            wavesurfer.current.on('audioprocess', () => {
                if (!isMountedRef.current) return;
                const time = wavesurfer.current.getCurrentTime();
                setCurrentTime(time);
                if (overviewWs.current && overviewWs.current.getDuration() > 0) {
                    // Sync Overview
                    const dur = wavesurfer.current.getDuration();
                    if (dur > 0) overviewWs.current.seekTo(time / dur);
                }

                // LOOP PLAYBACK LOGIC
                if (isLoopingRef.current && loopInRef.current !== null && loopOutRef.current !== null) {
                    if (time >= loopOutRef.current) {
                        wavesurfer.current.setTime(loopInRef.current);
                    }
                }
            });

            wavesurfer.current.on('zoom', (px) => {
                if (!isMountedRef.current) return;
                setZoom(px);
            });

            wavesurfer.current.on('interaction', () => {
                let time = wavesurfer.current.getCurrentTime();

                // Snap to Grid
                if (isQuantizedRef.current && beatsRef.current.length > 0) {
                    const b = beatsRef.current;
                    const nearest = b.reduce((prev, curr) =>
                        Math.abs(curr.time - time) < Math.abs(prev.time - time) ? curr : prev
                    );
                    // Only snap if within 0.2s to avoid jumping too far? 
                    // Or hard snap? User asked for snap. Hard snap is better for "Beat Grids".
                    time = nearest.time;
                    wavesurfer.current.setTime(time);
                }

                setCurrentTime(time);
                setSelectionStart(time);
            });

            wavesurfer.current.on('error', (e) => {
                console.error("WaveSurfer Error:", e);
                toast.error("Audio Error: " + (e.message || e));
            });

            // Notify parent of play/pause/finish state changes (needed by RankingView)
            wavesurfer.current.on('play', () => {
                if (!isMountedRef.current) return;
                setInternalPlaying(true);
                onPlayPauseRef.current?.(true);
            });
            wavesurfer.current.on('pause', () => {
                if (!isMountedRef.current) return;
                setInternalPlaying(false);
                onPlayPauseRef.current?.(false);
            });
            wavesurfer.current.on('finish', () => {
                if (!isMountedRef.current) return;
                setInternalPlaying(false);
                onPlayPauseRef.current?.(false);
            });

            // Sync Overview Clicks
            overviewWs.current.on('click', (rel) => {
                if (wavesurfer.current) wavesurfer.current.seekTo(rel);
            });

            // Trigger initial load if track is already present (optimization for race conditions)
            if (fullTrack?.path || blobUrl) {
                const loadUrl = blobUrl || `/api/stream?path=${encodeURIComponent(fullTrack.path)}`;
                wavesurfer.current.load(loadUrl);
                overviewWs.current.load(loadUrl);
            }
        };

        initWaveSurfer();

        // Cleanup on Unmount
        return () => {
            try {
                if (wavesurfer.current) {
                    wavesurfer.current.un('audioprocess');
                    wavesurfer.current.un('interaction');
                    wavesurfer.current.stop();
                    wavesurfer.current.destroy();
                }
                if (overviewWs.current) overviewWs.current.destroy();
            } catch (e) { console.warn("WaveSurfer cleanup error", e); }
            wavesurfer.current = null;
            overviewWs.current = null;
        };
    }, []); // Run once on mount

    // --- 2. Track Loading Effect (Runs when track changes) ---
    useEffect(() => {
        if (!wavesurfer.current || !overviewWs.current) return;
        if (!fullTrack?.path && !blobUrl) return;
        if (!isVisible) return;
        if (streaming) {
            setLoading(false);
            setBufferReady(false);
            return;
        }

        const url = blobUrl || `/api/stream?path=${encodeURIComponent(fullTrack.path)}`;

        // Don't reload if it's the same URL? 
        // Actually, user might want to reload if they edited it. 
        // But for now, let's just load.

        setLoading(true);
        setBufferReady(false); // Reset buffer state
        setMultibandBuffers(null); // Reset analysis
        // Clear Regions/Cues from previous track
        const regions = wavesurfer.current.plugins.find(p => p.getRegions);
        if (regions) regions.clearRegions();

        wavesurfer.current.load(url);
        overviewWs.current.load(url);

        // Reset State
        setLoopIn(null);
        setLoopOut(null);
        setIsLooping(false);
        setCuts([]);
        setHotCues([]);
        setBeatGrid([]); // Will re-fetch

    }, [fullTrack?.path, blobUrl, streaming]); // Added streaming dependency

    const beatCanvasRef = useRef(null);

    // 1. Grid Rendering Effect — Canvas-based (1 element vs 1000+ regions)
    useEffect(() => {
        if (!wavesurfer.current || !duration || !beats?.length || !beatCanvasRef.current) return;

        const canvas = beatCanvasRef.current;
        const wrapper = wavesurfer.current.getWrapper();
        const scrollEl = wrapper?.parentElement;
        if (!scrollEl) return;

        let rafPending = false;

        const drawGrid = () => {
            rafPending = false;
            const ctx = canvas.getContext('2d');
            const dpr = window.devicePixelRatio || 1;
            const w = scrollEl.clientWidth;
            const h = scrollEl.clientHeight;
            if (!w || !h) return;

            canvas.width = w * dpr;
            canvas.height = h * dpr;
            canvas.style.width = `${w}px`;
            canvas.style.height = `${h}px`;
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
            ctx.clearRect(0, 0, w, h);

            const pxPerSec = scrollEl.scrollWidth / duration;
            const scrollLeft = scrollEl.scrollLeft;
            const startTime = scrollLeft / pxPerSec - 0.5;
            const endTime = (scrollLeft + w) / pxPerSec + 0.5;

            // Adaptive density: skip non-downbeats at low zoom
            const pxPerBeat = pxPerSec * (60 / bpm);
            const showAllBeats = pxPerBeat >= 12;

            for (let i = 0; i < beats.length; i++) {
                const b = beats[i];
                if (b.time < startTime || b.time > endTime) continue;
                if (!showAllBeats && !b.isDownbeat) continue;

                const x = Math.round(b.time * pxPerSec - scrollLeft) + 0.5;

                if (b.isDownbeat) {
                    // Vertical line
                    ctx.strokeStyle = 'rgba(255, 255, 255, 0.22)';
                    ctx.lineWidth = 1;
                    ctx.beginPath();
                    ctx.moveTo(x, 0);
                    ctx.lineTo(x, h);
                    ctx.stroke();

                    // Top triangle
                    ctx.fillStyle = 'rgba(255, 60, 60, 0.95)';
                    ctx.beginPath();
                    ctx.moveTo(x - 4, 0);
                    ctx.lineTo(x + 4, 0);
                    ctx.lineTo(x, 5);
                    ctx.closePath();
                    ctx.fill();

                    // Bottom triangle
                    ctx.beginPath();
                    ctx.moveTo(x - 4, h);
                    ctx.lineTo(x + 4, h);
                    ctx.lineTo(x, h - 5);
                    ctx.closePath();
                    ctx.fill();

                    // Bar number
                    ctx.fillStyle = 'rgba(255, 255, 255, 0.55)';
                    ctx.font = 'bold 10px ui-monospace, Menlo, monospace';
                    ctx.fillText(String(b.barNum), x + 4, 12);
                } else {
                    ctx.strokeStyle = 'rgba(255, 255, 255, 0.06)';
                    ctx.lineWidth = 1;
                    ctx.beginPath();
                    ctx.moveTo(x, 0);
                    ctx.lineTo(x, h);
                    ctx.stroke();
                }
            }
        };

        const scheduleDraw = () => {
            if (rafPending) return;
            rafPending = true;
            requestAnimationFrame(drawGrid);
        };

        drawGrid();
        // Schedule extra redraws after WaveSurfer applies zoom (async DOM update)
        const t1 = setTimeout(scheduleDraw, 50);
        const t2 = setTimeout(scheduleDraw, 200);

        scrollEl.addEventListener('scroll', scheduleDraw, { passive: true });
        const ro = new ResizeObserver(scheduleDraw);
        ro.observe(scrollEl);

        // Listen to WaveSurfer zoom event for accurate redraw timing
        const zoomHandler = () => scheduleDraw();
        wavesurfer.current.on('zoom', zoomHandler);

        return () => {
            clearTimeout(t1);
            clearTimeout(t2);
            scrollEl.removeEventListener('scroll', scheduleDraw);
            ro.disconnect();
            try { wavesurfer.current?.un('zoom', zoomHandler); } catch (e) { }
        };
    }, [beats, zoom, duration, bpm]);

    // 2. Interactive Overlay Effect (Cues, Selection, Cuts)
    useEffect(() => {
        if (!wavesurfer.current || !duration) return;
        let regions = wavesurfer.current.plugins.find(p => p.addRegion);
        let ovRegions = overviewWs.current?.plugins.find(p => p.addRegion);
        if (!regions) return;

        // Clear existing interactive regions
        regions.getRegions().forEach(r => {
            if (r.id === 'selection-range' || r.id.startsWith('cut-') || r.id.startsWith('insert-') || r.id.startsWith('delete-') || r.id === 'drop-marker' || r.id === 'active-loop' || r.id.startsWith('cue-')) {
                r.remove();
            }
        });

        if (ovRegions) {
            ovRegions.getRegions().forEach(r => {
                if (r.id.startsWith('cue-ov-') || r.id === 'drop-marker-ov') r.remove();
            });
        }

        // 2. Render Selection Range (Beat Select)
        if (!simpleMode) {
            const beatDuration = 60 / bpm;
            let start = selectionStart;

            // Apply Quantize if enabled
            if (isQuantized && beats.length > 0) {
                const nearestBeat = beats.reduce((prev, curr) =>
                    Math.abs(curr.time - start) < Math.abs(prev.time - start) ? curr : prev
                );
                start = nearestBeat.time;
            }

            const selectionEnd = Math.min(start + (beatDuration * selectedBeats), duration);

            regions.addRegion({
                id: 'selection-range',
                start: start,
                end: selectionEnd,
                color: 'rgba(0, 204, 255, 0.4)',
                drag: true,
                resize: true,
                attributes: { label: 'selection' }
            });
        }

        // 3. Render Cuts
        cuts.forEach(cut => {
            let color = 'rgba(255, 152, 0, 0.3)'; // Default Clone
            let label = 'CLONE';
            if (cut.type === 'delete') {
                color = 'rgba(239, 68, 68, 0.4)'; // Red
                label = 'DELETE';
            }
            if (cut.type === 'insert') {
                color = 'rgba(34, 197, 94, 0.4)'; // Green
                label = 'INSERT';
            }

            regions.addRegion({
                id: cut.id,
                start: cut.start,
                end: cut.end,
                color: color,
                drag: true,
                resize: true,
                attributes: { label }
            });
        });

        // 4. Render Drop Marker
        if (dropTime) {
            regions.addRegion({
                id: 'drop-marker',
                start: dropTime,
                end: dropTime + 0.1,
                color: 'rgba(255, 0, 0, 0.6)',
                drag: false,
                resize: false,
                attributes: { label: 'DROP' }
            });

            if (ovRegions) {
                ovRegions.addRegion({
                    id: 'drop-marker-ov',
                    start: dropTime,
                    end: dropTime + 0.2,
                    color: 'rgba(255, 0, 0, 0.8)',
                    drag: false,
                    resize: false
                });
            }
        }

        // 5. Render Hot Cues
        hotCues.forEach(cue => {
            const color = HOT_CUE_COLORS[cue.HotCueNum - 1] || 'rgba(255, 255, 0, 0.8)';
            regions.addRegion({
                id: cue.ID.startsWith('cue-') ? cue.ID : `cue-${cue.ID}`,
                start: cue.InPoint,
                end: cue.InPoint + 0.1,
                color: color,
                drag: true,
                resize: false,
                attributes: { label: `CUE ${String.fromCharCode(64 + cue.HotCueNum)}` }
            });

            if (ovRegions) {
                ovRegions.addRegion({
                    id: `cue-ov-${cue.ID}`,
                    start: cue.InPoint,
                    end: cue.InPoint + 0.5,
                    color: color,
                    drag: false,
                    resize: false
                });
            }
        });

        // 6. Render Active Loop
        if (loopIn !== null && loopOut !== null) {
            regions.addRegion({
                id: 'active-loop',
                start: loopIn,
                end: loopOut,
                color: 'rgba(255, 255, 0, 0.2)',
                drag: true,
                resize: true,
                attributes: { label: 'LOOP' }
            });
        }

    }, [selectionStart, selectedBeats, bpm, cuts, isQuantized, dropTime, hotCues, loopIn, loopOut, duration]);

    useEffect(() => {
        if (!wavesurfer.current || isPlaying === undefined) return;
        if (isPlaying && !wavesurfer.current.isPlaying()) {
            wavesurfer.current.play();
        } else if (!isPlaying && wavesurfer.current.isPlaying()) {
            wavesurfer.current.pause();
        }
    }, [isPlaying]);

    useEffect(() => {
        if (wavesurfer.current) wavesurfer.current.zoom(zoom);
    }, [zoom]);

    const formatTime = (s) => {
        const m = Math.floor(s / 60);
        const sec = Math.floor(s % 60);
        const ms = Math.floor((s % 1) * 100);
        return `${m}:${sec.toString().padStart(2, '0')}.${ms.toString().padStart(2, '0')}`;
    };

    const handleSetHotCue = (num) => {
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
    };

    const handleJumpHotCue = useCallback((num) => {
        const cue = hotCues.find(c => c.HotCueNum === num);
        if (cue && wavesurfer.current) {
            wavesurfer.current.setTime(cue.InPoint);
            setCurrentTime(cue.InPoint);
        }
    }, [hotCues]);

    const handleDeleteHotCue = useCallback((num) => {
        setHotCues(prev => prev.filter(c => c.HotCueNum !== num));
    }, []);

    const handleSetLoopIn = () => setLoopIn(wavesurfer.current.getCurrentTime());
    const handleSetLoopOut = () => {
        const time = wavesurfer.current.getCurrentTime();
        if (loopIn !== null && time > loopIn) {
            setLoopOut(time);
            setIsLooping(true);
        }
    };

    const handleSaveCues = async () => {
        if (!track) return;
        try {
            await api.post('/api/track/cues/save', { track_id: track.id, cues: hotCues });
            toast.success("Cues saved successfully!");
        } catch (err) { toast.error("Failed to save cues."); }
    };

    const handleGridShift = (delta) => {
        if (!beatGrid || beatGrid.length === 0) return;
        const newGrid = beatGrid.map(b => ({ ...b, time: b.time + delta }));
        setBeatGrid(newGrid);
        if (dropTime) setDropTime(prev => prev + delta);
        toast.info(`Grid shifted ${delta > 0 ? '+' : ''}${(delta * 1000).toFixed(0)}ms`);
    };

    const handleSaveGrid = async () => {
        if (!track) return;
        try {
            await api.post('/api/track/grid/save', { track_id: track.id, beat_grid: beatGrid });
            toast.success("Beat Grid saved!");
        } catch (err) { toast.error("Failed to save grid."); }
    };

    const handleDetectDrop = async () => {
        if (!fullTrack?.path) return;
        toast.info("Analyzing audio for drop...");
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
            toast.error("Drop detection failed.");
        }
    };

    const handleRender = async (inputCuts, customName = null) => {
        if (!fullTrack?.path || !duration) {
            toast.error("No track loaded or duration unknown.");
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
            toast.error("No valid segments to export.");
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
            console.log("Render Payload:", payload);
            setRenderProgress(30);
            const res = await api.post('/api/audio/render', payload);
            setRenderProgress(100);
            setTimeout(() => {
                setIsRendering(false);
                setRenderProgress(0);
                toast.success("Render Complete! File saved to exports folder.");
                if (res.data.track_id) {
                    toast.info("New track added to library.");
                }
            }, 500);
        } catch (err) {
            console.error("Render failed", err);
            toast.error("Render Failed: " + (err.response?.data?.detail || err.message));
            setIsRendering(false);
        }
    };

    const handleClone = () => {
        // Find selection region
        const regions = wavesurfer.current.plugins.find(p => p.getRegions);
        const selection = regions.getRegions().find(r => r.id === 'selection-range');
        if (!selection) return;

        const newCut = { start: selection.start, end: selection.end, id: `cut-${Date.now()}` };
        setCuts(prev => [...prev, newCut]);

        // Add to history
        const newHistory = [...history.slice(0, historyIdx + 1), { type: 'add_cut', data: newCut }];
        setHistory(newHistory);
        setHistoryIdx(newHistory.length - 1);
    };

    const handleCopy = () => {
        if (!wavesurfer.current) {
            toast.error("Waveform not loaded.");
            return;
        }
        const regions = wavesurfer.current.plugins?.find(p => p.getRegions);
        if (!regions) {
            toast.error("Regions plugin not available.");
            return;
        }
        const selection = regions.getRegions()?.find(r => r.id === 'selection-range');
        if (!selection) {
            toast.error("No selection. Click on waveform to create a selection first.");
            return;
        }
        if (!fullTrack?.path) {
            toast.error("No track path available.");
            return;
        }
        setClipboard({
            duration: selection.end - selection.start,
            start: selection.start,
            end: selection.end,
            source_path: fullTrack.path
        });
        toast.success(`Copied ${(selection.end - selection.start).toFixed(2)}s section!`);
    };

    const handlePaste = () => {
        if (!clipboard) {
            toast.error("Clipboard empty. Use COPY first.");
            return;
        }
        const pSize = clipboard.duration;
        const pAt = currentTime;

        if (!clipboard.start && clipboard.start !== 0) {
            toast.error("No audio segment in clipboard.");
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

        // Use functional setState to avoid stale closure
        setCuts(prev => [...prev, newCut]);
        const newHistory = [...history.slice(0, historyIdx + 1), { type: 'add_cut', data: newCut }];
        setHistory(newHistory);
        setHistoryIdx(newHistory.length - 1);
        toast.success(`Segment pasted at ${pAt.toFixed(2)}s.`);
        // Preview rebuild handled by debounced effect
    };

    const handleInsert = () => {
        const regions = wavesurfer.current?.plugins?.find(p => p.getRegions);
        const selection = regions?.getRegions()?.find(r => r.id === 'selection-range');
        if (!selection) {
            toast.error("No selection. Click and drag on waveform to select a region.");
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
        const newHistory = [...history.slice(0, historyIdx + 1), { type: 'add_cut', data: newCut }];
        setHistory(newHistory);
        setHistoryIdx(newHistory.length - 1);
        toast.info("Insert region marked.");
        // Preview handled by debounced effect
    };

    const handleDelete = () => {
        const regions = wavesurfer.current?.plugins?.find(p => p.getRegions);
        const selection = regions?.getRegions()?.find(r => r.id === 'selection-range');
        if (!selection) {
            toast.error("No selection. Click and drag on waveform to select a region.");
            return;
        }

        const newCut = {
            start: selection.start,
            end: selection.end,
            id: `delete-${Date.now()}`,
            type: 'delete'
        };

        setCuts(prev => [...prev, newCut]);
        const newHistory = [...history.slice(0, historyIdx + 1), { type: 'add_cut', data: newCut }];
        setHistory(newHistory);
        setHistoryIdx(newHistory.length - 1);
        toast.info("Section marked for deletion.");
        // Preview handled by debounced effect
    };

    const jumpToCue = (time) => {
        if (wavesurfer.current) {
            wavesurfer.current.setTime(time);
            setCurrentTime(time);
        }
    };

    const handleApplyAllEdits = async () => {
        if (!fullTrack?.path || !duration) return;

        const deleteCuts = cuts.filter(c => c.type === 'delete').sort((a, b) => a.start - b.start);
        if (deleteCuts.length === 0) {
            toast.error("No delete regions found. Mark some sections with DELETE first.");
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
    };

    const previewGenRef = useRef(0); // Track generation to ignore stale results
    const updateVisualPreview = useCallback(async (currentCuts) => {
        if (!wavesurfer.current) return;

        let sourceBuffer = originalBufferRef.current;
        if (!sourceBuffer) sourceBuffer = wavesurfer.current.getDecodedData();
        if (!sourceBuffer) return;

        // If no cuts, restore original (early return, no rebuild)
        if (!currentCuts || currentCuts.length === 0) {
            // Reset to original via reload
            const origUrl = blobUrl || (fullTrack?.path ? `/api/stream?path=${encodeURIComponent(fullTrack.path)}` : null);
            if (origUrl) {
                const time = wavesurfer.current.getCurrentTime();
                wavesurfer.current.load(origUrl);
                wavesurfer.current.once('ready', () => {
                    if (!isMountedRef.current) return;
                    wavesurfer.current.setTime(time);
                });
            }
            return;
        }

        toast.info("Updating Waveform...");
        const gen = ++previewGenRef.current;

        try {
            const newBuffer = await buildPreviewBuffer(sourceBuffer, currentCuts, duration, fullTrack?.path);

            // Stale check: a newer preview started while we were rebuilding
            if (gen !== previewGenRef.current || !isMountedRef.current) return;

            const newBlob = bufferToWave(newBuffer, newBuffer.length);
            const newUrl = trackBlobUrl(URL.createObjectURL(newBlob));

            const time = wavesurfer.current.getCurrentTime();
            wavesurfer.current.load(newUrl);
            // CRITICAL: 'once' instead of 'on' - 'on' stacks listeners on every preview update
            wavesurfer.current.once('ready', () => {
                if (!isMountedRef.current) return;
                wavesurfer.current.setTime(time);
            });

        } catch (e) {
            console.error("Preview Gen Failed", e);
            toast.error("Visual Preview Failed");
        }
    }, [blobUrl, fullTrack?.path, duration, toast, trackBlobUrl]);

    // Debounced preview rebuild — runs whenever cuts change (handleInsert/Delete/Paste/Clear/Undo)
    // 300ms debounce avoids rebuilding on every rapid edit
    useEffect(() => {
        if (!bufferReady) return;
        const t = setTimeout(() => updateVisualPreview(cuts), 300);
        return () => clearTimeout(t);
    }, [cuts, bufferReady, updateVisualPreview]);

    const handleClear = () => {
        if (cuts.length === 0) return;
        const newHistory = [...history.slice(0, historyIdx + 1), { type: 'clear_cuts', data: cuts }];
        setCuts([]);
        setHistory(newHistory);
        setHistoryIdx(newHistory.length - 1);
        // Preview rebuild via debounced effect
    };

    const handleUndo = () => {
        if (historyIdx < 0) return;
        const last = history[historyIdx];
        if (last.type === 'add_cut') setCuts(prev => prev.filter(c => c.id !== last.data.id));
        if (last.type === 'clear_cuts') setCuts(last.data);
        setHistoryIdx(prev => prev - 1);
        // Preview rebuild via debounced effect
    };

    const handleRedo = () => {
        if (historyIdx >= history.length - 1) return;
        const next = history[historyIdx + 1];
        if (next.type === 'add_cut') setCuts(prev => [...prev, next.data]);
        if (next.type === 'clear_cuts') setCuts([]);
        setHistoryIdx(prev => prev + 1);
    };

    // Edit hotkeys — only active in full mode (simpleMode is ranking, conflicts with shortcuts)
    const editHotkeyOpts = { enabled: !simpleMode, preventDefault: true, enableOnFormTags: false };
    useHotkeys('ctrl+c, meta+c', () => handleCopy(), editHotkeyOpts, [fullTrack?.path]);
    useHotkeys('ctrl+v, meta+v', () => handlePaste(), editHotkeyOpts, [clipboard, currentTime, history, historyIdx]);
    useHotkeys('i', () => handleInsert(), editHotkeyOpts, [currentTime, history, historyIdx]);
    useHotkeys('delete, backspace', () => handleDelete(), editHotkeyOpts, [history, historyIdx]);
    useHotkeys('ctrl+z, meta+z', () => handleUndo(), editHotkeyOpts, [history, historyIdx]);
    useHotkeys('ctrl+shift+z, meta+shift+z, ctrl+y, meta+y', () => handleRedo(), editHotkeyOpts, [history, historyIdx]);
    useHotkeys('ctrl+e, meta+e', () => handleRender(cuts), editHotkeyOpts, [cuts, fullTrack?.path, duration]);
    useHotkeys('ctrl+s, meta+s', () => handleSaveCues(), editHotkeyOpts, [hotCues, track]);
    // Zoom shortcuts
    useHotkeys('ctrl+plus, meta+plus, ctrl+equal, meta+equal', () => setZoom(p => Math.min(ZOOM_MAX, p + ZOOM_STEP)), editHotkeyOpts);
    useHotkeys('ctrl+minus, meta+minus', () => setZoom(p => Math.max(ZOOM_MIN, p - ZOOM_STEP)), editHotkeyOpts);
    // Loop in/out
    useHotkeys('l', () => loopIn === null ? handleSetLoopIn() : handleSetLoopOut(), editHotkeyOpts, [loopIn]);
    useHotkeys('shift+l', () => { setLoopIn(null); setLoopOut(null); setIsLooping(false); }, editHotkeyOpts);
    // Hot Cues: 1-8 jump, Shift+1-8 set
    useHotkeys('1,2,3,4,5,6,7,8', (e, h) => {
        const num = parseInt(h.keys?.[0] ?? e.key, 10);
        if (num >= 1 && num <= 8) handleJumpHotCue(num);
    }, editHotkeyOpts, [handleJumpHotCue]);
    useHotkeys('shift+1,shift+2,shift+3,shift+4,shift+5,shift+6,shift+7,shift+8', (e, h) => {
        const num = parseInt((h.keys?.[0] ?? e.key).replace('shift+', ''), 10);
        if (num >= 1 && num <= 8) handleSetHotCue(num);
    }, editHotkeyOpts, [hotCues]);

    // Sync playback state with external prop (Ranking Mode)
    useEffect(() => {
        if (!wavesurfer.current) return;
        if (isPlayingExternal === true) {
            wavesurfer.current.play().catch(() => { });
        } else if (isPlayingExternal === false) {
            wavesurfer.current.pause();
        }
    }, [isPlayingExternal]);

    if (loading && !fullTrack) return <div className="flex h-full items-center justify-center text-ink-muted bg-black">Loading...</div>;

    if (simpleMode) {
        return (
            <div className="flex flex-col h-full w-full bg-[#030303] overflow-hidden relative group rounded-xl">
                {/* Top Section: Overview with more room */}
                <div className="h-12 w-full border-b border-white/10 relative bg-black/60 shrink-0 mb-2">
                    <div ref={overviewRef} className="rb-overview-container !h-full !bg-transparent" />
                </div>

                {/* Main Section: Waveform with distinct 3-band coloring (Native Gradients) */}
                <div className="relative w-full flex-1 mt-1 bg-black overflow-hidden">
                    {/* 3-Band / RGB Layers - Stacked for clarity (Top to Bottom: High -> Mid -> Low) */}
                    {(visualMode === 'rgb' || visualMode === '3band') && (
                        <>
                            {/* High Band (Top) */}
                            <div ref={waveHighRef} className={`absolute inset-0 z-30 pointer-events-none opacity-100 ${visualMode === 'rgb' ? 'mix-blend-screen' : 'mix-blend-normal'}`} />
                            {/* Mid Band (Middle) */}
                            <div ref={waveMidRef} className={`absolute inset-0 z-20 pointer-events-none opacity-100 ${visualMode === 'rgb' ? 'mix-blend-screen' : 'mix-blend-normal'}`} />
                            {/* Low Band (Bottom) */}
                            <div ref={waveLowRef} className={`absolute inset-0 z-10 pointer-events-none opacity-100 ${visualMode === 'rgb' ? 'mix-blend-screen' : 'mix-blend-normal'}`} />
                        </>
                    )}
                    {/* Master Layer (Audio/Interaction) - Keep on top for interaction but transparent */}
                    <div ref={waveformRef} className="absolute inset-0 z-40" />

                    {analyzing && (
                        <div className="absolute inset-0 z-30 flex items-center justify-center bg-black/50 backdrop-blur-sm">
                            <span className="text-xs font-bold text-amber2 animate-pulse">ANALYZING 3-BAND...</span>
                        </div>
                    )}
                </div>

                <div className="absolute bottom-4 right-4 flex items-center gap-3 z-50">
                    <button
                        onClick={handleToggleVisualMode}
                        className="text-[10px] font-black text-white/50 hover:text-white hover:bg-black tracking-[0.2em] uppercase bg-black/80 px-3 py-1.5 rounded-lg border border-white/10 backdrop-blur-md shadow-2xl transition-all cursor-pointer"
                        title="Toggle Waveform Color"
                    >
                        {visualMode.toUpperCase()}
                    </button>
                </div>
            </div>
        );
    }

    return (
        <div className="rb-edit-container relative">
            {isRendering && (
                <div className="absolute inset-0 z-[100] flex flex-col items-center justify-center bg-black/90 backdrop-blur-md animate-fade-in">
                    <div className="w-80 p-8 glass-panel border border-amber2/20 rounded-2xl flex flex-col items-center">
                        <Loader2 size={48} className="text-amber2 animate-spin mb-6" />
                        <h3 className="text-xl font-bold text-white mb-2">Rendering Audio</h3>
                        <p className="text-ink-secondary text-sm mb-6">Processing insertion and effects...</p>

                        <div className="w-full h-2 bg-white/5 rounded-full overflow-hidden mb-2">
                            <div
                                className="h-full bg-gradient-to-r from-amber2 to-amber2-press transition-all duration-300"
                                style={{ width: `${renderProgress}%` }}
                            />
                        </div>
                        <div className="text-[10px] font-mono text-amber2 tracking-widest">{renderProgress}% COMPLETE</div>
                    </div>
                </div>
            )}
            {/* Top Toolbar - Purely for Project status now */}
            <div className="rb-header">
                <div className="flex items-center gap-6">
                    <div className="flex items-center gap-3">
                        <span className="text-ink-muted font-bold tracking-tight">RB EDITOR PRO</span>
                    </div>
                    <div className="bg-[#1a1a1a] h-6 px-4 flex items-center rounded border border-white/5 font-bold text-amber2 text-[10px]">
                        EDIT MODE
                    </div>
                </div>
                <div className="flex items-center gap-4">
                    <button
                        onClick={() => setShowBrowser(!showBrowser)}
                        className={`flex items-center gap-2 px-3 py-1.5 rounded-lg border text-[10px] font-bold transition-all ${showBrowser ? 'bg-amber2/20 border-amber2/30 text-amber2' : 'bg-[#1a1a1a] border-white/5 text-ink-muted'}`}
                    >
                        <ListPlus size={14} /> BROWSER
                    </button>
                    <div className="flex items-center gap-2 text-[10px] text-ink-muted font-mono">
                        <ScanLine size={12} />
                        <span>GRID LOCK: ON</span>
                    </div>
                </div>
            </div>


            {showBrowser && (
                <div className="absolute left-0 top-[88px] bottom-0 z-[60] shadow-2xl flex animate-slide-in-left">
                    <EditorBrowser onLoadTrack={loadTrack} onClose={() => setShowBrowser(false)} />
                </div>
            )}

            {/* Sub-Header / Project Bar */}
            <div className="h-10 bg-[#111] border-b border-white/5 px-4 flex items-center justify-between flex-shrink-0">
                <div className="flex items-center gap-4">
                    <select
                        value={selectedProject}
                        onChange={(e) => setSelectedProject(e.target.value)}
                        className="bg-[#050505] text-ink-primary font-bold outline-none text-xs border border-white/5 rounded px-2 py-1 max-w-[150px]"
                    >
                        <option value="">New Project</option>
                        {projectList.map(p => <option key={p.path} value={p.path}>{p.name}.prj</option>)}
                    </select>
                </div>
                <div className="flex items-center gap-4">
                    <div className="flex items-center gap-2 mr-2">
                        {hotCues.sort((a, b) => a.HotCueNum - b.HotCueNum).map(cue => (
                            <button
                                key={cue.ID}
                                onClick={() => jumpToCue(cue.InPoint)}
                                className="w-6 h-6 rounded flex items-center justify-center text-[10px] font-bold text-white transition-transform hover:scale-110"
                                style={{ backgroundColor: HOT_CUE_COLORS[cue.HotCueNum - 1] }}
                            >
                                {String.fromCharCode(64 + cue.HotCueNum)}
                            </button>
                        ))}
                    </div>

                    <div className="flex items-center bg-[#050505] px-2 py-1 rounded border border-white/5 gap-2">
                        <button onClick={() => wavesurfer.current?.stop()} className="rb-transport-btn"><SkipBack size={12} /></button>
                        <button onClick={() => wavesurfer.current?.playPause()} className="rb-transport-btn">
                            {isPlaying ? <Pause size={14} className="text-orange-500" /> : <Play size={14} />}
                        </button>
                    </div>

                    <div onClick={handleToggleVisualMode} className={`flex items-center h-8 px-3 rounded border border-white/5 gap-2 cursor-pointer transition-all ${visualMode !== 'blue' ? 'bg-indigo-500/20 border-indigo-500/30' : 'bg-black'}`}>
                        <Layers size={12} className={visualMode !== 'blue' ? 'text-indigo-400' : 'text-ink-muted'} />
                        <span className={`text-[10px] uppercase font-bold ${visualMode !== 'blue' ? 'text-indigo-400' : 'text-ink-muted'}`}>{visualMode}</span>
                    </div>

                    <div onClick={() => setIsQuantized(!isQuantized)} className={`flex items-center h-8 px-3 rounded border border-white/5 gap-2 cursor-pointer transition-all ${isQuantized ? 'bg-amber2/10 border-amber2/30' : 'bg-black'}`}>
                        <RotateCcw size={12} className={isQuantized ? 'text-amber2' : 'text-orange-500'} />
                        <span className={`text-[10px] uppercase font-bold ${isQuantized ? 'text-amber2' : 'text-ink-muted'}`}>Q : {isQuantized ? 'ON' : 'AUTO'}</span>
                    </div>

                    <div className="flex items-center gap-1 bg-[#050505] px-2 py-1 rounded border border-white/5">
                        <span className="text-[9px] text-ink-muted font-bold mr-2">GRID</span>
                        <button onClick={() => handleGridShift(-0.01)} className="p-1 hover:bg-white/5 rounded text-ink-secondary hover:text-white" title="-10ms"><ChevronLeft size={12} /></button>
                        <button onClick={() => handleSaveGrid()} className="p-1 hover:bg-white/5 rounded text-amber2 hover:text-amber2" title="Save Grid"><Save size={12} /></button>
                        <button onClick={() => handleGridShift(0.01)} className="p-1 hover:bg-white/5 rounded text-ink-secondary hover:text-white" title="+10ms"><ChevronRight size={12} /></button>
                    </div>

                    <button
                        onClick={handleDetectDrop}
                        className="flex items-center h-8 px-3 rounded border border-red-500/30 bg-red-500/10 gap-2 cursor-pointer transition-all hover:bg-red-500/20"
                        title="Detect Drop (Re-analyze)"
                    >
                        <Zap size={12} className="text-red-400" />
                        <span className="text-[10px] uppercase font-bold text-red-400">DROP</span>
                    </button>
                </div>
            </div>

            {/* Metadata Bar */}
            <div className="h-12 flex items-center justify-between px-6 bg-black border-b border-white/5">
                <div className="flex items-center gap-4">
                    <div className="rb-metadata-value !text-amber2 bg-amber2/20 px-2 rounded border border-amber2/20 uppercase">
                        {visualMode} MODE
                    </div>
                    <div className="flex items-center gap-4">
                        <div className="w-8 h-8 bg-amber2/20 flex items-center justify-center rounded border border-amber2/20">
                            <Disc size={20} className="text-amber2" />
                        </div>
                        <div>
                            <div className="text-sm font-bold truncate max-w-[200px]">{fullTrack?.Title || 'No Track'}</div>
                            <div className="text-[10px] text-ink-muted truncate">{fullTrack?.Artist || 'Unknown Artist'}</div>
                        </div>
                    </div>
                </div>
                <div className="rb-metadata-box">
                    <span>TIME <span className="rb-metadata-value">{formatTime(currentTime)}</span></span>
                    <span>KEY <span className="rb-metadata-value">{fullTrack?.Key || '4A'}</span></span>
                    <span>BPM <span className="rb-metadata-value">{bpm.toFixed(2)}</span></span>
                </div>
            </div>

            {/* Waveform Section */}
            <div className="flex-1 flex flex-col bg-black">
                {/* Overview */}
                <div ref={overviewRef} className="rb-overview-container" />

                {/* Detail View */}
                <div className="rb-detail-container relative">
                    {streaming ? (
                        <div className="absolute inset-0 z-[60] flex flex-col items-center justify-center bg-black/40 backdrop-blur-sm">
                            <div className="bg-mx-shell/80 p-8 rounded-2xl border border-white/10 flex flex-col items-center gap-4 shadow-2xl">
                                <div className="w-16 h-16 bg-amber-500/20 rounded-full flex items-center justify-center border border-amber-500/30">
                                    <Music size={32} className="text-amber-500" />
                                </div>
                                <div className="text-center">
                                    <h3 className="text-lg font-bold text-white mb-1 tracking-tight">Stream Not Supported</h3>
                                    <p className="text-sm text-ink-secondary max-w-[240px] leading-relaxed">
                                        Cloud and subscription tracks (SoundCloud, Spotify, etc.) cannot be analyzed or edited directly.
                                    </p>
                                </div>
                                <div className="flex gap-2 mt-2">
                                    <span className="px-3 py-1 bg-amber-500/10 text-amber-500 text-[10px] font-bold rounded-full border border-amber-500/20 uppercase tracking-widest">
                                        Restricted
                                    </span>
                                </div>
                            </div>
                        </div>
                    ) : (
                        loading && (
                            <div className="absolute inset-0 z-50 flex flex-col items-center justify-center bg-black/60 backdrop-blur-md">
                                <Loader2 className="w-12 h-12 text-amber2 animate-spin mb-4" />
                                <div className="text-amber2 font-bold uppercase tracking-widest text-xs animate-pulse">Loading Audio...</div>
                                <div className="text-[10px] text-ink-muted mt-2">Decoding high-fidelity waveform buffer</div>
                            </div>
                        )
                    )}

                    <div ref={waveformRef} className={`w-full h-full ws-wave-freq relative z-40
                        ${visualMode === 'blue' ? 'filter grayscale-[1] sepia-[1] hue-rotate-[190deg] saturate-[3] brightness-[0.8]' : ''}
                        ${streaming ? 'opacity-20 pointer-events-none' : ''}
                    `} />

                    {/* Canvas-based Beat Grid (replaces 1000+ Region DOM nodes) */}
                    {!streaming && (
                        <canvas ref={beatCanvasRef} className="absolute top-0 left-0 z-[45] pointer-events-none" />
                    )}

                    {/* Multi-Band Layers (Real Waveforms) */}
                    {!streaming && (visualMode === 'rgb' || visualMode === '3band') && (
                        <>
                            {/* Stacking: High (Top) > Mid > Low (Bottom) */}
                            {/* High Band (Highs) */}
                            <div ref={waveHighRef} className={`absolute inset-0 z-30 pointer-events-none opacity-100 ${visualMode === 'rgb' ? 'mix-blend-screen' : 'mix-blend-normal'}`} />
                            {/* Mid Band (Mids) */}
                            <div ref={waveMidRef} className={`absolute inset-0 z-20 pointer-events-none opacity-100 ${visualMode === 'rgb' ? 'mix-blend-screen' : 'mix-blend-normal'}`} />
                            {/* Low Band (Bass) */}
                            <div ref={waveLowRef} className={`absolute inset-0 z-10 pointer-events-none opacity-100 ${visualMode === 'rgb' ? 'mix-blend-screen' : 'mix-blend-normal'}`} />
                        </>
                    )}

                    {/* Zoom Controls Overlay */}
                    <div className="absolute bottom-4 left-4 flex gap-2 z-50">
                        <button onClick={() => setZoom(prev => Math.max(ZOOM_MIN, prev - ZOOM_STEP))} className="p-1 bg-black/60 border border-white/10 rounded pointer-events-auto" title="Zoom Out"><ZoomOut size={12} /></button>
                        <button onClick={() => setZoom(prev => Math.min(ZOOM_MAX, prev + ZOOM_STEP))} className="p-1 bg-black/60 border border-white/10 rounded pointer-events-auto" title="Zoom In"><ZoomIn size={12} /></button>
                        <div className="px-2 py-1 bg-black/60 border border-white/10 rounded text-[9px] font-mono text-ink-muted pointer-events-none">{zoom}px/s</div>
                    </div>

                    {/* Cuts Summary */}
                    {cuts.length > 0 && (
                        <div className="absolute top-2 right-2 bg-black/80 backdrop-blur-md border border-white/10 rounded-lg p-2 text-[10px] font-mono text-ink-secondary max-w-[200px]">
                            <div className="text-amber-400 font-bold mb-1 flex items-center gap-1"><Scissors size={10} /> {cuts.length} Edit(s)</div>
                            {cuts.slice(0, 3).map(c => (
                                <div key={c.id} className={`truncate ${c.type === 'delete' ? 'text-red-400' : 'text-green-400'}`}>
                                    {c.type === 'delete' ? `DEL: ${c.start.toFixed(1)}s - ${c.end.toFixed(1)}s` : `INS: @${(c.insertAt || 0).toFixed(1)}s`}
                                </div>
                            ))}
                            {cuts.length > 3 && <div className="text-ink-placeholder">+{cuts.length - 3} more</div>}
                        </div>
                    )}
                </div>
            </div>

            {/* Bottom Control Panels */}
            {/* Bottom Control Panels: Stacked Reversion */}
            <div className="flex bg-[#0a0a0a] border-t border-white/5 h-80 overflow-hidden">
                {/* Column 1: Loops & Beat Select */}
                <div className="w-1/2 border-r border-white/5 flex flex-col p-2 bg-[#050505]">
                    {/* Loops Top */}
                    <div className="flex-1 border-b border-white/5 p-2 flex flex-col">
                        <div className="rb-panel-title !bg-transparent !p-0 mb-3 flex items-center gap-2">
                            <Infinity size={12} className="text-amber-500" /> Loops
                        </div>
                        <div className="flex gap-2">
                            <button onClick={handleSetLoopIn} className="flex-1 h-12 bg-mx-card/40 hover:bg-mx-hover/40 border border-amber-500/30 text-amber-500 font-bold rounded flex items-center justify-center gap-2 text-xs">
                                LOOP IN
                            </button>
                            <button onClick={handleSetLoopOut} className="flex-1 h-12 bg-mx-card/40 hover:bg-mx-hover/40 border border-amber-500/30 text-amber-500 font-bold rounded flex items-center justify-center gap-2 text-xs">
                                LOOP OUT
                            </button>
                            <button onClick={() => { setLoopIn(null); setLoopOut(null); setIsLooping(false); }} className="w-12 h-12 bg-mx-card/20 border border-white/5 text-ink-muted rounded flex items-center justify-center">
                                <X size={14} />
                            </button>
                        </div>
                    </div>
                    {/* Beat Select Bottom */}
                    <div className="flex-1 p-2 flex flex-col">
                        <div className="rb-panel-title !bg-transparent !p-0 mb-3">Beat Select</div>
                        <div className="grid grid-cols-4 gap-1.5 overflow-y-auto">
                            {[1, 2, 4, 8, 16, 32, 64, 128].map(b => (
                                <button
                                    key={b}
                                    onClick={() => setSelectedBeats(b)}
                                    className={`h-9 text-[11px] font-bold border rounded transition-all ${selectedBeats === b ? 'bg-amber2/20 border-amber2 text-amber2' : 'bg-[#1a1a1a] border-white/5 text-ink-muted'}`}
                                >
                                    {b} BEAT
                                </button>
                            ))}
                        </div>
                    </div>
                </div>

                {/* Column 2: Hot Cues & Edit Actions */}
                <div className="w-1/2 flex flex-col p-2 bg-[#050505]">
                    {/* Hot Cues Top */}
                    <div className="flex-1 border-b border-white/5 p-2 flex flex-col overflow-hidden">
                        <div className="rb-panel-title !bg-transparent !p-0 mb-3 flex items-center gap-2">
                            <Target size={12} className="text-orange-400" /> Hot Cues
                        </div>
                        <div className="grid grid-cols-4 gap-2 flex-1 overflow-y-auto pr-1">
                            {[1, 2, 3, 4, 5, 6, 7, 8].map(num => {
                                const cue = hotCues.find(c => c.HotCueNum === num);
                                return (
                                    <button
                                        key={num}
                                        onClick={() => cue ? handleJumpHotCue(num) : handleSetHotCue(num)}
                                        onContextMenu={(e) => {
                                            e.preventDefault();
                                            if (cue) handleDeleteHotCue(num);
                                            else handleSetHotCue(num);
                                        }}
                                        title={cue ? `Jump to ${formatTime(cue.InPoint)} • Right-click to delete • Shift+${num} to overwrite` : `Set Hot Cue ${String.fromCharCode(64 + num)} (Shift+${num})`}
                                        className={`h-16 rounded border-2 flex flex-col items-center justify-center font-bold transition-all relative group ${cue
                                            ? 'text-white border-white/20 cursor-pointer'
                                            : 'bg-mx-card/30 border-white/5 text-ink-placeholder'
                                            }`}
                                        style={cue ? { backgroundColor: HOT_CUE_COLORS[num - 1] } : {}}
                                    >
                                        <span className="text-xl">{(String.fromCharCode(64 + num))}</span>
                                        {cue && (
                                            <div className="absolute top-1 right-1">
                                                <Target size={10} className="text-white/50" />
                                            </div>
                                        )}
                                        {cue && (
                                            <span className="absolute bottom-0.5 left-1/2 -translate-x-1/2 text-[8px] font-mono opacity-70">{formatTime(cue.InPoint)}</span>
                                        )}
                                        {!cue && <Plus size={12} className="opacity-0 group-hover:opacity-100 transition-opacity" />}
                                    </button>
                                );
                            })}
                        </div>
                        <button onClick={handleSaveCues} className="mt-2 h-7 bg-amber2/20 border border-amber2/30 text-amber2 text-[10px] font-bold rounded flex items-center justify-center gap-2">
                            <Save size={12} /> SAVE TO XML
                        </button>
                    </div>

                    {/* Edit Actions Bottom */}
                    <div className="flex-1 p-2 flex flex-col justify-end">
                        <div className="rb-panel-title !bg-transparent !p-0 mb-3 text-ink-secondary uppercase tracking-tighter">Edit Tools</div>
                        <div className="grid grid-cols-4 gap-2">
                            <button onClick={handleCopy} className="rb-tool-btn !py-2" title="Copy selection (Ctrl+C)"><Clipboard size={14} />COPY</button>
                            <button onClick={handlePaste} className="rb-tool-btn !py-2" title="Paste at cursor (Ctrl+V)"><Clipboard size={14} />PASTE</button>
                            <button onClick={handleInsert} className="rb-tool-btn !py-2" title="Insert silence (I)"><ListPlus size={14} />INSERT</button>
                            <button onClick={handleDelete} className="rb-tool-btn !py-2" title="Delete selection (Del)"><Trash2 size={14} />DELETE</button>
                            <button onClick={handleClear} className="rb-tool-btn !py-2 text-orange-400" title="Clear all edits"><Scissors size={14} />CLEAR</button>
                            <button onClick={handleUndo} disabled={historyIdx < 0} className="rb-tool-btn !py-2 disabled:opacity-20" title="Undo (Ctrl+Z)"><RotateCcw size={14} />UNDO</button>
                            <button onClick={handleRedo} disabled={historyIdx >= history.length - 1} className="rb-tool-btn !py-2 disabled:opacity-20" title="Redo (Ctrl+Shift+Z)"><RotateCw size={14} />REDO</button>
                            <button onClick={() => handleRender(cuts)} className="rb-tool-btn !py-2 text-amber2 border-amber2/10" title="Export edited audio (Ctrl+E)"><Download size={14} />EXPORT</button>
                        </div>
                    </div>
                </div>
            </div>

            {/* Confirm Modal (replaces window.confirm) */}
            {confirmModal && (
                <div className="absolute inset-0 z-[200] flex items-center justify-center bg-black/70 backdrop-blur-sm animate-fade-in" onClick={() => setConfirmModal(null)}>
                    <div className="w-[420px] glass-panel border border-white/10 rounded-2xl p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
                        <h3 className="text-lg font-bold text-white mb-2">{confirmModal.title || 'Confirm'}</h3>
                        <p className="text-sm text-ink-secondary mb-6 leading-relaxed">{confirmModal.message}</p>
                        <div className="flex gap-2 justify-end">
                            <button
                                onClick={() => setConfirmModal(null)}
                                className="px-4 py-2 rounded-lg bg-mx-card/40 hover:bg-mx-card/60 border border-white/10 text-sm font-bold text-ink-secondary"
                            >Cancel</button>
                            <button
                                onClick={() => {
                                    const cb = confirmModal.onConfirm;
                                    setConfirmModal(null);
                                    cb?.();
                                }}
                                className="px-4 py-2 rounded-lg bg-amber2/20 hover:bg-amber2/30 border border-amber2/40 text-sm font-bold text-amber2"
                                autoFocus
                            >{confirmModal.confirmLabel || 'Confirm'}</button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
});

export default WaveformEditor;
