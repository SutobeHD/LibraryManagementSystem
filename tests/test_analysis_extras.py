"""Tests for app/analysis_extras.py: E1-E8 on synthetic signals, the A1 tier rule and the
compute_extras contract (never raises, JSON-serialisable, fixed sub-dict names)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from app import analysis_extras as ax

SR = 44100
RNG = np.random.default_rng(7)


def _noise(seconds: float = 12.0, amp: float = 0.3) -> np.ndarray:
    return RNG.uniform(-amp, amp, int(seconds * SR)).astype(np.float32)


def _shape(x: np.ndarray, gain_db_of_hz, sr: int = SR) -> np.ndarray:
    """Apply a frequency-dependent gain (dB, vectorised over Hz) in the FFT domain."""
    spec = np.fft.rfft(x.astype(np.float64))
    freqs = np.fft.rfftfreq(len(x), 1.0 / sr)
    spec *= 10.0 ** (np.asarray(gain_db_of_hz(freqs), dtype=np.float64) / 20.0)
    return np.fft.irfft(spec, len(x)).astype(np.float32)


def _brickwall(x: np.ndarray, fc_hz: float, sr: int = SR) -> np.ndarray:
    return _shape(x, lambda f: np.where(f > fc_hz, -400.0, 0.0), sr)


def _sine(freq: float, seconds: float = 12.0, amp: float = 0.5) -> np.ndarray:
    t = np.arange(int(seconds * SR)) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _spectrum(x: np.ndarray, sr: int = SR, **kw) -> dict:
    return ax.analyze_spectrum(x, sr, **kw)[0]


# --------------------------------------------------------------------------- E1 geometry


def test_e1_brickwall_16k_is_hard_edge_tier_d():
    c = _spectrum(_brickwall(_noise(), 16000))
    assert c["hard_edge"] is True
    assert abs(c["cutoff_edge_hz"] - 16000) < 300
    assert c["edge_drop_db"] >= ax.HARD_EDGE_DB
    assert c["tier"] == "D" and c["tier_reason"] == "hard_edge"
    assert c["flags"] == []
    assert c["lame_estimate_kbps"] is None
    assert c["band_hz"] == ax.HARD_EDGE_BAND_HZ == 500.0


def test_e1_brickwall_19500_is_tier_b_lame_256():
    c = _spectrum(_brickwall(_noise(), 19500))
    assert abs(c["cutoff_edge_hz"] - 19500) < 300
    assert c["tier"] == "B"
    assert c["lame_estimate_kbps"] == 256
    assert c["flags"] == []


def test_e1_brickwall_20500_hard_edge_is_b_not_a():
    c = _spectrum(_brickwall(_noise(), 20500))
    assert c["hard_edge"] is True
    assert c["tier"] == "B"
    assert c["lame_estimate_kbps"] == 320


def test_e1_full_band_noise_is_tier_a_no_edge():
    c = _spectrum(_noise())
    assert c["hard_edge"] is False
    assert c["cutoff_edge_hz"] is None
    assert c["cutoff_thr_hz"] >= 20500
    assert c["zero_from_hz"] is None
    assert c["tier"] == "A" and c["tier_reason"] == "full_band"


def test_e1_dark_master_gentle_rolloff_is_no_tier_pruefen():
    # 8 dB/kHz above 12 kHz: -80 dB at Nyquist, no digital zero, no edge -> natural roll-off
    dark = _shape(_noise(), lambda f: np.minimum(0.0, -(f - 12000.0) / 1000.0 * 8.0))
    c = _spectrum(dark)
    assert c["hard_edge"] is False
    assert c["zero_from_hz"] is None
    assert 16000 < c["cutoff_thr_hz"] < 20500
    assert c["tier"] is None
    assert c["tier_reason"] == "rolloff"
    assert c["flags"] == ["pruefen"]


def test_e1_soft_lowpass_into_digital_zero_takes_tier_from_zero_start():
    # 30 dB/kHz slope from 15 kHz (15 dB per 500 Hz band: too soft for the edge test) that lands on a
    # -120 dB floor = codec lowpass with a soft filter. Zero region starts at the -100 dB crossing.
    soft = _shape(
        _noise(), lambda f: np.maximum(-120.0, np.minimum(0.0, -(f - 15000.0) / 1000.0 * 30.0))
    )
    c = _spectrum(soft)
    assert c["hard_edge"] is False
    assert c["zero_from_hz"] is not None and abs(c["zero_from_hz"] - 18333) < 400
    assert c["tier"] == "C" and c["tier_reason"] == "digital_zero"
    assert c["tier_cutoff_hz"] == c["zero_from_hz"]
    assert c["lame_estimate_kbps"] == 192
    assert c["flags"] == []


def test_e1_lowest_edge_wins_over_higher_encoder_lowpass():
    # music stops at 15.4 kHz (-80 dB residue), encoder lowpass at 19.96 kHz (-120 dB above)
    gain = lambda f: np.where(f > 19960.0, -120.0, np.where(f > 15400.0, -80.0, 0.0))  # noqa: E731
    c = _spectrum(_shape(_noise(), gain))
    assert c["hard_edge"] is True
    assert abs(c["cutoff_edge_hz"] - 15400) < 300
    assert c["tier"] == "D"
    assert c["zero_from_hz"] is not None and abs(c["zero_from_hz"] - 19960) < 300


def test_e1_anti_alias_filter_near_nyquist_is_not_an_edge():
    c = _spectrum(_brickwall(_noise(), 21800))
    assert c["hard_edge"] is False
    assert c["tier"] == "A" and c["tier_reason"] == "full_band"


def test_e1_band_width_parameter_changes_sensitivity():
    # 20 dB per 1 kHz: invisible at 500 Hz (10 dB), an edge at 2000 Hz (40 dB)
    slope = _shape(
        _noise(), lambda f: np.maximum(-200.0, np.minimum(0.0, -(f - 16000.0) / 1000.0 * 20.0))
    )
    assert _spectrum(slope, band_hz=500.0)["hard_edge"] is False
    assert _spectrum(slope, band_hz=2000.0)["hard_edge"] is True


def test_e1_sample_rate_meta_below_44k_forces_d():
    c = _spectrum(_noise(), sample_rate_meta=32000)
    assert c["tier"] == "D" and c["tier_reason"] == "sample_rate"
    assert c["sample_rate_used"] == 32000


# --------------------------------------------------------------------------- E1 tier rule (unit)


def test_cutoff_tier_a1_rule_unit():
    t = ax.cutoff_tier
    assert t(None, 20600, -65.0, 44100)["tier"] == "A"
    assert t(20600, 20600, -120.0, 44100)["tier"] == "B"  # an edge is never A
    assert t(None, 20700, -65.0, 48000)["tier"] is None  # 48k needs >= 21 kHz for A
    assert t(None, 21000, -65.0, 48000)["tier"] == "A"
    assert t(19000, 19000, -120.0, 44100)["tier"] == "B"
    assert t(18000, 18000, -120.0, 44100)["tier"] == "C"
    assert t(17000, 17000, -120.0, 44100)["tier"] == "D"
    assert t(None, 22000, None, 32000) == {
        **t(None, 22000, None, 32000),
        "tier": "D",
        "tier_reason": "sample_rate",
    }
    boundary = t(16800, 16800, -120.0, 44100)
    assert boundary["tier"] == "D" and boundary["flags"] == ["pruefen", "boundary"]
    assert boundary["lame_estimate_kbps"] == 128
    rolloff = t(None, 15000, -80.0, 44100)
    assert rolloff["tier"] is None and rolloff["tier_reason"] == "rolloff"
    assert rolloff["flags"] == ["pruefen"] and rolloff["tier_cutoff_hz"] is None


def test_cutoff_tier_digital_zero_paths():
    t = ax.cutoff_tier
    # spec case: digital-zero floor above the threshold cutoff -> that cutoff is the edge
    dz = t(None, 14600, -118.0, 44100)
    assert dz["tier"] == "D" and dz["tier_reason"] == "digital_zero"
    assert dz["tier_cutoff_hz"] == 14600
    # zero region starting far above a dark threshold cutoff -> the codec lowpass is the edge
    far = t(None, 9500, -88.0, 44100, zero_from_hz=18760)
    assert far["tier"] == "C" and far["tier_reason"] == "digital_zero"
    assert far["tier_cutoff_hz"] == 18760 and far["lame_estimate_kbps"] == 192
    # zero region at the Nyquist of a 44.1k source inside a 48k file = SRC filter, not a codec
    src = t(None, 21000, -120.0, 48000, zero_from_hz=22050)
    assert src["tier"] == "A" and src["tier_reason"] == "full_band"
    adc = t(None, 15000, -110.0, 44100, zero_from_hz=21900)
    assert adc["tier"] is None and adc["tier_reason"] == "rolloff"
    assert t(None, 21000, -120.0, 48000)["tier"] == "A"  # thr at guard without zero_from


# --------------------------------------------------------------------------- E2


def test_e2_clipped_square_counts_runs_sine_does_not():
    square = np.sign(_sine(100, amp=1.0)).astype(np.float32)
    clipped = ax.clipping_stats(square)
    assert clipped["samples_total"] > 0
    assert clipped["runs_total"] > 0
    assert clipped["per_channel"][0]["max_run"] >= ax.CLIP_MIN_RUN
    assert ax.clipping_stats(_sine(100, amp=0.5))["samples_total"] == 0


def test_e2_short_runs_below_three_are_ignored():
    x = np.zeros(1000, dtype=np.float32)
    x[10:12] = 1.0  # run of 2
    x[100:103] = -1.0  # run of 3
    c = ax.clipping_stats(x)
    assert c["samples_total"] == 3
    assert c["runs_total"] == 1


def test_e2_true_peak_of_sine_matches_amplitude():
    assert abs(ax.true_peak_dbtp(_sine(1000, amp=0.5)) - (-6.02)) < 0.1


# --------------------------------------------------------------------------- E3-E7


def test_e3_dynamics_plr_and_crest():
    d = ax.dynamics_stats(_sine(1000, amp=0.5), lufs=-14.0)
    assert abs(d["peak_dbfs"] - (-6.02)) < 0.05
    assert abs(d["plr"] - 7.98) < 0.1
    assert abs(d["crest_db"] - 3.01) < 0.05
    assert ax.dynamics_stats(_sine(1000), lufs=-100.0)["plr"] is None
    assert ax.dynamics_stats(_sine(1000), lufs=None)["plr"] is None


def test_e3_loudness_range_steady_tone_is_near_zero_and_short_is_none():
    stereo = np.stack([_sine(1000), _sine(1000)])
    lra = ax.loudness_range(stereo, SR)
    assert lra is not None and lra < 0.5
    assert ax.loudness_range(_sine(1000, seconds=1.0), SR) is None


def test_e4_silence_leading_and_trailing():
    x = np.concatenate([np.zeros(SR), _sine(440, seconds=2.0), np.zeros(2 * SR)]).astype(np.float32)
    s = ax.silence_stats(x, SR)
    assert abs(s["leading_ms"] - 1000) < 5
    assert abs(s["trailing_ms"] - 2000) < 5
    assert ax.silence_stats(np.zeros(SR, dtype=np.float32), SR)["all_silent"] is True


def test_e5_dc_offset_per_channel():
    stereo = np.stack([_sine(440) + 0.1, _sine(440) - 0.2]).astype(np.float32)
    dc = ax.dc_offset(stereo)
    assert abs(dc[0] - 0.1) < 1e-3
    assert abs(dc[1] + 0.2) < 1e-3


def test_e6_bass_share_of_50hz_tone():
    freqs, _, power = ax.power_spectrum_stats(_sine(50), SR)
    share = ax.bass_share(freqs, power)
    assert share["share_60"] > 0.9
    assert share["share_120"] > share["share_60"] - 1e-9
    freqs, _, power = ax.power_spectrum_stats(_sine(5000), SR)
    assert ax.bass_share(freqs, power)["share_120"] < 0.01


def test_e7_low_band_correlation_same_inverted_mono():
    bass = _sine(50)
    assert ax.low_band_correlation(np.stack([bass, bass]), SR) > 0.99
    assert ax.low_band_correlation(np.stack([bass, -bass]), SR) < -0.99
    wide = np.stack([bass + _noise(amp=0.05), -bass + _noise(amp=0.05)])
    assert ax.low_band_correlation(wide, SR) < 0.0  # bass cancels in mono
    assert ax.low_band_correlation(bass, SR) is None


# --------------------------------------------------------------------------- E8


@pytest.fixture
def no_fpcalc(monkeypatch, tmp_path):
    monkeypatch.setattr(ax.shutil, "which", lambda name, *a, **kw: None)
    monkeypatch.setenv("FPCALC_DIR", str(tmp_path / "nowhere"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    return tmp_path


def test_e8_fingerprint_unavailable_when_fpcalc_missing(no_fpcalc):
    assert ax.find_fpcalc() is None
    res = ax.fingerprint_file(str(no_fpcalc / "track.wav"))
    assert res is not None and res["available"] is False
    assert ax.fingerprint_file(None) is None
    assert ax.fingerprint_file("") is None


def test_e8_find_fpcalc_via_fpcalc_dir_prepends_path(no_fpcalc, monkeypatch):
    fake_dir = no_fpcalc / "fp"
    fake_dir.mkdir()
    (fake_dir / "fpcalc.exe").write_bytes(b"")
    monkeypatch.setenv("FPCALC_DIR", str(fake_dir))
    found = ax.find_fpcalc()
    assert found is not None and Path(found).parent == fake_dir
    assert ax.os.environ["PATH"].split(ax.os.pathsep)[0] == str(fake_dir)


def test_e8_find_fpcalc_via_winget_package_dir(no_fpcalc, monkeypatch):
    pkg = (
        no_fpcalc
        / "localappdata"
        / "Microsoft"
        / "WinGet"
        / "Packages"
        / "AcoustID.Chromaprint_Microsoft.Winget.Source_8wekyb3d8bbwe"
        / "chromaprint-fpcalc-1.6.2-windows-x86_64"
    )
    pkg.mkdir(parents=True)
    (pkg / "fpcalc.exe").write_bytes(b"")
    found = ax.find_fpcalc()
    assert found is not None and Path(found).parent == pkg


def test_e8_fingerprint_never_raises(no_fpcalc, monkeypatch):
    from app import external_track_match as etm

    monkeypatch.setattr(ax, "find_fpcalc", lambda: "fpcalc")
    monkeypatch.setattr(etm, "fingerprint", lambda *a, **k: 1 / 0)
    res = ax.fingerprint_file(str(no_fpcalc / "t.wav"))
    assert res is not None and res["available"] is True
    assert "ZeroDivisionError" in res["error"]


def test_e8_fingerprint_maps_sentinels(no_fpcalc, monkeypatch):
    from app import external_track_match as etm

    monkeypatch.setattr(ax, "find_fpcalc", lambda: "fpcalc")
    calls: list[dict] = []

    def fake(path, **kw):
        calls.append(kw)
        return etm.Fingerprint(fpcalc_hash="AQAD" * 10, duration_s=123.0)

    monkeypatch.setattr(etm, "fingerprint", fake)
    res = ax.fingerprint_file(str(no_fpcalc / "t.wav"))
    assert res == {
        "available": True,
        "fpcalc_hash": "AQAD" * 10,
        "duration_s": 123.0,
        "sample_seconds": ax.FPCALC_SAMPLE_SECONDS,
        "elapsed_s": res["elapsed_s"],
    }
    # sandbox root = the file's own directory, never an app.main import
    assert calls[0]["allowed_roots"] == [Path(no_fpcalc / "t.wav").resolve().parent]
    assert calls[0]["timeout"] == ax.FPCALC_TIMEOUT_S

    monkeypatch.setattr(etm, "fingerprint", lambda *a, **k: etm.DecodeError("rc=1"))
    assert ax.fingerprint_file(str(no_fpcalc / "t.wav"))["error"] == "rc=1"
    monkeypatch.setattr(etm, "fingerprint", lambda *a, **k: etm.Timeout("slow"))
    assert ax.fingerprint_file(str(no_fpcalc / "t.wav"))["error"] == "slow"
    monkeypatch.setattr(etm, "fingerprint", lambda *a, **k: etm.BinaryMissing("gone"))
    assert ax.fingerprint_file(str(no_fpcalc / "t.wav"))["available"] is False


# --------------------------------------------------------------------------- compute_extras


def _stereo_track() -> np.ndarray:
    bass = _sine(50, amp=0.4)
    hf = _brickwall(_noise(amp=0.1), 16000)
    return np.stack([bass + hf, bass + hf]).astype(np.float32)


def test_compute_extras_contract_and_json(no_fpcalc, tmp_path):
    y = _stereo_track()
    out = ax.compute_extras(
        y, SR, y.mean(axis=0), SR, lufs=-9.0, first_signal_ms=12.5, sample_rate_meta=SR
    )
    assert out["extras_version"] == 1
    for key in ("spectrum", "clipping", "dynamics", "silence", "dc", "bass", "lowband"):
        assert isinstance(out[key], dict) and "error" not in out[key], key
    assert out["fingerprint"] is None  # no file_path -> E8 skipped
    sp = out["spectrum"]
    assert sp["tier"] == "D" and sp["hard_edge"] is True
    for key in (
        "cutoff_edge_hz",
        "cutoff_thr_hz",
        "zero_from_hz",
        "hard_edge",
        "edge_drop_db",
        "floor_rel_db",
        "tier",
        "tier_reason",
        "flags",
        "lame_estimate_kbps",
    ):
        assert key in sp, key
    assert out["clipping"]["samples_total"] == 0 and "true_peak_dbtp" in out["clipping"]
    assert out["dynamics"]["plr"] is not None and "lra" in out["dynamics"]
    assert out["silence"]["first_signal_ms"] == 12.5 and out["silence"]["trailing_ms"] < 50
    assert len(out["dc"]["per_channel"]) == 2 and out["dc"]["max_abs"] is not None
    assert out["bass"]["share_60"] > 0.5
    assert out["lowband"]["corr"] > 0.99 and out["lowband"]["band_hz"] == 150.0
    for stage in ("spectrum", "clipping", "dynamics", "silence", "dc", "lowband"):
        assert stage in out["t_stage"]
    json.dumps(out)  # numpy scalars converted

    with_file = ax.compute_extras(
        y, SR, y.mean(axis=0), SR, lufs=-9.0, first_signal_ms=None, file_path=str(tmp_path / "x")
    )
    assert with_file["fingerprint"] == {"available": False, "reason": "fpcalc not found"}
    assert "fingerprint" in with_file["t_stage"]


def test_compute_extras_mono_input_and_empty_native_fallback():
    mono = _brickwall(_noise(), 19500)
    out = ax.compute_extras(mono, SR, mono, SR, lufs=None, first_signal_ms=None)
    assert out["spectrum"]["tier"] == "B"
    assert out["lowband"]["corr"] is None
    assert out["dynamics"]["plr"] is None
    assert len(out["dc"]["per_channel"]) == 1

    fallback = ax.compute_extras(
        np.zeros(0, dtype=np.float32), 48000, mono, SR, lufs=None, first_signal_ms=None
    )
    assert fallback["spectrum"]["tier"] == "B" and fallback["spectrum"]["sample_rate_used"] == SR


def test_compute_extras_block_failure_is_isolated(monkeypatch):
    y = _stereo_track()
    monkeypatch.setattr(ax, "true_peak_dbtp", lambda *_a, **_k: 1 / 0)
    out = ax.compute_extras(y, SR, y.mean(axis=0), SR, lufs=-9.0, first_signal_ms=None)
    assert "error" in out["clipping"] and "ZeroDivisionError" in out["clipping"]["error"]
    assert "error" not in out["spectrum"] and "error" not in out["dynamics"]
    assert "clipping" in out["t_stage"]


def test_compute_extras_unsupported_shape_never_raises():
    bad = np.zeros((2, 2, 100), dtype=np.float32)
    out = ax.compute_extras(bad, SR, bad.ravel(), SR, lufs=None, first_signal_ms=None)
    for key in ("spectrum", "clipping", "dynamics", "silence", "dc", "bass", "lowband"):
        assert "error" in out[key]
    assert out["fingerprint"] is None and out["extras_version"] == 1
    json.dumps(out)
