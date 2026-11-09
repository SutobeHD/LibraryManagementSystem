/**
 * SettingsAnalysis — Analysis depth, ranking filter, library insight thresholds.
 */

import React, { useCallback } from 'react';
import { Sliders, Power, Info, User } from 'lucide-react';
import { Section, Field } from './SettingsControls';
import { ANALYSIS_DEPTH_OPTIONS } from '../analysisDepth';

const SettingsAnalysis = ({ settings, setSettings }) => {
    const set = useCallback(
        (key, value) => {
            setSettings((prev) => ({ ...prev, [key]: value }));
        },
        [setSettings]
    );

    return (
        <div className="space-y-6">
            <Section title="Analysis depth" icon={Sliders}>
                <p className="text-xs text-ink-muted">
                    What a track analysis computes. Default for every run; the Analyse dialog can
                    override it per run.
                </p>
                <div className="grid grid-cols-2 gap-3">
                    {ANALYSIS_DEPTH_OPTIONS.map((q) => (
                        <button
                            key={q.id}
                            onClick={() => set('analysis_depth', q.id)}
                            className={`flex flex-col items-center p-4 rounded-2xl border transition-all ${
                                settings.analysis_depth === q.id
                                    ? 'bg-amber2/20 border-amber2'
                                    : 'bg-mx-deepest/50 border-white/5 hover:border-white/20'
                            }`}
                        >
                            <span
                                className={`font-bold text-sm ${settings.analysis_depth === q.id ? 'text-white' : 'text-ink-secondary'}`}
                            >
                                {q.label}
                            </span>
                            <span className="text-[10px] text-ink-muted mt-1 text-center">
                                {q.sub}
                            </span>
                        </button>
                    ))}
                </div>
            </Section>

            <Section title="Ranking Mode" icon={Power}>
                <Field label="Default queue filter">
                    <select
                        value={settings.ranking_filter_mode || 'all'}
                        onChange={(e) => set('ranking_filter_mode', e.target.value)}
                        className="input-glass w-full"
                    >
                        <option value="all">All Tracks</option>
                        <option value="unrated">Unrated Only (0 Stars)</option>
                        <option value="untagged">Untagged Only (No Comments)</option>
                    </select>
                </Field>
            </Section>

            <Section title="Library Insights" icon={Info}>
                <div className="grid grid-cols-2 gap-4">
                    <Field label="Low quality threshold (kbps)">
                        <input
                            type="number"
                            min="0"
                            max="320"
                            value={settings.insights_bitrate_threshold || 320}
                            onChange={(e) =>
                                set('insights_bitrate_threshold', parseInt(e.target.value) || 0)
                            }
                            className="input-glass w-full"
                        />
                    </Field>
                    <Field label="Lost track play threshold">
                        <input
                            type="number"
                            min="0"
                            value={settings.insights_playcount_threshold || 0}
                            onChange={(e) =>
                                set('insights_playcount_threshold', parseInt(e.target.value) || 0)
                            }
                            className="input-glass w-full"
                        />
                    </Field>
                </div>
            </Section>

            <Section title="Artist View" icon={User}>
                <Field label="Min tracks to show artist">
                    <input
                        type="number"
                        min="0"
                        value={settings.artist_view_threshold || 0}
                        onChange={(e) =>
                            set('artist_view_threshold', parseInt(e.target.value) || 0)
                        }
                        className="input-glass w-32"
                    />
                </Field>
            </Section>
        </div>
    );
};

export default SettingsAnalysis;
