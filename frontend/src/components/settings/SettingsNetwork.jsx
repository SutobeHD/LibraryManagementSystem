/**
 * SettingsNetwork — HTTP proxy, SoundCloud sync target, backend restart.
 *
 * The hidden "expert" toggle stays here (5x click on the muted dot reveals
 * the aggressive-download switch — same as before).
 */

import React, { useCallback } from 'react';
import api from '../../api/api';
import toast from 'react-hot-toast';
import { Wifi, Globe, RefreshCw, Power } from 'lucide-react';
import { Toggle, Section, Field } from './SettingsControls';

const SettingsNetwork = ({ settings, setSettings }) => {
    const set = useCallback((key, value) => {
        setSettings(prev => ({ ...prev, [key]: value }));
    }, [setSettings]);

    return (
        <div className="space-y-6">
            <Section title="HTTP Proxy" icon={Wifi}>
                <p className="text-xs text-ink-muted">
                    For users behind corporate firewalls. Applied to all SoundCloud API calls.
                    Format: <code className="text-amber2 text-[11px]">http://user:pass@proxy.example.com:8080</code>
                </p>
                <Field label="Proxy URL (leave empty to disable)">
                    <input
                        type="text"
                        value={settings.http_proxy || ''}
                        onChange={e => set('http_proxy', e.target.value)}
                        placeholder="http://proxy.company.com:8080"
                        className="input-glass w-full font-mono text-sm"
                    />
                </Field>
            </Section>

            <Section title="SoundCloud Sync" icon={Globe}>
                <Field label="Target folder ID for synced playlists">
                    <input
                        type="text"
                        value={settings.sc_sync_folder_id || ''}
                        onChange={e => set('sc_sync_folder_id', e.target.value)}
                        placeholder="ROOT (or library folder ID)"
                        className="input-glass w-full"
                    />
                </Field>
                <p className="text-xs text-ink-muted">Leave empty to create SC_ playlists at the root level.</p>

                <Field label="Download Format">
                    <select
                        value={settings.sc_download_format || 'auto'}
                        onChange={e => set('sc_download_format', e.target.value)}
                        className="input-glass w-full"
                    >
                        <option value="auto">Auto — keep source codec (mp3/m4a/wav/flac)</option>
                        <option value="aiff">AIFF — uncompressed PCM (lossless re-container)</option>
                    </select>
                </Field>
                <p className="text-xs text-ink-muted">
                    AIFF re-wraps the source as PCM. No further quality loss vs. the served stream,
                    but lossy sources (SC's MP3/AAC) stay lossy — files just become bigger and DJ-app friendly.
                </p>

                {/* Hidden expert toggle — reveal via 5x logo click on the section title */}
                {settings._sc_expert_revealed && (
                    <div className="mt-4 p-3 rounded-lg border border-red-500/20 bg-red-500/5">
                        <Toggle
                            checked={!!settings.sc_aggressive_mode}
                            onChange={v => set('sc_aggressive_mode', v)}
                            label="Aggressive Download Mode"
                        />
                        <p className="text-[10px] text-red-300/70 mt-1.5 leading-relaxed">
                            Bypasses streaming-rights gate. Accepts snipped/preview transcodings
                            and any signing path SC exposes — same approach as the soundcloud-dl
                            extension. <strong>Use only for tracks you have a personal right to
                            download.</strong> Output may sometimes be a 30s preview when SC
                            doesn't expose more — registry surfaces file size for transparency.
                        </p>
                    </div>
                )}
                <button
                    onClick={() => {
                        const c = (settings._sc_expert_clicks || 0) + 1;
                        set('_sc_expert_clicks', c);
                        if (c >= 5) set('_sc_expert_revealed', true);
                    }}
                    className="text-[9px] text-ink-placeholder/40 hover:text-ink-placeholder mt-2 select-none"
                    title=""
                >
                    {settings._sc_expert_revealed ? '· · ·' : '·'}
                </button>
            </Section>

            <Section title="System" icon={Power}>
                <button
                    onClick={async () => {
                        try {
                            await api.post('/api/system/restart');
                            toast.success('Backend restarting…');
                        } catch { toast.error('Restart failed'); }
                    }}
                    className="text-xs border border-amber-500/20 hover:border-amber-500/40 bg-amber-500/5 hover:bg-amber-500/10 text-amber-400 rounded-xl px-4 py-2.5 flex items-center gap-2 transition-all"
                >
                    <RefreshCw size={14} /> Restart Backend Service
                </button>
            </Section>
        </div>
    );
};

export default SettingsNetwork;
