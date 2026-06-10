/**
 * ScopeBucketPicker — 4-bucket scope chooser for the Format Converter.
 *
 * Buckets:
 *   single   → { kind:'track_ids', ids:[id] }       (search title/artist, pick 1)
 *   playlist → { kind:'playlist', playlist_id }      (real picker, no raw ID)
 *   subset   → { kind:'library_subset', subset_kind, color_id?, tag_id? }
 *   path     → { kind:'path', path }                 (collapsed under Advanced)
 *
 * Backend wire-up:
 *   GET /api/library/format-swap/playlists       — bucket 2 dropdown
 *   GET /api/library/format-swap/colors          — bucket 3 By Color swatches
 *   GET /api/library/format-swap/mytags          — bucket 3 By MyTag list
 *   GET /api/library/format-swap/subset-counts?  — chip badges (lazy)
 *
 * value shape passed to onChange:
 *   { bucket, scope, isValid }
 *
 * onChange is also fired on every sub-picker change so the parent can clear
 * stale dry-run results without each bucket having to know about it.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
    Music, ListMusic, Library, FolderTree, Search, Loader2, Palette, Tag, Star,
    StarOff, FileAudio, Archive, ChevronRight, Sparkles,
} from 'lucide-react';
import api from '../../api/api';
import { useToast } from '../ToastContext';

const RENDER_CAP = 300;

const BUCKETS = [
    { id: 'single', label: 'Single Track', icon: Music, desc: 'Search + pick one' },
    { id: 'playlist', label: 'Playlist', icon: ListMusic, desc: 'From your library' },
    { id: 'subset', label: 'Library Subset', icon: Library, desc: 'All / by tag / by colour' },
    { id: 'path', label: 'Advanced: Folder', icon: FolderTree, desc: 'Recursive path' },
];

// Subset preset chips — one chip per subset_kind. parameterised chips reveal
// a secondary picker (color swatches or MyTag list).
const SUBSET_CHIPS = [
    { id: 'all', label: 'All Library', icon: Library },
    { id: 'ranked', label: 'Ranked', icon: Star },
    { id: 'unranked', label: 'Unranked', icon: StarOff },
    { id: 'all_lossy', label: 'Lossy only', icon: FileAudio },
    { id: 'all_lossless', label: 'Lossless only', icon: Archive },
    { id: 'by_color', label: 'By Color…', icon: Palette },
    { id: 'uncolored', label: 'Uncolored', icon: Palette },
    { id: 'by_mytag', label: 'By MyTag…', icon: Tag },
];

const PIONEER_COLOR_HEX = {
    0: 'transparent',
    1: '#ff007f',
    2: '#ff0000',
    3: '#ff7f00',
    4: '#ffd700',
    5: '#00d000',
    6: '#00c8ff',
    7: '#0070ff',
    8: '#a000ff',
};

const tid = (t) => t.ID ?? t.id ?? t.TrackID ?? t.track_id;
const tname = (t) => t.Title || t.title || t.Name || '(untitled)';
const tartist = (t) => t.Artist || t.artist || '';

// Reusable title+artist substring filter (case-insensitive)
function filterTracks(list, q) {
    if (!q.trim()) return list;
    const s = q.toLowerCase();
    return list.filter(
        (t) => tname(t).toLowerCase().includes(s) || tartist(t).toLowerCase().includes(s),
    );
}

const SearchBox = ({ value, onChange, placeholder, loading }) => (
    <div className="flex items-center gap-2 px-3 py-2 bg-mx-input border-b border-line-subtle">
        <Search size={12} className="text-ink-muted shrink-0" />
        <input
            type="text"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder={placeholder}
            className="flex-1 bg-transparent text-[12px] text-ink-primary placeholder-ink-placeholder outline-none"
        />
        {loading && <Loader2 size={11} className="animate-spin text-amber2" />}
    </div>
);

// ─── Bucket 1: Single Track ────────────────────────────────────────────────
function SingleTrackPicker({ track, onPick }) {
    const [tracks, setTracks] = useState([]);
    const [loading, setLoading] = useState(false);
    const [q, setQ] = useState('');

    useEffect(() => {
        setLoading(true);
        api
            .get('/api/library/tracks')
            .then((res) => {
                const list = Array.isArray(res.data) ? res.data : (res.data?.tracks ?? []);
                setTracks(Array.isArray(list) ? list : []);
            })
            .catch((e) => console.error('[ScopeBucketPicker] tracks load failed', e))
            .finally(() => setLoading(false));
    }, []);

    const filtered = useMemo(() => filterTracks(tracks, q).slice(0, RENDER_CAP), [tracks, q]);

    if (track) {
        return (
            <div className="flex items-center justify-between p-3 bg-amber2/5 border border-amber2/25 rounded-mx-sm">
                <div className="min-w-0">
                    <p className="text-[13px] font-semibold text-ink-primary truncate">{tname(track)}</p>
                    <p className="text-ink-muted text-tiny truncate">{tartist(track)}</p>
                </div>
                <button
                    onClick={() => onPick(null)}
                    className="ml-3 text-[10px] text-ink-muted hover:text-ink-secondary underline shrink-0"
                >
                    Change
                </button>
            </div>
        );
    }

    return (
        <div className="border border-line-subtle rounded-mx-sm overflow-hidden">
            <SearchBox value={q} onChange={setQ} placeholder="Search title or artist…" loading={loading} />
            <div className="max-h-56 overflow-y-auto divide-y divide-line-subtle">
                {filtered.length === 0 ? (
                    <div className="p-4 text-center text-ink-muted text-tiny">
                        {loading ? 'Loading…' : 'No tracks found'}
                    </div>
                ) : (
                    filtered.map((t, i) => (
                        <button
                            key={tid(t) ?? i}
                            onClick={() => { onPick(t); setQ(''); }}
                            className="w-full text-left px-3 py-2 hover:bg-mx-hover transition-colors grid grid-cols-[1fr_auto_auto] gap-2 items-center"
                        >
                            <div className="min-w-0">
                                <p className="text-[12px] text-ink-primary truncate">{tname(t)}</p>
                                <p className="text-[10px] text-ink-muted truncate">{tartist(t)}</p>
                            </div>
                            <span className="font-mono text-[10px] text-ink-muted whitespace-nowrap">
                                {Number(t.BPM || t.bpm || 0).toFixed(1)} BPM
                            </span>
                            <span className="font-mono text-[10px] text-ink-muted whitespace-nowrap">
                                {t.Key || t.key || ''}
                            </span>
                        </button>
                    ))
                )}
            </div>
        </div>
    );
}

// ─── Bucket 2: Playlist (real dropdown) ───────────────────────────────────
function PlaylistDropdown({ playlistId, onPick }) {
    const [playlists, setPlaylists] = useState([]);
    const [loading, setLoading] = useState(false);
    const [q, setQ] = useState('');

    useEffect(() => {
        setLoading(true);
        api
            .get('/api/library/format-swap/playlists')
            .then((res) => setPlaylists(Array.isArray(res.data) ? res.data : []))
            .catch((e) => console.error('[ScopeBucketPicker] playlists load failed', e))
            .finally(() => setLoading(false));
    }, []);

    const filtered = useMemo(() => {
        if (!q.trim()) return playlists;
        const s = q.toLowerCase();
        return playlists.filter((p) => (p.name || '').toLowerCase().includes(s));
    }, [playlists, q]);

    const selected = playlists.find((p) => String(p.id) === String(playlistId));

    if (selected) {
        return (
            <div className="flex items-center justify-between p-3 bg-amber2/5 border border-amber2/25 rounded-mx-sm">
                <div className="min-w-0 flex items-center gap-2">
                    {selected.type === '4' ? (
                        <Sparkles size={14} className="text-amber2 shrink-0" />
                    ) : (
                        <ListMusic size={14} className="text-amber2 shrink-0" />
                    )}
                    <div className="min-w-0">
                        <p className="text-[13px] font-semibold text-ink-primary truncate">{selected.name}</p>
                        <p className="text-ink-muted text-tiny">{selected.track_count} tracks</p>
                    </div>
                </div>
                <button
                    onClick={() => onPick(null)}
                    className="ml-3 text-[10px] text-ink-muted hover:text-ink-secondary underline shrink-0"
                >
                    Change
                </button>
            </div>
        );
    }

    return (
        <div className="border border-line-subtle rounded-mx-sm overflow-hidden">
            <SearchBox value={q} onChange={setQ} placeholder="Search playlists…" loading={loading} />
            <div className="max-h-56 overflow-y-auto divide-y divide-line-subtle">
                {filtered.length === 0 ? (
                    <div className="p-4 text-center text-ink-muted text-tiny">
                        {loading ? 'Loading…' : 'No playlists'}
                    </div>
                ) : (
                    filtered.map((p) => (
                        <button
                            key={p.id}
                            onClick={() => onPick(p.id)}
                            className="w-full text-left px-3 py-2 hover:bg-mx-hover transition-colors flex items-center justify-between gap-2"
                        >
                            <div className="flex items-center gap-2 min-w-0">
                                {p.type === '4' ? (
                                    <Sparkles size={12} className="text-amber2 shrink-0" />
                                ) : (
                                    <ListMusic size={12} className="text-ink-muted shrink-0" />
                                )}
                                <span className="text-[12px] text-ink-primary truncate">{p.name}</span>
                            </div>
                            <span className="font-mono text-[10px] text-ink-muted whitespace-nowrap shrink-0">
                                {p.track_count}
                            </span>
                        </button>
                    ))
                )}
            </div>
        </div>
    );
}

// ─── Bucket 3: Library Subset (chips + secondary pickers) ──────────────────
function LibrarySubsetPicker({ subset, onPick, onCountChange }) {
    const toast = useToast();
    const [colors, setColors] = useState([]);
    const [mytags, setMytags] = useState([]);
    const [counts, setCounts] = useState({}); // key → {count, total_source_mb}
    const [pendingKey, setPendingKey] = useState(null);

    useEffect(() => {
        api
            .get('/api/library/format-swap/colors')
            .then((res) => setColors(Array.isArray(res.data) ? res.data : []))
            .catch((e) => console.error('[ScopeBucketPicker] colors load failed', e));
        api
            .get('/api/library/format-swap/mytags')
            .then((res) => setMytags(Array.isArray(res.data) ? res.data : []))
            .catch((e) => console.error('[ScopeBucketPicker] mytags load failed', e));
    }, []);

    // ── Count fetcher (cached, debounced via simple key check) ─────────────
    const fetchCount = useCallback((scope) => {
        const key = JSON.stringify(scope);
        if (counts[key] !== undefined) return Promise.resolve(counts[key]);
        if (pendingKey === key) return Promise.resolve(null);
        setPendingKey(key);
        const params = { subset_kind: scope.subset_kind };
        if (scope.color_id !== undefined) params.color_id = scope.color_id;
        if (scope.tag_id !== undefined) params.tag_id = scope.tag_id;
        if (scope.file_type !== undefined) params.file_type = scope.file_type;
        return api
            .get('/api/library/format-swap/subset-counts', { params })
            .then((res) => {
                setCounts((prev) => ({ ...prev, [key]: res.data }));
                return res.data;
            })
            .catch((e) => {
                console.error('[ScopeBucketPicker] subset-counts failed', e);
                return null;
            })
            .finally(() => setPendingKey(null));
    }, [counts, pendingKey]);

    // ── When a subset is fully resolved, fetch its count + bubble up ───────
    useEffect(() => {
        if (!subset?.subset_kind) {
            onCountChange?.(null);
            return;
        }
        // Skip count fetch when secondary picker is still required (no id chosen)
        if (subset.subset_kind === 'by_color' && subset.color_id === undefined) return;
        if (subset.subset_kind === 'by_mytag' && subset.tag_id === undefined) return;
        fetchCount(subset).then((c) => {
            if (c) {
                onCountChange?.(c);
                if (c.count === 0) {
                    toast.info('Subset matches 0 tracks — pick another');
                }
            }
        });
    }, [subset, fetchCount, onCountChange, toast]);

    const pickChip = (chipId) => {
        if (chipId === 'by_color' || chipId === 'by_mytag') {
            // reveal secondary picker; leave color_id/tag_id undefined until chosen
            onPick({ subset_kind: chipId });
            return;
        }
        onPick({ subset_kind: chipId });
    };

    const pickColor = (colorId) => onPick({ subset_kind: 'by_color', color_id: colorId });
    const pickTag = (tagId) => onPick({ subset_kind: 'by_mytag', tag_id: tagId });

    return (
        <div className="space-y-3">
            {/* Chip grid */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                {SUBSET_CHIPS.map((chip) => {
                    const Icon = chip.icon;
                    const active = subset?.subset_kind === chip.id;
                    const key = JSON.stringify({ subset_kind: chip.id });
                    const cached = counts[key];
                    return (
                        <button
                            key={chip.id}
                            onClick={() => pickChip(chip.id)}
                            className={`flex flex-col items-center gap-1 p-2.5 rounded-mx-sm border transition-all text-center ${
                                active
                                    ? 'bg-amber2/10 border-amber2/50 text-amber2'
                                    : 'border-line-subtle text-ink-muted hover:bg-mx-hover'
                            }`}
                        >
                            <Icon size={15} />
                            <span className="text-[11px] font-semibold leading-tight">{chip.label}</span>
                            {cached && cached.count !== undefined ? (
                                <span className="font-mono text-[10px] opacity-70">{cached.count}</span>
                            ) : null}
                        </button>
                    );
                })}
            </div>

            {/* By-Color secondary picker */}
            {subset?.subset_kind === 'by_color' && (
                <div className="border border-line-subtle rounded-mx-sm p-3 space-y-2">
                    <div className="text-tiny text-ink-muted">Pick a Pioneer colour</div>
                    <div className="flex flex-wrap gap-2">
                        {colors.map((c) => {
                            const sel = subset.color_id === c.color_id;
                            return (
                                <button
                                    key={c.color_id}
                                    onClick={() => pickColor(c.color_id)}
                                    title={`${c.label} (${c.count})`}
                                    className={`flex items-center gap-1.5 px-2 py-1.5 rounded-mx-sm border text-[11px] transition-all ${
                                        sel
                                            ? 'border-amber2/60 bg-amber2/10 text-amber2'
                                            : 'border-line-subtle text-ink-muted hover:bg-mx-hover'
                                    }`}
                                >
                                    <span
                                        className="inline-block w-3 h-3 rounded-full border border-line-default"
                                        style={{ background: PIONEER_COLOR_HEX[c.color_id] }}
                                    />
                                    <span>{c.label}</span>
                                    <span className="font-mono opacity-60">({c.count})</span>
                                </button>
                            );
                        })}
                    </div>
                </div>
            )}

            {/* By-MyTag secondary picker */}
            {subset?.subset_kind === 'by_mytag' && (
                <div className="border border-line-subtle rounded-mx-sm p-3 space-y-2">
                    <div className="text-tiny text-ink-muted">Pick a MyTag</div>
                    {mytags.length === 0 ? (
                        <p className="text-tiny text-ink-placeholder">No MyTags defined.</p>
                    ) : (
                        <div className="max-h-48 overflow-y-auto divide-y divide-line-subtle">
                            {mytags.map((t) => {
                                const sel = subset.tag_id === t.tag_id;
                                return (
                                    <button
                                        key={t.tag_id}
                                        onClick={() => pickTag(t.tag_id)}
                                        className={`w-full text-left px-2 py-1.5 flex items-center justify-between gap-2 transition-colors ${
                                            sel ? 'bg-amber2/10 text-amber2' : 'hover:bg-mx-hover text-ink-secondary'
                                        }`}
                                    >
                                        <span className="text-[12px] truncate">{t.name}</span>
                                        <span className="font-mono text-[10px] opacity-70 shrink-0">{t.count}</span>
                                    </button>
                                );
                            })}
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

// ─── Bucket 4: Advanced Folder Path ───────────────────────────────────────
function AdvancedFolderPath({ pathValue, onChange }) {
    return (
        <details className="border border-line-subtle rounded-mx-sm">
            <summary className="cursor-pointer px-3 py-2 text-tiny text-ink-muted hover:text-ink-primary flex items-center gap-2">
                <ChevronRight size={12} />
                Advanced: Folder path
            </summary>
            <div className="p-3 space-y-1">
                <input
                    type="text"
                    className="input-glass w-full text-[13px] font-mono"
                    placeholder="C:\Users\you\Music\Library\house"
                    value={pathValue || ''}
                    onChange={(e) => onChange(e.target.value)}
                />
                <p className="text-tiny text-ink-placeholder">
                    All tracks whose folder_path starts here (recursive).
                </p>
            </div>
        </details>
    );
}

// ─── Main picker ──────────────────────────────────────────────────────────
export default function ScopeBucketPicker({ value, onChange }) {
    const bucket = value?.bucket || 'subset';

    // Per-bucket state — reset on bucket switch via switchBucket()
    const [singleTrack, setSingleTrack] = useState(null);
    const [playlistId, setPlaylistId] = useState(null);
    const [subset, setSubset] = useState(null);
    const [pathValue, setPathValue] = useState('');
    const [subsetCount, setSubsetCount] = useState(null);

    // ── Build the scope payload for the current bucket ────────────────────
    const buildPayload = useCallback(
        (b, st, pid, sub, pth) => {
            if (b === 'single') {
                const ok = !!st;
                return {
                    bucket: b,
                    scope: ok ? { kind: 'track_ids', ids: [String(tid(st))] } : null,
                    isValid: ok,
                };
            }
            if (b === 'playlist') {
                const ok = pid != null;
                return {
                    bucket: b,
                    scope: ok ? { kind: 'playlist', playlist_id: Number(pid) } : null,
                    isValid: ok,
                };
            }
            if (b === 'subset') {
                if (!sub?.subset_kind) return { bucket: b, scope: null, isValid: false };
                if (sub.subset_kind === 'by_color' && sub.color_id === undefined) {
                    return { bucket: b, scope: null, isValid: false };
                }
                if (sub.subset_kind === 'by_mytag' && sub.tag_id === undefined) {
                    return { bucket: b, scope: null, isValid: false };
                }
                return {
                    bucket: b,
                    scope: { kind: 'library_subset', ...sub },
                    isValid: true,
                };
            }
            if (b === 'path') {
                const ok = (pth || '').trim().length > 3;
                return {
                    bucket: b,
                    scope: ok ? { kind: 'path', path: pth.trim() } : null,
                    isValid: ok,
                };
            }
            return { bucket: b, scope: null, isValid: false };
        },
        [],
    );

    // ── Emit on any sub-picker change ─────────────────────────────────────
    useEffect(() => {
        onChange?.(buildPayload(bucket, singleTrack, playlistId, subset, pathValue));
        // We intentionally do NOT include onChange in deps — parent provides
        // a fresh closure every render; including it would cause infinite loops.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [bucket, singleTrack, playlistId, subset, pathValue, buildPayload]);

    const switchBucket = (b) => {
        // Wipe per-bucket state on switch so stale picks can't leak into the
        // emitted scope. Parent clears dryResult via its onChange handler.
        onChange?.({ bucket: b, scope: null, isValid: false });
        if (b !== 'single') setSingleTrack(null);
        if (b !== 'playlist') setPlaylistId(null);
        if (b !== 'subset') {
            setSubset(null);
            setSubsetCount(null);
        }
        if (b !== 'path') setPathValue('');
        // bucket itself lives on parent (value.bucket) — onChange call above
        // will land via the next render
    };

    // ── Render ────────────────────────────────────────────────────────────
    return (
        <div className="space-y-3">
            {/* Bucket radio cards */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                {BUCKETS.map((b) => {
                    const Icon = b.icon;
                    const active = bucket === b.id;
                    return (
                        <button
                            key={b.id}
                            onClick={() => switchBucket(b.id)}
                            className={`flex flex-col items-center gap-1 p-3 rounded-mx-sm border transition-all text-center ${
                                active
                                    ? 'bg-amber2/10 border-amber2/50 text-amber2'
                                    : 'border-line-subtle text-ink-muted hover:bg-mx-hover'
                            }`}
                        >
                            <Icon size={16} />
                            <span className="text-[12px] font-semibold leading-tight">{b.label}</span>
                            <span className="text-[10px] opacity-70 leading-tight">{b.desc}</span>
                        </button>
                    );
                })}
            </div>

            {/* Bucket body */}
            {bucket === 'single' && (
                <SingleTrackPicker track={singleTrack} onPick={setSingleTrack} />
            )}
            {bucket === 'playlist' && (
                <PlaylistDropdown playlistId={playlistId} onPick={setPlaylistId} />
            )}
            {bucket === 'subset' && (
                <>
                    <LibrarySubsetPicker
                        subset={subset}
                        onPick={setSubset}
                        onCountChange={setSubsetCount}
                    />
                    {subsetCount && subsetCount.count !== undefined && (
                        <div className="text-tiny text-ink-muted">
                            <span className="font-mono text-ink-secondary">{subsetCount.count}</span>{' '}
                            tracks · {subsetCount.total_source_mb} MB source
                        </div>
                    )}
                </>
            )}
            {bucket === 'path' && (
                <AdvancedFolderPath pathValue={pathValue} onChange={setPathValue} />
            )}
        </div>
    );
}
