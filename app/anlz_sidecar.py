"""
ANLZ-Sidecar writer — shared helper used by every track-import path
(SoundCloud download, drag-drop import, folder watcher) so the resulting
DAT/EXT/2EX files always end up in a deterministic location next to the
audio file. The USB-sync engine (OneLibraryUsbWriter) then copies them
straight to PIONEER/USBANLZ/<bucket>/<hash>/ on the stick.

Layout:
    <music_dir>/.lms_anlz/<sha-of-abs-path>/ANLZ0000.DAT
                                            /ANLZ0000.EXT
                                            /ANLZ0000.2EX
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def sidecar_dir_for(file_path: Path) -> Path:
    """Stable, collision-resistant per-track sidecar directory."""
    h = hashlib.sha1(str(file_path.resolve()).encode("utf-8")).hexdigest()[:16]
    return file_path.parent / ".lms_anlz" / h


def write_companion_anlz(file_path: Path, analysis_result: Optional[Dict[str, Any]] = None) -> Optional[Path]:
    """
    Write DAT/EXT/2EX next to file_path. Returns the sidecar directory on
    success, None on failure.

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
            analysis_result = run_full_analysis(str(file_path))
            if analysis_result.get("status") != "ok":
                logger.warning(
                    "anlz_sidecar: analysis returned status=%s for %s",
                    analysis_result.get("status"), file_path.name,
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
            nonzero = sum(1 for e in pwv6 if any(e) if isinstance(e, (list, tuple)))
            ratio = nonzero / max(len(pwv6), 1)
            if ratio < 0.5:
                logger.warning(
                    "anlz_sidecar: %s — only %.0f%% of pwv6 entries non-zero "
                    "(suspect stub waveform)",
                    file_path.name, ratio * 100,
                )
            else:
                logger.info(
                    "anlz_sidecar: %s → %s (color-waveform: %d/%d entries, "
                    "%d hd-detail)",
                    file_path.name, target.name,
                    nonzero, len(pwv6), len(wf.get("pwv7") or []),
                )
        else:
            logger.info("anlz_sidecar: %s → %s (no color waveform data)",
                        file_path.name, target.name)
        return target
    except Exception as exc:
        logger.warning("anlz_sidecar: write failed for %s: %s", file_path.name, exc)
        return None
