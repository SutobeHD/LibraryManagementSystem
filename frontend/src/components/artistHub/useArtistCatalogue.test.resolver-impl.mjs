/**
 * Worker-thread ESM hooks for `useArtistCatalogue.test.js`. Co-loaded by
 * `useArtistCatalogue.test.resolver.mjs` via `module.register(...)`.
 *
 * Two jobs: point `react` at the fake hooks runtime and `artistCatalogueApi` at the
 * stub (the real one pulls in axios + `import.meta.env`), and retry Vite-style
 * extensionless relative specifiers with `.js` the way the dawReducer resolver does.
 * No-op for everything else.
 */
import { existsSync } from 'node:fs';
import { dirname, extname, resolve as resolvePath } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const FAKE_REACT = new URL('./useArtistCatalogue.test.fake-react.mjs', import.meta.url).href;
const API_STUB = new URL('./useArtistCatalogue.test.api-stub.mjs', import.meta.url).href;

export async function resolve(specifier, context, nextResolve) {
    if (specifier === 'react') return { url: FAKE_REACT, format: 'module', shortCircuit: true };
    if (
        specifier.startsWith('.') &&
        specifier.replace(/\.js$/, '').endsWith('/artistCatalogueApi')
    ) {
        return { url: API_STUB, format: 'module', shortCircuit: true };
    }
    try {
        return await nextResolve(specifier, context);
    } catch (err) {
        if (
            err?.code === 'ERR_MODULE_NOT_FOUND' &&
            specifier.startsWith('.') &&
            !extname(specifier) &&
            context?.parentURL
        ) {
            const parent = fileURLToPath(context.parentURL);
            const guess = resolvePath(dirname(parent), specifier + '.js');
            if (existsSync(guess)) {
                return nextResolve(pathToFileURL(guess).href, context);
            }
        }
        throw err;
    }
}
