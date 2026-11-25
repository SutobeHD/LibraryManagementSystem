"""Library artwork path -> image file on disk.

One resolver for `GET /api/artwork` (cover in the app) and the USB export (cover on
the stick), so both show the same image. A track's artwork path is either
Rekordbox's `djmdContent.ImagePath` (`/PIONEER/Artwork/...`, relative to the
Rekordbox share folder) or an absolute path into the LMS covers folder.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

ARTWORK_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif"})
COVERS_DIR = Path(__file__).resolve().parent / "data" / "covers"


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


def resolve_artwork_path(path: str) -> Path:
    """The image file a library artwork path points at.

    Only image files inside the LMS covers folder or the Rekordbox share pass.

    Raises:
        ArtworkPathError: 404 empty path or no such file, 400 not an image type,
            403 outside both folders.
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
    roots = [COVERS_DIR.resolve()]
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
