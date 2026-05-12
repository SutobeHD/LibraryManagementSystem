---
description: Add a new FastAPI route in app/main.py with auth/lock/model boilerplate
argument-hint: "<HTTP_METHOD> <path> <short purpose>  e.g.  POST /api/library/dedupe scan duplicates"
allowed-tools: Read, Edit, Grep, Bash, Agent
---

Add a new FastAPI route: $ARGUMENTS

This is a guided scaffold, not blind insertion. Follow this order:

1. **Read `app/main.py` top-of-file imports + request-model section** so the new route matches existing style.
2. **Check `docs/backend-index.md`** for the right grouping — routes are clustered by feature (system, library, playlist, usb, soundcloud, analysis, phrase, duplicates, …). Insert the new route in its cluster, not at the bottom.
3. **Decide auth gate:**
   - Read-only library endpoints: no token required.
   - Write to library / playlists / tracks: **must** acquire `_db_write_lock` (RLock) before any rbox/SQLAlchemy write.
   - System / shutdown / process control: gated by `X-Session-Token` (see `POST /api/system/init-token`).
4. **Decide model:** if the request body has > 2 fields, create a Pydantic `BaseModel` next to existing models. Don't accept loose `dict`.
5. **Error handling:** raise `HTTPException(status_code=..., detail=...)`. The global exception handler converts unexpected exceptions to 500 with sanitised messages — don't wrap in try/except just to re-raise.
6. **After the edit:**
   - Run `python -c "import ast; ast.parse(open('app/main.py').read())"` to syntax-check.
   - Run `pytest tests/ -k <new_route_keyword>` if a test exists, otherwise note that a test is needed.
   - Update `docs/backend-index.md` row.
   - Update `docs/FILE_MAP.md` `app/main.py` row if the route count or notable surface changed.

If the route needs heavy DSP, queue work via `AudioAnalyzer` / `analysis_engine.AnalysisEngine.submit` and return a `task_id` immediately — never block the request thread on librosa/madmom.

Use the `route-architect` subagent if the request is non-trivial (multiple endpoints, new model hierarchy, cross-cutting auth concerns).
