"""artist_store.attribution — which library tracks belong to an artist, and as what.

Owner refinement 2026-09-26 ("ihnen Tracks zuschreiben"). Until now an artist's local
tracks were whatever the library's ``Artist`` string named; the ``Remixer`` column and
the ``(X Remix)`` in a title were never looked at, so a DJ's folder of remixes BY an
artist never showed up under that artist. Three layers, later ones win:

1. **Artist field** — exactly the registry's grouping: the library's own splitter (via
   ``db.get_tracks_by_artist``) over every library spelling that resolves to the
   collection. This is the set the hub has always counted and the projection always
   wrote, so nothing that was in it falls out. Inside it the role is refined with the
   T-20 vocabulary: ``featured`` when the artist only follows ``feat.``,
   ``remixed_by_other`` when the title credits someone else's remix, ``remixer`` when
   the title credits their remix and the Artist field names the original act too.
2. **Credits** — tracks whose Artist field does not name the artist but whose
   ``Remixer`` field (``remixer``, HIGH) or title does: ``(X Remix)`` / ``X Remix``
   tail (``remixer``), ``feat. X`` (``featured``), ``X - Title`` prefix (``primary``),
   all MEDIUM. Name comparison is ``merge.fold_key`` through ``identity``'s parser —
   deterministic, never edit distance, and a version word is never a person.
3. **Manual** — ``assign`` puts any library track under the artist with a role the
   user picked; ``exclude`` takes a track out whatever matched it.

One answer serves the artist page AND the Rekordbox projection (:func:`membership`), so
a playlist can never disagree with the page it mirrors. Pure apart from the sidecar
reads: no network, no ``master.db`` writes.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from app.artist_store import identity, registry, schema
from app.artist_store.merge import fold_key
from app.artist_store.schema import KIND_ARTIST

logger = logging.getLogger("ARTIST_STORE")

ROLE_ORDER = (
    schema.ROLE_PRIMARY,
    schema.ROLE_REMIXER,
    schema.ROLE_REMIXED_BY_OTHER,
    schema.ROLE_FEATURED,
)

SOURCE_ARTIST_FIELD = "artist_field"
SOURCE_REMIXER_FIELD = "remixer_field"
SOURCE_TITLE_REMIX = "title_remix"
SOURCE_TITLE_FEATURED = "title_featured"
SOURCE_TITLE_PREFIX = "title_prefix"
SOURCE_MANUAL = "manual"

ACTION_CLEAR = "clear"

DEFAULT_CANDIDATE_LIMIT = 50
MAX_CANDIDATE_LIMIT = 200


class LibraryNotLoaded(RuntimeError):
    """A write needs the loaded library to snapshot the track it names."""


class UnknownCollection(KeyError):
    """No stored collection has this id, and no name came with it that derives the id."""


class TrackNotInLibrary(LookupError):
    """The loaded library holds no track with this id."""


def track_id(track: Any) -> str | None:
    """Content id of a UI track dict. Live rows key it ``ID``, the XML backend ``id``."""
    if not isinstance(track, Mapping):
        return None
    value = track.get("ID") or track.get("id") or track.get("TrackID")
    return str(value) if value else None


@dataclass(frozen=True)
class Attribution:
    role: str
    confidence: str
    source: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {
            "role": self.role,
            "confidence": self.confidence,
            "source": self.source,
            "detail": self.detail,
        }


@dataclass
class _Scope:
    """One collection as the library sees it right now."""

    collection_id: str
    name: str
    stored: bool
    library_names: list[str]
    artist_ids: list[str]
    names: identity._Names


def _library_tracks(db: Any) -> dict[str, dict[str, Any]]:
    """``db.tracks`` re-keyed by content id; empty when no library is loaded."""
    if db is None:
        return {}
    raw = getattr(db, "tracks", None) or {}
    values = raw.values() if isinstance(raw, Mapping) else raw
    out: dict[str, dict[str, Any]] = {}
    for track in values:
        tid = track_id(track)
        if tid:
            out[tid] = track
    return out


def _scopes(db: Any, collection_ids: Iterable[str], kind: str) -> dict[str, _Scope]:
    """Scope per wanted collection from ONE store snapshot and ONE ``db.artists`` pass.

    A collection with no stored row still has a scope when library spellings resolve to
    its derived id — the hub and browse hand those ids out before anything is stored.
    """
    wanted = set(collection_ids)
    store = registry._store_index(kind)
    ids_by_name: dict[str, str] = {}
    grouped: dict[str, list[str]] = {}
    counts: dict[str, int] = {}
    for row in (getattr(db, "artists", None) or []) if db is not None else []:
        if not isinstance(row, Mapping):
            continue
        name = str(row.get("name") or "").strip()
        aid = row.get("id")
        if not name or not aid:
            continue
        cid = registry._resolve_id(name, kind, store)
        if cid not in wanted:
            continue
        ids_by_name[name] = str(aid)
        grouped.setdefault(cid, []).append(name)
        try:
            counts[name] = int(row.get("track_count") or 0)
        except (TypeError, ValueError):
            counts[name] = 0

    scopes: dict[str, _Scope] = {}
    for cid in wanted:
        collection = store.collections.get(cid)
        library_names = sorted(grouped.get(cid, []), key=lambda n: (-counts.get(n, 0), n))
        if collection is None and not library_names:
            continue
        stored_names = registry.artist_names(cid, kind) if collection is not None else ()
        spellings = list(dict.fromkeys([*stored_names, *library_names]))
        scopes[cid] = _Scope(
            collection_id=cid,
            name=str(collection["canonical_name"]) if collection is not None else library_names[0],
            stored=collection is not None,
            library_names=library_names,
            artist_ids=[ids_by_name[n] for n in library_names],
            names=identity._Names.build(spellings),
        )
    return scopes


def _credit(title: str, names: identity._Names) -> identity.CreditParse:
    credit = identity.parse_credit(title)
    identity._claim_suffix_credit(credit, names)
    return credit


def _remixer_is(credit: identity.CreditParse, names: identity._Names) -> bool:
    """Whether the title's remix credit names this artist.

    The shared parser keeps a trailing version word on the remixer — ``(Boys Noize VIP
    Remix)`` reads as remixer ``Boys Noize VIP`` — which would turn an artist's own VIP
    into "remixed by someone else". Trailing version words are peeled before comparing.
    """
    if not credit.remixer:
        return False
    if names.matches(credit.remixer):
        return True
    words = credit.remixer.split()
    while words and fold_key(words[-1]) in identity._VERSION_VOCAB:
        words.pop()
    return bool(words) and names.matches(" ".join(words))


def _artist_field_role(track: Mapping[str, Any], names: identity._Names) -> Attribution:
    """Role of a track the Artist field already gives to this artist."""
    artist = str(track.get("Artist") or "")
    main = identity._split_names(identity._strip_feat(artist))
    featured_only = not any(names.matches(n) for n in main) and any(
        names.matches(n) for n in identity._featured_names(artist)
    )
    if featured_only:
        return Attribution(
            schema.ROLE_FEATURED,
            schema.CONFIDENCE_HIGH,
            SOURCE_ARTIST_FIELD,
            "Named after feat. in the Artist field",
        )
    credit = _credit(str(track.get("Title") or ""), names)
    kind = (credit.remix_kind or "Remix").lower()
    if _remixer_is(credit, names):
        others = [n for n in main if not names.matches(n)]
        if others:
            return Attribution(
                schema.ROLE_REMIXER,
                schema.CONFIDENCE_HIGH,
                SOURCE_ARTIST_FIELD,
                f"Their {kind} of {', '.join(others)}",
            )
    elif credit.remixer:
        return Attribution(
            schema.ROLE_REMIXED_BY_OTHER,
            schema.CONFIDENCE_HIGH,
            SOURCE_ARTIST_FIELD,
            f"Their track, {kind} by {credit.remixer}",
        )
    return Attribution(
        schema.ROLE_PRIMARY, schema.CONFIDENCE_HIGH, SOURCE_ARTIST_FIELD, "Artist field names them"
    )


def _credit_role(track: Mapping[str, Any], names: identity._Names) -> Attribution | None:
    """Role of a track the Artist field does NOT give to this artist, or None."""
    remixers = str(track.get("Remixer") or "")
    if remixers and any(names.matches(n) for n in identity._split_names(remixers)):
        return Attribution(
            schema.ROLE_REMIXER,
            schema.CONFIDENCE_HIGH,
            SOURCE_REMIXER_FIELD,
            "Remixer field credits them",
        )
    title = str(track.get("Title") or "")
    if not title:
        return None
    credit = _credit(title, names)
    if _remixer_is(credit, names):
        kind = (credit.remix_kind or "Remix").lower()
        return Attribution(
            schema.ROLE_REMIXER,
            schema.CONFIDENCE_MEDIUM,
            SOURCE_TITLE_REMIX,
            f"Title credits their {kind}",
        )
    if any(names.matches(f) for f in credit.featured):
        return Attribution(
            schema.ROLE_FEATURED,
            schema.CONFIDENCE_MEDIUM,
            SOURCE_TITLE_FEATURED,
            "Title credits them as featured",
        )
    if credit.artist_prefix and any(names.matches(n) for n in credit.primary_names):
        return Attribution(
            schema.ROLE_PRIMARY,
            schema.CONFIDENCE_MEDIUM,
            SOURCE_TITLE_PREFIX,
            "Title names them before the dash",
        )
    return None


_NON_WORD = re.compile(r"[^\w]+")


def _words(text: str) -> str:
    """Folded text as space-padded words: ``Sirens (Boys Noize Remix)`` -> `` sirens boys noize remix ``.

    Brackets and dashes glue straight onto a name in a title, so a plain folded
    substring test would miss ``(boys noize`` — the credit a DJ library is full of.
    """
    return f" {_NON_WORD.sub(' ', fold_key(text)).strip()} "


def _needles(names: identity._Names) -> tuple[str, ...]:
    return tuple(w for w in (_words(k) for k in names.strict) if w.strip())


class _Folds:
    """Per-run cache of each track's title / remixer as words — built once, read per artist."""

    def __init__(self) -> None:
        self._cache: dict[str, tuple[str, str]] = {}

    def mentions(self, tid: str, track: Mapping[str, Any], needles: tuple[str, ...]) -> bool:
        """Cheap pre-filter: only a track that names a spelling gets the full parse."""
        words = self._cache.get(tid)
        if words is None:
            words = (_words(str(track.get("Title") or "")), _words(str(track.get("Remixer") or "")))
            self._cache[tid] = words
        return any(n in words[0] or n in words[1] for n in needles)


@dataclass
class _Result:
    rows: list[tuple[dict[str, Any], Attribution]]
    excluded: list[dict[str, Any]]
    assigned_missing: list[dict[str, Any]]


def _manual(row: Mapping[str, Any]) -> Attribution:
    return Attribution(
        str(row.get("role") or schema.ROLE_PRIMARY),
        schema.CONFIDENCE_HIGH,
        SOURCE_MANUAL,
        "Assigned by you",
    )


def _same_recording(row: Mapping[str, Any], track: Mapping[str, Any]) -> bool:
    """Does the id still name the track the user picked? (Threat T16)

    Content ids come back after a reload — another XML, a rebuilt ``master.db`` — on a
    different recording, and a manual row must not follow the number there. The title
    is the witness, not the artist string: a merge rewrites that on purpose. A fixer
    edit that trims the title ("Boys Noize - Starter" -> "Starter", "01 Starter")
    keeps the row, whole words either way round; an unrelated title does not.
    """
    then = fold_key(str(row.get("title") or ""))
    now = fold_key(str(track.get("Title") or ""))
    if not then or not now:
        return True
    return f" {then} " in f" {now} " or f" {now} " in f" {then} "


def _attribute(
    db: Any,
    scope: _Scope,
    tracks: Mapping[str, dict[str, Any]],
    folds: _Folds | None = None,
) -> _Result:
    found: dict[str, tuple[dict[str, Any], Attribution]] = {}
    for aid in scope.artist_ids:
        for track in db.get_tracks_by_artist(aid) or []:
            tid = track_id(track)
            if tid and tid not in found:
                found[tid] = (track, _artist_field_role(track, scope.names))
    folds = folds or _Folds()
    needles = _needles(scope.names)
    for tid, track in tracks.items():
        if tid in found or not needles or not folds.mentions(tid, track, needles):
            continue
        role = _credit_role(track, scope.names)
        if role is not None:
            found[tid] = (track, role)

    excluded: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    manual = schema.list_track_assignments(scope.collection_id) if scope.stored else []
    for row in manual:
        tid = str(row["track_id"])
        track = tracks.get(tid)
        replaced = track is not None and not _same_recording(row, track)
        if replaced:
            track = None
        if row["action"] == schema.EXCLUDE:
            if track is None:
                continue
            hit = found.pop(tid, None)
            excluded.append(
                {
                    "track_id": tid,
                    "title": track.get("Title") or row.get("title") or "",
                    "artist": track.get("Artist") or row.get("artist") or "",
                    "would_be": hit[1].as_dict() if hit else None,
                }
            )
            continue
        if track is None:
            missing.append(
                {
                    "track_id": tid,
                    "title": row.get("title") or "",
                    "artist": row.get("artist") or "",
                    "role": row.get("role"),
                    "reason": "replaced" if replaced else "gone",
                }
            )
            continue
        found[tid] = (track, _manual(row))
    return _Result(list(found.values()), excluded, missing)


def _counts(rows: Iterable[tuple[dict[str, Any], Attribution]]) -> dict[str, int]:
    counts = dict.fromkeys(ROLE_ORDER, 0)
    manual = total = 0
    for _track, attribution in rows:
        counts[attribution.role] = counts.get(attribution.role, 0) + 1
        manual += attribution.source == SOURCE_MANUAL
        total += 1
    return {**counts, "manual": manual, "total": total}


def local_tracks(db: Any, collection_id: str, kind: str = KIND_ARTIST) -> dict[str, Any] | None:
    """The artist page's local half: every attributed track with its role, in one call.

    None when neither the store nor the loaded library knows the collection. Without a
    loaded library the answer is empty and says so (``library_loaded: false``) rather
    than claiming the artist has nothing.
    """
    scope = _scopes(db, [collection_id], kind).get(collection_id)
    if scope is None:
        return None
    tracks = _library_tracks(db)
    result = _attribute(db, scope, tracks) if db is not None else _Result([], [], [])
    logger.info(
        "op=artist_local_tracks collection=%s tracks=%d excluded=%d missing=%d",
        collection_id,
        len(result.rows),
        len(result.excluded),
        len(result.assigned_missing),
    )
    return {
        "collection_id": collection_id,
        "name": scope.name,
        "stored": scope.stored,
        "library_loaded": db is not None,
        "library_names": scope.library_names,
        "tracks": [{**track, "artist_role": a.as_dict()} for track, a in result.rows],
        "counts": _counts(result.rows),
        "excluded": result.excluded,
        "assigned_missing": result.assigned_missing,
    }


def membership(
    db: Any, collection_ids: Iterable[str], kind: str = KIND_ARTIST
) -> dict[str, list[str]]:
    """``collection_id`` -> ordered local track ids, for the Rekordbox projection.

    The same three layers as :func:`local_tracks`, so a projected playlist holds
    exactly what the artist page lists — remixes included, exclusions honoured.
    """
    if db is None:
        return {}
    wanted = list(dict.fromkeys(collection_ids))
    scopes = _scopes(db, wanted, kind)
    tracks = _library_tracks(db)
    folds = _Folds()
    out: dict[str, list[str]] = {}
    for cid in wanted:
        scope = scopes.get(cid)
        if scope is None:
            continue
        rows = _attribute(db, scope, tracks, folds).rows
        ids = [tid for tid in (track_id(t) for t, _ in rows) if tid]
        if ids:
            out[cid] = ids
    return out


def _ensure_collection(collection_id: str, name: str | None, kind: str) -> None:
    """Store a derived collection the first time the user writes to it.

    The hub and browse hand out ids for artists nothing has stored yet. A manual
    assignment needs a row to hang off, so it is created here — but only from a name
    that derives exactly this id, never an arbitrary one.
    """
    if schema.get_collection(collection_id) is not None:
        return
    text = " ".join(str(name or "").split())
    if not text or schema.collection_id_for(text, kind) != collection_id:
        raise UnknownCollection(collection_id)
    cid = schema.create_collection(text, kind)
    schema.add_alias(cid, text, source=registry.ALIAS_SOURCE_LIBRARY)


def set_assignment(
    db: Any,
    collection_id: str,
    track: str,
    *,
    action: str,
    role: str | None = None,
    name: str | None = None,
    kind: str = KIND_ARTIST,
) -> dict[str, Any]:
    """Assign, exclude or clear one track for one artist; returns that track's new state.

    ``clear`` drops the manual row so the automatic layers decide again. ``assign``
    defaults to ``primary``. Raises ``UnknownCollection`` for an unknown collection (and
    no name that derives it), ``TrackNotInLibrary`` for a track the loaded library does
    not hold, ``LibraryNotLoaded`` without a library, ``ValueError`` for a bad action or
    role. The two lookups are their own types so a stray ``KeyError`` from a bug can
    never pass for "not found".
    """
    tid = str(track or "").strip()
    if not tid:
        raise ValueError("track_id must be non-empty")
    if action == ACTION_CLEAR:
        if schema.get_collection(collection_id) is None:
            raise UnknownCollection(collection_id)
        schema.clear_track_assignment(collection_id, tid)
    else:
        if action not in schema.ASSIGNMENT_ACTIONS:
            raise ValueError(
                f"unknown action {action!r}; expected assign, exclude or {ACTION_CLEAR}"
            )
        if db is None:
            raise LibraryNotLoaded("Load the library before assigning tracks.")
        library = _library_tracks(db)
        target = library.get(tid)
        if target is None:
            raise TrackNotInLibrary(tid)
        chosen = (role or schema.ROLE_PRIMARY) if action == schema.ASSIGN else None
        if chosen is not None and chosen not in schema.ASSIGNABLE_ROLES:
            raise ValueError(
                f"unknown role {chosen!r}; expected one of {sorted(schema.ASSIGNABLE_ROLES)}"
            )
        _ensure_collection(collection_id, name, kind)
        schema.set_track_assignment(
            collection_id,
            tid,
            action,
            role=chosen,
            title=str(target.get("Title") or ""),
            artist=str(target.get("Artist") or ""),
        )
    logger.info("op=artist_track_assign collection=%s action=%s", collection_id, action)

    page = local_tracks(db, collection_id, kind) or {}
    row = next((t for t in page.get("tracks", []) if track_id(t) == tid), None)
    return {
        "collection_id": collection_id,
        "track_id": tid,
        "action": action,
        "track": row,
        "counts": page.get("counts") or _counts([]),
        "excluded_count": len(page.get("excluded") or []),
    }


def search_candidates(
    db: Any,
    collection_id: str,
    query: str,
    limit: int = DEFAULT_CANDIDATE_LIMIT,
    kind: str = KIND_ARTIST,
) -> dict[str, Any] | None:
    """Library tracks matching ``query`` for "Add tracks", each flagged if already theirs.

    Case-insensitive substring over title, artist and remixer. A blank query returns
    nothing rather than the whole library — this is a search box, not a browser. None,
    like :func:`local_tracks`, when neither the store nor the library knows the id.
    """
    needle = " ".join(str(query or "").split()).casefold()
    size = max(1, min(int(limit), MAX_CANDIDATE_LIMIT))
    empty = {"collection_id": collection_id, "query": needle, "tracks": [], "total": 0}
    if not needle:
        return empty
    page = local_tracks(db, collection_id, kind)
    if page is None:
        return None
    if db is None:
        return empty
    roles = {track_id(t): t["artist_role"] for t in page.get("tracks", [])}
    excluded = {e["track_id"] for e in page.get("excluded", [])}
    folded_needle = fold_key(needle)
    hits: list[dict[str, Any]] = []
    total = 0
    for tid, track in _library_tracks(db).items():
        haystack = " ".join(
            str(track.get(field) or "") for field in ("Title", "Artist", "Remixer")
        ).casefold()
        if needle not in haystack and (
            not folded_needle or folded_needle not in fold_key(haystack)
        ):
            continue
        total += 1
        if len(hits) < size:
            hits.append(
                {
                    "id": tid,
                    "Title": track.get("Title") or "",
                    "Artist": track.get("Artist") or "",
                    "Remixer": track.get("Remixer") or "",
                    "Album": track.get("Album") or "",
                    "BPM": track.get("BPM"),
                    "Key": track.get("Key") or "",
                    "artist_role": roles.get(tid),
                    "excluded": tid in excluded,
                }
            )
    return {"collection_id": collection_id, "query": needle, "tracks": hits, "total": total}
