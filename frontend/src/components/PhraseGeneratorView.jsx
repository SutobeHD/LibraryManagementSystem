/**
 * PhraseGeneratorView — Phrase & Auto-Cue Generator (batch)
 *
 * Writes phrase markers as Rekordbox MEMORY cues across a chosen scope:
 * a single track, a whole playlist, a hand-picked selection, or the entire
 * collection. Runs as a background job with a live progress panel (done/total,
 * ETA, written/skipped/failed, cancel).
 *
 * Flow:
 *   1. Pick a scope (PhraseScopePicker)
 *   2. Pick phrase length + options (downbeat align, bar markers)
 *   3. "Generate" → POST /api/phrase/batch/start → poll → progress
 *
 * Memory cues are written non-destructively into each track's existing ANLZ
 * (beat grid, waveform and hot cues are preserved).
 */

import { useCallback, useState } from 'react';
import { BarChart3, Zap, Loader2, AlertTriangle, Info } from 'lucide-react';
import toast from 'react-hot-toast';
import PhraseScopePicker from './PhraseScopePicker';
import PhraseBatchProgress from './PhraseBatchProgress';
import usePhraseBatch from './usePhraseBatch';

const PHRASE_LENGTHS = [
    { value: 8, label: '8 Bars', desc: 'Short — house, techno intro' },
    { value: 16, label: '16 Bars', desc: 'Standard — most dance music' },
    { value: 32, label: '32 Bars', desc: 'Long — progressive, ambient' },
];

const Toggle = ({ on, onClick, label, hint }) => (
    <button
        onClick={onClick}
        className="flex items-center justify-between w-full p-2.5 rounded-mx-sm border border-line-subtle hover:bg-mx-hover transition-colors"
    >
        <div className="text-left min-w-0">
            <p className="text-[12px] text-ink-primary">{label}</p>
            {hint && <p className="text-[10px] text-ink-muted">{hint}</p>}
        </div>
        <div
            className={`w-9 h-5 rounded-full p-0.5 shrink-0 transition-colors ${on ? 'bg-amber2' : 'bg-line-subtle'}`}
        >
            <div
                className={`w-4 h-4 rounded-full bg-white transition-transform ${on ? 'translate-x-4' : ''}`}
            />
        </div>
    </button>
);

const PhraseGeneratorView = () => {
    const [phraseLength, setPhraseLength] = useState(16);
    const [alignDownbeat, setAlignDownbeat] = useState(false);
    const [includeBars, setIncludeBars] = useState(false);
    const [scopeState, setScopeState] = useState({
        scope: null,
        valid: false,
        count: 0,
        mode: 'collection',
    });

    const { progress, running, error, start, cancel } = usePhraseBatch();

    const handleScopeChange = useCallback((s) => setScopeState(s), []);

    const handleGenerate = () => {
        if (!scopeState.valid || !scopeState.scope) {
            toast.error('Select a scope first');
            return;
        }
        start({
            scope: scopeState.scope,
            phrase_length: phraseLength,
            align_downbeat: alignDownbeat,
            include_bar_markers: includeBars,
        });
    };

    const countLabel =
        scopeState.count == null ? '' : scopeState.count === 1 ? ' (1 track)' : ` (${scopeState.count} tracks)`;
    const bigScope =
        scopeState.mode === 'collection' || (scopeState.count != null && scopeState.count > 200);

    return (
        <div className="h-full overflow-y-auto p-6 bg-mx-deepest">
            <div className="max-w-3xl mx-auto space-y-6">
                {/* Header */}
                <div className="flex items-center gap-3">
                    <div
                        className="w-9 h-9 rounded-mx-md flex items-center justify-center"
                        style={{ background: 'var(--amber-bg)', color: 'var(--amber)' }}
                    >
                        <BarChart3 size={18} />
                    </div>
                    <div>
                        <h1 className="text-lg font-semibold text-ink-primary">Phrase Generator</h1>
                        <p className="text-ink-muted text-tiny">
                            Write phrase memory cues across tracks, playlists or the whole collection
                        </p>
                    </div>
                </div>

                {/* Scope */}
                <PhraseScopePicker onScopeChange={handleScopeChange} />

                {/* Phrase length */}
                <div className="mx-card rounded-mx-md p-4 space-y-3">
                    <div className="mx-caption">Phrase Length</div>
                    <div className="grid grid-cols-3 gap-2">
                        {PHRASE_LENGTHS.map((pl) => (
                            <button
                                key={pl.value}
                                onClick={() => setPhraseLength(pl.value)}
                                className={`flex flex-col items-center p-3 rounded-mx-sm border transition-all text-center ${
                                    phraseLength === pl.value
                                        ? 'bg-amber2/10 border-amber2/50 text-amber2'
                                        : 'border-line-subtle text-ink-muted hover:bg-mx-hover'
                                }`}
                            >
                                <span className="text-[14px] font-bold">{pl.label}</span>
                                <span className="text-[9px] mt-1 opacity-70">{pl.desc}</span>
                            </button>
                        ))}
                    </div>
                </div>

                {/* Options */}
                <div className="mx-card rounded-mx-md p-4 space-y-2">
                    <div className="mx-caption">Options</div>
                    <Toggle
                        on={alignDownbeat}
                        onClick={() => setAlignDownbeat((v) => !v)}
                        label="Align to downbeat"
                        hint="More accurate, but loads each track's audio (slow on large scopes)"
                    />
                    <Toggle
                        on={includeBars}
                        onClick={() => setIncludeBars((v) => !v)}
                        label="Include bar markers"
                        hint="Also place a memory cue at every bar (many cues per track)"
                    />
                    {alignDownbeat && bigScope && (
                        <div className="flex items-start gap-2 text-amber2 text-[10px] bg-amber2/5 border border-amber2/20 rounded-mx-sm px-3 py-2">
                            <Info size={12} className="mt-0.5 shrink-0" />
                            Downbeat alignment loads audio per track — this can take a while over a large
                            collection.
                        </div>
                    )}
                </div>

                {/* Generate */}
                <button
                    onClick={handleGenerate}
                    disabled={running || !scopeState.valid}
                    className="w-full btn-primary flex items-center justify-center gap-2 py-2.5 disabled:opacity-40 disabled:cursor-not-allowed"
                >
                    {running ? (
                        <>
                            <Loader2 size={15} className="animate-spin" /> Processing…
                        </>
                    ) : (
                        <>
                            <Zap size={15} /> Generate Cues{countLabel}
                        </>
                    )}
                </button>

                {/* Start error */}
                {error && !progress && (
                    <div className="flex items-start gap-2 text-bad text-[11px] bg-bad/5 border border-bad/20 rounded-mx-sm px-3 py-2">
                        <AlertTriangle size={13} className="mt-0.5 shrink-0" />
                        {error}
                    </div>
                )}

                {/* Live progress */}
                <PhraseBatchProgress progress={progress} running={running} onCancel={cancel} />
            </div>
        </div>
    );
};

export default PhraseGeneratorView;
