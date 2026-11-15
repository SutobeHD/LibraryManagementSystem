/**
 * node --test frontend/src/components/artistHub/catalogueCopy.test.js
 *
 * Pure copy + derivation builders — no DOM, no resolver needed (the imports carry
 * extensions). The load-bearing cases are the honesty ones: a typed backend state
 * must never derive buckets, a not-checked track must never count as missing, a
 * bucket whose sources were not queried must never read as "nothing missing", and a
 * run with failures must never read as a success.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import {
    LINK_MISSING_CHIP,
    allSourcesOk,
    bucketEmptyNote,
    callBudgetLine,
    creditLine,
    downloadAllNote,
    downloadSummary,
    downloadTone,
    exclusionReason,
    fetchedLine,
    formatDate,
    formatDuration,
    progressLine,
    relativeTime,
    roleLine,
    searchNamesLine,
    sourceStates,
    sourceStatusLine,
    splitCatalogue,
    stateSentence,
    truncationNote,
} from './catalogueCopy.js';

const track = (over = {}) => ({
    sc_id: 'soundcloud:tracks:1',
    title: 'Rocket Boy',
    duration_ms: 278000,
    in_library: false,
    auto_queue_allowed: true,
    role: 'primary',
    confidence: 'high',
    identity_source: 'classifier',
    credit_parse: { reason: 'Uploaded by the linked account' },
    ...over,
});

const ALL_OK = { uploads: 'ok', search: 'ok', reposts: 'ok' };

const okView = (over = {}) => ({
    status: 'ok',
    collection_id: 'a_1',
    their_tracks: [track()],
    their_remixes: [],
    remixed_by_others: [],
    featured: [],
    uncertain: [],
    mixes_and_sets: [],
    in_library: [],
    link_missing: false,
    sources: { ...ALL_OK },
    search_queries_run: ['Boys Noize'],
    search_queries_skipped: [],
    fetched_at: new Date().toISOString(),
    from_cache: false,
    truncated: false,
    calls_used: 3,
    call_budget: 25,
    ...over,
});

test('splitCatalogue returns empty buckets for every typed non-ok state', () => {
    for (const status of ['not_linked', 'not_connected', 'artist_gone']) {
        const split = splitCatalogue({ status, detail: 'x' });
        assert.equal(split.ok, false);
        assert.deepEqual(split.rows.their_tracks, []);
        assert.deepEqual(split.missing.their_tracks, []);
        assert.deepEqual(split.queueable, []);
        assert.equal(split.total, 0);
    }
    assert.equal(splitCatalogue(null).ok, false);
});

test('only an explicit in_library:false counts as missing', () => {
    const split = splitCatalogue(
        okView({
            their_tracks: [
                track({ sc_id: 'a', in_library: false }),
                track({ sc_id: 'b', in_library: true, auto_queue_allowed: false }),
                // never diffed (the excluded bucket's shape) — not a gap we measured
                track({ sc_id: 'c', in_library: null, auto_queue_allowed: false }),
            ],
        })
    );
    assert.deepEqual(
        split.missing.their_tracks.map((t) => t.sc_id),
        ['a']
    );
    assert.equal(split.counts.their_tracks, 3);
    assert.equal(split.missingCounts.their_tracks, 1);
});

test('queueable mirrors the server flag across every bucket, not a rule we recompute', () => {
    const split = splitCatalogue(
        okView({
            their_tracks: [track({ sc_id: 'a', auto_queue_allowed: true })],
            their_remixes: [
                track({ sc_id: 'b', role: 'remixer', auto_queue_allowed: true }),
                track({ sc_id: 'c', role: 'remixer', auto_queue_allowed: false }),
            ],
            uncertain: [track({ sc_id: 'd', role: 'uncertain', auto_queue_allowed: false })],
        })
    );
    assert.deepEqual(
        split.queueable.map((t) => t.sc_id),
        ['a', 'b']
    );
    assert.equal(split.total, 4);
});

test('splitCatalogue carries the link-missing flag through instead of guessing', () => {
    assert.equal(splitCatalogue(okView()).linkMissing, false);
    assert.equal(splitCatalogue(okView({ link_missing: true })).linkMissing, true);
    assert.equal(splitCatalogue({ status: 'not_connected' }).linkMissing, null);
});

test('stateSentence prefers the backend detail and always says something', () => {
    assert.equal(stateSentence({ status: 'not_linked', detail: 'Link one.' }), 'Link one.');
    assert.match(stateSentence({ status: 'not_connected' }), /SoundCloud is not connected/);
    assert.match(stateSentence({ status: 'something_new' }), /unavailable/);
});

test('fetchedLine distinguishes a cache hit from a live fetch, and never guesses', () => {
    assert.equal(fetchedLine({ status: 'not_linked' }), '');
    assert.match(fetchedLine(okView({ from_cache: true })), /cache · fetched just now/);
    assert.match(fetchedLine(okView()), /^Fetched from SoundCloud just now/);
    assert.equal(fetchedLine(okView({ fetched_at: '' })), 'Fetched from SoundCloud.');
});

test('truncationNote fires only when the backend said the fetch was cut short', () => {
    assert.equal(truncationNote(okView()), '');
    assert.match(truncationNote(okView({ truncated: true })), /not proof that you own it/);
});

test('callBudgetLine drops rather than invent a budget', () => {
    assert.equal(callBudgetLine(okView()), '3 of 25 SoundCloud calls used');
    assert.equal(callBudgetLine(okView({ call_budget: 0 })), '');
    assert.equal(callBudgetLine({ status: 'not_linked' }), '');
});

// ─── per-source honesty ───────────────────────────────────────────────────────

test('sourceStatusLine names all three sources and their real status', () => {
    assert.equal(sourceStatusLine(okView()), 'Uploads ✓ · Search ✓ · Reposts ✓');
    assert.equal(
        sourceStatusLine(okView({ sources: { ...ALL_OK, reposts: 'skipped_budget' } })),
        'Uploads ✓ · Search ✓ · Reposts not queried (budget)'
    );
    assert.equal(sourceStatusLine({ status: 'not_connected' }), '');
});

test('an unlinked artist says WHY uploads and reposts did not run', () => {
    const states = sourceStates(
        okView({
            link_missing: true,
            sources: { uploads: 'not_queried', search: 'ok', reposts: 'not_queried' },
        })
    );
    const byKey = Object.fromEntries(states.map((s) => [s.key, s]));
    assert.match(byKey.uploads.short, /no linked account/);
    assert.match(byKey.reposts.text, /no SoundCloud account is linked/);
    assert.equal(byKey.search.ok, true);
});

test('a missing source status defaults to not_queried, never to ok', () => {
    const states = sourceStates(okView({ sources: {} }));
    assert.deepEqual(
        states.map((s) => s.status),
        ['not_queried', 'not_queried', 'not_queried']
    );
    assert.equal(allSourcesOk(okView({ sources: {} })), false);
    assert.equal(allSourcesOk(okView()), true);
    assert.equal(allSourcesOk({ status: 'not_connected' }), false);
});

test('an empty bucket may only claim "nothing missing" when every source ran', () => {
    assert.match(bucketEmptyNote(okView(), 'their_tracks'), /Nothing from this artist/);
    assert.match(bucketEmptyNote(okView(), 'their_remixes'), /own remixes is missing/);

    const partial = bucketEmptyNote(
        okView({ sources: { ...ALL_OK, reposts: 'skipped_budget' } }),
        'their_remixes'
    );
    assert.match(partial, /only partly queried/);
    assert.match(partial, /reposts not queried \(the per-run call budget ran out\)/);
    assert.match(partial, /nobody looked/);
    assert.doesNotMatch(partial, /Nothing/);

    const failed = bucketEmptyNote(
        okView({ sources: { ...ALL_OK, search: 'failed' } }),
        'featured'
    );
    assert.match(failed, /search could not be reached/);

    assert.match(bucketEmptyNote(null, 'their_tracks'), /No catalogue has been read/);
});

test('searchNamesLine reports which spellings were searched and which never were', () => {
    assert.equal(searchNamesLine(okView()), 'searched for Boys Noize');
    assert.match(
        searchNamesLine(
            okView({ search_queries_run: ['Boys Noize'], search_queries_skipped: ['BNR'] })
        ),
        /never searched for BNR \(budget\)/
    );
    assert.equal(searchNamesLine(okView({ search_queries_run: [] })), '');
    assert.equal(searchNamesLine({ status: 'not_connected' }), '');
});

// ─── per-row explanation ──────────────────────────────────────────────────────

test('roleLine and creditLine say why a row is where it is, or admit they cannot', () => {
    assert.equal(roleLine(track()), 'Their track · high confidence');
    assert.equal(
        roleLine(track({ role: 'remixer', confidence: 'medium' })),
        'Their remix · medium confidence'
    );
    assert.match(roleLine(track({ identity_source: 'user_override' })), /pinned by you$/);
    assert.equal(roleLine({}), '');
    assert.equal(creditLine(track()), 'Uploaded by the linked account');
    assert.match(creditLine({}), /No reason was recorded/);
});

test('the link-missing chip is one short phrase, not a paragraph', () => {
    assert.equal(LINK_MISSING_CHIP, 'not linked — identified by name only');
});

test('downloadAllNote says what the button will NOT take', () => {
    const note = downloadAllNote(3);
    assert.match(note, /^3 tracks/);
    assert.match(note, /their remix/);
    assert.match(note, /remixed by others, featured, uncertain/);
    assert.match(downloadAllNote(1), /^1 track /);
});

test('downloadSummary reports what landed, never a blanket success', () => {
    assert.equal(
        downloadSummary({ total: 5, succeeded: 3, skipped: 1, failed: 1 }),
        '3 downloaded · 1 skipped · 1 failed of 5 queued'
    );
    assert.equal(downloadSummary({ total: 2, succeeded: 2 }), '2 downloaded of 2 queued');
    assert.equal(
        downloadSummary({ total: 4, succeeded: 1, status: 'cancelled' }),
        '1 downloaded of 4 queued, run cancelled'
    );
    assert.equal(downloadSummary(null), '');
});

test('downloadTone refuses to call a partial or empty run a success', () => {
    assert.equal(downloadTone({ total: 2, succeeded: 2, status: 'done' }), 'success');
    assert.equal(downloadTone({ total: 2, succeeded: 1, failed: 1 }), 'error');
    assert.equal(downloadTone({ total: 2, succeeded: 1, skipped: 1 }), 'neutral');
    assert.equal(downloadTone({ total: 2, succeeded: 0, skipped: 2 }), 'neutral');
    assert.equal(downloadTone({ status: 'error' }), 'error');
});

test('progressLine names the track being fetched', () => {
    assert.equal(
        progressLine({ total: 12, done: 3, current_track: { title: 'Cerebral' } }),
        'Track 4 of 12 — Cerebral'
    );
    assert.equal(progressLine({ total: 2, done: 2 }), 'Track 2 of 2');
    assert.equal(progressLine(null), '');
});

test('formatDuration and formatDate stay empty instead of printing junk', () => {
    assert.equal(formatDuration(278000), '4:38');
    assert.equal(formatDuration(0), '');
    assert.equal(formatDuration('nope'), '');
    assert.equal(formatDate(''), '');
    assert.equal(formatDate('not-a-date'), '');
});

test('relativeTime buckets and passes an unparseable stamp through untouched', () => {
    assert.equal(relativeTime(null), null);
    assert.equal(relativeTime(new Date().toISOString()), 'just now');
    assert.equal(relativeTime(new Date(Date.now() - 5 * 60_000).toISOString()), '5 min ago');
    assert.equal(relativeTime(new Date(Date.now() - 3 * 3_600_000).toISOString()), '3 h ago');
    assert.equal(relativeTime('whenever'), 'whenever');
});

test('exclusionReason explains every backend reason and falls back safely', () => {
    assert.match(exclusionReason({ excluded_reason: 'long_form' }), /15 minutes/);
    assert.match(exclusionReason({ excluded_reason: 'keyword' }), /dj set/);
    assert.match(exclusionReason({ excluded_reason: 'unavailable' }), /preview only/);
    assert.match(exclusionReason({ excluded_reason: 'brand_new' }), /mix\/set rule/);
});
