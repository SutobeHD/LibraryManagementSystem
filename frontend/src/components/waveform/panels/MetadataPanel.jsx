/**
 * MetadataPanel — inline-edit Title / Artist / Album / Genre / BPM /
 * Key / Comment / Rating.
 *
 * Surface-agnostic: reads from useTrackEditorState. Mounted in
 * WaveformEditor and DjEditDaw behind FEATURE_METADATA_PANEL.
 *
 * Save path: POST /api/track/{tid} with the updated dict. The route
 * dual-writes to Rekordbox master.db (under _db_write_lock) and to ID3
 * tags in the source audio file (via app/audio_tags.py, gated by the
 * `write_tags_to_files` setting which defaults to true).
 *
 * Slice 4 of waveform-editor-extensions.
 */

import { useCallback, useEffect, useState } from 'react';
import { Save } from 'lucide-react';
import api from '../../../api/api';
import { useToast } from '../../ToastContext';
import { log } from '../../../utils/log';
import useTrackEditorState from '../state/useTrackEditorState';

const FIELDS = [
    { key: 'Title', label: 'Title', type: 'text' },
    { key: 'Artist', label: 'Artist', type: 'text' },
    { key: 'Album', label: 'Album', type: 'text' },
    { key: 'Genre', label: 'Genre', type: 'text' },
    { key: 'BPM', label: 'BPM', type: 'number', step: '0.01' },
    { key: 'Key', label: 'Key', type: 'text' },
    { key: 'Rating', label: 'Rating', type: 'number', min: '0', max: '5', step: '1' },
    { key: 'Comment', label: 'Comment', type: 'text' },
];

export default function MetadataPanel({ track }) {
    const toast = useToast();
    const { state, loadMetadata, updateMetadataFields } = useTrackEditorState();
    const { metadata } = state;
    const [isSaving, setIsSaving] = useState(false);
    const [savedTagStatus, setSavedTagStatus] = useState(null);

    useEffect(() => {
        if (!track?.id) return;
        loadMetadata({
            metadata: {
                Title: track.Title || '',
                Artist: track.Artist || '',
                Album: track.Album || '',
                Genre: track.Genre || '',
                BPM: track.BPM || 0,
                Key: track.Key || '',
                Rating: track.Rating || 0,
                Comment: track.Comment || '',
            },
        });
    }, [track?.id, track?.Title, track?.Artist, track?.Album, track?.Genre, track?.BPM, track?.Key, track?.Rating, track?.Comment, loadMetadata]);

    const handleSave = useCallback(async () => {
        if (!track?.id || !metadata) return;
        setIsSaving(true);
        setSavedTagStatus(null);
        try {
            const payload = {};
            for (const k of Object.keys(metadata)) {
                const v = metadata[k];
                if (v === '' || v === null || v === undefined) continue;
                payload[k] = v;
            }
            if (Object.keys(payload).length === 0) {
                toast.info('No changes to save');
                return;
            }
            const resp = await api.post(`/api/track/${track.id}`, payload);
            const tagStatus = resp.data?.file_tags || 'unknown';
            setSavedTagStatus(tagStatus);
            toast.success(`Metadata saved (ID3: ${tagStatus})`);
        } catch (err) {
            log.error('[MetadataPanel] save failed', err);
            toast.error('Failed to save metadata');
        } finally {
            setIsSaving(false);
        }
    }, [track?.id, metadata, toast]);

    if (!metadata) {
        return (
            <div className="bg-[#1a1a1a] border border-white/5 rounded-lg p-3 my-2 text-[10px] text-ink-muted">
                Load a track to edit its metadata.
            </div>
        );
    }

    return (
        <div className="bg-[#1a1a1a] border border-white/5 rounded-lg p-3 my-2">
            <div className="flex items-center justify-between mb-3">
                <h3 className="text-[11px] font-bold tracking-wider text-amber2">METADATA</h3>
                <div className="flex items-center gap-2">
                    {savedTagStatus && (
                        <span
                            className={`text-[9px] font-mono ${
                                savedTagStatus === 'written'
                                    ? 'text-green-400'
                                    : 'text-orange-400'
                            }`}
                            title="ID3 tag write-back status from the last save"
                        >
                            ID3: {savedTagStatus}
                        </span>
                    )}
                    <button
                        onClick={handleSave}
                        disabled={isSaving}
                        className="flex items-center gap-1.5 px-3 py-1 bg-amber2/20 border border-amber2/30 text-amber2 text-[10px] font-bold rounded hover:bg-amber2/30 disabled:opacity-50"
                    >
                        <Save size={12} />
                        {isSaving ? 'SAVING...' : 'SAVE'}
                    </button>
                </div>
            </div>

            <div className="grid grid-cols-2 gap-2">
                {FIELDS.map(({ key, label, type, ...rest }) => (
                    <div key={key} className="flex flex-col gap-0.5">
                        <label className="text-[9px] font-bold text-ink-muted uppercase">
                            {label}
                        </label>
                        <input
                            type={type}
                            value={metadata[key] ?? ''}
                            onChange={(e) =>
                                updateMetadataFields({
                                    [key]:
                                        type === 'number'
                                            ? parseFloat(e.target.value) || 0
                                            : e.target.value,
                                })
                            }
                            {...rest}
                            className="bg-[#0f0f0f] border border-white/10 text-[10px] text-white px-2 py-1 rounded outline-none focus:border-amber2/50"
                        />
                    </div>
                ))}
            </div>

            <div className="mt-3 text-[9px] text-ink-muted">
                Saves to Rekordbox <span className="font-mono">master.db</span> + ID3 tags in the
                audio file (per <span className="text-amber2">write_tags_to_files</span> setting).
            </div>
        </div>
    );
}
