/**
 * useEditorKeyboard - Wires global keydown shortcuts for the editor.
 *
 * Bindings:
 *   m  - Memory cue           1-8 - Hot cues A-H
 *   l  - Loop                 f   - Fade in
 *   o  - Fade out             s   - Split at playhead
 *   c  - Copy to palette      delete - Delete selected
 *   q  - Toggle snap          g   - Toggle grid edit mode
 *
 * Inputs are ignored while focus is on an <input> element.
 */

import { useEffect } from 'react';

export default function useEditorKeyboard({
    addMarker,
    handleSplit,
    handleCopy,
    handleDelete,
    handleToggleSnap,
    toggleGridMode,
}) {
    useEffect(() => {
        const handleKeyDown = (e) => {
            if (e.target.tagName === 'INPUT') return;

            switch (e.key.toLowerCase()) {
                case 'm': addMarker(0, -1); break; // Memory Cue
                case 'l': addMarker(4, -1); break; // Loop
                case '1': addMarker(0, 0); break;  // Hot Cue A
                case '2': addMarker(0, 1); break;  // Hot Cue B
                case '3': addMarker(0, 2); break;
                case '4': addMarker(0, 3); break;
                case '5': addMarker(0, 4); break;
                case '6': addMarker(0, 5); break;
                case '7': addMarker(0, 6); break;
                case '8': addMarker(0, 7); break;
                case 'f': addMarker(1, -1); break; // Fade In
                case 'o': addMarker(2, -1); break; // Fade Out
                case 's': handleSplit(); break;
                case 'c': handleCopy(); break;
                case 'delete': handleDelete(); break;
                case 'q': handleToggleSnap(); break;
                case 'g': toggleGridMode(); break; // Toggle Grid Edit Mode
            }
        };

        window.addEventListener('keydown', handleKeyDown);
        return () => window.removeEventListener('keydown', handleKeyDown);
    }, [addMarker, handleSplit, handleCopy, handleDelete, handleToggleSnap, toggleGridMode]);
}
