"""Tag writes keep an exact copy first, rewrite atomically and respect the size cap.

Covers ``app/tag_backups.py`` through ``audio_tags.write_tags``. Every audio file is
created under ``tmp_path``; the backup store is pointed at ``tmp_path`` per test. The
MP3/FLAC/AIFF/WAV round trips are written with soundfile; M4A needs an ffmpeg with the
aac encoder (``app.ffmpeg_resolver``, e.g. ``LMS_FFMPEG_FULL``) and skips without one.
"""

from __future__ import annotations

import hashlib
import logging
import os
import stat
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any

import pytest
from mutagen.id3 import APIC, ID3, TALB

from app import audio_tags, ffmpeg_resolver, folder_watcher, tag_backups

ROOT = Path(__file__).resolve().parents[1]
_JPEG = b"\xff\xd8\xff\xe0" + b"embedded-front-cover" * 8


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "store"
    monkeypatch.setattr(tag_backups, "backup_root", lambda: root)
    return root


def _mp3(path: Path, size: int = 4096) -> Path:
    # No MPEG frames needed: the ID3 writer only prepends its header.
    path.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * size)
    return path


def _temps(folder: Path) -> list[Path]:
    return list(folder.glob(".lmstag-*"))


def _store_bytes(root: Path) -> int:
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file() and p.suffix != ".json")


# ---------------------------------------------------------------- once per file


def test_first_write_keeps_an_exact_copy_and_later_writes_do_not(tmp_path, store) -> None:
    f = _mp3(tmp_path / "a.mp3")
    original = f.read_bytes()

    assert audio_tags.write_tags(f, {"Title": "One"}) is True
    assert audio_tags.write_tags(f, {"Title": "Two"}) is True
    assert audio_tags.write_tags(f, {"Comment": "Three"}) is True

    gens = tag_backups.generations(f)
    assert len(gens) == 1
    entry, manifest = gens[0]
    assert entry.copy.read_bytes() == original
    assert manifest["sha256"] == hashlib.sha256(original).hexdigest()
    assert manifest["size"] == len(original)
    assert manifest["name"] == "a.mp3"
    assert manifest["written"]["size"] == f.stat().st_size
    assert str(ID3(str(f))["TIT2"]) == "Two"
    assert entry.copy.parent.parent == store
    assert _temps(tmp_path) == []


def test_every_spelling_of_one_path_shares_the_copy(tmp_path, store) -> None:
    (tmp_path / "sub").mkdir()
    f = _mp3(tmp_path / "a.mp3")

    audio_tags.write_tags(f, {"Title": "One"})
    audio_tags.write_tags(tmp_path / "sub" / ".." / "a.mp3", {"Title": "Two"})

    assert len(tag_backups.generations(f)) == 1


def test_an_outside_edit_gets_its_own_generation(tmp_path, store) -> None:
    f = _mp3(tmp_path / "a.mp3")
    original = f.read_bytes()
    audio_tags.write_tags(f, {"Title": "Ours"})
    tags = ID3(str(f))
    tags.add(TALB(encoding=3, text="another tagger"))
    tags.save(str(f))
    st = f.stat()
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))  # clocks tick ~16 ms
    outside = f.read_bytes()

    audio_tags.write_tags(f, {"Title": "Ours again"})

    copies = [entry.copy.read_bytes() for entry, _manifest in tag_backups.generations(f)]
    assert copies == [original, outside]


def test_backup_false_takes_no_copy(tmp_path, store) -> None:
    f = _mp3(tmp_path / "fresh.mp3")

    assert audio_tags.write_tags(f, {"Title": "Download"}, backup=False) is True

    assert tag_backups.generations(f) == []
    assert not store.exists()


# ----------------------------------------------------------------------- the cap


def test_cap_prunes_the_oldest_copies_first(tmp_path, store, monkeypatch) -> None:
    files = [_mp3(tmp_path / f"{i}.mp3") for i in range(4)]
    size = files[0].stat().st_size
    monkeypatch.setattr(tag_backups, "TAG_BACKUP_CAP_BYTES", 2 * size + 100)

    for f in files:
        assert audio_tags.write_tags(f, {"Title": "x"}) is True

    assert [len(tag_backups.generations(f)) for f in files] == [0, 0, 1, 1]
    assert _store_bytes(store) <= 2 * size + 100
    assert sorted(p.name for p in store.iterdir()) == sorted(
        tag_backups.file_key(f) for f in files[2:]
    )  # emptied key folders are removed

    # A pruned file gets a fresh copy (of its state now) on its next write.
    before = files[0].read_bytes()
    audio_tags.write_tags(files[0], {"Title": "y"})
    assert [e.copy.read_bytes() for e, _m in tag_backups.generations(files[0])] == [before]
    assert len(tag_backups.generations(files[2])) == 0  # now the oldest


def test_a_copy_larger_than_the_cap_is_still_kept(tmp_path, store, monkeypatch, caplog) -> None:
    monkeypatch.setattr(tag_backups, "TAG_BACKUP_CAP_BYTES", 100)
    f = _mp3(tmp_path / "big.mp3")
    caplog.set_level(logging.WARNING, logger="TAG_BACKUPS")

    assert audio_tags.write_tags(f, {"Title": "x"}) is True

    assert len(tag_backups.generations(f)) == 1
    assert any("over_cap" in r.getMessage() for r in caplog.records)


def test_crash_leftovers_are_swept_but_an_unreadable_manifest_keeps_its_copy(
    tmp_path, store
) -> None:
    key_dir = store / ("0" * 20)
    key_dir.mkdir(parents=True)
    (key_dir / "20260101-000000-000001.mp3.part").write_bytes(b"half")
    (key_dir / "20260101-000000-000002.mp3").write_bytes(b"no manifest")
    (key_dir / "20260101-000000-000003.mp3").write_bytes(b"kept")
    (key_dir / "20260101-000000-000003.json").write_text("{not json", encoding="utf-8")

    audio_tags.write_tags(_mp3(tmp_path / "a.mp3"), {"Title": "x"})  # triggers a prune scan

    assert sorted(p.name for p in key_dir.iterdir()) == [
        "20260101-000000-000003.json",
        "20260101-000000-000003.mp3",
    ]


# ------------------------------------------------------- failure mid-write


def _junk_then(outcome: str) -> Any:
    def handler(path: Path, fields: Any, artwork: Any, suffix: str) -> bool:
        with open(path, "r+b") as fh:  # half a save: a rewritten header, then trouble
            fh.write(b"JUNK" * 64)
        if outcome == "raises":
            raise RuntimeError("mutagen blew up mid-save")
        if outcome == "interrupt":
            raise KeyboardInterrupt
        return outcome == "ok"

    return handler


@pytest.mark.parametrize("outcome", ["raises", "returns_false", "interrupt"])
def test_a_writer_failing_mid_save_leaves_the_original_byte_identical(
    tmp_path, store, monkeypatch, outcome
) -> None:
    f = _mp3(tmp_path / "a.mp3")
    before = f.read_bytes()
    monkeypatch.setitem(audio_tags._DISPATCH, ".mp3", _junk_then(outcome))

    if outcome == "interrupt":
        with pytest.raises(KeyboardInterrupt):
            audio_tags.write_tags(f, {"Title": "x"})
    else:
        assert audio_tags.write_tags(f, {"Title": "x"}) is False

    assert f.read_bytes() == before
    assert _temps(tmp_path) == []
    assert [e.copy.read_bytes() for e, _m in tag_backups.generations(f)] == [before]


def test_a_file_held_open_by_another_process_is_not_replaced(tmp_path, store, monkeypatch) -> None:
    f = _mp3(tmp_path / "a.mp3")
    before = f.read_bytes()
    monkeypatch.setattr(tag_backups, "_REPLACE_BACKOFF_S", 0)

    def held(src: Any, dst: Any) -> None:
        raise PermissionError(13, "The process cannot access the file")

    monkeypatch.setattr(tag_backups.os, "replace", held)

    assert audio_tags.write_tags(f, {"Title": "x"}) is False
    assert f.read_bytes() == before
    assert _temps(tmp_path) == []


def test_a_file_changed_while_its_copy_was_edited_is_not_replaced(
    tmp_path, store, monkeypatch
) -> None:
    f = _mp3(tmp_path / "a.mp3")

    def meanwhile(path: Path, fields: Any, artwork: Any, suffix: str) -> bool:
        f.write_bytes(f.read_bytes() + b"appended by someone else")
        return True

    monkeypatch.setitem(audio_tags._DISPATCH, ".mp3", meanwhile)
    expected_after = f.read_bytes() + b"appended by someone else"

    assert audio_tags.write_tags(f, {"Title": "x"}) is False
    assert f.read_bytes() == expected_after  # their write stands, ours is dropped


def test_a_track_streaming_to_the_player_does_not_block_the_write(tmp_path, store) -> None:
    """The stream reader holds no handle between chunks (Windows refuses os.replace then)."""
    from app import main

    f = _mp3(tmp_path / "playing.mp3", size=3 * 1024 * 1024)
    stream = main._read_file_range(f, 0, f.stat().st_size - 1)
    first = next(stream)  # the browser read one chunk and paused

    assert audio_tags.write_tags(f, {"Title": "edited while playing"}) is True
    assert str(ID3(str(f))["TIT2"]) == "edited while playing"
    assert len(first) == main._STREAM_CHUNK_BYTES
    stream.close()


def test_a_killed_process_leaves_the_original_untouched(tmp_path) -> None:
    """A hard kill mid-save (no finally, no except) — the strongest crash we can stage."""
    f = _mp3(tmp_path / "a.mp3")
    before = f.read_bytes()
    script = textwrap.dedent(
        """
        import os, sys
        from app import audio_tags

        def dies(path, fields, artwork, suffix):
            with open(path, "r+b") as fh:
                fh.write(b"JUNK" * 64)
                fh.flush()
            os._exit(9)

        audio_tags._DISPATCH[".mp3"] = dies
        audio_tags.write_tags(sys.argv[1], {"Title": "never lands"})
        """
    )
    env = {**os.environ, "APPDATA": str(tmp_path / "appdata"), "PYTHONPATH": str(ROOT)}
    done = subprocess.run(
        [sys.executable, "-c", script, str(f)], cwd=ROOT, env=env, timeout=60, check=False
    )

    assert done.returncode == 9
    assert f.read_bytes() == before
    leftovers = _temps(tmp_path)
    assert len(leftovers) == 1  # the half-written temp copy, never the original
    assert not folder_watcher._is_audio(leftovers[0])  # never auto-imported
    copies = list(
        (tmp_path / "appdata" / "MusicLibraryManager" / "tag-write-backups").rglob("*.mp3")
    )
    assert [c.read_bytes() for c in copies] == [before]


# -------------------------------------------------------------- refusals


def test_no_copy_means_no_write(tmp_path, store, monkeypatch) -> None:
    f = _mp3(tmp_path / "a.mp3")
    before = f.read_bytes()

    def disk_full(*args: Any) -> Any:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(tag_backups, "_take_copy", disk_full)

    assert audio_tags.write_tags(f, {"Title": "x"}) is False
    assert f.read_bytes() == before


def test_a_read_only_file_is_refused_without_a_copy(tmp_path, store) -> None:
    f = _mp3(tmp_path / "a.mp3")
    os.chmod(f, stat.S_IREAD)
    try:
        assert audio_tags.write_tags(f, {"Title": "x"}) is False
        assert tag_backups.generations(f) == []
    finally:
        os.chmod(f, stat.S_IREAD | stat.S_IWRITE)


def test_log_lines_carry_no_path(tmp_path, store, monkeypatch, caplog) -> None:
    folder = tmp_path / "Private Crate"
    folder.mkdir()
    files = [_mp3(folder / f"{i}.mp3") for i in range(3)]
    monkeypatch.setattr(tag_backups, "TAG_BACKUP_CAP_BYTES", files[0].stat().st_size + 10)
    caplog.set_level(logging.DEBUG)

    for f in files:
        audio_tags.write_tags(f, {"Title": "x"})

    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("op=tag")]
    assert any("op=tag_backup status=created" in line for line in lines)
    assert any("op=tag_backup_prune" in line for line in lines)
    for line in lines:
        assert "Private Crate" not in line
        assert str(tmp_path) not in line


# ------------------------------------------- real containers, byte-exact restore

#: libsndfile (soundfile) writes these four; M4A needs an ffmpeg with the aac encoder.
_SOUNDFILE = {
    ".mp3": ("MP3", "MPEG_LAYER_III"),
    ".flac": ("FLAC", "PCM_16"),
    ".aiff": ("AIFF", "PCM_16"),
    ".wav": ("WAV", "PCM_16"),
}
_SUFFIXES = [".aiff", ".flac", ".m4a", ".mp3", ".wav"]


def _sine() -> Any:
    np = pytest.importorskip("numpy")
    t = np.arange(44100) / 44100
    return (0.3 * np.sin(2 * np.pi * 440 * t)).astype("float32")


def _aac_ffmpeg() -> str:
    resolved = ffmpeg_resolver.resolve_for_encoder("aac")
    if not resolved.available or not resolved.binary:
        pytest.skip("no ffmpeg with the aac encoder")
    return resolved.binary


def _real_file(path: Path) -> Path:
    sf = pytest.importorskip("soundfile")
    if path.suffix in _SOUNDFILE:
        fmt, subtype = _SOUNDFILE[path.suffix]
        sf.write(str(path), _sine(), 44100, format=fmt, subtype=subtype)
        return path
    source = path.with_suffix(".src.wav")
    sf.write(str(source), _sine(), 44100, format="WAV", subtype="PCM_16")
    subprocess.run(
        [
            _aac_ffmpeg(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-c:a",
            "aac",
            str(path),
        ],
        check=True,
        timeout=30,
    )
    source.unlink()
    return path


def _embed_cover(path: Path) -> None:
    suffix = path.suffix
    if suffix == ".mp3":
        tags = ID3()
        tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="front", data=_JPEG))
        tags.save(str(path))
    elif suffix == ".flac":
        from mutagen.flac import FLAC, Picture

        flac = FLAC(str(path))
        pic = Picture()
        pic.type, pic.mime, pic.data = 3, "image/jpeg", _JPEG
        flac.add_picture(pic)
        flac.save()
    elif suffix == ".m4a":
        from mutagen.mp4 import MP4, MP4Cover

        mp4 = MP4(str(path))
        mp4["covr"] = [MP4Cover(_JPEG, imageformat=MP4Cover.FORMAT_JPEG)]
        mp4.save()
    else:
        from mutagen.aiff import AIFF
        from mutagen.wave import WAVE

        container = WAVE(str(path)) if suffix == ".wav" else AIFF(str(path))
        if container.tags is None:
            container.add_tags()
        container.tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="front", data=_JPEG))
        container.save()


def _cover(path: Path) -> bytes:
    import mutagen

    f = mutagen.File(str(path))
    if path.suffix == ".flac":
        return bytes(f.pictures[0].data)
    if path.suffix == ".m4a":
        return bytes(f["covr"][0])
    return bytes(f.tags.getall("APIC")[0].data)


def _pcm_md5(path: Path) -> str:
    if path.suffix in _SOUNDFILE:
        import soundfile as sf

        data, _rate = sf.read(str(path), dtype="int16")
        return hashlib.md5(data.tobytes()).hexdigest()
    out = subprocess.run(
        [
            _aac_ffmpeg(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-f",
            "s16le",
            "-",
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    return hashlib.md5(out.stdout).hexdigest()


@pytest.mark.parametrize("suffix", _SUFFIXES)
def test_tags_land_audio_and_cover_stay_and_restore_is_byte_exact(tmp_path, store, suffix) -> None:
    f = _real_file(tmp_path / f"track{suffix}")
    _embed_cover(f)
    original = f.read_bytes()
    pcm = _pcm_md5(f)

    assert audio_tags.write_tags(f, {"Title": "Edited", "Artist": "Someone", "Comment": "c"})

    tags = audio_tags.read_tags(f)
    assert (tags.get("title"), tags.get("artist")) == ("Edited", "Someone")
    assert _pcm_md5(f) == pcm
    assert _cover(f) == _JPEG
    (entry, _manifest), *rest = tag_backups.generations(f)
    assert rest == []
    assert entry.copy.read_bytes() == original

    with audio_tags.FileWriteLocks([f]):
        assert tag_backups.restore(f) is True
    assert f.read_bytes() == original
    assert _temps(tmp_path) == []


def test_restore_refuses_a_damaged_copy(tmp_path, store) -> None:
    f = _mp3(tmp_path / "a.mp3")
    audio_tags.write_tags(f, {"Title": "x"})
    edited = f.read_bytes()
    ((entry, _manifest),) = tag_backups.generations(f)
    entry.copy.write_bytes(b"bit rot")

    with pytest.raises(ValueError, match="damaged"):
        tag_backups.restore(f)
    assert f.read_bytes() == edited


def test_restore_without_a_copy_is_a_no_op(tmp_path, store) -> None:
    f = _mp3(tmp_path / "never-written.mp3")

    assert tag_backups.restore(f) is False
