import React, { useState, useEffect, useRef } from 'react';
import { Play, Pause, SkipBack, SkipForward, Volume2, Maximize2, X } from 'lucide-react';
import api from '../api/api';
import { log } from '../utils/log';

const Player = ({ track, onClose, onMaximize }) => {
    const [playing, setPlaying] = useState(false);
    const [volume, setVolumeState] = useState(() => {
        const saved = localStorage.getItem('rb_volume');
        return saved !== null ? parseFloat(saved) : 1.0;
    });
    const setVolume = (v) => { setVolumeState(v); localStorage.setItem('rb_volume', String(v)); };
    const [progress, setProgress] = useState(0);
    const [duration, setDuration] = useState(0);
    const audioRef = useRef(null);

    useEffect(() => {
        if (track) {
            setPlaying(!isStreaming(track));
            setProgress(0);
        }
    }, [track]);

    const isStreaming = (t) => {
        const path = t.path || t.Path || '';
        return path.startsWith('soundcloud:') || path.startsWith('spotify:') || path.startsWith('tidal:') || path.startsWith('beatport:');
    };

    useEffect(() => {
        if (audioRef.current && !isStreaming(track)) {
            playing ? audioRef.current.play().catch(e => log.warn("Play error", e)) : audioRef.current.pause();
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
        const safeDuration = Number.isFinite(d) && d > 0
            ? d
            : (parseFloat(track?.TotalTime) || duration || 0);
        if (!safeDuration) return;
        const target = Math.max(0, Math.min(1, ratio)) * safeDuration;
        try {
            audioRef.current.currentTime = target;
            setProgress(target);
        } catch (e) {
            console.warn("Seek failed:", e);
        }
    };

    const formatTime = (t) => {
        if (!t) return "0:00";
        const m = Math.floor(t / 60);
        const s = Math.floor(t % 60);
        return `${m}:${s.toString().padStart(2, '0')}`;
    };

    if (!track) return null;

    const streaming = isStreaming(track);

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
                    <span className="text-[13px] font-medium text-ink-primary truncate">{track.Title || 'Unknown Title'}</span>
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

            {/* Progress */}
            <div className="flex-1 flex flex-col gap-1.5 min-w-0">
                {streaming ? (
                    <div className="text-center mx-caption" style={{ color: 'var(--ink-placeholder)' }}>
                        Direct streaming for Cloud/Subscription tracks not supported
                    </div>
                ) : (
                    <>
                        <div className="flex items-center justify-between">
                            <span className="font-mono text-[10px]" style={{ color: 'var(--amber)' }}>{formatTime(progress)}</span>
                            {(track.BPM || track.Key) && (
                                <span className="mx-chip mx-chip-amber font-mono">
                                    {track.BPM && `${Math.round(track.BPM)} BPM`}{track.BPM && track.Key && ' · '}{track.Key}
                                </span>
                            )}
                            <span className="font-mono text-[10px] text-ink-muted">{formatTime(duration)}</span>
                        </div>
                        <div
                            className="py-2 -my-2 cursor-pointer relative group"
                            onClick={(e) => {
                                if (streaming) return;
                                const rect = e.currentTarget.getBoundingClientRect();
                                seekTo((e.clientX - rect.left) / rect.width);
                            }}
                            onMouseDown={(e) => {
                                if (streaming) return;
                                const rect = e.currentTarget.getBoundingClientRect();
                                const onMove = (ev) => seekTo((ev.clientX - rect.left) / rect.width);
                                const onUp = () => {
                                    document.removeEventListener('mousemove', onMove);
                                    document.removeEventListener('mouseup', onUp);
                                };
                                document.addEventListener('mousemove', onMove);
                                document.addEventListener('mouseup', onUp);
                            }}
                        ><div
                            className="h-[3px] rounded-full relative pointer-events-none"
                            style={{ background: 'var(--line-subtle)' }}
                        >
                            <div
                                className="absolute inset-y-0 left-0 bg-amber2 rounded-full"
                                style={{ width: `${duration ? (progress / duration) * 100 : 0}%` }}
                            >
                                <div
                                    className="absolute right-0 top-1/2 -translate-y-1/2 w-2.5 h-2.5 rounded-full bg-amber2 opacity-0 group-hover:opacity-100 transition-opacity"
                                    style={{ boxShadow: '0 0 6px var(--amber-glow)' }}
                                />
                            </div>
                        </div>
                        </div>
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
