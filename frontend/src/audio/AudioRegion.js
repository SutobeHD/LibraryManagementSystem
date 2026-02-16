/**
 * AudioRegion - Core data structure for non-destructive audio editing
 * 
 * Each region represents a reference to a portion of the original audio file.
 * The original file is never modified - all edits are stored as region metadata.
 */

let regionIdCounter = 0;

/**
 * Generate a unique region ID
 */
export function generateRegionId() {
    return `region-${Date.now()}-${regionIdCounter++}`;
}

/**
 * Create a new AudioRegion
 * 
 * @param {Object} params - Region parameters
 * @param {AudioBuffer} params.sourceBuffer - Reference to original AudioBuffer
 * @param {string} params.sourcePath - Path to original audio file
 * @param {number} params.sourceStart - Start time in original audio (seconds)
 * @param {number} params.sourceEnd - End time in original audio (seconds)
 * @param {number} params.timelineStart - Position on timeline (seconds)
 * @param {string} [params.id] - Optional custom ID
 * @param {string} [params.name] - Optional display name
 * @param {string} [params.color] - Optional color for UI
 * @returns {AudioRegion}
 */
export function createRegion({
    sourceBuffer,
    sourcePath,
    sourceStart,
    sourceEnd,
    timelineStart,
    id = null,
    name = null,
    color = null
}) {
    return {
        id: id || generateRegionId(),
        name: name || `Region ${regionIdCounter}`,

        // Source reference (non-destructive)
        sourceBuffer,
        sourcePath,
        sourceStart,
        sourceEnd,

        // Timeline position
        timelineStart,

        // Computed duration
        get duration() {
            return this.sourceEnd - this.sourceStart;
        },

        // Timeline end position
        get timelineEnd() {
            return this.timelineStart + this.duration;
        },

        // Envelope settings
        fadeInDuration: 0,      // seconds
        fadeOutDuration: 0,     // seconds
        gain: 1.0,              // 0.0 - 2.0

        // UI state
        color: color || '#3b82f6',  // Default blue
        isSelected: false,
        isMuted: false,
        isLocked: false
    };
}

/**
 * Clone a region (for copy/paste operations)
 * Creates a new region with same source reference but new ID
 * 
 * @param {AudioRegion} region - Region to clone
 * @param {number} [newTimelineStart] - Optional new timeline position
 * @returns {AudioRegion}
 */
export function cloneRegion(region, newTimelineStart = null) {
    return {
        ...region,
        id: generateRegionId(),
        name: `${region.name} (Copy)`,
        timelineStart: newTimelineStart !== null ? newTimelineStart : region.timelineStart,
        isSelected: false
    };
}

/**
 * Split a region at a given time position
 * Returns two new regions that together represent the original
 * 
 * @param {AudioRegion} region - Region to split
 * @param {number} splitTime - Timeline position to split at
 * @returns {[AudioRegion, AudioRegion]} - Left and right regions
 */
export function splitRegion(region, splitTime) {
    // Validate split point is within region
    if (splitTime <= region.timelineStart || splitTime >= region.timelineEnd) {
        console.warn('Split point outside region bounds');
        return [region, null];
    }

    // Calculate the split point in source time
    const relativeOffset = splitTime - region.timelineStart;
    const sourceSplitPoint = region.sourceStart + relativeOffset;

    // Create left region (inherits fade-in)
    const leftRegion = {
        ...region,
        id: generateRegionId(),
        name: `${region.name} (L)`,
        sourceEnd: sourceSplitPoint,
        fadeOutDuration: 0,  // Reset fade-out on left
        isSelected: false
    };

    // Create right region (inherits fade-out)
    const rightRegion = {
        ...region,
        id: generateRegionId(),
        name: `${region.name} (R)`,
        sourceStart: sourceSplitPoint,
        timelineStart: splitTime,
        fadeInDuration: 0,  // Reset fade-in on right
        isSelected: false
    };

    return [leftRegion, rightRegion];
}

/**
 * Trim a region's start or end
 * 
 * @param {AudioRegion} region - Region to trim
 * @param {number} newSourceStart - New source start time
 * @param {number} newSourceEnd - New source end time
 * @returns {AudioRegion}
 */
export function trimRegion(region, newSourceStart = null, newSourceEnd = null) {
    const trimmedRegion = { ...region };

    if (newSourceStart !== null && newSourceStart >= region.sourceStart) {
        const trimAmount = newSourceStart - region.sourceStart;
        trimmedRegion.sourceStart = newSourceStart;
        trimmedRegion.timelineStart = region.timelineStart + trimAmount;
    }

    if (newSourceEnd !== null && newSourceEnd <= region.sourceEnd) {
        trimmedRegion.sourceEnd = newSourceEnd;
    }

    return trimmedRegion;
}

/**
 * Move a region to a new timeline position
 * 
 * @param {AudioRegion} region - Region to move
 * @param {number} newTimelineStart - New timeline start position
 * @returns {AudioRegion}
 */
export function moveRegion(region, newTimelineStart) {
    return {
        ...region,
        timelineStart: Math.max(0, newTimelineStart)
    };
}

/**
 * Set envelope for a region
 * 
 * @param {AudioRegion} region - Region to modify
 * @param {number} [fadeIn] - Fade-in duration in seconds
 * @param {number} [fadeOut] - Fade-out duration in seconds
 * @param {number} [gain] - Gain value (0.0 - 2.0)
 * @returns {AudioRegion}
 */
export function setEnvelope(region, fadeIn = null, fadeOut = null, gain = null) {
    const updated = { ...region };

    if (fadeIn !== null) {
        updated.fadeInDuration = Math.max(0, Math.min(fadeIn, region.duration / 2));
    }
    if (fadeOut !== null) {
        updated.fadeOutDuration = Math.max(0, Math.min(fadeOut, region.duration / 2));
    }
    if (gain !== null) {
        updated.gain = Math.max(0, Math.min(2.0, gain));
    }

    return updated;
}

/**
 * Check if two regions overlap on the timeline
 * 
 * @param {AudioRegion} regionA 
 * @param {AudioRegion} regionB 
 * @returns {boolean}
 */
export function regionsOverlap(regionA, regionB) {
    return !(regionA.timelineEnd <= regionB.timelineStart ||
        regionB.timelineEnd <= regionA.timelineStart);
}

/**
 * Sort regions by timeline position
 * 
 * @param {AudioRegion[]} regions 
 * @returns {AudioRegion[]}
 */
export function sortRegionsByPosition(regions) {
    return [...regions].sort((a, b) => a.timelineStart - b.timelineStart);
}

/**
 * Calculate total timeline duration based on regions
 * 
 * @param {AudioRegion[]} regions 
 * @returns {number}
 */
export function calculateTimelineDuration(regions) {
    if (regions.length === 0) return 0;
    return Math.max(...regions.map(r => r.timelineEnd));
}

export default {
    createRegion,
    cloneRegion,
    splitRegion,
    trimRegion,
    moveRegion,
    setEnvelope,
    regionsOverlap,
    sortRegionsByPosition,
    calculateTimelineDuration,
    generateRegionId
};
