
/**
 * AudioBandAnalyzer
 * Splits an AudioBuffer into 3 frequency bands (Rekordbox-style):
 * - Low: < 400 Hz  (Bass / Kick / Punch)
 * - Mid: 400 Hz - 2000 Hz  (Vocals / Instruments)
 * - High: > 2000 Hz (Cymbals / Hi-Hats / Air)
 * 
 * Uses OfflineAudioContext for fast rendering.
 */
class AudioBandAnalyzer {
    /**
     * Splits audio buffer into 3 bands.
     * @param {AudioBuffer} audioBuffer 
     * @returns {Promise<{low: AudioBuffer, mid: AudioBuffer, high: AudioBuffer}>}
     */
    static async splitBands(audioBuffer) {
        if (!audioBuffer) throw new Error("No buffer provided");

        // Frequency boundaries: Low < 400Hz, Mid 400 - 2000Hz, High > 2000Hz
        // High cutoff set to 2000Hz per user request for more visible highs.
        const lowConfig = [{ type: 'lowpass', freq: 400 }];
        const midConfig = [
            { type: 'highpass', freq: 400 },
            { type: 'lowpass', freq: 2000 }
        ];
        const highConfig = [{ type: 'highpass', freq: 2000 }];

        // Run 3 parallel renderings
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
     * Converts AudioBuffer to WAV Blob
     * @param {AudioBuffer} buffer 
     * @returns {Blob}
     */
    static bufferToWav(buffer) {
        const numOfChan = buffer.numberOfChannels;
        const length = buffer.length * numOfChan * 2 + 44;
        const bufferArr = new ArrayBuffer(length);
        const view = new DataView(bufferArr);
        const channels = [];
        let i;
        let sample;
        let offset = 0;
        let pos = 0;

        // write RIFF chunk
        setUint32(0x46464952); // "RIFF"
        setUint32(length - 8); // file length - 8
        setUint32(0x45564157); // "WAVE"

        // write fmt chunk
        setUint32(0x20746d66); // "fmt "
        setUint32(16); // length = 16
        setUint16(1); // PCM (uncompressed)
        setUint16(numOfChan);
        setUint32(buffer.sampleRate);
        setUint32(buffer.sampleRate * 2 * numOfChan); // avg. bytes/sec
        setUint16(numOfChan * 2); // block-align
        setUint16(16); // 16-bit

        // write data chunk
        setUint32(0x61746164); // "data"
        setUint32(length - pos - 4); // chunk length

        // write interleaved data
        for (i = 0; i < buffer.numberOfChannels; i++)
            channels.push(buffer.getChannelData(i));

        while (pos < length) {
            for (i = 0; i < numOfChan; i++) {
                sample = Math.max(-1, Math.min(1, channels[i][offset]));
                sample = (0.5 + sample < 0 ? sample * 32768 : sample * 32767) | 0;
                view.setInt16(44 + offset * numOfChan * 2 + i * 2, sample, true);
            }
            offset++;
            pos += numOfChan * 2; // Should track bytes written?
        }
        // Logic above is slightly mixed. 
        // Correct implementation:

        let writeOffset = 44;
        for (let j = 0; j < buffer.length; j++) {
            for (let ch = 0; ch < numOfChan; ch++) {
                let s = channels[ch][j];
                s = Math.max(-1, Math.min(1, s));
                s = s < 0 ? s * 0x8000 : s * 0x7FFF;
                view.setInt16(writeOffset, s, true);
                writeOffset += 2;
            }
        }

        return new Blob([bufferArr], { type: "audio/wav" });

        function setUint16(data) { view.setUint16(pos, data, true); pos += 2; }
        function setUint32(data) { view.setUint32(pos, data, true); pos += 4; }
    }
}

export default AudioBandAnalyzer;
