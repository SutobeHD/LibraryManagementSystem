"""A mock :class:`SourcePlugin` for the ``external_track_match`` test-suite.

This adapter implements the full ``SourcePlugin`` Protocol with zero network
I/O: ``search`` returns a deterministic list of pre-canned :class:`Candidate`
objects (or whatever the test stuffed into ``canned_results``). It exists so
the adapter-registry tests can register a real, contract-compliant adapter
side-by-side with :class:`~app.external_track_match.SoundCloudAdapter` without
hitting SoundCloud.
"""

from __future__ import annotations

from app.external_track_match import Candidate, VersionTag, parse_version_tag


class MockAdapter:
    """A deterministic, network-free ``SourcePlugin`` implementation."""

    name = "mock"

    def __init__(
        self,
        *,
        name: str = "mock",
        canned_results: list[Candidate] | None = None,
        quota: int | None = 999,
    ) -> None:
        # Instance-level name override so two mock adapters can coexist in the
        # registry under different keys.
        self.name = name
        self._canned = canned_results
        self._quota = quota
        #: Records every ``search`` call so tests can assert dispatch kwargs.
        self.calls: list[dict] = []

    async def search(
        self,
        title: str,
        artist: str,
        duration_s: float | None = None,
        *,
        max_results: int = 20,
    ) -> list[Candidate]:
        """Return the canned candidate list (or one synthesised from the query)."""
        self.calls.append(
            {
                "title": title,
                "artist": artist,
                "duration_s": duration_s,
                "max_results": max_results,
            }
        )
        if self._canned is not None:
            return list(self._canned[:max_results])
        # Synthesise a single deterministic candidate echoing the query.
        return [
            Candidate(
                source=self.name,
                source_id=f"mock-{title}-{artist}",
                title=title,
                artist=artist,
                duration_s=duration_s,
                version_tag=parse_version_tag(title),
                url=f"https://example.test/{title}",
                raw={"title": title, "artist": artist},
            )
        ]

    def parse_version(self, raw: dict) -> VersionTag | None:
        """Parse a version tag straight from ``raw['title']`` (no source override)."""
        title = raw.get("title", "") if isinstance(raw, dict) else ""
        return parse_version_tag(title) if title else None

    def quota_remaining(self) -> int | None:
        """Return the configured quota hint."""
        return self._quota
