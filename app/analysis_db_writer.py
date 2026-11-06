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
            ``audio_missing`` / ``analysis_failed`` / ``anlz_write_failed``) so
            callers can map it without parsing ``error``, which may hold an
            absolute file path.
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
        # master.db counts. Files in a dir we picked ourselves would be linked to no
        # row, while the row still claimed "analysed" — Rekordbox then shows a BPM
        # with no grid or waveform and never re-analyses the track. Recording a new
        # path means reproducing Rekordbox's share layout, which nothing here has
        # verified, so such a track is refused before any DSP runs.
        anlz_dir = self._recorded_anlz_dir(track_id)
        if anlz_dir is None:
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
            dat_exists = (Path(anlz_dir) / f"{_ANLZ_BASE}.DAT").is_file()
            if existing_bpm and existing_bpm > 0 and dat_exists:
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
        anlz_paths = self._write_anlz(track_id, file_path, analysis, anlz_dir)
        if "dat" not in anlz_paths:
            return {
                "status": "error",
                "reason": "anlz_write_failed",
                "error": f"Writing ANLZ files for track {track_id} failed",
            }

        # 7. Update database
        db_updated = self._update_db(track_id, analysis)

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
        self, track_id: str, file_path: str, analysis: dict[str, Any], anlz_dir: str
    ) -> dict[str, str]:
        """Write the ANLZ files into the track's recorded ANLZ dir; ``{}`` on failure."""
        try:
            from .anlz_writer import write_anlz_files

            # The path is recorded but Rekordbox creates the dir lazily.
            Path(anlz_dir).mkdir(parents=True, exist_ok=True)
            return write_anlz_files(
                anlz_dir=anlz_dir,
                track_path=file_path,
                analysis_result=analysis,
                filename_base=_ANLZ_BASE,
            )
        except Exception as e:
            logger.error(f"Failed to write ANLZ files for track {track_id}: {e}")
            return {}

    def _recorded_anlz_dir(self, track_id: str) -> str | None:
        """Dir of the AnalysisDataPath master.db records for the track, or None.

        Not via ``get_content_anlz_paths`` / ``get_content_anlz_dir``: both
        ``unwrap()`` on an empty AnalysisDataPath and abort the process (see
        ``app/anlz_safe.py``). A track with a tag BPM that Rekordbox never analysed
        is exactly that row, and no ``except`` can catch the abort.
        """
        from .anlz_safe import resolve_anlz_dir

        return resolve_anlz_dir(self.live_db.db, str(track_id))

    def _has_anlz_dat(self, track_id: str) -> bool:
        """True when the track's recorded ANLZ dir already holds ``ANLZ0000.DAT``."""
        anlz_dir = self._recorded_anlz_dir(track_id)
        if not anlz_dir:
            return False
        return (Path(anlz_dir) / f"{_ANLZ_BASE}.DAT").is_file()

    def _update_db(self, track_id: str, analysis: dict[str, Any]) -> bool:
        """
        Update djmdContent fields in master.db via rbox.

        Updates: bpm, key_id, analysed flag. Never ``analysis_data_path``: the
        caller only gets here for a track whose path master.db already records
        and whose ANLZ files were just written there.

        Holds ``db_lock`` from the re-read to the last write: ``update_content``
        writes the whole row, so a row read outside the lock would clobber a
        concurrent comment / rating / artist edit.
        """
        from .database import db_lock

        try:
            with db_lock():
                item = self.live_db.db.get_content_by_id(str(track_id))
                if not item:
                    logger.error(f"Content {track_id} not found in DB for update")
                    return False

                # BPM: stored as integer (bpm * 100)
                bpm_int = round(analysis["bpm"] * 100)
                item.bpm = bpm_int

                # Analysed flag (Rekordbox uses this to know the track has been analyzed)
                # The 'analysed' field is a bitmask; different bits mean different analysis
                # stages. Typical fully-analyzed value observed: 4294967295 (all bits set)
                # or simpler values. We set it to indicate BPM + key + waveform are done.
                item.analysed = 4294967295  # 0xFFFFFFFF — fully analyzed

                self.live_db.db.update_content(item)
                logger.info(
                    f"Updated djmdContent for {track_id}: bpm={bpm_int}, analysed=0xFFFFFFFF"
                )

                # Update key via dedicated method (handles djmdKey join table)
                key_id = analysis.get("key_id", 0)
                if key_id > 0:
                    full_key = self._key_id_to_name(key_id)
                    if full_key:
                        try:
                            self.live_db.db.update_content_key(str(track_id), full_key)
                            logger.info(f"Updated key for {track_id}: {full_key} (key_id={key_id})")
                        except Exception as e:
                            logger.warning(f"update_content_key failed for {track_id}: {e}")

            return True

        except Exception as e:
            logger.error(f"DB update failed for track {track_id}: {e}")
            return False

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
    def _key_id_to_name(key_id: int) -> str | None:
        """Convert Rekordbox key_id to the full key name (e.g., 'Am' or 'Cmaj')."""
        # Reverse of _REKORDBOX_KEY_ID from analysis_engine
        _ID_TO_KEY = {
            1: "C major",
            2: "C# major",
            3: "D major",
            4: "D# major",
            5: "E major",
            6: "F major",
            7: "F# major",
            8: "G major",
            9: "G# major",
            10: "A major",
            11: "A# major",
            12: "B major",
            13: "C minor",
            14: "C# minor",
            15: "D minor",
            16: "D# minor",
            17: "E minor",
            18: "F minor",
            19: "F# minor",
            20: "G minor",
            21: "G# minor",
            22: "A minor",
            23: "A# minor",
            24: "B minor",
        }
        return _ID_TO_KEY.get(key_id)

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
