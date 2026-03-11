
/**
 * AudioBandAnalyzer
 * Splits an AudioBuffer into 3 frequency bands (Rekordbox-style):
 * - Low: < 400 Hz  (Bass / Kick / Punch)
 * - Mid: 400 Hz - 2000 Hz  (Vocals / Instruments)
 * - High: > 2000 Hz (Cymbals / Hi-Hats / Air)
 * 
 * Uses OfflineAudioContext for fast rendering.
 * Also provides peak generation for waveform visualization.
 */
class AudioBandAnalyzer {
    /**
     * Splits audio buffer into 3 bands.
     * @param {AudioBuffer} audioBuffer 
     * @returns {Promise<{low: AudioBuffer, mid: AudioBuffer, high: AudioBuffer}>}
     */
    static async splitBands(audioBuffer) {
        if (!audioBuffer) throw new Error("No buffer provided");

        const lowConfig = [{ type: 'lowpass', freq: 400 }];
        const midConfig = [
            { type: 'highpass', freq: 400 },
            { type: 'lowpass', freq: 2000 }
        ];
        const highConfig = [{ type: 'highpass', freq: 2000 }];

        const [low, mid, high] = await Promise.all([
            this.renderFilteredBuffer(audioBuffer, lowConfig),
            this.renderFilteredBuffer(audioBuffer, midConfig),
            this.renderFilteredBuffer(audioBuffer, highConfig)
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

        // Merge channels to mono for peak calculation
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
     * Pre-computes peaks for each frequency band at the given resolution.
     * 
     * @param {AudioBuffer} audioBuffer - Source audio buffer
     * @param {number} samplesPerPixel - Samples per display pixel
     * @param {Function} [onProgress] - Progress callback (0-1)
     * @returns {Promise<{low: Array, mid: Array, high: Array}>}
     */
    static async generateBandPeaks(audioBuffer, samplesPerPixel, onProgress = null) {
        if (onProgress) onProgress(0);

        // Split into bands
        const { low, mid, high } = await this.splitBands(audioBuffer);
        if (onProgress) onProgress(0.5);

        // Generate peaks for each band
        const lowPeaks = this.generatePeaks(low, samplesPerPixel);
        const midPeaks = this.generatePeaks(mid, samplesPerPixel);
        const highPeaks = this.generatePeaks(high, samplesPerPixel);

        if (onProgress) onProgress(1.0);

        return { low: lowPeaks, mid: midPeaks, high: highPeaks };
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

        return new Blob([arrayBuffer], { type: "audio/wav" });
    }
}

export default AudioBandAnalyzer;
