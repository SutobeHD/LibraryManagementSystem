"""Tests for `app/services.py`.

Focus: the file-IO error paths that Phase 1.5 stopped swallowing
(SettingsManager.load, MetadataManager.load), the SystemGuard process
probe, and the small `clean_tag` text utility. Mocking strategy:
redirect class-level Path attributes via monkeypatch so we never touch
the real settings.json / metadata_mappings.json. Everywhere a real
filesystem call would still happen, we use `tmp_path`.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.services import (
    MetadataManager,
    SettingsManager,
    SystemGuard,
    XMLProcessor,
)

# ---------------------------------------------------------------------------
# SettingsManager
# ---------------------------------------------------------------------------

class TestSettingsManager:
    """`load()` must never raise; falls back to `cls.DEFAULT` on any error."""

    def test_load_missing_file_returns_defaults(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        monkeypatch.setattr(SettingsManager, "CONFIG", tmp_path / "missing.json")
        result = SettingsManager.load()
        assert result == SettingsManager.DEFAULT

    def test_load_malformed_json_returns_defaults(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        bad = tmp_path / "settings.json"
        bad.write_text("{ this is not json", encoding="utf-8")
        monkeypatch.setattr(SettingsManager, "CONFIG", bad)
        result = SettingsManager.load()
        assert result == SettingsManager.DEFAULT

    def test_load_empty_file_returns_defaults(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        bad = tmp_path / "settings.json"
        bad.write_text("", encoding="utf-8")
        monkeypatch.setattr(SettingsManager, "CONFIG", bad)
        result = SettingsManager.load()
        assert result == SettingsManager.DEFAULT

    def test_load_valid_json_merges_with_defaults(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        cfg = tmp_path / "settings.json"
        cfg.write_text('{"theme": "light", "auto_snap": false}', encoding="utf-8")
        monkeypatch.setattr(SettingsManager, "CONFIG", cfg)
        result = SettingsManager.load()
        # User keys override:
        assert result["theme"] == "light"
        assert result["auto_snap"] is False
        # Defaults still present:
        assert result["backup_retention_days"] == 7

    def test_default_contract_pins_critical_keys(self) -> None:
        """Other modules read these keys via SettingsManager.load() — if
        someone renames or removes them in DEFAULT, those callers
        suddenly fail with a KeyError or silent wrong-default behaviour."""
        d = SettingsManager.DEFAULT
        for key in (
            "backup_retention_days", "theme", "hide_streaming",
            "artist_view_threshold", "last_lib_mode",
        ):
            assert key in d, f"DEFAULT lost the {key!r} key"


# ---------------------------------------------------------------------------
# MetadataManager
# ---------------------------------------------------------------------------

class TestMetadataManager:
    """`load()` returns the empty triple on missing file; add_mapping /
    get_mapped_name roundtrip cleanly."""

    @pytest.fixture
    def isolated_metadata(self, tmp_path: Path, monkeypatch):
        store = tmp_path / "metadata_mappings.json"
        monkeypatch.setattr(MetadataManager, "MAPPINGS_FILE", store)
        return store

    def test_load_missing_file_returns_empty_triple(
        self, isolated_metadata
    ) -> None:
        result = MetadataManager.load()
        assert result == {"artists": {}, "labels": {}, "albums": {}}

    def test_load_malformed_json_returns_empty_triple(
        self, isolated_metadata
    ) -> None:
        isolated_metadata.write_text("not json at all", encoding="utf-8")
        result = MetadataManager.load()
        assert result == {"artists": {}, "labels": {}, "albums": {}}

    def test_add_mapping_then_get_mapped_name(
        self, isolated_metadata
    ) -> None:
        MetadataManager.add_mapping("artists", "DJ_x", "DJ X")
        assert MetadataManager.get_mapped_name("artists", "DJ_x") == "DJ X"

    def test_get_mapped_name_passthrough_on_miss(
        self, isolated_metadata
    ) -> None:
        """Unmapped names return their input unchanged."""
        assert MetadataManager.get_mapped_name("artists", "Anonymous") == "Anonymous"

    def test_add_mapping_creates_unknown_category(
        self, isolated_metadata
    ) -> None:
        """Asking for a brand-new category creates it on demand."""
        MetadataManager.add_mapping("genres", "DnB", "Drum & Bass")
        assert MetadataManager.get_mapped_name("genres", "DnB") == "Drum & Bass"

    def test_add_mapping_persists_across_load(
        self, isolated_metadata
    ) -> None:
        """The whole point: written mappings survive process restart."""
        MetadataManager.add_mapping("labels", "ABC", "ABC Records")
        # Drop and reload via load():
        loaded = MetadataManager.load()
        assert loaded["labels"]["ABC"] == "ABC Records"


# ---------------------------------------------------------------------------
# SystemGuard
# ---------------------------------------------------------------------------

class TestSystemGuard:
    """`is_rekordbox_running` walks psutil — must tolerate weird per-process
    info dicts without crashing."""

    def test_returns_true_when_rekordbox_seen(self, monkeypatch) -> None:
        fake_proc = MagicMock()
        fake_proc.info = {"name": "rekordbox.exe"}
        fake_proc.pid = 1234
        monkeypatch.setattr(
            "app.services.psutil.process_iter", lambda fields: [fake_proc]
        )
        assert SystemGuard.is_rekordbox_running() is True

    def test_returns_false_when_no_match(self, monkeypatch) -> None:
        fake_proc = MagicMock()
        fake_proc.info = {"name": "explorer.exe"}
        fake_proc.pid = 4321
        monkeypatch.setattr(
            "app.services.psutil.process_iter", lambda fields: [fake_proc]
        )
        assert SystemGuard.is_rekordbox_running() is False

    def test_handles_none_name(self, monkeypatch) -> None:
        """psutil sometimes returns `name=None` for kernel-level processes.
        The walker must skip them, not AttributeError."""
        bad = MagicMock()
        bad.info = {"name": None}
        bad.pid = 1
        good = MagicMock()
        good.info = {"name": "RekordboxAgent.exe"}
        good.pid = 2
        monkeypatch.setattr(
            "app.services.psutil.process_iter", lambda fields: [bad, good]
        )
        assert SystemGuard.is_rekordbox_running() is True

    def test_handles_missing_name_key(self, monkeypatch) -> None:
        """If the info dict somehow lacks the 'name' key, skip the proc."""
        # A bare dict raises KeyError on ['name'] — replicate that.
        empty_proc = MagicMock()
        empty_proc.info = {}
        empty_proc.pid = 99
        monkeypatch.setattr(
            "app.services.psutil.process_iter", lambda fields: [empty_proc]
        )
        # Should not raise; just return False because nothing matched.
        assert SystemGuard.is_rekordbox_running() is False

    def test_returns_false_on_empty_iter(self, monkeypatch) -> None:
        monkeypatch.setattr(
            "app.services.psutil.process_iter", lambda fields: []
        )
        assert SystemGuard.is_rekordbox_running() is False


# ---------------------------------------------------------------------------
# XMLProcessor.clean_tag
# ---------------------------------------------------------------------------

class TestCleanTag:
    """`clean_tag` strips REMOVE_STRINGS markers and collapses whitespace."""

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("Song Title (Original Mix)", "Song Title"),
            ("Song Title (Extended Mix)", "Song Title"),
            ("Song Title Original Mix", "Song Title"),
            ("Already Clean", "Already Clean"),
            ("  leading and trailing  ", "leading and trailing"),
            ("Multiple  spaces   inside", "Multiple spaces inside"),
            ("", ""),
        ],
    )
    def test_clean_tag_pairs(self, raw: str, expected: str) -> None:
        assert XMLProcessor.clean_tag(raw) == expected

    def test_clean_tag_none_input(self) -> None:
        """Passing None must return empty string (defensive — used in
        bulk-rename pipelines where attribute values may be missing)."""
        assert XMLProcessor.clean_tag(None) == ""

    def test_repeated_removal(self) -> None:
        """Both markers in one string are both stripped."""
        cleaned = XMLProcessor.clean_tag("A (Original Mix) (Extended Mix)")
        assert "Original Mix" not in cleaned
        assert "Extended Mix" not in cleaned
        assert cleaned.startswith("A")
