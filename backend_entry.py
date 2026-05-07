"""
PyInstaller entry-point for the RB_Backend sidecar.

The package modules (app/*.py) use relative imports — running app/main.py
directly fails with `attempted relative import with no known parent package`.
This wrapper loads `app.main` as a module so the relative imports resolve,
then hands off to uvicorn with the same host/port the dev workflow uses.
"""

import sys
import multiprocessing


def main():
    # Required on Windows when frozen — otherwise ProcessPoolExecutor children
    # try to re-spawn the bundle and tunnel themselves into a fork bomb.
    multiprocessing.freeze_support()

    import uvicorn
    from app.main import app

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")


if __name__ == "__main__":
    main()
