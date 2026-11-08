/**
 * scRefreshClassification — what a failed `POST /api/soundcloud/refresh` means.
 *
 * Split out of `api.js` so the three-way verdict is testable without loading the
 * axios instance (importing `api.js` runs `_bootstrap()` and touches `window`).
 *
 * The route is `require_session`-gated, so a 401 has two different senders and they
 * need opposite remedies:
 *   - `detail === 'auth_expired'` (app/main.py, the SC-refresh route) — SoundCloud
 *     refused the stored refresh token, the keyring entry is already cleared, so the
 *     user has to consent again.
 *   - any other 401 — `require_session` rejected our own SESSION_TOKEN
 *     (app/auth.py sends detail "Unauthorized"). SoundCloud is untouched; running the
 *     OAuth window here would ask the user to fix the wrong thing.
 * Everything else — 503, 429, a network drop, a client-side timeout, an error with no
 * response at all — leaves the stored login intact, so it is transient by definition.
 *
 * The no-response case deliberately lands in `transient` rather than in its own
 * bucket: the client cannot tell a sidecar that died from one that is simply slower
 * than our timeout, and both are retryable.
 */

/** SoundCloud rejected the stored refresh token — re-consent needed. */
export const SC_EXPIRED = 'sc-expired';
/** Our own SESSION_TOKEN is stale (sidecar restarted) — app restart needed. */
export const SESSION_DEAD = 'session-dead';
/** Could not renew right now — the stored SC login is still there. */
export const TRANSIENT = 'transient';

const HTTP_UNAUTHORIZED = 401;
const SC_EXPIRED_DETAIL = 'auth_expired';

/**
 * Classify a rejected SC-refresh request.
 *
 * @param {unknown} err - an axios error, or anything a rejected promise carried.
 * @returns {'sc-expired'|'session-dead'|'transient'}
 */
export function classifyRefreshError(err) {
    const response = err?.response;
    if (!response || response.status !== HTTP_UNAUTHORIZED) return TRANSIENT;
    return response.data?.detail === SC_EXPIRED_DETAIL ? SC_EXPIRED : SESSION_DEAD;
}
