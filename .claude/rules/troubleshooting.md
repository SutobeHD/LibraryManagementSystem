# When you hit something weird

1. **`docs/MAP.md` / `docs/FILE_MAP.md`** row for the file — non-obvious invariant likely documented.
2. **`CHANGELOG.md`** for recent rework in that area.
3. **`git log -- <file>`** for recent `fix(` / `refactor(` commits.
4. **`docs/research/_INDEX.md`** — in-flight research/implementation doc may capture active design.
5. **Parser/writer/exporter odd** → rbox version quirks. Check `app/anlz_safe.py` + `app/usb_one_library.py`. USB byte-layout invariants in `app/usb_pdb.py` comments (verified vs F: drive snapshot).
6. **Desktop app misbehaves** → check Python sidecar booted: `curl http://127.0.0.1:8000/api/system/health`. Tauri: `npm run tauri dev` terminal for Rust panics / sidecar errors.
7. **Frontend can't reach backend** → CORS whitelist in `app/main.py` + axios `baseURL` in `frontend/src/api/api.js`. Port 8000 hardcoded.
8. **`SafeAnlzParser` panics repeatedly** → per-run budget `MAX_PANICS_PER_RUN=32` may be exhausted (`app/anlz_safe.py`). Bisecting blacklist `_bad_ids` is in-memory; sidecar restart resets.
9. **`master.db` write fails/hangs** → missing `_db_write_lock` acquisition, or Rekordbox holds DB. Close Rekordbox first.
10. **USB sync silently corrupts sticks** → PDB byte layout in `app/usb_pdb.py` most likely culprit. Run `pytest tests/test_pdb_structure.py` vs reference fixture.
11. **Unexpected test failure**, esp. `test_pdb_structure.py` or `test_onelibrary_wal_flush.py` → your change probably broke a byte-level or SQLite-WAL invariant. Don't update fixture without understanding why.
12. **Tauri command returns `{ error }` not data** → `src-tauri/src/audio/commands.rs` handler. All return `Result<T, String>`; frontend logs raw error in dev console.
13. **SoundCloud login fails / `SOUNDCLOUD_CLIENT_ID` error** → `.env` missing, or backend not restarted after creating it. App credentials (`.env` with the user's own SC app `CLIENT_ID`/`SECRET`) are required *before* OAuth — separate from the user's SC login token. The sidecar reads `.env` only at boot → restart it after `.env` edits. Claude **cannot write `.env`** (settings-blocked) — hand the user a paste-ready block. Don't re-diagnose from scratch each session.
14. **`tauri` / `vite` "command not found" or missing `node_modules`** → fresh clone/worktree without installed deps. `npm install` (root) + `npm install --prefix frontend`. Tauri prod build additionally needs the bundled Python sidecar binary — for UI checks prefer `npm run dev:full`.
