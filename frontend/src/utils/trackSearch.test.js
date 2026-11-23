import { test } from 'node:test';
import assert from 'node:assert/strict';

import { compileToken, filterTracks, tokenizeQuery } from './trackSearch.js';

const LIB = [
    {
        ID: 1,
        Title: 'Night Drive',
        Artist: 'Kölsch',
        Genre: 'Deep House',
        Label: 'Kompakt',
        BPM: 122,
        Rating: 5,
        Key: 'Am',
        ReleaseYear: 2019,
    },
    {
        ID: 2,
        Title: 'Re:Mix',
        Artist: 'Daft',
        Genre: 'House',
        Label: 'Roulé',
        BPM: 140.4,
        Rating: 4,
        Key: '11A',
        ReleaseYear: 2024,
    },
    {
        ID: 3,
        Title: 'Acid Rain',
        Artist: 'Unknown',
        Genre: 'Techno',
        Label: '',
        BPM: 145,
        Rating: 2,
        Key: '1A',
        ReleaseYear: 0,
    },
    {
        ID: 4,
        Title: 'Raw Cut',
        Artist: 'X',
        Genre: 'Deep Techno',
        BPM: 0,
        Rating: 0,
        Key: '',
        ReleaseYear: 2010,
    },
];

// Fresh array per query: the haystack cache is keyed by list identity.
const ids = (q) => filterTracks([...LIB], q).map((t) => t.ID);

test('tokenizer keeps double-quoted values with spaces together', () => {
    assert.deepEqual(tokenizeQuery('genre:"Deep House" acid'), [
        { field: 'genre', value: 'deep house', quoted: true },
        { field: null, value: 'acid', quoted: false },
    ]);
    assert.deepEqual(tokenizeQuery('"night drive"'), [
        { field: null, value: 'night drive', quoted: true },
    ]);
    assert.deepEqual(tokenizeQuery('label:"komp'), [
        { field: 'label', value: 'komp', quoted: true },
    ]);
    assert.deepEqual(tokenizeQuery('"a:b"'), [{ field: null, value: 'a:b', quoted: true }]);
    assert.deepEqual(tokenizeQuery('   '), []);
});

test('quoted values filter text fields and free text', () => {
    assert.deepEqual(ids('genre:"deep house"'), [1]);
    assert.deepEqual(ids('genre:deep'), [1, 4]);
    assert.deepEqual(ids('"night drive"'), [1]);
    assert.deepEqual(ids('night drive'), [1]);
    assert.deepEqual(ids('"drive night"'), []);
});

test('rating supports >=, <=, >, <, = and a bare number', () => {
    assert.deepEqual(ids('rating:>=4'), [1, 2]);
    assert.deepEqual(ids('rating:>4'), [1]);
    assert.deepEqual(ids('rating:<3'), [3, 4]);
    assert.deepEqual(ids('rating:<=2'), [3, 4]);
    assert.deepEqual(ids('rating:=4'), [2]);
    assert.deepEqual(ids('rating:5'), [1]);
    assert.deepEqual(ids('rating:0'), [4]);
});

test('bpm keeps ranges and exact rounding, adds operators, skips unanalysed tracks', () => {
    assert.deepEqual(ids('bpm:138-142'), [2]);
    assert.deepEqual(ids('bpm:142-138'), [2]);
    assert.deepEqual(ids('bpm:>140'), [2, 3]);
    assert.deepEqual(ids('bpm:>=145'), [3]);
    assert.deepEqual(ids('bpm:<130'), [1]);
    assert.deepEqual(ids('bpm:140'), [2]);
    assert.deepEqual(ids('bpm:121.6-122.4'), [1]);
});

test('year compares numbers; unknown year never matches', () => {
    assert.deepEqual(ids('year:2024'), [2]);
    assert.deepEqual(ids('year:>=2019'), [1, 2]);
    assert.deepEqual(ids('year:<2015'), [4]);
});

test('key matches the Camelot slot in either notation', () => {
    assert.deepEqual(ids('key:8A'), [1]);
    assert.deepEqual(ids('key:am'), [1]);
    assert.deepEqual(ids('key:1A'), [3]);
    assert.deepEqual(ids('key:11'), [2]);
});

test('field and free-text tokens combine with AND', () => {
    assert.deepEqual(ids('genre:techno bpm:>140'), [3]);
    assert.deepEqual(ids('rating:>=4 genre:"deep house"'), [1]);
    assert.deepEqual(ids('artist:daft'), [2]);
    assert.deepEqual(ids('title:"acid rain"'), [3]);
});

test('unknown fields and malformed numbers are free text as typed', () => {
    assert.deepEqual(ids('mood:techno'), []);
    assert.deepEqual(ids('re:mix'), [2]);
    assert.deepEqual(ids('rating:high'), []);
    assert.deepEqual(ids('bpm:fast'), []);
    assert.equal(typeof compileToken({ field: 'rating', value: 'abc' }), 'function');
});

const EXTRA = [
    { ID: 'blue', Title: 'Blue (12" Mix)', Artist: 'Lane', Key: 'A' },
    { ID: 'seven', Title: 'Ride (7" Edit)', Artist: 'Lane', Key: 'Am' },
    { ID: '444', Title: '4:44', Artist: 'Jay', Key: 'Bm' },
    { ID: 'n44', Title: 'Number 44', Artist: 'Kay', Key: 'B' },
    { ID: 'rez', Title: 'Re:Zero', Artist: 'Kay', Key: 'Bb' },
    { ID: 'zp', Title: 'Zero Point', Artist: 'Kay', Key: '8A' },
];
const extraIds = (q) => filterTracks([...EXTRA], q).map((t) => t.ID);

test('an inch mark is a literal quote character, not an open phrase', () => {
    assert.deepEqual(tokenizeQuery('12" mix'), [
        { field: null, value: '12"', quoted: false },
        { field: null, value: 'mix', quoted: false },
    ]);
    assert.deepEqual(extraIds('12" mix'), ['blue']);
    assert.deepEqual(extraIds('7"'), ['seven']);
    assert.deepEqual(extraIds('title:7"'), ['seven']);
    // An opening quote without a closing one stays literal in free text...
    assert.deepEqual(tokenizeQuery('"deep ho'), [
        { field: null, value: '"deep', quoted: false },
        { field: null, value: 'ho', quoted: false },
    ]);
    // ...but right after `field:` it quotes the value being typed.
    assert.deepEqual(tokenizeQuery('genre:"deep ho'), [
        { field: 'genre', value: 'deep ho', quoted: true },
    ]);
    // A balanced pair at the start of a token is a phrase: "12", then mix.
    assert.deepEqual(extraIds('"12" mix'), ['blue']);
});

test('only known field names start a field token', () => {
    assert.deepEqual(tokenizeQuery('4:44 re:zero'), [
        { field: null, value: '4:44', quoted: false },
        { field: null, value: 're:zero', quoted: false },
    ]);
    assert.deepEqual(extraIds('4:44'), ['444']);
    assert.deepEqual(extraIds('re:zero'), ['rez']);
    assert.deepEqual(tokenizeQuery('Title:"Re:Zero"'), [
        { field: 'title', value: 're:zero', quoted: true },
    ]);
});

test('bpm:0 and year:0 list the zeros; comparisons still skip them', () => {
    assert.deepEqual(ids('bpm:0'), [4]);
    assert.deepEqual(ids('bpm:=0'), [4]);
    assert.deepEqual(ids('bpm:<200'), [1, 2, 3]);
    assert.deepEqual(ids('bpm:0-130'), [1]);
    assert.deepEqual(ids('year:0'), [3]);
    assert.deepEqual(ids('year:=0'), [3]);
    assert.deepEqual(ids('year:<2030'), [1, 2, 4]);
});

test('a bare note matches both modes; a mode or Camelot code one slot', () => {
    assert.deepEqual(extraIds('key:a'), ['blue', 'seven', 'zp']);
    assert.deepEqual(extraIds('key:am'), ['seven', 'zp']);
    assert.deepEqual(extraIds('key:8a'), ['seven', 'zp']);
    assert.deepEqual(extraIds('key:11b'), ['blue']);
    assert.deepEqual(extraIds('key:b'), ['444', 'n44']);
    assert.deepEqual(extraIds('key:bb'), ['rez']);
    assert.deepEqual(extraIds('key:bm'), ['444']);
});

test('half-typed tokens filter nothing instead of hiding every track', () => {
    for (const q of ['bpm:', 'rating:>=', 'rating:<', 'bpm:138-', 'genre:""']) {
        assert.deepEqual(ids(q), [1, 2, 3, 4], q);
    }
});

test('empty query returns the list itself', () => {
    const list = [...LIB];
    assert.equal(filterTracks(list, ''), list);
    assert.equal(filterTracks(list, '   '), list);
});
