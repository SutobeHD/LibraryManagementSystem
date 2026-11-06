"""artist_store.merge — duplicate-artist detection, preview, apply and revert (T-5/T-6).

The Original Idea's own words: *"es kann ja einfach zu mehrfachen künstlern vom
gleichen durch kleinschreibung kommen"*. One artist, several spellings, several rows
in the browse column. This module finds those groups, costs the merge, performs it and
takes it back.

:func:`candidates`, :func:`preview` and :func:`preview_many` write NOTHING — not
``master.db``, not the audio files, not the ``artists.db`` sidecar. :func:`apply` and
:func:`revert` are the only mutating entry points, and both journal every row into the
metadata-fixer undo log under one ``run_id``.

**Deterministic folds only, never fuzzy matching.** A false merge repoints tracks onto
the wrong artist and, once the variant rows are gone, the groups cannot be told apart
again — edit distance would trade a reversible annoyance for an unpickable one. So
:func:`fold_key` folds exactly what a human obviously typed differently:

  * case (``BOYS NOIZE`` / ``boys noize``),
  * leading, trailing and repeated whitespace (``Boys  Noize``),
  * ``.`` ``-`` ``_`` and the unicode dashes -> a space (``Mr. Oizo`` / ``Mr-Oizo``),
  * apostrophes, ASCII and smart, deleted (``Guns N' Roses`` / ``Guns N Roses``),
  * ``&`` -> ``and`` (``Simon & Garfunkel`` / ``Simon and Garfunkel``).

Anything else — an initialism (``M.A.N.D.Y.`` vs ``MANDY``), a typo, a missing word —
stays a separate group on purpose. Missing a group costs a click; merging two real
artists costs data.

Four entry points:

  * :func:`candidates` — every library artist name that folds together with another,
    per-variant counts, a suggested canonical spelling, group total, biggest first.
  * :func:`preview` — what an apply would do to one group: tracks repointed, files
    re-tagged, orphan rows left behind, and which USB folders would merge.
  * :func:`apply` — repoint the tracks with ``update_content`` (never
    ``update_content_artist``, which leaves ``rb_local_usn`` stale), re-reading each
    row inside ``db_lock()`` because ``update_content`` writes the WHOLE row.
  * :func:`revert` — replay one run's journal in reverse, restoring ``artist_id`` and
    the file tag; a partial replay reports itself as partial.

USB impact matters because the artist name is baked into the export layout
(``app/usb_one_library.py:_dest_audio_path`` -> ``<usb>/Contents/<Artist>/<Title>/``)
and into ``app/usb_manager.py:_track_hash``, so a merge makes every touched track dirty
in the USB diff. Byte sizes come from the **local source files** (the only ones we can
stat without a stick plugged in) and the field names say so.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.artist_store import registry
from app.artist_store.schema import KIND_ARTIST
from app.metadata_fixer import schema as fixer_log

logger = logging.getLogger("ARTIST_STORE")

#: Bump when :func:`fold_key` changes — group ids are derived from its output, so a
#: fold change re-keys every group and any stored group id goes stale.
FOLD_VERSION = 1

#: USB export root segment, per ``app/usb_one_library.py:_dest_audio_path``.
USB_CONTENTS_DIR = "Contents"

#: Tracks repointed under one ``db_lock()`` hold. Budget: <= 400 ms per chunk.
CHUNK_SIZE = 200

#: ``verify_bytes=None`` resolves to True at or below this many tracks, False above.
#: Whole-file SHA-1 is byte-identity PROOF, not a revert requirement: at ~63 MiB per
#: AIFF a 5000-track run would read ~630 GiB for a merge that rewrites one tag frame.
VERIFY_BYTES_MAX_TRACKS = 250

#: ``runs.note`` marker so a merge run is recognisable in the shared undo log.
MERGE_RUN_KIND = "artist_merge"

#: ``mutations.entity_kind`` for a track repoint. Deliberately NOT ``content``:
#: the generic ``metadata_fixer.applier`` reverts a ``content`` row by feeding
#: ``{field: before_value}`` to ``update_tracks_metadata``, and that path answers True
#: for an unrecognised key — a merge reverted through it would report success and
#: change nothing. A foreign kind makes it refuse instead. :func:`revert` owns these.
ENTITY_MERGE_CONTENT = "artist_content"

#: ``mutations.field`` values. ``artist_id`` (not the name) is what restores the link.
FIELD_ARTIST_ID = "artist_id"
FIELD_ARTIST_ROW = "artist_row"

#: Tag key handed to ``audio_tags.write_tags``. Explicit allowlist because
#: ``update_track_metadata`` answers True for an unknown key — ``"ArtistName"`` is a
#: silent no-op there, and the same typo must not reach a tag write unnoticed.
TAG_FIELD_ARTIST = "Artist"
_ALLOWED_TAG_FIELDS = frozenset({TAG_FIELD_ARTIST})

SKIP_TAG_WRITE_FAILED = "tag_write_failed"
SKIP_NO_LOCAL_FILE = "no_local_file"
ABORT_REKORDBOX_RUNNING = "rekordbox_running"

_WS_RUN = re.compile(r"\s+")
_AMPERSAND = re.compile(r"\s*&\s*")

# Apostrophes are deleted, not spaced: they sit inside a word ("O'Connor", "N'"), so a
# space would split it and stop the variant folding onto its apostrophe-less twin.
# Escaped, not literal: the glyphs are indistinguishable in most editors and ruff's
# ambiguous-character rule flags them.
_APOSTROPHES = "'\u2018\u2019\u201b\u02bc\u2032`\u00b4"
# These do separate words in practice ("Mr.Oizo", "Boys-Noize"), so they become a space
# and the whitespace collapse below does the rest.
_SEPARATORS = ".-_\u2010\u2011\u2012\u2013\u2014\u2015"

_FOLD_TABLE: dict[int, str | None] = {ord(c): None for c in _APOSTROPHES}
_FOLD_TABLE.update({ord(c): " " for c in _SEPARATORS})

_SEGMENT_FALLBACK_BAD = '<>:"/\\|?*'

_segment_fn: Any = None


class MergeError(RuntimeError):
    """Base for every refusal that stops a merge before it writes."""


class MergeUnavailable(MergeError):
    """The library backend cannot repoint artists (XML mode, rbox absent) — HTTP 400."""


class RekordboxRunningError(MergeError):
    """Rekordbox holds the library — writing now races it — HTTP 409."""


# --------------------------------------------------------- side-effect indirections
#
# Lazily imported and reached through one-line wrappers so importing this module does
# not pull the heavy ``app.database`` -> rbox chain, and so a test can replace the
# lock, the tag write and the hash independently.


def _db_lock() -> AbstractContextManager[None]:
    """The global ``master.db`` write lock (RLock — the facade re-enters it safely)."""
    from app.database import db_lock

    return db_lock()


def _write_tags(path: str, updates: Mapping[str, Any]) -> bool:
    """Mirror an artist rename into the audio file. Never raises; False = not written."""
    from app import audio_tags

    return bool(audio_tags.write_tags(path, dict(updates)))


def _read_tag_artist(path: str | None) -> str | None:
    """The file's current artist tag, or None when it cannot be read."""
    if not path:
        return None
    from app import audio_tags

    value = audio_tags.read_tags(path).get("artist")
    return None if value is None else str(value)


def _file_sha1(path: str | None) -> str | None:
    """SHA-1 of the whole file — byte-identity proof only, never a revert requirement."""
    if not path:
        return None
    p = Path(path)
    if not p.is_file():
        return None
    h = hashlib.sha1()  # integrity marker, not a security primitive
    try:
        with p.open("rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
    except OSError as e:
        logger.warning("artist merge: sha1 read failed for %s (%s)", path, e)
        return None
    return h.hexdigest()


def _rekordbox_running() -> bool:
    """Process-name check, mirroring ``app/main.py:_is_rekordbox_running``.

    Not a lock — the user can open Rekordbox one instruction later, which is why the
    run re-checks before every chunk. An unavailable rbox means "cannot tell"; the run
    proceeds, exactly as the analysis routes do.
    """
    try:
        import rbox
    except ImportError:
        return False
    try:
        return bool(rbox.is_rekordbox_running())
    except Exception as e:  # compiled extension — the raised type is not contractual
        logger.warning("artist merge: is_rekordbox_running() failed err=%s", e)
        return False


def _guard_rekordbox() -> None:
    if _rekordbox_running():
        raise RekordboxRunningError("Rekordbox is running. Close it before merging artists.")


# --------------------------------------------------------------------------- folding


def fold_key(name: str) -> str:
    """Deterministic grouping key for an artist name. Equal keys == merge candidates.

    NFKC first so compatibility forms (fullwidth letters, ligatures, non-breaking
    space) do not hide an otherwise identical spelling. Empty for a name that folds
    away entirely (``"-"``, ``"'"``) — callers must treat that as "not groupable"
    rather than as a group of junk.
    """
    text = unicodedata.normalize("NFKC", str(name or ""))
    text = _AMPERSAND.sub(" and ", text)
    text = text.translate(_FOLD_TABLE)
    return _WS_RUN.sub(" ", text).strip().casefold()


def group_id_for(key: str, kind: str = KIND_ARTIST) -> str:
    """Stable id for a fold group. Derived, so it survives a library reload."""
    digest = hashlib.sha256(f"{kind}\x00{FOLD_VERSION}\x00{key}".encode()).hexdigest()[:12]
    return f"g_{digest}"


def _is_mixed_case(name: str) -> bool:
    """True for a name that is neither all-lower nor all-upper — i.e. spelled, not typed."""
    return name != name.lower() and name != name.upper()


def _variant_order(name: str, track_count: int) -> tuple[int, int, str, str]:
    """Canonical-suggestion ranking: most tracks, then properly cased, then alphabetical."""
    return (-track_count, 0 if _is_mixed_case(name) else 1, name.casefold(), name)


def suggest_canonical(counts: Mapping[str, int]) -> str:
    """Best-spelled variant of a group: most tracks, ties to mixed case, then A-Z."""
    if not counts:
        raise ValueError("cannot suggest a canonical name for an empty group")
    return min(counts, key=lambda name: _variant_order(name, counts[name]))


# --------------------------------------------------------------------------- library


def _library_counts(db: Any) -> dict[str, int]:
    """``artist name -> owned track count`` from the loaded library.

    Reuses the registry's reader instead of re-deriving it: it already tolerates a
    missing/hostile ``db.artists``, and a second implementation would drift from the
    one the hub and the backlog count with.
    """
    counts: dict[str, int] = {}
    for row in registry._library_artists(db):
        counts[row["name"]] = counts.get(row["name"], 0) + row["track_count"]
    return counts


def _artist_ids(db: Any) -> dict[str, str]:
    """``artist name -> art_{i}``, valid only for this library load.

    ``art_{i}`` is a position in a list rebuilt on every load, so it is never stored —
    it is used here and thrown away, purely to reach ``get_tracks_by_artist``.
    """
    out: dict[str, str] = {}
    for row in getattr(db, "artists", None) or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        aid = row.get("id")
        if name and aid:
            out[name] = str(aid)
    return out


def _track_key(track: Mapping[str, Any]) -> str:
    """Identity used to de-duplicate tracks across variants of one group.

    A track can sit under two variants at once (``Artist`` = ``"boys noize & Boys
    Noize"``), so the affected set must be distinct or the preview double-counts.
    """
    tid = track.get("ID") or track.get("id")
    return str(tid) if tid else f"_anon:{id(track)}"


def _variant_tracks(db: Any, name: str, ids: Mapping[str, str]) -> list[dict[str, Any]] | None:
    """Tracks credited to one library artist name, or None when the db cannot say."""
    aid = ids.get(name)
    getter = getattr(db, "get_tracks_by_artist", None)
    if aid is None or getter is None:
        return None
    try:
        rows = getter(aid)
    except (AttributeError, TypeError, KeyError, ValueError) as e:
        logger.warning("artist merge: get_tracks_by_artist(%s) failed err=%s", aid, e)
        return None
    return [r for r in rows or [] if isinstance(r, dict)]


def _file_size(path: str | None) -> int | None:
    """Size of a local audio file, or None when it is absent, streaming or unreadable."""
    if not path:
        return None
    try:
        p = Path(path)
        if not p.is_file():
            return None
        return p.stat().st_size
    except (OSError, ValueError) as e:
        logger.debug("artist merge: cannot stat %s (%s)", path, e)
        return None


# --------------------------------------------------------------------------- USB layout


def _usb_segment(name: str) -> str:
    """Folder segment the USB exporter builds for an artist name.

    Imported lazily from the exporter so the rule cannot drift; ``usb_one_library``
    is a heavy module and merge previews run from a hot route. The fallback mirrors
    ``OneLibraryUsbWriter._safe_segment`` for an environment where that import fails.
    """
    global _segment_fn
    if _segment_fn is None:
        try:
            from app.usb_one_library import OneLibraryUsbWriter

            _segment_fn = OneLibraryUsbWriter._safe_segment
        except (ImportError, AttributeError) as e:  # pragma: no cover - import guard
            logger.warning("artist merge: USB segment rule unavailable (%s); using fallback", e)
            _segment_fn = _usb_segment_fallback
    return str(_segment_fn(name))


def _usb_segment_fallback(name: str) -> str:  # pragma: no cover - import guard
    out = "".join(c if c not in _SEGMENT_FALLBACK_BAD else "_" for c in str(name)).strip()
    return out[:80] or "Unknown"


def _usb_folder(name: str) -> str:
    return f"{USB_CONTENTS_DIR}/{_usb_segment(name)}"


# --------------------------------------------------------------------------- results


@dataclass(frozen=True)
class MergeVariant:
    """One spelling of an artist as the library currently holds it."""

    name: str
    track_count: int

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "tracks": self.track_count}


@dataclass(frozen=True)
class MergeCandidate:
    """A group of library names that fold onto one key — i.e. one artist, spelled N ways.

    ``total_tracks`` sums the per-variant counts: detection never enumerates tracks, so
    one track credited to two variants of the group counts twice. :func:`preview`
    resolves the exact figure.
    """

    group_id: str
    key: str
    kind: str
    variants: tuple[MergeVariant, ...]
    suggested_canonical: str
    total_tracks: int

    def names(self) -> list[str]:
        return [v.name for v in self.variants]

    def as_dict(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "key": self.key,
            "kind": self.kind,
            "variants": [v.as_dict() for v in self.variants],
            "suggested_canonical": self.suggested_canonical,
            "total_tracks": self.total_tracks,
        }


@dataclass(frozen=True)
class UsbFolderImpact:
    """One ``Contents/<Artist>`` folder the merge would collapse into the canonical one."""

    artist_name: str
    folder: str
    target_folder: str
    tracks: int
    bytes_local_source: int
    files_unmeasured: int
    case_only_rename: bool
    compound_artist: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "artist_name": self.artist_name,
            "folder": self.folder,
            "target_folder": self.target_folder,
            "tracks": self.tracks,
            "bytes_local_source": self.bytes_local_source,
            "files_unmeasured": self.files_unmeasured,
            "case_only_rename": self.case_only_rename,
            "compound_artist": self.compound_artist,
        }


@dataclass(frozen=True)
class UsbImpact:
    """What the next USB export would have to reshuffle after this merge.

    ``bytes_local_source`` is the size of the **local** files, summed per folder — the
    stick may hold transcoded copies, and it may not even be plugged in. It is the
    honest upper bound the dialog can quote, not a measurement of the stick.
    """

    canonical_folder: str
    folders_to_merge: tuple[UsbFolderImpact, ...]
    tracks_relocated: int
    tracks_already_in_place: int
    bytes_local_source: int
    files_unmeasured: int
    case_only_renames: int
    segment_rule: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "canonical_folder": self.canonical_folder,
            "folders_to_merge": [f.as_dict() for f in self.folders_to_merge],
            "tracks_relocated": self.tracks_relocated,
            "tracks_already_in_place": self.tracks_already_in_place,
            "bytes_local_source": self.bytes_local_source,
            "files_unmeasured": self.files_unmeasured,
            "case_only_renames": self.case_only_renames,
            "segment_rule": self.segment_rule,
        }


@dataclass(frozen=True)
class MergePreview:
    """Everything an apply would touch, computed without touching any of it.

    ``counts_exact`` is False when the library could not be asked for the actual track
    rows (no ``get_tracks_by_artist``, or a name with no live id): the numbers then fall
    back to the per-variant counts, which double-count a track credited to two variants
    of the same group. File and USB figures are empty in that case rather than guessed,
    and ``files_measured`` says so.

    ``orphans_after`` counts absorbed variants that still own tracks — i.e. the artist
    entries left empty by the merge. It is the library's artist list, which is split and
    normalised (``_split_artists``), so a variant is not guaranteed to be exactly one
    ``DjmdArtist`` row; deleting those rows is opt-in in the apply anyway.

    ``compound_artist_tracks`` are affected tracks whose artist row names more than this
    group (``"boys noize, Objekt"``). Repointing them to the canonical artist flattens
    the credit — the dialog has to say so before the user confirms.
    """

    group_id: str
    key: str
    kind: str
    canonical: str
    canonical_in_library: bool
    variants: tuple[MergeVariant, ...]
    absorbing: tuple[MergeVariant, ...]
    total_tracks: int
    tracks_to_rewrite: int
    tracks_already_canonical: int
    counts_exact: bool
    files_to_retag: int
    files_missing: int
    files_measured: bool
    orphans_after: int
    compound_artist_tracks: int
    compound_artist_names: tuple[str, ...]
    usb: UsbImpact

    def as_dict(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "key": self.key,
            "kind": self.kind,
            "canonical": self.canonical,
            "canonical_in_library": self.canonical_in_library,
            "variants": [v.as_dict() for v in self.variants],
            "absorbing": [v.as_dict() for v in self.absorbing],
            "total_tracks": self.total_tracks,
            "tracks_to_rewrite": self.tracks_to_rewrite,
            "tracks_already_canonical": self.tracks_already_canonical,
            "counts_exact": self.counts_exact,
            "files_to_retag": self.files_to_retag,
            "files_missing": self.files_missing,
            "files_measured": self.files_measured,
            "orphans_after": self.orphans_after,
            "compound_artist_tracks": self.compound_artist_tracks,
            "compound_artist_names": list(self.compound_artist_names),
            "usb": self.usb.as_dict(),
        }


# --------------------------------------------------------------------------- detection


def candidates(db: Any, kind: str = KIND_ARTIST) -> list[MergeCandidate]:
    """Library artist names that fold onto one key, biggest group first. Pure read.

    Only groups of 2+ distinct spellings are returned — a name that folds to nothing
    (pure punctuation) is skipped rather than pooled with the other junk.
    """
    counts = _library_counts(db)
    groups: dict[str, list[str]] = defaultdict(list)
    for name in counts:
        key = fold_key(name)
        if key:
            groups[key].append(name)

    out: list[MergeCandidate] = []
    for key, names in groups.items():
        if len(names) < 2:
            continue
        ordered = sorted(names, key=lambda n: _variant_order(n, counts[n]))
        variants = tuple(MergeVariant(n, counts[n]) for n in ordered)
        out.append(
            MergeCandidate(
                group_id=group_id_for(key, kind),
                key=key,
                kind=kind,
                variants=variants,
                suggested_canonical=variants[0].name,
                total_tracks=sum(v.track_count for v in variants),
            )
        )
    out.sort(key=lambda c: (-c.total_tracks, c.key))
    logger.info("op=artist_merge_candidates groups=%d", len(out))
    return out


def _resolve_group(db: Any, group: str | Iterable[str], kind: str) -> tuple[str | None, list[str]]:
    """``(group_id, names)`` for a group id or an explicit list of names."""
    if isinstance(group, str):
        # A bare artist name is iterable, so without this guard "Boys Noize" would be
        # read character by character and silently preview a group of 11 letters.
        if not group.startswith("g_"):
            raise ValueError(f"{group!r} is not a group id; pass a list of names instead")
        for candidate in candidates(db, kind):
            if candidate.group_id == group:
                return candidate.group_id, candidate.names()
        raise KeyError(f"unknown merge group {group!r}")
    names: list[str] = []
    for raw in group:
        name = str(raw or "").strip()
        if name and name not in names:
            names.append(name)
    if not names:
        raise ValueError("a merge group needs at least one artist name")
    return None, names


@dataclass(frozen=True)
class _MergePlan:
    """What both :func:`preview` and :func:`apply` have to work out first.

    Shared so the two cannot disagree about which tracks a merge touches — a preview
    that costs one set and an apply that rewrites another is the worst failure this
    feature can have.
    """

    group_id: str
    kind: str
    canonical: str
    variants: tuple[MergeVariant, ...]
    absorbing: tuple[MergeVariant, ...]
    variant_counts: dict[str, int]
    artist_ids: dict[str, str]
    affected: dict[str, dict[str, Any]]
    counts_exact: bool


def _plan(
    db: Any,
    group_id_or_names: str | Iterable[str],
    canonical: str | None,
    kind: str,
) -> _MergePlan:
    """Resolve a group + canonical spelling to the exact set of tracks to repoint."""
    group_id, names = _resolve_group(db, group_id_or_names, kind)
    counts = _library_counts(db)
    ids = _artist_ids(db)

    variant_counts = {name: counts.get(name, 0) for name in names}
    target = str(canonical or "").strip() or suggest_canonical(variant_counts)
    if target not in variant_counts:
        variant_counts[target] = counts.get(target, 0)

    ordered = sorted(variant_counts, key=lambda n: _variant_order(n, variant_counts[n]))
    variants = tuple(MergeVariant(n, variant_counts[n]) for n in ordered)
    absorbing = tuple(v for v in variants if v.name != target)

    affected: dict[str, dict[str, Any]] = {}
    counts_exact = True
    for variant in absorbing:
        rows = _variant_tracks(db, variant.name, ids)
        if rows is None:
            # The library cannot enumerate this variant's tracks (no live artist id,
            # no get_tracks_by_artist). Its per-variant count is then the only figure
            # available, and it double-counts a track credited to two variants.
            if variant.track_count:
                counts_exact = False
            continue
        for row in rows:
            affected.setdefault(_track_key(row), row)

    return _MergePlan(
        group_id=group_id or group_id_for(fold_key(target), kind),
        kind=kind,
        canonical=target,
        variants=variants,
        absorbing=absorbing,
        variant_counts=variant_counts,
        artist_ids=ids,
        affected=affected,
        counts_exact=counts_exact,
    )


def preview(
    db: Any,
    group_id_or_names: str | Iterable[str],
    canonical: str | None = None,
    kind: str = KIND_ARTIST,
    *,
    measure_files: bool = True,
) -> MergePreview:
    """Exactly what an apply would do to one group — computed, never performed.

    ``group_id_or_names`` is a ``g_…`` id from :func:`candidates` or an explicit list of
    library names (the UI also lets the user hand-pick two artists the fold did not
    group). ``canonical`` defaults to the group's suggestion; it may be a spelling the
    library does not hold yet (re-casing is the usual reason), in which case every
    existing variant is absorbed.

    Pure: no ``master.db`` write, no tag write, no sidecar write, no network. The only
    filesystem access is ``stat`` on the local audio files for the byte estimate, and
    ``measure_files=False`` skips even that.
    """
    plan = _plan(db, group_id_or_names, canonical, kind)
    group_id = plan.group_id
    target = plan.canonical
    ids = plan.artist_ids
    variant_counts = plan.variant_counts
    variants = plan.variants
    absorbing = plan.absorbing
    affected = plan.affected
    counts_exact = plan.counts_exact

    canonical_rows = _variant_tracks(db, target, ids)
    if canonical_rows is None:
        tracks_already_canonical = variant_counts.get(target, 0)
    else:
        canonical_keys = {_track_key(r) for r in canonical_rows}
        tracks_already_canonical = len(canonical_keys - set(affected))

    if counts_exact:
        tracks_to_rewrite = len(affected)
        total_tracks = tracks_to_rewrite + tracks_already_canonical
    else:
        tracks_to_rewrite = sum(v.track_count for v in absorbing)
        total_tracks = sum(v.track_count for v in variants)

    variant_names = {v.name for v in variants}
    files_to_retag = 0
    files_missing = 0
    compound: dict[str, int] = defaultdict(int)
    folders: dict[str, dict[str, Any]] = {}
    target_folder = _usb_folder(target)
    target_segment = _usb_segment(target)

    for row in affected.values():
        size = _file_size(row.get("path")) if measure_files else None
        if size is None:
            files_missing += 1
        else:
            files_to_retag += 1

        artist_name = str(row.get("Artist") or row.get("artist") or "").strip()
        is_compound = bool(artist_name) and artist_name not in variant_names
        if is_compound:
            compound[artist_name] += 1
        folder_key = artist_name or target
        entry = folders.get(folder_key)
        if entry is None:
            segment = _usb_segment(folder_key)
            entry = {
                "artist_name": folder_key,
                "folder": f"{USB_CONTENTS_DIR}/{segment}",
                "segment": segment,
                "tracks": 0,
                "bytes": 0,
                "unmeasured": 0,
                "compound": is_compound,
            }
            folders[folder_key] = entry
        entry["tracks"] += 1
        if size is None:
            entry["unmeasured"] += 1
        else:
            entry["bytes"] += size

    to_merge: list[UsbFolderImpact] = []
    already_in_place = 0
    for entry in sorted(folders.values(), key=lambda e: (-int(e["tracks"]), str(e["folder"]))):
        if entry["segment"] == target_segment:
            already_in_place += int(entry["tracks"])
            continue
        to_merge.append(
            UsbFolderImpact(
                artist_name=str(entry["artist_name"]),
                folder=str(entry["folder"]),
                target_folder=target_folder,
                tracks=int(entry["tracks"]),
                bytes_local_source=int(entry["bytes"]),
                files_unmeasured=int(entry["unmeasured"]),
                # Same folder under a case-insensitive comparison: exFAT/NTFS cannot
                # rename it directly, the exporter needs the two-step temp rename.
                case_only_rename=str(entry["segment"]).casefold() == target_segment.casefold(),
                compound_artist=bool(entry["compound"]),
            )
        )

    usb = UsbImpact(
        canonical_folder=target_folder,
        folders_to_merge=tuple(to_merge),
        tracks_relocated=sum(f.tracks for f in to_merge),
        tracks_already_in_place=already_in_place,
        bytes_local_source=sum(f.bytes_local_source for f in to_merge),
        files_unmeasured=sum(f.files_unmeasured for f in to_merge),
        case_only_renames=sum(1 for f in to_merge if f.case_only_rename),
        segment_rule="usb_one_library.OneLibraryUsbWriter._safe_segment",
    )

    result = MergePreview(
        group_id=group_id,
        key=fold_key(target),
        kind=kind,
        canonical=target,
        canonical_in_library=variant_counts.get(target, 0) > 0,
        variants=variants,
        absorbing=absorbing,
        total_tracks=total_tracks,
        tracks_to_rewrite=tracks_to_rewrite,
        tracks_already_canonical=tracks_already_canonical,
        counts_exact=counts_exact,
        files_to_retag=files_to_retag if measure_files else 0,
        files_missing=files_missing if measure_files else 0,
        # Not just the opt-out: a library that cannot enumerate its tracks yields file
        # and USB figures covering only part of the group, so they are not "measured".
        files_measured=measure_files and counts_exact,
        orphans_after=sum(1 for v in absorbing if v.track_count > 0),
        compound_artist_tracks=sum(compound.values()),
        compound_artist_names=tuple(sorted(compound)),
        usb=usb,
    )
    logger.info(
        "op=artist_merge_preview group=%s canonical=%s tracks=%d folders=%d exact=%s",
        result.group_id,
        result.canonical,
        result.tracks_to_rewrite,
        len(usb.folders_to_merge),
        result.counts_exact,
    )
    return result


def preview_many(
    db: Any,
    groups: Sequence[str | Iterable[str]],
    kind: str = KIND_ARTIST,
) -> list[MergePreview]:
    """Preview several groups in one pass (the merge screen's "select all"). Pure.

    Detection runs once here: calling :func:`preview` per group id would re-scan the
    whole library for each one.
    """
    by_id = {c.group_id: c.names() for c in candidates(db, kind)}
    out: list[MergePreview] = []
    for group in groups:
        if isinstance(group, str):
            names = by_id.get(group)
            if names is None:
                raise KeyError(f"unknown merge group {group!r}")
        else:
            names = list(group)
        out.append(preview(db, names, None, kind))
    return out


# --------------------------------------------------------------------------- apply

#: Stated in every apply payload that deleted an orphan, and in the revert payload.
ORPHAN_WARNING = (
    "Deleting an artist entry also clears Remixer, Original-Artist, Composer and "
    "Lyricist on every row that still references it, leaves no tombstone, and leaves "
    "those rows' change counter stale. A revert re-creates the artist under a NEW id "
    "and cannot restore those links."
)


def _content_id(track: Mapping[str, Any]) -> str | None:
    """Rekordbox content id of a UI track dict, or None when it carries none."""
    value = track.get("ID") or track.get("id") or track.get("TrackID")
    return str(value) if value else None


def _row_id(row: Any) -> str | None:
    """Primary key of an rbox row object or of a dict shaped like one."""
    if row is None:
        return None
    if isinstance(row, Mapping):
        value = row.get("id") or row.get("ID")
    else:
        value = getattr(row, "id", None) or getattr(row, "ID", None)
    return str(value) if value else None


def _attr_str(item: Any, name: str) -> str | None:
    """One attribute of an rbox row as a string, or None when it is unset."""
    value = getattr(item, name, None)
    return str(value) if value not in (None, "") else None


def _chunks(rows: Sequence[Any], size: int) -> Iterator[list[Any]]:
    for start in range(0, len(rows), size):
        yield list(rows[start : start + size])


def _tag_updates(name: str) -> dict[str, str]:
    """The one tag field a merge may write, checked against the allowlist.

    ``update_track_metadata`` answers True for a field key it does not recognise, so
    ``"ArtistName"`` is a silent no-op there. Nothing in this module may reach a write
    with a field the allowlist does not name.
    """
    updates = {TAG_FIELD_ARTIST: name}
    unknown = set(updates) - _ALLOWED_TAG_FIELDS
    if unknown:
        raise MergeError(f"refusing to write unlisted tag field(s): {sorted(unknown)}")
    return updates


def _require_writers(db: Any) -> None:
    """Refuse before the first write when the backend cannot repoint an artist."""
    missing = [
        name
        for name in ("get_content_by_id", "update_content", "get_artist_by_name", "create_artist")
        if not callable(getattr(db, name, None))
    ]
    if missing:
        raise MergeUnavailable(
            "this library backend cannot repoint artists (missing "
            f"{', '.join(missing)}) — switch to live Rekordbox mode"
        )


def _pre_image(track: Mapping[str, Any], *, want_tag: bool, want_sha1: bool) -> dict[str, Any]:
    """Everything about a track that must be known BEFORE the lock is taken.

    Reading the file's tag and hashing its bytes are the two slow steps; doing them
    here keeps ``db_lock()`` held for the database work only.
    """
    src = str(track.get("path") or "") or None
    return {
        "content_id": _content_id(track),
        "path": src,
        "artist_name": str(track.get("Artist") or track.get("artist") or "") or None,
        "tag_artist": _read_tag_artist(src) if (want_tag and src) else None,
        "sha1": _file_sha1(src) if (want_sha1 and src) else None,
    }


@dataclass(frozen=True)
class SkippedFile:
    """An audio file the run could not write. Reported, never half-written."""

    content_id: str
    path: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {"content_id": self.content_id, "path": self.path, "reason": self.reason}


@dataclass(frozen=True)
class MergeApplyResult:
    """What one merge run actually did — including where it stopped.

    ``tracks_rewritten`` counts ``master.db`` rows repointed and journalled;
    ``files_retagged`` counts audio files whose artist tag was rewritten. They differ
    whenever a file is locked, missing or in a format ``audio_tags`` cannot write —
    those land in ``files_skipped`` and the run continues.

    ``tracks_already_canonical`` counts rows the run **read and left alone** because
    they already pointed at the canonical artist. It is not the preview's field of the
    same name: an apply never reads the canonical variant's own tracks, so this only
    ever covers rows reached through an absorbed spelling.
    """

    run_id: str
    group_id: str
    key: str
    kind: str
    canonical: str
    canonical_artist_id: str
    tracks_total: int
    tracks_rewritten: int
    tracks_already_canonical: int
    tracks_failed: int
    chunks: int
    write_tags: bool
    verify_bytes: bool
    files_retagged: int
    files_skipped: tuple[SkippedFile, ...]
    files_verified_changed: int
    files_verified_unchanged: int
    delete_orphans: bool
    orphans_deleted: tuple[str, ...]
    orphans_skipped: tuple[dict[str, str], ...]
    aborted: bool
    abort_reason: str
    elapsed_s: float

    @property
    def revertable(self) -> bool:
        return bool(self.tracks_rewritten or self.orphans_deleted)

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "group_id": self.group_id,
            "key": self.key,
            "kind": self.kind,
            "canonical": self.canonical,
            "canonical_artist_id": self.canonical_artist_id,
            "tracks_total": self.tracks_total,
            "tracks_rewritten": self.tracks_rewritten,
            "tracks_already_canonical": self.tracks_already_canonical,
            "tracks_failed": self.tracks_failed,
            "chunks": self.chunks,
            "write_tags": self.write_tags,
            "verify_bytes": self.verify_bytes,
            "files_retagged": self.files_retagged,
            "files_skipped": [f.as_dict() for f in self.files_skipped],
            "files_verified_changed": self.files_verified_changed,
            "files_verified_unchanged": self.files_verified_unchanged,
            "delete_orphans": self.delete_orphans,
            "orphans_deleted": list(self.orphans_deleted),
            "orphans_skipped": [dict(o) for o in self.orphans_skipped],
            "orphan_warning": ORPHAN_WARNING if self.orphans_deleted else "",
            "aborted": self.aborted,
            "abort_reason": self.abort_reason,
            "revertable": self.revertable,
            "elapsed_s": round(self.elapsed_s, 3),
        }


@dataclass(frozen=True)
class MergeRevertResult:
    """What a replay of one merge run restored — and what it could not.

    ``complete`` is False whenever anything was left behind: a failed row, a file the
    tag could not be written back into, or a run stopped mid-way by Rekordbox opening.
    """

    run_id: str
    tracks_restored: int
    tracks_failed: int
    artists_restored: int
    artists_failed: int
    artist_id_remap: tuple[dict[str, str], ...]
    files_restored: int
    files_skipped: tuple[SkippedFile, ...]
    aborted: bool
    abort_reason: str
    complete: bool
    elapsed_s: float

    @property
    def orphan_links_not_restored(self) -> bool:
        return bool(self.artists_restored)

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "tracks_restored": self.tracks_restored,
            "tracks_failed": self.tracks_failed,
            "artists_restored": self.artists_restored,
            "artists_failed": self.artists_failed,
            "artist_id_remap": [dict(r) for r in self.artist_id_remap],
            "files_restored": self.files_restored,
            "files_skipped": [f.as_dict() for f in self.files_skipped],
            "aborted": self.aborted,
            "abort_reason": self.abort_reason,
            "complete": self.complete,
            "orphan_links_not_restored": self.orphan_links_not_restored,
            "orphan_warning": ORPHAN_WARNING if self.artists_restored else "",
            "elapsed_s": round(self.elapsed_s, 3),
        }


def _resolve_canonical_artist(db: Any, name: str) -> str:
    """Id of the canonical ``DjmdArtist`` row, created once if it does not exist yet.

    Resolved ONCE per run and reused for every track: ``get_artist_by_name`` is an
    exact, case-sensitive lookup, so re-resolving per track would be N pointless reads
    and would let a half-written row split the merge across two artist entries.
    """
    row = db.get_artist_by_name(name)
    if row is None:
        _guard_rekordbox()
        with _db_lock():
            row = db.create_artist(name)
    artist_id = _row_id(row)
    if artist_id is None:
        raise MergeUnavailable(f"could not resolve or create the artist row for {name!r}")
    return artist_id


def _delete_orphans(
    db: Any,
    plan: _MergePlan,
    run_id: str,
    moved_off: Mapping[str, int],
    canonical_artist_id: str,
) -> tuple[tuple[str, ...], tuple[dict[str, str], ...]]:
    """Hard-delete the absorbed artist rows the merge can PROVE it emptied.

    Journalled last so a reverse replay re-inserts them first, before the tracks that
    have to point back at them. Every guard here exists because ``delete_artist``
    detaches five columns and leaves no tombstone — see :data:`ORPHAN_WARNING`.
    """
    deleted: list[str] = []
    skipped: list[dict[str, str]] = []
    deleter = getattr(db, "delete_artist", None)
    getter = getattr(db, "get_artist_by_name", None)
    if not callable(deleter) or not callable(getter):
        return (), tuple(
            {"name": v.name, "reason": "backend cannot delete artist rows"} for v in plan.absorbing
        )

    for variant in plan.absorbing:
        row = getter(variant.name)
        artist_id = _row_id(row)
        if artist_id is None:
            # The library's artist list is split + normalised, so a variant is not
            # guaranteed to be one DjmdArtist row ("boys noize" may only ever appear
            # inside "boys noize, Objekt"). No exact row: nothing to delete.
            skipped.append({"name": variant.name, "reason": "no exact artist row"})
            continue
        if artist_id == canonical_artist_id:
            skipped.append({"name": variant.name, "reason": "is the canonical artist"})
            continue
        moved = int(moved_off.get(artist_id, 0))
        if moved < max(1, variant.track_count):
            skipped.append(
                {
                    "name": variant.name,
                    "reason": f"still referenced (repointed {moved} of {variant.track_count})",
                }
            )
            continue

        _guard_rekordbox()
        with _db_lock():
            fixer_log.record_mutation(
                run_id,
                None,
                None,
                FIELD_ARTIST_ROW,
                before_value=variant.name,
                after_value=None,
                before_json={"id": artist_id, "name": variant.name, "kind": plan.kind},
                after_json=None,
                entity_kind=fixer_log.ENTITY_ARTIST,
                entity_id=artist_id,
            )
            try:
                ok = bool(deleter(artist_id))
            except Exception as e:  # rbox is compiled — the raised type is not contractual
                logger.warning("artist merge: delete_artist(%s) failed err=%s", artist_id, e)
                ok = False
        if ok:
            deleted.append(variant.name)
        else:
            skipped.append({"name": variant.name, "reason": "delete_artist failed"})
    return tuple(deleted), tuple(skipped)


def apply(
    db: Any,
    group: str | Iterable[str],
    canonical: str | None = None,
    kind: str = KIND_ARTIST,
    *,
    write_tags: bool = True,
    verify_bytes: bool | None = None,
    delete_orphans: bool = False,
) -> MergeApplyResult:
    """Repoint every track of a variant group onto one canonical artist. Journalled.

    The write loop is the load-bearing part and its shape is not stylistic:

    * ``update_content(item)`` is the writer, never ``update_content_artist(id, name)``.
      The latter repoints the track but leaves the content row's ``rb_local_usn``
      stale (measured: 330569 before AND after), which is the counter Rekordbox uses
      for change tracking and cloud sync.
    * ``update_content`` writes the WHOLE row, so every row is re-read with
      ``get_content_by_id`` **inside** the same ``db_lock()`` that writes it, exactly
      one attribute is changed, and it goes straight back. A row read before the lock
      would silently clobber a concurrent BPM / key / comment / colour / rating edit.
    * The pre-image is journalled **before** the write, so a crash can only ever leave
      a revert entry for a change that did not happen (a harmless no-op restore) —
      never a change with no way back.

    ``write_tags`` mirrors the new artist into the audio file. A file that cannot be
    written — locked, read-only, missing, unsupported format — is skipped and reported
    in ``files_skipped``; it is never half-written and never silently dropped.

    ``verify_bytes`` hashes each file before and after the tag write. That is
    byte-identity *proof*, not a revert requirement: it never runs when ``write_tags``
    is False, and it defaults to on only at or below :data:`VERIFY_BYTES_MAX_TRACKS`
    tracks.

    ``delete_orphans`` is off by default. See :data:`ORPHAN_WARNING`.

    Raises :class:`RekordboxRunningError` when Rekordbox holds the library at the start
    (mirror it as HTTP 409), :class:`MergeUnavailable` when the backend cannot repoint
    artists, and ``ValueError`` for a group with nothing to absorb.
    """
    started = time.monotonic()
    _guard_rekordbox()
    _require_writers(db)
    fixer_log.init_db()

    plan = _plan(db, group, canonical, kind)
    if not plan.absorbing:
        raise ValueError(f"nothing to merge into {plan.canonical!r} — the group has one spelling")

    rows = list(plan.affected.values())
    total = len(rows)
    verify = bool(write_tags) and (
        total <= VERIFY_BYTES_MAX_TRACKS if verify_bytes is None else bool(verify_bytes)
    )
    canonical_artist_id = _resolve_canonical_artist(db, plan.canonical)

    run_id = fixer_log.create_run(
        [],
        note=json.dumps(
            {
                "kind": MERGE_RUN_KIND,
                "group_id": plan.group_id,
                "collection_kind": plan.kind,
                "canonical": plan.canonical,
                "canonical_artist_id": canonical_artist_id,
                "absorbing": [v.name for v in plan.absorbing],
                "tracks": total,
                "write_tags": bool(write_tags),
                "verify_bytes": verify,
                "delete_orphans": bool(delete_orphans),
            }
        ),
    )

    rewritten = already = failed = retagged = 0
    verified_changed = verified_same = chunks = 0
    skipped: list[SkippedFile] = []
    moved_off: dict[str, int] = defaultdict(int)
    aborted = False
    abort_reason = ""

    for chunk in _chunks(rows, CHUNK_SIZE):
        # Re-checked per chunk: the start-of-run guard is a process-name check, not a
        # lock, so the user can open Rekordbox one chunk in. Abort cleanly rather than
        # half-writing.
        if _rekordbox_running():
            aborted = True
            abort_reason = ABORT_REKORDBOX_RUNNING
            logger.warning("op=artist_merge run=%s aborted=rekordbox_running", run_id)
            break
        chunks += 1
        images = [_pre_image(row, want_tag=bool(write_tags), want_sha1=verify) for row in chunk]
        written: list[dict[str, Any]] = []

        with _db_lock():
            for image in images:
                cid = image["content_id"]
                if not cid:
                    failed += 1
                    continue
                try:
                    item = db.get_content_by_id(cid)
                except Exception as e:  # compiled backend — the raised type is not contractual
                    logger.warning("artist merge: get_content_by_id(%s) failed err=%s", cid, e)
                    item = None
                if item is None:
                    failed += 1
                    continue

                before_id = _attr_str(item, "artist_id")
                if before_id == canonical_artist_id:
                    already += 1
                    continue

                fixer_log.record_mutation(
                    run_id,
                    cid,
                    None,
                    FIELD_ARTIST_ID,
                    before_value=before_id,
                    after_value=canonical_artist_id,
                    before_json={
                        "content_id": cid,
                        "artist_id": before_id,
                        "artist_name": image["artist_name"],
                        "tag_artist": image["tag_artist"],
                        "path": image["path"],
                    },
                    after_json={
                        "artist_id": canonical_artist_id,
                        "artist_name": plan.canonical,
                    },
                    entity_kind=ENTITY_MERGE_CONTENT,
                    before_sha1=image["sha1"],
                    file_path=image["path"],
                )

                try:
                    item.artist_id = canonical_artist_id
                    ok = bool(db.update_content(item))
                except Exception as e:  # compiled backend — the raised type is not contractual
                    logger.warning("artist merge: update_content(%s) failed err=%s", cid, e)
                    ok = False
                if not ok:
                    failed += 1
                    continue

                rewritten += 1
                if before_id:
                    moved_off[before_id] += 1
                written.append(image)

        if not write_tags:
            continue
        # Outside the lock on purpose: a tag write is file I/O and must not extend the
        # master.db hold time. The row is already committed and journalled, so a
        # failure here is reportable, not corrupting.
        updates = _tag_updates(plan.canonical)
        for image in written:
            src = image["path"]
            cid = str(image["content_id"])
            if not src:
                skipped.append(SkippedFile(cid, "", SKIP_NO_LOCAL_FILE))
                continue
            if not _write_tags(src, updates):
                skipped.append(SkippedFile(cid, src, SKIP_TAG_WRITE_FAILED))
                continue
            retagged += 1
            if verify:
                after = _file_sha1(src)
                if image["sha1"] and after and after != image["sha1"]:
                    verified_changed += 1
                else:
                    verified_same += 1

    orphans_deleted: tuple[str, ...] = ()
    orphans_skipped: tuple[dict[str, str], ...] = ()
    if delete_orphans:
        if aborted or failed:
            orphans_skipped = tuple(
                {"name": v.name, "reason": "run did not finish cleanly"} for v in plan.absorbing
            )
        else:
            orphans_deleted, orphans_skipped = _delete_orphans(
                db, plan, run_id, moved_off, canonical_artist_id
            )

    fixer_log.set_run_status(run_id, fixer_log.RUN_FAILED if aborted else fixer_log.RUN_COMPLETED)
    elapsed = time.monotonic() - started
    logger.info(
        "op=artist_merge run=%s group=%s canonical=%s tracks=%d chunks=%d retagged=%d "
        "failed=%d orphans=%d aborted=%s elapsed=%.2f",
        run_id,
        plan.group_id,
        plan.canonical,
        rewritten,
        chunks,
        retagged,
        failed,
        len(orphans_deleted),
        aborted,
        elapsed,
    )
    return MergeApplyResult(
        run_id=run_id,
        group_id=plan.group_id,
        key=fold_key(plan.canonical),
        kind=plan.kind,
        canonical=plan.canonical,
        canonical_artist_id=canonical_artist_id,
        tracks_total=total,
        tracks_rewritten=rewritten,
        tracks_already_canonical=already,
        tracks_failed=failed,
        chunks=chunks,
        write_tags=bool(write_tags),
        verify_bytes=verify,
        files_retagged=retagged,
        files_skipped=tuple(skipped),
        files_verified_changed=verified_changed,
        files_verified_unchanged=verified_same,
        delete_orphans=bool(delete_orphans),
        orphans_deleted=orphans_deleted,
        orphans_skipped=orphans_skipped,
        aborted=aborted,
        abort_reason=abort_reason,
        elapsed_s=elapsed,
    )


# --------------------------------------------------------------------------- revert


def _merge_run_note(run: Mapping[str, Any]) -> dict[str, Any]:
    """The run's note payload, or raise if the run is not an artist merge.

    The undo log is shared with the metadata fixer. Replaying a fixer run through this
    module (or a merge run through the fixer's applier) would restore the wrong field,
    so the kind marker is checked before anything is written.
    """
    raw = run.get("note") or ""
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        payload = None
    if not isinstance(payload, dict) or payload.get("kind") != MERGE_RUN_KIND:
        raise ValueError(f"run {run.get('run_id')!r} is not an artist-merge run")
    return payload


def _restore_artist_row(db: Any, mutation: Mapping[str, Any]) -> tuple[str, str] | None:
    """Re-create a deleted artist row. Returns ``(old_id, new_id)`` or None on failure.

    rbox mints a fresh id on insert, so the row cannot come back under its original
    id — the caller remaps the tracks that pointed at the old one. The five columns
    ``delete_artist`` detached as collateral are gone for good (:data:`ORPHAN_WARNING`).
    """
    before = mutation.get("before_json")
    row: Mapping[str, Any] = before if isinstance(before, Mapping) else {}
    name = str(row.get("name") or mutation.get("before_value") or "")
    old_id = str(mutation.get("entity_id") or row.get("id") or "")
    if not name:
        logger.warning("artist merge revert: entity row %s has no name", mutation.get("entity_id"))
        return None
    try:
        existing = db.get_artist_by_name(name)
        if existing is None:
            with _db_lock():
                existing = db.create_artist(name)
    except Exception as e:  # compiled backend — the raised type is not contractual
        logger.warning("artist merge revert: re-creating artist %r failed err=%s", name, e)
        return None
    new_id = _row_id(existing)
    if new_id is None:
        return None
    return old_id, new_id


def revert(db: Any, run_id: str, *, write_tags: bool = True) -> MergeRevertResult:
    """Undo one merge run: replay its journal in reverse, restoring the artist link.

    Reverse order matters — the artist rows a run deleted are journalled last, so they
    come back first, before the tracks that have to point at them again. Because rbox
    mints a new id on insert, those tracks are repointed at the NEW id via
    ``artist_id_remap``, not at the id the journal holds.

    Restoration follows the same discipline as the apply: re-read
    ``get_content_by_id`` inside ``db_lock()``, change only ``artist_id``, write with
    ``update_content``. The file tag is restored from the journalled pre-image; a file
    that cannot be written leaves its mutation unreverted so a re-run retries it, and
    the result reports ``complete=False``.
    """
    started = time.monotonic()
    _guard_rekordbox()
    _require_writers(db)
    fixer_log.init_db()

    run = fixer_log.get_run(run_id)
    if run is None:
        raise KeyError(f"unknown merge run {run_id!r}")
    _merge_run_note(run)

    pending = [m for m in fixer_log.get_mutations(run_id, reverse=True) if not m["reverted"]]
    remap: dict[str, str] = {}
    artists_restored = artists_failed = 0
    content_rows: list[Mapping[str, Any]] = []

    for mutation in pending:
        if str(mutation.get("entity_kind") or "") != fixer_log.ENTITY_ARTIST:
            content_rows.append(mutation)
            continue
        restored = _restore_artist_row(db, mutation)
        if restored is None:
            artists_failed += 1
            continue
        old_id, new_id = restored
        if old_id and new_id != old_id:
            remap[old_id] = new_id
        fixer_log.mark_mutation_reverted(str(mutation["mutation_id"]))
        artists_restored += 1

    tracks_restored = tracks_failed = files_restored = 0
    skipped: list[SkippedFile] = []
    aborted = False
    abort_reason = ""

    for chunk in _chunks(content_rows, CHUNK_SIZE):
        if _rekordbox_running():
            aborted = True
            abort_reason = ABORT_REKORDBOX_RUNNING
            logger.warning("op=artist_merge_revert run=%s aborted=rekordbox_running", run_id)
            break
        restored_rows: list[Mapping[str, Any]] = []

        with _db_lock():
            for mutation in chunk:
                cid = str(mutation.get("content_id") or "")
                if not cid:
                    tracks_failed += 1
                    continue
                before = mutation.get("before_value")
                target_id = remap.get(str(before), before) if before else None
                try:
                    item = db.get_content_by_id(cid)
                except Exception as e:  # compiled backend — the raised type is not contractual
                    logger.warning("artist merge revert: get_content_by_id(%s) err=%s", cid, e)
                    item = None
                if item is None:
                    tracks_failed += 1
                    continue
                try:
                    item.artist_id = target_id
                    ok = bool(db.update_content(item))
                except Exception as e:  # compiled backend — the raised type is not contractual
                    logger.warning("artist merge revert: update_content(%s) err=%s", cid, e)
                    ok = False
                if not ok:
                    tracks_failed += 1
                    continue
                tracks_restored += 1
                restored_rows.append(mutation)

        for restored_row in restored_rows:
            pre = restored_row.get("before_json")
            tag_artist = pre.get("tag_artist") if isinstance(pre, Mapping) else None
            src = restored_row.get("file_path")
            cid = str(restored_row.get("content_id") or "")
            if write_tags and tag_artist is not None and src:
                if _write_tags(str(src), _tag_updates(str(tag_artist))):
                    files_restored += 1
                else:
                    # The row is back but the file still carries the merged artist.
                    # Leave the mutation unreverted so a re-run retries the file.
                    skipped.append(SkippedFile(cid, str(src), SKIP_TAG_WRITE_FAILED))
                    continue
            fixer_log.mark_mutation_reverted(str(restored_row["mutation_id"]))

    complete = not (aborted or tracks_failed or artists_failed or skipped)
    fixer_log.set_run_status(
        run_id, fixer_log.RUN_REVERTED if complete else fixer_log.RUN_REVERT_PARTIAL
    )
    elapsed = time.monotonic() - started
    logger.info(
        "op=artist_merge_revert run=%s tracks=%d failed=%d artists=%d files=%d "
        "complete=%s elapsed=%.2f",
        run_id,
        tracks_restored,
        tracks_failed,
        artists_restored,
        files_restored,
        complete,
        elapsed,
    )
    return MergeRevertResult(
        run_id=run_id,
        tracks_restored=tracks_restored,
        tracks_failed=tracks_failed,
        artists_restored=artists_restored,
        artists_failed=artists_failed,
        artist_id_remap=tuple({"old": old, "new": new} for old, new in sorted(remap.items())),
        files_restored=files_restored,
        files_skipped=tuple(skipped),
        aborted=aborted,
        abort_reason=abort_reason,
        complete=complete,
        elapsed_s=elapsed,
    )


__all__ = [
    "CHUNK_SIZE",
    "FOLD_VERSION",
    "ORPHAN_WARNING",
    "VERIFY_BYTES_MAX_TRACKS",
    "MergeApplyResult",
    "MergeCandidate",
    "MergeError",
    "MergePreview",
    "MergeRevertResult",
    "MergeUnavailable",
    "MergeVariant",
    "RekordboxRunningError",
    "SkippedFile",
    "UsbFolderImpact",
    "UsbImpact",
    "apply",
    "candidates",
    "fold_key",
    "group_id_for",
    "preview",
    "preview_many",
    "revert",
    "suggest_canonical",
]
