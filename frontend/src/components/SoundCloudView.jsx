import React, { useState, useEffect } from 'react';
import api from '../api/api';
import { Download, Cloud, Key, Info, CheckCircle, XCircle, Loader2, ExternalLink, ShieldCheck, LogIn, RefreshCw } from 'lucide-react';
import { toast } from 'react-hot-toast';
import { invoke } from '@tauri-apps/api/core';
import { listen } from '@tauri-apps/api/event';

const SoundCloudView = () => {
    const [url, setUrl] = useState('');
    // PRIVACY: do not hold the actual OAuth token in React state — the real
    // token lives in the OS keyring on the backend and is never exposed via
    // /api/settings. We track *whether* the user is authenticated as a bool
    // so the UI can render "Reconnect" vs "Login" without ever touching the
    // secret in the renderer process.
    const [hasToken, setHasToken] = useState(false);
    const [isDownloading, setIsDownloading] = useState(false);
    const [tasks, setTasks] = useState({});
    const [isLoggingIn, setIsLoggingIn] = useState(false);
    const [loginMessage, setLoginMessage] = useState('');

    // EC11: Ref-based guard prevents multiple simultaneous login requests
    // even if the user spam-clicks the button before state re-renders.
    const loginInFlightRef = React.useRef(false);

    useEffect(() => {
        // Local-only auth probe — pure keyring lookup, no SC round-trip, no
        // sc:auth-expired interceptor noise on mount.
        api.get('/api/soundcloud/auth-status')
            .then(res => setHasToken(Boolean(res.data?.data?.authenticated)))
            .catch(() => setHasToken(false));

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
            setHasToken(false);
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
            // Hand the secret straight to the backend keyring — never persisted
            // in React state. We flip the local auth-flag once the backend has
            // confirmed it accepted the token.
            await api.post('/api/soundcloud/auth-token', { token: newToken });
            setHasToken(true);
            // Tell the workspace-bar account chip to re-pull /me.
            window.dispatchEvent(new CustomEvent('sc:auth-changed'));
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
        <div className="h-full w-full overflow-y-auto p-4 md:p-8 relative animate-slide-up">
            {/* Ambient brand glow — matches SettingsView */}
            <div className="absolute top-[-20%] right-[-10%] w-[600px] h-[600px] bg-amber2/10 rounded-full blur-[120px] pointer-events-none" />

            <div className="max-w-6xl mx-auto relative z-10">
                {/* Header */}
                <div className="glass-panel px-8 py-6 rounded-3xl shadow-2xl mb-6">
                    <div className="flex items-center gap-5">
                        <div className="p-3.5 bg-amber2/20 rounded-2xl shadow-lg shadow-amber2/10">
                            <Cloud size={36} className="text-amber2" />
                        </div>
                        <div>
                            <h1 className="text-3xl font-bold bg-gradient-to-r from-white to-slate-400 bg-clip-text text-transparent">SoundCloud Downloader</h1>
                            <p className="text-ink-secondary mt-0.5 text-sm">High-Quality (Go+) & Original Lossless Downloads</p>
                        </div>
                    </div>
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                    {/* Download Section */}
                    <div className="lg:col-span-2 space-y-6">
                        <div className="glass-panel p-6 rounded-2xl shadow-2xl">
                            <label className="mx-caption block mb-3">Paste URL (Track or Playlist)</label>
                            <div className="flex gap-3">
                                <input
                                    value={url}
                                    onChange={(e) => setUrl(e.target.value)}
                                    placeholder="https://soundcloud.com/artist/track..."
                                    className="input-glass flex-1 text-base py-3 px-4"
                                />
                                <button
                                    onClick={handleDownload}
                                    disabled={isDownloading || !url}
                                    className="btn-primary flex items-center gap-2 px-6 rounded-xl shadow-lg shadow-amber2/20 disabled:opacity-50"
                                >
                                    {isDownloading ? <Loader2 className="animate-spin" size={18} /> : <Download size={18} />}
                                    Download
                                </button>
                            </div>
                        </div>

                        {/* Task List */}
                        <div className="space-y-3">
                            <h2 className="mx-caption px-1">Active & Recent Tasks</h2>
                            {Object.keys(tasks).length === 0 ? (
                                <div className="glass-panel p-12 rounded-2xl border-dashed flex flex-col items-center justify-center text-ink-placeholder">
                                    <Cloud size={40} className="mb-4 opacity-20" />
                                    <p className="text-sm">No recent downloads</p>
                                </div>
                            ) : (
                                <div className="space-y-3">
                                    {Object.values(tasks).sort((a, b) => b.startTime - a.startTime).map(task => (
                                        <div key={task.id} className="glass-panel p-4 rounded-2xl flex items-center gap-4 group hover:border-line-interactive transition-colors">
                                            <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${task.status === 'Completed' ? 'bg-ok/10 text-ok' : task.status === 'Failed' ? 'bg-bad/10 text-bad' : 'bg-amber2/10 text-amber2'}`}>
                                                {task.status === 'Completed' ? <CheckCircle size={20} /> : task.status === 'Failed' ? <XCircle size={20} /> : <Loader2 className="animate-spin" size={20} />}
                                            </div>
                                            <div className="flex-1 min-w-0">
                                                <div className="flex justify-between items-center mb-1">
                                                    <span className="text-sm font-medium text-ink-primary truncate pr-4">{task.url}</span>
                                                    <span className="mx-caption">{task.status}</span>
                                                </div>
                                                <div className="w-full h-1.5 bg-mx-input rounded-full overflow-hidden">
                                                    <div
                                                        className={`h-full transition-all duration-500 ${task.status === 'Completed' ? 'bg-ok' : task.status === 'Failed' ? 'bg-bad' : 'bg-amber2'}`}
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
                        <div className="glass-panel p-6 rounded-2xl shadow-2xl">
                            <div className="flex items-center justify-between mb-5">
                                <div className="flex items-center gap-3">
                                    <ShieldCheck className={hasToken ? "text-ok" : "text-amber2"} size={20} />
                                    <h2 className="font-bold text-ink-primary">Go+ Authentication</h2>
                                </div>
                                {hasToken && <span className="text-[10px] font-bold text-ok uppercase flex items-center gap-1"><CheckCircle size={10} /> Authenticated</span>}
                            </div>

                            <p className="text-xs text-ink-secondary mb-6 leading-relaxed">
                                {hasToken ? "Your SoundCloud account is connected. You can download high-quality tracks and playlists." : "Log in to your SoundCloud account to download full tracks in 256kbps AAC or original lossless files."}
                            </p>

                            <button
                                onClick={handleLogin}
                                disabled={isLoggingIn}
                                className={`w-full flex flex-col items-center justify-center gap-2 py-4 rounded-xl font-bold transition-colors ${isLoggingIn ? 'bg-amber2/20 text-amber2-hover' : 'bg-amber2 hover:bg-amber2-hover text-mx-deepest'}`}
                            >
                                <div className="flex items-center gap-2">
                                    {isLoggingIn ? <Loader2 size={16} className="animate-spin" /> : (hasToken ? <RefreshCw size={16} /> : <LogIn size={16} />)}
                                    {isLoggingIn ? 'Authenticating...' : (hasToken ? 'Reconnect Account' : 'Login with SoundCloud')}
                                </div>
                                {isLoggingIn && loginMessage && (
                                    <span className="text-[10px] uppercase tracking-widest opacity-80">{loginMessage}</span>
                                )}
                            </button>
                        </div>

                        <div className="glass-panel p-6 rounded-2xl text-center">
                            <p className="mx-caption mb-4">Quick Links</p>
                            <a
                                href="https://soundcloud.com"
                                target="_blank"
                                rel="noreferrer"
                                className="flex items-center justify-center gap-2 text-xs font-bold text-ink-primary hover:text-amber2 transition-colors"
                            >
                                Open SoundCloud <ExternalLink size={12} />
                            </a>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default SoundCloudView;
