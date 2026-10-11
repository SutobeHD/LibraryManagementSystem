"""Track-metadata field policy: which keys a library backend stores, and their value rules.

``LiveRekordboxDB.update_track_metadata`` used to answer True for "BPM", "Key" or a typo
like "ArtistName" and write nothing, and stored ``None`` as the string ``'None'``. Every
track-metadata write now runs :func:`normalise_track_updates` first, so a refused update
raises before the first write. No heavy imports: the routes and the metadata fixer
import this without pulling in rbox.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

#: Keys ``LiveRekordboxDB.update_track_metadata`` writes to master.db.
LIVE_WRITABLE_FIELDS: frozenset[str] = frozenset(
    {"Title", "Comment", "Rating", "ColorID", "Artist", "Genre", "Album"}
)

_WRITABLE: dict[str, frozenset[str]] = {"live": LIVE_WRITABLE_FIELDS}

_STR_FIELDS = frozenset({"Title", "Artist", "Album", "Genre", "Comment"})
# master.db stores Rating 0-5. ColorID is a djmdColor row (1-8, 0 = none) and lands in
# a u8 of the PDB track row on USB export.
_INT_RANGES: dict[str, dict[str, tuple[int, int]]] = {
    "live": {"Rating": (0, 5), "ColorID": (0, 8)},
}


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
    """Field keys ``backend`` persists."""
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


def normalise_track_updates(updates: Mapping[str, Any], backend: str) -> dict[str, Any]:
    """Allowlist the keys and type-check every value. Raises before anything is written.

    Raises ``UnsupportedTrackFields`` for a key outside :func:`writable_fields` and
    ``InvalidTrackFieldValue`` for a value of the wrong type or range, ``None``
    included. Returns a copy with Rating / ColorID as ``int``.
    """
    unknown = set(updates) - writable_fields(backend)
    if unknown:
        raise UnsupportedTrackFields(unknown, backend)
    ranges = _INT_RANGES[backend]
    out = dict(updates)
    for key, value in out.items():
        if key in ranges:
            lo, hi = ranges[key]
            out[key] = _int_value(key, value, lo, hi)
        elif key in _STR_FIELDS and not isinstance(value, str):
            raise InvalidTrackFieldValue(f"{key} must be a string, got {value!r}")
    return out
