/**
 * linksCopy — what the artist view says about where an artist lives online, and about
 * which library tracks are theirs (owner refinement 2026-09-26).
 *
 * Pure string builders like `catalogueCopy.js`, unit-tested for the same reason: a
 * source that was never reached must not read as "this artist has no Instagram", and a
 * link fished out of a bio must not look as certain as one the artist published.
 *
 * Payload shapes: `app/artist_store/links.py::list_links` / `::refresh` and
 * `app/artist_store/attribution.py::local_tracks`.
 */

import { formatNumber, pluralise } from './mergeCopy.js';
import { relativeTime } from './catalogueCopy.js';

const THOUSAND = 1000;
const MILLION = 1000000;

/** Groups in display order. `category` comes from the backend's service table. */
export const LINK_GROUPS = [
    { key: 'social', label: 'Social' },
    { key: 'music', label: 'Listen' },
    { key: 'store', label: 'Buy' },
    { key: 'scene', label: 'Scene' },
    { key: 'web', label: 'Web' },
];

export const SOURCE_TEXT = {
    manual: 'Added by you',
    soundcloud_profile: 'From their SoundCloud profile',
    musicbrainz: 'From MusicBrainz',
    soundcloud_bio: 'Mentioned in their SoundCloud bio — check it before you trust it',
};

/** "Instagram · @boysnoize", "Spotify", "Website · boysnoize.com". */
export const linkLabel = (link) => {
    const service = link?.service_label || 'Link';
    const handle = link?.handle ? String(link.handle) : '';
    return handle ? `${service} · ${handle}` : service;
};

/** Hover text: where it goes and why it is shown. */
export const linkTitle = (link) => {
    const lines = [link?.url || ''];
    const source = SOURCE_TEXT[link?.source];
    if (source) lines.push(source);
    if (link?.title && link.title !== link?.service_label) lines.push(`Labelled "${link.title}"`);
    return lines.filter(Boolean).join('\n');
};

/** A bio link is a guess; every other source is the artist's or the user's own word. */
export const isTentative = (link) => link?.source === 'soundcloud_bio';

/** Links bucketed by `category`, groups without links dropped, backend order kept. */
export const groupLinks = (links) => {
    const byKey = new Map(LINK_GROUPS.map((g) => [g.key, []]));
    (Array.isArray(links) ? links : []).forEach((link) => {
        const bucket = byKey.get(link?.category) ?? byKey.get('web');
        bucket.push(link);
    });
    return LINK_GROUPS.map((g) => ({ ...g, links: byKey.get(g.key) })).filter(
        (g) => g.links.length > 0
    );
};

const SOUNDCLOUD_STATUS = {
    ok: { text: 'SoundCloud profile read', ok: true },
    not_linked: { text: 'SoundCloud: link their account to read its links', ok: false },
    not_connected: { text: 'SoundCloud: sign in to read their profile', ok: false },
    not_found: { text: 'SoundCloud: that account is gone', ok: false },
    failed: { text: 'SoundCloud could not be reached', ok: false },
    skipped_budget: { text: 'SoundCloud: call limit reached', ok: false },
};

const MUSICBRAINZ_STATUS = {
    ok: { text: 'MusicBrainz read', ok: true },
    no_match: { text: 'MusicBrainz has no entry for them', ok: true },
    needs_confirmation: { text: 'MusicBrainz: pick the right artist below', ok: false },
    ambiguous: { text: 'MusicBrainz ties their SoundCloud to several artists', ok: false },
    not_found: { text: 'MusicBrainz: the linked entry is gone', ok: false },
    failed: { text: 'MusicBrainz could not be reached', ok: false },
    not_queried: { text: 'MusicBrainz not asked', ok: false },
};

/** Per-source lines for the last refresh, `[]` when nothing was ever fetched. */
export const sourceLines = (sources) => {
    if (!sources || typeof sources !== 'object') return [];
    const out = [];
    const sc = SOUNDCLOUD_STATUS[sources.soundcloud];
    if (sc) out.push({ key: 'soundcloud', ...sc });
    const mb = MUSICBRAINZ_STATUS[sources.musicbrainz];
    if (mb) out.push({ key: 'musicbrainz', ...mb });
    return out;
};

/** "Checked 5 min ago" — or null before the first Find-links click. */
export const lastFetchedLine = (lastFetch) => {
    const when = relativeTime(lastFetch?.fetched_at);
    return when ? `Checked ${when}` : null;
};

/**
 * What an empty strip says. It may only claim "nothing listed" when every source it
 * asked actually answered; otherwise it names what was not reached.
 */
export const emptyLinksNote = (payload) => {
    const sources = payload?.sources ?? payload?.last_fetch?.sources;
    if (!sources) {
        return 'No links yet. "Find links" reads their SoundCloud profile and MusicBrainz — or add one yourself.';
    }
    const lines = sourceLines(sources);
    const unreached = lines.filter((line) => !line.ok);
    if (unreached.length === 0) {
        return 'Neither their SoundCloud profile nor MusicBrainz lists another profile. Add one yourself if you know it.';
    }
    return `${unreached.map((line) => line.text).join(' · ')} — links from there may be missing.`;
};

export const hiddenLine = (count) =>
    Number(count) > 0 ? `${pluralise(count, 'hidden link', 'hidden links')} — restore` : null;

/** "Boys Noize — Person · DE · score 100" for a MusicBrainz candidate. */
export const musicBrainzCandidateLine = (candidate) => {
    const bits = [candidate?.type, candidate?.country].filter(Boolean);
    if (candidate?.disambiguation) bits.push(`“${candidate.disambiguation}”`);
    if (Number.isFinite(Number(candidate?.score))) bits.push(`score ${Number(candidate.score)}`);
    const tail = bits.length ? ` — ${bits.join(' · ')}` : '';
    return `${candidate?.name || 'Unnamed'}${tail}`;
};

/** 1234 → "1.2k", 1234567 → "1.2M". Exact below a thousand. */
export const compactCount = (value) => {
    const n = Number(value);
    if (!Number.isFinite(n) || n < 0) return '0';
    if (n >= MILLION) return `${(n / MILLION).toFixed(1).replace(/\.0$/, '')}M`;
    if (n >= THOUSAND) return `${(n / THOUSAND).toFixed(1).replace(/\.0$/, '')}k`;
    return formatNumber(n);
};

const MATCH_TEXT = {
    exact: 'same name',
    close: 'same name without spaces',
    weak: 'different name',
};

/** "1.2M followers · 312 tracks · Berlin, DE · same name" for a SoundCloud account. */
export const soundCloudCandidateLine = (user) => {
    const bits = [
        `${compactCount(user?.followers_count)} followers`,
        `${formatNumber(user?.track_count)} tracks`,
    ];
    const place = [user?.city, user?.country].filter(Boolean).join(', ');
    if (place) bits.push(place);
    if (MATCH_TEXT[user?.match]) bits.push(MATCH_TEXT[user.match]);
    return bits.join(' · ');
};

// --------------------------------------------------------------------------- local roles

/** The local panel's filters, in display order. `key` is a role or a pseudo-group. */
export const LOCAL_FILTERS = [
    { key: 'all', label: 'All' },
    { key: 'primary', label: 'Their tracks' },
    { key: 'remixer', label: 'Their remixes' },
    { key: 'remixed_by_other', label: 'Remixed by others' },
    { key: 'featured', label: 'Featured on' },
    { key: 'manual', label: 'Added by you' },
];

export const LOCAL_ROLE_LABEL = {
    primary: 'Their track',
    remixer: 'Their remix',
    remixed_by_other: 'Remixed by other',
    featured: 'Featured',
};

/** The roles a user can give a track by hand, in the order the menus offer them. */
export const ASSIGNABLE_ROLES = ['primary', 'remixer', 'remixed_by_other', 'featured'];

export const LOCAL_SOURCE_TEXT = {
    artist_field: 'Artist field',
    remixer_field: 'Remixer field',
    title_remix: 'Remix credit in the title',
    title_featured: 'Feature credit in the title',
    title_prefix: 'Artist name in the title',
    manual: 'Assigned by you',
};

/** Count per filter key, read from the payload — never recounted into a different number. */
export const localFilterCount = (payload, key) => {
    const counts = payload?.counts ?? {};
    if (key === 'all') return Number(counts.total) || 0;
    return Number(counts[key]) || 0;
};

/** Tracks for one filter. `manual` is a source, every other key a role. */
export const filterLocalTracks = (tracks, key) => {
    const rows = Array.isArray(tracks) ? tracks : [];
    if (key === 'all') return rows;
    if (key === 'manual') return rows.filter((t) => t?.artist_role?.source === 'manual');
    return rows.filter((t) => t?.artist_role?.role === key);
};

/** "Their remix · Remix credit in the title" — the why behind a row's badge. */
export const localRoleTitle = (track) => {
    const role = track?.artist_role;
    if (!role) return '';
    const label = LOCAL_ROLE_LABEL[role.role] || role.role;
    const source = LOCAL_SOURCE_TEXT[role.source] || role.source;
    return [label, source, role.detail].filter(Boolean).join(' · ');
};

/**
 * The line under the local panel head. Says when the library is not loaded instead of
 * implying the artist owns nothing, and names manual rows that left the library.
 */
export const localSummaryLine = (payload) => {
    if (!payload) return null;
    if (payload.library_loaded === false) return 'Load a library to see which tracks are theirs.';
    const bits = [];
    const excluded = (payload.excluded ?? []).length;
    const missing = (payload.assigned_missing ?? []).length;
    if (excluded) bits.push(`${pluralise(excluded, 'track', 'tracks')} excluded by you`);
    if (missing) {
        bits.push(
            `${pluralise(missing, 'assigned track', 'assigned tracks')} no longer in the library`
        );
    }
    return bits.length ? bits.join(' · ') : null;
};
