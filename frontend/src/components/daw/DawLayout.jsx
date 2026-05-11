/**
 * DawLayout — Slot-style layout shell for the DJ Edit DAW.
 *
 * ┌──────────────────────────────────────────────────┐
 * │  toolbar                                          │
 * ├──────────────────────────────────────────────────┤
 * │  overview  (mini-map; always shown)              │
 * ├──────────────────────────────────────────────────┤
 * │  timeline (when activeTrack)                      │
 * │    or                                             │
 * │  emptyState (when !activeTrack)                   │
 * │      scrollbar (absolutely positioned at bottom)  │
 * ├──────────────────────────────────────────────────┤
 * │  controlStrip                                     │
 * ├──────────────────────────────────────────────────┤
 * │  browser (collapsible)                            │
 * └──────────────────────────────────────────────────┘
 *
 * Pure presentational. Receives nodes as props (slot pattern) — does NOT
 * render any DAW-specific logic, ref, or state.
 */
import React from 'react';
import { Music } from 'lucide-react';

export default function DawLayout({
    toolbar,
    overview,
    timeline,
    scrollbar,
    controlStrip,
    browser,
    exportModal,
    fileInput,
    activeTrack,
    isLibraryCollapsed,
    onOpen,
}) {
    return (
        <div className="flex flex-col h-full bg-mx-deepest text-white overflow-hidden">
            {/* Top Bar: Project Header */}
            {toolbar}

            {/* Middle: Overview + Timeline Area */}
            <div className="flex-1 flex flex-col overflow-hidden relative min-h-0">
                {/* Waveform Overview Mini-Map (always shown, placeholder when no track) */}
                {overview}

                {activeTrack ? (
                    // min-h-0 lets this flex child shrink/grow correctly so
                    // DawTimeline's ResizeObserver picks up the real available
                    // height instead of staying pinned at its default.
                    <div className="flex-1 relative min-h-0">
                        {timeline}
                        {/* Scrollbar Overlay at bottom of timeline area */}
                        <div className="absolute bottom-0 left-0 right-0 z-10">
                            {scrollbar}
                        </div>
                    </div>
                ) : (
                    /* Empty State */
                    <div className="flex-1 flex flex-col items-center justify-center bg-mx-deepest/50">
                        <Music size={48} className="text-slate-800 mb-4" />
                        <h2 className="text-lg font-semibold text-ink-muted">No Project Loaded</h2>
                        <p className="text-sm text-ink-placeholder mt-2 mb-6">Select a track from the library below to start editing</p>
                        <div className="flex gap-3">
                            <button
                                onClick={onOpen}
                                className="px-4 py-2 bg-mx-card hover:bg-mx-hover rounded-lg text-sm text-white transition-colors border border-white/5"
                            >
                                Open Project
                            </button>
                        </div>
                    </div>
                )}
            </div>

            {/* Control Strip (Transport + Tools + Cues) */}
            {controlStrip}

            {/* Bottom: Library Browser (Collapsible/Resizable) */}
            <div
                className={`border-t border-white/10 relative z-20 transition-all duration-300 ease-in-out shrink-0 overflow-hidden ${isLibraryCollapsed ? 'h-[32px]' : 'h-[240px]'
                    }`}
            >
                <div className="h-full w-full">
                    {browser}
                </div>
            </div>

            {/* Export Modal */}
            {exportModal}

            {/* Hidden File Input for Open Dialog */}
            {fileInput}
        </div>
    );
}
