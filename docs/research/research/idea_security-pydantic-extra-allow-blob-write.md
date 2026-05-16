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
- Persistence path: `SettingsManager.save` at `app/services.py:672-692` writes `Path("settings.json")` atomically (tmp + `os.replace`); `load` at `app/services.py:661-669` merges file over `DEFAULT` dict, no schema validation.
- Frontend writes unanticipated keys today: `shortcuts` (object — `SettingsView.jsx:119`, `SettingsShortcuts.jsx`), `waveform_color_{low,mid,high}` (`SettingsAppearance.jsx:31-34`), `locale` (`SettingsAppearance.jsx:65`), plus `sc_sync_folder_id` / `sc_download_format` / `legacy_pdb_stub` (in `services.py:DEFAULT` but absent from `SetReq` fields).
- `POST /api/settings` at `app/main.py:1874` is NOT yet gated by `require_session` — Phase-1 auth gate (see `docs/research/implement/draftplan_security-api-auth-hardening.md`) would close the unauth window but does not validate payload shape.
- Wholesale strict-allowlist would break the live frontend the moment it adds a new key before backend re-ship (e.g. `waveform_color_*` added without `SetReq` update would 422 today).
- `SettingsManager.load` swallows `OSError`/`JSONDecodeError` → falls back to `DEFAULT` silently; corrupted/oversized JSON = silent loss of user prefs.
- No rate limit on POST; FastAPI/Starlette default body limit is effectively unbounded for JSON in this app.

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
- **Frontend-only / extras (allowed by `extra: "allow"`):** `shortcuts: {action → combo}` (DAW key bindings, `SettingsShortcuts.jsx`), `waveform_color_low/mid/high` (hex strings, `SettingsAppearance.jsx:31-34`), `locale` (`SettingsAppearance.jsx:65`), `sc_sync_folder_id`, `sc_download_format`, `legacy_pdb_stub` (declared in `services.py:DEFAULT` but NOT in `SetReq`). Net: ~7 unanticipated keys actively in use, more likely.
- **Risk after Phase-1 auth lands:** unauth blob-write closed; remaining threat = authed-bug, LLM-injection, or compromised desktop process bloating `settings.json`. Severity ↓ from critical → moderate, urgency ↓ but not zero.
- **Pre-auth concrete blob attack today:** `curl -X POST http://127.0.0.1:8000/api/settings -d '{"x": "<100MB garbage>"}'` → `SettingsManager.save` writes 100 MB JSON → next startup `SettingsManager.load` blocks on parse + frontend `api.get('/api/settings')` hangs → soft DoS that survives restart.
- **Stored-XSS-on-read amplifier:** values are echoed back verbatim by GET `/api/settings`; any frontend that renders a setting without escaping (e.g. `waveform_visual_mode` injected into a `<style>` block) becomes an XSS sink.
- **Token leak amplifier:** `soundcloud_auth_token` is in plaintext; an attacker who can WRITE arbitrary keys can also OVERWRITE this one to swap the user's auth identity silently.

## Options Considered

Required by `evaluated_`. Per option: sketch ≤3 bullets, pros, cons, S/M/L/XL, risk.

### Option A — Strict whitelist
- Sketch: Flip `extra: "allow"` → `extra: "forbid"`. Declare every legitimate key in `SetReq` (known + currently-untyped: `shortcuts`, `waveform_color_*`, `locale`, `sc_*`, `legacy_pdb_stub`). Tight per-field types + bounded length/regex.
- Pros: smallest attack surface; schema is the contract; rejected unknowns are loud.
- Cons: every new frontend setting requires backend update + redeploy; high coupling; risk of accidentally breaking in-the-wild `settings.json` keys not anticipated here; load-path must also strip unknowns or 422 forever.
- Effort: M (audit every frontend POST site + nested validators for `shortcuts` dict).
- Risk: high regression surface — first frontend feature to add a new key without backend coordination breaks Save.

### Option B — Hybrid (typed-known + size-capped-unknown)
- Sketch: Keep `extra: "allow"` but add: per-value byte cap (e.g. 8 KB), per-key-count cap on dicts (e.g. 64), list-length cap (e.g. 256 for `scan_folders`), total serialized-payload cap (e.g. 256 KB). Strict types on known fields. Custom validator at top of `SetReq` enforces extras-budget pre-`SettingsManager.save`.
- Pros: keeps forward-compat the frontend already relies on; closes blob-write quantitatively; one place to enforce caps; backward-compatible with existing `settings.json` files.
- Cons: doesn't catch typo-keys / namespace pollution; bytes-cap requires re-serializing payload at validation time (small perf hit, negligible at typical sizes).
- Effort: S-M (single Pydantic validator + handful of constants).
- Risk: low — strict caps are pure additions; legitimate payloads are < 10 KB total.

### Option C — Schema-versioning + frontend-managed-extension
- Sketch: Add `schema_version` field; route unknown keys into a single `_extras: dict[str, Any]` blob with the same per-value + total caps as Option B. Frontend opts-in by writing through `_extras` for new prefs until promoted. Backend gains an explicit migration hook per version.
- Pros: clean separation known-vs-experimental; future-proof for real schema migrations; explicit audit trail of unknown keys.
- Cons: requires coordinated frontend refactor; more files touched; over-engineered for the immediate threat; doesn't ship faster than B.
- Effort: L (frontend + backend + migration tests + docs).
- Risk: scope creep — solves a problem we don't have yet at the cost of delaying the one we do.

## Recommendation

Required by `evaluated_`. ≤80 words. Which option + what blocks commit.

**Option B (Hybrid).** Keep `extra: "allow"` for forward-compat. Add Pydantic validator on `SetReq` enforcing: per-value ≤ 8 KB serialized, per-dict ≤ 64 keys, list ≤ 256 entries (path ≤ 1024 chars for `scan_folders`), total payload ≤ 256 KB. Tighten types on the 15 declared fields (regex on `theme`, `waveform_visual_mode`; non-negative on int thresholds). Independently gate POST with `require_session` once Phase-1 auth-hardening lands. Open Questions Q3+Q5 must be settled in `evaluated_` before `draftplan_`.

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
