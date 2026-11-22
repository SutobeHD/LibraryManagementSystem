"""Browser-playable view of AIFF files: a virtual WAV computed from the source.

Chromium / WebView2 decode no AIFF (``<audio>`` MediaError 4, WebAudio
``decodeAudioData`` rejects), and AIFF is both the download default and most of
the library. Instead of transcoding to disk, the stream routes serve the same
PCM as a WAV whose bytes are produced on demand: a fixed 44-byte RIFF header,
then interleaved little-endian PCM. Every byte offset maps to exactly one frame,
so an HTTP Range request seeks straight into the AIFF through libsndfile. No
cache, no temp files, no wait before a long mix starts. The source is opened per
chunk, so no handle outlives a read (Windows would otherwise block the in-place
format converter until a dropped connection's generator is garbage-collected).

Samples are copied exactly for 16/24/32-bit integer and 32-bit float sources.
8-bit, u-law/A-law and IMA ADPCM widen losslessly to 16 bit; 64-bit float
narrows to 32-bit float. Anything else (DWVW: libsndfile 1.2.2 cannot seek it)
is rejected up front, so a response never breaks off mid-stream.
"""

from __future__ import annotations

import logging
import struct
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import soundfile as sf

if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger(__name__)

# Only extensions validate_audio_path admits (main.ALLOWED_AUDIO_EXTENSIONS).
WAV_VIEW_SUFFIXES = frozenset({".aif", ".aiff"})
WAV_HEADER_BYTES = 44

_WAVE_FORMAT_PCM = 1
_WAVE_FORMAT_IEEE_FLOAT = 3
# RIFF size field is u32 and counts everything after itself (36 header bytes + data).
_MAX_DATA_BYTES = 0xFFFFFFFF - 36
# Output bytes per read — matches the raw stream route's chunk size.
_CHUNK_BYTES = 1024 * 1024


class WavViewError(Exception):
    """Source cannot be presented as WAV (unreadable, unsupported or too large)."""


@dataclass(frozen=True)
class _Encoding:
    read_dtype: str  # dtype libsndfile converts the source samples to
    out_dtype: str  # little-endian dtype written to the WAV
    bits: int
    format_tag: int


_PCM16 = _Encoding("int16", "<i2", 16, _WAVE_FORMAT_PCM)
_PCM24 = _Encoding("int32", "<i4", 24, _WAVE_FORMAT_PCM)
_PCM32 = _Encoding("int32", "<i4", 32, _WAVE_FORMAT_PCM)
_FLOAT32 = _Encoding("float32", "<f4", 32, _WAVE_FORMAT_IEEE_FLOAT)

# libsndfile subtypes verified to read + seek bit-exactly. Unlisted ones raise WavViewError.
_ENCODINGS: dict[str, _Encoding] = {
    "PCM_16": _PCM16,
    "PCM_24": _PCM24,
    "PCM_32": _PCM32,
    "FLOAT": _FLOAT32,
    "DOUBLE": _FLOAT32,
    "PCM_S8": _PCM16,
    "PCM_U8": _PCM16,
    "ULAW": _PCM16,
    "ALAW": _PCM16,
    "IMA_ADPCM": _PCM16,
}


@dataclass(frozen=True)
class WavView:
    source: Path
    samplerate: int
    channels: int
    frames: int
    encoding: _Encoding

    @property
    def frame_bytes(self) -> int:
        return self.channels * self.encoding.bits // 8

    @property
    def data_bytes(self) -> int:
        return self.frames * self.frame_bytes

    @property
    def size(self) -> int:
        return WAV_HEADER_BYTES + self.data_bytes

    @property
    def header(self) -> bytes:
        block_align = self.frame_bytes
        return struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF",
            36 + self.data_bytes,
            b"WAVE",
            b"fmt ",
            16,
            self.encoding.format_tag,
            self.channels,
            self.samplerate,
            self.samplerate * block_align,
            block_align,
            self.encoding.bits,
            b"data",
            self.data_bytes,
        )


def needs_wav_view(path: Path) -> bool:
    """True for files the browser cannot decode and the stream routes serve as WAV."""
    return path.suffix.lower() in WAV_VIEW_SUFFIXES


def wav_filename(name: str) -> str:
    """``Track.aiff`` -> ``Track.wav`` for the response's Content-Disposition."""
    return f"{Path(name).stem}.wav"


def describe(path: Path) -> WavView:
    """Read the source header and lay out the WAV view. Blocking (opens the file)."""
    try:
        info = sf.info(str(path))
    except (sf.SoundFileError, RuntimeError, OSError) as e:
        raise WavViewError(f"unreadable audio: {e}") from e
    if info.channels < 1 or info.samplerate < 1 or info.frames < 0:
        raise WavViewError(
            f"invalid stream: channels={info.channels} rate={info.samplerate} frames={info.frames}"
        )
    encoding = _ENCODINGS.get(info.subtype)
    if encoding is None:
        raise WavViewError(f"unsupported sample encoding {info.subtype}")
    view = WavView(
        source=path,
        samplerate=int(info.samplerate),
        channels=int(info.channels),
        frames=int(info.frames),
        encoding=encoding,
    )
    if view.data_bytes > _MAX_DATA_BYTES:
        raise WavViewError(f"{view.data_bytes} PCM bytes exceed the 4 GiB WAV limit")
    return view


def parse_range(header: str, size: int) -> tuple[int, int] | None:
    """``Range`` header -> inclusive ``(start, end)``, per RFC 7233.

    ``None``: header to be ignored (other unit, malformed, multiple ranges) -> serve
    the whole file with 200. ValueError: syntactically valid but unsatisfiable -> 416.
    Handles open-ended (``500-``) and suffix (``-500`` = last 500 bytes) forms.
    """
    units, sep, spec = header.partition("=")
    if not sep or units.strip().lower() != "bytes" or "," in spec:
        return None
    start_s, dash, end_s = (part.strip() for part in spec.strip().partition("-"))
    if not dash or not (start_s or end_s):
        return None
    if not (start_s or "0").isdigit() or not (end_s or "0").isdigit():
        return None
    if not start_s:
        if int(end_s) == 0 or size == 0:
            raise ValueError("empty suffix range")
        return max(size - int(end_s), 0), size - 1
    start = int(start_s)
    if end_s and int(end_s) < start:
        return None
    if start >= size:
        raise ValueError("range starts past the end")
    end = min(int(end_s), size - 1) if end_s else size - 1
    return start, end


def _encode(block: np.ndarray, enc: _Encoding) -> bytes:
    # numpy on first use only: app.main imports this module at sidecar boot and must
    # stay numpy-free (tests/test_librosa_lazy_import.py). soundfile imports it lazily too.
    import numpy as np

    if enc.bits == 24:
        # libsndfile returns 24-bit samples left-justified in int32 (sample << 8), so the
        # little-endian bytes 1..3 of every int32 are the exact 24-bit sample.
        as_bytes = block.astype(enc.out_dtype, copy=False).view(np.uint8).reshape(-1, 4)
        return as_bytes[:, 1:].tobytes()
    return block.astype(enc.out_dtype, copy=False).tobytes()


def _read_block(view: WavView, frame: int, n: int) -> bytes:
    """Up to ``n`` frames from ``frame`` on, encoded. Short or empty past the source's end."""
    try:
        with sf.SoundFile(str(view.source)) as f:
            if frame >= f.frames:
                return b""
            if frame:
                f.seek(frame)
            block = f.read(n, dtype=view.encoding.read_dtype, always_2d=True)
    except (sf.SoundFileError, RuntimeError, OSError) as e:
        # Replaced or removed mid-stream (format converter, tag rewrite): finish with
        # silence instead of breaking off the response.
        logger.warning("op=wav_view_read file=%s frame=%d err=%s", view.source.name, frame, e)
        return b""
    return _encode(block, view.encoding)


def iter_range(view: WavView, start: int, end: int) -> Iterator[bytes]:
    """Bytes ``start..end`` (inclusive) of the WAV view, in ~1 MiB chunks. Blocking.

    Frames the source no longer has (it shrank or vanished after ``describe``) go
    out as silence, so the response always matches the Content-Length announced
    from ``view.size``.
    """
    end = min(end, view.size - 1)
    if start > end:
        return
    if start < WAV_HEADER_BYTES:
        yield view.header[start : min(end + 1, WAV_HEADER_BYTES)]
        start = WAV_HEADER_BYTES
        if start > end:
            return

    fb = view.frame_bytes
    rel_start = start - WAV_HEADER_BYTES
    rel_stop = end + 1 - WAV_HEADER_BYTES  # exclusive
    frame = rel_start // fb
    stop_frame = -(-rel_stop // fb)  # ceil: the frame holding the last byte is read whole
    block_frames = max(1, _CHUNK_BYTES // fb)

    while frame < stop_frame:
        n = min(block_frames, stop_frame - frame)
        data = _read_block(view, frame, n)
        if len(data) < n * fb:
            data += bytes(n * fb - len(data))
        base = frame * fb
        lo = max(rel_start - base, 0)
        hi = min(rel_stop - base, n * fb)
        yield data if (lo == 0 and hi == len(data)) else data[lo:hi]
        frame += n
