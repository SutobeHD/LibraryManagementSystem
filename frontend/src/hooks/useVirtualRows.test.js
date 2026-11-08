/**
 * Range math of the TrackTable row windowing (computeVirtualRange).
 * node --import ./frontend/src/audio/dawState/dawReducer.test.resolver.mjs --test frontend/src/hooks/useVirtualRows.test.js
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
    computeVirtualRange,
    TRACK_ROW_HEIGHT_PX,
    VIRTUAL_OVERSCAN_ROWS,
} from './useVirtualRows.js';

const RH = 20;

test('empty list mounts nothing', () => {
    for (const rowCount of [0, -1, undefined, Number.NaN]) {
        assert.deepEqual(
            computeVirtualRange({ rowCount, rowHeight: RH, viewTop: 0, viewBottom: 500 }),
            { start: 0, end: 0, offsetTop: 0, offsetBottom: 0, totalHeight: 0 }
        );
    }
});

test('top of the list: visible rows + overscan below, no spacer above', () => {
    const r = computeVirtualRange({
        rowCount: 20000,
        rowHeight: RH,
        viewTop: 0,
        viewBottom: 400,
        overscan: 10,
    });
    assert.equal(r.start, 0);
    assert.equal(r.end, 30); // rows 0..19 visible + 10
    assert.equal(r.offsetTop, 0);
    assert.equal(r.offsetBottom, (20000 - 30) * RH);
    assert.equal(r.totalHeight, 20000 * RH);
});

test('mid-list: overscan on both sides, spacers add up to the full height', () => {
    const r = computeVirtualRange({
        rowCount: 20000,
        rowHeight: RH,
        viewTop: 2000,
        viewBottom: 2400,
        overscan: 10,
    });
    assert.equal(r.start, 90); // first visible 100
    assert.equal(r.end, 130); // last visible 119
    assert.equal(r.offsetTop, 90 * RH);
    assert.equal(r.offsetTop + (r.end - r.start) * RH + r.offsetBottom, r.totalHeight);
});

test('partially visible edge rows count as visible', () => {
    const r = computeVirtualRange({
        rowCount: 100,
        rowHeight: RH,
        viewTop: 2005,
        viewBottom: 2401,
        overscan: 0,
    });
    assert.equal(r.start, 100 - 1); // clamped: row 100 does not exist
    const mid = computeVirtualRange({
        rowCount: 1000,
        rowHeight: RH,
        viewTop: 2005,
        viewBottom: 2401,
        overscan: 0,
    });
    assert.equal(mid.start, 100);
    assert.equal(mid.end, 121); // row 120 shows its first pixel
});

test('mounted row count stays viewport + 2*overscan regardless of list size', () => {
    for (const rowCount of [1000, 20000, 50000]) {
        const r = computeVirtualRange({
            rowCount,
            rowHeight: 45,
            viewTop: 45 * 500,
            viewBottom: 45 * 500 + 900,
            overscan: VIRTUAL_OVERSCAN_ROWS,
        });
        assert.equal(r.end - r.start, 20 + 2 * VIRTUAL_OVERSCAN_ROWS);
    }
});

test('bottom of the list clamps end and leaves no bottom spacer', () => {
    const r = computeVirtualRange({
        rowCount: 500,
        rowHeight: RH,
        viewTop: 500 * RH - 400,
        viewBottom: 500 * RH,
        overscan: 10,
    });
    assert.equal(r.end, 500);
    assert.equal(r.offsetBottom, 0);
    assert.equal(r.start, 500 - 20 - 10);
});

test('view past the end (scrollTop not yet clamped) still mounts the tail', () => {
    const r = computeVirtualRange({
        rowCount: 50,
        rowHeight: RH,
        viewTop: 99999,
        viewBottom: 100399,
        overscan: 5,
    });
    assert.equal(r.end, 50);
    assert.ok(r.start < r.end);
});

test('view above row 0 (sticky header, table further down a page)', () => {
    const r = computeVirtualRange({
        rowCount: 100,
        rowHeight: RH,
        viewTop: -300,
        viewBottom: 100,
        overscan: 2,
    });
    assert.equal(r.start, 0);
    assert.equal(r.end, 7); // rows 0..4 visible + 2
});

test('align=2 keeps start even so nth-child striping does not flip', () => {
    for (let top = 0; top < 2000; top += 7) {
        const r = computeVirtualRange({
            rowCount: 1000,
            rowHeight: RH,
            viewTop: top,
            viewBottom: top + 300,
            overscan: 3,
            align: 2,
        });
        assert.equal(r.start % 2, 0, `start ${r.start} at top ${top}`);
        assert.ok(r.start <= Math.floor(top / RH) - 3 || r.start === 0);
        assert.equal(r.offsetTop, r.start * RH);
    }
});

test('bad row height falls back to the default estimate', () => {
    const r = computeVirtualRange({ rowCount: 10, rowHeight: 0, viewTop: 0, viewBottom: 100 });
    assert.equal(r.totalHeight, 10 * TRACK_ROW_HEIGHT_PX);
});

test('fractional pitch (border-collapse rows) keeps spacer math consistent', () => {
    const rh = 25.5;
    const r = computeVirtualRange({
        rowCount: 20000,
        rowHeight: rh,
        viewTop: 123456,
        viewBottom: 124256,
        overscan: 10,
        align: 2,
    });
    assert.ok(
        Math.abs(r.offsetTop + (r.end - r.start) * rh + r.offsetBottom - r.totalHeight) < 1e-6
    );
    assert.ok(r.start * rh <= 123456 && 123456 < r.end * rh);
});
