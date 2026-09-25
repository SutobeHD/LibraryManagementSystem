/**
 * UsbSettingsView — edit MYSETTING.DAT / MYSETTING2.DAT / DJMMYSETTING.DAT
 *
 * Per-stick CDJ + DJM hardware settings (auto-cue level, jog mode, fader
 * curves, etc.). Schema is fetched from the backend so dropdown options stay
 * in sync if the upstream pyrekordbox enum tables grow.
 *
 * Layout:
 *   ┌ Device picker ───────────────────────────┐
 *   │ [Player] [Mixer]                        │  tabs
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
import React, { useEffect, useMemo, useState, useCallback, useRef } from 'react';
import { createPortal } from 'react-dom';
import { Save, RotateCcw, Sliders, HardDrive, Info, Loader2, AlertTriangle } from 'lucide-react';
import api from '../api/api';
import { useToast } from './ToastContext';
import { confirmModal } from './ConfirmModal';

// Logical tabs — each spans one or more Pioneer .DAT files. "Player" merges
// MYSETTING (core) + MYSETTING2 (the NXS2-era "extended" fields); Pioneer only
// splits them across two binaries for historical reasons, so we present them as
// one tab. Each field still routes to its own file on save (see `_fileId`).
const TABS = [
  {
    id: 'player',
    label: 'Player',
    sub: 'CDJ — Cues, Quantize, Tempo, Jog, Vinyl, Pads, Waveform, Display',
    files: ['MYSETTING', 'MYSETTING2'],
  },
  {
    id: 'mixer',
    label: 'Mixer',
    sub: 'DJM standalone mixer — Faders, Headphones, Mic, FX, MIDI',
    files: ['DJMMYSETTING'],
  },
];

const log = (level, msg, data) => console[level](`[UsbSettingsView] ${msg}`, data ?? '');

export default function UsbSettingsView() {
  const toast = useToast();
  const [schema, setSchema] = useState(null);            // shape: {available, files: {…}}
  const [devices, setDevices] = useState([]);            // detected USBs (from /api/usb/devices)
  const [profiles, setProfiles] = useState([]);          // saved profiles (from /api/usb/profiles)
  const [selectedDeviceId, setSelectedDeviceId] = useState('');
  const [activeTab, setActiveTab] = useState('player');
  const [values, setValues] = useState({});              // {MYSETTING: {auto_cue: "on", …}, …}
  const [dirty, setDirty] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const [reloadKey, setReloadKey] = useState(0);   // bump to re-run initial load
  const [slow, setSlow] = useState(false);         // true once load exceeds the slow-threshold

  // ── Initial load: schema (once) + device list ─────────────────────────────
  // Re-runnable via `reloadKey` (Retry button). A slow-threshold timer flips
  // `slow` so a stalled drive scan surfaces a Retry affordance instead of an
  // endless spinner.
  useEffect(() => {
    let cancelled = false;
    setSlow(false);
    const slowTimer = setTimeout(() => { if (!cancelled) setSlow(true); }, 8000);
    (async () => {
      setLoading(true);
      setError(null);
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
    return () => { cancelled = true; clearTimeout(slowTimer); };
  }, [reloadKey]);

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

  // Merge every file of the active tab into `group`-keyed buckets, tagging each
  // field with the file it belongs to (`_fileId`) so save still targets the
  // right .DAT. Shared group names (e.g. "Display" exists in both MYSETTING and
  // MYSETTING2) collapse into one card; insertion order is preserved.
  const groupedFields = useMemo(() => {
    const tab = TABS.find(t => t.id === activeTab);
    if (!tab || !schema?.files) return [];
    const groups = new Map();
    tab.files.forEach(fileId => {
      const fileSchema = schema.files[fileId];
      if (!fileSchema) return;
      fileSchema.fields.forEach(f => {
        if (!groups.has(f.group)) groups.set(f.group, []);
        groups.get(f.group).push({ ...f, _fileId: fileId });
      });
    });
    return Array.from(groups.entries()).map(([name, fields]) => ({ name, fields }));
  }, [schema, activeTab]);

  // ── Render guards ─────────────────────────────────────────────────────────
  if (error) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="mx-card p-6 max-w-md text-center">
          <AlertTriangle size={28} className="text-amber2 mx-auto mb-3" />
          <div className="text-ink-primary font-semibold mb-1">USB Settings unavailable</div>
          <div className="text-tiny text-ink-muted mb-4">{error}</div>
          <button
            onClick={() => setReloadKey(k => k + 1)}
            className="flex items-center gap-2 px-3 py-2 rounded-mx-sm text-tiny font-semibold border border-line-subtle text-ink-secondary hover:bg-mx-hover transition-all mx-auto"
          >
            <RotateCcw size={12} /> Retry
          </button>
        </div>
      </div>
    );
  }

  if (loading && !schema) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-3 text-center px-6">
        <Loader2 className="animate-spin text-amber2" size={28} />
        <div className="text-tiny text-ink-muted">Scanning USB drives…</div>
        {slow && (
          <div className="mt-1 max-w-xs flex flex-col items-center gap-3">
            <div className="text-tiny text-ink-muted">
              This is taking longer than usual — a disconnected or unreadable drive can stall the scan.
            </div>
            <button
              onClick={() => setReloadKey(k => k + 1)}
              className="flex items-center gap-2 px-3 py-2 rounded-mx-sm text-tiny font-semibold border border-line-subtle text-ink-secondary hover:bg-mx-hover transition-all"
            >
              <RotateCcw size={12} /> Retry
            </button>
          </div>
        )}
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
            onChange={async e => {
              const nextValue = e.target.value;
              if (dirty) {
                const ok = await confirmModal({
                  title: 'Unsaved changes',
                  message: 'You have unsaved changes. Discard?',
                  confirmLabel: 'Discard',
                });
                if (!ok) return;
              }
              setSelectedDeviceId(nextValue);
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

      {/* Tabs */}
      <div className="px-6 pt-3 flex-shrink-0">
        <div className="flex gap-1">
          {TABS.map(t => (
            <button
              key={t.id}
              onClick={() => setActiveTab(t.id)}
              className={`px-4 py-2 rounded-mx-sm text-tiny font-semibold transition-all border ${
                activeTab === t.id
                  ? 'bg-amber-500/15 border-amber-500/40 text-amber-300'
                  : 'border-line-subtle text-ink-secondary hover:bg-mx-hover'
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
        <p className="mx-caption mt-2">{TABS.find(t => t.id === activeTab)?.sub}</p>
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
                    key={`${f._fileId}:${f.key}`}
                    field={f}
                    value={values[f._fileId]?.[f.key] ?? f.default}
                    onChange={v => setField(f._fileId, f.key, v)}
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
      <HelpTooltip
        text={field.help}
        className={`flex-1 min-w-0 flex items-center gap-1 text-tiny text-ink-secondary ${field.help ? 'cursor-help' : ''}`}
      >
        <span className="truncate">{field.label}</span>
        {field.help && <Info size={10} className="shrink-0 text-ink-muted/50" />}
      </HelpTooltip>
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

// Hover/focus help bubble. Renders into a body-level portal with fixed
// positioning so it never gets clipped by the scrollable settings pane.
function HelpTooltip({ text, className = '', children }) {
  const [show, setShow] = useState(false);
  const [coords, setCoords] = useState({ top: 0, left: 0 });
  const ref = useRef(null);

  const reveal = useCallback(() => {
    const r = ref.current?.getBoundingClientRect();
    if (r) setCoords({ top: r.top - 8, left: r.left + r.width / 2 });
    setShow(true);
  }, []);
  const hide = useCallback(() => setShow(false), []);

  if (!text) return <span className={className}>{children}</span>;

  return (
    <span
      ref={ref}
      className={className}
      onMouseEnter={reveal}
      onMouseLeave={hide}
      onFocus={reveal}
      onBlur={hide}
      tabIndex={0}
    >
      {children}
      {show && createPortal(
        <div
          role="tooltip"
          style={{ top: coords.top, left: coords.left }}
          className="fixed z-[200] -translate-x-1/2 -translate-y-full max-w-[260px] px-2.5 py-1.5 rounded-mx-sm bg-mx-deepest border border-line-subtle text-[11px] leading-snug text-ink-secondary shadow-lg pointer-events-none whitespace-normal"
        >
          {text}
        </div>,
        document.body,
      )}
    </span>
  );
}
