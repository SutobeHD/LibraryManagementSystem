// Tag chips for the Ranking view. A chip writes its label verbatim as one
// comma-separated token into the track Comment (that is what Rekordbox shows), so
// every string below is a token exactly as it lands in the library.
//
// Genres are the top level; each genre owns its sub-genres. Lists are alphabetical
// except TYPE_TAGS, which follows the energy curve of a set on purpose. A tag may
// appear in exactly one list: the same token cannot mean two things in a comment.

export const GENRE_TREE = {
    'Hard Techno': ['Schranz'],
    House: [],
    Techno: ['Acid', 'Groove', 'Hardgroove', 'Industrial', 'Minimal', 'Raw', 'Tribal'],
    Trance: [],
};

export const GENRES = Object.keys(GENRE_TREE);

// [genre, subgenres] pairs for the genres that have sub-genres, in genre order.
export const SUBGENRE_GROUPS = Object.entries(GENRE_TREE).filter(([, subs]) => subs.length > 0);

export const COMPONENT_TAGS = [
    'Beat',
    'Bounce',
    'Dark',
    'Emotional',
    'Euphoric',
    'Fluid',
    'Fun',
    'Hypnotic',
    'Melodic',
    'Synth',
    'Vocal',
];

export const TYPE_TAGS = ['relaxed', 'progressiv', 'Build up', 'Peak Time', 'Build down'];

export const ALL_TAGS = [
    ...GENRES,
    ...SUBGENRE_GROUPS.flatMap(([, subs]) => subs),
    ...COMPONENT_TAGS,
    ...TYPE_TAGS,
];

const sameTag = (a, b) => a.trim().toLowerCase() === b.trim().toLowerCase();

// A comment is a comma-separated list of tokens; free text between commas is kept
// as its own token so toggling a chip never rewrites what the user typed.
export const splitCommentTags = (comment) =>
    (comment || '')
        .split(',')
        .map((token) => token.trim())
        .filter(Boolean);

// Whole-token match, case-insensitive: 'Techno' is not active because the comment
// says 'Hard Techno', and 'euphoric' from an older comment still lights 'Euphoric'.
export const hasCommentTag = (comment, tag) =>
    splitCommentTags(comment).some((token) => sameTag(token, tag));

export const toggleCommentTag = (comment, tag) => {
    const tokens = splitCommentTags(comment);
    const without = tokens.filter((token) => !sameTag(token, tag));
    if (without.length !== tokens.length) return without.join(', ');
    return [...tokens, tag].join(', ');
};
