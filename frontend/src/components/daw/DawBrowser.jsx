/**
 * DawBrowser — Left panel file/library browser for the DJ Edit DAW
 * 
 * Lists tracks from the library and recent .rbep projects.
 * Tracks can be clicked to load into the editor.
 * Now includes Palette tab and collapse toggle.
 */

import React, { useState, useEffect } from 'react';
import { Search, Music, FolderOpen, Grid, ChevronDown, ChevronUp, FileAudio } from 'lucide-react';
import api from '../../api/api';

const DawBrowser = React.memo(({ onLoadTrack, onOpenProject, isCollapsed, onToggleCollapse }) => {
    const [searchQuery, setSearchQuery] = useState('');
    const [tracks, setTracks] = useState([]);
    const [projects, setProjects] = useState([]);
    const [activeSection, setActiveSection] = useState('library'); // 'library' | 'projects' | 'palette'
    const [isLoading, setIsLoading] = useState(false);

    // Load library tracks
    useEffect(() => {
        const fetchTracks = async () => {
            setIsLoading(true);
            try {
                const res = await api.get('/api/library/tracks', { params: { limit: 100 } });
                setTracks(res.data?.tracks || []);
            } catch (err) {
                console.warn('[DawBrowser] Failed to load tracks:', err);
            }
            setIsLoading(false);
        };
        fetchTracks();
    }, []);

    // Load recent projects
    useEffect(() => {
        const fetchProjects = async () => {
            try {
                const res = await api.get('/api/projects/recent');
                setProjects(res.data?.projects || []);
            } catch {
                // Projects endpoint may not exist yet
                setProjects([]);
            }
        };
        fetchProjects();
    }, []);

    // Filter tracks by search
    const filteredTracks = searchQuery
        ? tracks.filter(t =>
            (t.title || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
            (t.artist || '').toLowerCase().includes(searchQuery.toLowerCase())
        )
        : tracks;

    return (
        <div className="w-full h-full flex flex-col bg-slate-950/80 border-t border-white/5">
            {/* Header / Tabs / Search */}
            <div className="flex items-center justify-between px-2 py-1 border-b border-white/5 bg-slate-900/50 h-[32px] shrink-0">
                <div className="flex gap-1 overflow-x-auto no-scrollbar">
                    <TabButton
                        icon={<Music size={10} />}
                        label="Library"
                        active={activeSection === 'library'}
                        onClick={() => setActiveSection('library')}
                    />
                    <TabButton
                        icon={<FolderOpen size={10} />}
                        label="Projects"
                        active={activeSection === 'projects'}
                        onClick={() => setActiveSection('projects')}
                    />
                    <TabButton
                        icon={<Grid size={10} />}
                        label="Palette"
                        active={activeSection === 'palette'}
                        onClick={() => setActiveSection('palette')}
                    />
                </div>

                <div className="flex items-center gap-2">
                    {/* Search only visible if not collapsed (or if enough space) */}
                    <div className={`flex items-center gap-2 bg-slate-800/50 rounded px-2 py-0.5 border border-white/5 w-48 transition-opacity ${isCollapsed ? 'opacity-0 pointer-events-none' : 'opacity-100'}`}>
                        <Search size={10} className="text-slate-500 shrink-0" />
                        <input
                            type="text"
                            placeholder="Search..."
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            className="bg-transparent text-[10px] text-white placeholder-slate-600 w-full focus:outline-none"
                            disabled={isCollapsed}
                        />
                    </div>

                    {/* Collapse Toggle */}
                    <button
                        onClick={onToggleCollapse}
                        className="p-1 text-slate-500 hover:text-white transition-colors"
                        title={isCollapsed ? "Expand" : "Collapse"}
                    >
                        {isCollapsed ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                    </button>
                </div>
            </div>

            {/* Content Area (Hidden if collapsed via parent height, but we render content anyway) */}
            <div className={`flex-1 overflow-hidden flex flex-col ${isCollapsed ? 'invisible' : 'visible'}`}>
                {activeSection === 'library' && (
                    <>
                        {/* Column Headers */}
                        <div className="flex items-center px-4 py-1 text-[10px] font-bold text-slate-500 border-b border-white/5 bg-slate-900/30 shrink-0">
                            <div className="w-1/3">Title</div>
                            <div className="w-1/4">Artist</div>
                            <div className="w-16 text-right">BPM</div>
                            <div className="w-16 text-right ml-4">Key</div>
                        </div>

                        {/* List */}
                        <div className="flex-1 overflow-y-auto custom-scrollbar bg-slate-950/30">
                            {isLoading ? (
                                <div className="flex items-center justify-center py-8">
                                    <div className="w-4 h-4 border-2 border-cyan-500/30 border-t-cyan-500 rounded-full animate-spin" />
                                </div>
                            ) : filteredTracks.length === 0 ? (
                                <p className="text-xs text-slate-600 text-center py-8">
                                    {searchQuery ? 'No matches' : 'No tracks loaded'}
                                </p>
                            ) : (
                                filteredTracks.map((track) => (
                                    <div
                                        key={track.id || track.TrackID}
                                        onDoubleClick={() => onLoadTrack?.(track)}
                                        className="flex items-center px-4 py-1 hover:bg-white/5 transition-colors group cursor-pointer border-b border-white/5 text-xs text-slate-300"
                                    >
                                        <div className="w-1/3 truncate font-medium text-white group-hover:text-cyan-400">
                                            {track.title || track.Title || 'Untitled'}
                                        </div>
                                        <div className="w-1/4 truncate text-slate-400">
                                            {track.artist || track.Artist || 'Unknown'}
                                        </div>
                                        <div className="w-16 text-right font-mono text-slate-500">
                                            {(track.bpm || track.BPM)?.toFixed(1) || '-'}
                                        </div>
                                        <div className="w-16 text-right ml-4 font-mono text-slate-500">
                                            {track.key || track.Key || '-'}
                                        </div>
                                    </div>
                                ))
                            )}
                        </div>
                    </>
                )}

                {activeSection === 'projects' && (
                    <div className="flex-1 overflow-y-auto custom-scrollbar p-2">
                        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
                            {projects.length === 0 ? (
                                <p className="col-span-full text-xs text-slate-600 text-center py-8">No recent projects</p>
                            ) : (
                                projects.map((prj, idx) => (
                                    <button
                                        key={idx}
                                        onClick={() => onOpenProject?.(prj.filepath)}
                                        className="flex items-center gap-2 px-3 py-2 rounded bg-slate-800/40 hover:bg-white/10 border border-white/5 text-left transition-all"
                                    >
                                        <FileAudio size={16} className="text-cyan-500/70 shrink-0" />
                                        <div className="min-w-0">
                                            <div className="text-xs text-white truncate group-hover:text-cyan-400">
                                                {prj.name || 'Untitled'}
                                            </div>
                                            <div className="text-[10px] text-slate-500 truncate">
                                                {prj.filepath}
                                            </div>
                                        </div>
                                    </button>
                                ))
                            )}
                        </div>
                    </div>
                )}

                {activeSection === 'palette' && (
                    <div className="flex-1 flex flex-col items-center justify-center text-slate-600">
                        <Grid size={32} className="mb-2 opacity-50" />
                        <p className="text-xs font-semibold">Palette Browser</p>
                        <p className="text-[10px] opacity-75">Work in progress</p>
                    </div>
                )}
            </div>
        </div>
    );
});

const TabButton = ({ icon, label, active, onClick }) => (
    <button
        onClick={onClick}
        className={`flex items-center px-3 py-1 text-[10px] uppercase font-bold rounded-t-lg transition-colors border-b-2 ${active
                ? 'bg-white/5 text-cyan-400 border-cyan-500'
                : 'text-slate-500 hover:text-slate-300 border-transparent hover:bg-white/5'
            }`}
    >
        <span className="mr-1">{icon}</span>
        {label}
    </button>
);

DawBrowser.displayName = 'DawBrowser';

export default DawBrowser;
