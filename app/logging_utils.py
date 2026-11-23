"""Log redaction helpers — scrub absolute paths from log lines + tracebacks.

`safe_error_message_str` is the string-input variant of `safe_error_message`
(`app/main.py`); the two share the replacement list so widening one widens both.

`RedactingFormatter` is the wire-time interception point: it overrides
`Formatter.format` so the persisted log line AND the cached
`LogRecord.exc_text` (used by sibling handlers per CPython
`Logger.callHandlers` iteration order) are both scrubbed.

Invariant: must be the formatter on EVERY handler attached to the root
logger; otherwise the first formatter to run populates `record.exc_text`
with raw paths, and any handler whose formatter doesn't also scrub the
cached string will leak them.

Do NOT flip `capture_locals=True` on `traceback.TracebackException`
anywhere without widening `safe_error_message_str` scope — locals freely
embed paths (e.g. `file_path` in `validate_audio_path`).
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any

from .config import EXPORT_DIR, MUSIC_DIR, TEMP_DIR

# Process-local app root; mirrors `APP_DIR` in `app/main.py` so both
# helpers strip the same install-layout prefix.
_APP_DIR = os.path.dirname(os.path.abspath(__file__))

# Resolved ONCE at import — the prefix set is process-stable, and these
# `.resolve()` calls hit the filesystem. Rebuilding the list per call meant a
# syscall per log line (RedactingFormatter.format runs for every record); a
# resolve() failure there would throw inside the log handler and drop the line.
_SENSITIVE_PREFIXES = [
    p
    for p in (
        _APP_DIR,
        str(Path.home()),
        os.environ.get("APPDATA", ""),
        str(EXPORT_DIR.resolve()),
        str(MUSIC_DIR.resolve()),
        str(TEMP_DIR.resolve()),
    )
    if p
]


# A path separator as it shows up in log text: "\" or "/", doubled by a
# repr / JSON dump, or percent-encoded in a URL query string.
_SEP = r"(?:\\{1,2}|/|%5[cC]|%2[fF])"
# Windows long-path / UNC spellings of a local drive: \\?\C:\..., \\localhost\C$\...
_UNC = r"(?:(?:\\{2,4}|//|(?:%5[cC]){2})(?:\?|localhost|127\.0\.0\.1)" + _SEP + r")?"
# What may follow a matched prefix: a separator or anything that ends a path
# token. Keeps "...\Users\tb" from matching inside "...\Users\tbone".
_END = r"(?=$|[\\/%\s'\":;,)\]}>|?&#])"


def _prefix_pattern(prefix: str) -> str:
    """Regex for one absolute path prefix in every spelling a log line can carry.

    The old plain `str.replace` only caught the exact spelling, so
    `C:/Users/<name>/Music/...` (1791 of 5037 library paths), a URL-encoded
    query string in a uvicorn access line, the doubled backslashes of a list
    repr and the UNC form all reached the logs with the account name in them.
    """
    parts = [part for part in re.split(r"[\\/]+", prefix) if part]
    if not parts:
        return ""
    head, *rest = parts
    if re.fullmatch(r"[A-Za-z]:", head):
        # "C:" as typed, "C$" in an admin share, "C%3A" percent-encoded
        first = re.escape(head[0]) + r"(?::|\$|%3[aA])"
        lead = _UNC
    else:
        first = re.escape(head)
        lead = _SEP if prefix[:1] in "\\/" else ""

    def component(text: str) -> str:
        return re.escape(text).replace(r"\ ", r"(?: |%20|\+)")

    body = _SEP.join([first, *(component(c) for c in rest)])
    return lead + body + _END


def _build_scrubber(prefixes: list[str]) -> re.Pattern[str] | None:
    patterns = [_prefix_pattern(p) for p in sorted(set(prefixes), key=len, reverse=True)]
    patterns = [p for p in patterns if p]
    return re.compile("|".join(patterns), re.IGNORECASE) if patterns else None


_SCRUBBER = _build_scrubber(_SENSITIVE_PREFIXES)


def safe_error_message_str(msg: str) -> str:
    """Strip absolute paths from a rendered log/error string.

    Operates on already-rendered text — call sites pass `str(exc)`,
    `Formatter.format` output, or `record.exc_text`. Replaces each
    sensitive prefix with ``[...]``, whatever the slash direction, case,
    doubling, percent-encoding or UNC spelling.
    """
    if not msg or _SCRUBBER is None:
        return msg
    return _SCRUBBER.sub("[...]", msg)


class RedactingFormatter(logging.Formatter):
    """`logging.Formatter` that scrubs paths from message + cached traceback.

    Override semantics:

    1. `super().format(record)` runs the standard pipeline, which (when
       `record.exc_info` is set) populates `record.exc_text` via
       `self.formatException(record.exc_info)` on the first formatter
       call across all handlers (CPython `Lib/logging/__init__.py`
       `Formatter.format`).
    2. We then mutate `record.exc_text` in place so any sibling handler
       whose formatter reuses the cache sees the scrubbed version.
    3. The returned string is scrubbed unconditionally so the calling
       handler's emit gets clean output regardless of what was cached.
    """

    def format(self, record: logging.LogRecord) -> str:
        s = super().format(record)
        if record.exc_text:
            record.exc_text = safe_error_message_str(record.exc_text)
        return safe_error_message_str(s)


def _redacting(base: type[logging.Formatter]) -> type[logging.Formatter]:
    """A subclass of `base` whose output and cached traceback are scrubbed."""

    class _Redacting(base):  # type: ignore[valid-type,misc]
        def format(self, record: logging.LogRecord) -> str:
            s = super().format(record)
            if record.exc_text:
                record.exc_text = safe_error_message_str(record.exc_text)
            return safe_error_message_str(s)

    _Redacting.__name__ = f"Redacting{base.__name__}"
    return _Redacting


def uvicorn_log_config() -> dict[str, Any]:
    """uvicorn's own logging config with scrubbing formatters.

    uvicorn's "uvicorn" / "uvicorn.access" loggers do not propagate to the root
    logger, so `RedactingFormatter` never saw them: access lines carried the
    request query string (`/api/stream?path=C%3A%5CUsers%5C<name>...`) and the
    "Exception in ASGI application" traceback carried every frame's file path.
    Pass this as `uvicorn.run(..., log_config=uvicorn_log_config())`.
    """
    import copy

    from uvicorn.config import LOGGING_CONFIG

    config = copy.deepcopy(LOGGING_CONFIG)
    config["formatters"]["default"]["()"] = RedactingUvicornDefaultFormatter
    config["formatters"]["access"]["()"] = RedactingUvicornAccessFormatter
    return config


try:
    from uvicorn.logging import AccessFormatter as _UvicornAccess
    from uvicorn.logging import DefaultFormatter as _UvicornDefault

    RedactingUvicornDefaultFormatter = _redacting(_UvicornDefault)
    RedactingUvicornAccessFormatter = _redacting(_UvicornAccess)
except ImportError:  # uvicorn is a runtime dependency; keep the module importable without it
    RedactingUvicornDefaultFormatter = RedactingFormatter
    RedactingUvicornAccessFormatter = RedactingFormatter
