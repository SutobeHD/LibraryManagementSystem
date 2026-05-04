/**
 * DuplicateView — Acoustic Duplicate Finder & Merge UI
 *
 * Left panel: list of duplicate groups with similarity badge.
 * Right panel: horizontal cards per track in the group.
 * Master selection: radio button or "Auto" (highest bitrate).
 * Merge options: "Merge Play Counts" checkbox.
 * Confirm → POST /api/duplicates/merge.
 *
 * Scan flow:
 *   1. Load all library track paths
 *   2. POST /api/duplicates/scan → {job_id}
 *   3. Poll GET /api/duplicates/results?job_id=... until done
 *   4. Show groups
 *
 * Design: Melodex tokens (mx-*, ink-*, amber2, bad/ok).
 */

import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
    Copy, Check, AlertTriangle, Loader2, Music, ChevronRight,
    Trash2, Zap, RefreshCw, HardDrive, Activity,
} from 'lucide-react';
import api from '../api/api';
import toast from 'react-hot-toast';

const log = (level, msg, data) =>
    console[level]?.(`[DuplicateView] ${msg}`, data ?? '');

// ─────────────────────────────────────────────────────────────────────────────
//  Helpers
// ─────────────────────────────────────────────────────────────────────────────

const formatMb = (mb) => {
    if (mb == null) return '—';
    return mb >= 100 ? `${Math.round(mb)} MB` : `${mb.toFixed(1)} MB`;
};

const similarityColor = (sim) => {
    if (sim >= 0.95) return 'text-bad';
    if (sim >= 0.90) return 'text-amber2';
    return 'text-info';
};

const similarityLabel = (sim) => `${Math.round(sim * 100)}% match`;

// ─────────────────────────────────────────────────────────────────────────────
//  TrackCard — one card in the group detail panel
// ─────────────────────────────────────────────────────────────────────────────

/**
 * TrackCard — displays metadata for one track in a duplicate group.
 *
 * Props:
 *   track       — {path, title, artist, format, bitrate, size_mb, play_count}
 *   isMaster    — whether this track is the selected master (keep)
 *   onSelect    — called when the radio button is clicked
 */
const TrackCard = ({ track, isMaster, onSelect }) => (
    <div
        className={`flex-shrink-0 w-56 p-3 rounded-mx-md border transition-all cursor-pointer ${
            isMaster
                ? 'bg-amber2/5 border-amber2/40'
                : 'bg-mx-card border-line-subtle hover:border-line-default'
        }`}
        onClick={onSelect}
    >
        {/* Radio + Master badge */}
        <div className="flex items-center gap-2 mb-2.5">
            <div className={`w-3.5 h-3.5 rounded-full border-2 flex items-center justify-center ${
                isMaster ? 'border-amber2 bg-amber2' : 'border-line-default'
            }`}>
                {isMaster && <div className="w-1.5 h-1.5 rounded-full bg-mx-deepest" />}
            </div>
            <span className={`text-[10px] font-semibold uppercase tracking-wider ${isMaster ? 'text-amber2' : 'text-ink-muted'}`}>
                {isMaster ? 'Keep' : 'Remove'}
            </span>
        </div>

        {/* Track info */}
        <p className="text-[12px] font-semibold text-ink-primary truncate mb-0.5">
            {track.title || track.path?.split(/[\\/]/).pop() || '(untitled)'}
        </p>
        <p className="text-[10px] text-ink-muted truncate mb-2">
            {track.artist || '—'}
        </p>

        {/* Meta grid */}
        <div className="space-y-1 text-[10px] font-mono text-ink-secondary">
            <div className="flex justify-between">
                <span className="text-ink-muted">Format</span>
                <span>{track.format || '—'}</span>
            </div>
            <div className="flex justify-between">
                <span className="text-ink-muted">Bitrate</span>
                <span>{track.bitrate ? `${track.bitrate} kbps` : '—'}</span>
            </div>
            <div className="flex justify-between">
                <span className="text-ink-muted">Size</span>
                <span>{formatMb(track.size_mb)}</span>
            </div>
            <div className="flex justify-between">
                <span className="text-ink-muted">Plays</span>
                <span>{track.play_count ?? 0}</span>
            </div>
        </div>
    </div>
);

// ─────────────────────────────────────────────────────────────────────────────
//  GroupDetail — right panel
// ─────────────────────────────────────────────────────────────────────────────

/**
 * GroupDetail — right panel showing cards for all tracks in a duplicate group.
 *
 * Props:
 *   group           — {master, similarity, duplicates: [{path,...}]}
 *   onMergeSuccess  — called when merge completes successfully
 */
const GroupDetail = ({ group, onMergeSuccess }) => {
    const [masterPath, setMasterPath] = useState(() => {
        // Auto: pick highest bitrate
        const sorted = [...(group.duplicates || [])].sort(
            (a, b) => (b.bitrate || 0) - (a.bitrate || 0)
        );
        return sorted[0]?.path || group.master;
    });
    const [mergePlayCounts, setMergePlayCounts] = useState(true);
    const [merging, setMerging] = useState(false);
    const [merged, setMerged] = useState(false);

    // Reset when group changes
    useEffect(() => {
        const sorted = [...(group.duplicates || [])].sort(
            (a, b) => (b.bitrate || 0) - (a.bitrate || 0)
        );
        setMasterPath(sorted[0]?.path || group.master);
        setMerged(false);
    }, [group]);

    const handleAutoSelect = () => {
        const sorted = [...(group.duplicates || [])].sort(
            (a, b) => (b.bitrate || 0) - (a.bitrate || 0)
        );
        setMasterPath(sorted[0]?.path || group.master);
    };

    const handleMerge = async () => {
        const removePaths = (group.duplicates || [])
            .map(t => t.path)
            .filter(p => p !== masterPath);

        if (removePaths.length === 0) {
            toast.error('Nothing to remove — select a different master');
            return;
        }

        setMerging(true);
        log('info', 'merging', { masterPath, removePaths, mergePlayCounts });
        try {
            const res = await api.post('/api/duplicates/merge', {
                keep_path: masterPath,
                remove_paths: removePaths,
                merge_play_counts: mergePlayCounts,
            });
            if (res.data?.status !== 'ok') throw new Error(res.data?.message || 'Merge failed');

            const result = res.data.data;
            toast.success(`Merged — ${result.removed} duplicate(s) removed from library`);
            setMerged(true);
            onMergeSuccess?.();
            log('info', 'merge success', result);
        } catch (e) {
            log('error', 'merge failed', e);
            const msg = e?.response?.data?.detail || e.message || 'Unknown error';
            toast.error(`Merge failed: ${msg}`);
        } finally {
            setMerging(false);
        }
    };

    if (merged) {
        return (
            <div className="h-full flex flex-col items-center justify-center gap-3 text-ok">
                <Check size={36} />
                <p className="text-[14px] font-semibold">Group merged</p>
                <p className="text-tiny text-ink-muted">Duplicates removed from library</p>
            </div>
        );
    }

    return (
        <div className="h-full flex flex-col gap-4">
            {/* Header */}
            <div className="flex items-center justify-between">
                <div>
                    <p className="text-[13px] font-semibold text-ink-primary">
                        {(group.duplicates || []).length} tracks
                    </p>
                    <p className={`text-[11px] font-semibold ${similarityColor(group.similarity)}`}>
                        {similarityLabel(group.similarity)}
                    </p>
                </div>
                <button
                    onClick={handleAutoSelect}
                    className="text-[10px] text-amber2 hover:underline"
                >
                    Auto (best quality)
                </button>
            </div>

            {/* Track cards — horizontal scroll */}
            <div className="flex gap-3 overflow-x-auto pb-2">
                {(group.duplicates || []).map((track, i) => (
                    <TrackCard
                        key={track.path || i}
                        track={track}
                        isMaster={track.path === masterPath}
                        onSelect={() => setMasterPath(track.path)}
                    />
                ))}
            </div>

            {/* Options */}
            <label className="flex items-center gap-2 cursor-pointer text-[12px] text-ink-secondary hover:text-ink-primary">
                <input
                    type="checkbox"
                    checked={mergePlayCounts}
                    onChange={e => setMergePlayCounts(e.target.checked)}
                    className="accent-amber2 w-4 h-4"
                />
                Merge play counts into master track
            </label>

            {/* Merge button */}
            <div className="mt-auto">
                <div className="text-[10px] text-ink-muted mb-2">
                    Master: <span className="font-mono text-ink-secondary">
                        {masterPath?.split(/[\\/]/).pop() || '—'}
                    </span>
                    {' '}— {(group.duplicates || []).length - 1} duplicate(s) will be removed from library.
                </div>
                <button
                    onClick={handleMerge}
                    disabled={merging}
                    className="w-full btn-primary flex items-center justify-center gap-2 py-2.5 disabled:opacity-40"
                >
                    {merging
                        ? <><Loader2 size={14} className="animate-spin" /> Merging…</>
                        : <><Trash2 size={14} /> Merge — Remove Duplicates</>}
                </button>
            </div>
        </div>
    );
};

// ─────────────────────────────────────────────────────────────────────────────
//  Main view
// ─────────────────────────────────────────────────────────────────────────────

const DuplicateView = () => {
    const [scanning, setScanning] = useState(false);
    const [scanProgress, setScanProgress] = useState(null);  // {done, total}
    const [groups, setGroups] = useState(null);               // null = not scanned
    const [scanError, setScanError] = useState(null);
    const [selectedGroupIdx, setSelectedGroupIdx] = useState(0);
    const pollRef = useRef(null);

    // ── Scan ─────────────────────────────────────────────────────────────────
    const startScan = useCallback(async () => {
        setScanError(null);
        setGroups(null);
        setScanProgress({ done: 0, total: 0 });

        // Load track paths from library
        log('info', 'loading library tracks for scan');
        let trackPaths = [];
        try {
            const res = await api.get('/api/library/tracks');
            const list = res.data?.tracks ?? res.data?.data ?? res.data ?? [];
            trackPaths = (Array.isArray(list) ? list : [])
                .map(t => t.Location || t.path || '')
                .filter(Boolean);
            log('info', `${trackPaths.length} track paths collected`);
        } catch (e) {
            log('error', 'failed to load tracks', e);
            setScanError('Failed to load library tracks');
            return;
        }

        if (trackPaths.length === 0) {
            setScanError('No tracks in library to scan');
            return;
        }

        // POST scan request
        setScanning(true);
        let jobId = null;
        try {
            const res = await api.post('/api/duplicates/scan', { track_paths: trackPaths });
            if (res.data?.status !== 'ok') throw new Error(res.data?.message || 'Scan failed to start');
            jobId = res.data.data?.job_id;
            log('info', 'scan started', { jobId, total: res.data.data?.total });
        } catch (e) {
            log('error', 'scan request failed', e);
            setScanError(e?.response?.data?.detail || e.message || 'Scan failed');
            setScanning(false);
            return;
        }

        // Poll for results
        pollRef.current = setInterval(async () => {
            try {
                const res = await api.get('/api/duplicates/results', { params: { job_id: jobId } });
                const data = res.data?.data;
                if (!data) return;

                if (data.status === 'running') {
                    setScanProgress({ done: data.done || 0, total: data.total || 0 });
                    return;
                }

                clearInterval(pollRef.current);
                setScanning(false);

                if (data.status === 'error') {
                    setScanError(data.error || 'Scan error');
                    log('error', 'scan job errored', data.error);
                    return;
                }

                // Done
                const g = data.groups || [];
                setGroups(g);
                setSelectedGroupIdx(0);
                setScanProgress(null);
                log('info', `scan done: ${g.length} groups`);
                if (g.length === 0) toast.success('No duplicates found');
                else toast.success(`Found ${g.length} duplicate group(s)`);

            } catch (e) {
                log('error', 'poll failed', e);
            }
        }, 1500);
    }, []);

    // Cleanup poll on unmount
    useEffect(() => {
        return () => { if (pollRef.current) clearInterval(pollRef.current); };
    }, []);

    const handleMergeSuccess = useCallback(() => {
        // Refresh after merge — re-run scan or just update local state
        setGroups(prev => {
            if (!prev) return prev;
            // Keep the group in the list but it will show "merged" state
            return [...prev];
        });
    }, []);

    // ── Render ───────────────────────────────────────────────────────────────
    return (
        <div className="h-full flex flex-col bg-mx-deepest">
            {/* Toolbar */}
            <div className="flex items-center gap-3 px-6 py-4 border-b border-line-subtle shrink-0">
                <div className="w-8 h-8 rounded-mx-md flex items-center justify-center" style={{ background: 'var(--amber-bg)', color: 'var(--amber)' }}>
                    <Copy size={16} />
                </div>
                <div>
                    <h1 className="text-[14px] font-semibold text-ink-primary">Duplicate Finder</h1>
                    <p className="text-ink-muted text-tiny">Acoustic & hash-based duplicate detection</p>
                </div>

                <button
                    onClick={startScan}
                    disabled={scanning}
                    className="ml-auto btn-primary flex items-center gap-2 py-2 px-4 disabled:opacity-40"
                >
                    {scanning
                        ? <><Loader2 size={14} className="animate-spin" /> Scanning…</>
                        : <><RefreshCw size={14} /> Scan Library</>}
                </button>
            </div>

            {/* Progress bar */}
            {scanning && scanProgress && (
                <div className="px-6 py-2 border-b border-line-subtle bg-mx-shell shrink-0">
                    <div className="flex items-center justify-between text-tiny mb-1">
                        <span className="text-ink-muted">Analysing tracks…</span>
                        <span className="font-mono text-amber2">
                            {scanProgress.done} / {scanProgress.total || '?'}
                        </span>
                    </div>
                    <div className="w-full h-1 bg-line-subtle rounded-full overflow-hidden">
                        <div
                            className="h-full bg-amber2 rounded-full transition-all duration-300"
                            style={{
                                width: scanProgress.total
                                    ? `${(scanProgress.done / scanProgress.total) * 100}%`
                                    : '0%'
                            }}
                        />
                    </div>
                </div>
            )}

            {/* Error */}
            {scanError && (
                <div className="mx-6 mt-4 flex items-start gap-2 text-bad text-[11px] bg-bad/5 border border-bad/20 rounded-mx-sm px-3 py-2">
                    <AlertTriangle size={13} className="mt-0.5 shrink-0" />
                    {scanError}
                </div>
            )}

            {/* Empty state */}
            {!scanning && groups === null && !scanError && (
                <div className="flex-1 flex flex-col items-center justify-center gap-4 text-center p-8">
                    <div className="w-16 h-16 rounded-2xl bg-mx-card border border-line-subtle flex items-center justify-center">
                        <Copy size={28} className="text-ink-muted" strokeWidth={1.2} />
                    </div>
                    <div>
                        <p className="text-[14px] font-semibold text-ink-primary mb-1">Find Duplicates</p>
                        <p className="text-tiny text-ink-muted max-w-xs">
                            Scans your entire library using acoustic fingerprinting
                            (or fast hash comparison if librosa is unavailable).
                        </p>
                    </div>
                    <button onClick={startScan} className="btn-primary flex items-center gap-2">
                        <Zap size={14} /> Start Scan
                    </button>
                </div>
            )}

            {/* No duplicates found */}
            {!scanning && groups !== null && groups.length === 0 && (
                <div className="flex-1 flex flex-col items-center justify-center gap-3 text-center p-8">
                    <Check size={36} className="text-ok" />
                    <p className="text-[14px] font-semibold text-ink-primary">No duplicates found</p>
                    <p className="text-tiny text-ink-muted">Your library looks clean.</p>
                </div>
            )}

            {/* Results — split panel */}
            {groups !== null && groups.length > 0 && (
                <div className="flex-1 flex min-h-0">
                    {/* Left: group list */}
                    <div className="w-72 shrink-0 border-r border-line-subtle overflow-y-auto">
                        <div className="px-4 py-3 border-b border-line-subtle">
                            <span className="text-[11px] font-semibold text-ink-primary">
                                {groups.length} group{groups.length !== 1 ? 's' : ''}
                            </span>
                        </div>
                        <div className="divide-y divide-line-subtle">
                            {groups.map((g, i) => {
                                const repTrack = g.duplicates?.[0];
                                const isActive = i === selectedGroupIdx;
                                return (
                                    <button
                                        key={i}
                                        onClick={() => setSelectedGroupIdx(i)}
                                        className={`w-full text-left px-4 py-3 transition-colors ${
                                            isActive ? 'bg-amber2/5 border-l-2 border-amber2' : 'hover:bg-mx-hover'
                                        }`}
                                    >
                                        <div className="flex items-center justify-between mb-1">
                                            <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-mx-xs ${similarityColor(g.similarity)} bg-current/10`}>
                                                {similarityLabel(g.similarity)}
                                            </span>
                                            <span className="text-[10px] text-ink-muted font-mono">
                                                {(g.duplicates || []).length} tracks
                                            </span>
                                        </div>
                                        <p className="text-[12px] text-ink-primary truncate">
                                            {repTrack?.title || repTrack?.path?.split(/[\\/]/).pop() || '(unknown)'}
                                        </p>
                                        <p className="text-[10px] text-ink-muted truncate">
                                            {repTrack?.artist || ''}
                                        </p>
                                    </button>
                                );
                            })}
                        </div>
                    </div>

                    {/* Right: group detail */}
                    <div className="flex-1 overflow-y-auto p-6">
                        {groups[selectedGroupIdx] && (
                            <GroupDetail
                                key={selectedGroupIdx}
                                group={groups[selectedGroupIdx]}
                                onMergeSuccess={handleMergeSuccess}
                            />
                        )}
                    </div>
                </div>
            )}
        </div>
    );
};

export default DuplicateView;
