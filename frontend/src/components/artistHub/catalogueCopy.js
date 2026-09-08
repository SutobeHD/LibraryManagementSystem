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
 *  3. A bucket may only be called empty when every source that feeds it came back
 *     `ok`. A source that was never queried gets said out loud instead.
 *  4. A finished download reports what actually landed — downloaded / skipped /
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
 * The rendered buckets, in the owner's order. One per identity role plus the
 * collapsed mix/set strip. `key` matches the backend payload key exactly.
 */
export const BUCKETS = [
    {
        key: 'their_tracks',
        label: 'Their tracks',
        blurb: 'This artist is the main credit — by their own account, by the title, or by the uploader name.',
    },
    {
        key: 'their_remixes',
        label: 'Their remixes',
        blurb: 'Their remix, edit or flip of someone else’s track. This is their music, so "Download all missing" includes it.',
    },
    {
        key: 'remixed_by_others',
        label: 'Remixed by others',
        blurb: 'Their track, remixed by somebody else. Listed for review, never queued for you — download a row by hand.',
    },
    {
        key: 'featured',
        label: 'Featured on',
        blurb: 'A "feat." / "ft." credit only. Review bucket: download a row by hand if you want it.',
    },
    {
        key: 'uncertain',
        label: 'Uncertain — review',
        blurb: 'The name turned up in the tags, in a near-spelling, or in an unparseable mention. Nothing here is claimed as theirs.',
    },
    {
        key: 'mixes_and_sets',
        label: 'Mixes & sets — excluded',
        blurb: 'Kept out of every missing count by the mix/set rule. Still downloadable one at a time.',
    },
];

export const MIXES_BUCKET = 'mixes_and_sets';

/** Human labels for a role, used by the per-row pin menu and the row itself. */
export const ROLE_LABEL = {
    primary: 'Their track',
    remixer: 'Their remix',
    remixed_by_other: 'Remixed by someone else',
    featured: 'Featured credit',
    uncertain: 'Uncertain',
};

/** What the pin menu offers. `null` clears the pin and hands the row back to the classifier. */
export const ROLE_OPTIONS = [
    { value: 'primary', label: ROLE_LABEL.primary },
    { value: 'remixer', label: ROLE_LABEL.remixer },
    { value: 'remixed_by_other', label: ROLE_LABEL.remixed_by_other },
    { value: 'featured', label: ROLE_LABEL.featured },
    { value: 'uncertain', label: ROLE_LABEL.uncertain },
    { value: null, label: 'Clear pin — let the classifier decide' },
];

export const CONFIDENCE_LABEL = {
    high: 'high confidence',
    medium: 'medium confidence',
    low: 'low confidence',
};

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
    const rows = {};
    const missing = {};
    const counts = {};
    const missingCounts = {};
    let total = 0;
    let queueable = [];

    for (const bucket of BUCKETS) {
        const list = ok && Array.isArray(view[bucket.key]) ? view[bucket.key].slice() : [];
        rows[bucket.key] = list;
        counts[bucket.key] = list.length;
        const gaps = list.filter((t) => t.in_library === false);
        missing[bucket.key] = gaps;
        missingCounts[bucket.key] = gaps.length;
        total += list.length;
        queueable = queueable.concat(list.filter((t) => t.auto_queue_allowed === true));
    }

    return {
        ok,
        rows,
        missing,
        counts,
        missingCounts,
        total,
        queueable,
        linkMissing: ok ? view.link_missing === true : null,
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
    not_linked:
        'No SoundCloud account is linked to this artist and there is no name to search for.',
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

// ─── Per-source status ────────────────────────────────────────────────────────
//
// Three sources fill the buckets: the artist's own uploads, a search across every
// spelling they answer to, and their reposts. Each reports its own `ok` / `failed` /
// `skipped_budget` / `not_queried`. An empty bucket is only "nothing missing" when
// every source came back `ok`; otherwise it means nobody looked, and saying anything
// else is a claim about data that was never fetched.

export const SOURCES = [
    { key: 'uploads', label: 'Uploads', needsLink: true },
    { key: 'search', label: 'Search', needsLink: false },
    { key: 'reposts', label: 'Reposts', needsLink: true },
];

export const SOURCE_STATUS_TEXT = {
    ok: 'queried',
    failed: 'could not be reached',
    skipped_budget: 'not queried (the per-run call budget ran out)',
    not_queried: 'not queried on this pass',
};

const SOURCE_STATUS_SHORT = {
    ok: '✓',
    failed: 'failed',
    skipped_budget: 'not queried (budget)',
    not_queried: 'not queried',
};

/** One entry per source: its status, a short chip word and a full sentence fragment. */
export const sourceStates = (view) => {
    if (!view || view.status !== 'ok') return [];
    const sources = view.sources || {};
    const unlinked = view.link_missing === true;
    return SOURCES.map((source) => {
        const status = sources[source.key] || 'not_queried';
        const blockedByLink = unlinked && source.needsLink && status === 'not_queried';
        return {
            key: source.key,
            label: source.label,
            status,
            ok: status === 'ok',
            short: blockedByLink ? 'not queried (no linked account)' : SOURCE_STATUS_SHORT[status],
            text: blockedByLink
                ? 'not queried — no SoundCloud account is linked to this artist'
                : SOURCE_STATUS_TEXT[status] || SOURCE_STATUS_TEXT.not_queried,
        };
    });
};

/** "Uploads ✓ · Search ✓ · Reposts not queried (budget)". Empty for a non-`ok` payload. */
export const sourceStatusLine = (view) =>
    sourceStates(view)
        .map((source) => `${source.label} ${source.short}`)
        .join(' · ');

/** Did every source actually run? Only then may an empty bucket be called empty. */
export const allSourcesOk = (view) => {
    const states = sourceStates(view);
    return states.length > 0 && states.every((source) => source.ok);
};

const BUCKET_NOTHING_MISSING = {
    their_tracks: 'Nothing from this artist’s own tracks is missing from your library.',
    their_remixes: 'None of this artist’s own remixes is missing from your library.',
    remixed_by_others: 'No remix of their work by another artist is missing from your library.',
    featured: 'Nothing they are featured on is missing from your library.',
    uncertain: 'Nothing needs reviewing — every track found carried a credit we could read.',
    mixes_and_sets: 'Nothing was excluded by the mix/set rule.',
};

/**
 * What an empty bucket is allowed to say.
 *
 * The successor to the old `repostsNote`, widened to all three sources: the positive
 * sentence only fires when every source came back `ok`. Otherwise the line names the
 * sources that did not run, because an empty list from an unqueried source is not
 * evidence of absence.
 */
export const bucketEmptyNote = (view, bucketKey) => {
    const states = sourceStates(view);
    if (states.length === 0) {
        return 'No catalogue has been read for this artist yet, so nothing can be said about this list.';
    }
    const notOk = states.filter((source) => !source.ok);
    if (notOk.length === 0) {
        return BUCKET_NOTHING_MISSING[bucketKey] || 'Nothing is missing from this list.';
    }
    const which = notOk.map((source) => `${source.label.toLowerCase()} ${source.text}`).join(', ');
    return (
        `SoundCloud was only partly queried on this pass — ${which}. ` +
        'An empty list here means nobody looked, not that nothing is missing. Refresh to try again.'
    );
};

/** Which names the search actually went out for, and which it never reached. */
export const searchNamesLine = (view) => {
    if (!view || view.status !== 'ok') return '';
    const run = Array.isArray(view.search_queries_run) ? view.search_queries_run : [];
    const skipped = Array.isArray(view.search_queries_skipped) ? view.search_queries_skipped : [];
    if (run.length === 0 && skipped.length === 0) return '';
    const parts = [];
    if (run.length) parts.push(`searched for ${run.join(', ')}`);
    if (skipped.length) parts.push(`never searched for ${skipped.join(', ')} (budget)`);
    return parts.join(' · ');
};

/** The header chip when nobody has bound an account. Identification is by name alone. */
export const LINK_MISSING_CHIP = 'not linked — identified by name only';

export const LINK_MISSING_SENTENCE =
    'No SoundCloud account is bound to this artist, so every row here was found by name. ' +
    'Nothing can reach high confidence without the account, and their own uploads and ' +
    'reposts were not queried at all. Link the profile to close that gap.';

/** Why this track landed in this bucket, in the classifier's own words. */
export const creditLine = (track) => {
    const reason = track?.credit_parse?.reason;
    if (typeof reason === 'string' && reason.trim()) return reason.trim();
    return 'No reason was recorded for this row.';
};

/** "Their remix · medium confidence · pinned by you". Only ever from real fields. */
export const roleLine = (track) => {
    const parts = [];
    const role = ROLE_LABEL[track?.role];
    if (role) parts.push(role);
    const confidence = CONFIDENCE_LABEL[track?.confidence];
    if (confidence) parts.push(confidence);
    if (track?.identity_source === 'user_override') parts.push('pinned by you');
    return parts.join(' · ');
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

/** What "Download all missing" will and will not take. */
export const downloadAllNote = (count) =>
    `${count} track${count === 1 ? '' : 's'} the diff proved missing carry a role of "their ` +
    'track" or "their remix" at high or medium confidence. Only those are queued. Anything ' +
    'in a review bucket — remixed by others, featured, uncertain — and every excluded mix has ' +
    'to be downloaded row by row.';

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
