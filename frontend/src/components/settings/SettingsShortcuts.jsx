/**
 * SettingsShortcuts — Configurable DAW keyboard shortcut bindings.
 */

import React, { useCallback } from 'react';
import { Keyboard } from 'lucide-react';
import { Section, KeyCapture } from './SettingsControls';

const SHORTCUT_DEFAULTS = {
    play_pause:  'Space',
    jump_start:  'Home',
    jump_end:    'End',
    scrub_back:  'ArrowLeft',
    scrub_fwd:   'ArrowRight',
    split:       'Ctrl+E',
    delete:      'Delete',
    undo:        'Ctrl+Z',
    redo:        'Ctrl+Shift+Z',
    copy:        'Ctrl+C',
    paste:       'Ctrl+V',
    duplicate:   'Ctrl+D',
    save:        'Ctrl+S',
    open:        'Ctrl+O',
};

const SHORTCUT_LABELS = {
    play_pause:  'Play / Pause',
    jump_start:  'Jump to Start',
    jump_end:    'Jump to End',
    scrub_back:  'Scrub Back (1 Beat)',
    scrub_fwd:   'Scrub Forward (1 Beat)',
    split:       'Split Region',
    delete:      'Ripple Delete',
    undo:        'Undo',
    redo:        'Redo',
    copy:        'Copy Selection',
    paste:       'Paste / Insert',
    duplicate:   'Duplicate',
    save:        'Save Project',
    open:        'Open Project',
};

const SettingsShortcuts = ({ settings, setSettings }) => {
    const setShortcut = useCallback((action, combo) => {
        setSettings(prev => ({
            ...prev,
            shortcuts: { ...(prev.shortcuts || {}), [action]: combo },
        }));
    }, [setSettings]);

    return (
        <div className="space-y-6">
            <Section title="DAW Keyboard Shortcuts" icon={Keyboard}>
                <p className="text-xs text-ink-muted">
                    Click any shortcut to capture a new key binding. Changes apply immediately in the DAW editor after saving.
                    Press <kbd className="px-1.5 py-0.5 bg-mx-card rounded text-[10px] font-mono border border-white/10">Esc</kbd> to cancel capture.
                </p>
                <div className="space-y-1.5">
                    {Object.entries(SHORTCUT_LABELS).map(([action, label]) => (
                        <div key={action} className="flex items-center justify-between p-2.5 rounded-xl hover:bg-mx-card/50 transition-colors">
                            <span className="text-sm text-ink-primary">{label}</span>
                            <KeyCapture
                                binding={settings.shortcuts?.[action] || SHORTCUT_DEFAULTS[action]}
                                onCapture={combo => setShortcut(action, combo)}
                            />
                        </div>
                    ))}
                </div>
                <button
                    onClick={() => setSettings(prev => ({ ...prev, shortcuts: { ...SHORTCUT_DEFAULTS } }))}
                    className="text-xs text-ink-muted hover:text-white border border-white/10 hover:border-white/20 rounded-lg px-3 py-2 transition-all"
                >
                    Reset to defaults
                </button>
            </Section>
        </div>
    );
};

export default SettingsShortcuts;
