"""Importing pyrekordbox without letting it reconfigure our logging.

`import pyrekordbox` runs `config.update_config()`, which does three
things we do not want in this process:

1. calls `logging.basicConfig()`, attaching a handler of its own;
2. sets `logging.root.setLevel(NOTSET)`, so the backend starts emitting
   every DEBUG record from every library into the log file that
   `RedactingFormatter` (app/main.py) guards — precisely the widening
   the redaction layer exists to prevent;
3. logs "Incompatible rekordbox 6 database: Could not retrieve db-key."
   on the ROOT logger, because it cannot find the master.db key inside
   Rekordbox's app.asar. Irrelevant to us: we read ANLZ files and
   MySetting files, never `pyrekordbox.db6`.

Measured 2026-09-03: importing `app.usb_mysettings` moved the root
logger from INFO to NOTSET. Wrap such imports in `quiet_import()`.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterator

DBKEY_WARNING = "Incompatible rekordbox 6 database: Could not retrieve db-key."


class _DropDbKeyWarning(logging.Filter):
    """Drops that one record and nothing else."""

    def filter(self, record: logging.LogRecord) -> bool:
        # Match `msg`, not `getMessage()`: a foreign record with bad
        # %-args would make getMessage() raise inside the filter.
        return not (
            record.levelno == logging.WARNING
            and isinstance(record.msg, str)
            and record.msg == DBKEY_WARNING
        )


@contextlib.contextmanager
def quiet_import() -> Iterator[None]:
    """Restore the root logger's level and handlers after the import."""
    root = logging.getLogger()
    level, handlers = root.level, root.handlers[:]
    flt = _DropDbKeyWarning()
    root.addFilter(flt)
    try:
        yield
    finally:
        root.removeFilter(flt)
        root.setLevel(level)
        root.handlers[:] = handlers
