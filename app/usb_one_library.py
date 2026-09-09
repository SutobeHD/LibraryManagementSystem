"""
USB OneLibrary writer — uses rbox.OneLibrary to build PIONEER/rekordbox/exportLibrary.db
that CDJ-3000 (and other modern Pioneer hardware) reads natively.

Workflow:
  1. Create empty exportLibrary.db at PIONEER/rekordbox/
  2. Iterate LibrarySource → insert artists, albums, genres, keys, labels (deduped)
  3. Insert contents (tracks) with FK references
  4. Build playlist tree (folders → playlists → playlist_contents)
  5. Copy ANLZ sidecars from .lms_anlz/<hash>/ to PIONEER/USBANLZ/<bucket>/<hash>/
  6. Copy audio files to a stable USB layout
"""

from __future__ import annotations

import contextlib
import errno
import gc
import hashlib
import logging
import os
import shutil
import time
from collections.abc import Callable, Generator, Iterable
from pathlib import Path
from typing import Any


def _copy_file_atomic(src: Path, dst: Path) -> None:
    """Copy ``src`` to ``dst`` via a ``.part`` file + rename.

    ``shutil.copy2`` straight to ``dst`` creates the destination immediately
    and fills it progressively. Interrupt it — stick pulled, disk full, user
    cancels — and a TRUNCATED file is sitting at ``dst``. The caller's
    ``if not dest_path.exists()`` guard then treats it as already-copied on
    every later sync, so the damage is permanent and silent: the CDJ plays a
    track that stops early.

    Copying to a sibling ``.part`` first means an interrupted copy leaves
    nothing at ``dst``, and the next sync copies it properly.
    """
    tmp = dst.with_name(dst.name + ".part")
    try:
        shutil.copy2(str(src), str(tmp))
        os.replace(tmp, dst)
    except OSError:
        with contextlib.suppress(OSError):
            tmp.unlink()
        raise


def _needs_copy(src: Path, dst: Path) -> bool:
    """True when ``dst`` is missing or does not match ``src``'s size.

    The size check is what heals sticks already damaged by the previous
    truncate-in-place behaviour — existence alone would keep skipping them
    forever. copy2 is a byte-exact copy, so a size mismatch means truncation.
    """
    try:
        if not dst.exists():
            return True
        return dst.stat().st_size != src.stat().st_size
    except OSError:
        return True


logger = logging.getLogger(__name__)

try:
    import rbox

    RBOX_AVAILABLE = True
except Exception as e:
    rbox = None
    RBOX_AVAILABLE = False
    logger.warning(f"rbox library unavailable: {e}")


# ---------------------------------------------------------------------------
# Relocation pass — a renamed artist must MOVE audio, not re-copy it
# ---------------------------------------------------------------------------

#: Intermediate name used by the two-step rename. Never left behind on success.
_RELOC_TMP_SUFFIX = ".lms-reloc-tmp"

#: Per-run cap on the report's `details` list, so a 10k-track stick stays cheap.
_RELOC_DETAIL_CAP = 200

#: Windows ERROR_NOT_SAME_DEVICE — the MoveFileEx twin of POSIX EXDEV.
_WIN_NOT_SAME_DEVICE = 17


def _dir_entries(path: Path) -> list[str]:
    """Real on-disk names inside `path`; empty when missing or unreadable."""
    try:
        return os.listdir(path)
    except OSError:
        return []


def _match_segment(parent: Path, wanted: str) -> tuple[str | None, list[str]]:
    """(exact name, case-insensitive matches) for `wanted` inside `parent`.

    `Path.exists()` cannot answer this: on Windows/exFAT it returns True for
    `Boys Noize` while the directory on disk is really `boys noize` — which is
    precisely the difference this pass exists to see.
    """
    names = _dir_entries(parent)
    if wanted in names:
        return wanted, []
    folded = wanted.casefold()
    return None, [n for n in names if n.casefold() == folded]


def _existing_ci(root: Path, target: Path) -> Path | None:
    """Real path under `root` matching `target`, tolerating case differences.

    An exact segment always wins, so on a case-sensitive volume holding both
    `boys noize/` and `Boys Noize/` this never crosses from one into the other.
    Ambiguity (several variants, no exact match) returns None instead of guessing.
    """
    try:
        parts = target.relative_to(root).parts
    except ValueError:
        return None
    cur = root
    for part in parts:
        exact, ci = _match_segment(cur, part)
        if exact is not None:
            cur = cur / exact
        elif len(ci) == 1:
            cur = cur / ci[0]
        else:
            return None
    return cur


def _two_step_rename(src: Path, dst: Path) -> None:
    """Rename `src` to `dst` through a temporary name.

    A case-only rename (`boys noize` -> `Boys Noize`) performed directly is
    either a no-op or a FileExistsError on Windows/exFAT, because both names
    address the same directory entry. Going through a third name is the only
    portable way to restyle a folder that already holds the files.
    """
    tmp = src.with_name(src.name + _RELOC_TMP_SUFFIX)
    n = 0
    while tmp.exists():
        n += 1
        tmp = src.with_name(f"{src.name}{_RELOC_TMP_SUFFIX}{n}")
    os.rename(src, tmp)
    try:
        os.rename(tmp, dst)
    except OSError:
        with contextlib.suppress(OSError):
            os.rename(tmp, src)
        raise


def _ensure_dirs_cased(root: Path, directory: Path) -> None:
    """Make `directory` exist under `root` with exactly the requested casing."""
    try:
        parts = directory.relative_to(root).parts
    except ValueError:
        return
    cur = root
    cur.mkdir(parents=True, exist_ok=True)
    for part in parts:
        exact, ci = _match_segment(cur, part)
        if exact is None:
            if len(ci) == 1:
                _two_step_rename(cur / ci[0], cur / part)
            else:
                (cur / part).mkdir(exist_ok=True)
        cur = cur / part


def _existing_ancestor(path: Path) -> Path:
    cur = path
    while not cur.exists() and cur != cur.parent:
        cur = cur.parent
    return cur


def _same_volume(src: Path, dst: Path) -> bool:
    """True when both paths live on one volume.

    `st_dev` carries the volume serial number on Windows too, so this is a real
    check on both platforms. Any stat failure answers False: a copy is slow, a
    half-move is unrecoverable.
    """
    try:
        return os.stat(_existing_ancestor(src)).st_dev == os.stat(_existing_ancestor(dst)).st_dev
    except OSError:
        return False


def _size_of(path: Path | None) -> int | None:
    if path is None:
        return None
    try:
        return path.stat().st_size
    except OSError:
        return None


#: Bytes hashed from each end of a file for the relocation identity check. Enough to
#: separate two different recordings that happen to share a name and a byte count —
#: audio headers and tags differ at the head, the payload tail differs at the end —
#: without reading gigabytes off a USB stick to decide one move.
_FINGERPRINT_EDGE = 64 * 1024


def _content_fingerprint(path: Path | None) -> str | None:
    """A cheap identity for an audio file: size + first and last 64 KiB.

    Relocation moves and deletes files on removable media, and the only thing it
    otherwise knows about a candidate is its name and its byte count. Those two match
    routinely on a DJ stick full of re-exported versions of the same track, so acting
    on them alone can move — or delete — a recording the user cannot get back.
    Returns ``None`` when the file cannot be read, which callers must treat as
    "not proven identical", never as a match.
    """
    if path is None:
        return None
    try:
        size = path.stat().st_size
        digest = hashlib.sha1(str(size).encode("ascii"), usedforsecurity=False)
        with path.open("rb") as handle:
            digest.update(handle.read(_FINGERPRINT_EDGE))
            if size > _FINGERPRINT_EDGE * 2:
                handle.seek(-_FINGERPRINT_EDGE, os.SEEK_END)
                digest.update(handle.read(_FINGERPRINT_EDGE))
        return digest.hexdigest()
    except OSError:
        return None


def _same_content(left: Path | None, right: Path | None) -> bool:
    """True only when both files were readable AND fingerprint identical."""
    a = _content_fingerprint(left)
    return a is not None and a == _content_fingerprint(right)


def _copy_verify(src: Path, dst: Path) -> int:
    """Copy `src` to `dst` and prove it arrived. Returns the verified size.

    Raises before the caller is allowed to delete anything, so a failed copy can
    never cost the only surviving copy of a track.
    """
    expected = src.stat().st_size
    dst.parent.mkdir(parents=True, exist_ok=True)
    _copy_file_atomic(src, dst)
    landed = _size_of(dst)
    if landed != expected:
        raise OSError(f"relocation copy unverified: {dst} is {landed} B, expected {expected} B")
    return expected


def _free_name(dest: Path) -> Path:
    """A sibling of `dest` that nothing occupies yet."""
    n = 0
    cand = dest
    while cand.exists() or _existing_ci(dest.parent, cand) is not None:
        n += 1
        cand = dest.with_name(f"{dest.stem} ({n}){dest.suffix}")
    return cand


def _prune_empty_dirs(leaf: Path, stop: Path) -> int:
    """Remove `leaf` and its parents below `stop`, but only while truly empty."""
    removed = 0
    cur = leaf
    while cur != stop and stop in cur.parents:
        if not cur.is_dir() or _dir_entries(cur):
            break
        try:
            cur.rmdir()
        except OSError:
            break
        removed += 1
        cur = cur.parent
    return removed


def _index_contents(contents: Path) -> dict[str, list[Path]]:
    """Every file already on the stick, bucketed by case-folded filename."""
    index: dict[str, list[Path]] = {}
    for dirpath, _dirnames, filenames in os.walk(contents):
        base = Path(dirpath)
        for name in filenames:
            if name.endswith(".part") or _RELOC_TMP_SUFFIX in name:
                continue
            index.setdefault(name.casefold(), []).append(base / name)
    return index


def _index_drop(index: dict[str, list[Path]], path: Path) -> None:
    bucket = index.get(path.name.casefold())
    if bucket and path in bucket:
        bucket.remove(path)


def _index_move(index: dict[str, list[Path]], old: Path, new: Path) -> None:
    _index_drop(index, old)
    index.setdefault(new.name.casefold(), []).append(new)


def _reloc_detail(report: dict[str, Any], action: str, dest: Path, **fields: str) -> None:
    details = report["details"]
    if len(details) >= _RELOC_DETAIL_CAP:
        report["details_truncated"] = True
        return
    details.append({"action": action, "dest": str(dest), **fields})


def _pick_candidate(
    index: dict[str, list[Path]],
    dest: Path,
    expected: int,
    planned_dests: set[str],
) -> Path | None:
    """The file already on the stick that `dest` should be fed from, or None.

    Three guards stop this from stealing the wrong track: identical filename,
    identical byte size, and never a path some other track in the same run is
    itself planning to occupy.
    """
    cands = [
        p
        for p in index.get(dest.name.casefold(), [])
        if p != dest and str(p).casefold() not in planned_dests and _size_of(p) == expected
    ]
    if not cands:
        return None
    same_title = dest.parent.name.casefold()
    cands.sort(key=lambda p: (p.parent.name.casefold() != same_title, str(p)))
    return cands[0]


def _relocate_one(
    contents: Path,
    src: Path | None,
    dest: Path,
    index: dict[str, list[Path]],
    planned_dests: set[str],
    touched: set[Path],
    report: dict[str, Any],
) -> None:
    if contents not in dest.parents:
        report["skipped"] += 1
        _reloc_detail(report, "outside_contents", dest)
        return

    expected = _size_of(src)
    if expected is None:
        report["skipped"] += 1
        return

    # `Path.__eq__` is case-insensitive on Windows, so every identity check below
    # compares strings — telling `boys noize` from `Boys Noize` is the whole job.
    actual = _existing_ci(contents, dest)
    if actual is not None and str(actual) != str(dest):
        # Only the casing differs — the bytes already sit where they belong.
        _ensure_dirs_cased(contents, dest.parent)
        recased = _existing_ci(contents, dest)
        if recased is not None and str(recased) != str(dest):
            _two_step_rename(recased, dest)
        if not dest.exists():
            report["errors"] += 1
            _reloc_detail(report, "case_rename_failed", dest, source=str(actual))
            return
        _index_move(index, actual, dest)
        touched.add(actual.parent)
        report["relocated"] += 1
        report["bytes_moved"] += _size_of(dest) or 0
        _reloc_detail(report, "case_rename", dest, source=str(actual))
        return

    cand = _pick_candidate(index, dest, expected, planned_dests)
    if cand is None:
        report["skipped"] += 1
        return

    # `_pick_candidate` matches on filename and byte count alone. On a stick full of
    # re-exported versions that also matches files belonging to tracks OUTSIDE this
    # sync — and moving one of those strands its PDB row while the copy phase, which
    # compares sizes, sees nothing to repair. Prove the bytes are the same recording
    # before touching it; an unreadable candidate counts as not proven.
    if not _same_content(cand, src):
        report["skipped"] += 1
        _reloc_detail(report, "candidate_content_mismatch", dest, source=str(cand))
        return

    _ensure_dirs_cased(contents, dest.parent)
    if not cand.exists():
        # A directory rename just above may have carried the candidate with it.
        recased = _existing_ci(contents, cand)
        if recased is None:
            report["errors"] += 1
            _reloc_detail(report, "source_vanished", dest, source=str(cand))
            return
        cand = recased

    origin_dir = cand.parent
    occupied = _existing_ci(contents, dest)

    if occupied is not None and str(occupied) == str(cand):
        # The directory rename above already carried the candidate here.
        if str(cand) != str(dest):
            _two_step_rename(cand, dest)
        _index_move(index, cand, dest)
        touched.add(origin_dir)
        report["relocated"] += 1
        report["bytes_moved"] += _size_of(dest) or 0
        _reloc_detail(report, "case_rename", dest, source=str(cand))
        return

    if occupied is not None:
        report["collisions"] += 1
        # Deleting from the stick needs proof, not a size match: two different
        # recordings of the same track routinely share a name and a byte count, and
        # this file may be the user's only copy. Only a fingerprint match removes it;
        # anything else falls through to keeping BOTH files.
        if _size_of(occupied) == expected and _same_content(occupied, cand):
            cand.unlink()
            _index_drop(index, cand)
            touched.add(origin_dir)
            report["duplicates_removed"] += 1
            report["skipped"] += 1
            _reloc_detail(report, "collision_identical", dest, source=str(cand))
            return
        alt = _free_name(dest)
        report["bytes_copied"] += _copy_verify(cand, alt)
        cand.unlink()
        _index_move(index, cand, alt)
        touched.add(origin_dir)
        report["copied"] += 1
        _reloc_detail(report, "collision_renamed", alt, source=str(cand), occupied=str(occupied))
        return

    if _same_volume(cand, dest.parent):
        try:
            os.replace(cand, dest)
        except OSError as exc:
            if exc.errno != errno.EXDEV and getattr(exc, "winerror", None) != _WIN_NOT_SAME_DEVICE:
                raise
        else:
            if _size_of(dest) != expected:
                report["errors"] += 1
                _reloc_detail(report, "move_unverified", dest, source=str(cand))
                return
            _index_move(index, cand, dest)
            touched.add(origin_dir)
            report["relocated"] += 1
            report["bytes_moved"] += expected
            _reloc_detail(report, "moved", dest, source=str(cand))
            return

    report["bytes_copied"] += _copy_verify(cand, dest)
    cand.unlink()
    _index_move(index, cand, dest)
    touched.add(origin_dir)
    report["copied"] += 1
    _reloc_detail(report, "copied_cross_volume", dest, source=str(cand))


def relocate_audio_files(
    usb_root: str | Path,
    planned: Iterable[tuple[Path | None, Path]],
    *,
    contents_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Move audio already on the stick to its new destination instead of re-copying it.

    An artist merge (`boys noize` + `Boys Noize` -> one artist) changes nothing
    about a track except the path it belongs at, so the copy phase would rewrite
    gigabytes that are already there. This pass runs first and settles a pure
    path change with a rename.

    `planned` is one `(local source, wanted USB destination)` pair per track; an
    entry whose source is missing locally is left to the copy phase. Nothing
    outside `contents_dir` is ever touched, and a file only becomes a candidate
    when it carries the destination's filename AND the source's exact byte size
    AND is not itself another track's planned destination.

    Report keys: `relocated`, `copied` (copy-and-verify fallback), `skipped`,
    `collisions`, `errors`, `bytes_moved`, `bytes_copied`, `duplicates_removed`,
    `pruned_dirs`, `details` (capped) and `details_truncated`.
    """
    report: dict[str, Any] = {
        "relocated": 0,
        "copied": 0,
        "skipped": 0,
        "collisions": 0,
        "errors": 0,
        "bytes_moved": 0,
        "bytes_copied": 0,
        "duplicates_removed": 0,
        "pruned_dirs": 0,
        "details": [],
        "details_truncated": False,
    }
    root = Path(usb_root)
    contents = Path(contents_dir) if contents_dir is not None else root / "Contents"
    entries = [(Path(s) if s is not None else None, Path(d)) for s, d in planned]
    if not entries or not contents.is_dir():
        report["skipped"] = len(entries)
        return report

    index = _index_contents(contents)
    if not index:
        report["skipped"] = len(entries)
        return report

    planned_dests = {str(d).casefold() for _, d in entries}
    touched: set[Path] = set()
    for src, dest in entries:
        try:
            _relocate_one(contents, src, dest, index, planned_dests, touched, report)
        except OSError as exc:
            report["errors"] += 1
            _reloc_detail(report, "error", dest, error=str(exc))
            logger.warning("[USB-relocate] %s failed: %s", dest, exc)

    for leaf in sorted(touched, key=lambda p: len(p.parts), reverse=True):
        report["pruned_dirs"] += _prune_empty_dirs(leaf, contents)

    logger.info(
        "[USB-relocate] relocated=%d copied=%d skipped=%d collisions=%d errors=%d "
        "moved=%dB copied=%dB pruned=%d dupes=%d",
        report["relocated"],
        report["copied"],
        report["skipped"],
        report["collisions"],
        report["errors"],
        report["bytes_moved"],
        report["bytes_copied"],
        report["pruned_dirs"],
        report["duplicates_removed"],
    )
    return report


class OneLibraryUsbWriter:
    """
    Writes the modern Library One DB (exportLibrary.db) plus ANLZ sidecars
    and audio files to a USB stick CDJ-3000 understands.
    """

    def __init__(
        self,
        usb_root: str,
        dest_resolver: Callable[[str, str, str], Path] | None = None,
    ):
        """
        dest_resolver(artist, album, filename) -> absolute Path on the USB.
        When provided, OneLibrary uses the SAME destination logic as the
        legacy XML writer so files are not copied twice into different
        directory trees. Falls back to an internal `_dest_audio_path` when
        no resolver is passed (older callers, tests).
        """
        if len(usb_root) == 2 and usb_root[1] == ":":
            usb_root = usb_root + "\\"
        self.usb_root = Path(usb_root)
        self.pioneer = self.usb_root / "PIONEER"
        self.rb_dir = self.pioneer / "rekordbox"
        self.anlz_root = self.pioneer / "USBANLZ"
        self.artwork_dir = self.pioneer / "Artwork"
        # Pioneer-canonical: audio at <USB>/Contents/, NOT under PIONEER/.
        # Verified against a real Rekordbox-exported stick. The actual final
        # path is determined by `dest_resolver` when one is supplied — the
        # legacy XML writer passes its own resolver so both writers land in
        # the same directory tree (no duplication).
        self.music_dir = self.usb_root / "Contents"
        self.db_path = self.rb_dir / "exportLibrary.db"
        self._dest_resolver = dest_resolver

    def ensure_structure(self):
        for d in (self.rb_dir, self.anlz_root, self.artwork_dir, self.music_dir):
            d.mkdir(parents=True, exist_ok=True)

        # Legacy export.pdb / exportExt.pdb policy:
        # * Stub disabled (default): DELETE any stale PDB left over from a
        #   previous Rekordbox-native sync. Without this Rekordbox shows an
        #   empty "Device Library" branch alongside our healthy "OneLibrary"
        #   branch — looks broken even though OneLibrary is fine.
        # * Stub enabled (`legacy_pdb_stub=true`): write the header-only
        #   stub so older CDJ firmware sees a valid (if empty) PDB. Real
        #   row encoders aren't implemented — see app/usb_pdb.py.
        try:
            from .services import SettingsManager

            stub_enabled = SettingsManager.load().get("legacy_pdb_stub", False)
        except Exception:
            stub_enabled = False

        # PDB stub policy — preserved here for the case where the row-encoder
        # path can't run yet (e.g. write_export_pdb hasn't been wired up by
        # the sync loop). The full PDB write happens later in `sync()` after
        # the OneLibrary DB has been populated, because we need the track
        # IDs the writer assigned in order to FK them from the PDB rows.
        # On `ensure_structure`, do nothing destructive — `sync()` overwrites
        # the PDBs with real data, or the stub policy below kicks in for
        # the `_legacy_pdb_stub` setting.
        self._stub_only = stub_enabled

    # Path to the bundled template DB (built by app.templates.build_template
    # from any Rekordbox-exported stick). The template ships with N
    # placeholder content rows that we mutate via update_content, working
    # around rbox 0.1.7's broken create_content path.
    TEMPLATE_DB = Path(__file__).parent / "templates" / "exportLibrary_template.db"

    def sync(
        self,
        source,
        audio_copy: bool = True,
        copy_anlz: bool = True,
        playlist_filter: list[str] | None = None,
        write_pdb: bool = True,
    ) -> Generator[dict, None, None]:
        """Main entry: yields progress events.

        TEMPLATE-BASED APPROACH (rbox 0.1.7 workaround):

        rbox 0.1.7's `OneLibrary.create()` returns a DB whose schema fails
        Diesel FK validation on every subsequent insert (verified
        empirically). Even on a real Rekordbox-created DB,
        `create_content(path)` raises "Unexpected null for non-null column".
        There is no Python-level constructor for `NewContent` so
        `insert_content` is unreachable too.

        Workaround: ship a clean template DB derived from a real Rekordbox
        export (see app/templates/build_template.py). The template contains
        N placeholder content rows. We copy it onto the USB, then mutate
        each row via `update_content` to populate user data — that path
        works fine. `create_image`, `create_artist`, `create_album` etc.
        also work, so reference tables get populated normally.

        Hard limit: the number of user tracks per OneLibrary sync is capped
        at the template's slot count (currently 16 from F: drive). Beyond
        that we skip the extras and log clearly. The legacy rekordbox.xml
        export (always written) covers the full library.

        `playlist_filter` (optional list of playlist IDs from the source):
        when set, only tracks reachable through these playlists are written,
        and the playlist tree on USB is restricted to those playlists +
        their folder ancestors. None / empty list = full library.
        """
        if not RBOX_AVAILABLE:
            yield {
                "stage": "error",
                "message": "rbox library missing — cannot write OneLibrary",
                "progress": -1,
            }
            return

        if not self.TEMPLATE_DB.exists():
            logger.warning(
                "[OneLibrary] No template DB at %s — Rekordbox auto-detect "
                "will be unavailable. Build one with: python -m "
                "app.templates.build_template <path_to_rekordbox_stick>",
                self.TEMPLATE_DB,
            )
            yield {
                "stage": "warning",
                "message": (
                    "OneLibrary template missing — Rekordbox won't auto-detect this stick. "
                    "Run `python -m app.templates.build_template <Rekordbox-exported-stick>` "
                    "once to build the template, then re-sync. Legacy XML still works for manual import."
                ),
                "progress": 100,
            }
            return

        yield {"stage": "preparing", "message": "Creating USB structure", "progress": 1}
        self.ensure_structure()

        # Stage 1 — copy template to USB (DB + WAL + SHM together)
        for ext in ("", "-shm", "-wal"):
            src = Path(str(self.TEMPLATE_DB) + ext)
            dst = Path(str(self.db_path) + ext)
            dst.unlink(missing_ok=True)
            if src.exists():
                shutil.copy2(str(src), str(dst))
        logger.info(
            "[OneLibrary] Copied template to %s (%d B)", self.db_path, self.db_path.stat().st_size
        )

        try:
            db = rbox.OneLibrary(str(self.db_path))
        except Exception as e:
            logger.error("[OneLibrary] Failed to open templated DB: %s", e, exc_info=True)
            yield {"stage": "error", "message": f"Cannot open template DB: {e}", "progress": -1}
            return

        # Set our device-unique my_tag_master_dbid so different sticks have
        # distinct Property records (CDJ behaviour expectation).
        try:
            mytag_dbid = (
                int(hashlib.sha1(str(self.usb_root).encode()).hexdigest()[:8], 16) & 0x7FFFFFFF
            )
            prop = next(iter(db.get_properties()))
            prop.my_tag_master_dbid = mytag_dbid
            try:
                db.update_property(prop)
            except Exception as exc:
                logger.debug("[OneLibrary] update_property skipped: %s", exc)
        except Exception as exc:
            logger.debug("[OneLibrary] property dbid update skipped: %s", exc)

        yield {"stage": "preparing", "message": "Reading placeholder slots…", "progress": 5}

        # Sorted by id — gives deterministic slot allocation
        placeholders = sorted(db.get_contents(), key=lambda c: c.id)
        slot_count = len(placeholders)
        logger.info("[OneLibrary] Template provides %d content slots", slot_count)

        # Reference-table caches (these CAN be created fresh — only
        # create_content is broken, the others work).
        artist_cache: dict[str, str] = {}
        album_cache: dict[str, str] = {}
        genre_cache: dict[str, str] = {}
        key_cache: dict[str, str] = {}
        label_cache: dict[str, str] = {}

        # Pre-warm caches with what's already in the template
        try:
            for a in db.get_artists():
                artist_cache.setdefault((a.name or ""), str(a.id))
            for a in db.get_albums():
                album_cache.setdefault((a.name or ""), str(a.id))
            for g in db.get_genres():
                genre_cache.setdefault((g.name or ""), str(g.id))
            for k in db.get_keys():
                key_cache.setdefault((k.name or ""), str(k.id))
            for lab in db.get_labels():
                label_cache.setdefault((lab.name or ""), str(lab.id))
        except Exception as exc:
            logger.debug("[OneLibrary] cache pre-warm skipped: %s", exc)

        content_id_map: dict[str, str] = {}
        all_tracks = list(source.iter_tracks())

        # Restrict to the playlists the user checked in the UI. Without this
        # the OneLibrary placeholder slots get overwritten with the first N
        # tracks of the entire library — playlist selection in the UI was a
        # no-op for everything except SetSticks.
        if playlist_filter:
            target_ids = set()
            for pid in playlist_filter:
                try:
                    target_ids.update(str(tid) for tid in source.get_playlist_track_ids(pid))
                except Exception as exc:
                    logger.warning(
                        "[OneLibrary] couldn't resolve playlist %s: %s",
                        pid,
                        exc,
                    )
            before = len(all_tracks)
            all_tracks = [t for t in all_tracks if str(t.get("id")) in target_ids]
            logger.info(
                "[OneLibrary] Playlist filter: %d/%d tracks kept (%d playlists)",
                len(all_tracks),
                before,
                len(playlist_filter),
            )

        total = len(all_tracks)
        used_slots = 0
        skipped_overflow = 0

        # Stage 1b — relocation. An artist rename (merge) changes only where a
        # track belongs, so move what is already on the stick before the copy
        # phase decides it is missing and rewrites gigabytes.
        if audio_copy:
            planned: list[tuple[Path | None, Path]] = []
            for t in all_tracks[:slot_count]:
                p = Path(t["path"]) if t.get("path") else None
                if p is None or not p.exists():
                    continue
                planned.append((p, self._planned_dest(t, p)))
            reloc = relocate_audio_files(self.usb_root, planned, contents_dir=self.music_dir)
            if any(reloc[k] for k in ("relocated", "copied", "collisions", "errors")):
                yield {
                    "stage": "relocate",
                    "message": (
                        f"Moved {reloc['relocated']} file(s) in place "
                        f"({reloc['copied']} copied, {reloc['collisions']} collision(s), "
                        f"{reloc['errors']} error(s))"
                    ),
                    "progress": 5,
                    "report": reloc,
                }

        # Stage 2 — populate slots via update_content (the working path)
        for i, t in enumerate(all_tracks):
            if i >= slot_count:
                skipped_overflow += 1
                continue
            try:
                slot = placeholders[i]

                # Resolve refs
                artist_id = self._get_or_create_artist(db, artist_cache, t.get("artist") or "")
                album_id = self._get_or_create_album(
                    db, album_cache, t.get("album") or "", artist_id
                )
                genre_id = self._get_or_create_genre(db, genre_cache, t.get("genre") or "")
                key_id = self._get_or_create_key(db, key_cache, t.get("key") or "")
                label_id = self._get_or_create_label(db, label_cache, t.get("label") or "")

                # Audio file copy → USB (Pioneer-canonical /Contents/<Artist>/<Title>/)
                src_path = Path(t["path"]) if t.get("path") else None
                if audio_copy and src_path and src_path.exists():
                    dest_path = self._planned_dest(t, src_path)
                    if _needs_copy(src_path, dest_path):
                        dest_path.parent.mkdir(parents=True, exist_ok=True)
                        _copy_file_atomic(src_path, dest_path)
                    usb_rel_path = "/" + str(dest_path.relative_to(self.usb_root)).replace(
                        "\\", "/"
                    )
                else:
                    usb_rel_path = ""

                # Mutate the placeholder slot with user track data
                slot.title = t.get("title") or ""
                slot.title_for_search = (t.get("title") or "").lower()
                slot.subtitle = ""
                slot.path = usb_rel_path
                slot.file_name = src_path.name if src_path else ""
                slot.dj_comment = t.get("comment") or ""
                slot.bpmx100 = int((t.get("bpm") or 0) * 100)
                slot.length = int((t.get("duration_ms") or 0) / 1000)
                slot.rating = int(t.get("rating") or 0) * 51  # 0-5 → 0-255
                slot.release_year = int(t.get("release_year") or 0)
                slot.bitrate = int(t.get("bitrate") or 0)
                slot.isrc = ""
                if artist_id is not None:
                    slot.artist_id = int(artist_id)
                if album_id is not None:
                    slot.album_id = int(album_id)
                if genre_id is not None:
                    slot.genre_id = int(genre_id)
                if key_id is not None:
                    slot.key_id = int(key_id)
                if label_id is not None:
                    slot.label_id = int(label_id)

                # Artwork — extract embedded cover, write small+medium JPEGs
                # to PIONEER/Artwork/<bucket>/, point the existing image row
                # (image_id is preserved from the placeholder slot) at the
                # small variant. Done BEFORE update_content so the FK stays
                # valid in case the user-data overlay shifts image_id.
                if src_path and src_path.exists():
                    try:
                        self._write_track_artwork(db, slot, src_path)
                    except Exception as exc:
                        logger.debug("[OneLibrary] artwork skipped for slot %s: %s", slot.id, exc)

                # ANLZ sidecars (DAT/EXT/2EX) — beatgrid + cues + waveforms.
                # Done before update_content so the analysis_data_file_path
                # field can land in the same write.
                if copy_anlz:
                    try:
                        anlz_rel = self._generate_or_copy_anlz_for(t, str(slot.id), source)
                        if anlz_rel:
                            slot.analysis_data_file_path = anlz_rel
                    except Exception as exc:
                        logger.debug("[OneLibrary] ANLZ skipped for slot %s: %s", slot.id, exc)

                db.update_content(slot)
                content_id_map[t["id"]] = str(slot.id)
                used_slots += 1

                if i % 5 == 0 or i == slot_count - 1:
                    yield {
                        "stage": "tracks",
                        "message": f"Slot {i + 1}/{slot_count}: {(t.get('title') or '?')[:40]}",
                        "progress": 5 + int(70 * (i + 1) / max(slot_count, 1)),
                    }
            except Exception as e:
                logger.warning(
                    f"[OneLibrary] Slot {i} update failed for track {t.get('id')}: {e}",
                    exc_info=False,
                )

        # Stage 3 — delete unused placeholder rows so the CDJ menu doesn't
        # show "__placeholder_X__" entries
        for unused in placeholders[used_slots:]:
            try:
                db.delete_content(unused.id)
            except Exception as exc:
                logger.debug(f"[OneLibrary] couldn't delete unused slot {unused.id}: {exc}")

        # Stage 4 — playlist tree (create_playlist works, no template needed)
        yield {"stage": "playlists", "message": "Writing playlist tree…", "progress": 80}
        try:
            self._write_playlists(db, source, content_id_map, playlist_filter)
        except Exception as e:
            logger.warning(f"[OneLibrary] playlist tree write skipped: {e}")

        # NOTE: Previously we tried to force a SQLite auto-checkpoint here
        # by issuing 1000+ dummy `update_content` writes — the theory was
        # that crossing the wal_autocheckpoint=1000 threshold would merge
        # WAL into main DB. In practice this only ran a PASSIVE checkpoint
        # which leaves the WAL file un-truncated, and the residual WAL
        # frames caused Rekordbox to mark the library as corrupted.
        # The real flush now happens in Stage 6 below via handle close +
        # reopen, which guarantees a TRUNCATE-equivalent state.

        # Stage 5 — Mirror everything we just wrote into export.pdb /
        # exportExt.pdb so older CDJs (CDJ-2000nxs2 era) and Rekordbox's
        # "Device Library" view see the same tracks + playlists. We pull
        # the data straight from the OneLibrary DB so the FKs are
        # guaranteed to line up between the two formats.
        #
        # `write_pdb=False` escape hatch: the PDB writer's empty_candidate
        # field still doesn't match the F: drive Pioneer reference (we use
        # one global blank page; F: uses 20 per-table blanks). When the
        # mismatched .pdb is on the stick, Rekordbox 7 prompts "Device
        # library is corrupted" even though the OneLibrary DB itself is
        # valid. Skipping the PDB writes lets the user keep working with
        # OneLibrary-only sticks (CDJ-3000 / Rekordbox-7 native path)
        # until the PDB structural fix lands.
        if write_pdb:
            yield {"stage": "pdb", "message": "Writing legacy PDB…", "progress": 90}
            try:
                self._write_pdb_from_db(db, source)
            except Exception as e:
                logger.warning(f"[OneLibrary] PDB write skipped: {e}", exc_info=False)
        else:
            # Make sure no stale PDB from a prior sync stays on the stick —
            # otherwise Rekordbox keeps reading the old (broken) PDB and
            # our skip would have no effect.
            for stale in (
                self.rb_dir / "export.pdb",
                self.rb_dir / "exportExt.pdb",
            ):
                try:
                    stale.unlink(missing_ok=True)
                except Exception as exc:
                    logger.debug("[OneLibrary] couldn't remove stale PDB %s: %s", stale, exc)
            logger.info("[OneLibrary] PDB write disabled (write_pdb=False) — OneLibrary-only sync")

        # Stage 6 — Force WAL flush by destroying the rbox handle. WHY:
        # rbox 0.1.7 holds the SQLite connection open for the lifetime of
        # the Python wrapper and exposes no `close()` / no PRAGMA passthrough.
        # If `db` falls out of scope only at function return, the WAL
        # (~400 KB of unmerged frames) survives on the USB stick and
        # Rekordbox prompts "Device library is corrupted" on insert.
        #
        # CRITICAL: the `del db` MUST run in this scope — passing `db` to
        # a helper and `del`-ing the parameter inside the helper only
        # drops the local binding; the outer ref keeps the rbox object
        # alive and the handle is never released. Same trap with closures.
        # Verified: helper-based del leaves -wal=387312 B; inline del
        # leaves -wal=0 B.
        try:
            del db
            gc.collect()
            time.sleep(0.5)
            self._reopen_for_recovery()
            self._log_post_flush_state()
        except Exception as e:
            logger.warning(f"[OneLibrary] WAL flush failed: {e}", exc_info=False)

        # Final summary
        if skipped_overflow > 0:
            yield {
                "stage": "warning",
                "message": (
                    f"OneLibrary: {used_slots}/{total} tracks written "
                    f"({skipped_overflow} skipped — template has only {slot_count} slots). "
                    f"Rebuild template from a Rekordbox stick with more tracks for a higher cap. "
                    f"All {total} tracks are in rekordbox.xml for manual import."
                ),
                "progress": 100,
            }
        else:
            yield {
                "stage": "complete",
                "message": f"OneLibrary export written: {used_slots} tracks",
                "progress": 100,
            }

    # ─── helpers ─────────────────────────────────────────────────────────

    def _reopen_for_recovery(self) -> None:
        """Open + immediately close the DB once more to force WAL recovery.

        Caller MUST have already `del`'d its own reference to the rbox
        handle and run `gc.collect()` BEFORE calling this — otherwise the
        first connection is still alive and SQLite can't truncate the WAL.

        SQLite's open path runs WAL recovery (merges complete frames into
        the main DB) and, when no other connection holds the WAL,
        performs a TRUNCATE checkpoint that empties the -wal file.
        """
        if rbox is None:
            return
        path = str(self.db_path)
        try:
            db2 = rbox.OneLibrary(path)
        except Exception as e:
            logger.warning("[OneLibrary] Reopen for WAL flush failed: %s", e)
            return
        with contextlib.suppress(Exception):
            list(db2.get_contents())
        del db2
        gc.collect()
        time.sleep(0.5)

    def _log_post_flush_state(self) -> None:
        """Diagnostic — verify the fix worked in the field.

        Target: -wal = 0 B. SHM may still exist (~32 KB) which is normal
        for a cleanly-closed WAL-mode SQLCipher DB.
        """
        try:
            wal = Path(str(self.db_path) + "-wal")
            wal_size = wal.stat().st_size if wal.exists() else 0
            logger.info(
                "[OneLibrary] WAL flush complete: -wal=%d B (target 0)",
                wal_size,
            )
            if wal_size > 0:
                logger.warning(
                    "[OneLibrary] WAL still has %d bytes after flush — "
                    "Rekordbox may flag the library as corrupted. "
                    "Investigate rbox close semantics.",
                    wal_size,
                )
        except Exception:
            pass

    def _get_or_create_artist(self, db, cache: dict, name: str) -> str | None:
        if not name:
            return None
        if name in cache:
            return cache[name]
        try:
            existing = db.get_artist_by_name(name)
            if existing:
                cache[name] = str(existing.id)
                return cache[name]
        except Exception:
            pass
        try:
            obj = db.create_artist(name)
            cache[name] = str(obj.id)
            return cache[name]
        except Exception as e:
            logger.debug(f"create_artist failed for {name}: {e}")
            return None

    def _get_or_create_album(self, db, cache: dict, name: str, artist_id: str | None) -> str | None:
        if not name:
            return None
        key = f"{name}|{artist_id or ''}"
        if key in cache:
            return cache[key]
        try:
            existing = db.get_album_by_name(name)
            if existing:
                cache[key] = str(existing.id)
                return cache[key]
        except Exception:
            pass
        try:
            obj = db.create_album(name, artist_id, None)
            cache[key] = str(obj.id)
            return cache[key]
        except Exception as e:
            logger.debug(f"create_album failed: {e}")
            return None

    def _get_or_create_genre(self, db, cache: dict, name: str) -> str | None:
        if not name:
            return None
        if name in cache:
            return cache[name]
        try:
            existing = db.get_genre_by_name(name)
            if existing:
                cache[name] = str(existing.id)
                return cache[name]
        except Exception:
            pass
        try:
            obj = db.create_genre(name)
            cache[name] = str(obj.id)
            return cache[name]
        except Exception:
            return None

    def _get_or_create_key(self, db, cache: dict, name: str) -> str | None:
        if not name:
            return None
        if name in cache:
            return cache[name]
        try:
            existing = db.get_key_by_name(name)
            if existing:
                cache[name] = str(existing.id)
                return cache[name]
        except Exception:
            pass
        try:
            obj = db.create_key(name)
            cache[name] = str(obj.id)
            return cache[name]
        except Exception:
            return None

    def _get_or_create_label(self, db, cache: dict, name: str) -> str | None:
        if not name:
            return None
        if name in cache:
            return cache[name]
        try:
            existing = db.get_label_by_name(name)
            if existing:
                cache[name] = str(existing.id)
                return cache[name]
        except Exception:
            pass
        try:
            obj = db.create_label(name)
            cache[name] = str(obj.id)
            return cache[name]
        except Exception:
            return None

    def _write_pdb_from_db(self, db, source) -> None:
        """Mirror the freshly-built OneLibrary DB into export.pdb / exportExt.pdb.

        Pulled from the OneLibrary DB rather than the source LibrarySource so
        the IDs are guaranteed to match what's in exportLibrary.db (each
        playlist_content row, every artist FK on every track, etc.).
        """
        from . import usb_pdb
        from .usb_manager import _is_excluded_playlist

        # ── Gather rows ────────────────────────────────────────────────
        artists = {int(a.id): (a.name or "") for a in db.get_artists()}
        # Artwork rows: pull image table out of OneLibrary so the legacy
        # PDB's djmdArtwork has the same id ↔ path mapping the modern
        # OneLibrary DB has. Track rows already store their image_id;
        # without this table CDJ-2000NXS2-era hardware shows generic
        # placeholders instead of cover art (Rekordbox 7 native view
        # falls back to OneLibrary so it isn't affected).
        artworks = {
            int(img.id): (img.path or "") for img in db.get_images() if (img.path or "").strip()
        }
        albums = {
            int(a.id): (a.name or "", int(getattr(a, "artist_id", 0) or 0)) for a in db.get_albums()
        }
        keys = {int(k.id): (k.name or "") for k in db.get_keys()}
        genres = {int(g.id): (g.name or "") for g in db.get_genres()}
        labels = {int(lab.id): (lab.name or "") for lab in db.get_labels()}

        contents_data = []
        for c in db.get_contents():
            # Skip placeholder rows that still have the template title
            title = c.title or ""
            if title.startswith("__placeholder_"):
                continue
            # Date semantics — verified vs F: drive byte-by-byte:
            #   PDB slot 10 ("date_added") <- OneLibrary `date_created`
            #     (date when track first entered any rekordbox library)
            #   PDB slot 15 ("analyze_date") <- OneLibrary `date_added`
            #     (date when track was added to / synced onto the stick)
            # Despite the slot names, F: drive Pioneer exports use the
            # SWAPPED mapping above. Setting them the "obvious" way (using
            # date_added for slot 10) caused Rekordbox to flag the library
            # as corrupted — the dates didn't match what Rekordbox expected
            # to find based on its master.db record for the same content_id.
            date_created_str = ""
            try:
                if getattr(c, "date_created", None):
                    date_created_str = c.date_created.strftime("%Y-%m-%d")
            except Exception:
                pass
            date_added_str = ""
            try:
                if getattr(c, "date_added", None):
                    date_added_str = c.date_added.strftime("%Y-%m-%d")
            except Exception:
                pass
            # analyze_path: copy from OneLibrary's analysis_data_file_path —
            # without it the PDB row has no link to the .DAT sidecar and
            # Rekordbox flags the device library as corrupted.
            analyze_path_str = getattr(c, "analysis_data_file_path", "") or ""
            contents_data.append(
                {
                    "id": int(c.id),
                    "title": title,
                    "artist_id": int(getattr(c, "artist_id", 0) or 0),
                    "album_id": int(getattr(c, "album_id", 0) or 0),
                    "genre_id": int(getattr(c, "genre_id", 0) or 0),
                    "key_id": int(getattr(c, "key_id", 0) or 0),
                    "label_id": int(getattr(c, "label_id", 0) or 0),
                    "color_id": int(getattr(c, "color_id", 0) or 0),
                    "artwork_id": int(getattr(c, "image_id", 0) or 0),
                    "bpm": (int(getattr(c, "bpmx100", 0) or 0)) / 100.0,
                    "length_seconds": int(getattr(c, "length", 0) or 0),
                    "bitrate": int(getattr(c, "bitrate", 0) or 0),
                    "year": int(getattr(c, "release_year", 0) or 0),
                    "rating": int(getattr(c, "rating", 0) or 0),
                    "sample_rate": int(getattr(c, "sampling_rate", 0) or 0),
                    "sample_depth": int(getattr(c, "bit_depth", 0) or 0),
                    "file_size": int(getattr(c, "file_size", 0) or 0),
                    "file_path": getattr(c, "path", "") or "",
                    "file_name": getattr(c, "file_name", "") or "",
                    "comment": getattr(c, "dj_comment", "") or "",
                    "isrc": getattr(c, "isrc", "") or "",
                    # See date semantics comment above — slots are swapped on F: drive.
                    "date_added": date_created_str,  # PDB slot 10 ← OneLibrary date_created
                    "analyze_path": analyze_path_str,
                    "analyze_date": date_added_str,  # PDB slot 15 ← OneLibrary date_added
                    "file_type": int(getattr(c, "file_type", 0) or 0),
                    "play_count": int(getattr(c, "play_count", 0) or 0),
                    # FK back into the PC-side rekordbox masterdb. Real
                    # Rekordbox embeds these in every PDB track row so the
                    # CDJ can match a played track back to the desktop
                    # library when sticks rejoin. Without them present (the
                    # "magic constant" path the writer used previously),
                    # Rekordbox flags the PDB as corrupt on import.
                    "master_db_id": int(getattr(c, "master_db_id", 0) or 0),
                    "master_content_id": int(getattr(c, "master_content_id", 0) or 0),
                    # Bitmask + index_shift are observed non-zero on real
                    # exports (analysis-state flags). 0x000C0700 is the
                    # "fully analysed" bitmask seen on F: drive — safe
                    # default that doesn't claim missing analysis we lack.
                    "bitmask": int(getattr(c, "bitmask", 0x000C0700) or 0x000C0700),
                    "index_shift": int(getattr(c, "index_shift", 0) or 0),
                }
            )

        # Playlist tree — preserve folder hierarchy + per-sibling sort order.
        # rbox 0.1.7 returns `attribute` as a `PlaylistType` enum (unhashable),
        # so coerce via `int()` per the live_database.py shim.
        pls_by_id = {p.id: p for p in db.get_playlists()}

        def _attr_int(p):
            raw = getattr(p, "attribute", 0)
            try:
                return int(getattr(raw, "value", raw))
            except (TypeError, ValueError):
                return 0

        # Sort siblings within each parent so seq values reflect display order
        # in Rekordbox (matches what users see in the source library).
        siblings: dict[int, list[Any]] = {}
        for p in pls_by_id.values():
            parent = int(getattr(p, "parent_id", 0) or 0)
            siblings.setdefault(parent, []).append(p)
        for kids in siblings.values():
            kids.sort(key=lambda x: int(getattr(x, "seq", 0) or 0))

        playlists_pdb: list[dict[str, Any]] = []
        playlist_entries_pdb: list[tuple] = []
        for parent_id, kids in siblings.items():
            for sort_idx, p in enumerate(kids):
                pname = p.name or ""
                if _is_excluded_playlist(pname):
                    continue
                is_folder = _attr_int(p) == 1
                playlists_pdb.append(
                    {
                        "id": int(p.id),
                        "parent_id": parent_id,
                        "sort_order": sort_idx,  # 0-based within siblings
                        "is_folder": is_folder,
                        "name": pname,
                    }
                )
                if not is_folder:
                    try:
                        # rbox quirk: `get_playlist_contents` returns the
                        # joined Content rows themselves (not the link rows),
                        # so the content id is `pc.id`, not `pc.content_id`.
                        # Earlier version used the wrong attribute and
                        # shipped an empty playlist_entries table.
                        contents = db.get_playlist_contents(int(p.id))
                        for entry_idx, pc in enumerate(contents):
                            cid = int(getattr(pc, "id", 0) or 0)
                            if cid:
                                playlist_entries_pdb.append((entry_idx, cid, int(p.id)))
                    except Exception as exc:
                        logger.debug(
                            "[OneLibrary] PDB playlist_contents skipped for %s: %s",
                            p.id,
                            exc,
                        )

        # ── Write ──────────────────────────────────────────────────────
        # Truncate-write succeeds even if Rekordbox holds a read handle.
        usb_pdb.write_export_pdb(
            self.usb_root,
            contents=contents_data,
            artists=artists,
            albums=albums,
            keys=keys,
            genres=genres,
            labels=labels,
            playlists=playlists_pdb,
            playlist_entries=playlist_entries_pdb,
            artworks=artworks,
        )

        # exportExt.pdb — MyTag definitions + tag-track associations.
        # Categories (rbox attribute MyTagType.Folder=1) and tags
        # (MyTagType.List=0) live in the same id space, so we just split
        # them by `attribute` and pass both buckets into the ext writer.
        tag_categories: dict[int, str] = {}
        tags: dict[int, str] = {}
        for mt in db.get_my_tags():
            attr_raw = getattr(mt, "attribute", 0)
            try:
                attr_int = int(getattr(attr_raw, "value", attr_raw))
            except (TypeError, ValueError):
                attr_int = 0
            if attr_int == 1:
                tag_categories[int(mt.id)] = mt.name or ""
            else:
                tags[int(mt.id)] = mt.name or ""
        tag_track_links: list[tuple[int, int]] = []
        for tag_id in tags:
            try:
                for tc in db.get_my_tag_contents(tag_id):
                    track_id = int(getattr(tc, "id", 0) or 0)
                    if track_id:
                        tag_track_links.append((track_id, tag_id))
            except Exception:
                pass

        usb_pdb.write_export_ext_pdb(
            self.usb_root,
            tags=tags,
            tag_categories=tag_categories,
            tag_track_links=tag_track_links,
        )
        logger.info(
            "[OneLibrary] PDB written: %d tracks, %d artists, %d albums, %d playlists, %d entries",
            len(contents_data),
            len(artists),
            len(albums),
            len(playlists_pdb),
            len(playlist_entries_pdb),
        )

    def _write_track_artwork(self, db, slot, audio_path: Path) -> None:
        """Generate the bucketed artwork pair for one track and update the
        OneLibrary `image` row to point at the small JPEG.

        Reuses whichever image_id the placeholder slot already references
        (template-baseline images carry empty paths after anonymisation).
        """
        from . import usb_artwork

        image_id = getattr(slot, "image_id", None)
        if image_id in (None, 0):
            # No FK — try to create a fresh image row (works on real DBs).
            try:
                img = db.create_image(usb_artwork.usb_relative_path(1))  # placeholder path
                image_id = int(img.id)
                slot.image_id = image_id
            except Exception as exc:
                logger.debug("[OneLibrary] create_image failed: %s", exc)
                return

        result = usb_artwork.write_artwork_pair(audio_path, int(image_id), self.pioneer)
        if not result:
            return  # no embedded art — leave existing image FK in place

        # Point the image record at our small JPEG so CDJ list-view can find it
        try:
            img_row = db.get_image_by_id(int(image_id))
            if img_row is not None:
                img_row.path = usb_artwork.usb_relative_path(int(image_id))
                db.update_image(img_row)
        except Exception as exc:
            logger.debug("[OneLibrary] update_image path skipped: %s", exc)

    def _planned_dest(self, track: dict, src_path: Path) -> Path:
        """Where this track's audio belongs on the stick.

        Single source of truth for the relocation pass and the copy phase — the
        two disagreeing would relocate a file and then copy it again anyway.
        """
        if self._dest_resolver is not None:
            return self._dest_resolver(
                track.get("artist") or "",
                track.get("title") or "",
                src_path.name,
            )
        return self._dest_audio_path(track, src_path)

    def _dest_audio_path(self, track: dict, src_path: Path) -> Path:
        """Pioneer-canonical layout: <usb>/Contents/<Artist>/<Title>/<filename>.

        Used as a fallback when no `dest_resolver` is supplied. Title (not
        Album) is the second segment to match Rekordbox's own export format.
        """
        artist = self._safe_segment(track.get("artist") or "Unknown Artist")
        title = self._safe_segment(track.get("title") or src_path.stem or "Unknown Title")
        return self.music_dir / artist / title / src_path.name

    @staticmethod
    def _safe_segment(s: str) -> str:
        bad = '<>:"/\\|?*'
        out = "".join(c if c not in bad else "_" for c in s).strip()
        return out[:80] or "Unknown"

    def _copy_artwork(self, track: dict, content_id: str) -> None:
        """Copy cover-art into PIONEER/Artwork/<bucket>/<hash>.jpg if available."""
        art = track.get("artwork")
        if not art:
            return
        src = Path(art)
        if not src.exists():
            return
        bucket = "P" + str(int(content_id) // 1000).zfill(3) if content_id.isdigit() else "P000"
        target_dir = self.artwork_dir / bucket
        target_dir.mkdir(parents=True, exist_ok=True)
        h = hashlib.sha1(content_id.encode()).hexdigest()[:8].upper()
        try:
            shutil.copy2(str(src), str(target_dir / f"{h}.jpg"))
        except Exception as e:
            logger.debug(f"Artwork copy skipped: {e}")

    @staticmethod
    def _anlz_bucket(content_id: int) -> tuple:
        """CDJ bucket layout: PIONEER/USBANLZ/P<bucket-hex>/<inner-hex>/.

        Real Rekordbox exports use bucket = `P{(id // 256):03X}` and inner =
        `{id:08X}`. Both are upper-case hex. Verified against an F: drive
        export. The exact convention isn't strictly required — Rekordbox
        and CDJs read the path from the DB — but matching it makes the
        result indistinguishable from a real Rekordbox stick.
        """
        cid = max(int(content_id), 0)
        bucket = f"P{(cid // 256):03X}".upper()
        inner = f"{cid:08X}".upper()
        return bucket, inner

    def _generate_or_copy_anlz_for(
        self,
        track: dict,
        content_id: str,
        source,
    ) -> str | None:
        """Drop the per-track ANLZ sidecar trio into PIONEER/USBANLZ/.

        Strategy:
          1. Look for cached sidecars in <music_dir>/.lms_anlz/<hash>/ —
             written at import-time by `anlz_sidecar.write_companion_anlz`.
             If present, just copy.
          2. Otherwise run the analysis on demand (slow but bounded — same
             code path as the importer uses) and cache the output.
          3. Either way, copy the resulting DAT/EXT/2EX into the CDJ
             bucket layout so they ride out to the stick.

        Returns the relative `analysis_data_file_path` (matches
        Rekordbox's own value in exportLibrary.db) or None on failure.
        """
        sidecar_dir = source.get_anlz_sidecar_dir(track)

        # Auto-generate if no cached sidecar — but only if we have an audio
        # source. Streaming pseudo-tracks (SoundCloud URI etc.) get None.
        if not (sidecar_dir and sidecar_dir.exists()):
            audio_path_str = track.get("path")
            if not audio_path_str:
                return None
            audio_path = Path(audio_path_str)
            if not audio_path.exists():
                return None
            try:
                from . import anlz_sidecar

                sidecar_dir = anlz_sidecar.write_companion_anlz(audio_path)
            except Exception as exc:
                logger.debug("[ANLZ] generation failed for %s: %s", audio_path.name, exc)
                return None
            if not sidecar_dir or not sidecar_dir.exists():
                return None

        bucket, inner = self._anlz_bucket(int(content_id))
        target_dir = self.anlz_root / bucket / inner
        target_dir.mkdir(parents=True, exist_ok=True)

        copied = []
        for src in sidecar_dir.glob("ANLZ*"):
            dst = target_dir / src.name
            try:
                _copy_file_atomic(src, dst)
                copied.append(src.name)
            except OSError as exc:
                logger.debug("[ANLZ] copy %s -> %s failed: %s", src, dst, exc)

        if not copied:
            return None

        # Relative path stored in OneLibrary `content.analysis_data_file_path`
        # — must point at the .DAT specifically (CDJ infers .EXT/.2EX from there)
        return f"/PIONEER/USBANLZ/{bucket}/{inner}/ANLZ0000.DAT"

    # Back-compat shim — old `_copy_anlz_for` callers should switch to
    # `_generate_or_copy_anlz_for`. Kept while we transition the call sites.
    def _copy_anlz_for(self, track: dict, content_id: str, source) -> None:
        self._generate_or_copy_anlz_for(track, content_id, source)

    def _write_playlists(
        self,
        db,
        source,
        content_id_map: dict[str, str],
        playlist_filter: list[str] | None = None,
    ) -> None:
        """Walks playlist tree, creates folders / playlists, links tracks.

        rbox 0.1.7 caveat: `create_playlist_content(playlist_id, content_id,
        seq)` rejects str ids with TypeError ("'str' object cannot be
        interpreted as an integer"). Earlier code stored ids as str and the
        TypeError got silently swallowed — playlists shipped to USB but were
        empty on the CDJ. We now pass ints throughout.

        System playlists like "Import" are filtered out — see
        usb_manager.EXCLUDED_USB_PLAYLISTS.

        When `playlist_filter` is set, only those playlists (plus the folder
        ancestors needed to reach them in the tree) are emitted — keeps the
        CDJ menu clean when the user picks a subset to push.
        """
        from .usb_manager import _is_excluded_playlist

        playlists = [
            p for p in source.iter_playlists() if not _is_excluded_playlist(p.get("name", ""))
        ]

        # Prune to selected playlists + folder ancestors. We walk parent_id
        # chains so a deeply nested checked playlist still has its folders
        # written first (otherwise create_playlist would orphan it).
        if playlist_filter:
            keep = {str(p) for p in playlist_filter}
            by_id = {str(p["id"]): p for p in playlists}
            ancestors: set = set()
            for pid in list(keep):
                cur = by_id.get(pid)
                while cur:
                    parent = str(cur.get("parent_id") or "")
                    if not parent or parent.upper() == "ROOT":
                        break
                    if parent in ancestors or parent in keep:
                        break
                    ancestors.add(parent)
                    cur = by_id.get(parent)
            keep |= ancestors
            before = len(playlists)
            playlists = [p for p in playlists if str(p["id"]) in keep]
            logger.info(
                "[OneLibrary] Playlist filter: %d/%d playlists kept (incl. %d ancestor folders)",
                len(playlists),
                before,
                len(ancestors),
            )
        # Build parent → children map
        by_parent: dict[str, list[dict]] = {}
        for p in playlists:
            by_parent.setdefault(p["parent_id"], []).append(p)

        # ID-translation: source-pid → onelibrary-pid (kept as int)
        id_map: dict[str, int | None] = {"ROOT": None}

        def _emit(parent_src_id: str, parent_one_id: int | None):
            children = by_parent.get(parent_src_id, [])
            for seq, child in enumerate(children):
                try:
                    if child["type"] == "0":
                        obj = (
                            db.create_playlist_folder(child["name"], parent_one_id, seq)
                            if hasattr(db, "create_playlist_folder")
                            else db.create_playlist(child["name"], parent_one_id, seq)
                        )
                    else:
                        obj = db.create_playlist(child["name"], parent_one_id, seq)
                    one_id = int(getattr(obj, "id", 0)) or None
                    id_map[child["id"]] = one_id
                    # Link tracks (skip for folders/smart-without-materialised).
                    # Both ids MUST be int for rbox's create_playlist_content.
                    if child["type"] in ("1", "4") and one_id is not None:
                        linked = 0
                        for ti, t_src_id in enumerate(child["track_ids"]):
                            content_id_str = content_id_map.get(str(t_src_id))
                            if not content_id_str:
                                continue
                            try:
                                db.create_playlist_content(
                                    int(one_id),
                                    int(content_id_str),
                                    ti,
                                )
                                linked += 1
                            except Exception as e:
                                logger.warning(
                                    "[OneLibrary] playlist_content link failed "
                                    "(pl=%s,content=%s): %s",
                                    one_id,
                                    content_id_str,
                                    e,
                                )
                        logger.info(
                            "[OneLibrary] playlist '%s' linked %d/%d tracks",
                            child["name"],
                            linked,
                            len(child["track_ids"]),
                        )
                    _emit(child["id"], one_id)
                except Exception as e:
                    logger.warning(f"playlist '{child['name']}' skipped: {e}")

        _emit("ROOT", None)
