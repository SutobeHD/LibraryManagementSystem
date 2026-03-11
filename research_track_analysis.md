# Research: Track Analysis & Automated Feature Extraction

## Objective
How to automatically extract BPM, Beatgrids, Waveforms, and Cues from an audio file (any format) without relying on Rekordbox's pre-analyzed files.

## Existing Tools & Libraries

### 1. Librosa (Python)
- **Strengths**: Industry standard for scientific audio analysis. Excellent Beat Tracking (`librosa.beat.beat_track`).
- **Difficulty**: Can be slow for large libraries. Focuses on "Onset detection" which might miss subtle swing in some genres.

### 2. Essentia (C++ / Python)
- **Strengths**: Used by many professional DJ software. Extremely fast and accurate for BPM and Key detection.
- **Difficulty**: Installation on Windows can be tricky due to complex C++ dependencies.

### 3. Aubio (C)
- **Strengths**: Very lightweight and real-time capable.
- **Difficulty**: Less accurate than Essentia for complex electronic music.

### 4. Madmom (Python)
- **Strengths**: Uses Deep Learning (RNNs) for beat tracking. Often considered the most accurate open-source beat tracker.
- **Difficulty**: Heavy dependencies (TensorFlow/PyTorch/etc) which increase the app's bundle size significantly.

## Methodology for "Native" Feel

### Beatgrid Alignment
To match the "Rekordbox feel", we need:
1. **Dynamic BPM**: Detecting if a track drifts (common in disco/live drums).
2. **Phase Snapping**: Ensuring the first beat (Downbeat) is correctly detected. This is the hardest part for any AI.
3. **Smart Snap**: Snapping grids to the nearest integer BPM unless drift is detected.

### Waveform Generation
- **RMS/Peak Analysis**: Standard waveforms use volume envelopes.
- **3-Band (RGB) Waveforms**: Require splitting the audio into High, Mid, and Low frequencies (using Band-pass filters) and calculating the power of each individually.

## Challenges & Difficulties
- **Syncopation**: Bass-heavy or syncopated genres (Jazz, Breakbeat) often trick beat trackers into half or double speed.
- **Transcoding**: Analyzing MP3 vs FLAC vs WAV requires consistent decoding (using `ffmpeg` or `pydub`).
- **Compatibility**: Converting our analyzed data *into* the proprietary Rekordbox binary tags (PDBQ, PWV3) is the ultimate technical hurdle.

## Roadmap Suggestion
We should implement a **Hybrid Analysis Engine**:
- Use `Essentia` or `Aubio` for fast initial peak/BPM detection.
- Provide a "Manual Adjust" UI (our existing Grid Editor) for the user to fix AI mistakes.
- Use a worker-pool to analyze tracks in the background to avoid freezing the UI.
