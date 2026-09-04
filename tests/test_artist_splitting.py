"""Tests for artist-name splitting and the artist list it feeds.

Regression: `_split_artists` filtered empty parts *before* normalising, so any
name the normaliser consumed entirely ("Premiere:", "01 - ", "supported by")
entered the artist list as "". That produced a ghost artist in the Artists view
which showed a track count but resolved to zero tracks, because
`get_tracks_by_artist` returns [] on a falsy name.

The splitter is duplicated in `RekordboxXMLDB` and `LiveRekordboxDB`; both are
covered here so a fix to one cannot silently drift from the other.
"""

from __future__ import annotations

import pytest

pytest.importorskip("rbox", reason="pyrekordbox not installed on this platform")

from app.database import RekordboxXMLDB
from app.live_database import LiveRekordboxDB

# Inputs the normaliser strips down to nothing.
CONSUMED_ENTIRELY = [
    "01 - ",
    "02. ",
    "1 -",
    "Premiere",
    "Premiere:",
    "Exclusive:",
    "exclusive",
    "supported by",
]

BACKENDS = [
    pytest.param(lambda: LiveRekordboxDB("does-not-exist.db"), id="live"),
    pytest.param(RekordboxXMLDB, id="xml"),
]


@pytest.fixture(params=BACKENDS)
def backend(request):
    return request.param()


class TestSplitArtists:
    @pytest.mark.parametrize("raw", CONSUMED_ENTIRELY)
    def test_never_yields_an_empty_name(self, backend, raw) -> None:
        assert "" not in backend._split_artists(raw), (
            f"{raw!r} normalised away to an empty artist — that becomes a ghost row "
            "in the Artists view that can never resolve back to its tracks"
        )

    @pytest.mark.parametrize("raw", CONSUMED_ENTIRELY)
    def test_falls_back_to_the_raw_part(self, backend, raw) -> None:
        # Losing the name entirely would hide the tracks; keep what the user typed.
        assert backend._split_artists(raw) == [raw.strip()]

    def test_blank_input_yields_nothing(self, backend) -> None:
        assert backend._split_artists("") == []
        assert backend._split_artists("   ") == []

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Boys Noize", ["Boys Noize"]),
            ("A & B", ["A", "B"]),
            ("X feat. Y", ["X", "Y"]),
            ("X ft. Y", ["X", "Y"]),
            ("X vs. Y", ["X", "Y"]),
            ("A, B; C/D", ["A", "B", "C", "D"]),
        ],
    )
    def test_ordinary_splitting_is_unchanged(self, backend, raw, expected) -> None:
        assert backend._split_artists(raw) == expected

    def test_separators_do_not_leak_empty_entries(self, backend) -> None:
        assert backend._split_artists("A & & B") == ["A", "B"]
        assert backend._split_artists(", A ,") == ["A"]


def test_both_backends_split_identically() -> None:
    """The implementation is duplicated — pin the two copies to each other."""
    live = LiveRekordboxDB("does-not-exist.db")
    xml = RekordboxXMLDB()
    for raw in [*CONSUMED_ENTIRELY, "Boys Noize", "A & B", "X feat. Y", "DJ Koze", ""]:
        assert live._split_artists(raw) == xml._split_artists(raw), f"drift on {raw!r}"


class TestArtistListRoundTrip:
    """The reported symptom: header said "0 / 13 Tracks" with a blank name."""

    @pytest.fixture(autouse=True)
    def _neutral_settings(self, monkeypatch):
        # _finalize_ui_metadata reads the real settings file; artist_view_threshold
        # from the developer's own config would otherwise filter the fixtures away.
        import app.services as services

        monkeypatch.setattr(services.SettingsManager, "load", staticmethod(lambda: {}))

    def _live_with(self, artist_strings: list[str]) -> LiveRekordboxDB:
        db = LiveRekordboxDB("does-not-exist.db")
        db.tracks = {
            str(i): {"id": str(i), "Artist": a, "Artwork": ""} for i, a in enumerate(artist_strings)
        }
        db._finalize_ui_metadata()
        return db

    def test_every_listed_artist_resolves_to_its_tracks(self) -> None:
        db = self._live_with(["Premiere:", "Premiere:", "Boys Noize"])

        assert db.artists, "no artists were built at all"
        for artist in db.artists:
            found = db.get_tracks_by_artist(artist["id"])
            assert len(found) == artist["track_count"], (
                f"{artist['name']!r} counts {artist['track_count']} tracks but "
                f"resolves to {len(found)} — this is the 0/N bug"
            )

    def test_no_artist_has_a_blank_name(self) -> None:
        db = self._live_with(["01 - ", "supported by", "Boys Noize"])
        assert all(a["name"] for a in db.artists)

    def test_count_matches_occurrences(self) -> None:
        db = self._live_with(["Boys Noize", "Boys Noize", "Someone Else"])
        by_name = {a["name"]: a["track_count"] for a in db.artists}
        assert by_name["Boys Noize"] == 2
        assert by_name["Someone Else"] == 1
