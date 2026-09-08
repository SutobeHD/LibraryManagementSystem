"""artist_store.identity — name-based, remix-aware track roles + the identity table.

Owner decision 2026-09-08: most of a label-signed artist's catalogue is uploaded by
labels, promo channels and DJs, so "uploader URN equality" alone misses most of it.
The artist is identified by their **name** — in the title's artist prefix, in the
uploader name, in a remixer credit — with explicit care for remixes. The uploader-URN
match stays the HIGHEST-confidence signal; it just stops being the only one. Linking
an artist to an account stays manual.

Every fetched track gets exactly one role **for this artist** plus a confidence:

  * ``primary``          — the artist is the main credit.
  * ``remixer``          — the artist made this remix/edit/flip of someone else's track.
                           THIS IS THEIR MUSIC — a DJ wants their own remixes.
  * ``remixed_by_other`` — the artist is the main credit but the parenthetical credits
                           someone else. Listed separately, never auto-queued.
  * ``featured``         — ``feat./ft./with Artist`` only.
  * ``uncertain``        — name only in tags, a near-spelling, an unparseable mention,
                           or no credit at all. Review bucket: never auto-queued, never
                           counted as missing.

Name comparison is :func:`app.artist_store.merge.fold_key` — deterministic, no edit
distance. A false attribution is worse than a missed one, so a name that only *nearly*
matches lands in ``uncertain`` with the near-spelling shown, never in ``primary``.

The remix rules, spelled out, because they are the ones that go wrong:

  * ``Overdrive (Boys Noize Remix)``               -> ``remixer`` for Boys Noize
  * ``Boys Noize - Overdrive (Erol Alkan Remix)``  -> ``remixed_by_other`` for Boys Noize,
                                                     ``remixer`` for Erol Alkan
  * ``Boys Noize - Overdrive (Extended Mix)``      -> ``primary``
  * a name that appears ONLY inside ``(X Remix)`` is never ``primary``.

:func:`auto_queue_eligible` is the single rule the route and the UI share:
``role in {primary, remixer} and confidence in {high, medium}``.

The identity table (``track_identity``, migration v2 in ``schema.py``) is the owner's
"local file with artist id + universal track id": ISRC when the upload carries one, the
SoundCloud URN as the fallback key, one row per ``(collection, track)``. A pinned
``user_override`` WINS over the classifier on every subsequent pass.

Pure apart from the sidecar: no HTTP, no ``master.db``, no token anywhere near it.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.artist_store import registry, schema
from app.artist_store.catalogue import (
    PROVIDER_SOUNDCLOUD,
    coerce_track,
    normalize_user_urn,
)
from app.artist_store.merge import fold_key
from app.external_track_match import parse_version_tag

logger = logging.getLogger("ARTIST_STORE")

ROLE_PRIMARY = schema.ROLE_PRIMARY
ROLE_REMIXER = schema.ROLE_REMIXER
ROLE_REMIXED_BY_OTHER = schema.ROLE_REMIXED_BY_OTHER
ROLE_FEATURED = schema.ROLE_FEATURED
ROLE_UNCERTAIN = schema.ROLE_UNCERTAIN
ROLES = schema.IDENTITY_ROLES

CONFIDENCE_HIGH = schema.CONFIDENCE_HIGH
CONFIDENCE_MEDIUM = schema.CONFIDENCE_MEDIUM
CONFIDENCE_LOW = schema.CONFIDENCE_LOW
CONFIDENCES = schema.IDENTITY_CONFIDENCES

#: The one auto-queue rule. Everything outside it is review-only.
AUTO_QUEUE_ROLES = frozenset({ROLE_PRIMARY, ROLE_REMIXER})
AUTO_QUEUE_CONFIDENCES = frozenset({CONFIDENCE_HIGH, CONFIDENCE_MEDIUM})

#: ``credit_parse.matched_on`` — which signal decided the role.
SIGNAL_UPLOADER_URN = "uploader_urn"
SIGNAL_TITLE_PREFIX = "title_prefix"
SIGNAL_UPLOADER_NAME = "uploader_name"
SIGNAL_REMIX_CREDIT = "remix_credit"
SIGNAL_FEATURED_CREDIT = "featured_credit"
SIGNAL_TAGS = "tags"
SIGNAL_NEAR_MATCH = "near_match"
SIGNAL_TITLE_MENTION = "title_mention"
SIGNAL_NONE = "none"
SIGNAL_USER_OVERRIDE = "user_override"

SOURCE_CLASSIFIER = "classifier"
SOURCE_USER_OVERRIDE = "user_override"

# ── Title grammar ─────────────────────────────────────────────────────────────

#: "Artist - Title" — the first spaced dash (ASCII, en, em) splits prefix from body.
_PREFIX_SPLIT = re.compile(r"\s[-–—]\s")  # noqa: RUF001 - en/em dashes are real separators

#: Promo channels prefix the real credit: "PREMIERE: Boys Noize - Overdrive".
_LEADING_TAG = re.compile(
    r"^(?:premiere|first listen|exclusive|free download|free dl|out now|new)\s*[:|]\s*",
    re.IGNORECASE,
)

#: Featured credits. ``with`` and ``w/`` only count inside a bracket group — in running
#: title text they are ordinary words ("Dancing with Tears in My Eyes").
_FEAT_RE = re.compile(
    r"(?:^|[\s(\[])(?:feat\.?|ft\.?|featuring)\s+(?P<names>[^()\[\]]+?)"
    r"(?=\s*[)\]]|\s+[-–—]\s|\s*[(\[]|$)",  # noqa: RUF001
    re.IGNORECASE,
)
_WITH_GROUP_RE = re.compile(
    r"[(\[]\s*(?:with|w/)\s+(?P<names>[^()\[\]]+?)\s*[)\]]",
    re.IGNORECASE,
)
_FEAT_GROUP_RE = re.compile(
    r"\s*[(\[]\s*(?:feat\.?|ft\.?|featuring|with|w/)\s+[^()\[\]]*[)\]]",
    re.IGNORECASE,
)
_FEAT_TAIL_RE = re.compile(r"\s+(?:feat\.?|ft\.?|featuring)\s+.*$", re.IGNORECASE)

#: Separators between co-credited names ("Boys Noize & Skrillex", "A x B", "A, B").
_NAME_SEP = re.compile(r"\s*(?:,|&|\+|/|\bx\b|\bvs\.?\b|\band\b|\bb2b\b)\s*", re.IGNORECASE)

_TRAILING_GROUP = re.compile(r"\s*[(\[][^()\[\]]*[)\]]\s*$")

#: Derivation kinds that name a remixer. Matches the set ``parse_version_tag`` knows.
_KINDS = "remix|bootleg|edit|rework|flip|refix|mashup|vip|dub"
_DASH_REMIX_RE = re.compile(
    rf"\s[-–—]\s(?P<name>[^-–—()\[\]]+?)\s+(?P<kind>{_KINDS})\s*$",  # noqa: RUF001
    re.IGNORECASE,
)
_BARE_GROUP_RE = re.compile(r"[(\[]\s*(?P<word>[A-Za-z]+)(?:\s+(?:19|20)\d{2})?\s*[)\]]\s*$")
_UNATTRIBUTED_TAIL_RE = re.compile(
    r"\s(?P<kind>remix|bootleg|edit|rework|refix|flip|mashup)$", re.IGNORECASE
)

#: A bare "(Remix)" / "(Edit)" with no name is a derivation by SOMEONE — unknown who.
_UNATTRIBUTED_WORDS = frozenset(
    {
        "remix",
        "bootleg",
        "edit",
        "rework",
        "refix",
        "flip",
        "mashup",
        "rerub",
        "redux",
        "reprise",
        "reimagined",
        "interpretation",
    }
)

#: Words that describe a VERSION, not a person. ``parse_version_tag`` reads
#: "(Radio Edit)" / "(Club Dub)" as remixer="Radio"/"Club"; this set catches that.
_VERSION_VOCAB = frozenset(
    {
        "original",
        "extended",
        "radio",
        "club",
        "dub",
        "instrumental",
        "acapella",
        "acappella",
        "vip",
        "mix",
        "edit",
        "version",
        "cut",
        "remix",
        "short",
        "long",
        "full",
        "album",
        "single",
        "vocal",
        "remaster",
        "remastered",
        "dirty",
        "clean",
        "explicit",
        "intro",
        "outro",
        "re",
        "master",
        "the",
    }
)

_NON_ALNUM = re.compile(r"[^0-9a-z]+")
_QUOTES = re.compile(r"[\"“”]")


# ── Public rule ───────────────────────────────────────────────────────────────


def auto_queue_eligible(role: str, confidence: str) -> bool:
    """The single auto-queue rule. ``primary``/``remixer`` at ``high``/``medium`` only.

    ``uncertain``, ``featured`` and ``remixed_by_other`` are review-only whatever their
    confidence; ``low`` is review-only whatever the role.
    """
    return role in AUTO_QUEUE_ROLES and confidence in AUTO_QUEUE_CONFIDENCES


# ── Name folding ──────────────────────────────────────────────────────────────


def _compact(folded: str) -> str:
    """Fold with every non-alphanumeric removed — the near-match tier (``boysnoize``)."""
    return _NON_ALNUM.sub("", folded)


def _split_names(text: str) -> list[str]:
    pieces = [p.strip(" .,") for p in _NAME_SEP.split(text)]
    return [p for p in pieces if p]


@dataclass(frozen=True)
class _Names:
    """The artist's spellings, folded once per classify call."""

    raw: tuple[str, ...]
    strict: frozenset[str]
    compact: frozenset[str]
    suffix_patterns: tuple[re.Pattern[str], ...]

    @classmethod
    def build(cls, names: Iterable[str]) -> _Names:
        raw: list[str] = []
        strict: set[str] = set()
        for name in names:
            text = str(name or "").strip()
            key = fold_key(text)
            if not text or not key:
                continue
            raw.append(text)
            strict.add(key)
        compact = {c for c in (_compact(k) for k in strict) if c}
        patterns = tuple(
            re.compile(rf"(?:^|\s){re.escape(key)}\s+({_KINDS})$") for key in sorted(strict)
        )
        return cls(tuple(raw), frozenset(strict), frozenset(compact), patterns)

    def matches(self, candidate: str | None) -> bool:
        """Exact fold match of a whole credit or any of its co-credited pieces."""
        if not candidate:
            return False
        if fold_key(candidate) in self.strict:
            return True
        return any(fold_key(piece) in self.strict for piece in _split_names(candidate))

    def near(self, candidate: str | None) -> str | None:
        """The piece that matches only after compacting — evidence for ``uncertain``."""
        if not candidate:
            return None
        for piece in [candidate, *_split_names(candidate)]:
            key = fold_key(piece)
            if key and key not in self.strict and _compact(key) in self.compact:
                return piece.strip()
        return None

    def mentioned_in(self, text: str) -> bool:
        haystack = f" {fold_key(_QUOTES.sub(' ', text))} "
        return any(f" {key} " in haystack for key in self.strict)

    def suffix_credit(self, folded_body: str) -> str | None:
        """``... boys noize remix`` with no brackets — the credited kind, or None."""
        for pattern in self.suffix_patterns:
            m = pattern.search(folded_body)
            if m:
                return m.group(1)
        return None


# ── Credit parsing ────────────────────────────────────────────────────────────


@dataclass
class CreditParse:
    """What the title says, before any artist is compared against it.

    Everything here is shown to the user as the WHY behind a role. Raw spellings are
    kept as typed; folding happens only at comparison time.
    """

    title: str
    artist_prefix: str | None = None
    primary_names: list[str] = field(default_factory=list)
    title_body: str = ""
    title_tail: str = ""
    remixer: str | None = None
    remixer_names: list[str] = field(default_factory=list)
    remix_kind: str | None = None
    featured: list[str] = field(default_factory=list)
    version: str | None = None
    derivation_unattributed: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "artist_prefix": self.artist_prefix,
            "primary_names": list(self.primary_names),
            "title_body": self.title_body,
            "title_tail": self.title_tail,
            "remixer": self.remixer,
            "remixer_names": list(self.remixer_names),
            "remix_kind": self.remix_kind,
            "featured": list(self.featured),
            "version": self.version,
            "derivation_unattributed": self.derivation_unattributed,
        }


def _is_version_vocab(name: str) -> bool:
    words = fold_key(name).split()
    return bool(words) and all(w in _VERSION_VOCAB for w in words)


def _featured_names(text: str) -> list[str]:
    out: list[str] = []
    for regex in (_FEAT_RE, _WITH_GROUP_RE):
        for m in regex.finditer(text):
            for name in _split_names(m.group("names")):
                if name not in out:
                    out.append(name)
    return out


def _strip_feat(text: str) -> str:
    text = _FEAT_GROUP_RE.sub("", text)
    return _FEAT_TAIL_RE.sub("", text).strip()


def _parse_remix(body: str) -> tuple[str | None, str | None, str | None, bool, str]:
    """``(remixer, kind, version, unattributed, tail)`` read off a title body.

    Trailing groups that are not a version tag (``[BNR]``, a catalogue number) are
    peeled one at a time — at most three — so ``Overdrive (Erol Alkan Remix) [BNR]``
    still yields the remixer. A group whose "remixer" is pure version vocabulary
    (``(Radio Edit)``) is a version, not a person, and peeling continues.
    """
    tail = body.strip()
    version: str | None = None
    for _ in range(4):
        tag = parse_version_tag(tail)
        if tag is not None:
            if tag.remixer and not _is_version_vocab(tag.remixer):
                kind = tag.modifiers[-1] if tag.modifiers else tag.label.title()
                return tag.remixer.strip(), kind, version, False, tail
            version = version or " ".join(tag.modifiers) or tag.label.title()
        else:
            dash = _DASH_REMIX_RE.search(tail)
            if dash and not _is_version_vocab(dash.group("name")):
                return dash.group("name").strip(), dash.group("kind").title(), version, False, tail
            bare = _BARE_GROUP_RE.search(tail)
            if bare and bare.group("word").casefold() in _UNATTRIBUTED_WORDS:
                return None, bare.group("word").title(), version, True, tail
        group = _TRAILING_GROUP.search(tail)
        if group is None:
            break
        tail = tail[: group.start()].rstrip()
        if not tail:
            break
    if tail:
        loose = _UNATTRIBUTED_TAIL_RE.search(fold_key(tail))
        if loose:
            return None, loose.group("kind").title(), version, True, tail
    return None, None, version, False, tail


def parse_credit(title: str) -> CreditParse:
    """Split a SoundCloud title into artist prefix, body, remix credit and features.

    Pure string work; no artist is compared here. ``artist_prefix`` is only set when a
    spaced dash separates two non-empty halves — a lone ``-`` inside a word is not a
    credit boundary.
    """
    text = re.sub(r"\s+", " ", str(title or "")).strip()
    parse = CreditParse(title=text)
    if not text:
        return parse
    text = _LEADING_TAG.sub("", text).strip() or text
    parse.featured = _featured_names(text)

    body = text
    parts = _PREFIX_SPLIT.split(text, maxsplit=1)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        prefix, body = parts[0].strip(), parts[1].strip()
        parse.artist_prefix = prefix
        parse.primary_names = _split_names(_strip_feat(prefix))
    parse.title_body = body

    remixer, kind, version, unattributed, tail = _parse_remix(_strip_feat(body))
    parse.title_tail = tail
    parse.remixer = remixer
    parse.remixer_names = _split_names(remixer) if remixer else []
    parse.remix_kind = kind
    parse.version = version
    parse.derivation_unattributed = unattributed
    return parse


def _claim_suffix_credit(credit: CreditParse, names: _Names) -> None:
    """Resolve an unattributed ``… X Remix`` tail when X is one of the artist's names.

    ``parse_credit`` is name-agnostic and cannot tell where the title stem ends and an
    unbracketed remixer begins; with the artist's spellings in hand the tail
    ``bangarang boys noize remix`` is an exact, deterministic credit. Any other name in
    that position stays unattributed — no guessing at a stranger's boundary.
    """
    if credit.remixer or not credit.derivation_unattributed or not credit.title_tail:
        return
    folded_tail = fold_key(credit.title_tail)
    kind = names.suffix_credit(folded_tail)
    if kind is None:
        return
    matched = next(
        (raw for raw in names.raw if folded_tail.endswith(f"{fold_key(raw)} {kind.casefold()}")),
        None,
    )
    if matched is None:
        return
    credit.remixer = matched
    credit.remixer_names = [matched]
    credit.remix_kind = kind.title()
    credit.derivation_unattributed = False


# ── Decision ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Signals:
    uploader_linked: bool
    uploader_name_is_artist: bool
    prefix_is_artist: bool
    prefix_is_other: bool
    remixer_is_artist: bool
    remixer_is_other: bool
    featured_is_artist: bool
    derivation_unattributed: bool
    tag_mention: bool
    title_mention: bool
    near: str | None


def _signals(
    track: Mapping[str, Any], credit: CreditParse, names: _Names, own_urn: str
) -> _Signals:
    uploader_name = str(track.get("uploader_name") or "")
    prefix = credit.artist_prefix
    prefix_is_artist = names.matches(prefix)
    remixer_is_artist = names.matches(credit.remixer)
    near = names.near(prefix) or names.near(uploader_name) or names.near(credit.remixer)
    return _Signals(
        uploader_linked=bool(own_urn) and normalize_user_urn(track.get("uploader_urn")) == own_urn,
        uploader_name_is_artist=names.matches(uploader_name),
        prefix_is_artist=prefix_is_artist,
        prefix_is_other=bool(prefix) and not prefix_is_artist,
        remixer_is_artist=remixer_is_artist,
        remixer_is_other=bool(credit.remixer) and not remixer_is_artist,
        featured_is_artist=any(names.matches(f) for f in credit.featured),
        derivation_unattributed=credit.derivation_unattributed,
        tag_mention=names.mentioned_in(str(track.get("tag_list") or "")),
        title_mention=names.mentioned_in(credit.title),
        near=near,
    )


def _decide(sig: _Signals, credit: CreditParse) -> tuple[str, str, str, str]:
    """``(role, confidence, matched_on, reason)`` — the role model, in priority order."""
    kind = (credit.remix_kind or "Remix").lower()
    remixer = credit.remixer or "someone else"
    linked = sig.uploader_linked

    if sig.remixer_is_artist and not sig.prefix_is_artist:
        return (
            ROLE_REMIXER,
            CONFIDENCE_HIGH if linked else CONFIDENCE_MEDIUM,
            SIGNAL_REMIX_CREDIT,
            f"Credited as the {kind} artist in the title"
            + (", and uploaded by the linked account" if linked else ""),
        )

    if sig.prefix_is_artist:
        if sig.remixer_is_other:
            return (
                ROLE_REMIXED_BY_OTHER,
                CONFIDENCE_HIGH if linked else CONFIDENCE_MEDIUM,
                SIGNAL_TITLE_PREFIX,
                f"Main credit in the title, but the {kind} is by {remixer}",
            )
        if sig.derivation_unattributed and not linked:
            return (
                ROLE_UNCERTAIN,
                CONFIDENCE_LOW,
                SIGNAL_TITLE_PREFIX,
                f"Main credit in the title, but this is an unattributed {kind} from another uploader",
            )
        if linked:
            return (
                ROLE_PRIMARY,
                CONFIDENCE_HIGH,
                SIGNAL_UPLOADER_URN,
                "Uploaded by the linked account and credited as the artist in the title",
            )
        return (
            ROLE_PRIMARY,
            CONFIDENCE_MEDIUM,
            SIGNAL_TITLE_PREFIX,
            "Credited as the artist in the title prefix",
        )

    if linked:
        if sig.prefix_is_other:
            if sig.featured_is_artist:
                return (
                    ROLE_FEATURED,
                    CONFIDENCE_MEDIUM,
                    SIGNAL_FEATURED_CREDIT,
                    f"Uploaded by the linked account, but the title credits "
                    f"{credit.artist_prefix} as the artist and this artist only as featured",
                )
            return (
                ROLE_UNCERTAIN,
                CONFIDENCE_LOW,
                SIGNAL_UPLOADER_URN,
                f"Uploaded by the linked account, but the title credits "
                f"{credit.artist_prefix} as the artist",
            )
        if sig.remixer_is_other:
            return (
                ROLE_REMIXED_BY_OTHER,
                CONFIDENCE_HIGH,
                SIGNAL_UPLOADER_URN,
                f"Uploaded by the linked account; the {kind} is by {remixer}",
            )
        return (
            ROLE_PRIMARY,
            CONFIDENCE_HIGH,
            SIGNAL_UPLOADER_URN,
            "Uploaded by the linked SoundCloud account",
        )

    if sig.uploader_name_is_artist:
        if sig.prefix_is_other:
            return (
                ROLE_UNCERTAIN,
                CONFIDENCE_LOW,
                SIGNAL_UPLOADER_NAME,
                f"The uploader is named like the artist, but the title credits "
                f"{credit.artist_prefix}",
            )
        if sig.remixer_is_other:
            return (
                ROLE_REMIXED_BY_OTHER,
                CONFIDENCE_MEDIUM,
                SIGNAL_UPLOADER_NAME,
                f"Uploader named like the artist; the {kind} is by {remixer}",
            )
        if sig.derivation_unattributed:
            return (
                ROLE_UNCERTAIN,
                CONFIDENCE_LOW,
                SIGNAL_UPLOADER_NAME,
                f"Uploader named like the artist, but this is an unattributed {kind}",
            )
        return (
            ROLE_PRIMARY,
            CONFIDENCE_MEDIUM,
            SIGNAL_UPLOADER_NAME,
            "The uploader's display name matches, but the account is not the linked one",
        )

    if sig.featured_is_artist:
        return (
            ROLE_FEATURED,
            CONFIDENCE_LOW,
            SIGNAL_FEATURED_CREDIT,
            "Named only as a featured artist, on another account's upload",
        )
    if sig.tag_mention:
        return (ROLE_UNCERTAIN, CONFIDENCE_LOW, SIGNAL_TAGS, "Named only in the tags")
    if sig.near:
        return (
            ROLE_UNCERTAIN,
            CONFIDENCE_LOW,
            SIGNAL_NEAR_MATCH,
            f"'{sig.near}' is a near-spelling of the name, not an exact match",
        )
    if sig.title_mention:
        return (
            ROLE_UNCERTAIN,
            CONFIDENCE_LOW,
            SIGNAL_TITLE_MENTION,
            "The name appears in the title without a parseable credit",
        )
    return (ROLE_UNCERTAIN, CONFIDENCE_LOW, SIGNAL_NONE, "No credit for this artist on this track")


# ── Public API ────────────────────────────────────────────────────────────────


def classify_track(
    track: Mapping[str, Any],
    artist_urn: str | None,
    names: Sequence[str] | _Names,
    *,
    override: str | None = None,
) -> dict[str, Any]:
    """Role + confidence + WHY for one coerced track. Pure.

    ``override`` is the user's pinned role for this track; it replaces the classifier's
    verdict outright (``identity_source="user_override"``) while the classifier's own
    reading stays visible in ``classifier_role`` / ``classifier_confidence``.
    """
    folded = names if isinstance(names, _Names) else _Names.build(names)
    own_urn = normalize_user_urn(artist_urn)
    credit = parse_credit(str(track.get("title") or ""))
    _claim_suffix_credit(credit, folded)
    sig = _signals(track, credit, folded, own_urn)
    role, confidence, matched_on, reason = _decide(sig, credit)

    effective_role, effective_conf, source = role, confidence, SOURCE_CLASSIFIER
    if override is not None:
        if override not in ROLES:
            raise ValueError(f"unknown override role {override!r}")
        effective_role, effective_conf, source = override, CONFIDENCE_HIGH, SOURCE_USER_OVERRIDE
        matched_on = SIGNAL_USER_OVERRIDE
        reason = f"Pinned by you as {override} (classifier read: {role}, {confidence})"

    eligible = auto_queue_eligible(effective_role, effective_conf)
    # A track that has been through the ownership diff carries ``in_library``; an
    # owned track is never queued however strong its role. Before the diff the flag
    # is the role gate alone.
    if "in_library" in track:
        eligible = eligible and track.get("in_library") is False

    return {
        **track,
        "role": effective_role,
        "confidence": effective_conf,
        "classifier_role": role,
        "classifier_confidence": confidence,
        "identity_source": source,
        "auto_queue_allowed": eligible,
        "credit_parse": {
            **credit.as_dict(),
            "uploader_name": str(track.get("uploader_name") or ""),
            "uploader_linked": sig.uploader_linked,
            "label_name": str(track.get("label_name") or ""),
            "isrc": str(track.get("isrc") or ""),
            "near_match": sig.near,
            "matched_on": matched_on,
            "reason": reason,
        },
    }


def classify_roles(
    tracks: Iterable[Any],
    artist_urn: str | None,
    names: Sequence[str],
    *,
    overrides: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Role, confidence, ``auto_queue_allowed`` and ``credit_parse`` for every track.

    ``names`` is the canonical name plus every alias from the sidecar (see
    :func:`app.artist_store.registry.artist_names`); every one of them counts as the
    artist. ``artist_urn`` is the manually linked account (may be ``None`` — then no
    track can reach ``high`` through the uploader). ``overrides`` maps ``sc_id`` to a
    pinned role and wins over the classifier.

    Pure: nothing is read from or written to the sidecar here. Rows the catalogue
    coercion drops (no id / no title) are dropped here too, and duplicates by ``sc_id``
    keep their first occurrence — same contract as ``catalogue.coerce_tracks``, but
    extra keys already on a track (``in_library``, ``bucket`` …) are preserved.
    """
    folded = _Names.build(names)
    pins = dict(overrides or {})
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in tracks or []:
        coerced = coerce_track(raw)
        if coerced is None or coerced["sc_id"] in seen:
            continue
        seen.add(coerced["sc_id"])
        merged = {**dict(raw), **coerced} if isinstance(raw, Mapping) else coerced
        out.append(classify_track(merged, artist_urn, folded, override=pins.get(coerced["sc_id"])))
    return out


def role_counts(classified: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """Per-role tally of what was classified — nothing is counted that was not."""
    counts = dict.fromkeys(sorted(ROLES), 0)
    for track in classified:
        role = str(track.get("role") or "")
        if role in counts:
            counts[role] += 1
    return counts


def load_overrides(collection_id: str) -> dict[str, str]:
    """``sc_id -> pinned role`` for one collection, straight from the identity table."""
    return schema.get_identity_overrides(collection_id)


def remember_identities(collection_id: str, classified: Iterable[Mapping[str, Any]]) -> int:
    """Upsert the classifier's verdict per track into ``track_identity``.

    Writes the **classifier's** role/confidence, never the override-applied one — the
    pin lives in ``user_override`` and is not touched by this call. ``first_seen`` is
    kept, ``last_seen`` refreshed. Returns the number of rows written.

    The collection must exist (foreign key); a missing one raises
    ``sqlite3.IntegrityError`` rather than silently creating an orphan.
    """
    entries: list[dict[str, Any]] = []
    for track in classified:
        sc_id = str(track.get("sc_id") or "").strip()
        if not sc_id:
            continue
        entries.append(
            {
                "sc_urn": sc_id,
                "isrc": track.get("isrc") or None,
                "title": track.get("title") or None,
                "uploader_urn": track.get("uploader_urn") or None,
                "role": track.get("classifier_role") or track.get("role"),
                "confidence": track.get("classifier_confidence") or track.get("confidence"),
            }
        )
    written = schema.upsert_track_identities(collection_id, entries)
    logger.info("op=artist_identity_remember collection=%s rows=%d", collection_id, written)
    return written


def set_override(collection_id: str, sc_id: str, role: str | None) -> bool:
    """Pin (or with ``None`` unpin) a track's role for one artist. False if unknown track."""
    return schema.set_identity_override(collection_id, sc_id, role)


def classify_for_collection(
    collection_id: str,
    tracks: Iterable[Any],
    *,
    artist_urn: str | None = None,
    names: Sequence[str] | None = None,
    remember: bool = True,
) -> list[dict[str, Any]]:
    """Classify with the collection's link, spellings and pins, then remember the result.

    Convenience for the route: resolves ``artist_urn`` from the SoundCloud link and
    ``names`` from the registry when not supplied, applies the stored ``user_override``
    pins, and — unless ``remember=False`` — upserts the classifier's verdicts.
    """
    urn = artist_urn
    if urn is None:
        link = schema.get_link(collection_id, PROVIDER_SOUNDCLOUD)
        urn = str(link.get("remote_id") or "") if link else ""
    spellings = tuple(names) if names is not None else registry.artist_names(collection_id)
    classified = classify_roles(tracks, urn, spellings, overrides=load_overrides(collection_id))
    if remember and classified:
        remember_identities(collection_id, classified)
    return classified


__all__ = [
    "AUTO_QUEUE_CONFIDENCES",
    "AUTO_QUEUE_ROLES",
    "CONFIDENCES",
    "CONFIDENCE_HIGH",
    "CONFIDENCE_LOW",
    "CONFIDENCE_MEDIUM",
    "ROLES",
    "ROLE_FEATURED",
    "ROLE_PRIMARY",
    "ROLE_REMIXED_BY_OTHER",
    "ROLE_REMIXER",
    "ROLE_UNCERTAIN",
    "SIGNAL_FEATURED_CREDIT",
    "SIGNAL_NEAR_MATCH",
    "SIGNAL_NONE",
    "SIGNAL_REMIX_CREDIT",
    "SIGNAL_TAGS",
    "SIGNAL_TITLE_MENTION",
    "SIGNAL_TITLE_PREFIX",
    "SIGNAL_UPLOADER_NAME",
    "SIGNAL_UPLOADER_URN",
    "SIGNAL_USER_OVERRIDE",
    "SOURCE_CLASSIFIER",
    "SOURCE_USER_OVERRIDE",
    "CreditParse",
    "auto_queue_eligible",
    "classify_for_collection",
    "classify_roles",
    "classify_track",
    "load_overrides",
    "parse_credit",
    "remember_identities",
    "role_counts",
    "set_override",
]
