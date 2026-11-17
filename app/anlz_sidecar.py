"""
LMS ANLZ cache — DAT/EXT/2EX files LMS generated for a track that has no
Rekordbox analysis (XML-mode import, SoundCloud download, USB-export fallback).
The USB-sync engine (OneLibraryUsbWriter) copies them to
PIONEER/USBANLZ/<bucket>/<hash>/ on the stick.

Layout (per-user cache dir, never the music folder):
    <user cache>/MusicLibraryManager/anlz/<sha-of-abs-path>/ANLZ0000.DAT
                                                            /ANLZ0000.EXT
                                                            /ANLZ0000.2EX

Older builds wrote ``<music_dir>/.lms_anlz/<sha>/`` next to the audio file, i.e.
into the user's music collection. Those folders are still read
(``legacy_sidecar_dir_for``) but nothing writes there any more.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any

from platformdirs import user_cache_dir

logger = logging.getLogger(__name__)

_APP_DIRNAME = "MusicLibraryManager"


def anlz_cache_root() -> Path:
    """Root of the LMS ANLZ cache: the per-user cache dir, outside every music folder."""
    return Path(user_cache_dir(_APP_DIRNAME, appauthor=False)) / "anlz"


def _path_key(file_path: Path) -> str:
    return hashlib.sha1(str(file_path.resolve()).encode("utf-8")).hexdigest()[:16]


def sidecar_dir_for(file_path: Path) -> Path:
    """Stable, collision-resistant per-track ANLZ cache directory (keyed on the path)."""
    return anlz_cache_root() / _path_key(file_path)


def legacy_sidecar_dir_for(file_path: Path) -> Path:
    """Where builds before 0.1 wrote the sidecar, next to the audio. Read-only."""
    return file_path.parent / ".lms_anlz" / _path_key(file_path)


def write_companion_anlz(
    file_path: Path, analysis_result: dict[str, Any] | None = None
) -> Path | None:
    """
    Write DAT/EXT/2EX for file_path into the LMS ANLZ cache. Returns the cache
    directory on success, None on failure. Never writes next to the audio file.

    If analysis_result is None, runs the full analysis pipeline (uses the
    on-disk cache so re-imports are cheap).

    NEVER raises — ANLZ is best-effort. The caller should never fail an
    import just because beatgrid binaries couldn't be written.
    """
    file_path = Path(file_path)
    if not file_path.exists():
        logger.warning("anlz_sidecar: file missing %s", file_path)
        return None

    try:
        if analysis_result is None:
            from .analysis_engine import run_full_analysis

            analysis_result = run_full_analysis(str(file_path)) or {}
            if analysis_result.get("status") != "ok":
                logger.warning(
                    "anlz_sidecar: analysis returned status=%s for %s",
                    analysis_result.get("status"),
                    file_path.name,
                )
                return None
    except Exception as exc:
        logger.warning("anlz_sidecar: analysis failed for %s: %s", file_path.name, exc)
        return None

    try:
        from .anlz_writer import write_anlz_files

        target = sidecar_dir_for(file_path)
        target.mkdir(parents=True, exist_ok=True)
        write_anlz_files(
            anlz_dir=str(target),
            track_path=str(file_path),
            analysis_result=analysis_result,
            filename_base="ANLZ0000",
        )
        # Sanity-check the color-waveform data — three-band FFT should produce
        # 1190+/1200 non-zero entries on any real audio. Warn loudly if we're
        # accidentally shipping zero/stub waveforms (regression guard).
        wf = analysis_result.get("waveform", {}) or {}
        pwv6 = wf.get("pwv6") or []
        if pwv6:
            # isinstance MUST come first: comprehension `if` clauses run
            # left-to-right, so `any(e)` ahead of the guard would raise TypeError
            # on a non-iterable element and (since the ANLZ files are already
            # written above) make a successful write report failure.
            nonzero = sum(1 for e in pwv6 if isinstance(e, (list, tuple)) and any(e))
            ratio = nonzero / max(len(pwv6), 1)
            if ratio < 0.5:
                logger.warning(
                    "anlz_sidecar: %s — only %.0f%% of pwv6 entries non-zero "
                    "(suspect stub waveform)",
                    file_path.name,
                    ratio * 100,
                )
            else:
                logger.info(
                    "anlz_sidecar: %s → %s (color-waveform: %d/%d entries, %d hd-detail)",
                    file_path.name,
                    target.name,
                    nonzero,
                    len(pwv6),
                    len(wf.get("pwv7") or []),
                )
        else:
            logger.info(
                "anlz_sidecar: %s → %s (no color waveform data)", file_path.name, target.name
            )
        return target
    except Exception as exc:
        logger.warning("anlz_sidecar: write failed for %s: %s", file_path.name, exc)
        return None
