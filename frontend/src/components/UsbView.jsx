/**
 * UsbView — Melodex-styled USB device manager.
 *
 * Reworked from the legacy version with:
 *   • Melodex tokens (mx-* surfaces, ink-* text, amber2 accent, mono data)
 *   • All filesystem types supported (FAT32, exFAT, NTFS, HFS+, APFS, ext*, ReFS…)
 *   • Compatibility matrix: PC + Pioneer CDJ-3000 / CDJ-2000NXS2 / CDJ-2000NXS / older
 *   • Three-tier status:
 *       OK       → green check
 *       WARN     → yellow exclamation (works but limited / firmware-dependent)
 *       INCOMPAT → red X (won't read on this hardware)
 *
 * The matrix is enforced client-side (compat data is static, not from the
 * backend). Backend already reports `filesystem` via GetVolumeInformationW
 * on Windows — we just classify it here.
 */
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
    HardDrive, RefreshCw, Power, Trash2, Check, X, AlertTriangle,
    Loader2, ChevronRight, ChevronDown, Usb, Database, ArrowUpDown, Clock,
    ListMusic, Music, Zap, PlayCircle, Folder, FolderOpen, Download, Edit2,
    ShieldCheck, ShieldAlert, Info,
} from 'lucide-react';
import api from '../api/api';
import toast from 'react-hot-toast';

// ────────────────────────────────────────────────────────────────────
//  COMPATIBILITY DATA
// ────────────────────────────────────────────────────────────────────

/**
 * Pioneer DJ device compatibility matrix per filesystem.
 * Values: 'ok' | 'warn' | 'incompat'
 * Sources: Pioneer DJ official spec sheets + rekordbox docs.
 *   • CDJ-3000:        FAT32, exFAT, HFS+
 *   • CDJ-2000NXS2:    FAT32, exFAT (FW ≥1.40), HFS+ (FW ≥1.40)
 *   • CDJ-2000NXS:     FAT32 only
 *   • Older CDJ:       FAT32 only
 *   • PC (rekordbox):  every filesystem the OS can mount
 */
const FS_COMPAT = {
    FAT32:    { pc: 'ok',     cdj3000: 'ok',     cdj2000nxs2: 'ok',     cdj2000nxs: 'ok',       cdjOlder: 'ok' },
    EXFAT:    { pc: 'ok',     cdj3000: 'ok',     cdj2000nxs2: 'warn',   cdj2000nxs: 'incompat', cdjOlder: 'incompat' },
    'HFS+':   { pc: 'warn',   cdj3000: 'ok',     cdj2000nxs2: 'warn',   cdj2000nxs: 'incompat', cdjOlder: 'incompat' },
    HFSPLUS:  { pc: 'warn',   cdj3000: 'ok',     cdj2000nxs2: 'warn',   cdj2000nxs: 'incompat', cdjOlder: 'incompat' },
    NTFS:     { pc: 'ok',     cdj3000: 'incompat', cdj2000nxs2: 'incompat', cdj2000nxs: 'incompat', cdjOlder: 'incompat' },
    REFS:     { pc: 'ok',     cdj3000: 'incompat', cdj2000nxs2: 'incompat', cdj2000nxs: 'incompat', cdjOlder: 'incompat' },
    EXT2:     { pc: 'warn',   cdj3000: 'incompat', cdj2000nxs2: 'incompat', cdj2000nxs: 'incompat', cdjOlder: 'incompat' },
    EXT3:     { pc: 'warn',   cdj3000: 'incompat', cdj2000nxs2: 'incompat', cdj2000nxs: 'incompat', cdjOlder: 'incompat' },
    EXT4:     { pc: 'warn',   cdj3000: 'incompat', cdj2000nxs2: 'incompat', cdj2000nxs: 'incompat', cdjOlder: 'incompat' },
    BTRFS:    { pc: 'warn',   cdj3000: 'incompat', cdj2000nxs2: 'incompat', cdj2000nxs: 'incompat', cdjOlder: 'incompat' },
    APFS:     { pc: 'warn',   cdj3000: 'incompat', cdj2000nxs2: 'incompat', cdj2000nxs: 'incompat', cdjOlder: 'incompat' },
    UNKNOWN:  { pc: 'warn',   cdj3000: 'warn',   cdj2000nxs2: 'warn',   cdj2000nxs: 'warn',     cdjOlder: 'warn' },
};

/** Friendly notes shown next to warn/incompat statuses. */
const FS_NOTES = {
    FAT32:   '4 GB max file size · widest support',
    EXFAT:   'CDJ-2000NXS2 needs firmware ≥ 1.40 · older CDJs cannot read',
    'HFS+':  'Mac-formatted · only readable on CDJ-3000 & NXS2 (FW ≥ 1.40)',
    HFSPLUS: 'Mac-formatted · only readable on CDJ-3000 & NXS2 (FW ≥ 1.40)',
    NTFS:    'Windows-only · no Pioneer CDJ supports NTFS',
    REFS:    'Modern Windows filesystem · no Pioneer CDJ support',
    EXT4:    'Linux-only · no Pioneer CDJ support',
    EXT3:    'Linux-only · no Pioneer CDJ support',
    EXT2:    'Linux-only · no Pioneer CDJ support',
    BTRFS:   'Linux-only · no Pioneer CDJ support',
    APFS:    'macOS-only · no Pioneer CDJ support',
    UNKNOWN: 'Filesystem could not be detected — please check manually',
};

const CDJ_TARGETS = [
    { id: 'pc',         label: 'PC / rekordbox',  short: 'PC' },
    { id: 'cdj3000',    label: 'CDJ-3000',        short: '3000' },
    { id: 'cdj2000nxs2',label: 'CDJ-2000NXS2',    short: 'NXS2' },
    { id: 'cdj2000nxs', label: 'CDJ-2000NXS',     short: 'NXS' },
    { id: 'cdjOlder',   label: 'Older CDJ',       short: 'Older' },
];

/** Normalize the raw filesystem string into a key into FS_COMPAT. */
const normalizeFs = (raw) => {
    if (!raw) return 'UNKNOWN';
    const v = String(raw).toUpperCase().trim();
    if (v === 'VFAT' || v === 'FAT' || v === 'FAT32') return 'FAT32';
    if (v.includes('EXFAT')) return 'EXFAT';
    if (v.includes('HFS')) return 'HFS+';
    if (v === 'NTFS') return 'NTFS';
    if (v === 'REFS') return 'REFS';
    if (v === 'APFS') return 'APFS';
    if (v === 'EXT2') return 'EXT2';
    if (v === 'EXT3') return 'EXT3';
    if (v === 'EXT4') return 'EXT4';
    if (v === 'BTRFS') return 'BTRFS';
    return 'UNKNOWN';
};

/** Compute the worst status across all CDJs (for the headline summary). */
const worstCdjStatus = (compat) => {
    const cdjOnly = ['cdj3000', 'cdj2000nxs2', 'cdj2000nxs', 'cdjOlder'];
    if (cdjOnly.some(k => compat[k] === 'incompat')) return 'partial';
    if (cdjOnly.some(k => compat[k] === 'warn')) return 'warn';
    return 'ok';
};

// ────────────────────────────────────────────────────────────────────
//  PRESENTATION HELPERS
// ────────────────────────────────────────────────────────────────────

const StatusIcon = ({ status, size = 12 }) => {
    if (status === 'ok')       return <Check size={size} className="text-ok" />;
    if (status === 'warn')     return <AlertTriangle size={size} className="text-amber2" />;
    if (status === 'incompat') return <X size={size} className="text-bad" />;
    return null;
};

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
    const diff = new Date() - d;
    if (diff < 60000)    return 'Just now';
    if (diff < 3600000)  return `${Math.floor(diff / 60000)}m ago`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
    if (diff < 604800000)return `${Math.floor(diff / 86400000)}d ago`;
    return d.toLocaleDateString();
};

const USB_TYPES = [
    { id: 'MainCollection', label: 'Main Collection',  desc: 'Primary DJ library',         icon: Database },
    { id: 'Collection',     label: 'Collection',       desc: 'Full library copy',          icon: HardDrive },
    { id: 'PartCollection', label: 'Part Collection',  desc: 'Selected genres / folders',  icon: ListMusic },
    { id: 'SetStick',       label: 'Set Stick',        desc: 'Playlists only (<500 tracks)', icon: PlayCircle },
];

const SYNC_TYPES = [
    { id: 'collection', label: 'Collection', icon: Database },
    { id: 'playlists',  label: 'Playlists',  icon: ListMusic },
    { id: 'metadata',   label: 'Metadata',   icon: ArrowUpDown },
];

// ────────────────────────────────────────────────────────────────────
//  COMPATIBILITY PANEL
// ────────────────────────────────────────────────────────────────────

const CompatibilityPanel = ({ filesystem }) => {
    const fsKey = normalizeFs(filesystem);
    const compat = FS_COMPAT[fsKey] || FS_COMPAT.UNKNOWN;
    const note = FS_NOTES[fsKey];
    const worst = worstCdjStatus(compat);

    const headline = {
        ok:      { tone: 'ok',     icon: ShieldCheck,  label: 'Compatible with all Pioneer CDJs' },
        warn:    { tone: 'amber2', icon: ShieldAlert,  label: 'Works on most CDJs — see warnings' },
        partial: { tone: 'amber2', icon: ShieldAlert,  label: 'Works on PC but limited on CDJs' },
    }[worst] || { tone: 'amber2', icon: Info, label: 'Compatibility unknown' };

    const Hdr = headline.icon;

    return (
        <div className="mx-card p-4">
            <div className="flex items-center justify-between mb-3">
                <span className="mx-caption">Hardware Compatibility</span>
                <span className="mx-chip mx-chip-amber font-mono">{fsKey}</span>
            </div>

            {/* Headline */}
            <div className="flex items-start gap-3 mb-4">
                <Hdr size={20} className={`text-${headline.tone} mt-0.5 shrink-0`} />
                <div className="min-w-0">
                    <div className="text-[13px] text-ink-primary font-medium">{headline.label}</div>
                    {note && <div className="text-tiny text-ink-muted mt-0.5">{note}</div>}
                </div>
            </div>

            {/* Per-target matrix */}
            <div className="grid grid-cols-5 gap-1.5">
                {CDJ_TARGETS.map(t => {
                    const status = compat[t.id] || 'warn';
                    const ringColor = status === 'ok' ? 'ok' : status === 'warn' ? 'amber2' : 'bad';
                    const bgClass = status === 'ok'
                        ? 'bg-ok/5 border-ok/30'
                        : status === 'warn'
                            ? 'bg-amber2/5 border-amber2/30'
                            : 'bg-bad/5 border-bad/30';
                    const titleText = status === 'ok'
                        ? `${t.label}: fully supported`
                        : status === 'warn'
                            ? `${t.label}: limited — ${note || 'check firmware'}`
                            : `${t.label}: NOT supported by ${fsKey}`;
                    return (
                        <div
                            key={t.id}
                            title={titleText}
                            className={`flex flex-col items-center gap-1.5 p-2 rounded-mx-sm border ${bgClass}`}
                        >
                            <StatusIcon status={status} size={14} />
                            <span className={`text-[10px] font-mono text-${ringColor} text-center leading-tight`}>
                                {t.short}
                            </span>
                        </div>
                    );
                })}
            </div>
        </div>
    );
};

// ────────────────────────────────────────────────────────────────────
//  PLAYLIST TREE
// ────────────────────────────────────────────────────────────────────

const getDescendantIds = (node) => {
    let ids = [];
    if (node.Type !== '0') ids.push(node.ID);
    if (node.Children) node.Children.forEach(c => { ids = ids.concat(getDescendantIds(c)); });
    return ids;
};

const PlaylistTreeNode = ({ node, depth = 0, selectedIds, onToggle }) => {
    const [open, setOpen] = useState(true);
    const isFolder = node.Type === '0';
    const children = node.Children || [];

    if (isFolder) {
        const descendantIds = getDescendantIds(node);
        const selectedCount = descendantIds.filter(id => selectedIds.includes(id)).length;
        const isAll = descendantIds.length > 0 && selectedCount === descendantIds.length;
        const isPartial = selectedCount > 0 && !isAll;

        return (
            <div>
                <div
                    className="w-full flex items-center gap-2 px-3 py-1 text-[12px] hover:bg-mx-hover transition-all text-left text-ink-primary group"
                    style={{ paddingLeft: `${depth * 14 + 12}px` }}
                >
                    <button onClick={() => setOpen(!open)} className="flex items-center gap-1.5 outline-none">
                        {open ? <ChevronDown size={10} className="text-amber2" /> : <ChevronRight size={10} className="text-amber2/60" />}
                        {open ? <FolderOpen size={12} className="text-amber2" /> : <Folder size={12} className="text-amber2/60" />}
                    </button>
                    <button
                        onClick={() => onToggle(node)}
                        className={`w-3 h-3 rounded-mx-xs border flex items-center justify-center transition-all ${
                            isAll
                                ? 'bg-amber2 border-amber2'
                                : isPartial
                                    ? 'bg-amber2/50 border-amber2'
                                    : 'border-line-default hover:border-line-interactive'
                        }`}
                    >
                        {isAll && <Check size={8} className="text-mx-deepest" />}
                        {isPartial && <div className="w-1.5 h-0.5 bg-mx-deepest rounded-full" />}
                    </button>
                    <span className="font-medium cursor-pointer truncate" onClick={() => setOpen(!open)}>{node.Name}</span>
                    <span className="font-mono text-[10px] text-ink-muted ml-auto">{children.filter(c => c.Type !== '0').length}</span>
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
            className={`w-full flex items-center gap-2 px-3 py-1 text-[12px] transition-all text-left border ${
                isSelected
                    ? 'bg-amber2/10 text-amber2 border-amber2/30'
                    : 'hover:bg-mx-hover text-ink-secondary border-transparent'
            }`}
            style={{ paddingLeft: `${depth * 14 + 12}px` }}
        >
            <div className={`w-3.5 h-3.5 rounded-mx-xs border flex items-center justify-center shrink-0 ${
                isSelected ? 'bg-amber2 border-amber2' : 'border-line-default'
            }`}>
                {isSelected && <Check size={9} className="text-mx-deepest" />}
            </div>
            {node.Type === '4' ? <Zap size={11} className="text-amber2" /> : <Music size={11} />}
            <span className="truncate">{node.Name}</span>
        </button>
    );
};

// ────────────────────────────────────────────────────────────────────
//  USB CONTENTS TREE
// ────────────────────────────────────────────────────────────────────

const UsbLibraryTree = ({ item, level = 0 }) => {
    const [isExpanded, setIsExpanded] = useState(level < 1);

    if (item.type === 'folder') {
        return (
            <div className="select-none">
                <div
                    onClick={() => setIsExpanded(!isExpanded)}
                    className="flex items-center gap-2 px-3 py-1 hover:bg-mx-hover cursor-pointer transition-all group"
                    style={{ paddingLeft: `${level * 12 + 12}px` }}
                >
                    {isExpanded ? <ChevronDown size={12} className="text-ink-muted" /> : <ChevronRight size={12} className="text-ink-muted" />}
                    <Folder size={13} className={isExpanded ? 'text-amber2' : 'text-ink-secondary'} />
                    <span className={`text-[12px] ${isExpanded ? 'text-ink-primary font-medium' : 'text-ink-secondary'}`}>{item.name}</span>
                    <span className="text-[10px] font-mono text-ink-muted opacity-0 group-hover:opacity-100 ml-auto">
                        {item.children.length}
                    </span>
                </div>
                {isExpanded && (
                    <div className="border-l border-line-subtle ml-3">
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
            className="flex items-center gap-3 px-3 py-1 hover:bg-mx-hover transition-all group"
            style={{ paddingLeft: `${level * 12 + 28}px` }}
        >
            <div className="flex-1 min-w-0">
                <div className="text-[12px] font-medium text-ink-primary truncate">{item.Title}</div>
                <div className="text-[10px] text-ink-muted truncate">{item.ArtistName || 'Unknown Artist'}</div>
            </div>
            <div className="text-[10px] text-ink-muted font-mono opacity-0 group-hover:opacity-100 transition-opacity">
                {item.BPM ? (item.BPM / 100).toFixed(2) : '—'}
            </div>
        </div>
    );
};

// ────────────────────────────────────────────────────────────────────
//  SPACE BAR
// ────────────────────────────────────────────────────────────────────

const SpaceBar = ({ total, free, estimatedUsage }) => {
    if (!total) return null;
    const used = total - free;
    const usedPct = (used / total) * 100;
    const estimatePct = (estimatedUsage / total) * 100;
    const afterFree = free - estimatedUsage;

    return (
        <div className="space-y-2">
            <div className="flex items-center justify-between text-[10px]">
                <span className="mx-caption">Storage</span>
                <span className="font-mono text-ink-secondary">
                    {formatBytes(afterFree > 0 ? afterFree : 0)} free after sync
                </span>
            </div>
            <div className="w-full h-2 bg-mx-input rounded-full overflow-hidden flex border border-line-subtle">
                <div
                    className="h-full transition-all"
                    style={{ width: `${usedPct}%`, background: 'var(--ink-muted)' }}
                    title={`Used: ${formatBytes(used)}`}
                />
                {estimatedUsage > 0 && (
                    <div
                        className="h-full transition-all"
                        style={{
                            width: `${Math.min(estimatePct, 100 - usedPct)}%`,
                            background: afterFree < 0 ? 'var(--bad)' : 'var(--amber)',
                        }}
                        title={`Sync: ~${formatBytes(estimatedUsage)}`}
                    />
                )}
            </div>
            <div className="flex items-center gap-3 text-[10px] text-ink-muted">
                <span className="flex items-center gap-1">
                    <span className="w-1.5 h-1.5 rounded-full" style={{ background: 'var(--ink-muted)' }} /> Used {formatBytes(used)}
                </span>
                {estimatedUsage > 0 && (
                    <span className="flex items-center gap-1">
                        <span className="w-1.5 h-1.5 rounded-full" style={{ background: 'var(--amber)' }} /> Sync ~{formatBytes(estimatedUsage)}
                    </span>
                )}
                <span className="flex items-center gap-1">
                    <span className="w-1.5 h-1.5 rounded-full bg-mx-input border border-line-subtle" /> Free {formatBytes(free)}
                </span>
            </div>
        </div>
    );
};

// ────────────────────────────────────────────────────────────────────
//  MAIN VIEW
// ────────────────────────────────────────────────────────────────────

const UsbView = () => {
    const [devices, setDevices] = useState([]);
    const [profiles, setProfiles] = useState([]);
    const [selectedDeviceId, setSelectedDeviceId] = useState(null);
    const [scanning, setScanning] = useState(false);
    const [syncing, setSyncing] = useState(null);
    const [syncProgress, setSyncProgress] = useState(null);
    const [diff, setDiff] = useState(null);
    const [playlistTree, setPlaylistTree] = useState([]);
    const [selectedSyncType, setSelectedSyncType] = useState('collection');

    // Contents viewer
    const [activeLibrary, setActiveLibrary] = useState('library_legacy');
    const [usbTracks, setUsbTracks] = useState({ library_one: [], library_legacy: [] });
    const [loadingContents, setLoadingContents] = useState(false);

    // ── Loaders ──────────────────────────────────────────────────
    const loadUsbContents = useCallback(async (deviceId) => {
        if (!deviceId) return;
        setLoadingContents(true);
        try {
            const res = await api.get(`/api/usb/${deviceId}/contents`);
            setUsbTracks(res.data.tracks || { library_one: [], library_legacy: [] });
        } catch (e) {
            console.error('Failed to load USB contents', e);
        }
        setLoadingContents(false);
    }, []);

    const scanDevices = useCallback(async () => {
        setScanning(true);
        try {
            const [devRes, profRes] = await Promise.all([
                api.get('/api/usb/devices'),
                api.get('/api/usb/profiles'),
            ]);
            setDevices(devRes.data);
            setProfiles(profRes.data);
            if (!selectedDeviceId && devRes.data.length > 0) {
                setSelectedDeviceId(devRes.data[0].device_id);
            }
        } catch (e) {
            console.error('Scan failed', e);
        }
        setScanning(false);
    }, [selectedDeviceId]);

    const loadPlaylists = useCallback(async () => {
        try {
            const res = await api.get('/api/playlists/tree');
            setPlaylistTree(res.data || []);
        } catch { /* noop */ }
    }, []);

    useEffect(() => {
        scanDevices();
        loadPlaylists();
    }, []);  // eslint-disable-line react-hooks/exhaustive-deps

    useEffect(() => {
        if (selectedDeviceId) loadUsbContents(selectedDeviceId);
    }, [selectedDeviceId, loadUsbContents]);

    // ── Derived ──────────────────────────────────────────────────
    const allDevices = useMemo(() => [
        ...profiles.map(p => {
            const dev = devices.find(d => d.device_id === p.device_id);
            return dev ? { ...p, ...dev } : { ...p, connected: false };
        }),
        ...devices.filter(d => !profiles.some(p => p.device_id === d.device_id)),
    ], [devices, profiles]);

    const sel = useMemo(
        () => allDevices.find(d => d.device_id === selectedDeviceId),
        [allDevices, selectedDeviceId]
    );

    const isConnected = useCallback(
        (device) => devices.some(d => d.device_id === device?.device_id),
        [devices]
    );

    // ── Mutations ────────────────────────────────────────────────
    const saveProfile = async (updates) => {
        const device = allDevices.find(d => d.device_id === selectedDeviceId);
        if (!device) return;
        const profile = { device_id: device.device_id, label: device.label, drive: device.drive, ...device, ...updates };
        try {
            const res = await api.post('/api/usb/profiles', profile);
            const saved = res.data.profile;
            setProfiles(prev => {
                const idx = prev.findIndex(p => p.device_id === saved.device_id);
                if (idx >= 0) { const n = [...prev]; n[idx] = saved; return n; }
                return [...prev, saved];
            });
            toast.success('Profile saved');
        } catch {
            toast.error('Failed to save profile');
        }
    };

    const deleteProfile = async (deviceId) => {
        if (!confirm('Delete this device profile? This cannot be undone.')) return;
        try {
            await api.delete(`/api/usb/profiles/${deviceId}`);
            setProfiles(prev => prev.filter(p => p.device_id !== deviceId));
            toast.success('Profile deleted');
        } catch {
            toast.error('Failed to delete profile');
        }
    };

    const runSync = async () => {
        if (!sel) return;
        const playlistIds = selectedSyncType === 'playlists' ? (sel.sync_playlists || []) : [];
        if (selectedSyncType === 'playlists' && playlistIds.length === 0) {
            toast.error('Select at least one playlist to sync');
            return;
        }
        setSyncing(sel.device_id);
        setSyncProgress({ stage: 'starting', message: 'Preparing…', progress: 0 });
        try {
            const res = await api.post('/api/usb/sync', {
                device_id: sel.device_id,
                sync_type: selectedSyncType,
                playlist_ids: playlistIds,
                library_types: sel.library_types || ['library_legacy'],
            }, { timeout: 0 });
            const result = res.data.result;
            setSyncProgress({ ...result, progress: 100 });
            if (res.data.status === 'success') {
                toast.success(result.message || 'Sync complete');
                scanDevices();
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
        setSyncProgress({ stage: 'starting', message: 'Syncing all devices…', progress: 0 });
        try {
            const res = await api.post('/api/usb/sync/all');
            toast.success(res.data.result?.message || 'All devices synced');
            scanDevices();
        } catch {
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
            toast.error('Preview failed: ' + (e.response?.data?.detail || e.message));
            setDiff(null);
        }
    };

    const ejectDrive = async () => {
        if (!sel?.drive) return;
        if (!confirm(`Safely eject ${sel.drive}?`)) return;
        try {
            const res = await api.post('/api/usb/eject', { drive: sel.drive });
            res.data.status === 'success' ? toast.success(res.data.message) : toast.error(res.data.message);
            scanDevices();
        } catch {
            toast.error('Eject failed');
        }
    };

    const resetUsb = async () => {
        if (!sel?.device_id) return;
        if (!confirm('This will DELETE all Rekordbox data on this USB. Continue?')) return;
        try {
            const res = await api.post('/api/usb/reset', { device_id: sel.device_id });
            res.data.status === 'success' ? toast.success(res.data.message) : toast.error(res.data.message);
            scanDevices();
        } catch {
            toast.error('Reset failed');
        }
    };

    const handleRename = async () => {
        if (!sel?.drive) return;
        const newLabel = prompt('Enter new name for USB drive:', sel.label);
        if (!newLabel || newLabel === sel.label) return;
        try {
            const res = await api.post('/api/usb/rename', { drive: sel.drive, new_label: newLabel });
            res.data.status === 'success' ? toast.success(res.data.message) : toast.error(res.data.message);
            setTimeout(scanDevices, 1000);
        } catch (e) {
            toast.error(e.response?.data?.detail || 'Rename failed');
        }
    };

    const togglePlaylist = (node) => {
        if (!sel) return;
        const current = new Set(sel.sync_playlists || []);
        const targetIds = getDescendantIds(node);
        const allSelected = targetIds.length > 0 && targetIds.every(id => current.has(id));
        const next = new Set(current);
        targetIds.forEach(id => { allSelected ? next.delete(id) : next.add(id); });
        saveProfile({ sync_playlists: Array.from(next) });
    };

    const initLibrary = async () => {
        try {
            await api.post('/api/usb/initialize', { drive: sel.drive });
            toast.success('Library initialized');
            setTimeout(scanDevices, 500);
        } catch {
            toast.error('Failed to initialize library');
        }
    };

    // ── Render ───────────────────────────────────────────────────
    return (
        <div className="h-full flex flex-col bg-mx-deepest text-ink-primary overflow-hidden animate-fade-in">
            {/* Header */}
            <div className="px-6 py-4 border-b border-line-subtle flex items-center justify-between">
                <div className="flex items-center gap-3">
                    <div className="p-2.5 bg-amber2/10 rounded-mx-md border border-amber2-dim">
                        <HardDrive size={20} className="text-amber2" />
                    </div>
                    <div>
                        <h1 className="text-[20px] font-semibold tracking-tight">USB Export</h1>
                        <p className="text-tiny text-ink-muted font-mono">
                            {devices.length} connected · {profiles.length} registered
                        </p>
                    </div>
                </div>
                <div className="flex items-center gap-2">
                    <button
                        onClick={syncAll}
                        disabled={!!syncing || profiles.filter(isConnected).length === 0}
                        className="btn-primary flex items-center gap-2 disabled:opacity-30 disabled:cursor-not-allowed"
                    >
                        <ArrowUpDown size={14} /> Update All
                    </button>
                    <button
                        onClick={scanDevices}
                        disabled={scanning}
                        className="btn-secondary flex items-center gap-2"
                    >
                        <RefreshCw size={14} className={scanning ? 'animate-spin' : ''} /> Scan
                    </button>
                </div>
            </div>

            {/* Main */}
            <div className="flex-1 flex overflow-hidden">
                {/* Device list */}
                <div className="w-72 border-r border-line-subtle overflow-y-auto p-2 space-y-1 bg-mx-shell">
                    <div className="mx-caption px-3 py-2">Devices</div>

                    {allDevices.length === 0 && !scanning && (
                        <div className="flex flex-col items-center justify-center h-48 text-center px-4">
                            <Usb size={32} className="text-ink-placeholder mb-3" />
                            <p className="text-[12px] text-ink-muted">No USB devices detected</p>
                            <p className="text-[10px] text-ink-placeholder mt-1">Insert a drive and click Scan</p>
                        </div>
                    )}
                    {scanning && allDevices.length === 0 && (
                        <div className="flex items-center justify-center h-32">
                            <Loader2 size={20} className="animate-spin text-amber2" />
                        </div>
                    )}

                    {allDevices.map(device => {
                        const connected = isConnected(device);
                        const isSelected = sel?.device_id === device.device_id;
                        const fsKey = normalizeFs(device.filesystem);
                        const compat = FS_COMPAT[fsKey] || FS_COMPAT.UNKNOWN;
                        const worst = worstCdjStatus(compat);
                        return (
                            <button
                                key={device.device_id}
                                onClick={() => { setSelectedDeviceId(device.device_id); setDiff(null); }}
                                className={`w-full text-left p-2.5 rounded-mx-sm border transition-all ${
                                    isSelected
                                        ? 'bg-mx-selected border-amber2/50'
                                        : 'bg-mx-card border-line-subtle hover:bg-mx-hover hover:border-line-default'
                                }`}
                            >
                                <div className="flex items-center gap-2.5">
                                    <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                                        connected ? 'bg-ok shadow-[0_0_4px_#3DD68C]' : 'bg-ink-placeholder'
                                    }`} />
                                    <HardDrive size={14} className={isSelected ? 'text-amber2' : 'text-ink-secondary'} />
                                    <div className="flex-1 min-w-0">
                                        <div className="text-[13px] font-medium text-ink-primary truncate">
                                            {device.label || 'USB Drive'}
                                        </div>
                                        <div className="text-[10px] text-ink-muted font-mono flex items-center gap-1.5">
                                            <span>{device.drive}</span>
                                            <span>·</span>
                                            <span>{fsKey}</span>
                                            <span>·</span>
                                            <span>{device.track_count || 0} tr</span>
                                        </div>
                                    </div>
                                    {/* Compat status badge */}
                                    {worst === 'partial' && (
                                        <X size={12} className="text-bad shrink-0" title="Won't work on Pioneer CDJs" />
                                    )}
                                    {worst === 'warn' && (
                                        <AlertTriangle size={12} className="text-amber2 shrink-0" title="Limited CDJ support" />
                                    )}
                                    {syncing === device.device_id && (
                                        <Loader2 size={12} className="animate-spin text-amber2 shrink-0" />
                                    )}
                                </div>
                                {device.last_sync && (
                                    <div className="mt-1.5 ml-5 text-[10px] text-ink-placeholder font-mono flex items-center gap-1">
                                        <Clock size={9} /> {formatDate(device.last_sync)}
                                    </div>
                                )}
                            </button>
                        );
                    })}
                </div>

                {/* Detail */}
                <div className="flex-1 overflow-y-auto p-6">
                    {!sel ? (
                        <div className="flex flex-col items-center justify-center h-full text-center">
                            <HardDrive size={40} className="text-ink-placeholder mb-3" />
                            <p className="text-ink-muted text-[13px]">Select a device from the list</p>
                        </div>
                    ) : (
                        <div className="space-y-5 max-w-3xl">
                            {/* Device header */}
                            <div className="flex items-start justify-between">
                                <div>
                                    <h2 className="text-[18px] font-semibold tracking-tight flex items-center gap-2.5">
                                        <div className={`w-2 h-2 rounded-full ${
                                            isConnected(sel) ? 'bg-ok shadow-[0_0_6px_#3DD68C]' : 'bg-bad'
                                        }`} />
                                        {sel.label || 'USB Drive'}
                                        <button
                                            onClick={handleRename}
                                            className="p-1 hover:bg-mx-hover rounded-mx-sm text-ink-muted hover:text-amber2 transition-colors"
                                            title="Rename drive"
                                        >
                                            <Edit2 size={13} />
                                        </button>
                                    </h2>
                                    <p className="text-tiny text-ink-muted font-mono mt-1">
                                        {sel.drive} · {normalizeFs(sel.filesystem)} · {formatBytes(sel.total_space)} total · {formatBytes(sel.free_space)} free
                                    </p>
                                </div>
                                <button
                                    onClick={() => deleteProfile(sel.device_id)}
                                    className="p-2 hover:bg-bad/10 text-ink-muted hover:text-bad rounded-mx-sm transition-all"
                                    title="Delete profile"
                                >
                                    <Trash2 size={14} />
                                </button>
                            </div>

                            {/* Compatibility — always shown, all FS types supported */}
                            <CompatibilityPanel filesystem={sel.filesystem} />

                            {/* Non-Rekordbox state */}
                            {!sel.is_rekordbox && (
                                <div
                                    className="mx-card p-6 text-center flex flex-col items-center gap-3"
                                    style={{ background: 'var(--amber-bg)', borderColor: 'var(--amber-dim)' }}
                                >
                                    <AlertTriangle size={28} className="text-amber2" />
                                    <div>
                                        <div className="text-[14px] font-semibold text-ink-primary">No Rekordbox library detected</div>
                                        <p className="text-tiny text-ink-secondary mt-1 max-w-md">
                                            This drive doesn't have the <code className="font-mono text-amber2">PIONEER</code> folder structure.
                                        </p>
                                    </div>
                                    <button onClick={initLibrary} className="btn-primary flex items-center gap-2 mt-2">
                                        <Database size={14} /> Initialize Library
                                    </button>
                                </div>
                            )}

                            {sel.is_rekordbox && (
                                <>
                                    {/* Storage */}
                                    {sel.total_space && (
                                        <div className="mx-card p-4">
                                            <SpaceBar
                                                total={sel.total_space}
                                                free={sel.free_space}
                                                estimatedUsage={diff?.space_estimate || 0}
                                            />
                                        </div>
                                    )}

                                    {/* Device type */}
                                    <div className="mx-card p-4">
                                        <div className="mx-caption mb-3">Device Type</div>
                                        <div className="grid grid-cols-2 gap-2">
                                            {USB_TYPES.map(type => {
                                                const Icon = type.icon;
                                                const active = sel.type === type.id;
                                                return (
                                                    <button
                                                        key={type.id}
                                                        onClick={() => saveProfile({ type: type.id })}
                                                        className={`flex items-center gap-2.5 p-2.5 rounded-mx-sm border transition-all text-left ${
                                                            active
                                                                ? 'bg-amber2/10 border-amber2/50 text-amber2'
                                                                : 'bg-mx-input border-line-subtle text-ink-secondary hover:bg-mx-hover hover:border-line-default'
                                                        }`}
                                                    >
                                                        <Icon size={15} />
                                                        <div className="min-w-0">
                                                            <div className="text-[12px] font-medium">{type.label}</div>
                                                            <div className="text-[10px] text-ink-muted truncate">{type.desc}</div>
                                                        </div>
                                                        {active && <Check size={12} className="ml-auto" />}
                                                    </button>
                                                );
                                            })}
                                        </div>
                                    </div>

                                    {/* Sync controls */}
                                    <div className="mx-card p-4">
                                        <div className="mx-caption mb-3">Sync</div>
                                        <div className="grid grid-cols-3 gap-2 mb-3">
                                            {SYNC_TYPES.map(st => {
                                                const Icon = st.icon;
                                                const active = selectedSyncType === st.id;
                                                return (
                                                    <button
                                                        key={st.id}
                                                        onClick={() => setSelectedSyncType(st.id)}
                                                        className={`flex flex-col items-center gap-1.5 py-2.5 px-2 rounded-mx-sm border transition-all ${
                                                            active
                                                                ? 'bg-amber2/10 border-amber2/50 text-amber2'
                                                                : 'bg-mx-input border-line-subtle text-ink-muted hover:bg-mx-hover'
                                                        }`}
                                                    >
                                                        <Icon size={15} />
                                                        <span className="text-[10px] font-semibold uppercase tracking-wider">{st.label}</span>
                                                    </button>
                                                );
                                            })}
                                        </div>

                                        {isConnected(sel) && (
                                            <button
                                                onClick={loadDiff}
                                                className="w-full mb-3 flex items-center justify-between px-3 py-2 bg-mx-input hover:bg-mx-hover rounded-mx-sm border border-line-subtle text-tiny transition-all"
                                            >
                                                <span className="text-ink-secondary">Preview changes</span>
                                                <ChevronRight size={12} className="text-ink-muted" />
                                            </button>
                                        )}

                                        {diff && (
                                            <div className="mb-3 p-3 bg-mx-input rounded-mx-sm border border-line-subtle text-tiny font-mono space-y-1">
                                                <Row label="Tracks add"    value={`+${diff.tracks?.to_add || 0}`}    color="ok" />
                                                <Row label="Tracks update" value={`~${diff.tracks?.to_update || 0}`} color="amber2" />
                                                <Row label="Tracks remove" value={`-${diff.tracks?.to_remove || 0}`} color="bad" />
                                                <Row label="Unchanged"     value={diff.tracks?.unchanged || 0} muted />
                                                <div className="border-t border-line-subtle pt-1 mt-1">
                                                    <Row label="Playlists add" value={`+${diff.playlists?.to_add || 0}`} color="ok" />
                                                </div>
                                                {diff.space_estimate > 0 && (
                                                    <div className="border-t border-line-subtle pt-1 mt-1">
                                                        <Row
                                                            label="Est. space"
                                                            value={`~${formatBytes(diff.space_estimate)}`}
                                                            color={diff.space_estimate > (sel.free_space || 0) ? 'bad' : 'amber2'}
                                                        />
                                                    </div>
                                                )}
                                            </div>
                                        )}

                                        <div className="flex gap-2">
                                            <button
                                                onClick={runSync}
                                                disabled={!!syncing || !isConnected(sel)}
                                                className="btn-primary flex-1 flex items-center justify-center gap-2 disabled:opacity-30 disabled:cursor-not-allowed"
                                            >
                                                {syncing === sel.device_id
                                                    ? <><Loader2 size={14} className="animate-spin" /> Syncing…</>
                                                    : <><Download size={14} /> Sync {SYNC_TYPES.find(s => s.id === selectedSyncType)?.label}</>}
                                            </button>
                                            <button
                                                onClick={ejectDrive}
                                                disabled={!isConnected(sel)}
                                                className="btn-secondary flex items-center gap-2 disabled:opacity-30"
                                            >
                                                <Power size={14} /> Eject
                                            </button>
                                        </div>

                                        {syncing === sel.device_id && syncProgress && (
                                            <div className="mt-3 space-y-1.5">
                                                <div className="flex items-center justify-between text-tiny">
                                                    <span className="text-ink-secondary">{syncProgress.message}</span>
                                                    <span className="font-mono text-amber2">{Math.max(0, syncProgress.progress)}%</span>
                                                </div>
                                                <div className="w-full h-1 bg-line-subtle rounded-full overflow-hidden">
                                                    <div
                                                        className="h-full bg-amber2 rounded-full transition-all duration-500"
                                                        style={{ width: `${Math.max(0, syncProgress.progress)}%` }}
                                                    />
                                                </div>
                                            </div>
                                        )}
                                    </div>

                                    {/* Playlist selection */}
                                    {selectedSyncType === 'playlists' && (
                                        <div className="mx-card p-4">
                                            <div className="flex items-center justify-between mb-3">
                                                <span className="mx-caption">Select Playlists</span>
                                                <span className="text-[10px] font-mono text-amber2">
                                                    {(sel.sync_playlists || []).length} selected
                                                </span>
                                            </div>
                                            <div className="max-h-64 overflow-y-auto pr-1 -mx-1">
                                                {playlistTree.length > 0 ? playlistTree.map(node => (
                                                    <PlaylistTreeNode
                                                        key={node.ID}
                                                        node={node}
                                                        selectedIds={sel.sync_playlists || []}
                                                        onToggle={togglePlaylist}
                                                    />
                                                )) : (
                                                    <p className="text-ink-placeholder text-tiny text-center py-4">No playlists loaded</p>
                                                )}
                                            </div>
                                        </div>
                                    )}

                                    {/* Settings */}
                                    <div className="mx-card p-4">
                                        <div className="mx-caption mb-3">Settings</div>
                                        <Toggle
                                            label="Auto-sync on startup"
                                            checked={sel.auto_sync || false}
                                            onChange={(v) => saveProfile({ auto_sync: v })}
                                        />
                                        <Toggle
                                            label="Mirrored sync"
                                            sub="Keep both libraries identical"
                                            checked={sel.sync_mirrored || false}
                                            onChange={(v) => saveProfile({ sync_mirrored: v })}
                                        />
                                        {sel.sync_mirrored && (
                                            <div className="mt-2 p-2.5 bg-mx-input rounded-mx-sm border border-line-subtle">
                                                <div className="mx-caption mb-2">Primary Library (Master)</div>
                                                <div className="grid grid-cols-2 gap-2">
                                                    <PillBtn
                                                        active={sel.sync_primary !== 'library_legacy'}
                                                        onClick={() => saveProfile({ sync_primary: 'library_one' })}
                                                    >Newer</PillBtn>
                                                    <PillBtn
                                                        active={sel.sync_primary === 'library_legacy'}
                                                        onClick={() => saveProfile({ sync_primary: 'library_legacy' })}
                                                    >Legacy</PillBtn>
                                                </div>
                                            </div>
                                        )}

                                        <div className="border-t border-line-subtle mt-3 pt-3">
                                            <div className="mx-caption mb-2">Target Libraries</div>
                                            <Toggle
                                                label="Library One"
                                                sub="Newer (CDJ-3000 / rx3)"
                                                checked={(sel.library_types || ['library_legacy']).includes('library_one')}
                                                onChange={(v) => {
                                                    const cur = sel.library_types || ['library_legacy'];
                                                    saveProfile({ library_types: v ? [...new Set([...cur, 'library_one'])] : cur.filter(t => t !== 'library_one') });
                                                }}
                                            />
                                            <Toggle
                                                label="Library Legacy"
                                                sub="Older (CDJ-2000 / Nexus)"
                                                checked={(sel.library_types || ['library_legacy']).includes('library_legacy')}
                                                onChange={(v) => {
                                                    const cur = sel.library_types || ['library_legacy'];
                                                    saveProfile({ library_types: v ? [...new Set([...cur, 'library_legacy'])] : cur.filter(t => t !== 'library_legacy') });
                                                }}
                                            />
                                        </div>
                                    </div>

                                    {/* Danger zone */}
                                    <div className="mx-card p-4" style={{ borderColor: 'rgba(232, 92, 74, 0.20)' }}>
                                        <div className="mx-caption mb-3" style={{ color: 'var(--bad)' }}>Danger Zone</div>
                                        <button
                                            onClick={resetUsb}
                                            disabled={!isConnected(sel)}
                                            className="flex items-center gap-2 px-3 py-2 bg-bad/10 hover:bg-bad/20 text-bad rounded-mx-sm text-tiny font-semibold border border-bad/30 transition-all disabled:opacity-30"
                                        >
                                            <Trash2 size={12} /> Reset USB
                                        </button>
                                    </div>

                                    {/* Library contents */}
                                    <div className="mx-card overflow-hidden">
                                        <div className="flex items-center justify-between px-4 py-3 border-b border-line-subtle">
                                            <div className="flex items-center gap-2">
                                                <Database size={12} className="text-amber2" />
                                                <span className="mx-caption">USB Library Contents</span>
                                            </div>
                                            <div className="flex gap-1 bg-mx-input p-0.5 rounded-mx-sm border border-line-subtle">
                                                <PillTab
                                                    active={activeLibrary === 'library_one'}
                                                    onClick={() => setActiveLibrary('library_one')}
                                                >One</PillTab>
                                                <PillTab
                                                    active={activeLibrary === 'library_legacy'}
                                                    onClick={() => setActiveLibrary('library_legacy')}
                                                >Legacy</PillTab>
                                            </div>
                                        </div>
                                        <div className="max-h-[500px] overflow-y-auto">
                                            {loadingContents ? (
                                                <div className="p-12 flex flex-col items-center gap-3 text-ink-muted text-tiny">
                                                    <Loader2 size={20} className="animate-spin text-amber2" />
                                                    Reading USB database…
                                                </div>
                                            ) : (usbTracks[activeLibrary] || []).length === 0 ? (
                                                <div className="p-12 flex flex-col items-center gap-2 text-ink-placeholder text-center">
                                                    <Music size={28} strokeWidth={1.2} />
                                                    <p className="text-tiny">No tracks in {activeLibrary === 'library_one' ? 'Newer' : 'Legacy'} format</p>
                                                    <p className="text-[10px]">Run sync to populate</p>
                                                </div>
                                            ) : (
                                                <div className="py-1">
                                                    {(usbTracks[activeLibrary] || []).map((item, i) => (
                                                        <UsbLibraryTree key={i} item={item} />
                                                    ))}
                                                </div>
                                            )}
                                        </div>
                                    </div>

                                    {/* Stats footer */}
                                    <div className="flex items-center gap-3 text-[10px] text-ink-placeholder font-mono px-1">
                                        <span>RB DB: {sel.has_export_db ? '✓' : '✗'}</span>
                                        <span>·</span>
                                        <span>Legacy PDB: {sel.has_legacy_pdb ? '✓' : '✗'}</span>
                                        <span>·</span>
                                        <span className="truncate">{sel.device_id}</span>
                                    </div>
                                </>
                            )}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

// ────────────────────────────────────────────────────────────────────
//  SMALL HELPERS
// ────────────────────────────────────────────────────────────────────

const Row = ({ label, value, color, muted }) => (
    <div className="flex justify-between">
        <span className="text-ink-secondary">{label}</span>
        <span className={muted ? 'text-ink-muted' : color === 'ok' ? 'text-ok' : color === 'bad' ? 'text-bad' : 'text-amber2'}>
            {value}
        </span>
    </div>
);

const Toggle = ({ label, sub, checked, onChange }) => (
    <label className="flex items-center justify-between p-2 rounded-mx-sm hover:bg-mx-hover cursor-pointer transition-all">
        <div className="flex flex-col">
            <span className="text-[12px] text-ink-primary">{label}</span>
            {sub && <span className="text-[10px] text-ink-muted">{sub}</span>}
        </div>
        <input
            type="checkbox"
            checked={checked}
            onChange={(e) => onChange(e.target.checked)}
            className="accent-amber2 w-4 h-4"
        />
    </label>
);

const PillBtn = ({ active, onClick, children }) => (
    <button
        onClick={onClick}
        className={`py-1.5 text-[11px] font-medium rounded-mx-sm border transition-all ${
            active ? 'bg-amber2/10 border-amber2/50 text-amber2' : 'border-line-subtle text-ink-muted hover:bg-mx-hover'
        }`}
    >
        {children}
    </button>
);

const PillTab = ({ active, onClick, children }) => (
    <button
        onClick={onClick}
        className={`px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider rounded-mx-xs transition-all ${
            active ? 'bg-amber2 text-mx-deepest' : 'text-ink-muted hover:text-ink-primary'
        }`}
    >
        {children}
    </button>
);

export default UsbView;
