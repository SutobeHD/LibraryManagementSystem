"""Quality-tier classification + lossless-first candidate picking.

Implements the owner's **lossless-first hard rule** (Findings § "Quality
policy hardening", 2026-05-13): among 100%-match candidates a lossless source
ALWAYS beats any lossy source — unconditionally, regardless of platform order,
latency, or which responded first. The downloader never *silently* delivers a
lossy ``.m4a`` / ``.mp3``.

The rule is encoded structurally in :class:`app.downloader.models.QualityTier`
(Tier 0/1 lossless always sort ahead of Tier 2/3/4 lossy). This module:

* :func:`classify` — maps a :class:`TrackMatch`'s *claimed* format/bit-depth/
  sample-rate/bitrate onto a :class:`QualityTier`.
* :func:`is_lossless` — Tier 0/1 predicate.
* :func:`pick_best` — index of the best-quality candidate (lossless-first by
  construction of the sort key).
* :func:`pick_with_policy` — applies the ``lossless_only`` setting and reports
  whether the winner is a lossy pick (so the UI can badge it).

See ``docs/research/implement/accepted_downloader-unified-multi-source.md``
§ "P2.10 — app/downloader/quality.py".
"""

from __future__ import annotations

from .models import QualityTier, TrackMatch

#: Lossless container/codec set. Membership here means Tier 0 or Tier 1.
_LOSSLESS_FORMATS: frozenset[str] = frozenset({"flac", "alac", "wav", "aiff"})

#: The two lossless tiers — used by :func:`is_lossless`.
_LOSSLESS_TIERS: tuple[QualityTier, QualityTier] = (
    QualityTier.HIRES_LOSSLESS,
    QualityTier.CD_LOSSLESS,
)


def classify(m: TrackMatch) -> QualityTier:
    """Classify a :class:`TrackMatch` into a :class:`QualityTier` from its claims.

    Lossless formats (FLAC/ALAC/WAV/AIFF) split into hi-res (≥ 24-bit OR
    > 44.1 kHz) vs CD-rate. Lossy formats split purely by claimed bitrate:
    ≥ 256 kbps → high, ≥ 128 kbps → standard, below → last-resort. Format is
    quality-neutral within a tier — MP3 and AAC at the same bitrate tie.
    """
    if m.claimed_format in _LOSSLESS_FORMATS:
        if (m.claimed_bit_depth or 16) >= 24 or (m.claimed_sample_rate_hz or 44100) > 44100:
            return QualityTier.HIRES_LOSSLESS
        return QualityTier.CD_LOSSLESS

    # Lossy — ranked by bitrate only.
    br = m.claimed_bitrate_kbps or 0
    if br >= 256:
        return QualityTier.HIGH_LOSSY
    if br >= 128:
        return QualityTier.STANDARD_LOSSY
    return QualityTier.LAST_RESORT


def is_lossless(m: TrackMatch) -> bool:
    """Return ``True`` when ``m`` classifies into a lossless tier (0 or 1)."""
    return classify(m) in _LOSSLESS_TIERS


def pick_best(candidates: list[TrackMatch]) -> int:
    """Return the index of the best-quality candidate.

    Sorts by :meth:`TrackMatch.quality_sort_key`, which encodes the
    lossless-first hard rule: every Tier 0/1 candidate sorts ahead of every
    Tier 2/3/4 candidate, unconditionally. Stable on ties — insertion order
    breaks them, so the first-listed of two equal-quality claims wins.

    Raises:
        ValueError: if ``candidates`` is empty.
    """
    if not candidates:
        raise ValueError("no candidates")
    indexed = sorted(enumerate(candidates), key=lambda iv: iv[1].quality_sort_key())
    return indexed[0][0]


def pick_with_policy(
    candidates: list[TrackMatch],
    *,
    lossless_only: bool,
) -> tuple[int | None, bool]:
    """Pick a candidate under the owner's lossless-first policy.

    Returns ``(picked_index, is_lossy_pick)``:

    * ``lossless_only=True`` + at least one lossless candidate exists → the
      best lossless one; ``is_lossy_pick=False``.
    * ``lossless_only=True`` + no lossless candidate → ``(None, True)``. The
      caller surfaces "no lossless source found" and lets the user explicitly
      accept the lossy file or skip — **never a silent lossy download**.
    * ``lossless_only=False`` → the best candidate overall; ``is_lossy_pick``
      is ``True`` when that winner is Tier ≥ 2 so the UI can badge it.

    An empty candidate list returns ``(None, False)`` — nothing to pick, and
    nothing lossy was delivered.
    """
    if not candidates:
        return None, False

    lossless_indices = [i for i, c in enumerate(candidates) if is_lossless(c)]

    if lossless_only:
        if not lossless_indices:
            # Caller decides — the policy refuses to silently fetch lossy.
            return None, True
        best = min(lossless_indices, key=lambda i: candidates[i].quality_sort_key())
        return best, False

    best = pick_best(candidates)
    return best, not is_lossless(candidates[best])


__all__ = ["classify", "is_lossless", "pick_best", "pick_with_policy"]
