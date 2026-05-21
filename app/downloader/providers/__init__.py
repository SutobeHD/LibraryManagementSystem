"""Concrete :class:`~app.downloader.SourceProvider` implementations.

One module per coherent platform group:

* :mod:`app.downloader.providers.spotiflac` — Spotify-pivoted multi-service
  provider (Tidal / Qobuz / Amazon / Apple Music / Deezer) wrapping the
  reverse-engineering ``SpotiFLAC`` library inside a crash-isolated
  ``ProcessPoolExecutor`` worker pool (the ``app.anlz_safe`` pattern).
* :mod:`app.downloader.providers.soundcloud` — SoundCloud provider wrapping
  the project's existing ``soundcloud_api`` + ``soundcloud_downloader`` code.

Each class implements the three-coroutine contract (``resolve_url`` /
``search`` / ``fetch``) from :class:`app.downloader.SourceProvider`.

See ``docs/research/implement/accepted_downloader-unified-multi-source.md``
§ "P1.5 / P1.7".
"""

from __future__ import annotations

from .soundcloud import SoundCloudProvider
from .spotiflac import SpotiFlacProvider

__all__ = ["SoundCloudProvider", "SpotiFlacProvider"]
