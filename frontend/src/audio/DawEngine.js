/**
 * DawEngine — Web Audio API Playback Engine
 * 
 * Manages AudioContext lifecycle, audio loading, and region-based playback.
 * Designed for the DJ Edit DAW — schedules multiple AudioBufferSourceNodes
 * to play back non-contiguous regions seamlessly.
 */

import { convertFileSrc } from '@tauri-apps/api/core';

// ─── ENGINE STATE ──────────────────────────────────────────────────────────────

let audioContext = null;
let isResumed = false;
let activeSourceNodes = [];
let playbackStartTime = 0;  // audioContext.currentTime when playback started
let playbackOffset = 0;     // timeline offset where playback started (seconds)
let _isPlaying = false;
let _onPlaybackEnd = null;
let animFrameId = null;

// ─── AUDIO CONTEXT LIFECYCLE ───────────────────────────────────────────────────

/**
 * Get or create the AudioContext. Created in suspended state per browser policy.
 * @returns {AudioContext}
 */
export function getAudioContext() {
    if (!audioContext) {
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        console.log('[DawEngine] AudioContext created, state:', audioContext.state);
    }
    return audioContext;
}

/**
 * Resume the AudioContext. Must be called from a user gesture handler.
 * @returns {Promise<void>}
 */
export async function resumeContext() {
    const ctx = getAudioContext();
    if (ctx.state === 'suspended') {
        await ctx.resume();
        isResumed = true;
        console.log('[DawEngine] AudioContext resumed');
    }
}

/**
 * Ensure context is ready. Call this before any playback operation.
 */
async function ensureContext() {
    const ctx = getAudioContext();
    if (ctx.state === 'suspended') {
        await ctx.resume();
        isResumed = true;
    }
    return ctx;
}

/**
 * Dispose of the AudioContext and clear resources.
 * Important for preventing memory leaks in SPAs.
 */
export async function dispose() {
    stopPlayback();
    if (audioContext) {
        if (audioContext.state !== 'closed') {
            await audioContext.close();
        }
        audioContext = null;
        isResumed = false;
        console.log('[DawEngine] AudioContext closed and disposed');
    }
    clearCache();
}

// ─── AUDIO LOADING ─────────────────────────────────────────────────────────────

/**
 * Audio buffer cache. Key = filepath, Value = AudioBuffer
 */
const bufferCache = new Map();

/**
 * Load and decode an audio file into an AudioBuffer.
 * Caches results for repeated access.
 * 
 * @param {string} filepath - Path to audio file
 * @returns {Promise<AudioBuffer>}
 */
export async function loadAudio(filepath) {
    // Check cache first
    if (bufferCache.has(filepath)) {
        return bufferCache.get(filepath);
    }

    const ctx = getAudioContext();

    // 1. Try Tauri asset URL first (if available)
    let url;
    let useBackend = false;

    try {
        url = convertFileSrc(filepath);
    } catch (err) {
        console.warn('[DawEngine] convertFileSrc failed/not available, using backend.', err);
        useBackend = true;
    }

    if (useBackend) {
        url = `http://localhost:8000/api/audio/stream?path=${encodeURIComponent(filepath)}`;
    }

    console.log('[DawEngine] Loading audio:', filepath);
    console.log('[DawEngine] constructed URL:', url);

    try {
        let response = await fetch(url);

        // If fetch fails (or 404/500), try backend fallback if not already used
        if (!response.ok && !useBackend) {
            console.warn(`[DawEngine] Asset URL fetch failed (${response.status}), retrying with backend...`);
            const backendUrl = `http://localhost:8000/api/audio/stream?path=${encodeURIComponent(filepath)}`;
            console.log('[DawEngine] Retrying with:', backendUrl);
            response = await fetch(backendUrl);
        }

        if (!response.ok) {
            console.error(`[DawEngine] Final fetch failed: ${response.status} ${response.statusText}`);
            throw new Error(`Failed to fetch audio: ${response.status} ${response.statusText}`);
        }

        console.log('[DawEngine] Fetch success, content-length:', response.headers.get('content-length'));

        const arrayBuffer = await response.arrayBuffer();
        const audioBuffer = await ctx.decodeAudioData(arrayBuffer);

        bufferCache.set(filepath, audioBuffer);
        console.log('[DawEngine] Decoded:', filepath, `${audioBuffer.duration.toFixed(1)}s`);

        return audioBuffer;

    } catch (err) {
        // If fetch threw network error (e.g. CSP blocked), retry with backend
        if (!useBackend) {
            console.warn('[DawEngine] Network error with asset URL, retrying with backend:', err);
            try {
                const backendUrl = `http://localhost:8000/api/audio/stream?path=${encodeURIComponent(filepath)}`;
                console.log('[DawEngine] Retrying with:', backendUrl);
                const response = await fetch(backendUrl);
                if (!response.ok) throw new Error(`Backend fetch failed: ${response.status}`);

                const arrayBuffer = await response.arrayBuffer();
                const audioBuffer = await ctx.decodeAudioData(arrayBuffer);
                bufferCache.set(filepath, audioBuffer);

                console.log('[DawEngine] Decoded (Retry):', filepath);
                return audioBuffer;
            } catch (retryErr) {
                console.error('[DawEngine] Backend fallback failed:', retryErr);
                throw new Error(`Load failed: ${err.message} -> Retry: ${retryErr.message}`);
            }
        }

        console.error('[DawEngine] Error loading audio:', err);
        throw err;
    }
}

/**
 * Clear the audio buffer cache.
 */
export function clearCache() {
    bufferCache.clear();
}

// ─── PLAYBACK ──────────────────────────────────────────────────────────────────

/**
 * Play regions from a given timeline position.
 * Schedules one AudioBufferSourceNode per region that overlaps the playback range.
 * 
 * @param {Array} regions - Array of region objects with timelineStart, duration, sourceStart, sourceEnd
 * @param {AudioBuffer} sourceBuffer - The decoded audio buffer for the source file
 * @param {number} fromTime - Timeline position to start playback (seconds)
 * @param {number} [toTime] - Optional end time (for loop playback)
 * @param {Function} [onEnd] - Callback when playback reaches end
 */
export async function playRegions(regions, sourceBuffer, fromTime, toTime = null, onEnd = null) {
    const ctx = await ensureContext();

    // Stop any current playback
    stopPlayback();

    if (!regions || regions.length === 0 || !sourceBuffer) return;

    _isPlaying = true;
    _onPlaybackEnd = onEnd;
    playbackStartTime = ctx.currentTime;
    playbackOffset = fromTime;

    // Sort regions by timeline position
    const sorted = [...regions].sort((a, b) => a.timelineStart - b.timelineStart);

    // Calculate the total timeline duration
    const timelineEnd = toTime || Math.max(...sorted.map(r => r.timelineStart + r.duration));

    // Schedule each region that falls within the playback range
    let lastScheduledEnd = 0;

    for (const region of sorted) {
        const regionEnd = region.timelineStart + region.duration;

        // Skip regions entirely before the playback start
        if (regionEnd <= fromTime) continue;
        // Skip regions entirely after the playback end
        if (toTime && region.timelineStart >= toTime) continue;

        // Calculate when this region starts relative to playback start
        const scheduleStart = Math.max(0, region.timelineStart - fromTime);

        // Calculate the offset within the source buffer
        let bufferOffset = region.sourceStart;
        let playDuration = region.sourceDuration || (region.sourceEnd - region.sourceStart);

        // If playback starts mid-region, adjust offset and duration
        if (fromTime > region.timelineStart) {
            const skipAmount = fromTime - region.timelineStart;
            bufferOffset += skipAmount;
            playDuration -= skipAmount;
        }

        // If playing to a specific end time, clip the duration
        if (toTime && regionEnd > toTime) {
            playDuration -= (regionEnd - toTime);
        }

        if (playDuration <= 0) continue;

        // Create and schedule the source node
        const source = ctx.createBufferSource();
        source.buffer = sourceBuffer;
        source.connect(ctx.destination);
        source.start(ctx.currentTime + scheduleStart, bufferOffset, playDuration);

        activeSourceNodes.push(source);
        lastScheduledEnd = Math.max(lastScheduledEnd, scheduleStart + playDuration);
    }

    // Set up end detection
    if (lastScheduledEnd > 0) {
        const checkEnd = () => {
            if (!_isPlaying) return;
            const elapsed = ctx.currentTime - playbackStartTime;
            if (elapsed >= lastScheduledEnd) {
                _isPlaying = false;
                if (_onPlaybackEnd) _onPlaybackEnd();
            } else {
                setTimeout(checkEnd, 50);
            }
        };
        setTimeout(checkEnd, 50);
    }
}

/**
 * Stop all active playback.
 */
export function stopPlayback() {
    for (const node of activeSourceNodes) {
        try { node.stop(); } catch { /* already stopped */ }
        try { node.disconnect(); } catch { /* already disconnected */ }
    }
    activeSourceNodes = [];
    _isPlaying = false;
    _onPlaybackEnd = null;
}

/**
 * Get the current playback position on the timeline (seconds).
 * @returns {number}
 */
export function getCurrentTime() {
    if (!_isPlaying || !audioContext) return playbackOffset;
    const elapsed = audioContext.currentTime - playbackStartTime;
    return playbackOffset + elapsed;
}

/**
 * Check if currently playing.
 * @returns {boolean}
 */
export function isPlaying() {
    return _isPlaying;
}

// ─── OFFLINE RENDERING (EXPORT) ────────────────────────────────────────────────

/**
 * Render the timeline to an AudioBuffer using OfflineAudioContext.
 * Used for WAV/MP3 export.
 * 
 * @param {Array} regions - Regions to render
 * @param {AudioBuffer} sourceBuffer - Source audio buffer
 * @param {number} sampleRate - Output sample rate (default: 44100)
 * @param {Function} [onProgress] - Progress callback (0-1)
 * @returns {Promise<AudioBuffer>}
 */
export async function renderTimeline(regions, sourceBuffer, sampleRate = 44100, onProgress = null) {
    if (!regions || regions.length === 0 || !sourceBuffer) {
        throw new Error('No regions or source buffer to render');
    }

    // Calculate total duration
    const sorted = [...regions].sort((a, b) => a.timelineStart - b.timelineStart);
    const totalDuration = Math.max(...sorted.map(r => r.timelineStart + r.duration));
    const totalSamples = Math.ceil(totalDuration * sampleRate);
    const numChannels = sourceBuffer.numberOfChannels;

    const offlineCtx = new OfflineAudioContext(numChannels, totalSamples, sampleRate);

    // Schedule all regions
    for (const region of sorted) {
        const source = offlineCtx.createBufferSource();
        source.buffer = sourceBuffer;
        source.connect(offlineCtx.destination);

        const bufferOffset = region.sourceStart;
        const playDuration = region.sourceDuration || (region.sourceEnd - region.sourceStart);

        source.start(region.timelineStart, bufferOffset, playDuration);
    }

    if (onProgress) onProgress(0.1);

    const renderedBuffer = await offlineCtx.startRendering();

    if (onProgress) onProgress(1.0);

    return renderedBuffer;
}

/**
 * Convert an AudioBuffer to a WAV Blob.
 * Clean implementation without the legacy bugs.
 * 
 * @param {AudioBuffer} buffer
 * @returns {Blob}
 */
export function audioBufferToWav(buffer) {
    const numChannels = buffer.numberOfChannels;
    const sampleRate = buffer.sampleRate;
    const format = 1; // PCM
    const bitDepth = 16;

    const bytesPerSample = bitDepth / 8;
    const blockAlign = numChannels * bytesPerSample;
    const dataLength = buffer.length * blockAlign;
    const headerLength = 44;
    const totalLength = headerLength + dataLength;

    const arrayBuffer = new ArrayBuffer(totalLength);
    const view = new DataView(arrayBuffer);

    let offset = 0;

    // Helper functions
    const writeString = (str) => {
        for (let i = 0; i < str.length; i++) {
            view.setUint8(offset++, str.charCodeAt(i));
        }
    };
    const writeUint32 = (val) => { view.setUint32(offset, val, true); offset += 4; };
    const writeUint16 = (val) => { view.setUint16(offset, val, true); offset += 2; };

    // RIFF header
    writeString('RIFF');
    writeUint32(totalLength - 8);
    writeString('WAVE');

    // fmt chunk
    writeString('fmt ');
    writeUint32(16);              // chunk size
    writeUint16(format);          // PCM
    writeUint16(numChannels);
    writeUint32(sampleRate);
    writeUint32(sampleRate * blockAlign);  // byte rate
    writeUint16(blockAlign);
    writeUint16(bitDepth);

    // data chunk
    writeString('data');
    writeUint32(dataLength);

    // Extract channel data
    const channels = [];
    for (let ch = 0; ch < numChannels; ch++) {
        channels.push(buffer.getChannelData(ch));
    }

    // Write interleaved samples
    for (let i = 0; i < buffer.length; i++) {
        for (let ch = 0; ch < numChannels; ch++) {
            let sample = channels[ch][i];
            sample = Math.max(-1, Math.min(1, sample));
            sample = sample < 0 ? sample * 0x8000 : sample * 0x7FFF;
            view.setInt16(offset, sample, true);
            offset += 2;
        }
    }

    return new Blob([arrayBuffer], { type: 'audio/wav' });
}

export default {
    getAudioContext,
    resumeContext,
    loadAudio,
    clearCache,
    playRegions,
    stopPlayback,
    getCurrentTime,
    isPlaying,
    renderTimeline,
    audioBufferToWav,
    dispose,
};
