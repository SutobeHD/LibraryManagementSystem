/**
 * node --import ./frontend/src/components/artistHub/useArtistCatalogue.test.resolver.mjs \
 *      --test frontend/src/components/artistHub/useArtistCatalogue.test.js
 *
 * Lifecycle of one batch download. The load-bearing case is the regression that shipped:
 * `download()` guarded its `downloading`/`job` reset with `load`'s fetch counter, which
 * every catalogue re-read bumps — so a finished run, or an Update pressed mid-run, left
 * the panel disabled with the progress bar pinned and the result summary never rendered.
 * The guard is now the generation counter, which only an artist switch or unmount bumps;
 * the reset still refuses to touch a newer artist's state, or a later run's.
 *
 * Driven by a fake hooks runtime, not by React — see `useArtistCatalogue.test.fake-react.mjs`.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import useArtistCatalogue from './useArtistCatalogue.js';
import { calls, resetStub, stub } from './useArtistCatalogue.test.api-stub.mjs';
import { renderHook, settle } from './useArtistCatalogue.test.fake-react.mjs';

const CATALOGUE = { status: 'ok', their_tracks: [], their_remixes: [] };
const FINISHED = { status: 'done', total: 2, downloaded: 2, failed: 0 };

// Named + `use`-prefixed so eslint's rules-of-hooks sees a custom hook, not a callback.
const useCatalogueUnderTest = (props) => useArtistCatalogue(props);

const mount = async (collectionId = 7) => {
    const hook = renderHook(useCatalogueUnderTest, { collectionId });
    await settle();
    return hook;
};

test.beforeEach(() => {
    resetStub();
    stub.fetchCatalogue = async () => CATALOGUE;
    stub.startMissingDownload = async () => ({ job_id: 'job-7', total: 2 });
    stub.pollDownloadJob = async () => FINISHED;
});

test('a finished run clears downloading + job and keeps the result', async () => {
    stub.pollDownloadJob = async (_jobId, { onProgress }) => {
        onProgress?.({ status: 'running', total: 2, done: 1, percent: 50 });
        return FINISHED;
    };
    const hook = await mount();
    assert.deepEqual(hook.current.view, CATALOGUE);

    const finished = await hook.current.download({ autoQueue: true });

    assert.deepEqual(finished, FINISHED);
    assert.equal(hook.current.downloading, false, 'panel would stay disabled forever');
    assert.equal(hook.current.job, null, 'progress bar would stay pinned');
    assert.deepEqual(hook.current.result, FINISHED, 'result summary never renders otherwise');
    assert.equal(calls.fetchCatalogue, 2, 'catalogue re-read after the run');
    hook.unmount();
});

test('a failed start resets the panel and rethrows for the caller toast', async () => {
    stub.startMissingDownload = async () => {
        throw new Error('download could not be started');
    };
    const hook = await mount();

    await assert.rejects(hook.current.download({ autoQueue: true }), /could not be started/);

    assert.equal(hook.current.downloading, false);
    assert.equal(hook.current.job, null);
    assert.equal(hook.current.result, null);
    hook.unmount();
});

test('pressing Update mid-run neither cancels the run nor pins the panel', async () => {
    let release;
    const gate = new Promise((resolve) => {
        release = resolve;
    });
    stub.pollDownloadJob = async (_jobId, { isCancelled, onProgress }) => {
        onProgress?.({ status: 'running', total: 2, done: 1, percent: 50 });
        await gate;
        return isCancelled?.() ? null : FINISHED;
    };
    const hook = await mount();

    const running = hook.current.download({ autoQueue: true });
    await settle();
    assert.equal(hook.current.downloading, true);

    // The Update button is clickable during a run (ArtistDetail's `updateBlocked`
    // has no `downloading` term), and a plain re-read is not a cancellation.
    await hook.current.reload({ refresh: true });
    await settle();

    release();
    assert.deepEqual(await running, FINISHED, 'a re-read must not cancel the run');
    await settle();
    assert.equal(hook.current.downloading, false, 'panel would stay disabled forever');
    assert.equal(hook.current.job, null, 'progress bar would stay pinned');
    assert.deepEqual(hook.current.result, FINISHED);
    hook.unmount();
});

test('the panel stays busy until the closing catalogue re-read lands', async () => {
    let releaseRead;
    const readGate = new Promise((resolve) => {
        releaseRead = resolve;
    });
    // Only the closing re-read is held open; the mount read passes through.
    stub.fetchCatalogue = async () => {
        if (calls.fetchCatalogue === 2) await readGate;
        return CATALOGUE;
    };
    const hook = await mount();

    const running = hook.current.download({ autoQueue: true });
    await settle();
    assert.equal(
        hook.current.downloading,
        true,
        'unlocking here re-enables Download-all against the pre-run split'
    );

    releaseRead();
    assert.deepEqual(await running, FINISHED);
    await settle();
    assert.equal(hook.current.downloading, false);
    assert.equal(hook.current.job, null);
    assert.equal(calls.fetchCatalogue, 2);
    hook.unmount();
});

test('a run still in flight survives the previous run finishing its re-read', async () => {
    let releaseRead;
    const readGate = new Promise((resolve) => {
        releaseRead = resolve;
    });
    // Only the first run's post-run re-read is held open; the mount read and the
    // second run's own re-read pass through.
    stub.fetchCatalogue = async () => {
        if (calls.fetchCatalogue === 2) await readGate;
        return CATALOGUE;
    };
    let releasePoll;
    const pollGate = new Promise((resolve) => {
        releasePoll = resolve;
    });
    stub.pollDownloadJob = async () => {
        if (calls.pollDownloadJob > 1) await pollGate;
        return FINISHED;
    };
    const hook = await mount();

    const first = hook.current.download({ autoQueue: true });
    await settle();
    const second = hook.current.download({ autoQueue: true });
    await settle();
    assert.equal(hook.current.downloading, true);

    releaseRead();
    await first;
    await settle();
    assert.equal(hook.current.downloading, true, 'the second run is still running');
    assert.notEqual(hook.current.job, null, 'its progress bar must not be cleared');

    releasePoll();
    await second;
    await settle();
    assert.equal(hook.current.downloading, false);
    assert.equal(hook.current.job, null);
    hook.unmount();
});

test('switching artist mid-run never writes the stale run into the new artist', async () => {
    let release;
    const gate = new Promise((resolve) => {
        release = resolve;
    });
    stub.pollDownloadJob = async (_jobId, { isCancelled }) => {
        await gate;
        return isCancelled?.() ? null : FINISHED;
    };
    const hook = await mount(7);

    const running = hook.current.download({ autoQueue: true });
    await settle();
    assert.equal(hook.current.downloading, true);

    hook.rerender({ collectionId: 8 });
    await settle();
    assert.equal(hook.current.downloading, false, 'the new artist starts clean');

    release();
    assert.equal(await running, null, 'a run nobody watches reports nothing');
    await settle();
    assert.equal(hook.current.downloading, false);
    assert.equal(hook.current.job, null);
    assert.equal(hook.current.result, null, 'the stale run must not fill the new panel');
    hook.unmount();
});
