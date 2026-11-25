"""Unit tests for `app.logging_utils.RedactingFormatter`.

Covers the four behaviors required by
`docs/research/research/evaluated_security-error-handler-exc-info-leak.md`:

1. `exc_info` traceback scrubbed end-to-end.
2. Chained exception ("During handling of the above") preserves chain
   markers while scrubbing both frames.
3. `args`-style interpolation (`logger.error("path=%s", APP_DIR)`)
   produces a scrubbed final string.
4. Non-exception log lines are byte-identical to a plain `Formatter`
   (modulo the always-on scrub pass, which is a no-op on path-free input).
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import sys
from pathlib import Path

import pytest

from app.logging_utils import RedactingFormatter, safe_error_message_str

_APP_DIR = os.path.dirname(os.path.abspath(__import__("app").__file__))
_FMT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


@pytest.fixture()
def stream_logger() -> tuple[logging.Logger, io.StringIO]:
    """Yield a freshly configured logger + the StringIO its handler writes to.

    Each test gets its own logger name so handlers don't accumulate
    across the suite.
    """
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(RedactingFormatter(fmt=_FMT))

    # Unique logger per call avoids handler bleed across tests; setting
    # propagate=False keeps the root logger (which test harness may
    # configure with its own handlers) out of the captured stream.
    logger = logging.getLogger(f"test_logging_redaction.{id(buf)}")
    logger.setLevel(logging.DEBUG)
    logger.handlers = [handler]
    logger.propagate = False
    return logger, buf


def test_exc_info_traceback_scrubbed(stream_logger: tuple[logging.Logger, io.StringIO]) -> None:
    logger, buf = stream_logger
    try:
        raise ValueError(f"bad path: {_APP_DIR}/foo.py")
    except ValueError:
        logger.error("boom", exc_info=True)

    out = buf.getvalue()
    assert "[...]" in out, f"expected '[...]' marker in {out!r}"
    assert _APP_DIR not in out, f"APP_DIR leaked into log output: {out!r}"
    # Traceback structure preserved (header line present).
    assert "Traceback (most recent call last)" in out


def test_chained_exception_preserves_chain_marker(
    stream_logger: tuple[logging.Logger, io.StringIO],
) -> None:
    logger, buf = stream_logger
    try:
        try:
            raise OSError(f"primary {_APP_DIR}/inner.py")
        except OSError as inner:
            raise RuntimeError(f"wrap {_APP_DIR}/outer.py") from inner
    except RuntimeError:
        logger.error("wrapped", exc_info=True)

    out = buf.getvalue()
    # "During handling of the above" appears only when chained via implicit
    # __context__; "direct cause" appears when chained via `from`. We use
    # `from`, so expect the direct-cause marker.
    assert (
        "The above exception was the direct cause" in out or "During handling of the above" in out
    ), f"chain marker missing in {out!r}"
    assert _APP_DIR not in out, f"APP_DIR leaked through chained traceback: {out!r}"
    assert "[...]" in out


def test_args_interpolation_scrubbed(stream_logger: tuple[logging.Logger, io.StringIO]) -> None:
    logger, buf = stream_logger
    logger.error("path=%s", _APP_DIR)

    out = buf.getvalue()
    assert _APP_DIR not in out, f"args path leaked: {out!r}"
    assert "path=[...]" in out, f"expected scrubbed path interpolation in {out!r}"


def test_data_dir_prefixes_scrubbed() -> None:
    """EXPORT/MUSIC/TEMP dirs (resolved once at import) must also be scrubbed,
    not just the app dir — a leaked export path discloses the user's library."""
    from app.config import EXPORT_DIR, MUSIC_DIR

    for root in (EXPORT_DIR, MUSIC_DIR):
        leaked = f"failed to write {root.resolve()}/sub/file.dat"
        out = safe_error_message_str(leaked)
        assert str(root.resolve()) not in out, f"data dir leaked: {out!r}"
        assert "[...]" in out


def test_safe_error_message_str_noop_on_clean_input() -> None:
    assert safe_error_message_str("no paths here") == "no paths here"
    assert safe_error_message_str("") == ""


def test_non_exception_log_format_unchanged() -> None:
    """A path-free `logger.info("hello")` must be byte-identical via
    `RedactingFormatter` vs a plain `Formatter` — the scrub is a no-op
    when no sensitive prefix appears.
    """
    record = logging.LogRecord(
        name="probe",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello",
        args=(),
        exc_info=None,
    )

    plain = logging.Formatter(fmt=_FMT).format(record)
    redacted = RedactingFormatter(fmt=_FMT).format(record)
    assert (
        plain == redacted
    ), f"non-exception format diverged:\n  plain={plain!r}\n  redacted={redacted!r}"


def test_allowed_roots_boot_line_hides_user_paths() -> None:
    """The boot line used to log the list repr: doubled backslashes beat the scrub."""
    from pathlib import Path

    from app.main import _describe_roots

    home = Path.home()
    line = _describe_roots([home / "Music", Path(os.environ.get("APPDATA") or home) / "x"])
    assert str(home) not in line
    assert line.count("[...]") == 2
    assert "\\\\" not in line


# --- every spelling of a user path (PC test 2026-11-22) -----------------------
#
# The scrub used to be a plain `str.replace` of the exact prefix. Forward-slash
# library paths (1791 of 5037 in a real library), URL-encoded query strings in
# uvicorn access lines, doubled backslashes from a list repr and UNC paths all
# reached the logs with the account name.


def _home() -> str:
    return str(Path.home())


def _spellings(home: str) -> dict[str, str]:
    from urllib.parse import quote

    music = home + os.sep + "Music" + os.sep + "Some Track.flac"
    out = {
        "native": music,
        "forward slashes": music.replace("\\", "/"),
        "upper case": music.upper(),
        "lower case": music.lower(),
        "percent-encoded": "GET /api/stream?path=" + quote(music, safe="") + " HTTP/1.1",
        "percent-encoded, slashes kept": "/api/x?path=" + quote(music.replace("\\", "/")),
        "list repr": repr([music]),
        "json": json.dumps({"path": music}),
    }
    if re.match(r"^[A-Za-z]:", home):
        bs = "\\"
        out["unc admin share"] = (
            bs * 2 + "localhost" + bs + home.replace(":", "$", 1) + bs + "Music"
        )
        out["long path"] = bs * 2 + "?" + bs + home + bs + "Music"
    return out


@pytest.mark.parametrize("name", list(_spellings(str(Path.home()))))
def test_every_spelling_of_the_home_path_is_scrubbed(name: str) -> None:
    text = _spellings(_home())[name]
    out = safe_error_message_str(text)
    user = Path.home().name
    assert "[...]" in out, out
    assert user.lower() not in out.lower().replace("[...]", ""), f"{name}: {out!r}"


def test_a_longer_name_sharing_the_prefix_is_left_alone() -> None:
    other = _home() + "x" + os.sep + "Music"
    assert safe_error_message_str(other) == other


def test_text_after_the_prefix_survives() -> None:
    out = safe_error_message_str(_home().replace("\\", "/") + "/Music/a.flac?x=1")
    assert out == "[...]/Music/a.flac?x=1"


# --- uvicorn's own loggers -----------------------------------------------------


def test_uvicorn_access_line_is_scrubbed() -> None:
    from urllib.parse import quote

    from app.logging_utils import RedactingUvicornAccessFormatter

    fmt = RedactingUvicornAccessFormatter(
        fmt='%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False
    )
    path = "/api/stream?path=" + quote(_home() + os.sep + "Music" + os.sep + "a.flac", safe="")
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:5000", "GET", path, "1.1", 200),
        None,
    )
    out = fmt.format(record)
    assert "GET /api/stream?path=[...]" in out
    assert Path.home().name.lower() not in out.lower().replace("[...]", "")


def test_uvicorn_error_traceback_is_scrubbed() -> None:
    from app.logging_utils import RedactingUvicornDefaultFormatter

    fmt = RedactingUvicornDefaultFormatter(fmt="%(levelprefix)s %(message)s", use_colors=False)
    try:
        raise RuntimeError("boom in " + _home() + os.sep + "app" + os.sep + "main.py")
    except RuntimeError:
        record = logging.LogRecord(
            "uvicorn.error",
            logging.ERROR,
            __file__,
            1,
            "Exception in ASGI application",
            (),
            sys.exc_info(),
        )
    out = fmt.format(record)
    assert "Exception in ASGI application" in out
    assert _home() not in out
    assert record.exc_text is not None and _home() not in record.exc_text


def test_uvicorn_log_config_is_a_valid_dict_config() -> None:
    import logging.config

    from app.logging_utils import (
        RedactingUvicornAccessFormatter,
        RedactingUvicornDefaultFormatter,
        uvicorn_log_config,
    )

    config = uvicorn_log_config()
    assert config["formatters"]["default"]["()"] is RedactingUvicornDefaultFormatter
    assert config["formatters"]["access"]["()"] is RedactingUvicornAccessFormatter
    saved = {
        n: (logging.getLogger(n).handlers[:], logging.getLogger(n).propagate)
        for n in ("uvicorn", "uvicorn.access", "uvicorn.error")
    }
    try:
        logging.config.dictConfig(config)
        handler = logging.getLogger("uvicorn.access").handlers[0]
        assert isinstance(handler.formatter, RedactingUvicornAccessFormatter)
    finally:
        for n, (handlers, propagate) in saved.items():
            logging.getLogger(n).handlers = handlers
            logging.getLogger(n).propagate = propagate


def test_sidecar_entry_point_passes_the_log_config(monkeypatch) -> None:
    import uvicorn

    import backend_entry

    seen: dict = {}
    monkeypatch.setattr(uvicorn, "run", lambda *a, **k: seen.update(k))
    backend_entry.main()
    assert seen["log_config"]["formatters"]["access"]["()"].__name__.startswith("Redacting")
