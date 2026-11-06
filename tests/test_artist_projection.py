"""Artist-Hub projection tests (T-7 — app/artist_store/projection.py).

The headline requirement is idempotency: syncing twice leaves exactly one ``Artists``
folder and one playlist per favourite, with no duplicate entries, and a re-sync of an
unchanged artist performs zero ``master.db`` writes.

Nothing here opens a Rekordbox library. ``FakeRekordbox`` stands in for the
``RekordboxDB`` facade and reproduces the semantics the empirical probe measured
(``scripts/dev/rbox_artist_merge_probe.py``): playlist names are NOT unique, a path
lookup returns the first match, and adding a track never de-duplicates. The artist ->
track mapping still runs through production code — a real ``LiveRekordboxDB`` with
hand-filled ``tracks`` and the real ``_finalize_ui_metadata``.
"""

from __future__ import annotations

import itertools
from collections import Counter
from typing import Any

import pytest

pytest.importorskip("rbox", reason="pyrekordbox not installed on this platform")

from app.artist_store import projection, registry, schema
from app.live_database import LiveRekordboxDB

XML_PATH = "C:/Pioneer/rekordbox/masterPlaylists6.xml"


class FakeRekordbox:
    """Mocked facade. Counts every call so a test can assert on zero writes."""

    def __init__(self, library: Any = None, xml_path: str | None = XML_PATH) -> None:
        self.library = library
        self._xml_path = xml_path
        self.nodes: dict[str, dict[str, Any]] = {}
        self.songs: dict[str, list[str]] = {}
        self._ids = itertools.count(1)
        self.calls: Counter[str] = Counter()

    # --- reads
    @property
    def artists(self) -> list[dict[str, Any]]:
        return getattr(self.library, "artists", []) or []

    def get_tracks_by_artist(self, aid: str) -> list[dict[str, Any]]:
        self.calls["get_tracks_by_artist"] += 1
        if self.library is None:
            return []
        return self.library.get_tracks_by_artist(aid)

    def playlist_xml_path(self) -> str | None:
        self.calls["playlist_xml_path"] += 1
        return self._xml_path

    def get_playlist_by_id(self, pid: str) -> dict[str, Any] | None:
        self.calls["get_playlist_by_id"] += 1
        return self.nodes.get(str(pid))

    def get_playlist_by_path(self, path: list[str]) -> dict[str, Any] | None:
        self.calls["get_playlist_by_path"] += 1
        parent = "ROOT"
        node = None
        for name in path:
            node = next(
                (
                    n
                    for n in self.nodes.values()
                    if n["Name"] == name and str(n["ParentID"]) == str(parent)
                ),
                None,
            )
            if node is None:
                return None
            parent = node["ID"]
        return node

    def get_playlist_children(self, parent_id: str = "ROOT") -> list[dict[str, Any]]:
        self.calls["get_playlist_children"] += 1
        return [n for n in self.nodes.values() if str(n["ParentID"]) == str(parent_id)]

    def get_playlist_track_ids(self, pid: str) -> list[str]:
        self.calls["get_playlist_track_ids"] += 1
        return list(self.songs.get(str(pid), []))

    # --- writes
    def _create(self, name: str, parent_id: str, is_folder: bool) -> dict[str, Any]:
        # No uniqueness on (Name, ParentID) — measured. Two calls, two siblings.
        pid = str(next(self._ids))
        node = {
            "ID": pid,
            "Name": name,
            "ParentID": str(parent_id),
            "Type": "0" if is_folder else "1",
            "UUID": f"uuid-{pid}",
        }
        self.nodes[pid] = node
        self.songs[pid] = []
        return node

    def create_folder(self, name: str, parent_id: str = "ROOT") -> dict[str, Any]:
        self.calls["create_folder"] += 1
        return self._create(name, parent_id, True)

    def create_playlist(
        self,
        name: str,
        parent_id: str = "ROOT",
        is_folder: bool = False,
        tracks: list[str] | None = None,
    ) -> dict[str, Any]:
        self.calls["create_playlist"] += 1
        return self._create(name, parent_id, is_folder)

    def add_track_to_playlist(self, pid: str, tid: str) -> bool:
        self.calls["add_track_to_playlist"] += 1
        if str(pid) not in self.nodes:
            return False
        self.songs.setdefault(str(pid), []).append(str(tid))  # rbox never de-duplicates
        return True

    def remove_track_from_playlist(self, pid: str, tid: str) -> bool:
        self.calls["remove_track_from_playlist"] += 1
        rows = self.songs.get(str(pid), [])
        if str(tid) not in rows:
            return False
        rows.remove(str(tid))
        return True

    # --- test helpers
    def drop(self, pid: str) -> None:
        """What the user does inside Rekordbox when they delete a node."""
        self.nodes.pop(str(pid), None)
        self.songs.pop(str(pid), None)

    def folders(self, name: str) -> list[dict[str, Any]]:
        return [n for n in self.nodes.values() if n["Name"] == name and n["Type"] == "0"]

    def children_of(self, pid: str) -> list[dict[str, Any]]:
        return [n for n in self.nodes.values() if str(n["ParentID"]) == str(pid)]

    def reset_calls(self) -> None:
        self.calls.clear()


def _close_thread_conn() -> None:
    conn = getattr(schema._local, "conn", None)
    if conn is not None:
        conn.close()
        del schema._local.conn


@pytest.fixture(autouse=True)
def _neutral_library_config(monkeypatch):
    """Keep the developer's own settings and alias mappings out of the fixtures."""
    import app.services as services

    monkeypatch.setattr(services.SettingsManager, "load", staticmethod(lambda: {}))
    monkeypatch.setattr(
        services.MetadataManager,
        "get_mapped_name",
        classmethod(lambda cls, category, name: name),
    )


@pytest.fixture(autouse=True)
def store(tmp_path, monkeypatch):
    """Throwaway sidecar DB; never the user's real ``artists.db``."""
    monkeypatch.setattr(schema, "_db_path", lambda: tmp_path / "artists.db")
    monkeypatch.setattr(schema, "_initialised", False)
    _close_thread_conn()
    schema.init_db()
    yield schema
    _close_thread_conn()


@pytest.fixture(autouse=True)
def _rekordbox_closed(monkeypatch):
    """Default: Rekordbox is closed. The dev machine's real state must not leak in."""
    monkeypatch.setattr(projection, "_rekordbox_running", lambda: False)


def _library(*artist_strings: str) -> LiveRekordboxDB:
    """A loaded-looking library whose artist list came from the production splitter."""
    db = LiveRekordboxDB("does-not-exist.db")
    db.tracks = {
        str(i): {"ID": str(i), "Artist": a, "Artwork": ""}
        for i, a in enumerate(artist_strings, start=1)
    }
    db._finalize_ui_metadata()
    return db


def _favourite(name: str) -> str:
    return registry.favourite_artist_by_name(name)


def _artist_playlists(fake: FakeRekordbox) -> dict[str, list[str]]:
    """``playlist name -> member track ids`` for everything under the Artists folder."""
    folders = fake.folders("Artists")
    assert len(folders) == 1, f"expected exactly one Artists folder, got {len(folders)}"
    return {n["Name"]: fake.songs[n["ID"]] for n in fake.children_of(folders[0]["ID"])}


# --------------------------------------------------------------------------- idempotency


def test_sync_twice_leaves_one_folder_and_n_playlists() -> None:
    library = _library("Boys Noize", "Boys Noize", "Helena Hauff")
    fake = FakeRekordbox(library)
    _favourite("Boys Noize")
    _favourite("Helena Hauff")

    first = projection.sync(fake)
    second = projection.sync(fake)

    assert first["created"] is True and first["playlists_created"] == 2
    assert second["created"] is False and second["adopted"] is False
    assert second["playlists_created"] == 0, "a second sync minted new playlists"
    assert len(fake.folders("Artists")) == 1
    assert sorted(_artist_playlists(fake)) == ["Boys Noize", "Helena Hauff"]
    assert fake.calls["create_folder"] == 1


def test_second_sync_adds_no_duplicate_entries() -> None:
    library = _library("Boys Noize", "Boys Noize")
    fake = FakeRekordbox(library)
    _favourite("Boys Noize")

    projection.sync(fake)
    projection.sync(fake)

    members = _artist_playlists(fake)["Boys Noize"]
    assert sorted(members) == ["1", "2"]
    assert len(members) == len(set(members)), "the playlist grew duplicate rows"


def test_unchanged_artist_performs_zero_writes() -> None:
    library = _library("Boys Noize", "Helena Hauff")
    fake = FakeRekordbox(library)
    _favourite("Boys Noize")
    projection.sync(fake)
    fake.reset_calls()

    report = projection.sync(fake)

    assert fake.calls["add_track_to_playlist"] == 0
    assert fake.calls["remove_track_from_playlist"] == 0
    assert fake.calls["create_playlist"] == 0 and fake.calls["create_folder"] == 0
    assert report["tracks_added"] == 0 and report["tracks_removed"] == 0
    assert report["playlists_updated"] == 0


def test_folder_is_addressed_by_stored_id_not_by_name() -> None:
    """A name lookup on every run would silently hit a same-named sibling."""
    library = _library("Boys Noize")
    fake = FakeRekordbox(library)
    _favourite("Boys Noize")
    projection.sync(fake)
    fake.reset_calls()

    projection.sync(fake)

    assert fake.calls["get_playlist_by_path"] == 0
    assert fake.calls["get_playlist_by_id"] >= 1


# --------------------------------------------------------------------------- diff in place


def test_new_tracks_are_added_to_an_existing_playlist() -> None:
    library = _library("Boys Noize")
    fake = FakeRekordbox(library)
    _favourite("Boys Noize")
    projection.sync(fake)

    library.tracks["9"] = {"ID": "9", "Artist": "Boys Noize", "Artwork": ""}
    library._finalize_ui_metadata()
    report = projection.sync(fake)

    assert report["tracks_added"] == 1 and report["tracks_removed"] == 0
    assert report["playlists_updated"] == 1
    assert sorted(_artist_playlists(fake)["Boys Noize"]) == ["1", "9"]


def test_stale_tracks_are_removed_not_recreated() -> None:
    library = _library("Boys Noize", "Boys Noize")
    fake = FakeRekordbox(library)
    _favourite("Boys Noize")
    projection.sync(fake)
    playlist_id = fake.folders("Artists")[0]["ID"]
    playlist_id = fake.children_of(playlist_id)[0]["ID"]

    del library.tracks["2"]
    library._finalize_ui_metadata()
    report = projection.sync(fake)

    assert report["tracks_removed"] == 1 and report["tracks_added"] == 0
    assert fake.songs[playlist_id] == ["1"]
    assert fake.calls["create_playlist"] == 1, "the playlist was recreated instead of diffed"


def test_duplicate_rows_from_an_earlier_run_are_healed() -> None:
    library = _library("Boys Noize")
    fake = FakeRekordbox(library)
    _favourite("Boys Noize")
    projection.sync(fake)
    playlist_id = fake.children_of(fake.folders("Artists")[0]["ID"])[0]["ID"]
    fake.songs[playlist_id].append("1")  # what a pre-fix run left behind

    report = projection.sync(fake)

    assert fake.songs[playlist_id] == ["1"]
    assert report["tracks_removed"] == 1


def test_alias_variants_land_in_one_playlist() -> None:
    library = _library("Boys Noize", "boys noize", "BOYS NOIZE")
    fake = FakeRekordbox(library)
    _favourite("Boys Noize")

    projection.sync(fake)

    playlists = _artist_playlists(fake)
    assert list(playlists) == ["Boys Noize"]
    assert sorted(playlists["Boys Noize"]) == ["1", "2", "3"]


# --------------------------------------------------------------------------- self-healing


def test_deleted_playlist_is_recreated_and_the_new_id_stored() -> None:
    library = _library("Boys Noize")
    fake = FakeRekordbox(library)
    cid = _favourite("Boys Noize")
    projection.sync(fake)
    old_id = schema.get_projection(cid)["rb_playlist_id"]
    fake.drop(old_id)  # user deleted it inside Rekordbox

    report = projection.sync(fake)

    new_id = schema.get_projection(cid)["rb_playlist_id"]
    assert new_id != old_id, "the id-map still points at the deleted playlist"
    assert new_id in fake.nodes
    assert report["playlists_created"] == 1
    assert fake.songs[new_id] == ["1"], "the recreated playlist was left empty"


def test_playlist_recreated_by_hand_is_readopted_not_duplicated() -> None:
    library = _library("Boys Noize")
    fake = FakeRekordbox(library)
    cid = _favourite("Boys Noize")
    projection.sync(fake)
    folder_id = fake.folders("Artists")[0]["ID"]
    fake.drop(schema.get_projection(cid)["rb_playlist_id"])
    manual = fake.create_playlist("Boys Noize", folder_id)

    report = projection.sync(fake)

    assert report["playlists_adopted"] == 1 and report["playlists_created"] == 0
    assert schema.get_projection(cid)["rb_playlist_id"] == manual["ID"]
    assert len(fake.children_of(folder_id)) == 1


def test_preexisting_folder_is_adopted_by_name_exactly_once() -> None:
    library = _library("Boys Noize")
    fake = FakeRekordbox(library)
    existing = fake.create_folder("Artists")
    fake.reset_calls()
    _favourite("Boys Noize")

    first = projection.sync(fake)
    lookups_after_first = fake.calls["get_playlist_by_path"]
    second = projection.sync(fake)

    assert first["adopted"] is True and first["created"] is False
    assert first["folder_id"] == existing["ID"]
    assert second["adopted"] is False
    assert fake.calls["create_folder"] == 0
    assert lookups_after_first == 1 and fake.calls["get_playlist_by_path"] == 1


def test_deleted_folder_is_readopted_by_name_once_then_tracked_by_id() -> None:
    library = _library("Boys Noize")
    fake = FakeRekordbox(library)
    _favourite("Boys Noize")
    projection.sync(fake)
    fake.drop(fake.folders("Artists")[0]["ID"])
    replacement = fake.create_folder("Artists")  # user made their own
    fake.reset_calls()

    report = projection.sync(fake)

    assert report["adopted"] is True and report["created"] is False
    assert report["folder_id"] == replacement["ID"]
    assert schema.get_meta(projection._folder_meta_key(schema.KIND_ARTIST)) == replacement["ID"]
    assert fake.calls["get_playlist_by_path"] == 1


def test_renamed_folder_is_kept_by_id_never_duplicated() -> None:
    """Renaming keeps the row id, so the id-map must follow the rename, not the name."""
    library = _library("Boys Noize")
    fake = FakeRekordbox(library)
    _favourite("Boys Noize")
    projection.sync(fake)
    folder_id = fake.folders("Artists")[0]["ID"]
    fake.nodes[folder_id]["Name"] = "Lieblingskünstler"

    report = projection.sync(fake)

    assert report["folder_id"] == folder_id
    assert report["created"] is False and report["adopted"] is False
    assert fake.calls["create_folder"] == 1, "a second folder was created after a rename"


def test_a_playlist_named_artists_at_root_is_not_adopted_as_the_folder() -> None:
    library = _library("Boys Noize")
    fake = FakeRekordbox(library)
    fake.create_playlist("Artists", "ROOT")  # a plain playlist, not a folder
    _favourite("Boys Noize")

    report = projection.sync(fake)

    assert report["created"] is True and report["adopted"] is False
    assert len(fake.folders("Artists")) == 1
    assert fake.nodes[report["folder_id"]]["Type"] == "0"


# --------------------------------------------------------------------------- guards


def test_run_aborts_when_rekordbox_is_running(monkeypatch) -> None:
    library = _library("Boys Noize")
    fake = FakeRekordbox(library)
    _favourite("Boys Noize")
    monkeypatch.setattr(projection, "_rekordbox_running", lambda: True)

    with pytest.raises(projection.RekordboxRunningError):
        projection.sync(fake)

    assert fake.nodes == {}, "a refused run still wrote to master.db"
    assert fake.calls["create_folder"] == 0 and fake.calls["create_playlist"] == 0


def test_rekordbox_opened_mid_run_aborts_before_the_next_write(monkeypatch) -> None:
    library = _library("Boys Noize", "Helena Hauff", "Marie Davidson")
    fake = FakeRekordbox(library)
    for name in ("Boys Noize", "Helena Hauff", "Marie Davidson"):
        _favourite(name)
    checks = {"n": 0}

    def _running() -> bool:
        checks["n"] += 1
        return checks["n"] > 3  # run start + folder + first artist, then Rekordbox opens

    monkeypatch.setattr(projection, "_rekordbox_running", _running)

    report = projection.sync(fake)

    assert report["aborted"] is True
    assert report["playlists_created"] == 1, "kept writing after Rekordbox opened"
    assert len(fake.children_of(report["folder_id"])) == 1
    assert list(_artist_playlists(fake).values()) == [["1"]], "aborted mid-artist"
    assert any("Rekordbox" in e["error"] for e in report["errors"])


def test_rekordbox_is_rechecked_once_per_artist(monkeypatch) -> None:
    """Per artist, not per write — and not skipped either."""
    library = _library("Boys Noize", "Helena Hauff")
    fake = FakeRekordbox(library)
    _favourite("Boys Noize")
    _favourite("Helena Hauff")
    checks = {"n": 0}

    def _running() -> bool:
        checks["n"] += 1
        return False

    monkeypatch.setattr(projection, "_rekordbox_running", _running)
    projection.sync(fake)

    # run start + folder create + one per artist
    assert checks["n"] == 4


def test_missing_playlist_xml_refuses_to_run() -> None:
    library = _library("Boys Noize")
    fake = FakeRekordbox(library, xml_path=None)
    _favourite("Boys Noize")

    with pytest.raises(projection.ProjectionUnavailable):
        projection.sync(fake)

    assert fake.nodes == {}


def test_facade_without_the_passthrough_refuses_to_run() -> None:
    class Old:
        """A facade from before the playlist-XML passthrough existed."""

        artists = ()

    with pytest.raises(projection.ProjectionUnavailable):
        projection.sync(Old())


# --------------------------------------------------------------------------- dry run


def test_dry_run_writes_nothing_and_reports_the_plan() -> None:
    library = _library("Boys Noize", "Boys Noize", "Helena Hauff")
    fake = FakeRekordbox(library)
    cid = _favourite("Boys Noize")
    _favourite("Helena Hauff")

    report = projection.sync(fake, dry_run=True)

    assert report["dry_run"] is True
    assert report["created"] is True and report["playlists_created"] == 2
    assert report["tracks_added"] == 3 and report["tracks_removed"] == 0
    assert fake.nodes == {}, "dry_run created playlists"
    assert fake.calls["add_track_to_playlist"] == 0
    assert schema.get_meta(projection._folder_meta_key(schema.KIND_ARTIST)) is None
    assert schema.get_projection(cid) is None, "dry_run wrote the sidecar id-map"


def test_dry_run_diffs_an_existing_projection_without_writing() -> None:
    library = _library("Boys Noize", "Boys Noize")
    fake = FakeRekordbox(library)
    _favourite("Boys Noize")
    projection.sync(fake)
    del library.tracks["2"]
    library.tracks["9"] = {"ID": "9", "Artist": "Boys Noize", "Artwork": ""}
    library._finalize_ui_metadata()
    fake.reset_calls()

    report = projection.sync(fake, dry_run=True)

    assert report["tracks_added"] == 1 and report["tracks_removed"] == 1
    assert report["playlists_updated"] == 1
    assert fake.calls["add_track_to_playlist"] == 0
    assert fake.calls["remove_track_from_playlist"] == 0


def test_dry_run_is_allowed_while_rekordbox_is_running(monkeypatch) -> None:
    library = _library("Boys Noize")
    fake = FakeRekordbox(library)
    _favourite("Boys Noize")
    monkeypatch.setattr(projection, "_rekordbox_running", lambda: True)

    report = projection.sync(fake, dry_run=True)

    assert report["playlists_created"] == 1
    assert fake.nodes == {}


# --------------------------------------------------------------------------- bookkeeping


def test_last_projected_at_is_recorded_per_artist() -> None:
    library = _library("Boys Noize")
    fake = FakeRekordbox(library)
    cid = _favourite("Boys Noize")

    projection.sync(fake)

    row = schema.get_projection(cid)
    assert row["rb_playlist_id"] in fake.nodes
    assert row["rb_uuid"] == fake.nodes[row["rb_playlist_id"]]["UUID"]
    assert row["last_projected_at"]


def test_favourite_without_local_tracks_is_skipped_not_projected() -> None:
    library = _library("Boys Noize")
    fake = FakeRekordbox(library)
    _favourite("Boys Noize")
    _favourite("Someone With Nothing Yet")

    report = projection.sync(fake)

    assert [s["name"] for s in report["skipped"]] == ["Someone With Nothing Yet"]
    assert [s["reason"] for s in report["skipped"]] == [projection.SKIP_NO_LOCAL_TRACKS]
    assert list(_artist_playlists(fake)) == ["Boys Noize"]


def test_no_favourites_writes_nothing() -> None:
    fake = FakeRekordbox(_library("Boys Noize"))

    report = projection.sync(fake)

    assert report["artists"] == 0 and report["folder_id"] is None
    assert fake.nodes == {}, "an empty favourites list still created the folder"


def test_a_failing_artist_does_not_lose_the_rest_of_the_run(monkeypatch) -> None:
    library = _library("Boys Noize", "Helena Hauff")
    fake = FakeRekordbox(library)
    _favourite("Boys Noize")
    _favourite("Helena Hauff")
    real_add = fake.add_track_to_playlist

    def _explode(pid: str, tid: str) -> bool:
        if tid == "1":
            raise RuntimeError("db locked")
        return real_add(pid, tid)

    monkeypatch.setattr(fake, "add_track_to_playlist", _explode)

    report = projection.sync(fake)

    assert len(report["errors"]) == 1
    assert report["errors"][0]["name"] == "Boys Noize"
    assert report["aborted"] is False
    assert _artist_playlists(fake)["Helena Hauff"] == ["2"]


def test_a_failed_diff_still_stores_the_playlist_id(monkeypatch) -> None:
    """Otherwise the next run re-creates a playlist that already exists."""
    library = _library("Boys Noize")
    fake = FakeRekordbox(library)
    cid = _favourite("Boys Noize")
    real_add = fake.add_track_to_playlist
    broken = {"yes": True}

    def _add(pid: str, tid: str) -> bool:
        if broken["yes"]:
            raise RuntimeError("boom")
        return real_add(pid, tid)

    monkeypatch.setattr(fake, "add_track_to_playlist", _add)

    first = projection.sync(fake)
    stored = schema.get_projection(cid)["rb_playlist_id"]
    broken["yes"] = False
    second = projection.sync(fake)

    assert first["errors"] and stored in fake.nodes
    assert second["playlists_created"] == 0, "the half-projected playlist was duplicated"
    assert schema.get_projection(cid)["rb_playlist_id"] == stored
    assert fake.songs[stored] == ["1"], "the retry did not fill the playlist"


# --------------------------------------------------------------------------- status


def test_status_reports_the_id_map_and_verifies_it() -> None:
    library = _library("Boys Noize", "Helena Hauff")
    fake = FakeRekordbox(library)
    cid = _favourite("Boys Noize")
    _favourite("Helena Hauff")
    projection.sync(fake)
    fake.drop(schema.get_projection(cid)["rb_playlist_id"])

    state = projection.status(fake)

    assert state["folder_name"] == "Artists" and state["folder_exists"] is True
    assert state["favourites"] == 2 and state["projected"] == 1 and state["pending"] == 1
    by_name = {a["name"]: a for a in state["artists"]}
    assert by_name["Boys Noize"]["exists"] is False
    assert by_name["Helena Hauff"]["exists"] is True
    assert by_name["Helena Hauff"]["local_tracks"] == 1
    assert state["playlist_xml"] == XML_PATH


def test_every_master_db_write_goes_through_the_locked_facade() -> None:
    """`db.active_db.<mutator>` bypasses `_db_write_lock` — an AST walk, not a habit."""
    import ast
    import inspect

    from app.database import RekordboxDB

    tree = ast.parse(inspect.getsource(projection))
    attributes = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "active_db" not in attributes, "projection reached past the facade"

    for name in (
        "create_folder",
        "create_playlist",
        "add_track_to_playlist",
        "remove_track_from_playlist",
    ):
        assert name in attributes, f"{name} is no longer the write path — re-check the lock"
        # `_serialised` wraps with functools.wraps, so __wrapped__ is the proof.
        assert hasattr(getattr(RekordboxDB, name), "__wrapped__"), (
            f"facade.{name} left the auto-serialised list; the projection would write "
            "to master.db without holding _db_write_lock"
        )


def test_status_without_a_library_still_renders() -> None:
    _favourite("Boys Noize")

    state = projection.status(None)

    assert state["favourites"] == 1
    assert state["folder_exists"] is False
    assert state["artists"][0]["local_tracks"] == 0
    assert state["artists"][0]["rb_playlist_id"] is None
