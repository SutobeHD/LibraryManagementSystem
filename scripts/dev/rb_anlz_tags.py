"""Raw Rekordbox ANLZ tag editing + MP3/FLAC container helpers (no pyrekordbox dependency).

Why raw: pyrekordbox's AnlzFile drops tags it does not know (e.g. PVB2) on save, and the
copies pipeline needs byte-exact control over PPTH / PVBR / PQTZ / PQT2 / PWV* / PVB2.

ANLZ layout: 28-byte file header (``PMAI``, len_header, len_file, ...) followed by tags,
each ``<fourcc><len_header><len_tag>...`` big-endian; ``len_tag`` covers the whole tag.
Verified against real Rekordbox 6.8 / 7.x files on 2026-10-16..22 (see
``scripts/dev/rb_format_copies.py`` for the pipeline that uses this module).
"""

from __future__ import annotations

import hashlib
import struct
import subprocess
from pathlib import Path

Tag = tuple[str, int, bytes]  # (fourcc, len_header, raw tag incl. header)


# ── file level ───────────────────────────────────────────────────────────────────────


def read_tags(path: Path | str) -> tuple[bytes, list[Tag]]:
    b = Path(path).read_bytes()
    magic, hlen, _tlen = struct.unpack(">4sII", b[:12])
    if magic != b"PMAI":
        raise ValueError(f"{path}: not an ANLZ file (magic {magic!r})")
    tags: list[Tag] = []
    i = hlen
    while i < len(b):
        fourcc, th, tl = struct.unpack(">4sII", b[i : i + 12])
        tags.append((fourcc.decode("ascii"), th, b[i : i + tl]))
        i += tl
    return b[:hlen], tags


def write_tags(path: Path | str, head: bytes, tags: list[Tag]) -> None:
    body = b"".join(t[2] for t in tags)
    head = head[:8] + struct.pack(">I", len(head) + len(body)) + head[12:]
    Path(path).write_bytes(head + body)


def md5_file(path: Path | str) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ── individual tags ──────────────────────────────────────────────────────────────────


def ppth_tag(filename: str) -> bytes:
    """Rekordbox 6+ stores only ``?/<filename>`` (UTF-16-BE, NUL-terminated)."""
    enc = ("?/" + filename).encode("utf-16-be") + b"\x00\x00"
    return b"PPTH" + struct.pack(">III", 16, 16 + len(enc), len(enc)) + enc


def pvbr_tag(raw: bytes, last: int) -> bytes:
    """400 zero entries + one trailing value: 0 for PCM/FLAC, ``frames*1152`` for MP3."""
    th = struct.unpack(">I", raw[4:8])[0]
    n = (len(raw) - th) // 4
    return raw[:th] + b"\x00" * ((n - 1) * 4) + struct.pack(">I", last)


def pqtz_entries(raw: bytes) -> list[tuple[int, int, int]]:
    """(beat, tempo*100, time_ms) per beat."""
    th = struct.unpack(">I", raw[4:8])[0]
    return [struct.unpack(">HHI", raw[o : o + 8]) for o in range(th, len(raw), 8)]


def shift_pqtz(raw: bytes, ms: int) -> bytes:
    th = struct.unpack(">I", raw[4:8])[0]
    b = bytearray(raw)
    for off in range(th, len(raw), 8):
        t = struct.unpack(">I", b[off + 4 : off + 8])[0]
        b[off + 4 : off + 8] = struct.pack(">I", t + ms)
    return bytes(b)


def shift_pqt2(raw: bytes, ms: int) -> bytes:
    """PQT2 header carries first/last beat time at offsets 28 and 36."""
    b = bytearray(raw)
    for off in (28, 36):
        t = struct.unpack(">I", b[off : off + 4])[0]
        b[off : off + 4] = struct.pack(">I", t + ms)
    return bytes(b)


def shift_wave(raw: bytes, k: int) -> bytes:
    """Prepend ``k`` zero entries to a PWV3/PWV5/PWV7 waveform (150 entries/s)."""
    fourcc, th, tl, eb, ne = struct.unpack(">4sIIII", raw[:20])
    if tl != len(raw) or (tl - th) != eb * ne:
        raise ValueError(f"{fourcc!r}: unexpected waveform layout")
    body = b"\x00" * (eb * k) + raw[th:]
    head = bytearray(raw[:th])
    head[8:12] = struct.pack(">I", th + len(body))
    head[16:20] = struct.pack(">I", ne + k)
    return bytes(head) + body


def pwv3_heights(raw: bytes):
    import numpy as np

    return np.frombuffer(raw[24:], dtype=np.uint8) & 0x1F


# ── MP3 header (encoder delay) ───────────────────────────────────────────────────────


def mp3_header(path: Path | str) -> dict:
    """First frame offset + Xing/Info tag + LAME encoder string + delay/padding."""
    b = Path(path).read_bytes()
    i = 0
    if b[:3] == b"ID3":
        sz = (b[6] << 21) | (b[7] << 14) | (b[8] << 7) | b[9]
        i = 10 + sz + (10 if b[5] & 0x10 else 0)
    while i < len(b) - 4 and not (b[i] == 0xFF and (b[i + 1] & 0xE0) == 0xE0):
        i += 1
    hdr = b[i : i + 4]
    ver = (hdr[1] >> 3) & 3  # 3 = MPEG1
    mono = (hdr[3] >> 6) == 3
    side = (17 if mono else 32) if ver == 3 else (9 if mono else 17)
    tagpos = i + 4 + side
    tag = b[tagpos : tagpos + 4]
    res: dict = {"first_frame": i, "xing": tag.decode("latin1") if tag in (b"Xing", b"Info") else None}
    if res["xing"]:
        flags = int.from_bytes(b[tagpos + 4 : tagpos + 8], "big")
        off = tagpos + 8
        off += (4 if flags & 1 else 0) + (4 if flags & 2 else 0)
        off += (100 if flags & 4 else 0) + (4 if flags & 8 else 0)
        res["enc"] = b[off : off + 9].decode("latin1", "replace")
        x = b[off + 21 : off + 24]
        res["delay"] = (x[0] << 4) | (x[1] >> 4)
        res["pad"] = ((x[1] & 15) << 8) | x[2]
    return res


def rekordbox_mp3_view(path: Path | str) -> tuple[list[str], int, dict]:
    """How Rekordbox decodes this MP3 relative to ffmpeg's default (gapless) decode.

    Measured 2026-10-16 by aligning stored PWV3 waveforms against decoded audio:
      Info frame by real LAME (``LAME`` upper-case) -> full decode + 1152 samples
      Info frame by ffmpeg (``Lavc``/``Lavf``)       -> full decode (no gapless trim)
      no Info frame / ``Lame`` lower-case            -> same as ffmpeg default
    Returns (extra ffmpeg input args, samples to prepend, header dict).
    """
    h = mp3_header(path)
    enc = h.get("enc") or ""
    if h["xing"] and enc.startswith("LAME"):
        return ["-flags2", "+skip_manual"], 1152, h
    if h["xing"] and enc.startswith(("Lavc", "Lavf")):
        return ["-flags2", "+skip_manual"], 0, h
    return [], 0, h


# ── FLAC seek index (PVB2) ───────────────────────────────────────────────────────────


def flac_frames(path: Path | str, ffprobe: str = "ffprobe") -> list[tuple[int, int, int]]:
    """(pts_samples, duration_samples, byte_pos) per FLAC frame."""
    r = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "a:0", "-show_entries",
         "packet=pts,duration,pos", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, timeout=300,
    )
    out = []
    for line in r.stdout.split():
        parts = line.split(",")
        if len(parts) >= 3:
            out.append((int(parts[0]), int(parts[1]), int(parts[2])))
    return out


def build_pvb2(path: Path | str, ffprobe: str = "ffprobe", n: int = 400) -> bytes:
    """Rekordbox's FLAC seek table: 400 x (u64 sample, u64 byte offset, u32 blocksize).

    Entry k = last frame starting strictly before ``k * total / n``. Reproduces
    Rekordbox's own tag byte-exact on ~98 % of files (rest differ by one frame).
    """
    fr = flac_frames(path, ffprobe)
    total = fr[-1][0] + fr[-1][1]
    base = fr[0][2]
    body = b""
    for k in range(n):
        target = k * total // n
        lo, hi = 0, len(fr) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if fr[mid][0] < target or mid == 0:
                lo = mid
            else:
                hi = mid - 1
        pts, dur, pos = fr[lo]
        body += struct.pack(">QQI", pts, pos - base, dur)
    return b"PVB2" + struct.pack(">IIIIIII", 32, 32 + len(body), 0, 0, total, n, 20) + body


# ── .3EX embedding (msgpack) ─────────────────────────────────────────────────────────


def _msgpack_str(s: str) -> bytes:
    b = s.encode()
    return (bytes([0xA0 | len(b)]) if len(b) < 32 else b"\xd9" + bytes([len(b)])) + b


def patch_3ex(path: Path | str, content_id: str, audio_md5: str) -> None:
    """``d2`` = own content ID, ``d3`` = md5 of own audio file; everything else untouched."""
    import msgpack

    p = Path(path)
    raw = p.read_bytes()
    before = msgpack.unpackb(raw, raw=False, strict_map_key=False)
    out = raw
    for key, val in ((b"d2", content_id), (b"d3", audio_md5)):
        i = out.index(b"\xa2" + key) + 3
        tag = out[i]
        if 0xA0 <= tag <= 0xBF:
            n, hl = tag & 0x1F, 1
        elif tag == 0xD9:
            n, hl = out[i + 1], 2
        else:
            raise ValueError(f"unexpected msgpack type {tag:#x} for {key!r}")
        out = out[:i] + _msgpack_str(val) + out[i + hl + n :]
    after = msgpack.unpackb(out, raw=False, strict_map_key=False)
    eb, ea = before["embedding"], after["embedding"]
    if ea["d2"] != content_id or ea["d3"] != audio_md5:
        raise ValueError("3EX patch failed")
    rest = lambda e: {k: v for k, v in e.items() if k not in ("d2", "d3")}  # noqa: E731
    if rest(eb) != rest(ea):
        raise ValueError("3EX patch touched other fields")
    p.write_bytes(out)
