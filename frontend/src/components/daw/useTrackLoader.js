/**
 * useTrackLoader — Effect hook that hydrates DAW state when activeTrack changes.
 *
 * Decodes audio, builds the tempo map, creates an initial region spanning the
 * full track, then generates waveform peaks (preferring the backend 3-band
 * Butterworth waveform, falling back to client-side BiquadFilter LOD).
 *
 * Skips the auto-load entirely when `skipNextAutoLoad.current === true` — that
 * flag is set by useDawProject.handleFileSelect after a .rbep open so the
 * 9 parsed edit regions aren't overwritten by a single default region.
 */
import { useEffect } from 'react';
import toast from 'react-hot-toast';

import * as DawEngine from '../../audio/DawEngine';
import { buildTempoMap } from '../../audio/RbepSerializer';
import AudioBandAnalyzer from '../../utils/AudioBandAnalyzer';
import api from '../../api/api';
import { log } from '../../utils/log';

/**
 * Convert backend waveform data ({low, mid, high} float arrays 0-1)
 * into the {min, max} peak format that DawTimeline expects.
 * Backend Butterworth 4th-order filters produce higher quality than
 * client-side BiquadFilter.
 */
function convertBackendWaveform(data) {
    const toPeaks = (arr) =>
        arr.map(v => ({ min: -Math.abs(v), max: Math.abs(v) }));

    return {
        low:  toPeaks(data.low),
        mid:  toPeaks(data.mid),
        high: toPeaks(data.high),
    };
}

export default function useTrackLoader({ activeTrack, dispatch, skipNextAutoLoad, hasInitialized }) {
    useEffect(() => {
        if (!activeTrack) return;

        // Skip auto-load if the track was just hydrated from a .rbep project file.
        // handleFileSelect has already loaded the audio, parsed 9 edit regions, and
        // dispatched HYDRATE — running loadTrack() here would overwrite those regions
        // with a single default full-track region, making the export equal the original.
        if (skipNextAutoLoad.current) {
            skipNextAutoLoad.current = false;
            log.debug('[DjEditDaw] Skipping auto-load — regions already hydrated from .rbep');
            return;
        }

        const loadTrack = async () => {
            try {
                DawEngine.getAudioContext();

                const track = activeTrack;
                // /api/library/tracks returns rekordbox tracks with `path`
                // (lowercase). Older .rbep paths used `FilePath`/`filepath`/
                // `Location`. Try all four so library-list double-clicks
                // actually load instead of silently warning.
                const filepath = track.FilePath || track.filepath || track.Location || track.path;
                if (!filepath) {
                    console.warn('[DjEditDaw] No filepath on track:', track);
                    return;
                }

                // Set track metadata
                dispatch({
                    type: 'SET_TRACK_META',
                    payload: {
                        title: track.Title || track.title || '',
                        artist: track.Artist || track.artist || '',
                        album: track.Album || track.album || '',
                        filepath,
                        id: track.TrackID || track.ID || track.id || '',
                    }
                });

                dispatch({
                    type: 'SET_PROJECT',
                    payload: {
                        name: `${track.Title || track.title || 'Untitled'} (Edit)`,
                        filepath: '',
                        dirty: false,
                    }
                });

                // Load and decode audio
                toast.loading('Loading audio...', { id: 'daw-load' });
                const audioBuffer = await DawEngine.loadAudio(filepath);

                dispatch({ type: 'SET_SOURCE_BUFFER', payload: { buffer: audioBuffer } });

                // Set BPM and build tempo map
                const bpm = track.BPM || track.bpm || 128;
                dispatch({ type: 'SET_BPM', payload: bpm });

                const firstBeatMs = track.firstBeatMs || 0;
                const tempoMap = buildTempoMap(bpm, firstBeatMs, audioBuffer.duration * 1000);
                dispatch({ type: 'SET_TEMPO_MAP', payload: tempoMap });

                // Create initial region (entire track)
                const initialRegion = {
                    id: crypto.randomUUID(),
                    sourceFile: filepath,
                    sourceStart: 0,
                    sourceEnd: audioBuffer.duration,
                    sourceDuration: audioBuffer.duration,
                    timelineStart: 0,
                    timelineEnd: audioBuffer.duration,
                    duration: audioBuffer.duration,
                };
                dispatch({ type: 'SET_REGIONS', payload: [initialRegion] });

                // Generate waveform peaks for visualization
                toast.loading('Analyzing waveform...', { id: 'daw-load' });

                // Peak resolution targets — base count of `targetPeaks` peaks
                // across the full source audio. 16 000 ≈ 40 peaks/sec for a
                // 400s track — 4× the previous 4 000 base while still
                // generating in <5s in a browser via Web Audio OfflineContext.
                // 32k was tried but the BiquadFilter offline rendering of 3
                // band chains over a 408s buffer (~18M samples * 3) hung the
                // main thread for too long. The LOD pyramid below decimates
                // this base into r2/r4 for zoomed-out views.
                const targetPeaks   = 16000;
                const samplesPerPixel = Math.ceil(audioBuffer.length / targetPeaks);

                // 1. Always generate mono fallback peaks first (instant, guaranteed)
                try {
                    const fallback = AudioBandAnalyzer.generatePeaks(audioBuffer, samplesPerPixel);
                    dispatch({ type: 'SET_FALLBACK_PEAKS', payload: fallback });
                } catch (err) {
                    console.warn('[DjEditDaw] Fallback peaks failed:', err);
                }

                // 2. Try backend 3-band waveform (Butterworth, Rekordbox-quality)
                let usedBackendWaveform = false;
                try {
                    // pps (peaks-per-second) — derived from targetPeaks so
                    // backend matches client-side resolution.
                    const pps = Math.max(30, Math.ceil(targetPeaks / audioBuffer.duration));
                    const resp = await api.get('/api/audio/waveform', {
                        params: { path: filepath, pps },
                        timeout: 15000,
                    });
                    if (resp.data?.low?.length > 0) {
                        const bandPeaks = convertBackendWaveform(resp.data);
                        // Backend returns single-resolution arrays — wrap into
                        // LOD shape so the renderer's LOD-aware code path
                        // (r1/r2/r4) works. We synthesise r2/r4 by decimating
                        // r1 client-side.
                        bandPeaks.lod = {
                            r1: { low: bandPeaks.low, mid: bandPeaks.mid, high: bandPeaks.high },
                            r2: {
                                low:  AudioBandAnalyzer._decimatePeaks(bandPeaks.low,  2),
                                mid:  AudioBandAnalyzer._decimatePeaks(bandPeaks.mid,  2),
                                high: AudioBandAnalyzer._decimatePeaks(bandPeaks.high, 2),
                            },
                            r4: {
                                low:  AudioBandAnalyzer._decimatePeaks(bandPeaks.low,  4),
                                mid:  AudioBandAnalyzer._decimatePeaks(bandPeaks.mid,  4),
                                high: AudioBandAnalyzer._decimatePeaks(bandPeaks.high, 4),
                            },
                        };
                        dispatch({ type: 'SET_BAND_PEAKS', payload: bandPeaks });
                        usedBackendWaveform = true;
                    }
                } catch (err) {
                    console.warn('[DjEditDaw] Backend waveform unavailable, falling back to client-side:', err.message);
                }

                // 3. Fallback: client-side band splitting with multi-resolution
                // LOD (BiquadFilter — less accurate than backend Butterworth
                // but always available). Returns { low, mid, high, mono, lod }.
                if (!usedBackendWaveform) {
                    try {
                        const bandPeaks = await AudioBandAnalyzer.generateMultiResolutionPeaks(
                            audioBuffer,
                            samplesPerPixel,
                        );
                        dispatch({ type: 'SET_BAND_PEAKS', payload: bandPeaks });
                    } catch (err) {
                        console.warn('[DjEditDaw] Band peaks failed, using mono fallback:', err);
                    }
                }

                toast.success('Track loaded', { id: 'daw-load' });
                hasInitialized.current = true;

            } catch (err) {
                console.error('[DjEditDaw] Load failed:', err);
                toast.error(`Failed to load: ${err.message}`, { id: 'daw-load' });
            }
        };

        loadTrack();
    }, [activeTrack]);
}
