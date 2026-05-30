/**
 * shoot.mjs — automated page screenshots via headless Chrome + CDP.
 *
 * Drives the running frontend (Vite dev server on :5173) through every main
 * view and writes a PNG per view to tmp/shots/. Uses only Node built-ins
 * (global WebSocket + fetch, child_process) — no Playwright/Puppeteer dep.
 *
 * Why this exists: the app polls the backend continuously (heartbeat +
 * library-status) and runs canvas/RAF animations, so the generic
 * "wait for network-idle" screenshot tools time out. CDP's
 * Page.captureScreenshot just grabs the current frame — no idle wait.
 *
 * Prereqs: `npm run dev:full` (or preview servers) running, library loaded.
 * Usage:   node scripts/dev/shoot.mjs
 *          SHOOT_URL=http://127.0.0.1:5173/ node scripts/dev/shoot.mjs
 */
import { spawn } from 'node:child_process';
import { mkdtempSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const CHROME_CANDIDATES = [
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
];
const CHROME = CHROME_CANDIDATES.find(existsSync);
if (!CHROME) throw new Error('No Chrome/Edge found in the usual install paths.');

const URL = process.env.SHOOT_URL || 'http://127.0.0.1:5173/';
const PORT = Number(process.env.SHOOT_CDP_PORT || 9222);
const OUT = join(process.cwd(), 'tmp', 'shots');
mkdirSync(OUT, { recursive: true });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ── Navigation script: [label, clickRegexOrNull, settleMs] ──────────────────
// A null regex means "don't click, just settle + shoot" (used for the first
// shot after entering Live). Each step clicks a button whose text matches,
// waits, then screenshots.
const STEPS = [
    ['00-mode-select', null, 600],
    ['01-library-playlists', '/Rekordbox Live/i', 3500],
    ['02-library-artists', '/^Artists$/i', 1800],
    ['03-library-labels', '/^Labels$/i', 1800],
    ['04-library-albums', '/^Albums$/i', 1800],
    ['05-audio-import', '/^Audio Import$/i', 1500],
    ['06-ranking', '/^Ranking$/i', 1800],
    ['07-editor-studio', '/^Editor$/i', 3000],
    ['08-sync-usb-export', '/^Sync$/i', 2500],
    ['09-usb-settings', '/^USB Settings$/i', 3000],
    ['10-soundcloud', '/^SoundCloud$/i', 1800],
    ['11-sc-library', '/^SCloudLibrary$/i', 1800],
    ['12-downloads', '/^Downloads$/i', 1800],
    ['13-utilities', '/^Utilities$/i', 1800],
    ['14-insights', '/^Insights$/i', 2200],
];

async function getPageWsUrl() {
    for (let i = 0; i < 60; i++) {
        try {
            const targets = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json();
            const page = targets.find((t) => t.type === 'page' && t.webSocketDebuggerUrl);
            if (page) return page.webSocketDebuggerUrl;
        } catch {
            /* CDP endpoint not up yet */
        }
        await sleep(200);
    }
    throw new Error('Chrome CDP endpoint did not come up.');
}

function cdpClient(wsUrl) {
    const ws = new WebSocket(wsUrl);
    let nextId = 0;
    const pending = new Map();
    const ready = new Promise((res, rej) => {
        ws.addEventListener('open', () => res());
        ws.addEventListener('error', (e) => rej(e));
    });
    ws.addEventListener('message', (ev) => {
        const msg = JSON.parse(ev.data);
        if (msg.id && pending.has(msg.id)) {
            pending.get(msg.id)(msg);
            pending.delete(msg.id);
        }
    });
    const send = (method, params = {}) =>
        new Promise((res) => {
            const id = ++nextId;
            pending.set(id, res);
            ws.send(JSON.stringify({ id, method, params }));
        });
    return { ready, send, close: () => ws.close() };
}

async function main() {
    const profile = mkdtempSync(join(tmpdir(), 'shoot-profile-'));
    const chrome = spawn(
        CHROME,
        [
            '--headless=new',
            `--remote-debugging-port=${PORT}`,
            `--user-data-dir=${profile}`,
            '--window-size=1440,900',
            '--hide-scrollbars',
            '--no-first-run',
            '--no-default-browser-check',
            '--disable-extensions',
            'about:blank',
        ],
        { stdio: 'ignore' },
    );

    try {
        const wsUrl = await getPageWsUrl();
        const c = cdpClient(wsUrl);
        await c.ready;
        await c.send('Page.enable');
        await c.send('Runtime.enable');
        await c.send('Emulation.setDeviceMetricsOverride', {
            width: 1440,
            height: 900,
            deviceScaleFactor: 1,
            mobile: false,
        });
        await c.send('Page.navigate', { url: URL });
        await sleep(4000); // initial bundle load + library autoload

        const clickByText = (reLiteral) =>
            c.send('Runtime.evaluate', {
                expression: `(()=>{const b=[...document.querySelectorAll('button')].find(x=>${reLiteral}.test((x.textContent||'').trim()));if(b){b.click();return true}return false})()`,
                returnByValue: true,
            });

        const shoot = async (name) => {
            const { result } = await c.send('Page.captureScreenshot', { format: 'png', fromSurface: true });
            const file = join(OUT, `${name}.png`);
            writeFileSync(file, Buffer.from(result.data, 'base64'));
            console.log('shot:', file);
        };

        for (const [name, reLiteral, settle] of STEPS) {
            if (reLiteral) {
                const r = await clickByText(reLiteral);
                if (r?.result?.value === false) {
                    console.warn(`  (skip ${name}: no button matched ${reLiteral})`);
                    continue;
                }
            }
            await sleep(settle);
            await shoot(name);
        }

        c.close();
        console.log(`\nDone. ${STEPS.length} views → ${OUT}`);
    } finally {
        chrome.kill();
    }
}

main().catch((e) => {
    console.error('shoot failed:', e);
    process.exit(1);
});
