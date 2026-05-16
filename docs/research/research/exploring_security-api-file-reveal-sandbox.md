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

---

## Problem

`app/main.py:565-584` (`file_reveal`) accepts user-controlled `path` and runs `subprocess.run(["explorer", "/select,", str(p)])` (Windows) / `["open", "-R", ...]` (macOS) / `["xdg-open", str(p.parent)]` (Linux). Positional (not `shell=True`) → command injection hard. But: zero path validation — only an `exists()` check (line 570). Authenticated caller can ask explorer to navigate anywhere on disk — including `%APPDATA%` with the new `.session-token` file, user home, network shares. UI-driven recon primitive. **Hotfix commit `e3a5ae8` did NOT touch this endpoint** (verified via `git log -- app/main.py`); the only frontend caller is `frontend/src/components/TrackTable.jsx:460` and passes a track **file** path. Need: `validate_audio_path`-equivalent sandbox for reveal, restrict target to `ALLOWED_AUDIO_ROOTS`, log refused attempts at WARN.

## Goals / Non-goals

**Goals** (each testable with a pytest case against the handler)
- Restrict reveal-target to `ALLOWED_AUDIO_ROOTS` via existing `validate_audio_path` (`app/main.py:168-205`). **Test:** request with `path` outside roots → 403, no `subprocess.run` invocation (mock + assert not called).
- Cover both file-reveal (current sole use) **and** directory-reveal **only if Q1 confirms a caller** — otherwise reject dir paths with a clear 400. **Test:** request with directory path → expected status code per Q1 decision.
- Log refused reveal attempts at WARN with the rejected path (same pattern as `validate_audio_path` line 202). **Test:** `caplog` captures `WARNING ... SECURITY: Blocked /api/file/reveal ...`.
- Preserve current contract for valid inputs (200 + `{"status": "success"}`). **Test:** valid in-root audio path → 200 + subprocess invoked with expected argv per platform.

**Non-goals**
- Don't introduce a separate "reveal-allowed-list" — reuse the existing `ALLOWED_AUDIO_ROOTS` sandbox so policy stays in one place
- Don't add a generic "reveal arbitrary folder" feature; if user needs that they navigate explorer manually
- Don't redesign the endpoint surface (POST / JSON body / 200-OK contract stays)
- Don't switch away from `subprocess.run` — positional args are already injection-safe

## Constraints

External facts bounding solution (rate limits, data shape, perf budget, legal, capacity). Cite source.

- Hotfix commit `e3a5ae8` strengthened `validate_audio_path` (`app/main.py:168-205`) to use `Path.is_relative_to` (proper path-segment match) instead of `str.startswith` — any reveal sandbox built on top inherits this fix automatically.
- file/write hotfix (`app/main.py:587-636`, `_FILE_WRITE_EXTENSIONS` at line 587) established the pattern: **extension allowlist + `ALLOWED_AUDIO_ROOTS` membership via `is_relative_to` + WARN log on refuse + 403 on escape**. Reveal should follow the same shape so future audits only learn one pattern.
- Reveal target may be a **file** (current sole use case — `TrackTable.jsx:460` passes `t.path`) or a **directory** (no current caller). `validate_audio_path` only accepts files (`file_path.is_file()` check at line 183) and only audio extensions (line 179 — `ALLOWED_AUDIO_EXTENSIONS = {.mp3, .wav, .aiff, .aif, .flac, .m4a, .ogg, .wma, .alac}` at line 166).
- `subprocess.run(["explorer", "/select,", str(p)])` is positional — no shell, no injection. The threat is **policy** (which paths may we reveal?), not **code injection**. Mitigation lives in path validation, not subprocess hardening.
- Endpoint is `POST` with `FileRevealReq` Pydantic body (`app/main.py:561-562`) — no auth gate yet. Will inherit `X-Session-Token` once `security-api-auth-hardening` lands.
- Cross-platform branches at `app/main.py:574-579`: Windows uses `explorer /select,<file>`, macOS uses `open -R <file>`, **Linux uses `xdg-open <p.parent>` (opens the parent dir, not selecting the file)**. Asymmetry: on Linux a sandbox-validated file is acceptable, but the actual revealed surface is `p.parent` — confirm sandbox check applies to `p` (sufficient: `p.parent.is_relative_to(root)` follows from `p.is_relative_to(root)` for any root). Any sandboxing must apply uniformly before the platform branch.

## Open Questions

Numbered. Each resolvable (yes/no or X vs Y), not philosophy.

1. ~~**Directory reveal**: validate dirs via a new `validate_directory_path` helper, or only allow file-reveal in v1?~~ **RESOLVED (2026-05-15):** frontend grep (`/api/file/reveal`) shows exactly one caller — `frontend/src/components/TrackTable.jsx:460` — passing `t.path || t.Path || t.Location` (always a track file). No dir-reveal caller exists. **Decision:** v1 = file-only (Option A path). Dir-reveal can be added later when a real consumer appears.
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

### 2026-05-15 — rework-pass verification
- **Reproducibility confirmed:** read `app/main.py:565-584` (current `main` HEAD post-`e3a5ae8`) — handler still has only `p.exists()` check (line 570), no `is_relative_to` / extension validation. Attack from previous entry is reproducible against current code.
- **Hotfix scope confirmed:** `git log --oneline -5 -- app/main.py` shows `e3a5ae8 fix(security): hotfixes from auth-hardening audit (5 findings)` did **not** include `/api/file/reveal`. This endpoint is the unfixed remnant.
- **Caller audit:** `Grep /api/file/reveal frontend/src` → single hit `TrackTable.jsx:460`, passes `trackPath = t.path || t.Path || t.Location` (always a file). Resolves Q1: v1 is file-only.
- **Tauri capability re Option C:** repo uses `tauri-plugin-shell` v2.2 (`src-tauri/Cargo.toml:12`, `src-tauri/capabilities/main.json:11,19`). `tauri-plugin-opener` (the crate exposing `revealItemInDir` — Tauri 2's idiomatic reveal API) is **not installed**. Option C requires adding a new dep + capability entry — not a free swap.

## Options Considered

Required by `evaluated_`. Per option: sketch ≤3 bullets, pros, cons, S/M/L/XL, risk.

### Option A — Reuse `validate_audio_path` as-is (file-only) (RECOMMENDED)
- Sketch:
  - One-line change: replace `Path(r.path)` / `p.exists()` block (`app/main.py:569-571`) with `p = validate_audio_path(r.path)` before the platform branch at line 574.
  - Reveal of directories returns 400 ("File type not allowed") — but Q1 confirms no current caller passes a directory, so no regression.
- Pros: zero new code, inherits the `is_relative_to` hotfix and the db-known-paths escape hatch (line 200) for free, smallest audit surface, fastest to ship.
- Cons: couples reveal policy to the audio-extensions allowlist (mp3/wav/flac/etc) — future dir-reveal or `.rbep`-reveal feature would need a second pass; error message "File type not allowed" is misleading if a non-audio file is ever requested.
- Effort: S (≤10 LOC, 3-5 pytest cases)
- Risk: Low (single caller already passes audio file paths; verified `TrackTable.jsx:460`).

### Option B — Split into `validate_audio_path` + `validate_directory_path`
- Sketch:
  - Extract the `is_relative_to(ALLOWED_AUDIO_ROOTS)` + db-known-paths block from `validate_audio_path` (lines 186-203) into a private `_validate_path_in_roots(p: Path)` helper.
  - New `validate_directory_path(path_str) -> Path` — resolve, assert `is_dir()`, call `_validate_path_in_roots`. No extension check.
  - Reveal handler: branch on `Path(r.path).is_dir()` to pick which validator to call before the platform branch.
- Pros: handles both reveal modes; shared root-check stays single-source-of-truth; pattern reusable for any future "open in OS" endpoints.
- Cons: introduces one new public-ish helper to test and document; one more place where the db-known-paths escape hatch must stay in sync; **no current caller needs dir-reveal** (premature generalization per Q1).
- Effort: S-M
- Risk: Low (well-scoped refactor + new helper, both unit-testable).

### Option C — Drop the endpoint, migrate frontend to Tauri opener-plugin
- Sketch:
  - Add `tauri-plugin-opener` dep (`src-tauri/Cargo.toml` + `npm i @tauri-apps/plugin-opener` for frontend bindings).
  - Add `opener:allow-reveal-item-in-dir` permission to `src-tauri/capabilities/main.json` (current capabilities only list `shell:*`, `dialog:*`, `fs:*` — no `opener`).
  - Replace `api.post('/api/file/reveal', { path })` in `TrackTable.jsx:460` with `await revealItemInDir(path)` from `@tauri-apps/plugin-opener`.
  - Delete `POST /api/file/reveal` handler + `FileRevealReq` from `app/main.py`.
  - Browser-dev mode: feature becomes desktop-only (Tauri-context check) or show "desktop-only" toast.
- Pros: zero backend attack surface for this primitive; Tauri opener plugin has its own scope config in capabilities; aligns with "let the desktop wrapper handle OS calls".
- Cons: **adds new Rust dep + new capability** (non-trivial review burden, security audit needs to validate scope); breaks browser-dev workflow for reveal; requires frontend refactor; loses dev/prod parity for one minor feature; migration cost outweighs sandboxing a 4-line check in Option A.
- Effort: M (Cargo dep + capability JSON + frontend rewrite + plugin permission scope tuning + manual Tauri smoke test)
- Risk: Medium (new plugin permission may be too broad/narrow; capability schema changes; user must rebuild desktop binary).

## Recommendation

Required by `evaluated_`. ≤80 words. Which option + what blocks commit.

**Option A** for the immediate fix. Q1 confirmed file-only is sufficient (single caller, file paths). Smallest patch (≤10 LOC), zero new abstractions, inherits hotfix + db-escape-hatch.

**Concrete next step (Phase 1 of `exploring_`):** patch `app/main.py:565-584` — replace lines 569-571 with `p = validate_audio_path(r.path)` and pass `str(p)` to all three subprocess branches. Add 3 pytest cases in `tests/test_main_security.py` (or nearest existing): outside-roots → 403, non-audio extension → 400, valid in-root audio → 200 + mocked subprocess called with expected argv.

**Option C** deferred to a future cleanup once browser-dev mode is dropped; revisit when Tauri-only is the supported production path.

**Gates before promoting to `exploring_`:** answer Q3 (`.upgrade-snapshots/` carve-out — likely "leave permitted, document"), Q5 (403 vs 404 on escape — recommend 403 to match `validate_audio_path` posture). Q1 resolved. Q2 (Linux `xdg-open <parent>` asymmetry) and Q4 (db-known-paths escape hatch) are inherited from `validate_audio_path` and need no separate decision.

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
