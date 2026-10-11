/**
 * artistHubApi — the merge + projection half of the Artist Hub's HTTP surface.
 *
 * One module so the request shapes live in one place and the job polling is not
 * copy-pasted into three components. Everything goes through the shared axios
 * instance (`src/api/api.js`) — Bearer token, baseURL and the 401 handling come
 * with it.
 *
 * Routes (`app/main.py`, "ARTIST HUB: merge + Rekordbox projection"):
 *
 *   GET  /api/artists/merge/candidates      → { candidates: [MergeCandidate], total }
 *   POST /api/artists/merge/preview         → MergePreview        (pure, no write)
 *   POST /api/artists/merge/apply           → { status, data: { job_id, total, … } }
 *   POST /api/artists/merge/revert/{run_id} → { status, data: { job_id, total, … } }
 *   GET  /api/artists/merge/runs            → { runs: [journal run + parsed note] }
 *   GET  /api/artists/jobs/{job_id}         → { status, data: job }
 *   POST /api/artists/projection/sync       → { status, data: { job_id, total, … } }
 *   GET  /api/artists/projection/status     → projection.status()
 *
 * All three writers are background jobs behind ONE single-flight lock, so a
 * second one while the first runs is a 409 — that is a different 409 from
 * "Rekordbox holds the library", and `errorMessage` keeps them apart instead of
 * blaming Rekordbox for a busy queue.
 *
 * Result payloads are the `as_dict()` of the dataclasses in
 * `app/artist_store/merge.py` and the report dict of
 * `app/artist_store/projection.py`.
 */

import api from '../../api/api';
import {
    ARTIST_LONG_OP_TIMEOUT_MS,
    ARTIST_MERGE_MAX_POLL_FAILURES,
    ARTIST_MERGE_POLL_INTERVAL_MS,
} from '../../config/constants';

const HTTP_CONFLICT = 409;
const JOB_DONE = 'done';
const JOB_FAILED = ['error', 'failed', 'cancelled'];

/** Rekordbox holds the library — the 409 every writer in this feature can return. */
export const REKORDBOX_RUNNING_MESSAGE =
    'Rekordbox is open and holds the library. Close Rekordbox, then run this again.';

const detailOf = (error) => {
    const detail = error?.response?.data?.detail;
    return typeof detail === 'string' && detail.trim() ? detail.trim() : '';
};

export const isRekordboxRunning = (error) =>
    error?.response?.status === HTTP_CONFLICT && /rekordbox/i.test(detailOf(error));

/** A sentence for the user: the 409 in plain words, else the backend detail. */
export const errorMessage = (error, fallback) => {
    if (isRekordboxRunning(error)) return REKORDBOX_RUNNING_MESSAGE;
    return detailOf(error) || error?.message || fallback;
};

// The job routes answer `{status:'ok', data:{…}}` (the phrase-batch envelope);
// the read routes answer the payload directly. Accept both.
const unwrap = (payload) => {
    if (payload && typeof payload === 'object' && !Array.isArray(payload)) {
        const inner = payload.data;
        if (inner && typeof inner === 'object' && !Array.isArray(inner)) return inner;
    }
    return payload;
};

const listOf = (payload, key) => {
    const body = unwrap(payload);
    if (Array.isArray(body)) return body;
    if (Array.isArray(body?.[key])) return body[key];
    return [];
};

const sleep = (ms) =>
    new Promise((resolve) => {
        setTimeout(resolve, ms);
    });

/** The run note comes back parsed; tolerate the raw JSON string too. */
const parseRunNote = (note) => {
    if (note && typeof note === 'object') return note;
    if (typeof note !== 'string' || !note.trim()) return {};
    try {
        const parsed = JSON.parse(note);
        return parsed && typeof parsed === 'object' ? parsed : {};
    } catch {
        return {};
    }
};

const normaliseRun = (run) => {
    const note = parseRunNote(run?.note);
    return {
        run_id: run?.run_id ?? '',
        created_at: run?.created_at ?? null,
        status: run?.status ?? 'unknown',
        mutation_count: run?.mutation_count ?? 0,
        canonical: note.canonical ?? '',
        absorbing: Array.isArray(note.absorbing) ? note.absorbing : [],
        tracks: note.tracks ?? null,
        delete_orphans: !!note.delete_orphans,
    };
};

/**
 * Poll one artist-hub job to its end and return the engine's report.
 *
 * Resolves `null` when `isCancelled()` turns true (the caller unmounted) — the
 * job keeps running server-side and, for a merge, stays revertable from the
 * journal. `done` steps 0 → total in one move because the engines run as a
 * single atomic pass; `onProgress` still fires per poll so the UI can show that
 * it is alive.
 */
const pollArtistJob = async (jobId, { onProgress, isCancelled } = {}) => {
    let failures = 0;
    for (;;) {
        await sleep(ARTIST_MERGE_POLL_INTERVAL_MS);
        if (isCancelled?.()) return null;
        let job;
        try {
            const res = await api.get(`/api/artists/jobs/${encodeURIComponent(jobId)}`);
            job = unwrap(res.data);
            failures = 0;
        } catch (e) {
            // A 404 is terminal — the sidecar restarted and lost the job record.
            if (e?.response?.status === 404) {
                throw new Error('The backend lost this job (was it restarted?).');
            }
            failures += 1;
            if (failures >= ARTIST_MERGE_MAX_POLL_FAILURES) throw e;
            continue;
        }
        if (!job) continue;
        onProgress?.(job);
        if (job.status === JOB_DONE) return job.result ?? job;
        if (JOB_FAILED.includes(job.status)) {
            throw new Error(job.error || 'The job failed.');
        }
    }
};

const startJob = async (url, body) => {
    const res = await api.post(url, body, { timeout: ARTIST_LONG_OP_TIMEOUT_MS });
    return unwrap(res.data);
};

export const fetchMergeCandidates = async () => {
    const res = await api.get('/api/artists/merge/candidates');
    return listOf(res.data, 'candidates');
};

export const fetchMergePreview = async ({ names, canonical }) => {
    const res = await api.post('/api/artists/merge/preview', { names, canonical });
    return unwrap(res.data);
};

export const fetchMergeRuns = async () => {
    const res = await api.get('/api/artists/merge/runs');
    return listOf(res.data, 'runs').map(normaliseRun);
};

/** Start a merge and resolve with its `MergeApplyResult` (or `null` if cancelled). */
export const applyMerge = async ({ names, canonical, deleteOrphans }, hooks = {}) => {
    const started = await startJob('/api/artists/merge/apply', {
        names,
        canonical,
        delete_orphans: !!deleteOrphans,
    });
    hooks.onProgress?.({ status: 'running', done: 0, total: started?.total ?? 0, percent: 0 });
    return pollArtistJob(started.job_id, hooks);
};

/** Replay one merge run backwards; resolves with its `MergeRevertResult`. */
export const revertMergeRun = async (runId, hooks = {}) => {
    const started = await startJob(`/api/artists/merge/revert/${encodeURIComponent(runId)}`, {});
    hooks.onProgress?.({ status: 'running', done: 0, total: started?.total ?? 0, percent: 0 });
    return pollArtistJob(started.job_id, hooks);
};

export const fetchProjectionStatus = async () => {
    const res = await api.get('/api/artists/projection/status');
    return unwrap(res.data);
};

/** Mirror the favourites into Rekordbox; resolves with the projection report. */
export const syncProjection = async (hooks = {}) => {
    const started = await startJob('/api/artists/projection/sync', { dry_run: false });
    hooks.onProgress?.({ status: 'running', done: 0, total: started?.total ?? 0, percent: 0 });
    return pollArtistJob(started.job_id, hooks);
};
