/**
 * SettingsUsb — Per-stick USB profile CRUD (label, type, audio format).
 *
 * Loads profiles lazily on mount (the parent only mounts this when the USB
 * tab is active) and writes through to /api/usb/profiles.
 */

import React, { useState, useEffect, useCallback } from 'react';
import api from '../../api/api';
import toast from 'react-hot-toast';
import { confirmModal } from '../ConfirmModal';
import {
    HardDrive, RefreshCw, Trash2, ChevronRight,
} from 'lucide-react';
import { Section, Field, Select } from './SettingsControls';

const USB_TYPE_LABELS = {
    MainCollection: 'Main Collection',
    Collection:     'Collection',
    PartCollection: 'Part Collection',
    SetStick:       'Set Stick',
};

const AUDIO_FORMATS = [
    { id: 'original', label: 'Original (no conversion)' },
    { id: 'mp3',      label: 'MP3' },
    { id: 'flac',     label: 'FLAC (lossless)' },
    { id: 'wav',      label: 'WAV (uncompressed)' },
    { id: 'aac',      label: 'AAC (m4a)' },
];

const BITRATES     = ['128', '192', '256', '320'];
const SAMPLE_RATES = ['44100', '48000', '96000'];

const SettingsUsb = () => {
    const [usbProfiles, setUsbProfiles] = useState([]);
    const [usbProfilesLoading, setUsbProfilesLoading] = useState(false);
    const [editingProfileId, setEditingProfileId] = useState(null);

    const loadUsbProfiles = useCallback(() => {
        setUsbProfilesLoading(true);
        api.get('/api/usb/profiles')
            .then(res => setUsbProfiles(Array.isArray(res.data) ? res.data : []))
            .catch(err => console.warn('[Settings/USB] load profiles failed', err))
            .finally(() => setUsbProfilesLoading(false));
    }, []);

    useEffect(() => {
        loadUsbProfiles();
    }, [loadUsbProfiles]);

    const updateUsbProfile = useCallback(async (profile, patch) => {
        try {
            const updated = { ...profile, ...patch };
            await api.post('/api/usb/profiles', updated);
            setUsbProfiles(prev => prev.map(p => p.device_id === profile.device_id ? updated : p));
            toast.success('Profile updated');
        } catch (err) {
            toast.error('Failed to update profile');
            console.error('[Settings/USB] update failed', err);
        }
    }, []);

    const deleteUsbProfile = useCallback(async (deviceId) => {
        if (!(await confirmModal({
            title: 'Delete USB profile?',
            message: 'Delete this USB profile? This does not affect the actual USB drive.',
            confirmLabel: 'Delete',
            danger: true,
        }))) return;
        try {
            await api.delete(`/api/usb/profiles/${deviceId}`);
            setUsbProfiles(prev => prev.filter(p => p.device_id !== deviceId));
            toast.success('Profile deleted');
        } catch {
            toast.error('Failed to delete profile');
        }
    }, []);

    return (
        <div className="space-y-4">
            <Section title="USB Export Profiles" icon={HardDrive}>
                <p className="text-tiny text-ink-muted mb-4">
                    Each USB stick has its own profile. Configure type and audio export format here.
                    Format settings are applied when files need conversion during sync.
                </p>

                {usbProfilesLoading ? (
                    <div className="text-tiny text-ink-muted py-4 text-center">Loading profiles…</div>
                ) : usbProfiles.length === 0 ? (
                    <div className="text-tiny text-ink-muted py-6 text-center">
                        No USB profiles yet. Plug in a USB stick and configure it from <strong>USB Export</strong>.
                    </div>
                ) : (
                    <div className="space-y-2">
                        {usbProfiles.map(profile => {
                            const isOpen = editingProfileId === profile.device_id;
                            return (
                                <div key={profile.device_id} className="bg-mx-input rounded-mx-sm border border-line-subtle">
                                    {/* Row header */}
                                    <button
                                        onClick={() => setEditingProfileId(isOpen ? null : profile.device_id)}
                                        className="w-full px-3 py-2.5 flex items-center justify-between text-left hover:bg-mx-hover transition-colors"
                                    >
                                        <div className="flex items-center gap-3 min-w-0 flex-1">
                                            <HardDrive size={14} className="text-amber2 shrink-0" />
                                            <div className="min-w-0 flex-1">
                                                <div className="text-[12px] font-medium text-ink-primary truncate">
                                                    {profile.label || profile.drive || profile.device_id.slice(0, 12)}
                                                </div>
                                                <div className="text-[10px] text-ink-muted truncate">
                                                    {USB_TYPE_LABELS[profile.type] || profile.type || 'Collection'}
                                                    {profile.drive && ` · ${profile.drive}`}
                                                </div>
                                            </div>
                                        </div>
                                        <div className="flex items-center gap-2">
                                            <span className="text-[10px] font-mono text-ink-muted px-2 py-0.5 bg-mx-deepest rounded">
                                                {profile.audio_format === 'original' || !profile.audio_format
                                                    ? 'Original'
                                                    : `${(profile.audio_format || '').toUpperCase()}${profile.audio_format && profile.audio_format !== 'flac' && profile.audio_format !== 'wav' ? ` ${profile.audio_bitrate || '320'}` : ''}`}
                                            </span>
                                            <ChevronRight size={12} className={`text-ink-muted transition-transform ${isOpen ? 'rotate-90' : ''}`} />
                                        </div>
                                    </button>

                                    {/* Edit form */}
                                    {isOpen && (
                                        <div className="px-3 py-3 border-t border-line-subtle space-y-3">
                                            {/* Label */}
                                            <Field label="Label">
                                                <input
                                                    type="text"
                                                    className="input-glass text-tiny w-full"
                                                    placeholder={profile.drive || 'Custom label'}
                                                    defaultValue={profile.label || ''}
                                                    onBlur={e => {
                                                        if (e.target.value !== (profile.label || '')) {
                                                            updateUsbProfile(profile, { label: e.target.value });
                                                        }
                                                    }}
                                                />
                                            </Field>

                                            {/* Type */}
                                            <Field label="Type">
                                                <Select
                                                    value={profile.type || 'Collection'}
                                                    onChange={v => updateUsbProfile(profile, { type: v })}
                                                    options={Object.entries(USB_TYPE_LABELS).map(([id, label]) => ({ id, label }))}
                                                />
                                            </Field>

                                            {/* Audio format */}
                                            <Field label="Audio Format">
                                                <Select
                                                    value={profile.audio_format || 'original'}
                                                    onChange={v => updateUsbProfile(profile, { audio_format: v })}
                                                    options={AUDIO_FORMATS.map(f => ({ id: f.id, label: f.label }))}
                                                />
                                            </Field>

                                            {/* Bitrate (only for lossy) */}
                                            {(profile.audio_format === 'mp3' || profile.audio_format === 'aac') && (
                                                <Field label="Bitrate (kbps)">
                                                    <Select
                                                        value={profile.audio_bitrate || '320'}
                                                        onChange={v => updateUsbProfile(profile, { audio_bitrate: v })}
                                                        options={BITRATES.map(b => ({ id: b, label: `${b} kbps` }))}
                                                    />
                                                </Field>
                                            )}

                                            {/* Sample rate (only when converting) */}
                                            {profile.audio_format && profile.audio_format !== 'original' && (
                                                <Field label="Sample Rate (Hz)">
                                                    <Select
                                                        value={profile.audio_sample_rate || '44100'}
                                                        onChange={v => updateUsbProfile(profile, { audio_sample_rate: v })}
                                                        options={SAMPLE_RATES.map(r => ({ id: r, label: `${r} Hz` }))}
                                                    />
                                                </Field>
                                            )}

                                            {/* Delete button */}
                                            <div className="pt-2 border-t border-line-subtle">
                                                <button
                                                    onClick={() => deleteUsbProfile(profile.device_id)}
                                                    className="text-[10px] text-rose-400 hover:text-rose-300 flex items-center gap-1.5 transition-colors"
                                                >
                                                    <Trash2 size={11} /> Remove profile
                                                </button>
                                            </div>
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                )}

                <button
                    onClick={loadUsbProfiles}
                    className="mt-4 text-tiny text-ink-muted hover:text-amber2 flex items-center gap-1.5 transition-colors"
                >
                    <RefreshCw size={11} /> Refresh
                </button>
            </Section>
        </div>
    );
};

export default SettingsUsb;
