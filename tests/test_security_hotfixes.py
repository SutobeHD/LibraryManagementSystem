"""Regression tests for the 5 security hotfixes in commit e3a5ae8.

Each section maps 1:1 to one finding in the commit body of
`fix(security): hotfixes from auth-hardening audit (5 findings)`.

We avoid `fastapi.testclient.TestClient` because the installed pair
(fastapi 0.109 + httpx 0.28) is incompatible — TestClient passes the
deprecated ``app=`` kwarg to httpx.Client. Instead we drive the ASGI
app directly via ``httpx.ASGITransport``, which is the supported path
on this stack and additionally lets us spoof the remote client tuple
(``client=("ip", port)``) so we can exercise the loopback gate in
finding #2 without monkey-patching the route.
"""
from __future__ import annotations

import asyncio
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from app.main import ALLOWED_AUDIO_ROOTS, SHUTDOWN_TOKEN, app, validate_audio_path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _post(
    url: str,
    json: dict | None = None,
    *,
    client: tuple[str, int] = ("127.0.0.1", 12345),
) -> httpx.Response:
    """Synchronous POST against the ASGI app with a controllable client tuple.

    ``raise_app_exceptions=False`` keeps app-level exceptions inside the
    middleware stack so the global exception handler can convert them to
    a 500 — same behaviour the live uvicorn server gives.
    """
    async def _go() -> httpx.Response:
        transport = httpx.ASGITransport(
            app=app, client=client, raise_app_exceptions=False,
        )
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as ac:
            return await ac.post(url, json=json)

    return asyncio.run(_go())


@pytest.fixture
def sandbox_root(tmp_path: Path) -> Iterator[Path]:
    """Add a temp dir to ALLOWED_AUDIO_ROOTS for one test, then remove it."""
    root = (tmp_path / "lib").resolve()
    root.mkdir()
    ALLOWED_AUDIO_ROOTS.append(root)
    try:
        yield root
    finally:
        # Pop the exact instance we added (don't disturb the module's defaults).
        try:
            ALLOWED_AUDIO_ROOTS.remove(root)
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# Finding 1: duplicate heartbeat handler removed
# ---------------------------------------------------------------------------


class TestNoDuplicateHeartbeatRoute:
    def test_only_one_heartbeat_route_registered(self) -> None:
        matches = [
            r for r in app.routes
            if getattr(r, "path", None) == "/api/system/heartbeat"
            and "POST" in getattr(r, "methods", set())
        ]
        assert len(matches) == 1, (
            f"Expected exactly one POST /api/system/heartbeat, "
            f"found {len(matches)}: {matches!r}"
        )


# ---------------------------------------------------------------------------
# Finding 2: SHUTDOWN_TOKEN gated to loopback
# ---------------------------------------------------------------------------


class TestHeartbeatTokenGate:
    def test_loopback_caller_receives_token(self) -> None:
        r = _post("/api/system/heartbeat", client=("127.0.0.1", 5555))
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "alive"
        assert body.get("token") == SHUTDOWN_TOKEN

    def test_ipv6_loopback_receives_token(self) -> None:
        r = _post("/api/system/heartbeat", client=("::1", 5555))
        assert r.status_code == 200
        assert r.json().get("token") == SHUTDOWN_TOKEN

    @pytest.mark.parametrize(
        "remote_ip",
        ["192.168.1.42", "10.0.0.5", "172.16.0.1", "8.8.8.8"],
    )
    def test_non_loopback_caller_does_not_receive_token(self, remote_ip: str) -> None:
        r = _post("/api/system/heartbeat", client=(remote_ip, 5555))
        assert r.status_code == 200
        body = r.json()
        assert body == {"status": "alive"}
        assert "token" not in body


# ---------------------------------------------------------------------------
# Finding 3: validate_audio_path uses Path.is_relative_to (no prefix bug)
# ---------------------------------------------------------------------------


class TestValidateAudioPathSandbox:
    def test_valid_audio_file_inside_root_accepted(
        self, sandbox_root: Path
    ) -> None:
        mp3 = sandbox_root / "song.mp3"
        mp3.write_bytes(b"\x00")  # 1 byte; we never decode
        result = validate_audio_path(str(mp3))
        assert result == mp3.resolve()

    def test_sibling_root_with_shared_prefix_is_rejected(
        self, tmp_path: Path
    ) -> None:
        """Regression: the str.startswith bug accepted '<root>_evil' as inside '<root>'."""
        good_root = (tmp_path / "lib").resolve()
        evil_root = (tmp_path / "lib_evil").resolve()
        good_root.mkdir()
        evil_root.mkdir()
        ALLOWED_AUDIO_ROOTS.append(good_root)
        try:
            evil_file = evil_root / "pwned.mp3"
            evil_file.write_bytes(b"\x00")
            with pytest.raises(Exception) as exc_info:
                validate_audio_path(str(evil_file))
            # HTTPException with status 403
            assert getattr(exc_info.value, "status_code", None) == 403
        finally:
            ALLOWED_AUDIO_ROOTS.remove(good_root)

    def test_path_outside_roots_rejected(
        self, tmp_path: Path, sandbox_root: Path
    ) -> None:
        # File exists, audio extension, but outside any allowed root and not
        # in db.tracks.
        outside = (tmp_path / "elsewhere").resolve()
        outside.mkdir()
        rogue = outside / "rogue.mp3"
        rogue.write_bytes(b"\x00")
        with pytest.raises(Exception) as exc_info:
            validate_audio_path(str(rogue))
        assert getattr(exc_info.value, "status_code", None) == 403

    def test_non_audio_extension_rejected(self, sandbox_root: Path) -> None:
        txt = sandbox_root / "note.txt"
        txt.write_bytes(b"hi")
        with pytest.raises(Exception) as exc_info:
            validate_audio_path(str(txt))
        assert getattr(exc_info.value, "status_code", None) == 400


# ---------------------------------------------------------------------------
# Finding 4: /api/debug/load_xml gated behind env flag
# ---------------------------------------------------------------------------


class TestDebugLoadXmlGate:
    def test_disabled_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LMS_ENABLE_DEBUG_ROUTES", raising=False)
        r = _post("/api/debug/load_xml")
        assert r.status_code == 404

    def test_disabled_when_flag_not_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LMS_ENABLE_DEBUG_ROUTES", "0")
        r = _post("/api/debug/load_xml")
        assert r.status_code == 404

    def test_enabled_when_flag_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LMS_ENABLE_DEBUG_ROUTES", "1")
        r = _post("/api/debug/load_xml")
        # Contract under test: the env-flag gate is REMOVED, so the route is
        # no longer a hard 404. What happens past the gate is downstream
        # behaviour we don't pin here — in the current build `db` is the
        # live RekordboxDB which has no load_xml() method, so the handler
        # raises AttributeError and the global exception middleware maps
        # it to a 500. Either 200 (if a future build wires it up) or 500
        # (today) proves the gate was passed; 404 would mean the env-flag
        # check is still blocking.
        assert r.status_code != 404
        assert r.status_code in (200, 500)


# ---------------------------------------------------------------------------
# Finding 5: /api/file/write sandboxed to ALLOWED_AUDIO_ROOTS + ext allow-list
# ---------------------------------------------------------------------------


class TestFileWriteSandbox:
    def test_write_inside_root_with_allowed_extension(
        self, sandbox_root: Path
    ) -> None:
        target = sandbox_root / "project.rbep"
        payload = {"path": str(target), "content": "hello"}
        r = _post("/api/file/write", json=payload)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "success"
        assert Path(body["path"]).read_text(encoding="utf-8") == "hello"

    def test_write_outside_roots_forbidden(self, tmp_path: Path) -> None:
        # tmp_path is NOT in ALLOWED_AUDIO_ROOTS for this test.
        target = tmp_path / "escape.rbep"
        payload = {"path": str(target), "content": "pwn"}
        r = _post("/api/file/write", json=payload)
        assert r.status_code == 403
        assert not target.exists()

    @pytest.mark.parametrize("ext", [".exe", ".py", ".dll", ".bat", ".ps1"])
    def test_write_forbidden_extension_rejected(
        self, sandbox_root: Path, ext: str
    ) -> None:
        target = sandbox_root / f"payload{ext}"
        r = _post(
            "/api/file/write",
            json={"path": str(target), "content": "evil"},
        )
        assert r.status_code == 400
        assert not target.exists()

    @pytest.mark.parametrize(
        "ext",
        [".rbep", ".json", ".txt", ".cue", ".m3u", ".m3u8"],
    )
    def test_all_allow_listed_extensions_accepted(
        self, sandbox_root: Path, ext: str
    ) -> None:
        target = sandbox_root / f"file{ext}"
        r = _post(
            "/api/file/write",
            json={"path": str(target), "content": "ok"},
        )
        assert r.status_code == 200, r.text
        assert target.read_text(encoding="utf-8") == "ok"
