"""GET /api/usb/devices without a stick took 4.2-4.9 s per call (PC test 2026-11-22).

cProfile: 99 % of `UsbDetector._scan_uncached` sat in `_get_bus_types` — two
PowerShell starts (Get-Disk + Get-Partition) on every scan. The bus type is now
read per drive through IOCTL_STORAGE_QUERY_PROPERTY, and only for fixed drives
that hold a PIONEER folder; PowerShell stays as the fallback.

GET /api/usb/profiles took 6.8-7.6 s: the scan cache was stamped before the scan,
so a 4 s scan was stale on arrival, and the profiles read scanned twice (prune +
connected flag). Parallel callers each ran their own scan.

Drives are faked (kernel32 stub, tmp folders); nothing is written to a real drive.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import usb_manager
from app.usb_manager import UsbDetector, UsbProfileManager

DEVICE_KEYS = {
    "device_id",
    "drive",
    "label",
    "serial",
    "filesystem",
    "is_rekordbox",
    "is_writable",
    "has_legacy_pdb",
    "has_export_db",
    "track_count",
    "total_space",
    "used_space",
    "free_space",
}


@pytest.fixture
def fake_drives(monkeypatch, tmp_path: Path):
    """Kernel32 stub: every drive is FIXED (3) — the case that needs the bus check."""
    types: dict[str, int] = {}

    kernel32 = SimpleNamespace(
        GetDriveTypeW=lambda d: types.get(d, 3),
        SetThreadErrorMode=lambda *_a: 0,
    )
    monkeypatch.setattr(usb_manager, "_windll", SimpleNamespace(kernel32=kernel32), raising=False)
    monkeypatch.setattr(
        UsbDetector,
        "_get_volume_info",
        staticmethod(lambda d: {"label": "STICK", "serial": 1234, "filesystem": "FAT32"}),
    )
    monkeypatch.setattr(
        UsbDetector,
        "_get_drive_size",
        staticmethod(lambda d: {"total": 1000, "used": 400, "free": 600}),
    )

    def no_powershell():
        raise AssertionError("PowerShell bus query must not run")

    monkeypatch.setattr(UsbDetector, "_get_bus_types", staticmethod(no_powershell))
    monkeypatch.setattr(UsbDetector, "_scan_cache", None)
    return types


def _drive(tmp_path: Path, name: str, rekordbox: bool) -> str:
    root = tmp_path / name
    root.mkdir()
    if rekordbox:
        (root / "PIONEER" / "rekordbox").mkdir(parents=True)
    return str(root) + "\\"


def test_no_stick_scan_never_asks_for_bus_types(fake_drives, monkeypatch, tmp_path) -> None:
    drives = [_drive(tmp_path, "c", False), _drive(tmp_path, "d", False)]
    monkeypatch.setattr(UsbDetector, "_get_removable_drives", staticmethod(lambda: drives))

    def no_ioctl(_d):
        raise AssertionError("no fixed drive with a PIONEER folder — no bus lookup")

    monkeypatch.setattr(usb_manager, "_bus_type_ioctl", no_ioctl)

    assert UsbDetector._scan_uncached() == []


def test_fixed_usb_drive_with_rekordbox_is_listed(fake_drives, monkeypatch, tmp_path) -> None:
    drive = _drive(tmp_path, "e", True)
    monkeypatch.setattr(usb_manager, "_bus_type_ioctl", lambda d: "USB")

    dev = UsbDetector._probe_drive(drive, {})

    assert dev is not None
    assert set(dev) == DEVICE_KEYS
    assert dev["is_rekordbox"] is True
    assert dev["label"] == "STICK"
    assert not (Path(drive) / ".rbep_write_test").exists()


def test_fixed_internal_disk_with_pioneer_folder_is_skipped(
    fake_drives, monkeypatch, tmp_path
) -> None:
    drive = _drive(tmp_path, "c", True)
    monkeypatch.setattr(usb_manager, "_bus_type_ioctl", lambda d: "NVMe")

    assert UsbDetector._probe_drive(drive, {}) is None


def test_powershell_is_the_fallback_when_the_ioctl_fails(
    fake_drives, monkeypatch, tmp_path
) -> None:
    drive = _drive(tmp_path, "e", True)
    monkeypatch.setattr(usb_manager, "_bus_type_ioctl", lambda d: None)
    calls: list[int] = []

    def powershell():
        calls.append(1)
        return {drive: "USB"}

    monkeypatch.setattr(UsbDetector, "_get_bus_types", staticmethod(powershell))

    assert UsbDetector._probe_drive(drive, {}) is not None
    assert calls == [1]


def test_removable_drive_needs_no_bus_lookup(fake_drives, monkeypatch, tmp_path) -> None:
    drive = _drive(tmp_path, "f", False)
    fake_drives[drive] = 2  # DRIVE_REMOVABLE

    def no_ioctl(_d):
        raise AssertionError("removable drives are listed without a bus check")

    monkeypatch.setattr(usb_manager, "_bus_type_ioctl", no_ioctl)

    dev = UsbDetector._probe_drive(drive, {})
    assert dev is not None and set(dev) == DEVICE_KEYS and dev["is_rekordbox"] is False


@pytest.mark.parametrize("bad", ["", "not a drive", "C:\\x;rm", "CD:"])
def test_ioctl_refuses_anything_but_a_drive_letter(bad: str) -> None:
    assert usb_manager._bus_type_ioctl(bad) is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows volume IOCTL")
def test_ioctl_reads_the_system_drive() -> None:
    system = Path(sys.executable).drive + "\\"
    assert usb_manager._bus_type_ioctl(system) in set(usb_manager._STORAGE_BUS_NAMES.values())


# ---------------------------------------------------------------------------
# Scan cache + the profiles read
# ---------------------------------------------------------------------------


@pytest.fixture
def counted_scan(monkeypatch):
    """`_scan_uncached` replaced by a counter; the cache starts empty."""
    calls: list[int] = []

    def fake(cls):
        calls.append(1)
        return [{"device_id": "dev1", "drive": "E:", "label": "STICK"}]

    monkeypatch.setattr(UsbDetector, "_scan_uncached", classmethod(fake))
    monkeypatch.setattr(UsbDetector, "_scan_cache", None)
    return calls


def test_a_slow_scan_is_not_stale_on_arrival(monkeypatch) -> None:
    clock = [100.0]
    calls: list[int] = []

    def slow(cls):
        calls.append(1)
        clock[0] += 4.5  # longer than the 3 s TTL
        return []

    monkeypatch.setattr(usb_manager.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(UsbDetector, "_scan_uncached", classmethod(slow))
    monkeypatch.setattr(UsbDetector, "_scan_cache", None)

    UsbDetector.scan()
    clock[0] += 0.5
    UsbDetector.scan()

    assert calls == [1]


def test_parallel_callers_share_one_scan(monkeypatch) -> None:
    calls: list[int] = []

    def slow(cls):
        calls.append(1)
        time.sleep(0.2)
        return []

    monkeypatch.setattr(UsbDetector, "_scan_uncached", classmethod(slow))
    monkeypatch.setattr(UsbDetector, "_scan_cache", None)
    threads = [threading.Thread(target=UsbDetector.scan) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert calls == [1]


def test_profiles_read_scans_once_and_flags_connected(counted_scan, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(usb_manager, "PROFILES_FILE", tmp_path / "usb_profiles.json")
    UsbProfileManager.save_profile({"device_id": "dev1", "drive": "E:", "label": "STICK"})
    UsbProfileManager.save_profile({"device_id": "dev2", "drive": "F:", "label": "OLD"})
    monkeypatch.setattr(UsbDetector, "_SCAN_TTL_SEC", 0.0)  # no cache to hide a second scan

    profiles = {p["device_id"]: p for p in UsbProfileManager.get_profiles()}

    assert counted_scan == [1]
    assert profiles["dev1"]["connected"] is True
    assert profiles["dev2"]["connected"] is False
