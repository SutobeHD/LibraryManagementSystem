---
slug: security-secrets-compare-digest-codebase-audit
title: Standardise secrets.compare_digest usage across all token compares in codebase
owner: tb
created: 2026-05-15
last_updated: 2026-05-15
tags: [security, follow-up, auth-audit-adjacent]
related: [security-api-auth-hardening]
---

# Standardise secrets.compare_digest usage across all token compares in codebase

> **Caveman style.** Fragments, bullets. Drop articles/filler/hedges. No prose paragraphs. Respect per-section caps below.
> State = folder + filename prefix (not frontmatter). Lifecycle = audit trail. See `../README.md`.

## Lifecycle

- 2026-05-15 — `research/idea_` — scaffolded from auth-audit adjacent findings
- 2026-05-15 — `research/idea_` — section fill + codebase audit
- 2026-05-15 — research/idea_ — rework pass + audit re-verification (quality-bar review pre-exploring_)
- 2026-05-15 — research/exploring_ — promoted; quality-bar met (audit table byte-verified; ruff-plugin misclaim corrected; compare_digest behavior live-verified)

---

## Problem

`app/main.py:2074,2083` uses `==` for SHUTDOWN_TOKEN compare → timing-attack relevant. Phase-1 auth introduces `require_session` with `secrets.compare_digest`, and old `==` paths are scheduled for deletion in the same Phase-1 commit. But other token / secret / signature `==` comparisons may remain elsewhere: SoundCloud OAuth callback verify, format-confirm capability token (~line 2440), USB format token, any HMAC compare. Need: enumerate every site, length-check before compare, decide shared helper `app/security_compare.py` vs inline `secrets.compare_digest`. Cost of inaction: drift back into `==`, inconsistent enforcement across newly-added routes.

## Goals / Non-goals

**Goals**
- Every token/secret/HMAC/capability-token compare uses `secrets.compare_digest` (constant-time)
- Length-check (and bytes-encode) before `compare_digest` — raw `compare_digest` raises `TypeError` on mismatched-length bytes or non-bytes-like
- Single shared helper `app/security_compare.py::safe_compare(token, expected)` to avoid pattern drift across routes
- Audit table covers all current sites with verdict (safe / needs-fix / not-applicable / out-of-scope)
- Coding-rules.md gains a manual review checklist for "any new token/secret compare must use the helper"

**Non-goals**
- Refactor `==` on non-secret strings (user-input phrase like `typed_confirmation == "FORMAT D"` is intentional UX, not auth)
- Refactor checksum/fingerprint compares (MD5/SHA1 on audio/cache content — not auth tokens)
- Replace dict `.get(token)` lookups (Python dict hash-collision is a separate question; address in Phase-2 if `_format_tokens` ever scales)
- Move SoundCloud OAuth token storage (already in OS keyring — out of scope)
- Mechanical lint backstop (Option C — pre-commit grep or semgrep) — defer unless drift recurs; ruff custom plugin is NOT viable (no plugin API)

## Constraints

External facts bounding solution (rate limits, data shape, perf budget, legal, capacity). Cite source.

- **`secrets.compare_digest(a, b) -> bool`** — accepts `str` (ASCII only) or bytes-like; raises `TypeError` on mixed `str`/`bytes`, `TypeError` on non-ASCII `str`; **does not** raise on length mismatch — returns `False` but with constant-time guarantee weakened. CPython docs: "If a and b are of different lengths, or if an error occurs, a timing attack could theoretically reveal information about the types and lengths of a and b". → Length-check + ASCII-or-bytes-only is required pre-call.
- **`hmac.compare_digest`** = alias of `secrets.compare_digest` (same primitive, same constraints). Either is fine; `secrets.compare_digest` is the modern idiom.
- **Pre-Phase-1 sites (to be deleted by Phase-1 plan)**: `SHUTDOWN_TOKEN` module-const (`app/main.py:125`), `==` compares at `app/main.py:2074,2083`, heartbeat token-leak at `app/main.py:951`. Phase-1's `draftplan_security-api-auth-hardening.md` (Step 8, line 431) deletes the query-string scheme entirely; module constant goes with it.
- **Phase-1 plan introduces `require_session`** (`app/auth.py` NEW, ~80 lines per draftplan line 442) — uses `secrets.compare_digest` correctly in the Bearer-path with length-check before compare (per draftplan line 481 mitigation note). Audit must NOT pre-empt this — Phase-1 lands the canonical pattern first; this audit only adds the shared helper + sweeps the remaining sites.
- **Existing `_format_tokens` capability check** (`app/main.py:2477,2493`) — uses `dict.get(r.token)` lookup, NOT a direct `==` compare. CPython dict lookup is hash-based (O(1) average) with potential timing variation in collision paths. For a 24-byte `secrets.token_urlsafe(24)` namespace (~144-bit entropy), this is not exploitable in practice — but the inner `meta["drive"] != r.drive` compare on line 2482 compares **drive paths** (e.g. `E:\\`), which are NOT secret. So `_format_tokens` is safe as-is; the dict-lookup is the auth boundary, not a string compare.
- **SoundCloud OAuth**: token storage in OS keyring (`keyring.set_password` at `app/main.py:3076`), token usage as outbound `Authorization: OAuth <token>` header to SC API (`app/soundcloud_api.py:249`, `app/soundcloud_downloader.py:217,310,520,579,628`). **No server-side OAuth callback** — SC token is set via UI-paste through `POST /api/soundcloud/auth-token`, not via redirect-callback. → No signature/state-verify compare exists. Token-format validation at line 3061-3072 uses length + `isascii()` checks, not equality. **Out of scope** — no compare to harden.
- **rbox / usb_pdb / anlz checksums**: `struct.unpack` byte-layout reads (`app/usb_pdb.py`), MD5 fingerprints for cache-key derivation (`app/analysis_cache.py:105`, `app/analysis_db_writer.py:35`), SHA1 for content-ID derivation (`app/anlz_sidecar.py:26`, `app/library_source.py:43`, `app/usb_one_library.py:875`). **All non-auth** — content-addressed identifiers, not secrets. Out of scope.
- **Frontend `key ===`** matches are React `KeyboardEvent.key` (UI keyboard handling). Out of scope.
- **Rust side** (`src-tauri/src/`): no `token ==` / `secret ==` sites — Rust does not handle auth tokens (no Rust-side HTTP-auth client to the sidecar per draftplan line 252). Out of scope.

## Open Questions

Numbered. Each resolvable (yes/no or X vs Y), not philosophy.

1. **Shared helper module vs inline?** Option B (`app/security_compare.py::safe_compare(token: str, expected: str) -> bool`) handles `isinstance` + length + ASCII + encode-to-bytes + `secrets.compare_digest` in one call. Inline at each site (currently only Phase-1's `require_session`) duplicates the boilerplate. **Lean: Option B** — even with only 2-3 sites today, the helper gives one audit-point + one test-target.
2. **Lint rule (pre-commit grep or semgrep)?** Ruff has **no third-party plugin API** (verified ruff 0.15.12 `--help`: no plugin/extension flag; only built-in Rust-implemented rules). Options for mechanical enforcement are: (a) pre-commit `pygrep-hooks` matching `\btoken\s*==` / `\bsecret\s*==` — ~15 lines in `.pre-commit-config.yaml`; (b) `semgrep` rule (real AST-based pattern, fewer false positives, but adds a new dev-dep). **Lean: defer** — manual review checklist in `coding-rules.md` is cheaper and the helper-import pattern is self-policing (anyone writing a new compare grabs the helper).
3. **Audit cadence: one-shot now + CI lint, or recurring quarterly?** One-shot if Phase-1 lands the helper + the codebase stays small (~141 routes, 1 contributor). Recurring if route count grows or contributor pool widens. **Lean: one-shot now** — re-audit only when a new route under `app/` is added by something other than `route-architect` agent (which can be taught to grep for the helper).
4. **Helper signature: `safe_compare(token, expected)` or `safe_compare_token(presented, expected)`?** Argument order matters for readability (left = untrusted, right = trusted). **Lean: `safe_compare(presented: str, expected: str) -> bool`** — order + naming makes the trust direction explicit.
5. **What about `hmac.compare_digest` vs `secrets.compare_digest`?** Identical primitive. **Lean: `secrets.compare_digest`** — modern stdlib idiom, doesn't pull `hmac` for compare-only use.

## Findings / Investigation

Dated subsections, append-only. ≤80 words each. Never edit past entries — supersede.

### 2026-05-15 — codebase-wide audit

Audit grep targets: `secrets.compare_digest`, `hmac.compare_digest`, `(token|secret|key|hash|sig|signature|hmac|digest)\s*(==|!=)`, `(==|!=)\s*(SHUTDOWN_TOKEN|SESSION_TOKEN|token|secret|password|...)`. Coverage: `app/`, `tests/`, `src-tauri/`, `frontend/`. Result: **zero existing `secrets.compare_digest` / `hmac.compare_digest` usages anywhere in source** (only mentioned in research docs). Two `token ==` sites in `app/main.py:2074,2083` (SHUTDOWN_TOKEN — Phase-1 deletes both). Zero `token ==` in Rust/frontend.

### 2026-05-15 — audit site table

| Site | Pattern | Auth-relevant? | Verdict | Phase-1 covers? |
|---|---|---|---|---|
| `app/main.py:2074` | `if token != SHUTDOWN_TOKEN` (`/api/system/shutdown`) | YES | **needs-fix → deleted by Phase-1** | YES — route gated by `require_session` Bearer, query-param `token` removed |
| `app/main.py:2083` | `if token != SHUTDOWN_TOKEN` (`/api/system/restart`) | YES | **needs-fix → deleted by Phase-1** | YES — same as above |
| `app/main.py:125` | `SHUTDOWN_TOKEN = secrets.token_urlsafe(32)` | YES (constant) | **deleted by Phase-1** | YES — module-const removed (draftplan line 431) |
| `app/main.py:951` | `payload["token"] = SHUTDOWN_TOKEN` (heartbeat loopback-only leak) | YES (leak, not compare) | **deleted by Phase-1** | YES — heartbeat token-leak removed; new token never exposed via HTTP |
| `app/main.py:2477` | `meta = _format_tokens.get(r.token)` (USB format-confirm) | YES (dict-key lookup) | **safe** — dict-hash boundary on 144-bit `token_urlsafe(24)`; no string-`==` compare | N/A — not in Phase-1 scope, already capability-token-pattern |
| `app/main.py:2482` | `meta["drive"] != r.drive` | NO — drive path is non-secret UX cross-check | **not-applicable** | N/A |
| `app/main.py:2488` | `r.typed_confirmation.strip() != expected` (FORMAT phrase) | NO — user-typed UX phrase, not secret | **not-applicable** | N/A |
| `app/main.py:3061-3072` | SC OAuth token length + `isascii()` validation | NO — input-format check, not equality | **not-applicable** | N/A |
| `app/main.py:3076` | `keyring.set_password(KEYRING_SERVICE, KEYRING_SC_TOKEN, token)` | YES (storage, not compare) | **safe** — OS keyring, no in-code compare | N/A |
| `app/soundcloud_api.py:249` + `soundcloud_downloader.py:217,310,520,579,628` | `Authorization: OAuth <token>` outbound header | NO — outbound, not compare | **not-applicable** | N/A |
| `app/main.py:3769` + 8 other `hashlib.{md5,sha1,sha256}` sites | content-fingerprint / cache-key / device-ID | NO — not auth tokens | **not-applicable** | N/A |
| `app/usb_pdb.py` `struct.unpack` reads | byte-layout parsing | NO — file-format, not auth | **not-applicable** | N/A |
| `src-tauri/**/*.rs` | (no matches) | — | **not-applicable** | N/A |
| `frontend/**/*.{js,jsx}` `key ===` matches | React `KeyboardEvent.key` | NO — UI keyboard | **not-applicable** | N/A |
| `tests/test_security_hotfixes.py:99,104` | `body.get("token") == SHUTDOWN_TOKEN` | NO — test assertion | **not-applicable** | Phase-1 rewrites these tests anyway |

### 2026-05-15 — cross-reference vs Phase-1 plan

Phase-1 draftplan (`draftplan_security-api-auth-hardening.md`):
- Line 265: documents `==` at 2031/2040 (now 2074/2083 post-hotfix) as Finding #8.
- Line 319: `secrets.compare_digest` listed for token check (constant-time).
- Line 380: `secrets.compare_digest` listed in `require_session` design.
- Line 431: Step 8 deletes legacy `SHUTDOWN_TOKEN` query-string scheme entirely + module-const.
- Line 442: `app/auth.py` NEW — `require_session` uses `secrets.compare_digest`.
- Line 481: length-check before compare documented as mitigation.

**Phase-1 covers all current `==`-on-token sites in the codebase** (both at 2074/2083). It does NOT introduce a shared `app/security_compare.py` helper — `require_session` calls `secrets.compare_digest` inline in `app/auth.py`. So this audit's value-add is: (a) confirm no other compares exist anywhere (done above), (b) propose extracting the inline `compare_digest`-call pattern into the shared helper as a follow-up after Phase-1 lands, so any future tokens (e.g. Phase-2 rate-limit-bypass tokens, plugin-API keys, etc.) have a single canonical site.

### 2026-05-15 — sites Phase-1 misses

None. Audit is exhaustive — every `==`/`!=` token-compare in active code is at `app/main.py:2074,2083`, both deleted by Phase-1. `_format_tokens` capability-token uses dict-lookup (safe). SoundCloud OAuth has no server-side callback-verify. No HMAC compares anywhere. The audit's recommendation is **forward-looking** (helper + checklist), not back-filling missing fixes.

## Options Considered

Required by `evaluated_`. Per option: sketch ≤3 bullets, pros, cons, S/M/L/XL, risk.

### Option A — Inline `secrets.compare_digest` at each site
- Sketch:
  - Each route that needs a token compare imports `secrets` + writes the length-check + `compare_digest` inline (3-4 lines per site)
  - Pattern lives in code review, not a module
  - Phase-1's `require_session` already follows this pattern
- Pros: Zero new module. No import. Each call site is self-explanatory.
- Cons: Pattern drift over time — easy to forget length-check, easy to use `==` instead. Audit per-site every quarter. No single test target.
- Effort: S (zero — Phase-1 already does this for the only existing site).
- Risk: Medium — drift recurs as routes are added by future contributors / non-`route-architect` paths.

### Option B — Shared `app/security_compare.py` helper *(RECOMMENDED)*
- Sketch:
  - New file `app/security_compare.py` exports `safe_compare(presented: str, expected: str) -> bool` (handles bytes-encode + length-check + `secrets.compare_digest`)
  - Phase-1's `require_session` refactored to `safe_compare(token, SESSION_TOKEN)` after Phase-1 lands
  - Any future token-compare (rate-limit bypass, plugin keys, etc.) imports the helper
  - Unit tests in `tests/test_security_compare.py`: empty, length-mismatch, ASCII-only, non-ASCII, bytes-input, equal, unequal-same-length
- Pros: One audit point. One test target. Self-documenting via import. Coding-rules.md can say "any token compare MUST import safe_compare".
- Cons: 1 new file (~20 LOC), 1 new test file (~50 LOC). Requires a follow-up refactor of `require_session` post-Phase-1.
- Effort: S (helper + tests = ~70 LOC; refactor `require_session` = 3-line change).
- Risk: Low — pure additive.

### Option C — pre-commit grep or semgrep rule
- Sketch:
  - `.pre-commit-config.yaml` adds `pygrep-hooks` entry matching `\b(token|secret|password)\s*(==|!=)\s*` in `app/**/*.py`
  - OR `semgrep` rule (AST-based pattern, less false-positive prone than regex; adds semgrep as a new dev-dep)
  - Note: ruff custom plugins are NOT viable — ruff has no third-party plugin API (built-in Rust rules only)
  - Fail-fast on any new `token ==` in CI before merge
- Pros: Mechanical enforcement, no human-review reliance. Backstop for Option A/B drift.
- Cons: Regex variant false-positives common (`if some_var_name_with_token == "literal"` triggers); needs allowlist. Doesn't help with the deeper bug (forgetting length-check). Adds CI step. Semgrep adds a new dev-dep.
- Effort: M (10-15 LOC config + allowlist refinement over time for pygrep; ~30 LOC + dep for semgrep).
- Risk: Medium — noise risk if rule too broad; bypass risk if rule too narrow.

## Recommendation

Required by `evaluated_`. ≤80 words. Which option + what blocks commit.

**Option B + manual checklist** — land Phase-1 first (introduces inline `secrets.compare_digest` in `require_session`), then this follow-up extracts the pattern into `app/security_compare.py::safe_compare`, refactors `require_session` to use it, adds unit tests, adds a one-line entry to `coding-rules.md` under "Backend concurrency" or new "Auth" section. **Option C as backstop**: if drift recurs after 6 months (i.e. a new `token ==` lands in a PR), add the pygrep-hook then. **Blocks commit until**: Phase-1 lands; helper file exists; `require_session` refactored; tests green; coding-rules.md entry added.

**Concrete first step (post-Phase-1):** create `app/security_compare.py` with `safe_compare(presented: str, expected: str) -> bool` (≤20 LOC: isinstance check → reject non-str → length-check → ASCII-check → encode-to-bytes → `secrets.compare_digest`). Then create `tests/test_security_compare.py` (7 cases per Option B sketch). Then 3-line refactor in `app/auth.py::require_session` to call `safe_compare(...)` instead of inline `secrets.compare_digest(...)`. Total: 1 new file + 1 new test file + 3-line edit in 1 file.

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

- Code: `app/main.py:2074,2083` (== sites, Phase-1 deletes), `app/main.py:125` (SHUTDOWN_TOKEN const, Phase-1 deletes), `app/main.py:2391-2493` (`_format_tokens` capability-token, dict-lookup safe), `app/main.py:3048-3095` (SC OAuth keyring storage, no compare)
- External docs: [`secrets.compare_digest` — Python stdlib](https://docs.python.org/3/library/secrets.html#secrets.compare_digest), [`hmac.compare_digest`](https://docs.python.org/3/library/hmac.html#hmac.compare_digest)
- Related research: `security-api-auth-hardening` (Phase-1 introduces the canonical pattern in `require_session`)
