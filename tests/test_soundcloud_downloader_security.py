"""Security regression tests for app/soundcloud_downloader.

Pins the URL allowlists used by the downloader's SSRF + token-leak guards.
Future changes to `_ALLOWED_CDN_HOST_SUFFIXES` / `_SC_FIRST_PARTY_HOST_SUFFIXES`
must keep these assertions green — they encode the security model.
"""

from __future__ import annotations

import pytest

from app.soundcloud_downloader import (
    _MAX_DOWNLOAD_BYTES,
    _is_allowed_cdn_url,
    _is_sc_first_party_url,
    _normalize_track_id,
)


class TestCdnAllowlist:
    """`_is_allowed_cdn_url` blocks the full SSRF surface."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://cf-media.sndcdn.com/foo.mp3",
            "https://cf-hls-media.sndcdn.com/playlist.m3u8",
            "https://sndcdn.com/asset",
            "https://api.soundcloud.com/tracks/1/download",
            "https://api-v2.soundcloud.com/tracks/1",
            "https://secure.soundcloud.com/oauth/token",
            "https://s3-fra.amazonaws.com/sc-stream/x.mp3",
            "https://d1234.cloudfront.net/x.mp3",
            "https://sc-akamai.akamaihd.net/x.mp3",
            "https://x.akamaized.net/x.mp3",
        ],
    )
    def test_known_sc_hosts_allowed(self, url: str) -> None:
        assert _is_allowed_cdn_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            # Confused-deputy suffix attack — `.com.attacker.com` ends in
            # `.attacker.com`, not `.sndcdn.com`.
            "https://evil.sndcdn.com.attacker.com/x",
            "https://attacker.example.com/x",
            # Plain non-SC host
            "https://example.com/foo.mp3",
            # IP literals (no DNS name → can't be a known CDN)
            "http://169.254.169.254/latest/meta-data/iam/info",  # AWS metadata
            "https://127.0.0.1/x",
            "https://10.0.0.5/x",
            "https://[::1]/x",
            # Non-http(s) schemes
            "file:///etc/passwd",
            "ftp://files.example.com/x",
            "gopher://x/",
            "javascript:alert(1)",
            # Garbage
            "",
            "not-a-url",
            "http://",
        ],
    )
    def test_hostile_urls_rejected(self, url: str) -> None:
        assert _is_allowed_cdn_url(url) is False


class TestFirstPartyDetection:
    """`_is_sc_first_party_url` decides where the OAuth token may be sent."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://api.soundcloud.com/me",
            "https://api-v2.soundcloud.com/tracks/1",
            "https://secure.soundcloud.com/oauth/token",
            "https://cf-hls-media.sndcdn.com/playlist.m3u8",
            "https://soundcloud.com/resolve",
            "https://sndcdn.com/anything",
        ],
    )
    def test_first_party_hosts_accepted(self, url: str) -> None:
        assert _is_sc_first_party_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            # Signed CDN URLs must NOT receive the OAuth token.
            "https://s3-fra.amazonaws.com/sc-stream/x.mp3?signature=…",
            "https://d1234.cloudfront.net/x.mp3",
            "https://x.akamaihd.net/x.mp3",
            # Suffix-attack
            "https://sndcdn.com.attacker.com/x",
            # Plain non-SC
            "https://example.com/x",
            # http (must be https for credential transport)
            "http://api.soundcloud.com/me",
        ],
    )
    def test_third_party_hosts_blocked(self, url: str) -> None:
        assert _is_sc_first_party_url(url) is False


class TestNormalizeTrackIdHardening:
    """Length-cap on `_normalize_track_id` blocks CPU-DoS via `ast.literal_eval`."""

    def test_oversized_input_rejected(self) -> None:
        # 3000 chars of plausibly-tuple-ish nonsense — would otherwise hit
        # ast.literal_eval with a pathological literal.
        evil = "(" + "1" * 3000 + ",)"
        assert _normalize_track_id(evil) is None

    def test_normal_id_passes(self) -> None:
        assert _normalize_track_id("1778088975330") == "1778088975330"

    def test_int_passes(self) -> None:
        assert _normalize_track_id(1778088975330) == "1778088975330"

    def test_legacy_tuple_blob_still_recoverable(self) -> None:
        # The historical bug we wrote this function to clean up.
        legacy = "('1778088975330', {'bpm': 154.0})"
        assert _normalize_track_id(legacy) == "1778088975330"

    def test_none_passes_through(self) -> None:
        assert _normalize_track_id(None) is None


class TestSizeLimits:
    """The byte-budget constant must stay sane — too small breaks WAV/FLAC,
    too large defeats the disk-exhaustion guard."""

    def test_budget_is_at_least_500_mib(self) -> None:
        # Real SC originals can be 300-400 MB (long DJ sets uploaded as WAV).
        assert _MAX_DOWNLOAD_BYTES >= 500 * 1024 * 1024

    def test_budget_is_at_most_4_gib(self) -> None:
        # Above 4 GiB we'd risk filling small SSDs with a single bad download.
        assert _MAX_DOWNLOAD_BYTES <= 4 * 1024 * 1024 * 1024
