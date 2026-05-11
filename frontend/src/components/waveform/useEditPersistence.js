import { useEffect } from 'react';
import { loadEditsForTrack, saveEditsForTrack, clearEditsForTrack } from './persistence';

// localStorage auto-save + restore for per-track edits (cuts + hot cues).
//  - auto-save debounced 500ms after cuts/hotCues change
//  - restore on track-id change after the buffer is ready (so we don't clobber the initial load)
export default function useEditPersistence({ fullTrack, bufferReady, cuts, hotCues, setCuts, setHotCues, toast }) {
    // Auto-save edits to localStorage (debounced 500ms)
    useEffect(() => {
        if (!fullTrack?.id) return;
        const t = setTimeout(() => {
            if (cuts.length === 0 && hotCues.length === 0) clearEditsForTrack(fullTrack.id);
            else saveEditsForTrack(fullTrack.id, { cuts, hotCues });
        }, 500);
        return () => clearTimeout(t);
    }, [cuts, hotCues, fullTrack?.id]);

    // Restore edits when track loads
    useEffect(() => {
        if (!fullTrack?.id || !bufferReady) return;
        const saved = loadEditsForTrack(fullTrack.id);
        if (saved && (saved.cuts?.length || saved.hotCues?.length)) {
            // Only restore if state is empty (don't clobber active session)
            if (cuts.length === 0 && hotCues.length === 0) {
                if (saved.cuts?.length) setCuts(saved.cuts);
                if (saved.hotCues?.length) setHotCues(saved.hotCues);
                toast.info(`Restored ${saved.cuts?.length || 0} edits + ${saved.hotCues?.length || 0} cues from auto-save`);
            }
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [fullTrack?.id, bufferReady]);
}
