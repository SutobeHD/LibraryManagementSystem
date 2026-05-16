---
slug: security-rate-limit-design
title: Rate-limit strategy for FastAPI sidecar (Phase 2 carve-out)
owner: tb
created: 2026-05-15
last_updated: 2026-05-15
tags: [security, follow-up, auth-audit-adjacent]
related: [security-api-auth-hardening]
---

# Rate-limit strategy for FastAPI sidecar (Phase 2 carve-out)

> **Caveman style.** Fragments, bullets. Drop articles/filler/hedges. No prose paragraphs. Respect per-section caps below.
> State = folder + filename prefix (not frontmatter). Lifecycle = audit trail. See `../README.md`.

## Lifecycle

- 2026-05-15 — `research/idea_` — scaffolded from auth-audit adjacent findings
- 2026-05-15 — `research/idea_` — section fill from thin scaffold
- 2026-05-15 — research/idea_ — rework pass (quality-bar review pre-exploring_)
- 2026-05-15 — research/exploring_ — promoted; quality-bar met (route inventory verified, 50 LOC defended via _format_tokens precedent, slowapi-vs-custom differentiated)

---

## Problem

No rate limiting today. Phase-1 auth draftplan explicitly defers slowapi to Phase 2. Design space to evaluate: slowapi (in-process, simple, fine for single-instance) vs fastapi-limiter (Redis-backed, overkill for sidecar) vs custom token-bucket. Attribution: per-IP vs per-session-token, both under reverse-proxy / Tailscale. Routes to gate first: `/api/system/shutdown`, `/api/system/restart`, `/api/soundcloud/auth-token`, future `/api/pairing/*` (Phase-2 mobile), heartbeat (if LAN-exposed). Limits per endpoint (e.g. 5/min for auth, 30/min for heartbeat). 429 + `Retry-After`. Loopback + paired-mobile whitelist to avoid self-lockout.

## Goals / Non-goals

**Goals**
- Cap-per-token AND cap-per-IP for unauth-able endpoints (heartbeat, pairing, healthcheck)
- Cap-per-token (Bearer) for authenticated mutation routes; cap-per-IP for the rest
- Whitelist loopback + paired-mobile from caps OR apply markedly higher caps
- Standardised 429 response: `Retry-After` header + JSON body `{ "error": "rate_limited", "retry_after_s": N }`
- Per-route burst-allowance config table (steady-rate + burst-cap) co-located with route decorators

**Non-goals**
- Not a DDoS mitigation — volumetric / SYN-flood / amplification is the network/firewall layer's job (Tailscale, Cloudflare, ISP)
- Not per-user accounting / billing / quota reporting — single-human product
- Not cross-process rate-limit state — single-instance FastAPI sidecar, no Redis, no multi-worker
- Not a WAF — no payload inspection, no signature matching

## Constraints

External facts bounding solution (rate limits, data shape, perf budget, legal, capacity). Cite source.

- **FastAPI / Starlette has no built-in rate-limit.** Middleware or decorator-based add-on required.
- **slowapi** (https://slowapi.readthedocs.io) — most common option; in-memory backend works for single-instance app; Redis optional; decorator-based; battle-tested.
- **fastapi-limiter** — requires Redis; heavy dep for a desktop sidecar that ships as a bundled Python process. Out of scope.
- **Custom token-bucket** — ~50 LOC for a thread-safe `dict[key, bucket]` + decorator; aligns with project's no-extra-deps tendency (Phase-1 auth-hardening also opted out of new deps).
- **Reverse-proxy header trust** — *speculative for v1*: today the sidecar is loopback-only (`app/main.py:4063` → `uvicorn.run(app, host="127.0.0.1", port=8000)`), so `X-Forwarded-For` is irrelevant. Constraint only activates if Phase-2 mobile-companion deployment ships behind Tailscale / Cloudflare Tunnel / nginx (OQ 1 in `draftplan_security-api-auth-hardening.md` — still un-answered). For v1 design: parser written but `TRUST_PROXY_HEADERS=0` default; flag flips in Phase-2 ship.
- **Phase-1 auth doesn't ship LAN bind by default** (sidecar binds `127.0.0.1:8000` per `app/main.py:4063`). Rate-limit becomes *critical* only in Phase-2 mobile-companion (paired-device + `0.0.0.0` bind); for Phase-1 standalone, rate-limit is defense-in-depth against a same-host malicious process / runaway frontend bug (e.g. retry-storm on auth failure).
- **Memory budget** — desktop sidecar; in-memory bucket store is fine (entries TTL'd; expect < 10k unique keys per session; loopback-only Phase-1 reduces to ~3 keys: `127.0.0.1`, `::1`, session-token).
- **Single-instance assumption** — no horizontal scale; no shared state needed across processes. `ProcessPoolExecutor(max_workers=1)` in `app/anlz_safe.py` is for rbox-quarantine, not request handling — main FastAPI process is single, all rate-limit state can live in `app/main.py` process memory.
- **Middleware stack compatibility** (`app/main.py:217-232`) — CORS middleware registered first; exception handlers at 238 + 261; static mounts at 270 + 275. A rate-limit middleware/exception-handler inserts cleanly between CORS and mounts; slowapi's `Limiter` + `SlowAPIMiddleware` follows the same Starlette-middleware pattern as CORSMiddleware. **No conflict expected.** Static mounts (`/exports`, `/api/artwork`) bypass any decorator-based limiter — covered only by middleware variant.

## Open Questions

Numbered. Each resolvable (yes/no or X vs Y), not philosophy.

1. In-memory custom token-bucket (Option B) vs slowapi pinned dep (Option A)? → resolvable by `evaluated_` once OQ 2/3/5 are answered.
2. Attribution: per-IP only, per-token only, or both? → preferred: **both** (per-IP for unauth routes — heartbeat, healthcheck, future pairing-init; per-token for auth routes — everything behind `require_session`). Resolvable yes/no on the both-combo.
3. Burst-allowance numbers — derive from concrete workload, not from gut feel:
   - **High-priority gated routes** (auth-sensitive or destructive): `5/min` steady, `10/min` burst. Defensible because (a) `shutdown`/`restart` are once-per-session human actions, (b) `/api/soundcloud/auth-token` is a credential-overwrite a human triggers ~once per OAuth flow, (c) future `/api/pairing/*` brute-force budget at 5/min still allows >5 min wall-time to enumerate even a 4-digit pairing code.
   - **Medium-priority** (heartbeat-if-LAN, healthcheck): `60/min` steady (1/sec — matches the frontend's heartbeat poll interval `frontend/src/main.jsx` window).
   - **Default for everything-else gated**: `120/min` steady, `300/min` burst (covers UI batch-rating, mass-tag-edit).
4. Whitelist behavior for loopback (`127.0.0.1`, `::1`): **exempt entirely** (skip limiter). Justification: Phase-1 deployment IS loopback-only; making it pay the lookup cost is pointless and makes test setup harder. Resolvable yes/no.
5. 429 response: `Retry-After` only (Phase-1) OR add `X-RateLimit-Limit` / `X-RateLimit-Remaining` / `X-RateLimit-Reset` headers? Preferred: `Retry-After` only for v1 (matches what the frontend toast pipeline can render today); add the X-RateLimit-* triple in Phase-2 once a dedicated rate-limit UI surface exists. Resolvable yes/no.
6. `X-Forwarded-For` trust: postponed to Phase-2 (Phase-1 is loopback). Build the key-func with a `trust_proxy_headers: bool = False` constructor arg so the toggle is a one-line config change later. Resolvable yes/no.
7. Paired-mobile attribution (Phase-2 dependency): treat as per-token via Bearer-bucket (cleaner: pairing revokes a token → its bucket is GC'd). Whitelisting paired-IPs is brittle (mobile IP changes with Wi-Fi roam). Resolvable A vs B.
8. Bucket persistence: in-memory only (reset on sidecar restart). Persisting to `session_state.db` would survive `/api/system/restart` but adds a write-on-every-request — not worth it for a single-user product. Resolvable yes/no.

## Findings / Investigation

Dated subsections, append-only. ≤80 words each. Never edit past entries — supersede.

### 2026-05-15 — initial scope
- Routes most needing rate-limit: pairing endpoints (Phase-2 brute-force token guess), `/api/system/shutdown` + `/api/system/restart` (DoS / restart-spam), `/api/soundcloud/auth-token` (token-overwrite spam), `/api/system/heartbeat` (if LAN-exposed).
- Token-bucket vs sliding-window trade-off: token-bucket simpler (one float + one timestamp per key), allows bursts naturally; sliding-window more fair but needs ring buffer.
- slowapi minimum-viable wire: 3 lines for `Limiter` init, 1 `@limiter.limit("5/minute")` decorator per route.
- Custom impl: ~50 LOC for thread-safe `dict[key, (tokens, last_refill)]` + `@rate_limit(rate, burst)` decorator + `RLock`.

### 2026-05-15 — concrete route inventory (verified)
- **High-priority bucket (gate-day-one)** — `5/min` steady, `10/min` burst:
  - `POST /api/system/shutdown` — `app/main.py:2071`
  - `POST /api/system/restart` — `app/main.py:2080`
  - `POST /api/soundcloud/auth-token` — `app/main.py:3048` (keyring credential overwrite)
  - `POST /api/pairing/*` — **does not exist yet** (`grep '/api/pair' app/main.py` → 0 hits). Reserved for Phase-2 mobile pairing; gate at route-add time.
- **Medium-priority bucket** — `60/min` steady, `120/min` burst:
  - `POST /api/system/heartbeat` — `app/main.py:937` (only relevant if LAN-exposed; Phase-1 loopback-only makes it moot — apply when `0.0.0.0` bind ships in Phase-2).
- **Low-priority bucket** (everything else gated by `require_session`) — default `120/min` steady, `300/min` burst. Covers ~146 routes per `docs/backend-index.md`. Most are POST mutations the user triggers via UI clicks; default ceiling handles batch operations (mass-rating, mass-tag).
- **Pattern precedent in repo**: `app/main.py:2391-2493` — `_format_tokens` is a TTL'd `dict[str, dict]` guarded by `threading.Lock` with `_purge_expired_tokens()` lazy-evict-on-access. Same exact concurrency shape needed for the token-bucket (TTL'd map + RLock + lazy purge). Custom Option B literally extends this proven pattern; ~50 LOC defensible because: `class TokenBucket(steady, burst)` w/ `take() -> bool` + `refill_to_now()` = ~25 LOC; `dict[str, TokenBucket]` + `RLock` + `_purge_stale(ttl=600)` = ~10 LOC; `@rate_limit(...)` decorator wrapper using `Request` injection = ~15 LOC. Total ~50 LOC + ~80 LOC tests.
- **Middleware insertion site**: `app/main.py:217` (after `CORSMiddleware`, before exception handlers at 238/261, before mounts at 270/275). Slowapi pattern: `app.state.limiter = limiter; app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler); app.add_middleware(SlowAPIMiddleware)`. Cleanly slots into existing stack.
- **No `@app.websocket` routes today** — WebSocket rate-limit is N/A for v1.

## Options Considered

Required by `evaluated_`. Per option: sketch ≤3 bullets, pros, cons, S/M/L/XL, risk.

### Option A — slowapi (pinned dep)
- Sketch:
  - `pip install slowapi==X.Y.Z`, pin in `requirements.txt`
  - `limiter = Limiter(key_func=get_remote_address)` in `app/main.py`; `app.state.limiter = limiter`; register exception handler
  - `@limiter.limit("5/minute")` per gated route; key-func variant per token vs IP
- Pros: battle-tested, decorator ergonomic, handles `Retry-After` + headers out of the box, Starlette-native middleware
- Cons: extra dep (Schicht-A pinning surface grows), one more thing to CVE-watch, key-func customisation for token+IP combo is non-trivial
- Effort: S
- Risk: low (stable library, in-memory backend is the default)

### Option B — Custom in-process token-bucket
- Sketch (concrete API surface, ~50 LOC + ~80 LOC tests):
  - `app/rate_limit.py`:
    - `class TokenBucket:` — `__init__(self, steady_per_min: float, burst: int)`; `take(self) -> bool` (returns True if a token was consumed, False if rate-limited); `retry_after_s(self) -> float`; internal `_refill_to(now)` with monotonic time.
    - `class BucketStore:` — `dict[str, TokenBucket]` + `threading.RLock` + `_last_purge: float`; `take(self, key: str, *, steady: float, burst: int) -> tuple[bool, float]` (bool=allowed, float=retry_after); `reset(self, key: str) -> None`; lazy `_purge_stale(ttl=600s)` on every Nth call.
    - `_store: BucketStore = BucketStore()` module singleton.
    - `def make_key(request: Request, *, mode: str) -> str` — `mode in {"ip", "token", "both"}`; reads `request.client.host` and `Authorization: Bearer …` header; concatenates with `|` for `both`. Loopback short-circuit returns sentinel `"__whitelist__"`.
    - `@rate_limit(steady=5.0, burst=10, key_mode="both")` decorator using FastAPI's `Request` injection; raises `HTTPException(429, headers={"Retry-After": str(int(retry_after_s))}, detail={"error": "rate_limited", "retry_after_s": int(retry_after_s)})`.
  - Whitelist set (`{"127.0.0.1", "::1"}` + Phase-2 paired-device IPs) — checked in `make_key`, returns sentinel that `BucketStore.take` always allows.
  - Pattern alignment: `app/main.py:2391-2493` `_format_tokens` already does TTL'd-dict + `threading.Lock` + lazy-purge — same shape, well-understood in this codebase.
- Pros: no new dep (matches Phase-1 lean stance per `draftplan_security-api-auth-hardening.md` Decisions table); full control over key-func / whitelist / response shape; easy to wire `X-RateLimit-*` headers (Phase-2) without forking slowapi; concurrency model identical to `_format_tokens` (already battle-tested in this app).
- Cons: maintenance burden; less battle-tested than slowapi; must hand-roll `Retry-After` math and bucket-refill correctness; test coverage entirely on us.
- Effort: S (50 LOC impl + 80 LOC tests).
- Risk: medium — concurrency bugs in the refill math are subtle; mitigated by `tests/test_rate_limit.py` (cases: take-until-empty, refill-after-wait, burst-allows-then-throttles, whitelist-bypass, concurrent-take from 4 threads, TTL purge).

### Option C — Reverse-proxy layer (nginx / Tailscale / Cloudflare)
- Sketch:
  - Document a recommended nginx `limit_req_zone` config + Tailscale ACL pattern
  - Sidecar stays bind-loopback; reverse proxy handles all rate-limit
  - No Python code change
- Pros: zero app-layer code, ops-grade tooling, offloads CVE surface
- Cons: doesn't help the standalone / Tauri-loopback case (no proxy present); user must self-configure; useless on first run
- Effort: XS (docs only)
- Risk: high — relies on user to deploy correctly; default deployment ships with no protection

## Recommendation

Required by `evaluated_`. ≤80 words. Which option + what blocks commit.

**Option B (custom token-bucket) for v1.** Matches Phase-1 no-new-dep stance per `draftplan_security-api-auth-hardening.md` Decisions; ~50 LOC mirrors existing `_format_tokens` pattern at `app/main.py:2391-2493`; auditable; full control over `Retry-After` + future `X-RateLimit-*` shape. Fall back to **Option A (slowapi)** only if behavior gaps emerge (sliding-window fairness, multi-key composite buckets we can't get right).

**Concrete first step (gate condition for `exploring_` → `evaluated_`):**
1. Land Phase-1 auth-hardening first (rate-limit is Phase-2 per the auth-hardening Decisions table — touching the same routes; sequence matters to avoid conflict at the `Depends(...)` decorator stack).
2. Promote this doc to `exploring_` once Phase-1 auth ships in `archived/implemented_security-api-auth-hardening_*`.
3. First three routes to gate (smallest blast radius, biggest abuse-payoff): `POST /api/system/shutdown` (`:2071`), `POST /api/system/restart` (`:2080`), `POST /api/soundcloud/auth-token` (`:3048`). Settings: `steady=5/min, burst=10, key_mode="both"`, loopback-whitelist on.
4. Open Questions blocking `evaluated_`: OQ 2 (attribution: confirm "both"), OQ 4 (whitelist: confirm "loopback exempt entirely"), OQ 5 (headers: confirm "Retry-After only for v1"). All three are user-decisions, not research questions.

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
