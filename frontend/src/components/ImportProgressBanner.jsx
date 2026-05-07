/**
 * Sticky progress banner — visible on every screen while local-file or
 * SoundCloud imports are running. Auto-hides when nothing is active.
 *
 * Polls /api/import/tasks + /api/soundcloud/tasks every 1.5s and renders
 *   • aggregate progress bar (% of currently active tasks completed)
 *   • current track filename + per-task stage
 *   • click → Sidebar → Sync → Downloads (full Import Manager view)
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Loader2, CheckCircle, AlertTriangle, X, ChevronRight } from 'lucide-react';
import api from '../api/api';

const ACTIVE_STATES = new Set([
    'Queued', 'Starting', 'Resolving', 'Downloading', 'Downloaded',
    'Analyzing', 'Importing', 'ANLZ', 'Sorting',
]);
const FAIL_STATES = new Set(['Failed', 'Error', 'Analysis Failed']);

const ImportProgressBanner = ({ onOpenManager }) => {
    const [importTasks, setImportTasks] = useState({});
    const [scTasks, setScTasks] = useState({});
    const [dismissed, setDismissed] = useState(false);

    useEffect(() => {
        const tick = async () => {
            try {
                const [imp, sc] = await Promise.all([
                    api.get('/api/import/tasks').catch(() => ({ data: {} })),
                    api.get('/api/soundcloud/tasks').catch(() => ({ data: {} })),
                ]);
                setImportTasks(imp.data || {});
                setScTasks(sc.data || {});
            } catch (e) { /* ignore */ }
        };
        tick();
        const t = setInterval(tick, 1500);
        return () => clearInterval(t);
    }, []);

    const stats = useMemo(() => {
        const all = [
            ...Object.values(importTasks).map(t => ({ ...t, _src: 'import' })),
            ...Object.values(scTasks).map(t => ({ ...t, _src: 'sc' })),
        ];
        const total = all.length;
        const active = all.filter(t => ACTIVE_STATES.has(t.status));
        const done = all.filter(t => t.status === 'Completed' || t.status === 'Linked' || t.status === 'Skipped');
        const failed = all.filter(t => FAIL_STATES.has(t.status));
        const inflight = active[0] || null;
        return { total, activeCount: active.length, doneCount: done.length, failedCount: failed.length, inflight };
    }, [importTasks, scTasks]);

    // Reset dismiss when a new import starts
    useEffect(() => {
        if (stats.activeCount > 0) setDismissed(false);
    }, [stats.activeCount]);

    if (dismissed) return null;
    if (stats.activeCount === 0) {
        // Briefly show "All done" toast-style banner if anything finished recently
        return null;
    }

    const overallPct = stats.total > 0
        ? Math.round((stats.doneCount / stats.total) * 100)
        : 0;

    return (
        <div
            className="fixed bottom-4 left-1/2 -translate-x-1/2 z-[80] w-[680px] max-w-[92vw]
                       bg-mx-shell/95 border border-amber2/40 rounded-2xl shadow-2xl backdrop-blur-xl
                       px-4 py-3 animate-fade-in cursor-pointer hover:bg-mx-shell transition-colors"
            onClick={() => onOpenManager && onOpenManager()}
            title="Klicken: Import Manager öffnen"
        >
            <div className="flex items-center gap-3">
                <Loader2 size={18} className="text-amber2 animate-spin shrink-0" />
                <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-3 mb-1">
                        <span className="text-sm font-bold text-white">
                            Import läuft —{' '}
                            <span className="text-amber2 font-mono">
                                {stats.doneCount}/{stats.total}
                            </span>{' '}
                            <span className="text-ink-muted text-[11px] font-normal">
                                ({stats.activeCount} aktiv{stats.failedCount ? `, ${stats.failedCount} Fehler` : ''})
                            </span>
                        </span>
                        <div className="flex items-center gap-2 shrink-0">
                            <span className="font-mono text-xs text-amber2">{overallPct}%</span>
                            <button
                                onClick={(e) => { e.stopPropagation(); setDismissed(true); }}
                                className="p-1 rounded hover:bg-white/10 text-ink-muted hover:text-white"
                                title="Schließen"
                            >
                                <X size={12} />
                            </button>
                            <ChevronRight size={14} className="text-ink-muted" />
                        </div>
                    </div>

                    {/* Aggregate progress bar */}
                    <div className="w-full h-1 bg-white/5 rounded-full overflow-hidden">
                        <div
                            className="h-full bg-gradient-to-r from-amber2 via-orange-400 to-amber2 transition-all"
                            style={{ width: `${overallPct}%` }}
                        />
                    </div>

                    {/* Currently active track */}
                    {stats.inflight && (
                        <div className="flex items-center gap-2 mt-2 text-[11px] text-ink-muted truncate">
                            <span className={`px-1.5 py-0.5 rounded text-[8px] font-bold uppercase tracking-wider shrink-0 ${
                                stats.inflight._src === 'import'
                                    ? 'bg-blue-500/20 text-blue-300 border border-blue-500/30'
                                    : 'bg-orange-500/20 text-orange-300 border border-orange-500/30'
                            }`}>
                                {stats.inflight._src === 'import' ? 'Lokal' : 'SC'}
                            </span>
                            <span className="text-amber2 font-mono shrink-0">{stats.inflight.status}</span>
                            <span className="text-ink-placeholder">·</span>
                            <span className="truncate">{stats.inflight.title || stats.inflight.file_path}</span>
                            {(stats.inflight.bpm || stats.inflight.key) && (
                                <>
                                    <span className="text-ink-placeholder shrink-0">·</span>
                                    <span className="font-mono text-purple-300 shrink-0">
                                        {stats.inflight.bpm ? `${Math.round(stats.inflight.bpm)} BPM` : ''}
                                        {stats.inflight.bpm && stats.inflight.key ? ' · ' : ''}
                                        {stats.inflight.key || ''}
                                    </span>
                                </>
                            )}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
};

export default ImportProgressBanner;
