/**
 * ESM resolver hook for `dawReducer.test.js`.
 *
 * Vite-style imports under frontend/ omit the `.js` extension; raw
 * Node.js is strict and refuses to guess. This hook retries failed
 * resolutions with `.js` appended so the production sub-reducer
 * modules can be loaded unchanged by the test file. Registered via
 * Node's `--import` flag on the test command.
 */
import { register } from 'node:module';

register(new URL('./dawReducer.test.resolver-impl.mjs', import.meta.url));
