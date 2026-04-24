import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
    HardDrive, RefreshCw, Power, Trash2, Settings, Check, X, AlertTriangle,
    Loader2, ChevronRight, Usb, Database, ArrowUpDown, Clock, Shield,
    Disc3, ListMusic, Music, Zap, PlayCircle, Plus, ChevronDown,
    Folder, FolderOpen, Download, Edit2
} from 'lucide-react';
import api from '../api/api';
import toast from 'react-hot-toast';

const UsbLibraryTree = ({ item, level = 0 }) => {
    const [isExpanded, setIsExpanded] = useState(level < 1); // Expand first level by default

    if (item.type === 'folder') {
        return (
            <div className="select-none">
                <div
                    onClick={() => setIsExpanded(!isExpanded)}
                    className="flex items-center gap-2 p-2 hover:bg-white/5 rounded-lg cursor-pointer transition-all group"
                    style={{ paddingLeft: `${level * 12 + 8}px` }}
                >
                    <div className="w-4 h-4 flex items-center justify-center">
                        {isExpanded ? <ChevronDown size={14} className="text-slate-500" /> : <ChevronRight size={14} className="text-slate-500" />}
                    </div>
                    <Folder size={16} className={isExpanded ? "text-cyan-400" : "text-slate-400"} />
                    <span className={`text-xs ${isExpanded ? 'text-slate-200 font-bold' : 'text-slate-400'}`}>{item.name}</span>
                    <span className="text-[10px] text-slate-600 opacity-0 group-hover:opacity-100 ml-auto mr-2">
                        {item.children.length} items
                    </span>
                </div>
                {isExpanded && (
                    <div className="ml-1 border-l border-white/5">
                        {item.children.map((child, i) => (
                            <UsbLibraryTree key={i} item={child} level={level + 1} />
                        ))}
                    </div>
                )}
            </div>
        );
    }

    return (
        <div
            className="flex items-center gap-3 p-2 py-1.5 hover:bg-white/[0.03] transition-all group"
            style={{ paddingLeft: `${level * 12 + 28}px` }}
        >
            <div className="flex-1 min-w-0">
                <div className="text-xs font-bold text-slate-300 truncate">{item.Title}</div>
                <div className="text-[9px] text-slate-500 truncate">{item.ArtistName || 'Unknown Artist'}</div>
            </div>
            <div className="text-[9px] text-slate-600 font-mono tabular-nums opacity-0 group-hover:opacity-100 transition-opacity">
                {item.BPM ? (item.BPM / 100).toFixed(2) : '-.--'}
            </div>
        </div>
    );
};

const USB_TYPES = [
    { id: 'MainCollection', label: 'Main Collection', desc: 'Primary DJ library', color: 'cyan', icon: Database },
    { id: 'Collection', label: 'Collection', desc: 'Full library copy', color: 'blue', icon: HardDrive },
    { id: 'PartCollection', label: 'Part Collection', desc: 'Selected genres/folders', color: 'purple', icon: ListMusic },
    { id: 'SetStick', label: 'Set Stick', desc: 'Playlists only (<500 tracks)', color: 'amber', icon: PlayCircle },
];

const SYNC_TYPES = [
    { id: 'collection', label: 'Collection', desc: 'Full library sync', icon: Database, color: 'cyan' },
    { id: 'playlists', label: 'Playlists', desc: 'Selected playlists only', icon: ListMusic, color: 'purple' },
    { id: 'metadata', label: 'Metadata', desc: 'BPM, Key, Rating, Cues', icon: ArrowUpDown, color: 'amber' },
];

const formatBytes = (b) => {
    if (!b) return '0 B';
    const k = 1024;
    const s = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(b) / Math.log(k));
    return `${(b / Math.pow(k, i)).toFixed(1)} ${s[i]}`;
};

const formatDate = (iso) => {
    if (!iso) return 'Never';
    const d = new Date(iso);
    const now = new Date();
    const diff = now - d;
    if (diff < 60000) return 'Just now';
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
    if (diff < 604800000) return `${Math.floor(diff / 86400000)}d ago`;
    return d.toLocaleDateString();
};

// ── Helper to get all descendant IDs ──
const getDescendantIds = (node) => {
    let ids = [];
    if (node.Type !== "0") ids.push(node.ID);
    if (node.Children) {
        node.Children.forEach(c => ids = ids.concat(getDescendantIds(c)));
    }
    return ids;
};

// ── Folder Tree Node for playlist selection ──
const PlaylistTreeNode = ({ node, depth = 0, selectedIds, onToggle }) => {
    const [open, setOpen] = useState(true);
    const isFolder = node.Type === "0";
    const children = node.Children || [];

    if (isFolder) {
        // Calculate folder selection state
        const descendantIds = getDescendantIds(node);
        const selectedCount = descendantIds.filter(id => selectedIds.includes(id)).length;
        const isAll = descendantIds.length > 0 && selectedCount === descendantIds.length;
        const isPartial = selectedCount > 0 && !isAll;

        return (
            <div>
                <div
                    className="w-full flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs hover:bg-white/5 transition-all text-left text-slate-300 group"
                    style={{ paddingLeft: `${depth * 16 + 12}px` }}
                >
                    {/* Toggle Open/Close */}
                    <button onClick={() => setOpen(!open)} className="flex items-center gap-2 outline-none">
                        {open ? <ChevronDown size={10} className="text-amber-400" /> : <ChevronRight size={10} className="text-amber-400/60" />}
                        {open ? <FolderOpen size={12} className="text-amber-400" /> : <Folder size={12} className="text-amber-400/60" />}
                    </button>

                    {/* Select Folder Checkbox */}
                    <button
                        onClick={() => onToggle(node)}
                        className={`w-3 h-3 rounded border flex items-center justify-center ml-1 transition-all ${isAll ? 'bg-purple-500 border-purple-500' :
                            isPartial ? 'bg-purple-500/50 border-purple-500' : 'border-slate-600 hover:border-slate-400'
                            }`}
                    >
                        {isAll && <Check size={8} className="text-white" />}
                        {isPartial && <div className="w-1.5 h-0.5 bg-white rounded-full" />}
                    </button>

                    <span className="font-medium cursor-pointer" onClick={() => setOpen(!open)}>{node.Name}</span>
                    <span className="text-slate-600 text-[9px] ml-auto">{children.filter(c => c.Type !== "0").length}</span>
                </div>
                {open && children.map(child => (
                    <PlaylistTreeNode key={child.ID} node={child} depth={depth + 1} selectedIds={selectedIds} onToggle={onToggle} />
                ))}
            </div>
        );
    }

    const isSelected = selectedIds.includes(node.ID);
    return (
        <button
            onClick={() => onToggle(node)}
            className={`w-full flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs transition-all text-left ${isSelected ? 'bg-purple-500/10 text-purple-400 border border-purple-500/20' : 'hover:bg-white/5 text-slate-400 border border-transparent'}`}
            style={{ paddingLeft: `${depth * 16 + 12}px` }}
        >
            <div className={`w-4 h-4 rounded border flex items-center justify-center shrink-0 ${isSelected ? 'bg-purple-500 border-purple-500' : 'border-white/20'}`}>
                {isSelected && <Check size={10} className="text-white" />}
            </div>
            {node.Type === "4" ? <Zap size={12} className="text-purple-400" /> : <Music size={12} />}
            <span className="truncate">{node.Name}</span>
        </button>
    );
};

// ── Space Usage Bar ──
const SpaceBar = ({ total, free, estimatedUsage }) => {
    if (!total) return null;
    const used = total - free;
    const usedPct = (used / total) * 100;
    const estimatePct = (estimatedUsage / total) * 100;
    const afterFree = free - estimatedUsage;
    const afterFreePct = Math.max(0, (afterFree / total) * 100);

    return (
        <div className="space-y-2">
            <div className="flex items-center justify-between text-[10px] text-slate-400">
                <span>Storage Usage</span>
                <span>{formatBytes(afterFree > 0 ? afterFree : 0)} free after sync</span>
            </div>
            <div className="w-full h-3 bg-white/5 rounded-full overflow-hidden flex">
                <div className="h-full bg-slate-500/60 transition-all" style={{ width: `${usedPct}%` }} title={`Used: ${formatBytes(used)}`} />
                {estimatedUsage > 0 && (
                    <div className={`h-full transition-all ${afterFree < 0 ? 'bg-red-500/80' : 'bg-cyan-500/50'}`}
                        style={{ width: `${Math.min(estimatePct, 100 - usedPct)}%` }}
                        title={`Sync will use: ~${formatBytes(estimatedUsage)}`} />
                )}
            </div>
            <div className="flex items-center gap-4 text-[9px] text-slate-500">
                <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-slate-500/60" /> Used ({formatBytes(used)})</span>
                {estimatedUsage > 0 && <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-cyan-500/50" /> Sync (~{formatBytes(estimatedUsage)})</span>}
                <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-white/5" /> Free ({formatBytes(free)})</span>
            </div>
        </div>
    );
};

const UsbView = () => {
    const [devices, setDevices] = useState([]);
    const [profiles, setProfiles] = useState([]);
    const [selectedDeviceId, setSelectedDeviceId] = useState(null);
    const [scanning, setScanning] = useState(false);
    const [syncing, setSyncing] = useState(null);
    const [syncProgress, setSyncProgress] = useState(null);
    const [diff, setDiff] = useState(null);
    const [playlists, setPlaylists] = useState([]);
    const [playlistTree, setPlaylistTree] = useState([]);
    const [settings, setSettings] = useState({ auto_sync_on_startup: false });
    const [selectedSyncType, setSelectedSyncType] = useState('collection');

    // -- Contents Viewer State --
    const [activeLibrary, setActiveLibrary] = useState('library_one');
    const [usbTracks, setUsbTracks] = useState({ library_one: [], library_legacy: [] });
    const [loadingContents, setLoadingContents] = useState(false);

    const loadUsbContents = useCallback(async (deviceId) => {
        if (!deviceId) return;
        setLoadingContents(true);
        try {
            const res = await api.get(`/api/usb/${deviceId}/contents`);
            setUsbTracks(res.data.tracks || { library_one: [], library_legacy: [] });
        } catch (e) {
            console.error("Failed to load USB contents:", e);
        }
        setLoadingContents(false);
    }, []);

    // ── Data Loading ──
    const scanDevices = useCallback(async () => {
        setScanning(true);
        try {
            const [devRes, profRes] = await Promise.all([
                api.get('/api/usb/devices'),
                api.get('/api/usb/profiles')
            ]);
            setDevices(devRes.data);
            setProfiles(profRes.data);

            if (!selectedDeviceId && devRes.data.length > 0) {
                setSelectedDeviceId(devRes.data[0].device_id);
            }
        } catch (e) {
            console.error('Scan failed:', e);
        }
        setScanning(false);
    }, [selectedDeviceId]);

    const loadPlaylists = useCallback(async () => {
        try {
            const res = await api.get('/api/playlists/tree');
            setPlaylistTree(res.data || []);
            // Also create flat list for backwards compat
            const flattenTree = (nodes, depth = 0) => {
                let flat = [];
                for (const n of (nodes || [])) {
                    flat.push({ ...n, depth });
                    if (n.Children) flat = flat.concat(flattenTree(n.Children, depth + 1));
                }
                return flat;
            };
            setPlaylists(flattenTree(res.data));
        } catch { }
    }, []);

    const loadSettings = useCallback(async () => {
        try {
            const res = await api.get('/api/usb/settings');
            setSettings(res.data);
        } catch { }
    }, []);

    useEffect(() => {
        scanDevices();
        loadPlaylists();
        loadSettings();
    }, []);

    useEffect(() => {
        if (selectedDeviceId) {
            loadUsbContents(selectedDeviceId);
            setActiveLibrary('library_legacy'); // Default to legacy (library_one is SQLCipher-encrypted)
        }
    }, [selectedDeviceId, loadUsbContents]);

    // ── Profile Management ──
    const saveProfile = async (updates) => {
        const device = allDevices.find(d => d.device_id === selectedDeviceId);
        if (!device) return;

        const profile = {
            device_id: device.device_id,
            label: device.label,
            drive: device.drive,
            ...device,
            ...updates
        };

        try {
            const res = await api.post('/api/usb/profiles', profile);
            const saved = res.data.profile;
            setProfiles(prev => {
                const idx = prev.findIndex(p => p.device_id === saved.device_id);
                if (idx >= 0) { const n = [...prev]; n[idx] = saved; return n; }
                return [...prev, saved];
            });
            toast.success('Profile saved');
        } catch (e) {
            toast.error('Failed to save profile');
        }
    };

    const deleteProfile = async (deviceId) => {
        if (!confirm('Delete this device profile? This cannot be undone.')) return;
        try {
            await api.delete(`/api/usb/profiles/${deviceId}`);
            setProfiles(prev => prev.filter(p => p.device_id !== deviceId));
            if (selectedDevice?.device_id === deviceId) setSelectedDevice(null);
            toast.success('Profile deleted');
        } catch {
            toast.error('Failed to delete profile');
        }
    };

    // ── Sync Operations ──
    const runSync = async () => {
        if (!sel) return;
        const syncType = selectedSyncType;
        const playlistIds = selectedSyncType === 'playlists' ? (sel.sync_playlists || []) : [];

        if (syncType === 'playlists' && playlistIds.length === 0) {
            toast.error('Select at least one playlist to sync');
            return;
        }

        setSyncing(sel.device_id);
        setSyncProgress({ stage: 'starting', message: 'Preparing...', progress: 0 });
        try {
            // USB sync is a long-running blocking call (file copy loop can take
            // several minutes for large playlists). The default 10s Axios timeout
            // would abort the HTTP request while the backend is still copying,
            // causing the UI to show "Sync failed" even though the sync itself
            // completes successfully on the server. Disable the timeout here.
            const res = await api.post('/api/usb/sync', {
                device_id: sel.device_id,
                sync_type: syncType,
                playlist_ids: playlistIds,
                library_types: sel.library_types || ["library_legacy"]
            }, { timeout: 0 });
            const result = res.data.result;
            setSyncProgress({ ...result, progress: 100 });
            if (res.data.status === 'success') {
                toast.success(result.message || 'Sync complete!');
                scanDevices();
                // Reload the USB Library Contents viewer — without this the box
                // below keeps showing the pre-sync state ("No tracks found")
                // even after a successful sync wrote the new XML.
                loadUsbContents(sel.device_id);
            } else {
                toast.error(result.message || 'Sync failed');
            }
        } catch (e) {
            toast.error('Sync failed: ' + (e.response?.data?.detail || e.message));
        }
        setTimeout(() => { setSyncing(null); setSyncProgress(null); }, 2000);
    };

    const syncAll = async () => {
        setSyncing('all');
        setSyncProgress({ stage: 'starting', message: 'Syncing all devices...', progress: 0 });
        try {
            const res = await api.post('/api/usb/sync/all');
            toast.success(res.data.result?.message || 'All devices synced');
            scanDevices();
        } catch (e) {
            toast.error('Sync all failed');
        }
        setTimeout(() => { setSyncing(null); setSyncProgress(null); }, 2000);
    };

    const loadDiff = async () => {
        if (!sel?.device_id) return;
        try {
            const res = await api.get(`/api/usb/diff/${sel.device_id}`);
            setDiff(res.data);
        } catch (e) {
            toast.error('Failed to preview: ' + (e.response?.data?.detail || e.message));
            setDiff(null);
        }
    };

    const ejectDrive = async () => {
        if (!sel?.drive) return;
        if (!confirm(`Safely eject ${sel.drive}?`)) return;
        try {
            const res = await api.post('/api/usb/eject', { drive: sel.drive });
            if (res.data.status === 'success') {
                toast.success(res.data.message);
                scanDevices();
            } else {
                toast.error(res.data.message);
            }
        } catch (e) {
            toast.error('Eject failed');
        }
    };

    const resetUsb = async () => {
        if (!sel?.device_id) return;
        if (!confirm('⚠️ This will DELETE all Rekordbox data on this USB. Continue?')) return;
        try {
            const res = await api.post('/api/usb/reset', { device_id: sel.device_id });
            if (res.data.status === 'success') {
                toast.success(res.data.message);
                scanDevices();
            } else {
                toast.error(res.data.message);
            }
        } catch (e) {
            toast.error('Reset failed');
        }
    };

    const handleRename = async () => {
        if (!sel?.drive) return;
        const newLabel = prompt("Enter new name for USB Drive:", sel.label);
        if (!newLabel || newLabel === sel.label) return;

        try {
            const res = await api.post('/api/usb/rename', {
                drive: sel.drive,
                new_label: newLabel
            });
            if (res.data.status === 'success') {
                toast.success(res.data.message);
                setTimeout(scanDevices, 1000); // Wait a sec for Windows to update
            } else {
                toast.error(res.data.message);
            }
        } catch (e) {
            toast.error(e.response?.data?.detail || "Rename failed");
        }
    };

    // ── Helpers ──
    const getTypeInfo = (typeId) => USB_TYPES.find(t => t.id === typeId) || USB_TYPES[1];
    const isConnected = (device) => devices.some(d => d.device_id === device?.device_id);

    const allDevices = useMemo(() => {
        const merged = [
            ...profiles.map(p => {
                const dev = devices.find(d => d.device_id === p.device_id);
                return dev ? { ...p, ...dev } : { ...p, connected: false };
            }),
            ...devices.filter(d => !profiles.some(p => p.device_id === d.device_id))
        ];
        return merged;
    }, [devices, profiles]);

    const sel = useMemo(() => allDevices.find(d => d.device_id === selectedDeviceId), [allDevices, selectedDeviceId]);
    const selType = sel ? getTypeInfo(sel.type) : null;

    const togglePlaylist = (node) => {
        if (!sel) return;
        const current = new Set(sel.sync_playlists || []);
        const targetIds = getDescendantIds(node);

        // Check if all targets are already selected
        const allSelected = targetIds.length > 0 && targetIds.every(id => current.has(id));

        const next = new Set(current);
        if (allSelected) {
            // Deselect all
            targetIds.forEach(id => next.delete(id));
        } else {
            // Select all
            targetIds.forEach(id => next.add(id));
        }

        saveProfile({ sync_playlists: Array.from(next) });
    };

    return (
        <div className="h-full flex flex-col bg-transparent text-white overflow-hidden animate-fade-in">
            {/* Header */}
            <div className="p-6 pb-4 border-b border-white/5">
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-4">
                        <div className="p-3 bg-indigo-500/20 rounded-xl border border-indigo-500/30">
                            <HardDrive size={28} className="text-indigo-400" />
                        </div>
                        <div>
                            <h1 className="text-2xl font-black italic tracking-tighter uppercase">USB Device Manager</h1>
                            <p className="text-slate-500 text-sm">{devices.length} connected · {profiles.length} registered</p>
                        </div>
                    </div>
                    <div className="flex items-center gap-2">
                        <button
                            onClick={syncAll}
                            disabled={!!syncing || profiles.filter(p => isConnected(p)).length === 0}
                            className="flex items-center gap-2 px-4 py-2 bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-400 rounded-xl text-sm font-bold border border-cyan-500/30 transition-all disabled:opacity-30"
                        >
                            <ArrowUpDown size={16} /> Update All
                        </button>
                        <button
                            onClick={scanDevices}
                            disabled={scanning}
                            className="flex items-center gap-2 px-4 py-2 bg-white/5 hover:bg-white/10 rounded-xl text-sm font-bold border border-white/10 transition-all"
                        >
                            <RefreshCw size={16} className={scanning ? 'animate-spin' : ''} /> Scan
                        </button>
                    </div>
                </div>
            </div>

            {/* Main Layout */}
            <div className="flex-1 flex overflow-hidden">
                {/* Left: Device List */}
                <div className="w-72 border-r border-white/5 overflow-y-auto p-3 space-y-1.5">
                    {allDevices.length === 0 && !scanning && (
                        <div className="flex flex-col items-center justify-center h-full text-center p-6">
                            <Usb size={40} className="text-slate-600 mb-4" />
                            <p className="text-slate-500 text-sm">No USB devices detected</p>
                            <p className="text-slate-600 text-xs mt-1">Insert a USB drive and click Scan</p>
                        </div>
                    )}
                    {scanning && allDevices.length === 0 && (
                        <div className="flex items-center justify-center h-32">
                            <Loader2 size={24} className="animate-spin text-indigo-400" />
                        </div>
                    )}

                    {allDevices.map(device => {
                        const type = getTypeInfo(device.type);
                        const connected = isConnected(device);
                        const isSelected = sel?.device_id === device.device_id;
                        const Icon = type.icon;
                        return (
                            <button
                                key={device.device_id}
                                onClick={() => { setSelectedDeviceId(device.device_id); setDiff(null); }}
                                className={`w-full text-left p-3 rounded-xl border transition-all ${isSelected
                                    ? `bg-${type.color}-500/10 border-${type.color}-500/30`
                                    : 'bg-white/[0.02] border-white/5 hover:bg-white/5'
                                    }`}
                            >
                                <div className="flex items-center gap-3">
                                    <div className={`w-2 h-2 rounded-full ${connected ? 'bg-emerald-400 animate-pulse' : 'bg-slate-600'}`} />
                                    <Icon size={18} className={`text-${type.color}-400`} />
                                    <div className="flex-1 min-w-0">
                                        <div className="font-bold text-sm truncate">{device.label || 'USB Drive'}</div>
                                        <div className="text-[10px] text-slate-500 flex items-center gap-2">
                                            <span>{device.drive}</span>
                                            <span>·</span>
                                            <span>{device.track_count || 0} tracks</span>
                                        </div>
                                    </div>
                                    {syncing === device.device_id && (
                                        <Loader2 size={14} className="animate-spin text-cyan-400" />
                                    )}
                                </div>
                                {device.last_sync && (
                                    <div className="mt-1.5 ml-5 text-[9px] text-slate-600 flex items-center gap-1">
                                        <Clock size={8} /> Last: {formatDate(device.last_sync)}
                                    </div>
                                )}
                            </button>
                        );
                    })}
                </div>

                {/* Right: Device Detail */}
                <div className="flex-1 overflow-y-auto p-6">
                    {!sel ? (
                        <div className="flex flex-col items-center justify-center h-full text-center">
                            <HardDrive size={48} className="text-slate-700 mb-4" />
                            <p className="text-slate-500">Select a device from the sidebar</p>
                        </div>
                    ) : (
                        <div className="space-y-6 max-w-3xl">
                            {/* Device Header */}
                            <div className="flex items-center justify-between px-1 mb-4">
                                <h2 className="text-xl font-bold flex items-center gap-3">
                                    <Usb className="text-cyan-400" />
                                    USB Devices
                                </h2>
                                <button
                                    onClick={() => scanDevices()}
                                    className="p-2 hover:bg-white/5 rounded-full text-slate-500 hover:text-cyan-400 transition-all active:rotate-180 duration-500"
                                    title="Scan for devices"
                                >
                                    <RefreshCw size={18} />
                                </button>
                            </div>
                            <div className="flex items-center justify-between">
                                <div>
                                    <h2 className="text-xl font-black italic uppercase tracking-tight flex items-center gap-3">
                                        <div className={`w-3 h-3 rounded-full ${isConnected(sel) ? 'bg-emerald-400' : 'bg-red-400'}`} />
                                        {sel.label || 'USB Drive'}
                                        <button onClick={handleRename} className="p-1 hover:bg-white/10 rounded-lg text-slate-500 hover:text-white transition-colors">
                                            <Edit2 size={16} />
                                        </button>
                                    </h2>
                                    <p className="text-slate-500 text-sm mt-1">
                                        {sel.drive} · {sel.filesystem || 'Unknown FS'} · {formatBytes(sel.total_space)} total · {formatBytes(sel.free_space)} free
                                    </p>
                                </div>
                                <div className="flex items-center gap-2">
                                    <button onClick={() => deleteProfile(sel.device_id)}
                                        className="p-2 hover:bg-red-500/10 text-slate-600 hover:text-red-400 rounded-lg transition-all"
                                        title="Delete profile"
                                    >
                                        <Trash2 size={16} />
                                    </button>
                                </div>
                            </div>

                            {/* Filesystem Compatibility Warning */}
                            {sel.filesystem && !['FAT32', 'EXFAT', 'VFAT'].includes(sel.filesystem.toUpperCase()) && (
                                <div className="glass-panel rounded-2xl p-4 border border-rose-500/20 bg-rose-500/5 flex items-start gap-4">
                                    <div className="p-2 bg-rose-500/10 rounded-full shrink-0">
                                        <AlertTriangle size={20} className="text-rose-400" />
                                    </div>
                                    <div>
                                        <h3 className="font-bold text-rose-200 text-sm">Incompatible Filesystem ({sel.filesystem})</h3>
                                        <p className="text-rose-200/70 text-xs mt-1">
                                            This USB stick is formatted as {sel.filesystem}. Pioneer CDJs and standalone systems usually only support <strong>FAT32</strong> or <strong>exFAT</strong>. It is highly recommended to backup your files and reformat this drive to FAT32 to ensure it can be read by club equipment.
                                        </p>
                                    </div>
                                </div>
                            )}


                            {/* Non-Rekordbox Warning & Init Action */}
                            {!sel.is_rekordbox && (
                                <div className="glass-panel rounded-2xl p-8 border border-amber-500/20 bg-amber-500/5 text-center flex flex-col items-center justify-center space-y-4">
                                    <div className="p-4 bg-amber-500/10 rounded-full">
                                        <AlertTriangle size={32} className="text-amber-400" />
                                    </div>
                                    <div>
                                        <h3 className="text-xl font-bold text-amber-100">No Rekordbox Library Detected</h3>
                                        <p className="text-amber-200/60 text-sm mt-2 max-w-md mx-auto">
                                            This USB drive does not have the required <code className="bg-black/20 px-1 rounded">PIONEER</code> folder structure.
                                        </p>
                                    </div>
                                    <button
                                        onClick={async () => {
                                            try {
                                                await api.post('/api/usb/initialize', { drive: sel.drive });
                                                toast.success("Library initialized!");
                                                setTimeout(() => scanDevices(), 500); // Refresh list to see it as valid with delay
                                            } catch (e) {
                                                console.error(e);
                                                toast.error("Failed to initialize library");
                                            }
                                        }}
                                        className="mt-2 px-6 py-3 bg-amber-500 hover:bg-amber-400 text-black font-bold rounded-xl flex items-center gap-2 transition-all hover:scale-105 active:scale-95"
                                    >
                                        <Database size={18} />
                                        Initialize Library
                                    </button>
                                </div>
                            )}

                            {/* Standard Rekordbox View */}
                            {sel.is_rekordbox && (
                                <>
                                    {/* Space Usage Bar */}
                                    {sel.total_space && (
                                        <div className="glass-panel rounded-2xl p-4 border border-white/5">
                                            <SpaceBar
                                                total={sel.total_space}
                                                free={sel.free_space}
                                                estimatedUsage={diff?.space_estimate || 0}
                                            />
                                        </div>
                                    )}

                                    {/* Type Selector */}
                                    <div className="glass-panel rounded-2xl p-4 border border-white/5">
                                        <div className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-3">Device Type</div>
                                        <div className="grid grid-cols-2 gap-2">
                                            {USB_TYPES.map(type => {
                                                const Icon = type.icon;
                                                const active = sel.type === type.id;
                                                return (
                                                    <button
                                                        key={type.id}
                                                        onClick={() => saveProfile({ type: type.id })}
                                                        className={`flex items-center gap-3 p-3 rounded-xl border transition-all text-left ${active
                                                            ? `bg-${type.color}-500/10 border-${type.color}-500/30 text-${type.color}-400`
                                                            : 'bg-white/[0.02] border-white/5 text-slate-400 hover:bg-white/5'
                                                            }`}
                                                    >
                                                        <Icon size={18} />
                                                        <div>
                                                            <div className="text-xs font-bold">{type.label}</div>
                                                            <div className="text-[9px] text-slate-500">{type.desc}</div>
                                                        </div>
                                                        {active && <Check size={14} className="ml-auto" />}
                                                    </button>
                                                );
                                            })}
                                        </div>
                                    </div>

                                    {/* Sync Controls */}
                                    <div className="glass-panel rounded-2xl p-4 border border-white/5">
                                        <div className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-3">Sync Controls</div>

                                        {/* Sync Type Selector */}
                                        <div className="grid grid-cols-3 gap-2 mb-4">
                                            {SYNC_TYPES.map(st => {
                                                const Icon = st.icon;
                                                const active = selectedSyncType === st.id;
                                                return (
                                                    <button
                                                        key={st.id}
                                                        onClick={() => setSelectedSyncType(st.id)}
                                                        className={`flex flex-col items-center gap-1.5 p-3 rounded-xl border transition-all text-center ${active
                                                            ? `bg-${st.color}-500/15 border-${st.color}-500/30 text-${st.color}-400 ring-1 ring-${st.color}-500/20`
                                                            : 'bg-white/[0.02] border-white/5 text-slate-500 hover:bg-white/5'
                                                            }`}
                                                    >
                                                        <Icon size={18} />
                                                        <span className="text-[10px] font-bold">{st.label}</span>
                                                    </button>
                                                );
                                            })}
                                        </div>

                                        {/* Diff Preview */}
                                        {isConnected(sel) && (
                                            <button onClick={loadDiff}
                                                className="w-full mb-3 flex items-center justify-between px-4 py-2.5 bg-white/[0.03] hover:bg-white/5 rounded-xl border border-white/5 text-xs transition-all"
                                            >
                                                <span className="text-slate-400">Preview Changes</span>
                                                <ChevronRight size={14} className="text-slate-600" />
                                            </button>
                                        )}

                                        {diff && (
                                            <div className="mb-4 p-3 bg-white/[0.02] rounded-xl border border-white/5 text-xs space-y-1.5">
                                                <div className="flex justify-between"><span className="text-slate-400">Tracks to add</span><span className="text-emerald-400 font-bold">+{diff.tracks?.to_add || 0}</span></div>
                                                <div className="flex justify-between"><span className="text-slate-400">Tracks to update</span><span className="text-amber-400 font-bold">~{diff.tracks?.to_update || 0}</span></div>
                                                <div className="flex justify-between"><span className="text-slate-400">Tracks to remove</span><span className="text-red-400 font-bold">-{diff.tracks?.to_remove || 0}</span></div>
                                                <div className="flex justify-between"><span className="text-slate-400">Unchanged</span><span className="text-slate-500">{diff.tracks?.unchanged || 0}</span></div>
                                                <div className="border-t border-white/5 pt-1.5 flex justify-between"><span className="text-slate-400">Playlists to add</span><span className="text-emerald-400 font-bold">+{diff.playlists?.to_add || 0}</span></div>
                                                {diff.space_estimate > 0 && (
                                                    <div className="border-t border-white/5 pt-1.5 flex justify-between">
                                                        <span className="text-slate-400">Est. space needed</span>
                                                        <span className={`font-bold ${diff.space_estimate > (sel.free_space || 0) ? 'text-red-400' : 'text-cyan-400'}`}>
                                                            ~{formatBytes(diff.space_estimate)}
                                                        </span>
                                                    </div>
                                                )}
                                            </div>
                                        )}

                                        {/* Sync + Eject Buttons Row */}
                                        <div className="flex gap-2">
                                            <button
                                                onClick={runSync}
                                                disabled={!!syncing || !isConnected(sel)}
                                                className="flex-1 flex items-center justify-center gap-2 px-4 py-3 bg-gradient-to-r from-cyan-500/20 to-blue-500/20 hover:from-cyan-500/30 hover:to-blue-500/30 text-cyan-400 rounded-xl text-sm font-bold border border-cyan-500/30 transition-all disabled:opacity-30"
                                            >
                                                {syncing === sel.device_id ? (
                                                    <><Loader2 size={16} className="animate-spin" /> Syncing...</>
                                                ) : (
                                                    <><Download size={16} /> Sync {SYNC_TYPES.find(s => s.id === selectedSyncType)?.label}</>
                                                )}
                                            </button>
                                            <button
                                                onClick={ejectDrive}
                                                disabled={!isConnected(sel)}
                                                className="flex items-center gap-2 px-4 py-3 bg-amber-500/10 hover:bg-amber-500/20 text-amber-400 rounded-xl text-sm font-bold border border-amber-500/20 transition-all disabled:opacity-30"
                                            >
                                                <Power size={16} /> Eject
                                            </button>
                                        </div>

                                        {/* Progress Bar */}
                                        {syncing === sel.device_id && syncProgress && (
                                            <div className="mt-4 space-y-2">
                                                <div className="flex items-center justify-between text-xs">
                                                    <span className="text-slate-400">{syncProgress.message}</span>
                                                    <span className="text-cyan-400 font-bold">{Math.max(0, syncProgress.progress)}%</span>
                                                </div>
                                                <div className="w-full h-1.5 bg-white/5 rounded-full overflow-hidden">
                                                    <div
                                                        className="h-full bg-gradient-to-r from-cyan-500 to-blue-500 rounded-full transition-all duration-500"
                                                        style={{ width: `${Math.max(0, syncProgress.progress)}%` }}
                                                    />
                                                </div>
                                            </div>
                                        )}
                                    </div>

                                    {/* Playlist Selection with Folder Tree */}
                                    {selectedSyncType === 'playlists' && (
                                        <div className="glass-panel rounded-2xl p-4 border border-white/5">
                                            <div className="flex items-center justify-between mb-3">
                                                <div className="text-[10px] font-bold text-slate-500 uppercase tracking-widest">Select Playlists</div>
                                                <span className="text-[10px] text-purple-400 font-bold">{(sel.sync_playlists || []).length} selected</span>
                                            </div>
                                            <div className="max-h-64 overflow-y-auto space-y-0.5 pr-1">
                                                {playlistTree.length > 0 ? playlistTree.map(node => (
                                                    <PlaylistTreeNode
                                                        key={node.ID}
                                                        node={node}
                                                        selectedIds={sel.sync_playlists || []}
                                                        onToggle={togglePlaylist}
                                                    />
                                                )) : (
                                                    <p className="text-slate-600 text-xs text-center py-4">No playlists loaded</p>
                                                )}
                                            </div>
                                        </div>
                                    )}

                                    {/* Settings */}
                                    <div className="glass-panel rounded-2xl p-4 border border-white/5">
                                        <div className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-3">Device Settings</div>
                                        <div className="space-y-2">
                                            <label className="flex items-center justify-between p-2 rounded-lg hover:bg-white/[0.02] cursor-pointer transition-all">
                                                <span className="text-sm text-slate-300">Auto-sync on startup</span>
                                                <input
                                                    type="checkbox"
                                                    checked={sel.auto_sync || false}
                                                    onChange={(e) => saveProfile({ auto_sync: e.target.checked })}
                                                    className="accent-cyan-500 w-4 h-4"
                                                />
                                            </label>

                                            <div className="pt-2 border-t border-white/5 mt-2">
                                                <div className="text-[9px] font-bold text-slate-500 uppercase tracking-widest mb-2">Sync Settings</div>

                                                <label className="flex items-center justify-between p-2 rounded-lg hover:bg-white/[0.02] cursor-pointer transition-all">
                                                    <div className="flex flex-col">
                                                        <span className="text-xs text-slate-300">Mirrored Sync</span>
                                                        <span className="text-[9px] text-slate-500 italic">Keep both libraries identical</span>
                                                    </div>
                                                    <input
                                                        type="checkbox"
                                                        checked={sel.sync_mirrored || false}
                                                        onChange={(e) => saveProfile({ sync_mirrored: e.target.checked })}
                                                        className="accent-cyan-500 w-4 h-4"
                                                    />
                                                </label>

                                                {sel.sync_mirrored && (
                                                    <div className="p-2 space-y-2 bg-white/[0.02] rounded-lg mt-1">
                                                        <div className="text-[9px] text-slate-500 uppercase font-bold tracking-tighter">Primary Library (Master)</div>
                                                        <div className="flex gap-2">
                                                            <button
                                                                onClick={() => saveProfile({ sync_primary: 'library_one' })}
                                                                className={`flex-1 py-1 text-[10px] rounded border transition-all ${sel.sync_primary !== 'library_legacy' ? 'bg-cyan-500/10 border-cyan-500/50 text-cyan-400' : 'border-white/10 text-slate-500'}`}
                                                            >
                                                                Newer
                                                            </button>
                                                            <button
                                                                onClick={() => saveProfile({ sync_primary: 'library_legacy' })}
                                                                className={`flex-1 py-1 text-[10px] rounded border transition-all ${sel.sync_primary === 'library_legacy' ? 'bg-purple-500/10 border-purple-500/50 text-purple-400' : 'border-white/10 text-slate-500'}`}
                                                            >
                                                                Legacy
                                                            </button>
                                                        </div>
                                                    </div>
                                                )}
                                            </div>

                                            <div className="pt-2 border-t border-white/5 mt-2">
                                                <div className="text-[9px] font-bold text-slate-500 uppercase tracking-widest mb-2">Target Libraries</div>
                                                <label className="flex items-center justify-between p-2 rounded-lg hover:bg-white/[0.02] cursor-pointer transition-all">
                                                    <div className="flex flex-col">
                                                        <span className="text-xs text-slate-300">Library One</span>
                                                        <span className="text-[9px] text-slate-500 italic">Newer (CDJ-3000/rx3)</span>
                                                    </div>
                                                    <input
                                                        type="checkbox"
                                                        checked={(sel.library_types || ["library_legacy"]).includes("library_one")}
                                                        onChange={(e) => {
                                                            const current = sel.library_types || ["library_legacy"];
                                                            const next = e.target.checked
                                                                ? [...new Set([...current, "library_one"])]
                                                                : current.filter(t => t !== "library_one");
                                                            saveProfile({ library_types: next });
                                                        }}
                                                        className="accent-cyan-500 w-4 h-4"
                                                    />
                                                </label>
                                                <label className="flex items-center justify-between p-2 rounded-lg hover:bg-white/[0.02] cursor-pointer transition-all">
                                                    <div className="flex flex-col">
                                                        <span className="text-xs text-slate-300">Library Legacy</span>
                                                        <span className="text-[9px] text-slate-500 italic">Legacy (CDJ-2000/Nexus)</span>
                                                    </div>
                                                    <input
                                                        type="checkbox"
                                                        checked={(sel.library_types || ["library_legacy"]).includes("library_legacy")}
                                                        onChange={(e) => {
                                                            const current = sel.library_types || ["library_legacy"];
                                                            const next = e.target.checked
                                                                ? [...new Set([...current, "library_legacy"])]
                                                                : current.filter(t => t !== "library_legacy");
                                                            saveProfile({ library_types: next });
                                                        }}
                                                        className="accent-purple-500 w-4 h-4"
                                                    />
                                                </label>
                                            </div>
                                        </div>
                                    </div>

                                    {/* Danger Zone */}
                                    <div className="glass-panel rounded-2xl p-4 border border-red-500/10">
                                        <div className="text-[10px] font-bold text-red-400/50 uppercase tracking-widest mb-3">Danger Zone</div>
                                        <div className="flex gap-2">
                                            <button
                                                onClick={resetUsb}
                                                disabled={!isConnected(sel)}
                                                className="flex items-center gap-2 px-4 py-2 bg-red-500/10 hover:bg-red-500/20 text-red-400 rounded-xl text-xs font-bold border border-red-500/20 transition-all disabled:opacity-30"
                                            >
                                                <Trash2 size={14} /> Reset USB
                                            </button>
                                        </div>
                                    </div>

                                    {/* USB Library View (Inline) */}
                                    <div className="glass-panel rounded-2xl overflow-hidden border border-white/5 flex flex-col bg-white/[0.01]">
                                        <div className="flex items-center justify-between p-4 border-b border-white/5 bg-white/[0.02]">
                                            <h3 className="text-[10px] font-black uppercase tracking-widest flex items-center gap-2 text-slate-400">
                                                <Database size={12} className="text-cyan-400" />
                                                USB Library Contents
                                            </h3>
                                            <div className="flex gap-1 bg-black/40 p-1 rounded-lg border border-white/5">
                                                <button
                                                    onClick={() => setActiveLibrary('library_one')}
                                                    className={`px-2 py-1 text-[9px] font-bold rounded-md transition-all ${activeLibrary === 'library_one' ? 'bg-cyan-500 text-white shadow-lg shadow-cyan-500/20' : 'text-slate-500 hover:text-white'}`}
                                                >
                                                    Library One
                                                </button>
                                                <button
                                                    onClick={() => setActiveLibrary('library_legacy')}
                                                    className={`px-2 py-1 text-[9px] font-bold rounded-md transition-all ${activeLibrary === 'library_legacy' ? 'bg-purple-500 text-white shadow-lg shadow-purple-500/20' : 'text-slate-500 hover:text-white'}`}
                                                >
                                                    Library Legacy
                                                </button>
                                            </div>
                                        </div>

                                        <div className="max-h-[500px] overflow-y-auto">
                                            {loadingContents ? (
                                                <div className="p-12 flex flex-col items-center justify-center gap-3 text-slate-500 italic text-xs">
                                                    <Loader2 size={24} className="animate-spin text-cyan-500" />
                                                    Reading USB Database...
                                                </div>
                                            ) : (usbTracks[activeLibrary] || []).length === 0 ? (
                                                <div className="p-12 flex flex-col items-center justify-center gap-3 text-slate-600 text-center">
                                                    <Music size={32} strokeWidth={1} />
                                                    <p className="text-xs uppercase tracking-tighter font-bold">No tracks found in {activeLibrary === 'library_one' ? 'Newer' : 'Legacy'} format</p>
                                                    <p className="text-[10px] opacity-50">Run sync to populate this library</p>
                                                </div>
                                            ) : (
                                                <div className="py-2">
                                                    {(usbTracks[activeLibrary] || []).map((item, i) => (
                                                        <UsbLibraryTree key={i} item={item} />
                                                    ))}
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                </>
                            )}

                            {/* Stats Footer */}
                            {sel.is_rekordbox && (
                                <div className="flex items-center gap-4 text-[10px] text-slate-600 px-1">
                                    <span>RB USB: {sel.has_export_db ? '✓ exportLibrary.db' : '✗ No DB'}</span>
                                    <span>·</span>
                                    <span>Legacy PDB: {sel.has_legacy_pdb ? '✓' : '✗'}</span>
                                    <span>·</span>
                                    <span>ID: {sel.device_id}</span>
                                </div>
                            )}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

export default UsbView;
