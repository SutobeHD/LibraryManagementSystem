import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'react-hot-toast';
import {
    AtSign,
    Check,
    Cloud,
    Disc3,
    Facebook,
    Globe,
    Instagram,
    Link2,
    Loader2,
    Music,
    Plus,
    Radio,
    RefreshCw,
    Search,
    ShoppingBag,
    Ticket,
    Twitch,
    Twitter,
    X,
    Youtube,
} from 'lucide-react';

import { confirmModal } from '../ConfirmModal';
import { promptModal } from '../PromptModal';
import { openExternal } from '../../utils/openExternal';
import {
    addLink,
    confirmMusicBrainz,
    dropMusicBrainz,
    fetchLinks,
    fetchSoundCloudCandidates,
    linksErrorMessage,
    refreshLinks,
    removeLink,
    restoreLinks,
} from './artistLinksApi';
import {
    emptyLinksNote,
    groupLinks,
    hiddenLine,
    isTentative,
    lastFetchedLine,
    linkLabel,
    linkTitle,
    musicBrainzCandidateLine,
    soundCloudCandidateLine,
    sourceLines,
} from './linksCopy';

/**
 * ArtistLinks — where the artist lives online (owner refinement 2026-09-26).
 *
 * One strip above the artist detail: every stored profile as a chip that opens in the
 * system browser, "Find links" (their SoundCloud profile + MusicBrainz, user-initiated
 * only), manual add, hide, restore — plus two pickers that never decide on their own:
 * which MusicBrainz entry is them, and which SoundCloud account is theirs.
 *
 * Chips are buttons, not `<a target="_blank">`: the Tauri shell plugin also hooks every
 * `_blank` anchor, and handling both would open the page twice.
 */

const SERVICE_ICON = {
    soundcloud: Cloud,
    instagram: Instagram,
    tiktok: AtSign,
    x: Twitter,
    facebook: Facebook,
    youtube: Youtube,
    threads: AtSign,
    twitch: Twitch,
    spotify: Music,
    apple_music: Music,
    deezer: Music,
    tidal: Music,
    mixcloud: Radio,
    bandcamp: ShoppingBag,
    beatport: ShoppingBag,
    traxsource: ShoppingBag,
    resident_advisor: Ticket,
    discogs: Disc3,
    songkick: Ticket,
    bandsintown: Ticket,
    linktree: Link2,
    website: Globe,
};

const MAX_ACCOUNT_SUGGESTIONS = 5;

const StripButton = ({ onClick, disabled, busy, icon: Icon, title, tone, children }) => (
    <button
        type="button"
        onClick={onClick}
        disabled={disabled || busy}
        title={title}
        className={`flex items-center gap-1.5 px-2.5 py-1 rounded-mx-sm text-[11px] border transition-colors disabled:opacity-40 disabled:cursor-not-allowed shrink-0 ${
            tone === 'primary'
                ? 'bg-amber2/10 border-amber2/40 text-amber2 hover:bg-amber2/20'
                : 'bg-mx-card border-line-subtle text-ink-primary hover:border-amber2/50 hover:text-amber2'
        }`}
    >
        {busy ? <Loader2 size={12} className="animate-spin" /> : Icon && <Icon size={12} />}
        {children}
    </button>
);

const LinkChip = ({ link, onOpen, onRemove, busy }) => {
    const Icon = SERVICE_ICON[link.service] || Globe;
    const tentative = isTentative(link);
    return (
        <span
            className={`group inline-flex items-center gap-0.5 rounded-mx-xs border text-[11px] ${
                tentative
                    ? 'border-dashed border-line-subtle text-ink-muted'
                    : 'border-line-subtle bg-mx-card text-ink-secondary'
            }`}
        >
            <button
                type="button"
                onClick={() => onOpen(link)}
                title={linkTitle(link)}
                className="inline-flex items-center gap-1.5 pl-2 py-[3px] hover:text-amber2 transition-colors"
            >
                <Icon size={12} className="shrink-0" />
                <span className="truncate max-w-[180px]">{linkLabel(link)}</span>
                {tentative && <span className="text-amber2/80">?</span>}
            </button>
            <button
                type="button"
                onClick={() => onRemove(link)}
                disabled={busy}
                title={
                    link.source === 'manual'
                        ? 'Remove this link'
                        : 'Hide this link — "Find links" will not bring it back'
                }
                className="px-1 py-[3px] opacity-0 group-hover:opacity-100 focus:opacity-100 text-ink-muted hover:text-bad transition-opacity"
            >
                <X size={11} />
            </button>
        </span>
    );
};

const ArtistLinks = ({
    artist,
    enabled,
    disabledReason,
    catalogue,
    onLinkAccount,
    refreshToken = 0,
}) => {
    const collectionId = artist?.collection_id;
    const [data, setData] = useState(null);
    const [sources, setSources] = useState(null);
    const [mbCandidates, setMbCandidates] = useState([]);
    const [scCandidates, setScCandidates] = useState(null);
    const [busy, setBusy] = useState('');
    const seqRef = useRef(0);

    const view = catalogue?.view;
    const scLinked = view ? view.link_state === 'linked' : !!artist?.sc_linked;

    const load = useCallback(async () => {
        if (!collectionId || !enabled) return;
        const seq = (seqRef.current += 1);
        try {
            const payload = await fetchLinks(collectionId);
            if (seqRef.current === seq) setData(payload);
        } catch (e) {
            if (seqRef.current !== seq) return;
            console.error('[ArtistLinks] loading links failed', e);
            setData(null);
        }
    }, [collectionId, enabled]);

    useEffect(() => {
        setData(null);
        setSources(null);
        setMbCandidates([]);
        setScCandidates(null);
        load();
    }, [load]);

    const refresh = useCallback(
        async ({ quiet = false } = {}) => {
            if (!collectionId) return;
            const seq = (seqRef.current += 1);
            setBusy('refresh');
            try {
                const payload = await refreshLinks(collectionId);
                if (seqRef.current !== seq) return;
                setData(payload);
                setSources(payload?.sources ?? null);
                setMbCandidates(payload?.musicbrainz_candidates ?? []);
                if (!quiet) {
                    const n = payload?.links?.length ?? 0;
                    const added = payload?.changes?.added ?? 0;
                    toast.success(
                        added > 0
                            ? `Found ${added} new link${added === 1 ? '' : 's'}`
                            : `${n} link${n === 1 ? '' : 's'} — nothing new`
                    );
                }
            } catch (e) {
                console.error('[ArtistLinks] refresh failed', e);
                toast.error(linksErrorMessage(e, 'Could not look for links.'));
            } finally {
                if (seqRef.current === seq) setBusy('');
            }
        },
        [collectionId]
    );

    // The parent bumps `refreshToken` after the user links, re-links or unlinks their
    // SoundCloud account — the moment that account's links become readable (or stop
    // being theirs). Refresh once, quietly. Mounting, or opening another artist, only
    // remembers the value: reading a profile must stay a user action.
    const tokenRef = useRef({ collectionId, refreshToken });
    useEffect(() => {
        const previous = tokenRef.current;
        tokenRef.current = { collectionId, refreshToken };
        if (!enabled || previous.collectionId !== collectionId) return;
        if (previous.refreshToken !== refreshToken) refresh({ quiet: true });
    }, [collectionId, enabled, refresh, refreshToken]);

    const open = useCallback((link) => {
        openExternal(link.url).catch((e) => {
            console.error('[ArtistLinks] opening a link failed', e);
            toast.error('Could not open that link.');
        });
    }, []);

    const add = useCallback(async () => {
        const value = await promptModal({
            title: `Add a link for ${artist?.name}`,
            message:
                'Paste the address of one of their profiles — Instagram, Bandcamp, Resident Advisor, a website…',
            placeholder: 'https://www.instagram.com/…',
            confirmLabel: 'Add link',
        });
        const url = String(value ?? '').trim();
        if (!url) return;
        setBusy('add');
        try {
            const res = await addLink(collectionId, url);
            toast.success(`Added ${res?.link?.service_label || 'link'}`);
            await load();
        } catch (e) {
            console.error('[ArtistLinks] adding a link failed', e);
            toast.error(linksErrorMessage(e, 'Could not add that link.'));
        } finally {
            setBusy('');
        }
    }, [artist?.name, collectionId, load]);

    const remove = useCallback(
        async (link) => {
            setBusy(link.url_key);
            try {
                const res = await removeLink(collectionId, link.url_key);
                toast(res?.outcome === 'hidden' ? 'Hidden — restore it any time' : 'Link removed');
                await load();
            } catch (e) {
                console.error('[ArtistLinks] removing a link failed', e);
                toast.error(linksErrorMessage(e, 'Could not remove that link.'));
            } finally {
                setBusy('');
            }
        },
        [collectionId, load]
    );

    const restore = useCallback(async () => {
        setBusy('restore');
        try {
            const res = await restoreLinks(collectionId);
            toast.success(`Restored ${res?.restored ?? 0}`);
            await load();
        } catch (e) {
            console.error('[ArtistLinks] restoring links failed', e);
            toast.error(linksErrorMessage(e, 'Could not restore the hidden links.'));
        } finally {
            setBusy('');
        }
    }, [collectionId, load]);

    const confirmMb = useCallback(
        async (candidate) => {
            setBusy('mb');
            try {
                const payload = await confirmMusicBrainz(collectionId, candidate.mbid);
                setData(payload);
                setSources(payload?.sources ?? null);
                setMbCandidates([]);
                toast.success(`MusicBrainz: linked to ${candidate.name}`);
            } catch (e) {
                console.error('[ArtistLinks] confirming MusicBrainz failed', e);
                toast.error(linksErrorMessage(e, 'Could not use that MusicBrainz entry.'));
            } finally {
                setBusy('');
            }
        },
        [collectionId]
    );

    const dropMb = useCallback(async () => {
        const ok = await confirmModal({
            title: 'Not this artist on MusicBrainz?',
            message:
                'Unlink the MusicBrainz entry and remove the links that came from it. ' +
                'Links from their SoundCloud profile and the ones you added stay.',
            confirmLabel: 'Unlink',
        });
        if (!ok) return;
        setBusy('mb');
        try {
            setData(await dropMusicBrainz(collectionId));
            toast('MusicBrainz entry unlinked');
        } catch (e) {
            console.error('[ArtistLinks] dropping MusicBrainz failed', e);
            toast.error(linksErrorMessage(e, 'Could not unlink MusicBrainz.'));
        } finally {
            setBusy('');
        }
    }, [collectionId]);

    const findAccount = useCallback(async () => {
        setBusy('sc');
        try {
            const res = await fetchSoundCloudCandidates(collectionId);
            setScCandidates((res?.candidates ?? []).slice(0, MAX_ACCOUNT_SUGGESTIONS));
        } catch (e) {
            console.error('[ArtistLinks] SoundCloud account search failed', e);
            toast.error(linksErrorMessage(e, 'Could not search SoundCloud.'));
        } finally {
            setBusy('');
        }
    }, [collectionId]);

    const pickAccount = useCallback(
        async (user) => {
            setBusy('sc');
            try {
                const ok = await onLinkAccount?.(user.permalink_url);
                if (ok) setScCandidates(null);
            } finally {
                setBusy('');
            }
        },
        [onLinkAccount]
    );

    const groups = useMemo(() => groupLinks(data?.links), [data?.links]);
    const lines = sourceLines(sources ?? data?.last_fetch?.sources);
    const fetched = lastFetchedLine(data?.last_fetch);
    const hidden = hiddenLine(data?.hidden_count);
    const mb = data?.musicbrainz;

    if (!enabled) {
        return (
            <div className="rounded-xl border border-line-subtle bg-mx-panel px-3.5 py-2 text-[11.5px] text-ink-muted shrink-0">
                <span className="text-[10px] font-semibold uppercase tracking-[0.08em] mr-2">
                    Links
                </span>
                {disabledReason}
            </div>
        );
    }

    return (
        <div className="rounded-xl border border-line-subtle bg-mx-panel px-3.5 py-2.5 shrink-0">
            <div className="flex items-center gap-2 flex-wrap">
                <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-ink-muted shrink-0">
                    Links
                </span>
                {groups.length === 0 ? (
                    <span className="text-[11.5px] text-ink-muted">
                        {emptyLinksNote({ sources, last_fetch: data?.last_fetch })}
                    </span>
                ) : (
                    groups.map((group) => (
                        <span key={group.key} className="flex items-center gap-1 flex-wrap">
                            {group.links.map((link) => (
                                <LinkChip
                                    key={link.url_key}
                                    link={link}
                                    onOpen={open}
                                    onRemove={remove}
                                    busy={busy === link.url_key}
                                />
                            ))}
                        </span>
                    ))
                )}
                <span className="flex-1" />
                {hidden && (
                    <button
                        type="button"
                        onClick={restore}
                        disabled={!!busy}
                        className="text-[11px] text-ink-muted hover:text-amber2 transition-colors"
                    >
                        {hidden}
                    </button>
                )}
                <StripButton onClick={add} busy={busy === 'add'} icon={Plus}>
                    Add
                </StripButton>
                {!scLinked && (
                    <StripButton
                        onClick={findAccount}
                        busy={busy === 'sc'}
                        icon={Search}
                        title="Search SoundCloud for accounts with this name — you pick which one is theirs"
                    >
                        Find their SoundCloud
                    </StripButton>
                )}
                <StripButton
                    tone="primary"
                    onClick={() => refresh()}
                    busy={busy === 'refresh'}
                    icon={RefreshCw}
                    title="Read the links on their SoundCloud profile and ask MusicBrainz"
                >
                    Find links
                </StripButton>
            </div>

            {(lines.length > 0 || fetched || mb) && (
                <div className="mt-1.5 flex items-center gap-x-2 gap-y-1 flex-wrap text-[11px] text-ink-muted">
                    {lines.map((line, index) => (
                        <span key={line.key} className={line.ok ? 'text-ok' : 'text-amber2'}>
                            {index > 0 && <span className="text-ink-muted mr-2">·</span>}
                            {line.text}
                        </span>
                    ))}
                    {fetched && <span>· {fetched}</span>}
                    {mb && (
                        <span className="flex items-center gap-1.5">
                            ·
                            <button
                                type="button"
                                onClick={() => open({ url: mb.url })}
                                className="hover:text-amber2 transition-colors"
                                title={mb.url}
                            >
                                MusicBrainz entry
                                {mb.anchored ? ' (via their SoundCloud)' : ' (picked by you)'}
                            </button>
                            <button
                                type="button"
                                onClick={dropMb}
                                disabled={busy === 'mb'}
                                className="text-ink-muted hover:text-bad transition-colors"
                            >
                                not them?
                            </button>
                        </span>
                    )}
                </div>
            )}

            {mbCandidates.length > 0 && (
                <div className="mt-2 rounded-mx-sm border border-amber2/30 bg-amber2/[0.05] px-3 py-2 text-[11.5px]">
                    <div className="text-ink-secondary mb-1">
                        MusicBrainz knows {mbCandidates.length === 1 ? 'an artist' : 'artists'} with
                        this name. Is one of them this artist?
                    </div>
                    {mbCandidates.map((candidate) => (
                        <div key={candidate.mbid} className="flex items-center gap-2 py-0.5">
                            <span className="flex-1 min-w-0 truncate text-ink-primary">
                                {musicBrainzCandidateLine(candidate)}
                            </span>
                            <StripButton
                                onClick={() => confirmMb(candidate)}
                                busy={busy === 'mb'}
                                icon={Check}
                            >
                                That’s them
                            </StripButton>
                        </div>
                    ))}
                    <button
                        type="button"
                        onClick={() => setMbCandidates([])}
                        className="mt-1 text-[11px] text-ink-muted hover:text-ink-secondary"
                    >
                        None of these
                    </button>
                </div>
            )}

            {scCandidates !== null && (
                <div className="mt-2 rounded-mx-sm border border-line-subtle bg-mx-input/60 px-3 py-2 text-[11.5px]">
                    <div className="flex items-center gap-2 text-ink-secondary mb-1">
                        <Cloud size={12} className="text-amber2" />
                        {scCandidates.length === 0
                            ? 'SoundCloud found no account with this name.'
                            : 'Which SoundCloud account is theirs? Nothing is linked until you pick one.'}
                        <span className="flex-1" />
                        <button
                            type="button"
                            onClick={() => setScCandidates(null)}
                            className="text-ink-muted hover:text-ink-secondary"
                            aria-label="Close"
                        >
                            <X size={12} />
                        </button>
                    </div>
                    {scCandidates.map((user) => (
                        <div key={user.urn} className="flex items-center gap-2 py-1">
                            {user.avatar_url ? (
                                <img
                                    src={user.avatar_url}
                                    alt=""
                                    className="w-7 h-7 rounded-full object-cover shrink-0"
                                    referrerPolicy="no-referrer"
                                />
                            ) : (
                                <span className="w-7 h-7 rounded-full bg-mx-card shrink-0" />
                            )}
                            <div className="flex-1 min-w-0">
                                <button
                                    type="button"
                                    onClick={() => open({ url: user.permalink_url })}
                                    className="font-semibold text-ink-primary hover:text-amber2 truncate block max-w-full text-left"
                                    title={user.permalink_url}
                                >
                                    {user.username}
                                    {user.full_name && user.full_name !== user.username
                                        ? ` · ${user.full_name}`
                                        : ''}
                                </button>
                                <div className="text-ink-muted truncate">
                                    {soundCloudCandidateLine(user)}
                                </div>
                            </div>
                            <StripButton
                                tone={user.match === 'exact' ? 'primary' : undefined}
                                onClick={() => pickAccount(user)}
                                busy={busy === 'sc'}
                                icon={Link2}
                            >
                                Link
                            </StripButton>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
};

export default ArtistLinks;
