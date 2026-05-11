import React from 'react';

// Replaces native window.confirm with a themed dialog. Click backdrop to dismiss.
export default function ConfirmModal({ modal, setModal }) {
    if (!modal) return null;
    return (
        <div className="absolute inset-0 z-[200] flex items-center justify-center bg-black/70 backdrop-blur-sm animate-fade-in" onClick={() => setModal(null)}>
            <div className="w-[420px] glass-panel border border-white/10 rounded-2xl p-6 shadow-2xl" onClick={(e) => e.stopPropagation()}>
                <h3 className="text-lg font-bold text-white mb-2">{modal.title || 'Confirm'}</h3>
                <p className="text-sm text-ink-secondary mb-6 leading-relaxed">{modal.message}</p>
                <div className="flex gap-2 justify-end">
                    <button
                        onClick={() => setModal(null)}
                        className="px-4 py-2 rounded-lg bg-mx-card/40 hover:bg-mx-card/60 border border-white/10 text-sm font-bold text-ink-secondary"
                    >Cancel</button>
                    <button
                        onClick={() => {
                            const cb = modal.onConfirm;
                            setModal(null);
                            cb?.();
                        }}
                        className="px-4 py-2 rounded-lg bg-amber2/20 hover:bg-amber2/30 border border-amber2/40 text-sm font-bold text-amber2"
                        autoFocus
                    >{modal.confirmLabel || 'Confirm'}</button>
                </div>
            </div>
        </div>
    );
}
