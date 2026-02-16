import React, { useState, useEffect, useRef } from 'react';
import { Play, Pause, SkipBack, SkipForward, Volume2, Maximize2, X } from 'lucide-react';
import api from '../api/api';

const Player = ({ track, onClose, onMaximize }) => {
    const [playing, setPlaying] = useState(false);
    const [volume, setVolume] = useState(1.0);
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
            playing ? audioRef.current.play().catch(e => console.log("Play error", e)) : audioRef.current.pause();
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
            setDuration(audioRef.current.duration || 0);
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
        <div className="h-20 bg-slate-950/90 border-t border-white/10 backdrop-blur-xl flex items-center px-4 fixed bottom-0 left-72 right-0 z-50 animate-slide-up shadow-2xl">
            {!streaming && (
                <audio
                    ref={audioRef}
                    src={`${api.defaults.baseURL}/api/stream?path=${encodeURIComponent(track.path || track.Path)}`}
                    onTimeUpdate={handleTimeUpdate}
                    onEnded={() => setPlaying(false)}
                />
            )}

            {/* Track Info */}
            <div className="flex items-center gap-4 w-1/4 min-w-[200px]">
                <div className="w-14 h-14 bg-slate-800 rounded-full shadow-lg overflow-hidden shrink-0 border border-white/5 relative group">
                    {track.Artwork ? (
                        <img src={`${api.defaults.baseURL}/api/artwork?path=${encodeURIComponent(track.Artwork)}`} className="w-full h-full object-cover" />
                    ) : (
                        <div className="w-full h-full flex items-center justify-center bg-gradient-to-br from-cyan-900 to-blue-900">
                            <span className="text-xs font-bold text-white/50">RB</span>
                        </div>
                    )}
                    {streaming && (
                        <div className="absolute inset-0 bg-black/60 flex items-center justify-center">
                            <div className="bg-amber-500 w-2 h-2 rounded-full animate-pulse"></div>
                        </div>
                    )}
                </div>
                <div className="flex flex-col overflow-hidden">
                    <span className="text-sm font-bold text-white truncate">{track.Title || 'Unknown Title'}</span>
                    <span className="text-xs text-slate-400 truncate">
                        {streaming ? (
                            <span className="text-amber-400 font-medium">Streaming Restricted</span>
                        ) : (
                            track.Artist || 'Unknown Artist'
                        )}
                    </span>
                </div>
            </div>

            {/* Controls */}
            <div className="flex-1 flex flex-col items-center justify-center gap-2">
                <div className="flex items-center gap-6">
                    <button className="text-slate-400 hover:text-white transition-colors disabled:opacity-20" disabled={streaming}><SkipBack size={20} /></button>
                    <button
                        onClick={() => !streaming && setPlaying(!playing)}
                        disabled={streaming}
                        className={`w-10 h-10 rounded-full flex items-center justify-center transition-all shadow-lg ${streaming ? 'bg-slate-800 text-slate-600' : 'bg-white text-black hover:scale-105 shadow-white/10'}`}
                    >
                        {playing && !streaming ? <Pause size={20} fill="currentColor" /> : <Play size={20} fill="currentColor" className="ml-0.5" />}
                    </button>
                    <button className="text-slate-400 hover:text-white transition-colors disabled:opacity-20" disabled={streaming}><SkipForward size={20} /></button>
                </div>
                <div className="w-full max-w-md flex items-center gap-3 text-xs font-mono text-slate-500">
                    {streaming ? (
                        <div className="flex-1 text-center text-[10px] text-slate-600 uppercase tracking-widest">
                            Direct streaming for Cloud/Subscription tracks not supported
                        </div>
                    ) : (
                        <>
                            <span>{formatTime(progress)}</span>
                            <div
                                className="flex-1 h-1 bg-slate-800 rounded-full cursor-pointer relative group"
                                onClick={(e) => {
                                    if (streaming) return;
                                    const rect = e.currentTarget.getBoundingClientRect();
                                    const p = (e.clientX - rect.left) / rect.width;
                                    audioRef.current.currentTime = p * audioRef.current.duration;
                                }}
                            >
                                <div className="absolute inset-y-0 left-0 bg-cyan-500 rounded-full group-hover:bg-cyan-400" style={{ width: `${(progress / duration) * 100}%` }}></div>
                            </div>
                            <span>{formatTime(duration)}</span>
                        </>
                    )}
                </div>
            </div>

            {/* Volume & More */}
            <div className="w-1/4 flex items-center justify-end gap-4 min-w-[200px]">
                <div className="flex items-center gap-2 group">
                    <Volume2 size={18} className="text-slate-400" />
                    <input
                        type="range" min="0" max="1" step="0.01"
                        value={volume}
                        onChange={(e) => setVolume(parseFloat(e.target.value))}
                        className="w-24 h-1 bg-slate-800 rounded-lg appearance-none cursor-pointer [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-3 [&::-webkit-slider-thumb]:h-3 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-white"
                    />
                </div>
                <button
                    onClick={() => {
                        setPlaying(false);
                        if (audioRef.current) audioRef.current.pause();
                        onClose();
                    }}
                    className="text-slate-400 hover:text-white transition-colors p-2 hover:bg-white/10 rounded-full"
                    title="Close Player"
                >
                    <X size={18} />
                </button>
            </div>
        </div>
    );
};

export default Player;
