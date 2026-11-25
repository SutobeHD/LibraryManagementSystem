"""
phrase_db_writer.py — write phrase memory cues into Rekordbox master.db (djmdCue).

NOT WIRED: nothing in the app calls this yet. `POST /api/phrase/commit` and the
phrase batch worker still go through `phrase_generator.commit_phrase_cues`, which
patches the ANLZ files only. Wiring it means calling `write_phrase_memory_cues()`
from `commit_phrase_cues`, with one snapshot and one DB handle per batch instead
of per track. On the pinned 0.1.7 surface each call also costs one `SELECT ID`
over every cue in the library (`_new_cue_ids`) — a batch caller fetches that set
once and hands it down as `used=` instead of paying it per track.

Writing cues into the ANLZ files alone does NOT make them appear in Rekordbox's
library view — Rekordbox reads cues from the `djmdCue` table (verified: a track
can have a `djmdCue` memory cue while its ANLZ memory list is empty, i.e. the two
drift). This module writes phrase markers as MEMORY cues (`Kind=0`) via
pyrekordbox, which manages the USN / UUID bookkeeping Rekordbox's sync needs
(`DjmdCue.create` registers with the agent registry, `db.commit()` stamps
`rb_local_usn`).

Pinned-dependency reality (pyrekordbox==0.1.7): `Rekordbox6Database` has neither
`add()` nor `generate_unused_id()` — both are later additions. The helpers below
probe with `getattr` and fall back to the 0.1.7 surface, so the module works on
both. `created_at`/`updated_at` are NOT NULL with no default and `DjmdCue.create`
does not fill them, so every INSERT sets them explicitly.

Live-DB caveat: 0.1.7 refuses Rekordbox >= 6.6.5 and needs a SQLCipher DBAPI plus
the db key to open the encrypted master.db — neither is installed (adding either
is a dependency/secret decision, not this module's). Until then, pass `db_file=`
pointing at a decrypted copy.

Safety contract:
  * ALWAYS backs up the file it is about to write, before writing it — the live
    master.db, or the `db_file` copy when one is given (timestamped
    `.phrasebak-*` copies of that file + its -wal) — unless the caller already
    snapshotted (backup=False). Snapshot target and write target are the same
    path by construction, so the returned `backups` always roll back the file
    that was actually mutated.
    -shm is deliberately not copied: it is a rebuildable wal-index.
  * Snapshot and write share ONE `db_lock()` hold, so the snapshot cannot
    predate a committed write from another thread, nor be torn by one.
  * Idempotent: a re-run REPLACES this track's prior phrase cues (Kind=0 whose
    Comment matches `P<n>`) instead of duplicating. The user's manual memory
    cues (other/blank comments) and hot cues (Kind>=1) are never touched.
  * Rekordbox MUST be closed — it locks master.db. A locked DB raises
    RekordboxLockedError (no partial write; SQLite blocks the writer, it does
    not corrupt).
  * `restore_master_db` rolls back a whole backup SET (one timestamp), never a
    db from one generation beside a -wal from another: SQLite would replay the
    foreign WAL frames over the restored pages.
  * A set of `master.db` also holds `masterPlaylists6.xml` when it sits beside
    the db: rbox keeps the playlist tree in both, and a db rolled back under a
    newer XML leaves Rekordbox with playlists the db does not know.
  * `marker` names a backup family (`.phrasebak-` here, `.mergebak-` for the
    artist merge); restore and prune only ever see sets of their own family.

InFrame is derived as int(InMsec * 0.15) (150 frames/s — verified against real
djmdCue rows). Memory cues are point cues: OutMsec=-1, OutFrame=0.
"""

import logging
import random
import re
import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .database import db_lock
from .pyrekordbox_compat import quiet_import

logger = logging.getLogger(__name__)

# A phrase cue's Comment ("P1", "P2", …) doubles as the idempotency marker.
_PHRASE_COMMENT_RE = re.compile(r"^P\d+$")
# InFrame = int(InMsec * _FRAMES_PER_MS); 150 fps, verified vs real djmdCue.
_FRAMES_PER_MS = 0.15
_BAK_MARKER = ".phrasebak-"
# rbox's playlist tree beside master.db; part of every master.db snapshot set.
PLAYLIST_XML = "masterPlaylists6.xml"
# Rekordbox allocates random cue IDs; mirror that instead of max()+1.
_MAX_CUE_ID = 2**28 - 1


class RekordboxLockedError(RuntimeError):
    """master.db is locked — Rekordbox is probably running."""


def _rekordbox_running() -> bool:
    """Process check, mirroring ``app/artist_store/merge.py:_rekordbox_running``.

    An unavailable rbox means "cannot tell" — proceed, like the analysis routes.
    """
    try:
        import rbox
    except ImportError:
        return False
    try:
        return bool(rbox.is_rekordbox_running())
    except Exception as e:  # compiled extension — the raised type is not contractual
        logger.warning("phrase_db_writer: is_rekordbox_running() failed err=%s", e)
        return False


def _unique_stamp(base: Path, marker: str = _BAK_MARKER) -> str:
    """A `%Y%m%d-%H%M%S-%f` stamp no existing backup beside `base` uses.

    The stamp must stay lexicographically sortable (restore picks the newest set
    by string comparison), so it is the clock — not a random suffix. But
    `datetime.now()` ticks in ~16 ms steps on Windows/py3.11, and two snapshots
    inside one tick would otherwise get the same name and the second would
    silently overwrite the first generation. Step 1 µs forward until free.
    """
    now = datetime.now()
    while any(base.parent.glob(f"{base.name}*{marker}{now:%Y%m%d-%H%M%S-%f}")):
        now += timedelta(microseconds=1)
    return f"{now:%Y%m%d-%H%M%S-%f}"


def _snapshot_sources(db_path: str) -> list[Path]:
    """Files one snapshot set copies: the db, its -wal, and the playlist XML.

    The XML only belongs to a db named `master.db` — a decrypted copy elsewhere
    must never pull the real library's XML into its set (and restore over it).
    """
    base = Path(db_path)
    sources = [Path(db_path), Path(db_path + "-wal")]
    if base.name == "master.db":
        sources.append(base.with_name(PLAYLIST_XML))
    return sources


def backup_master_db(db_path: str, *, marker: str = _BAK_MARKER) -> list[str]:
    """Copy `db_path` (+ its -wal + `masterPlaylists6.xml`) to timestamped backups.

    Each copy is `<file><marker><stamp>` beside its original; every file of one
    call shares the stamp, which is what makes it one restorable set.
    """
    timestamp = _unique_stamp(Path(db_path), marker)
    created: list[str] = []
    for src in _snapshot_sources(db_path):
        if src.exists():
            dst = f"{src}{marker}{timestamp}"
            shutil.copy2(str(src), dst)
            created.append(dst)
    logger.info("backup_master_db: backed up %d file(s) marker=%s", len(created), marker)
    return created


def _backup_target(backup: str | Path, marker: str = _BAK_MARKER) -> Path:
    """`…/master.db-wal.phrasebak-<stamp>` → `…/master.db-wal`."""
    path = Path(backup)
    base, found, _stamp = path.name.rpartition(marker)
    if not found:
        raise ValueError(f"not a phrase backup file: {path.name}")
    return path.parent / base


def _backup_sets(db_path: str, marker: str = _BAK_MARKER) -> dict[str, list[Path]]:
    """Every `marker` backup of this db's snapshot sources, grouped by stamp."""
    names = {src.name for src in _snapshot_sources(db_path)}
    parent = Path(db_path).parent
    sets: dict[str, list[Path]] = {}
    for candidate in parent.glob(f"*{marker}*"):
        base, _found, stamp = candidate.name.rpartition(marker)
        if base in names:
            sets.setdefault(stamp, []).append(candidate)
    return sets


def _newest_backup_set(db_path: str, marker: str = _BAK_MARKER) -> list[Path]:
    """The backup files sharing the newest timestamp, or []."""
    sets = _backup_sets(db_path, marker)
    if not sets:
        return []
    return sets[max(sets)]


def prune_backup_sets(db_path: str, *, marker: str, keep: int) -> int:
    """Delete all but the newest `keep` sets of one backup family. Returns files removed.

    Callers hold `db_lock()`, the same lock a restore reads a set under.
    """
    sets = _backup_sets(db_path, marker)
    removed = 0
    for stamp in sorted(sets)[: max(0, len(sets) - max(1, keep))]:
        for member in sets[stamp]:
            try:
                member.unlink()
                removed += 1
            except OSError as e:
                logger.warning("prune_backup_sets: could not remove a backup err=%s", e.strerror)
    if removed:
        logger.info("prune_backup_sets: removed %d file(s) marker=%s", removed, marker)
    return removed


def restore_master_db(
    db_path: str, backups: list[str] | None = None, *, marker: str = _BAK_MARKER
) -> int:
    """Roll master.db back from ONE backup set (all files, one timestamp).

    `masterPlaylists6.xml` comes back with the db when the set holds it; an XML
    the set does not hold is left as it is.

    Args:
        db_path: master.db path.
        backups: exact backup files to restore. Defaults to the newest set.
        marker:  backup family (`.phrasebak-` default, `.mergebak-` for a merge).

    Returns:
        Number of files copied back (0 when there is nothing to restore).

    Raises:
        ValueError:            an entry in `backups` is not a `<marker>*` file.
        RuntimeError:          Rekordbox is running, or the set has no main-db member.
        RekordboxLockedError:  a sidecar could not be removed (file held).
    """
    if _rekordbox_running():
        raise RuntimeError("Rekordbox is running — close it before restoring master.db.")

    members = (
        [Path(b) for b in backups] if backups is not None else _newest_backup_set(db_path, marker)
    )
    if not members:
        logger.info("restore_master_db: no backup found — nothing restored")
        return 0

    targets = {_backup_target(m, marker): m for m in members}
    main = Path(db_path)
    if main not in targets:
        raise RuntimeError(f"incomplete backup set — no snapshot of {main.name}: {sorted(targets)}")

    restored = 0
    with db_lock():
        # A WAL carries no binding to its db file, so any -wal/-shm left beside
        # the restored db would be replayed over it — re-applying exactly the
        # writes this restore undoes. Remove both first, unconditionally.
        for suffix in ("-wal", "-shm"):
            sidecar = Path(db_path + suffix)
            try:
                sidecar.unlink(missing_ok=True)
            except PermissionError as exc:
                raise RekordboxLockedError(
                    f"cannot remove {sidecar.name} — close Rekordbox before restoring"
                ) from exc
        for target, src in targets.items():
            shutil.copy2(str(src), str(target))
            restored += 1
    logger.info("restore_master_db: restored %d file(s)", restored)
    return restored


def _delete_cue(db: Any, cue: Any) -> None:
    """Delete a cue row, preferring pyrekordbox's USN-aware delete."""
    if hasattr(db, "delete"):
        db.delete(cue)
    else:  # pragma: no cover - depends on pyrekordbox version
        db.session.delete(cue)


def _add_row(db: Any, row: Any) -> None:
    """Stage a new row. 0.1.7 has no `db.add`; later versions do."""
    add = getattr(db, "add", None)
    (add or db.session.add)(row)


def _new_cue_ids(db: Any, table: Any, count: int, used: set[str] | None = None) -> list[str]:
    """`count` unused DjmdCue IDs as strings (the column is VARCHAR(255)).

    Args:
        used: IDs already taken. Given one, this skips the `SELECT ID` over the
              whole cue table — a batch caller fetches it once and reuses it.
              The set is MUTATED with every ID handed out, so IDs stay disjoint
              across calls sharing it.

    Every candidate is checked against `used` before it is accepted, including
    on the `generate_unused_id` branch: that helper only knows what is already
    in the database, not what this loop already handed out.
    """
    if count <= 0:
        return []
    generate = getattr(db, "generate_unused_id", None)
    if used is None:
        if generate is not None:
            used = set()
        else:
            # Querying with a half-built row pending triggers SQLAlchemy autoflush,
            # which raises the row's own NOT NULL errors from here instead of at commit.
            with db.no_autoflush:
                used = {str(row[0]) for row in db.query(table.ID).all()}
    ids: list[str] = []
    while len(ids) < count:
        candidate = str(generate(table)) if generate else str(random.randint(1, _MAX_CUE_ID))
        if candidate not in used:
            used.add(candidate)
            ids.append(candidate)
    return ids


def _cue_row_kwargs(
    cue_id: str,
    content_id: str,
    content_uuid: str,
    mcue: dict[str, Any],
    now: datetime,
) -> dict[str, Any]:
    """Column values for one phrase memory cue row."""
    pos = int(mcue.get("time_ms", 0))
    return {
        "ID": cue_id,
        "ContentID": content_id,
        "InMsec": pos,
        "InFrame": int(pos * _FRAMES_PER_MS),
        "InMpegFrame": 0,
        "InMpegAbs": 0,
        "OutMsec": -1,
        "OutFrame": 0,
        "Kind": 0,
        "Color": -1,
        "ColorTableIndex": 0,
        "ActiveLoop": 0,
        "Comment": str(mcue.get("name", "") or ""),
        "BeatLoopSize": 0,
        "CueMicrosec": 0,
        "ContentUUID": content_uuid,
        "UUID": str(uuid.uuid4()),
        # NOT NULL, no default, and DjmdCue.create does not fill them. Local
        # time, like Rekordbox's own rows.
        "created_at": now,
        "updated_at": now,
    }


def write_phrase_memory_cues(
    content_id: int | str,
    memory_cues: list[dict[str, Any]],
    db_path: str,
    *,
    backup: bool = True,
    db_file: str | None = None,
) -> dict[str, Any]:
    """
    Write phrase memory cues (Kind=0) into djmdCue for one track.

    Args:
        content_id:  Rekordbox track ID.
        memory_cues: anlz-format cue dicts ({"time_ms": int, "name": str, ...}).
        db_path:     master.db path — the DB opened when `db_file` is None.
        backup:      Snapshot the written file first (default True). The
                     snapshot always targets `db_file or db_path`, i.e. the file
                     this call mutates.
        db_file:     Open (and snapshot) this DB instead (a decrypted copy —
                     opened with `unlock=False`).

    Returns:
        {"written": int, "removed": int, "backups": [paths]}.

    Raises:
        ValueError:           `content_id` is not in the library, or has no UUID.
        RekordboxLockedError: master.db is locked (close Rekordbox).
    """
    # Bare `import pyrekordbox` calls logging.basicConfig() and drops the root
    # logger to NOTSET — see app/pyrekordbox_compat.py.
    with quiet_import():
        from pyrekordbox import Rekordbox6Database
        from pyrekordbox.db6.tables import DjmdCue

    cid = str(content_id)
    # Snapshotting anything but the file the write lands in produces a useless
    # backup and a rollback that re-applies the change it is meant to undo.
    target = db_file or db_path
    backups: list[str] = []

    with db_lock():
        db = None
        try:
            # Both branches open `target` — the snapshotted file — and differ
            # only in the SQLCipher unlock a decrypted copy must skip.
            db = (
                Rekordbox6Database(path=target, unlock=False)
                if db_file
                else Rekordbox6Database(path=target)
            )

            # Before the delete pass and before the snapshot: a bad ID must not
            # destroy existing cues, nor litter backup copies for a no-op call.
            content = db.get_content(ID=cid)
            if content is None:
                raise ValueError(f"content_id={cid} not found in master.db")
            content_uuid = getattr(content, "UUID", None)
            if not content_uuid:
                raise ValueError(f"content_id={cid} has no UUID — refusing to write orphan cues")

            backups = backup_master_db(target) if backup else []

            # Idempotency: drop this track's prior phrase cues only.
            removed = 0
            for cue in list(db.get_cue(ContentID=cid)):
                if cue.Kind == 0 and cue.Comment and _PHRASE_COMMENT_RE.match(cue.Comment):
                    _delete_cue(db, cue)
                    removed += 1

            now = datetime.now()
            ids = _new_cue_ids(db, DjmdCue, len(memory_cues))
            written = 0
            for cue_id, mcue in zip(ids, memory_cues, strict=True):
                _add_row(
                    db, DjmdCue.create(**_cue_row_kwargs(cue_id, cid, content_uuid, mcue, now))
                )
                written += 1

            db.commit()
            logger.info(
                "write_phrase_memory_cues: track=%s removed=%d written=%d", cid, removed, written
            )
            return {"written": written, "removed": removed, "backups": backups}

        except Exception as exc:
            if backups:
                logger.error(
                    "write_phrase_memory_cues failed after snapshot — roll back with "
                    "restore_master_db(%r); backups=%s",
                    target,
                    backups,
                )
            lowered = str(exc).lower()
            if any(k in lowered for k in ("locked", "readonly", "read-only")):
                raise RekordboxLockedError(
                    "master.db is locked — close Rekordbox before writing cues"
                ) from exc
            raise
        finally:
            if db is not None and hasattr(db, "close"):
                db.close()
