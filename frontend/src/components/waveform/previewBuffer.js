import api from '../../api/api';

// --- Shared decode context (reused, not recreated per insert) ---
let _sharedDecodeCtx = null;
const getSharedDecodeContext = () => {
    if (!_sharedDecodeCtx || _sharedDecodeCtx.state === 'closed') {
        _sharedDecodeCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    return _sharedDecodeCtx;
};

// Cache decoded insert slices keyed by `${src}:${start}:${end}` to avoid re-fetching
const insertSliceCache = new Map();
const SLICE_CACHE_MAX = 32;
const cacheSlice = (key, buffer) => {
    if (insertSliceCache.size >= SLICE_CACHE_MAX) {
        // Drop oldest entry (insertion order)
        const firstKey = insertSliceCache.keys().next().value;
        insertSliceCache.delete(firstKey);
    }
    insertSliceCache.set(key, buffer);
};

// --- Utility: Build Preview Buffer (Async with Splicing) ---
export const buildPreviewBuffer = async (originalBuffer, cuts, originalDuration, originalPath) => {
    // 1. Build Base Segments (Handle Deletes)
    const deleteCuts = cuts.filter(c => c.type === 'delete').sort((a, b) => a.start - b.start);
    let baseSegments = [];
    let lastPos = 0;

    deleteCuts.forEach(cut => {
        if (cut.start > lastPos) {
            baseSegments.push({ src: 'ORIGINAL', start: lastPos, end: cut.start, duration: cut.start - lastPos });
        }
        lastPos = Math.max(lastPos, cut.end);
    });
    if (lastPos < originalDuration) {
        baseSegments.push({ src: 'ORIGINAL', start: lastPos, end: originalDuration, duration: originalDuration - lastPos });
    }

    const baseTotalLen = baseSegments.reduce((sum, s) => sum + s.duration, 0);
    const sampleRate = originalBuffer.sampleRate;
    const channels = originalBuffer.numberOfChannels;

    // Create Base Buffer (use OfflineAudioContext just to get a valid AudioBuffer)
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

    // 2. Inject Inserts (sorted DESC by insertAt to avoid index invalidation)
    const inserts = cuts.filter(c => c.type === 'insert').sort((a, b) => b.insertAt - a.insertAt);
    let currentBuf = baseBuf;

    for (let ins of inserts) {
        let insBuf = null;
        if (ins.src && ins.start !== undefined && ins.end !== undefined) {
            const cacheKey = `${ins.src}:${ins.start.toFixed(4)}:${ins.end.toFixed(4)}`;
            if (insertSliceCache.has(cacheKey)) {
                insBuf = insertSliceCache.get(cacheKey);
            } else {
                try {
                    const sliceRes = await api.post('/api/audio/slice', { source_path: ins.src, start: ins.start, end: ins.end });
                    const arrayBuf = await (await fetch(sliceRes.data.url)).arrayBuffer();
                    // Reuse shared decode context (avoids hitting browser's AudioContext limit ~6)
                    const ctx = getSharedDecodeContext();
                    insBuf = await ctx.decodeAudioData(arrayBuf);
                    cacheSlice(cacheKey, insBuf);
                } catch (e) { console.error('Slice fetch failed', e); }
            }
        }

        if (!insBuf) {
            const gapFrames = Math.floor((ins.gap || 1) * sampleRate);
            // Use cheap throw-away OfflineAudioContext just to get an AudioBuffer instance
            const ctx = new OfflineAudioContext(channels, gapFrames, sampleRate);
            insBuf = ctx.createBuffer(channels, gapFrames, sampleRate);
        }

        const splitFrame = Math.floor(ins.insertAt * sampleRate);
        const safeSplit = Math.max(0, Math.min(splitFrame, currentBuf.length));

        const newTotal = currentBuf.length + insBuf.length;
        const newCtx = new OfflineAudioContext(channels, newTotal, sampleRate);
        const newBuf = newCtx.createBuffer(channels, newTotal, sampleRate);

        for (let c = 0; c < channels; c++) {
            const cData = currentBuf.getChannelData(c);
            const iData = insBuf.getChannelData(Math.min(c, insBuf.numberOfChannels - 1));
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
export const bufferToWave = (abuffer, len) => {
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

    return new Blob([buffer], { type: 'audio/wav' });

    function setUint16(data) { view.setUint16(pos, data, true); pos += 2; }
    function setUint32(data) { view.setUint32(pos, data, true); pos += 4; }
};
