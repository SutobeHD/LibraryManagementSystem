
/**
 * AudioBandAnalyzer
 * Splits an AudioBuffer into 3 frequency bands (Rekordbox-style):
 * - Low: < 400 Hz  (Bass / Kick / Punch)
 * - Mid: 400 Hz - 2000 Hz  (Vocals / Instruments)
 * - High: > 2000 Hz (Cymbals / Hi-Hats / Air)
 *
 * Also generates multi-resolution (LOD) peak arrays for zoom-adaptive rendering.
 */
class AudioBandAnalyzer {
    /**
     * Splits audio buffer into 3 bands.
     * @param {AudioBuffer} audioBuffer
     * @returns {Promise<{low: AudioBuffer, mid: AudioBuffer, high: AudioBuffer}>}
     */
    static async splitBands(audioBuffer) {
        if (!audioBuffer) throw new Error('No buffer provided');

        const lowConfig = [{ type: 'lowpass', freq: 400 }];
        const midConfig = [
            { type: 'highpass', freq: 400 },
            { type: 'lowpass', freq: 2000 }
        ];
        const highConfig = [{ type: 'highpass', freq: 2000 }];

        const [low, mid, high] = await Promise.all([
            this.renderFilteredBuffer(audioBuffer, lowConfig),
            this.renderFilteredBuffer(audioBuffer, midConfig),
            this.renderFilteredBuffer(audioBuffer, highConfig),
        ]);

        return { low, mid, high };
    }

    static async renderFilteredBuffer(buffer, filterConfigs) {
        const ctx = new OfflineAudioContext(buffer.numberOfChannels, buffer.length, buffer.sampleRate);
        const source = ctx.createBufferSource();
        source.buffer = buffer;
        let lastNode = source;
        filterConfigs.forEach(config => {
            const filter = ctx.createBiquadFilter();
            filter.type = config.type;
            filter.frequency.value = config.freq;
            filter.Q.value = 0.707; // Butterworth — flat passband
            lastNode.connect(filter);
            lastNode = filter;
        });
        lastNode.connect(ctx.destination);
        source.start();
        return await ctx.startRendering();
    }

    /**
     * Generate peak data from an AudioBuffer for waveform visualization.
     * Returns an array of { min, max } values, one per pixel column.
     *
     * @param {AudioBuffer} buffer - Audio buffer to analyze
     * @param {number} samplesPerPixel - How many samples each pixel column represents
     * @returns {Array<{min: number, max: number}>}
     */
    static generatePeaks(buffer, samplesPerPixel) {
        if (!buffer) return [];

        // Merge channels to mono
        const length = buffer.length;
        const numChannels = buffer.numberOfChannels;
        const data = new Float32Array(length);

        for (let ch = 0; ch < numChannels; ch++) {
            const channelData = buffer.getChannelData(ch);
            for (let i = 0; i < length; i++) {
                data[i] += channelData[i] / numChannels;
            }
        }

        const numPeaks = Math.ceil(length / samplesPerPixel);
        const peaks = new Array(numPeaks);

        for (let i = 0; i < numPeaks; i++) {
            const start = i * samplesPerPixel;
            const end = Math.min(start + samplesPerPixel, length);
            let min = 0;
            let max = 0;

            for (let j = start; j < end; j++) {
                const val = data[j];
                if (val < min) min = val;
                if (val > max) max = val;
            }

            peaks[i] = { min, max };
        }

        return peaks;
    }

    /**
     * Generate 3-band peak data for RGB waveform rendering.
     *
     * @param {AudioBuffer} audioBuffer
     * @param {number} samplesPerPixel
     * @param {Function} [onProgress]
     * @returns {Promise<{low: Array, mid: Array, high: Array}>}
     */
    static async generateBandPeaks(audioBuffer, samplesPerPixel, onProgress = null) {
        if (onProgress) onProgress(0);

        const { low, mid, high } = await this.splitBands(audioBuffer);
        if (onProgress) onProgress(0.5);

        const lowPeaks = this.generatePeaks(low, samplesPerPixel);
        const midPeaks = this.generatePeaks(mid, samplesPerPixel);
        const highPeaks = this.generatePeaks(high, samplesPerPixel);

        if (onProgress) onProgress(1.0);

        return { low: lowPeaks, mid: midPeaks, high: highPeaks };
    }

    /**
     * Generate multi-resolution (LOD) peak data for all 3 bands + mono fallback.
     * Produces r1 (full), r2 (half), r4 (quarter) resolution arrays.
     * This enables instant zoom-level switching with no recalculation in the render loop.
     *
     * @param {AudioBuffer} audioBuffer
     * @param {number} baseSamplesPerPixel - Base resolution (for r1)
     * @param {Function} [onProgress]
     * @returns {Promise<{low, mid, high, mono, lod: {r1, r2, r4}}>}
     */
    static async generateMultiResolutionPeaks(audioBuffer, baseSamplesPerPixel, onProgress = null) {
        if (onProgress) onProgress(0);

        const { low, mid, high } = await this.splitBands(audioBuffer);
        if (onProgress) onProgress(0.4);

        // Full resolution
        const lowR1 = this.generatePeaks(low, baseSamplesPerPixel);
        const midR1 = this.generatePeaks(mid, baseSamplesPerPixel);
        const highR1 = this.generatePeaks(high, baseSamplesPerPixel);
        const monoR1 = this.generatePeaks(audioBuffer, baseSamplesPerPixel);
        if (onProgress) onProgress(0.65);

        // Half resolution (2× decimated)
        const lowR2 = this._decimatePeaks(lowR1, 2);
        const midR2 = this._decimatePeaks(midR1, 2);
        const highR2 = this._decimatePeaks(highR1, 2);
        if (onProgress) onProgress(0.8);

        // Quarter resolution (4× decimated)
        const lowR4 = this._decimatePeaks(lowR1, 4);
        const midR4 = this._decimatePeaks(midR1, 4);
        const highR4 = this._decimatePeaks(highR1, 4);
        if (onProgress) onProgress(1.0);

        return {
            low: lowR1,
            mid: midR1,
            high: highR1,
            mono: monoR1,
            lod: {
                r1: { low: lowR1, mid: midR1, high: highR1 },
                r2: { low: lowR2, mid: midR2, high: highR2 },
                r4: { low: lowR4, mid: midR4, high: highR4 },
            },
        };
    }

    /**
     * Decimate peaks by combining every N entries into one.
     * Takes absolute max/min over group — preserves true peak.
     */
    static _decimatePeaks(peaks, factor) {
        if (!peaks || peaks.length === 0) return [];
        const out = [];
        for (let i = 0; i < peaks.length; i += factor) {
            let min = 0, max = 0;
            for (let j = i; j < Math.min(i + factor, peaks.length); j++) {
                if (peaks[j].min < min) min = peaks[j].min;
                if (peaks[j].max > max) max = peaks[j].max;
            }
            out.push({ min, max });
        }
        return out;
    }

    /**
     * Converts AudioBuffer to WAV Blob
     * @param {AudioBuffer} buffer
     * @returns {Blob}
     */
    static bufferToWav(buffer) {
        const numOfChan = buffer.numberOfChannels;
        const sampleRate = buffer.sampleRate;
        const bitDepth = 16;
        const bytesPerSample = bitDepth / 8;
        const blockAlign = numOfChan * bytesPerSample;
        const dataLength = buffer.length * blockAlign;
        const headerLength = 44;
        const totalLength = headerLength + dataLength;

        const arrayBuffer = new ArrayBuffer(totalLength);
        const view = new DataView(arrayBuffer);

        let offset = 0;

        const writeStr = (str) => {
            for (let i = 0; i < str.length; i++) {
                view.setUint8(offset++, str.charCodeAt(i));
            }
        };
        const writeU32 = (val) => { view.setUint32(offset, val, true); offset += 4; };
        const writeU16 = (val) => { view.setUint16(offset, val, true); offset += 2; };

        // RIFF header
        writeStr('RIFF');
        writeU32(totalLength - 8);
        writeStr('WAVE');

        // fmt chunk
        writeStr('fmt ');
        writeU32(16);
        writeU16(1);  // PCM
        writeU16(numOfChan);
        writeU32(sampleRate);
        writeU32(sampleRate * blockAlign);
        writeU16(blockAlign);
        writeU16(bitDepth);

        // data chunk
        writeStr('data');
        writeU32(dataLength);

        // Extract channels
        const channels = [];
        for (let ch = 0; ch < numOfChan; ch++) {
            channels.push(buffer.getChannelData(ch));
        }

        // Write interleaved samples
        for (let i = 0; i < buffer.length; i++) {
            for (let ch = 0; ch < numOfChan; ch++) {
                let s = channels[ch][i];
                s = Math.max(-1, Math.min(1, s));
                s = s < 0 ? s * 0x8000 : s * 0x7FFF;
                view.setInt16(offset, s, true);
                offset += 2;
            }
        }

        return new Blob([arrayBuffer], { type: 'audio/wav' });
    }
}

export default AudioBandAnalyzer;
