---
slug: soundcloud-persistent-login
title: SoundCloud persistent login (refresh-token + survive restart)
owner: tb
created: 2026-05-31
last_updated: 2026-05-31
tags: []
related: []
supersedes: []
superseded_by: []
---

# SoundCloud persistent login (refresh-token + survive restart)

> **Caveman+ style.** Fragments, bullets. Drop articles/filler/hedges. No prose paragraphs.
> Word caps are **soft** — recommendations, not hard blocks. Exceed when topic complexity demands; routines may flag excess length but never truncate facts.
> State = folder + filename prefix (not frontmatter). Lifecycle = audit trail. See `../README.md`.
> Routines advance this doc **autonomously** by state. **One** user gate: `approvalgate_` — read `## Approval Summary` + `## Mockup`, then `/approve` or `/reject`. After approval you test the finished branch locally and merge it yourself.
> Section ownership: each `> ↓ Stage X — <agent>: …` marker names the agent that fills the section. Don't write into a section before its stage.

## Lifecycle

- 2026-05-31 — `research/idea_` — created from template
- 2026-05-31 — `research/drafting_` — Original Idea filled; advanced for research-draft routine
- 2026-05-31 — `research/exploring_` — drafted (scout + prior-art + risk-surface + worker + idea-verifier PASS), ready for explore
- 2026-05-31 — `research/exploring_` — explore phase 1 done (tiered codebase+web+synthesis × 4 aspects / 8 OQs)
- 2026-05-31 — `research/evaluated_` — explore phase 2 verified (adversarial + citation + research-verifier PASS), recommendation = Option A

## Original Idea (verbatim — never edit)

After logging in to SoundCloud I have to log in again before almost every action, and again every time I restart the app. I want the login to persist — stay signed in across app restarts and across all SoundCloud features (browse, library sync, downloads) until I explicitly log out.

---

> ↓ Stage 1 — `drafting_`. `research-draft` fills Problem → Research Plan via 4 agents (Scout, Prior-Art, Risk-Surface, Worker). Verifier fills Idea Verification.

## Prior Art

- **Shipped:** [implemented_security-api-auth-hardening_2026-05-17](../archived/implemented_security-api-auth-hardening_2026-05-17.md) — Bearer + `require_session` + keyring token-handoff pattern. Covers app session token (`LMS_TOKEN`); does NOT touch SC OAuth refresh/expiry.
- **Shipped:** [implemented_security-cors-allow-credentials-tightening_2026-05-18](../archived/implemented_security-cors-allow-credentials-tightening_2026-05-18.md) — bearer-in-header only, no auth cookies. Constrains: SC refresh must not add cookie-auth.
- **Active:** [inprogress_security-mobile-paired-tokens-phase2](../implement/inprogress_security-mobile-paired-tokens-phase2.md) — hashed-token `auth.db` + `last_seen_at` throttle. Reusable storage pattern if keyring rejected.
- **Active:** [accepted_downloader-unified-multi-source](../implement/accepted_downloader-unified-multi-source.md) — downloads depend on SC auth; token expiry mid-download must not break flow.
- **External precedent:** SoundCloud OAuth 2.1 (`secure.soundcloud.com`) issues `refresh_token` + `expires_in` (~1h) for auth-code grant; `grant_type=refresh_token` renews (RFC 6749 §6). Verify in explore.
- Verdict: **greenfield** for SC token persistence/refresh — reuses existing auth infra, no overlap/duplication.

## Problem

SC OAuth access token ~1h TTL. App persists only bare access token (`app/main.py:3509`); `refresh_token` + `expires_in` arrive from SC but get discarded in Rust (`soundcloud_client.rs:107-115,232`), in the frontend, and in the backend (`ScAuthTokenReq` = 1 field, `app/main.py:3474`). No renewal path. On expiry every SC action 401s → forced interactive browser re-login (`api.js:168`). Restart shows false "logged in" (existence-only `auth-status`, `app/main.py:3534`). Cost: constant re-login; long sync/download breaks mid-flight.

## Goals / Non-goals

**Goals**
- SC login survives app + sidecar restart — no re-login on next launch.
- Token renews **silently server-side** — no browser popup until refresh genuinely fails.
- One shared auth state across all SC features (browse, library sync, downloads).
- Long-running download/sync survives token expiry mid-operation.
- Explicit logout still wipes all SC credentials.

**Non-goals**
- First-time interactive OAuth login unchanged (Rust PKCE flow stays).
- No multi-account / account switching.
- No new OAuth scopes.
- No cookie-based auth (forbidden, `coding-rules.md:16`).
- App session-token (`LMS_TOKEN`) auth untouched.

## Constraints

- **External API / rate limits:** SoundCloud OAuth `secure.soundcloud.com` — `AUTH_URL` `src-tauri/src/soundcloud_client.rs:89`, `TOKEN_URL` :90. Access token short-lived; renew via `grant_type=refresh_token`. Exact TTL + whether SC rotates/expires refresh tokens = OQ1/OQ2.
- **Token never-log:** `.claude/rules/coding-rules.md:15` + `docs/SECURITY.md:167,169` — never log token at any level; `refresh_token` falls under the same rule.
- **Bearer-only, no cookie auth:** `.claude/rules/coding-rules.md:16` — refresh path must not introduce `set_cookie`.
- **Secrets:** `SOUNDCLOUD_CLIENT_ID/SECRET` in `.env` only (`.claude/rules/coding-rules.md:13`); refresh grant needs `client_secret` — already present in Python `.env` + Rust config.
- **Keyring storage:** `KEYRING_SERVICE`/`KEYRING_SC_TOKEN` `app/main.py:76,78`; store at :3509, logout-delete at :3514. New `refresh_token` + `expires_at` need extra keys / blob.
- **Schicht-A pinning:** `.claude/rules/coding-rules.md:7` — deps `==X.Y.Z`. `requests==2.33.1` (`requirements.txt:20`) + `keyring==25.7.0` (`requirements.txt:45`) already pinned + already used by SC code.
- **No `requests` in async:** `.claude/rules/coding-rules.md:35`. Existing SC code is sync `requests` (`app/soundcloud_api.py:20`, `app/soundcloud_downloader.py:69`); refresh call must fit that context (sync helper / executor) → OQ3.
- **Auth gating + rate-limit:** `/api/soundcloud/auth-token` behind `require_session` + `@rate_limit(steady=5,burst=10)` `app/main.py:3481-3482`; a new refresh route needs both.
- **Concurrency invariants:** `_db_write_lock` / `validate_audio_path` / `SafeAnlzParser` — N/A (no `master.db` write, no filesystem path, no ANLZ).

## Dependencies

Baseline: **None — uses existing stack only.** Refresh reuses pinned `keyring` (store) + `requests` (refresh-grant POST, matches existing SC code). `httpx` only if explore (OQ3) picks async-by-the-book refresh → then a new Schicht-A dep.

| Dep | Kind | Version | License | Schicht-A audit needed? | Why |
|---|---|---|---|---|---|
| keyring | py | 25.7.0 (`requirements.txt:45`) | MIT | no — already pinned/used | store `refresh_token` + `expires_at` |
| requests | py | 2.33.1 (`requirements.txt:20`) | Apache-2.0 | no — already pinned/used | refresh-grant POST (matches `soundcloud_api.py`) |
| httpx | py | absent/unpinned | BSD-3 | yes — only IF added | only if async refresh chosen (OQ3) |

## Open Questions

1. Does SoundCloud's PKCE auth-code flow return a usable `refresh_token` + `expires_in`, and does `grant_type=refresh_token` mint a fresh access token without re-prompting? (yes/no — SC docs + already-deserialized struct fields `soundcloud_client.rs:107-115`).
2. Does SoundCloud rotate the `refresh_token` on each refresh (must re-store the new one), and do refresh tokens themselves expire? (rotate yes/no; refresh-TTL value).
3. Where does the refresh grant run — Python (reuse sync `requests`, `client_secret` from `.env`) vs Rust (`soundcloud_client.rs`, secret already there)? Sync `requests` vs httpx-async per `coding-rules.md:35`? (Python vs Rust).
4. Credential storage shape — keyring multi-key (`sc_refresh_token`, `sc_token_expiry`) vs single JSON blob under `sc_token` vs reuse `auth.db` (paired-tokens phase2)? (multikey vs blob vs auth.db).
5. Refresh trigger — proactive (on launch / when `now > expires_at − buffer`) vs reactive (on 401, retry-once) vs both? (which strategy).
6. Should `/api/soundcloud/auth-status` report real validity/refreshability instead of existence-only (`app/main.py:3534`)? (existence vs validity).
7. Frontend rework — replace interactive `_refreshScToken` → `invoke('login_to_soundcloud')` (`api.js:168`) with a silent backend `POST /api/soundcloud/refresh`; scope the 401 interceptor to SC URLs only (does it currently fire on non-SC 401s? `api.js:227`); share auth state across the 3 views. (confirm approach).
8. Logout ceremony — explicit logout must delete access + refresh + expiry (today only `sc_token` cleared, `app/main.py:3514`). (enumerate keys to clear).

## Research Plan

- Agent 1 (web + codebase): SoundCloud OAuth token semantics — `refresh_token` issuance, `expires_in` value, refresh-token rotation + expiry, `grant_type=refresh_token` request/response shape (SC dev docs) cross-checked vs `soundcloud_client.rs:107-234`. Covers OQ1, OQ2.
- Agent 2 (codebase + web): refresh ownership Rust-vs-Python — `client_secret` location, sync `requests` vs httpx-async constraint (`coding-rules.md:35`, `soundcloud_api.py:20`), how async routes invoke sync SC helpers. Covers OQ3, OQ7-async.
- Agent 3 (codebase): credential storage shape — keyring multi-key vs JSON blob vs `auth.db` reuse (paired-tokens phase2); never-log compliance; logout clear-all set. Covers OQ4, OQ8.
- Agent 4 (codebase): renewal trigger + `auth-status` validity + frontend interceptor/per-view rework (`api.js:227-249`, `SoundCloudView.jsx:15`, `SoundCloudSyncView.jsx:219`). Covers OQ5, OQ6, OQ7.

## Idea Verification

### 2026-05-31 — PASS
- **Intent fidelity:** clean — all 3 wants (restart-persist, silent per-action renewal, logout-wipe) map to Goals; Non-goals fence scope-creep.
- **Prior-art:** clean — 4 adjacent docs classified (overlap / constraint / reusable); greenfield verdict justified.
- **Research-Plan:** clean — 8 OQs all decidable, each maps to ≥1 agent, no orphans either way.
- Citations spot-checked (`main.py:3474/3509/3534`, `soundcloud_client.rs:107-115`, `api.js:168`, `requirements.txt:20/45`) — accurate.

---

> ↓ Stage 2 — `exploring_` (autonomous; no user gate). On Idea-Verifier PASS, `research-draft` advances `drafting_` → `exploring_` directly. `research-explore` runs parallel tiered agents (codebase + web + synthesis per OQ), an Adversarial agent, a Citation-Quality verifier, and a Research-Verifier — one autonomous pass to `evaluated_`.

## Findings / Investigation

### 2026-05-31 — F1: SC OAuth token lifecycle (OQ1, OQ2)
- **Codebase:** `TokenResponse` (`soundcloud_client.rs:107-115`) deserializes `access_token` (used) + `token_type`/`expires_in`/`refresh_token` (all `#[allow(dead_code)]`). `exchange_code_for_token` returns only `access_token` (`:233`). `get_auth_url` (`:171-199`): `response_type=code`, PKCE S256, **no `scope`**. `AUTH_URL`/`TOKEN_URL` `:89-90`. Zero expiry/refresh handling in `app/` or `src-tauri/`.
- **Web:** auth-code+PKCE returns `access_token`+`refresh_token`+`expires_in`+`scope`; access TTL ~1h per guide (conflict: 2024 blog says 6h → trust runtime `expires_in`). `grant_type=refresh_token` POST params: `grant_type,client_id,client_secret,refresh_token` (no `redirect_uri`). **Refresh token is SINGLE-USE / rotates** — each refresh returns a NEW refresh_token; must persist it. Refresh-token TTL undocumented → handle `invalid_grant` by forcing re-auth. (https://developers.soundcloud.com/docs/api/guide, https://developers.soundcloud.com/blog/security-updates-api/, https://github.com/soundcloud/api/issues/80)
- **Synthesis:** Persistent login feasible — SC already returns everything; app discards it (`:233`). Rotation is the key complication: each renewal consumes the old refresh_token, so renewal must serialize + atomically store the rotated token.
- **Confidence:** high (codebase + primary vendor docs agree; only refresh-token TTL unknown).

### 2026-05-31 — F2: Refresh ownership + sync/async (OQ3, OQ7-async)
- **Codebase:** Python loads `SOUNDCLOUD_CLIENT_ID` via `os.environ` (`soundcloud_api.py:52`) but **NOT the secret** — Python has no `client_secret` today. Rust has both (`soundcloud_client.rs:67-72,75-80`), used in exchange (`:211-212`). Async routes call sync SC helpers via `asyncio.to_thread(...)` (`main.py:3613,3657,3316`). `AuthExpiredError` exists (`soundcloud_api.py:138`); no refresh.
- **Web:** Refresh **server-side**: Python sidecar = confidential client (may hold secret); Tauri shell = public client (PKCE only). refresh grant requires `client_secret`. Sync `requests` in `async def` blocks loop → `run_in_threadpool`/`asyncio.to_thread` (existing pattern) or async `httpx`. (https://www.oauth.com/oauth2-servers/access-tokens/refreshing-access-tokens/, https://workos.com/blog/oauth-best-practices, https://fastapi.tiangolo.com/async/)
- **Synthesis:** Refresh in Python sidecar → must add `SOUNDCLOUD_CLIENT_SECRET` to Python env loading (Rust-only today). Reuse existing `asyncio.to_thread` + `requests` (no new dep) vs async `httpx` per `coding-rules.md:35` = the OQ3 fork. Rust-side refresh keeps secret put but can't renew during background sidecar work → Python preferred.
- **Confidence:** high.

### 2026-05-31 — F3: Credential storage + logout (OQ4, OQ8)
- **Codebase:** keyring stores only bare access token (`main.py:3509`); reads at `:3226,3303,3534,3589,3650,3683,3731,3776,3822`; logout deletes only `sc_token` (`:3514`); `KEYRING_*` consts `:76,78`. Paired-tokens phase2 `app/auth_db.py`: `%APPDATA%/MusicLibraryManager/auth.db`, table `paired_devices` (sha256 `token_hash`, WAL, per-thread conns, `_write_lock`).
- **Web:** keyring multi-entry vs JSON blob. **Windows Credential Manager practical ~1280-byte ceiling** → combined blob risks overflow; favor separate entries. OS keyring is the recommended at-rest store for refresh tokens (never plaintext). (https://github.com/jaraco/keyring/issues/540, https://developers.google.com/identity/protocols/oauth2/resources/best-practices, https://learn.microsoft.com/en-us/windows/win32/api/wincred/ns-wincred-credentiala)
- **Synthesis:** Store 3 separate keyring entries (`sc_token`, `sc_refresh_token`, `sc_token_expiry`) under existing service — dodges the 1280-byte cap, OS-native, minimal change. `auth.db` reuse is overkill (single user, no per-device need). Refresh_token stored **plaintext-usable** (NOT hashed like device tokens — must be replayable). Logout must delete all 3 keys.
- **Confidence:** high.

### 2026-05-31 — F4: Renewal trigger + auth-status + frontend (OQ5, OQ6, OQ7)
- **Codebase:** 401 interceptor fires on **ANY** 401, no URL check (`api.js:227`); `_refreshScToken` calls interactive `invoke('login_to_soundcloud')` (`:168`); `MAX_REFRESH_FAILS=2` (`:132`). Per-view independent auth state, no sharing, no re-check on tab switch (CSS `hidden`) (`SoundCloudView.jsx:28`, `SoundCloudSyncView.jsx:237`). `auth-status` existence-only (`main.py:3534`).
- **Web:** Combine proactive (refresh-ahead at `expires_at − buffer`, ~70-80% lifetime) + reactive (on-401 retry-once). Scope interceptor to `/api/soundcloud/*`. **Single-flight dedupe** (one shared refresh promise) — critical given single-use refresh tokens (concurrent refreshes race). Buffer 30-60s min. (https://nango.dev/blog/concurrency-with-oauth-token-refreshes/, https://www.oauth.com/oauth2-servers/making-authenticated-requests/refreshing-an-access-token/, https://www.npmjs.com/package/axios-auth-refresh)
- **Synthesis:** Backend owns renewal (proactive near-expiry + reactive on 401), serialized single-flight (matches SC rotation). Frontend `_refreshScToken` → silent `POST /api/soundcloud/refresh`; interactive login only on `invalid_grant`. Scope 401-handler to SC URLs (fixes wrong-popup-on-any-401). `auth-status` reports validity/refreshability. Per-view state → shared `sc:auth-changed` re-check (partly wired via ScAccountChip).
- **Confidence:** high.

## Adversarial Findings

### 2026-05-31
- **Weak assumption (F1/F4):** single-flight must be **backend-side** (a lock around the refresh grant), not just `api.js`. SC refresh is single-use → concurrent refreshes, proactive+reactive firing together, or a mid-refresh sidecar restart consume the rotated token; the loser holds a dead refresh_token → forced re-login despite the persistence promise.
- **Failure mode (F3):** 3 separate keyring writes are **non-atomic** — crash between writing access + refresh = mismatched pair → silent `invalid_grant` next launch. Mitigation: write refresh first, validate-on-read, treat partial state as logged-out.
- **Failure mode (F1/F4):** clock skew breaks the proactive `expires_at − buffer` trigger → reactive-on-401 must remain the backstop.
- **Failure mode (F2):** `client_secret` in Python `.env` widens blast radius to 2 processes (Rust + Python) — Constraints permit, but accept + document.
- **Coverage gap:** **browser-dev mode (no Tauri)** absent from F1-F4 — silent `/refresh` assumes the sidecar owns refresh; confirm it works without the Rust shell (secret in Python → should), else "persist across restart" breaks in dev.
- **Missing constraint:** never-log applies to `refresh_token` — new `/refresh` route + `invalid_grant` path must not echo it (→ threat-model). In-flight long downloads vs mid-refresh token handoff undefined (downloader prior-art).
- **Counter-example:** Nango blog (F4 cite) exists *because* in-memory single-flight + rotation still races across instances; their fix = server-side lock + stored token → reinforces backend single-flight.
- **Mitigated:** SSRF — refresh hits fixed `TOKEN_URL`, no user input ✔. Cookie-auth regression — bearer-only kept ✔.
- **Blockers:** (1) backend serialized single-flight + atomic store ordering; (2) browser-dev-mode refresh path. **Carry-forward:** clock skew, secret dual-process, refresh_token in logs, in-flight download handoff.

## Citation Quality

### 2026-05-31 — PASS
- PASS F1 — `soundcloud_client.rs:107-115` dead_code refresh_token/expires_in, `:233` returns access_token only, `:171-199` no `scope`; SC guide confirms single-use rotation + refresh params.
- PASS F2 — `:67-80` env getters; `soundcloud_api.py:52` reads CLIENT_ID; grep confirms Python never reads CLIENT_SECRET (0 matches).
- PASS F3 — `main.py:3509/3514` set/delete `sc_token`; keyring#540 confirms ~1280B Windows Credential Manager ceiling.
- PASS F4 — `api.js:227` 401 guard has no SC-URL scoping (any 401), `:168` invoke login; `main.py:3534` existence-only auth-status, `:3613` asyncio.to_thread.
- All 7 load-bearing citations verified; no FAIL, no unreachable URL.

---

> ↓ Stage 2 phase 2 (autonomous; no user gate) — `research-explore` deepens findings, runs Adversarial + Citation verifiers, then the Research-Verifier gates the whole body before Options-Synthesis advances the doc to `evaluated_`.

## Research Verification

Stage 2 wave-2 verifier over whole research body. ≤120 words. PASS → `evaluated_`; gaps → more Findings.

### 2026-05-31 — PASS
- **OQ coverage:** all 8 mapped, no orphans. OQ1→F1, OQ2→F1 (rotation yes; refresh-TTL flagged unknown), OQ3→F2, OQ4→F3, OQ5→F4, OQ6→F4, OQ7→F4+F2, OQ8→F3.
- **Internal consistency:** clean. F2 Python-side refresh + `client_secret` matches Constraints (secret in `.env`, dual-process accepted in Adversarial); refresh_token plaintext-usable (F3) ≠ hashed device-tokens (correct, must replay); never-log extended to refresh_token + carried forward. No contradictions.
- **Citation quality:** PASS — `## Citation Quality` all 4 findings PASS, 7 load-bearing cites verified, no FAIL/unreachable.
- **Adversarial concerns:** all captured. Both blockers present (backend single-flight + atomic store; browser-dev refresh). Carry-forwards: clock skew, secret dual-process, refresh_token-in-logs, in-flight download handoff. None dropped.

## Options Considered

### Option A — Backend-owned silent refresh (Python sidecar)
- Sketch:
  - Rust: return `{access_token, refresh_token, expires_in}` from exchange (stop discarding, `soundcloud_client.rs:233`) → frontend POSTs all three to backend.
  - Python: extend `ScAuthTokenReq` (access + refresh + expires_in); store 3 separate keyring entries (`sc_token`/`sc_refresh_token`/`sc_token_expiry`); add `SOUNDCLOUD_CLIENT_SECRET` to Python env loading.
  - Python `_ensure_valid_token()`: proactive (`now > expires_at − 60s`) + reactive (on SC 401) `grant_type=refresh_token` via existing `asyncio.to_thread` + sync `requests`, serialized by a `threading.Lock` (single-flight); atomically re-store rotated token (refresh-first write order).
  - New `POST /api/soundcloud/refresh` (`require_session` + `@rate_limit`); `auth-status` reports validity/refreshability; frontend `_refreshScToken` → that route (no browser); scope 401-interceptor to `/api/soundcloud/*`; interactive login only on `invalid_grant`; logout deletes all 3 keys.
- Pros: meets every Goal — silent, survives app + sidecar restart, shared backend state, background downloads/sync renew themselves; no new dep (`requests`+`keyring`); backend single-flight kills the rotation race.
- Cons: moves `client_secret` into Python `.env` (Adversarial 2026-05-31, dual-process exposure — accept+document); 3-key write non-atomic needs refresh-first ordering + validate-on-read (Adversarial 2026-05-31); browser-dev path must be verified (Adversarial 2026-05-31 blocker 2).
- Effort: M
- Risk: med — auth-path change; mitigated by write-ordering + tests.
- Prior-art match: reuses keyring pattern from `implemented_security-api-auth-hardening`; bearer-only per `implemented_security-cors-allow-credentials-tightening`.

### Option B — Rust-owned refresh (keep secret in Rust)
- Sketch: new `refresh_to_soundcloud` Tauri command does `grant_type=refresh_token` (secret already in Rust `:75-80`); frontend `invoke`s it silently → POSTs new token to backend; refresh_token persisted Rust-side.
- Pros: `client_secret` stays only in Rust (no dual-process exposure); reuses existing Rust OAuth module.
- Cons: refresh only works inside Tauri — **browser-dev mode can't `invoke`** → no silent refresh in dev (Adversarial 2026-05-31 blocker 2 made worse); background sidecar work (downloads/sync) can't trigger a Rust refresh while frontend idle → mid-download expiry still breaks (Adversarial 2026-05-31 in-flight concern unaddressed); refresh_token split-brain (Rust vs backend keyring); more IPC.
- Effort: M-L
- Risk: med-high — background-renewal gap, cross-process token state.
- Prior-art match: extends Rust `soundcloud_client` — novel for refresh.

### Option C — Minimal reactive-only backend refresh
- Sketch: Python stores refresh+expiry; refresh ONLY on SC 401 (reactive, retry-once), serialized; frontend calls silent `/refresh`; skip proactive trigger, auth-status-validity, per-view sharing, interceptor scoping.
- Pros: smallest change; fixes core "forced browser re-login" + restart persistence; no clock-skew surface (Adversarial 2026-05-31 — no proactive timer).
- Cons: first action each ~1h still eats one 401+retry latency; leaves the any-401 interceptor bug + per-view state unfixed (partial vs Goals); in-flight long download 401s mid-stream unless retry rewires the running request (Adversarial 2026-05-31 in-flight concern).
- Effort: S-M
- Risk: low
- Prior-art match: same keyring reuse as Option A.

## Recommendation

**Option A** — only option meeting all Goals (silent, restart- + sidecar-persistent, shared state, background-safe) with no new dependency. Option B breaks silent refresh in browser-dev + background tasks; Option C leaves the interceptor bug + in-flight expiry. **Blocks to resolve in plan:** (1) backend serialized single-flight + atomic refresh-first keyring write (Adversarial 2026-05-31 blocker 1); (2) verify the silent `/refresh` works in browser-dev without Tauri (blocker 2). **Threat-model carry-forwards:** `client_secret` dual-process, `refresh_token` never-logged in `/refresh` + `invalid_grant` paths, clock-skew (reactive backstop mitigates), in-flight download token handoff. Findings→OQ: F1→OQ1/2, F2→OQ3/7, F3→OQ4/8, F4→OQ5/6/7.

---

> ↓ Stage 3 — `implement/draftplan_`. `research-plan` fills Implementation Plan + Task Queue via 5 agents (Planner, Threat-Modeller, Migration, Perf-Budget, Test-Plan). Reviewer fills Review. On Review PASS, the Mockup+Summary-Agent fills `## Approval Summary` + `## Mockup`, then advances to `approvalgate_`.

## Implementation Plan

Stage 3 Planner-Agent. Concrete enough that someone else executes without re-deriving.

### Scope
- **In:** …
- **Out:** …

### Step-by-step
1. …

### Files touched
Path + role (read / edit / new):
- `<path>` — <role> — <why>

### Testing
High-level (see `## Test Plan` for concrete pytest/cargo cases):
- …

### Risks & rollback
- …

## Threat Model

Stage 3 Threat-Modeller-Agent. Required when feature touches: auth, `require_session`, filesystem (paths in / out), `master.db` writes, network, secrets, user-supplied paths. Otherwise: **"N/A — no security surface."**

### Assets
- … (data, secrets, attacker goal)

### Trust boundaries
- … (which layer trusts which input)

### Threats (STRIDE-light)
| ID | Threat | Mitigation in plan | Test covers |
|---|---|---|---|
| T1 | … | step N / file X | test_… |

### Residual risk
- ≤60 words — what cannot be eliminated, why acceptable.

## Migration Path

Stage 3 Migration-Path-Agent. Required when feature changes: DB schema, file layout, settings/config shape, IPC contract, on-disk caches, USB export bytes. Otherwise: **"N/A — no migration."**

### Before → After
- Data shape today: …
- Data shape after: …
- Existing-data handling: in-place migrate / lazy on read / one-shot backfill

### Backfill / forward-compat
- Migration script: `<file>` (or "no script — schema-additive")
- Old client reads new data: yes/no — how degraded
- Rollback: restore via `<backup>` / re-run reverse migration `<file>`

### User-visible behavior during migration
- … (downtime, progress UI, can app start before complete?)

## Performance Budget

Stage 3 Perf-Budget-Agent. Numbers, not "fast". If feature has no perceptible runtime cost: **"N/A — analysis-only / one-shot."**

| Path | Budget | Measured today | Source |
|---|---|---|---|
| <e.g. POST /api/duplicates/scan> | p95 ≤ 800ms / 50MB peak | … | `tests/perf/…` or "untested" |

### Worst-case scenario
- Input shape: <e.g. 50k tracks, 200 dupes>
- Expected impact: …
- Mitigation if exceeded: …

## API / UX Surface

Stage 3 Planner-Agent. What is added / changed at every layer the user / frontend touches.

### Backend (FastAPI)
- New routes: `<METHOD> <path>` — auth: `require_session`? rate-limited? lock?
- Changed routes: `<METHOD> <path>` — what changed in request/response shape

### Frontend (React)
- New components / hooks / IPC calls (axios + invoke):
- Changed components: …

### Tauri (Rust commands)
- New `#[tauri::command]`s: …
- Changed signatures: …

### CLI / sidecar logs
- New stdout markers (e.g. `LMS_TOKEN=`-style): …

## Telemetry

Stage 3 Planner-Agent. How we know it works after ship. ≤80 words. Otherwise: **"N/A — no runtime behavior to observe."**

- Log markers (`logger.info("op=… …")`): …
- Counters / timing: …
- Health-endpoint surface: …
- User-visible status (toast, statusline, dashboard tile): …

## Test Plan

Stage 3 Test-Plan-Agent. Concrete test cases, one row per. Must cover Threat Model + Migration + Perf budgets.

| ID | Layer | Test file | Case | Covers (Threat / OQ / Step) |
|---|---|---|---|---|
| T1 | py | `tests/test_<area>.py::test_<case>` | … | Threat T1 |
| T2 | rust | `src-tauri/src/audio/.../tests` | … | Step 3 |
| T3 | js | `frontend/src/**/*.test.js` | … | OQ 2 |
| T4 | integration | `tests/test_<integration>.py` | end-to-end happy path | full flow |
| T5 | perf | `tests/perf/<file>.py` (new) | p95 budget vs target | Perf table row N |

## Task Queue

<!--
Small, individually-committable implementation tasks. Written by research-plan (Stage 3),
approved by the user at the Approval Gate. research-implement works ONE task per branch:
routine/<slug>-task-<N>. 1 task = 1 feature = 1 PR. Tick - [x] when the PR is merged.
Keep tasks small — a task too big to review in one PR must be split.
Each task should map back to a Step in ## Implementation Plan and have ≥1 row in ## Test Plan.
-->

- [ ] <task — small, single-purpose, independently testable> — covers Step N, tests T<m>, T<n>

## Review

Stage 3 Reviewer-Agent (`review_`). Unchecked box or rework reason → `rework_`.

- [ ] Plan addresses all goals
- [ ] Plan matches `## Original Idea` — no scope-creep
- [ ] Open questions answered or deferred
- [ ] Prior Art referenced — no duplicated past work
- [ ] Threat Model present + each threat has a test (or N/A justified)
- [ ] Migration Path present + rollback documented (or N/A justified)
- [ ] Performance Budget set + worst-case scenario documented (or N/A justified)
- [ ] API / UX Surface enumerated for every layer touched
- [ ] Telemetry defined for shipped behavior (or N/A justified)
- [ ] Test Plan covers every Threat + every Step + every Perf row
- [ ] Task Queue items are small + independently committable + reference Steps + Tests
- [ ] Dependencies audited — new libs have Schicht-A entries
- [ ] Risk mitigations defined
- [ ] Rollback path clear
- [ ] Affected docs identified (`architecture.md`, `FILE_MAP.md`, indexes, `CHANGELOG.md`)

**Rework reasons:**
- …

## Approval Summary

Stage 3 Mockup+Summary-Agent (after Plan-Reviewer PASS). **Plain user-facing English — NOT Caveman.** This block is what the user reads to decide yes/no. ≤200 words. No `file:line` jargon — describe effects, not internals.

- **What it does:** 1–2 sentences, plain language. What the feature gives the user.
- **What you'll notice:** bullet list of user-visible effects (new button, faster scan, new export option, …).
- **Scope:** N files touched · N tasks · effort S/M/L · risk low/med/high.
- **Rollback:** one line — how it's undone if you dislike it after merge.
- **Mockup:** see `## Mockup` below.

## Mockup

Stage 3 Mockup+Summary-Agent. Adaptive to feature type — decide from `## API / UX Surface`:

- **UI feature** (has frontend components): write a self-contained static wireframe to `docs/research/mockups/<slug>.html` (inline CSS, no build step, no external assets — open in a browser locally). Fill the **UI** block below. Leave the **Backend** block empty/removed.
- **Backend / DSP / USB / DB feature** (no visible UI): fill the **Backend** block with a concrete example — sample API request/response, CLI/log output, or before→after data (metadata tags, USB tree, DB rows). Show the shape the user will actually see. Leave the **UI** block empty/removed.

### UI — mockup file
- `docs/research/mockups/<slug>.html` — <one-line layout + key-interaction description>

### Backend — concrete example
```text
<sample response / CLI output / before→after — the user-visible shape>
```

---

> ⛔ APPROVAL GATE — user `/approve` (→ `accepted_`) or `/reject "<reason>"` (→ `rework_`). The single sign-off: read `## Approval Summary` + `## Mockup`. After approval, nothing is re-researched.
> ↓ Stage 4 — `inprogress_`. `research-implement` builds each Task Queue item via 5 agents (Approach-Probe, Code, Standard-Review, Security-Review, Test-Coverage-Review, Doc-Sync) on a `routine/*` branch. You test + merge the branch yourself.

## PR Log

Stage 4. One row per task PR. `research-implement` appends; user notes merge after local testing.

| Task | Branch | PR | CI | Std Rev | Sec Rev | Test Cov | Doc Sync | Merged |
|---|---|---|---|---|---|---|---|---|
| … | `routine/<slug>-task-N` | #… | pass/fail | pass/fail | pass/fail | pass/fail | pass/fail | YYYY-MM-DD |

## Implementation Log

Stage 4 Code-Agent + Approach-Probe. Dated entries. What built / surprised / changed-from-plan.

### YYYY-MM-DD — Approach Probe (task N)
- Sketches considered: A (…), B (…), C (…)
- Selected: <letter> — why
- Rejected: … — why

### YYYY-MM-DD — Implementation
- Built: …
- Surprised: …
- Deviation from plan: …

---

## Decision / Outcome

Required by `archived/*`. Stage 4 Doc-Sync-Agent populates the checklist; user signs off after testing the branch locally + merging.

**Result**: implemented | superseded | abandoned
**Why**: …
**Rejected alternatives:**
- …

**Code references**: PR #…, commits …, files …

**Performance achieved** (vs `## Performance Budget`):
- <path> — measured p95 / peak — pass/fail

**Telemetry confirmed live**:
- <marker> visible in <logs / dashboard / health endpoint>

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
- Supersedes: <slug or none>
- Superseded by: <slug or none>
