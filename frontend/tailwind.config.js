/**
 * Tailwind config — Melodex design system
 *
 * Token source: Claude Design handoff (librarymanagementsystem) — dark, cinematic,
 * precision-engineered. Amber (#E8A42A) is the single brand accent. DM Sans for UI,
 * JetBrains Mono for data (BPM, durations, IDs).
 *
 * Legacy `djdark`/`djgray`/`neon.*` keys preserved for backward compat with older
 * components — they alias into the new palette.
 */

import defaultColors from 'tailwindcss/colors.js';
import plugin from 'tailwindcss/plugin.js';

// Colour token backed by an RGB channel var (`--<name>-rgb: R G B`).
const tok = (name) => `rgb(var(--${name}-rgb) / <alpha-value>)`;

// Tailwind's own palette families are used as hard-coded accents all over the
// components (bg-amber-500/20, text-purple-400 ...). Route every shade through a
// var so a theme can recolour a whole family with one `--skin-<family>` (and
// optional `--skin-<family>-light` for shades <= 300). Without a theme override
// each var falls back to Tailwind's stock value, so the default look is unchanged.
const SKINNABLE_FAMILIES = [
    'red',
    'orange',
    'amber',
    'yellow',
    'lime',
    'green',
    'emerald',
    'teal',
    'cyan',
    'sky',
    'blue',
    'indigo',
    'violet',
    'purple',
    'fuchsia',
    'pink',
    'rose',
];
const hexChannels = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)).join(' ');
const paletteColors = {};
const paletteVars = {};
for (const family of SKINNABLE_FAMILIES) {
    paletteColors[family] = {};
    for (const [shade, hex] of Object.entries(defaultColors[family])) {
        const name = `tw-${family}-${shade}`;
        const stock = hexChannels(hex);
        paletteColors[family][shade] = tok(name);
        paletteVars[`--${name}-rgb`] =
            Number(shade) <= 300
                ? `var(--skin-${family}-light, var(--skin-${family}, ${stock}))`
                : `var(--skin-${family}, ${stock})`;
    }
}

export default {
    content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
    // Built at runtime from variables (UsbSyncPanel tone/ringColor, InsightsView
    // KpiCard color) — invisible to the content scan.
    safelist: ['text-ok', 'text-amber2', 'text-bad', 'text-teal-400', 'text-rose-400'],
    theme: {
        extend: {
            colors: {
                ...paletteColors,
                // ── Melodex base palette ──────────────────────────────
                // Values live as RGB channel vars in src/index.css (:root) so a
                // theme (src/themes/*.css, [data-theme]) can swap them at runtime
                // while opacity modifiers (bg-mx-shell/50) keep working.
                mx: {
                    deepest: tok('mx-deepest'),
                    shell: tok('mx-shell'),
                    panel: tok('mx-panel'),
                    surface: tok('mx-surface'),
                    card: tok('mx-card'),
                    hover: tok('mx-hover'),
                    selected: tok('mx-selected'),
                    input: tok('mx-input'),
                },
                // borders
                line: {
                    subtle: tok('line-subtle'),
                    DEFAULT: tok('line-default'),
                    interactive: tok('line-interactive'),
                },
                // foreground / text
                ink: {
                    primary: tok('ink-primary'),
                    secondary: tok('ink-secondary'),
                    muted: tok('ink-muted'),
                    placeholder: tok('ink-placeholder'),
                    inverse: tok('ink-inverse'),
                },
                // accent (named amber for history; a theme may make it blue)
                amber2: {
                    DEFAULT: tok('amber'),
                    hover: tok('amber-hover'),
                    press: tok('amber-press'),
                    dim: tok('amber-dim'),
                },
                // semantic
                ok: tok('ok'),
                bad: tok('bad'),
                info: tok('info'),

                // ── Legacy aliases (don't break existing code) ───────
                djdark: tok('mx-deepest'),
                djgray: tok('mx-panel'),
                neon: {
                    blue: tok('info'),
                    purple: tok('amber'),
                    pink: tok('amber-hover'),
                },
            },
            fontFamily: {
                sans: ['var(--font-ui)'],
                mono: ['var(--font-mono)'],
            },
            fontSize: {
                // 11px / 12px / 14px / 16px / 20px / 28px / 40px
                xxs: ['0.6875rem', { lineHeight: '1.35' }],
                tiny: ['0.75rem', { lineHeight: '1.35' }],
            },
            spacing: {
                // component dimensions from design tokens
                sidebar: '220px',
                player: '72px',
                toolbar: '48px',
                header: '52px',
                'row-d': 'var(--row-h)',
            },
            boxShadow: {
                'mx-sm': '0 1px 4px rgba(0,0,0,0.45), 0 1px 2px rgba(0,0,0,0.3)',
                'mx-md': '0 4px 12px rgba(0,0,0,0.55), 0 1px 4px rgba(0,0,0,0.4)',
                'mx-lg': '0 8px 32px rgba(0,0,0,0.70), 0 2px 8px rgba(0,0,0,0.5)',
                'mx-glow': '0 0 0 1px rgb(var(--amber-rgb)), 0 0 12px rgb(var(--amber-rgb) / 0.20)',
                'mx-glow-sm': '0 0 6px rgb(var(--amber-rgb) / 0.20)',
            },
            borderRadius: {
                // Stock scale through vars so a theme can flatten every card at once.
                md: 'var(--radius-md, 0.375rem)',
                lg: 'var(--radius-lg, 0.5rem)',
                xl: 'var(--radius-xl, 0.75rem)',
                '2xl': 'var(--radius-2xl, 1rem)',
                '3xl': 'var(--radius-3xl, 1.5rem)',
                'mx-xs': 'var(--radius-mx-xs)',
                'mx-sm': 'var(--radius-mx-sm)',
                'mx-md': 'var(--radius-mx-md)',
                'mx-lg': 'var(--radius-mx-lg)',
                'mx-xl': 'var(--radius-mx-xl)',
            },
            transitionTimingFunction: {
                mx: 'cubic-bezier(0.2, 0, 0, 1)',
                'mx-spring': 'cubic-bezier(0.34, 1.56, 0.64, 1)',
            },
            animation: {
                'fade-in': 'fadeIn 0.4s ease-out',
                'slide-up': 'slideUp 0.4s cubic-bezier(0.16, 1, 0.3, 1)',
                blob: 'blob 7s infinite',
                'bar-bounce': 'barBounce 0.8s ease-in-out infinite alternate',
            },
            keyframes: {
                fadeIn: {
                    '0%': { opacity: '0', transform: 'translateY(10px)' },
                    '100%': { opacity: '1', transform: 'translateY(0)' },
                },
                slideUp: {
                    '0%': { opacity: '0', transform: 'translateY(20px)' },
                    '100%': { opacity: '1', transform: 'translateY(0)' },
                },
                blob: {
                    '0%': { transform: 'translate(0px, 0px) scale(1)' },
                    '33%': { transform: 'translate(30px, -50px) scale(1.1)' },
                    '66%': { transform: 'translate(-20px, 20px) scale(0.9)' },
                    '100%': { transform: 'translate(0px, 0px) scale(1)' },
                },
                barBounce: {
                    '0%': { transform: 'scaleY(0.4)' },
                    '100%': { transform: 'scaleY(1)' },
                },
            },
        },
    },
    plugins: [plugin(({ addBase }) => addBase({ ':root': paletteVars }))],
};
