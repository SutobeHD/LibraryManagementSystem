"""The USB PDB writers must never leave a truncated file behind.

`export.pdb` was written with `Path.write_bytes`, which truncates the
destination and then fills it. On removable media that is the worst shape
available: pull the stick or lose power part-way through and the CDJ refuses
the whole library — and the previous, working file is already gone, so there
is nothing to fall back to.

These tests interrupt the write at the point where truncate-in-place would
have destroyed the old file, and assert the old file survives byte-for-byte.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app import usb_pdb

TRACKS = [
    {
        "id": i,
        "title": f"Track {i}",
        "artist_id": 1,
        "album_id": 1,
        "genre_id": 0,
        "key_id": 0,
        "label_id": 0,
        "color_id": 0,
        "artwork_id": 0,
        "bpm": 128.0,
        "length_seconds": 300,
        "bitrate": 320,
        "file_path": f"/CONTENTS/t{i}.mp3",
        "file_name": f"t{i}.mp3",
        "date_added": "2026-08-31",
        "comment": "",
    }
    for i in range(1, 5)
]


def _write(usb_root: Path, tracks):
    return usb_pdb.write_export_pdb(
        str(usb_root),
        contents=tracks,
        artists={1: "A"},
        albums={1: "B"},
        keys={},
    )


class TestAtomicHelper:
    def test_creates_the_file(self, tmp_path: Path):
        target = tmp_path / "export.pdb"
        usb_pdb._atomic_write_bytes(target, b"hello")
        assert target.read_bytes() == b"hello"

    def test_leaves_no_temp_file_behind(self, tmp_path: Path):
        target = tmp_path / "export.pdb"
        usb_pdb._atomic_write_bytes(target, b"hello")
        assert list(tmp_path.glob("*.tmp")) == []

    def test_failed_write_preserves_the_previous_file(self, tmp_path: Path, monkeypatch):
        """The regression: a failure mid-write must not destroy the old file."""
        target = tmp_path / "export.pdb"
        target.write_bytes(b"PREVIOUS-GOOD-LIBRARY")

        def boom(fd):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(os, "fsync", boom)
        with pytest.raises(OSError):
            usb_pdb._atomic_write_bytes(target, b"NEW" * 100)

        assert target.read_bytes() == b"PREVIOUS-GOOD-LIBRARY"
        assert list(tmp_path.glob("*.tmp")) == [], "temp file not cleaned up"

    def test_replaces_content_completely(self, tmp_path: Path):
        """A shorter payload must not leave a tail of the old file."""
        target = tmp_path / "export.pdb"
        target.write_bytes(b"X" * 5000)
        usb_pdb._atomic_write_bytes(target, b"short")
        assert target.read_bytes() == b"short"


class TestExportPdbWriter:
    def test_writes_a_valid_file(self, tmp_path: Path):
        out = _write(tmp_path, TRACKS)
        assert out is not None
        assert Path(out).exists()
        assert Path(out).stat().st_size > 0

    def test_rewrite_does_not_go_through_truncate_in_place(self, tmp_path: Path, monkeypatch):
        """Interrupt a REWRITE and the stick must still hold the old library."""
        first = _write(tmp_path, TRACKS)
        assert first is not None
        target = Path(first)
        original = target.read_bytes()
        assert len(original) > 0

        def boom(fd):
            raise OSError(5, "Input/output error — stick pulled")

        monkeypatch.setattr(os, "fsync", boom)
        # write_export_pdb catches and returns None rather than raising.
        assert _write(tmp_path, TRACKS + TRACKS) is None
        assert target.read_bytes() == original, "previous export.pdb was damaged"
        assert list(target.parent.glob("*.tmp")) == []

    def test_second_write_actually_updates(self, tmp_path: Path):
        first = _write(tmp_path, TRACKS)
        original = Path(first).read_bytes()
        second = _write(tmp_path, TRACKS + TRACKS)
        assert second is not None
        assert Path(second).read_bytes() != original
