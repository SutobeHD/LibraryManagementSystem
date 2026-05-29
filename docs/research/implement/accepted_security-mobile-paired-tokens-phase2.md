---
slug: security-mobile-paired-tokens-phase2
title: Phase-2 paired-device tokens + QR-pairing for mobile-companion LAN/remote access
owner: tb
created: 2026-05-19
last_updated: 2026-05-19  # 2026-05-19 deep-exploration pass
tags: [security, auth, mobile, phase2, qr-pairing, paired-tokens]
related: [security-api-auth-hardening, mobile-companion-ranking-app]
ai_tasks: false  # set true to opt-in AI routines — see ## AI Tasks below
---

# Phase-2 paired-device tokens + QR-pairing for mobile-companion LAN/remote access

> **Caveman style.** Fragments, bullets. Drop articles/filler/hedges. No prose paragraphs. Respect per-section caps below.
> State = folder + filename prefix (not frontmatter). Lifecycle = audit trail. See `../README.md`.

## Lifecycle

- 2026-05-19 — `research/idea_` — scaffolded as Phase-2 carve-out from security-api-auth-hardening
- 2026-05-19 — research/idea_ — deep exploration toward exploring_-ready
- 2026-05-28 — `research/drafting_` — Stage 1 worker formally complete (content already at exploring_ depth — Findings + Options + Recommendation populated 2026-05-19)
- 2026-05-28 — `research/ideagate_` — Stage 1 verifier PASS, awaiting GATE A
- 2026-05-29 — `research/exploring_` — GATE A PASSED by user; entblockt `exploring_mobile-companion-ranking-app` hard-prereq; advanced for Stage 2 wave-2 verifier
- 2026-05-29 — `research/evaluated_` — Stage 2 wave-2 verifier PASS (Citation Quality 8/8, Adversarial validates Option A). 1 material draftplan carry-forward: `last_seen_at` write-per-request contention (throttle+WAL+per-thread conn). Recommendation Option A stands.
- 2026-05-29 — `implement/draftplan_` — planning started (Implementation Plan + 7-task queue; last_seen_at contention resolved in plan)
- 2026-05-29 — `implement/review_` — Plan-Reviewer pass: 5/5 boxes ticked, PASS (adversarial carry-forward addressed)
- 2026-05-29 — `implement/plangate_` — plan reviewed (Planner + Reviewer PASS), awaiting GATE C. Hard runtime prereq for mobile-companion shipping.
- 2026-05-29 — `implement/accepted_` — GATE C PASSED (user delegated gate authority to the agent for PASS-verified plans). Ready for `inprogress_`; implement-tier needs branch-model direction.

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

Each goal carries a concrete success metric (testable at `review_` / post-ship).

- **G1 — Per-device long-lived bearer via QR-pairing.** Phone scans desktop QR → holds a 256-bit device-token usable as `Authorization: Bearer`. **Metric:** `tests/test_pairing.py::test_pairing_complete_device_token_authorises_subsequent_mutation` green — paired token returns 2xx on `POST /api/track/{tid}`.
- **G2 — Sidecar-local auth DB, zero `master.db` contact.** `paired_devices` table lives in a new SQLite file under `%APPDATA%/MusicLibraryManager/`. **Metric:** `grep -n "paired_devices\|pairing" app/database.py` → 0 hits; `auth.db` path-asserted distinct from `master.db` in `tests/test_pairing.py::test_pairing_complete_persists_paired_device_row`.
- **G3 — Dual-token acceptance, single dependency.** `require_session` accepts `SESSION_TOKEN` (Tauri main) OR any non-revoked paired-device token; signature unchanged so all 84 route-decorations stay byte-identical. **Metric:** existing `tests/test_auth.py` 100% green (SESSION_TOKEN path) + new `test_revoked_device_token_returns_401_on_next_mutation` green.
- **G4 — Desktop revoke surface.** Settings → "Paired Devices" lists name/last-seen + per-row revoke + global "revoke all". **Metric:** `DELETE /api/pairing/{device_id}` returns 204 and the revoked token 401s within one request (`test_delete_device_revokes_token_returns_204`).
- **G5 — No time-based expiry; revoke is the only kill switch.** Device-token has no TTL column; lost-phone mitigation = explicit revoke (sister doc OQ5 RESOLVED). **Metric:** a paired token still authorises a mutation 24 h after issue in an integration test with a clock-advanced fixture.
- **G6 — Brute-force-guarded pairing routes.** `@rate_limit` from `app/rate_limit.py` gates `POST /api/pairing/complete` (and `start`). **Metric:** `test_pairing_complete_rate_limited_after_burst` — 11th rapid call returns 429 + `Retry-After`.
- **G7 — Token never logged.** No device-token value reaches `logging` at any level (carries Phase-1 `app/auth.py:14-18` rule). **Metric:** `grep -rn "device_token" app/pairing.py app/auth_db.py` shows every reference is hash/DB/return-value, never a `logger.*` argument; reviewer checklist item.

**Non-goals**
- mDNS auto-discovery (deferred to M2-Capacitor per sister doc OQ4).
- Cookie/session-cookie auth (Phase-1 archive Decisions: bearer-only).
- Row-level ACL per playlist/track (Phase-1 Non-goal carries forward).
- Tailscale/Funnel integration code (documented in sister-doc Findings; never embedded).
- Generalising `_format_tokens` helper (lives in Phase-2 implementation but not itself research-worthy).

## Constraints

External facts bounding solution (rate limits, data shape, perf budget, legal, capacity). Cite source. Line numbers re-verified 2026-05-19.

- **Phase-1 integration point — re-verified**: `app/auth.py:require_session` lives at lines **95-115**, **synchronous**, single param `authorization: Annotated[str | None, Header()]`, body = scheme-split → `safe_compare(candidate, SESSION_TOKEN)`. Every mutating route uses `Depends(require_session)` (84/85 per Phase-1 archive line 506). Extension MUST keep this exact signature so no route decoration changes.
- **`SESSION_TOKEN` generation — re-verified**: `app/auth.py:78` `secrets.token_urlsafe(32)`; module-level init guarded `if _mp.current_process().name == "MainProcess"` (line 83) — child `ProcessPoolExecutor` workers get `SESSION_TOKEN = ""`. Phase-2 `paired_devices` table-open must follow the same MainProcess guard to avoid double-init from the `SafeAnlzParser` pool.
- **`safe_compare` available — re-verified**: `app/security_compare.py` exports `safe_compare(presented, expected) -> bool` — constant-time, returns `False` (never raises) on non-ASCII / length-mismatch / wrong-type. Trust direction: `presented` = untrusted request side. Device-token comparison reuses it directly.
- **`@rate_limit` decorator-ready — re-verified**: `app/rate_limit.py` exports `rate_limit(steady, burst, key_mode)` + `_store` singleton. Signature `rate_limit(steady: float, burst: int, key_mode: Literal["ip","bearer","both"] = "both")`. Async-only wrapper; extracts `Request` from kwargs/args, fail-open if absent. 429 body `{"error":"rate_limited","retry_after_s":int}` + `Retry-After` header. **0 consumers today** — Phase-1 wired it onto shutdown/restart/sc-auth-token (`steady=5/min, burst=10`); Phase-2 pairing routes are the next consumer. `make_key` loopback-whitelists `127.0.0.1`/`::1` to sentinel `__whitelist__` → Tauri-main pairing calls are never throttled; mobile (LAN IP) gets a real bucket.
- **Mobile route surface fixed**: 13 reads + 3 writes + 1 status = 17 routes mobile touches (sister doc Findings #1 line 153). Phase-2 adds **only** 3 new routes (`POST /api/pairing/start`, `POST /api/pairing/complete`, `DELETE /api/pairing/{device_id}`). No existing route signature changes.
- **Storage isolation**: `paired_devices` table MUST live in sidecar-local SQLite (new `app/auth_db.py`, file `%APPDATA%/MusicLibraryManager/auth.db` via `platformdirs.user_data_dir` — same dir as `app/auth.py:_token_file_path`). NOT `master.db`: Rekordbox holds write-locks on `master.db` while open, and `app/database.py:_db_write_lock` serialises only that file. Phase-1 archive Option B (line 289) explicitly flags "auth state in `master.db` conflicts with no-shared-schema rule; use sidecar-local SQLite".
- **CORS preflight — re-verified**: CORS block is `app/main.py:218-229` (NOT 209-224 — doc drift corrected). `allow_credentials=False` already shipped (CORS Phase-B, commit `e579459`). env-driven `MOBILE_ALLOWED_ORIGINS` (sister doc OQ12, TRIGGER-PARKED, comma-split) lands alongside Phase-2 wiring; ~5 LoC patch appending to the `allow_origins=[...]` list at `:219`.
- **Bind point — re-verified**: `app/main.py:4167` `uvicorn.run(app, host="127.0.0.1", port=8000)`. LAN-exposure (`0.0.0.0` or reverse proxy) is a separate trigger — see OQ7. Phase-2 pairing flow works on either; the QR carries whatever host the user reaches the desktop on.
- **Token format**: re-use `secrets.token_urlsafe(32)` for both the one-shot pairing-code and the long-lived device-token. 256-bit entropy. No JWT (no claims needed; revoke = DB row flag, not key-rotation).
- **No token logging**: same rule as Phase-1 (`app/auth.py:14-18` warning). Codify in `.claude/rules/coding-rules.md` once shipped.
- **Test coverage prior-art**: sister doc lines 430-446 already sketch `tests/test_pairing.py` with 12 expected cases (`TestPairingStart` 4, `TestPairingComplete` 5, `TestPairedDeviceRevoke` 3). Treat as design contract; Phase-2 adds 2 rate-limit cases on top.
- **`auth_token` fixture auto-applies**: `tests/conftest.py` autouse `auth_token` fixture means new `test_pairing.py` cases get Bearer headers free (sister doc line 225). No per-test boilerplate.
- **Bundle ceiling**: mobile QR-scan handled by `jsQR` (~12 KB gz, sister doc Findings 2026-05-17 picked it over `qr-scanner`) dynamic-imported on pairing-screen only. Desktop QR-render side: a render-only lib (e.g. `qrcode` npm, ~5 KB gz) — far under any budget.
- **Token-handoff pattern proven**: Phase-1 stdout-banner + Rust capture-and-scrub + `%APPDATA%/.session-token` file + `get_session_token` IPC (sister doc Findings #4 line 224). Phase-2's `device_token` follows the same persistence idea but the row lives in `auth.db`, not an in-process `Mutex<String>` — so it survives sidecar respawn (Phase-1 archive Risks line 478: respawn no longer invalidates mobile clients).

## Open Questions

Numbered. Each resolvable (yes/no or X vs Y), not philosophy. RESOLVED = answered this pass. PARKED = deferred to named trigger.

1. **RESOLVED — QR payload = URL-form `lmsapp://pair?host=<host>&port=8000&code=<one-shot>`.** Sister doc OQ4 already froze this (line 92). Keep it; `?token=` renamed `?code=` to disambiguate one-shot pairing-code from long-lived device-token. JSON blob rejected: heavier QR (more modules → worse scan on dim cameras), no claim needs structured fields. `?ttl=` omitted — TTL is server-enforced, client doesn't need it. `host` = whatever the user reaches the desktop on (LAN IP or tunnel hostname), filled by `POST /api/pairing/start` response, not hard-coded. Manual fallback: same `host:port:code` shown as plain text under the QR.
2. **RESOLVED — pairing-code TTL = 60 s.** Sister doc OQ14 default confirmed. DJ "scan in booth" concern is a non-issue: pairing is a one-time setup done once per phone at the desk, not a per-session ritual. 60 s is generous for "look at screen, raise phone, scan". Longer TTL widens the brute-force window for marginal convenience. Test: `test_pairing_start_60s_ttl_enforced` + `test_pairing_complete_with_expired_token_is_410`.
3. **RESOLVED — two-step endpoint; `start` requires `Bearer SESSION_TOKEN`.** `POST /api/pairing/start` (Tauri-main only, returns one-shot code + host/port) → `POST /api/pairing/complete` (mobile, swaps code → device-token). `start` is `Depends(require_session)`-gated so only the already-trusted desktop can mint pairing-codes — a foreign LAN origin cannot spam codes into existence. `complete` is **unauthenticated** by Bearer (the phone has no token yet) — its sole guard is a valid unexpired code + rate-limit. Sister test `test_pairing_start_without_bearer_is_401` confirms.
4. **RESOLVED — store `token_hash`, not plaintext.** Schema column = `token_hash TEXT` (SHA-256 hex of the device-token). Diverges from Phase-1's plaintext `.session-token` file deliberately: that file is one secret under user-ACL; `auth.db` is a *multi-row* credential store that grows over the product's life — a leaked `.db` (backup, support-dump, cloud-sync mishap) must not hand an attacker every paired phone. Hashing cost is negligible: one SHA-256 over 43 bytes per request, dwarfed by the SQLite SELECT. `require_session` hashes the presented token then `safe_compare`s against indexed `token_hash`. See Findings 2026-05-19 schema sketch.
5. **RESOLVED — Settings-page section, no dedicated route.** New "Paired Devices" block inside existing `frontend/src/views/SettingsView.jsx` — table (name, last-seen, revoke button) + a "Revoke all" button. No `/settings/devices` route: one new component (`PairedDevicesPanel.jsx`) imported into SettingsView keeps router surface flat and matches how other Settings sub-panels are composed.
6. **RESOLVED — both per-device revoke AND global "revoke all".** `DELETE /api/pairing/{device_id}` for the targeted case (revoke one lost phone). `POST /api/pairing/revoke-all` panic-button for "I don't know which device is compromised" — flags every `paired_devices` row revoked in one transaction. `revoke-all` does NOT rotate `SESSION_TOKEN` (that would 401 the Tauri main app mid-session for no benefit — Tauri-main is the trusted local process, not a paired device). User-driven only; no automatic time-based rotation (G5).
7. **PARKED — LAN-bind / `0.0.0.0` decision. TRIGGER: mobile-companion draftplan kickoff.** Phase-2 ships QR + manual-URL pairing only; mDNS stays deferred to M2-Capacitor (web sandbox blocks `_libmgr._tcp.local` — sister doc OQ4). Whether the sidecar binds `0.0.0.0` vs stays `127.0.0.1`+reverse-proxy is the mobile-companion doc's call (its OQ on bind), not this doc's — paired-token issuance works identically on either. Not blocking: pairing logic is bind-agnostic.
8. **RESOLVED — `@rate_limit(steady=5, burst=10, key_mode="both")` on `complete`; same on `start`.** Reuses Phase-1's HIGH tier (archive Decisions: shutdown/restart used `5/min, burst=10`). 256-bit pairing-code is already brute-force-proof by entropy; rate-limit = defense-in-depth + log-noise cap + cheap insurance against a future shorter-code variant. Apply to `start` too — caps code-minting spam from a compromised desktop-origin script. `key_mode="both"` (IP|Bearer): `complete` has no Bearer so it keys on IP; loopback (Tauri-main calling `start`) hits the `__whitelist__` sentinel and is never throttled.
9. **RESOLVED — keep `SESSION_TOKEN` for Tauri-main; paired tokens for everything else. No auto-pair-on-boot.** `require_session` accepts EITHER (dual-acceptance, see Findings 2026-05-19). Tauri-main keeps the stdout-banner `SESSION_TOKEN` it already has — making it "pair itself" adds a bootstrap dependency (sidecar must serve `/api/pairing/*` before the main window can authenticate) for zero gain. The `X-Session-Token` legacy header is already gone (Phase-1 archive line 515 — dropped day 1, never shipped), so there is no compat header left to remove. `SESSION_TOKEN` removal is therefore a non-event: it simply coexists as the Tauri-main credential.
10. **RESOLVED — name the file `auth.db`, scope it as the sidecar auth store.** Not `paired_devices.db`. `auth.db` is deliberately broad so future auth-adjacent state (audit log of pairing events, possibly persisted rate-limit buckets if the in-memory `_store` ever needs durability) lands in the same file without a rename migration. Phase-2 ships exactly one table (`paired_devices`); the filename leaves headroom. Rate-limit buckets stay in-memory for now (rate-limit archive OQ8 RESOLVED: in-memory only) — `auth.db` is a *possible* future home, not a commitment.

## Idea Verification

Stage 1 Verifier. Dated entries, append-only.

### 2026-05-28 — PASS
- **Intent**: scope ("per-device long-lived bearer + QR pairing + revoke for mobile-companion") + carve-out from `security-api-auth-hardening` is consistent; G1-G7 each carry a concrete test as success metric. PARKED items (LAN-bind / mDNS / row-ACL) keep scope tight without losing the trail.
- **Prior-art**: 2 explicit cross-refs (`security-api-auth-hardening` parent, `mobile-companion-ranking-app` sibling). Sister-doc OQs (4, 12, 14) reused verbatim where they already froze decisions — no re-litigation.
- **Plan**: 10 OQs all RESOLVED or PARKED (with named trigger). Findings + Options + Recommendation already drafted. Bind decision deferred to mobile-companion doc — correct ownership. User GATE A is the next blocker; expected exploring_ wave 2 verifier PASS on first cycle.

---

> ⛔ GATE A — user `/gate-pass` (→ `exploring_`) or `/gate-reject` (→ `drafting_`).
> Note: hard prereq for any mobile-companion shipping. Without GATE A pass, the mobile-companion doc stays blocked.

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

- `require_session` (lines 95-115) is **synchronous + token-equality only**. Extension shape: accept either `SESSION_TOKEN` match OR `paired_devices.token_hash` match. Use `safe_compare` (`app/security_compare.py`) for both branches.
- Module currently emits boot banner + writes `.session-token` file only for `MainProcess` (line 83). Paired-device init must follow same guard (no double-init from `SafeAnlzParser` child process).
- Phase-1 token-file rule (line 14-18): "MUST NOT log the token value at any level, ever." Carries forward to device-tokens. Codify in coding-rules.md once Phase-2 ships.

### 2026-05-19 — `paired_devices` SQLite schema sketch

New file `app/auth_db.py`; DB at `%APPDATA%/MusicLibraryManager/auth.db` (`platformdirs.user_data_dir`, same dir as `.session-token`). Single table:

```sql
CREATE TABLE IF NOT EXISTS paired_devices (
    device_id    TEXT PRIMARY KEY,           -- uuid4 hex, surfaced in DELETE route
    token_hash   TEXT NOT NULL UNIQUE,       -- sha256 hex of device-token (OQ4)
    display_name TEXT NOT NULL,              -- user-editable, default = User-Agent product
    created_at   TEXT NOT NULL,              -- ISO-8601 UTC
    last_seen_at TEXT,                       -- updated on each authed request (best-effort)
    revoked      INTEGER NOT NULL DEFAULT 0  -- 0/1; revoke = UPDATE, not DELETE (audit trail)
);
CREATE INDEX IF NOT EXISTS idx_paired_token_hash ON paired_devices(token_hash);
```

- `revoked` is a flag, not a row-delete — keeps an audit trail of retired devices; `require_session` filters `WHERE token_hash=? AND revoked=0`.
- `last_seen_at` write is best-effort (wrap in `except sqlite3.Error`) — a stale timestamp must never 500 an otherwise-valid request.
- No `_db_write_lock` needed: `auth.db` is a separate file from `master.db`. A small dedicated `threading.Lock` in `app/auth_db.py` serialises its own writers (low traffic — pairing + last-seen).

### 2026-05-19 — QR payload format decision (OQ1 resolved)

- Final: `lmsapp://pair?host=<host>&port=8000&code=<one-shot-code>`.
- `host` filled at runtime from `POST /api/pairing/start` response (`request.url.hostname` / detected LAN IP), never compile-time.
- `code` = `secrets.token_urlsafe(32)` one-shot; `?token=` from the sister-doc sketch renamed `?code=` to keep "pairing-code" (ephemeral) and "device-token" (long-lived) lexically distinct everywhere.
- Custom scheme `lmsapp://` lets a future Capacitor build deep-link straight into `PairFlow`; the PWA path just string-matches `code.data.startsWith('lmsapp://pair?')` (sister doc `PairFlow.jsx:297`) and parses the query.
- Manual fallback for camera-less devices: the same code shown as plain `host:port:code` text under the QR; mobile has a paste field.

### 2026-05-19 — pairing handshake sequence

```
Desktop (Tauri-main)                Sidecar (FastAPI :8000)         Phone (mobile PWA)
        |                                   |                              |
        | 1. POST /api/pairing/start        |                              |
        |    Bearer SESSION_TOKEN           |                              |
        |---------------------------------->|                              |
        |                                   | mint code=token_urlsafe(32)  |
        |                                   | store {code, expires_at}     |
        |                                   |   in-memory dict, 60 s TTL   |
        | 2. {code, host, port}             |                              |
        |<----------------------------------|                              |
        | render QR lmsapp://pair?...       |                              |
        |                                   |        3. scan QR            |
        |                                   |     4. POST /api/pairing/complete
        |                                   |        body {code, device_name?}
        |                                   |<-----------------------------|
        |                                   | validate code:               |
        |                                   |   unknown/expired -> 410      |
        |                                   |   already-consumed -> 409     |
        |                                   | consume code (one-shot)       |
        |                                   | device_token=token_urlsafe(32)|
        |                                   | INSERT paired_devices row     |
        |                                   |   (token_hash=sha256(...))    |
        |                                   | 5. {device_token, device_id} |
        |                                   |----------------------------->|
        |                                   |   phone stores in localStorage|
        |                                   |        6. POST /api/track/{tid}
        |                                   |           Bearer device_token |
        |                                   |<-----------------------------|
        |                                   | require_session: hash+lookup  |
        |                                   |   revoked=0 -> 2xx            |
```

- Pairing-code store = **in-memory dict** (`{code: expires_at}`, `threading.Lock`, lazy TTL purge — mirrors `app/rate_limit.py:BucketStore` shape). Codes are ephemeral (60 s); no need to survive a sidecar restart. Only the *device-token* persists (to `auth.db`).
- One-shot: `complete` deletes the code from the dict on first valid use. A replay of the same code → not found → 410 (or 409 if the doc wants to distinguish "consumed" from "expired"; sister test `test_pairing_complete_idempotent_on_token_replay_returns_409` wants 409 for replay).

### 2026-05-19 — dual-acceptance design for `require_session`

Extending `require_session` (`app/auth.py:95-115`) without changing its signature:

```
def require_session(authorization = Header(None)) -> None:
    candidate = _extract_bearer(authorization)        # existing scheme-split, 401 on malformed
    if safe_compare(candidate, SESSION_TOKEN):        # branch 1: Tauri-main boot token
        return
    if _paired_token_valid(candidate):                # branch 2: paired device-token
        return
    raise HTTPException(401, "Unauthorized")
```

- `_paired_token_valid(candidate)` lives in `app/auth_db.py`: `h = sha256(candidate)`, `SELECT 1 FROM paired_devices WHERE token_hash=? AND revoked=0`, best-effort `UPDATE last_seen_at`. Returns bool.
- Branch order: `SESSION_TOKEN` first (constant-time, one comparison, the Tauri-main hot path) — only fall through to a DB hit on miss.
- `SESSION_TOKEN` empty-string guard already holds: in a `ProcessPoolExecutor` child `SESSION_TOKEN == ""`, and `safe_compare(candidate, "")` is `False` for any real token — branch 1 safely no-ops there.
- WebSocket variant: Phase-1 archive line 429 mandates a future `require_session_ws`. Still 0 `@app.websocket` routes (sister doc verified). If a paired-mobile WS ever lands, `require_session_ws` reuses the same two-branch check inside the handler. Not in Phase-2 scope — noted so the dual-acceptance logic is written once, in a shared helper, not duplicated.

## Adversarial Findings

### 2026-05-29 — devil's-advocate on Option A

- **`last_seen_at` write-per-GET (material).** Best-effort (Findings 2026-05-19 schema, line 147) covers *errors*, not *contention*. Every authed GET becomes a SQLite WRITE under the `auth.db` `threading.Lock` (line 148) → serializes all auth + fsync under concurrent mobile load. Risks the sister doc's G7 p95≤350ms budget. Mitigation absent: write only if `>60s` stale + WAL (`PRAGMA synchronous=NORMAL`) or async-queue. **Resolve at draftplan.**
- **Connection lifecycle underspecified.** `require_session` is sync (`auth.py:95`) → FastAPI threadpool → many threads hit `auth.db`. Doc's `threading.Lock` serializes writers but never states read connection model. A single shared connection + `check_same_thread` throws/serializes; needs per-thread connections (`live_database.py:27` pattern). Underspecified, not wrong.
- **QR shoulder-surf (accepted-risk, make explicit).** `lmsapp://pair?host=&port=&code=` shown as QR + plaintext; camera-capture within the 60s TTL = full pairing. Bounded by one-shot + physical proximity. Add an explicit accepted-risk line vs leaving silent.
- **No pairing/auth audit log (Repudiation).** `revoked` flag keeps a device audit trail, but no record of pairing attempts / auth failures despite the `auth.db` "headroom" rationale (OQ10). If `last_seen_at` writes get throttled (above), it's also the only breach signal — detection degrades. Minor; note for draftplan.
- **`complete` rate-limit key.** `@rate_limit(5,10,"both")` mandated (G6) — good; but `make_key` keys unauth `complete` on IP (`rate_limit.py:126`), so all phones behind one NAT share a bucket / IP-rotation defeats it. 256-bit code makes guessing moot; minor.

## Citation Quality

### 2026-05-29 — PASS (8/8)

- PASS: `require_session` sync + `safe_compare(candidate, SESSION_TOKEN)` (`auth.py:95-115`, l.114); `SESSION_TOKEN` (`auth.py:84`); `MainProcess` guard (`auth.py:83`, banner l.85 + token-file l.87); non-main `SESSION_TOKEN = ""` (`auth.py:92`) → `safe_compare(x,"")` False; `safe_compare` (`security_compare.py:23`, `secrets.compare_digest`); `BucketStore` in-mem TTL store (`rate_limit.py:82`, `_purge_stale` l.90; commit `830c056` confirmed); ZERO `@app.websocket` routes (grep empty).
- Cosmetic: `rate_limit.py` lock is `RLock` not plain `Lock` (doc said `Lock`). Harmless.
- ABSENT = planned new code (not a wrong cite): `_extract_bearer` helper (doc pseudocode) — to be written in Phase-2.

## Research Verification

### 2026-05-29 — PASS

- All 10 OQs RESOLVED/PARKED; Findings cite-accurate (Citation Quality 8/8 PASS); 4 options compared with a decision matrix; Recommendation (Option A) internally consistent and unchallenged by the adversarial pass (it found refinements to Option A's *implementation*, not a reason to prefer B/C/D).
- **Carry-forward to draftplan (do NOT block `evaluated_`):** (1) `last_seen_at` write strategy — throttle (>60s stale) + WAL + per-thread connections, so auth reads don't serialize on a write lock; (2) explicit QR shoulder-surf accepted-risk line; (3) optional pairing/auth audit log. These are plan-stage design details, not open research questions.
- Verdict: **PASS** → advance to `evaluated_`. Next user gate is C (after the plan).

## Options Considered

Required by `evaluated_`. Per option: sketch ≤3 bullets, pros, cons, S/M/L/XL, risk. Axes that differ: token-at-rest form, pairing-code persistence, code-store location.

### Comparison matrix

| Option | Device-token at rest | Pairing-code store | New deps | Code (impl + tests) | DB-leak resilience | Effort |
|---|---|---|---|---|---|---|
| **A — token_hash in `auth.db`, in-mem code** | SHA-256 hash | in-memory dict, 60 s TTL | 0 | ~120 + ~90 LoC | strong (hash) | M |
| **B — plaintext in `auth.db`, in-mem code** | plaintext | in-memory dict, 60 s TTL | 0 | ~105 + ~80 LoC | weak (plaintext) | M |
| **C — JWT, no DB, deny-list only** | not stored (stateless JWT) | in-memory dict, 60 s TTL | +1 (`PyJWT`) | ~110 + ~95 LoC | n/a (no token DB) | M |
| **D — token_hash in `master.db`** | SHA-256 hash | row in `master.db` | 0 | ~115 + ~90 LoC | strong (hash) | L |

### Option A — `token_hash` in sidecar-local `auth.db`, in-memory pairing-code store

- Sketch: new `app/auth_db.py` owns `auth.db` + `paired_devices` table (schema in Findings). Device-token issued plaintext to the phone once; only its SHA-256 hash persists. Pairing-codes live in an in-memory `{code: expires_at}` dict (60 s TTL, own `threading.Lock`). `require_session` gains branch 2: `sha256(candidate)` → indexed lookup `WHERE token_hash=? AND revoked=0`.
- Pros: leaked `auth.db` yields no usable tokens (hashes only); zero new deps (Schicht-A pinning surface unchanged); `master.db` never touched (no Rekordbox lock contention); revoke = one `UPDATE`, instant; ephemeral codes correctly don't survive restart; matches Phase-1 `app/auth.py` module shape and `app/rate_limit.py` in-mem-store shape.
- Cons: one SHA-256 + one SQLite SELECT per authed request (negligible — sub-ms); diverges from Phase-1's plaintext `.session-token` precedent (justified: multi-row store vs single-secret file).
- Effort: M (~120 LoC `auth_db.py` + 3 routes in `app/main.py` + ~90 LoC `tests/test_pairing.py`).
- Risk: low — every primitive (`secrets`, `sha256`, `safe_compare`, SQLite, in-mem TTL dict) is already proven in-repo.

### Option B — plaintext device-token in `auth.db`

- Sketch: identical to A but `paired_devices` stores the raw `device_token` (indexed, unique) instead of `token_hash`. `require_session` branch 2 = direct `safe_compare` against the stored column / `WHERE device_token=?`.
- Pros: marginally less code (no hash step); exact consistency with Phase-1's plaintext `.session-token` file; trivially debuggable (token visible in DB).
- Cons: a leaked / cloud-synced / support-dumped `auth.db` hands an attacker **every paired phone's live credential** at once — exactly the multi-device blast-radius hashing exists to contain; the SQLite file is not as locked-down as a single ACL'd `.session-token`.
- Effort: M (~105 LoC).
- Risk: medium — single-file leak = full auth compromise across all devices; the convenience saved is trivial.

### Option C — stateless JWT device-tokens, deny-list table only

- Sketch: `complete` returns a signed JWT (`{device_id, iat}`, HS256, server secret). No per-token row; `require_session` verifies the signature. Revocation = a `revoked_jwt(jti)` deny-list table consulted on each request. Pairing-codes still in-memory.
- Pros: token validity is a pure crypto check (no SELECT on the happy path); device list is implicit in issued JWTs.
- Cons: +1 pinned dep (`PyJWT` — Schicht-A surface grows, CVE-watch); revocation **still needs a DB** (deny-list) so the "no DB" win evaporates — and a deny-list is strictly worse than an allow-list (grows unbounded, can't enumerate active devices for the Settings UI without a *second* source of truth); JWT claims buy nothing (no expiry wanted, no roles); over-engineered for a single-user LAN tool.
- Effort: M (~110 LoC) — not cheaper than A despite "no token storage".
- Risk: medium — JWT footguns (alg-confusion, secret rotation invalidating all devices); the Settings "Paired Devices" list (G4) becomes awkward.

### Option D — `token_hash` row in `master.db`

- Sketch: same hashing as A, but the `paired_devices` table is a new table inside `master.db` instead of a separate `auth.db`.
- Pros: one fewer DB file; reuses the existing `app/database.py` connection + `_db_write_lock`.
- Cons: every pairing write + every `last_seen_at` update must take `_db_write_lock` and **blocks whenever Rekordbox holds the `master.db` write-lock** — i.e. a phone can't authenticate while the user has Rekordbox open; adds a table to the Rekordbox-owned schema (violates the "no shared-schema changes lightly" rule — Phase-1 archive Option B line 289 calls this out explicitly); couples auth lifecycle to library-DB migrations.
- Effort: L (schema migration into a third-party-owned DB + lock-contention testing).
- Risk: medium-high — auth availability becomes hostage to Rekordbox's lock; schema-drift risk against pyrekordbox.

## Recommendation

Required by `evaluated_`. ≤80 words. Which option + what blocks commit.

**Option A** — `token_hash` in sidecar-local `auth.db` + in-memory 60 s pairing-code store. Hashed-at-rest contains multi-device leak blast-radius (vs B); no new dep and a usable Settings device-list (vs C); no Rekordbox lock contention (vs D). Reuses Phase-1 `auth.py` + `rate_limit.py` shapes wholesale. **Gate to `evaluated_`**: none of OQ1-10 block — 9 RESOLVED, OQ7 PARKED (non-blocking, mobile-doc owns it). Promote once a reviewer confirms the dual-acceptance + handshake sketches. **Gate to `draftplan_`**: confirm `complete` replay → 409 vs 410 split with the sister doc's test contract; AND resolve the `last_seen_at` write-per-request contention (Adversarial 2026-05-29) — write-throttle (>60s stale) + WAL + per-thread `auth.db` connections so authed reads never serialize on the writer lock.

---

## Implementation Plan

Required from `implement/draftplan_`. Concrete enough that someone else executes without re-deriving.

### Scope
- **In:** Option A — sidecar-local `auth.db` with `paired_devices(token_hash)` + in-memory 60s pairing-code store; `require_session` dual-acceptance (SESSION_TOKEN OR paired device-token); 4 pairing routes; Tauri QR render; Settings "Paired Devices" list + revoke.
- **Out:** mobile UI itself (sister `mobile-companion` doc owns it); `MOBILE_ALLOWED_ORIGINS` CORS env-extension (sister doc, landed alongside frontend wiring); WebSocket `require_session_ws` (0 routes today — write dual-acceptance once in a shared helper so a future WS variant reuses it, but don't add the WS route); mDNS discovery (M2 Capacitor); token expiry (deliberately none — revoke UI is the lifecycle control).

### Step-by-step
1. **`app/auth_db.py`** — owns `auth.db` at `platformdirs.user_data_dir` (same dir as `.session-token`). `init_db()` idempotent (`CREATE TABLE IF NOT EXISTS` per Findings schema; `WAL` + `PRAGMA synchronous=NORMAL`); per-thread connection via `threading.local()` (mirrors `live_database.py:27`); dedicated `threading.Lock` for writers (NOT `_db_write_lock` — separate file). Functions: `create_device(token, display_name) → device_id`; `paired_token_valid(candidate) → bool` (`sha256` → `SELECT 1 WHERE token_hash=? AND revoked=0`; **throttled** best-effort `last_seen_at` write only if >60s stale — resolves Adversarial 2026-05-29 contention); `list_devices()`; `revoke_device(device_id)`. `MainProcess` guard on init (mirror `auth.py:83`).
2. **In-memory pairing-code store** — `{code: expires_at}`, own `threading.Lock`, 60s TTL, lazy purge (mirror `rate_limit.py:BucketStore`). One-shot consume on `complete`.
3. **Extend `app/auth.py`** — add `_extract_bearer(authorization) → str|None` (pseudocode calls it; currently ABSENT); `require_session` gains branch 2 `if _paired_token_valid(candidate): return` after the existing `safe_compare(candidate, SESSION_TOKEN)` branch. Signature unchanged. Child-process empty-`SESSION_TOKEN` guard already holds (`auth.py:92`).
4. **Routes in `app/main.py`:** `POST /api/pairing/start` (`Depends(require_session)` — desktop mints code with SESSION_TOKEN; returns `{code, host, port}`); `POST /api/pairing/complete` (**no session** — phone has no token yet; `@rate_limit(5, 10, "both")` mandatory; validate code → unknown/expired 410, consumed 409 → issue `device_token` + INSERT row); `DELETE /api/pairing/{device_id}` + `GET /api/pairing/devices` (both `Depends(require_session)`).
5. **Tauri (`src-tauri`)** — desktop calls `/api/pairing/start` with SESSION_TOKEN, renders QR `lmsapp://pair?host=&port=&code=` + plaintext `host:port:code` fallback.
6. **Frontend Settings** — "Paired Devices" section: list (`display_name`, `created_at`, `last_seen_at`) + per-device Revoke → `DELETE`.

### Files touched
- **New:** `app/auth_db.py` (~120 LOC), `tests/test_pairing.py` (~120 LOC).
- **Modified:** `app/auth.py` (+`_extract_bearer` + branch 2, ~30), `app/main.py` (+4 routes, ~100), `src-tauri/src/...` (QR render + `/start` call), `frontend/src/components/settings/Settings*.jsx` (device list), `docs/backend-index.md` (+4 routes), `docs/SECURITY.md` (Phase-2 chapter), `.claude/rules/coding-rules.md` ("never log device-token" line per Findings 2026-05-19).

### Testing
- `tests/test_pairing.py`: handshake happy-path (`start`→`complete`→authed `GET`); replay code → 409; expired/unknown → 410; **dual-acceptance** (SESSION_TOKEN 2xx + device_token 2xx + revoked → 401); `revoke_device` flips flag (UPDATE not DELETE); `last_seen_at` throttle (no write if <60s); `@rate_limit` on `complete` (6th in window → 429); child-process `SESSION_TOKEN==""` → device-token branch still works.
- Concurrency: N-thread `paired_token_valid` reads don't serialize on the writer lock (per-thread connections + WAL).

### Risks & rollback
- **`last_seen_at` contention (Adversarial 2026-05-29) — MITIGATED:** throttle (>60s stale) + WAL + per-thread read connections; authed reads never block on the writer lock, preserving sister doc p95≤350ms.
- **Leaked `auth.db` = hashes only** (Option A core property) — no usable tokens.
- **Pairing-code lost on sidecar restart** mid-pairing → 410 → re-scan (acceptable, one-time setup).
- **QR shoulder-surf** within 60s = full pairing — accepted risk (physical-proximity), documented in `SECURITY.md`.
- **Rollback:** delete `auth.db` + revert `auth.py` branch-2 + remove the 4 routes → SESSION_TOKEN-only auth restored, paired devices fall back to 401. No `master.db` touched.

### Task Queue
> Each = one `routine/security-mobile-paired-tokens-phase2-task-N` branch = one PR. Ordered.

- [ ] **T1 (Step 1):** `app/auth_db.py` — `auth.db` init (WAL, per-thread conn, writer Lock) + schema + `create_device`/`paired_token_valid` (throttled last_seen)/`list_devices`/`revoke_device`. Tests: schema-create, create+lookup, revoke flips flag, last_seen throttle.
- [ ] **T2 (Step 2):** in-memory pairing-code store (TTL dict + Lock + lazy purge). No deps. Tests: mint/consume one-shot, expiry purge.
- [ ] **T3 (Step 3):** `app/auth.py` `_extract_bearer` + `require_session` dual-acceptance (shared helper reusable by future `require_session_ws`). Deps: T1. Tests: dual-acceptance matrix + child-process empty-token.
- [ ] **T4 (Step 4):** `POST /api/pairing/start` + `POST /api/pairing/complete` (`@rate_limit(5,10,"both")`, 409/410 split). Deps: T1, T2, T3. Tests: handshake, replay 409, expired 410, rate-limit 429.
- [ ] **T5 (Step 4):** `DELETE /api/pairing/{device_id}` + `GET /api/pairing/devices` (`require_session`). Deps: T1, T3. Tests: list + revoke→401.
- [ ] **T6 (Step 5):** Tauri QR render + `/start` call with SESSION_TOKEN + plaintext fallback. Deps: T4.
- [ ] **T7 (Step 6):** frontend Settings "Paired Devices" list + revoke + re-pair screen. Deps: T5.
- [ ] **T-docs:** `backend-index.md` (+4 routes), `SECURITY.md` Phase-2 chapter, `coding-rules.md` never-log-device-token line. Folds into each PR.

## Review

Filled at `review_`. Unchecked box or rework reason → `rework_`.

- [x] Plan addresses all goals — per-device long-lived bearer (T1/T4), QR pairing UX (T6), revoke surface (T1/T5/T7), dual-acceptance without breaking Phase-1 (T3). Maps to mobile-companion Pre-M1 hard prereq.
- [x] Open questions answered or deferred — OQ1-10 resolved/parked at research; the one draftplan carry-forward (`last_seen_at` contention) is now resolved in Step 1 + Risks (throttle+WAL+per-thread conn); replay 409-vs-410 split fixed in T4.
- [x] Risk mitigations defined — hashes-at-rest, rate-limited unauth `complete`, throttled last_seen, QR shoulder-surf accepted-risk, child-process empty-token guard.
- [x] Rollback path clear — delete `auth.db` + revert branch-2 + remove routes; no `master.db` touched.
- [x] Affected docs identified — `backend-index.md`, `SECURITY.md` Phase-2 chapter, `coding-rules.md`; `architecture.md` auth data-flow + `FILE_MAP.md` (`app/auth_db.py`) at graduation.

**Reviewer note (2026-05-29):** PASS. Every primitive (`secrets`, `sha256`, `safe_compare`, sqlite WAL, in-mem TTL store, `@rate_limit`) is already proven in-repo. `_extract_bearer` is the only net-new helper. The adversarial `last_seen_at` concern that gated this at evaluated_ is fully addressed in the plan. No security-surface gaps: `complete` is the only unauthenticated route and it's rate-limited + 256-bit-code-gated.

**Rework reasons:**
- None — PASS.

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
