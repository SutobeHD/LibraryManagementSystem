---
slug: security-mobile-paired-tokens-phase2
title: Phase-2 paired-device tokens + QR-pairing for mobile-companion LAN/remote access
owner: tb
created: 2026-05-19
last_updated: 2026-05-19
tags: [security, auth, mobile, phase2, qr-pairing, paired-tokens]
related: [security-api-auth-hardening, mobile-companion-ranking-app]
ai_tasks: false  # set true to opt-in AI routines — see ## AI Tasks below
---

# Phase-2 paired-device tokens + QR-pairing for mobile-companion LAN/remote access

> **Caveman style.** Fragments, bullets. Drop articles/filler/hedges. No prose paragraphs. Respect per-section caps below.
> State = folder + filename prefix (not frontmatter). Lifecycle = audit trail. See `../README.md`.

## Lifecycle

- 2026-05-19 — `research/idea_` — scaffolded as Phase-2 carve-out from security-api-auth-hardening

## AI Tasks

<!--
Opt-in queue for remote AI routines. Activate by setting `ai_tasks: true` in frontmatter.
Each item: 1 concrete sub-task. Routine processes 1/run, ticks done, commits via PR.
-->

- [ ] _(none yet — flag stays false until Phase-1 dust settles)_

---

## Problem

Phase-1 ships single boot-time `SESSION_TOKEN` (`app/auth.py:84`, rotates only on sidecar restart). One secret per process, no per-device scoping, no revoke surface, cannot hand to a phone. Mobile-companion (`exploring_mobile-companion-ranking-app.md`) needs per-device long-lived bearer + QR pairing UX + revoke. Hard blocker: 0 LoC today in `app/pairing.py` / `paired_devices` table. Without Phase-2, **no mobile feature ships**.

## Goals / Non-goals

**Goals**
- Per-device long-lived bearer tokens issued via QR-pairing flow.
- `paired_devices` SQLite table in **sidecar-local DB** (NOT `master.db` — see Phase-1 archive Option B + `docs/SECURITY.md:175`).
- `require_session` accepts either `SESSION_TOKEN` (Tauri main app) OR a paired-device token (mobile, second desktop).
- Revoke UI on desktop (Settings → Paired Devices) + `DELETE /api/pairing/{device_id}`.
- Token-rotation policy: per-device explicit revoke on phone-lost; no time-based expiry by default (see Findings #3 of sister doc, OQ5 resolved).
- Rate-limit on `POST /api/pairing/complete` to defend against pairing-token brute-force.

**Non-goals**
- mDNS auto-discovery (deferred to M2-Capacitor per sister doc OQ4).
- Cookie/session-cookie auth (Phase-1 archive Decisions: bearer-only).
- Row-level ACL per playlist/track (Phase-1 Non-goal carries forward).
- Tailscale/Funnel integration code (documented in sister-doc Findings; never embedded).
- Generalising `_format_tokens` helper (lives in Phase-2 implementation but not itself research-worthy).

## Constraints

External facts bounding solution (rate limits, data shape, perf budget, legal, capacity). Cite source.

- **Phase-1 integration point**: `app/auth.py:require_session` (lines 95-115) is the single dependency every mutating route uses (`Depends(require_session)` — 84/85 routes per Phase-1 archive). Extension must keep this signature.
- **Mobile route surface fixed**: 13 reads + 3 writes + 1 status = 17 routes mobile touches (sister doc Findings #1 line 153). Phase-2 adds **only** 3 new routes (`POST /api/pairing/start`, `POST /api/pairing/complete`, `DELETE /api/pairing/{device_id}`). No existing route signature changes.
- **Storage isolation**: `paired_devices` table MUST live in sidecar-local SQLite (e.g. new `app/auth_db.py` with `%APPDATA%/MusicLibraryManager/auth.db`), NOT `master.db`. Rekordbox holds DB-locks on `master.db`; mixing pairing-state there blocks while user has Rekordbox open. Trade-off documented in `docs/SECURITY.md:175` Schicht-B chapter + Phase-1 archive Option B.
- **CORS preflight**: env-driven `MOBILE_ALLOWED_ORIGINS` (sister doc OQ12, TRIGGER-PARKED) lands alongside Phase-2 wiring; ~5 LoC patch to `app/main.py:209-224`.
- **Token format**: re-use `secrets.token_urlsafe(32)` pattern from `app/auth.py:78`. 256-bit entropy. No JWT (no claims needed; revoke = DB delete).
- **No token logging**: same rule as Phase-1 (`app/auth.py:14-18` warning). Codify in `.claude/rules/coding-rules.md` once shipped.
- **Test coverage prior-art**: sister doc lines 425-441 already sketch `tests/test_pairing.py` with 12 expected cases (`TestPairingStart`, `TestPairingComplete`, `TestPairedDeviceRevoke`). Treat as design contract.
- **Bundle ceiling**: mobile QR-scan polyfill `qr-scanner` (~30 KB gz) dynamic-imported on pairing-screen only (sister doc Findings #2). Desktop QR-render side has no comparable budget.
- **Rate-limit module exists**: `app/rate_limit.py` (commit `830c056`) is decorator-ready but not applied anywhere today. Phase-2 is the first consumer.
- **Token-handoff pattern proven**: Phase-1 stdout-banner + Rust capture-and-scrub + `%APPDATA%/.session-token` file + `get_session_token` IPC (sister doc Findings #4 line 224). Phase-2's `device_token` follows the same shape but persists to `paired_devices` SQLite row, not in-process `Mutex<String>`.

## Open Questions

Numbered. Each resolvable (yes/no or X vs Y), not philosophy.

1. **QR payload shape** — URL-form (`lmsapp://pair?host=<lan-ip>&port=8000&token=<one-shot>`, sister doc line 92) vs JSON-encoded blob (`{host, port, token, ttl, fp}`) vs **structured short-text** (`HOST:PORT:TOKEN` for manual fallback). URL-form already sketched; settle on it OR justify upgrade. Affects QR density + scan reliability on dim phone cameras.
2. **Pairing-token TTL** — sister doc OQ14 still open, defaults to **60 s**. DJ-workflow argument: longer (5-10 min) tolerates "scan in booth, walk to laptop" delay. Security argument: 60 s tight. Pick one + write test in `tests/test_pairing.py:test_pairing_start_60s_ttl_enforced`.
3. **Pairing endpoint shape** — two-step (`POST /api/pairing/start` returns one-shot pairing-token + LAN IP/port, `POST /api/pairing/complete` swaps pairing-token for device-token) confirmed in sister doc lines 92, 153, 196 + tests 425-441. Open: does `start` require `Bearer SESSION_TOKEN` (only Tauri main app can initiate, prevents foreign-origin spam)? Sister test `test_pairing_start_without_bearer_is_401` says yes — confirm + document.
4. **`paired_devices` SQLite schema** — minimal columns: `device_id (uuid)`, `device_token (text, indexed, unique)`, `display_name (text, user-editable)`, `created_at (timestamp)`, `last_seen_at (timestamp)`, `user_agent (text, set on first auth call)`. Open: store `token_hash` + comparison-only (defense if DB leaks) OR plaintext + rely on file ACLs? Phase-1 stores plaintext in `.session-token` file → consistency argues plaintext. Hashing adds CPU per request.
5. **Revocation UI placement** — Settings page new section "Paired Devices" (table: name, last seen, revoke button) vs dedicated route `/settings/devices`. Affects `frontend/src/views/SettingsView.jsx` vs new component. Phase-1 has no Settings-page UI for tokens (none needed for single boot-token). First UI for auth surface.
6. **Token-rotation on phone-lost** — explicit user-driven revoke only (sister doc OQ5 resolution) OR add "panic button" rotating ALL paired devices at once? `POST /api/pairing/revoke-all`? UX: one click vs select-and-revoke. Affects whether `SESSION_TOKEN` itself rotates in same action.
7. **mDNS auto-discovery vs manual URL+QR-only** — sister doc OQ4 defers mDNS to M2-Capacitor (web sandbox blocks `_libmgr._tcp.local`). Confirm Phase-2 ships QR + manual URL only; mDNS = separate future doc.
8. **Rate-limit policy on pairing routes** — `app/rate_limit.py` provides `@rate_limit(steady=N/min, burst=M, key_mode=both)` (per Phase-1 archive). Pick steady/burst for `POST /api/pairing/complete`. Reference: Phase-1 used `steady=5/min, burst=10` on `/api/system/shutdown` (archive Decisions). Pairing-token has 256-bit entropy so brute-force impractical anyway; rate-limit = defense-in-depth + log-noise reduction. Apply to `start` too?
9. **`SESSION_TOKEN` removal trigger** — Phase-1 archive line 394 says `X-Session-Token` backwards-compat header "removed early in Phase 2 once paired devices land". Define exact trigger: Tauri main app must also pair itself (auto-pair-on-boot, persists device-token to same `.session-token` file path)? OR keep `SESSION_TOKEN` for Tauri main app + paired tokens only for other devices? Affects Rust supervisor logic + `require_session` accept-both contract.
10. **Single-paired-device-DB vs separate per-purpose DBs** — does `auth.db` later host other auth-adjacent state (rate-limit buckets, audit log)? If yes, name + scope now to avoid migrations. If no, keep tightly named `paired_devices.db`.

## Findings / Investigation

Dated subsections, append-only. ≤80 words each. Never edit past entries — supersede.

### 2026-05-19 — sister-doc cross-references

- `exploring_mobile-companion-ranking-app.md` Findings #2 (post auth-Phase-1, lines 162-228) holds desktop-side QR-render UX sketch + `PairFlow.jsx` pseudocode (lines 268-307) + expected test signatures (lines 425-454).
- Same doc Recommendation lines 559-583 lists Phase-2 as **Pre-M1 hard prereq**; mobile work cannot begin until paired-tokens merged + `MOBILE_ALLOWED_ORIGINS` env wired.
- OQs 1, 4, 6, 8 in this doc are upstream-version of mobile-doc OQs (4, 5, 12, 14). Resolve here, propagate down.

### 2026-05-19 — Phase-1 archive build-on

- `archived/implemented_security-api-auth-hardening_2026-05-17.md` Option E (line 307) defined hybrid model = Phase-1 (env-var bearer) + Phase-2 (paired-device tokens) + IP-allowlist as defense-in-depth.
- Decisions table (line 347-355) explicitly parks OQ1 (loopback vs `0.0.0.0`), OQ3 (mobile QR pairing UX), OQ5 (revocation model) to Phase 2.
- Future-WebSocket constraint (line 429): when first `@app.websocket` route lands, MUST call `await require_session_ws(websocket)` inside handler. Phase-2 `require_session` extension must add the matching WS variant if mobile ever opens a WebSocket (currently 0 hits).
- Risks line 478 calls out Tauri sidecar-respawn token drift — Phase-2 should re-evaluate: with paired tokens persisting across sidecar restarts (DB-backed), respawn no longer invalidates mobile clients. Only Tauri's `Mutex<String>` SESSION_TOKEN refreshes.

### 2026-05-19 — `app/auth.py` integration shape

- `require_session` (lines 95-115) is **synchronous + token-equality only**. Extension shape: load paired-device tokens once at module init (or lazy-load on first miss), accept either `SESSION_TOKEN` match OR `paired_devices.device_token` match. Use `safe_compare` (`app/security_compare.py`, Phase-1 commit `8498937`) for both branches.
- Module currently emits boot banner + writes `.session-token` file only for `MainProcess` (line 83). Paired-device init must follow same guard (no double-init from `SafeAnlzParser` child process).
- Phase-1 token-file rule (line 14-18): "MUST NOT log the token value at any level, ever." Carries forward to device-tokens. Codify in coding-rules.md once Phase-2 ships.

## Options Considered

Required by `evaluated_`. Per option: sketch ≤3 bullets, pros, cons, S/M/L/XL, risk.

### Option A — _(to fill at exploring_ stage)_
- Sketch:
- Pros:
- Cons:
- Effort:
- Risk:

### Option B — _(to fill at exploring_ stage)_
- Sketch:
- Pros:
- Cons:
- Effort:
- Risk:

## Recommendation

Required by `evaluated_`. ≤80 words. Which option + what blocks commit.

_(to fill at evaluated_ stage)_

---

## Implementation Plan

Required from `implement/draftplan_`. Concrete enough that someone else executes without re-deriving.

### Scope
- **In:** _(to fill at draftplan_ stage)_
- **Out:** _(to fill at draftplan_ stage)_

### Step-by-step
1. _(to fill at draftplan_ stage)_

### Files touched
- _(to fill at draftplan_ stage)_

### Testing
- _(to fill at draftplan_ stage)_

### Risks & rollback
- _(to fill at draftplan_ stage)_

## Review

Filled at `review_`. Unchecked box or rework reason → `rework_`.

- [ ] Plan addresses all goals
- [ ] Open questions answered or deferred
- [ ] Risk mitigations defined
- [ ] Rollback path clear
- [ ] Affected docs identified (`architecture.md`, `FILE_MAP.md`, indexes, `CHANGELOG.md`)

**Rework reasons:**
- _(to fill at review_ stage)_

## Implementation Log

Filled during `inprogress_`. Dated entries. What built / surprised / changed-from-plan.

### YYYY-MM-DD
- _(to fill at inprogress_ stage)_

---

## Decision / Outcome

Required by `archived/*`.

**Result**: _(implemented | superseded | abandoned)_
**Why**: _(to fill at archive)_
**Rejected alternatives:**
- _(to fill at archive)_

**Code references**: PR #…, commits …, files …

**Docs updated** (required for `implemented_`):
- [ ] `docs/architecture.md`
- [ ] `docs/FILE_MAP.md`
- [ ] `docs/backend-index.md` (if backend changed)
- [ ] `docs/frontend-index.md` (if frontend changed)
- [ ] `docs/rust-index.md` (if Rust/Tauri changed)
- [ ] `CHANGELOG.md` (if user-visible)

## Links

- Code: `app/auth.py:95-115` (require_session integration point), `app/rate_limit.py` (commit `830c056`, decorator-ready, no consumers yet)
- Related research: `archived/implemented_security-api-auth-hardening_2026-05-17.md`, `research/exploring_mobile-companion-ranking-app.md`
- Reference: `docs/SECURITY.md:110-175` (Schicht-B API Authentication chapter)
