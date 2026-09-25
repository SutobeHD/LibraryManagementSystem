"""Tests for app.library_format_swap.

Covers the parts that can be tested without a real master.db: target config,
FFmpeg command shape, dry-run on empty scopes, manifest listing on empty
backup tree, and rollback against a hand-crafted manifest.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.library_format_swap import (
    DISK_HARD_ABORT_FACTOR,
    DISK_WARN_FACTOR,
    FILE_TYPE_AIFF,
    FILE_TYPE_FLAC,
    FILE_TYPE_M4A,
    FILE_TYPE_MP3,
    FILE_TYPE_WAV,
    PER_TRACK_TIMEOUT_SEC,
    TARGET_CONFIG,
    WATCHDOG_INTERVAL,
    FormatSwapEngine,
    _build_ffmpeg_cmd,
)


class TestTargetConfig:
    def test_all_four_targets_present(self):
        assert set(TARGET_CONFIG.keys()) == {"aiff", "flac", "wav", "mp3"}

    def test_each_target_has_required_keys(self):
        for name, cfg in TARGET_CONFIG.items():
            assert "ext" in cfg, f"{name} missing ext"
            assert "codec_args" in cfg, f"{name} missing codec_args"
            assert "file_type" in cfg, f"{name} missing file_type"
            assert "expansion_ratio" in cfg, f"{name} missing expansion_ratio"
            assert cfg["ext"].startswith("."), f"{name} ext must start with dot"
            assert isinstance(cfg["codec_args"], list), f"{name} codec_args not list"
            assert cfg["codec_args"][0] == "-c:a", f"{name} codec_args[0] not -c:a"
            assert isinstance(cfg["file_type"], int), f"{name} file_type not int"

    def test_file_type_codes(self):
        assert TARGET_CONFIG["aiff"]["file_type"] == FILE_TYPE_AIFF
        assert TARGET_CONFIG["flac"]["file_type"] == FILE_TYPE_FLAC
        assert TARGET_CONFIG["wav"]["file_type"] == FILE_TYPE_WAV
        assert TARGET_CONFIG["mp3"]["file_type"] == FILE_TYPE_MP3

    def test_expansion_ratios_plausible(self):
        # AIFF/WAV uncompressed PCM ~5x AAC; FLAC ~2.5x; MP3 (re-encode) <1x
        assert TARGET_CONFIG["aiff"]["expansion_ratio"] >= 4
        assert TARGET_CONFIG["wav"]["expansion_ratio"] >= 4
        assert TARGET_CONFIG["flac"]["expansion_ratio"] >= 2
        assert TARGET_CONFIG["mp3"]["expansion_ratio"] < 1


class TestConstants:
    def test_timeout_above_rule_default_with_documented_reason(self):
        # OQ3 — 600s defended in research; deviates from coding-rules.md 30s default
        assert PER_TRACK_TIMEOUT_SEC == 600

    def test_disk_thresholds_from_oq4(self):
        assert DISK_HARD_ABORT_FACTOR == 1.5
        assert DISK_WARN_FACTOR == 1.2
        assert DISK_HARD_ABORT_FACTOR > DISK_WARN_FACTOR

    def test_watchdog_interval(self):
        assert WATCHDOG_INTERVAL >= 10  # too small = thrash; too big = miss restarts

    def test_filetype_m4a_is_4(self):
        # safe_format_swap.py-proven Pioneer convention
        assert FILE_TYPE_M4A == 4


class TestFfmpegCommand:
    @pytest.mark.parametrize(
        "target,expected_codec",
        [("aiff", "pcm_s16le"), ("wav", "pcm_s16le"), ("flac", "flac"), ("mp3", "libmp3lame")],
    )
    def test_ffmpeg_cmd_codec_for_target(self, target, expected_codec):
        src = Path("/tmp/src.m4a")
        dst = Path("/tmp/dst" + TARGET_CONFIG[target]["ext"])
        cmd = _build_ffmpeg_cmd(src, dst, 48000, target)
        assert "-c:a" in cmd
        idx = cmd.index("-c:a")
        assert cmd[idx + 1] == expected_codec

    def test_ffmpeg_cmd_has_vn_to_drop_cover_art(self):
        # Cover-art-crash regression: FFmpeg refuses AIFF + PNG output without -vn
        cmd = _build_ffmpeg_cmd(Path("/tmp/s.m4a"), Path("/tmp/d.aiff"), 44100, "aiff")
        assert "-vn" in cmd

    def test_ffmpeg_cmd_locks_sample_rate_to_source(self):
        cmd = _build_ffmpeg_cmd(Path("/tmp/s.m4a"), Path("/tmp/d.aiff"), 96000, "aiff")
        assert "-ar" in cmd
        assert "96000" in cmd
        idx = cmd.index("-ar")
        assert cmd[idx + 1] == "96000"

    def test_ffmpeg_cmd_overwrite_flag(self):
        cmd = _build_ffmpeg_cmd(Path("/tmp/s.m4a"), Path("/tmp/d.aiff"), 48000, "aiff")
        assert "-y" in cmd

    def test_ffmpeg_cmd_preserves_metadata(self):
        cmd = _build_ffmpeg_cmd(Path("/tmp/s.m4a"), Path("/tmp/d.aiff"), 48000, "aiff")
        assert "-map_metadata" in cmd

    def test_mp3_target_includes_quality_arg(self):
        cmd = _build_ffmpeg_cmd(Path("/tmp/s.m4a"), Path("/tmp/d.mp3"), 48000, "mp3")
        assert "-q:a" in cmd
        idx = cmd.index("-q:a")
        assert cmd[idx + 1] == "0"  # highest VBR quality


class TestEngineConstructor:
    def test_rejects_unknown_target(self):
        live_db = MagicMock()
        with pytest.raises(ValueError, match="Unknown target"):
            FormatSwapEngine(live_db, "ogg")  # type: ignore[arg-type]

    def test_accepts_all_four_targets(self):
        live_db = MagicMock()
        for t in ("aiff", "flac", "wav", "mp3"):
            engine = FormatSwapEngine(live_db, t)
            assert engine.target == t
            assert engine.target_ext == TARGET_CONFIG[t]["ext"]


class TestScopeEnumeration:
    def test_unknown_scope_kind_raises(self):
        engine = FormatSwapEngine(MagicMock(), "aiff")
        with pytest.raises(ValueError, match="Unknown scope"):
            engine.enumerate_scope({"kind": "moon"})

    def test_track_ids_scope_with_empty_list(self):
        live_db = MagicMock()
        live_db.db.get_content_by_id.return_value = None
        engine = FormatSwapEngine(live_db, "aiff")
        result = engine.enumerate_scope({"kind": "track_ids", "ids": []})
        assert result == []

    def test_playlist_scope_requires_id(self):
        engine = FormatSwapEngine(MagicMock(), "aiff")
        with pytest.raises(ValueError, match="playlist_id"):
            engine.enumerate_scope({"kind": "playlist"})

    def test_path_scope_requires_path(self):
        engine = FormatSwapEngine(MagicMock(), "aiff")
        with pytest.raises(ValueError, match="path"):
            engine.enumerate_scope({"kind": "path"})

    def test_skips_already_target_ext(self):
        live_db = MagicMock()
        c1 = MagicMock(folder_path="/a/song.m4a", file_type=4, file_size=100, id="1")
        c1.rb_local_deleted = False
        c2 = MagicMock(folder_path="/a/song.aiff", file_type=6, file_size=500, id="2")
        c2.rb_local_deleted = False
        live_db.db.get_contents.return_value = [c1, c2]
        engine = FormatSwapEngine(live_db, "aiff")
        # Filter step
        assert engine._track_needs_conversion(c1) is True
        assert engine._track_needs_conversion(c2) is False


class TestDryRun:
    def test_empty_scope_returns_zero(self):
        live_db = MagicMock()
        live_db.db.get_contents.return_value = []
        live_db.db.get_content_by_id.return_value = None
        engine = FormatSwapEngine(live_db, "aiff")
        result = engine.dry_run({"kind": "track_ids", "ids": []})
        assert result.tracks == []
        assert result.total_source_mb == 0.0
        assert result.estimated_target_mb == 0.0
        assert result.drive_check_pass is True  # nothing requested = pass

    def test_invalid_scope_returns_error(self):
        live_db = MagicMock()
        live_db.db.get_contents.return_value = []
        engine = FormatSwapEngine(live_db, "aiff")
        result = engine.dry_run({"kind": "path"})  # missing path
        assert result.error is not None
        assert result.tracks == []


class TestManifestListing:
    def test_empty_backup_dir_returns_empty(self, tmp_path, monkeypatch):
        # Redirect _backup_root to an empty tmp dir
        from app import library_format_swap as mod

        monkeypatch.setattr(mod, "_backup_root", lambda: tmp_path / "no-such-dir")
        assert FormatSwapEngine.list_manifests() == []

    def test_lists_manifests_newest_first(self, tmp_path, monkeypatch):
        from app import library_format_swap as mod

        backup_root = tmp_path / "backups"
        backup_root.mkdir()
        monkeypatch.setattr(mod, "_backup_root", lambda: backup_root)

        for ts in ("20260601-100000", "20260602-200000", "20260603-300000"):
            sub = backup_root / ts
            sub.mkdir()
            (sub / f"manifest-{ts}.json").write_text(
                json.dumps(
                    {
                        "timestamp": ts,
                        "target": "aiff",
                        "tracks": [],
                        "scope": {"kind": "all_m4a"},
                        "batch_id": ts,
                    }
                )
            )

        result = FormatSwapEngine.list_manifests()
        assert len(result) == 3
        # Sorted newest-first
        assert result[0]["timestamp"] == "20260603-300000"
        assert result[-1]["timestamp"] == "20260601-100000"
        assert all(r["target"] == "aiff" for r in result)
        assert all(r["scope_kind"] == "all_m4a" for r in result)


class TestRollback:
    def test_rejects_missing_manifest(self, tmp_path, monkeypatch):
        from app import library_format_swap as mod

        monkeypatch.setattr(mod, "_backup_root", lambda: tmp_path / "none")
        monkeypatch.setattr(mod, "_check_rekordbox_running", lambda: False)
        engine = FormatSwapEngine(MagicMock(), "aiff")
        with pytest.raises(FileNotFoundError, match="manifest not found"):
            engine.rollback("manifest-doesnotexist.json")

    def test_rejects_when_rekordbox_running(self):
        from app import library_format_swap as mod

        with patch.object(mod, "_check_rekordbox_running", return_value=True):
            engine = FormatSwapEngine(MagicMock(), "aiff")
            with pytest.raises(RuntimeError, match="Rekordbox"):
                engine.rollback("anything.json")

    def test_restores_audio_files_from_manifest(self, tmp_path, monkeypatch):
        from app import library_format_swap as mod

        # Build a fake batch on disk
        music = tmp_path / "music"
        music.mkdir()
        backups = tmp_path / "backups" / "20260101-000000"
        backups.mkdir(parents=True)

        # The "renamed-out" m4a backup + "converted" aiff
        orig_path = music / "song.m4a"
        backup_path = music / "song.m4a.backup-20260101-000000"
        new_path = music / "song.aiff"
        backup_path.write_bytes(b"original m4a bytes")
        new_path.write_bytes(b"converted aiff bytes")

        manifest = {
            "timestamp": "20260101-000000",
            "db_backups": {},  # no DB ops for this test
            "tracks": [
                {
                    "id": "1",
                    "original": {
                        "folder_path": str(orig_path),
                        "file_name_l": "song.m4a",
                        "file_type": 4,
                        "file_size": 18,
                        "audio_backup": str(backup_path),
                    },
                    "new": {
                        "folder_path": str(new_path),
                        "file_name_l": "song.aiff",
                        "file_type": 6,
                        "file_size": 21,
                    },
                }
            ],
        }
        manifest_file = backups / "manifest-20260101-000000.json"
        manifest_file.write_text(json.dumps(manifest))

        monkeypatch.setattr(mod, "_backup_root", lambda: tmp_path / "backups")
        monkeypatch.setattr(mod, "_check_rekordbox_running", lambda: False)

        engine = FormatSwapEngine(MagicMock(), "aiff")
        result = engine.rollback("manifest-20260101-000000.json")

        assert result["audio_restored"] == 1
        assert result["target_deleted"] == 1
        assert orig_path.exists()
        assert orig_path.read_bytes() == b"original m4a bytes"
        assert not new_path.exists()
        assert not backup_path.exists()  # renamed away


class TestBatchTracking:
    def test_get_batch_returns_none_for_unknown_id(self):
        from app.library_format_swap import get_batch

        assert get_batch("nonexistent-batch-id") is None
