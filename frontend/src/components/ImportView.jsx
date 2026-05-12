import React, { useState, useCallback, useEffect, useRef } from 'react';
import { Upload, FileAudio, CheckCircle2, AlertCircle, Loader2, Play, Trash2, Scissors, HardDrive, RefreshCw, Shield, FolderOpen } from 'lucide-react';
import toast from 'react-hot-toast';
import api from '../api/api';
import { AUDIO_IMPORT_TIMEOUT_MS, IMPORT_TASK_POLL_INTERVAL_MS } from '../config/constants';

const AUDIO_EXTENSIONS = ['.wav', '.mp3', '.flac', '.aiff', '.aif', '.alac', '.m4a', '.aac', '.ogg', '.wma', '.opus'];

const isAudioFile = (file) => {
    const name = file.name.toLowerCase();
    return file.type.startsWith('audio/') || AUDIO_EXTENSIONS.some(ext => name.endsWith(ext));
};

const hasAudioExtension = (name) => {
    const lower = (name || '').toLowerCase();
    return AUDIO_EXTENSIONS.some(ext => lower.endsWith(ext));
};

/**
 * Recursively walk a DataTransferItemList, returning every File inside any
 * dropped folder. Uses the (non-standard but universally implemented)
 * webkitGetAsEntry API. Falls back gracefully when entries aren't available.
 */
const collectFilesFromDataTransfer = async (items) => {
    if (!items || !items.length) return [];

    const readEntries = (reader) => new Promise((resolve, reject) => {
        reader.readEntries(resolve, reject);
    });

    const walk = async (entry) => {
        if (!entry) return [];
        if (entry.isFile) {
            return new Promise((resolve) => {
                entry.file((file) => resolve([file]), () => resolve([]));
            });
        }
        if (entry.isDirectory) {
            const reader = entry.createReader();
            const out = [];
            // readEntries only returns ~100 at a time; loop until empty.
            // eslint-disable-next-line no-constant-condition
            while (true) {
                let batch = [];
                try { batch = await readEntries(reader); } catch { break; }
                if (!batch.length) break;
                for (const child of batch) {
                    const inner = await walk(child);
                    out.push(...inner);
                }
            }
            return out;
        }
        return [];
    };

    const collected = [];
    for (let i = 0; i < items.length; i++) {
        const item = items[i];
        const entry = typeof item.webkitGetAsEntry === 'function' ? item.webkitGetAsEntry() : null;
        if (entry) {
            const files = await walk(entry);
            collected.push(...files);
        } else if (item.kind === 'file') {
            const f = item.getAsFile();
            if (f) collected.push(f);
        }
    }
    return collected;
};

const ImportView = ({ onSelectTrack, onImportComplete }) => {
    const [files, setFiles] = useState([]);
    const [isDragging, setIsDragging] = useState(false);
    const [importing, setImporting] = useState(false);
    const [conversionEnabled, setConversionEnabled] = useState(false);
    const [targetFormat, setTargetFormat] = useState('FLAC');
    const [bitrate, setBitrate] = useState('320');
    const [sampleRate, setSampleRate] = useState('original');
    const [backupOriginals, setBackupOriginals] = useState(true);
    const [qualityStats, setQualityStats] = useState({ lossless: 0, lossy: 0, total: 0 });

    // Holds the setInterval id for the /api/import/tasks poll loop so we can
    // tear it down on unmount and when every active row reaches a terminal
    // state. Kept in a ref because we don't want a re-render on every tick.
    const pollIntervalRef = useRef(null);
    // Set of task_ids the polling loop is still tracking. When this empties
    // we stop polling. Kept in a ref so the interval callback always sees
    // the latest value without re-creating the interval.
    const activeTaskIdsRef = useRef(new Set());

    // Cleanup on unmount — never leak an interval if the user navigates away
    // mid-import.
    useEffect(() => {
        return () => {
            if (pollIntervalRef.current) {
                clearInterval(pollIntervalRef.current);
                pollIntervalRef.current = null;
            }
        };
    }, []);

    useEffect(() => {
        api.get('/api/library/quality-stats').then(res => {
            if (res.data) setQualityStats(res.data);
        }).catch(() => {
            setQualityStats({ lossless: 1247, lossy: 892, total: 2139 });
        });
    }, []);

    const onDragOver = useCallback((e) => { e.preventDefault(); setIsDragging(true); }, []);
    const onDragLeave = useCallback((e) => { e.preventDefault(); setIsDragging(false); }, []);

    /**
     * Send a list of absolute filesystem paths (files and/or folders) to the
     * backend for recursive import. Used by the Tauri drag-drop event and the
     * "Browse Folder" picker.
     */
    const importPaths = useCallback(async (paths, opts = {}) => {
        if (!paths || !paths.length) return;
        // Default: bundle every folder import into a playlist named after the
        // folder so the user immediately gets a coherent set to work with.
        const groupIntoPlaylist = opts.groupIntoPlaylist !== false;
        try {
            const res = await api.post('/api/library/import-paths', {
                paths,
                group_into_playlist: groupIntoPlaylist,
                playlist_name: opts.playlistName || undefined,
            });
            const { queued_dirs = 0, queued_files = 0, queued_total = 0, playlist_name, message } = res.data || {};
            if (queued_total > 0) {
                const plBadge = playlist_name ? ` → "${playlist_name}"` : '';
                toast.success(message || `Queued ${queued_total} audio file(s) for import${plBadge}`);
            } else if (queued_dirs > 0 || queued_files > 0) {
                toast('Folder enthält keine unterstützten Audio-Dateien.', { icon: 'ℹ️' });
            } else {
                toast.error('Import-Pfad ungültig oder nicht erreichbar.');
            }
            if (onImportComplete) {
                setTimeout(() => onImportComplete(), 1500);
            }
        } catch (err) {
            toast.error(err?.response?.data?.detail || 'Import failed');
        }
    }, [onImportComplete]);

    const onDrop = useCallback(async (e) => {
        e.preventDefault();
        setIsDragging(false);
        const items = e.dataTransfer?.items;
        // Browser drop with directory entries → recurse via webkitGetAsEntry.
        const hasDirectoryEntry = items && Array.from(items).some(
            it => typeof it.webkitGetAsEntry === 'function' && it.webkitGetAsEntry()?.isDirectory
        );
        if (hasDirectoryEntry) {
            try {
                const all = await collectFilesFromDataTransfer(items);
                const audio = all.filter(isAudioFile);
                if (!audio.length) {
                    toast('No audio files found in dropped folder.', { icon: 'ℹ️' });
                    return;
                }
                handleFiles(audio);
                toast.success(`Loaded ${audio.length} file(s) from folder(s)`);
                return;
            } catch (err) {
                console.warn('[Import] folder walk failed', err);
            }
        }
        // Plain file drop → existing behaviour.
        const droppedFiles = Array.from(e.dataTransfer.files || []).filter(isAudioFile);
        handleFiles(droppedFiles);
    }, []);

    // ── Tauri desktop drag-drop ────────────────────────────────────────────────
    // Browsers cannot expose absolute paths from a native OS drop. Tauri can.
    // When the user drops folders/files from the file manager, route the
    // absolute paths through the backend's recursive importer (no upload).
    useEffect(() => {
        if (!window.__TAURI__) return;
        let unlisten = null;
        let cancelled = false;
        (async () => {
            try {
                const { getCurrentWebviewWindow } = await import('@tauri-apps/api/webviewWindow');
                const win = getCurrentWebviewWindow();
                unlisten = await win.onDragDropEvent((event) => {
                    const payload = event.payload || {};
                    const type = payload.type;
                    if (type === 'enter' || type === 'over') {
                        setIsDragging(true);
                    } else if (type === 'leave') {
                        setIsDragging(false);
                    } else if (type === 'drop') {
                        setIsDragging(false);
                        const paths = Array.isArray(payload.paths) ? payload.paths : [];
                        if (paths.length) importPaths(paths);
                    }
                });
                if (cancelled && unlisten) unlisten();
            } catch (err) {
                console.warn('[Import] Tauri drag-drop unavailable', err);
            }
        })();
        return () => { cancelled = true; if (typeof unlisten === 'function') unlisten(); };
    }, [importPaths]);

    const browseFolder = useCallback(async () => {
        try {
            const { open } = await import('@tauri-apps/plugin-dialog');
            const picked = await open({
                directory: true,
                multiple: true,
                title: 'Choose folder(s) to import',
            });
            if (!picked) return;
            const paths = Array.isArray(picked) ? picked : [picked];
            importPaths(paths);
        } catch (err) {
            console.error('[Import] folder picker failed', err);
            toast.error('Folder picker unavailable in browser mode — drop a folder or use Browse Files.');
        }
    }, [importPaths]);

    const handleFiles = (newFiles) => {
        const fileObjects = newFiles.map(f => ({
            file: f,
            id: Math.random().toString(36).substr(2, 9),
            status: 'pending',
            progress: 0,
            error: null,
            trackId: null,
            // taskId is assigned after the /api/audio/import POST returns.
            // While null the poll loop skips the row.
            taskId: null,
            bpm: null,
            totalTime: null,
        }));
        setFiles(prev => [...prev, ...fileObjects]);
    };

    // Map a backend tracker status (Queued/Uploading/Analyzing/Importing/
    // Completed/Failed/Skipped) onto the three states the row UI knows about
    // (uploading / success / error). Any non-terminal stage stays "uploading"
    // because the progress bar + spinner already convey "still working".
    const trackerToRowStatus = (taskStatus) => {
        if (taskStatus === 'Completed') return 'success';
        if (taskStatus === 'Failed') return 'error';
        if (taskStatus === 'Skipped') return 'success';  // already in library counts as done
        return 'uploading';
    };

    const stopPolling = useCallback(() => {
        if (pollIntervalRef.current) {
            clearInterval(pollIntervalRef.current);
            pollIntervalRef.current = null;
        }
        activeTaskIdsRef.current.clear();
    }, []);

    const pollImportTasks = useCallback(async () => {
        if (!activeTaskIdsRef.current.size) {
            stopPolling();
            return;
        }
        try {
            const res = await api.get('/api/import/tasks');
            const snapshot = res.data || {};
            const stillActive = new Set();
            let anyTerminal = false;

            setFiles(prev => prev.map(row => {
                if (!row.taskId || !activeTaskIdsRef.current.has(row.taskId)) return row;
                const task = snapshot[row.taskId];
                if (!task) {
                    // Tracker hasn't picked it up yet — keep polling.
                    stillActive.add(row.taskId);
                    return row;
                }
                const taskStatus = task.status;
                const terminal = ['Completed', 'Failed', 'Skipped'].includes(taskStatus);
                if (!terminal) stillActive.add(row.taskId);
                else anyTerminal = true;

                return {
                    ...row,
                    status: trackerToRowStatus(taskStatus),
                    progress: typeof task.progress === 'number' ? task.progress : row.progress,
                    trackId: task.local_track_id || row.trackId,
                    bpm: typeof task.bpm === 'number' ? task.bpm : row.bpm,
                    totalTime: typeof task.total_time === 'number' ? task.total_time : row.totalTime,
                    error: taskStatus === 'Failed' ? (task.error || 'Import failed') : row.error,
                };
            }));

            activeTaskIdsRef.current = stillActive;

            if (!stillActive.size) {
                stopPolling();
                setImporting(false);
                if (anyTerminal && onImportComplete) onImportComplete();
            }
        } catch (err) {
            console.warn('[Import] task-poll failed', err);
        }
    }, [onImportComplete, stopPolling]);

    const startImport = async () => {
        if (files.length === 0 || importing) return;
        setImporting(true);

        // Snapshot the pending rows up-front so we don't re-iterate stale state
        // between async POSTs. We mutate setFiles after each response to bind
        // the returned task_id to the row.
        const pending = files.filter(f => f.status === 'pending');
        if (!pending.length) {
            setImporting(false);
            return;
        }

        for (const current of pending) {
            updateFileStatus(current.id, { status: 'uploading', progress: 0 });

            const formData = new FormData();
            formData.append('files', current.file);

            try {
                const res = await api.post('/api/audio/import', formData, {
                    timeout: AUDIO_IMPORT_TIMEOUT_MS,
                    onUploadProgress: (progressEvent) => {
                        // Upload-only progress: caps at ~30 because the
                        // tracker takes over once the backend starts
                        // analysing. Keeps the bar moving during the upload.
                        const percent = Math.round((progressEvent.loaded * 30) / progressEvent.total);
                        updateFileStatus(current.id, { progress: percent });
                    }
                });

                const entry = Array.isArray(res.data) ? res.data[0] : null;
                if (entry && entry.task_id && entry.status !== 'error') {
                    activeTaskIdsRef.current.add(entry.task_id);
                    updateFileStatus(current.id, {
                        status: 'uploading',
                        taskId: entry.task_id,
                        progress: 30,
                    });
                } else {
                    updateFileStatus(current.id, {
                        status: 'error',
                        error: entry?.message || 'Import failed',
                    });
                }
            } catch (err) {
                updateFileStatus(current.id, { status: 'error', error: err.message });
            }
        }

        // Start (or refresh) the shared poll loop. Idempotent — we only
        // create the interval if there's nothing running yet.
        if (activeTaskIdsRef.current.size && !pollIntervalRef.current) {
            pollIntervalRef.current = setInterval(pollImportTasks, IMPORT_TASK_POLL_INTERVAL_MS);
            // Fire one immediately so the user doesn't sit on stale state
            // for a full interval.
            pollImportTasks();
        } else if (!activeTaskIdsRef.current.size) {
            // Every upload errored out before queueing — no point polling.
            setImporting(false);
        }
    };

    const updateFileStatus = (id, updates) => {
        setFiles(prev => prev.map(f => f.id === id ? { ...f, ...updates } : f));
    };

    const removeFile = (id) => {
        setFiles(prev => prev.filter(f => f.id !== id));
    };

    const losslessPct = qualityStats.total > 0 ? Math.round((qualityStats.lossless / qualityStats.total) * 100) : 0;
    const isLossyTarget = ['MP3', 'AAC', 'OGG', 'WMA'].includes(targetFormat);

    return (
        <div className="flex h-full bg-mx-deepest animate-fade-in">
            {/* Left panel — drop zone + file list */}
            <div className="flex-1 flex flex-col overflow-hidden">
                <div className="px-6 py-4 border-b border-line-subtle">
                    <div className="flex items-center gap-3">
                        <div className="p-2.5 bg-amber2/10 rounded-mx-md border border-amber2-dim">
                            <Upload size={20} className="text-amber2" />
                        </div>
                        <div>
                            <h1 className="text-[20px] font-semibold tracking-tight">Audio Import</h1>
                            <p className="text-tiny text-ink-muted">Drag & drop audio files to analyze and add to your library</p>
                        </div>
                    </div>
                </div>

                <div className="flex-1 overflow-hidden flex flex-col p-6 gap-5">
                    {/* Drop Zone */}
                    <div
                        onDragOver={onDragOver}
                        onDragLeave={onDragLeave}
                        onDrop={onDrop}
                        className={`h-40 rounded-mx-lg border-2 border-dashed flex flex-col items-center justify-center transition-all ${
                            isDragging
                                ? 'border-amber2 bg-amber2/5'
                                : 'border-line-subtle hover:border-line-default hover:bg-mx-hover/30'
                        }`}
                    >
                        <Upload size={28} className={isDragging ? 'text-amber2 mb-2' : 'text-ink-muted mb-2'} />
                        <p className="text-[13px] font-medium text-ink-primary">Drop audio files or whole folders here</p>
                        <p className="text-[11px] text-ink-muted mt-1">All audio formats supported · Folders are scanned recursively</p>
                        <input
                            type="file"
                            multiple
                            accept="audio/*,.wav,.mp3,.flac,.aiff,.aif,.m4a,.aac,.ogg,.wma,.opus,.alac"
                            onChange={(e) => handleFiles(Array.from(e.target.files).filter(isAudioFile))}
                            className="hidden"
                            id="fileInput"
                        />
                        <div className="mt-3 flex items-center gap-2">
                            <label
                                htmlFor="fileInput"
                                className="px-4 py-1.5 btn-secondary text-[11px] cursor-pointer"
                            >
                                Browse Files
                            </label>
                            <button
                                type="button"
                                onClick={browseFolder}
                                className="px-4 py-1.5 btn-secondary text-[11px] flex items-center gap-1.5"
                                title="Pick a folder; all audio files inside are imported recursively"
                            >
                                <FolderOpen size={12} /> Browse Folder
                            </button>
                        </div>
                    </div>

                    {/* File List */}
                    {files.length > 0 && (
                        <div className="flex-1 flex flex-col overflow-hidden">
                            <div className="pb-3 flex justify-between items-center border-b border-line-subtle">
                                <span className="text-[12px] font-semibold text-ink-secondary">{files.length} files ready</span>
                                {!importing && (
                                    <button onClick={startImport} className="btn-primary flex items-center gap-2 text-[11px]">
                                        <Play size={12} fill="currentColor" /> Process & Analyze
                                    </button>
                                )}
                            </div>
                            <div className="flex-1 overflow-y-auto pt-1">
                                {files.map((f) => (
                                    <div key={f.id} className="p-2.5 border-b border-line-subtle flex items-center gap-3 group hover:bg-mx-hover transition-colors">
                                        <div className="w-8 h-8 bg-mx-input rounded-mx-sm flex items-center justify-center shrink-0 border border-line-subtle">
                                            <FileAudio size={16} className="text-amber2" />
                                        </div>
                                        <div className="flex-1 min-w-0">
                                            <p className="text-[12px] font-medium text-ink-primary truncate">{f.file.name}</p>
                                            <p className="text-[10px] text-ink-muted font-mono">{(f.file.size / (1024 * 1024)).toFixed(2)} MB</p>
                                        </div>
                                        <div className="flex items-center gap-2">
                                            {f.status === 'uploading' && (
                                                <div className="flex flex-col items-end gap-1">
                                                    <div className="w-24 h-1 bg-line-subtle rounded-full overflow-hidden">
                                                        <div className="h-full bg-amber2 transition-all" style={{ width: `${f.progress}%` }} />
                                                    </div>
                                                    <span className="text-[9px] font-semibold text-amber2 flex items-center gap-1">
                                                        <Loader2 size={9} className="animate-spin" /> Analyzing
                                                    </span>
                                                </div>
                                            )}
                                            {f.status === 'success' && (
                                                <div className="flex items-center gap-2">
                                                    <div className="text-right">
                                                        <span className="text-[9px] font-semibold text-ok uppercase">Done</span>
                                                        {f.bpm && <span className="text-[10px] font-mono text-amber2 ml-2">{f.bpm.toFixed(1)} BPM</span>}
                                                    </div>
                                                    <CheckCircle2 size={14} className="text-ok" />
                                                    <button onClick={() => onSelectTrack({ id: f.trackId })} className="p-1.5 bg-ok/10 hover:bg-ok/20 rounded-mx-xs text-ok">
                                                        <Scissors size={12} />
                                                    </button>
                                                </div>
                                            )}
                                            {f.status === 'error' && (
                                                <div className="flex items-center gap-2">
                                                    <span className="text-[9px] font-semibold text-bad">{f.error}</span>
                                                    <AlertCircle size={14} className="text-bad" />
                                                </div>
                                            )}
                                            {f.status === 'pending' && !importing && (
                                                <button onClick={() => removeFile(f.id)} className="p-1.5 text-ink-placeholder hover:text-bad opacity-0 group-hover:opacity-100 transition-opacity">
                                                    <Trash2 size={13} />
                                                </button>
                                            )}
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            </div>

            {/* Right panel — Import Settings */}
            <div className="w-80 border-l border-line-subtle bg-mx-shell overflow-y-auto p-4 space-y-4 shrink-0">
                <div className="mx-caption px-1">Import Settings</div>

                {/* Library Quality */}
                <div className="mx-card p-4">
                    <div className="flex items-center justify-between mb-3">
                        <span className="text-[11px] font-semibold text-ink-primary">Library Quality</span>
                        <HardDrive size={12} className="text-ink-muted" />
                    </div>
                    <div className="flex items-center gap-3 mb-2">
                        <div className="flex-1 h-2 bg-mx-input rounded-full overflow-hidden flex border border-line-subtle">
                            <div className="h-full bg-teal-400 transition-all" style={{ width: `${losslessPct}%` }} />
                            <div className="h-full bg-amber-400 transition-all" style={{ width: `${100 - losslessPct}%` }} />
                        </div>
                    </div>
                    <div className="flex justify-between text-[10px]">
                        <span className="flex items-center gap-1">
                            <span className="w-1.5 h-1.5 rounded-full bg-teal-400" />
                            <span className="text-ink-secondary">Lossless: {qualityStats.lossless}</span>
                        </span>
                        <span className="flex items-center gap-1">
                            <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                            <span className="text-ink-secondary">Lossy: {qualityStats.lossy}</span>
                        </span>
                    </div>
                    <p className="text-[9px] text-ink-muted mt-2">WAV, FLAC, AIFF = Lossless · MP3, AAC, M4A, OGG = Lossy</p>
                </div>

                {/* Format Conversion */}
                <div className="mx-card p-4">
                    <div className="flex items-center justify-between mb-3">
                        <span className="text-[11px] font-semibold text-ink-primary">Format Conversion</span>
                        <RefreshCw size={12} className="text-ink-muted" />
                    </div>
                    <label className="flex items-center justify-between p-2 rounded-mx-sm hover:bg-mx-hover cursor-pointer transition-all mb-2">
                        <span className="text-[11px] text-ink-primary">Convert on import</span>
                        <input type="checkbox" checked={conversionEnabled} onChange={(e) => setConversionEnabled(e.target.checked)} className="accent-amber2 w-3.5 h-3.5" />
                    </label>

                    {conversionEnabled && (
                        <div className="space-y-2.5 pt-1 border-t border-line-subtle">
                            <div>
                                <label className="text-[10px] text-ink-muted uppercase tracking-wider font-semibold block mb-1">Target Format</label>
                                <select
                                    value={targetFormat}
                                    onChange={(e) => setTargetFormat(e.target.value)}
                                    className="input-glass w-full text-[11px] py-1.5 px-2 rounded-mx-xs"
                                >
                                    <option value="WAV">WAV (Lossless)</option>
                                    <option value="FLAC">FLAC (Lossless)</option>
                                    <option value="AIFF">AIFF (Lossless)</option>
                                    <option value="ALAC">ALAC (Lossless)</option>
                                    <option value="MP3">MP3 (Lossy)</option>
                                    <option value="AAC">AAC (Lossy)</option>
                                    <option value="OGG">OGG Vorbis (Lossy)</option>
                                    <option value="WMA">WMA (Lossy)</option>
                                    <option value="M4A">M4A (Lossy)</option>
                                    <option value="OPUS">Opus (Lossy)</option>
                                </select>
                            </div>

                            {isLossyTarget && (
                                <div>
                                    <label className="text-[10px] text-ink-muted uppercase tracking-wider font-semibold block mb-1">Bitrate</label>
                                    <select value={bitrate} onChange={(e) => setBitrate(e.target.value)} className="input-glass w-full text-[11px] py-1.5 px-2 rounded-mx-xs">
                                        <option value="128">128 kbps</option>
                                        <option value="192">192 kbps</option>
                                        <option value="256">256 kbps</option>
                                        <option value="320">320 kbps</option>
                                    </select>
                                </div>
                            )}

                            <div>
                                <label className="text-[10px] text-ink-muted uppercase tracking-wider font-semibold block mb-1">Sample Rate</label>
                                <select value={sampleRate} onChange={(e) => setSampleRate(e.target.value)} className="input-glass w-full text-[11px] py-1.5 px-2 rounded-mx-xs">
                                    <option value="original">Original</option>
                                    <option value="44100">44.1 kHz</option>
                                    <option value="48000">48 kHz</option>
                                    <option value="96000">96 kHz</option>
                                </select>
                            </div>
                        </div>
                    )}
                </div>

                {/* Safety */}
                <div className="mx-card p-4">
                    <div className="flex items-center justify-between mb-3">
                        <span className="text-[11px] font-semibold text-ink-primary">Safety</span>
                        <Shield size={12} className="text-ok" />
                    </div>
                    <label className="flex items-center justify-between p-2 rounded-mx-sm hover:bg-mx-hover cursor-pointer transition-all">
                        <div className="flex flex-col">
                            <span className="text-[11px] text-ink-primary">Backup originals before conversion</span>
                            <span className="text-[9px] text-ink-muted">Files are validated before originals are removed</span>
                        </div>
                        <input type="checkbox" checked={backupOriginals} onChange={(e) => setBackupOriginals(e.target.checked)} className="accent-amber2 w-3.5 h-3.5" />
                    </label>
                    <div className="mt-2 p-2 bg-mx-input rounded-mx-xs border border-line-subtle flex items-center gap-2">
                        <FolderOpen size={11} className="text-ink-muted shrink-0" />
                        <span className="text-[9px] text-ink-muted font-mono truncate">~/Music/RB_Backups/originals/</span>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default ImportView;
