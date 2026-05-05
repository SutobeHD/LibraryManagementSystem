import React, { useState, Component, useEffect, useCallback, Suspense, lazy } from 'react'
import { invoke } from '@tauri-apps/api/core'; // Tauri Invoke
import ReactDOM from 'react-dom/client'
import { Music, Cloud, Download, Scissors, Settings, Folder, Wrench, Zap, FileCode, AlertTriangle, Upload, X, Database, ArrowRightLeft, RotateCw, Activity, BarChart3, HardDrive, Loader2, Sparkles, Copy, Layers } from 'lucide-react'
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
const PhraseGeneratorView = lazy(() => import('./components/PhraseGeneratorView'));
const DuplicateView = lazy(() => import('./components/DuplicateView'));
const UtilitiesView = lazy(() => import('./components/UtilitiesView'));

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
      {/* Sidebar — Melodex design system: 220px, near-black, amber active border-left */}
      <div
        className="h-screen flex flex-col relative z-20 shrink-0 bg-mx-shell border-r border-line-subtle"
        style={{ width: 220 }}
      >
        {/* Logo: 5 amber bars (audio meter) + wordmark */}
        <div className="px-4 py-3 border-b border-line-subtle flex items-center gap-2">
          <div className="flex items-end gap-[2px]">
            {[14, 18, 22, 16, 10].map((h, i) => (
              <div
                key={i}
                className="bg-amber2 rounded-[1.5px]"
                style={{ width: 3, height: h }}
              />
            ))}
          </div>
          <span className="text-[15px] font-bold tracking-tight text-ink-primary">RB Editor</span>
        </div>

        {/* Library Status Indicator */}
        <div className="px-3 pt-3">
          <div
            className={`px-3 py-2 rounded-mx-sm border flex items-center justify-between ${
              libraryStatus?.loaded
                ? 'bg-ok/5 border-ok/30'
                : 'bg-bad/5 border-bad/25'
            }`}
          >
            <div className="flex items-center gap-2">
              <div
                className={`w-1.5 h-1.5 rounded-full ${
                  libraryStatus?.loaded
                    ? 'bg-ok shadow-[0_0_6px_#3DD68C]'
                    : 'bg-bad shadow-[0_0_6px_#E85C4A]'
                }`}
              ></div>
              <div className="flex flex-col leading-tight">
                <span
                  className={`text-[10px] font-semibold uppercase tracking-wider ${
                    libraryStatus?.loaded ? 'text-ok' : 'text-bad'
                  }`}
                >
                  {libraryStatus?.loaded ? 'Active' : 'No Library'}
                </span>
                {libraryStatus?.loaded && (
                  <span className="text-[10px] font-mono text-ink-muted mt-0.5">
                    {libraryStatus.tracks?.toLocaleString?.() ?? libraryStatus.tracks} tracks
                  </span>
                )}
              </div>
            </div>
            {!libraryStatus?.loaded ? (
              <button
                onClick={onLoadLibrary}
                className="p-1.5 bg-amber2 hover:bg-amber2-hover text-mx-deepest rounded-mx-sm transition-colors"
                title="Load default library"
              >
                <Zap size={11} />
              </button>
            ) : (
              <button
                onClick={onUnloadLibrary}
                className="p-1.5 bg-mx-card hover:bg-bad/15 text-ink-muted hover:text-bad rounded-mx-sm transition-colors border border-line-subtle"
                title="Unload library"
              >
                <X size={11} />
              </button>
            )}
          </div>
        </div>

        {/* Navigation — grouped, scrollable */}
        <nav className="flex-1 mt-3 overflow-y-auto pb-2">
          <NavGroup label="Library">
            <NavBtn icon={<Music size={14} />} label="Library" active={activeTab === 'library'} onClick={() => setActiveTab('library')} />
            <NavBtn icon={<Upload size={14} />} label="Audio Import" active={activeTab === 'import'} onClick={() => setActiveTab('import')} />
            <NavBtn icon={<Zap size={14} />} label="Ranking Mode" active={activeTab === 'ranking'} onClick={() => setActiveTab('ranking')} />
            <NavBtn icon={<Activity size={14} />} label="Insights" active={activeTab === 'insights'} onClick={() => setActiveTab('insights')} />
          </NavGroup>

          <NavGroup label="Editor">
            <NavBtn icon={<Scissors size={14} />} label="Waveform Editor" active={activeTab === 'editor'} onClick={() => setActiveTab('editor')} />
            {libraryStatus?.mode === 'xml' && (
              <NavBtn icon={<FileCode size={14} />} label="XML Automator" active={activeTab === 'xml'} onClick={() => setActiveTab('xml')} />
            )}
          </NavGroup>

          <NavGroup label="Sync">
            <NavBtn icon={<HardDrive size={14} />} label="USB Export" active={activeTab === 'usb'} onClick={() => setActiveTab('usb')} />
            <NavBtn icon={<Cloud size={14} />} label="SoundCloud" active={activeTab === 'soundcloud'} onClick={() => setActiveTab('soundcloud')} />
            <NavBtn icon={<Download size={14} />} label="SCloudLibrary" active={activeTab === 'sc-sync'} onClick={() => setActiveTab('sc-sync')} />
          </NavGroup>

          <NavGroup label="Utilities">
            <NavBtn icon={<Wrench size={14} />} label="Utilities" active={activeTab === 'utilities'} onClick={() => setActiveTab('utilities')} />
          </NavGroup>

          <NavGroup label="Lab">
            <NavBtn icon={<Sparkles size={14} />} label="Design Lab" active={activeTab === 'design'} onClick={() => setActiveTab('design')} />
          </NavGroup>
        </nav>

        {/* Footer */}
        <div className="border-t border-line-subtle py-2">
          {libraryStatus?.loaded && libraryStatus?.mode === 'live' && (
            <div onClick={() => setShowBackups(true)} className="nav-item">
              <Database size={14} />
              <span>Backups</span>
            </div>
          )}
          <NavBtn icon={<Settings size={14} />} label="Settings" active={activeTab === 'settings'} onClick={() => setActiveTab('settings')} />
          <div onClick={handleExit} className="nav-item" style={{ color: 'var(--bad)' }}>
            <AlertTriangle size={14} />
            <span>Exit</span>
          </div>
        </div>
      </div>

      {/* Backup Manager Modal */}
      {showBackups && (
        <Suspense
          fallback={
            <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center">
              <Loader2 className="animate-spin text-amber2" size={32} />
            </div>
          }
        >
          <BackupManager onClose={() => setShowBackups(false)} />
        </Suspense>
      )}
    </>
  )
}

/** Group label for sidebar sections — matches Melodex `.t-caption` style. */
const NavGroup = ({ label, children }) => (
  <div className="pt-3">
    <div className="mx-caption px-4 pb-1.5">{label}</div>
    {children}
  </div>
)

const NavBtn = ({ icon, label, active, onClick }) => (
  <div onClick={onClick} className={`nav-item ${active ? 'active' : ''}`}>
    {icon}
    <span>{label}</span>
  </div>
)

const SelectionView = ({ onSelect }) => (
  <div className="fixed inset-0 z-[110] bg-mx-deepest flex flex-col items-center justify-center p-8 animate-fade-in">
    <div
      className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[800px] h-[800px] rounded-full blur-[150px] pointer-events-none"
      style={{ background: 'rgba(45, 212, 191, 0.03)' }}
    ></div>

    <div className="relative z-10 flex flex-col items-center max-w-4xl w-full">
      {/* Bar-graph logo, large */}
      <div className="flex items-end gap-1 mb-10">
        {[28, 36, 44, 32, 20].map((h, i) => (
          <div key={i} className="bg-amber2 rounded-[2px]" style={{ width: 6, height: h }} />
        ))}
      </div>

      <h1 className="text-3xl font-bold text-ink-primary mb-3 tracking-tight">Select Mode</h1>
      <p className="text-ink-secondary text-sm mb-12 text-center max-w-md">
        Choose your library source to continue.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6 w-full max-w-3xl">
        <button
          onClick={() => onSelect('live')}
          className="group relative p-7 mx-card rounded-mx-lg hover:border-amber2 transition-all text-left overflow-hidden shadow-mx-md"
        >
          <div className="absolute top-0 right-0 p-6 opacity-5 group-hover:opacity-15 transition-opacity">
            <Zap size={120} className="text-amber2" />
          </div>
          <div
            className="w-10 h-10 rounded-mx-md flex items-center justify-center mb-5"
            style={{ background: 'var(--amber-bg)', color: 'var(--amber)' }}
          >
            <Zap size={20} />
          </div>
          <h3 className="text-lg font-semibold text-ink-primary mb-1.5">Rekordbox Live</h3>
          <p className="text-ink-secondary text-tiny leading-relaxed">
            Direct integration with your <span className="font-mono">master.db</span>. Fast, live edits and backups.
          </p>
        </button>

        <button
          onClick={() => onSelect('xml')}
          className="group relative p-7 mx-card rounded-mx-lg hover:border-amber2 transition-all text-left overflow-hidden shadow-mx-md"
        >
          <div className="absolute top-0 right-0 p-6 opacity-5 group-hover:opacity-15 transition-opacity">
            <FileCode size={120} className="text-info" />
          </div>
          <div
            className="w-10 h-10 rounded-mx-md flex items-center justify-center mb-5"
            style={{ background: 'rgba(74, 158, 232, 0.08)', color: 'var(--info)' }}
          >
            <FileCode size={20} />
          </div>
          <h3 className="text-lg font-semibold text-ink-primary mb-1.5">XML Snapshot</h3>
          <p className="text-ink-secondary text-tiny leading-relaxed">
            Standard XML-based workflow. Best for analyzing and cleaning exports.
          </p>
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
      <Loader2 className="animate-spin text-amber2" size={28} />
      <span className="mx-caption">Loading View</span>
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

    // Close Tauri splashscreen (only in desktop context — no-op in browser)
    if (window.__TAURI__) {
      setTimeout(() => {
        invoke('close_splashscreen').catch(console.error);
      }, 2000);
    }

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
    <div className="flex h-screen w-screen bg-mx-deepest text-ink-primary overflow-hidden font-sans">
      {appMode === 'choice' && <SelectionView onSelect={handleModeSelect} />}

      {isInitialLoading && (
        <div className="fixed inset-0 z-[120] bg-mx-deepest flex flex-col items-center justify-center p-8 animate-fade-in font-sans">
          <div
            className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-96 h-96 rounded-full blur-[120px]"
            style={{ background: 'rgba(45, 212, 191, 0.04)' }}
          ></div>
          <div className="relative z-10 flex flex-col items-center max-w-md w-full">
            {/* Bar-graph logo, animated */}
            <div className="flex items-end gap-1 mb-8">
              {[20, 28, 36, 24, 16].map((h, i) => (
                <div
                  key={i}
                  className="bg-amber2 rounded-[2px] origin-bottom"
                  style={{
                    width: 5,
                    height: h,
                    animation: `barBounce 0.9s ${i * 0.12}s ease-in-out infinite alternate`,
                  }}
                />
              ))}
            </div>
            <h1 className="text-2xl font-semibold text-ink-primary mb-2 tracking-tight">Loading Library</h1>
            <p className="mx-caption mb-10" style={{ color: 'var(--amber)' }}>RB Editor Pro</p>
            <div className="w-full h-1 bg-line-subtle rounded-full overflow-hidden mb-3">
              <div
                className="h-full bg-amber2 transition-all duration-500 ease-out"
                style={{ width: libraryStatus.loaded ? '100%' : (libraryStatus.tracks > 0 ? '75%' : '20%') }}
              ></div>
            </div>
            <div className="flex justify-between w-full px-0.5 mb-8">
              <span className="mx-caption">Status</span>
              <span className="mx-caption" style={{ color: 'var(--amber)' }}>
                {libraryStatus.loaded ? 'Success' : `Initializing ${appMode.toUpperCase()}…`}
              </span>
            </div>
            {!libraryStatus.loaded && (
              <button
                onClick={() => setIsInitialLoading(false)}
                className="mt-8 text-[10px] text-ink-muted hover:text-ink-secondary underline transition-colors uppercase tracking-widest font-semibold"
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

      <main className="flex-1 h-full overflow-hidden relative z-10 bg-mx-deepest">
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
            {activeTab === 'utilities' && <ErrorBoundary key="eb-utilities"><UtilitiesView /></ErrorBoundary>}
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
// Global handler for Unhandled Promise Rejections
window.addEventListener('unhandledrejection', event => {
  console.error('Unhandled Promise Rejection:', event.reason);
  // Prevent default to avoid crashing the UI thread abruptly
  event.preventDefault();
});

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(
  <ToastProvider>
    <Toaster
      position="top-center"
      reverseOrder={false}
      toastOptions={{
        duration: 3000,
        style: {
          background: '#1A1E27',
          color: '#F0F2F7',
          border: '1px solid #2A2F3E',
          fontFamily: '"DM Sans", system-ui, sans-serif',
          fontSize: 13,
          maxWidth: '500px',
          borderRadius: 6,
        },
        success: { duration: 3000 },
        error: { duration: 4000 }
      }}
    />
    <App />
  </ToastProvider>
);

export default App
