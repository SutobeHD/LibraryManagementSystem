/**
 * useEditorRegions - Region/palette/marker/zoom/snap/grid handlers.
 *
 * Thin wrappers around TimelineState + AudioRegion mutators that just need
 * `state`, `setState`, and `sourceBufferRef` to operate. Centralised here so
 * the container stays focused on composition.
 */

import { useCallback } from 'react';
import api from '../../api/api';
import { log } from '../../utils/log';
import {
    addRegion,
    removeRegion,
    updateRegion,
    setSelection,
    selectRegions,
    setPaletteSlot,
    findEmptyPaletteSlot,
    toggleSnap,
    shiftGrid,
    setZoom,
    pushHistory,
    undo,
    redo,
} from '../../audio/TimelineState';
import {
    createRegion,
    cloneRegion,
    splitRegion,
} from '../../audio/AudioRegion';

export default function useEditorRegions({
    state,
    setState,
    sourcePath,
    sourceBufferRef,
    track,
}) {
    // Region operations
    const handleRegionSelect = useCallback((regionId) => {
        setState(prev => selectRegions(prev, [regionId]));
    }, [setState]);

    const handleRegionMove = useCallback((regionId, newStart) => {
        setState(prev => updateRegion(prev, regionId, { timelineStart: newStart }));
    }, [setState]);

    const handleRegionResize = useCallback((regionId, side, delta) => {
        setState(prev => {
            const region = prev.regions.find(r => r.id === regionId);
            if (!region) return prev;

            if (side === 'left') {
                const newSourceStart = Math.max(0, region.sourceStart + delta);
                const newTimelineStart = region.timelineStart + delta;
                return updateRegion(prev, regionId, {
                    sourceStart: newSourceStart,
                    timelineStart: newTimelineStart
                });
            } else {
                const newSourceEnd = Math.min(
                    sourceBufferRef.current?.duration || region.sourceEnd,
                    region.sourceEnd + delta
                );
                return updateRegion(prev, regionId, { sourceEnd: newSourceEnd });
            }
        });
    }, [sourceBufferRef, setState]);

    const handleSplit = useCallback(() => {
        const selectedId = state.selectedRegionIds[0];
        if (!selectedId) return;

        const region = state.regions.find(r => r.id === selectedId);
        if (!region) return;

        const [left, right] = splitRegion(region, state.playhead);
        if (!right) return;

        setState(prev => {
            const newState = pushHistory(prev, { type: 'split', regionId: selectedId });
            const withoutOriginal = removeRegion(newState, selectedId);
            let final = addRegion(withoutOriginal, left);
            final = addRegion(final, right);
            return selectRegions(final, [right.id]);
        });
    }, [state.selectedRegionIds, state.regions, state.playhead, setState]);

    const handleCopy = useCallback(() => {
        const selectedId = state.selectedRegionIds[0];
        if (!selectedId) return;

        const region = state.regions.find(r => r.id === selectedId);
        if (!region) return;

        const slotIndex = findEmptyPaletteSlot(state);
        if (slotIndex === -1) return; // All slots full

        setState(prev => setPaletteSlot(prev, slotIndex, cloneRegion(region)));
    }, [state.selectedRegionIds, state.regions, state, setState]);

    const handleDelete = useCallback(() => {
        const selectedId = state.selectedRegionIds[0];
        if (!selectedId) return;

        setState(prev => {
            const newState = pushHistory(prev, { type: 'delete', regionId: selectedId });
            return removeRegion(newState, selectedId);
        });
    }, [state.selectedRegionIds, setState]);

    const handleUndo = useCallback(() => {
        setState(prev => undo(prev));
    }, [setState]);

    const handleRedo = useCallback(() => {
        setState(prev => redo(prev));
    }, [setState]);

    // Palette handlers
    const handlePaletteSlotDrop = useCallback((slotIndex, regionData) => {
        // Create a proper region from the dropped data
        const region = createRegion({
            sourceBuffer: sourceBufferRef.current,
            sourcePath: sourcePath,
            sourceStart: regionData.sourceStart,
            sourceEnd: regionData.sourceEnd,
            timelineStart: regionData.timelineStart,
            name: regionData.name,
            color: regionData.color
        });

        setState(prev => setPaletteSlot(prev, slotIndex, region));
    }, [sourcePath, sourceBufferRef, setState]);

    // Handle drop onto timeline from palette
    const handleTimelineDrop = useCallback((regionData, time) => {
        if (!sourceBufferRef.current) return;

        // Create new region from the dropped data + current source buffer
        const newRegion = createRegion({
            sourceBuffer: sourceBufferRef.current,
            sourcePath: sourcePath,
            sourceStart: regionData.sourceStart,
            sourceEnd: regionData.sourceEnd,
            timelineStart: time,
            name: regionData.name,
            color: regionData.color
        });

        setState(prev => {
            const newState = pushHistory(prev, { type: 'add', regionId: newRegion.id });
            return addRegion(newState, newRegion);
        });
    }, [sourcePath, sourceBufferRef, setState]);

    const handlePaletteDragStart = useCallback((slotIndex, region) => {
        // Could track which slot is being dragged
    }, []);

    const handlePaletteSlotClear = useCallback((slotIndex) => {
        setState(prev => setPaletteSlot(prev, slotIndex, null));
    }, [setState]);

    // Zoom handlers
    const handleZoomIn = useCallback(() => {
        setState(prev => setZoom(prev, Math.min(2000, prev.zoom * 1.5)));
    }, [setState]);

    const handleZoomOut = useCallback(() => {
        setState(prev => setZoom(prev, Math.max(10, prev.zoom / 1.5)));
    }, [setState]);

    const handleZoomChange = useCallback((newZoom) => {
        setState(prev => setZoom(prev, newZoom));
    }, [setState]);

    // Snap toggle
    const handleToggleSnap = useCallback(() => {
        setState(prev => toggleSnap(prev));
    }, [setState]);

    // Selection change
    const handleSelectionChange = useCallback((start, end) => {
        setState(prev => setSelection(prev, start, end));
    }, [setState]);

    // Marker operations
    const addMarker = useCallback((type, num = -1) => {
        const time = state.playhead;
        const newMarker = {
            Name: type === 4 ? 'LOOP' : (num >= 0 ? `HOT CUE ${String.fromCharCode(65 + num)}` : 'MEMORY CUE'),
            Type: type,
            Start: time,
            Num: num,
            Red: type === 4 ? 0 : 239,
            Green: type === 4 ? 255 : 68,
            Blue: type === 4 ? 0 : 68
        };

        if (type === 4 && state.selection) {
            newMarker.Start = state.selection.start;
            newMarker.End = state.selection.end;
        }

        setState(prev => ({
            ...prev,
            markers: [...(prev.markers || []), newMarker]
        }));
    }, [state.playhead, state.selection, setState]);

    const handleNormalize = useCallback(() => {
        // Placeholder for normalization logic
        log.debug('Normalize clicked!');
        // This would typically involve analyzing the audio buffer and applying gain
        // to reach a target loudness/peak level.
        // For now, it's just a console log.
    }, []);

    const handleGridAdjust = useCallback((delta) => {
        setState(prev => shiftGrid(prev, delta));
    }, [setState]);

    const toggleGridMode = useCallback(() => {
        const newMode = state.editMode === 'grid' ? 'select' : 'grid';
        setState(prev => ({ ...prev, editMode: newMode }));
    }, [state.editMode, setState]);

    const handleSaveGrid = useCallback(async () => {
        if (!track?.id) return;
        try {
            await api.post('/api/track/grid/save', {
                track_id: track.id,
                beat_grid: state.beatGrid,
            });
            log.debug('Grid saved successfully');
        } catch (err) {
            console.error('Failed to save grid:', err);
        }
    }, [track?.id, state.beatGrid]);

    return {
        // Region ops
        handleRegionSelect,
        handleRegionMove,
        handleRegionResize,
        handleSplit,
        handleCopy,
        handleDelete,
        handleUndo,
        handleRedo,
        // Palette ops
        handlePaletteSlotDrop,
        handleTimelineDrop,
        handlePaletteDragStart,
        handlePaletteSlotClear,
        // Zoom + snap + selection
        handleZoomIn,
        handleZoomOut,
        handleZoomChange,
        handleToggleSnap,
        handleSelectionChange,
        // Markers
        addMarker,
        handleNormalize,
        // Grid
        handleGridAdjust,
        toggleGridMode,
        handleSaveGrid,
    };
}
