// node:test — `node --test frontend/src/components/downloads/recognitionCopy.test.js`
// Artist hub T-31 / plan row T43: recognition lines never claim a known artist, a
// correction or a suggestion the task payload lacks.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
    correctionLine,
    creditChips,
    formatNames,
    recognitionHeadline,
    suggestionState,
} from './recognitionCopy.js';

const BOYS = {
    name: 'Boys Noize',
    role: 'remixer',
    known: true,
    collection_id: 'a_1',
    canonical: 'Boys Noize',
    stored: true,
    favourite: true,
    library_tracks: 8,
};
const CHARLI = { name: 'Charli XCX', role: 'remixed_by_other', known: false };

const LABEL_UPLOAD = {
    raw_artist: 'Boysnoize Records',
    raw_title: 'Boys Noize - Starter',
    artist: 'Boys Noize',
    title: 'Starter',
    changed: true,
    corrections: ['known_artist_prefix'],
    suggestion: null,
    credits: [{ ...BOYS, role: 'primary' }],
};

const UNKNOWN_PREFIX = {
    raw_artist: 'Some Label',
    raw_title: 'New Act - Song',
    artist: 'Some Label',
    title: 'New Act - Song',
    changed: false,
    corrections: [],
    suggestion: { artist: 'New Act', title: 'Song', reason: 'unknown_artist_prefix' },
    credits: [{ name: 'New Act', role: 'primary', known: false }],
};

test('chips say favourite / known / new exactly as the credit does', () => {
    const chips = creditChips({ credits: [BOYS, CHARLI] });

    assert.deepEqual(
        chips.map((c) => [c.label, c.tone]),
        [
            ['Boys Noize · Remix', 'favourite'],
            ['Charli XCX · Original', 'new'],
        ]
    );
    assert.equal(chips[0].title, 'Favorit · 8 Tracks in deiner Library');
    assert.equal(chips[1].title, 'Neu — noch nicht in deiner Library.');
});

test('a known artist with no library tracks is stored, not "0 Tracks"', () => {
    const [chip] = creditChips({
        credits: [{ ...BOYS, favourite: false, library_tracks: 0 }],
    });

    assert.equal(chip.tone, 'known');
    assert.equal(chip.title, 'Im Artist-Hub gespeichert');
});

test('the headline follows the chips', () => {
    assert.equal(recognitionHeadline({ credits: [BOYS] }), 'Artist erkannt');
    assert.equal(recognitionHeadline({ credits: [BOYS, CHARLI] }), 'Teilweise erkannt');
    assert.equal(recognitionHeadline({ credits: [CHARLI] }), 'Neuer Artist');
    assert.equal(recognitionHeadline({ credits: [] }), null);
    assert.equal(recognitionHeadline(undefined), null);
});

test('a correction line appears only when the file got other names', () => {
    const line = correctionLine(LABEL_UPLOAD);

    assert.equal(line.before, 'Boysnoize Records – Boys Noize - Starter');
    assert.equal(line.after, 'Boys Noize – Starter');
    assert.equal(line.reasons.length, 1);
    assert.equal(correctionLine(UNKNOWN_PREFIX), null);
    assert.equal(correctionLine(null), null);
});

test('a suggestion waits for the import, then opens, then reads as applied', () => {
    assert.equal(suggestionState(UNKNOWN_PREFIX, null).state, 'waiting');

    const open = suggestionState(UNKNOWN_PREFIX, '555');
    assert.equal(open.state, 'open');
    assert.equal(open.names, 'New Act – Song');
    assert.deepEqual(open.undo, { artist: 'Some Label', title: 'New Act - Song' });

    const applied = suggestionState(
        { ...UNKNOWN_PREFIX, applied: { artist: 'New Act', title: 'Song' } },
        '555'
    );
    assert.equal(applied.state, 'applied');

    const undone = suggestionState(
        { ...UNKNOWN_PREFIX, applied: { artist: 'Some Label', title: 'New Act - Song' } },
        '555'
    );
    assert.equal(undone.state, 'open');
});

test('no suggestion, no suggestion line', () => {
    assert.equal(suggestionState(LABEL_UPLOAD, '555'), null);
    assert.equal(suggestionState({ suggestion: { artist: 'X' } }, '555'), null);
    assert.equal(suggestionState(undefined, '555'), null);
});

test('names are joined with an en dash and survive a missing half', () => {
    assert.equal(formatNames('A', 'B'), 'A – B');
    assert.equal(formatNames('', 'B'), 'B');
    assert.equal(formatNames('A', null), 'A');
});
