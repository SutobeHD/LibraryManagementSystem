/**
 * ExportModal — Project Export UI
 *
 * Features:
 * - Reads the user's default export folder from /api/settings (Settings → Export tab)
 * - Output folder picker via tauri-plugin-dialog (falls back to manual typing)
 * - Format selector (WAV / MP3 320kbps / FLAC)
 * - Normalization toggle
 * - WAV: rendered in-browser via DawEngine.renderTimeline + audioBufferToWav,
 *        then written to disk via tauri-plugin-fs (or downloaded in browser mode)
 * - MP3 / FLAC: rendered server-side via /api/audio/render, then either
 *        copied to the chosen folder via the backend or downloaded
 * - Progress bar with success/error states
 */

import React, { useState, useEffect, useCallback } from 'react';
import { X, FolderOpen, Music, CheckCircle2, AlertCircle, Download, Loader2 } from 'lucide-react';
import * as DawEngine from '../../audio/DawEngine';
import api from '../../api/api';
import { log } from '../../utils/log';
import { RENDER_API_TIMEOUT_MS, BLOB_URL_REVOKE_DELAY_MS } from '../../config/constants';

// ─── TAURI HELPERS (graceful fallback for browser/dev) ──────────────────────────

/**
 * Tauri 2 detection — `window.__TAURI__` is Tauri 1.x only.
 * Tauri 2 sets `__TAURI_INTERNALS__`. We check both for safety.
 * Best practice: try to load the plugin and fall back if it errors.
 */
const isTauri = typeof window !== 'undefined' && (
    Boolean(window.__TAURI_INTERNALS__) ||
    Boolean(window.__TAURI__) ||
    Boolean(window.isTauri)
);

log.info('[ExportModal] Tauri detection:', {
    isTauri,
    __TAURI_INTERNALS__: !!window.__TAURI_INTERNALS__,
    __TAURI__: !!window.__TAURI__,
});

async function pickDirectory(initial) {
    try {
        const { open } = await import('@tauri-apps/plugin-dialog');
        const picked = await open({
            directory: true,
            multiple: false,
            title: 'Select export folder',
            defaultPath: initial || undefined,
        });
        return typeof picked === 'string' ? picked : null;
    } catch (err) {
        console.warn('[ExportModal] Tauri dialog unavailable:', err);
        return null;
    }
}

async function createFolderIfNotExists(path) {
    try {
        const { mkdir } = await import('@tauri-apps/plugin-fs');
        const lastSlash = Math.max(path.lastIndexOf('\\'), path.lastIndexOf('/'));
        if (lastSlash <= 0) return;
        const dir = path.substring(0, lastSlash);
        log.debug('[ExportModal] Creating folder:', dir);
        await mkdir(dir, { recursive: true });
        log.debug('[ExportModal] Folder ready');
    } catch (err) {
        // mkdir may fail because folder already exists — that's fine
        log.debug('[ExportModal] mkdir result:', err.message);
    }
}

/**
 * Write binary file via Tauri 2 plugin-fs.
 * Tauri 2 API: writeFile(path, Uint8Array) — replaces Tauri 1's writeBinaryFile.
 * Returns the result; throws on actual failure (not "missing plugin").
 */
async function writeBinaryFile(path, uint8) {
    try {
        const fs = await import('@tauri-apps/plugin-fs');
        log.debug('[ExportModal] Writing', uint8.length, 'bytes to:', path);

        // Tauri 2 unified API
        if (typeof fs.writeFile === 'function') {
            await fs.writeFile(path, uint8);
        }
        // Tauri 1 fallback (just in case)
        else if (typeof fs.writeBinaryFile === 'function') {
            await fs.writeBinaryFile(path, uint8);
        } else {
            throw new Error('No fs write function found in plugin-fs');
        }

        log.debug('[ExportModal] Write successful');
        return true;
    } catch (err) {
        const msg = err.message || String(err);
        console.error('[ExportModal] Tauri fs write failed:', msg);
        throw new Error(`File write failed: ${msg}`);
    }
}

function joinPath(dir, file) {
    if (!dir) return file;
    const sep = dir.includes('\\') && !dir.includes('/') ? '\\' : (dir.includes('/') ? '/' : '\\');
    const trimmed = dir.replace(/[\\/]+$/, '');
    return `${trimmed}${sep}${file}`;
}

// ─── CONSTANTS ───────────────────────────────────────────────────────────────────

const FORMATS = [
    { id: 'wav',  label: 'WAV',     sub: '32-bit float · Lossless' },
    { id: 'mp3',  label: 'MP3 320', sub: '320 kbps · Small' },
    { id: 'flac', label: 'FLAC',    sub: '24-bit · Lossless+' },
];

// ─── COMPONENT ───────────────────────────────────────────────────────────────────

const ExportModal = React.memo(({ state, onClose }) => {
    const [outputDir,  setOutputDir]  = useState('');
    const [filename,   setFilename]   = useState('');
    const [format,     setFormat]     = useState('wav');
    const [normalize,  setNormalize]  = useState(false);
    const [phase,      setPhase]      = useState('idle'); // idle | exporting | done | error
    const [progress,   setProgress]   = useState(0);
    const [errorMsg,   setErrorMsg]   = useState('');
    const [savedPath,  setSavedPath]  = useState('');

    // Resolve track metadata from correct state paths
    const trackTitle  = state.trackMeta?.title  || state.project?.name || 'Untitled';
    const trackArtist = state.trackMeta?.artist || 'Unknown';

    // ── Init: load default folder from settings, derive a clean filename ──
    useEffect(() => {
        const safeName = (trackTitle || 'export').replace(/[<>:"/\\|?*]/g, '_').trim() || 'export';
        setFilename(safeName);
        api.get('/api/settings')
            .then(res => {
                const dir = res?.data?.default_export_dir;
                if (typeof dir === 'string' && dir.length) setOutputDir(dir);
            })
            .catch(() => { /* settings not critical — user can pick a folder */ });
    }, [trackTitle]);

    // ── Browse for output folder ──
    const handleBrowse = useCallback(async () => {
        const picked = await pickDirectory(outputDir);
        if (picked) setOutputDir(picked);
        else if (!isTauri) {
            setErrorMsg('Folder picker only works in the desktop app. Type a path manually.');
        }
    }, [outputDir]);

    // ── Start Export ──
    const handleExport = useCallback(async () => {
        setPhase('exporting');
        setProgress(0);
        setErrorMsg('');
        setSavedPath('');

        try {
            if (!state.sourceBuffer || !state.regions?.length) {
                throw new Error('No audio data to export');
            }

            const cleanName = (filename || 'export').replace(/[<>:"/\\|?*]/g, '_').replace(/\.(wav|mp3|flac)$/i, '');
            const outName = `${cleanName}.${format}`;
            const fullPath = outputDir ? joinPath(outputDir, outName) : outName;

            // ── WAV: browser-side rendering, then write to disk ──
            if (format === 'wav') {
                setProgress(10);
                const rendered = await DawEngine.renderTimeline(
                    state.regions,
                    state.sourceBuffer,
                    state.sourceBuffer.sampleRate,
                    (p) => setProgress(Math.round(10 + p * 75)),
                    state.volumeData || null  // Apply .rbep volume envelopes for Rekordbox-accurate output
                );

                setProgress(88);
                const wav = DawEngine.audioBufferToWav(rendered, normalize);
                const u8  = new Uint8Array(wav);

                if (outputDir) {
                    // Try Tauri write — falls back to download only if Tauri unavailable
                    try {
                        await createFolderIfNotExists(fullPath);
                        await writeBinaryFile(fullPath, u8);
                        setSavedPath(fullPath);
                    } catch (writeErr) {
                        console.error('[ExportModal] Tauri write failed, falling back to download:', writeErr);
                        if (!isTauri) {
                            // Genuine browser context — fall back to download
                            const blob = new Blob([u8], { type: 'audio/wav' });
                            triggerDownload(blob, outName);
                            setSavedPath(`Downloads / ${outName}`);
                        } else {
                            // Tauri context but write failed — surface the error
                            throw writeErr;
                        }
                    }
                } else {
                    // No folder selected — browser-style download
                    const blob = new Blob([u8], { type: 'audio/wav' });
                    triggerDownload(blob, outName);
                    setSavedPath(`Downloads / ${outName}`);
                }

                setProgress(100);
                setPhase('done');
                return;
            }

            // ── MP3 / FLAC: backend renders via FFmpeg, then we either save or download ──
            const sourcePath = state.trackMeta?.filepath;
            if (!sourcePath) {
                throw new Error('Source file path not available — open via Library, not via .rbep file picker.');
            }

            setProgress(10);
            const cuts = state.regions.map(r => ({
                start: r.sourceStart,
                end:   r.sourceEnd ?? (r.sourceStart + (r.sourceDuration || r.duration || 0)),
            }));

            const payload = {
                source_path: sourcePath,
                filename:    sourcePath,
                cuts,
                output_name: outName,
                fade_in:  false,
                fade_out: false,
                target_dir: outputDir || null,
            };

            setProgress(30);
            const resp = await api.post('/api/audio/render', payload, { timeout: RENDER_API_TIMEOUT_MS });
            setProgress(75);

            const dl = resp.data?.download_url || (resp.data?.filename ? `/exports/${resp.data.filename}` : null);
            if (!dl) {
                throw new Error(resp.data?.error || resp.data?.message || 'Backend render returned no output');
            }

            // If backend already wrote into the user's folder, we're done.
            if (resp.data?.saved_path) {
                setSavedPath(resp.data.saved_path);
                setProgress(100);
                setPhase('done');
                return;
            }

            // Otherwise: pull the file from /exports and either write to disk (Tauri) or download (browser)
            const absUrl = dl.startsWith('http') ? dl : `http://localhost:8000${dl}`;
            const dlResp = await fetch(absUrl);
            if (!dlResp.ok) throw new Error(`Download failed: ${dlResp.status}`);
            const blob = await dlResp.blob();
            const buf  = await blob.arrayBuffer();
            const u8   = new Uint8Array(buf);

            if (outputDir) {
                try {
                    await createFolderIfNotExists(fullPath);
                    await writeBinaryFile(fullPath, u8);
                    setSavedPath(fullPath);
                } catch (writeErr) {
                    console.error('[ExportModal] Tauri write failed, falling back to download:', writeErr);
                    if (!isTauri) {
                        triggerDownload(blob, outName);
                        setSavedPath(`Downloads / ${outName}`);
                    } else {
                        throw writeErr;
                    }
                }
            } else {
                triggerDownload(blob, outName);
                setSavedPath(`Downloads / ${outName}`);
            }

            setProgress(100);
            setPhase('done');

        } catch (err) {
            console.error('[ExportModal] Export failed:', err);
            setPhase('error');
            setErrorMsg(err.message || String(err));
        }
    }, [outputDir, filename, format, normalize, state]);

    // ── Formatted duration ──
    const durStr = (() => {
        const d = state.totalDuration || 0;
        const m = Math.floor(d / 60);
        const s = Math.floor(d % 60);
        return `${m}:${s.toString().padStart(2, '0')}`;
    })();

    // ── Download helper (browser fallback) ──
    function triggerDownload(blob, name) {
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = name;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        setTimeout(() => URL.revokeObjectURL(url), BLOB_URL_REVOKE_DELAY_MS);
    }

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.72)' }}>
            <div
                className="relative flex flex-col rounded-mx-lg overflow-hidden shadow-mx-lg border border-line-subtle bg-mx-shell"
                style={{ width: 460 }}
            >
                {/* Header */}
                <div className="flex items-center justify-between px-5 py-3.5 border-b border-line-subtle">
                    <div className="flex items-center gap-2.5">
                        <div className="w-7 h-7 rounded-mx-sm flex items-center justify-center" style={{ background: 'var(--amber-bg)', color: 'var(--amber)' }}>
                            <Download size={13} />
                        </div>
                        <span className="text-sm font-semibold text-ink-primary tracking-tight">Export Project</span>
                    </div>
                    <button onClick={onClose} className="w-6 h-6 flex items-center justify-center rounded text-ink-muted hover:text-ink-primary hover:bg-mx-hover transition-colors">
                        <X size={14} />
                    </button>
                </div>

                {/* Track Metadata Preview */}
                <div className="mx-5 mt-4 mx-card px-4 py-3 flex items-center gap-3">
                    <div className="w-8 h-8 rounded-mx-sm flex items-center justify-center flex-shrink-0" style={{ background: 'var(--amber-bg)', color: 'var(--amber)' }}>
                        <Music size={14} />
                    </div>
                    <div className="min-w-0 flex-1">
                        <div className="text-xs font-semibold text-ink-primary truncate">{trackTitle}</div>
                        <div className="text-[10px] text-ink-muted truncate">{trackArtist}</div>
                    </div>
                    <div className="text-right flex-shrink-0">
                        <div className="text-[10px] font-mono text-ink-secondary">{durStr}</div>
                        <div className="text-[10px] text-ink-placeholder">{state.bpm ? `${Math.round(state.bpm)} BPM` : '— BPM'}</div>
                    </div>
                </div>

                <div className="px-5 mt-4 space-y-4">
                    {/* Output Folder */}
                    <div>
                        <label className="text-[10px] font-bold text-ink-muted uppercase tracking-widest mb-1.5 block">Output Folder</label>
                        <div className="flex gap-2">
                            <input
                                type="text"
                                value={outputDir}
                                onChange={e => setOutputDir(e.target.value)}
                                placeholder={isTauri ? 'Click 📁 to choose…' : 'Browser mode — file will be downloaded'}
                                className="input-glass flex-1"
                            />
                            <button
                                onClick={handleBrowse}
                                disabled={!isTauri}
                                className="w-9 h-9 flex items-center justify-center rounded-mx-sm text-ink-secondary hover:text-ink-primary transition-colors flex-shrink-0 bg-mx-input border border-line-subtle hover:bg-mx-hover disabled:opacity-40 disabled:cursor-not-allowed"
                                title={isTauri ? 'Browse…' : 'Folder picker requires the desktop app'}
                            >
                                <FolderOpen size={13} />
                            </button>
                        </div>
                    </div>

                    {/* Filename */}
                    <div>
                        <label className="text-[10px] font-bold text-ink-muted uppercase tracking-widest mb-1.5 block">Filename</label>
                        <div className="flex items-center gap-2">
                            <input
                                type="text"
                                value={filename}
                                onChange={e => setFilename(e.target.value)}
                                className="input-glass flex-1"
                            />
                            <span className="text-[11px] font-mono text-ink-muted">.{format}</span>
                        </div>
                    </div>

                    {/* Format */}
                    <div>
                        <label className="text-[10px] font-bold text-ink-muted uppercase tracking-widest mb-1.5 block">Format</label>
                        <div className="grid grid-cols-3 gap-2">
                            {FORMATS.map(f => (
                                <button
                                    key={f.id}
                                    onClick={() => setFormat(f.id)}
                                    className={`px-3 py-2.5 rounded-mx-sm text-left transition-all border ${
                                        format === f.id
                                            ? 'bg-amber2/10 border-amber2/50 text-amber2'
                                            : 'bg-mx-input border-line-subtle text-ink-muted hover:bg-mx-hover hover:text-ink-secondary'
                                    }`}
                                >
                                    <div className="text-xs font-bold">{f.label}</div>
                                    <div className="text-[9px] opacity-70 mt-0.5">{f.sub}</div>
                                </button>
                            ))}
                        </div>
                    </div>

                    {/* Normalize toggle */}
                    <label className="flex items-center gap-3 cursor-pointer group">
                        <div
                            onClick={() => setNormalize(v => !v)}
                            className={`w-9 h-5 rounded-full flex items-center transition-all duration-200 ${normalize ? 'justify-end bg-amber2' : 'justify-start bg-mx-input border border-line-subtle'}`}
                            style={{ padding: '0 2px' }}
                        >
                            <div className="w-4 h-4 rounded-full bg-white shadow-sm transition-all" />
                        </div>
                        <span className="text-xs text-ink-secondary group-hover:text-ink-primary transition-colors select-none">
                            Apply Normalization
                        </span>
                    </label>
                </div>

                {/* Progress Bar / Status */}
                {phase !== 'idle' && (
                    <div className="mx-5 mt-4">
                        {phase === 'error' ? (
                            <div className="flex items-start gap-2 px-3 py-2.5 rounded-mx-sm bg-bad/10 border border-bad/30">
                                <AlertCircle size={13} className="text-bad flex-shrink-0 mt-0.5" />
                                <span className="text-xs text-bad break-words">{errorMsg || 'Export failed'}</span>
                            </div>
                        ) : phase === 'done' ? (
                            <div className="flex items-start gap-2 px-3 py-2.5 rounded-mx-sm bg-ok/10 border border-ok/30">
                                <CheckCircle2 size={13} className="text-ok flex-shrink-0 mt-0.5" />
                                <div className="flex-1 min-w-0">
                                    <div className="text-xs text-ok font-semibold">Export complete</div>
                                    {savedPath && (
                                        <div className="text-[10px] font-mono text-ink-muted truncate mt-0.5">{savedPath}</div>
                                    )}
                                </div>
                            </div>
                        ) : (
                            <div>
                                <div className="flex items-center justify-between mb-1.5">
                                    <span className="text-[10px] text-ink-muted flex items-center gap-1">
                                        <Loader2 size={10} className="animate-spin" /> Rendering…
                                    </span>
                                    <span className="text-[10px] font-mono text-ink-secondary">{progress}%</span>
                                </div>
                                <div className="h-1.5 rounded-full overflow-hidden bg-mx-input">
                                    <div
                                        className="h-full bg-amber2 transition-all duration-300"
                                        style={{ width: `${progress}%` }}
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
                        className="flex-1 py-2 rounded-mx-sm text-xs text-ink-secondary hover:text-ink-primary transition-colors bg-mx-input border border-line-subtle hover:bg-mx-hover"
                    >
                        {phase === 'done' ? 'Close' : 'Cancel'}
                    </button>
                    <button
                        onClick={handleExport}
                        disabled={phase === 'exporting'}
                        className="flex-1 py-2 rounded-mx-sm text-xs font-semibold text-mx-deepest flex items-center justify-center gap-1.5 transition-all disabled:opacity-50 bg-amber2 hover:bg-amber2-hover"
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
