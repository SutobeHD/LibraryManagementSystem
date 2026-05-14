import { useEffect, useSyncExternalStore } from 'react';
import api from '../api/api';

/**
 * Shared module-level cache for the full library track list.
 *
 * Before this, every view (PlaylistBrowser, EditorBrowser, ...) fetched
 * GET /api/library/tracks into its own state. On a 100k-track library
 * that meant N independent fetches and N full in-memory copies, all
 * resident at once because the tabs stay mounted. Now the first hook
 * consumer triggers one fetch; the rest read the shared snapshot.
 */

let snapshot = { tracks: [], loading: false, error: null, loaded: false };
let inFlight = null;
const listeners = new Set();

function setSnapshot(patch) {
  snapshot = { ...snapshot, ...patch };
  listeners.forEach((l) => l());
}

function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function getSnapshot() {
  return snapshot;
}

/**
 * Fetch (or refetch with force=true) the library track list into the
 * shared cache. Concurrent calls dedupe onto the one in-flight request.
 */
export function loadLibraryTracks(force = false) {
  if (snapshot.loaded && !force) return Promise.resolve(snapshot.tracks);
  if (inFlight) return inFlight;

  setSnapshot({ loading: true, error: null });
  inFlight = api
    .get('/api/library/tracks')
    .then((res) => {
      const tracks = Array.isArray(res.data) ? res.data : [];
      setSnapshot({ tracks, loading: false, error: null, loaded: true });
      return tracks;
    })
    .catch((err) => {
      setSnapshot({ loading: false, error: err });
      throw err;
    })
    .finally(() => {
      inFlight = null;
    });
  return inFlight;
}

/**
 * Read the shared library track list. The first consumer to mount kicks
 * off the fetch; later consumers get the cached array and the same
 * loading/error state. `reload()` forces a refetch (use after writes).
 */
export function useLibraryTracks() {
  const snap = useSyncExternalStore(subscribe, getSnapshot);

  useEffect(() => {
    if (!snap.loaded && !inFlight) {
      loadLibraryTracks().catch(() => {
        // error is captured in the shared snapshot
      });
    }
  }, [snap.loaded]);

  return {
    tracks: snap.tracks,
    loading: snap.loading,
    error: snap.error,
    loaded: snap.loaded,
    reload: () => loadLibraryTracks(true),
  };
}
