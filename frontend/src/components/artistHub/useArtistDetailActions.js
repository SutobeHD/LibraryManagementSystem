import { useCallback, useState } from 'react';
import { toast } from 'react-hot-toast';

import { confirmModal } from '../ConfirmModal';
import { promptModal } from '../PromptModal';
import { catalogueErrorMessage } from './artistCatalogueApi';
import {
    ROLE_LABEL,
    downloadAllNote,
    downloadSummary,
    downloadTone,
    splitCatalogue,
} from './catalogueCopy';

/**
 * useArtistDetailActions — the click handlers of the artist detail view.
 *
 * Split out of the components because the header (chip, Update, Download all) and
 * the panel body (per-track Download, the empty-state Link button) trigger the same
 * five actions from two different places in the tree.
 *
 * The honesty rules live here, not in the components:
 *  - a finished download reports downloaded / skipped / failed, and a run with a
 *    failure never gets a success toast;
 *  - a refresh reports the numbers it actually received;
 *  - every failure renders the backend's own sentence (`detail`), and the literal
 *    `auth_expired` is translated before it can reach a toast.
 */
const useArtistDetailActions = ({ artist, catalogue, onLinkChanged }) => {
    const [pendingScId, setPendingScId] = useState(null);

    // `link.permalink` on an ok/bound read, top-level `permalink` on the broken-link
    // states, and the hub row's own value before the first read comes back.
    const permalink =
        catalogue.view?.link?.permalink || catalogue.view?.permalink || artist?.sc_permalink || '';

    const handleLink = useCallback(async () => {
        const value = await promptModal({
            title: `Link ${artist?.name} to SoundCloud`,
            message:
                'Paste the artist\'s SoundCloud profile URL (or just their permalink, e.g. "boysnoize").\n' +
                'The binding is stored against this artist, not against the spelling, so a merge cannot break it.',
            defaultValue: permalink,
            placeholder: 'https://soundcloud.com/boysnoize',
            confirmLabel: 'Link profile',
        });
        const trimmed = String(value ?? '').trim();
        if (!trimmed) return;
        try {
            const account = await catalogue.link(trimmed);
            toast.success(
                account?.username
                    ? `Linked to ${account.username} on SoundCloud`
                    : 'SoundCloud profile linked'
            );
            onLinkChanged?.();
        } catch (e) {
            console.error('[ArtistHub] linking the SoundCloud profile failed', e);
            toast.error(catalogueErrorMessage(e, 'Could not link that SoundCloud profile.'));
        }
    }, [artist?.name, catalogue, onLinkChanged, permalink]);

    const handleUnlink = useCallback(async () => {
        const ok = await confirmModal({
            title: 'Unlink the SoundCloud profile?',
            message: `Unbind "${artist?.name}" from ${
                permalink || 'their SoundCloud account'
            }. Your tracks, favourites and merges stay untouched — only the catalogue link goes.`,
            confirmLabel: 'Unlink',
        });
        if (!ok) return;
        try {
            await catalogue.unlink();
            toast.success('SoundCloud profile unlinked');
            onLinkChanged?.();
        } catch (e) {
            console.error('[ArtistHub] unlinking failed', e);
            toast.error(catalogueErrorMessage(e, 'Could not unlink that profile.'));
        }
    }, [artist?.name, catalogue, onLinkChanged, permalink]);

    /** The per-artist Update button: force past the TTL cache. */
    const handleUpdate = useCallback(async () => {
        const payload = await catalogue.reload({ refresh: true });
        if (!payload) return;
        if (payload.status !== 'ok') {
            // Typed state — the panel renders the sentence; the toast only makes it
            // impossible to miss that the click did not produce a catalogue.
            toast.error(payload.detail || 'SoundCloud did not return a catalogue.');
            return;
        }
        const split = splitCatalogue(payload);
        toast.success(
            `${split.total} tracks read · ${split.queueable.length} missing and ready to queue`
        );
    }, [catalogue]);

    /**
     * Pin a row's role by hand — the manual half of identification.
     *
     * The row moves immediately and rolls back with a toast if the sidecar refused the
     * pin. Clearing a pin cannot be predicted client-side (only the classifier knows
     * where the row belongs), so that path re-reads instead of guessing.
     */
    const handlePinRole = useCallback(
        async (track, role) => {
            if (!track?.sc_id) return;
            try {
                await catalogue.pinRole(track.sc_id, role);
                if (role === null) {
                    await catalogue.reload();
                    toast.success(`Pin cleared — "${track.title}" is back with the classifier`);
                } else {
                    toast.success(`"${track.title}" pinned as ${ROLE_LABEL[role] || role}`);
                }
            } catch (e) {
                console.error('[ArtistHub] pinning the role failed', e);
                toast.error(
                    catalogueErrorMessage(
                        e,
                        'Could not pin that role — the row is back where it was.'
                    )
                );
            }
        },
        [catalogue]
    );

    const reportRun = useCallback((job) => {
        if (!job) return;
        const line = downloadSummary(job);
        const tone = downloadTone(job);
        if (tone === 'error') toast.error(line);
        else if (tone === 'success') toast.success(line);
        else toast(line);
    }, []);

    const runDownload = useCallback(
        async (payload, scId) => {
            setPendingScId(scId);
            try {
                const job = await catalogue.download(payload);
                reportRun(job);
            } catch (e) {
                console.error('[ArtistHub] batch download failed', e);
                toast.error(catalogueErrorMessage(e, 'The download could not be started.'));
            } finally {
                setPendingScId(null);
            }
        },
        [catalogue, reportRun]
    );

    /** "Download all missing" — server-side selection, `auto_queue_allowed` only. */
    const handleDownloadAll = useCallback(
        async (count) => {
            const ok = await confirmModal({
                title: 'Download the missing tracks?',
                message:
                    `${downloadAllNote(count)}\n\n` +
                    'They download one at a time through the normal SoundCloud downloader — ' +
                    'analysis, auto-import and the ANLZ write run exactly as for a single track.',
                confirmLabel: `Download ${count}`,
            });
            if (!ok) return;
            await runDownload({ autoQueue: true }, null);
        },
        [runDownload]
    );

    /** One row's Download button — any bucket, because the user pointed at it. */
    const handleDownloadOne = useCallback(
        async (track) => {
            if (!track?.sc_id) return;
            await runDownload({ scIds: [track.sc_id] }, track.sc_id);
        },
        [runDownload]
    );

    return {
        pendingScId,
        handleLink,
        handleUnlink,
        handleUpdate,
        handleDownloadAll,
        handleDownloadOne,
        handlePinRole,
    };
};

export default useArtistDetailActions;
