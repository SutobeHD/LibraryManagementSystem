"""metadata_fixer — detect + (later) fix malformed artist/title metadata.

M0 ships `detector` only: read-only detection of malformed `artist`/`title`
pairs across the documented malformation catalogue. No writes, no filesystem
touches beyond what the caller already read. The apply/revert path (M1) and
MusicBrainz enrichment (M2) land in later modules (`applier`, `musicbrainz_client`).

See docs/research/implement/accepted_metadata-name-fixer.md for the full plan.
"""

from __future__ import annotations

from app.metadata_fixer.detector import Match, Rule, scan

__all__ = ["Match", "Rule", "scan"]
