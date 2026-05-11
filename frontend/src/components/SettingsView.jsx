/**
 * SettingsView — Tabbed preferences panel (container).
 *
 * Owns:
 *   - the merged `settings` object (defaults + backend GET)
 *   - the active-tab pointer
 *   - load on mount (GET /api/settings) + save on demand (POST /api/settings)
 *
 * Each tab body lives in ./settings/Settings<Tab>.jsx and receives
 * `settings` + `setSettings`. Shared field helpers live in
 * ./settings/SettingsControls.jsx.
 *
 * Tabs:
 *   Library    — DB mode, scan folders, library filter
 *   Backup     — retention, auto-backup interval, archive frequency
 *   Export     — format, bitrate, sample rate, default output dir, RB bridge
 *   USB        — per-stick USB profile CRUD
 *   Audio      — CPAL output device picker (Tauri)
 *   Analysis   — quality preset, ranking filter, insights thresholds
 *   Appearance — waveform band colors, language/locale
 *   Shortcuts  — configurable DAW keyboard shortcuts
 *   Network    — HTTP proxy, SoundCloud sync, backend restart
 */

import React, { useState, useEffect } from 'react';
import api from '../api/api';
import toast from 'react-hot-toast';
import {
    Settings, Database, HardDrive, RefreshCw, Save,
    FileOutput, Speaker, Sliders, Keyboard,
    Wifi, Palette, Music,
} from 'lucide-react';

import SettingsLibrary from './settings/SettingsLibrary';
import SettingsBackup from './settings/SettingsBackup';
import SettingsExport from './settings/SettingsExport';
import SettingsUsb from './settings/SettingsUsb';
import SettingsAudio from './settings/SettingsAudio';
import SettingsAnalysis from './settings/SettingsAnalysis';
import SettingsAppearance from './settings/SettingsAppearance';
import SettingsShortcuts from './settings/SettingsShortcuts';
import SettingsNetwork from './settings/SettingsNetwork';

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

// ── Main component ────────────────────────────────────────────────────────────
const SettingsView = () => {
    const [settings, setSettings] = useState(DEFAULTS);
    const [activeTab, setActiveTab] = useState('library');
    const [saving, setSaving] = useState(false);

    // ── Load settings on mount ────────────────────────────────────────────────
    useEffect(() => {
        api.get('/api/settings')
            .then(res => setSettings({
                ...DEFAULTS,
                ...res.data,
                shortcuts: { ...DEFAULTS.shortcuts, ...(res.data.shortcuts || {}) },
            }))
            .catch(() => {});
    }, []);

    // ── Persist ───────────────────────────────────────────────────────────────
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

    // ── Active tab content ────────────────────────────────────────────────────
    const renderActiveTab = () => {
        switch (activeTab) {
            case 'library':    return <SettingsLibrary    settings={settings} setSettings={setSettings} />;
            case 'backup':     return <SettingsBackup     settings={settings} setSettings={setSettings} />;
            case 'export':     return <SettingsExport     settings={settings} setSettings={setSettings} />;
            case 'usb':        return <SettingsUsb />;
            case 'audio':      return <SettingsAudio      settings={settings} setSettings={setSettings} />;
            case 'analysis':   return <SettingsAnalysis   settings={settings} setSettings={setSettings} />;
            case 'appearance': return <SettingsAppearance settings={settings} setSettings={setSettings} />;
            case 'shortcuts':  return <SettingsShortcuts  settings={settings} setSettings={setSettings} />;
            case 'network':    return <SettingsNetwork    settings={settings} setSettings={setSettings} />;
            default:           return null;
        }
    };

    // ── Render ────────────────────────────────────────────────────────────────
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
                    {renderActiveTab()}
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
