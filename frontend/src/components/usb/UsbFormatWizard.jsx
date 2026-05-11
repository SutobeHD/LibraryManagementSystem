/**
 * UsbFormatWizard — destructive FAT32 / exFAT re-format modal.
 *
 * Two-step backend protocol:
 *   POST /api/usb/format/preview  → token + warning
 *   POST /api/usb/format/confirm  → wipe + reformat + Pioneer skeleton
 *
 * The container owns the preview/submit calls; this component is purely
 * presentational and pushes state changes back via `onChange`.
 */
import React from 'react';
import { AlertTriangle, Loader2, Eraser } from 'lucide-react';
import { formatBytes } from './UsbControls';

const InfoField = ({ label, children }) => (
    <div className="bg-mx-input border border-line-subtle rounded-lg px-3 py-2">
        <div className="text-[9px] uppercase tracking-wide text-ink-muted font-semibold">{label}</div>
        <div className="text-[12px] font-mono text-ink-primary mt-0.5">{children}</div>
    </div>
);

const UsbFormatWizard = ({ state, onChange, onClose, onSubmit }) => {
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
                        <InfoField label="Drive">{preview.drive}</InfoField>
                        <InfoField label="Current label">{preview.label || '(none)'}</InfoField>
                        <InfoField label="Current FS">{preview.filesystem}</InfoField>
                        <InfoField label="Total size">{formatBytes(preview.total_bytes || 0)}</InfoField>
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

export default UsbFormatWizard;
