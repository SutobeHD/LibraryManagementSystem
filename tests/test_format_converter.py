"""Engine tests for `app/format_converter.py` (T-4 swap/snapshot/manifest +
T-5 rollback).

Runs without FFmpeg or rbox: the engine's process helpers
(`_probe_sample_rate` / `_probe_bit_depth` / `_run_ffmpeg` /
`_is_rekordbox_running` / `_kill_rekordbox_if_present`) are module functions
that the tests monkeypatch, and the rbox handle is a `FakeMasterDb`. Real files
are created under `tmp_path` so the snapshot / rename / rollback filesystem
logic is exercised for real.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import app.format_converter as fc

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeContent:
    def __init__(self, cid, folder_path, file_type=4, file_size=1000, deleted=False):
        self.id = cid
        self.folder_path = str(folder_path)
        self.file_name_l = Path(folder_path).name
        self.file_type = file_type
        self.file_size = file_size
        self.rb_local_deleted = deleted


class FakeMasterDb:
    def __init__(self, contents, playlists=None, fail_ids=None):
        self._contents = contents
        self._playlists = playlists or {}
        self._fail_ids = set(fail_ids or [])
        self.updated = []

    def get_contents(self):
        return list(self._contents)

    def get_playlist_contents(self, pid):
        return list(self._playlists.get(pid, []))

    def get_playlists(self):
        return []

    def update_content(self, c):
        if c.id in self._fail_ids:
            raise RuntimeError(f"simulated DB failure for {c.id}")
        self.updated.append((c.id, c.folder_path, c.file_type, c.file_size))


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Build a music dir + a couple of m4a files + a dummy master.db, plus an
    engine wired to a FakeMasterDb. FFmpeg/ffprobe/RB-checks are stubbed."""
    music = tmp_path / "music"
    music.mkdir()
    files = {}
    for i in (1, 2):
        p = music / f"track{i}.m4a"
        p.write_bytes(b"FAKE-M4A-AUDIO" * 10)
        files[i] = p

    master_db = tmp_path / "rb" / "master.db"
    master_db.parent.mkdir()
    master_db.write_bytes(b"FAKE-MASTER-DB")
    (master_db.parent / "master.db-wal").write_bytes(b"WAL")

    backup_dir = tmp_path / "backups"

    contents = [FakeContent(i, files[i]) for i in (1, 2)]
    db = FakeMasterDb(contents)

    monkeypatch.setattr(fc, "_is_rekordbox_running", lambda: False)
    monkeypatch.setattr(fc, "_kill_rekordbox_if_present", lambda: False)
    monkeypatch.setattr(fc, "_probe_sample_rate", lambda src: 44100)
    monkeypatch.setattr(fc, "_probe_bit_depth", lambda src: 16)

    def fake_ffmpeg(cmd):
        # The last arg is the dst path; write a plausible (larger) output file.
        dst = Path(cmd[-1])
        dst.write_bytes(b"FAKE-AIFF-PCM" * 50)

    monkeypatch.setattr(fc, "_run_ffmpeg", fake_ffmpeg)

    engine = fc.FormatSwapEngine(db=db, master_db_path=master_db, backup_dir=backup_dir)
    return {
        "engine": engine,
        "db": db,
        "music": music,
        "files": files,
        "master_db": master_db,
        "backup_dir": backup_dir,
        "contents": contents,
    }


# ---------------------------------------------------------------------------
# Scope resolution
# ---------------------------------------------------------------------------


def test_resolve_scope_track_ids(env):
    items, label = env["engine"].resolve_scope({"track_ids": [1]})
    assert [c.id for c in items] == [1]
    assert "1 selected" in label


def test_resolve_scope_all_m4a(env):
    items, label = env["engine"].resolve_scope({"all_m4a": True})
    assert {c.id for c in items} == {1, 2}
    assert "all m4a" in label


def test_resolve_scope_path(env):
    items, _ = env["engine"].resolve_scope({"path": str(env["music"])})
    assert {c.id for c in items} == {1, 2}


def test_resolve_scope_playlist(env, monkeypatch):
    env["db"]._playlists = {7: env["contents"]}
    items, label = env["engine"].resolve_scope({"playlist_id": 7})
    assert {c.id for c in items} == {1, 2}
    assert "id=7" in label


def test_resolve_scope_none_raises(env):
    with pytest.raises(fc.FormatSwapError):
        env["engine"].resolve_scope({})


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


def test_dry_run_counts_and_no_writes(env):
    out = env["engine"].dry_run({"all_m4a": True}, "AIFF")
    assert out["dry_run"] is True
    assert out["convertible"] == 2
    assert out["target"] == "AIFF"
    assert out["estimated_target_mb"] >= out["source_mb"]  # AIFF expands
    # No files renamed / created.
    assert env["files"][1].exists()
    assert not (env["music"] / "track1.aiff").exists()


def test_dry_run_skips_already_target(env, tmp_path):
    # Add an AIFF row → counted as skipped when target is AIFF.
    aiff = env["music"] / "already.aiff"
    aiff.write_bytes(b"x")
    env["db"]._contents.append(FakeContent(3, aiff, file_type=12))
    out = env["engine"].dry_run({"all_m4a": False, "path": str(env["music"])}, "AIFF")
    assert out["convertible"] == 2  # the 2 m4a
    assert out["skipped"] >= 1  # the aiff


# ---------------------------------------------------------------------------
# run() — swap + manifest + content_id preservation
# ---------------------------------------------------------------------------


def test_run_converts_mutates_and_preserves_content_id(env):
    manifest = env["engine"].run({"all_m4a": True}, "AIFF")
    assert manifest["aborted"] is False
    assert len(manifest["tracks"]) == 2
    assert manifest["failed"] == 0

    for i in (1, 2):
        dst = env["music"] / f"track{i}.aiff"
        backup = env["music"] / f"track{i}.m4a.backup-{manifest['timestamp']}"
        assert dst.exists(), "converted file written"
        assert backup.exists(), "original preserved as .backup-<ts>"
        assert not (env["music"] / f"track{i}.m4a").exists(), "original renamed away"

    # content_id preserved (mutate-in-place, never delete+readd → beatgrid safe)
    updated_ids = {u[0] for u in env["db"].updated}
    assert updated_ids == {1, 2}
    for c in env["contents"]:
        assert c.folder_path.endswith(".aiff")
        assert c.file_type == 12  # AIFF (provisional code from codec)
        assert c.file_size > 0

    # Manifest written + readable
    mpath = env["backup_dir"] / f"manifest-{manifest['timestamp']}.json"
    assert mpath.exists()


def test_run_db_failure_recovers_that_track(env):
    # Track 2's update_content raises → its file pair must be restored, its row
    # attrs reverted, and it must NOT appear in the manifest.
    env["db"]._fail_ids = {2}
    manifest = env["engine"].run({"all_m4a": True}, "AIFF")
    assert manifest["failed"] == 1
    assert {t["id"] for t in manifest["tracks"]} == {1}

    # Track 2 fully restored
    assert env["files"][2].exists(), "original restored on DB failure"
    assert not (env["music"] / "track2.aiff").exists(), "converted file removed"
    c2 = next(c for c in env["contents"] if c.id == 2)
    assert c2.folder_path.endswith(".m4a")
    assert c2.file_type == 4

    # Track 1 still converted
    assert (env["music"] / "track1.aiff").exists()


def test_run_ffmpeg_failure_leaves_original_intact(env, monkeypatch):
    def boom(cmd):
        raise fc.FormatSwapError("ffmpeg exploded")

    monkeypatch.setattr(fc, "_run_ffmpeg", boom)
    manifest = env["engine"].run({"all_m4a": True}, "AIFF")
    assert manifest["failed"] == 2
    assert manifest["tracks"] == []
    for i in (1, 2):
        assert env["files"][i].exists(), "original untouched on ffmpeg failure"
        assert not (env["music"] / f"track{i}.aiff").exists()


def test_run_rekordbox_running_raises(env, monkeypatch):
    monkeypatch.setattr(fc, "_is_rekordbox_running", lambda: True)
    with pytest.raises(fc.FormatSwapError, match="Rekordbox is running"):
        env["engine"].run({"all_m4a": True}, "AIFF")
    assert env["files"][1].exists()  # no writes


def test_run_disk_abort_raises(env, monkeypatch):
    import collections

    Usage = collections.namedtuple("Usage", "total used free")
    monkeypatch.setattr(fc.shutil, "disk_usage", lambda p: Usage(1, 1, 0))
    with pytest.raises(fc.FormatSwapError, match="insufficient disk"):
        env["engine"].run({"all_m4a": True}, "AIFF")
    assert env["files"][1].exists()  # aborted before any write


def test_run_empty_scope_completes_noop(env):
    manifest = env["engine"].run({"track_ids": [999]}, "AIFF")
    assert manifest["tracks"] == []
    assert manifest["aborted"] is False


# ---------------------------------------------------------------------------
# rollback()
# ---------------------------------------------------------------------------


def test_rollback_restores_files_and_db(env):
    manifest = env["engine"].run({"all_m4a": True}, "AIFF")
    mid = f"manifest-{manifest['timestamp']}.json"

    # Corrupt the live master.db to prove rollback restores it from snapshot.
    env["master_db"].write_bytes(b"CORRUPTED")

    out = env["engine"].rollback(mid)
    assert out["restored_tracks"] == 2
    assert out["db_restored"] is True
    assert env["master_db"].read_bytes() == b"FAKE-MASTER-DB", "db restored from snapshot"
    for i in (1, 2):
        assert env["files"][i].exists(), "original renamed back"
        assert not (env["music"] / f"track{i}.aiff").exists(), "converted file deleted"


def test_rollback_rejects_path_traversal(env):
    for bad in ("../evil.json", "a/b.json", "/etc/passwd"):
        with pytest.raises(fc.FormatSwapError):
            env["engine"].rollback(bad)


def test_rollback_missing_manifest_raises(env):
    with pytest.raises(fc.FormatSwapError, match="not found"):
        env["engine"].rollback("manifest-nope.json")
