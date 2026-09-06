/**
 * catalogueCopy — the sentences the artist-detail view has to say out loud.
 *
 * Pure string builders, no React, no network — the same split `mergeCopy.js` uses,
 * and for the same reason: this screen has twice shipped controls that looked live
 * but were not, so every line it prints has to be derived from a real payload field
 * and testable on its own.
 *
 * Rules encoded here:
 *  1. Never invent a number. A count comes from the response or the sentence drops.
 *  2. A cached catalogue says when it was fetched; a truncated one says it is cut
 *     short, because "not listed" would otherwise read as "you own everything".
 *  3. A finished download reports what actually landed — downloaded / skipped /
 *     failed — never a blanket "done".
 *
 * Payload shapes: `app/artist_store/catalogue.py::catalogue` (wrapped by
 * `app/main.py::_artist_catalogue_view`) and the job record of
 * `app/main.py::_artist_download_job_record`.
 */

const SECOND_MS = 1000;
const MINUTE_MS = 60 * SECOND_MS;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;
const SECONDS_PER_MINUTE = 60;
const SECONDS_PAD = 2;

/**
 * The buckets and the counts the detail view renders, derived in one place.
 *
 * `in_library` is deliberately three-valued: `true` owned, `false` genuinely missing,
 * `null` never checked (the excluded mixes are not diffed at all). Only an explicit
 * `false` counts as missing here — treating `null` as missing would invent a gap.
 *
 * `queueable` mirrors the server's own `auto_queue_allowed` flag rather than
 * recomputing the rule, so the number on the "Download all missing" button is exactly
 * the number of tracks the backend will queue.
 */
export const splitCatalogue = (view) => {
    const ok = view?.status === 'ok';
    const theirs = (
        ok && Array.isArray(view.definitely_theirs) ? view.definitely_theirs : []
    ).slice();
    const remixes = (
        ok && Array.isArray(view.remixes_by_others) ? view.remixes_by_others : []
    ).slice();
    const mixes = (ok && Array.isArray(view.mixes_and_sets) ? view.mixes_and_sets : []).slice();
    const missingTheirs = theirs.filter((t) => t.in_library === false);
    const missingRemixes = remixes.filter((t) => t.in_library === false);
    return {
        ok,
        theirs,
        remixes,
        mixes,
        missingTheirs,
        missingRemixes,
        ownedTheirs: theirs.filter((t) => t.in_library === true).length,
        queueable: missingTheirs.filter((t) => t.auto_queue_allowed === true),
    };
};

/** "just now" / "5 min ago" / "3 h ago" / a local date. `null` when there is no stamp. */
export const relativeTime = (iso) => {
    if (!iso) return null;
    const parsed = new Date(iso);
    if (Number.isNaN(parsed.getTime())) return String(iso);
    const delta = Date.now() - parsed.getTime();
    if (delta < MINUTE_MS) return 'just now';
    if (delta < HOUR_MS) return `${Math.round(delta / MINUTE_MS)} min ago`;
    if (delta < DAY_MS) return `${Math.round(delta / HOUR_MS)} h ago`;
    return parsed.toLocaleDateString();
};

/** `4:38` from milliseconds. Empty string when the payload carried no duration. */
export const formatDuration = (ms) => {
    const n = Number(ms);
    if (!Number.isFinite(n) || n <= 0) return '';
    const total = Math.round(n / SECOND_MS);
    const minutes = Math.floor(total / SECONDS_PER_MINUTE);
    const seconds = total % SECONDS_PER_MINUTE;
    return `${minutes}:${String(seconds).padStart(SECONDS_PAD, '0')}`;
};

/** Local date for a SoundCloud `created_at`. Empty when unparseable — never "Invalid Date". */
export const formatDate = (iso) => {
    if (!iso) return '';
    const parsed = new Date(iso);
    return Number.isNaN(parsed.getTime()) ? '' : parsed.toLocaleDateString();
};

/**
 * The typed non-`ok` states of the catalogue route, in plain words.
 *
 * The backend already sends a full sentence in `detail`; these are the fallback for
 * a response that somehow arrives without one, so the panel never renders an empty
 * explanation next to an empty list.
 */
export const STATE_FALLBACK = {
    not_linked: 'No SoundCloud account is linked to this artist yet.',
    link_unresolved:
        'This artist carries an imported SoundCloud URL that was never resolved to an account.',
    not_connected: 'SoundCloud is not connected, so the catalogue could not be read.',
    artist_gone: 'SoundCloud no longer serves this account — deleted, private or renamed.',
};

export const stateSentence = (view) => {
    const detail = typeof view?.detail === 'string' ? view.detail.trim() : '';
    if (detail) return detail;
    return STATE_FALLBACK[view?.status] || 'The catalogue is unavailable for this artist.';
};

/** Where this list came from and when. Only ever built from a real `status: "ok"` payload. */
export const fetchedLine = (view) => {
    if (!view || view.status !== 'ok') return '';
    const ago = relativeTime(view.fetched_at);
    if (!ago) return view.from_cache ? 'Served from the local cache.' : 'Fetched from SoundCloud.';
    return view.from_cache
        ? `Served from the local cache · fetched ${ago}`
        : `Fetched from SoundCloud ${ago}`;
};

/** The one thing a truncated catalogue must not be allowed to imply. */
export const truncationNote = (view) =>
    view?.truncated
        ? 'Cut short by the per-run call cap — this is part of the catalogue, not all of it, ' +
          'so a track that is not listed here is not proof that you own it.'
        : '';

/** "0 of 25 SoundCloud calls used". Empty when the payload carried no budget. */
export const callBudgetLine = (view) => {
    if (!view || view.status !== 'ok') return '';
    const used = Number(view.calls_used);
    const cap = Number(view.call_budget);
    if (!Number.isFinite(used) || !Number.isFinite(cap) || cap <= 0) return '';
    return `${used} of ${cap} SoundCloud calls used`;
};

/** Why a track sits in the excluded strip instead of the missing list. */
export const EXCLUSION_REASON_TEXT = {
    long_form: 'longer than 15 minutes',
    keyword:
        'the title, tags or genre match the mix/set rule (dj set, radio show, boiler room, b2b…)',
    unavailable: 'SoundCloud does not serve this account a full stream — preview only, or blocked',
};

export const exclusionReason = (track) =>
    EXCLUSION_REASON_TEXT[track?.excluded_reason] || 'excluded by the mix/set rule';

/** The rule, in one sentence, printed on the collapsed strip itself. */
export const MIXES_RULE_SENTENCE =
    'Anything longer than 15 minutes, matching a mix/set keyword (dj set, radio show, boiler ' +
    'room, b2b…), or that SoundCloud will not stream in full is kept out of the missing count — ' +
    'expand to download a single one anyway.';

export const REMIX_RULE_SENTENCE =
    'Uploaded by someone else, with this artist named only in the title, the tags or the ' +
    'uploader name. Downloadable one by one, never queued for you by "Download all missing".';

/** Live progress for a running batch. `done` steps once per finished track. */
export const progressLine = (job) => {
    if (!job) return '';
    const total = Number(job.total) || 0;
    const done = Number(job.done) || 0;
    const position = total ? Math.min(done + 1, total) : done;
    const title = job.current_track?.title;
    const head = total ? `Track ${position} of ${total}` : 'Starting…';
    return title ? `${head} — ${title}` : head;
};

/**
 * What actually landed. Deliberately never "done": a run where every track failed
 * and a run where every track succeeded produce the same word otherwise.
 */
export const downloadSummary = (job) => {
    if (!job) return '';
    const total = Number(job.total) || 0;
    const succeeded = Number(job.succeeded) || 0;
    const skipped = Number(job.skipped) || 0;
    const failed = Number(job.failed) || 0;
    const parts = [`${succeeded} downloaded`];
    if (skipped) parts.push(`${skipped} skipped`);
    if (failed) parts.push(`${failed} failed`);
    const cancelled = job.status === 'cancelled' ? ', run cancelled' : '';
    return `${parts.join(' · ')} of ${total} queued${cancelled}`;
};

/** Which toast a finished run deserves. A partial run is not a success. */
export const downloadTone = (job) => {
    if (!job) return 'neutral';
    if ((Number(job.failed) || 0) > 0 || job.status === 'error') return 'error';
    if ((Number(job.succeeded) || 0) === 0) return 'neutral';
    if ((Number(job.skipped) || 0) > 0 || job.status === 'cancelled') return 'neutral';
    return 'success';
};

/** The note under the missing panel — what a download run will actually do. */
export const DOWNLOAD_PATH_NOTE =
    'Downloads run one at a time through the existing SoundCloud downloader, so analysis, ' +
    'auto-import and the ANLZ write happen exactly as for a single-track download. Preview-only ' +
    'tracks are skipped and reported, never downloaded as a snippet.';

// The remixes bucket can only ever be filled from the reposts path. When that path
// was not queried — no budget left, a failed call, or a cache hit that predates it —
// an empty list means "we did not look", NOT "nothing is missing". Saying the latter
// would be a claim about SoundCloud data that was never fetched.
export const REPOSTS_STATUS_TEXT = {
    ok: 'No remix by another uploader is missing from your library.',
    failed: 'The reposts path could not be reached, so remixes by other uploaders were not checked. Refresh to try again.',
    skipped_budget:
        'The per-run call budget ran out before the reposts path was queried, so remixes by other uploaders were not checked.',
    not_queried:
        'This view came from the cache, so remixes by other uploaders were not queried on this pass. Refresh to check them.',
};

export const repostsNote = (status) =>
    REPOSTS_STATUS_TEXT[status] ?? REPOSTS_STATUS_TEXT.not_queried;
