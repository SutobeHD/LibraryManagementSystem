import React, { useState, useEffect } from 'react';
import api from '../api/api';
import toast from 'react-hot-toast';
import { confirmModal } from './ConfirmModal';
import { log } from '../utils/log';
import { Download, RefreshCw, Scissors, Copy, Wand2, Search, Check, X, Merge, Sparkles, Loader2, Eye, AlertTriangle } from 'lucide-react';

const RENAME_PATTERN_LS_KEY = 'rb-editor:smart-rename:last-pattern';
const DEFAULT_RENAME_PATTERN = '%Artist% - %Title% [%BPM%]';
const RENAME_TOKENS = ['%Artist%', '%Title%', '%BPM%', '%Key%'];

// Mirror of LibraryTools.smart_rename's token substitution + sanitisation,
// used for the client-side preview only. The backend remains the source of
// truth for the actual rename.
const buildRenameName = (track, pattern) => {
    const artist = track.Artist || '';
    const title = track.Title || '';
    const bpm = String(Math.round(Number(track.BPM) || 0));
    const key = track.Key || '';
    let name = pattern
        .replaceAll('%Artist%', artist)
        .replaceAll('%Title%', title)
        .replaceAll('%BPM%', bpm)
        .replaceAll('%Key%', key);
    // Match Python re.sub(r'[<>:"/\\|?*]', '', ...).strip()
    name = name.replace(/[<>:"/\\|?*]/g, '').trim();
    return name;
};

const ToolsView = () => {
    const [activeTab, setActiveTab] = useState('duplicates');
    const [duplicates, setDuplicates] = useState([]);
    const [selectedDuplicate, setSelectedDuplicate] = useState(null);
    const [compareTracks, setCompareTracks] = useState([]);
    const [scanning, setScanning] = useState(false);
    const [merging, setMerging] = useState(false);

    // Smart Rename State
    // Pattern is persisted to localStorage so the user doesn't retype it
    // between sessions. Default matches LibraryTools.smart_rename's token set.
    const [pattern, setPattern] = useState(() => {
        try {
            return localStorage.getItem(RENAME_PATTERN_LS_KEY) || DEFAULT_RENAME_PATTERN;
        } catch {
            return DEFAULT_RENAME_PATTERN;
        }
    });
    // TODO: ToolsView is not currently passed track-selection from a parent.
    // For now Smart Rename operates on ALL tracks in the library; the UI
    // makes this explicit and the confirm modal warns before any rename.
    const [allTracks, setAllTracks] = useState([]);
    const [tracksLoading, setTracksLoading] = useState(false);
    const [renamePreview, setRenamePreview] = useState([]); // { id, from, to, sameName }
    const [renamePreviewBuilt, setRenamePreviewBuilt] = useState(false);
    const [renameRunning, setRenameRunning] = useState(false);
    const [renameResult, setRenameResult] = useState(null); // { success, errors }

    // Comment Editor State
    const [playlists, setPlaylists] = useState([]);
    const [commentData, setCommentData] = useState({
        scope: "LIB", // "LIB" or PlaylistID
        action: "remove", // remove, replace, append, set
        find: "",
        replace: ""
    });
    const [commentProcessing, setCommentProcessing] = useState(false);

    // Fetch Playlists on Mount (for scope selector)
    useEffect(() => {
        api.get('/api/playlists/tree').then(res => setPlaylists(res.data)).catch(console.error);
    }, []);

    const handleSelectDuplicate = async (group) => {
        // ... (existing)
        setSelectedDuplicate(group);
        setCompareTracks([]);
        try {
            const promises = group.ids.map(id => api.get(`/api/track/${id}`));
            const responses = await Promise.all(promises);
            setCompareTracks(responses.map(r => r.data));
        } catch (e) { console.error("Failed to load tracks", e); }
    };

    const handleKeep = async (keepTrack) => {
        if (!selectedDuplicate) return;
        const keepId = String(keepTrack.ID || keepTrack.id);
        const removeIds = selectedDuplicate.ids.filter(id => String(id) !== keepId).map(String);

        if (removeIds.length === 0) return;
        if (!(await confirmModal({
            title: 'Merge duplicates',
            message: `Keep "${keepTrack.Title}" and merge ${removeIds.length} duplicate(s)? Playlist memberships will be transferred.`,
            confirmLabel: 'Merge',
        }))) return;

        setMerging(true);
        try {
            await api.post('/api/tools/duplicates/merge', { keep_id: keepId, remove_ids: removeIds });
            toast.success(`Merged: kept "${keepTrack.Title}", removed ${removeIds.length} duplicates`);
            setDuplicates(prev => prev.filter(d => d !== selectedDuplicate));
            setSelectedDuplicate(null);
            setCompareTracks([]);
        } catch (e) {
            console.error('Merge failed:', e);
            toast.error('Merge failed');
        }
        setMerging(false);
    };

    const handleSmartMerge = async (group) => {
        if (!group) return;
        // Pick the best track automatically (highest rating, bitrate)
        let bestTrack = compareTracks[0];
        let bestScore = -1;
        for (const t of compareTracks) {
            const score = ((t.Rating || 0) * 100) + (t.BitRate || t.Bitrate || 0);
            if (score > bestScore) { bestScore = score; bestTrack = t; }
        }
        if (bestTrack) await handleKeep(bestTrack);
    };

    const handleMergeAll = async () => {
        if (!(await confirmModal({
            title: 'Auto-merge all duplicates',
            message: `Auto-merge all ${duplicates.length} duplicate groups? This keeps the highest-quality version and transfers playlist memberships.`,
            confirmLabel: 'Auto-merge',
        }))) return;
        setMerging(true);
        try {
            const res = await api.post('/api/tools/duplicates/merge-all');
            toast.success(`Merged ${res.data.groups_merged} duplicate groups`);
            setDuplicates([]);
            setSelectedDuplicate(null);
            setCompareTracks([]);
        } catch (e) {
            toast.error('Merge all failed');
        }
        setMerging(false);
    };

    const findDuplicates = async () => {
        setScanning(true);
        try {
            const res = await api.get('/api/tools/duplicates');
            setDuplicates(res.data);
        } catch (e) { console.error(e); }
        finally { setScanning(false); }
    };

    // Persist pattern as the user edits it so a refresh / tab switch
    // doesn't blow away their work.
    useEffect(() => {
        try { localStorage.setItem(RENAME_PATTERN_LS_KEY, pattern); } catch (e) { log.warn('rename pattern persist failed', e); }
    }, [pattern]);

    // Lazy-load the track list the first time the user opens the Rename tab.
    useEffect(() => {
        if (activeTab !== 'rename') return;
        if (allTracks.length > 0 || tracksLoading) return;
        setTracksLoading(true);
        api.get('/api/library/tracks')
            .then(res => setAllTracks(Array.isArray(res.data) ? res.data : []))
            .catch(e => { log.error('failed to fetch library tracks for rename preview', e); toast.error('Could not load track list'); })
            .finally(() => setTracksLoading(false));
    }, [activeTab, allTracks.length, tracksLoading]);

    const insertToken = (token) => setPattern(prev => `${prev}${token}`);

    const handleRenamePreview = () => {
        if (!pattern.trim()) {
            toast.error('Pattern is empty');
            return;
        }
        if (allTracks.length === 0) {
            toast.error('No tracks loaded yet');
            return;
        }
        const rows = allTracks.map(t => {
            const tid = String(t.id || t.ID || '');
            const from = (t.path || t.FolderPath || '').split(/[\\/]/).pop() || `(track ${tid})`;
            const baseName = buildRenameName(t, pattern);
            // Preserve extension from current path so the preview is honest
            const ext = (from.includes('.') ? from.slice(from.lastIndexOf('.')) : '');
            const to = baseName ? `${baseName}${ext}` : '(empty)';
            return { id: tid, from, to, sameName: from === to };
        });
        setRenamePreview(rows);
        setRenamePreviewBuilt(true);
        setRenameResult(null);
    };

    const handleRenameApply = async () => {
        if (!pattern.trim()) { toast.error('Pattern is empty'); return; }
        if (allTracks.length === 0) { toast.error('No tracks loaded'); return; }
        const trackIds = allTracks
            .map(t => String(t.id || t.ID || ''))
            .filter(Boolean);
        if (trackIds.length === 0) { toast.error('No valid track IDs'); return; }
        if (!(await confirmModal({
            title: `Rename ${trackIds.length} tracks?`,
            message: `Every audio file in the library will be renamed on disk using:\n\n${pattern}\n\nThis modifies files outside this app and cannot be undone automatically. Make sure you have a backup.`,
            confirmLabel: 'Rename All',
            danger: true,
        }))) return;

        setRenameRunning(true);
        setRenameResult(null);
        try {
            const res = await api.post('/api/tools/rename', {
                track_ids: trackIds,
                pattern,
            });
            const success = Array.isArray(res.data?.success) ? res.data.success : [];
            const errors = Array.isArray(res.data?.errors) ? res.data.errors : [];
            setRenameResult({ success, errors });
            if (errors.length === 0) {
                toast.success(`Renamed ${success.length} tracks`);
            } else if (success.length === 0) {
                toast.error(`Rename failed (${errors.length} errors)`);
            } else {
                toast.success(`Renamed ${success.length} of ${trackIds.length} (${errors.length} errors)`);
            }
            log.info('smart_rename result', { success: success.length, errors });
        } catch (e) {
            log.error('rename request failed', e);
            toast.error('Rename request failed');
            setRenameResult({ success: [], errors: [String(e?.message || e)] });
        } finally {
            setRenameRunning(false);
        }
    };

    const handleCommentRun = async () => {
        if (!(await confirmModal({
            title: 'Modify comments',
            message: 'This will modify comments for all selected tracks. Continue?',
            confirmLabel: 'Continue',
        }))) return;
        setCommentProcessing(true);
        try {
            const res = await api.post('/api/tools/batch-comment', {
                source_id: commentData.scope,
                action: commentData.action,
                find: commentData.find,
                replace: commentData.replace
            });
            toast.success(`Updated comments for ${res.data.count} tracks!`);
        } catch (e) {
            console.error(e);
            toast.error("Update failed.");
        } finally {
            setCommentProcessing(false);
        }
    };

    // Flatten playlist tree for dropdown
    const flattenPlaylists = (nodes, depth = 0) => {
        if (!Array.isArray(nodes)) return [];
        let options = [];
        nodes.forEach(n => {
            if (n.Type === "1") options.push({ id: n.ID, name: n.Name, depth });
            if (n.children && n.children.length > 0) {
                options = [...options, ...flattenPlaylists(n.children, depth + 1)];
            }
        });
        return options;
    };
    const flatPlaylists = flattenPlaylists(playlists || []);

    return (
        <div className="h-full flex flex-col bg-transparent text-white overflow-hidden">
            <div className="p-8 pb-0">
                <div className="flex items-center gap-4 mb-8">
                    <div className="p-3 bg-fuchsia-500/20 rounded-xl">
                        <Wand2 size={32} className="text-fuchsia-400" />
                    </div>
                    <div>
                        <h1 className="text-3xl font-bold">Library Tools</h1>
                        <p className="text-ink-secondary">Advanced utilities to keep your library clean</p>
                    </div>
                </div>

                <div className="flex gap-6 border-b border-white/10">
                    <button
                        onClick={() => setActiveTab('duplicates')}
                        className={`pb-4 px-2 font-bold text-sm tracking-widest uppercase transition-all border-b-2 ${activeTab === 'duplicates' ? 'border-amber2 text-amber2' : 'border-transparent text-ink-muted hover:text-ink-primary'}`}
                    >
                        Duplicate Manager
                    </button>
                    <button
                        onClick={() => setActiveTab('rename')}
                        className={`pb-4 px-2 font-bold text-sm tracking-widest uppercase transition-all border-b-2 ${activeTab === 'rename' ? 'border-fuchsia-400 text-fuchsia-400' : 'border-transparent text-ink-muted hover:text-ink-primary'}`}
                    >
                        Smart Rename
                    </button>
                    <button
                        onClick={() => setActiveTab('comments')}
                        className={`pb-4 px-2 font-bold text-sm tracking-widest uppercase transition-all border-b-2 ${activeTab === 'comments' ? 'border-amber-400 text-amber-400' : 'border-transparent text-ink-muted hover:text-ink-primary'}`}
                    >
                        Mass Comment Editor
                    </button>
                </div>
            </div>

            <div className="flex-1 p-8 overflow-y-auto">
                <div className="max-w-6xl mx-auto h-full">
                    {/* DUPLICATES TAB */}
                    {activeTab === 'duplicates' && (
                        <div className="glass-panel p-6 rounded-2xl flex flex-col h-full animate-fade-in">
                            <div className="flex items-center justify-between mb-4">
                                <h2 className="text-xl font-bold flex items-center gap-2 text-amber2">
                                    <Copy size={20} /> Duplicate Manager
                                </h2>
                                {duplicates.length > 0 && (
                                    <button
                                        onClick={handleMergeAll}
                                        disabled={merging}
                                        className="flex items-center gap-2 px-4 py-2 bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-400 rounded-xl text-xs font-bold border border-emerald-500/30 transition-all disabled:opacity-50"
                                    >
                                        {merging ? <RefreshCw size={14} className="animate-spin" /> : <Merge size={14} />}
                                        Merge All ({duplicates.length} groups)
                                    </button>
                                )}
                            </div>

                            <div className="flex-1 flex gap-6 overflow-hidden">
                                {/* List */}
                                <div className="w-1/3 flex flex-col">
                                    <div className="flex-1 bg-black/20 rounded-xl mb-4 overflow-y-auto border border-white/5 p-2 scrollbar-hide">
                                        {!Array.isArray(duplicates) || duplicates.length === 0 ? (
                                            <div className="h-full flex flex-col items-center justify-center text-ink-muted">
                                                <Search size={48} className="mb-4 opacity-20" />
                                                <p>No duplicates found yet</p>
                                            </div>
                                        ) : (
                                            <div className="space-y-2">
                                                {duplicates.map((d, i) => (
                                                    <div
                                                        key={i}
                                                        onClick={() => handleSelectDuplicate(d)}
                                                        className={`p-3 rounded-lg border cursor-pointer transition-colors ${selectedDuplicate === d ? 'bg-amber2/20 border-amber2/50' : 'bg-white/5 border-white/5 hover:bg-white/10'}`}
                                                    >
                                                        <div className="flex justify-between items-start mb-1">
                                                            <div className="font-bold text-ink-primary truncate pr-2">{d.Title}</div>
                                                            <span className="text-[10px] bg-red-500/20 text-red-300 px-1.5 py-0.5 rounded flex-shrink-0">
                                                                {d.count || d.Count || '?'}x
                                                            </span>
                                                        </div>
                                                        <div className="text-xs text-ink-muted">{d.Artist}</div>
                                                    </div>
                                                ))}
                                            </div>
                                        )}
                                    </div>
                                    <button
                                        onClick={findDuplicates}
                                        disabled={scanning}
                                        className="btn-primary w-full flex justify-center items-center gap-2 py-3"
                                    >
                                        {scanning ? <RefreshCw className="animate-spin" /> : <Search />}
                                        {scanning ? "Scanning..." : "Scan for Duplicates"}
                                    </button>
                                </div>

                                {/* Detail / Compare View */}
                                <div className="flex-1 bg-black/40 rounded-xl border border-white/5 flex flex-col relative overflow-hidden">
                                    {selectedDuplicate && compareTracks.length > 0 ? (
                                        <div className="flex-1 flex flex-col p-4 animate-fade-in">
                                            <div className="flex justify-between items-center mb-4">
                                                <h3 className="text-lg font-bold text-ink-primary flex items-center gap-2"><Merge size={18} /> Compare & Merge</h3>
                                                <div className="flex items-center gap-2">
                                                    <button
                                                        onClick={() => handleSmartMerge(selectedDuplicate)}
                                                        disabled={merging}
                                                        className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-500/20 hover:bg-emerald-500/30 text-emerald-400 rounded-lg text-xs font-bold border border-emerald-500/30 transition-all disabled:opacity-50"
                                                    >
                                                        <Sparkles size={12} /> Smart Merge
                                                    </button>
                                                    <span className="text-xs text-ink-muted">or select one to keep →</span>
                                                </div>
                                            </div>
                                            <div className="flex-1 flex gap-4 overflow-x-auto pb-2">
                                                {compareTracks.map(t => (
                                                    <div key={t.id || t.ID} className="min-w-[240px] flex-1 bg-black/60 p-4 rounded-xl border border-white/10 flex flex-col relative group hover:border-white/20 transition-colors">
                                                        <div className="text-xs text-amber2 font-mono mb-2 truncate">{t.id || t.ID}</div>
                                                        <div className="font-bold text-lg leading-tight mb-1">{t.Title}</div>
                                                        <div className="text-sm text-ink-secondary mb-4">{t.Artist}</div>

                                                        <div className="space-y-2 text-xs text-ink-muted mb-6">
                                                            <div className="flex justify-between border-b border-white/5 pb-1"><span>BPM</span> <span className="text-ink-primary">{t.BPM?.toFixed?.(2) || t.BPM || '—'}</span></div>
                                                            <div className="flex justify-between border-b border-white/5 pb-1"><span>Key</span> <span className="text-ink-primary">{t.Key || '—'}</span></div>
                                                            <div className="flex justify-between border-b border-white/5 pb-1"><span>Rating</span> <span className="text-ink-primary">{'★'.repeat(t.Rating || 0)}{'☆'.repeat(5 - (t.Rating || 0))}</span></div>
                                                            <div className="flex justify-between border-b border-white/5 pb-1"><span>Size</span> <span className="text-ink-primary">{t.Size ? (t.Size / 1024 / 1024).toFixed(1) + ' MB' : '—'}</span></div>
                                                            <div className="flex justify-between border-b border-white/5 pb-1"><span>Bitrate</span> <span className="text-ink-primary">{t.BitRate || t.Bitrate || '—'}</span></div>
                                                            <div className="truncate mt-2 opacity-50" title={t.path || t.FolderPath}>{t.path || t.FolderPath || '—'}</div>
                                                        </div>

                                                        <div className="mt-auto">
                                                            <button
                                                                onClick={() => handleKeep(t)}
                                                                className="w-full btn-primary py-2 text-xs flex items-center justify-center gap-2 hover:bg-green-600 border-green-500/50"
                                                            >
                                                                <Check size={14} /> KEEP THIS
                                                            </button>
                                                        </div>
                                                    </div>
                                                ))}
                                            </div>
                                        </div>
                                    ) : (
                                        <div className="absolute inset-0 flex flex-col items-center justify-center text-ink-muted">
                                            <Merge size={64} className="mb-6 opacity-20" />
                                            <h3 className="text-xl font-bold text-ink-primary mb-2">Select a Duplicate Group</h3>
                                            <p className="max-w-md text-center text-sm px-8">Select a group from the list to compare tracks side-by-side and merge metadata.</p>
                                        </div>
                                    )}
                                </div>
                            </div>
                        </div>
                    )}

                    {/* RENAME TAB */}
                    {activeTab === 'rename' && (
                        <div className="glass-panel p-6 rounded-2xl flex flex-col h-full animate-fade-in">
                            <h2 className="text-xl font-bold mb-4 flex items-center gap-2 text-fuchsia-400">
                                <Scissors size={20} /> Smart Rename
                            </h2>

                            <div className="mb-4 flex items-start gap-2 px-3 py-2 bg-amber-500/10 border border-amber-500/30 rounded-lg">
                                <AlertTriangle size={14} className="text-amber-400 flex-shrink-0 mt-0.5" />
                                <p className="text-xs text-amber-200 leading-relaxed">
                                    Smart Rename currently operates on every track in the library. Files are renamed on disk and library links are rewritten — this cannot be undone automatically.
                                </p>
                            </div>

                            <div className="mb-4">
                                <label className="text-[10px] text-ink-muted uppercase font-bold mb-2 block tracking-widest leading-none">Pattern</label>
                                <input
                                    value={pattern}
                                    onChange={e => setPattern(e.target.value)}
                                    placeholder={DEFAULT_RENAME_PATTERN}
                                    className="input-glass w-full font-mono text-fuchsia-400"
                                />
                                <div className="flex flex-wrap items-center gap-2 mt-3">
                                    <span className="text-[10px] text-ink-muted uppercase font-bold tracking-widest">Tokens</span>
                                    {RENAME_TOKENS.map(tok => (
                                        <button
                                            key={tok}
                                            type="button"
                                            onClick={() => insertToken(tok)}
                                            className="px-2 py-1 bg-fuchsia-500/10 hover:bg-fuchsia-500/20 border border-fuchsia-500/30 text-fuchsia-300 text-[11px] font-mono rounded transition-colors"
                                        >
                                            {tok}
                                        </button>
                                    ))}
                                </div>
                            </div>

                            <div className="mb-4 flex items-center justify-between text-xs">
                                <div className="text-ink-muted">
                                    Affected: <span className="text-ink-primary font-bold">{tracksLoading ? '…' : allTracks.length}</span> tracks
                                </div>
                                <div className="flex items-center gap-2">
                                    <button
                                        type="button"
                                        onClick={handleRenamePreview}
                                        disabled={tracksLoading || allTracks.length === 0 || renameRunning}
                                        className="flex items-center gap-1.5 px-3 py-1.5 bg-white/5 hover:bg-white/10 text-ink-primary rounded-lg border border-white/10 transition-colors text-xs disabled:opacity-50 disabled:cursor-not-allowed"
                                    >
                                        <Eye size={12} /> Preview
                                    </button>
                                    <button
                                        type="button"
                                        onClick={handleRenameApply}
                                        disabled={tracksLoading || allTracks.length === 0 || renameRunning}
                                        className="flex items-center gap-1.5 px-3 py-1.5 bg-fuchsia-500/20 hover:bg-fuchsia-500/30 text-fuchsia-300 rounded-lg border border-fuchsia-500/40 transition-colors text-xs font-bold disabled:opacity-50 disabled:cursor-not-allowed"
                                    >
                                        {renameRunning ? <RefreshCw size={12} className="animate-spin" /> : <Wand2 size={12} />}
                                        {renameRunning ? 'Renaming…' : 'Rename All'}
                                    </button>
                                </div>
                            </div>

                            <div className="flex-1 bg-black/20 rounded-xl overflow-hidden border border-white/5 flex flex-col">
                                {tracksLoading ? (
                                    <div className="flex-1 flex items-center justify-center text-ink-muted">
                                        <Loader2 size={28} className="animate-spin opacity-50" />
                                    </div>
                                ) : !renamePreviewBuilt ? (
                                    <div className="flex-1 flex flex-col items-center justify-center text-ink-muted px-8 text-center">
                                        <Eye size={48} className="mb-4 opacity-20" />
                                        <p className="text-sm">Click <span className="text-fuchsia-300 font-bold">Preview</span> to see the first 5 renames before applying.</p>
                                    </div>
                                ) : (
                                    <div className="flex-1 overflow-y-auto p-3 space-y-2 scrollbar-hide">
                                        <div className="text-[10px] text-ink-muted uppercase font-bold tracking-widest mb-1 px-1">
                                            Preview (first 5 of {renamePreview.length})
                                        </div>
                                        {renamePreview.slice(0, 5).map((row, i) => (
                                            <div
                                                key={row.id || i}
                                                className={`flex items-center gap-3 px-3 py-2 rounded-lg border text-xs font-mono ${row.sameName ? 'bg-white/[0.02] border-white/5 text-ink-muted' : 'bg-fuchsia-500/5 border-fuchsia-500/20 text-ink-primary'}`}
                                            >
                                                <div className="flex-1 truncate" title={row.from}>{row.from}</div>
                                                <div className="text-fuchsia-400 flex-shrink-0">→</div>
                                                <div className="flex-1 truncate text-right" title={row.to}>{row.to}</div>
                                            </div>
                                        ))}
                                        {renamePreview.length > 5 && (
                                            <div className="text-[11px] text-ink-muted text-center pt-2">
                                                … and {renamePreview.length - 5} more
                                            </div>
                                        )}
                                        {renameResult && (
                                            <div className="mt-4 pt-4 border-t border-white/5 space-y-1">
                                                <div className="text-[10px] text-ink-muted uppercase font-bold tracking-widest">Last Result</div>
                                                <div className="text-xs text-emerald-400">{renameResult.success.length} succeeded</div>
                                                {renameResult.errors.length > 0 && (
                                                    <div className="text-xs text-red-400">{renameResult.errors.length} error(s):
                                                        <ul className="list-disc list-inside mt-1 space-y-0.5 text-ink-muted font-mono">
                                                            {renameResult.errors.slice(0, 5).map((err, idx) => (
                                                                <li key={idx} className="truncate" title={err}>{err}</li>
                                                            ))}
                                                            {renameResult.errors.length > 5 && <li>… and {renameResult.errors.length - 5} more</li>}
                                                        </ul>
                                                    </div>
                                                )}
                                            </div>
                                        )}
                                    </div>
                                )}
                            </div>
                        </div>
                    )}

                    {/* COMMENTS TAB */}
                    {activeTab === 'comments' && (
                        <div className="glass-panel p-6 rounded-2xl flex flex-col h-full animate-fade-in">
                            <h2 className="text-xl font-bold mb-6 flex items-center gap-2 text-amber-500">
                                Mass Comment Editor
                            </h2>

                            <div className="space-y-6 max-w-2xl">
                                {/* Scope */}
                                <div>
                                    <label className="text-[10px] text-ink-muted uppercase font-bold mb-2 block tracking-widest">Target Scope</label>
                                    <select
                                        value={commentData.scope}
                                        onChange={e => setCommentData({ ...commentData, scope: e.target.value })}
                                        className="input-glass w-full text-ink-primary"
                                    >
                                        <option value="LIB">Full Library (All Tracks)</option>
                                        {flatPlaylists.map(pl => (
                                            <option key={pl.id} value={pl.id}>
                                                {'\u00A0'.repeat(pl.depth * 2)} {pl.name}
                                            </option>
                                        ))}
                                    </select>
                                </div>

                                {/* Action */}
                                <div>
                                    <label className="text-[10px] text-ink-muted uppercase font-bold mb-2 block tracking-widest">Action</label>
                                    <div className="flex gap-4">
                                        {['remove', 'replace', 'append', 'set'].map(act => (
                                            <button
                                                key={act}
                                                onClick={() => setCommentData({ ...commentData, action: act })}
                                                className={`flex-1 py-2 rounded-lg border text-sm capitalize ${commentData.action === act ? 'bg-amber-500/20 border-amber-500/50 text-amber-400' : 'bg-black/20 border-white/5 text-ink-muted hover:bg-white/5'}`}
                                            >
                                                {act}
                                            </button>
                                        ))}
                                    </div>
                                </div>

                                {/* Inputs */}
                                <div className="grid grid-cols-2 gap-4">
                                    {(commentData.action === 'remove' || commentData.action === 'replace') && (
                                        <div className={`${commentData.action === 'remove' ? 'col-span-2' : ''}`}>
                                            <label className="text-[10px] text-ink-muted uppercase font-bold mb-2 block tracking-widest">Find Text</label>
                                            <input
                                                value={commentData.find}
                                                onChange={e => setCommentData({ ...commentData, find: e.target.value })}
                                                className="input-glass w-full"
                                                placeholder="Text to find..."
                                            />
                                        </div>
                                    )}
                                    {commentData.action !== 'remove' && (
                                        <div className={`${commentData.action === 'set' || commentData.action === 'append' ? 'col-span-2' : ''}`}>
                                            <label className="text-[10px] text-ink-muted uppercase font-bold mb-2 block tracking-widest">
                                                {commentData.action === 'replace' ? 'Replace With' : 'Content'}
                                            </label>
                                            <input
                                                value={commentData.replace}
                                                onChange={e => setCommentData({ ...commentData, replace: e.target.value })}
                                                className="input-glass w-full"
                                                placeholder="New content..."
                                            />
                                        </div>
                                    )}
                                </div>

                                {/* Button */}
                                <button
                                    onClick={handleCommentRun}
                                    disabled={commentProcessing}
                                    className="btn-primary w-full py-4 mt-8 bg-amber-600 hover:bg-amber-500 border-amber-500"
                                >
                                    {commentProcessing ? 'Processing...' : 'Apply Changes'}
                                </button>
                            </div>
                        </div>
                    )}

                </div>
            </div>
        </div>
    );
};
export default ToolsView;
