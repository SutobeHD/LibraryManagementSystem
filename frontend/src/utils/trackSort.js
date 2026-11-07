// Sort helpers for TrackTable. Each column maps a track to a typed sort value;
// null means "missing" and always sorts last, in both directions, so blank
// fields never crowd the top of a descending list.

const MUSICAL_TO_CAMELOT = {
    'G#m': '1A',
    Abm: '1A',
    B: '1B',
    Cb: '1B',
    'D#m': '2A',
    Ebm: '2A',
    'F#': '2B',
    Gb: '2B',
    'A#m': '3A',
    Bbm: '3A',
    Db: '3B',
    'C#': '3B',
    Fm: '4A',
    Ab: '4B',
    'G#': '4B',
    Cm: '5A',
    Eb: '5B',
    'D#': '5B',
    Gm: '6A',
    Bb: '6B',
    'A#': '6B',
    Dm: '7A',
    F: '7B',
    Am: '8A',
    C: '8B',
    Em: '9A',
    G: '9B',
    Bm: '10A',
    D: '10B',
    'F#m': '11A',
    Gbm: '11A',
    A: '11B',
    'C#m': '12A',
    Dbm: '12A',
    E: '12B',
};

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: 'base' });

const text = (value) => {
    const s = value == null ? '' : String(value).trim();
    return s || null;
};

const positive = (value) => {
    const n = typeof value === 'number' ? value : parseFloat(value);
    return Number.isFinite(n) && n > 0 ? n : null;
};

const count = (value) => {
    const n = typeof value === 'number' ? value : parseFloat(value);
    return Number.isFinite(n) && n >= 0 ? n : null;
};

/** Camelot code ("8A") for a Camelot or musical key ("Am", "F#m", "Bb"), else null. */
export function camelotOf(key) {
    const raw = text(key);
    if (!raw) return null;
    const s = raw
        .replace(/\s+/g, '')
        .replace(/♯/g, '#')
        .replace(/♭/g, 'b')
        .replace(/minor$|min$/i, 'm')
        .replace(/major$|maj$/i, '');
    const camelot = /^(\d{1,2})([AB])$/i.exec(s);
    if (camelot) {
        const num = Number(camelot[1]);
        return num >= 1 && num <= 12 ? `${num}${camelot[2].toUpperCase()}` : null;
    }
    const musical = s.charAt(0).toUpperCase() + s.slice(1).toLowerCase();
    return MUSICAL_TO_CAMELOT[musical] || null;
}

/** Position on the Camelot wheel: 1A, 1B, 2A, 2B ... 12B. Unknown keys return null. */
export function keySortValue(key) {
    const code = camelotOf(key);
    if (!code) return null;
    return parseInt(code, 10) * 2 + (code.endsWith('B') ? 1 : 0);
}

/** MyTag names, deduplicated in their original order ("Raw, Raw, Hypnotic" -> 2 tags). */
export function mytagList(raw) {
    const seen = new Set();
    for (const part of String(raw || '').split(',')) {
        const tag = part.trim();
        if (tag && !seen.has(tag)) seen.add(tag);
    }
    return [...seen];
}

/** Upper-case file extension of a local track ("AIFF"); null for streams and bare names. */
export function formatOf(track) {
    const path = String(track?.path || '');
    if (!path || /^(soundcloud|spotify):/i.test(path)) return null;
    const name = path.split(/[\\/]/).pop();
    const dot = name.lastIndexOf('.');
    return dot > 0 && dot < name.length - 1 ? name.slice(dot + 1).toUpperCase() : null;
}

/**
 * "YYYY-MM-DD" a track was added, else null. The live library sends StockDate;
 * a track without one arrives as the string "None", which must not count as a date.
 */
export function dateAdded(track) {
    const raw = text(track?.StockDate ?? track?.DateAdded);
    return raw && /^\d{4}-\d{2}-\d{2}/.test(raw) ? raw.slice(0, 10) : null;
}

export const SORT_VALUES = {
    Title: (t) => text(t.Title),
    Artist: (t) => text(t.Artist),
    Album: (t) => text(t.Album),
    Genre: (t) => text(t.Genre),
    Label: (t) => text(t.Label),
    Composer: (t) => text(t.Composer),
    Remixer: (t) => text(t.Remixer),
    MyTag: (t) => text(mytagList(t.MyTag).join(', ')),
    Format: (t) => formatOf(t),
    BPM: (t) => positive(t.BPM),
    Key: (t) => keySortValue(t.Key),
    Color: (t) => positive(t.ColorID),
    Rating: (t) => positive(t.Rating),
    Bitrate: (t) => positive(t.Bitrate),
    PlayCount: (t) => count(t.PlayCount),
    TotalTime: (t) => positive(t.TotalTime),
    ReleaseYear: (t) => positive(t.ReleaseYear),
    DateAdded: (t) => dateAdded(t),
};

function compareValues(a, b, dir) {
    if (a === null || b === null) {
        if (a === b) return 0;
        return a === null ? 1 : -1;
    }
    if (typeof a === 'number' && typeof b === 'number') return (a - b) * dir;
    return collator.compare(String(a), String(b)) * dir;
}

/**
 * New array sorted by one column; ties keep their incoming order.
 * Returns the input unchanged when no column is selected.
 */
export function sortTracks(tracks, { key, direction } = {}) {
    if (!key) return tracks;
    const valueOf = SORT_VALUES[key] || ((t) => text(t[key]));
    const dir = direction === 'desc' ? -1 : 1;
    return tracks
        .map((track) => ({ track, value: valueOf(track) }))
        .sort((a, b) => compareValues(a.value, b.value, dir))
        .map((row) => row.track);
}
