/**
 * DawScrollbar — Horizontal scrollbar synchronized with the timeline
 *
 * Critical: avoids the feedback loop where programmatically setting
 * `scrollLeft` triggers an `onScroll` event that re-dispatches SET_SCROLL_X.
 * We use a `programmaticScroll` ref to suppress events fired by our own writes.
 */

import React, { useRef, useEffect, useCallback, useMemo } from 'react';

const DawScrollbar = React.memo(({ state, dispatch }) => {
    const { totalDuration, zoom, scrollX } = state;
    const containerRef = useRef(null);
    const programmaticScroll = useRef(false);
    const rafRef = useRef(null);

    // Total content width in pixels (timeline pixels match scrollbar pixels 1:1)
    const totalWidth = useMemo(
        () => Math.max(10, (totalDuration || 0) * (zoom || 100) + 200),
        [totalDuration, zoom]
    );

    // ── Sync state.scrollX → DOM scrollLeft (without triggering onScroll loop) ──
    useEffect(() => {
        const el = containerRef.current;
        if (!el) return;
        const target = Math.max(0, Math.round(scrollX || 0));
        if (Math.abs(el.scrollLeft - target) < 1) return; // already in sync
        programmaticScroll.current = true;
        el.scrollLeft = target;
        // Release the flag on the next frame, after the scroll event has fired
        requestAnimationFrame(() => { programmaticScroll.current = false; });
    }, [scrollX]);

    // ── User scroll → dispatch (debounced via rAF for smooth UI) ──
    const handleScroll = useCallback((e) => {
        if (programmaticScroll.current) return; // ignore our own writes
        const newScrollX = e.target.scrollLeft;
        if (rafRef.current) cancelAnimationFrame(rafRef.current);
        rafRef.current = requestAnimationFrame(() => {
            dispatch({ type: 'SET_SCROLL_X', payload: newScrollX });
        });
    }, [dispatch]);

    // Cleanup pending rAF on unmount
    useEffect(() => () => {
        if (rafRef.current) cancelAnimationFrame(rafRef.current);
    }, []);

    return (
        <div
            ref={containerRef}
            onScroll={handleScroll}
            className="w-full h-3 bg-mx-deepest border-t border-line-subtle overflow-x-auto overflow-y-hidden daw-scrollbar"
            style={{
                scrollbarWidth: 'thin',
                scrollbarColor: 'var(--amber) transparent',
            }}
        >
            <div style={{ width: totalWidth, height: '1px' }} />
        </div>
    );
});

DawScrollbar.displayName = 'DawScrollbar';
export default DawScrollbar;
