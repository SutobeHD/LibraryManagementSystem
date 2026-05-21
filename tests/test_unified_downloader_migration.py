"""Tests for ``app/downloader/migration.py`` — per-source → unified folder move.

Covers :func:`migrate_per_source_to_unified`: the happy-path move of
``MUSIC_DIR/SoundCloud/<artist>/*`` into ``MUSIC_DIR/<artist>/*``, the DB
``file_path`` rewrite, idempotency (a second run is a no-op), and the
collision-skip path.

Both ``MUSIC_DIR`` (module-level import in ``migration``) and the registry DB
are repointed at tmp paths.

See ``docs/research/implement/accepted_downloader-unified-multi-source.md``
§ "P4.16" and "(D7) Folder-migration plan".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app import download_registry
from app.downloader import migration


@pytest.fixture
def music_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated MUSIC_DIR + registry DB. Returns the music-dir path."""
    md = tmp_path / "music"
    md.mkdir()
    monkeypatch.setattr(migration, "MUSIC_DIR", md)
    monkeypatch.setattr(download_registry, "_REGISTRY_DB", md / "download_registry.db")
    download_registry.init_registry()
    return md


def _make_legacy_track(music_dir: Path, artist: str, filename: str) -> Path:
    """Create a legacy ``MUSIC_DIR/SoundCloud/<artist>/<filename>`` file."""
    artist_dir = music_dir / "SoundCloud" / artist
    artist_dir.mkdir(parents=True, exist_ok=True)
    f = artist_dir / filename
    f.write_bytes(b"audio-bytes")
    return f


def _register_path(file_path: Path, sc_id: str) -> None:
    """Insert a ``download_history`` row pointing at ``file_path``."""
    download_registry.register_download(
        sc_track_id=sc_id,
        title="T",
        artist="A",
        file_path=file_path,
        file_format="aiff",
    )


# ──────────────────────────────────────────────────────────────────────────────
# No-op when there is nothing to migrate
# ──────────────────────────────────────────────────────────────────────────────


def test_migration_no_soundcloud_folder(music_dir: Path) -> None:
    result = migration.migrate_per_source_to_unified()
    assert result == {"moved": 0, "skipped": 0, "reason": "no SoundCloud/ folder"}


# ──────────────────────────────────────────────────────────────────────────────
# Happy path
# ──────────────────────────────────────────────────────────────────────────────


def test_migration_moves_files_to_unified_layout(music_dir: Path) -> None:
    legacy = _make_legacy_track(music_dir, "Daft Punk", "one-more-time.aiff")

    result = migration.migrate_per_source_to_unified()

    assert result["moved"] == 1
    assert result["skipped"] == 0
    moved_to = music_dir / "Daft Punk" / "one-more-time.aiff"
    assert moved_to.is_file()
    assert not legacy.exists()
    assert moved_to.read_bytes() == b"audio-bytes"


def test_migration_updates_db_path_and_source(music_dir: Path) -> None:
    legacy = _make_legacy_track(music_dir, "Daft Punk", "aerodynamic.aiff")
    _register_path(legacy, "sc-100")

    migration.migrate_per_source_to_unified()

    rec = download_registry.get_record("sc-100")
    assert rec is not None
    assert rec["file_path"] == str(music_dir / "Daft Punk" / "aerodynamic.aiff")
    assert rec["source"] == "soundcloud"


def test_migration_handles_multiple_artists(music_dir: Path) -> None:
    _make_legacy_track(music_dir, "Artist A", "track-a.aiff")
    _make_legacy_track(music_dir, "Artist B", "track-b.aiff")
    _make_legacy_track(music_dir, "Artist B", "track-b2.aiff")

    result = migration.migrate_per_source_to_unified()

    assert result["moved"] == 3
    assert (music_dir / "Artist A" / "track-a.aiff").is_file()
    assert (music_dir / "Artist B" / "track-b.aiff").is_file()
    assert (music_dir / "Artist B" / "track-b2.aiff").is_file()


# ──────────────────────────────────────────────────────────────────────────────
# Idempotency
# ──────────────────────────────────────────────────────────────────────────────


def test_migration_second_run_is_noop(music_dir: Path) -> None:
    _make_legacy_track(music_dir, "Justice", "genesis.aiff")

    first = migration.migrate_per_source_to_unified()
    second = migration.migrate_per_source_to_unified()

    assert first["moved"] == 1
    # After the first run the SoundCloud/Justice dir is empty; the SoundCloud
    # root still exists, so the second run scans it and finds nothing to move.
    assert second["moved"] == 0
    assert second["skipped"] == 0


# ──────────────────────────────────────────────────────────────────────────────
# Collision handling
# ──────────────────────────────────────────────────────────────────────────────


def test_migration_skips_destination_collision(music_dir: Path) -> None:
    legacy = _make_legacy_track(music_dir, "Moderat", "a99.aiff")
    # A file with the same name already exists in the unified destination.
    dst_dir = music_dir / "Moderat"
    dst_dir.mkdir(parents=True, exist_ok=True)
    (dst_dir / "a99.aiff").write_bytes(b"pre-existing")

    result = migration.migrate_per_source_to_unified()

    assert result["moved"] == 0
    assert result["skipped"] == 1
    # The pre-existing file is untouched; the legacy file is left in place.
    assert (dst_dir / "a99.aiff").read_bytes() == b"pre-existing"
    assert legacy.exists()
