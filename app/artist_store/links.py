"""artist_store.links — where to find an artist: their own profiles, classified and ranked.

Owner refinement 2026-09-26 ("deren Social Media finden"). Four sources, strongest
first — the order is ``schema.LINK_SOURCE_RANK``:

1. **manual** — a URL the user pasted. Never overwritten by a fetch.
2. **soundcloud_profile** — the links the artist added to their own SoundCloud page
   (``/users/{urn}/web-profiles``), their ``website`` field and the account itself.
   The artist curated these, so they count as HIGH confidence.
3. **musicbrainz** — the URL relationships of the MusicBrainz artist, but only an
   artist reached through the linked SoundCloud URL (an exact relation) or one the
   user confirmed. A name search produces *candidates*, never a binding: electronic
   music is full of shared names.
4. **soundcloud_bio** — URLs and ``IG: @name``-style handles in the free bio text,
   known services only. LOW: bios name managers, labels and friends too.

Every URL is untrusted remote text. :func:`classify_url` is the one gate between a
string and a stored link: http(s) only, no credentials, no IP or single-label hosts,
default ports only, bounded length, and the service is decided by an exact
host-suffix table — a lookalike host is at best a generic ``website``, and generic
websites are only accepted from a source the artist or the user controls.

Credentials never live here: the caller passes an already-resolved SoundCloud token,
exactly like ``discovery.discover``. MusicBrainz needs none.
"""

from __future__ import annotations

import ipaddress
import logging
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlsplit

import requests

from app import musicbrainz_client as mb_client
from app import soundcloud_api as sc_api
from app.artist_store import schema
from app.artist_store.merge import fold_key

logger = logging.getLogger("ARTIST_STORE")

PROVIDER_MUSICBRAINZ = "musicbrainz"

WEBSITE = "website"

MAX_URL_LENGTH = 2048

#: Calls one SoundCloud refresh may spend: the profile and its web-profiles list.
LINKS_CALL_BUDGET = 3

#: A MusicBrainz name-search hit is only offered when it scores at least this AND its
#: name or an alias folds to one of the artist's spellings.
MB_CANDIDATE_MIN_SCORE = 90
MB_CANDIDATE_LIMIT = 3

#: Confidence stored on a MusicBrainz binding. ``anchored`` = derived from the linked
#: SoundCloud URL and re-derived on every refresh; ``confirmed`` = the user's pick,
#: which no refresh overrides.
MB_ANCHORED_CONFIDENCE = 1.0
MB_CONFIRMED_CONFIDENCE = 0.9

SOURCE_CONFIDENCE = {
    schema.LINK_SOURCE_MANUAL: schema.CONFIDENCE_HIGH,
    schema.LINK_SOURCE_SC_PROFILE: schema.CONFIDENCE_HIGH,
    schema.LINK_SOURCE_MUSICBRAINZ: schema.CONFIDENCE_HIGH,
    schema.LINK_SOURCE_SC_BIO: schema.CONFIDENCE_LOW,
}

# Per-source status in a refresh report. Only ``ok`` entitles anyone to say "no links".
STATUS_OK = "ok"
STATUS_FAILED = "failed"
STATUS_NOT_FOUND = "not_found"
STATUS_NOT_LINKED = "not_linked"
STATUS_NOT_CONNECTED = "not_connected"
STATUS_NOT_QUERIED = "not_queried"
STATUS_NO_MATCH = "no_match"
STATUS_NEEDS_CONFIRMATION = "needs_confirmation"
STATUS_AMBIGUOUS = "ambiguous"
STATUS_SKIPPED_BUDGET = "skipped_budget"


@dataclass(frozen=True)
class Service:
    key: str
    label: str
    hosts: tuple[str, ...]
    canonical_host: str | None
    category: str


#: Display order is this order. ``hosts`` are registrable domains: a URL's host must
#: equal one or end with ``.`` + one — ``notinstagram.com`` matches nothing.
SERVICES: tuple[Service, ...] = (
    Service("soundcloud", "SoundCloud", ("soundcloud.com",), "soundcloud.com", "music"),
    Service("instagram", "Instagram", ("instagram.com",), "www.instagram.com", "social"),
    Service("tiktok", "TikTok", ("tiktok.com",), "www.tiktok.com", "social"),
    Service("x", "X (Twitter)", ("x.com", "twitter.com"), "x.com", "social"),
    Service("facebook", "Facebook", ("facebook.com",), "www.facebook.com", "social"),
    Service("youtube", "YouTube", ("youtube.com",), "www.youtube.com", "social"),
    Service("threads", "Threads", ("threads.net", "threads.com"), "www.threads.net", "social"),
    Service("twitch", "Twitch", ("twitch.tv",), "www.twitch.tv", "social"),
    Service("spotify", "Spotify", ("open.spotify.com",), "open.spotify.com", "music"),
    Service(
        "apple_music",
        "Apple Music",
        ("music.apple.com", "itunes.apple.com"),
        "music.apple.com",
        "music",
    ),
    Service("deezer", "Deezer", ("deezer.com",), "www.deezer.com", "music"),
    Service("tidal", "TIDAL", ("tidal.com",), "tidal.com", "music"),
    Service("mixcloud", "Mixcloud", ("mixcloud.com",), "www.mixcloud.com", "music"),
    Service("bandcamp", "Bandcamp", ("bandcamp.com",), None, "store"),
    Service("beatport", "Beatport", ("beatport.com",), "www.beatport.com", "store"),
    Service("traxsource", "Traxsource", ("traxsource.com",), "www.traxsource.com", "store"),
    Service(
        "resident_advisor",
        "Resident Advisor",
        ("ra.co", "residentadvisor.net"),
        "ra.co",
        "scene",
    ),
    Service("discogs", "Discogs", ("discogs.com",), "www.discogs.com", "scene"),
    Service("songkick", "Songkick", ("songkick.com",), "www.songkick.com", "scene"),
    Service("bandsintown", "Bandsintown", ("bandsintown.com",), "www.bandsintown.com", "scene"),
    Service("linktree", "Linktree", ("linktr.ee",), "linktr.ee", "web"),
)
_SERVICE_BY_KEY = {s.key: s for s in SERVICES}
SERVICE_ORDER = {s.key: i for i, s in enumerate(SERVICES)} | {WEBSITE: len(SERVICES)}

_MOBILE_PREFIXES = ("www.", "m.", "mobile.", "web.")
_HOST_RE = re.compile(
    r"^(?=.{4,253}$)(?:(?!-)[a-z0-9-]{1,63}(?<!-)\.)+(?:[a-z]{2,63}|xn--[a-z0-9-]{2,59})$"
)
_BAD_CHARS = re.compile(r"[\s\\\x00-\x1f\x7f]")
_BARE_URL_RE = re.compile(r"^(?:[a-z0-9-]+\.)+[a-z]{2,63}(?:[/?#]|$)", re.IGNORECASE)
_SLUG = re.compile(r"^[A-Za-z0-9._~%+-]{1,120}$")


@dataclass(frozen=True)
class LinkCandidate:
    """One classified profile URL, before any source or confidence is attached."""

    url_key: str
    url: str
    service: str
    handle: str | None = None
    title: str | None = None

    def entry(self, source: str) -> dict[str, Any]:
        return {
            "url_key": self.url_key,
            "url": self.url,
            "service": self.service,
            "handle": self.handle,
            "title": self.title,
            "source": source,
            "confidence": SOURCE_CONFIDENCE[source],
        }


# --------------------------------------------------------------------------- profile rules
#
# One rule per service: ``(host, path segments, query) -> (canonical_path, identity,
# handle)`` or None. ``identity`` becomes the ``url_key`` — a folded handle for
# name-addressed services, the service's own id (case kept) for id-addressed ones. A
# URL that is a post, a track, a search or a share dialog is not a profile: None.

ProfileMatch = tuple[str, str, str | None]
ProfileRule = Callable[[str, list[str], str], ProfileMatch | None]


def _slug(value: str) -> str | None:
    return value if _SLUG.match(value or "") else None


def _drop_locale(segs: list[str]) -> list[str]:
    """``/de/artist/…``, ``/intl-de/artist/…`` → ``/artist/…``."""
    if segs and (segs[0].startswith("intl-") or (len(segs[0]) == 2 and segs[0].isalpha())):
        return segs[1:]
    return segs


def _single_name(reserved: frozenset[str], at_handle: bool) -> ProfileRule:
    """``service.tld/<name>`` and nothing deeper — deeper paths are posts or tracks."""

    def rule(_host: str, segs: list[str], _query: str) -> ProfileMatch | None:
        if len(segs) != 1:
            return None
        name = _slug(segs[0])
        if not name or name.startswith("@") or name.casefold() in reserved:
            return None
        return f"/{name}", name.casefold(), f"@{name}" if at_handle else name

    return rule


def _at_name(_host: str, segs: list[str], _query: str) -> ProfileMatch | None:
    """``service.tld/@<name>`` (TikTok, Threads)."""
    if len(segs) != 1 or not segs[0].startswith("@"):
        return None
    name = _slug(segs[0][1:])
    return (f"/@{name}", name.casefold(), f"@{name}") if name else None


_FACEBOOK_RESERVED = frozenset(
    {"sharer", "sharer.php", "share", "plugins", "groups", "events", "watch", "login", "pages"}
)


def _facebook(host: str, segs: list[str], query: str) -> ProfileMatch | None:
    if segs == ["profile.php"]:
        ids = parse_qs(query).get("id") or []
        fid = ids[0] if ids and ids[0].isdigit() else None
        return (f"/profile.php?id={fid}", f"id:{fid}", None) if fid else None
    return _single_name(_FACEBOOK_RESERVED, at_handle=False)(host, segs, query)


def _youtube(_host: str, segs: list[str], _query: str) -> ProfileMatch | None:
    first = segs[0] if segs else ""
    if len(segs) == 1 and first.startswith("@") and _slug(first[1:]):
        return f"/{first}", first.casefold(), first
    if first in ("channel", "c", "user") and len(segs) == 2 and _slug(segs[1]):
        ident = segs[1] if first == "channel" else segs[1].casefold()
        return f"/{first}/{segs[1]}", f"{first}:{ident}", None if first == "channel" else segs[1]
    return None


def _artist_id(_host: str, segs: list[str], _query: str) -> ProfileMatch | None:
    """``/artist/<id>`` behind an optional locale (Spotify, Deezer, TIDAL)."""
    rest = _drop_locale(segs)
    if rest[:1] == ["browse"]:
        rest = rest[1:]
    if len(rest) >= 2 and rest[0] == "artist" and _slug(rest[1]):
        return f"/artist/{rest[1]}", rest[1], None
    return None


def _apple_music(_host: str, segs: list[str], _query: str) -> ProfileMatch | None:
    if "artist" not in segs:
        return None
    idx = segs.index("artist")
    country = segs[0].lower() if idx == 1 and len(segs[0]) == 2 and segs[0].isalpha() else "us"
    tail = segs[idx + 1 :]
    ident = next(
        (s.removeprefix("id") for s in reversed(tail) if s.removeprefix("id").isdigit()), None
    )
    if not ident:
        return None
    slug = tail[0] if len(tail) > 1 and _slug(tail[0]) else None
    path = f"/{country}/artist/{slug}/{ident}" if slug else f"/{country}/artist/{ident}"
    return path, ident, None


def _bandcamp(host: str, _segs: list[str], _query: str) -> ProfileMatch | None:
    """``<name>.bandcamp.com`` — the subdomain IS the artist; any path under it is theirs."""
    sub = host.removesuffix(".bandcamp.com")
    if sub == host or "." in sub or not _slug(sub) or sub in ("daily", "www", "m"):
        return None
    return "/", sub.casefold(), sub


def _beatport(_host: str, segs: list[str], _query: str) -> ProfileMatch | None:
    if len(segs) >= 3 and segs[0] == "artist" and _slug(segs[1]) and segs[2].isdigit():
        return f"/artist/{segs[1]}/{segs[2]}", segs[2], segs[1]
    return None


def _traxsource(_host: str, segs: list[str], _query: str) -> ProfileMatch | None:
    if len(segs) >= 3 and segs[0] == "artist" and segs[1].isdigit() and _slug(segs[2]):
        return f"/artist/{segs[1]}/{segs[2]}", segs[1], segs[2]
    return None


def _resident_advisor(_host: str, segs: list[str], _query: str) -> ProfileMatch | None:
    if len(segs) >= 2 and segs[0] in ("dj", "dj.aspx") and _slug(segs[1]):
        name = segs[1].casefold()
        return f"/dj/{name}", name, segs[1]
    return None


def _numbered(prefix: str) -> ProfileRule:
    """``/<prefix>/<digits>[-slug]`` behind an optional locale (Discogs, Songkick, …)."""

    def rule(_host: str, segs: list[str], _query: str) -> ProfileMatch | None:
        rest = _drop_locale(segs)
        if len(rest) >= 2 and rest[0] == prefix and _slug(rest[1]):
            ident = rest[1].split("-", 1)[0]
            if ident.isdigit():
                return f"/{prefix}/{rest[1]}", ident, None
        return None

    return rule


_PROFILE_RULES: dict[str, ProfileRule] = {
    "soundcloud": _single_name(
        frozenset({"discover", "search", "stream", "you", "pages", "tags", "charts", "upload"}),
        at_handle=False,
    ),
    "instagram": _single_name(
        frozenset({"p", "reel", "reels", "explore", "stories", "tv", "accounts", "direct"}),
        at_handle=True,
    ),
    "tiktok": _at_name,
    "x": _single_name(
        frozenset({"home", "search", "intent", "share", "i", "hashtag", "explore", "settings"}),
        at_handle=True,
    ),
    "facebook": _facebook,
    "youtube": _youtube,
    "threads": _at_name,
    "twitch": _single_name(frozenset({"directory", "videos", "p", "settings", "search"}), False),
    "spotify": _artist_id,
    "apple_music": _apple_music,
    "deezer": _artist_id,
    "tidal": _artist_id,
    "mixcloud": _single_name(frozenset({"discover", "upload", "select", "live", "search"}), False),
    "bandcamp": _bandcamp,
    "beatport": _beatport,
    "traxsource": _traxsource,
    "resident_advisor": _resident_advisor,
    "discogs": _numbered("artist"),
    "songkick": _numbered("artists"),
    "bandsintown": _numbered("a"),
    "linktree": _single_name(frozenset({"s", "admin", "login"}), at_handle=False),
}


# --------------------------------------------------------------------------- classification


def _service_for(host: str) -> Service | None:
    for service in SERVICES:
        for suffix in service.hosts:
            if host == suffix or host.endswith("." + suffix):
                return service
    return None


def _bare(host: str) -> str:
    for prefix in _MOBILE_PREFIXES:
        if host.startswith(prefix) and host.count(".") > 1:
            return host[len(prefix) :]
    return host


def _safe_host(hostname: str | None) -> str | None:
    """Lower-cased ASCII host, or None for anything that is not a public DNS name."""
    host = (hostname or "").rstrip(".")
    if not host.isascii():
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError:
            return None
    host = host.lower()
    try:
        ipaddress.ip_address(host)
        return None
    except ValueError:
        pass
    return host if _HOST_RE.match(host) else None


def classify_url(
    raw: Any, *, allow_website: bool = False, title: str | None = None
) -> LinkCandidate | None:
    """The one gate from an untrusted string to a storable link, or None.

    A known service must point at a *profile* (not a post, track or share dialog); the
    canonical URL is rebuilt from the parts that identify it, so tracking parameters
    and fragments never survive. Anything else is a generic ``website`` — accepted only
    when ``allow_website``, because a stray homepage in free text is as likely a label
    or a booking agency as the artist.
    """
    text = str(raw or "").strip().strip("<>")
    if not text or len(text) > MAX_URL_LENGTH or _BAD_CHARS.search(text):
        return None
    if "://" not in text:
        if not _BARE_URL_RE.match(text):
            return None
        text = f"https://{text}"
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https") or parts.username or parts.password:
        return None
    if port not in (None, 80, 443):
        return None
    host = _safe_host(parts.hostname)
    if host is None:
        return None

    bare_host = _bare(host)
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    label = (title or "").strip() or None
    service = _service_for(bare_host)
    if service is not None:
        found = _PROFILE_RULES[service.key](
            bare_host, [s for s in path.split("/") if s], parts.query
        )
        if found is None:
            return None
        canonical_path, identity, handle = found
        return LinkCandidate(
            url_key=f"{service.key}:{identity}",
            url=f"https://{service.canonical_host or bare_host}{canonical_path}",
            service=service.key,
            handle=handle,
            title=label,
        )
    if not allow_website:
        return None
    clean_path = path.rstrip("/")
    return LinkCandidate(
        url_key=f"web:{bare_host}{clean_path.casefold()}",
        url=f"{scheme}://{host}{clean_path or '/'}",
        service=WEBSITE,
        handle=bare_host,
        title=label,
    )


# --------------------------------------------------------------------------- sources


_KNOWN_HOSTS = sorted({h for s in SERVICES for h in s.hosts}, key=len, reverse=True)
_URL_IN_TEXT = re.compile(r"https?://[^\s<>\"'`]+", re.IGNORECASE)
_BARE_SERVICE_URL = re.compile(
    r"(?<![\w./@-])(?:[a-z0-9-]+\.)?(?:"
    + "|".join(re.escape(h) for h in _KNOWN_HOSTS)
    + r")/[^\s<>\"'`]+",
    re.IGNORECASE,
)
_TRAILING_PUNCT = ".,;:!?)]}'\""
#: ``IG: @name`` / ``IG - @name`` / ``IG | @name`` — ASCII, en and em dash accepted.
_SEP = "(?:[:|\\-\u2013\u2014]\\s*)"
_HANDLE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "instagram",
        re.compile(
            rf"(?<![\w@])(?:ig|insta|instagram)\s*(?:{_SEP}@?|@)([A-Za-z0-9._]{{2,30}})",
            re.IGNORECASE,
        ),
    ),
    ("tiktok", re.compile(rf"(?<![\w@])tik\s?tok\s*{_SEP}?@([A-Za-z0-9._]{{2,24}})", re.I)),
    ("x", re.compile(rf"(?<![\w@])(?:twitter|x)\s*{_SEP}@([A-Za-z0-9_]{{1,15}})", re.I)),
)
_HANDLE_URL = {
    "instagram": "https://www.instagram.com/{}",
    "tiktok": "https://www.tiktok.com/@{}",
    "x": "https://x.com/{}",
}


def _trim(url: str) -> str:
    """Drop the sentence punctuation a URL picks up in running text."""
    while url and url[-1] in _TRAILING_PUNCT:
        if url[-1] == ")" and url.count("(") >= url.count(")"):
            break
        url = url[:-1]
    return url


def extract_bio_links(text: Any) -> list[LinkCandidate]:
    """Known-service profile links and ``IG: @name``-style handles in free bio text.

    Known services only: a bare homepage in a bio is as likely the label's as the
    artist's. Order of first appearance, one candidate per ``url_key``.
    """
    body = str(text or "")
    if not body.strip():
        return []
    found: dict[str, LinkCandidate] = {}
    spans = [m.group(0) for m in _URL_IN_TEXT.finditer(body)]
    spans += [m.group(0) for m in _BARE_SERVICE_URL.finditer(body)]
    for span in spans:
        candidate = classify_url(_trim(span))
        if candidate is not None:
            found.setdefault(candidate.url_key, candidate)
    for service, pattern in _HANDLE_PATTERNS:
        for m in pattern.finditer(body):
            candidate = classify_url(_HANDLE_URL[service].format(m.group(1).rstrip(".")))
            if candidate is not None:
                found.setdefault(candidate.url_key, candidate)
    return list(found.values())


def from_soundcloud_profile(
    profile: Mapping[str, Any] | None,
    web_profiles: Iterable[Any] = (),
) -> list[LinkCandidate]:
    """The account itself, its ``website`` field and every web-profile link it lists."""
    out: list[LinkCandidate] = []
    if profile:
        own = classify_url(profile.get("permalink_url"), title="SoundCloud")
        if own is not None:
            out.append(own)
        site = classify_url(
            profile.get("website"),
            allow_website=True,
            title=str(profile.get("website_title") or "") or None,
        )
        if site is not None:
            out.append(site)
    for item in web_profiles:
        if not isinstance(item, Mapping):
            continue
        candidate = classify_url(
            item.get("url"), allow_website=True, title=str(item.get("title") or "") or None
        )
        if candidate is not None:
            out.append(candidate)
    return out


#: MusicBrainz relationship types that may produce a generic website.
_MB_WEBSITE_TYPES = frozenset({"official homepage"})


def from_musicbrainz(relations: Iterable[Any]) -> list[LinkCandidate]:
    """URL relationships of a MusicBrainz artist, profile-shaped and still current.

    Ended relations are history, not a place to find the artist. Everything that is
    not a known service is dropped unless MusicBrainz calls it the official homepage —
    which removes the library catalogues (VIAF, WorldCat, LoC …) a DJ has no use for.
    """
    out: list[LinkCandidate] = []
    for rel in relations:
        if not isinstance(rel, Mapping) or rel.get("ended"):
            continue
        kind = str(rel.get("type") or "")
        candidate = classify_url(rel.get("url"), allow_website=kind in _MB_WEBSITE_TYPES)
        if candidate is not None:
            out.append(candidate)
    return out


def best_per_key(tagged: Iterable[tuple[LinkCandidate, str]]) -> list[dict[str, Any]]:
    """One store entry per ``url_key``: the strongest source wins, first seen breaks ties."""
    best: dict[str, tuple[int, dict[str, Any]]] = {}
    for candidate, source in tagged:
        rank = schema.LINK_SOURCE_RANK[source]
        current = best.get(candidate.url_key)
        if current is None or rank > current[0]:
            best[candidate.url_key] = (rank, candidate.entry(source))
    return [entry for _, entry in best.values()]


# --------------------------------------------------------------------------- read side


def _decorate(row: Mapping[str, Any]) -> dict[str, Any]:
    service = _SERVICE_BY_KEY.get(str(row.get("service")))
    return {
        "url_key": row["url_key"],
        "url": row["url"],
        "service": row["service"],
        "service_label": service.label if service else "Website",
        "category": service.category if service else "web",
        "handle": row.get("handle"),
        "title": row.get("title"),
        "source": row["source"],
        "confidence": row["confidence"],
        "hidden": bool(row.get("hidden")),
    }


def _sort_key(link: Mapping[str, Any]) -> tuple[int, int, str]:
    return (
        SERVICE_ORDER.get(str(link["service"]), len(SERVICE_ORDER)),
        -schema.LINK_SOURCE_RANK.get(str(link["source"]), 0),
        str(link["url_key"]),
    )


def musicbrainz_binding(collection_id: str) -> dict[str, Any] | None:
    link = schema.get_link(collection_id, PROVIDER_MUSICBRAINZ)
    if link is None or not link.get("remote_id"):
        return None
    return {
        "mbid": str(link["remote_id"]),
        "url": str(link.get("permalink") or ""),
        "anchored": (link.get("confidence") or 0) >= MB_ANCHORED_CONFIDENCE,
    }


def list_links(collection_id: str) -> dict[str, Any]:
    """Stored links in display order, plus what the last refresh saw. No network."""
    rows = sorted((_decorate(r) for r in schema.list_web_links(collection_id)), key=_sort_key)
    return {
        "collection_id": collection_id,
        "links": rows,
        "hidden_count": schema.count_hidden_web_links(collection_id),
        "last_fetch": schema.get_link_fetch(collection_id),
        "musicbrainz": musicbrainz_binding(collection_id),
    }


# --------------------------------------------------------------------------- write side


def add_manual_link(collection_id: str, url: str) -> dict[str, Any]:
    """Store a URL the user typed. ValueError when it is not a usable web link."""
    candidate = classify_url(url, allow_website=True)
    if candidate is None:
        raise ValueError(
            "That is not a link this app can store. It has to be an http(s) address of a "
            "profile page, for example https://www.instagram.com/name."
        )
    row = schema.add_manual_web_link(collection_id, candidate.entry(schema.LINK_SOURCE_MANUAL))
    logger.info("op=artist_link_add collection=%s service=%s", collection_id, candidate.service)
    return _decorate(row)


def remove_link(collection_id: str, url_key: str) -> str | None:
    """``deleted`` (a manual link), ``hidden`` (a fetched one) or None (no such link)."""
    outcome = schema.remove_web_link(collection_id, url_key)
    logger.info("op=artist_link_remove collection=%s outcome=%s", collection_id, outcome)
    return outcome


def restore_hidden(collection_id: str) -> int:
    return schema.unhide_web_links(collection_id)


def _names_match(candidate: Mapping[str, Any], name_keys: set[str]) -> bool:
    spellings = [candidate.get("name"), *(candidate.get("aliases") or [])]
    return any(fold_key(str(s or "")) in name_keys for s in spellings)


def musicbrainz_candidates(names: Sequence[str], mb: Any = mb_client) -> list[dict[str, Any]]:
    """Name-search hits worth showing: a high score AND a spelling that folds to ours.

    One search, on the canonical name; the aliases only widen what counts as a match.
    """
    if not names:
        return []
    name_keys = {k for k in (fold_key(n) for n in names) if k}
    hits = mb.search_artists(names[0], limit=10)
    keep = [
        {k: h.get(k) for k in ("mbid", "name", "disambiguation", "country", "type", "score")}
        for h in hits
        if int(h.get("score") or 0) >= MB_CANDIDATE_MIN_SCORE and _names_match(h, name_keys)
    ]
    return keep[:MB_CANDIDATE_LIMIT]


def _set_musicbrainz(collection_id: str, mbid: str, confidence: float) -> None:
    schema.set_link(
        collection_id,
        PROVIDER_MUSICBRAINZ,
        mbid,
        f"https://musicbrainz.org/artist/{mbid}",
        confidence,
    )


def confirm_musicbrainz(collection_id: str, mbid: str) -> dict[str, Any]:
    """Bind the MusicBrainz artist the user picked. ValueError for a malformed id."""
    key = str(mbid or "").strip().lower()
    if not mb_client.is_mbid(key):
        raise ValueError(f"not a MusicBrainz id: {mbid!r}")
    _set_musicbrainz(collection_id, key, MB_CONFIRMED_CONFIDENCE)
    logger.info("op=artist_mb_confirm collection=%s", collection_id)
    return musicbrainz_binding(collection_id) or {}


def drop_musicbrainz(collection_id: str) -> bool:
    """Unbind MusicBrainz and take its links with it. Hidden ones stay hidden.

    "That is not this artist" has to empty the strip now, not at the next refresh —
    the links on screen came from the binding the user just rejected.
    """
    removed = schema.remove_link(collection_id, PROVIDER_MUSICBRAINZ)
    schema.merge_fetched_web_links(collection_id, [], [schema.LINK_SOURCE_MUSICBRAINZ])
    return removed


def _soundcloud_url(permalink: str | None) -> str | None:
    value = str(permalink or "").strip()
    if not value:
        return None
    candidate = classify_url(value if "://" in value else f"https://soundcloud.com/{value}")
    return candidate.url if candidate and candidate.service == "soundcloud" else None


def _refresh_musicbrainz(
    collection_id: str,
    names: Sequence[str],
    sc_url: str | None,
    mb: Any,
    report: dict[str, Any],
) -> list[LinkCandidate]:
    """Settle the MusicBrainz binding, then read its URL relations.

    An anchored binding is a pure function of the linked SoundCloud URL, so it is
    re-derived every time and dropped the moment the URL no longer leads to exactly one
    artist (the account was re-linked, or MusicBrainz changed). A binding the user
    confirmed is never second-guessed. With no binding, a name search offers
    candidates — and binds nothing.
    """
    binding = musicbrainz_binding(collection_id)
    if binding is None or binding["anchored"]:
        anchored = mb.artists_for_url(sc_url) if sc_url else []
        if len(anchored) == 1:
            if binding is None or binding["mbid"] != anchored[0]["mbid"]:
                _set_musicbrainz(collection_id, anchored[0]["mbid"], MB_ANCHORED_CONFIDENCE)
            binding = musicbrainz_binding(collection_id)
        else:
            if binding is not None:
                drop_musicbrainz(collection_id)
                binding = None
            if len(anchored) > 1:
                report["musicbrainz"] = STATUS_AMBIGUOUS
                report["musicbrainz_detail"] = (
                    "MusicBrainz ties this SoundCloud profile to several artists."
                )
                return []
    if binding is None:
        report["musicbrainz_candidates"] = musicbrainz_candidates(names, mb)
        report["musicbrainz"] = (
            STATUS_NEEDS_CONFIRMATION if report["musicbrainz_candidates"] else STATUS_NO_MATCH
        )
        return []
    artist = mb.artist_with_urls(binding["mbid"])
    if artist is None:
        report["musicbrainz"] = STATUS_NOT_FOUND
        return []
    report["musicbrainz"] = STATUS_OK
    return from_musicbrainz(artist.get("relations") or [])


def refresh(
    collection_id: str,
    *,
    names: Sequence[str],
    sc_urn: str = "",
    sc_permalink: str | None = None,
    token: str = "",
    budget: sc_api.CallBudget | None = None,
    use_musicbrainz: bool = True,
    sc_user_fetch: Callable[..., Any] | None = None,
    sc_profiles_fetch: Callable[..., Any] | None = None,
    mb: Any = mb_client,
) -> dict[str, Any]:
    """Ask every source once, fold the answers into the store, report per source.

    User-initiated only (the Find-links click, or right after the user linked an
    account). ``sources`` is the honesty contract, as in the catalogue: a source that
    was not reached says so, and the links it contributed before stay untouched.
    """
    report: dict[str, Any] = {
        "soundcloud": STATUS_NOT_LINKED,
        "musicbrainz": STATUS_NOT_QUERIED,
    }
    tagged: list[tuple[LinkCandidate, str]] = []
    answered: set[str] = set()
    run_budget = budget or sc_api.CallBudget(
        limit=LINKS_CALL_BUDGET, label=f"links:{collection_id}"
    )

    if not sc_urn:
        # No bound account means no account links: what an earlier binding contributed
        # goes (it may have been the wrong account — that is why people unlink). Hidden
        # rows and manual ones survive, as everywhere else.
        answered.update({schema.LINK_SOURCE_SC_PROFILE, schema.LINK_SOURCE_SC_BIO})
    elif not token:
        report["soundcloud"] = STATUS_NOT_CONNECTED
    else:
        user_fetch = sc_user_fetch or sc_api.get_user
        profiles_fetch = sc_profiles_fetch or sc_api.get_user_web_profiles
        try:
            profile = user_fetch(sc_urn, token, budget=run_budget)
            if profile is None:
                report["soundcloud"] = (
                    STATUS_SKIPPED_BUDGET if run_budget.exhausted else STATUS_NOT_FOUND
                )
            else:
                profiles = profiles_fetch(sc_urn, token, budget=run_budget)
                tagged += [
                    (c, schema.LINK_SOURCE_SC_PROFILE)
                    for c in from_soundcloud_profile(profile, profiles)
                ]
                tagged += [
                    (c, schema.LINK_SOURCE_SC_BIO)
                    for c in extract_bio_links(profile.get("description"))
                ]
                report["soundcloud"] = STATUS_OK
                answered.update({schema.LINK_SOURCE_SC_PROFILE, schema.LINK_SOURCE_SC_BIO})
                sc_permalink = str(profile.get("permalink_url") or "") or sc_permalink
        except sc_api.AuthExpiredError:
            report["soundcloud"] = STATUS_NOT_CONNECTED
        except (requests.RequestException, sc_api.RateLimitError, ValueError) as exc:
            logger.warning(
                "op=artist_links_refresh source=soundcloud collection=%s err=%s",
                collection_id,
                type(exc).__name__,
            )
            report["soundcloud"] = STATUS_FAILED

    if use_musicbrainz:
        try:
            mb_links = _refresh_musicbrainz(
                collection_id, names, _soundcloud_url(sc_permalink), mb, report
            )
            tagged += [(c, schema.LINK_SOURCE_MUSICBRAINZ) for c in mb_links]
            if report["musicbrainz"] == STATUS_OK:
                answered.add(schema.LINK_SOURCE_MUSICBRAINZ)
        except (mb_client.MusicBrainzError, ValueError) as exc:
            logger.warning(
                "op=artist_links_refresh source=musicbrainz collection=%s err=%s",
                collection_id,
                exc,
            )
            report["musicbrainz"] = STATUS_FAILED

    counts = schema.merge_fetched_web_links(collection_id, best_per_key(tagged), answered)
    sources = {"soundcloud": report["soundcloud"], "musicbrainz": report["musicbrainz"]}
    schema.record_link_fetch(collection_id, sources)
    logger.info(
        "op=artist_links_refresh collection=%s soundcloud=%s musicbrainz=%s added=%d "
        "updated=%d removed=%d calls=%d",
        collection_id,
        sources["soundcloud"],
        sources["musicbrainz"],
        counts["added"],
        counts["updated"],
        counts["removed"],
        run_budget.used,
    )
    return {
        **list_links(collection_id),
        "sources": sources,
        "musicbrainz_detail": report.get("musicbrainz_detail"),
        "musicbrainz_candidates": report.get("musicbrainz_candidates") or [],
        "changes": counts,
        "calls_used": run_budget.used,
    }


# --------------------------------------------------------------------------- account suggestions


_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def rank_soundcloud_accounts(
    users: Iterable[Mapping[str, Any]], names: Sequence[str], limit: int = 5
) -> list[dict[str, Any]]:
    """Order SoundCloud search hits for the "which account is theirs?" picker.

    ``exact`` — the display name, full name or permalink folds to one of the artist's
    spellings; ``close`` — the same after dropping punctuation and spaces
    (``boysnoize``); ``weak`` otherwise. Within a tier, more followers first. Only a
    ranking: the user still clicks the account they mean.
    """
    keys = {k for k in (fold_key(n) for n in names) if k}
    compact = {c for c in (_NON_ALNUM.sub("", k) for k in keys) if c}
    tiers = {"exact": 0, "close": 1, "weak": 2}
    ranked: list[tuple[int, int, dict[str, Any]]] = []
    fields = (
        "urn",
        "username",
        "full_name",
        "permalink_url",
        "avatar_url",
        "followers_count",
        "track_count",
        "city",
        "country",
    )
    for user in users:
        spellings = (user.get("username"), user.get("full_name"), user.get("permalink"))
        folded = [fold_key(str(s)) for s in spellings if s]
        if any(f in keys for f in folded):
            match = "exact"
        elif any(_NON_ALNUM.sub("", f) in compact for f in folded):
            match = "close"
        else:
            match = "weak"
        row = {k: user.get(k) for k in fields}
        row["match"] = match
        ranked.append((tiers[match], -int(user.get("followers_count") or 0), row))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return [row for _, _, row in ranked[: max(0, limit)]]
