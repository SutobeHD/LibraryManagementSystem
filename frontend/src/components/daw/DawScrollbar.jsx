
import React, { useRef, useEffect, useCallback } from 'react';
import { useMemo } from 'react';

/**
 * DawScrollbar — Horizontal scrollbar synchronized with the timeline
 */
const DawScrollbar = React.memo(({ state, dispatch }) => {
    const { totalDuration, zoom, scrollX } = state;
    const containerRef = useRef(null);
    const thumbRef = useRef(null);

    // Calculate total width of timeline in pixels
    const totalWidth = useMemo(() => totalDuration * zoom, [totalDuration, zoom]);

    // Calculate viewport width (approximation, as actual width is in canvas)
    // We can assume viewport is container width.
    // If totalWidth < viewport, no scrollbar needed?
    // But we need to allow scrolling negative margin?
    // Let's rely on container width.

    const containerWidth = containerRef.current?.clientWidth || 1000;
    // This is tricky because containerRef is null on first render.
    // We can use 100% width.

    // Instead of custom thumb, let's use native scrollbar behavior with a dummy spacer?
    // Or a custom UI range slider?
    // Native scrollbar is easiest for user interaction (drag, click track).

    const viewportWidth = window.innerWidth; // Rough estimate or pass from parent?
    // Using a spacer div width = totalDuration * zoom + padding

    const handleScroll = useCallback((e) => {
        const newScrollX = e.target.scrollLeft - 20; // Adjust for margin?
        // Actually, scrollX in state corresponds to pixels.
        // If we set scrollLeft, we dispatch SET_SCROLL_X.
        dispatch({ type: 'SET_SCROLL_X', payload: e.target.scrollLeft });
    }, [dispatch]);

    useEffect(() => {
        if (containerRef.current) {
            containerRef.current.scrollLeft = Math.max(0, scrollX);
        }
    }, [scrollX]);

    return (
        <div
            ref={containerRef}
            onScroll={handleScroll}
            className="w-full h-4 bg-slate-900 border-t border-white/5 overflow-x-auto overflow-y-hidden custom-scrollbar"
            style={{
                scrollbarWidth: 'auto',
                scrollbarColor: '#475569 #0f172a'
            }}
        >
            <div style={{ width: Math.max(10, totalWidth + 400), height: '1px' }} />
        </div>
    );
});

DawScrollbar.displayName = 'DawScrollbar';
export default DawScrollbar;
