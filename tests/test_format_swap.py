"""Unit tests for the dependency-free format-converter foundation:
`app/format_swap_codec.py` (codec/disk/probe decision logic) and
`app/format_swap_tracker.py` (batch progress tracker).

These run without FFmpeg, rbox, pydantic or fastapi — the rbox/FFmpeg
orchestration (`app/format_converter.py`) and the FastAPI routes are tested
separately on a runner that has those deps.
"""

from __future__ import annotations

import app.format_swap_codec as codec
import app.format_swap_tracker as tracker

# ---------------------------------------------------------------------------
# Codec / target specs
# ---------------------------------------------------------------------------


def test_target_extensions():
    assert codec.target_extension("AIFF") == ".aiff"
    assert codec.target_extension("flac") == ".flac"  # case-insensitive
    assert codec.target_extension("WAV") == ".wav"
    assert codec.target_extension("MP3") == ".mp3"


def test_unknown_target_raises():
    for bad in ("OGG", "", "alac", "aac"):
        try:
            codec.target_extension(bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} should be rejected")


def test_rekordbox_file_type_codes_pinned():
    """PROVISIONAL byte-level RB FileType codes — pinned so any change is
    deliberate + reviewed against a real master.db before graduation."""
    assert codec.rekordbox_file_type("AIFF") == 12
    assert codec.rekordbox_file_type("WAV") == 11
    assert codec.rekordbox_file_type("FLAC") == 5
    assert codec.rekordbox_file_type("MP3") == 1
    assert codec.SOURCE_FILE_TYPES["M4A"] == 4


# ---------------------------------------------------------------------------
# FFmpeg command builder (Threat CI-1: arg-list, never a shell string)
# ---------------------------------------------------------------------------


def test_aiff_cmd_16_and_24_bit():
    c16 = codec.build_ffmpeg_cmd(
        "ffmpeg", "in.m4a", "out.aiff", "AIFF", bit_depth=16, sample_rate=44100
    )
    assert "-c:a" in c16 and c16[c16.index("-c:a") + 1] == "pcm_s16le"
    assert "-ar" in c16 and c16[c16.index("-ar") + 1] == "44100"
    assert "-vn" in c16 and "-map_metadata" in c16 and c16[-1] == "out.aiff"
    c24 = codec.build_ffmpeg_cmd(
        "ffmpeg", "in.m4a", "o.aiff", "AIFF", bit_depth=24, sample_rate=48000
    )
    assert c24[c24.index("-c:a") + 1] == "pcm_s24le"


def test_flac_uses_s32_for_24bit():
    c = codec.build_ffmpeg_cmd(
        "ffmpeg", "in.wav", "o.flac", "FLAC", bit_depth=24, sample_rate=44100
    )
    assert c[c.index("-c:a") + 1] == "flac"
    assert "-sample_fmt" in c and c[c.index("-sample_fmt") + 1] == "s32"
    c16 = codec.build_ffmpeg_cmd(
        "ffmpeg", "in.wav", "o.flac", "FLAC", bit_depth=16, sample_rate=44100
    )
    assert c16[c16.index("-sample_fmt") + 1] == "s16"


def test_mp3_quality_and_id3():
    c = codec.build_ffmpeg_cmd(
        "ffmpeg", "in.aiff", "o.mp3", "MP3", mp3_quality=2, sample_rate=44100
    )
    assert c[c.index("-c:a") + 1] == "libmp3lame"
    assert c[c.index("-q:a") + 1] == "2"
    assert "-write_id3v2" in c


def test_cmd_is_arg_list_no_shell_injection():
    """A crafted filename stays a single list element — no shell parsing."""
    evil = "x; rm -rf ~ #.m4a"
    c = codec.build_ffmpeg_cmd("ffmpeg", evil, "out.aiff", "AIFF", sample_rate=44100)
    assert evil in c  # passed verbatim as one element, never concatenated
    assert all(isinstance(part, str) for part in c)


def test_no_ar_flag_when_sample_rate_missing():
    c = codec.build_ffmpeg_cmd("ffmpeg", "in.m4a", "o.aiff", "AIFF", sample_rate=None)
    assert "-ar" not in c


# ---------------------------------------------------------------------------
# Bit-depth parsing (OQ6 — sample_fmt primary, bits_per_raw_sample fallback)
# ---------------------------------------------------------------------------


def test_parse_bit_depth_sample_fmt():
    assert codec.parse_bit_depth("s16,") == 16
    assert codec.parse_bit_depth("s32,24") == 24
    assert codec.parse_bit_depth("s16p") == 16
    assert codec.parse_bit_depth("s24le") == 24


def test_parse_bit_depth_bits_fallback():
    # fltp sample_fmt → fall through to bits_per_raw_sample
    assert codec.parse_bit_depth("fltp,24") == 24
    assert codec.parse_bit_depth("fltp,16") == 16


def test_parse_bit_depth_ambiguous_defaults_16():
    assert codec.parse_bit_depth("") == 16
    assert codec.parse_bit_depth("fltp") == 16
    assert codec.parse_bit_depth("unknown,garbage") == 16


# ---------------------------------------------------------------------------
# Disk pre-flight (OQ4 — 1.5x abort, 1.2x warn)
# ---------------------------------------------------------------------------


def test_estimate_target_bytes():
    assert codec.estimate_target_bytes(1000, "AIFF") == 5500
    assert codec.estimate_target_bytes(1000, "FLAC") == 3000
    assert codec.estimate_target_bytes(1000, "MP3") == 1000
    assert codec.estimate_target_bytes(0, "AIFF") == 0


def test_disk_verdict_abort_warn_ok():
    est = 1000
    # free below the 1.2x floor -> abort
    v = codec.disk_verdict(free_bytes=1100, estimated_target_bytes=est)
    assert v["abort"] and not v["warning"]
    # free between the 1.2x floor and the 1.5x comfort line -> warning, not abort
    v = codec.disk_verdict(free_bytes=1300, estimated_target_bytes=est)
    assert not v["abort"] and v["warning"]
    # free at/above 1.5x -> clean
    v = codec.disk_verdict(free_bytes=2000, estimated_target_bytes=est)
    assert not v["abort"] and not v["warning"]
    # exactly at the 1.2x floor is acceptable (>= floor -> not abort)
    v = codec.disk_verdict(free_bytes=1200, estimated_target_bytes=est)
    assert not v["abort"] and v["warning"]


# ---------------------------------------------------------------------------
# Progress tracker
# ---------------------------------------------------------------------------


def test_tracker_register_and_get():
    tid = tracker.register(trigger="user_format_pick", target="AIFF", scope="playlist 7", total=10)
    t = tracker.get(tid)
    assert t["status"] == "Queued" and t["total"] == 10 and t["progress"] == 0
    assert t["converted"] == 0 and t["failed"] == 0 and t["beatgrid_preserved"] is True


def test_tracker_mark_track_progress():
    tid = tracker.register(trigger="user_format_pick", target="AIFF", scope="s", total=4)
    tracker.update(tid, status="Converting")
    tracker.mark_track(tid, "a.m4a", ok=True)
    tracker.mark_track(tid, "b.m4a", ok=True)
    tracker.mark_track(tid, "c.m4a", ok=False)
    t = tracker.get(tid)
    assert t["converted"] == 2 and t["failed"] == 1
    assert t["progress"] == 75  # 3 of 4 done
    assert t["current_track"] == "c.m4a"


def test_tracker_beatgrid_flag_sticks_false():
    tid = tracker.register(trigger="quality_verdict", target="FLAC", scope="s", total=2)
    tracker.mark_track(tid, "a", ok=True, beatgrid_preserved=False)
    tracker.mark_track(tid, "b", ok=True, beatgrid_preserved=True)
    assert tracker.get(tid)["beatgrid_preserved"] is False  # never flips back to True


def test_tracker_status_history_dedupes():
    tid = tracker.register(trigger="user_format_pick", target="WAV", scope="s", total=1)
    tracker.update(tid, status="Converting")
    tracker.update(tid, status="Converting")  # duplicate, should not append
    tracker.update(tid, status="Completed")
    stages = [h["stage"] for h in tracker.get(tid)["stage_history"]]
    assert stages == ["Queued", "Converting", "Completed"]


def test_tracker_clear_finished():
    tid_done = tracker.register(trigger="x", target="MP3", scope="s", total=1)
    tracker.update(tid_done, status="Completed")
    tid_live = tracker.register(trigger="x", target="MP3", scope="s", total=1)
    tracker.update(tid_live, status="Converting")
    tracker.clear_finished()
    assert tracker.get(tid_done) is None
    assert tracker.get(tid_live) is not None
