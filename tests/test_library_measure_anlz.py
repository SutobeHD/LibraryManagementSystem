"""Tests for scripts/library_measure_anlz.py on synthetic ANLZ bytes. No user files involved."""

from __future__ import annotations

import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import library_measure_anlz as lma  # noqa: E402

# --------------------------------------------------------------------------- tag builders
# Layouts follow pyrekordbox 0.1.7 anlz/structs.py (the parser under test).


def _pmai(tags: list[bytes]) -> bytes:
    body = b"".join(tags)
    return struct.pack(">4sIIIIII", b"PMAI", 28, 28 + len(body), 1, 0x10000, 0x10000, 0) + body


def _pssi(mood: int, phrases: list[tuple[int, int]], end_beat: int, bank: int = 0) -> bytes:
    total = 32 + 24 * len(phrases)
    buf = struct.pack(">4sIII", b"PSSI", 32, total, 24)
    buf += struct.pack(">HH", len(phrases), mood) + b"\x00" * 6
    buf += struct.pack(">HH", end_beat, 1) + bytes([bank, 0])
    for i, (beat, kind) in enumerate(phrases, 1):
        k1 = 1 if (mood == 1 and kind == 5) else 0
        buf += struct.pack(">HHHBBBBBB", i, beat, kind, 0, k1, 0, 0, 0, 0)
        buf += struct.pack(">HHHBBBBH", 0, 0, 0, 0, 0, 0, 0, 0)
    assert len(buf) == total
    return buf


def _pqtz(entries: list[tuple[int, float, int]]) -> bytes:
    buf = struct.pack(">4sIIII", b"PQTZ", 24, 24 + 8 * len(entries), 0, 0x80000)
    buf += struct.pack(">I", len(entries))
    for beat, bpm, ms in entries:
        buf += struct.pack(">HHI", beat, round(bpm * 100), ms)
    return buf


def _pqt2(n_beats: int, bpm: float, u3: int, flags: int = 0x01000002) -> bytes:
    buf = struct.pack(">4sII", b"PQT2", 56, 56 + 2 * n_beats)
    buf += struct.pack(">III", 0, flags, 0)
    buf += struct.pack(">HHI", 1, round(bpm * 100), 0)
    buf += struct.pack(">HHI", 1, round(bpm * 100), 1000 * n_beats)
    buf += struct.pack(">IIII", n_beats, u3, 0, 0)
    buf += bytes([(i % 4) + 1, 0][j] for i in range(n_beats) for j in range(2))
    return buf


def _ppth(path: str) -> bytes:
    data = path.encode("utf-16-be") + b"\x00\x00"
    return struct.pack(">4sIII", b"PPTH", 16, 16 + len(data), len(data)) + data


def _pcpt(hot_cue: int, time_ms: int, loop_ms: int | None, u1: int = 0x10000) -> bytes:
    kind = 2 if loop_ms is not None else 1
    buf = struct.pack(">4sIIII", b"PCPT", 0x1C, 0x38, hot_cue, 4)
    buf += struct.pack(">IHHBBH", u1, 0xFFFF, 0xFFFF, kind, 0, 1000)
    buf += struct.pack(">Ii", time_ms, loop_ms if loop_ms is not None else -1)
    buf += b"\x00" * 16
    assert len(buf) == 0x38
    return buf


def _pcob(cue_type: int, cues: list[tuple[int, int, int | None]], u1: int = 0x10000) -> bytes:
    entries = b"".join(_pcpt(*c, u1=u1) for c in cues)
    buf = struct.pack(">4sII", b"PCOB", 24, 24 + len(entries))
    buf += struct.pack(">IHHi", cue_type, 0, len(cues), -1)
    return buf + entries


def _pcp2(hot_cue: int, time_ms: int, color_id: int, comment: str) -> bytes:
    comment_bytes = comment.encode("utf-16-be")
    len_entry = 48 + len(comment_bytes)
    buf = struct.pack(">4sIII", b"PCP2", 16, len_entry, hot_cue)
    buf += struct.pack(">B3xIi", 1, time_ms, -1)
    buf += struct.pack(">B7xHHI", color_id, 0, 0, len(comment_bytes)) + comment_bytes
    buf += bytes([0, 0, 0, 0])
    assert len(buf) == len_entry
    return buf


def _pco2(cue_type: int, cues: list[tuple[int, int, int, str]]) -> bytes:
    entries = b"".join(_pcp2(*c) for c in cues)
    buf = struct.pack(">4sII", b"PCO2", 20, 20 + len(entries))
    buf += struct.pack(">IHH", cue_type, len(cues), 0)
    return buf + entries


def _pwv6(frames: list[tuple[int, int, int]]) -> bytes:
    payload = bytes(v for f in frames for v in f)
    return struct.pack(">4sIIII", b"PWV6", 20, 20 + len(payload), 3, len(frames)) + payload


def _pwv7(frames: list[tuple[int, int, int]]) -> bytes:
    payload = bytes(v for f in frames for v in f)
    head = struct.pack(">4sIIIII", b"PWV7", 24, 24 + len(payload), 3, len(frames), 0x960000)
    return head + payload


def _pwv5(entries: list[int]) -> bytes:
    payload = b"".join(struct.pack(">H", e) for e in entries)
    return struct.pack(">4sIIIII", b"PWV5", 24, 24 + len(payload), 2, len(entries), 0) + payload


def _pwvc(values: tuple[int, int, int]) -> bytes:
    return struct.pack(">4sIIHHHH", b"PWVC", 14, 20, 0, *values)


HIGH_PHRASES = [(1, 1), (33, 5), (65, 3), (97, 2), (129, 5), (161, 6)]


# --------------------------------------------------------------------------- PSSI mask


def test_mask_roundtrip_and_detection():
    plain = _pssi(1, HIGH_PHRASES, 193)
    assert lma.pssi_is_plain(plain) and not lma.pssi_is_masked(plain)

    masked = lma.mask_pssi(plain)
    assert masked != plain
    assert masked[:0x12] == plain[:0x12], "bytes before the mood field are never masked"
    assert lma.pssi_is_masked(masked) and not lma.pssi_is_plain(masked)

    assert lma.unmask_pssi(masked) == plain
    assert lma.unmask_pssi(plain) == plain, "a plain tag is left alone"
    assert lma.mask_pssi(masked) == masked, "a masked tag is never masked twice"


def test_mask_key_depends_on_entry_count():
    a = lma.mask_pssi(_pssi(2, [(1, 1), (33, 9)], 65))
    b = lma.mask_pssi(_pssi(2, [(1, 1), (33, 9), (65, 10)], 97))
    assert a[0x12:0x14] != b[0x12:0x14], "same mood, different len_entries -> different mask"


def test_short_tag_is_neither_plain_nor_masked():
    assert not lma.pssi_is_plain(b"PSSI\x00\x00\x00\x20")
    assert not lma.pssi_is_masked(b"PSSI\x00\x00\x00\x20")
    assert lma.unmask_pssi(b"PSSI") == b"PSSI"


# --------------------------------------------------------------------------- load / parse


def _ext_blob(masked: bool) -> bytes:
    pssi = _pssi(1, HIGH_PHRASES, 193)
    if masked:
        pssi = lma.mask_pssi(pssi)
    return _pmai([_ppth("?/track.aiff"), _pqtz([(1, 140.0, 20), (2, 140.0, 448)]), pssi])


def test_unmask_anlz_bytes_splices_only_pssi():
    plain_blob = _ext_blob(masked=False)
    masked_blob = _ext_blob(masked=True)
    assert masked_blob != plain_blob

    out, was_masked = lma.unmask_anlz_bytes(masked_blob)
    assert was_masked is True
    assert out == plain_blob
    assert len(out) == len(masked_blob)

    out2, was_masked2 = lma.unmask_anlz_bytes(plain_blob)
    assert was_masked2 is False and out2 == plain_blob

    no_pssi = _pmai([_ppth("x.mp3")])
    assert lma.unmask_anlz_bytes(no_pssi) == (no_pssi, None)


def test_parse_anlz_reads_masked_pssi_as_plain():
    anlz, masked, tag_errors = lma.parse_anlz(_ext_blob(masked=True))
    assert masked is True and tag_errors == {}
    assert anlz.tag_types == ["PPTH", "PQTZ", "PSSI"]
    pssi = anlz.get_tag("PSSI").content
    assert int.from_bytes(bytes(pssi.mood), "big") == 1
    assert [(e.beat, e.kind) for e in pssi.entries] == HIGH_PHRASES
    assert int.from_bytes(bytes(pssi.end_beat), "big") == 193
    assert anlz.get_tag("PPTH").content.path == "?/track.aiff"


def test_load_anlz_reads_file_without_touching_it(tmp_path: Path):
    p = tmp_path / "ANLZ0000.EXT"
    blob = _ext_blob(masked=True)
    p.write_bytes(blob)
    before = p.stat().st_mtime_ns

    anlz = lma.load_anlz(p)

    assert anlz.tag_types == ["PPTH", "PQTZ", "PSSI"]
    assert p.read_bytes() == blob and p.stat().st_mtime_ns == before


# --------------------------------------------------------------------------- grid


def test_distinct_tempos_and_switches():
    assert lma.distinct_tempos([140.0, 140.01, 140.04, 150.0]) == [140.0, 150.0]
    assert lma.distinct_tempos([]) == []
    assert lma.tempo_switches([140.0, 140.0, 140.0]) == 0
    assert lma.tempo_switches([140.0, 150.0, 140.0]) == 2
    assert lma.tempo_switches([140.0, 140.03, 140.0]) == 0, "within tolerance"


def test_grid_summary():
    entries = [(1, 140.0, 20), (2, 140.0, 448), (3, 140.0, 877), (4, 140.0, 1305)]
    entries += [(1, 150.0, 1734), (2, 150.0, 2134), (3, 150.0, 2534), (4, 150.0, 2934)]
    g = lma.grid_summary(entries)
    assert g["present"] and g["beats"] == 8 and g["bars"] == 2
    assert g["first_downbeat_ms"] == 20 and g["last_beat_ms"] == 2934
    assert g["tempo_distinct"] == 2 and g["tempo_changes"] == 1 and g["tempo_switches"] == 1
    assert g["bpm_min"] == 140.0 and g["bpm_max"] == 150.0
    assert lma.grid_summary([]) == {"present": False}


def test_grid_summary_first_downbeat_can_be_later_than_first_beat():
    g = lma.grid_summary([(3, 128.0, 10), (4, 128.0, 478), (1, 128.0, 947)])
    assert g["first_beat_ms"] == 10 and g["first_downbeat_ms"] == 947 and g["bars"] == 1


# --------------------------------------------------------------------------- phrases


def test_phrase_summary_high_mood():
    p = lma.phrase_summary(1, HIGH_PHRASES, 193)
    assert p["mood"] == "high" and p["count"] == 6
    assert p["kinds"] == "1,5,3,2,5,6"
    assert p["labels"] == "Intro,Chorus,Down,Up,Chorus,Outro"
    assert p["intro_bars"] == 8 and p["outro_bars"] == 8
    assert p["chorus_count"] == 2 and p["end_beat"] == 193 and p["bars"] == 48.25
    assert p["min_phrase_bars"] == 8 and p["max_phrase_bars"] == 8


def test_phrase_summary_runs_and_trailing_outros():
    phrases = [(1, 1), (17, 1), (33, 9), (49, 9), (65, 9), (81, 10), (97, 10)]
    p = lma.phrase_summary(2, phrases, 129)
    assert p["labels"] == "Intro*2,Chorus*3,Outro*2"
    assert p["intro_bars"] == 8 and p["outro_bars"] == 12 and p["chorus_count"] == 3


def test_phrase_labels_per_mood():
    assert lma.phrase_label(2, 2) == "Verse1" and lma.phrase_label(2, 8) == "Bridge"
    assert lma.phrase_label(3, 4) == "Verse1" and lma.phrase_label(3, 5) == "Verse2"
    assert lma.phrase_label(1, 4) == "?4" and lma.phrase_label(9, 1) == "?1"
    assert lma.phrase_summary(1, [], 0)["count"] == 0


# --------------------------------------------------------------------------- waveforms


def test_band_summary_low_mid_high_order():
    frames = [(40, 20, 10)] * 50 + [(80, 40, 20)] * 50
    b = lma.band_summary(bytes(v for f in frames for v in f), segments=10)
    assert b["frames"] == 100
    assert b["low"] == 60.0 and b["mid"] == 30.0 and b["high"] == 15.0
    assert b["bass_share"] == pytest.approx(60 / 105, abs=1e-3)
    assert b["brightness"] == pytest.approx(15 / 105, abs=1e-3)
    assert len(b["curve"]) == 10 and b["curve"][:5] == [0.5] * 5 and b["curve"][5:] == [1.0] * 5
    assert b["peak_pos"] == 0.5 and b["max_byte"] == 80
    assert lma.band_summary(b"") == {"present": False}


def test_color_detail_summary_bit_layout():
    # red=7 green=0 blue=0 height=31 -> 0b111_000_000_11111_00
    red = (7 << 13) | (31 << 2)
    blue = (7 << 7) | (16 << 2)
    c = lma.color_detail_summary([red, blue])
    assert c["frames"] == 2
    assert c["red"] == 3.5 and c["green"] == 0.0 and c["blue"] == 3.5
    assert c["height"] == 23.5 and c["brightness"] == 0.5


def test_color_preview_summary():
    frame = bytes([0, 100, 0, 0x7F | 0x80, 0, 10])  # d3 red 127 (high bit stripped), d5 blue 10
    c = lma.color_preview_summary(frame * 4)
    assert c["frames"] == 4 and c["red"] == 127.0 and c["green"] == 0.0 and c["blue"] == 10.0
    assert c["brightness"] == pytest.approx(10 / 137, abs=1e-3)


# --------------------------------------------------------------------------- path + writer


def test_ppth_match():
    real = r"C:\Users\x\Music\Lib\Artist - Title.aiff"
    assert lma.ppth_match("?/Artist - Title.aiff", real) == "basename"
    assert lma.ppth_match("/Users/x/Music/Lib/Artist - Title.aiff", real) == "full"
    assert lma.ppth_match("/Contents/Artist - Title.m4a", real) == "ext_mismatch"
    assert lma.ppth_match("?/Other.aiff", real) == "mismatch"
    assert lma.ppth_match("", real) == "empty" and lma.ppth_match(None, real) == "empty"
    assert lma.ppth_match("?/x.mp3", None) == "no_real_path"


def _lms_style_pssi() -> bytes:
    # app/anlz_writer.py:_build_pssi: entry_count(2) mood(2) bank(2)=0 end_beat(2) reserved(8)
    buf = struct.pack(">4sIII", b"PSSI", 32, 32 + 24, 24)
    buf += struct.pack(">HHHH", 1, 1, 0, 193) + b"\x00" * 8
    buf += b"\x00" * 24
    return buf


def test_writer_guess():
    rb = lma.writer_guess(_pssi(1, HIGH_PHRASES, 193), _pwvc((0x50, 0x6F, 0x6D)), _pqt2(4, 140, 7))
    assert rb["guess"] == "rekordbox"
    assert rb["votes"] == {"pssi": "rekordbox", "pwvc": "rekordbox", "pqt2": "rekordbox"}

    lms = lma.writer_guess(_lms_style_pssi(), _pwvc((0, 0, 0)), _pqt2(4, 140, 0))
    assert lms["guess"] == "lms"
    assert lms["votes"] == {"pssi": "lms", "pwvc": "lms", "pqt2": "lms"}

    assert lma.writer_guess(None, None, None) == {"guess": "unknown", "votes": {}}
    mixed = lma.writer_guess(_lms_style_pssi(), _pwvc((0x50, 0, 0)), None)
    assert mixed["guess"] == "conflict"


# --------------------------------------------------------------------------- per track


def _write_track(tmp_path: Path, *, masked: bool = True, with_ex2: bool = True) -> dict[str, str]:
    pssi = _pssi(1, HIGH_PHRASES, 193)
    if masked:
        pssi = lma.mask_pssi(pssi)
    grid = [(1, 140.0, 20), (2, 140.0, 448), (3, 140.0, 877), (4, 140.0, 1305), (1, 140.0, 1734)]
    hot = [(1, 20, None), (2, 1734, 3448)]
    mem = [(0, 877, None)]
    dat = _pmai(
        [_ppth("?/Artist - Title.aiff"), _pqtz(grid), _pcob(1, hot), _pcob(0, mem)],
    )
    ext = _pmai(
        [
            _ppth("?/Artist - Title.aiff"),
            _pcob(1, hot),
            _pcob(0, mem),
            _pco2(1, [(1, 20, 3, "drop"), (2, 1734, 5, "")]),
            _pco2(0, [(0, 877, 0, "")]),
            _pqt2(5, 140.0, 0x12345),
            _pwv5([(7 << 13) | (20 << 2)] * 300),
            pssi,
        ]
    )
    ex2 = _pmai(
        [
            _ppth("/Contents/Artist - Title.m4a"),
            _pwv7([(60, 30, 10)] * 300),
            _pwv6([(50, 25, 5)] * 12),
            _pwvc((0x50, 0x6F, 0x6D)),
        ]
    )
    (tmp_path / "ANLZ0000.DAT").write_bytes(dat)
    (tmp_path / "ANLZ0000.EXT").write_bytes(ext)
    if with_ex2:
        (tmp_path / "ANLZ0000.2EX").write_bytes(ex2)
    return {
        "DAT": str(tmp_path / "ANLZ0000.DAT"),
        "EXT": str(tmp_path / "ANLZ0000.EXT"),
        "EX2": str(tmp_path / "ANLZ0000.2EX"),
    }


def test_measure_track_anlz_synthetic(tmp_path: Path):
    paths = _write_track(tmp_path)
    row = lma.measure_track_anlz(paths, r"C:\Music\Artist - Title.aiff")

    assert row["status"] == "ok" and row["errors"] == {}
    assert row["files"] == {"DAT": True, "EXT": True, "EX2": True}
    assert row["tags"]["EX2"] == ["PPTH", "PWV7", "PWV6", "PWVC"]

    assert row["grid"]["beats"] == 5 and row["grid"]["bars"] == 2
    assert row["grid"]["tempo_changes"] == 0 and row["grid"]["first_downbeat_ms"] == 20
    assert row["grid2"] == {
        "present": True,
        "beats": 5,
        "anchor_bpm": [140.0, 140.0],
        "anchor_ms": [0, 5000],
        "flags": "0x01000002",
    }

    assert row["cues"]["hot"] == 2 and row["cues"]["memory"] == 1 and row["cues"]["loops"] == 1
    assert row["cues"]["colours"] == {"3": 1, "5": 1} and row["cues"]["comments"] == 1

    assert row["pssi"]["present"] and row["pssi"]["masked"] is True
    assert row["pssi"]["mood"] == "high" and row["pssi"]["kinds"] == "1,5,3,2,5,6"
    assert row["pssi"]["kind_variants"] == "000,100,000,000,100,000"

    assert row["band_detail"]["frames"] == 300 and row["band_detail"]["low"] == 60.0
    assert row["band_preview"]["frames"] == 12 and row["band_preview"]["high"] == 5.0
    assert row["color_detail"]["frames"] == 300 and row["color_detail"]["red"] == 7.0
    assert row["color_preview"] == {"present": False}

    assert row["ppth"]["dat"] == "?/Artist - Title.aiff" and row["ppth"]["dat_match"] == "basename"
    assert row["ppth"]["ex2_match"] == "ext_mismatch"
    assert row["writer"]["guess"] == "rekordbox"


def test_measure_track_anlz_plain_pssi_and_missing_ex2(tmp_path: Path):
    paths = _write_track(tmp_path, masked=False, with_ex2=False)
    row = lma.measure_track_anlz(paths, None)
    assert row["status"] == "ok"
    assert row["files"]["EX2"] is False
    assert row["pssi"]["masked"] is False
    assert row["band_detail"] == {"present": False}
    assert row["ppth"]["dat_match"] == "no_real_path" and row["ppth"]["ex2_match"] == "empty"
    assert row["writer"]["votes"] == {"pssi": "rekordbox", "pqt2": "rekordbox"}


def test_measure_track_anlz_records_parse_errors(tmp_path: Path):
    paths = _write_track(tmp_path)
    bad = bytearray(_pmai([_pqtz([(1, 140.0, 20)])]))
    bad[28 + 16 : 28 + 20] = b"\x00\x00\x00\x00"  # PQTZ u2 Const 0x80000 -> ConstError
    Path(paths["EXT"]).write_bytes(bytes(bad))
    Path(paths["EX2"]).write_bytes(b"PMAI\x00")  # too short for the file header
    row = lma.measure_track_anlz(paths, None)
    assert row["status"] == "partial"
    assert row["errors"] == {} or set(row["errors"]) == {"EX2"}
    assert (
        set(row["tag_errors"]["EXT"]) == {"PQTZ"}
        and "ConstError" in row["tag_errors"]["EXT"]["PQTZ"]
    )
    assert set(row["errors"]) == {"EX2"} and row["errors"]["EX2"]
    assert row["grid"]["beats"] == 5, "DAT still measured"
    assert row["pssi"] == {"present": False, "masked": None}

    missing = lma.measure_track_anlz({"DAT": str(tmp_path / "nope.DAT")}, None)
    assert missing["status"] == "missing"


def test_summarize_counts():
    rows = [
        {
            "status": "ok",
            "files": {"DAT": True, "EXT": True, "EX2": False},
            "errors": {},
            "tags": {"DAT": ["PPTH", "PQTZ"]},
            "grid": {"present": True, "tempo_changes": 1},
            "grid2": {"present": False},
            "pssi": {"present": True, "masked": True, "mood": "high", "count": 12},
            "writer": {"guess": "rekordbox"},
            "ppth": {"dat_match": "basename"},
            "band_detail": {"present": True, "bass_share": 0.5, "brightness": 0.1, "frames": 9},
            "color_detail": {"present": True, "frames": 9},
        },
        {"status": "error", "error": "ValueError: boom"},
    ]
    s = lma.summarize(rows)
    assert s["tracks"] == 2 and s["status"] == {"ok": 1, "error": 1}
    assert s["files_present"] == {"DAT": 1, "EXT": 1}
    assert s["errors"] == {"row:ValueError": 1}
    assert s["tempo_changed"] == 1 and s["pqt2_missing"] == 1 and s["grid_missing"] == 0
    assert s["pssi"] == {"masked": 1} and s["moods"] == {"high": 1}
    assert s["writer"] == {"rekordbox": 1, "unknown": 1}
    assert s["pwv7_frames_eq_pwv5"] == [1, 1] and s["bass_share_mean"] == 0.5


def test_tolerant_parse_keeps_other_tags():
    pssi = lma.mask_pssi(_pssi(2, [(1, 1), (33, 9), (97, 10)], 129))
    hot = [(1, 20, None), (2, 1734, 3448)]
    blob = _pmai(
        [
            _ppth("?/x.aiff"),
            _pcob(1, hot, u1=0x100000),  # Rekordbox variant pyrekordbox rejects
            _pqt2(5, 140.0, 7, flags=0x02000002),  # dito
            pssi,
        ]
    )
    anlz, masked, tag_errors = lma.parse_anlz(blob)
    assert masked is True
    assert set(tag_errors) == {"PCOB", "PQT2"}
    assert all(e.startswith("ConstError") for e in tag_errors.values())
    assert anlz.tag_types == ["PPTH", "PSSI"]
    assert int.from_bytes(bytes(anlz.get_tag("PSSI").content.mood), "big") == 2

    raw = {m: [blob[s : s + n]] for m, s, n in lma._walk_tags(blob)[0]}
    assert lma.pcob_counts(raw[b"PCOB"][0]) == (2, 0, 1)
    g2 = lma.pqt2_summary(raw[b"PQT2"][0])
    assert g2["beats"] == 5 and g2["flags"] == "0x02000002" and g2["anchor_bpm"] == [140.0, 140.0]
    assert lma.pqt2_summary(None) == {"present": False}
    assert lma.pcob_counts(b"PCOB") == (0, 0, 0)


def test_measure_track_partial_on_tag_errors(tmp_path: Path):
    paths = _write_track(tmp_path)
    ext = bytearray(Path(paths["EXT"]).read_bytes())
    for magic, start, _n in lma._walk_tags(bytes(ext))[0]:
        if magic == b"PQT2":
            ext[start + 16 : start + 20] = (0x02000002).to_bytes(4, "big")
    Path(paths["EXT"]).write_bytes(bytes(ext))
    row = lma.measure_track_anlz(paths, None)
    assert row["status"] == "partial" and row["errors"] == {}
    assert set(row["tag_errors"]["EXT"]) == {"PQT2"}
    assert row["grid2"]["present"] and row["grid2"]["flags"] == "0x02000002"
    assert row["pssi"]["present"] and row["cues"]["hot"] == 2 and row["cues"]["comments"] == 1
    assert "PQT2" not in row["tags"]["EXT"]
