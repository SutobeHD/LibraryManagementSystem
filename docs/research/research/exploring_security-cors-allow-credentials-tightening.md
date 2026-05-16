---
slug: security-cors-allow-credentials-tightening
title: CORS allow_credentials=True + allow_methods/headers=["*"] is overly permissive
owner: tb
created: 2026-05-15
last_updated: 2026-05-15
tags: [security, follow-up, auth-audit-adjacent]
related: [security-api-auth-hardening]
---

# CORS allow_credentials=True + allow_methods/headers=["*"] is overly permissive

> **Caveman style.** Fragments, bullets. Drop articles/filler/hedges. No prose paragraphs. Respect per-section caps below.
> State = folder + filename prefix (not frontmatter). Lifecycle = audit trail. See `../README.md`.

## Lifecycle

- 2026-05-15 — `research/idea_` — scaffolded from auth-audit adjacent findings
- 2026-05-15 — `research/idea_` — section fill from thin scaffold
- 2026-05-15 — research/idea_ — rework pass (quality-bar review pre-exploring_)
- 2026-05-15 — research/exploring_ — promoted; quality-bar met (frontend axios audit enumerated 164 calls / 41 files; sentinel cookie confirmed dead-code 0 reads)

---

## Problem

`app/main.py:217-232` configures CORS with `allow_credentials=True, allow_methods=["*"], allow_headers=["*"]` (wildcards on lines 230-231). Wildcards tolerable today: no cookie-based auth — bearer-in-`X-Session-Token` header sidesteps CSRF. BUT: SC sentinel at `app/main.py:3087-3094` already sets a cookie via `Set-Cookie`. If anyone later adds session-cookie auth (mobile-pairing Phase-2, browser-only fallback), this CORS config becomes a live CSRF risk. Need: explicit `allow_methods` list (GET/POST/PUT/PATCH/DELETE/OPTIONS), explicit `allow_headers` list incl. `Content-Type` + `X-Session-Token` (+ `Authorization` reserved), codify "no cookie-auth ever" as repo invariant.

## Goals / Non-goals

**Goals**
- Replace `allow_methods=["*"]` at `app/main.py:230` with explicit list (GET/POST/PUT/PATCH/DELETE/OPTIONS) — drops wildcard surface, fits only verbs actually used (verified: GET=69, POST=87, PUT=1, PATCH=4, DELETE=3; HEAD/OPTIONS not app-emitted). **Testable**: `grep -c "api\.(get\|post\|put\|patch\|delete)" frontend/src/` matches each verb in the explicit list.
- Replace `allow_headers=["*"]` at `app/main.py:231` with explicit list (`Content-Type`, `X-Session-Token`, `Authorization`) — `Authorization` reserved for future bearer scheme, `X-Session-Token` is the only custom header currently set (api.js:87). **Testable**: a request with an un-listed custom header from the frontend's actual call sites must 200; one with a fabricated `X-Foo: bar` may be optionally checked to fail preflight.
- Codify "no session cookies — bearer-in-header is the only authenticated transport" as a permanent rule in `.claude/rules/coding-rules.md` (Backend section). Future cookie-auth PRs auto-rejected. **Testable**: rule line exists; PR-check grep would block new `response.set_cookie(` introducing an auth secret.
- Keep behaviour byte-identical for Tauri + Vite-dev today (verb/header enumeration in Findings confirms zero-regression set). **Testable**: `tests/test_api_routes_smoke.py` green pre- and post-change; manual e2e on SoundCloudView login flow + system-shutdown flow.

**Non-goals**
- Do NOT shrink `allow_origins` list at `app/main.py:219-228` — Tauri (`tauri://localhost`, `https://tauri.localhost`) and dev (`localhost:1420`, `localhost:5173`, `127.0.0.1` variants, `localhost:8000`) all need to stay.
- Do NOT remove the SC sentinel cookie at `app/main.py:3087-3094` in Option A — orthogonal concern. The cookie carries `"os_keyring_active"` not the real token (EC13); it's a UI-state flag, not an auth credential. Removing it is Option B's scope.
- Do NOT add CSRF tokens / SameSite=Strict tightening / Origin allowlist middleware — out of scope; if Option C ("no cookie-auth ever") holds, CSRF is structurally impossible.

## Constraints

External facts bounding solution (rate limits, data shape, perf budget, legal, capacity). Cite source.

- `allow_origins` explicit list at `app/main.py:219-228` — keep verbatim. 4 dev origins (`localhost`/`127.0.0.1` × `1420`/`5173`), 2 self-origins (`localhost:8000`/`127.0.0.1:8000`), 2 Tauri schemes (`tauri://localhost`, `https://tauri.localhost`).
- `allow_credentials=True` at `app/main.py:229` — needed today ONLY for the SC sentinel cookie roundtrip (`response.set_cookie(key="sc_token", …)` at `app/main.py:3087`) AND for `axios.create({withCredentials: true})` at `frontend/src/api/api.js:17`. **Resolved in rework (Q6)**: neither frontend nor backend ever reads the cookie — it's write-only-then-discarded. Removing it does NOT break `sc:auth-expired` detection (100% 401-driven, see `frontend/src/api/api.js:115-136`, `frontend/src/components/SoundCloudView.jsx:52-62`). Stale docstring at `app/soundcloud_api.py:3` falsely claims backend reads the cookie — actual reads are from `keyring.get_password(...)`. **Option A keeps `credentials=True` for safety; Option B drops it.**
- `allow_methods=["*"]` at `app/main.py:230` — minimum useful explicit set covering actual usage: `GET, POST, PUT, PATCH, DELETE, OPTIONS`. **Derived from enumeration** in Findings (`api.<verb>(` grep of `frontend/src/`): 69 GET, 87 POST, 1 PUT (`SoundCloudSyncView.jsx:594`), 4 PATCH (`BatchEditBar.jsx:30`, `TrackTable.jsx:270,293,486`), 3 DELETE (`PlaylistBrowser.jsx:390`, `settings/SettingsUsb.jsx:72`, `UsbView.jsx:157`). `OPTIONS` mandatory for preflight (browser-emitted). `HEAD` not used.
- `allow_headers=["*"]` at `app/main.py:231` — minimum useful explicit set: `Content-Type` (axios JSON default; CORS-safelisted but explicit listing avoids preflight ambiguity for non-safelisted JSON), `X-Session-Token` (the ONLY custom header set anywhere — `frontend/src/api/api.js:87`), `Authorization` (reserved for future bearer scheme, no current usage). **Derived from enumeration**: zero `headers: {…}` blocks in `frontend/src/`; only `config.headers[…] =` site is `api.js:87`. `X-Requested-With` (proposed in earlier draft) is NOT set anywhere in code — drop unless we add it explicitly. (TODO: confirm `Accept` not needed beyond CORS-safelisted default.)
- CORS spec forbids `allow_credentials=True` combined with `allow_origins=["*"]`, but does NOT forbid `allow_credentials=True` with explicit origin list — current config is compliant, tightening preserves compliance.
- Tightening to explicit lists MUST NOT break Tauri (`tauri://localhost` already in allowlist) or browser-dev (Vite proxy at port 5173 → 8000) today — verified by frontend verb/header enumeration above.

## Open Questions

Numbered. Each resolvable (yes/no or X vs Y), not philosophy.

1. Drop `allow_credentials=True` entirely if all auth is bearer-only? — **Resolved: YES, in Option B.** Frontend has zero `document.cookie` reads (verified). Backend has zero `request.cookies.get("sc_token")` reads (verified — see Q6). `withCredentials=true` only round-trips a value no one consumes.
2. Cookie `sc_token` at `app/main.py:3087-3094` — does it need `Set-Cookie` at all? — **Resolved: NO.** Frontend never reads it (HttpOnly + 0 `document.cookie` sites); backend never reads it (Q6). The sentinel is write-only-then-discarded — pure dead code. Delete in Option B; no localStorage replacement needed.
3. Include `Accept` / `Origin` / `Cookie` in explicit `allow_headers`? — **Resolved: NO.** `Accept`/`Accept-Language`/`Content-Language`/`Content-Type` are CORS-safelisted (always allowed without explicit listing); `Origin` is browser-set; `Cookie` is governed by `allow_credentials`. Keep list minimal: `Content-Type, X-Session-Token, Authorization`.
4. Should `X-Session-Token` get a deprecation note now? — **Resolved: NO.** `app/main.py` system-shutdown endpoints still gate on it; until those move to `Authorization: Bearer`, keep allowed without deprecation. Re-evaluate when shutdown flow migrates.
5. Should `OPTIONS` preflight responses be cached (`Access-Control-Max-Age`)? — Starlette default is no header (~5s browser default). Setting `max_age=600` cuts preflight noise. **Resolved: defer.** Cosmetic, orthogonal to security tightening; do as a follow-up if dev complains.
6. **NEW (resolved 2026-05-15)** — Does any backend route read the `sc_token` cookie value? — **NO.** Grep of `app/` for `cookies.get` / `request.cookies` / `Cookie(` / `sc_token` returned: (a) `main.py:67` defines `KEYRING_SC_TOKEN = "sc_token"` — a keyring identifier, unrelated to the HTTP cookie; (b) `main.py:3087` sets the cookie; (c) `soundcloud_api.py:3` docstring claims "Uses the auth_token (stored as HttpOnly cookie sc_token)" but the file actually reads from the OS keyring — **stale comment, separate cleanup ticket**. Zero `request.cookies.get("sc_token")` call sites. Cookie is write-only-then-discarded. **Implication**: Option B is now a ~4-line change: remove `response.set_cookie(...)` at `app/main.py:3087-3094`, remove `withCredentials: true` at `frontend/src/api/api.js:17`, set `allow_credentials=False` at `app/main.py:229`, and fix the stale docstring in `app/soundcloud_api.py:3`.

## Findings / Investigation

Dated subsections, append-only. ≤80 words each. Never edit past entries — supersede.

### 2026-05-15 — initial scope
- Verb enumeration via grep `api\.<verb>\(` across `frontend/src/`: 164 total occurrences in 41 files. Used: GET (majority), POST (majority), PATCH (5: `BatchEditBar`, `TrackTable` ×3, batch edits), PUT (1: `SoundCloudSyncView` settings), DELETE (registry deletes). NOT used: HEAD, OPTIONS (preflight only — browser-emitted, not app-emitted). Minimum methods list: `GET, POST, PUT, PATCH, DELETE, OPTIONS`. *(Superseded by 2026-05-15 — rework verification below: PATCH count is 4, not 5.)*
- Header enumeration via grep `Content-Type|X-Requested-With|X-Session-Token` and `headers:\s*\{` across `frontend/src/`: only `X-Session-Token` explicitly set (interceptor at `frontend/src/api/api.js:87`). No `Authorization` header in current code (SC auth-token posted in JSON body to `/api/soundcloud/auth-token`). `Content-Type: application/json` is axios default. No `Authorization` Bearer usage today.
- `withCredentials=true` at `frontend/src/api/api.js:17` is solely for the SC sentinel cookie. Comment: `"Send HttpOnly cookies (sc_token sentinel)"`. The only `Set-Cookie` in `app/main.py` is at `:3087-3094` (`key="sc_token", value="os_keyring_active"|"", httponly=True, samesite="lax"`). Cookie holds NO secret — only "auth-present" flag.
- `allow_credentials=True` interaction with bearer-only design: if everything authenticated is bearer-in-header (current state — `X-Session-Token` + future `Authorization`), `credentials=True` is dead-weight for auth AND a permanent CSRF leak vector for any future cookie-set endpoint. Today's only Set-Cookie is non-auth (sentinel), so the leak vector is theoretical not actual.
- Proposed permanent rule for `.claude/rules/coding-rules.md` (Backend concurrency / Secrets & paths section): "Do not introduce session cookies. Bearer-in-header (`X-Session-Token`, future `Authorization: Bearer …`) is the only authenticated transport. UI-state flags (e.g. SC sentinel) may use cookies OR localStorage but MUST carry no secret value. Adding a new `response.set_cookie(...)` that holds an auth secret is a hard veto."
- Tightening blast-radius: zero. Explicit list `[GET,POST,PUT,PATCH,DELETE,OPTIONS]` is a superset of actually-used verbs; explicit list `[Content-Type,Authorization,X-Session-Token,X-Requested-With]` is a superset of currently-sent custom headers. No preflight or actual request will be newly rejected.

### 2026-05-15 — rework verification (pre-`exploring_`)
- **Verb counts (re-grepped, file:line dump):** `api.get(`=69 in 33 files; `api.post(`=87 in 30 files; `api.put(`=1 (`SoundCloudSyncView.jsx:594`); `api.patch(`=4 (`BatchEditBar.jsx:30`, `TrackTable.jsx:270,293,486` — **prior "5" was wrong**); `api.delete(`=3 (`PlaylistBrowser.jsx:390`, `settings/SettingsUsb.jsx:72`, `UsbView.jsx:157`); `api.head/options/request` = 0. Sum: 69+87+1+4+3 = 164 ✓ matches doc.
- **Header sites (re-grepped):** `config.headers[…] =` occurs at exactly 1 site — `frontend/src/api/api.js:87` (`X-Session-Token`). Zero `headers: {` blocks anywhere in `frontend/src/`. `X-Requested-With` is NOT set in code — drop from earlier proposal. Final allowlist: `Content-Type, X-Session-Token, Authorization`.
- **Frontend cookie reads:** `grep document.cookie|sc_token|sc_auth_present frontend/src` = ZERO matches outside `api.js:17` (the `withCredentials` comment). Sentinel is HttpOnly → JS-unreadable by design; frontend's auth-expired flow is 401-driven (`api.js:115-136`, `SoundCloudView.jsx:52-62`). Cookie has no consumer on frontend.
- **Backend cookie reads:** `grep cookies.get|request.cookies|Cookie( app/` = ZERO matches reading `sc_token`. Stale docstring at `app/soundcloud_api.py:3` claims "Uses the auth_token (stored as HttpOnly cookie sc_token)" but the file reads from `keyring.get_password(KEYRING_SERVICE, KEYRING_SC_TOKEN)`. Cookie has no consumer on backend either. **Implication: sentinel is dead code; Option B is now load-bearing.**
- **Line-number citations fixed:** prior doc said CORS block `:222-224` / `:219-228` / `:229-231`; actual block is `app/main.py:217-232` (origins list 219-228, `allow_credentials=True` line 229, `allow_methods` line 230, `allow_headers` line 231). SC sentinel was double-cited as `:3036-3043` (wrong — that's DELETE history endpoint) and `:3087-3094` (correct).

## Options Considered

Required by `evaluated_`. Per option: sketch ≤3 bullets, pros, cons, S/M/L/XL, risk.

### Option A — Minimal tightening (explicit methods + headers, keep allow_credentials)
- Sketch:
  - `app/main.py:230` → `allow_methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS"]`.
  - `app/main.py:231` → `allow_headers=["Content-Type","X-Session-Token","Authorization"]` (dropped `X-Requested-With` — not set anywhere).
  - Keep `allow_credentials=True` and `allow_origins` list unchanged. Add explanatory comment block referencing this doc.
- Concrete impl-cost: 2 lines changed in 1 file (`app/main.py:230-231`). No frontend change. No test change. **2 files affected including the explanatory comment.**
- Pros: Zero behaviour change for Tauri + dev. Drops wildcard attack surface (any future header injection or rare-verb abuse is structurally blocked). Auditable: explicit list reviewable in PR.
- Cons: Cosmetic-only security improvement while `allow_credentials=True` stays. Doesn't remove the now-known dead sentinel cookie. Doesn't address the underlying "cookies + CORS credentials" risk.
- Effort: S (one-file edit, no test changes — `tests/test_api_routes_smoke.py` should stay green).
- Risk: Very low. If frontend ever adds a new custom header (e.g. `X-Trace-Id`), preflight fails until allowlist updated — caught immediately in dev console.

### Option B — Drop allow_credentials + remove the dead SC sentinel cookie entirely
- Sketch:
  - Backend: delete `response.set_cookie("sc_token", …)` block at `app/main.py:3087-3094`. Remove the unused `response: Response` parameter from `set_soundcloud_auth_token` (`app/main.py:3049`). Fix stale docstring at `app/soundcloud_api.py:3` ("Uses the auth_token stored as HttpOnly cookie sc_token" — actually reads from keyring).
  - Backend CORS: `app/main.py:229` → `allow_credentials=False`. Also apply Option A's methods+headers tightening.
  - Frontend: `frontend/src/api/api.js:17` → `withCredentials: false`. Remove the misleading comment on the same line.
  - **No `localStorage` write needed** — the earlier draft of this option proposed a localStorage flag, but the post-rework enumeration shows neither frontend nor backend ever reads the sentinel. There is no consumer to replace.
- Concrete impl-cost: ~10 lines deleted across 3 files (`app/main.py`, `frontend/src/api/api.js`, `app/soundcloud_api.py`). 0 lines added (besides Option A's allowlists). **3 files affected.**
- Pros: Clean separation — auth is 100% bearer-in-header. Removes the structural CSRF surface entirely. Removes ~8 lines of dead code (sentinel + comment + `Response` param). Frontend can run from any origin (e.g. future mobile-pairing flow) without cookie semantics. Eliminates a misleading docstring.
- Cons: Need to confirm via `e2e-tester` that no third-party code path (e.g. a future browser extension, telemetry library, dev tool) relied on the cookie. Removes a *theoretical* future hook for "cheap auth-presence check from backend without keyring lookup" — but that hook isn't used today.
- Effort: S+ (was M in earlier draft; reduced now that no localStorage wiring is needed).
- Risk: Low. Auth-expired detection (401-driven) is independent. Main risk is a stealthy import of a route that reads `request.cookies.get("sc_token")` outside `app/` (e.g. test fixtures, plugins) — grep confirms zero matches in `app/` but `tests/` should be scanned in the plan stage.

### Option C — Status quo + permanent rule + future-cookie veto
- Sketch:
  - Don't tighten CORS now (keep wildcards).
  - Add a rule line in `.claude/rules/coding-rules.md` (Backend section): "Do not introduce session cookies; bearer-in-header is the only authenticated transport. Any new `response.set_cookie(...)` carrying an auth secret is a hard veto."
  - Document the SC sentinel as the only exception, with the rationale "value is public, not a secret".
- Concrete impl-cost: ~3 lines added in 1 file (`.claude/rules/coding-rules.md`). **1 file affected.**
- Pros: Zero code change. Captures the load-bearing invariant where future contributors (incl. agents) will see it. Cheapest by far.
- Cons: Doesn't remove the current wildcard surface. Relies on humans (and agents) reading the rule. Doesn't fix Q1/Q2/Q6. Locks in dead code (the sentinel) by giving it a "documented exception" status it doesn't deserve.
- Effort: XS (one-paragraph rules edit).
- Risk: None to existing system. Risk of inaction = wildcard stays + relies on rule-compliance for safety.

## Recommendation

Required by `evaluated_`. ≤80 words. Which option + what blocks commit.

**Do Option A + Option C now, queue Option B as the immediate follow-up.** Concrete next step: land Option A as a 2-line PR (`app/main.py:230-231` explicit lists) + a `coding-rules.md` rule paragraph (Option C). **Gate conditions**: (1) `tests/test_api_routes_smoke.py` green; (2) `e2e-tester` verifies SoundCloud login + system-shutdown flows. After A+C ship, open Option B (dead-sentinel removal — confirmed scope after Q6 resolution, ~10 LoC across 3 files, no `localStorage` needed).

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
