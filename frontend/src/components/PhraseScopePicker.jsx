/**
 * PhraseScopePicker — choose which tracks a phrase batch runs over.
 *
 * Four modes, emitted as a backend `scope` object via onScopeChange:
 *   single     → { kind:'single', track_id }
 *   playlist   → { kind:'playlist', playlist_id }       (whole playlist)
 *   selection  → { kind:'selection', track_ids:[...] }  (subset of playlist OR collection)
 *   collection → { kind:'collection' }                  (entire library)
 *
 * onScopeChange({ scope, valid, count, mode }) fires on every change. Pass a
 * stable (useCallback'd) handler.
 *
 * Multi-select is a self-contained checklist (TrackTable has no multi-select).
 */

import { useEffect, useMemo, useState } from 'react';
import {
    Music, Search, ListMusic, Library, CheckSquare, Square, Loader2, ChevronRight,
} from 'lucide-react';
import api from '../api/api';

const MODES = [
    { id: 'single', label: 'Single', icon: Music, desc: 'One track' },
    { id: 'playlist', label: 'Playlist', icon: ListMusic, desc: 'Whole playlist' },
    { id: 'selection', label: 'Selection', icon: CheckSquare, desc: 'Pick tracks' },
    { id: 'collection', label: 'Collection', icon: Library, desc: 'Whole library' },
];

const RENDER_CAP = 300; // max rows rendered in a checklist/picker (search to narrow)

const tid = (t) => t.ID ?? t.id ?? t.TrackID ?? t.track_id;
const tname = (t) => t.Name || t.title || '(untitled)';
const tartist = (t) => t.Artist || t.artist || '';

const log = (level, msg, data) => console[level]?.(`[PhraseScopePicker] ${msg}`, data ?? '');

function flattenPlaylists(nodes, depth = 0, out = []) {
    for (const n of nodes || []) {
        const type = String(n.Type ?? n.type ?? '');
        if (type === '1' || type === '4') out.push({ id: n.ID, name: n.Name, depth });
        if (n.Children?.length) flattenPlaylists(n.Children, depth + 1, out);
    }
    return out;
}

function filterTracks(list, q) {
    if (!q.trim()) return list;
    const s = q.toLowerCase();
    return list.filter(
        (t) => tname(t).toLowerCase().includes(s) || tartist(t).toLowerCase().includes(s),
    );
}

// ── Small search input ──────────────────────────────────────────────────────
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

// ── Main ────────────────────────────────────────────────────────────────────
export default function PhraseScopePicker({ onScopeChange }) {
    const [mode, setMode] = useState('collection');
    const [allTracks, setAllTracks] = useState([]);
    const [tracksLoading, setTracksLoading] = useState(false);
    const [playlists, setPlaylists] = useState([]);

    // single
    const [singleTrack, setSingleTrack] = useState(null);
    const [singleSearch, setSingleSearch] = useState('');

    // playlist (whole)
    const [playlistId, setPlaylistId] = useState(null);
    const [plSearch, setPlSearch] = useState('');

    // selection
    const [selSource, setSelSource] = useState('collection'); // 'collection' | 'playlist'
    const [selPlaylistId, setSelPlaylistId] = useState(null);
    const [selPlTracks, setSelPlTracks] = useState([]);
    const [selPlLoading, setSelPlLoading] = useState(false);
    const [selectedIds, setSelectedIds] = useState(() => new Set());
    const [selSearch, setSelSearch] = useState('');

    // ── Load collection + playlist tree once ────────────────────────────────
    useEffect(() => {
        setTracksLoading(true);
        api
            .get('/api/library/tracks')
            .then((res) => {
                const list = Array.isArray(res.data)
                    ? res.data
                    : res.data?.tracks ?? res.data?.data ?? [];
                setAllTracks(Array.isArray(list) ? list : []);
            })
            .catch((e) => log('error', 'load tracks failed', e))
            .finally(() => setTracksLoading(false));
        api
            .get('/api/playlists/tree')
            .then((res) => {
                if (Array.isArray(res.data)) setPlaylists(flattenPlaylists(res.data));
            })
            .catch((e) => log('error', 'load playlists failed', e));
    }, []);

    // ── Fetch playlist tracks for selection-from-playlist ───────────────────
    useEffect(() => {
        if (!(mode === 'selection' && selSource === 'playlist' && selPlaylistId)) return;
        setSelPlLoading(true);
        api
            .get(`/api/playlist/${selPlaylistId}/tracks?_=${Date.now()}`)
            .then((res) => setSelPlTracks(Array.isArray(res.data) ? res.data : []))
            .catch((e) => {
                log('error', 'load playlist tracks failed', e);
                setSelPlTracks([]);
            })
            .finally(() => setSelPlLoading(false));
    }, [mode, selSource, selPlaylistId]);

    const selPool = selSource === 'playlist' ? selPlTracks : allTracks;
    const filteredSel = useMemo(() => filterTracks(selPool, selSearch), [selPool, selSearch]);
    const filteredSingle = useMemo(
        () => filterTracks(allTracks, singleSearch).slice(0, RENDER_CAP),
        [allTracks, singleSearch],
    );
    const filteredPlaylists = useMemo(() => {
        if (!plSearch.trim()) return playlists;
        const s = plSearch.toLowerCase();
        return playlists.filter((p) => (p.name || '').toLowerCase().includes(s));
    }, [playlists, plSearch]);

    // ── Emit scope on any change (onScopeChange must be stable) ──────────────
    useEffect(() => {
        let scope = null;
        let valid = false;
        let count = 0;
        if (mode === 'single') {
            valid = !!singleTrack;
            count = valid ? 1 : 0;
            scope = valid ? { kind: 'single', track_id: Number(tid(singleTrack)) } : null;
        } else if (mode === 'playlist') {
            valid = !!playlistId;
            count = null; // resolved server-side
            scope = valid ? { kind: 'playlist', playlist_id: String(playlistId) } : null;
        } else if (mode === 'selection') {
            valid = selectedIds.size > 0;
            count = selectedIds.size;
            scope = valid ? { kind: 'selection', track_ids: [...selectedIds].map(Number) } : null;
        } else {
            count = allTracks.length;
            valid = count > 0;
            scope = { kind: 'collection' };
        }
        onScopeChange?.({ scope, valid, count, mode });
    }, [mode, singleTrack, playlistId, selectedIds, allTracks.length, onScopeChange]);

    // ── Selection helpers ───────────────────────────────────────────────────
    const toggleId = (id) =>
        setSelectedIds((prev) => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id);
            else next.add(id);
            return next;
        });
    const allFilteredSelected =
        filteredSel.length > 0 && filteredSel.every((t) => selectedIds.has(Number(tid(t))));
    const toggleAllFiltered = () =>
        setSelectedIds((prev) => {
            const next = new Set(prev);
            if (allFilteredSelected) filteredSel.forEach((t) => next.delete(Number(tid(t))));
            else filteredSel.forEach((t) => next.add(Number(tid(t))));
            return next;
        });

    const switchMode = (m) => {
        setMode(m);
        // reset selections that don't apply so stale scope can't leak
        if (m !== 'selection') setSelectedIds(new Set());
    };

    // ── Render ──────────────────────────────────────────────────────────────
    return (
        <div className="mx-card rounded-mx-md p-4 space-y-3">
            <div className="mx-caption">Scope</div>

            {/* Mode tabs */}
            <div className="grid grid-cols-4 gap-2">
                {MODES.map((m) => {
                    const Icon = m.icon;
                    const active = mode === m.id;
                    return (
                        <button
                            key={m.id}
                            onClick={() => switchMode(m.id)}
                            className={`flex flex-col items-center gap-1 p-2.5 rounded-mx-sm border transition-all text-center ${
                                active
                                    ? 'bg-amber2/10 border-amber2/50 text-amber2'
                                    : 'border-line-subtle text-ink-muted hover:bg-mx-hover'
                            }`}
                        >
                            <Icon size={15} />
                            <span className="text-[11px] font-semibold">{m.label}</span>
                            <span className="text-[8px] opacity-70 leading-tight">{m.desc}</span>
                        </button>
                    );
                })}
            </div>

            {/* SINGLE */}
            {mode === 'single' && (
                <div>
                    {singleTrack ? (
                        <div className="flex items-center justify-between p-3 bg-amber2/5 border border-amber2/25 rounded-mx-sm">
                            <div className="min-w-0">
                                <p className="text-[13px] font-semibold text-ink-primary truncate">{tname(singleTrack)}</p>
                                <p className="text-ink-muted text-tiny truncate">{tartist(singleTrack)}</p>
                            </div>
                            <button
                                onClick={() => setSingleTrack(null)}
                                className="ml-3 text-[10px] text-ink-muted hover:text-ink-secondary underline shrink-0"
                            >
                                Change
                            </button>
                        </div>
                    ) : (
                        <div className="border border-line-subtle rounded-mx-sm overflow-hidden">
                            <SearchBox value={singleSearch} onChange={setSingleSearch} placeholder="Search title or artist…" loading={tracksLoading} />
                            <div className="max-h-56 overflow-y-auto divide-y divide-line-subtle">
                                {filteredSingle.length === 0 ? (
                                    <div className="p-4 text-center text-ink-muted text-tiny">
                                        {tracksLoading ? 'Loading…' : 'No tracks found'}
                                    </div>
                                ) : (
                                    filteredSingle.map((t, i) => (
                                        <button
                                            key={tid(t) ?? i}
                                            onClick={() => { setSingleTrack(t); setSingleSearch(''); }}
                                            className="w-full text-left px-3 py-2 hover:bg-mx-hover transition-colors"
                                        >
                                            <p className="text-[12px] text-ink-primary truncate">{tname(t)}</p>
                                            <p className="text-[10px] text-ink-muted truncate">{tartist(t)}</p>
                                        </button>
                                    ))
                                )}
                            </div>
                        </div>
                    )}
                </div>
            )}

            {/* PLAYLIST (whole) */}
            {mode === 'playlist' && (
                <div className="border border-line-subtle rounded-mx-sm overflow-hidden">
                    <SearchBox value={plSearch} onChange={setPlSearch} placeholder="Search playlists…" />
                    <div className="max-h-56 overflow-y-auto divide-y divide-line-subtle">
                        {filteredPlaylists.length === 0 ? (
                            <div className="p-4 text-center text-ink-muted text-tiny">No playlists</div>
                        ) : (
                            filteredPlaylists.map((p) => (
                                <button
                                    key={p.id}
                                    onClick={() => setPlaylistId(p.id)}
                                    className={`w-full flex items-center gap-2 text-left px-3 py-2 transition-colors ${
                                        playlistId === p.id ? 'bg-amber2/10 text-amber2' : 'hover:bg-mx-hover text-ink-primary'
                                    }`}
                                    style={{ paddingLeft: `${12 + p.depth * 14}px` }}
                                >
                                    <ListMusic size={12} className="shrink-0 opacity-70" />
                                    <span className="text-[12px] truncate">{p.name}</span>
                                    {playlistId === p.id && <ChevronRight size={12} className="ml-auto" />}
                                </button>
                            ))
                        )}
                    </div>
                </div>
            )}

            {/* SELECTION */}
            {mode === 'selection' && (
                <div className="space-y-2">
                    {/* source toggle */}
                    <div className="flex items-center gap-2">
                        {[
                            { id: 'collection', label: 'From Collection' },
                            { id: 'playlist', label: 'From Playlist' },
                        ].map((s) => (
                            <button
                                key={s.id}
                                onClick={() => setSelSource(s.id)}
                                className={`flex-1 py-1.5 text-[11px] rounded-mx-sm border transition-all ${
                                    selSource === s.id
                                        ? 'bg-amber2/10 border-amber2/50 text-amber2'
                                        : 'border-line-subtle text-ink-muted hover:bg-mx-hover'
                                }`}
                            >
                                {s.label}
                            </button>
                        ))}
                    </div>

                    {/* playlist chooser when source=playlist */}
                    {selSource === 'playlist' && (
                        <select
                            value={selPlaylistId || ''}
                            onChange={(e) => setSelPlaylistId(e.target.value || null)}
                            className="w-full bg-mx-input border border-line-subtle rounded-mx-sm px-3 py-2 text-[12px] text-ink-primary outline-none"
                        >
                            <option value="">Select a playlist…</option>
                            {playlists.map((p) => (
                                <option key={p.id} value={p.id}>
                                    {' '.repeat(p.depth * 2)}{p.name}
                                </option>
                            ))}
                        </select>
                    )}

                    {/* checklist */}
                    <div className="border border-line-subtle rounded-mx-sm overflow-hidden">
                        <SearchBox
                            value={selSearch}
                            onChange={setSelSearch}
                            placeholder="Search to filter…"
                            loading={selPlLoading || tracksLoading}
                        />
                        <div className="flex items-center justify-between px-3 py-1.5 bg-mx-shell border-b border-line-subtle">
                            <button
                                onClick={toggleAllFiltered}
                                className="flex items-center gap-1.5 text-[10px] text-ink-secondary hover:text-amber2"
                            >
                                {allFilteredSelected ? <CheckSquare size={12} /> : <Square size={12} />}
                                {allFilteredSelected ? 'Deselect' : 'Select'} shown ({filteredSel.length})
                            </button>
                            <span className="text-[10px] font-mono text-amber2">{selectedIds.size} selected</span>
                        </div>
                        <div className="max-h-56 overflow-y-auto divide-y divide-line-subtle">
                            {filteredSel.length === 0 ? (
                                <div className="p-4 text-center text-ink-muted text-tiny">
                                    {selPlLoading ? 'Loading…' : 'No tracks'}
                                </div>
                            ) : (
                                filteredSel.slice(0, RENDER_CAP).map((t, i) => {
                                    const id = Number(tid(t));
                                    const checked = selectedIds.has(id);
                                    return (
                                        <button
                                            key={id || i}
                                            onClick={() => toggleId(id)}
                                            className="w-full flex items-center gap-2.5 text-left px-3 py-2 hover:bg-mx-hover transition-colors"
                                        >
                                            {checked ? (
                                                <CheckSquare size={14} className="text-amber2 shrink-0" />
                                            ) : (
                                                <Square size={14} className="text-ink-muted shrink-0" />
                                            )}
                                            <div className="min-w-0">
                                                <p className="text-[12px] text-ink-primary truncate">{tname(t)}</p>
                                                <p className="text-[10px] text-ink-muted truncate">{tartist(t)}</p>
                                            </div>
                                        </button>
                                    );
                                })
                            )}
                            {filteredSel.length > RENDER_CAP && (
                                <div className="px-3 py-2 text-center text-[10px] text-ink-muted">
                                    Showing first {RENDER_CAP} of {filteredSel.length} — search to narrow
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            )}

            {/* COLLECTION */}
            {mode === 'collection' && (
                <div className="flex items-center gap-3 p-3 bg-amber2/5 border border-amber2/25 rounded-mx-sm">
                    <Library size={18} className="text-amber2 shrink-0" />
                    <div>
                        <p className="text-[13px] font-semibold text-ink-primary">Entire collection</p>
                        <p className="text-ink-muted text-tiny">
                            {tracksLoading ? 'Loading…' : `${allTracks.length} track(s) will be processed`}
                        </p>
                    </div>
                </div>
            )}
        </div>
    );
}
