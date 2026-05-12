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

import hashlib
import logging
import os
import time
from collections.abc import Generator
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _compute_anlz_subdir(content_id: str) -> str:
    """
    Compute the ANLZ subdirectory path matching Rekordbox's naming convention.
    Rekordbox uses: USBANLZ/{hash_prefix}/{uuid-like}/ANLZ0000.DAT

    The hash prefix is a 3-digit hex number (000-fff), and the subfolder
    is derived from the content's UUID.
    """
    # Rekordbox uses the content's UUID for the folder name.
    # We compute a hash prefix from the content_id for the first level.
    h = hashlib.md5(content_id.encode()).hexdigest()
    prefix = h[:3]
    subfolder = h[:8] + '-' + h[8:12] + '-' + h[12:16] + '-' + h[16:20] + '-' + h[20:32]
    return f"{prefix}/{subfolder}"


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
            Dict with analysis results and write status
        """

        # 1. Validate track exists
        track = self.live_db.tracks.get(str(track_id))
        if not track:
            return {"status": "error", "error": f"Track {track_id} not found"}

        # 2. Check if already analyzed (skip unless forced)
        if not force:
            existing_bpm = track.get("BPM", 0)
            if existing_bpm and existing_bpm > 0:
                # Check if ANLZ files exist
                try:
                    paths = self.live_db.db.get_content_anlz_paths(str(track_id))
                    if paths and paths.get('DAT'):
                        dat_path = str(paths['DAT'])
                        if os.path.exists(dat_path):
                            logger.info(f"Track {track_id} already analyzed (BPM={existing_bpm}), skipping. Use force=True to re-analyze.")
                            return {"status": "skipped", "reason": "already_analyzed", "bpm": existing_bpm}
                except Exception:
                    pass  # No ANLZ paths yet — proceed with analysis

        # 3. Get audio file path
        file_path = track.get("path", "")
        if not file_path or not os.path.exists(file_path):
            return {"status": "error", "error": f"Audio file not found: {file_path}"}

        logger.info(f"Starting analysis for track {track_id}: {os.path.basename(file_path)}")
        start_time = time.time()

        # 4. Run analysis
        try:
            from .analysis_engine import run_full_analysis
            analysis = run_full_analysis(file_path)
        except Exception as e:
            logger.error(f"Analysis failed for track {track_id}: {e}")
            return {"status": "error", "error": f"Analysis failed: {e}"}

        if analysis.get("status") == "error":
            return {"status": "error", "error": analysis.get("error", "Unknown analysis error")}

        elapsed_analysis = time.time() - start_time
        logger.info(f"Analysis complete for {track_id}: BPM={analysis['bpm']}, Key={analysis['key']} ({elapsed_analysis:.1f}s)")

        # 5. Write ANLZ binary files
        anlz_paths = self._write_anlz(track_id, file_path, analysis)

        # 6. Update database
        db_updated = self._update_db(track_id, analysis)

        # 7. Update in-memory cache
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

    def _write_anlz(self, track_id: str, file_path: str, analysis: dict[str, Any]) -> dict[str, str]:
        """Write ANLZ binary files to the Rekordbox ANLZ directory."""
        try:
            from .anlz_writer import write_anlz_files

            # Determine ANLZ directory
            anlz_dir = self._resolve_anlz_dir(track_id)
            if not anlz_dir:
                logger.warning(f"Could not determine ANLZ directory for track {track_id}, creating new one")
                anlz_dir = self._create_anlz_dir(track_id)

            return write_anlz_files(
                anlz_dir=anlz_dir,
                track_path=file_path,
                analysis_result=analysis,
                filename_base="ANLZ0000",
            )
        except Exception as e:
            logger.error(f"Failed to write ANLZ files for track {track_id}: {e}")
            return {}

    def _resolve_anlz_dir(self, track_id: str) -> str | None:
        """
        Find the existing ANLZ directory for a track.
        Returns the directory path, or None if no ANLZ dir exists yet.
        """
        try:
            # rbox can tell us where the ANLZ files live
            anlz_dir = self.live_db.db.get_content_anlz_dir(str(track_id))
            if anlz_dir:
                dir_str = str(anlz_dir)
                if os.path.exists(dir_str):
                    return dir_str
                # Directory doesn't exist yet but path is known — create it
                os.makedirs(dir_str, exist_ok=True)
                return dir_str
        except Exception as e:
            logger.debug(f"get_content_anlz_dir failed for {track_id}: {e}")

        # Fallback: check known paths
        try:
            paths = self.live_db.db.get_content_anlz_paths(str(track_id))
            if paths:
                for key in ('DAT', 'EXT', '2EX'):
                    p = paths.get(key)
                    if p:
                        return str(Path(str(p)).parent)
        except Exception as e:
            logger.debug(f"get_content_anlz_paths failed for {track_id}: {e}")

        return None

    def _create_anlz_dir(self, track_id: str) -> str:
        """Create a new ANLZ directory for a track that has never been analyzed."""
        from .config import REKORDBOX_ROOT

        anlz_root = Path(REKORDBOX_ROOT) / "share" / "PIONEER" / "USBANLZ"
        subdir = _compute_anlz_subdir(str(track_id))
        anlz_dir = anlz_root / subdir
        os.makedirs(anlz_dir, exist_ok=True)
        logger.info(f"Created new ANLZ directory: {anlz_dir}")
        return str(anlz_dir)

    def _update_db(self, track_id: str, analysis: dict[str, Any]) -> bool:
        """
        Update djmdContent fields in master.db via rbox.

        Updates: bpm, key_id, analysed flag, analysis_data_path
        """
        try:
            item = self.live_db.db.get_content_by_id(str(track_id))
            if not item:
                logger.error(f"Content {track_id} not found in DB for update")
                return False

            # BPM: stored as integer (bpm × 100)
            bpm_int = int(round(analysis["bpm"] * 100))
            item.bpm = bpm_int

            # Analysed flag (Rekordbox uses this to know the track has been analyzed)
            # The 'analysed' field is a bitmask; different bits mean different analysis stages.
            # Typical fully-analyzed value observed: 4294967295 (all bits set) or simpler values.
            # We set it to indicate BPM + key + waveform are done.
            item.analysed = 4294967295  # 0xFFFFFFFF — fully analyzed

            self.live_db.db.update_content(item)
            logger.info(f"Updated djmdContent for {track_id}: bpm={bpm_int}, analysed=0xFFFFFFFF")

            # Update key via dedicated method (handles djmdKey join table)
            key_id = analysis.get("key_id", 0)
            if key_id > 0:
                key_name = analysis.get("key", "")
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
            1: 'C major', 2: 'C# major', 3: 'D major', 4: 'D# major',
            5: 'E major', 6: 'F major', 7: 'F# major', 8: 'G major',
            9: 'G# major', 10: 'A major', 11: 'A# major', 12: 'B major',
            13: 'C minor', 14: 'C# minor', 15: 'D minor', 16: 'D# minor',
            17: 'E minor', 18: 'F minor', 19: 'F# minor', 20: 'G minor',
            21: 'G# minor', 22: 'A minor', 23: 'A# minor', 24: 'B minor',
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

        logger.info(f"Batch analysis complete: {analyzed} analyzed, {skipped} skipped, {errors} errors")

    def get_unanalyzed_tracks(self) -> list[str]:
        """
        Find tracks in the library that have no analysis data (BPM=0 or no ANLZ files).

        Returns:
            List of track IDs that need analysis
        """
        unanalyzed = []
        for tid, track in self.live_db.tracks.items():
            bpm = track.get("BPM", 0)
            if not bpm or bpm <= 0:
                unanalyzed.append(tid)
                continue

            # Also check if ANLZ files exist
            try:
                paths = self.live_db.db.get_content_anlz_paths(tid)
                if not paths or not paths.get('DAT'):
                    unanalyzed.append(tid)
                    continue
                dat_path = str(paths['DAT'])
                if not os.path.exists(dat_path):
                    unanalyzed.append(tid)
            except Exception:
                unanalyzed.append(tid)

        logger.info(f"Found {len(unanalyzed)} unanalyzed tracks out of {len(self.live_db.tracks)}")
        return unanalyzed
