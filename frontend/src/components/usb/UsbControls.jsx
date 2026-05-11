/**
 * UsbControls — shared helpers used across the USB sub-components.
 *
 *  • compatibility data (FS_COMPAT, FS_NOTES, CDJ_TARGETS, USB_TYPES)
 *  • normalizeFs / worstCdjStatus
 *  • format helpers (formatBytes, formatDate)
 *  • small visual primitives (StatusIcon, Toggle, PillBtn, PillTab, Row, SpaceBar)
 *  • playlist helpers (getDescendantIds, PlaylistTreeNode, UsbLibraryTree)
 *
 * Kept in one file on purpose: every sub-panel pulls a handful of these,
 * and re-importing from N scattered files was getting noisy.
 */
import React, { useState } from 'react';
import {
    Check, X, AlertTriangle, ChevronRight, ChevronDown,
    Folder, FolderOpen, Music, Zap, HardDrive, Database,
    ListMusic, PlayCircle,
} from 'lucide-react';

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
export const FS_COMPAT = {
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
export const FS_NOTES = {
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

export const CDJ_TARGETS = [
    { id: 'pc',         label: 'PC / rekordbox',  short: 'PC' },
    { id: 'cdj3000',    label: 'CDJ-3000',        short: '3000' },
    { id: 'cdj2000nxs2',label: 'CDJ-2000NXS2',    short: 'NXS2' },
    { id: 'cdj2000nxs', label: 'CDJ-2000NXS',     short: 'NXS' },
    { id: 'cdjOlder',   label: 'Older CDJ',       short: 'Older' },
];

export const USB_TYPES = [
    { id: 'MainCollection', label: 'Main Collection',  desc: 'Primary DJ library',         icon: Database },
    { id: 'Collection',     label: 'Collection',       desc: 'Full library copy',          icon: HardDrive },
    { id: 'PartCollection', label: 'Part Collection',  desc: 'Selected genres / folders',  icon: ListMusic },
    { id: 'SetStick',       label: 'Set Stick',        desc: 'Playlists only (<500 tracks)', icon: PlayCircle },
];

/** Normalize the raw filesystem string into a key into FS_COMPAT. */
export const normalizeFs = (raw) => {
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
export const worstCdjStatus = (compat) => {
    const cdjOnly = ['cdj3000', 'cdj2000nxs2', 'cdj2000nxs', 'cdjOlder'];
    if (cdjOnly.some(k => compat[k] === 'incompat')) return 'partial';
    if (cdjOnly.some(k => compat[k] === 'warn')) return 'warn';
    return 'ok';
};

// ────────────────────────────────────────────────────────────────────
//  PRESENTATION HELPERS
// ────────────────────────────────────────────────────────────────────

export const StatusIcon = ({ status, size = 12 }) => {
    if (status === 'ok')       return <Check size={size} className="text-ok" />;
    if (status === 'warn')     return <AlertTriangle size={size} className="text-amber2" />;
    if (status === 'incompat') return <X size={size} className="text-bad" />;
    return null;
};

export const formatBytes = (b) => {
    if (!b) return '0 B';
    const k = 1024;
    const s = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(b) / Math.log(k));
    return `${(b / Math.pow(k, i)).toFixed(1)} ${s[i]}`;
};

export const formatDate = (iso) => {
    if (!iso) return 'Never';
    const d = new Date(iso);
    const diff = new Date() - d;
    if (diff < 60000)    return 'Just now';
    if (diff < 3600000)  return `${Math.floor(diff / 60000)}m ago`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
    if (diff < 604800000)return `${Math.floor(diff / 86400000)}d ago`;
    return d.toLocaleDateString();
};

// ────────────────────────────────────────────────────────────────────
//  PLAYLIST TREE
// ────────────────────────────────────────────────────────────────────

export const getDescendantIds = (node) => {
    let ids = [];
    if (node.Type !== '0') ids.push(node.ID);
    if (node.Children) node.Children.forEach(c => { ids = ids.concat(getDescendantIds(c)); });
    return ids;
};

export const PlaylistTreeNode = ({ node, depth = 0, selectedIds, onToggle }) => {
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
//  USB LIBRARY TREE (folder / track flat tree)
// ────────────────────────────────────────────────────────────────────

export const UsbLibraryTree = ({ item, level = 0 }) => {
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

export const SpaceBar = ({ total, free, estimatedUsage }) => {
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
//  SMALL HELPERS
// ────────────────────────────────────────────────────────────────────

export const Row = ({ label, value, color, muted }) => (
    <div className="flex justify-between">
        <span className="text-ink-secondary">{label}</span>
        <span className={muted ? 'text-ink-muted' : color === 'ok' ? 'text-ok' : color === 'bad' ? 'text-bad' : 'text-amber2'}>
            {value}
        </span>
    </div>
);

export const Toggle = ({ label, sub, checked, onChange }) => (
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

export const PillBtn = ({ active, onClick, children }) => (
    <button
        onClick={onClick}
        className={`py-1.5 text-[11px] font-medium rounded-mx-sm border transition-all ${
            active ? 'bg-amber2/10 border-amber2/50 text-amber2' : 'border-line-subtle text-ink-muted hover:bg-mx-hover'
        }`}
    >
        {children}
    </button>
);

export const PillTab = ({ active, onClick, children }) => (
    <button
        onClick={onClick}
        className={`px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider rounded-mx-xs transition-all ${
            active ? 'bg-amber2 text-mx-deepest' : 'text-ink-muted hover:text-ink-primary'
        }`}
    >
        {children}
    </button>
);
