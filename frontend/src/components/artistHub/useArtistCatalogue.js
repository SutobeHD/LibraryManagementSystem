import { useCallback, useEffect, useRef, useState } from 'react';

import {
    catalogueErrorMessage,
    fetchCatalogue,
    isUnknownCollection,
    linkSoundCloudProfile,
    pollDownloadJob,
    startMissingDownload,
    unlinkSoundCloudProfile,
} from './artistCatalogueApi';

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
        clearResult: () => setResult(null),
    };
};

export default useArtistCatalogue;
