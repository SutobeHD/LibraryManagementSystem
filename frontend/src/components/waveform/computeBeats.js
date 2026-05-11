// Builds the beat array used for grid rendering + snap-to-grid. Respects per-segment BPM
// changes encoded in beatGrid; falls back to even spacing when no grid exists.
export default function computeBeats(beatGrid, bpm, duration) {
    if (!duration || !bpm) return [];
    const result = [];

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
}
