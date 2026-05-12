"""
LibrarySource — uniform abstraction over Live (master.db) and XML modes.

Used by USB-sync to read tracks/playlists/cues regardless of mode.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

logger = logging.getLogger(__name__)


class LibrarySource:
    """Common interface."""
    mode: str = ""

    def iter_tracks(self) -> Iterable[dict]:
        raise NotImplementedError

    def iter_playlists(self) -> Iterable[dict]:
        """yields {id, name, parent_id, type ('0'|'1'|'4'), track_ids: list}"""
        raise NotImplementedError

    def get_track(self, tid) -> dict | None:
        raise NotImplementedError

    def get_playlist_track_ids(self, pid) -> list[str]:
        raise NotImplementedError

    def get_anlz_sidecar_dir(self, track: dict) -> Path | None:
        """Returns directory containing prebuilt ANLZ files (from import-time analysis), if any."""
        path = track.get("path")
        if not path:
            return None
        import hashlib
        p = Path(path)
        sidecar_root = p.parent / ".lms_anlz"
        if not sidecar_root.exists():
            return None
        h = hashlib.sha1(str(p).encode("utf-8")).hexdigest()[:16]
        candidate = sidecar_root / h
        return candidate if candidate.exists() else None


class XmlLibrarySource(LibrarySource):
    """Reads from RekordboxXMLDB."""
    mode = "xml"

    def __init__(self, xml_db):
        self.db = xml_db

    def iter_tracks(self) -> Iterable[dict]:
        for tid, t in self.db.tracks.items():
            yield self._normalize(tid, t)

    def get_track(self, tid) -> dict | None:
        t = self.db.tracks.get(str(tid))
        return self._normalize(str(tid), t) if t else None

    def iter_playlists(self) -> Iterable[dict]:
        for p in self.db.playlists:
            pid = str(p.get("ID"))
            t_ids = [
                str(t.get("id") or t.get("TrackID"))
                for t in self.db.playlists_tracks.get(pid, [])
            ]
            yield {
                "id": pid,
                "name": p.get("Name", ""),
                "parent_id": p.get("ParentID", "ROOT"),
                "type": p.get("Type", "1"),
                "track_ids": t_ids,
                "smart_list": p.get("SmartList") if p.get("Type") == "4" else None,
            }

    def get_playlist_track_ids(self, pid) -> list[str]:
        pid = str(pid)
        return [
            str(t.get("id") or t.get("TrackID"))
            for t in self.db.playlists_tracks.get(pid, [])
        ]

    @staticmethod
    def _normalize(tid: str, t: dict) -> dict:
        return {
            "id": tid,
            "title": t.get("Title") or "",
            "artist": t.get("Artist") or "",
            "album": t.get("Album") or "",
            "genre": t.get("Genre") or "",
            "label": t.get("Label") or "",
            "key": t.get("Key") or "",
            "bpm": float(t.get("BPM") or 0),
            "path": t.get("path") or "",
            "duration_ms": int(float(t.get("TotalTime") or 0) * 1000),
            "rating": int(t.get("Rating") or 0),
            "color_id": t.get("ColorID") or "",
            "comment": t.get("Comment") or "",
            "bitrate": int(t.get("Bitrate") or 0),
            "play_count": int(t.get("PlayCount") or 0),
            "release_year": int(t.get("ReleaseYear") or 0),
            "artwork": t.get("Artwork") or "",
            "beats": t.get("beatGrid") or [],
            "position_marks": t.get("positionMarks") or [],
        }


class LiveLibrarySource(LibrarySource):
    """Reads from rbox.MasterDb (Live mode)."""
    mode = "live"

    def __init__(self, live_db):
        self.live_db = live_db

    def iter_tracks(self) -> Iterable[dict]:
        for tid, t in self.live_db.tracks.items():
            yield self._normalize(str(tid), t)

    def get_track(self, tid) -> dict | None:
        t = self.live_db.tracks.get(str(tid))
        return self._normalize(str(tid), t) if t else None

    def iter_playlists(self) -> Iterable[dict]:
        for p in self.live_db.playlists:
            pid = str(p.get("ID"))
            tracks = self.live_db.get_playlist_tracks(pid) if hasattr(self.live_db, "get_playlist_tracks") else []
            yield {
                "id": pid,
                "name": p.get("Name", ""),
                "parent_id": p.get("ParentID") or "ROOT",
                "type": p.get("Type", "1"),
                "track_ids": [str(t.get("id") or t.get("ID")) for t in tracks],
                "smart_list": p.get("SmartList") if p.get("Type") == "4" else None,
            }

    def get_playlist_track_ids(self, pid) -> list[str]:
        if hasattr(self.live_db, "get_playlist_tracks"):
            return [str(t.get("id") or t.get("ID")) for t in self.live_db.get_playlist_tracks(str(pid))]
        return []

    @staticmethod
    def _normalize(tid: str, t: dict) -> dict:
        return {
            "id": tid,
            "title": t.get("Title") or t.get("title") or "",
            "artist": t.get("Artist") or t.get("artist") or "",
            "album": t.get("Album") or t.get("album") or "",
            "genre": t.get("Genre") or t.get("genre") or "",
            "label": t.get("Label") or t.get("label") or "",
            "key": t.get("Key") or t.get("key") or "",
            "bpm": float(t.get("BPM") or t.get("bpm") or 0),
            "path": t.get("path") or t.get("folder_path") or "",
            "duration_ms": int(float(t.get("TotalTime") or t.get("duration_ms") or 0) * (1000 if (t.get("TotalTime") or 0) < 10000 else 1)),
            "rating": int(t.get("Rating") or 0),
            "color_id": t.get("ColorID") or "",
            "comment": t.get("Comment") or "",
            "bitrate": int(t.get("Bitrate") or t.get("BitRate") or 0),
            "play_count": int(t.get("PlayCount") or 0),
            "release_year": int(t.get("ReleaseYear") or 0),
            "artwork": t.get("Artwork") or "",
            "beats": t.get("beatGrid") or [],
            "position_marks": t.get("positionMarks") or [],
        }


def from_db(db_wrapper) -> LibrarySource:
    """Factory: pick correct source from DBWrapper."""
    if db_wrapper.mode == "live" and getattr(db_wrapper, "live_db", None):
        return LiveLibrarySource(db_wrapper.live_db)
    return XmlLibrarySource(db_wrapper.xml_db)
