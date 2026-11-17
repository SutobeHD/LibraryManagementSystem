"""run_full_analysis depth switch ("rekordbox" | "high").

The heavy DSP functions are stubbed on the engine module; only librosa's WAV
load runs for real (a 2 s stereo file written per test). Covers: which blocks
run at which depth, the extras contract, the depth-aware cache, and the
cue-toggle refresh on a cache hit (handover B10).
"""

from __future__ import annotations

import logging
import os
import struct
import sys
import types
import wave
from typing import Any

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.analysis_cache import AnalysisCache  # noqa: E402

ae = pytest.importorskip("app.analysis_engine")
if not ae._ensure_libs():  # pragma: no cover - librosa missing
    pytest.skip("librosa not available", allow_module_level=True)


_BEATS = [{"time_ms": i * 468.75, "beat_number": i % 4 + 1, "tempo": 12800} for i in range(8)]
_PHRASES = [{"label": "Intro", "start_time": 0.0, "end_time": 1.0, "mood": "low"}]
_MOOD = {"mood": "Energetic", "brightness": 0.5, "warmth": 0.4, "texture": 0.3}
_EXTRAS = {"e1_cutoff_hz": 19800.0, "e2_clipping": 0}


def _write_stereo_wav(path: str, seconds: float = 2.0, sr: int = 44100) -> None:
    import math

    n = int(seconds * sr)
    frames = bytearray()
    for i in range(n):
        v = int(12000 * math.sin(2 * math.pi * 220 * i / sr))
        frames += struct.pack("<hh", v, v // 2)
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(bytes(frames))


class _Calls:
    def __init__(self) -> None:
        self.names: list[str] = []
        self.extras_kwargs: list[dict[str, Any]] = []
        self.extras_args: list[tuple] = []


@pytest.fixture
def calls(monkeypatch, tmp_path):
    rec = _Calls()

    def mark(name, value):
        def _f(*a, **k):
            rec.names.append(name)
            return value

        return _f

    beat_result = {
        "bpm": 128.0,
        "bpm_raw": 128.0,
        "beats": _BEATS,
        "beat_count": len(_BEATS),
        "downbeat_index": 0,
        "method": "stub",
        "grid_confidence": 0.9,
    }
    key_result = {
        "key": "Am",
        "camelot": "8A",
        "openkey": "1m",
        "key_id": 22,
        "confidence": 0.8,
        "method": "stub",
    }
    monkeypatch.setattr(ae, "get_encoder_delay", mark("delay", 0.0))
    monkeypatch.setattr(ae, "find_first_signal_onset", mark("onset", 0.25))
    monkeypatch.setattr(ae, "detect_beats", mark("beats", beat_result))
    monkeypatch.setattr(ae, "detect_key", mark("key", key_result))
    monkeypatch.setattr(ae, "generate_waveform_data", mark("waveform", {"pwav": []}))
    monkeypatch.setattr(ae, "detect_phrases", mark("phrases", _PHRASES))
    monkeypatch.setattr(ae, "detect_tempo_changes", mark("tempo_grid", []))
    monkeypatch.setattr(ae, "generate_pvbr", mark("pvbr", [0] * 400))
    monkeypatch.setattr(ae, "calculate_lufs", mark("lufs", -9.5))
    monkeypatch.setattr(ae, "calculate_replay_gain", mark("replay_gain", -8.5))
    monkeypatch.setattr(ae, "detect_mood", mark("mood", dict(_MOOD)))
    monkeypatch.setattr(ae, "hint_genre", mark("genre", "Techno"))
    monkeypatch.setattr(ae, "compute_stereo_features", mark("stereo", {"width": 0.3}))
    monkeypatch.setattr(ae, "generate_hot_cues", mark("hot", [{"name": "hot"}]))
    monkeypatch.setattr(ae, "generate_memory_cues", mark("mem", [{"name": "mem"}]))
    monkeypatch.setattr(ae, "generate_grid_memory_cues", mark("grid", [{"name": "grid"}]))

    def compute_extras(y_native, sr_native, y, sr, **kw):
        rec.names.append("extras")
        rec.extras_args.append((y_native, sr_native, y, sr))
        rec.extras_kwargs.append(kw)
        return dict(_EXTRAS)

    mod = types.ModuleType("app.analysis_extras")
    mod.compute_extras = compute_extras  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.analysis_extras", mod)
    monkeypatch.setattr(ae, "_EXTRAS_IMPORT_WARNED", False)

    from app import analysis_cache

    monkeypatch.setattr(analysis_cache, "_default_cache", AnalysisCache(str(tmp_path / "cache")))
    return rec


@pytest.fixture
def wav(tmp_path) -> str:
    p = str(tmp_path / "stereo.wav")
    _write_stereo_wav(p)
    return p


def _run(path: str, **kw) -> dict[str, Any]:
    stages: list[str] = []
    kw.setdefault("progress_callback", lambda stage, pct: stages.append(stage))
    result = ae.run_full_analysis(path, **kw)
    result["_stages"] = stages
    return result


# --- depth split -------------------------------------------------------------


def test_rekordbox_depth_skips_mood_stereo_genre_and_extras(calls, wav):
    r = _run(wav, use_cache=False, depth="rekordbox")

    assert r["status"] == "ok"
    assert r["depth"] == "rekordbox"
    assert r["lufs"] == -9.5 and r["replay_gain"] == -8.5  # B7: lufs stays
    assert r["peak"] > 0.0  # B6: peak stays
    assert r["stereo"] is None
    assert r["mood"] is None
    assert r["genre_hint"] is None
    assert r["extras"] is None
    assert r["channels"] == 2
    for never in ("mood", "genre", "stereo", "extras"):
        assert never not in calls.names
    assert "mood" not in r["_stages"] and "extras" not in r["_stages"]
    for always in (
        "beats",
        "key",
        "waveform",
        "phrases",
        "tempo_grid",
        "pvbr",
        "lufs",
        "hot",
        "mem",
    ):
        assert always in calls.names


def test_default_depth_is_rekordbox(calls, wav):
    r = _run(wav, use_cache=False)
    assert r["depth"] == "rekordbox"
    assert r["mood"] is None


def test_high_depth_runs_everything_and_calls_extras_with_the_contract(calls, wav):
    r = _run(wav, use_cache=False, depth="high")

    assert r["status"] == "ok"
    assert r["depth"] == "high"
    assert r["stereo"] == {"width": 0.3}
    assert r["mood"] == _MOOD
    assert r["genre_hint"] == "Techno"
    assert r["extras"] == _EXTRAS
    assert r["lufs"] == -9.5 and r["peak"] > 0.0
    assert "mood" in r["_stages"] and "extras" in r["_stages"]
    assert calls.names.count("extras") == 1

    y_native, sr_native, y, sr = calls.extras_args[0]
    assert y_native.ndim == 2 and y_native.shape[0] == 2
    assert sr_native == 44100
    assert y.ndim == 1 and sr == 44100
    kw = calls.extras_kwargs[0]
    assert kw == {
        "lufs": -9.5,
        "first_signal_ms": 250.0,
        "file_path": wav,
        "sample_rate_meta": 44100,
    }


def test_missing_extras_module_yields_none_and_warns_once(calls, wav, monkeypatch, caplog):
    monkeypatch.setitem(sys.modules, "app.analysis_extras", None)  # import -> ModuleNotFoundError

    with caplog.at_level(logging.WARNING, logger="app.analysis_engine"):
        r1 = _run(wav, use_cache=False, depth="high")
        r2 = _run(wav, use_cache=False, depth="high")

    assert r1["status"] == "ok" and r2["status"] == "ok"
    assert r1["extras"] is None and r2["extras"] is None
    assert r1["mood"] == _MOOD  # the rest of the high level still ran
    warnings = [m for m in caplog.messages if "analysis_extras" in m]
    assert len(warnings) == 1


def test_extras_runtime_failure_does_not_fail_the_analysis(calls, wav, monkeypatch, caplog):
    def boom(*a, **k):
        raise RuntimeError("fpcalc exploded")

    sys.modules["app.analysis_extras"].compute_extras = boom  # type: ignore[attr-defined]
    with caplog.at_level(logging.WARNING, logger="app.analysis_engine"):
        r = _run(wav, use_cache=False, depth="high")
    assert r["status"] == "ok"
    assert r["extras"] is None
    assert any("fpcalc exploded" in m for m in caplog.messages)


def test_unknown_depth_raises_before_any_work(calls, wav):
    with pytest.raises(ValueError):
        ae.run_full_analysis(wav, depth="fast")
    with pytest.raises(ValueError):
        ae.run_full_analysis(wav, depth="")
    assert calls.names == []


# --- cache ---------------------------------------------------------------------


def test_cache_hit_recomputes_cues_with_the_current_toggles(calls, wav):
    """B10: the cached cue lists belong to the toggles of the run that produced them."""
    first = _run(wav, auto_hot_cues=True, auto_memory_cues=True, memory_cue_grid=False)
    assert first["cache_hit"] is False
    assert first["hot_cues"] == [{"name": "hot"}]
    assert first["memory_cues"] == [{"name": "mem"}]

    second = _run(wav, auto_hot_cues=False, auto_memory_cues=True, memory_cue_grid=True)
    assert second["cache_hit"] is True
    assert second["hot_cues"] == []
    assert second["memory_cues"] == [{"name": "grid"}]
    assert second["_stages"] == ["cache_hit"]
    assert calls.names.count("beats") == 1  # no re-analysis


def test_rekordbox_cache_entry_does_not_answer_a_high_request(calls, wav):
    rb = _run(wav, depth="rekordbox")
    assert rb["cache_hit"] is False and rb["extras"] is None

    high = _run(wav, depth="high")
    assert high["cache_hit"] is False
    assert high["depth"] == "high"
    assert high["extras"] == _EXTRAS
    assert calls.names.count("beats") == 2

    again_rb = _run(wav, depth="rekordbox")  # the high entry is a superset -> hit
    assert again_rb["cache_hit"] is True
    assert again_rb["depth"] == "high"
    assert again_rb["extras"] == _EXTRAS
    assert calls.names.count("beats") == 2


def test_cache_stores_the_depth(calls, wav, tmp_path):
    _run(wav, depth="high")
    from app.analysis_cache import get_default_cache

    entry = get_default_cache()._index[os.path.abspath(wav)]
    assert entry["depth"] == "high"
    assert entry["version"] == 4


# --- AnalysisEngine wrappers ---------------------------------------------------


class _RecordingExecutor:
    def __init__(self) -> None:
        self.submitted: list[tuple] = []

    def submit(self, fn, *args, **kwargs):
        from concurrent.futures import Future

        self.submitted.append((fn, args, kwargs))
        fut: Future = Future()
        fut.set_result({"ok": True})
        return fut


def test_submit_appends_depth_as_the_last_positional_argument(monkeypatch):
    ex = _RecordingExecutor()
    monkeypatch.setattr(ae.AnalysisEngine, "get_executor", classmethod(lambda cls: ex))
    monkeypatch.setattr(ae.AnalysisEngine, "_tasks", {})

    ae.AnalysisEngine.submit("t", "x.mp3", auto_hot_cues=False, depth="high")

    assert ex.submitted == [
        (ae.run_full_analysis, ("x.mp3", None, True, None, False, None, None, "high"), {})
    ]


def test_analyze_sync_forwards_depth(monkeypatch):
    seen: list[tuple] = []
    monkeypatch.setattr(
        ae, "run_full_analysis", lambda p, cap=None, **kw: seen.append((p, cap, kw)) or {}
    )
    ae.AnalysisEngine.analyze_sync("x.mp3", depth="high")
    ae.AnalysisEngine.analyze_sync("y.mp3")
    assert seen == [("x.mp3", None, {"depth": "high"}), ("y.mp3", None, {"depth": "rekordbox"})]
