/**
 * SettingsControls — Shared building blocks for the tabbed Settings panel.
 *
 * Exports:
 *   Toggle      — labelled on/off switch
 *   Section     — outer card wrapper with an icon-prefixed heading
 *   Field       — label + control row
 *   Select      — compact native <select>
 *   KeyCapture  — keyboard-shortcut capture button
 */

import React, { useState, useRef } from 'react';
import { ChevronRight } from 'lucide-react';

/** Render a toggle switch */
export const Toggle = ({ checked, onChange, label, sub }) => (
    <div className="flex items-center justify-between">
        <div>
            <p className="text-sm font-semibold text-white">{label}</p>
            {sub && <p className="text-xs text-ink-muted mt-0.5">{sub}</p>}
        </div>
        <button
            role="switch"
            aria-checked={checked}
            onClick={() => onChange(!checked)}
            className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${checked ? 'bg-amber2' : 'bg-mx-hover'}`}
        >
            <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${checked ? 'translate-x-6' : 'translate-x-1'}`} />
        </button>
    </div>
);

/** Section wrapper */
export const Section = ({ title, icon: Icon, children }) => (
    <div className="bg-mx-deepest/50 rounded-2xl p-6 border border-white/5 space-y-5">
        <h2 className="text-xs font-bold text-amber2 uppercase tracking-widest flex items-center gap-2">
            {Icon && <Icon size={14} />}{title}
        </h2>
        {children}
    </div>
);

/** Label + select/input row */
export const Field = ({ label, children }) => (
    <div>
        <label className="text-xs text-ink-secondary mb-2 block font-bold uppercase tracking-wide">{label}</label>
        {children}
    </div>
);

/** Native styled <select> for the USB profile form */
export const Select = ({ value, onChange, options }) => (
    <select
        className="input-glass text-tiny w-full"
        value={value}
        onChange={e => onChange(e.target.value)}
    >
        {options.map(o => (
            <option key={o.id} value={o.id}>{o.label}</option>
        ))}
    </select>
);

/** Keyboard capture button (records a key-combo for shortcut bindings) */
export const KeyCapture = ({ binding, onCapture }) => {
    const [capturing, setCapturing] = useState(false);
    const ref = useRef(null);

    const start = () => {
        setCapturing(true);
        setTimeout(() => ref.current?.focus(), 50);
    };

    const handleKey = (e) => {
        e.preventDefault();
        e.stopPropagation();

        // Ignore modifier-only presses
        if (['Control', 'Shift', 'Alt', 'Meta'].includes(e.key)) return;

        // Escape cancels capture
        if (e.key === 'Escape') { setCapturing(false); return; }

        let combo = '';
        if (e.ctrlKey)  combo += 'Ctrl+';
        if (e.shiftKey) combo += 'Shift+';
        if (e.altKey)   combo += 'Alt+';

        if (e.code === 'Space')        combo += 'Space';
        else if (e.key.length === 1)   combo += e.key.toUpperCase();
        else                           combo += e.key;

        onCapture(combo);
        setCapturing(false);
    };

    return (
        <div className="flex items-center gap-2">
            <button
                ref={ref}
                onKeyDown={capturing ? handleKey : undefined}
                onBlur={() => setCapturing(false)}
                onClick={start}
                className={`
                    px-3 py-1.5 rounded-lg text-xs font-mono border transition-all min-w-[120px] text-center
                    ${capturing
                        ? 'bg-amber2/20 border-amber2 text-amber2-hover animate-pulse'
                        : 'bg-mx-card border-white/10 text-ink-primary hover:border-amber2/50 hover:text-white'}
                `}
            >
                {capturing ? 'Press a key…' : (binding || '—')}
            </button>
            {!capturing && (
                <button onClick={start} title="Edit shortcut" className="text-ink-muted hover:text-amber2 transition-colors">
                    <ChevronRight size={12} />
                </button>
            )}
        </div>
    );
};
