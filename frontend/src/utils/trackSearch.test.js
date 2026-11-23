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

test('unknown fields and malformed numbers fall back to free text', () => {
    assert.deepEqual(ids('mood:techno'), [3, 4]);
    assert.deepEqual(ids('re:mix'), [2]);
    assert.deepEqual(ids('rating:high'), []);
    assert.deepEqual(ids('bpm:fast'), []);
    assert.equal(typeof compileToken({ field: 'rating', value: 'abc' }), 'function');
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
