"""artist_store.recognizer — who a downloaded track is by, and the names its file gets.

Owner refinement 2026-09-26 (2): "beim Downloaden einen Erkenner, ob es den Artist
gibt und Song linked etc und Name korrekt ist". The SoundCloud downloader calls
:func:`recognize` between its metadata fetch and its tag write, so a file enters the
library under the artist's own name — and the artist page, the Rekordbox playlist and
the catalogue diff pick it up with no manual step.

SoundCloud's fields lie in known ways: a label or promo channel uploads
``Artist - Title`` under its own name, an artist re-cases their name, the title carries
``(X Remix)`` / ``feat. X``. Three questions per download:

1. **Who is credited?** Label metadata (``publisher_metadata.artist``) first, then a
   title prefix, then the uploader. A version phrase on either side of the dash
   (``Overdrive - Extended Mix``) is never a credit.
2. **Is that artist known?** The hub's own answer — stored collections, aliases,
   favourites, library spellings, the SoundCloud account an artist is bound to.
   Tolerance widens exact -> case -> ``merge.fold_key`` and stops at the first tier
   that hits; two artists behind one key is ambiguous and answers "unknown".
3. **What does the file say?** Only a HIGH-confidence correction is applied; a split
   nothing vouches for comes back as a :class:`Suggestion` the user applies — the
   metadata-name-fixer rule, never rename on a guess (Threat T18).

Pure apart from artists.db reads: no network, no writes.
"""

from __future__ import annotations

import logging
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from app.artist_store import identity, registry, schema
from app.artist_store.merge import fold_key
from app.artist_store.schema import KIND_ARTIST

logger = logging.getLogger("ARTIST_STORE")

#: What ``_apply_sc_metadata`` has always written when SoundCloud names nobody.
UNKNOWN_ARTIST = "Unknown Artist"

CORRECTION_TITLE_REPEATS_ARTIST = "title_repeats_artist"
CORRECTION_KNOWN_ARTIST_PREFIX = "known_artist_prefix"
CORRECTION_BOUND_ACCOUNT = "bound_account"
CORRECTION_KNOWN_SPELLING = "known_spelling"

SUGGESTION_UNKNOWN_ARTIST_PREFIX = "unknown_artist_prefix"


@dataclass(frozen=True)
class Credit:
    """One name on the track, as the hub knows it. ``role`` is relative to that artist."""

    name: str
    role: str
    known: bool
    collection_id: str | None = None
    canonical: str | None = None
    stored: bool = False
    favourite: bool = False
    library_tracks: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "role": self.role,
            "known": self.known,
            "collection_id": self.collection_id,
            "canonical": self.canonical,
            "stored": self.stored,
            "favourite": self.favourite,
            "library_tracks": self.library_tracks,
        }


@dataclass(frozen=True)
class Suggestion:
    """A correction nothing vouches for — shown, never written."""

    artist: str
    title: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {"artist": self.artist, "title": self.title, "reason": self.reason}


@dataclass(frozen=True)
class Recognition:
    raw_artist: str
    raw_title: str
    artist: str
    title: str
    corrections: tuple[str, ...]
    credits: tuple[Credit, ...]
    suggestion: Suggestion | None = None

    @property
    def changed(self) -> bool:
        return self.artist != self.raw_artist or self.title != self.raw_title

    def as_dict(self) -> dict[str, Any]:
        return {
            "raw_artist": self.raw_artist,
            "raw_title": self.raw_title,
            "artist": self.artist,
            "title": self.title,
            "changed": self.changed,
            "corrections": list(self.corrections),
            "suggestion": self.suggestion.as_dict() if self.suggestion else None,
            "credits": [c.as_dict() for c in self.credits],
        }


def _clean(value: Any) -> str:
    """Whitespace collapsed; a control character is a space — never a tag's business."""
    text = "".join(" " if unicodedata.category(ch) == "Cc" else ch for ch in str(value or ""))
    return " ".join(text.split())


class _Lookup:
    """Name -> known artist, from ONE ``registry.known_artists`` pass."""

    def __init__(self, db: Any, kind: str) -> None:
        rows = registry.known_artists(db, kind)
        self._rows = {str(r["collection_id"]): r for r in rows}
        self._tiers: tuple[dict[str, set[str]], ...] = ({}, {}, {})
        for row in rows:
            cid = str(row["collection_id"])
            for spelling in row["spellings"]:
                text = _clean(spelling)
                if not text:
                    continue
                for tier, key in zip(self._tiers, _keys(text), strict=True):
                    if key:
                        tier.setdefault(key, set()).add(cid)

    def find(self, name: str) -> dict[str, Any] | None:
        text = _clean(name)
        if not text:
            return None
        for tier, key in zip(self._tiers, _keys(text), strict=True):
            hits = tier.get(key) if key else None
            if hits:
                return self._rows[next(iter(hits))] if len(hits) == 1 else None
        return None

    def by_id(self, collection_id: str | None) -> dict[str, Any] | None:
        return self._rows.get(collection_id) if collection_id else None


def _keys(text: str) -> tuple[str, str, str]:
    """Exact, then case-insensitive, then ``fold_key`` — widest last."""
    return text, text.casefold(), fold_key(text)


def _user_urn(user: Mapping[str, Any]) -> str:
    urn = _clean(user.get("urn"))
    if urn:
        return urn
    uid = _clean(user.get("id"))
    return f"soundcloud:users:{uid}" if uid.isdigit() else ""


def _same_name(a: str, b: str) -> bool:
    """Equal up to ``fold_key``, or up to every non-alphanumeric (``boysnoize``)."""
    fa, fb = fold_key(a), fold_key(b)
    if not fa or not fb:
        return False
    return fa == fb or identity._compact(fa) == identity._compact(fb)


def _prefix_split(title: str) -> tuple[str, str] | None:
    """``Artist - Title`` -> (artist, title), unless either side is a version phrase."""
    credit = identity.parse_credit(title)
    prefix, body = _clean(credit.artist_prefix), _clean(credit.title_body)
    if not prefix or not body:
        return None
    if identity._is_version_vocab(prefix) or identity._is_version_vocab(body):
        return None
    return prefix, body


def _names_in(artist_field: str) -> list[str]:
    return identity._split_names(identity._strip_feat(artist_field))


def _names_a_known_artist(prefix: str, lookup: _Lookup) -> bool:
    return lookup.find(prefix) is not None or any(
        lookup.find(name) is not None for name in _names_in(prefix)
    )


def _peel_version(name: str) -> str:
    """``Boys Noize VIP`` -> ``Boys Noize``: a version word is never part of a person."""
    words = name.split()
    while words and fold_key(words[-1]) in identity._VERSION_VOCAB:
        words.pop()
    return " ".join(words)


def _credit(name: str, role: str, lookup: _Lookup) -> Credit:
    known = lookup.find(name)
    if known is None:
        return Credit(name=name, role=role, known=False)
    return Credit(
        name=name,
        role=role,
        known=True,
        collection_id=str(known["collection_id"]),
        canonical=str(known["name"]),
        stored=bool(known["stored"]),
        favourite=bool(known["favourite"]),
        library_tracks=int(known["library_tracks"]),
    )


def _credits(artist: str, title: str, lookup: _Lookup) -> tuple[Credit, ...]:
    """Everyone named, each with the role the artist page would give the track."""
    parse = identity.parse_credit(title)
    primaries = _names_in(artist)
    remixers = [n for n in (_peel_version(r) for r in parse.remixer_names) if n]
    remixers = [r for r in remixers if not any(_same_name(r, p) for p in primaries)]
    featured = [*identity._featured_names(artist), *parse.featured]
    primary_role = schema.ROLE_REMIXED_BY_OTHER if remixers else schema.ROLE_PRIMARY
    named: Iterable[tuple[str, str]] = (
        *((n, primary_role) for n in primaries),
        *((n, schema.ROLE_REMIXER) for n in remixers),
        *((n, schema.ROLE_FEATURED) for n in featured),
    )
    out: list[Credit] = []
    seen: set[str] = set()
    for name, role in named:
        credit = _credit(name, role, lookup)
        key = credit.collection_id or f"name:{fold_key(name)}"
        if key in seen:
            continue
        seen.add(key)
        out.append(credit)
    return tuple(out)


def recognize(
    sc_meta: Mapping[str, Any], db: Any = None, *, kind: str = KIND_ARTIST
) -> Recognition:
    """The names a SoundCloud download should carry, and who is on it.

    ``sc_meta`` is the v2 track payload ``_apply_sc_metadata`` reads (``user``,
    ``publisher_metadata``, ``title``). ``db`` is the loaded library or None — without
    one only the artist store vouches for a name.
    """
    user = sc_meta.get("user") or {}
    pub = sc_meta.get("publisher_metadata") or {}
    uploader = _clean(user.get("username"))
    label_artist = _clean(pub.get("artist"))
    raw_artist = label_artist or uploader or UNKNOWN_ARTIST
    raw_title = _clean(pub.get("release_title") or sc_meta.get("title"))

    lookup = _Lookup(db, kind)
    artist, title = raw_artist, raw_title
    corrections: list[str] = []
    suggestion: Suggestion | None = None
    from_uploader = not label_artist

    split = _prefix_split(raw_title) if raw_title else None
    if split is not None:
        prefix, body = split
        if _same_name(prefix, raw_artist):
            # The credited artist, typed again: keep the human spelling over a handle.
            if from_uploader and fold_key(prefix) != fold_key(raw_artist):
                artist = prefix
            title = body
            corrections.append(CORRECTION_TITLE_REPEATS_ARTIST)
        elif from_uploader:
            if _names_a_known_artist(prefix, lookup):
                artist, title = prefix, body
                from_uploader = False
                corrections.append(CORRECTION_KNOWN_ARTIST_PREFIX)
            else:
                suggestion = Suggestion(prefix, body, SUGGESTION_UNKNOWN_ARTIST_PREFIX)

    if from_uploader and artist == uploader:
        bound = lookup.by_id(
            schema.collection_for_remote(registry.PROVIDER_SOUNDCLOUD, _user_urn(user))
        )
        if bound is not None and str(bound["name"]) != artist:
            artist = str(bound["name"])
            corrections.append(CORRECTION_BOUND_ACCOUNT)

    # "Unknown Artist" is a placeholder, never a person — not even one the library has
    # a pile of untagged tracks under.
    named = artist != UNKNOWN_ARTIST
    known = lookup.find(artist) if named else None
    if known is not None and str(known["name"]) != artist:
        artist = str(known["name"])
        corrections.append(CORRECTION_KNOWN_SPELLING)

    # Credits describe the likeliest reading: with a suggestion pending that is the
    # suggestion, so "is the artist known?" is asked about the artist, not the label.
    reading = (suggestion.artist, suggestion.title) if suggestion else (artist, title)
    recognition = Recognition(
        raw_artist=raw_artist,
        raw_title=raw_title,
        artist=artist,
        title=title,
        corrections=tuple(corrections),
        credits=_credits(*reading, lookup) if named or suggestion else (),
        suggestion=suggestion,
    )
    logger.info(
        "op=download_recognize changed=%s corrections=%s known=%d suggestion=%s",
        recognition.changed,
        ",".join(recognition.corrections) or "-",
        sum(c.known for c in recognition.credits),
        bool(suggestion),
    )
    return recognition


__all__ = [
    "CORRECTION_BOUND_ACCOUNT",
    "CORRECTION_KNOWN_ARTIST_PREFIX",
    "CORRECTION_KNOWN_SPELLING",
    "CORRECTION_TITLE_REPEATS_ARTIST",
    "SUGGESTION_UNKNOWN_ARTIST_PREFIX",
    "UNKNOWN_ARTIST",
    "Credit",
    "Recognition",
    "Suggestion",
    "recognize",
]
