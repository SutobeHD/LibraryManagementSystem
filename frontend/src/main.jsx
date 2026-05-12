import React, { useState, Component, useEffect, useCallback, Suspense, lazy } from 'react'
import { invoke } from '@tauri-apps/api/core'; // Tauri Invoke
import ReactDOM from 'react-dom/client'
import { Music, Cloud, Download, Scissors, Settings, Folder, Wrench, Zap, FileCode, AlertTriangle, Upload, X, ArrowRightLeft, RotateCw, Activity, BarChart3, HardDrive, Loader2, Sparkles, Copy, Layers, FilePlus, FolderOpen, ArrowLeft, Sliders } from 'lucide-react'
import './index.css'
import { ToastProvider } from './components/ToastContext'
import { Toaster } from 'react-hot-toast'
import toast from 'react-hot-toast'
import { ConfirmModalRoot, confirmModal } from './components/ConfirmModal'
import { PromptModalRoot, promptModal } from './components/PromptModal'
import { log } from './utils/log'
import { HEARTBEAT_INTERVAL_MS, LIBRARY_STATUS_INTERVAL_MS } from './config/constants'

// SPEED: Lazy-load heavy views — only the active view is loaded into the bundle
// const WaveformEditor = lazy(() => import('./components/WaveformEditor')); // Replaced by DjEditDaw
const DjEditDaw = lazy(() => import('./components/daw/DjEditDaw'));
const ToolsView = lazy(() => import('./components/ToolsView'));
const SettingsView = lazy(() => import('./components/SettingsView'));
const RankingView = lazy(() => import('./components/RankingView'));
const XmlCleanView = lazy(() => import('./components/XmlCleanView'));
const MetadataView = lazy(() => import('./components/MetadataView'));
const ImportView = lazy(() => import('./components/ImportView'));
const UsbView = lazy(() => import('./components/UsbView'));
const UsbSettingsView = lazy(() => import('./components/UsbSettingsView'));
const DesignView = lazy(() => import('./components/DesignView'));
const SoundCloudView = lazy(() => import('./components/SoundCloudView'));
const SoundCloudSyncView = lazy(() => import('./components/SoundCloudSyncView'));
const DownloadManagerView = lazy(() => import('./components/DownloadManagerView'));
import ImportProgressBanner from './components/ImportProgressBanner';
const PhraseGeneratorView = lazy(() => import('./components/PhraseGeneratorView'));
const DuplicateView = lazy(() => import('./components/DuplicateView'));
const UtilitiesView = lazy(() => import('./components/UtilitiesView'));
const InsightsView  = lazy(() => import('./components/InsightsView'));

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
  const handleExit = async () => {
    if (await confirmModal({ title: "Exit Application?", confirmLabel: "Exit" })) {
      try {
        const token = getSessionToken();
        await api.post('/api/system/shutdown', null, { params: { token } });
      }
      catch (e) {
        // Best-effort shutdown ping — backend might already be down by the
        // time we get here (Tauri runtime closes before this resolves).
        log.debug('shutdown ping failed', e);
      }
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
          <span className="text-[15px] font-bold tracking-tight text-ink-primary">Library Manager</span>
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
            <NavBtn icon={<BarChart3 size={14} />} label="Insights" active={activeTab === 'insights'} onClick={() => setActiveTab('insights')} />
          </NavGroup>

          <NavGroup label="Editor">
            <NavBtn icon={<Scissors size={14} />} label="Waveform Editor" active={activeTab === 'editor'} onClick={() => setActiveTab('editor')} />
            {libraryStatus?.mode === 'xml' && (
              <NavBtn icon={<FileCode size={14} />} label="XML Automator" active={activeTab === 'xml'} onClick={() => setActiveTab('xml')} />
            )}
          </NavGroup>

          <NavGroup label="Sync">
            <NavBtn icon={<HardDrive size={14} />} label="USB Export" active={activeTab === 'usb'} onClick={() => setActiveTab('usb')} />
            <NavBtn icon={<Sliders size={14} />} label="USB Settings" active={activeTab === 'usb-settings'} onClick={() => setActiveTab('usb-settings')} />
            <NavBtn icon={<Cloud size={14} />} label="SoundCloud" active={activeTab === 'soundcloud'} onClick={() => setActiveTab('soundcloud')} />
            <NavBtn icon={<Download size={14} />} label="SCloudLibrary" active={activeTab === 'sc-sync'} onClick={() => setActiveTab('sc-sync')} />
            <NavBtn icon={<Download size={14} />} label="Downloads" active={activeTab === 'downloads'} onClick={() => setActiveTab('downloads')} />
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
          <NavBtn icon={<Settings size={14} />} label="Settings" active={activeTab === 'settings'} onClick={() => setActiveTab('settings')} />
          <div onClick={handleExit} className="nav-item" style={{ color: 'var(--bad)' }}>
            <AlertTriangle size={14} />
            <span>Exit</span>
          </div>
        </div>
      </div>
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

// Subtle dot-grid backdrop — sharp, low-contrast, no blur. Sits behind the
// content so the screen feels like an extension of the app shell rather than
// a soft hero gradient.
const DotGridBackdrop = () => (
  <div
    className="absolute inset-0 pointer-events-none"
    style={{
      backgroundImage:
        'radial-gradient(circle at 1px 1px, rgba(232,164,42,0.07) 1px, transparent 1.5px)',
      backgroundSize: '24px 24px',
      maskImage:
        'radial-gradient(ellipse at center, rgba(0,0,0,0.9) 0%, rgba(0,0,0,0.55) 55%, transparent 90%)',
      WebkitMaskImage:
        'radial-gradient(ellipse at center, rgba(0,0,0,0.9) 0%, rgba(0,0,0,0.55) 55%, transparent 90%)',
    }}
  />
);

const XmlSubmodeView = ({ onPick, onBack }) => {
  const cards = [
    {
      id: 'new-empty',
      icon: FilePlus,
      title: 'New Empty',
      desc: 'Create a fresh, empty rekordbox.xml in the app folder.',
    },
    {
      id: 'standalone',
      icon: Sparkles,
      title: 'Standalone',
      desc: 'Pick a custom location and create a new XML there — independent of Rekordbox.',
    },
    {
      id: 'import',
      icon: Upload,
      title: 'Import',
      desc: 'Drop or browse an existing rekordbox.xml export and load it.',
    },
    {
      id: 'defined-path',
      icon: FolderOpen,
      title: 'Defined Path',
      desc: 'Point at an existing XML on disk — edits write back to the same file.',
    },
  ];
  return (
    <div className="fixed inset-0 z-[110] bg-mx-deepest flex flex-col items-center justify-center p-8 animate-fade-in">
      <DotGridBackdrop />
      <div className="relative z-10 flex flex-col items-center max-w-5xl w-full">
        <div className="flex items-end gap-1 mb-10">
          {[28, 36, 44, 32, 20].map((h, i) => (
            <div key={i} className="bg-amber2 rounded-[2px]" style={{ width: 6, height: h }} />
          ))}
        </div>

        <h1 className="text-3xl font-bold text-ink-primary mb-3 tracking-tight">XML Mode</h1>
        <p className="text-ink-secondary text-sm mb-12 text-center max-w-md">
          Choose how to start the XML library.
        </p>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-5 w-full max-w-4xl">
          {cards.map(({ id, icon: Icon, title, desc }) => (
            <button
              key={id}
              onClick={() => onPick(id)}
              className="group relative p-7 mx-card rounded-mx-lg hover:border-amber2 transition-all text-left overflow-hidden shadow-mx-md"
            >
              <div className="absolute top-0 right-0 p-6 opacity-5 group-hover:opacity-15 transition-opacity">
                <Icon size={120} className="text-amber2" />
              </div>
              <div
                className="w-10 h-10 rounded-mx-md flex items-center justify-center mb-5"
                style={{ background: 'var(--amber-bg)', color: 'var(--amber)' }}
              >
                <Icon size={20} />
              </div>
              <h3 className="text-lg font-semibold text-ink-primary mb-1.5">{title}</h3>
              <p className="text-ink-secondary text-tiny leading-relaxed">{desc}</p>
            </button>
          ))}
        </div>

        <button
          onClick={onBack}
          className="mt-10 flex items-center gap-2 text-[11px] text-ink-muted hover:text-ink-secondary uppercase tracking-widest font-semibold transition-colors"
        >
          <ArrowLeft size={14} /> Back
        </button>
      </div>
    </div>
  );
};

const SelectionView = ({ onSelect }) => (
  <div className="fixed inset-0 z-[110] bg-mx-deepest flex flex-col items-center justify-center p-8 animate-fade-in">
    <DotGridBackdrop />



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
            Direct integration with your <span className="font-mono">master.db</span>. Fast, live edits — Rekordbox keeps its own backups.
          </p>
        </button>

        <button
          onClick={() => onSelect('xml')}
          className="group relative p-7 mx-card rounded-mx-lg hover:border-amber2 transition-all text-left overflow-hidden shadow-mx-md"
        >
          <div className="absolute top-0 right-0 p-6 opacity-5 group-hover:opacity-15 transition-opacity">
            <FileCode size={120} className="text-amber2" />
          </div>
          <div
            className="w-10 h-10 rounded-mx-md flex items-center justify-center mb-5"
            style={{ background: 'var(--amber-bg)', color: 'var(--amber)' }}
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
    if (mode === 'xml') {
      // XML branch shows a submode picker first — no API call yet.
      setAppMode('xml-submode');
      return;
    }
    setAppMode(mode);
    setIsInitialLoading(true);
    try {
      await api.post('/api/library/mode', { mode });
      setActiveTab('library');
    } catch (e) {
      console.error("Mode select failed", e);
    }
  }, []);

  const handleXmlSubmode = useCallback(async (submode) => {
    try {
      await api.post('/api/library/mode', { mode: 'xml' });
    } catch (e) {
      console.error("Failed to switch to xml mode", e);
      return;
    }

    if (submode === 'new-empty') {
      setAppMode('xml');
      setIsInitialLoading(true);
      try {
        await api.post('/api/library/new', {});
        setActiveTab('library');
        await checkLibraryStatus();
      } catch (e) {
        console.error("Create empty library failed", e);
        toast.error("Failed to create empty library.");
      }
      return;
    }

    if (submode === 'standalone') {
      // Internal standalone XML — auto-create if missing, else open
      const STANDALONE_PATH = 'standalone.xml';
      setAppMode('xml');
      setIsInitialLoading(true);
      try {
        const loadRes = await api.post('/api/library/load', { path: STANDALONE_PATH });
        if (loadRes.data?.status !== 'success') {
          // Missing/invalid → create then load
          await api.post('/api/library/new', { path: STANDALONE_PATH });
          await api.post('/api/library/load', { path: STANDALONE_PATH });
        }
        setActiveTab('library');
        await checkLibraryStatus();
      } catch (e) {
        console.error("Standalone init failed", e);
        try {
          await api.post('/api/library/new', { path: STANDALONE_PATH });
          await api.post('/api/library/load', { path: STANDALONE_PATH });
          setActiveTab('library');
          await checkLibraryStatus();
        } catch (e2) {
          console.error("Standalone fallback create failed", e2);
          toast.error("Failed to init standalone XML.");
          setIsInitialLoading(false);
          setAppMode('xml-submode');
        }
      }
      return;
    }

    if (submode === 'import') {
      // Hand off to XmlCleanView — its existing drop-zone handles the upload.
      setAppMode('xml');
      setActiveTab('xml');
      // Don't show the loading splash — the user is about to drop a file.
      return;
    }

    if (submode === 'defined-path') {
      let target = null;
      try {
        const { open } = await import('@tauri-apps/plugin-dialog');
        target = await open({
          title: 'Pick existing XML',
          multiple: false,
          filters: [{ name: 'Rekordbox XML', extensions: ['xml'] }],
        });
      } catch (_) {
        target = await promptModal({
          title: 'Existing rekordbox.xml',
          message: 'Enter the path to an existing rekordbox.xml:',
        });
      }
      if (!target) return;
      setAppMode('xml');
      setIsInitialLoading(true);
      try {
        const res = await api.post('/api/library/load', { path: target });
        if (res.data.status !== 'success') {
          toast.error(`Failed to load XML: ${res.data.message || 'unknown error'}`);
          setIsInitialLoading(false);
          setAppMode('xml-submode');
          return;
        }
        setActiveTab('library');
        await checkLibraryStatus();
      } catch (e) {
        console.error("Defined-path load failed", e);
        toast.error("Failed to load XML at that path.");
        setIsInitialLoading(false);
        setAppMode('xml-submode');
      }
    }
  }, [checkLibraryStatus]);

  const handleLoadLibrary = useCallback(async () => {
    try {
      const res = await api.post('/api/library/load');
      if (res.data.status === 'success') {
        checkLibraryStatus();
      } else {
        toast.error("Failed to load library: " + res.data.message);
      }
    } catch (e) {
      toast.error("Error loading library");
    }
  }, [checkLibraryStatus]);

  const handleUnloadLibrary = useCallback(async () => {
    if (!(await confirmModal({
      title: "Unload library?",
      message: "Are you sure you want to unload the library?",
      confirmLabel: "Unload",
    }))) return;
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
        const res = await api.post('/api/system/heartbeat');
        // SECURITY: Capture session token from heartbeat response
        if (res.data?.token) {
          setSessionToken(res.data.token);
        }
      } catch (e) { /* backend offline */ }
    }, HEARTBEAT_INTERVAL_MS);

    const checkInterval = setInterval(() => {
      if ((appMode === 'xml' || appMode === 'live') && !libraryStatus.loaded) {
        checkLibraryStatus();
      }
    }, LIBRARY_STATUS_INTERVAL_MS);

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
      {appMode === 'xml-submode' && (
        <XmlSubmodeView
          onPick={handleXmlSubmode}
          onBack={() => setAppMode('choice')}
        />
      )}

      {isInitialLoading && (
        <div className="fixed inset-0 z-[120] bg-mx-deepest flex flex-col items-center justify-center p-8 animate-fade-in font-sans">
          <DotGridBackdrop />

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
            <p className="mx-caption mb-10" style={{ color: 'var(--amber)' }}>LibraryManagementSystem</p>
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
        <div className={`h-full w-full relative ${playerTrack ? 'pb-20' : ''}`}>
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
                <InsightsView libraryStatus={libraryStatus} />
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

            <div className={activeTab === 'downloads' ? 'h-full' : 'hidden'}>
              <ErrorBoundary key="eb-downloads">
                <DownloadManagerView />
              </ErrorBoundary>
            </div>

            {activeTab === 'usb' && <ErrorBoundary key="eb-usb"><UsbView /></ErrorBoundary>}
            {activeTab === 'usb-settings' && <ErrorBoundary key="eb-usb-settings"><UsbSettingsView /></ErrorBoundary>}
            {activeTab === 'design' && <ErrorBoundary key="eb-design"><DesignView /></ErrorBoundary>}
            {activeTab === 'utilities' && (
              <ErrorBoundary key="eb-utilities">
                <UtilitiesView
                  onSelectTrack={handleTrackSelect}
                  onEditTrack={handleTrackEdit}
                  onPlayTrack={(track) => setPlayerTrack(track)}
                  libraryStatus={libraryStatus}
                />
              </ErrorBoundary>
            )}
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

      {/* Live import-progress banner (auto-hides when no active task) */}
      <ImportProgressBanner onOpenManager={() => setActiveTab('downloads')} />
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
    <ConfirmModalRoot />
    <PromptModalRoot />
    <App />
  </ToastProvider>
);

export default App
