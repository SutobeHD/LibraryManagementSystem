/**
 * SettingsExport — Default export folder, format defaults, Rekordbox bridge.
 */

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import api, { exportRekordboxXml, rekordboxXmlExportSummary } from '../../api/api';
import toast from 'react-hot-toast';
import { promptModal } from '../PromptModal';
import { FileOutput, FolderOpen, RefreshCw } from 'lucide-react';
import { Section, Field } from './SettingsControls';

/** Playlist tree -> picker rows in tree order; `depth` drives the indent. */
const flattenTree = (nodes, depth = 0, out = []) => {
    for (const n of nodes || []) {
        out.push({ node: n, depth });
        flattenTree(n.Children, depth + 1, out);
    }
    return out;
};

const SettingsExport = ({ settings, setSettings }) => {
    const set = useCallback(
        (key, value) => {
            setSettings((prev) => ({ ...prev, [key]: value }));
        },
        [setSettings]
    );

    const [playlistTree, setPlaylistTree] = useState([]);
    const [xmlScopeId, setXmlScopeId] = useState('');
    const [xmlExporting, setXmlExporting] = useState(false);

    useEffect(() => {
        api.get('/api/playlists/tree')
            .then((res) => setPlaylistTree(Array.isArray(res.data) ? res.data : []))
            .catch((err) => console.error('[SettingsExport] playlist tree load failed', err));
    }, []);

    const xmlScopeRows = useMemo(() => flattenTree(playlistTree), [playlistTree]);

    const handleXmlExport = async () => {
        const node = xmlScopeRows.find((r) => String(r.node.ID) === xmlScopeId)?.node ?? null;
        setXmlExporting(true);
        try {
            toast.success(rekordboxXmlExportSummary(await exportRekordboxXml(node)));
        } catch (err) {
            console.error('[SettingsExport] Rekordbox push failed', err);
            const detail = err.response?.data?.detail;
            toast.error(`Export failed${detail ? `: ${detail}` : ''}`);
        } finally {
            setXmlExporting(false);
        }
    };

    return (
        <div className="space-y-6">
            <Section title="Default Output Folder" icon={FolderOpen}>
                <p className="text-xs text-ink-muted">
                    Audio exports from the Waveform Editor go here unless you pick a different
                    folder per export. Empty = use the app's built-in{' '}
                    <span className="font-mono">./exports</span> directory.
                </p>
                <Field label="Default export folder">
                    <div className="flex gap-2">
                        <input
                            type="text"
                            value={settings.default_export_dir || ''}
                            onChange={(e) => set('default_export_dir', e.target.value)}
                            placeholder="e.g. <user_dir>\Music\Exports"
                            className="input-glass flex-1"
                        />
                        <button
                            type="button"
                            onClick={async () => {
                                try {
                                    const { open } = await import('@tauri-apps/plugin-dialog');
                                    const picked = await open({
                                        directory: true,
                                        multiple: false,
                                        title: 'Choose default export folder',
                                        defaultPath: settings.default_export_dir || undefined,
                                    });
                                    if (typeof picked === 'string' && picked.length) {
                                        set('default_export_dir', picked);
                                    }
                                } catch (err) {
                                    console.error('[Settings] folder picker failed', err);
                                    toast.error(
                                        'Folder picker unavailable in browser mode — type the path manually.'
                                    );
                                }
                            }}
                            className="px-3 py-2 rounded-lg text-xs bg-mx-shell/50 border border-white/10 hover:border-amber2/50 hover:bg-amber2/5 transition-all flex items-center gap-1.5"
                            title="Browse…"
                        >
                            <FolderOpen size={13} /> Browse
                        </button>
                    </div>
                </Field>
            </Section>

            <Section title="Format Defaults" icon={FileOutput}>
                <Field label="Default export format">
                    <select
                        value={settings.export_format}
                        onChange={(e) => set('export_format', e.target.value)}
                        className="input-glass w-full"
                    >
                        <option value="xml">Rekordbox XML</option>
                        <option value="m3u">M3U Playlist</option>
                        <option value="csv">CSV Spreadsheet</option>
                    </select>
                </Field>
                <div className="grid grid-cols-2 gap-4">
                    <Field label="Audio export bitrate">
                        <select
                            value={settings.export_bitrate || '320'}
                            onChange={(e) => set('export_bitrate', e.target.value)}
                            className="input-glass w-full"
                        >
                            <option value="128">128 kbps (MP3)</option>
                            <option value="192">192 kbps (MP3)</option>
                            <option value="256">256 kbps (AAC)</option>
                            <option value="320">320 kbps (MP3 – max)</option>
                            <option value="lossless">Lossless (WAV/FLAC)</option>
                        </select>
                    </Field>
                    <Field label="Sample rate">
                        <select
                            value={settings.export_sample_rate || '44100'}
                            onChange={(e) => set('export_sample_rate', e.target.value)}
                            className="input-glass w-full"
                        >
                            <option value="44100">44.1 kHz (CD quality)</option>
                            <option value="48000">48 kHz (broadcast)</option>
                            <option value="96000">96 kHz (studio)</option>
                        </select>
                    </Field>
                </div>
            </Section>

            <Section title="Rekordbox Bridge" icon={RefreshCw}>
                <p className="text-xs text-ink-muted">
                    Bi-directional sync with the Rekordbox XML library.
                </p>
                <Field label="XML export scope">
                    <select
                        value={xmlScopeId}
                        onChange={(e) => setXmlScopeId(e.target.value)}
                        className="input-glass w-full"
                    >
                        <option value="">Whole library</option>
                        {xmlScopeRows.map(({ node, depth }) => (
                            <option key={node.ID} value={String(node.ID)}>
                                {'\u00a0\u00a0'.repeat(depth)}
                                {node.Type === '0' ? `${node.Name} (folder)` : node.Name}
                            </option>
                        ))}
                    </select>
                </Field>
                <p className="text-xs text-ink-muted">
                    Writes <span className="font-mono">exports/&lt;name&gt;.xml</span> — a folder
                    exports its whole subtree. Streaming tracks have no local file and are skipped.
                </p>
                <div className="grid grid-cols-2 gap-3">
                    <button
                        onClick={handleXmlExport}
                        disabled={xmlExporting}
                        className="flex items-center justify-center gap-2 p-4 rounded-xl bg-mx-shell/50 border border-white/10 hover:border-amber2/50 hover:bg-amber2/5 transition-all text-sm disabled:opacity-50 disabled:cursor-wait"
                    >
                        <FileOutput size={16} className="text-amber2" /> Push to Rekordbox
                    </button>
                    <button
                        onClick={async () => {
                            const path = await promptModal({
                                title: 'Import from XML',
                                message: 'Rekordbox XML export path:',
                            });
                            if (!path) return;
                            try {
                                const res = await api.post('/api/rekordbox/import', {
                                    xml_path: path,
                                });
                                const notify =
                                    res.data.status === 'success' ? toast.success : toast.error;
                                notify(res.data.message || 'Import complete');
                            } catch (err) {
                                console.error('[SettingsExport] XML import failed', err);
                                toast.error(
                                    `Import failed: ${err?.response?.data?.detail || err.message}`
                                );
                            }
                        }}
                        className="flex items-center justify-center gap-2 p-4 rounded-xl bg-mx-shell/50 border border-white/10 hover:border-amber2/50 hover:bg-amber2/5 transition-all text-sm"
                    >
                        <RefreshCw size={16} className="text-amber2" /> Pull from Rekordbox
                    </button>
                </div>
            </Section>
        </div>
    );
};

export default SettingsExport;
