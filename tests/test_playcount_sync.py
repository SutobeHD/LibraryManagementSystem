"""Tests for app/playcount_sync.py — USB <-> PC play-count sync engine.

Pure logic (_apply_strategy, diff_playcounts) plus the XML reader and the
USB meta round-trip. rbox is a soft dependency; the PC-DB write path is not
exercised here (it needs rbox + a real master.db), only the deterministic
XML-patch + diff/resolve logic.
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app import playcount_sync as ps  # noqa: E402

# --- _apply_strategy (pure) ------------------------------------------------


def test_apply_strategy_all_modes():
    assert ps._apply_strategy("take_pc", 5, 9, 100.0, 200.0) == (5, 100.0)
    assert ps._apply_strategy("take_usb", 5, 9, 100.0, 200.0) == (9, 200.0)
    assert ps._apply_strategy("sum", 5, 9, 100.0, 200.0) == (14, 200.0)
    # take_max keeps larger count + latest last_played
    assert ps._apply_strategy("take_max", 5, 9, 300.0, 200.0) == (9, 300.0)
    assert ps._apply_strategy("take_max", 12, 9, 100.0, 200.0) == (12, 200.0)
    # unknown strategy falls back to take_max
    assert ps._apply_strategy("bogus", 5, 9, 100.0, 200.0) == (9, 200.0)


# --- diff_playcounts (pure) ------------------------------------------------


def _t(tid, count, lp, title="T"):
    return {"track_id": tid, "play_count": count, "last_played": lp, "title": title}


def test_diff_equal_counts_auto_equal():
    out = ps.diff_playcounts([_t("1", 5, 100.0)], [_t("1", 5, 50.0)], last_sync_ts=10.0)
    assert out["conflicts"] == []
    assert out["auto"][0]["source"] == "equal"
    assert out["auto"][0]["resolved_last_played"] == 100.0  # max of the two


def test_diff_only_pc_changed_takes_pc():
    # last_sync=100: pc played after (150), usb not (80)
    out = ps.diff_playcounts([_t("1", 9, 150.0)], [_t("1", 5, 80.0)], last_sync_ts=100.0)
    assert out["conflicts"] == []
    assert out["auto"][0]["source"] == "pc"
    assert out["auto"][0]["resolved_count"] == 9


def test_diff_only_usb_changed_takes_usb():
    out = ps.diff_playcounts([_t("1", 5, 80.0)], [_t("1", 9, 150.0)], last_sync_ts=100.0)
    assert out["auto"][0]["source"] == "usb"
    assert out["auto"][0]["resolved_count"] == 9


def test_diff_both_changed_is_conflict():
    out = ps.diff_playcounts([_t("1", 7, 150.0)], [_t("1", 9, 160.0)], last_sync_ts=100.0)
    assert out["auto"] == []
    c = out["conflicts"][0]
    assert c["pc_count"] == 7 and c["usb_count"] == 9


def test_diff_track_not_on_usb_skipped():
    out = ps.diff_playcounts([_t("1", 5, 100.0)], [], last_sync_ts=10.0)
    assert out["auto"] == [] and out["conflicts"] == []


def test_diff_track_without_id_skipped():
    out = ps.diff_playcounts([{"play_count": 5}], [_t("1", 5, 0.0)], last_sync_ts=10.0)
    assert out["auto"] == [] and out["conflicts"] == []


def test_diff_first_sync_mismatch_is_conflict():
    """Documented policy: with no baseline (ts=0) a count mismatch where both
    sides are >0 is conservatively a conflict, not an auto-resolve."""
    out = ps.diff_playcounts([_t("1", 3, 0.0)], [_t("1", 7, 0.0)], last_sync_ts=0.0)
    assert len(out["conflicts"]) == 1


# --- read_usb_xml_playcounts ----------------------------------------------

_XML = """<?xml version="1.0" encoding="UTF-8"?>
<DJ_PLAYLISTS Version="1.0.0">
  <COLLECTION Entries="2">
    <TRACK TrackID="10" Name="A" Artist="X" PlayCount="4" LastPlayed="2024-01-15"/>
    <TRACK TrackID="11" Name="B" Artist="Y" PlayCount="notanumber"/>
  </COLLECTION>
</DJ_PLAYLISTS>
"""


def test_read_usb_xml_playcounts(tmp_path):
    p = tmp_path / "export.xml"
    p.write_text(_XML, encoding="utf-8")
    rows = ps.read_usb_xml_playcounts(str(p))
    by_id = {r["track_id"]: r for r in rows}
    assert by_id["10"]["play_count"] == 4
    assert by_id["10"]["last_played"] > 0  # LastPlayed parsed to epoch
    assert by_id["11"]["play_count"] == 0  # garbage PlayCount → 0, no crash


def test_read_usb_xml_missing_and_malformed(tmp_path):
    assert ps.read_usb_xml_playcounts(str(tmp_path / "nope.xml")) == []
    bad = tmp_path / "bad.xml"
    bad.write_text("<DJ_PLAYLISTS><nope", encoding="utf-8")
    assert ps.read_usb_xml_playcounts(str(bad)) == []


# --- USB sync meta round-trip ----------------------------------------------


def test_sync_meta_roundtrip(tmp_path):
    root = str(tmp_path)
    meta = {"last_sync_ts": 123.0, "tracks": {"1": {"play_count": 3}}}
    ps.save_usb_sync_meta(root, meta)
    loaded = ps.load_usb_sync_meta(root)
    assert loaded["last_sync_ts"] == 123.0
    assert loaded["tracks"]["1"]["play_count"] == 3


def test_sync_meta_missing_returns_default(tmp_path):
    out = ps.load_usb_sync_meta(str(tmp_path))
    assert out == {"last_sync_ts": 0.0, "tracks": {}}


def test_sync_meta_corrupt_returns_default(tmp_path):
    meta_path = tmp_path / ps._SYNC_META_FILENAME
    meta_path.parent.mkdir(parents=True)
    meta_path.write_text("{not json", encoding="utf-8")
    out = ps.load_usb_sync_meta(str(tmp_path))
    assert out == {"last_sync_ts": 0.0, "tracks": {}}


def test_sync_meta_invalid_root():
    assert ps.load_usb_sync_meta("") == {"last_sync_ts": 0.0, "tracks": {}}


# --- resolve_playcounts: deterministic XML patch path ----------------------


def test_resolve_patches_usb_xml(tmp_path):
    """The USB XML PlayCount is patched even when rbox/PC-DB is unavailable."""
    xml = tmp_path / "export.xml"
    xml.write_text(_XML, encoding="utf-8")
    res = ps.resolve_playcounts(
        [
            {
                "track_id": "10",
                "strategy": "take_max",
                "pc_count": 4,
                "usb_count": 9,
                "pc_last_played": 0.0,
                "usb_last_played": 1_700_000_000.0,
            }
        ],
        pc_db_path=str(tmp_path / "missing_master.db"),
        usb_xml_path=str(xml),
    )
    assert isinstance(res["committed"], int)
    rows = {r["track_id"]: r for r in ps.read_usb_xml_playcounts(str(xml))}
    assert rows["10"]["play_count"] == 9  # take_max(4,9) committed to XML


def test_resolve_missing_xml_reports_error(tmp_path):
    res = ps.resolve_playcounts([], pc_db_path="x", usb_xml_path=str(tmp_path / "no.xml"))
    assert any("USB XML not found" in e for e in res["errors"])


def test_resolve_rejects_non_list():
    res = ps.resolve_playcounts({"not": "a list"}, pc_db_path="x", usb_xml_path="y")  # type: ignore[arg-type]
    assert res["committed"] == 0 and res["errors"]


def test_save_meta_invalid_inputs_raise():
    import pytest

    with pytest.raises(RuntimeError):
        ps.save_usb_sync_meta("", {})
    with pytest.raises(RuntimeError):
        ps.save_usb_sync_meta("/tmp/x", "not a dict")  # type: ignore[arg-type]


def test_roundtrip_meta_is_json_serializable(tmp_path):
    meta = {"last_sync_ts": 1.0, "tracks": {"a": {"play_count": 2, "last_played": 3.5}}}
    ps.save_usb_sync_meta(str(tmp_path), meta)
    raw = (tmp_path / ps._SYNC_META_FILENAME).read_text(encoding="utf-8")
    assert json.loads(raw)["tracks"]["a"]["last_played"] == 3.5
