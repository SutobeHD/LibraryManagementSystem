"""Pure-Python ANLZ path resolution in `app.anlz_safe`.

These replace `rbox.MasterDb.get_content_anlz_dir()` and
`get_content_anlz_paths()`, which call `unwrap()` on the AnalysisDataPath
column and ABORT the process (Rust panic, uncatchable by `try/except`)
for any track Rekordbox has never analysed. Measured on the live library:
that abort cost 46 process kills per full load, exhausted the panic budget
and left 1251 of 4719 tracks without a beat grid.

The stubs below stand in for `rbox.MasterDb` so the contract is pinned
without needing rbox, a Rekordbox install, or the user's library.
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.anlz_safe import resolve_anlz_dir, resolve_anlz_paths  # noqa: E402

SHARE = r"C:\Users\tb\AppData\Roaming\Pioneer\rekordbox\share"
REL = "/PIONEER/USBANLZ/44d/00cc2-7321-4a2e-88d7-fbcc7074c1b3/ANLZ0000.DAT"


class FakeContent:
    def __init__(self, cid, analysis_data_path):
        self.id = cid
        self.analysis_data_path = analysis_data_path


class FakeDb:
    """Only the two members the resolvers are allowed to touch."""

    def __init__(self, contents):
        self._contents = contents

    def share_directory(self):  # a method on rbox.MasterDb, not a property
        return SHARE

    def get_contents(self):
        return list(self._contents)

    def get_content_by_id(self, cid):
        for c in self._contents:
            if str(c.id) == str(cid):
                return c
        return None


def test_joins_share_dir_with_the_relative_path():
    db = FakeDb([FakeContent(1, REL)])
    out = _resolve_with(db)

    assert out["1"]["DAT"] == os.path.join(
        SHARE, "PIONEER", "USBANLZ", "44d", "00cc2-7321-4a2e-88d7-fbcc7074c1b3", "ANLZ0000.DAT"
    )


def test_leading_slash_does_not_discard_the_share_root():
    """`Path("C:/share") / "/PIONEER/x"` yields "C:/PIONEER/x" — the bug this guards."""
    db = FakeDb([FakeContent(1, REL)])
    out = _resolve_with(db)

    assert out["1"]["DAT"].startswith(SHARE)


def test_sibling_keys_use_rbox_spelling_and_extensions():
    db = FakeDb([FakeContent(1, REL)])
    out = _resolve_with(db)

    assert set(out["1"]) == {"DAT", "EXT", "EX2"}, "rbox spells the third key EX2"
    assert out["1"]["EXT"].endswith(".EXT")
    assert out["1"]["EX2"].endswith(".2EX"), "key EX2 addresses the .2EX file"


def test_unanalysed_rows_are_skipped_not_resolved():
    """Empty path == exactly the set that aborted the old rbox call."""
    db = FakeDb([FakeContent(1, REL), FakeContent(2, ""), FakeContent(3, None)])
    out = _resolve_with(db)

    assert set(out) == {"1"}


def test_track_ids_filter_restricts_the_result():
    db = FakeDb([FakeContent(1, REL), FakeContent(2, REL)])

    assert set(_resolve_with(db, ["2"])) == {"2"}


def test_resolve_dir_returns_the_containing_directory():
    db = FakeDb([FakeContent(1, REL)])

    assert resolve_anlz_dir(db, "1") == os.path.join(
        SHARE, "PIONEER", "USBANLZ", "44d", "00cc2-7321-4a2e-88d7-fbcc7074c1b3"
    )


def test_resolve_dir_returns_none_for_an_unanalysed_track():
    """The case that used to kill the backend process."""
    db = FakeDb([FakeContent(1, "")])

    assert resolve_anlz_dir(db, "1") is None


def test_resolve_dir_returns_none_for_an_unknown_track():
    assert resolve_anlz_dir(FakeDb([]), "999") is None


def test_resolve_dir_survives_a_raising_db():
    class Raising(FakeDb):
        def get_content_by_id(self, cid):
            raise RuntimeError("db closed")

    assert resolve_anlz_dir(Raising([]), "1") is None


def _resolve_with(db, track_ids=None):
    """Call resolve_anlz_paths with `rbox.MasterDb` swapped for the stub."""
    import types

    fake_rbox = types.ModuleType("rbox")
    fake_rbox.MasterDb = lambda _path: db
    saved = sys.modules.get("rbox")
    sys.modules["rbox"] = fake_rbox
    try:
        return resolve_anlz_paths("ignored.db", track_ids)
    finally:
        if saved is None:
            sys.modules.pop("rbox", None)
        else:
            sys.modules["rbox"] = saved
