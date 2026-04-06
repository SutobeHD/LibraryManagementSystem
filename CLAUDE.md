# CLAUDE.md — RB Editor Pro

> **Note**: The user (tb) speaks German. When responding conversationally, German is fine. Code, comments, docs, and filenames are always in English.

---

## MANDATORY WORKFLOW — Follow This Every Session

### Start of Every Task
1. **Read `.claude/docs/FILE_MAP.md` first** — identifies the exact files to edit without blind search
2. Read the relevant index file in `.claude/docs/` for the area you're working in

### After Every Edit Session (NON-OPTIONAL)
1. **Update docs** — update `FILE_MAP.md` and the relevant `.claude/docs/` index file to reflect any added/removed/renamed files or changed APIs
2. **Git commit** — create a descriptive commit after every completed task. Format: `type(scope): description`. Never leave work uncommitted.

```bash
git add <specific files>
git commit -m "feat(soundcloud): add retry logic for 429 rate limit errors"
```

These are not optional steps. Every agent and every session must follow this workflow.

---

## Project Overview

RB Editor Pro is a Tauri + React + Python desktop application for professional DJ library management:
- Rekordbox XML integration (parse, clean, export)
- Non-destructive audio editing (beatgrids, cues, envelopes)
- SoundCloud sync (OAuth PKCE, playlist matching, download)
- USB device sync with incremental backup engine
- Real-time 3-band waveform analysis via Rust/FFT

**Stack**: React 18 + Vite (frontend) | FastAPI + Python (backend, port 8000) | Rust + Tauri 2.x (desktop wrapper, native audio)

---

## Core Coding Principles

### 1. Defensive Programming (NASA/Military Grade)

Every function must be written as if it will receive invalid input. The application must be **logically unable to crash** from unhandled errors.

```python
# BAD
def process_track(track):
    return track["bpm"] * 2

# GOOD
def process_track(track: dict) -> float | None:
    """Double the BPM of a track. Returns None if BPM unavailable."""
    if not isinstance(track, dict):
        logger.error("process_track: expected dict, got %s", type(track))
        return None
    bpm = track.get("bpm")
    if bpm is None or not isinstance(bpm, (int, float)) or bpm <= 0:
        logger.warning("process_track: invalid BPM value: %r", bpm)
        return None
    return float(bpm) * 2
```

Rules:
- **Validate all inputs** at function boundaries — type, range, nullability
- **Never assume** a dict key exists — always `.get()` with fallback
- **Never let exceptions propagate silently** — catch, log, return safe default
- **Guard all async/await** — wrap in try/except or use `.catch()`
- **React**: Every component that fetches data needs error state + loading state
- **Rust**: Use `Result<T, E>` everywhere, no `.unwrap()` in production code

### 2. Comprehensive Logging

**Every new feature MUST include logging.** No exceptions.

#### Python (use `loguru` or `logging`):
```python
import logging
logger = logging.getLogger(__name__)

# Levels:
logger.debug("USB scan started: path=%s", path)       # Detailed trace
logger.info("Track imported: id=%s, title=%s", id, title)  # Key events
logger.warning("BPM analysis slow: %.2fs for %s", elapsed, file)  # Degraded
logger.error("Export failed: %s — %s", path, exc)     # Errors (non-fatal)
logger.critical("DB connection lost: %s", exc)         # Fatal errors
```

#### TypeScript/React (use structured console or a logger util):
```typescript
// At module level
const log = (level: string, msg: string, data?: object) =>
  console[level](`[ComponentName] ${msg}`, data ?? '');

log('info', 'Track loaded', { id, title, duration });
log('warn', 'Waveform cache miss', { trackId });
log('error', 'API call failed', { endpoint, status, error });
```

#### Rust:
```rust
use log::{debug, info, warn, error};
info!("Audio engine initialized: sample_rate={}, channels={}", sr, ch);
error!("Playback stream error: {:?}", e);
```

**What to log**:
- Every API call (request + response status)
- Every state transition in complex components
- Every file I/O operation
- Every external service call (FFmpeg, SQLite, SoundCloud API)
- Every user action that triggers backend work
- Performance metrics for operations > 100ms

### 3. AI-Readable Comments

Write comments that help AI assistants (and future developers) understand code instantly.

```typescript
/**
 * Resolves a SoundCloud track match against the local library.
 *
 * Matching strategy (in order of confidence):
 * 1. Exact ISRC code match (99% confidence)
 * 2. Title + Artist fuzzy match with jaro-winkler (>0.92 threshold)
 * 3. Duration match within ±3s as tiebreaker
 *
 * @param scTrack   - Track object from SC API (has id, title, user, duration)
 * @param library   - Local track array from /api/library/tracks
 * @returns         - Best match with confidence score, or null if no match
 */
function matchScTrackToLibrary(scTrack: ScTrack, library: LocalTrack[]): MatchResult | null {
```

Rules:
- **Function-level JSDoc/docstrings** on all non-trivial functions
- **Explain the "why"** — architecture decisions, non-obvious logic, workarounds
- **Mark workarounds** with `// WORKAROUND: <reason> — revisit when <condition>`
- **Mark TODOs** with `// TODO: <what> — <why it's deferred>`
- Comment on **data shape assumptions**: `// SC API v2 returns duration in ms, not seconds`

### 4. Token Efficiency (Keep Context Lean)

- **Read `.claude/docs/FILE_MAP.md` first** — single file that maps the entire codebase; never search blindly
- **Then read the relevant index** (`.claude/docs/frontend-index.md`, `backend-index.md`, `rust-index.md`) for the area you're changing
- **Targeted edits** over full rewrites — use Edit tool, not rewrite entire files
- **Don't re-read files** already read in the same conversation
- **One concern per PR/commit** — don't bundle unrelated changes
- **Responses**: Lead with the action/answer. Skip preamble. No trailing summaries.

### 5. Security First

- **No hardcoded secrets** — use `.env`, keyring, or Tauri secure storage
- **Validate all API inputs** — FastAPI Pydantic models for every endpoint body
- **Sanitize file paths** — all file operations must use `ALLOWED_AUDIO_ROOTS` sandboxing
- **Session tokens** — all system-level endpoints require `X-Session-Token` header
- **CORS** — locked to localhost only (never wildcard in prod)
- **No SQL string interpolation** — use SQLAlchemy ORM or parameterized queries
- **XSS** — never use `dangerouslySetInnerHTML`, always sanitize user-provided display strings

### 6. Modern Language Standards

**Python (3.10+)**:
- Type hints on all function signatures
- `async/await` for I/O-bound operations
- Pydantic v2 models for validation
- Pathlib over `os.path`
- f-strings over `.format()`

**TypeScript/React**:
- Functional components only (no class components)
- `const` over `let`, `let` over `var`
- Explicit return types on complex functions
- `useCallback`/`useMemo` where re-renders matter
- Tailwind CSS — no inline styles unless truly dynamic

**Rust**:
- Clippy clean (`cargo clippy -- -D warnings`)
- `?` operator over `.unwrap()` / `.expect()` in fallible paths
- Prefer `Arc<Mutex<T>>` over raw pointers for shared state
- Document all public Tauri commands with `/// # Errors` section

### 7. Update Docs After Every Change (MANDATORY)

All index files live in `.claude/docs/`. After **any** code change, update the relevant files — this is not optional:

| Changed area | Update these files |
|---|---|
| Any file added/renamed/deleted | `.claude/docs/FILE_MAP.md` |
| React components | `.claude/docs/frontend-index.md` + `FILE_MAP.md` |
| FastAPI routes or Python modules | `.claude/docs/backend-index.md` + `FILE_MAP.md` |
| Rust commands, modules, events | `.claude/docs/rust-index.md` + `FILE_MAP.md` |
| System data flows or architecture | `.claude/docs/architecture.md` |

Then commit: `git commit -m "type(scope): description"`

---

## Project-Specific Rules

### FastAPI Backend
- All endpoints under `/api/` prefix
- Return `{"status": "ok", "data": ...}` for success
- Return `{"status": "error", "message": "...", "code": "ERROR_CODE"}` for errors
- Use `BackgroundTasks` for operations > 500ms
- Never block the event loop — use `asyncio.run_in_executor` for CPU-bound work

### React Frontend
- Axios instance from `frontend/src/api/api.js` — never create raw `fetch` calls
- All API errors bubble through the Axios interceptors (handles 401/429 automatically)
- Toast notifications via `ToastContext` — never `alert()`
- Loading states required for every async operation
- Error boundaries wrap every lazy-loaded view

### Tauri IPC
- Tauri commands in `src-tauri/src/audio/commands.rs`
- Frontend invokes via `@tauri-apps/api/core`
- Commands must return `Result<T, String>` — never panic
- Long operations should emit progress events via `app.emit()`

### Audio Processing
- Never modify source files — all edits are non-destructive (stored as `.rbep` overlays)
- FFmpeg for format conversion — path in `app/config.py`
- Analysis results cached — don't re-analyze unchanged files
- Sample rate conversions use Rubato (Rust) or librosa (Python)

---

## Dev Environment

```bash
# Full dev stack (frontend + backend + tauri)
npm run dev:full

# Frontend only
npm run dev --prefix frontend    # Vite @ localhost:5173

# Backend only
python -m app.main               # FastAPI @ localhost:8000

# Tauri dev
npm run tauri dev                # Wraps Vite + Tauri

# Tests
cd frontend && npm test
cd app && pytest
cd src-tauri && cargo test
```

Key ports: Frontend `5173`, Backend `8000`, Tauri dev uses Vite proxy.

---

## File Organization Cheat Sheet

| What you need            | Where to look                          |
|--------------------------|----------------------------------------|
| React components         | `frontend/src/`                        |
| API calls (frontend)     | `frontend/src/api/api.js`              |
| DAW audio state          | `frontend/src/audio/DawState.js`       |
| FastAPI routes           | `app/main.py`                          |
| Business logic           | `app/services.py`                      |
| Rekordbox DB access      | `app/database.py`, `app/live_database.py` |
| SoundCloud integration   | `app/soundcloud_api.py`                |
| USB sync engine          | `app/usb_manager.py`                   |
| Rust audio engine        | `src-tauri/src/audio/`                 |
| Tauri commands           | `src-tauri/src/audio/commands.rs`      |
| OAuth/SoundCloud (Rust)  | `src-tauri/src/soundcloud_client.rs`   |
| Architecture overview    | `.claude/docs/architecture.md`         |
| Frontend component index | `.claude/docs/frontend-index.md`       |
| Backend module index     | `.claude/docs/backend-index.md`        |
| Rust command index       | `.claude/docs/rust-index.md`           |
