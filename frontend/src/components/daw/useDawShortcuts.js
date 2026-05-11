/**
 * useDawShortcuts — keyboard-shortcut binding for the DJ Edit DAW.
 *
 * Owns:
 *   • `shortcutsRef` — configurable combo strings, loaded once from
 *     /api/settings (key `shortcuts`) on mount and merged onto the defaults.
 *     Stored in a ref so the keydown listener closure always reads the
 *     latest bindings without needing to be re-registered.
 *   • `matches(e, combo)` — helper that tests a KeyboardEvent against a
 *     combo string of the form ['Ctrl+']['Shift+']['Alt+']key.
 *   • The keydown / keyup listener wiring (window).
 *
 * Receives action handlers + special-case handlers (Shift slip-mode, hot-cue
 * 1..8) from `useDawKeyhandlers`.
 */
import { useEffect, useRef } from 'react';

import api from '../../api/api';

const DEFAULT_SHORTCUTS = {
    play_pause: 'Space',   jump_start: 'Home',      jump_end: 'End',
    scrub_back: 'ArrowLeft', scrub_fwd: 'ArrowRight',
    split: 'Ctrl+E',       delete: 'Delete',
    undo: 'Ctrl+Z',        redo: 'Ctrl+Shift+Z',
    copy: 'Ctrl+C',        paste: 'Ctrl+V',
    duplicate: 'Ctrl+D',   save: 'Ctrl+S',          open: 'Ctrl+O',
};

/**
 * Returns true if a KeyboardEvent matches a combo string.
 * Combo format: ['Ctrl+']['Shift+']['Alt+']key
 * key is matched against both e.code (e.g. 'Space') and e.key (e.g. 'ArrowLeft').
 */
export function matches(e, combo) {
    if (!combo) return false;
    const parts   = combo.split('+');
    const key     = parts[parts.length - 1];
    const ctrl    = parts.includes('Ctrl');
    const shift   = parts.includes('Shift');
    const alt     = parts.includes('Alt');
    if (e.ctrlKey !== ctrl || e.shiftKey !== shift || e.altKey !== alt) return false;
    return e.code === key || e.key === key;
}

export default function useDawShortcuts({ handlers, onShiftDown, onShiftUp, onHotcue }) {
    // Configurable keyboard shortcuts — loaded from /api/settings on mount.
    // Stored in a ref (not state) so the keydown handler closure always reads
    // the latest value without needing to be re-registered on every settings change.
    const shortcutsRef = useRef({ ...DEFAULT_SHORTCUTS });

    // Load configurable shortcuts from settings on mount
    useEffect(() => {
        api.get('/api/settings')
            .then(res => {
                const saved = res.data?.shortcuts;
                if (saved && typeof saved === 'object') {
                    shortcutsRef.current = { ...shortcutsRef.current, ...saved };
                }
            })
            .catch(() => {}); // non-fatal — defaults remain in ref
    }, []);

    // KEYBOARD SHORTCUTS (EC8: capture all DAW-relevant keys)
    // Uses shortcutsRef for configurable bindings; ref lookup is always current
    // even though this effect only re-registers when action handlers change.
    useEffect(() => {
        const sc = () => shortcutsRef.current; // alias for brevity

        const handleKeyDown = (e) => {
            if (e.target.closest('input, select, textarea')) return;

            // Play / Pause
            if (matches(e, sc().play_pause))  { handlers.play_pause(e);  return; }

            // Jump to Start / End
            if (matches(e, sc().jump_start))  { handlers.jump_start(e);  return; }
            if (matches(e, sc().jump_end))    { handlers.jump_end(e);    return; }

            // Scrub Back / Forward (handler short-circuits when Ctrl is held)
            if (matches(e, sc().scrub_back) && !e.ctrlKey) { handlers.scrub_back(e); return; }
            if (matches(e, sc().scrub_fwd)  && !e.ctrlKey) { handlers.scrub_fwd(e);  return; }

            // Split / Ripple Delete
            if (matches(e, sc().split))   { handlers.split(e);   return; }
            if (matches(e, sc().delete))  { handlers.delete(e);  return; }

            // Undo (must check redo first — redo has Shift modifier)
            if (matches(e, sc().redo))    { handlers.redo(e);    return; }
            if (matches(e, sc().undo))    { handlers.undo(e);    return; }

            // Copy / Paste / Duplicate
            if (matches(e, sc().copy))      { handlers.copy(e);      return; }
            if (matches(e, sc().paste))     { handlers.paste(e);     return; }
            if (matches(e, sc().duplicate)) { handlers.duplicate(e); return; }

            // Save / Open
            if (matches(e, sc().save)) { handlers.save(e); return; }
            if (matches(e, sc().open)) { handlers.open(e); return; }

            // Shift (held) — Slip mode
            if (e.key === 'Shift') {
                onShiftDown();
                return;
            }

            // 1–8 — Hot cue jump
            const num = parseInt(e.key);
            if (num >= 1 && num <= 8 && !e.ctrlKey && !e.altKey) {
                onHotcue(num);
                return;
            }
        };

        const handleKeyUp = (e) => {
            if (e.key === 'Shift') {
                onShiftUp();
            }
        };

        window.addEventListener('keydown', handleKeyDown);
        window.addEventListener('keyup', handleKeyUp);
        return () => {
            window.removeEventListener('keydown', handleKeyDown);
            window.removeEventListener('keyup', handleKeyUp);
        };
    }, [handlers, onShiftDown, onShiftUp, onHotcue]);

    return { shortcutsRef };
}
