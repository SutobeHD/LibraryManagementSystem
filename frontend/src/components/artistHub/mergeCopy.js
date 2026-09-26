/**
 * mergeCopy — the sentences the merge dialog has to say out loud.
 *
 * Pure string builders, no React, no network: an artist merge is not undoable by
 * closing the dialog, so what it will do has to be stated in full *before* the
 * confirm. Keeping the wording here (and testable) is why it exists as its own
 * module — `MergeDialog.jsx` renders these, it does not compose them.
 *
 * Load-bearing rule: never invent a number the preview did not report. The
 * backend measures the USB cost from the LOCAL files (`bytes_local_source`) and
 * says so via `files_measured` / `files_unmeasured`; when there is no byte figure
 * the copy falls back to the track count instead of guessing a size.
 *
 * Preview shape: `app/artist_store/merge.py::MergePreview.as_dict`.
 */

const BYTE_UNITS = ['B', 'KB', 'MB', 'GB', 'TB'];
const BYTE_STEP = 1024;
// Below this the fractional digit still carries information (1.4 GB); above it
// the decimal is noise (412 MB).
const BYTE_DECIMAL_CUTOFF = 100;

/** Locale-grouped integer. Anything unusable renders as 0, never as NaN. */
export const formatNumber = (value) => {
    const n = Number(value);
    return Number.isFinite(n) ? Math.round(n).toLocaleString() : '0';
};

export const pluralise = (value, singular, plural) =>
    `${formatNumber(value)} ${Number(value) === 1 ? singular : plural}`;

/** Human byte size, or `null` when the caller has no real figure to show. */
export const formatBytes = (bytes) => {
    const n = Number(bytes);
    if (!Number.isFinite(n) || n <= 0) return null;
    let value = n;
    let unit = 0;
    while (value >= BYTE_STEP && unit < BYTE_UNITS.length - 1) {
        value /= BYTE_STEP;
        unit += 1;
    }
    const digits = unit === 0 || value >= BYTE_DECIMAL_CUTOFF ? 0 : 1;
    return `${value.toFixed(digits)} ${BYTE_UNITS[unit]}`;
};

/** The dry-run line under the canonical picker. */
export const dryRunLine = (preview) =>
    `${pluralise(preview?.tracks_to_rewrite, 'track', 'tracks')} will be rewritten in Rekordbox`;

/** Effect 1 — the database rows. */
export const databaseEffect = (preview) => {
    const base = `${pluralise(
        preview?.tracks_to_rewrite,
        'track is',
        'tracks are'
    )} rewritten in Rekordbox (master.db).`;
    if (preview?.counts_exact === false) {
        return `${base} Upper bound — a track credited to two of these spellings is counted twice here.`;
    }
    const already = Number(preview?.tracks_already_canonical) || 0;
    if (already > 0) {
        return `${base} ${pluralise(already, 'track', 'tracks')} already point at the canonical name and stay untouched.`;
    }
    return base;
};

/** Effect 2 — the audio files on disk. */
export const filesEffect = (preview) => {
    if (preview?.files_measured === false) {
        return 'The artist tag is rewritten inside the audio file of every rewritten track. The files could not be counted before the run.';
    }
    const missing = Number(preview?.files_missing) || 0;
    const base = `${pluralise(preview?.files_to_retag, 'audio file is', 'audio files are')} re-tagged on disk — their timestamps change and every other tool reading them sees the canonical name.`;
    if (missing > 0) {
        return `${base} ${pluralise(missing, 'track has', 'tracks have')} no readable file and are skipped.`;
    }
    return base;
};

/** Effect 3 — the USB stick. Size only when the preview actually measured one. */
export const usbEffect = (preview) => {
    const usb = preview?.usb;
    const folders = usb?.folders_to_merge ?? [];
    if (!usb || folders.length === 0) {
        return 'No folder on the USB stick changes — every affected track already lives under the canonical folder.';
    }
    const target = usb.canonical_folder || preview?.canonical || 'the canonical folder';
    const bytes = formatBytes(usb.bytes_local_source);
    const unmeasured = Number(usb.files_unmeasured) || 0;
    const moved = pluralise(usb.tracks_relocated, 'track', 'tracks');

    let size;
    if (bytes && unmeasured > 0) {
        size = `${moved}, about ${bytes} measured (${formatNumber(unmeasured)} could not be measured)`;
    } else if (bytes) {
        size = `${moved}, about ${bytes}`;
    } else {
        // No byte figure — say tracks. Never guess a size.
        size = unmeasured > 0 ? `${moved} (size not measured)` : moved;
    }

    const caseOnly = Number(usb.case_only_renames) || 0;
    const caseNote =
        caseOnly > 0
            ? ` ${formatNumber(caseOnly)} of them differ only in capitalisation and are renamed in two steps.`
            : '';

    return `${pluralise(folders.length, 'folder merges', 'folders merge')} into ${target} at the next USB export: ${size} moved on the stick, not re-copied.${caseNote}`;
};

/** The three effects the dialog must state before the confirm, in order. */
export const mergeEffects = (preview) => [
    { id: 'db', text: databaseEffect(preview) },
    { id: 'files', text: filesEffect(preview) },
    { id: 'usb', text: usbEffect(preview) },
];

/** `Contents/boys noize, Contents/BOYS NOIZE → Contents/Boys Noize`, or ''. */
export const usbFolderList = (preview) => {
    const usb = preview?.usb;
    const folders = (usb?.folders_to_merge ?? []).map((f) => f.folder).filter(Boolean);
    if (folders.length === 0) return '';
    return `${folders.join(', ')} → ${usb.canonical_folder || preview?.canonical || ''}`.trim();
};

/**
 * Repointing a track whose artist row names more than this group flattens the
 * credit ("boys noize, Objekt" → "Boys Noize"). The preview counts them; the
 * dialog has to say so. Returns `null` when the group has none.
 */
export const compoundWarning = (preview) => {
    const n = Number(preview?.compound_artist_tracks) || 0;
    if (n <= 0) return null;
    const names = preview?.compound_artist_names ?? [];
    const examples = names.length ? ` (e.g. ${names.slice(0, 3).join(', ')})` : '';
    return `${pluralise(n, 'track credits', 'tracks credit')} more than this artist${examples}. Merging repoints them to the canonical artist and flattens that credit.`;
};

/** One-line warning under the opt-in orphan checkbox. */
export const ORPHAN_WARNING_LINE =
    'Hard delete, no tombstone — it also clears Remixer, Original-Artist, Composer and Lyricist on every track that still references those entries, and a revert cannot restore those links.';

export const JOURNAL_NOTE =
    'Every rewritten row is journalled with its pre-image before the write, so the whole run can be reverted from the History tab. Rekordbox must be closed while merging.';

/** The confirm-modal body: the three effects plus whatever else is switched on. */
export const confirmMessage = (preview, { deleteOrphans = false } = {}) => {
    const lines = [];
    mergeEffects(preview).forEach((effect) => {
        lines.push(`• ${effect.text}`);
        // The confirm names the folders, not just how many: on the stick they are
        // the only thing the user can check the merge against afterwards.
        if (effect.id === 'usb') {
            const folders = usbFolderList(preview);
            if (folders) lines.push(`   ${folders}`);
        }
    });
    const compound = compoundWarning(preview);
    if (compound) lines.push(`• ${compound}`);
    if (deleteOrphans) {
        const orphans = Number(preview?.orphans_after) || 0;
        lines.push(
            `• ${pluralise(orphans, 'empty artist entry is', 'empty artist entries are')} deleted. ${ORPHAN_WARNING_LINE}`
        );
    }
    lines.push('');
    lines.push(JOURNAL_NOTE);
    return lines.join('\n');
};

/** Post-run summary for the toast + the result strip. */
export const applySummary = (result) => {
    if (!result) return 'Merge finished.';
    const parts = [`${pluralise(result.tracks_rewritten, 'track', 'tracks')} rewritten`];
    if (result.write_tags) {
        parts.push(`${pluralise(result.files_retagged, 'file', 'files')} re-tagged`);
    }
    const skipped = result.files_skipped?.length ?? 0;
    if (skipped > 0) parts.push(`${formatNumber(skipped)} skipped`);
    const orphans = result.orphans_deleted?.length ?? 0;
    if (orphans > 0) parts.push(`${pluralise(orphans, 'artist entry', 'artist entries')} deleted`);
    if (result.aborted) parts.push('run aborted early');
    return `${parts.join(' · ')}.`;
};

/** Post-revert summary. `complete === false` is stated, never smoothed over. */
export const revertSummary = (result) => {
    if (!result) return 'Revert finished.';
    const parts = [`${pluralise(result.tracks_restored, 'track', 'tracks')} restored`];
    if (result.files_restored) {
        parts.push(`${pluralise(result.files_restored, 'file tag', 'file tags')} restored`);
    }
    if (result.artists_restored) {
        parts.push(
            `${pluralise(result.artists_restored, 'artist entry', 'artist entries')} re-created`
        );
    }
    const failed = (Number(result.tracks_failed) || 0) + (Number(result.artists_failed) || 0);
    if (failed > 0) parts.push(`${formatNumber(failed)} failed`);
    const summary = `${parts.join(' · ')}.`;
    return result.complete === false
        ? `${summary} The revert is incomplete — run it again once the blockers are gone.`
        : summary;
};
