"""artist_store.projection — mirror favourite collections into Rekordbox (T-7).

One folder (``Artists``) at the library root, one playlist per favourite inside it,
flat. Each playlist holds that collection's local tracks including every alias
variant, so a merged artist projects as ONE playlist, not one per spelling.

Three measured facts shape everything here (Findings waves 4+5 of
``docs/research/implement/inprogress_library-artist-hub.md``, reproducible via
``scripts/dev/rbox_artist_merge_probe.py``):

* ``djmdPlaylist`` has **no** uniqueness on ``(Name, ParentID)`` or ``UUID``. Creating
  the same folder twice yields two siblings and ``get_playlist_by_path`` silently
  returns the first. So the sidecar owns the id-map: a name lookup happens exactly
  once, to adopt something that already exists, and every later run addresses the
  node by its stored id.
* ``rbox`` mints a fresh UUID per create and bumps the USN itself (+2 per node) —
  neither is a re-run key, and there is nothing for us to bump.
* ``rbox`` also maintains ``masterPlaylists6.xml`` beside ``master.db`` and **silently
  skips** that update when the file is absent (``plxml_path=None``). Playlists written
  in that state exist in the database and disappear from Rekordbox on the next
  restart, so a missing XML path refuses the run instead of half-projecting.

Diff-in-place, never delete-and-recreate: a re-sync of an unchanged artist performs
**zero** ``master.db`` writes. Every write goes through the ``RekordboxDB`` facade
(``app/database.py``) so it holds ``_db_write_lock``; ``db.active_db`` is never touched.
The sidecar keeps its own module-private lock and never takes that one.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.artist_store import registry, schema
from app.artist_store.schema import KIND_ARTIST

logger = logging.getLogger("ARTIST_STORE")

#: Root folder per collection kind. Only ``artist`` ships; the others exist so the
#: label/genre/setlist follow-up is a table row, not a rewrite (see schema docstring).
FOLDER_NAMES = {
    KIND_ARTIST: "Artists",
    "label": "Labels",
    "genre": "Genres",
    "setlist": "Setlists",
}

#: ``store_meta`` key holding the adopted-or-created root folder id, per kind.
_FOLDER_META_PREFIX = "projection_folder_id"

#: Frontend playlist-type vocabulary (``app/live_database.py:ATTR_TO_TYPE``).
_TYPE_FOLDER = "0"

SKIP_NO_LOCAL_TRACKS = "no_local_tracks"


class ProjectionError(RuntimeError):
    """Base for every refusal that stops a projection run before it writes."""


class ProjectionUnavailable(ProjectionError):
    """The library backend cannot be projected into safely (route: HTTP 400)."""


class RekordboxRunningError(ProjectionError):
    """Rekordbox holds the library — writing now races it (route: HTTP 409)."""


def folder_name_for(kind: str = KIND_ARTIST) -> str:
    """Root-folder name for a collection kind. Unknown kinds get a title-cased plural."""
    return FOLDER_NAMES.get(kind, f"{kind.title()}s")


def _folder_meta_key(kind: str) -> str:
    return f"{_FOLDER_META_PREFIX}:{kind}"


def _rekordbox_running() -> bool:
    """Process-name check, mirroring ``app/main.py:_is_rekordbox_running``.

    Not a lock — a user can still open Rekordbox one instruction later, which is why
    the run re-checks before every artist that needs a write. An unavailable rbox
    means "cannot tell"; the run proceeds, exactly as the analysis routes do.
    """
    try:
        import rbox
    except ImportError:
        return False
    try:
        return bool(rbox.is_rekordbox_running())
    except Exception as e:  # compiled extension — the raised type is not contractual
        logger.warning("artist projection: is_rekordbox_running() failed err=%s", e)
        return False


def _guard_rekordbox() -> None:
    if _rekordbox_running():
        raise RekordboxRunningError(
            "Rekordbox is running. Close it before syncing the Artists folder."
        )


def playlist_xml_path(db: Any) -> str | None:
    """Rekordbox's ``masterPlaylists6.xml`` path as the facade reports it, or None."""
    getter = getattr(db, "playlist_xml_path", None)
    if not callable(getter):
        return None
    try:
        path = getter()
    except Exception as e:  # backend-specific; never let a status read raise
        logger.warning("artist projection: playlist_xml_path() failed err=%s", e)
        return None
    return str(path) if path else None


def _require_playlist_xml(db: Any) -> str:
    """Refuse to project when rbox would silently skip the playlist-XML update.

    ``MasterDb::new(path)`` leaves ``plxml_path=None`` if ``masterPlaylists6.xml`` is
    not beside the database, and ``insert_playlist`` then discards the XML write. The
    playlists land in ``master.db`` and vanish from Rekordbox after a restart — the
    exact failure this assert exists to prevent.
    """
    getter = getattr(db, "playlist_xml_path", None)
    if not callable(getter):
        raise ProjectionUnavailable(
            "the database facade exposes no playlist_xml_path(); refusing to write "
            "playlists that Rekordbox may never see"
        )
    path = playlist_xml_path(db)
    if not path:
        raise ProjectionUnavailable(
            "Rekordbox's masterPlaylists6.xml was not found next to master.db — rbox "
            "would write playlists that Rekordbox drops on its next restart. Switch to "
            "live mode with a real Rekordbox installation before syncing."
        )
    return path


# --------------------------------------------------------------------------- helpers


def _node_id(node: Any) -> str | None:
    """Playlist id out of whatever the backend returned (dict node or ORM row)."""
    if node is None:
        return None
    if isinstance(node, dict):
        value = node.get("ID") or node.get("id")
    else:
        value = getattr(node, "ID", None) or getattr(node, "id", None)
    return str(value) if value else None


def _node_field(node: Any, *names: str) -> Any:
    for name in names:
        value = node.get(name) if isinstance(node, dict) else getattr(node, name, None)
        if value:
            return value
    return None


def _track_id(track: Any) -> str | None:
    """Track id from a UI track dict. Live rows key it ``ID``, the XML backend ``id``."""
    if not isinstance(track, dict):
        return None
    value = track.get("ID") or track.get("id") or track.get("TrackID")
    return str(value) if value else None


def _artist_track_ids(db: Any, kind: str, wanted: set[str]) -> dict[str, list[str]]:
    """``collection_id`` -> ordered local track ids, every alias variant folded in.

    Resolution reuses ``registry``'s one-pass store index deliberately: a second
    name->collection rule would drift from the one the hub and the merge use, and a
    merged artist would split back into one playlist per spelling.
    """
    store = registry._store_index(kind)
    ordered: dict[str, list[str]] = {}
    seen: dict[str, set[str]] = {}
    for row in getattr(db, "artists", None) or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        artist_id = row.get("id")
        if not name or not artist_id:
            continue
        cid = registry._resolve_id(name, kind, store)
        if cid not in wanted:
            continue
        bucket = ordered.setdefault(cid, [])
        known = seen.setdefault(cid, set())
        for track in db.get_tracks_by_artist(str(artist_id)) or []:
            tid = _track_id(track)
            if tid and tid not in known:
                known.add(tid)
                bucket.append(tid)
    return ordered


def _diff(current: list[str], desired: list[str]) -> tuple[list[str], list[str]]:
    """(to_add, to_remove). Extra copies of a wanted track count as stale.

    Removing duplicates is what makes a library that was projected by an earlier,
    buggier run self-heal: ``remove_track_from_playlist`` drops one row per call, so
    listing a track twice in ``to_remove`` deletes both surplus rows.
    """
    desired_set = set(desired)
    kept: set[str] = set()
    to_remove: list[str] = []
    for tid in current:
        if tid in desired_set and tid not in kept:
            kept.add(tid)
            continue
        to_remove.append(tid)
    to_add = [tid for tid in desired if tid not in kept]
    return to_add, to_remove


def _playlist_track_ids(db: Any, pid: str) -> list[str]:
    """Current members of a playlist, read fresh from the backend.

    Not the in-memory cache: ``add_track_to_playlist`` does not maintain it, so a
    second sync in the same process would read an empty playlist and add everything
    again — the duplicate-entry bug this whole module is shaped to avoid.
    """
    getter = getattr(db, "get_playlist_track_ids", None)
    if callable(getter):
        return [str(t) for t in getter(pid) or []]
    tracks = db.get_playlist_tracks(pid) or []
    return [tid for tid in (_track_id(t) for t in tracks) if tid]


def _new_report(kind: str, dry_run: bool) -> dict[str, Any]:
    return {
        "kind": kind,
        "dry_run": dry_run,
        "folder_name": folder_name_for(kind),
        "folder_id": None,
        "created": False,
        "adopted": False,
        "playlists_created": 0,
        "playlists_adopted": 0,
        "playlists_updated": 0,
        "tracks_added": 0,
        "tracks_removed": 0,
        "artists": 0,
        "skipped": [],
        "errors": [],
        "aborted": False,
        "elapsed_s": 0.0,
    }


# --------------------------------------------------------------------------- folder


def _resolve_folder(db: Any, kind: str, report: dict[str, Any], dry_run: bool) -> str | None:
    """Stored id first, name exactly once, create last. Returns the folder id.

    The stored id is verified every run: the user can delete or rename the folder
    inside Rekordbox at any time, and an id-map that trusted itself would then write
    playlists into a dead parent.
    """
    name = folder_name_for(kind)
    stored = schema.get_meta(_folder_meta_key(kind))
    if stored:
        node = db.get_playlist_by_id(stored)
        # Existing is not enough: djmdPlaylist reuses ids, so a deleted folder's id
        # can come back as somebody's playlist. Filing artist playlists under a
        # playlist is the failure this guard exists for.
        if node is not None and str(_node_field(node, "Type") or _TYPE_FOLDER) != _TYPE_FOLDER:
            logger.warning(
                "artist projection: stored folder id=%s now resolves to a playlist, not a "
                "folder — re-adopting by name",
                stored,
            )
            node = None
        if node is not None:
            report["folder_id"] = stored
            return stored
        logger.info(
            "op=artist_projection folder id=%s no longer usable — re-adopting by name", stored
        )

    node = db.get_playlist_by_path([name])
    if node is not None and str(_node_field(node, "Type") or _TYPE_FOLDER) != _TYPE_FOLDER:
        logger.warning(
            "artist projection: a playlist (not a folder) named %r sits at the library "
            "root — creating a separate folder rather than filing artists under it",
            name,
        )
        node = None
    if node is not None:
        folder_id = _node_id(node)
        if folder_id:
            report["adopted"] = True
            report["folder_id"] = folder_id
            if not dry_run:
                schema.set_meta(_folder_meta_key(kind), folder_id)
            return folder_id

    report["created"] = True
    if dry_run:
        return None

    _guard_rekordbox()
    created = db.create_folder(name, "ROOT")
    folder_id = _node_id(created)
    if not folder_id:
        report["created"] = False
        report["errors"].append({"scope": "folder", "name": name, "error": "create_folder failed"})
        return None
    schema.set_meta(_folder_meta_key(kind), folder_id)
    report["folder_id"] = folder_id
    return folder_id


def _children_by_name(db: Any, folder_id: str | None) -> dict[str, Any]:
    """Folded playlist name -> node, for the one re-adoption a dead id is allowed."""
    if not folder_id:
        return {}
    out: dict[str, Any] = {}
    for child in db.get_playlist_children(folder_id) or []:
        name = _node_field(child, "Name", "name")
        if not name:
            continue
        out.setdefault(schema.sort_key_for(str(name)), child)
    return out


# --------------------------------------------------------------------------- sync


def _project_one(
    db: Any,
    collection: dict[str, Any],
    desired: list[str],
    folder_id: str,
    children: dict[str, Any],
    report: dict[str, Any],
    dry_run: bool,
) -> None:
    """One favourite: verify / re-adopt / create its playlist, then diff its members."""
    cid = str(collection["id"])
    name = str(collection["canonical_name"])
    guarded = False

    def _writable() -> None:
        """Re-check Rekordbox once per artist, before that artist's first write."""
        nonlocal guarded
        if not guarded:
            _guard_rekordbox()
            guarded = True

    stored = schema.get_projection(cid)
    pid = str(stored["rb_playlist_id"]) if stored and stored["rb_playlist_id"] else None
    node = db.get_playlist_by_id(pid) if pid else None
    if pid and node is None:
        logger.info("op=artist_projection collection=%s playlist=%s gone — re-adopting", cid, pid)
    created_now = False

    if node is None:
        node = children.get(schema.sort_key_for(name))
        if node is not None:
            report["playlists_adopted"] += 1
        elif not desired:
            report["skipped"].append(
                {"collection_id": cid, "name": name, "reason": SKIP_NO_LOCAL_TRACKS}
            )
            return
        elif dry_run:
            report["playlists_created"] += 1
            report["tracks_added"] += len(desired)
            return
        else:
            _writable()
            node = db.create_playlist(name, folder_id, False)
            if _node_id(node) is None:
                report["errors"].append(
                    {"collection_id": cid, "name": name, "error": "create_playlist failed"}
                )
                return
            report["playlists_created"] += 1
            created_now = True

    pid = _node_id(node)
    if pid is None:
        report["errors"].append({"collection_id": cid, "name": name, "error": "playlist has no id"})
        return

    uuid = _node_field(node, "UUID", "uuid")
    if not dry_run:
        # Store the id-map BEFORE touching the songs: a failure half-way through the
        # diff must not leave a playlist we then re-create by name on the next run.
        schema.set_projection(cid, pid, uuid)

    current: list[str] = [] if created_now else _playlist_track_ids(db, pid)
    to_add, to_remove = _diff(current, desired)

    if dry_run:
        report["tracks_added"] += len(to_add)
        report["tracks_removed"] += len(to_remove)
        if to_add or to_remove:
            report["playlists_updated"] += 1
        return

    added = removed = 0
    failed = 0
    if to_add or to_remove:
        _writable()
        for tid in to_remove:
            if db.remove_track_from_playlist(pid, tid):
                removed += 1
            else:
                failed += 1
        for tid in to_add:
            if db.add_track_to_playlist(pid, tid):
                added += 1
            else:
                failed += 1

    report["tracks_added"] += added
    report["tracks_removed"] += removed
    if (added or removed) and not created_now:
        report["playlists_updated"] += 1
    if failed:
        report["errors"].append(
            {"collection_id": cid, "name": name, "error": f"{failed} track write(s) failed"}
        )

    schema.set_projection(cid, pid, uuid)  # refresh last_projected_at


def sync(db: Any, kind: str = KIND_ARTIST, dry_run: bool = False) -> dict[str, Any]:
    """Mirror the favourites of ``kind`` into Rekordbox. Returns a per-run report.

    Idempotent by construction: one folder and N playlists no matter how often it
    runs, and an artist whose membership already matches costs **zero** ``master.db``
    writes (the sidecar still stamps ``last_projected_at``).

    ``dry_run=True`` writes nothing at all — not to ``master.db``, not to the sidecar —
    and reports what a real run would do. A dry run is allowed while Rekordbox is
    open; a real one is not, and re-checks before every artist that needs a write so
    a user opening Rekordbox mid-run aborts the loop instead of half-projecting it.

    Report keys: ``folder_id``, ``created`` / ``adopted`` (the folder),
    ``playlists_created`` / ``playlists_adopted`` / ``playlists_updated`` (updated
    counts pre-existing playlists whose membership changed), ``tracks_added``,
    ``tracks_removed``, ``skipped`` and ``errors`` (lists of dicts), ``aborted``.

    Raises ``ProjectionUnavailable`` when the backend cannot be projected into safely
    and ``RekordboxRunningError`` when Rekordbox holds the library at run start.
    """
    started = time.monotonic()
    report = _new_report(kind, dry_run)
    _require_playlist_xml(db)
    if not dry_run:
        _guard_rekordbox()

    favourites = schema.list_favourites(kind)
    report["artists"] = len(favourites)
    if not favourites:
        report["elapsed_s"] = round(time.monotonic() - started, 3)
        return report

    wanted = {str(row["id"]) for row in favourites}
    tracks = _artist_track_ids(db, kind, wanted)

    folder_id = _resolve_folder(db, kind, report, dry_run)
    if folder_id is None and not dry_run:
        report["aborted"] = True
        report["elapsed_s"] = round(time.monotonic() - started, 3)
        return report

    children = _children_by_name(db, folder_id)

    for collection in favourites:
        cid = str(collection["id"])
        try:
            _project_one(
                db,
                collection,
                tracks.get(cid, []),
                folder_id or "",
                children,
                report,
                dry_run,
            )
        except RekordboxRunningError:
            report["aborted"] = True
            report["errors"].append(
                {
                    "collection_id": cid,
                    "name": collection["canonical_name"],
                    "error": "Rekordbox was opened during the run — aborted before writing",
                }
            )
            break
        except Exception as e:  # one bad artist must not lose the rest of the run
            logger.exception("artist projection failed for collection=%s", cid)
            report["errors"].append(
                {"collection_id": cid, "name": collection["canonical_name"], "error": str(e)}
            )

    report["elapsed_s"] = round(time.monotonic() - started, 3)
    logger.info(
        "op=artist_projection artists=%d created=%d adopted=%d playlists_created=%d "
        "playlists_updated=%d added=%d removed=%d skipped=%d errors=%d dry_run=%s elapsed=%.2f",
        report["artists"],
        int(report["created"]),
        int(report["adopted"]),
        report["playlists_created"],
        report["playlists_updated"],
        report["tracks_added"],
        report["tracks_removed"],
        len(report["skipped"]),
        len(report["errors"]),
        dry_run,
        report["elapsed_s"],
    )
    return report


# --------------------------------------------------------------------------- status


def status(db: Any = None, kind: str = KIND_ARTIST) -> dict[str, Any]:
    """Projection state for the panel. Pure read — never writes, never raises.

    ``db=None`` (library not loaded) still reports the stored id-map, so the panel
    renders before the library finishes loading. With a library it also verifies that
    every stored id still resolves, which is how a folder the user deleted inside
    Rekordbox shows up as ``exists: false`` instead of as a silent no-op next sync.
    """
    folder_id = schema.get_meta(_folder_meta_key(kind))
    folder_exists = False
    if db is not None and folder_id:
        try:
            folder_exists = db.get_playlist_by_id(folder_id) is not None
        except Exception as e:
            logger.warning("artist projection status: folder lookup failed err=%s", e)

    favourites = schema.list_favourites(kind)
    wanted = {str(row["id"]) for row in favourites}
    tracks = _artist_track_ids(db, kind, wanted) if db is not None else {}

    artists: list[dict[str, Any]] = []
    projected = 0
    for collection in favourites:
        cid = str(collection["id"])
        stored = schema.get_projection(cid)
        pid = str(stored["rb_playlist_id"]) if stored and stored["rb_playlist_id"] else None
        exists = False
        if db is not None and pid:
            try:
                exists = db.get_playlist_by_id(pid) is not None
            except Exception as e:
                logger.warning("artist projection status: playlist lookup failed err=%s", e)
        if pid and exists:
            projected += 1
        artists.append(
            {
                "collection_id": cid,
                "name": collection["canonical_name"],
                "rb_playlist_id": pid,
                "exists": exists,
                "last_projected_at": stored["last_projected_at"] if stored else None,
                "local_tracks": len(tracks.get(cid, [])),
            }
        )

    return {
        "kind": kind,
        "folder_name": folder_name_for(kind),
        "folder_id": folder_id,
        "folder_exists": folder_exists,
        "favourites": len(favourites),
        "projected": projected,
        "pending": len(favourites) - projected,
        "playlist_xml": playlist_xml_path(db) if db is not None else None,
        "rekordbox_running": _rekordbox_running(),
        "artists": artists,
    }
