"""Curated DJ-genre starter list (D5).

Seeded into the ``canonical_genres`` table on first run with ``seeded=1``.
Short, CDJ-display-safe, Title-Case strings — no symbols except ``&`` and the
trailing parenthesis disambiguator (``Trap (Hip-Hop)``).

Maintained here as a plain Python tuple so it diffs cleanly in PRs. The owner
can edit / delete entries via the Settings UI after first run; this tuple is
only the onboarding default, never re-applied destructively.

Source: ``docs/research/implement/accepted_downloader-unified-multi-source.md``
§ "D5 — Genre starter list". The doc's bracketed ``[ ... cluster ]`` lines are
section headers, not list members, and are intentionally omitted here.
"""

from __future__ import annotations

#: The curated genre starter pool, grouped by cluster (comments are headers
#: only — every string below is a real canonical genre).
GENRE_STARTER: tuple[str, ...] = (
    # House cluster
    "House",
    "Tech House",
    "Deep House",
    "Progressive House",
    "Future House",
    "Bass House",
    "Tropical House",
    "Afro House",
    "Melodic House",
    "Soulful House",
    # Techno cluster
    "Techno",
    "Melodic Techno",
    "Hard Techno",
    "Minimal Techno",
    "Industrial Techno",
    "Dub Techno",
    "Acid Techno",
    # Trance cluster
    "Trance",
    "Progressive Trance",
    "Psytrance",
    "Uplifting Trance",
    "Tech Trance",
    "Vocal Trance",
    # Drum & Bass / Breaks
    "Drum & Bass",
    "Liquid DnB",
    "Neurofunk",
    "Jump Up",
    "Jungle",
    "Breakbeat",
    "UK Garage",
    "Future Garage",
    # Hard cluster
    "Hardstyle",
    "Hardcore",
    "Frenchcore",
    "Uptempo",
    "Rawstyle",
    # Bass cluster
    "Dubstep",
    "Riddim",
    "Future Bass",
    "Trap",
    "Glitch Hop",
    "Moombahton",
    # Disco / Funk
    "Disco",
    "Nu Disco",
    "Funk",
    "Boogie",
    # Hip-Hop / Soul
    "Hip-Hop",
    "Trap (Hip-Hop)",
    "R&B",
    "Neo-Soul",
    # Electronica / Ambient
    "Electronica",
    "IDM",
    "Ambient",
    "Downtempo",
    "Chillout",
    "Lo-Fi",
    # Misc DJ-relevant
    "Pop",
    "Rock",
    "Indie",
    "Mashup",
    "Edit",
    "Bootleg",
    "Remix",
)

__all__ = ["GENRE_STARTER"]
