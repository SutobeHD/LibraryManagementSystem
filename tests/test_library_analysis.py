"""Tests for scripts/library_analysis.py on a synthetic atlas and a handful of tracks."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import library_analysis as la  # noqa: E402

from app.genre_atlas import GenreAtlas  # noqa: E402


def _genre(gid, name, parent, bpm, aliases=(), level=2):
    lo, t0, t1, hi = bpm
    return {
        "id": gid,
        "name": name,
        "aliases": list(aliases),
        "family": "electronic",
        "parent": parent,
        "level": level,
        "bpm": {"min": lo, "typical": [t0, t1], "max": hi},
    }


@pytest.fixture()
def atlas() -> GenreAtlas:
    return GenreAtlas(
        {
            "genres": [
                _genre("electronic", "Electronic", None, (60, 120, 140, 200), level=0),
                _genre("techno", "Techno", "electronic", (118, 128, 140, 160), level=1),
                _genre("hard-techno", "Hard Techno", "techno", (140, 148, 158, 175)),
                _genre("raw-techno", "Raw Techno", "techno", (125, 130, 137, 142)),
                _genre("hard-bounce", "Hard Bounce", "hard-techno", (140, 148, 160, 170), level=3),
            ],
            "tags": [
                {
                    "id": "tag-raw",
                    "name": "Raw",
                    "aliases": [],
                    "resolves_to": ["raw-techno", "hard-techno"],
                }
            ],
            "scenes": [
                {
                    "id": "scene-240kmh",
                    "name": "240KM/H",
                    "kind": "label",
                    "soundcloud": "soundcloud.com/240kmhk",
                    "genres": ["hard-bounce"],
                    "tags_used": [],
                }
            ],
        }
    )


def _track(tid, **kw):
    base = {
        "ID": str(tid),
        "Title": "",
        "Artist": "",
        "Genre": "",
        "Comment": "",
        "Label": "",
        "MyTag": "",
        "BPM": 0.0,
        "Rating": 0,
        "path": f"C:\\Music\\{tid}.aiff",
    }
    base.update(kw)
    return base


@pytest.fixture()
def tracks() -> list[dict]:
    return [
        _track(1, Genre="Raw", BPM=133.0, MyTag="Raw, Raw, Hypnotic", Rating=4),
        _track(2, Genre="Hard Techno", BPM=152.0),
        _track(3, Genre="HARD TECHNO", BPM=150.0, Comment="https://soundcloud.com/240kmhk/x"),
        _track(4, BPM=135.0, Comment="https://soundcloud.com/unknown-label/y"),
        _track(5, BPM=165.0, path="soundcloud:tracks:42"),
        _track(6, Genre="Loop Samples", BPM=0.0, path="C:/Music/6.mp3"),
    ]


def test_is_filled_treats_rekordbox_zero_as_empty():
    assert not la.is_filled("BPM", 0)
    assert la.is_filled("PlayCount", 0)
    assert not la.is_filled("Genre", "  ")
    assert not la.is_filled("TagIDs", [])


def test_mytags_are_deduplicated_in_order():
    assert la.mytags({"MyTag": "Melodic, Raw, Raw, BadFormat"}) == ["Melodic", "Raw", "BadFormat"]
    assert la.mytags({"MyTag": ""}) == []


def test_source_and_format_from_path():
    assert la.source_of({"path": "soundcloud:tracks:1"}) == "soundcloud"
    assert la.source_of({"path": "C:\\Music\\a.aiff"}) == "local"
    assert la.format_of({"path": "C:/Music/a.FLAC"}) == "flac"
    assert la.format_of({"path": "spotify:track:1"}) == "-"


def test_field_report_counts_fill_rate(tracks):
    rows = {r["field"]: r for r in la.field_report(tracks)}
    assert rows["BPM"]["filled"] == 5
    assert rows["Rating"]["filled"] == 1
    assert rows["BPM"]["median"] == 150.0


def test_genre_vocabulary_groups_spellings_and_flags_unresolved(tracks, atlas):
    gv = la.genre_vocabulary(tracks, atlas)
    assert gv["tracks_without_genre"] == 2
    assert {"key": "hard techno", "spellings": ["HARD TECHNO", "Hard Techno"], "tracks": 2} in gv[
        "spelling_variants"
    ]
    assert [v["value"] for v in gv["unresolved_values"]] == ["Loop Samples"]
    raw = next(v for v in gv["values"] if v["value"] == "Raw")
    assert raw["resolves_to"] == ["raw-techno", "hard-techno"]


def test_coverage_splits_metadata_tempo_and_none(tracks, atlas):
    cov, results = la.coverage(tracks, atlas)
    assert len(results) == len(tracks)
    assert cov["kinds"]["metadata"]["tracks"] == 3
    assert cov["kinds"]["bpm_only"]["tracks"] == 1  # 135 BPM sits in the techno window
    assert cov["kinds"]["none"]["tracks"] == 2  # 165 BPM falls between level-1 windows
    assert cov["evidence_sources"]["scene"] == 1
    assert dict(cov["top1_level1"])["techno"] >= 3


def test_agreement_leave_genre_out(tracks, atlas):
    ag = la.agreement(tracks, atlas)
    a = ag["A_without_genre"]
    assert a["labelled"] == 3  # Raw, Hard Techno, HARD TECHNO; Loop Samples does not resolve
    per = {v["value"]: v for v in ag["per_value"]}
    # The 240KM/H upload predicts hard-bounce, a child of the labelled hard-techno.
    assert per["HARD TECHNO"]["A"]["same_branch1_pct"] == 100.0
    # Without the uploader URL, 150 BPM is in no level-1 window: no prediction at all.
    assert per["HARD TECHNO"]["B"]["predicted"] == 0


def test_gaps_lists_unmatched_uploaders(tracks, atlas):
    _cov, results = la.coverage(tracks, atlas)
    gp = la.gaps(tracks, atlas, results, top=10)
    assert gp["unmatched_soundcloud_uploaders"] == [("soundcloud.com/unknown-label", 1)]
    assert sum(gp["no_candidate_reasons"].values()) >= 2


def test_report_renders_and_csv_has_one_row_per_track(tracks, atlas, tmp_path):
    rep = la.analyse(tracks, atlas, top=10, cache_dir=tmp_path / "no-cache")
    results = rep.pop("_results")
    md = la.render_md(rep, atlas, 10)
    assert "## 3. Atlas coverage" in md and "Loop Samples" in md
    out = tmp_path / "tracks.csv"
    la.write_csv(out, tracks, results, atlas)
    with out.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.reader(fh, delimiter=";"))
    assert len(rows) == len(tracks) + 1
    assert rows[0][:3] == ["ID", "Artist", "Title"]


def test_analysis_cache_report_counts_valid_entries(tmp_path):
    from app.analysis_cache import AnalysisCache

    audio = tmp_path / "a.aiff"
    audio.write_bytes(b"x" * 64)
    cache_dir = tmp_path / "cache"
    AnalysisCache(str(cache_dir)).put(
        str(audio), {"mood": {"mood": "Dark"}, "lufs": -9.0, "key_confidence": 0.5}
    )
    tracks = [_track(1, path=str(audio)), _track(2, path=str(tmp_path / "b.aiff"))]
    rep = la.analysis_cache_report(tracks, cache_dir)
    assert rep is not None
    assert (rep["local_tracks"], rep["with_valid_entry"]) == (2, 1)
    assert rep["mood"] == [("Dark", 1)]
    assert la.analysis_cache_report(tracks, tmp_path / "missing") is None
