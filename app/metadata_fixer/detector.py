"""Read-only detection of malformed artist/title metadata.

No writes. No filesystem touches — operates on plain ``{"title", "artist"}``
dicts the caller already loaded (from ``read_tags`` / ``DjmdContent``).

Each rule maps to a class in the malformation catalogue
(docs/research/implement/accepted_metadata-name-fixer.md, Findings 2026-05-15):

  1 — artist embedded in title parens   (empty artist + "Title (Artist)")
  2 — "feat." in title field            (suggestion-only; policy unresolved)
  4 — track-number prefix in title      ("01 - Intro" -> "Intro")
  5 — HTML-entity encoding              ("Rock &amp; Roll" -> "Rock & Roll")
  6 — smart-quotes / unicode dashes     (U+2019 -> U+0027, NFC)
  7 — double-encoded "Artist - Title"   (title prefix == artist -> strip)
  8 — label/catalog marker in title     ("Strobe [MAU5001]" -> "Strobe")

Class 3 (reversed Title/Artist) needs an external canonical source (MusicBrainz)
and is deliberately absent until M2. Classes {1,4,5,6,7,8} are the high-precision
M1 subset; class {2} is surfaced as a low-confidence suggestion only.
"""

from __future__ import annotations

import html
import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

# --- Class 6: smart-quote / dash translation map. NFC applied after. ---
_SMART_QUOTES = {
    0x2018: 0x27,  # left single quote  -> apostrophe (0x27)
    0x2019: 0x27,  # right single quote -> apostrophe (0x27)
    0x201C: 0x22,  # left double quote  -> quote (0x22)
    0x201D: 0x22,  # right double quote -> quote (0x22)
    0x2013: 0x2D,  # en dash            -> hyphen (0x2D)
    0x2014: 0x2D,  # em dash            -> hyphen (0x2D)
}

# --- Class 4: leading track-number prefix. ---
# Collision guard (Adversarial 2026-05-28): real release names like
# "19 - Naughty Forty" must NOT be stripped. Heuristic: only strip when the
# number is zero-padded ("01".."09") or a single digit ("1".."9") followed by a
# separator — a strong track-position signal. Two-digit non-padded numbers
# ("19 - …") are left alone (recall trade for precision, per the precision SLO).
_TRACK_NUM_PREFIX_RE = re.compile(r"^(?:0\d|\d)\s*[-.\s]\s+")

# --- Class 8: label/catalog-number bracket at end of title. ---
_CATALOG_BRACKET_RE = re.compile(r"\s*[\[(][A-Z]{2,5}\d{2,5}[\])]\s*$")
# Mix-name brackets must never be stripped by rule 8.
_MIX_NAME_WHITELIST = {
    "original mix",
    "extended mix",
    "radio edit",
    "club mix",
    "dub mix",
    "instrumental",
    "acapella",
}

# --- Class 1: trailing "(...)" capture + the leading non-paren stem. ---
_TRAILING_PAREN_RE = re.compile(r"^(?P<stem>.+?)\s*\((?P<inner>[^()]+)\)\s*$")

# --- Class 2: featuring marker inside a field. ---
_FEAT_RE = re.compile(r"\b(?:feat\.?|ft\.?|featuring)\b", re.IGNORECASE)

# A paren payload that looks like a mix/version descriptor, a year, or a
# remaster note is NOT an artist (guards rule 1 false-positives).
_PAREN_NOT_ARTIST_RE = re.compile(
    r"(?i)\b(?:mix|remix|edit|version|remaster(?:ed)?|bootleg|vip|dub|"
    r"instrumental|acapella|live|demo|\d{4})\b"
)


@dataclass(frozen=True)
class Match:
    """One detected malformation. ``before``/``suggested`` carry only changed fields."""

    rule_id: int
    rule_name: str
    confidence: float
    before: dict[str, str]
    suggested: dict[str, str]


@dataclass(frozen=True)
class Rule:
    rule_id: int
    name: str
    match_fn: Callable[[Mapping[str, str]], Match | None]
    #: Active rules batch-apply in M1; non-active are suggestion-only.
    active: bool = field(default=True)


def _s(track: Mapping[str, str], key: str) -> str:
    """Return a stripped string field, tolerant of None / missing keys."""
    val = track.get(key)
    return val.strip() if isinstance(val, str) else ""


def _rule_1_artist_in_title_parens(track: Mapping[str, str]) -> Match | None:
    artist = _s(track, "artist")
    title = _s(track, "title")
    if artist or not title:
        return None  # only fires when artist is blank
    m = _TRAILING_PAREN_RE.match(title)
    if not m:
        return None
    inner = m.group("inner").strip()
    stem = m.group("stem").strip()
    if not inner or not stem or _PAREN_NOT_ARTIST_RE.search(inner):
        return None
    return Match(
        rule_id=1,
        rule_name="artist_in_title_parens",
        confidence=0.90,
        before={"artist": "", "title": title},
        suggested={"artist": inner, "title": stem},
    )


def _rule_2_feat_in_title(track: Mapping[str, str]) -> Match | None:
    title = _s(track, "title")
    if not title or not _FEAT_RE.search(title):
        return None
    # Suggestion-only: policy (keep vs migrate to artist) is unresolved (OQ10).
    return Match(
        rule_id=2,
        rule_name="feat_in_title",
        confidence=0.50,
        before={"title": title},
        suggested={"title": title},  # no concrete rewrite; flagged for review
    )


def _rule_4_track_number_prefix(track: Mapping[str, str]) -> Match | None:
    title = _s(track, "title")
    if not title:
        return None
    stripped = _TRACK_NUM_PREFIX_RE.sub("", title, count=1)
    if stripped == title or not stripped:
        return None
    return Match(
        rule_id=4,
        rule_name="track_number_prefix",
        confidence=0.95,
        before={"title": title},
        suggested={"title": stripped},
    )


def _rule_5_html_entities(track: Mapping[str, str]) -> Match | None:
    out: dict[str, str] = {}
    before: dict[str, str] = {}
    for fieldname in ("title", "artist"):
        val = _s(track, fieldname)
        unescaped = html.unescape(val)
        if unescaped != val:
            before[fieldname] = val
            out[fieldname] = unescaped
    if not out:
        return None
    return Match(
        rule_id=5,
        rule_name="html_entities",
        confidence=0.98,
        before=before,
        suggested=out,
    )


def _rule_6_smart_quotes(track: Mapping[str, str]) -> Match | None:
    out: dict[str, str] = {}
    before: dict[str, str] = {}
    for fieldname in ("title", "artist"):
        val = _s(track, fieldname)
        if not val:
            continue
        fixed = unicodedata.normalize("NFC", val.translate(_SMART_QUOTES))
        if fixed != val:
            before[fieldname] = val
            out[fieldname] = fixed
    if not out:
        return None
    return Match(
        rule_id=6,
        rule_name="smart_quotes",
        confidence=0.98,
        before=before,
        suggested=out,
    )


def _rule_7_double_encoded_artist_prefix(track: Mapping[str, str]) -> Match | None:
    artist = _s(track, "artist")
    title = _s(track, "title")
    if not artist or " - " not in title:
        return None
    prefix, _, rest = title.partition(" - ")
    if prefix.strip().casefold() != artist.casefold() or not rest.strip():
        return None
    return Match(
        rule_id=7,
        rule_name="double_encoded_artist_prefix",
        confidence=0.90,
        before={"title": title},
        suggested={"title": rest.strip()},
    )


def _rule_8_catalog_bracket(track: Mapping[str, str]) -> Match | None:
    title = _s(track, "title")
    if not title:
        return None
    m = _CATALOG_BRACKET_RE.search(title)
    if not m:
        return None
    inner = m.group(0).strip(" []()").casefold()
    if inner in _MIX_NAME_WHITELIST:
        return None
    stripped = _CATALOG_BRACKET_RE.sub("", title, count=1).strip()
    if not stripped or stripped == title:
        return None
    return Match(
        rule_id=8,
        rule_name="catalog_bracket",
        confidence=0.85,
        before={"title": title},
        suggested={"title": stripped},
    )


#: Catalogue order = rule order. Class 3 (reversed) deferred to M2 (needs MusicBrainz).
_CATALOGUE: list[Rule] = [
    Rule(1, "artist_in_title_parens", _rule_1_artist_in_title_parens),
    Rule(2, "feat_in_title", _rule_2_feat_in_title, active=False),
    Rule(4, "track_number_prefix", _rule_4_track_number_prefix),
    Rule(5, "html_entities", _rule_5_html_entities),
    Rule(6, "smart_quotes", _rule_6_smart_quotes),
    Rule(7, "double_encoded_artist_prefix", _rule_7_double_encoded_artist_prefix),
    Rule(8, "catalog_bracket", _rule_8_catalog_bracket),
]

#: High-precision subset that M1 may batch-apply (precision SLO >= 98%).
ACTIVE_RULE_IDS: frozenset[int] = frozenset(r.rule_id for r in _CATALOGUE if r.active)


def scan(
    tracks: Iterable[Mapping[str, str]],
    *,
    rule_ids: Iterable[int] | None = None,
) -> list[tuple[Mapping[str, str], Match]]:
    """Run the catalogue over ``tracks``. Pure: never mutates inputs.

    Returns ``(track, match)`` pairs — one per fired rule per track. Pass
    ``rule_ids`` to restrict to a subset (e.g. ``ACTIVE_RULE_IDS``).
    """
    wanted = frozenset(rule_ids) if rule_ids is not None else None
    catalogue = _CATALOGUE if wanted is None else [r for r in _CATALOGUE if r.rule_id in wanted]
    results: list[tuple[Mapping[str, str], Match]] = []
    for track in tracks:
        for rule in catalogue:
            match = rule.match_fn(track)
            if match is not None:
                results.append((track, match))
    return results
