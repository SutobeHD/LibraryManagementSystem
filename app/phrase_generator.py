"""
phrase_generator.py — Phrase & Auto-Cue Generator

Generates phrase markers at every N-bar phrase boundary in a track and writes
them as Rekordbox MEMORY cues (unlimited, separate from the 8 hot-cue slots).
Beat positions come from the Rekordbox database (no re-analysis needed if the
track is already analysed); optional FFT energy analysis detects the first true
downbeat so the phrase grid is musically aligned.

The commit is non-destructive: only the memory-cue tags in the track's existing
ANLZ files are replaced (see anlz_cue_patch); beat grid, waveform and hot cues
are preserved.
"""

import logging
from pathlib import Path
from typing import Any

from .anlz_cue_patch import patch_memory_cues, read_beats_from_anlz

logger = logging.getLogger(__name__)

# Colours (0xRRGGBB) assigned to phrase / bar markers.
_COLOR_PHRASE_START = 0xFF8C00  # amber / orange — phrase boundary
_COLOR_BAR_START = 0x444444  # dark grey — bar marker (non-phrase)


class PhraseNotAnalysedError(RuntimeError):
    """Raised when a track has no existing ANLZ files to patch (not analysed)."""


# ─────────────────────────────────────────────────────────────────────────────
#  Beat extraction
# ─────────────────────────────────────────────────────────────────────────────


def extract_beats_from_db(track_id: int, db_path: str) -> list[float]:
    """
    Retrieve stored beat positions (in seconds) for a track.

    rbox's MasterDb exposes no beat-grid getter, so beats are read from the
    track's on-disk ANLZ PQTZ tag — the same grid Rekordbox persists and the
    same file the phrase cues are written into. `db_path` is used only to
    locate the ANLZ directory (via rbox). Returns [] when the track has no
    ANLZ / beat grid (not analysed).

    Args:
        track_id: Rekordbox integer track ID.
        db_path:  Absolute path to Rekordbox master.db (locates the ANLZ dir).

    Returns:
        Sorted list of beat timestamps in seconds. [] on any failure.
    """
    if not isinstance(track_id, int) or track_id <= 0:
        logger.warning("extract_beats_from_db: invalid track_id=%r", track_id)
        return []
    if not db_path or not isinstance(db_path, str):
        logger.warning("extract_beats_from_db: invalid db_path=%r", db_path)
        return []

    anlz_dir = resolve_anlz_dir(track_id, db_path)
    if not anlz_dir:
        logger.info("extract_beats_from_db: no ANLZ dir for track_id=%d", track_id)
        return []

    beats = read_beats_from_anlz(anlz_dir)
    logger.info("extract_beats_from_db: %d beats for track_id=%d", len(beats), track_id)
    return beats


# ─────────────────────────────────────────────────────────────────────────────
#  Downbeat detection
# ─────────────────────────────────────────────────────────────────────────────


def detect_first_downbeat(audio_path: str, beats: list[float]) -> float:
    """
    Detect the position of the first true downbeat using spectral energy analysis.

    Strategy:
      1. Load a short clip around each of the first 8 beats (50 ms windows).
      2. Compute RMS energy in the low-frequency band (bass / kick drum).
      3. The beat with the highest energy is the most likely downbeat.
      4. Return the beat's position in seconds.

    Falls back to returning beats[0] (the first analysed beat) if audio
    loading or librosa are not available.

    Args:
        audio_path: Absolute path to the audio file.
        beats:      Sorted list of beat timestamps in seconds.

    Returns:
        Timestamp in seconds of the detected downbeat.
        Returns 0.0 if beats is empty.
    """
    if not beats:
        logger.warning("detect_first_downbeat: empty beats list")
        return 0.0

    if not audio_path or not isinstance(audio_path, str):
        logger.warning("detect_first_downbeat: invalid audio_path=%r", audio_path)
        return float(beats[0])

    audio_file = Path(audio_path)
    if not audio_file.exists():
        logger.warning("detect_first_downbeat: audio file not found: %s", audio_file)
        return float(beats[0])

    logger.debug("detect_first_downbeat: analysing %s, %d beats", audio_file, len(beats))

    try:
        import librosa  # type: ignore  # soft-dependency

        # Only analyse the first 8 beats — enough to find the downbeat
        candidates = beats[:8]
        sr_target = 11025  # Low SR is sufficient for energy analysis
        window_dur = 0.05  # 50 ms window around each beat

        # Load just the section we need (up to ~8 beats + buffer)
        load_duration = min(candidates[-1] + 1.0, 30.0) if candidates else 5.0
        y, sr = librosa.load(
            str(audio_file),
            sr=sr_target,
            mono=True,
            offset=0.0,
            duration=load_duration,
        )

        best_idx = 0
        best_energy = -1.0

        for idx, beat_t in enumerate(candidates):
            start_sample = int((beat_t - window_dur / 2) * sr)
            end_sample = int((beat_t + window_dur / 2) * sr)
            start_sample = max(0, start_sample)
            end_sample = min(len(y), end_sample)

            if end_sample <= start_sample:
                continue

            window = y[start_sample:end_sample]
            # Low-pass: sum energy in the lower half of the spectrum
            fft = abs(librosa.stft(window, n_fft=64, hop_length=32))
            low_energy = float(fft[: fft.shape[0] // 2].mean())
            if low_energy > best_energy:
                best_energy = low_energy
                best_idx = idx

        result = float(beats[best_idx])
        logger.info(
            "detect_first_downbeat: downbeat at %.3fs (beat index %d, energy=%.4f)",
            result,
            best_idx,
            best_energy,
        )
        return result

    except ImportError:
        logger.warning(
            "detect_first_downbeat: librosa not available — using first beat as downbeat"
        )
        return float(beats[0])
    except Exception as exc:
        logger.error("detect_first_downbeat: analysis error — %s", exc)
        return float(beats[0])


# ─────────────────────────────────────────────────────────────────────────────
#  Cue generation
# ─────────────────────────────────────────────────────────────────────────────


def generate_phrase_cues(
    beats: list[float],
    phrase_length: int = 16,
) -> list[dict]:
    """
    Generate a list of cue point dicts at every N-bar phrase boundary.

    Starting from beat index 0 (assumed to be beat 1 of bar 1 after
    downbeat alignment), a cue is placed at every phrase_length beats
    (phrase start) and optionally at every 4 beats (bar start).

    Phrase-start cues are emitted as type "phrase_start", bar-start cues as
    type "bar_start". The caller maps phrase_start cues to memory cues at
    commit time (see commit_phrase_cues).

    Args:
        beats:         Sorted list of beat timestamps in seconds.
        phrase_length: Number of beats per phrase (8, 16, or 32).
                       Must be a positive multiple of 4.

    Returns:
        List of cue dicts:
          {
            position_ms (int): cue position in milliseconds,
            type (str):        "phrase_start" | "bar_start",
            label (str):       e.g. "P1", "B4",
            color (int):       RGB color integer,
            index (int):       sequential index within its type,
          }
        Returns [] if beats is empty or phrase_length is invalid.
    """
    if not beats:
        logger.warning("generate_phrase_cues: empty beats list")
        return []

    if not isinstance(phrase_length, int) or phrase_length <= 0 or phrase_length % 4 != 0:
        logger.warning(
            "generate_phrase_cues: invalid phrase_length=%r — must be positive multiple of 4",
            phrase_length,
        )
        return []

    beats = sorted(beats)
    cues: list[dict] = []
    phrase_idx = 0
    bar_idx = 0
    beats_per_bar = 4

    logger.debug(
        "generate_phrase_cues: %d beats, phrase_length=%d",
        len(beats),
        phrase_length,
    )

    for beat_num, t in enumerate(beats):
        position_ms = round(t * 1000)
        is_phrase = (beat_num % phrase_length) == 0
        is_bar = (beat_num % beats_per_bar) == 0

        if is_phrase:
            phrase_idx += 1
            cues.append(
                {
                    "position_ms": position_ms,
                    "type": "phrase_start",
                    "label": f"P{phrase_idx}",
                    "color": _COLOR_PHRASE_START,
                    "index": phrase_idx,
                }
            )
        elif is_bar:
            bar_idx += 1
            cues.append(
                {
                    "position_ms": position_ms,
                    "type": "bar_start",
                    "label": f"B{bar_idx}",
                    "color": _COLOR_BAR_START,
                    "index": bar_idx,
                }
            )

    logger.info(
        "generate_phrase_cues: generated %d cues (%d phrase, %d bar)",
        len(cues),
        sum(1 for c in cues if c["type"] == "phrase_start"),
        sum(1 for c in cues if c["type"] == "bar_start"),
    )
    return cues


# ─────────────────────────────────────────────────────────────────────────────
#  Memory-cue commit (non-destructive ANLZ write)
# ─────────────────────────────────────────────────────────────────────────────


def _rgb(color_int: int) -> tuple[int, int, int]:
    """Split a 0xRRGGBB integer into an (r, g, b) tuple."""
    return ((color_int >> 16) & 0xFF, (color_int >> 8) & 0xFF, color_int & 0xFF)


def phrase_cues_to_memory_dicts(
    cues: list[dict],
    include_bar_markers: bool = False,
) -> list[dict[str, Any]]:
    """
    Map generate_phrase_cues() output to anlz_writer memory-cue dicts.

    Phrase-start cues always become memory cues. Bar-start cues are included
    only when include_bar_markers is True — a full track yields hundreds of bar
    markers, so they are off by default.

    Returns dicts in anlz_writer format:
        {"type": "memory_cue", "time_ms": int, "number": 0,
         "name": str, "color_rgb": (r, g, b)}.
    """
    wanted = {"phrase_start", "bar_start"} if include_bar_markers else {"phrase_start"}
    out: list[dict[str, Any]] = []
    for cue in cues:
        if cue.get("type") not in wanted:
            continue
        pos_ms = cue.get("position_ms")
        if pos_ms is None:
            continue
        out.append(
            {
                "type": "memory_cue",
                "time_ms": int(pos_ms),
                "number": 0,
                "name": cue.get("label", ""),
                "color_rgb": _rgb(int(cue.get("color", _COLOR_PHRASE_START))),
            }
        )
    return out


def resolve_anlz_dir(track_id: int, db_path: str) -> str | None:
    """
    Find the existing ANLZ directory for a track via rbox, or None if the track
    has no ANLZ files (i.e. not analysed).

    Mirrors analysis_db_writer._resolve_anlz_dir but standalone (no live-db
    instance needed): tries get_content_anlz_dir, then derives the parent from
    explicit ANLZ file paths.
    """
    try:
        import rbox  # type: ignore
    except ImportError:
        logger.warning("resolve_anlz_dir: rbox not installed")
        return None

    try:
        master_db = rbox.MasterDb(db_path)
        anlz_dir = master_db.get_content_anlz_dir(str(track_id))
        if anlz_dir and Path(str(anlz_dir)).is_dir():
            return str(anlz_dir)

        paths = master_db.get_content_anlz_paths(str(track_id))
        if paths and hasattr(paths, "get"):
            for key in ("DAT", "EXT", "2EX"):
                p = paths.get(key)
                if p:
                    parent = Path(str(p)).parent
                    if parent.is_dir():
                        return str(parent)
    except Exception as exc:
        logger.warning("resolve_anlz_dir: failed for track_id=%s — %s", track_id, exc)
    return None


def commit_phrase_cues(
    track_id: int,
    cues: list[dict],
    db_path: str,
    *,
    include_bar_markers: bool = False,
) -> dict[str, Any]:
    """
    Write phrase markers as Rekordbox MEMORY cues into the track's existing
    ANLZ files. Non-destructive: only the memory-cue tags are replaced; beat
    grid, waveform and hot cues are preserved (see anlz_cue_patch).

    Args:
        track_id:            Rekordbox integer track ID.
        cues:                Cue dicts from generate_phrase_cues().
        db_path:             Path to Rekordbox master.db (used to locate ANLZ).
        include_bar_markers: Also write bar-start markers as memory cues.

    Returns:
        {"written": int, "anlz_dir": str, "dat": bool, "ext": bool,
         "backups": [...], "base": str}.

    Raises:
        ValueError:             Invalid arguments.
        PhraseNotAnalysedError: Track has no ANLZ files to patch.
        RuntimeError:           The ANLZ write failed.
    """
    if not isinstance(track_id, int) or track_id <= 0:
        raise ValueError(f"commit_phrase_cues: invalid track_id={track_id!r}")
    if not isinstance(cues, list):
        raise ValueError(f"commit_phrase_cues: cues must be list, got {type(cues)}")
    if not db_path or not isinstance(db_path, str):
        raise ValueError(f"commit_phrase_cues: invalid db_path={db_path!r}")

    memory_cues = phrase_cues_to_memory_dicts(cues, include_bar_markers=include_bar_markers)

    anlz_dir = resolve_anlz_dir(track_id, db_path)
    if not anlz_dir:
        raise PhraseNotAnalysedError(
            f"track_id={track_id} has no ANLZ files — analyse the track first"
        )

    try:
        result = patch_memory_cues(anlz_dir, memory_cues)
    except FileNotFoundError as exc:
        raise PhraseNotAnalysedError(str(exc)) from exc
    except Exception as exc:
        logger.error("commit_phrase_cues: ANLZ write failed for track_id=%d — %s", track_id, exc)
        raise RuntimeError(f"Failed to write memory cues: {exc}") from exc

    result["written"] = len(memory_cues)
    logger.info(
        "commit_phrase_cues: %d memory cues written for track_id=%d → %s",
        len(memory_cues),
        track_id,
        anlz_dir,
    )
    return result
