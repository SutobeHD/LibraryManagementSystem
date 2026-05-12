"""
playcount_sync.py — USB Play-Count Sync Engine

Compares play counts between the PC (Rekordbox master.db) and a USB drive
(Pioneer/rekordbox XML exported to USB). Detects conflicts where both sides
have been played since the last sync, and provides resolution strategies.

Sync metadata is stored at <usb_root>/PIONEER/RB_EDITOR_SYNC.json so it
survives USB unmount/remount without affecting Rekordbox's own files.
"""

import json
import logging
import xml.etree.ElementTree as ET
from pathlib import Path

logger = logging.getLogger(__name__)

# Path within the USB root where our sync metadata lives.
_SYNC_META_FILENAME = "PIONEER/RB_EDITOR_SYNC.json"


# ─────────────────────────────────────────────────────────────────────────────
#  Sync metadata persistence
# ─────────────────────────────────────────────────────────────────────────────

def load_usb_sync_meta(usb_root: str) -> dict:
    """
    Load the LibraryManagementSystem sync metadata from a USB drive.

    The metadata file stores the timestamp of the last successful sync
    and a mapping of track_id → {play_count, last_played} as seen at
    that sync point (used for three-way conflict detection).

    Args:
        usb_root: Absolute path to the root of the USB drive (e.g. "E:\\").

    Returns:
        Dict with keys:
          - last_sync_ts (float): Unix timestamp of last sync (0.0 if never).
          - tracks (dict[str, dict]): Per-track snapshot at last sync.
        Returns a safe empty default if the file is missing or corrupt.
    """
    if not usb_root or not isinstance(usb_root, str):
        logger.warning("load_usb_sync_meta: invalid usb_root=%r", usb_root)
        return {"last_sync_ts": 0.0, "tracks": {}}

    meta_path = Path(usb_root) / _SYNC_META_FILENAME
    logger.debug("load_usb_sync_meta: reading %s", meta_path)

    if not meta_path.exists():
        logger.info("load_usb_sync_meta: no meta file found at %s — first sync", meta_path)
        return {"last_sync_ts": 0.0, "tracks": {}}

    try:
        with open(meta_path, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError(f"expected dict, got {type(data)}")
        # Ensure required keys with safe defaults
        data.setdefault("last_sync_ts", 0.0)
        data.setdefault("tracks", {})
        logger.info(
            "load_usb_sync_meta: loaded meta — last_sync=%s, %d track snapshots",
            data["last_sync_ts"], len(data["tracks"]),
        )
        return data
    except (json.JSONDecodeError, ValueError, OSError) as exc:
        logger.error("load_usb_sync_meta: failed to parse %s — %s", meta_path, exc)
        return {"last_sync_ts": 0.0, "tracks": {}}


def save_usb_sync_meta(usb_root: str, meta: dict) -> None:
    """
    Persist sync metadata back to the USB drive.

    Creates the PIONEER directory if it doesn't exist.  Writes atomically
    via a temp file so a mid-write crash leaves the previous version intact.

    Args:
        usb_root: Absolute path to the USB root.
        meta: Dict in the format returned by load_usb_sync_meta.

    Raises:
        RuntimeError: If the write fails (caller should surface this).
    """
    if not usb_root or not isinstance(usb_root, str):
        raise RuntimeError(f"save_usb_sync_meta: invalid usb_root={usb_root!r}")
    if not isinstance(meta, dict):
        raise RuntimeError(f"save_usb_sync_meta: meta must be dict, got {type(meta)}")

    meta_path = Path(usb_root) / _SYNC_META_FILENAME
    logger.debug("save_usb_sync_meta: writing %s", meta_path)

    try:
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = meta_path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2, ensure_ascii=False)
        tmp_path.replace(meta_path)
        logger.info("save_usb_sync_meta: written OK — last_sync_ts=%s", meta.get("last_sync_ts"))
    except OSError as exc:
        logger.error("save_usb_sync_meta: write failed — %s", exc)
        raise RuntimeError(f"Failed to write sync metadata: {exc}") from exc


# ─────────────────────────────────────────────────────────────────────────────
#  Conflict detection
# ─────────────────────────────────────────────────────────────────────────────

def diff_playcounts(
    pc_tracks: list[dict],
    usb_tracks: list[dict],
    last_sync_ts: float,
) -> dict:
    """
    Three-way diff between PC play counts, USB play counts, and last-sync snapshot.

    A track is auto-resolved when only one side changed since last sync.
    A conflict occurs when both sides changed (both were played separately).

    Args:
        pc_tracks: List of dicts from Rekordbox master.db.
            Required keys: track_id (int|str), play_count (int), last_played (float|None).
        usb_tracks: List of dicts read from USB XML.
            Required keys: track_id (int|str), play_count (int), last_played (float|None).
        last_sync_ts: Unix timestamp of the last successful sync (0.0 = never synced).

    Returns:
        {
          "auto": [
              {"track_id", "title", "artist", "resolved_count", "resolved_last_played",
               "source": "pc"|"usb"|"equal"}
          ],
          "conflicts": [
              {"track_id", "title", "artist",
               "pc_count", "usb_count", "pc_last_played", "usb_last_played"}
          ]
        }
    """
    logger.info(
        "diff_playcounts: pc=%d tracks, usb=%d tracks, last_sync_ts=%.0f",
        len(pc_tracks), len(usb_tracks), last_sync_ts,
    )

    # Index USB tracks by track_id for O(1) lookup
    usb_by_id: dict[str, dict] = {}
    for t in usb_tracks:
        tid = str(t.get("track_id", ""))
        if tid:
            usb_by_id[tid] = t

    auto: list[dict] = []
    conflicts: list[dict] = []

    for pc in pc_tracks:
        tid = str(pc.get("track_id", ""))
        if not tid:
            logger.debug("diff_playcounts: skipping pc track with no track_id")
            continue

        pc_count = int(pc.get("play_count") or 0)
        pc_lp = float(pc.get("last_played") or 0.0)
        title = pc.get("title") or "(unknown)"
        artist = pc.get("artist") or ""

        usb = usb_by_id.get(tid)
        if usb is None:
            # Track exists on PC but not on USB — skip (not synced yet)
            logger.debug("diff_playcounts: track %s not on USB — skipping", tid)
            continue

        usb_count = int(usb.get("play_count") or 0)
        usb_lp = float(usb.get("last_played") or 0.0)

        if pc_count == usb_count:
            # Counts are equal — nothing to do
            auto.append({
                "track_id": tid,
                "title": title,
                "artist": artist,
                "resolved_count": pc_count,
                "resolved_last_played": max(pc_lp, usb_lp),
                "source": "equal",
            })
            continue

        # Determine which sides changed since last sync
        pc_changed = pc_lp > last_sync_ts if last_sync_ts > 0 else pc_count > 0
        usb_changed = usb_lp > last_sync_ts if last_sync_ts > 0 else usb_count > 0

        if pc_changed and usb_changed and pc_count != usb_count:
            # Both played since last sync — real conflict
            logger.info(
                "diff_playcounts: CONFLICT track=%s pc=%d usb=%d",
                tid, pc_count, usb_count,
            )
            conflicts.append({
                "track_id": tid,
                "title": title,
                "artist": artist,
                "pc_count": pc_count,
                "usb_count": usb_count,
                "pc_last_played": pc_lp,
                "usb_last_played": usb_lp,
            })
        elif pc_changed:
            # Only PC changed → take PC
            auto.append({
                "track_id": tid,
                "title": title,
                "artist": artist,
                "resolved_count": pc_count,
                "resolved_last_played": pc_lp,
                "source": "pc",
            })
        else:
            # Only USB changed → take USB
            auto.append({
                "track_id": tid,
                "title": title,
                "artist": artist,
                "resolved_count": usb_count,
                "resolved_last_played": usb_lp,
                "source": "usb",
            })

    logger.info(
        "diff_playcounts: %d auto-resolved, %d conflicts",
        len(auto), len(conflicts),
    )
    return {"auto": auto, "conflicts": conflicts}


# ─────────────────────────────────────────────────────────────────────────────
#  Resolution & commit
# ─────────────────────────────────────────────────────────────────────────────

def _apply_strategy(
    strategy: str,
    pc_count: int,
    usb_count: int,
    pc_lp: float,
    usb_lp: float,
) -> tuple[int, float]:
    """
    Apply a resolution strategy to produce the final (play_count, last_played).

    Strategies:
      take_max  — keep the larger count, latest last_played
      take_pc   — trust the PC record unconditionally
      take_usb  — trust the USB record unconditionally
      sum       — add both sides (useful when device was detached for a long time)

    Returns:
        (final_play_count, final_last_played)
    """
    if strategy == "take_pc":
        return pc_count, pc_lp
    if strategy == "take_usb":
        return usb_count, usb_lp
    if strategy == "sum":
        return pc_count + usb_count, max(pc_lp, usb_lp)
    # default: take_max
    if pc_count >= usb_count:
        return pc_count, max(pc_lp, usb_lp)
    return usb_count, max(pc_lp, usb_lp)


def resolve_playcounts(
    resolutions: list[dict],
    pc_db_path: str,
    usb_xml_path: str,
) -> dict:
    """
    Commit resolved play counts to both the PC Rekordbox DB and the USB XML.

    Each resolution dict must contain:
      - track_id (str|int)
      - strategy: "take_max" | "take_pc" | "take_usb" | "sum"
      - pc_count (int)
      - usb_count (int)
      - pc_last_played (float)
      - usb_last_played (float)

    The PC DB update uses rbox if available (best-effort — logs errors but
    doesn't raise so the USB XML can still be updated).  The USB XML is
    patched in-place and written back atomically.

    Args:
        resolutions: List of resolution dicts (see above).
        pc_db_path: Path to Rekordbox master.db.
        usb_xml_path: Path to the exported Rekordbox XML on the USB drive.

    Returns:
        {"committed": int, "errors": list[str]}
    """
    logger.info(
        "resolve_playcounts: %d resolutions, db=%s, xml=%s",
        len(resolutions), pc_db_path, usb_xml_path,
    )

    if not isinstance(resolutions, list):
        logger.error("resolve_playcounts: resolutions must be list, got %s", type(resolutions))
        return {"committed": 0, "errors": ["resolutions must be a list"]}

    errors: list[str] = []
    committed = 0

    # Build a lookup from track_id → (final_count, final_lp)
    finals: dict[str, tuple[int, float]] = {}
    for r in resolutions:
        if not isinstance(r, dict):
            errors.append(f"invalid resolution item (not a dict): {r!r}")
            continue
        tid = str(r.get("track_id", ""))
        if not tid:
            errors.append("resolution missing track_id")
            continue
        strategy = r.get("strategy", "take_max")
        pc_c = int(r.get("pc_count") or 0)
        usb_c = int(r.get("usb_count") or 0)
        pc_lp = float(r.get("pc_last_played") or 0.0)
        usb_lp = float(r.get("usb_last_played") or 0.0)
        final_count, final_lp = _apply_strategy(strategy, pc_c, usb_c, pc_lp, usb_lp)
        finals[tid] = (final_count, final_lp)
        logger.debug(
            "resolve_playcounts: track=%s strategy=%s → count=%d lp=%.0f",
            tid, strategy, final_count, final_lp,
        )

    # ── 1. Update PC database via rbox ─────────────────────────────────────
    try:
        import rbox  # type: ignore  # soft-dependency: rbox wheel

        db_path = Path(pc_db_path)
        if not db_path.exists():
            raise FileNotFoundError(f"master.db not found: {db_path}")

        master_db = rbox.MasterDb(str(db_path))
        for tid, (count, lp) in finals.items():
            try:
                # rbox integer track ids
                int_tid = int(tid)
                # rbox 0.1.x API: set_play_count(track_id, count)
                # last_played update may not be available in all versions —
                # we attempt it and fall back gracefully.
                master_db.set_play_count(int_tid, count)
                try:
                    master_db.set_last_played(int_tid, int(lp))
                except AttributeError:
                    logger.warning(
                        "resolve_playcounts: rbox.set_last_played not available for track=%s", tid
                    )
                committed += 1
                logger.info("resolve_playcounts: PC updated track=%s count=%d", tid, count)
            except Exception as exc:
                msg = f"PC DB update failed for track {tid}: {exc}"
                logger.error("resolve_playcounts: %s", msg)
                errors.append(msg)

    except ImportError:
        logger.warning(
            "resolve_playcounts: rbox not installed — PC DB will not be updated"
        )
        errors.append("rbox library not installed; PC database not updated")
    except FileNotFoundError as exc:
        logger.error("resolve_playcounts: %s", exc)
        errors.append(str(exc))
    except Exception as exc:
        logger.error("resolve_playcounts: unexpected PC DB error — %s", exc)
        errors.append(f"PC DB error: {exc}")

    # ── 2. Patch USB XML ────────────────────────────────────────────────────
    usb_path = Path(usb_xml_path)
    if not usb_path.exists():
        msg = f"USB XML not found: {usb_path}"
        logger.error("resolve_playcounts: %s", msg)
        errors.append(msg)
        return {"committed": committed, "errors": errors}

    try:
        tree = ET.parse(str(usb_path))
        root = tree.getroot()

        # Rekordbox XML TRACK elements have attribute TrackID
        tracks_elem = root.find(".//COLLECTION")
        if tracks_elem is None:
            raise ValueError("No COLLECTION element found in USB XML")

        updated_in_xml = 0
        for track_elem in tracks_elem.findall("TRACK"):
            tid = track_elem.get("TrackID", "")
            if tid in finals:
                final_count, final_lp = finals[tid]
                track_elem.set("PlayCount", str(final_count))
                # Rekordbox stores date as YYYY-MM-DD in DateAdded; last_played
                # is not a standard field but we store it as a custom attribute.
                if final_lp > 0:
                    from datetime import datetime, timezone
                    dt = datetime.fromtimestamp(final_lp, tz=timezone.utc)
                    track_elem.set("LastPlayed", dt.strftime("%Y-%m-%d"))
                updated_in_xml += 1

        # Atomic write via temp file
        tmp_xml = usb_path.with_suffix(".tmp")
        tree.write(str(tmp_xml), encoding="utf-8", xml_declaration=True)
        tmp_xml.replace(usb_path)
        logger.info(
            "resolve_playcounts: USB XML updated — %d tracks patched", updated_in_xml
        )

    except (ET.ParseError, ValueError, OSError) as exc:
        msg = f"USB XML update failed: {exc}"
        logger.error("resolve_playcounts: %s", msg)
        errors.append(msg)

    return {"committed": committed, "errors": errors}


# ─────────────────────────────────────────────────────────────────────────────
#  USB XML reader (helper used by API layer)
# ─────────────────────────────────────────────────────────────────────────────

def read_usb_xml_playcounts(usb_xml_path: str) -> list[dict]:
    """
    Parse a Rekordbox-format XML file on the USB drive and return play-count data.

    Args:
        usb_xml_path: Path to the Rekordbox XML (e.g. <usb>/PIONEER/rekordbox/export.xml).

    Returns:
        List of dicts: [{track_id, title, artist, play_count, last_played}]
        Returns empty list on any parse error.
    """
    path = Path(usb_xml_path)
    logger.debug("read_usb_xml_playcounts: parsing %s", path)

    if not path.exists():
        logger.warning("read_usb_xml_playcounts: file not found: %s", path)
        return []

    try:
        tree = ET.parse(str(path))
        root = tree.getroot()
        collection = root.find(".//COLLECTION")
        if collection is None:
            logger.warning("read_usb_xml_playcounts: no COLLECTION in %s", path)
            return []

        tracks = []
        for elem in collection.findall("TRACK"):
            tid = elem.get("TrackID", "")
            if not tid:
                continue
            play_count_raw = elem.get("PlayCount", "0")
            try:
                play_count = int(play_count_raw)
            except ValueError:
                play_count = 0

            # last_played: try our custom attribute first, then DateAdded
            lp_str = elem.get("LastPlayed") or elem.get("DateAdded") or ""
            last_played = 0.0
            if lp_str:
                try:
                    from datetime import datetime, timezone
                    dt = datetime.strptime(lp_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                    last_played = dt.timestamp()
                except ValueError:
                    pass

            tracks.append({
                "track_id": tid,
                "title": elem.get("Name", ""),
                "artist": elem.get("Artist", ""),
                "play_count": play_count,
                "last_played": last_played,
            })

        logger.info("read_usb_xml_playcounts: parsed %d tracks from %s", len(tracks), path)
        return tracks

    except (ET.ParseError, OSError) as exc:
        logger.error("read_usb_xml_playcounts: parse error — %s", exc)
        return []
