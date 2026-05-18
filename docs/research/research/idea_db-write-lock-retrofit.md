---
slug: db-write-lock-retrofit
title: Retrofit _db_write_lock acquisition on all master.db write routes
owner: tb
created: 2026-05-19
last_updated: 2026-05-19
tags: [backend, concurrency, rbox, security, follow-up]
related: [security-api-auth-hardening]
ai_tasks: false
---

# Retrofit _db_write_lock acquisition on all master.db write routes

## Lifecycle

- 2026-05-19 — `research/idea_` — scaffolded from auth-hardening adjacent finding (metadata-name-fixer Constraints)

## AI Tasks

<!--
Opt-in queue for remote AI routines. Activate by setting `ai_tasks: true` in frontmatter.
Each item: 1 concrete sub-task. Routine processes 1/run, ticks done, commits via PR.
-->

- [ ] _(none yet — flag stays false until Open Questions firm up)_

---

## Problem

`_db_write_lock` (`app/database.py:22`) + `db_lock()` ctx-manager (25-40) + `_serialised` decorator (43-53) all defined — none acquired. Grep `db_lock|_db_write_lock` in `app/main.py` returns 0/85 mutating routes. Grep `@_serialised` in `app/database.py` returns 0 applications — decorator dead. Docstring at `database.py:36-37` claims "individual mutating methods are already wrapped" — false. Under concurrent POST/PUT/PATCH/DELETE, writers race against `master.db`. rbox 0.1.7 known to panic on concurrent writes. Cost of inaction: silent data corruption + sidecar crashes once Phase-2 mobile-companion lands concurrent edit load.

## Goals / Non-goals

**Goals**
- Every `master.db` write path serialised through `_db_write_lock` before merge.
- Invariant from `coding-rules.md` "Backend concurrency" becomes enforced, not aspirational.
- Zero behavior change for read paths.
- Test coverage proves concurrent writers serialise (no rbox panic, no sqlite `database is locked`).

**Non-goals**
- Not redesigning rbox isolation (`anlz_safe.py` ProcessPoolExecutor stays).
- Not adding row-level locking — RLock around `master.db` writers, full stop.
- Not extending to XML mode (`RekordboxXMLDB`) unless trivially covered.
- Not blocking on Phase-2 mobile-companion landing — prereq for it, not coupled.

## Constraints

- `_db_write_lock = threading.RLock()` at `app/database.py:22`. Reentrant — nested calls safe.
- `db_lock()` ctx-manager at `app/database.py:25-40` — public callsite helper.
- `_serialised` decorator at `app/database.py:43-53` — defined, **0 applications** in module.
- `app/main.py` 85 mutating routes (POST/PUT/PATCH/DELETE) from auth-hardening audit (archived `implemented_security-api-auth-hardening_2026-05-17.md`). 0 acquire the lock today.
- `app/anlz_safe.py` ProcessPoolExecutor + bisect blacklist — adjacent rbox-isolation precedent for **read** paths. Process boundary ≠ thread lock — orthogonal concern.
- rbox 0.1.7 panics on concurrent writes (CLAUDE.md `coding-rules.md` "Backend concurrency").
- Phase-1 `require_session` already on every mutation route (84/85, archived doc). Phase-2 `@rate_limit` already on 3 sensitive routes. Adding lock = third dependency in stack.

## Open Questions

1. **Insertion point** — FastAPI `Depends(serialise_writes)` (single point) vs per-route `with db_lock():` (mechanical, lots of diff) vs `@_serialised` class-method auto-wrap (cleanest long-term, fixes the dead-decorator lie)? Each has different blast radius for the existing 85 routes.
2. **Method-level vs route-level retrofit** — fix `RekordboxDB.update_tracks_metadata` + siblings (covers all callers automatically) vs middleware wrapping every POST/PUT/PATCH/DELETE handler (covers future callers but locks read-only mutations too coarse)?
3. **Backwards-compat** — any route NEEDS lock-free write access (long-running mutation that yields, streaming response with side-effects, background task spawn)? Audit before locking.
4. **Phase ordering** — Phase-3 dependency-stack item layered after `require_session` + `@rate_limit`, or separate cross-cutting concern? Order matters: rate-limit-then-lock vs lock-then-rate-limit changes failure mode (429 vs queue depth).
5. **Test strategy** — 4-thread concurrent-POST harness + sqlite busy-timeout assertion + rbox panic detection. Where does it live (`tests/test_concurrency.py` new file)? Reproducer for the panic without flakiness — possible?
6. **rbox ProcessPoolExecutor interaction** — `_db_write_lock` is threading-only. `anlz_safe.SafeAnlzParser` lives in worker process — does the lock cover ProcessPool boundary or is parser read-only enough to ignore? Confirm parser never writes.

## Findings / Investigation

### 2026-05-19 — empirical lock-acquisition grep
- `grep -c 'db_lock\|_db_write_lock' app/main.py` → 0 (zero of 85 mutation routes).
- `grep -c '@_serialised' app/database.py` → 0 (decorator defined, never applied).
- `update_tracks_metadata` (`app/database.py:1007`) — no `with _db_write_lock`, no `@_serialised`. Reproduces auth-hardening finding.
- Docstring `database.py:36-37` claims method-level wrap — **inaccurate**. Either documentation drift or decorator was removed without docstring update.
- Surfaced in `exploring_metadata-name-fixer.md` Constraints (2026-05-15) as adjacent risk during M0 audit. Carved out here to keep that doc scoped.

## Options Considered

### Option A — per-route `with db_lock():` retrofit
- Sketch:
  - Touch each of 85 handlers in `app/main.py`.
  - Wrap `db.foo(...)` calls in `with db_lock():`.
  - Mechanical, surface-level.
- Pros: explicit; visible at call site; easy to grep coverage.
- Cons: 85-line diff; easy to miss new routes; future routes need reviewer to remember.
- Effort: M
- Risk: low correctness, high drift (new routes unprotected).

### Option B — `Depends(serialise_writes)` FastAPI dependency
- Sketch:
  - New `app/auth.py`-adjacent dep yielding inside `with _db_write_lock:`.
  - Add to every POST/PUT/PATCH/DELETE handler (already touched by `Depends(require_session)`).
  - Ordering: `require_session` → `rate_limit` → `serialise_writes`.
- Pros: single insertion point; reusable; pairs with existing dep stack.
- Cons: per-route opt-in still required; harder to enforce globally; lock held for entire request (incl. JSON-parse + validation) — fatter critical section.
- Effort: M
- Risk: critical section bloats request latency under load.

### Option C — `RekordboxDB`-class-method auto-wrap via `@_serialised`
- Sketch:
  - Apply `@_serialised` to every mutating method on `RekordboxDB` (`update_*`, `add_*`, `remove_*`, `create_*`, `delete_*`, `save_*`).
  - Repair the docstring lie at `database.py:36-37` — now true.
  - Optional: class decorator iterates `vars(cls)` and wraps method names matching a prefix list.
- Pros: lock scope tight (DB call only); future routes auto-covered; restores docstring truth; zero `app/main.py` churn.
- Cons: hides locking from route author; debugging deadlocks harder; need to audit XML-mode siblings (`RekordboxXMLDB`); ProcessPoolExecutor boundary uncovered.
- Effort: S–M
- Risk: missed method = silent unprotected write; need a test asserting every public mutator on `RekordboxDB` is wrapped.

## Recommendation

_(empty — fill at `evaluated_`)_

---

## Implementation Plan

_(empty — fill at `implement/draftplan_`)_

## Review

_(empty — fill at `review_`)_

## Implementation Log

_(empty — fill at `inprogress_`)_

---

## Decision / Outcome

_(empty — fill at `archived/`)_

## Links

- Code: `app/database.py:22` (`_db_write_lock`), `app/database.py:25-40` (`db_lock()`), `app/database.py:43-53` (`_serialised`), `app/database.py:1007` (`update_tracks_metadata` — unprotected), `app/main.py` (85 mutation routes, 0 acquire), `app/anlz_safe.py:1-40` (ProcessPoolExecutor precedent for adjacent rbox isolation).
- Rules: `.claude/rules/coding-rules.md` "Backend concurrency" (aspirational invariant).
- Related research: `security-api-auth-hardening` (archived 2026-05-17, carved this out), `metadata-name-fixer` (Constraints surface, 2026-05-15).
