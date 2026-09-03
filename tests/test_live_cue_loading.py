"""Cue loading in `app.live_database`.

`rbox.get_cues()` reads djmdCue in one batch, so a single row with a NULL
in a non-null column fails the whole library: on the dev machine every
one of 4719 tracks loaded zero cues with only a single ERROR line to show
for it. The fallback reads Rekordbox's own per-track JSON mirror
(djmdContentCue) instead, which recovers 852 cues across 746 tracks.

Also pins the Num convention. `djmdCue.Kind` counts 0 = memory cue,
1..N = hot cue slot, while POSITION_MARK (xml_generator.py:56) and the
timeline (TimelineCanvas.jsx:416) read -1 = memory cue, 0-7 = hot cue
A-H. Passing Kind through as Num would label every memory cue "Hot Cue A"
and shift A-H by one at USB/XML export.
"""

from __future__ import annotations

import json
import os
import sys
import threading

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.live_database import LiveRekordboxDB  # noqa: E402


class FakeCue:
    def __init__(self, cid, ident="1", hot_cue=0, in_msec=0, out_msec=-1, commnt=""):
        self.content_id = cid
        self.id = ident
        self.hot_cue = hot_cue
        self.in_msec = in_msec
        self.out_msec = out_msec
        self.commnt = commnt


class FakeContentCueRow:
    def __init__(self, content_id, entries, raw=None):
        self.id = f"row-{content_id}"
        self.content_id = content_id
        self.cues = raw if raw is not None else json.dumps(entries)


class FakeDb:
    def __init__(self, cues=None, content_cues=None, cues_raises=False):
        self._cues = cues or []
        self._content_cues = content_cues or []
        self._cues_raises = cues_raises

    def get_cues(self):
        if self._cues_raises:
            raise RuntimeError("Diesel error: Unexpected null for non-null column")
        return list(self._cues)

    def get_content_cues(self):
        return list(self._content_cues)


def _db(fake, track_ids=("100", "200")):
    """A LiveRekordboxDB with just the state the cue loader touches.

    `.db` is a thread-local property, so the stub goes into the connection
    slot it reads rather than onto the instance.
    """
    inst = LiveRekordboxDB.__new__(LiveRekordboxDB)
    inst._local = threading.local()
    inst._local.conn = fake
    inst.tracks = {tid: {"ID": tid} for tid in track_ids}
    return inst


def _entry(content_id="100", ident="1", kind=1, in_msec=1000, out_msec=-1, comment=""):
    return {
        "ID": ident,
        "ContentID": content_id,
        "Kind": kind,
        "InMsec": in_msec,
        "OutMsec": out_msec,
        "Comment": comment,
    }


def test_uses_djmd_cue_when_it_is_readable():
    inst = _db(FakeDb(cues=[FakeCue("100", ident="7", hot_cue=1, in_msec=500)]))
    inst._load_cues()

    assert [c["ID"] for c in inst.tracks["100"]["Cues"]] == ["7"]
    assert inst.tracks["100"]["Cues"][0]["InMsec"] == 500


def test_falls_back_to_the_mirror_when_djmd_cue_raises():
    """The real-world case: one bad row kills the whole batch read."""
    inst = _db(
        FakeDb(
            cues_raises=True,
            content_cues=[FakeContentCueRow("100", [_entry(), _entry(ident="2", kind=0)])],
        )
    )
    inst._load_cues()

    assert len(inst.tracks["100"]["Cues"]) == 2


def test_fallback_warns_that_it_may_under_report(caplog):
    inst = _db(FakeDb(cues_raises=True, content_cues=[FakeContentCueRow("100", [_entry()])]))
    with caplog.at_level("WARNING"):
        inst._load_cues()

    assert any("djmdCue unreadable" in r.message for r in caplog.records)


@pytest.mark.parametrize(
    ("kind", "expected_num"),
    [(0, -1), (1, 0), (2, 1), (8, 7), (9, 8)],
)
def test_kind_maps_to_the_position_mark_num_convention(kind, expected_num):
    """Kind 0 is a memory cue (-1); hot slot N is Num N-1, i.e. A-H."""
    inst = _db(
        FakeDb(cues_raises=True, content_cues=[FakeContentCueRow("100", [_entry(kind=kind)])])
    )
    inst._load_cues()

    cue = inst.tracks["100"]["Cues"][0]
    assert cue["Num"] == expected_num
    assert cue["Kind"] == kind, "raw Rekordbox value stays available"


def test_out_point_marks_a_loop():
    inst = _db(
        FakeDb(
            cues_raises=True,
            content_cues=[
                FakeContentCueRow("100", [_entry(out_msec=5000), _entry(ident="2", out_msec=-1)])
            ],
        )
    )
    inst._load_cues()

    types = [c["Type"] for c in inst.tracks["100"]["Cues"]]
    assert types == [4, 0], "OutMsec > 0 is a loop (Type 4), otherwise a marker (Type 0)"


def test_cues_land_on_their_own_track():
    inst = _db(
        FakeDb(
            cues_raises=True,
            content_cues=[
                FakeContentCueRow("100", [_entry(content_id="100")]),
                FakeContentCueRow("200", [_entry(content_id="200"), _entry(content_id="200")]),
            ],
        )
    )
    inst._load_cues()

    assert len(inst.tracks["100"]["Cues"]) == 1
    assert len(inst.tracks["200"]["Cues"]) == 2


def test_cue_for_an_unknown_track_is_ignored():
    inst = _db(FakeDb(cues_raises=True, content_cues=[FakeContentCueRow("999", [_entry("999")])]))
    inst._load_cues()

    assert all("Cues" not in t for t in inst.tracks.values())


def test_unparsable_mirror_row_does_not_abort_the_rest():
    inst = _db(
        FakeDb(
            cues_raises=True,
            content_cues=[
                FakeContentCueRow("100", None, raw="{not json"),
                FakeContentCueRow("200", [_entry(content_id="200")]),
            ],
        )
    )
    inst._load_cues()

    assert "Cues" not in inst.tracks["100"]
    assert len(inst.tracks["200"]["Cues"]) == 1


def test_both_sources_failing_is_logged_not_raised(caplog):
    class Broken(FakeDb):
        def get_content_cues(self):
            raise RuntimeError("mirror gone too")

    inst = _db(Broken(cues_raises=True))
    with caplog.at_level("ERROR"):
        inst._load_cues()  # must not raise

    assert any("both sources" in r.message for r in caplog.records)
