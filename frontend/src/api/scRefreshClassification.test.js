/**
 * node --test frontend/src/api/scRefreshClassification.test.js
 *
 * Pure predicate — no DOM, no axios, no resolver needed (the import carries its
 * extension). The load-bearing cases are the ones that decide which remedy the user
 * is shown: only the `auth_expired` marker may open the OAuth window, a bare 401 from
 * `require_session` means our own bearer died, and anything without that 401 leaves
 * the stored SoundCloud login alone and must read as retryable.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import {
    SC_EXPIRED,
    SESSION_DEAD,
    TRANSIENT,
    classifyRefreshError,
} from './scRefreshClassification.js';

/** An axios-shaped rejection. */
const axiosErr = (status, data) => ({
    isAxiosError: true,
    message: `Request failed with status code ${status}`,
    response: { status, data },
});

test('401 with the auth_expired marker is the SoundCloud session', () => {
    assert.equal(classifyRefreshError(axiosErr(401, { detail: 'auth_expired' })), SC_EXPIRED);
});

test('the full backend body shape still classifies as sc-expired', () => {
    // app/main.py answers the genuine expiry with both fields.
    const err = axiosErr(401, { status: 'expired', detail: 'auth_expired' });
    assert.equal(classifyRefreshError(err), SC_EXPIRED);
});

test('401 from require_session is our own dead bearer, not SoundCloud', () => {
    assert.equal(classifyRefreshError(axiosErr(401, { detail: 'Unauthorized' })), SESSION_DEAD);
});

test('a 401 with no usable body is treated as the dead bearer', () => {
    // Conservative on purpose: without the marker we must not open the OAuth window.
    assert.equal(classifyRefreshError(axiosErr(401, undefined)), SESSION_DEAD);
    assert.equal(classifyRefreshError(axiosErr(401, '')), SESSION_DEAD);
    assert.equal(classifyRefreshError(axiosErr(401, 'Unauthorized')), SESSION_DEAD);
    assert.equal(classifyRefreshError(axiosErr(401, { detail: null })), SESSION_DEAD);
});

test('the marker only counts on a 401', () => {
    assert.equal(classifyRefreshError(axiosErr(403, { detail: 'auth_expired' })), TRANSIENT);
});

test('an error with no response at all is transient', () => {
    // Client-side timeout / network drop / sidecar gone: the stored login is intact.
    assert.equal(classifyRefreshError(new Error('timeout of 20000ms exceeded')), TRANSIENT);
    assert.equal(classifyRefreshError({ code: 'ECONNABORTED', message: 'aborted' }), TRANSIENT);
});

test('503 and 429 are transient', () => {
    assert.equal(
        classifyRefreshError(axiosErr(503, { detail: 'SoundCloud unreachable' })),
        TRANSIENT
    );
    assert.equal(classifyRefreshError(axiosErr(429, { detail: 'Rate limited' })), TRANSIENT);
});

test('a rejection that is not an object at all is transient', () => {
    // `invoke()` rejects with a bare string; nothing here may throw on it.
    assert.equal(classifyRefreshError('boom'), TRANSIENT);
    assert.equal(classifyRefreshError(null), TRANSIENT);
    assert.equal(classifyRefreshError(undefined), TRANSIENT);
});
