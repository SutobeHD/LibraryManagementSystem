import React, { useState, useMemo, Component, useEffect, useCallback, Suspense, lazy } from 'react'
import { invoke } from '@tauri-apps/api/core'; // Tauri Invoke
import ReactDOM from 'react-dom/client'
import { Music, Cloud, Download, Settings, Folder, Wrench, Zap, FileCode, AlertTriangle, Upload, X, Minus, Square, Unplug, ArrowRightLeft, RotateCw, Activity, BarChart3, HardDrive, Loader2, Sparkles, Copy, Layers, FilePlus, FolderOpen, ArrowLeft, Sliders, List, User, Tag, Disc, RefreshCw, TrendingDown, PlayCircle, ImageOff } from 'lucide-react'
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
const SoundCloudView = lazy(() => import('./components/SoundCloudView'));
const SoundCloudSyncView = lazy(() => import('./components/SoundCloudSyncView'));
const DownloadManagerView = lazy(() => import('./components/DownloadManagerView'));
import ImportProgressBanner from './components/ImportProgressBanner';
const PhraseGeneratorView = lazy(() => import('./components/PhraseGeneratorView'));
const DuplicateView = lazy(() => import('./components/DuplicateView'));
const UtilitiesView = lazy(() => import('./components/UtilitiesView'));
const InsightsView  = lazy(() => import('./components/InsightsView'));

import api from './api/api'

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

/**
 * Workspace groups — Blender-style. The unified TopBar switches between
 * these and lists the active workspace's views. The XML Automator only
 * appears while a library is loaded in XML mode.
 */
const buildWorkspaces = (libraryStatus) => [
  {
    id: 'library',
    label: 'Library',
    // The library's metadata modes are the workspace's views (lifted up from
    // MetadataView's own header). activeTab is 'lib-<mode>'.
    items: [
      { tab: 'lib-playlists', label: 'Playlists', icon: List },
      { tab: 'lib-artists', label: 'Artists', icon: User },
      { tab: 'lib-labels', label: 'Labels', icon: Tag },
      { tab: 'lib-albums', label: 'Albums', icon: Disc },
    ],
  },
  {
    id: 'import',
    label: 'Audio Import',
    items: [{ tab: 'import', label: 'Audio Import', icon: Upload }],
  },
  {
    id: 'ranking',
    label: 'Ranking',
    items: [{ tab: 'ranking', label: 'Ranking Mode', icon: Zap }],
  },
  {
    id: 'editor',
    label: 'Editor',
    items: [
      { tab: 'editor', label: 'Studio', icon: Activity },
      ...(libraryStatus?.mode === 'xml'
        ? [{ tab: 'xml', label: 'XML Automator', icon: FileCode }]
        : []),
    ],
  },
  {
    id: 'usb',
    label: 'USB',
    items: [
      { tab: 'usb', label: 'USB Export', icon: HardDrive },
      { tab: 'usb-settings', label: 'USB Settings', icon: Sliders },
    ],
  },
  {
    id: 'soundcloud',
    label: 'SoundCloud',
    items: [
      { tab: 'soundcloud', label: 'SoundCloud', icon: Cloud },
      { tab: 'sc-sync', label: 'SCloudLibrary', icon: Download },
      { tab: 'downloads', label: 'Downloads', icon: Download },
    ],
  },
  {
    id: 'utilities',
    label: 'Utilities',
    // Tools + Library-Health filters are dissolved into individual flat tabs
    // (no inner grid/toggle); each is a `util-<mode>` view.
    items: [
      { tab: 'util-phrase', label: 'Phrase Cues', icon: Layers },
      { tab: 'util-duplicates', label: 'Duplicates', icon: Copy },
      { tab: 'util-xml', label: 'XML Cleaner', icon: FileCode },
      { tab: 'util-converter', label: 'Converter', icon: RefreshCw },
      { tab: 'util-low_quality', label: 'Low Quality', icon: TrendingDown },
      { tab: 'util-lost', label: 'Lost', icon: PlayCircle },
      { tab: 'util-no_artwork', label: 'No Cover', icon: ImageOff },
      { tab: 'insights', label: 'Insights', icon: BarChart3 },
    ],
  },
]

/** tab id → workspace id (XML resolves to the editor workspace). */
const TAB_WORKSPACE = {
  'lib-playlists': 'library', 'lib-artists': 'library', 'lib-labels': 'library', 'lib-albums': 'library',
  import: 'import',
  ranking: 'ranking',
  editor: 'editor', xml: 'editor',
  usb: 'usb', 'usb-settings': 'usb',
  soundcloud: 'soundcloud', 'sc-sync': 'soundcloud', downloads: 'soundcloud',
  'util-phrase': 'utilities', 'util-duplicates': 'utilities', 'util-xml': 'utilities',
  'util-converter': 'utilities', 'util-low_quality': 'utilities', 'util-lost': 'utilities',
  'util-no_artwork': 'utilities', insights: 'utilities',
}

/**
 * TopBar — single unified app bar. Carries the brand, the Blender-style
 * workspace tabs, the active workspace's view tabs, the library-status
 * indicator and the Settings / Exit actions. Replaces the old split
 * WorkspaceBar + left Sidebar.
 */
const TopBar = ({
  workspaces,
  activeWorkspace,
  activeTab,
  onPickWorkspace,
  setActiveTab,
  libraryStatus,
  onLoadLibrary,
  onUnloadLibrary,
}) => {
  const isTauri =
    typeof window !== 'undefined' &&
    !!(window.__TAURI_INTERNALS__ || window.__TAURI__ || window.__TAURI_METADATA__);

  // Frameless window (decorations:false): we draw our own minimize / maximize /
  // close controls. Close pings the sidecar shutdown route first (Bearer
  // auto-attached by the api.js interceptor) before tearing the window down.
  const winCtl = async (action) => {
    if (action === 'close') {
      try {
        await api.post('/api/system/shutdown');
      } catch (e) {
        // Best-effort — backend may already be down by the time this resolves.
        log.debug('shutdown ping failed', e);
      }
    }
    if (!isTauri) {
      if (action === 'close') {
        window.close();
        document.body.innerHTML =
          "<div style='color:white;display:flex;justify-content:center;height:100vh;align-items:center;background:#0f172a;font-family:sans-serif'>Application Closed</div>";
      }
      return;
    }
    try {
      const { getCurrentWindow } = await import('@tauri-apps/api/window');
      const w = getCurrentWindow();
      if (action === 'min') return await w.minimize();
      if (action === 'max') return await w.toggleMaximize();
      if (action === 'close') return await w.close();
    } catch (e) {
      log.debug('window control failed', e);
    }
  };

  return (
    <div
      data-tauri-drag-region
      className="flex items-stretch h-10 bg-mx-shell border-b border-line-subtle shrink-0 select-none relative z-20"
    >
      {/* Brand */}
      <div className="flex items-center gap-2 px-3.5 border-r border-line-subtle shrink-0">
        <div className="flex items-end gap-[2px]">
          {[8, 12, 16, 11, 7].map((h, i) => (
            <div key={i} className="bg-amber2 rounded-[1px]" style={{ width: 2.5, height: h }} />
          ))}
        </div>
        <span className="text-[12px] font-bold tracking-wide text-ink-primary">LMS</span>
      </div>

      {/* Workspace tabs */}
      {workspaces.map((ws) => {
        const active = ws.id === activeWorkspace
        return (
          <button
            key={ws.id}
            onClick={() => onPickWorkspace(ws)}
            className={`px-3.5 text-[10.5px] font-semibold uppercase tracking-[0.08em] border-r border-line-subtle transition-colors shrink-0 ${
              active
                ? 'bg-mx-panel text-amber2'
                : 'text-ink-secondary hover:text-ink-primary hover:bg-mx-hover'
            }`}
            style={active ? { boxShadow: 'inset 0 -2px 0 var(--amber)' } : undefined}
          >
            {ws.label}
          </button>
        )
      })}

      <div className="flex-1 min-w-[12px]" data-tauri-drag-region />

      {/* Library status */}
      <div className="flex items-center gap-2 px-3 border-l border-line-subtle shrink-0">
        <div
          className={`w-1.5 h-1.5 rounded-full ${
            libraryStatus?.loaded
              ? 'bg-ok shadow-[0_0_6px_#3DD68C]'
              : 'bg-bad shadow-[0_0_6px_#E85C4A]'
          }`}
        ></div>
        <div className="flex flex-col leading-none gap-[3px]">
          <span
            className={`text-[9px] font-semibold uppercase tracking-wider ${
              libraryStatus?.loaded ? 'text-ok' : 'text-bad'
            }`}
          >
            {libraryStatus?.loaded ? 'Active' : 'No Library'}
          </span>
          {libraryStatus?.loaded && (
            <span className="text-[9px] font-mono text-ink-muted">
              {libraryStatus.tracks?.toLocaleString?.() ?? libraryStatus.tracks} tracks
            </span>
          )}
        </div>
        {!libraryStatus?.loaded ? (
          <button
            onClick={onLoadLibrary}
            className="p-1 bg-amber2 hover:bg-amber2-hover text-mx-deepest rounded-mx-sm transition-colors"
            title="Load default library"
          >
            <Zap size={11} />
          </button>
        ) : (
          <button
            onClick={onUnloadLibrary}
            className="p-1 bg-mx-card hover:bg-bad/15 text-ink-muted hover:text-bad rounded-mx-sm transition-colors border border-line-subtle"
            title="Unload library"
          >
            <Unplug size={11} />
          </button>
        )}
      </div>

      {/* Settings */}
      <button
        onClick={() => setActiveTab('settings')}
        title="Settings"
        className={`flex items-center px-3 border-l border-line-subtle transition-colors shrink-0 ${
          activeTab === 'settings'
            ? 'bg-mx-selected text-amber2'
            : 'text-ink-secondary hover:text-ink-primary hover:bg-mx-hover'
        }`}
      >
        <Settings size={15} />
      </button>

      {/* Window controls (frameless — replaces the native title bar) */}
      <button
        onClick={() => winCtl('min')}
        title="Minimize"
        className="flex items-center px-3 border-l border-line-subtle text-ink-secondary hover:text-ink-primary hover:bg-mx-hover transition-colors shrink-0"
      >
        <Minus size={15} />
      </button>
      <button
        onClick={() => winCtl('max')}
        title="Maximize"
        className="flex items-center px-3 border-l border-line-subtle text-ink-secondary hover:text-ink-primary hover:bg-mx-hover transition-colors shrink-0"
      >
        <Square size={12} />
      </button>
      <button
        onClick={() => winCtl('close')}
        title="Close"
        className="flex items-center px-3 border-l border-line-subtle text-ink-secondary hover:text-white hover:bg-bad transition-colors shrink-0"
      >
        <X size={15} />
      </button>
    </div>
  )
}

/**
 * WorkspaceNav — in-content nav for the active workspace's sibling views.
 *
 * Lives at the top of the content area (NOT the global top chrome), so the
 * top bar stays constant across workspaces. Rendered only when a workspace
 * has more than one view — single-view workspaces (e.g. Studio in live mode)
 * stay fully immersive.
 */
const WorkspaceNav = ({ items, activeTab, setActiveTab }) => (
  <div className="flex items-stretch h-7 bg-mx-shell/40 border-b border-line-subtle shrink-0 px-2 gap-1 select-none">
    {items.map((it) => {
      const Icon = it.icon
      const active = activeTab === it.tab
      return (
        <button
          key={it.tab}
          onClick={() => setActiveTab(it.tab)}
          className={`flex items-center gap-1.5 px-2.5 my-0.5 rounded-sm text-[10px] whitespace-nowrap transition-colors ${
            active
              ? 'bg-mx-selected text-ink-primary font-medium'
              : 'text-ink-secondary hover:text-ink-primary hover:bg-mx-hover'
          }`}
        >
          <Icon size={12} className={active ? 'text-amber2' : 'opacity-70'} />
          {it.label}
        </button>
      )
    })}
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
  const [activeTab, setActiveTab] = useState('lib-playlists')
  const [activeWorkspace, setActiveWorkspace] = useState('library')
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
        setActiveTab('lib-playlists');
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
        setActiveTab('lib-playlists');
        await checkLibraryStatus();
      } catch (e) {
        console.error("Standalone init failed", e);
        try {
          await api.post('/api/library/new', { path: STANDALONE_PATH });
          await api.post('/api/library/load', { path: STANDALONE_PATH });
          setActiveTab('lib-playlists');
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
        setActiveTab('lib-playlists');
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
    // SPEED: Heartbeat at 5s instead of 2s — sufficient for keepalive.
    // Phase-1 auth-hardening: heartbeat is now a pure alive-only ping
    // ({"status":"alive"}). Session-token bootstrap moved to
    // frontend/src/api/api.js (Tauri IPC / dev-middleware fetch); this
    // effect just keeps the sidecar's last_heartbeat fresh.
    const hbInterval = setInterval(async () => {
      try {
        await api.post('/api/system/heartbeat');
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

  const workspaces = useMemo(() => buildWorkspaces(libraryStatus), [libraryStatus]);
  const currentWorkspace = workspaces.find((w) => w.id === activeWorkspace) || workspaces[0];

  // Keep the workspace tab in sync when the view changes from elsewhere
  // (e.g. "edit track" jumps straight to the editor). Tabs with no workspace
  // — Settings — leave the current workspace untouched.
  useEffect(() => {
    const ws = TAB_WORKSPACE[activeTab];
    if (ws) setActiveWorkspace(ws);
  }, [activeTab]);

  const handleWorkspacePick = useCallback((ws) => {
    setActiveWorkspace(ws.id);
    if (ws.items[0]) setActiveTab(ws.items[0].tab);
  }, []);

  return (
    <div className="flex flex-col h-screen w-screen bg-mx-deepest text-ink-primary overflow-hidden font-sans">
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

      <TopBar
        workspaces={workspaces}
        activeWorkspace={activeWorkspace}
        activeTab={activeTab}
        onPickWorkspace={handleWorkspacePick}
        setActiveTab={setActiveTab}
        libraryStatus={libraryStatus}
        onLoadLibrary={handleLoadLibrary}
        onUnloadLibrary={handleUnloadLibrary}
      />

      <main className="flex-1 min-h-0 overflow-hidden relative z-10 bg-mx-deepest flex flex-col">
        {currentWorkspace.items.length > 1 && (
          <WorkspaceNav
            items={currentWorkspace.items}
            activeTab={activeTab}
            setActiveTab={setActiveTab}
          />
        )}
        <div className={`flex-1 min-h-0 w-full relative ${playerTrack ? 'pb-20' : ''}`}>
          <Suspense fallback={<ViewLoader />}>
            {/* STABILITY: Each view wrapped in its own ErrorBoundary */}
            <div className={activeTab.startsWith('lib-') ? 'h-full' : 'hidden'}>
              <ErrorBoundary key="eb-library">
                <MetadataView mode={activeTab.replace('lib-', '')} onSelectTrack={handleTrackSelect} onEditTrack={handleTrackEdit} onPlayTrack={handlePlayTrack} libraryStatus={libraryStatus} />
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
            {activeTab.startsWith('util-') && (
              <ErrorBoundary key="eb-utilities">
                <UtilitiesView
                  mode={activeTab.replace('util-', '')}
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
