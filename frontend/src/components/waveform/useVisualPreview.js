import { useCallback, useEffect, useRef } from 'react';
import { buildPreviewBuffer, bufferToWave } from './previewBuffer';

// Debounced non-destructive preview rebuild — whenever cuts change, splice the AudioBuffer
// and reload the master WaveSurfer with the spliced version. Skips when bufferReady is false
// (avoids tearing the ready event on first load).
export default function useVisualPreview({
    wavesurfer,
    originalBufferRef,
    isMountedRef,
    blobUrl,
    fullTrack,
    duration,
    bufferReady,
    cuts,
    trackBlobUrl,
    toast,
}) {
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

        toast.info('Updating Waveform...');
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
            console.error('Preview Gen Failed', e);
            toast.error('Visual Preview Failed');
        }
    }, [blobUrl, fullTrack?.path, duration, toast, trackBlobUrl, wavesurfer, originalBufferRef, isMountedRef]);

    // Debounced preview rebuild — runs whenever cuts change (handleInsert/Delete/Paste/Clear/Undo)
    // 300ms debounce avoids rebuilding on every rapid edit
    useEffect(() => {
        if (!bufferReady) return;
        const t = setTimeout(() => updateVisualPreview(cuts), 300);
        return () => clearTimeout(t);
    }, [cuts, bufferReady, updateVisualPreview]);
}
