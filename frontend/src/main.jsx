import React, { useState, Component, useEffect, useCallback, Suspense, lazy } from 'react'
import { invoke } from '@tauri-apps/api/core'; // Tauri Invoke
import ReactDOM from 'react-dom/client'
import { Music, Cloud, Download, Scissors, Settings, Folder, Wrench, Zap, FileCode, AlertTriangle, Upload, X, Database, ArrowRightLeft, RotateCw, Activity, BarChart3, HardDrive, Loader2, Sparkles } from 'lucide-react'
import './index.css'
import { ToastProvider } from './components/ToastContext'
import { Toaster } from 'react-hot-toast'

// SPEED: Lazy-load heavy views — only the active view is loaded into the bundle
// const WaveformEditor = lazy(() => import('./components/WaveformEditor')); // Replaced by DjEditDaw
const DjEditDaw = lazy(() => import('./components/daw/DjEditDaw'));
const ToolsView = lazy(() => import('./components/ToolsView'));
const SettingsView = lazy(() => import('./components/SettingsView'));
const RankingView = lazy(() => import('./components/RankingView'));
const XmlCleanView = lazy(() => import('./components/XmlCleanView'));
const MetadataView = lazy(() => import('./components/MetadataView'));
const ImportView = lazy(() => import('./components/ImportView'));
const InsightsView = lazy(() => import('./components/InsightsView'));
const UsbView = lazy(() => import('./components/UsbView'));
const BackupManager = lazy(() => import('./components/BackupManager'));
const DesignView = lazy(() => import('./components/DesignView'));
const SoundCloudView = lazy(() => import('./components/SoundCloudView'));
const SoundCloudSyncView = lazy(() => import('./components/SoundCloudSyncView'));

import api, { setSessionToken, getSessionToken } from './api/api'

// Error Boundary Configuration
class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }
  static getDerivedStateFromError(error) { return { hasError: true, error }; }
  componentDidCatch(error, errorInfo) { console.error("View Error:", error, errorInfo); }
  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center h-full text-center p-8 glass-panel m-8 rounded-2xl">
          <div className="bg-red-500/20 p-4 rounded-full mb-4 animate-bounce">
            <AlertTriangle size={48} className="text-red-500" />
          </div>
          <h2 className="text-2xl font-bold mb-2 text-white">Something went wrong</h2>
          <p className="text-slate-400 mb-6 max-w-md">{this.state.error?.message || "An unexpected error occurred in this view."}</p>
          <button
            onClick={() => this.setState({ hasError: false })}
            className="btn-primary"
          >
            Try Again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

const Sidebar = ({ activeTab, setActiveTab, libraryStatus, onLoadLibrary, onUnloadLibrary }) => {
  const [showBackups, setShowBackups] = useState(false);

  const handleExit = async () => {
    if (confirm("Exit Application?")) {
      try {
        const token = getSessionToken();
        await api.post('/api/system/shutdown', null, { params: { token } });
      }
      catch (e) { }
      window.close();
      document.body.innerHTML = "<div style='color:white;display:flex;justify-content:center;height:100vh;align-items:center;background:#0f172a;font-family:sans-serif'>Application Closed</div>";
    }
  };

  return (
    <>
      <div className="w-64 h-screen flex flex-col relative z-20 shrink-0">
        {/* Logo Area */}
        <div className="p-8 pb-6">
          <div className="flex items-center gap-3 mb-1">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan-500 to-blue-600 flex items-center justify-center shadow-lg shadow-cyan-500/20">
              <Zap size={20} className="text-white fill-white" />
            </div>
            <div className="text-lg font-bold tracking-tight text-white font-sans">
              MUSIC LIBRARY
            </div>
          </div>
          <div className="text-[10px] font-bold text-cyan-500 tracking-[0.2em] pl-11 uppercase opacity-90">MANAGER</div>

          {/* Library Status Indicator */}
          <div className="mt-6 px-4">
            <div className={`p-3 rounded-lg border flex items-center justify-between ${libraryStatus?.loaded ? 'bg-emerald-900/20 border-emerald-500/30' : 'bg-rose-900/10 border-rose-500/20'}`}>
              <div className="flex items-center gap-2">
                <div className={`w-2 h-2 rounded-full ${libraryStatus?.loaded ? 'bg-emerald-400 shadow-[0_0_8px_#34d399]' : 'bg-rose-400 shadow-[0_0_8px_#fb7185]'}`}></div>
                <div className="flex flex-col">
                  <span className={`text-[10px] font-bold uppercase ${libraryStatus?.loaded ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {libraryStatus?.loaded ? 'Library Active' : 'No Library'}
                  </span>
                  {libraryStatus?.loaded && <span className="text-[9px] text-slate-500">{libraryStatus.tracks} Tracks</span>}
                </div>
              </div>
              {!libraryStatus?.loaded ? (
                <button
                  onClick={onLoadLibrary}
                  className="p-1.5 bg-rose-500 hover:bg-rose-400 text-white rounded transition-colors"
                  title="Load Default Library"
                >
                  <Zap size={12} />
                </button>
              ) : (
                <button
                  onClick={onUnloadLibrary}
                  className="p-1.5 bg-slate-800 hover:bg-red-500/20 text-slate-400 hover:text-red-400 rounded transition-colors border border-white/5"
                  title="Unload Library"
                >
                  <X size={12} />
                </button>
              )}
            </div>
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 px-4 space-y-1 mt-6 overflow-y-auto">
          <NavBtn icon={<Upload size={18} />} label="Audio Import" active={activeTab === 'import'} onClick={() => setActiveTab('import')} />
          <NavBtn icon={<Music size={18} />} label="Library" active={activeTab === 'library'} onClick={() => setActiveTab('library')} />
          <NavBtn icon={<Zap size={18} />} label="Ranking Mode" active={activeTab === 'ranking'} onClick={() => setActiveTab('ranking')} />
          <NavBtn icon={<Sparkles size={18} className="text-cyan-400" />} label="Design Lab" active={activeTab === 'design'} onClick={() => setActiveTab('design')} />
          <NavBtn icon={<Scissors size={18} />} label="Waveform Editor" active={activeTab === 'editor'} onClick={() => setActiveTab('editor')} />
          <NavBtn icon={<HardDrive size={18} />} label="USB" active={activeTab === 'usb'} onClick={() => setActiveTab('usb')} />
          <NavBtn icon={<Wrench size={18} />} label="Utilities" active={activeTab === 'tools'} onClick={() => setActiveTab('tools')} />
          {libraryStatus?.mode === 'xml' && (
            <NavBtn icon={<FileCode size={18} />} label="XML Automator" active={activeTab === 'xml'} onClick={() => setActiveTab('xml')} />
          )}
          <div className="pt-4 mt-4 border-t border-white/5">
            <NavBtn icon={<Cloud size={18} className="text-orange-500" />} label="SC Download" active={activeTab === 'soundcloud'} onClick={() => setActiveTab('soundcloud')} />
            <NavBtn icon={<ArrowRightLeft size={18} className="text-orange-400" />} label="SC Playlist Manager" active={activeTab === 'sc-sync'} onClick={() => setActiveTab('sc-sync')} />
            <NavBtn icon={<Activity size={18} />} label="Insights" active={activeTab === 'insights'} onClick={() => setActiveTab('insights')} />
          </div>
        </nav>

        {/* Footer Settings */}
        <div className="p-4 mt-auto">
          {libraryStatus?.loaded && libraryStatus?.mode === 'live' && (
            <div onClick={() => setShowBackups(true)} className="nav-item group mb-1">
              <Database size={18} className="text-emerald-500 group-hover:text-emerald-400" />
              <span className="font-medium text-sm text-emerald-500 group-hover:text-emerald-400">Backups</span>
            </div>
          )}
          <NavBtn icon={<Settings size={18} />} label="Settings" active={activeTab === 'settings'} onClick={() => setActiveTab('settings')} />
          <div onClick={handleExit} className="nav-item group mt-1">
            <AlertTriangle size={18} className="text-rose-500 group-hover:text-rose-400" />
            <span className="font-medium text-sm text-rose-500 group-hover:text-rose-400">Exit</span>
          </div>
        </div>
      </div>

      {/* Backup Manager Modal */}
      {showBackups && <Suspense fallback={<div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center"><Loader2 className="animate-spin text-cyan-400" size={32} /></div>}><BackupManager onClose={() => setShowBackups(false)} /></Suspense>}
    </>
  )
}

const NavBtn = ({ icon, label, active, onClick }) => (
  <div onClick={onClick} className={`nav-item ${active ? 'active' : ''}`}>
    {icon}
    <span className="font-medium text-sm">{label}</span>
  </div>
)

const SelectionView = ({ onSelect }) => (
  <div className="fixed inset-0 z-[110] bg-slate-950 flex flex-col items-center justify-center p-8 animate-fade-in">
    <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[800px] bg-cyan-600/5 rounded-full blur-[120px] pointer-events-none"></div>

    <div className="relative z-10 flex flex-col items-center max-w-4xl w-full">
      <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-cyan-500 to-blue-600 flex items-center justify-center shadow-2xl shadow-cyan-500/20 mb-12 animate-float">
        <Zap size={40} className="text-white fill-white" />
      </div>

      <h1 className="text-5xl font-black text-white mb-4 tracking-tighter uppercase italic">Select Mode</h1>
      <p className="text-slate-400 text-lg mb-16 text-center max-w-md">Choose your library source to continue.</p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-8 w-full max-w-3xl">
        <button
          onClick={() => onSelect('live')}
          className="group relative p-8 glass-panel rounded-3xl border border-white/5 hover:border-cyan-500/50 transition-all hover:scale-[1.02] text-left overflow-hidden shadow-2xl shadow-black/50"
        >
          <div className="absolute top-0 right-0 p-6 opacity-10 group-hover:opacity-30 transition-opacity">
            <Zap size={120} className="text-cyan-400" />
          </div>
          <div className="w-12 h-12 rounded-xl bg-cyan-500/20 flex items-center justify-center mb-6 text-cyan-400">
            <Zap size={24} />
          </div>
          <h3 className="text-2xl font-bold text-white mb-2 italic uppercase">Rekordbox Live</h3>
          <p className="text-slate-400 text-sm leading-relaxed">Direct integration with your master.db. Fast, live edits and backups.</p>
        </button>

        <button
          onClick={() => onSelect('xml')}
          className="group relative p-8 glass-panel rounded-3xl border border-white/5 hover:border-amber-500/50 transition-all hover:scale-[1.02] text-left overflow-hidden shadow-2xl shadow-black/50"
        >
          <div className="absolute top-0 right-0 p-6 opacity-10 group-hover:opacity-30 transition-opacity">
            <FileCode size={120} className="text-amber-400" />
          </div>
          <div className="w-12 h-12 rounded-xl bg-amber-500/20 flex items-center justify-center mb-6 text-amber-400">
            <FileCode size={24} />
          </div>
          <h3 className="text-2xl font-bold text-white mb-2 italic uppercase">XML Snapshot</h3>
          <p className="text-slate-400 text-sm leading-relaxed">Standard XML-based workflow. Best for analyzing and cleaning exports.</p>
        </button>
      </div>
    </div>
  </div>
);

import Player from './components/Player'

// SPEED: Suspense loading fallback for lazy-loaded views
const ViewLoader = () => (
  <div className="flex items-center justify-center h-full">
    <div className="flex flex-col items-center gap-3">
      <Loader2 className="animate-spin text-cyan-400" size={32} />
      <span className="text-xs text-slate-500 uppercase tracking-widest font-bold">Loading View</span>
    </div>
  </div>
);

const App = () => {
  const [appMode, setAppMode] = useState('choice')
  const [activeTab, setActiveTab] = useState('library')
  const [activeTrack, setActiveTrack] = useState(null)
  const [playerTrack, setPlayerTrack] = useState(null)
  const [libraryStatus, setLibraryStatus] = useState({ loaded: false, mode: 'live', tracks: 0, playlists: 0 })
  const [isInitialLoading, setIsInitialLoading] = useState(false)

  const checkLibraryStatus = useCallback(async () => {
    try {
      const res = await api.get('/api/library/status');
      setLibraryStatus(res.data);
      if (res.data.loaded) {
        setIsInitialLoading(false);
      }
    } catch (e) {
      console.error("Failed to check library status", e);
    }
  }, []);

  const handleModeSelect = useCallback(async (mode) => {
    setAppMode(mode);
    setIsInitialLoading(true);
    try {
      await api.post('/api/library/mode', { mode });
      setActiveTab(mode === 'xml' ? 'xml' : 'library');
    } catch (e) {
      console.error("Mode select failed", e);
    }
  }, []);

  const handleLoadLibrary = useCallback(async () => {
    try {
      const res = await api.post('/api/library/load');
      if (res.data.status === 'success') {
        checkLibraryStatus();
      } else {
        alert("Failed to load library: " + res.data.message);
      }
    } catch (e) {
      alert("Error loading library");
    }
  }, [checkLibraryStatus]);

  const handleUnloadLibrary = useCallback(async () => {
    if (!confirm("Are you sure you want to unload the library?")) return;
    try {
      await api.post('/api/library/unload');
      setAppMode('choice');
      setLibraryStatus({ loaded: false, mode: 'live', tracks: 0, playlists: 0 });
    } catch (e) { console.error(e); }
  }, []);

  useEffect(() => {
    // SPEED: Heartbeat at 5s instead of 2s — sufficient for keepalive
    const hbInterval = setInterval(async () => {
      try {
        const res = await fetch('http://localhost:8000/api/system/heartbeat', { method: 'POST' });
        const data = await res.json();
        // SECURITY: Capture session token from heartbeat response
        if (data.token) {
          setSessionToken(data.token);
        }
      } catch (e) { /* backend offline */ }
    }, 5000);

    const checkInterval = setInterval(() => {
      if (appMode !== 'choice' && !libraryStatus.loaded) {
        checkLibraryStatus();
      }
    }, 1000);

    // RESTORED: Splash Screen Close Logic
    setTimeout(() => {
      invoke('close_splashscreen').catch(console.error);
    }, 2000); // Minimum 2s splash screen visibility

    // Auto-load remembered mode
    const autoInit = async () => {
      try {
        const res = await api.get('/api/settings');
        if (res.data.remember_lib_mode && res.data.last_lib_mode) {
          handleModeSelect(res.data.last_lib_mode);
        }
      } catch (e) { console.error("Auto-init failed", e); }
    };
    autoInit();

    return () => {
      clearInterval(hbInterval);
      clearInterval(checkInterval);
    };
  }, [libraryStatus.loaded, appMode, checkLibraryStatus, handleModeSelect]);

  const handleTrackSelect = useCallback((track) => { setActiveTrack(track); }, []);
  const handleTrackEdit = useCallback((track) => { setActiveTrack(track); setActiveTab('editor'); }, []);
  const handlePlayTrack = useCallback((track) => { setPlayerTrack(track); }, []);

  return (
    <div className="flex h-screen w-screen bg-slate-950 text-slate-200 overflow-hidden font-sans selection:bg-cyan-500/30">
      {appMode === 'choice' && <SelectionView onSelect={handleModeSelect} />}

      {isInitialLoading && (
        <div className="fixed inset-0 z-[120] bg-slate-950 flex flex-col items-center justify-center p-8 animate-fade-in font-sans">
          {/* Loading UI omitted for brevity, same as before */}
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-96 h-96 bg-cyan-600/10 rounded-full blur-[100px] animate-pulse"></div>
          <div className="relative z-10 flex flex-col items-center max-w-md w-full">
            <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-cyan-500 to-blue-600 flex items-center justify-center shadow-2xl shadow-cyan-500/20 mb-8 animate-bounce">
              <Zap size={32} className="text-white fill-white" />
            </div>
            <h1 className="text-3xl font-bold text-white mb-2 tracking-tight italic uppercase">Loading Library</h1>
            <p className="text-cyan-500 font-bold text-[10px] tracking-[0.3em] uppercase mb-12">Music Library Manager</p>
            <div className="w-full h-1.5 bg-white/5 rounded-full overflow-hidden mb-4 border border-white/5 shadow-inner">
              <div
                className="h-full bg-gradient-to-r from-cyan-500 to-blue-500 transition-all duration-500 ease-out"
                style={{ width: libraryStatus.loaded ? '100%' : (libraryStatus.tracks > 0 ? '75%' : '20%') }}
              ></div>
            </div>
            <div className="flex justify-between w-full px-1 mb-8">
              <span className="text-[10px] font-bold text-slate-500 uppercase">Status</span>
              <span className="text-[10px] font-bold text-cyan-400 uppercase">
                {libraryStatus.loaded ? 'Success' : `Initializing ${appMode.toUpperCase()}...`}
              </span>
            </div>
            {!libraryStatus.loaded && (
              <button
                onClick={() => setIsInitialLoading(false)}
                className="mt-12 text-[10px] text-slate-600 hover:text-slate-400 underline transition-colors uppercase tracking-widest font-bold"
              >
                Manual Bypass
              </button>
            )}
          </div>
        </div>
      )}

      <Sidebar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        libraryStatus={libraryStatus}
        onLoadLibrary={handleLoadLibrary}
        onUnloadLibrary={handleUnloadLibrary}
      />

      <main className="flex-1 h-full overflow-hidden relative z-10 bg-slate-950/50">
        <div className="h-full w-full relative pb-20">
          <Suspense fallback={<ViewLoader />}>
            {/* STABILITY: Each view wrapped in its own ErrorBoundary */}
            <div className={activeTab === 'library' ? 'h-full' : 'hidden'}>
              <ErrorBoundary key="eb-library">
                <MetadataView onSelectTrack={handleTrackSelect} onEditTrack={handleTrackEdit} onPlayTrack={handlePlayTrack} libraryStatus={libraryStatus} />
              </ErrorBoundary>
            </div>

            <div className={activeTab === 'xml' ? 'h-full' : 'hidden'}>
              <ErrorBoundary key="eb-xml">
                <XmlCleanView libraryStatus={libraryStatus} />
              </ErrorBoundary>
            </div>

            <div className={activeTab === 'import' ? 'h-full' : 'hidden'}>
              <ErrorBoundary key="eb-import">
                <ImportView onSelectTrack={handleTrackEdit} onImportComplete={checkLibraryStatus} onPlayTrack={handlePlayTrack} />
              </ErrorBoundary>
            </div>

            <div className={activeTab === 'ranking' ? 'h-full' : 'hidden'}>
              <ErrorBoundary key="eb-ranking">
                <RankingView libraryStatus={libraryStatus} onSelectTrack={handleTrackSelect} onEditTrack={handleTrackEdit} />
              </ErrorBoundary>
            </div>

            <div className={activeTab === 'editor' ? 'h-full' : 'hidden'}>
              <ErrorBoundary key="eb-editor">
                <DjEditDaw track={activeTrack} />
              </ErrorBoundary>
            </div>

            <div className={activeTab === 'insights' ? 'h-full' : 'hidden'}>
              <ErrorBoundary key="eb-insights">
                <InsightsView onSelectTrack={handleTrackSelect} onEditTrack={handleTrackEdit} libraryStatus={libraryStatus} />
              </ErrorBoundary>
            </div>

            <div className={activeTab === 'soundcloud' ? 'h-full' : 'hidden'}>
              <ErrorBoundary key="eb-soundcloud">
                <SoundCloudView />
              </ErrorBoundary>
            </div>

            <div className={activeTab === 'sc-sync' ? 'h-full' : 'hidden'}>
              <ErrorBoundary key="eb-sc-sync">
                <SoundCloudSyncView />
              </ErrorBoundary>
            </div>

            {activeTab === 'usb' && <ErrorBoundary key="eb-usb"><UsbView /></ErrorBoundary>}
            {activeTab === 'design' && <ErrorBoundary key="eb-design"><DesignView /></ErrorBoundary>}
            {activeTab === 'tools' && <ErrorBoundary key="eb-tools"><ToolsView /></ErrorBoundary>}
            {activeTab === 'settings' && <ErrorBoundary key="eb-settings"><SettingsView /></ErrorBoundary>}
          </Suspense>
        </div>
      </main>

      {/* Hide Player in Editor and Ranking modes */}
      {!['editor', 'ranking'].includes(activeTab) && (
        <Player
          track={playerTrack}
          onClose={() => setPlayerTrack(null)}
          onMaximize={() => { setActiveTrack(playerTrack); setActiveTab('editor'); }}
        />
      )}
    </div>
  )
}

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <ToastProvider>
    <Toaster
      position="top-center"
      reverseOrder={false}
      toastOptions={{
        duration: 3000,
        style: {
          background: '#1e293b',
          color: '#fff',
          border: '1px solid rgba(255,255,255,0.1)',
          backdropFilter: 'blur(10px)',
          maxWidth: '500px'
        },
        success: { duration: 3000 },
        error: { duration: 4000 }
      }}
    />
    <App />
  </ToastProvider>
);

export default App
