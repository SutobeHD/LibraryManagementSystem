/**
 * Worker-thread implementation of the ESM resolver hook used by
 * `dawReducer.test.js`. Co-loaded by `dawReducer.test.resolver.mjs`
 * via `module.register(...)`. The hook intercepts relative,
 * extensionless specifiers (Vite-style) that Node would otherwise
 * reject with ERR_MODULE_NOT_FOUND and retries them with `.js`
 * appended. No-op for everything else.
 */
import { existsSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { dirname, resolve as resolvePath, extname } from 'node:path';

export async function resolve(specifier, context, nextResolve) {
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
