"""Local attribution tests (T-24 — app/artist_store/attribution.py).

Owner refinement 2026-09-26: an artist's local tracks are no longer only what the
Artist string names. Pins the three layers — Artist field (the old set, unchanged),
remix / feature credits, manual assign / exclude — and that the Rekordbox projection
reads exactly the same answer as the artist page.

Same fixture shape as ``test_artist_store_registry.py``: a ``LiveRekordboxDB`` against a
path that does not exist, ``.tracks`` filled by hand, the real ``_finalize_ui_metadata``
and the real splitter. The store is a throwaway SQLite file in ``tmp_path``.
"""

from __future__ import annotations

import sqlite3

import pytest

pytest.importorskip("rbox", reason="pyrekordbox not installed on this platform")

from app.artist_store import attribution, projection, schema
from app.live_database import LiveRekordboxDB

BOYS = "Boys Noize"


def _close_thread_conn() -> None:
    conn = getattr(schema._local, "conn", None)
    if conn is not None:
        conn.close()
        del schema._local.conn


@pytest.fixture(autouse=True)
def _neutral_library_config(monkeypatch):
    import app.services as services

    monkeypatch.setattr(services.SettingsManager, "load", staticmethod(lambda: {}))
    monkeypatch.setattr(
        services.MetadataManager,
        "get_mapped_name",
        classmethod(lambda cls, category, name: name),
    )


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(schema, "_db_path", lambda: tmp_path / "artists.db")
    monkeypatch.setattr(schema, "_initialised", False)
    _close_thread_conn()
    schema.init_db()
    yield schema
    _close_thread_conn()


def _library(*rows: dict) -> LiveRekordboxDB:
    """``rows`` are partial track dicts; ids are assigned in order, starting at 1."""
    db = LiveRekordboxDB("does-not-exist.db")
    db.tracks = {}
    for i, row in enumerate(rows, start=1):
        db.tracks[str(i)] = {"ID": str(i), "Title": "", "Artist": "", "Remixer": "", **row}
    db._finalize_ui_metadata()
    return db


def _cid(name: str = BOYS) -> str:
    return schema.collection_id_for(name)


def _stored(name: str = BOYS) -> str:
    """A collection the user saved. An artist who only ever appears as a remixer has no
    library spelling, so only a stored row can carry the names to look for."""
    return schema.create_collection(name)


def _roles(page: dict) -> dict[str, tuple[str, str, str]]:
    return {
        t["ID"]: (
            t["artist_role"]["role"],
            t["artist_role"]["confidence"],
            t["artist_role"]["source"],
        )
        for t in page["tracks"]
    }


# --------------------------------------------------------------------------- artist field


def test_artist_field_set_is_the_registry_grouping_across_spellings() -> None:
    db = _library(
        {"Title": "Overdrive", "Artist": "Boys Noize"},
        {"Title": "Rocket Boy", "Artist": "BOYS NOIZE"},
        {"Title": "Unrelated", "Artist": "Helena Hauff"},
    )

    page = attribution.local_tracks(db, _cid())

    assert page is not None
    assert _roles(page) == {
        "1": ("primary", "high", "artist_field"),
        "2": ("primary", "high", "artist_field"),
    }
    assert sorted(page["library_names"]) == ["BOYS NOIZE", "Boys Noize"]
    assert page["stored"] is False
    assert page["counts"]["total"] == 2


def test_featured_only_in_the_artist_field_is_featured() -> None:
    db = _library({"Title": "Bangarang", "Artist": "Skrillex feat. Boys Noize"})

    assert _roles(attribution.local_tracks(db, _cid())) == {
        "1": ("featured", "high", "artist_field")
    }


def test_someone_elses_remix_of_their_track_is_remixed_by_other() -> None:
    db = _library({"Title": "Overdrive (Erol Alkan Remix)", "Artist": "Boys Noize"})

    page = attribution.local_tracks(db, _cid())

    assert _roles(page) == {"1": ("remixed_by_other", "high", "artist_field")}
    assert "Erol Alkan" in page["tracks"][0]["artist_role"]["detail"]


def test_their_remix_with_the_original_act_in_the_artist_field_is_remixer() -> None:
    db = _library({"Title": "Sirens (Boys Noize Remix)", "Artist": "Charli XCX, Boys Noize"})

    page = attribution.local_tracks(db, _cid())

    assert _roles(page) == {"1": ("remixer", "high", "artist_field")}
    assert "Charli XCX" in page["tracks"][0]["artist_role"]["detail"]


def test_their_own_remix_of_their_own_track_stays_primary() -> None:
    db = _library({"Title": "Overdrive (Boys Noize VIP Remix)", "Artist": "Boys Noize"})

    assert _roles(attribution.local_tracks(db, _cid())) == {
        "1": ("primary", "high", "artist_field")
    }


# --------------------------------------------------------------------------- credits


def test_remixer_field_credits_them() -> None:
    _stored()
    db = _library({"Title": "Sirens", "Artist": "Charli XCX", "Remixer": "Boys Noize"})

    assert _roles(attribution.local_tracks(db, _cid())) == {
        "1": ("remixer", "high", "remixer_field")
    }


@pytest.mark.parametrize(
    "title",
    [
        "Sirens (Boys Noize Remix)",
        "Sirens [Boys Noize Edit]",
        "Sirens - Boys Noize Remix",
        "Sirens Boys Noize Remix",
        "Sirens (BOYS NOIZE Remix) [Label]",
        "Sirens (Boys Noize VIP Remix)",
        "Sirens (Boys Noize Extended Remix)",
    ],
)
def test_title_remix_credit_is_remixer(title: str) -> None:
    _stored()
    db = _library({"Title": title, "Artist": "Charli XCX"})

    assert _roles(attribution.local_tracks(db, _cid())) == {
        "1": ("remixer", "medium", "title_remix")
    }


def test_title_feature_credit_is_featured() -> None:
    _stored()
    db = _library({"Title": "Bangarang (feat. Boys Noize)", "Artist": "Skrillex"})

    assert _roles(attribution.local_tracks(db, _cid())) == {
        "1": ("featured", "medium", "title_featured")
    }


def test_label_upload_with_the_artist_in_the_title_prefix_is_primary() -> None:
    _stored()
    db = _library({"Title": "Boys Noize - Rocket Boy", "Artist": "Boysnoize Records"})

    assert _roles(attribution.local_tracks(db, _cid())) == {
        "1": ("primary", "medium", "title_prefix")
    }


def test_a_version_word_is_never_a_person() -> None:
    db = _library(
        {"Title": "Song (Extended Mix)", "Artist": "Someone"},
        {"Title": "Other", "Artist": "Extended"},
    )

    page = attribution.local_tracks(db, _cid("Extended"))

    assert set(_roles(page)) == {"2"}


def test_a_near_spelling_is_not_a_credit() -> None:
    _stored()
    db = _library(
        {"Title": "Noize Boys Anthem (Toys Noize Remix)", "Artist": "Somebody"},
        {"Title": "Sirens (Boysnoize Remix)", "Artist": "Charli XCX"},
    )

    assert attribution.local_tracks(db, _cid())["tracks"] == []
    assert _cid() not in attribution.membership(db, [_cid()])


def test_the_old_artist_field_set_is_a_subset_of_the_new_one() -> None:
    db = _library(
        {"Title": "Overdrive", "Artist": "Boys Noize"},
        {"Title": "Sirens (Boys Noize Remix)", "Artist": "Charli XCX"},
        {"Title": "Bangarang", "Artist": "Skrillex feat. Boys Noize"},
    )
    art_id = next(a["id"] for a in db.artists if a["name"] == BOYS)
    old = {t["ID"] for t in db.get_tracks_by_artist(art_id)}

    new = set(attribution.membership(db, [_cid()])[_cid()])

    assert old <= new
    assert new - old == {"2"}


# --------------------------------------------------------------------------- manual


def test_assign_adds_any_track_under_the_chosen_role() -> None:
    db = _library(
        {"Title": "Overdrive", "Artist": "Boys Noize"},
        {"Title": "White Label Tool", "Artist": "Unknown"},
    )

    result = attribution.set_assignment(db, _cid(), "2", action="assign", role="remixer", name=BOYS)

    assert result["track"]["artist_role"] == {
        "role": "remixer",
        "confidence": "high",
        "source": "manual",
        "detail": "Assigned by you",
    }
    assert result["counts"]["manual"] == 1
    assert schema.get_collection(_cid()) is not None
    page = attribution.local_tracks(db, _cid())
    assert page["stored"] is True
    assert _roles(page)["2"] == ("remixer", "high", "manual")


def test_assign_defaults_to_primary() -> None:
    db = _library({"Title": "White Label Tool", "Artist": "Unknown"}, {"Artist": BOYS})

    result = attribution.set_assignment(db, _cid(), "1", action="assign", name=BOYS)

    assert result["track"]["artist_role"]["role"] == "primary"


def test_exclude_beats_every_automatic_match() -> None:
    db = _library(
        {"Title": "Overdrive", "Artist": "Boys Noize"},
        {"Title": "Sirens (Boys Noize Remix)", "Artist": "Charli XCX"},
    )

    first = attribution.set_assignment(db, _cid(), "1", action="exclude", name=BOYS)
    attribution.set_assignment(db, _cid(), "2", action="exclude", name=BOYS)

    assert first["track"] is None
    page = attribution.local_tracks(db, _cid())
    assert page["tracks"] == []
    assert {e["track_id"]: e["would_be"]["role"] for e in page["excluded"]} == {
        "1": "primary",
        "2": "remixer",
    }
    assert _cid() not in attribution.membership(db, [_cid()])


def test_clear_hands_the_track_back_to_the_automatic_layers() -> None:
    db = _library({"Title": "Overdrive", "Artist": "Boys Noize"})
    attribution.set_assignment(db, _cid(), "1", action="exclude", name=BOYS)

    result = attribution.set_assignment(db, _cid(), "1", action="clear")

    assert result["track"]["artist_role"]["source"] == "artist_field"
    assert attribution.local_tracks(db, _cid())["excluded"] == []


def test_an_assigned_track_that_left_the_library_is_listed_not_repointed() -> None:
    db = _library({"Title": "Overdrive", "Artist": "Boys Noize"}, {"Title": "Gone", "Artist": "X"})
    attribution.set_assignment(db, _cid(), "2", action="assign", name=BOYS)
    del db.tracks["2"]

    page = attribution.local_tracks(db, _cid())

    assert set(_roles(page)) == {"1"}
    assert page["assigned_missing"] == [
        {"track_id": "2", "title": "Gone", "artist": "X", "role": "primary", "reason": "gone"}
    ]


def _reload_with(db: LiveRekordboxDB, tid: str, row: dict) -> None:
    """A reload — another XML, a rebuilt master.db — that hands ``tid`` to ``row``."""
    db.tracks[tid] = {"ID": tid, "Title": "", "Artist": "", "Remixer": "", **row}
    db._finalize_ui_metadata()


def test_a_reused_id_does_not_carry_a_manual_assignment() -> None:
    db = _library({"Title": "Overdrive", "Artist": "Boys Noize"}, {"Title": "White Label Tool"})
    attribution.set_assignment(db, _cid(), "2", action="assign", role="remixer", name=BOYS)

    _reload_with(db, "2", {"Title": "Completely Different Song", "Artist": "Other Act"})
    page = attribution.local_tracks(db, _cid())

    assert set(_roles(page)) == {"1"}
    assert page["assigned_missing"] == [
        {
            "track_id": "2",
            "title": "White Label Tool",
            "artist": "",
            "role": "remixer",
            "reason": "replaced",
        }
    ]
    assert attribution.membership(db, [_cid()]) == {_cid(): ["1"]}


def test_a_reused_id_does_not_carry_an_exclusion() -> None:
    db = _library({"Title": "Rocket Boy", "Artist": "Boys Noize"})
    attribution.set_assignment(db, _cid(), "1", action="exclude", name=BOYS)

    _reload_with(db, "1", {"Title": "Overdrive", "Artist": "Boys Noize"})
    page = attribution.local_tracks(db, _cid())

    assert _roles(page) == {"1": ("primary", "high", "artist_field")}
    assert page["excluded"] == []


@pytest.mark.parametrize(
    ("then", "now"),
    [
        ("Boys Noize - Starter", "Starter"),
        ("01 Starter", "Starter"),
        ("Starter", "Starter (Original Mix)"),
        ("STARTER", "starter"),
    ],
)
def test_a_fixed_title_keeps_the_manual_row(then: str, now: str) -> None:
    db = _library({"Title": then, "Artist": "Boysnoize Records"})
    attribution.set_assignment(db, _cid(), "1", action="assign", role="primary", name=BOYS)

    _reload_with(db, "1", {"Title": now, "Artist": "Boysnoize Records"})

    assert _roles(attribution.local_tracks(db, _cid())) == {"1": ("primary", "high", "manual")}


def test_a_merge_rewritten_artist_keeps_the_manual_row() -> None:
    db = _library({"Title": "Starter", "Artist": "Boysnoize Records"})
    attribution.set_assignment(db, _cid(), "1", action="exclude", name=BOYS)

    _reload_with(db, "1", {"Title": "Starter", "Artist": "BNR"})

    assert [e["track_id"] for e in attribution.local_tracks(db, _cid())["excluded"]] == ["1"]


def test_a_title_that_only_shares_letters_is_another_recording() -> None:
    db = _library({"Title": "Go", "Artist": "Somebody"})
    attribution.set_assignment(db, _cid(), "1", action="assign", name=BOYS)

    _reload_with(db, "1", {"Title": "Gold", "Artist": "Somebody"})

    assert attribution.local_tracks(db, _cid())["assigned_missing"][0]["reason"] == "replaced"


def test_a_name_that_does_not_derive_the_id_is_refused() -> None:
    db = _library({"Title": "Overdrive", "Artist": "Boys Noize"})

    with pytest.raises(attribution.UnknownCollection):
        attribution.set_assignment(db, _cid(), "1", action="exclude", name="Somebody Else")
    with pytest.raises(attribution.UnknownCollection):
        attribution.set_assignment(db, _cid(), "1", action="exclude")
    with pytest.raises(attribution.UnknownCollection):
        attribution.set_assignment(db, _cid(), "1", action="clear")
    assert schema.get_collection(_cid()) is None


def test_bad_inputs_are_refused_before_anything_is_written() -> None:
    db = _library({"Title": "Overdrive", "Artist": "Boys Noize"})

    with pytest.raises(attribution.TrackNotInLibrary):
        attribution.set_assignment(db, _cid(), "999", action="assign", name=BOYS)
    with pytest.raises(ValueError):
        attribution.set_assignment(db, _cid(), "1", action="assign", role="uncertain", name=BOYS)
    with pytest.raises(ValueError):
        attribution.set_assignment(db, _cid(), "1", action="delete", name=BOYS)
    with pytest.raises(attribution.LibraryNotLoaded):
        attribution.set_assignment(None, _cid(), "1", action="assign", name=BOYS)
    assert schema.get_collection(_cid()) is None


# --------------------------------------------------------------------------- read edges


def test_unknown_collection_is_none() -> None:
    db = _library({"Title": "Overdrive", "Artist": "Boys Noize"})

    assert attribution.local_tracks(db, _cid("Nobody")) is None
    assert attribution.search_candidates(db, _cid("Nobody"), "over") is None
    assert attribution.search_candidates(None, _cid("Nobody"), "over") is None


def test_without_a_library_a_stored_artist_is_empty_and_says_why() -> None:
    cid = _stored()

    page = attribution.local_tracks(None, cid)

    assert page["library_loaded"] is False
    assert page["tracks"] == []
    assert attribution.membership(None, [cid]) == {}


def test_search_candidates_flags_attributed_and_excluded_rows() -> None:
    db = _library(
        {"Title": "Overdrive", "Artist": "Boys Noize"},
        {"Title": "Over and Over", "Artist": "Somebody"},
        {"Title": "Overkill", "Artist": "Boys Noize"},
    )
    attribution.set_assignment(db, _cid(), "3", action="exclude", name=BOYS)

    result = attribution.search_candidates(db, _cid(), "over")

    by_id = {t["id"]: t for t in result["tracks"]}
    assert result["total"] == 3
    assert by_id["1"]["artist_role"]["role"] == "primary"
    assert by_id["2"]["artist_role"] is None
    assert by_id["3"]["excluded"] is True
    assert attribution.search_candidates(db, _cid(), "   ")["tracks"] == []


# --------------------------------------------------------------------------- projection


def test_projection_reads_the_same_membership() -> None:
    db = _library(
        {"Title": "Overdrive", "Artist": "Boys Noize"},
        {"Title": "Sirens (Boys Noize Remix)", "Artist": "Charli XCX"},
        {"Title": "Rocket Boy", "Artist": "Boys Noize"},
    )
    attribution.set_assignment(db, _cid(), "3", action="exclude", name=BOYS)

    ids = projection._artist_track_ids(db, schema.KIND_ARTIST, {_cid()})

    assert ids == {_cid(): ["1", "2"]}


# --------------------------------------------------------------------------- migration v3


def test_v2_file_walks_to_v3_and_keeps_its_rows(tmp_path) -> None:
    conn = sqlite3.connect(str(tmp_path / "old.db"))
    conn.row_factory = sqlite3.Row
    conn.executescript(schema._DDL_V1)
    conn.executescript(schema._DDL_V2_TRACK_IDENTITY)
    conn.execute(
        "INSERT INTO collections (id, kind, canonical_name, sort_key, created_at, updated_at) "
        "VALUES ('a_1', 'artist', 'Boys Noize', 'boys noize', '2026-01-01', '2026-01-01')"
    )
    conn.execute(
        "INSERT INTO track_identity (sc_urn, collection_id, role, confidence, first_seen, "
        "last_seen) VALUES ('soundcloud:tracks:1', 'a_1', 'primary', 'high', 'x', 'x')"
    )
    schema._set_schema_version(conn, 2)
    conn.commit()

    assert schema.migrate(conn) == 3
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"web_links", "link_fetch", "track_assignments"} <= tables
    assert conn.execute("SELECT COUNT(*) FROM track_identity").fetchone()[0] == 1
    assert schema.migrate(conn) == 3
    conn.close()


def test_v3_step_is_registered() -> None:
    assert schema._MIGRATIONS[2] is schema._migrate_v2_to_v3
    assert schema.SCHEMA_VERSION == 3
