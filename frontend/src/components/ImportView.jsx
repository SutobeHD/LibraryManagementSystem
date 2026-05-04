import React, { useState, useCallback } from 'react';
import { Upload, FileAudio, CheckCircle2, AlertCircle, Loader2, Play, Trash2, Scissors } from 'lucide-react';
import api from '../api/api';

const ImportView = ({ onSelectTrack, onImportComplete }) => {
    const [files, setFiles] = useState([]);
    const [isDragging, setIsDragging] = useState(false);
    const [importing, setImporting] = useState(false);

    const onDragOver = useCallback((e) => {
        e.preventDefault();
        setIsDragging(true);
    }, []);

    const onDragLeave = useCallback((e) => {
        e.preventDefault();
        setIsDragging(false);
    }, []);

    const onDrop = useCallback((e) => {
        e.preventDefault();
        setIsDragging(false);
        const droppedFiles = Array.from(e.dataTransfer.files).filter(f => f.type.startsWith('audio/') || f.name.endsWith('.wav') || f.name.endsWith('.mp3'));
        handleFiles(droppedFiles);
    }, []);

    const handleFiles = (newFiles) => {
        const fileObjects = newFiles.map(f => ({
            file: f,
            id: Math.random().toString(36).substr(2, 9),
            status: 'pending',
            progress: 0,
            error: null,
            trackId: null
        }));
        setFiles(prev => [...prev, ...fileObjects]);
    };

    const startImport = async () => {
        if (files.length === 0 || importing) return;
        setImporting(true);

        for (let i = 0; i < files.length; i++) {
            if (files[i].status !== 'pending') continue;

            const current = files[i];
            updateFileStatus(current.id, { status: 'uploading' });

            const formData = new FormData();
            formData.append('files', current.file);

            try {
                const res = await api.post('/api/audio/import', formData, {
                    onUploadProgress: (progressEvent) => {
                        const percent = Math.round((progressEvent.loaded * 100) / progressEvent.total);
                        updateFileStatus(current.id, { progress: percent });
                    }
                });

                if (res.data && res.data[0].status === 'success') {
                    updateFileStatus(current.id, {
                        status: 'success',
                        progress: 100,
                        trackId: res.data[0].id,
                        bpm: res.data[0].bpm,
                        totalTime: res.data[0].totalTime
                    });
                    if (onImportComplete) onImportComplete();
                } else {
                    updateFileStatus(current.id, {
                        status: 'error',
                        error: res.data[0]?.message || 'Import failed'
                    });
                }
            } catch (err) {
                updateFileStatus(current.id, { status: 'error', error: err.message });
            }
        }
        setImporting(false);
    };

    const updateFileStatus = (id, updates) => {
        setFiles(prev => prev.map(f => f.id === id ? { ...f, ...updates } : f));
    };

    const removeFile = (id) => {
        setFiles(prev => prev.filter(f => f.id !== id));
    };

    return (
        <div className="flex flex-col h-full bg-mx-deepest/50 animate-in fade-in duration-500">
            {/* Header */}
            <div className="p-8 border-b border-white/5">
                <h1 className="text-3xl font-bold text-white mb-2 flex items-center gap-3">
                    <Upload className="text-amber2" />
                    Audio Import <span className="text-xs bg-amber2/10 text-amber2 px-2 py-0.5 rounded border border-amber2/20 ml-2">PRO</span>
                </h1>
                <p className="text-ink-secondary">Drag & Drop audio files to analyze and add them to your Rekordbox collection.</p>
            </div>

            <div className="flex-1 overflow-hidden flex flex-col p-8 gap-8">
                {/* Drop Zone */}
                <div
                    onDragOver={onDragOver}
                    onDragLeave={onDragLeave}
                    onDrop={onDrop}
                    className={`h-48 rounded-xl border-2 border-dashed flex flex-col items-center justify-center transition-all duration-300 ${isDragging
                        ? 'border-amber2 bg-amber2/5'
                        : 'border-white/10 hover:border-white/20 hover:bg-white/5'
                        }`}
                >
                    <div className="w-20 h-20 rounded-full bg-mx-shell border border-white/5 flex items-center justify-center mb-4 shadow-2xl">
                        <Upload size={32} className={isDragging ? 'text-amber2 scale-110 transition-transform' : 'text-ink-muted'} />
                    </div>
                    <p className="text-xl font-medium text-ink-primary">Drop files here</p>
                    <p className="text-sm text-ink-muted mt-2">Support for WAV, MP3, AIFF, FLAC</p>
                    <input
                        type="file"
                        multiple
                        accept="audio/*"
                        onChange={(e) => handleFiles(Array.from(e.target.files))}
                        className="hidden"
                        id="fileInput"
                    />
                    <label
                        htmlFor="fileInput"
                        className="mt-6 px-6 py-2 bg-mx-card hover:bg-mx-hover rounded-full text-sm font-bold border border-white/5 transition-colors cursor-pointer"
                    >
                        Browse Files
                    </label>
                </div>

                {/* File List */}
                {files.length > 0 && (
                    <div className="flex-1 flex flex-col overflow-hidden">
                        <div className="pb-4 flex justify-between items-center border-b border-white/5">
                            <span className="text-sm font-bold text-ink-secondary">{files.length} Files Ready</span>
                            {!importing && (
                                <button
                                    onClick={startImport}
                                    className="px-6 py-2 bg-slate-100 hover:bg-white text-black rounded-lg text-sm font-bold shadow-lg shadow-white/10 transition-all active:scale-95 flex items-center gap-2"
                                >
                                    <Play size={14} fill="currentColor" />
                                    Process & Analyze
                                </button>
                            )}
                        </div>
                        <div className="flex-1 overflow-y-auto pt-2 custom-scrollbar">
                            {files.map((f) => (
                                <div key={f.id} className="p-3 border-b border-white/5 flex items-center gap-4 group hover:bg-white/5 transition-colors rounded-lg">
                                    <div className="w-10 h-10 bg-mx-card rounded-xl flex items-center justify-center shrink-0">
                                        <FileAudio size={20} className="text-amber2" />
                                    </div>
                                    <div className="flex-1 min-w-0">
                                        <p className="text-sm font-bold text-ink-primary truncate">{f.file.name}</p>
                                        <p className="text-[10px] text-ink-muted font-mono mt-0.5">{(f.file.size / (1024 * 1024)).toFixed(2)} MB</p>
                                    </div>

                                    {/* Status Indicator */}
                                    <div className="flex items-center gap-3">
                                        {f.status === 'uploading' && (
                                            <div className="flex flex-col items-end gap-1">
                                                <div className="w-32 h-1 bg-white/5 rounded-full overflow-hidden">
                                                    <div className="h-full bg-amber2 transition-all duration-300" style={{ width: `${f.progress}%` }} />
                                                </div>
                                                <span className="text-[10px] items-center gap-1 font-bold text-amber2 flex uppercase tracking-tighter">
                                                    <Loader2 size={10} className="animate-spin" /> Analyzing
                                                </span>
                                            </div>
                                        )}
                                        {f.status === 'success' && (
                                            <div className="flex items-center gap-3">
                                                <div className="flex flex-col items-end">
                                                    <span className="text-[10px] font-bold text-green-500 uppercase tracking-tighter">Ready for Edit</span>
                                                    {f.bpm && <span className="text-[10px] font-mono text-amber2 font-bold">{f.bpm.toFixed(1)} BPM</span>}
                                                </div>
                                                <CheckCircle2 size={18} className="text-green-500" />
                                                <button
                                                    onClick={() => onSelectTrack({ id: f.trackId })}
                                                    className="p-2 bg-green-500/10 hover:bg-green-500/20 rounded-lg text-green-500"
                                                >
                                                    <Scissors size={14} />
                                                </button>
                                            </div>
                                        )}
                                        {f.status === 'error' && (
                                            <div className="flex items-center gap-2">
                                                <span className="text-[10px] font-bold text-red-500 uppercase tracking-tighter">{f.error}</span>
                                                <AlertCircle size={18} className="text-red-500" />
                                            </div>
                                        )}
                                        {f.status === 'pending' && !importing && (
                                            <button
                                                onClick={() => removeFile(f.id)}
                                                className="p-2 text-ink-placeholder hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity"
                                            >
                                                <Trash2 size={16} />
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
    );
};

export default ImportView;
