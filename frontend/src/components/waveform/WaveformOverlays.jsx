import React, { useEffect } from 'react';
import { Scissors, X } from 'lucide-react';
import { HOT_CUE_COLORS } from './useWaveformInteractions';
import useTrackEditorState from './state/useTrackEditorState';
import { CDJ_MEMORY_COLORS, HOT_CUE_SURFACE_COLORS } from '../../config/constants';

function hexToRgba(hex, alpha) {
    const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex);
    if (!m) return `rgba(255, 215, 0, ${alpha})`;
    return `rgba(${parseInt(m[1], 16)}, ${parseInt(m[2], 16)}, ${parseInt(m[3], 16)}, ${alpha})`;
}

// Renders cue markers, beat-selection region, cut/insert/delete regions, drop marker, and loop
// region via the WaveSurfer Regions plugin (side-effect only). Also paints the floating cuts
// summary panel that sits inside the detail container.
export default function WaveformOverlays({
    wavesurfer,
    overviewWs,
    duration,
    simpleMode,
    bpm,
    beats,
    selectionStart,
    selectedBeats,
    isQuantized,
    cuts,
    setCuts,
    setCurrentTime,
    dropTime,
    hotCues,
    loopIn,
    loopOut,
    handleClear,
}) {
    // Slice 5 follow-up: also render the hook-driven cues + memory cues on
    // both the detail waveform and the overview minimap. Both data sources
    // coexist during dogfood; Slice 6 cleanup will retire the old useState
    // bag and the two sources will collapse.
    const { state: trackEditorState } = useTrackEditorState();
    const hookHotCues = trackEditorState?.hotCues || [];
    const hookMemoryCues = trackEditorState?.cues || [];

    // 2. Interactive Overlay Effect (Cues, Selection, Cuts) — writes into the Regions plugin.
    useEffect(() => {
        if (!wavesurfer.current || !duration) return;
        // Prefer the stashed `__regions` ref (set in useWaveSurfer) and fall
        // back to the `.plugins.find` lookup for backward compat.
        const regions =
            wavesurfer.current.__regions ||
            wavesurfer.current.plugins?.find(p => p.addRegion);
        const ovRegions =
            overviewWs.current?.__regions ||
            overviewWs.current?.plugins?.find(p => p.addRegion);
        if (!regions) return;

        // Clear existing interactive regions
        regions.getRegions().forEach(r => {
            if (
                r.id === 'selection-range' ||
                r.id.startsWith('cut-') ||
                r.id.startsWith('insert-') ||
                r.id.startsWith('delete-') ||
                r.id === 'drop-marker' ||
                r.id === 'active-loop' ||
                r.id.startsWith('cue-') ||
                r.id.startsWith('hook-cue-') ||
                r.id.startsWith('hook-mem-')
            ) {
                r.remove();
            }
        });

        if (ovRegions) {
            ovRegions.getRegions().forEach(r => {
                if (
                    r.id.startsWith('cue-ov-') ||
                    r.id === 'drop-marker-ov' ||
                    r.id === 'active-loop-ov' ||
                    r.id.startsWith('hook-cue-ov-') ||
                    r.id.startsWith('hook-mem-ov-')
                ) {
                    r.remove();
                }
            });
        }

        // 2. Render Selection Range (Beat Select)
        if (!simpleMode) {
            const beatDuration = 60 / bpm;
            let start = selectionStart;

            // Apply Quantize if enabled
            if (isQuantized && beats.length > 0) {
                const nearestBeat = beats.reduce((prev, curr) =>
                    Math.abs(curr.time - start) < Math.abs(prev.time - start) ? curr : prev
                );
                start = nearestBeat.time;
            }

            const selectionEnd = Math.min(start + (beatDuration * selectedBeats), duration);

            regions.addRegion({
                id: 'selection-range',
                start: start,
                end: selectionEnd,
                color: 'rgba(0, 204, 255, 0.4)',
                drag: true,
                resize: true,
                attributes: { label: 'selection' }
            });
        }

        // 3. Render Cuts
        cuts.forEach(cut => {
            let color = 'rgba(255, 152, 0, 0.3)'; // Default Clone
            let label = 'CLONE';
            if (cut.type === 'delete') {
                color = 'rgba(239, 68, 68, 0.4)'; // Red
                label = 'DELETE';
            }
            if (cut.type === 'insert') {
                color = 'rgba(34, 197, 94, 0.4)'; // Green
                label = 'INSERT';
            }

            regions.addRegion({
                id: cut.id,
                start: cut.start,
                end: cut.end,
                color: color,
                drag: true,
                resize: true,
                attributes: { label }
            });
        });

        // 4. Render Drop Marker
        if (dropTime) {
            regions.addRegion({
                id: 'drop-marker',
                start: dropTime,
                end: dropTime + 0.1,
                color: 'rgba(255, 0, 0, 0.6)',
                drag: false,
                resize: false,
                attributes: { label: 'DROP' }
            });

            if (ovRegions) {
                ovRegions.addRegion({
                    id: 'drop-marker-ov',
                    start: dropTime,
                    end: dropTime + 0.2,
                    color: 'rgba(255, 0, 0, 0.8)',
                    drag: false,
                    resize: false
                });
            }
        }

        // 5. Render Hot Cues
        hotCues.forEach(cue => {
            const color = HOT_CUE_COLORS[cue.HotCueNum - 1] || 'rgba(255, 255, 0, 0.8)';
            regions.addRegion({
                id: cue.ID.startsWith('cue-') ? cue.ID : `cue-${cue.ID}`,
                start: cue.InPoint,
                end: cue.InPoint + 0.1,
                color: color,
                drag: true,
                resize: false,
                attributes: { label: `CUE ${String.fromCharCode(64 + cue.HotCueNum)}` }
            });

            if (ovRegions) {
                ovRegions.addRegion({
                    id: `cue-ov-${cue.ID}`,
                    start: cue.InPoint,
                    end: cue.InPoint + 0.5,
                    color: color,
                    drag: false,
                    resize: false
                });
            }
        });

        // 6. Render Active Loop — on detail AND overview so the loop range
        //    is visible at the high-level view too.
        if (loopIn !== null && loopOut !== null) {
            regions.addRegion({
                id: 'active-loop',
                start: loopIn,
                end: loopOut,
                color: 'rgba(255, 255, 0, 0.2)',
                drag: true,
                resize: true,
                attributes: { label: 'LOOP' }
            });
            if (ovRegions) {
                ovRegions.addRegion({
                    id: 'active-loop-ov',
                    start: loopIn,
                    end: loopOut,
                    color: 'rgba(255, 255, 0, 0.32)',
                    drag: false,
                    resize: false,
                });
            }
        }

        // 7. Render NEW hot cues from the hook (Slice 1+).
        //    Wider band (0.25 s) on detail and thicker band (0.6 s) on
        //    overview so the markers are visible at any zoom level.
        //    `content` is the visible label (WaveSurfer v7 supports HTML).
        hookHotCues.forEach(cue => {
            const palette = HOT_CUE_SURFACE_COLORS.find(p => p.id === cue.color_id) || HOT_CUE_SURFACE_COLORS[0];
            const colorDetail = hexToRgba(palette.hex, 0.85);
            const colorOv = hexToRgba(palette.hex, 0.95);
            const start = (cue.time_ms || 0) / 1000;
            const letter = String.fromCharCode(64 + (cue.number || 1));
            regions.addRegion({
                id: `hook-cue-${cue.number}`,
                start,
                end: start + 0.25,
                color: colorDetail,
                drag: false,
                resize: false,
                content: letter,
                attributes: { label: letter, 'data-cue-kind': 'hot' },
            });
            if (ovRegions) {
                ovRegions.addRegion({
                    id: `hook-cue-ov-${cue.number}`,
                    start,
                    end: start + 0.6,
                    color: colorOv,
                    drag: false,
                    resize: false,
                });
            }
        });

        // 8. Render NEW memory cues from the hook (Slice 1+). Thinner band
        //    than hot cues so the two are visually distinguishable.
        hookMemoryCues.forEach(cue => {
            const palette = CDJ_MEMORY_COLORS.find(p => p.id === cue.color_id) || CDJ_MEMORY_COLORS[4];
            const colorDetail = hexToRgba(palette.hex, 0.7);
            const colorOv = hexToRgba(palette.hex, 0.85);
            const start = (cue.time_ms || 0) / 1000;
            regions.addRegion({
                id: `hook-mem-${cue.id}`,
                start,
                end: start + 0.15,
                color: colorDetail,
                drag: false,
                resize: false,
                attributes: { label: cue.name || 'M' },
            });
            if (ovRegions) {
                ovRegions.addRegion({
                    id: `hook-mem-ov-${cue.id}`,
                    start,
                    end: start + 0.45,
                    color: colorOv,
                    drag: false,
                    resize: false,
                });
            }
        });

    }, [selectionStart, selectedBeats, bpm, cuts, isQuantized, dropTime, hotCues, loopIn, loopOut, duration, beats, simpleMode, wavesurfer, overviewWs, hookHotCues, hookMemoryCues]);

    // Cuts summary floats inside the detail container — slotted in via the children-pass-through.
    if (cuts.length === 0) return null;
    return (
        <div className="absolute top-2 right-2 bg-black/85 backdrop-blur-md border border-white/10 rounded-lg p-2 text-[10px] font-mono text-ink-secondary w-[240px] max-h-[60%] overflow-y-auto">
            <div className="text-amber-400 font-bold mb-1.5 flex items-center justify-between">
                <span className="flex items-center gap-1"><Scissors size={10} /> {cuts.length} Edit{cuts.length === 1 ? '' : 's'}</span>
                <button
                    onClick={handleClear}
                    title="Clear all edits"
                    className="text-ink-muted hover:text-red-400 transition-colors px-1"
                >Clear</button>
            </div>
            {cuts.map(c => {
                const isDelete = c.type === 'delete';
                const jumpTime = isDelete ? c.start : (c.insertAt ?? c.start);
                return (
                    <div
                        key={c.id}
                        className="group flex items-center justify-between gap-1 py-0.5 hover:bg-white/5 rounded px-1 cursor-pointer"
                        onClick={() => { wavesurfer.current?.setTime(jumpTime); setCurrentTime(jumpTime); }}
                        title="Click to jump to this edit"
                    >
                        <span className={`truncate flex-1 ${isDelete ? 'text-red-400' : 'text-green-400'}`}>
                            {isDelete ? `DEL ${c.start.toFixed(1)}–${c.end.toFixed(1)}s` : `INS @${(c.insertAt ?? 0).toFixed(1)}s`}
                        </span>
                        <button
                            onClick={(e) => {
                                e.stopPropagation();
                                setCuts(prev => prev.filter(x => x.id !== c.id));
                            }}
                            title="Remove this edit"
                            className="opacity-40 group-hover:opacity-100 hover:text-red-400 transition-opacity"
                        >
                            <X size={11} />
                        </button>
                    </div>
                );
            })}
        </div>
    );
}
