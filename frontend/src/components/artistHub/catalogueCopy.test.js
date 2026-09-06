/**
 * node --test frontend/src/components/artistHub/catalogueCopy.test.js
 *
 * Pure copy + derivation builders — no DOM, no resolver needed (the imports carry
 * extensions). The load-bearing cases are the honesty ones: a typed backend state
 * must never derive buckets, a not-checked track must never count as missing, and a
 * run with failures must never read as a success.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import {
    callBudgetLine,
    downloadSummary,
    downloadTone,
    exclusionReason,
    fetchedLine,
    formatDate,
    formatDuration,
    progressLine,
    relativeTime,
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
    ...over,
});

const okView = (over = {}) => ({
    status: 'ok',
    collection_id: 'a_1',
    definitely_theirs: [track()],
    remixes_by_others: [],
    mixes_and_sets: [],
    in_library: [],
    fetched_at: new Date().toISOString(),
    from_cache: false,
    truncated: false,
    calls_used: 3,
    call_budget: 25,
    ...over,
});

test('splitCatalogue returns empty buckets for every typed non-ok state', () => {
    for (const status of ['not_linked', 'link_unresolved', 'not_connected', 'artist_gone']) {
        const split = splitCatalogue({ status, detail: 'x' });
        assert.equal(split.ok, false);
        assert.deepEqual(split.theirs, []);
        assert.deepEqual(split.missingTheirs, []);
        assert.deepEqual(split.queueable, []);
    }
    assert.equal(splitCatalogue(null).ok, false);
});

test('only an explicit in_library:false counts as missing', () => {
    const split = splitCatalogue(
        okView({
            definitely_theirs: [
                track({ sc_id: 'a', in_library: false }),
                track({ sc_id: 'b', in_library: true, auto_queue_allowed: false }),
                // never diffed (the excluded bucket's shape) — not a gap we measured
                track({ sc_id: 'c', in_library: null, auto_queue_allowed: false }),
            ],
        })
    );
    assert.deepEqual(
        split.missingTheirs.map((t) => t.sc_id),
        ['a']
    );
    assert.equal(split.ownedTheirs, 1);
});

test('queueable mirrors the server flag, not a rule we recompute', () => {
    const split = splitCatalogue(
        okView({
            definitely_theirs: [
                track({ sc_id: 'a', auto_queue_allowed: true }),
                track({ sc_id: 'b', auto_queue_allowed: false }),
            ],
        })
    );
    assert.deepEqual(
        split.queueable.map((t) => t.sc_id),
        ['a']
    );
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
