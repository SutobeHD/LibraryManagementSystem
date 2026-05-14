/**
 * PhraseGeneratorView — Phrase & Auto-Cue Generator
 *
 * Generates hot cue points at every N-bar phrase boundary for any
 * analysed track in the Rekordbox library.
 *
 * Flow:
 *   1. User picks a track from the searchable selector
 *   2. Picks phrase length (8 / 16 / 32 bars)
 *   3. "Generate" → calls POST /api/phrase/generate → preview list
 *   4. "Commit to Library" → calls POST /api/phrase/commit → hot cues written
 *
 * Design: Melodex tokens (mx-*, ink-*, amber2).
 * Phrase-start markers: amber. Bar markers: grey.
 */

import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
    Music, Zap, Check, AlertTriangle, Loader2, Search, ChevronRight,
    BarChart3, Clock, RefreshCw,
} from 'lucide-react';
import api from '../api/api';
import toast from 'react-hot-toast';
import { useLibraryTracks } from '../hooks/useLibraryTracks';

// ─────────────────────────────────────────────────────────────────────────────
//  Constants
// ─────────────────────────────────────────────────────────────────────────────

const PHRASE_LENGTHS = [
    { value: 8,  label: '8 Bars',  desc: 'Short phrase — house, techno intro' },
    { value: 16, label: '16 Bars', desc: 'Standard phrase — most dance music' },
    { value: 32, label: '32 Bars', desc: 'Long phrase — progressive, ambient' },
];

const log = (level, msg, data) =>
    console[level]?.(`[PhraseGeneratorView] ${msg}`, data ?? '');

// ─────────────────────────────────────────────────────────────────────────────
//  Helpers
// ─────────────────────────────────────────────────────────────────────────────

/** Format milliseconds as mm:ss.xxx */
function formatMs(ms) {
    if (ms == null || isNaN(ms)) return '—';
    const totalSec = ms / 1000;
    const min = Math.floor(totalSec / 60);
    const sec = (totalSec % 60).toFixed(1).padStart(4, '0');
    return `${min}:${sec}`;
}

// ─────────────────────────────────────────────────────────────────────────────
//  Sub-components
// ─────────────────────────────────────────────────────────────────────────────

/**
 * CueRow — one generated cue position in the preview list.
 *
 * Props: cue (phrase_start|bar_start, position_ms, label)
 */
const CueRow = ({ cue }) => {
    const isPhrase = cue.type === 'phrase_start';
    return (
        <div className={`flex items-center gap-3 px-3 py-1.5 rounded-mx-xs ${isPhrase ? 'bg-amber2/5' : ''}`}>
            {/* Colour swatch */}
            <div
                className="w-2 h-2 rounded-full shrink-0"
                style={{ background: isPhrase ? '#E8A42A' : '#555' }}
            />
            {/* Position */}
            <span className="font-mono text-[11px] text-ink-muted w-16 shrink-0">
                {formatMs(cue.position_ms)}
            </span>
            {/* Label */}
            <span className={`text-[12px] font-semibold ${isPhrase ? 'text-amber2' : 'text-ink-secondary'}`}>
                {cue.label}
            </span>
            {/* Type badge */}
            <span className={`ml-auto text-[9px] uppercase tracking-wider px-1.5 py-0.5 rounded-mx-xs ${
                isPhrase
                    ? 'bg-amber2/10 text-amber2 border border-amber2/30'
                    : 'bg-mx-card text-ink-muted border border-line-subtle'
            }`}>
                {isPhrase ? 'Phrase' : 'Bar'}
            </span>
        </div>
    );
};

// ─────────────────────────────────────────────────────────────────────────────
//  Main view
// ─────────────────────────────────────────────────────────────────────────────

const PhraseGeneratorView = () => {
    // ── Track selector ──────────────────────────────────────────────────────
    // Track list comes from the shared library cache — one fetch across views.
    const { tracks, loading: tracksLoading } = useLibraryTracks();
    const [trackSearch, setTrackSearch] = useState('');
    const [selectedTrack, setSelectedTrack] = useState(null);
    const [selectorOpen, setSelectorOpen] = useState(false);

    // ── Phrase config ───────────────────────────────────────────────────────
    const [phraseLength, setPhraseLength] = useState(16);

    // ── Generate state ──────────────────────────────────────────────────────
    const [generating, setGenerating] = useState(false);
    const [cues, setCues] = useState(null);        // list of cue dicts
    const [genError, setGenError] = useState(null);
    const [genWarning, setGenWarning] = useState(null);

    // ── Commit state ────────────────────────────────────────────────────────
    const [committing, setCommitting] = useState(false);
    const [committed, setCommitted] = useState(false);

    // ── Filtered track list ──────────────────────────────────────────────────
    const filteredTracks = useMemo(() => {
        if (!trackSearch.trim()) return tracks.slice(0, 100);
        const q = trackSearch.toLowerCase();
        return tracks
            .filter(t => {
                const title  = (t.Name || t.title || '').toLowerCase();
                const artist = (t.Artist || t.artist || '').toLowerCase();
                return title.includes(q) || artist.includes(q);
            })
            .slice(0, 100);
    }, [tracks, trackSearch]);

    // ── Generate ─────────────────────────────────────────────────────────────
    const handleGenerate = useCallback(async () => {
        if (!selectedTrack) {
            toast.error('Select a track first');
            return;
        }
        const trackId = selectedTrack.TrackID ?? selectedTrack.track_id;
        if (!trackId) {
            toast.error('Selected track has no ID');
            return;
        }

        setGenerating(true);
        setGenError(null);
        setGenWarning(null);
        setCues(null);
        setCommitted(false);
        log('info', 'generating', { trackId, phraseLength });

        try {
            const res = await api.post('/api/phrase/generate', {
                track_id: Number(trackId),
                phrase_length: phraseLength,
            });
            if (res.data?.status !== 'ok') throw new Error(res.data?.message || 'Generate failed');

            const result = res.data.data;
            setCues(result.cues || []);
            if (result.warning) setGenWarning(result.warning);
            log('info', `generated ${result.cues?.length} cues`);
        } catch (e) {
            log('error', 'generate failed', e);
            const msg = e?.response?.data?.detail || e.message || 'Unknown error';
            setGenError(msg);
            toast.error(`Generate failed: ${msg}`);
        } finally {
            setGenerating(false);
        }
    }, [selectedTrack, phraseLength]);

    // ── Commit ───────────────────────────────────────────────────────────────
    const handleCommit = useCallback(async () => {
        if (!cues || cues.length === 0) {
            toast.error('Generate cues first');
            return;
        }
        const trackId = selectedTrack?.TrackID ?? selectedTrack?.track_id;
        if (!trackId) return;

        setCommitting(true);
        log('info', 'committing cues', { trackId, count: cues.length });

        try {
            const res = await api.post('/api/phrase/commit', {
                track_id: Number(trackId),
                cues,
            });
            if (res.data?.status !== 'ok') throw new Error(res.data?.message || 'Commit failed');

            const written = res.data.data?.written ?? 0;
            setCommitted(true);
            toast.success(`${written} hot cue(s) written to library`);
            log('info', `committed ${written} cues`);
        } catch (e) {
            log('error', 'commit failed', e);
            const msg = e?.response?.data?.detail || e.message || 'Unknown error';
            toast.error(`Commit failed: ${msg}`);
        } finally {
            setCommitting(false);
        }
    }, [cues, selectedTrack]);

    // ── Render ───────────────────────────────────────────────────────────────
    const phraseCues = cues?.filter(c => c.type === 'phrase_start') ?? [];
    const barCues    = cues?.filter(c => c.type === 'bar_start')    ?? [];

    return (
        <div className="h-full overflow-y-auto p-6 bg-mx-deepest">
            <div className="max-w-3xl mx-auto space-y-6">

                {/* Header */}
                <div className="flex items-center gap-3">
                    <div className="w-9 h-9 rounded-mx-md flex items-center justify-center" style={{ background: 'var(--amber-bg)', color: 'var(--amber)' }}>
                        <BarChart3 size={18} />
                    </div>
                    <div>
                        <h1 className="text-lg font-semibold text-ink-primary">Phrase Generator</h1>
                        <p className="text-ink-muted text-tiny">Auto-place hot cues at phrase & bar boundaries</p>
                    </div>
                </div>

                {/* ── Track selector ────────────────────────────────────────── */}
                <div className="mx-card rounded-mx-md p-4 space-y-3">
                    <div className="mx-caption">Track</div>

                    {/* Selected track display */}
                    {selectedTrack ? (
                        <div className="flex items-center justify-between p-3 bg-amber2/5 border border-amber2/25 rounded-mx-sm">
                            <div className="min-w-0">
                                <p className="text-[13px] font-semibold text-ink-primary truncate">
                                    {selectedTrack.Name || selectedTrack.title || '(untitled)'}
                                </p>
                                <p className="text-ink-muted text-tiny truncate">
                                    {selectedTrack.Artist || selectedTrack.artist || ''}
                                </p>
                            </div>
                            <button
                                onClick={() => { setSelectedTrack(null); setCues(null); setCommitted(false); }}
                                className="ml-3 text-[10px] text-ink-muted hover:text-ink-secondary underline shrink-0"
                            >
                                Change
                            </button>
                        </div>
                    ) : (
                        <button
                            onClick={() => setSelectorOpen(o => !o)}
                            className="w-full flex items-center gap-2 px-3 py-2.5 bg-mx-input border border-line-subtle rounded-mx-sm hover:bg-mx-hover transition-colors text-ink-muted text-tiny"
                        >
                            <Music size={13} />
                            <span>Select a track…</span>
                            <ChevronRight size={12} className="ml-auto" />
                        </button>
                    )}

                    {/* Inline track picker */}
                    {selectorOpen && !selectedTrack && (
                        <div className="border border-line-subtle rounded-mx-sm overflow-hidden">
                            {/* Search input */}
                            <div className="flex items-center gap-2 px-3 py-2 bg-mx-input border-b border-line-subtle">
                                <Search size={12} className="text-ink-muted shrink-0" />
                                <input
                                    autoFocus
                                    type="text"
                                    placeholder="Search title or artist…"
                                    value={trackSearch}
                                    onChange={e => setTrackSearch(e.target.value)}
                                    className="flex-1 bg-transparent text-[12px] text-ink-primary placeholder-ink-placeholder outline-none"
                                />
                                {tracksLoading && <Loader2 size={11} className="animate-spin text-amber2" />}
                            </div>
                            {/* Results */}
                            <div className="max-h-56 overflow-y-auto divide-y divide-line-subtle">
                                {filteredTracks.length === 0 ? (
                                    <div className="p-4 text-center text-ink-muted text-tiny">
                                        {tracksLoading ? 'Loading…' : 'No tracks found'}
                                    </div>
                                ) : filteredTracks.map((t, i) => {
                                    const tid = t.TrackID ?? t.track_id ?? i;
                                    return (
                                        <button
                                            key={tid}
                                            className="w-full text-left px-3 py-2 hover:bg-mx-hover transition-colors"
                                            onClick={() => {
                                                setSelectedTrack(t);
                                                setSelectorOpen(false);
                                                setTrackSearch('');
                                                setCues(null);
                                                setCommitted(false);
                                            }}
                                        >
                                            <p className="text-[12px] text-ink-primary truncate">
                                                {t.Name || t.title || '(untitled)'}
                                            </p>
                                            <p className="text-[10px] text-ink-muted truncate">
                                                {t.Artist || t.artist || ''}{t.BPM ? ` · ${t.BPM} BPM` : ''}
                                            </p>
                                        </button>
                                    );
                                })}
                            </div>
                        </div>
                    )}
                </div>

                {/* ── Phrase length selector ───────────────────────────────── */}
                <div className="mx-card rounded-mx-md p-4 space-y-3">
                    <div className="mx-caption">Phrase Length</div>
                    <div className="grid grid-cols-3 gap-2">
                        {PHRASE_LENGTHS.map(pl => (
                            <button
                                key={pl.value}
                                onClick={() => setPhraseLength(pl.value)}
                                className={`flex flex-col items-center p-3 rounded-mx-sm border transition-all text-center ${
                                    phraseLength === pl.value
                                        ? 'bg-amber2/10 border-amber2/50 text-amber2'
                                        : 'border-line-subtle text-ink-muted hover:bg-mx-hover'
                                }`}
                            >
                                <span className="text-[14px] font-bold">{pl.label}</span>
                                <span className="text-[9px] mt-1 opacity-70">{pl.desc}</span>
                            </button>
                        ))}
                    </div>
                </div>

                {/* ── Generate button ──────────────────────────────────────── */}
                <button
                    onClick={handleGenerate}
                    disabled={generating || !selectedTrack}
                    className="w-full btn-primary flex items-center justify-center gap-2 py-2.5 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                    {generating
                        ? <><Loader2 size={15} className="animate-spin" /> Generating…</>
                        : <><Zap size={15} /> Generate Cues</>}
                </button>

                {/* ── Error / Warning ──────────────────────────────────────── */}
                {genError && (
                    <div className="flex items-start gap-2 text-bad text-[11px] bg-bad/5 border border-bad/20 rounded-mx-sm px-3 py-2">
                        <AlertTriangle size={13} className="mt-0.5 shrink-0" />
                        {genError}
                    </div>
                )}
                {genWarning && (
                    <div className="flex items-start gap-2 text-amber2 text-[11px] bg-amber2/5 border border-amber2/20 rounded-mx-sm px-3 py-2">
                        <AlertTriangle size={13} className="mt-0.5 shrink-0" />
                        {genWarning}
                    </div>
                )}

                {/* ── Cue preview ──────────────────────────────────────────── */}
                {cues !== null && (
                    <div className="mx-card rounded-mx-md p-4 space-y-3">
                        {/* Summary */}
                        <div className="flex items-center justify-between">
                            <div className="mx-caption">Preview</div>
                            <div className="flex items-center gap-3 text-[10px] font-mono">
                                <span>
                                    <span className="text-amber2 font-semibold">{phraseCues.length}</span>
                                    <span className="text-ink-muted"> phrase</span>
                                </span>
                                <span>
                                    <span className="text-ink-secondary font-semibold">{barCues.length}</span>
                                    <span className="text-ink-muted"> bar</span>
                                </span>
                            </div>
                        </div>

                        {cues.length === 0 ? (
                            <p className="text-ink-muted text-tiny text-center py-4">
                                No cues generated — track may not have a beat grid yet.
                            </p>
                        ) : (
                            <div className="space-y-0.5 max-h-80 overflow-y-auto">
                                {cues.map((c, i) => <CueRow key={i} cue={c} />)}
                            </div>
                        )}

                        {/* Commit button */}
                        {cues.length > 0 && (
                            <div className="pt-2 border-t border-line-subtle">
                                {committed ? (
                                    <div className="flex items-center gap-2 text-ok text-[12px] font-semibold">
                                        <Check size={14} />
                                        Cues committed to library
                                    </div>
                                ) : (
                                    <button
                                        onClick={handleCommit}
                                        disabled={committing}
                                        className="w-full btn-primary flex items-center justify-center gap-2 py-2.5 disabled:opacity-40 disabled:cursor-not-allowed"
                                    >
                                        {committing
                                            ? <><Loader2 size={14} className="animate-spin" /> Writing to library…</>
                                            : <><Check size={14} /> Commit to Library</>}
                                    </button>
                                )}
                            </div>
                        )}
                    </div>
                )}

            </div>
        </div>
    );
};

export default PhraseGeneratorView;
