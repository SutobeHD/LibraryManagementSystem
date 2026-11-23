import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from .database import db
from .xml_generator import RekordboxXML, XmlFolder, XmlPlaylist, is_streaming_path

logger = logging.getLogger(__name__)


class PlaylistNotFoundError(LookupError):
    pass


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
    path = RekordboxXML.generate(tracks.data, output_path, nodes)
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
    def import_library(xml_path: str) -> dict:
        """Imports data from a Rekordbox XML and updates the local database."""
        results: dict[str, Any] = {"added": 0, "updated": 0, "errors": []}
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()
            collection = root.find("COLLECTION")
            if collection is None:
                raise ValueError("Invalid Rekordbox XML: No COLLECTION found.")

            for track_el in collection.findall("TRACK"):
                try:
                    # Extract basic info
                    location = track_el.get("Location", "")
                    # Convert file://localhost/C:/... to C:/... Rekordbox (and our export)
                    # percent-encode the URL: an undecoded %20 never matched a library path.
                    clean_path = (
                        unquote(location).replace("file://localhost/", "").replace("/", "\\")
                    )

                    track_data: dict[str, Any] = {
                        "Title": track_el.get("Name"),
                        "Artist": track_el.get("Artist"),
                        "Album": track_el.get("Album"),
                        # `or default`, not get(name, default): a present-but-empty
                        # attr (common on un-analyzed Rekordbox tracks) returns ""
                        # which float("") would reject and drop the whole track.
                        "BPM": float(track_el.get("AverageBpm") or 120),
                        "path": clean_path,
                        "TotalTime": float(track_el.get("TotalTime") or 0),
                        "beatGrid": [],
                        "positionMarks": [],
                    }

                    # Extract Beatgrid
                    for tempo in track_el.findall("TEMPO"):
                        track_data["beatGrid"].append(
                            {
                                "time": float(tempo.get("Inizio") or 0),
                                "bpm": float(tempo.get("Bpm") or 0),
                                "beat": int(tempo.get("Battito") or tempo.get("Battuta") or 1),
                                "metro": tempo.get("Metro", "4/4"),
                            }
                        )

                    # Extract Cues
                    for mark in track_el.findall("POSITION_MARK"):
                        track_data["positionMarks"].append(
                            {
                                "Name": mark.get("Name", ""),
                                "Type": mark.get("Type", "0"),
                                "Start": mark.get("Start", "0"),
                                "Num": mark.get("Num", "-1"),
                            }
                        )

                    # Update or Add to local DB
                    # We match by path as the primary key for external sync
                    existing_id = None
                    for tid, t in db.tracks.items():
                        if t.get("path") == clean_path:
                            existing_id = tid
                            break

                    if existing_id:
                        # RekordboxDB has no update_track(); the real merge API is
                        # update_tracks_metadata (XML mode merges the dict, live
                        # mode delegates to update_track_metadata).
                        db.update_tracks_metadata([existing_id], track_data)
                        results["updated"] += 1
                    else:
                        db.add_track(track_data)
                        results["added"] += 1

                except Exception as e:
                    results["errors"].append(str(e))

            db.save()
            return results
        except Exception as e:
            logger.error(f"Import failed: {e}")
            raise
