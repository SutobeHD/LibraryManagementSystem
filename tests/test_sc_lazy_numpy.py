"""``import app.soundcloud_api`` must not import numpy.

``app.main`` imports this module at sidecar boot; the fuzzy-match index needs numpy only
once a sync or preview actually runs. Checked in a fresh interpreter because this suite
imports numpy anyway.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_CHILD = (
    "import json, sys\n"
    "import app.soundcloud_api\n"
    "print('@@RESULT@@' + json.dumps({'numpy': 'numpy' in sys.modules}))\n"
)


def test_import_soundcloud_api_does_not_load_numpy() -> None:
    proc = subprocess.run(
        [sys.executable, "-c", _CHILD],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("@@RESULT@@")]
    assert (
        proc.returncode == 0 and lines
    ), f"child failed rc={proc.returncode}: {proc.stderr[-2000:]}"
    result = json.loads(lines[-1][len("@@RESULT@@") :])
    assert result["numpy"] is False


def test_index_still_matches_after_lazy_import() -> None:
    from app.soundcloud_api import _LocalTrackIndex

    index = _LocalTrackIndex(
        {
            "1": {"Title": "Strobe", "Artist": "deadmau5"},
            "2": {"Title": "Ghosts n Stuff", "Artist": "deadmau5"},
        }
    )
    assert index.best_match("Strobe", "deadmau5") == ("1", 1.0)
    tid, score = index.best_match("Strobe (Club Edit)", "deadmau5")
    assert tid == "1"
    assert 0.65 <= score < 1.0
    assert index.best_match("Completely Different Song", "Someone Else") == (None, 0.0)
