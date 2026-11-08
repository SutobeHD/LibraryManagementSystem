"""SoundCloud sync matcher: the indexed matcher answers exactly like the old brute force.

``_brute_force_reference`` is a verbatim copy of
``SoundCloudSyncEngine._fuzzy_match_with_score`` before the local-library index
(2026-11-08). Every query must return the identical ``(track_id, score)`` tuple,
including tie-breaks (first track in dict order wins). The ``slow`` benchmark pins
the speed-up at 20k tracks x 500 SC tracks.
"""

from __future__ import annotations

import random
import re
import time
from difflib import SequenceMatcher
from typing import Any
from unittest.mock import MagicMock

import pytest

from app import soundcloud_api
from app.soundcloud_api import SoundCloudSyncEngine, _LocalTrackIndex


def _normalize(title: str) -> str:
    return re.sub(r"[^\w\s]", "", title.lower().strip())


def _brute_force_reference(
    sc_title: str, sc_artist: str, local_tracks: dict[str, dict[str, Any]]
) -> tuple[str | None, float]:
    sc_combined = f"{sc_artist} - {sc_title}".lower()
    sc_norm_title = _normalize(sc_title)
    best_match = None
    best_ratio = 0.0

    for tid, track in local_tracks.items():
        local_title = (track.get("Title") or "").lower()
        local_artist = (track.get("Artist") or "").lower()
        local_combined = f"{local_artist} - {local_title}"

        if sc_norm_title and sc_norm_title == _normalize(local_title):
            return tid, 1.0

        ratio = SequenceMatcher(None, sc_combined, local_combined).ratio()
        if ratio > best_ratio and ratio >= 0.65:
            best_ratio = ratio
            best_match = tid

    return best_match, round(best_ratio, 3)


# ---------------------------------------------------------------------------
# Synthetic library / playlist generators (deterministic)
# ---------------------------------------------------------------------------

_SYLLABLES = (
    "ka", "lo", "mi", "ra", "ten", "dor", "vel", "shu", "ne", "on", "ix", "ter", "bel",
    "ma", "sun", "set", "deep", "ho", "use", "tra", "nce", "bass", "li", "ar", "co",
    "de", "flo", "ri", "da", "zen", "qu", "ark", "wav", "ey", "so", "ul", "pe", "gro",
)  # fmt: skip
_SUFFIXES = ("", "", "", " (Original Mix)", " (Extended Mix)", " (Radio Edit)", " (VIP)", "R")


def _word(rng: random.Random) -> str:
    return "".join(rng.choice(_SYLLABLES) for _ in range(rng.randint(1, 3))).capitalize()


def _phrase(rng: random.Random, lo: int, hi: int) -> str:
    return " ".join(_word(rng) for _ in range(rng.randint(lo, hi)))


def _artist(rng: random.Random) -> str:
    if rng.random() < 0.75:
        return _phrase(rng, 1, 2)
    return f"{_phrase(rng, 1, 1)} & {_phrase(rng, 1, 1)}"


def _title(rng: random.Random) -> str:
    suffix = rng.choice(_SUFFIXES)
    if suffix == "R":
        suffix = f" ({_artist(rng)} Remix)"
    return _phrase(rng, 1, 4) + suffix


def _make_library(n: int, seed: int) -> dict[str, dict[str, Any]]:
    rng = random.Random(seed)
    artists = [_artist(rng) for _ in range(max(1, n // 6))]
    return {
        str(10_000 + i): {"Title": _title(rng), "Artist": rng.choice(artists)} for i in range(n)
    }


def _typo(rng: random.Random, text: str) -> str:
    if len(text) < 4:
        return text + "x"
    i = rng.randrange(len(text))
    op = rng.random()
    if op < 0.33:
        return text[:i] + text[i + 1 :]
    if op < 0.66:
        return text[:i] + rng.choice("aeiourst") + text[i:]
    return text[:i] + rng.choice("aeiourst") + text[i + 1 :]


def _make_queries(library: dict[str, dict[str, Any]], n: int, seed: int) -> list[tuple[str, str]]:
    """Mix: exact-normalised hits, typos, SC decorations, artist drift, unrelated tracks."""
    rng = random.Random(seed)
    tracks = list(library.values())
    queries: list[tuple[str, str]] = []
    for _ in range(n):
        track = rng.choice(tracks)
        title = track.get("Title") or ""
        artist = track.get("Artist") or ""
        roll = rng.random()
        if roll < 0.2:
            queries.append((title.upper() + "!", artist))
        elif roll < 0.4:
            queries.append((_typo(rng, title), artist))
        elif roll < 0.5:
            queries.append((f"{title} [Free DL]", artist))
        elif roll < 0.6:
            queries.append((title.split(" (")[0] + " (Extended)", f"{artist} Official"))
        else:
            queries.append((_title(rng), _artist(rng)))
    return queries


#: Hand-picked shapes the generator does not produce: duplicates, exact ties, missing
#: fields, punctuation-only titles, Unicode case quirks, multi-chunk and autojunk lengths.
_EDGE_TRACKS: dict[str, dict[str, Any]] = {
    "e01": {"Title": "Velvet Shuffle", "Artist": "Some DJ"},
    "e02": {"Title": "Velvet Shuffle", "Artist": "Other DJ"},
    "e03": {"Title": "Twin Peak", "Artist": "Mirror"},
    "e04": {"Title": "Twin Peak", "Artist": "Mirror"},
    "e05": {"Title": "!!!", "Artist": "Punct"},
    "e06": {"Title": None, "Artist": "No Title"},
    "e07": {"Artist": "Missing Title"},
    "e08": {"Title": "Untitled", "Artist": None},
    "e09": {"Title": "   ", "Artist": "Blank"},
    "e10": {"Title": "Café del Mar (Ünïcödé Remix)", "Artist": "Énergie"},
    "e11": {"Title": "東京 Nights", "Artist": "夜"},
    "e12": {"Title": "ΣΟΦΙΑ ΣΣ", "Artist": "ΕΛΛΗΝΙΚΆ"},
    "e13": {"Title": "İstanbul Groove", "Artist": "DJ İ"},
    "e14": {"Title": "🔥 Fire 🔥", "Artist": "Emoji"},
    "e15": {"Title": "A Very Long Title " * 5, "Artist": "Long Artist Name Here"},
    "e16": {"Title": "x" * 210, "Artist": "Autojunk"},
    "e17": {"Title": "t" * 61, "Artist": ""},  # combined " - " + 61 = 64 chars
    "e18": {"Title": "t" * 62, "Artist": ""},  # 65 chars -> two chunks
}

_EDGE_QUERIES: list[tuple[str, Any]] = [
    ("Velvet Shuffle", "Other DJ"),
    ("Velvet Shufle", "Other DJ"),
    ("Velvet Shufle", None),
    ("Twin Peaks", "Mirror"),
    ("???", "Punct"),
    ("", "No Title"),
    ("", ""),
    ("Cafe del Mar (Unicode Remix)", "Energie"),
    ("東京 Night", "夜"),
    ("σοφια σσ", "ελληνικα"),  # noqa: RUF001 - Greek final-sigma casing on purpose
    ("Istanbul Groove", "DJ I"),
    ("Fire", "Emoji"),
    ("A Very Long Title A Very Long Title A Very Long Title", "Long Artist Name"),
    ("x" * 205, "autojunk"),
    ("t" * 60, ""),
    ("жжж €€€", "unknown chars"),
    ("Some Extremely Long SoundCloud Upload Title [FREE DOWNLOAD] (Bootleg) 2026", "x"),
]


@pytest.fixture
def engine() -> SoundCloudSyncEngine:
    return SoundCloudSyncEngine(MagicMock())


# ---------------------------------------------------------------------------
# Equality: indexed matcher == brute force
# ---------------------------------------------------------------------------


class TestMatchesBruteForce:
    def test_synthetic_library_with_edge_cases(self, engine) -> None:
        library = {**_EDGE_TRACKS, **_make_library(400, seed=11)}
        library["e99"] = {"Title": "Velvet Shuffle", "Artist": "Last DJ"}
        queries = _EDGE_QUERIES + _make_queries(library, 160, seed=12)

        mismatches = [
            (title, artist, got, want)
            for title, artist in queries
            if (got := engine._fuzzy_match_with_score(title, artist, library))
            != (want := _brute_force_reference(title, artist, library))
        ]
        assert mismatches == []

    def test_near_duplicate_library_ties_and_close_scores(self, engine) -> None:
        """One artist, numbered titles, shared suffix: many candidates with equal
        or near-equal ratios, so best-first pruning and tie-breaking both get used."""
        library = {
            f"s{i:03d}": {"Title": f"Track {i:03d} (Original Mix)", "Artist": "DJ Sample"}
            for i in range(300)
        }
        queries = [(f"Track {i:02d} (Original Mix)", "DJ Sample") for i in range(0, 100, 3)]
        queries += [(f"Trak {i} Original", "DJ Sampl") for i in range(0, 300, 13)]
        queries += [("Track", "DJ Sample"), ("Original Mix", "")]

        for title, artist in queries:
            assert engine._fuzzy_match_with_score(title, artist, library) == _brute_force_reference(
                title, artist, library
            ), (title, artist)

    def test_exact_title_hit_takes_first_in_dict_order(self, engine) -> None:
        library = {
            "a": {"Title": "Velvet Shuffle", "Artist": "Wrong Artist"},
            "b": {"Title": "Velvet Shuffle", "Artist": "Some DJ"},
        }
        assert engine._fuzzy_match_with_score("velvet shuffle!", "Some DJ", library) == ("a", 1.0)

    def test_equal_ratio_tie_takes_first_in_dict_order(self, engine) -> None:
        library = {
            "z": {"Title": "Unrelated Thing", "Artist": "Nobody"},
            "b": {"Title": "Twin Peak", "Artist": "Mirror"},
            "a": {"Title": "Twin Peak", "Artist": "Mirror"},
        }
        tid, score = engine._fuzzy_match_with_score("Twin Peaks", "Mirror", library)
        assert tid == "b"
        assert (tid, score) == _brute_force_reference("Twin Peaks", "Mirror", library)

    def test_empty_library(self, engine) -> None:
        assert engine._fuzzy_match_with_score("Anything", "Anyone", {}) == (None, 0.0)


# ---------------------------------------------------------------------------
# LCS upper bound
# ---------------------------------------------------------------------------


def _lcs_dp(a: str, b: str) -> int:
    prev = [0] * (len(b) + 1)
    for ca in a:
        cur = [0]
        for j, cb in enumerate(b):
            cur.append(prev[j] + 1 if ca == cb else max(prev[j + 1], cur[j]))
        prev = cur
    return prev[-1]


def test_lcs_bound_exact_up_to_64_chars_and_upper_bound_beyond() -> None:
    rng = random.Random(5)
    alphabet = "ab c-"
    library = {
        str(i): {
            "Title": "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 160))),
            "Artist": "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 8))),
        }
        for i in range(100)
    }
    combined = [f"{t['Artist']} - {t['Title']}" for t in library.values()]
    index = _LocalTrackIndex(library)
    for _ in range(15):
        query = "".join(rng.choice(alphabet + "xz") for _ in range(rng.randint(1, 130)))
        bounds = index.lcs_upper_bounds(query).tolist()
        for local, bound in zip(combined, bounds, strict=True):
            lcs = _lcs_dp(query, local)
            if len(local) <= 64:
                assert bound == lcs, (query, local)
            else:
                assert bound >= lcs, (query, local)
            matched = sum(
                block.size for block in SequenceMatcher(None, query, local).get_matching_blocks()
            )
            assert bound >= matched, (query, local)


# ---------------------------------------------------------------------------
# Index lifetime on the engine
# ---------------------------------------------------------------------------


class _CountingIndex(_LocalTrackIndex):
    builds = 0

    def __init__(self, local_tracks):
        type(self).builds += 1
        super().__init__(local_tracks)


@pytest.fixture
def counting_index(monkeypatch) -> type[_CountingIndex]:
    _CountingIndex.builds = 0
    monkeypatch.setattr(soundcloud_api, "_LocalTrackIndex", _CountingIndex)
    return _CountingIndex


class TestIndexReuse:
    def test_same_mapping_builds_once(self, engine, counting_index) -> None:
        library = _make_library(50, seed=3)
        for title, artist in _make_queries(library, 20, seed=4):
            engine._fuzzy_match_track(title, artist, library)
        assert counting_index.builds == 1

    def test_resized_mapping_rebuilds_and_sees_new_track(self, engine, counting_index) -> None:
        library = {"t1": {"Title": "Old Song", "Artist": "Someone"}}
        assert engine._fuzzy_match_track("Brand New", "Artist", library) is None
        library["t2"] = {"Title": "Brand New", "Artist": "Artist"}
        assert engine._fuzzy_match_track("Brand New", "Artist", library) == "t2"
        assert counting_index.builds == 2

    def test_other_mapping_rebuilds(self, engine, counting_index) -> None:
        engine._fuzzy_match_track("Song", "A", {"t1": {"Title": "Song", "Artist": "A"}})
        assert engine._fuzzy_match_track("Song", "A", {"t9": {"Title": "Song", "Artist": "A"}}) == (
            "t9"
        )
        assert counting_index.builds == 2

    def test_preview_and_sync_index_once_per_engine(self, counting_index) -> None:
        library = {
            "t1": {"Title": "Velvet Shuffle", "Artist": "Some DJ"},
            "t2": {"Title": "Deep Water", "Artist": "Blue"},
        }
        db = MagicMock()
        db.tracks = library
        db.playlists = [{"Name": "SC_Likes", "ID": 7}]
        db.get_playlist_tracks.return_value = [{"ID": "t2"}]
        playlist = {
            "is_likes": True,
            "title": "Likes",
            "tracks": [
                {"title": "Velvet Shufle", "artist": "Some DJ", "permalink_url": "u1"},
                {"title": "Deep Water", "artist": "Blue", "permalink_url": "u2"},
                {"title": "Nothing Like It", "artist": "Stranger", "permalink_url": "u3"},
                {"title": "", "artist": "Gone", "permalink_url": "u4"},
            ],
        }
        engine = SoundCloudSyncEngine(db)

        preview = engine.preview_matches(playlist, "token")
        assert [(p["status"], p["local_id"]) for p in preview] == [
            ("matched", "t1"),
            ("matched", "t2"),
            ("unmatched", None),
            ("dead", None),
        ]
        assert preview[1]["score"] == 1.0

        result = engine.sync_playlist(playlist, "token")
        assert (result["matched"], result["unmatched"], result["dead_tracks"]) == (2, 1, 1)
        assert (result["already_synced"], result["added"]) == (1, 1)
        db.add_track_to_playlist.assert_called_once_with("7", "t1")
        assert counting_index.builds == 1


# ---------------------------------------------------------------------------
# Benchmark: 20k-track library x 500-track playlist
# ---------------------------------------------------------------------------


@pytest.mark.slow
def test_benchmark_20k_library_500_track_playlist() -> None:
    library = _make_library(20_000, seed=21)
    queries = _make_queries(library, 500, seed=22)

    started = time.perf_counter()
    engine = SoundCloudSyncEngine(MagicMock())
    indexed = [engine._fuzzy_match_with_score(t, a, library) for t, a in queries]
    indexed_s = time.perf_counter() - started

    sample = random.Random(23).sample(range(len(queries)), 6)
    started = time.perf_counter()
    reference = {i: _brute_force_reference(*queries[i], library) for i in sample}
    brute_force_s = (time.perf_counter() - started) / len(sample) * len(queries)

    speedup = brute_force_s / indexed_s
    print(
        f"\nsc fuzzy match 20k x 500: indexed {indexed_s:.2f}s, "
        f"brute force ~{brute_force_s:.0f}s (extrapolated from {len(sample)}), "
        f"speed-up ~{speedup:.0f}x"
    )
    assert {i: indexed[i] for i in sample} == reference
    assert indexed_s < 15.0
    assert speedup >= 20.0
