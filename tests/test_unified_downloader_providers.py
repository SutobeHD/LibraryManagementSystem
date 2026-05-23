"""Tests for ``app/downloader/providers/`` — the Phase-1 provider layer.

Two provider implementations are covered:

* :class:`app.downloader.providers.spotiflac.SpotiFlacProvider` — focus is
  the Odesli-based ``resolve_url`` (HTTP mocked at ``_odesli_lookup_sync``)
  and the ``spotiflac-cli`` subprocess invocation in ``fetch`` (mocked at
  ``_run_cli_download``). The dead pip-0.x ``SpotiFLAC`` package +
  ``ProcessPoolExecutor`` crash machinery are gone — the CLI binary itself
  owns crash isolation now.
* :class:`app.downloader.providers.soundcloud.SoundCloudProvider` — the SC
  API is mocked; no provider test ever touches the network or downloads bytes.

See ``docs/research/implement/accepted_downloader-unified-multi-source.md``
§ "P1.5 / P1.7".
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from app.downloader import SourceProvider
from app.downloader.models import QualityTier, TrackMatch
from app.downloader.providers import soundcloud as sc_mod
from app.downloader.providers import spotiflac as sf_mod
from app.downloader.providers.soundcloud import SoundCloudProvider
from app.downloader.providers.spotiflac import SpotiFlacProvider

# ──────────────────────────────────────────────────────────────────────────────
# SpotiFlacProvider — ABC conformance + construction
# ──────────────────────────────────────────────────────────────────────────────


def test_spotiflac_provider_is_a_source_provider() -> None:
    """SpotiFlacProvider satisfies the SourceProvider ABC (all abstracts impl)."""
    provider = SpotiFlacProvider("qobuz")
    assert isinstance(provider, SourceProvider)
    assert provider.platform == "qobuz"


def test_spotiflac_provider_rejects_unserved_platform() -> None:
    """Constructing for a non-SpotiFLAC platform fails fast."""
    with pytest.raises(ValueError, match="cannot serve platform"):
        SpotiFlacProvider("soundcloud")


def test_spotiflac_provider_defaults_to_tidal() -> None:
    """The default platform is tidal."""
    assert SpotiFlacProvider().platform == "tidal"


def test_spotiflac_provider_drops_apple_and_deezer() -> None:
    """v7 has no Apple Music or Deezer download providers — construction fails."""
    with pytest.raises(ValueError, match="cannot serve platform"):
        SpotiFlacProvider("apple_music")
    with pytest.raises(ValueError, match="cannot serve platform"):
        SpotiFlacProvider("deezer")


# ──────────────────────────────────────────────────────────────────────────────
# SpotiFlacProvider — _extract_spotify_id (offline, no network)
# ──────────────────────────────────────────────────────────────────────────────


def test_extract_spotify_id_recognises_track_url() -> None:
    """The 22-char ID falls out of an ``open.spotify.com/track/<id>`` URL."""
    assert (
        sf_mod._extract_spotify_id("https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT")
        == "4cOdK2wGLETKBW3PvgPWqT"
    )


def test_extract_spotify_id_returns_none_for_non_track() -> None:
    """A non-Spotify-track URL parses to ``None`` without raising."""
    assert sf_mod._extract_spotify_id("https://soundcloud.com/x/y") is None
    assert sf_mod._extract_spotify_id("not a url at all") is None


# ──────────────────────────────────────────────────────────────────────────────
# SpotiFlacProvider — resolve_url (Odesli HTTP mocked) + search
# ──────────────────────────────────────────────────────────────────────────────


_FAKE_ODESLI: dict[str, Any] = {
    "entityUniqueId": "SPOTIFY_SONG::abc123",
    "userCountry": "US",
    "entitiesByUniqueId": {
        "SPOTIFY_SONG::abc123": {
            "id": "abc123",
            "type": "song",
            "title": "Strobe",
            "artistName": "deadmau5",
            "thumbnailUrl": "https://img/cover.jpg",
            "apiProvider": "spotify",
            "platforms": ["spotify"],
        }
    },
    "linksByPlatform": {
        "spotify": {"url": "https://open.spotify.com/track/abc123"},
        "tidal": {"url": "https://tidal.com/track/111"},
        "qobuz": {"url": "https://qobuz.com/track/222"},
        "amazonMusic": {"url": "https://music.amazon.com/tracks/A123"},
        # Non-v7-served keys must be filtered out by resolve_url.
        "youtube": {"url": "https://youtube.com/watch?v=zzz"},
        "soundcloud": {"url": "https://soundcloud.com/x/y"},
    },
}


def test_resolve_url_builds_per_service_claims(monkeypatch: pytest.MonkeyPatch) -> None:
    """resolve_url turns the Odesli response into one claim per v7-served service.

    Non-v7 cross-URLs (YouTube / SoundCloud) are dropped; the three served
    platforms (Tidal / Qobuz / Amazon) become Hi-Res claims carrying the
    Spotify-origin fragment.
    """
    monkeypatch.setattr(sf_mod, "_odesli_lookup_sync", lambda _id: dict(_FAKE_ODESLI))

    matches = asyncio.run(
        SpotiFlacProvider("tidal").resolve_url("https://open.spotify.com/track/abc123")
    )

    platforms = {m.platform for m in matches}
    assert platforms == {"tidal", "qobuz", "amazon"}  # youtube + soundcloud dropped
    for m in matches:
        assert m.title == "Strobe"
        assert m.artist == "deadmau5"
        assert m.cover_url == "https://img/cover.jpg"
        assert m.quality_tier == QualityTier.HIRES_LOSSLESS
        # The Spotify origin must ride along for fetch() to recover.
        assert "#spotify=https://open.spotify.com/track/abc123" in m.url


def test_resolve_url_returns_empty_on_non_spotify_url() -> None:
    """A non-Spotify URL yields an empty list (no Odesli call needed)."""
    matches = asyncio.run(SpotiFlacProvider("tidal").resolve_url("https://soundcloud.com/x/y"))
    assert matches == []


def test_resolve_url_returns_empty_when_odesli_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An Odesli failure (``None``) yields an empty list — dead source, not abort."""
    monkeypatch.setattr(sf_mod, "_odesli_lookup_sync", lambda _id: None)
    matches = asyncio.run(
        SpotiFlacProvider("tidal").resolve_url("https://open.spotify.com/track/abc123")
    )
    assert matches == []


def test_spotiflac_search_is_a_noop() -> None:
    """SpotiFLAC has no free-form search — search() always returns []."""
    assert asyncio.run(SpotiFlacProvider("tidal").search("anything")) == []


def test_spotiflac_fetch_rejects_wrong_platform() -> None:
    """fetch() refuses a claim whose platform it does not serve."""
    sc_claim = TrackMatch(
        platform="soundcloud",
        url="https://soundcloud.com/x/y",
        title="t",
        artist="a",
        duration_s=1.0,
        claimed_format="mp3",
        claimed_bitrate_kbps=128,
        quality_tier=QualityTier.STANDARD_LOSSY,
    )
    with pytest.raises(ValueError, match="cannot serve platform"):
        asyncio.run(SpotiFlacProvider("tidal").fetch(sc_claim, Path(".")))


def test_spotiflac_fetch_rejects_claim_without_spotify_origin(tmp_path: Path) -> None:
    """fetch() needs the #spotify= fragment to drive the pivoted download."""
    claim = TrackMatch(
        platform="tidal",
        url="https://tidal.com/track/111",  # no #spotify= fragment
        title="t",
        artist="a",
        duration_s=1.0,
        claimed_format="flac",
        claimed_bit_depth=24,
        claimed_sample_rate_hz=96000,
        quality_tier=QualityTier.HIRES_LOSSLESS,
    )
    with pytest.raises(ValueError, match="no Spotify origin"):
        asyncio.run(SpotiFlacProvider("tidal").fetch(claim, tmp_path))


def test_spotiflac_fetch_drives_cli_with_spotify_origin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """fetch() extracts the Spotify origin and forwards it to the CLI."""
    captured: dict[str, Any] = {}

    async def _fake_run_cli_download(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        out = tmp_path / "Strobe.flac"
        out.write_bytes(b"flac-bytes")
        return {"success": True, "service": kwargs["service"], "file": str(out)}

    monkeypatch.setattr(sf_mod, "_run_cli_download", _fake_run_cli_download)
    # Bypass the locate-binary check — no built binary required for this unit test.
    monkeypatch.setattr(sf_mod, "_locate_cli", lambda: tmp_path / "fake-spotiflac-cli")

    claim = TrackMatch(
        platform="tidal",
        url="https://tidal.com/track/111#spotify=https://open.spotify.com/track/abc",
        title="Strobe",
        artist="deadmau5",
        album="For Lack of a Better Name",
        duration_s=636.0,
        isrc="USUS11000301",
        claimed_format="flac",
        claimed_bit_depth=24,
        claimed_sample_rate_hz=96000,
        quality_tier=QualityTier.HIRES_LOSSLESS,
    )
    result = asyncio.run(SpotiFlacProvider("tidal").fetch(claim, tmp_path))

    assert result == tmp_path / "Strobe.flac"
    assert captured["service"] == "tidal"
    assert captured["spotify_id"] == "abc"
    assert captured["title"] == "Strobe"
    assert captured["artist"] == "deadmau5"
    assert captured["album"] == "For Lack of a Better Name"


def test_spotiflac_fetch_raises_on_cli_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """fetch() raises RuntimeError when the CLI reports failure."""

    async def _fake_run_cli_download(**kwargs: Any) -> dict[str, Any]:
        return {"success": False, "service": kwargs["service"], "error": "mirror 503"}

    monkeypatch.setattr(sf_mod, "_run_cli_download", _fake_run_cli_download)
    monkeypatch.setattr(sf_mod, "_locate_cli", lambda: tmp_path / "fake-spotiflac-cli")

    claim = TrackMatch(
        platform="qobuz",
        url="https://qobuz.com/track/x#spotify=https://open.spotify.com/track/xyz",
        title="t",
        artist="a",
        duration_s=1.0,
        claimed_format="flac",
        claimed_bit_depth=24,
        claimed_sample_rate_hz=96000,
        quality_tier=QualityTier.HIRES_LOSSLESS,
    )
    with pytest.raises(RuntimeError, match="mirror 503"):
        asyncio.run(SpotiFlacProvider("qobuz").fetch(claim, tmp_path))


def test_extract_spotify_origin() -> None:
    """The #spotify= fragment extractor handles present + absent cases."""
    assert sf_mod._extract_spotify_origin("https://t/1#spotify=https://s/abc") == "https://s/abc"
    assert sf_mod._extract_spotify_origin("https://t/1") is None
    assert sf_mod._extract_spotify_origin("https://t/1#spotify=") is None


# ──────────────────────────────────────────────────────────────────────────────
# SoundCloudProvider — ABC conformance
# ──────────────────────────────────────────────────────────────────────────────


def test_soundcloud_provider_is_a_source_provider() -> None:
    """SoundCloudProvider satisfies the SourceProvider ABC."""
    provider = SoundCloudProvider()
    assert isinstance(provider, SourceProvider)
    assert provider.platform == "soundcloud"


# ──────────────────────────────────────────────────────────────────────────────
# SoundCloudProvider — resolve_url (SC API mocked)
# ──────────────────────────────────────────────────────────────────────────────


class _FakeSCApi:
    """Stand-in for SoundCloudPlaylistAPI — records calls, returns canned data."""

    resolve_result: dict[str, Any] | None = None
    resolve_raises: Exception | None = None
    last_url: str | None = None

    @classmethod
    def resolve_track_from_url(
        cls, url: str, auth_token: str | None = None
    ) -> dict[str, Any] | None:
        cls.last_url = url
        if cls.resolve_raises is not None:
            raise cls.resolve_raises
        return cls.resolve_result


def _install_fake_sc_api(monkeypatch: pytest.MonkeyPatch) -> type[_FakeSCApi]:
    """Patch SoundCloudPlaylistAPI in the soundcloud_api module with the fake."""
    import app.soundcloud_api as real_api

    _FakeSCApi.resolve_result = None
    _FakeSCApi.resolve_raises = None
    _FakeSCApi.last_url = None
    monkeypatch.setattr(real_api, "SoundCloudPlaylistAPI", _FakeSCApi)
    return _FakeSCApi


def test_sc_resolve_url_builds_claim_for_downloadable_track(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A downloadable SC track is claimed as CD-lossless (optimistic)."""
    fake = _install_fake_sc_api(monkeypatch)
    fake.resolve_result = {
        "id": 999,
        "title": "Bootleg Edit",
        "artist": "DJ Example",
        "duration": 215000,
        "permalink_url": "https://soundcloud.com/dj/bootleg-edit",
        "artwork_url": "https://img/art.jpg",
        "downloadable": True,
        "isrc": "GBXYZ1234567",
    }

    matches = asyncio.run(
        SoundCloudProvider().resolve_url("https://soundcloud.com/dj/bootleg-edit")
    )
    assert len(matches) == 1
    m = matches[0]
    assert m.platform == "soundcloud"
    assert m.title == "Bootleg Edit"
    assert m.duration_s == pytest.approx(215.0)
    assert m.isrc == "GBXYZ1234567"
    assert m.quality_tier == QualityTier.CD_LOSSLESS  # downloadable → lossless claim


def test_sc_resolve_url_claims_non_downloadable_as_lossy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-downloadable SC track is claimed as the lossy stream ceiling."""
    fake = _install_fake_sc_api(monkeypatch)
    fake.resolve_result = {
        "id": 1,
        "title": "Stream Only",
        "artist": "Artist",
        "duration": 180000,
        "permalink_url": "https://soundcloud.com/a/stream-only",
        "downloadable": False,
        "isrc": None,
    }

    matches = asyncio.run(SoundCloudProvider().resolve_url("https://soundcloud.com/a/stream-only"))
    assert len(matches) == 1
    assert matches[0].quality_tier == QualityTier.HIGH_LOSSY
    assert matches[0].claimed_format == "aac"
    assert matches[0].isrc is None


def test_sc_resolve_url_returns_empty_for_non_track(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A URL resolving to a non-track (None) yields an empty list."""
    fake = _install_fake_sc_api(monkeypatch)
    fake.resolve_result = None

    matches = asyncio.run(SoundCloudProvider().resolve_url("https://soundcloud.com/a/playlist"))
    assert matches == []


def test_sc_resolve_url_swallows_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """An AuthExpiredError degrades to an empty list (dead source, not abort)."""
    from app.soundcloud_api import AuthExpiredError

    fake = _install_fake_sc_api(monkeypatch)
    fake.resolve_raises = AuthExpiredError("token expired")

    matches = asyncio.run(SoundCloudProvider("tok").resolve_url("https://soundcloud.com/x"))
    assert matches == []


# ──────────────────────────────────────────────────────────────────────────────
# SoundCloudProvider — search (v2 endpoint mocked at _sc_get)
# ──────────────────────────────────────────────────────────────────────────────


class _FakeResp:
    """Minimal requests.Response stand-in — just .json()."""

    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def json(self) -> Any:
        return self._payload


def test_sc_search_returns_claims(monkeypatch: pytest.MonkeyPatch) -> None:
    """search() maps a v2 /search/tracks collection into TrackMatch claims."""
    import app.soundcloud_api as real_api

    collection = {
        "collection": [
            {
                "id": 10,
                "title": "Result One",
                "user": {"username": "Uploader A"},
                "duration": 200000,
                "permalink_url": "https://soundcloud.com/a/result-one",
                "downloadable": False,
                "publisher_metadata": {"isrc": "AAISRC0000001"},
            },
            {
                "id": 11,
                "title": "Result Two",
                "user": {"username": "Uploader B"},
                "duration": 240000,
                "permalink_url": "https://soundcloud.com/b/result-two",
                "downloadable": True,
            },
            # Dead entry — no id, no title: must be filtered out.
            {"id": None, "title": "", "user": {}},
        ]
    }

    monkeypatch.setattr(real_api, "get_sc_client_id", lambda: "fake-client-id")
    monkeypatch.setattr(
        real_api,
        "_sc_get",
        lambda url, headers=None, params=None, timeout=None: _FakeResp(collection),
    )

    matches = asyncio.run(SoundCloudProvider().search("result", limit=5))
    assert len(matches) == 2
    assert matches[0].title == "Result One"
    assert matches[0].artist == "Uploader A"
    assert matches[0].isrc == "AAISRC0000001"
    assert matches[0].quality_tier == QualityTier.HIGH_LOSSY  # not downloadable
    assert matches[1].title == "Result Two"
    assert matches[1].quality_tier == QualityTier.CD_LOSSLESS  # downloadable


def test_sc_search_returns_empty_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """A transport failure inside search() degrades to an empty list."""
    import app.soundcloud_api as real_api

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("network down")

    monkeypatch.setattr(real_api, "get_sc_client_id", lambda: "fake-client-id")
    monkeypatch.setattr(real_api, "_sc_get", _boom)

    assert asyncio.run(SoundCloudProvider().search("query")) == []


def test_sc_search_respects_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """search() truncates the result set to ``limit`` claims."""
    import app.soundcloud_api as real_api

    collection = {
        "collection": [
            {
                "id": i,
                "title": f"Track {i}",
                "user": {"username": "U"},
                "duration": 1000,
                "permalink_url": f"https://soundcloud.com/u/t{i}",
            }
            for i in range(1, 11)  # realistic 1-based SC track ids
        ]
    }
    monkeypatch.setattr(real_api, "get_sc_client_id", lambda: "cid")
    monkeypatch.setattr(
        real_api,
        "_sc_get",
        lambda url, headers=None, params=None, timeout=None: _FakeResp(collection),
    )

    matches = asyncio.run(SoundCloudProvider().search("t", limit=3))
    assert len(matches) == 3


# ──────────────────────────────────────────────────────────────────────────────
# SoundCloudProvider — fetch (existing SC downloader functions mocked)
# ──────────────────────────────────────────────────────────────────────────────


def test_sc_fetch_rejects_wrong_platform() -> None:
    """fetch() refuses a non-SoundCloud claim."""
    tidal_claim = TrackMatch(
        platform="tidal",
        url="https://tidal.com/track/1",
        title="t",
        artist="a",
        duration_s=1.0,
        claimed_format="flac",
        claimed_bit_depth=24,
        claimed_sample_rate_hz=96000,
        quality_tier=QualityTier.HIRES_LOSSLESS,
    )
    with pytest.raises(ValueError, match="cannot serve platform"):
        asyncio.run(SoundCloudProvider().fetch(tidal_claim, Path(".")))


def test_sc_fetch_official_download_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """fetch() uses the official /download URL for a downloadable track and
    moves the temp file into dest_dir under an 'Artist - Title.ext' name."""
    import app.soundcloud_api as real_api
    import app.soundcloud_downloader as dl_mod

    # resolve → a downloadable track
    fake_api = _install_fake_sc_api(monkeypatch)
    fake_api.resolve_result = {
        "id": 555,
        "title": "My Track",
        "artist": "My Artist",
        "downloadable": True,
    }

    # The official-download resolver returns a CDN URL.
    monkeypatch.setattr(
        dl_mod, "_resolve_official_download_url", lambda tid, tok: "https://cdn/file"
    )

    # The byte-puller writes a fake source temp file and returns its path.
    src_temp = tmp_path / "src.flac"
    src_temp.write_bytes(b"original-flac-bytes")

    def _fake_stream(url: str, tok: str | None) -> Path:
        return src_temp

    monkeypatch.setattr(dl_mod, "_stream_file_to_temp", _fake_stream)
    # Transcoding fallback must NOT be reached on the downloadable path.
    monkeypatch.setattr(
        dl_mod,
        "_resolve_stream_via_transcodings",
        lambda tid, tok: pytest.fail("transcoding fallback should not run"),
    )

    claim = TrackMatch(
        platform="soundcloud",
        url="https://soundcloud.com/my/track",
        title="My Track",
        artist="My Artist",
        duration_s=200.0,
        claimed_format="flac",
        claimed_bit_depth=16,
        claimed_sample_rate_hz=44100,
        quality_tier=QualityTier.CD_LOSSLESS,
    )
    result = asyncio.run(SoundCloudProvider().fetch(claim, tmp_path))

    assert result == tmp_path / "My Artist - My Track.flac"
    assert result.read_bytes() == b"original-flac-bytes"
    assert not src_temp.exists()  # moved, not copied


def test_sc_fetch_transcoding_fallback_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A non-downloadable track falls through to the transcoding stream."""
    import app.soundcloud_api as real_api
    import app.soundcloud_downloader as dl_mod

    fake_api = _install_fake_sc_api(monkeypatch)
    fake_api.resolve_result = {
        "id": 7,
        "title": "Stream Track",
        "artist": "Stream Artist",
        "downloadable": False,
    }
    # Official path is never consulted for a non-downloadable track, but the
    # transcoding resolver must return a progressive source.
    monkeypatch.setattr(
        dl_mod,
        "_resolve_stream_via_transcodings",
        lambda tid, tok: {
            "url": "https://cdn/stream",
            "protocol": "progressive",
            "mime_type": "audio/mpeg",
        },
    )
    src_temp = tmp_path / "stream.mp3"
    src_temp.write_bytes(b"mp3-bytes")
    monkeypatch.setattr(dl_mod, "_stream_file_to_temp", lambda url, tok: src_temp)

    claim = TrackMatch(
        platform="soundcloud",
        url="https://soundcloud.com/s/stream-track",
        title="Stream Track",
        artist="Stream Artist",
        duration_s=180.0,
        claimed_format="aac",
        claimed_bitrate_kbps=256,
        quality_tier=QualityTier.HIGH_LOSSY,
    )
    result = asyncio.run(SoundCloudProvider().fetch(claim, tmp_path))
    assert result == tmp_path / "Stream Artist - Stream Track.mp3"


def test_sc_fetch_raises_when_no_stream(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """fetch() raises RuntimeError when no stream source can be resolved."""
    import app.soundcloud_api as real_api
    import app.soundcloud_downloader as dl_mod

    fake_api = _install_fake_sc_api(monkeypatch)
    fake_api.resolve_result = {
        "id": 3,
        "title": "Gone",
        "artist": "Nobody",
        "downloadable": False,
    }
    monkeypatch.setattr(dl_mod, "_resolve_stream_via_transcodings", lambda tid, tok: None)

    claim = TrackMatch(
        platform="soundcloud",
        url="https://soundcloud.com/n/gone",
        title="Gone",
        artist="Nobody",
        duration_s=1.0,
        claimed_format="aac",
        claimed_bitrate_kbps=256,
        quality_tier=QualityTier.HIGH_LOSSY,
    )
    with pytest.raises(RuntimeError, match="no available SoundCloud stream"):
        asyncio.run(SoundCloudProvider().fetch(claim, tmp_path))


def test_sc_fetch_raises_when_url_not_a_track(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """fetch() raises ValueError when the claim URL resolves to no track."""
    fake_api = _install_fake_sc_api(monkeypatch)
    fake_api.resolve_result = None

    claim = TrackMatch(
        platform="soundcloud",
        url="https://soundcloud.com/not/a-track",
        title="x",
        artist="y",
        duration_s=1.0,
        claimed_format="aac",
        claimed_bitrate_kbps=256,
        quality_tier=QualityTier.HIGH_LOSSY,
    )
    with pytest.raises(ValueError, match="did not resolve to a track"):
        asyncio.run(SoundCloudProvider().fetch(claim, tmp_path))


def test_quality_claim_helper() -> None:
    """_quality_claim returns lossless for downloadable, lossy otherwise."""
    fmt_dl, bd_dl, _sr_dl, br_dl, tier_dl = sc_mod._quality_claim(True)
    assert fmt_dl == "flac" and tier_dl == QualityTier.CD_LOSSLESS and br_dl is None
    fmt_no, bd_no, _sr_no, br_no, tier_no = sc_mod._quality_claim(False)
    assert fmt_no == "aac" and tier_no == QualityTier.HIGH_LOSSY and bd_no is None
    assert br_no == 256
