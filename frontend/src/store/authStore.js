// Tiny module-level auth state shared across the frontend.
//
// Phase 1 of the API auth-hardening (see
// docs/research/implement/draftplan_security-api-auth-hardening.md):
// the sidecar self-generates a session token at boot. The Tauri Rust
// supervisor captures it from stdout and exposes it to the frontend
// via the ``get_session_token`` IPC; the browser-dev path reads it
// from ``GET /dev-token`` (served by the vite dev-middleware). Either
// way the value lands in ``_sessionToken`` and is attached as
// ``Authorization: Bearer ${token}`` on every axios request.
//
// If both bootstrap paths fail (corrupted file, IPC unregistered,
// fresh dev clone with no sidecar running yet) ``_authBootstrapFailed``
// flips true so mutation UI can disable itself before the user fires
// a write that will only 401 anyway. Read-only views stay functional.

let _sessionToken = '';
let _authBootstrapFailed = false;
let _bootstrapPromise = null;

export function setSessionToken(token) {
    _sessionToken = token || '';
}

export function getSessionToken() {
    return _sessionToken;
}

export function setBootstrapFailed(flag) {
    _authBootstrapFailed = !!flag;
}

export function isAuthBootstrapFailed() {
    return _authBootstrapFailed;
}

// Stash the bootstrap promise from ``api.js`` so anything that wants to
// await the initial token-fetch (e.g. a top-level "wait until backend
// + auth ready" effect in ``main.jsx``) can do so without re-running
// the IPC handshake.
export function setBootstrapPromise(promise) {
    _bootstrapPromise = promise;
}

export function getBootstrapPromise() {
    return _bootstrapPromise;
}
