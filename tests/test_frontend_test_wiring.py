"""Every frontend test file must actually be run by `npm test`.

`frontend/src/audio/dawState/dawReducer.test.js` — 10 assertions pinning the
composed dawReducer's contract — existed for as long as the split-reducer
refactor did and had never run in CI. There was no `test` script in
`frontend/package.json` and no step in `.github/workflows/ci.yml`; the only
way to run it was to copy the command out of the file's own docstring.

Both are wired now, but the wiring is an explicit file list rather than a
glob, so a new test file would silently repeat the same fate:

- Node's `--test` accepts glob patterns only from v21; the CI runner is Node 20.
- Directory discovery does not work either — the ESM resolver hook the test
  needs (to load Vite-style extensionless imports) tries to import the
  directory itself and fails with ERR_UNSUPPORTED_DIR_IMPORT.

So this test is the thing that keeps the list honest.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FRONTEND = REPO_ROOT / "frontend"


def _test_script() -> str:
    pkg = json.loads((FRONTEND / "package.json").read_text(encoding="utf-8"))
    script = pkg.get("scripts", {}).get("test")
    assert script, (
        "frontend/package.json has no `test` script. The dawReducer suite went "
        "unrun for its entire existence because of exactly this."
    )
    return script


def test_every_frontend_test_file_is_in_the_test_script() -> None:
    script = _test_script()
    test_files = sorted(
        p.relative_to(FRONTEND).as_posix() for p in (FRONTEND / "src").rglob("*.test.js")
    )
    assert test_files, "no frontend *.test.js found — did the suite move?"

    missing = [f for f in test_files if f not in script]
    assert not missing, (
        "these frontend test files are not run by `npm test --prefix frontend`:\n"
        + "\n".join(f"  {f}" for f in missing)
        + "\nAdd them to the `test` script in frontend/package.json. A glob will "
        "not work: Node 21+ only, and the resolver hook breaks directory "
        "discovery."
    )


def test_ci_runs_the_frontend_suite() -> None:
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "npm test --prefix frontend" in ci, (
        "ci.yml no longer runs the frontend test suite. Wiring a test file into "
        "package.json is only half of it — without a CI step nothing runs it on "
        "a push."
    )
    assert "npm test --prefix frontend || true" not in ci, (
        "the frontend test step is non-blocking. See docs/QUALITY_GATES.md — "
        "clippy is the only gate allowed to be."
    )
