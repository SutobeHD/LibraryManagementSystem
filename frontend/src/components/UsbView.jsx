/**
 * UsbView — Melodex-styled USB device manager (container).
 *
 * Owns: device-selection state, sync settings, API polling, modals.
 * Renders: layout (left list + right panel + bottom controls). Each
 * panel lives in `./usb/*.jsx` and is fed data + callbacks via props.
 *
 * Compatibility / classification / format-wizard / play-count-sync /
 * metadata-sync logic moved into:
 *   • ./usb/UsbControls.jsx       — shared helpers + compat tables
 *   • ./usb/UsbDeviceList.jsx     — left rail
 *   • ./usb/UsbSyncPanel.jsx      — right-pane top half + tail blocks
 *   • ./usb/UsbProfileEditor.jsx  — playlist picker + USB-library viewer
 *   • ./usb/UsbFormatWizard.jsx   — FAT32 / exFAT re-format modal
 *   • ./usb/MetadataSyncPanel.jsx — collapsible metadata sync
 *   • ./usb/PlayCountSync.jsx     — collapsible playcount diff
 */
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
    HardDrive, RefreshCw, ArrowUpDown,
} from 'lucide-react';
import api from '../api/api';
import toast from 'react-hot-toast';
import { confirmModal } from './ConfirmModal';
import { promptModal } from './PromptModal';

import { getDescendantIds } from './usb/UsbControls';
import UsbDeviceList from './usb/UsbDeviceList';
import UsbSyncPanel, { UsbSyncControlsTail, UsbSettingsTail, UsbStatsFooter } from './usb/UsbSyncPanel';
import UsbProfileEditor from './usb/UsbProfileEditor';
import UsbFormatWizard from './usb/UsbFormatWizard';
import MetadataSyncPanel from './usb/MetadataSyncPanel';
import PlayCountSync from './usb/PlayCountSync';

const UsbView = () => {
    const [devices, setDevices] = useState([]);
    const [profiles, setProfiles] = useState([]);
    const [selectedDeviceId, setSelectedDeviceId] = useState(null);
    const [scanning, setScanning] = useState(false);
    const [syncing, setSyncing] = useState(null);
    const [syncProgress, setSyncProgress] = useState(null);
    const [diff, setDiff] = useState(null);
    const [playlistTree, setPlaylistTree] = useState([]);
    const [hiddenCount, setHiddenCount] = useState(0);
    // sync_type wird jetzt aus USB-Typ + Kontext abgeleitet — kein separater State mehr.
    // Mapping: SetStick → 'playlists', alles andere → 'collection'.
    // Rationale: Doppelte Auswahl (Target Ecosystem + Sync-Type) verwirrt — Target legt Inhalt fest.

    // Contents viewer
    const [activeLibrary, setActiveLibrary] = useState('library_legacy');
    const [usbTracks, setUsbTracks] = useState({ library_one: [], library_legacy: [] });
    const [loadingContents, setLoadingContents] = useState(false);

    // Format wizard — null | {preview, fs, label, ack, typed, busy}
    const [formatModal, setFormatModal] = useState(null);

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
            const allDrives = devRes.data;
            const filtered = allDrives.filter(d =>
                d.is_removable !== false &&
                d.drive_type !== 'fixed' &&
                !['C:\\', 'C:/', 'C:'].includes(d.drive)
            );
            setHiddenCount(allDrives.length - filtered.length);
            setDevices(filtered);
            setProfiles(profRes.data);
            if (!selectedDeviceId && filtered.length > 0) {
                setSelectedDeviceId(filtered[0].device_id);
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
        if (!(await confirmModal({
            title: 'Delete device profile?',
            message: 'Delete this device profile? This cannot be undone.',
            confirmLabel: 'Delete',
            danger: true,
        }))) return;
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
        // Always playlist-scoped: only checked playlists are pushed to USB.
        // Both Pioneer formats (exportLibrary.db + export.pdb) + rekordbox.xml
        // are written. User selects playlists via the sidebar tree → toggle.
        const playlistIds = sel.sync_playlists || [];
        if (playlistIds.length === 0) {
            toast.error('Select at least one playlist to sync');
            return;
        }
        setSyncing(sel.device_id);
        setSyncProgress({ stage: 'starting', message: 'Preparing…', progress: 0 });
        try {
            const res = await api.post('/api/usb/sync', {
                device_id: sel.device_id,
                sync_type: 'playlists',
                playlist_ids: playlistIds,
                // Always export both formats — Rekordbox auto-detects via
                // exportLibrary.db, older CDJs / manual import use rekordbox.xml.
                library_types: ['library_one', 'library_legacy'],
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
        if (!(await confirmModal({
            title: 'Eject drive',
            message: `Safely eject ${sel.drive}?`,
            confirmLabel: 'Eject',
        }))) return;
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
        if (!(await confirmModal({
            title: 'Reset USB?',
            message: 'This will DELETE all Rekordbox data on this USB. Continue?',
            confirmLabel: 'Delete data',
            danger: true,
        }))) return;
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
        const newLabel = await promptModal({
            title: 'Rename USB drive',
            message: 'Enter new name for USB drive:',
            defaultValue: sel.label,
        });
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

    // ── FAT32 / exFAT format wizard ───────────────────────────────────────────
    // Two-step protocol enforced by the backend (POST /api/usb/format/preview
    // → POST /api/usb/format/confirm). The UI mirrors that with a modal that
    // requires (a) reading the warning + drive details, (b) ticking the
    // acknowledgement checkbox, and (c) typing the literal `FORMAT <DRIVE>`.
    const openFormatWizard = useCallback(async () => {
        if (!sel?.drive) return;
        try {
            const res = await api.post('/api/usb/format/preview', { drive: sel.drive });
            setFormatModal({
                preview: res.data,
                fs: 'FAT32',
                label: (res.data.label || 'CDJ').slice(0, 11),
                ack: false,
                typed: '',
                busy: false,
            });
        } catch (err) {
            toast.error(err?.response?.data?.detail || 'Could not read drive info');
        }
    }, [sel]);

    const closeFormatWizard = useCallback(() => setFormatModal(null), []);

    const submitFormat = useCallback(async () => {
        if (!formatModal) return;
        const { preview, fs, label, ack, typed } = formatModal;
        if (!ack) { toast.error('Please confirm you understand the data will be erased.'); return; }
        if (typed.trim() !== preview.confirm_phrase) {
            toast.error(`Type exactly: ${preview.confirm_phrase}`);
            return;
        }
        setFormatModal(m => ({ ...m, busy: true }));
        try {
            const res = await api.post('/api/usb/format/confirm', {
                drive: preview.drive,
                token: preview.token,
                filesystem: fs,
                label: label || 'CDJ',
                typed_confirmation: typed.trim(),
            });
            toast.success(res.data?.message || 'Drive formatted.');
            setFormatModal(null);
            setTimeout(scanDevices, 1500);
        } catch (err) {
            toast.error(err?.response?.data?.detail || 'Format failed');
            setFormatModal(m => m && { ...m, busy: false });
        }
    }, [formatModal, scanDevices]);

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
                <UsbDeviceList
                    devices={devices}
                    allDevices={allDevices}
                    selectedDeviceId={selectedDeviceId}
                    scanning={scanning}
                    syncing={syncing}
                    hiddenCount={hiddenCount}
                    isConnected={isConnected}
                    onSelect={(id) => { setSelectedDeviceId(id); setDiff(null); }}
                />

                {/* Detail */}
                <div className="flex-1 overflow-y-auto p-6">
                    {!sel ? (
                        <div className="flex flex-col items-center justify-center h-full text-center">
                            <HardDrive size={40} className="text-ink-placeholder mb-3" />
                            <p className="text-ink-muted text-[13px]">Select a device from the list</p>
                        </div>
                    ) : (
                        <div className="space-y-5 max-w-3xl">
                            {/* Top half: header + compat + sync source + target */}
                            <UsbSyncPanel
                                sel={sel}
                                isConnected={isConnected(sel)}
                                diff={diff}
                                syncing={syncing}
                                syncProgress={syncProgress}
                                onRename={handleRename}
                                onEject={ejectDrive}
                                onInitLibrary={initLibrary}
                                onSaveProfile={saveProfile}
                            />

                            {sel.is_rekordbox && (
                                <>
                                    {/* Playlist picker (placed before sync controls so the user
                                        sees what's getting sent before they hit "Sync Now"). */}
                                    <div className="mx-card p-4">
                                        <div className="flex items-center justify-between mb-3">
                                            <span className="mx-caption">Select Playlists</span>
                                            <span className="text-[10px] font-mono text-amber2">
                                                {(sel.sync_playlists || []).length} selected
                                            </span>
                                        </div>
                                        <div className="max-h-64 overflow-y-auto pr-1 -mx-1">
                                            <UsbProfileEditor
                                                playlistTree={playlistTree}
                                                selectedPlaylistIds={sel.sync_playlists || []}
                                                onTogglePlaylist={togglePlaylist}
                                                usbTracks={usbTracks}
                                                activeLibrary={activeLibrary}
                                                setActiveLibrary={setActiveLibrary}
                                                loadingContents={loadingContents}
                                                renderTreeOnly
                                            />
                                        </div>
                                    </div>

                                    {/* Sync controls */}
                                    <UsbSyncControlsTail
                                        sel={sel}
                                        isConnected={isConnected(sel)}
                                        diff={diff}
                                        syncing={syncing}
                                        syncProgress={syncProgress}
                                        onSaveProfile={saveProfile}
                                        onLoadDiff={loadDiff}
                                        onRunSync={runSync}
                                    />

                                    {/* Metadata Sync — combined play count + full metadata sync */}
                                    {isConnected(sel) && (
                                        <>
                                            <PlayCountSync
                                                usbRoot={sel.path || sel.mount_point || ''}
                                                usbXmlPath={
                                                    sel.rekordbox_xml_path ||
                                                    ((sel.path || sel.mount_point || '') + '/PIONEER/rekordbox/export.xml')
                                                }
                                            />
                                            <MetadataSyncPanel device={sel} />
                                        </>
                                    )}

                                    {/* Settings + Drive actions + Danger zone */}
                                    <UsbSettingsTail
                                        sel={sel}
                                        isConnected={isConnected(sel)}
                                        onSaveProfile={saveProfile}
                                        onRename={handleRename}
                                        onDeleteProfile={deleteProfile}
                                        onResetUsb={resetUsb}
                                        onOpenFormatWizard={openFormatWizard}
                                    />

                                    {/* USB Library — playlist sidebar + flat track list */}
                                    <UsbProfileEditor
                                        playlistTree={playlistTree}
                                        selectedPlaylistIds={sel.sync_playlists || []}
                                        onTogglePlaylist={togglePlaylist}
                                        usbTracks={usbTracks}
                                        activeLibrary={activeLibrary}
                                        setActiveLibrary={setActiveLibrary}
                                        loadingContents={loadingContents}
                                        renderLibraryOnly
                                    />

                                    {/* Stats footer */}
                                    <UsbStatsFooter sel={sel} />
                                </>
                            )}
                        </div>
                    )}
                </div>
            </div>

            {/* ── Format Wizard Modal ────────────────────────────────────── */}
            {formatModal && (
                <UsbFormatWizard
                    state={formatModal}
                    onChange={(patch) => setFormatModal(m => m && { ...m, ...patch })}
                    onClose={closeFormatWizard}
                    onSubmit={submitFormat}
                />
            )}
        </div>
    );
};

export default UsbView;
