import axios from 'axios';

// Detect if we are running in Tauri
const isTauri = !!(window.__TAURI_INTERNALS__ || window.__TAURI_METADATA__ || window.__TAURI__);

const API_BASE_URL = isTauri
    ? 'http://127.0.0.1:8000'
    : ''; // Use proxy (empty string) in browser-preview mode

const api = axios.create({
    baseURL: API_BASE_URL
});

export default api;
export { API_BASE_URL };
