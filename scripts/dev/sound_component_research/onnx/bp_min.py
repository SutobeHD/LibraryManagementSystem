"""Minimal basic-pitch pre / post-processing without importing `basic_pitch` (no TensorFlow, no pretty_midi).

Mirrors basic_pitch 0.4.0 `inference.run_inference` + `note_creation.output_to_notes_polyphonic`
(Apache-2.0, Spotify AB). Needs numpy + scipy.signal + an onnxruntime session on `nmp.onnx`.
Input: mono float32 at 22050 Hz. Output: list of (start_s, end_s, midi, amplitude).
"""
import numpy as np
import scipy.signal

SR = 22050
HOP = 256
FPS = SR // HOP                      # 86
N_SAMPLES = SR * 2 - HOP             # 43844 samples per model window
OVERLAP_FRAMES = 30
OVERLAP = OVERLAP_FRAMES * HOP
STEP = N_SAMPLES - OVERLAP
MIDI_OFFSET = 21
MAX_FREQ_IDX = 87
OUT_NAMES = ["StatefulPartitionedCall:1", "StatefulPartitionedCall:2"]   # note, onset (contour unused)
IN_NAME = "serving_default_input_2:0"


def windows(y):
    """(n,) -> (n_win, N_SAMPLES, 1) float32, half-overlap zero-padded in front like the original."""
    y = np.concatenate([np.zeros(OVERLAP // 2, np.float32), y.astype(np.float32)])
    out = []
    for i in range(0, len(y), STEP):
        w = y[i:i + N_SAMPLES]
        out.append(np.pad(w, (0, N_SAMPLES - len(w))))
    return np.stack(out)[..., None]


def unwrap(out, n_samples):
    out = out[:, OVERLAP_FRAMES // 2:-(OVERLAP_FRAMES // 2), :]
    return out.reshape(-1, out.shape[2])[: int(np.floor(n_samples * (FPS / SR)))]


def run_model(sess, y, batch=1):
    """-> note (frames, 88), onset (frames, 88)."""
    w = windows(y)
    notes, onsets = [], []
    for i in range(0, len(w), batch):
        n, o = sess.run(OUT_NAMES, {IN_NAME: w[i:i + batch]})
        notes.append(n)
        onsets.append(o)
    return unwrap(np.concatenate(notes), len(y)), unwrap(np.concatenate(onsets), len(y))


def frame_times(n_frames):
    t = np.arange(n_frames) * HOP / SR
    off = (HOP / SR) * (FPS * 2 - N_SAMPLES / HOP) + 0.0018
    return t - off * np.floor(np.arange(n_frames) / (FPS * 2))


def to_notes(frames, onsets, onset_thresh=0.5, frame_thresh=0.3, min_note_len=11, energy_tol=11):
    """Polyphonic decode incl. inferred onsets + melodia trick (basic-pitch defaults)."""
    n_frames = frames.shape[0]
    diffs = []
    for n in (1, 2):
        fa = np.concatenate([np.zeros((n, frames.shape[1])), frames])
        diffs.append(fa[n:] - fa[:-n])
    fd = np.min(diffs, axis=0)
    fd[fd < 0] = 0
    fd[:2] = 0
    fd = np.max(onsets) * fd / np.max(fd)
    onsets = np.max([onsets, fd], axis=0)

    peaks = scipy.signal.argrelmax(onsets, axis=0)
    pk = np.zeros(onsets.shape)
    pk[peaks] = onsets[peaks]
    t_idx, f_idx = np.where(pk >= onset_thresh)
    rem = frames.astype(np.float64).copy()
    notes = []

    def clear(a, b, f):
        rem[a:b, f] = 0
        if f < MAX_FREQ_IDX:
            rem[a:b, f + 1] = 0
        if f > 0:
            rem[a:b, f - 1] = 0

    for s, f in zip(t_idx[::-1], f_idx[::-1]):
        if s >= n_frames - 1:
            continue
        i, k = s + 1, 0
        while i < n_frames - 1 and k < energy_tol:
            k = k + 1 if rem[i, f] < frame_thresh else 0
            i += 1
        i -= k
        if i - s <= min_note_len:
            continue
        clear(s, i, f)
        notes.append((s, i, f + MIDI_OFFSET, float(np.mean(frames[s:i, f]))))

    while np.max(rem) > frame_thresh:
        mid, f = np.unravel_index(np.argmax(rem), rem.shape)
        rem[mid, f] = 0
        i, k = mid + 1, 0
        while i < n_frames - 1 and k < energy_tol:
            k = k + 1 if rem[i, f] < frame_thresh else 0
            clear(i, i + 1, f)
            i += 1
        end = i - 1 - k
        i, k = mid - 1, 0
        while i > 0 and k < energy_tol:
            k = k + 1 if rem[i, f] < frame_thresh else 0
            clear(i, i + 1, f)
            i -= 1
        start = i + 1 + k
        if end - start <= min_note_len:
            continue
        notes.append((start, end, f + MIDI_OFFSET, float(np.mean(frames[start:end, f]))))

    ts = frame_times(n_frames)
    return [(float(ts[a]), float(ts[b]), int(p), amp) for a, b, p, amp in notes]


def predict(sess, y22k, batch=1):
    frames, onsets = run_model(sess, y22k, batch)
    return to_notes(frames, onsets)
