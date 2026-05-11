/**
 * useEditorPlayback - Audio loading + playback engine + render/export
 *
 * Owns:
 * - audioContextRef, sourceBufferRef, playerRef, startTimeRef, pauseTimeRef
 * - isLoading / isPlaying / isRendering / renderProgress state
 * - Loads sourceUrl into an AudioBuffer (and seeds TimelineState)
 * - Transport handlers (play/pause/stop)
 * - Seamless seek via handlePlayheadChange
 * - Offline rendering -> WAV download via handleRender
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { loadAudioSource } from '../../audio/TimelineState';

// Buffer to WAV conversion helper (kept local to the playback hook)
function bufferToWave(abuffer, len) {
    const numOfChan = abuffer.numberOfChannels;
    const length = len * numOfChan * 2 + 44;
    const buffer = new ArrayBuffer(length);
    const view = new DataView(buffer);
    const channels = [];
    let offset = 0;
    let pos = 0;

    function setUint16(data) { view.setUint16(pos, data, true); pos += 2; }
    function setUint32(data) { view.setUint32(pos, data, true); pos += 4; }

    setUint32(0x46464952); // "RIFF"
    setUint32(length - 8);
    setUint32(0x45564157); // "WAVE"
    setUint32(0x20746d66); // "fmt "
    setUint32(16);
    setUint16(1);
    setUint16(numOfChan);
    setUint32(abuffer.sampleRate);
    setUint32(abuffer.sampleRate * 2 * numOfChan);
    setUint16(numOfChan * 2);
    setUint16(16);
    setUint32(0x61746164); // "data"
    setUint32(length - pos - 4);

    for (let i = 0; i < abuffer.numberOfChannels; i++)
        channels.push(abuffer.getChannelData(i));

    while (pos < len) {
        for (let i = 0; i < numOfChan; i++) {
            let sample = Math.max(-1, Math.min(1, channels[i][pos]));
            sample = (0.5 + sample < 0 ? sample * 32768 : sample * 32767) | 0;
            view.setInt16(44 + offset, sample, true);
            offset += 2;
        }
        pos++;
    }

    return new Blob([buffer], { type: 'audio/wav' });
}

export default function useEditorPlayback({
    sourceUrl,
    sourcePath,
    state,
    setState,
    track,
    onRenderComplete,
}) {
    const audioContextRef = useRef(null);
    const sourceBufferRef = useRef(null);
    const playerRef = useRef(null);
    const startTimeRef = useRef(0);
    const pauseTimeRef = useRef(0);

    const [isLoading, setIsLoading] = useState(true);
    const [isPlaying, setIsPlaying] = useState(false);
    const [isRendering, setIsRendering] = useState(false);
    const [renderProgress, setRenderProgress] = useState(0);

    // Load audio source
    useEffect(() => {
        if (!sourceUrl) return;

        const loadAudio = async () => {
            setIsLoading(true);
            try {
                const ctx = new (window.AudioContext || window.webkitAudioContext)();
                audioContextRef.current = ctx;

                const response = await fetch(sourceUrl);
                const arrayBuffer = await response.arrayBuffer();
                const audioBuffer = await ctx.decodeAudioData(arrayBuffer);

                sourceBufferRef.current = audioBuffer;

                setState(prev => loadAudioSource(prev, audioBuffer, sourcePath));
                setIsLoading(false);
            } catch (error) {
                console.error('Failed to load audio:', error);
                setIsLoading(false);
            }
        };

        loadAudio();

        return () => {
            if (audioContextRef.current) {
                audioContextRef.current.close();
            }
        };
    }, [sourceUrl, sourcePath, setState]);

    // Playback controls
    const handlePlay = useCallback(() => {
        if (!audioContextRef.current || !sourceBufferRef.current) return;

        const ctx = audioContextRef.current;
        if (ctx.state === 'suspended') ctx.resume();

        const source = ctx.createBufferSource();
        source.buffer = sourceBufferRef.current;
        source.connect(ctx.destination);

        const offset = pauseTimeRef.current || state.playhead;
        source.start(0, offset);
        startTimeRef.current = ctx.currentTime - offset;
        playerRef.current = source;

        setIsPlaying(true);
        setState(prev => ({ ...prev, isPlaying: true }));

        // Update playhead during playback
        const updatePlayhead = () => {
            if (!isPlaying) return;
            const currentTime = ctx.currentTime - startTimeRef.current;
            setState(prev => ({ ...prev, playhead: currentTime }));
            requestAnimationFrame(updatePlayhead);
        };
        requestAnimationFrame(updatePlayhead);

        source.onended = () => {
            setIsPlaying(false);
            setState(prev => ({ ...prev, isPlaying: false }));
        };
    }, [state.playhead, isPlaying, setState]);

    const handlePause = useCallback(() => {
        if (playerRef.current) {
            playerRef.current.stop();
            pauseTimeRef.current = audioContextRef.current.currentTime - startTimeRef.current;
        }
        setIsPlaying(false);
        setState(prev => ({ ...prev, isPlaying: false }));
    }, [setState]);

    const handleStop = useCallback(() => {
        if (playerRef.current) {
            playerRef.current.stop();
        }
        pauseTimeRef.current = 0;
        setIsPlaying(false);
        setState(prev => ({ ...prev, isPlaying: false, playhead: 0 }));
    }, [setState]);

    // Playhead change with seamless-seek if playing
    const handlePlayheadChange = useCallback((time) => {
        pauseTimeRef.current = time;
        setState(prev => ({ ...prev, playhead: time }));

        // Seamless-seek if playing
        if (isPlaying && playerRef.current && audioContextRef.current && sourceBufferRef.current) {
            try {
                // Prevent onended from stopping playback during seek
                playerRef.current.onended = null;
                playerRef.current.stop();
            } catch (e) { /* Ignore if already stopped */ }

            const ctx = audioContextRef.current;
            const source = ctx.createBufferSource();
            source.buffer = sourceBufferRef.current;
            source.connect(ctx.destination);

            source.start(0, time);
            startTimeRef.current = ctx.currentTime - time;
            playerRef.current = source;

            // Restore onended
            source.onended = () => {
                setIsPlaying(false);
                setState(prev => ({ ...prev, isPlaying: false }));
            };
        }
    }, [isPlaying, setState]);

    // Render / Export
    const handleRender = useCallback(async () => {
        if (!sourceBufferRef.current || state.regions.length === 0) return;

        setIsRendering(true);
        setRenderProgress(10);

        try {
            const sortedRegions = [...state.regions].sort(
                (a, b) => a.timelineStart - b.timelineStart
            );

            const totalDuration = Math.max(
                ...sortedRegions.map(r => r.timelineStart + (r.sourceEnd - r.sourceStart))
            );

            const sampleRate = sourceBufferRef.current.sampleRate;
            const channels = sourceBufferRef.current.numberOfChannels;
            const offlineCtx = new OfflineAudioContext(
                channels,
                Math.ceil(totalDuration * sampleRate),
                sampleRate
            );

            setRenderProgress(30);

            for (const region of sortedRegions) {
                const source = offlineCtx.createBufferSource();
                source.buffer = region.sourceBuffer;

                // Create gain node for envelope
                const gainNode = offlineCtx.createGain();

                const regionStart = region.timelineStart;
                const regionDuration = region.sourceEnd - region.sourceStart;
                const regionEnd = regionStart + regionDuration;

                // Apply fade-in
                gainNode.gain.setValueAtTime(0, regionStart);
                gainNode.gain.linearRampToValueAtTime(
                    region.gain,
                    regionStart + region.fadeInDuration
                );

                // Steady gain
                gainNode.gain.setValueAtTime(
                    region.gain,
                    regionEnd - region.fadeOutDuration
                );

                // Fade-out
                gainNode.gain.linearRampToValueAtTime(0, regionEnd);

                source.connect(gainNode);
                gainNode.connect(offlineCtx.destination);

                source.start(regionStart, region.sourceStart, regionDuration);
            }

            setRenderProgress(60);

            const renderedBuffer = await offlineCtx.startRendering();

            setRenderProgress(90);

            // Convert to WAV blob
            const wavBlob = bufferToWave(renderedBuffer, renderedBuffer.length);

            // Create download link
            const url = URL.createObjectURL(wavBlob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${track?.Title || 'Rendered'}_Edit_${Date.now()}.wav`;
            a.click();
            URL.revokeObjectURL(url);

            setRenderProgress(100);
            setTimeout(() => {
                setIsRendering(false);
                setRenderProgress(0);
            }, 500);

            onRenderComplete?.(wavBlob);
        } catch (error) {
            console.error('Render failed:', error);
            setIsRendering(false);
            setRenderProgress(0);
        }
    }, [state.regions, track, onRenderComplete]);

    return {
        // Refs (shared with persistence hook)
        audioContextRef,
        sourceBufferRef,
        // Loading state
        isLoading,
        setIsLoading,
        // Transport
        isPlaying,
        isRendering,
        renderProgress,
        handlePlay,
        handlePause,
        handleStop,
        handlePlayheadChange,
        handleRender,
    };
}
