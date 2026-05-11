/**
 * SettingsAudio — CPAL output device picker (Tauri-only enumeration).
 */

import React, { useState, useEffect, useCallback } from 'react';
import { Music } from 'lucide-react';
import { Section, Field } from './SettingsControls';

const SettingsAudio = ({ settings, setSettings }) => {
    const [audioDevices, setAudioDevices] = useState(['System Default']);

    const set = useCallback((key, value) => {
        setSettings(prev => ({ ...prev, [key]: value }));
    }, [setSettings]);

    // Enumerate CPAL audio devices (Tauri desktop only)
    useEffect(() => {
        if (window.__TAURI__) {
            import('@tauri-apps/api/core').then(({ invoke }) => {
                invoke('list_audio_devices')
                    .then(devices => setAudioDevices(devices))
                    .catch(e => console.warn('[Settings] list_audio_devices failed:', e));
            });
        }
    }, []);

    return (
        <div className="space-y-6">
            <Section title="Output Device" icon={Music}>
                <p className="text-xs text-ink-muted">
                    Select which audio output device the DAW playback engine uses.
                    Takes effect the next time a track is loaded.
                    {!window.__TAURI__ && <span className="block mt-1 text-amber-400">⚠ Device enumeration requires the desktop app (Tauri).</span>}
                </p>
                <Field label="Audio output">
                    <select
                        value={settings.audio_output_device || ''}
                        onChange={e => set('audio_output_device', e.target.value)}
                        className="input-glass w-full"
                    >
                        {audioDevices.map(d => (
                            <option key={d} value={d === 'System Default' ? '' : d}>{d}</option>
                        ))}
                    </select>
                </Field>
                {audioDevices.length === 1 && window.__TAURI__ && (
                    <p className="text-xs text-ink-muted italic">Only the system default was found. Check that your audio drivers are installed.</p>
                )}
            </Section>
        </div>
    );
};

export default SettingsAudio;
