"""Artist-Hub registry tests (T-4 — app/artist_store/registry.py).

Covers the load-bearing behaviour: resolving the library into the store is idempotent
and never keys on the UI's unstable ``art_{i}`` ids, favourites round-trip with the
enrichment the hub renders, and the Tier-1 backlog is owned-track-count descending
with everything already favourited removed — the ranking the owner asked for.

No Rekordbox library is opened: the fixture builds a ``LiveRekordboxDB`` against a
path that does not exist, fills ``.tracks`` by hand and runs the real
``_finalize_ui_metadata`` so the artist list comes from production code. The store is
a throwaway SQLite file in ``tmp_path``.
"""

from __future__ import annotations

import pytest

pytest.importorskip("rbox", reason="pyrekordbox not installed on this platform")

from app.artist_store import registry, schema
from app.live_database import LiveRekordboxDB


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
def store(tmp_path, monkeypatch):
    """Point the sidecar at a throwaway DB and reset its per-process state."""
    monkeypatch.setattr(schema, "_db_path", lambda: tmp_path / "artists.db")
    monkeypatch.setattr(schema, "_initialised", False)
    _close_thread_conn()
    schema.init_db()
    yield schema
    _close_thread_conn()


def _library(*artist_strings: str) -> LiveRekordboxDB:
    """A loaded-looking library whose artist list came from the production splitter."""
    db = LiveRekordboxDB("does-not-exist.db")
    db.tracks = {
        str(i): {"id": str(i), "Artist": a, "Artwork": ""} for i, a in enumerate(artist_strings)
    }
    db._finalize_ui_metadata()
    return db


def _names(rows) -> list[str]:
    return [r["name"] for r in rows]


# --------------------------------------------------------------------------- resolve


def test_resolve_creates_one_collection_per_artist() -> None:
    db = _library("Boys Noize", "Boys Noize", "Helena Hauff")

    result = registry.resolve_library_artists(db)

    assert result["scanned"] == 2
    assert result["created"] == 2
    assert sorted(c["canonical_name"] for c in schema.list_collections()) == [
        "Boys Noize",
        "Helena Hauff",
    ]


def test_resolve_is_idempotent() -> None:
    db = _library("Boys Noize", "Helena Hauff", "Marie Davidson")

    first = registry.resolve_library_artists(db)
    before = [dict(c) for c in schema.list_collections()]
    aliases_before = {c["id"]: schema.list_aliases(c["id"]) for c in before}

    second = registry.resolve_library_artists(db)

    assert first["created"] == 3
    assert second["created"] == 0, "a second pass minted new collections"
    assert second["aliases_added"] == 0, "a second pass duplicated alias rows"
    assert second["by_name"] == first["by_name"]
    after = [dict(c) for c in schema.list_collections()]
    assert [c["id"] for c in after] == [c["id"] for c in before]
    assert {c["id"]: schema.list_aliases(c["id"]) for c in after} == aliases_before


def test_resolve_records_the_raw_library_name_as_an_alias() -> None:
    db = _library("Boys Noize")

    registry.resolve_library_artists(db)

    cid = schema.collection_id_for("Boys Noize")
    aliases = {a["alias"] for a in schema.list_aliases(cid)}
    assert "Boys Noize" in aliases


def test_resolve_folds_case_variants_onto_one_collection() -> None:
    db = _library("Boys Noize", "boys noize", "BOYS NOIZE")

    result = registry.resolve_library_artists(db)

    assert len(set(result["by_name"].values())) == 1, "casing split one artist into several"
    assert len(schema.list_collections()) == 1


def test_resolve_keeps_a_merged_variant_on_its_canonical_collection() -> None:
    canonical = schema.create_collection("Boys Noize")
    schema.add_alias(canonical, "Boys Noize (Official)", source="merge")
    db = _library("Boys Noize", "Boys Noize (Official)")

    result = registry.resolve_library_artists(db)

    assert set(result["by_name"].values()) == {canonical}, "a merge was split back apart"
    assert len(schema.list_collections()) == 1


def test_resolve_ids_are_not_the_unstable_ui_ids() -> None:
    db = _library("Boys Noize", "Helena Hauff")

    result = registry.resolve_library_artists(db)

    ui_ids = {a["id"] for a in db.artists}
    assert ui_ids & set(result["by_name"].values()) == set()
    assert all(not cid.startswith("art_") for cid in result["by_name"].values())


# --------------------------------------------------------------------------- favourites


def test_favourites_round_trip() -> None:
    db = _library("Boys Noize", "Boys Noize", "Helena Hauff")
    registry.resolve_library_artists(db)
    cid = schema.collection_id_for("Boys Noize")

    assert registry.add_favourite_artist(cid) is True
    assert registry.add_favourite_artist(cid) is False

    rows = registry.list_favourite_artists(db)
    assert _names(rows) == ["Boys Noize"]
    row = rows[0]
    assert row["collection_id"] == cid
    assert row["track_count"] == 2
    assert row["sync_mode"] == schema.SYNC_REVIEW
    assert row["sc_linked"] is False
    assert row["favourite"] is True

    assert registry.remove_favourite_artist(cid) is True
    assert registry.list_favourite_artists(db) == []
    assert schema.get_collection(cid) is not None, "un-favouriting deleted the collection"


def test_favourite_rows_report_the_soundcloud_link_and_sync_mode() -> None:
    db = _library("Boys Noize")
    registry.resolve_library_artists(db)
    cid = schema.collection_id_for("Boys Noize")
    registry.add_favourite_artist(cid)
    schema.set_link(
        cid,
        registry.PROVIDER_SOUNDCLOUD,
        remote_id="soundcloud:users:1234",
        permalink="https://soundcloud.com/boysnoize",
    )
    schema.set_sync_mode(cid, schema.SYNC_AUTO)

    row = registry.list_favourite_artists(db)[0]

    assert row["sc_linked"] is True
    assert row["sc_permalink"] == "https://soundcloud.com/boysnoize"
    assert row["sync_mode"] == schema.SYNC_AUTO


def test_favourite_track_count_sums_alias_variants() -> None:
    db = _library("Boys Noize", "boys noize", "BOYS NOIZE", "Helena Hauff")
    registry.resolve_library_artists(db)
    cid = schema.collection_id_for("Boys Noize")
    registry.add_favourite_artist(cid)

    row = registry.list_favourite_artists(db)[0]

    assert row["track_count"] == 3, "alias variants did not fold into one count"


def test_favourite_by_name_creates_the_collection_when_unseen() -> None:
    cid = registry.favourite_artist_by_name("Marie Davidson")

    assert cid == schema.collection_id_for("Marie Davidson")
    assert schema.is_favourite(cid) is True
    assert _names(registry.list_favourite_artists()) == ["Marie Davidson"]


def test_favourite_by_name_rejects_a_blank_name() -> None:
    with pytest.raises(ValueError):
        registry.favourite_artist_by_name("   ")


def test_favouriting_an_unknown_collection_raises() -> None:
    with pytest.raises(KeyError):
        registry.add_favourite_artist("a_deadbeef1234")


def test_favourites_list_without_a_library_still_renders() -> None:
    registry.favourite_artist_by_name("Boys Noize")

    rows = registry.list_favourite_artists()

    assert _names(rows) == ["Boys Noize"]
    assert rows[0]["track_count"] == 0


# --------------------------------------------------------------------------- Tier-1 backlog


def test_backlog_is_sorted_by_owned_track_count_descending() -> None:
    db = _library(*(["Boys Noize"] * 5), *(["Helena Hauff"] * 3), "Marie Davidson")
    registry.resolve_library_artists(db)

    rows = registry.backlog(db)

    assert _names(rows) == ["Boys Noize", "Helena Hauff", "Marie Davidson"]
    assert [r["track_count"] for r in rows] == [5, 3, 1]


def test_backlog_excludes_favourited() -> None:
    db = _library(*(["Boys Noize"] * 5), *(["Helena Hauff"] * 3), "Marie Davidson")
    registry.resolve_library_artists(db)
    registry.add_favourite_artist(schema.collection_id_for("Boys Noize"))

    rows = registry.backlog(db)

    assert _names(rows) == ["Helena Hauff", "Marie Davidson"]
    assert schema.collection_id_for("Boys Noize") not in {r["collection_id"] for r in rows}


def test_backlog_excludes_a_favourite_reached_through_an_alias() -> None:
    db = _library(*(["Boys Noize"] * 4), "boys noize", "Helena Hauff")
    registry.resolve_library_artists(db)
    registry.add_favourite_artist(schema.collection_id_for("BOYS NOIZE"))

    assert _names(registry.backlog(db)) == ["Helena Hauff"]


def test_backlog_needs_no_resolve_pass_first() -> None:
    """The hub is a read: a never-resolved library still ranks, and nothing is written."""
    db = _library(*(["Boys Noize"] * 2), "Helena Hauff")

    rows = registry.backlog(db)

    assert _names(rows) == ["Boys Noize", "Helena Hauff"]
    assert schema.list_collections() == [], "a read path wrote to the store"


def test_backlog_honours_the_limit() -> None:
    db = _library(*(["Boys Noize"] * 3), *(["Helena Hauff"] * 2), "Marie Davidson")

    assert _names(registry.backlog(db, limit=2)) == ["Boys Noize", "Helena Hauff"]
    assert registry.backlog(db, limit=0) == []
    assert len(registry.backlog(db, limit=None)) == 3


def test_backlog_ties_break_deterministically() -> None:
    db = _library("Zola", "Alpha", "Mika")

    assert _names(registry.backlog(db)) == ["Alpha", "Mika", "Zola"]


def test_library_artist_counts_keys_on_store_ids() -> None:
    db = _library(*(["Boys Noize"] * 2), "boys noize", "Helena Hauff")

    counts = registry.library_artist_counts(db)

    assert counts[schema.collection_id_for("Boys Noize")] == 3
    assert counts[schema.collection_id_for("Helena Hauff")] == 1


# --------------------------------------------------------------------------- hub


def test_hub_returns_favourites_and_backlog() -> None:
    db = _library(*(["Boys Noize"] * 4), *(["Helena Hauff"] * 2), "Marie Davidson")
    registry.resolve_library_artists(db)
    registry.add_favourite_artist(schema.collection_id_for("Boys Noize"))

    payload = registry.hub(db)

    assert set(payload) == {"favourites", "backlog", "backlog_total", "backlog_query"}
    assert _names(payload["favourites"]) == ["Boys Noize"]
    assert payload["favourites"][0]["track_count"] == 4
    assert _names(payload["backlog"]) == ["Helena Hauff", "Marie Davidson"]


def test_hub_writes_nothing() -> None:
    db = _library("Boys Noize", "Helena Hauff")

    registry.hub(db)

    assert schema.list_collections() == []
    assert schema.list_favourites() == []


# --------------------------------------------------------------------------- empty library


def test_empty_library_yields_empty_lists() -> None:
    db = _library()

    assert registry.backlog(db) == []
    assert registry.list_favourite_artists(db) == []
    assert registry.hub(db) == {
        "favourites": [],
        "backlog": [],
        "backlog_total": 0,
        "backlog_query": "",
    }
    assert registry.resolve_library_artists(db) == {
        "scanned": 0,
        "created": 0,
        "aliases_added": 0,
        "by_name": {},
    }


def test_library_without_an_artist_list_yields_empty_lists() -> None:
    db = LiveRekordboxDB("does-not-exist.db")

    assert registry.backlog(db) == []
    assert registry.hub(db) == {
        "favourites": [],
        "backlog": [],
        "backlog_total": 0,
        "backlog_query": "",
    }


def test_hub_without_a_library_still_lists_favourites() -> None:
    registry.favourite_artist_by_name("Boys Noize")

    payload = registry.hub(None)

    assert _names(payload["favourites"]) == ["Boys Noize"]
    assert payload["backlog"] == []


class TestBacklogSearchBeyondTheLimit:
    """A search that only filters the rows already sent hides everything below `limit`."""

    def _db_with(self, count):
        # `count` artists on descending track counts, so "Zeta Rare" ranks last.
        names = [f"Artist {i:02d}" for i in range(count - 1)] + ["Zeta Rare"]
        strings = []
        for rank, name in enumerate(names):
            strings.extend([name] * (count - rank))
        return _library(*strings)

    def test_query_filters_before_truncation(self) -> None:
        db = self._db_with(30)

        unfiltered = registry.hub(db, backlog_limit=5)
        assert "Zeta Rare" not in [r["name"] for r in unfiltered["backlog"]]
        assert unfiltered["backlog_total"] > 5

        found = registry.hub(db, backlog_limit=5, query="zeta")
        assert [r["name"] for r in found["backlog"]] == ["Zeta Rare"]
        assert found["backlog_total"] == 1
        assert found["backlog_query"] == "zeta"

    def test_total_reports_the_pre_truncation_count(self) -> None:
        db = self._db_with(30)
        payload = registry.hub(db, backlog_limit=5)
        assert len(payload["backlog"]) == 5
        assert payload["backlog_total"] == 30

    def test_query_is_case_and_whitespace_insensitive(self) -> None:
        db = self._db_with(30)
        assert registry.hub(db, query="  ZETA  ")["backlog_total"] == 1

    def test_empty_query_is_not_a_filter(self) -> None:
        db = self._db_with(30)
        assert registry.hub(db, backlog_limit=None, query="   ")["backlog_total"] == 30


# --------------------------------------------------------------------------- browse


_BROWSE_KEYS = {
    "collection_id",
    "name",
    "track_count",
    "artwork",
    "is_favourite",
    "sync_mode",
    "sc_linked",
    "library_names",
}


def _browse_library():
    """5 artists on distinct track counts, so name- and count-order differ."""
    return _library(
        *(["Zola Jesus"] * 5),
        *(["Alpha Tracks"] * 4),
        *(["Marie Davidson"] * 3),
        *(["Boys Noize"] * 2),
        "Helena Hauff",
    )


def test_browse_rows_carry_exactly_the_contract_keys() -> None:
    db = _library("Boys Noize")

    row = registry.browse(db)["artists"][0]

    assert set(row) == _BROWSE_KEYS
    assert row["collection_id"] == schema.collection_id_for("Boys Noize")
    assert row["track_count"] == 1
    assert row["sync_mode"] == schema.SYNC_REVIEW
    assert row["sc_linked"] is False
    assert row["library_names"] == ["Boys Noize"]


def test_browse_includes_favourites_and_flags_them() -> None:
    db = _library(*(["Boys Noize"] * 2), "Helena Hauff")
    registry.resolve_library_artists(db)
    registry.add_favourite_artist(schema.collection_id_for("Boys Noize"))

    payload = registry.browse(db)

    assert _names(payload["artists"]) == ["Boys Noize", "Helena Hauff"]
    assert {r["name"]: r["is_favourite"] for r in payload["artists"]} == {
        "Boys Noize": True,
        "Helena Hauff": False,
    }
    assert _names(registry.backlog(db)) == ["Helena Hauff"], "backlog still hides favourites"


def test_browse_flags_a_favourite_reached_through_an_alias() -> None:
    db = _library(*(["Boys Noize"] * 2), "boys noize")
    registry.resolve_library_artists(db)
    registry.add_favourite_artist(schema.collection_id_for("BOYS NOIZE"))

    rows = registry.browse(db)["artists"]

    assert len(rows) == 1, "casing variants did not fold into one row"
    assert rows[0]["is_favourite"] is True
    assert sorted(rows[0]["library_names"]) == ["Boys Noize", "boys noize"]


def test_browse_reports_the_soundcloud_link_and_sync_mode() -> None:
    db = _library("Boys Noize")
    registry.resolve_library_artists(db)
    cid = schema.collection_id_for("Boys Noize")
    schema.set_link(cid, registry.PROVIDER_SOUNDCLOUD, permalink="https://soundcloud.com/bn")
    schema.set_sync_mode(cid, schema.SYNC_AUTO)

    row = registry.browse(db)["artists"][0]

    assert row["sc_linked"] is True
    assert row["sync_mode"] == schema.SYNC_AUTO


def test_browse_sorts_by_name_by_default() -> None:
    payload = registry.browse(_browse_library())

    assert _names(payload["artists"]) == [
        "Alpha Tracks",
        "Boys Noize",
        "Helena Hauff",
        "Marie Davidson",
        "Zola Jesus",
    ]
    assert payload["sort"] == "name"


def test_browse_name_sort_is_case_insensitive() -> None:
    db = _library("zeta", "Alpha", "Mika")

    assert _names(registry.browse(db, sort="name")["artists"]) == ["Alpha", "Mika", "zeta"]


def test_browse_sorts_by_track_count_descending() -> None:
    payload = registry.browse(_browse_library(), sort="tracks")

    assert _names(payload["artists"]) == [
        "Zola Jesus",
        "Alpha Tracks",
        "Marie Davidson",
        "Boys Noize",
        "Helena Hauff",
    ]
    assert [r["track_count"] for r in payload["artists"]] == [5, 4, 3, 2, 1]
    assert payload["sort"] == "tracks"


def test_browse_track_sort_breaks_ties_by_name() -> None:
    db = _library("Zola", "Alpha", "Mika")

    assert _names(registry.browse(db, sort="tracks")["artists"]) == ["Alpha", "Mika", "Zola"]


def test_browse_unknown_sort_falls_back_to_name() -> None:
    payload = registry.browse(_browse_library(), sort="popularity")

    assert payload["sort"] == "name"
    assert _names(payload["artists"]) == _names(registry.browse(_browse_library())["artists"])


def test_browse_total_is_the_pre_pagination_count() -> None:
    payload = registry.browse(_browse_library(), limit=2)

    assert len(payload["artists"]) == 2
    assert payload["total"] == 5
    assert payload["limit"] == 2
    assert payload["offset"] == 0


def test_browse_offset_pages_without_gaps_or_repeats() -> None:
    db = _library(*[f"Artist {i:02d}" for i in range(10)])

    seen = []
    for offset in range(0, 12, 3):
        page = registry.browse(db, limit=3, offset=offset)
        assert page["total"] == 10
        assert page["offset"] == offset
        seen.extend(_names(page["artists"]))

    assert seen == [f"Artist {i:02d}" for i in range(10)]
    assert len(set(seen)) == 10


def test_browse_offset_past_the_end_is_an_empty_page() -> None:
    payload = registry.browse(_browse_library(), offset=500)

    assert payload["artists"] == []
    assert payload["total"] == 5


class TestBrowseSearchBeyondTheLimit:
    """The backlog bug class again: filtering only the delivered page hides the tail."""

    def _db(self):
        names = [f"Artist {i:02d}" for i in range(29)] + ["Zeta Rare"]
        return _library(*names)

    def test_query_filters_before_pagination(self) -> None:
        db = self._db()

        page_one = registry.browse(db, limit=5)
        assert "Zeta Rare" not in _names(page_one["artists"])

        found = registry.browse(db, query="zeta", limit=5)
        assert _names(found["artists"]) == ["Zeta Rare"]
        assert found["total"] == 1
        assert found["query"] == "zeta"

    def test_query_matches_a_raw_library_variant(self) -> None:
        """A merged variant is searchable by what Rekordbox shows, not just the canonical."""
        cid = schema.create_collection("Boys Noize")
        schema.add_alias(cid, "BOYS NOIZE (Official)", source="merge")
        db = _library("Boys Noize", "BOYS NOIZE (Official)")

        found = registry.browse(db, query="official")

        assert len(found["artists"]) == 1
        assert found["artists"][0]["name"] == "Boys Noize"
        assert "BOYS NOIZE (Official)" in found["artists"][0]["library_names"]

    def test_query_is_case_and_whitespace_insensitive(self) -> None:
        assert registry.browse(self._db(), query="  ZETA  ")["total"] == 1

    def test_empty_query_is_not_a_filter(self) -> None:
        assert registry.browse(self._db(), query="   ")["total"] == 30


def test_browse_caps_the_limit() -> None:
    db = _library(*[f"Artist {i:04d}" for i in range(registry.MAX_BROWSE_LIMIT + 5)])

    payload = registry.browse(db, limit=10_000)

    assert payload["limit"] == registry.MAX_BROWSE_LIMIT
    assert len(payload["artists"]) == registry.MAX_BROWSE_LIMIT
    assert payload["total"] == registry.MAX_BROWSE_LIMIT + 5


@pytest.mark.parametrize("limit", [0, -1, -500])
def test_browse_survives_a_non_positive_limit(limit) -> None:
    payload = registry.browse(_browse_library(), limit=limit)

    assert payload["artists"] == []
    assert payload["limit"] == 0
    assert payload["total"] == 5, "the count stays honest even with nothing delivered"


def test_browse_survives_a_negative_offset() -> None:
    payload = registry.browse(_browse_library(), limit=2, offset=-5)

    assert payload["offset"] == 0
    assert _names(payload["artists"]) == ["Alpha Tracks", "Boys Noize"]


def test_browse_without_a_loaded_library_still_lists_favourites() -> None:
    """No library is not the same as no favourites — a star must stay un-starrable."""
    registry.favourite_artist_by_name("Boys Noize")

    payload = registry.browse(None)

    assert payload["total"] == 1
    assert _names(payload["artists"]) == ["Boys Noize"]
    assert payload["artists"][0]["is_favourite"] is True
    assert payload["artists"][0]["track_count"] == 0
    assert payload["artists"][0]["library_names"] == []
    assert payload["limit"] == registry.DEFAULT_BROWSE_LIMIT
    assert payload["offset"] == 0


def test_browse_without_a_library_or_favourites_is_an_empty_page() -> None:
    assert registry.browse(None) == {
        "artists": [],
        "total": 0,
        "limit": registry.DEFAULT_BROWSE_LIMIT,
        "offset": 0,
        "query": "",
        "sort": "name",
    }


def test_browse_lists_a_favourite_the_library_no_longer_contains() -> None:
    """Raising artist_view_threshold after favouriting must not orphan the star."""
    registry.favourite_artist_by_name("Gone From The Library")
    db = _library("Boys Noize", "Boys Noize")

    payload = registry.browse(db)

    rows = {r["name"]: r for r in payload["artists"]}
    assert set(rows) == {"Boys Noize", "Gone From The Library"}
    assert rows["Gone From The Library"]["is_favourite"] is True
    assert rows["Gone From The Library"]["track_count"] == 0
    assert rows["Boys Noize"]["track_count"] == 2


def test_browse_writes_nothing() -> None:
    db = _library("Boys Noize", "Helena Hauff")

    registry.browse(db, query="boys", sort="tracks")

    assert schema.list_collections() == []
    assert schema.list_favourites() == []
