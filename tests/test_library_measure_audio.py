"""Tests for scripts/library_measure_audio.py: the Stage-E extras (E1-E7) on synthetic signals,
the resume key / skip logic and the error-row behaviour. Heavy engine blocks are mocked."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import library_measure_audio as lma  # noqa: E402

SR = 44100
RNG = np.random.default_rng(7)


def _noise(seconds: float = 12.0, amp: float = 0.3) -> np.ndarray:
    return RNG.uniform(-amp, amp, int(seconds * SR)).astype(np.float32)


def _brickwall(x: np.ndarray, fc_hz: float, sr: int = SR) -> np.ndarray:
    spec = np.fft.rfft(x)
    spec[np.fft.rfftfreq(len(x), 1.0 / sr) > fc_hz] = 0
    return np.fft.irfft(spec, len(x)).astype(np.float32)


def _sine(freq: float, seconds: float = 12.0, amp: float = 0.5) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _cutoff(x: np.ndarray, sr: int = SR) -> dict:
    freqs, median_db, _ = lma.power_spectrum_stats(x, sr)
    c = lma.spectral_cutoff(freqs, median_db)
    c.update(lma.cutoff_tier(c["cutoff_hz"], sr, c["hard_edge"]))
    return c


# --------------------------------------------------------------------------- E1


def test_e1_brickwall_16k_is_hard_edge_tier_d():
    c = _cutoff(_brickwall(_noise(), 16000))
    assert abs(c["cutoff_hz"] - 16000) < 300
    assert c["hard_edge"] is True
    assert c["edge_drop_db"] >= lma.HARD_EDGE_DB
    assert c["tier"] == "D"
    assert c["pruefen"] is False


def test_e1_brickwall_19500_is_tier_b_lame_256():
    c = _cutoff(_brickwall(_noise(), 19500))
    assert abs(c["cutoff_hz"] - 19500) < 300
    assert c["tier"] == "B"
    assert c["lame_bitrate_est"] == 256


def test_e1_brickwall_20500_hard_edge_is_b_not_a():
    c = _cutoff(_brickwall(_noise(), 20500))
    assert c["hard_edge"] is True
    assert c["tier"] == "B"
    assert c["lame_bitrate_est"] == 320


def test_e1_full_band_noise_is_tier_a_no_edge():
    c = _cutoff(_noise())
    assert c["hard_edge"] is False
    assert c["cutoff_hz"] >= 20500
    assert c["tier"] == "A"


def test_e1_tier_thresholds_unit():
    assert lma.cutoff_tier(20600, 44100, False)["tier"] == "A"
    assert lma.cutoff_tier(20600, 44100, True)["tier"] == "B"
    assert lma.cutoff_tier(20700, 48000, False)["tier"] == "B"  # 48k needs >= 21 kHz for A
    assert lma.cutoff_tier(21000, 48000, False)["tier"] == "A"
    assert lma.cutoff_tier(19000, 44100, True)["tier"] == "B"
    assert lma.cutoff_tier(18000, 44100, True)["tier"] == "C"
    assert lma.cutoff_tier(17000, 44100, True)["tier"] == "D"
    assert lma.cutoff_tier(22000, 32000, False)["tier"] == "D"
    assert lma.cutoff_tier(17100, 44100, True)["pruefen"] is True
    assert lma.cutoff_tier(15000, 44100, False)["pruefen_reason"] == "rolloff"


# --------------------------------------------------------------------------- E2


def test_e2_clipped_square_counts_runs_sine_does_not():
    square = np.sign(_sine(100, amp=1.0)).astype(np.float32)
    clipped = lma.clipping_stats(square)
    assert clipped["samples_total"] > 0
    assert clipped["runs_total"] > 0
    assert clipped["per_channel"][0]["max_run"] >= lma.CLIP_MIN_RUN
    assert lma.clipping_stats(_sine(100, amp=0.5))["samples_total"] == 0


def test_e2_short_runs_below_three_are_ignored():
    x = np.zeros(1000, dtype=np.float32)
    x[10:12] = 1.0  # run of 2
    x[100:103] = -1.0  # run of 3
    c = lma.clipping_stats(x)
    assert c["samples_total"] == 3
    assert c["runs_total"] == 1


def test_e2_true_peak_of_sine_matches_amplitude():
    assert abs(lma.true_peak_dbtp(_sine(1000, amp=0.5)) - (-6.02)) < 0.1


# --------------------------------------------------------------------------- E3-E7


def test_e3_dynamics_plr_and_crest():
    d = lma.dynamics_stats(_sine(1000, amp=0.5), lufs=-14.0)
    assert abs(d["peak_dbfs"] - (-6.02)) < 0.05
    assert abs(d["plr"] - 7.98) < 0.1
    assert abs(d["crest_db"] - 3.01) < 0.05
    assert lma.dynamics_stats(_sine(1000), lufs=-100.0)["plr"] is None


def test_e3_loudness_range_steady_tone_is_near_zero_and_short_is_none():
    stereo = np.stack([_sine(1000), _sine(1000)])
    lra = lma.loudness_range(stereo, SR)
    assert lra is not None and lra < 0.5
    assert lma.loudness_range(_sine(1000, seconds=1.0), SR) is None


def test_e4_silence_leading_and_trailing():
    x = np.concatenate([np.zeros(SR), _sine(440, seconds=2.0), np.zeros(2 * SR)]).astype(np.float32)
    s = lma.silence_stats(x, SR)
    assert abs(s["leading_ms"] - 1000) < 5
    assert abs(s["trailing_ms"] - 2000) < 5
    assert lma.silence_stats(np.zeros(SR, dtype=np.float32), SR)["all_silent"] is True


def test_e5_dc_offset_per_channel():
    stereo = np.stack([_sine(440) + 0.1, _sine(440) - 0.2]).astype(np.float32)
    dc = lma.dc_offset(stereo)
    assert abs(dc[0] - 0.1) < 1e-3
    assert abs(dc[1] + 0.2) < 1e-3


def test_e6_bass_share_of_50hz_tone():
    freqs, _, power = lma.power_spectrum_stats(_sine(50), SR)
    share = lma.bass_share(freqs, power)
    assert share["share_60"] > 0.9
    assert share["share_120"] > share["share_60"] - 1e-9
    freqs, _, power = lma.power_spectrum_stats(_sine(5000), SR)
    assert lma.bass_share(freqs, power)["share_120"] < 0.01


def test_e7_low_band_correlation_same_inverted_mono():
    bass = _sine(50)
    assert lma.low_band_correlation(np.stack([bass, bass]), SR) > 0.99
    assert lma.low_band_correlation(np.stack([bass, -bass]), SR) < -0.99
    wide = np.stack([bass + _noise(amp=0.05), -bass + _noise(amp=0.05)])
    assert lma.low_band_correlation(wide, SR) < 0.0  # bass cancels in mono
    assert lma.low_band_correlation(bass, SR) is None


# --------------------------------------------------------------------------- keys / plan


def _write_wav(path: Path, data: np.ndarray, sr: int = SR) -> Path:
    sf.write(str(path), data.T if data.ndim == 2 else data, sr, subtype="PCM_16")
    return path


def test_plan_tracks_splits_streams_missing_local_and_skips_done(tmp_path):
    files = [_write_wav(tmp_path / f"t{i}.wav", _sine(440, seconds=0.5)) for i in range(3)]
    tracks = [
        {"ID": "s1", "path": "soundcloud:tracks:1"},
        {"ID": "m1", "path": str(tmp_path / "gone.wav")},
        *({"ID": f"l{i}", "path": str(f)} for i, f in enumerate(files)),
    ]
    plan = lma.plan_tracks(tracks, set())
    assert len(plan.streams) == 1 and len(plan.missing) == 1
    assert plan.candidates == 3 and len(plan.todo) == 3 and plan.skipped == 0
    key0 = plan.todo[0]["_key"]
    assert key0.startswith("l0|") and key0.endswith(f"|{files[0].stat().st_size}")

    plan2 = lma.plan_tracks(tracks, {key0})
    assert len(plan2.todo) == 2 and plan2.skipped == 1
    assert all(t["_key"] != key0 for t in plan2.todo)

    only = lma.plan_tracks(tracks, set(), only_ids={"l2"})
    assert [t["ID"] for t in only.todo] == ["l2"]


def test_plan_tracks_seeded_sample_is_stable(tmp_path):
    files = [_write_wav(tmp_path / f"t{i}.wav", _sine(440, seconds=0.2)) for i in range(8)]
    tracks = [{"ID": f"l{i}", "path": str(f)} for i, f in enumerate(files)]
    a = [t["ID"] for t in lma.plan_tracks(tracks, set(), limit=3, seed=1).todo]
    b = [t["ID"] for t in lma.plan_tracks(tracks, set(), limit=3, seed=1).todo]
    c = [t["ID"] for t in lma.plan_tracks(tracks, set(), limit=3, seed=2).todo]
    assert a == b and len(a) == 3
    assert a != c
    assert [t["ID"] for t in lma.plan_tracks(tracks, set(), limit=2).todo] == ["l0", "l1"]


def test_key_changes_when_file_changes(tmp_path):
    f = _write_wav(tmp_path / "t.wav", _sine(440, seconds=0.2))
    track = {"ID": "1", "path": str(f)}
    k1 = lma.make_key(track, f.stat())
    _write_wav(f, _sine(440, seconds=0.4))
    assert lma.make_key(track, f.stat()) != k1


def test_load_done_keys_ignores_garbage_lines(tmp_path):
    out = tmp_path / "audio.jsonl"
    out.write_text(
        json.dumps({"track_key": "a|b|1|2"})
        + "\nnot json\n\n"
        + json.dumps({"track_key": "c|d|3|4", "key": "Am"})
        + "\n",
        encoding="utf-8",
    )
    assert lma.load_done_keys(out) == {"a|b|1|2", "c|d|3|4"}
    assert lma.load_done_keys(tmp_path / "missing.jsonl") == set()


def test_track_budget():
    assert lma.track_budget_s({"TotalTime": 300}) == 3000.0
    assert lma.track_budget_s({"TotalTime": 5}) == lma.MIN_BUDGET_S
    assert lma.track_budget_s({}) == lma.DEFAULT_BUDGET_S


# --------------------------------------------------------------------------- measure_task / track


def test_measure_task_turns_undecodable_file_into_error_row(tmp_path):
    bad = tmp_path / "bad.wav"
    bad.write_text("this is not audio", encoding="utf-8")
    row = lma.measure_task({"ID": "x", "path": str(bad), "Title": "t"}, "high")
    assert row["status"] == "error"
    assert row["error_type"]
    assert row["error_message"]
    assert row["id"] == "x" and row["depth"] == "high"
    assert row["track_key"] == "x|" + str(bad) + "|0|0"
    assert "t_cpu_s" in row and "t_wall_s" in row and row["worker_pid"]


@pytest.fixture
def mocked_engine(monkeypatch):
    ae = lma._engine()
    monkeypatch.setattr(
        ae,
        "detect_beats",
        lambda y, sr, **kw: {
            "bpm": 130.0,
            "bpm_raw": 129.9,
            "beats": [0, 1],
            "beat_count": 2,
            "downbeat_index": 0,
            "method": "mock",
            "grid_confidence": 0.5,
        },
    )
    monkeypatch.setattr(
        ae,
        "detect_key",
        lambda y, sr: {"key": "Am", "camelot": "8A", "confidence": 0.7, "method": "mock"},
    )
    monkeypatch.setattr(
        ae,
        "detect_phrases",
        lambda y, sr, bpm, duration: [
            {"label": "Intro", "mood": "Low", "energy": 0.2, "start_ms": 0, "end_ms": 5000, "x": 1}
        ],
    )
    monkeypatch.setattr(
        ae,
        "detect_tempo_changes",
        lambda y, sr, bpm: [{"time": 0.0, "bpm": 130.0}, {"time": 5.0, "bpm": 131.0}],
    )
    return ae


def test_measure_track_high_and_rekordbox(tmp_path, mocked_engine):
    bass = _sine(50, amp=0.4)
    stereo = np.stack(
        [bass + _brickwall(_noise(amp=0.1), 16000), bass + _brickwall(_noise(amp=0.1), 16000)]
    )
    wav = _write_wav(tmp_path / "track.wav", stereo)

    high = lma.measure_track(str(wav), "high")
    assert high["depth"] == "high"
    assert high["channels"] == 2 and high["sample_rate_native"] == SR
    assert high["bpm"] == 130.0 and high["key"] == "Am" and high["beat_method"] == "mock"
    assert high["phrases"] == [
        {"label": "Intro", "mood": "Low", "energy": 0.2, "start_ms": 0, "end_ms": 5000}
    ]
    assert high["tempo_anchors"] == {"count": 2, "bpm_min": 130.0, "bpm_max": 131.0}
    assert "beats" not in high and "waveform" not in high
    assert high["cutoff"]["tier"] == "D" and high["cutoff"]["hard_edge"] is True
    assert high["low_band_corr"] > 0.99
    assert high["stereo"]["phase_correlation"] > 0.9
    assert high["bass"]["share_60"] > 0.5
    assert high["clipping"]["samples_total"] == 0
    assert high["dynamics"]["plr"] is not None
    assert high["silence"]["trailing_ms"] < 50
    assert len(high["dc_offset"]) == 2
    for stage in ("load", "beats", "key", "lufs", "spectrum", "clipping", "dynamics"):
        assert stage in high["t_stage"]

    rb = lma.measure_track(str(wav), "rekordbox")
    assert rb["depth"] == "rekordbox"
    for absent in ("lufs", "mood", "cutoff", "clipping", "dynamics", "low_band_corr"):
        assert absent not in rb
    assert "spectrum" not in rb["t_stage"] and "beats" in rb["t_stage"]

    with pytest.raises(ValueError):
        lma.measure_track(str(wav), "medium")


def test_measure_task_keeps_resume_key_separate_from_musical_key(tmp_path, mocked_engine):
    wav = _write_wav(tmp_path / "t.wav", np.stack([_sine(50), _sine(50)]))
    track = {"ID": "7", "path": str(wav), "_key": "7|p|1|2", "_mtime": 1, "_size": 2}
    row = lma.measure_task(track, "rekordbox")
    assert row["status"] == "ok"
    assert row["track_key"] == "7|p|1|2"
    assert row["key"] == "Am"
    out = tmp_path / "o.jsonl"
    out.write_text(json.dumps(row) + "\n", encoding="utf-8")
    assert lma.load_done_keys(out) == {"7|p|1|2"}
