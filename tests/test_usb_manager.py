"""Tests for `app/usb_manager.py`.

Focus: the profile JSON roundtrip (the chief failure mode was profiles
silently disappearing after Windows reformat / drive-letter changes),
the XML attribute sanitiser, the Windows-reserved-filename guard, and
the per-drive lock-file context manager. No real USB needed; every
test scopes its filesystem state to `tmp_path` and monkeypatches the
module-level `PROFILES_FILE` Path.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from app import usb_manager
from app.usb_manager import (
    UsbProfileManager,
    UsbSyncEngine,
    locked_sync,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def isolated_profiles(tmp_path: Path, monkeypatch):
    """Redirect the on-disk profile store to a per-test scratch file
    AND stub out UsbDetector.scan so prune_duplicates doesn't try to
    enumerate real removable drives during the test."""
    store = tmp_path / "usb_profiles.json"
    monkeypatch.setattr(usb_manager, "PROFILES_FILE", store)
    monkeypatch.setattr(usb_manager.UsbDetector, "scan", classmethod(lambda cls: []))
    return store


@pytest.fixture
def sync_engine(tmp_path: Path):
    """Construct a UsbSyncEngine whose `usb_root` points inside tmp_path.
    The engine itself doesn't touch the filesystem on __init__ — paths
    are derived lazily — so this is cheap."""
    return UsbSyncEngine(
        local_db_path=str(tmp_path / "fake_local.db"),
        usb_drive=str(tmp_path),
        filesystem="NTFS",
    )


# ---------------------------------------------------------------------------
# UsbProfileManager roundtrip
# ---------------------------------------------------------------------------

class TestProfileRoundtrip:
    """save_profile / get_profile must persist and read back the same dict."""

    def test_save_then_get(self, isolated_profiles) -> None:
        profile = {
            "device_id": "abc123",
            "drive": "E:\\",
            "label": "PIONEER",
        }
        saved = UsbProfileManager.save_profile(profile)
        # save_profile fills required defaults:
        assert saved["device_id"] == "abc123"
        assert saved["sync_mode"] == "full"
        assert saved["type"] == "Collection"

        loaded = UsbProfileManager.get_profile("abc123")
        assert loaded is not None
        assert loaded["device_id"] == "abc123"
        assert loaded["drive"] == "E:\\"

    def test_get_unknown_device_returns_none(self, isolated_profiles) -> None:
        assert UsbProfileManager.get_profile("never_saved") is None

    def test_save_profile_updates_existing(self, isolated_profiles) -> None:
        """A second save for the same device_id should MERGE, not replace."""
        UsbProfileManager.save_profile(
            {"device_id": "x", "drive": "E:\\", "label": "L1"}
        )
        UsbProfileManager.save_profile(
            {"device_id": "x", "label": "L1-renamed"}
        )
        loaded = UsbProfileManager.get_profile("x")
        # The previously-stored "drive" should still be there (merge).
        assert loaded["drive"] == "E:\\"
        assert loaded["label"] == "L1-renamed"

    def test_settings_roundtrip(self, isolated_profiles) -> None:
        """get_settings / save_settings pair handles the small global block."""
        # Default when file missing:
        assert UsbProfileManager.get_settings() == {"auto_sync_on_startup": False}

        UsbProfileManager.save_settings(
            {"auto_sync_on_startup": True, "feature_flag": "exp"}
        )
        out = UsbProfileManager.get_settings()
        assert out["auto_sync_on_startup"] is True
        assert out["feature_flag"] == "exp"

    def test_save_profile_persists_to_disk(self, isolated_profiles) -> None:
        """The store file should exist after one save and be valid JSON."""
        UsbProfileManager.save_profile({"device_id": "fs_test", "drive": "F:\\"})
        assert isolated_profiles.exists()
        import json
        data = json.loads(isolated_profiles.read_text(encoding="utf-8"))
        assert "fs_test" in data["profiles"]


# ---------------------------------------------------------------------------
# _xml_safe
# ---------------------------------------------------------------------------

class TestXmlSafe:
    """ASCII control chars below 0x20 (except \\t \\n \\r) are illegal in
    XML 1.0 — Rekordbox track names sometimes contain them and break
    `xml.etree.ElementTree`'s round-trip."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("Hello\x13World", "HelloWorld"),  # DC3 stripped
            ("\x00null\x01start\x02heading", "nullstartheading"),
            ("Mixed\x05Bell\x07Sep", "MixedBellSep"),
        ],
    )
    def test_strips_control_chars(self, raw: str, expected: str) -> None:
        assert UsbSyncEngine._xml_safe(raw) == expected

    @pytest.mark.parametrize(
        "preserved",
        ["tab\there", "line\nbreak", "CR\rhere", "plain text", "üñîçødé"],
    )
    def test_preserves_legal_chars(self, preserved: str) -> None:
        assert UsbSyncEngine._xml_safe(preserved) == preserved

    def test_empty_input(self) -> None:
        assert UsbSyncEngine._xml_safe("") == ""

    def test_none_input(self) -> None:
        """None must coerce to empty (defensive — Rekordbox attrs can be missing)."""
        assert UsbSyncEngine._xml_safe(None) == ""

    def test_del_char_stripped(self) -> None:
        """ASCII 0x7F (DEL) is in the disallowed range."""
        assert UsbSyncEngine._xml_safe("front\x7Fback") == "frontback"


# ---------------------------------------------------------------------------
# _clean_filename — Windows reserved + trailing dots
# ---------------------------------------------------------------------------

class TestCleanFilename:
    """Reserved Windows device names and trailing dots/spaces must be neutralised."""

    @pytest.mark.parametrize(
        "reserved",
        [
            "CON", "PRN", "AUX", "NUL",
            "COM1", "COM2", "COM9",
            "LPT1", "LPT5", "LPT9",
            # Case insensitivity — the check is on .upper():
            "con", "Prn", "lpt3",
        ],
    )
    def test_reserved_names_prefixed(self, sync_engine, reserved: str) -> None:
        out = sync_engine._clean_filename(reserved)
        assert out.upper() != reserved.upper(), (
            f"reserved name {reserved!r} returned unchanged — Windows will refuse it"
        )
        # The convention is an underscore prefix:
        assert out.startswith("_")

    def test_trailing_dot_stripped(self, sync_engine) -> None:
        """Windows silently drops trailing dots; we must mirror that."""
        assert sync_engine._clean_filename("foo.") == "foo"
        assert sync_engine._clean_filename("bar..") == "bar"
        assert sync_engine._clean_filename("baz...") == "baz"

    def test_trailing_space_stripped(self, sync_engine) -> None:
        assert sync_engine._clean_filename("hello ") == "hello"
        assert sync_engine._clean_filename("hello   ") == "hello"

    def test_leading_dot_stripped(self, sync_engine) -> None:
        assert sync_engine._clean_filename(".foo") == "foo"

    @pytest.mark.parametrize(
        "raw, banned",
        [
            ('foo/bar', '/'),
            ('foo\\bar', '\\'),
            ('foo:bar', ':'),
            ('foo*bar', '*'),
            ('foo?bar', '?'),
            ('foo"bar', '"'),
            ('foo<bar', '<'),
            ('foo>bar', '>'),
            ('foo|bar', '|'),
        ],
    )
    def test_illegal_path_chars_replaced(self, sync_engine, raw, banned) -> None:
        cleaned = sync_engine._clean_filename(raw)
        assert banned not in cleaned

    def test_empty_returns_unknown(self, sync_engine) -> None:
        """Empty / falsy input must fall back to a non-empty default."""
        assert sync_engine._clean_filename("") == "Unknown"
        assert sync_engine._clean_filename(None) == "Unknown"


# ---------------------------------------------------------------------------
# locked_sync context manager
# ---------------------------------------------------------------------------

class TestLockedSync:
    """Creates `.rbep_sync_lock`; refuses re-entry; releases on exit."""

    def test_creates_lock_on_enter(self, tmp_path: Path) -> None:
        lock = tmp_path / ".rbep_sync_lock"
        assert not lock.exists()
        with locked_sync(tmp_path):
            assert lock.exists(), "lock file should be present inside the with-block"

    def test_releases_lock_on_exit(self, tmp_path: Path) -> None:
        lock = tmp_path / ".rbep_sync_lock"
        with locked_sync(tmp_path):
            pass
        assert not lock.exists(), "lock file should be removed after exit"

    def test_concurrent_acquire_raises(self, tmp_path: Path) -> None:
        """A second `locked_sync` over the same root while the first
        is still active must raise — that's the whole point."""
        with locked_sync(tmp_path):
            with pytest.raises(Exception, match="locked"):
                with locked_sync(tmp_path):
                    pass

    def test_lock_released_after_exception(self, tmp_path: Path) -> None:
        """Even if the body raises, the lock file must be cleaned up."""
        lock = tmp_path / ".rbep_sync_lock"
        with pytest.raises(ValueError):
            with locked_sync(tmp_path):
                raise ValueError("simulated failure")
        assert not lock.exists()

    def test_stale_lock_is_replaced(self, tmp_path: Path, monkeypatch) -> None:
        """A lock file older than 10 minutes is treated as stale and replaced
        rather than refused — the previous sync evidently crashed without
        cleanup. We forge an old mtime and verify re-acquire succeeds."""
        import os
        import time
        lock = tmp_path / ".rbep_sync_lock"
        lock.touch()
        # Backdate by 15 minutes:
        very_old = time.time() - 900
        os.utime(lock, (very_old, very_old))
        # Should succeed (not raise) — stale lock auto-cleaned.
        with locked_sync(tmp_path):
            assert lock.exists()  # fresh lock now belongs to us
        assert not lock.exists()
