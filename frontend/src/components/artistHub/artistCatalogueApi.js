/**
 * artistCatalogueApi — the SoundCloud half of the Artist Hub's HTTP surface.
 *
 * Sibling of `artistHubApi.js` (merge + Rekordbox projection); kept apart because
 * these routes speak a different envelope and a different failure vocabulary.
 *
 * Routes (`app/main.py`, "ARTIST HUB: SoundCloud catalogue + batch download"):
 *
 *   GET    /api/artists/{id}/catalogue?refresh=  → discriminated union on `status`
 *   POST   /api/artists/{id}/link                → { status, collection_id, link, artist }
 *   DELETE /api/artists/{id}/link                → { status, collection_id, removed }
 *   POST   /api/artists/{id}/tracks/{urn}/role   → { status, sc_urn, identity }
 *   GET    /api/artists/{id}/identities          → { status, total, identities }
 *   POST   /api/artists/{id}/download-missing    → { status, data: { job_id, total, … } }
 *   GET    /api/artists/download/status?job_id=  → { status, data: job }
 *
 * The catalogue read is a **union, not an error channel**: `status: "ok"` carries the
 * role buckets, while `not_linked` / `not_connected` / `artist_gone` carry a `detail`
 * and no bucket keys at all. Callers must branch on `status` and render `detail`;
 * treating a typed state as an empty catalogue is the exact "looks live but is not"
 * failure this feature keeps hitting. An `ok` payload with `link_missing: true` is a
 * real by-name catalogue for an artist nobody bound — not an error state.
 */

import api from '../../api/api';
import {
    ARTIST_CATALOGUE_TIMEOUT_MS,
    ARTIST_DOWNLOAD_MAX_POLL_FAILURES,
    ARTIST_DOWNLOAD_POLL_INTERVAL_MS,
} from '../../config/constants';

const HTTP_NOT_FOUND = 404;
const HTTP_TOO_MANY = 429;

const JOB_DONE = 'done';
const JOB_TERMINAL = ['done', 'error', 'failed', 'cancelled'];

/** `POST /link` answers 401 with this machine string, not with a sentence. */
const AUTH_EXPIRED_DETAIL = 'auth_expired';

export const SC_SESSION_EXPIRED_MESSAGE =
    'The SoundCloud session expired. Sign in again under SoundCloud, then retry.';

export const SC_RATE_LIMITED_MESSAGE =
    'SoundCloud is rate-limiting this app right now. Wait for the limit to reset, then retry.';

const detailOf = (error) => {
    const detail = error?.response?.data?.detail;
    return typeof detail === 'string' && detail.trim() ? detail.trim() : '';
};

/** A sentence for the user — never a raw status code, never the literal `auth_expired`. */
export const catalogueErrorMessage = (error, fallback) => {
    const detail = detailOf(error);
    if (detail === AUTH_EXPIRED_DETAIL) return SC_SESSION_EXPIRED_MESSAGE;
    if (error?.response?.status === HTTP_TOO_MANY) return detail || SC_RATE_LIMITED_MESSAGE;
    return detail || error?.message || fallback;
};

export const isUnknownCollection = (error) => error?.response?.status === HTTP_NOT_FOUND;

const unwrap = (payload) => {
    if (payload && typeof payload === 'object' && !Array.isArray(payload)) {
        const inner = payload.data;
        if (inner && typeof inner === 'object' && !Array.isArray(inner)) return inner;
    }
    return payload;
};

const sleep = (ms) =>
    new Promise((resolve) => {
        setTimeout(resolve, ms);
    });

/**
 * One artist's catalogue. `refresh` forces past the sidecar's TTL cache and is the
 * only thing in this module that can cost a live SoundCloud call.
 */
export const fetchCatalogue = async (collectionId, { refresh = false } = {}) => {
    const res = await api.get(`/api/artists/${encodeURIComponent(collectionId)}/catalogue`, {
        params: { refresh },
        timeout: ARTIST_CATALOGUE_TIMEOUT_MS,
    });
    return res.data;
};

/** Bind the artist to a SoundCloud account from a profile URL or a bare permalink. */
export const linkSoundCloudProfile = async (collectionId, urlOrPermalink) => {
    const res = await api.post(
        `/api/artists/${encodeURIComponent(collectionId)}/link`,
        { url_or_permalink: urlOrPermalink },
        { timeout: ARTIST_CATALOGUE_TIMEOUT_MS }
    );
    return res.data;
};

/** Unbind. Idempotent — favourites, aliases and the cached catalogue survive. */
export const unlinkSoundCloudProfile = async (collectionId) => {
    const res = await api.delete(`/api/artists/${encodeURIComponent(collectionId)}/link`);
    return res.data;
};

/**
 * Queue a batch download.
 *
 * `autoQueue` lets the server pick, and it may then only pick tracks the identity
 * layer marked `auto_queue_allowed` (their tracks and their own remixes, at high or
 * medium confidence) that the diff proved missing. A review-bucket row or an excluded
 * set has to be named in `scIds`, so nothing uncertain is ever queued implicitly.
 */
export const startMissingDownload = async (
    collectionId,
    { scIds = [], autoQueue = false } = {}
) => {
    const res = await api.post(
        `/api/artists/${encodeURIComponent(collectionId)}/download-missing`,
        { sc_ids: scIds, auto_queue: autoQueue },
        { timeout: ARTIST_CATALOGUE_TIMEOUT_MS }
    );
    return unwrap(res.data);
};

export const fetchDownloadJob = async (jobId) => {
    const res = await api.get('/api/artists/download/status', { params: { job_id: jobId } });
    return unwrap(res.data);
};

/**
 * Poll one batch download to its end and resolve with the final job record.
 *
 * Resolves `null` when `isCancelled()` turns true (the view unmounted or the artist
 * changed) — the job keeps running server-side, which is why the caller must not
 * report anything about it once it stops watching.
 */
export const pollDownloadJob = async (jobId, { onProgress, isCancelled } = {}) => {
    let failures = 0;
    for (;;) {
        await sleep(ARTIST_DOWNLOAD_POLL_INTERVAL_MS);
        if (isCancelled?.()) return null;
        let job;
        try {
            job = await fetchDownloadJob(jobId);
            failures = 0;
        } catch (e) {
            // A 404 is terminal: the sidecar restarted and lost the in-process record.
            if (e?.response?.status === HTTP_NOT_FOUND) {
                throw new Error('The backend lost this download job (was it restarted?).');
            }
            failures += 1;
            if (failures >= ARTIST_DOWNLOAD_MAX_POLL_FAILURES) throw e;
            continue;
        }
        if (!job) continue;
        onProgress?.(job);
        if (JOB_TERMINAL.includes(job.status)) {
            if (job.status !== JOB_DONE && job.status !== 'cancelled' && job.error) {
                throw new Error(job.error);
            }
            return job;
        }
    }
};

/**
 * Pin one catalogue track's role for this artist. `role: null` clears the pin.
 *
 * The classifier reads a name; the user knows. The pin is stored in the sidecar's
 * `track_identity` table and wins over the classifier on every later read, so the row
 * stays where the user put it. 404 means the track has no identity row yet — the
 * artist's catalogue has to have been read once first.
 */
export const pinTrackRole = async (collectionId, scUrn, role) => {
    const res = await api.post(
        `/api/artists/${encodeURIComponent(collectionId)}/tracks/${encodeURIComponent(scUrn)}/role`,
        { role: role ?? null }
    );
    return res.data;
};

/** The local artist→track identity table. Read-only, no SoundCloud call. */
export const fetchTrackIdentities = async (collectionId) => {
    const res = await api.get(`/api/artists/${encodeURIComponent(collectionId)}/identities`);
    return res.data;
};
