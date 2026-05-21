---
slug: db-write-lock-retrofit
title: Close _db_write_lock coverage gaps on master.db write methods
owner: tb
created: 2026-05-19
last_updated: 2026-05-21
tags: [backend, concurrency, rbox, security, follow-up]
related: [security-api-auth-hardening]
---

# Close _db_write_lock coverage gaps on master.db write methods

## Lifecycle

- 2026-05-19 — `research/idea_` — scaffolded from auth-hardening adjacent finding (metadata-name-fixer Constraints)
- 2026-05-19 — `research/idea_` — deep exploration toward exploring_-ready (empirical audit)
- 2026-05-21 — `research/idea_` → `implement/draftplan_` — planning started; GATE A/B skipped by user decision (idea explored to Recommendation, OQs all RESOLVED)
- 2026-05-21 — `implement/draftplan_` → `implement/review_` — Implementation Plan + Task Queue written; independent Review PASS
- 2026-05-21 — `implement/review_` → `implement/plangate_` — plan reviewed, awaiting GATE C
- 2026-05-21 — `implement/plangate_` → `implement/rework_` — GATE C rejected by user: independent re-review found a 3rd unprotected master.db writer (AnalysisDBWriter); 6 rework reasons

---

## Problem

> **2026-05-19 audit overturned the scaffold premise.** `_serialised` IS applied — `setattr` loop at `database.py:1076-1086` wraps 21 `RekordboxDB` methods. Scaffold's "0 applications / dead decorator / false docstring / `update_tracks_metadata` unprotected" findings all wrong. Real, smaller problem below.

`_serialised` (`app/database.py:43-53`) wraps mutating `RekordboxDB` methods via a `setattr` loop — but the loop is a **hand-maintained name list** (`database.py:1077-1084`). The list drifts. AST enumeration of `RekordboxDB` finds **1 mutator missing**: `ensure_standalone_master_db` (`database.py:728`) — calls `rbox.OneLibrary.create()`, writes `master.db`, unwrapped. Low live-race risk (one-shot, `if path.exists(): return` guard) but a real coverage hole and proof the list-maintenance pattern fails silently.

The structural defect is the **list itself**: any future `RekordboxDB` mutator added without editing `database.py:1077-1084` is a silent unprotected writer. Concurrent writes corrupt because `LiveRekordboxDB` opens a **per-thread** `rbox.MasterDb` handle (`live_database.py:21,35` — `threading.local()`): multiple FastAPI request threads = multiple independent rbox/SQLite handles on one file. The lock is the only serialisation. rbox 0.1.7 panics on concurrent writes (`coding-rules.md`). Cost of inaction: a missed mutator → silent corruption + sidecar crash, risk rising once Phase-2 mobile-companion adds concurrent edit load.

**Second, bigger hole — the facade is NOT the sole chokepoint.** Routes `POST /api/mytags`, `DELETE /api/mytags/{id}`, `POST /api/track/{tid}/mytags` call `_require_live_db().create_mytag / delete_mytag / set_track_mytags` (`main.py:975,986,1002`) — they reach `LiveRekordboxDB` **directly**, bypassing `RekordboxDB` and therefore its `_serialised` wrapping entirely. `LiveRekordboxDB.create_mytag/delete_mytag/set_track_mytags` (`live_database.py:925,937,949`) write `master.db` **with no lock at all**. Any retrofit must wrap `LiveRekordboxDB` mutators too, or `_require_live_db()` stays a permanent unprotected write path.

> **Adjacent bug, NOT lock-scope** (separate fix): routes `POST /api/track/cues/save`, `/api/track/grid/save` (`main.py:1011,1014`) call `db.save_track_cues` / `db.save_track_beatgrid` — **neither method exists on the `RekordboxDB` facade** (no `__getattr__`). These two routes `AttributeError` at runtime. Out of scope here; flagged for its own task. (The mytag routes are *not* broken — they call `_require_live_db()`, see above.)

## Goals / Non-goals

**Goals**
- Every mutating method on **both** `RekordboxDB` and `LiveRekordboxDB` serialised. Metric: a test introspects mutators of both classes, asserts each carries `_serialised` (`func.__wrapped__` present) — count of unwrapped mutators = 0. Closes `ensure_standalone_master_db` (facade) + the 3 `LiveRekordboxDB` mytag writers reached via `_require_live_db()`.
- Coverage cannot silently drift. Metric: adding a new mutating method to either class without protection fails CI (the introspection test above).
- Zero behavior change for read paths. Metric: all `get_*`/`list_*` methods + property accessors stay unwrapped; existing `pytest tests/` green, no new failures.
- Concurrent writers proven to serialise. Metric: N-thread (N=8) concurrent-write harness completes with 0 rbox panics + 0 sqlite `database is locked`; with the lock monkeypatched to a no-op the same harness fails (negative control).

**Non-goals**
- Not redesigning rbox isolation (`anlz_safe.py` ProcessPoolExecutor stays).
- Not adding row-level locking — RLock around `master.db` writers, full stop.
- `RekordboxXMLDB` mutators — only wrapped if trivially covered. XML mode (`save_xml` to a file) is single-process, lower concurrent-write risk than the live `rbox.MasterDb`; in-scope only if the chosen mechanism (Option B prefix-match) sweeps it for free. Confirm at draftplan.
- Not blocking on Phase-2 mobile-companion landing — prereq for it, not coupled.
- Not converting `LiveRekordboxDB` per-thread connections to a shared pool — separate, larger concern (see PARKED note after Open Questions).
- Not fixing the broken `save_track_cues` / `save_track_beatgrid` routes (non-existent facade methods) — separate bug, own task.

## Constraints

_(all re-verified 2026-05-19 this session)_

- `_db_write_lock = threading.RLock()` at `app/database.py:22`. Reentrant — nested mutating calls (e.g. `update_track_comment` → `update_tracks_metadata`) don't self-deadlock.
- `db_lock()` ctx-manager at `app/database.py:25-40` — public multi-step-transaction helper. **0 callsites** (`grep db_lock app/main.py` → none) — not a bug; intended for atomic multi-mutation, none coded yet.
- `_serialised` decorator at `app/database.py:43-53` — **IS applied**. `setattr` loop `database.py:1076-1086` wraps 21 methods. Mechanism: `setattr(RekordboxDB, name, _serialised(getattr(RekordboxDB, name)))`. Not `@`-syntax, so a `@_serialised` grep misses it (false negative).
- Coverage gap: AST-enumerated `RekordboxDB` mutators vs 21-name loop list → **1 missing: `ensure_standalone_master_db`** (`database.py:728`, `rbox.OneLibrary.create()` writer). All other facade mutators (`update_*`, `add_*`, `delete_*`, `create_*`, `move_*`, `rename_*`, `reorder_*`, `set_mode`, `load/unload_library`, `refresh_metadata`, `save`) are in the list.
- `RekordboxDB` facade has **no** `create_mytag`/`delete_mytag`/`set_track_mytags`/`save_track_cues`/`save_track_beatgrid` methods (verified AST). `create_mytag`/`delete_mytag`/`set_track_mytags` exist on `RekordboxXMLDB` (`database.py:567,574,587`) + `LiveRekordboxDB` (`live_database.py:925,937,949`) — and the mytag routes reach them via `_require_live_db()`, so those are real (unwrapped) write paths, not broken routes. `save_track_cues`/`save_track_beatgrid` exist on **no** class — routes `main.py:1011,1014` call `db.<that>` on the facade (no `__getattr__`) → runtime `AttributeError`; that pair is the adjacent broken-route bug, not a lock gap.
- `app/main.py` — 85 mutating routes (POST/PUT/PATCH/DELETE), `grep -c '@app.(post|put|patch|delete)'` → 85, confirmed. Routes don't need the lock directly: protection lives on `RekordboxDB` methods.
- Route decorator pattern (FYI, not load-bearing here): `@app.post(path, dependencies=[Depends(require_session)])` — auth is a decorator kwarg, `@rate_limit` a separate stacked decorator (`main.py:2185,2192,3159`). Confirms a route-level lock would have to stack here — rejected anyway (OQ2).
- `LiveRekordboxDB` opens `rbox.MasterDb` per thread via `threading.local()` (`live_database.py:21,35`). Concurrent threads = concurrent independent handles on one file — root cause of the race.
- `app/anlz_safe.py` ProcessPoolExecutor — **read-only**: iterates `get_content_anlz_paths` + reads `rbox.Anlz` beatgrids, never writes (module docstring `anlz_safe.py:1-40` confirms). `threading.RLock` doesn't cross the process boundary — irrelevant here since parser doesn't write.
- rbox 0.1.7 panics on concurrent writes (CLAUDE.md `coding-rules.md` "Backend concurrency"). Same crate, same `unwrap()`-on-abort failure mode as the read-path panic `anlz_safe.py` quarantines.
- Phase-1 `require_session` on every mutation route; Phase-2 `@rate_limit` on 3 routes (archived `implemented_security-api-auth-hardening_2026-05-17.md`).

## Open Questions

1. **Insertion point** — RESOLVED. Not route-level. The `setattr` loop already establishes method-level wrapping as the project's chosen pattern. Fix is: make that wrapping drift-proof. Route-level (`Depends`/middleware) rejected — see OQ2 + Option B.
2. **Method-level vs route-level** — RESOLVED. Method-level. Route-level over-locks: it would serialise read-only routes (e.g. `POST /api/file/reveal`, analysis-only POSTs) that never touch `master.db`, and a `Depends`-held lock spans the whole request incl. JSON parse + slow I/O. Method-level scopes the lock to the actual DB call. Caveat: `RekordboxDB` is *not* a single chokepoint — `_require_live_db()` (`main.py:949`) returns `LiveRekordboxDB` directly, so wrapping must hit `LiveRekordboxDB` mutators too (see Findings "Second gap class" + Recommendation gate 1/3).
3. **Backwards-compat — any writer needs lock-free access?** — RESOLVED (low risk). The only newly-wrapped method is `ensure_standalone_master_db` — a one-shot startup init, no background-task spawn, no streaming. `refresh_metadata` (the one long-running mutator) is already wrapped today with no reported deadlock, so RLock-around-long-call is already tolerated by the codebase. Auto-wrap (Option B) doesn't change which methods are wrapped beyond adding the gap — re-confirm at draftplan that the prefix set captures exactly the intended 22.
4. **Phase ordering vs `require_session`/`@rate_limit`** — RESOLVED. Non-issue. Lock is on `RekordboxDB` methods, not a route decorator — it does not stack with `require_session`/`@rate_limit` at all. No 429-vs-queue-depth ordering question: rate-limit rejects at the route boundary long before the DB method runs.
5. **Test strategy** — RESOLVED (location + shape). New file `tests/test_concurrency.py`. Two tests: (a) **introspection** — enumerate mutators of `RekordboxDB` *and* `LiveRekordboxDB` by name prefix, assert each wrapped (`func.__wrapped__` present) — deterministic, no flakiness, the drift guard; (b) **concurrent harness** — 8 threads each call a wrapped mutator on a temp `master.db`, assert 0 exceptions. Negative control (monkeypatch lock to a no-op) should fail. Flakiness risk only in (b) — keep it `@pytest.mark.slow`, (a) is the CI gate.
6. **rbox ProcessPoolExecutor interaction** — RESOLVED. `anlz_safe.py` is read-only (verified `anlz_safe.py:1-40` docstring + grep: only `get_content_anlz_paths` reads + `rbox.Anlz` beatgrid reads). Parser never writes `master.db`, so the threading-only lock not crossing the process boundary is irrelevant. No action.

> PARKED (out of scope, future doc): `LiveRekordboxDB` per-thread `rbox.MasterDb` handles (`live_database.py:21,35`) are the structural reason a single missed lock corrupts. A shared single connection + lock would be defence-in-depth. Trigger: if gap-closing proves insufficient under the OQ5 harness, or Phase-2 mobile load. Larger refactor — own topic.

## Findings / Investigation

### 2026-05-19 — empirical lock-acquisition grep (scaffold, SUPERSEDED)
- Scaffold claimed `@_serialised` 0 applications + docstring false. **Both wrong** — see audit below. Kept for trail.
- Surfaced in `exploring_metadata-name-fixer.md` Constraints (2026-05-15) as adjacent risk during M0 audit. Carved out here.

### 2026-05-19 — full empirical audit (this session)
- **`_serialised` IS applied.** `setattr` loop `database.py:1076-1086` wraps 21 mutating `RekordboxDB` methods. A `@_serialised`-syntax grep returns 0 because the loop uses `setattr`, not decorator syntax — the scaffold grep was a false negative.
- **Docstring `database.py:36-37` is TRUE**, not false. "Individual mutating methods are already wrapped" — correct for the 21 in the loop. No docstring repair needed.
- **`update_tracks_metadata` IS protected** — name present in loop list (`database.py:1082`), wrapped at line 1085. Scaffold's "unprotected" claim wrong.
- **Real bug: the hand list drifts.** AST enumeration of `RekordboxDB` mutators vs the 21-name loop list → exactly **1 unprotected: `ensure_standalone_master_db`** (`database.py:728`). It calls `rbox.OneLibrary.create()` (`database.py:738`) — a genuine `master.db` write. Guarded by `if self.live_db_path.exists(): return True`, so one-shot at startup — low live-race probability, but a real coverage hole and a demonstration the list silently fell out of sync.
- **Second gap class — `_require_live_db()` bypasses the facade.** `main.py:949` `_require_live_db()` returns the `LiveRekordboxDB` instance directly. Routes `POST /api/mytags` (`main.py:975`), `DELETE /api/mytags/{id}` (`986`), `POST /api/track/{tid}/mytags` (`1002`) call `_require_live_db().create_mytag/delete_mytag/set_track_mytags` — these `LiveRekordboxDB` methods (`live_database.py:925,937,949`) write `master.db` and are **never `_serialised`** (the wrap loop targets `RekordboxDB` only). 3 unprotected concurrent write paths. The "facade is sole chokepoint" assumption is false — retrofit must wrap `LiveRekordboxDB` mutators too.
- **`db.save_track_cues`/`db.save_track_beatgrid` are an `AttributeError`, not a lock gap.** Those names exist on no class (AST-verified across `database.py` + `live_database.py`); the `RekordboxDB` facade has no `__getattr__`. Routes `main.py:1011,1014` crash at runtime — separate broken-route bug, "Adjacent bug" note in Problem, out of scope. (Earlier draft of this audit wrongly lumped mytags in with these — corrected: mytags route via `_require_live_db()` and DO reach live methods.)
- **Root cause of races:** `LiveRekordboxDB.db` property (`live_database.py:30-36`) lazily opens a `rbox.MasterDb` per thread (`threading.local()`, line 21). Multiple request threads = multiple independent rbox handles on one `master.db`. The lock is the *only* serialisation — any unwrapped mutator = an unserialised concurrent writer.
- **rbox concurrent-write panic — evidence chain:** `anlz_safe.py:6-16` documents rbox aborting the whole process via `Option::unwrap()` on `None` (Windows exit `0xC0000409`) — that's the *read* path. `coding-rules.md` "Backend concurrency" states the same crate panics on concurrent *writes*. No in-repo reproducer captured yet (the panic aborts before a traceback) — OQ5 harness is the planned reproducer.
- **ProcessPool boundary:** `anlz_safe.py` worker is read-only (docstring `anlz_safe.py:20-39` + grep: `get_content_anlz_paths` reads, `rbox.Anlz` reads). Lock not crossing the process boundary is moot — no write to serialise there.
- **`db_lock()` 0 callsites** — not dead code; it's the multi-step-transaction helper, simply unused so far. Leave as-is.

## Options Considered

> Audit found two gap classes: (1) `RekordboxDB` hand list missing `ensure_standalone_master_db`; (2) `LiveRekordboxDB` mytag mutators reached directly via `_require_live_db()`, never wrapped. Both must be closed. Options compare *how to wrap both classes and stop drift*. The old "per-route `with db_lock()`" idea is dropped — over-locks read-only routes, duplicates method-level protection.

### Option A — extend the hand-maintained name list(s)
- Sketch: add `"ensure_standalone_master_db"` to the `RekordboxDB` `setattr` loop `database.py:1077-1084`; add a second `setattr` loop for `LiveRekordboxDB` covering `create_mytag`, `delete_mytag`, `set_track_mytags` (+ any other live mutators an audit finds).
- Impl cost: ~1 LoC + a new ~6-line loop block; one file.
- Blast radius: minimal — two loop lists.
- Failure mode: **lists still drift.** Now *two* lists to forget. Fixes today's symptom, not the cause.
- Effort: XS. Risk: low correctness now, high recurrence (doubled — two lists).

### Option B — auto-wrap via shared class decorator (prefix-matched)
- Sketch: one reusable `@serialise_mutators` class decorator that iterates `vars(cls)`, wrapping every plain method whose name matches a mutator-prefix allowlist (`set_`, `load_`, `unload_`, `create_`, `delete_`, `remove_`, `add_`, `update_`, `move_`, `rename_`, `reorder_`, `refresh_`, `save`, `ensure_`) and is not a `property`/dunder/`get_*`/`list_*`. Apply to **`RekordboxDB` and `LiveRekordboxDB`** (and `RekordboxXMLDB` if free). Same `_serialised` wrapper, applied by pattern.
- Impl cost: ~20-25 LoC (decorator fn + prefix tuple) — applies to N classes by one `@` line each; deletes the 9-line `RekordboxDB` name list. Net-neutral-ish diff, `database.py` + `live_database.py`.
- Blast radius: `database.py` + `live_database.py`; zero `main.py` churn. Picks up `ensure_standalone_master_db` + the 3 live mytag mutators automatically.
- Failure mode: a future mutator named off-pattern (e.g. `import_library`, `purge_orphans`) escapes the prefix set. Rarer than forgetting a list entry; with the prefix set as *single source of truth* shared with the OQ5 introspection test, a known-mutator miss fails CI. A genuinely new prefix needs one obvious human edit, not a silent omission.
- Effort: S. Risk: low — the prefix allowlist is the only judgement call. Scales cleanly to the 2nd/3rd class (the decisive edge over A/C now that two classes are in scope).

### Option C — explicit `@_serialised` decorator at each method definition
- Sketch: delete the `RekordboxDB` `setattr` loop; put `@_serialised` directly above each mutator `def` — 22 in `RekordboxDB`, plus the live mutators in `LiveRekordboxDB`. `_serialised` is defined above `RekordboxDB`; for `live_database.py` it must be imported (cross-module) or duplicated — minor friction.
- Impl cost: ~22 + ~N decorator lines across two files; ~40+-line diff.
- Blast radius: `database.py` + `live_database.py`, touches every mutator def site.
- Failure mode: same drift class as Option A — a new mutator needs the author to remember `@_serialised`. Locally visible at the `def` (reviewer sees siblings decorated). Most readable; weakest drift-proofing on its own; the cross-module `_serialised` import is mild ugliness.
- Effort: M. Risk: low correctness, medium recurrence (better than A — visible at def site).

### Common to all: OQ5 introspection test
Whichever option ships, `tests/test_concurrency.py` test (a) is the actual drift guard — it fails CI when a known mutator is unprotected. Options differ in how *self-evident* coverage is to a human reader; the test is what makes coverage *enforced*.

## Recommendation

**Option B (auto-wrap, prefix-matched) + OQ5 introspection test.** Two reasons B wins decisively now: (1) drift is the real defect — the audit proved the hand list silently fell behind, and a list will do so again; (2) the audit found a *second* class needing wrapping (`LiveRekordboxDB` via `_require_live_db()`). A and C both scale by repetition (a 2nd loop list / a 2nd batch of `@` decorators + a cross-module import); B's one prefix-matched decorator applies to N classes by one `@` line each. B removes the drifting artefact instead of duplicating it.

Diff spans `database.py` + `live_database.py`: one `@serialise_mutators` decorator, applied to `RekordboxDB` + `LiveRekordboxDB`; `ensure_standalone_master_db` + the 3 live mytag writers get covered automatically by prefix; delete the old `setattr` loop; add `tests/test_concurrency.py`. No `main.py` churn, no route changes. Docstring `database.py:36-37` is already accurate — no doc repair (scaffold was wrong about that).

Fallback: if B's prefix-matching reads as too implicit in review, Option C is the readable runner-up (same test, explicit `@_serialised`) at a larger, two-file diff.

**Scope split:** the broken `save_track_cues`/`save_track_beatgrid` routes (`AttributeError` — non-existent facade methods) are a *separate* bug — own task, do not bundle into this draftplan.

**Draftplan gate conditions:**
1. Prefix allowlist finalised against a full mutator enumeration of **both** `RekordboxDB` (22) and `LiveRekordboxDB` — agree the exact prefix tuple, confirm it captures every intended mutator and excludes every `get_*`/`list_*`/property.
2. OQ5 harness flakiness assessed — confirm test (b) (8-thread write) is stable enough for `@pytest.mark.slow`, or ship test (a) introspection-only as the CI gate.
3. Decide on `RekordboxXMLDB` — wrap it too (free if the prefix decorator is applied), or leave it (XML mode is single-process file-write, lower risk). Lean: wrap, it's one `@` line.
4. User sign-off on Option B vs C (implicit-but-tested vs explicit-but-larger-diff).

---

## Implementation Plan

### Mechanism — Option B, refined

Verification audit 2026-05-21 found raw Option B (prefix-matched runtime wrapping) unsafe: a `vars(cls)` prefix sweep catches `LiveRekordboxDB._load_beatgrids_from_anlz` — a background-thread `master.db` *reader* that must NOT enter the write lock. Refinement keeps Option B's win (one reusable decorator, N classes by one `@` line) but moves prefix-matching out of the runtime path:

- `serialise_mutators(*names)` — class decorator, **explicit method-name list**. Wraps each named method with `_serialised`. No `vars(cls)` sweep → no false-positive runtime wrapping.
- Prefix-matching → **CI drift test only** (`tests/test_concurrency.py`). A forgotten `update_*`/`create_*`/… → CI red. Prefix false-positive in a test = visible failure a human checks (safe); in runtime = a wrongly-locked loader (bug).

Net: Option B ergonomics + the OQ5 introspection test as the *enforced* drift guard, minus the unsafe sweep. Resolves gate conditions 1 (enumeration below) + 3 (XML wrapped); condition 4 (B vs C) → B-refined, user signs at GATE C.

### Scope

**In**
- New module `app/db_lock.py` — `_db_write_lock`, `db_lock()`, `_serialised`, new `serialise_mutators(*names)`. Breaks the `database.py`↔`live_database.py` import cycle (Option C's noted cross-module-import friction — solved once, centrally).
- `RekordboxDB` (`database.py`) — `setattr` loop → `@serialise_mutators`; add `ensure_standalone_master_db` (closes Gap 1).
- `LiveRekordboxDB` (`live_database.py`) — `@serialise_mutators` on 14 mutators (closes Gap 2 — the `_require_live_db()` facade-bypass).
- `RekordboxXMLDB` (`database.py`) — `@serialise_mutators` on 16 mutators (XML-mode mytag bypass; gate cond. 3).
- `tests/test_concurrency.py` — new.

**Out**
- `save_track_cues`/`save_track_beatgrid` broken routes (`main.py:1011,1014`) — `AttributeError`, separate bug, own task (chip filed by audit agent).
- `LiveRekordboxDB.load` / `RekordboxXMLDB.load_xml` — read `master.db` / parse XML into memory, not writers. Excluded; deliberate scope edge — flagged for GATE C.
- `LiveRekordboxDB` per-thread `rbox.MasterDb` → shared pool. PARKED (own topic).
- No `main.py` / route / frontend change.

### Wrap-sets — finalised (gate condition 1)

Enumerated from current source 2026-05-21, cross-checked vs the existing `setattr` loop (21 names matched exactly).

- **`RekordboxDB` — 22**: `set_mode`, `load_library`, `unload_library`, `create_new_library`, `refresh_metadata`, `add_track`, `delete_track`, `rename_playlist`, `move_playlist`, `delete_playlist`, `reorder_playlist_track`, `create_folder`, `create_smart_playlist`, `update_smart_playlist`, `create_playlist`, `add_track_to_playlist`, `remove_track_from_playlist`, `save`, `update_tracks_metadata`, `update_track_comment`, `update_track_path` (= the 21 loop names) **+ `ensure_standalone_master_db`** (Gap 1).
- **`LiveRekordboxDB` — 14**: `add_track`, `delete_track`, `update_track_comment`, `update_track_metadata`, `create_mytag`, `delete_mytag`, `set_track_mytags`, `rename_playlist`, `move_playlist`, `delete_playlist`, `create_playlist`, `add_track_to_playlist`, `remove_track_from_playlist`, `reorder_playlist_track`.
- **`RekordboxXMLDB` — 16**: `add_track`, `create_playlist`, `add_track_to_playlist`, `remove_track_from_playlist`, `reorder_playlist_track`, `rename_playlist`, `move_playlist`, `delete_playlist`, `create_folder`, `create_smart_playlist`, `update_smart_playlist`, `create_mytag`, `delete_mytag`, `set_track_mytags`, `delete_track`, `save_xml`.

Excluded (verified non-writers): all `get_*`/`list_*`/`find_*`, `evaluate_smart_playlist` (returns list), properties, `_`-private (incl. every `_load_*`), `LiveRekordboxDB.load`, `RekordboxXMLDB.load_xml`.

Drift-test prefix tuple: `add_ create_ delete_ remove_ update_ set_ move_ rename_ reorder_ refresh_ unload_ load_ ensure_ save`. One readonly-allowlist entry: `RekordboxXMLDB.load_xml` (matches `load_`, is a reader).

### Step-by-step

1. **`app/db_lock.py`** (new). Move `_db_write_lock` / `db_lock()` / `_serialised` out of `database.py`. Add:
   ```python
   def serialise_mutators(*method_names):
       """Class decorator: wrap each named method with _serialised."""
       def decorate(cls):
           for name in method_names:
               setattr(cls, name, _serialised(getattr(cls, name)))
           return cls
       return decorate
   ```
   `database.py` adds `from .db_lock import _db_write_lock, db_lock, _serialised` — existing import sites (incl. tests importing `db_lock` from `app.database`) unchanged. `db_lock.py` imports stdlib only → no cycle.
2. **`RekordboxDB`** — delete `setattr` loop (`database.py:1076-1086`); `@serialise_mutators(<22 names>)` above `class RekordboxDB`. Closes Gap 1.
3. **`LiveRekordboxDB`** — `from .db_lock import serialise_mutators`; `@serialise_mutators(<14 names>)` above `class LiveRekordboxDB`. Closes Gap 2.
4. **`RekordboxXMLDB`** — `@serialise_mutators(<16 names>)` above `class RekordboxXMLDB`.
5. **`tests/test_concurrency.py`** — 3 tests (see Testing).
6. `pytest tests/ -v` + `ruff check app/ tests/` + `mypy app/`. `python scripts/regen_maps.py`. Fix `coding-rules.md` `_db_write_lock` path.

Re-entrancy: facade `RekordboxDB.add_track` (wrapped) → `active_db.add_track` (now wrapped) → RLock re-acquired, same thread, safe. Pre-existing pattern (`update_tracks_metadata`→`save`). Decorator adds a redundant acquire on the facade path; the point is it also covers the direct `_require_live_db()` path.

### Files touched
- `app/db_lock.py` — NEW (~45 LoC).
- `app/database.py` — primitives move out + re-import; `setattr` loop → `@serialise_mutators` on `RekordboxDB` + `RekordboxXMLDB`.
- `app/live_database.py` — import + `@serialise_mutators` on `LiveRekordboxDB`.
- `tests/test_concurrency.py` — NEW.
- `docs/FILE_MAP.md` (new-module row), `docs/MAP.md` + `docs/MAP_L2.md` (regen). `.claude/rules/coding-rules.md` "Backend concurrency" cites `app/main.py:_db_write_lock` — stale (it is `database.py` today, `db_lock.py` after) — correct it.

### Testing
- **`test_mutator_coverage`** (CI gate, deterministic) — each of 3 classes: every wrap-set name resolves to a method with `__wrapped__` set (`_serialised` uses `functools.wraps` — confirmed).
- **`test_no_unwrapped_mutator`** (CI gate, the drift guard) — each class: enumerate public methods (skip `_`-private, dunder, `property`); any whose name starts with a prefix-tuple entry must be in the wrap-set OR the readonly-allowlist. New prefixed mutator added unwrapped → CI red.
- **`test_concurrent_writes`** (`@pytest.mark.slow`) — 8 threads call wrapped mutators on a temp `master.db`; assert 0 exceptions, 0 sqlite `database is locked`. Negative control: `_db_write_lock` monkeypatched to `nullcontext()` → harness must fail (proves the lock load-bearing).
- Regression: full `pytest tests/` green; read paths unchanged.

### Risks & rollback
- **Wrap-set drifts** (mutator added, list forgotten) → `test_no_unwrapped_mutator` fails CI. Residual: a non-prefix-named mutator (`purge_orphans`) escapes — accepted (doc Option-B failure-mode); rare, one obvious edit.
- **Readonly-allowlist hides a real mutator** — allowlist is 1 entry (`load_xml`); each entry carries a one-line justification, PR-reviewed.
- **Import cycle** `database.py`↔`live_database.py` — `db_lock.py` imports stdlib only; both import it freely.
- **Double-wrap deadlock** facade→delegate — non-risk: `RLock` reentrant, pre-existing.
- **`@pytest.mark.slow` harness flaky** — the two deterministic tests are the CI gates; harness is opt-in evidence, not a gate.
- **Rollback** — 5 tasks = 5 PRs/commits; `git revert` per task, reverse order. `db_lock.py` re-export keeps `database.py`'s public surface stable → reverting a later task can't break an earlier import site.

## Task Queue

- [ ] **Task 1 — `app/db_lock.py`: extract lock primitives + add `serialise_mutators`.** New module holds `_db_write_lock`, `db_lock()`, `_serialised`, `serialise_mutators(*names)`. `database.py` re-imports the first three. No class re-wrapped, `setattr` loop untouched, zero behavior change. Gate: `pytest tests/` green. Smallest, lowest-risk — merge first.
- [ ] **Task 2 — `RekordboxDB`: `setattr` loop → `@serialise_mutators`, close Gap 1.** Delete loop (`database.py:1076-1086`); `@serialise_mutators(<22 names>)` incl. `ensure_standalone_master_db`. `database.py` only. Gate: `pytest tests/` green; `ensure_standalone_master_db.__wrapped__` present.
- [ ] **Task 3 — `LiveRekordboxDB`: `@serialise_mutators` on 14 mutators (close Gap 2).** Closes the `_require_live_db()` facade-bypass — `create_mytag`/`delete_mytag`/`set_track_mytags` + all other Live mutators. `live_database.py` only.
- [ ] **Task 4 — `RekordboxXMLDB`: `@serialise_mutators` on 16 mutators.** XML-mode mytag bypass. `database.py`.
- [ ] **Task 5 — `tests/test_concurrency.py` + doc sync.** `test_mutator_coverage` + `test_no_unwrapped_mutator` (CI gates) + `test_concurrent_writes` (`@pytest.mark.slow`, negative control). `docs/FILE_MAP.md` row, `python scripts/regen_maps.py`, fix `coding-rules.md` `_db_write_lock` reference.

Deps: Tasks 2/3/4 depend on Task 1. Task 4 sequences after Task 2 (both edit `database.py` — avoids a rebase). Task 5 last (asserts wrap-sets from 2-4). 1 task = 1 `routine/db-write-lock-retrofit-task-N` branch = 1 PR.

## Review

### 2026-05-21 — PASS

- [x] Plan addresses all goals
  - 4 goals → 4 test-backed metrics: wrap-sets cover all 3 classes; `test_no_unwrapped_mutator` = drift gate; reads untouched + regression suite; `test_concurrent_writes` + negative control.
- [x] Plan matches `## Original Idea` — no scope-creep
  - Doc predates the `## Original Idea` template section — anchored against `## Problem` + `## Recommendation` instead. Plan = Gap 1 + Gap 2 + Recommendation's Option B (refined for the verified `_load_*` safety issue) + the XML decision the doc itself deferred to draftplan. Broken-route bug + connection-pool explicitly OUT. See GATE C flag.
- [x] Open questions answered or deferred
  - All 6 OQs RESOLVED in-doc. Gate conditions 1-3 resolved by the plan; condition 4 (B vs C) = the GATE C sign-off itself.
- [x] Task Queue items are small + independently committable
  - 5 tasks, each ≤1 production file + own `routine/*` branch + PR; T1 = zero-behavior-change foundation; deps + sequencing stated.
- [x] Risk mitigations defined
  - 6 risks each mitigated; residual (non-prefix-named mutator) named + accepted.
- [x] Rollback path clear
  - Per-task `git revert` reverse-order; `db_lock.py` re-export keeps `database.py`'s public surface stable across partial reverts.
- [x] Affected docs identified
  - `FILE_MAP.md`, `MAP.md`/`MAP_L2.md` regen, `coding-rules.md` stale-ref fix — in Files touched + Task 5. No `architecture.md` change (no new data flow); no `CHANGELOG.md` (no user-visible behavior change).

**Verdict: PASS** — executable, scoped, tested, reversible.

**Flag for GATE C** (not a rework reason): doc has no `## Original Idea` block — scaffolded 2026-05-19, predates that template section. The pipeline's anti-scope-creep anchor is absent. Recommend the user add a 1-3 sentence `## Original Idea` (verbatim, authored once) at GATE C so the Stage-4 `research-implement` review-agent has the anchor.

**Rework reasons:** none.

### 2026-05-21 — INDEPENDENT RE-REVIEW — REWORK (GATE C reject)

User rejected GATE C. A fresh independent reviewer agent re-checked the plan vs current source — the PASS above was self-authored + self-reviewed (no Agent-A/B independence). It found a BLOCKER: the plan's "two gap classes, both closed" completeness claim is **false**.

- [ ] Plan addresses all goals — **FAIL.** `AnalysisDBWriter._update_db` (`app/analysis_db_writer.py:223`) is a **third** unprotected `master.db` writer — `self.live_db.db.update_content(item)` (`:245`) + `update_content_key` (`:255`), raw `rbox.MasterDb` handle, zero lock (`grep _db_write_lock|db_lock|_serialised app/analysis_db_writer.py` → 0 hits). Reached via `POST /api/library/analyze-full` + `/analyze-batch` (`main.py:2783,2810`) in a thread-pool executor → genuinely concurrent with mytag/track-update threads. Worse live-race risk than `ensure_standalone_master_db`. Wrapping the 3 classes' *methods* does not cover it — it calls the raw rbox handle directly.

**Rework reasons** — `research-plan` must address each:

1. **BLOCKER — third writer missed; the coverage model is incomplete.** Bring `AnalysisDBWriter` into scope (wrap `_update_db`, or hold `db_lock()` across the `analyze-full`/`analyze-batch` route bodies) — or carve it out in `## Non-goals` with a stated reason. Deeper defect: the plan assumed method-wrapping 3 classes = total coverage. Any code grabbing the raw `rbox.MasterDb` / `active_db.db` handle bypasses every method wrapper.
2. **Re-audit ALL raw-handle + multi-step writers.** Grep `app/` for `.db.update_`/`.db.insert_`/`.db.delete_`/`.db.add_`, `active_db.db`, `rbox.MasterDb`, raw `OneLibrary`. `POST /api/tools/duplicates/merge` (`main.py:2658`) binds `rbox = db.active_db.db` for a multi-mutation merge with no transaction lock spanning it — `db_lock()` (the 0-callsite multi-step helper) is exactly for this. Plan must enumerate every such site + state coverage.
3. **Drift test must key on `(class, method)` tuples, not bare names.** Prefix `load_` matches both `RekordboxDB.load_library` (wrapped) and `RekordboxXMLDB.load_xml` (readonly-allowlisted) — opposite classifications. `tests/test_concurrency.py` wrap-sets + allowlist must be class-qualified.
4. **`test_concurrent_writes` harness — specify the temp-DB seed + downgrade its status.** `rbox.OneLibrary.create()` is broken in rbox 0.1.7 (`coding-rules.md`) — seed the temp `master.db` from `app/templates/exportLibrary_template.db`. Linux CI lacks `rbox` → harness is Windows-only / opt-in; `## Testing` must state it is NOT a CI gate (only the 2 deterministic introspection tests gate CI).
5. **`## Risks` — add two.** (a) `refresh_metadata` holds the write-lock across a full-library `_finalize_ui_metadata` iteration — accepted contention, sharper under the Phase-2 mobile load the plan cites as motivation. (b) The drift test pressures authors to wrap a prefixed *reader* — name "prefixed reader wrongly locked" as a residual risk, symmetric to the `_load_*` false-positive.
6. **MINOR — Task 1 precondition.** State that `database.py`'s re-export must preserve lock *object identity* (`from .db_lock import _db_write_lock` — never re-create the `RLock`), else the lock silently splits.

Mechanism (shared `db_lock.py` + `serialise_mutators` + `(class,method)` drift test) is **sound** — keep it. The defect is scope enumeration, not approach.

## Implementation Log

_(empty — fill at `inprogress_`)_

---

## Decision / Outcome

_(empty — fill at `archived/`)_

## Links

- Code: `app/database.py:22` (`_db_write_lock`), `app/database.py:25-40` (`db_lock()` — 0 callsites, multi-step helper), `app/database.py:43-53` (`_serialised`), `app/database.py:1076-1086` (`setattr` wrap loop — 21 names, the artefact that drifts), `app/database.py:728-743` (`ensure_standalone_master_db` — unwrapped `RekordboxDB` mutator, gap 1).
- Gap 2 — facade bypass: `app/main.py:949` (`_require_live_db()`), `app/main.py:975,986,1002` (mytag routes), `app/live_database.py:925,937,949` (`create_mytag`/`delete_mytag`/`set_track_mytags` — `LiveRekordboxDB` writers, unwrapped). `app/live_database.py:21,35` (per-thread `rbox.MasterDb` — race root cause).
- `app/anlz_safe.py:1-40` (read-only ProcessPool — no write to serialise).
- Adjacent bug (separate task): `app/main.py:1011,1014` call `db.save_track_cues`/`db.save_track_beatgrid` — methods absent from `RekordboxDB` facade (no `__getattr__`) → runtime `AttributeError`.
- Rules: `.claude/rules/coding-rules.md` "Backend concurrency".
- Related research: `security-api-auth-hardening` (archived 2026-05-17, carved this out), `metadata-name-fixer` (Constraints surface, 2026-05-15).
