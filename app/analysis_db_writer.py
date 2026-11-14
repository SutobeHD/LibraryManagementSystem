"""
LibraryManagementSystem -- Analysis-to-Database Writer
=============================================
Orchestrates writing analysis results into the Rekordbox live database:
  1. Runs AnalysisEngine on a track
  2. Writes ANLZ binary files (.DAT, .EXT, .2EX) via anlz_writer
  3. Updates djmdContent fields (BPM, key, analysed flag) via rbox

This replaces the need for Rekordbox to analyze tracks — our analysis
is injected directly, and Rekordbox will read it as if it analyzed the track itself.
"""

import logging
import os
import time
from collections.abc import Generator
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: File stem the writer uses inside a track's ANLZ dir (``ANLZ0000.DAT`` / ``.EXT`` / ``.2EX``).
_ANLZ_BASE = "ANLZ0000"

#: How long one track's analysis may run in the worker pool before the writer stops
#: waiting and reports ``analysis_failed``. A long DJ mix legitimately takes minutes.
_ANALYSIS_TIMEOUT_S = 900.0

#: ``djmdContent.Analysed`` for a fully analysed track: the value Rekordbox itself writes
#: (4905 of 4906 rows of a real library, 2026-11-14). rbox maps the column to a C long,
#: so the old 0xFFFFFFFF raised OverflowError on assignment and killed the whole write.
REKORDBOX_ANALYSED = 105

#: Pitch classes as Rekordbox's own analysis names them in ``djmdKey.ScaleName``: flats,
#: except F#. All twelve minor names (Dbm, Ebm, F#m, Abm, Bbm, ...) appear verbatim in a
#: real library. ``update_content_key`` reuses a row by exact name and creates a new one
#: for any other spelling, so "A minor" would add a key Rekordbox never uses.
_REKORDBOX_PITCH_NAMES = ("C", "Db", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")


class AnalysisDbUpdateError(RuntimeError):
    """master.db refused the analysis write (row missing, rbox error, bad value).

    ``bpm_written``: the row update (BPM + analysed) landed before a later part
    (the key) failed, so master.db already holds the new BPM.
    """

    def __init__(self, message: str, *, bpm_written: bool = False) -> None:
        super().__init__(message)
        self.bpm_written = bpm_written


def rekordbox_key_name(key_id: Any) -> str | None:
    """Rekordbox key name for an ``analysis_engine`` key id (1-12 major, 13-24 minor)."""
    if not isinstance(key_id, int) or isinstance(key_id, bool) or not 1 <= key_id <= 24:
        return None
    root = _REKORDBOX_PITCH_NAMES[(key_id - 1) % 12]
    return root if key_id <= 12 else f"{root}m"


def rekordbox_anlz_rel_path(content_uuid: str | None) -> str | None:
    """The ``AnalysisDataPath`` Rekordbox records for a content row, from its uuid.

    ``/PIONEER/USBANLZ/<uuid[:3]>/<uuid[3:]>/ANLZ0000.DAT`` (relative to the share dir).
    4897 of 4905 analysed rows of a real library follow it exactly (2026-11-14); the
    other 8 are Rekordbox re-analyses (``ANLZ0001``) or relocated files.
    """
    u = (content_uuid or "").strip()
    if len(u) < 4 or any(c in u for c in "/\\:") or ".." in u:
        return None
    return f"/PIONEER/USBANLZ/{u[:3]}/{u[3:]}/{_ANLZ_BASE}.DAT"


class AnalysisDBWriter:
    """
    Writes analysis results into the Rekordbox live database.

    Usage:
        writer = AnalysisDBWriter(live_db)
        result = writer.analyze_and_save(track_id)
        # or batch:
        for progress in writer.analyze_batch(track_ids):
            print(progress)
    """

    def __init__(self, live_db):
        """
        Args:
            live_db: LiveRekordboxDB instance (must be loaded and connected)
        """
        self.live_db = live_db
        self._executor: ProcessPoolExecutor | None = None

    def _get_executor(self) -> ProcessPoolExecutor:
        if self._executor is None:
            cores = max(1, (os.cpu_count() or 2) - 1)
            self._executor = ProcessPoolExecutor(max_workers=cores)
        return self._executor

    def shutdown(self):
        if self._executor:
            self._executor.shutdown(wait=False)
            self._executor = None

    def analyze_and_save(
        self,
        track_id: str,
        force: bool = False,
    ) -> dict[str, Any]:
        """
        Full pipeline: analyze a track and write results to Rekordbox DB + ANLZ files.

        Args:
            track_id: djmdContent ID
            force: If True, re-analyze even if track is already analyzed

        Returns:
            Dict with analysis results and write status. An ``error`` result
            carries a ``reason`` (``track_not_found`` / ``no_anlz_path`` /
            ``audio_missing`` / ``analysis_failed`` / ``anlz_write_failed`` /
            ``db_update_failed``) so callers can map it without parsing ``error``,
            which may hold an absolute file path.
        """

        # 1. Validate track exists
        track = self.live_db.tracks.get(str(track_id))
        if not track:
            return {
                "status": "error",
                "reason": "track_not_found",
                "error": f"Track {track_id} not found",
            }

        # 2. Where this track's ANLZ files live: only the AnalysisDataPath recorded in
        # master.db counts, file name included (a Rekordbox re-analysis records
        # ANLZ0001.DAT). Files in a dir we picked ourselves would be linked to no
        # row, while the row still claimed "analysed" — Rekordbox then shows a BPM
        # with no grid or waveform and never re-analyses the track. A track without a
        # path is refused before any DSP runs; LMS imports record one at import time
        # (``LiveRekordboxDB.attach_import_anlz``).
        recorded_dat = self._recorded_anlz_dat(track_id)
        if recorded_dat is None:
            return {
                "status": "error",
                "reason": "no_anlz_path",
                "error": (
                    f"Track {track_id} has no AnalysisDataPath in master.db. "
                    "Analyse it once in Rekordbox first."
                ),
            }

        # 3. Check if already analyzed (skip unless forced)
        if not force:
            existing_bpm = track.get("BPM", 0)
            if existing_bpm and existing_bpm > 0 and recorded_dat.is_file():
                logger.info(
                    f"Track {track_id} already analyzed (BPM={existing_bpm}), skipping. Use force=True to re-analyze."
                )
                return {
                    "status": "skipped",
                    "reason": "already_analyzed",
                    "bpm": existing_bpm,
                }

        # 4. Get audio file path
        file_path = track.get("path", "")
        if not file_path or not os.path.exists(file_path):
            return {
                "status": "error",
                "reason": "audio_missing",
                "error": f"Audio file not found: {file_path}",
            }

        logger.info(f"Starting analysis for track {track_id}: {os.path.basename(file_path)}")
        start_time = time.time()

        # 5. Run analysis
        try:
            analysis = self._run_analysis(file_path)
        except Exception as e:
            logger.error(f"Analysis failed for track {track_id}: {e}")
            return {
                "status": "error",
                "reason": "analysis_failed",
                "error": f"Analysis failed: {e}",
            }

        if analysis.get("status") == "error":
            return {
                "status": "error",
                "reason": "analysis_failed",
                "error": analysis.get("error", "Unknown analysis error"),
            }

        elapsed_analysis = time.time() - start_time
        logger.info(
            f"Analysis complete for {track_id}: BPM={analysis['bpm']}, Key={analysis['key']} ({elapsed_analysis:.1f}s)"
        )

        # 6. Write ANLZ binary files. Without a .DAT (beat grid) master.db must not say
        # "analysed"; write_anlz_files swallows each file's failure on its own.
        anlz_paths = self._write_anlz(track_id, file_path, analysis, recorded_dat)
        if "dat" not in anlz_paths:
            return {
                "status": "error",
                "reason": "anlz_write_failed",
                "error": f"Writing ANLZ files for track {track_id} failed",
            }

        # 7. Update database. A refused write is an error, not "ok": the ANLZ files are
        # new but master.db still holds the old values. The cache follows master.db:
        # only a BPM that did land (the key write failed after it) reaches it.
        try:
            db_updated = self._update_db(track_id, analysis)
        except AnalysisDbUpdateError as e:
            logger.error(f"DB update failed for track {track_id}: {e}")
            if e.bpm_written:
                track["BPM"] = analysis["bpm"]
            return {
                "status": "error",
                "reason": "db_update_failed",
                "error": f"master.db update failed for track {track_id}: {e}",
                "anlz_paths": anlz_paths,
            }

        # 8. Update in-memory cache
        self._update_cache(track_id, analysis)

        elapsed_total = time.time() - start_time
        logger.info(f"Track {track_id} analysis + write complete in {elapsed_total:.1f}s")

        return {
            "status": "ok",
            "track_id": track_id,
            "bpm": analysis["bpm"],
            "key": analysis["key"],
            "camelot": analysis["camelot"],
            "key_id": analysis.get("key_id", 0),
            "duration": analysis["duration"],
            "lufs": analysis.get("lufs", -100),
            "beat_count": analysis.get("beat_count", 0),
            "phrase_count": len(analysis.get("phrases", [])),
            "beat_method": analysis.get("beat_method", ""),
            "key_method": analysis.get("key_method", ""),
            "anlz_paths": anlz_paths,
            "db_updated": db_updated,
            "elapsed": round(elapsed_total, 2),
        }

    def _run_analysis(self, file_path: str) -> dict[str, Any]:
        """Run the full analysis pipeline on one file in ``AnalysisEngine``'s worker pool.

        Never in the calling (sidecar) process: librosa / madmom hold the GIL and
        hundreds of MB for seconds to minutes per track, and a native crash in that
        stack would take playback and every open request down with it.
        """
        from .analysis_engine import AnalysisEngine, run_full_analysis

        future = AnalysisEngine.get_executor().submit(run_full_analysis, file_path)
        try:
            return future.result(timeout=_ANALYSIS_TIMEOUT_S)
        except BrokenProcessPool:
            # A worker died mid-track. Drop the pool so the next submit (this batch's
            # next track, or any /api/analysis call) gets a fresh one, not this error.
            AnalysisEngine.shutdown()
            raise

    def _write_anlz(
        self, track_id: str, file_path: str, analysis: dict[str, Any], recorded_dat: Path
    ) -> dict[str, str]:
        """Write the ANLZ trio under the recorded ``.DAT``'s dir and name; ``{}`` on failure."""
        try:
            from .anlz_writer import write_anlz_files

            # The path is recorded but Rekordbox creates the dir lazily.
            recorded_dat.parent.mkdir(parents=True, exist_ok=True)
            return write_anlz_files(
                anlz_dir=str(recorded_dat.parent),
                track_path=file_path,
                analysis_result=analysis,
                filename_base=recorded_dat.stem,
            )
        except Exception as e:
            logger.error(f"Failed to write ANLZ files for track {track_id}: {e}")
            return {}

    def _recorded_anlz_dat(self, track_id: str) -> Path | None:
        """The ``.DAT`` path master.db records for the track (may not exist yet), or None.

        Not via ``get_content_anlz_paths`` / ``get_content_anlz_dir``: both
        ``unwrap()`` on an empty AnalysisDataPath and abort the process (see
        ``app/anlz_safe.py``). A track with a tag BPM that Rekordbox never analysed
        is exactly that row, and no ``except`` can catch the abort.
        """
        from .anlz_safe import resolve_anlz_dat

        dat = resolve_anlz_dat(self.live_db.db, str(track_id))
        return Path(dat) if dat else None

    def _has_anlz_dat(self, track_id: str) -> bool:
        """True when the ``.DAT`` master.db records for the track is on disk."""
        dat = self._recorded_anlz_dat(track_id)
        return dat is not None and dat.is_file()

    def _update_db(self, track_id: str, analysis: dict[str, Any]) -> bool:
        """
        Update djmdContent fields in master.db via rbox. True once every field landed.

        Updates: bpm, key, analysed flag. Never ``analysis_data_path``: the
        caller only gets here for a track whose path master.db already records
        and whose ANLZ files were just written there.

        Holds ``db_lock`` from the re-read to the last write: ``update_content``
        writes the whole row, so a row read outside the lock would clobber a
        concurrent comment / rating / artist edit.

        Raises ``AnalysisDbUpdateError`` when any part is refused (missing row, rbox
        error, a value rbox cannot store); the caller turns that into an error result.
        """
        from .database import db_lock

        row_written = False
        try:
            with db_lock():
                item = self.live_db.db.get_content_by_id(str(track_id))
                if not item:
                    raise AnalysisDbUpdateError(f"content {track_id} not found in master.db")

                bpm_int = round(analysis["bpm"] * 100)  # master.db stores centi-BPM
                item.bpm = bpm_int
                item.analysed = REKORDBOX_ANALYSED
                self.live_db.db.update_content(item)
                row_written = True
                logger.info(
                    f"Updated djmdContent for {track_id}: bpm={bpm_int}, "
                    f"analysed={REKORDBOX_ANALYSED}"
                )

                key_name = self._key_id_to_name(analysis.get("key_id", 0))
                if key_name:
                    self.live_db.db.update_content_key(str(track_id), key_name)
                    logger.info(f"Updated key for {track_id}: {key_name}")
        except AnalysisDbUpdateError:
            raise
        except Exception as e:  # rbox raises its own error types plus OverflowError/TypeError
            raise AnalysisDbUpdateError(f"{type(e).__name__}: {e}", bpm_written=row_written) from e
        return True

    def _update_cache(self, track_id: str, analysis: dict[str, Any]):
        """Update the in-memory track cache with analysis results."""
        tid = str(track_id)
        if tid not in self.live_db.tracks:
            return

        track = self.live_db.tracks[tid]
        track["BPM"] = analysis["bpm"]
        track["Key"] = analysis.get("camelot", analysis.get("key", ""))

        # Store beatgrid in cache for frontend use
        beats = analysis.get("beats", [])
        if beats:
            track["beatGrid"] = [
                {
                    "time": b["time_ms"] / 1000.0,
                    "bpm": b["tempo"] / 100.0,
                    "beat": b["beat_number"],
                }
                for b in beats
            ]

        logger.debug(f"Cache updated for track {tid}: BPM={track['BPM']}, Key={track['Key']}")

    @staticmethod
    def _key_id_to_name(key_id: Any) -> str | None:
        """Rekordbox key name ("Am", "F#", "Dbm") for an engine key id, else None."""
        return rekordbox_key_name(key_id)

    # -----------------------------------------------------------------------
    # Batch analysis
    # -----------------------------------------------------------------------

    def analyze_batch(
        self,
        track_ids: list[str],
        force: bool = False,
    ) -> Generator[dict[str, Any], None, None]:
        """
        Analyze multiple tracks sequentially, yielding progress after each.

        Yields:
            Dict with: {track_id, index, total, status, bpm, key, ...}
        """
        total = len(track_ids)
        logger.info(f"Starting batch analysis: {total} tracks (force={force})")

        analyzed = 0
        skipped = 0
        errors = 0

        for i, tid in enumerate(track_ids):
            try:
                result = self.analyze_and_save(tid, force=force)
                status = result.get("status", "error")

                if status == "ok":
                    analyzed += 1
                elif status == "skipped":
                    skipped += 1
                else:
                    errors += 1

                yield {
                    "track_id": tid,
                    "index": i + 1,
                    "total": total,
                    "analyzed": analyzed,
                    "skipped": skipped,
                    "errors": errors,
                    **result,
                }
            except Exception as e:
                errors += 1
                logger.error(f"Batch analysis error for {tid}: {e}")
                yield {
                    "track_id": tid,
                    "index": i + 1,
                    "total": total,
                    "analyzed": analyzed,
                    "skipped": skipped,
                    "errors": errors,
                    "status": "error",
                    "error": str(e),
                }

        logger.info(
            f"Batch analysis complete: {analyzed} analyzed, {skipped} skipped, {errors} errors"
        )

    def get_unanalyzed_tracks(self) -> list[str]:
        """
        Find tracks in the library that have no analysis data (BPM=0 or no ANLZ files).

        Returns:
            List of track IDs that need analysis
        """
        unanalyzed = []
        for tid, track in self.live_db.tracks.items():
            bpm = track.get("BPM", 0)
            if not bpm or bpm <= 0 or not self._has_anlz_dat(tid):
                unanalyzed.append(tid)

        logger.info(f"Found {len(unanalyzed)} unanalyzed tracks out of {len(self.live_db.tracks)}")
        return unanalyzed
