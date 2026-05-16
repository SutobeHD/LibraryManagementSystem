# Coding rules — non-negotiable

Load-bearing constraints, not style preferences. Violating them breaks the project.

## Dependency pinning (Schicht-A Hardening 2026)

- **Python:** every dep in `requirements.txt` is `==X.Y.Z`. Never `>=` or `~=`. Never bump without CVE check + `pytest`.
- **Node:** lockfile canonical. `npm run lint:lockfile` after dep change. `npm ci` (not `install`) in CI.
- **Rust:** `Cargo.lock` committed. Don't `cargo update` casually.

## Secrets & paths

- `.env` never committed. `.env.example` is the only template. Required: `SOUNDCLOUD_CLIENT_ID`, `SOUNDCLOUD_CLIENT_SECRET`.
- `ALLOWED_AUDIO_ROOTS` sandboxes filesystem. Never bypass via `os.path.normpath` tricks. Use `Path.is_relative_to(resolved_root)` — canonical pattern in `app/main.py:validate_audio_path`.
- System endpoints behind `X-Session-Token` (one-shot via `POST /api/system/init-token`). Never leak in logs/heartbeats — not at INFO, not at DEBUG, not even redacted.

## Stack boundaries

- Audio DSP realtime → Rust (`src-tauri/src/audio/`); offline → Python (`app/analysis_engine.py`, librosa/madmom/essentia).
- HTTP / orchestration / DB → Python.
- UI / state / interactions → React.
- No layer-crossing without reason. No reimplementing Python in JS or vice versa.

## Backend concurrency

- `app/main.py:_db_write_lock` (RLock) serialises **all** Rekordbox `master.db` writers. Any new `rbox`/`pyrekordbox` write path MUST acquire it.
- `app/anlz_safe.py:SafeAnlzParser` (ProcessPoolExecutor, `max_workers=1`) quarantines rbox calls — rbox 0.1.5/0.1.7 has known `unwrap()` panics. Never call rbox parsing directly from main process.

## Python style (slopcode-cleanup targets — see `docs/HANDOVER.md`)

- **Pydantic v2** — `.model_dump()`, never `.dict()`.
- **No bare `except:` / `except: pass`** — type exception, log it. `except (sqlite3.Error, OSError) as e: logger.warning("op=X table=Y err=%s", e)`.
- **No `requests.get()` in `async def`** — `httpx.AsyncClient` + timeout + retry (`tenacity` or hand-rolled).
- **Subprocess always has `timeout=`** — FFmpeg 30s default, PowerShell 10s. Log start/end + elapsed.
- **No raw f-string SQL** — SQLAlchemy ORM or parameterised. Concatenation needs explicit allowlist (see `app/backup_engine.py:ALLOWED_TABLES`).
- **Type hints required** for new code. `mypy app/<module>.py` clean before commit.
- **`pathlib` over `os.path.join`** throughout.

## Rust style (refactor targets)

- **No `unsafe impl Send + Sync`** without `// SAFETY:` block + Cargo issue link (cpal `Stream` is `!Send` by design).
- **No `.unwrap()`/`.expect()`** in fallible paths — use `Result<T, ScError>` (`thiserror::Error`) or `?`. `expect()` OK in `main()` setup with clear panic message.
- **No `println!`/`eprintln!`** outside `#[cfg(test)]` — `log::info!/warn!/error!`.
- **No hardcoded `channels = 2`** — read from decoder, fail-fast on multichannel or downmix.
- **Tauri commands documented** — every `pub #[tauri::command]` has `///` doc + `# Errors` section.
- **`Box<dyn Error>` is a smell** — typed `thiserror` enums.

## Frontend style (refactor targets)

- **No `alert()`/`confirm()`/`prompt()`** — `useToast()` + Confirm-Modal-Component.
- **No `console.log` debug residues** in committed code. `console.error`/`console.warn` OK for real errors. Dev-only debug → `frontend/src/utils/log.js`.
- **No raw `fetch()` with `localhost:8000`** — axios via `frontend/src/api/api.js`. Tauri-context → `invoke()`.
- **No empty `catch {}`** — minimum `console.error('[Component] op failed', err)` + toast.
- **No magic numbers** — `frontend/src/config/constants.js`.

## rbox version quirks

rbox 0.1.7's `OneLibrary.create()` + `create_content()` are broken. Workaround: `app/usb_one_library.py` uses pre-built template (`app/templates/exportLibrary_template.db`) and mutates it. Don't "fix" by re-enabling `create_content` — raises `Unexpected null for non-null column`.

## Pioneer USB export — byte-verified invariants

`app/usb_pdb.py` byte layout verified **byte-for-byte against real Pioneer-exported F: drive**. Comments explain every magic number. Read the file before changing. Wrong flag/offset silently corrupts stick — Rekordbox refuses to load without telling you why.

Critical invariants:
- **Data-page flag `0x34`** (not `0x24`) on every real-export data page.
- **Descriptor `empty_candidate = next_unused_page`** (past EOF). Pointing at any USED page (incl. `last_page`) flags library as corrupted.
- **Index-page heap layout:** 24-byte structured prefix (`page_idx`, `next_btree`, const `0x03FFFFFF`, const `0`, `num_entries=0`, sentinel `0x1FFF`) + `0x1FFFFFF8` empty-slot padding to end. `next_btree = first_data_page` when table has data, else `0x03FFFFFF` sentinel.
- **Empty tables = single index page** (`first == last`).
- **Index-page header `u7 = num_b_tree_entries`** (= 0 for our writer).
- **Chain-terminator `next_page` patched `0` → `next_unused_page`** so Rekordbox doesn't follow chain into page 0 (file header).
- **String encoder:** short ASCII / long UTF-16-LE.

Run `pytest tests/test_pdb_structure.py` after any change. Fail = change is wrong unless reference fixture intentionally updated.
