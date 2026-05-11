/**
 * SettingsAppearance — Waveform band colours, locale picker.
 */

import React, { useCallback } from 'react';
import { Palette, Globe } from 'lucide-react';
import { Section, Field } from './SettingsControls';

const SettingsAppearance = ({ settings, setSettings }) => {
    const set = useCallback((key, value) => {
        setSettings(prev => ({ ...prev, [key]: value }));
    }, [setSettings]);

    return (
        <div className="space-y-6">
            <Section title="Waveform Colors" icon={Palette}>
                <p className="text-xs text-ink-muted">
                    Custom colors for the 3-band waveform display (Low / Mid / High frequency bands).
                    Changes the palette across the DAW editor and overview.
                </p>
                <Field label="Color mode">
                    <select value={settings.waveform_visual_mode || 'custom'} onChange={e => set('waveform_visual_mode', e.target.value)} className="input-glass w-full">
                        <option value="blue">Standard Blue (monochrome)</option>
                        <option value="rgb">RGB Intensity (preset)</option>
                        <option value="3band">High Contrast 3-Band (preset)</option>
                        <option value="custom">Custom Colors (below)</option>
                    </select>
                </Field>
                <div className="grid grid-cols-3 gap-4">
                    {[
                        { key: 'waveform_color_low',  label: 'Low (Bass)', defaultColor: '#ef4444' },
                        { key: 'waveform_color_mid',  label: 'Mid',        defaultColor: '#22c55e' },
                        { key: 'waveform_color_high', label: 'High (Air)', defaultColor: '#3b82f6' },
                    ].map(({ key, label, defaultColor }) => (
                        <div key={key} className="flex flex-col items-center gap-2">
                            <label className="text-xs text-ink-secondary font-bold uppercase">{label}</label>
                            <div className="relative">
                                <input
                                    type="color"
                                    value={settings[key] || defaultColor}
                                    onChange={e => set(key, e.target.value)}
                                    className="w-14 h-14 rounded-xl border-0 cursor-pointer bg-transparent p-0.5"
                                    style={{ outline: `2px solid ${settings[key] || defaultColor}40` }}
                                />
                            </div>
                            <span className="text-[10px] text-ink-muted font-mono">{settings[key] || defaultColor}</span>
                        </div>
                    ))}
                </div>
                <div className="flex items-center gap-3 h-6 rounded-lg overflow-hidden border border-white/10">
                    <div className="flex-1 h-full" style={{ background: settings.waveform_color_low  || '#ef4444' }} />
                    <div className="flex-1 h-full" style={{ background: settings.waveform_color_mid  || '#22c55e' }} />
                    <div className="flex-1 h-full" style={{ background: settings.waveform_color_high || '#3b82f6' }} />
                </div>
            </Section>

            <Section title="Language" icon={Globe}>
                <div className="grid grid-cols-2 gap-3">
                    {[
                        { id: 'de', label: 'Deutsch', flag: '🇩🇪' },
                        { id: 'en', label: 'English',  flag: '🇬🇧' },
                    ].map(lang => (
                        <button
                            key={lang.id}
                            onClick={() => set('locale', lang.id)}
                            className={`flex items-center gap-3 p-4 rounded-2xl border transition-all ${
                                (settings.locale || 'de') === lang.id
                                    ? 'bg-amber2/20 border-amber2'
                                    : 'bg-mx-deepest/50 border-white/5 hover:border-white/20'}`}
                        >
                            <span className="text-2xl">{lang.flag}</span>
                            <span className={`font-bold text-sm ${(settings.locale || 'de') === lang.id ? 'text-white' : 'text-ink-secondary'}`}>{lang.label}</span>
                        </button>
                    ))}
                </div>
                <p className="text-xs text-ink-muted italic">Full i18n support is being rolled out progressively.</p>
            </Section>
        </div>
    );
};

export default SettingsAppearance;
