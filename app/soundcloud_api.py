"""
SoundCloud API client — playlists, likes, and per-artist catalogue.

Uses the auth_token (stored in the OS keyring via `keyring.get_password`) for
authenticated requests. Public API only (`api.soundcloud.com`).

Resilience:
  - 429 backoff driven by the response body (`errors[].meta.reset_time`). The
    public API documents no `Retry-After` header, so the body is the real signal.
  - AuthExpiredError on 401/403, and on 404 only where a 404 genuinely means auth
    (`/me`). Artist endpoints pass `auth_404=False` and get NotFoundError instead,
    because a deleted / private / renamed artist legitimately 404s.
  - One shared `_sc_paginate` for every `linked_partitioning` cursor walk.
    `offset` is deprecated across the API and is no longer sent.
  - Dead/null track filtering.

ToU guardrails (owner decision — docs/research/implement/inprogress_library-artist-hub.md):
  - Catalogue fetches are user-initiated per artist. Nothing is pre-fetched.
  - Every fetch takes a `CallBudget`: a hard per-run call cap that stops the walk
    and reports `truncated`, logged as `op=artist_sc_fetch … calls=N`.
  - No response caching in this module — caching belongs in the sidecar with a TTL.
    The fetches used to be `@lru_cache`d on the OAuth token, which froze background
    syncs (new uploads never appeared) and pinned the token as a process-lifetime
    cache key.

The OAuth token is never logged — not at INFO, not at DEBUG, not redacted, and
never as a cache key.
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import urlparse, urlsplit, urlunsplit

import requests

logger = logging.getLogger(__name__)

# SECURITY: Client ID is read from the SOUNDCLOUD_CLIENT_ID env var (set in .env).
# We never ship hardcoded credentials in the source — see .env.example for setup.
# If the env var is missing, the scraper below tries to extract a public web-
# player ID from soundcloud.com at runtime (cached in memory only).

# ──────────────────────────────────────────────────────────────────────────────
# Dynamic Client ID Scraper
# ──────────────────────────────────────────────────────────────────────────────

_DYNAMIC_CLIENT_ID: str | None = None
_DYNAMIC_CLIENT_ID_EXPIRES: float = 0.0


def get_sc_client_id() -> str:
    """
    Resolve a valid SoundCloud client_id. Resolution order:
      1. SOUNDCLOUD_CLIENT_ID environment variable (preferred — set in .env).
      2. In-memory cache from a previous successful scrape (1-hour TTL).
      3. Live scrape of soundcloud.com to extract the public web-player ID.

    Raises RuntimeError if all three fail — we never silently fall back to a
    hardcoded ID, because that would (a) leak a fingerprint to SoundCloud and
    (b) couple this codebase to a single shared client_id that could be
    revoked at any time.
    """
    global _DYNAMIC_CLIENT_ID, _DYNAMIC_CLIENT_ID_EXPIRES
    now = time.time()

    env_id = os.environ.get("SOUNDCLOUD_CLIENT_ID")
    if env_id:
        return env_id

    # Pre-checks: use cached ID if still valid
    if _DYNAMIC_CLIENT_ID and now < _DYNAMIC_CLIENT_ID_EXPIRES:
        return _DYNAMIC_CLIENT_ID

    # STEALTH HEADERS: Mimic a standard desktop Chrome browser to bypass simple bot checks
    stealth_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,de;q=0.8",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

    try:
        logger.info("[SC Scraper] Attempting to scrape dynamic client_id from soundcloud.com...")

        # Fast timeout (5s) to avoid stalling the backend if SC is hanging or proxying via Cloudflare challenge
        resp = requests.get("https://soundcloud.com", headers=stealth_headers, timeout=5.0)

        logger.info(
            f"[SC Scraper] Main page status: {resp.status_code}, HTML length: {len(resp.text)} bytes"
        )
        resp.raise_for_status()

        # Find script tags: <script crossorigin src="https://a-v2.sndcdn.com/assets/49-8c9df1fb.js">
        script_urls = re.findall(r'<script crossorigin src="([^"]+)"></script>', resp.text)
        if not script_urls:
            # Fallback regex if SC changes their markup
            script_urls = re.findall(r'src="([^"]+?sndcdn\.com/assets/[^"]+?\.js)"', resp.text)

        logger.info(f"[SC Scraper] Found {len(script_urls)} .js bundle links to scan.")

        # ROBUST REGEX: allows spaces between client_id, colon, and quotes, matches single or double quotes
        regex_pattern = r'client_id\s*:\s*["\']([a-zA-Z0-9]{32})["\']'

        # Iterate scripts looking for the 32-character client_id
        for url in script_urls:
            try:
                js_resp = requests.get(url, headers=stealth_headers, timeout=5.0)
                logger.debug(f"[SC Scraper] Scanning script: {url} (Status: {js_resp.status_code})")
            except Exception as e_script:
                logger.warning(
                    f"[SC Scraper] Skipped script {url} due to network error: {e_script}"
                )
                continue

            if js_resp.status_code == 200:
                match = re.search(regex_pattern, js_resp.text)
                if match:
                    new_id = match.group(1)
                    _DYNAMIC_CLIENT_ID = new_id
                    _DYNAMIC_CLIENT_ID_EXPIRES = now + 3600  # cache 1 hour
                    logger.info(
                        f"[SC Scraper] SUCCESS! Fetched dynamic client_id: {_DYNAMIC_CLIENT_ID}"
                    )
                    return _DYNAMIC_CLIENT_ID
                else:
                    logger.debug(f"[SC Scraper] No client_id found in script: {url}")

        logger.warning("[SC Scraper] Regex found no client_id in any JS bundles.")

    except requests.exceptions.HTTPError as he:
        logger.error(
            f"[SC Scraper] Blocked by SC (Status {he.response.status_code}). Likely Cloudflare Challenge."
        )
    except requests.exceptions.Timeout:
        logger.error("[SC Scraper] Timeout after 5 seconds while reaching soundcloud.com")
    except Exception as e:
        logger.error(f"[SC Scraper] Unexpected error: {e}")

    # No hardcoded fallback by design — see module docstring. The user must
    # either provide their own SOUNDCLOUD_CLIENT_ID in .env, or accept that
    # SC public endpoints are unreachable when the scrape fails.
    raise RuntimeError(
        "Could not resolve a SoundCloud client_id. "
        "Set SOUNDCLOUD_CLIENT_ID in your .env file (see .env.example), "
        "or check your network connection to soundcloud.com."
    )


# SoundCloud API base URL.
# All endpoints use:  Authorization: OAuth <access_token>  +  ?client_id=<SC_CLIENT_ID>
SC_API_BASE = "https://api.soundcloud.com"

# Page size for collection endpoints. 200 is the documented maximum (default 50).
SC_PAGE_LIMIT = 200

# Page size for /users/{urn}/related — one hop, one page by default (ToU guardrail).
SC_RELATED_LIMIT = 50

# Polite spacing between pages of the same walk.
SC_PAGE_SLEEP_SECONDS = 0.3

# Last-resort stop for a cursor walk with no CallBudget: SoundCloud handing back
# a self-referential next_href would otherwise spin the sidecar forever.
SC_MAX_PAGES = 100

# Hard per-run call cap when a caller does not supply its own budget.
# 25 pages of 200 items covers a 5000-track artist; anything past that is a crawl.
SC_DEFAULT_CALL_BUDGET = 25

# Never sleep longer than this on a 429, whatever the server asks for.
SC_MAX_BACKOFF_SECONDS = 300.0

# Hosts accepted by resolve_user(). Anything else is refused before a request is
# made — /resolve takes a caller-supplied URL, so it is an SSRF surface.
_SC_RESOLVE_HOSTS = ("soundcloud.com", "www.soundcloud.com", "m.soundcloud.com")

_PERMALINK_RE = re.compile(r"^[A-Za-z0-9_-]{1,255}$")

# The normalised track contract between this client and the catalogue classifier.
SC_TRACK_FIELDS: tuple[str, ...] = (
    "sc_id",
    "title",
    "permalink_url",
    "duration_ms",
    "uploader_urn",
    "uploader_name",
    "genre",
    "tag_list",
    "access",
    "streamable",
    "sharing",
    "downloadable",
    "created_at",
    "artwork_url",
)

SC_ARTIST_FIELDS: tuple[str, ...] = (
    "urn",
    "username",
    "permalink_url",
    "track_count",
    "followers_count",
    "avatar_url",
)

# ──────────────────────────────────────────────────────────────────────────────
# Custom Exceptions
# ──────────────────────────────────────────────────────────────────────────────


class AuthExpiredError(Exception):
    """Raised when the SoundCloud OAuth token is invalid or has expired."""

    pass


class RateLimitError(Exception):
    """Raised when the API rate limit is exceeded and retries are exhausted."""

    pass


class NotFoundError(Exception):
    """Raised when a SoundCloud resource is really gone (404), not an auth problem.

    A deleted, private or renamed artist 404s legitimately — raising
    AuthExpiredError there pops a bogus "please log in again" per dead artist.
    """

    pass


# ──────────────────────────────────────────────────────────────────────────────
# Per-run call budget (ToU guardrail) + result type that reports truncation
# ──────────────────────────────────────────────────────────────────────────────


@dataclass
class CallBudget:
    """Hard cap on HTTP calls for one user-initiated run.

    One `spend()` = one page fetch. Network-error and 429 retries inside `_sc_get`
    are not counted separately: they are the same logical call.
    """

    limit: int = SC_DEFAULT_CALL_BUDGET
    used: int = 0
    label: str = ""

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    @property
    def exhausted(self) -> bool:
        return self.used >= self.limit

    def try_spend(self) -> bool:
        """Consume one call. Returns False when the cap is already reached."""
        if self.exhausted:
            logger.warning(
                "op=artist_sc_budget label=%s state=exhausted limit=%d used=%d",
                self.label or "unlabelled",
                self.limit,
                self.used,
            )
            return False
        self.used += 1
        return True


class SCResultList(list):
    """A plain list that also reports how the walk ended.

    Callers that only iterate keep working; callers that must honour the ToU cap
    read `truncated` / `stop_reason` instead of guessing from the length.
    """

    def __init__(
        self,
        items: list | None = None,
        *,
        truncated: bool = False,
        stop_reason: str = "",
        calls_used: int = 0,
    ) -> None:
        super().__init__(items or [])
        self.truncated = truncated
        self.stop_reason = stop_reason
        self.calls_used = calls_used


# ──────────────────────────────────────────────────────────────────────────────
# Rate-Limited HTTP helper
# ──────────────────────────────────────────────────────────────────────────────


def _get_proxy() -> dict | None:
    """
    Read the HTTP proxy URL from app settings (persisted in settings.json).
    Returns a requests-compatible proxies dict, or None if no proxy is configured.
    Used by all SoundCloud API calls so corporate firewall users can route traffic.
    """
    try:
        from .services import SettingsManager

        proxy_url = (SettingsManager.load() or {}).get("http_proxy", "").strip()
        if proxy_url:
            return {"http": proxy_url, "https": proxy_url}
    except Exception as exc:
        logger.debug("[SC] _get_proxy: could not read settings: %s", exc)
    return None


def _parse_reset_time(value: Any, now: float) -> float | None:
    """Turn a 429 body's `reset_time` into seconds-to-wait.

    SoundCloud's own examples show an absolute timestamp, but the field is typed
    loosely in the spec, so accept epoch-seconds, epoch-milliseconds, an ISO-8601
    instant, or a plain delta. Returns None when the value is unusable.
    """
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        seconds = float(value)
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            seconds = float(text)
        except ValueError:
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                logger.debug("[SC] 429 reset_time not parseable: %r", text)
                return None
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return max(0.0, parsed.timestamp() - now)

    if seconds > 1e12:  # epoch milliseconds
        seconds /= 1000.0
    if seconds > 1e9:  # epoch seconds
        return max(0.0, seconds - now)
    return max(0.0, seconds)


def _rate_limit_wait(resp: requests.Response, fallback: float) -> float:
    """Seconds to wait after a 429.

    Order: `Retry-After` header (undocumented but honoured if present), then the
    documented body shape `errors[].meta.reset_time`, then the caller's fallback.
    Clamped to SC_MAX_BACKOFF_SECONDS so a bad server value cannot hang a run.
    """
    header = resp.headers.get("Retry-After")
    if header:
        try:
            return min(max(float(header), 0.0), SC_MAX_BACKOFF_SECONDS)
        except (TypeError, ValueError):
            logger.debug("[SC] 429 Retry-After not numeric: %r", header)

    try:
        body = resp.json()
    except (ValueError, AttributeError):
        body = None

    if isinstance(body, dict):
        now = time.time()
        for err in body.get("errors") or []:
            meta = err.get("meta") if isinstance(err, dict) else None
            if not isinstance(meta, dict):
                continue
            wait = _parse_reset_time(meta.get("reset_time"), now)
            if wait is not None:
                logger.warning(
                    "[SC] 429 rate_limit=%s reset_time=%s → waiting %.1fs",
                    meta.get("rate_limit"),
                    meta.get("reset_time"),
                    min(wait, SC_MAX_BACKOFF_SECONDS),
                )
                return min(wait, SC_MAX_BACKOFF_SECONDS)

    return min(max(fallback, 0.0), SC_MAX_BACKOFF_SECONDS)


def _log_url(url: str) -> str:
    """A URL safe to log: path only, query dropped.

    ``_sc_paginate`` follows a SERVER-SUPPLIED ``next_href``. SoundCloud's documented
    cursor does not carry credentials, but the repo rule on the OAuth token is absolute
    — not at INFO, not at DEBUG, not redacted — and an untrusted remote URL is no place
    to make an exception. The query string is never needed to read a log line.
    """
    try:
        split = urlsplit(str(url))
    except ValueError:
        return "<unparseable url>"
    base = urlunsplit((split.scheme, split.netloc, split.path, "", ""))
    return f"{base}?…" if split.query else base


def _sc_get(
    url: str,
    headers: dict,
    params: dict | None = None,
    max_retries: int = 3,
    timeout: int = 15,
    *,
    auth_404: bool = True,
) -> requests.Response:
    """
    Perform a GET request against the SoundCloud API with automatic 429 backoff.

    On a 429 response:
      - Waits per `_rate_limit_wait` (body `reset_time` — there is no documented
        `Retry-After` header) and retries up to `max_retries` times.
    On 401/403:
      - Raises AuthExpiredError immediately.
    On 404:
      - `auth_404=True` (default) → AuthExpiredError. SoundCloud returns 404 on
        /me when the client_id is invalid or the token doesn't match the account,
        so on those endpoints a 404 really is an auth failure.
      - `auth_404=False` → NotFoundError. Artist endpoints pass this: a deleted,
        private or renamed artist 404s legitimately and must not be reported as
        an expired login.
    """
    delay = 1.0
    for attempt in range(max_retries + 1):
        try:
            logger.debug("[SC] GET Request to %s (params: %s)", _log_url(url), params)
            resp = requests.get(
                url, headers=headers, params=params, timeout=timeout, proxies=_get_proxy()
            )
            logger.info("[SC] Response %s from %s", resp.status_code, _log_url(url))
        except requests.RequestException as exc:
            logger.warning(f"[SC] Network error on attempt {attempt + 1}: {exc}")
            if attempt >= max_retries:
                raise
            time.sleep(delay)
            delay *= 2
            continue

        if resp.status_code == 200:
            # EC10: Catch malformed/non-JSON responses from SoundCloud
            try:
                resp.json()  # Validate JSON parsability before returning
                # logger.debug(f"[SC] JSON Response snippet: {str(resp_json)[:200]}...")
                return resp
            except ValueError as json_err:
                logger.error(
                    f"[SC] Malformed JSON from {url}: {json_err}. Raw body snippet: {resp.text[:200]}"
                )
                raise ValueError(
                    f"SoundCloud returned non-JSON (status 200). Raw: {resp.text[:120]}"
                ) from json_err

        if resp.status_code in (401, 403):
            logger.error(
                f"[SC] Auth error {resp.status_code}: token invalid or expired. Body: {resp.text[:200]}"
            )
            raise AuthExpiredError(
                f"SoundCloud auth token is invalid or expired (HTTP {resp.status_code})."
            )

        if resp.status_code == 404:
            if auth_404:
                logger.error(
                    f"[SC] 404 Not Found from SoundCloud for {url}. Body: {resp.text[:200]}"
                )
                raise AuthExpiredError(
                    f"SoundCloud returned 404 for {url}. Token or client_id may be invalid."
                )
            logger.info("[SC] 404 — resource gone (deleted, private or renamed): %s", url)
            raise NotFoundError(f"SoundCloud resource not found: {url}")

        if resp.status_code == 429:
            retry_after = _rate_limit_wait(resp, delay * 2)
            logger.warning(
                "[SC] 429 Too Many Requests. Retrying in %.1fs (attempt %d/%d).",
                retry_after,
                attempt + 1,
                max_retries,
            )
            if attempt >= max_retries:
                raise RateLimitError("SoundCloud rate limit exceeded. Please try again later.")
            time.sleep(retry_after)
            delay = min(delay * 2, 60)
            continue

        # All other non-200 codes
        logger.error(f"[SC] Unexpected status {resp.status_code} for {url}: {resp.text[:200]}")
        resp.raise_for_status()

    raise RateLimitError("Max retries reached.")


def _sc_paginate(
    url: str,
    headers: dict,
    params: dict | None = None,
    *,
    max_items: int | None = None,
    budget: CallBudget | None = None,
    auth_404: bool = True,
    timeout: int = 15,
    page_sleep: float = SC_PAGE_SLEEP_SECONDS,
    max_pages: int | None = None,
) -> tuple[list, bool, str]:
    """Walk a `linked_partitioning` collection and return (items, truncated, reason).

    The single cursor walk for the whole client — `get_playlists` and `get_likes`
    each hand-rolled this loop with divergent bugs. Handles both response shapes
    (bare list, or `{"collection": [...], "next_href": ...}`), never sends the
    deprecated `offset`, and stops early on `max_items` or an exhausted
    `CallBudget`, reporting which one via the `reason`.
    """
    items: list = []
    truncated = False
    reason = ""
    next_url: str | None = url
    page_params = dict(params or {})
    page_cap = SC_MAX_PAGES if max_pages is None else max_pages
    pages = 0

    while next_url:
        if pages >= page_cap:
            logger.warning("[SC] paginate: page cap %d reached for %s — stopping.", page_cap, url)
            truncated, reason = True, "max_pages"
            break
        if budget is not None and not budget.try_spend():
            truncated, reason = True, "budget"
            break

        pages += 1
        resp = _sc_get(next_url, headers, page_params, timeout=timeout, auth_404=auth_404)
        data = resp.json()

        if isinstance(data, list):
            collection: Any = data
            next_url = None
        elif isinstance(data, dict):
            collection = data.get("collection", [])
            next_url = data.get("next_href")  # already carries its own query string
            page_params = {}
        else:
            logger.warning("[SC] paginate: unexpected payload type %s — stopping.", type(data))
            break

        if not isinstance(collection, list):
            logger.warning(
                "[SC] paginate: collection is %s, not a list — stopping.", type(collection)
            )
            break

        items.extend(collection)

        if max_items is not None and len(items) >= max_items:
            over = len(items) > max_items
            del items[max_items:]
            truncated = bool(next_url) or over
            reason = "max_items" if truncated else ""
            break

        if next_url:
            time.sleep(page_sleep)

    return items, truncated, reason


def user_urn(user: str | int) -> str:
    """Build `soundcloud:users:{id}`. Numeric ids are deprecated API-wide (2025-04-23)."""
    text = str(user).strip()
    if text.startswith("soundcloud:users:"):
        return text
    if not text:
        raise ValueError("Empty SoundCloud user id.")
    return f"soundcloud:users:{text}"


def _keeps_cache_clear(func):
    """Keep a no-op `.cache_clear()` on fetches that used to be `@lru_cache`d.

    `app/main.py` still calls `SoundCloudPlaylistAPI.get_playlists.cache_clear()`
    before every fetch. The cache is gone (it was keyed on the OAuth token), but
    the attribute has to survive or that route 500s. Remove the shim once the
    caller does.
    """
    func.cache_clear = lambda: None
    return func


# ──────────────────────────────────────────────────────────────────────────────
# SoundCloud Playlist API
# ──────────────────────────────────────────────────────────────────────────────


class SoundCloudPlaylistAPI:
    """Fetches playlist and track data from SoundCloud."""

    @staticmethod
    def _get_headers(auth_token: str | None = None) -> dict:
        headers = {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        if auth_token:
            headers["Authorization"] = f"OAuth {auth_token}"
        return headers

    @staticmethod
    def _resolve_user_id(auth_token: str) -> int:
        """Resolve the current user's numeric ID from their auth token.
        Raises AuthExpiredError on 401/403/404."""
        resp = _sc_get(
            f"{SC_API_BASE}/me",
            headers=SoundCloudPlaylistAPI._get_headers(auth_token),
            params={} if auth_token else {"client_id": get_sc_client_id()},
            timeout=10,
        )
        data = resp.json()
        user_id = data.get("id")
        if not user_id:
            raise ValueError("Could not determine user ID from /me endpoint.")
        return user_id

    @staticmethod
    def get_user_profile(auth_token: str) -> dict:
        """
        Fetch the authenticated user's public profile from SoundCloud.
        Returns a dict with: id, username, full_name, avatar_url, permalink_url,
        followers_count, track_count.

        EC1: If avatar_url is null/missing, the key is still present (value=None).
             The frontend must render a fallback (initials/icon) in that case.
        EC2: Raises AuthExpiredError on 401/403/404 from the SC API.
        """
        resp = _sc_get(
            f"{SC_API_BASE}/me",
            headers=SoundCloudPlaylistAPI._get_headers(auth_token),
            params={} if auth_token else {"client_id": get_sc_client_id()},
            timeout=10,
        )
        data = resp.json()
        return {
            "id": data.get("id"),
            "username": data.get("username") or data.get("permalink") or "Unknown",
            "full_name": data.get("full_name") or "",
            "avatar_url": data.get("avatar_url"),  # may be None — frontend handles fallback
            "permalink_url": data.get("permalink_url") or "",
            "followers_count": data.get("followers_count", 0),
            "track_count": data.get("track_count", 0),
        }

    @staticmethod
    def _normalize_track(raw: dict | None) -> dict | None:
        """
        Convert a raw SoundCloud track object into our canonical format.
        Returns None for dead/deleted tracks (Criterion 9, 12).
        """
        if not raw or not isinstance(raw, dict):
            return None
        track_id = raw.get("id")
        if not track_id:
            return None

        title = raw.get("title", "")
        user = raw.get("user", {})
        artist = user.get("username", "") if isinstance(user, dict) else ""

        # A track with an id but no title + no user is likely deleted
        is_deleted = not title and not artist
        if is_deleted:
            logger.debug(f"[SC] Skipping deleted/empty track id={track_id}")
            return None

        # download_url is present in the API response when downloadable=True.
        # It points to the official /tracks/{id}/download endpoint.
        # We include it here so callers don't need a second API round-trip.
        return {
            "id": track_id,
            "title": title,
            "artist": artist,
            "duration": raw.get("duration", 0),
            "permalink_url": raw.get("permalink_url", ""),
            "artwork_url": raw.get("artwork_url"),
            "downloadable": raw.get("downloadable", False),
            "download_url": raw.get("download_url"),  # None when not downloadable
        }

    @staticmethod
    def resolve_track_from_url(permalink_url: str, auth_token: str | None = None) -> dict | None:
        """
        Resolve a SoundCloud permalink URL to a normalized track dict.

        Uses the /resolve endpoint to look up any SC URL (track, playlist, user).
        Returns a normalized track dict (same shape as _normalize_track) when the
        URL resolves to a track, or None on failure / if it resolves to a non-track.

        This is used by the download endpoint when the caller provides only a URL
        (rather than pre-resolved track metadata), so the backend can check
        'downloadable' before making any download attempt.
        """
        headers = SoundCloudPlaylistAPI._get_headers(auth_token)
        params: dict = {"url": permalink_url}
        if not auth_token:
            params["client_id"] = get_sc_client_id()

        logger.info("[SC] Resolving URL: %s", permalink_url)
        try:
            resp = _sc_get(
                f"{SC_API_BASE}/resolve",
                headers=headers,
                params=params,
                timeout=10,
            )
            data = resp.json()

            # /resolve returns the resource directly; check it's a track
            kind = data.get("kind", "")
            if kind != "track":
                logger.warning(
                    "[SC] resolve_track_from_url: kind=%s (not a track) for %s", kind, permalink_url
                )
                return None

            return SoundCloudPlaylistAPI._normalize_track(data)

        except AuthExpiredError:
            raise
        except Exception as exc:
            logger.error("[SC] resolve_track_from_url failed for %s: %s", permalink_url, exc)
            return None

    @staticmethod
    @_keeps_cache_clear
    def get_playlists(auth_token: str) -> list[dict]:
        """
        Fetch ALL playlists for the authenticated user.
        Follows next_href pagination until exhausted (Criterion 8).
        Raises AuthExpiredError on token problems (Criterion 5).
        """
        urn = user_urn(SoundCloudPlaylistAPI._resolve_user_id(auth_token))
        headers = SoundCloudPlaylistAPI._get_headers(auth_token)

        params: dict[str, Any] = {"limit": SC_PAGE_LIMIT, "linked_partitioning": "true"}
        if not auth_token:
            params["client_id"] = get_sc_client_id()

        logger.info("[SC] Starting playlist fetch for %s", urn)
        raw_playlists, truncated, reason = _sc_paginate(
            f"{SC_API_BASE}/users/{urn}/playlists", headers, params
        )

        playlists: list[dict] = []
        for pl in raw_playlists:
            if not isinstance(pl, dict) or not pl.get("id"):
                continue
            tracks_raw = pl.get("tracks") or []
            # No hard limit — frontend handles scrolling
            track_preview = [
                t
                for t in (SoundCloudPlaylistAPI._normalize_track(tr) for tr in tracks_raw)
                if t is not None
            ]
            playlists.append(
                {
                    "id": pl.get("id"),
                    "title": pl.get("title", "Untitled"),
                    "track_count": pl.get("track_count", len(tracks_raw)),
                    "duration": pl.get("duration", 0),
                    "artwork_url": pl.get("artwork_url")
                    or (tracks_raw[0].get("artwork_url") if tracks_raw else None),
                    "permalink_url": pl.get("permalink_url", ""),
                    "created_at": pl.get("created_at", ""),
                    "is_public": pl.get("sharing", "public") != "private",
                    "tracks": track_preview,
                }
            )

        logger.info(
            "[SC] Fetched %d playlists for %s (truncated=%s reason=%s).",
            len(playlists),
            urn,
            truncated,
            reason or "-",
        )
        return playlists

    @staticmethod
    @_keeps_cache_clear
    def get_likes(auth_token: str, max_tracks: int = 500) -> dict:
        """
        Fetch user's liked tracks as a virtual playlist.
        Paginates until max_tracks reached or list exhausted (Criterion 8).
        Raises AuthExpiredError on token problems (Criterion 5).

        Uses `/users/{urn}/likes/tracks`; `/users/{id}/favorites` is deprecated
        in the public API spec.
        """
        urn = user_urn(SoundCloudPlaylistAPI._resolve_user_id(auth_token))
        headers = SoundCloudPlaylistAPI._get_headers(auth_token)

        params: dict[str, Any] = {
            "limit": min(SC_PAGE_LIMIT, max_tracks),
            "linked_partitioning": "true",
        }
        if not auth_token:
            params["client_id"] = get_sc_client_id()

        raw_items, _truncated, _reason = _sc_paginate(
            f"{SC_API_BASE}/users/{urn}/likes/tracks", headers, params, max_items=max_tracks
        )

        tracks: list[dict] = []
        for item in raw_items:
            normalized = SoundCloudPlaylistAPI._normalize_track(_unwrap_track(item))
            if normalized:
                tracks.append(normalized)

        logger.info("[SC] Fetched %d liked tracks for %s.", len(tracks), urn)
        return {
            "id": "likes",
            "title": "❤️ Liked Tracks",
            "track_count": len(tracks),
            "duration": sum(t.get("duration", 0) for t in tracks),
            "artwork_url": tracks[0].get("artwork_url") if tracks else None,
            "permalink_url": "",
            "created_at": "",
            "is_public": False,
            "is_likes": True,
            "tracks": tracks,
        }

    @staticmethod
    def get_full_playlist_tracks(playlist_id: int | str, auth_token: str) -> list[dict]:
        """
        Fetch ALL tracks for a specific playlist (not just the 20-track preview).
        Uses full representation and paginates (Criterion 8).
        """
        headers = SoundCloudPlaylistAPI._get_headers(auth_token)
        try:
            params = {"representation": "full"}
            if not auth_token:
                params["client_id"] = get_sc_client_id()
            resp = _sc_get(
                f"{SC_API_BASE}/playlists/{playlist_id}", headers=headers, params=params, timeout=20
            )
        except AuthExpiredError:
            raise
        except Exception as exc:
            logger.error(f"[SC] get_full_playlist_tracks({playlist_id}): {exc}")
            return []

        data = resp.json()
        if not isinstance(data, dict):
            logger.warning(f"[SC] Unexpected payload for playlist {playlist_id}.")
            return []

        raw_tracks = data.get("tracks", [])
        if not isinstance(raw_tracks, list):
            logger.warning(f"[SC] tracks field is not a list for playlist {playlist_id}.")
            return []

        result = []
        for raw in raw_tracks:
            normalized = SoundCloudPlaylistAPI._normalize_track(raw)
            if normalized:
                result.append(normalized)

        logger.info(
            f"[SC] get_full_playlist_tracks({playlist_id}): {len(result)} valid tracks (filtered from {len(raw_tracks)})."
        )
        return result


# ──────────────────────────────────────────────────────────────────────────────
# Artist catalogue — /users/{urn}/tracks, /reposts/tracks, /related, /resolve
# ──────────────────────────────────────────────────────────────────────────────


def _unwrap_track(item: Any) -> dict | None:
    """Return the track object, unwrapping `{"type": …, "track": {…}}` envelopes."""
    if not isinstance(item, dict):
        return None
    inner = item.get("track")
    return inner if isinstance(inner, dict) else item


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_str(value: Any) -> str:
    return "" if value is None else str(value)


def _artist_headers(auth_token: str) -> dict:
    """Headers for the artist endpoints. A token is required — no anonymous path.

    The catalogue is only ever fetched for an artist the user selected while
    logged in. Falling back to a scraped public client_id would return a
    different, partial view and quietly misreport what an artist has released.
    """
    if not auth_token:
        raise AuthExpiredError(
            "SoundCloud login required: the artist catalogue needs an authenticated session."
        )
    return SoundCloudPlaylistAPI._get_headers(auth_token)


def normalize_catalogue_track(raw: Any) -> dict | None:
    """Raw SC track → the normalised contract dict (`SC_TRACK_FIELDS`), or None.

    None means "not a usable track object" (no id, or an id with neither title
    nor uploader = a deleted stub). Missing fields become "" / 0 / False — never
    a guessed value. In particular `access` stays "" when the payload omits it,
    so a caller can never mistake "unknown" for "playable".
    """
    if not isinstance(raw, dict):
        return None

    track_id = raw.get("id")
    urn = _as_str(raw.get("urn"))
    if not track_id and not urn.startswith("soundcloud:tracks:"):
        return None

    raw_user = raw.get("user")
    user: dict = raw_user if isinstance(raw_user, dict) else {}
    uploader_name = _as_str(user.get("username"))
    title = _as_str(raw.get("title"))
    if not title and not uploader_name:
        logger.debug("[SC] Skipping deleted/empty track id=%s", track_id)
        return None

    uploader_id = user.get("urn") or user.get("id") or raw.get("user_id")

    return {
        "sc_id": urn if urn.startswith("soundcloud:tracks:") else f"soundcloud:tracks:{track_id}",
        "title": title,
        "permalink_url": _as_str(raw.get("permalink_url")),
        "duration_ms": _as_int(raw.get("duration")),
        "uploader_urn": user_urn(uploader_id) if uploader_id else "",
        "uploader_name": uploader_name,
        "genre": _as_str(raw.get("genre")),
        "tag_list": _as_str(raw.get("tag_list")),
        "access": _as_str(raw.get("access")),
        "streamable": bool(raw.get("streamable", False)),
        "sharing": _as_str(raw.get("sharing")),
        "downloadable": bool(raw.get("downloadable", False)),
        "created_at": _as_str(raw.get("created_at")),
        "artwork_url": _as_str(raw.get("artwork_url")),
    }


def normalize_artist(raw: Any) -> dict | None:
    """Raw SC user → `SC_ARTIST_FIELDS` dict, or None when it carries no identity."""
    if not isinstance(raw, dict):
        return None
    identity = raw.get("urn") or raw.get("id")
    if not identity:
        return None
    return {
        "urn": user_urn(identity),
        "username": _as_str(raw.get("username")) or _as_str(raw.get("permalink")),
        "permalink_url": _as_str(raw.get("permalink_url")),
        "track_count": _as_int(raw.get("track_count")),
        "followers_count": _as_int(raw.get("followers_count")),
        "avatar_url": _as_str(raw.get("avatar_url")),
    }


def _fetch_track_collection(
    endpoint: str,
    label: str,
    user: str | int,
    auth_token: str,
    *,
    max_items: int | None,
    budget: CallBudget | None,
    extra_params: dict[str, Any] | None = None,
) -> SCResultList:
    """Shared walk for the two track collections. Returns normalised tracks."""
    urn = user_urn(user)
    headers = _artist_headers(auth_token)
    spent_before = budget.used if budget else 0

    params: dict[str, Any] = {
        "limit": SC_PAGE_LIMIT,
        "linked_partitioning": "true",
        # The legal gate: `preview` is a snippet and `blocked` is metadata only.
        # Without this the API defaults to "playable,preview" and snipped tracks
        # would land in the "missing" list as if they were fetchable.
        "access": "playable",
    }
    params.update(extra_params or {})

    raw_items, truncated, reason = _sc_paginate(
        f"{SC_API_BASE}/users/{urn}/{endpoint}",
        headers,
        params,
        max_items=max_items,
        budget=budget,
        auth_404=False,
    )

    tracks: list[dict] = []
    for item in raw_items:
        normalized = normalize_catalogue_track(_unwrap_track(item))
        if normalized:
            tracks.append(normalized)

    calls = (budget.used - spent_before) if budget else 0
    logger.info(
        "op=artist_sc_fetch endpoint=%s artist=%s tracks=%d calls=%d truncated=%s reason=%s",
        label,
        urn,
        len(tracks),
        calls,
        truncated,
        reason or "-",
    )
    return SCResultList(tracks, truncated=truncated, stop_reason=reason, calls_used=calls)


def get_user_tracks(
    user_urn_or_id: str | int,
    auth_token: str,
    *,
    max_items: int | None = None,
    budget: CallBudget | None = None,
) -> SCResultList:
    """An artist's OWN uploads — `GET /users/{urn}/tracks`.

    Reposts are a different path and are NOT included here (see get_user_reposts).
    Stops early on `max_items` or an exhausted `budget`; the returned list reports
    `truncated` / `stop_reason` so a partial catalogue is never presented as complete.

    Raises AuthExpiredError without a token or on 401/403, NotFoundError when the
    artist is gone (deleted / private / renamed).
    """
    return _fetch_track_collection(
        "tracks",
        "tracks",
        user_urn_or_id,
        auth_token,
        max_items=max_items,
        budget=budget,
        extra_params={"sort": "desc"},
    )


def get_user_reposts(
    user_urn_or_id: str | int,
    auth_token: str,
    *,
    max_items: int | None = None,
    budget: CallBudget | None = None,
) -> SCResultList:
    """An artist's reposted tracks — `GET /users/{urn}/reposts/tracks`.

    Separate from their own uploads by design: a repost is someone else's upload.
    Same truncation and error contract as get_user_tracks. `sort` is not sent —
    it is documented on /tracks only.
    """
    return _fetch_track_collection(
        "reposts/tracks",
        "reposts",
        user_urn_or_id,
        auth_token,
        max_items=max_items,
        budget=budget,
    )


def get_related_artists(
    user_urn_or_id: str | int,
    auth_token: str,
    *,
    max_items: int | None = SC_RELATED_LIMIT,
    budget: CallBudget | None = None,
) -> SCResultList:
    """Related artists — `GET /users/{urn}/related`. ONE hop, never transitive.

    The returned User objects already carry `track_count` / `followers_count`, so
    ranking needs no follow-up call. An empty result is normal for a niche artist
    and is returned as an empty list, not an error — the caller falls back to
    local uploader co-occurrence. A 404 (artist gone) degrades the same way.
    """
    urn = user_urn(user_urn_or_id)
    headers = _artist_headers(auth_token)
    spent_before = budget.used if budget else 0

    params: dict[str, Any] = {
        "limit": min(SC_RELATED_LIMIT, max_items or SC_RELATED_LIMIT),
        "linked_partitioning": "true",
    }

    try:
        raw_items, truncated, reason = _sc_paginate(
            f"{SC_API_BASE}/users/{urn}/related",
            headers,
            params,
            max_items=max_items,
            budget=budget,
            auth_404=False,
        )
    except NotFoundError:
        logger.info("op=artist_sc_related artist=%s result=not_found", urn)
        return SCResultList([], stop_reason="not_found", calls_used=1)

    artists: list[dict] = []
    for item in raw_items:
        normalized = normalize_artist(item)
        if normalized:
            artists.append(normalized)

    calls = (budget.used - spent_before) if budget else 0
    logger.info(
        "op=artist_sc_fetch endpoint=related artist=%s artists=%d calls=%d truncated=%s",
        urn,
        len(artists),
        calls,
        truncated,
    )
    return SCResultList(artists, truncated=truncated, stop_reason=reason, calls_used=calls)


def _to_soundcloud_url(url_or_permalink: str) -> str:
    """Accept a full SC URL or a bare permalink; refuse anything off-platform.

    /resolve takes a caller-supplied URL, so this is an SSRF surface — the host
    allowlist mirrors the downloader's.
    """
    value = (url_or_permalink or "").strip()
    if not value:
        raise ValueError("Empty SoundCloud URL or permalink.")

    if "://" in value:
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Unsupported scheme for SoundCloud resolve: {parsed.scheme!r}")
        if parsed.hostname not in _SC_RESOLVE_HOSTS:
            raise ValueError(f"Refusing to resolve a non-SoundCloud host: {parsed.hostname!r}")
        return value

    slug = value.strip("/")
    if not _PERMALINK_RE.match(slug):
        raise ValueError(f"Not a valid SoundCloud permalink: {url_or_permalink!r}")
    return f"https://soundcloud.com/{slug}"


def resolve_user(
    url_or_permalink: str,
    auth_token: str,
    *,
    budget: CallBudget | None = None,
) -> dict | None:
    """Bind an artist to a SoundCloud account — `GET /resolve`.

    Returns the `SC_ARTIST_FIELDS` dict, or None when the URL is gone, resolves to
    something that is not a user, or the call budget is exhausted (the caller owns
    the budget and can tell the cases apart via `budget.exhausted`).
    """
    target = _to_soundcloud_url(url_or_permalink)
    headers = _artist_headers(auth_token)

    if budget is not None and not budget.try_spend():
        logger.warning("op=artist_sc_resolve url=%s result=budget_exhausted", target)
        return None

    try:
        resp = _sc_get(
            f"{SC_API_BASE}/resolve",
            headers=headers,
            params={"url": target},
            timeout=10,
            auth_404=False,
        )
    except NotFoundError:
        logger.info("op=artist_sc_resolve url=%s result=not_found", target)
        return None

    data = resp.json()
    kind = data.get("kind") if isinstance(data, dict) else None
    if kind and kind != "user":
        logger.warning("op=artist_sc_resolve url=%s result=kind_%s", target, kind)
        return None

    artist = normalize_artist(data)
    if artist is None:
        logger.warning("op=artist_sc_resolve url=%s result=unusable_payload", target)
        return None

    logger.info("op=artist_sc_resolve url=%s result=ok urn=%s", target, artist["urn"])
    return artist


# ──────────────────────────────────────────────────────────────────────────────
# SoundCloud Sync Engine
# ──────────────────────────────────────────────────────────────────────────────


class SoundCloudSyncEngine:
    """Syncs SoundCloud playlists → local Rekordbox collection playlists."""

    SYNC_PREFIX = "SC_"

    def __init__(self, db_manager):
        self.db = db_manager

    def _normalize_title(self, title: str) -> str:
        return re.sub(r"[^\w\s]", "", title.lower().strip())

    def _fuzzy_match_track(self, sc_title: str, sc_artist: str, local_tracks: dict) -> str | None:
        """Find the best matching local track. Returns the local track ID or None."""
        tid, _ = self._fuzzy_match_with_score(sc_title, sc_artist, local_tracks)
        return tid

    def _fuzzy_match_with_score(self, sc_title: str, sc_artist: str, local_tracks: dict):
        """Find the best match and return (local_track_id, score). Score 0..1."""
        sc_combined = f"{sc_artist} - {sc_title}".lower()
        sc_norm_title = self._normalize_title(sc_title)
        best_match = None
        best_ratio = 0.0

        for tid, track in local_tracks.items():
            local_title = (track.get("Title") or "").lower()
            local_artist = (track.get("Artist") or "").lower()
            local_combined = f"{local_artist} - {local_title}"

            # Exact normalized title match wins immediately
            if sc_norm_title and sc_norm_title == self._normalize_title(local_title):
                return tid, 1.0

            ratio = SequenceMatcher(None, sc_combined, local_combined).ratio()
            if ratio > best_ratio and ratio >= 0.65:
                best_ratio = ratio
                best_match = tid

        return best_match, round(best_ratio, 3)

    def find_or_create_playlist(self, sc_playlist_title: str) -> str | None:
        """Find existing synced playlist or create a new one. Returns playlist ID string.
        Respects the 'sc_sync_folder_id' setting: if set, creates the playlist inside
        that local Rekordbox folder instead of ROOT.
        """
        from .services import SettingsManager

        sync_name = f"{self.SYNC_PREFIX}{sc_playlist_title}"
        for pl in self.db.playlists:
            if pl.get("Name") == sync_name:
                return str(pl.get("ID"))
        try:
            if hasattr(self.db, "create_playlist"):
                # Determine target parent folder from settings
                target_folder_id = SettingsManager.load().get("sc_sync_folder_id") or "ROOT"
                logger.info(f"[SC] Creating playlist '{sync_name}' in folder id={target_folder_id}")
                # db.create_playlist() returns a node_data dict: {"ID": str, "Name": str, ...}
                node_data = self.db.create_playlist(sync_name, parent_id=target_folder_id)
                if isinstance(node_data, dict):
                    pid = str(node_data["ID"])
                else:
                    pid = str(node_data)
                logger.info(f"[SC] Created synced playlist: {sync_name} (ID: {pid})")
                return pid
            else:
                logger.warning("[SC] Database does not support create_playlist.")
        except Exception as exc:
            logger.error(f"[SC] Failed to create playlist {sync_name}: {exc}")
        return None

    def sync_playlist(self, sc_playlist: dict, auth_token: str) -> dict:
        """
        Sync a single SoundCloud playlist to local collection.
        Handles dead tracks gracefully (Criterion 9).
        """
        title = sc_playlist.get("title", "Untitled")
        sc_id = sc_playlist.get("id")

        result = {
            "playlist_title": title,
            "sc_id": sc_id,
            "matched": 0,
            "unmatched": 0,
            "already_synced": 0,
            "added": 0,
            "dead_tracks": 0,
            "errors": [],
        }

        # Fetch full track list
        if sc_playlist.get("is_likes"):
            sc_tracks = sc_playlist.get("tracks", [])
        else:
            # A playlist dict without an id used to build '/playlists/None', which SC
            # answers with a 404 -> a bogus 're-login' toast.
            sc_tracks = (
                SoundCloudPlaylistAPI.get_full_playlist_tracks(sc_id, auth_token) if sc_id else []
            )

        if not sc_tracks:
            result["errors"].append("No live tracks found in playlist (all may have been deleted).")
            return result

        pid = self.find_or_create_playlist(title)
        if not pid:
            result["errors"].append("Could not create or find local playlist.")
            return result

        # Existing track IDs in the local playlist (to skip re-adds)
        existing_track_ids: set = set()
        try:
            existing = self.db.get_playlist_tracks(pid)
            existing_track_ids = {str(t.get("id", t.get("ID", ""))) for t in existing}
        except Exception:
            pass

        local_tracks = self.db.tracks if hasattr(self.db, "tracks") else {}

        for sc_track in sc_tracks:
            sc_title = sc_track.get("title", "")
            sc_artist = sc_track.get("artist", "")

            if not sc_title:
                result["dead_tracks"] += 1
                continue

            matched_tid = self._fuzzy_match_track(sc_title, sc_artist, local_tracks)
            if matched_tid:
                result["matched"] += 1
                if matched_tid in existing_track_ids:
                    result["already_synced"] += 1
                else:
                    try:
                        if hasattr(self.db, "add_track_to_playlist"):
                            self.db.add_track_to_playlist(pid, matched_tid)
                            result["added"] += 1
                        elif hasattr(self.db.active_db, "add_track_to_playlist"):
                            self.db.active_db.add_track_to_playlist(pid, matched_tid)
                            result["added"] += 1
                    except Exception as exc:
                        result["errors"].append(f"Failed to add '{sc_title}': {exc}")
            else:
                result["unmatched"] += 1

        return result

    def sync_all(self, playlists: list[dict], auth_token: str) -> list[dict]:
        """Sync all provided playlists sequentially."""
        results = []
        for pl in playlists:
            result = self.sync_playlist(pl, auth_token)
            results.append(result)
        return results

    def preview_matches(self, sc_playlist: dict, auth_token: str) -> list[dict]:
        """
        Dry-run: return per-track match details WITHOUT writing to the DB.
        Used by the Inspector Panel endpoint.
        Returns list of dicts:
          { sc_title, sc_artist, sc_url, local_id, local_title, local_artist, score, status }
          status: 'matched' | 'unmatched' | 'dead'
        """
        sc_id = sc_playlist.get("id")
        if sc_playlist.get("is_likes"):
            sc_tracks = sc_playlist.get("tracks", [])
        else:
            sc_tracks = (
                SoundCloudPlaylistAPI.get_full_playlist_tracks(sc_id, auth_token) if sc_id else []
            )

        local_tracks = self.db.tracks if hasattr(self.db, "tracks") else {}
        preview = []

        for sc_track in sc_tracks:
            sc_title = sc_track.get("title", "")
            sc_artist = sc_track.get("artist", "")

            if not sc_title:
                preview.append(
                    {
                        "sc_title": "",
                        "sc_artist": sc_artist,
                        "sc_url": sc_track.get("permalink_url", ""),
                        "local_id": None,
                        "local_title": None,
                        "local_artist": None,
                        "score": 0.0,
                        "status": "dead",
                    }
                )
                continue

            tid, score = self._fuzzy_match_with_score(sc_title, sc_artist, local_tracks)
            if tid:
                local = local_tracks[tid]
                preview.append(
                    {
                        "sc_title": sc_title,
                        "sc_artist": sc_artist,
                        "sc_url": sc_track.get("permalink_url", ""),
                        "local_id": tid,
                        "local_title": local.get("Title", ""),
                        "local_artist": local.get("Artist", ""),
                        "score": score,
                        "status": "matched",
                    }
                )
            else:
                preview.append(
                    {
                        "sc_title": sc_title,
                        "sc_artist": sc_artist,
                        "sc_url": sc_track.get("permalink_url", ""),
                        "local_id": None,
                        "local_title": None,
                        "local_artist": None,
                        "score": 0.0,
                        "status": "unmatched",
                    }
                )

        return preview
