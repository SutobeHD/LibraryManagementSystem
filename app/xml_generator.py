"""Rekordbox collection XML (DJ_PLAYLISTS) writer for the /api/rekordbox/export bridge."""

from __future__ import annotations

import re
import urllib.parse
import xml.etree.ElementTree as ET
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

# Rekordbox's own Kind strings where the extension alone is not the name.
_KIND_ALIASES = {".aif": "AIFF", ".m4a": "M4A", ".mp4": "M4A", ".alac": "M4A"}
# URI schemes of service tracks (`soundcloud:tracks:123`); same set as the USB sync's
# `_is_streaming_pseudo_path`. A drive letter is one character, so `C:/` never matches.
_STREAMING_SCHEMES = frozenset({"soundcloud", "spotify", "tidal", "beatport", "http", "https"})
_DATE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_TRACK_ID = re.compile(r"[0-9]+")
# Characters XML 1.0 cannot carry. ElementTree writes them unescaped, and Rekordbox (and
# ET.parse) then reject the whole file.
_XML_ILLEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿]")


def _text(value: Any) -> str:
    """Attribute-safe string: None -> "" (ET cannot serialise None), illegal chars dropped."""
    if value is None:
        return ""
    return _XML_ILLEGAL.sub("", str(value))


def _int(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def is_streaming_path(path: Any) -> bool:
    """True for a streaming-service URI (``soundcloud:tracks:123``): no local file exists.

    Such a path made ``location_for_path`` invent ``file://localhost/<cwd>/soundcloud:...``.
    """
    scheme, sep, _ = str(path or "").partition(":")
    return bool(sep) and scheme.lower() in _STREAMING_SCHEMES


@dataclass
class XmlPlaylist:
    """Playlist ``NODE`` (Type 1). ``tracks`` index ``tracks_data``, playlist order, repeats ok."""

    name: str
    tracks: list[int] = field(default_factory=list)


@dataclass
class XmlFolder:
    """Folder ``NODE`` (Type 0) of playlists and further folders."""

    name: str
    children: list[XmlPlaylist | XmlFolder] = field(default_factory=list)


def _playlist_node(parent: ET.Element, node: XmlPlaylist | XmlFolder, keys: dict[int, str]) -> None:
    if isinstance(node, XmlFolder):
        folder = ET.SubElement(parent, "NODE", Type="0", Name=_text(node.name))
        folder.set("Count", str(len(node.children)))
        for child in node.children:
            _playlist_node(folder, child, keys)
        return
    entries = [keys[i] for i in node.tracks if i in keys]  # streaming tracks have no key
    playlist = ET.SubElement(parent, "NODE", Name=_text(node.name), Type="1", KeyType="0")
    playlist.set("Entries", str(len(entries)))
    for key in entries:
        ET.SubElement(playlist, "TRACK", Key=key)


def kind_for_path(path: str) -> str | None:
    """Rekordbox ``Kind`` for the file's real extension ("MP3 File", "AIFF File"), or None."""
    ext = Path(str(path or "")).suffix.lower()
    if not ext:
        return None
    return f"{_KIND_ALIASES.get(ext, ext[1:].upper())} File"


def location_for_path(path: str) -> str:
    """``file://localhost/...`` URL, percent-encoded the way Rekordbox writes it.

    Same quoting as the USB XML sync (``app/usb_manager.py``): a raw space, ``#``, ``&`` or
    non-ASCII character in the path made Rekordbox miss the file.
    """
    raw = str(path or "")
    if not raw:
        return ""
    p = raw.replace("\\", "/")
    if not (re.match(r"[A-Za-z]:/", p) or p.startswith("/")):
        p = str(Path(raw).absolute()).replace("\\", "/")
    return urllib.parse.quote(f"file://localhost/{p.lstrip('/')}", safe=":/./-_~")


def date_added(stock_date: Any) -> str:
    """``YYYY-MM-DD`` from the track's ``StockDate``; today only when it has none."""
    m = _DATE.match(str(stock_date or "").strip())
    if m:
        try:
            datetime(int(m[1]), int(m[2]), int(m[3]))
            return m[0]
        except ValueError:
            pass
    return datetime.now().strftime("%Y-%m-%d")


def xml_rating(value: Any) -> int | None:
    """Rekordbox XML rating (0/51/102/153/204/255) or None when unusable.

    Live master.db and the app's UI store 0-5 stars; an XML library holds the raw value.
    0-5 is read as stars (no real Rekordbox raw rating lies in 1-5), anything up to 255
    passes through.
    """
    try:
        r = int(value)
    except (TypeError, ValueError):
        return None
    if 0 <= r <= 5:
        return r * 51
    if 5 < r <= 255:
        return r
    return None


def _source_id(data: dict) -> str | None:
    tid = str(data.get("TrackID") or data.get("ID") or data.get("id") or "").strip()
    return tid if _TRACK_ID.fullmatch(tid) else None


def _assign_track_ids(tracks_data: list) -> list[str]:
    """The source library's TrackID where it has a usable one, else a free number.

    Stable ids let a second export of the same tracks update them in Rekordbox instead of
    adding duplicates. A missing, non-numeric or repeated id gets the lowest unused number.
    """
    taken: set[str] = set()
    ids: list[str | None] = []
    for data in tracks_data:
        tid = _source_id(data)
        if tid is not None and tid not in taken:
            taken.add(tid)
            ids.append(tid)
        else:
            ids.append(None)
    out: list[str] = []
    n = 1
    for tid in ids:
        if tid is None:
            while str(n) in taken:
                n += 1
            tid = str(n)
            taken.add(tid)
        out.append(tid)
    return out


class RekordboxXML:
    @staticmethod
    def generate(
        tracks_data: list, output_path: Path, playlists: Sequence[XmlPlaylist | XmlFolder] = ()
    ) -> str:
        """Write ``tracks_data`` (info, beatGrid, cues) as DJ_PLAYLISTS XML; return its path.

        Streaming tracks (``is_streaming_path``) are left out of COLLECTION and of every
        playlist: they have no file a Location could point at. ``playlists`` go under the
        ROOT node; none = ROOT alone, so Rekordbox imports the tracks without a playlist.
        """
        local = [i for i, d in enumerate(tracks_data) if not is_streaming_path(d.get("path"))]
        keys = dict(zip(local, _assign_track_ids([tracks_data[i] for i in local]), strict=True))
        root = ET.Element("DJ_PLAYLISTS", Version="1.0.0")
        collection = ET.SubElement(root, "COLLECTION", Entries=str(len(local)))

        for i in local:
            data, track_id = tracks_data[i], keys[i]
            path = _text(data.get("path"))
            track = ET.SubElement(collection, "TRACK")
            track.set("TrackID", track_id)
            name = data.get("Title") or data.get("filename") or Path(path).stem or "Unknown"
            track.set("Name", _text(name))
            track.set("Artist", _text(data.get("Artist")))
            track.set("Album", _text(data.get("Album")))
            track.set("Genre", _text(data.get("Genre")))
            kind = kind_for_path(path)
            if kind:
                track.set("Kind", kind)
            track.set("TotalTime", str(_int(data.get("TotalTime"))))
            if path:
                track.set("Location", location_for_path(path))
            track.set("DateAdded", date_added(data.get("StockDate")))
            try:
                bpm = f"{float(data.get('BPM') or 0):.2f}"
            except (TypeError, ValueError):
                bpm = "0.00"
            track.set("AverageBpm", bpm)
            bitrate = _int(data.get("Bitrate") or data.get("BitRate"))
            if bitrate > 0:
                track.set("BitRate", str(bitrate))
            if data.get("Key"):
                track.set("Tonality", _text(data["Key"]))
            if data.get("Comment"):
                track.set("Comments", _text(data["Comment"]))
            rating = xml_rating(data.get("Rating"))
            if rating is not None:
                track.set("Rating", str(rating))

            # 1. Beatgrid: one TEMPO per beat, so the first Inizio is the first beat.
            for beat in data.get("beatGrid") or []:
                tempo = ET.SubElement(track, "TEMPO")
                tempo.set("Inizio", str(beat["time"]))
                tempo.set("Bpm", str(beat["bpm"]))
                tempo.set("Metro", beat.get("metro", "4/4"))
                tempo.set("Battito", str(beat.get("beat", 1)))

            # 2. Cues & Markers (POSITION_MARK Tags)
            # Rekordbox XML POSITION_MARK attributes:
            # Type: 0=Cue/HotCue/MemoryCue, 1=FadeIn, 2=FadeOut, 3=Load, 4=Loop
            # Num: -1=MemoryCue/Loop, 0-7=HotCue A-H
            # Copy — never mutate the caller's positionMarks list (appending the
            # DROP below would otherwise leak into the input + duplicate on re-run).
            cues = list(data.get("positionMarks") or [])

            # Add detected drop as a specific Memory Cue if available
            if "dropTime" in data:
                cues.append(
                    {"Name": "DROP", "Type": "0", "Start": str(data["dropTime"]), "Num": "-1"}
                )

            for cue in cues:
                mark = ET.SubElement(track, "POSITION_MARK")
                mark.set("Name", _text(cue.get("Name", "")))
                mark.set("Type", str(cue.get("Type", "0")))
                mark.set("Start", str(cue.get("Start", "0")))
                mark.set("Num", str(cue.get("Num", "-1")))

                # Support for Loops (Type 4)
                if str(cue.get("Type")) == "4" and "End" in cue:
                    mark.set("End", str(cue["End"]))

                # Colors (Optional in XML but supported)
                if "Red" in cue:
                    mark.set("Red", str(cue.get("Red", 0)))
                    mark.set("Green", str(cue.get("Green", 0)))
                    mark.set("Blue", str(cue.get("Blue", 0)))

        # Rekordbox wants PLAYLISTS > ROOT even when the export carries no playlist.
        top = ET.SubElement(ET.SubElement(root, "PLAYLISTS"), "NODE", Type="0", Name="ROOT")
        top.set("Count", str(len(playlists)))
        for node in playlists:
            _playlist_node(top, node, keys)

        tree = ET.ElementTree(root)
        ET.indent(tree, space="  ", level=0)
        xml_out = output_path.with_suffix(".xml")
        tree.write(xml_out, encoding="utf-8", xml_declaration=True)
        return str(xml_out)

    @staticmethod
    def generate_for_track(track_data: dict, output_path: Path):
        """Legacy wrapper for single track generation."""
        return RekordboxXML.generate([track_data], output_path)
