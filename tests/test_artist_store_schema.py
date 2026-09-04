"""Artist-Hub sidecar schema tests (T-3 — app/artist_store/schema.py).

Covers the load-bearing invariants: the DB lives beside the other sidecars (never
inside Rekordbox ``master.db``), schema creation is idempotent, the migration runner
walks versions forward and refuses a downgrade, ids are derived from the canonical
name (never from the UI's unstable ``art_{i}``), aliases and favourites round-trip,
and every writer holds the module-private lock — not ``_db_write_lock``.

No Rekordbox library is opened here; the store is pure SQLite.
"""

from __future__ import annotations

import ast
import sqlite3
import threading
from pathlib import Path

import pytest
from platformdirs import user_data_dir

from app.artist_store import schema

EXPECTED_TABLES = {
    "collections",
    "aliases",
    "links",
    "sync_state",
    "projection",
    "catalogue_cache",
    "favourites",
    "store_meta",
}


def _close_thread_conn() -> None:
    conn = getattr(schema._local, "conn", None)
    if conn is not None:
        conn.close()
        del schema._local.conn


@pytest.fixture
def store(tmp_path, monkeypatch):
    """Point the module at a throwaway DB and reset its per-thread/process state."""
    db_file = tmp_path / "artists.db"
    monkeypatch.setattr(schema, "_db_path", lambda: db_file)
    monkeypatch.setattr(schema, "_initialised", False)
    _close_thread_conn()
    schema.init_db()
    yield schema
    _close_thread_conn()


@pytest.fixture
def artist(store) -> str:
    return store.create_collection("Boys Noize")


class _RecordingLock:
    """threading.Lock that counts acquisitions, so a writer can be proven to lock."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.acquisitions = 0

    def __enter__(self):
        self._lock.acquire()
        self.acquisitions += 1
        return self

    def __exit__(self, *exc_info) -> bool:
        self._lock.release()
        return False


class TestDbLocation:
    def test_db_path_is_under_user_data_dir(self) -> None:
        expected_dir = Path(user_data_dir("MusicLibraryManager", appauthor=False, roaming=False))
        path = schema._db_path()
        assert path.parent == expected_dir
        assert path.name == "artists.db"

    def test_module_does_not_borrow_the_rekordbox_write_lock(self) -> None:
        # _db_write_lock serialises rbox master.db writers only; a sidecar taking it
        # would stall the whole library behind favourites bookkeeping. Walked as an AST
        # so this test needs neither rbox nor an import of app.database.
        tree = ast.parse(Path(schema.__file__).read_text(encoding="utf-8"))
        used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        used |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        assert not used & {"_db_write_lock", "db_lock"}

        imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
        assert "app.database" not in imported
        assert isinstance(schema._write_lock, type(threading.Lock()))


class TestSchemaCreation:
    def test_all_tables_exist(self, store) -> None:
        names = {
            r["name"]
            for r in store._connect()
            .execute("SELECT name FROM sqlite_master WHERE type='table'")
            .fetchall()
        }
        assert names >= EXPECTED_TABLES

    def test_kind_sort_index_exists(self, store) -> None:
        names = {
            r["name"]
            for r in store._connect()
            .execute("SELECT name FROM sqlite_master WHERE type='index'")
            .fetchall()
        }
        assert "ix_collections_kind_sort" in names

    def test_init_is_idempotent_and_keeps_data(self, store) -> None:
        cid = store.create_collection("Boys Noize")
        store.add_favourite(cid)

        store.init_db()
        store.init_db()

        assert store.get_collection(cid) is not None
        assert [f["id"] for f in store.list_favourites()] == [cid]
        assert store._schema_version(store._connect()) == store.SCHEMA_VERSION

    def test_kind_defaults_to_artist(self, store) -> None:
        conn = store._connect()
        conn.execute(
            "INSERT INTO collections (id, canonical_name, sort_key, created_at, updated_at) "
            "VALUES ('x_1', 'X', 'x', '2026-01-01', '2026-01-01')"
        )
        row = conn.execute("SELECT kind FROM collections WHERE id = 'x_1'").fetchone()
        assert row["kind"] == "artist"


class TestMigrationRunner:
    def test_fresh_db_is_stamped_at_current_version(self, store) -> None:
        assert store._schema_version(store._connect()) == store.SCHEMA_VERSION

    def test_step_walk_bumps_the_version(self, store, monkeypatch) -> None:
        walked: list[int] = []

        def _v1_to_v2(conn: sqlite3.Connection) -> None:
            walked.append(2)
            conn.execute("CREATE TABLE step_two (x TEXT)")

        def _v2_to_v3(conn: sqlite3.Connection) -> None:
            walked.append(3)
            conn.execute("CREATE TABLE step_three (x TEXT)")

        monkeypatch.setattr(store, "SCHEMA_VERSION", 3)
        monkeypatch.setattr(store, "_MIGRATIONS", {1: _v1_to_v2, 2: _v2_to_v3})

        conn = store._connect()
        assert store.migrate(conn) == 3
        assert walked == [2, 3], "steps must run in order, one version at a time"
        assert store._schema_version(conn) == 3
        tables = {
            r["name"]
            for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert {"step_two", "step_three"} <= tables

    def test_missing_step_raises_instead_of_skipping(self, store, monkeypatch) -> None:
        monkeypatch.setattr(store, "SCHEMA_VERSION", 4)
        monkeypatch.setattr(store, "_MIGRATIONS", {})
        with pytest.raises(RuntimeError, match="no migration path"):
            store.migrate(store._connect())

    def test_downgrade_is_refused(self, store, monkeypatch) -> None:
        conn = store._connect()
        future = store.SCHEMA_VERSION + 5
        store._set_schema_version(conn, future)
        conn.commit()

        called: list[int] = []
        monkeypatch.setattr(
            store, "_MIGRATIONS", {store.SCHEMA_VERSION: lambda c: called.append(1)}
        )

        assert store.migrate(conn) == future, "a newer DB must be reported, not rewritten"
        assert called == []
        assert store._schema_version(conn) == future


class TestCollectionIds:
    def test_id_is_derived_and_stable_across_casing_and_spacing(self) -> None:
        base = schema.collection_id_for("Boys Noize")
        assert base == schema.collection_id_for("boys noize")
        assert base == schema.collection_id_for("  BOYS   NOIZE ")

    def test_id_never_looks_like_the_unstable_ui_id(self) -> None:
        # art_{i} is a list index rebuilt on every library load — a store keyed on it
        # silently repoints to a different artist after the next scan.
        assert not schema.collection_id_for("Boys Noize").startswith("art_")

    def test_kind_is_part_of_the_id(self) -> None:
        assert schema.collection_id_for("Kompakt", "label") != schema.collection_id_for("Kompakt")

    def test_blank_name_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-space"):
            schema.collection_id_for("   ")

    def test_create_is_idempotent_for_a_recased_name(self, store) -> None:
        first = store.create_collection("Boys Noize")
        second = store.create_collection("boys noize")
        assert first == second
        assert len(store.list_collections()) == 1

    def test_rename_keeps_the_id_and_keeps_the_old_name_resolvable(self, store, artist) -> None:
        assert store.set_canonical_name(artist, "Boys Noize (DE)") is True
        assert store.get_collection(artist)["canonical_name"] == "Boys Noize (DE)"
        assert store.resolve_alias("Boys Noize")["id"] == artist


class TestAliases:
    def test_alias_round_trip(self, store, artist) -> None:
        assert store.add_alias(artist, "BOYS NOIZE", source="merge") is True
        assert store.add_alias(artist, "BOYS NOIZE", source="merge") is False

        aliases = {a["alias"] for a in store.list_aliases(artist)}
        assert {"Boys Noize", "BOYS NOIZE"} <= aliases

        assert store.resolve_alias("BOYS NOIZE")["id"] == artist
        assert store.remove_alias(artist, "BOYS NOIZE") is True
        assert store.remove_alias(artist, "BOYS NOIZE") is False

    def test_several_variants_resolve_to_one_collection(self, store, artist) -> None:
        # This is what makes a merge survive: the raw library strings keep resolving.
        for variant in ("boys noize", "BOYS NOIZE", "Boys  Noize"):
            store.add_alias(artist, variant, source="merge")
        resolved = {
            store.resolve_alias(v)["id"] for v in ("boys noize", "BOYS NOIZE", "Boys  Noize")
        }
        assert resolved == {artist}

    def test_unknown_alias_resolves_to_none(self, store, artist) -> None:
        assert store.resolve_alias("Someone Else") is None
        assert store.resolve_alias("   ") is None

    def test_canonical_alias_is_seeded_on_create(self, store, artist) -> None:
        sources = {a["alias"]: a["source"] for a in store.list_aliases(artist)}
        assert sources["Boys Noize"] == "canonical"


class TestFavourites:
    def test_favourites_round_trip(self, store, artist) -> None:
        assert store.is_favourite(artist) is False
        assert store.add_favourite(artist) is True
        assert store.add_favourite(artist) is False, "adding twice must not duplicate the row"
        assert store.is_favourite(artist) is True

        rows = store.list_favourites()
        assert [r["id"] for r in rows] == [artist]
        assert rows[0]["canonical_name"] == "Boys Noize"
        assert rows[0]["added_at"]

        assert store.remove_favourite(artist) is True
        assert store.remove_favourite(artist) is False
        assert store.list_favourites() == []

    def test_favourites_are_ordered_by_sort_key(self, store) -> None:
        for name in ("Zomby", "Aphex Twin", "boys noize"):
            store.add_favourite(store.create_collection(name))
        assert [r["canonical_name"] for r in store.list_favourites()] == [
            "Aphex Twin",
            "boys noize",
            "Zomby",
        ]

    def test_favourite_requires_an_existing_collection(self, store) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            store.add_favourite("a_deadbeef0000")


class TestLinksSyncProjection:
    def test_link_round_trip_and_upsert(self, store, artist) -> None:
        store.set_link(artist, "soundcloud", "soundcloud:users:1234567", "boysnoize", 0.98)
        link = store.get_link(artist, "soundcloud")
        assert link["remote_id"] == "soundcloud:users:1234567"
        assert link["permalink"] == "boysnoize"
        assert link["confidence"] == pytest.approx(0.98)

        store.set_link(artist, "soundcloud", "soundcloud:users:7654321", "boysnoize2", 0.4)
        assert store.get_link(artist, "soundcloud")["remote_id"] == "soundcloud:users:7654321"
        assert store.remove_link(artist, "soundcloud") is True
        assert store.get_link(artist, "soundcloud") is None

    def test_sync_mode_defaults_to_review(self, store, artist) -> None:
        assert store.get_sync_state(artist) is None
        assert store.get_sync_mode(artist) == store.SYNC_REVIEW

    def test_sync_mode_round_trip(self, store, artist) -> None:
        store.set_sync_mode(artist, store.SYNC_AUTO)
        assert store.get_sync_mode(artist) == "auto"
        store.set_sync_mode(artist, store.SYNC_OFF)
        assert store.get_sync_mode(artist) == "off"

    def test_unknown_sync_mode_is_rejected(self, store, artist) -> None:
        with pytest.raises(ValueError, match="unknown sync mode"):
            store.set_sync_mode(artist, "sometimes")

    def test_record_sync_keeps_the_mode(self, store, artist) -> None:
        store.set_sync_mode(artist, store.SYNC_AUTO)
        store.record_sync(artist, error="429 from provider")
        state = store.get_sync_state(artist)
        assert state["mode"] == "auto", "an error stamp must not reset the user's choice"
        assert state["last_error"] == "429 from provider"
        assert state["last_sync_at"]

        store.record_sync(artist)
        assert store.get_sync_state(artist)["last_error"] is None

    def test_projection_round_trip(self, store, artist) -> None:
        assert store.get_projection(artist) is None
        store.set_projection(artist, "37501150", "u-abc")
        row = store.get_projection(artist)
        assert row["rb_playlist_id"] == "37501150"
        assert row["rb_uuid"] == "u-abc"
        assert row["last_projected_at"]

        store.set_projection(artist, "175782530")
        assert store.get_projection(artist)["rb_playlist_id"] == "175782530"
        assert store.clear_projection(artist) is True
        assert store.get_projection(artist) is None

    def test_catalogue_cache_round_trip_and_ttl(self, store, artist) -> None:
        store.set_catalogue_cache(artist, {"tracks": [{"title": "Rocket Boy"}]})
        assert store.get_catalogue_cache(artist)["tracks"][0]["title"] == "Rocket Boy"
        assert store.get_catalogue_cache(artist, max_age_s=3600) is not None
        assert store.get_catalogue_cache(artist, max_age_s=-1) is None

    def test_deleting_a_collection_cascades(self, store, artist) -> None:
        store.add_favourite(artist)
        store.set_link(artist, "soundcloud", "soundcloud:users:1", "x", 1.0)
        store.set_sync_mode(artist, store.SYNC_AUTO)
        store.set_projection(artist, "37501150")
        store.set_catalogue_cache(artist, [])

        assert store.delete_collection(artist) is True
        assert store.delete_collection(artist) is False

        conn = store._connect()
        # Literal statements, not an interpolated table name — house rule, and the
        # allowlist here is the child-table list itself.
        counts = {
            "aliases": "SELECT COUNT(*) AS n FROM aliases WHERE collection_id = ?",
            "links": "SELECT COUNT(*) AS n FROM links WHERE collection_id = ?",
            "sync_state": "SELECT COUNT(*) AS n FROM sync_state WHERE collection_id = ?",
            "projection": "SELECT COUNT(*) AS n FROM projection WHERE collection_id = ?",
            "catalogue_cache": "SELECT COUNT(*) AS n FROM catalogue_cache WHERE collection_id = ?",
            "favourites": "SELECT COUNT(*) AS n FROM favourites WHERE collection_id = ?",
        }
        for table, sql in counts.items():
            assert conn.execute(sql, (artist,)).fetchone()["n"] == 0, f"{table} kept an orphan"


class TestWriteLocking:
    @pytest.mark.parametrize(
        "call",
        [
            pytest.param(lambda s, cid: s.create_collection("Someone New"), id="create_collection"),
            pytest.param(lambda s, cid: s.add_alias(cid, "BOYS NOIZE"), id="add_alias"),
            pytest.param(lambda s, cid: s.remove_alias(cid, "Boys Noize"), id="remove_alias"),
            pytest.param(lambda s, cid: s.set_canonical_name(cid, "Boys Noize DE"), id="rename"),
            pytest.param(lambda s, cid: s.set_link(cid, "soundcloud", "u:1"), id="set_link"),
            pytest.param(lambda s, cid: s.remove_link(cid, "soundcloud"), id="remove_link"),
            pytest.param(lambda s, cid: s.set_sync_mode(cid, "auto"), id="set_sync_mode"),
            pytest.param(lambda s, cid: s.record_sync(cid), id="record_sync"),
            pytest.param(lambda s, cid: s.set_projection(cid, "1"), id="set_projection"),
            pytest.param(lambda s, cid: s.clear_projection(cid), id="clear_projection"),
            pytest.param(lambda s, cid: s.add_favourite(cid), id="add_favourite"),
            pytest.param(lambda s, cid: s.remove_favourite(cid), id="remove_favourite"),
            pytest.param(lambda s, cid: s.set_catalogue_cache(cid, []), id="set_catalogue_cache"),
            pytest.param(lambda s, cid: s.delete_collection(cid), id="delete_collection"),
        ],
    )
    def test_every_writer_holds_the_module_lock(self, store, artist, monkeypatch, call) -> None:
        recorder = _RecordingLock()
        monkeypatch.setattr(store, "_write_lock", recorder)
        call(store, artist)
        assert recorder.acquisitions >= 1

    @pytest.mark.parametrize(
        "call",
        [
            pytest.param(lambda s, cid: s.get_collection(cid), id="get_collection"),
            pytest.param(lambda s, cid: s.list_collections(), id="list_collections"),
            pytest.param(lambda s, cid: s.list_aliases(cid), id="list_aliases"),
            pytest.param(lambda s, cid: s.resolve_alias("Boys Noize"), id="resolve_alias"),
            pytest.param(lambda s, cid: s.list_favourites(), id="list_favourites"),
            pytest.param(lambda s, cid: s.is_favourite(cid), id="is_favourite"),
            pytest.param(lambda s, cid: s.get_sync_mode(cid), id="get_sync_mode"),
            pytest.param(lambda s, cid: s.get_projection(cid), id="get_projection"),
        ],
    )
    def test_reads_do_not_take_the_lock(self, store, artist, monkeypatch, call) -> None:
        recorder = _RecordingLock()
        monkeypatch.setattr(store, "_write_lock", recorder)
        call(store, artist)
        assert recorder.acquisitions == 0, "reads must not serialise behind the writer"

    def test_concurrent_writers_do_not_lose_rows(self, store) -> None:
        names = [f"Artist {i:03d}" for i in range(60)]
        errors: list[Exception] = []

        def _worker(chunk: list[str]) -> None:
            try:
                for name in chunk:
                    store.add_favourite(store.create_collection(name))
            except Exception as e:  # re-asserted below; a swallowed error would pass the test
                errors.append(e)

        threads = [threading.Thread(target=_worker, args=(names[i::4],)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert len(store.list_favourites()) == len(names)
