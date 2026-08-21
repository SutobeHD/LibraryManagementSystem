"""Per-encoder FFmpeg binary resolution with cached ``-encoders`` probing.

The PATH ``ffmpeg`` on a stripped build may only carry ``pcm_s16le`` — enough
for AIFF/WAV, useless for MP3/FLAC. This module walks an ordered candidate
list (user setting > env var > PATH default > well-known install locations >
Electron ``ffmpeg-static`` bundles) and picks the first binary whose audio
encoder set contains the encoder a target format requires.

``ffprobe`` resolution is deliberately independent (:func:`resolve_ffprobe`):
discovery candidates like Electron bundles ship **no** ffprobe sibling, so
deriving ffprobe from the resolved ffmpeg would break sample-rate probing for
every track. ffprobe derives only from the configured path / PATH default and
falls back to bare ``ffprobe``.

Used by ``app/library_format_swap.py`` (command building + export preflight)
and ``GET /api/library/format-swap/capabilities`` in ``app/main.py``.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.config import FFMPEG_BIN

logger = logging.getLogger("FFMPEG_RESOLVER")

# Short probe timeout per coding-rules subprocess default — a `-encoders`
# listing is instant; anything slower is a hung/broken binary.
PROBE_TIMEOUT_SEC = 10

# Audio-encoder line in `ffmpeg -hide_banner -encoders` output, e.g.
# " A....D pcm_s16le        PCM signed 16-bit little-endian"
_AUDIO_ENCODER_RE = re.compile(r"^\s*A[A-Z.]{5}\s+(\S+)")

# Memoised probe results keyed on the candidate path string. A settings
# change produces a new key -> natural invalidation. Failures cached too.
_ENCODER_CACHE: dict[str, frozenset[str] | None] = {}


@dataclass(frozen=True)
class ResolvedFfmpeg:
    available: bool
    binary: str | None = None
    source: str | None = None
    reason: str | None = None


def clear_probe_cache() -> None:
    _ENCODER_CACHE.clear()


def configured_settings_ffmpeg() -> str:
    """Late-bound read of the ``ffmpeg_path`` settings key (never at import)."""
    try:
        from app.services import SettingsManager

        return str(SettingsManager.load().get("ffmpeg_path", "") or "").strip()
    except (ImportError, AttributeError, TypeError) as e:
        logger.debug("ffmpeg_resolver: settings read failed (%s)", e)
        return ""


def candidate_binaries() -> list[tuple[str, str]]:
    """Ordered ``(path, source_label)`` candidates.

    PATH default is tried BEFORE discovery paths so aiff/wav resolve to
    today's binary and default-target behavior is unchanged. Electron
    ``ffmpeg-static`` bundles come last — they belong to other apps and may
    vanish on their uninstall.
    """
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(path: str, source: str) -> None:
        key = path.casefold()
        if key not in seen:
            seen.add(key)
            out.append((path, source))

    settings_path = configured_settings_ffmpeg()
    if settings_path and Path(settings_path).exists():
        add(settings_path, "settings")

    env_path = os.environ.get("LMS_FFMPEG_FULL") or ""
    if env_path and Path(env_path).exists():
        add(env_path, "env")

    # Bare PATH lookup — no existence check possible/needed.
    add(FFMPEG_BIN, "default")

    local_appdata = os.environ.get("LOCALAPPDATA") or ""
    if local_appdata:
        links = Path(local_appdata) / "Microsoft" / "WinGet" / "Links" / "ffmpeg.exe"
        if links.exists():
            add(str(links), "winget")
        packages = Path(local_appdata) / "Microsoft" / "WinGet" / "Packages"
        try:
            hits = sorted(
                packages.glob("Gyan.FFmpeg*/ffmpeg-*/bin/ffmpeg.exe"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            hits = []
        for hit in hits:
            add(str(hit), "winget")

    manual = Path("C:/ffmpeg/bin/ffmpeg.exe")
    if manual.exists():
        add(str(manual), "manual_c_ffmpeg")

    choco = Path("C:/ProgramData/chocolatey/bin/ffmpeg.exe")
    if choco.exists():
        add(str(choco), "chocolatey")

    userprofile = os.environ.get("USERPROFILE") or ""
    if userprofile:
        scoop = Path(userprofile) / "scoop" / "shims" / "ffmpeg.exe"
        if scoop.exists():
            add(str(scoop), "scoop")

    if local_appdata:
        programs = Path(local_appdata) / "Programs"
        try:
            electron_hits = sorted(
                programs.glob("*/resources/app.asar.unpacked/node_modules/ffmpeg-static/ffmpeg.exe")
            )
        except OSError:
            electron_hits = []
        for hit in electron_hits:
            add(str(hit), "electron_ffmpeg_static")

    return out


def probe_audio_encoders(path: str) -> frozenset[str] | None:
    """Audio encoder names of ``path``, or ``None`` when the probe fails.

    Memoised (failures too) — :func:`clear_probe_cache` re-probes.
    """
    key = str(path)
    if key in _ENCODER_CACHE:
        return _ENCODER_CACHE[key]

    encoders: frozenset[str] | None
    try:
        r = subprocess.run(
            [key, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=PROBE_TIMEOUT_SEC,
        )
        if r.returncode != 0:
            encoders = None
        else:
            found: set[str] = set()
            for line in (r.stdout or "").splitlines():
                m = _AUDIO_ENCODER_RE.match(line)
                # "=" filters the header legend line (" A..... = Audio").
                if m and m.group(1) != "=":
                    found.add(m.group(1))
            encoders = frozenset(found)
    except (subprocess.SubprocessError, OSError) as e:
        logger.debug("ffmpeg_resolver: probe failed for %s (%s)", key, e)
        encoders = None

    _ENCODER_CACHE[key] = encoders
    return encoders


def resolve_for_encoder(encoder: str) -> ResolvedFfmpeg:
    """First candidate whose probe carries ``encoder`` wins."""
    probed = 0
    for path, source in candidate_binaries():
        encoders = probe_audio_encoders(path)
        probed += 1
        if encoders and encoder in encoders:
            return ResolvedFfmpeg(available=True, binary=path, source=source)
    return ResolvedFfmpeg(
        available=False,
        binary=None,
        source=None,
        reason=f"no '{encoder}' encoder found in {probed} probed binaries",
    )


def _derive_sibling_ffprobe(ffmpeg_path: str) -> str | None:
    low = ffmpeg_path.lower()
    if low.endswith("ffmpeg.exe"):
        return ffmpeg_path[:-10] + "ffprobe.exe"
    if low.endswith("ffmpeg"):
        return ffmpeg_path[:-6] + "ffprobe"
    return None


def resolve_ffprobe() -> str:
    """ffprobe path, independent of discovery-candidate ffmpeg binaries.

    Derives the sibling only from the configured ``ffmpeg_path`` and the PATH
    default; an absolute derivation is accepted only when it exists on disk.
    Never derived from a discovery candidate (Electron bundles ship no
    ffprobe — deriving would fail every track before ffmpeg even runs).
    """
    for cand in (configured_settings_ffmpeg(), FFMPEG_BIN):
        if not cand:
            continue
        derived = _derive_sibling_ffprobe(cand)
        if derived is None:
            continue
        p = Path(derived)
        if p.is_absolute():
            if p.exists():
                return derived
            continue
        return derived  # bare name -> PATH lookup (today's behavior)
    return "ffprobe"
