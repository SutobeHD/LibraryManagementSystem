// Open a web link outside the app: the system browser in Tauri, a new tab in the browser.
//
// Every URL that reaches here came from somewhere untrusted — a SoundCloud profile, a
// MusicBrainz relation, an artist bio, a paste. `safeExternalUrl` is the last gate before
// the operating system is asked to open it: http(s) only, no credentials, a dotted host,
// no whitespace or control characters. The backend applies the same rules before it
// stores a link (`app/artist_store/links.py:classify_url`); this is defence in depth.
//
// In Tauri the call goes to the shell plugin's `open` command, whose default scope
// (tauri-plugin-shell 2.3.5) is `^((mailto:\w+)|(tel:\w+)|(https?://\w+)).+` — the
// `shell:allow-open` capability in `src-tauri/capabilities/main.json` is what lets it run.
// Links are opened from buttons, not `<a target="_blank">`: the plugin also hooks every
// `_blank` anchor on the page, and doing both would open the page twice.

const MAX_URL_LENGTH = 2048;
const WHITESPACE = /\s/;
const IPV4_HOST = /^\d{1,3}(\.\d{1,3}){3}$/;

/** Whitespace, a backslash or a C0/DEL control character — none belongs in a web link. */
function hasUnsafeChars(text) {
    if (WHITESPACE.test(text)) return true;
    for (let i = 0; i < text.length; i += 1) {
        const code = text.charCodeAt(i);
        if (code < 0x20 || code === 0x7f || code === 0x5c) return true;
    }
    return false;
}

export function isTauriRuntime() {
    return (
        typeof window !== 'undefined' &&
        !!(window.__TAURI_INTERNALS__ || window.__TAURI_METADATA__ || window.__TAURI__)
    );
}

/** The canonical href of a safe http(s) URL, or null. Never throws. */
export function safeExternalUrl(raw) {
    const text = typeof raw === 'string' ? raw.trim() : '';
    if (!text || text.length > MAX_URL_LENGTH || hasUnsafeChars(text)) return null;
    let url;
    try {
        url = new URL(text);
    } catch {
        return null;
    }
    if (url.protocol !== 'https:' && url.protocol !== 'http:') return null;
    if (url.username || url.password) return null;
    // The URL parser rewrites every IPv4 spelling (hex, octal, one integer) to dotted
    // decimal, so one pattern refuses them all — as the backend's classify_url does.
    const host = url.hostname.replace(/\.$/, '');
    if (!host.includes('.') || host.startsWith('[') || IPV4_HOST.test(host)) return null;
    return url.href;
}

/**
 * Open `raw` outside the app. Resolves to `'system'` (Tauri) or `'tab'` (browser dev).
 * Rejects without opening anything when the URL is not a safe http(s) link.
 *
 * `deps` exists for tests: `{ isTauri, invoke, windowOpen }`.
 */
export async function openExternal(raw, deps = {}) {
    const url = safeExternalUrl(raw);
    if (!url) throw new Error('Refusing to open a link that is not a plain web address.');
    const tauri = deps.isTauri ?? isTauriRuntime();
    if (tauri) {
        const invoke = deps.invoke ?? (await import('@tauri-apps/api/core')).invoke;
        await invoke('plugin:shell|open', { path: url });
        return 'system';
    }
    const windowOpen =
        deps.windowOpen ?? ((href) => window.open(href, '_blank', 'noopener,noreferrer'));
    windowOpen(url);
    return 'tab';
}
