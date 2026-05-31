"""
Round-trip tests for app/anlz_cue_patch.py.

Strategy: build a synthetic but structurally real ANLZ via anlz_writer's own
high-level builders, patch its memory cues, then assert that

  * every non-memory-cue tag is carried through byte-for-byte,
  * the memory PCOB (.DAT) / PCOB+PCO2 (.EXT) equal a fresh build of the new
    cues,
  * the PMAI file length is recomputed correctly,
  * a backup is created,
  * the operation is idempotent.

No rbox dependency — anlz_writer/anlz_cue_patch are pure-Python byte writers.
"""

import struct

import pytest

from app import anlz_cue_patch as patch
from app.anlz_writer import (
    PMAI_MAGIC,
    _build_pco2,
    _build_pcob,
    build_dat,
    build_ext,
)

# ── Fixtures: synthetic analysis data ────────────────────────────────────────

BEATS = [{"beat_number": (i % 4) + 1, "tempo": 12800, "time_ms": i * 500} for i in range(8)]
PVBR = [i for i in range(400)]
PWAV = [i % 256 for i in range(400)]
PWV2 = [i % 256 for i in range(100)]
HOT_CUES = [{"type": "hot_cue", "number": 0, "time_ms": 1000, "name": "A"}]
ORIG_MEM = [{"type": "memory_cue", "time_ms": 500, "number": 0}]

NEW_MEM = [
    {"type": "memory_cue", "time_ms": 0, "number": 0, "name": "P1", "color_rgb": (232, 164, 42)},
    {
        "type": "memory_cue",
        "time_ms": 16000,
        "number": 0,
        "name": "P2",
        "color_rgb": (232, 164, 42),
    },
    {
        "type": "memory_cue",
        "time_ms": 32000,
        "number": 0,
        "name": "P3",
        "color_rgb": (232, 164, 42),
    },
]


def _parse(data: bytes):
    """Return list of (magic, cue_type_or_None, raw_bytes) for top-level tags."""
    tags, end = patch._walk_tags(data)
    out = []
    for magic, start, total_len in tags:
        cue_type = (
            patch._tag_cue_type(data, start, total_len) if magic in (b"PCOB", b"PCO2") else None
        )
        out.append((magic, cue_type, data[start : start + total_len]))
    return out, data[end:]


def _is_mem(magic, cue_type):
    return magic in (b"PCOB", b"PCO2") and cue_type == 0


def _write_dat(tmp_path, mem=ORIG_MEM):
    data = build_dat("X:/track.mp3", BEATS, PVBR, PWAV, PWV2, hot_cues=HOT_CUES, memory_cues=mem)
    (tmp_path / "ANLZ0000.DAT").write_bytes(data)
    return data


def _write_ext(tmp_path, mem=ORIG_MEM):
    data = build_ext(
        "X:/track.mp3",
        BEATS,
        pwv3=[i % 256 for i in range(20)],
        pwv5=[i % 256 for i in range(20)],
        pwv4=[[1, 2, 3, 4, 5, 6]] * 5,
        phrases=[],
        duration_ms=180000,
        hot_cues=HOT_CUES,
        memory_cues=mem,
        bpm=128.0,
    )
    (tmp_path / "ANLZ0000.EXT").write_bytes(data)
    return data


# ── Tests ────────────────────────────────────────────────────────────────────


def test_dat_preserves_non_cue_tags_and_replaces_memory(tmp_path):
    orig = _write_dat(tmp_path)
    orig_tags, _ = _parse(orig)

    patch.patch_memory_cues(str(tmp_path), NEW_MEM)

    new = (tmp_path / "ANLZ0000.DAT").read_bytes()
    new_tags, trailing = _parse(new)

    # same tag count + order, non-memory tags byte-identical
    assert [t[0] for t in new_tags] == [t[0] for t in orig_tags]
    assert trailing == b""
    for (omagic, octype, obytes), (nmagic, _nctype, nbytes) in zip(
        orig_tags, new_tags, strict=True
    ):
        if _is_mem(omagic, octype):
            assert nbytes == _build_pcob(0, NEW_MEM)
        else:
            assert nbytes == obytes, f"tag {nmagic!r} mutated"


def test_dat_pmai_length_recomputed(tmp_path):
    _write_dat(tmp_path)
    patch.patch_memory_cues(str(tmp_path), NEW_MEM)
    new = (tmp_path / "ANLZ0000.DAT").read_bytes()
    assert new[:4] == PMAI_MAGIC
    file_len = struct.unpack(">I", new[8:12])[0]
    assert file_len == len(new)


def test_ext_replaces_pcob_and_pco2(tmp_path):
    _write_dat(tmp_path)  # real ANLZ dirs always hold both .DAT + .EXT
    orig = _write_ext(tmp_path)
    orig_tags, _ = _parse(orig)

    patch.patch_memory_cues(str(tmp_path), NEW_MEM)

    new = (tmp_path / "ANLZ0000.EXT").read_bytes()
    new_tags, _ = _parse(new)
    assert [t[0] for t in new_tags] == [t[0] for t in orig_tags]
    saw_pcob = saw_pco2 = False
    for (omagic, octype, obytes), (nmagic, _nctype, nbytes) in zip(
        orig_tags, new_tags, strict=True
    ):
        if omagic == b"PCOB" and octype == 0:
            assert nbytes == _build_pcob(0, NEW_MEM)
            saw_pcob = True
        elif omagic == b"PCO2" and octype == 0:
            assert nbytes == _build_pco2(0, NEW_MEM)
            saw_pco2 = True
        else:
            assert nbytes == obytes, f"tag {nmagic!r} mutated"
    assert saw_pcob and saw_pco2


def test_hot_cue_pcob_untouched(tmp_path):
    """Patching memory cues must never disturb the hot-cue PCOB (cue_type=1)."""
    _write_dat(tmp_path)  # real ANLZ dirs always hold both .DAT + .EXT
    orig = _write_ext(tmp_path)
    orig_tags, _ = _parse(orig)
    hot = [b for (m, c, b) in orig_tags if m == b"PCOB" and c == 1]

    patch.patch_memory_cues(str(tmp_path), NEW_MEM)
    new = (tmp_path / "ANLZ0000.EXT").read_bytes()
    new_tags, _ = _parse(new)
    hot_after = [b for (m, c, b) in new_tags if m == b"PCOB" and c == 1]
    assert hot == hot_after


def test_backup_created(tmp_path):
    _write_dat(tmp_path)
    res = patch.patch_memory_cues(str(tmp_path), NEW_MEM)
    assert res["dat"] is True
    assert len(res["backups"]) >= 1
    assert any(".DAT.bak-" in b for b in res["backups"])


def test_idempotent(tmp_path):
    _write_dat(tmp_path)
    patch.patch_memory_cues(str(tmp_path), NEW_MEM)
    first = (tmp_path / "ANLZ0000.DAT").read_bytes()
    patch.patch_memory_cues(str(tmp_path), NEW_MEM, backup=False)
    second = (tmp_path / "ANLZ0000.DAT").read_bytes()
    assert first == second


def test_empty_cue_list(tmp_path):
    orig = _write_dat(tmp_path)
    orig_tags, _ = _parse(orig)
    patch.patch_memory_cues(str(tmp_path), [])
    new = (tmp_path / "ANLZ0000.DAT").read_bytes()
    new_tags, _ = _parse(new)
    # memory PCOB now empty, everything else identical
    for (omagic, octype, obytes), (_nmagic, _nctype, nbytes) in zip(
        orig_tags, new_tags, strict=True
    ):
        if _is_mem(omagic, octype):
            assert nbytes == _build_pcob(0, [])
        else:
            assert nbytes == obytes


def test_large_cue_list(tmp_path):
    _write_dat(tmp_path)
    big = [{"type": "memory_cue", "time_ms": i * 1000, "number": 0} for i in range(200)]
    patch.patch_memory_cues(str(tmp_path), big)
    new = (tmp_path / "ANLZ0000.DAT").read_bytes()
    new_tags, _ = _parse(new)
    mem = [b for (m, c, b) in new_tags if _is_mem(m, c)]
    assert mem and mem[0] == _build_pcob(0, big)
    # PMAI length still consistent
    assert struct.unpack(">I", new[8:12])[0] == len(new)


def test_missing_dat_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        patch.patch_memory_cues(str(tmp_path), NEW_MEM)
