"""Tests for app.genre_atlas: matching logic on a synthetic atlas + integrity of the snapshot."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.genre_atlas import (
    ATLAS_FILE,
    GenreAtlas,
    library_spelling,
    normalize_key,
    soundcloud_permalink,
)


def _genre(gid, name, parent, bpm, aliases=(), family="electronic", level=2):
    lo, t0, t1, hi = bpm
    return {
        "id": gid,
        "name": name,
        "aliases": list(aliases),
        "family": family,
        "parent": parent,
        "level": level,
        "bpm": {"min": lo, "typical": [t0, t1], "max": hi},
        "status": "draft",
        "definition": f"{name} definition.",
    }


@pytest.fixture()
def atlas() -> GenreAtlas:
    data = {
        "schema_version": 1,
        "source": {"repo": "genre-atlas", "commit": "test"},
        "genres": [
            _genre("techno", "Techno", "electronic", (118, 128, 140, 160), level=1),
            _genre("hard-dance", "Hard Dance", "electronic", (140, 148, 155, 165), level=1),
            _genre(
                "hard-techno", "Hard Techno", "techno", (140, 148, 158, 175), aliases=["Hardtechno"]
            ),
            _genre("hard-house", "Hard House", "hard-dance", (140, 145, 150, 155)),
            _genre("hard-trance", "Hard Trance", "hard-dance", (138, 142, 150, 155)),
            _genre("trance-techno", "Trance Techno", "techno", (135, 140, 152, 160)),
            _genre("hard-bounce", "Hard Bounce", "hard-techno", (140, 148, 160, 170)),
            _genre("raw-techno", "Raw Techno", "techno", (125, 130, 137, 142), aliases=["Raw"]),
            _genre("drum-and-bass", "Drum and Bass", "electronic", (160, 170, 176, 180), level=1),
        ],
        "tags": [
            {
                "id": "tag-hard-trance",
                "name": "Hard Trance",
                "aliases": ["DJ Daddy Trance"],
                "resolves_to": ["hard-house", "trance-techno", "hard-trance"],
                "resolution": {"hard-house": "offbeat bass under a house kick"},
                "meaning": "revival label",
            },
            {
                "id": "tag-trance",
                "name": "Trance",
                "aliases": [],
                "resolves_to": ["trance-techno", "hard-house"],
                "resolution": {},
                "meaning": "mood label",
            },
            {
                "id": "tag-bounce",
                "name": "Bounce",
                "aliases": ["Bouncy Techno"],
                "resolves_to": ["hard-bounce"],
                "resolution": {},
                "meaning": "offbeat bass",
            },
        ],
        "scenes": [
            {
                "id": "scene-240kmh",
                "name": "240KM/H",
                "kind": "label",
                "soundcloud": "soundcloud.com/240kmhk",
                "genres": ["hard-bounce", "hard-techno"],
                "tags_used": ["tag-bounce"],
            },
            {
                "id": "scene-r-label-group",
                "name": "R - Label Group",
                "kind": "label",
                "soundcloud": None,
                "genres": ["hard-techno"],
                "tags_used": [],
            },
        ],
    }
    return GenreAtlas(data)


# --- normalisation ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Drum & Bass", "drum n bass"),
        ("Drum & Bass", "DRUM-AND-BASS"),
        ("R - Label Group", "R-Label Group"),
        ("Mákina", "makina"),
        ("Techno (Peak Time / Driving)", "techno peak time driving"),
    ],
)
def test_normalize_key_collapses_variants(a, b):
    assert normalize_key(a) == normalize_key(b)


def test_normalize_key_empty():
    assert normalize_key(None) == ""
    assert normalize_key("   ") == ""


def test_soundcloud_permalink_from_comment():
    assert (
        soundcloud_permalink(None, "https://soundcloud.com/240kmhk/some-track")
        == "soundcloud.com/240kmhk"
    )
    assert soundcloud_permalink("no url here") is None


# --- suggest -----------------------------------------------------------------------------------


def _ids(result):
    return [c["id"] for c in result["candidates"]]


def test_empty_input_gives_no_candidates(atlas):
    res = atlas.suggest()
    assert res["candidates"] == []
    assert res["bpm_only"] is False


def test_tag_in_genre_field_ranks_resolution_order(atlas):
    res = atlas.suggest(genre="Hard Trance", bpm=147)
    assert _ids(res)[:2] == ["hard-house", "trance-techno"]
    assert res["matched"]["tags"][0]["id"] == "tag-hard-trance"
    top = res["candidates"][0]
    assert "offbeat bass under a house kick" in top["tests"]


def test_longer_tag_consumes_shorter_overlap(atlas):
    """'Hard Trance' must not also count as the generic 'Trance' tag."""
    res = atlas.suggest(genre="Hard Trance")
    assert {t["id"] for t in res["matched"]["tags"]} == {"tag-hard-trance"}


def test_genre_name_inside_tag_term_not_double_counted(atlas):
    res = atlas.suggest(genre="Hard Trance")
    hard_trance = next(c for c in res["candidates"] if c["id"] == "hard-trance")
    assert all(r["source"] == "tag" for r in hard_trance["reasons"])


def test_soundcloud_uploader_scene_is_strong_prior(atlas):
    res = atlas.suggest(title="Some Track", comment="https://soundcloud.com/240kmhk/x", bpm=152)
    assert _ids(res)[0] == "hard-bounce"
    assert res["matched"]["scenes"][0]["id"] == "scene-240kmh"
    assert any(r["field"] == "soundcloud" for r in res["candidates"][0]["reasons"])


def test_scene_name_matches_across_spacing_variants(atlas):
    res = atlas.suggest(label="R-Label Group")
    assert _ids(res) == ["hard-techno"]


def test_comment_tokens_count_as_user_evidence(atlas):
    res = atlas.suggest(comment="Raw", bpm=132)
    assert _ids(res) == ["raw-techno"]
    assert res["candidates"][0]["reasons"][0]["field"] == "comment"


def test_bpm_outside_window_demotes(atlas):
    inside = atlas.suggest(genre="Hard Techno", bpm=150)["candidates"][0]["score"]
    outside = atlas.suggest(genre="Hard Techno", bpm=120)["candidates"][0]["score"]
    assert outside < inside
    reasons = atlas.suggest(genre="Hard Techno", bpm=120)["candidates"][0]["reasons"]
    assert any("outside" in r["text"] for r in reasons)


def test_bpm_octave_error_is_tolerated(atlas):
    res = atlas.suggest(genre="Drum and Bass", bpm=87)
    reasons = res["candidates"][0]["reasons"]
    assert any("double tempo" in r["text"] for r in reasons)


def test_bpm_only_fallback_uses_level_one_windows(atlas):
    res = atlas.suggest(bpm=150)
    assert res["bpm_only"] is True
    assert _ids(res) == ["hard-dance"]
    assert len(res["candidates"][0]["reasons"]) == 1


def test_confidence_sums_to_one(atlas):
    res = atlas.suggest(genre="Hard Trance", bpm=147)
    assert abs(sum(c["confidence"] for c in res["candidates"]) - 1.0) < 0.01


def test_limit_is_respected(atlas):
    assert len(atlas.suggest(genre="Hard Trance", limit=1)["candidates"]) == 1


def test_unknown_resolves_to_ids_are_skipped():
    data = {
        "genres": [_genre("techno", "Techno", "electronic", (118, 128, 140, 160), level=1)],
        "tags": [
            {
                "id": "tag-x",
                "name": "Xtag",
                "aliases": [],
                "resolves_to": ["planned-only", "techno"],
            }
        ],
        "scenes": [],
    }
    res = GenreAtlas(data).suggest(title="Xtag")
    assert _ids(res) == ["techno"]


def test_missing_snapshot_degrades_to_empty(tmp_path: Path):
    atlas = GenreAtlas.load(tmp_path / "missing.json")
    assert atlas.suggest(genre="Techno", bpm=130)["candidates"] == []


def test_library_spelling_prefers_user_genre(atlas):
    cand = atlas.suggest(genre="Hardtechno")["candidates"][0]
    assert library_spelling(cand, ["House", "hard techno", "Trance"]) == "hard techno"
    assert library_spelling(cand, ["House"]) is None


def test_library_spelling_prefers_exact_atlas_spelling(atlas):
    cand = atlas.suggest(genre="Hardtechno")["candidates"][0]
    assert library_spelling(cand, ["HARD TECHNO", "Hard Techno", "HardTechno"]) == "Hard Techno"
    assert library_spelling(cand, ["HARD TECHNO", "Hardtechno"]) == "Hardtechno"


# --- shipped snapshot ------------------------------------------------------------------------


@pytest.fixture(scope="module")
def snapshot() -> dict:
    return json.loads(ATLAS_FILE.read_text(encoding="utf-8"))


def test_snapshot_is_small_enough_for_the_repo():
    assert ATLAS_FILE.stat().st_size < 500 * 1024


def test_snapshot_references_resolve(snapshot):
    genre_ids = {g["id"] for g in snapshot["genres"]}
    tag_ids = {t["id"] for t in snapshot["tags"]}
    for g in snapshot["genres"]:
        assert g["parent"] is None or g["parent"] in genre_ids
    for s in snapshot["scenes"]:
        assert set(s["tags_used"]) <= tag_ids
    # tags and scenes may point at genres that are only planned in the atlas; most must exist
    targets = [gid for t in snapshot["tags"] for gid in t["resolves_to"]]
    assert sum(gid in genre_ids for gid in targets) / len(targets) > 0.95


def test_snapshot_suggests_hard_house_for_daddy_trance():
    atlas = GenreAtlas.load()
    res = atlas.suggest(artist="Marlon Hoffstadt aka DJ Daddy Trance", genre="Hard Trance", bpm=147)
    assert res["candidates"][0]["id"] in {"hard-house", "trance-techno"}


@pytest.mark.parametrize(("bpm", "expected"), [(132, "raw-techno"), (152, "hard-techno")])
def test_snapshot_bare_raw_label_resolves_by_tempo(bpm, expected):
    """'Raw' is a tag (raw techno, hard techno, rawstyle, ...), not an alias of one genre."""
    res = GenreAtlas.load().suggest(genre="Raw", bpm=bpm)
    assert res["matched"]["tags"][0]["id"] == "tag-raw"
    assert res["candidates"][0]["id"] == expected


def test_snapshot_suggests_hard_bounce_for_240kmh_upload():
    atlas = GenreAtlas.load()
    res = atlas.suggest(comment="https://soundcloud.com/240kmhk/track", bpm=152)
    assert res["candidates"][0]["id"] == "hard-bounce"
