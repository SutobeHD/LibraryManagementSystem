"""
phrase_generator.py — Phrase & Auto-Cue Generator

Generates hot cue points at every N-bar phrase boundary in a track.
Uses beat positions from the Rekordbox database (no re-analysis required
if the track is already analyzed). Falls back to FFT energy analysis to
detect the first true downbeat so the phrase grid is musically aligned.

All DB writes are non-destructive at the API level: the caller decides
whether to commit.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Maximum number of hot cues Rekordbox supports per track.
_MAX_HOT_CUES = 8

# Colors (Rekordbox color IDs) assigned to phrase/bar markers.
_COLOR_PHRASE_START = 0xFF8C00   # amber / orange — phrase boundary
_COLOR_BAR_START    = 0x444444   # dark grey — bar marker (non-phrase)


# ─────────────────────────────────────────────────────────────────────────────
#  Beat extraction
# ─────────────────────────────────────────────────────────────────────────────

def extract_beats_from_db(track_id: int, db_path: str) -> list[float]:
    """
    Retrieve stored beat positions (in seconds) from the Rekordbox master.db.

    Uses rbox to access the track's beatgrid.  Returns an empty list if the
    track has no stored beatgrid (e.g. not yet analysed).

    Args:
        track_id: Rekordbox integer track ID.
        db_path:  Absolute path to Rekordbox master.db.

    Returns:
        Sorted list of beat timestamps in seconds.
        Returns [] on any error (caller must handle gracefully).
    """
    if not isinstance(track_id, int) or track_id <= 0:
        logger.warning("extract_beats_from_db: invalid track_id=%r", track_id)
        return []
    if not db_path or not isinstance(db_path, str):
        logger.warning("extract_beats_from_db: invalid db_path=%r", db_path)
        return []

    db = Path(db_path)
    if not db.exists():
        logger.error("extract_beats_from_db: master.db not found: %s", db)
        return []

    logger.debug("extract_beats_from_db: loading beatgrid for track_id=%d", track_id)

    try:
        import rbox  # type: ignore  # soft-dependency

        master_db = rbox.MasterDb(str(db))
        # rbox returns beat_grid as a list of (position_ms, bpm) tuples
        beatgrid = master_db.get_beat_grid(track_id)
        if not beatgrid:
            logger.info(
                "extract_beats_from_db: no beatgrid for track_id=%d", track_id
            )
            return []

        # beatgrid entries: each entry is a marker for one beat.
        # We expand them into individual beat timestamps using the BPM.
        beats: list[float] = []
        entries = sorted(beatgrid, key=lambda e: e[0])

        for i, (pos_ms, bpm) in enumerate(entries):
            if bpm is None or bpm <= 0:
                logger.warning(
                    "extract_beats_from_db: invalid bpm=%s at pos=%s — skipping segment",
                    bpm, pos_ms,
                )
                continue
            next_pos_ms = entries[i + 1][0] if i + 1 < len(entries) else None
            beat_interval_s = 60.0 / float(bpm)
            t = pos_ms / 1000.0
            while True:
                beats.append(t)
                t += beat_interval_s
                if next_pos_ms is not None and (t * 1000) >= next_pos_ms:
                    break
                # Safety: don't generate beats past 3 hours
                if t > 10800.0:
                    break

        beats.sort()
        logger.info(
            "extract_beats_from_db: %d beats extracted for track_id=%d",
            len(beats), track_id,
        )
        return beats

    except ImportError:
        logger.warning("extract_beats_from_db: rbox not installed")
        return []
    except Exception as exc:
        logger.error(
            "extract_beats_from_db: unexpected error for track_id=%d — %s",
            track_id, exc,
        )
        return []


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
        sr_target = 11025   # Low SR is sufficient for energy analysis
        window_dur = 0.05   # 50 ms window around each beat

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
            end_sample   = int((beat_t + window_dur / 2) * sr)
            start_sample = max(0, start_sample)
            end_sample   = min(len(y), end_sample)

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
            result, best_idx, best_energy,
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

    The first 8 phrase-start cues are mapped as hot cue A–H.
    Bar-start cues are type "bar_start" (shown as grey markers in the UI).

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
        len(beats), phrase_length,
    )

    for beat_num, t in enumerate(beats):
        position_ms = int(round(t * 1000))
        is_phrase = (beat_num % phrase_length) == 0
        is_bar    = (beat_num % beats_per_bar) == 0

        if is_phrase:
            phrase_idx += 1
            cues.append({
                "position_ms": position_ms,
                "type": "phrase_start",
                "label": f"P{phrase_idx}",
                "color": _COLOR_PHRASE_START,
                "index": phrase_idx,
            })
        elif is_bar:
            bar_idx += 1
            cues.append({
                "position_ms": position_ms,
                "type": "bar_start",
                "label": f"B{bar_idx}",
                "color": _COLOR_BAR_START,
                "index": bar_idx,
            })

    logger.info(
        "generate_phrase_cues: generated %d cues (%d phrase, %d bar)",
        len(cues),
        sum(1 for c in cues if c["type"] == "phrase_start"),
        sum(1 for c in cues if c["type"] == "bar_start"),
    )
    return cues


# ─────────────────────────────────────────────────────────────────────────────
#  DB commit
# ─────────────────────────────────────────────────────────────────────────────

def commit_cues_to_db(
    track_id: int,
    cues: list[dict],
    db_path: str,
) -> None:
    """
    Write generated cue points into the Rekordbox master.db as hot cues.

    Only phrase_start cues up to _MAX_HOT_CUES (8) are written as hot cues
    (A–H).  All cues are also stored in the .rbep overlay system via the
    existing RbepSerializer pattern so they appear in the DAW timeline.

    The actual DB write uses rbox if available; otherwise raises RuntimeError
    so the API layer can return a meaningful 503.

    Args:
        track_id: Rekordbox integer track ID.
        cues:     List of cue dicts from generate_phrase_cues().
        db_path:  Path to Rekordbox master.db.

    Raises:
        RuntimeError: If rbox is unavailable or the DB write fails.
        ValueError:   If arguments are invalid.
    """
    if not isinstance(track_id, int) or track_id <= 0:
        raise ValueError(f"commit_cues_to_db: invalid track_id={track_id!r}")
    if not isinstance(cues, list):
        raise ValueError(f"commit_cues_to_db: cues must be list, got {type(cues)}")
    if not db_path or not isinstance(db_path, str):
        raise ValueError(f"commit_cues_to_db: invalid db_path={db_path!r}")

    db = Path(db_path)
    if not db.exists():
        raise RuntimeError(f"master.db not found: {db}")

    logger.info(
        "commit_cues_to_db: writing %d cues for track_id=%d → %s",
        len(cues), track_id, db,
    )

    # Select only phrase_start cues for hot cues (up to 8)
    hot_cue_candidates = [c for c in cues if c.get("type") == "phrase_start"]
    hot_cues = hot_cue_candidates[:_MAX_HOT_CUES]

    try:
        import rbox  # type: ignore

        master_db = rbox.MasterDb(str(db))

        # rbox hot cue structure: list of dicts with keys:
        #   index (0-7), position_ms, name, color
        rbox_cues = []
        for i, cue in enumerate(hot_cues):
            pos_ms = cue.get("position_ms")
            if pos_ms is None:
                continue
            rbox_cues.append({
                "index": i,
                "position_ms": int(pos_ms),
                "name": cue.get("label", f"P{i+1}"),
                "color": cue.get("color", _COLOR_PHRASE_START),
            })

        master_db.set_hot_cues(track_id, rbox_cues)
        logger.info(
            "commit_cues_to_db: %d hot cues written for track_id=%d",
            len(rbox_cues), track_id,
        )

    except ImportError as exc:
        raise RuntimeError(
            "rbox library not installed — cannot write to Rekordbox database"
        ) from exc
    except Exception as exc:
        logger.error(
            "commit_cues_to_db: DB write failed for track_id=%d — %s", track_id, exc
        )
        raise RuntimeError(f"Failed to write cues to database: {exc}") from exc
