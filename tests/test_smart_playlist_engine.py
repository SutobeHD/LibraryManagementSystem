"""Tests for app/smart_playlist_engine.py — the smart-playlist rule evaluator.

Pure logic, no I/O. Locks the operator/field semantics (Rekordbox-XML subset)
so a refactor can't silently change which tracks a smart playlist matches.
"""

from __future__ import annotations

import os
import sys
import time
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import smart_playlist_engine as spe  # noqa: E402

# --- helpers ---------------------------------------------------------------


def _cond(field, op, left, right="", unit="0"):
    return {
        "Field": str(field),
        "Operator": str(op),
        "ValueLeft": left,
        "ValueRight": right,
        "ValueUnit": unit,
    }


def _crit(conditions, logical="all"):
    return {"LogicalOperator": logical, "conditions": conditions}


TRACKS = [
    {
        "id": 1,
        "Title": "Sunset Drive",
        "Artist": "Aria",
        "Genre": "House",
        "BPM": 124.0,
        "Rating": 5,
    },
    {"id": 2, "Title": "Night Run", "Artist": "Beck", "Genre": "Techno", "BPM": 140.0, "Rating": 3},
    {"id": 3, "Title": "Dawn", "Artist": "Aria", "Genre": "Ambient", "BPM": 90.0, "Rating": 1},
]


# --- numeric operators -----------------------------------------------------


def test_numeric_equals_and_range():
    eq = spe.evaluate(_crit([_cond(8, 1, "124")]), TRACKS)  # BPM == 124
    assert [t["id"] for t in eq] == [1]
    rng = spe.evaluate(_crit([_cond(8, 0, "100", "130")]), TRACKS)  # 100..130
    assert [t["id"] for t in rng] == [1]


def test_numeric_greater_and_less():
    gt = spe.evaluate(_crit([_cond(8, 3, "125")]), TRACKS)  # BPM > 125
    assert [t["id"] for t in gt] == [2]
    lt = spe.evaluate(_crit([_cond(8, 4, "100")]), TRACKS)  # BPM < 100
    assert [t["id"] for t in lt] == [3]


def test_rating_field_is_numeric():
    hi = spe.evaluate(_crit([_cond(7, 3, "2")]), TRACKS)  # Rating > 2
    assert {t["id"] for t in hi} == {1, 2}


# --- string operators ------------------------------------------------------


def test_string_contains_starts_ends_equals():
    contains = spe.evaluate(_crit([_cond(1, 5, "run")]), TRACKS)  # Title contains 'run' (ci)
    assert [t["id"] for t in contains] == [2]
    starts = spe.evaluate(_crit([_cond(1, 7, "Sun")]), TRACKS)
    assert [t["id"] for t in starts] == [1]
    ends = spe.evaluate(_crit([_cond(1, 8, "ive")]), TRACKS)
    assert [t["id"] for t in ends] == [1]
    eq = spe.evaluate(_crit([_cond(2, 1, "aria")]), TRACKS)  # case-insensitive equals
    assert {t["id"] for t in eq} == {1, 3}


def test_string_not_contains():
    out = spe.evaluate(_crit([_cond(4, 6, "house")]), TRACKS)  # Genre not contains house
    assert {t["id"] for t in out} == {2, 3}


# --- logical operators -----------------------------------------------------


def test_logical_all_vs_any():
    conds = [_cond(2, 1, "Aria"), _cond(8, 3, "100")]  # Artist=Aria AND BPM>100
    assert [t["id"] for t in spe.evaluate(_crit(conds, "all"), TRACKS)] == [1]
    # Artist=Aria OR BPM>100 → 1 (both), 2 (bpm), 3 (artist)
    assert {t["id"] for t in spe.evaluate(_crit(conds, "any"), TRACKS)} == {1, 2, 3}


# --- edge cases ------------------------------------------------------------


def test_empty_criteria_returns_all():
    assert spe.evaluate({}, TRACKS) == TRACKS
    assert spe.evaluate(_crit([]), TRACKS) == TRACKS


def test_unknown_field_matches_nothing():
    assert spe.evaluate(_crit([_cond(99, 1, "x")]), TRACKS) == []


def test_missing_track_value_is_not_a_match():
    tracks = [{"id": 9, "Title": "NoBpm"}]  # no BPM key
    assert spe.evaluate(_crit([_cond(8, 3, "1")]), tracks) == []


def test_non_numeric_value_does_not_crash():
    # bad ValueLeft for a numeric field → condition false, never raises
    assert spe.evaluate(_crit([_cond(8, 1, "not-a-number")]), TRACKS) == []


# --- relative date fields --------------------------------------------------


def test_date_newer_and_older_than_days():
    now = time.time()
    recent = time.strftime("%Y-%m-%d", time.localtime(now - 2 * 86400))
    old = time.strftime("%Y-%m-%d", time.localtime(now - 60 * 86400))
    tracks = [{"id": "r", "StockDate": recent}, {"id": "o", "StockDate": old}]
    # op 3 (>) with unit days = newer than N days ago
    newer = spe.evaluate(_crit([_cond(10, 3, "10", unit="1")]), tracks)
    assert [t["id"] for t in newer] == ["r"]
    # op 4 (<) = older than N days ago
    older = spe.evaluate(_crit([_cond(10, 4, "10", unit="1")]), tracks)
    assert [t["id"] for t in older] == ["o"]


# --- XML round-trip --------------------------------------------------------


def test_from_xml_node_parses_conditions():
    xml = (
        '<SmartList LogicalOperator="any" AutomaticUpdate="1">'
        '<CONDITION Field="8" Operator="3" ValueLeft="120" ValueRight="" ValueUnit="0"/>'
        "</SmartList>"
    )
    node = ET.fromstring(xml)
    crit = spe.from_xml_node(node)
    assert crit["LogicalOperator"] == "any"
    assert len(crit["conditions"]) == 1
    assert crit["conditions"][0]["Field"] == "8"
    # parsed criteria drives evaluate end-to-end
    assert {t["id"] for t in spe.evaluate(crit, TRACKS)} == {1, 2}


def test_from_xml_node_none_returns_empty():
    assert spe.from_xml_node(None) == {}


def test_to_xml_attrs_roundtrips_root_flags():
    attrs = spe.to_xml_attrs({"LogicalOperator": "any", "AutomaticUpdate": "0"})
    assert attrs == {"LogicalOperator": "any", "AutomaticUpdate": "0"}
    assert spe.to_xml_attrs({}) == {}
