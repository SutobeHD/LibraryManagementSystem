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
- 2026-05-15 — research/exploring_ — perfect-quality rework loop (deep self-review pass)

---

## Problem

Global handler `app/main.py:261-268` line 264: `logger.error(f"Unhandled Exception on {request.method} {request.url}: {exc}", exc_info=True)`. `safe_error_message()` (`app/main.py:207-214`) redacts paths in client response body but is **never** called inside the handler — only by select route bodies. Stack traces in `./logs/app.log` (FileHandler at `app/main.py:114`, `LOG_DIR` from `app/config.py:8`) retain absolute paths from per-frame `__file__`, plus `str(exc)` may embed paths via exception args. Leak vectors: crash uploads, AV quarantine ingestion, user-shared screenshots, support-bundle exports. Fix: log-write-time redaction (custom `Formatter.format` overrides `record.exc_text` + final string with `safe_error_message`).

## Goals / Non-goals

**Goals**
- Apply `safe_error_message`-equivalent redaction to the persisted log line + formatted traceback. Coverage: `record.exc_text` (cache mutation in place, protects sibling handlers) + final returned string (catches `record.msg` and `record.args`-interpolated content after `super().format` runs `record.getMessage()`).
- Preserve triage value: exception type, file:line per frame, function name, redacted exception string — keep `exc_info=True` chain intact.
- Redact at log-write time inside a custom `Formatter.format`; the call site `app/main.py:264` stays unchanged.
- Apply to ALL handlers (FileHandler + StreamHandler) — terminal output during `npm run tauri dev` must not leak. Implementation pre-sets one shared `RedactingFormatter` instance on every handler before `basicConfig`; basicConfig's `if h.formatter is None` guard (CPython 3.13.5 `Lib/logging/__init__.py` L110) leaves it intact.
- Cover sub-loggers (`uvicorn`, `fastapi`, `httpx`) — guaranteed automatically since `basicConfig` configures root and they propagate.
- Zero regression on `RequestValidationError` handler (`app/main.py:248-252`): its message is constructed without `exc_info`, so it travels through the same Formatter but has no `exc_text` block to scrub; output unchanged.
- Widen `safe_error_message` to also strip `EXPORT_DIR`, `MUSIC_DIR`, `TEMP_DIR` (`app/config.py:7,9,10`) — these appear in `ALLOWED_AUDIO_ROOTS` and surface in audio-stack tracebacks.

**Non-goals**
- Drop `exc_info` — destroys chained-exception info needed for rbox-panic + `_db_write_lock` triage.
- Migrate to `structlog` / JSON logging — 730 logger call sites in `app/` (verified count); separate XL refactor.
- Add log rotation, ACL hardening, or WER exclusion — separate threat models, follow-up ideas (PARKED OQ3 + OQ7).
- Modify the `validate_audio_path` SECURITY warning (`app/main.py:202`): attacker-controlled path is logged intentionally for audit, and the redactor leaves it untouched anyway (path does not match `APP_DIR`/`Path.home()`/`%APPDATA%`).
- Per-frame `FrameSummary` rewrite — whole-string scrub catches more cases at less code (PARKED-resolved OQ1).

## Constraints

External facts bounding solution. All claims re-verified file:line and against `Lib/logging/__init__.py` from CPython 3.13.5 (`logging.__file__` = `C:\Users\tb\AppData\Local\Programs\Python\Python313\Lib\logging\__init__.py`).

- `safe_error_message` (`app/main.py:207-214`) operates on `str(e)`; strips `APP_DIR` (`app/main.py:120`, `os.path.dirname(os.path.abspath(__file__))`), `str(Path.home())`, `os.environ['APPDATA']`. Never invoked in global handler (`app/main.py:261-268`). Empirically verified on a synthetic `ValueError('Bad path: {APP_DIR}/foo.py')`: post-scrub output reads `ValueError: Bad path: [...]/foo.py`.
- `logger.error(..., exc_info=True)` at `app/main.py:264` dumps full formatted traceback through `Formatter.formatException()` → `traceback.format_exception()`. Per-frame absolute paths from `__file__`. Locals NOT serialized by default (would need `tb_locals=True` opt-in on `traceback.TracebackException` — not used here). Absolute paths alone leak install layout + Windows user folder.
- Logging configured via `logging.basicConfig` at `app/main.py:110-117`: two handlers — `FileHandler(LOG_DIR / "app.log", encoding='utf-8')` (`app/main.py:114`) + `StreamHandler(sys.stdout)` (`app/main.py:115`). `LOG_DIR = Path("./logs")` (`app/config.py:8`); `LOG_DIR.mkdir(exist_ok=True)` runs at import (`app/config.py:15`). CWD-relative. No rotation/ACL/size cap. No `RotatingFileHandler`/`TimedRotatingFileHandler` anywhere in `app/` (only used in `app/usb_manager.py` for an unrelated rotated handler).
- **`basicConfig` formatter-attachment behavior (CPython 3.13.5 `Lib/logging/__init__.py` L109-112, verified):**
  ```
  for h in handlers:
      if h.formatter is None:
          h.setFormatter(fmt)
      root.addHandler(h)
  ```
  Conclusion: pre-setting our `RedactingFormatter` on each handler BEFORE calling `basicConfig(handlers=[fh, sh], …)` survives — basicConfig won't overwrite it. (Empirically also verified: when handlers carry no pre-set formatter, basicConfig assigns the SAME instance to all of them, so either wiring style works; the pre-set form is the more explicit choice the Recommendation adopts.)
- `app.log` path resolves against process CWD. In Tauri prod, `src-tauri/src/main.rs:335` spawns the sidecar via `shell.sidecar("rb-backend")` with no `current_dir` set — child inherits parent CWD (Windows: install dir, e.g. `%LOCALAPPDATA%\<app>\` per-user or `C:\Program Files\<app>\` machine-wide). Dev (`npm run dev:full` / `tauri dev`): CWD is repo root → `./logs/app.log` sits inside the git working tree. All locations user-readable by any same-uid process (AV agents, telemetry, screenshare).
- Windows Error Reporting can capture process memory on crash — exception data lives outside our log scope. Mitigation requires `WerAddExcludedApplication` registry entry. Out of scope.
- `LogRecord.exc_text` lifecycle (CPython 3.13.5 `Lib/logging/__init__.py` `Formatter.format`, verified via `inspect.getsource`): inside `format()`, if `record.exc_info` set and `record.exc_text` falsy → assigns `record.exc_text = self.formatException(record.exc_info)`. Once populated, every subsequent handler skips the re-format and concatenates the cached string verbatim. Empirically confirmed: 2-handler setup with distinct Formatter subclasses — handler-1 sees `exc_text is None` pre-format, handler-2 sees populated `exc_text` pre-format and reuses the cache. **Implication:** if EITHER handler's formatter scrubs and the OTHER doesn't, the un-scrubbed one wins whichever runs FIRST in `self.handlers` list order (`Logger.callHandlers` iterates `c.handlers` in insertion order). Mitigation: scrub MUST mutate `record.exc_text` in place AND scrub returned string.
- Root vs APP_MAIN logger: `basicConfig` attaches handlers to **root**. `getLogger("APP_MAIN")` has `propagate=True` (default), so APP_MAIN records bubble to root handlers — empirically confirmed (`APP_MAIN.handlers == []`, `root.handlers == [...]`). Sub-loggers `uvicorn`, `fastapi`, `httpx` also propagate to root by default. **Therefore a root-level formatter swap covers every logger automatically** — resolves OQ6 (see below).
- Python `logging` is sync. Redaction cost: 3 `str.replace` on a 1380-byte synthetic traceback = **0.46 µs per call** (1000-iter timing). Negligible relative to disk-write latency.
- `%(message)s` (format string at `app/main.py:112`) covers only the leading line. Traceback is appended AFTER `formatMessage(record)` returns, via the `if record.exc_text:` block in `Formatter.format`. So a `format`-string-only change cannot scrub the traceback — must subclass `Formatter` and override `format()`.

## Open Questions

All resolved in-line OR explicitly PARKED with reason.

1. **RESOLVED — whole-string scrub.** One `safe_error_message` pass over the string returned by `super().format(record)`, mirrored onto `record.exc_text`. Reasons: catches paths inside exception args + custom `__repr__` (per-frame rewrite misses these), single pass = O(n), code shape mirrors existing `safe_error_message` callers.
2. **RESOLVED — keep `exc_info=True`.** Manual `tb.tb_frame...` form drops chained exceptions (`__cause__`/`__context__`) — recently load-bearing for diagnosing rbox-panic chains and `_db_write_lock` re-raises. Formatter-side scrub preserves chain info.
3. **PARKED — split idea.** Filesystem ACL hardening (`%APPDATA%/MusicLibraryManager/logs/` + ICACLS) is defense-in-depth, separate threat model (file-permission boundary vs log-content boundary). Reason: orthogonal scope, separate testing surface, would bloat this change. **Action:** scaffold follow-up idea `security-app-log-acl` post-implementation.
4. **RESOLVED — scrub `record.args` indirectly via the final-string pass, not via separate Filter.** Reason: Filter runs BEFORE Formatter (`Handler.handle` → `filter` → `emit` → `format`), so `exc_text` is still `None` at filter time and Filter would have to duplicate Formatter work. The recommended pseudocode (`return safe_error_message_str(super().format(record))`) catches args automatically: `super().format` calls `record.getMessage()` which interpolates args into the message string, and the final-string scrub then strips matching paths from the interpolated result. No need to mutate `record.args` directly. The `validate_audio_path` warning at `app/main.py:202` is INSIDE the message string (f-string at call site, not `args`), so the always-on scrub does not affect it — and even if a future caller used `args`, the path it shows is an attacker-controlled value, which the scrubber leaves untouched (those paths do not match `APP_DIR`/`Path.home()`/`%APPDATA%`).
5. **RESOLVED — extend `safe_error_message` to `EXPORT_DIR`, `MUSIC_DIR`, `TEMP_DIR`.** These are all already CWD-relative `./exports` `./music` `./temp_uploads` (`app/config.py:7,9,10`); their `.resolve()` form appears in `ALLOWED_AUDIO_ROOTS` (`app/main.py:144-146`) and would surface in traceback frames touching audio code. **PARKED — per-user drive entries in `ALLOWED_AUDIO_ROOTS` (D:/Music, etc.):** dynamic, change at runtime, scrubbing them needs an iterable lookup not a static const. Acceptable risk for now (paths are user's own filesystem layout, less PII-loaded than `~/`).
6. **RESOLVED — root-level Formatter.** `basicConfig` attaches to root, `APP_MAIN`/`uvicorn`/`fastapi`/`httpx` all `propagate=True` by default (empirically confirmed: `getLogger('APP_MAIN').handlers == []` post-basicConfig). Therefore a single Formatter on root's handlers covers every sub-logger automatically. No per-logger plumbing needed.
7. **PARKED — log rotation as separate idea.** `RotatingFileHandler` size cap + retention is a separate threat model (disk-fill DoS vs content-leak). Will scaffold `security-log-rotation-policy` follow-up post-implementation.
8. **RESOLVED — no preemptive locals strip.** Current code does not enable `tb_locals=True`; default `Formatter.formatException` calls `traceback.TracebackException(..., capture_locals=False)`. Adding a `formatException` override now is dead code. **Action:** add a code comment + lint-style assertion in `RedactingFormatter.__init__` documenting that any future `capture_locals=True` flip would re-introduce a leak vector and needs paired widening of `safe_error_message`.

## Findings / Investigation

Dated subsections, append-only. ≤80 words each. Never edit past entries — supersede.

### 2026-05-15 — initial scope
- Call site: `app/main.py:261-268` — single `@app.exception_handler(Exception)`; logs via `APP_MAIN` logger.
- Redactor: `app/main.py:207-214` — `safe_error_message(e)` on `str(e)`, replaces `APP_DIR`/`Path.home()`/`%APPDATA%` with `[...]`. Not called inside global handler.
- Logging: `basicConfig` at `app/main.py:110-117` with `FileHandler(LOG_DIR/"app.log")` + `StreamHandler(stdout)`. `LOG_DIR = Path("./logs")` (`app/config.py:8`). No rotation/ACL.
- `traceback.format_exception()` output: header + per-frame `File "<abs_path>", line N, in <func>\n    <source>` + final `<ExcType>: <str(exc)>`. Locals omitted by default.
- `LogRecord.exc_text` lifecycle: populated by `Formatter.format` first call, then cached; subsequent handlers reuse.

### 2026-05-15 — CPython source + behavioral verification
- `Lib/logging/__init__.py` `Formatter.format` (CPython 3.13.5, `logging.__file__` at `…\Python313\Lib\logging\__init__.py`, verified via `inspect.getsource`): lines (paraphrased) `if record.exc_info: if not record.exc_text: record.exc_text = self.formatException(record.exc_info)`. Cache-write happens iff `exc_info` set AND `exc_text` falsy — so populates exactly once across all handlers. `Logger.callHandlers` iterates `c.handlers` in insertion order — empirically confirmed (handler 1 sees `exc_text is None`; handler 2 sees populated cache, length 120 bytes).
- `basicConfig(handlers=[h1, h2])` empirically assigns the **same Formatter instance** (`id(h1.formatter) == id(h2.formatter)`) to both when neither has a pre-set formatter. So a single Formatter swap in basicConfig propagates to every handler.
- `getLogger("APP_MAIN").handlers == []` post-basicConfig; `propagate=True` (default). Sub-loggers `uvicorn`, `fastapi`, `httpx` likewise. Root-level formatter covers them.
- Round-trip scrub test: `ValueError(f'Bad path: {APP_DIR}/foo.py')` → `traceback.format_exception` → 3× `str.replace` → `ValueError: Bad path: [...]/foo.py`. Confirmed regex-free string operations suffice.
- Perf: 3 `str.replace` on a 1380-byte synthetic traceback = **0.46 µs / call** (1000-iter timing). Spec'd ≤1ms; actual is ~2000× headroom.

### 2026-05-15 — net diff sizing
- `RedactingFormatter` class skeleton (new file `app/logging_utils.py`): ~25 lines including docstring with multi-handler-order invariant note.
- `safe_error_message` widening to `EXPORT_DIR`/`MUSIC_DIR`/`TEMP_DIR`: +3 entries in the `for sensitive in [...]` list, +1 import line. Net ~+4 lines, `app/main.py:207-214`.
- `basicConfig` swap at `app/main.py:110-117`: replace `format=...` kwarg with explicit pre-built `RedactingFormatter(fmt=...)` instance attached via `handlers=[h1, h2]` (h1, h2 created inline; basicConfig auto-shares the formatter). Net diff ~+6 / -1 lines.
- Test file `tests/test_logging_redaction.py` (new): one `StringIO`-handler fixture + 4 assertions (scrub in `record.exc_text`; scrub in returned string; `APP_DIR` substring absent; chained-exception preserves chain). ~50 lines.
- **Total estimated diff:** ~+85 / -1 lines across 3 files. Single commit feasible.

### 2026-05-15 — net diff sizing (revised, supersedes prior entry)
Switching wiring approach from "basicConfig auto-shares formatter" to "pre-set formatter before basicConfig" — both work, but pre-set is more explicit, doesn't rely on basicConfig internals, and survives any future config refactor.
- `app/logging_utils.py` (new): `safe_error_message_str` (~6 lines) + `RedactingFormatter` (docstring + ~5-line `format` override) → ~30 lines total.
- `app/main.py:110-117` rewrite to pre-set-formatter pattern: ~+6 / -1 lines net.
- `app/main.py:207-214` body refactor to delegate via `safe_error_message_str`: ~-7 / +2 lines net.
- `tests/test_logging_redaction.py` (new): StringIO fixture + 4 cases → ~60 lines.
- **Revised total estimated diff:** ~+98 / -8 lines across 3 source files + 1 test file. Single commit feasible.

### 2026-05-15 — multi-handler-order verification matrix
| First handler's formatter | Second handler's formatter | Leak in handler 2? |
|---|---|---|
| RedactingFormatter (scrubs `exc_text` + returns scrubbed string) | RedactingFormatter (same instance) | No — both scrubbed |
| Plain Formatter | RedactingFormatter | **Yes** — first emit writes un-scrubbed `exc_text` to cache; second's super().format reads cache, returns scrubbed string for handler 2, but handler 1's stream already received raw paths. |
| RedactingFormatter | Plain Formatter | **Safe** — RedactingFormatter mutates `record.exc_text` after super().format; handler 2's super().format reads the scrubbed cache + concatenates. Required mutation order: `super().format(record)` THEN `record.exc_text = safe_error_message_str(record.exc_text)`. |
- **Invariant chosen by recommended wiring:** all handlers carry the same `RedactingFormatter` instance, AND the formatter mutates `record.exc_text` after `super().format`. Both protections are independently sufficient (rows 1 + 3 above); having both makes the implementation robust against a future contributor adding a non-redacting handler.

## Options Considered

Per option: sketch ≤3 bullets, pros, cons, effort (hours), behavior diff, maintenance debt, risk.

### Comparison table

| | Option A — Formatter | Option B — Filter | Option C — structlog |
|---|---|---|---|
| Effort (hours) | ~3-4h (code + 4 unit tests + manual verify + doc-syncer) | ~5-6h (filter + dup-formatter helper + 2 attach sites + tests) | ~30-50h (730-site refactor + dep audit + test-format migration) |
| Net diff | ~+85 / -1 lines, 3 files | ~+100 / -1 lines, 3 files | ~+1500 / -1500 lines, ~60 files |
| Behavior diff (functional) | None for non-exception logs; tracebacks scrubbed | Same as A | Log line shape changes from `%(message)s` to JSON / kv; downstream parser break |
| Behavior diff (debugging) | Identical traceback minus literal sensitive paths | Identical | Tracebacks now structured; learning curve |
| Maintenance debt | Low — single class, mirrors existing `safe_error_message` | Medium — duplicate `formatException` helper drifts vs stdlib | High — new dep, Schicht-A pin + CVE check ongoing |
| Touch surface | `app/main.py:110-117`, `app/main.py:207-214`, new `app/logging_utils.py` | Same + filter-attach calls | Every `app/*.py` with `logger.X` |
| Risk | Low | Medium | High |

### Option A — Custom Formatter scrubbing exc_text (RECOMMENDED)
- Sketch:
  - New class `RedactingFormatter(logging.Formatter)` in new `app/logging_utils.py`. Override `format(record)`: call `super().format(record)`, mutate `record.exc_text = safe_error_message_str(record.exc_text)` if non-empty, return `safe_error_message_str(super_result)`.
  - Pre-set one `RedactingFormatter(fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s')` instance on both `FileHandler` and `StreamHandler` before calling `basicConfig(handlers=[fh, sh], level=INFO)`. basicConfig's `if h.formatter is None` guard (`Lib/logging/__init__.py` L110) leaves our pre-set formatter alone.
  - Widen `safe_error_message` (`app/main.py:207-214`) to include `str(EXPORT_DIR.resolve())`, `str(MUSIC_DIR.resolve())`, `str(TEMP_DIR.resolve())` (via new `safe_error_message_str` helper in `app/logging_utils.py`).
- Pros: minimal blast radius (~+85 lines, 3 files); catches `%(message)s` line + `exc_text` cache in one place; root-level config covers `uvicorn`/`fastapi`/`httpx` automatically; preserves `exc_info=True` triage value; no caller refactor; reuses existing redactor (single source of truth).
- Cons: depends on every handler attached to root carrying the `RedactingFormatter` (single docstring-documented invariant; cache-mutation makes the order of any sibling handler with a plain Formatter still safe — see Findings matrix row 3); record-pickling across `ProcessPoolExecutor` boundaries (`app/anlz_safe.py`) bypasses scrubbing on the producer side — currently moot (child stderr is captured raw by parent stream handler, then re-emitted through parent's RedactingFormatter), but a future child using `QueueHandler` + `pickle` needs scrubbing on the consumer.
- Effort: ~3-4 hours (code + 4 unit tests + manual route-crash verify + 1 doc-syncer pass).
- Risk: Low. Pure formatting layer. Unit test: `RedactingFormatter` against `StringIO` handler with `ValueError(APP_DIR)` confirms `[...]` present and `APP_DIR` absent in output.

### Option B — Custom logging.Filter at handler level
- Sketch:
  - `RedactingFilter(logging.Filter)` subclass; `filter(record)` mutates `record.msg`, scrubs each `record.args` element, force-instantiates `logging.Formatter().formatException(record.exc_info)` and pre-populates `record.exc_text` with the scrubbed version (so downstream Formatter sees cache hit and skips re-format).
  - Attach the filter to both `FileHandler` and `StreamHandler`.
- Pros: can drop entire records (return False) for blocklist use cases; familiar API.
- Cons: filter runs BEFORE Formatter (`Handler.handle` → `filter` → `emit` → `format`), so `exc_text` is always `None` at filter time → must instantiate a throwaway Formatter + call `formatException` itself (duplicates stdlib work; brittle if stdlib changes `formatException` semantics). `record.args` interpolation happens inside `Formatter.format` via `record.getMessage()`, so filter must scrub both `args` and `msg` separately. More moving parts.
- Effort: ~5-6 hours.
- Risk: Medium. Easy regression vector: forget to scrub `args`; `record.getMessage()` then re-interpolates raw paths back into `%(message)s` output.

### Option C — Replace stdlib logging with structlog
- Sketch:
  - Add `structlog` dep (pin-and-audit gate per `.claude/rules/coding-rules.md`); configure processor chain with `redact_paths` processor invoking `safe_error_message`.
  - Refactor 730 `logger.X(...)` call sites in `app/` to structured `log.X("event", key=value)` form.
- Pros: structured logs simplify support-bundle parsing; redaction is a first-class processor; aligns with hypothetical Schicht-B JSON-logging direction.
- Cons: 730 call-site refactor; new runtime dep (Schicht-A pin + CVE-check obligation); breaks any test that asserts on log-line shape (already checked: none in `tests/`, but adds drag); orthogonal to immediate single-handler leak fix.
- Effort: ~30-50 hours.
- Risk: High. Touches every module. Needs own research doc + sign-off. Not warranted by the targeted leak.

## Recommendation

**Option A — RedactingFormatter.** Pre-set one `RedactingFormatter` instance on each root handler before `basicConfig` (basicConfig's `if h.formatter is None` guard, CPython `Lib/logging/__init__.py` L110, leaves it untouched). Root-level config carries scrubbing to every propagating sub-logger automatically (`uvicorn`/`fastapi`/`httpx` all `propagate=True`). `exc_text` cache mutation inside the override defeats handler-order leak even if a future change attaches a second handler with a non-redacting formatter. All open questions resolved or PARKED with split-idea reasons. Diff ~+98 / -8 lines across new `app/logging_utils.py`, `app/main.py:110-117`, `app/main.py:207-214`. Single atomic commit.

**Exact class shape (pseudocode, ~10 lines body):**

```
# app/logging_utils.py
class RedactingFormatter(logging.Formatter):
    """Scrubs absolute paths from log lines + cached tracebacks.
    Invariant: must be the formatter on EVERY handler attached to the root
    logger; otherwise exc_text cache (populated by first formatter to run,
    per CPython Logger.callHandlers iteration order) leaks raw paths to any
    handler whose formatter doesn't also scrub the cached string.
    Do NOT flip capture_locals=True anywhere without widening
    safe_error_message_str scope — locals freely embed paths."""
    def format(self, record):
        s = super().format(record)               # populates record.exc_text cache (first call only)
        if record.exc_text:
            record.exc_text = safe_error_message_str(record.exc_text)  # patch cache for sibling handlers
        return safe_error_message_str(s)         # scrub final string unconditionally
```

**Wiring change (`app/main.py:110-117`) — pre-set formatter so basicConfig respects it:**

```
_fmt = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
_red = RedactingFormatter(fmt=_fmt)
_fh = logging.FileHandler(LOG_DIR / "app.log", encoding='utf-8'); _fh.setFormatter(_red)
_sh = logging.StreamHandler(sys.stdout);                          _sh.setFormatter(_red)
logging.basicConfig(level=logging.INFO, handlers=[_fh, _sh])
# basicConfig (CPython 3.13.5 Lib/logging/__init__.py L110: `if h.formatter is None`)
# skips its default formatter when ours is already attached. Same instance on both
# handlers guarantees cache-write is scrubbed before any handler emits.
```

**First step:** scaffold `app/logging_utils.py` + `tests/test_logging_redaction.py`. **No gates remaining** — `tests/` empty of log-shape asserts (verified: zero `caplog` / `asctime` / `app.log` / `FileHandler` matches under `tests/`). Log rotation, ACL, WER exclusion → PARKED follow-up ideas.

---

## Implementation Plan

Seeded ahead of `implement/draftplan_` because all gates resolved. Concrete enough that someone else executes without re-deriving.

### Scope
- **In:**
  - New module `app/logging_utils.py` containing `RedactingFormatter` + `safe_error_message_str` (string-only variant of `safe_error_message`, since `record.exc_text`/the formatted message are already strings, not exceptions).
  - Edit `app/main.py:207-214` — widen `safe_error_message` path list to include `EXPORT_DIR.resolve()`, `MUSIC_DIR.resolve()`, `TEMP_DIR.resolve()`; refactor body to delegate to `safe_error_message_str` so the two helpers share replacement-list logic.
  - Edit `app/main.py:110-117` — rewrite to construct `FileHandler` + `StreamHandler` with pre-set `RedactingFormatter` instance, then call `basicConfig(handlers=[fh, sh], level=INFO)`. The `format=` kwarg is removed because the formatter is already attached.
  - New test `tests/test_logging_redaction.py` exercising `StringIO`-backed handler with synthetic exceptions.
- **Out:**
  - Log rotation, file ACL hardening, WER exclusion (separate idea docs).
  - Per-frame `traceback.FrameSummary` rewrite.
  - structlog migration.
  - Any change to `validate_audio_path` SECURITY warning logging.
  - Touching `RequestValidationError` handler.

### Step-by-step
1. Create `app/logging_utils.py` (~30 lines): `safe_error_message_str(msg: str) -> str` (string-input variant; imports `APP_DIR`/`HOME`/`APPDATA`/`EXPORT_DIR`/`MUSIC_DIR`/`TEMP_DIR` via `from .config import …` to avoid cycles — `app.config` does NOT import `app.main`) and `RedactingFormatter(logging.Formatter)` with the `format` override from Recommendation. Docstring carries the multi-handler-order invariant + capture_locals warning.
2. Refactor `safe_error_message` (`app/main.py:207-214`) body to `return safe_error_message_str(str(e))` — call signature unchanged for existing callers; widened path list lives in `app/logging_utils.py:safe_error_message_str`.
3. Rewrite `app/main.py:110-117` to the pre-set-formatter pattern (see Recommendation wiring block). Pre-built `_fh` + `_sh` carry the `RedactingFormatter` before `basicConfig`; basicConfig leaves them alone (verified: `Lib/logging/__init__.py` L110 `if h.formatter is None`).
4. Add `tests/test_logging_redaction.py` (~60 lines):
   - Fixture builds `StringIO`-backed `StreamHandler` + `RedactingFormatter`.
   - Case 1: `logger.error("ctx", exc_info=ValueError(APP_DIR))` → assert `"[...]"` present, `APP_DIR` absent.
   - Case 2: chained — `try: raise OSError(APP_DIR)` then `except: raise RuntimeError("wrap")` → assert "During handling of the above" present, neither frame leaks `APP_DIR`.
   - Case 3: `logger.error("path=%s", APP_DIR)` (args interpolation) → assert scrubbed in final string.
   - Case 4: `logger.info("hello")` → assert byte-identical to plain `Formatter('…').format(record)` (no regression for non-exception lines beyond redaction passes).
5. Run `pytest tests/test_logging_redaction.py -v` and `pytest tests/ -x` for regression.
6. Manual verify: `npm run dev:full`; in another shell `curl -X POST http://127.0.0.1:8000/<route-that-throws>` (use `/api/duplicates/scan` with malformed body or temp-add a `/api/__crash` route); tail `./logs/app.log`; confirm no `C:\Users\` / `APP_DIR` substrings, traceback structure intact (header + per-frame lines + final ExcType line + scrubbed paths).
7. `doc-syncer` subagent pass: update `docs/FILE_MAP.md` (new `app/logging_utils.py` row), `docs/MAP.md` + `docs/MAP_L2.md` via `python scripts/regen_maps.py`.

### Files touched
- `app/logging_utils.py` — new, ~30 lines (`safe_error_message_str` + `RedactingFormatter`).
- `app/main.py:110-117` — rewrite to pre-set-formatter pattern, ~+6 / -1 lines net.
- `app/main.py:207-214` — `safe_error_message` body delegates to helper, ~-7 / +2 lines net.
- `tests/test_logging_redaction.py` — new, ~60 lines (4 cases).
- `docs/FILE_MAP.md` — 1 new row.
- `docs/MAP.md` + `docs/MAP_L2.md` — auto-regen via `scripts/regen_maps.py`.

### Testing
- Unit: synthetic `ValueError(APP_DIR)` round-trip through `RedactingFormatter`; assert scrubbed substring + path absent.
- Unit: chained exception (`from`) preserves chain markers.
- Unit: `args`-style log (`logger.error("p=%s", APP_DIR)`) produces scrubbed final string.
- Unit: non-exception log (`logger.info("hello")`) unchanged byte-for-byte vs baseline.
- Regression: `pytest tests/` full pass.
- Manual: trigger global exception via `curl http://127.0.0.1:8000/api/__forced_crash` style probe (or via a temporarily added route), tail `./logs/app.log`, confirm no `C:\Users\` substrings.

### Risks & rollback
- Risk: future contributor attaches a second handler with a pre-set `Formatter()` → cache-leak invariant broken. Mitigation: docstring on `RedactingFormatter` documents the constraint; class-level `__init_subclass__` could `warnings.warn` if subclassed without override (low ROI — defer).
- Risk: `record.args` contains a non-string path object whose `repr()` contains the path. `safe_error_message_str` operates on the rendered final string, so this is covered automatically once `super().format(record)` runs `record.getMessage()`.
- Risk: a test elsewhere starts asserting log-line shape; currently zero matches in `tests/` (verified) but future drag. Mitigation: format string unchanged, so non-exception output is byte-identical.
- Rollback: single revert of the implementation commit restores prior `basicConfig` + un-widened `safe_error_message`; no schema migrations, no on-disk format change.

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
