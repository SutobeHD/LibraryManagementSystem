"""Tests for ``app/downloader/aiff.py`` — bit-depth detection + AIFF conversion.

Covers :func:`detect_bit_depth` (16- vs 24-bit signal extraction from the
ffprobe JSON) and :func:`convert_to_aiff` (lossless → bit-depth-matched AIFF,
lossy → no conversion, AAC ``.m4a`` → kept-as-is, never fake-lossless).

ffprobe / ffmpeg are stubbed via ``monkeypatch`` on ``subprocess.run`` so the
suite never shells out — the tests assert on the codec flag the module
*chooses*, not on real transcoding.

See ``docs/research/implement/accepted_downloader-unified-multi-source.md``
§ "P4.13" and "(D4) AIFF post-download pipeline".
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from app.downloader import aiff

# ──────────────────────────────────────────────────────────────────────────────
# detect_bit_depth — ffprobe JSON interpretation
# ──────────────────────────────────────────────────────────────────────────────


def _ffprobe_json(**stream_fields: object) -> str:
    """Build a one-audio-stream ffprobe ``-of json`` payload."""
    return json.dumps({"streams": [stream_fields]})


def _patch_probe(monkeypatch: pytest.MonkeyPatch, stdout: str) -> None:
    """Make ``subprocess.run`` (as called by the ffprobe path) return ``stdout``."""

    def fake_run(cmd, *args, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(aiff.subprocess, "run", fake_run)


def test_detect_bit_depth_24_via_bits_per_raw_sample(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_probe(monkeypatch, _ffprobe_json(bits_per_raw_sample="24", sample_fmt="s32"))
    assert aiff.detect_bit_depth(Path("hi-res.flac")) == 24


def test_detect_bit_depth_24_via_sample_fmt_only(monkeypatch: pytest.MonkeyPatch) -> None:
    # No bits_per_raw_sample, but a 32-bit sample format → treated as 24-bit.
    _patch_probe(monkeypatch, _ffprobe_json(sample_fmt="s32p"))
    assert aiff.detect_bit_depth(Path("ambiguous.flac")) == 24


def test_detect_bit_depth_16_for_cd_rate(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_probe(monkeypatch, _ffprobe_json(bits_per_raw_sample="16", sample_fmt="s16"))
    assert aiff.detect_bit_depth(Path("cd.flac")) == 16


def test_detect_bit_depth_falls_back_to_16_on_probe_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(cmd, *args, **kwargs):
        raise OSError("ffprobe missing")

    monkeypatch.setattr(aiff.subprocess, "run", boom)
    assert aiff.detect_bit_depth(Path("broken.flac")) == 16


def test_detect_bit_depth_16_on_garbage_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_probe(monkeypatch, "not json at all")
    assert aiff.detect_bit_depth(Path("x.flac")) == 16


# ──────────────────────────────────────────────────────────────────────────────
# convert_to_aiff — format routing + codec selection
# ──────────────────────────────────────────────────────────────────────────────


class _FakeFFmpeg:
    """Records the ffmpeg command and fakes a successful conversion on disk."""

    def __init__(self, probe_stdout: str) -> None:
        self.probe_stdout = probe_stdout
        self.convert_cmd: list[str] | None = None

    def __call__(self, cmd, *args, **kwargs):
        # ffprobe calls carry "-show_entries"; ffmpeg conversion calls carry "-c:a".
        if "-show_entries" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=self.probe_stdout, stderr="")
        self.convert_cmd = list(cmd)
        # The output path is the final cmd token after "-y".
        dst = Path(cmd[-1])
        dst.write_bytes(b"\x00" * 4096)  # > 1024-byte sanity floor
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


def test_convert_aiff_passthrough_returns_source(tmp_path: Path) -> None:
    src = tmp_path / "already.aiff"
    src.write_bytes(b"\x00" * 2048)
    assert aiff.convert_to_aiff(src) == src


def test_convert_lossy_mp3_returns_none(tmp_path: Path) -> None:
    src = tmp_path / "track.mp3"
    src.write_bytes(b"\x00" * 2048)
    # No conversion for genuinely-lossy containers — caller keeps the original.
    assert aiff.convert_to_aiff(src) is None


def test_convert_16bit_flac_uses_pcm_s16le(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "cd.flac"
    src.write_bytes(b"\x00" * 2048)
    fake = _FakeFFmpeg(_ffprobe_json(bits_per_raw_sample="16", sample_fmt="s16"))
    monkeypatch.setattr(aiff.subprocess, "run", fake)

    out = aiff.convert_to_aiff(src)
    assert out is not None and out.suffix == ".aiff"
    assert fake.convert_cmd is not None
    assert "pcm_s16le" in fake.convert_cmd
    assert "-map_metadata" in fake.convert_cmd
    assert not src.exists()  # source removed after a successful conversion


def test_convert_24bit_flac_uses_pcm_s24le(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "hi-res.flac"
    src.write_bytes(b"\x00" * 2048)
    fake = _FakeFFmpeg(_ffprobe_json(bits_per_raw_sample="24", sample_fmt="s32"))
    monkeypatch.setattr(aiff.subprocess, "run", fake)

    out = aiff.convert_to_aiff(src)
    assert out is not None and out.suffix == ".aiff"
    assert fake.convert_cmd is not None
    # The hi-res regression the refactor exists to fix: 24-bit must NOT downgrade.
    assert "pcm_s24le" in fake.convert_cmd
    assert "pcm_s16le" not in fake.convert_cmd


def test_convert_wav_swaps_container(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "master.wav"
    src.write_bytes(b"\x00" * 2048)
    fake = _FakeFFmpeg(_ffprobe_json(bits_per_raw_sample="24"))
    monkeypatch.setattr(aiff.subprocess, "run", fake)
    out = aiff.convert_to_aiff(src)
    assert out is not None and out.suffix == ".aiff"


def test_convert_aac_m4a_kept_not_recontainered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "soundcloud.m4a"
    src.write_bytes(b"\x00" * 2048)
    # codec_name=aac → lossy → must stay .m4a (no fake-lossless re-container).
    fake = _FakeFFmpeg(_ffprobe_json(codec_name="aac", sample_fmt="fltp"))
    monkeypatch.setattr(aiff.subprocess, "run", fake)

    out = aiff.convert_to_aiff(src)
    assert out == src
    assert fake.convert_cmd is None  # ffmpeg conversion never invoked
    assert src.exists()


def test_convert_alac_m4a_is_converted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "lossless.m4a"
    src.write_bytes(b"\x00" * 2048)
    fake = _FakeFFmpeg(_ffprobe_json(codec_name="alac", bits_per_raw_sample="24"))
    monkeypatch.setattr(aiff.subprocess, "run", fake)

    out = aiff.convert_to_aiff(src)
    assert out is not None and out.suffix == ".aiff"
    assert fake.convert_cmd is not None and "pcm_s24le" in fake.convert_cmd


def test_convert_returns_none_on_ffmpeg_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "cd.flac"
    src.write_bytes(b"\x00" * 2048)

    def fake_run(cmd, *args, **kwargs):
        if "-show_entries" in cmd:
            return subprocess.CompletedProcess(
                cmd, 0, stdout=_ffprobe_json(bits_per_raw_sample="16"), stderr=""
            )
        # ffmpeg conversion fails (non-zero exit, no output file).
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")

    monkeypatch.setattr(aiff.subprocess, "run", fake_run)
    assert aiff.convert_to_aiff(src) is None
    assert src.exists()  # source preserved when conversion fails


def test_convert_returns_none_on_timeout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "cd.flac"
    src.write_bytes(b"\x00" * 2048)

    def fake_run(cmd, *args, **kwargs):
        if "-show_entries" in cmd:
            return subprocess.CompletedProcess(
                cmd, 0, stdout=_ffprobe_json(bits_per_raw_sample="16"), stderr=""
            )
        raise subprocess.TimeoutExpired(cmd, 300)

    monkeypatch.setattr(aiff.subprocess, "run", fake_run)
    assert aiff.convert_to_aiff(src) is None
    assert src.exists()
