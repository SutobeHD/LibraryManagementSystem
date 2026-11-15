"""Cover art for the USB stick, with the real Pillow (B8, 0.1 core-loop test).

Pillow was neither in requirements.txt nor in backend.spec, so every export logged
"Pillow not installed" and PIONEER/Artwork stayed empty.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from app import usb_artwork

Image = pytest.importorskip("PIL.Image")

ROOT = Path(__file__).resolve().parents[1]


def _png_with_alpha(size: tuple[int, int]) -> bytes:
    img = Image.new("RGBA", size, (200, 30, 30, 0))
    for x in range(size[0] // 4, size[0] // 2):
        for y in range(size[1] // 4, size[1] // 2):
            img.putpixel((x, y), (10, 200, 10, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _decode(data: bytes):
    return Image.open(io.BytesIO(data))


@pytest.mark.parametrize(
    ("size", "quality"),
    [
        (usb_artwork.SMALL_SIZE, usb_artwork.JPEG_QUALITY_SMALL),
        (usb_artwork.MEDIUM_SIZE, usb_artwork.JPEG_QUALITY_MEDIUM),
    ],
)
def test_resize_turns_any_image_into_a_bounded_rgb_jpeg(size, quality) -> None:
    out = usb_artwork._resize_to_jpeg(_png_with_alpha((1200, 900)), size, quality)

    assert out is not None
    img = _decode(out)
    assert img.format == "JPEG"
    assert img.mode == "RGB"
    assert img.width <= size[0] and img.height <= size[1]
    assert max(img.size) == max(size)  # aspect kept, longest side fills the box


def test_transparent_pixels_become_white_not_black() -> None:
    out = usb_artwork._resize_to_jpeg(_png_with_alpha((400, 400)), (80, 80), 90)
    corner = _decode(out).getpixel((2, 2))
    assert all(channel > 240 for channel in corner)


def test_garbage_bytes_are_refused_without_raising() -> None:
    assert usb_artwork._resize_to_jpeg(b"not an image", (80, 80), 80) is None


def test_write_artwork_pair_writes_both_cdj_variants(tmp_path: Path) -> None:
    album = tmp_path / "music" / "Album"
    album.mkdir(parents=True)
    audio = album / "track.mp3"
    audio.write_bytes(b"\xff\xfb" + b"\0" * 64)  # no embedded art: cover.jpg is used
    cover = io.BytesIO()
    Image.new("RGB", (700, 700), (20, 40, 160)).save(cover, format="JPEG")
    (album / "cover.jpg").write_bytes(cover.getvalue())
    pioneer = tmp_path / "stick" / "PIONEER"

    result = usb_artwork.write_artwork_pair(audio, 1, pioneer)

    assert result is not None
    small, medium = result
    # Bucket naming is an open registry todo (usb-artwork); only the pair is checked here.
    bucket = pioneer / "Artwork" / usb_artwork._bucket_for(1)
    assert (small, medium) == (bucket / "a1.jpg", bucket / "a1_m.jpg")
    assert _decode(small.read_bytes()).size == usb_artwork.SMALL_SIZE
    assert _decode(medium.read_bytes()).size == usb_artwork.MEDIUM_SIZE
    assert sorted(p.name for p in album.iterdir()) == ["cover.jpg", "track.mp3"]


def test_pillow_is_pinned_and_bundled() -> None:
    reqs = (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    pins = [line.strip() for line in reqs if line.strip().lower().startswith("pillow")]
    assert pins == ["Pillow==13.0.0"]
    spec = (ROOT / "backend.spec").read_text(encoding="utf-8")
    assert "_installed('PIL')" in spec  # the build refuses to run without Pillow
