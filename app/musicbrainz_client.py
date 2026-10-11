"""musicbrainz_client — the one MusicBrainz web-service client (``/ws/2``, JSON).

Shared by every feature that asks MusicBrainz anything. The Artist Hub uses it for
profile links (owner refinement 2026-09-26); the metadata fixer's M2 and the remix
detector's M3 name MusicBrainz too and must come through here rather than open a
second client — the rate limit below is per IP, not per feature.

Policy, from ``musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting``:

* **One request per second per IP**, averaged. Going over earns 503s and, sustained,
  an IP block. Enforced here with one process-wide lock that spaces every request at
  least :data:`MIN_INTERVAL_S` after the previous one, whichever thread sent it.
* **A meaningful User-Agent with contact information is mandatory.** Anonymous or
  library-default agents are throttled into a shared pool. :data:`USER_AGENT` names
  the app and points at the repository — never at the user.
* One retry on 503, honouring ``Retry-After`` up to :data:`MAX_RETRY_AFTER_S`.

Everything this module returns is untrusted remote data. It hands back plain dicts;
URLs are validated by whoever renders or opens them (``app/artist_store/links.py``).

Sync by design: ``requests`` is already pinned, and the only callers are FastAPI
``def`` routes, which run in the threadpool.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any
from urllib.parse import urlsplit

import requests

logger = logging.getLogger(__name__)

MB_BASE = "https://musicbrainz.org/ws/2"

#: Kept in step with ``package.json``; informational only.
CLIENT_VERSION = "1.0.0"
USER_AGENT = (
    f"MusicLibraryManager/{CLIENT_VERSION} ( https://github.com/SutobeHD/LibraryManagementSystem )"
)

#: Seconds between two requests from this process. 1.0 is the documented ceiling;
#: the margin absorbs clock jitter between our timer and theirs.
MIN_INTERVAL_S = 1.1
TIMEOUT_S = 10
MAX_RETRY_AFTER_S = 5.0
MAX_SEARCH_LIMIT = 25

_MBID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")

#: Lucene syntax characters in a search term. Escaped, so an artist called
#: ``AC/DC`` or ``Kid (A)`` is a phrase, not a query.
_LUCENE_SPECIAL = re.compile(r'([+\-&|!(){}\[\]^"~*?:\\/])')

_throttle_lock = threading.Lock()
_last_request_at = 0.0


class MusicBrainzError(RuntimeError):
    """MusicBrainz answered, but not with something usable (4xx, malformed JSON)."""


class MusicBrainzUnavailable(MusicBrainzError):
    """MusicBrainz could not be reached or is shedding load (network, 5xx, 503)."""


def is_mbid(value: str) -> bool:
    return bool(_MBID_RE.match(str(value or "").strip().lower()))


def _proxies() -> dict[str, str] | None:
    """The app's configured HTTP proxy — the same setting the SoundCloud client honours."""
    try:
        from .services import SettingsManager

        proxy_url = str((SettingsManager.load() or {}).get("http_proxy", "") or "").strip()
    except (ImportError, OSError, ValueError, AttributeError) as exc:
        logger.debug("musicbrainz: proxy setting unreadable: %s", exc)
        return None
    return {"http": proxy_url, "https": proxy_url} if proxy_url else None


def _wait_for_slot() -> None:
    """Block until this process may send its next request.

    The sleep happens inside the lock on purpose: every caller queues for its own
    slot, so two threads can never fire inside the same second.
    """
    global _last_request_at
    with _throttle_lock:
        wait = MIN_INTERVAL_S - (time.monotonic() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.monotonic()


def _retry_after(resp: requests.Response) -> float:
    try:
        value = float(resp.headers.get("Retry-After", ""))
    except (TypeError, ValueError):
        value = MIN_INTERVAL_S
    return max(MIN_INTERVAL_S, min(value, MAX_RETRY_AFTER_S))


def _get(path: str, params: dict[str, Any]) -> dict[str, Any] | None:
    """GET ``/ws/2/<path>`` as JSON. None on 404; raises on everything else unusable."""
    url = f"{MB_BASE}/{path}"
    query = {**params, "fmt": "json"}
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    for attempt in range(2):
        _wait_for_slot()
        started = time.monotonic()
        try:
            resp = requests.get(
                url, params=query, headers=headers, timeout=TIMEOUT_S, proxies=_proxies()
            )
        except requests.RequestException as exc:
            logger.warning(
                "op=musicbrainz_get path=%s state=unreachable err=%s", path, type(exc).__name__
            )
            raise MusicBrainzUnavailable("MusicBrainz could not be reached.") from exc
        logger.info(
            "op=musicbrainz_get path=%s status=%d elapsed=%.2f",
            path,
            resp.status_code,
            time.monotonic() - started,
        )
        if resp.status_code == 200:
            try:
                data = resp.json()
            except ValueError as exc:
                raise MusicBrainzError("MusicBrainz returned something that is not JSON.") from exc
            if not isinstance(data, dict):
                raise MusicBrainzError("MusicBrainz returned an unexpected payload.")
            return data
        if resp.status_code == 404:
            return None
        if resp.status_code == 503 and attempt == 0:
            time.sleep(_retry_after(resp))
            continue
        if resp.status_code >= 500:
            raise MusicBrainzUnavailable(f"MusicBrainz is unavailable (HTTP {resp.status_code}).")
        raise MusicBrainzError(f"MusicBrainz refused the request (HTTP {resp.status_code}).")
    raise MusicBrainzUnavailable("MusicBrainz is rate limiting this address — try again later.")


def _artist_summary(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    mbid = str(raw.get("id") or "").strip().lower()
    name = str(raw.get("name") or "").strip()
    if not is_mbid(mbid) or not name:
        return None
    return {
        "mbid": mbid,
        "name": name,
        "sort_name": str(raw.get("sort-name") or ""),
        "disambiguation": str(raw.get("disambiguation") or ""),
        "country": str(raw.get("country") or ""),
        "type": str(raw.get("type") or ""),
    }


def _require_web_url(resource: str) -> str:
    text = str(resource or "").strip()
    parts = urlsplit(text)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"not a web URL: {resource!r}")
    return text


def artists_for_url(resource: str) -> list[dict[str, Any]]:
    """Artists MusicBrainz relates to exactly this URL (``/url?resource=…&inc=artist-rels``).

    The anchored lookup: when the user has linked an artist to a SoundCloud account,
    that profile URL either is in MusicBrainz or it is not — there is no fuzzy match
    to get wrong. Several results mean MusicBrainz itself ties the URL to several
    artists; the caller must treat that as ambiguous, not pick one.
    """
    data = _get("url", {"resource": _require_web_url(resource), "inc": "artist-rels"})
    if not data:
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rel in data.get("relations") or []:
        if not isinstance(rel, dict) or rel.get("target-type") != "artist":
            continue
        artist = _artist_summary(rel.get("artist"))
        if artist is not None and artist["mbid"] not in seen:
            seen.add(artist["mbid"])
            out.append(artist)
    return out


def artist_with_urls(mbid: str) -> dict[str, Any] | None:
    """One artist plus its URL relationships (``/artist/<mbid>?inc=url-rels``).

    ``relations`` carries ``{type, url, ended}`` per link, where ``type`` is
    MusicBrainz's relationship name (``social network``, ``official homepage``,
    ``bandcamp``, …). None when the MBID does not exist. Raises ``ValueError`` for
    something that is not an MBID — it is interpolated into the request path.
    """
    key = str(mbid or "").strip().lower()
    if not is_mbid(key):
        raise ValueError(f"not a MusicBrainz id: {mbid!r}")
    data = _get(f"artist/{key}", {"inc": "url-rels"})
    if data is None:
        return None
    summary = _artist_summary(data)
    if summary is None:
        return None
    relations: list[dict[str, Any]] = []
    for rel in data.get("relations") or []:
        if not isinstance(rel, dict):
            continue
        target = rel.get("url")
        resource = str(target.get("resource") or "") if isinstance(target, dict) else ""
        if resource:
            relations.append(
                {
                    "type": str(rel.get("type") or ""),
                    "url": resource,
                    "ended": bool(rel.get("ended")),
                }
            )
    return {**summary, "relations": relations}


def search_artists(name: str, limit: int = 5) -> list[dict[str, Any]]:
    """Artists whose name or alias matches ``name`` as a phrase, best score first.

    Candidates only. A shared name is common in electronic music, so nothing here
    may bind an artist on its own — the caller shows these for the user to confirm.
    """
    text = " ".join(str(name or "").split())
    if not text:
        return []
    phrase = _LUCENE_SPECIAL.sub(r"\\\1", text)
    size = max(1, min(int(limit), MAX_SEARCH_LIMIT))
    data = _get("artist", {"query": f'artist:"{phrase}" OR alias:"{phrase}"', "limit": size})
    if not data:
        return []
    out: list[dict[str, Any]] = []
    for raw in data.get("artists") or []:
        summary = _artist_summary(raw)
        if summary is None:
            continue
        aliases = [
            str(a.get("name") or "").strip()
            for a in (raw.get("aliases") or [])
            if isinstance(a, dict) and a.get("name")
        ]
        try:
            score = int(raw.get("score") or 0)
        except (TypeError, ValueError):
            score = 0
        out.append({**summary, "score": score, "aliases": aliases})
    out.sort(key=lambda a: -a["score"])
    return out
