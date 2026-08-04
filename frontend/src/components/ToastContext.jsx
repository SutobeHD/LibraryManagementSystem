/* eslint-disable react-refresh/only-export-components -- useToast() is the consumer hook for the provider defined in this file; the standard context pattern keeps them together */
import { createContext, useContext, useState, useCallback, useMemo } from 'react';
import { X, CheckCircle, AlertCircle, Info } from 'lucide-react';

const ToastContext = createContext(null);

export const useToast = () => {
    const context = useContext(ToastContext);
    if (!context) throw new Error('useToast must be used within a ToastProvider');
    return context;
};

export const ToastProvider = ({ children }) => {
    const [toasts, setToasts] = useState([]);

    // Declared before addToast: it used to sit below and be closed over from
    // an empty-dep useCallback, which only worked by accident of `const`
    // hoisting resolving at call time rather than at useCallback time.
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

    // Memoised: an inline object literal here gave every consumer of
    // useToast() a new context value on each ToastProvider render, forcing
    // them all to re-render whenever any toast appeared or expired.
    const value = useMemo(
        () => ({
            addToast,
            success: (msg) => addToast(msg, 'success'),
            error: (msg) => addToast(msg, 'error'),
            info: (msg) => addToast(msg, 'info'),
        }),
        [addToast]
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
