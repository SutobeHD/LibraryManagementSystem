/**
 * ExportModal — Project Export UI
 *
 * Features:
 * - Metadata preview (title, artist, BPM, duration)
 * - Output path selection via Tauri file dialog
 * - Format selector (WAV / MP3 320kbps / FLAC)
 * - Normalization toggle
 * - Progress bar wired to Tauri event 'export-progress'
 * - Success/error states
 * - Graceful fallback to browser-side WAV download when Tauri unavailable
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { X, FolderOpen, Music, CheckCircle2, AlertCircle, Download, Loader2 } from 'lucide-react';
import * as DawEngine from '../../audio/DawEngine';
import AudioBandAnalyzer from '../../utils/AudioBandAnalyzer';

// ─── TAURI DYNAMIC IMPORTS (graceful fallback if not in Tauri context) ──────────

async function tauriInvoke(cmd, args) {
    try {
        const { invoke } = await import('@tauri-apps/api/core');
        return await invoke(cmd, args);
    } catch {
        return null; // fallback to web mode
    }
}

async function tauriListen(event, cb) {
    try {
        const { listen } = await import('@tauri-apps/api/event');
        return await listen(event, cb);
    } catch {
        return () => {}; // noop unlisten
    }
}

// ─── CONSTANTS ───────────────────────────────────────────────────────────────────

const FORMATS = [
    { id: 'wav',  label: 'WAV',      sub: '16-bit PCM · Lossless' },
    { id: 'mp3',  label: 'MP3 320',  sub: '320 kbps · Small' },
    { id: 'flac', label: 'FLAC',     sub: '24-bit · Lossless+' },
];

// ─── COMPONENT ───────────────────────────────────────────────────────────────────

const ExportModal = React.memo(({ state, onClose }) => {
    const [outputPath,  setOutputPath]  = useState('');
    const [format,      setFormat]      = useState('wav');
    const [normalize,   setNormalize]   = useState(false);
    const [phase,       setPhase]       = useState('idle'); // idle | exporting | done | error
    const [progress,    setProgress]    = useState(0);
    const [errorMsg,    setErrorMsg]    = useState('');
    const unlistenRef   = useRef(null);

    // Subscribe to Tauri export events
    useEffect(() => {
        let aliveProgress = true;
        let aliveComplete = true;
        let aliveError    = true;

        (async () => {
            unlistenRef.current = [
                await tauriListen('export-progress', (ev) => {
                    if (aliveProgress) setProgress(Math.round((ev.payload ?? 0) * 100));
                }),
                await tauriListen('export-complete', () => {
                    if (aliveComplete) { setPhase('done'); setProgress(100); }
                }),
                await tauriListen('export-error', (ev) => {
                    if (aliveError) { setPhase('error'); setErrorMsg(ev.payload ?? 'Unknown error'); }
                }),
            ];
        })();

        return () => {
            aliveProgress = false; aliveComplete = false; aliveError = false;
            unlistenRef.current?.forEach(u => u && u());
        };
    }, []);

    // ── Browse for output folder ──
    const handleBrowse = useCallback(async () => {
        const dir = await tauriInvoke('open_file_dialog', { directory: true, title: 'Select export folder' });
        if (dir) {
            const safeName = (state.trackTitle || 'export').replace(/[<>:"/\\|?*]/g, '_');
            setOutputPath(`${dir}/${safeName}.${format}`);
        }
    }, [state.trackTitle, format]);

    // Update extension in path when format changes
    useEffect(() => {
        if (!outputPath) return;
        setOutputPath(p => p.replace(/\.(wav|mp3|flac)$/, `.${format}`));
    }, [format]);

    // ── Start Export ──
    const handleExport = useCallback(async () => {
        setPhase('exporting');
        setProgress(0);
        setErrorMsg('');

        const trackMeta = {
            title:    state.trackTitle   || 'Untitled',
            artist:   state.trackArtist  || 'Unknown',
            bpm:      state.bpm,
            key:      state.trackKey     || '',
        };

        // Try Tauri first
        const tauriResult = await tauriInvoke('export_project', {
            path:      outputPath || undefined,
            format,
            normalize,
            regions:   state.regions,
            trackMeta,
        });

        if (tauriResult !== null) {
            // Tauri command returned — wait for event to set done
            return;
        }

        // ── Fallback: browser-side WAV download ──
        try {
            if (!state.sourceBuffer || !state.regions?.length) {
                throw new Error('No audio data to export');
            }

            setProgress(10);
            const rendered = await DawEngine.renderTimeline(
                state.regions,
                state.sourceBuffer,
                state.sourceBuffer.sampleRate,
                (p) => setProgress(Math.round(10 + p * 88))
            );

            setProgress(98);
            const wav  = DawEngine.audioBufferToWav(rendered);
            const url  = URL.createObjectURL(wav);
            const link = document.createElement('a');
            link.href     = url;
            link.download = `${trackMeta.title}.wav`;
            link.click();
            setTimeout(() => URL.revokeObjectURL(url), 5000);

            setProgress(100);
            setPhase('done');
        } catch (err) {
            setPhase('error');
            setErrorMsg(err.message || String(err));
        }
    }, [outputPath, format, normalize, state]);

    // ── Formatted duration ──
    const durStr = (() => {
        const d = state.totalDuration || 0;
        const m = Math.floor(d / 60);
        const s = Math.floor(d % 60);
        return `${m}:${s.toString().padStart(2, '0')}`;
    })();

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.72)' }}>
            <div
                className="relative flex flex-col rounded-xl overflow-hidden shadow-2xl border border-white/10"
                style={{ width: 420, background: 'linear-gradient(160deg, #0f1425 0%, #0b0f1e 100%)' }}
            >
                {/* Header */}
                <div className="flex items-center justify-between px-5 py-3.5 border-b border-white/8">
                    <div className="flex items-center gap-2.5">
                        <div className="w-7 h-7 rounded-lg flex items-center justify-center" style={{ background: 'linear-gradient(135deg,#6366f1,#8b5cf6)' }}>
                            <Download size={13} className="text-white" />
                        </div>
                        <span className="text-sm font-semibold text-white tracking-tight">Export Project</span>
                    </div>
                    <button onClick={onClose} className="w-6 h-6 flex items-center justify-center rounded text-slate-500 hover:text-white hover:bg-white/8 transition-colors">
                        <X size={14} />
                    </button>
                </div>

                {/* Track Metadata Preview */}
                <div className="mx-5 mt-4 rounded-lg px-4 py-3 flex items-center gap-3" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.07)' }}>
                    <div className="w-8 h-8 rounded-md flex items-center justify-center flex-shrink-0" style={{ background: 'rgba(99,102,241,0.2)' }}>
                        <Music size={14} className="text-indigo-400" />
                    </div>
                    <div className="min-w-0 flex-1">
                        <div className="text-xs font-semibold text-white truncate">{state.trackTitle || 'Untitled'}</div>
                        <div className="text-[10px] text-slate-500 truncate">{state.trackArtist || 'Unknown Artist'}</div>
                    </div>
                    <div className="text-right flex-shrink-0">
                        <div className="text-[10px] font-mono text-slate-400">{durStr}</div>
                        <div className="text-[10px] text-slate-600">{state.bpm ? `${Math.round(state.bpm)} BPM` : '— BPM'}</div>
                    </div>
                </div>

                <div className="px-5 mt-4 space-y-4">
                    {/* Output Path */}
                    <div>
                        <label className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1.5 block">Output Path</label>
                        <div className="flex gap-2">
                            <input
                                type="text"
                                value={outputPath}
                                onChange={e => setOutputPath(e.target.value)}
                                placeholder="Click 📁 to select folder..."
                                className="flex-1 px-3 py-2 rounded-lg text-xs text-slate-300 placeholder-slate-600 outline-none"
                                style={{ background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)' }}
                            />
                            <button
                                onClick={handleBrowse}
                                className="w-8 h-8 flex items-center justify-center rounded-lg text-slate-400 hover:text-white transition-colors flex-shrink-0"
                                style={{ background: 'rgba(255,255,255,0.07)', border: '1px solid rgba(255,255,255,0.1)' }}
                                title="Browse…"
                            >
                                <FolderOpen size={13} />
                            </button>
                        </div>
                    </div>

                    {/* Format */}
                    <div>
                        <label className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-1.5 block">Format</label>
                        <div className="grid grid-cols-3 gap-2">
                            {FORMATS.map(f => (
                                <button
                                    key={f.id}
                                    onClick={() => setFormat(f.id)}
                                    className={`px-3 py-2.5 rounded-lg text-left transition-all ${format === f.id ? 'text-white' : 'text-slate-500 hover:text-slate-300'}`}
                                    style={{
                                        background: format === f.id ? 'linear-gradient(135deg,rgba(99,102,241,0.30),rgba(139,92,246,0.18))' : 'rgba(255,255,255,0.04)',
                                        border: format === f.id ? '1px solid rgba(99,102,241,0.5)' : '1px solid rgba(255,255,255,0.07)',
                                    }}
                                >
                                    <div className="text-xs font-bold">{f.label}</div>
                                    <div className="text-[9px] opacity-60 mt-0.5">{f.sub}</div>
                                </button>
                            ))}
                        </div>
                    </div>

                    {/* Normalize toggle */}
                    <label className="flex items-center gap-3 cursor-pointer group">
                        <div
                            onClick={() => setNormalize(v => !v)}
                            className={`w-9 h-5 rounded-full flex items-center transition-all duration-200 ${normalize ? 'justify-end' : 'justify-start'}`}
                            style={{ background: normalize ? 'rgba(99,102,241,0.8)' : 'rgba(255,255,255,0.1)', padding: '0 2px' }}
                        >
                            <div className="w-4 h-4 rounded-full bg-white shadow-md transition-all" />
                        </div>
                        <span className="text-xs text-slate-400 group-hover:text-slate-300 transition-colors select-none">
                            Apply Normalization
                        </span>
                    </label>
                </div>

                {/* Progress Bar (visible during export or after) */}
                {phase !== 'idle' && (
                    <div className="mx-5 mt-4">
                        {phase === 'error' ? (
                            <div className="flex items-center gap-2 px-3 py-2.5 rounded-lg" style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)' }}>
                                <AlertCircle size={13} className="text-red-400 flex-shrink-0" />
                                <span className="text-xs text-red-300">{errorMsg || 'Export failed'}</span>
                            </div>
                        ) : phase === 'done' ? (
                            <div className="flex items-center gap-2 px-3 py-2.5 rounded-lg" style={{ background: 'rgba(34,197,94,0.1)', border: '1px solid rgba(34,197,94,0.3)' }}>
                                <CheckCircle2 size={13} className="text-green-400 flex-shrink-0" />
                                <span className="text-xs text-green-300">Export complete!</span>
                            </div>
                        ) : (
                            <div>
                                <div className="flex items-center justify-between mb-1.5">
                                    <span className="text-[10px] text-slate-500 flex items-center gap-1">
                                        <Loader2 size={10} className="animate-spin" /> Rendering…
                                    </span>
                                    <span className="text-[10px] font-mono text-slate-400">{progress}%</span>
                                </div>
                                <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.08)' }}>
                                    <div
                                        className="h-full rounded-full transition-all duration-300"
                                        style={{ width: `${progress}%`, background: 'linear-gradient(90deg,#6366f1,#8b5cf6)' }}
                                    />
                                </div>
                            </div>
                        )}
                    </div>
                )}

                {/* Actions */}
                <div className="flex gap-2 px-5 py-4 mt-3">
                    <button
                        onClick={onClose}
                        className="flex-1 py-2 rounded-lg text-xs text-slate-400 hover:text-white transition-colors"
                        style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)' }}
                    >
                        {phase === 'done' ? 'Close' : 'Cancel'}
                    </button>
                    <button
                        onClick={phase === 'done' || phase === 'error' ? handleExport : handleExport}
                        disabled={phase === 'exporting'}
                        className="flex-1 py-2 rounded-lg text-xs font-semibold text-white flex items-center justify-center gap-1.5 transition-all disabled:opacity-50"
                        style={{ background: 'linear-gradient(135deg,#6366f1,#8b5cf6)', boxShadow: '0 2px 12px rgba(99,102,241,0.4)' }}
                    >
                        {phase === 'exporting'
                            ? <><Loader2 size={12} className="animate-spin" /> Exporting…</>
                            : phase === 'error'
                                ? <><Download size={12} /> Retry</>
                                : <><Download size={12} /> Export</>
                        }
                    </button>
                </div>
            </div>
        </div>
    );
});

ExportModal.displayName = 'ExportModal';

export default ExportModal;
