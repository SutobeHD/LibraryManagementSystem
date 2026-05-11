/**
 * UsbSyncPanel — the right-hand main pane.
 *
 * Renders the per-device controls:
 *   • Header (label + rename + eject)
 *   • Hardware-compatibility matrix (PC + CDJ-3000 / NXS2 / NXS / older)
 *   • Non-Rekordbox empty state ("Initialize Library")
 *   • Storage bar with estimated sync usage
 *   • Main sync source toggle (PC ↔ USB)
 *   • Target ecosystem picker (MainCollection / Collection / Part / SetStick)
 *   • Sync controls — preview diff, sync button, progress bar
 *   • Settings card (auto-sync + mirrored + primary library)
 *   • Drive actions (rename)
 *   • Danger zone (delete profile, reset USB, format wizard)
 *   • Stats footer
 *
 * All API calls live in the container; we only call back into the
 * handler props provided.
 */
import React from 'react';
import {
    HardDrive, Power, Edit2, AlertTriangle, Database, Usb, Check,
    ChevronRight, Trash2, Eraser, Download, Loader2, Clock,
    ShieldCheck, ShieldAlert, Info,
} from 'lucide-react';
import {
    FS_COMPAT, FS_NOTES, CDJ_TARGETS, USB_TYPES,
    normalizeFs, worstCdjStatus, formatBytes,
    StatusIcon, SpaceBar, Toggle, PillBtn, Row,
} from './UsbControls';

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
//  HEADER (label + rename + eject)
// ────────────────────────────────────────────────────────────────────

const DeviceHeader = ({ sel, isConnected, onRename, onEject }) => (
    <div className="flex items-start justify-between">
        <div>
            <h2 className="text-[18px] font-semibold tracking-tight flex items-center gap-2.5">
                <div className={`w-2 h-2 rounded-full ${
                    isConnected ? 'bg-ok shadow-[0_0_6px_#3DD68C]' : 'bg-bad'
                }`} />
                {sel.label || 'USB Drive'}
                <button
                    onClick={onRename}
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
            onClick={onEject}
            disabled={!isConnected}
            className="p-2 hover:bg-amber2/10 text-ink-muted hover:text-amber2 rounded-mx-sm transition-all disabled:opacity-30"
            title="Safely eject drive"
        >
            <Power size={16} />
        </button>
    </div>
);

// ────────────────────────────────────────────────────────────────────
//  Main sync source + target ecosystem
// ────────────────────────────────────────────────────────────────────

const MainSourceCard = ({ sel, onSave }) => (
    <div className="mx-card p-4">
        <div className="mx-caption mb-3">Main Sync Source</div>
        <div className="grid grid-cols-2 gap-2">
            <button
                onClick={() => onSave({ sync_direction: 'pc_main' })}
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
                onClick={() => onSave({ sync_direction: 'usb_main' })}
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
);

const TargetEcosystemCard = ({ sel, onSave }) => (
    <div className="mx-card p-4">
        <div className="mx-caption mb-3">Target Ecosystem</div>
        <div className="grid grid-cols-2 gap-2">
            {USB_TYPES.map(type => {
                const Icon = type.icon;
                const active = sel.type === type.id;
                return (
                    <button
                        key={type.id}
                        onClick={() => onSave({ type: type.id })}
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
);

// ────────────────────────────────────────────────────────────────────
//  Sync controls
// ────────────────────────────────────────────────────────────────────

const SyncControls = ({ sel, syncing, syncProgress, diff, isConnected, onLoadDiff, onRunSync }) => (
    <div className="mx-card p-4">
        <div className="flex items-center justify-between mb-3">
            <span className="mx-caption">Sync</span>
            <span className="text-[10px] text-ink-muted">
                {sel.type === 'SetStick'
                    ? `${(sel.sync_playlists || []).length} playlists selected`
                    : `Full ${USB_TYPES.find(t => t.id === sel.type)?.label || 'collection'}`}
            </span>
        </div>

        {isConnected && (
            <button
                onClick={onLoadDiff}
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
            onClick={onRunSync}
            disabled={!!syncing || !isConnected || !(sel.sync_playlists || []).length}
            title={(sel.sync_playlists || []).length ? '' : 'Select at least one playlist'}
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
);

// ────────────────────────────────────────────────────────────────────
//  Settings card
// ────────────────────────────────────────────────────────────────────

const SettingsCard = ({ sel, onSave }) => (
    <div className="mx-card p-4">
        <div className="mx-caption mb-3">Settings</div>
        <Toggle
            label="Auto-sync on startup"
            checked={sel.auto_sync || false}
            onChange={(v) => onSave({ auto_sync: v })}
        />
        <Toggle
            label="Mirrored sync"
            sub="Keep both libraries identical"
            checked={sel.sync_mirrored || false}
            onChange={(v) => onSave({ sync_mirrored: v })}
        />
        {sel.sync_mirrored && (
            <div className="mt-2 p-2.5 bg-mx-input rounded-mx-sm border border-line-subtle">
                <div className="mx-caption mb-2">Primary Library (Master)</div>
                <div className="grid grid-cols-2 gap-2">
                    <PillBtn
                        active={sel.sync_primary !== 'library_legacy'}
                        onClick={() => onSave({ sync_primary: 'library_one' })}
                    >Newer</PillBtn>
                    <PillBtn
                        active={sel.sync_primary === 'library_legacy'}
                        onClick={() => onSave({ sync_primary: 'library_legacy' })}
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
);

// ────────────────────────────────────────────────────────────────────
//  Public — sync panel pre-profile-editor block
// ────────────────────────────────────────────────────────────────────

/**
 * The "top half" of the right pane (everything ABOVE the playlist
 * picker + USB-library viewer). Split out so the container can render
 * `UsbSyncPanel` → `UsbProfileEditor` → metadata panels → settings/danger
 * in the same order as the original layout.
 */
const UsbSyncPanel = ({
    sel,
    isConnected,
    diff,
    syncing,
    syncProgress,
    onRename,
    onEject,
    onInitLibrary,
    onSaveProfile,
    onLoadDiff,
    onRunSync,
}) => {
    return (
        <>
            {/* Device header */}
            <DeviceHeader sel={sel} isConnected={isConnected} onRename={onRename} onEject={onEject} />

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
                    <button onClick={onInitLibrary} className="btn-primary flex items-center gap-2 mt-2">
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
                    <MainSourceCard sel={sel} onSave={onSaveProfile} />

                    {/* Target Ecosystem */}
                    <TargetEcosystemCard sel={sel} onSave={onSaveProfile} />
                </>
            )}
        </>
    );
};

/**
 * The "bottom half" of the right pane: sync controls (preview + run),
 * settings + drive actions + danger zone + stats footer.
 *
 * Split into its own component because the playlist picker + USB-library
 * viewer (`UsbProfileEditor`) sit BETWEEN the target-ecosystem card and
 * these controls in the original layout — but they're all rendered by
 * the container, so each "half" gets its own component for readability.
 */
export const UsbSyncControlsTail = ({
    sel,
    isConnected,
    diff,
    syncing,
    syncProgress,
    onSaveProfile,
    onLoadDiff,
    onRunSync,
    onRename,
    onDeleteProfile,
    onResetUsb,
    onOpenFormatWizard,
}) => {
    return (
        <>
            {/* Sync controls */}
            <SyncControls
                sel={sel}
                syncing={syncing}
                syncProgress={syncProgress}
                diff={diff}
                isConnected={isConnected}
                onLoadDiff={onLoadDiff}
                onRunSync={onRunSync}
            />
        </>
    );
};

/**
 * The trailing settings + actions block. Renders below the metadata
 * sync panels in the original layout.
 */
export const UsbSettingsTail = ({
    sel,
    isConnected,
    onSaveProfile,
    onRename,
    onDeleteProfile,
    onResetUsb,
    onOpenFormatWizard,
}) => {
    return (
        <>
            {/* Settings */}
            <SettingsCard sel={sel} onSave={onSaveProfile} />

            {/* Drive actions — non-destructive */}
            <div className="mx-card p-4">
                <div className="mx-caption mb-3">Drive Actions</div>
                <div className="flex items-center gap-2 flex-wrap">
                    <button
                        onClick={onRename}
                        className="flex items-center gap-2 px-3 py-2 bg-mx-input hover:bg-mx-hover text-ink-secondary rounded-mx-sm text-tiny font-semibold border border-line-subtle transition-all"
                    >
                        <Edit2 size={12} /> Rename Drive
                    </button>
                </div>
            </div>

            {/* Danger zone — destructive only */}
            <div className="mx-card p-4" style={{ borderColor: 'rgba(232, 92, 74, 0.20)' }}>
                <div className="mx-caption mb-3" style={{ color: 'var(--bad)' }}>Danger Zone</div>
                <div className="flex items-center gap-2 flex-wrap">
                    <button
                        onClick={() => onDeleteProfile(sel.device_id)}
                        className="flex items-center gap-2 px-3 py-2 bg-bad/10 hover:bg-bad/20 text-bad rounded-mx-sm text-tiny font-semibold border border-bad/30 transition-all"
                    >
                        <Trash2 size={12} /> Delete Profile
                    </button>
                    <button
                        onClick={onResetUsb}
                        disabled={!isConnected}
                        className="flex items-center gap-2 px-3 py-2 bg-bad/10 hover:bg-bad/20 text-bad rounded-mx-sm text-tiny font-semibold border border-bad/30 transition-all disabled:opacity-30"
                    >
                        <Trash2 size={12} /> Reset USB
                    </button>
                    <button
                        onClick={onOpenFormatWizard}
                        disabled={!isConnected}
                        title="Wipe & re-format this drive as FAT32 / exFAT for CDJs"
                        className="flex items-center gap-2 px-3 py-2 bg-bad/15 hover:bg-bad/25 text-bad rounded-mx-sm text-tiny font-bold border border-bad/40 transition-all disabled:opacity-30"
                    >
                        <Eraser size={12} /> Format for CDJ…
                    </button>
                </div>
            </div>
        </>
    );
};

/**
 * Last line of the right pane: a tiny font-mono diagnostic strip.
 */
export const UsbStatsFooter = ({ sel }) => (
    <div className="flex items-center gap-3 text-[10px] text-ink-placeholder font-mono px-1">
        <span>RB DB: {sel.has_export_db ? '✓' : '✗'}</span>
        <span>·</span>
        <span>Legacy PDB: {sel.has_legacy_pdb ? '✓' : '✗'}</span>
        <span>·</span>
        <span className="truncate">{sel.device_id}</span>
    </div>
);

export default UsbSyncPanel;
