// Token search for the Collection / playlist views. The query is parsed once per
// keystroke into predicates; each track is then checked against them, with one
// lower-cased free-text haystack per track built once per list.
//
//   bpm:>140  bpm:<=128  bpm:138-142  bpm:128     (0 = not analysed, never matches)
//   rating:>=4  rating:<3  rating:5               (0 = unrated, a real value)
//   year:2024  year:>=2020                        (0 = unknown, never matches)
//   key:Am  key:8A                                (same Camelot slot; else substring)
//   genre:techno  genre:"deep house"  label:…  artist:…  title:…  album:…
//   "deep house"                                  (quoted phrase, free text)
//   anything else                                 (free text: Title/Artist/Album/Comment/Genre/Label)
//
// A token that cannot work as a filter (unknown field, value that is no number)
// falls back to free text (the token as written, or its value) instead of
// silently matching nothing; a field still being typed ("bpm:", "rating:>=",
// "bpm:138-") filters nothing.

import { camelotOf } from './trackSort.js';

/** Tooltip for the search box. */
export const SEARCH_SYNTAX_HINT =
    'Filter: bpm:>140  bpm:138-142  rating:>=4  year:2024  key:8A  genre:"deep house"  label:  artist:  title:  album:  "exact phrase"';

const trackHay = (t) =>
    [t.Title, t.Artist, t.Album, t.Comment, t.Genre, t.Label]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();

// Index-aligned with the list and reused until the list is replaced (every reload
// sets a new array): ~4x faster than a per-track lookup.
const haysByList = new WeakMap();
const haysFor = (list) => {
    let hays = haysByList.get(list);
    if (!hays) {
        hays = list.map(trackHay);
        haysByList.set(list, hays);
    }
    return hays;
};

const TEXT_FIELD_PROPS = new Map([
    ['genre', 'Genre'],
    ['label', 'Label'],
    ['artist', 'Artist'],
    ['title', 'Title'],
    ['album', 'Album'],
]);

const NUMBER_FIELDS = new Map([
    ['bpm', { of: (t) => parseFloat(t.BPM) || 0, zeroIsMissing: true, round: true }],
    ['rating', { of: (t) => parseInt(t.Rating, 10) || 0, zeroIsMissing: false }],
    ['year', { of: (t) => parseInt(t.ReleaseYear, 10) || 0, zeroIsMissing: true }],
]);

const NUMBER = /^\d+(?:\.\d*)?$/;
const RANGE = /^(\d+(?:\.\d*)?)-(\d+(?:\.\d*)?)?$/;
const OPERATOR = /^(>=|<=|>|<|=)?(.*)$/;

/**
 * Split a query into tokens. Whitespace separates tokens except inside double
 * quotes; an unclosed quote runs to the end (the user is still typing). A colon
 * before any quote splits field and value: `genre:"deep house"` ->
 * { field: 'genre', value: 'deep house' }. Everything is lower-cased.
 */
export function tokenizeQuery(query) {
    const q = String(query || '').toLowerCase();
    const tokens = [];
    let i = 0;
    while (i < q.length) {
        while (i < q.length && /\s/.test(q[i])) i += 1;
        if (i >= q.length) break;
        let field = null;
        let text = '';
        let quoted = false;
        while (i < q.length && !/\s/.test(q[i])) {
            const ch = q[i];
            if (ch === '"') {
                const close = q.indexOf('"', i + 1);
                const end = close === -1 ? q.length : close;
                text += q.slice(i + 1, end);
                quoted = true;
                i = close === -1 ? q.length : close + 1;
            } else if (ch === ':' && field === null && !quoted && text) {
                field = text;
                text = '';
                i += 1;
            } else {
                text += ch;
                i += 1;
            }
        }
        tokens.push({ field, value: text, quoted });
    }
    return tokens;
}

const freeText = (needle) => (needle ? (_t, hay) => hay.includes(needle) : null);

// A field token that cannot filter: match the token as written ("re:mix" in a
// title) or just its value (`mood:dark` finds "dark").
const fallback = ({ field, value }) => {
    const whole = `${field}:${value}`;
    return (_t, hay) => hay.includes(whole) || hay.includes(value);
};

// Predicate for a numeric field; null while the value is still being typed
// ("rating:>=", "bpm:138-"), undefined when the value is no number at all.
function numberPredicate(spec, value) {
    const { of, zeroIsMissing } = spec;
    const present = zeroIsMissing ? (n) => n !== 0 : () => true;
    const range = RANGE.exec(value);
    if (range) {
        if (range[2] === undefined) return null;
        const a = parseFloat(range[1]);
        const b = parseFloat(range[2]);
        const lo = Math.min(a, b);
        const hi = Math.max(a, b);
        return (t) => {
            const n = of(t);
            return present(n) && n >= lo && n <= hi;
        };
    }
    const [, op = '=', rest] = OPERATOR.exec(value);
    if (!rest) return null;
    if (!NUMBER.test(rest)) return undefined;
    const target = parseFloat(rest);
    const cmp = {
        '>': (n) => n > target,
        '>=': (n) => n >= target,
        '<': (n) => n < target,
        '<=': (n) => n <= target,
        '=': spec.round ? (n) => Math.round(n) === Math.round(target) : (n) => n === target,
    }[op];
    return (t) => {
        const n = of(t);
        return present(n) && cmp(n);
    };
}

function keyPredicate(value) {
    const slot = camelotOf(value);
    if (slot) return (t) => camelotOf(t.Key) === slot;
    return (t) =>
        String(t.Key || '')
            .toLowerCase()
            .includes(value);
}

/**
 * One token -> predicate `(track, hay) => boolean`, or null for a token that
 * filters nothing yet (empty value, operator without a number).
 */
export function compileToken(token) {
    const { field, value } = token;
    if (field === null) return freeText(value);
    if (!value) return null;
    const spec = NUMBER_FIELDS.get(field);
    if (spec) {
        const pred = numberPredicate(spec, value);
        return pred === undefined ? fallback(token) : pred;
    }
    if (field === 'key') return keyPredicate(value);
    const prop = TEXT_FIELD_PROPS.get(field);
    if (prop)
        return (t) =>
            String(t[prop] || '')
                .toLowerCase()
                .includes(value);
    return fallback(token);
}

/** Whole query -> one predicate `(track, hay) => boolean`; all tokens must match. */
export function compileQuery(query) {
    const preds = tokenizeQuery(query).map(compileToken).filter(Boolean);
    return (t, hay) => preds.every((pred) => pred(t, hay));
}

/** Tracks of `list` matching `query`; the list itself when the query is empty. */
export function filterTracks(list, query) {
    if (!query || !String(query).trim()) return list;
    const match = compileQuery(query);
    const hays = haysFor(list);
    return list.filter((t, i) => match(t, hays[i]));
}
