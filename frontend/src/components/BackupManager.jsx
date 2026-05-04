import React, { useState, useEffect, useCallback } from 'react';
import {
    Database, Download, RotateCw, Clock, AlertTriangle, X, Check, Save,
    GitCommit, ChevronRight, ChevronDown, Archive, Trash2, Loader2, Plus, History
} from 'lucide-react';
import api from '../api/api';
import toast from 'react-hot-toast';

const formatSize = (bytes) => {
    if (!bytes) return '0 B';
    const k = 1024;
    const s = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${(bytes / Math.pow(k, i)).toFixed(1)} ${s[i]}`;
};

const formatDate = (iso) => {
    if (!iso) return '';
    const d = new Date(iso);
    return d.toLocaleString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
};

const timeSince = (iso) => {
    if (!iso) return '';
    const diff = Date.now() - new Date(iso).getTime();
    if (diff < 60000) return 'Just now';
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
    return `${Math.floor(diff / 86400000)}d ago`;
};

const BackupManager = ({ onClose }) => {
    const [backups, setBackups] = useState([]);
    const [loading, setLoading] = useState(true);
    const [creating, setCreating] = useState(false);
    const [restoring, setRestoring] = useState(null);
    const [expandedCommit, setExpandedCommit] = useState(null);
    const [commitDiff, setCommitDiff] = useState(null);

    const loadBackups = useCallback(async () => {
        setLoading(true);
        try {
            const res = await api.get('/api/library/backups');
            setBackups(res.data || []);
        } catch (e) {
            toast.error('Failed to load backups');
        }
        setLoading(false);
    }, []);

    useEffect(() => { loadBackups(); }, [loadBackups]);

    const createBackup = async () => {
        setCreating(true);
        try {
            const res = await api.post('/api/library/backup');
            if (res.data.status === 'unchanged') {
                toast('No changes to backup', { icon: '📋' });
            } else if (res.data.status === 'success' || !res.data.status) {
                toast.success(`Backup created: ${res.data.hash || 'OK'}`);
            } else {
                toast.error(res.data.message || 'Backup failed');
            }
            loadBackups();
        } catch (e) {
            toast.error('Backup failed');
        }
        setCreating(false);
    };

    const restoreBackup = async (backup) => {
        const confirmMsg = backup.is_legacy
            ? `Restore legacy backup "${backup.filename}"? Current state will be backed up automatically.`
            : `Restore to commit ${backup.hash}? Current state will be backed up automatically.`;

        if (!confirm(confirmMsg)) return;

        setRestoring(backup.hash);
        try {
            const payload = backup.is_legacy
                ? { filename: backup.filename }
                : { filename: '', commit_hash: backup.hash };

            const res = await api.post('/api/library/restore', payload);
            if (res.data.status === 'success') {
                toast.success(res.data.message || 'Restored successfully');
                loadBackups();
            } else {
                toast.error(res.data.message || 'Restore failed');
            }
        } catch (e) {
            toast.error('Restore failed');
        }
        setRestoring(null);
    };

    const viewDiff = async (hash) => {
        if (expandedCommit === hash) {
            setExpandedCommit(null);
            setCommitDiff(null);
            return;
        }
        setExpandedCommit(hash);
        try {
            const res = await api.get(`/api/library/backup/${hash}/diff`);
            setCommitDiff(res.data);
        } catch {
            setCommitDiff(null);
        }
    };

    return (
        <div className="fixed inset-0 z-[100] bg-black/60 backdrop-blur-sm flex items-center justify-center p-4 animate-fade-in">
            <div className="w-full max-w-2xl max-h-[85vh] bg-mx-deepest rounded-3xl border border-white/10 shadow-2xl flex flex-col overflow-hidden">
                {/* Header */}
                <div className="p-6 pb-4 border-b border-white/5 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                        <div className="p-2.5 bg-emerald-500/20 rounded-xl border border-emerald-500/30">
                            <History size={22} className="text-emerald-400" />
                        </div>
                        <div>
                            <h2 className="text-xl font-black italic uppercase tracking-tight">Backup Timeline</h2>
                            <p className="text-ink-muted text-xs mt-0.5">{backups.length} backups · Incremental engine</p>
                        </div>
                    </div>
                    <div className="flex items-center gap-2">
                        <button onClick={createBackup} disabled={creating}
                            className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-400 rounded-lg text-xs font-bold border border-emerald-500/30 transition-all disabled:opacity-50"
                        >
                            {creating ? <Loader2 size={14} className="animate-spin" /> : <Plus size={14} />}
                            New Backup
                        </button>
                        <button onClick={onClose} className="p-2 hover:bg-white/5 rounded-lg transition-colors">
                            <X size={18} className="text-ink-secondary" />
                        </button>
                    </div>
                </div>

                {/* Timeline */}
                <div className="flex-1 overflow-y-auto p-4">
                    {loading ? (
                        <div className="flex items-center justify-center h-32">
                            <Loader2 size={24} className="animate-spin text-emerald-400" />
                        </div>
                    ) : backups.length === 0 ? (
                        <div className="flex flex-col items-center justify-center h-32 text-center">
                            <Archive size={32} className="text-ink-placeholder mb-3" />
                            <p className="text-ink-muted text-sm">No backups yet</p>
                            <p className="text-ink-placeholder text-xs">Click "New Backup" to create your first snapshot</p>
                        </div>
                    ) : (
                        <div className="relative">
                            {/* Timeline Line */}
                            <div className="absolute left-4 top-0 bottom-0 w-px bg-white/5" />

                            {backups.map((backup, i) => {
                                const isLegacy = backup.is_legacy;
                                const isExpanded = expandedCommit === backup.hash;
                                const stats = backup.stats || {};
                                const hasChanges = stats.modified || stats.added || stats.deleted;

                                return (
                                    <div key={backup.hash || i} className="relative pl-10 mb-1">
                                        {/* Timeline Dot */}
                                        <div className={`absolute left-[11px] top-4 w-2.5 h-2.5 rounded-full border-2 z-10 ${isLegacy
                                                ? 'bg-amber-500 border-amber-500/50'
                                                : i === 0
                                                    ? 'bg-emerald-400 border-emerald-400/50'
                                                    : 'bg-mx-hover border-slate-600'
                                            }`} />

                                        <div className={`p-3 rounded-xl border transition-all hover:bg-white/[0.02] ${isExpanded ? 'bg-white/[0.03] border-white/10' : 'border-transparent'
                                            }`}>
                                            <div className="flex items-center justify-between gap-3">
                                                <div className="flex-1 min-w-0">
                                                    <div className="flex items-center gap-2">
                                                        {isLegacy ? (
                                                            <span className="text-[9px] font-bold px-1.5 py-0.5 bg-amber-500/20 text-amber-400 rounded">LEGACY</span>
                                                        ) : (
                                                            <code className="text-[10px] font-mono text-ink-muted bg-white/5 px-1.5 py-0.5 rounded">{backup.hash}</code>
                                                        )}
                                                        <span className="text-xs text-ink-primary truncate">{backup.message}</span>
                                                    </div>
                                                    <div className="flex items-center gap-3 mt-1 text-[10px] text-ink-placeholder">
                                                        <span className="flex items-center gap-1"><Clock size={9} /> {formatDate(backup.timestamp)}</span>
                                                        <span>{timeSince(backup.timestamp)}</span>
                                                        {backup.size && <span>{formatSize(backup.size)}</span>}
                                                        {hasChanges && !isLegacy && (
                                                            <span className="text-ink-muted">
                                                                {stats.added > 0 && <span className="text-emerald-400">+{stats.added}</span>}
                                                                {stats.modified > 0 && <span className="text-amber-400 ml-1">~{stats.modified}</span>}
                                                                {stats.deleted > 0 && <span className="text-red-400 ml-1">-{stats.deleted}</span>}
                                                            </span>
                                                        )}
                                                    </div>
                                                </div>
                                                <div className="flex items-center gap-1">
                                                    {!isLegacy && (
                                                        <button onClick={() => viewDiff(backup.hash)}
                                                            className="p-1.5 hover:bg-white/5 rounded-lg transition-colors text-ink-muted hover:text-ink-primary"
                                                            title="View changes"
                                                        >
                                                            <ChevronRight size={14} className={`transition-transform ${isExpanded ? 'rotate-90' : ''}`} />
                                                        </button>
                                                    )}
                                                    <button
                                                        onClick={() => restoreBackup(backup)}
                                                        disabled={restoring === backup.hash}
                                                        className="p-1.5 hover:bg-emerald-500/10 rounded-lg transition-colors text-ink-muted hover:text-emerald-400"
                                                        title="Restore this backup"
                                                    >
                                                        {restoring === backup.hash
                                                            ? <Loader2 size={14} className="animate-spin" />
                                                            : <RotateCw size={14} />}
                                                    </button>
                                                </div>
                                            </div>

                                            {/* Expanded Diff View */}
                                            {isExpanded && commitDiff && (
                                                <div className="mt-3 p-3 bg-white/[0.02] rounded-xl border border-white/5 text-[11px]">
                                                    {Object.entries(commitDiff.tables || {}).map(([table, info]) => (
                                                        <div key={table} className="mb-2 last:mb-0">
                                                            <div className="font-bold text-ink-secondary mb-1 flex items-center gap-2">
                                                                <Database size={10} />
                                                                {table}
                                                                <span className="text-emerald-400">+{info.added}</span>
                                                                <span className="text-amber-400">~{info.modified}</span>
                                                                <span className="text-red-400">-{info.deleted}</span>
                                                            </div>
                                                        </div>
                                                    ))}
                                                    {Object.keys(commitDiff.tables || {}).length === 0 && (
                                                        <div className="text-ink-placeholder text-center py-2">No detailed diff available</div>
                                                    )}
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                );
                            })}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

export default BackupManager;
