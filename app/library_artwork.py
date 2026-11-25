"""Library artwork path -> image file on disk.

One resolver for `GET /api/artwork` (cover in the app) and the USB export (cover on
the stick), so both show the same image. A track's artwork path is either
Rekordbox's `djmdContent.ImagePath` (`/PIONEER/Artwork/...`, relative to the
Rekordbox share folder) or an absolute path into the LMS covers folder
(`COVERS_DIR`, where the import writes the cover it extracts from the file).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from platformdirs import user_data_dir

logger = logging.getLogger(__name__)

ARTWORK_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"})
_APP_DIRNAME = "MusicLibraryManager"


def _lms_data_dir() -> Path:
    """%APPDATA%/MusicLibraryManager; the platformdirs user-data dir without APPDATA."""
    app_data = os.environ.get("APPDATA")
    if app_data:
        return Path(app_data) / _APP_DIRNAME
    return Path(user_data_dir(_APP_DIRNAME, appauthor=False))


# Not the code tree: the installed sidecar is a PyInstaller onefile, its code tree
# a temp dir that is unpacked on every start and deleted on exit.
COVERS_DIR = _lms_data_dir() / "covers"
# Read-only: the code-tree folder COVERS_DIR used to be (dev checkouts).
LEGACY_COVERS_DIR = Path(__file__).resolve().parent / "data" / "covers"


class ArtworkPathError(ValueError):
    """An artwork path the resolver refuses; `status` is what `/api/artwork` answers."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def rekordbox_share_dir() -> Path | None:
    """Rekordbox 6/7 share folder (root of ImagePath), or None without APPDATA."""
    app_data = os.environ.get("APPDATA")
    if not app_data:
        return None
    return Path(app_data) / "Pioneer" / "rekordbox" / "share"


def legacy_covers_dirs() -> list[Path]:
    """Folders older builds wrote imported covers to; read, never written."""
    dirs = [LEGACY_COVERS_DIR]
    app_data = os.environ.get("APPDATA")
    if app_data:
        # The import wrote to REKORDBOX_ROOT.parent / "app/data/covers" (inside
        # Pioneer's folder) and stored the absolute path as the track's artwork.
        dirs.append(Path(app_data) / "Pioneer" / "app" / "data" / "covers")
    return dirs


def resolve_artwork_path(path: str) -> Path:
    """The image file a library artwork path points at.

    Only image files inside the LMS covers folder, a legacy covers folder or the
    Rekordbox share pass.

    Raises:
        ArtworkPathError: 404 empty path or no such file, 400 not an image type,
            403 outside every allowed folder.
    """
    if not path:
        raise ArtworkPathError(404, "No path provided")
    share = rekordbox_share_dir()
    candidate = Path(path)
    if path.startswith("/PIONEER/"):
        if share is not None:
            # lstrip is load-bearing: share / "/PIONEER/x" would drop the share root.
            candidate = share / path.lstrip("/")
        else:
            logger.warning("APPDATA not found, cannot resolve PIONEER artwork path")
    file_path = candidate.resolve()

    if file_path.suffix.lower() not in ARTWORK_EXTENSIONS:
        raise ArtworkPathError(400, "Invalid artwork file type")
    roots = [COVERS_DIR.resolve(), *(d.resolve() for d in legacy_covers_dirs())]
    if share is not None:
        roots.append(share.resolve())
    if not any(file_path.is_relative_to(root) for root in roots):
        raise ArtworkPathError(403, "Access denied: path outside allowed artwork directories")
    if not file_path.is_file():
        raise ArtworkPathError(404, "Artwork file not found")
    return file_path


def library_artwork_file(path: str | None) -> Path | None:
    """`resolve_artwork_path`, or None where the route would answer an error."""
    if not path:
        return None
    try:
        return resolve_artwork_path(path)
    except ArtworkPathError as exc:
        logger.debug("[artwork] library cover %r not usable: %s", path, exc.detail)
        return None
    except OSError as exc:  # resolve() on an unreadable / malformed path
        logger.debug("[artwork] library cover %r not resolvable: %s", path, exc)
        return None
