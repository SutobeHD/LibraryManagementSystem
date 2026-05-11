import { log } from '../../utils/log';

// localStorage auto-save (cuts + cues, keyed by track.id)
const STORAGE_KEY_PREFIX = 'rb-editor:edits:';
const STORAGE_VERSION = 1;

export const loadEditsForTrack = (trackId) => {
    if (!trackId) return null;
    try {
        const raw = localStorage.getItem(STORAGE_KEY_PREFIX + trackId);
        if (!raw) return null;
        const parsed = JSON.parse(raw);
        if (parsed.version !== STORAGE_VERSION) return null;
        return parsed;
    } catch (e) { return null; }
};

export const saveEditsForTrack = (trackId, data) => {
    if (!trackId) return;
    try {
        localStorage.setItem(STORAGE_KEY_PREFIX + trackId, JSON.stringify({ version: STORAGE_VERSION, ...data, savedAt: Date.now() }));
    } catch (e) { /* quota or disabled */ }
};

export const clearEditsForTrack = (trackId) => {
    if (!trackId) return;
    try { localStorage.removeItem(STORAGE_KEY_PREFIX + trackId); } catch (e) { log.debug('WaveformEditor clearEditsForTrack failed', e); }
};
