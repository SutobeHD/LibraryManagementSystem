// node:test — `node --test frontend/src/components/artistHub/linksCopy.test.js`
//
// The artist view's sentences about links and local roles. The rule these pin: an
// unreached source never reads as "no links", a bio link never reads as certain, and
// every count comes from the payload.

import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
    compactCount,
    emptyLinksNote,
    filterLocalTracks,
    groupLinks,
    hiddenLine,
    isTentative,
    lastFetchedLine,
    linkLabel,
    linkTitle,
    localFilterCount,
    localRoleTitle,
    localSummaryLine,
    musicBrainzCandidateLine,
    soundCloudCandidateLine,
    sourceLines,
} from './linksCopy.js';

const IG = {
    url: 'https://www.instagram.com/boysnoize',
    service: 'instagram',
    service_label: 'Instagram',
    category: 'social',
    handle: '@boysnoize',
    source: 'soundcloud_profile',
};

test('a link reads as service plus handle', () => {
    assert.equal(linkLabel(IG), 'Instagram · @boysnoize');
    assert.equal(linkLabel({ service_label: 'Spotify' }), 'Spotify');
    assert.equal(linkLabel(null), 'Link');
});

test('the hover text says where it goes and why it is shown', () => {
    assert.equal(
        linkTitle(IG),
        'https://www.instagram.com/boysnoize\nFrom their SoundCloud profile'
    );
    assert.match(linkTitle({ ...IG, source: 'soundcloud_bio' }), /check it before you trust it/);
});

test('only a bio link is tentative', () => {
    assert.equal(isTentative({ source: 'soundcloud_bio' }), true);
    for (const source of ['manual', 'soundcloud_profile', 'musicbrainz']) {
        assert.equal(isTentative({ source }), false);
    }
});

test('links group by category in display order, empty groups dropped', () => {
    const groups = groupLinks([
        { category: 'store', url: 'b' },
        IG,
        { category: 'mystery', url: 'w' },
    ]);
    assert.deepEqual(
        groups.map((g) => [g.key, g.links.length]),
        [
            ['social', 1],
            ['store', 1],
            ['web', 1],
        ]
    );
    assert.deepEqual(groupLinks(undefined), []);
});

test('never fetched is not "nothing found"', () => {
    assert.match(emptyLinksNote({}), /No links yet/);
    assert.match(emptyLinksNote(null), /No links yet/);
});

test('an unreached source is named instead of claiming absence', () => {
    const note = emptyLinksNote({ sources: { soundcloud: 'failed', musicbrainz: 'ok' } });
    assert.match(note, /SoundCloud could not be reached/);
    assert.doesNotMatch(note, /Neither/);
    const unlinked = emptyLinksNote({
        sources: { soundcloud: 'not_linked', musicbrainz: 'no_match' },
    });
    assert.match(unlinked, /link their account/);
});

test('absence is only claimed when every source answered', () => {
    assert.match(
        emptyLinksNote({ last_fetch: { sources: { soundcloud: 'ok', musicbrainz: 'no_match' } } }),
        /Neither their SoundCloud profile nor MusicBrainz/
    );
});

test('source lines carry an ok flag per source', () => {
    assert.deepEqual(
        sourceLines({ soundcloud: 'ok', musicbrainz: 'needs_confirmation' }).map((l) => [
            l.key,
            l.ok,
        ]),
        [
            ['soundcloud', true],
            ['musicbrainz', false],
        ]
    );
    assert.deepEqual(sourceLines(undefined), []);
});

test('last fetched and hidden lines stay silent without data', () => {
    assert.equal(lastFetchedLine(null), null);
    assert.equal(hiddenLine(0), null);
    assert.equal(hiddenLine(2), '2 hidden links — restore');
    assert.equal(hiddenLine(1), '1 hidden link — restore');
});

test('candidate lines', () => {
    assert.equal(
        musicBrainzCandidateLine({
            name: 'Boys Noize',
            type: 'Person',
            country: 'DE',
            disambiguation: 'German DJ',
            score: 100,
        }),
        'Boys Noize — Person · DE · “German DJ” · score 100'
    );
    assert.equal(
        soundCloudCandidateLine({
            followers_count: 1234567,
            track_count: 312,
            city: 'Berlin',
            country: 'Germany',
            match: 'exact',
        }),
        '1.2M followers · 312 tracks · Berlin, Germany · same name'
    );
    assert.equal(compactCount(999), '999');
    assert.equal(compactCount(1500), '1.5k');
    assert.equal(compactCount('x'), '0');
});

const PAGE = {
    library_loaded: true,
    counts: { total: 4, primary: 2, remixer: 1, remixed_by_other: 0, featured: 1, manual: 1 },
    tracks: [
        { ID: '1', artist_role: { role: 'primary', source: 'artist_field' } },
        { ID: '2', artist_role: { role: 'primary', source: 'manual' } },
        {
            ID: '3',
            artist_role: {
                role: 'remixer',
                source: 'title_remix',
                detail: 'Title credits their remix',
            },
        },
        { ID: '4', artist_role: { role: 'featured', source: 'artist_field' } },
    ],
    excluded: [{ track_id: '9' }],
    assigned_missing: [],
};

test('local filters read the payload counts and split by role or source', () => {
    assert.equal(localFilterCount(PAGE, 'all'), 4);
    assert.equal(localFilterCount(PAGE, 'remixer'), 1);
    assert.equal(localFilterCount(PAGE, 'manual'), 1);
    assert.equal(localFilterCount(null, 'all'), 0);
    assert.deepEqual(
        filterLocalTracks(PAGE.tracks, 'primary').map((t) => t.ID),
        ['1', '2']
    );
    assert.deepEqual(
        filterLocalTracks(PAGE.tracks, 'manual').map((t) => t.ID),
        ['2']
    );
    assert.equal(filterLocalTracks(PAGE.tracks, 'all').length, 4);
});

test('a role badge explains itself', () => {
    assert.equal(
        localRoleTitle(PAGE.tracks[2]),
        'Their remix · Remix credit in the title · Title credits their remix'
    );
    assert.equal(localRoleTitle({}), '');
});

test('the summary line says why a list may look short', () => {
    assert.equal(localSummaryLine(PAGE), '1 track excluded by you');
    assert.equal(
        localSummaryLine({ library_loaded: false }),
        'Load a library to see which tracks are theirs.'
    );
    assert.equal(
        localSummaryLine({ ...PAGE, excluded: [], assigned_missing: [{}, {}] }),
        '2 assigned tracks no longer in the library'
    );
    assert.equal(localSummaryLine({ ...PAGE, excluded: [] }), null);
});
