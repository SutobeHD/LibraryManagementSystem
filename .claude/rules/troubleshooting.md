# When you hit something weird

1. **Check `docs/MAP.md` or `docs/FILE_MAP.md`** row for that file — likely a non-obvious invariant is documented.
2. **Check `CHANGELOG.md`** for recent rework in that area.
3. **Check `git log -- <file>`** for recent commits — particularly any `fix(` or `refactor(` against the file.
4. **Check `docs/research/_INDEX.md`** — there might be an in-flight research/implementation doc that captures the active design.
5. **If a parser/writer/exporter behaves oddly**, suspect rbox version quirks — check `app/anlz_safe.py` and `app/usb_one_library.py` for the known patterns. The byte-layout invariants for Pioneer USB export live in `app/usb_pdb.py` comments — verified against an F: drive snapshot.
6. **If the desktop app misbehaves**, check that the Python sidecar booted: `curl http://127.0.0.1:8000/api/system/health`. Tauri-side: check `npm run tauri dev` terminal for Rust panics or sidecar boot errors.
7. **If frontend can't reach backend**, verify the CORS whitelist in `app/main.py` and the axios `baseURL` in `frontend/src/api/api.js`. The port 8000 is hardcoded.
8. **If `SafeAnlzParser` panics repeatedly**, the per-run budget (`MAX_PANICS_PER_RUN=32`) may be exhausted — check `app/anlz_safe.py`. The bisecting blacklist (`_bad_ids`) is in-memory only; restart of the sidecar resets it.
9. **If a write to `master.db` fails or hangs**, suspect missing `_db_write_lock` acquisition or Rekordbox having the DB open. Close Rekordbox first.
10. **If USB sync produces silently-corrupted sticks**, the PDB byte layout in `app/usb_pdb.py` is the most likely culprit — run `pytest tests/test_pdb_structure.py` to verify against the reference fixture.
11. **If a test you didn't expect to fail starts failing**, especially `tests/test_pdb_structure.py` or `tests/test_onelibrary_wal_flush.py` — your last change probably broke a byte-level or SQLite-WAL invariant. Don't update the fixture without understanding why.
12. **If a Tauri command returns `{ error }` instead of data**, check `src-tauri/src/audio/commands.rs` for the matching handler — they all return `Result<T, String>` and the frontend logs the raw error in dev console.
