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

---

## Problem

`app/main.py:558` accepts user-controlled `path` and runs `subprocess.run(["explorer", "/select,", path])`. Positional (not `shell=True`) → command injection hard. But: zero path validation. Authenticated caller can ask explorer to navigate anywhere on disk — including `%APPDATA%` with the new `.session-token` file, user home, network shares. UI-driven recon primitive. Need: `validate_audio_path`-equivalent sandbox for reveal, restrict target to `ALLOWED_AUDIO_ROOTS`, reject if file extension not in audio allowlist, log refused attempts at WARN.

## Goals / Non-goals

**Goals**
- Restrict reveal-target to `ALLOWED_AUDIO_ROOTS` via existing `validate_audio_path` (`app/main.py:168`)
- Optionally accept project-file extensions (`.rbep`, `.json`, `.txt`, `.cue`, `.m3u`, `.m3u8`) per the `_FILE_WRITE_EXTENSIONS` allowlist established by the file/write hotfix
- Log refused reveal attempts at WARN with the rejected path (same pattern as `validate_audio_path` line 202)
- Cover both file-reveal (most common) and directory-reveal (less common but legitimate)

**Non-goals**
- Don't introduce a separate "reveal-allowed-list" — reuse the existing `ALLOWED_AUDIO_ROOTS` sandbox so policy stays in one place
- Don't add a generic "reveal arbitrary folder" feature; if user needs that they navigate explorer manually
- Don't redesign the endpoint surface (POST / JSON body / 200-OK contract stays)
- Don't switch away from `subprocess.run` — positional args are already injection-safe

## Constraints

External facts bounding solution (rate limits, data shape, perf budget, legal, capacity). Cite source.

- Hotfix commit `e3a5ae8` already strengthened `validate_audio_path` to use `Path.is_relative_to` (proper path-segment match) instead of `str.startswith` — any reveal sandbox built on top inherits this fix automatically.
- file/write hotfix (`app/main.py:587` `_FILE_WRITE_EXTENSIONS`) established the pattern: **extension allowlist + `ALLOWED_AUDIO_ROOTS` membership check**. Reveal should follow the same shape so future audits only have to learn one pattern.
- Reveal target may be a **file** (most common — "show me this track in explorer") or a **directory** (less common but legitimate — "open the folder of this collection"). `validate_audio_path` only accepts files (`file_path.is_file()` check at line 183).
- `subprocess.run(["explorer", "/select,", str(p)])` is positional — no shell, no injection. The threat is **policy** (which paths may we reveal?), not **code injection**. Mitigation lives in path validation, not subprocess hardening.
- Endpoint is currently `POST` with `FileRevealReq` Pydantic body (`app/main.py:561`) — no auth gate yet. Will inherit `X-Session-Token` once `security-api-auth-hardening` lands.
- Cross-platform branches at `app/main.py:574-579`: Windows uses `explorer /select,`, macOS uses `open -R`, Linux uses `xdg-open` on the parent directory. Any sandboxing must apply uniformly before the platform branch.

## Open Questions

Numbered. Each resolvable (yes/no or X vs Y), not philosophy.

1. **Directory reveal**: validate dirs via a new `validate_directory_path` helper (same `Path.is_relative_to(ALLOWED_AUDIO_ROOTS)` check, no extension/`is_file` constraint), or **only allow file-reveal in v1** and reject dir paths with 400? Frontend usage audit needed.
2. **Cross-platform**: macOS (`open -R`) and Linux (`xdg-open <parent>`) need the same sandbox check. Linux branch reveals the **parent directory**, not the file itself — does that change the threat model? Out-of-scope today (Windows-only build), but document the expected behavior so a future port doesn't drop the check.
3. **`.upgrade-snapshots/` carve-out**: this directory lives **inside** `ALLOWED_AUDIO_ROOTS`, so reveal of files inside it is automatically permitted. Is that desired (debugging convenience) or should we explicitly exclude it (snapshot metadata may include paths users don't expect to be browsable)?
4. **Database-known paths**: `validate_audio_path` has an escape hatch for paths registered in `db.tracks` (line 200). Should reveal honor the same escape hatch? Probably yes — symmetric with playback — but worth confirming so a legitimately-imported track outside `ALLOWED_AUDIO_ROOTS` is still revealable.
5. **404 vs 403 leakage**: current handler returns `404 "Not found: <path>"` echoing the input. After sandboxing, should an out-of-sandbox path return 403 (truthful) or 404 (less info-leak)? `validate_audio_path` returns 403 with the path masked in logs only — reuse that posture.

## Findings / Investigation

Dated subsections, append-only. ≤80 words each. Never edit past entries — supersede.

### 2026-05-15 — initial scope
- Concrete attack today (pre-fix): authenticated `POST /api/file/reveal` with `path=C:\Windows\System32\config\SAM` → user's explorer opens at SAM file (info leak about Windows internals + UI confusion). Post-Phase-1-auth: `path=%APPDATA%\MusicLibraryManager\.session-token` → reveals token file location to anyone holding a valid token.
- Fix sketch (prose): apply `validate_audio_path` to file targets; for directory targets, write a small `validate_directory_path` helper that runs the same `is_relative_to(ALLOWED_AUDIO_ROOTS)` check without the `is_file` / extension constraints. Log refused attempts at WARN. Return 403 (not 404) on sandbox-escape, echoing `validate_audio_path` posture.
- Endpoint is already platform-aware (`app/main.py:574-579`) but every branch passes the un-validated `str(p)` — sandbox check must sit **before** the branch.

## Options Considered

Required by `evaluated_`. Per option: sketch ≤3 bullets, pros, cons, S/M/L/XL, risk.

### Option A — Reuse `validate_audio_path` as-is (file-only)
- Sketch:
  - One-line change: replace `Path(r.path)` / `p.exists()` block with `p = validate_audio_path(r.path)` before the platform branch.
  - Reveal of directories returns 400 ("File type not allowed") — frontend either tolerates or stops sending dir paths.
- Pros: zero new code, inherits the `is_relative_to` hotfix and the db-known-paths escape hatch for free, smallest audit surface.
- Cons: rejects legitimate dir-reveal use cases (e.g. "open the folder of this playlist"); error message is misleading for dir paths; couples reveal policy to the audio-extensions allowlist forever.
- Effort: S
- Risk: Low (regression: dir reveals break; need frontend audit).

### Option B — Split into `validate_audio_path` + `validate_directory_path` (RECOMMENDED)
- Sketch:
  - Extract the `is_relative_to(ALLOWED_AUDIO_ROOTS)` + db-known-paths block from `validate_audio_path` into a private `_validate_path_in_roots(p: Path)` helper.
  - New `validate_directory_path(path_str) -> Path` — resolve, assert `is_dir()`, call `_validate_path_in_roots`. No extension check.
  - Reveal handler: branch on `Path(r.path).is_dir()` to pick which validator to call before the platform branch.
- Pros: handles both reveal modes; shared root-check stays single-source-of-truth; pattern reusable for any future "open in OS" endpoints; minimal API surface change.
- Cons: introduces one new public-ish helper to test and document; one more place where the db-known-paths escape hatch must stay in sync.
- Effort: S-M
- Risk: Low (well-scoped refactor + new helper, both unit-testable).

### Option C — Drop the endpoint entirely
- Sketch:
  - Delete `POST /api/file/reveal` from `app/main.py`.
  - Frontend uses Tauri's native `shell.open` / `revealItemInDir` API (already available in Tauri 2) for reveals in production builds.
  - Browser-dev mode loses the reveal button (or shows "desktop-only").
- Pros: zero backend attack surface for this primitive; Tauri's API has its own permission scoping in `tauri.conf.json`; aligns with "let the desktop wrapper handle OS calls".
- Cons: breaks browser-dev workflow; requires frontend refactor + Tauri-allowlist tuning; loses parity between dev and prod environments; migration is non-trivial vs. a small sandboxing patch.
- Effort: M
- Risk: Medium (frontend changes, Tauri allowlist config, dev/prod divergence).

## Recommendation

Required by `evaluated_`. ≤80 words. Which option + what blocks commit.

**Option B** for the immediate fix: preserves browser-dev parity, handles both file and directory reveals, and keeps the policy check in one shared helper that already gets security review. Effort is S-M with low risk and inherits the `is_relative_to` hotfix.

**Option C** as a longer-term migration once the desktop-Tauri context is the only supported production path — at that point `/api/file/reveal` becomes pure attack surface with no consumer, and deletion is cleaner than maintenance.

Blocks before commit: answer Open Questions 1 (dir-reveal in scope?), 3 (`.upgrade-snapshots/` policy), 5 (403 vs 404 on escape).

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
