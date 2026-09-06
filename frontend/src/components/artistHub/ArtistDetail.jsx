import { useEffect, useMemo, useState } from 'react';
import {
    AlertTriangle,
    ChevronDown,
    ChevronRight,
    Clock,
    Cloud,
    Download,
    ExternalLink,
    Link2,
    Link2Off,
    Loader2,
    RefreshCw,
} from 'lucide-react';

import { ARTIST_CATALOGUE_PAGE_SIZE } from '../../config/constants';
import { formatNumber, pluralise } from './mergeCopy';
import {
    DOWNLOAD_PATH_NOTE,
    MIXES_RULE_SENTENCE,
    REMIX_RULE_SENTENCE,
    callBudgetLine,
    downloadSummary,
    exclusionReason,
    fetchedLine,
    formatDate,
    formatDuration,
    progressLine,
    splitCatalogue,
    stateSentence,
    truncationNote,
    repostsNote,
} from './catalogueCopy';

/**
 * ArtistDetail — screen 2 of `docs/research/mockups/library-artist-hub.html`: what you
 * own beside what is missing on SoundCloud, plus the excluded sets kept visible.
 *
 * Three things this view is built not to do, because the feature shipped them twice:
 *  1. Show a control that looks live but is not. The Update button is enabled only for
 *     a linked artist; otherwise it stays disabled and says why in the same words the
 *     backend uses.
 *  2. Render a typed backend state (`not_linked`, `not_connected`, `artist_gone`) as an
 *     empty list. Those states carry no bucket keys at all and are rendered as the
 *     sentence they are.
 *  3. Report a download that did not happen. Every run reports downloaded / skipped /
 *     failed from the job record, never a blanket success.
 *
 * The left panel takes the existing `TrackTable` as `children` — the local half of this
 * screen is the same table the rest of the app uses, not a second track renderer.
 */

const BUCKET_THEIRS = 'theirs';
const BUCKET_REMIXES = 'remixes';

const MAX_ERRORS_SHOWN = 5;
const PERCENT_MAX = 100;

const Chip = ({ tone = 'muted', icon: Icon, children, title }) => (
    <span
        title={title}
        className={`flex items-center gap-1.5 px-2 py-[3px] rounded-mx-xs text-[10px] whitespace-nowrap border ${
            tone === 'ok'
                ? 'text-ok bg-ok/[0.07] border-ok/30'
                : tone === 'amber'
                  ? 'text-amber2 bg-amber2/10 border-amber2/40'
                  : 'text-ink-muted bg-mx-card border-line-subtle'
        }`}
    >
        {Icon && <Icon size={11} />}
        {children}
    </span>
);

const PanelHead = ({ label, children }) => (
    <div className="flex items-center gap-2 px-3.5 py-2.5 border-b border-line-subtle">
        <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-ink-muted">
            {label}
        </span>
        {children}
    </div>
);

const PanelNote = ({ children }) => (
    <div className="border-t border-line-subtle px-3.5 py-2.5 text-[11.5px] text-ink-muted leading-relaxed">
        {children}
    </div>
);

const Hint = ({ children }) => (
    <div className="px-4 py-8 text-center text-[12px] text-ink-muted leading-relaxed">
        {children}
    </div>
);

const SmallButton = ({ onClick, disabled, title, icon: Icon, busy, tone, children }) => (
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

/** One catalogue row. Never claims a format or a bitrate — the API reports neither. */
const TrackRow = ({ track, onDownload, busy, disabled, showUploader, reason }) => {
    const duration = formatDuration(track.duration_ms);
    const posted = formatDate(track.created_at);
    // Mirrors `app/artist_store/catalogue.py::is_playable` exactly. Getting this wrong
    // would offer a Download the backend then refuses and counts as "skipped".
    const playable =
        track.access === 'playable' && !!track.streamable && track.sharing === 'public';
    return (
        <div className="flex items-center gap-3 px-3 py-2 mb-1.5 rounded-xl bg-mx-card/40 border border-white/5">
            <div className="flex-1 min-w-0">
                <div className="font-semibold text-[13px] text-ink-primary truncate">
                    {track.permalink_url ? (
                        <a
                            href={track.permalink_url}
                            target="_blank"
                            rel="noreferrer"
                            className="hover:text-amber2 transition-colors"
                            title={`Open "${track.title}" on SoundCloud`}
                        >
                            {track.title}
                        </a>
                    ) : (
                        track.title
                    )}
                </div>
                <div className="mt-0.5 flex items-center gap-2 text-[11.5px] text-ink-muted flex-wrap">
                    {duration && <span className="font-mono">{duration}</span>}
                    {posted && <span>posted {posted}</span>}
                    {showUploader && track.uploader_name && (
                        <span className="truncate">by {track.uploader_name}</span>
                    )}
                    {showUploader && (
                        <span>{track.credited ? 'named in the title/tags' : 'not named'}</span>
                    )}
                    {reason && <span>{reason}</span>}
                    {track.downloadable && <Chip>artist allows download</Chip>}
                </div>
            </div>
            <SmallButton
                onClick={() => onDownload(track)}
                busy={busy}
                disabled={disabled || !playable}
                icon={Download}
                title={
                    playable
                        ? `Download "${track.title}" through the SoundCloud downloader`
                        : 'SoundCloud does not serve this account a full stream of this track — ' +
                          'preview only, private or blocked. It is not downloadable.'
                }
            >
                {playable ? 'Download' : 'Not streamable'}
            </SmallButton>
        </div>
    );
};

/** The counts line under the artist name. Every number comes from a real payload. */
export const ArtistDetailSummary = ({ localShown, localTotal, catalogue, scEnabled }) => {
    const split = useMemo(() => splitCatalogue(catalogue.view), [catalogue.view]);
    const filtered = localShown !== localTotal;
    return (
        <p className="text-ink-secondary text-sm mt-0.5 flex items-center gap-2 flex-wrap">
            <span className="font-mono">
                {filtered
                    ? `${formatNumber(localShown)} / ${formatNumber(localTotal)} in library`
                    : `${formatNumber(localTotal)} in library`}
            </span>
            {catalogue.loading || catalogue.refreshing ? (
                <span className="text-ink-muted">· reading the SoundCloud catalogue…</span>
            ) : split.ok ? (
                <>
                    <span className="text-amber2 font-mono">
                        · {formatNumber(split.missingTheirs.length)} missing on SoundCloud
                    </span>
                    <span className="text-ink-muted font-mono">
                        · {formatNumber(split.missingRemixes.length)} remixes by others
                    </span>
                </>
            ) : (
                <span className="text-ink-muted">
                    · {scEnabled ? 'no catalogue read yet' : 'not linked to SoundCloud'}
                </span>
            )}
        </p>
    );
};

/** Header controls: link state, Update, Download all missing. */
export const ArtistDetailActions = ({ artist, catalogue, actions, scEnabled, disabledReason }) => {
    const split = useMemo(() => splitCatalogue(catalogue.view), [catalogue.view]);
    const view = catalogue.view;
    // Three states, not two: bound and usable, bound but broken (imported URL that was
    // never resolved, or an account SoundCloud no longer serves), and not bound at all.
    // Collapsing the middle one into "not linked" would hide the Unlink button for
    // exactly the link the user needs to get rid of.
    const usable = view?.status === 'ok' || !!view?.link?.resolved;
    const bound =
        usable ||
        view?.status === 'artist_gone' ||
        view?.status === 'link_unresolved' ||
        (!view && !!artist?.sc_linked);
    const permalink = view?.link?.permalink || view?.permalink || artist?.sc_permalink || '';
    const queueable = split.queueable.length;

    const updateBlocked = !scEnabled
        ? disabledReason
        : !bound
          ? 'Link a SoundCloud profile first — there is nothing to update until this artist is bound to an account.'
          : view?.status === 'not_connected'
            ? stateSentence(view)
            : '';

    return (
        <div className="flex items-center gap-2 shrink-0">
            {usable ? (
                <Chip tone="ok" icon={Link2} title={permalink || 'Linked to a SoundCloud account'}>
                    {permalink ? permalink.replace(/^https?:\/\//, '') : 'SC linked'}
                </Chip>
            ) : (
                <SmallButton
                    onClick={actions.handleLink}
                    disabled={!scEnabled}
                    busy={catalogue.linking}
                    icon={Link2}
                    title={
                        scEnabled
                            ? bound
                                ? stateSentence(view)
                                : 'Bind this artist to a SoundCloud profile URL'
                            : disabledReason
                    }
                >
                    {bound ? 'Re-link profile' : 'Link SoundCloud profile'}
                </SmallButton>
            )}
            {bound && (
                <SmallButton
                    onClick={actions.handleUnlink}
                    busy={catalogue.linking}
                    icon={Link2Off}
                    title="Unbind this artist from that SoundCloud account"
                >
                    Unlink
                </SmallButton>
            )}
            <SmallButton
                onClick={actions.handleUpdate}
                disabled={!!updateBlocked}
                busy={catalogue.refreshing}
                icon={RefreshCw}
                title={updateBlocked || 'Fetch this artist‘s catalogue from SoundCloud now'}
            >
                Update
            </SmallButton>
            <SmallButton
                tone="primary"
                onClick={() => actions.handleDownloadAll(queueable)}
                disabled={!split.ok || queueable === 0 || catalogue.downloading}
                busy={catalogue.downloading && actions.pendingScId === null}
                icon={Download}
                title={
                    !split.ok
                        ? 'No catalogue has been read for this artist yet'
                        : queueable === 0
                          ? 'Nothing from this artist’s own uploads is missing'
                          : `Download ${queueable} missing track(s) uploaded by this artist‘s own account`
                }
            >
                Download all missing{split.ok && queueable > 0 ? ` (${queueable})` : ''}
            </SmallButton>
        </div>
    );
};

const RunProgress = ({ catalogue }) => {
    const job = catalogue.job;
    if (!catalogue.downloading || !job) return null;
    const percent = Math.min(PERCENT_MAX, Math.max(0, Number(job.percent) || 0));
    return (
        <div className="rounded-xl border border-amber2/30 bg-amber2/[0.06] px-3.5 py-2.5">
            <div className="flex items-center gap-2 text-[12px] text-ink-primary">
                <Loader2 size={14} className="animate-spin text-amber2" />
                <span className="truncate">{progressLine(job)}</span>
                <span className="flex-1" />
                <span className="font-mono text-[11px] text-ink-muted">{percent.toFixed(0)}%</span>
            </div>
            <div className="mt-2 h-1.5 rounded-full bg-black/30 overflow-hidden">
                <div className="h-full bg-amber2 transition-all" style={{ width: `${percent}%` }} />
            </div>
        </div>
    );
};

const RunResult = ({ catalogue }) => {
    const job = catalogue.result;
    if (!job || catalogue.downloading) return null;
    const errors = Array.isArray(job.errors) ? job.errors : [];
    const failed = (Number(job.failed) || 0) > 0;
    return (
        <div
            className={`rounded-xl border px-3.5 py-2.5 ${
                failed ? 'border-bad/40 bg-bad/[0.06]' : 'border-line-subtle bg-mx-card/60'
            }`}
        >
            <div className="flex items-center gap-2 text-[12px] text-ink-primary">
                {failed ? (
                    <AlertTriangle size={14} className="text-bad shrink-0" />
                ) : (
                    <Download size={14} className="text-ink-muted shrink-0" />
                )}
                <span>{downloadSummary(job)}</span>
                <span className="flex-1" />
                <button
                    type="button"
                    onClick={catalogue.clearResult}
                    className="text-[11px] text-ink-muted hover:text-ink-secondary transition-colors"
                >
                    Dismiss
                </button>
            </div>
            {errors.length > 0 && (
                <ul className="mt-1.5 space-y-0.5 text-[11.5px] text-ink-muted">
                    {errors.slice(0, MAX_ERRORS_SHOWN).map((entry) => (
                        <li key={entry.sc_id} className="truncate">
                            {entry.title || entry.sc_id} — {entry.error}
                        </li>
                    ))}
                    {errors.length > MAX_ERRORS_SHOWN && (
                        <li>+ {errors.length - MAX_ERRORS_SHOWN} more in the backend log</li>
                    )}
                </ul>
            )}
        </div>
    );
};

/** The excluded strip. Collapsed, counted, and every row still downloadable one by one. */
const MixesStrip = ({ tracks, actions, catalogue }) => {
    const [open, setOpen] = useState(false);
    const Icon = open ? ChevronDown : ChevronRight;
    return (
        <div className="rounded-xl border border-line-subtle bg-mx-input/60 shrink-0">
            <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                className="w-full flex items-start gap-2 px-3.5 py-2.5 text-left"
            >
                <Icon size={14} className="text-ink-muted mt-[2px] shrink-0" />
                <span className="text-[12px] font-semibold text-ink-secondary shrink-0">
                    Mixes &amp; sets ({formatNumber(tracks.length)}) — excluded
                </span>
                <span className="text-[11.5px] text-ink-muted leading-relaxed">
                    {MIXES_RULE_SENTENCE}
                </span>
                <Chip>not counted as missing</Chip>
            </button>
            {open && (
                <div className="px-3 pb-3 max-h-64 overflow-y-auto">
                    {tracks.length === 0 ? (
                        <Hint>Nothing was excluded for this artist.</Hint>
                    ) : (
                        tracks.map((track) => (
                            <TrackRow
                                key={track.sc_id}
                                track={track}
                                reason={exclusionReason(track)}
                                onDownload={actions.handleDownloadOne}
                                busy={actions.pendingScId === track.sc_id}
                                disabled={catalogue.downloading}
                            />
                        ))
                    )}
                </div>
            )}
        </div>
    );
};

/** Everything the missing panel can say when it has no list to show. */
const MissingEmptyState = ({ catalogue, actions, scEnabled, disabledReason, split }) => {
    const view = catalogue.view;
    if (!scEnabled) return <Hint>{disabledReason}</Hint>;
    if (catalogue.loading) {
        return (
            <div className="flex items-center justify-center gap-3 py-16 text-ink-muted text-[12px]">
                <Loader2 size={18} className="animate-spin text-amber2" />
                Reading the SoundCloud catalogue…
            </div>
        );
    }
    if (catalogue.error) {
        return (
            <Hint>
                <p className="mb-3">{catalogue.error}</p>
                <SmallButton onClick={() => catalogue.reload()} icon={RefreshCw}>
                    Try again
                </SmallButton>
            </Hint>
        );
    }
    if (!view) return <Hint>No catalogue has been read for this artist yet.</Hint>;
    if (view.status !== 'ok') {
        const canLink = view.status === 'not_linked' || view.status === 'link_unresolved';
        return (
            <Hint>
                <p className="mb-3">{stateSentence(view)}</p>
                <div className="flex items-center justify-center gap-2">
                    {canLink && (
                        <SmallButton onClick={actions.handleLink} icon={Link2} tone="primary">
                            {view.status === 'link_unresolved'
                                ? 'Re-link this profile'
                                : 'Link SoundCloud profile'}
                        </SmallButton>
                    )}
                    {view.status === 'not_connected' && (
                        <SmallButton onClick={() => catalogue.reload()} icon={RefreshCw}>
                            Retry
                        </SmallButton>
                    )}
                    {view.permalink && (
                        <a
                            href={view.permalink}
                            target="_blank"
                            rel="noreferrer"
                            className="flex items-center gap-1.5 px-2.5 py-1 rounded-mx-sm text-[11px] bg-mx-card border border-line-subtle text-ink-primary hover:text-amber2 hover:border-amber2/50 transition-colors"
                        >
                            <ExternalLink size={12} />
                            Open the profile
                        </a>
                    )}
                </div>
            </Hint>
        );
    }
    if (split.theirs.length + split.remixes.length === 0) {
        return <Hint>SoundCloud lists no playable tracks on this account.</Hint>;
    }
    return null;
};

const ArtistDetail = ({
    artist,
    catalogue,
    actions,
    scEnabled,
    disabledReason,
    tracksLoading,
    localTotal,
    children,
}) => {
    const split = useMemo(() => splitCatalogue(catalogue.view), [catalogue.view]);
    const [bucket, setBucket] = useState(BUCKET_THEIRS);
    const [shown, setShown] = useState(ARTIST_CATALOGUE_PAGE_SIZE);

    const rows = bucket === BUCKET_THEIRS ? split.missingTheirs : split.missingRemixes;

    useEffect(() => {
        setShown(ARTIST_CATALOGUE_PAGE_SIZE);
    }, [bucket, catalogue.view]);

    // Every branch that has no list to show routes through MissingEmptyState, so a
    // typed backend state can never be rendered as an empty bucket.
    const showList =
        scEnabled &&
        !catalogue.loading &&
        !catalogue.error &&
        split.ok &&
        split.theirs.length + split.remixes.length > 0;

    const budget = callBudgetLine(catalogue.view);
    const truncated = truncationNote(catalogue.view);
    const aliases = (artist?.library_names?.length || 1) - 1;

    return (
        <div className="flex-1 min-h-0 flex flex-col gap-3">
            <RunProgress catalogue={catalogue} />
            <RunResult catalogue={catalogue} />

            <div className="flex-1 min-h-0 grid grid-cols-1 xl:grid-cols-2 gap-4">
                {/* Local half — the same TrackTable the rest of the app uses. */}
                <div className="bg-mx-panel border border-line-subtle rounded-xl flex flex-col min-h-0 overflow-hidden">
                    <PanelHead label={`In your library · ${formatNumber(localTotal)}`}>
                        <span className="flex-1" />
                        {aliases > 0 && (
                            <Chip title={(artist?.library_names || []).join(' · ')}>
                                {pluralise(aliases, 'alias', 'aliases')} merged
                            </Chip>
                        )}
                    </PanelHead>
                    <div className="flex-1 min-h-0">
                        {tracksLoading ? (
                            <div className="flex items-center justify-center gap-3 py-16 text-ink-muted text-[12px]">
                                <Loader2 size={18} className="animate-spin text-amber2" />
                                Loading tracks…
                            </div>
                        ) : localTotal === 0 ? (
                            <Hint>
                                No local tracks found for this artist in the loaded library.
                            </Hint>
                        ) : (
                            children
                        )}
                    </div>
                </div>

                {/* Remote half — missing, split the way the owner asked. */}
                <div className="bg-mx-panel border border-line-subtle rounded-xl flex flex-col min-h-0 overflow-hidden">
                    <PanelHead label={`Missing on SoundCloud · ${formatNumber(rows.length)}`}>
                        <div className="inline-flex rounded-mx-sm overflow-hidden border border-line-subtle bg-mx-input ml-1">
                            {[
                                {
                                    id: BUCKET_THEIRS,
                                    label: `Definitely theirs (${split.missingTheirs.length})`,
                                    title: 'Uploaded by this artist’s own SoundCloud account — the only bucket "Download all missing" queues.',
                                },
                                {
                                    id: BUCKET_REMIXES,
                                    label: `Remixes by others (${split.missingRemixes.length})`,
                                    title: REMIX_RULE_SENTENCE,
                                },
                            ].map((option) => (
                                <button
                                    key={option.id}
                                    type="button"
                                    title={option.title}
                                    onClick={() => setBucket(option.id)}
                                    className={`px-2 py-[3px] text-[10px] border-r border-line-subtle last:border-r-0 transition-colors ${
                                        bucket === option.id
                                            ? 'bg-amber2/10 text-amber2 font-semibold'
                                            : 'text-ink-muted hover:text-ink-secondary hover:bg-mx-hover'
                                    }`}
                                >
                                    {option.label}
                                </button>
                            ))}
                        </div>
                        <span className="flex-1" />
                        {split.ok && (
                            <Chip
                                tone={catalogue.view?.from_cache ? 'muted' : 'ok'}
                                icon={catalogue.view?.from_cache ? Clock : Cloud}
                                title={budget}
                            >
                                {fetchedLine(catalogue.view)}
                            </Chip>
                        )}
                    </PanelHead>

                    <div className="flex-1 min-h-0 overflow-y-auto p-3">
                        {!showList ? (
                            <MissingEmptyState
                                catalogue={catalogue}
                                actions={actions}
                                scEnabled={scEnabled}
                                disabledReason={disabledReason}
                                split={split}
                            />
                        ) : rows.length === 0 ? (
                            <Hint>
                                {bucket === BUCKET_THEIRS
                                    ? `Nothing missing from this artist’s own uploads — all ${formatNumber(
                                          split.theirs.length
                                      )} of them are already in your library.`
                                    : repostsNote(catalogue?.reposts_status)}
                            </Hint>
                        ) : (
                            <>
                                {rows.slice(0, shown).map((track) => (
                                    <TrackRow
                                        key={track.sc_id}
                                        track={track}
                                        showUploader={bucket === BUCKET_REMIXES}
                                        onDownload={actions.handleDownloadOne}
                                        busy={actions.pendingScId === track.sc_id}
                                        disabled={catalogue.downloading}
                                    />
                                ))}
                                {rows.length > shown && (
                                    <button
                                        type="button"
                                        onClick={() =>
                                            setShown((n) => n + ARTIST_CATALOGUE_PAGE_SIZE)
                                        }
                                        className="w-full px-2.5 py-2 mt-1 rounded-mx-sm text-[11px] bg-mx-card border border-line-subtle text-ink-primary hover:border-amber2/50 hover:text-amber2 transition-colors"
                                    >
                                        Show more · {rows.length - shown} left
                                    </button>
                                )}
                            </>
                        )}
                    </div>

                    <PanelNote>
                        {truncated && (
                            <span className="flex items-start gap-1.5 mb-1 text-amber2">
                                <AlertTriangle size={12} className="mt-[2px] shrink-0" />
                                {truncated}
                            </span>
                        )}
                        {bucket === BUCKET_THEIRS ? DOWNLOAD_PATH_NOTE : REMIX_RULE_SENTENCE}
                        {budget && <span className="block mt-1 font-mono">{budget}</span>}
                    </PanelNote>
                </div>
            </div>

            {split.ok && (
                <MixesStrip tracks={split.mixes} actions={actions} catalogue={catalogue} />
            )}
        </div>
    );
};

export default ArtistDetail;
