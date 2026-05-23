"""SpotiFLAC-backed multi-service provider (subprocess wrapper around v7 CLI).

Replaces the abandoned ``SpotiFLAC`` pip-0.x package with a subprocess call to
the in-tree ``spotiflac-cli`` Go binary, which wraps the real SpotiFLAC v7
download engine (``github.com/spotbye/SpotiFLAC``, vendored under
``spotiflac-cli/spotiflac-src/``).

Architecture
------------
* ``resolve_url`` — calls the public Songlink / Odesli HTTP API directly to
  get cross-platform URLs for a Spotify track plus basic metadata (title /
  artist / cover). Builds one :class:`TrackMatch` claim per SpotiFLAC-served
  paid service Odesli linked. The real v7 backend serves **only three**
  download providers — Tidal, Qobuz and Amazon Music. The dead pip-0.x
  package falsely claimed Deezer and Apple Music; they are intentionally
  dropped here.

* ``search`` — unsupported by SpotiFLAC; always returns an empty list.

* ``fetch`` — runs ``spotiflac-cli.exe --service <svc> --spotify-id <id>
  --title --artist --album --out <dest>`` as a subprocess and parses the
  JSON result line. The CLI binary itself owns crash isolation (a panic in
  the Go backend kills the subprocess, not the Python sidecar); there is no
  ``ProcessPoolExecutor`` here any more.

Quality claims
--------------
Each per-service claim carries the service's publicly-known *optimistic*
quality ceiling (:data:`_SERVICE_CEILING`). Real per-track quality is
verified post-download by ``quality_engine`` (downstream).

Known limitation — duration
---------------------------
The Songlink / Odesli response does not expose track duration. Claims carry
``duration_s = 0.0`` as a placeholder; if the matcher's duration gate is
strict, this can suppress otherwise-valid cross-platform matches. A future
enhancement is to extend the CLI with a ``--mode metadata`` subcommand that
returns the full Spotify-side metadata block. See the research doc.

See ``docs/research/implement/accepted_downloader-unified-multi-source.md``
§ P1.5 for the original integration plan and the deviation note on the dead
pip-0.x package.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import requests
from anyio import to_thread

from .. import SourceProvider
from ..models import AudioFormat, Platform, QualityTier, TrackMatch

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Tunables
# ──────────────────────────────────────────────────────────────────────────────

#: How long a single Odesli lookup may take. Songlink rate-limits anonymous
#: requests (~10 RPM); a short timeout lets the resolver move on without
#: stalling sibling providers.
_RESOLVE_TIMEOUT_S = 30.0

#: How long a single CLI download invocation may take. Hi-Res FLAC can run
#: 30-80 MB plus the backend's per-mirror retries; 5 min covers a normal
#: Hi-Res download with headroom.
_FETCH_TIMEOUT_S = 300.0

#: Platforms the ``spotiflac-cli`` binary can fetch, in the downloader's
#: :data:`Platform` vocabulary -> SpotiFLAC v7 service key. The real v7
#: backend only has these three; Deezer and Apple Music are deliberately
#: out (contrary to what the dead pip-0.x package claimed).
_PLATFORM_TO_SERVICE: dict[Platform, str] = {
    "tidal": "tidal",
    "qobuz": "qobuz",
    "amazon": "amazon",
}

#: v7-served :data:`Platform` -> Odesli ``linksByPlatform`` key. Used to
#: surface Odesli's sibling URL when available; resolve_url claims **all
#: three** v7 services for any Spotify URL regardless, because each CLI
#: download path pivots from the Spotify ID alone (Qobuz via ISRC,
#: Tidal/Amazon via Spotify metadata). Odesli URLs are display-only.
_V7_TO_ODESLI_KEY: dict[Platform, str] = {
    "tidal": "tidal",
    "qobuz": "qobuz",
    "amazon": "amazonMusic",
}

#: Publicly-known optimistic delivery ceiling per service. Verified post-
#: download by ``quality_engine``; these claims are the upper bound.
#: ``(format, bit_depth, sample_rate_hz, bitrate_kbps, tier)``.
_SERVICE_CEILING: dict[
    Platform, tuple[AudioFormat, int | None, int | None, int | None, QualityTier]
] = {
    "qobuz": ("flac", 24, 192000, None, QualityTier.HIRES_LOSSLESS),
    "tidal": ("flac", 24, 96000, None, QualityTier.HIRES_LOSSLESS),
    "amazon": ("flac", 24, 96000, None, QualityTier.HIRES_LOSSLESS),
}

#: Songlink / Odesli endpoint — public, no auth, ~10 RPM unauthenticated.
_ODESLI_URL = "https://api.song.link/v1-alpha.1/links"

#: Spotify open-page track-ID pattern (22-char base62 segment after ``track/``).
_SPOTIFY_TRACK_RE = re.compile(r"open\.spotify\.com/track/([A-Za-z0-9]+)")


# ──────────────────────────────────────────────────────────────────────────────
# CLI binary location
# ──────────────────────────────────────────────────────────────────────────────


def _locate_cli() -> Path:
    """Find the ``spotiflac-cli`` binary in the repo.

    Default layout: ``<repo-root>/spotiflac-cli/spotiflac-cli{.exe}``. An
    override path may be set via the ``SPOTIFLAC_CLI`` env var (useful for
    tests and for packaging the binary into the Tauri bundle later).

    Raises:
        RuntimeError: the binary is not present (needs ``go build`` in
            ``spotiflac-cli/``).
    """
    override = os.environ.get("SPOTIFLAC_CLI", "").strip()
    if override:
        p = Path(override)
        if p.is_file():
            return p
        raise RuntimeError(f"SPOTIFLAC_CLI={override!r} is not a file")

    # app/downloader/providers/spotiflac.py -> repo root is parents[3].
    repo_root = Path(__file__).resolve().parents[3]
    for name in ("spotiflac-cli.exe", "spotiflac-cli"):
        candidate = repo_root / "spotiflac-cli" / name
        if candidate.is_file():
            return candidate
    raise RuntimeError(
        f"spotiflac-cli binary not found under {repo_root / 'spotiflac-cli'}; "
        "build it with `cd spotiflac-cli && go build -o spotiflac-cli.exe .`."
    )


# ──────────────────────────────────────────────────────────────────────────────
# Odesli cross-link lookup (resolve side)
# ──────────────────────────────────────────────────────────────────────────────


def _extract_spotify_id(url: str) -> str | None:
    """Pull the 22-char Spotify track ID out of an ``open.spotify.com`` URL.

    Tolerant of tracking params (``?si=...``), www-prefix and the ``intl-*``
    locale fragment Spotify sometimes inserts.
    """
    m = _SPOTIFY_TRACK_RE.search(url)
    return m.group(1) if m else None


def _odesli_lookup_sync(spotify_id: str) -> dict[str, Any] | None:
    """Blocking Songlink call — run in a worker thread via :func:`to_thread.run_sync`.

    Returns the parsed JSON dict on HTTP 200, ``None`` on any failure (network,
    non-200, non-JSON). A dead Odesli must not break the rest of resolve.
    """
    try:
        resp = requests.get(
            _ODESLI_URL,
            params={
                "url": f"https://open.spotify.com/track/{spotify_id}",
                "userCountry": "US",
            },
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=_RESOLVE_TIMEOUT_S,
        )
    except requests.RequestException as exc:
        logger.info("[spotiflac] Odesli network error for %s: %s", spotify_id, exc)
        return None
    if resp.status_code != 200:
        logger.info("[spotiflac] Odesli HTTP %s for %s", resp.status_code, spotify_id)
        return None
    try:
        return resp.json()
    except ValueError:
        logger.info("[spotiflac] Odesli non-JSON for %s", spotify_id)
        return None


# ──────────────────────────────────────────────────────────────────────────────
# CLI subprocess (fetch side)
# ──────────────────────────────────────────────────────────────────────────────


def _parse_cli_result(stdout_bytes: bytes) -> dict[str, Any]:
    """Pick the JSON result line off the CLI's stdout.

    The CLI logs progress / diagnostics above and prints a single JSON line
    last; the final non-empty line starting with ``{`` is that JSON.
    """
    text = stdout_bytes.decode("utf-8", errors="replace").strip()
    last = next(
        (ln for ln in reversed(text.splitlines()) if ln.strip().startswith("{")),
        None,
    )
    if not last:
        return {
            "success": False,
            "error": (f"spotiflac-cli produced no JSON result on stdout: {text[-200:]!r}"),
        }
    try:
        return json.loads(last)
    except json.JSONDecodeError as exc:
        return {
            "success": False,
            "error": f"spotiflac-cli JSON parse failed ({exc}): {last!r}",
        }


async def _run_cli_download(
    *,
    cli: Path,
    service: str,
    spotify_id: str,
    out_dir: Path,
    title: str,
    artist: str,
    album: str,
    tidal_api: str = "",
) -> dict[str, Any]:
    """Async subprocess invocation of ``spotiflac-cli`` for one download.

    Returns the parsed JSON ``{success, service, file?, error?}``. Never
    raises — the result dict carries the outcome.
    """
    args: list[str] = [
        str(cli),
        "--service",
        service,
        "--spotify-id",
        spotify_id,
        "--out",
        str(out_dir),
    ]
    if title:
        args += ["--title", title]
    if artist:
        args += ["--artist", artist]
    if album:
        args += ["--album", album]
    if tidal_api:
        args += ["--tidal-api", tidal_api]

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_FETCH_TIMEOUT_S)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return {
            "success": False,
            "service": service,
            "error": f"spotiflac-cli timed out after {_FETCH_TIMEOUT_S:.0f}s",
        }

    if stderr:
        # CLI logs progress + diagnostics on stderr — forward to our logger so
        # nothing is lost when a download fails.
        logger.debug(
            "[spotiflac-cli stderr] %s",
            stderr.decode("utf-8", errors="replace")[:2000],
        )
    return _parse_cli_result(stdout)


# ──────────────────────────────────────────────────────────────────────────────
# Provider
# ──────────────────────────────────────────────────────────────────────────────


class SpotiFlacProvider(SourceProvider):
    """:class:`~app.downloader.SourceProvider` over the in-tree ``spotiflac-cli``.

    One instance covers a single SpotiFLAC-served paid service so the
    orchestrator can hold one provider per platform and rank them uniformly.
    The ``platform`` property reports the bound target; ``resolve_url`` still
    surfaces *every* SpotiFLAC-served sibling-service URL Odesli finds, so any
    instance can yield all three claims for the same track.
    """

    def __init__(self, platform: Platform = "tidal") -> None:
        """Bind the provider to one served platform.

        Raises:
            ValueError: ``platform`` is not a SpotiFLAC-served service.
        """
        if platform not in _PLATFORM_TO_SERVICE:
            raise ValueError(
                f"SpotiFlacProvider cannot serve platform {platform!r}; "
                f"served: {sorted(_PLATFORM_TO_SERVICE)}"
            )
        self._platform: Platform = platform

    @property
    def platform(self) -> Platform:
        """The SpotiFLAC service this instance targets."""
        return self._platform

    async def resolve_url(self, url: str) -> list[TrackMatch]:
        """Resolve a Spotify track URL to per-service :class:`TrackMatch` claims.

        Routes through the public Songlink / Odesli API for cross-platform
        URLs and basic metadata. Returns one claim per SpotiFLAC-served
        service (Tidal / Qobuz / Amazon) Odesli linked. Quality is the
        service's optimistic ceiling — ``quality_engine`` verifies it
        post-download.

        Returns an empty list when ``url`` is not a Spotify track URL or
        Odesli failed; never raises — a dead provider must not abort a
        multi-provider resolve.
        """
        spotify_id = _extract_spotify_id(url)
        if not spotify_id:
            return []
        data = await to_thread.run_sync(_odesli_lookup_sync, spotify_id)
        if not data:
            return []

        # Pull title / artist / cover from the Spotify entity Odesli echoed back.
        title = ""
        artist = ""
        cover_url: str | None = None
        for ent in (data.get("entitiesByUniqueId") or {}).values():
            if isinstance(ent, dict) and ent.get("apiProvider") == "spotify":
                title = ent.get("title", "") or ""
                artist = ent.get("artistName", "") or ""
                cover_url = ent.get("thumbnailUrl") or None
                break

        # Canonicalise the Spotify URL via Odesli's echo when available — strips
        # tracking params, normalises locale prefix.
        spotify_url = url
        sp_link = (data.get("linksByPlatform") or {}).get("spotify") or {}
        if isinstance(sp_link, dict) and sp_link.get("url"):
            spotify_url = sp_link["url"]

        meta = {
            "title": title,
            "artist": artist,
            "cover_url": cover_url,
            "spotify_url": spotify_url,
        }

        # Each CLI download path pivots from the Spotify ID alone — Odesli's
        # sibling URLs are display-only. So claim all three v7-served services
        # regardless of whether Odesli surfaced their URL.
        links = data.get("linksByPlatform") or {}
        matches: list[TrackMatch] = []
        for platform, odesli_key in _V7_TO_ODESLI_KEY.items():
            link = links.get(odesli_key)
            svc_url = link.get("url") if isinstance(link, dict) else None
            matches.append(self._build_claim(platform, svc_url or meta["spotify_url"], meta))

        logger.debug("[spotiflac] resolve_url(%s) -> %d service claim(s)", url, len(matches))
        return matches

    async def search(self, query: str, limit: int = 5) -> list[TrackMatch]:
        """Free-form search — unsupported, always ``[]``.

        SpotiFLAC can only act on a known Spotify URL. Per the
        :class:`~app.downloader.SourceProvider` contract a provider that
        cannot search legitimately returns an empty list.
        """
        return []

    async def fetch(self, match: TrackMatch, dest_dir: Path) -> Path:
        """Download the audio for a chosen :class:`TrackMatch`.

        Runs ``spotiflac-cli`` as a subprocess, parses its JSON result. The
        Spotify origin URL is recovered from the ``#spotify=`` fragment
        :meth:`_build_claim` stamped on the claim URL — :class:`TrackMatch`
        has no escape-hatch field and is frozen.

        Raises:
            ValueError: ``match`` is not a SpotiFLAC-served claim or carries
                no Spotify origin.
            RuntimeError: the CLI failed (network, mirror down, JSON parse).
        """
        if match.platform not in _PLATFORM_TO_SERVICE:
            raise ValueError(f"SpotiFlacProvider.fetch cannot serve platform {match.platform!r}")
        dest_dir.mkdir(parents=True, exist_ok=True)

        spotify_url = _extract_spotify_origin(match.url)
        if not spotify_url:
            raise ValueError(
                f"claim for {match.platform} has no Spotify origin — "
                "cannot drive spotiflac-cli's Spotify-pivoted download"
            )
        spotify_id = _extract_spotify_id(spotify_url) or ""
        if not spotify_id:
            raise ValueError(f"could not parse Spotify track ID from {spotify_url!r}")

        cli = _locate_cli()
        service = _PLATFORM_TO_SERVICE[match.platform]

        result = await _run_cli_download(
            cli=cli,
            service=service,
            spotify_id=spotify_id,
            out_dir=dest_dir,
            title=match.title or "",
            artist=match.artist or "",
            album=match.album or "",
        )
        if not result.get("success"):
            raise RuntimeError(f"spotiflac-cli {service}: {result.get('error', 'unknown error')}")
        file_path = result.get("file") or ""
        if not file_path:
            raise RuntimeError(f"spotiflac-cli {service}: success reported but no file path")
        return Path(file_path)

    # ──────────────────────────────────────────────────────────────────────
    # Internals
    # ──────────────────────────────────────────────────────────────────────

    def _build_claim(
        self, platform: Platform, service_url: str, meta: dict[str, Any]
    ) -> TrackMatch:
        """Build one per-service :class:`TrackMatch` from the Odesli metadata.

        Quality fields are the service's optimistic ceiling
        (:data:`_SERVICE_CEILING`). The Spotify origin URL is appended to the
        claim URL as a ``#spotify=`` fragment so :meth:`fetch` can recover it.

        Duration is ``0.0`` — Odesli does not expose track duration; see the
        module docstring's "Known limitation" note.
        """
        fmt, bit_depth, sample_rate, bitrate, tier = _SERVICE_CEILING[platform]
        origin = meta.get("spotify_url", "")
        claim_url = f"{service_url}#spotify={origin}" if origin else service_url
        return TrackMatch(
            platform=platform,
            url=claim_url,
            title=meta.get("title") or "Unknown",
            artist=meta.get("artist") or "Unknown",
            duration_s=0.0,
            cover_url=meta.get("cover_url"),
            claimed_format=fmt,
            claimed_bit_depth=bit_depth,
            claimed_sample_rate_hz=sample_rate,
            claimed_bitrate_kbps=bitrate,
            quality_tier=tier,
        )


def _extract_spotify_origin(claim_url: str) -> str | None:
    """Pull the ``#spotify=`` origin fragment back out of a claim URL.

    :meth:`SpotiFlacProvider._build_claim` appends ``#spotify=<url>`` to every
    claim so :meth:`SpotiFlacProvider.fetch` can drive the CLI's
    Spotify-pivoted download. Returns ``None`` when the fragment is absent.
    """
    marker = "#spotify="
    idx = claim_url.find(marker)
    if idx == -1:
        return None
    origin = claim_url[idx + len(marker) :]
    return origin or None


__all__ = ["SpotiFlacProvider"]
