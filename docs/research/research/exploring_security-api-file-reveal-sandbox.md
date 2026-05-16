---
slug: security-api-file-reveal-sandbox
title: /api/file/reveal accepts arbitrary path to subprocess.run(['explorer', '/select,', path])
owner: tb
created: 2026-05-15
last_updated: 2026-05-15
tags: [security, follow-up, auth-audit-adjacent]
related: [security-api-auth-hardening]
---

# /api/file/reveal accepts arbitrary path to subprocess.run(['explorer', '/select,', path])

> **Caveman style.** Fragments, bullets. Drop articles/filler/hedges. No prose paragraphs. Respect per-section caps below.
> State = folder + filename prefix (not frontmatter). Lifecycle = audit trail. See `../README.md`.

## Lifecycle

- 2026-05-15 — `research/idea_` — scaffolded from auth-audit adjacent findings
- 2026-05-15 — `research/idea_` — section fill from thin scaffold
- 2026-05-15 — research/idea_ — rework pass (quality-bar review pre-exploring_)
- 2026-05-15 — research/exploring_ — promoted; quality-bar met (Q1 caller-audit-resolved; Tauri-plugin reality checked → C demoted, A recommended)
- 2026-05-15 — research/exploring_ — perfect-quality rework loop (deep self-review pass)

---

## Problem

- Endpoint: `POST /api/file/reveal` (`app/main.py:565-584`, `file_reveal`).
- Body: `FileRevealReq{ path: str }` (`app/main.py:561-562`). User-controlled.
- Validation: `Path(r.path).exists()` only (line 570). No root sandbox. No ext check.
- Platform branch (`app/main.py:574-579`):
  - win32 (575): `subprocess.run(["explorer", "/select,", str(p)], check=False)`
  - darwin (577): `subprocess.run(["open", "-R", str(p)], check=False)`
  - linux (579): `subprocess.run(["xdg-open", str(p.parent)], check=False)` — reveals **parent dir**, not file.
- Positional argv (no `shell=True`) → injection hard. Threat = **policy**, not code-exec.
- Authenticated caller asks explorer to navigate anywhere on disk: `%APPDATA%\MusicLibraryManager\.session-token` (token-file location leak), `C:\Users\<u>\.ssh\id_ed25519`, user home, mapped network shares.
- Hotfix `e3a5ae8` skipped this endpoint (verified `git log --oneline -5 -- app/main.py`).
- Sole frontend caller: `frontend/src/components/TrackTable.jsx:460`, passes `trackPath = t.path || t.Path || t.Location` — always a file.
- Fix: route through `validate_audio_path` (`app/main.py:168-205`) before platform branch. Inherits `is_relative_to` hotfix + db-known-paths escape hatch.

## Goals / Non-goals

**Goals** (each = pytest case against `file_reveal` handler)
- Route reveal through `validate_audio_path` (`app/main.py:168-205`) before platform branch. **Test:** path outside `ALLOWED_AUDIO_ROOTS` → 403, `subprocess.run` mocked + asserted not called.
- File-only v1 (Q1 RESOLVED — `TrackTable.jsx:460` sole caller, passes file path). Directory path → 400 ("File type not allowed", inherited from `validate_audio_path` line 180). **Test:** dir path → 400, subprocess not called.
- WARN log on refuse, matching `validate_audio_path` line 202 format (`SECURITY: Blocked access to path outside allowed roots: <resolved>`). **Test:** `caplog` captures `WARNING` with resolved path string.
- Preserve 200 contract (`{"status": "success"}`) for valid in-root audio file. **Test:** valid in-root `.mp3` → 200 + subprocess called once with platform-correct argv (`["explorer","/select,",str(p)]` on win32; `["open","-R",str(p)]` on darwin; `["xdg-open",str(p.parent)]` else).
- 404 stays 404 (in-root path, file missing). **Test:** in-root path not on disk → 404 (inherited from `validate_audio_path` line 184).

**Non-goals**
- New "reveal-allowed-list". Reuse `ALLOWED_AUDIO_ROOTS` — single policy source.
- Generic "reveal arbitrary folder" feature. Out of scope.
- Endpoint-shape redesign (POST/JSON body/200 contract stay).
- Move off `subprocess.run` — positional argv already injection-safe.
- Auth gate (`X-Session-Token`). Owned by `security-api-auth-hardening` Phase 1, lands separately.

## Constraints

- Hotfix `e3a5ae8` rewrote `validate_audio_path` (`app/main.py:168-205`) from `str.startswith` to `Path.is_relative_to` (line 190-193). Building on top inherits the fix.
- `validate_audio_path` signature stable: `(path_str: str) -> Path`. Raises `HTTPException(400)` on invalid path, `(400)` on non-audio ext, `(404)` on missing file, `(403)` on outside-roots + WARN log (line 202). Returns resolved `Path` on success.
- Extension allowlist: `ALLOWED_AUDIO_EXTENSIONS = {.mp3,.wav,.aiff,.aif,.flac,.m4a,.ogg,.wma,.alac}` (line 166). Directories rejected (line 183 `is_file()` check). Reveal v1 file-only → reuse is exact-fit.
- Db-escape hatch (line 199-203): exact-match against `db.tracks[*]['path']`. Imported tracks outside roots still revealable — symmetric with playback.
- file/write hotfix (`app/main.py:587-636`) established the pattern: ext allowlist + `is_relative_to(ALLOWED_AUDIO_ROOTS)` + WARN + 403. Reveal should match shape so audits learn one pattern.
- `subprocess.run(positional, check=False)` — no shell, no injection. Threat = **policy**, not exec. Mitigation = path validation, not subprocess hardening.
- Endpoint `POST` + `FileRevealReq` body. No auth gate yet. `X-Session-Token` arrives via `security-api-auth-hardening` Phase 1 — orthogonal.
- Linux branch passes `str(p.parent)` to `xdg-open`. `p.is_relative_to(root)` implies `p.parent.is_relative_to(root)` for any root containing `p` — sandbox check on `p` covers Linux automatically. Check must sit **before** platform branch.

## Open Questions

1. ~~**Directory reveal**: dir-validator helper, or file-only v1?~~ **RESOLVED (2026-05-15):** `Grep /api/file/reveal frontend/src` → single hit `TrackTable.jsx:460`, file path only. v1 = file-only via `validate_audio_path`. Dir helper deferred until real consumer appears.
2. ~~**404 vs 403 on out-of-sandbox**~~: **RESOLVED (2026-05-15):** match `validate_audio_path` posture (403 + WARN log of resolved path). No special 404→403 conflation in reveal handler — let validator raise its own codes (400 invalid path / 400 non-audio ext / 404 missing file / 403 outside roots).
3. ~~**Db-known-paths escape hatch**~~: **RESOLVED (2026-05-15):** inherited from `validate_audio_path` line 199-203 automatically. Symmetric with playback (same validator). No separate decision needed.
4. **PARKED — `.upgrade-snapshots/` carve-out**: dir lives inside `ALLOWED_AUDIO_ROOTS` → reveal auto-permitted. Snapshot metadata may surface paths users don't expect to browse. Not blocking v1 — symmetric with current playback behavior. Revisit if snapshot tooling surfaces paths users react to.
5. **PARKED — cross-platform port**: macOS `open -R` + Linux `xdg-open <parent>` both gated by `p` sandbox check (Linux parent-fold proven safe in Constraints). Out-of-scope today (Windows-only build). Documented for future port.

## Findings / Investigation

Dated subsections, append-only. ≤80 words each. Never edit past entries — supersede.

### 2026-05-15 — initial scope
- Concrete attack pre-fix: authenticated `POST /api/file/reveal` with `path=%APPDATA%\MusicLibraryManager\.session-token` → reveals token-file location to any valid-token holder (= primary leak). Also: `path=C:\Users\<user>\.ssh\id_ed25519` (user-readable, exfil target) or any other user-readable file user did not intend to surface in app UI.
- Fix sketch: apply `validate_audio_path` to file targets before platform branch. WARN on refuse. Inherit 403/404/400 codes from validator.
- Endpoint platform-aware (`app/main.py:574-579`); every branch passes un-validated `str(p)`. Sandbox must sit **before** branch.

### 2026-05-15 — rework-pass verification
- **Reproducibility:** `app/main.py:565-584` re-read on `main` HEAD post-`e3a5ae8`. Handler still has only `p.exists()` (line 570). No `is_relative_to`, no ext check. Attack reproducible.
- **Hotfix scope:** `git log --oneline -5 -- app/main.py` confirms `e3a5ae8 fix(security): hotfixes from auth-hardening audit (5 findings)` skipped `/api/file/reveal`. Unfixed remnant.
- **Caller audit:** `Grep /api/file/reveal frontend/src` → single hit `frontend/src/components/TrackTable.jsx:460`, file path only. Resolves Q1: file-only v1.
- **Tauri capability re Option C:** `tauri-plugin-shell` v2.2 at `src-tauri/Cargo.toml:12`. `tauri-plugin-opener` not installed. Option C = new dep + capability JSON edit.

### 2026-05-15 — deep verification (perfect-quality pass)
- **Argv shapes re-verified at `app/main.py:574-579`:**
  - win32 (575): `subprocess.run(["explorer", "/select,", str(p)], check=False)` — `/select,` is one token (trailing comma = explorer CLI separator). `p` = file.
  - darwin (577): `subprocess.run(["open", "-R", str(p)], check=False)` — `-R` = reveal-in-Finder. `p` = file.
  - else (579): `subprocess.run(["xdg-open", str(p.parent)], check=False)` — `xdg-open` lacks select-file flag, passes parent dir. Sandbox check on `p` covers it (`p.is_relative_to(root)` ⇒ `p.parent.is_relative_to(root)`).
- **`validate_audio_path` signature unchanged** (`app/main.py:168-205`): `(path_str: str) -> Path`. Raises `400` (invalid/non-audio-ext), `404` (missing/not-file), `403` (outside roots + WARN line 202). Db-known-paths exact-match escape hatch at line 199-203. Drop-in usable as `p = validate_audio_path(r.path)`.
- **Tauri capability re Option C (full inventory):** `src-tauri/Cargo.toml:10-14` = `tauri 2.11`, `tauri-plugin-shell 2.2`, `tauri-plugin-dialog 2`, `tauri-plugin-fs 2`. `src-tauri/capabilities/main.json:8-27` permits `core:default`, `shell:allow-spawn` (sidecar-scoped), `shell:allow-execute`, `dialog:*`, `fs:*`. No opener plugin, no `opener:*` permission. Option C = +1 Cargo dep, +1 npm dep, +1 capability entry, +1 frontend rewrite, +Tauri smoke test.
- **Frontend caller error handling** (`TrackTable.jsx:458-463`): `handleReveal` wraps `api.post` in `try/catch`, all errors → toast `'Konnte Datei nicht im Explorer öffnen'`. No status-code-specific branches. Backend can tighten 400/403/404 without UI coordination.

## Options Considered

### Comparison table

| Option | LOC | Caller impact | New deps | New abstractions | Effort | Risk |
|---|---|---|---|---|---|---|
| **A — Reuse `validate_audio_path`** | ~3 changed in `main.py:569-571` + ~40 in `tests/` | None (single caller, file path) | None | None | S | Low |
| B — Split file/dir validators | ~30 changed in `main.py:168-205` + new helper + ~60 in tests | None | None | 1 helper (`_validate_path_in_roots`) + 1 public (`validate_directory_path`) | S-M | Low |
| C — Tauri opener-plugin | ~5 in `TrackTable.jsx` + delete ~22 in `main.py` + 1 line Cargo + 1 line npm + ~3 lines capability JSON | Refactor 1 call site + Tauri-context branch for browser-dev | `tauri-plugin-opener` (Rust) + `@tauri-apps/plugin-opener` (npm) | New permission scope to audit | M | Medium |

### Option A — Reuse `validate_audio_path` as-is (file-only) (RECOMMENDED)
- Sketch:
  - Replace `app/main.py:569-571` (`p = Path(r.path); if not p.exists(): raise 404`) with `p = validate_audio_path(r.path)` before line 574 platform branch.
  - Pass `str(p)` (already resolved by validator) to all three subprocess branches unchanged.
  - Dir-paths reject at 400 ("File type not allowed") via validator line 180. No current caller → no regression (Q1).
- Pros: zero new code, inherits `is_relative_to` hotfix + db-known-paths escape hatch, smallest audit surface.
- Cons: error message "File type not allowed" misleading if non-audio file requested; future dir-reveal / `.rbep`-reveal needs a second pass.
- Effort: S (~3 LOC + 5 pytest cases).
- Risk: Low. `TrackTable.jsx:460` already passes audio file path.

### Option B — Split into `validate_audio_path` + `validate_directory_path`
- Sketch:
  - Extract `is_relative_to(ALLOWED_AUDIO_ROOTS)` + db-known-paths block (`app/main.py:186-203`) into private `_validate_path_in_roots(p: Path)`.
  - New `validate_directory_path(path_str) -> Path` — resolve, `is_dir()` assert, call helper. No ext check.
  - Reveal handler branches on `Path(r.path).is_dir()` pre-platform-branch.
- Pros: handles both modes; shared root-check stays single-source; pattern reusable for future "open in OS" endpoints.
- Cons: 2 new public-ish symbols to test/document; db-known-paths escape hatch now in 2 callers; **no current dir-reveal caller** (premature generalization per Q1).
- Effort: S-M.
- Risk: Low.

### Option C — Drop endpoint, migrate frontend to Tauri opener-plugin
- Sketch:
  - Add `tauri-plugin-opener = "2"` to `src-tauri/Cargo.toml:14` + `npm i @tauri-apps/plugin-opener` for frontend bindings.
  - Add `"opener:allow-reveal-item-in-dir"` permission to `src-tauri/capabilities/main.json:27`. Optional `scope` block to constrain to `ALLOWED_AUDIO_ROOTS`-equivalent dirs.
  - Replace `TrackTable.jsx:460` `api.post('/api/file/reveal', { path })` with `await revealItemInDir(trackPath)` from `@tauri-apps/plugin-opener`.
  - Delete `POST /api/file/reveal` handler + `FileRevealReq` from `app/main.py:561-584` (~22 LOC).
  - Browser-dev mode: feature becomes Tauri-only — add `isTauri()` guard + "desktop-only" toast fallback.
- Pros: zero backend attack surface for this primitive; opener plugin has own scope config; aligns with "desktop wrapper handles OS calls".
- Cons: new Rust+npm dep (audit burden); breaks browser-dev parity; UI refactor; capability-scope tuning required.
- Effort: M (Cargo + capability JSON + npm + frontend + scope tuning + Tauri smoke test).
- Risk: Medium. Plugin scope may be too broad/narrow; user must rebuild desktop binary.

## Recommendation

**Option A.** Q1 resolved → file-only sufficient. Smallest patch (~3 LOC), zero new abstractions, inherits `is_relative_to` hotfix + db-escape-hatch + WARN log.

**Injection shape** (`app/main.py:565-584`, pseudocode-prose):

```
@app.post("/api/file/reveal")
def file_reveal(r: FileRevealReq):
    try:
        p = validate_audio_path(r.path)   # NEW — replaces lines 569-571.
                                          # Raises 400 (invalid/non-audio ext),
                                          # 404 (missing/not-file),
                                          # 403 (outside roots + WARN log).
        import subprocess                  # unchanged (line 572)
        import sys                         # unchanged (line 573)
        if sys.platform == "win32":
            subprocess.run(["explorer", "/select,", str(p)], check=False)
        elif sys.platform == "darwin":
            subprocess.run(["open", "-R", str(p)], check=False)
        else:
            subprocess.run(["xdg-open", str(p.parent)], check=False)
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, safe_error_message(e))
```

Net diff: −3 lines (`p = Path(r.path)` / `if not p.exists()` / `raise HTTPException(404, ...)`), +1 line (`p = validate_audio_path(r.path)`). Platform branch byte-identical. Sole caller `TrackTable.jsx:460` unaffected (errors toast-swallowed, no status-code branches per `TrackTable.jsx:458-463`).

**Option C** deferred. Revisit when browser-dev mode is dropped or when adding a 2nd reveal-style endpoint (then the dep cost amortises).

**Gates to `evaluated_`:** Implementation Plan below filled. All 5 Open Questions resolved or PARKED. Tests scoped. Ready for sign-off review.

---

## Implementation Plan

### Scope
- **In:**
  - Route `POST /api/file/reveal` through `validate_audio_path` (`app/main.py:168-205`) before platform branch.
  - 5 pytest cases in `tests/test_main_security.py` (new file if absent; else append): outside-roots → 403 + no subprocess; non-audio ext → 400 + no subprocess; missing file → 404 + no subprocess; dir path → 400 + no subprocess; valid in-root audio → 200 + subprocess called with platform-correct argv (`monkeypatch sys.platform`).
- **Out:**
  - Dir-reveal helper (Option B). No current caller (Q1).
  - Tauri opener-plugin migration (Option C). Deferred.
  - `X-Session-Token` gate. Owned by `security-api-auth-hardening` Phase 1.
  - `.upgrade-snapshots/` carve-out (Q4 PARKED).
  - Cross-platform port (Q5 PARKED — Windows-only build today).

### Step-by-step
1. Edit `app/main.py`: at line 569 delete the 3-line `p = Path(r.path)` / `if not p.exists(): raise HTTPException(404, ...)` block. Insert single line `p = validate_audio_path(r.path)` immediately after `try:` (line 568). Imports at 572-573 and platform branch at 574-579 stay byte-identical.
2. Run `ruff check app/main.py && ruff format app/main.py` (PostToolUse hook auto-runs).
3. Create/extend `tests/test_main_security.py` with the 5 cases. Pattern after existing `validate_audio_path` tests (`Grep "validate_audio_path" tests/` for closest fixture style). Use `monkeypatch.setattr("subprocess.run", mock_run)` to assert call/no-call + exact argv per platform (`monkeypatch.setattr(sys, "platform", "win32"/"darwin"/"linux")`).
4. `pytest tests/test_main_security.py -v` — all green.
5. Spawn `test-runner` subagent for broader sweep before commit.
6. Atomic commit: `fix(backend): sandbox /api/file/reveal via validate_audio_path`.
7. Doc-syncer subagent: update `docs/backend-index.md` reveal-endpoint row + this doc state transition.

### Files touched
- `app/main.py` (lines 565-584, ~3 LOC delta)
- `tests/test_main_security.py` (new or +5 cases)
- `docs/backend-index.md` (reveal-endpoint row)
- `docs/research/research/inprogress_security-api-file-reveal-sandbox.md` (rename + Implementation Log)

### Testing
- pytest: 5 new cases enumerated under Scope.
- Manual smoke: `/dev-full` → Track context menu → "Reveal" on a valid track → explorer opens. Repeat with hex-edited path pointing outside roots (e.g. via curl) → 403 + WARN in backend log.
- `caplog.records` check for the `SECURITY: Blocked access to path outside allowed roots: <path>` line.

### Risks & rollback
- **Risk:** Imported track outside `ALLOWED_AUDIO_ROOTS` but registered in `db.tracks` — reveal stays permitted via db-escape-hatch (line 199-203). Symmetric with playback. Documented behavior, not regression.
- **Risk:** Non-audio extension path passed by future caller → 400 with misleading "File type not allowed" message. Acceptable for v1; Option B graduation path if it bites.
- **Rollback:** `git revert <sha>` restores the un-sandboxed handler. Single-file change, no schema/migration. Trivial.

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
