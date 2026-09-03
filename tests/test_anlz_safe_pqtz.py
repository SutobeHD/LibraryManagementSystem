"""Beat-grid extraction in `app.anlz_safe`.

Guards the regression that made the whole feature silent: with the old
`rbox.Anlz` path the parser reported "no PQTZ" for every file of a
Rekordbox 6.8.4 library, so `load_all_beatgrids` returned `hits=0` for
4719 tracks without a single error line. These tests round-trip a DAT
built by our own writer, so a parser swap that stops reading beats
fails here instead of in the field.
"""

from __future__ import annotations

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

pytest.importorskip("pyrekordbox", reason="ANLZ parser not installed")

from app.anlz_safe import _pqtz_entries_from_dat  # noqa: E402
from app.anlz_writer import build_dat  # noqa: E402

BPM = 128.0
BEAT_MS = 60_000.0 / BPM  # 468.75 ms


def _beats(count: int = 8) -> list[dict[str, int]]:
    return [
        {
            "beat_number": (i % 4) + 1,
            "tempo": int(round(BPM * 100)),
            "time_ms": int(round(i * BEAT_MS)),
        }
        for i in range(count)
    ]


def _write_dat(tmp_path, beats) -> str:
    data = build_dat(
        track_path="C:/music/track.mp3",
        beats=beats,
        pvbr=[0] * 400,
        pwav=[0] * 400,
        pwv2=[0] * 100,
    )
    path = os.path.join(str(tmp_path), "ANLZ0000.DAT")
    with open(path, "wb") as fh:
        fh.write(data)
    return path


def test_reads_every_beat_with_time_bpm_and_beat_number(tmp_path):
    entries = _pqtz_entries_from_dat(_write_dat(tmp_path, _beats(8)))

    assert entries is not None, "writer-produced PQTZ must be readable"
    assert len(entries) == 8
    assert [e["beat"] for e in entries] == [1, 2, 3, 4, 1, 2, 3, 4]
    assert all(e["bpm"] == pytest.approx(BPM) for e in entries)
    # seconds, not milliseconds
    assert entries[0]["time"] == pytest.approx(0.0)
    assert entries[4]["time"] == pytest.approx(4 * BEAT_MS / 1000.0, abs=0.002)


def test_beat_numbers_are_not_flattened_to_one(tmp_path):
    """The pre-fix code hardcoded `beat: 1`, which loses downbeats."""
    entries = _pqtz_entries_from_dat(_write_dat(tmp_path, _beats(8)))

    assert entries is not None
    assert {e["beat"] for e in entries} == {1, 2, 3, 4}


def test_empty_grid_returns_none(tmp_path):
    assert _pqtz_entries_from_dat(_write_dat(tmp_path, [])) is None


def test_garbage_file_returns_none_instead_of_raising(tmp_path):
    path = os.path.join(str(tmp_path), "garbage.DAT")
    with open(path, "wb") as fh:
        fh.write(b"PMAI" + os.urandom(512))

    assert _pqtz_entries_from_dat(path) is None


def test_missing_file_returns_none(tmp_path):
    assert _pqtz_entries_from_dat(os.path.join(str(tmp_path), "nope.DAT")) is None


def test_recursion_limit_is_restored(tmp_path):
    before = sys.getrecursionlimit()
    _pqtz_entries_from_dat(_write_dat(tmp_path, _beats(4)))

    assert sys.getrecursionlimit() == before
