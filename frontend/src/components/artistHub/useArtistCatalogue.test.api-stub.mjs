/**
 * Stand-in for `artistCatalogueApi` in `useArtistCatalogue.test.js`.
 *
 * The real module imports the axios instance (and through it Vite's `import.meta.env`),
 * which raw Node cannot load. Every export delegates to `stub`, so a test rewires one
 * call without touching the hook. `calls` records what the hook asked for — the
 * post-download catalogue re-read is asserted through it.
 */

export const stub = {
    fetchCatalogue: async () => ({ status: 'ok' }),
    startMissingDownload: async () => ({ job_id: 'job-1', total: 0 }),
    pollDownloadJob: async () => ({ status: 'done', total: 0, downloaded: 0, failed: 0 }),
    linkSoundCloudProfile: async () => ({ artist: null }),
    unlinkSoundCloudProfile: async () => ({ removed: true }),
    pinTrackRole: async () => ({ status: 'ok' }),
};

export const calls = { fetchCatalogue: 0, startMissingDownload: 0, pollDownloadJob: 0 };

export const resetStub = () => {
    for (const key of Object.keys(calls)) calls[key] = 0;
};

export const fetchCatalogue = (...args) => {
    calls.fetchCatalogue += 1;
    return stub.fetchCatalogue(...args);
};

export const startMissingDownload = (...args) => {
    calls.startMissingDownload += 1;
    return stub.startMissingDownload(...args);
};

export const pollDownloadJob = (...args) => {
    calls.pollDownloadJob += 1;
    return stub.pollDownloadJob(...args);
};

export const linkSoundCloudProfile = (...args) => stub.linkSoundCloudProfile(...args);
export const unlinkSoundCloudProfile = (...args) => stub.unlinkSoundCloudProfile(...args);
export const pinTrackRole = (...args) => stub.pinTrackRole(...args);

export const catalogueErrorMessage = (error, fallback) => error?.message || fallback;
export const isUnknownCollection = () => false;
