import axios from 'axios';

// Detect if we are running in Tauri
const isTauri = !!(window.__TAURI_INTERNALS__ || window.__TAURI_METADATA__ || window.__TAURI__);

const API_BASE_URL = isTauri
    ? 'http://127.0.0.1:8000'
    : ''; // Use proxy (empty string) in browser-preview mode

const api = axios.create({
    baseURL: API_BASE_URL,
    timeout: 30000, // 30s default timeout for stability
    withCredentials: true, // Send HttpOnly cookies
});

// --- SECURITY: Session token management ---
// The backend generates a unique token per session, returned via the heartbeat endpoint.
// This token is required for sensitive operations (shutdown, restart).
let _sessionToken = '';

export function setSessionToken(token) {
    _sessionToken = token;
}

export function getSessionToken() {
    return _sessionToken;
}

// --- STABILITY: AbortController factory ---
// Create cancellable requests to prevent memory leaks on component unmount.
export function createCancelToken() {
    const controller = new AbortController();
    return {
        signal: controller.signal,
        cancel: () => controller.abort(),
    };
}

// Helper to make a cancellable GET request
export function cancellableGet(url, config = {}) {
    const controller = new AbortController();
    const promise = api.get(url, { ...config, signal: controller.signal });
    return { promise, cancel: () => controller.abort() };
}

// Helper to make a cancellable POST request
export function cancellablePost(url, data, config = {}) {
    const controller = new AbortController();
    const promise = api.post(url, data, { ...config, signal: controller.signal });
    return { promise, cancel: () => controller.abort() };
}

export default api;
export { API_BASE_URL };
