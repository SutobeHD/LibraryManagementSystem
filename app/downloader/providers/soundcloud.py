"""SoundCloud :class:`~app.downloader.SourceProvider`.

A thin adapter over the project's *existing* SoundCloud code — it adds no new
network logic, it re-uses what already ships and is already tested:

* :mod:`app.soundcloud_api` — ``SoundCloudPlaylistAPI.resolve_track_from_url``
  for URL resolution and the ``_sc_get`` / ``get_sc_client_id`` helpers for the
  v2 search call.
* :mod:`app.soundcloud_downloader` — ``_resolve_official_download_url``,
  ``_resolve_stream_via_transcodings`` and the ``_stream_file_to_temp`` /
  ``_download_hls_to_temp`` byte-pullers for the actual fetch.

All three coroutine methods are sync-bound underneath, so they run the blocking
work on a worker thread via :func:`anyio.to_thread.run_sync` — the existing
``app.main`` pattern; no ``httpx`` is pulled in for v1.

Quality claims
--------------
SoundCloud serves either an *original-file* download (when the uploader ticked
the download box — could be WAV/FLAC/MP3, format unknown until fetched) or a
transcoded stream (Go+ 256 kbps AAC, or standard 128 kbps MP3). Phase-1 cannot
know the original file's true format, so a ``downloadable`` track is claimed
optimistically as lossless CD-tier and corrected post-download by
``quality_engine``; a non-downloadable track is claimed as the lossy stream
ceiling. See ``docs/research/implement/accepted_downloader-unified-multi-source.md``
§ "P1.7" + § "Quality policy hardening".
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import quote

from anyio import to_thread

from .. import SourceProvider
from ..models import Platform, QualityTier, TrackMatch

logger = logging.getLogger(__name__)

#: SoundCloud v2 search endpoint — same host the web player's search box hits.
_SC_V2_SEARCH = "https://api-v2.soundcloud.com/search/tracks"

#: SoundCloud durations are integer milliseconds; the downloader works in
#: float seconds.
_MS_PER_S = 1000.0


class SoundCloudProvider(SourceProvider):
    """:class:`~app.downloader.SourceProvider` backed by the existing SC code.

    Holds an optional OAuth token (the per-account ``auth_token`` the rest of
    the app stores in the OS keyring). When present it is forwarded to every
    underlying SC call so private/Go+ tracks the account can stream are
    reachable; when absent the calls fall back to anonymous ``client_id`` mode.
    """

    def __init__(self, auth_token: str | None = None) -> None:
        """Bind the provider, optionally to a SoundCloud OAuth token."""
        self._auth_token = auth_token

    @property
    def platform(self) -> Platform:
        """Always ``"soundcloud"``."""
        return "soundcloud"

    async def resolve_url(self, url: str) -> list[TrackMatch]:
        """Resolve a SoundCloud permalink URL to a single :class:`TrackMatch`.

        Delegates to ``SoundCloudPlaylistAPI.resolve_track_from_url`` (the
        existing ``/resolve`` wrapper). Returns a one-element list for a track
        URL, or an empty list when the URL resolves to a non-track
        (playlist/user) or to nothing.

        A dead source must not abort a multi-provider resolve, so transport
        failures are swallowed into an empty list rather than raised.
        """
        from app.soundcloud_api import AuthExpiredError, SoundCloudPlaylistAPI

        def _resolve() -> dict[str, Any] | None:
            return SoundCloudPlaylistAPI.resolve_track_from_url(url, self._auth_token)

        try:
            track = await to_thread.run_sync(_resolve)
        except AuthExpiredError as exc:
            logger.info("[sc-provider] resolve_url(%s) auth failed: %s", url, exc)
            return []
        except Exception as exc:
            logger.warning("[sc-provider] resolve_url(%s) failed: %s", url, exc)
            return []

        if not track:
            return []
        return [self._claim_from_track(track)]

    async def search(self, query: str, limit: int = 5) -> list[TrackMatch]:
        """Free-form search via the SoundCloud v2 ``/search/tracks`` endpoint.

        Returns up to ``limit`` :class:`TrackMatch` claims. An empty list on a
        transport failure, an auth failure, or a genuinely empty result set —
        the orchestrator treats "no hits" and "search unavailable" alike.
        """
        from app.soundcloud_api import AuthExpiredError, _sc_get, get_sc_client_id

        def _search() -> list[dict[str, Any]]:
            headers: dict[str, str] = {
                "Accept": "application/json",
                "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"),
            }
            params: dict[str, Any] = {"q": query, "limit": limit}
            if self._auth_token:
                headers["Authorization"] = f"OAuth {self._auth_token}"
            else:
                params["client_id"] = get_sc_client_id()
            resp = _sc_get(
                f"{_SC_V2_SEARCH}?q={quote(query)}",
                headers=headers,
                params={k: v for k, v in params.items() if k != "q"},
                timeout=15,
            )
            data = resp.json()
            collection = data.get("collection", []) if isinstance(data, dict) else []
            return [t for t in collection if isinstance(t, dict)]

        try:
            raw_hits = await to_thread.run_sync(_search)
        except AuthExpiredError as exc:
            logger.info("[sc-provider] search(%r) auth failed: %s", query, exc)
            return []
        except Exception as exc:
            logger.warning("[sc-provider] search(%r) failed: %s", query, exc)
            return []

        # Truncate to `limit` *valid* claims — a dead hit (filtered to None by
        # _claim_from_v2_track) must not consume a slot.
        matches: list[TrackMatch] = []
        for raw in raw_hits:
            claim = self._claim_from_v2_track(raw)
            if claim is not None:
                matches.append(claim)
            if len(matches) >= limit:
                break
        logger.debug("[sc-provider] search(%r) -> %d hit(s)", query, len(matches))
        return matches

    async def fetch(self, match: TrackMatch, dest_dir: Path) -> Path:
        """Download the audio for a chosen SoundCloud :class:`TrackMatch`.

        Re-uses the existing two-stage acquisition from
        :mod:`app.soundcloud_downloader`: the official ``/download`` endpoint
        first (when the uploader enabled it), then the v2 ``transcodings[]``
        stream fallback. The resulting temp file is moved into ``dest_dir``
        under an ``Artist - Title.<ext>`` name.

        Raises:
            ValueError: ``match`` is not a SoundCloud claim, or its URL is not
                a resolvable SoundCloud track.
            RuntimeError: no usable stream (private/removed/paywalled) or the
                byte download itself failed.
        """
        if match.platform != "soundcloud":
            raise ValueError(f"SoundCloudProvider.fetch cannot serve platform {match.platform!r}")
        dest_dir.mkdir(parents=True, exist_ok=True)

        final_path = await to_thread.run_sync(self._fetch_blocking, match, dest_dir)
        return final_path

    # ──────────────────────────────────────────────────────────────────────
    # Blocking fetch — runs on a worker thread
    # ──────────────────────────────────────────────────────────────────────

    def _fetch_blocking(self, match: TrackMatch, dest_dir: Path) -> Path:
        """Synchronous body of :meth:`fetch` (offloaded to a thread)."""
        from app.soundcloud_api import SoundCloudPlaylistAPI
        from app.soundcloud_downloader import (
            _download_hls_to_temp,
            _resolve_official_download_url,
            _resolve_stream_via_transcodings,
            _sanitize_name,
            _stream_file_to_temp,
        )

        track = SoundCloudPlaylistAPI.resolve_track_from_url(match.url, self._auth_token)
        if not track or not track.get("id"):
            raise ValueError(f"SoundCloud URL did not resolve to a track: {match.url}")
        sc_track_id = str(track["id"])
        downloadable = bool(track.get("downloadable"))

        source: dict[str, Any] | None = None
        if downloadable:
            official_url = _resolve_official_download_url(sc_track_id, self._auth_token)
            if official_url:
                source = {
                    "url": official_url,
                    "protocol": "progressive",
                    "mime_type": "",
                }
        if source is None:
            source = _resolve_stream_via_transcodings(sc_track_id, self._auth_token)
        if source is None:
            raise RuntimeError(
                f"no available SoundCloud stream for sc_id={sc_track_id} "
                "(private/removed, or no full account access)"
            )

        if source.get("protocol") == "hls":
            tmp_path = _download_hls_to_temp(
                source["url"], self._auth_token, source.get("mime_type", "")
            )
        else:
            tmp_path = _stream_file_to_temp(source["url"], self._auth_token)
        if tmp_path is None:
            raise RuntimeError(f"SoundCloud file download failed for sc_id={sc_track_id}")

        ext = tmp_path.suffix.lower() or ".mp3"
        artist = _sanitize_name(match.artist or track.get("artist") or "Unknown")
        title = _sanitize_name(match.title or track.get("title") or sc_track_id)
        final_path = dest_dir / f"{artist} - {title}{ext}"
        shutil.move(str(tmp_path), str(final_path))
        logger.info("[sc-provider] fetched sc_id=%s -> %s", sc_track_id, final_path)
        return final_path

    # ──────────────────────────────────────────────────────────────────────
    # Claim builders
    # ──────────────────────────────────────────────────────────────────────

    def _claim_from_track(self, track: dict[str, Any]) -> TrackMatch:
        """Build a :class:`TrackMatch` from a v1-normalised SC track dict.

        ``track`` is the shape produced by
        ``SoundCloudPlaylistAPI._normalize_track`` (now carrying ``isrc``).
        """
        downloadable = bool(track.get("downloadable"))
        fmt, bit_depth, sample_rate, bitrate, tier = _quality_claim(downloadable)
        return TrackMatch(
            platform="soundcloud",
            url=str(track.get("permalink_url") or ""),
            title=str(track.get("title") or "Unknown"),
            artist=str(track.get("artist") or "Unknown"),
            duration_s=float(track.get("duration") or 0) / _MS_PER_S,
            isrc=track.get("isrc") or None,
            cover_url=track.get("artwork_url") or None,
            claimed_format=fmt,
            claimed_bit_depth=bit_depth,
            claimed_sample_rate_hz=sample_rate,
            claimed_bitrate_kbps=bitrate,
            quality_tier=tier,
        )

    def _claim_from_v2_track(self, raw: dict[str, Any]) -> TrackMatch | None:
        """Build a :class:`TrackMatch` from a raw v2 ``/search/tracks`` hit.

        Returns ``None`` for a dead/incomplete hit (no id, or no title and no
        uploader — the same filter ``_normalize_track`` applies).
        """
        track_id = raw.get("id")
        if not track_id:
            return None
        title = str(raw.get("title") or "")
        user = raw.get("user") or {}
        artist = str(user.get("username") or "") if isinstance(user, dict) else ""
        if not title and not artist:
            return None  # deleted/empty track

        downloadable = bool(raw.get("downloadable"))
        fmt, bit_depth, sample_rate, bitrate, tier = _quality_claim(downloadable)
        publisher = raw.get("publisher_metadata") or {}
        isrc = (publisher.get("isrc") if isinstance(publisher, dict) else None) or raw.get("isrc")
        return TrackMatch(
            platform="soundcloud",
            url=str(raw.get("permalink_url") or ""),
            title=title or "Unknown",
            artist=artist or "Unknown",
            duration_s=float(raw.get("duration") or 0) / _MS_PER_S,
            isrc=isrc or None,
            cover_url=raw.get("artwork_url") or None,
            claimed_format=fmt,
            claimed_bit_depth=bit_depth,
            claimed_sample_rate_hz=sample_rate,
            claimed_bitrate_kbps=bitrate,
            quality_tier=tier,
        )


def _quality_claim(
    downloadable: bool,
) -> tuple[Any, int | None, int | None, int | None, QualityTier]:
    """Synthesise a Phase-1 quality claim for a SoundCloud track.

    A ``downloadable`` track exposes the uploader's *original* file — possibly
    lossless WAV/FLAC, format unknowable until fetched — so it is claimed
    optimistically as CD-tier lossless FLAC. A non-downloadable track only has
    the transcoded stream ceiling: Go+ 256 kbps AAC. Both claims are corrected
    by ``quality_engine.probe()`` after the bytes land. Returns
    ``(format, bit_depth, sample_rate_hz, bitrate_kbps, tier)``.
    """
    if downloadable:
        return ("flac", 16, 44100, None, QualityTier.CD_LOSSLESS)
    return ("aac", None, 48000, 256, QualityTier.HIGH_LOSSY)


__all__ = ["SoundCloudProvider"]
