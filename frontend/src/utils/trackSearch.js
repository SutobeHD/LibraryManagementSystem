// Token search for the Collection / playlist views. The query is parsed once per
// keystroke into predicates; each track is then checked against them, with one
// lower-cased free-text haystack per track built once per list.
//
//   bpm:>140  bpm:<=128  bpm:138-142  bpm:128     (0 = not analysed: only bpm:0 finds it)
//   rating:>=4  rating:<3  rating:5               (0 = unrated, a real value)
//   year:2024  year:>=2020                        (0 = unknown: only year:0 finds it)
//   key:8A  key:Am  key:A                         (Camelot slot; a bare note = both modes)
//   genre:techno  genre:"deep house"  label:…  artist:…  title:…  album:…
//   "deep house"                                  (quoted phrase, free text)
//   anything else                                 (free text: Title/Artist/Album/Comment/Genre/Label)
//
// Only a known field name before the colon starts a field token: `4:44` and
// `re:zero` stay free text as typed. A `"` opens a quote directly after `field:`
// or at the start of a free-text token that has a closing `"`; any other `"` is
// a literal character (`12" mix`). A field value that is no number falls back
// to free text as typed; a field still being typed ("bpm:", "rating:>=",
// "bpm:138-") filters nothing.

import { camelotOf } from './trackSort.js';

// Tooltip for the search box.
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

const KNOWN_FIELDS = new Set([...NUMBER_FIELDS.keys(), 'key', ...TEXT_FIELD_PROPS.keys()]);

const NUMBER = /^\d+(?:\.\d*)?$/;
const RANGE = /^(\d+(?:\.\d*)?)-(\d+(?:\.\d*)?)?$/;
const OPERATOR = /^(>=|<=|>|<|=)?(.*)$/;
const FIELD_PREFIX = /^([a-z]+):/;
const NOTE_ONLY = /^[a-g](?:#|b|♯|♭)?$/;
const SPACE = /\s/;

/**
 * Split a lower-cased query into `{ field, value, quoted }` tokens on whitespace.
 * `field` is set only for a known field name before the colon. A `"` directly
 * after `field:` quotes the value (unclosed runs to the end, still typing:
 * `genre:"deep ho`); at the start of a free-text token it quotes a phrase only
 * when a closing `"` follows. Every other `"` is a literal character.
 */
export function tokenizeQuery(query) {
    const q = String(query || '').toLowerCase();
    const tokens = [];
    let i = 0;
    while (i < q.length) {
        while (i < q.length && SPACE.test(q[i])) i += 1;
        if (i >= q.length) break;
        let field = null;
        let text = '';
        let quoted = false;
        const prefix = FIELD_PREFIX.exec(q.slice(i, i + 16));
        if (prefix && KNOWN_FIELDS.has(prefix[1])) {
            field = prefix[1];
            i += prefix[0].length;
            if (q[i] === '"') {
                const close = q.indexOf('"', i + 1);
                const end = close === -1 ? q.length : close;
                text = q.slice(i + 1, end);
                quoted = true;
                i = close === -1 ? q.length : close + 1;
            }
        } else if (q[i] === '"') {
            const close = q.indexOf('"', i + 1);
            if (close !== -1) {
                text = q.slice(i + 1, close);
                quoted = true;
                i = close + 1;
            }
        }
        while (i < q.length && !SPACE.test(q[i])) {
            text += q[i];
            i += 1;
        }
        tokens.push({ field, value: text, quoted });
    }
    return tokens;
}

const freeText = (needle) => (needle ? (_t, hay) => hay.includes(needle) : null);

// Predicate for a numeric field; null while the value is still being typed
// ("rating:>=", "bpm:138-"), undefined when the value is no number at all.
// Zero-is-missing fields keep 0 out of ranges and comparisons, while an exact
// `bpm:0` / `year:0` lists exactly those tracks.
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
    if (op === '=') {
        if (spec.round) return (t) => Math.round(of(t)) === Math.round(target);
        return (t) => of(t) === target;
    }
    const cmp = {
        '>': (n) => n > target,
        '>=': (n) => n >= target,
        '<': (n) => n < target,
        '<=': (n) => n <= target,
    }[op];
    return (t) => {
        const n = of(t);
        return present(n) && cmp(n);
    };
}

// Camelot code ("8A") or a key with its mode ("Am") -> that slot; a bare note
// ("a", "f#", "bb") -> major and minor; anything else matches as a substring.
function keyPredicate(value) {
    const slots = NOTE_ONLY.test(value)
        ? [camelotOf(value), camelotOf(`${value}m`)].filter(Boolean)
        : [camelotOf(value)].filter(Boolean);
    if (slots.length === 1) return (t) => camelotOf(t.Key) === slots[0];
    if (slots.length === 2) {
        return (t) => {
            const slot = camelotOf(t.Key);
            return slot === slots[0] || slot === slots[1];
        };
    }
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
        return pred === undefined ? freeText(`${field}:${value}`) : pred;
    }
    if (field === 'key') return keyPredicate(value);
    const prop = TEXT_FIELD_PROPS.get(field);
    if (prop)
        return (t) =>
            String(t[prop] || '')
                .toLowerCase()
                .includes(value);
    return freeText(`${field}:${value}`);
}

// Whole query -> one predicate `(track, hay) => boolean`; all tokens must match.
export function compileQuery(query) {
    const preds = tokenizeQuery(query).map(compileToken).filter(Boolean);
    return (t, hay) => preds.every((pred) => pred(t, hay));
}

// Tracks of `list` matching `query`; the list itself when the query is empty.
export function filterTracks(list, query) {
    if (!query || !String(query).trim()) return list;
    const match = compileQuery(query);
    const hays = haysFor(list);
    return list.filter((t, i) => match(t, hays[i]));
}
