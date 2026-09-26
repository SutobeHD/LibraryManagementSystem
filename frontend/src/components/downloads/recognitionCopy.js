/**
 * Copy for the download recognizer (artist hub T-31): who a downloaded track is by,
 * whether the library knows them, and which names the file got.
 *
 * Pure — no React, no API — so `recognitionCopy.test.js` pins every sentence against
 * the payload `GET /api/soundcloud/tasks` carries in `task.recognition`
 * (`app/artist_store/recognizer.py:Recognition.as_dict`). A line never claims a
 * known artist, a correction or a suggestion the payload does not hold.
 */

/** How the artist is credited on THIS track — the role their artist page gives it. */
export const CREDIT_ROLE_LABEL = {
    primary: 'Artist',
    remixer: 'Remix',
    remixed_by_other: 'Original',
    featured: 'feat.',
};

export const CORRECTION_TEXT = {
    title_repeats_artist: 'Der Titel wiederholte den Artist-Namen.',
    known_artist_prefix: 'Der Titel nennt vor dem Bindestrich einen Artist aus deiner Library.',
    bound_account: 'Hochgeladen vom verknüpften SoundCloud-Konto des Artists.',
    known_spelling: 'Geschrieben wie in deiner Library.',
};

export const SUGGESTION_TEXT = {
    unknown_artist_prefix:
        'Der Titel nennt vor dem Bindestrich einen Artist, den deine Library noch nicht kennt — deshalb nur ein Vorschlag.',
};

const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;

/** `Artist – Title`, the way the task card shows a pair of names. */
export function formatNames(artist, title) {
    const a = String(artist ?? '').trim();
    const t = String(title ?? '').trim();
    if (a && t) return `${a} – ${t}`;
    return a || t;
}

/**
 * One chip per credited name: `{ key, label, title, tone }`, tone one of
 * `favourite` / `known` / `new`. Empty without a recognition.
 */
export function creditChips(recognition) {
    const credits = Array.isArray(recognition?.credits) ? recognition.credits : [];
    return credits
        .filter((c) => c && String(c.name ?? '').trim())
        .map((c, i) => {
            const role = CREDIT_ROLE_LABEL[c.role] || '';
            const shown = c.known && c.canonical ? c.canonical : c.name;
            const label = role ? `${shown} · ${role}` : shown;
            let tone = 'new';
            let title = 'Neu — noch nicht in deiner Library.';
            if (c.known) {
                const count = Number(c.library_tracks) || 0;
                const tracks = count
                    ? `${plural(count, 'Track', 'Tracks')} in deiner Library`
                    : 'Im Artist-Hub gespeichert';
                tone = c.favourite ? 'favourite' : 'known';
                title = c.favourite ? `Favorit · ${tracks}` : tracks;
            }
            return { key: c.collection_id || `${c.name}-${i}`, label, title, tone };
        });
}

/** One headline for the whole recognition, or null when there is nothing to say. */
export function recognitionHeadline(recognition) {
    const chips = creditChips(recognition);
    if (!chips.length) return null;
    const known = chips.filter((c) => c.tone !== 'new').length;
    if (known === 0) return chips.length === 1 ? 'Neuer Artist' : 'Neue Artists';
    if (known === chips.length) return 'Artist erkannt';
    return 'Teilweise erkannt';
}

/**
 * The correction the recognizer applied to the file, or null when the file carries
 * SoundCloud's own names. `{ before, after, reasons }`.
 */
export function correctionLine(recognition) {
    if (!recognition?.changed) return null;
    const reasons = (recognition.corrections ?? [])
        .map((code) => CORRECTION_TEXT[code])
        .filter(Boolean);
    return {
        before: formatNames(recognition.raw_artist, recognition.raw_title),
        after: formatNames(recognition.artist, recognition.title),
        reasons,
    };
}

const samePair = (a, b) => !!a && !!b && a.artist === b.artist && a.title === b.title;

/**
 * The pending suggestion for a task, or null.
 *
 * `state`: `open` (can be applied — the track is in the library), `waiting` (not
 * imported yet), `applied` (the file now carries it). `undo` is the pair to write back.
 */
export function suggestionState(recognition, localTrackId) {
    const suggestion = recognition?.suggestion;
    if (!suggestion?.artist || !suggestion?.title) return null;
    const applied = recognition.applied ?? null;
    let state = localTrackId ? 'open' : 'waiting';
    if (samePair(applied, suggestion)) state = 'applied';
    return {
        artist: suggestion.artist,
        title: suggestion.title,
        names: formatNames(suggestion.artist, suggestion.title),
        reason: SUGGESTION_TEXT[suggestion.reason] || '',
        state,
        undo: { artist: recognition.raw_artist ?? '', title: recognition.raw_title ?? '' },
    };
}
