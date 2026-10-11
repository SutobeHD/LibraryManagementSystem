/**
 * artistDiscoveryApi — the discovery + background-sync half of the Artist Hub's HTTP
 * surface. Sibling of `artistCatalogueApi.js` (per-artist catalogue, link, download).
 *
 * Routes (`app/main.py`, "ARTIST HUB: discovery + background sync"):
 *
 *   GET  /api/artists/discover?limit=  → { status, soundcloud, suggestions, sources, … }
 *   GET  /api/artists/sync/status      → { status, enabled, running, idle, reason, … }
 *   POST /api/artists/sync/run         → { status, data: SyncRun }
 *
 * The discovery payload is **never a bare list**. `sources.related` and
 * `sources.co_occurrence` each carry their own state, and only `ok` entitles the UI to
 * say a source found nothing. Everything the caller needs to phrase that lives in
 * `discoveryCopy.js`; this module only speaks HTTP.
 *
 * A `sync/run` answer is a *report*, not a success flag: a pass that refused because
 * the app was busy comes back 200 with `reason_stopped: "busy:<probe>"`. Rendering that
 * as "synced" is exactly the fabrication this feature is under a hard gate for.
 */

import api from '../../api/api';
import {
    ARTIST_DISCOVER_LIMIT,
    ARTIST_DISCOVER_TIMEOUT_MS,
    ARTIST_SYNC_RUN_TIMEOUT_MS,
} from '../../config/constants';
import { catalogueErrorMessage } from './artistCatalogueApi';

const HTTP_CONFLICT = 409;

export const SYNC_ALREADY_RUNNING_MESSAGE =
    'A background sync pass is already running — its result appears here when it finishes.';

/** `GET /api/artists/discover`. Throws on transport failure; states live in the payload. */
export const fetchDiscovery = async ({ limit = ARTIST_DISCOVER_LIMIT } = {}) => {
    const res = await api.get('/api/artists/discover', {
        params: { limit },
        timeout: ARTIST_DISCOVER_TIMEOUT_MS,
    });
    return res.data ?? {};
};

/** `GET /api/artists/sync/status`. Read-only, unauthenticated, safe to poll. */
export const fetchSyncStatus = async () => {
    const res = await api.get('/api/artists/sync/status');
    return res.data ?? {};
};

/**
 * `POST /api/artists/sync/run`. `force` runs with the opt-in setting off; it does NOT
 * bypass the idle check, so a busy app still answers with a reason instead of a run.
 */
export const runBackgroundSync = async ({ force = false } = {}) => {
    const res = await api.post(
        '/api/artists/sync/run',
        { force },
        { timeout: ARTIST_SYNC_RUN_TIMEOUT_MS }
    );
    return res.data?.data ?? null;
};

export const isSyncAlreadyRunning = (error) => error?.response?.status === HTTP_CONFLICT;

/** A sentence for the user. Shares the catalogue routes' 401/429 vocabulary. */
export const discoveryErrorMessage = (error, fallback) => {
    if (isSyncAlreadyRunning(error)) return SYNC_ALREADY_RUNNING_MESSAGE;
    return catalogueErrorMessage(error, fallback);
};
