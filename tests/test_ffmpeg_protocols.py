"""Protocol-aware ffmpeg resolution and its use in the SoundCloud downloader (B18).

The PATH ffmpeg on the user's machine is a decode-only build without network
protocols, so HLS downloads must pick a binary that can fetch https.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app import ffmpeg_resolver as resolver_mod
from app import soundcloud_downloader as dl
from app.ffmpeg_resolver import ResolvedFfmpeg

PROTOCOLS_LISTING = """Supported file protocols:
Input:
  async
  file
  https
  tcp
  tls
Output:
  file
  rtmp
"""


@pytest.fixture(autouse=True)
def _fresh_cache():
    resolver_mod.clear_probe_cache()
    yield
    resolver_mod.clear_probe_cache()


def test_probe_reads_only_input_protocols(monkeypatch):
    def fake_run(cmd, **_kw):
        assert cmd[1:] == ["-hide_banner", "-protocols"]
        return subprocess.CompletedProcess(cmd, 0, stdout=PROTOCOLS_LISTING, stderr="")

    monkeypatch.setattr(resolver_mod.subprocess, "run", fake_run)
    protocols = resolver_mod.probe_input_protocols("ffmpeg")
    assert protocols == frozenset({"async", "file", "https", "tcp", "tls"})
    assert "rtmp" not in protocols


def test_probe_failure_is_none_and_cached(monkeypatch):
    calls = []

    def fake_run(cmd, **_kw):
        calls.append(cmd)
        raise OSError("not found")

    monkeypatch.setattr(resolver_mod.subprocess, "run", fake_run)
    assert resolver_mod.probe_input_protocols("missing") is None
    assert resolver_mod.probe_input_protocols("missing") is None
    assert len(calls) == 1


def test_resolve_skips_a_decode_only_build(monkeypatch):
    monkeypatch.setattr(
        resolver_mod,
        "candidate_binaries",
        lambda: [("lexicon-ffmpeg", "default"), ("full-ffmpeg", "winget")],
    )
    table = {
        "lexicon-ffmpeg": frozenset({"file", "pipe"}),
        "full-ffmpeg": frozenset({"file", "https", "tcp", "tls"}),
    }
    monkeypatch.setattr(resolver_mod, "probe_input_protocols", table.get)

    got = resolver_mod.resolve_for_protocols(("https", "tls", "tcp"))
    assert got == ResolvedFfmpeg(available=True, binary="full-ffmpeg", source="winget")


def test_resolve_reports_when_nothing_qualifies(monkeypatch):
    monkeypatch.setattr(resolver_mod, "candidate_binaries", lambda: [("lexicon-ffmpeg", "default")])
    monkeypatch.setattr(resolver_mod, "probe_input_protocols", lambda _p: frozenset({"file"}))

    got = resolver_mod.resolve_for_protocols(("https",))
    assert got.available is False
    assert got.binary is None
    assert "https" in (got.reason or "")


HLS_URL = "https://cf-hls-media.sndcdn.com/playlist/abc.m3u8"


def test_hls_download_runs_the_resolved_binary(monkeypatch):
    monkeypatch.setattr(
        dl,
        "resolve_for_protocols",
        lambda req: ResolvedFfmpeg(available=True, binary="full-ffmpeg", source="winget"),
    )
    seen = []

    def fake_run(cmd, **_kw):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="stop here")

    monkeypatch.setattr(dl.subprocess, "run", fake_run)
    assert dl._download_hls_to_temp(HLS_URL, None, "audio/mp4") is None
    assert seen and seen[0][0] == "full-ffmpeg"
    assert "-protocol_whitelist" in seen[0]


def test_hls_download_stops_without_a_network_ffmpeg(monkeypatch):
    monkeypatch.setattr(
        dl,
        "resolve_for_protocols",
        lambda req: ResolvedFfmpeg(available=False, reason="no ffmpeg with input protocols"),
    )

    def must_not_run(*_a, **_kw):
        raise AssertionError("ffmpeg must not run without network support")

    monkeypatch.setattr(dl.subprocess, "run", must_not_run)
    assert dl._download_hls_to_temp(HLS_URL, None, "audio/mp4") is None


def test_aiff_conversion_uses_the_resolved_binary(monkeypatch, tmp_path: Path):
    src = tmp_path / "track.m4a"
    src.write_bytes(b"\0" * 2048)
    monkeypatch.setattr(
        dl,
        "resolve_for_encoder",
        lambda enc: ResolvedFfmpeg(available=True, binary="enc-ffmpeg", source="settings"),
    )
    seen = []

    def fake_run(cmd, **_kw):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="stop here")

    monkeypatch.setattr(dl.subprocess, "run", fake_run)
    assert dl._convert_to_aiff(src) is None
    assert seen[0][0] == "enc-ffmpeg"
    assert src.exists()


def test_aiff_conversion_keeps_the_source_without_ffmpeg(monkeypatch, tmp_path: Path):
    src = tmp_path / "track.m4a"
    src.write_bytes(b"\0" * 2048)
    monkeypatch.setattr(
        dl, "resolve_for_encoder", lambda enc: ResolvedFfmpeg(available=False, reason="none")
    )
    assert dl._convert_to_aiff(src) is None
    assert src.exists()
