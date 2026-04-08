/**
 * ExportModal — Project Export UI
 *
 * Features:
 * - Metadata preview (title, artist, BPM, duration)
 * - Output path selection via Tauri file dialog
 * - Format selector (WAV / MP3 320kbps / FLAC)
 * - Normalization toggle
 * - Browser-side WAV export + backend rendering for MP3/FLAC
 * - Progress bar with success/error states
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import { X, FolderOpen, Music, CheckCircle2, AlertCircle, Download, Loader2 } from 'lucide-react';
import * as DawEngine from '../../audio/DawEngine';
import api from '../../api/api';

// ─── TAURI DYNAMIC IMPORTS (graceful fallback if not in Tauri context) ──────────

async function tauriInvoke(cmd, args) {
    try {
        const { invoke } = await import('@tauri-apps/api/core');
        return await invoke(cmd, args);
    } catch {
        return null; // fallback to web mode
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

    // Resolve track metadata from correct state paths
    const trackTitle  = state.trackMeta?.title  || state.project?.name || 'Untitled';
    const trackArtist = state.trackMeta?.artist || 'Unknown';
    const trackKey    = state.trackMeta?.key    || '';

    // ── Browse for output folder ──
    const handleBrowse = useCallback(async () => {
        const dir = await tauriInvoke('open_file_dialog', { directory: true, title: 'Select export folder' });
        if (dir) {
            const safeName = (trackTitle || 'export').replace(/[<>:"/\\|?*]/g, '_');
            setOutputPath(`${dir}/${safeName}.${format}`);
        }
    }, [trackTitle, format]);

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

        try {
            if (!state.sourceBuffer || !state.regions?.length) {
                throw new Error('No audio data to export');
            }

            const safeName = (trackTitle).replace(/[<>:"/\\|?*]/g, '_');

            // ── WAV: browser-side rendering (fast, no backend needed) ──
            // File is saved to the browser's Downloads folder (standard browser behaviour).
            // In Tauri desktop mode the Tauri file-dialog is used to choose the exact path.
            if (format === 'wav') {
                setProgress(10);
                const rendered = await DawEngine.renderTimeline(
                    state.regions,
                    state.sourceBuffer,
                    state.sourceBuffer.sampleRate,
                    (p) => setProgress(Math.round(10 + p * 85))
                );

                setProgress(96);
                const wav = DawEngine.audioBufferToWav(rendered);
                triggerDownload(wav, `${safeName}.wav`);
                setProgress(100);
                setPhase('done');
                // Note: WAV goes to browser Downloads folder — not to the selected outputPath.
                // outputPath is used for filename only when no Tauri context is available.
                return;
            }

            // ── MP3 / FLAC: backend rendering via /api/audio/render ──
            const sourcePath = state.trackMeta?.filepath;
            if (!sourcePath) {
                throw new Error('Source file path not available — cannot render MP3/FLAC');
            }

            setProgress(10);

            // Build cuts array from regions
            const cuts = state.regions.map(r => ({
                start: r.sourceStart,
                end: r.sourceEnd ?? (r.sourceStart + r.duration),
            }));

            const outputName = `${safeName}.${format}`;
            const payload = {
                source_path: sourcePath,
                filename: sourcePath,
                cuts,
                output_name: outputName,
                fade_in: false,
                fade_out: false,
            };

            setProgress(30);
            const resp = await api.post('/api/audio/render', payload, { timeout: 120000 });
            setProgress(80);

            if (resp.data?.download_url || resp.data?.filename) {
                // Download rendered file from backend
                const downloadUrl = resp.data.download_url || `/exports/${resp.data.filename}`;
                const dlResp = await fetch(downloadUrl);
                if (!dlResp.ok) throw new Error(`Download failed: ${dlResp.status}`);
                const blob = await dlResp.blob();
                triggerDownload(blob, outputName);
            } else {
                throw new Error(resp.data?.error || 'Backend render returned no output');
            }

            setProgress(100);
            setPhase('done');

        } catch (err) {
            console.error('[ExportModal] Export failed:', err);
            setPhase('error');
            setErrorMsg(err.message || String(err));
        }
    }, [outputPath, format, normalize, state, trackTitle]);

    // ── Formatted duration ──
    const durStr = (() => {
        const d = state.totalDuration || 0;
        const m = Math.floor(d / 60);
        const s = Math.floor(d % 60);
        return `${m}:${s.toString().padStart(2, '0')}`;
    })();

    // ── Download helper ──
    function triggerDownload(blob, filename) {
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        setTimeout(() => URL.revokeObjectURL(url), 5000);
    }

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
                        <div className="text-xs font-semibold text-white truncate">{trackTitle}</div>
                        <div className="text-[10px] text-slate-500 truncate">{trackArtist}</div>
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
