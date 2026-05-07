/**
 * UsbSettingsView — edit MYSETTING.DAT / MYSETTING2.DAT / DJMMYSETTING.DAT
 *
 * Per-stick CDJ + DJM hardware settings (auto-cue level, jog mode, fader
 * curves, etc.). Schema is fetched from the backend so dropdown options stay
 * in sync if the upstream pyrekordbox enum tables grow.
 *
 * Layout:
 *   ┌ Device picker ───────────────────────────┐
 *   │ [Player] [Player+] [Mixer]              │  file tabs
 *   ├──────────────────────────────────────────┤
 *   │  Group: Auto Cue                        │
 *   │   Auto Cue          [On  ▼]             │
 *   │   Auto Cue Level    [Memory ▼]          │
 *   │  Group: Cues                            │
 *   │   …                                     │
 *   ├──────────────────────────────────────────┤
 *   │ [Reset to Defaults]            [Save] ──┤  sticky footer
 *   └──────────────────────────────────────────┘
 */
import React, { useEffect, useMemo, useState, useCallback } from 'react';
import { Save, RotateCcw, Sliders, HardDrive, Info, Loader2, AlertTriangle } from 'lucide-react';
import api from '../api/api';
import { useToast } from './ToastContext';

// File-tab label + descriptive subtitle for the panel header
const FILE_TABS = [
  { id: 'MYSETTING',    label: 'Player',          sub: 'CDJ — Cues, Quantize, Jog, Display' },
  { id: 'MYSETTING2',   label: 'Player Extended', sub: 'CDJ — Vinyl, Pads, Waveform, Beat Jump' },
  { id: 'DJMMYSETTING', label: 'Mixer',           sub: 'DJM — Faders, Headphones, Mic, FX, MIDI' },
];

const log = (level, msg, data) => console[level](`[UsbSettingsView] ${msg}`, data ?? '');

export default function UsbSettingsView() {
  const toast = useToast();
  const [schema, setSchema] = useState(null);            // shape: {available, files: {…}}
  const [devices, setDevices] = useState([]);            // detected USBs (from /api/usb/devices)
  const [profiles, setProfiles] = useState([]);          // saved profiles (from /api/usb/profiles)
  const [selectedDeviceId, setSelectedDeviceId] = useState('');
  const [activeFile, setActiveFile] = useState('MYSETTING');
  const [values, setValues] = useState({});              // {MYSETTING: {auto_cue: "on", …}, …}
  const [dirty, setDirty] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  // ── Initial load: schema (once) + device list ─────────────────────────────
  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const [schemaRes, devRes, profRes] = await Promise.all([
          api.get('/api/usb/mysettings/schema'),
          api.get('/api/usb/devices'),
          api.get('/api/usb/profiles'),
        ]);
        if (cancelled) return;
        if (!schemaRes.data?.available) {
          setError(schemaRes.data?.error || 'pyrekordbox unavailable on the backend');
          setLoading(false);
          return;
        }
        setSchema(schemaRes.data);
        const detected = devRes.data?.devices || devRes.data || [];
        const stored = profRes.data?.profiles || profRes.data || [];
        // Only USB-class devices, never the system drive
        const usbOnly = detected.filter(d => (d.type || '').toLowerCase() !== 'fixed');
        setDevices(usbOnly);
        setProfiles(stored);
        // Default selection: first connected device that has a profile
        const fallback = usbOnly[0]?.device_id || stored[0]?.device_id || '';
        setSelectedDeviceId(fallback);
        log('info', 'loaded', { devices: usbOnly.length, profiles: stored.length });
      } catch (exc) {
        log('error', 'initial load failed', exc);
        setError(exc.message || 'Failed to load USB settings');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  // ── Load values whenever the selected device changes ──────────────────────
  useEffect(() => {
    if (!selectedDeviceId || !schema) return;
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const res = await api.get(`/api/usb/mysettings/${selectedDeviceId}`);
        if (cancelled) return;
        setValues(res.data?.values || {});
        setDirty(false);
        log('info', 'values loaded', { device: selectedDeviceId });
      } catch (exc) {
        log('error', 'values load failed', exc);
        toast.error('Failed to read settings from stick');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [selectedDeviceId, schema, toast]);

  const setField = useCallback((fileId, key, value) => {
    setValues(prev => ({
      ...prev,
      [fileId]: { ...(prev[fileId] || {}), [key]: value },
    }));
    setDirty(true);
  }, []);

  const handleSave = useCallback(async () => {
    if (!selectedDeviceId) return;
    setSaving(true);
    try {
      const res = await api.post('/api/usb/mysettings', {
        device_id: selectedDeviceId,
        values,
      });
      log('info', 'saved', res.data);
      toast.success('Settings saved to stick');
      setDirty(false);
    } catch (exc) {
      log('error', 'save failed', exc);
      toast.error('Save failed: ' + (exc.response?.data?.detail || exc.message));
    } finally {
      setSaving(false);
    }
  }, [selectedDeviceId, values, toast]);

  const handleResetDefaults = useCallback(() => {
    if (!schema) return;
    const defaults = {};
    Object.entries(schema.files).forEach(([fid, fdata]) => {
      defaults[fid] = {};
      fdata.fields.forEach(f => { defaults[fid][f.key] = f.default; });
    });
    setValues(defaults);
    setDirty(true);
    toast.info('Defaults restored — click Save to write to stick');
  }, [schema, toast]);

  // Group fields of the active file by their `group` attribute, preserving
  // the schema's original ordering inside each group.
  const groupedFields = useMemo(() => {
    if (!schema?.files?.[activeFile]) return [];
    const groups = new Map();
    schema.files[activeFile].fields.forEach(f => {
      if (!groups.has(f.group)) groups.set(f.group, []);
      groups.get(f.group).push(f);
    });
    return Array.from(groups.entries()).map(([name, fields]) => ({ name, fields }));
  }, [schema, activeFile]);

  // ── Render guards ─────────────────────────────────────────────────────────
  if (error) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="mx-card p-6 max-w-md text-center">
          <AlertTriangle size={28} className="text-amber2 mx-auto mb-3" />
          <div className="text-ink-primary font-semibold mb-1">USB Settings unavailable</div>
          <div className="text-tiny text-ink-muted">{error}</div>
        </div>
      </div>
    );
  }

  if (loading && !schema) {
    return (
      <div className="h-full flex items-center justify-center">
        <Loader2 className="animate-spin text-amber2" size={28} />
      </div>
    );
  }

  if (devices.length === 0 && profiles.length === 0) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="mx-card p-6 max-w-md text-center">
          <HardDrive size={28} className="text-ink-muted mx-auto mb-3" />
          <div className="text-ink-primary font-semibold mb-1">No USB stick detected</div>
          <div className="text-tiny text-ink-muted">
            Plug in a USB drive — its profile will appear here automatically once it is initialised.
          </div>
        </div>
      </div>
    );
  }

  // Combined device list (detected + stored) deduped on device_id
  const allDevices = [...devices];
  profiles.forEach(p => {
    if (!allDevices.find(d => d.device_id === p.device_id)) {
      allDevices.push({ ...p, _offline: true });
    }
  });

  return (
    <div className="h-full flex flex-col">
      {/* Header — title + device picker */}
      <div className="px-6 py-4 border-b border-line-subtle flex-shrink-0">
        <div className="flex items-center gap-3 mb-3">
          <Sliders size={18} className="text-amber2" />
          <h1 className="text-lg font-semibold text-ink-primary">USB Hardware Settings</h1>
          <span className="text-tiny text-ink-muted">
            CDJ player &amp; DJM mixer behaviour, written into <code className="bg-mx-input px-1.5 py-0.5 rounded text-[10px]">PIONEER/MYSETTING*.DAT</code>
          </span>
        </div>
        <div className="flex items-center gap-3">
          <label className="mx-caption">Device</label>
          <select
            value={selectedDeviceId}
            onChange={e => {
              if (dirty && !confirm('You have unsaved changes. Discard?')) return;
              setSelectedDeviceId(e.target.value);
            }}
            className="input-glass min-w-[260px]"
          >
            {allDevices.map(d => (
              <option key={d.device_id} value={d.device_id}>
                {d.label || d.device_id} {d.drive ? `(${d.drive})` : ''} {d._offline ? '— offline' : ''}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* File tabs */}
      <div className="px-6 pt-3 flex-shrink-0">
        <div className="flex gap-1">
          {FILE_TABS.map(t => (
            <button
              key={t.id}
              onClick={() => setActiveFile(t.id)}
              className={`px-4 py-2 rounded-mx-sm text-tiny font-semibold transition-all border ${
                activeFile === t.id
                  ? 'bg-amber-500/15 border-amber-500/40 text-amber-300'
                  : 'border-line-subtle text-ink-secondary hover:bg-mx-hover'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
        <p className="mx-caption mt-2">{FILE_TABS.find(t => t.id === activeFile)?.sub}</p>
      </div>

      {/* Settings groups — scrollable */}
      <div className="flex-1 overflow-y-auto px-6 pt-3 pb-6">
        {loading ? (
          <div className="flex justify-center py-12">
            <Loader2 className="animate-spin text-amber2" size={24} />
          </div>
        ) : (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 max-w-5xl">
            {groupedFields.map(({ name, fields }) => (
              <SettingGroup key={name} name={name}>
                {fields.map(f => (
                  <SettingField
                    key={f.key}
                    field={f}
                    value={values[activeFile]?.[f.key] ?? f.default}
                    onChange={v => setField(activeFile, f.key, v)}
                  />
                ))}
              </SettingGroup>
            ))}
          </div>
        )}
      </div>

      {/* Footer — Reset + Save */}
      <div className="px-6 py-3 border-t border-line-subtle flex-shrink-0 flex items-center justify-between bg-mx-panel">
        <button
          onClick={handleResetDefaults}
          className="flex items-center gap-2 px-3 py-2 rounded-mx-sm text-tiny font-semibold border border-line-subtle text-ink-secondary hover:bg-mx-hover transition-all"
        >
          <RotateCcw size={12} /> Reset to Defaults
        </button>
        <div className="flex items-center gap-3">
          {dirty && <span className="text-tiny text-amber-400">Unsaved changes</span>}
          <button
            onClick={handleSave}
            disabled={!dirty || saving}
            className="flex items-center gap-2 px-4 py-2 rounded-mx-sm text-tiny font-semibold bg-amber2 text-black hover:bg-amber-400 disabled:opacity-40 disabled:cursor-not-allowed transition-all"
          >
            {saving ? <Loader2 className="animate-spin" size={12} /> : <Save size={12} />}
            {saving ? 'Saving…' : 'Save to Stick'}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Sub-components ────────────────────────────────────────────────────────

function SettingGroup({ name, children }) {
  return (
    <div className="mx-card p-4">
      <div className="mx-caption mb-2 text-amber-400/80">{name}</div>
      <div className="space-y-2">{children}</div>
    </div>
  );
}

function SettingField({ field, value, onChange }) {
  return (
    <div className="flex items-center gap-3">
      <label
        className="text-tiny text-ink-secondary flex-1 truncate"
        title={field.help}
      >
        {field.label}
        {field.help && (
          <Info size={10} className="inline ml-1 text-ink-muted/50" />
        )}
      </label>
      <select
        value={value || ''}
        onChange={e => onChange(e.target.value)}
        className="input-glass min-w-[140px] text-tiny"
      >
        {field.options.map(o => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  );
}
