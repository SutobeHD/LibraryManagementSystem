"""Tests for ``app/downloader/genre_sync.py`` — genre normalisation + mapping.

Covers :func:`normalise_genre`, :func:`seed_starter_genres`, and the four
:func:`map_genre` paths: exact-cached, exact-canonical, fuzzy >= 0.90, and
novel→owner-callback (add-new / map-existing / skip).

Each test runs against an isolated SQLite registry: the
``download_registry._REGISTRY_DB`` module global is repointed at a tmp file
and ``init_registry()`` builds the (real) schema there.

See ``docs/research/implement/accepted_downloader-unified-multi-source.md``
§ "P4.14", "(D5)" and "D5 — Genre starter list".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app import download_registry
from app.downloader import genre_sync
from app.downloader._genre_starter import GENRE_STARTER


@pytest.fixture
def registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated registry DB with the genre tables created. Returns its path."""
    db_path = tmp_path / "download_registry.db"
    monkeypatch.setattr(download_registry, "_REGISTRY_DB", db_path)
    download_registry.init_registry()
    return db_path


# ──────────────────────────────────────────────────────────────────────────────
# normalise_genre
# ──────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Deep House", "deep house"),
        ("deep-house", "deep house"),
        ("Deep_House", "deep house"),
        ("  TECH   HOUSE  ", "tech house"),
        ("Drum-&-Bass", "drum & bass"),
        ("", ""),
        ("   ", ""),
    ],
)
def test_normalise_genre(raw: str, expected: str) -> None:
    assert genre_sync.normalise_genre(raw) == expected


# ──────────────────────────────────────────────────────────────────────────────
# seed_starter_genres
# ──────────────────────────────────────────────────────────────────────────────


def test_seed_starter_genres_populates_table(registry: Path) -> None:
    count = genre_sync.seed_starter_genres()
    assert count == len(GENRE_STARTER)
    assert count >= 55  # D5 spec floor


def test_seed_starter_genres_is_idempotent(registry: Path) -> None:
    first = genre_sync.seed_starter_genres()
    second = genre_sync.seed_starter_genres()
    assert first == second  # re-seed adds nothing


def test_seed_marks_rows_as_seeded(registry: Path) -> None:
    genre_sync.seed_starter_genres()
    with download_registry._conn() as db:
        row = db.execute("SELECT seeded FROM canonical_genres WHERE name = 'Tech House'").fetchone()
    assert row is not None and row["seeded"] == 1


# ──────────────────────────────────────────────────────────────────────────────
# map_genre — exact paths
# ──────────────────────────────────────────────────────────────────────────────


def test_map_genre_exact_canonical(registry: Path) -> None:
    genre_sync.seed_starter_genres()
    # "tech-house" normalises to "tech house", matches canonical "Tech House".
    assert genre_sync.map_genre("tech-house") == "Tech House"


def test_map_genre_empty_returns_none(registry: Path) -> None:
    genre_sync.seed_starter_genres()
    assert genre_sync.map_genre("") is None
    assert genre_sync.map_genre("   ") is None


def test_map_genre_caches_exact_decision(registry: Path) -> None:
    genre_sync.seed_starter_genres()
    genre_sync.map_genre("DEEP_HOUSE")
    with download_registry._conn() as db:
        row = db.execute(
            "SELECT canonical, decision_source FROM genre_mappings WHERE incoming = ?",
            ("deep house",),
        ).fetchone()
    assert row is not None
    assert row["canonical"] == "Deep House"
    assert row["decision_source"] == "auto_exact"


def test_map_genre_uses_cached_mapping_first(registry: Path) -> None:
    genre_sync.seed_starter_genres()
    # Pre-seed a deliberately "wrong" cached mapping; map_genre must honour it
    # over the exact-canonical match, proving the cache is consulted first.
    with download_registry._conn() as db:
        db.execute(
            "INSERT INTO genre_mappings"
            "(incoming, canonical, decision_made_at, decision_source) "
            "VALUES ('techno', 'Hardstyle', '2026-01-01T00:00:00+00:00', 'owner_map')"
        )
    assert genre_sync.map_genre("Techno") == "Hardstyle"


# ──────────────────────────────────────────────────────────────────────────────
# map_genre — fuzzy path
# ──────────────────────────────────────────────────────────────────────────────


def test_map_genre_fuzzy_match(registry: Path) -> None:
    genre_sync.seed_starter_genres()
    # "Techno " typo — close enough (>= 0.90) to canonical "Techno".
    result = genre_sync.map_genre("Technoo")
    assert result == "Techno"
    with download_registry._conn() as db:
        row = db.execute(
            "SELECT decision_source FROM genre_mappings WHERE incoming = 'technoo'"
        ).fetchone()
    assert row is not None and row["decision_source"].startswith("auto_fuzzy_")


def test_map_genre_below_fuzzy_threshold_is_novel(registry: Path) -> None:
    genre_sync.seed_starter_genres()
    # A genre nowhere near any canonical entry → novel → callback fires.
    seen: list[str] = []

    def callback(raw: str) -> str | None:
        seen.append(raw)
        return None  # skip

    assert genre_sync.map_genre("ZZZ Unmatchable Vibes 9000", owner_callback=callback) is None
    assert seen == ["ZZZ Unmatchable Vibes 9000"]


# ──────────────────────────────────────────────────────────────────────────────
# map_genre — novel / owner callback
# ──────────────────────────────────────────────────────────────────────────────


def test_map_genre_novel_no_callback_returns_none(registry: Path) -> None:
    genre_sync.seed_starter_genres()
    assert genre_sync.map_genre("PROGTRANCE_2026") is None


def test_map_genre_novel_callback_add_new(registry: Path) -> None:
    genre_sync.seed_starter_genres()

    def callback(_raw: str) -> str:
        return "Progtrance 2026"  # owner chooses "add as new canonical"

    result = genre_sync.map_genre("PROGTRANCE_2026", owner_callback=callback)
    assert result == "Progtrance 2026"
    # New canonical genre persisted with seeded=0.
    with download_registry._conn() as db:
        row = db.execute(
            "SELECT seeded FROM canonical_genres WHERE name = 'Progtrance 2026'"
        ).fetchone()
    assert row is not None and row["seeded"] == 0


def test_map_genre_novel_callback_map_to_existing(registry: Path) -> None:
    genre_sync.seed_starter_genres()

    def callback(_raw: str) -> str:
        return "Trance"  # owner maps the novel string onto an existing genre

    result = genre_sync.map_genre("PROGTRANCE_2026", owner_callback=callback)
    assert result == "Trance"
    with download_registry._conn() as db:
        row = db.execute(
            "SELECT decision_source FROM genre_mappings WHERE incoming = 'progtrance 2026'"
        ).fetchone()
    assert row is not None and row["decision_source"] == "owner_map"


def test_map_genre_novel_decision_is_cached(registry: Path) -> None:
    genre_sync.seed_starter_genres()
    calls: list[str] = []

    def callback(raw: str) -> str:
        calls.append(raw)
        return "Progtrance 2026"

    # First call escalates; second call with the same genre must NOT re-ask.
    genre_sync.map_genre("PROGTRANCE_2026", owner_callback=callback)
    second = genre_sync.map_genre("progtrance-2026", owner_callback=callback)
    assert second == "Progtrance 2026"
    assert len(calls) == 1  # callback fired exactly once


def test_map_genre_callback_skip_returns_none(registry: Path) -> None:
    genre_sync.seed_starter_genres()

    def callback(_raw: str) -> None:
        return None

    assert genre_sync.map_genre("WEIRD GENRE", owner_callback=callback) is None
    # A skipped genre is NOT cached — owner may decide differently next time.
    with download_registry._conn() as db:
        row = db.execute("SELECT * FROM genre_mappings WHERE incoming = 'weird genre'").fetchone()
    assert row is None
