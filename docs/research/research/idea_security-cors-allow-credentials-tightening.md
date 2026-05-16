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

---

## Problem

`app/main.py:222-224` configures CORS with `allow_credentials=True, allow_methods=["*"], allow_headers=["*"]`. Wildcards tolerable today: no cookie-based auth — Bearer-in-`Authorization` header sidesteps CSRF. BUT: SC sentinel at `app/main.py:3036-3043` already sets a cookie via `Set-Cookie`. If anyone later adds session-cookie auth (mobile-pairing Phase-2, browser-only fallback), this CORS config becomes a live CSRF risk. Need: explicit `allow_methods` list (GET/POST/PUT/DELETE/PATCH/OPTIONS), explicit `allow_headers` list incl. `Authorization` + `Content-Type` + `X-Session-Token`, codify "no cookie-auth ever" as repo invariant.

## Goals / Non-goals

**Goals**
- …

**Non-goals**
- …

## Constraints

External facts bounding solution (rate limits, data shape, perf budget, legal, capacity). Cite source.

- …

## Open Questions

Numbered. Each resolvable (yes/no or X vs Y), not philosophy.

1. …

## Findings / Investigation

Dated subsections, append-only. ≤80 words each. Never edit past entries — supersede.

### YYYY-MM-DD — <label>
- …

## Options Considered

Required by `evaluated_`. Per option: sketch ≤3 bullets, pros, cons, S/M/L/XL, risk.

### Option A — <name>
- Sketch:
- Pros:
- Cons:
- Effort:
- Risk:

### Option B — <name>
- Sketch:
- Pros:
- Cons:
- Effort:
- Risk:

## Recommendation

Required by `evaluated_`. ≤80 words. Which option + what blocks commit.

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
