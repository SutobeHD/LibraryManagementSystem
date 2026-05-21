"""Thin matching adapter over the shared ``app.external_track_match`` module.

The downloader does **not** own a fuzzy matcher — that would be a 4th fork of
the same ``difflib.SequenceMatcher`` logic the shared ``external_track_match``
module exists to prevent. This adapter does only the two things the shared
matcher legitimately cannot:

1. **ISRC fast-path** — when both sides carry an ISRC and they are equal, the
   match is certain (confidence 1.0). ``external_track_match`` is
   title/artist-only and never sees an ISRC.
2. **±2 s duration hard-gate** — a D1 invariant: two tracks whose durations
   differ by more than 2 seconds are not the same recording, full stop.
   ``external_track_match`` knows nothing about duration either.

Everything title/artist is delegated to
:func:`app.external_track_match.fuzzy_match_with_score`.

See ``docs/research/implement/accepted_downloader-unified-multi-source.md``
§ "P2.8 + P2.9 — matching delegated to app/external_track_match.py (I1)".
"""

from __future__ import annotations

from app.external_track_match import (
    Candidate as XtmCandidate,
)
from app.external_track_match import (
    fuzzy_match_with_score,
    parse_version_tag,
)

from .models import MatchResult, TrackMatch

#: D1 duration invariant — durations farther apart than this (seconds) are
#: never the same recording, regardless of how well the titles match.
_DURATION_GATE_S: float = 2.0

#: D1's 100%-match bar for the delegated fuzzy score. ``fuzzy_match_with_score``
#: is invoked with its own internal ``threshold=0.65`` (so it returns a real
#: score rather than ``None`` for anything decent); the adapter then applies
#: this stricter cutoff to decide ``is_match``.
_FUZZY_MATCH_BAR: float = 0.92

#: Threshold handed to ``fuzzy_match_with_score`` itself — kept at the shared
#: module's SC-calibrated default so a real score is always returned for the
#: single candidate; the adapter re-judges with ``_FUZZY_MATCH_BAR``.
_FUZZY_INTERNAL_THRESHOLD: float = 0.65


def _to_xtm(m: TrackMatch) -> XtmCandidate:
    """Map a downloader :class:`TrackMatch` → an ``external_track_match.Candidate``.

    The shared ``Candidate`` has no quality/bitrate/format field, so the full
    :class:`TrackMatch` is parked in ``raw["track_match"]`` — fully recoverable
    by any caller that needs the quality data back. The version tag is parsed
    from the title via the shared :func:`parse_version_tag`.
    """
    return XtmCandidate(
        source=m.platform,
        source_id=m.url,
        title=m.title,
        artist=m.artist,
        duration_s=m.duration_s,
        version_tag=parse_version_tag(m.title),
        url=m.url,
        raw={"track_match": m},
    )


def match(
    needle: TrackMatch,
    candidates: list[TrackMatch],
) -> list[tuple[TrackMatch, MatchResult]]:
    """Run the 100%-match gate over ``candidates`` against ``needle``.

    For each candidate, in order:

    * **ISRC fast-path** — both ISRCs present and equal → immediate match
      (confidence 1.0, ``rule_fired="isrc_equality"``).
    * **duration hard-gate** — ``|needle.duration_s - cand.duration_s| > 2`` →
      immediate non-match (``rule_fired="duration_gate_failed"``).
    * **fuzzy delegation** — otherwise hand the pair to
      :func:`app.external_track_match.fuzzy_match_with_score`; the candidate is
      a match when a best id came back *and* the score clears
      :data:`_FUZZY_MATCH_BAR` (0.92).

    Returns a ``(TrackMatch, MatchResult)`` pair per input candidate, in the
    same order — non-matches are kept (with ``is_match=False``) so the caller
    can surface near-misses.
    """
    out: list[tuple[TrackMatch, MatchResult]] = []

    for cand in candidates:
        # 1. ISRC fast-path — certain identity, skips title/duration logic.
        if needle.isrc and cand.isrc and needle.isrc == cand.isrc:
            out.append(
                (
                    cand,
                    MatchResult(is_match=True, confidence=1.0, rule_fired="isrc_equality"),
                )
            )
            continue

        # 2. Duration hard-gate — D1 invariant, title match cannot override it.
        if abs(needle.duration_s - cand.duration_s) > _DURATION_GATE_S:
            out.append(
                (
                    cand,
                    MatchResult(
                        is_match=False,
                        confidence=0.0,
                        rule_fired="duration_gate_failed",
                    ),
                )
            )
            continue

        # 3. Fuzzy delegation to the shared matcher. ``fuzzy_match_with_score``
        #    iterates a ``{id: {"Title", "Artist"}}`` dict — bridge the single
        #    candidate into that shape (its id is the XTM ``source_id`` == url).
        xtm = _to_xtm(cand)
        haystack = {xtm.source_id: {"Title": xtm.title, "Artist": xtm.artist}}
        best_id, score = fuzzy_match_with_score(
            needle.title,
            needle.artist,
            haystack,
            threshold=_FUZZY_INTERNAL_THRESHOLD,
        )
        is_match = best_id is not None and score >= _FUZZY_MATCH_BAR
        out.append(
            (
                cand,
                MatchResult(
                    is_match=is_match,
                    confidence=score,
                    rule_fired=f"xtm_fuzzy_{score:.2f}",
                ),
            )
        )

    return out


__all__ = ["match"]
