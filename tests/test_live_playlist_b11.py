"""Live playlist operations end to end against an rbox stand-in (B11, 0.1 core-loop test).

* add / remove never updated the ``playlists_tracks`` cache that
  ``get_playlist_tracks`` serves from: an added track stayed invisible until reload;
* reorder was remove + add (always to the end) and still answered success;
* ``move_playlist`` failed into an empty folder ("Invalid sequence number: 0") and
  back to ROOT (rbox reads ``parent_id=None`` as "keep the current parent").

``_FakeRbox`` reproduces the rbox 0.1.7 behaviour measured on a master.db copy on
2026-11-14: seq is a VALUE shifted like Rekordbox does, an explicit seq above the row
count is refused, ``seq=None`` appends, ``parent_id=None`` keeps the parent and ROOT
is spelled "root".
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.live_database import LiveRekordboxDB


class _FakeRbox:
    def __init__(self) -> None:
        self.nodes: dict[str, SimpleNamespace] = {}
        self.songs: dict[str, SimpleNamespace] = {}
        self._next = 1000

    def _id(self) -> str:
        self._next += 1
        return str(self._next)

    # --- tree ----------------------------------------------------------------
    def add_node(self, nid: str, parent: str, seq: int, folder: bool = False) -> None:
        self.nodes[nid] = SimpleNamespace(
            id=nid, name=nid, parent_id=parent, seq=seq, attribute=1 if folder else 0
        )

    def get_playlists(self) -> list[SimpleNamespace]:
        return list(self.nodes.values())

    def get_playlist_children(self, parent: str) -> list[SimpleNamespace]:
        return [n for n in self.nodes.values() if n.parent_id == parent]

    def move_playlist(self, nid: str, seq: int | None = None, parent_id: str | None = None):
        node = self.nodes[nid]
        if parent_id is not None and parent_id != node.parent_id:
            old_parent = node.parent_id
            for n in self.get_playlist_children(old_parent):
                if n.seq > node.seq:
                    n.seq -= 1
            dest = self.get_playlist_children(parent_id)
            if seq is not None and not 1 <= seq <= len(dest):
                raise RuntimeError(f"Invalid sequence number: {seq} (count: {len(dest)})")
            node.parent_id = parent_id
            node.seq = max((n.seq for n in dest), default=0) + 1
            if seq is None:
                return
        if seq is None:
            return
        siblings = self.get_playlist_children(node.parent_id)
        if not 1 <= seq <= len(siblings):
            raise RuntimeError(f"Invalid sequence number: {seq} (count: {len(siblings)})")
        self._shift(siblings, node, seq, "seq")

    @staticmethod
    def _shift(rows: list[SimpleNamespace], row: SimpleNamespace, new: int, attr: str) -> None:
        old = getattr(row, attr)
        for r in rows:
            v = getattr(r, attr)
            if r is row:
                continue
            if new > old and old < v <= new:
                setattr(r, attr, v - 1)
            elif new < old and new <= v < old:
                setattr(r, attr, v + 1)
        setattr(row, attr, new)

    # --- songs ---------------------------------------------------------------
    def get_playlist_songs(self, pid: str) -> list[SimpleNamespace]:
        rows = [s for s in self.songs.values() if s.playlist_id == str(pid)]
        return sorted(rows, key=lambda s: s.track_no)

    def create_playlist_song(self, pid: str, cid: str) -> SimpleNamespace:
        n = len(self.get_playlist_songs(pid))
        row = SimpleNamespace(id=self._id(), playlist_id=str(pid), content_id=cid, track_no=n + 1)
        self.songs[row.id] = row
        return row

    def delete_playlist_song(self, sid: str) -> None:
        row = self.songs.pop(str(sid))
        for s in self.get_playlist_songs(row.playlist_id):
            if s.track_no > row.track_no:
                s.track_no -= 1

    def move_playlist_song(self, sid: str, seq: int) -> None:
        row = self.songs[str(sid)]
        rows = self.get_playlist_songs(row.playlist_id)
        if not 1 <= seq <= len(rows):
            raise RuntimeError(f"Invalid sequence number: {seq} (count: {len(rows)})")
        self._shift(rows, row, seq, "track_no")


@pytest.fixture
def rb(monkeypatch: pytest.MonkeyPatch) -> _FakeRbox:
    handle = _FakeRbox()
    monkeypatch.setattr(LiveRekordboxDB, "db", property(lambda self: handle))
    return handle


@pytest.fixture
def live(rb: _FakeRbox) -> LiveRekordboxDB:
    # Root: gaps and duplicates in seq like a real library (1, 2, 5, 6, 6).
    for nid, seq in (("A", 1), ("B", 2), ("C", 5), ("D", 6), ("E", 6)):
        rb.add_node(nid, "root", seq)
    rb.add_node("F", "root", 7, folder=True)  # empty folder
    rb.add_node("G", "root", 8, folder=True)
    rb.add_node("P", "G", 1)
    db = LiveRekordboxDB("does-not-exist.db")
    db._refresh_playlist_nodes()
    db.tracks = {cid: {"ID": cid, "Title": cid} for cid in ("t1", "t2", "t3", "t4")}
    for cid in ("t1", "t2", "t3"):
        rb.create_playlist_song("A", cid)
    db.playlists_tracks.clear()
    db.playlists_tracks["A"] = ["t1", "t2", "t3"]
    return db


def _order(rb: _FakeRbox, parent: str) -> list[str]:
    return [n.id for n in sorted(rb.get_playlist_children(parent), key=lambda n: n.seq)]


def _ids(tracks: list[dict]) -> list[str]:
    return [t["ID"] for t in tracks]


# --- tracks -----------------------------------------------------------------------


def test_added_track_shows_up_without_a_reload(live: LiveRekordboxDB) -> None:
    assert live.add_track_to_playlist("A", "t4") is True
    assert _ids(live.get_playlist_tracks("A")) == ["t1", "t2", "t3", "t4"]


def test_removed_track_disappears_without_a_reload(live: LiveRekordboxDB) -> None:
    assert live.remove_track_from_playlist("A", "t2") is True
    assert _ids(live.get_playlist_tracks("A")) == ["t1", "t3"]


@pytest.mark.parametrize(
    ("track", "index", "expected"),
    [
        ("t3", 0, ["t3", "t1", "t2"]),
        ("t1", 1, ["t2", "t1", "t3"]),
        ("t1", 2, ["t2", "t3", "t1"]),
        ("t2", 0, ["t2", "t1", "t3"]),
        ("t3", 1, ["t1", "t3", "t2"]),
        ("t2", 1, ["t1", "t2", "t3"]),  # no-op
        ("t1", 99, ["t2", "t3", "t1"]),  # clamped like the XML backend
        ("t3", -5, ["t3", "t1", "t2"]),
    ],
)
def test_reorder_puts_the_track_at_the_target_index(
    live: LiveRekordboxDB, rb: _FakeRbox, track: str, index: int, expected: list[str]
) -> None:
    assert live.reorder_playlist_track("A", track, index) is True
    assert [s.content_id for s in rb.get_playlist_songs("A")] == expected
    assert _ids(live.get_playlist_tracks("A")) == expected


def test_reorder_of_a_track_not_in_the_playlist_is_refused(live: LiveRekordboxDB) -> None:
    assert live.reorder_playlist_track("A", "t4", 0) is False


# --- tree -------------------------------------------------------------------------


def test_move_into_an_empty_folder(live: LiveRekordboxDB, rb: _FakeRbox) -> None:
    assert live.move_playlist("A", None, target_id="F", position="inside") is True
    assert rb.nodes["A"].parent_id == "F"
    assert next(p for p in live.playlists if p["ID"] == "A")["ParentID"] == "F"


def test_move_back_to_root(live: LiveRekordboxDB, rb: _FakeRbox) -> None:
    assert live.move_playlist("P", "ROOT") is True
    assert rb.nodes["P"].parent_id == "root"
    assert next(p for p in live.playlists if p["ID"] == "P")["ParentID"] == "ROOT"


def test_move_back_to_root_by_dropping_onto_root(live: LiveRekordboxDB, rb: _FakeRbox) -> None:
    assert live.move_playlist("P", None, target_id="ROOT", position="inside") is True
    assert rb.nodes["P"].parent_id == "root"


@pytest.mark.parametrize(
    ("pid", "target", "position", "expected"),
    [
        ("E", "B", "before", ["A", "E", "B", "C", "D"]),
        ("A", "C", "after", ["B", "C", "A", "D", "E"]),
        ("A", "C", "before", ["B", "A", "C", "D", "E"]),
        ("D", "A", "before", ["D", "A", "B", "C", "E"]),
    ],
)
def test_move_next_to_a_sibling_with_gappy_seqs(
    live: LiveRekordboxDB,
    rb: _FakeRbox,
    pid: str,
    target: str,
    position: str,
    expected: list[str],
) -> None:
    assert live.move_playlist(pid, "ROOT", target_id=target, position=position) is True
    order = [n for n in _order(rb, "root") if n not in ("F", "G")]
    assert order == expected


def test_move_from_a_folder_next_to_a_root_sibling(live: LiveRekordboxDB, rb: _FakeRbox) -> None:
    assert live.move_playlist("P", "ROOT", target_id="B", position="after") is True
    assert rb.nodes["P"].parent_id == "root"
    order = _order(rb, "root")
    assert order.index("P") == order.index("B") + 1


def test_moving_a_folder_into_itself_is_refused(live: LiveRekordboxDB, rb: _FakeRbox) -> None:
    assert live.move_playlist("G", None, target_id="G", position="inside") is False
    assert rb.nodes["G"].parent_id == "root"
