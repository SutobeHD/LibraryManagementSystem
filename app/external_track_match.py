"""external_track_match — shared title/version parsing + fuzzy-match + fingerprint.

Single home for the track-identity primitives four sister docs depend on
(remix-detector, extended-remix-finder, quality-upgrade-finder,
underground-mainstream). M1 lifts the SoundCloud sync engine's title normaliser +
fuzzy matcher to module-level pure functions and adds the version-tag parser +
fingerprint/adapter surface the sisters consume.

Pure, stdlib-only, no DB/network/async at module level. The only module state is
``ADAPTER_REGISTRY`` (tests reset it via an autouse fixture). ``master.db`` writers,
``_db_write_lock``, and ``rbox``/``pyrekordbox`` are deliberately NOT imported —
enforced by ``test_module_has_no_db_writer_imports``.

Scope note: M1 ships the parsing/matching core + a PATH-detect fingerprint shell
(no ``fpcalc`` binary bundled — degrades to unavailable). Real source adapters
(Discogs/Beatport) are M2/M3; the ``SourcePlugin`` Protocol + registry exist now so
they slot in without an API change.
"""

from __future__ import annotations

import contextlib
import logging
import re
import shutil
import subprocess
import time
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

logger = logging.getLogger(__name__)

#: Canonical version label set (12 members). Order = stem-family first
#: (original→acapella), then derivation-family (vip→mashup). Set semantics:
#: ordering is for readability only. Shared verbatim with analysis-remix-detector.
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

VERSION_LABELS: frozenset[str] = frozenset(
    {
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
    }
)


# ── Dataclasses ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class VersionTag:
    """A parsed version descriptor. ``modifiers`` carries compound/year tokens."""

    label: VersionLabel
    remixer: str | None = None
    modifiers: tuple[str, ...] = ()


@dataclass(frozen=True)
class Candidate:
    """One external-source match returned by ``SourcePlugin.search``."""

    source: str
    source_id: str
    title: str
    artist: str
    duration_s: float | None = None
    version_tag: VersionTag | None = None
    url: str | None = None
    raw: dict = field(default_factory=dict, hash=False, compare=False)


@dataclass(frozen=True)
class Fingerprint:
    """A computed acoustic fingerprint (Chromaprint via ``fpcalc``)."""

    fpcalc_hash: str
    duration_s: float


# ── Fingerprint-unavailable sentinels ──────────────────────────────────────────


@dataclass(frozen=True)
class FingerprintUnavailable:
    """Base sentinel: fingerprinting could not produce a result."""

    reason: str


@dataclass(frozen=True)
class BinaryMissing(FingerprintUnavailable):
    """``fpcalc`` not found on PATH (M1 default — binary not bundled)."""


@dataclass(frozen=True)
class Timeout(FingerprintUnavailable):
    """``fpcalc`` exceeded the timeout."""


@dataclass(frozen=True)
class DecodeError(FingerprintUnavailable):
    """``fpcalc`` ran but failed to decode the audio / parse output."""


# ── Adapter errors ──────────────────────────────────────────────────────────────


class AdapterError(Exception):
    """Base of the source-adapter error hierarchy."""


class AdapterNotRegistered(AdapterError):
    """Lookup for an adapter name absent from the registry."""


class AdapterTransportError(AdapterError):
    """Network/HTTP failure inside a ``SourcePlugin.search``."""


class AdapterQuotaExceeded(AdapterError):
    """Adapter refused because its API quota is exhausted."""


class AdapterParseError(AdapterError):
    """Adapter could not parse a source payload."""


# ── SourcePlugin Protocol + registry ────────────────────────────────────────────


@runtime_checkable
class SourcePlugin(Protocol):
    """Duck-typed external-source adapter. No class hierarchy required."""

    name: str

    async def search(
        self, title: str, artist: str, duration_s: float | None = None, *, max_results: int = 20
    ) -> list[Candidate]: ...

    def parse_version(self, raw: str) -> VersionTag | None: ...

    def quota_remaining(self) -> int | None: ...


ADAPTER_REGISTRY: dict[str, SourcePlugin] = {}


def register_adapter(name: str, plugin: SourcePlugin) -> None:
    """Register (or replace) an adapter under ``name``. Idempotent."""
    ADAPTER_REGISTRY[name] = plugin


def get_adapter(name: str) -> SourcePlugin:
    """Look up a registered adapter; raise :class:`AdapterNotRegistered` if absent."""
    try:
        return ADAPTER_REGISTRY[name]
    except KeyError:
        raise AdapterNotRegistered(name) from None


def list_adapters() -> list[str]:
    """Names of all registered adapters."""
    return sorted(ADAPTER_REGISTRY)


# ── Pure title functions ─────────────────────────────────────────────────────────

_NON_WORD_RE = re.compile(r"[^\w\s]")
_FEAT_RE = re.compile(r"\s+(feat\.?|ft\.?|featuring|with)\s+.*$", re.IGNORECASE)
_TAIL_PAREN_RE = re.compile(r"\s*[(\[][^()\[\]]*[)\]]\s*$")
_TRAILING_DASH_VARIANT_RE = re.compile(
    r"\s[-–—]\s.*$",  # noqa: RUF001 - en/em dashes are real title separators
)


def normalize_title(title: str, *, nfd_fold: bool = True) -> str:
    """Lowercase, accent-fold, strip non-word punctuation.

    Lift of ``SoundCloudSyncEngine._normalize_title``. ``nfd_fold`` (default on)
    adds NFD accent-folding — new vs the current stdlib-only behaviour; callers
    needing byte-equivalence with the old matcher pass ``nfd_fold=False``.
    """
    text = title.lower().strip()
    if nfd_fold:
        text = "".join(
            c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c)
        )
    return _NON_WORD_RE.sub("", text)


@lru_cache(maxsize=4096)
def extract_title_stem(title: str, *, drop_features: bool = True) -> str:
    """Strip tail variant groups + optional feat. clauses → canonical grouping root.

    Removes trailing ``(...)``/``[...]`` groups and ``- Extended Mix`` style
    trailing-dash variants; with ``drop_features`` also drops ``feat./ft.`` tails.
    Result is lowercased + whitespace-collapsed (NOT punctuation-stripped — that's
    :func:`normalize_title`'s job).
    """
    text = title.strip()
    if drop_features:
        text = _FEAT_RE.sub("", text)
    # Strip repeated tail par/bracket groups (e.g. "X (a) (b)").
    prev = None
    while prev != text:
        prev = text
        text = _TAIL_PAREN_RE.sub("", text)
    text = _TRAILING_DASH_VARIANT_RE.sub("", text)
    return re.sub(r"\s+", " ", text).strip().lower()


# parse_version_tag regex catalogue — anchored at title tail, case-insensitive.
# Shapes lifted verbatim from analysis-remix-detector Findings 2026-05-15.
_PURE_VARIANT_RE = re.compile(
    r"[(\[](?P<v>Original|Extended|Radio|Club|Dub|Instrumental|Acapella|VIP)"
    r"(?:\s+(?:Mix|Edit|Version|Cut))?[)\]]\s*$",
    re.IGNORECASE,
)
_YEAR_EDIT_RE = re.compile(
    r"[(\[](?P<year>(?:19|20)\d{2})\s+(?P<kind>Edit|Remaster(?:ed)?|Version)[)\]]\s*$",
    re.IGNORECASE,
)
_REMIXER_RE = re.compile(
    r"[(\[](?P<remixer>[^()\[\]]+?)\s+"
    r"(?P<kind>Remix|Bootleg|Edit|Rework|Flip|Refix|Mashup|Dub|VIP)[)\]]\s*$",
    re.IGNORECASE,
)
_COMPOUND_RE = re.compile(
    r"[(\[](?P<remixer>[^()\[\]]+?)\s+(?P<mod>Extended|Club|Dub|Instrumental)\s+"
    r"(?P<kind>Remix|Mix)[)\]]\s*$",
    re.IGNORECASE,
)
_TRAILING_DASH_TAG_RE = re.compile(
    r"\s[-–—]\s(?P<v>Extended|Radio|Club|Dub|Instrumental|Acapella|VIP|Original)"  # noqa: RUF001
    r"(?:\s+(?:Mix|Edit|Version))?\s*$",
    re.IGNORECASE,
)

#: Derivation-kind token → canonical label.
_KIND_TO_LABEL: dict[str, VersionLabel] = {
    "remix": "remix",
    "bootleg": "bootleg",
    "flip": "bootleg",
    "refix": "bootleg",
    "rework": "bootleg",
    "edit": "edit",
    "remaster": "edit",
    "remastered": "edit",
    "version": "edit",
    "mashup": "mashup",
    "dub": "dub",
    "vip": "vip",
}


def _pure_label(token: str) -> VersionLabel:
    """Map a pure-variant token (Original/Extended/...) to its canonical label."""
    return token.lower()  # type: ignore[return-value]  # token ∈ VERSION_LABELS by regex


def parse_version_tag(title: str) -> VersionTag | None:
    """Parse the tail version descriptor of ``title`` → :class:`VersionTag` or ``None``.

    Title-only (no source context): an adapter's ``parse_version`` overrides
    source-aware cases (e.g. SoundCloud ``original mix`` = radio cut). Returns
    ``None`` when no recognised variant suffix is present.
    """
    if not title:
        return None

    # Compound ("(Artist Extended Remix)") before the plainer remixer shape so the
    # modifier token isn't swallowed into the remixer name.
    m = _COMPOUND_RE.search(title)
    if m:
        kind = m.group("kind").lower()
        label: VersionLabel = "remix" if kind == "remix" else "extended"
        return VersionTag(
            label=label,
            remixer=m.group("remixer").strip(),
            modifiers=(m.group("mod").title(), "Remix" if kind == "remix" else "Mix"),
        )

    m = _YEAR_EDIT_RE.search(title)
    if m:
        return VersionTag(label="edit", remixer=None, modifiers=(m.group("year"),))

    m = _REMIXER_RE.search(title)
    if m:
        kind = m.group("kind").lower()
        mapped = _KIND_TO_LABEL.get(kind, "remix")
        return VersionTag(
            label=mapped,
            remixer=m.group("remixer").strip(),
            modifiers=(m.group("kind").title(),),
        )

    m = _PURE_VARIANT_RE.search(title)
    if m:
        token = m.group("v")
        return VersionTag(label=_pure_label(token), remixer=None, modifiers=(token.title(),))

    m = _TRAILING_DASH_TAG_RE.search(title)
    if m:
        token = m.group("v")
        return VersionTag(label=_pure_label(token), remixer=None, modifiers=(token.title(),))

    return None


def fuzzy_match_with_score(
    query_title: str,
    query_artist: str,
    candidates: dict[str, dict],
    *,
    threshold: float = 0.65,
) -> tuple[str | None, float]:
    """Best fuzzy match over ``candidates`` → ``(best_id_or_None, rounded_score)``.

    Verbatim port of ``SoundCloudSyncEngine._fuzzy_match_with_score``: combined
    ``artist - title`` ``SequenceMatcher`` ratio, with an exact-normalised-title
    short-circuit returning score ``1.0``. ``candidates`` maps id → track dict with
    ``Title`` / ``Artist`` keys.
    """
    from difflib import SequenceMatcher

    sc_combined = f"{query_artist} - {query_title}".lower()
    sc_norm_title = normalize_title(query_title, nfd_fold=False)
    best_match: str | None = None
    best_ratio = 0.0

    for tid, track in candidates.items():
        local_title = (track.get("Title") or "").lower()
        local_artist = (track.get("Artist") or "").lower()
        local_combined = f"{local_artist} - {local_title}"

        if sc_norm_title and sc_norm_title == normalize_title(local_title, nfd_fold=False):
            return tid, 1.0

        ratio = SequenceMatcher(None, sc_combined, local_combined).ratio()
        if ratio > best_ratio and ratio >= threshold:
            best_ratio = ratio
            best_match = tid

    return best_match, round(best_ratio, 3)


# ── Fingerprint surface (PATH-detect only at M1) ─────────────────────────────────


@lru_cache(maxsize=1)
def is_fingerprinting_available() -> bool:
    """True iff ``fpcalc`` is resolvable on PATH (cached). Lets callers skip batches."""
    return shutil.which("fpcalc") is not None


def fingerprint(
    audio_path: str | Path,
    *,
    sample_seconds: int = 120,
    timeout: float = 10.0,
    allowed_roots: list[Path] | None = None,
) -> Fingerprint | FingerprintUnavailable:
    """Compute a Chromaprint fingerprint via ``fpcalc``.

    Validates ``audio_path`` is inside an allowed root before spawning the
    subprocess (sandbox). ``allowed_roots`` defaults to a lazy import of
    ``app.main.ALLOWED_AUDIO_ROOTS`` (kept lazy so an empty-at-import value
    doesn't bind). Returns a :class:`FingerprintUnavailable` subclass rather than
    raising on the expected failure modes.
    """
    if not is_fingerprinting_available():
        return BinaryMissing("fpcalc not found on PATH")

    path = Path(audio_path).resolve()
    if allowed_roots is None:
        try:
            from app.main import ALLOWED_AUDIO_ROOTS as _roots

            allowed_roots = [Path(r).resolve() for r in _roots]
        except Exception:
            allowed_roots = []
    if not any(path.is_relative_to(root) for root in allowed_roots):
        return DecodeError(f"path outside allowed roots: {path}")

    started = time.monotonic()
    try:
        proc = subprocess.run(
            ["fpcalc", "-length", str(sample_seconds), str(path)],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return Timeout(f"fpcalc exceeded {timeout}s")
    elapsed = time.monotonic() - started
    logger.info("fpcalc path=%s elapsed=%.3fs rc=%d", path, elapsed, proc.returncode)

    if proc.returncode != 0:
        return DecodeError(f"fpcalc rc={proc.returncode}: {proc.stderr.strip()[:200]}")

    fp_hash: str | None = None
    duration: float | None = None
    for line in proc.stdout.splitlines():
        if line.startswith("FINGERPRINT="):
            fp_hash = line[len("FINGERPRINT=") :].strip()
        elif line.startswith("DURATION="):
            with contextlib.suppress(ValueError):
                duration = float(line[len("DURATION=") :].strip())
    if not fp_hash or duration is None:
        return DecodeError("fpcalc output missing FINGERPRINT/DURATION")
    return Fingerprint(fpcalc_hash=fp_hash, duration_s=duration)
