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
export default {
    content: [
        "./index.html",
        "./src/**/*.{js,ts,jsx,tsx}",
    ],
    theme: {
        extend: {
            colors: {
                // ── Melodex base palette ──────────────────────────────
                mx: {
                    deepest: '#0D0F14',
                    shell:   '#13161D',
                    panel:   '#1A1E27',
                    surface: '#1E2230',
                    card:    '#222736',
                    hover:   '#272C3A',
                    selected:'#2A3045',
                    input:   '#181B24',
                },
                // borders
                line: {
                    subtle:      '#2A2F3E',
                    DEFAULT:     '#353C50',
                    interactive: '#404760',
                },
                // foreground / text
                ink: {
                    primary:     '#F0F2F7',
                    secondary:   '#9BA3B8',
                    muted:       '#5C6478',
                    placeholder: '#3E4558',
                    inverse:     '#0D0F14',
                },
                // amber accent
                amber2: {
                    DEFAULT: '#E8A42A',
                    hover:   '#F5C860',
                    press:   '#C8841A',
                    dim:     '#7A5215',
                },
                // semantic
                ok:   '#3DD68C',
                bad:  '#E85C4A',
                info: '#4A9EE8',

                // ── Legacy aliases (don't break existing code) ───────
                djdark: '#0D0F14',
                djgray: '#1A1E27',
                neon: {
                    blue:   '#4A9EE8',
                    purple: '#E8A42A',
                    pink:   '#F5C860',
                },
            },
            fontFamily: {
                sans: ['"DM Sans"', 'Inter', 'system-ui', 'sans-serif'],
                mono: ['"JetBrains Mono"', '"Fira Mono"', 'monospace'],
            },
            fontSize: {
                // 11px / 12px / 14px / 16px / 20px / 28px / 40px
                'xxs':  ['0.6875rem', { lineHeight: '1.35' }],
                'tiny': ['0.75rem',   { lineHeight: '1.35' }],
            },
            spacing: {
                // component dimensions from design tokens
                'sidebar': '220px',
                'player':  '72px',
                'toolbar': '48px',
                'header':  '52px',
                'row-d':   '36px',
            },
            boxShadow: {
                'mx-sm':   '0 1px 4px rgba(0,0,0,0.45), 0 1px 2px rgba(0,0,0,0.3)',
                'mx-md':   '0 4px 12px rgba(0,0,0,0.55), 0 1px 4px rgba(0,0,0,0.4)',
                'mx-lg':   '0 8px 32px rgba(0,0,0,0.70), 0 2px 8px rgba(0,0,0,0.5)',
                'mx-glow': '0 0 0 1px #E8A42A, 0 0 12px rgba(232,164,42,0.20)',
                'mx-glow-sm': '0 0 6px rgba(232,164,42,0.20)',
            },
            borderRadius: {
                'mx-xs': '2px',
                'mx-sm': '4px',
                'mx-md': '6px',
                'mx-lg': '8px',
                'mx-xl': '12px',
            },
            transitionTimingFunction: {
                'mx': 'cubic-bezier(0.2, 0, 0, 1)',
                'mx-spring': 'cubic-bezier(0.34, 1.56, 0.64, 1)',
            },
            animation: {
                'fade-in': 'fadeIn 0.4s ease-out',
                'slide-up': 'slideUp 0.4s cubic-bezier(0.16, 1, 0.3, 1)',
                'blob': 'blob 7s infinite',
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
                    '0%':   { transform: 'translate(0px, 0px) scale(1)' },
                    '33%':  { transform: 'translate(30px, -50px) scale(1.1)' },
                    '66%':  { transform: 'translate(-20px, 20px) scale(0.9)' },
                    '100%': { transform: 'translate(0px, 0px) scale(1)' },
                },
                barBounce: {
                    '0%':   { transform: 'scaleY(0.4)' },
                    '100%': { transform: 'scaleY(1)' },
                },
            },
        },
    },
    plugins: [],
}
