import React from 'react';
import { Database, Sparkles, Zap, HardDrive } from 'lucide-react';

const UsbView = () => {
    return (
        <div className="h-full flex flex-col bg-transparent text-white overflow-hidden animate-fade-in">
            <div className="p-8 pb-0">
                <div className="flex items-center gap-4 mb-8">
                    <div className="p-3 bg-indigo-500/20 rounded-xl">
                        <HardDrive size={32} className="text-indigo-400" />
                    </div>
                    <div>
                        <h1 className="text-3xl font-bold italic tracking-tighter uppercase">USB Device Management</h1>
                        <p className="text-slate-400">Manage tracks and playlists for your external hardware</p>
                    </div>
                </div>
            </div>

            <div className="flex-1 p-8 flex flex-col items-center justify-center text-center">
                <div className="glass-panel p-12 rounded-[2.5rem] border border-white/10 max-w-2xl w-full relative overflow-hidden group">
                    <div className="absolute top-0 right-0 p-8 opacity-5 group-hover:opacity-10 transition-opacity pointer-events-none">
                        <HardDrive size={160} className="text-indigo-400" />
                    </div>

                    <div className="w-24 h-24 bg-indigo-500/10 rounded-3xl flex items-center justify-center mb-8 mx-auto border border-indigo-500/20">
                        <Sparkles size={48} className="text-indigo-400 animate-pulse" />
                    </div>

                    <h2 className="text-3xl font-black text-white mb-4 italic uppercase tracking-tight">Coming Soon</h2>
                    <p className="text-slate-400 text-lg leading-relaxed mb-8">
                        The USB Device Management module is currently in development. You will soon be able to directly export playlists, sync metadata changes back to USB devices, and manage your portable library with professional precision.
                    </p>

                    <div className="flex justify-center gap-4">
                        <div className="px-6 py-2 bg-white/5 rounded-full border border-white/10 text-xs font-bold uppercase tracking-widest text-slate-500">
                            Direct Export
                        </div>
                        <div className="px-6 py-2 bg-white/5 rounded-full border border-white/10 text-xs font-bold uppercase tracking-widest text-slate-500">
                            Metadata Sync
                        </div>
                        <div className="px-6 py-2 bg-white/5 rounded-full border border-white/10 text-xs font-bold uppercase tracking-widest text-slate-500">
                            Device Manager
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default UsbView;
