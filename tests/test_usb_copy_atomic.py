"""USB audio copies must not leave a truncated file that never self-heals.

`shutil.copy2` straight to the destination creates the file immediately and
fills it progressively. Interrupt it and a truncated track sits on the stick —
and the caller's `if not dest_path.exists()` guard then treated it as
already-copied on every later sync. The CDJ plays a track that stops early,
forever, and no amount of re-syncing fixes it.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from app import usb_one_library as uol

PAYLOAD = b"ID3\x04\x00" + b"\xaa" * 8192


@pytest.fixture
def src(tmp_path: Path) -> Path:
    f = tmp_path / "source.mp3"
    f.write_bytes(PAYLOAD)
    return f


class TestAtomicCopy:
    def test_copies_the_bytes(self, src: Path, tmp_path: Path):
        dst = tmp_path / "usb" / "track.mp3"
        dst.parent.mkdir()
        uol._copy_file_atomic(src, dst)
        assert dst.read_bytes() == PAYLOAD

    def test_leaves_no_part_file(self, src: Path, tmp_path: Path):
        dst = tmp_path / "usb" / "track.mp3"
        dst.parent.mkdir()
        uol._copy_file_atomic(src, dst)
        assert list(dst.parent.glob("*.part")) == []

    def test_interrupted_copy_leaves_no_destination(self, src: Path, tmp_path: Path, monkeypatch):
        """The regression: a partial copy must not masquerade as a done one."""
        dst = tmp_path / "usb" / "track.mp3"
        dst.parent.mkdir()

        def boom(s, d, *a, **k):
            Path(d).write_bytes(PAYLOAD[:100])  # partial write, then failure
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(shutil, "copy2", boom)
        with pytest.raises(OSError):
            uol._copy_file_atomic(src, dst)

        assert not dst.exists(), "a truncated file was left where the track belongs"
        assert list(dst.parent.glob("*.part")) == []

    def test_interrupted_copy_does_not_destroy_an_existing_track(
        self, src: Path, tmp_path: Path, monkeypatch
    ):
        dst = tmp_path / "usb" / "track.mp3"
        dst.parent.mkdir()
        dst.write_bytes(b"PREVIOUSLY-SYNCED-TRACK")

        def boom(s, d, *a, **k):
            Path(d).write_bytes(PAYLOAD[:100])
            raise OSError(5, "Input/output error")

        monkeypatch.setattr(shutil, "copy2", boom)
        with pytest.raises(OSError):
            uol._copy_file_atomic(src, dst)
        assert dst.read_bytes() == b"PREVIOUSLY-SYNCED-TRACK"


class TestNeedsCopy:
    def test_missing_destination_needs_copy(self, src: Path, tmp_path: Path):
        assert uol._needs_copy(src, tmp_path / "nope.mp3") is True

    def test_identical_destination_is_skipped(self, src: Path, tmp_path: Path):
        dst = tmp_path / "track.mp3"
        dst.write_bytes(PAYLOAD)
        assert uol._needs_copy(src, dst) is False

    def test_truncated_destination_is_re_copied(self, src: Path, tmp_path: Path):
        """Heals sticks already damaged by the old truncate-in-place path —
        existence alone would skip them forever."""
        dst = tmp_path / "track.mp3"
        dst.write_bytes(PAYLOAD[:100])
        assert uol._needs_copy(src, dst) is True

    def test_unreadable_source_errs_toward_copying(self, tmp_path: Path):
        assert uol._needs_copy(tmp_path / "gone.mp3", tmp_path / "also-gone.mp3") is True


class TestEndToEndHealing:
    def test_a_truncated_track_is_repaired_on_the_next_sync(self, src: Path, tmp_path: Path):
        dst = tmp_path / "usb" / "track.mp3"
        dst.parent.mkdir()
        dst.write_bytes(PAYLOAD[:100])  # damage from a previous interrupted sync

        if uol._needs_copy(src, dst):
            uol._copy_file_atomic(src, dst)

        assert dst.read_bytes() == PAYLOAD
