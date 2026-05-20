import { useState, useEffect, useRef } from 'react';
import { Play, Pause, SkipBack, SkipForward, Volume2, X } from 'lucide-react';
import api from '../api/api';
import { log } from '../utils/log';
import { waveAmps, drawSeededWave, hashSeed } from './shared/seededWaveform';

/** Three staggered equalizer bars — shown next to the title while playing. */
const PlayingBars = () => (
    <span className="flex items-end gap-[1.5px] h-3 shrink-0">
        {[5, 11, 4].map((h, i) => (
            <span
                key={i}
                className="w-[2.5px] rounded-[1px] bg-ok"
                style={{
                    height: h,
                    transformOrigin: 'bottom',
                    animation: `barBounce 0.9s ${i * 0.15}s ease-in-out infinite alternate`,
                }}
            />
        ))}
    </span>
);

/** Amber mirror-bar waveform scrubber — resizes with its container, click + drag to seek. */
const SeededWaveform = ({ seed, playhead, onSeek }) => {
    const canvasRef = useRef(null);
    const draggingRef = useRef(false);
    const playheadRef = useRef(playhead);
    const amps = waveAmps(typeof seed === 'number' ? seed : hashSeed(seed));
    playheadRef.current = playhead;

    useEffect(() => {
        if (canvasRef.current) drawSeededWave(canvasRef.current, amps, playhead, 28);
    }, [amps, playhead]);

    useEffect(() => {
        const canvas = canvasRef.current;
        const parent = canvas?.parentElement;
        if (!parent) return undefined;
        const ro = new ResizeObserver(() =>
            drawSeededWave(canvas, amps, playheadRef.current, 28),
        );
        ro.observe(parent);
        return () => ro.disconnect();
    }, [amps]);

    const seekFromEvent = (e) => {
        const rect = e.currentTarget.getBoundingClientRect();
        onSeek(Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width)));
    };
    const onPointerDown = (e) => {
        draggingRef.current = true;
        try {
            e.currentTarget.setPointerCapture(e.pointerId);
        } catch {
            /* setPointerCapture unsupported — click-seek still works */
        }
        seekFromEvent(e);
    };
    const onPointerMove = (e) => {
        if (draggingRef.current) seekFromEvent(e);
    };
    const onPointerUp = (e) => {
        draggingRef.current = false;
        try {
            e.currentTarget.releasePointerCapture(e.pointerId);
        } catch {
            /* no capture to release */
        }
    };

    return (
        <div
            className="bg-mx-deepest rounded-mx-xs overflow-hidden cursor-pointer"
            style={{ height: 28 }}
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
        >
            <canvas ref={canvasRef} style={{ display: 'block', width: '100%', height: 28 }} />
        </div>
    );
};

const Player = ({ track, onClose }) => {
    const [playing, setPlaying] = useState(false);
    const [volume, setVolumeState] = useState(() => {
        const saved = localStorage.getItem('rb_volume');
        return saved !== null ? parseFloat(saved) : 1.0;
    });
    const setVolume = (v) => {
        setVolumeState(v);
        localStorage.setItem('rb_volume', String(v));
    };
    const [progress, setProgress] = useState(0);
    const [duration, setDuration] = useState(0);
    const audioRef = useRef(null);

    const isStreaming = (t) => {
        const path = t?.path || t?.Path || '';
        return (
            path.startsWith('soundcloud:') ||
            path.startsWith('spotify:') ||
            path.startsWith('tidal:') ||
            path.startsWith('beatport:')
        );
    };

    useEffect(() => {
        if (track) {
            setPlaying(!isStreaming(track));
            setProgress(0);
        }
    }, [track]);

    useEffect(() => {
        if (audioRef.current && !isStreaming(track)) {
            playing
                ? audioRef.current.play().catch((e) => log.warn('Play error', e))
                : audioRef.current.pause();
        }
    }, [playing, track]);

    useEffect(() => {
        if (audioRef.current) {
            audioRef.current.volume = volume;
        }
    }, [volume]);

    const handleTimeUpdate = () => {
        if (audioRef.current) {
            setProgress(audioRef.current.currentTime);
            const d = audioRef.current.duration;
            if (Number.isFinite(d) && d > 0) {
                setDuration(d);
            }
        }
    };

    const handleLoadedMeta = () => {
        if (audioRef.current) {
            const d = audioRef.current.duration;
            if (Number.isFinite(d) && d > 0) setDuration(d);
            else if (track?.TotalTime) setDuration(parseFloat(track.TotalTime) || 0);
        }
    };

    const seekTo = (ratio) => {
        if (!audioRef.current) return;
        const d = audioRef.current.duration;
        // Fallback: track metadata duration (HTML5 audio sometimes reports Infinity for chunked streams)
        const safeDuration =
            Number.isFinite(d) && d > 0
                ? d
                : parseFloat(track?.TotalTime) || duration || 0;
        if (!safeDuration) return;
        const target = Math.max(0, Math.min(1, ratio)) * safeDuration;
        try {
            audioRef.current.currentTime = target;
            setProgress(target);
        } catch (e) {
            log.warn('Seek failed', e);
        }
    };

    const formatTime = (t) => {
        if (!t) return '0:00';
        const m = Math.floor(t / 60);
        const s = Math.floor(t % 60);
        return `${m}:${s.toString().padStart(2, '0')}`;
    };

    if (!track) return null;

    const streaming = isStreaming(track);
    const playhead = duration > 0 ? Math.min(1, progress / duration) : 0;
    const waveSeed =
        track.id ?? track.TrackID ?? track.Path ?? track.path ?? track.Title ?? 'track';

    return (
        <div
            className="flex items-center px-5 fixed bottom-0 right-0 z-50 animate-slide-up shadow-mx-lg gap-4"
            style={{
                height: 72,
                left: 220,
                background: 'var(--mx-panel)',
                borderTop: '1px solid var(--line-subtle)',
            }}
        >
            {!streaming && (
                <audio
                    ref={audioRef}
                    src={`${api.defaults.baseURL}/api/stream?path=${encodeURIComponent(track.path || track.Path)}`}
                    onTimeUpdate={handleTimeUpdate}
                    onLoadedMetadata={handleLoadedMeta}
                    onDurationChange={handleLoadedMeta}
                    onEnded={() => setPlaying(false)}
                    preload="metadata"
                />
            )}

            {/* Track info */}
            <div className="flex items-center gap-2.5 flex-shrink-0" style={{ flexBasis: 230, minWidth: 0 }}>
                <div
                    className="w-11 h-11 rounded-mx-sm overflow-hidden shrink-0 relative"
                    style={{ background: 'var(--mx-card)', border: '1px solid var(--line-subtle)' }}
                >
                    {track.Artwork ? (
                        <img src={`${api.defaults.baseURL}/api/artwork?path=${encodeURIComponent(track.Artwork)}`} className="w-full h-full object-cover" loading="lazy" />
                    ) : (
                        <div className="w-full h-full flex items-center justify-center text-ink-muted text-[10px] font-semibold tracking-wider">RB</div>
                    )}
                    {streaming && (
                        <div className="absolute inset-0 bg-black/60 flex items-center justify-center">
                            <div className="bg-amber2 w-1.5 h-1.5 rounded-full animate-pulse"></div>
                        </div>
                    )}
                </div>
                <div className="flex flex-col overflow-hidden min-w-0">
                    <span className="text-[13px] font-medium text-ink-primary truncate flex items-center gap-1.5">
                        <span className="truncate">{track.Title || 'Unknown Title'}</span>
                        {playing && !streaming && <PlayingBars />}
                    </span>
                    <span className="text-[11px] text-ink-muted truncate mt-0.5">
                        {streaming
                            ? <span className="text-amber2">Streaming restricted</span>
                            : (track.Artist || 'Unknown Artist')}
                    </span>
                </div>
            </div>

            {/* Transport */}
            <div className="flex items-center gap-1 flex-shrink-0">
                <button
                    className="p-1.5 rounded-mx-sm text-ink-secondary hover:text-ink-primary hover:bg-mx-hover transition-colors disabled:opacity-20"
                    disabled={streaming}
                ><SkipBack size={16} /></button>
                <button
                    onClick={() => !streaming && setPlaying(!playing)}
                    disabled={streaming}
                    className={`w-9 h-9 rounded-full flex items-center justify-center transition-all ${
                        streaming ? 'bg-mx-card text-ink-muted' : 'bg-amber2 text-mx-deepest hover:bg-amber2-hover'
                    }`}
                >
                    {playing && !streaming
                        ? <Pause size={16} fill="currentColor" />
                        : <Play size={16} fill="currentColor" className="ml-0.5" />}
                </button>
                <button
                    className="p-1.5 rounded-mx-sm text-ink-secondary hover:text-ink-primary hover:bg-mx-hover transition-colors disabled:opacity-20"
                    disabled={streaming}
                ><SkipForward size={16} /></button>
            </div>

            {/* Waveform scrubber */}
            <div className="flex-1 flex flex-col gap-1.5 min-w-0">
                {streaming ? (
                    <div className="text-center mx-caption" style={{ color: 'var(--ink-placeholder)' }}>
                        Direct streaming for cloud/subscription tracks not supported
                    </div>
                ) : (
                    <>
                        <div className="flex items-center justify-between">
                            <span className="font-mono text-[10px] font-semibold" style={{ color: 'var(--amber)' }}>{formatTime(progress)}</span>
                            {(track.BPM || track.Key) && (
                                <span className="mx-chip mx-chip-amber font-mono">
                                    {track.BPM && `${Math.round(track.BPM)} BPM`}{track.BPM && track.Key && ' · '}{track.Key}
                                </span>
                            )}
                            <span className="font-mono text-[10px] text-ink-muted">{formatTime(duration)}</span>
                        </div>
                        <SeededWaveform seed={waveSeed} playhead={playhead} onSeek={seekTo} />
                    </>
                )}
            </div>

            {/* Volume + close */}
            <div className="flex items-center gap-2 flex-shrink-0">
                <Volume2 size={14} className="text-ink-muted" />
                <input
                    type="range" min="0" max="1" step="0.01"
                    value={volume}
                    onChange={(e) => setVolume(parseFloat(e.target.value))}
                    className="appearance-none cursor-pointer outline-none [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-2.5 [&::-webkit-slider-thumb]:h-2.5 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-ink-primary"
                    style={{
                        width: 72,
                        height: 3,
                        borderRadius: 2,
                        background: `linear-gradient(to right, var(--ink-secondary) 0%, var(--ink-secondary) ${volume * 100}%, var(--line-subtle) ${volume * 100}%, var(--line-subtle) 100%)`,
                    }}
                />
                <button
                    onClick={() => {
                        setPlaying(false);
                        if (audioRef.current) audioRef.current.pause();
                        onClose();
                    }}
                    className="p-1.5 rounded-mx-sm text-ink-muted hover:text-ink-primary hover:bg-mx-hover transition-colors ml-2"
                    title="Close player"
                >
                    <X size={14} />
                </button>
            </div>
        </div>
    );
};

export default Player;
