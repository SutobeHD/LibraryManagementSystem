import { useCallback, useEffect, useRef, useState } from 'react';
import ReactDOM from 'react-dom';
import { toast } from 'react-hot-toast';
import { Check, Loader2, Search, Star, UserPlus, X } from 'lucide-react';

import api from '../../api/api';
import {
    ARTIST_ASSIGN_PICKER_LIMIT,
    ARTIST_ASSIGN_SEARCH_DEBOUNCE_MS,
} from '../../config/constants';
import { linksErrorMessage, setTrackAssignment } from './artistLinksApi';
import { ASSIGNABLE_ROLES, LOCAL_ROLE_LABEL } from './linksCopy';

/**
 * assignArtistModal — "Artist zuordnen…" from any track table in the app.
 *
 * Owner refinement 2026-09-26: a track the credits do not tie to an artist (a white
 * label, a bootleg tagged with the uploader's name) can be handed to that artist by
 * hand. The assignment lives in the artist store, keyed by the library's content id,
 * so the artist page, its counts and its Rekordbox playlist all pick it up.
 *
 *   const result = await assignArtistModal({ track });
 *   // → { collection_id, name, role } or null when cancelled
 *
 * Same singleton-host pattern as `PromptModal` / `ConfirmModal`: mount
 * `<AssignArtistModalRoot />` once near the app root.
 */

let pushRequest = null;
const pendingQueue = [];

export function assignArtistModal({ track } = {}) {
    return new Promise((resolve) => {
        const req = { track, resolve };
        if (pushRequest) pushRequest(req);
        else pendingQueue.push(req);
    });
}

const trackIdOf = (track) => track?.id ?? track?.ID ?? null;

const AssignDialog = ({ request, onDone }) => {
    const { track } = request;
    const [query, setQuery] = useState('');
    const [rows, setRows] = useState([]);
    const [loading, setLoading] = useState(false);
    const [picked, setPicked] = useState(null);
    const [role, setRole] = useState(ASSIGNABLE_ROLES[0]);
    const [saving, setSaving] = useState(false);
    const inputRef = useRef(null);
    const seqRef = useRef(0);

    const finish = useCallback(
        (value) => {
            request.resolve(value);
            onDone();
        },
        [request, onDone]
    );

    // Empty box → your favourites; typing → the whole library, server-filtered.
    useEffect(() => {
        const seq = (seqRef.current += 1);
        setLoading(true);
        const handle = setTimeout(
            async () => {
                try {
                    const text = query.trim();
                    const res = text
                        ? await api.get('/api/artists/browse', {
                              params: { q: text, limit: ARTIST_ASSIGN_PICKER_LIMIT },
                          })
                        : await api.get('/api/artists/hub', { params: { limit: 0 } });
                    if (seqRef.current !== seq) return;
                    const list = text ? res.data?.artists : res.data?.favourites;
                    setRows(Array.isArray(list) ? list : []);
                } catch (e) {
                    if (seqRef.current !== seq) return;
                    console.error('[AssignArtistModal] artist search failed', e);
                    setRows([]);
                } finally {
                    if (seqRef.current === seq) setLoading(false);
                }
            },
            query ? ARTIST_ASSIGN_SEARCH_DEBOUNCE_MS : 0
        );
        return () => clearTimeout(handle);
    }, [query]);

    useEffect(() => {
        const handle = setTimeout(() => inputRef.current?.focus(), 0);
        return () => clearTimeout(handle);
    }, []);

    // `target` lets a double-click save the row it names — `picked` is still the old
    // state inside the same event.
    const save = useCallback(
        async (target) => {
            const choice = target ?? picked;
            const id = trackIdOf(track);
            if (!choice || id == null) return;
            setSaving(true);
            try {
                await setTrackAssignment(choice.collection_id, id, {
                    action: 'assign',
                    role,
                    name: choice.name,
                });
                toast.success(`Assigned to ${choice.name} · ${LOCAL_ROLE_LABEL[role]}`);
                finish({ collection_id: choice.collection_id, name: choice.name, role });
            } catch (e) {
                console.error('[AssignArtistModal] assignment failed', e);
                toast.error(linksErrorMessage(e, 'Could not assign the track.'));
                setSaving(false);
            }
        },
        [finish, picked, role, track]
    );

    return (
        <div
            className="fixed inset-0 z-[300] flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in"
            onMouseDown={(e) => {
                if (e.target === e.currentTarget) finish(null);
            }}
            onKeyDown={(e) => {
                if (e.key === 'Escape') finish(null);
            }}
        >
            <div className="bg-mx-shell border border-white/10 rounded-xl p-5 w-[30rem] max-w-[92vw] shadow-2xl">
                <div className="flex justify-between items-start gap-3 mb-3">
                    <div className="min-w-0">
                        <h3 className="text-lg font-bold text-white flex items-center gap-2">
                            <UserPlus size={18} className="text-amber2" /> Assign to an artist
                        </h3>
                        <p className="text-[12px] text-ink-muted truncate mt-0.5">
                            {track?.Artist || '?'} – {track?.Title || '?'}
                        </p>
                    </div>
                    <button
                        type="button"
                        onClick={() => finish(null)}
                        className="text-ink-secondary hover:text-white"
                        aria-label="Close"
                    >
                        <X size={20} />
                    </button>
                </div>

                <div className="relative mb-2">
                    <Search
                        size={14}
                        className="absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted"
                    />
                    <input
                        ref={inputRef}
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        placeholder="Search your artists…"
                        className="input-glass w-full pl-9 text-sm"
                    />
                </div>

                <div className="h-56 overflow-y-auto rounded-mx-sm border border-line-subtle bg-mx-input/60">
                    {loading && rows.length === 0 ? (
                        <div className="flex items-center justify-center gap-2 h-full text-[12px] text-ink-muted">
                            <Loader2 size={14} className="animate-spin text-amber2" /> Searching…
                        </div>
                    ) : rows.length === 0 ? (
                        <div className="flex items-center justify-center h-full px-6 text-center text-[12px] text-ink-muted">
                            {query.trim()
                                ? 'No artist in your library matches that.'
                                : 'No favourites yet — type a name to search the whole library.'}
                        </div>
                    ) : (
                        rows.map((row) => {
                            const selected = picked?.collection_id === row.collection_id;
                            return (
                                <button
                                    key={row.collection_id}
                                    type="button"
                                    onClick={() => setPicked(row)}
                                    onDoubleClick={() => {
                                        setPicked(row);
                                        save(row);
                                    }}
                                    className={`w-full flex items-center gap-2 px-3 py-1.5 text-left text-[12.5px] transition-colors ${
                                        selected
                                            ? 'bg-amber2/10 text-amber2'
                                            : 'text-ink-secondary hover:bg-mx-hover'
                                    }`}
                                >
                                    {(row.is_favourite || row.favourite) && (
                                        <Star size={11} className="text-amber2 shrink-0" />
                                    )}
                                    <span className="truncate flex-1">{row.name}</span>
                                    <span className="font-mono text-[11px] text-ink-muted">
                                        {row.track_count ?? 0}
                                    </span>
                                    {selected && <Check size={13} className="shrink-0" />}
                                </button>
                            );
                        })
                    )}
                </div>

                <div className="mt-3">
                    <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-ink-muted mb-1.5">
                        As
                    </div>
                    <div className="flex flex-wrap gap-1">
                        {ASSIGNABLE_ROLES.map((value) => (
                            <button
                                key={value}
                                type="button"
                                onClick={() => setRole(value)}
                                className={`px-2.5 py-1 rounded-mx-xs text-[11px] border transition-colors ${
                                    role === value
                                        ? 'bg-amber2/10 text-amber2 border-amber2/40 font-semibold'
                                        : 'bg-mx-input text-ink-muted border-line-subtle hover:text-ink-secondary'
                                }`}
                            >
                                {LOCAL_ROLE_LABEL[value]}
                            </button>
                        ))}
                    </div>
                </div>

                <div className="flex justify-end gap-3 mt-5">
                    <button
                        type="button"
                        onClick={() => finish(null)}
                        className="px-4 py-2 text-sm font-medium text-ink-secondary hover:text-white transition-colors"
                    >
                        Cancel
                    </button>
                    <button
                        type="button"
                        onClick={() => save()}
                        disabled={!picked || saving || trackIdOf(track) == null}
                        className="px-4 py-2 text-sm font-medium bg-amber2 text-white rounded-lg transition-colors flex items-center gap-2 disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                        {saving ? (
                            <Loader2 size={16} className="animate-spin" />
                        ) : (
                            <Check size={16} />
                        )}
                        Assign
                    </button>
                </div>
            </div>
        </div>
    );
};

/** Singleton portal host — mount once near the app root, next to the other modal roots. */
export const AssignArtistModalRoot = () => {
    const [queue, setQueue] = useState([]);

    useEffect(() => {
        pushRequest = (req) => setQueue((q) => [...q, req]);
        if (pendingQueue.length) setQueue((q) => [...q, ...pendingQueue.splice(0)]);
        return () => {
            pushRequest = null;
        };
    }, []);

    if (queue.length === 0) return null;
    return ReactDOM.createPortal(
        <AssignDialog
            key={trackIdOf(queue[0].track) ?? 'assign'}
            request={queue[0]}
            onDone={() => setQueue((q) => q.slice(1))}
        />,
        document.body
    );
};

export default AssignArtistModalRoot;
