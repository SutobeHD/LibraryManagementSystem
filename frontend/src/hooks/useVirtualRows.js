import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';

/**
 * Row windowing for long tables: only the rows in (and near) the viewport are
 * mounted; spacers above and below stand in for the rest. Hand-rolled — no
 * windowing library in the deps.
 *
 * Rows are assumed to share one height. The hook measures the real row pitch
 * from the mounted rows (it differs per skin and column set) and uses the
 * estimate below only until the first rows exist.
 */

/** Row pitch of the default skin before anything is measured: 36px art + 2*4px padding + 1px border. */
export const TRACK_ROW_HEIGHT_PX = 45;

/** Rows mounted beyond each viewport edge — keeps fast wheel scrolling from showing blank space. */
export const VIRTUAL_OVERSCAN_ROWS = 10;

// Sub-pixel jitter between measurements must not re-layout every spacer.
const ROW_HEIGHT_TOLERANCE_PX = 0.5;

// Viewport guess for the very first render, before any layout exists.
const FALLBACK_VIEWPORT_PX = 1000;

const EMPTY_RANGE = Object.freeze({
    start: 0,
    end: 0,
    offsetTop: 0,
    offsetBottom: 0,
    totalHeight: 0,
});

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

/**
 * Which rows to mount for a viewport.
 *
 * `viewTop` / `viewBottom` are px relative to the top edge of row 0 (negative =
 * above the first row). `align` rounds `start` down to a multiple of itself, so
 * `:nth-child` striping keeps its parity while the window slides.
 *
 * @returns {{start: number, end: number, offsetTop: number, offsetBottom: number, totalHeight: number}}
 *   rows `[start, end)`; spacer heights above / below them; height of all rows.
 */
export function computeVirtualRange({
    rowCount,
    rowHeight,
    viewTop,
    viewBottom,
    overscan = VIRTUAL_OVERSCAN_ROWS,
    align = 1,
}) {
    if (!(rowCount > 0)) return EMPTY_RANGE;
    const rh = rowHeight > 0 ? rowHeight : TRACK_ROW_HEIGHT_PX;
    const pad = Math.max(0, Math.floor(overscan) || 0);
    const step = Math.max(1, Math.floor(align) || 1);
    const last = rowCount - 1;

    const firstVisible = clamp(Math.floor(viewTop / rh), 0, last);
    const lastVisible = clamp(Math.ceil(viewBottom / rh) - 1, firstVisible, last);

    let start = Math.max(0, firstVisible - pad);
    start -= start % step;
    const end = Math.min(rowCount, lastVisible + 1 + pad);

    return {
        start,
        end,
        offsetTop: start * rh,
        offsetBottom: (rowCount - end) * rh,
        totalHeight: rowCount * rh,
    };
}

/**
 * @param {object} opts
 * @param {number} opts.rowCount       total rows
 * @param {number} [opts.overscan]     rows beyond each viewport edge
 * @param {number} [opts.align]        `start` granularity (2 keeps even/odd striping stable)
 * @param {*}      [opts.resetKey]     scroll back to the top when this changes (list identity);
 *                                     row edits and re-fetches of the same list keep the position
 * @returns {{scrollRef, bodyRef, start, end, offsetTop, offsetBottom, totalHeight, rowHeight}}
 *   `scrollRef` → the scroll container, `bodyRef` → the element whose children are exactly
 *   the mounted rows (a `<tbody>`), spacers rendered outside it.
 */
export function useVirtualRows({
    rowCount,
    overscan = VIRTUAL_OVERSCAN_ROWS,
    align = 1,
    resetKey,
}) {
    const scrollRef = useRef(null);
    const bodyRef = useRef(null);
    const [view, setView] = useState(() => ({
        top: 0,
        bottom: typeof window === 'undefined' ? FALLBACK_VIEWPORT_PX : window.innerHeight,
        rowHeight: TRACK_ROW_HEIGHT_PX,
    }));

    const range = computeVirtualRange({
        rowCount,
        rowHeight: view.rowHeight,
        viewTop: view.top,
        viewBottom: view.bottom,
        overscan,
        align,
    });

    // What the DOM shows right now — the scroll handler reads geometry against it.
    const committed = useRef({ range, view, rowCount, overscan, align });
    useLayoutEffect(() => {
        committed.current = { range, view, rowCount, overscan, align };
    });

    const sync = useCallback(() => {
        const body = bodyRef.current;
        if (!body) return;
        const cur = committed.current;

        let rowHeight = cur.view.rowHeight;
        const rows = body.children;
        if (rows.length >= 2) {
            const first = rows[0].getBoundingClientRect().top;
            const lastTop = rows[rows.length - 1].getBoundingClientRect().top;
            const pitch = (lastTop - first) / (rows.length - 1);
            if (pitch > 0) rowHeight = pitch;
        } else if (rows.length === 1) {
            const h = rows[0].getBoundingClientRect().height;
            if (h > 0) rowHeight = h;
        }
        if (Math.abs(rowHeight - cur.view.rowHeight) < ROW_HEIGHT_TOLERANCE_PX) {
            rowHeight = cur.view.rowHeight;
        }

        // Row 0 sits one top-spacer above the first mounted row.
        const row0Top = body.getBoundingClientRect().top - cur.range.offsetTop;
        // Clip to the container AND the window: if the container is not height-bounded
        // (an ancestor scrolls instead), the window still caps how many rows mount.
        const scroller = scrollRef.current;
        const box = scroller ? scroller.getBoundingClientRect() : null;
        const clipTop = Math.max(box ? box.top : 0, 0);
        const clipBottom = Math.min(box ? box.bottom : window.innerHeight, window.innerHeight);
        const next = { top: clipTop - row0Top, bottom: clipBottom - row0Top, rowHeight };

        const nextRange = computeVirtualRange({
            rowCount: cur.rowCount,
            rowHeight,
            viewTop: next.top,
            viewBottom: next.bottom,
            overscan: cur.overscan,
            align: cur.align,
        });
        if (
            nextRange.start !== cur.range.start ||
            nextRange.end !== cur.range.end ||
            rowHeight !== cur.view.rowHeight
        ) {
            setView(next);
        }
    }, []);

    useEffect(() => {
        // Scroll events don't bubble, but a window capture listener sees them all: the
        // container's own and those of any scrolling ancestor.
        const scrollOpts = { passive: true, capture: true };
        window.addEventListener('scroll', sync, scrollOpts);
        window.addEventListener('resize', sync, { passive: true });
        // Container resizes, and the table itself (skin switch / column toggle change row height).
        const ro = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(sync);
        if (ro && scrollRef.current) ro.observe(scrollRef.current);
        const table = bodyRef.current?.parentElement;
        if (ro && table) ro.observe(table);
        return () => {
            window.removeEventListener('scroll', sync, scrollOpts);
            window.removeEventListener('resize', sync, { passive: true });
            ro?.disconnect();
        };
    }, [sync]);

    // The browser clamps scrollTop when the list (or the measured row height) shrinks;
    // re-read geometry before paint instead of waiting for a scroll event.
    useLayoutEffect(() => {
        sync();
    }, [rowCount, view.rowHeight, sync]);

    const lastResetKey = useRef(resetKey);
    useLayoutEffect(() => {
        if (Object.is(lastResetKey.current, resetKey)) return;
        lastResetKey.current = resetKey;
        if (scrollRef.current) scrollRef.current.scrollTop = 0;
        sync();
    }, [resetKey, sync]);

    return { scrollRef, bodyRef, ...range, rowHeight: view.rowHeight };
}
