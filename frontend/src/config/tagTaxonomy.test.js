/**
 * node --test frontend/src/config/tagTaxonomy.test.js
 *
 * Pure module, imports carry extensions — no resolver needed. Guards two things:
 * the taxonomy stays sorted and free of duplicates, and chip toggling works on whole
 * comma-separated tokens (the old substring match turned 'Hard Techno' into 'Hard '
 * when 'Techno' was toggled off).
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import {
    ALL_TAGS,
    COMPONENT_TAGS,
    GENRES,
    GENRE_TREE,
    SUBGENRE_GROUPS,
    TYPE_TAGS,
    hasCommentTag,
    splitCommentTags,
    toggleCommentTag,
} from './tagTaxonomy.js';

const isSorted = (list) =>
    list.every((item, i) => i === 0 || list[i - 1].localeCompare(item, 'en') < 0);

test('genres and every sub-genre list are alphabetical', () => {
    assert.ok(isSorted(GENRES), `genres not sorted: ${GENRES.join(', ')}`);
    for (const [genre, subs] of Object.entries(GENRE_TREE)) {
        assert.ok(isSorted(subs), `${genre} sub-genres not sorted: ${subs.join(', ')}`);
    }
    assert.ok(isSorted(COMPONENT_TAGS), `components not sorted: ${COMPONENT_TAGS.join(', ')}`);
});

test('type tags keep the energy-curve order, not alphabetical', () => {
    assert.deepEqual(TYPE_TAGS, ['relaxed', 'progressiv', 'Build up', 'Peak Time', 'Build down']);
});

test('no tag appears in two lists, even with different casing', () => {
    const seen = new Map();
    for (const tag of ALL_TAGS) {
        const key = tag.toLowerCase();
        assert.ok(!seen.has(key), `duplicate tag: '${tag}' and '${seen.get(key)}'`);
        seen.set(key, tag);
    }
});

test('sub-genre groups only list genres that have sub-genres', () => {
    for (const [genre, subs] of SUBGENRE_GROUPS) {
        assert.ok(GENRES.includes(genre));
        assert.ok(subs.length > 0);
    }
    assert.ok(!SUBGENRE_GROUPS.some(([genre]) => genre === 'House'));
});

test('splitCommentTags trims tokens and drops empties', () => {
    assert.deepEqual(splitCommentTags(' Techno,  Acid ,, Dark, '), ['Techno', 'Acid', 'Dark']);
    assert.deepEqual(splitCommentTags(''), []);
    assert.deepEqual(splitCommentTags(null), []);
});

test('hasCommentTag matches whole tokens only', () => {
    assert.equal(hasCommentTag('Hard Techno, Schranz', 'Techno'), false);
    assert.equal(hasCommentTag('Hard Techno, Schranz', 'Hard Techno'), true);
    assert.equal(hasCommentTag('Hardgroove', 'Groove'), false);
    assert.equal(hasCommentTag('Techno, euphoric', 'Euphoric'), true);
});

test('toggleCommentTag appends a missing tag and removes a present one', () => {
    assert.equal(toggleCommentTag('', 'Techno'), 'Techno');
    assert.equal(toggleCommentTag('Techno', 'Acid'), 'Techno, Acid');
    assert.equal(toggleCommentTag('Techno, Acid', 'Techno'), 'Acid');
    assert.equal(toggleCommentTag('Techno, Acid', 'Acid'), 'Techno');
});

test('toggling Techno off leaves Hard Techno untouched', () => {
    assert.equal(toggleCommentTag('Hard Techno, Techno', 'Techno'), 'Hard Techno');
    assert.equal(toggleCommentTag('Hard Techno', 'Techno'), 'Hard Techno, Techno');
});

test('toggle removes an older lower-case spelling of the same tag', () => {
    assert.equal(toggleCommentTag('Techno, euphoric', 'Euphoric'), 'Techno');
});

test('free text between commas survives a toggle', () => {
    assert.equal(toggleCommentTag('great drop at 2:10, Techno', 'Techno'), 'great drop at 2:10');
    assert.equal(toggleCommentTag('great drop at 2:10', 'Techno'), 'great drop at 2:10, Techno');
});
