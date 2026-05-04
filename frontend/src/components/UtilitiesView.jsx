import React, { useState, Suspense, lazy } from 'react';
import { Layers, Copy, FileCode, RefreshCw, ArrowLeft, Loader2, Wrench } from 'lucide-react';

const PhraseGeneratorView = lazy(() => import('./PhraseGeneratorView'));
const DuplicateView = lazy(() => import('./DuplicateView'));
const XmlCleanView = lazy(() => import('./XmlCleanView'));

const TOOLS = [
    { id: 'phrase', icon: Layers, title: 'Phrase Cues Generator', desc: 'Generate phrase markers and auto-cue points from beat analysis', color: 'text-amber2' },
    { id: 'duplicates', icon: Copy, title: 'Duplicate Finder', desc: 'Find acoustic duplicates using fingerprint analysis', color: 'text-teal-400' },
    { id: 'xml', icon: FileCode, title: 'XML Cleaner', desc: 'Validate and clean Rekordbox XML exports', color: 'text-blue-400' },
    { id: 'converter', icon: RefreshCw, title: 'Mass Format Converter', desc: 'Batch convert audio files between formats', color: 'text-orange-400' },
];

const UtilitiesView = () => {
    const [activeTool, setActiveTool] = useState(null);

    if (activeTool) {
        return (
            <div className="h-full flex flex-col">
                <div className="px-6 py-3 border-b border-line-subtle flex items-center gap-3">
                    <button
                        onClick={() => setActiveTool(null)}
                        className="p-1.5 hover:bg-mx-hover rounded-mx-sm transition-colors text-ink-muted hover:text-ink-primary"
                    >
                        <ArrowLeft size={16} />
                    </button>
                    <span className="text-[13px] font-medium text-ink-primary">
                        {TOOLS.find(t => t.id === activeTool)?.title}
                    </span>
                </div>
                <div className="flex-1 overflow-hidden">
                    <Suspense fallback={<div className="flex items-center justify-center h-full"><Loader2 className="animate-spin text-amber2" size={24} /></div>}>
                        {activeTool === 'phrase' && <PhraseGeneratorView />}
                        {activeTool === 'duplicates' && <DuplicateView />}
                        {activeTool === 'xml' && <XmlCleanView />}
                        {activeTool === 'converter' && <ConverterPlaceholder />}
                    </Suspense>
                </div>
            </div>
        );
    }

    return (
        <div className="h-full flex flex-col bg-mx-deepest animate-fade-in">
            <div className="px-6 py-4 border-b border-line-subtle">
                <div className="flex items-center gap-3">
                    <div className="p-2.5 bg-amber2/10 rounded-mx-md border border-amber2-dim">
                        <Wrench size={20} className="text-amber2" />
                    </div>
                    <div>
                        <h1 className="text-[20px] font-semibold tracking-tight">Utilities</h1>
                        <p className="text-tiny text-ink-muted">Tools for library management and audio processing</p>
                    </div>
                </div>
            </div>

            <div className="flex-1 overflow-y-auto p-6">
                <div className="grid grid-cols-2 gap-4 max-w-3xl">
                    {TOOLS.map(tool => {
                        const Icon = tool.icon;
                        return (
                            <button
                                key={tool.id}
                                onClick={() => tool.id !== 'converter' ? setActiveTool(tool.id) : null}
                                className={`mx-card p-5 text-left transition-all hover:border-amber2/40 hover:bg-mx-hover group ${
                                    tool.id === 'converter' ? 'opacity-50 cursor-not-allowed' : ''
                                }`}
                            >
                                <div className="flex items-start gap-3">
                                    <div className="p-2 bg-mx-input rounded-mx-sm border border-line-subtle group-hover:border-line-default">
                                        <Icon size={18} className={tool.color} />
                                    </div>
                                    <div className="flex-1 min-w-0">
                                        <div className="text-[13px] font-semibold text-ink-primary mb-1">{tool.title}</div>
                                        <div className="text-[11px] text-ink-muted leading-relaxed">{tool.desc}</div>
                                        {tool.id === 'converter' && (
                                            <span className="inline-block mt-2 text-[9px] font-semibold uppercase tracking-wider text-amber2 bg-amber2/10 px-2 py-0.5 rounded-mx-xs border border-amber2/20">
                                                Coming Soon
                                            </span>
                                        )}
                                    </div>
                                </div>
                            </button>
                        );
                    })}
                </div>
            </div>
        </div>
    );
};

const ConverterPlaceholder = () => (
    <div className="flex items-center justify-center h-full text-ink-muted">
        <div className="text-center">
            <RefreshCw size={40} className="mx-auto mb-3 text-ink-placeholder" />
            <p className="text-[13px] font-medium">Mass Format Converter</p>
            <p className="text-tiny text-ink-muted mt-1">Coming in a future update</p>
        </div>
    </div>
);

export default UtilitiesView;
