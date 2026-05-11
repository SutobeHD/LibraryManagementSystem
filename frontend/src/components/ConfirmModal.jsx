import React, { useState, useEffect, useCallback, useRef } from 'react';
import ReactDOM from 'react-dom';
import { X, Check, AlertTriangle } from 'lucide-react';

// Module-level subscriber registry so a single mounted <ConfirmModalRoot />
// instance fields every confirmModal() call from anywhere in the app.
let pushRequest = null;
const pendingQueue = [];

/**
 * Promise-based replacement for window.confirm().
 *
 *   const ok = await confirmModal({
 *     title: 'Delete file?',
 *     message: 'This cannot be undone.',
 *     confirmLabel: 'Delete',
 *     cancelLabel: 'Cancel',
 *     danger: true,
 *   });
 *
 * Resolves to true on confirm, false on cancel / Escape / click-outside.
 */
export function confirmModal(opts = {}) {
    return new Promise((resolve) => {
        const req = {
            title: opts.title || 'Confirm',
            message: opts.message || '',
            confirmLabel: opts.confirmLabel || 'Confirm',
            cancelLabel: opts.cancelLabel || 'Cancel',
            danger: !!opts.danger,
            resolve,
        };
        if (pushRequest) {
            pushRequest(req);
        } else {
            // Root not yet mounted — buffer until it is.
            pendingQueue.push(req);
        }
    });
}

const ConfirmDialog = ({ request, onDone }) => {
    const confirmBtnRef = useRef(null);

    const handleConfirm = useCallback(() => {
        request.resolve(true);
        onDone();
    }, [request, onDone]);

    const handleCancel = useCallback(() => {
        request.resolve(false);
        onDone();
    }, [request, onDone]);

    useEffect(() => {
        const onKey = (e) => {
            if (e.key === 'Escape') {
                e.stopPropagation();
                handleCancel();
            } else if (e.key === 'Enter') {
                e.stopPropagation();
                handleConfirm();
            }
        };
        window.addEventListener('keydown', onKey);
        // Autofocus the confirm button so Enter / Space work without tabbing.
        setTimeout(() => confirmBtnRef.current?.focus(), 0);
        return () => window.removeEventListener('keydown', onKey);
    }, [handleCancel, handleConfirm]);

    const danger = request.danger;
    const confirmClasses = danger
        ? 'px-4 py-2 text-sm font-medium bg-red-500 hover:bg-red-600 text-white rounded-lg transition-colors flex items-center gap-2'
        : 'px-4 py-2 text-sm font-medium bg-amber2 hover:bg-amber2 text-white rounded-lg transition-colors flex items-center gap-2';

    return (
        <div
            className="fixed inset-0 z-[300] flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in"
            onMouseDown={(e) => {
                if (e.target === e.currentTarget) handleCancel();
            }}
        >
            <div className="bg-mx-shell border border-white/10 rounded-xl p-6 w-[28rem] max-w-[90vw] shadow-2xl scale-100 animate-in fade-in zoom-in duration-200">
                <div className="flex justify-between items-center mb-4">
                    <div className="flex items-center gap-2">
                        {danger && <AlertTriangle size={18} className="text-red-400" />}
                        <h3 className="text-lg font-bold text-white">{request.title}</h3>
                    </div>
                    <button
                        onClick={handleCancel}
                        className="text-ink-secondary hover:text-white"
                        aria-label="Close"
                    >
                        <X size={20} />
                    </button>
                </div>
                {request.message && (
                    <p className="text-sm text-ink-secondary mb-6 whitespace-pre-wrap leading-relaxed">
                        {request.message}
                    </p>
                )}
                <div className="flex justify-end gap-3">
                    <button
                        onClick={handleCancel}
                        className="px-4 py-2 text-sm font-medium text-ink-secondary hover:text-white transition-colors"
                    >
                        {request.cancelLabel}
                    </button>
                    <button
                        ref={confirmBtnRef}
                        onClick={handleConfirm}
                        className={confirmClasses}
                    >
                        <Check size={16} /> {request.confirmLabel}
                    </button>
                </div>
            </div>
        </div>
    );
};

/**
 * Singleton portal host. Mount once near the app root (next to <Toaster />).
 * Maintains a FIFO of pending requests so back-to-back confirmModal() calls
 * never collide visually — only the head of the queue is rendered.
 */
export const ConfirmModalRoot = () => {
    const [queue, setQueue] = useState([]);

    useEffect(() => {
        pushRequest = (req) => setQueue((q) => [...q, req]);
        // Drain anything that was requested before the root mounted.
        if (pendingQueue.length) {
            setQueue((q) => [...q, ...pendingQueue.splice(0)]);
        }
        return () => { pushRequest = null; };
    }, []);

    if (queue.length === 0) return null;

    const current = queue[0];
    const handleDone = () => setQueue((q) => q.slice(1));

    return ReactDOM.createPortal(
        <ConfirmDialog request={current} onDone={handleDone} />,
        document.body
    );
};

export default ConfirmDialog;
