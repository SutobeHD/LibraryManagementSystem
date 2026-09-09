/**
 * discoveryCopy — the sentences the Discover tab and the background-sync line must say.
 *
 * Same split (and same reason) as `catalogueCopy.js`: this screen has three times
 * shipped a control that read as live while nothing behind it worked, so every line is
 * derived from a real payload field and tested on its own.
 *
 * Rules encoded here:
 *  1. An empty suggestion list may only read as "nothing to suggest" when BOTH sources
 *     actually answered. A source that failed, hit the call cap or was never queried
 *     gets said out loud instead.
 *  2. A count that the payload did not measure (`track_count: null`) is not printed.
 *  3. "You do not own this yet" is a claim: it needs `excluded_against` to be non-zero,
 *     otherwise the panel says the check could not run.
 *  4. A sync pass that did not happen is reported by its reason — never as a sync.
 *
 * Payload shapes: `app/artist_store/discovery.py::discover` and
 * `app/artist_store/sync.py::SyncRun.as_dict` / `idle_report`, both wrapped by
 * `app/main.py` (`/api/artists/discover`, `/api/artists/sync/status|run`).
 */

// Explicit extension: `discoveryCopy.test.js` runs under plain `node --test`, which has
// no Vite resolver to guess it.
import { relativeTime } from './catalogueCopy.js';

export const SOURCE_RELATED = 'related';
export const SOURCE_CO_OCCURRENCE = 'co_occurrence';

export const STATE_OK = 'ok';
export const STATE_FAILED = 'failed';
export const STATE_SKIPPED_BUDGET = 'skipped_budget';
export const STATE_NOT_QUERIED = 'not_queried';
export const STATE_NO_DATA = 'no_data';

/** `reason_stopped` values of a run that never walked an artist. */
export const STOP_DISABLED = 'disabled';
export const STOP_COMPLETED = 'completed';
export const STOP_CALL_BUDGET = 'call_budget_exhausted';
export const STOP_ARTIST_CAP = 'artist_cap_reached';
export const STOP_NO_REFRESHER = 'refresher_unsupported';
export const STOP_NOT_CONNECTED = 'not_connected';

const RELATED_REASONS = {
    not_signed_in: 'SoundCloud is not connected, so its related-artist list was never asked.',
    no_linked_accounts:
        'None of your favourites is linked to a SoundCloud profile yet, so there was no account ' +
        'to ask for related artists. Open an artist and use “Link SoundCloud profile”.',
    no_favourites: 'Favourite an artist first — discovery is seeded from your favourites.',
    auth_expired: 'The SoundCloud session expired part-way through, so the walk stopped early.',
    rate_limited: 'SoundCloud rate-limited the app part-way through, so the walk stopped early.',
    call_budget_spent: 'The per-run call cap was reached before every favourite was asked.',
    not_found: 'The accounts that were asked are gone (deleted, private or renamed).',
};

/**
 * What the related-artists hop actually did. `null` when it ran cleanly — the caller
 * then has nothing to explain away.
 */
export const relatedNote = (payload) => {
    const detail = payload?.sources_detail?.[SOURCE_RELATED] ?? {};
    const state = payload?.sources?.[SOURCE_RELATED] ?? STATE_NOT_QUERIED;
    if (state === STATE_OK) {
        const skipped = detail.skipped?.length || 0;
        if (skipped > 0) {
            // Never assume the cause. A 429 and an expired session also leave seeds
            // unasked, and naming the call cap for those was simply wrong.
            const why = RELATED_REASONS[detail.reason] || 'the walk stopped before the rest.';
            return `Asked ${detail.queried?.length || 0} of your linked favourites — ${why}`;
        }
        return null;
    }
    const reason = RELATED_REASONS[detail.reason] || '';
    if (state === STATE_SKIPPED_BUDGET) {
        return reason || 'The per-run call cap was reached before any favourite was asked.';
    }
    if (state === STATE_FAILED) {
        return (
            reason ||
            'SoundCloud’s related-artist list could not be read, so these suggestions come only ' +
                'from catalogues already cached here.'
        );
    }
    return (
        reason ||
        'SoundCloud’s related-artist list was not queried, so these suggestions come only from ' +
            'catalogues already cached here.'
    );
};

/** The zero-call tier. `no_data` means no catalogue is cached yet — not "nothing found". */
export const coOccurrenceNote = (payload) => {
    const state = payload?.sources?.[SOURCE_CO_OCCURRENCE] ?? STATE_NO_DATA;
    if (state === STATE_OK) return null;
    return (
        'No cached catalogue to read yet, so the offline source had nothing to work with — ' +
        'open a favourite artist once and it fills up.'
    );
};

/** True only when every source answered. The gate on saying "nothing to suggest". */
export const allSourcesAnswered = (payload) =>
    payload?.sources?.[SOURCE_RELATED] === STATE_OK &&
    payload?.sources?.[SOURCE_CO_OCCURRENCE] === STATE_OK;

/**
 * What to print when the list came back empty. Never "no suggestions" unless both
 * sources actually answered.
 */
export const emptyNote = (payload) => {
    if (!payload) return 'Nothing loaded yet.';
    if (allSourcesAnswered(payload)) {
        return 'Both sources answered and turned up nobody you do not already have.';
    }
    return (
        'No suggestions to show — and that is not the same as “nobody found”. ' +
        [relatedNote(payload), coOccurrenceNote(payload)].filter(Boolean).join(' ')
    );
};

/**
 * The "already yours" filter is a claim about the library. Says so when the store had
 * nothing to check against, instead of implying every row is new to you.
 */
export const exclusionNote = (payload) => {
    const against = payload?.excluded_against ?? {};
    const names = Number(against.local_names) || 0;
    const urns = Number(against.linked_accounts) || 0;
    if (names === 0 && urns === 0) {
        return 'Nothing was checked against your library yet, so an artist you already own can appear here.';
    }
    const excluded = Number(payload?.excluded) || 0;
    const checked = `Checked against ${names} name${names === 1 ? '' : 's'} you own`;
    const accounts = urns ? ` and ${urns} linked account${urns === 1 ? '' : 's'}` : '';
    return excluded
        ? `${checked}${accounts} · ${excluded} filtered out.`
        : `${checked}${accounts}.`;
};

/** `12 calls of 15` — the observable per-run cap. Empty when the payload carried none. */
export const callBudgetNote = (payload) => {
    const budget = payload?.call_budget;
    if (!budget || typeof budget.limit !== 'number') return '';
    const used = Number(payload?.calls_used);
    if (!Number.isFinite(used)) return '';
    return `${used} of ${budget.limit} SoundCloud calls used`;
};

/** "Suggested by A, B" — the favourites that pointed at this candidate. */
export const seedLine = (candidate) => {
    const seeds = candidate?.seeds ?? [];
    if (!seeds.length) return '';
    if (seeds.length === 1) return `Suggested by ${seeds[0]}`;
    if (seeds.length === 2) return `Suggested by ${seeds[0]} and ${seeds[1]}`;
    return `Suggested by ${seeds[0]}, ${seeds[1]} and ${seeds.length - 2} more`;
};

const NUMBER_FORMAT = new Intl.NumberFormat();

/**
 * The measured facts of one candidate, in order. A `null` count was never measured, so
 * it is dropped rather than rendered as 0.
 */
export const candidateFacts = (candidate) => {
    const facts = [];
    if (typeof candidate?.followers_count === 'number') {
        facts.push(`${NUMBER_FORMAT.format(candidate.followers_count)} followers`);
    }
    if (typeof candidate?.track_count === 'number') {
        facts.push(`${NUMBER_FORMAT.format(candidate.track_count)} tracks`);
    }
    if (candidate?.co_occurrence_tracks > 0) {
        const n = candidate.co_occurrence_tracks;
        facts.push(`${n} cached track${n === 1 ? '' : 's'} beside your favourites`);
    }
    return facts;
};

// --------------------------------------------------------------------- background sync

const PROBE_REASONS = {
    library_not_loaded: 'the library is still loading',
};

const PROBE_LABELS = {
    analyze_batch: 'an analysis run',
    artist_download: 'an artist download',
    artist_job: 'an artist job',
    duplicate_scan: 'a duplicate scan',
    local_import: 'a local import',
    phrase_batch: 'a phrase batch',
    sc_download: 'a SoundCloud download',
    usb_sync: 'a USB sync',
};

/** `"sc_download:downloading"` → `"a SoundCloud download is running"`. */
export const busyReasonSentence = (reason) => {
    const raw = String(reason || '').trim();
    if (!raw || raw === 'idle') return '';
    if (PROBE_REASONS[raw]) return PROBE_REASONS[raw];
    const label = PROBE_LABELS[raw.split(':')[0]];
    return label ? `${label} is running` : raw;
};

/**
 * The line under the favourites list: why a background pass would run right now, or
 * why it would not. Never claims a sync happened.
 */
export const idleSentence = (status) => {
    if (!status) return 'Checking what the app is busy with…';
    if (status.idle) return 'Idle — a background pass may run.';
    const reason = busyReasonSentence(status.reason);
    return reason ? `Waiting — ${reason}.` : 'Waiting — the app is busy.';
};

const STOP_SENTENCES = {
    [STOP_DISABLED]:
        'Background sync is switched off, so nothing was refreshed. Turn it on in Settings → Network, or use Sync now.',
    [STOP_CALL_BUDGET]: 'stopped at the per-run call cap — the rest go first next time',
    [STOP_ARTIST_CAP]: 'stopped at the per-run artist cap — the rest go first next time',
    [STOP_NOT_CONNECTED]: 'stopped because SoundCloud is not connected',
    [STOP_NO_REFRESHER]: 'could not start — the catalogue refresher refused the shared call budget',
};

/**
 * One sentence for a finished run, built only from what the record actually counted.
 * A refusal reports the refusal; it never reads as a completed sync.
 */
export const runSummary = (run) => {
    if (!run) return '';
    const stop = String(run.reason_stopped || '');
    if (stop === STOP_DISABLED) return STOP_SENTENCES[STOP_DISABLED];
    if (stop.startsWith('busy:')) {
        const reason = busyReasonSentence(stop.slice('busy:'.length));
        return reason
            ? `No pass ran — ${reason}.`
            : 'No pass ran — the app was busy when it was asked.';
    }
    if (stop === STOP_NO_REFRESHER) return `The pass ${STOP_SENTENCES[STOP_NO_REFRESHER]}.`;

    const synced = Number(run.artists_synced) || 0;
    const skipped = Number(run.artists_skipped) || 0;
    const calls = Number(run.calls_used) || 0;
    const parts = [`${synced} artist${synced === 1 ? '' : 's'} refreshed`];
    if (skipped) parts.push(`${skipped} left for next time`);
    parts.push(`${calls} of ${run.call_budget} calls used`);
    const tail = STOP_SENTENCES[stop];
    const errors = (run.errors ?? []).length;
    const failed = errors ? ` · ${errors} failed` : '';
    return `${parts.join(' · ')}${failed}${tail && stop !== STOP_COMPLETED ? ` · ${tail}` : ''}.`;
};

/** "Last checked 3 h ago" for one artist. Empty when it has never been synced. */
export const lastSyncedLabel = (isoOrNull) => {
    const ago = relativeTime(isoOrNull);
    return ago ? `checked ${ago}` : '';
};

/** What Auto / Review / Off actually do, now that the scheduler honours them. */
export const SYNC_MODE_HINTS = {
    auto: 'Auto — the idle background pass refreshes this artist’s catalogue. It never downloads.',
    review: 'Review — refreshed by the same idle pass; new tracks wait for you to pick them.',
    off: 'Off — the background pass skips this artist entirely.',
};
