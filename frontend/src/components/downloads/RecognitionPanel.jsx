import React, { useMemo, useState } from 'react';
import toast from 'react-hot-toast';
import { Check, Lightbulb, Loader2, Star, Undo2, UserCheck, Wand2 } from 'lucide-react';
import api from '../../api/api';
import {
    correctionLine,
    creditChips,
    recognitionHeadline,
    suggestionState,
} from './recognitionCopy';

/**
 * RecognitionPanel — the download recognizer's answer on a Download Manager task
 * (artist hub T-31): who is credited and whether the library knows them, the names
 * the file got and why, and a suggestion the recognizer would not apply on its own.
 *
 * "Übernehmen" / "Rückgängig" write through
 * `POST /api/soundcloud/downloads/{sc_track_id}/names` — library row + file tags,
 * only ever for a track this app downloaded. The next task poll carries the result
 * (`recognition.applied`), so the panel keeps no copy of it.
 */

const TONE_CLASS = {
    favourite: 'bg-amber2/10 text-amber2 border-amber2/40',
    known: 'bg-ok/10 text-ok border-ok/30',
    new: 'bg-white/5 text-ink-secondary border-white/10 border-dashed',
};

const RecognitionPanel = ({ task }) => {
    const recognition = task?.recognition;
    const [dismissed, setDismissed] = useState(false);
    const [busy, setBusy] = useState(false);
    const chips = useMemo(() => creditChips(recognition), [recognition]);

    if (!recognition) return null;
    const headline = recognitionHeadline(recognition);
    const correction = correctionLine(recognition);
    const suggestion = suggestionState(recognition, task.local_track_id);

    const writeNames = async (names, doneMessage) => {
        setBusy(true);
        try {
            await api.post(
                `/api/soundcloud/downloads/${encodeURIComponent(task.sc_track_id)}/names`,
                { artist: names.artist, title: names.title }
            );
            toast.success(doneMessage);
        } catch (err) {
            console.error('[RecognitionPanel] writing names failed', err);
            toast.error(err?.response?.data?.detail || 'Namen konnten nicht geschrieben werden');
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="mt-2 space-y-1.5 text-[11px]">
            {headline && (
                <div className="flex items-center gap-1.5 flex-wrap">
                    <span className="flex items-center gap-1 text-ink-muted">
                        <UserCheck size={11} /> {headline}
                    </span>
                    {chips.map((chip) => (
                        <span
                            key={chip.key}
                            title={chip.title}
                            className={`inline-flex items-center gap-1 px-1.5 py-[1px] rounded border ${TONE_CLASS[chip.tone]}`}
                        >
                            {chip.tone === 'favourite' && (
                                <Star size={9} className="fill-current" />
                            )}
                            {chip.label}
                            {chip.tone === 'new' && (
                                <span className="text-[9px] uppercase tracking-wider opacity-70">
                                    neu
                                </span>
                            )}
                        </span>
                    ))}
                </div>
            )}

            {correction && (
                <div
                    className="flex items-center gap-1.5 text-ink-muted min-w-0"
                    title={correction.reasons.join(' ')}
                >
                    <Wand2 size={11} className="text-ok shrink-0" />
                    <span className="truncate">
                        Name korrigiert:{' '}
                        <span className="line-through opacity-60">{correction.before}</span>
                        {' → '}
                        <span className="text-ink-secondary">{correction.after}</span>
                    </span>
                </div>
            )}

            {suggestion && !dismissed && (
                <div className="flex items-center gap-2 rounded-lg border border-amber2/30 bg-amber2/5 px-2 py-1.5">
                    <Lightbulb size={11} className="text-amber2 shrink-0" />
                    <span className="flex-1 min-w-0 truncate" title={suggestion.reason}>
                        {suggestion.state === 'applied' ? 'Übernommen: ' : 'Vorschlag: '}
                        <span className="text-ink-primary">{suggestion.names}</span>
                    </span>
                    {suggestion.state === 'applied' ? (
                        <button
                            type="button"
                            disabled={busy}
                            onClick={() =>
                                writeNames(suggestion.undo, 'Ursprüngliche Namen wiederhergestellt')
                            }
                            className="flex items-center gap-1 px-2 py-0.5 rounded border border-white/10 text-ink-secondary hover:text-white disabled:opacity-40"
                            title="Artist und Titel wieder so schreiben, wie SoundCloud sie geliefert hat"
                        >
                            {busy ? (
                                <Loader2 size={10} className="animate-spin" />
                            ) : (
                                <Undo2 size={10} />
                            )}
                            Rückgängig
                        </button>
                    ) : (
                        <>
                            <button
                                type="button"
                                disabled={busy || suggestion.state !== 'open'}
                                onClick={() =>
                                    writeNames(
                                        { artist: suggestion.artist, title: suggestion.title },
                                        'Namen übernommen'
                                    )
                                }
                                className="flex items-center gap-1 px-2 py-0.5 rounded bg-amber2/20 text-amber2 border border-amber2/40 hover:bg-amber2/30 disabled:opacity-40 disabled:cursor-not-allowed"
                                title={
                                    suggestion.state === 'waiting'
                                        ? 'Erst möglich, wenn der Track in der Library ist'
                                        : 'Artist und Titel so in Library und Datei schreiben'
                                }
                            >
                                {busy ? (
                                    <Loader2 size={10} className="animate-spin" />
                                ) : (
                                    <Check size={10} />
                                )}
                                Übernehmen
                            </button>
                            <button
                                type="button"
                                onClick={() => setDismissed(true)}
                                className="px-2 py-0.5 rounded text-ink-muted hover:text-ink-secondary"
                            >
                                Ignorieren
                            </button>
                        </>
                    )}
                </div>
            )}
        </div>
    );
};

export default RecognitionPanel;
