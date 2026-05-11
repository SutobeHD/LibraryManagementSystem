/**
 * regionsReducer — region create / split / move / delete / resize / clipboard.
 *
 * Owns: regions[], clipboard[], clipboardSpan, and the cross-cutting
 * selectedRegionIds writes that happen as a side effect of region
 * mutations (e.g. REMOVE_REGION drops the deleted id from the set,
 * PASTE_INSERT replaces the selection with the freshly pasted ids).
 */

import { log } from '../../utils/log';
import { normalizeRegion, normalizeRegions } from './helpers';

/**
 * Region-domain reducer. Returns `state` unchanged for actions it
 * doesn't own — the barrel composes this with the other sub-reducers.
 *
 * @param {Object} state
 * @param {Object} action
 * @returns {Object}
 */
export function regionsReducer(state, action) {
    switch (action.type) {

        // ── Regions ──────────────────────────
        case 'SET_REGIONS':
            return {
                ...state,
                regions: normalizeRegions(action.payload),
                project: { ...state.project, dirty: true },
            };

        case 'ADD_REGION': {
            const normalized = normalizeRegion(action.payload);
            if (!normalized) return state;
            const newRegions = [...state.regions, normalized]
                .sort((a, b) => a.timelineStart - b.timelineStart);
            return {
                ...state,
                regions: newRegions,
                project: { ...state.project, dirty: true },
            };
        }

        case 'REMOVE_REGION': {
            const filtered = state.regions.filter(r => r.id !== action.payload);
            return {
                ...state,
                regions: filtered,
                selectedRegionIds: (() => {
                    const s = new Set(state.selectedRegionIds);
                    s.delete(action.payload);
                    return s;
                })(),
                project: { ...state.project, dirty: true },
            };
        }

        case 'UPDATE_REGION': {
            const { id, updates } = action.payload;
            const updatedRegions = state.regions.map(r =>
                r.id === id ? (normalizeRegion({ ...r, ...updates }) || r) : r
            );
            return {
                ...state,
                regions: updatedRegions,
                project: { ...state.project, dirty: true },
            };
        }

        case 'SPLIT_REGION_AT': {
            const { regionId, splitTime } = action.payload;
            const region = state.regions.find(r => r.id === regionId);
            if (!region) return state;

            // Validate split point
            if (splitTime <= region.timelineStart || splitTime >= region.timelineStart + region.duration) {
                return state;
            }

            const relativeOffset = splitTime - region.timelineStart;
            const sourceSplitPoint = region.sourceStart + relativeOffset;

            const leftRegion = {
                ...region,
                id: crypto.randomUUID(),
                sourceEnd: sourceSplitPoint,
                duration: relativeOffset,
                sourceDuration: relativeOffset,
            };

            const rightDuration = region.duration - relativeOffset;
            const rightRegion = {
                ...region,
                id: crypto.randomUUID(),
                sourceStart: sourceSplitPoint,
                timelineStart: splitTime,
                duration: rightDuration,
                sourceDuration: rightDuration,
                // Clear stored beat values since they're invalidated
                _beatStart: undefined,
                _beatEnd: undefined,
                _songBeatStart: undefined,
                _songBeatEnd: undefined,
            };

            const newRegions = normalizeRegions(
                state.regions
                    .filter(r => r.id !== regionId)
                    .concat([leftRegion, rightRegion])
            ).sort((a, b) => a.timelineStart - b.timelineStart);

            return {
                ...state,
                regions: newRegions,
                selectedRegionIds: new Set(),
                project: { ...state.project, dirty: true },
            };
        }

        case 'RIPPLE_DELETE': {
            const deleteId = action.payload;
            const deleteRegion = state.regions.find(r => r.id === deleteId);
            if (!deleteRegion) return state;

            const gap = deleteRegion.duration;
            const deleteStart = deleteRegion.timelineStart;

            const newRegions = state.regions
                .filter(r => r.id !== deleteId)
                .map(r => {
                    if (r.timelineStart > deleteStart) {
                        return {
                            ...r,
                            timelineStart: r.timelineStart - gap,
                            timelineEnd: (r.timelineStart - gap) + r.duration,
                            _beatStart: undefined,
                            _beatEnd: undefined,
                        };
                    }
                    return r;
                });

            return {
                ...state,
                regions: newRegions,
                selectedRegionIds: new Set(),
                project: { ...state.project, dirty: true },
            };
        }

        // ── Clipboard / Editing ──────────────
        case 'COPY_SELECTION': {
            log.debug('Reducer: COPY_SELECTION', {
                selectedIds: Array.from(state.selectedRegionIds),
                range: state.selectionRange
            });

            let regionsToCopy = [];
            let copyStart = 0;
            // Total span of the user's selection. When a time-range was
            // selected this MUST equal range.end - range.start, even if
            // the regions inside don't fully cover the range. Otherwise
            // PASTE_INSERT's ripple shift falls short by the trailing
            // (or leading) empty space and the next region snuggles up
            // against the paste — the visible "missing half between two
            // region lines" the user reported.
            let clipboardSpan = 0;

            // 1. Check for Time Selection Range
            if (state.selectionRange && Math.abs(state.selectionRange.end - state.selectionRange.start) > 0.001) {
                const { start, end } = state.selectionRange;
                copyStart = start;
                clipboardSpan = end - start;

                // Find regions intersecting the selection range
                const intersecting = state.regions.filter(r =>
                    r.timelineStart < end && (r.timelineStart + r.duration) > start
                );

                regionsToCopy = intersecting.map(r => {
                    const intersectStart = Math.max(r.timelineStart, start);
                    const intersectEnd = Math.min(r.timelineStart + r.duration, end);
                    const newDuration = intersectEnd - intersectStart;

                    // Calculate new source start based on where the intersection starts relative to region start
                    const offsetFromRegionStart = intersectStart - r.timelineStart;
                    const newSourceStart = r.sourceStart + offsetFromRegionStart;

                    return {
                        ...r,
                        id: crypto.randomUUID(), // New ID for clipboard item
                        timelineStart: intersectStart,
                        duration: newDuration,
                        sourceStart: newSourceStart,
                        // sourceEnd MUST track sourceStart — without this the
                        // clipboard inherits the original region's sourceEnd
                        // (which still points at the old, larger boundary).
                        // DawEngine's playRegions falls back to sourceEnd
                        // when sourceDuration is missing, and the offline
                        // export renderer uses sourceEnd directly. A stale
                        // sourceEnd makes small clipped sections play extra
                        // audio past the visible region edge (audible as
                        // ghost content beyond the displayed waveform).
                        sourceEnd: newSourceStart + newDuration,
                        sourceDuration: newDuration,
                        _beatStart: undefined, _beatEnd: undefined
                    };
                });
            } else {
                // 2. Fallback: Copy whole selected regions
                regionsToCopy = state.regions.filter(r => state.selectedRegionIds.has(r.id));
                if (regionsToCopy.length > 0) {
                    regionsToCopy.sort((a, b) => a.timelineStart - b.timelineStart);
                    copyStart = regionsToCopy[0].timelineStart;
                    // For whole-region selection, span = first start → last end
                    const lastEnd = regionsToCopy.reduce(
                        (acc, r) => Math.max(acc, r.timelineStart + r.duration),
                        copyStart
                    );
                    clipboardSpan = lastEnd - copyStart;
                }
            }

            if (regionsToCopy.length === 0) return state;

            // Sort by time
            regionsToCopy.sort((a, b) => a.timelineStart - b.timelineStart);

            // Normalize to 0 offset relative to copy start
            const clipboardData = regionsToCopy.map(r => ({
                ...r,
                _offset: r.timelineStart - copyStart
            }));

            return { ...state, clipboard: clipboardData, clipboardSpan };
        }

        case 'PASTE_INSERT': {
            log.debug('Reducer: PASTE_INSERT', state.clipboard);
            if (state.clipboard.length === 0) return state;

            const EPSILON = 0.001;
            const rawInsertTime = state.playhead;

            // Snap insertTime to the previous region's END if the playhead
            // sits in dead space (no region under it). Rekordbox's editor
            // does the same — clicking past the last clip and pasting
            // attaches the new clip flush against the existing content
            // rather than leaving a leading silence gap. Only snaps
            // FORWARD-LOOKING (no jump backwards across a real gap that
            // the user might want to span).
            const sortedExisting = [...state.regions].sort(
                (a, b) => a.timelineStart - b.timelineStart
            );
            const containing = sortedExisting.find(r =>
                rawInsertTime > r.timelineStart - EPSILON &&
                rawInsertTime < r.timelineStart + r.duration - EPSILON
            );
            let insertTime = rawInsertTime;
            if (!containing) {
                let prevEnd = 0;
                for (const r of sortedExisting) {
                    const rEnd = r.timelineStart + r.duration;
                    if (rEnd <= rawInsertTime + EPSILON && rEnd > prevEnd) {
                        prevEnd = rEnd;
                    }
                }
                if (prevEnd > 0 && prevEnd < rawInsertTime - EPSILON) {
                    insertTime = prevEnd;
                }
            }

            let tempRegions = [...state.regions];

            // 1. Check if we need to split a region at insertTime
            const intersectIdx = tempRegions.findIndex(r =>
                insertTime > r.timelineStart + EPSILON &&
                insertTime < r.timelineStart + r.duration - EPSILON
            );

            if (intersectIdx !== -1) {
                const r = tempRegions[intersectIdx];
                const relativeOffset = insertTime - r.timelineStart;
                const sourceSplitPoint = r.sourceStart + relativeOffset;

                // Create Left Part (ends at insertTime)
                const leftRegion = {
                    ...r,
                    id: crypto.randomUUID(),
                    duration: relativeOffset,
                    sourceDuration: relativeOffset,
                    sourceEnd: sourceSplitPoint,
                    _beatStart: undefined, _beatEnd: undefined // Invalidate beat cache
                };

                // Create Right Part (starts at insertTime)
                const rightRegion = {
                    ...r,
                    id: crypto.randomUUID(),
                    timelineStart: insertTime,
                    sourceStart: sourceSplitPoint,
                    duration: r.duration - relativeOffset,
                    sourceDuration: r.duration - relativeOffset,
                    _beatStart: undefined, _beatEnd: undefined
                };

                // Replace original with Left and Right
                tempRegions.splice(intersectIdx, 1, leftRegion, rightRegion);
            }

            // 2. Pack the clipboard items contiguously at insertTime —
            // collapse any internal gaps the original selection had. The
            // user's "the gap remains in the paste" complaint comes from
            // the previous behaviour of preserving _offset (which encoded
            // the position INSIDE the original selection, gaps included).
            // For a single-region clipboard this changes nothing.
            const sortedClip = [...state.clipboard].sort(
                (a, b) => (a._offset ?? 0) - (b._offset ?? 0)
            );
            let cursor = insertTime;
            const pastedRegions = sortedClip.map(r => {
                const placed = {
                    ...r,
                    id: crypto.randomUUID(),
                    timelineStart: cursor,
                    timelineEnd: cursor + r.duration,
                    _offset: undefined,
                };
                cursor += r.duration;
                return placed;
            });
            const pastedSpan = cursor - insertTime;

            log.debug('Reducer: PASTE_INSERT debug', {
                rawInsertTime,
                insertTime,
                pastedSpan,
                intersectIdx,
                regionCount: tempRegions.length,
            });

            // 3. Ripple Shift: Move everything >= insertTime to the right
            //    by EXACTLY the packed paste span. Using pastedSpan rather
            //    than the original clipboardSpan keeps the next region
            //    flush against the last pasted item.
            const shiftedRegions = tempRegions.map(r => {
                if (r.timelineStart >= insertTime - 0.0001) {
                    return { ...r, timelineStart: r.timelineStart + pastedSpan };
                }
                return r;
            });

            const finalRegions = normalizeRegions(
                [...shiftedRegions, ...pastedRegions]
            ).sort((a, b) => a.timelineStart - b.timelineStart);

            return {
                ...state,
                regions: finalRegions,
                selectedRegionIds: new Set(pastedRegions.map(r => r.id)),
                project: { ...state.project, dirty: true },
            };
        }

        case 'DUPLICATE_SELECTION': {
            log.debug('Reducer: DUPLICATE_SELECTION', state.selectedRegionIds);
            const selectedRegions = state.regions.filter(r => state.selectedRegionIds.has(r.id));
            if (selectedRegions.length === 0) return state;

            const sorted = [...selectedRegions].sort((a, b) => a.timelineStart - b.timelineStart);
            const startT = sorted[0].timelineStart;
            const endT = sorted[sorted.length - 1].timelineStart + sorted[sorted.length - 1].duration;
            const duration = endT - startT;

            const duplicates = selectedRegions.map(r => ({
                ...r,
                id: crypto.randomUUID(),
                timelineStart: r.timelineStart + duration,
                timelineEnd: r.timelineStart + duration + r.duration
            }));

            const finalRegions = normalizeRegions(
                [...state.regions, ...duplicates]
            ).sort((a, b) => a.timelineStart - b.timelineStart);

            return {
                ...state,
                regions: finalRegions,
                selectedRegionIds: new Set(duplicates.map(r => r.id)),
                project: { ...state.project, dirty: true },
            };
        }

        // ── Volume ───────────────────────────
        case 'SET_VOLUME_DATA':
            return { ...state, volumeData: action.payload };

        default:
            return state;
    }
}
