"""Track-metadata field policy: which keys a library backend stores, and their value rules.

``LiveRekordboxDB.update_track_metadata`` used to answer True for "BPM", "Key" or a typo
like "ArtistName" and write nothing, and stored ``None`` as the string ``'None'``. The XML
facade merged any key and any value into memory: ``save_xml`` dropped the unknown keys,
and a value it could not serialise (an int Title, ``Key: 8``) truncated the library file.
Every track-metadata write now runs :func:`normalise_track_updates` first, so a refused
update raises before the first write. No heavy imports: the routes and the metadata
fixer import this without pulling in rbox.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping
from typing import Any

#: Keys ``LiveRekordboxDB.update_track_metadata`` writes to master.db.
LIVE_WRITABLE_FIELDS: frozenset[str] = frozenset(
    {"Title", "Comment", "Rating", "ColorID", "Artist", "Genre", "Album"}
)

#: Keys the XML backend persists: what ``RekordboxXMLDB.save_xml`` writes back and
#: ``_parse_track`` reads. A key outside it would sit in memory until the next load.
XML_WRITABLE_FIELDS: frozenset[str] = frozenset(
    {
        "Title",
        "Artist",
        "Album",
        "BPM",
        "Key",
        "Genre",
        "Label",
        "Comment",
        "TotalTime",
        "Rating",
        "ColorID",
        "beatGrid",
        "positionMarks",
    }
)

_WRITABLE: dict[str, frozenset[str]] = {"live": LIVE_WRITABLE_FIELDS, "xml": XML_WRITABLE_FIELDS}

_STR_FIELDS = frozenset({"Title", "Artist", "Album", "Genre", "Comment", "Key", "Label"})
_FLOAT_FIELDS = frozenset({"BPM", "TotalTime"})
_LIST_FIELDS = frozenset({"beatGrid", "positionMarks"})
# master.db stores Rating 0-5; Rekordbox XML stores it raw (0/51/../255). ColorID is a
# djmdColor row (1-8, 0 = none) and lands in a u8 of the PDB track row on USB export.
_INT_RANGES: dict[str, dict[str, tuple[int, int]]] = {
    "live": {"Rating": (0, 5), "ColorID": (0, 8)},
    "xml": {"Rating": (0, 255), "ColorID": (0, 8)},
}
# Characters XML 1.0 cannot carry. ElementTree writes them unescaped, and the next
# load_xml then fails on the whole library file.
_XML_ILLEGAL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿]")


class TrackFieldError(ValueError):
    """A track update the backend refuses as a whole. Nothing was written."""


class UnsupportedTrackFields(TrackFieldError):
    """The update names field keys this backend cannot write."""

    def __init__(self, fields: Iterable[str], backend: str) -> None:
        self.fields = sorted(fields)
        self.backend = backend
        super().__init__(f"{backend} library cannot write field(s): {', '.join(self.fields)}")


class InvalidTrackFieldValue(TrackFieldError):
    """A known field carries a value the backend cannot store."""


def writable_fields(backend: str) -> frozenset[str]:
    """Field keys ``backend`` (``"live"`` / ``"xml"``) persists."""
    return _WRITABLE[backend]


def _int_value(key: str, value: Any, lo: int, hi: int) -> int:
    # bool is an int subclass, and a float would be truncated silently (3.9 -> 3).
    if not isinstance(value, bool) and isinstance(value, (int, str)):
        try:
            number = int(value) if isinstance(value, int) else int(value.strip())
        except ValueError:
            pass
        else:
            if lo <= number <= hi:
                return number
    raise InvalidTrackFieldValue(f"{key} must be an integer {lo}-{hi}, got {value!r}")


def _float_value(key: str, value: Any) -> float:
    if not isinstance(value, bool) and isinstance(value, (int, float)):
        try:
            number = float(value)
        except OverflowError:  # an int beyond float range
            pass
        else:
            if math.isfinite(number) and number >= 0:
                return number
    raise InvalidTrackFieldValue(f"{key} must be a finite number >= 0, got {value!r}")


def _check_xml_text(key: str, value: str) -> None:
    if _XML_ILLEGAL.search(value):
        raise InvalidTrackFieldValue(f"{key} contains a character XML cannot store")


def normalise_track_updates(updates: Mapping[str, Any], backend: str) -> dict[str, Any]:
    """Allowlist the keys and type-check every value. Raises before anything is written.

    Raises ``UnsupportedTrackFields`` for a key outside :func:`writable_fields` and
    ``InvalidTrackFieldValue`` for a value of the wrong type or range, ``None``
    included; for ``"xml"`` also for text XML 1.0 cannot carry. Returns a copy with
    Rating / ColorID as ``int`` and BPM / TotalTime as ``float``.
    """
    unknown = set(updates) - writable_fields(backend)
    if unknown:
        raise UnsupportedTrackFields(unknown, backend)
    xml = backend == "xml"
    ranges = _INT_RANGES[backend]
    out = dict(updates)
    for key, value in out.items():
        if key in ranges:
            lo, hi = ranges[key]
            out[key] = _int_value(key, value, lo, hi)
        elif key in _STR_FIELDS:
            if not isinstance(value, str):
                raise InvalidTrackFieldValue(f"{key} must be a string, got {value!r}")
            if xml:
                _check_xml_text(key, value)
        elif key in _FLOAT_FIELDS:
            out[key] = _float_value(key, value)
        elif key in _LIST_FIELDS:
            if not isinstance(value, list) or not all(isinstance(i, Mapping) for i in value):
                raise InvalidTrackFieldValue(f"{key} must be a list of objects")
            if xml:
                for item in value:
                    for v in item.values():
                        if isinstance(v, str):
                            _check_xml_text(key, v)
    return out
