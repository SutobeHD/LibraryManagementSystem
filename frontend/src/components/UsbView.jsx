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
    ShieldCheck, ShieldAlert, Info, Eraser,
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

/**
 * USB-Library panel — renders the stick like a normal music library:
 *   sidebar = playlist tree (parsed from PIONEER/rekordbox.xml <PLAYLISTS>)
 *   main    = flat track table (filterable)
 *
 * Falls back gracefully when the stick has tracks but no playlist tree
 * (e.g. exportLibrary.db that we couldn't decrypt) — then it's just the
 * flat track table.
 */
const UsbLibraryPanel = ({ usbTracks, activeLibrary, setActiveLibrary, loadingContents }) => {
    const [selectedPlaylist, setSelectedPlaylist] = React.useState(null);
    const [search, setSearch] = React.useState('');

    const flatKey = activeLibrary === 'library_one' ? 'library_one_flat' : 'library_legacy_flat';
    const allTracks = usbTracks[flatKey] || [];
    const playlists = activeLibrary === 'library_legacy' ? (usbTracks.library_legacy_playlists || []) : [];

    // Build minimal id-set from selected playlist (track_keys point at TrackID)
    const filteredTracks = React.useMemo(() => {
        let list = allTracks;
        if (selectedPlaylist) {
            const keep = new Set((selectedPlaylist.track_keys || []).map(String));
            list = list.filter(t => keep.has(String(t.ID)));
        }
        if (search) {
            const q = search.toLowerCase();
            list = list.filter(t =>
                (t.Title || '').toLowerCase().includes(q) ||
                (t.ArtistName || '').toLowerCase().includes(q) ||
                (t.Album || '').toLowerCase().includes(q)
            );
        }
        return list;
    }, [allTracks, selectedPlaylist, search]);

    // Tree structure: type "0" = folder, "1" = playlist, "4" = smart
    const playlistTree = React.useMemo(() => {
        // Flatten parent strings into a 2-level grouped list (folder → playlists).
        const folders = playlists.filter(p => p.type === '0');
        const leaves = playlists.filter(p => p.type !== '0');
        const tree = [
            ...folders.map(f => ({
                ...f,
                children: leaves.filter(l => l.parent === f.name),
            })),
            // Top-level playlists (parent="ROOT" or no matching folder)
            ...leaves.filter(l => l.parent === 'ROOT' || !folders.find(f => f.name === l.parent)),
        ];
        return tree;
    }, [playlists]);

    const formatBPM = (b) => b ? (b / 100).toFixed(1) : '—';
    const formatDur = (sec) => {
        if (!sec) return '—';
        const m = Math.floor(sec / 60), s = sec % 60;
        return `${m}:${String(s).padStart(2, '0')}`;
    };

    return (
        <div className="mx-card overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3 border-b border-line-subtle">
                <div className="flex items-center gap-2">
                    <Database size={12} className="text-amber2" />
                    <span className="mx-caption">USB Library</span>
                    <span className="text-[10px] text-ink-muted font-mono">
                        · {allTracks.length} tracks{playlists.length ? ` · ${playlists.length} playlists` : ''}
                    </span>
                </div>
                <div className="flex gap-2 items-center">
                    <input
                        value={search}
                        onChange={e => setSearch(e.target.value)}
                        placeholder="Suchen…"
                        className="px-2 py-1 bg-mx-input border border-line-subtle rounded text-tiny w-40"
                    />
                    <div className="flex gap-1 bg-mx-input p-0.5 rounded-mx-sm border border-line-subtle">
                        <PillTab active={activeLibrary === 'library_one'} onClick={() => { setActiveLibrary('library_one'); setSelectedPlaylist(null); }}>One</PillTab>
                        <PillTab active={activeLibrary === 'library_legacy'} onClick={() => { setActiveLibrary('library_legacy'); setSelectedPlaylist(null); }}>Legacy</PillTab>
                    </div>
                </div>
            </div>

            {loadingContents ? (
                <div className="p-12 flex flex-col items-center gap-3 text-ink-muted text-tiny">
                    <Loader2 size={20} className="animate-spin text-amber2" />
                    Reading USB database…
                </div>
            ) : allTracks.length === 0 ? (
                <div className="p-12 flex flex-col items-center gap-2 text-ink-placeholder text-center">
                    <Music size={28} strokeWidth={1.2} />
                    <p className="text-tiny">No tracks in {activeLibrary === 'library_one' ? 'Newer' : 'Legacy'} format</p>
                    <p className="text-[10px]">Run sync to populate</p>
                </div>
            ) : (
                <div className="flex" style={{ maxHeight: 500 }}>
                    {/* Playlist sidebar */}
                    {activeLibrary === 'library_legacy' && playlists.length > 0 && (
                        <div className="w-56 border-r border-line-subtle overflow-y-auto py-1 shrink-0">
                            <button
                                onClick={() => setSelectedPlaylist(null)}
                                className={`w-full text-left flex items-center gap-2 px-3 py-1.5 transition-colors ${
                                    !selectedPlaylist ? 'bg-amber2/10 text-amber2' : 'text-ink-secondary hover:bg-white/5'
                                }`}
                            >
                                <Database size={11} />
                                <span className="text-[11px] font-semibold flex-1">All Tracks</span>
                                <span className="text-[10px] text-ink-muted font-mono">{allTracks.length}</span>
                            </button>
                            {playlistTree.map((node, i) => (
                                <UsbPlaylistTreeNode
                                    key={i}
                                    node={node}
                                    selected={selectedPlaylist?.name === node.name}
                                    onSelect={setSelectedPlaylist}
                                    selectedName={selectedPlaylist?.name}
                                />
                            ))}
                        </div>
                    )}

                    {/* Track list */}
                    <div className="flex-1 overflow-y-auto">
                        <table className="w-full text-tiny">
                            <thead className="sticky top-0 bg-mx-shell border-b border-line-subtle">
                                <tr className="text-ink-muted text-[10px] uppercase tracking-wider">
                                    <th className="text-left px-3 py-2 font-semibold">Title</th>
                                    <th className="text-left px-3 py-2 font-semibold">Artist</th>
                                    <th className="text-left px-3 py-2 font-semibold">Album</th>
                                    <th className="text-center px-2 py-2 font-semibold w-14">BPM</th>
                                    <th className="text-center px-2 py-2 font-semibold w-12">Key</th>
                                    <th className="text-right px-3 py-2 font-semibold w-14">Time</th>
                                </tr>
                            </thead>
                            <tbody>
                                {filteredTracks.map((t, i) => (
                                    <tr key={i} className="border-b border-line-subtle/30 hover:bg-mx-hover transition-colors">
                                        <td className="px-3 py-1.5 text-ink-primary truncate max-w-[280px]" title={t.Title}>{t.Title || '—'}</td>
                                        <td className="px-3 py-1.5 text-ink-secondary truncate max-w-[200px]">{t.ArtistName || '—'}</td>
                                        <td className="px-3 py-1.5 text-ink-muted truncate max-w-[180px]">{t.Album || '—'}</td>
                                        <td className="px-2 py-1.5 text-center font-mono text-amber2">{formatBPM(t.BPM)}</td>
                                        <td className="px-2 py-1.5 text-center font-mono text-blue-300">{t.Key || '—'}</td>
                                        <td className="px-3 py-1.5 text-right text-ink-muted font-mono">{formatDur(t.TotalTime)}</td>
                                    </tr>
                                ))}
                                {filteredTracks.length === 0 && (
                                    <tr><td colSpan={6} className="px-3 py-8 text-center text-ink-placeholder text-[11px]">
                                        Keine Tracks {selectedPlaylist ? `in "${selectedPlaylist.name}"` : ''}{search ? ` für "${search}"` : ''}
                                    </td></tr>
                                )}
                            </tbody>
                        </table>
                    </div>
                </div>
            )}
        </div>
    );
};

const UsbPlaylistTreeNode = ({ node, onSelect, selectedName }) => {
    const [open, setOpen] = React.useState(true);
    const isFolder = node.type === '0';
    const isSelected = selectedName === node.name;
    return (
        <div>
            <button
                onClick={() => isFolder ? setOpen(o => !o) : onSelect(node)}
                className={`w-full text-left flex items-center gap-2 px-3 py-1 transition-colors ${
                    isSelected ? 'bg-amber2/15 text-amber2' : 'text-ink-secondary hover:bg-white/5'
                }`}
                title={node.name}
            >
                {isFolder ? (
                    open ? <ChevronDown size={10} className="text-amber-500/60" /> : <ChevronRight size={10} className="text-amber-500/60" />
                ) : (
                    <ListMusic size={10} className="text-amber2/50" />
                )}
                <span className="text-[11px] flex-1 truncate">{node.name}</span>
                {!isFolder && (
                    <span className="text-[10px] text-ink-muted font-mono">{(node.track_keys || []).length}</span>
                )}
            </button>
            {isFolder && open && (node.children || []).map((c, i) => (
                <div key={i} style={{ paddingLeft: 12 }}>
                    <UsbPlaylistTreeNode node={c} onSelect={onSelect} selectedName={selectedName} />
                </div>
            ))}
        </div>
    );
};

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

    const usedColor = usedPct > 95 ? 'var(--bad)' : usedPct > 80 ? 'var(--amber)' : '#2DD4BF';

    return (
        <div className="space-y-2">
            <div className="flex items-center justify-between text-[10px]">
                <span className="mx-caption">Storage</span>
                <span className="font-mono text-ink-secondary">
                    {formatBytes(afterFree > 0 ? afterFree : 0)} free after sync
                </span>
            </div>
            <div className="w-full h-2.5 bg-mx-input rounded-full overflow-hidden flex border border-line-subtle">
                <div
                    className="h-full transition-all"
                    style={{ width: `${usedPct}%`, background: usedColor }}
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
                    <span className="w-1.5 h-1.5 rounded-full" style={{ background: usedColor }} /> Used {formatBytes(used)}
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
    // sync_type wird jetzt aus USB-Typ + Kontext abgeleitet — kein separater State mehr.
    // Mapping: SetStick → 'playlists', alles andere → 'collection'.
    // Rationale: Doppelte Auswahl (Target Ecosystem + Sync-Type) verwirrt — Target legt Inhalt fest.

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

    const [hiddenCount, setHiddenCount] = useState(0);

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
        // Sync-Inhalt aus USB-Typ ableiten — keine doppelte Auswahl
        const isPlaylistOnly = sel.type === 'SetStick';
        const sync_type      = isPlaylistOnly ? 'playlists' : 'collection';
        const playlistIds    = isPlaylistOnly ? (sel.sync_playlists || []) : [];
        if (isPlaylistOnly && playlistIds.length === 0) {
            toast.error('Select at least one playlist for the Set Stick');
            return;
        }
        setSyncing(sel.device_id);
        setSyncProgress({ stage: 'starting', message: 'Preparing…', progress: 0 });
        try {
            const res = await api.post('/api/usb/sync', {
                device_id: sel.device_id,
                sync_type,
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

    // ── FAT32 / exFAT format wizard ───────────────────────────────────────────
    // Two-step protocol enforced by the backend (POST /api/usb/format/preview
    // → POST /api/usb/format/confirm). The UI mirrors that with a modal that
    // requires (a) reading the warning + drive details, (b) ticking the
    // acknowledgement checkbox, and (c) typing the literal `FORMAT <DRIVE>`.
    const [formatModal, setFormatModal] = useState(null); // null | {preview, fs, label, ack, typed, busy}

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
                <div className="w-72 border-r border-line-subtle overflow-y-auto p-2 space-y-1 bg-mx-shell">
                    <div className="mx-caption px-3 py-2">Devices</div>

                    {allDevices.length === 0 && !scanning && (
                        <div className="flex flex-col items-center justify-center h-48 text-center px-4">
                            <Usb size={32} className="text-ink-placeholder mb-3" />
                            <p className="text-[12px] text-ink-muted">No USB devices detected</p>
                            <p className="text-[10px] text-ink-placeholder mt-1">Insert a USB stick and click Scan</p>
                            {hiddenCount > 0 && (
                                <p className="text-[10px] text-ink-placeholder mt-2">{hiddenCount} system drive(s) hidden</p>
                            )}
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
                                        <div className="text-[11px] font-mono flex items-center gap-1.5 mt-0.5">
                                            <span className="text-ink-primary font-semibold">{device.drive}</span>
                                            <span className="text-ink-placeholder">·</span>
                                            <span className="text-amber2">{fsKey}</span>
                                            <span className="text-ink-placeholder">·</span>
                                            <span className="text-ink-secondary">{device.track_count || 0} tracks</span>
                                        </div>
                                    </div>
                                    {/* Compat status badge */}
                                    {worst === 'partial' && (
                                        <AlertTriangle size={12} className="text-orange-500 shrink-0" title="Wrong format for CDJs — consider reformatting" />
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
                                    <p className="text-[13px] text-ink-secondary font-mono mt-1">
                                        {sel.drive} · <span className="text-teal-400">{normalizeFs(sel.filesystem)}</span> · {formatBytes(sel.total_space)} total · {formatBytes(sel.free_space)} free
                                    </p>
                                </div>
                                <button
                                    onClick={ejectDrive}
                                    disabled={!isConnected(sel)}
                                    className="p-2 hover:bg-amber2/10 text-ink-muted hover:text-amber2 rounded-mx-sm transition-all disabled:opacity-30"
                                    title="Safely eject drive"
                                >
                                    <Power size={16} />
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

                                    {/* Main Sync Source */}
                                    <div className="mx-card p-4">
                                        <div className="mx-caption mb-3">Main Sync Source</div>
                                        <div className="grid grid-cols-2 gap-2">
                                            <button
                                                onClick={() => saveProfile({ sync_direction: 'pc_main' })}
                                                className={`flex items-center gap-2.5 p-3 rounded-mx-sm border transition-all ${
                                                    (sel.sync_direction || 'pc_main') === 'pc_main'
                                                        ? 'bg-amber2/10 border-amber2/50 text-amber2'
                                                        : 'bg-mx-input border-line-subtle text-ink-secondary hover:bg-mx-hover'
                                                }`}
                                            >
                                                <Database size={15} />
                                                <div className="text-[12px] font-medium">PC is Main</div>
                                            </button>
                                            <button
                                                onClick={() => saveProfile({ sync_direction: 'usb_main' })}
                                                className={`flex items-center gap-2.5 p-3 rounded-mx-sm border transition-all ${
                                                    sel.sync_direction === 'usb_main'
                                                        ? 'bg-amber2/10 border-amber2/50 text-amber2'
                                                        : 'bg-mx-input border-line-subtle text-ink-secondary hover:bg-mx-hover'
                                                }`}
                                            >
                                                <Usb size={15} />
                                                <div className="text-[12px] font-medium">USB is Main</div>
                                            </button>
                                        </div>
                                        <p className="text-[10px] text-ink-muted mt-2">
                                            {(sel.sync_direction || 'pc_main') === 'pc_main'
                                                ? 'PC library is the source of truth — USB receives updates.'
                                                : 'USB library is the source of truth — PC receives updates.'}
                                        </p>
                                    </div>

                                    {/* Target Ecosystem */}
                                    <div className="mx-card p-4">
                                        <div className="mx-caption mb-3">Target Ecosystem</div>
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

                                    {/* Playlist selection — ABOVE contents */}
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

                                    {/* Sync controls — vereinfacht: Inhalt ergibt sich aus Target Ecosystem */}
                                    <div className="mx-card p-4">
                                        <div className="flex items-center justify-between mb-3">
                                            <span className="mx-caption">Sync</span>
                                            <span className="text-[10px] text-ink-muted">
                                                {sel.type === 'SetStick'
                                                    ? `${(sel.sync_playlists || []).length} playlists selected`
                                                    : `Full ${USB_TYPES.find(t => t.id === sel.type)?.label || 'collection'}`}
                                            </span>
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

                                        <button
                                            onClick={runSync}
                                            disabled={!!syncing || !isConnected(sel)}
                                            className="btn-primary w-full flex items-center justify-center gap-2 disabled:opacity-30 disabled:cursor-not-allowed"
                                        >
                                            {syncing === sel.device_id
                                                ? <><Loader2 size={14} className="animate-spin" /> Syncing…</>
                                                : <><Download size={14} /> Sync Now</>}
                                        </button>

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
                                                <div className="flex items-center gap-1.5 text-[10px] text-ink-muted font-mono">
                                                    <Clock size={10} />
                                                    <span>Estimated time: calculating…</span>
                                                </div>
                                            </div>
                                        )}
                                    </div>

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
                                            <div className="px-3 py-2 rounded-md bg-mx-input/40 border border-line-subtle text-tiny leading-snug text-ink-muted">
                                                Both formats are written automatically:
                                                <span className="block mt-1 text-ink-secondary">• <strong>exportLibrary.db</strong> — Rekordbox 6/7 + CDJ-3000 auto-detect</span>
                                                <span className="block text-ink-secondary">• <strong>rekordbox.xml</strong> — older Rekordbox / manual import (Preferences → Advanced → Database)</span>
                                            </div>
                                            <div className="mt-2 px-3 py-2 rounded-md bg-amber-500/10 border border-amber-500/30 text-amber-300 text-tiny leading-snug">
                                                <strong>Stick nicht erkannt?</strong> Aktuell ist die OneLibrary-Erstellung
                                                durch einen rbox-Library-Bug eingeschränkt. Workaround:
                                                <span className="block mt-1">In Rekordbox → <strong>Preferences → Advanced → Database</strong> → "rekordbox xml" → File-Picker → die <code className="bg-black/30 px-1 rounded">PIONEER/rekordbox.xml</code> auf dem Stick auswählen → Import.</span>
                                            </div>
                                        </div>
                                    </div>

                                    {/* Danger zone */}
                                    <div className="mx-card p-4" style={{ borderColor: 'rgba(232, 92, 74, 0.20)' }}>
                                        <div className="mx-caption mb-3" style={{ color: 'var(--bad)' }}>Danger Zone</div>
                                        <div className="flex items-center gap-2 flex-wrap">
                                            <button
                                                onClick={handleRename}
                                                className="flex items-center gap-2 px-3 py-2 bg-mx-input hover:bg-mx-hover text-ink-secondary rounded-mx-sm text-tiny font-semibold border border-line-subtle transition-all"
                                            >
                                                <Edit2 size={12} /> Rename Drive
                                            </button>
                                            <button
                                                onClick={() => deleteProfile(sel.device_id)}
                                                className="flex items-center gap-2 px-3 py-2 bg-bad/10 hover:bg-bad/20 text-bad rounded-mx-sm text-tiny font-semibold border border-bad/30 transition-all"
                                            >
                                                <Trash2 size={12} /> Delete Profile
                                            </button>
                                            <button
                                                onClick={resetUsb}
                                                disabled={!isConnected(sel)}
                                                className="flex items-center gap-2 px-3 py-2 bg-bad/10 hover:bg-bad/20 text-bad rounded-mx-sm text-tiny font-semibold border border-bad/30 transition-all disabled:opacity-30"
                                            >
                                                <Trash2 size={12} /> Reset USB
                                            </button>
                                            <button
                                                onClick={openFormatWizard}
                                                disabled={!isConnected(sel)}
                                                title="Wipe & re-format this drive as FAT32 / exFAT for CDJs"
                                                className="flex items-center gap-2 px-3 py-2 bg-bad/15 hover:bg-bad/25 text-bad rounded-mx-sm text-tiny font-bold border border-bad/40 transition-all disabled:opacity-30"
                                            >
                                                <Eraser size={12} /> Format for CDJ…
                                            </button>
                                        </div>
                                    </div>

                                    {/* USB Library — playlist sidebar + flat track list */}
                                    <UsbLibraryPanel
                                        usbTracks={usbTracks}
                                        activeLibrary={activeLibrary}
                                        setActiveLibrary={setActiveLibrary}
                                        loadingContents={loadingContents}
                                    />

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

            {/* ── Format Wizard Modal ────────────────────────────────────── */}
            {formatModal && (
                <FormatWizardModal
                    state={formatModal}
                    onChange={(patch) => setFormatModal(m => m && { ...m, ...patch })}
                    onClose={closeFormatWizard}
                    onSubmit={submitFormat}
                    formatBytes={formatBytes}
                />
            )}
        </div>
    );
};


// ────────────────────────────────────────────────────────────────────
//  FORMAT WIZARD — destructive, double-confirm
// ────────────────────────────────────────────────────────────────────

const FormatWizardModal = ({ state, onChange, onClose, onSubmit, formatBytes }) => {
    const { preview, fs, label, ack, typed, busy } = state;
    const phraseOk = typed.trim() === preview.confirm_phrase;
    const canSubmit = ack && phraseOk && !busy && (label || '').trim().length > 0;

    return (
        <div
            className="fixed inset-0 z-[200] flex items-center justify-center bg-black/70 backdrop-blur-sm"
            onClick={busy ? undefined : onClose}
        >
            <div
                className="w-[560px] max-w-[92vw] bg-mx-deepest border border-bad/40 rounded-2xl shadow-2xl shadow-bad/20 overflow-hidden"
                onClick={(e) => e.stopPropagation()}
            >
                {/* Header */}
                <div className="px-6 py-4 bg-bad/10 border-b border-bad/30 flex items-center gap-3">
                    <div className="p-2 bg-bad/20 rounded-lg border border-bad/40">
                        <AlertTriangle size={20} className="text-bad" />
                    </div>
                    <div>
                        <h2 className="text-[15px] font-bold text-bad">Format USB drive</h2>
                        <p className="text-[11px] text-ink-muted font-mono mt-0.5">DESTRUCTIVE — all data on this drive will be erased</p>
                    </div>
                </div>

                {/* Body */}
                <div className="p-6 space-y-5">
                    {/* What will happen */}
                    <div className="bg-bad/5 border border-bad/20 rounded-xl p-4 space-y-2">
                        <p className="text-[12px] font-semibold text-bad">What will happen</p>
                        <ul className="text-[11px] text-ink-secondary space-y-1 list-disc list-inside">
                            <li>Every file on <span className="font-mono text-bad">{preview.drive}</span> will be permanently deleted.</li>
                            <li>The drive is reformatted as <span className="font-mono text-amber2">{fs}</span> with label <span className="font-mono text-amber2">"{label || 'CDJ'}"</span>.</li>
                            <li>The Pioneer skeleton (<span className="font-mono">/PIONEER/rekordbox</span>) and the <span className="font-mono">DEVICE.PIONEER</span> marker are recreated, so the stick is immediately CDJ-ready.</li>
                            <li>This action cannot be undone. Make a backup first if you have anything valuable on it.</li>
                        </ul>
                    </div>

                    {/* Drive info */}
                    <div className="grid grid-cols-2 gap-3 text-[11px]">
                        <Info_Field label="Drive">{preview.drive}</Info_Field>
                        <Info_Field label="Current label">{preview.label || '(none)'}</Info_Field>
                        <Info_Field label="Current FS">{preview.filesystem}</Info_Field>
                        <Info_Field label="Total size">{formatBytes(preview.total_bytes || 0)}</Info_Field>
                    </div>

                    {/* Choices */}
                    <div className="grid grid-cols-2 gap-3">
                        <div>
                            <label className="text-[10px] uppercase tracking-wide text-ink-muted font-semibold block mb-1">Filesystem</label>
                            <select
                                value={fs}
                                onChange={(e) => onChange({ fs: e.target.value })}
                                disabled={busy}
                                className="input-glass w-full text-[12px]"
                            >
                                <option value="FAT32">FAT32 — CDJ-2000NXS2 + CDJ-3000 (max 4GB/file)</option>
                                <option value="exFAT">exFAT — CDJ-3000 only (no 4GB limit)</option>
                            </select>
                        </div>
                        <div>
                            <label className="text-[10px] uppercase tracking-wide text-ink-muted font-semibold block mb-1">New label (max 11 chars)</label>
                            <input
                                type="text"
                                maxLength={11}
                                value={label}
                                onChange={(e) => onChange({ label: e.target.value.toUpperCase().slice(0, 11) })}
                                disabled={busy}
                                className="input-glass w-full text-[12px] font-mono"
                                placeholder="CDJ"
                            />
                        </div>
                    </div>

                    {/* Confirmations */}
                    <div className="space-y-3">
                        <label className="flex items-start gap-2.5 cursor-pointer p-2 rounded-lg hover:bg-mx-hover/30">
                            <input
                                type="checkbox"
                                checked={ack}
                                onChange={(e) => onChange({ ack: e.target.checked })}
                                disabled={busy}
                                className="mt-0.5 accent-bad w-4 h-4 shrink-0"
                            />
                            <span className="text-[12px] text-ink-primary">
                                I understand that <strong className="text-bad">every file</strong> on <span className="font-mono">{preview.drive}</span> will be permanently lost and that this cannot be undone.
                            </span>
                        </label>
                        <div>
                            <label className="text-[10px] uppercase tracking-wide text-ink-muted font-semibold block mb-1">
                                Type <span className="font-mono text-bad bg-bad/10 px-1.5 py-0.5 rounded">{preview.confirm_phrase}</span> to enable the format button
                            </label>
                            <input
                                type="text"
                                value={typed}
                                onChange={(e) => onChange({ typed: e.target.value })}
                                disabled={busy}
                                placeholder={preview.confirm_phrase}
                                className={`input-glass w-full text-[12px] font-mono ${typed && (phraseOk ? 'border-ok' : 'border-bad')}`}
                                autoFocus
                            />
                        </div>
                    </div>
                </div>

                {/* Footer */}
                <div className="px-6 py-4 bg-mx-shell border-t border-line-subtle flex items-center justify-end gap-3">
                    <button
                        onClick={onClose}
                        disabled={busy}
                        className="px-4 py-2 rounded-lg text-tiny font-semibold border border-line-subtle bg-mx-input hover:bg-mx-hover text-ink-secondary disabled:opacity-30"
                    >
                        Cancel
                    </button>
                    <button
                        onClick={onSubmit}
                        disabled={!canSubmit}
                        className="px-4 py-2 rounded-lg text-tiny font-bold flex items-center gap-2 bg-bad/20 hover:bg-bad/30 text-bad border border-bad/50 disabled:opacity-30 disabled:cursor-not-allowed"
                    >
                        {busy ? <Loader2 size={12} className="animate-spin" /> : <Eraser size={12} />}
                        {busy ? 'Formatting…' : `Format ${preview.drive} now`}
                    </button>
                </div>
            </div>
        </div>
    );
};

const Info_Field = ({ label, children }) => (
    <div className="bg-mx-input border border-line-subtle rounded-lg px-3 py-2">
        <div className="text-[9px] uppercase tracking-wide text-ink-muted font-semibold">{label}</div>
        <div className="text-[12px] font-mono text-ink-primary mt-0.5">{children}</div>
    </div>
);


// ────────────────────────────────────────────────────────────────────
//  PLAY COUNT SYNC
// ────────────────────────────────────────────────────────────────────

/**
 * PlayCountSync — collapsible section inside UsbView.
 *
 * Shows auto-resolved count summary and a conflict table with per-track
 * strategy dropdowns.  Two-step commit: "Review" → "Write Sync".
 *
 * Props:
 *   usbRoot     — root path of the mounted USB drive (e.g. "E:\")
 *   usbXmlPath  — path to the Rekordbox XML on the USB
 */
const PlayCountSync = ({ usbRoot, usbXmlPath }) => {
    const [open, setOpen] = useState(false);
    const [loading, setLoading] = useState(false);
    const [diffData, setDiffData] = useState(null);  // {auto, conflicts, last_sync_ts}
    const [error, setError] = useState(null);
    const [strategies, setStrategies] = useState({});  // {track_id: strategy}
    const [committing, setCommitting] = useState(false);
    const [commitResult, setCommitResult] = useState(null);
    const [confirmStep, setConfirmStep] = useState(0);  // 0=idle 1=confirm 2=confirmed

    const log = (level, msg, data) =>
        console[level]?.(`[PlayCountSync] ${msg}`, data ?? '');

    const fetchDiff = async () => {
        if (!usbRoot || !usbXmlPath) {
            setError('USB root or XML path not set. Select a USB device first.');
            return;
        }
        setLoading(true);
        setError(null);
        setDiffData(null);
        setCommitResult(null);
        setConfirmStep(0);
        log('info', 'fetchDiff', { usbRoot, usbXmlPath });
        try {
            const res = await api.get('/api/usb/playcount/diff', {
                params: { usb_root: usbRoot, usb_xml_path: usbXmlPath },
            });
            if (res.data?.status !== 'ok') throw new Error(res.data?.message || 'Unknown error');
            const data = res.data.data;
            setDiffData(data);
            // Default strategy for every conflict: take_max
            const initStrategies = {};
            (data.conflicts || []).forEach(c => { initStrategies[c.track_id] = 'take_max'; });
            setStrategies(initStrategies);
            log('info', 'diff loaded', { auto: data.auto?.length, conflicts: data.conflicts?.length });
        } catch (e) {
            log('error', 'fetchDiff failed', e);
            setError(e.message || 'Failed to load diff');
        } finally {
            setLoading(false);
        }
    };

    const setAllMax = () => {
        const next = {};
        (diffData?.conflicts || []).forEach(c => { next[c.track_id] = 'take_max'; });
        setStrategies(next);
    };

    const handleCommit = async () => {
        if (confirmStep === 0) { setConfirmStep(1); return; }
        if (confirmStep === 1) { setConfirmStep(2); return; }

        // Step 2 — actually commit
        setCommitting(true);
        setError(null);
        log('info', 'committing resolutions');
        try {
            const resolutions = (diffData?.conflicts || []).map(c => ({
                track_id: c.track_id,
                strategy: strategies[c.track_id] || 'take_max',
                pc_count: c.pc_count,
                usb_count: c.usb_count,
                pc_last_played: c.pc_last_played,
                usb_last_played: c.usb_last_played,
            }));
            const res = await api.post('/api/usb/playcount/resolve', {
                resolutions,
                usb_root: usbRoot,
                usb_xml_path: usbXmlPath,
            });
            if (res.data?.status !== 'ok') throw new Error(res.data?.message || 'Commit failed');
            setCommitResult(res.data.data);
            setConfirmStep(0);
            log('info', 'commit result', res.data.data);
        } catch (e) {
            log('error', 'commit failed', e);
            setError(e.message || 'Commit failed');
            setConfirmStep(0);
        } finally {
            setCommitting(false);
        }
    };

    const formatTs = (ts) => {
        if (!ts || ts === 0) return 'Never';
        return new Date(ts * 1000).toLocaleDateString();
    };

    return (
        <div className="mx-card rounded-mx-md mt-4">
            {/* Header toggle */}
            <button
                className="w-full flex items-center justify-between px-4 py-3 hover:bg-mx-hover rounded-mx-md transition-colors"
                onClick={() => setOpen(o => !o)}
                aria-expanded={open}
            >
                <div className="flex items-center gap-2">
                    <ArrowUpDown size={14} className="text-amber2" />
                    <span className="text-[12px] font-semibold text-ink-primary">Play Count Sync</span>
                </div>
                {open ? <ChevronDown size={14} className="text-ink-muted" /> : <ChevronRight size={14} className="text-ink-muted" />}
            </button>

            {open && (
                <div className="px-4 pb-4 border-t border-line-subtle pt-3 space-y-3">
                    {/* Controls row */}
                    <div className="flex items-center gap-2">
                        <button
                            onClick={fetchDiff}
                            disabled={loading}
                            className="btn-primary text-[11px] py-1.5 px-3 flex items-center gap-1.5"
                        >
                            {loading ? <Loader2 size={11} className="animate-spin" /> : <RefreshCw size={11} />}
                            Analyse Counts
                        </button>
                        {diffData?.last_sync_ts !== undefined && (
                            <span className="text-[10px] text-ink-muted font-mono">
                                Last sync: {formatTs(diffData.last_sync_ts)}
                            </span>
                        )}
                    </div>

                    {/* Error */}
                    {error && (
                        <div className="text-bad text-[11px] bg-bad/5 border border-bad/20 rounded-mx-sm px-3 py-2 flex items-center gap-2">
                            <AlertTriangle size={12} /> {error}
                        </div>
                    )}

                    {/* Commit result */}
                    {commitResult && (
                        <div className="text-ok text-[11px] bg-ok/5 border border-ok/20 rounded-mx-sm px-3 py-2">
                            Sync written — {commitResult.committed} track(s) updated.
                            {(commitResult.errors || []).length > 0 && (
                                <span className="text-amber2 ml-2">{commitResult.errors.length} warning(s)</span>
                            )}
                        </div>
                    )}

                    {diffData && (
                        <>
                            {/* Auto-resolved summary */}
                            <div className="flex items-center gap-4 text-[11px] font-mono">
                                <span className="text-ink-secondary">
                                    Auto: <span className="text-ok font-semibold">{(diffData.auto || []).length}</span>
                                </span>
                                <span className="text-ink-secondary">
                                    Conflicts: <span className={diffData.conflicts?.length > 0 ? 'text-amber2 font-semibold' : 'text-ok font-semibold'}>
                                        {(diffData.conflicts || []).length}
                                    </span>
                                </span>
                            </div>

                            {/* Conflict table */}
                            {(diffData.conflicts || []).length > 0 && (
                                <div className="space-y-2">
                                    <div className="flex items-center justify-between">
                                        <span className="text-[10px] uppercase tracking-wider text-ink-muted font-semibold">Conflicts</span>
                                        <button
                                            onClick={setAllMax}
                                            className="text-[10px] text-amber2 hover:underline"
                                        >
                                            Set All to MAX
                                        </button>
                                    </div>

                                    <div className="border border-line-subtle rounded-mx-sm overflow-hidden">
                                        {/* Table header */}
                                        <div className="grid grid-cols-[1fr_72px_72px_120px] gap-1 px-3 py-1.5 bg-mx-base text-[10px] text-ink-muted font-semibold uppercase tracking-wider border-b border-line-subtle">
                                            <span>Track</span>
                                            <span className="text-right">PC</span>
                                            <span className="text-right">USB</span>
                                            <span className="text-center">Strategy</span>
                                        </div>
                                        {/* Rows */}
                                        <div className="max-h-56 overflow-y-auto divide-y divide-line-subtle">
                                            {diffData.conflicts.map(c => (
                                                <div
                                                    key={c.track_id}
                                                    className="grid grid-cols-[1fr_72px_72px_120px] gap-1 px-3 py-2 items-center hover:bg-mx-hover"
                                                >
                                                    <div className="min-w-0">
                                                        <p className="text-[11px] text-ink-primary truncate">{c.title || c.track_id}</p>
                                                        {c.artist && <p className="text-[10px] text-ink-muted truncate">{c.artist}</p>}
                                                    </div>
                                                    <span className="text-right text-[11px] font-mono text-info">{c.pc_count}</span>
                                                    <span className="text-right text-[11px] font-mono text-amber2">{c.usb_count}</span>
                                                    <select
                                                        value={strategies[c.track_id] || 'take_max'}
                                                        onChange={e => setStrategies(s => ({ ...s, [c.track_id]: e.target.value }))}
                                                        className="input-glass text-[10px] py-0.5 px-1.5 rounded-mx-xs"
                                                    >
                                                        <option value="take_max">Take MAX</option>
                                                        <option value="take_pc">Take PC</option>
                                                        <option value="take_usb">Take USB</option>
                                                        <option value="sum">Sum Both</option>
                                                    </select>
                                                </div>
                                            ))}
                                        </div>
                                    </div>

                                    {/* Commit button — double-confirm */}
                                    <div className="flex items-center gap-2 pt-1">
                                        {confirmStep === 0 && (
                                            <button onClick={handleCommit} className="btn-secondary text-[11px] py-1.5 px-3">
                                                Write Sync
                                            </button>
                                        )}
                                        {confirmStep === 1 && (
                                            <>
                                                <span className="text-amber2 text-[11px]">This will modify both PC DB and USB XML.</span>
                                                <button onClick={handleCommit} className="btn-secondary text-[11px] py-1.5 px-3">
                                                    Confirm
                                                </button>
                                                <button onClick={() => setConfirmStep(0)} className="text-[10px] text-ink-muted hover:text-ink-secondary">
                                                    Cancel
                                                </button>
                                            </>
                                        )}
                                        {confirmStep === 2 && (
                                            <>
                                                <span className="text-bad text-[11px] font-semibold">Last chance — this cannot be undone.</span>
                                                <button onClick={handleCommit} disabled={committing} className="btn-primary text-[11px] py-1.5 px-3 flex items-center gap-1.5">
                                                    {committing ? <Loader2 size={11} className="animate-spin" /> : null}
                                                    Write Now
                                                </button>
                                                <button onClick={() => setConfirmStep(0)} className="text-[10px] text-ink-muted hover:text-ink-secondary">
                                                    Cancel
                                                </button>
                                            </>
                                        )}
                                    </div>
                                </div>
                            )}

                            {(diffData.conflicts || []).length === 0 && (
                                <p className="text-ok text-[11px]">No conflicts — all play counts auto-resolved.</p>
                            )}
                        </>
                    )}
                </div>
            )}
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

// ────────────────────────────────────────────────────────────────────
//  METADATA SYNC PANEL (inline, device-aware)
// ────────────────────────────────────────────────────────────────────

const METADATA_CATEGORIES = [
    { id: 'play_counts', label: 'Play Counts', desc: 'Play count and last played date' },
    { id: 'ratings', label: 'Ratings', desc: 'Star ratings (0-5)' },
    { id: 'tags', label: 'Tags & Comments', desc: 'Comment field and custom tags' },
    { id: 'color', label: 'Color Labels', desc: 'Track color assignments' },
    { id: 'hot_cues', label: 'Hot Cues', desc: 'Hot cue points (A-H)' },
    { id: 'memory_cues', label: 'Memory Cues', desc: 'Memory cue and loop points' },
    { id: 'beat_grids', label: 'Beat Grids', desc: 'Beat grid and BPM data' },
];

const MetadataSyncPanel = ({ device }) => {
    const [open, setOpen] = useState(false);
    const [syncMode, setSyncMode] = useState('smart');
    const [mainSource, setMainSource] = useState('pc');
    const [categories, setCategories] = useState(
        METADATA_CATEGORIES.reduce((acc, c) => ({ ...acc, [c.id]: true }), {})
    );

    const toggleCategory = (id) => {
        setCategories(prev => ({ ...prev, [id]: !prev[id] }));
    };

    return (
        <div className="mx-card rounded-mx-md">
            <button
                className="w-full flex items-center justify-between px-4 py-3 hover:bg-mx-hover rounded-mx-md transition-colors"
                onClick={() => setOpen(o => !o)}
            >
                <div className="flex items-center gap-2">
                    <ArrowUpDown size={14} className="text-teal-400" />
                    <span className="text-[12px] font-semibold text-ink-primary">Metadata Sync</span>
                </div>
                {open ? <ChevronDown size={14} className="text-ink-muted" /> : <ChevronRight size={14} className="text-ink-muted" />}
            </button>

            {open && (
                <div className="px-4 pb-4 border-t border-line-subtle pt-3 space-y-3">
                    {/* Sync Mode */}
                    <div className="grid grid-cols-2 gap-2">
                        <button
                            onClick={() => setSyncMode('smart')}
                            className={`flex items-center gap-2 p-2.5 rounded-mx-sm border transition-all text-left ${
                                syncMode === 'smart'
                                    ? 'bg-amber2/10 border-amber2/50 text-amber2'
                                    : 'bg-mx-input border-line-subtle text-ink-secondary hover:bg-mx-hover'
                            }`}
                        >
                            <Zap size={13} />
                            <div>
                                <div className="text-[11px] font-semibold">Smart</div>
                                <div className="text-[9px] text-ink-muted">Auto-detect newest</div>
                            </div>
                        </button>
                        <button
                            onClick={() => setSyncMode('manual')}
                            className={`flex items-center gap-2 p-2.5 rounded-mx-sm border transition-all text-left ${
                                syncMode === 'manual'
                                    ? 'bg-amber2/10 border-amber2/50 text-amber2'
                                    : 'bg-mx-input border-line-subtle text-ink-secondary hover:bg-mx-hover'
                            }`}
                        >
                            <ArrowUpDown size={13} />
                            <div>
                                <div className="text-[11px] font-semibold">Manual</div>
                                <div className="text-[9px] text-ink-muted">Pick main source</div>
                            </div>
                        </button>
                    </div>

                    {/* Manual source picker */}
                    {syncMode === 'manual' && (
                        <div className="grid grid-cols-2 gap-2">
                            <button
                                onClick={() => setMainSource('pc')}
                                className={`flex items-center gap-2 p-2 rounded-mx-xs border transition-all text-[11px] font-medium ${
                                    mainSource === 'pc' ? 'bg-teal-400/10 border-teal-400/50 text-teal-400' : 'border-line-subtle text-ink-muted hover:bg-mx-hover'
                                }`}
                            >
                                <Database size={12} /> PC is Main
                            </button>
                            <button
                                onClick={() => setMainSource('usb')}
                                className={`flex items-center gap-2 p-2 rounded-mx-xs border transition-all text-[11px] font-medium ${
                                    mainSource === 'usb' ? 'bg-teal-400/10 border-teal-400/50 text-teal-400' : 'border-line-subtle text-ink-muted hover:bg-mx-hover'
                                }`}
                            >
                                <Usb size={12} /> USB is Main
                            </button>
                        </div>
                    )}

                    {/* Categories */}
                    <div className="space-y-0.5">
                        <div className="text-[10px] text-ink-muted uppercase tracking-wider font-semibold mb-1.5">Sync Categories</div>
                        {METADATA_CATEGORIES.map(cat => (
                            <label
                                key={cat.id}
                                className="flex items-center justify-between p-1.5 rounded-mx-xs hover:bg-mx-hover cursor-pointer transition-all"
                            >
                                <div className="flex flex-col">
                                    <span className="text-[11px] text-ink-primary">{cat.label}</span>
                                    <span className="text-[9px] text-ink-muted">{cat.desc}</span>
                                </div>
                                <input
                                    type="checkbox"
                                    checked={categories[cat.id]}
                                    onChange={() => toggleCategory(cat.id)}
                                    className="accent-amber2 w-3.5 h-3.5"
                                />
                            </label>
                        ))}
                    </div>

                    {/* Action */}
                    <button className="btn-primary text-[11px] py-1.5 px-3 flex items-center gap-1.5 w-full justify-center">
                        <ArrowUpDown size={11} /> Sync Metadata to {device?.label || 'USB'}
                    </button>
                </div>
            )}
        </div>
    );
};

export default UsbView;
