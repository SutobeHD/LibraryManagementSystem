# Coding rules — non-negotiable

These are **load-bearing constraints**, not style preferences. Violating them breaks the project.

## Dependency pinning (Schicht-A Hardening 2026)

- **Python:** every dep in `requirements.txt` is `==X.Y.Z`. Never relax to `>=` or `~=`. Never bump without checking CVE notes + running `pytest`.
- **Node:** lockfile is canonical. Run `npm run lint:lockfile` after any dep change. `npm ci` (not `npm install`) for reproducible installs in CI.
- **Rust:** Cargo.lock is committed. Don't `cargo update` casually.

## Secrets & paths

- `.env` is **never committed**. `.env.example` is the only template. Required keys today: `SOUNDCLOUD_CLIENT_ID`, `SOUNDCLOUD_CLIENT_SECRET`.
- `ALLOWED_AUDIO_ROOTS` sandboxes filesystem access — never bypass via `os.path.normpath` tricks. Use `Path.is_relative_to(resolved_root)` (already canonical pattern in `app/main.py:validate_audio_path`).
- System endpoints sit behind `X-Session-Token` (one-shot via `POST /api/system/init-token`). Never leak the token in logs/heartbeats — not at INFO, not at DEBUG, not even redacted.

## Stack boundaries

- Audio DSP heavy lifting → Rust (`src-tauri/src/audio/`) for realtime, Python (`app/analysis_engine.py`, librosa/madmom/essentia) for offline.
- HTTP / orchestration / DB → Python.
- UI / state / interactions → React.
- Don't cross layers needlessly. Don't reimplement Python logic in JS or vice versa.

## Backend concurrency

- `app/main.py:_db_write_lock` (RLock) serialises **all** Rekordbox `master.db` writers. Any new write path through `rbox`/`pyrekordbox` MUST acquire it.
- `app/anlz_safe.py:SafeAnlzParser` (ProcessPoolExecutor, `max_workers=1`) quarantines rbox calls — rbox 0.1.5/0.1.7 has known `unwrap()` panics. Never call rbox parsing directly from the main process.

## Python style — current refactor targets

These are codified from the slopcode-cleanup mission (`docs/HANDOVER.md`). Apply them in any new or edited code:

- **Pydantic v2** — use `.model_dump()`, never legacy `.dict()`.
- **No bare `except:` or `except: pass`** — type the exception and log it. `except (sqlite3.Error, OSError) as e: logger.warning("op=X table=Y err=%s", e)`.
- **No `requests.get(...)` in `async def` paths** — use `httpx.AsyncClient` with timeout + retry (`tenacity` or hand-rolled backoff).
- **Subprocess calls always have `timeout=`** — default `timeout=30` for FFmpeg, `timeout=10` for PowerShell. Log start + end with elapsed time.
- **No raw f-string SQL** — use SQLAlchemy ORM or parameterised queries. If you must concatenate, validate against an explicit allowlist (see `app/backup_engine.py:ALLOWED_TABLES`).
- **Type hints required** for new code. `mypy app/<your_module>.py` should be clean before commit.
- **pathlib over `os.path.join`** — `Path("...")` throughout.

## Rust style — current refactor targets

- **No `unsafe impl Send + Sync`** without an explicit `// SAFETY:` block + Cargo issue link justifying it (cpal `Stream` is `!Send` by design).
- **No `.unwrap()` / `.expect()`** in fallible paths — use `Result<T, ScError>` (`thiserror::Error` enum) or `?` propagation. `expect()` is fine in `main()` setup with a clear panic message.
- **No `println!` / `eprintln!`** outside `#[cfg(test)]` — use `log::info!`, `log::warn!`, `log::error!`.
- **No hardcoded `channels = 2`** — read channel count from the decoder, fail-fast on multichannel or downmix.
- **Tauri commands documented** — every `pub #[tauri::command]` has `///` doc with a `# Errors` section.
- **`Box<dyn Error>` is a smell** — use typed error enums (`thiserror`).

## Frontend style — current refactor targets

- **No `alert()` / `confirm()` / `prompt()`** — use `useToast()` + Confirm-Modal-Component.
- **No `console.log` debug residues** in committed code. `console.error` / `console.warn` are fine for real errors. Use `frontend/src/utils/log.js` for dev-only debug.
- **No raw `fetch()` with `localhost:8000`** — go through `frontend/src/api/api.js` axios instance. Tauri-context calls go through `invoke()`.
- **No empty `catch {}`** — at minimum `console.error('[Component] op failed', err)` + toast.
- **No magic numbers** — put constants in `frontend/src/config/constants.js`.

## rbox version quirks

- rbox 0.1.7's `OneLibrary.create()` and `create_content()` are broken. Workaround: `app/usb_one_library.py` uses a pre-built template (`app/templates/exportLibrary_template.db`) and mutates it. Don't "fix" this by re-enabling create_content — it raises `Unexpected null for non-null column`.

## Pioneer USB export — byte-verified invariants

`app/usb_pdb.py` byte layout is verified **byte-for-byte against a real Pioneer-exported F: drive**. Comments explain every magic number. Read the file before changing it. A wrong flag/offset corrupts the stick silently — Rekordbox refuses to load it without telling you why.

Critical invariants:
- **Data-page flag `0x34`** (not `0x24`) on every real-export data page.
- **Descriptor `empty_candidate = next_unused_page`** (past EOF). Pointing it at any USED page (last_page included) flags the library as corrupted.
- **Index-page heap layout:** 24-byte structured prefix (`page_idx`, `next_btree`, const `0x03FFFFFF`, const `0`, `num_entries=0`, sentinel `0x1FFF`) followed by `0x1FFFFFF8` empty-slot padding to end. `next_btree = first_data_page` when the table has data, else `0x03FFFFFF` sentinel.
- **Empty tables = single index page** (`first == last`).
- **Index-page header `u7 = num_b_tree_entries`** (= 0 for our writer).
- **Chain-terminator `next_page` patched from `0` → `next_unused_page`** so Rekordbox doesn't follow chain into page 0 (the file header).
- **String encoder:** short ASCII / long UTF-16-LE.

Run `pytest tests/test_pdb_structure.py` after any change. If it fails, the change is wrong unless you also intentionally updated the reference fixture.
