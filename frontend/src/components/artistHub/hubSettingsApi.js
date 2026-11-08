import api from '../../api/api';

/**
 * The settings the hub exposes in its own gear popover and status card.
 * Same keys as Settings → Analysis / Network — one store, two entry points.
 */
export const HUB_SETTING_DEFAULTS = {
    artist_view_threshold: 0,
    artist_background_sync: false,
    sc_download_format: 'auto',
};

export const pickHubSettings = (all) => {
    const out = { ...HUB_SETTING_DEFAULTS };
    for (const key of Object.keys(HUB_SETTING_DEFAULTS)) {
        if (all && all[key] !== undefined && all[key] !== null) out[key] = all[key];
    }
    return out;
};

export const fetchHubSettings = async () => {
    const res = await api.get('/api/settings');
    return pickHubSettings(res.data);
};

/**
 * POST /api/settings replaces the whole settings file, so a partial body would
 * reset every other key. Read the stored file first and write it back merged;
 * a failed read throws before anything is written.
 */
export const saveHubSettings = async (patch) => {
    const res = await api.get('/api/settings');
    const current = res?.data;
    if (!current || typeof current !== 'object') {
        throw new Error('Settings could not be read — nothing was saved.');
    }
    await api.post('/api/settings', { ...current, ...patch });
    return pickHubSettings({ ...current, ...patch });
};
