import React, { useState } from 'react';
import api from '../api/api';
import { confirmModal } from './ConfirmModal';
import { Upload, FileCode, CheckCircle, AlertTriangle, Zap, Server } from 'lucide-react';

const XmlCleanView = () => {
    const [dragActive, setDragActive] = useState(false);
    const [file, setFile] = useState(null);
    const [scanning, setScanning] = useState(false);
    const [scanResult, setScanResult] = useState(null);
    const [error, setError] = useState(null);

    const handleDrag = (e) => { e.preventDefault(); e.stopPropagation(); setDragActive(e.type === "dragenter" || e.type === "dragover"); };
    const handleDrop = (e) => { e.preventDefault(); e.stopPropagation(); setDragActive(false); if (e.dataTransfer.files?.[0]) setFile(e.dataTransfer.files[0]); };
    const handleChange = (e) => { if (e.target.files?.[0]) setFile(e.target.files[0]); };

    const startScan = async () => {
        if (!file) return;
        setScanning(true); setError(null); setScanResult(null);

        const formData = new FormData();
        formData.append("file", file);
        formData.append("artist_folder", "_AUTO_ARTISTS");
        formData.append("label_folder", "_AUTO_LABELS");

        try {
            // Using existing endpoint but improved backend logic
            const res = await api.post('/api/xml/clean', formData);
            // Expected response: { status: "success", tracks: 1234, playlists: 50, ... }
            if (res.data.status === "success" || res.data.tracks !== undefined) {
                setScanResult(res.data);
            } else {
                // Fallback for file download response (old behavior compatibility)
                setScanResult({ tracks: "?", playlists: "?" });
            }
        } catch (err) {
            console.error(err);
            setError("Scan failed. Is the backend running?");
        } finally {
            setScanning(false);
        }
    };

    return (
        <div className="p-12 h-full flex flex-col items-center justify-center bg-transparent text-white overflow-y-auto">
            <div className="text-center mb-10">
                <h1 className="text-5xl font-bold mb-4 flex items-center justify-center gap-4 drop-shadow-lg">
                    <Server size={48} className="text-amber2" />
                    <span className="bg-gradient-to-r from-amber2 to-amber2-press bg-clip-text text-transparent">Library Manager</span>
                </h1>
                <p className="text-ink-secondary text-lg max-w-xl mx-auto leading-relaxed">
                    Import your <code>rekordbox.xml</code> to load your library.<br />
                    We will scan for tracks, playlists, and metadata.
                </p>
            </div>

            {!scanResult ? (
                <div className="w-full max-w-2xl flex flex-col gap-6">
                    <div
                        className={`w-full h-64 border-2 border-dashed rounded-3xl flex flex-col items-center justify-center transition-all duration-300 cursor-pointer shadow-xl backdrop-blur-sm 
                            ${dragActive ? 'border-amber2 bg-amber2/10 scale-105' : 'border-line-default bg-mx-shell/50 hover:border-amber2/50 hover:bg-mx-card/80'}`}
                        onDragEnter={handleDrag} onDragLeave={handleDrag} onDragOver={handleDrag} onDrop={handleDrop}
                        onClick={() => !scanning && document.getElementById('fileUpload').click()}
                    >
                        <input type="file" id="fileUpload" className="hidden" onChange={handleChange} accept=".xml" disabled={scanning} />

                        {file ? (
                            <div className="text-center animate-fade-in">
                                <div className="w-16 h-16 bg-blue-500/20 rounded-full flex items-center justify-center mx-auto mb-4">
                                    <FileCode size={32} className="text-blue-400" />
                                </div>
                                <p className="font-bold text-xl text-white mb-1">{file.name}</p>
                                <p className="text-sm font-mono text-amber2">{(file.size / 1024 / 1024).toFixed(2)} MB</p>
                            </div>
                        ) : (
                            <div className="text-center text-ink-muted">
                                <Upload size={48} className="mx-auto mb-4 opacity-50" />
                                <p className="text-lg font-medium mb-1">Drop rekordbox.xml here</p>
                                <p className="text-sm opacity-60">or click to browse</p>
                            </div>
                        )}
                    </div>

                    {file ? (
                        <button
                            onClick={startScan}
                            disabled={scanning}
                            className={`w-full h-16 rounded-xl font-bold text-lg shadow-lg flex items-center justify-center gap-3 transition-all
                                ${scanning ? 'bg-mx-card text-ink-secondary cursor-wait' : 'btn-primary hover:scale-[1.02] active:scale-[0.98]'}`}
                        >
                            {scanning ? (
                                <>
                                    <div className="w-5 h-5 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                                    <span>Scanning Library...</span>
                                </>
                            ) : (
                                <>
                                    <Zap size={20} fill="currentColor" />
                                    <span>Scan Library</span>
                                </>
                            )}
                        </button>
                    ) : (
                        <div className="flex flex-col gap-4">
                            <div className="h-px bg-white/5 w-full my-2" />
                            <button
                                onClick={async () => {
                                    const ok = await confirmModal({
                                        title: 'Create new library?',
                                        message: 'Create a fresh, empty library? (rekordbox.xml)',
                                        confirmLabel: 'Create',
                                    });
                                    if (ok) {
                                        const res = await api.post('/api/library/new');
                                        setScanResult({ tracks: 0, playlists: 0 });
                                    }
                                }}
                                className="w-full h-12 rounded-xl font-bold text-xs uppercase tracking-widest border border-amber2/30 text-amber2 hover:bg-amber2/10 transition-all flex items-center justify-center gap-2"
                            >
                                <Zap size={14} /> Create New Empty Library
                            </button>
                        </div>
                    )}
                </div>
            ) : (
                <div className="w-full max-w-2xl bg-gradient-to-br from-green-900/20 to-emerald-900/20 border border-green-500/30 rounded-3xl p-10 text-center animate-slide-up shadow-2xl backdrop-blur-xl">
                    <div className="w-20 h-20 bg-green-500/20 rounded-full flex items-center justify-center mx-auto mb-6 shadow-[0_0_30px_rgba(34,197,94,0.3)]">
                        <CheckCircle size={40} className="text-green-400" />
                    </div>
                    <h2 className="text-3xl font-bold mb-2 text-white">Library Loaded</h2>
                    <p className="text-ink-secondary mb-8">Your music is ready to explore.</p>

                    <div className="grid grid-cols-2 gap-4 mb-8">
                        <div className="bg-mx-deepest/50 rounded-xl p-4 border border-white/5">
                            <div className="text-ink-secondary text-xs uppercase font-bold tracking-widest mb-1">Tracks</div>
                            <div className="text-2xl font-mono text-amber2">{scanResult.tracks || 0}</div>
                        </div>
                        <div className="bg-mx-deepest/50 rounded-xl p-4 border border-white/5">
                            <div className="text-ink-secondary text-xs uppercase font-bold tracking-widest mb-1">Playlists</div>
                            <div className="text-2xl font-mono text-purple-400">{scanResult.playlists || 0}</div>
                        </div>
                    </div>

                    <button onClick={() => { setFile(null); setScanResult(null); }} className="text-sm text-ink-muted hover:text-white underline decoration-slate-700 hover:decoration-white transition-all">
                        Load a different file
                    </button>
                </div>
            )}

            {error && (
                <div className="mt-6 p-4 bg-red-900/40 border border-red-500/50 rounded-xl flex items-center gap-3 text-red-200 animate-shake backdrop-blur-md">
                    <AlertTriangle size={20} className="text-red-400" />
                    <span>{error}</span>
                </div>
            )}
        </div>
    );
};

export default XmlCleanView;
