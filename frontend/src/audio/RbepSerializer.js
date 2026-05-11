/**
 * RbepSerializer — .rbep XML Parser/Serializer
 * 
 * Handles the critical Beat ↔ Seconds conversion for Rekordbox Edit Project files.
 * The .rbep format stores section positions as BEAT INDICES, not seconds.
 * This module converts between the two using a tempo map.
 * 
 * Also handles POSITION_MARK nodes for cue points and loops (standard Rekordbox XML schema).
 */

// ─── TEMPO MAP UTILITIES ───────────────────────────────────────────────────────

/**
 * Build a tempo map for a constant-BPM track.
 * Each entry: { index, bpm, positionMs }
 * 
 * @param {number} bpm - Track BPM
 * @param {number} firstBeatMs - Position of the first beat in milliseconds
 * @param {number} durationMs - Total track duration in milliseconds
 * @returns {Array<{index: number, bpm: number, positionMs: number}>}
 */
export function buildTempoMap(bpm, firstBeatMs, durationMs) {
    const msPerBeat = 60000 / bpm;
    const map = [];
    let pos = firstBeatMs;
    let index = 0;

    while (pos < durationMs) {
        map.push({ index, bpm, positionMs: pos });
        pos += msPerBeat;
        index++;
    }

    return map;
}

/**
 * Convert a beat index to seconds using a tempo map.
 * Handles variable BPM by interpolating between tempo map entries.
 * 
 * @param {number} beatIndex - Beat index (can be fractional)
 * @param {Array<{index: number, bpm: number, positionMs: number}>} tempoMap
 * @returns {number} Time in seconds
 */
export function beatsToSeconds(beatIndex, tempoMap) {
    if (!tempoMap || tempoMap.length === 0) return 0;

    // Find the surrounding tempo map entries
    let lower = tempoMap[0];
    let upper = null;

    for (let i = 0; i < tempoMap.length; i++) {
        if (tempoMap[i].index <= beatIndex) {
            lower = tempoMap[i];
            upper = tempoMap[i + 1] || null;
        } else {
            break;
        }
    }

    // Interpolate from the lower entry
    const msPerBeat = 60000 / lower.bpm;
    const beatOffset = beatIndex - lower.index;
    const posMs = lower.positionMs + (beatOffset * msPerBeat);

    return posMs / 1000;
}

/**
 * Convert seconds to a beat index using a tempo map.
 * 
 * @param {number} seconds - Time in seconds
 * @param {Array<{index: number, bpm: number, positionMs: number}>} tempoMap
 * @returns {number} Beat index (can be fractional)
 */
export function secondsToBeats(seconds, tempoMap) {
    if (!tempoMap || tempoMap.length === 0) return 0;

    const ms = seconds * 1000;

    // Find the surrounding tempo map entries
    let lower = tempoMap[0];

    for (let i = 0; i < tempoMap.length; i++) {
        if (tempoMap[i].positionMs <= ms) {
            lower = tempoMap[i];
        } else {
            break;
        }
    }

    const msPerBeat = 60000 / lower.bpm;
    const msOffset = ms - lower.positionMs;
    const beatOffset = msOffset / msPerBeat;

    return lower.index + beatOffset;
}

// ─── .rbep XML PARSER ──────────────────────────────────────────────────────────

/**
 * Parse a .rbep XML string into a runtime project object.
 * Converts beat-indexed sections to seconds using the embedded tempo map.
 * 
 * @param {string} xmlString - Raw .rbep XML content
 * @returns {Object} Runtime project structure
 */
export function parseRbep(xmlString) {
    const parser = new DOMParser();
    const doc = parser.parseFromString(xmlString, 'application/xml');

    const parseError = doc.querySelector('parsererror');
    if (parseError) {
        throw new Error('Invalid .rbep XML: ' + parseError.textContent);
    }

    const project = {
        info: {
            app: doc.querySelector('info > app')?.textContent || 'rekordbox',
            version: doc.querySelector('info > version')?.textContent || '1',
        },
        tracks: [],
        mastergrid: null,
    };

    // Parse mastergrid
    const mastergridEl = doc.querySelector('mastergrid');
    if (mastergridEl) {
        project.mastergrid = {
            indexOffset: parseInt(mastergridEl.getAttribute('indexoffset') || '1'),
            beats: parseBeatData(mastergridEl.querySelector('data')),
        };
    }

    // Parse tracks
    const trackEls = doc.querySelectorAll('tracks > track');
    for (const trackEl of trackEls) {
        const track = parseTrack(trackEl, project.mastergrid);
        project.tracks.push(track);
    }

    return project;
}

/**
 * Parse a single <track> element
 */
function parseTrack(trackEl, mastergrid) {
    const songEl = trackEl.querySelector('song');
    const editEl = trackEl.querySelector('edit');
    const songgridEl = trackEl.querySelector('songgrid');

    // Parse song metadata
    const song = {
        id: songEl?.getAttribute('id') || '',
        uuid: songEl?.getAttribute('uuid') || crypto.randomUUID(),
        title: songEl?.querySelector('title')?.textContent || 'Untitled',
        artist: songEl?.querySelector('artist')?.textContent || 'Unknown',
        album: songEl?.querySelector('album')?.textContent || '',
        filepath: songEl?.querySelector('filepath')?.textContent || '',
    };

    // Parse cue points & loops (POSITION_MARK nodes)
    const cuePoints = [];
    const positionMarks = songEl?.querySelectorAll('POSITION_MARK') || [];
    for (const pm of positionMarks) {
        cuePoints.push({
            name: pm.getAttribute('Name') || '',
            type: parseInt(pm.getAttribute('Type') || '0'), // 0=Cue, 4=Loop
            start: parseFloat(pm.getAttribute('Start') || '0'),
            end: pm.hasAttribute('End') ? parseFloat(pm.getAttribute('End')) : null,
            num: parseInt(pm.getAttribute('Num') || '-1'),
            red: parseInt(pm.getAttribute('Red') || '40'),
            green: parseInt(pm.getAttribute('Green') || '255'),
            blue: parseInt(pm.getAttribute('Blue') || '0'),
        });
    }

    // Parse songgrid (per-beat positions from original track)
    let songTempoMap = [];
    if (songgridEl) {
        const orgGridEl = songgridEl.querySelector('orggrid');
        const gridData = orgGridEl ? orgGridEl.querySelector('data') : songgridEl.querySelector('data');
        songTempoMap = parseBeatData(gridData);
    }

    // Use mastergrid as the timeline tempo map for beat→seconds conversion
    const timelineTempoMap = mastergrid?.beats || songTempoMap;

    // Parse edit sections (beat indices → seconds)
    let regions = [];
    if (editEl) {
        const positionData = editEl.querySelector('position > data');
        if (positionData) {
            const sections = positionData.querySelectorAll('section');
            let timelinePos = 0;

            for (const section of sections) {
                const startBeat = parseFloat(section.getAttribute('start') || '0');
                const endBeat = parseFloat(section.getAttribute('end') || '0');
                const songStartBeat = parseFloat(section.getAttribute('songstart') || '0');
                const songEndBeat = parseFloat(section.getAttribute('songend') || '0');

                // Convert to seconds
                const timelineStart = beatsToSeconds(startBeat, timelineTempoMap);
                const timelineEnd = beatsToSeconds(endBeat, timelineTempoMap);
                const sourceStart = beatsToSeconds(songStartBeat, songTempoMap);
                const sourceEnd = beatsToSeconds(songEndBeat, songTempoMap);

                regions.push({
                    id: crypto.randomUUID(),
                    sourceFile: song.filepath,
                    timelineStart,
                    timelineEnd,
                    duration: timelineEnd - timelineStart,
                    sourceStart,
                    sourceEnd,
                    sourceDuration: sourceEnd - sourceStart,
                    // Store original beat values for round-trip fidelity
                    _beatStart: startBeat,
                    _beatEnd: endBeat,
                    _songBeatStart: songStartBeat,
                    _songBeatEnd: songEndBeat,
                });

                timelinePos = timelineEnd;
            }
        }
    }

    // Parse volume
    let volume = [];
    const volumeData = editEl?.querySelector('volume > data');
    if (volumeData) {
        const sections = volumeData.querySelectorAll('section');
        for (const s of sections) {
            volume.push({
                startBeat: parseFloat(s.getAttribute('start') || '0'),
                endBeat: parseFloat(s.getAttribute('end') || '0'),
                vol: parseFloat(s.getAttribute('vol') || '1.0'),
            });
        }
    }

    // Parse BPM
    let bpm = 128;
    const bpmData = editEl?.querySelector('bpm > data');
    if (bpmData) {
        const bpmSection = bpmData.querySelector('section');
        if (bpmSection) {
            bpm = parseFloat(bpmSection.getAttribute('bpm') || '128');
        }
    }

    return {
        trackId: trackEl.getAttribute('trackid') || '1',
        song,
        cuePoints,
        regions,
        volume,
        bpm,
        songTempoMap,
        songGridInfo: songgridEl ? {
            length: parseInt(songgridEl.getAttribute('length') || '0'),
            bpm: parseFloat(songgridEl.getAttribute('bpm') || '0'),
            indexOffset: parseInt(songgridEl.getAttribute('indexoffset') || '1'),
        } : null,
    };
}

/**
 * Parse <data> element containing <beat> children into a tempo map array.
 */
function parseBeatData(dataEl) {
    if (!dataEl) return [];
    const beats = [];
    const beatEls = dataEl.querySelectorAll('beat');
    for (const b of beatEls) {
        beats.push({
            index: parseInt(b.getAttribute('index') || '0'),
            bpm: parseFloat(b.getAttribute('bpm') || '0'),
            positionMs: parseFloat(b.getAttribute('position') || '0'),
        });
    }
    return beats;
}

// ─── .rbep XML SERIALIZER ──────────────────────────────────────────────────────

/**
 * Serialize a runtime project object to .rbep XML string.
 * Converts seconds back to beat indices using the tempo map.
 * 
 * @param {Object} project - Runtime project
 * @returns {string} .rbep XML string
 */
export function serializeRbep(project) {
    const lines = [];
    lines.push('<?xml version="1.0" encoding="UTF-8"?>');
    lines.push('');
    lines.push('<project>');

    // Info
    lines.push('  <info>');
    lines.push(`    <app>${escXml(project.info?.app || 'rekordbox')}</app>`);
    lines.push(`    <version>${escXml(project.info?.version || '1')}</version>`);
    lines.push('  </info>');

    // Tracks
    lines.push('  <tracks>');
    for (const track of (project.tracks || [])) {
        serializeTrack(lines, track, project.mastergrid);
    }
    lines.push('  </tracks>');

    // Mastergrid
    if (project.mastergrid) {
        lines.push(`  <mastergrid indexoffset="${project.mastergrid.indexOffset || 1}">`);
        lines.push('    <data>');
        for (const b of (project.mastergrid.beats || [])) {
            lines.push(`      <beat index="${b.index}" bpm="${b.bpm}" position="${b.positionMs}"/>`);
        }
        lines.push('    </data>');
        lines.push('  </mastergrid>');
    }

    lines.push('</project>');

    return lines.join('\r\n');
}

function serializeTrack(lines, track, mastergrid) {
    const timelineTempoMap = mastergrid?.beats || track.songTempoMap || [];
    const songTempoMap = track.songTempoMap || [];

    lines.push(`    <track trackid="${track.trackId || '1'}">`);

    // Song metadata + POSITION_MARK cues
    lines.push(`      <song id="${escXml(track.song.id)}" uuid="${escXml(track.song.uuid)}">`);
    lines.push(`        <title>${escXml(track.song.title)}</title>`);
    lines.push(`        <artist>${escXml(track.song.artist)}</artist>`);
    lines.push(`        <album>${escXml(track.song.album)}</album>`);
    lines.push(`        <filepath>${escXml(track.song.filepath)}</filepath>`);

    // Cue points (POSITION_MARK)
    for (const cue of (track.cuePoints || [])) {
        let attrs = `Name="${escXml(cue.name)}" Type="${cue.type}" Start="${cue.start.toFixed(3)}"`;
        if (cue.end !== null && cue.end !== undefined) {
            attrs += ` End="${cue.end.toFixed(3)}"`;
        }
        attrs += ` Num="${cue.num}" Red="${cue.red}" Green="${cue.green}" Blue="${cue.blue}"`;
        lines.push(`        <POSITION_MARK ${attrs}/>`);
    }

    lines.push('      </song>');

    // Edit section
    lines.push('      <edit>');

    // Position sections (seconds → beats)
    lines.push('        <position>');
    lines.push('          <data>');
    for (const region of (track.regions || [])) {
        // Use stored beat values if available (round-trip fidelity), else convert
        const startBeat = region._beatStart ?? secondsToBeats(region.timelineStart, timelineTempoMap);
        const endBeat = region._beatEnd ?? secondsToBeats(region.timelineEnd, timelineTempoMap);
        const songStartBeat = region._songBeatStart ?? secondsToBeats(region.sourceStart, songTempoMap);
        const songEndBeat = region._songBeatEnd ?? secondsToBeats(region.sourceEnd, songTempoMap);

        lines.push(`            <section start="${startBeat.toFixed(1)}" end="${endBeat.toFixed(1)}" songstart="${songStartBeat.toFixed(1)}" songend="${songEndBeat.toFixed(1)}"/>`);
    }
    lines.push('          </data>');
    lines.push('        </position>');

    // Volume
    lines.push('        <volume>');
    lines.push('          <data>');
    if (track.volume && track.volume.length > 0) {
        for (const v of track.volume) {
            lines.push(`            <section start="${v.startBeat.toFixed(1)}" end="${v.endBeat.toFixed(1)}" vol="${v.vol.toFixed(1)}"/>`);
        }
    } else {
        // Default: full volume for entire duration
        const totalBeats = track.regions.length > 0
            ? (track.regions[track.regions.length - 1]._beatEnd ?? secondsToBeats(track.regions[track.regions.length - 1].timelineEnd, timelineTempoMap))
            : 0;
        lines.push(`            <section start="0.0" end="${totalBeats.toFixed(1)}" vol="1.0"/>`);
    }
    lines.push('          </data>');
    lines.push('        </volume>');

    // BPM
    lines.push('        <bpm>');
    lines.push('          <data>');
    const totalBeats = track.regions.length > 0
        ? (track.regions[track.regions.length - 1]._beatEnd ?? secondsToBeats(track.regions[track.regions.length - 1].timelineEnd, timelineTempoMap))
        : 0;
    lines.push(`            <section start="0.0" end="${totalBeats.toFixed(1)}" bpm="${(track.bpm || 128).toFixed(2)}"/>`);
    lines.push('          </data>');
    lines.push('        </bpm>');

    // Prepared (hotcue/memorycue/activecensor stubs)
    lines.push('        <prepared>');
    lines.push('          <hotcue>');
    lines.push('            <data/>');
    lines.push('          </hotcue>');
    lines.push('          <memorycue>');
    lines.push('            <data/>');
    lines.push('          </memorycue>');
    lines.push('          <activecensor>');
    lines.push('            <data/>');
    lines.push('          </activecensor>');
    lines.push('        </prepared>');

    lines.push('      </edit>');

    // Song grid
    if (track.songGridInfo && songTempoMap.length > 0) {
        lines.push(`      <songgrid length="${track.songGridInfo.length}" bpm="${track.songGridInfo.bpm}" indexoffset="${track.songGridInfo.indexOffset}">`);
        lines.push(`        <orggrid indexoffset="0">`);
        lines.push('          <data>');
        for (const b of songTempoMap) {
            lines.push(`            <beat index="${b.index}" bpm="${b.bpm}" position="${b.positionMs}"/>`);
        }
        lines.push('          </data>');
        lines.push('        </orggrid>');
        lines.push('      </songgrid>');
    }

    lines.push('    </track>');
}

function escXml(str) {
    if (str == null) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&apos;');
}

// ─── PROJECT FILE I/O ──────────────────────────────────────────────────────────

/**
 * Load a .rbep file from disk via fetch (Tauri asset protocol or local file).
 * 
 * @param {string} filepath - Path to .rbep file
 * @returns {Promise<Object>} Parsed project
 */
export async function loadRbepFile(filepath) {
    // In Tauri, use convertFileSrc or invoke to read file
    // Fallback: fetch from backend
    try {
        const { invoke } = await import('@tauri-apps/api/core');
        const xmlString = await invoke('plugin:fs|read_text_file', { path: filepath });
        return parseRbep(xmlString);
    } catch {
        // Fallback: read the .rbep via the backend file proxy. Goes through the
        // shared axios instance so session-token + 401-refresh + 429-backoff all
        // apply just like every other API call.
        const { default: api } = await import('../api/api');
        const res = await api.get('/api/file/read', {
            params: { path: filepath },
            responseType: 'text',
            transformResponse: [(d) => d],  // keep the raw XML string
        });
        return parseRbep(res.data);
    }
}

/**
 * Save a project to a .rbep file.
 * 
 * @param {Object} project - Runtime project object
 * @param {string} filepath - Target file path
 * @returns {Promise<void>}
 */
export async function saveRbepFile(project, filepath) {
    const xmlString = serializeRbep(project);

    // Try Tauri native file write first (desktop context)
    if (window.__TAURI__) {
        try {
            const { invoke } = await import('@tauri-apps/api/core');
            await invoke('plugin:fs|write_text_file', { path: filepath, contents: xmlString });
            return;
        } catch (e) {
            console.warn('[RbepSerializer] Tauri fs write failed, falling back to backend:', e);
        }
    }

    // Fallback: POST to backend via api instance (includes session token + proper headers)
    // Lazy-import api to avoid circular deps at module level
    const { default: api } = await import('../api/api.js');
    const res = await api.post('/api/file/write', { path: filepath, content: xmlString });
    if (res.data?.status !== 'success') {
        throw new Error(res.data?.message || 'Backend file write returned no success status');
    }
}

export default {
    buildTempoMap,
    beatsToSeconds,
    secondsToBeats,
    parseRbep,
    serializeRbep,
    loadRbepFile,
    saveRbepFile,
};
