import { useCallback, useEffect, useRef, useState } from 'react';

import {
    catalogueErrorMessage,
    fetchCatalogue,
    isUnknownCollection,
    linkSoundCloudProfile,
    pinTrackRole,
    pollDownloadJob,
    startMissingDownload,
    unlinkSoundCloudProfile,
} from './artistCatalogueApi';
import { BUCKETS, MIXES_BUCKET } from './catalogueCopy';

const ROLE_BUCKET = {
    primary: 'their_tracks',
    remixer: 'their_remixes',
    remixed_by_other: 'remixed_by_others',
    featured: 'featured',
    uncertain: 'uncertain',
};

/**
 * Move one row into the bucket its new role renders in — the optimistic half of a pin.
 *
 * `role: null` (clearing a pin) cannot be predicted here: only the classifier knows
 * where the row goes back to, so the view is left untouched and the reload that follows
 * shows the answer. An excluded mix never moves either: the mix/set gate runs before
 * roles, so a pin does not lift it out of the strip.
 */
export const movePinnedRow = (view, scId, role) => {
    const target = ROLE_BUCKET[role];
    if (!view || view.status !== 'ok' || !target) return view;
    let moved = null;
    const next = { ...view };
    for (const bucket of BUCKETS) {
        const rows = Array.isArray(view[bucket.key]) ? view[bucket.key] : [];
        const hit = rows.find((t) => t.sc_id === scId);
        if (hit && bucket.key === MIXES_BUCKET) return view;
        if (hit) {
            moved = { ...hit, role, identity_source: 'user_override', confidence: 'high' };
            next[bucket.key] = rows.filter((t) => t.sc_id !== scId);
        } else {
            next[bucket.key] = rows;
        }
    }
    if (!moved) return view;
    moved.auto_queue_allowed =
        moved.in_library === false && (role === 'primary' || role === 'remixer');
    next[target] = [...next[target], moved];
    return next;
};

/**
 * useArtistCatalogue — catalogue state for exactly one selected artist.
 *
 * ToU guardrail this hook implements (owner decision, see
 * `docs/research/implement/inprogress_library-artist-hub.md`): the catalogue is read
 * **when the user selects an artist**, never speculatively and never for an artist
 * nobody bound. `enabled` is what enforces it — the caller passes false for an artist
 * that is neither favourited nor already linked, and then nothing is requested at all.
 *
 * What it deliberately does NOT do:
 *  - turn a typed state (`not_linked`, `not_connected`, …) into an error or an empty
 *    list. Those are successful answers and are handed back in `view` verbatim.
 *  - report anything about a download job it stopped watching. Switching artist
 *    cancels the poll; the run continues server-side and is not summarised here.
 *  - leave a role pin showing after the server refused it. `pinRole` moves the row
 *    optimistically and puts the whole previous view back if the call fails, so the
 *    screen never shows a classification the sidecar did not store.
 */
const useArtistCatalogue = ({ collectionId, enabled = true }) => {
    const [view, setView] = useState(null);
    const [loading, setLoading] = useState(false);
    const [refreshing, setRefreshing] = useState(false);
    const [error, setError] = useState('');
    const [linking, setLinking] = useState(false);
    const [job, setJob] = useState(null);
    const [downloading, setDownloading] = useState(false);
    const [result, setResult] = useState(null);

    // Every async result is stamped with the sequence it started in, so a slow
    // response for the previous artist can never land in this artist's panel.
    const seqRef = useRef(0);
    const currentRef = useRef(collectionId);

    useEffect(() => {
        currentRef.current = collectionId;
        seqRef.current += 1;
        setView(null);
        setError('');
        setJob(null);
        setResult(null);
        setDownloading(false);
        setLoading(false);
        setRefreshing(false);
    }, [collectionId]);

    const load = useCallback(
        async ({ refresh = false } = {}) => {
            if (!collectionId || !enabled) return null;
            const seq = (seqRef.current += 1);
            if (refresh) setRefreshing(true);
            else setLoading(true);
            try {
                const payload = await fetchCatalogue(collectionId, { refresh });
                if (seqRef.current !== seq) return null;
                setView(payload);
                setError('');
                return payload;
            } catch (e) {
                if (seqRef.current !== seq) return null;
                console.error('[ArtistHub] catalogue read failed', e);
                setError(
                    isUnknownCollection(e)
                        ? 'This artist is not in the artist store yet — add them to your ' +
                              'favourites first, then link a SoundCloud profile.'
                        : catalogueErrorMessage(e, 'Could not read the SoundCloud catalogue.')
                );
                return null;
            } finally {
                if (seqRef.current === seq) {
                    setLoading(false);
                    setRefreshing(false);
                }
            }
        },
        [collectionId, enabled]
    );

    // The one fetch trigger: an artist got selected (or the caller enabled it).
    useEffect(() => {
        if (!collectionId || !enabled) return;
        load();
    }, [collectionId, enabled, load]);

    /** Bind a profile URL / permalink. Returns the bound account, or throws for the caller's toast. */
    const link = useCallback(
        async (urlOrPermalink) => {
            if (!collectionId) return null;
            setLinking(true);
            try {
                const payload = await linkSoundCloudProfile(collectionId, urlOrPermalink);
                await load();
                return payload?.artist ?? null;
            } finally {
                setLinking(false);
            }
        },
        [collectionId, load]
    );

    const unlink = useCallback(async () => {
        if (!collectionId) return false;
        setLinking(true);
        try {
            const payload = await unlinkSoundCloudProfile(collectionId);
            await load();
            return !!payload?.removed;
        } finally {
            setLinking(false);
        }
    }, [collectionId, load]);

    /**
     * Start a batch download and watch it to the end.
     *
     * Resolves with the final job record, or `null` when the view stopped watching.
     * The catalogue is re-read afterwards so the owned/missing split reflects what
     * landed instead of the split the run started from.
     */
    const download = useCallback(
        async ({ scIds = [], autoQueue = false } = {}) => {
            if (!collectionId) return null;
            const seq = seqRef.current;
            setDownloading(true);
            setResult(null);
            try {
                const started = await startMissingDownload(collectionId, { scIds, autoQueue });
                if (seqRef.current !== seq) return null;
                setJob({ status: 'running', total: started?.total ?? 0, done: 0, percent: 0 });
                const finished = await pollDownloadJob(started.job_id, {
                    onProgress: (next) => {
                        if (seqRef.current === seq) setJob(next);
                    },
                    isCancelled: () => seqRef.current !== seq,
                });
                if (seqRef.current !== seq || !finished) return null;
                setResult(finished);
                await load();
                return finished;
            } finally {
                if (seqRef.current === seq) {
                    setDownloading(false);
                    setJob(null);
                }
            }
        },
        [collectionId, load]
    );

    /**
     * Pin a track's role and move it between buckets at once.
     *
     * The row jumps immediately — the server's answer is the classification the next
     * read will produce anyway — but the pre-click view is kept and restored verbatim
     * if the call fails, because a row sitting in a bucket the sidecar never accepted
     * is exactly the "looks live but is not" failure this screen keeps shipping.
     * Throws for the caller's toast.
     */
    const pinRole = useCallback(
        async (scId, role) => {
            if (!collectionId || !scId) return null;
            const seq = seqRef.current;
            const previous = view;
            setView((current) => movePinnedRow(current, scId, role));
            try {
                return await pinTrackRole(collectionId, scId, role);
            } catch (e) {
                if (seqRef.current === seq) setView(previous);
                throw e;
            }
        },
        [collectionId, view]
    );

    // Nothing may be reported about a run this hook is no longer watching.
    useEffect(
        () => () => {
            seqRef.current += 1;
        },
        []
    );

    return {
        view,
        loading,
        refreshing,
        error,
        linking,
        job,
        downloading,
        result,
        reload: load,
        link,
        unlink,
        download,
        pinRole,
        clearResult: () => setResult(null),
    };
};

export default useArtistCatalogue;
