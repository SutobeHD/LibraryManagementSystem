"""
SoundCloud Downloader — Dedup-aware download pipeline with two acquisition paths.

ACQUISITION PATHS
=================
1. Official download endpoint (preferred):
     GET https://api.soundcloud.com/tracks/{id}/download
   Used when the creator enabled the download button (`downloadable: true`).
   Returns the original uploaded file (WAV, FLAC, or MP3).

2. Stream reconstruction (fallback):
     GET https://api-v2.soundcloud.com/tracks/{id}  →  media.transcodings[]
   Uses the exact same signed CDN streams the SoundCloud web player plays for
   the authenticated user. Supports `progressive` (direct MP3) and `hls`
   (segment download + ffmpeg copy-mux to .m4a).

LEGAL BOUNDARIES
================
We only download what the user's own account has streaming access to via
SoundCloud's own API — we do NOT circumvent any DRM, paywall, or access
control. Explicit gates:

  - `snipped: true` transcodings are rejected (30-second preview clips for
    paywalled content the user has no full access to — saving those as full
    tracks would be misleading).
  - 401/403 responses from the transcoding-signing endpoint are respected;
    the track is skipped without retrying through another path.
  - `hq` (Go+ 256 kbps AAC) transcodings are ONLY used when SoundCloud itself
    returns them — SC only does this for accounts with an active Go+
    subscription. We never probe for higher quality than the user has paid
    for.
  - No re-encoding of HLS segments: ffmpeg is invoked with `-c copy` which
    just repackages the existing AAC/MP3 bytes into a standard container.

This matches the legal surface of the SoundCloud web player itself — it is a
Terms-of-Service question (civil contract between user and SoundCloud), not a
copyright circumvention question.

DEDUPLICATION
=============
Two-layer dedup is applied before every download:
  1. SoundCloud track ID → O(1) SQLite indexed query
  2. SHA-256 content hash after download → catches re-uploads with new IDs

FILE ORGANIZATION
=================
  {MUSIC_DIR}/SoundCloud/{sanitized_artist}/{sanitized_title}.{ext}

POST-DOWNLOAD PIPELINE
======================
  1. SHA-256 hash → content-based dedup check
  2. Registry update (status = downloaded)
  3. Background: BPM/key analysis → registry update (status = analyzed)
  4. Background: Auto-import into library + auto-sort into matching SC playlist
"""

import logging
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Dict, Optional

import requests

from .config import FFMPEG_BIN, MUSIC_DIR
from . import download_registry as registry

logger = logging.getLogger(__name__)

# Allowed audio extensions from official SC downloads
_ALLOWED_EXTS = frozenset({".mp3", ".wav", ".flac", ".aiff", ".aif", ".ogg", ".opus", ".m4a", ".aac"})

# Maximum per-component filename length (Windows MAX_PATH-safe)
_MAX_NAME_LEN = 80

# Network timeouts
_API_TIMEOUT = 15       # seconds — URL resolution / redirect
_DOWNLOAD_TIMEOUT = 180  # seconds — actual file download (large files up to ~500 MB)

# v2 API — needed for `media.transcodings[]`. The public v1 (api.soundcloud.com)
# doesn't expose the transcoding URLs used by the web player.
_V2_API_BASE = "https://api-v2.soundcloud.com"

# Browser-like User-Agent — the v2 /tracks endpoint will reject generic clients.
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Content-Type → extension mapping
_CT_MAP: Dict[str, str] = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/flac": ".flac",
    "audio/x-flac": ".flac",
    "audio/aiff": ".aiff",
    "audio/x-aiff": ".aiff",
    "audio/ogg": ".ogg",
    "audio/opus": ".opus",
    "audio/aac": ".aac",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
}


# ── Filename helpers ───────────────────────────────────────────────────────────

# M6: Windows reserved device names. Even with a safe extension, naming a
# file CON.mp3 / NUL.txt etc. fails or opens the device handle. Match the
# stem (before optional dot+ext) case-insensitively.
_WIN_RESERVED_RE = re.compile(
    r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)", re.IGNORECASE,
)


def _sanitize_name(name: str) -> str:
    """
    Convert an artist/title string to a safe filesystem component.
    Strips Windows/Unix path-illegal characters, collapses whitespace, limits length.

    M6: also prefixes Windows-reserved device names (CON, PRN, AUX, NUL,
    COM1–9, LPT1–9) with an underscore so the resulting path can never
    resolve to a device handle.
    """
    if not name or not name.strip():
        return "Unknown"
    # Replace illegal chars (Windows: < > : " / \ | ? * and control chars)
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    safe = re.sub(r'\s+', " ", safe).strip(" ._")
    if len(safe) > _MAX_NAME_LEN:
        safe = safe[:_MAX_NAME_LEN].rstrip(" ._")
    if _WIN_RESERVED_RE.match(safe):
        safe = "_" + safe
    return safe or "Unknown"


def _build_save_path(artist: str, title: str, ext: str) -> Path:
    """
    Canonical path for a downloaded track:
      {MUSIC_DIR}/SoundCloud/{sanitized_artist}/{sanitized_title}.{ext}

    Handles filename collisions by appending a numeric suffix.
    Creates the artist subdirectory if it doesn't exist.
    """
    artist_dir = MUSIC_DIR / "SoundCloud" / _sanitize_name(artist)
    artist_dir.mkdir(parents=True, exist_ok=True)
    stem = _sanitize_name(title)
    candidate = artist_dir / f"{stem}{ext}"
    counter = 1
    while candidate.exists():
        candidate = artist_dir / f"{stem} ({counter}){ext}"
        counter += 1

    # L1: Windows MAX_PATH = 260 (without the \\?\ prefix). We aim for ≤250 to
    # leave headroom for the ".part" temp-file suffix used during download.
    # If the candidate is too long, truncate the stem and retry collision-handling.
    MAX_TOTAL = 250
    if len(str(candidate)) > MAX_TOTAL:
        overflow = len(str(candidate)) - MAX_TOTAL
        # Reserve room for ext + " (NN)" collision suffix.
        new_stem_len = max(8, len(stem) - overflow - 8)
        truncated_stem = stem[:new_stem_len].rstrip(" ._") or "track"
        logger.warning(
            "[SC-DL] Path > %d chars, truncating stem %r -> %r",
            MAX_TOTAL, stem, truncated_stem,
        )
        candidate = artist_dir / f"{truncated_stem}{ext}"
        counter = 1
        while candidate.exists():
            candidate = artist_dir / f"{truncated_stem} ({counter}){ext}"
            counter += 1
    return candidate


def _guess_extension(content_type: str, url: str) -> str:
    """Determine file extension from Content-Type header, falling back to URL path."""
    ct_lower = content_type.lower()
    for mime, ext in _CT_MAP.items():
        if mime in ct_lower:
            return ext
    # Fall back: extract from URL path before the query string
    url_stem = url.split("?")[0]
    suffix = Path(url_stem).suffix.lower()
    return suffix if suffix in _ALLOWED_EXTS else ".mp3"


# ── Network helpers ────────────────────────────────────────────────────────────

def _resolve_official_download_url(
    sc_track_id: str,
    auth_token: Optional[str],
) -> Optional[str]:
    """
    Resolve the official download URL for a downloadable SC track.

    Flow:
      GET /tracks/{id}/download  →  follow redirect(s)  →  return final URL

    The final URL points to the CDN (typically AWS S3). We stream from there.
    Returns None on any network or HTTP error; caller decides what to do.
    """
    from .soundcloud_api import SC_API_BASE, get_sc_client_id

    headers: Dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }
    if auth_token:
        headers["Authorization"] = f"OAuth {auth_token}"

    params: Dict[str, str] = {} if auth_token else {"client_id": get_sc_client_id()}
    url = f"{SC_API_BASE}/tracks/{sc_track_id}/download"
    logger.info("[SC-DL] Resolving official download URL: sc_id=%s", sc_track_id)

    try:
        # H8: ``stream=True`` opens an unbuffered connection — without an
        # explicit close the underlying urllib3 connection leaks back into
        # the pool with un-drained body bytes. ``with`` guarantees release
        # via ``resp.close()`` on every exit path.
        with requests.get(
            url,
            headers=headers,
            params=params,
            allow_redirects=True,   # follow the 302 chain to the CDN
            timeout=_API_TIMEOUT,
            stream=True,            # avoid buffering the body here
        ) as resp:
            resp.raise_for_status()
            logger.info("[SC-DL] Resolved to: %s", resp.url[:120])
            return resp.url

    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else "?"
        logger.error(
            "[SC-DL] HTTP %s resolving download URL for sc_id=%s: %s",
            code, sc_track_id, exc,
        )
        return None
    except requests.RequestException as exc:
        logger.error("[SC-DL] Network error resolving download URL (sc_id=%s): %s", sc_track_id, exc)
        return None


def _normalize_track_id(raw) -> Optional[str]:
    """
    Coerce a track-id value into a clean string ID.

    Older registry rows accidentally stored the full
    ``str((tid, analysis_dict))`` representation (the historical Tuple bug),
    e.g. ``('1778088975330', {'bpm': 154.0, ...})``. We pull the first
    numeric token out of that to recover a usable ID. Returns None when
    nothing usable is found.
    """
    if raw is None:
        return None
    if isinstance(raw, (int,)):
        return str(raw)
    s = str(raw)
    if not s or s.lower() == "none":
        return None
    # Already clean (purely digits, optional underscore prefix for XML mode)
    if s.isdigit() or (s.startswith("pl_") is False and "_" not in s and " " not in s and "(" not in s):
        return s
    # Try to literal-eval in case it's a real tuple repr
    try:
        import ast
        v = ast.literal_eval(s)
        if isinstance(v, tuple) and v:
            return _normalize_track_id(v[0])
    except (ValueError, SyntaxError):
        pass
    # Fallback: regex out the first long digit run (tids are 13+ digits)
    import re
    m = re.search(r"\d{6,}", s)
    return m.group(0) if m else None


def _resolve_stream_via_transcodings(
    sc_track_id: str,
    auth_token: Optional[str],
) -> Optional[Dict]:
    """
    Resolve a signed CDN stream URL via the v2 `media.transcodings[]` array.

    This is the same mechanism the SoundCloud web player uses. We only use what
    SC itself returns for the authenticated account — no paywall circumvention,
    no DRM bypass. See module docstring for the legal boundary contract.

    Returns a dict:
        {url: <signed CDN URL>, protocol: "progressive"|"hls",
         mime_type: str, quality: "sq"|"hq"}
    Or None if:
      - The track has no usable (non-snipped) transcoding for this account.
      - SC denies access (401/403) — paywall or removed content.
      - A network error occurs.
    """
    from .soundcloud_api import get_sc_client_id

    base_headers = {"User-Agent": _UA, "Accept": "application/json"}
    auth_headers = dict(base_headers)
    if auth_token:
        auth_headers["Authorization"] = f"OAuth {auth_token}"

    try:
        client_id = get_sc_client_id()
    except RuntimeError as exc:
        logger.error("[SC-DL] No client_id available for sc_id=%s: %s", sc_track_id, exc)
        return None
    params = {"client_id": client_id}

    # Step 1 — fetch v2 track metadata (includes media.transcodings[]) ────────
    # Try with OAuth first; if SC rejects (often because token's v1-style is
    # incompatible with v2), retry anonymously like the soundcloud-dl extension
    # does — client_id alone is enough for public tracks.
    track_data = None
    used_auth = bool(auth_token)
    attempts = []
    if auth_token:
        attempts.append((auth_headers, "auth"))
    attempts.append((base_headers, "anon"))
    for attempt_headers, attempt_label in attempts:
        try:
            resp = requests.get(
                f"{_V2_API_BASE}/tracks/{sc_track_id}",
                headers=attempt_headers, params=params, timeout=_API_TIMEOUT,
            )
            if resp.status_code in (401, 403):
                logger.info(
                    "[SC-DL] v2 metadata HTTP %s on attempt=%s for sc_id=%s",
                    resp.status_code, attempt_label, sc_track_id,
                )
                continue  # try next variant
            resp.raise_for_status()
            track_data = resp.json()
            used_auth = (attempt_label == "auth")
            break
        except requests.RequestException as exc:
            logger.warning(
                "[SC-DL] v2 metadata fetch error attempt=%s sc_id=%s: %s",
                attempt_label, sc_track_id, exc,
            )
            continue
        except ValueError:
            logger.warning(
                "[SC-DL] v2 metadata non-JSON attempt=%s sc_id=%s",
                attempt_label, sc_track_id,
            )
            continue

    if track_data is None:
        logger.warning(
            "[SC-DL] No stream access for sc_id=%s (both auth and anon refused — paywall/removed)",
            sc_track_id,
        )
        return None

    transcodings = (track_data.get("media") or {}).get("transcodings") or []
    track_auth = track_data.get("track_authorization")

    if not transcodings:
        logger.warning(
            "[SC-DL] sc_id=%s has no transcodings (private/removed/unavailable)",
            sc_track_id,
        )
        return None

    # Legal gate: reject 30s-preview (`snipped`) transcodings — those are what
    # SC serves when the user has NO full access to the track. Downloading the
    # preview and saving as a full file would be misleading and cross from
    # "what I can stream" into "what I'm circumventing".
    full_transcodings = [t for t in transcodings if not t.get("snipped", False)]
    if not full_transcodings:
        logger.warning(
            "[SC-DL] sc_id=%s only exposes snipped previews — "
            "user has no full streaming access. Skipping.",
            sc_track_id,
        )
        return None

    # Rank: prefer hq (Go+) > sq, then progressive > hls (simpler muxing).
    # SC only returns `hq` when the authenticated account is Go+ — we honor
    # whatever SC chose to expose; we never probe for paid quality.
    def _rank(t: dict) -> tuple:
        quality = 1 if t.get("quality") == "hq" else 0
        proto = 1 if (t.get("format") or {}).get("protocol") == "progressive" else 0
        return (quality, proto)

    best = sorted(full_transcodings, key=_rank, reverse=True)[0]
    fmt = best.get("format") or {}
    protocol = fmt.get("protocol")
    mime = fmt.get("mime_type", "")
    quality = best.get("quality", "sq")
    tc_url = best.get("url")

    if not tc_url or protocol not in ("progressive", "hls"):
        logger.error(
            "[SC-DL] Unusable transcoding for sc_id=%s: protocol=%s url=%s",
            sc_track_id, protocol, bool(tc_url),
        )
        return None

    # Step 2 — resolve the signed CDN URL ──────────────────────────────────────
    # Use whichever variant succeeded for metadata.
    sign_headers = auth_headers if used_auth else base_headers
    sign_params = {"client_id": client_id}
    if track_auth:
        sign_params["track_authorization"] = track_auth

    signed = None
    sign_attempts = [(sign_headers, "primary")]
    if used_auth:
        sign_attempts.append((base_headers, "anon-fallback"))
    for s_headers, s_label in sign_attempts:
        try:
            resp = requests.get(tc_url, headers=s_headers, params=sign_params, timeout=_API_TIMEOUT)
            if resp.status_code in (401, 403):
                logger.info(
                    "[SC-DL] Transcoding sign HTTP %s on %s for sc_id=%s",
                    resp.status_code, s_label, sc_track_id,
                )
                continue
            resp.raise_for_status()
            signed = resp.json()
            break
        except requests.RequestException as exc:
            logger.warning(
                "[SC-DL] Transcoding sign error %s sc_id=%s: %s", s_label, sc_track_id, exc,
            )
            continue
        except ValueError:
            logger.warning(
                "[SC-DL] Transcoding sign non-JSON %s sc_id=%s", s_label, sc_track_id,
            )
            continue

    if signed is None:
        logger.warning(
            "[SC-DL] Transcoding sign denied for sc_id=%s (all attempts failed)",
            sc_track_id,
        )
        return None

    cdn_url = signed.get("url")
    if not cdn_url:
        logger.error("[SC-DL] Sign response had no url field for sc_id=%s", sc_track_id)
        return None

    logger.info(
        "[SC-DL] Resolved transcoding: sc_id=%s protocol=%s quality=%s mime=%s",
        sc_track_id, protocol, quality, mime,
    )
    return {
        "url": cdn_url,
        "protocol": protocol,
        "mime_type": mime,
        "quality": quality,
    }


def _download_hls_to_temp(
    m3u8_url: str,
    auth_token: Optional[str],
    mime_type: str,
) -> Optional[Path]:
    """
    Download an HLS playlist via ffmpeg and copy-mux into a single audio file.

    We use ffmpeg `-c copy` so there is NO re-encoding — the existing AAC or
    MP3 segments are just repackaged into a standard container. This keeps us
    away from any transcoding/re-encoding that could be read as content
    alteration, and preserves the exact audio bytes SC served.

    Returns the temp file path on success, or None on failure.
    """
    # Pick container by codec hint — AAC streams need .m4a + aac_adtstoasc BSF,
    # MP3 streams can stay .mp3. Default to .m4a (SC HLS is almost always AAC).
    is_mp3 = "mpeg" in mime_type.lower() and "mp4" not in mime_type.lower() \
             and "aac" not in mime_type.lower()
    ext = ".mp3" if is_mp3 else ".m4a"

    with tempfile.NamedTemporaryFile(prefix="rbpro_sc_", suffix=ext, delete=False) as tf:
        out_path = Path(tf.name)

    cmd = [
        FFMPEG_BIN,
        "-hide_banner", "-loglevel", "error",
        "-user_agent", _UA,
    ]
    if auth_token:
        # ffmpeg accepts per-request headers for HLS segment fetches
        cmd += ["-headers", f"Authorization: OAuth {auth_token}\r\n"]
    cmd += ["-i", m3u8_url, "-c", "copy"]
    if not is_mp3:
        # AAC-in-ADTS → MP4 container requires this bitstream filter
        cmd += ["-bsf:a", "aac_adtstoasc"]
    cmd += ["-y", str(out_path)]

    try:
        logger.info("[SC-DL] HLS mux via ffmpeg → %s", out_path.name)
        result = subprocess.run(
            cmd,
            capture_output=True, text=True,
            timeout=_DOWNLOAD_TIMEOUT * 2,
        )
        if result.returncode != 0:
            logger.error(
                "[SC-DL] ffmpeg failed (code %d): %s",
                result.returncode, (result.stderr or "")[:500],
            )
            out_path.unlink(missing_ok=True)
            return None

        size = out_path.stat().st_size
        if size < 1024:
            logger.error("[SC-DL] ffmpeg output too small (%d bytes) — aborting", size)
            out_path.unlink(missing_ok=True)
            return None

        logger.info("[SC-DL] HLS muxed %d bytes → %s", size, out_path.name)
        return out_path

    except subprocess.TimeoutExpired:
        logger.error("[SC-DL] ffmpeg timed out after %ds", _DOWNLOAD_TIMEOUT * 2)
        out_path.unlink(missing_ok=True)
        return None
    except OSError as exc:
        logger.error("[SC-DL] ffmpeg not available or failed: %s", exc)
        out_path.unlink(missing_ok=True)
        return None


def _stream_file_to_temp(
    download_url: str,
    auth_token: Optional[str],
) -> Optional[Path]:
    """
    Stream the audio file from `download_url` into a secure named temp file.

    Returns the temp file path on success.
    Returns None on any network error.
    The caller is responsible for deleting the temp file on failure.
    """
    headers: Dict[str, str] = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }
    if auth_token:
        headers["Authorization"] = f"OAuth {auth_token}"

    try:
        resp = requests.get(
            download_url,
            headers=headers,
            stream=True,
            timeout=_DOWNLOAD_TIMEOUT,
        )
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "")
        ext = _guess_extension(content_type, download_url)

        with tempfile.NamedTemporaryFile(
            prefix="rbpro_sc_", suffix=ext, delete=False
        ) as tf:
            tmp_path = Path(tf.name)
            total = 0
            for chunk in resp.iter_content(chunk_size=65_536):
                if chunk:
                    tf.write(chunk)
                    total += len(chunk)

        logger.info("[SC-DL] Streamed %d bytes to temp=%s", total, tmp_path.name)
        return tmp_path

    except requests.RequestException as exc:
        logger.error("[SC-DL] Streaming failed from %s: %s", download_url[:80], exc)
        return None


# ── Downloader ─────────────────────────────────────────────────────────────────

class SoundCloudDownloader:
    """
    Queue-based manager for SoundCloud downloads.
    Each download runs in its own daemon thread.

    Public API:
      download_track(...)    → task_id str  (returns immediately)
      get_task_status(id)    → dict | None
      cleanup_processes()    → atexit hook (no-op — no subprocesses to kill)
    """

    def __init__(self) -> None:
        self.tasks: Dict[str, Dict] = {}
        self._lock = threading.Lock()

    # ── Public entry point ─────────────────────────────────────────────────────

    def download_track(
        self,
        *,
        sc_track_id: str,
        sc_permalink_url: str,
        title: str,
        artist: str,
        duration_ms: int = 0,
        downloadable: bool,
        auth_token: Optional[str] = None,
        sc_playlist_title: Optional[str] = None,
        on_complete: Optional[Callable] = None,
    ) -> str:
        """
        Queue a track for download. Returns a task_id immediately.

        Legal compliance gate:
          - downloadable must be True (set by the creator on SoundCloud).
            Non-downloadable tracks are rejected without making any network request.

        Deduplication gate:
          - Checks registry by sc_track_id before starting.
          - After download, checks SHA-256 hash against registry.

        Args:
          sc_track_id       : SoundCloud numeric track ID (as string)
          sc_permalink_url  : SC track URL (for registry / logging)
          title, artist     : Track metadata for file naming + registry
          duration_ms       : Track duration in ms (from SC API)
          downloadable      : Must be True — from SC API 'downloadable' field
          auth_token        : OAuth access token (required for most downloads)
          sc_playlist_title : Optional source playlist name for auto-sort
          on_complete       : Optional callback(task_id: str, success: bool, file_path: Path | None)
        """
        task_id = f"sc_{sc_track_id}_{int(time.time())}"

        # Note: `downloadable` is kept as a signal (preferred path: original
        # uploaded file via /tracks/{id}/download), but no longer a hard gate.
        # When the creator hasn't enabled the download button, we fall back to
        # the same signed streams the SoundCloud web player uses for this user.
        # Legal boundaries live in _resolve_stream_via_transcodings (see module
        # docstring): snipped previews, 401/403, and unavailable tracks are
        # skipped there.

        # ── Gate: Deduplication — skip download but STILL link to playlist ────
        if registry.is_already_downloaded(sc_track_id):
            logger.info("[SC-DL] Skipped download sc_id=%s '%s' — already in registry. "
                        "Linking to playlist if applicable.", sc_track_id, title)
            existing = registry.get_record(sc_track_id) or {}
            raw_id = existing.get("local_track_id")
            local_track_id = _normalize_track_id(raw_id)
            # Self-heal: if registry held a Tuple-string blob, persist the cleaned ID
            if local_track_id and raw_id and str(raw_id) != local_track_id:
                try:
                    registry.update_analysis(
                        sc_track_id=str(sc_track_id),
                        bpm=existing.get("bpm"),
                        key_str=existing.get("key_str"),
                        confidence=existing.get("confidence"),
                        local_track_id=local_track_id,
                    )
                    logger.info("[SC-DL] Registry self-heal sc_id=%s: %r → %s",
                                sc_track_id, str(raw_id)[:40], local_track_id)
                except Exception as exc:
                    logger.debug("[SC-DL] registry self-heal skipped: %s", exc)
            sorted_into_pl = False
            if sc_playlist_title and local_track_id:
                try:
                    self._auto_add_to_playlist(str(local_track_id), sc_playlist_title)
                    sorted_into_pl = True
                except Exception as exc:
                    logger.warning("[SC-DL] Playlist link on skip failed: %s", exc)
            self._set_task(task_id, {
                "id": task_id, "sc_track_id": sc_track_id,
                "title": title, "artist": artist,
                "playlist_title": sc_playlist_title or "",
                "status": "Linked" if sorted_into_pl else "Skipped",
                "progress": 100,
                "duplicate": True, "error": None,
                "start_time": time.time(),
                "stage_history": [
                    {"stage": "Skipped", "ts": time.time()},
                    *([{"stage": "Sorting", "ts": time.time()}] if sorted_into_pl else []),
                    *([{"stage": "Completed", "ts": time.time()}] if sorted_into_pl else []),
                ],
                "local_track_id": local_track_id,
                "bpm": existing.get("bpm"),
                "key": existing.get("key_str"),
                "file_path": existing.get("file_path"),
            })
            if on_complete:
                on_complete(task_id, True, None)
            return task_id

        # Register as 'downloading' immediately to block parallel duplicates
        registry.register_download(
            sc_track_id=sc_track_id, title=title, artist=artist,
            duration_ms=duration_ms, sc_permalink_url=sc_permalink_url,
            sc_playlist_title=sc_playlist_title, status="downloading",
        )

        self._set_task(task_id, {
            "id": task_id, "sc_track_id": sc_track_id,
            "title": title, "artist": artist,
            "playlist_title": sc_playlist_title or "",
            "status": "Starting", "progress": 0,
            "error": None, "start_time": time.time(),
            "stage_history": [{"stage": "Starting", "ts": time.time()}],
            "local_track_id": None, "bpm": None, "key": None,
            "file_path": None,
        })

        def _run() -> None:
            try:
                self._do_download(
                    task_id=task_id, sc_track_id=sc_track_id,
                    sc_permalink_url=sc_permalink_url,
                    title=title, artist=artist, duration_ms=duration_ms,
                    downloadable=downloadable,
                    auth_token=auth_token, sc_playlist_title=sc_playlist_title,
                    on_complete=on_complete,
                )
            except Exception as exc:
                logger.error(
                    "[SC-DL] Unhandled error in download thread (task=%s): %s",
                    task_id, exc, exc_info=True,
                )
                self._update_task(task_id, status="Error", error=str(exc))
                registry.mark_failed(sc_track_id, str(exc))
                if on_complete:
                    on_complete(task_id, False, None)

        thread = threading.Thread(
            target=_run, daemon=True, name=f"sc-dl-{sc_track_id}"
        )
        thread.start()
        return task_id

    # ── Core download logic ────────────────────────────────────────────────────

    def _do_download(
        self, *, task_id: str, sc_track_id: str, sc_permalink_url: str,
        title: str, artist: str, duration_ms: int, downloadable: bool,
        auth_token: Optional[str], sc_playlist_title: Optional[str],
        on_complete: Optional[Callable],
    ) -> None:
        """Full download + hash + registry pipeline. Runs in a background thread."""

        tmp_path: Optional[Path] = None

        try:
            # Step 1 — Resolve a usable source URL.
            # Two-stage fallback:
            #   (a) Official /download endpoint if the creator enabled it.
            #   (b) v2 transcodings[] (same streams the web player plays).
            self._update_task(task_id, status="Resolving", progress=5)
            logger.info(
                "[SC-DL] Starting: sc_id=%s title='%s' downloadable=%s",
                sc_track_id, title, downloadable,
            )

            source: Optional[Dict] = None
            if downloadable:
                official_url = _resolve_official_download_url(sc_track_id, auth_token)
                if official_url:
                    source = {"url": official_url, "protocol": "progressive",
                              "mime_type": "", "quality": "original"}
                else:
                    logger.info(
                        "[SC-DL] Official /download endpoint failed for sc_id=%s; "
                        "falling back to transcodings[]", sc_track_id,
                    )

            if source is None:
                source = _resolve_stream_via_transcodings(sc_track_id, auth_token)

            if source is None:
                err = (
                    "Download fehlgeschlagen: kein verfügbarer Stream. "
                    "Entweder ist der Track privat/gelöscht, oder dein Konto "
                    "hat keinen vollen Zugriff (Paywall/Go+ ohne Abo)."
                )
                self._update_task(task_id, status="Failed", error=err)
                registry.mark_failed(sc_track_id, err)
                if on_complete:
                    on_complete(task_id, False, None)
                return

            # Step 2 — Download by protocol ────────────────────────────────────
            self._update_task(task_id, status="Downloading", progress=15)
            protocol = source.get("protocol")

            if protocol == "hls":
                tmp_path = _download_hls_to_temp(
                    source["url"], auth_token, source.get("mime_type", ""),
                )
            else:
                # progressive — including the official /download redirect
                tmp_path = _stream_file_to_temp(source["url"], auth_token)

            if not tmp_path:
                err = "Datei-Download fehlgeschlagen (Netzwerkfehler oder ffmpeg-Problem)."
                self._update_task(task_id, status="Failed", error=err)
                registry.mark_failed(sc_track_id, err)
                if on_complete:
                    on_complete(task_id, False, None)
                return

            self._update_task(task_id, status="Processing", progress=80)

            # Step 3 — Move to organized final location ────────────────────────
            ext = tmp_path.suffix.lower() or ".mp3"
            final_path = _build_save_path(artist, title, ext)
            shutil.move(str(tmp_path), str(final_path))
            tmp_path = None  # moved, no longer needs cleanup
            file_size = final_path.stat().st_size
            logger.info("[SC-DL] Saved: %s (%d bytes)", final_path, file_size)

            # Step 4 — SHA-256: content-based duplicate check ──────────────────
            self._update_task(task_id, status="Hashing", progress=88)
            sha256 = registry.compute_sha256(final_path)

            if sha256:
                existing = registry.find_by_hash(sha256)
                if existing and existing["sc_track_id"] != sc_track_id:
                    # Same content under a different SC ID — remove the duplicate
                    logger.warning(
                        "[SC-DL] Content duplicate: sc_id=%s matches existing sc_id=%s. "
                        "Removing duplicate file.",
                        sc_track_id, existing["sc_track_id"],
                    )
                    final_path.unlink(missing_ok=True)
                    registry.mark_failed(
                        sc_track_id,
                        f"Duplicate content (matches sc_id={existing['sc_track_id']})"
                    )
                    self._update_task(
                        task_id, status="Duplicate", progress=100,
                        error=(
                            f"Dieser Track ist bereits vorhanden als "
                            f"'{existing.get('title', '?')}' von '{existing.get('artist', '?')}'."
                        )
                    )
                    if on_complete:
                        on_complete(task_id, False, None)
                    return

            # Step 5 — Register as downloaded ──────────────────────────────────
            registry.register_download(
                sc_track_id=sc_track_id, title=title, artist=artist,
                duration_ms=duration_ms, sc_permalink_url=sc_permalink_url,
                sc_playlist_title=sc_playlist_title,
                file_path=final_path, file_format=ext.lstrip("."),
                file_size_bytes=file_size, sha256_hash=sha256,
                status="downloaded",
            )

            self._update_task(task_id, status="Downloaded", progress=85)
            logger.info("[SC-DL] Downloaded: '%s' → %s", title, final_path)

            if on_complete:
                on_complete(task_id, True, final_path)

            # Step 6 — Trigger background analysis (must not raise) ────────────
            self._update_task(task_id, status="Analyzing", progress=88)
            self._trigger_analysis_async(sc_track_id, final_path, sc_playlist_title, task_id=task_id)

        except Exception as exc:
            logger.error(
                "[SC-DL] Unexpected error in _do_download (sc_id=%s): %s",
                sc_track_id, exc, exc_info=True,
            )
            # Clean up temp file if the move hadn't happened yet
            if tmp_path and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:
                    pass
            err = f"Interner Fehler: {exc}"
            self._update_task(task_id, status="Error", error=err)
            registry.mark_failed(sc_track_id, err)
            if on_complete:
                on_complete(task_id, False, None)

    # ── Post-download pipeline ─────────────────────────────────────────────────

    def _trigger_analysis_async(
        self,
        sc_track_id: str,
        file_path: Path,
        sc_playlist_title: Optional[str],
        task_id: Optional[str] = None,
    ) -> None:
        """
        Spawn a daemon thread to run BPM/key analysis and auto-import.
        Errors here must NOT bubble up — the download itself already succeeded.
        """
        def _analyze() -> None:
            local_track_id: Optional[str] = None
            try:
                # Mark as analyzing in registry
                registry.register_download(
                    sc_track_id=sc_track_id, title="", artist="",
                    status="analyzing",
                )
                if task_id:
                    self._update_task(task_id, status="Analyzing", progress=90)

                from .analysis_engine import run_full_analysis
                logger.info("[SC-DL] Analyzing (full pipeline): %s", file_path.name)
                result = run_full_analysis(str(file_path))
                bpm = result.get("bpm")
                key = result.get("key")
                conf = result.get("key_confidence", result.get("confidence"))

                # Auto-import into library — pass full analysis result so the
                # importer can persist beatgrid + cues + waveform without
                # re-running analysis.
                if task_id:
                    self._update_task(task_id, status="Importing", progress=93,
                                      bpm=bpm, key=key, file_path=str(file_path))
                local_track_id = self._auto_import(file_path, analysis_result=result)
                if task_id and local_track_id:
                    self._update_task(task_id, local_track_id=local_track_id)

                # Write companion ANLZ binary files (DAT/EXT/2EX) so CDJs get
                # beatgrid + cues + colored waveforms when this track lands on
                # a USB stick.
                try:
                    self._write_companion_anlz(file_path, result)
                except Exception as exc:
                    logger.warning("[SC-DL] ANLZ generation failed for %s: %s", file_path.name, exc)

                registry.update_analysis(
                    sc_track_id=sc_track_id, bpm=bpm,
                    key_str=key, confidence=conf,
                    local_track_id=local_track_id,
                )
                logger.info(
                    "[SC-DL] Analysis done: sc_id=%s bpm=%.1f key=%s local_id=%s",
                    sc_track_id, bpm or 0, key or "?", local_track_id,
                )

                # Auto-sort into SC playlist after import
                if sc_playlist_title and local_track_id:
                    if task_id:
                        self._update_task(task_id, status="Sorting", progress=98)
                    self._auto_add_to_playlist(local_track_id, sc_playlist_title)

                if task_id:
                    self._update_task(task_id, status="Completed", progress=100)

            except Exception as exc:
                logger.error(
                    "[SC-DL] Background analysis failed for sc_id=%s: %s",
                    sc_track_id, exc, exc_info=True,
                )
                if task_id:
                    self._update_task(task_id, status="Analysis Failed", progress=100, error=str(exc))

        thread = threading.Thread(
            target=_analyze, daemon=True, name=f"sc-analyze-{sc_track_id}"
        )
        thread.start()

    def _auto_import(self, file_path: Path, analysis_result: Optional[Dict] = None) -> Optional[str]:
        """
        Import the downloaded track into the library.
        Returns the new local track_id string, or None on failure.
        Passes full analysis result (if any) so the importer skips re-analysis.
        """
        try:
            from .services import ImportManager
            result = ImportManager.process_import(file_path, analysis_result=analysis_result)
            # process_import returns (tid, analysis) tuple — unpack
            if isinstance(result, tuple) and len(result) >= 1:
                track_id = result[0]
            else:
                track_id = result
            if track_id:
                logger.info("[SC-DL] Imported into library: track_id=%s", track_id)
            else:
                logger.warning("[SC-DL] Import returned no track_id for %s", file_path)
            return str(track_id) if track_id else None
        except Exception as exc:
            logger.error("[SC-DL] Auto-import failed for %s: %s", file_path, exc)
            return None

    def _write_companion_anlz(self, file_path: Path, result: Dict) -> None:
        """Write DAT/EXT/2EX sidecars next to the audio file. See
        app/anlz_sidecar.py for the layout contract — kept unified across
        every track-import path so USB-sync's OneLibraryUsbWriter has a
        single place to look.
        """
        from .anlz_sidecar import write_companion_anlz as _write
        target = _write(file_path, result)
        if target:
            logger.info("[SC-DL] ANLZ written → %s", target)

    def _auto_add_to_playlist(self, local_track_id: str, sc_playlist_title: str) -> None:
        """
        Add the imported track to the matching local SC_ playlist.
        Creates the playlist if it doesn't exist (via SoundCloudSyncEngine).
        """
        try:
            from .database import db
            from .soundcloud_api import SoundCloudSyncEngine

            engine = SoundCloudSyncEngine(db)
            pid = engine.find_or_create_playlist(sc_playlist_title)
            if not pid:
                logger.warning(
                    "[SC-DL] Could not find/create playlist for '%s'", sc_playlist_title
                )
                return

            add_fn = (
                db.add_track_to_playlist
                if hasattr(db, "add_track_to_playlist")
                else (
                    db.active_db.add_track_to_playlist
                    if hasattr(db, "active_db")
                    else None
                )
            )
            if add_fn:
                add_fn(pid, local_track_id)
                logger.info(
                    "[SC-DL] Auto-sorted track %s into 'SC_%s' (pid=%s)",
                    local_track_id, sc_playlist_title, pid,
                )
            else:
                logger.warning("[SC-DL] DB has no add_track_to_playlist method.")

        except Exception as exc:
            logger.error(
                "[SC-DL] auto_add_to_playlist failed (playlist='%s'): %s",
                sc_playlist_title, exc,
            )

    # ── State helpers ──────────────────────────────────────────────────────────

    def _set_task(self, task_id: str, data: Dict) -> None:
        with self._lock:
            self.tasks[task_id] = data

    def _update_task(self, task_id: str, **kwargs) -> None:
        with self._lock:
            if task_id in self.tasks:
                # Capture stage transitions in history for UI timeline
                if "status" in kwargs:
                    new_stage = kwargs["status"]
                    cur = self.tasks[task_id]
                    last = cur.get("stage_history", [])[-1:] or [{}]
                    if last[0].get("stage") != new_stage:
                        cur.setdefault("stage_history", []).append({
                            "stage": new_stage, "ts": time.time(),
                        })
                self.tasks[task_id].update(kwargs)

    def get_task_status(self, task_id: str) -> Optional[Dict]:
        with self._lock:
            return self.tasks.get(task_id)

    def cleanup_processes(self) -> None:
        """No-op: kept for API compatibility. No subprocesses used."""
        logger.debug("[SC-DL] cleanup_processes called (no-op — HTTP-based downloader)")


# Module-level singleton used by main.py
sc_downloader = SoundCloudDownloader()
