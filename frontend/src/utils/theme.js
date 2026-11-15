/**
 * theme — UI skin selection (per device, localStorage).
 *
 * A theme is a set of CSS-var overrides under `:root[data-theme="<id>"]`
 * (see src/themes/). The default theme has no override sheet.
 * Applied before the first render (main.jsx) so there is no flash.
 */

export const THEME_STORAGE_KEY = 'lms.ui_theme';
export const DEFAULT_THEME = 'melodex';

export const THEMES = [
    { id: 'melodex', label: 'Melodex', desc: 'Standard: Amber-Akzent, DM Sans, luftige Zeilen' },
    {
        id: 'rekordbox',
        label: 'Rekordbox-Stil',
        desc: 'Schwarz/Grau, blauer Akzent, Arial, 25px-Zebrazeilen',
    },
];

// Rekordbox 3-band waveform colours (low / mid / high), see docs/reference/rbxport/ui-skin.md §2.5.
export const REKORDBOX_WAVEFORM_COLORS = {
    waveform_color_low: '#0055E1',
    waveform_color_mid: '#FFA600',
    waveform_color_high: '#FFFFFF',
};

const isKnown = (id) => THEMES.some((t) => t.id === id);

export function getStoredTheme() {
    try {
        const id = window.localStorage.getItem(THEME_STORAGE_KEY);
        return isKnown(id) ? id : DEFAULT_THEME;
    } catch (err) {
        console.warn('[theme] localStorage read failed', err);
        return DEFAULT_THEME;
    }
}

export function applyTheme(id) {
    const theme = isKnown(id) ? id : DEFAULT_THEME;
    document.documentElement.dataset.theme = theme;
    return theme;
}

export function setTheme(id) {
    const theme = applyTheme(id);
    try {
        window.localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch (err) {
        console.warn('[theme] localStorage write failed', err);
    }
    return theme;
}
