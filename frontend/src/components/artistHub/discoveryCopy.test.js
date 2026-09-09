/**
 * node --test frontend/src/components/artistHub/discoveryCopy.test.js
 *
 * Pure copy builders — no DOM, no resolver needed (the imports carry extensions).
 * The load-bearing cases are the honesty ones: an empty list may only read as
 * "nobody found" when both sources answered, an unmeasured count is never printed,
 * "already yours" is never claimed without something to check against, and a sync
 * pass that did not run must never read as a sync that did.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import {
    STATE_FAILED,
    STATE_NOT_QUERIED,
    STATE_NO_DATA,
    STATE_OK,
    STATE_SKIPPED_BUDGET,
    allSourcesAnswered,
    busyReasonSentence,
    callBudgetNote,
    candidateFacts,
    coOccurrenceNote,
    emptyNote,
    exclusionNote,
    idleSentence,
    lastSyncedLabel,
    relatedNote,
    runSummary,
    seedLine,
} from './discoveryCopy.js';

const payload = (over = {}) => ({
    suggestions: [],
    sources: { related: STATE_OK, co_occurrence: STATE_OK },
    sources_detail: {
        related: { state: STATE_OK, reason: '', queried: ['Boys Noize'], skipped: [], failed: [] },
        co_occurrence: { state: STATE_OK, scanned: ['Boys Noize'], no_cache: [] },
    },
    calls_used: 2,
    call_budget: { limit: 15, used: 2, remaining: 13 },
    excluded: 3,
    excluded_against: { local_names: 120, linked_accounts: 4 },
    ...over,
});

// --------------------------------------------------------------------- source states

test('a clean related hop has nothing to explain away', () => {
    assert.equal(relatedNote(payload()), null);
    assert.equal(coOccurrenceNote(payload()), null);
    assert.equal(allSourcesAnswered(payload()), true);
});

test('a not-queried related source is never silence', () => {
    const note = relatedNote(
        payload({
            sources: { related: STATE_NOT_QUERIED, co_occurrence: STATE_OK },
            sources_detail: {
                related: { state: STATE_NOT_QUERIED, reason: 'not_signed_in' },
                co_occurrence: { state: STATE_OK },
            },
        })
    );
    assert.match(note, /not connected/i);
});

test('a failed related source says it could not look, not that it found nothing', () => {
    const note = relatedNote(
        payload({
            sources: { related: STATE_FAILED, co_occurrence: STATE_OK },
            sources_detail: {
                related: { state: STATE_FAILED, reason: 'rate_limited' },
                co_occurrence: { state: STATE_OK },
            },
        })
    );
    assert.match(note, /rate-limited/i);
});

test('an ok hop that ran out of budget still admits the skipped seeds', () => {
    const note = relatedNote(
        payload({
            sources_detail: {
                related: {
                    state: STATE_OK,
                    queried: ['A'],
                    skipped: ['B', 'C'],
                    failed: [],
                    reason: 'rate_limited',
                },
                co_occurrence: { state: STATE_OK },
            },
        })
    );
    // The cause comes from the payload. Hardcoding the call cap here mislabelled a
    // 429 and an expired session as "the cap was reached".
    assert.match(note, /rate-limited/i);
    assert.doesNotMatch(note, /call cap/i);
});

test('an unasked seed with no stated reason never invents the call cap', () => {
    const note = relatedNote(
        payload({
            sources_detail: {
                related: {
                    state: STATE_OK,
                    queried: ['A'],
                    skipped: ['B'],
                    failed: [],
                    reason: '',
                },
                co_occurrence: { state: STATE_OK },
            },
        })
    );
    assert.match(note, /stopped before the rest/i);
    assert.doesNotMatch(note, /call cap/i);
});

test('skipped_budget reports the cap', () => {
    const note = relatedNote(
        payload({
            sources: { related: STATE_SKIPPED_BUDGET, co_occurrence: STATE_OK },
            sources_detail: {
                related: { state: STATE_SKIPPED_BUDGET, reason: 'call_budget_spent', skipped: [] },
                co_occurrence: { state: STATE_OK },
            },
        })
    );
    assert.match(note, /call cap/i);
});

// ------------------------------------------------------------------------ empty list

test('an empty list only reads as "nobody found" when both sources answered', () => {
    assert.match(emptyNote(payload()), /turned up nobody/i);
});

test('an empty list with an unqueried source says so instead', () => {
    const note = emptyNote(
        payload({
            sources: { related: STATE_NOT_QUERIED, co_occurrence: STATE_NO_DATA },
            sources_detail: {
                related: { state: STATE_NOT_QUERIED, reason: 'no_linked_accounts' },
                co_occurrence: { state: STATE_NO_DATA },
            },
        })
    );
    assert.match(note, /not the same as/i);
    assert.match(note, /linked to a SoundCloud profile/i);
    assert.doesNotMatch(note, /turned up nobody/i);
});

// ----------------------------------------------------------------------- the filter

test('"already yours" is not claimed when nothing was checked against', () => {
    const note = exclusionNote(
        payload({ excluded_against: { local_names: 0, linked_accounts: 0 } })
    );
    assert.match(note, /Nothing was checked against your library/i);
});

test('a real exclusion check reports what it checked', () => {
    const note = exclusionNote(payload());
    assert.match(note, /120 names/);
    assert.match(note, /4 linked accounts/);
    assert.match(note, /3 filtered out/);
});

test('the call cap is printed from the payload, never invented', () => {
    assert.equal(callBudgetNote(payload()), '2 of 15 SoundCloud calls used');
    assert.equal(callBudgetNote({}), '');
});

// ------------------------------------------------------------------------ candidates

test('an unmeasured count is dropped, not rendered as zero', () => {
    const facts = candidateFacts({
        followers_count: null,
        track_count: null,
        co_occurrence_tracks: 0,
    });
    assert.deepEqual(facts, []);
});

test('measured counts are printed', () => {
    const facts = candidateFacts({
        followers_count: 1234,
        track_count: 12,
        co_occurrence_tracks: 3,
    });
    assert.equal(facts.length, 3);
    assert.match(facts[0], /followers/);
    assert.match(facts[2], /3 cached tracks/);
});

test('the seed line names who pointed at the candidate', () => {
    assert.equal(seedLine({ seeds: [] }), '');
    assert.equal(seedLine({ seeds: ['A'] }), 'Suggested by A');
    assert.equal(seedLine({ seeds: ['A', 'B'] }), 'Suggested by A and B');
    assert.equal(seedLine({ seeds: ['A', 'B', 'C', 'D'] }), 'Suggested by A, B and 2 more');
});

// --------------------------------------------------------------------- sync sentences

test('a busy probe reason becomes a sentence a user can act on', () => {
    assert.equal(busyReasonSentence('sc_download:downloading'), 'a SoundCloud download is running');
    assert.equal(busyReasonSentence('library_not_loaded'), 'the library is still loading');
    assert.equal(busyReasonSentence('idle'), '');
    assert.equal(busyReasonSentence('something_new:1'), 'something_new:1');
});

test('the idle line explains the wait instead of shrugging', () => {
    assert.match(idleSentence({ idle: true, reason: 'idle' }), /Idle/);
    assert.match(
        idleSentence({ idle: false, reason: 'sc_download:downloading' }),
        /Waiting — a SoundCloud download is running\./
    );
});

test('a refused pass never reads as a sync', () => {
    const summary = runSummary({
        artists_synced: 0,
        artists_skipped: 0,
        calls_used: 0,
        call_budget: 60,
        reason_stopped: 'busy:phrase_batch:running',
        errors: [],
    });
    assert.match(summary, /No pass ran/);
    assert.doesNotMatch(summary, /refreshed/);
});

test('a disabled pass says where to switch it on', () => {
    assert.match(
        runSummary({ reason_stopped: 'disabled', artists_synced: 0, call_budget: 60 }),
        /switched off/i
    );
});

test('a completed pass reports only what it counted', () => {
    const summary = runSummary({
        artists_synced: 4,
        artists_skipped: 2,
        calls_used: 17,
        call_budget: 60,
        reason_stopped: 'completed',
        errors: [{ collection_id: 'c1' }],
    });
    assert.match(summary, /4 artists refreshed/);
    assert.match(summary, /2 left for next time/);
    assert.match(summary, /17 of 60 calls used/);
    assert.match(summary, /1 failed/);
});

test('a capped pass says which cap stopped it', () => {
    const summary = runSummary({
        artists_synced: 20,
        artists_skipped: 5,
        calls_used: 60,
        call_budget: 60,
        reason_stopped: 'call_budget_exhausted',
        errors: [],
    });
    assert.match(summary, /per-run call cap/);
});

test('an artist that was never synced gets no invented timestamp', () => {
    assert.equal(lastSyncedLabel(null), '');
    assert.equal(lastSyncedLabel(''), '');
    assert.match(lastSyncedLabel(new Date().toISOString()), /checked/);
});
