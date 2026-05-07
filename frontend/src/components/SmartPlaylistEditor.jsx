import React, { useState, useEffect } from 'react';
import api from '../api/api';
import toast from 'react-hot-toast';
import { X, Plus, Trash2, Sparkles } from 'lucide-react';

const FIELDS = [
    { id: '1', name: 'Title', kind: 'string' },
    { id: '2', name: 'Artist', kind: 'string' },
    { id: '3', name: 'Album', kind: 'string' },
    { id: '4', name: 'Genre', kind: 'string' },
    { id: '5', name: 'Comment', kind: 'string' },
    { id: '6', name: 'Play Count', kind: 'number' },
    { id: '7', name: 'Rating', kind: 'number' },
    { id: '8', name: 'BPM', kind: 'number' },
    { id: '9', name: 'Year', kind: 'number' },
    { id: '10', name: 'Date Added', kind: 'date' },
    { id: '11', name: 'Bitrate', kind: 'number' },
    { id: '12', name: 'Key', kind: 'string' },
    { id: '13', name: 'Duration (s)', kind: 'number' },
    { id: '15', name: 'Label', kind: 'string' },
];

const STRING_OPS = [
    { id: '1', name: 'is' },
    { id: '2', name: 'is not' },
    { id: '5', name: 'contains' },
    { id: '6', name: 'does not contain' },
    { id: '7', name: 'starts with' },
    { id: '8', name: 'ends with' },
];

const NUMBER_OPS = [
    { id: '1', name: '=' },
    { id: '2', name: '≠' },
    { id: '3', name: '>' },
    { id: '4', name: '<' },
    { id: '0', name: 'in range' },
];

const DATE_OPS = [
    { id: '3', name: 'within last' },
    { id: '4', name: 'older than' },
    { id: '0', name: 'in range' },
];

const DATE_UNITS = [
    { id: '1', name: 'days' },
    { id: '2', name: 'weeks' },
    { id: '3', name: 'months' },
];

const newCondition = () => ({
    Field: '8', Operator: '0', ValueLeft: '120', ValueRight: '130', ValueUnit: '0',
});

const SmartPlaylistEditor = ({ parentId = 'ROOT', existing = null, onClose, onSaved }) => {
    const [name, setName] = useState(existing?.name || '');
    const [logical, setLogical] = useState(existing?.criteria?.LogicalOperator || 'all');
    const [conditions, setConditions] = useState(existing?.criteria?.conditions || [newCondition()]);
    const [preview, setPreview] = useState(null);
    const [saving, setSaving] = useState(false);

    const fieldKindFor = (fid) => FIELDS.find(f => f.id === fid)?.kind || 'string';

    const opsFor = (fid) => {
        const k = fieldKindFor(fid);
        if (k === 'number') return NUMBER_OPS;
        if (k === 'date') return DATE_OPS;
        return STRING_OPS;
    };

    const updateCondition = (idx, patch) => {
        setConditions(prev => prev.map((c, i) => i === idx ? { ...c, ...patch } : c));
    };

    const removeCondition = (idx) => {
        setConditions(prev => prev.filter((_, i) => i !== idx));
    };

    const addCondition = () => setConditions(prev => [...prev, newCondition()]);

    const buildCriteria = () => ({
        LogicalOperator: logical,
        AutomaticUpdate: '1',
        conditions,
    });

    const save = async () => {
        if (!name.trim()) { toast.error('Name fehlt'); return; }
        if (!conditions.length) { toast.error('Mindestens eine Bedingung'); return; }
        setSaving(true);
        try {
            if (existing?.id) {
                await api.post('/api/playlists/smart/update', { pid: existing.id, criteria: buildCriteria() });
                toast.success('Smart-Playlist aktualisiert');
            } else {
                await api.post('/api/playlists/smart/create', { name, parent_id: parentId, criteria: buildCriteria() });
                toast.success('Smart-Playlist erstellt');
            }
            onSaved && onSaved();
        } catch (e) {
            toast.error('Speichern fehlgeschlagen: ' + (e.response?.data?.detail || e.message));
        } finally {
            setSaving(false);
        }
    };

    const runPreview = async () => {
        try {
            // For new playlists we have no pid yet — backend has no preview-by-criteria endpoint,
            // so we save+evaluate or use a temporary client-side hint here.
            if (existing?.id) {
                const res = await api.get(`/api/playlists/smart/${existing.id}/evaluate`);
                setPreview(res.data || []);
            } else {
                toast('Vorschau nach Speichern verfügbar.');
            }
        } catch (e) { toast.error('Preview fehlgeschlagen'); }
    };

    return (
        <div className="fixed inset-0 z-[150] bg-black/70 backdrop-blur-sm flex items-center justify-center p-6">
            <div className="bg-mx-shell border border-white/10 rounded-2xl shadow-2xl w-full max-w-2xl max-h-[85vh] overflow-y-auto">
                <div className="flex items-center justify-between p-5 border-b border-white/5">
                    <div className="flex items-center gap-3">
                        <Sparkles size={20} className="text-purple-400" />
                        <h2 className="text-lg font-bold text-white">{existing ? 'Smart Playlist bearbeiten' : 'Neue Smart Playlist'}</h2>
                    </div>
                    <button onClick={onClose} className="p-1.5 hover:bg-white/5 rounded text-ink-muted">
                        <X size={18} />
                    </button>
                </div>

                <div className="p-5 space-y-5">
                    {!existing && (
                        <div>
                            <label className="text-xs uppercase tracking-wider text-ink-muted">Name</label>
                            <input
                                value={name}
                                onChange={e => setName(e.target.value)}
                                placeholder="z.B. Peak-Time Tech-House"
                                className="w-full mt-1 bg-mx-card border border-white/10 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-purple-400/50"
                            />
                        </div>
                    )}

                    <div>
                        <label className="text-xs uppercase tracking-wider text-ink-muted">Verknüpfung</label>
                        <div className="flex gap-2 mt-1">
                            {['all', 'any'].map(v => (
                                <button
                                    key={v}
                                    onClick={() => setLogical(v)}
                                    className={`px-3 py-1.5 rounded-lg text-xs font-bold border transition-all ${
                                        logical === v
                                            ? 'bg-purple-500/20 text-purple-300 border-purple-500/40'
                                            : 'bg-mx-card border-white/10 text-ink-secondary hover:bg-white/5'
                                    }`}
                                >
                                    {v === 'all' ? 'Alle Bedingungen' : 'Mindestens eine'}
                                </button>
                            ))}
                        </div>
                    </div>

                    <div>
                        <label className="text-xs uppercase tracking-wider text-ink-muted">Bedingungen</label>
                        <div className="space-y-2 mt-2">
                            {conditions.map((c, i) => {
                                const ops = opsFor(c.Field);
                                const k = fieldKindFor(c.Field);
                                return (
                                    <div key={i} className="flex items-center gap-2 bg-mx-card border border-white/5 rounded-lg p-2">
                                        <select
                                            value={c.Field}
                                            onChange={e => updateCondition(i, { Field: e.target.value })}
                                            className="bg-mx-shell border border-white/10 rounded px-2 py-1 text-xs"
                                        >
                                            {FIELDS.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}
                                        </select>
                                        <select
                                            value={c.Operator}
                                            onChange={e => updateCondition(i, { Operator: e.target.value })}
                                            className="bg-mx-shell border border-white/10 rounded px-2 py-1 text-xs"
                                        >
                                            {ops.map(o => <option key={o.id} value={o.id}>{o.name}</option>)}
                                        </select>
                                        <input
                                            value={c.ValueLeft}
                                            onChange={e => updateCondition(i, { ValueLeft: e.target.value })}
                                            placeholder={k === 'date' ? '7' : 'Wert'}
                                            className="flex-1 bg-mx-shell border border-white/10 rounded px-2 py-1 text-xs"
                                        />
                                        {c.Operator === '0' && (
                                            <input
                                                value={c.ValueRight}
                                                onChange={e => updateCondition(i, { ValueRight: e.target.value })}
                                                placeholder="bis"
                                                className="w-20 bg-mx-shell border border-white/10 rounded px-2 py-1 text-xs"
                                            />
                                        )}
                                        {k === 'date' && (
                                            <select
                                                value={c.ValueUnit}
                                                onChange={e => updateCondition(i, { ValueUnit: e.target.value })}
                                                className="bg-mx-shell border border-white/10 rounded px-2 py-1 text-xs"
                                            >
                                                {DATE_UNITS.map(u => <option key={u.id} value={u.id}>{u.name}</option>)}
                                            </select>
                                        )}
                                        <button
                                            onClick={() => removeCondition(i)}
                                            className="p-1 text-red-400 hover:bg-red-500/10 rounded"
                                            title="Bedingung entfernen"
                                        >
                                            <Trash2 size={12} />
                                        </button>
                                    </div>
                                );
                            })}
                        </div>
                        <button
                            onClick={addCondition}
                            className="mt-2 flex items-center gap-2 px-3 py-1.5 text-xs bg-purple-500/10 border border-purple-500/30 text-purple-300 rounded-lg hover:bg-purple-500/20"
                        >
                            <Plus size={12} /> Bedingung hinzufügen
                        </button>
                    </div>

                    {preview && (
                        <div className="bg-mx-card border border-white/5 rounded-lg p-3">
                            <div className="text-xs text-ink-muted mb-2">{preview.length} Treffer</div>
                            <div className="max-h-32 overflow-y-auto text-xs space-y-1">
                                {preview.slice(0, 30).map((t, i) => (
                                    <div key={i} className="text-ink-secondary truncate">
                                        {t.Title || t.title} — {t.Artist || t.artist}
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                </div>

                <div className="flex justify-between p-5 border-t border-white/5">
                    <button
                        onClick={runPreview}
                        className="px-3 py-1.5 text-xs bg-mx-card border border-white/10 rounded-lg hover:bg-white/5"
                    >
                        Vorschau
                    </button>
                    <div className="flex gap-2">
                        <button
                            onClick={onClose}
                            className="px-3 py-1.5 text-xs bg-mx-card border border-white/10 rounded-lg hover:bg-white/5"
                        >
                            Abbrechen
                        </button>
                        <button
                            onClick={save}
                            disabled={saving}
                            className="px-4 py-1.5 text-xs bg-gradient-to-r from-purple-500 to-purple-600 text-white rounded-lg font-bold disabled:opacity-50"
                        >
                            {saving ? 'Speichern…' : 'Speichern'}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default SmartPlaylistEditor;
