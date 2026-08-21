"""Byte-layout regression tests for the ANLZ cue + VBR tags.

Guards the 2026-08-22 fix. `_build_pcob` used to write the entry count into
the PCOB header's FIRST u16 (`unknown`) instead of the second (`len_cues`),
so every conformant reader parsed **zero** hot cues no matter how many PCPT
records followed. Memory lists survived only because the old code wrote the
count into both slots when `cue_type == 0`.

These tests assert the reader-visible *count*, not just the times — the old
bug was invisible to a test that only compared cue positions whenever a hot
cue happened to coincide with a memory cue.

`pytest.importorskip` keeps the suite green on a machine without the
reference parser installed; CI has it.
"""

from __future__ import annotations

import struct

import pytest

from app.anlz_writer import build_dat, build_ext

pyrekordbox_anlz = pytest.importorskip("pyrekordbox.anlz")

HOT_CUES = [
    {
        "number": 0,
        "type": "hot_cue",
        "time_ms": 14777,
        "name": "Start",
        "color_id": 1,
        "color_rgb": (222, 68, 207),
    },
    {
        "number": 1,
        "type": "hot_cue",
        "time_ms": 29777,
        "name": "Verse",
        "color_id": 2,
        "color_rgb": (48, 209, 190),
    },
    {
        "number": 2,
        "type": "hot_cue",
        "time_ms": 44778,
        "name": "Drop",
        "color_id": 3,
        "color_rgb": (255, 140, 0),
    },
]
# Deliberately disjoint from HOT_CUES: overlapping positions are what let the
# original bug hide for months.
MEMORY_CUES = [
    {"type": "memory_cue", "time_ms": 1000, "name": "Intro"},
    {"type": "memory_cue", "time_ms": 90000, "name": "Outro"},
]

HOT_TIMES = sorted(c["time_ms"] for c in HOT_CUES)
MEMORY_TIMES = sorted(c["time_ms"] for c in MEMORY_CUES)


def _write(tmp_path, *, hot=HOT_CUES, memory=MEMORY_CUES):
    dat = tmp_path / "ANLZ0000.DAT"
    ext = tmp_path / "ANLZ0000.EXT"
    dat.write_bytes(
        build_dat(
            "/music/x.mp3", [], [0] * 400, [0] * 400, [0] * 400, hot_cues=hot, memory_cues=memory
        )
    )
    ext.write_bytes(
        build_ext(
            "/music/x.mp3", [], [0] * 900, [0] * 900, [[0] * 900], hot_cues=hot, memory_cues=memory
        )
    )
    return dat, ext


def _lists(path, tag):
    """{cue_type: parsed_tag_content} for every `tag` list in the file."""
    f = pyrekordbox_anlz.AnlzFile.parse_file(str(path))
    out = {}
    for t in f.getall_tags(tag):
        content = t.content
        cue_type = int(content.get("cue_type", content.get("type")))
        out[cue_type] = content
    return out


class TestPcobFieldOrder:
    @pytest.mark.parametrize("which", ["dat", "ext"])
    def test_hot_list_reports_its_real_count(self, tmp_path, which):
        """The regression: len_cues must carry the entry count, not 0."""
        files = dict(zip(("dat", "ext"), _write(tmp_path), strict=True))
        hot = _lists(files[which], "PCOB")[1]
        assert hot.count == len(HOT_CUES)
        assert sorted(e.time for e in hot.entries) == HOT_TIMES

    @pytest.mark.parametrize("which", ["dat", "ext"])
    def test_memory_list_still_round_trips(self, tmp_path, which):
        files = dict(zip(("dat", "ext"), _write(tmp_path), strict=True))
        mem = _lists(files[which], "PCOB")[0]
        assert mem.count == len(MEMORY_CUES)
        assert sorted(e.time for e in mem.entries) == MEMORY_TIMES

    def test_unknown_u16_is_zero(self, tmp_path):
        """rbox/rekordcrate hard-asserts this field is 0 and rejects the whole
        file otherwise — the old writer put the entry count here."""
        dat, _ = _write(tmp_path)
        blob = dat.read_bytes()
        off = -1
        seen = 0
        while (off := blob.find(b"PCOB", off + 1)) >= 0:
            unknown, len_cues = struct.unpack_from(">HH", blob, off + 16)
            assert unknown == 0, f"PCOB at 0x{off:x} has unknown={unknown}"
            assert len_cues > 0
            seen += 1
        assert seen == 2  # hot + memory


class TestPco2FieldOrder:
    def test_extended_list_reports_its_real_count(self, tmp_path):
        _, ext = _write(tmp_path)
        hot = _lists(ext, "PCO2")[1]
        assert hot.count == len(HOT_CUES)
        assert sorted(e.time for e in hot.entries) == HOT_TIMES

    def test_extended_entries_carry_names(self, tmp_path):
        """PCO2 is what gives the CDJ-3000 cue names + colours; an entry body
        whose declared length is wrong desynchronises every entry after it."""
        _, ext = _write(tmp_path)
        hot = _lists(ext, "PCO2")[1]
        names = [e.comment.rstrip("\x00") for e in hot.entries]
        assert names == [c["name"] for c in HOT_CUES]

    def test_entry_total_len_matches_emitted_bytes(self, tmp_path):
        """len_entry must equal 48 + len_comment — the reader derives its
        trailing padding from it."""
        _, ext = _write(tmp_path)
        blob = ext.read_bytes()
        off = -1
        seen = 0
        while (off := blob.find(b"PCP2", off + 1)) >= 0:
            len_entry = struct.unpack_from(">I", blob, off + 8)[0]
            # body starts at +12; len_comment is 28 bytes into it
            len_comment = struct.unpack_from(">I", blob, off + 40)[0]
            assert len_entry == 48 + len_comment
            seen += 1
        assert seen == len(HOT_CUES) + len(MEMORY_CUES)


class TestPvbrLength:
    def test_declares_1620_like_every_real_export(self, tmp_path):
        """4,989 PVBR tags in the reference Rekordbox library all declare
        1620; the writer computed 1616 by omitting the trailing u32."""
        dat, _ = _write(tmp_path)
        blob = dat.read_bytes()
        off = blob.find(b"PVBR")
        assert off >= 0
        len_header, len_tag = struct.unpack_from(">II", blob, off + 4)
        assert (len_header, len_tag) == (16, 1620)

    def test_parses_without_warnings(self, tmp_path, caplog):
        dat, _ = _write(tmp_path)
        with caplog.at_level("WARNING", logger="pyrekordbox"):
            pyrekordbox_anlz.AnlzFile.parse_file(str(dat))
        assert not [r for r in caplog.records if "len_tag" in r.getMessage()]


class TestEmptyLists:
    def test_no_cues_produces_zero_counts(self, tmp_path):
        dat, ext = _write(tmp_path, hot=[], memory=[])
        for path in (dat, ext):
            for content in _lists(path, "PCOB").values():
                assert content.count == 0
                assert list(content.entries) == []
