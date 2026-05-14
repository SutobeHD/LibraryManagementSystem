import { useEffect, useRef, useState } from 'react';

/**
 * Windowing for long scrollable lists. Renders only the rows in (and near)
 * the viewport; the rest are accounted for with top/bottom spacer height.
 *
 * The track table at 100k+ rows otherwise mounts 100k+ <tr> nodes and
 * freezes the browser on first paint and on every sort. Assumes a fixed
 * row height — the table enforces it per <tr>.
 *
 * @param {object}  opts
 * @param {number}  opts.rowCount   total number of rows
 * @param {number}  opts.rowHeight  fixed per-row height in px
 * @param {number} [opts.overscan]  extra rows rendered above/below the viewport
 * @returns {{ scrollRef, startIndex, endIndex, padTop, padBottom }}
 */
export function useVirtualRows({ rowCount, rowHeight, overscan = 8 }) {
  const scrollRef = useRef(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportHeight, setViewportHeight] = useState(0);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return undefined;

    const sync = () => {
      setScrollTop(el.scrollTop);
      setViewportHeight(el.clientHeight);
    };
    sync();

    el.addEventListener('scroll', sync, { passive: true });
    const ro = new ResizeObserver(sync);
    ro.observe(el);
    return () => {
      el.removeEventListener('scroll', sync);
      ro.disconnect();
    };
  }, []);

  // Re-sync against the DOM when the row count changes — the browser has
  // already clamped scrollTop if the content shrank (e.g. after a filter).
  useEffect(() => {
    const el = scrollRef.current;
    if (el) setScrollTop(el.scrollTop);
  }, [rowCount]);

  const safeRowHeight = rowHeight > 0 ? rowHeight : 1;
  const maxStart = Math.max(0, rowCount - 1);
  const startIndex = Math.min(
    maxStart,
    Math.max(0, Math.floor(scrollTop / safeRowHeight) - overscan),
  );
  const visibleCount = Math.ceil(viewportHeight / safeRowHeight) + overscan * 2;
  const endIndex = Math.min(rowCount, startIndex + visibleCount);
  const padTop = startIndex * safeRowHeight;
  const padBottom = Math.max(0, (rowCount - endIndex) * safeRowHeight);

  return { scrollRef, startIndex, endIndex, padTop, padBottom };
}
