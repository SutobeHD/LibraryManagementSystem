"""USB MYSETTING / DJMMYSETTING file read/write + schema for frontend.

These tiny binary files (148–160 bytes) live in `<USB>/PIONEER/` and tell
CDJs / DJMs how the user wants their hardware to behave when this stick is
inserted (auto-cue level, jog mode, fader curve, mic low-cut, …).

Pioneer's hardware reads these on insert; without them the deck reverts to
its own local defaults — not strictly required for stick recognition, but
strongly required for a "feels like home" CDJ experience.

Files written:
  PIONEER/MYSETTING.DAT     — main DJ settings (CDJ player)
  PIONEER/MYSETTING2.DAT    — extended settings (CDJ player)
  PIONEER/DJMMYSETTING.DAT  — DJM mixer settings
  PIONEER/DEVSETTING.DAT    — device settings (rarely customised)

Read/write via `pyrekordbox.MySettingFile` & friends. We expose a
JSON-serializable schema so the frontend can render labelled dropdowns
without hardcoding the enum tables.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from pyrekordbox import (
        MySettingFile,
        MySetting2File,
        DjmMySettingFile,
        DevSettingFile,
    )
    from pyrekordbox.mysettings import structs as _ms_structs
    _PYRB_AVAILABLE = True
except Exception as exc:
    logger.warning("pyrekordbox unavailable for MYSETTING I/O: %s", exc)
    MySettingFile = MySetting2File = DjmMySettingFile = DevSettingFile = None
    _ms_structs = None
    _PYRB_AVAILABLE = False


# ──────────────────────────────────────────────────────────────────────────────
# Schema definitions
#
# Shape: file_id → list of fields. Each field:
#   {
#     "key":     str — pyrekordbox key
#     "label":   str — human-readable in the UI
#     "options": [{"value": str, "label": str}]  — for the dropdown
#     "default": str — pyrekordbox default
#     "group":   str — UI grouping (Player / Display / Quantize / Mixer / FX / …)
#     "help":    str — one-sentence tooltip
#   }
#
# We translate pyrekordbox snake_case enum members into "pretty" labels for
# the dropdown UI. The internal value sent back to /POST stays snake_case.
# ──────────────────────────────────────────────────────────────────────────────


def _humanize(value: str) -> str:
    """`'minus_18db'` → `'-18 dB'`, `'fast_cut'` → `'Fast Cut'`."""
    # Early-return for dB values so .title() doesn't downcase the B
    m = re.match(r"^minus_(\d+)db$", value)
    if m:
        return f"-{m.group(1)} dB"
    # Numeric words read better as digits in the dropdown
    word_to_digit = {
        "one": "1", "two": "2", "three": "3", "four": "4", "five": "5",
        "six": "6", "seven": "7", "eight": "8", "nine": "9", "ten": "10",
        "eleven": "11", "twelve": "12", "thirteen": "13", "fourteen": "14",
        "fifteen": "15", "sixteen": "16", "thirtytwo": "32", "sixtyfour": "64",
    }
    if value in word_to_digit:
        return word_to_digit[value]
    if value == "half":
        return "1/2"
    if value == "quarter":
        return "1/4"
    if value == "eighth":
        return "1/8"
    # Underscore → space, capitalise each word
    return value.replace("_", " ").strip().title()


def _enum_options(enum_name: str) -> List[Dict[str, str]]:
    """Pull `value → display label` pairs from pyrekordbox's construct enums."""
    if not _PYRB_AVAILABLE:
        return []
    enum_obj = getattr(_ms_structs, enum_name, None)
    if enum_obj is None:
        return []
    # construct Enum stores its mapping in `.encmapping`
    members = getattr(enum_obj, "encmapping", None) or {}
    out: List[Dict[str, str]] = []
    for name in members.keys():
        # Python identifier suffix `_` is used to avoid keyword collisions
        clean = name.rstrip("_")
        out.append({"value": clean, "label": _humanize(clean)})
    return out


# Full schema — each entry maps a pyrekordbox file → its editable fields.
SCHEMA: Dict[str, List[Dict[str, Any]]] = {
    "MYSETTING": [
        # Auto-Cue + Memory
        {"key": "auto_cue",            "label": "Auto Cue",            "enum": "AutoCue",            "group": "Auto Cue",  "help": "Automatically place a cue point at the first audible peak."},
        {"key": "auto_cue_level",      "label": "Auto Cue Level",      "enum": "AutoCueLevel",       "group": "Auto Cue",  "help": "Threshold level for auto-cue detection."},
        {"key": "hotcue_autoload",     "label": "Hot Cue Auto-Load",   "enum": "HotCueAutoLoad",     "group": "Cues",      "help": "Whether to auto-load saved hot cues when the track loads."},
        {"key": "hotcue_color",        "label": "Hot Cue Colour",      "enum": "HotCueColor",        "group": "Cues",      "help": "Colour-code hot cue buttons."},
        # Quantize
        {"key": "quantize",            "label": "Quantize",            "enum": "Quantize",           "group": "Quantize",  "help": "Snap cues, loops and beat jumps to the beatgrid."},
        {"key": "quantize_beat_value", "label": "Quantize Beat Value", "enum": "QuantizeBeatValue",  "group": "Quantize",  "help": "Resolution at which quantize snaps."},
        # Tempo / Sync
        {"key": "tempo_range",         "label": "Tempo Range",         "enum": "TempoRange",         "group": "Tempo",     "help": "Pitch fader range."},
        {"key": "master_tempo",        "label": "Master Tempo",        "enum": "MasterTempo",        "group": "Tempo",     "help": "Lock pitch when changing tempo."},
        {"key": "sync",                "label": "Sync",                "enum": "Sync",               "group": "Tempo",     "help": "Tempo / phase sync to the master deck."},
        # Display
        {"key": "language",            "label": "Language",            "enum": "Language",           "group": "Display",   "help": "On-deck UI language."},
        {"key": "lcd_brightness",      "label": "LCD Brightness",      "enum": "LCDBrightness",      "group": "Display",   "help": "Brightness level of the player LCD."},
        {"key": "phase_meter",         "label": "Phase Meter",         "enum": "PhaseMeter",         "group": "Display",   "help": "Style of the on-deck phase meter."},
        {"key": "time_mode",           "label": "Time Display",        "enum": "TimeMode",           "group": "Display",   "help": "Show elapsed or remaining time."},
        {"key": "on_air_display",      "label": "On Air Display",      "enum": "OnAirDisplay",       "group": "Display",   "help": "Highlight the active deck."},
        {"key": "slip_flashing",       "label": "Slip Flashing",       "enum": "SlipFlashing",       "group": "Display",   "help": "Flash the slip indicator while engaged."},
        # Jog
        {"key": "jog_mode",            "label": "Jog Mode",            "enum": "JogMode",            "group": "Jog",       "help": "Vinyl scratch behaviour vs. CDJ resume-from-pause."},
        {"key": "jog_ring_brightness", "label": "Jog Ring Brightness", "enum": "JogRingBrightness",  "group": "Jog",       "help": "Brightness of the jog wheel ring LEDs."},
        {"key": "jog_ring_indicator",  "label": "Jog Ring Indicator",  "enum": "JogRingIndicator",   "group": "Jog",       "help": "Show the rotation indicator on the jog ring."},
        # Misc
        {"key": "play_mode",           "label": "Play Mode",           "enum": "PlayMode",           "group": "Playback",  "help": "Continue to the next track or stop after each."},
        {"key": "needle_lock",         "label": "Needle Lock",         "enum": "NeedleLock",         "group": "Playback",  "help": "Lock needle search during playback."},
        {"key": "eject_lock",          "label": "Eject Lock",          "enum": "EjectLock",          "group": "Playback",  "help": "Disable the eject button during playback."},
        {"key": "disc_slot_illumination", "label": "Disc Slot Illumination", "enum": "DiscSlotIllumination", "group": "Display", "help": "Illumination of the disc slot."},
    ],
    "MYSETTING2": [
        {"key": "vinyl_speed_adjust",   "label": "Vinyl Speed Adjust",   "enum": "VinylSpeedAdjust",   "group": "Vinyl",  "help": "When to apply the vinyl-mode speed brake."},
        {"key": "jog_display_mode",     "label": "Jog Display Mode",     "enum": "JogDisplayMode",     "group": "Display","help": "Information shown on the jog wheel display."},
        {"key": "pad_button_brightness","label": "Pad Button Brightness","enum": "PadButtonBrightness","group": "Display","help": "Brightness of the performance pads."},
        {"key": "jog_lcd_brightness",   "label": "Jog LCD Brightness",   "enum": "JogLCDBrightness",   "group": "Display","help": "Brightness of the jog wheel LCD."},
        {"key": "waveform_divisions",   "label": "Waveform Divisions",   "enum": "WaveformDivisions",  "group": "Display","help": "Time-scale or phrase-marker overlay on the waveform."},
        {"key": "waveform",             "label": "Waveform Display",     "enum": "Waveform",           "group": "Display","help": "Show waveform or phase meter."},
        {"key": "beat_jump_beat_value", "label": "Beat Jump Value",      "enum": "BeatJumpBeatValue",  "group": "Quantize","help": "How many beats one Beat Jump press jumps."},
    ],
    "DJMMYSETTING": [
        # Faders
        {"key": "channel_fader_curve",      "label": "Channel Fader Curve",       "enum": "ChannelFaderCurve",      "group": "Faders", "help": "Response curve of the per-channel fader."},
        {"key": "channel_fader_curve_long", "label": "Channel Fader Curve (Long)","enum": "ChannelFaderCurveLong",  "group": "Faders", "help": "Curve for long-throw channel faders on flagship DJMs."},
        {"key": "cross_fader_curve",        "label": "Crossfader Curve",          "enum": "CrossfaderCurve",        "group": "Faders", "help": "Response curve of the crossfader."},
        # Headphones
        {"key": "headphones_pre_eq",     "label": "Headphones Pre EQ",     "enum": "HeadphonesPreEQ",        "group": "Headphones", "help": "Whether headphone cue picks up the signal pre or post EQ."},
        {"key": "headphones_mono_split", "label": "Headphones Mono Split", "enum": "HeadphonesMonoSplit",    "group": "Headphones", "help": "Split cue and master to separate L/R headphone channels."},
        # Mic
        {"key": "mic_low_cut",           "label": "Mic Low Cut",           "enum": "MicLowCut",              "group": "Mic",        "help": "High-pass filter on the mic input."},
        {"key": "talk_over_mode",        "label": "Talk-Over Mode",        "enum": "TalkOverMode",           "group": "Mic",        "help": "How aggressively talk-over ducks the music."},
        {"key": "talk_over_level",       "label": "Talk-Over Level",       "enum": "TalkOverLevel",          "group": "Mic",        "help": "Amount of attenuation applied during talk-over."},
        # FX / MIDI
        {"key": "beat_fx_quantize",      "label": "Beat FX Quantize",      "enum": "BeatFXQuantize",         "group": "FX",         "help": "Snap Beat FX engagement to the beatgrid."},
        {"key": "midi_channel",          "label": "MIDI Channel",          "enum": "MidiChannel",            "group": "MIDI",       "help": "Outgoing MIDI channel for performance data."},
        {"key": "midi_button_type",      "label": "MIDI Button Type",      "enum": "MidiButtonType",         "group": "MIDI",       "help": "Toggle vs. trigger behaviour for MIDI buttons."},
        # Display
        {"key": "display_brightness",    "label": "Display Brightness",    "enum": "MixerDisplayBrightness", "group": "Display",    "help": "Brightness of the mixer display."},
        {"key": "indicator_brightness",  "label": "Indicator Brightness",  "enum": "MixerIndicatorBrightness","group": "Display",    "help": "Brightness of LED indicators."},
    ],
}


def get_schema() -> Dict[str, Any]:
    """Return the full editable-field schema, plus the current default value
    of each field (so the frontend can show the deck's factory default)."""
    if not _PYRB_AVAILABLE:
        return {"available": False, "error": "pyrekordbox not installed"}

    file_classes = {
        "MYSETTING":     MySettingFile,
        "MYSETTING2":    MySetting2File,
        "DJMMYSETTING":  DjmMySettingFile,
    }
    out: Dict[str, Any] = {"available": True, "files": {}}
    for file_id, fields in SCHEMA.items():
        cls = file_classes[file_id]
        defaults_inst = cls()
        out_fields = []
        for f in fields:
            options = _enum_options(f["enum"])
            default_raw = defaults_inst.get(f["key"])
            default_value = str(default_raw) if default_raw is not None else None
            out_fields.append({
                **{k: v for k, v in f.items() if k != "enum"},
                "options": options,
                "default": default_value,
            })
        out["files"][file_id] = {
            "filename": _file_filename(file_id),
            "fields": out_fields,
        }
    return out


def _file_filename(file_id: str) -> str:
    return {
        "MYSETTING":    "MYSETTING.DAT",
        "MYSETTING2":   "MYSETTING2.DAT",
        "DJMMYSETTING": "DJMMYSETTING.DAT",
        "DEVSETTING":   "DEVSETTING.DAT",
    }[file_id]


def _file_class(file_id: str):
    return {
        "MYSETTING":    MySettingFile,
        "MYSETTING2":   MySetting2File,
        "DJMMYSETTING": DjmMySettingFile,
        "DEVSETTING":   DevSettingFile,
    }[file_id]


def read_settings(usb_root: Path) -> Dict[str, Dict[str, str]]:
    """Read all four MYSETTING files from a stick (use defaults where missing).

    Returns: {file_id: {field_key: enum_value_str, …}, …}
    """
    if not _PYRB_AVAILABLE:
        return {}

    pioneer = Path(usb_root) / "PIONEER"
    out: Dict[str, Dict[str, str]] = {}
    for file_id in ("MYSETTING", "MYSETTING2", "DJMMYSETTING"):
        cls = _file_class(file_id)
        path = pioneer / _file_filename(file_id)
        try:
            inst = cls.parse_file(str(path)) if path.exists() else cls()
        except Exception as exc:
            logger.warning("[mysettings] read %s failed (%s) — using defaults", path, exc)
            inst = cls()
        out[file_id] = {f["key"]: str(inst.get(f["key"])) for f in SCHEMA[file_id]}
    return out


def write_settings(
    usb_root: Path,
    values: Dict[str, Dict[str, str]],
    *,
    only_create_missing: bool = False,
) -> Dict[str, str]:
    """Write MYSETTING files to <USB>/PIONEER/. Returns {file_id: written_path}.

    `values` shape: {"MYSETTING": {"auto_cue": "off", …}, "MYSETTING2": {…}, …}.
    Unknown file_ids / fields are silently skipped (forward-compat).
    Missing file_ids fall back to defaults.

    `only_create_missing=True` skips files that already exist on the stick —
    used by the sync engine so we don't clobber a user's hand-edited stick.
    """
    if not _PYRB_AVAILABLE:
        logger.warning("[mysettings] pyrekordbox unavailable — skipping write")
        return {}

    pioneer = Path(usb_root) / "PIONEER"
    pioneer.mkdir(parents=True, exist_ok=True)

    written: Dict[str, str] = {}
    for file_id in ("MYSETTING", "MYSETTING2", "DJMMYSETTING"):
        target = pioneer / _file_filename(file_id)
        if only_create_missing and target.exists():
            continue

        cls = _file_class(file_id)
        # Start with file's pyrekordbox defaults (ensures no missing key crashes)
        inst = cls()

        # Overlay supplied values; ignore unknown keys, log on failure but
        # keep going (other fields shouldn't suffer from one typo).
        for key, val in (values or {}).get(file_id, {}).items():
            if val is None or val == "":
                continue
            valid = {f["key"] for f in SCHEMA[file_id]}
            if key not in valid:
                logger.debug("[mysettings] %s: ignoring unknown key %s", file_id, key)
                continue
            try:
                inst.set(key, val)
            except Exception as exc:
                logger.warning(
                    "[mysettings] %s.%s = %r rejected: %s — keeping default",
                    file_id, key, val, exc,
                )

        try:
            data = inst.build()
            target.write_bytes(data)
            written[file_id] = str(target)
            logger.info("[mysettings] wrote %s (%d B)", target, len(data))
        except Exception as exc:
            logger.error("[mysettings] build/write %s failed: %s", target, exc, exc_info=True)

    return written


def write_defaults(usb_root: Path) -> Dict[str, str]:
    """Convenience: write all-defaults MYSETTING files (used at sync time
    when the user hasn't customised anything)."""
    return write_settings(usb_root, values={}, only_create_missing=True)
