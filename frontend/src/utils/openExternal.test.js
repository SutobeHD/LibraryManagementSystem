// node:test — `node --test frontend/src/utils/openExternal.test.js`
//
// Pins the last gate before the OS opens a link (Threats T13 / T17 in
// docs/research/implement/inprogress_library-artist-hub.md): only a plain http(s) URL
// reaches the opener, and each runtime takes its own path.

import assert from 'node:assert/strict';
import { test } from 'node:test';

import { openExternal, safeExternalUrl } from './openExternal.js';

test('plain http(s) profile links pass and are canonicalised', () => {
    assert.equal(
        safeExternalUrl('https://www.instagram.com/boysnoize'),
        'https://www.instagram.com/boysnoize'
    );
    assert.equal(safeExternalUrl('  https://ra.co/dj/boysnoize  '), 'https://ra.co/dj/boysnoize');
    assert.equal(safeExternalUrl('http://www.boysnoize.com'), 'http://www.boysnoize.com/');
});

test('script, file, credential and local links are refused', () => {
    for (const raw of [
        'javascript:alert(1)',
        'JavaScript:alert(1)',
        'data:text/html,<b>x</b>',
        'file:///C:/Windows/System32/calc.exe',
        '\\\\server\\share\\x.exe',
        'https://user:pw@instagram.com/x',
        'https://localhost/x',
        'https://[::1]/x',
        'https://exa mple.com',
        'mailto:someone@example.com',
        'https://example.com/\u0000',
        `https://${'a'.repeat(2100)}.com`,
        '',
        null,
        undefined,
        42,
    ]) {
        assert.equal(safeExternalUrl(raw), null, String(raw).slice(0, 40));
    }
});

test('an IP-literal host is refused in every spelling the URL parser folds to IPv4', () => {
    for (const raw of [
        'https://127.0.0.1/x',
        'http://192.168.1.10/',
        'https://0x7f.1/',
        'https://2130706433/',
        'https://1.2.3/',
        'https://localhost./x',
    ]) {
        assert.equal(safeExternalUrl(raw), null, raw);
    }
    assert.equal(safeExternalUrl('https://www.example.com./x'), 'https://www.example.com./x');
});

test('in Tauri the shell plugin opens it', async () => {
    const calls = [];
    const where = await openExternal('https://soundcloud.com/boysnoize', {
        isTauri: true,
        invoke: async (cmd, args) => calls.push([cmd, args]),
        windowOpen: () => assert.fail('window.open must not run in Tauri'),
    });
    assert.equal(where, 'system');
    assert.deepEqual(calls, [['plugin:shell|open', { path: 'https://soundcloud.com/boysnoize' }]]);
});

test('in the browser it opens a new tab', async () => {
    const opened = [];
    const where = await openExternal('https://soundcloud.com/boysnoize', {
        isTauri: false,
        invoke: async () => assert.fail('invoke must not run in the browser'),
        windowOpen: (href) => opened.push(href),
    });
    assert.equal(where, 'tab');
    assert.deepEqual(opened, ['https://soundcloud.com/boysnoize']);
});

test('an unsafe link is refused before any opener runs', async () => {
    await assert.rejects(
        openExternal('javascript:alert(1)', {
            isTauri: true,
            invoke: async () => assert.fail('must not invoke'),
            windowOpen: () => assert.fail('must not open'),
        }),
        /not a plain web address/
    );
});
