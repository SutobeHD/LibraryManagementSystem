"""Pytest fixtures shared across the suite.

The headline export is the autouse ``auth_token`` fixture: it
monkeypatches ``app.auth.SESSION_TOKEN`` to a known constant **and**
exposes a ready-to-use ``Authorization: Bearer …`` header dict so
gated-route tests can stay short. The constant is identical across all
tests for the whole session, but ``monkeypatch.setattr`` reverts cleanly
between tests so a test that explicitly mutates the token (e.g. for the
constant-time-mismatch path in ``test_auth.py``) doesn't leak state.

Tests that need to exercise the **unauthenticated** path opt out with
``@pytest.mark.no_auth`` — the fixture skips the monkeypatch entirely
when that marker is present, so the boot-time token (set in
``app/auth.py`` during import) is the only thing in play and the test
can legitimately reach the 401 branch.

Phase-1 note: until Step 4 of the auth-hardening plan lands (bulk
``Depends(require_session)`` decoration of all mutation routes), this
fixture has **no observable effect on the existing test suite** — every
existing test hits routes that ignore the ``Authorization`` header. The
fixture is shipped early so Step 4 can land atomically against a
suite that already speaks Bearer.

Host isolation: before anything from ``app`` is imported, the per-user
directories (``APPDATA``, ``LOCALAPPDATA``, ``HOME``/``USERPROFILE``, the
XDG base dirs) are pointed at a throwaway sandbox and the keyring is
forced onto the ``fail`` backend. Without that, importing ``app.auth``
overwrites the real ``MusicLibraryManager/.session-token`` (a running dev
sidecar then answers 401 until restarted), ``auth.db`` opens in the real
user-data dir, and ``app.database.db`` binds to the host's real Rekordbox
``master.db``. ``LMS_TEST_SANDBOX=<dir>`` pins the sandbox root (same
layout as the external sandbox plugin); unset, a temp dir is created per
session and removed at exit.
"""

from __future__ import annotations

import atexit
import functools
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest


def _isolate_host_dirs() -> Path:
    """Redirect every per-user location the app resolves into a sandbox."""
    pinned = os.environ.get("LMS_TEST_SANDBOX")
    if pinned:
        root = Path(pinned)
    else:
        root = Path(tempfile.mkdtemp(prefix="lms-pytest-"))
        atexit.register(shutil.rmtree, root, ignore_errors=True)

    home = root / "home"
    dirs = {
        "APPDATA": root / "Roaming",
        "LOCALAPPDATA": root / "Local",
        "USERPROFILE": home,
        "HOME": home,
        "XDG_DATA_HOME": home / ".local" / "share",
        "XDG_CONFIG_HOME": home / ".config",
        "XDG_CACHE_HOME": home / ".cache",
        "XDG_STATE_HOME": home / ".local" / "state",
    }
    for key, path in dirs.items():
        path.mkdir(parents=True, exist_ok=True)
        os.environ[key] = str(path)
    # Tests that need a working keyring install their own backend in-test.
    os.environ["PYTHON_KEYRING_BACKEND"] = "keyring.backends.fail.Keyring"

    if sys.platform == "win32":
        # platformdirs resolves Windows folders through SHGetFolderPathW and
        # ignores the environment; swap in its env-var resolver.
        import platformdirs.windows as _pd_windows

        _pd_windows.get_win_folder = functools.lru_cache(maxsize=None)(
            _pd_windows.get_win_folder_from_env_vars
        )

    from platformdirs import user_data_dir

    resolved = Path(user_data_dir("MusicLibraryManager", appauthor=False, roaming=False))
    if not resolved.resolve().is_relative_to(root.resolve()):
        raise RuntimeError(
            f"test sandbox not applied: user_data_dir resolves to {resolved}, "
            f"outside {root} — refusing to run against the host's app data"
        )
    return root


TEST_SANDBOX_ROOT = _isolate_host_dirs()

# Importing this module at top-level triggers the boot-time token
# generation in ``app/auth.py`` (banner-emit + file-write side
# effects) — inside the sandbox set up above. The suite as a whole
# must boot the real auth module exactly once so the FastAPI app graph
# imports cleanly when individual tests pull in ``app.main``.
from app import auth as _auth  # noqa: E402

# Known constant the autouse fixture pins ``SESSION_TOKEN`` to. Length
# matches a real ``secrets.token_urlsafe(32)`` (~43 chars after b64url
# encoding) so any test that asserts header-length parity with the
# real token continues to hold. **Not** a real secret — this string
# only ever exists in the test process.
TEST_SESSION_TOKEN = "TEST_TOKEN_FIXTURE_VALUE_NOT_A_REAL_SECRET_X"


@pytest.fixture(autouse=True)
def auth_token(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, str]:
    """Pin ``app.auth.SESSION_TOKEN`` to ``TEST_SESSION_TOKEN`` for the test.

    Returns a header dict ``{"Authorization": "Bearer <token>"}`` that
    callers can splat into ``httpx.AsyncClient(headers=...)`` or any
    per-request ``headers=`` kwarg. The fixture is autouse so tests
    don't need to declare it explicitly; the return value is still
    available via ``request.getfixturevalue("auth_token")`` or by
    listing the fixture in the test signature.

    Tests marked ``@pytest.mark.no_auth`` get the **untouched**
    boot-time token instead — useful for asserting that the 401
    rejection actually fires against a randomly-generated value the
    test doesn't know.
    """
    if request.node.get_closest_marker("no_auth"):
        # Hand back the real boot-time token's header so the test can
        # opt back IN if it explicitly asks for it; but DON'T patch
        # the module constant — the test wants the genuine secret.
        return {"Authorization": f"Bearer {_auth.SESSION_TOKEN}"}

    monkeypatch.setattr(_auth, "SESSION_TOKEN", TEST_SESSION_TOKEN)
    return {"Authorization": f"Bearer {TEST_SESSION_TOKEN}"}


@pytest.fixture
def empty_library(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """Swap ``app.main.db`` for a library that knows no tracks.

    ``validate_audio_path`` admits a path outside ``ALLOWED_AUDIO_ROOTS``
    when it exact-matches a ``db.tracks`` entry; reading that property
    builds ``LiveRekordboxDB`` on whatever ``master.db`` the process found.
    Sandbox-rejection tests must not depend on that library's contents.
    """
    from app import main

    library = SimpleNamespace(tracks={})
    monkeypatch.setattr(main, "db", library)
    return library


def pytest_configure(config: pytest.Config) -> None:
    """Register the ``no_auth`` marker so ``--strict-markers`` is happy."""
    config.addinivalue_line(
        "markers",
        "no_auth: skip the auto-injected Bearer header so the test can "
        "exercise the unauthenticated request path against the real "
        "boot-time session token.",
    )
