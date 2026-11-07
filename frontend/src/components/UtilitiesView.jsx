/**
 * UtilitiesView — router for the Utilities workspace.
 *
 * Each tool and each Library-Health filter is its own flat tab in the
 * workspace nav (no inner grid / toggle / sub-tabs). The `mode` prop selects
 * what to render:
 *   • phrase / duplicates / xml / converter — the individual tools
 *   • low_quality / lost / no_artwork        — Library-Health track lists
 */

import React, { useState, useEffect, useMemo, Suspense, lazy } from 'react';
import {
    Loader2,
    TrendingDown,
    PlayCircle,
    ImageOff,
    Search,
    AlertCircle,
    Music,
} from 'lucide-react';
import api from '../api/api';
import TrackTable from './TrackTable';

const PhraseGeneratorView = lazy(() => import('./PhraseGeneratorView'));
const DuplicateView = lazy(() => import('./DuplicateView'));
const XmlCleanView = lazy(() => import('./XmlCleanView'));
const FormatConverterView = lazy(() => import('./FormatConverterView'));

const HEALTH_META = {
    low_quality: {
        label: 'Low Quality',
        icon: TrendingDown,
        color: 'text-amber-400',
        tip: 'Replace these with high-quality AIFF or FLAC for better sound system performance.',
    },
    lost: {
        label: 'Lost Tracks',
        icon: PlayCircle,
        color: 'text-rose-400',
        tip: 'Tracks that haven\'t been played yet — move to a "New Music" playlist for review.',
    },
    no_artwork: {
        label: 'No Cover',
        icon: ImageOff,
        color: 'text-ink-secondary',
        tip: 'Tracks missing artwork — useful to fix before exporting to USB.',
    },
};

const UtilitiesView = ({
    mode = 'phrase',
    onSelectTrack,
    onEditTrack,
    onPlayTrack,
    libraryStatus,
}) => {
    const isHealth = mode in HEALTH_META;

    // ── Library Health state ─────────────────────────────────────────────────────
    const [tracks, setTracks] = useState([]);
    const [loading, setLoading] = useState(false);
    const [searchTerm, setSearchTerm] = useState('');

    useEffect(() => {
        if (!isHealth || !libraryStatus?.loaded) return;
        setLoading(true);
        setSearchTerm('');
        api.get(`/api/insights/${mode}`)
            .then((res) => {
                setTracks(res.data || []);
                setLoading(false);
            })
            .catch((err) => {
                console.error('[Utilities/Health] load failed', err);
                setLoading(false);
            });
    }, [mode, isHealth, libraryStatus?.loaded]);

    const filteredTracks = useMemo(() => {
        if (!searchTerm) return tracks;
        const q = searchTerm.toLowerCase();
        return tracks.filter(
            (t) =>
                (t.Title && t.Title.toLowerCase().includes(q)) ||
                (t.Artist && t.Artist.toLowerCase().includes(q))
        );
    }, [tracks, searchTerm]);

    // ── Tools — render the selected tool directly (it's its own tab now) ─────────
    if (!isHealth) {
        return (
            <div className="h-full overflow-hidden">
                <Suspense
                    fallback={
                        <div className="flex items-center justify-center h-full">
                            <Loader2 className="animate-spin text-amber2" size={24} />
                        </div>
                    }
                >
                    {mode === 'phrase' && <PhraseGeneratorView />}
                    {mode === 'duplicates' && <DuplicateView />}
                    {mode === 'xml' && <XmlCleanView />}
                    {mode === 'converter' && <FormatConverterView />}
                </Suspense>
            </div>
        );
    }

    // ── Library Health — track list for the selected filter ──────────────────────
    const meta = HEALTH_META[mode];
    const MetaIcon = meta.icon;

    return (
        <div className="h-full flex flex-col bg-mx-deepest animate-fade-in p-6">
            {/* Header — current filter + search (the selector lives in the workspace nav) */}
            <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2.5">
                    <div className="p-2 bg-amber2/10 rounded-mx-md border border-amber2-dim">
                        <MetaIcon size={18} className="text-amber2" />
                    </div>
                    <div>
                        <h1 className="text-[18px] font-semibold tracking-tight">{meta.label}</h1>
                        <span className="font-mono text-tiny text-amber2">
                            {tracks.length} tracks
                        </span>
                    </div>
                </div>
                <div className="relative w-64">
                    <Search
                        size={14}
                        className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted"
                    />
                    <input
                        className="input-glass w-full pl-9 text-tiny"
                        placeholder="Search results..."
                        value={searchTerm}
                        onChange={(e) => setSearchTerm(e.target.value)}
                    />
                </div>
            </div>

            {/* Track list */}
            <div className="flex-1 mx-card overflow-hidden">
                {loading ? (
                    <div className="h-full flex items-center justify-center">
                        <Loader2 className="animate-spin text-amber2" size={24} />
                    </div>
                ) : tracks.length === 0 ? (
                    <div className="h-full flex flex-col items-center justify-center text-ink-muted">
                        <Music size={48} className="mb-3 opacity-20" />
                        <p className="text-[12px] font-medium text-ink-secondary">All clean!</p>
                        <p className="text-tiny text-ink-placeholder mt-1">
                            No tracks match this filter.
                        </p>
                    </div>
                ) : (
                    <div className="h-full overflow-y-auto p-2">
                        <TrackTable
                            tracks={filteredTracks}
                            onSelectTrack={onSelectTrack}
                            onEditTrack={onEditTrack}
                            onPlay={onPlayTrack}
                            playlistId={`UTIL_HEALTH_${mode.toUpperCase()}`}
                            variant="minimal"
                        />
                    </div>
                )}
            </div>

            {/* Tip */}
            <div className="mt-3 px-3 py-2 bg-amber2/5 border border-amber2/15 rounded-mx-sm flex items-center gap-2">
                <AlertCircle size={13} className="text-amber2 shrink-0" />
                <p className="text-tiny text-ink-secondary leading-relaxed">{meta.tip}</p>
            </div>
        </div>
    );
};

export default UtilitiesView;
