import React from 'react';

// Error Boundary — prevents WaveSurfer / decode crashes from white-screening the app
export default class WaveformErrorBoundary extends React.Component {
    constructor(props) {
        super(props);
        this.state = { hasError: false, error: null };
    }
    static getDerivedStateFromError(error) {
        return { hasError: true, error };
    }
    componentDidCatch(error, info) {
        console.error('WaveformEditor crashed:', error, info);
    }
    handleRetry = () => {
        this.setState({ hasError: false, error: null });
    };
    render() {
        if (this.state.hasError) {
            return (
                <div className="flex flex-col items-center justify-center h-full p-8 bg-black text-center">
                    <div className="text-red-400 font-bold text-lg mb-2">Waveform Editor crashed</div>
                    <div className="text-ink-muted text-sm mb-4 max-w-md font-mono">
                        {this.state.error?.message || 'Unknown error'}
                    </div>
                    <button
                        onClick={this.handleRetry}
                        className="px-4 py-2 rounded bg-amber2/20 border border-amber2/40 text-amber2 font-bold hover:bg-amber2/30"
                    >
                        Retry
                    </button>
                </div>
            );
        }
        return this.props.children;
    }
}
