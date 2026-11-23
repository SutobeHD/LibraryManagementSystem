"""POST /api/usb/profiles merges a partial body into the stored profile (PC test 2026-11-22).

`model_dump()` without `exclude_unset` filled every field the body left out with the
model default, so a rename (device_id + label only) reset drive, type, sync mode and
the playlist selection. The profile store is a file under `tmp_path`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from app import usb_manager
from app.main import app
from app.usb_manager import UsbProfileManager

FULL = {
    "device_id": "dev1",
    "label": "Club",
    "drive": "E:",
    "type": "SetStick",
    "sync_mode": "playlists_only",
    "sync_playlists": ["p1", "p2"],
    "auto_sync": True,
    "audio_format": "mp3",
    "audio_bitrate": "256",
    "audio_sample_rate": "48000",
    "sync_direction": "usb_main",
    "sync_mirrored": True,
    "sync_primary": "library_one",
    "library_types": ["library_one"],
}


@pytest.fixture(autouse=True)
def store(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "usb_profiles.json"
    monkeypatch.setattr(usb_manager, "PROFILES_FILE", path)
    monkeypatch.setattr(usb_manager.UsbDetector, "scan", classmethod(lambda cls: []))
    return path


def _post(headers: dict[str, str], body: dict) -> dict:
    async def _go() -> httpx.Response:
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            return await ac.post("/api/usb/profiles", json=body, headers=headers)

    r = asyncio.run(_go())
    assert r.status_code == 200, r.text
    return r.json()["profile"]


def test_partial_post_keeps_the_stored_fields(auth_token) -> None:
    _post(auth_token, FULL)

    out = _post(auth_token, {"device_id": "dev1", "label": "Renamed"})

    assert out["label"] == "Renamed"
    for key, value in FULL.items():
        if key != "label":
            assert out[key] == value, key
    assert UsbProfileManager.get_profile("dev1") == out


def test_new_profile_still_gets_the_defaults(auth_token) -> None:
    out = _post(auth_token, {"device_id": "fresh", "label": "New"})

    assert out["type"] == "Collection"
    assert out["sync_mode"] == "full"
    assert out["sync_playlists"] == []
    assert out["auto_sync"] is False
    assert out["audio_format"] == "original"
    assert out["sync_direction"] == "pc_main"
    assert out["drive"] is None


def test_full_object_from_the_ui_overwrites_everything(auth_token) -> None:
    _post(auth_token, FULL)
    changed = {
        **FULL,
        "type": "Collection",
        "sync_playlists": [],
        "sync_primary": None,
        "connected": True,  # the UI echoes the GET field back; ignored
    }

    out = _post(auth_token, changed)

    assert out["type"] == "Collection"
    assert out["sync_playlists"] == []
    assert out["sync_primary"] is None
    assert "connected" not in out


def test_partial_post_fills_defaults_an_old_profile_lacks(auth_token) -> None:
    UsbProfileManager.save_profile({"device_id": "old", "drive": "F:", "type": "SetStick"})

    out = _post(auth_token, {"device_id": "old", "label": "Old"})

    assert (out["drive"], out["type"], out["label"]) == ("F:", "SetStick", "Old")
    assert out["audio_format"] == "original"
