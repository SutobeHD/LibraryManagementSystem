---
slug: security-pydantic-extra-allow-blob-write
title: Pydantic SetReq extra:allow as unauth blob-write primitive
owner: tb
created: 2026-05-15
last_updated: 2026-05-15
tags: [security, follow-up, auth-audit-adjacent]
related: [security-api-auth-hardening]
---

# Pydantic SetReq extra:allow as unauth blob-write primitive

> **Caveman style.** Fragments, bullets. Drop articles/filler/hedges. No prose paragraphs. Respect per-section caps below.
> State = folder + filename prefix (not frontmatter). Lifecycle = audit trail. See `../README.md`.

## Lifecycle

- 2026-05-15 — `research/idea_` — scaffolded from auth-audit adjacent findings
- 2026-05-15 — `research/idea_` — section fill from thin scaffold
- 2026-05-15 — `research/idea_` — rework pass (quality-bar review pre-`exploring_`)
- 2026-05-15 — research/exploring_ — promoted; quality-bar met (concrete caps 8KB/64/256/256KB; decoupled-from-Phase-1; agent caught + superseded own token-leak overclaim)

---

## Problem

`app/main.py` ~line 316: `class SetReq(BaseModel): model_config = {"extra": "allow"}` for settings POST. Currently pre-auth → arbitrary key dump into `settings.json` by anyone. After Phase-1 auth lands: caller authenticated, but schema still unconstrained — a buggy or compromised client can dump unbounded payloads. Stored-blob write primitive persists across restarts. Need schema-allowlist for accepted setting keys, per-value size cap, per-key type validation. Cost of inaction: settings.json grows unbounded, exfil channel via stored XSS-on-read, possible parser DoS on bloated keys.

## Goals / Non-goals

**Goals**
- Constrain `POST /api/settings` to known fields + safe value ranges (type + length caps).
- Cap total payload size + per-key value size so a single POST cannot bloat `settings.json` unbounded.
- Preserve forward-compat for legitimate future setting additions without backend redeploy.
- Surface schema violations clearly to frontend (`422` with field path + reason, not a 500).
- Keep load-path tolerant: an old `settings.json` with now-rejected keys must not brick startup.

**Non-goals**
- Redesign the entire settings system (no schema-versioning migration framework).
- Move shortcut-binding storage out of `settings.json` (separate concern).
- Centralise all frontend setting writes through a single facade (refactor scope creep).

## Constraints

External facts bounding solution (rate limits, data shape, perf budget, legal, capacity). Cite source.

- `SetReq` at `app/main.py:319` declares `model_config = {"extra": "allow"}` deliberately — comment lines 320-322 state frontend writes arbitrary preference keys (shortcuts, waveform colors, scan_folders, …).
- POST handler `save_s` at `app/main.py:1874-1892` merges `model_dump()` + `model_extra` then `SettingsManager.save(payload)` — no key filtering, no size cap.
- Persistence path: `SettingsManager.save` at `app/services.py:671-692` writes `Path("settings.json")` atomically (tmp + `os.replace`); `load` at `app/services.py:660-669` merges file over `DEFAULT` dict, no schema validation.
- Frontend writes unanticipated keys today: `shortcuts` (object — `SettingsView.jsx:119`, `frontend/src/components/settings/SettingsShortcuts.jsx:47`), `waveform_color_{low,mid,high}` (`frontend/src/components/settings/SettingsAppearance.jsx:31-33`), `locale` (`frontend/src/components/settings/SettingsAppearance.jsx:65`), plus `sc_sync_folder_id` / `sc_download_format` / `legacy_pdb_stub` (in `services.py:DEFAULT` 655-657 but absent from `SetReq` fields).
- `POST /api/settings` at `app/main.py:1874` has NO auth gate today — `require_session` does not yet exist in `app/main.py` (verified: zero matches). Phase-1 auth-hardening (`docs/research/implement/draftplan_security-api-auth-hardening.md`) introduces it; until that ships, the endpoint is fully pre-auth.
- Wholesale strict-allowlist would break the live frontend the moment it adds a new key before backend re-ship (e.g. `waveform_color_*` added without `SetReq` update would 422 today).
- `SettingsManager.load` (`app/services.py:660-669`) swallows `OSError`/`JSONDecodeError` → falls back to `DEFAULT` silently; corrupted/oversized JSON = silent loss of user prefs with only a `logger.warning`.
- No rate limit on POST; FastAPI/Starlette default body limit is effectively unbounded for JSON in this app (no `MAX_BODY_SIZE` middleware in `app/main.py`).
- `soundcloud_auth_token` is a vestigial `SetReq` field — the real token lives in OS keyring via `set_soundcloud_auth_token` (`app/main.py:3049-3084`, uses `keyring.set_password`). The `settings.json` value is only echoed back through `GET /api/settings` and read once by `SoundCloudView.jsx:23-24` for legacy UI display; overwriting it does NOT swap the user's auth identity (corrected from earlier finding).

## Open Questions

Numbered. Each resolvable (yes/no or X vs Y), not philosophy.

1. Strict whitelist of allowed keys vs extended deny-list (allow unknowns except a flagged blocklist)?
2. Hard per-value size cap — 1 KB, 8 KB, 64 KB? Different limit for string vs list/dict?
3. Hard total `settings.json` size cap on POST — 64 KB, 256 KB, 1 MB?
4. Should validation walk nested dicts recursively (e.g. `shortcuts.{action}` length cap, max keys per dict)?
5. Migration path for already-stored `settings.json` containing now-rejected keys — strip silently on load, warn-and-keep, or fail-loud requiring user intervention?
6. Should rejected POSTs return a structured 422 with per-field reasons, or a generic 400 (information disclosure tradeoff)?
7. Type-coerce vs strict-mode for known fields (Pydantic default coerces `"true"` → `True`; risk for boolean spoofing via stringly-typed clients)?
8. Cap on number of entries in list-valued keys (`scan_folders` length, plus path length per entry)?
9. Whether to also gate POST `/api/settings` with `require_session` independently of this work (assume yes — tracked under auth-hardening) or treat the two as one combined ship?
10. Audit-log retention for rejected payloads — log size + offending key only, never log full body (PII / token risk via `soundcloud_auth_token`)?

## Findings / Investigation

Dated subsections, append-only. ≤80 words each. Never edit past entries — supersede.

### 2026-05-15 — initial scope
- **Declared `SetReq` fields** (`app/main.py:325-339`): `default_export_format`, `default_export_dir`, `theme`, `auto_snap`, `db_path`, `artist_view_threshold`, `waveform_visual_mode`, `hide_streaming`, `remember_lib_mode`, `last_lib_mode`, `ranking_filter_mode`, `insights_playcount_threshold`, `insights_bitrate_threshold`, `soundcloud_auth_token`, `scan_folders` — 15 typed fields.
- **Frontend-only / extras (allowed by `extra: "allow"`):** `shortcuts: {action → combo}` (DAW key bindings, `SettingsShortcuts.jsx:47`), `waveform_color_low/mid/high` (hex strings, `SettingsAppearance.jsx:31-33`), `locale` (`SettingsAppearance.jsx:65`), `sc_sync_folder_id`, `sc_download_format`, `legacy_pdb_stub` (declared in `services.py:DEFAULT` 655-657 but NOT in `SetReq`). Net: 6 named unanticipated keys; an unauth client can add unlimited more.
- **Risk after Phase-1 auth lands:** unauth blob-write closed; remaining threat = authed-bug, LLM-injection, or compromised desktop process bloating `settings.json`. Severity ↓ from critical → moderate, urgency ↓ but not zero.
- **Pre-auth concrete blob attack today:** `curl -X POST http://127.0.0.1:8000/api/settings -d '{"x": "<100MB garbage>"}'` → `SettingsManager.save` writes 100 MB JSON → next startup `SettingsManager.load` returns `{**DEFAULT, **<huge>}` (no streaming) + `GET /api/settings` serializes it on every UI mount → 100 MB allocation + multi-second hang per request. Persists across restarts; recovery requires manual `settings.json` delete.
- **Stored-XSS-on-read amplifier:** values are echoed back verbatim by GET `/api/settings`; any frontend that renders a setting without escaping (e.g. `waveform_visual_mode` injected into a `<style>` block) becomes an XSS sink. React's JSX auto-escapes textContent, so the realistic sink is anything passed to `dangerouslySetInnerHTML`, inline `style={}` strings, or `<style>` blocks driven by setting values.

### 2026-05-15 — supersede: token-leak amplifier was wrong
- Earlier claim that overwriting `soundcloud_auth_token` via `SetReq` "swaps the user's auth identity silently" is INCORRECT. Verified: real token is stored in OS keyring via `set_soundcloud_auth_token` (`app/main.py:3049-3084`); every SC API call reads from `keyring.get_password(KEYRING_SERVICE, KEYRING_SC_TOKEN)` (verified at lines 2812, 2885, 3141, 3201, 3232, 3278, 3322, 3366). The `settings.json` field is vestigial; only consumer is `SoundCloudView.jsx:23-24` for legacy UI display. Overwriting it spoofs the displayed value but cannot redirect SC API calls. Removing the field from `SetReq` + `DEFAULT` is a separate cleanup, not a token-security gate.

## Options Considered

Required by `evaluated_`. Per option: sketch ≤3 bullets, pros, cons, S/M/L/XL, risk.

### Option A — Strict whitelist
- Sketch: Flip `extra: "allow"` → `extra: "forbid"`. Declare every legitimate key in `SetReq` (known + currently-untyped: `shortcuts`, `waveform_color_*`, `locale`, `sc_*`, `legacy_pdb_stub`). Tight per-field types + bounded length/regex.
- Pros: smallest attack surface; schema is the contract; rejected unknowns are loud.
- Cons: every new frontend setting requires backend update + redeploy; high coupling; risk of accidentally breaking in-the-wild `settings.json` keys not anticipated here; load-path must also strip unknowns or 422 forever.
- Effort: M (audit every frontend POST site + nested validators for `shortcuts` dict).
- Risk: high regression surface — first frontend feature to add a new key without backend coordination breaks Save.

### Option B — Hybrid (typed-known + size-capped-unknown)
- Sketch: Keep `extra: "allow"` but add: per-value byte cap (8 KB serialized), per-key-count cap on dicts (64), list-length cap (256 for `scan_folders`, path ≤ 1024 chars per entry), total serialized-payload cap (256 KB). Strict types on known fields. Custom Pydantic `model_validator(mode="after")` on `SetReq` enforces extras-budget pre-`SettingsManager.save`.
- Numbers grounded: a typical `settings.json` on a populated install is < 10 KB; the largest legitimate value is `shortcuts` (~30 actions × ~30-char combo strings ≈ 1 KB) — 8 KB/value leaves 8× headroom. 64 dict keys covers `shortcuts` (~30 today) with 2× headroom. 256 list entries covers a power-user `scan_folders` (typical 5-20 paths) with massive margin while still rejecting a runaway. 256 KB total = 25× current real-world size, low enough that the file cannot become a multi-MB DoS sink. Caps are starting points — Q2/Q3/Q8 may refine after measuring real installs.
- Pros: keeps forward-compat the frontend already relies on; closes blob-write quantitatively; one place to enforce caps; backward-compatible with existing `settings.json` files (load-path untouched).
- Cons: doesn't catch typo-keys / namespace pollution (a frontend bug writing `wavefrom_color_low` would silently persist); bytes-cap requires re-serializing payload at validation time (small perf hit, negligible at typical < 10 KB sizes).
- Effort: S-M (single Pydantic validator + handful of constants; nested-dict walker for Q4 if scoped in).
- Risk: low — strict caps are pure additions; legitimate payloads are < 10 KB total; one regression risk = a future legitimate setting (e.g. a 16 KB color-palette blob) hitting the per-value cap and forcing a constant bump.

### Option C — Schema-versioning + frontend-managed-extension
- Sketch: Add `schema_version` field; route unknown keys into a single `_extras: dict[str, Any]` blob with the same per-value + total caps as Option B. Frontend opts-in by writing through `_extras` for new prefs until promoted. Backend gains an explicit migration hook per version.
- Pros: clean separation known-vs-experimental; future-proof for real schema migrations; explicit audit trail of unknown keys.
- Cons: requires coordinated frontend refactor; more files touched; over-engineered for the immediate threat; doesn't ship faster than B.
- Effort: L (frontend + backend + migration tests + docs).
- Risk: scope creep — solves a problem we don't have yet at the cost of delaying the one we do.

## Recommendation

Required by `evaluated_`. ≤80 words. Which option + what blocks commit.

**Option B (Hybrid).** Keep `extra: "allow"` for forward-compat. Add Pydantic `model_validator(mode="after")` on `SetReq` enforcing: per-value ≤ 8 KB serialized, per-dict ≤ 64 keys, list ≤ 256 entries (path ≤ 1024 chars for `scan_folders`), total payload ≤ 256 KB. Tighten types on the 15 declared fields (regex on `theme` ∈ {dark,light}, `waveform_visual_mode` ∈ {blue,3band,custom}; non-negative on int thresholds; hex-color regex on `waveform_color_*`). Independently gate POST with `require_session` once Phase-1 auth-hardening lands — the two ships are decoupled (auth closes unauth window; this work closes payload-shape window).

**First step in `evaluated_`**: measure real `settings.json` size + key counts on a populated install to confirm cap defaults are not regressive. **Gates before `draftplan_`**: Q2 (per-value cap final number), Q3 (total cap final number), Q5 (load-path migration strategy for now-rejected stored keys), Q8 (list-entry caps). Q1/Q4/Q6/Q7/Q10 can defer to `draftplan_`. Q9 is resolved: combined ship rejected — auth-hardening already in flight, this work lands separately on top.

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
