/**
 * Minimal hooks runtime standing in for `react` in `useArtistCatalogue.test.js`.
 *
 * The repo has no React test harness (no jsdom, no react-test-renderer, no
 * testing-library) and adding one is a dependency decision. This file implements
 * only the four hooks `useArtistCatalogue` uses, plus a driver that re-renders on
 * every state write and flushes effects after each pass — enough to exercise a
 * hook's async lifecycle from plain `node --test`.
 *
 * Deliberately NOT React: renders are synchronous and unbatched. That makes the
 * state after an awaited call exactly the state the last setter wrote, which is
 * what the assertions read. It is not a substitute for rendering the real panel.
 */

const MAX_RENDER_PASSES = 50;
const MAX_SETTLE_TICKS = 50;
const QUIET_TICKS = 2;

let active = null;
let renders = 0;

const slot = (make) => {
    const instance = active;
    const index = instance.index++;
    if (instance.hooks.length <= index) instance.hooks[index] = make();
    return instance.hooks[index];
};

const sameDeps = (a, b) =>
    Array.isArray(a) &&
    Array.isArray(b) &&
    a.length === b.length &&
    a.every((v, i) => Object.is(v, b[i]));

export const useState = (initial) => {
    const instance = active;
    const hook = slot(() => ({ value: typeof initial === 'function' ? initial() : initial }));
    const set = (next) => {
        const value = typeof next === 'function' ? next(hook.value) : next;
        if (Object.is(value, hook.value)) return;
        hook.value = value;
        instance.render();
    };
    return [hook.value, set];
};

export const useRef = (initial) => slot(() => ({ current: initial }));

export const useMemo = (factory, deps) => {
    const hook = slot(() => ({ value: factory(), deps }));
    if (!sameDeps(hook.deps, deps)) {
        hook.value = factory();
        hook.deps = deps;
    }
    return hook.value;
};

export const useCallback = (fn, deps) => {
    const hook = slot(() => ({ fn, deps }));
    if (!sameDeps(hook.deps, deps)) {
        hook.fn = fn;
        hook.deps = deps;
    }
    return hook.fn;
};

export const useEffect = (fn, deps) => {
    const instance = active;
    const hook = slot(() => ({ deps: null, cleanup: undefined, ran: false }));
    if (!hook.ran || !sameDeps(hook.deps, deps)) {
        hook.deps = deps;
        hook.ran = true;
        instance.queue.push({ hook, fn });
    }
};

export const useLayoutEffect = useEffect;

const runEffects = (instance) => {
    const queued = instance.queue;
    instance.queue = [];
    for (const { hook, fn } of queued) {
        if (typeof hook.cleanup === 'function') hook.cleanup();
        const cleanup = fn();
        hook.cleanup = typeof cleanup === 'function' ? cleanup : undefined;
    }
};

const renderInstance = (instance) => {
    // A setter fired from a render or an effect must not re-enter the pass it is
    // already inside — mark it dirty and let the loop below pick it up instead.
    if (instance.rendering) {
        instance.dirty = true;
        return;
    }
    instance.rendering = true;
    try {
        let passes = 0;
        do {
            instance.dirty = false;
            active = instance;
            instance.index = 0;
            try {
                instance.value = instance.fn(instance.props);
            } finally {
                active = null;
            }
            runEffects(instance);
            passes += 1;
            renders += 1;
        } while (instance.dirty && passes < MAX_RENDER_PASSES);
        if (instance.dirty) throw new Error('fake-react: render did not settle');
    } finally {
        instance.rendering = false;
    }
};

/** Mount `fn(props)` and keep re-running it. `result.current` is its latest return. */
export const renderHook = (fn, props) => {
    const instance = {
        fn,
        props,
        hooks: [],
        index: 0,
        queue: [],
        dirty: false,
        rendering: false,
        value: undefined,
    };
    instance.render = () => renderInstance(instance);
    instance.render();
    return {
        get current() {
            return instance.value;
        },
        rerender: (next) => {
            if (next !== undefined) instance.props = next;
            instance.render();
        },
        unmount: () => {
            for (const hook of instance.hooks) {
                if (typeof hook?.cleanup === 'function') hook.cleanup();
            }
        },
    };
};

/**
 * Let queued timers and microtasks (the hook's own awaits) drain, until the hook
 * has stopped re-rendering.
 *
 * Condition-based on purpose: a fixed tick count asserts against half-settled
 * state the moment a stub chain grows one await longer, and passes or fails on
 * timing rather than on behaviour. A parked promise counts as settled — it
 * renders nothing — so only a hook that never stops rendering hits the throw.
 */
export const settle = async (maxTicks = MAX_SETTLE_TICKS) => {
    let quiet = 0;
    for (let i = 0; i < maxTicks; i += 1) {
        const before = renders;
        await new Promise((resolve) => {
            setTimeout(resolve, 0);
        });
        if (renders !== before) {
            quiet = 0;
            continue;
        }
        quiet += 1;
        if (quiet >= QUIET_TICKS) return;
    }
    throw new Error(`fake-react: settle() still re-rendering after ${maxTicks} ticks`);
};
