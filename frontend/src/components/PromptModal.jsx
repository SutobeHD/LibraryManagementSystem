import React, { useState, useEffect, useCallback, useRef } from 'react';
import ReactDOM from 'react-dom';
import { X, Check } from 'lucide-react';

// Module-level subscriber registry so a single mounted <PromptModalRoot />
// instance fields every promptModal() call from anywhere in the app.
let pushRequest = null;
const pendingQueue = [];

/**
 * Promise-based replacement for window.prompt().
 *
 *   const value = await promptModal({
 *     title: 'Rename track',
 *     message: 'New title:',
 *     defaultValue: track.Title,
 *     placeholder: 'Untitled',
 *   });
 *
 * Resolves to the entered string on confirm, or null on cancel / Escape /
 * click-outside — matching native prompt() semantics.
 */
export function promptModal(opts = {}) {
    return new Promise((resolve) => {
        const req = {
            title: opts.title || 'Input',
            message: opts.message || '',
            defaultValue: opts.defaultValue ?? '',
            placeholder: opts.placeholder || '',
            confirmLabel: opts.confirmLabel || 'OK',
            cancelLabel: opts.cancelLabel || 'Cancel',
            resolve,
        };
        if (pushRequest) {
            pushRequest(req);
        } else {
            pendingQueue.push(req);
        }
    });
}

const PromptDialog = ({ request, onDone }) => {
    const [value, setValue] = useState(String(request.defaultValue ?? ''));
    const inputRef = useRef(null);

    const handleConfirm = useCallback(() => {
        request.resolve(value);
        onDone();
    }, [request, value, onDone]);

    const handleCancel = useCallback(() => {
        request.resolve(null);
        onDone();
    }, [request, onDone]);

    useEffect(() => {
        // Autofocus + select the existing text so users can immediately type.
        const t = setTimeout(() => {
            const el = inputRef.current;
            if (el) {
                el.focus();
                el.select?.();
            }
        }, 0);
        return () => clearTimeout(t);
    }, []);

    return (
        <div
            className="fixed inset-0 z-[300] flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in"
            onMouseDown={(e) => {
                if (e.target === e.currentTarget) handleCancel();
            }}
        >
            <div className="bg-mx-shell border border-white/10 rounded-xl p-6 w-[28rem] max-w-[90vw] shadow-2xl scale-100 animate-in fade-in zoom-in duration-200">
                <div className="flex justify-between items-center mb-4">
                    <h3 className="text-lg font-bold text-white">{request.title}</h3>
                    <button
                        onClick={handleCancel}
                        className="text-ink-secondary hover:text-white"
                        aria-label="Close"
                    >
                        <X size={20} />
                    </button>
                </div>
                {request.message && (
                    <p className="text-sm text-ink-secondary mb-3 whitespace-pre-wrap leading-relaxed">
                        {request.message}
                    </p>
                )}
                <input
                    ref={inputRef}
                    value={value}
                    onChange={(e) => setValue(e.target.value)}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                            e.preventDefault();
                            handleConfirm();
                        } else if (e.key === 'Escape') {
                            e.preventDefault();
                            handleCancel();
                        }
                    }}
                    placeholder={request.placeholder}
                    className="input-glass w-full mb-6 font-medium text-base"
                />
                <div className="flex justify-end gap-3">
                    <button
                        onClick={handleCancel}
                        className="px-4 py-2 text-sm font-medium text-ink-secondary hover:text-white transition-colors"
                    >
                        {request.cancelLabel}
                    </button>
                    <button
                        onClick={handleConfirm}
                        className="px-4 py-2 text-sm font-medium bg-amber2 hover:bg-amber2 text-white rounded-lg transition-colors flex items-center gap-2"
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
 * Maintains a FIFO of pending requests so back-to-back promptModal() calls
 * never collide visually — only the head of the queue is rendered.
 */
export const PromptModalRoot = () => {
    const [queue, setQueue] = useState([]);

    useEffect(() => {
        pushRequest = (req) => setQueue((q) => [...q, req]);
        if (pendingQueue.length) {
            setQueue((q) => [...q, ...pendingQueue.splice(0)]);
        }
        return () => { pushRequest = null; };
    }, []);

    if (queue.length === 0) return null;

    const current = queue[0];
    const handleDone = () => setQueue((q) => q.slice(1));

    return ReactDOM.createPortal(
        <PromptDialog request={current} onDone={handleDone} />,
        document.body
    );
};

export default PromptDialog;
