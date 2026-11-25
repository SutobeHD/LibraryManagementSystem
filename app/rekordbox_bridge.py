import logging
import posixpath
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from .database import db
from .xml_generator import RekordboxXML, XmlFolder, XmlPlaylist, is_streaming_path

logger = logging.getLogger(__name__)

# Track fields an XML import can carry; the active library stores only some of them.
_IMPORT_FIELDS = frozenset(
    {
        "Title",
        "Artist",
        "Album",
        "Genre",
        "Comment",
        "Key",
        "Label",
        "Rating",
        "BPM",
        "TotalTime",
        "beatGrid",
        "positionMarks",
    }
)
_DRIVE_PATH = re.compile(r"[A-Za-z]:/")


def _path_key(path: Any) -> str:
    """Comparable library path, the same on every OS the sidecar runs on.

    A drive path (``C:\\x`` / ``C:/x``) is Windows: either separator, case-insensitive.
    ``os.path.normcase`` only does that on Windows, so a POSIX run never matched.
    """
    if not path:
        return ""
    p = str(path).replace("\\", "/")
    if _DRIVE_PATH.match(p):
        return posixpath.normpath(p).casefold()
    return posixpath.normpath(p)


def _float_or_none(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def _import_rating(raw: str | None, backend: str) -> int | None:
    """XML Rating (0, 51 ... 255) in the active library's scale: stars live, raw in XML mode."""
    try:
        value = int(raw) if raw is not None else -1
    except ValueError:
        return None
    if not 0 <= value <= 255:
        return None
    return round(value / 51) if backend == "live" else value


def _import_row(el: ET.Element, backend: str) -> dict[str, Any]:
    """One COLLECTION TRACK as a library track dict, None for an attribute the XML lacks.

    Grid and cue dicts have the shape ``RekordboxXMLDB`` parses them into. No TEMPO /
    POSITION_MARK = None, not []: an un-analysed track in the XML must not erase the
    library's grid or cues.
    """
    grid = [
        {
            "time": float(t.get("Inizio") or 0),
            "bpm": float(t.get("Bpm") or 0),
            "beat": int(t.get("Battito") or t.get("Battuta") or 1),
            "metro": t.get("Metro", "4/4"),
        }
        for t in el.findall("TEMPO")
    ]
    raw = unquote(el.get("Location", "")).removeprefix("file://localhost/")
    path = raw.replace("/", "\\") if _DRIVE_PATH.match(raw) else "/" + raw.lstrip("/")
    marks = []
    for mark in el.findall("POSITION_MARK"):
        m: dict[str, Any] = {
            "Name": mark.get("Name", ""),
            "Type": mark.get("Type", "0"),
            "Start": float(mark.get("Start") or 0),
            "Num": int(mark.get("Num") or -1),
            "Red": int(mark.get("Red") or 0),
            "Green": int(mark.get("Green") or 0),
            "Blue": int(mark.get("Blue") or 0),
        }
        if mark.get("End"):
            m["End"] = float(mark.get("End") or 0)
        marks.append(m)
    return {
        "path": path,
        "Title": el.get("Name"),
        "Artist": el.get("Artist"),
        "Album": el.get("Album"),
        "Genre": el.get("Genre"),
        "Comment": el.get("Comments"),
        "Key": el.get("Tonality"),
        "Label": el.get("Label"),
        "Rating": _import_rating(el.get("Rating"), backend),
        "BPM": _float_or_none(el.get("AverageBpm")),
        "TotalTime": _float_or_none(el.get("TotalTime")),
        "beatGrid": grid or None,
        "positionMarks": marks or None,
    }


class PlaylistNotFoundError(LookupError):
    pass


class BeatgridsLoadingError(RuntimeError):
    """The live library's beat grids are still loading; an export now would have no TEMPO."""


@dataclass(frozen=True)
class RbxExportResult:
    path: str
    exported: int  # tracks in COLLECTION
    skipped_streaming: int  # streaming tracks left out (no local file)
    playlist: str | None  # top NODE under ROOT; None = ROOT only


class _ExportTracks:
    """Each library track once, in first-seen order; playlists refer to it by index."""

    def __init__(self) -> None:
        self.data: list[dict[str, Any]] = []
        self._index: dict[str, int] = {}

    def add(self, tid: Any, fallback: dict[str, Any] | None = None) -> int | None:
        key = str(tid or "")
        if not key:
            return None
        if key not in self._index:
            track = db.get_track_details(key) or fallback
            if not track:
                return None
            self._index[key] = len(self.data)
            self.data.append(track)
        return self._index[key]


def _find_node(nodes: list[dict[str, Any]], pid: str) -> dict[str, Any] | None:
    for node in nodes:
        if str(node.get("ID")) == pid:
            return node
        found = _find_node(node.get("Children") or [], pid)
        if found is not None:
            return found
    return None


def _xml_node(
    node: dict[str, Any], tracks: _ExportTracks, name: str | None = None
) -> XmlPlaylist | XmlFolder:
    """Library playlist-tree node -> XML node; a folder (Type 0) keeps its whole subtree."""
    label = name or str(node.get("Name") or "") or "Untitled"
    children = node.get("Children") or []
    if str(node.get("Type")) == "0" or children:
        return XmlFolder(label, [_xml_node(c, tracks) for c in children])
    # The same tracks, order and smart-playlist result the app's playlist view shows.
    entries = []
    for t in db.get_playlist_tracks(str(node.get("ID"))) or []:
        idx = tracks.add(t.get("ID") or t.get("id") or t.get("TrackID"), t)
        if idx is not None:
            entries.append(idx)
    return XmlPlaylist(label, entries)


def _await_beatgrids(tracks: list[dict[str, Any]]) -> None:
    """Return once the grids these tracks will get are in memory; else BeatgridsLoadingError.

    The live library's grids arrive ~30 s after a load (background loader). An export
    in that window wrote every track without TEMPO (5041 tracks: 2.2 MB instead of
    265 MB) and reported success. The track dicts are the library's own, so the grids
    the loader adds show up in them. No wait when every local track has a grid.
    """
    if all(t.get("beatGrid") for t in tracks if not is_streaming_path(t.get("path"))):
        return
    if not db.wait_for_beatgrids():
        raise BeatgridsLoadingError(
            "Beat grids are still loading from the Rekordbox analysis files - retry in a moment."
        )


def _position_marks(cues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Live-library cues (``LiveRekordboxDB._cue_dict``) as POSITION_MARK dicts.

    Start/End in seconds; Num -1 = memory cue, 0-7 = hot cue A-H; Type 4 = loop.
    No colour: Rekordbox gives an imported hot cue its default colour.
    """
    marks: list[dict[str, Any]] = []
    for cue in cues:
        try:
            start_ms, out_ms = int(cue["InMsec"]), int(cue.get("OutMsec") or -1)
        except (KeyError, TypeError, ValueError):
            continue
        mark: dict[str, Any] = {
            "Name": str(cue.get("Comment") or ""),
            "Type": "4" if out_ms > start_ms else "0",
            "Start": f"{start_ms / 1000:.3f}",
            "Num": str(cue.get("Num", -1)),
        }
        if mark["Type"] == "4":
            mark["End"] = f"{out_ms / 1000:.3f}"
        marks.append(mark)
    return marks


def _with_cues(track: dict[str, Any]) -> dict[str, Any]:
    """The track with ``positionMarks``; a live track carries its cues as ``Cues`` instead.

    The export only read ``positionMarks``, which only the XML library fills: every
    live-library export went out without a single cue.
    """
    if track.get("positionMarks") or not track.get("Cues"):
        return track
    return {**track, "positionMarks": _position_marks(track["Cues"])}


def _write(
    tracks: _ExportTracks, nodes: list[XmlPlaylist | XmlFolder], output_path: Path
) -> RbxExportResult:
    if not tracks.data:
        raise ValueError("No tracks found for export.")
    skipped = sum(1 for t in tracks.data if is_streaming_path(t.get("path")))
    if skipped == len(tracks.data):
        raise ValueError(
            f"Nothing to export: all {skipped} tracks are streaming tracks without a local file."
        )
    _await_beatgrids(tracks.data)
    path = RekordboxXML.generate([_with_cues(t) for t in tracks.data], output_path, nodes)
    return RbxExportResult(
        path=path,
        exported=len(tracks.data) - skipped,
        skipped_streaming=skipped,
        playlist=nodes[0].name if nodes else None,
    )


class RekordboxBridge:
    @staticmethod
    def export_collection(
        track_ids: list[str], output_path: Path, playlist_name: str | None = None
    ) -> RbxExportResult:
        """Selected tracks as Rekordbox XML. ValueError when no exportable track is left.

        With ``playlist_name`` the tracks also form that playlist, in ``track_ids`` order;
        without it PLAYLISTS holds ROOT alone (the whole-library push has no playlist).
        """
        tracks = _ExportTracks()
        order = [idx for tid in track_ids if (idx := tracks.add(tid)) is not None]
        nodes: list[XmlPlaylist | XmlFolder] = (
            [XmlPlaylist(playlist_name, order)] if playlist_name else []
        )
        return _write(tracks, nodes, output_path)

    @staticmethod
    def export_playlist(
        playlist_id: str, output_path: Path, name: str | None = None
    ) -> RbxExportResult:
        """One library playlist, or a folder with its subtree, as Rekordbox XML.

        PlaylistNotFoundError for an unknown id, ValueError when no exportable track is
        left. ``name`` replaces the top node's name.
        """
        node = _find_node(db.get_playlist_tree() or [], str(playlist_id))
        if node is None:
            raise PlaylistNotFoundError(f"Playlist not found: {playlist_id}")
        tracks = _ExportTracks()
        return _write(tracks, [_xml_node(node, tracks, name)], output_path)

    @staticmethod
    def import_library(xml_path: str) -> dict[str, Any]:
        """Add or update library tracks from a Rekordbox XML COLLECTION, matched by path.

        An existing track gets only the fields the active library can store
        (``db.writable_track_fields``) and only those whose value differs; the rest are
        listed in ``not_written``. Sending every field made each update fail the
        field allowlist, and comparing raw path strings missed every track stored
        with ``/``. ``errors`` names the track per failure.
        """
        root = ET.parse(xml_path).getroot()
        collection = root.find("COLLECTION")
        if collection is None:
            raise ValueError("Invalid Rekordbox XML: No COLLECTION found.")
        backend = db.mode
        writable = db.writable_track_fields()
        by_path = {_path_key(t.get("path")): tid for tid, t in db.tracks.items() if t.get("path")}
        results: dict[str, Any] = {
            "added": 0,
            "updated": 0,
            "unchanged": 0,
            "errors": [],
            "not_written": sorted(_IMPORT_FIELDS - writable),
        }
        for track_el in collection.findall("TRACK"):
            label = track_el.get("Name") or track_el.get("Location") or "?"
            try:
                row = _import_row(track_el, backend)
                tid = by_path.get(_path_key(row["path"]))
                if tid is None:
                    new_id = db.add_track({k: v for k, v in row.items() if v is not None})
                    if new_id:
                        by_path[_path_key(row["path"])] = str(new_id)
                    results["added"] += 1
                    continue
                current = db.tracks.get(tid) or {}
                changes = {
                    k: v
                    for k, v in row.items()
                    if k in writable and v is not None and v != current.get(k)
                }
                if not changes:
                    results["unchanged"] += 1
                    continue
                db.update_tracks_metadata([tid], changes)
                results["updated"] += 1
            except Exception as e:
                logger.warning("op=rbx_import track=%s err=%s", label, e)
                results["errors"].append(f"{label}: {e}")
        db.save()
        return results
