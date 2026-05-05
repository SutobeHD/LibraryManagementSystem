"""
RBEP Parser — Parses Rekordbox Editor Project (.rbep) files.
These are XML files created by Rekordbox's Edit mode containing non-destructive
edits: volume envelopes, BPM maps, hot cues, memory cues, active censors,
and beat grid data.
"""

import os
import logging
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Default project directory — user's local .rbep files
DEFAULT_PRJ_DIR = Path(__file__).parent.parent / "archive" / "data" / "prj"


class RbepProject:
    """Represents a parsed .rbep project file."""

    def __init__(self, filepath: str):
        self.filepath = Path(filepath)
        self.name = self.filepath.stem
        self.tracks = []
        self._parse()

    def _parse(self):
        """Parse the .rbep XML file into structured data."""
        try:
            tree = ET.parse(str(self.filepath))
            root = tree.getroot()

            # Parse info
            info = root.find("info")
            self.app = info.findtext("app", "") if info is not None else ""
            self.version = info.findtext("version", "1") if info is not None else "1"

            # Parse tracks
            tracks_el = root.find("tracks")
            if tracks_el is not None:
                for track_el in tracks_el.findall("track"):
                    track = self._parse_track(track_el)
                    if track:
                        self.tracks.append(track)

        except ET.ParseError as e:
            logger.error(f"Failed to parse RBEP file {self.filepath}: {e}")
        except Exception as e:
            logger.error(f"Error reading RBEP file {self.filepath}: {e}")

    def _parse_track(self, track_el) -> Optional[Dict]:
        """Parse a single <track> element."""
        track_id = track_el.get("trackid", "")
        song_el = track_el.find("song")
        if song_el is None:
            return None

        track = {
            "trackId": track_id,
            "songId": song_el.get("id", ""),
            "uuid": song_el.get("uuid", ""),
            "title": song_el.findtext("title", ""),
            "artist": song_el.findtext("artist", ""),
            "album": song_el.findtext("album", ""),
            "filepath": "",
            "edit": None,
            "beatGrid": [],
        }

        # Parse filepath — in real Rekordbox .rbep files, <filepath> sits directly
        # under <song> (no intermediate <data> wrapper). Fall back to the legacy
        # nested layout for backwards compatibility with older fixture files.
        fp_el = song_el.find("filepath")
        if fp_el is None:
            data_el = song_el.find("data")
            if data_el is not None:
                fp_el = data_el.find("filepath")
        if fp_el is not None and fp_el.text:
            track["filepath"] = fp_el.text.strip()

        # Parse edit data — <edit> is a direct child of <track> in real .rbep files.
        # The legacy/test layout placed it under <song>; check both for compatibility.
        edit_el = track_el.find("edit") or song_el.find("edit")
        if edit_el is not None:
            track["edit"] = self._parse_edit(edit_el)

        # Parse position sections — under <edit><position><data><section .../> in real
        # .rbep files. These describe the edited timeline (start/end in beats vs.
        # songstart/songend in source-song beats). Collect ALL sections, not just one.
        position_sections: list[dict] = []
        if edit_el is not None:
            pos_el = edit_el.find("position")
            if pos_el is not None:
                data_el = pos_el.find("data")
                if data_el is not None:
                    for sec in data_el.findall("section"):
                        try:
                            position_sections.append({
                                "start": float(sec.get("start", 0) or 0),
                                "end": float(sec.get("end", 0) or 0),
                                "songStart": float(sec.get("songstart", 0) or 0),
                                "songEnd": float(sec.get("songend", 0) or 0),
                            })
                        except (TypeError, ValueError) as exc:
                            logger.warning(
                                "rbep: bad position section attrs %r: %s",
                                sec.attrib, exc,
                            )
        # Legacy fallback: <position> directly under <song> with a single <section>
        if not position_sections:
            legacy_pos = song_el.find("position")
            if legacy_pos is not None:
                section = legacy_pos.find("section") or legacy_pos.find("data/section")
                if section is not None:
                    try:
                        position_sections.append({
                            "start": float(section.get("start", 0) or 0),
                            "end": float(section.get("end", 0) or 0),
                            "songStart": float(section.get("songstart", 0) or 0),
                            "songEnd": float(section.get("songend", 0) or 0),
                        })
                    except (TypeError, ValueError) as exc:
                        logger.warning("rbep: bad legacy position section: %s", exc)
        track["positions"] = position_sections
        # Convenience: total edited timeline end (in beats — convert to seconds via songgrid BPM)
        if position_sections:
            track["editEndBeats"] = max(s["end"] for s in position_sections)

        # Parse beat grid
        songgrid_el = track_el.find("songgrid")
        if songgrid_el is not None:
            track["beatGrid"] = self._parse_songgrid(songgrid_el)
            track["bpm"] = float(songgrid_el.get("bpm", 0))
            track["gridLength"] = int(songgrid_el.get("length", 0))

        return track

    def _parse_edit(self, edit_el) -> Dict:
        """Parse <edit> element containing volume, BPM, hotcue, memorycue, activecensor data."""
        edit = {
            "volume": [],
            "bpm": [],
            "hotcues": [],
            "memoryCues": [],
            "activeCensors": [],
        }

        # Volume envelope
        vol_el = edit_el.find("volume")
        if vol_el is not None:
            data_el = vol_el.find("data")
            if data_el is not None:
                for sec in data_el.findall("section"):
                    edit["volume"].append({
                        "start": float(sec.get("start", 0)),
                        "end": float(sec.get("end", 0)),
                        "vol": float(sec.get("vol", 1.0)),
                    })

        # BPM map
        bpm_el = edit_el.find("bpm")
        if bpm_el is not None:
            data_el = bpm_el.find("data")
            if data_el is not None:
                for sec in data_el.findall("section"):
                    edit["bpm"].append({
                        "start": float(sec.get("start", 0)),
                        "end": float(sec.get("end", 0)),
                        "bpm": float(sec.get("bpm", 0)),
                    })

        # Hot cues
        hc_el = edit_el.find("prepared/hotcue")
        if hc_el is not None:
            data_el = hc_el.find("data")
            if data_el is not None:
                for cue in data_el.findall("cue"):
                    edit["hotcues"].append({
                        "index": int(cue.get("index", 0)),
                        "name": cue.get("name", ""),
                        "position": float(cue.get("position", 0)),
                        "color": cue.get("color", ""),
                    })

        # Memory cues
        mc_el = edit_el.find("prepared/memorycue")
        if mc_el is not None:
            data_el = mc_el.find("data")
            if data_el is not None:
                for cue in data_el.findall("cue"):
                    edit["memoryCues"].append({
                        "index": int(cue.get("index", 0)),
                        "name": cue.get("name", ""),
                        "position": float(cue.get("position", 0)),
                    })

        # Active censors
        ac_el = edit_el.find("prepared/activecensor")
        if ac_el is not None:
            data_el = ac_el.find("data")
            if data_el is not None:
                for sec in data_el.findall("section"):
                    edit["activeCensors"].append({
                        "start": float(sec.get("start", 0)),
                        "end": float(sec.get("end", 0)),
                    })

        return edit

    def _parse_songgrid(self, songgrid_el) -> List[Dict]:
        """Parse <songgrid> element containing beat positions."""
        beats = []
        orggrid = songgrid_el.find("orggrid")
        if orggrid is not None:
            data_el = orggrid.find("data")
            if data_el is not None:
                for beat in data_el.findall("beat"):
                    beats.append({
                        "index": int(beat.get("index", 0)),
                        "bpm": float(beat.get("bpm", 0)),
                        "position": float(beat.get("position", 0)),
                    })
        return beats

    def to_dict(self) -> Dict:
        """Convert the project to a JSON-serializable dict."""
        return {
            "name": self.name,
            "filepath": str(self.filepath),
            "app": self.app,
            "version": self.version,
            "tracks": self.tracks,
        }


def list_projects(prj_dir: str = None) -> List[Dict]:
    """List all available .rbep project files."""
    directory = Path(prj_dir) if prj_dir else DEFAULT_PRJ_DIR
    if not directory.exists():
        return []

    projects = []
    for f in sorted(directory.glob("*.rbep")):
        try:
            stat = f.stat()
            projects.append({
                "name": f.stem,
                "filename": f.name,
                "size": stat.st_size,
                "modified": stat.st_mtime,
            })
        except Exception:
            pass
    return projects


def parse_project(name: str, prj_dir: str = None) -> Optional[Dict]:
    """Parse a specific .rbep project file by name."""
    directory = Path(prj_dir) if prj_dir else DEFAULT_PRJ_DIR
    filepath = directory / f"{name}.rbep"
    if not filepath.exists():
        # Try with the name as-is (might already have extension)
        filepath = directory / name
        if not filepath.exists():
            return None

    project = RbepProject(str(filepath))
    return project.to_dict()
