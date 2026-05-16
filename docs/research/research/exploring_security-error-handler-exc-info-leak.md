---
slug: security-error-handler-exc-info-leak
title: Global exception handler logs exc_info with potential path/PII leak
owner: tb
created: 2026-05-15
last_updated: 2026-05-15
tags: [security, follow-up, auth-audit-adjacent]
related: [security-api-auth-hardening]
---

# Global exception handler logs exc_info with potential path/PII leak

> **Caveman style.** Fragments, bullets. Drop articles/filler/hedges. No prose paragraphs. Respect per-section caps below.
> State = folder + filename prefix (not frontmatter). Lifecycle = audit trail. See `../README.md`.

## Lifecycle

- 2026-05-15 — `research/idea_` — scaffolded from auth-audit adjacent findings
- 2026-05-15 — `research/idea_` — section fill from thin scaffold
- 2026-05-15 — research/idea_ — rework pass (quality-bar review pre-exploring_)
- 2026-05-15 — research/exploring_ — promoted; quality-bar met (concrete RedactingFormatter spec; CPython 3.13.5 source verified; multi-handler caveat added)

---

## Problem

`app/main.py:264` (handler `app/main.py:261-268`): `logger.error(f"Unhandled Exception on {request.method} {request.url}: {exc}", exc_info=True)`. `safe_error_message()` (app/main.py:207-214) redacts paths in client response but NOT in log file. Stack traces in `./logs/app.log` retain absolute paths from `__file__` per frame, exception args echoed via `repr(...)`. Leak vectors: crash reports, antivirus quarantine, user-shared screenshots, support-bundle uploads. Need: log-side redaction (apply `safe_error_message` to log message + frame paths), OR rotate logs to user-protected dir only, OR drop full stack from log line (keep file+line only).

## Goals / Non-goals

**Goals**
- Apply `safe_error_message` redaction (or equivalent) to the persisted log message + formatted traceback, not just to client response body.
- Preserve debugging value: keep exception type, file:line per frame, function name, redacted exception string — enough for triage.
- Redact at log-write time (formatter/handler), not at call site — handler line stays `logger.error(..., exc_info=True)`, no caller refactor.
- Cover both `LogRecord.msg`/`args` (the `f"Unhandled Exception on {request.method} {request.url}: {exc}"` substring) and `LogRecord.exc_text` (the formatted traceback `exc_info=True` produces).
- Apply same scrubbing to `StreamHandler(stdout)` so terminal output during `npm run tauri dev` doesn't leak either.
- No regression on `RequestValidationError` handler (lines 248-252) which already redacts manually via formatted string.

**Non-goals**
- Don't drop `exc_info` entirely — kills frame info needed for bisecting rbox panics + `_db_write_lock` deadlocks.
- Don't migrate to `structlog` / JSON logging in this scope — separate refactor, large blast radius.
- Don't add log rotation/ACL hardening — orthogonal follow-up (see Open Question 3).
- Don't touch the `validate_audio_path` SECURITY warning at line 202 (it logs an attacker-controlled path on purpose for audit; redaction would defeat its purpose — different threat model).

## Constraints

External facts bounding solution (rate limits, data shape, perf budget, legal, capacity). Cite source.

- `safe_error_message` (app/main.py:207-214) only operates on `str(e)` — strips `APP_DIR`, `Path.home()`, `%APPDATA%`. It is NEVER applied inside the global handler at app/main.py:261-268; the redaction only runs at the (few) call sites that explicitly wrap response bodies.
- `logger.error(..., exc_info=True)` (app/main.py:264) dumps the FULL formatted traceback via `Formatter.formatException()` → `traceback.format_exception()`. Frame filenames are absolute paths from `__file__`. Locals are NOT included by default (CPython needs `tb_locals` opt-in), but file paths alone already leak install layout + user-folder.
- Logging is configured via `logging.basicConfig` at app/main.py:110-117: two handlers — `FileHandler(LOG_DIR / "app.log", encoding='utf-8')` and `StreamHandler(sys.stdout)`. `LOG_DIR = Path("./logs")` (app/config.py:8) — CWD-relative, no rotation policy, no ACL, no size cap.
- `app.log` lives wherever the sidecar is launched from (CWD-relative `./logs/app.log`). In Tauri prod, `src-tauri/src/main.rs:332-340` spawns the sidecar via `shell.sidecar("rb-backend")` WITHOUT setting `current_dir` — CWD inherits from the Tauri parent process (typically the install dir on Windows, e.g. `%LOCALAPPDATA%\<app>\` for the per-user installer flow, or `C:\Program Files\<app>\` for the machine-wide variant). In dev (`npm run dev:full` / `tauri dev`), CWD is the repo root → `./logs/app.log` sits inside the git working tree. All these locations are user-readable by any process running as the same user (incl. AV agents, telemetry, screenshare tools).
- Windows Error Reporting (WER) can capture process memory on crash — exception data lives there too, outside our log scope. Mitigation requires `WerAddExcludedApplication` or registry exclusion — out of scope here.
- `LogRecord.exc_text` is populated lazily by `Formatter.format()` (CPython 3.10+, verified against `logging/__init__.py` `Formatter.format`) on first emit via `self.formatException(record.exc_info)`, then cached on the record. **Multi-handler order matters:** `Logger.callHandlers` iterates `self.handlers` in list order; whichever handler's formatter runs FIRST populates the cache. Subsequent handlers reuse that cache verbatim — so EITHER both handlers must share the same redacting Formatter instance (or class), OR the first handler in `basicConfig(handlers=[…])` must be the redacting one. Mixed config = leak in the un-redacted handler.
- Python `logging` is sync; redaction must be O(n) over the formatted traceback string. With current `safe_error_message` doing 3 `str.replace` per call, that's negligible (<1ms for typical 5kB traceback).
- The `%(message)s` format string at app/main.py:112 controls only the leading line. The full traceback is appended by the Formatter AFTER `%(message)s` is rendered, via `formatException` → joined with `\n`. So an override of `Formatter.format()` (not just the format string) is required.

## Open Questions

Numbered. Each resolvable (yes/no or X vs Y), not philosophy.

1. Scrub the WHOLE formatted traceback string (one `safe_error_message` pass over the joined output), or walk each `traceback.FrameSummary` and rewrite `filename` per frame? Whole-string is simpler + catches paths appearing in exception args; per-frame is more precise but misses paths embedded in custom `__repr__` of exception objects.
2. Keep `exc_info=True` at the call site (let the Formatter redact downstream), or drop to `exc_info=False` + manually log `f"{type(exc).__name__}: file={tb.tb_frame.f_code.co_filename}:{tb.tb_lineno}"`? Former preserves full triage value; latter is bulletproof but loses chained exceptions (`__cause__`/`__context__`).
3. Move `app.log` to `%APPDATA%/MusicLibraryManager/logs/` with per-user ACL (Windows ICACLS), or leave CWD-relative + rely solely on redaction? ACL hardening is a defense-in-depth complement, not a replacement.
4. Add a `logging.Filter` subclass that recursively scrubs `LogRecord.args` (in case future code passes paths via `%s` interpolation) — yes always-on, or only on the global-exception logger? Always-on is safer; risks over-redacting intentional path logs (e.g. `validate_audio_path` security warning at line 202).
5. Should redaction expand beyond `APP_DIR` / `Path.home()` / `%APPDATA%` to also cover `EXPORT_DIR`, `MUSIC_DIR`, `TEMP_DIR`, and entries in `ALLOWED_AUDIO_ROOTS` (which include user-configured drive paths)?
6. Apply same Formatter to ALL loggers via root config, or only to the `APP_MAIN` logger? Subloggers (`uvicorn`, `fastapi`, `httpx`) may emit their own tracebacks under `exc_info=True` — narrow scope misses those.
7. Add a log-rotation policy (`RotatingFileHandler` with size cap + retention) in the same change, or split to a separate idea? Argues for split — orthogonal threat model.
8. Strip locals from frames pre-emptively (set `sys.tracebacklimit` or override `Formatter.formatException`)? Currently locals are NOT serialized, but a future tweak to `tb_locals=True` for debugging would re-introduce the leak silently.

## Findings / Investigation

Dated subsections, append-only. ≤80 words each. Never edit past entries — supersede.

### 2026-05-15 — initial scope
- Call site confirmed: app/main.py:261-268 — single `@app.exception_handler(Exception)`; logs via module logger `APP_MAIN`.
- Redactor confirmed: app/main.py:207-214 — `safe_error_message(e)` operates on `str(e)` only, replaces `APP_DIR` / `Path.home()` / `%APPDATA%` with `[...]`. Never called inside global handler.
- Log destination confirmed: app/main.py:110-117 — `basicConfig` with `FileHandler(LOG_DIR / "app.log")` + `StreamHandler(stdout)`. `LOG_DIR = Path("./logs")` (app/config.py:8). No rotation, no ACL.
- `traceback.format_exception()` output structure: header (`Traceback (most recent call last):`) + per-frame block (`  File "<absolute_path>", line <n>, in <func>\n    <source>`) + final `<ExcType>: <str(exc)>`. Locals excluded by default.
- `logging.LogRecord.exc_text` lifecycle: populated by `Formatter.format()` on first emit via `self.formatException(record.exc_info)`, then cached on the record so subsequent handlers reuse the cached string.
- Fix sketch (prose only): subclass `logging.Formatter`, override `format(record)` — call `super().format(record)` to populate/cache `exc_text`, then run `safe_error_message` on `record.exc_text` AND on the returned formatted string, return the scrubbed copy. Wire by replacing the `format=` kwarg in `basicConfig` with explicit handler setup that assigns the custom Formatter to both `FileHandler` and `StreamHandler`. Optionally extend `safe_error_message` to cover `EXPORT_DIR`, `MUSIC_DIR`, `TEMP_DIR` (see OQ5).

## Options Considered

Required by `evaluated_`. Per option: sketch ≤3 bullets, pros, cons, S/M/L/XL, risk.

### Option A — Custom Formatter scrubbing exc_text (recommended)
- Sketch:
  - New class `RedactingFormatter(logging.Formatter)` in `app/main.py` (or a new `app/logging_utils.py`); override `format()` to call `super().format(record)` (which populates `record.exc_text` if not already), then run `safe_error_message` on the returned string AND overwrite `record.exc_text` with the scrubbed substring to prevent leak via cache-reuse by downstream handlers.
  - Replace the `format=` kwarg in `basicConfig` (app/main.py:110-117) with explicit `FileHandler` + `StreamHandler` instances, BOTH assigned the SAME `RedactingFormatter` instance (per Constraint: first formatter wins on `exc_text` cache).
  - Optionally widen `safe_error_message` to also strip `EXPORT_DIR`, `MUSIC_DIR`, `TEMP_DIR` (resolves OQ5).
- Pros: minimal blast radius — net diff ~+25 lines (new class ~15, basicConfig rewrite ~8, plus reuse of `safe_error_message`); catches both `%(message)s` and `exc_text` in one place; works for the root logger so sub-loggers (`fastapi`, `uvicorn`, `httpx`) inherit if root config carries it (resolves OQ6); preserves `exc_info=True` debug value; no caller refactor; existing redactor reused (single source of truth).
- Cons: doesn't drop entire records (no policy control); SHARED-formatter requirement is load-bearing — if a future change attaches a second handler with a plain `Formatter()`, the cache-write order may leak (mitigation: document invariant in class docstring + assert in basicConfig); if `LogRecord` is pickled (multiproc queue, e.g. `app/anlz_safe.py` ProcessPoolExecutor child output), scrubbing happens on the consumer side — currently moot (child workers use module-level `getLogger(__name__)` and their stderr is captured by parent stream handler) but a future risk.
- Effort: S.
- Risk: Low. Pure formatting layer, no behavior change for non-exception logs. Confirmable via unit test: emit a synthetic `logger.error("boom %s", APP_DIR, exc_info=ValueError(APP_DIR))` to a `StringIO`-backed handler with `RedactingFormatter`, assert `[...]` appears and `APP_DIR` substring does not.

### Option B — Custom logging.Filter at handler level
- Sketch:
  - `RedactingFilter(logging.Filter)` subclass; `filter(record)` returns True after mutating `record.msg`, `record.args`, `record.exc_text` in place (must force-format via `logging.Formatter().formatException(record.exc_info)` if `exc_text` is None at filter time, then assign the scrubbed string to `record.exc_text` so the downstream handler's formatter sees the cache and skips re-formatting).
  - Attach filter to both `FileHandler` and `StreamHandler`.
- Pros: can drop records entirely (return False) — useful for blocklisting noisy paths; filter API is conceptually familiar; can chain multiple filters in order.
- Cons: Filters run BEFORE the handler's Formatter (per `Handler.handle` → `Handler.filter` → `Handler.emit` → `Formatter.format`), so `record.exc_text` is always `None` at filter time — the filter must instantiate a throwaway `Formatter` and call `formatException` itself, which duplicates the work the real Formatter is about to do (Constraint: `exc_text` will then be reused from cache, so it's not double-work at runtime, but it IS code that conceptually mirrors Formatter responsibilities). `record.msg` may be a `%s`-template with raw paths in `record.args` — must scrub BOTH (`getMessage()` rendering happens inside `Formatter.format`, not in the filter). Larger net diff: ~+35 lines (filter class + helper + attach to two handlers).
- Effort: S–M.
- Risk: Medium. Easy to forget that `record.args` carries lazy-format substitutions → ends up scrubbing only `record.msg` template but leaving raw paths in `args` that the formatter then interpolates back in.

### Option C — Replace stdlib logging with structlog
- Sketch:
  - Add `structlog` dep; configure processor chain with a custom `redact_paths` processor running `safe_error_message` over event dict values.
  - Refactor every `logger.X(...)` call site across `app/` to structured `log.X("event", key=value)` form.
- Pros: structured logs are easier to consume; redaction is a first-class processor concern; ergonomic for JSON output (better support-bundle UX); aligns with Schicht-A hardening direction long-term.
- Cons: huge refactor — `app/` has ~hundreds of `logger.X` calls; structlog adds a runtime dep (Schicht-A pinning gate, security audit); breaks existing log-line format assumptions in `tests/` (any test that greps log lines); orthogonal to the immediate leak fix.
- Effort: XL.
- Risk: High. Touches every module. Would need its own research doc + sign-off — not warranted by a single-handler leak.

## Recommendation

Required by `evaluated_`. ≤80 words. Which option + what blocks commit.

**Option A** — `RedactingFormatter(logging.Formatter)` in new `app/logging_utils.py`; override `format()` → `super().format(record)` then `safe_error_message` over result AND `record.exc_text` (defeats cache-reuse leak). Rewrite `basicConfig` (app/main.py:110-117) as explicit `FileHandler` + `StreamHandler` sharing one Formatter instance, attached to root logger (covers `fastapi`/`uvicorn`/`httpx` — resolves OQ6). Widen `safe_error_message` to `EXPORT_DIR`/`MUSIC_DIR`/`TEMP_DIR` (OQ5).

**First step:** create `app/logging_utils.py:RedactingFormatter` + `tests/test_logging_redaction.py` (synthetic `ValueError(APP_DIR)`, assert `[...]` in output, `APP_DIR` absent). **Gates before `evaluated_`:** (a) resolve OQ1 (pick whole-string scrub); (b) confirm no `tests/` asserts on log-line shape — already checked: no `caplog`/`asctime` matches in `tests/`, safe. Log rotation/ACL → split idea (OQ3, OQ7).

---

## Implementation Plan

Required from `implement/draftplan_`. Concrete enough that someone else executes without re-deriving.

### Scope
- **In:** …
- **Out:** …

### Step-by-step
1. …

### Files touched
- …

### Testing
- …

### Risks & rollback
- …

## Review

Filled at `review_`. Unchecked box or rework reason → `rework_`.

- [ ] Plan addresses all goals
- [ ] Open questions answered or deferred
- [ ] Risk mitigations defined
- [ ] Rollback path clear
- [ ] Affected docs identified (`architecture.md`, `FILE_MAP.md`, indexes, `CHANGELOG.md`)

**Rework reasons:**
- …

## Implementation Log

Filled during `inprogress_`. Dated entries. What built / surprised / changed-from-plan.

### YYYY-MM-DD
- …

---

## Decision / Outcome

Required by `archived/*`.

**Result**: implemented | superseded | abandoned
**Why**: …
**Rejected alternatives:**
- …

**Code references**: PR #…, commits …, files …

**Docs updated** (required for `implemented_`):
- [ ] `docs/architecture.md`
- [ ] `docs/FILE_MAP.md`
- [ ] `docs/backend-index.md` (if backend changed)
- [ ] `docs/frontend-index.md` (if frontend changed)
- [ ] `docs/rust-index.md` (if Rust/Tauri changed)
- [ ] `CHANGELOG.md` (if user-visible)

## Links

- Code: <file:line or PR>
- External docs: <url>
- Related research: <slugs>
