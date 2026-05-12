"""
Smart-Playlist evaluator. Mode-agnostic: works on any list of track dicts.

Criteria format (Rekordbox-XML compatible, simplified):
{
  "LogicalOperator": "all" | "any",
  "AutomaticUpdate": "1" | "0",
  "conditions": [
    {"Field": "<key>", "Operator": "<op>", "ValueLeft": str, "ValueRight": str|None, "ValueUnit": str}
  ]
}

Field IDs (Rekordbox spec subset):
  1  Title           4  Genre        7  Rating
  2  Artist          5  Comments     8  BPM
  3  Album           6  PlayCount    9  Year
  10 DateAdded       11 Bitrate      12 Key
  13 Duration        14 Color        15 Label

Operators:
  0  is in range (ValueLeft–ValueRight)
  1  equals
  2  not equals
  3  greater than
  4  less than
  5  contains
  6  not contains
  7  starts with
  8  ends with

Unit (for date/duration):
  0  none / value as-is
  1  days
  2  weeks
  3  months
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


_FIELD_MAP = {
    "1": ("Title", str),
    "2": ("Artist", str),
    "3": ("Album", str),
    "4": ("Genre", str),
    "5": ("Comment", str),
    "6": ("PlayCount", int),
    "7": ("Rating", int),
    "8": ("BPM", float),
    "9": ("ReleaseYear", int),
    "10": ("StockDate", str),  # date string
    "11": ("Bitrate", int),
    "12": ("Key", str),
    "13": ("TotalTime", float),
    "14": ("ColorID", str),
    "15": ("Label", str),
}


def _coerce(val: Any, kind):
    if val is None or val == "":
        return None
    try:
        if kind is int:
            return int(float(val))
        if kind is float:
            return float(val)
        return str(val)
    except (ValueError, TypeError):
        return None


def _date_to_ts(s: str):
    """Parse 'YYYY-MM-DD' or ISO timestamp to unix epoch."""
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y/%m/%d"):
        try:
            return datetime.strptime(str(s)[:19], fmt).timestamp()
        except ValueError:
            continue
    return None


def _shift_unit(value: float, unit: str) -> float:
    """Convert numeric value with unit (days/weeks/months) → seconds offset."""
    u = str(unit or "0")
    if u == "1":
        return value * 86400
    if u == "2":
        return value * 86400 * 7
    if u == "3":
        return value * 86400 * 30
    return value


def _check_condition(track: dict, cond: dict) -> bool:
    field = str(cond.get("Field", ""))
    op = str(cond.get("Operator", "1"))
    val_l = cond.get("ValueLeft")
    val_r = cond.get("ValueRight")
    unit = cond.get("ValueUnit", "0")

    fmap = _FIELD_MAP.get(field)
    if not fmap:
        return False
    track_key, kind = fmap
    track_val = track.get(track_key)
    if track_val is None:
        return False

    # Date fields → timestamp; numeric "days ago"
    if track_key == "StockDate":
        ts = _date_to_ts(str(track_val))
        if ts is None:
            return False
        if op in ("0", "3", "4"):
            now = time.time()
            offset = _shift_unit(_coerce(val_l, float) or 0, unit)
            cutoff = now - offset
            if op == "3":  # > N days ago means newer than cutoff
                return ts >= cutoff
            if op == "4":  # < N days ago means older
                return ts < cutoff
            if op == "0":
                offset_r = _shift_unit(_coerce(val_r, float) or 0, unit)
                return now - offset_r <= ts <= now - offset
        return False

    # Numeric fields
    if kind in (int, float):
        tv = _coerce(track_val, kind)
        lv = _coerce(val_l, kind)
        rv = _coerce(val_r, kind)
        if tv is None or lv is None:
            return False
        if op == "0":  # in range
            return rv is not None and lv <= tv <= rv
        if op == "1":
            return tv == lv
        if op == "2":
            return tv != lv
        if op == "3":
            return tv > lv
        if op == "4":
            return tv < lv
        return False

    # String fields
    tv = str(track_val).lower()
    lv = (str(val_l) if val_l else "").lower()
    if op == "1":
        return tv == lv
    if op == "2":
        return tv != lv
    if op == "5":
        return lv in tv
    if op == "6":
        return lv not in tv
    if op == "7":
        return tv.startswith(lv)
    if op == "8":
        return tv.endswith(lv)
    return False


def evaluate(criteria: dict, tracks: list[dict]) -> list[dict]:
    """Apply criteria → matching tracks."""
    if not criteria:
        return list(tracks)
    conditions = criteria.get("conditions") or []
    if not conditions:
        return list(tracks)
    op = str(criteria.get("LogicalOperator", "all")).lower()
    use_all = op in ("all", "and", "1")

    result = []
    for t in tracks:
        try:
            checks = [_check_condition(t, c) for c in conditions]
            if (use_all and all(checks)) or (not use_all and any(checks)):
                result.append(t)
        except Exception as e:
            logger.debug(f"smart-eval skip track {t.get('id')}: {e}")
    return result


def to_xml_attrs(criteria: dict) -> dict[str, str]:
    """Serialize SmartList criteria to XML <SmartList> attributes (root-level)."""
    if not criteria:
        return {}
    return {
        "LogicalOperator": str(criteria.get("LogicalOperator", "all")),
        "AutomaticUpdate": str(criteria.get("AutomaticUpdate", "1")),
    }


def from_xml_node(node) -> dict:
    """Parse <SmartList> XML element → criteria dict."""
    if node is None:
        return {}
    out = {
        "LogicalOperator": node.get("LogicalOperator", "all"),
        "AutomaticUpdate": node.get("AutomaticUpdate", "1"),
        "conditions": [],
    }
    for c in node.findall("CONDITION"):
        out["conditions"].append({
            "Field": c.get("Field", ""),
            "Operator": c.get("Operator", "1"),
            "ValueLeft": c.get("ValueLeft", ""),
            "ValueRight": c.get("ValueRight", ""),
            "ValueUnit": c.get("ValueUnit", "0"),
        })
    return out
