"""Shared track-matching, version-tag taxonomy, fingerprint and adapter-registry module.

This module is the single source of truth for three sister features
(remix-detector, extended-remix-finder, quality-upgrade-finder). It owns:

* the fuzzy track matcher (lifted verbatim from ``SoundCloudSyncEngine``),
* the canonical ``VersionTag`` taxonomy + a title-stem extractor,
* a ``fpcalc`` (Chromaprint) fingerprint wrapper with PATH-detect graceful
  degradation,
* an adapter-registry plugin slot (``SourcePlugin`` Protocol) so every
  external source (SoundCloud / Discogs / Beatport / ...) exposes one
  ``search`` interface.

Read-only by design: no master-DB writes, no DB-write-lock acquisition, no
Rekordbox-library parser imports. Match results are transient ``Candidate``
objects — persistence is each sister feature's own concern.

See ``docs/research/implement/accepted_external-track-match-unified-module.md``
for the full design rationale (M1 scope).
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from functools import lru_cache
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Canonical version-tag taxonomy
# ──────────────────────────────────────────────────────────────────────────────

# Canonical 12-member label vocabulary. Ordering rule: stem-family first
# (original, extended, radio, club, dub, instrumental, acapella) then
# derivative-family (vip, remix, bootleg, edit, mashup). Members are aligned
# with the sister-docs; only this module owns the enumeration.
VersionLabel = Literal[
    "original",
    "extended",
    "radio",
    "club",
    "dub",
    "instrumental",
    "acapella",
    "vip",
    "remix",
    "bootleg",
    "edit",
    "mashup",
]

#: Tuple form of the canonical label set — for membership checks in tests
#: and callers that need to iterate the vocabulary.
VERSION_LABELS: tuple[VersionLabel, ...] = (
    "original",
    "extended",
    "radio",
    "club",
    "dub",
    "instrumental",
    "acapella",
    "vip",
    "remix",
    "bootleg",
    "edit",
    "mashup",
)


# ──────────────────────────────────────────────────────────────────────────────
# Frozen dataclasses
# ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class VersionTag:
    """A parsed version descriptor.

    ``label`` is the canonical primary classification. ``remixer`` carries the
    artist name when the tag is a remix/bootleg/edit/mashup attributed to a
    third party. ``modifiers`` carries compound / year tokens (e.g.
    ``("2024",)`` for a year-edit, ``("Extended", "Remix")`` for a compound
    "Extended Remix"). Frozen + tuple-typed so instances are hashable and
    cheap to use as ``parametrize`` ids.
    """

    label: VersionLabel
    remixer: str | None = None
    modifiers: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Candidate:
    """A single match candidate returned from a ``SourcePlugin.search`` call.

    ``raw`` is an escape-hatch holding the source-specific payload (SoundCloud
    ``permalink``, Discogs ``release_id``, ...) so callers that need a field
    the canonical shape does not expose can still reach it.
    """

    source: str
    source_id: str
    title: str
    artist: str
    duration_s: float | None
    version_tag: VersionTag | None
    url: str | None
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Fingerprint:
    """A successful ``fpcalc`` (Chromaprint) fingerprint result."""

    fpcalc_hash: str
    duration_s: float


# ──────────────────────────────────────────────────────────────────────────────
# Fingerprint failure sentinels
# ──────────────────────────────────────────────────────────────────────────────


class FingerprintUnavailable:
    """Namespace of importable singleton sentinels for fingerprint failure.

    ``fingerprint()`` returns one of these singletons (never the class itself)
    when it cannot produce a real :class:`Fingerprint`. Callers branch with
    ``isinstance(result, FingerprintUnavailable)`` for the general case, or
    compare against a specific singleton (``result is FingerprintUnavailable.BINARY_MISSING``)
    for the precise failure mode.
    """

    class _Reason:
        """A single fingerprint-failure sentinel."""

        __slots__ = ("reason",)

        def __init__(self, reason: str) -> None:
            self.reason = reason

        def __repr__(self) -> str:
            return f"<FingerprintUnavailable.{self.reason}>"

    #: ``fpcalc`` is not on PATH.
    BINARY_MISSING: _Reason
    #: ``fpcalc`` exceeded its subprocess timeout.
    TIMEOUT: _Reason
    #: ``fpcalc`` ran but could not decode the audio file.
    DECODE_ERROR: _Reason

    def __init__(self) -> None:  # pragma: no cover - never instantiated
        raise TypeError("FingerprintUnavailable is a sentinel namespace, not instantiable")


FingerprintUnavailable.BINARY_MISSING = FingerprintUnavailable._Reason("BINARY_MISSING")
FingerprintUnavailable.TIMEOUT = FingerprintUnavailable._Reason("TIMEOUT")
FingerprintUnavailable.DECODE_ERROR = FingerprintUnavailable._Reason("DECODE_ERROR")

#: Convenient union for type hints / isinstance checks.
FingerprintResult = "Fingerprint | FingerprintUnavailable._Reason"


# ──────────────────────────────────────────────────────────────────────────────
# Adapter error hierarchy
# ──────────────────────────────────────────────────────────────────────────────


class AdapterError(Exception):
    """Base class for every adapter-registry / adapter-transport failure."""


class AdapterNotRegistered(AdapterError):
    """Raised by :func:`get_adapter` when the requested name is unknown."""


class AdapterTransportError(AdapterError):
    """Raised by an adapter when an external HTTP call fails irrecoverably."""


class AdapterQuotaExceeded(AdapterError):
    """Raised by an adapter when the source's rate / quota limit is hit."""


class AdapterParseError(AdapterError):
    """Raised by an adapter when a source response cannot be parsed."""


# ──────────────────────────────────────────────────────────────────────────────
# SourcePlugin Protocol
# ──────────────────────────────────────────────────────────────────────────────


@runtime_checkable
class SourcePlugin(Protocol):
    """Duck-typed interface every external source adapter implements.

    Adapters are registered into :data:`ADAPTER_REGISTRY` via
    :func:`register_adapter` and looked up by :func:`get_adapter`. ``search``
    is async because adapters are HTTP-bound; the pure matcher functions in
    this module stay synchronous.
    """

    name: str

    async def search(
        self,
        title: str,
        artist: str,
        duration_s: float | None = None,
        *,
        max_results: int = 20,
    ) -> list[Candidate]:
        """Search the source. Empty list on no match; raises ``AdapterError`` on transport failure."""
        ...

    def parse_version(self, raw: dict) -> VersionTag | None:
        """Reverse-lookup a :class:`VersionTag` from the source's native metadata."""
        ...

    def quota_remaining(self) -> int | None:
        """Best-effort remaining-quota hint. ``None`` when unknown."""
        ...


# ──────────────────────────────────────────────────────────────────────────────
# Adapter registry
# ──────────────────────────────────────────────────────────────────────────────

#: Module-level registry singleton. Mutated at adapter import / app boot.
ADAPTER_REGISTRY: dict[str, SourcePlugin] = {}


def register_adapter(name: str, plugin: SourcePlugin) -> None:
    """Register (or replace) an adapter under ``name``. Idempotent."""
    ADAPTER_REGISTRY[name] = plugin


def get_adapter(name: str) -> SourcePlugin:
    """Return the adapter registered under ``name``.

    Raises:
        AdapterNotRegistered: if no adapter is registered under that name.
    """
    try:
        return ADAPTER_REGISTRY[name]
    except KeyError:
        raise AdapterNotRegistered(name) from None


def list_adapters() -> list[str]:
    """Return the names of every currently registered adapter."""
    return list(ADAPTER_REGISTRY.keys())


# ──────────────────────────────────────────────────────────────────────────────
# Pure string functions — normalisation + stem extraction
# ──────────────────────────────────────────────────────────────────────────────


def normalize_title(title: str) -> str:
    """Lowercase, strip, accent-fold and drop non-word punctuation.

    The core of the rule is lifted verbatim from
    ``SoundCloudSyncEngine._normalize_title`` (``app/soundcloud_api.py``):
    ``re.sub(r'[^\\w\\s]', '', title.lower().strip())``. Accent-folding via
    Unicode NFD decomposition is added on top — ``'Pacífico' -> 'pacifico'`` —
    so accented and unaccented spellings of the same title collide.
    """
    folded = _strip_accents(title)
    return re.sub(r"[^\w\s]", "", folded.lower().strip())


def _strip_accents(text: str) -> str:
    """Fold accented Latin characters to their base form via NFD decomposition."""
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


# Trailing parenthetical / bracket group at the very end of a title, e.g.
# "Strobe (Radio Edit)" or "Strobe [Extended Mix]". Applied repeatedly to
# peel nested / multi-suffix groups ("Song (Remix) (2024 Edit)").
_TAIL_GROUP_RE = re.compile(r"\s*[\(\[\{][^\(\)\[\]\{\}]*[\)\]\}]\s*$")

# "feat." / "ft." / "featuring" / "with" clause — everything from the keyword
# to the end of the (already paren-stripped) string.
_FEATURE_RE = re.compile(
    r"\s*(?:feat\.?|ft\.?|featuring|with)\s+.*$",
    re.IGNORECASE,
)

# Trailing-dash variant, e.g. "Strobe - Extended Mix". Only the last
# dash-delimited segment is dropped, and only when it looks like a version
# descriptor (ends in a known mix/edit keyword) so artist-dash-title strings
# survive intact.
_DASH_VARIANT_RE = re.compile(
    r"\s+-\s+[^-]*\b(?:mix|edit|version|remix|bootleg|dub|edct|"
    r"instrumental|acapella|a cappella|vip|flip|refix|rework|remaster(?:ed)?)\b\s*$",
    re.IGNORECASE,
)


@lru_cache(maxsize=4096)
def extract_title_stem(title: str, *, drop_features: bool = True) -> str:
    """Strip version suffixes and (optionally) feature clauses down to a stem.

    Removes — in order — trailing parenthetical/bracket groups (repeatedly,
    for nested/multi-suffix titles), the trailing-dash variant
    (``- Extended Mix``) and, when ``drop_features`` is true,
    ``feat.``/``ft.``/``featuring``/``with`` clauses. The result is lowercased,
    accent-folded and whitespace-collapsed so equivalent titles collapse to one
    canonical root for grouping:

        ``extract_title_stem("Strobe (Radio Edit)")``
        ``== extract_title_stem("Strobe - Extended Mix")``
        ``== extract_title_stem("Strobe (Deadmau5 Club Mix)")``
        ``== "strobe"``

    Cached (``lru_cache(4096)``) — the result is a pure function of its args.
    """
    if not title:
        return ""

    stem = title.strip()

    # Peel trailing paren/bracket groups, repeatedly (handles nesting).
    prev: str | None = None
    while prev != stem:
        prev = stem
        stem = _TAIL_GROUP_RE.sub("", stem).strip()

    # Drop a trailing-dash version segment ("- Extended Mix").
    stem = _DASH_VARIANT_RE.sub("", stem).strip()

    # Optionally drop a "feat. X" / "with X" clause.
    if drop_features:
        stem = _FEATURE_RE.sub("", stem).strip()

    # Canonicalise: accent-fold, lowercase, collapse internal whitespace.
    stem = _strip_accents(stem).lower()
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem


# ──────────────────────────────────────────────────────────────────────────────
# Version-tag parsing
# ──────────────────────────────────────────────────────────────────────────────

# Keyword → (label, canonical-modifier) collapse table. Order matters: the
# parser scans this list and the FIRST keyword found in the title's suffix
# wins, so more-specific multi-word keywords are listed before bare ones.
_VERSION_KEYWORDS: tuple[tuple[str, VersionLabel, str], ...] = (
    # extended family
    ("extended mix", "extended", "Extended"),
    ("extended version", "extended", "Extended"),
    ("extended remix", "remix", "Extended"),
    ("extended", "extended", "Extended"),
    ("long version", "extended", "Long"),
    ("full version", "extended", "Full"),
    ('12" mix', "extended", '12"'),
    ('12" version', "extended", '12"'),
    ("club mix", "club", "Club"),
    ("club version", "club", "Club"),
    ("club edit", "club", "Club"),
    # radio family
    ("radio edit", "radio", "Radio"),
    ("radio mix", "radio", "Radio"),
    ("radio version", "radio", "Radio"),
    ("short edit", "radio", "Short"),
    ("clean edit", "radio", "Clean"),
    ("intro edit", "radio", "Intro"),
    ("single edit", "radio", "Single"),
    ("single version", "radio", "Single"),
    # dub
    ("dub mix", "dub", "Dub"),
    ("dub version", "dub", "Dub"),
    ("dub", "dub", "Dub"),
    # instrumental
    ("instrumental mix", "instrumental", "Instrumental"),
    ("instrumental version", "instrumental", "Instrumental"),
    ("instrumental", "instrumental", "Instrumental"),
    # acapella
    ("acappella", "acapella", "Acapella"),
    ("a cappella", "acapella", "Acapella"),
    ("acapella", "acapella", "Acapella"),
    # vip
    ("vip mix", "vip", "VIP"),
    ("vip edit", "vip", "VIP"),
    ("vip", "vip", "VIP"),
    # derivative-family (remixer-bearing)
    ("extended remix", "remix", "Remix"),
    ("remix", "remix", "Remix"),
    ("bootleg", "bootleg", "Bootleg"),
    ("flip", "bootleg", "Flip"),
    ("refix", "bootleg", "Refix"),
    ("rework", "bootleg", "Rework"),
    ("mashup", "mashup", "Mashup"),
    ("mash up", "mashup", "Mashup"),
    ("remaster", "edit", "Remaster"),
    ("remastered", "edit", "Remaster"),
    ("edit", "edit", "Edit"),
    ("original mix", "original", "Original"),
    ("original version", "original", "Original"),
    ("original", "original", "Original"),
    ("club", "club", "Club"),
)

# Year token, e.g. "2024" — captured as a modifier for year-edits / remasters.
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")

# Labels whose tag should carry a remixer name when one is present.
_REMIXER_BEARING: frozenset[VersionLabel] = frozenset(
    {"remix", "bootleg", "edit", "mashup", "club", "vip", "dub"}
)

# Keywords that, on their own, are not enough to attribute a remixer (they
# describe a cut of the original, not a third-party rework).
_NON_ATTRIBUTING = frozenset(
    {"Extended", "Long", "Full", '12"', "Radio", "Short", "Clean", "Intro", "Single", "Original"}
)


def _iter_suffix_groups(title: str) -> list[str]:
    """Return the text of every trailing paren/bracket group, outermost-last.

    ``"Song (feat. X) (Deadmau5 Remix)"`` -> ``["feat. X", "Deadmau5 Remix"]``.
    """
    groups: list[str] = []
    remaining = title.strip()
    while True:
        m = _TAIL_GROUP_RE.search(remaining)
        if not m:
            break
        inner = m.group(0).strip()
        inner = inner[1:-1].strip()  # drop the bracket pair
        groups.append(inner)
        remaining = remaining[: m.start()].rstrip()
    groups.reverse()
    return groups


def _classify_segment(segment: str) -> tuple[VersionLabel, str] | None:
    """Match a single suffix segment against the keyword table.

    Returns ``(label, modifier)`` for the first keyword found, else ``None``.
    """
    lowered = segment.lower()
    for keyword, label, modifier in _VERSION_KEYWORDS:
        if keyword in lowered:
            return label, modifier
    return None


def _extract_remixer(segment: str, keyword_modifier: str) -> str | None:
    """Pull a remixer name out of a ``"<Remixer> Remix"``-style segment.

    Everything before the trailing version keyword(s) is treated as the
    remixer. Returns ``None`` when nothing meaningful is left.
    """
    text = segment.strip()
    # Strip any trailing version keyword tokens (e.g. "Remix", "Extended Remix").
    trailing = re.compile(
        r"\s*\b(?:extended|long|full|club|radio|short|clean|intro|single|original|"
        r"vip|dub|instrumental|acapella|a cappella|remix|bootleg|flip|refix|rework|"
        r"mashup|mash up|edit|remaster(?:ed)?|mix|version)\b\s*$",
        re.IGNORECASE,
    )
    prev: str | None = None
    while prev != text:
        prev = text
        text = trailing.sub("", text).strip()
    # Drop a leading "feat./ft./by" if it leaked in.
    text = re.sub(r"^(?:feat\.?|ft\.?|by|featuring)\s+", "", text, flags=re.IGNORECASE).strip()
    if not text or text.lower() in {"the", "a"}:
        return None
    # A bare year is a modifier, not a remixer.
    if _YEAR_RE.fullmatch(text):
        return None
    return text


@lru_cache(maxsize=4096)
def parse_version_tag(title: str) -> VersionTag | None:
    """Parse a :class:`VersionTag` from a track title.

    Inspects trailing parenthetical/bracket groups first (the canonical place
    for version info), then falls back to a trailing-dash segment. Captures a
    remixer name for remix/bootleg/edit/mashup tags and a 4-digit year as a
    modifier. Returns ``None`` when the title carries no recognised version
    suffix.

    Cached (``lru_cache(4096)``) — pure function of ``title``.
    """
    if not title:
        return None

    segments: list[str] = list(_iter_suffix_groups(title))

    # Fall back to the trailing-dash segment if no bracket groups carry info.
    dash_match = _DASH_VARIANT_RE.search(title)
    if dash_match:
        dash_seg = dash_match.group(0).lstrip(" -").strip()
        segments.append(dash_seg)

    if not segments:
        return None

    # Scan segments outermost-last so the most specific (last) version wins,
    # but remember any feature-only segment so it does not shadow a real tag.
    chosen: tuple[VersionLabel, str] | None = None
    chosen_segment = ""
    for segment in segments:
        classified = _classify_segment(segment)
        if classified is not None:
            chosen = classified
            chosen_segment = segment

    if chosen is None:
        return None

    label, modifier = chosen
    modifiers: list[str] = []

    # A year token in the chosen segment is a modifier (year-edit / remaster).
    year_match = _YEAR_RE.search(chosen_segment)
    if year_match:
        modifiers.append(year_match.group(0))

    if modifier:
        modifiers.append(modifier)

    # Capture a remixer for derivative tags.
    remixer: str | None = None
    if label in _REMIXER_BEARING and modifier not in _NON_ATTRIBUTING:
        remixer = _extract_remixer(chosen_segment, modifier)

    # De-duplicate modifiers while preserving order.
    seen: set[str] = set()
    ordered_modifiers: list[str] = []
    for mod in modifiers:
        if mod not in seen:
            seen.add(mod)
            ordered_modifiers.append(mod)

    return VersionTag(label=label, remixer=remixer, modifiers=tuple(ordered_modifiers))


# ──────────────────────────────────────────────────────────────────────────────
# Fuzzy matching — lifted from SoundCloudSyncEngine._fuzzy_match_with_score
# ──────────────────────────────────────────────────────────────────────────────


def fuzzy_match_with_score(
    query_title: str,
    query_artist: str,
    candidates: dict,
    *,
    threshold: float = 0.65,
) -> tuple[str | None, float]:
    """Find the best matching candidate and return ``(best_id_or_None, score)``.

    Direct lift of ``SoundCloudSyncEngine._fuzzy_match_with_score`` — same
    ``difflib.SequenceMatcher`` ratio over the combined ``"artist - title"``
    haystack, same exact-normalised-title short-circuit returning
    ``(tid, 1.0)``, same ``round(score, 3)`` return shape. ``candidates`` maps
    an id to a track dict with ``"Title"`` / ``"Artist"`` keys.

    The ``threshold`` (default ``0.65``, the SC-calibrated value) is now a
    keyword argument so sister features can pick a stricter / looser cutoff at
    the call site.
    """
    sc_combined = f"{query_artist} - {query_title}".lower()
    sc_norm_title = normalize_title(query_title)
    best_match: str | None = None
    best_ratio = 0.0

    for tid, track in candidates.items():
        local_title = (track.get("Title") or "").lower()
        local_artist = (track.get("Artist") or "").lower()
        local_combined = f"{local_artist} - {local_title}"

        # Exact normalised-title match wins immediately.
        if sc_norm_title and sc_norm_title == normalize_title(local_title):
            return tid, 1.0

        ratio = SequenceMatcher(None, sc_combined, local_combined).ratio()
        if ratio > best_ratio and ratio >= threshold:
            best_ratio = ratio
            best_match = tid

    return best_match, round(best_ratio, 3)


# ──────────────────────────────────────────────────────────────────────────────
# Fingerprinting — fpcalc (Chromaprint) wrapper with PATH-detect
# ──────────────────────────────────────────────────────────────────────────────

_FPCALC_BINARY = "fpcalc"


@lru_cache(maxsize=1)
def _fpcalc_path() -> str | None:
    """Resolve the ``fpcalc`` executable on PATH. Cached (PATH does not move mid-run)."""
    return shutil.which(_FPCALC_BINARY)


def is_fingerprinting_available() -> bool:
    """Return ``True`` when ``fpcalc`` is on PATH.

    Cached PATH-detect — callers short-circuit batch fingerprint jobs without
    paying a subprocess spawn per file.
    """
    return _fpcalc_path() is not None


def _resolve_audio_root_guard(audio_path: Path) -> None:
    """Validate ``audio_path`` against ``ALLOWED_AUDIO_ROOTS`` before subprocess.

    Mirrors the sandbox in ``app/main.py:validate_audio_path``. Imported lazily
    so this module stays importable in test contexts that never boot
    ``app.main``. When the allow-list is empty (e.g. ``app.main`` was never
    imported) the guard is a no-op — the caller is responsible for only handing
    in trusted paths in that case.

    Raises:
        ValueError: if the path resolves outside every allowed root.
    """
    try:
        from app.main import ALLOWED_AUDIO_ROOTS
    except Exception:  # pragma: no cover - app.main optional in unit tests
        return

    if not ALLOWED_AUDIO_ROOTS:
        return

    resolved = audio_path.resolve()
    if not any(resolved.is_relative_to(root) for root in ALLOWED_AUDIO_ROOTS):
        raise ValueError(
            f"audio path {resolved} is outside the allowed audio roots — refusing to fingerprint"
        )


def fingerprint(
    audio_path: str | Path,
    *,
    sample_seconds: int = 120,
    timeout: float = 10.0,
) -> Fingerprint | FingerprintUnavailable._Reason:
    """Fingerprint a local audio file via ``fpcalc`` (Chromaprint).

    Returns a :class:`Fingerprint` on success, or one of the
    :class:`FingerprintUnavailable` sentinels when ``fpcalc`` is missing,
    times out, or fails to decode the file. Never raises on a missing binary
    or a decode failure — degradation is graceful by design so M1 can ship
    fingerprint-optional.

    When ``fpcalc`` is available the ``audio_path`` is validated against
    ``ALLOWED_AUDIO_ROOTS`` *before* the subprocess is spawned (path-traversal
    guard, per coding-rules). The PATH-detect short-circuit runs first so a
    missing binary is reported even for a path that would not pass the guard.

    Args:
        audio_path: local file to fingerprint.
        sample_seconds: how many seconds ``fpcalc`` samples (``-length``).
        timeout: subprocess timeout ceiling in seconds.

    Raises:
        ValueError: if ``audio_path`` is outside the allowed audio roots.
    """
    path = Path(audio_path)

    binary = _fpcalc_path()
    if binary is None:
        logger.info("fpcalc not on PATH — fingerprinting unavailable")
        return FingerprintUnavailable.BINARY_MISSING

    # Path-traversal guard — runs before the subprocess is ever spawned.
    _resolve_audio_root_guard(path)

    cmd = [binary, "-length", str(sample_seconds), str(path)]
    start = _now()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.warning("fpcalc path=%s timed out after %.1fs", path, timeout)
        return FingerprintUnavailable.TIMEOUT
    except OSError as exc:
        logger.warning("fpcalc path=%s failed to launch: %s", path, exc)
        return FingerprintUnavailable.BINARY_MISSING

    elapsed = _now() - start
    if proc.returncode != 0:
        logger.warning(
            "fpcalc path=%s exited %d elapsed=%.3f stderr=%s",
            path,
            proc.returncode,
            elapsed,
            (proc.stderr or "").strip()[:200],
        )
        return FingerprintUnavailable.DECODE_ERROR

    parsed = _parse_fpcalc_output(proc.stdout)
    if parsed is None:
        logger.warning("fpcalc path=%s produced unparseable output elapsed=%.3f", path, elapsed)
        return FingerprintUnavailable.DECODE_ERROR

    logger.info("fpcalc path=%s elapsed=%.3f", path, elapsed)
    return parsed


def _parse_fpcalc_output(stdout: str) -> Fingerprint | None:
    """Parse ``fpcalc``'s ``DURATION=...`` / ``FINGERPRINT=...`` stdout block."""
    duration: float | None = None
    fp_hash: str | None = None
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("DURATION="):
            try:
                duration = float(line[len("DURATION=") :])
            except ValueError:
                return None
        elif line.startswith("FINGERPRINT="):
            fp_hash = line[len("FINGERPRINT=") :].strip()
    if not fp_hash or duration is None:
        return None
    return Fingerprint(fpcalc_hash=fp_hash, duration_s=duration)


def _now() -> float:
    """Monotonic clock read — isolated so tests can patch it if needed."""
    import time

    return time.monotonic()


# ──────────────────────────────────────────────────────────────────────────────
# SoundCloud adapter — first real SourcePlugin
# ──────────────────────────────────────────────────────────────────────────────

#: SoundCloud public API base (mirrors ``app/soundcloud_api.SC_API_BASE``).
_SC_API_BASE = "https://api.soundcloud.com"

#: SoundCloud-specific override: a SoundCloud ``original mix`` is a radio cut,
#: not a canonical extended cut (per the doc's source-aware collapse table).
_SC_VERSION_OVERRIDES: dict[str, VersionLabel] = {
    "original mix": "radio",
    "original": "radio",
}


class SoundCloudAdapter:
    """``SourcePlugin`` adapter wrapping SoundCloud track search.

    Uses the existing ``app.soundcloud_api`` HTTP plumbing (``_sc_get`` with
    429-backoff + auth-error translation) so this module does not re-implement
    SoundCloud transport. ``search`` hits the public ``/tracks`` endpoint and
    maps each hit onto a :class:`Candidate`.
    """

    name = "soundcloud"

    def __init__(self, auth_token: str | None = None) -> None:
        self._auth_token = auth_token

    async def search(
        self,
        title: str,
        artist: str,
        duration_s: float | None = None,
        *,
        max_results: int = 20,
    ) -> list[Candidate]:
        """Search SoundCloud for ``"<artist> <title>"``.

        Runs the (synchronous) ``requests``-based SoundCloud client in a worker
        thread so this coroutine never blocks the event loop.

        Raises:
            AdapterTransportError: on any SoundCloud transport / auth failure.
        """
        import asyncio

        query = f"{artist} {title}".strip() or title.strip()
        try:
            raw_tracks = await asyncio.to_thread(self._search_sync, query, max_results)
        except AdapterError:
            raise
        except Exception as exc:
            raise AdapterTransportError(f"SoundCloud search failed: {exc}") from exc

        return [c for c in (self._to_candidate(t) for t in raw_tracks) if c is not None]

    def _search_sync(self, query: str, max_results: int) -> list[dict]:
        """Blocking SoundCloud ``/tracks?q=`` call. Run via ``asyncio.to_thread``."""
        from app.soundcloud_api import (
            AuthExpiredError,
            RateLimitError,
            SoundCloudPlaylistAPI,
            _sc_get,
            get_sc_client_id,
        )

        headers = SoundCloudPlaylistAPI._get_headers(self._auth_token)
        params: dict = {"q": query, "limit": max_results}
        if not self._auth_token:
            params["client_id"] = get_sc_client_id()

        try:
            resp = _sc_get(f"{_SC_API_BASE}/tracks", headers=headers, params=params, timeout=15)
        except RateLimitError as exc:
            raise AdapterQuotaExceeded(str(exc)) from exc
        except AuthExpiredError as exc:
            raise AdapterTransportError(str(exc)) from exc

        data = resp.json()
        if isinstance(data, dict):
            collection = data.get("collection", [])
        elif isinstance(data, list):
            collection = data
        else:
            raise AdapterParseError(f"unexpected SoundCloud /tracks payload type: {type(data)}")
        if not isinstance(collection, list):
            raise AdapterParseError("SoundCloud /tracks collection is not a list")
        return [t for t in collection if isinstance(t, dict)]

    def _to_candidate(self, raw: dict) -> Candidate | None:
        """Map a raw SoundCloud track object onto a :class:`Candidate`."""
        track_id = raw.get("id")
        if not track_id:
            return None
        title = raw.get("title", "") or ""
        user = raw.get("user", {})
        artist = user.get("username", "") if isinstance(user, dict) else ""
        duration_ms = raw.get("duration")
        duration_s = (duration_ms / 1000.0) if isinstance(duration_ms, (int, float)) else None
        return Candidate(
            source=self.name,
            source_id=str(track_id),
            title=title,
            artist=artist,
            duration_s=duration_s,
            version_tag=self.parse_version(raw),
            url=raw.get("permalink_url"),
            raw=raw,
        )

    def parse_version(self, raw: dict) -> VersionTag | None:
        """Parse a :class:`VersionTag` from a SoundCloud track's ``title``.

        Applies the SoundCloud-specific source-aware override: a SoundCloud
        ``original mix`` denotes a radio cut, so the bare title parse is
        re-labelled to ``radio``.
        """
        title = raw.get("title", "") if isinstance(raw, dict) else ""
        if not title:
            return None
        tag = parse_version_tag(title)
        lowered = title.lower()
        for token, override in _SC_VERSION_OVERRIDES.items():
            if token in lowered:
                modifiers = tag.modifiers if tag else ()
                if "Original" not in modifiers:
                    modifiers = (*modifiers, "Original")
                return VersionTag(label=override, remixer=None, modifiers=modifiers)
        return tag

    def quota_remaining(self) -> int | None:
        """SoundCloud exposes no quota header — always ``None`` (unknown)."""
        return None


def register_soundcloud_adapter(auth_token: str | None = None) -> SoundCloudAdapter:
    """Build a :class:`SoundCloudAdapter` and register it under ``"soundcloud"``."""
    adapter = SoundCloudAdapter(auth_token=auth_token)
    register_adapter(adapter.name, adapter)
    return adapter


__all__ = [
    "ADAPTER_REGISTRY",
    "VERSION_LABELS",
    "AdapterError",
    "AdapterNotRegistered",
    "AdapterParseError",
    "AdapterQuotaExceeded",
    "AdapterTransportError",
    "Candidate",
    "Fingerprint",
    "FingerprintUnavailable",
    "SoundCloudAdapter",
    "SourcePlugin",
    "VersionLabel",
    "VersionTag",
    "extract_title_stem",
    "fingerprint",
    "fuzzy_match_with_score",
    "get_adapter",
    "is_fingerprinting_available",
    "list_adapters",
    "normalize_title",
    "parse_version_tag",
    "register_adapter",
    "register_soundcloud_adapter",
]
