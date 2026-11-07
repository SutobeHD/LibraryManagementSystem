import React, { createContext, useContext, useState, useCallback, useMemo } from 'react';
import { X, CheckCircle, AlertCircle, Info } from 'lucide-react';

const ToastContext = createContext(null);

export const useToast = () => {
    const context = useContext(ToastContext);
    if (!context) throw new Error('useToast must be used within a ToastProvider');
    return context;
};

export const ToastProvider = ({ children }) => {
    const [toasts, setToasts] = useState([]);

    const removeToast = useCallback((id) => {
        setToasts((prev) => prev.filter((t) => t.id !== id));
    }, []);

    const addToast = useCallback(
        (message, type = 'info', duration = 3000) => {
            const id = Date.now().toString();
            setToasts((prev) => [...prev, { id, message, type }]);
            setTimeout(() => removeToast(id), duration);
        },
        [removeToast]
    );

    const success = useCallback((msg) => addToast(msg, 'success'), [addToast]);
    const error = useCallback((msg) => addToast(msg, 'error'), [addToast]);
    const info = useCallback((msg) => addToast(msg, 'info'), [addToast]);

    // Stable across toast add/remove: a new object here re-renders every
    // consumer (PlaylistBrowser → the whole TrackTable) twice per toast.
    const value = useMemo(
        () => ({ addToast, success, error, info }),
        [addToast, success, error, info]
    );

    return (
        <ToastContext.Provider value={value}>
            {children}
            <div className="fixed bottom-6 right-6 z-[9999] flex flex-col gap-2 pointer-events-none">
                {toasts.map((toast) => (
                    <div
                        key={toast.id}
                        className={`
                            pointer-events-auto flex items-center gap-3 px-4 py-3 rounded-xl shadow-2xl backdrop-blur-md border animate-slide-in-right
                            ${toast.type === 'success' ? 'bg-green-500/10 border-green-500/20 text-green-400' : ''}
                            ${toast.type === 'error' ? 'bg-red-500/10 border-red-500/20 text-red-400' : ''}
                            ${toast.type === 'info' ? 'bg-mx-card/80 border-white/10 text-ink-primary' : ''}
                        `}
                    >
                        {toast.type === 'success' && <CheckCircle size={18} />}
                        {toast.type === 'error' && <AlertCircle size={18} />}
                        {toast.type === 'info' && <Info size={18} />}
                        <span className="text-sm font-medium">{toast.message}</span>
                        <button
                            onClick={() => removeToast(toast.id)}
                            className="hover:text-white transition-colors"
                        >
                            <X size={14} />
                        </button>
                    </div>
                ))}
            </div>
        </ToastContext.Provider>
    );
};
