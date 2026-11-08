import { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'react-hot-toast';
import { Loader2, Settings2 } from 'lucide-react';

import { fetchHubSettings, saveHubSettings } from './hubSettingsApi';

const Row = ({ label, hint, children }) => (
    <div className="flex items-center justify-between gap-3 py-1.5">
        <div className="min-w-0">
            <div className="text-[12px] text-ink-primary">{label}</div>
            {hint && <div className="text-[10.5px] text-ink-muted leading-snug">{hint}</div>}
        </div>
        <div className="shrink-0">{children}</div>
    </div>
);

export const Switch = ({ checked, onChange, disabled, title }) => (
    <button
        type="button"
        role="switch"
        aria-checked={!!checked}
        disabled={disabled}
        title={title}
        onClick={(e) => {
            e.stopPropagation();
            onChange(!checked);
        }}
        className={`relative w-7 h-4 rounded-full transition-colors disabled:opacity-40 ${
            checked ? 'bg-amber2' : 'bg-mx-card border border-line-subtle'
        }`}
    >
        <span
            className={`absolute top-1/2 -translate-y-1/2 w-3 h-3 rounded-full transition-all ${
                checked ? 'left-[14px] bg-black' : 'left-[2px] bg-ink-muted'
            }`}
        />
    </button>
);

/**
 * Gear button + popover with the hub's own settings. Every change saves at once
 * (no Save button) and `onSaved` lets the hub reload what the setting affects.
 */
const HubSettingsPopover = ({ onSaved }) => {
    const [open, setOpen] = useState(false);
    const [settings, setSettings] = useState(null);
    const [loadError, setLoadError] = useState('');
    const [savingKey, setSavingKey] = useState('');
    const [thresholdDraft, setThresholdDraft] = useState('');
    const rootRef = useRef(null);

    const load = useCallback(async () => {
        setLoadError('');
        try {
            const data = await fetchHubSettings();
            setSettings(data);
            setThresholdDraft(String(data.artist_view_threshold ?? 0));
        } catch (e) {
            console.error('[HubSettingsPopover] failed to load settings', e);
            setSettings(null);
            setLoadError('Settings could not be read — try again in a moment.');
        }
    }, []);

    useEffect(() => {
        if (open) load();
    }, [open, load]);

    useEffect(() => {
        if (!open) return undefined;
        const onDown = (e) => {
            if (rootRef.current && !rootRef.current.contains(e.target)) setOpen(false);
        };
        const onKey = (e) => {
            if (e.key === 'Escape') setOpen(false);
        };
        document.addEventListener('mousedown', onDown);
        document.addEventListener('keydown', onKey);
        return () => {
            document.removeEventListener('mousedown', onDown);
            document.removeEventListener('keydown', onKey);
        };
    }, [open]);

    const save = useCallback(
        async (key, value) => {
            if (!settings || settings[key] === value) return;
            setSavingKey(key);
            try {
                const next = await saveHubSettings({ [key]: value });
                setSettings(next);
                onSaved?.(key, next);
            } catch (e) {
                console.error('[HubSettingsPopover] failed to save setting', key, e);
                toast.error('Setting not saved — the settings file could not be updated.');
            } finally {
                setSavingKey('');
            }
        },
        [onSaved, settings]
    );

    const commitThreshold = () => {
        const parsed = Math.max(0, parseInt(thresholdDraft, 10) || 0);
        setThresholdDraft(String(parsed));
        save('artist_view_threshold', parsed);
    };

    return (
        <div ref={rootRef} className="relative">
            <button
                type="button"
                onClick={() => setOpen((v) => !v)}
                aria-expanded={open}
                title="Hub settings"
                className={`p-2 rounded-full transition-all border border-white/5 hover:bg-white/10 hover:text-amber2 ${
                    open ? 'text-amber2 bg-white/10' : 'text-ink-secondary'
                }`}
            >
                <Settings2 size={16} />
            </button>

            {open && (
                <div className="absolute right-0 top-full mt-2 w-80 z-50 rounded-xl border border-line-subtle bg-mx-panel shadow-2xl">
                    <div className="flex items-center gap-2 px-3.5 py-2 border-b border-line-subtle">
                        <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-ink-muted">
                            Hub settings
                        </span>
                        <div className="flex-1" />
                        {savingKey && <Loader2 size={12} className="animate-spin text-amber2" />}
                    </div>
                    <div className="px-3.5 py-2 divide-y divide-line-subtle">
                        {loadError ? (
                            <p className="py-2 text-[11.5px] text-ink-muted">{loadError}</p>
                        ) : !settings ? (
                            <div className="flex items-center gap-2 py-2 text-[11.5px] text-ink-muted">
                                <Loader2 size={12} className="animate-spin text-amber2" />
                                Loading…
                            </div>
                        ) : (
                            <>
                                <Row
                                    label="Min tracks per artist"
                                    hint="Artists with fewer tracks stay out of the lists."
                                >
                                    <input
                                        type="number"
                                        min="0"
                                        value={thresholdDraft}
                                        disabled={savingKey === 'artist_view_threshold'}
                                        onChange={(e) => setThresholdDraft(e.target.value)}
                                        onBlur={commitThreshold}
                                        onKeyDown={(e) => {
                                            if (e.key === 'Enter') commitThreshold();
                                        }}
                                        className="input-glass w-16 text-right text-[12px] py-1 px-2"
                                    />
                                </Row>
                                <Row
                                    label="Background sync"
                                    hint="Refreshes Auto/Review favourites while idle. Never downloads."
                                >
                                    <Switch
                                        checked={!!settings.artist_background_sync}
                                        disabled={savingKey === 'artist_background_sync'}
                                        onChange={(v) => save('artist_background_sync', v)}
                                    />
                                </Row>
                                <Row label="Download format" hint="For missing-track downloads.">
                                    <select
                                        value={settings.sc_download_format || 'auto'}
                                        disabled={savingKey === 'sc_download_format'}
                                        onChange={(e) => save('sc_download_format', e.target.value)}
                                        className="input-glass text-[12px] py-1 px-2"
                                    >
                                        <option value="auto">Auto (source)</option>
                                        <option value="aiff">AIFF</option>
                                    </select>
                                </Row>
                            </>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
};

export default HubSettingsPopover;
