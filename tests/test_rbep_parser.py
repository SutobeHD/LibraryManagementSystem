"""Tests for app/rbep_parser.py — Rekordbox Editor Project (.rbep) XML parser.

.rbep files are user-supplied project files; a corrupt one must degrade
gracefully (empty project), never crash the caller. Also locks the
real-vs-legacy layout fallbacks for filepath / edit / position / songgrid.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import rbep_parser  # noqa: E402
from app.rbep_parser import RbepProject  # noqa: E402

REAL_RBEP = """<?xml version="1.0" encoding="UTF-8"?>
<project>
  <info><app>rekordbox</app><version>6</version></info>
  <tracks>
    <track trackid="T1">
      <song id="S1" uuid="u-1">
        <title>Edited Cut</title>
        <artist>DJ Test</artist>
        <album>EP</album>
        <filepath>/music/cut.wav</filepath>
      </song>
      <edit>
        <volume><data>
          <section start="0" end="4" vol="0.5"/>
        </data></volume>
        <bpm><data>
          <section start="0" end="8" bpm="128"/>
        </data></bpm>
        <prepared>
          <hotcue><data>
            <cue index="0" name="A" position="1.5" color="red"/>
          </data></hotcue>
          <memorycue><data>
            <cue index="0" name="M" position="2.0"/>
          </data></memorycue>
        </prepared>
        <position><data>
          <section start="0" end="16" songstart="0" songend="16"/>
          <section start="16" end="32" songstart="0" songend="16"/>
        </data></position>
      </edit>
      <songgrid bpm="128.0" length="4">
        <orggrid><data>
          <beat index="0" bpm="128.0" position="0.0"/>
          <beat index="1" bpm="128.0" position="0.46875"/>
        </data></orggrid>
      </songgrid>
    </track>
  </tracks>
</project>
"""

LEGACY_RBEP = """<?xml version="1.0"?>
<project>
  <tracks>
    <track trackid="L1">
      <song id="S2">
        <title>Legacy</title>
        <data><filepath>/old/legacy.mp3</filepath></data>
        <edit/>
        <position><section start="0" end="8" songstart="0" songend="8"/></position>
      </song>
    </track>
  </tracks>
</project>
"""


def _write(tmp_path, name, body) -> str:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return str(p)


def test_parses_real_layout(tmp_path):
    proj = RbepProject(_write(tmp_path, "real.rbep", REAL_RBEP))
    assert proj.app == "rekordbox"
    assert proj.version == "6"
    assert len(proj.tracks) == 1
    t = proj.tracks[0]
    assert t["trackId"] == "T1"
    assert t["songId"] == "S1"
    assert t["title"] == "Edited Cut"
    assert t["filepath"] == "/music/cut.wav"
    # edit data parsed off the <track>-level <edit>
    assert t["edit"]["volume"][0]["vol"] == 0.5
    assert t["edit"]["bpm"][0]["bpm"] == 128.0
    assert t["edit"]["hotcues"][0]["name"] == "A"
    assert t["edit"]["memoryCues"][0]["position"] == 2.0
    # ALL position sections collected, not just the first
    assert len(t["positions"]) == 2
    assert t["editEndBeats"] == 32.0
    # songgrid
    assert t["bpm"] == 128.0
    assert t["gridLength"] == 4
    assert len(t["beatGrid"]) == 2
    assert t["beatGrid"][1]["position"] == 0.46875


def test_legacy_layout_fallbacks(tmp_path):
    proj = RbepProject(_write(tmp_path, "legacy.rbep", LEGACY_RBEP))
    assert len(proj.tracks) == 1
    t = proj.tracks[0]
    assert t["filepath"] == "/old/legacy.mp3"  # nested <data><filepath>
    assert len(t["positions"]) == 1  # legacy <position><section>
    assert t["positions"][0]["end"] == 8.0


def test_corrupt_file_degrades_gracefully(tmp_path):
    """Regression: a ParseError must not leave app/version unset (to_dict crash)."""
    proj = RbepProject(_write(tmp_path, "bad.rbep", "<project><tracks><not-closed"))
    assert proj.tracks == []
    # these attributes must exist even though parsing aborted
    assert proj.app == ""
    assert proj.version == "1"
    d = proj.to_dict()  # would AttributeError before the fix
    assert d["tracks"] == []
    assert d["app"] == ""


def test_track_without_song_is_skipped(tmp_path):
    body = "<project><tracks><track trackid='X'/></tracks></project>"
    proj = RbepProject(_write(tmp_path, "nosong.rbep", body))
    assert proj.tracks == []


def test_to_dict_shape(tmp_path):
    proj = RbepProject(_write(tmp_path, "real.rbep", REAL_RBEP))
    d = proj.to_dict()
    assert set(d) == {"name", "filepath", "app", "version", "tracks"}
    assert d["name"] == "real"


def test_list_projects_empty_for_missing_dir(tmp_path):
    assert rbep_parser.list_projects(str(tmp_path / "nope")) == []


def test_list_and_parse_project_by_name(tmp_path):
    _write(tmp_path, "real.rbep", REAL_RBEP)
    listed = rbep_parser.list_projects(str(tmp_path))
    assert [p["name"] for p in listed] == ["real"]
    parsed = rbep_parser.parse_project("real", str(tmp_path))
    assert parsed is not None
    assert parsed["tracks"][0]["title"] == "Edited Cut"
    # unknown name → None, never raises
    assert rbep_parser.parse_project("ghost", str(tmp_path)) is None
