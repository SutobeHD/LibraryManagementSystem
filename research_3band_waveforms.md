# Research: 3-Band Waveforms (RGB)

## What are 3-Band Waveforms?
Unlike standard single-color waveforms (which often use RMS or Peak amplitude of the full audio signal), **3-Band Waveforms** split the audio into three distinct frequency ranges and assign a color to the amplitude of each range:
- **Low (Bass)**: Typically < 150 Hz. Usually represented in **Blue**.
- **Mid**: Typically 150 Hz – 2.5 kHz. Usually represented in **Orange/Amber**.
- **High (Treble)**: Typically > 2.5 kHz. Usually represented in **White/Light Blue**.

This allows DJs to visually see where the kick drums, vocals, and hi-hats are located within a track without hearing it.

## How to extract 3-Band data ourselves
For our new **Beta Audio Import**, we can extract 3-Band waveforms during the background analysis phase:

1. **Filtering**: Use digital filters (e.g., Butterworth filters in `scipy.signal` or `librosa`) to pass the audio through a Low-Pass filter, a Band-Pass filter, and a High-Pass filter.
2. **Envelope Extraction**: Calculate the RMS or Peak amplitude envelope for each of the three filtered signals.
3. **Downsampling**: Reduce the resolution to a manageable size (e.g., 100-200 points per second of audio) to store efficiently.
4. **Storage**: Save these three arrays (Low, Mid, High) in our local database or as a compressed JSON/NumPy file alongside the track.

### Ease of Implementation
- **Backend (Analysis)**: Med-High difficulty. Processing 3 filters on full tracks takes CPU time. We MUST use a background worker pool (`concurrent.futures` or Celery) so the UI doesn't freeze.
- **Frontend (Rendering)**: Medium difficulty. We can use the HTML5 `<canvas>` element (as we likely do in `DawTimeline`). Instead of drawing one continuous path, we draw three stacked paths or interweaved vertical bars (like Pioneer's CDJ-3000), where the height and color of each segment correspond to the Low, Mid, and High values at that specific time.

## Displaying in the UI

### 1. Library Tab (Mini-Waveform)
- **Feasibility**: High.
- **Approach**: Since the Library tab shows many tracks, rendering 3-Band waveforms for *every* track might cause performance issues. We should pre-render a low-resolution static image (PNG/SVG) of the 3-Band waveform and serve it as a static asset, or draw a very simplified `<canvas>` with fewer data points. 
- **Rekordbox style**: Rekordbox shows a tiny preview column. It helps massively in judging the energy levels of a playlist.

### 2. Ranking Mode & Editor (Full Timeline)
- **Feasibility**: High.
- **Approach**: In the `DawTimeline`, we can draw the three bands overlaying each other. 
    - The Base layer is Blue (Bass).
    - The Middle layer is Orange (Mids).
    - The Top layer is White (Highs).
- **Performance**: We should use `requestAnimationFrame` and WebGL if possible for large zoomed-in waveforms, but a highly optimized 2D Canvas context is usually sufficient if we only draw the visible window.

## Integration with Rekordbox USBs
If we want these custom 3-Band waveforms to show up on a CDJ-3000, we have to inject them into the `.2EX` binary Anlz files (Tag `PWV3`) on the USB stick. (See `research_rekordbox_internals.md`). This requires reverse-engineering the exact byte structure Pioneer expects.

## Conclusion
Implementing our own 3-Band waveform generator is entirely possible and highly recommended for the "Beta Audio Import" feature to achieve a premium, professional feel. The most critical aspect will be optimizing the frontend Canvas drawing to prevent lag when scrolling through the library or zooming in the editor.
