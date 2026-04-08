import React, { useState, useEffect } from 'react';
import api from '../api/api';
import { Download, Cloud, Key, Info, CheckCircle, XCircle, Loader2, ExternalLink, ShieldCheck, LogIn, RefreshCw } from 'lucide-react';
import { toast } from 'react-hot-toast';
import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';

const SoundCloudView = () => {
    const [url, setUrl] = useState('');
    const [token, setToken] = useState('');
    const [isDownloading, setIsDownloading] = useState(false);
    const [tasks, setTasks] = useState({});
    const [isLoggingIn, setIsLoggingIn] = useState(false);
    const [loginMessage, setLoginMessage] = useState('');

    // EC11: Ref-based guard prevents multiple simultaneous login requests
    // even if the user spam-clicks the button before state re-renders.
    const loginInFlightRef = React.useRef(false);

    useEffect(() => {
        // Load existing token
        api.get('/api/settings').then(res => {
            if (res.data.soundcloud_auth_token) {
                setToken(res.data.soundcloud_auth_token);
            }
        }).catch(() => { /* settings may not be loaded yet — ignore */ });

        // EC12: Poll for tasks; .catch() ensures a failed request never freezes the spinner.
        const interval = setInterval(() => {
            api.get('/api/soundcloud/tasks')
                .then(res => {
                    setTasks(res.data ?? {});
                    const active = Object.values(res.data ?? {}).some(
                        t => t.status === 'Downloading' || t.status === 'Starting'
                    );
                    if (!active) setIsDownloading(false);
                })
                .catch(() => {
                    // Silently ignore polling errors — avoids frozen spinner (EC12)
                });
        }, 3000);

        // Listen to native auth events (only available in Tauri desktop context)
        let unlisten = null;
        if (window.__TAURI__) {
            unlisten = listen('sc-login-progress', (event) => {
                const data = event.payload;
                setLoginMessage(data.message);
            });
        }

        // EC7: React to the global 'sc:auth-expired' event from the Axios interceptor
        const onAuthExpired = () => {
            setToken('');
            setLoginMessage('');
        };
        window.addEventListener('sc:auth-expired', onAuthExpired);

        return () => {
            clearInterval(interval);
            if (unlisten) unlisten.then(f => f());
            window.removeEventListener('sc:auth-expired', onAuthExpired);
        };
    }, []);

    const handleDownload = async () => {
        if (!url) {
            toast.error("Please enter a SoundCloud URL");
            return;
        }
        setIsDownloading(true);
        try {
            await api.post('/api/soundcloud/download', { url });
            toast.success("Download started!");
            setUrl('');
        } catch (err) {
            toast.error("Failed to start download");
            setIsDownloading(false);
        }
    };

    const handleLogin = async () => {
        // EC11: Block concurrent login calls — ref check is synchronous,
        // unlike setState which batches and may fire twice.
        if (loginInFlightRef.current) return;
        loginInFlightRef.current = true;

        setIsLoggingIn(true);
        setLoginMessage('Initializing secure login...');
        try {
            const newToken = await invoke('login_to_soundcloud');
            setLoginMessage('Saving credentials securely...');
            // Save token via HttpOnly cookie securely
            await api.post('/api/soundcloud/auth-token', { token: newToken });
            setToken(newToken);
            toast.success('SoundCloud Login erfolgreich!');
        } catch (e) {
            const errStr = String(e);
            // Distinguish Tauri unavailability from real auth errors
            if (errStr.includes('invoke') || errStr.includes('TAURI') || errStr.includes('undefined')) {
                toast.error('Login ist nur in der Desktop-App verfügbar.');
            } else {
                toast.error(`Login fehlgeschlagen: ${errStr}`);
            }
        } finally {
            setIsLoggingIn(false);
            setLoginMessage('');
            loginInFlightRef.current = false;
        }
    };

    return (
        <div className="p-8 max-w-6xl mx-auto animate-fade-in">
            <div className="flex items-center gap-4 mb-8">
                <div className="w-12 h-12 bg-orange-500 rounded-2xl flex items-center justify-center shadow-lg shadow-orange-500/20">
                    <Cloud className="text-white" size={28} />
                </div>
                <div>
                    <h1 className="text-3xl font-bold text-white tracking-tight">SoundCloud Downloader</h1>
                    <p className="text-slate-400">High-Quality (Go+) & Original Lossless Downloads</p>
                </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
                {/* Download Section */}
                <div className="lg:col-span-2 space-y-8">
                    <div className="glass-panel p-8 rounded-3xl border border-white/10 bg-black/40 backdrop-blur-xl">
                        <label className="block text-[10px] font-black text-slate-500 uppercase tracking-[0.2em] mb-4">Paste URL (Track or Playlist)</label>
                        <div className="flex gap-4">
                            <input
                                value={url}
                                onChange={(e) => setUrl(e.target.value)}
                                placeholder="https://soundcloud.com/artist/track..."
                                className="input-glass flex-1 text-lg py-4 px-6"
                            />
                            <button
                                onClick={handleDownload}
                                disabled={isDownloading || !url}
                                className={`px-8 rounded-2xl font-bold flex items-center gap-3 transition-all ${isDownloading || !url ? 'bg-slate-800 text-slate-500' : 'bg-orange-500 hover:bg-orange-400 text-white shadow-lg shadow-orange-500/40 transform hover:-translate-y-1'}`}
                            >
                                {isDownloading ? <Loader2 className="animate-spin" size={20} /> : <Download size={20} />}
                                Download
                            </button>
                        </div>
                    </div>

                    {/* Task List */}
                    <div className="space-y-4">
                        <h2 className="text-sm font-bold text-slate-400 uppercase tracking-widest px-2">Active & Recent Tasks</h2>
                        {Object.keys(tasks).length === 0 ? (
                            <div className="glass-panel p-12 rounded-3xl border border-dashed border-white/5 flex flex-col items-center justify-center text-slate-600">
                                <Cloud size={40} className="mb-4 opacity-20" />
                                <p>No recent downloads</p>
                            </div>
                        ) : (
                            <div className="space-y-3">
                                {Object.values(tasks).sort((a, b) => b.startTime - a.startTime).map(task => (
                                    <div key={task.id} className="glass-panel p-4 rounded-2xl border border-white/5 flex items-center gap-4 group hover:border-white/10 transition-colors">
                                        <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${task.status === 'Completed' ? 'bg-green-500/10 text-green-500' : task.status === 'Failed' ? 'bg-red-500/10 text-red-500' : 'bg-orange-500/10 text-orange-500'}`}>
                                            {task.status === 'Completed' ? <CheckCircle size={20} /> : task.status === 'Failed' ? <XCircle size={20} /> : <Loader2 className="animate-spin" size={20} />}
                                        </div>
                                        <div className="flex-1 min-w-0">
                                            <div className="flex justify-between items-center mb-1">
                                                <span className="text-sm font-medium text-slate-200 truncate pr-4">{task.url}</span>
                                                <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">{task.status}</span>
                                            </div>
                                            <div className="w-full h-1.5 bg-white/5 rounded-full overflow-hidden">
                                                <div
                                                    className={`h-full transition-all duration-500 ${task.status === 'Completed' ? 'bg-green-500' : task.status === 'Failed' ? 'bg-red-500' : 'bg-orange-500'}`}
                                                    style={{ width: `${task.progress}%` }}
                                                />
                                            </div>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                </div>

                {/* Settings & Auth Section */}
                <div className="space-y-6">
                    <div className="glass-panel p-6 rounded-3xl border border-white/10 bg-white/5 backdrop-blur-md">
                        <div className="flex items-center justify-between mb-6">
                            <div className="flex items-center gap-3">
                                <ShieldCheck className={token ? "text-emerald-400" : "text-cyan-400"} size={20} />
                                <h2 className="font-bold text-white">Go+ Authentication</h2>
                            </div>
                            {token && <span className="text-[10px] font-bold text-emerald-500 uppercase flex items-center gap-1"><CheckCircle size={10} /> Authenticated</span>}
                        </div>

                        <p className="text-xs text-slate-400 mb-6 leading-relaxed">
                            {token ? "Your SoundCloud account is connected. You can download high-quality tracks and playlists." : "Log in to your SoundCloud account to download full tracks in 256kbps AAC or original lossless files."}
                        </p>

                        <button
                            onClick={handleLogin}
                            disabled={isLoggingIn}
                            className={`w-full flex flex-col items-center justify-center gap-2 py-4 ${isLoggingIn ? 'bg-orange-500/20 text-orange-400' : 'bg-orange-500 hover:bg-orange-400 text-white'} rounded-xl font-bold transition-colors`}
                        >
                            <div className="flex items-center gap-2">
                                {isLoggingIn ? <Loader2 size={16} className="animate-spin" /> : (token ? <RefreshCw size={16} /> : <LogIn size={16} />)}
                                {isLoggingIn ? 'Authenticating...' : (token ? 'Reconnect Account' : 'Login with SoundCloud')}
                            </div>
                            {isLoggingIn && loginMessage && (
                                <span className="text-[10px] uppercase tracking-widest opacity-80">{loginMessage}</span>
                            )}
                        </button>
                    </div>

                    <div className="glass-panel p-6 rounded-3xl border border-white/5 bg-black/20 text-center">
                        <p className="text-[10px] text-slate-500 mb-4 uppercase tracking-[0.2em] font-black">Quick Links</p>
                        <a
                            href="https://soundcloud.com"
                            target="_blank"
                            rel="noreferrer"
                            className="flex items-center justify-center gap-2 text-xs font-bold text-slate-300 hover:text-white transition-colors"
                        >
                            Open SoundCloud <ExternalLink size={12} />
                        </a>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default SoundCloudView;
