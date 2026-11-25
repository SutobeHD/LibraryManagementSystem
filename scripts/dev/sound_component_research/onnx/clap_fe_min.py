"""CLAP log-mel features without transformers / torch: mirrors `ClapFeatureExtractor` for
laion/clap-htsat-unfused (48 kHz, fusion off, slaney mel 50-14000 Hz, 10 s, repeatpad).
Deviation on purpose: clips longer than 10 s get a deterministic centre crop instead of `rand_trunc`.
"""
import librosa
import numpy as np

SR, N_FFT, HOP, N_MELS, FMIN, FMAX = 48000, 1024, 480, 64, 50, 14000
MAX_LEN = 10 * SR
_MEL = librosa.filters.mel(sr=SR, n_fft=N_FFT, n_mels=N_MELS, fmin=FMIN, fmax=FMAX, htk=False, norm="slaney")


def fit(y):
    if len(y) > MAX_LEN:
        o = (len(y) - MAX_LEN) // 2
        return y[o:o + MAX_LEN]
    if len(y) < MAX_LEN:
        y = np.tile(y, MAX_LEN // len(y))
        y = np.pad(y, (0, MAX_LEN - len(y)))
    return y


def logmel(y):
    """mono float (n,) @48 kHz -> (1001, 64) float32 dB."""
    p = np.abs(librosa.stft(fit(y).astype(np.float64), n_fft=N_FFT, hop_length=HOP, window="hann",
                            center=True, pad_mode="reflect")) ** 2
    return (10.0 * np.log10(np.maximum(1e-10, _MEL.astype(np.float64) @ p))).T.astype(np.float32)


def features(wins):
    """list of mono windows -> (n, 1, 1001, 64) float32 = ONNX `input_features`."""
    return np.stack([logmel(w) for w in wins])[:, None]
