import React, { useState, useEffect } from 'react';
import api from '../api/api';
import { Settings, Database, HardDrive, RefreshCw, Save, Trash2, Shield, User, Globe, Moon, Bell, Info, CheckCircle, AlertCircle, FileOutput, Power, Folder, Check } from 'lucide-react';

const SettingsView = () => {
    const [settings, setSettings] = useState({
        backup_retention_days: 7,
        export_format: "xml",
        auto_backup: true,
        waveform_visual_mode: "blue"
    });
    const [status, setStatus] = useState("");

    useEffect(() => {
        loadSettings();
    }, []);

    const [libStatus, setLibStatus] = useState({ mode: 'xml', loaded: false });

    useEffect(() => {
        loadSettings();
        loadLibStatus();
    }, []);

    const loadLibStatus = async () => {
        try {
            const res = await api.get('/api/library/status');
            setLibStatus(res.data);
        } catch (e) {
            console.error("Failed to load library status", e);
        }
    };

    const handleSwitchMode = async (mode) => {
        try {
            const res = await api.post('/api/library/mode', { mode });
            if (res.data.status === "success") {
                setLibStatus({ ...libStatus, mode: res.data.mode });
                setStatus(`Switched to ${res.data.mode.toUpperCase()} mode`);
                setTimeout(() => setStatus(""), 3000);
            }
        } catch (e) {
            alert("Failed to switch mode");
        }
    };

    const triggerBackup = async () => {
        try {
            setStatus("Creating Backup...");
            const res = await api.post('/api/library/backup');
            if (res.data.status === "success") {
                setStatus("Backup Created Successfully!");
            } else {
                setStatus("Backup Failed: " + (res.data.message || "Unknown error"));
            }
            setTimeout(() => setStatus(""), 3000);
        } catch (e) {
            setStatus("Backup Error");
        }
    };

    const loadSettings = async () => {
        try {
            const res = await api.get('/api/settings');
            setSettings(res.data);
        } catch (e) {
            console.error("Failed to load settings", e);
        }
    };

    const saveSettings = async () => {
        setStatus("Saving...");
        try {
            await api.post('/api/settings', settings);
            setStatus("Settings Saved Successfully!");
            setTimeout(() => setStatus(""), 3000);
        } catch (e) {
            setStatus("Error saving settings");
        }
    };

    const handleSelectDB = async () => {
        try {
            const res = await api.post('/api/system/select_db');
            if (res.data.path) {
                setSettings({ ...settings, master_db_path: res.data.path.replace(/\\/g, "/") });
            }
        } catch (e) { alert("Dialog failed. Please paste path manually."); }
    }

    const cleanupBackups = async () => {
        if (!confirm("Delete old backups?")) return;
        try {
            const res = await api.post('/api/system/cleanup');
            alert(res.data.message || "Cleanup Complete");
        } catch (e) { alert("Cleanup failed"); }
    };

    const handleRestartBackend = async () => {
        if (!confirm("Restart Backend Server? The UI may lose connection briefly.")) return;
        try {
            await api.post('/api/system/restart');
            setStatus("Backend Restarting...");
            setTimeout(() => setStatus(""), 5000);
        } catch (e) {
            alert("Failed to trigger restart");
        }
    };

    const handleSync = async () => {
        if (!confirm("Confirm and Sync all pending changes to the Rekordbox Database? This will create an automatic backup first.")) return;
        setStatus("Syncing...");
        try {
            const res = await api.post('/api/library/sync');
            if (res.data.status === "success") {
                setStatus("Changes Synced Successfully!");
            } else {
                setStatus("Sync Failed: " + (res.data.message || "Unknown error"));
            }
            setTimeout(() => setStatus(""), 3000);
        } catch (e) {
            setStatus("Sync Error");
        }
    };

    return (
        <div className="h-full w-full flex flex-col items-center bg-transparent text-white relative overflow-y-auto p-4 md:p-8">
            {/* Background Decoration */}
            <div className="absolute top-[-20%] right-[-10%] w-[600px] h-[600px] bg-cyan-500/10 rounded-full blur-[120px] pointer-events-none"></div>

            <div className="w-full max-w-4xl glass-panel p-6 md:p-10 rounded-3xl relative z-10 animate-slide-up shadow-2xl my-auto">
                <div className="flex items-center gap-6 mb-10 border-b border-white/10 pb-8">
                    <div className="p-4 bg-cyan-500/20 rounded-2xl shadow-lg shadow-cyan-500/10">
                        <Settings size={40} className="text-cyan-400" />
                    </div>
                    <div>
                        <h1 className="text-4xl font-bold bg-gradient-to-r from-white to-slate-400 bg-clip-text text-transparent">Preferences</h1>
                        <p className="text-slate-400 mt-1">Configure your Rekordbox integration parameters</p>
                    </div>
                </div>

                <div className="space-y-10">
                    {/* Database Mode Selection */}
                    <div>
                        <h2 className="text-xs font-bold text-cyan-400 uppercase tracking-widest mb-4 flex items-center gap-2">
                            <Database size={16} /> Library Connection Mode
                        </h2>
                        <div className="grid grid-cols-2 gap-4">
                            <button
                                onClick={() => handleSwitchMode('xml')}
                                className={`flex flex-col items-center p-6 rounded-2xl border transition-all ${libStatus.mode === 'xml' ? 'bg-cyan-500/20 border-cyan-500 shadow-lg shadow-cyan-500/10' : 'bg-slate-950/50 border-white/5 hover:border-white/20'}`}
                            >
                                <FileOutput size={32} className={libStatus.mode === 'xml' ? 'text-cyan-400 mb-3' : 'text-slate-500 mb-3'} />
                                <span className={`font-bold ${libStatus.mode === 'xml' ? 'text-white' : 'text-slate-400'}`}>XML Snapshot</span>
                                <p className="text-[10px] text-slate-500 mt-1 text-center">Static export from Rekordbox</p>
                            </button>
                            <button
                                onClick={() => handleSwitchMode('live')}
                                className={`flex flex-col items-center p-6 rounded-2xl border transition-all ${libStatus.mode === 'live' ? 'bg-cyan-500/20 border-cyan-500 shadow-lg shadow-cyan-500/10' : 'bg-slate-950/50 border-white/5 hover:border-white/20'}`}
                            >
                                <Database size={32} className={libStatus.mode === 'live' ? 'text-cyan-400 mb-3' : 'text-slate-500 mb-3'} />
                                <span className={`font-bold ${libStatus.mode === 'live' ? 'text-white' : 'text-slate-400'}`}>Live Database</span>
                                <p className="text-[10px] text-slate-500 mt-1 text-center">Direct access (Master.db)</p>
                            </button>
                        </div>
                        <div className="mt-4 flex items-center gap-3">
                            <label className="flex items-center gap-3 cursor-pointer group">
                                <div className={`w-5 h-5 rounded border flex items-center justify-center transition-colors ${settings.remember_lib_mode ? 'bg-cyan-500 border-cyan-500' : 'bg-transparent border-slate-600 group-hover:border-cyan-500'}`}>
                                    {settings.remember_lib_mode && <Check size={12} className="text-white" />}
                                </div>
                                <input
                                    type="checkbox"
                                    checked={settings.remember_lib_mode}
                                    onChange={e => setSettings({ ...settings, remember_lib_mode: e.target.checked })}
                                    className="hidden"
                                />
                                <span className="text-sm text-slate-300 group-hover:text-white transition-colors font-medium">Remember my selection</span>
                            </label>
                        </div>
                    </div>

                    {/* DB Info & Backup */}
                    {libStatus.mode === 'live' && (
                        <div className="bg-cyan-500/5 border border-cyan-500/20 rounded-2xl p-6 animate-pulse-subtle">
                            <div className="flex justify-between items-center gap-4">
                                <div>
                                    <h3 className="text-sm font-bold text-white flex items-center gap-2">
                                        <HardDrive size={16} className="text-cyan-400" /> Live Database Active
                                    </h3>
                                    <p className="text-xs text-slate-400 mt-1 font-mono">{libStatus.path}</p>
                                </div>
                                <div className="flex gap-2">
                                    <button onClick={triggerBackup} className="btn-ghost py-2 px-4 flex items-center gap-2 rounded-xl text-xs border-cyan-500/20 hover:bg-cyan-500/10">
                                        <Save size={14} /> Manual Backup
                                    </button>
                                </div>
                            </div>
                        </div>
                    )}

                    {/* Backup & Export */}
                    <div className="grid grid-cols-2 gap-8">
                        <div>
                            <h2 className="text-xs font-bold text-cyan-400 uppercase tracking-widest mb-4 flex items-center gap-2">
                                <HardDrive size={16} /> Backup Strategy
                            </h2>
                            <div className="bg-slate-950/50 rounded-2xl p-6 border border-white/5 space-y-4 h-full">
                                <div>
                                    <label className="text-xs text-slate-400 mb-2 block font-bold uppercase">Retention (Days)</label>
                                    <input
                                        type="number"
                                        value={settings.backup_retention_days}
                                        onChange={e => setSettings({ ...settings, backup_retention_days: parseInt(e.target.value) })}
                                        className="input-glass w-full"
                                    />
                                </div>
                                <div>
                                    <label className="text-xs text-slate-400 mb-2 block font-bold uppercase">Archival Frequency</label>
                                    <select
                                        value={settings.archive_frequency || 'daily'}
                                        onChange={e => setSettings({ ...settings, archive_frequency: e.target.value })}
                                        className="input-glass w-full"
                                    >
                                        <option value="off">Off (Session Only)</option>
                                        <option value="daily">Daily Archive</option>
                                        <option value="weekly">Weekly Archive</option>
                                        <option value="monthly">Monthly Archive</option>
                                    </select>
                                </div>
                                <div className="pt-2">
                                    <label className="flex items-center gap-3 cursor-pointer group">
                                        <div className={`w-5 h-5 rounded border flex items-center justify-center transition-colors ${settings.auto_backup ? 'bg-cyan-500 border-cyan-500' : 'bg-transparent border-slate-600 group-hover:border-cyan-500'}`}>
                                            {settings.auto_backup && <Save size={12} className="text-white" />}
                                        </div>
                                        <input
                                            type="checkbox"
                                            checked={settings.auto_backup}
                                            onChange={e => setSettings({ ...settings, auto_backup: e.target.checked })}
                                            className="hidden"
                                        />
                                        <span className="text-sm text-slate-300 group-hover:text-white transition-colors">Auto-backup on launch</span>
                                    </label>
                                </div>
                            </div>
                        </div>

                        <div>
                            <h2 className="text-xs font-bold text-cyan-400 uppercase tracking-widest mb-4 flex items-center gap-2">
                                <FileOutput size={16} /> Export Options
                            </h2>
                            <div className="bg-slate-950/50 rounded-2xl p-6 border border-white/5 space-y-4 h-full flex flex-col justify-between">
                                <div>
                                    <label className="text-xs text-slate-400 mb-2 block font-bold uppercase">Default Format</label>
                                    <select
                                        value={settings.export_format}
                                        onChange={e => setSettings({ ...settings, export_format: e.target.value })}
                                        className="input-glass w-full appearance-none bg-slate-900 cursor-pointer"
                                    >
                                        <option value="xml">Rekordbox XML</option>
                                        <option value="m3u">M3U Playlist</option>
                                        <option value="csv">CSV Data</option>
                                    </select>
                                </div>
                                <button onClick={cleanupBackups} className="w-full btn-ghost text-red-400 hover:text-red-300 hover:bg-red-500/10 flex items-center justify-center gap-2 border-red-500/20 hover:border-red-500/40 transition-all">
                                    <Trash2 size={16} /> Clean Old Backups
                                </button>
                            </div>
                        </div>
                    </div>

                    {/* Rekordbox Synchronization */}
                    <div className="bg-cyan-400/5 rounded-2xl p-6 border border-cyan-400/20 space-y-4">
                        <div className="flex justify-between items-start">
                            <div>
                                <h2 className="text-xs font-bold text-cyan-400 uppercase tracking-widest mb-1 flex items-center gap-2">
                                    <RefreshCw size={16} /> Rekordbox Bridge (XML)
                                </h2>
                                <p className="text-xs text-slate-500">Bi-directional metadata and beatgrid synchronization.</p>
                            </div>
                        </div>

                        <div className="grid grid-cols-2 gap-4 pt-2">
                            <button
                                onClick={async () => {
                                    if (!confirm("Export entire local collection to Rekordbox XML?")) return;
                                    setStatus("Exporting XML...");
                                    try {
                                        // Get all track IDs
                                        const tracks = await api.get('/api/library/tracks');
                                        const ids = tracks.data.map(t => t.id || t.TrackID);
                                        const res = await api.post('/api/rekordbox/export', { track_ids: ids });
                                        setStatus(`Export successful: ${res.data.path}`);
                                    } catch (e) { setStatus("Export failed"); }
                                    setTimeout(() => setStatus(""), 5000);
                                }}
                                className="flex items-center justify-center gap-3 p-4 rounded-xl bg-slate-900/50 border border-white/10 hover:border-cyan-500/50 hover:bg-cyan-500/5 transition-all group"
                            >
                                <FileOutput className="text-slate-500 group-hover:text-cyan-400 transition-colors" size={20} />
                                <div className="text-left">
                                    <div className="text-sm font-bold">Push to Rekordbox</div>
                                    <div className="text-[10px] text-slate-500">Generate Bridge XML</div>
                                </div>
                            </button>

                            <button
                                onClick={async () => {
                                    const path = prompt("Enter path to Rekordbox exported XML file:");
                                    if (!path) return;
                                    setStatus("Importing XML...");
                                    try {
                                        const res = await api.post('/api/rekordbox/import', { xml_path: path });
                                        setStatus(res.data.message);
                                    } catch (e) { setStatus("Import failed"); }
                                    setTimeout(() => setStatus(""), 5000);
                                }}
                                className="flex items-center justify-center gap-3 p-4 rounded-xl bg-slate-900/50 border border-white/10 hover:border-cyan-500/50 hover:bg-cyan-500/5 transition-all group"
                            >
                                <RefreshCw className="text-slate-500 group-hover:text-cyan-400 transition-colors" size={20} />
                                <div className="text-left">
                                    <div className="text-sm font-bold">Pull from Rekordbox</div>
                                    <div className="text-[10px] text-slate-500">Import Changes & Grids</div>
                                </div>
                            </button>
                        </div>
                    </div>

                    {/* Waveform Visualization */}
                    <div className="bg-slate-950/50 rounded-2xl p-6 border border-white/5 space-y-4">
                        <h2 className="text-xs font-bold text-cyan-400 uppercase tracking-widest mb-4 flex items-center gap-2">
                            Activity Waveform Style
                        </h2>
                        <div className="grid grid-cols-2 gap-8">
                            <div>
                                <label className="text-xs text-slate-400 mb-2 block font-bold uppercase">Color Profile</label>
                                <select
                                    value={settings.waveform_visual_mode || 'blue'}
                                    onChange={e => setSettings({ ...settings, waveform_visual_mode: e.target.value })}
                                    className="input-glass w-full"
                                >
                                    <option value="blue">Standard Blue</option>
                                    <option value="rgb">RGB Intensity (Red-Green-Blue)</option>
                                    <option value="3band">High Contrast (3-Band Style)</option>
                                </select>
                            </div>
                            <div className="flex items-center">
                                <span className="text-xs text-slate-500 italic leading-relaxed">
                                    Changes the color palette of waveforms across the application.
                                    <br />("RGB" uses Red for lows/bottom, Blue for highs/top.)
                                </span>
                            </div>
                        </div>
                    </div>

                    <div className="bg-slate-950/50 rounded-2xl p-6 border border-white/5 space-y-4">
                        <h2 className="text-xs font-bold text-cyan-400 uppercase tracking-widest mb-4 flex items-center gap-2">
                            <Shield size={16} /> Library Filtering
                        </h2>
                        <div className="flex items-center justify-between">
                            <div>
                                <h3 className="text-sm font-bold text-white">Hide Streaming Content</h3>
                                <p className="text-xs text-slate-500 mt-1">Filter out tracks from SoundCloud, Spotify, Tidal, and Beatport.</p>
                            </div>
                            <label className="relative inline-flex items-center cursor-pointer">
                                <input
                                    type="checkbox"
                                    className="sr-only peer"
                                    checked={settings.hide_streaming}
                                    onChange={e => setSettings({ ...settings, hide_streaming: e.target.checked })}
                                />
                                <div className="w-11 h-6 bg-slate-800 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-slate-400 after:border-slate-300 after:border after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:bg-cyan-600 peer-checked:after:bg-white"></div>
                            </label>
                        </div>
                    </div>

                    {/* Ranking Mode Settings */}
                    <div className="bg-slate-950/50 rounded-2xl p-6 border border-white/5 space-y-4">
                        <h2 className="text-xs font-bold text-cyan-400 uppercase tracking-widest mb-4 flex items-center gap-2">
                            <Power size={16} /> Power Ranking Mode
                        </h2>
                        <div className="grid grid-cols-2 gap-8">
                            <div>
                                <label className="text-xs text-slate-400 mb-2 block font-bold uppercase">Filter Mode</label>
                                <select
                                    value={settings.ranking_filter_mode || 'all'}
                                    onChange={e => setSettings({ ...settings, ranking_filter_mode: e.target.value })}
                                    className="input-glass w-full"
                                >
                                    <option value="all">Show All Tracks</option>
                                    <option value="unrated">Unrated Only (0 Stars)</option>
                                    <option value="untagged">Untagged Only (No Comments)</option>
                                </select>
                            </div>
                            <div className="flex items-center">
                                <span className="text-xs text-slate-500 italic leading-relaxed">This determines which tracks appear in your queue when you select a source in Ranking Mode.</span>
                            </div>
                        </div>
                    </div>

                    {/* Insights Settings */}
                    <div className="bg-slate-950/50 rounded-2xl p-6 border border-white/5 space-y-4">
                        <h2 className="text-xs font-bold text-cyan-400 uppercase tracking-widest mb-4 flex items-center gap-2">
                            <Folder size={16} /> Library Insights
                        </h2>
                        <div className="grid grid-cols-2 gap-8">
                            <div>
                                <label className="text-xs text-slate-400 mb-2 block font-bold uppercase">Low Quality Threshold (kbps)</label>
                                <input
                                    type="number"
                                    min="0"
                                    max="320"
                                    value={settings.insights_bitrate_threshold || 320}
                                    onChange={e => setSettings({ ...settings, insights_bitrate_threshold: parseInt(e.target.value) || 0 })}
                                    className="input-glass w-full"
                                />
                            </div>
                            <div>
                                <label className="text-xs text-slate-400 mb-2 block font-bold uppercase">Lost Track Threshold (Plays)</label>
                                <input
                                    type="number"
                                    min="0"
                                    value={settings.insights_playcount_threshold || 0}
                                    onChange={e => setSettings({ ...settings, insights_playcount_threshold: parseInt(e.target.value) || 0 })}
                                    className="input-glass w-full"
                                />
                            </div>
                        </div>
                        <div className="text-xs text-slate-500 italic">
                            Adjusts the criteria for the "Low Quality" and "Lost Tracks" insights views.
                        </div>
                    </div>

                    {/* Artist View Threshold */}
                    <div className="bg-slate-950/50 rounded-2xl p-6 border border-white/5 space-y-4">
                        <h2 className="text-xs font-bold text-cyan-400 uppercase tracking-widest mb-4 flex items-center gap-2">
                            <User size={16} /> Artist View
                        </h2>
                        <div>
                            <label className="text-xs text-slate-400 mb-2 block font-bold uppercase">Min Tracks Threshold</label>
                            <div className="flex gap-4 items-center">
                                <input
                                    type="number"
                                    min="0"
                                    value={settings.artist_view_threshold || 0}
                                    onChange={e => setSettings({ ...settings, artist_view_threshold: parseInt(e.target.value) || 0 })}
                                    className="input-glass w-32"
                                />
                                <span className="text-xs text-slate-500">Only show artists with this many tracks or more.</span>
                            </div>
                        </div>
                    </div>
                </div>

                {/* System Controls */}
                <div className="mt-8 pt-8 border-t border-white/5">
                    <h2 className="text-xs font-bold text-cyan-400 uppercase tracking-widest mb-4 flex items-center gap-2">
                        <RefreshCw size={16} /> System Operations
                    </h2>
                    <div className="flex gap-4">
                        <button onClick={handleRestartBackend} className="btn-ghost text-amber-400 border-amber-500/20 hover:bg-amber-500/10 flex items-center gap-2 px-4 py-2 rounded-lg transition-all">
                            <RefreshCw size={16} /> Restart Backend Service
                        </button>
                    </div>
                </div>

                <div className="mt-10 pt-8 border-t border-white/10 flex justify-between items-center">
                    <div className={`text-sm font-bold flex items-center gap-2 ${status.includes("Error") ? "text-red-400" : "text-green-400"}`}>
                        {status && (status.includes("Error") ? <AlertCircle size={16} /> : <CheckCircle size={16} />)}
                        {status}
                    </div>
                    <button onClick={saveSettings} className="btn-primary flex items-center gap-3 px-10 py-4 rounded-xl text-lg shadow-xl shadow-cyan-500/20">
                        <Save size={20} /> Save Changes
                    </button>
                </div>
            </div>
        </div>
    );
};
export default SettingsView;
