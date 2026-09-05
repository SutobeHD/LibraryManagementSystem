/**
 * node --test frontend/src/components/artistHub/mergeCopy.test.js
 *
 * Pure copy builders — no DOM, no resolver needed (the imports carry extensions).
 * The load-bearing case is the last one: no byte figure ⇒ the sentence says
 * tracks, never an invented size.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import {
    applySummary,
    compoundWarning,
    confirmMessage,
    databaseEffect,
    dryRunLine,
    filesEffect,
    formatBytes,
    mergeEffects,
    revertSummary,
    usbEffect,
} from './mergeCopy.js';

const preview = (over = {}) => ({
    canonical: 'Boys Noize',
    tracks_to_rewrite: 162,
    tracks_already_canonical: 250,
    counts_exact: true,
    files_to_retag: 162,
    files_missing: 0,
    files_measured: true,
    orphans_after: 3,
    compound_artist_tracks: 0,
    compound_artist_names: [],
    usb: {
        canonical_folder: 'Contents/Boys Noize',
        folders_to_merge: [{ folder: 'Contents/boys noize' }, { folder: 'Contents/BOYS NOIZE' }],
        tracks_relocated: 162,
        tracks_already_in_place: 250,
        bytes_local_source: 2_900_000_000,
        files_unmeasured: 0,
        case_only_renames: 0,
    },
    ...over,
});

test('formatBytes returns null instead of a fake zero', () => {
    assert.equal(formatBytes(0), null);
    assert.equal(formatBytes(null), null);
    assert.equal(formatBytes('nope'), null);
    assert.equal(formatBytes(1024), '1.0 KB');
    assert.equal(formatBytes(2_900_000_000), '2.7 GB');
});

test('dry-run line names the rewrite count', () => {
    assert.match(dryRunLine(preview()), /^162 tracks will be rewritten in Rekordbox$/);
});

test('database effect flags an inexact count instead of hiding it', () => {
    assert.match(databaseEffect(preview()), /162 tracks are rewritten in Rekordbox/);
    assert.match(databaseEffect(preview({ counts_exact: false })), /Upper bound/);
});

test('files effect says what it cannot count', () => {
    assert.match(filesEffect(preview()), /162 audio files are re-tagged/);
    assert.match(filesEffect(preview({ files_missing: 4 })), /4 tracks have no readable file/);
    assert.match(filesEffect(preview({ files_measured: false })), /could not be counted/);
});

test('usb effect quotes the measured size and says "moved, not re-copied"', () => {
    const text = usbEffect(preview());
    assert.match(text, /2 folders merge into Contents\/Boys Noize/);
    assert.match(text, /about 2\.7 GB/);
    assert.match(text, /not re-copied/);
});

test('usb effect falls back to tracks when the preview reports no bytes', () => {
    const text = usbEffect(
        preview({
            usb: { ...preview().usb, bytes_local_source: 0, files_unmeasured: 162 },
        })
    );
    assert.match(text, /162 tracks \(size not measured\)/);
    assert.ok(!/GB|MB|KB/.test(text), 'must not invent a size');
});

test('usb effect handles a merge with nothing to move', () => {
    const text = usbEffect(preview({ usb: { ...preview().usb, folders_to_merge: [] } }));
    assert.match(text, /No folder on the USB stick changes/);
});

test('all three effects are always present', () => {
    assert.deepEqual(
        mergeEffects(preview()).map((e) => e.id),
        ['db', 'files', 'usb']
    );
});

test('compound credits are surfaced, and absent when there are none', () => {
    assert.equal(compoundWarning(preview()), null);
    const text = compoundWarning(
        preview({ compound_artist_tracks: 7, compound_artist_names: ['boys noize, Objekt'] })
    );
    assert.match(text, /7 tracks credit more than this artist/);
    assert.match(text, /flattens that credit/);
});

test('confirm message states the three effects, the orphan warning and the journal', () => {
    const text = confirmMessage(preview(), { deleteOrphans: true });
    assert.match(text, /rewritten in Rekordbox/);
    assert.match(text, /re-tagged on disk/);
    assert.match(text, /folders merge into/);
    assert.match(text, /Contents\/boys noize, Contents\/BOYS NOIZE → Contents\/Boys Noize/);
    assert.match(text, /3 empty artist entries are deleted/);
    assert.match(text, /Remixer, Original-Artist, Composer and Lyricist/);
    assert.match(text, /journalled/);
    assert.ok(!/empty artist entries are deleted/.test(confirmMessage(preview())));
});

test('summaries report skips, aborts and incomplete reverts', () => {
    const applied = applySummary({
        tracks_rewritten: 162,
        write_tags: true,
        files_retagged: 160,
        files_skipped: [{ reason: 'tag_write_failed' }],
        orphans_deleted: [],
        aborted: true,
    });
    assert.match(applied, /162 tracks rewritten/);
    assert.match(applied, /1 skipped/);
    assert.match(applied, /run aborted early/);

    const reverted = revertSummary({
        tracks_restored: 100,
        tracks_failed: 2,
        artists_restored: 0,
        artists_failed: 0,
        files_restored: 0,
        complete: false,
    });
    assert.match(reverted, /100 tracks restored/);
    assert.match(reverted, /2 failed/);
    assert.match(reverted, /revert is incomplete/);
});
