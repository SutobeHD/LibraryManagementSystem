import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
    camelotOf,
    dateAdded,
    formatOf,
    keySortValue,
    mytagList,
    sortTracks,
} from './trackSort.js';

const ids = (tracks) => tracks.map((t) => t.ID);

test('camelotOf reads Camelot and musical spellings', () => {
    assert.equal(camelotOf('8A'), '8A');
    assert.equal(camelotOf(' 12b '), '12B');
    assert.equal(camelotOf('Am'), '8A');
    assert.equal(camelotOf('F#m'), '11A');
    assert.equal(camelotOf('Bbm'), '3A');
    assert.equal(camelotOf('BBM'), '3A');
    assert.equal(camelotOf('Bb'), '6B');
    assert.equal(camelotOf('B'), '1B');
    assert.equal(camelotOf('E minor'), '9A');
    assert.equal(camelotOf('D major'), '10B');
    assert.equal(camelotOf('13A'), null);
    assert.equal(camelotOf('H'), null);
    assert.equal(camelotOf(''), null);
});

test('key order walks the wheel: 1A, 1B, 2A ... 12B', () => {
    const keys = ['12B', 'Am', '1B', '2A', 'C', '1A'];
    const sorted = [...keys].sort((a, b) => keySortValue(a) - keySortValue(b));
    assert.deepEqual(sorted, ['1A', '1B', '2A', 'Am', 'C', '12B']);
});

test('mytagList drops duplicates and blanks, keeps order', () => {
    assert.deepEqual(mytagList('Raw, Raw, Hypnotic, , BadFormat'), [
        'Raw',
        'Hypnotic',
        'BadFormat',
    ]);
    assert.deepEqual(mytagList(''), []);
    assert.deepEqual(mytagList(undefined), []);
});

test('formatOf takes the file extension of local paths only', () => {
    assert.equal(formatOf({ path: 'C:\\Music\\a b.aiff' }), 'AIFF');
    assert.equal(formatOf({ path: '/music/x.Flac' }), 'FLAC');
    assert.equal(formatOf({ path: 'soundcloud:tracks:1' }), null);
    assert.equal(formatOf({ path: 'C:/Music/.hidden' }), null);
    assert.equal(formatOf({}), null);
});

test('missing values sort last in both directions', () => {
    const tracks = [
        { ID: 'a', ReleaseYear: 0 },
        { ID: 'b', ReleaseYear: 2024 },
        { ID: 'c', ReleaseYear: 2019 },
        { ID: 'd' },
    ];
    assert.deepEqual(ids(sortTracks(tracks, { key: 'ReleaseYear', direction: 'asc' })), [
        'c',
        'b',
        'a',
        'd',
    ]);
    assert.deepEqual(ids(sortTracks(tracks, { key: 'ReleaseYear', direction: 'desc' })), [
        'b',
        'c',
        'a',
        'd',
    ]);
});

test('text sort ignores case and keeps spelling variants together', () => {
    const tracks = [
        { ID: 1, Genre: 'Trance' },
        { ID: 2, Genre: 'HARD TECHNO' },
        { ID: 3, Genre: '' },
        { ID: 4, Genre: 'hardgroove' },
        { ID: 5, Genre: 'Hard Techno' },
    ];
    assert.deepEqual(ids(sortTracks(tracks, { key: 'Genre', direction: 'asc' })), [2, 5, 4, 1, 3]);
});

test('Date Added sorts on StockDate, the field the library actually sends', () => {
    const tracks = [
        { ID: 1, StockDate: '2026-01-12' },
        { ID: 2, StockDate: '2025-11-12' },
        { ID: 3, StockDate: '' },
        { ID: 4, StockDate: 'None' },
        { ID: 5, StockDate: '2025-12-01' },
    ];
    assert.deepEqual(
        ids(sortTracks(tracks, { key: 'DateAdded', direction: 'desc' })),
        [1, 5, 2, 3, 4]
    );
});

test('dateAdded accepts only real dates', () => {
    assert.equal(dateAdded({ StockDate: '2026-01-12' }), '2026-01-12');
    assert.equal(dateAdded({ StockDate: '2026-01-12T10:00:00' }), '2026-01-12');
    assert.equal(dateAdded({ StockDate: 'None' }), null);
    assert.equal(dateAdded({ DateAdded: '2024-05-01' }), '2024-05-01');
    assert.equal(dateAdded({}), null);
});

test('key column sorts mixed notations on the Camelot wheel', () => {
    const tracks = [
        { ID: 1, Key: '9A' },
        { ID: 2, Key: 'Am' },
        { ID: 3, Key: '' },
        { ID: 4, Key: '8B' },
        { ID: 5, Key: '1A' },
    ];
    assert.deepEqual(ids(sortTracks(tracks, { key: 'Key', direction: 'asc' })), [5, 2, 4, 1, 3]);
});

test('colour and play count: 0 colour is missing, 0 plays is a value', () => {
    const tracks = [
        { ID: 1, ColorID: 0, PlayCount: 3 },
        { ID: 2, ColorID: '7', PlayCount: 0 },
        { ID: 3, ColorID: 1 },
    ];
    assert.deepEqual(ids(sortTracks(tracks, { key: 'Color', direction: 'asc' })), [3, 2, 1]);
    assert.deepEqual(ids(sortTracks(tracks, { key: 'PlayCount', direction: 'asc' })), [2, 1, 3]);
});

test('MyTag sorts on the deduplicated list; ties keep input order', () => {
    const tracks = [
        { ID: 1, MyTag: 'Raw, Raw' },
        { ID: 2, MyTag: 'Hypnotic' },
        { ID: 3, MyTag: 'Raw' },
    ];
    assert.deepEqual(ids(sortTracks(tracks, { key: 'MyTag', direction: 'asc' })), [2, 1, 3]);
});

test('no sort key returns the same array; unknown columns fall back to text', () => {
    const tracks = [
        { ID: 1, Foo: 'b' },
        { ID: 2, Foo: 'a' },
    ];
    assert.equal(sortTracks(tracks, { key: null }), tracks);
    assert.deepEqual(ids(sortTracks(tracks, { key: 'Foo', direction: 'asc' })), [2, 1]);
});
