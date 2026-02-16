import React, { useState, useEffect } from 'react';
import { X, Check } from 'lucide-react';

const RenameModal = ({ isOpen, onClose, onConfirm, initialValue, title = "Rename" }) => {
    const [value, setValue] = useState(initialValue || "");

    useEffect(() => { setValue(initialValue || ""); }, [initialValue, isOpen]);

    if (!isOpen) return null;

    return (
        <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
            <div className="bg-slate-900 border border-white/10 rounded-xl p-6 w-96 shadow-2xl scale-100 animate-in fade-in zoom-in duration-200">
                <div className="flex justify-between items-center mb-4">
                    <h3 className="text-lg font-bold text-white">{title}</h3>
                    <button onClick={onClose} className="text-slate-400 hover:text-white"><X size={20} /></button>
                </div>
                <input
                    autoFocus
                    value={value}
                    onChange={(e) => setValue(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') onConfirm(value); if (e.key === 'Escape') onClose(); }}
                    className="input-glass w-full mb-6 font-medium text-lg"
                    placeholder="Enter new name..."
                />
                <div className="flex justify-end gap-3">
                    <button onClick={onClose} className="px-4 py-2 text-sm font-medium text-slate-400 hover:text-white transition-colors">Cancel</button>
                    <button onClick={() => onConfirm(value)} className="px-4 py-2 text-sm font-medium bg-cyan-600 hover:bg-cyan-500 text-white rounded-lg transition-colors flex items-center gap-2">
                        <Check size={16} /> Save
                    </button>
                </div>
            </div>
        </div>
    );
};

export default RenameModal;
