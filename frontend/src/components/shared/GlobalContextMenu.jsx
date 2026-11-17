import { useCallback, useEffect, useState } from 'react';
import toast from 'react-hot-toast';
import { Clipboard, Copy, Eraser, Scissors, TextSelect } from 'lucide-react';
import { ContextMenu } from './ContextMenu';

// Two jobs:
//  1. Kill the WebView's own menu app-wide — "Reload", "Back", "Inspect",
//     "Save image as…" are never valid actions inside a DJ library manager.
//  2. Where the app itself has no menu for the spot, offer the options that DO
//     make sense: real edit actions on text fields, copy on a selection.

const isTextInput = (el) =>
    !!el &&
    ((el.tagName === 'INPUT' &&
        !['checkbox', 'radio', 'range', 'color', 'file', 'button', 'submit'].includes(
            (el.type || 'text').toLowerCase()
        )) ||
        el.tagName === 'TEXTAREA');

// A right-click inside an input collapses the selection *before* contextmenu
// fires, so by the time the menu is built the highlighted text is gone and
// Cut/Copy would always render dead. Remember the last real selection per
// element and restore it when the menu opens on that same element.
let lastSelection = null;

const forgetSelection = () => {
    lastSelection = null;
};

const installSelectionTracker = () => {
    const remember = () => {
        const el = document.activeElement;
        if (!isTextInput(el)) return;
        const start = el.selectionStart ?? 0;
        const end = el.selectionEnd ?? 0;
        if (end > start) lastSelection = { el, start, end };
    };
    const onMouseDown = (e) => {
        // Left-click moves the caret on purpose — the old range is stale.
        if (e.button === 0) forgetSelection();
    };
    const onKeyDown = (e) => {
        if (!e.shiftKey && !e.ctrlKey && !e.metaKey) forgetSelection();
    };
    // `selectionchange` only reaches the document for text fields in newer
    // Chromium; `select` + key/mouse-up cover the WebView versions that don't.
    document.addEventListener('selectionchange', remember);
    document.addEventListener('select', remember, true);
    document.addEventListener('keyup', remember, true);
    document.addEventListener('mouseup', remember, true);
    document.addEventListener('mousedown', onMouseDown, true);
    document.addEventListener('keydown', onKeyDown, true);
    document.addEventListener('input', forgetSelection, true);
    return () => {
        document.removeEventListener('selectionchange', remember);
        document.removeEventListener('select', remember, true);
        document.removeEventListener('keyup', remember, true);
        document.removeEventListener('mouseup', remember, true);
        document.removeEventListener('mousedown', onMouseDown, true);
        document.removeEventListener('keydown', onKeyDown, true);
        document.removeEventListener('input', forgetSelection, true);
    };
};

// React tracks the last value it wrote; assigning `.value` directly leaves the
// tracker in sync and the change event is swallowed. Go through the prototype
// setter so controlled inputs actually update.
const setNativeValue = (el, value) => {
    const proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement : HTMLInputElement;
    const setter = Object.getOwnPropertyDescriptor(proto.prototype, 'value')?.set;
    if (setter) setter.call(el, value);
    else el.value = value;
    el.dispatchEvent(new Event('input', { bubbles: true }));
};

const replaceSelection = (el, text) => {
    const start = el.selectionStart ?? el.value.length;
    const end = el.selectionEnd ?? el.value.length;
    const next = el.value.slice(0, start) + text + el.value.slice(end);
    setNativeValue(el, next);
    const caret = start + text.length;
    requestAnimationFrame(() => {
        try {
            el.setSelectionRange(caret, caret);
        } catch {
            /* selection API unavailable on this input type */
        }
    });
};

const writeClipboard = async (text) => {
    try {
        await navigator.clipboard.writeText(text);
        return true;
    } catch (err) {
        console.error('[GlobalContextMenu] clipboard write failed', err);
        toast.error('Zwischenablage nicht verfügbar');
        return false;
    }
};

const buildItems = (target) => {
    const selection = String(window.getSelection?.() || '');

    if (isTextInput(target) && !target.disabled) {
        const el = target;
        let start = el.selectionStart ?? 0;
        let end = el.selectionEnd ?? 0;
        if (end <= start && lastSelection?.el === el) {
            ({ start, end } = lastSelection);
            end = Math.min(end, el.value.length);
            start = Math.min(start, end);
            if (end > start) {
                try {
                    el.focus();
                    el.setSelectionRange(start, end);
                } catch {
                    /* input type without a selection API */
                }
            }
        }
        const hasSel = end > start;
        const selText = hasSel ? el.value.slice(start, end) : '';
        return [
            {
                id: 'cut',
                label: 'Ausschneiden',
                icon: Scissors,
                disabled: !hasSel || el.readOnly,
                onSelect: async () => {
                    if (await writeClipboard(selText)) replaceSelection(el, '');
                },
            },
            {
                id: 'copy',
                label: 'Kopieren',
                icon: Copy,
                disabled: !hasSel,
                onSelect: () => writeClipboard(selText),
            },
            {
                id: 'paste',
                label: 'Einfügen',
                icon: Clipboard,
                disabled: el.readOnly,
                onSelect: async () => {
                    try {
                        const text = await navigator.clipboard.readText();
                        el.focus();
                        replaceSelection(el, text);
                    } catch (err) {
                        console.error('[GlobalContextMenu] clipboard read failed', err);
                        toast.error('Zwischenablage nicht lesbar — Strg+V benutzen');
                    }
                },
            },
            { separator: true },
            {
                id: 'select-all',
                label: 'Alles auswählen',
                icon: TextSelect,
                hint: 'Strg+A',
                disabled: !el.value,
                onSelect: () => {
                    el.focus();
                    el.select();
                },
            },
            {
                id: 'clear',
                label: 'Feld leeren',
                icon: Eraser,
                disabled: !el.value || el.readOnly,
                onSelect: () => {
                    el.focus();
                    setNativeValue(el, '');
                },
            },
        ];
    }

    if (selection.trim()) {
        return [
            {
                id: 'copy-selection',
                label: 'Auswahl kopieren',
                icon: Copy,
                onSelect: () => writeClipboard(selection),
            },
        ];
    }

    // Nothing sensible to offer here — show no menu at all rather than a
    // browser one.
    return [];
};

const GlobalContextMenu = () => {
    const [menu, setMenu] = useState(null);
    const close = useCallback(() => setMenu(null), []);

    useEffect(() => {
        // Capture phase, registered on the document: fires before any component
        // handler, so the native menu is dead no matter what the app does with
        // the event afterwards (stopPropagation included).
        const suppress = (e) => e.preventDefault();
        document.addEventListener('contextmenu', suppress, true);
        const stopTracking = installSelectionTracker();
        return () => {
            document.removeEventListener('contextmenu', suppress, true);
            stopTracking();
        };
    }, []);

    useEffect(() => {
        const onContextMenu = (e) => {
            const target = e.target;
            const x = e.clientX;
            const y = e.clientY;
            // Let the app's own menus win. They render on a state update, so
            // check after React has flushed this discrete event.
            setTimeout(() => {
                if (document.querySelector('[data-context-menu="true"]')) return;
                const items = buildItems(target);
                if (items.length) setMenu({ x, y, items });
            }, 0);
        };
        document.addEventListener('contextmenu', onContextMenu);
        return () => document.removeEventListener('contextmenu', onContextMenu);
    }, []);

    if (!menu) return null;
    return <ContextMenu x={menu.x} y={menu.y} items={menu.items} onClose={close} />;
};

export default GlobalContextMenu;
