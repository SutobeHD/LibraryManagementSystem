/**
 * SettingsLibrary — DB connection mode, watched folders, library filter.
 *
 * Owns its own tab-local state (scan-folder input, watcher status, lib status),
 * but persists everything through the parent's `setSettings` / `save` plumbing.
 */

import React, { useState, useEffect, useCallback } from 'react';
import api from '../../api/api';
import toast from 'react-hot-toast';
import { HEARTBEAT_INTERVAL_MS } from '../../config/constants';
import {
    Database, Shield, Folder, Plus, X, FolderOpen,
} from 'lucide-react';
import { Toggle, Section, Field } from './SettingsControls';

const SettingsLibrary = ({ settings, setSettings }) => {
    const [libStatus, setLibStatus] = useState({ mode: 'xml', loaded: false });
    const [scanFolderInput, setScanFolderInput] = useState('');
    const [watcherStatus, setWatcherStatus] = useState({ running: false, folders: [], pending_imports: 0 });

    const set = useCallback((key, value) => {
        setSettings(prev => ({ ...prev, [key]: value }));
    }, [setSettings]);

    // ── Folder watcher status (live polled while Library tab is open) ────────
    const refreshWatcherStatus = useCallback(() => {
        api.get('/api/library/folder-watcher/status')
            .then(res => setWatcherStatus(res.data || { running: false, folders: [], pending_imports: 0 }))
            .catch(() => {});
    }, []);

    useEffect(() => {
        refreshWatcherStatus();
        const id = setInterval(refreshWatcherStatus, HEARTBEAT_INTERVAL_MS);
        return () => clearInterval(id);
    }, [refreshWatcherStatus]);

    // ── Library status on mount ───────────────────────────────────────────────
    useEffect(() => {
        api.get('/api/library/status')
            .then(res => setLibStatus(res.data))
            .catch(() => {});
    }, []);

    // ── Library helpers ───────────────────────────────────────────────────────
    const switchMode = async (mode) => {
        try {
            const res = await api.post('/api/library/mode', { mode });
            if (res.data.status === 'success') {
                setLibStatus(prev => ({ ...prev, mode: res.data.mode }));
                toast.success(`Switched to ${res.data.mode.toUpperCase()} mode`);
            }
        } catch {
            toast.error('Failed to switch library mode');
        }
    };

    const addScanFolder = async () => {
        const folder = scanFolderInput.trim();
        if (!folder) return;
        const existing = settings.scan_folders || [];
        if (existing.includes(folder)) { toast.error('Folder already in list'); return; }
        try {
            const res = await api.post('/api/library/folder-watcher/add', { path: folder });
            const folders = res.data?.folders || [...existing, folder];
            set('scan_folders', folders);
            setScanFolderInput('');
            toast.success(`Watching: ${folder}`);
            refreshWatcherStatus();
        } catch (err) {
            toast.error(err?.response?.data?.detail || 'Failed to start watcher');
        }
    };

    const browseScanFolder = async () => {
        try {
            const { open } = await import('@tauri-apps/plugin-dialog');
            const picked = await open({
                directory: true,
                multiple: false,
                title: 'Choose folder to watch for new tracks',
            });
            if (typeof picked === 'string' && picked.length) {
                setScanFolderInput(picked);
            }
        } catch (err) {
            toast.error('Folder picker unavailable in browser mode — type the path manually.');
        }
    };

    const removeScanFolder = async (path) => {
        try {
            const res = await api.post('/api/library/folder-watcher/remove', { path });
            const folders = res.data?.folders ?? (settings.scan_folders || []).filter(f => f !== path);
            set('scan_folders', folders);
            refreshWatcherStatus();
        } catch {
            // Fall back to local-only removal so the user isn't stuck on a stale entry.
            set('scan_folders', (settings.scan_folders || []).filter(f => f !== path));
        }
    };

    const watchedSet = new Set((watcherStatus.folders || []).filter(f => f.alive).map(f => f.path));

    return (
        <div className="space-y-6">
            <Section title="Connection Mode" icon={Database}>
                <div className="grid grid-cols-2 gap-4">
                    {['xml', 'live'].map(mode => (
                        <button
                            key={mode}
                            onClick={() => switchMode(mode)}
                            className={`flex flex-col items-center p-5 rounded-2xl border transition-all ${
                                libStatus.mode === mode
                                    ? 'bg-amber2/20 border-amber2 shadow-lg shadow-amber2/10'
                                    : 'bg-mx-deepest/50 border-white/5 hover:border-white/20'}`}
                        >
                            <Database size={28} className={libStatus.mode === mode ? 'text-amber2 mb-2' : 'text-ink-muted mb-2'} />
                            <span className={`font-bold text-sm ${libStatus.mode === mode ? 'text-white' : 'text-ink-secondary'}`}>
                                {mode === 'xml' ? 'XML Snapshot' : 'Live Database'}
                            </span>
                            <p className="text-[10px] text-ink-muted mt-1 text-center">
                                {mode === 'xml' ? 'Static Rekordbox export' : 'Direct access (master.db)'}
                            </p>
                        </button>
                    ))}
                </div>
                <Toggle
                    checked={settings.remember_lib_mode}
                    onChange={v => set('remember_lib_mode', v)}
                    label="Remember mode selection"
                />
                {libStatus.mode === 'live' && (
                    <div className="p-3 bg-amber2/5 border border-amber2/20 rounded-xl">
                        <p className="text-xs text-ink-secondary font-mono truncate">{libStatus.path}</p>
                    </div>
                )}
            </Section>

            <Section title="Watched Folders" icon={FolderOpen}>
                <p className="text-xs text-ink-muted">
                    Folders monitored in the background. New audio files are auto-imported and analysed
                    as soon as they appear (or on next app start). An initial scan runs when you add a folder.
                </p>
                <div className="flex gap-2">
                    <input
                        value={scanFolderInput}
                        onChange={e => setScanFolderInput(e.target.value)}
                        onKeyDown={e => e.key === 'Enter' && addScanFolder()}
                        placeholder="C:\Music\My Tracks"
                        className="input-glass flex-1 text-sm"
                    />
                    <button
                        onClick={browseScanFolder}
                        title="Browse…"
                        className="px-3 py-2 rounded-xl text-xs bg-mx-shell/50 border border-white/10 hover:border-amber2/50 hover:bg-amber2/5 transition-all flex items-center gap-1.5"
                    >
                        <FolderOpen size={13} /> Browse
                    </button>
                    <button onClick={addScanFolder} className="px-3 py-2 bg-amber2/20 hover:bg-amber2/30 border border-amber2/30 rounded-xl text-amber2 transition-all">
                        <Plus size={16} />
                    </button>
                </div>
                {(settings.scan_folders || []).length > 0 && (
                    <div className="space-y-2 mt-1">
                        {(settings.scan_folders || []).map(f => {
                            const watching = watchedSet.has(f);
                            return (
                                <div key={f} className="flex items-center justify-between p-2.5 bg-mx-shell/60 rounded-xl border border-white/5">
                                    <div className="min-w-0 flex-1 flex items-center gap-2">
                                        <span
                                            className={`shrink-0 w-2 h-2 rounded-full ${watching ? 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.6)]' : 'bg-ink-muted'}`}
                                            title={watching ? 'Watching' : 'Not watching'}
                                        />
                                        <span className="text-xs text-ink-primary font-mono truncate">{f}</span>
                                        <span className={`text-[10px] uppercase tracking-wide ${watching ? 'text-emerald-300' : 'text-ink-muted'}`}>
                                            {watching ? 'Live' : 'Idle'}
                                        </span>
                                    </div>
                                    <button onClick={() => removeScanFolder(f)} className="ml-2 flex-shrink-0 text-ink-muted hover:text-red-400 transition-colors">
                                        <X size={14} />
                                    </button>
                                </div>
                            );
                        })}
                    </div>
                )}
                {watcherStatus.pending_imports > 0 && (
                    <p className="text-[11px] text-amber2 mt-1">
                        {watcherStatus.pending_imports} file{watcherStatus.pending_imports === 1 ? '' : 's'} queued for import…
                    </p>
                )}
            </Section>

            <Section title="Library Filter" icon={Shield}>
                <Toggle
                    checked={settings.hide_streaming}
                    onChange={v => set('hide_streaming', v)}
                    label="Hide Streaming Content"
                    sub="Filter SoundCloud, Spotify, Tidal, Beatport tracks from library view"
                />
            </Section>
        </div>
    );
};

export default SettingsLibrary;
