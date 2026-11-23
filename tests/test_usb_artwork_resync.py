"""Cover files follow their slot across re-syncs (PC test 2026-11-22).

`write_artwork_pair` returned early whenever a slot's four files existed. Slots are
reused per sync, so after a re-sync an image id could show the previous track's
cover — also for a track with no cover at all. Now a digest of the source image
(`PIONEER/Artwork/.lms-artwork.json`) decides: rewrite on change, leave alone when
equal; files of image ids the new database no longer uses are removed.

Real `OneLibraryUsbWriter.sync()` against a stick folder under `tmp_path`.
"""

from __future__ import annotations

import gc
import io
from pathlib import Path

import pytest

from app import anlz_sidecar, usb_artwork

Image = pytest.importorskip("PIL.Image")
rbox = pytest.importorskip("rbox")

from tests.test_anlz_usb_export import _source_trio  # noqa: E402
from tests.test_onelibrary_track_limit import _Source  # noqa: E402

RED, GREEN, BLUE = (220, 20, 20), (20, 200, 20), (20, 20, 220)


@pytest.fixture(autouse=True)
def no_analysis(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("sync must use the sidecar, not re-analyse")

    monkeypatch.setattr(anlz_sidecar, "write_companion_anlz", boom)


def _jpeg(color: tuple[int, int, int], size: int = 300) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (size, size), color).save(buf, format="JPEG")
    return buf.getvalue()


def _color_of(data: bytes) -> tuple[int, int, int]:
    img = Image.open(io.BytesIO(data)).convert("RGB")
    return img.getpixel((img.width // 2, img.height // 2))


def _close(a, b, tol: int = 40) -> bool:
    return all(abs(x - y) <= tol for x, y in zip(a, b, strict=True))


def _track(tmp: Path, name: str, color: tuple[int, int, int] | None) -> dict:
    folder = tmp / "music" / name
    folder.mkdir(parents=True, exist_ok=True)
    audio = folder / f"{name}.mp3"
    audio.write_bytes(b"\xff\xfb" + name.encode() * 16)
    if color is not None:
        (folder / "cover.jpg").write_bytes(_jpeg(color))
    return {
        "id": name,
        "title": name,
        "artist": "A",
        "album": "",
        "genre": "",
        "key": "",
        "label": "",
        "bpm": 120.0,
        "duration_ms": 30000,
        "path": str(audio),
    }


def _sync(tmp: Path, stick: Path, tracks: list[dict]) -> None:
    from app.usb_one_library import OneLibraryUsbWriter

    source = _Source(
        tracks,
        [
            {
                "id": "p",
                "name": "P",
                "parent_id": "ROOT",
                "type": "1",
                "track_ids": [t["id"] for t in tracks],
            }
        ],
        _source_trio(tmp / "side").parent,
    )
    events = list(OneLibraryUsbWriter(str(stick)).sync(source, audio_copy=True, copy_anlz=True))
    assert events[-1]["stage"] == "complete", events[-1]


def _covers(stick: Path) -> dict[str, tuple[int, str]]:
    """title -> (image id, image path) as the stick's database has it."""
    db = rbox.OneLibrary(str(stick / "PIONEER" / "rekordbox" / "exportLibrary.db"))
    try:
        paths = {img.id: img.path or "" for img in db.get_images()}
        return {
            c.title: (c.image_id, paths.get(c.image_id, ""))
            for c in db.get_contents()
            if not (c.title or "").startswith("__placeholder_")
        }
    finally:
        del db
        gc.collect()


def _art_files(stick: Path) -> set[str]:
    root = stick / "PIONEER" / "Artwork"
    return {p.name for p in root.rglob("*.jpg")}


def test_a_reused_slot_shows_its_new_tracks_cover(tmp_path: Path) -> None:
    stick = tmp_path / "stick"
    stick.mkdir()
    red, green, blue = (
        _track(tmp_path, "T0", RED),
        _track(tmp_path, "T1", GREEN),
        _track(tmp_path, "T2", BLUE),
    )
    _sync(tmp_path, stick, [red, green, blue])
    first = _covers(stick)
    assert all(path for _id, path in first.values())

    # T0 leaves the library: T1 and T2 move up one slot each.
    _sync(tmp_path, stick, [green, blue])
    second = _covers(stick)

    assert set(second) == {"T1", "T2"}
    for title, color in (("T1", GREEN), ("T2", BLUE)):
        image_id, rel = second[title]
        small = stick / rel.lstrip("/")
        medium = small.with_name(f"a{image_id}_m.jpg")
        assert _close(_color_of(small.read_bytes()), color), title
        assert _close(_color_of(medium.read_bytes()), color), title
        assert small.with_name(f"b{image_id}.jpg").read_bytes() == small.read_bytes()
    # The third slot is gone, so are its four files.
    live = {image_id for image_id, _ in second.values()}
    assert {int(n.lstrip("ab").split("_")[0].split(".")[0]) for n in _art_files(stick)} == live


def test_a_track_without_cover_does_not_inherit_one(tmp_path: Path) -> None:
    stick = tmp_path / "stick"
    stick.mkdir()
    _sync(tmp_path, stick, [_track(tmp_path, "T0", RED)])

    _sync(tmp_path, stick, [_track(tmp_path, "N0", None)])

    (_image_id, rel) = _covers(stick)["N0"]
    assert rel == ""
    assert _art_files(stick) == set()


def test_a_changed_cover_is_rewritten(tmp_path: Path) -> None:
    stick = tmp_path / "stick"
    stick.mkdir()
    t = _track(tmp_path, "T0", RED)
    _sync(tmp_path, stick, [t])

    (Path(t["path"]).parent / "cover.jpg").write_bytes(_jpeg(BLUE))
    _sync(tmp_path, stick, [t])

    _id, rel = _covers(stick)["T0"]
    assert _close(_color_of((stick / rel.lstrip("/")).read_bytes()), BLUE)


def test_an_unchanged_cover_is_not_rewritten(tmp_path: Path, monkeypatch) -> None:
    stick = tmp_path / "stick"
    stick.mkdir()
    tracks = [_track(tmp_path, "T0", RED), _track(tmp_path, "T1", GREEN)]
    _sync(tmp_path, stick, tracks)

    def no_resize(*_a, **_k):
        raise AssertionError("identical source re-encoded")

    monkeypatch.setattr(usb_artwork, "_resize_to_jpeg", no_resize)
    _sync(tmp_path, stick, tracks)

    assert all(path for _id, path in _covers(stick).values())


# ---------------------------------------------------------------------------
# usb_artwork helpers
# ---------------------------------------------------------------------------


def test_files_without_a_manifest_entry_are_rewritten_once(tmp_path: Path) -> None:
    """A stick from before the manifest: its files say nothing about their source."""
    t = _track(tmp_path, "T0", BLUE)
    pioneer = tmp_path / "stick" / "PIONEER"
    bucket = pioneer / "Artwork" / "00001"
    bucket.mkdir(parents=True)
    for name in ("a1.jpg", "a1_m.jpg", "b1.jpg", "b1_m.jpg"):
        (bucket / name).write_bytes(_jpeg(RED, 80))
    manifest: dict[str, str] = {}

    assert usb_artwork.write_artwork_pair(Path(t["path"]), 1, pioneer, manifest)

    assert _close(_color_of((bucket / "a1.jpg").read_bytes()), BLUE)
    assert set(manifest) == {"1"}


def test_prune_touches_only_dead_artwork(tmp_path: Path) -> None:
    pioneer = tmp_path / "PIONEER"
    art = pioneer / "Artwork"
    for rel in (
        "00001/a1.jpg",
        "00001/b1_m.jpg",
        "00001/a2.jpg",  # dead id
        "00002/a25.jpg",  # dead id, whole bucket goes
        "00000/a3.jpg",  # live id 3 in the old id//1000 bucket
        "00001/a3.jpg",
        "00001/notes.txt",
        "custom/a9.jpg",
    ):
        (art / rel).parent.mkdir(parents=True, exist_ok=True)
        (art / rel).write_bytes(b"x")
    manifest = {"1": "d1", "2": "d2", "3": "d3", "junk": "x"}

    removed = usb_artwork.prune_artwork(pioneer, {1, 3}, manifest)

    left = {str(p.relative_to(art)).replace("\\", "/") for p in art.rglob("*") if p.is_file()}
    assert left == {
        "00001/a1.jpg",
        "00001/b1_m.jpg",
        "00001/a3.jpg",
        "00001/notes.txt",
        "custom/a9.jpg",
    }
    assert removed == 3
    assert not (art / "00002").exists() and not (art / "00000").exists()
    assert manifest == {"1": "d1", "3": "d3"}


def test_manifest_roundtrip_and_garbage(tmp_path: Path) -> None:
    pioneer = tmp_path / "PIONEER"
    usb_artwork.save_manifest(pioneer, {"1": "abc"})
    assert usb_artwork.load_manifest(pioneer) == {"1": "abc"}

    (pioneer / "Artwork" / usb_artwork.MANIFEST_NAME).write_text("{not json", encoding="utf-8")
    assert usb_artwork.load_manifest(pioneer) == {}
