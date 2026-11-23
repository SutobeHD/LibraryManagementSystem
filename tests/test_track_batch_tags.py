"""PATCH /api/tracks/batch writes the audio-file tags like the single-track edit.

TrackTable and BatchEditBar save Title / Artist / Album through the batch route, which
only wrote the library: the file kept its old tags, while ``POST /api/track/{tid}``
mirrored its fields into the file when ``write_tags_to_files`` is on (default true).
Both routes now share one write-back and report it per track as ``file_tags``.

Every audio file is a fresh copy under ``tmp_path``; the library is the rbox stand-in
from ``test_track_batch_writes``. Nothing outside ``tmp_path`` is opened.
"""

from __future__ import annotations

import shutil
import wave
from pathlib import Path
from typing import Any

import pytest
from mutagen.id3 import ID3
from mutagen.wave import WAVE

from app import main
from tests.test_track_batch_writes import (
    _batch,
    _fail_on,
    _MasterDb,
    _req,
    _row,
    facade,
    live,
    master,
)


def _mp3(path: Path) -> Path:
    # No MPEG frames needed: the ID3 writer only prepends its header.
    path.write_bytes(b"\xff\xfb\x90\x00" + b"\x00" * 4096)
    return path


def _wav(path: Path) -> Path:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"\x00\x00" * 4410)
    return path


@pytest.fixture
def files(tmp_path: Path) -> dict[str, Path]:
    music = tmp_path / "music"
    music.mkdir()
    return {"1": _mp3(music / "one.mp3"), "2": _wav(music / "two.wav")}


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    cfg: dict[str, Any] = {"write_tags_to_files": True}
    monkeypatch.setattr(main.SettingsManager, "load", staticmethod(lambda: dict(cfg)))
    return cfg


@pytest.fixture
def lib(facade, live, files, settings):
    for tid, path in files.items():
        live.tracks[tid]["path"] = str(path)
    return live


def _frames(path: Path) -> dict[str, str]:
    tags = WAVE(str(path)).tags if path.suffix == ".wav" else ID3(str(path))
    return {key: str(frame) for key, frame in (tags or {}).items()}


def test_batch_writes_title_artist_album_into_every_file(lib, files, auth_token) -> None:
    updates = {"Title": "New Title", "Artist": "New Artist", "Album": "New Album"}

    r = _batch(["1", "2"], updates, auth_token)

    assert r.status_code == 200, r.text
    assert r.json() == {"status": "success", "file_tags": {"1": "written", "2": "written"}}
    for path in files.values():
        frames = _frames(path)
        assert frames["TIT2"] == "New Title"
        assert frames["TPE1"] == "New Artist"
        assert frames["TALB"] == "New Album"


def test_batch_writes_the_same_tags_as_the_single_track_edit(
    lib, files, tmp_path, auth_token
) -> None:
    twin = shutil.copy(files["1"], tmp_path / "music" / "twin.mp3")
    lib.tracks["3"]["path"] = str(twin)
    updates = {"Rating": 4, "ColorID": 2, "Comment": "warm-up", "Genre": "Techno"}

    single = _req("POST", "/api/track/1", updates, auth_token)
    batch = _batch(["3"], updates, auth_token)

    assert single.status_code == batch.status_code == 200
    assert single.json()["file_tags"] == "written"
    assert batch.json()["file_tags"] == {"3": "written"}
    assert _frames(Path(twin)) == _frames(files["1"])
    assert Path(twin).read_bytes() == files["1"].read_bytes()


def test_setting_off_leaves_every_file_alone(lib, files, settings, auth_token) -> None:
    settings["write_tags_to_files"] = False
    before = {tid: p.read_bytes() for tid, p in files.items()}

    r = _batch(["1", "2"], {"Title": "New"}, auth_token)

    assert r.status_code == 200, r.text
    assert r.json()["file_tags"] == {"1": "skipped", "2": "skipped"}
    assert {tid: p.read_bytes() for tid, p in files.items()} == before
    assert lib.tracks["1"]["Title"] == "New"  # the library write still happened


def test_setting_missing_means_on(lib, files, settings, auth_token) -> None:
    settings.clear()  # an old settings.json without the key: default true, as before
    r = _batch(["1"], {"Title": "New"}, auth_token)
    assert r.json()["file_tags"] == {"1": "written"}
    assert _frames(files["1"])["TIT2"] == "New"


def test_per_track_status_for_missing_path_and_missing_file(lib, tmp_path, auth_token) -> None:
    lib.tracks["2"]["path"] = ""
    lib.tracks["3"]["path"] = str(tmp_path / "music" / "gone.mp3")

    r = _batch(["1", "2", "3"], {"Title": "New"}, auth_token)

    assert r.status_code == 200, r.text
    assert r.json()["file_tags"] == {"1": "written", "2": "skipped", "3": "failed"}


def test_a_crashing_tag_write_is_reported_for_that_track_only(
    lib, files, monkeypatch, auth_token
) -> None:
    real = main.audio_tags.write_tags

    def flaky(src: Any, updates: Any, artwork: Any = None) -> bool:
        if str(src).endswith(".wav"):
            raise OSError("file in use")
        return real(src, updates, artwork=artwork)

    monkeypatch.setattr(main.audio_tags, "write_tags", flaky)

    r = _batch(["1", "2"], {"Album": "A"}, auth_token)

    assert r.status_code == 200, r.text
    assert r.json()["file_tags"] == {"1": "written", "2": "error"}


def test_unreadable_settings_report_error_and_keep_the_library_write(
    lib, files, monkeypatch, auth_token
) -> None:
    def broken() -> dict[str, Any]:
        raise OSError("settings.json locked")

    monkeypatch.setattr(main.SettingsManager, "load", staticmethod(broken))
    before = files["1"].read_bytes()

    r = _batch(["1", "2"], {"Title": "New"}, auth_token)

    assert r.status_code == 200, r.text
    assert r.json()["file_tags"] == {"1": "error", "2": "error"}
    assert files["1"].read_bytes() == before
    assert lib.tracks["1"]["Title"] == "New"


def test_cover_art_is_embedded_like_the_single_track_edit(lib, files, tmp_path, auth_token) -> None:
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")
    lib.tracks["1"]["Artwork"] = str(cover)

    r = _batch(["1"], {"Title": "New"}, auth_token)

    assert r.json()["file_tags"] == {"1": "written"}
    assert ID3(str(files["1"])).getall("APIC")[0].data == cover.read_bytes()


@pytest.mark.parametrize(
    ("ids", "updates", "status"),
    [
        (["1", "9"], {"Title": "New"}, 404),  # unknown id
        (["1", "2"], {"Rating": 9}, 400),  # bad value
        (["1", "2"], {"Title": "New", "Artist": "X"}, 500),  # rbox refuses row 2
    ],
)
def test_a_refused_batch_touches_no_file(
    lib, files, master: _MasterDb, auth_token, ids, updates, status
) -> None:
    master.hook = _fail_on("update_content_artist", "2")
    before = {tid: p.read_bytes() for tid, p in files.items()}

    r = _batch(ids, updates, auth_token)

    assert r.status_code == status, r.text
    assert {tid: p.read_bytes() for tid, p in files.items()} == before
    assert master.rows["1"] == _row("1")
