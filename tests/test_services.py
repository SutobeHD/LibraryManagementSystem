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

# app.services transitively imports app.database -> app.live_database -> rbox.
# Skip on platforms without pyrekordbox (Linux CI runners).
pytest.importorskip("rbox", reason="pyrekordbox not installed on this platform")

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

    def test_load_missing_file_returns_defaults(self, tmp_path: Path, monkeypatch) -> None:
        monkeypatch.setattr(SettingsManager, "CONFIG", tmp_path / "missing.json")
        result = SettingsManager.load()
        assert result == SettingsManager.DEFAULT

    def test_load_malformed_json_returns_defaults(self, tmp_path: Path, monkeypatch) -> None:
        bad = tmp_path / "settings.json"
        bad.write_text("{ this is not json", encoding="utf-8")
        monkeypatch.setattr(SettingsManager, "CONFIG", bad)
        result = SettingsManager.load()
        assert result == SettingsManager.DEFAULT

    def test_load_empty_file_returns_defaults(self, tmp_path: Path, monkeypatch) -> None:
        bad = tmp_path / "settings.json"
        bad.write_text("", encoding="utf-8")
        monkeypatch.setattr(SettingsManager, "CONFIG", bad)
        result = SettingsManager.load()
        assert result == SettingsManager.DEFAULT

    def test_load_valid_json_merges_with_defaults(self, tmp_path: Path, monkeypatch) -> None:
        cfg = tmp_path / "settings.json"
        cfg.write_text('{"theme": "light", "auto_snap": false}', encoding="utf-8")
        monkeypatch.setattr(SettingsManager, "CONFIG", cfg)
        result = SettingsManager.load()
        # User keys override:
        assert result["theme"] == "light"
        assert result["auto_snap"] is False
        # Defaults still present:
        assert result["theme"] == "light"  # explicit user override survives merge
        assert "default_export_format" in result  # default key still merged in

    def test_default_contract_pins_critical_keys(self) -> None:
        """Other modules read these keys via SettingsManager.load() — if
        someone renames or removes them in DEFAULT, those callers
        suddenly fail with a KeyError or silent wrong-default behaviour."""
        d = SettingsManager.DEFAULT
        for key in (
            "theme",
            "hide_streaming",
            "artist_view_threshold",
            "last_lib_mode",
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

    def test_load_missing_file_returns_empty_triple(self, isolated_metadata) -> None:
        result = MetadataManager.load()
        assert result == {"artists": {}, "labels": {}, "albums": {}}

    def test_load_malformed_json_returns_empty_triple(self, isolated_metadata) -> None:
        isolated_metadata.write_text("not json at all", encoding="utf-8")
        result = MetadataManager.load()
        assert result == {"artists": {}, "labels": {}, "albums": {}}

    def test_add_mapping_then_get_mapped_name(self, isolated_metadata) -> None:
        MetadataManager.add_mapping("artists", "DJ_x", "DJ X")
        assert MetadataManager.get_mapped_name("artists", "DJ_x") == "DJ X"

    def test_get_mapped_name_passthrough_on_miss(self, isolated_metadata) -> None:
        """Unmapped names return their input unchanged."""
        assert MetadataManager.get_mapped_name("artists", "Anonymous") == "Anonymous"

    def test_add_mapping_creates_unknown_category(self, isolated_metadata) -> None:
        """Asking for a brand-new category creates it on demand."""
        MetadataManager.add_mapping("genres", "DnB", "Drum & Bass")
        assert MetadataManager.get_mapped_name("genres", "DnB") == "Drum & Bass"

    def test_add_mapping_persists_across_load(self, isolated_metadata) -> None:
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
        monkeypatch.setattr("app.services.psutil.process_iter", lambda fields: [fake_proc])
        assert SystemGuard.is_rekordbox_running() is True

    def test_returns_false_when_no_match(self, monkeypatch) -> None:
        fake_proc = MagicMock()
        fake_proc.info = {"name": "explorer.exe"}
        fake_proc.pid = 4321
        monkeypatch.setattr("app.services.psutil.process_iter", lambda fields: [fake_proc])
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
        monkeypatch.setattr("app.services.psutil.process_iter", lambda fields: [bad, good])
        assert SystemGuard.is_rekordbox_running() is True

    def test_handles_missing_name_key(self, monkeypatch) -> None:
        """If the info dict somehow lacks the 'name' key, skip the proc."""
        # A bare dict raises KeyError on ['name'] — replicate that.
        empty_proc = MagicMock()
        empty_proc.info = {}
        empty_proc.pid = 99
        monkeypatch.setattr("app.services.psutil.process_iter", lambda fields: [empty_proc])
        # Should not raise; just return False because nothing matched.
        assert SystemGuard.is_rekordbox_running() is False

    def test_returns_false_on_empty_iter(self, monkeypatch) -> None:
        monkeypatch.setattr("app.services.psutil.process_iter", lambda fields: [])
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


# ---------------------------------------------------------------------------
# SettingsManager — atomic save
# ---------------------------------------------------------------------------


class TestSettingsAtomicSave:
    """The save path is atomic: tmp file + os.replace. A crash mid-write
    must not leave ``settings.json`` truncated."""

    def test_save_writes_complete_json(self, tmp_path: Path, monkeypatch) -> None:
        cfg = tmp_path / "settings.json"
        monkeypatch.setattr(SettingsManager, "CONFIG", cfg)
        SettingsManager.save({"theme": "dark", "auto_snap": True})
        import json

        loaded = json.loads(cfg.read_text(encoding="utf-8"))
        assert loaded["theme"] == "dark"
        assert loaded["auto_snap"] is True

    def test_save_leaves_no_tmp_files(self, tmp_path: Path, monkeypatch) -> None:
        cfg = tmp_path / "settings.json"
        monkeypatch.setattr(SettingsManager, "CONFIG", cfg)
        SettingsManager.save({"theme": "dark"})
        leftovers = [p for p in tmp_path.iterdir() if p.name != "settings.json"]
        assert leftovers == []

    def test_save_overwrites_existing_file(self, tmp_path: Path, monkeypatch) -> None:
        cfg = tmp_path / "settings.json"
        cfg.write_text('{"theme": "old"}', encoding="utf-8")
        monkeypatch.setattr(SettingsManager, "CONFIG", cfg)
        SettingsManager.save({"theme": "new"})
        import json

        assert json.loads(cfg.read_text(encoding="utf-8"))["theme"] == "new"


# ---------------------------------------------------------------------------
# LibraryTools.generate_smart_playlists — "By Artist" retired (T-11)
# ---------------------------------------------------------------------------


class _FakePlaylistDb:
    """Minimal stand-in for `app.services.db`: tracks, playlists, create, save."""

    def __init__(self, tracks: dict | None = None, playlists: list | None = None) -> None:
        self.tracks = tracks or {}
        self.playlists = playlists if playlists is not None else []
        self.saved = 0
        self._seq = 0

    def create_playlist(self, name, parent_id="ROOT", is_folder=False, tracks=None):
        self._seq += 1
        node = {
            "ID": f"pl_{self._seq}",
            "Name": name,
            "Type": "0" if is_folder else "1",
            "ParentID": parent_id,
            "Tracks": list(tracks or []),
        }
        self.playlists.append(node)
        return node

    def save(self) -> None:
        self.saved += 1


def _library(n_artist: int = 6, n_label: int = 6) -> dict:
    tracks = {}
    for i in range(n_artist):
        tracks[f"a{i}"] = {"Artist": "boys noize", "Label": "Boysnoize Records"}
    for i in range(n_label):
        tracks[f"b{i}"] = {"Artist": "Boys Noize", "Label": "Boysnoize Records"}
    return tracks


class TestSmartPlaylistsRetiredArtistBranch:
    """The raw-string "By Artist" generator is gone; "By Label" is untouched."""

    def test_no_by_artist_folder_is_created(self, monkeypatch) -> None:
        from app import services

        fake = _FakePlaylistDb(tracks=_library())
        monkeypatch.setattr(services, "db", fake)

        services.LibraryTools.generate_smart_playlists(artist_threshold=1, label_threshold=1)

        names = [p["Name"] for p in fake.playlists]
        assert "By Artist" not in names
        assert "boys noize" not in names
        assert "Boys Noize" not in names

    def test_by_label_still_generated(self, monkeypatch) -> None:
        from app import services

        fake = _FakePlaylistDb(tracks=_library())
        monkeypatch.setattr(services, "db", fake)

        report = services.LibraryTools.generate_smart_playlists(label_threshold=5)

        names = [p["Name"] for p in fake.playlists]
        assert "By Label" in names
        assert "Boysnoize Records" in names
        assert report["labels_created"] == 1
        assert report["ok"] is True
        assert fake.saved == 1

    def test_label_threshold_still_filters(self, monkeypatch) -> None:
        from app import services

        fake = _FakePlaylistDb(tracks=_library(n_artist=1, n_label=1))
        monkeypatch.setattr(services, "db", fake)

        report = services.LibraryTools.generate_smart_playlists(label_threshold=5)

        assert report["labels_created"] == 0
        assert "Boysnoize Records" not in [p["Name"] for p in fake.playlists]

    def test_report_points_at_the_artist_hub(self, monkeypatch) -> None:
        from app import services

        fake = _FakePlaylistDb(tracks=_library())
        monkeypatch.setattr(services, "db", fake)

        report = services.LibraryTools.generate_smart_playlists()

        assert report["artists"]["source"] == "artist_hub"
        assert report["artists"]["endpoint"] == "/api/artists/projection/sync"

    def test_existing_by_artist_folder_is_reported_never_deleted(self, monkeypatch) -> None:
        """A user who already ran the old generator keeps their playlists."""
        from app import services

        existing = [
            {"ID": "auto", "Name": "Auto Playlists", "Type": "0", "ParentID": "ROOT"},
            {"ID": "byart", "Name": "By Artist", "Type": "0", "ParentID": "auto"},
            {"ID": "p1", "Name": "boys noize", "Type": "1", "ParentID": "byart"},
            {"ID": "p2", "Name": "Boys Noize", "Type": "1", "ParentID": "byart"},
        ]
        fake = _FakePlaylistDb(tracks=_library(), playlists=existing)
        monkeypatch.setattr(services, "db", fake)

        report = services.LibraryTools.generate_smart_playlists()

        assert report["legacy_by_artist"] == {
            "id": "byart",
            "name": "By Artist",
            "playlists": 2,
        }
        ids = [p["ID"] for p in fake.playlists]
        assert "byart" in ids and "p1" in ids and "p2" in ids

    def test_no_legacy_folder_reports_none(self, monkeypatch) -> None:
        from app import services

        fake = _FakePlaylistDb(tracks=_library())
        monkeypatch.setattr(services, "db", fake)

        assert services.LibraryTools.generate_smart_playlists()["legacy_by_artist"] is None

    def test_unreachable_auto_folder_reports_not_ok(self, monkeypatch) -> None:
        from app import services

        fake = _FakePlaylistDb(tracks=_library())
        monkeypatch.setattr(fake, "create_playlist", lambda *a, **k: None)
        monkeypatch.setattr(services, "db", fake)

        report = services.LibraryTools.generate_smart_playlists()

        assert report["ok"] is False
        assert report["labels_created"] == 0
        assert fake.saved == 0
