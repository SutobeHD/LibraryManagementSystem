# Übergabeprotokoll — Slopcode-Cleanup RB Editor Pro

**Empfänger**: Claude Opus 4.7 1M Max Instanz (frische Session, kein Vorwissen)
**Auftraggeber**: tb (User) — spricht Deutsch, Caveman-Protokoll
**Datum**: 2026-05-11
**Scope**: Vollständiger Slopcode-Cleanup gemäß Audit unten. `.env`-Rotation ist EXKLUDIERT (User macht selbst).

---

## 0. MISSION

Behebe systematisch ALLE Slopcode-Findings dieses Audits. Liefere produktionsreifen Code. Halte dich strikt an CLAUDE.md (Caveman, Sizing/DoD, max 5 Loops, Defensive Programming, Logging-Pflicht, Doc-Update + Git-Commit nach jeder Task).

---

## 1. KONTEXT

### Projekt
- **RB Editor Pro** — Tauri 2.x + React 18 + FastAPI Desktop-App für DJ-Library-Management
- Features: Rekordbox-XML, non-destruktiver Audio-Editor, SoundCloud-Sync (OAuth PKCE), USB-Sync, FFT-Waveform
- Repo lokal: `C:\Users\tb\Documents\Appp\RB_Editor_Pro\` (Windows 11, PowerShell + Bash verfügbar)
- Git: branch `main`, sync mit `origin/main`, last commit `6a11b81`
- **Repo-Naming-Inkonsistenz**: Lokaler Path `RB_Editor_Pro` ↔ `package.json#name=music-library-manager` ↔ GitHub `LibraryManagementSystem` ↔ `Cargo.toml#name=library-management-system`. Vereinheitlichen auf **`library-management-system`** (kebab-case bzw. snake je Manifest).

### Stack-Layout

| Bereich | Pfad | Port |
|---|---|---|
| Frontend | `frontend/src/**` (Vite, JSX, Tailwind) | 5173 |
| Backend | `app/**` (FastAPI, Python 3.10+) | 8000 |
| Rust/Tauri | `src-tauri/src/**` | - |
| Docs | `docs/` (FILE_MAP.md + 3 index files) | - |
| Tests | `tests/` (pytest), `tests-e2e/` (vitest) | - |

### Pflicht-Reads ZUERST (in dieser Reihenfolge)
1. `CLAUDE.md` — Operating Manual + Caveman-Protokoll
2. `docs/FILE_MAP.md` — Repo-Map
3. `docs/frontend-index.md`, `docs/backend-index.md`, `docs/rust-index.md` — Area-Indizes
4. `docs/architecture.md` — Datenflüsse

---

## 2. HARTE CONSTRAINTS

- ❌ **NICHT anfassen**: `.env`, `.env*`, alles unter `.release-backup/`, branch `XMLStandaloneLibary` (user-protected), `stash@{0}` (User-Insurance)
- ❌ **NIE**: hardcoded Secrets, raw SQL-f-Strings, `dangerouslySetInnerHTML`, raw `fetch()` außerhalb `api.js`, `alert/confirm/prompt`, `.unwrap()` in fallible Rust-Paths, `print()` statt logger, Pydantic v1
- ✅ **IMMER**: Type-Hints, Pydantic v2 `.model_dump()`, Loguru/logging, Toast statt alert, `axios api.js`, `Result<T,String>` für Tauri Commands, `log::` Rust-Macros, pathlib statt os.path, async I/O wo asynchron
- ✅ **Nach JEDER Task**: `docs/FILE_MAP.md` + relevanten Index aktualisieren → `git add <files>` → `git commit -m "type(scope): desc"`
- ✅ **Commit-Format**: `fix(area): description` / `refactor(area): description` / `chore(area): description`
- ✅ **Eine Concern pro Commit** — keine gebündelten Refactors

---

## 3. PHASING — Reihenfolge ist BINDEND

Bearbeite Phasen sequenziell. Phase abschließen, committen, dann nächste. NICHT Phasen mischen.

### **PHASE 1: SECURITY HARDENING** (Sizing: M, ~12h)

Höchste Prio — Risiko für User-Daten / Live-Systeme.

| # | File:Line | Problem | Fix-Strategie | DoD |
|---|---|---|---|---|
| 1.1 | `app/backup_engine.py:66,251,264` | f-String SQL: `f"SELECT * FROM {table}"` | Whitelist explizit: `if table not in ALLOWED_TABLES: raise ValueError`. Constants oben in Modul definieren. | Keine f-String-SQL mehr; Tests die Injection-Attempts ablehnen |
| 1.2 | `app/main.py:3017` | `print(f"DEBUG: ... Token: {safe_token}")` | Entfernen oder `logger.debug()` mit redaktion (`token[:4] + "***"`) | Kein Token mehr in stdout |
| 1.3 | `app/live_database.py:167,271,275,279,511,538,597,941,969,974,981` | 11x `except: pass` | Jede Stelle einzeln auditen: typed `except (sqlite3.Error, OSError)` + `logger.warning("op=X table=Y err=%s", e)` + safe default | Kein bare except; alle catches loggen |
| 1.4 | `app/database.py:198,241,705` | bare except | wie 1.3 | wie 1.3 |
| 1.5 | `app/services.py:142,151,159,660,674,703` | bare except | wie 1.3 | wie 1.3 |
| 1.6 | `app/usb_manager.py:50,58,653,775,824,1144,1535` | bare except | wie 1.3 | wie 1.3 |
| 1.7 | `app/sidecar.py:17` | bare JSON-load except | typed `except (json.JSONDecodeError, OSError)` + log | erledigt |
| 1.8 | `app/main.py:1092`, `app/usb_manager.py:155,160` | `subprocess.check_output` ohne `timeout=` | Default `timeout=30` für FFmpeg, `timeout=10` für PS-Calls. Bei `TimeoutExpired` log + raise typed exception | Kein subprocess ohne timeout |
| 1.9 | `src-tauri/src/audio/playback.rs:12-13` | `unsafe impl Send+Sync for PlaybackEngine` | cpal `Stream` ist `!Send`. Richtige Lösung: Stream auf Audio-Thread halten, nur Steuer-Signale (Arc<AtomicBool>, ringbuffer) crossthread teilen. `unsafe impl` entfernen, Struktur refaktorieren. **Falls zu invasiv**: TODO mit Issue + `// SAFETY: …` Comment mit Justification | Kein nacktes `unsafe impl Send/Sync` ohne Safety-Block |
| 1.10 | Globale Locks | `app/database.py:969` globaler `db`-Singleton ohne Lock | `asyncio.Lock` + Helper `async def with_db()` ODER threading.RLock für sync paths. Alle Mutations gated. | Race-Conditions eliminiert; konkurrente Tests bestehen |

**Commits**: 1 pro Sub-Task (1.1, 1.2, …). Prefix `fix(security): ...` oder `fix(reliability): ...`.

---

### **PHASE 2: RUST CORRECTNESS** (Sizing: M, ~16h)

| # | File:Line | Problem | Fix-Strategie | DoD |
|---|---|---|---|---|
| 2.1 | `src-tauri/src/audio/analysis.rs:47-49` | 3-Band FFT-Bin-Indices statt Hz | Bands aus Frequenz mappen: `low=20-250Hz`, `mid=250-4000Hz`, `high=4000-20000Hz`. Index = `freq * fft_size / sample_rate`. Sample-Rate als Param durchreichen. | Bands unabhängig von SR korrekt |
| 2.2 | `src-tauri/src/audio/analysis.rs:103` | `detect_key()` returnt hardcoded `"8A"` | Entweder: (a) real implementieren via Krumhansl-Schmuckler oder Pitch-Class-Profile; (b) `Result::Err("not implemented")` + Frontend zeigt "—". Lüge an User raus. | Kein Fake-Wert mehr |
| 2.3 | `src-tauri/src/audio/analysis.rs:82` | `for i in 1..energies.len()-1` panic bei len<2 | Guard: `if energies.len() < 3 { return default; }` | Kein underflow |
| 2.4 | `src-tauri/src/main.rs:330` | `.expect("error while building tauri application")` | `match` mit `eprintln!` + `std::process::exit(1)` (Setup-Phase, kein Panic) | Graceful exit |
| 2.5 | `src-tauri/src/audio/export.rs:81` | `re_samples - rs_samples` panic | Validierung: `if region.end <= region.start { return Err("invalid region".into()); }` + `saturating_sub` | Kein Crash bei invalider Region |
| 2.6 | `src-tauri/src/audio/export.rs:69` | `(max_timeline_end * sample_rate as f32) as usize` overflow | `.max(0.0)` + Bounds-Check; `usize::try_from(rounded as i64)` | Kein Overflow |
| 2.7 | `src-tauri/**` (~50 Stellen) | `println!`/`eprintln!` statt `log::` | Bulk-Replace: `println!` → `log::info!`, `eprintln!` → `log::error!`. `env_logger`/`tauri-plugin-log` initialisieren falls noch nicht | Keine println/eprintln mehr außer in `#[cfg(test)]` |
| 2.8 | 6 Tauri Commands | Fehlende `///` Doc + `# Errors` Section | Jeder pub `#[tauri::command]`: `/// Lädt Audio …\n/// # Errors\n/// - X wenn Y` | Alle Commands dokumentiert |
| 2.9 | `src-tauri/src/main.rs:168 ↔ 208` | Duplizierter OAuth-Code (~40 LOC) | Helper-Fn `async fn ensure_oauth_token(...) -> Result<String, String>` extrahieren | Login + Export rufen Helper auf |
| 2.10 | `src-tauri/src/audio/engine.rs:14-17,192-199` | Leerer Struct + Stub `seek()` | Beides löschen wenn ungenutzt; Wenn genutzt → Issue + `todo!()` mit Issue-Link, NICHT silent stub | Code reflektiert echten State |
| 2.11 | `src-tauri/src/soundcloud_client.rs:22` | `Box<dyn Error>` | `thiserror::Error` Enum `ScError { Network, Parse, Auth, ... }` | Typisierte Errors |
| 2.12 | `Cargo.toml` | `rubato`, `crossbeam-channel` unused; `tokio="full"` | Unused entfernen; tokio features minimieren (`["rt-multi-thread","macros","io-util","time","fs","sync"]`) | `cargo machete` clean, `cargo build` green |
| 2.13 | `src-tauri/src/audio/analysis.rs:70`, `export.rs:64`, `engine.rs:109` | hardcoded channels=2 | Channels aus Decoder lesen, fail-fast bei mono/multichannel oder downmix | Kein hardcoded stereo |

**Commits**: `fix(rust): ...` / `refactor(rust): ...`. Update `docs/rust-index.md` nach jeder Änderung.

---

### **PHASE 3: BACKEND HARDENING** (Sizing: L, ~20h)

| # | File:Line | Problem | Fix-Strategie | DoD |
|---|---|---|---|---|
| 3.1 | `app/main.py:834,2073,3449` | Pydantic v1 `.dict()` | → `.model_dump()` | Keine `.dict()` mehr |
| 3.2 | 16 Endpoints | Body als `r: dict` | Pro Endpoint: Pydantic-Model `class XYZRequest(BaseModel)` definieren. Inkl. `usb_save_settings`, `analyze_track`, `system_heartbeat`, `usb_sync_all`, `merge_all_duplicates` | Alle POST/PUT mit typed Body |
| 3.3 | `app/soundcloud_api.py:75,94,187` + `soundcloud_downloader.py:228,331,444,582,640,665,668` | Sync `requests.get` in async | `httpx.AsyncClient` mit Connection-Pool. Timeout + Retry (tenacity oder eigener Backoff für 429) | Kein blocking-HTTP in async path |
| 3.4 | `app/main.py:224` | `global_exception_handler` 207 LOC | Pro Exception-Typ in eigene Funktion splitten; Handler nur dispatched. Pattern-Match-Tabelle. | Funktion < 50 LOC |
| 3.5 | `app/database.py` 51 Funktionen | Fehlende Type Hints | Komplette Datei type-annotieren. `mypy app/database.py` muss durchlaufen | `mypy` clean für database.py |
| 3.6 | `app/services.py` 19 Funktionen | wie 3.5 | wie 3.5 | wie 3.5 |
| 3.7 | `app/live_database.py` 17 Funktionen | wie 3.5 | wie 3.5 | wie 3.5 |
| 3.8 | 12 Stellen | `os.path.join` statt pathlib | `Path()` durchgehend | Keine os.path.join außer Legacy-Drittlib |
| 3.9 | `app/main.py` 8 Stellen | Hardcoded `"library_management_system"` Keyring-Service | Constant `KEYRING_SERVICE = "library_management_system"` modulglobal | DRY |
| 3.10 | `app/services.py:286,423`, `usb_manager.py:1612` | FFmpeg/subprocess ohne Pre-Log | `logger.info("ffmpeg start: args=%s", cmd)` + `logger.info("ffmpeg done: rc=%s, elapsed=%.2fs", rc, t)` | Alle subprocess-Calls geloggt |
| 3.11 | `app/audio_tags.py:287`, `anlz_safe.py:33`, `services.py:1008` | TODO/WORKAROUND ohne Issue | GitHub-Issues anlegen, IDs in Comments einsetzen oder Code entfernen | Jedes TODO hat Owner+Issue |

**Commits**: `fix(api): ...`, `refactor(db): ...`, `chore(types): ...`. Update `docs/backend-index.md`.

---

### **PHASE 4: FRONTEND CLEANUP** (Sizing: L, ~24h)

#### 4A — Convention-Fixes (mechanisch, ~6h)

| # | Files | Problem | Fix |
|---|---|---|---|
| 4.1 | 24 Stellen | `alert/confirm/prompt` | `useToast()` Context + Confirm-Modal-Component aus shared/ |
| 4.2 | 34 Stellen | `console.log` Debug-Reste | Loglevel-Util `frontend/src/utils/log.js` mit `if (import.meta.env.DEV)` Guard; `console.error/warn` erhalten |
| 4.3 | 5 Files | Raw `fetch()` mit `localhost:8000` | Auf `api.js` migrieren. Falls Tauri-IPC: über `invoke()` |
| 4.4 | 7 Stellen | `catch {}` empty | Min: `console.error('[Component] op failed', err)` + Toast |
| 4.5 | Hardcoded numbers | `5000`, `180000`, `5001` | Constants in `frontend/src/config/constants.js` |

#### 4B — God-Components splitten (~18h)

Reihenfolge nach LOC absteigend:

1. **WaveformEditor.jsx (2223 LOC)** → Split: `WaveformCanvas` + `WaveformControls` + `WaveformZoom` + `WaveformOverlays` + `useWaveformInteractions` Hook
2. **UsbView.jsx (1937 LOC)** → Split: `UsbDeviceList` + `UsbSyncPanel` + `UsbProfileEditor` + `UsbFormatWizard`
3. **DawTimeline.jsx (1188 LOC)** → Split: Rendering-Layer + State-Layer + Event-Handler
4. **SettingsView.jsx (1179 LOC)** → Tab-pro-Component (`SettingsAudio`, `SettingsLibrary`, `SettingsSoundCloud`, `SettingsAdvanced`)
5. **DawState.js (1031 LOC)** → Reducer pro Domain (regions, transport, selection, history)
6. **NonDestructiveEditor.jsx (1008 LOC)** → Editor-Container + Keyboard-Hook + Toolbar-Component
7. **DjEditDaw.jsx (972 LOC)** → DAW-Layout + Project-Persistence-Hook

**Pro Split**: Tests dass Verhalten identisch bleibt (Smoke-Test im Browser via `preview_*` Tools — siehe Phase 6).

**Commits**: `refactor(frontend): split WaveformEditor into 5 components` etc. Update `docs/frontend-index.md`.

---

### **PHASE 5: REPO-HYGIENE + TOOLING** (Sizing: M, ~10h)

| # | Issue | Fix |
|---|---|---|
| 5.1 | Repo-Naming-Chaos (4 Namen) | Vereinheitlichen auf `library-management-system`. Update `package.json` (Root + frontend), `Cargo.toml`, `README.md`, alle docs. GitHub-Repo bleibt `LibraryManagementSystem` (PascalCase, schon richtig). |
| 5.2 | `app/brute_force_mytags.py`, `app/inspect_smart_pl.py` git-tracked | `git rm --cached` + commit |
| 5.3 | 33+ Debug-Scripts in `app/` | Verschieben nach `scripts/dev/`, dort gitignored ODER bei genutzt → tracked nach `scripts/dev/` |
| 5.4 | `frontend/fix_waveform.py`, `fix_waveform_v2.py` | Löschen (Python-Files im Frontend = falsch) |
| 5.5 | `docker-compose.yml` + `Dockerfile.backend/.frontend` | Löschen (Projekt ist Desktop, kein Container) |
| 5.6 | `docs/FILE_MAP.md` referenziert `PROJECT_WIKI.md` | Reference löschen |
| 5.7 | `docs/frontend-index.md` listet 8/33 Komponenten | Komplett regenerieren — alle 33 erfassen mit One-Liner-Description |
| 5.8 | `requirements.txt` driftet | Mit `pipreqs app/` oder manuellem Audit synchronisieren. Mindestens: `madmom`, `essentia`, `pyrekordbox`, `numpy` explizit listen falls direkt importiert |
| 5.9 | `.gitignore` redundante Einträge | Dedupe (`dist/`, `build/`, `.vscode/` doppelt) |
| 5.10 | `tests/legacy_debug/` 23 Files | Falls historisch wertvoll → `archive/`; sonst löschen |
| 5.11 | `tests-e2e/` → `tests/e2e/` | Naming-Konsistenz (alle snake_case) |
| 5.12 | TypeScript? | Projekt ist plain JS. Entweder bewusst commiten oder Migration-Plan. Default: NICHT migrieren, aber `jsconfig.json` für VSCode-Hints |
| 5.13 | Kein ESLint/Prettier | `frontend/.eslintrc.cjs` + `frontend/.prettierrc` anlegen mit react-Standard-Config. `npm run lint` Script |
| 5.14 | Kein ruff/black/mypy | `pyproject.toml` mit `[tool.ruff]`, `[tool.black]`, `[tool.mypy]` Sections. Inkl. `make lint` |
| 5.15 | CI nur `release.yml` | `.github/workflows/ci.yml` mit Jobs: `python-lint-test` (ruff + pytest), `rust-lint-test` (clippy + cargo test), `frontend-lint` (eslint). Trigger: `push` + `pull_request` |
| 5.16 | Workspace-Bloat 2.5GB | `.release-backup/`, `build/`, `dist/`, `backups/` NICHT anfassen (User-Daten). Aber `usb_sync.log` 424KB, `backend_test.log`, `standalone.xml`, `anlz_test_modified.DAT`, `test_gen.db` aus Root nach `tmp/` (gitignored). |

---

### **PHASE 6: VERIFICATION & TESTS** (Sizing: M, ~20h)

#### 6A — Test-Coverage aufbauen

Aktueller Stand: 3 Tests für 50+ Module. Mindest-Ziel:

| Modul | Test-File | Min-Coverage |
|---|---|---|
| `app/database.py` | `tests/test_database.py` | CRUD-Tracks, Playlists |
| `app/services.py` | `tests/test_services.py` | XML-Export, BPM-Analysis-Mock |
| `app/usb_manager.py` | `tests/test_usb_manager.py` | Mock-FS, profile-load/save |
| `app/soundcloud_api.py` | `tests/test_soundcloud_api.py` | httpx-mock, 429-retry |
| `src-tauri/src/audio/analysis.rs` | inline `#[cfg(test)]` | FFT-Band-Mapping, edge cases |
| `src-tauri/src/audio/export.rs` | inline `#[cfg(test)]` | invalid-region rejection |
| `frontend/src/audio/DawState.js` | `frontend/src/audio/DawState.test.js` | Reducer-Transitions |

#### 6B — Verification Workflow (laut CLAUDE.md preview_tools)

Nach jeder UI-Änderung:
1. `preview_start` (npm run dev)
2. `preview_console_logs` — keine neuen Errors
3. `preview_snapshot` — Layout intakt
4. `preview_click`/`preview_fill` für Interaktionen
5. `preview_screenshot` als Proof

#### 6C — Backend-Smoke

```bash
python -m app.main &
curl -f http://localhost:8000/api/health
pytest tests/ -v
```

#### 6D — Rust-Smoke

```bash
cd src-tauri && cargo clippy -- -D warnings && cargo test
```

---

## 4. STATUS-REPORTING

Nach jeder Phase: Status-Badge laut CLAUDE.md:

```
<small>Status: 🟢 Done | Sizing: M | DoD: Erfüllt | Loops: X/5 | Sec/Perf: Safe</small>
```

Plus kurzer Phase-Report:
- Welche Sub-Tasks erledigt
- Welche Commits gemacht (Hash + Subject)
- Welche Tests grün
- Was geblockt / offen

---

## 5. ESCALATION

Wenn nach 5 Loops an einem Task nicht gelöst:
1. Aktuellen Stand committen (`wip(area): ...`)
2. TODO-Comment mit Begründung an Stelle
3. Im Status-Report markieren: 🟡 Blocked
4. Weiter zu nächster Task — NICHT festfressen

Wenn destruktive Operation nötig (z.B. `git rm --cached` für tracked Files): erst Liste an User zur Approval, NICHT eigenmächtig.

---

## 6. ABSCHLUSS-DOD (ALLE PHASEN)

- ✅ Alle 🔴-Items aus Audit gefixt (außer `.env` — User-Domain)
- ✅ Alle 🟠-Items aus Audit gefixt
- ✅ `cargo clippy -- -D warnings` clean
- ✅ `mypy app/` clean (oder dokumentierte Exclusions)
- ✅ `ruff check app/` clean
- ✅ `npm run lint` clean (sobald 5.13 erledigt)
- ✅ `pytest tests/` grün, mindestens 8 neue Test-Files (siehe 6A)
- ✅ `cargo test` grün
- ✅ CI-Workflow `ci.yml` läuft auf Push grün
- ✅ `docs/FILE_MAP.md` aktuell, alle 3 Index-Files synchron mit Code
- ✅ Jeder Commit hat `type(scope): description` Format
- ✅ Status-Report pro Phase abgegeben

---

## 7. ANHANG — Audit-Findings Komplettliste

### Frontend (siehe Phase 4)
24 alert/prompt | 34 console.log | 5 raw fetch | 7 empty catch | 7 God-Components | 5 hardcoded numbers | Inline-styles 2x | handleNormalize placeholder NonDestructiveEditor.jsx:474

### Backend (siehe Phase 1+3)
40+ bare except | 3 SQL-f-Strings | print() in main.py:3017 | 10 sync requests in async | 3 .dict() v1 | 16 endpoints ohne Pydantic-Body | global db singleton | 3 subprocess ohne timeout | 207-LOC global_exception_handler | 51+19+17 fehlende type hints | 12 os.path.join | 8x "library_management_system" hardcoded | 3 TODOs ohne Issue

### Rust (siehe Phase 2)
unsafe impl Send+Sync playback.rs:12 | detect_key fake "8A" | FFT bin-as-Hz bug | unwrap/expect main.rs:330 | export.rs:81 underflow | analysis.rs:82 underflow | ~50x println/eprintln | 6 Commands ohne Doc | duplizierter OAuth ~40 LOC | leerer Struct + stub seek | Box<dyn Error> inkonsistent | clone-spam soundcloud_client | unused deps rubato/crossbeam | tokio="full"

### Repo (siehe Phase 5)
4 Project-Namen | 2 git-tracked Debug-Scripts | 33+ Debug-Files in app/ | fix_waveform*.py | docker-compose/Dockerfile dead | FILE_MAP.md → PROJECT_WIKI.md (404) | frontend-index 8/33 | requirements.txt drift | .gitignore Duplikate | tests/legacy_debug 23 Files | nur release.yml CI | kein tsconfig/eslint/prettier/ruff/black/mypy

---

**START-BEFEHL FÜR OPUS 4.7 1M**:
> "Lies CLAUDE.md, dann docs/FILE_MAP.md, dann dieses Übergabeprotokoll. Beginne mit Phase 1, Task 1.1. Status nach jeder Phase melden."
