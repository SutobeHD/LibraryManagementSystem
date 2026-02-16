import React, { useEffect, useState } from 'react';
import { X } from 'lucide-react';

export default function SoundCloudProgressModal({ isOpen, onClose }) {
    const [progress, setProgress] = useState({
        stage: 'auth',
        message: 'Initializing...',
        current: 0,
        total: 0,
        trackName: ''
    });

    useEffect(() => {
        if (!isOpen) return;

        let unlisten;

        // Listen to progress events from Rust
        const setupListener = async () => {
            const { listen } = await import('@tauri-apps/api/event');
            unlisten = await listen('sc-export-progress', (event) => {
                setProgress(event.payload);
            });
        };

        setupListener();

        return () => {
            if (unlisten) unlisten();
        };
    }, [isOpen]);

    if (!isOpen) return null;

    const getProgressPercentage = () => {
        if (progress.stage === 'searching' && progress.total > 0) {
            return Math.round((progress.current / progress.total) * 100);
        }
        return 0;
    };

    const getStageTitle = () => {
        switch (progress.stage) {
            case 'auth':
                return '🔐 Authenticating with SoundCloud';
            case 'searching':
                return '🔍 Searching Tracks';
            case 'creating':
                return '📦 Creating Playlist';
            default:
                return 'Processing...';
        }
    };

    return (
        <div className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4">
            <div className="bg-slate-800 rounded-2xl shadow-2xl border border-white/10 max-w-lg w-full p-6">
                {/* Header */}
                <div className="flex items-center justify-between mb-6">
                    <h2 className="text-2xl font-bold text-white flex items-center gap-3">
                        <div className="w-3 h-3 bg-orange-500 rounded-full animate-pulse"></div>
                        Exporting to SoundCloud
                    </h2>
                </div>

                {/* Stage */}
                <div className="mb-4">
                    <div className="text-lg font-semibold text-cyan-400 mb-2">{getStageTitle()}</div>
                    <div className="text-sm text-slate-400">{progress.message}</div>
                </div>

                {/* Progress Bar (only for searching stage) */}
                {progress.stage === 'searching' && progress.total > 0 && (
                    <div className="mb-4">
                        <div className="flex justify-between text-xs text-slate-400 mb-2">
                            <span>Track {progress.current} of {progress.total}</span>
                            <span>{getProgressPercentage()}%</span>
                        </div>
                        <div className="h-3 bg-slate-700 rounded-full overflow-hidden">
                            <div
                                className="h-full bg-gradient-to-r from-orange-600 to-orange-400 transition-all duration-300 ease-out"
                                style={{ width: `${getProgressPercentage()}%` }}
                            ></div>
                        </div>
                        {progress.trackName && (
                            <div className="mt-2 text-xs text-slate-500 truncate">
                                {progress.trackName}
                            </div>
                        )}
                    </div>
                )}

                {/* Spinner for non-searching stages */}
                {progress.stage !== 'searching' && (
                    <div className="flex justify-center py-4">
                        <div className="w-12 h-12 border-4 border-slate-700 border-t-orange-500 rounded-full animate-spin"></div>
                    </div>
                )}

                {/* Info */}
                <div className="mt-6 p-3 bg-slate-900/50 rounded-lg border border-white/5">
                    <p className="text-xs text-slate-400 text-center">
                        Please keep this window open. This process may take several minutes for large playlists.
                    </p>
                </div>
            </div>
        </div>
    );
}
