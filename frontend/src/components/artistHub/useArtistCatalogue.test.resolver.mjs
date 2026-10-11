/**
 * ESM resolver hook for `useArtistCatalogue.test.js`. Registered via Node's
 * `--import` flag on the test command; the mapping itself lives in
 * `useArtistCatalogue.test.resolver-impl.mjs`.
 */
import { register } from 'node:module';

register(new URL('./useArtistCatalogue.test.resolver-impl.mjs', import.meta.url));
