"""Source separation on onnxruntime + numpy / librosa only (no torch): STFT / iSTFT + chunking outside the graph.

umxhq  : `other` spectrogram model on the mixture magnitude, mixture phase (= openunmix Separator niter=0).
htdemucs: core network on 7.8 s segments (STFT outside), overlap-add like demucs.apply (shifts 0).
Input: float32 (2, n) at 44.1 kHz. Stems stay in memory.
"""
import math

import librosa
import numpy as np

N_FFT, HOP = 4096, 1024
SEG = 343980                      # htdemucs training segment (7.8 s)
HTD_SOURCES = ["drums", "bass", "other", "vocals"]


def _stft(y):
    return librosa.stft(y, n_fft=N_FFT, hop_length=HOP, window="hann", center=True, pad_mode="reflect")


def _istft(z, n):
    return librosa.istft(z, n_fft=N_FFT, hop_length=HOP, window="hann", center=True, length=n)


def umx_other(sess, wav):
    """-> (2, n) float32 `other` stem."""
    z = _stft(wav)                                   # (2, 2049, T) complex64
    mag = np.abs(z).astype(np.float32)
    est = sess.run(None, {"mag": mag[None]})[0][0]
    return _istft(est * (z / np.maximum(mag, 1e-20)), wav.shape[1]).astype(np.float32)


def _htd_spec(x):
    le = math.ceil(x.shape[-1] / HOP)
    pad = HOP // 2 * 3
    xp = np.pad(x, ((0, 0), (pad, pad + le * HOP - x.shape[-1])), mode="reflect")
    z = _stft(xp)[:, :-1, :] / math.sqrt(N_FFT)      # torch.stft(normalized=True), drop the Nyquist bin
    return z[:, :, 2:2 + le]


def _htd_ispec(z, length):
    z = np.pad(z, ((0, 0), (0, 0), (0, 1), (2, 2)))
    pad = HOP // 2 * 3
    le = HOP * math.ceil(length / HOP) + 2 * pad
    x = _istft(z * math.sqrt(N_FFT), le)
    return x[..., pad:pad + length]


def htd_segment(sess, seg):
    """seg float32 (2, SEG) -> (4, 2, SEG)."""
    z = _htd_spec(seg)
    mag = np.stack([z.real, z.imag], axis=1).reshape(1, 4, z.shape[1], z.shape[2]).astype(np.float32)
    x, xt = sess.run(None, {"mix": seg[None], "mag": mag})
    x = x[0].reshape(4, 2, 2, x.shape[-2], x.shape[-1])
    return _htd_ispec(x[:, :, 0] + 1j * x[:, :, 1], SEG).astype(np.float32) + xt[0]


def htdemucs(sess, wav, overlap=0.25, ranges=None):
    """-> (4, 2, n) float32 in HTD_SOURCES order. ranges: optional [(start, end)] sample spans to cover
    (segments that do not touch any span are skipped and stay zero)."""
    ref = wav.mean(0)
    mean, std = ref.mean(), ref.std() + 1e-8
    w = (wav - mean) / std
    n = w.shape[1]
    stride = int((1 - overlap) * SEG)
    weight = np.concatenate([np.arange(1, SEG // 2 + 1), np.arange(SEG - SEG // 2, 0, -1)]).astype(np.float32)
    weight /= weight.max()
    out = np.zeros((4, 2, n), np.float32)
    sw = np.zeros(n, np.float32)
    n_seg = 0
    for off in range(0, n, stride):
        length = min(n - off, SEG)
        if ranges is not None and not any(off < e and off + length > s for s, e in ranges):
            continue
        delta = SEG - length
        start = off - delta // 2
        end = start + SEG
        cs, ce = max(0, start), min(n, end)
        chunk = np.pad(w[:, cs:ce], ((0, 0), (cs - start, end - ce)))
        y = htd_segment(sess, np.ascontiguousarray(chunk))[..., delta // 2:delta // 2 + length]
        out[..., off:off + length] += weight[:length] * y
        sw[off:off + length] += weight[:length]
        n_seg += 1
    out /= np.maximum(sw, 1e-8)
    return out * std + mean, n_seg
