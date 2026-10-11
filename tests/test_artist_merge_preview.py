"""Artist-Hub merge detection + preview tests (T-5 — app/artist_store/merge.py).

Two things are load-bearing here and both are asserted directly:

  * **the fold only folds what a human typed differently** — case, whitespace,
    punctuation, apostrophes, ``&``/``and``. Two genuinely different artists must never
    land in one group: a false merge repoints tracks onto the wrong artist and, once the
    variant rows are gone, cannot be picked apart again.
  * **the preview writes nothing.** Every mutator on the DB facade is replaced with a
    tripwire, and the sidecar DB path is pointed at ``tmp_path`` and asserted to still
    not exist afterwards — so a preview that touched ``artists.db`` fails too.

The library is a real ``LiveRekordboxDB`` with hand-filled ``tracks`` run through the
production ``_finalize_ui_metadata``, so the artist list and the per-name track counts
come from shipped code, not from a hand-written fixture. No Rekordbox library is ever
opened.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("rbox", reason="pyrekordbox not installed on this platform")

from app.artist_store import merge, schema
from app.live_database import LiveRekordboxDB

#: Everything on the facade that changes state. ``preview``/``candidates`` may call
#: none of them. Mirrors the ``_serialised`` list in ``app/database.py`` plus the rbox
#: artist writers an apply (T-6) will use.
MUTATORS = (
    "set_mode",
    "load_library",
    "unload_library",
    "create_new_library",
    "refresh_metadata",
    "add_track",
    "delete_track",
    "rename_playlist",
    "move_playlist",
    "delete_playlist",
    "reorder_playlist_track",
    "create_folder",
    "create_smart_playlist",
    "update_smart_playlist",
    "create_playlist",
    "add_track_to_playlist",
    "remove_track_from_playlist",
    "save",
    "save_xml",
    "update_tracks_metadata",
    "update_track_metadata",
    "update_track_comment",
    "update_track_path",
    "save_track_cues",
    "save_track_beatgrid",
    "update_content",
    "update_content_artist",
    "create_artist",
    "delete_artist",
)


def _close_thread_conn() -> None:
    conn = getattr(schema._local, "conn", None)
    if conn is not None:
        conn.close()
        del schema._local.conn


@pytest.fixture(autouse=True)
def _neutral_library_config(monkeypatch):
    """Keep the developer's own settings and alias mappings out of the fixtures.

    ``_finalize_ui_metadata`` reads ``artist_view_threshold`` from the real settings
    file and ``_normalize_artist_name`` consults the real ``metadata_mappings.json`` —
    either would silently rewrite or filter away the artists these tests assert on.
    """
    import app.services as services

    monkeypatch.setattr(services.SettingsManager, "load", staticmethod(lambda: {}))
    monkeypatch.setattr(
        services.MetadataManager,
        "get_mapped_name",
        classmethod(lambda cls, category, name: name),
    )


@pytest.fixture(autouse=True)
def _sidecar_off_limits(tmp_path, monkeypatch):
    """Point ``artists.db`` at a throwaway path that is never created.

    ``init_db`` is deliberately NOT called: merge previews must not touch the sidecar
    at all, so the file's absence at the end of a test is itself an assertion.
    """
    monkeypatch.setattr(schema, "_db_path", lambda: tmp_path / "artists.db")
    monkeypatch.setattr(schema, "_initialised", False)
    _close_thread_conn()
    yield tmp_path / "artists.db"
    _close_thread_conn()


class NoWriteDB:
    """Read-only proxy: every mutator raises instead of running."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.blocked: list[str] = []

    def __getattr__(self, name: str) -> Any:
        if name in MUTATORS:

            def _tripwire(*args: Any, **kwargs: Any) -> None:
                self.blocked.append(name)
                raise AssertionError(f"preview called the mutator {name!r}")

            return _tripwire
        return getattr(self._inner, name)


def _library(*tracks: dict[str, Any]) -> LiveRekordboxDB:
    """A loaded-looking library whose artist list came from the production splitter."""
    db = LiveRekordboxDB("does-not-exist.db")
    db.tracks = {
        str(i): {"ID": str(i), "Artwork": "", "path": "", **t} for i, t in enumerate(tracks)
    }
    db._finalize_ui_metadata()
    return db


def _audio(tmp_path, name: str, size: int) -> str:
    path = tmp_path / name
    path.write_bytes(b"\0" * size)
    return str(path)


def _artist_list(*rows: tuple[str, int]) -> SimpleNamespace:
    """A library that exposes only the artist list — no track lookup, no writers."""
    return SimpleNamespace(
        artists=[
            {"id": f"art_{i}", "name": name, "track_count": count}
            for i, (name, count) in enumerate(rows)
        ]
    )


def _group_names(candidate: merge.MergeCandidate) -> set[str]:
    return set(candidate.names())


# --------------------------------------------------------------------------- fold


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Boys Noize", "boys noize"),
        ("Boys Noize", "BOYS NOIZE"),
        ("Boys Noize", "  Boys   Noize "),
        ("Mr. Oizo", "Mr Oizo"),
        ("Mr. Oizo", "Mr.Oizo"),
        ("Boys-Noize", "Boys Noize"),
        ("Boys_Noize", "Boys Noize"),
        ("Boys\u2013Noize", "Boys Noize"),
        ("Guns N' Roses", "Guns N Roses"),
        ("Guns N\u2019 Roses", "Guns N' Roses"),
        ("Simon & Garfunkel", "Simon and Garfunkel"),
        ("Simon&Garfunkel", "Simon and Garfunkel"),
    ],
)
def test_fold_key_collapses_typing_variants(left: str, right: str) -> None:
    assert merge.fold_key(left) == merge.fold_key(right)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("Objekt", "Object"),
        ("Marie Davidson", "Marie Davidsson"),
        ("Helena Hauff", "Helena Haufe"),
        ("Boys Noize", "Boy Noize"),
        ("Air", "Hair"),
    ],
)
def test_fold_key_keeps_different_artists_apart(left: str, right: str) -> None:
    assert merge.fold_key(left) != merge.fold_key(right)


def test_fold_key_is_empty_for_pure_punctuation() -> None:
    assert merge.fold_key("-") == ""
    assert merge.fold_key("  ") == ""


# --------------------------------------------------------------------------- candidates


def test_casing_variants_form_one_group() -> None:
    db = _library(
        {"Artist": "Boys Noize"},
        {"Artist": "boys noize"},
        {"Artist": "BOYS NOIZE"},
        {"Artist": "Objekt"},
    )

    groups = merge.candidates(db)

    assert len(groups) == 1
    assert _group_names(groups[0]) == {"Boys Noize", "boys noize", "BOYS NOIZE"}
    assert groups[0].total_tracks == 3


def test_punctuation_variants_form_one_group() -> None:
    db = _library(
        {"Artist": "Mr. Oizo"},
        {"Artist": "Mr Oizo"},
        {"Artist": "Mr.Oizo"},
    )

    groups = merge.candidates(db)

    assert len(groups) == 1
    assert _group_names(groups[0]) == {"Mr. Oizo", "Mr Oizo", "Mr.Oizo"}


def test_ampersand_and_word_variants_form_one_group() -> None:
    """``&`` / ``and`` folds together.

    Built from a hand-set artist list, not from ``_finalize_ui_metadata``: the library
    splitter treats ``&`` as an artist separator, so a name containing one never reaches
    the artist list through the live path. The fold still has to cover it — an explicit
    merge (and a non-splitting source) can hand us both spellings.
    """

    db = _artist_list(("Simon & Garfunkel", 4), ("Simon and Garfunkel", 2), ("Helena Hauff", 9))

    groups = merge.candidates(db)

    assert len(groups) == 1
    assert _group_names(groups[0]) == {"Simon & Garfunkel", "Simon and Garfunkel"}
    assert groups[0].total_tracks == 6


def test_different_artists_do_not_group() -> None:
    db = _library(
        {"Artist": "Objekt"},
        {"Artist": "Object"},
        {"Artist": "Marie Davidson"},
        {"Artist": "Marie Davidsson"},
        {"Artist": "Helena Hauff"},
    )

    assert merge.candidates(db) == []


def test_single_spelling_is_not_a_candidate() -> None:
    db = _library({"Artist": "Helena Hauff"}, {"Artist": "Helena Hauff"})

    assert merge.candidates(db) == []


def test_groups_are_sorted_by_total_tracks_descending() -> None:
    db = _library(
        {"Artist": "Boys Noize"},
        {"Artist": "boys noize"},
        {"Artist": "Mr. Oizo"},
        {"Artist": "Mr Oizo"},
        {"Artist": "Mr.Oizo"},
        {"Artist": "Mr Oizo"},
    )

    groups = merge.candidates(db)

    assert [g.total_tracks for g in groups] == [4, 2]
    assert groups[0].suggested_canonical == "Mr Oizo"


def test_group_id_is_stable_across_reloads() -> None:
    first = merge.candidates(_library({"Artist": "Boys Noize"}, {"Artist": "boys noize"}))
    second = merge.candidates(_library({"Artist": "boys noize"}, {"Artist": "Boys Noize"}))

    assert first[0].group_id == second[0].group_id


# --------------------------------------------------------------------------- canonical


def test_canonical_suggestion_prefers_the_most_owned_variant() -> None:
    db = _library(
        {"Artist": "boys noize"},
        {"Artist": "boys noize"},
        {"Artist": "Boys Noize"},
        {"Artist": "BOYS NOIZE"},
    )

    groups = merge.candidates(db)

    assert groups[0].suggested_canonical == "boys noize"


def test_canonical_suggestion_breaks_ties_on_spelling() -> None:
    db = _library(
        {"Artist": "boys noize"},
        {"Artist": "Boys Noize"},
        {"Artist": "BOYS NOIZE"},
    )

    groups = merge.candidates(db)

    assert groups[0].suggested_canonical == "Boys Noize"
    assert [v.name for v in groups[0].variants] == ["Boys Noize", "BOYS NOIZE", "boys noize"]


def test_canonical_suggestion_falls_back_to_alphabetical() -> None:
    counts = {"BOYS NOIZE": 2, "boys noize": 2}

    assert merge.suggest_canonical(counts) == "BOYS NOIZE"


# --------------------------------------------------------------------------- preview


@pytest.fixture
def merge_library(tmp_path):
    """3 canonical tracks, 2 lower-case (30 bytes on disk), 1 upper-case with no file."""
    return _library(
        {"Artist": "Boys Noize", "path": _audio(tmp_path, "a.aiff", 5)},
        {"Artist": "Boys Noize", "path": _audio(tmp_path, "b.aiff", 5)},
        {"Artist": "Boys Noize", "path": _audio(tmp_path, "c.aiff", 5)},
        {"Artist": "boys noize", "path": _audio(tmp_path, "d.aiff", 10)},
        {"Artist": "boys noize", "path": _audio(tmp_path, "e.aiff", 20)},
        {"Artist": "BOYS NOIZE", "path": ""},
        {"Artist": "Objekt", "path": _audio(tmp_path, "f.aiff", 7)},
    )


def test_preview_counts_match_the_fixture(merge_library) -> None:
    group = merge.candidates(merge_library)[0]

    result = merge.preview(merge_library, group.group_id, "Boys Noize")

    assert result.canonical == "Boys Noize"
    assert result.counts_exact is True
    assert result.total_tracks == 6
    assert result.tracks_to_rewrite == 3
    assert result.tracks_already_canonical == 3
    assert [v.as_dict() for v in result.absorbing] == [
        {"name": "boys noize", "tracks": 2},
        {"name": "BOYS NOIZE", "tracks": 1},
    ]
    assert result.orphans_after == 2
    assert result.files_to_retag == 2
    assert result.files_missing == 1
    assert result.compound_artist_tracks == 0


def test_preview_reports_the_usb_folders_that_would_merge(merge_library) -> None:
    group = merge.candidates(merge_library)[0]

    usb = merge.preview(merge_library, group.group_id, "Boys Noize").usb

    assert usb.canonical_folder == "Contents/Boys Noize"
    assert [f.folder for f in usb.folders_to_merge] == [
        "Contents/boys noize",
        "Contents/BOYS NOIZE",
    ]
    assert usb.bytes_local_source == 30
    assert usb.files_unmeasured == 1
    assert usb.tracks_relocated == 3
    assert usb.tracks_already_in_place == 0
    # Both variants differ from the canonical folder only by case — the exporter needs
    # the two-step temp rename there, not a plain move.
    assert usb.case_only_renames == 2


def test_preview_accepts_explicit_names_and_a_canonical_outside_the_library(
    merge_library,
) -> None:
    result = merge.preview(merge_library, ["boys noize", "BOYS NOIZE"], "Boys  Noize")

    assert result.canonical == "Boys  Noize"
    assert result.canonical_in_library is False
    assert result.tracks_to_rewrite == 3
    assert {v.name for v in result.absorbing} == {"boys noize", "BOYS NOIZE"}


def test_preview_defaults_to_the_suggested_canonical(merge_library) -> None:
    group = merge.candidates(merge_library)[0]

    assert merge.preview(merge_library, group.group_id).canonical == group.suggested_canonical


def test_preview_deduplicates_a_track_credited_to_two_variants(tmp_path) -> None:
    """One track, two spellings of the same artist in its credit — still one rewrite."""
    db = _library(
        {"Artist": "boys noize, BOYS NOIZE", "path": _audio(tmp_path, "g.aiff", 11)},
        {"Artist": "Boys Noize", "path": _audio(tmp_path, "h.aiff", 3)},
    )

    result = merge.preview(db, ["boys noize", "BOYS NOIZE", "Boys Noize"], "Boys Noize")

    assert result.tracks_to_rewrite == 1
    # The per-variant counts add up to 3 (the track is credited to two of them); the
    # exact total is the distinct set.
    assert result.total_tracks == 2
    assert sum(v.track_count for v in result.variants) == 3
    assert result.usb.bytes_local_source == 11
    assert result.compound_artist_tracks == 1
    assert result.compound_artist_names == ("boys noize, BOYS NOIZE",)


def test_preview_measure_files_off_skips_the_filesystem(merge_library, monkeypatch) -> None:
    def _boom(_path: str | None) -> int | None:
        raise AssertionError("measure_files=False still stat'd the library")

    monkeypatch.setattr(merge, "_file_size", _boom)
    group = merge.candidates(merge_library)[0]

    result = merge.preview(merge_library, group.group_id, "Boys Noize", measure_files=False)

    assert result.files_measured is False
    assert result.tracks_to_rewrite == 3
    assert result.usb.bytes_local_source == 0


def test_preview_falls_back_to_variant_counts_without_a_track_lookup() -> None:
    db = _artist_list(("Boys Noize", 3), ("boys noize", 2))

    result = merge.preview(db, ["Boys Noize", "boys noize"], "Boys Noize")

    assert result.counts_exact is False
    assert result.tracks_to_rewrite == 2
    assert result.usb.folders_to_merge == ()
    # Nothing was enumerated, so the file counts cover nothing — say so rather than
    # letting a dialog print "0 files to re-tag".
    assert result.files_measured is False


def test_preview_rejects_an_unknown_group_id(merge_library) -> None:
    with pytest.raises(KeyError):
        merge.preview(merge_library, "g_deadbeefdead")


def test_preview_rejects_an_empty_group(merge_library) -> None:
    with pytest.raises(ValueError):
        merge.preview(merge_library, [])


def test_preview_rejects_a_bare_artist_name(merge_library) -> None:
    """A string is iterable — without the guard this would group single letters."""
    with pytest.raises(ValueError):
        merge.preview(merge_library, "Boys Noize")


def test_preview_as_dict_is_json_shaped(merge_library) -> None:
    group = merge.candidates(merge_library)[0]

    payload = merge.preview(merge_library, group.group_id, "Boys Noize").as_dict()

    assert payload["canonical"] == "Boys Noize"
    assert payload["absorbing"][0] == {"name": "boys noize", "tracks": 2}
    assert payload["usb"]["folders_to_merge"][0]["target_folder"] == "Contents/Boys Noize"


# --------------------------------------------------------------------------- purity


def test_preview_writes_nothing(merge_library, _sidecar_off_limits) -> None:
    db = NoWriteDB(merge_library)

    groups = merge.candidates(db)
    result = merge.preview(db, groups[0].group_id, "Boys Noize")

    assert result.tracks_to_rewrite == 3
    assert db.blocked == []
    assert not _sidecar_off_limits.exists(), "preview touched the artists.db sidecar"


def test_preview_many_writes_nothing(merge_library, _sidecar_off_limits) -> None:
    db = NoWriteDB(merge_library)

    results = merge.preview_many(db, [g.group_id for g in merge.candidates(db)])

    assert [r.canonical for r in results] == ["Boys Noize"]
    assert db.blocked == []
    assert not _sidecar_off_limits.exists()


def test_preview_leaves_the_library_rows_untouched(merge_library) -> None:
    before = {tid: dict(t) for tid, t in merge_library.tracks.items()}
    artists_before = [dict(a) for a in merge_library.artists]

    group = merge.candidates(merge_library)[0]
    merge.preview(merge_library, group.group_id, "Boys Noize")

    assert {tid: dict(t) for tid, t in merge_library.tracks.items()} == before
    assert [dict(a) for a in merge_library.artists] == artists_before
