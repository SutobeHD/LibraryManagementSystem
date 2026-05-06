"""
LibraryManagementSystem -- Analysis Settings
=============================================
Centralized tunables for the analysis pipeline.

Defaults match Rekordbox conventions. Override via environment variables
prefixed with RB_ANALYSIS_ (e.g. RB_ANALYSIS_BPM_OUTPUT_MIN=70).
"""
from __future__ import annotations

import os
import logging
from dataclasses import dataclass, fields, replace as dataclass_replace
from typing import ClassVar

logger = logging.getLogger(__name__)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning(f"Invalid float for {name}: {raw!r}, using default {default}")
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning(f"Invalid int for {name}: {raw!r}, using default {default}")
        return default


@dataclass(frozen=True)
class AnalysisSettings:
    # -- BPM detection / output range -------------------------------------
    bpm_detect_min: float = 60.0       # what madmom DBN / librosa may find
    bpm_detect_max: float = 210.0
    bpm_output_min: float = 80.0       # Pioneer-style display sweet spot
    bpm_output_max: float = 180.0

    # -- Octave-disambiguation thresholds ---------------------------------
    onset_density_high_ratio: float = 5.5   # > → halve-time misread, double
    onset_density_low_ratio: float = 0.4    # < → double-time misread, halve

    # -- Key detection ----------------------------------------------------
    minor_bias: float = 1.10           # K-S fallback (1.0 = neutral)

    # -- Waveform colors --------------------------------------------------
    color_gamma: float = 0.65          # < 1 brightens mids in PWV4/5/6/7

    # -- Cue limits -------------------------------------------------------
    cue_max_hot: int = 8               # Rekordbox hot cue slots A..H
    cue_max_memory: int = 16
    memory_min_bar_spacing: int = 16

    # -- Phrase detection -------------------------------------------------
    phrase_bars: int = 8               # window length for energy/MFCC analysis
    phrase_merge_max_bars: int = 16    # don't merge once phrase already large

    # -- Dynamic tempo grid -----------------------------------------------
    tempo_change_threshold_bpm: float = 1.5
    tempo_change_min_spacing_s: float = 8.0

    # -- Loudness ---------------------------------------------------------
    replay_gain_target_lufs: float = -18.0

    # -- Sample-rate handling ---------------------------------------------
    waveform_sr_cap: int = 96000       # downsample masters above this for waveforms
    analysis_sr: int = 44100           # beat / key / phrase analysis SR

    # ---------------------------------------------------------------------
    @classmethod
    def from_env(cls) -> "AnalysisSettings":
        """Build settings, overriding fields from environment variables."""
        defaults = cls()
        kwargs = {}
        for f in fields(cls):
            env_name = f"RB_ANALYSIS_{f.name.upper()}"
            if env_name not in os.environ:
                continue
            if f.type == "float" or f.default.__class__ is float:
                kwargs[f.name] = _env_float(env_name, getattr(defaults, f.name))
            elif f.type == "int" or f.default.__class__ is int:
                kwargs[f.name] = _env_int(env_name, getattr(defaults, f.name))
        return dataclass_replace(defaults, **kwargs) if kwargs else defaults


# Module-level singleton (re-loadable for tests)
_settings: AnalysisSettings = AnalysisSettings.from_env()


def get_settings() -> AnalysisSettings:
    return _settings


def reload_settings() -> AnalysisSettings:
    """Re-read environment and rebuild settings (for tests / config UIs)."""
    global _settings
    _settings = AnalysisSettings.from_env()
    return _settings
