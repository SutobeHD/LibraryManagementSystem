/**
 * SettingsView — Tabbed preferences panel.
 *
 * Tabs:
 *   Library   — DB mode, scan folders, library filter
 *   Backup    — retention, auto-backup interval, archive frequency
 *   Export    — format, bitrate, sample rate
 *   Audio     — output device selection (via Tauri CPAL enumeration)
 *   Analysis  — quality preset (Fast / Standard / Thorough)
 *   Appearance— waveform band colors, language/locale
 *   Shortcuts — configurable DAW keyboard shortcuts
 *   Network   — HTTP proxy for SoundCloud API calls
 *
 * All settings are persisted via POST /api/settings (arbitrary JSON).
 * The backend's SettingsManager handles load/save transparently.
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import api from '../api/api';
import toast from 'react-hot-toast';
import {
    Settings, Database, HardDrive, RefreshCw, Save, Trash2, Shield,
    User, Globe, Moon, Bell, Info, CheckCircle, AlertCircle, FileOutput,
    Power, Folder, Check, Plus, X, Speaker, Sliders, Keyboard,
    Wifi, Palette, Music, FolderOpen, ChevronRight
} from 'lucide-react';

// ── Default settings ──────────────────────────────────────────────────────────
// Merged with whatever the backend returns; unrecognised keys are preserved.
const DEFAULTS = {
    // Library
    backup_retention_days: 7,
    auto_backup: true,
    archive_frequency: 'daily',
    auto_backup_interval_min: 30,   // 0 = session-only
    remember_lib_mode: false,
    hide_streaming: false,
    scan_folders: [],               // extra watched folders

    // Export
    export_format: 'xml',
    export_bitrate: '320',
    export_sample_rate: '44100',
    default_export_dir: '',           // Default output folder for audio exports (DAW). Empty = backend ./exports.

    // Audio
    audio_output_device: '',        // '' = system default

    // Analysis
    analysis_quality: 'standard',  // 'fast' | 'standard' | 'thorough'
    ranking_filter_mode: 'all',
    insights_bitrate_threshold: 320,
    insights_playcount_threshold: 0,
    artist_view_threshold: 0,

    // Appearance
    waveform_visual_mode: 'blue',
    waveform_color_low: '#ef4444',
    waveform_color_mid: '#22c55e',
    waveform_color_high: '#3b82f6',
    locale: 'de',                  // 'de' | 'en'

    // Shortcuts (action → key-combo string)
    shortcuts: {
        play_pause:  'Space',
        jump_start:  'Home',
        jump_end:    'End',
        scrub_back:  'ArrowLeft',
        scrub_fwd:   'ArrowRight',
        split:       'Ctrl+E',
        delete:      'Delete',
        undo:        'Ctrl+Z',
        redo:        'Ctrl+Shift+Z',
        copy:        'Ctrl+C',
        paste:       'Ctrl+V',
        duplicate:   'Ctrl+D',
        save:        'Ctrl+S',
        open:        'Ctrl+O',
    },

    // Network
    http_proxy: '',
    sc_sync_folder_id: '',
};

const SHORTCUT_LABELS = {
    play_pause:  'Play / Pause',
    jump_start:  'Jump to Start',
    jump_end:    'Jump to End',
    scrub_back:  'Scrub Back (1 Beat)',
    scrub_fwd:   'Scrub Forward (1 Beat)',
    split:       'Split Region',
    delete:      'Ripple Delete',
    undo:        'Undo',
    redo:        'Redo',
    copy:        'Copy Selection',
    paste:       'Paste / Insert',
    duplicate:   'Duplicate',
    save:        'Save Project',
    open:        'Open Project',
};

const TABS = [
    { id: 'library',    label: 'Library',    icon: Database },
    { id: 'backup',     label: 'Backup',     icon: HardDrive },
    { id: 'export',     label: 'Export',     icon: FileOutput },
    { id: 'usb',        label: 'USB Profiles', icon: HardDrive },
    { id: 'audio',      label: 'Audio',      icon: Music },
    { id: 'analysis',   label: 'Analysis',   icon: Sliders },
    { id: 'appearance', label: 'Appearance', icon: Palette },
    { id: 'shortcuts',  label: 'Shortcuts',  icon: Keyboard },
    { id: 'network',    label: 'Network',    icon: Wifi },
];

const USB_TYPE_LABELS = {
    MainCollection: 'Main Collection',
    Collection:     'Collection',
    PartCollection: 'Part Collection',
    SetStick:       'Set Stick',
};

const AUDIO_FORMATS = [
    { id: 'original', label: 'Original (no conversion)' },
    { id: 'mp3',      label: 'MP3' },
    { id: 'flac',     label: 'FLAC (lossless)' },
    { id: 'wav',      label: 'WAV (uncompressed)' },
    { id: 'aac',      label: 'AAC (m4a)' },
];

const BITRATES     = ['128', '192', '256', '320'];
const SAMPLE_RATES = ['44100', '48000', '96000'];

// ── Helpers ───────────────────────────────────────────────────────────────────

/** Render a toggle switch */
const Toggle = ({ checked, onChange, label, sub }) => (
    <div className="flex items-center justify-between">
        <div>
            <p className="text-sm font-semibold text-white">{label}</p>
            {sub && <p className="text-xs text-ink-muted mt-0.5">{sub}</p>}
        </div>
        <button
            role="switch"
            aria-checked={checked}
            onClick={() => onChange(!checked)}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${checked ? 'bg-amber2' : 'bg-mx-hover'}`}
        >
            <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${checked ? 'translate-x-6' : 'translate-x-1'}`} />
        </button>
    </div>
);

/** Section wrapper */
const Section = ({ title, icon: Icon, children }) => (
    <div className="bg-mx-deepest/50 rounded-2xl p-6 border border-white/5 space-y-5">
        <h2 className="text-xs font-bold text-amber2 uppercase tracking-widest flex items-center gap-2">
            {Icon && <Icon size={14} />}{title}
        </h2>
        {children}
    </div>
);

/** Label + select/input row */
const Field = ({ label, children }) => (
    <div>
        <label className="text-xs text-ink-secondary mb-2 block font-bold uppercase tracking-wide">{label}</label>
        {children}
    </div>
);

/** Native styled <select> for the USB profile form */
const Select = ({ value, onChange, options }) => (
    <select
        className="input-glass text-tiny w-full"
        value={value}
        onChange={e => onChange(e.target.value)}
    >
        {options.map(o => (
            <option key={o.id} value={o.id}>{o.label}</option>
        ))}
    </select>
);

// ── Keyboard capture ──────────────────────────────────────────────────────────
const KeyCapture = ({ binding, onCapture }) => {
    const [capturing, setCapturing] = useState(false);
    const ref = useRef(null);

    const start = () => {
        setCapturing(true);
        setTimeout(() => ref.current?.focus(), 50);
    };

    const handleKey = (e) => {
        e.preventDefault();
        e.stopPropagation();

        // Ignore modifier-only presses
        if (['Control', 'Shift', 'Alt', 'Meta'].includes(e.key)) return;

        // Escape cancels capture
        if (e.key === 'Escape') { setCapturing(false); return; }

        let combo = '';
        if (e.ctrlKey)  combo += 'Ctrl+';
        if (e.shiftKey) combo += 'Shift+';
        if (e.altKey)   combo += 'Alt+';

        if (e.code === 'Space')        combo += 'Space';
        else if (e.key.length === 1)   combo += e.key.toUpperCase();
        else                           combo += e.key;

        onCapture(combo);
        setCapturing(false);
    };

    return (
        <div className="flex items-center gap-2">
            <button
                ref={ref}
                onKeyDown={capturing ? handleKey : undefined}
                onBlur={() => setCapturing(false)}
                onClick={start}
                className={`
                    px-3 py-1.5 rounded-lg text-xs font-mono border transition-all min-w-[120px] text-center
                    ${capturing
                        ? 'bg-amber2/20 border-amber2 text-amber2-hover animate-pulse'
                        : 'bg-mx-card border-white/10 text-ink-primary hover:border-amber2/50 hover:text-white'}
                `}
            >
                {capturing ? 'Press a key…' : (binding || '—')}
            </button>
            {!capturing && (
                <button onClick={start} title="Edit shortcut" className="text-ink-muted hover:text-amber2 transition-colors">
                    <ChevronRight size={12} />
                </button>
            )}
        </div>
    );
};

// ── Main component ────────────────────────────────────────────────────────────
const SettingsView = () => {
    const [settings, setSettings] = useState(DEFAULTS);
    const [activeTab, setActiveTab] = useState('library');
    const [saving, setSaving] = useState(false);
    const [libStatus, setLibStatus] = useState({ mode: 'xml', loaded: false });
    const [audioDevices, setAudioDevices] = useState(['System Default']);
    const [scanFolderInput, setScanFolderInput] = useState('');
    const [watcherStatus, setWatcherStatus] = useState({ running: false, folders: [], pending_imports: 0 });
    const [usbProfiles, setUsbProfiles] = useState([]);
    const [usbProfilesLoading, setUsbProfilesLoading] = useState(false);
    const [editingProfileId, setEditingProfileId] = useState(null);

    // ── Folder watcher status (live polled while Library tab is open) ────────
    const refreshWatcherStatus = useCallback(() => {
        api.get('/api/library/folder-watcher/status')
            .then(res => setWatcherStatus(res.data || { running: false, folders: [], pending_imports: 0 }))
            .catch(() => {});
    }, []);

    useEffect(() => {
        if (activeTab !== 'library') return;
        refreshWatcherStatus();
        const id = setInterval(refreshWatcherStatus, 5000);
        return () => clearInterval(id);
    }, [activeTab, refreshWatcherStatus]);

    // ── USB profiles loader (lazy on tab activation) ──────────────────────────
    const loadUsbProfiles = useCallback(() => {
        setUsbProfilesLoading(true);
        api.get('/api/usb/profiles')
            .then(res => setUsbProfiles(Array.isArray(res.data) ? res.data : []))
            .catch(err => console.warn('[Settings/USB] load profiles failed', err))
            .finally(() => setUsbProfilesLoading(false));
    }, []);

    useEffect(() => {
        if (activeTab === 'usb') loadUsbProfiles();
    }, [activeTab, loadUsbProfiles]);

    const updateUsbProfile = useCallback(async (profile, patch) => {
        try {
            const updated = { ...profile, ...patch };
            await api.post('/api/usb/profiles', updated);
            setUsbProfiles(prev => prev.map(p => p.device_id === profile.device_id ? updated : p));
            toast.success('Profile updated');
        } catch (err) {
            toast.error('Failed to update profile');
            console.error('[Settings/USB] update failed', err);
        }
    }, []);

    const deleteUsbProfile = useCallback(async (deviceId) => {
        if (!confirm('Delete this USB profile? This does not affect the actual USB drive.')) return;
        try {
            await api.delete(`/api/usb/profiles/${deviceId}`);
            setUsbProfiles(prev => prev.filter(p => p.device_id !== deviceId));
            toast.success('Profile deleted');
        } catch {
            toast.error('Failed to delete profile');
        }
    }, []);

    // ── Load settings + library status on mount ───────────────────────────────
    useEffect(() => {
        api.get('/api/settings')
            .then(res => setSettings({ ...DEFAULTS, ...res.data, shortcuts: { ...DEFAULTS.shortcuts, ...(res.data.shortcuts || {}) } }))
            .catch(() => {});
        api.get('/api/library/status')
            .then(res => setLibStatus(res.data))
            .catch(() => {});

        // Enumerate CPAL audio devices (Tauri desktop only)
        if (window.__TAURI__) {
            import('@tauri-apps/api/core').then(({ invoke }) => {
                invoke('list_audio_devices')
                    .then(devices => setAudioDevices(devices))
                    .catch(e => console.warn('[Settings] list_audio_devices failed:', e));
            });
        }
    }, []);

    const set = useCallback((key, value) => {
        setSettings(prev => ({ ...prev, [key]: value }));
    }, []);

    const setShortcut = useCallback((action, combo) => {
        setSettings(prev => ({
            ...prev,
            shortcuts: { ...(prev.shortcuts || {}), [action]: combo },
        }));
    }, []);

    // ── Persist ────────────────────────────────────────────────────────────────
    const saveSettings = async () => {
        setSaving(true);
        try {
            await api.post('/api/settings', settings);
            toast.success('Settings saved');
        } catch {
            toast.error('Failed to save settings');
        } finally {
            setSaving(false);
        }
    };

    // ── Library helpers ────────────────────────────────────────────────────────
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

    const triggerBackup = async () => {
        try {
            const res = await api.post('/api/library/backup');
            if (res.data.status === 'success') toast.success('Backup created');
            else toast.error('Backup failed: ' + (res.data.message || 'Unknown error'));
        } catch {
            toast.error('Backup error');
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

    // ── Standalone library (self-managed XML, no Rekordbox needed) ─────────
    const [standaloneInfo, setStandaloneInfo] = useState({ path: '', default_path: '', exists: false, is_active: false });

    const refreshStandaloneInfo = useCallback(() => {
        api.get('/api/library/standalone/info')
            .then(res => setStandaloneInfo(res.data || {}))
            .catch(() => {});
    }, []);

    useEffect(() => {
        if (activeTab === 'library') refreshStandaloneInfo();
    }, [activeTab, refreshStandaloneInfo, libStatus.mode]);

    const initStandalone = async (customPath = '') => {
        try {
            const res = await api.post('/api/library/standalone/init', { path: customPath || '' });
            toast.success(`Standalone library ready (${res.data.track_count} tracks)`);
            setLibStatus({ mode: 'standalone', loaded: true, path: res.data.path });
            refreshStandaloneInfo();
        } catch (err) {
            toast.error(err?.response?.data?.detail || 'Could not initialise standalone library');
        }
    };

    const browseStandalonePath = async () => {
        try {
            const { save } = await import('@tauri-apps/plugin-dialog');
            const picked = await save({
                title: 'Choose location for your standalone library XML',
                defaultPath: standaloneInfo.path || standaloneInfo.default_path,
                filters: [{ name: 'Rekordbox XML', extensions: ['xml'] }],
            });
            if (typeof picked === 'string' && picked.length) {
                await api.post('/api/library/standalone/path', { path: picked });
                toast.success('Standalone library path updated');
                refreshStandaloneInfo();
            }
        } catch {
            toast.error('Picker unavailable — paste the path manually instead.');
        }
    };

    // ── Tab content renderers ──────────────────────────────────────────────────

    const LIB_MODES = [
        { id: 'live',       label: 'Live Database', sub: 'Direct master.db (Rekordbox installed)' },
        { id: 'xml',        label: 'XML Snapshot',  sub: 'Static Rekordbox export' },
        { id: 'standalone', label: 'Standalone',    sub: 'Own library — no Rekordbox needed' },
    ];

    const renderLibrary = () => (
        <div className="space-y-6">
            <Section title="Connection Mode" icon={Database}>
                <div className="grid grid-cols-3 gap-3">
                    {LIB_MODES.map(({ id, label, sub }) => (
                        <button
                            key={id}
                            onClick={() => id === 'standalone' ? initStandalone() : switchMode(id)}
                            className={`flex flex-col items-center p-4 rounded-2xl border transition-all ${
                                libStatus.mode === id
                                    ? 'bg-amber2/20 border-amber2 shadow-lg shadow-amber2/10'
                                    : 'bg-mx-deepest/50 border-white/5 hover:border-white/20'}`}
                        >
                            <Database size={24} className={libStatus.mode === id ? 'text-amber2 mb-1.5' : 'text-ink-muted mb-1.5'} />
                            <span className={`font-bold text-[12px] ${libStatus.mode === id ? 'text-white' : 'text-ink-secondary'}`}>
                                {label}
                            </span>
                            <p className="text-[10px] text-ink-muted mt-1 text-center">{sub}</p>
                        </button>
                    ))}
                </div>
                <Toggle
                    checked={settings.remember_lib_mode}
                    onChange={v => set('remember_lib_mode', v)}
                    label="Remember mode selection"
                />
                {libStatus.mode === 'live' && (
                    <div className="flex items-center justify-between p-3 bg-amber2/5 border border-amber2/20 rounded-xl">
                        <p className="text-xs text-ink-secondary font-mono truncate">{libStatus.path}</p>
                        <button onClick={triggerBackup} className="ml-3 flex-shrink-0 text-xs text-amber2 hover:text-amber2-hover flex items-center gap-1.5 border border-amber2/20 rounded-lg px-3 py-1.5 hover:bg-amber2/10 transition-all">
                            <Save size={12} /> Backup
                        </button>
                    </div>
                )}
                {libStatus.mode === 'standalone' && (
                    <div className="space-y-2 p-3 bg-emerald-500/5 border border-emerald-500/20 rounded-xl">
                        <div className="flex items-center justify-between gap-3">
                            <div className="min-w-0 flex-1">
                                <p className="text-[10px] uppercase tracking-wide text-emerald-300 font-semibold mb-1">Standalone library file</p>
                                <p className="text-xs text-ink-secondary font-mono truncate">{standaloneInfo.path || libStatus.path}</p>
                            </div>
                            <button
                                onClick={browseStandalonePath}
                                className="flex-shrink-0 text-xs text-emerald-300 hover:text-emerald-200 flex items-center gap-1.5 border border-emerald-500/30 rounded-lg px-3 py-1.5 hover:bg-emerald-500/10 transition-all"
                            >
                                <FolderOpen size={12} /> Change…
                            </button>
                        </div>
                        <p className="text-[10px] text-ink-muted">
                            Self-managed Rekordbox-XML library. No Rekordbox install needed; imports, USB sync, analysis and CDJ export all work directly off this file.
                        </p>
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

    const renderBackup = () => (
        <div className="space-y-6">
            <Section title="Retention" icon={HardDrive}>
                <Field label="Keep backups for (days)">
                    <input
                        type="number" min="1" max="365"
                        value={settings.backup_retention_days}
                        onChange={e => set('backup_retention_days', parseInt(e.target.value) || 7)}
                        className="input-glass w-32"
                    />
                </Field>
                <Field label="Archive frequency">
                    <select value={settings.archive_frequency || 'daily'} onChange={e => set('archive_frequency', e.target.value)} className="input-glass w-full">
                        <option value="off">Off (session snapshots only)</option>
                        <option value="daily">Daily</option>
                        <option value="weekly">Weekly</option>
                        <option value="monthly">Monthly</option>
                    </select>
                </Field>
            </Section>

            <Section title="Auto-Backup" icon={Save}>
                <Toggle
                    checked={settings.auto_backup}
                    onChange={v => set('auto_backup', v)}
                    label="Auto-backup on launch"
                    sub="Creates a snapshot every time the app starts"
                />
                <Field label="Background interval">
                    <div className="flex items-center gap-3">
                        <select
                            value={settings.auto_backup_interval_min}
                            onChange={e => set('auto_backup_interval_min', parseInt(e.target.value))}
                            className="input-glass w-48"
                        >
                            <option value={0}>Off (manual only)</option>
                            <option value={15}>Every 15 minutes</option>
                            <option value={30}>Every 30 minutes</option>
                            <option value={60}>Every hour</option>
                            <option value={120}>Every 2 hours</option>
                        </select>
                        <span className="text-xs text-ink-muted">while the app is open</span>
                    </div>
                </Field>
                <button
                    onClick={triggerBackup}
                    className="text-xs border border-white/10 hover:border-amber2/40 bg-mx-shell/50 hover:bg-amber2/5 text-ink-primary hover:text-white rounded-xl px-4 py-2.5 flex items-center gap-2 transition-all"
                >
                    <Save size={14} /> Create Backup Now
                </button>
            </Section>

            <Section title="Cleanup" icon={Trash2}>
                <p className="text-xs text-ink-muted">Removes backup snapshots older than the retention window.</p>
                <button
                    onClick={async () => {
                        try {
                            const res = await api.post('/api/system/cleanup');
                            toast.success(res.data.message || 'Old backups removed');
                        } catch { toast.error('Cleanup failed'); }
                    }}
                    className="text-xs border border-red-500/20 hover:border-red-500/40 bg-red-500/5 hover:bg-red-500/10 text-red-400 rounded-xl px-4 py-2.5 flex items-center gap-2 transition-all"
                >
                    <Trash2 size={14} /> Clean Old Backups
                </button>
            </Section>
        </div>
    );

    const renderExport = () => (
        <div className="space-y-6">
            <Section title="Default Output Folder" icon={FolderOpen}>
                <p className="text-xs text-ink-muted">
                    Audio exports from the Waveform Editor go here unless you pick a different folder per export.
                    Empty = use the app's built-in <span className="font-mono">./exports</span> directory.
                </p>
                <Field label="Default export folder">
                    <div className="flex gap-2">
                        <input
                            type="text"
                            value={settings.default_export_dir || ''}
                            onChange={e => set('default_export_dir', e.target.value)}
                            placeholder="e.g. <user_dir>\Music\Exports"
                            className="input-glass flex-1"
                        />
                        <button
                            type="button"
                            onClick={async () => {
                                try {
                                    const { open } = await import('@tauri-apps/plugin-dialog');
                                    const picked = await open({
                                        directory: true,
                                        multiple: false,
                                        title: 'Choose default export folder',
                                        defaultPath: settings.default_export_dir || undefined,
                                    });
                                    if (typeof picked === 'string' && picked.length) {
                                        set('default_export_dir', picked);
                                    }
                                } catch (err) {
                                    console.error('[Settings] folder picker failed', err);
                                    toast.error('Folder picker unavailable in browser mode — type the path manually.');
                                }
                            }}
                            className="px-3 py-2 rounded-lg text-xs bg-mx-shell/50 border border-white/10 hover:border-amber2/50 hover:bg-amber2/5 transition-all flex items-center gap-1.5"
                            title="Browse…"
                        >
                            <FolderOpen size={13} /> Browse
                        </button>
                    </div>
                </Field>
            </Section>

            <Section title="Format Defaults" icon={FileOutput}>
                <Field label="Default export format">
                    <select value={settings.export_format} onChange={e => set('export_format', e.target.value)} className="input-glass w-full">
                        <option value="xml">Rekordbox XML</option>
                        <option value="m3u">M3U Playlist</option>
                        <option value="csv">CSV Spreadsheet</option>
                    </select>
                </Field>
                <div className="grid grid-cols-2 gap-4">
                    <Field label="Audio export bitrate">
                        <select value={settings.export_bitrate || '320'} onChange={e => set('export_bitrate', e.target.value)} className="input-glass w-full">
                            <option value="128">128 kbps (MP3)</option>
                            <option value="192">192 kbps (MP3)</option>
                            <option value="256">256 kbps (AAC)</option>
                            <option value="320">320 kbps (MP3 – max)</option>
                            <option value="lossless">Lossless (WAV/FLAC)</option>
                        </select>
                    </Field>
                    <Field label="Sample rate">
                        <select value={settings.export_sample_rate || '44100'} onChange={e => set('export_sample_rate', e.target.value)} className="input-glass w-full">
                            <option value="44100">44.1 kHz (CD quality)</option>
                            <option value="48000">48 kHz (broadcast)</option>
                            <option value="96000">96 kHz (studio)</option>
                        </select>
                    </Field>
                </div>
            </Section>

            <Section title="Rekordbox Bridge" icon={RefreshCw}>
                <p className="text-xs text-ink-muted">Bi-directional sync with the Rekordbox XML library.</p>
                <div className="grid grid-cols-2 gap-3">
                    <button
                        onClick={async () => {
                            try {
                                const tracks = await api.get('/api/library/tracks');
                                const ids = tracks.data.map(t => t.id || t.TrackID);
                                const res = await api.post('/api/rekordbox/export', { track_ids: ids });
                                toast.success(`Exported: ${res.data.path}`);
                            } catch { toast.error('Export failed'); }
                        }}
                        className="flex items-center justify-center gap-2 p-4 rounded-xl bg-mx-shell/50 border border-white/10 hover:border-amber2/50 hover:bg-amber2/5 transition-all text-sm"
                    >
                        <FileOutput size={16} className="text-amber2" /> Push to Rekordbox
                    </button>
                    <button
                        onClick={async () => {
                            const path = prompt('Rekordbox XML export path:');
                            if (!path) return;
                            try {
                                const res = await api.post('/api/rekordbox/import', { xml_path: path });
                                toast.success(res.data.message || 'Import complete');
                            } catch { toast.error('Import failed'); }
                        }}
                        className="flex items-center justify-center gap-2 p-4 rounded-xl bg-mx-shell/50 border border-white/10 hover:border-amber2/50 hover:bg-amber2/5 transition-all text-sm"
                    >
                        <RefreshCw size={16} className="text-amber2" /> Pull from Rekordbox
                    </button>
                </div>
            </Section>
        </div>
    );

    const renderAudio = () => (
        <div className="space-y-6">
            <Section title="Output Device" icon={Music}>
                <p className="text-xs text-ink-muted">
                    Select which audio output device the DAW playback engine uses.
                    Takes effect the next time a track is loaded.
                    {!window.__TAURI__ && <span className="block mt-1 text-amber-400">⚠ Device enumeration requires the desktop app (Tauri).</span>}
                </p>
                <Field label="Audio output">
                    <select
                        value={settings.audio_output_device || ''}
                        onChange={e => set('audio_output_device', e.target.value)}
                        className="input-glass w-full"
                    >
                        {audioDevices.map(d => (
                            <option key={d} value={d === 'System Default' ? '' : d}>{d}</option>
                        ))}
                    </select>
                </Field>
                {audioDevices.length === 1 && window.__TAURI__ && (
                    <p className="text-xs text-ink-muted italic">Only the system default was found. Check that your audio drivers are installed.</p>
                )}
            </Section>
        </div>
    );

    const renderAnalysis = () => (
        <div className="space-y-6">
            <Section title="Analysis Quality" icon={Sliders}>
                <p className="text-xs text-ink-muted">Controls the accuracy vs. speed trade-off for BPM and key detection.</p>
                <div className="grid grid-cols-3 gap-3">
                    {[
                        { id: 'fast',      label: 'Fast',      sub: 'librosa — ~2s/track' },
                        { id: 'standard',  label: 'Standard',  sub: 'madmom RNN — ~8s/track' },
                        { id: 'thorough',  label: 'Thorough',  sub: 'Ensemble — ~20s/track' },
                    ].map(q => (
                        <button
                            key={q.id}
                            onClick={() => set('analysis_quality', q.id)}
                            className={`flex flex-col items-center p-4 rounded-2xl border transition-all ${
                                settings.analysis_quality === q.id
                                    ? 'bg-amber2/20 border-amber2'
                                    : 'bg-mx-deepest/50 border-white/5 hover:border-white/20'}`}
                        >
                            <span className={`font-bold text-sm ${settings.analysis_quality === q.id ? 'text-white' : 'text-ink-secondary'}`}>{q.label}</span>
                            <span className="text-[10px] text-ink-muted mt-1 text-center">{q.sub}</span>
                        </button>
                    ))}
                </div>
            </Section>

            <Section title="Ranking Mode" icon={Power}>
                <Field label="Default queue filter">
                    <select value={settings.ranking_filter_mode || 'all'} onChange={e => set('ranking_filter_mode', e.target.value)} className="input-glass w-full">
                        <option value="all">All Tracks</option>
                        <option value="unrated">Unrated Only (0 Stars)</option>
                        <option value="untagged">Untagged Only (No Comments)</option>
                    </select>
                </Field>
            </Section>

            <Section title="Library Insights" icon={Info}>
                <div className="grid grid-cols-2 gap-4">
                    <Field label="Low quality threshold (kbps)">
                        <input type="number" min="0" max="320"
                            value={settings.insights_bitrate_threshold || 320}
                            onChange={e => set('insights_bitrate_threshold', parseInt(e.target.value) || 0)}
                            className="input-glass w-full" />
                    </Field>
                    <Field label="Lost track play threshold">
                        <input type="number" min="0"
                            value={settings.insights_playcount_threshold || 0}
                            onChange={e => set('insights_playcount_threshold', parseInt(e.target.value) || 0)}
                            className="input-glass w-full" />
                    </Field>
                </div>
            </Section>

            <Section title="Artist View" icon={User}>
                <Field label="Min tracks to show artist">
                    <input type="number" min="0"
                        value={settings.artist_view_threshold || 0}
                        onChange={e => set('artist_view_threshold', parseInt(e.target.value) || 0)}
                        className="input-glass w-32" />
                </Field>
            </Section>
        </div>
    );

    const renderAppearance = () => (
        <div className="space-y-6">
            <Section title="Waveform Colors" icon={Palette}>
                <p className="text-xs text-ink-muted">
                    Custom colors for the 3-band waveform display (Low / Mid / High frequency bands).
                    Changes the palette across the DAW editor and overview.
                </p>
                <Field label="Color mode">
                    <select value={settings.waveform_visual_mode || 'custom'} onChange={e => set('waveform_visual_mode', e.target.value)} className="input-glass w-full">
                        <option value="blue">Standard Blue (monochrome)</option>
                        <option value="rgb">RGB Intensity (preset)</option>
                        <option value="3band">High Contrast 3-Band (preset)</option>
                        <option value="custom">Custom Colors (below)</option>
                    </select>
                </Field>
                <div className="grid grid-cols-3 gap-4">
                    {[
                        { key: 'waveform_color_low',  label: 'Low (Bass)', defaultColor: '#ef4444' },
                        { key: 'waveform_color_mid',  label: 'Mid',        defaultColor: '#22c55e' },
                        { key: 'waveform_color_high', label: 'High (Air)', defaultColor: '#3b82f6' },
                    ].map(({ key, label, defaultColor }) => (
                        <div key={key} className="flex flex-col items-center gap-2">
                            <label className="text-xs text-ink-secondary font-bold uppercase">{label}</label>
                            <div className="relative">
                                <input
                                    type="color"
                                    value={settings[key] || defaultColor}
                                    onChange={e => set(key, e.target.value)}
                                    className="w-14 h-14 rounded-xl border-0 cursor-pointer bg-transparent p-0.5"
                                    style={{ outline: `2px solid ${settings[key] || defaultColor}40` }}
                                />
                            </div>
                            <span className="text-[10px] text-ink-muted font-mono">{settings[key] || defaultColor}</span>
                        </div>
                    ))}
                </div>
                <div className="flex items-center gap-3 h-6 rounded-lg overflow-hidden border border-white/10">
                    <div className="flex-1 h-full" style={{ background: settings.waveform_color_low  || '#ef4444' }} />
                    <div className="flex-1 h-full" style={{ background: settings.waveform_color_mid  || '#22c55e' }} />
                    <div className="flex-1 h-full" style={{ background: settings.waveform_color_high || '#3b82f6' }} />
                </div>
            </Section>

            <Section title="Language" icon={Globe}>
                <div className="grid grid-cols-2 gap-3">
                    {[
                        { id: 'de', label: 'Deutsch', flag: '🇩🇪' },
                        { id: 'en', label: 'English',  flag: '🇬🇧' },
                    ].map(lang => (
                        <button
                            key={lang.id}
                            onClick={() => set('locale', lang.id)}
                            className={`flex items-center gap-3 p-4 rounded-2xl border transition-all ${
                                (settings.locale || 'de') === lang.id
                                    ? 'bg-amber2/20 border-amber2'
                                    : 'bg-mx-deepest/50 border-white/5 hover:border-white/20'}`}
                        >
                            <span className="text-2xl">{lang.flag}</span>
                            <span className={`font-bold text-sm ${(settings.locale || 'de') === lang.id ? 'text-white' : 'text-ink-secondary'}`}>{lang.label}</span>
                        </button>
                    ))}
                </div>
                <p className="text-xs text-ink-muted italic">Full i18n support is being rolled out progressively.</p>
            </Section>
        </div>
    );

    const renderShortcuts = () => (
        <div className="space-y-6">
            <Section title="DAW Keyboard Shortcuts" icon={Keyboard}>
                <p className="text-xs text-ink-muted">
                    Click any shortcut to capture a new key binding. Changes apply immediately in the DAW editor after saving.
                    Press <kbd className="px-1.5 py-0.5 bg-mx-card rounded text-[10px] font-mono border border-white/10">Esc</kbd> to cancel capture.
                </p>
                <div className="space-y-1.5">
                    {Object.entries(SHORTCUT_LABELS).map(([action, label]) => (
                        <div key={action} className="flex items-center justify-between p-2.5 rounded-xl hover:bg-mx-card/50 transition-colors">
                            <span className="text-sm text-ink-primary">{label}</span>
                            <KeyCapture
                                binding={settings.shortcuts?.[action] || DEFAULTS.shortcuts[action]}
                                onCapture={combo => setShortcut(action, combo)}
                            />
                        </div>
                    ))}
                </div>
                <button
                    onClick={() => setSettings(prev => ({ ...prev, shortcuts: { ...DEFAULTS.shortcuts } }))}
                    className="text-xs text-ink-muted hover:text-white border border-white/10 hover:border-white/20 rounded-lg px-3 py-2 transition-all"
                >
                    Reset to defaults
                </button>
            </Section>
        </div>
    );

    const renderNetwork = () => (
        <div className="space-y-6">
            <Section title="HTTP Proxy" icon={Wifi}>
                <p className="text-xs text-ink-muted">
                    For users behind corporate firewalls. Applied to all SoundCloud API calls.
                    Format: <code className="text-amber2 text-[11px]">http://user:pass@proxy.example.com:8080</code>
                </p>
                <Field label="Proxy URL (leave empty to disable)">
                    <input
                        type="text"
                        value={settings.http_proxy || ''}
                        onChange={e => set('http_proxy', e.target.value)}
                        placeholder="http://proxy.company.com:8080"
                        className="input-glass w-full font-mono text-sm"
                    />
                </Field>
            </Section>

            <Section title="SoundCloud Sync" icon={Globe}>
                <Field label="Target folder ID for synced playlists">
                    <input
                        type="text"
                        value={settings.sc_sync_folder_id || ''}
                        onChange={e => set('sc_sync_folder_id', e.target.value)}
                        placeholder="ROOT (or Rekordbox folder ID)"
                        className="input-glass w-full"
                    />
                </Field>
                <p className="text-xs text-ink-muted">Leave empty to create SC_ playlists at the root level.</p>
            </Section>

            <Section title="System" icon={Power}>
                <button
                    onClick={async () => {
                        try {
                            await api.post('/api/system/restart');
                            toast.success('Backend restarting…');
                        } catch { toast.error('Restart failed'); }
                    }}
                    className="text-xs border border-amber-500/20 hover:border-amber-500/40 bg-amber-500/5 hover:bg-amber-500/10 text-amber-400 rounded-xl px-4 py-2.5 flex items-center gap-2 transition-all"
                >
                    <RefreshCw size={14} /> Restart Backend Service
                </button>
            </Section>
        </div>
    );

    // ── USB Profiles tab ─────────────────────────────────────────────────────
    const renderUsbProfiles = () => (
        <div className="space-y-4">
            <Section title="USB Export Profiles" icon={HardDrive}>
                <p className="text-tiny text-ink-muted mb-4">
                    Each USB stick has its own profile. Configure type and audio export format here.
                    Format settings are applied when files need conversion during sync.
                </p>

                {usbProfilesLoading ? (
                    <div className="text-tiny text-ink-muted py-4 text-center">Loading profiles…</div>
                ) : usbProfiles.length === 0 ? (
                    <div className="text-tiny text-ink-muted py-6 text-center">
                        No USB profiles yet. Plug in a USB stick and configure it from <strong>USB Export</strong>.
                    </div>
                ) : (
                    <div className="space-y-2">
                        {usbProfiles.map(profile => {
                            const isOpen = editingProfileId === profile.device_id;
                            return (
                                <div key={profile.device_id} className="bg-mx-input rounded-mx-sm border border-line-subtle">
                                    {/* Row header */}
                                    <button
                                        onClick={() => setEditingProfileId(isOpen ? null : profile.device_id)}
                                        className="w-full px-3 py-2.5 flex items-center justify-between text-left hover:bg-mx-hover transition-colors"
                                    >
                                        <div className="flex items-center gap-3 min-w-0 flex-1">
                                            <HardDrive size={14} className="text-amber2 shrink-0" />
                                            <div className="min-w-0 flex-1">
                                                <div className="text-[12px] font-medium text-ink-primary truncate">
                                                    {profile.label || profile.drive || profile.device_id.slice(0, 12)}
                                                </div>
                                                <div className="text-[10px] text-ink-muted truncate">
                                                    {USB_TYPE_LABELS[profile.type] || profile.type || 'Collection'}
                                                    {profile.drive && ` · ${profile.drive}`}
                                                </div>
                                            </div>
                                        </div>
                                        <div className="flex items-center gap-2">
                                            <span className="text-[10px] font-mono text-ink-muted px-2 py-0.5 bg-mx-deepest rounded">
                                                {profile.audio_format === 'original' || !profile.audio_format
                                                    ? 'Original'
                                                    : `${(profile.audio_format || '').toUpperCase()}${profile.audio_format && profile.audio_format !== 'flac' && profile.audio_format !== 'wav' ? ` ${profile.audio_bitrate || '320'}` : ''}`}
                                            </span>
                                            <ChevronRight size={12} className={`text-ink-muted transition-transform ${isOpen ? 'rotate-90' : ''}`} />
                                        </div>
                                    </button>

                                    {/* Edit form */}
                                    {isOpen && (
                                        <div className="px-3 py-3 border-t border-line-subtle space-y-3">
                                            {/* Label */}
                                            <Field label="Label">
                                                <input
                                                    type="text"
                                                    className="input-glass text-tiny w-full"
                                                    placeholder={profile.drive || 'Custom label'}
                                                    defaultValue={profile.label || ''}
                                                    onBlur={e => {
                                                        if (e.target.value !== (profile.label || '')) {
                                                            updateUsbProfile(profile, { label: e.target.value });
                                                        }
                                                    }}
                                                />
                                            </Field>

                                            {/* Type */}
                                            <Field label="Type">
                                                <Select
                                                    value={profile.type || 'Collection'}
                                                    onChange={v => updateUsbProfile(profile, { type: v })}
                                                    options={Object.entries(USB_TYPE_LABELS).map(([id, label]) => ({ id, label }))}
                                                />
                                            </Field>

                                            {/* Audio format */}
                                            <Field label="Audio Format">
                                                <Select
                                                    value={profile.audio_format || 'original'}
                                                    onChange={v => updateUsbProfile(profile, { audio_format: v })}
                                                    options={AUDIO_FORMATS.map(f => ({ id: f.id, label: f.label }))}
                                                />
                                            </Field>

                                            {/* Bitrate (only for lossy) */}
                                            {(profile.audio_format === 'mp3' || profile.audio_format === 'aac') && (
                                                <Field label="Bitrate (kbps)">
                                                    <Select
                                                        value={profile.audio_bitrate || '320'}
                                                        onChange={v => updateUsbProfile(profile, { audio_bitrate: v })}
                                                        options={BITRATES.map(b => ({ id: b, label: `${b} kbps` }))}
                                                    />
                                                </Field>
                                            )}

                                            {/* Sample rate (only when converting) */}
                                            {profile.audio_format && profile.audio_format !== 'original' && (
                                                <Field label="Sample Rate (Hz)">
                                                    <Select
                                                        value={profile.audio_sample_rate || '44100'}
                                                        onChange={v => updateUsbProfile(profile, { audio_sample_rate: v })}
                                                        options={SAMPLE_RATES.map(r => ({ id: r, label: `${r} Hz` }))}
                                                    />
                                                </Field>
                                            )}

                                            {/* Delete button */}
                                            <div className="pt-2 border-t border-line-subtle">
                                                <button
                                                    onClick={() => deleteUsbProfile(profile.device_id)}
                                                    className="text-[10px] text-rose-400 hover:text-rose-300 flex items-center gap-1.5 transition-colors"
                                                >
                                                    <Trash2 size={11} /> Remove profile
                                                </button>
                                            </div>
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                )}

                <button
                    onClick={loadUsbProfiles}
                    className="mt-4 text-tiny text-ink-muted hover:text-amber2 flex items-center gap-1.5 transition-colors"
                >
                    <RefreshCw size={11} /> Refresh
                </button>
            </Section>
        </div>
    );

    const TAB_CONTENT = {
        library:    renderLibrary,
        backup:     renderBackup,
        export:     renderExport,
        usb:        renderUsbProfiles,
        audio:      renderAudio,
        analysis:   renderAnalysis,
        appearance: renderAppearance,
        shortcuts:  renderShortcuts,
        network:    renderNetwork,
    };

    // ── Render ─────────────────────────────────────────────────────────────────
    return (
        <div className="h-full w-full flex flex-col items-center bg-transparent text-white overflow-y-auto p-4 md:p-8 relative">
            <div className="absolute top-[-20%] right-[-10%] w-[600px] h-[600px] bg-amber2/10 rounded-full blur-[120px] pointer-events-none" />

            <div className="w-full max-w-4xl relative z-10 animate-slide-up my-auto">
                {/* Header */}
                <div className="glass-panel px-8 py-6 rounded-3xl shadow-2xl mb-4">
                    <div className="flex items-center gap-5">
                        <div className="p-3.5 bg-amber2/20 rounded-2xl shadow-lg shadow-amber2/10">
                            <Settings size={36} className="text-amber2" />
                        </div>
                        <div>
                            <h1 className="text-3xl font-bold bg-gradient-to-r from-white to-slate-400 bg-clip-text text-transparent">Preferences</h1>
                            <p className="text-ink-secondary mt-0.5 text-sm">LibraryManagementSystem — Configure all application settings</p>
                        </div>
                    </div>
                </div>

                {/* Tab strip */}
                <div className="glass-panel rounded-2xl p-1.5 mb-4 flex gap-1 flex-wrap">
                    {TABS.map(tab => {
                        const Icon = tab.icon;
                        return (
                            <button
                                key={tab.id}
                                onClick={() => setActiveTab(tab.id)}
                                className={`flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-bold uppercase tracking-wide transition-all ${
                                    activeTab === tab.id
                                        ? 'bg-amber2/20 text-amber2-hover shadow-md'
                                        : 'text-ink-secondary hover:text-white hover:bg-white/5'
                                }`}
                            >
                                <Icon size={13} />{tab.label}
                            </button>
                        );
                    })}
                </div>

                {/* Tab content */}
                <div className="glass-panel rounded-3xl p-6 shadow-2xl">
                    {TAB_CONTENT[activeTab]?.()}
                </div>

                {/* Footer */}
                <div className="mt-4 flex justify-end">
                    <button
                        onClick={saveSettings}
                        disabled={saving}
                        className="btn-primary flex items-center gap-3 px-8 py-3 rounded-xl text-sm shadow-xl shadow-amber2/20 disabled:opacity-50"
                    >
                        {saving ? <RefreshCw size={16} className="animate-spin" /> : <Save size={16} />}
                        {saving ? 'Saving…' : 'Save Changes'}
                    </button>
                </div>
            </div>
        </div>
    );
};

export default SettingsView;
