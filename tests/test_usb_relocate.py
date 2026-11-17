"""Tests for the USB relocation pass (`app/usb_one_library.py`).

An artist merge (`boys noize` + `Boys Noize` -> one artist) changes only the
destination *path* of an already-exported track. Without this pass the next
export re-copies gigabytes of audio that is already on the stick; with it the
files are moved. Every failure mode here loses user audio if it regresses, so
each one has its own test:

  * a pure rename must copy ZERO bytes,
  * a case-only rename must survive a case-insensitive volume (simulated —
    no real exFAT stick required),
  * a collision must never clobber the file that is already there,
  * a cross-volume move must fall back to copy-and-verify,
  * the source is never deleted before the destination verifies,
  * emptied variant folders are pruned, folders still holding files are not,
  * name + size is never proof — only a content fingerprint moves or deletes,
  * `OneLibraryUsbWriter.sync()`'s own Stage-1b wiring, the configuration
    production actually runs (`audio_copy=True` + a `dest_resolver`).

Everything runs in `tmp_path`. No real USB volume is touched.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import usb_one_library as uol

BLOCK = b"A" * 4096
OTHER = b"B" * 2048


def _write(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


@pytest.fixture
def stick(tmp_path: Path) -> Path:
    """`<tmp>/usb` with an existing (empty) Contents tree."""
    contents = tmp_path / "usb" / "Contents"
    contents.mkdir(parents=True)
    return tmp_path / "usb"


@pytest.fixture
def no_copies(monkeypatch):
    """Fail the test the moment anything tries to copy bytes."""

    def _boom(src, dst):  # pragma: no cover - only runs on regression
        raise AssertionError(f"relocation copied bytes: {src} -> {dst}")

    monkeypatch.setattr(uol, "_copy_file_atomic", _boom)


def _relocate(stick: Path, planned):
    return uol.relocate_audio_files(stick, planned, contents_dir=stick / "Contents")


# ---------------------------------------------------------------------------
# Pure rename — the whole point of the pass
# ---------------------------------------------------------------------------


class TestPureRename:
    def test_pure_rename_copies_zero_bytes(self, tmp_path: Path, stick: Path, no_copies) -> None:
        local = _write(tmp_path / "music" / "track.aiff", BLOCK)
        old = _write(stick / "Contents" / "Old Name" / "Xpress" / "track.aiff", BLOCK)
        dest = stick / "Contents" / "New Name" / "Xpress" / "track.aiff"

        report = _relocate(stick, [(local, dest)])

        assert report["relocated"] == 1
        assert report["copied"] == 0
        assert report["bytes_copied"] == 0
        assert report["bytes_moved"] == len(BLOCK)
        assert dest.read_bytes() == BLOCK
        assert not old.exists()

    def test_emptied_variant_folder_is_pruned(self, tmp_path: Path, stick: Path, no_copies) -> None:
        local = _write(tmp_path / "music" / "track.aiff", BLOCK)
        _write(stick / "Contents" / "Old Name" / "Xpress" / "track.aiff", BLOCK)
        dest = stick / "Contents" / "New Name" / "Xpress" / "track.aiff"

        report = _relocate(stick, [(local, dest)])

        assert report["pruned_dirs"] == 2  # "Xpress" then "Old Name"
        assert not (stick / "Contents" / "Old Name").exists()

    def test_non_empty_variant_folder_survives(
        self, tmp_path: Path, stick: Path, no_copies
    ) -> None:
        local = _write(tmp_path / "music" / "a.aiff", BLOCK)
        _write(stick / "Contents" / "Old Name" / "T1" / "a.aiff", BLOCK)
        keeper = _write(stick / "Contents" / "Old Name" / "T2" / "b.aiff", OTHER)
        dest = stick / "Contents" / "New Name" / "T1" / "a.aiff"

        _relocate(stick, [(local, dest)])

        assert not (stick / "Contents" / "Old Name" / "T1").exists()
        assert (stick / "Contents" / "Old Name").is_dir()
        assert keeper.read_bytes() == OTHER

    def test_several_variant_folders_merge_into_one(
        self, tmp_path: Path, stick: Path, no_copies
    ) -> None:
        """The headline case: `boys noize` + `BN` + `Boys  Noize` -> one folder."""
        contents = stick / "Contents"
        planned = []
        for i, variant in enumerate(("boyz noize", "BN", "Boys  Noize")):
            data = BLOCK + bytes([i])
            local = _write(tmp_path / "music" / f"t{i}.aiff", data)
            _write(contents / variant / f"T{i}" / f"t{i}.aiff", data)
            planned.append((local, contents / "Boys Noize" / f"T{i}" / f"t{i}.aiff"))

        report = _relocate(stick, planned)

        assert report["relocated"] == 3
        assert report["copied"] == 0
        assert report["bytes_copied"] == 0
        assert sorted(os.listdir(contents)) == ["Boys Noize"]
        assert sorted(p.name for p in (contents / "Boys Noize").iterdir()) == ["T0", "T1", "T2"]

    def test_already_in_place_is_left_alone(self, tmp_path: Path, stick: Path, no_copies) -> None:
        local = _write(tmp_path / "music" / "track.aiff", BLOCK)
        dest = _write(stick / "Contents" / "Artist" / "T" / "track.aiff", BLOCK)

        report = _relocate(stick, [(local, dest)])

        assert report == {
            **report,
            "relocated": 0,
            "copied": 0,
            "skipped": 1,
            "collisions": 0,
            "errors": 0,
        }
        assert dest.read_bytes() == BLOCK

    def test_nothing_on_the_stick_is_left_to_the_copy_phase(
        self, tmp_path: Path, stick: Path, no_copies
    ) -> None:
        local = _write(tmp_path / "music" / "track.aiff", BLOCK)
        _write(stick / "Contents" / "Someone" / "T" / "unrelated.aiff", OTHER)
        dest = stick / "Contents" / "Artist" / "T" / "track.aiff"

        report = _relocate(stick, [(local, dest)])

        assert report["relocated"] == 0
        assert report["skipped"] == 1
        assert not dest.exists()

    def test_missing_local_source_is_skipped(self, tmp_path: Path, stick: Path, no_copies) -> None:
        _write(stick / "Contents" / "Old" / "T" / "track.aiff", BLOCK)
        dest = stick / "Contents" / "New" / "T" / "track.aiff"

        report = _relocate(stick, [(tmp_path / "music" / "gone.aiff", dest)])

        assert report["skipped"] == 1
        assert report["relocated"] == 0
        assert (stick / "Contents" / "Old" / "T" / "track.aiff").exists()

    def test_a_different_size_is_never_a_candidate(
        self, tmp_path: Path, stick: Path, no_copies
    ) -> None:
        """Same filename, different bytes = a different track. Never move it."""
        local = _write(tmp_path / "music" / "track.aiff", BLOCK)
        stale = _write(stick / "Contents" / "Old" / "T" / "track.aiff", OTHER)
        dest = stick / "Contents" / "New" / "T" / "track.aiff"

        report = _relocate(stick, [(local, dest)])

        assert report["relocated"] == 0
        assert stale.read_bytes() == OTHER

    def test_never_steals_another_tracks_planned_destination(
        self, tmp_path: Path, stick: Path, no_copies
    ) -> None:
        """Two tracks, one filename: B already sits at its own destination."""
        local_a = _write(tmp_path / "music" / "a" / "track.aiff", BLOCK)
        local_b = _write(tmp_path / "music" / "b" / "track.aiff", BLOCK)
        dest_a = stick / "Contents" / "A" / "T" / "track.aiff"
        dest_b = _write(stick / "Contents" / "B" / "T" / "track.aiff", BLOCK)

        report = _relocate(stick, [(local_a, dest_a), (local_b, dest_b)])

        assert report["relocated"] == 0
        assert dest_b.read_bytes() == BLOCK
        assert not dest_a.exists()

    def test_destination_outside_contents_is_refused(
        self, tmp_path: Path, stick: Path, no_copies
    ) -> None:
        local = _write(tmp_path / "music" / "track.aiff", BLOCK)
        _write(stick / "Contents" / "Old" / "T" / "track.aiff", BLOCK)

        report = _relocate(stick, [(local, stick / "PIONEER" / "track.aiff")])

        assert report["skipped"] == 1
        assert report["relocated"] == 0
        assert not (stick / "PIONEER").exists()


# ---------------------------------------------------------------------------
# Case-only rename — the trap that eats a folder on Windows / exFAT
# ---------------------------------------------------------------------------


class TestCaseOnlyRename:
    @pytest.fixture
    def case_insensitive_volume(self, monkeypatch):
        """Make a DIRECT case-only rename fail the way Windows/exFAT does.

        There `boys noize` and `Boys Noize` address the same directory entry, so
        `os.rename` between them raises FileExistsError (or silently does
        nothing). Only a detour through a third name works — which is exactly
        what this fixture proves the implementation takes.
        """
        real_rename = os.rename

        def guarded(src, dst, *args, **kwargs):
            s, d = str(src), str(dst)
            if s != d and s.casefold() == d.casefold():
                raise FileExistsError(f"case-only rename refused by the volume: {s} -> {d}")
            return real_rename(src, dst, *args, **kwargs)

        monkeypatch.setattr(os, "rename", guarded)

    def test_case_only_rename_two_step(
        self, tmp_path: Path, stick: Path, no_copies, case_insensitive_volume
    ) -> None:
        local = _write(tmp_path / "music" / "track.aiff", BLOCK)
        _write(stick / "Contents" / "boys noize" / "Xpress" / "track.aiff", BLOCK)
        dest = stick / "Contents" / "Boys Noize" / "Xpress" / "track.aiff"

        report = _relocate(stick, [(local, dest)])

        assert report["relocated"] == 1
        assert report["copied"] == 0
        assert report["bytes_copied"] == 0
        assert os.listdir(stick / "Contents") == ["Boys Noize"]
        assert dest.read_bytes() == BLOCK

    def test_case_only_rename_leaves_no_temp_directory(
        self, tmp_path: Path, stick: Path, no_copies, case_insensitive_volume
    ) -> None:
        local = _write(tmp_path / "music" / "track.aiff", BLOCK)
        _write(stick / "Contents" / "boys noize" / "Xpress" / "track.aiff", BLOCK)
        dest = stick / "Contents" / "Boys Noize" / "Xpress" / "track.aiff"

        _relocate(stick, [(local, dest)])

        leftovers = [p for p in (stick / "Contents").rglob("*") if uol._RELOC_TMP_SUFFIX in p.name]
        assert leftovers == []

    def test_case_only_filename_rename(
        self, tmp_path: Path, stick: Path, no_copies, case_insensitive_volume
    ) -> None:
        local = _write(tmp_path / "music" / "Track.aiff", BLOCK)
        _write(stick / "Contents" / "Artist" / "T" / "track.aiff", BLOCK)
        dest = stick / "Contents" / "Artist" / "T" / "Track.aiff"

        report = _relocate(stick, [(local, dest)])

        assert report["relocated"] == 1
        assert os.listdir(stick / "Contents" / "Artist" / "T") == ["Track.aiff"]

    def test_exact_name_wins_over_a_case_variant(
        self, tmp_path: Path, stick: Path, no_copies
    ) -> None:
        """On a case-sensitive volume both folders can exist. Merge, don't rename."""
        local = _write(tmp_path / "music" / "track.aiff", BLOCK)
        variant = stick / "Contents" / "boys noize" / "T" / "track.aiff"
        if variant.parent.exists():  # pragma: no cover - defensive
            pytest.skip("case-insensitive volume")
        _write(variant, BLOCK)
        (stick / "Contents" / "Boys Noize" / "T").mkdir(parents=True, exist_ok=True)
        dest = stick / "Contents" / "Boys Noize" / "T" / "track.aiff"
        if dest.exists():
            pytest.skip("case-insensitive volume — the two folders are one")

        report = _relocate(stick, [(local, dest)])

        assert report["relocated"] == 1
        assert dest.read_bytes() == BLOCK
        assert not (stick / "Contents" / "boys noize").exists()

    def test_a_case_variant_another_track_plans_is_never_taken(
        self, tmp_path: Path, stick: Path, no_copies
    ) -> None:
        """Two tracks whose destinations differ only by case: neither may steal the file.

        The case variant of a track's own destination is only a candidate while no
        second track plans that same folded path — otherwise one of them would move
        the other's audio out from under it.
        """
        local_a = _write(tmp_path / "music" / "a" / "track.aiff", BLOCK)
        local_b = _write(tmp_path / "music" / "b" / "track.aiff", BLOCK)
        occupied = stick / "Contents" / "boys noize" / "T" / "track.aiff"
        _write(occupied, BLOCK)
        (stick / "Contents" / "Boys Noize" / "T").mkdir(parents=True, exist_ok=True)
        dest_a = stick / "Contents" / "Boys Noize" / "T" / "track.aiff"
        if dest_a.exists():
            pytest.skip("case-insensitive volume — the two folders are one")

        report = _relocate(stick, [(local_a, dest_a), (local_b, occupied)])

        assert report["relocated"] == 0
        assert occupied.read_bytes() == BLOCK
        assert not dest_a.exists()


# ---------------------------------------------------------------------------
# Collisions — the destination is occupied
# ---------------------------------------------------------------------------


class TestCollision:
    def test_collision_never_clobbers(self, tmp_path: Path, stick: Path) -> None:
        local = _write(tmp_path / "music" / "track.aiff", BLOCK)
        source = _write(stick / "Contents" / "Old" / "T" / "track.aiff", BLOCK)
        dest = _write(stick / "Contents" / "New" / "T" / "track.aiff", OTHER)

        report = _relocate(stick, [(local, dest)])

        assert report["collisions"] == 1
        assert report["copied"] == 1
        assert dest.read_bytes() == OTHER  # the occupant is untouched
        assert (stick / "Contents" / "New" / "T" / "track (1).aiff").read_bytes() == BLOCK
        assert not source.exists()

    def test_identical_duplicate_is_removed_not_moved(self, tmp_path: Path, stick: Path) -> None:
        local = _write(tmp_path / "music" / "track.aiff", BLOCK)
        source = _write(stick / "Contents" / "Old" / "T" / "track.aiff", BLOCK)
        dest = _write(stick / "Contents" / "New" / "T" / "track.aiff", BLOCK)

        report = _relocate(stick, [(local, dest)])

        assert report["collisions"] == 1
        assert report["duplicates_removed"] == 1
        assert report["copied"] == 0
        assert dest.read_bytes() == BLOCK
        assert not source.exists()
        assert not (stick / "Contents" / "Old").exists()


# ---------------------------------------------------------------------------
# Cross-volume + verification — never a silent half-move
# ---------------------------------------------------------------------------


class TestCrossVolume:
    def test_cross_volume_falls_back_to_copy_and_verify(
        self, tmp_path: Path, stick: Path, monkeypatch
    ) -> None:
        monkeypatch.setattr(uol, "_same_volume", lambda a, b: False)
        local = _write(tmp_path / "music" / "track.aiff", BLOCK)
        source = _write(stick / "Contents" / "Old" / "T" / "track.aiff", BLOCK)
        dest = stick / "Contents" / "New" / "T" / "track.aiff"

        report = _relocate(stick, [(local, dest)])

        assert report["copied"] == 1
        assert report["relocated"] == 0
        assert report["bytes_copied"] == len(BLOCK)
        assert dest.read_bytes() == BLOCK
        assert not source.exists()

    def test_exdev_from_os_replace_also_falls_back(
        self, tmp_path: Path, stick: Path, monkeypatch
    ) -> None:
        """`_same_volume` says yes but the kernel disagrees — still no half-move."""
        import errno as _errno

        real_replace = os.replace

        def refusing(src, dst, *args, **kwargs):
            raise OSError(_errno.EXDEV, "Invalid cross-device link")

        monkeypatch.setattr(os, "replace", refusing)
        local = _write(tmp_path / "music" / "track.aiff", BLOCK)
        source = _write(stick / "Contents" / "Old" / "T" / "track.aiff", BLOCK)
        dest = stick / "Contents" / "New" / "T" / "track.aiff"

        # the atomic copy needs the real primitive back for its own rename
        def copy_with_real_replace(src, dst):
            monkeypatch.setattr(os, "replace", real_replace)
            try:
                uol.shutil.copy2(str(src), str(dst))
            finally:
                monkeypatch.setattr(os, "replace", refusing)

        monkeypatch.setattr(uol, "_copy_file_atomic", copy_with_real_replace)

        report = _relocate(stick, [(local, dest)])

        assert report["copied"] == 1
        assert dest.read_bytes() == BLOCK
        assert not source.exists()

    def test_source_survives_a_failed_verification(
        self, tmp_path: Path, stick: Path, monkeypatch
    ) -> None:
        """A truncated copy must cost the copy, never the only good file."""
        monkeypatch.setattr(uol, "_same_volume", lambda a, b: False)

        def truncating(src, dst):
            Path(dst).parent.mkdir(parents=True, exist_ok=True)
            Path(dst).write_bytes(Path(src).read_bytes()[:10])

        monkeypatch.setattr(uol, "_copy_file_atomic", truncating)
        local = _write(tmp_path / "music" / "track.aiff", BLOCK)
        source = _write(stick / "Contents" / "Old" / "T" / "track.aiff", BLOCK)
        dest = stick / "Contents" / "New" / "T" / "track.aiff"

        report = _relocate(stick, [(local, dest)])

        assert report["errors"] == 1
        assert report["copied"] == 0
        assert source.read_bytes() == BLOCK  # never deleted
        assert dest.stat().st_size == 10  # the copy phase heals this one

    def test_a_failure_does_not_abort_the_other_tracks(
        self, tmp_path: Path, stick: Path, monkeypatch
    ) -> None:
        monkeypatch.setattr(uol, "_same_volume", lambda a, b: False)

        def only_first_fails(src, dst):
            if Path(src).name == "bad.aiff":
                raise OSError("disk went away")
            uol.shutil.copy2(str(src), str(dst))

        monkeypatch.setattr(uol, "_copy_file_atomic", only_first_fails)
        bad_local = _write(tmp_path / "music" / "bad.aiff", BLOCK)
        good_local = _write(tmp_path / "music" / "good.aiff", BLOCK)
        bad_src = _write(stick / "Contents" / "Old" / "T" / "bad.aiff", BLOCK)
        _write(stick / "Contents" / "Old" / "T" / "good.aiff", BLOCK)
        bad_dest = stick / "Contents" / "New" / "T" / "bad.aiff"
        good_dest = stick / "Contents" / "New" / "T" / "good.aiff"

        report = _relocate(stick, [(bad_local, bad_dest), (good_local, good_dest)])

        assert report["errors"] == 1
        assert report["copied"] == 1
        assert bad_src.exists()
        assert good_dest.read_bytes() == BLOCK


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


class TestGuards:
    def test_missing_contents_dir_is_a_no_op(self, tmp_path: Path) -> None:
        local = _write(tmp_path / "music" / "track.aiff", BLOCK)
        report = uol.relocate_audio_files(
            tmp_path / "usb", [(local, tmp_path / "usb" / "Contents" / "A" / "T" / "track.aiff")]
        )
        assert report["relocated"] == 0
        assert report["skipped"] == 1

    def test_empty_plan_is_a_no_op(self, stick: Path) -> None:
        report = _relocate(stick, [])
        assert report["relocated"] == 0
        assert report["skipped"] == 0

    def test_part_files_are_never_candidates(self, tmp_path: Path, stick: Path, no_copies) -> None:
        local = _write(tmp_path / "music" / "track.aiff", BLOCK)
        leftover = _write(stick / "Contents" / "Old" / "T" / "track.aiff.part", BLOCK)
        dest = stick / "Contents" / "New" / "T" / "track.aiff"

        report = _relocate(stick, [(local, dest)])

        assert report["relocated"] == 0
        assert leftover.exists()

    def test_details_are_capped(self, tmp_path: Path, stick: Path, no_copies, monkeypatch) -> None:
        monkeypatch.setattr(uol, "_RELOC_DETAIL_CAP", 2)
        planned = []
        for i in range(4):
            local = _write(tmp_path / "music" / f"t{i}.aiff", BLOCK + bytes([i]))
            _write(stick / "Contents" / "Old" / f"T{i}" / f"t{i}.aiff", BLOCK + bytes([i]))
            planned.append((local, stick / "Contents" / "New" / f"T{i}" / f"t{i}.aiff"))

        report = _relocate(stick, planned)

        assert report["relocated"] == 4
        assert len(report["details"]) == 2
        assert report["details_truncated"] is True


class TestCaseSensitiveVolumeLookup:
    """`_existing_ci` on a case-sensitive volume, simulated through its listing.

    Windows cannot host `boys noize/` and `Boys Noize/` side by side, so the
    directory listing is faked instead of the filesystem — the guarantee under
    test ("an exact segment always wins") lives entirely in that lookup.
    """

    def test_exact_segment_never_crosses_into_the_variant(self, tmp_path, monkeypatch) -> None:
        root = tmp_path / "Contents"
        listings = {
            str(root): ["boys noize", "Boys Noize"],
            str(root / "Boys Noize"): ["T"],
            str(root / "Boys Noize" / "T"): [],
            str(root / "boys noize"): ["T"],
            str(root / "boys noize" / "T"): ["track.aiff"],
        }
        monkeypatch.setattr(uol, "_dir_entries", lambda p: listings.get(str(p), []))

        assert uol._existing_ci(root, root / "Boys Noize" / "T" / "track.aiff") is None

    def test_lone_variant_is_found(self, tmp_path, monkeypatch) -> None:
        root = tmp_path / "Contents"
        listings = {
            str(root): ["boys noize"],
            str(root / "boys noize"): ["T"],
            str(root / "boys noize" / "T"): ["track.aiff"],
        }
        monkeypatch.setattr(uol, "_dir_entries", lambda p: listings.get(str(p), []))

        found = uol._existing_ci(root, root / "Boys Noize" / "T" / "track.aiff")
        assert found == root / "boys noize" / "T" / "track.aiff"

    def test_two_variants_and_no_exact_is_refused(self, tmp_path, monkeypatch) -> None:
        root = tmp_path / "Contents"
        listings = {str(root): ["boys noize", "BOYS NOIZE"]}
        monkeypatch.setattr(uol, "_dir_entries", lambda p: listings.get(str(p), []))

        assert uol._existing_ci(root, root / "Boys Noize" / "T" / "track.aiff") is None


class TestPlannedDest:
    """The relocation pass and the copy phase must agree on the destination."""

    def test_resolver_wins_over_the_fallback(self, tmp_path: Path) -> None:
        seen: dict[str, str] = {}

        def resolver(artist, title, filename):
            seen.update(artist=artist, title=title, filename=filename)
            return tmp_path / "Contents" / artist / title / filename

        writer = uol.OneLibraryUsbWriter(str(tmp_path), dest_resolver=resolver)
        got = writer._planned_dest(
            {"artist": "Boys Noize", "title": "Xpress"}, Path("x") / "track.aiff"
        )

        assert got == tmp_path / "Contents" / "Boys Noize" / "Xpress" / "track.aiff"
        assert seen == {"artist": "Boys Noize", "title": "Xpress", "filename": "track.aiff"}

    def test_fallback_uses_the_pioneer_layout(self, tmp_path: Path) -> None:
        writer = uol.OneLibraryUsbWriter(str(tmp_path))
        got = writer._planned_dest(
            {"artist": "Boys Noize", "title": "Xpress"}, Path("x") / "track.aiff"
        )
        assert got == tmp_path / "Contents" / "Boys Noize" / "Xpress" / "track.aiff"


# ---------------------------------------------------------------------------
# Wiring — the legacy XML sync runs the pass before its copy loop
# ---------------------------------------------------------------------------


class TestLegacySyncWiring:
    def test_relocate_before_copy_reports_a_move(self, tmp_path: Path, stick: Path) -> None:
        from app.usb_manager import UsbSyncEngine

        engine = UsbSyncEngine(
            local_db_path=str(tmp_path / "fake_local.db"),
            usb_drive=str(stick),
            filesystem="NTFS",
        )
        local = _write(tmp_path / "music" / "track.aiff", BLOCK)
        old_dest = engine._get_safe_dest_path("Old Name", "Xpress", "track.aiff")
        _write(old_dest, BLOCK)
        new_dest = engine._get_safe_dest_path("New Name", "Xpress", "track.aiff")

        events = list(
            engine._relocate_before_copy(
                [{"path": str(local), "artist": "New Name", "title": "Xpress"}]
            )
        )

        assert len(events) == 1
        assert events[0]["stage"] == "relocate"
        assert events[0]["report"]["relocated"] == 1
        assert new_dest.read_bytes() == BLOCK
        assert not old_dest.exists()

    def test_relocate_before_copy_is_silent_when_nothing_moves(
        self, tmp_path: Path, stick: Path
    ) -> None:
        from app.usb_manager import UsbSyncEngine

        engine = UsbSyncEngine(
            local_db_path=str(tmp_path / "fake_local.db"),
            usb_drive=str(stick),
            filesystem="NTFS",
        )
        local = _write(tmp_path / "music" / "track.aiff", BLOCK)
        _write(engine._get_safe_dest_path("Artist", "T", "track.aiff"), BLOCK)

        events = list(
            engine._relocate_before_copy([{"path": str(local), "artist": "Artist", "title": "T"}])
        )

        assert events == []

    @pytest.mark.parametrize(
        ("path_str", "expected"),
        [
            ("soundcloud:tracks:123", True),
            ("spotify:track:abc", True),
            ("https://example.test/a.mp3", True),
            ("C:/Music/track.aiff", False),
            ("C:\\Music\\track.aiff", False),
            ("/home/dj/track.aiff", False),
            ("", False),
        ],
    )
    def test_streaming_pseudo_path_rule(self, path_str: str, expected: bool) -> None:
        from app.usb_manager import _is_streaming_pseudo_path

        assert _is_streaming_pseudo_path(path_str) is expected

    def test_streaming_pseudo_paths_are_ignored(self, tmp_path: Path, stick: Path) -> None:
        from app.usb_manager import UsbSyncEngine

        engine = UsbSyncEngine(
            local_db_path=str(tmp_path / "fake_local.db"),
            usb_drive=str(stick),
            filesystem="NTFS",
        )
        events = list(
            engine._relocate_before_copy(
                [{"path": "soundcloud:tracks:123", "artist": "A", "title": "T"}]
            )
        )
        assert events == []


class TestContentIsProvenBeforeMovingOrDeleting:
    """Name + byte count is not proof of "the same recording".

    A DJ stick is full of re-exported and re-named versions of the same tracks, so
    those two attributes collide routinely. Acting on them alone let the pass move a
    file belonging to a track outside this sync — the copy phase, which also compares
    sizes, then saw nothing to repair — and delete a file that merely looked like a
    duplicate. Both are irreversible on removable media.
    """

    def test_a_stranger_with_the_same_name_and_size_is_not_moved(
        self, tmp_path: Path, stick: Path, no_copies
    ) -> None:
        local = _write(tmp_path / "music" / "shared.aiff", b"X" * 600)
        stranger = _write(stick / "Contents" / "Someone Else" / "T" / "shared.aiff", b"Y" * 600)
        dest = stick / "Contents" / "Wanted" / "T" / "shared.aiff"

        report = _relocate(stick, [(local, dest)])

        assert stranger.read_bytes() == b"Y" * 600, "another track's audio was moved away"
        assert not dest.exists()
        assert report["relocated"] == 0
        assert report["skipped"] >= 1
        assert any(
            d.get("action") == "candidate_content_mismatch" for d in report.get("details", [])
        ), report.get("details")

    def test_the_real_file_still_moves(self, tmp_path: Path, stick: Path, no_copies) -> None:
        """The guard must not break the case it exists to protect."""
        local = _write(tmp_path / "music" / "shared.aiff", b"X" * 600)
        old = _write(stick / "Contents" / "old name" / "T" / "shared.aiff", b"X" * 600)
        dest = stick / "Contents" / "New Name" / "T" / "shared.aiff"

        report = _relocate(stick, [(local, dest)])

        assert report["relocated"] == 1
        assert report["bytes_copied"] == 0
        assert dest.read_bytes() == b"X" * 600
        assert not old.exists()

    def test_a_same_size_collision_with_different_bytes_deletes_nothing(
        self, tmp_path: Path, stick: Path
    ) -> None:
        # No `no_copies` here on purpose: keeping both recordings is exactly what
        # should happen, and that means copying the candidate beside the occupant.
        local = _write(tmp_path / "music" / "c.aiff", b"D" * 1000)
        cand = _write(stick / "Contents" / "old name" / "T" / "c.aiff", b"D" * 1000)
        occupied = _write(stick / "Contents" / "New Name" / "T" / "c.aiff", b"E" * 1000)

        report = _relocate(stick, [(local, occupied)])

        assert occupied.read_bytes() == b"E" * 1000, "the occupant was overwritten"
        assert report["duplicates_removed"] == 0, (
            "a file was deleted from the stick on a name+size match alone"
        )
        survivors = sorted(p.name for p in occupied.parent.iterdir())
        assert len(survivors) == 2, f"one of the two recordings was lost: {survivors}"
        assert not cand.exists() or cand.read_bytes() == b"D" * 1000

    def test_a_genuine_duplicate_is_still_removed(
        self, tmp_path: Path, stick: Path, no_copies
    ) -> None:
        """Identical bytes: removing the stale copy is the point of the branch."""
        local = _write(tmp_path / "music" / "c.aiff", b"D" * 1000)
        cand = _write(stick / "Contents" / "old name" / "T" / "c.aiff", b"D" * 1000)
        occupied = _write(stick / "Contents" / "New Name" / "T" / "c.aiff", b"D" * 1000)

        report = _relocate(stick, [(local, occupied)])

        assert report["duplicates_removed"] == 1
        assert not cand.exists()
        assert occupied.read_bytes() == b"D" * 1000

    @pytest.mark.parametrize(
        "size",
        [uol._FINGERPRINT_EDGE + 1, 100 * 1024, uol._FINGERPRINT_EDGE * 2],
    )
    def test_a_shared_head_is_not_proof_for_a_small_file(self, tmp_path: Path, size: int) -> None:
        """64 KiB < size <= 128 KiB used to hash the head only — an oversized ID3
        cover-art frame makes two different recordings share that head verbatim."""
        head = b"H" * uol._FINGERPRINT_EDGE
        a = _write(tmp_path / "a.aiff", head + b"A" * (size - len(head)))
        b = _write(tmp_path / "b.aiff", head + b"B" * (size - len(head)))

        assert uol._same_content(a, b) is False

    def test_a_shared_head_collision_deletes_nothing(self, tmp_path: Path, stick: Path) -> None:
        # No `no_copies`: keeping both recordings means copying one beside the other.
        head = b"H" * uol._FINGERPRINT_EDGE
        body = 100 * 1024 - len(head)
        local = _write(tmp_path / "music" / "c.aiff", head + b"D" * body)
        _write(stick / "Contents" / "old name" / "T" / "c.aiff", head + b"D" * body)
        occupied = _write(stick / "Contents" / "New Name" / "T" / "c.aiff", head + b"E" * body)

        report = _relocate(stick, [(local, occupied)])

        assert report["duplicates_removed"] == 0
        assert occupied.read_bytes().endswith(b"E" * 64)
        assert sorted(p.name for p in occupied.parent.iterdir()) == ["c (1).aiff", "c.aiff"]

    def test_a_stranger_does_not_veto_the_real_candidate(
        self, tmp_path: Path, stick: Path, no_copies
    ) -> None:
        """A same-name, same-size stranger sorting first is skipped over, not a veto."""
        local = _write(tmp_path / "music" / "shared.aiff", b"X" * 600)
        stranger = _write(stick / "Contents" / "Aaa" / "T" / "shared.aiff", b"Y" * 600)
        real_old = _write(stick / "Contents" / "zzz" / "T" / "shared.aiff", b"X" * 600)
        dest = stick / "Contents" / "New" / "T" / "shared.aiff"

        report = _relocate(stick, [(local, dest)])

        assert report["relocated"] == 1
        assert report["bytes_copied"] == 0
        assert dest.read_bytes() == b"X" * 600
        assert not real_old.exists()
        assert stranger.read_bytes() == b"Y" * 600


# ---------------------------------------------------------------------------
# Wiring — OneLibraryUsbWriter.sync() Stage 1b
# ---------------------------------------------------------------------------
#
# `TestLegacySyncWiring` above covers `UsbSyncEngine._relocate_before_copy`, the
# legacy XML path. Production drives the OneLibrary writer instead
# (app/usb_manager.py: `OneLibraryUsbWriter(drive, dest_resolver=...)` then
# `sync(..., audio_copy=True)`), and Stage 1b only runs under `audio_copy` — the
# exact complement of what the legacy tests reach. These drive the REAL `sync()`
# against a fake rbox handle, so the wiring itself is asserted: the guard, the
# ordering against the copy loop, the two bounds, and the shared destination.


class _Row:
    """Stand-in for an rbox content / artist / album row."""

    def __init__(self, rid: int) -> None:
        self.id = rid
        self.name = f"__placeholder_{rid}__"
        self.title = self.name
        self.path = ""


class _FakeDb:
    """Only the rbox.OneLibrary surface `sync()` actually calls."""

    def __init__(self, slots: int, fail_titles: frozenset[str] = frozenset()) -> None:
        self.contents = [_Row(i + 1) for i in range(slots)]
        self.updated: list[_Row] = []
        self.deleted: list[int] = []
        self.fail_titles = fail_titles
        self._next = 1000

    def get_properties(self):
        return []

    def get_contents(self):
        return list(self.contents)

    def get_artists(self):
        return []

    def get_albums(self):
        return []

    def get_genres(self):
        return []

    def get_keys(self):
        return []

    def get_labels(self):
        return []

    def get_artist_by_name(self, *a):
        return None

    get_album_by_name = get_artist_by_name
    get_genre_by_name = get_artist_by_name
    get_key_by_name = get_artist_by_name
    get_label_by_name = get_artist_by_name

    def create_artist(self, *a):
        self._next += 1
        return _Row(self._next)

    create_album = create_artist
    create_genre = create_artist
    create_key = create_artist
    create_label = create_artist

    def update_content(self, slot):
        if slot.title in self.fail_titles:
            raise RuntimeError(f"rbox refused slot {slot.id}")
        self.updated.append(slot)

    def delete_content(self, cid):
        self.deleted.append(cid)

    def survivors(self) -> list[_Row]:
        return [row for row in self.contents if row.id not in self.deleted]


class _FakeSource:
    def __init__(self, tracks, playlists=None):
        self.tracks = tracks
        self._pl = playlists or {}

    def iter_tracks(self):
        return iter(self.tracks)

    def iter_playlists(self):
        return iter([])

    def get_playlists_tree(self):
        return []

    def get_playlist_track_ids(self, pid):
        return self._pl.get(pid, [])

    def get_track_anlz_paths(self, tid):
        return None


def _track(local: Path, artist: str, title: str, tid: str = "1") -> dict:
    return {"id": tid, "artist": artist, "title": title, "path": str(local)}


def _reloc_event(events):
    got = [e for e in events if e.get("stage") == "relocate"]
    return got[0] if got else None


@pytest.fixture
def run_sync(tmp_path: Path, monkeypatch):
    """Drive the REAL `sync()` against a fake rbox. Returns (events, db, writer)."""

    def _run(
        stick_root,
        tracks,
        *,
        slots=4,
        audio_copy=True,
        playlist_filter=None,
        dest_resolver=None,
        playlists=None,
        fail_titles=frozenset(),
    ):
        db = _FakeDb(slots, frozenset(fail_titles))
        monkeypatch.setattr(uol, "rbox", SimpleNamespace(OneLibrary=lambda p: db))
        monkeypatch.setattr(uol, "RBOX_AVAILABLE", True)
        # Stage 6 sleeps 2x0.5 s waiting for the rbox handle to release the WAL.
        monkeypatch.setattr(uol, "time", SimpleNamespace(sleep=lambda *_: None))
        writer = uol.OneLibraryUsbWriter(str(stick_root), dest_resolver=dest_resolver)
        template = tmp_path / "template.db"
        template.write_bytes(b"\x00" * 64)
        writer.TEMPLATE_DB = template
        events = list(
            writer.sync(
                _FakeSource(tracks, playlists),
                audio_copy=audio_copy,
                copy_anlz=False,
                playlist_filter=playlist_filter,
                write_pdb=False,
            )
        )
        return events, db, writer

    return _run


class TestOneLibrarySyncStage1b:
    """Stage 1b must run before the copy loop and agree with it on the destination.

    The two disagreeing, or Stage 1b not running at all, means a pure artist rename
    re-copies gigabytes that are already on the stick — silently, with both stages
    reporting success. `no_copies` is on every pure-rename test here: Stage 1 copies
    the template with `shutil.copy2`, so the fixture proves Stage 1b AND the copy
    loop moved zero bytes.
    """

    def test_a_pure_rename_copies_zero_bytes_through_sync(
        self, tmp_path: Path, stick: Path, run_sync, no_copies
    ) -> None:
        local = _write(tmp_path / "music" / "t.aiff", BLOCK)
        old = _write(stick / "Contents" / "Old Name" / "Xpress" / "t.aiff", BLOCK)

        events, db, _writer = run_sync(stick, [_track(local, "New Name", "Xpress")])

        ev = _reloc_event(events)
        assert ev is not None
        assert ev["progress"] == 5
        assert ev["report"]["relocated"] == 1
        assert ev["report"]["bytes_moved"] == len(BLOCK)
        assert ev["report"]["bytes_copied"] == 0
        assert not old.exists()
        assert os.listdir(stick / "Contents") == ["New Name"]
        assert (stick / "Contents" / "New Name" / "Xpress" / "t.aiff").read_bytes() == BLOCK
        # The copy loop resolved the same destination Stage 1b moved the file to.
        assert db.updated[0].path == "/Contents/New Name/Xpress/t.aiff"

    def test_skipped_when_audio_copy_false(
        self, tmp_path: Path, stick: Path, run_sync, no_copies
    ) -> None:
        local = _write(tmp_path / "music" / "t.aiff", BLOCK)
        old = _write(stick / "Contents" / "Old Name" / "Xpress" / "t.aiff", BLOCK)

        events, _db, _writer = run_sync(
            stick, [_track(local, "New Name", "Xpress")], audio_copy=False
        )

        assert _reloc_event(events) is None
        assert old.exists()
        assert os.listdir(stick / "Contents") == ["Old Name"]

    def test_playlist_filter_bounds_stage_1b(
        self, tmp_path: Path, stick: Path, run_sync, no_copies
    ) -> None:
        """Stage 1b runs AFTER the playlist filter — a track the user did not select
        is not part of this export, so its stick copy must stay where it is."""
        keep = _write(tmp_path / "music" / "keep.aiff", BLOCK)
        drop = _write(tmp_path / "music" / "drop.aiff", BLOCK + b"Z")
        _write(stick / "Contents" / "Old" / "K" / "keep.aiff", BLOCK)
        drop_old = _write(stick / "Contents" / "Old" / "D" / "drop.aiff", BLOCK + b"Z")

        events, _db, _writer = run_sync(
            stick,
            [_track(keep, "New", "K", "1"), _track(drop, "New", "D", "2")],
            playlist_filter=["pl1"],
            playlists={"pl1": ["1"]},
        )

        ev = _reloc_event(events)
        assert ev is not None
        assert ev["report"]["relocated"] == 1
        assert drop_old.exists()

    def test_slot_count_bounds_stage_1b(
        self, tmp_path: Path, stick: Path, run_sync, no_copies
    ) -> None:
        """Past the template's slot count a track gets no row, so moving its stick
        copy would strand audio no library entry points at."""
        tracks = []
        for i in range(3):
            loc = _write(tmp_path / "music" / f"t{i}.aiff", BLOCK + bytes([i]))
            _write(stick / "Contents" / "Old" / f"T{i}" / f"t{i}.aiff", BLOCK + bytes([i]))
            tracks.append(_track(loc, "New", f"T{i}", str(i)))

        events, _db, _writer = run_sync(stick, tracks, slots=2)

        ev = _reloc_event(events)
        assert ev is not None
        assert ev["report"]["relocated"] == 2
        assert (stick / "Contents" / "Old" / "T2" / "t2.aiff").exists()

    def test_stage_1b_honours_the_dest_resolver(
        self, tmp_path: Path, stick: Path, run_sync, no_copies
    ) -> None:
        """Production always passes a resolver, so both stages must route through it
        rather than the fallback layout."""

        def resolver(artist, title, filename):
            return stick / "Contents" / f"R_{artist}" / title / filename

        local = _write(tmp_path / "music" / "t.aiff", BLOCK)
        _write(stick / "Contents" / "Old" / "Xpress" / "t.aiff", BLOCK)

        events, db, _writer = run_sync(
            stick, [_track(local, "New Name", "Xpress")], dest_resolver=resolver
        )

        ev = _reloc_event(events)
        assert ev is not None
        assert ev["report"]["relocated"] == 1
        assert ev["report"]["bytes_copied"] == 0
        assert os.listdir(stick / "Contents") == ["R_New Name"]
        assert db.updated[0].path == "/Contents/R_New Name/Xpress/t.aiff"


class TestUnreadableLocalPath:
    """One local file the user lost read access to must cost that one track.

    `Path.exists()` re-raises EACCES — py3.11 `pathlib._IGNORED_ERRNOS` covers only
    ENOENT, ENOTDIR, EBADF and WSAELOOP — and by Stage 1b the stick's
    exportLibrary.db has already been replaced with the bare template. An abort
    there leaves the user with a wiped CDJ library.
    """

    def test_one_unreadable_file_does_not_cost_the_export(
        self, tmp_path: Path, stick: Path, run_sync, no_copies, monkeypatch
    ) -> None:
        import errno as _errno

        good = _write(tmp_path / "music" / "good.aiff", BLOCK)
        _write(stick / "Contents" / "Old" / "Good" / "good.aiff", BLOCK)
        bad = tmp_path / "locked" / "bad.aiff"

        real_exists = Path.exists

        def guarded(self, *args, **kwargs):
            if str(self) == str(bad):
                raise PermissionError(_errno.EACCES, "access is denied")
            return real_exists(self, *args, **kwargs)

        monkeypatch.setattr(Path, "exists", guarded)

        events, db, _writer = run_sync(
            stick,
            [_track(bad, "New", "Bad", "1"), _track(good, "New", "Good", "2")],
        )

        assert any(e["stage"] == "complete" for e in events)
        reloc = _reloc_event(events)
        assert reloc is not None
        assert reloc["report"]["relocated"] == 1
        assert (stick / "Contents" / "New" / "Good" / "good.aiff").read_bytes() == BLOCK

        # Stage 3 prunes the slots nothing was written into BY INDEX. Counting them
        # instead leaves a gap the moment one slot fails, and deletes the row of the
        # track that did survive.
        survivors = db.survivors()
        assert [row.title for row in survivors] == ["Bad", "Good"]
        assert survivors[0].path == ""  # unreadable: row kept, no audio on the stick
        assert survivors[1].path == "/Contents/New/Good/good.aiff"


class TestSlotPruning:
    """Stage 3 deletes the placeholder slots nothing was written into.

    It has to pick them by index. A slot can fail anywhere in the Stage 2 body —
    rbox refusing the write, artwork, ANLZ — and counting the successes instead
    shifts the slice by one, deleting the row of a track that DID land.
    """

    def test_a_failed_slot_does_not_delete_a_populated_row(
        self, tmp_path: Path, stick: Path, run_sync, no_copies
    ) -> None:
        doomed = _write(tmp_path / "music" / "a.aiff", BLOCK)
        keeper = _write(tmp_path / "music" / "b.aiff", BLOCK + b"Z")
        _write(stick / "Contents" / "Old" / "Doomed" / "a.aiff", BLOCK)
        _write(stick / "Contents" / "Old" / "Keeper" / "b.aiff", BLOCK + b"Z")

        _events, db, _writer = run_sync(
            stick,
            [_track(doomed, "New", "Doomed", "1"), _track(keeper, "New", "Keeper", "2")],
            fail_titles={"Doomed"},
        )

        survivors = db.survivors()
        assert [row.title for row in survivors] == ["Keeper"]
        assert survivors[0].path == "/Contents/New/Keeper/b.aiff"
