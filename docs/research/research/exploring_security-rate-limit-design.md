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
- 2026-05-15 — research/exploring_ — perfect-quality rework loop (deep self-review pass)

---

## Problem

Zero inbound rate-limit on FastAPI sidecar (verified: `grep -i 'rate.{0,3}limit|throttl|slowapi'` in `app/` returns only `RateLimitError` from outbound SC API helper in `app/soundcloud_api.py:142` — unrelated). Phase-1 auth draftplan defers in-app rate-limit to Phase 2 (`draftplan_security-api-auth-hardening.md:345` Decisions table). Design choice: slowapi (in-process, pinned dep) vs custom token-bucket (~50 LOC, no dep). Attribution: per-IP + per-Bearer. First-gate routes: `POST /api/system/shutdown` (`app/main.py:2071`), `POST /api/system/restart` (`:2080`), `POST /api/soundcloud/auth-token` (`:3048`), Phase-2 `/api/pairing/*` at add-time, heartbeat (`:937`) once LAN-bound. 429 + `Retry-After`. Loopback whitelist (sentinel) prevents self-lockout.

## Goals / Non-goals

**Goals**
- Cap per-IP on unauth routes (no Bearer present → IP-only key).
- Cap per-(IP|Bearer-hash) concat on `require_session` mutation routes (rotation/revoke kills the Bearer-keyed bucket).
- Loopback IPs (`127.0.0.1`, `::1`) short-circuit to sentinel `__whitelist__` (always-allow, no bucket allocated). Paired-mobile (Phase-2) keyed per-Bearer only — mobile IP roams across Wi-Fi.
- 429 response: `Retry-After: N` header + JSON `{"error": "rate_limited", "retry_after_s": N}`.
- Per-route `(steady, burst, key_mode)` triple declared at decorator site — no central config table.

**Non-goals**
- Not DDoS mitigation. Volumetric / SYN-flood / amplification = network layer (Tailscale, Cloudflare, ISP firewall).
- Not per-user quota / billing — single-human product.
- Not cross-process state — single uvicorn worker, no Redis.
- Not a WAF — no payload inspection.
- Not WebSocket rate-limit — no `@app.websocket` routes in `app/` (grep verified).

## Constraints

External facts bounding solution. Cite source.

- **FastAPI / Starlette: no built-in rate-limit.** Middleware or decorator required.
- **slowapi** (https://slowapi.readthedocs.io) — in-memory default backend; Redis optional; decorator-based; Starlette-native middleware.
- **fastapi-limiter** — requires Redis. Out of scope (no Redis in sidecar bundle).
- **Custom token-bucket** — ~50 LOC + 80 LOC tests. Matches Phase-1 no-new-dep stance per `draftplan_security-api-auth-hardening.md:345` Decisions table.
- **Sidecar bind = `127.0.0.1:8000`** (`app/main.py:4063` → `uvicorn.run(app, host="127.0.0.1", port=8000)`). `X-Forwarded-For` parsing not wired for Phase-2; constructor arg `trust_proxy_headers: bool = False` reserved (OQ 6 PARKED — Phase-2 decides on `0.0.0.0` bind, see `draftplan_security-api-auth-hardening.md:67` OQ 1 still open).
- **Phase-1 threat = same-host process / retry-storm bug.** Phase-2 threat = LAN attacker post mobile-companion bind-widening.
- **Memory budget** — Phase-1 loopback-only: zero buckets allocated (all traffic hits whitelist sentinel; sentinel short-circuits without touching `_buckets`). Phase-2 LAN: <10k unique keys/session, TTL'd at 600s, bounded.
- **Single uvicorn worker.** No multi-process, no shared state. `ProcessPoolExecutor(max_workers=1)` in `app/anlz_safe.py` quarantines rbox parsing only — main FastAPI process is single, bucket store lives in module-singleton dict.
- **Middleware stack** (`app/main.py:217` CORS → `:238/261` exception handlers → `:270/275` static mounts). Rate-limit middleware/exception-handler slots between CORS and mounts. Static mounts (`/exports`, `/api/artwork`) bypass decorator variant — covered only via middleware-mode wrap (deferred; first three gated routes are non-static).

## Open Questions

Numbered. Each resolvable (yes/no, X vs Y). RESOLVED = answered. PARKED = deferred to named gate.

1. **RESOLVED — Option B (custom token-bucket).** No new dep; matches Phase-1 stance; ~50 LOC mirrors `_format_tokens` precedent at `app/main.py:2391-2493`. Slowapi fallback only if Option-B hits a wall.
2. **RESOLVED — `key_mode="both"` (IP + Bearer concat).** Unauth routes: IP-only (no Bearer present). Auth routes: `"ip|bearer-hash"`. Logout/rotate revokes Bearer → its bucket key changes → fresh budget for new token.
3. **RESOLVED — three tiers, declared at decorator site.** HIGH (`steady=5/min, burst=10`): shutdown/restart/auth-token/Phase-2 pairing-init. MEDIUM (`steady=60/min, burst=120`): heartbeat-when-LAN, healthcheck. DEFAULT (`steady=120/min, burst=300`): every other `require_session` mutation. Justification: shutdown/restart once per session; auth-token once per OAuth flow; pairing-init at 5/min lets 4-digit code take >2000 min wall-clock; medium = 1/sec heartbeat poll headroom; default covers mass-rating batches (≤300 rows tested in `tests/test_database.py`).
4. **RESOLVED — loopback whitelist via sentinel.** `make_key()` returns `"__whitelist__"` for `127.0.0.1`/`::1`; `BucketStore.take("__whitelist__", …)` short-circuits `return (True, 0.0)` without touching the dict. Zero lookup cost, no test-setup friction.
5. **RESOLVED — `Retry-After` only for v1.** Frontend toast pipeline (`frontend/src/api/api.js` interceptor) already renders `Retry-After`. `X-RateLimit-*` triple deferred until a dedicated rate-limit UI surface ships (Phase-2 candidate).
6. **PARKED — `trust_proxy_headers` flag for Phase-2.** Constructor accepts `trust_proxy_headers: bool = False`; default False (Phase-1 loopback). Phase-2 `0.0.0.0` bind (gated on `draftplan_security-api-auth-hardening.md:67` OQ 1) flips it.
7. **RESOLVED — per-Bearer attribution for paired mobile.** Mobile Wi-Fi roams → IP-whitelist brittle. Pairing revoke kills Bearer → bucket key dies → no orphan budget leak.
8. **RESOLVED — in-memory only.** No `session_state.db` persistence. Write-per-request cost > recovery value for single-user product. Sidecar restart = clean slate (matches `SHUTDOWN_TOKEN` lifecycle at `app/main.py:125`).

## Findings / Investigation

Dated subsections, append-only. ≤80 words each. Never edit past entries — supersede.

### 2026-05-15 — initial scope
- Routes most needing rate-limit: pairing endpoints (Phase-2 brute-force token guess), `/api/system/shutdown` + `/api/system/restart` (DoS / restart-spam), `/api/soundcloud/auth-token` (token-overwrite spam), `/api/system/heartbeat` (if LAN-exposed).
- Token-bucket vs sliding-window trade-off: token-bucket simpler (one float + one timestamp per key), allows bursts naturally; sliding-window more fair but needs ring buffer.
- slowapi minimum-viable wire: 3 lines for `Limiter` init, 1 `@limiter.limit("5/minute")` decorator per route.
- Custom impl: ~50 LOC for thread-safe `dict[key, (tokens, last_refill)]` + `@rate_limit(rate, burst)` decorator + `RLock`.

### 2026-05-15 — concrete route inventory (verified)
- **High-priority bucket (gate-day-one)** — `steady=5/min, burst=10`:
  - `POST /api/system/shutdown` — `app/main.py:2071`
  - `POST /api/system/restart` — `app/main.py:2080`
  - `POST /api/soundcloud/auth-token` — `app/main.py:3048` (keyring credential overwrite)
  - `POST /api/pairing/*` — does not exist (`grep '/api/pair' app/main.py` → 0). Reserved for Phase-2 mobile pairing; gate at route-add time.
- **Medium-priority bucket** — `steady=60/min, burst=120`:
  - `POST /api/system/heartbeat` — `app/main.py:937` (only relevant LAN-exposed; Phase-1 loopback makes it moot — apply when Phase-2 `0.0.0.0` bind ships).
- **Default bucket** (every `require_session` mutation) — `steady=120/min, burst=300`. Covers ~146 routes per `docs/backend-index.md`. Default handles mass-rating / mass-tag batch UI flows.
- **Pattern precedent**: `app/main.py:2391-2493` `_format_tokens` = TTL'd `dict[str, dict]` + `threading.Lock` + lazy `_purge_expired_tokens()`. Identical concurrency shape. Custom Option B literally extends this proven pattern.
- **Middleware insertion site**: `app/main.py:217` (after `CORSMiddleware`, before exception handlers `:238/261`, before mounts `:270/275`).
- **No `@app.websocket` routes** (`grep '@app\.websocket' app/` → 0). WebSocket rate-limit N/A for v1.
- **No existing in-app rate-limit code**. `RateLimitError` in `app/soundcloud_api.py:142` is *outbound* SC API throttle handling, not inbound limiter — unrelated.

### 2026-05-15 — TokenBucket API shape + bucket-key + whitelist (concrete prose)

**`class TokenBucket`** — prose-form signatures (≤25 LOC):
- `__init__(self, steady_per_min: float, burst: int)` — stores `steady_per_sec = steady_per_min / 60.0`, `capacity = burst`, `tokens: float = float(burst)`, `last_refill: float = time.monotonic()`.
- `take(self) -> tuple[bool, float]` — internally calls `_refill_to(time.monotonic())`; if `tokens >= 1.0`: decrement, return `(True, 0.0)`; else compute `retry_after_s = (1.0 - tokens) / steady_per_sec`, return `(False, retry_after_s)`.
- `_refill_to(self, now: float) -> None` — `elapsed = now - last_refill`; `tokens = min(capacity, tokens + elapsed * steady_per_sec)`; `last_refill = now`. Pure-CPU; no lock (caller — `BucketStore` — holds RLock).

**`class BucketStore`** — TTL'd map (~10 LOC):
- `_buckets: dict[str, TokenBucket] = {}`, `_lock: threading.RLock`, `_last_purge: float`.
- `take(self, key: str, *, steady: float, burst: int) -> tuple[bool, float]` — whitelist short-circuit (`if key == "__whitelist__": return (True, 0.0)`); else `with _lock:` get-or-create `_buckets[key]`, call `bucket.take()`. Every Nth call (or `now - _last_purge > 60s`), lazy-evict entries whose `last_refill < now - 600s` and `tokens >= capacity` (fully-refilled = inactive, safe to drop).
- Module singleton `_store: BucketStore`.

**`def make_key(request: Request, *, mode: Literal["ip","bearer","both"]) -> str`** (bucket-key derivation, ~15 LOC):
- `client_ip = request.client.host if request.client else "unknown"`.
- **Whitelist sentinel**: `if client_ip in {"127.0.0.1", "::1"}: return "__whitelist__"`. (Phase-2: replace with `_WHITELIST_IPS` frozenset incl. paired-device IPs from `paired_devices` table — TODO.)
- For `mode="ip"`: return `f"ip:{client_ip}"`.
- For `mode="bearer"` and `mode="both"`: parse `Authorization` header; if `header.startswith("Bearer ")`, `bearer_hash = hashlib.sha256(header[7:].encode()).hexdigest()[:16]`; else `bearer_hash = "none"`. (Hash avoids logging raw tokens; 16 hex chars = 64 bits, collision-safe for <10k keys.)
- For `mode="bearer"`: return `f"b:{bearer_hash}"`.
- For `mode="both"`: return `f"ip:{client_ip}|b:{bearer_hash}"`.

**`@rate_limit(steady: float, burst: int, key_mode: str = "both")`** decorator (~15 LOC):
- Wraps async handler. Extracts `Request` from kwargs (FastAPI auto-injection if param typed `Request`). Calls `make_key(request, mode=key_mode)` → `_store.take(key, steady=steady, burst=burst)`. On `(False, retry_after_s)`: raise `HTTPException(429, headers={"Retry-After": str(max(1, int(retry_after_s)))}, detail={"error": "rate_limited", "retry_after_s": int(retry_after_s)})`. On `(True, _)`: pass-through to handler.

**Whitelist policy** (final): sentinel `"__whitelist__"` returned from `make_key` for any IP in `_WHITELIST_IPS = frozenset({"127.0.0.1", "::1"})`. Phase-2 mobile pairing adds paired-device IPs OR (preferred per OQ 7) keeps the IP whitelist unchanged and lets paired mobiles fall through to per-Bearer attribution. Decision frozen: whitelist is for **loopback only**; mobiles go through Bearer-keyed limit.

## Options Considered

### Comparison matrix

| Option | New dep | LOC (impl + tests) | Maintenance debt | Correctness-risk | Effort | Whitelist control | `X-RateLimit-*` ext |
|---|---|---|---|---|---|---|---|
| **A — slowapi** | +1 (pin in `requirements.txt`) | ~10 impl, lib-tested | CVE-watch + lib upgrades | low (battle-tested) | S | indirect (key-func) | needs upstream PR or fork |
| **B — custom token-bucket** | 0 | ~50 impl + ~80 tests | extends `_format_tokens` shape (`app/main.py:2391-2493`) | medium (refill math) | S | direct (sentinel) | trivial (own response) |
| **C — reverse-proxy (nginx/Tailscale)** | 0 in-app | ~0 (docs only) | shifted to user / ops | high (default ships unprotected) | XS | N/A (proxy config) | proxy-emitted |

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
- Sketch: full API shape in Findings 2026-05-15 "TokenBucket API shape" subsection (TokenBucket / BucketStore / make_key / @rate_limit). `_store: BucketStore = BucketStore()` module singleton. Whitelist set `frozenset({"127.0.0.1", "::1"})` checked in `make_key`, returns sentinel `"__whitelist__"` that `BucketStore.take` short-circuits.
- Pattern alignment: `app/main.py:2391-2493` `_format_tokens` = TTL'd-dict + `threading.Lock` + lazy-purge. Same shape, battle-tested in-repo.
- Pros: no new dep (matches Phase-1 lean stance per `draftplan_security-api-auth-hardening.md:345` Decisions); full control over key-func / whitelist / response shape; `X-RateLimit-*` triple is a 3-line response-mutation in our decorator vs upstream slowapi PR; concurrency identical to `_format_tokens`.
- Cons: maintenance burden; less battle-tested than slowapi; hand-roll `Retry-After` math + refill correctness; test coverage entirely ours.
- Effort: S (50 LOC impl + 80 LOC tests).
- Risk: medium — refill-math concurrency bugs are subtle; mitigated by `tests/test_rate_limit.py` 7 cases listed in Implementation Plan §Step-by-step #2.

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

**Option B (custom token-bucket) for v1.** No new dep (matches Phase-1 stance, `draftplan_security-api-auth-hardening.md:345`). ~50 LOC mirrors `_format_tokens` shape (`app/main.py:2391-2493`). Full control over `Retry-After` + future `X-RateLimit-*` triple. Fall back to Option A only if Option B hits a wall (sliding-window fairness, multi-key composites).

**Decorator usage on first three gated routes** (pseudocode-prose; lives in `app/main.py` post-decorator-stack):

```
# app/rate_limit.py exports @rate_limit decorator + _store singleton

@app.post("/api/system/shutdown")                 # app/main.py:2071
@rate_limit(steady=5.0, burst=10, key_mode="both")
async def shutdown(req: Request, token: str = ""): ...

@app.post("/api/system/restart")                  # app/main.py:2080
@rate_limit(steady=5.0, burst=10, key_mode="both")
async def restart(req: Request, token: str = ""): ...

@app.post("/api/soundcloud/auth-token")           # app/main.py:3048
@rate_limit(steady=5.0, burst=10, key_mode="both")
async def sc_auth_token(req: Request, payload: AuthTokenReq): ...
```

Decorator order: `@app.post(...)` outermost, `@rate_limit(...)` directly under, then any `Depends(require_session)` via `dependencies=[…]` in `@app.post`.

**Gate to `evaluated_`**: Phase-1 auth-hardening must ship (currently at `implement/draftplan_security-api-auth-hardening.md`). Promote once auth lands in `archived/implemented_security-api-auth-hardening_*`. All Open Questions resolved or PARKED above — no user-decisions blocking promotion.

---

## Implementation Plan

Seeded at `exploring_`. Fleshed out at `implement/draftplan_`.

### Scope
- **In:** `app/rate_limit.py` (TokenBucket + BucketStore + make_key + @rate_limit decorator); decorator applied to first 3 routes (`shutdown`, `restart`, `sc_auth_token`); `tests/test_rate_limit.py`.
- **Out:** middleware-mode wrap of static mounts (`/exports`, `/api/artwork`); `X-Forwarded-For` trust (Phase-2 PARKED OQ 6); `X-RateLimit-*` triple (Phase-2 PARKED OQ 5); heartbeat gate (waits for Phase-2 LAN bind); persistence to `session_state.db` (rejected OQ 8).

### Step-by-step
1. Write `app/rate_limit.py` per Findings 2026-05-15 "TokenBucket API shape" subsection. Module singleton `_store: BucketStore`. Public surface: `@rate_limit(steady, burst, key_mode)` + `_store` (for test reset).
2. Write `tests/test_rate_limit.py` first (TDD): `test_take_until_empty`, `test_refill_after_wait` (monkeypatched `time.monotonic`), `test_burst_allows_then_throttles`, `test_whitelist_bypass` (loopback IP → sentinel), `test_concurrent_take` (4 `threading.Thread` workers, exactly `burst` `(True, …)` returns), `test_ttl_purge` (set `last_refill` back 700s, trigger N+1 call, assert key evicted from `_buckets`), `test_auth_before_ratelimit` (unauth + over-limit → 401, not 429).
3. Apply decorator to 3 routes per Recommendation pseudocode. Add `req: Request` param if missing.
4. Manual smoke: `curl -X POST http://127.0.0.1:8000/api/system/shutdown` 11 times in quick succession → first 10 pass auth-check then proceed to handler (subject to existing Bearer gate), 11th returns 429 + `Retry-After`.
5. `pytest tests/test_rate_limit.py -v` + `ruff check app/rate_limit.py tests/test_rate_limit.py` + `mypy app/rate_limit.py`.
6. Doc-syncer pass: add row to `docs/FILE_MAP.md` (`app/rate_limit.py`); `python scripts/regen_maps.py`; update `docs/backend-index.md` if route signatures changed.

### Files touched
- `app/rate_limit.py` (new, ~50 LOC).
- `app/main.py` (3 decorator additions on lines `:2071`, `:2080`, `:3048` — plus `from app.rate_limit import rate_limit` import).
- `tests/test_rate_limit.py` (new, ~80 LOC).
- `docs/FILE_MAP.md`, `docs/MAP.md`, `docs/MAP_L2.md` (doc-syncer).

### Testing
- Unit: 7 cases above on `TokenBucket` + `BucketStore` + `make_key` + decorator (see Step-by-step #2).
- Integration: in-process FastAPI `TestClient` hits gated route 11x rapidly; asserts 11th = 429 with `Retry-After` header and JSON body `{"error": "rate_limited", "retry_after_s": int}`.
- Concurrent: 4-thread `take()` race over a 10-burst bucket asserts exactly 10 `(True, …)` returns.

### Risks & rollback
- **Refill-math bug** → buckets never refill or over-refill. Mitigated by `refill-after-wait` test + monkeypatched clock.
- **Decorator + `Depends(require_session)` ordering** — `Depends` resolves in FastAPI's request-pipeline *before* the handler function runs; `@rate_limit` wraps the handler, so its body executes after auth has already 401'd a missing/invalid Bearer. Net effect: 401 fires before 429 on unauth+over-limit. Mitigated by integration test (`tests/test_rate_limit.py::test_auth_before_ratelimit`).
- **Whitelist bypass on Phase-2 LAN bind** → loopback sentinel still active means Tauri remains unlimited even on LAN exposure. Acceptable: Tauri = trusted local. Document in `docs/SECURITY.md` Phase-2 update.
- **Rollback**: remove 3 decorator lines + `app/rate_limit.py` import. No DB migrations, no on-disk state. Revertable via single `git revert`.

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
