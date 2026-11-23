"""Settings files on an initialized stick (PC test 2026-11-22).

`POST /api/usb/initialize` wrote DEVSETTING / MYSETTING / MYSETTING2 / DJMMYSETTING
as zero bytes, and the sync's seeding skipped them because they existed, so an
initialized stick kept empty settings forever. Initialize now writes the same valid
defaults the sync seeds; the seeding replaces a blank file and never a real one.

Sticks are folders under `tmp_path`; no real drive is touched.
"""

from __future__ import annotations

import asyncio
import struct
from pathlib import Path

import httpx
import pytest

from app import usb_mysettings as ms
from app.main import app
from app.usb_manager import UsbDetector, UsbSyncEngine

pyrb = pytest.importorskip("pyrekordbox")
from pyrekordbox.mysettings.file import crc16xmodem  # noqa: E402

NAMES = ("DEVSETTING.DAT", "MYSETTING.DAT", "MYSETTING2.DAT", "DJMMYSETTING.DAT")
ZERO_SIZES = {
    "DEVSETTING.DAT": 140,
    "MYSETTING.DAT": 148,
    "MYSETTING2.DAT": 148,
    "DJMMYSETTING.DAT": 160,
}


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    import time

    monkeypatch.setattr(time, "sleep", lambda _s: None)


def _post(url: str, headers: dict[str, str], body: dict) -> httpx.Response:
    async def _go() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            return await ac.post(url, json=body, headers=headers)

    return asyncio.run(_go())


def _assert_valid(pioneer: Path) -> None:
    for name in NAMES:
        data = (pioneer / name).read_bytes()
        assert data.strip(b"\x00"), f"{name} is blank"
        cls = pyrb.mysettings.file.FILES[name]
        cls.parse(data)  # header constants + structure


def _zero_stick(root: Path) -> Path:
    pioneer = root / "PIONEER"
    pioneer.mkdir(parents=True)
    for name, size in ZERO_SIZES.items():
        (pioneer / name).write_bytes(b"\x00" * size)
    return pioneer


def test_crc16_xmodem_check_value() -> None:
    assert ms._crc16_xmodem(b"123456789") == 0x31C3


def test_devsetting_layout() -> None:
    data = ms.build_devsetting()
    assert len(data) == ms.DEVSETTING_SIZE == 140
    assert struct.unpack_from("<I", data, 0)[0] == 0x60
    assert data[4:36].rstrip(b"\x00") == b"PIONEER DJ"
    assert data[36:68].rstrip(b"\x00") == b"rekordbox"
    assert struct.unpack_from("<I", data, 100)[0] == 32
    body = data[104:136]
    assert body[:9] == bytes.fromhex("785634120100000001")
    crc, tail = struct.unpack_from("<HH", data, 136)
    assert crc == crc16xmodem(body) and tail == 0
    pyrb.DevSettingFile.parse(data)


def test_initialize_route_writes_valid_settings(tmp_path: Path, auth_token) -> None:
    stick = tmp_path / "stick"
    stick.mkdir()

    r = _post("/api/usb/initialize", auth_token, {"drive": str(stick)})

    assert r.status_code == 200, r.text
    assert (stick / "PIONEER" / "rekordbox").is_dir()
    _assert_valid(stick / "PIONEER")


def test_initialize_keeps_real_settings(tmp_path: Path) -> None:
    pioneer = tmp_path / "PIONEER"
    pioneer.mkdir()
    custom = pyrb.MySettingFile()
    custom.set("auto_cue", "off")
    mine = custom.build()
    (pioneer / "MYSETTING.DAT").write_bytes(mine)

    assert UsbDetector.initialize_usb(str(tmp_path))

    assert (pioneer / "MYSETTING.DAT").read_bytes() == mine
    _assert_valid(pioneer)


def test_seed_replaces_zero_filled_files(tmp_path: Path) -> None:
    pioneer = _zero_stick(tmp_path)

    written = ms.write_defaults(tmp_path)

    assert set(written) == {"DEVSETTING", "MYSETTING", "MYSETTING2", "DJMMYSETTING"}
    _assert_valid(pioneer)


def test_seed_never_overwrites_real_files(tmp_path: Path) -> None:
    ms.write_defaults(tmp_path)
    pioneer = tmp_path / "PIONEER"
    before = {n: (pioneer / n).read_bytes() for n in NAMES}

    assert ms.write_defaults(tmp_path) == {}
    assert {n: (pioneer / n).read_bytes() for n in NAMES} == before


def test_seed_keeps_a_file_it_cannot_judge(tmp_path: Path) -> None:
    """Non-zero bytes are somebody's settings, even when we cannot parse them."""
    pioneer = tmp_path / "PIONEER"
    pioneer.mkdir()
    odd = b"\x01" + b"\x00" * 139
    (pioneer / "DEVSETTING.DAT").write_bytes(odd)

    ms.write_defaults(tmp_path)

    assert (pioneer / "DEVSETTING.DAT").read_bytes() == odd


def test_sync_structure_repairs_a_stick_initialized_by_the_old_code(tmp_path: Path) -> None:
    pioneer = _zero_stick(tmp_path)
    engine = UsbSyncEngine(str(tmp_path / "local.db"), str(tmp_path), filesystem="NTFS")

    engine._ensure_usb_structure()

    _assert_valid(pioneer)
