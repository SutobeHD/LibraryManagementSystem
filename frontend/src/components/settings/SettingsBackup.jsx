/**
 * SettingsBackup — Retention policy, auto-backup intervals, cleanup.
 */

import React, { useCallback } from 'react';
import api from '../../api/api';
import toast from 'react-hot-toast';
import { HardDrive, Save, Trash2 } from 'lucide-react';
import { Toggle, Section, Field } from './SettingsControls';

const SettingsBackup = ({ settings, setSettings }) => {
    const set = useCallback((key, value) => {
        setSettings(prev => ({ ...prev, [key]: value }));
    }, [setSettings]);

    const triggerBackup = async () => {
        try {
            const res = await api.post('/api/library/backup');
            if (res.data.status === 'success') {
                toast.success('Backup created');
            } else if (res.data.status === 'unchanged') {
                toast('No changes to backup', { icon: '📋' });
            } else {
                toast.error('Backup failed: ' + (res.data.message || 'Unknown error'));
            }
        } catch (err) {
            console.error('[SettingsBackup] trigger failed', err);
            toast.error('Backup error');
        }
    };

    return (
        <div className="space-y-6">
            <Section title="Retention" icon={HardDrive}>
                <Field label="Keep backups for (days)">
                    <input
                        type="number" min="1" max="365"
                        value={settings.backup_retention_days}
                        onChange={e => set('backup_retention_days', parseInt(e.target.value) || 7)}
                        className="input-glass w-32"
                    />
                </Field>
                <Field label="Archive frequency">
                    <select value={settings.archive_frequency || 'daily'} onChange={e => set('archive_frequency', e.target.value)} className="input-glass w-full">
                        <option value="off">Off (session snapshots only)</option>
                        <option value="daily">Daily</option>
                        <option value="weekly">Weekly</option>
                        <option value="monthly">Monthly</option>
                    </select>
                </Field>
            </Section>

            <Section title="Auto-Backup" icon={Save}>
                <Toggle
                    checked={settings.auto_backup}
                    onChange={v => set('auto_backup', v)}
                    label="Auto-backup on launch"
                    sub="Creates a snapshot every time the app starts"
                />
                <Field label="Background interval">
                    <div className="flex items-center gap-3">
                        <select
                            value={settings.auto_backup_interval_min}
                            onChange={e => set('auto_backup_interval_min', parseInt(e.target.value))}
                            className="input-glass w-48"
                        >
                            <option value={0}>Off (manual only)</option>
                            <option value={15}>Every 15 minutes</option>
                            <option value={30}>Every 30 minutes</option>
                            <option value={60}>Every hour</option>
                            <option value={120}>Every 2 hours</option>
                        </select>
                        <span className="text-xs text-ink-muted">while the app is open</span>
                    </div>
                </Field>
                <button
                    onClick={triggerBackup}
                    className="text-xs border border-white/10 hover:border-amber2/40 bg-mx-shell/50 hover:bg-amber2/5 text-ink-primary hover:text-white rounded-xl px-4 py-2.5 flex items-center gap-2 transition-all"
                >
                    <Save size={14} /> Create Backup Now
                </button>
            </Section>

            <Section title="Cleanup" icon={Trash2}>
                <p className="text-xs text-ink-muted">Removes backup snapshots older than the retention window.</p>
                <button
                    onClick={async () => {
                        try {
                            const res = await api.post('/api/system/cleanup');
                            const data = res.data || {};
                            const total = (data.deleted_legacy || 0) + (data.deleted_commits || 0);
                            const freedMb = ((data.freed_bytes || 0) / 1048576).toFixed(1);
                            if (total === 0) {
                                toast('No backups older than retention window', { icon: '🧹' });
                            } else {
                                toast.success(`Removed ${total} backup${total === 1 ? '' : 's'} (${freedMb} MB freed)`);
                            }
                        } catch (err) {
                            console.error('[SettingsBackup] cleanup failed', err);
                            toast.error('Cleanup failed');
                        }
                    }}
                    className="text-xs border border-red-500/20 hover:border-red-500/40 bg-red-500/5 hover:bg-red-500/10 text-red-400 rounded-xl px-4 py-2.5 flex items-center gap-2 transition-all"
                >
                    <Trash2 size={14} /> Clean Old Backups
                </button>
            </Section>
        </div>
    );
};

export default SettingsBackup;
