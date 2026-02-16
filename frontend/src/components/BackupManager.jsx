import React, { useState, useEffect } from 'react';
import { Database, Download, RotateCw, Archive, Clock, AlertTriangle, X, Check, Save } from 'lucide-react';
import api from '../api/api';


const BackupManager = ({ onClose }) => {
    const [backups, setBackups] = useState([]);
    const [loading, setLoading] = useState(true);
    const [creating, setCreating] = useState(false);
    const [restoring, setRestoring] = useState(null);
    const [error, setError] = useState(null);

    useEffect(() => {
        loadBackups();
    }, []);

    const loadBackups = async () => {
        setLoading(true);
        try {
            const res = await api.get('/api/library/backups');
            setBackups(res.data);
            setError(null);
        } catch (e) {
            setError("Failed to load backups");
            console.error(e);
        } finally {
            setLoading(false);
        }
    };

    const handleCreateBackup = async () => {
        setCreating(true);
        try {
            const res = await api.post('/api/library/sync'); // Reused endpoint for manual backup
            if (res.data.status === 'success') {
                await loadBackups();
            } else {
                setError("Failed to create backup: " + res.data.message);
            }
        } catch (e) {
            setError("Failed to create backup");
        } finally {
            setCreating(false);
        }
    };

    const handleRestore = async (filename) => {
        if (!confirm(`WARNING: Restore backup '${filename}'?\n\n- Current library will be overwritten.\n- A safety backup of the CURRENT state will be created first.\n- The application will need to restart.`)) {
            return;
        }

        setRestoring(filename);
        try {
            const res = await api.post('/api/library/restore', { filename });
            if (res.data.status === 'success') {
                alert("Restore Successful!\n\nThe application will now restart to load the restored database.");
                // Trigger generic shutdown/restart or just close
                window.close();
            } else {
                alert("Restore Failed: " + res.data.message);
            }
        } catch (e) {
            alert("Restore Failed: Connection Error");
        } finally {
            setRestoring(null);
        }
    };

    const formatSize = (bytes) => {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    };

    return (
        <div className="fixed inset-0 z-[200] bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-8 animate-fade-in">
            <div className="bg-slate-900 border border-white/10 rounded-2xl shadow-2xl w-full max-w-4xl h-[80vh] flex flex-col overflow-hidden">

                {/* Header */}
                <div className="p-6 border-b border-white/5 flex items-center justify-between bg-slate-900/50">
                    <div className="flex items-center gap-3">
                        <div className="w-10 h-10 rounded-lg bg-emerald-500/20 flex items-center justify-center text-emerald-400">
                            <Database size={20} />
                        </div>
                        <div>
                            <h2 className="text-xl font-bold text-white">Backup Manager</h2>
                            <p className="text-sm text-slate-400">Secure, Restore, and Manage your Library Snapshots</p>
                        </div>
                    </div>
                    <button onClick={onClose} className="p-2 hover:bg-white/5 rounded-full text-slate-400 hover:text-white transition-colors">
                        <X size={20} />
                    </button>
                </div>

                {/* Toolbar */}
                <div className="p-4 border-b border-white/5 flex items-center justify-between bg-white/[0.02]">
                    <div className="flex items-center gap-4">
                        <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-blue-500/10 border border-blue-500/20 text-blue-400 text-xs font-medium">
                            <Archive size={12} />
                            <span>Auto-Archival Active</span>
                        </div>
                    </div>
                    <button
                        onClick={handleCreateBackup}
                        disabled={creating}
                        className="flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg font-medium transition-all shadow-lg shadow-emerald-900/20 disabled:opacity-50 disabled:cursor-not-allowed"
                    >
                        {creating ? <RotateCw size={16} className="animate-spin" /> : <Save size={16} />}
                        <span>{creating ? 'Creating Snapshot...' : 'Create New Backup'}</span>
                    </button>
                </div>

                {/* List */}
                <div className="flex-1 overflow-y-auto p-4 space-y-2">
                    {error && (
                        <div className="p-4 rounded-lg bg-red-500/10 border border-red-500/20 text-red-400 flex items-center gap-2 mb-4">
                            <AlertTriangle size={16} />
                            {error}
                        </div>
                    )}

                    {loading ? (
                        <div className="flex flex-col items-center justify-center h-64 text-slate-500">
                            <RotateCw size={32} className="animate-spin mb-4 opacity-50" />
                            <p>Scanning backups...</p>
                        </div>
                    ) : backups.length === 0 ? (
                        <div className="flex flex-col items-center justify-center h-64 text-slate-500">
                            <Database size={48} className="mb-4 opacity-20" />
                            <p>No backups found.</p>
                        </div>
                    ) : (
                        <table className="w-full text-left border-collapse">
                            <thead className="text-xs font-semibold text-slate-500 uppercase tracking-wider sticky top-0 bg-slate-900 z-10">
                                <tr>
                                    <th className="pb-3 pl-4">Type</th>
                                    <th className="pb-3">Filename</th>
                                    <th className="pb-3">Date Created</th>
                                    <th className="pb-3">Size</th>
                                    <th className="pb-3 pr-4 text-right">Actions</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-800/50">
                                {backups.map((backup) => (
                                    <tr key={backup.filename} className="group hover:bg-white/[0.02] transition-colors">
                                        <td className="py-3 pl-4 align-middle">
                                            <span className={`inline-flex items-center px-2 py-1 rounded text-[10px] font-bold uppercase tracking-wide
                        ${backup.type === 'Session' ? 'bg-slate-700 text-slate-300' :
                                                    backup.type === 'Archive' ? 'bg-purple-900/30 text-purple-400 border border-purple-500/20' :
                                                        backup.type === 'Pre-Restore' ? 'bg-amber-900/20 text-amber-400 border border-amber-500/20' :
                                                            'bg-slate-800 text-slate-400'}`}>
                                                {backup.type === 'Archive' && <Archive size={10} className="mr-1" />}
                                                {backup.type}
                                            </span>
                                        </td>
                                        <td className="py-3 font-mono text-sm text-slate-300 group-hover:text-white transition-colors">
                                            {backup.filename}
                                        </td>
                                        <td className="py-3 text-sm text-slate-400">
                                            <div className="flex items-center gap-1.5">
                                                <Clock size={12} className="opacity-50" />
                                                {backup.date}
                                            </div>
                                        </td>
                                        <td className="py-3 text-sm text-slate-500 font-mono">
                                            {formatSize(backup.size)}
                                        </td>
                                        <td className="py-3 pr-4 text-right">
                                            <button
                                                onClick={() => handleRestore(backup.filename)}
                                                disabled={restoring}
                                                className="px-3 py-1.5 rounded hover:bg-cyan-500/10 text-cyan-400 hover:text-cyan-300 border border-transparent hover:border-cyan-500/30 transition-all text-xs font-medium inline-flex items-center gap-1.5 disabled:opacity-30"
                                            >
                                                {restoring === backup.filename ? <RotateCw size={12} className="animate-spin" /> : <RotateCw size={12} />}
                                                <span>Restore</span>
                                            </button>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    )}
                </div>

                {/* Footer */}
                <div className="p-4 border-t border-white/5 bg-slate-900/50 text-xs text-slate-500 flex justify-between">
                    <p>Session backups are auto-pruned (keep last 3). Archives are permanent.</p>
                    <p>Total Backups: {backups.length}</p>
                </div>
            </div>
        </div>
    );
};

export default BackupManager;
