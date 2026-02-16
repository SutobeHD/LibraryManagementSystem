import React, { useState } from 'react';
import api from '../api/api';
import { Star, Palette, Save, X } from 'lucide-react';

const COLORS = [
    { id: 0, hex: 'transparent', name: 'None' }, { id: 1, hex: '#db2777', name: 'Pink' },
    { id: 2, hex: '#dc2626', name: 'Red' }, { id: 3, hex: '#ea580c', name: 'Orange' },
    { id: 4, hex: '#ca8a04', name: 'Yellow' }, { id: 5, hex: '#16a34a', name: 'Green' },
    { id: 6, hex: '#06b6d4', name: 'Aqua' }, { id: 7, hex: '#2563eb', name: 'Blue' },
    { id: 8, hex: '#7c3aed', name: 'Purple' }
];

const BatchEditBar = ({ selectedTracks, onClearSelection, onUpdateComplete }) => {
    const [rating, setRating] = useState(0);
    const [colorId, setColorId] = useState(0);
    const [genre, setGenre] = useState("");
    const [saving, setSaving] = useState(false);

    if (selectedTracks.length === 0) return null;

    const handleSave = async () => {
        setSaving(true);
        const updates = {};
        if (rating > 0) updates.Rating = rating;
        if (colorId !== 0) updates.ColorID = colorId;
        if (genre) updates.Genre = genre;

        try {
            await api.patch('/api/tracks/batch', {
                track_ids: selectedTracks.map(t => t.id),
                updates: updates
            });
            onUpdateComplete();
            onClearSelection();
        } catch (err) {
            console.error(err);
            alert("Failed to update tracks");
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="absolute bottom-6 left-1/2 -translate-x-1/2 min-w-[600px] glass-panel rounded-full p-4 flex items-center justify-between z-30 animate-slide-in shadow-[0_10px_40px_rgba(0,0,0,0.5)] bg-gray-900/90 hover:shadow-[0_10px_50px_rgba(168,85,247,0.3)] transition-all">
            <div className="flex items-center gap-6 px-4">
                <span className="text-neon-blue font-bold font-mono tracking-wider">{selectedTracks.length} Selected</span>

                {/* Rating */}
                <div className="flex items-center gap-3 border-l border-white/10 pl-4">
                    <div className="flex gap-1">
                        {[1, 2, 3, 4, 5].map(s => (
                            <Star
                                key={s}
                                size={20}
                                className={`cursor-pointer transition-transform hover:scale-125 ${rating >= s ? 'text-yellow-400 fill-yellow-400' : 'text-gray-600'}`}
                                onClick={() => setRating(rating === s ? 0 : s)}
                            />
                        ))}
                    </div>
                </div>

                {/* Color */}
                <div className="flex items-center gap-2 border-l border-white/10 pl-4">
                    <Palette size={18} className="text-gray-400" />
                    <div className="flex gap-1">
                        {COLORS.map(c => (
                            <button
                                key={c.id}
                                onClick={() => setColorId(colorId === c.id ? '' : c.id)}
                                className={`w-5 h-5 rounded-full border-2 transition-transform hover:scale-125 ${colorId === c.id ? 'border-white scale-125 ring-2 ring-white/50' : 'border-transparent'}`}
                                style={{ backgroundColor: c.hex }}
                                title={c.name}
                            />
                        ))}
                    </div>
                </div>

                {/* Genre */}
                <div className="border-l border-white/10 pl-4">
                    <input
                        value={genre}
                        onChange={(e) => setGenre(e.target.value)}
                        placeholder="Genre..."
                        className="bg-black/40 border border-white/10 px-3 py-1.5 rounded-full text-sm w-32 focus:border-neon-purple outline-none transition-colors text-white"
                    />
                </div>
            </div>

            <div className="flex gap-3 pl-4 border-l border-white/10">
                <button
                    onClick={handleSave}
                    disabled={saving}
                    className="btn-primary rounded-full px-6 py-2 flex items-center gap-2 text-sm"
                >
                    <Save size={16} />
                    {saving ? '...' : 'Apply'}
                </button>
                <button
                    onClick={onClearSelection}
                    className="w-8 h-8 rounded-full bg-white/10 flex items-center justify-center hover:bg-white/20 transition-colors text-gray-300"
                >
                    <X size={16} />
                </button>
            </div>
        </div>
    );
};

export default BatchEditBar;
