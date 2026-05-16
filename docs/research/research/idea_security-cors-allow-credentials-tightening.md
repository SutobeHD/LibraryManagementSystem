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

---

## Problem

`app/main.py:222-224` configures CORS with `allow_credentials=True, allow_methods=["*"], allow_headers=["*"]`. Wildcards tolerable today: no cookie-based auth — Bearer-in-`Authorization` header sidesteps CSRF. BUT: SC sentinel at `app/main.py:3036-3043` already sets a cookie via `Set-Cookie`. If anyone later adds session-cookie auth (mobile-pairing Phase-2, browser-only fallback), this CORS config becomes a live CSRF risk. Need: explicit `allow_methods` list (GET/POST/PUT/DELETE/PATCH/OPTIONS), explicit `allow_headers` list incl. `Authorization` + `Content-Type` + `X-Session-Token`, codify "no cookie-auth ever" as repo invariant.

## Goals / Non-goals

**Goals**
- Replace `allow_methods=["*"]` at `app/main.py:230` with explicit list (GET/POST/PUT/PATCH/DELETE/OPTIONS) — drops wildcard surface, fits only verbs actually used.
- Replace `allow_headers=["*"]` at `app/main.py:231` with explicit list (`Content-Type`, `Authorization`, `X-Session-Token`, `X-Requested-With`) — `Authorization` reserved for future bearer scheme, `X-Session-Token` is current one-shot shutdown gate.
- Codify "no session cookies — bearer-in-header is the only authenticated transport" as a permanent rule in `.claude/rules/coding-rules.md` (Backend section). Future cookie-auth PRs auto-rejected.
- Keep behaviour byte-identical for Tauri + Vite-dev today (verb/header enumeration in Findings confirms zero-regression set).

**Non-goals**
- Do NOT shrink `allow_origins` list at `app/main.py:219-228` — Tauri (`tauri://localhost`, `https://tauri.localhost`) and dev (`localhost:1420`, `localhost:5173`, `127.0.0.1` variants, `localhost:8000`) all need to stay.
- Do NOT remove the SC sentinel cookie at `app/main.py:3087-3094` — orthogonal concern. The cookie carries `"os_keyring_active"` not the real token (EC13); it's a UI-state flag, not an auth credential. Replacing it with localStorage is Option B's scope, not this doc's.
- Do NOT add CSRF tokens / SameSite=Strict tightening / Origin allowlist middleware — out of scope; if Option C ("no cookie-auth ever") holds, CSRF is structurally impossible.

## Constraints

External facts bounding solution (rate limits, data shape, perf budget, legal, capacity). Cite source.

- `allow_origins` explicit list at `app/main.py:219-228` — keep verbatim. 4 dev origins (`localhost`/`127.0.0.1` × `1420`/`5173`), 2 self-origins (`localhost:8000`/`127.0.0.1:8000`), 2 Tauri schemes (`tauri://localhost`, `https://tauri.localhost`).
- `allow_credentials=True` at `app/main.py:229` — needed today for the SC sentinel cookie roundtrip (`response.set_cookie(key="sc_token", …)` at `app/main.py:3087`) AND for `axios.create({withCredentials: true})` at `frontend/src/api/api.js:17` to actually send/receive that cookie. Removing it breaks the frontend `sc:auth-expired` detection flow.
- `allow_methods=["*"]` at `app/main.py:230` — minimum useful explicit set covering actual usage: `GET`, `POST`, `PUT`, `PATCH`, `DELETE`, `OPTIONS`. (`OPTIONS` mandatory for preflight; `HEAD` not used.)
- `allow_headers=["*"]` at `app/main.py:231` — minimum useful explicit set: `Content-Type` (axios JSON default), `Authorization` (reserved for future bearer scheme), `X-Session-Token` (current shutdown gate at `frontend/src/api/api.js:87`, may stay one release for legacy), `X-Requested-With` (axios-classic XHR marker, harmless).
- CORS spec forbids `allow_credentials=True` combined with `allow_origins=["*"]`, but does NOT forbid `allow_credentials=True` with explicit origin list — current config is compliant, tightening preserves compliance.
- Tightening to explicit lists MUST NOT break Tauri (`tauri://localhost` already in allowlist) or browser-dev (Vite proxy at port 5173 → 8000) today — verified by frontend verb/header enumeration in Findings below.

## Open Questions

Numbered. Each resolvable (yes/no or X vs Y), not philosophy.

1. Drop `allow_credentials=True` entirely if all auth is bearer-only (no cookie ever needed)? — Depends on Q2. If sentinel cookie becomes localStorage, `withCredentials=true` in axios + `allow_credentials=True` in CORS both become dead-weight and remove a future-CSRF leak vector.
2. Cookie `sc_token` at `app/main.py:3087-3094` is sentinel-only (value `"os_keyring_active"`, no auth content) — does it actually need `Set-Cookie` + `credentials=True`? Could be a `localStorage` flag set by the auth-token response body instead. Tradeoff: localStorage is JS-readable (XSS-exposed) but sentinel has no secret value; HttpOnly cookie protects against XSS but locks us into `allow_credentials=True`.
3. Include `Accept` / `Origin` / `Cookie` in explicit `allow_headers` list, or rely on FastAPI/Starlette + browser defaults? CORS spec lists `Accept`, `Accept-Language`, `Content-Language`, `Content-Type` as CORS-safelisted request headers (always allowed). `Origin` is set by browser, not subject to allowlist. `Cookie` is governed by `allow_credentials`, not `allow_headers`. Likely no — keep list minimal.
4. Should `X-Session-Token` get a deprecation note now (planned removal next release) or is it permanent? `app/main.py` system-shutdown endpoints still gate on it; until those move to bearer, keep it in the allowlist without deprecation.
5. Should `OPTIONS` preflight responses themselves be cached (`Access-Control-Max-Age`)? Starlette default is no header (= browser default ~5s). Setting to 600s would cut preflight noise in dev. Cosmetic, not security.

## Findings / Investigation

Dated subsections, append-only. ≤80 words each. Never edit past entries — supersede.

### 2026-05-15 — initial scope
- Verb enumeration via grep `api\.(get|post|put|patch|delete|head|options)\(` across `frontend/src/`: 164 total occurrences in 41 files. Used: GET (majority), POST (majority), PATCH (5: `BatchEditBar`, `TrackTable` ×3, batch edits), PUT (1: `SoundCloudSyncView` settings), DELETE (registry deletes). NOT used: HEAD, OPTIONS (preflight only — browser-emitted, not app-emitted). Minimum methods list: `GET, POST, PUT, PATCH, DELETE, OPTIONS`.
- Header enumeration via grep `Content-Type|X-Requested-With|X-Session-Token` and `headers:\s*\{` across `frontend/src/`: only `X-Session-Token` explicitly set (interceptor at `frontend/src/api/api.js:87`). No `Authorization` header in current code (SC auth-token posted in JSON body to `/api/soundcloud/auth-token`). `Content-Type: application/json` is axios default. No `Authorization` Bearer usage today.
- `withCredentials=true` at `frontend/src/api/api.js:17` is solely for the SC sentinel cookie. Comment: `"Send HttpOnly cookies (sc_token sentinel)"`. The only `Set-Cookie` in `app/main.py` is at `:3087-3094` (`key="sc_token", value="os_keyring_active"|"", httponly=True, samesite="lax"`). Cookie holds NO secret — only "auth-present" flag.
- `allow_credentials=True` interaction with bearer-only design: if everything authenticated is bearer-in-header (current state — `X-Session-Token` + future `Authorization`), `credentials=True` is dead-weight for auth AND a permanent CSRF leak vector for any future cookie-set endpoint. Today's only Set-Cookie is non-auth (sentinel), so the leak vector is theoretical not actual.
- Proposed permanent rule for `.claude/rules/coding-rules.md` (Backend concurrency / Secrets & paths section): "Do not introduce session cookies. Bearer-in-header (`X-Session-Token`, future `Authorization: Bearer …`) is the only authenticated transport. UI-state flags (e.g. SC sentinel) may use cookies OR localStorage but MUST carry no secret value. Adding a new `response.set_cookie(...)` that holds an auth secret is a hard veto."
- Tightening blast-radius: zero. Explicit list `[GET,POST,PUT,PATCH,DELETE,OPTIONS]` is a superset of actually-used verbs; explicit list `[Content-Type,Authorization,X-Session-Token,X-Requested-With]` is a superset of currently-sent custom headers. No preflight or actual request will be newly rejected.

## Options Considered

Required by `evaluated_`. Per option: sketch ≤3 bullets, pros, cons, S/M/L/XL, risk.

### Option A — Minimal tightening (explicit methods + headers, keep allow_credentials)
- Sketch:
  - `app/main.py:230` → `allow_methods=["GET","POST","PUT","PATCH","DELETE","OPTIONS"]`.
  - `app/main.py:231` → `allow_headers=["Content-Type","Authorization","X-Session-Token","X-Requested-With"]`.
  - Keep `allow_credentials=True` and `allow_origins` list unchanged. Add explanatory comment block referencing this doc.
- Pros: Zero behaviour change for Tauri + dev. Drops wildcard attack surface (any future header injection or rare-verb abuse is structurally blocked). Auditable: explicit list reviewable in PR.
- Cons: Cosmetic-only security improvement while `allow_credentials=True` stays. Doesn't address the underlying "cookies + CORS credentials" risk.
- Effort: S (one-file edit, no test changes — `tests/test_api_routes_smoke.py` should stay green).
- Risk: Very low. If frontend ever adds a new custom header (e.g. `X-Trace-Id`), preflight fails until allowlist updated — caught immediately in dev console.

### Option B — Drop allow_credentials + replace SC sentinel cookie with localStorage flag
- Sketch:
  - Backend: replace `response.set_cookie("sc_token", "os_keyring_active", …)` at `app/main.py:3087-3094` with returning `{"status":"success","auth_present":true}` in the response body. Same for the logout path.
  - Frontend: in `setSoundcloudAuthToken` caller, write `localStorage.setItem("sc_auth_present","1")` on success / `removeItem` on logout. Replace any `document.cookie` reads (none today — sentinel is HttpOnly, only backend reads it; frontend uses 401-driven `sc:auth-expired` event) with localStorage reads.
  - CORS: `allow_credentials=False`. axios: `withCredentials: false`.
- Pros: Clean separation — auth is 100% bearer-in-header. Removes the structural CSRF surface entirely. Frontend can run from any origin (e.g. future mobile-pairing flow) without cookie semantics.
- Cons: Sentinel becomes XSS-readable (localStorage). Today's sentinel carries no secret (`"os_keyring_active"` is public info), so XSS-readability is acceptable, but the invariant "no secret in localStorage" must be added alongside. Requires coordinated backend+frontend change; needs `e2e-tester` run.
- Effort: M (backend ~10 LoC, frontend ~5 LoC + caller wiring, plus axios config flip).
- Risk: Low-medium. Auth-expired detection (401-driven) doesn't depend on the cookie; localStorage flag is purely cosmetic UI state. Risk is missing a hidden cookie-read site (audit needed).

### Option C — Status quo + permanent rule + future-cookie veto
- Sketch:
  - Don't tighten CORS now (keep wildcards).
  - Add a rule line in `.claude/rules/coding-rules.md` (Backend section): "Do not introduce session cookies; bearer-in-header is the only authenticated transport. Any new `response.set_cookie(...)` carrying an auth secret is a hard veto."
  - Document the SC sentinel as the only exception, with the rationale "value is public, not a secret".
- Pros: Zero code change. Captures the load-bearing invariant where future contributors (incl. agents) will see it. Cheapest by far.
- Cons: Doesn't remove the current wildcard surface. Relies on humans (and agents) reading the rule. Doesn't fix Q1/Q2.
- Effort: XS (one-paragraph rules edit).
- Risk: None to existing system. Risk of inaction = wildcard stays + relies on rule-compliance for safety.

## Recommendation

Required by `evaluated_`. ≤80 words. Which option + what blocks commit.

Do **Option A immediately** (cheap, safe, zero regression) AND **Option C in parallel** (the permanent veto rule belongs in `coding-rules.md` regardless — it's the long-term guard that makes the wildcard surface in A's residual `allow_credentials=True` structurally harmless). Spin **Option B as a separate research topic** (`idea_security-drop-cors-credentials-sc-sentinel-localstorage`) — it's a coordinated backend+frontend change that needs its own scope + `e2e-tester` plan, not a hidden subtask of this doc.

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
