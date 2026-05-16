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
- **Reverse-proxy header trust** — under Tailscale / Cloudflare Tunnel / nginx, the real client IP is in `X-Forwarded-For`; `request.client.host` becomes the proxy. Must be parsed safely; trust only when a `TRUST_PROXY_HEADERS` env-flag is set, otherwise spoofable on any LAN.
- **Phase-1 doesn't ship LAN bind by default** (sidecar binds `127.0.0.1:8000` per `app/main.py:4012`). Rate-limit becomes critical in Phase-2 when mobile companion forces `0.0.0.0` bind or reverse-proxy mode.
- **Memory budget** — desktop sidecar; in-memory bucket store is fine (entries TTL'd; expect < 10k unique keys per session).
- **Single-instance assumption** — no horizontal scale; no shared state needed across processes.

## Open Questions

Numbered. Each resolvable (yes/no or X vs Y), not philosophy.

1. In-memory custom token-bucket vs slowapi (extra pinned dep)?
2. Attribution: per-IP only, per-token only, or both (per-IP for unauth routes + per-token for auth routes)?
3. Burst-allowance shape per endpoint — e.g. 10/min steady, 30/min burst — single global default or per-route table?
4. Whitelist behavior: explicit loopback exempt (skip limiter entirely) OR generous caps for loopback (e.g. 600/min)?
5. 429 response: include `X-RateLimit-Limit` / `X-RateLimit-Remaining` / `X-RateLimit-Reset` headers, or only `Retry-After`?
6. `X-Forwarded-For` trust: enabled only when `TRUST_PROXY_HEADERS=1` env-flag is set?
7. Paired-mobile attribution: treat as per-token (Bearer) and use the token-bucket, OR add the paired-device IP to the whitelist on pairing?
8. Bucket persistence: in-memory only (reset on sidecar restart) or persist to sidecar-local SQLite (`session_state.db`)?

## Findings / Investigation

Dated subsections, append-only. ≤80 words each. Never edit past entries — supersede.

### 2026-05-15 — initial scope
- Routes most needing rate-limit: pairing endpoints (Phase-2 brute-force token guess), `/api/system/shutdown` + `/api/system/restart` (DoS / restart-spam), `/api/soundcloud/auth-token` (token-overwrite spam), `/api/system/heartbeat` (if LAN-exposed).
- Token-bucket vs sliding-window trade-off: token-bucket simpler (one float + one timestamp per key), allows bursts naturally; sliding-window more fair but needs ring buffer.
- slowapi minimum-viable wire: 3 lines for `Limiter` init, 1 `@limiter.limit("5/minute")` decorator per route.
- Custom impl: ~50 LOC for thread-safe `dict[key, (tokens, last_refill)]` + `@rate_limit(rate, burst)` decorator + `RLock`.

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
- Sketch:
  - `app/rate_limit.py` ~50 LOC: thread-safe `dict[str, Bucket]` + `RLock`, refill-on-read, TTL eviction
  - `@rate_limit(steady="5/min", burst=10, key="ip|token|both")` decorator
  - Whitelist set (`{"127.0.0.1", "::1"}` + paired IPs) checked before bucket lookup
- Pros: no new dep (matches Phase-1 lean stance), full control over key-func / whitelist / response shape, easy to wire `X-RateLimit-*` headers exactly the way the frontend expects
- Cons: maintenance burden, less battle-tested, must hand-roll `Retry-After` math, test coverage entirely on us
- Effort: S (50 LOC + tests)
- Risk: medium — concurrency bugs in the bucket-refill math are subtle; mitigated by a focused `tests/test_rate_limit.py`

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

**Option B (custom token-bucket) for v1.** Matches Phase-1 no-new-dep stance; ~50 LOC is auditable; full control over `X-RateLimit-*` header shape and whitelist semantics. Fall back to **Option A (slowapi)** only if behavior gaps emerge (e.g. need for sliding-window fairness, multi-key composite buckets we can't get right). Blocker before commit: resolve OQ 2 (attribution shape) + OQ 4 (whitelist vs generous caps) — both drive the bucket key-func design.

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
