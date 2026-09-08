"""artist_store.catalogue — classify an artist's SoundCloud tracks, diff against the library (T-14).

Three jobs, kept apart so each is testable on its own:

``classify``
    Splits a fetched catalogue into the owner's three buckets on the **uploader
    account URN**. Since 2026-09-08 that is the highest-confidence signal, not the
    only one: the name-driven, remix-aware role layer lives in
    ``app/artist_store/identity.py`` and runs on top of these buckets.
``diff``
    "Do I already own this?" — reuses ``app/external_track_match.py`` (``parse_version_tag``,
    ``extract_title_stem``, ``fuzzy_match_with_score``) behind a derivation gate so a
    remix/VIP never collapses onto the original it derives from.
``catalogue``
    Ties the two together over the sidecar's TTL cache. The **fetched catalogue** is
    cached, never the diff — the local side changes whenever the library does.

This module never sees the OAuth token. The fetch callable is supplied by the caller
(the route owns the keyring), so there is no token here to log, cache or key on.

Pure + stdlib apart from the sidecar schema: no HTTP, no ``master.db``, no rbox.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.artist_store import schema
from app.external_track_match import (
    extract_title_stem,
    fuzzy_match_with_score,
    parse_version_tag,
)

logger = logging.getLogger("ARTIST_STORE")

PROVIDER_SOUNDCLOUD = "soundcloud"

BUCKET_THEIRS = "definitely_theirs"
BUCKET_REMIXES = "remixes_by_others"
BUCKET_MIXES = "mixes_and_sets"

#: Anything longer is a set, not a track. Owner rule; catches the long-form the
#: keyword list misses (an untitled 40-minute live recording).
LONG_FORM_MS = 15 * 60 * 1000

#: Hard per-artist ceiling (threat T7). A hostile or absurd profile cannot make the
#: sidecar hold an unbounded payload; the overflow is reported as ``truncated``.
MAX_CATALOGUE_TRACKS = 2000

#: TTL for the sidecar catalogue cache. Long enough that clicking through artists
#: costs no calls, short enough that it stays a cache and not a mirror (ToU).
CACHE_TTL_S = 6 * 60 * 60

#: Owned-vs-remote match threshold. Tuned on the seeded corpus in
#: ``tests/test_artist_catalogue.py`` (``test_missing_diff_threshold_corpus``), which
#: pins both directions: same-track-different-punctuation must match, remix/VIP/other-track
#: must not. Deliberately far above ``external_track_match``'s own 0.65 default — that
#: value was tuned for free-text external search, while here the strings are already
#: stem-reduced, accent-folded, derivation-gated and token-gated, so true pairs land at
#: or near 1.0 and the headroom is spent rejecting near-miss titles.
MISSING_MATCH_THRESHOLD = 0.90

#: Minimum Jaccard overlap of the two title stems' word sets before the fuzzy score is
#: even consulted. SequenceMatcher cannot separate "Kill the Beat" from "Kill the Beast"
#: (0.981) from "Cafe Racer" vs "Café Racer" (0.957) — one differing character inside a
#: word costs about as much as an accent. Comparing word *sets* does separate them: a
#: substituted word breaks the set, re-punctuation ("Rock & Roll" / "Rock and Roll") does
#: not. Bias is deliberate: a wrongly-owned verdict hides a track the user does not have
#: (the gig-night failure this feature exists to prevent), while a wrongly-missing one
#: only shows an extra row.
TOKEN_OVERLAP_FLOOR = 0.65

#: Upper bound on fuzzy comparisons per remote track. The blocking index normally hands
#: back a handful; this stops a pathological library (thousands of same-named tracks)
#: from turning one diff into a full cross-product.
MAX_FUZZY_CANDIDATES = 400

#: Version labels that describe the SAME recording for ownership purposes. Owning
#: "Overdrive" means you are not missing "Overdrive (Original Mix)".
_BASE_LABELS = frozenset(
    {"original", "extended", "radio", "club", "dub", "instrumental", "acapella"}
)

#: Mix/set keywords. ⚠️ A bare ``\bmix\b`` is deliberately ABSENT — "Original Mix",
#: "Extended Mix" and "Club Mix" are exactly the tracks the user wants. Long-form is
#: caught by ``LONG_FORM_MS`` instead.
_MIX_KEYWORDS = re.compile(
    r"\b(?:"
    r"podcast|dj[\s\-_]?set|live[\s\-_]?set|radio[\s\-_]?show|episodes?"
    r"|ep\.?\s?\d{1,4}|b2b|boiler[\s\-_]?room|essential[\s\-_]?mix|guest[\s\-_]?mix"
    r"|mixtape|takeover|residency"
    r")\b",
    re.IGNORECASE,
)

_URN_USER_RE = re.compile(r"^soundcloud:users:(\d+)$", re.IGNORECASE)
_DIGITS_RE = re.compile(r"^\d+$")
_WS_RUN = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^\w]+")
_FIRST_TOKEN = re.compile(r"\w+")

#: ISO 3901: 2-letter country, 3-char registrant, 2-digit year, 5-digit designation.
#: Anything else ("", "0", "unknown", a placeholder a label typed) is not an identity
#: and must never short-circuit the diff to "owned".
_ISRC_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{3}\d{7}$")
_ISRC_STRIP = re.compile(r"[\s\-]+")

#: How a remote track was matched to a local one. ``isrc`` is exact identity;
#: ``title`` is the fuzzy path; ``none`` means the diff found no owned track.
MATCH_ISRC = "isrc"
MATCH_TITLE = "title"
MATCH_NONE = "none"


# ── Errors ────────────────────────────────────────────────────────────────────


class CatalogueError(Exception):
    """Base of the catalogue error hierarchy. Routes map these to explicit responses."""


class ArtistNotLinked(CatalogueError):
    """The collection has no SoundCloud account bound, so there is nothing to fetch.

    Raised instead of returning an empty catalogue: an empty list would render as
    "this artist has released nothing", which is a lie about state we do not have.
    """


class CatalogueUnavailable(CatalogueError):
    """No cached catalogue and no way to fetch one (no fetcher / no credentials).

    The UI must say so rather than showing an empty or stale list as if it were live.
    """


# ── Result types ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Classification:
    """The owner's three buckets. Every fetched track lands in exactly one of them.

    There is deliberately no fourth "discard" bucket: a track that was fetched but shown
    nowhere is a silent drop, and the owner ruled those out for the mix filter for the
    same reason. A foreign upload whose credit cannot be proven is still listed under
    ``remixes_by_others`` — visible, never auto-queued — carrying ``credited=False``.
    """

    definitely_theirs: list[dict[str, Any]] = field(default_factory=list)
    remixes_by_others: list[dict[str, Any]] = field(default_factory=list)
    mixes_and_sets: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class TrackMatch:
    """One remote track's verdict against the library.

    ``method`` says HOW it was decided: an exact ISRC hit is identity, a title score is
    a similarity — the UI should not present the two with the same certainty.
    """

    sc_id: str
    local_track_id: str | None
    score: float
    method: str = MATCH_NONE

    @property
    def matched(self) -> bool:
        return self.local_track_id is not None


@dataclass(frozen=True)
class Diff:
    """``sc_id`` -> verdict, plus the owned / missing split as id tuples."""

    matches: dict[str, TrackMatch] = field(default_factory=dict)
    in_library: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()


# ── Small helpers ─────────────────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_user_urn(value: Any) -> str:
    """Canonical ``soundcloud:users:<id>`` form. Empty string when unusable.

    Numeric ids are spec-deprecated in favour of URNs but still flow through older call
    sites and cached payloads, so both shapes fold onto one comparable value. Identity
    comparison is only ever done on this — never on a display name.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    if _DIGITS_RE.match(text):
        return f"soundcloud:users:{text}"
    m = _URN_USER_RE.match(text)
    if m:
        return f"soundcloud:users:{m.group(1)}"
    return text.casefold()


def normalize_isrc(value: Any) -> str:
    """Canonical 12-character ISRC (upper, no dashes/spaces), or ``""`` when not one.

    Rekordbox stores whatever the tag carried (``US-RC1-17-07839`` or ``USRC11707839``)
    and SoundCloud returns whatever the uploader typed. Both fold onto one comparable
    string; a value that does not have the ISO 3901 shape is discarded rather than
    compared, so two tracks tagged ``"0"`` never read as the same recording.
    """
    text = _ISRC_STRIP.sub("", str(value or "")).upper()
    return text if _ISRC_RE.match(text) else ""


def _accent_fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", str(text or ""))
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _fold(text: str) -> str:
    """Accent-folded, punctuation-collapsed, lowercase form for name comparison."""
    stripped = _accent_fold(text)
    return _WS_RUN.sub(" ", _NON_ALNUM.sub(" ", stripped)).strip().casefold()


def _tokens(stem: str) -> frozenset[str]:
    return frozenset(_fold(stem).split())


def token_overlap(left: str, right: str) -> float:
    """Jaccard overlap of two stems' word sets. 0.0 when either side has no words."""
    a, b = _tokens(left), _tokens(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _first_token(text: str) -> str:
    m = _FIRST_TOKEN.search(text)
    return m.group(0).casefold() if m else ""


#: Parenthetical head words that mark a DIFFERENT recording, not a spelling of the
#: same one. Anything here must never fold onto the original — missing it hides a
#: genuine gap. ``original``/``extended``/``club`` are deliberately absent: those ARE
#: the track you own.
_BARE_DERIVATIONS = frozenset(
    {
        "remix",
        "rework",
        "refix",
        "reprise",
        "rerub",
        "redux",
        "bootleg",
        "flip",
        "mashup",
        "edit",
        "vip",
        "live",
        "acoustic",
        "demo",
        "unplugged",
        "remaster",
        "remastered",
        "reimagined",
        "interpretation",
    }
)

_TRAILING_PAREN = re.compile(r"[([{]([^)\]}]{1,60})[)\]}]\s*$")


def _bare_derivation(title: str) -> str:
    """The derivation word of a trailing ``(Remix)``-style parenthetical, else ``""``.

    Only fires when the parenthetical is *just* the derivation word (optionally with a
    year or a short qualifier), because a named remixer is already handled upstream.
    """
    match = _TRAILING_PAREN.search(title.strip())
    if match is None:
        return ""
    words = _fold(match.group(1)).split()
    if not words:
        return ""
    for word in words:
        if word in _BARE_DERIVATIONS:
            return word
    return ""


def derivation_key(title: str) -> tuple[str, str]:
    """Identity of the *version* a title describes: ``("base", "")`` or (label, who).

    The gate that keeps a remix from collapsing onto the original it derives from.
    ``(Original Mix)`` / ``(Extended Mix)`` / bare all fold to ``base`` — owning the
    track means you are not missing its original-mix listing. ``(X Remix)``, ``(VIP)``,
    ``(2019 Edit)``, ``(X Bootleg)`` each get their own key, so they are separate
    recordings you may legitimately be missing.
    """
    raw = str(title or "")
    tag = parse_version_tag(raw)
    if tag is None:
        # parse_version_tag only recognises a parenthetical that names a remixer or
        # carries a label it knows. A BARE derivation — "(Remix)", "(Live)", "(Flip)" —
        # falls through, and returning ("base", "") here made it collapse onto the
        # original: the track then reads as ALREADY OWNED and a real gap is hidden.
        # That is the dangerous direction, so a bare derivation gets its own key.
        bare = _bare_derivation(raw)
        return (bare, "") if bare else ("base", "")
    if tag.remixer:
        return (tag.label, _fold(tag.remixer))
    if tag.label in _BASE_LABELS:
        return ("base", "")
    return (tag.label, _fold(" ".join(tag.modifiers)))


def title_stems(title: str, known_names: Iterable[str] = ()) -> tuple[str, ...]:
    """Candidate grouping stems for a title, best first.

    SoundCloud titles routinely carry an ``Artist - `` prefix that Rekordbox keeps in a
    separate field. ``extract_title_stem`` reads ``" - "`` as a trailing *version*
    separator and would reduce ``"Boys Noize - Overdrive"`` to ``"boys noize"``, so the
    prefix is stripped here first when it matches a known name; when it matches nothing
    both readings are returned and the caller scores against each.
    """
    text = _WS_RUN.sub(" ", str(title or "")).strip()
    if not text:
        return ()
    known = {_fold(n) for n in known_names if str(n or "").strip()}
    out: list[str] = []

    def _add(value: str) -> None:
        # Accents are folded here, not left to the scorer: its exact-title short circuit
        # runs with nfd_fold=False, so "Café Racer" would otherwise fall to the ratio path.
        folded = _accent_fold(value).strip()
        if folded and folded not in out:
            out.append(folded)

    head, sep, tail = text.partition(" - ")
    if sep and tail.strip():
        if _fold(head) in known:
            _add(extract_title_stem(tail.strip()))
            return tuple(out)
        _add(extract_title_stem(text))
        _add(extract_title_stem(tail.strip()))
        return tuple(out)
    _add(extract_title_stem(text))
    return tuple(out)


def _artist_names_for(track: Mapping[str, Any], extra: Iterable[str] = ()) -> tuple[str, ...]:
    names = [str(track.get("uploader_name") or "").strip()]
    names.extend(str(n or "").strip() for n in extra)
    return tuple(n for n in names if n)


# ── Track coercion (SC payloads are untrusted input) ───────────────────────────


def _coerce_track(raw: Any) -> dict[str, Any] | None:
    """Normalised SC track dict with every field forced to its contract type.

    Returns ``None`` for a payload with no usable identity — a track we cannot name or
    address is not something to show the user, and inventing a placeholder would be a
    fabricated row.
    """
    if not isinstance(raw, Mapping):
        return None
    sc_id = str(raw.get("sc_id") or "").strip()
    title = str(raw.get("title") or "").strip()
    if not sc_id or not title:
        return None
    try:
        duration_ms = int(raw.get("duration_ms") or 0)
    except (TypeError, ValueError):
        duration_ms = 0
    return {
        "sc_id": sc_id,
        "title": title,
        "permalink_url": str(raw.get("permalink_url") or ""),
        "duration_ms": max(0, duration_ms),
        "uploader_urn": str(raw.get("uploader_urn") or ""),
        "uploader_name": str(raw.get("uploader_name") or ""),
        "genre": str(raw.get("genre") or ""),
        "tag_list": str(raw.get("tag_list") or ""),
        "access": str(raw.get("access") or "").strip().casefold(),
        "streamable": bool(raw.get("streamable")),
        "sharing": str(raw.get("sharing") or "").strip().casefold(),
        "downloadable": bool(raw.get("downloadable")),
        "created_at": str(raw.get("created_at") or ""),
        "artwork_url": str(raw.get("artwork_url") or ""),
        # Normalised here so the diff, the identity table and the UI all compare the
        # same 12 characters; "" when the upload carries no usable ISRC.
        "isrc": normalize_isrc(raw.get("isrc")),
        "label_name": str(raw.get("label_name") or "").strip(),
    }


def coerce_track(raw: Any) -> dict[str, Any] | None:
    """Public single-row form of the coercion; ``None`` for a row with no identity."""
    return _coerce_track(raw)


def coerce_tracks(raw_tracks: Iterable[Any]) -> list[dict[str, Any]]:
    """Coerce a fetched payload, dropping unusable rows and de-duplicating by ``sc_id``."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in raw_tracks or []:
        track = _coerce_track(raw)
        if track is None or track["sc_id"] in seen:
            continue
        seen.add(track["sc_id"])
        out.append(track)
    return out


# ── Classification ────────────────────────────────────────────────────────────


def is_playable(track: Mapping[str, Any]) -> bool:
    """Legally and technically streamable in full.

    ``access`` is the public API's snipped gate: ``playable`` = full, ``preview`` =
    snippet, ``blocked`` = metadata only. A preview must never enter the missing list —
    queueing it would download a snippet and call it the track.
    """
    return (
        track.get("access") == "playable"
        and bool(track.get("streamable"))
        and track.get("sharing") == "public"
    )


def mix_exclusion_reason(track: Mapping[str, Any]) -> str | None:
    """Why this belongs in the collapsed "Mixes & sets" bucket, or ``None``.

    Owner rule, in order: not fully playable, or longer than 15 minutes, or a keyword
    hit on title/tags/genre. ``downloadable`` is a ranking badge and is never consulted.
    """
    if not is_playable(track):
        return "unavailable"
    try:
        duration_ms = int(track.get("duration_ms") or 0)
    except (TypeError, ValueError):
        duration_ms = 0
    if duration_ms > LONG_FORM_MS:
        return "long_form"
    haystack = " ".join(str(track.get(key) or "") for key in ("title", "tag_list", "genre"))
    if _MIX_KEYWORDS.search(haystack):
        return "keyword"
    return None


def names_the_artist(track: Mapping[str, Any], folded_names: Sequence[str]) -> bool:
    """Is the artist named in the title, the tags or the uploading account's name?

    A display-name hit is evidence of a *credit*, never of ownership — an account can
    call itself anything. It only ever sorts the remix list; identity stays on the URN.
    """
    if not folded_names:
        return False
    haystack = (
        f" {_fold(str(track.get('title') or ''))} "
        f"{_fold(str(track.get('tag_list') or ''))} "
        f"{_fold(str(track.get('uploader_name') or ''))} "
    )
    return any(name and f" {name} " in haystack for name in folded_names)


def classify(
    tracks: Iterable[Any],
    artist_urn: str,
    *,
    artist_names: Sequence[str] = (),
) -> Classification:
    """Split a fetched catalogue into the owner's three buckets.

    ``definitely_theirs`` is decided by ``uploader_urn == artist_urn`` and by nothing
    else — never by a name match (threat T11). It is the only bucket a batch download
    may ever auto-queue.

    Everything uploaded by another account lands in ``remixes_by_others``, tagged
    ``credited`` when ``artist_names`` (canonical name + aliases) is actually found in
    the title, tags or uploader name. Uncredited rows are ranked lower by the UI, not
    hidden: this is a reposts-path listing, and dropping it would be the silent loss the
    mix filter was explicitly designed to avoid.

    The mix/set gate runs first, so a 40-minute set from the artist's own account is a
    set, not a missing track.
    """
    own_urn = normalize_user_urn(artist_urn)
    folded_names = [n for n in (_fold(name) for name in artist_names) if n]
    result = Classification()

    for track in coerce_tracks(tracks):
        is_own = bool(own_urn) and normalize_user_urn(track["uploader_urn"]) == own_urn
        entry = {
            **track,
            "credited": True if is_own else names_the_artist(track, folded_names),
            "excluded_reason": None,
        }
        reason = mix_exclusion_reason(track)
        if reason is not None:
            result.mixes_and_sets.append(
                {**entry, "bucket": BUCKET_MIXES, "excluded_reason": reason}
            )
        elif is_own:
            result.definitely_theirs.append({**entry, "bucket": BUCKET_THEIRS})
        else:
            result.remixes_by_others.append({**entry, "bucket": BUCKET_REMIXES})

    return result


# ── Local-library index + diff ────────────────────────────────────────────────


@dataclass(frozen=True)
class _LocalEntry:
    track_id: str
    stem: str
    artist: str
    dkey: tuple[str, str]


class _LocalIndex:
    """Blocking index over the owned tracks.

    A full cross-product is not affordable: a 200-track profile against a 5000-track
    library is a million ``SequenceMatcher`` runs. Candidates are drawn from two cheap
    blocking keys — folded artist and the stem's first word — then filtered to the same
    derivation key before any fuzzy work happens.
    """

    __slots__ = ("by_artist", "by_isrc", "by_token", "entries")

    def __init__(self, local_tracks: Mapping[str, Any] | Iterable[Any] | None) -> None:
        self.entries: list[_LocalEntry] = []
        self.by_artist: dict[str, list[int]] = {}
        self.by_token: dict[str, list[int]] = {}
        # ISRC -> first local track id carrying it. Exact identity, consulted before
        # any title work. Indexed even for a track without a usable title.
        self.by_isrc: dict[str, str] = {}
        for track_id, track in _iter_local(local_tracks):
            isrc = normalize_isrc(track.get("ISRC") or track.get("isrc"))
            if isrc:
                self.by_isrc.setdefault(isrc, track_id)
            title = str(track.get("Title") or track.get("title") or "").strip()
            if not title:
                continue
            artist = str(track.get("Artist") or track.get("artist") or "").strip()
            dkey = derivation_key(title)
            for stem in title_stems(title, (artist,)):
                if not stem:
                    continue
                idx = len(self.entries)
                self.entries.append(_LocalEntry(track_id, stem, artist, dkey))
                self.by_artist.setdefault(_fold(artist), []).append(idx)
                self.by_token.setdefault(_first_token(stem), []).append(idx)

    def candidates(self, stems: Sequence[str], artists: Sequence[str]) -> list[_LocalEntry]:
        picked: list[int] = []
        seen: set[int] = set()
        for bucket in [self.by_artist.get(_fold(a), []) for a in artists] + [
            self.by_token.get(_first_token(s), []) for s in stems
        ]:
            for idx in bucket:
                if idx not in seen:
                    seen.add(idx)
                    picked.append(idx)
                    if len(picked) >= MAX_FUZZY_CANDIDATES:
                        return [self.entries[i] for i in picked]
        return [self.entries[i] for i in picked]


def _iter_local(
    local_tracks: Mapping[str, Any] | Iterable[Any] | None,
) -> Iterable[tuple[str, Mapping[str, Any]]]:
    """Accept ``db.tracks`` (id -> dict) or a plain sequence of track dicts."""
    if not local_tracks:
        return []
    out: list[tuple[str, Mapping[str, Any]]] = []
    if isinstance(local_tracks, Mapping):
        items: Iterable[tuple[Any, Any]] = local_tracks.items()
    else:
        items = ((None, track) for track in local_tracks)
    for key, track in items:
        if not isinstance(track, Mapping):
            continue
        track_id = str(key if key is not None else (track.get("id") or track.get("ID") or ""))
        if not track_id:
            continue
        out.append((track_id, track))
    return out


def _pair_score(remote_stem: str, remote_artist: str, entry: _LocalEntry) -> float:
    """Score one pair through the shipped matcher, so its semantics stay shared.

    ``fuzzy_match_with_score`` short-circuits to 1.0 on an exact normalised title. That
    is kept deliberately: after stem reduction and the derivation gate, an identical
    title is the strongest evidence available, and artist strings drift far more than
    titles do — which is the reason this whole feature exists.
    """
    _tid, score = fuzzy_match_with_score(
        remote_stem,
        remote_artist,
        {"c": {"Title": entry.stem, "Artist": entry.artist}},
        threshold=0.0,
    )
    return score


def match_score(
    remote_track: Mapping[str, Any],
    entry: _LocalEntry,
    *,
    artist_names: Sequence[str] = (),
    token_floor: float = TOKEN_OVERLAP_FLOOR,
) -> float:
    """Best score between one remote track and one owned track; 0.0 when gated out.

    Two gates run before any fuzzy work: the derivation key (a remix is not its
    original) and the stem token overlap (a substituted word is a different title).
    """
    if derivation_key(str(remote_track.get("title") or "")) != entry.dkey:
        return 0.0
    names = _artist_names_for(remote_track, artist_names)
    stems = title_stems(str(remote_track.get("title") or ""), names)
    best = 0.0
    for stem in stems:
        if token_overlap(stem, entry.stem) < token_floor:
            continue
        for artist in names or ("",):
            best = max(best, _pair_score(stem, artist, entry))
            if best >= 1.0:
                return best
    return best


def diff(
    local_tracks: Mapping[str, Any] | Iterable[Any] | None,
    remote_tracks: Iterable[Any],
    *,
    threshold: float = MISSING_MATCH_THRESHOLD,
    artist_names: Sequence[str] = (),
) -> Diff:
    """Which remote tracks are already owned, and which are genuinely missing.

    **ISRC first.** When the remote track and a local track both carry a usable ISRC
    and they are equal, that is the same recording by definition — ``owned``, score
    1.0, ``method="isrc"``, no title work. Only when either side lacks an ISRC does the
    title path run.

    Then two gates, in order. **Derivation** — a remix, VIP, bootleg or year-edit never
    matches the original it derives from, while ``(Original Mix)`` / ``(Extended Mix)``
    / bare are the same recording. **Fuzzy** — the shipped ``external_track_match``
    scorer over title stems + artist, at :data:`MISSING_MATCH_THRESHOLD`.
    """
    index = _LocalIndex(local_tracks)
    matches: dict[str, TrackMatch] = {}
    owned: list[str] = []
    missing: list[str] = []

    for track in coerce_tracks(remote_tracks):
        sc_id = track["sc_id"]
        isrc = track.get("isrc") or ""
        local_by_isrc = index.by_isrc.get(isrc) if isrc else None
        if local_by_isrc is not None:
            matches[sc_id] = TrackMatch(sc_id, local_by_isrc, 1.0, MATCH_ISRC)
            owned.append(sc_id)
            continue
        names = _artist_names_for(track, artist_names)
        stems = title_stems(track["title"], names)
        best_id: str | None = None
        best_score = 0.0
        for entry in index.candidates(stems, names):
            score = match_score(track, entry, artist_names=artist_names)
            if score > best_score:
                best_score, best_id = score, entry.track_id
            if best_score >= 1.0:
                break
        if best_id is not None and best_score >= threshold:
            matches[sc_id] = TrackMatch(sc_id, best_id, round(best_score, 3), MATCH_TITLE)
            owned.append(sc_id)
        else:
            matches[sc_id] = TrackMatch(sc_id, None, round(best_score, 3), MATCH_NONE)
            missing.append(sc_id)

    return Diff(matches=matches, in_library=tuple(owned), missing=tuple(missing))


# ── The tie-together ──────────────────────────────────────────────────────────

#: ``fetch(artist_urn) -> iterable of normalised SC track dicts``. Supplied by the
#: caller so the OAuth token never reaches this module.
Fetcher = Callable[[str], Iterable[Any]]


def _annotate(tracks: list[dict[str, Any]], result: Diff) -> list[dict[str, Any]]:
    """Attach each track's ownership verdict.

    A track the diff never looked at (the mixes bucket is excluded from "missing" by the
    owner's rule) gets ``in_library=None`` — "not checked" — rather than ``False``, which
    would assert something about the library that was never measured.
    """
    out: list[dict[str, Any]] = []
    for track in tracks:
        verdict = result.matches.get(track["sc_id"])
        owned = verdict.matched if verdict is not None else None
        out.append(
            {
                **track,
                "in_library": owned,
                "local_track_id": verdict.local_track_id if verdict is not None else None,
                "match_score": verdict.score if verdict is not None else None,
                "match_method": verdict.method if verdict is not None else None,
                "auto_queue_allowed": track.get("bucket") == BUCKET_THEIRS and owned is False,
            }
        )
    return out


def _cached_payload(collection_id: str, artist_urn: str, max_age_s: float) -> dict[str, Any] | None:
    payload = schema.get_catalogue_cache(collection_id, max_age_s=max_age_s)
    if not isinstance(payload, Mapping):
        return None
    if normalize_user_urn(payload.get("artist_urn")) != normalize_user_urn(artist_urn):
        return None  # rebound to a different account — the cache is about someone else
    tracks = payload.get("tracks")
    if not isinstance(tracks, list):
        return None
    return dict(payload)


def catalogue(
    collection_id: str,
    *,
    local_tracks: Mapping[str, Any] | Iterable[Any] | None = None,
    artist_urn: str | None = None,
    artist_names: Sequence[str] = (),
    fetch: Fetcher | None = None,
    max_age_s: float = CACHE_TTL_S,
    force_refresh: bool = False,
    max_tracks: int = MAX_CATALOGUE_TRACKS,
    threshold: float = MISSING_MATCH_THRESHOLD,
) -> dict[str, Any]:
    """An artist's catalogue: three buckets, each track flagged owned or missing.

    Fetching happens **on selection** and only through the caller's ``fetch`` callable —
    no speculative pre-fetch, and no credentials in this module. A fresh cache entry is
    served without calling ``fetch`` at all; a miss with no fetcher raises
    :class:`CatalogueUnavailable` rather than returning an empty catalogue that would
    read as "this artist has released nothing".

    The **fetched catalogue** is what gets cached, never the diff — the local side moves
    every time the library does.

    Returns ``definitely_theirs`` / ``remixes_by_others`` / ``mixes_and_sets`` (lists of
    annotated tracks), ``in_library`` (the ``sc_id``s found in the library),
    ``fetched_at``, ``from_cache`` and ``truncated``.

    Raises :class:`ArtistNotLinked` when no SoundCloud account is bound.
    """
    urn = artist_urn
    if not urn:
        link = schema.get_link(collection_id, PROVIDER_SOUNDCLOUD)
        urn = str(link.get("remote_id") or "") if link else ""
    if not urn:
        raise ArtistNotLinked(
            f"collection {collection_id!r} has no SoundCloud account bound; "
            "link one before fetching a catalogue"
        )

    names = tuple(str(n).strip() for n in artist_names if str(n or "").strip())
    payload = None if force_refresh else _cached_payload(collection_id, urn, max_age_s)
    from_cache = payload is not None

    if payload is None:
        if fetch is None:
            raise CatalogueUnavailable(
                f"no cached catalogue for {collection_id!r} and no SoundCloud fetcher "
                "available (not signed in?)"
            )
        raw = fetch(urn)
        # The client's own result object reports a fetch cut short by its call budget or
        # item cap. Losing that flag here would present a partial catalogue as complete.
        stop_reason = getattr(raw, "stop_reason", None)
        fetched = coerce_tracks(raw)
        truncated = bool(getattr(raw, "truncated", False)) or len(fetched) > max_tracks
        if stop_reason:
            logger.info(
                "op=artist_catalogue collection=%s fetch_stopped reason=%s",
                collection_id,
                stop_reason,
            )
        if len(fetched) > max_tracks:
            logger.warning(
                "op=artist_catalogue collection=%s capped fetched=%d cap=%d",
                collection_id,
                len(fetched),
                max_tracks,
            )
            fetched = fetched[:max_tracks]
        payload = {
            "artist_urn": normalize_user_urn(urn),
            "fetched_at": _now_iso(),
            "truncated": truncated,
            "tracks": fetched,
        }
        schema.set_catalogue_cache(collection_id, payload)

    tracks = coerce_tracks(payload.get("tracks") or [])
    split = classify(tracks, urn, artist_names=names)
    result = diff(
        local_tracks,
        split.definitely_theirs + split.remixes_by_others,
        threshold=threshold,
        artist_names=names,
    )

    theirs = _annotate(split.definitely_theirs, result)
    remixes = _annotate(split.remixes_by_others, result)
    mixes = _annotate(split.mixes_and_sets, Diff())

    logger.info(
        "op=artist_catalogue collection=%s tracks=%d theirs=%d remixes=%d mixes=%d "
        "in_library=%d cache=%s truncated=%s",
        collection_id,
        len(tracks),
        len(theirs),
        len(remixes),
        len(mixes),
        len(result.in_library),
        from_cache,
        bool(payload.get("truncated")),
    )

    return {
        BUCKET_THEIRS: theirs,
        BUCKET_REMIXES: remixes,
        BUCKET_MIXES: mixes,
        "in_library": list(result.in_library),
        "fetched_at": str(payload.get("fetched_at") or ""),
        "from_cache": from_cache,
        "truncated": bool(payload.get("truncated")),
    }


__all__ = [
    "BUCKET_MIXES",
    "BUCKET_REMIXES",
    "BUCKET_THEIRS",
    "CACHE_TTL_S",
    "LONG_FORM_MS",
    "MATCH_ISRC",
    "MATCH_NONE",
    "MATCH_TITLE",
    "MAX_CATALOGUE_TRACKS",
    "MISSING_MATCH_THRESHOLD",
    "TOKEN_OVERLAP_FLOOR",
    "ArtistNotLinked",
    "CatalogueError",
    "CatalogueUnavailable",
    "Classification",
    "Diff",
    "TrackMatch",
    "catalogue",
    "classify",
    "coerce_track",
    "coerce_tracks",
    "derivation_key",
    "diff",
    "is_playable",
    "match_score",
    "mix_exclusion_reason",
    "names_the_artist",
    "normalize_isrc",
    "normalize_user_urn",
    "title_stems",
    "token_overlap",
]
