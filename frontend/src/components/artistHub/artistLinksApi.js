/**
 * artistLinksApi — where an artist lives online, and which library tracks are theirs.
 *
 * Owner refinement 2026-09-26. Two small route families (`app/main.py`, after the
 * identity routes), kept apart from the catalogue module because neither speaks the
 * catalogue's union envelope:
 *
 *   GET    /api/artists/{id}/links                      → { links, hidden_count, last_fetch, musicbrainz }
 *   POST   /api/artists/{id}/links/refresh              → the same + { sources, musicbrainz_candidates, changes }
 *   POST   /api/artists/{id}/links            { url }   → { link }
 *   POST   /api/artists/{id}/links/remove     { url_key } → { outcome: "deleted" | "hidden" }
 *   POST   /api/artists/{id}/links/restore              → { restored }
 *   POST   /api/artists/{id}/links/musicbrainz { mbid } → refresh payload
 *   DELETE /api/artists/{id}/links/musicbrainz          → { removed, links, … }
 *   GET    /api/artists/{id}/soundcloud/candidates      → { candidates }
 *
 *   GET    /api/artists/{id}/local-tracks               → { tracks, counts, excluded, assigned_missing }
 *   POST   /api/artists/{id}/local-tracks/{track}       → { track, counts, excluded_count }
 *   GET    /api/artists/{id}/local-tracks/candidates?q= → { tracks, total }
 *
 * `sources` on a refresh is the honesty contract, as on the catalogue: a source that
 * was not reached says so, and the view must never render that as "no links".
 */

import api from '../../api/api';
import { ARTIST_ASSIGN_SEARCH_LIMIT, ARTIST_LINKS_TIMEOUT_MS } from '../../config/constants';
import { catalogueErrorMessage } from './artistCatalogueApi';

const base = (collectionId) => `/api/artists/${encodeURIComponent(collectionId)}`;

/** Same sentence rules as the catalogue: the backend's `detail`, never a raw code. */
export const linksErrorMessage = (error, fallback) => catalogueErrorMessage(error, fallback);

export const fetchLinks = async (collectionId) =>
    (await api.get(`${base(collectionId)}/links`)).data;

export const refreshLinks = async (collectionId, { musicbrainz = true } = {}) =>
    (
        await api.post(
            `${base(collectionId)}/links/refresh`,
            { musicbrainz },
            { timeout: ARTIST_LINKS_TIMEOUT_MS }
        )
    ).data;

export const addLink = async (collectionId, url) =>
    (await api.post(`${base(collectionId)}/links`, { url })).data;

export const removeLink = async (collectionId, urlKey) =>
    (await api.post(`${base(collectionId)}/links/remove`, { url_key: urlKey })).data;

export const restoreLinks = async (collectionId) =>
    (await api.post(`${base(collectionId)}/links/restore`)).data;

export const confirmMusicBrainz = async (collectionId, mbid) =>
    (
        await api.post(
            `${base(collectionId)}/links/musicbrainz`,
            { mbid },
            { timeout: ARTIST_LINKS_TIMEOUT_MS }
        )
    ).data;

export const dropMusicBrainz = async (collectionId) =>
    (await api.delete(`${base(collectionId)}/links/musicbrainz`)).data;

export const fetchSoundCloudCandidates = async (collectionId) =>
    (
        await api.get(`${base(collectionId)}/soundcloud/candidates`, {
            timeout: ARTIST_LINKS_TIMEOUT_MS,
        })
    ).data;

export const fetchLocalTracks = async (collectionId) =>
    (await api.get(`${base(collectionId)}/local-tracks`)).data;

/**
 * Assign, exclude or clear one library track for one artist. `name` lets the backend
 * store an artist that only existed as a library spelling until now.
 */
export const setTrackAssignment = async (collectionId, trackId, { action, role, name } = {}) =>
    (
        await api.post(`${base(collectionId)}/local-tracks/${encodeURIComponent(trackId)}`, {
            action,
            role: role ?? null,
            name: name ?? null,
        })
    ).data;

export const searchAssignCandidates = async (collectionId, query) =>
    (
        await api.get(`${base(collectionId)}/local-tracks/candidates`, {
            params: { q: query, limit: ARTIST_ASSIGN_SEARCH_LIMIT },
        })
    ).data;
