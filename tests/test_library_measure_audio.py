"""Tests for scripts/library_measure_audio.py: resume key / skip logic, error rows, the summary
and measure_track wiring of app.analysis_extras.compute_extras. Heavy engine blocks are mocked;
the E1-E8 measurements themselves are covered by tests/test_analysis_extras.py."""

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


def _write_wav(path: Path, data: np.ndarray, sr: int = SR) -> Path:
    sf.write(str(path), data.T if data.ndim == 2 else data, sr, subtype="PCM_16")
    return path


# --------------------------------------------------------------------------- keys / plan


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


def test_cli_defaults_follow_handover_3_5_1():
    args = lma.parse_args([])
    assert args.workers == 10
    assert args.max_tasks_per_child == 10
    assert args.progress_every == 50
    assert args.depth == "high"


# --------------------------------------------------------------------------- summary


def test_summary_path_and_summarize_rows(tmp_path):
    out = tmp_path / "audio.jsonl"
    assert lma.summary_path_for(out) == tmp_path / "audio.summary.json"
    rows = [
        {
            "track_key": "1|a|1|1",
            "status": "ok",
            "depth": "high",
            "t_cpu_s": 40.0,
            "spectrum": {
                "tier": "B",
                "tier_reason": "hard_edge",
                "flags": ["pruefen", "boundary"],
                "lame_estimate_kbps": 320,
                "cutoff_edge_hz": 20250.0,
            },
            "clipping": {"error": "boom"},
            "fingerprint": {"available": True, "fpcalc_hash": "AQAD"},
        },
        {
            "track_key": "2|b|1|1",
            "status": "ok",
            "depth": "high",
            "t_cpu_s": 60.0,
            "spectrum": {"tier": None, "tier_reason": "rolloff", "flags": ["pruefen"]},
            "fingerprint": {"available": False},
        },
        {"track_key": "3|c|1|1", "status": "ok", "depth": "high", "cutoff": {"tier": "D"}},
        {"track_key": "4|d|1|1", "status": "ok", "depth": "rekordbox", "t_cpu_s": 30.0},
        {"track_key": "5|e|1|1", "status": "error", "error_type": "ValueError"},
        {"track_key": "6|f|0|0", "status": "stream"},
    ]
    out.write_text("".join(json.dumps(r) + "\n" for r in rows) + "garbage\n", encoding="utf-8")
    s = lma.summarize_rows(out)
    assert s["total"] == 6
    assert s["status"] == {"ok": 4, "error": 1, "stream": 1}
    assert s["tiers"] == {"B": 1, "None": 1}
    assert s["tier_reasons"] == {"hard_edge": 1, "rolloff": 1}
    assert s["flags"] == {"pruefen": 2, "boundary": 1}
    assert s["lame_estimate_kbps"] == {"320": 1}
    assert s["fingerprint"] == {"available": 1, "unavailable": 1, "error": 0, "skipped": 0}
    assert s["extras_block_errors"] == 1
    assert s["legacy_rows"] == 1
    assert s["t_cpu_s"]["median"] == 40.0 and s["t_cpu_s"]["max"] == 60.0
    assert s["cutoff_edge_hz"]["min"] == 20250.0
    assert lma.summarize_rows(tmp_path / "missing.jsonl") == {"total": 0}


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

    high = lma.measure_track(str(wav), "high", sample_rate_meta=SR)
    assert high["depth"] == "high"
    assert high["channels"] == 2 and high["sample_rate_native"] == SR
    assert high["bpm"] == 130.0 and high["key"] == "Am" and high["beat_method"] == "mock"
    assert high["phrases"] == [
        {"label": "Intro", "mood": "Low", "energy": 0.2, "start_ms": 0, "end_ms": 5000}
    ]
    assert high["tempo_anchors"] == {"count": 2, "bpm_min": 130.0, "bpm_max": 131.0}
    assert "beats" not in high and "waveform" not in high
    # compute_extras sub-dicts land at the top level of the row
    assert high["extras_version"] == 1
    assert high["spectrum"]["tier"] == "D" and high["spectrum"]["hard_edge"] is True
    assert high["spectrum"]["sample_rate_used"] == SR
    assert high["lowband"]["corr"] > 0.99
    assert high["stereo"]["phase_correlation"] > 0.9
    assert high["bass"]["share_60"] > 0.5
    assert high["clipping"]["samples_total"] == 0
    assert high["dynamics"]["plr"] is not None
    assert high["silence"]["trailing_ms"] < 50
    assert high["silence"]["first_signal_ms"] == high["first_signal_ms"]
    assert len(high["dc"]["per_channel"]) == 2
    assert high["fingerprint"] is not None and "available" in high["fingerprint"]
    for absent in ("cutoff", "dc_offset", "low_band_corr"):
        assert absent not in high
    for stage in ("load", "beats", "key", "lufs", "spectrum", "clipping", "dynamics", "lowband"):
        assert stage in high["t_stage"]
    json.dumps(high)

    rb = lma.measure_track(str(wav), "rekordbox")
    assert rb["depth"] == "rekordbox"
    for absent in ("lufs", "mood", "spectrum", "clipping", "dynamics", "lowband", "fingerprint"):
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
