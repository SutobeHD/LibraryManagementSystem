import { confirmModal } from './ConfirmModal';
import { getAnalysisDepth } from '../api/api';

// Copy for the two depth levels — shared by the Settings cards and the per-run dialog.
// Ids match ANALYSIS_DEPTHS in config/constants.js and the backend's `depth` field.
export const ANALYSIS_DEPTH_OPTIONS = [
    {
        id: 'rekordbox',
        label: 'Rekordbox',
        sub: 'What Rekordbox itself computes: BPM, beat grid, key, waveforms, phrases, cues, loudness',
    },
    {
        id: 'high',
        label: 'High',
        sub: 'Additionally stereo image, mood, genre hint, quality cutoff, clipping, dynamics, bass share, mono compatibility; about 15 % longer',
    },
];

/**
 * Per-run depth dialog, preset to the global `analysis_depth` setting (decision B12).
 * `subject` names the track; without it the message is the track count.
 * Resolves to 'rekordbox' | 'high', or null when the user cancels.
 */
export async function askAnalysisDepth({ count = 1, subject = null } = {}) {
    const preset = await getAnalysisDepth();
    const choice = await confirmModal({
        title: 'Analyse',
        message: subject ?? (count === 1 ? '1 track' : `${count} tracks`),
        options: ANALYSIS_DEPTH_OPTIONS,
        defaultOption: preset,
        confirmLabel: 'Start',
        cancelLabel: 'Cancel',
    });
    return choice || null;
}
