"""M0 detector tests — read-only malformation detection.

Covers the exact signatures from the plan
(docs/research/implement/accepted_metadata-name-fixer.md, Recommendation M0)
plus a synthetic per-rule precision/recall corpus for the high-precision
subset {1, 4, 5, 6, 7, 8}.
"""

from __future__ import annotations

import unicodedata

import pytest

from app.metadata_fixer import detector
from app.metadata_fixer.detector import ACTIVE_RULE_IDS, Match, scan


def _matches_for(track: dict[str, str], rule_id: int) -> list[Match]:
    return [m for _t, m in scan([track]) if m.rule_id == rule_id]


# --------------------------------------------------------------------------- #
# Per-class unit behaviour
# --------------------------------------------------------------------------- #
def test_class1_artist_in_parens_precision_recall() -> None:
    # positives: empty artist + "Title (Artist)"
    positives = [{"artist": "", "title": f"Track{i} (Artist{i})"} for i in range(100)]
    # negatives: paren is a mix/version descriptor, or artist already set
    negatives = [{"artist": "", "title": f"Track{i} (Original Mix)"} for i in range(50)]
    negatives += [{"artist": "Somebody", "title": f"Track{i} (Whoever)"} for i in range(50)]

    tp = sum(1 for t in positives if _matches_for(t, 1))
    fp = sum(1 for t in negatives if _matches_for(t, 1))
    recall = tp / len(positives)
    precision = tp / (tp + fp) if (tp + fp) else 1.0
    assert recall >= 0.95
    assert precision >= 0.98

    # exact rewrite
    (m,) = _matches_for({"artist": "", "title": "Strobe (Deadmau5)"}, 1)
    assert m.suggested == {"artist": "Deadmau5", "title": "Strobe"}


def test_class4_track_num_prefix_strips_only_leading() -> None:
    (m,) = _matches_for({"artist": "X", "title": "01 - Intro"}, 4)
    assert m.suggested["title"] == "Intro"
    # no leading number -> no match
    assert _matches_for({"artist": "X", "title": "Track 01"}, 4) == []
    # Adversarial negative: real release name must survive (not zero-padded)
    assert _matches_for({"artist": "X", "title": "19 - Naughty Forty"}, 4) == []


def test_class5_html_entities_unescape_idempotent() -> None:
    track = {"artist": "X", "title": "Rock &amp; Roll"}
    (m,) = _matches_for(track, 5)
    once = m.suggested["title"]
    assert once == "Rock & Roll"
    # second pass over already-fixed value yields no match (idempotent)
    assert _matches_for({"artist": "X", "title": once}, 5) == []


def test_class6_smart_quotes_to_ascii_then_nfc() -> None:
    track = {"artist": "X", "title": "Don’t Stop"}  # noqa: RUF001 — smart quote is the fixture
    (m,) = _matches_for(track, 6)
    assert m.suggested["title"] == "Don't Stop"
    assert m.suggested["title"] == unicodedata.normalize("NFC", m.suggested["title"])


def test_class7_double_encoded_anchor_match_case_insensitive() -> None:
    track = {"artist": "daft punk", "title": "Daft Punk - One More Time (Daft Punk Remix)"}
    (m,) = _matches_for(track, 7)
    assert m.suggested["title"] == "One More Time (Daft Punk Remix)"
    # prefix that is not the artist must not strip
    assert _matches_for({"artist": "X", "title": "Y - Z"}, 7) == []


def test_class8_catalog_no_bracket_strip_collision_safe() -> None:
    (m,) = _matches_for({"artist": "X", "title": "Strobe [MAU5001]"}, 8)
    assert m.suggested["title"] == "Strobe"
    # mix-name bracket preserved
    assert _matches_for({"artist": "X", "title": "Strobe [Original Mix]"}, 8) == []


# --------------------------------------------------------------------------- #
# Corpus-level SLO + zero-write guarantee
# --------------------------------------------------------------------------- #
def _seeded_corpus() -> dict[int, dict[str, list[dict[str, str]]]]:
    """100 positives + 100 negatives per active class."""
    corpus: dict[int, dict[str, list[dict[str, str]]]] = {}
    corpus[1] = {
        "pos": [{"artist": "", "title": f"Song{i} (Artist{i})"} for i in range(100)],
        "neg": [{"artist": "A", "title": f"Song{i}"} for i in range(100)],
    }
    corpus[4] = {
        "pos": [{"artist": "A", "title": f"0{i % 9 + 1} - Song{i}"} for i in range(100)],
        "neg": [{"artist": "A", "title": f"Song{i}"} for i in range(100)],
    }
    corpus[5] = {
        "pos": [{"artist": "A", "title": f"Rock{i} &amp; Roll"} for i in range(100)],
        "neg": [{"artist": "A", "title": f"Rock{i} and Roll"} for i in range(100)],
    }
    corpus[6] = {
        "pos": [{"artist": "A", "title": f"Don’t{i}"} for i in range(100)],  # noqa: RUF001
        "neg": [{"artist": "A", "title": f"Dont{i}"} for i in range(100)],
    }
    corpus[7] = {
        "pos": [{"artist": f"Artist{i}", "title": f"Artist{i} - Song{i}"} for i in range(100)],
        "neg": [{"artist": f"Artist{i}", "title": f"Song{i}"} for i in range(100)],
    }
    corpus[8] = {
        "pos": [{"artist": "A", "title": f"Song{i} [AB{1000 + i}]"} for i in range(100)],
        "neg": [{"artist": "A", "title": f"Song{i} [Original Mix]"} for i in range(100)],
    }
    return corpus


def test_detector_full_500_corpus_per_rule_precision_recall() -> None:
    corpus = _seeded_corpus()
    assert set(corpus) == set(ACTIVE_RULE_IDS)
    for rule_id, sets in corpus.items():
        tp = sum(1 for t in sets["pos"] if _matches_for(t, rule_id))
        fp = sum(1 for t in sets["neg"] if _matches_for(t, rule_id))
        recall = tp / len(sets["pos"])
        precision = tp / (tp + fp) if (tp + fp) else 1.0
        assert recall >= 0.95, f"rule {rule_id} recall {recall:.3f}"
        assert precision >= 0.98, f"rule {rule_id} precision {precision:.3f}"


def test_detector_zero_writes_smoke() -> None:
    """scan() must never mutate the input track dicts."""
    tracks = [
        {"artist": "", "title": "Strobe (Deadmau5)"},
        {"artist": "X", "title": "01 - Intro"},
        {"artist": "X", "title": "Rock &amp; Roll"},
    ]
    snapshot = [dict(t) for t in tracks]
    scan(tracks)
    assert tracks == snapshot


def test_class2_feat_is_suggestion_only_not_active() -> None:
    # class 2 fires as a low-confidence suggestion, excluded from the active subset
    (m,) = _matches_for({"artist": "Avicii", "title": "Levels (feat. Ne-Yo)"}, 2)
    assert m.confidence < 0.8
    assert 2 not in ACTIVE_RULE_IDS
    # restricting scan to active rules drops class 2
    active_hits = [
        mm
        for _t, mm in scan(
            [{"artist": "Avicii", "title": "Levels (feat. Ne-Yo)"}], rule_ids=ACTIVE_RULE_IDS
        )
    ]
    assert all(mm.rule_id != 2 for mm in active_hits)


@pytest.mark.parametrize("bad", [{}, {"title": None}, {"artist": None, "title": None}])
def test_scan_tolerates_missing_or_none_fields(bad: dict) -> None:
    assert scan([bad]) == []
