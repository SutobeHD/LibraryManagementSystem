import { useEffect, useState } from 'react';
import { Sparkles } from 'lucide-react';
import api from '../api/api';

/**
 * Genre suggestions from the genre atlas for one library track.
 *
 * Read-only: shows ranked candidates with their reasons (uploader/label scene, labels such as
 * SoundCloud "trance" or Beatport categories, genre names, BPM window). Clicking a chip only
 * calls onPick with the user's own spelling when the library already has that genre, otherwise
 * with the atlas name; saving stays the user's explicit action.
 */
const MAX_CHIPS = 5;

function describe(candidate) {
    const lines = (candidate.reasons || []).map((r) => `• ${r.text}`);
    if (candidate.tests && candidate.tests.length) {
        lines.push('', 'Check:', ...candidate.tests.map((t) => `– ${t}`));
    }
    if (candidate.parent_name)
        lines.unshift(`${candidate.name} (part of ${candidate.parent_name})`, '');
    return lines.join('\n');
}

export default function GenreSuggestions({ trackId, currentGenre, onPick }) {
    const [data, setData] = useState(null);
    const [failed, setFailed] = useState(false);

    useEffect(() => {
        if (!trackId) {
            setData(null);
            return undefined;
        }
        let cancelled = false;
        setFailed(false);
        api.get(`/api/track/${encodeURIComponent(trackId)}/genre-suggestions`)
            .then((res) => {
                if (!cancelled) setData(res.data);
            })
            .catch((err) => {
                console.error('[GenreSuggestions] load failed', err);
                if (!cancelled) {
                    setData(null);
                    setFailed(true);
                }
            });
        return () => {
            cancelled = true;
        };
    }, [trackId]);

    if (failed) {
        return (
            <div className="mt-2 text-[10px] text-ink-placeholder">
                Atlas suggestions unavailable.
            </div>
        );
    }
    // Two atlas genres can map to the same library spelling; show that label once.
    const seen = new Set();
    const candidates = (data?.candidates || [])
        .filter((c) => {
            const key = (c.library_genre || c.name).trim().toLowerCase();
            if (seen.has(key)) return false;
            seen.add(key);
            return true;
        })
        .slice(0, MAX_CHIPS);
    if (!candidates.length) return null;

    const current = (currentGenre || '').trim().toLowerCase();
    const matched = [
        ...(data.matched?.scenes || []).map((s) => s.name),
        ...(data.matched?.tags || []).map((t) => `"${t.name}"`),
    ];

    return (
        <div className="mt-2" data-testid="genre-suggestions">
            <div className="text-[9px] font-black text-ink-placeholder uppercase tracking-[0.2em] mb-1.5 px-1 flex items-center gap-1.5">
                <Sparkles size={10} /> Atlas suggestions{data.bpm_only ? ' · tempo only' : ''}
            </div>
            <div className="flex flex-wrap gap-1.5">
                {candidates.map((c) => {
                    const value = c.library_genre || c.name;
                    const active = value.trim().toLowerCase() === current;
                    return (
                        <button
                            key={c.id}
                            type="button"
                            title={describe(c)}
                            onClick={() => onPick(value)}
                            className={`px-2.5 py-1 rounded-md text-[10px] font-bold border transition-all ${
                                active
                                    ? 'bg-amber2/20 border-amber2 text-amber2'
                                    : 'bg-black/20 border-white/5 text-ink-muted hover:border-white/20 hover:text-ink-primary'
                            }`}
                        >
                            {value}
                            <span className="ml-1.5 font-normal text-ink-placeholder">
                                {Math.round((c.confidence || 0) * 100)}%
                            </span>
                        </button>
                    );
                })}
            </div>
            {matched.length > 0 && (
                <div
                    className="mt-1.5 px-1 text-[9px] text-ink-placeholder truncate"
                    title={matched.join(', ')}
                >
                    from {matched.join(', ')}
                </div>
            )}
        </div>
    );
}
