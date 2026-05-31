---
slug: db-write-lock-retrofit
title: Close _db_write_lock coverage gaps on master.db write methods
owner: tb
created: 2026-05-19
last_updated: 2026-05-31
tags: [backend, concurrency, rbox, security, follow-up]
related: [security-api-auth-hardening]
ai_tasks: false
---

# Close _db_write_lock coverage gaps on master.db write methods

## Lifecycle

- 2026-05-19 — `research/idea_` — scaffolded from auth-hardening adjacent finding (metadata-name-fixer Constraints)
- 2026-05-19 — `research/idea_` — deep exploration toward exploring_-ready (empirical audit)
- 2026-05-28 — `research/drafting_` — Stage 1 worker formally complete (Prior Art + Research Plan retrofitted to match current template; content was already at exploring_ depth)
- 2026-05-28 — `research/ideagate_` — Stage 1 verifier PASS, awaiting GATE A
- 2026-05-29 — `research/exploring_` — GATE A PASSED by user; Option B (auto-wrap, prefix-matched) committed in Recommendation; advanced for Stage 2 wave-2 verifier
- 2026-05-29 — `research/exploring_` — wave-2 verification: citation refresh (5 stale line-anchors fixed) + Adversarial + Research Verifier → **GAPS**. Found THIRD gap class: `AnalysisDBWriter` rbox-direct `master.db` write (`update_content`/`update_content_key`) uncovered by any class decorator; OQ5 drift guard circular. Stays `exploring_` for wave-2 round 2.
- 2026-05-31 — `research/evaluated_` — wave-2 round-2: all 3 GAPS closed (AnalysisDBWriter → wrap-at-callsite in-scope; drift guard → prefix-independent AST write-sink detection + `KNOWN_CALLSITE_PROTECTED` manifest; Goal-1 metric re-stated). Research Verifier PASS round 2. Option B + callsite-lock recommendation stands.
- 2026-05-31 — `implement/draftplan_` — planning started (research-plan routine)
- 2026-05-31 — `implement/review_` — plan filled (Impl Plan + Threat + Migration N/A + Perf + API/UX none + Telemetry + 9-row Test Plan + 5-task queue; XMLDB excluded, import-cycle risk flagged); Plan-Reviewer next
- 2026-05-31 — `implement/approvalgate_` — Plan-Reviewer PASS (all 14 boxes, 0 rework; verified AST scope complete + import-cycle/mytag/AnalysisDBWriter handling); mockup + Approval Summary ready; awaiting user `/approve` or `/reject`
- 2026-05-31 — `implement/accepted_` — approved by user (batch approve alongside library-format-converter)

## AI Tasks

<!--
Opt-in queue for remote AI routines. Activate by setting `ai_tasks: true` in frontmatter.
Each item: 1 concrete sub-task. Routine processes 1/run, ticks done, commits via PR.
-->

- [ ] _(none yet — flag stays false until Open Questions firm up)_

---

## Problem

> **2026-05-19 audit overturned the scaffold premise.** `_serialised` IS applied — `setattr` loop at `database.py:1076-1086` wraps 21 `RekordboxDB` methods. Scaffold's "0 applications / dead decorator / false docstring / `update_tracks_metadata` unprotected" findings all wrong. Real, smaller problem below.

`_serialised` (`app/database.py:43-53`) wraps mutating `RekordboxDB` methods via a `setattr` loop — but the loop is a **hand-maintained name list** (`database.py:1077-1084`). The list drifts. AST enumeration of `RekordboxDB` finds **1 mutator missing**: `ensure_standalone_master_db` (`database.py:728`) — calls `rbox.OneLibrary.create()`, writes `master.db`, unwrapped. Low live-race risk (one-shot, `if path.exists(): return` guard) but a real coverage hole and proof the list-maintenance pattern fails silently.

The structural defect is the **list itself**: any future `RekordboxDB` mutator added without editing `database.py:1077-1084` is a silent unprotected writer. Concurrent writes corrupt because `LiveRekordboxDB` opens a **per-thread** `rbox.MasterDb` handle (`live_database.py:21,35` — `threading.local()`): multiple FastAPI request threads = multiple independent rbox/SQLite handles on one file. The lock is the only serialisation. rbox 0.1.7 panics on concurrent writes (`coding-rules.md`). Cost of inaction: a missed mutator → silent corruption + sidecar crash, risk rising once Phase-2 mobile-companion adds concurrent edit load.

**Second, bigger hole — the facade is NOT the sole chokepoint.** Routes `POST /api/mytags`, `DELETE /api/mytags/{id}`, `POST /api/track/{tid}/mytags` call `_require_live_db().create_mytag / delete_mytag / set_track_mytags` (`main.py:975,986,1002`) — they reach `LiveRekordboxDB` **directly**, bypassing `RekordboxDB` and therefore its `_serialised` wrapping entirely. `LiveRekordboxDB.create_mytag/delete_mytag/set_track_mytags` (`live_database.py:925,937,949`) write `master.db` **with no lock at all**. Any retrofit must wrap `LiveRekordboxDB` mutators too, or `_require_live_db()` stays a permanent unprotected write path.

> **Adjacent bug, NOT lock-scope** (separate fix): routes `POST /api/track/cues/save`, `/api/track/grid/save` (`main.py:1011,1014`) call `db.save_track_cues` / `db.save_track_beatgrid` — **neither method exists on the `RekordboxDB` facade** (no `__getattr__`). These two routes `AttributeError` at runtime. Out of scope here; flagged for its own task. (The mytag routes are *not* broken — they call `_require_live_db()`, see above.)

## Goals / Non-goals

**Goals**
- Every `master.db` write path serialised under `_db_write_lock` — covering (i) mutating methods on `RekordboxDB` + `LiveRekordboxDB` (auto-wrapped by `@serialise_mutators`, Option B), and (ii) rbox-direct writers that bypass both facades (`AnalysisDBWriter._update_db`'s `update_content`/`update_content_key`), serialised by an explicit lock acquire at the callsite. Metric: a CI introspection test enumerates writers by **AST write-sink detection** (methods calling `<recv>.db.<rbox-write>`, `self._try_call`, or module-level `rbox.*.create`) across `database.py` + `live_database.py` + `analysis_db_writer.py` — NOT by name prefix — and asserts each flagged writer is either `__wrapped__` or listed in a small `KNOWN_CALLSITE_PROTECTED` manifest. Count of flagged-but-unprotected writers = 0. Cannot green-light an uncovered rbox-direct writer (AnalysisDBWriter), since detection is independent of the decorator's prefix allowlist.
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

## Idea Verification

Stage 1 Verifier. Dated entries, append-only.

### 2026-05-28 — PASS
- **Intent**: scaffold premise (every method unprotected) overturned by 2026-05-19 audit; real scope (1 RekordboxDB miss + 3 LiveRekordboxDB bypasses + drift-proofing) fully consistent with the auth-hardening adjacent-finding from which it was carved. No scope-creep: PARKED note keeps per-thread-handle refactor out, "Adjacent bug" note keeps the save_track_cues AttributeError out.
- **Prior-art**: 2 carve-out anchors cited verbatim — `security-api-auth-hardening` (parent), `metadata-name-fixer` (sibling). No duplication.
- **Plan**: all 6 OQs RESOLVED inline (audit produced answers), Options Considered + Recommendation already drafted with explicit draftplan-gate conditions (prefix-set finalise, harness flakiness, XMLDB inclusion, Option B-vs-C). User GATE A is the next blocker — content is exploring_-ready.

---

> ⛔ GATE A — user `/gate-pass` (→ `exploring_`) or `/gate-reject` (→ `drafting_`).
> Note: the empirical audit + Options + Recommendation already cover most of Stage 2's deliverables. GATE A pass is expected to advance straight through exploring_ verifier on the first cycle.

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

### 2026-05-29 — wave-2 verification (line-ref refresh + THIRD gap class)
- **Line-ref refresh** (code shifted down since 2026-05-19 audit; every symbol + claim unchanged, anchors corrected, all re-Read this session):
  - `_require_live_db()` → `main.py:1053` (was 949); returns `db.active_db` (`main.py:1057`), which is the `LiveRekordboxDB` instance in live mode.
  - mytag route calls → `main.py:1079` (create), `1090` (delete), `1106` (set); routes `@1073 / 1087 / 1103`.
  - `LiveRekordboxDB` mytag defs → `live_database.py:1025 / 1037 / 1049` (was 925/937/949).
  - per-thread handle → `live_database.py:27` (`threading.local()`), `41` (`rbox.MasterDb(...)`), `36-37` (`db` property).
  - broken cue/grid routes → `main.py:1116 / 1121` call `db.save_track_cues / save_track_beatgrid`; still absent on every class → `AttributeError` stands (separate task).
- **THIRD gap class — `AnalysisDBWriter` writes `master.db` OUTSIDE both facades.** `LiveRekordboxDB.get_analysis_writer()` (`live_database.py:1128`) returns `AnalysisDBWriter`. `AnalysisDBWriter._update_db` (`analysis_db_writer.py:223-264`, called from `analyze_and_save` at `:134`) writes `djmdContent` via `self.live_db.db.update_content(item)` (`:245`) + `self.live_db.db.update_content_key(...)` (`:255`) — direct `rbox.MasterDb` calls on the per-thread handle, **no `_db_write_lock`**. These are methods on the rbox handle, NOT on `RekordboxDB`/`LiveRekordboxDB`, so **no class-level wrapping (Option A/B/C) can ever cover them** — and `get_analysis_writer` is `get_`-prefixed, explicitly excluded by Option B's allowlist. Goal-1 metric ("unwrapped mutators = 0" by class introspection) reports green while this path stays unprotected = false pass. The DB write runs **in-process** (the `ProcessPoolExecutor` at `analysis_db_writer.py:64` parallelises analysis, not the write), so an RLock CAN serialise it — but only if the retrofit locks `analyze_and_save`/`_update_db` at the callsite, not via a decorator on the two DB classes.
- Confidence: high (every claim re-Read this session at the cited line).

### 2026-05-31 — wave-2 round-2: gap closures (3 verifier GAPS resolved)

All cites re-Read this session. Gap-1/2/3 from `## Research Verification` 2026-05-29 closed below.

**Gap 1 — AnalysisDBWriter scope: DECIDED → wrap at callsite (option a), NOT a new doc.**
- `AnalysisDBWriter._update_db` (`analysis_db_writer.py:223-264`) writes `master.db` via `self.live_db.db.update_content(item)` (`:245`) + `self.live_db.db.update_content_key(...)` (`:255`) — calls on the per-thread `rbox.MasterDb` handle, not methods on `RekordboxDB`/`LiveRekordboxDB`. No class decorator (Option B) can reach them. `get_analysis_writer` (`live_database.py:1128`) is `get_`-prefixed → excluded from Option B allowlist.
- **In-process confirmed (stronger than verifier stated).** `ProcessPoolExecutor` at `analysis_db_writer.py:64` (`_get_executor`) is **never called** — zero `.submit()`, `_get_executor` zero callers. Vestigial. `run_full_analysis` (`:119`) + `_update_db` (`:134` call) run synchronously in the same thread.
- Both routes dispatch in-process: `analyze_track_full` → `loop.run_in_executor(None, writer.analyze_and_save, ...)` (`main.py:3086`, default ThreadPool); `analyze_batch` → plain `for ... in writer.analyze_batch(...)` (`main.py:3126`, event-loop thread). `threading.RLock` serialises both vs facade/live mutators on other request threads.
- **Decision: wrap at callsite, in scope.** Acquire `_db_write_lock` around the write in `_update_db` (`:244-258`), or via `db_lock()` ctx-mgr (`database.py:25-40`, importable, 0 prior callsites — its intended use). RLock reentrancy safe if a wrapped live-mutator is called inside. NOT parked: same `master.db`, same race, higher write volume (per analysed track) than mytag routes — parking leaves the highest-volume writer unprotected + re-opens the false-green Goal-1 closes. ~2 LoC, one file.

**Gap 2 — drift guard redesign: AST write-sink detection, prefix-set-independent.**
- Root defect: old OQ5 test (a) shared the decorator's prefix allowlist → off-prefix writer passes BOTH. New guard detects *actual rbox write calls*, never consulting the prefix set.
- **Design — `test_concurrency.py::test_no_unprotected_master_db_writer`:**
  1. AST-parse `app/database.py`, `app/live_database.py`, `app/analysis_db_writer.py` (grep-seeded module list, asserted in test).
  2. For each method, walk body. Flag as **writer** if it contains any write-sink (none name-prefix-keyed):
     - `<recv>.db.<attr>(...)` where `<attr>` ∈ rbox write-API set (`update_content*`, `create_content*`, `create_playlist*`, `delete_playlist*`, `update_content_artist/genre/album/key`, `commit`, …) — catches `_update_db` (`:245`/`:255`), `add_track`@828, `update_track_metadata`@909, `delete_playlist`@1213, `create_playlist`@1223, `add_track_to_playlist`@1245, `remove_track_from_playlist`@1254 (AST-verified this session).
     - `self._try_call([...], ...)` — dynamic dispatch helper (`live_database.py:1012`, `getattr(self.db, name)()`). Catches `create_mytag`@1025, `delete_mytag`@1037, `set_track_mytags`@1049 (reach rbox indirectly, no literal `.db.<write>`).
     - module-level `rbox.<Class>.<create|...>(...)` — catches `ensure_standalone_master_db`@728 (`rbox.OneLibrary.create`@738).
  3. For each flagged writer assert protected: `getattr(method, "__wrapped__", None)` set (Option B) **or** name in explicit `KNOWN_CALLSITE_PROTECTED` manifest (callsite-locked, e.g. `AnalysisDBWriter._update_db`). Else flagged-but-unprotected = CI fail.
- Non-circular: detection key = "calls a rbox write sink", orthogonal to decorator prefix logic. Future `commit`/`flush`/`import_library` writing rbox is flagged the instant it touches a sink. Manual surface = small `KNOWN_CALLSITE_PROTECTED` + the rbox-write-API set (grow when rbox adds APIs, itself diffable).
- Edge: `_try_call` rule may over-flag a read-only `_try_call` (none today — all write). Fails safe (toward protection), unlike old false-green.

**Gap 3 — Goal 1 re-stated.** See `## Goals / Non-goals` revised Goal-1 bullet — metric now keyed on AST write-sink detection across all three modules + callsite-protected manifest, so a rbox-direct writer (AnalysisDBWriter) cannot green while unprotected.

**Stale-cite note:** `## Links` block still shows pre-2026-05-29 anchors (`live_database.py:21,35`, mytag `:925,937,949`) — symbol+claim correct, refresh to `:27/:41` + `:1025/1037/1049` at draftplan (non-blocking).
- **Confidence:** high (AST walk + grep + every cite re-Read this session).

## Adversarial Findings

### 2026-05-29 — devil's-advocate pass on Option B
- **Coverage claim false on arrival.** The `AnalysisDBWriter` write path (Findings 2026-05-29) is an unprotected `master.db` writer reached via `get_analysis_writer` (`live_database.py:1128`), excluded by the `get_` prefix and not a method on either wrapped class. Higher concurrent-write volume than the mytag routes (runs per analysed track). Refs Goal 1, Recommendation 2026-05-29.
- **Drift guard is circular.** OQ5 introspection test (a) shares the prefix set with the `@serialise_mutators` decorator. A mutator named off-prefix (a future `commit`/`flush`/`import_*`, or the rbox-direct writes above) passes BOTH test and decorator. The guard catches only a known-prefix method that lost its `@` — not the real drift class (new name shape). Refs OQ5 (2026-05-19), Option B failure-mode.
- **`vars(cls)` excludes inherited.** `RekordboxDB` / `LiveRekordboxDB` / `RekordboxXMLDB` are independent (no shared base — `database.py:55`, `live_database.py:24`), so no double-wrap; but `RekordboxXMLDB` (gate-condition 3) is a genuine third surface needing its own `@`, not "free". Refs Recommendation gate 3.
- **RLock reentrancy is thread-local only.** `LiveRekordboxDB.load()` (`live_database.py:44`) spawns a daemon beatgrid-loader thread (`_start_beatgrid_background_load` at `:94`). A wrapped mutator that offloads work to another thread which then calls a wrapped mutator would NOT reenter (different thread) → deadlock. Currently read-only so latent, but OQ3's "RLock makes nesting safe" is unqualified. Refs OQ3 (2026-05-19).

## Citation Quality

### 2026-05-29 — PASS-with-refresh
- PASS (line-accurate, verified): `database.py:22, 25-40, 43-53, 728, 738, 1076-1086` (loop = exactly 21 names; `ensure_standalone_master_db` genuinely absent), `database.py:36-37` docstring accurate, `anlz_safe.py:1-40` read-only, `grep -cE '@app\.(post|put|patch|delete)' app/main.py` = 85, no `__getattr__` on `RekordboxDB`.
- FAIL→refreshed (stale line only — symbol + claim correct): the 5 `main.py` / `live_database.py` refs, corrected in Findings 2026-05-29 (`_require_live_db`, mytag routes, live mytag defs, per-thread handle, cue/grid routes). Code shifted ~62-104 lines (main.py) / ~100-124 (live_database.py). No substantive claim was false.
- Verdict: all claims substantively accurate; anchors refreshed.

## Research Verification

### 2026-05-29 — GAPS
- OQ1–OQ6 each have ≥1 Finding: yes. Citation Quality: PASS (after refresh).
- **GAP (blocking):** the `AnalysisDBWriter` direct-rbox write path (Findings + Adversarial 2026-05-29) is a real unprotected `master.db` writer that the chosen Option B (class-level prefix decorator) structurally cannot cover — the writes are `rbox.MasterDb` calls (`update_content` / `update_content_key`), not methods on `RekordboxDB`/`LiveRekordboxDB`. Goal-1 metric would green while this path stays unprotected.
- **GAP (design):** OQ5 drift guard is circular (shares prefix set with the decorator) — cannot catch off-prefix mutators.
- Required before `evaluated_`: (1) decide scope — wrap `AnalysisDBWriter.analyze_and_save`/`_update_db` explicitly at the callsite (lock acquire, not class decorator), or PARK analysis-write serialisation as its own doc; (2) redesign the drift guard to enumerate writers by AST / actual-write detection, not by the same prefix set the decorator uses; (3) re-state Goal 1 so the metric cannot green-light an uncovered rbox-direct writer.
- Verdict: **GAPS** — doc stays `exploring_`. Next explore wave (or user) resolves the 3 items above.

### 2026-05-31 — PASS (round 2)
- All 3 GAPS from 2026-05-29 closed by wave-2 round-2 (Findings 2026-05-31), every cite re-Read this session:
- **Gap 1 (scope) — CLOSED.** Decided: wrap `AnalysisDBWriter._update_db` (`analysis_db_writer.py:223-264`) at the callsite via `_db_write_lock`/`db_lock()`, NOT a separate doc. Code-justified: write runs in-process (ProcessPoolExecutor `:64` vestigial — never `.submit()`ed; both routes dispatch in-process, `main.py:3086`/`3126`), so RLock serialises it; it is the highest-volume `master.db` writer (per analysed track) — parking defeats the goal. In scope, ~2 LoC, one file.
- **Gap 2 (circular guard) — CLOSED.** New drift guard detects writers by AST write-sink (`.db.<rbox-write>` + `self._try_call` + module-level `rbox.*.create`) across 3 modules, with a small `KNOWN_CALLSITE_PROTECTED` manifest. Detection orthogonal to the decorator's prefix allowlist → off-prefix + rbox-direct writers caught. AST-verified vs current code (surfaces 6 live mutators + 3 mytag methods + `ensure_standalone_master_db` + `AnalysisDBWriter._update_db`).
- **Gap 3 (Goal 1 metric) — CLOSED.** Goal 1 re-stated to key the metric on AST write-sink detection + callsite manifest, explicitly covering the rbox-direct AnalysisDBWriter path; cannot report green while unprotected.
- OQ1–OQ6 each still ≥1 Finding. Citation Quality PASS (2026-05-29) holds; no new stale cites (Links `:21,35`/`:925…` flagged for draftplan refresh, non-blocking — symbol+claim correct).
- Verdict: **PASS** — graduate `exploring_` → `evaluated_`.

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

**Option B (auto-wrap, prefix-matched) + OQ5 introspection test.** **CONFIRMED 2026-05-29 by user.** Two reasons B wins decisively: (1) drift is the real defect — the audit proved the hand list silently fell behind, and a list will do so again; (2) the audit found a *second* class needing wrapping (`LiveRekordboxDB` via `_require_live_db()`). A and C both scale by repetition (a 2nd loop list / a 2nd batch of `@` decorators + a cross-module import); B's one prefix-matched decorator applies to N classes by one `@` line each. B removes the drifting artefact instead of duplicating it.

Diff spans `database.py` + `live_database.py`: one `@serialise_mutators` decorator, applied to `RekordboxDB` + `LiveRekordboxDB`; `ensure_standalone_master_db` + the 3 live mytag writers get covered automatically by prefix; delete the old `setattr` loop; add `tests/test_concurrency.py`. No `main.py` churn, no route changes. Docstring `database.py:36-37` is already accurate — no doc repair (scaffold was wrong about that).

**Option C status:** DEFERRED. Reviewers who would prefer explicit `@_serialised` per def-site can request it at PR review — code-review-checklist convention covers visibility, the CI introspection test covers correctness either way. If review pushback ever appears at draftplan_ time, switch is mechanical (delete `@serialise_mutators` lines, scatter `@_serialised` to each def — same test pinning behaviour).

**Scope split:** the broken `save_track_cues`/`save_track_beatgrid` routes (`AttributeError` — non-existent facade methods) are a *separate* bug — own task, do not bundle into this draftplan.

**Draftplan gate conditions:**
1. Prefix allowlist finalised against a full mutator enumeration of **both** `RekordboxDB` (22) and `LiveRekordboxDB` — agree the exact prefix tuple, confirm it captures every intended mutator and excludes every `get_*`/`list_*`/property.
2. OQ5 harness flakiness assessed — confirm test (b) (8-thread write) is stable enough for `@pytest.mark.slow`, or ship test (a) introspection-only as the CI gate.
3. Decide on `RekordboxXMLDB` — wrap it too (free if the prefix decorator is applied), or leave it (XML mode is single-process file-write, lower risk). Lean: wrap, it's one `@` line.
4. User sign-off on Option B vs C (implicit-but-tested vs explicit-but-larger-diff).

---

## Implementation Plan

### Scope

**In:**
- `@serialise_mutators` prefix-matched class decorator (new, `database.py`) — replaces `setattr` loop `:1076-1086`.
- Apply decorator to `RekordboxDB` (`database.py:708`) + `LiveRekordboxDB` (`live_database.py:24`).
- Explicit lock acquire at `AnalysisDBWriter._update_db` callsite (`analysis_db_writer.py:223-264`, writes `:245`/`:255`) — rbox-direct, no class decorator can reach it.
- `KNOWN_CALLSITE_PROTECTED` manifest (lists callsite-locked writers, e.g. `AnalysisDBWriter._update_db`).
- `tests/test_concurrency.py` — AST write-sink drift guard (prefix-INDEPENDENT) + `@pytest.mark.slow` 8-thread harness + no-op-lock negative control.

**Out (per Non-goals):**
- rbox isolation redesign (`anlz_safe.py` ProcessPool stays).
- Row-level locking.
- `LiveRekordboxDB` per-thread→shared-pool conversion (PARKED).
- `save_track_cues`/`save_track_beatgrid` AttributeError routes (separate bug).

**XMLDB decision (gate-cond 3): EXCLUDE from rbox-concurrency concern; OPTIONAL prefix sweep.**
- `RekordboxXMLDB.create_mytag/delete_mytag/set_track_mytags` (`database.py:567/574/587`) write **XML file only** via `save_xml()` (`:610`) — no `rbox`/`master.db`. AST write-sink guard won't flag them (no `.db.<rbox-write>`).
- Decorator applies to XMLDB by one `@` line, free — but adds RLock to single-process file writes with no concurrent-write risk. Lean: apply for uniformity (1 line, harmless RLock), but it is NOT a gap closure. If reviewer objects to needless locking on file-only writes, drop the XMLDB `@` — gate-cond 3 satisfied either way.

### Step-by-step

1. Define `@serialise_mutators(cls)` in `database.py` (near `_serialised:43`). Iterate `vars(cls)`; wrap each plain function whose name starts with a prefix in `_MUTATOR_PREFIXES` and is not dunder / `property` / `get_*` / `list_*`. Reuse existing `_serialised` wrapper. `__wrapped__` set by `functools.wraps`.
2. Define `_MUTATOR_PREFIXES` tuple (single source of truth; the drift-guard does NOT consult it — see step 6). Finalise per gate-cond 1: `("set_", "load_", "unload_", "create_", "delete_", "remove_", "add_", "update_", "move_", "rename_", "reorder_", "refresh_", "save", "ensure_")`.
3. Apply `@serialise_mutators` to `RekordboxDB` (`database.py:708`) + `LiveRekordboxDB` (`live_database.py:24`). Cross-module: `database.py` already imports `LiveRekordboxDB` from `live_database` → reverse import risks a cycle. Resolve by hosting `_serialised`+`_db_write_lock`+decorator where both import cleanly (tiny `app/_db_lock.py`, OR apply decorator to `LiveRekordboxDB` from `database.py` post-import). Verify `python -c "import app.database"` boots.
4. Delete old `setattr` loop `database.py:1076-1086` (+ `del _name`). Decorator now covers all 21 + `ensure_standalone_master_db:728`.
5. Add explicit lock at `AnalysisDBWriter._update_db`: wrap the write region (`:244-258`, covering `update_content:245` + `update_content_key:255`) in `with db_lock():` (import from `database`). RLock reentrancy-safe if a wrapped live mutator is called inside. ~2 LoC.
6. Create `KNOWN_CALLSITE_PROTECTED = {"AnalysisDBWriter._update_db"}` manifest (in `test_concurrency.py` or a tiny shared const).
7. Write AST write-sink drift guard `test_no_unprotected_master_db_writer`: parse `database.py` + `live_database.py` + `analysis_db_writer.py` (module list asserted in-test). Flag a method a writer if body contains any of: `<recv>.db.<attr>(...)` where attr ∈ rbox-write-API set; `self._try_call([...])`; module-level `rbox.<Class>.<create|...>`. For each flagged writer assert `getattr(fn, "__wrapped__", None)` set OR name in `KNOWN_CALLSITE_PROTECTED`. Else CI fail. Detection orthogonal to `_MUTATOR_PREFIXES`.
8. Write `@pytest.mark.slow` concurrent harness: 8 threads each call a wrapped mutator on a temp `master.db`; assert 0 exceptions / 0 rbox panics / 0 sqlite "database is locked". Negative control: monkeypatch `_db_write_lock` to a no-op ctx-mgr → harness expected to fail.

### Files touched

| Path | Role | Why |
|---|---|---|
| `app/database.py` | facade + lock home | add `@serialise_mutators`+prefix tuple; apply to `RekordboxDB`; delete `setattr` loop `:1076-1086` |
| `app/live_database.py` | live DB class | apply `@serialise_mutators` to `LiveRekordboxDB:24`; import lock/decorator |
| `app/analysis_db_writer.py` | rbox-direct writer | `with db_lock():` around `_update_db` write region `:244-258` |
| `app/_db_lock.py` (optional) | shared lock/decorator home | break import cycle if step-3 needs it |
| `tests/test_concurrency.py` | NEW | AST drift guard (CI gate) + slow 8-thread harness + negative control + `KNOWN_CALLSITE_PROTECTED` |

### Testing
- Drift guard `test_no_unprotected_master_db_writer` = deterministic CI gate; 0 flagged-but-unprotected writers.
- Slow harness (`@pytest.mark.slow`) = serialisation proof + negative control.
- Regression: full `pytest tests/` green; read paths (`get_*`/`list_*`/properties) stay unwrapped.
- `ruff check` + `mypy app/database.py app/live_database.py app/analysis_db_writer.py` clean.

### Risks & rollback
- **Risk:** cross-module `_serialised`/lock import cycle (`database.py` ↔ `live_database.py`). Mitigation: shared `_db_lock.py` or post-import application; verify boot.
- **Risk:** prefix tuple over-wraps a non-mutator or under-wraps a future off-prefix mutator. Mitigation: drift guard is prefix-INDEPENDENT — under-wrap fails CI; over-wrap only adds harmless RLock.
- **Risk:** slow harness flaky on CI. Mitigation: `@pytest.mark.slow`, excluded from default gate; drift guard is the real gate.
- **Rollback:** revert the 3-4-file diff + delete `test_concurrency.py`. No on-disk/state change → clean `git revert`; old `setattr` loop restored = prior behavior exactly.

## Threat Model

Touches `master.db` writes → real integrity/availability surface (NOT "no security surface"). Local desktop, no network attacker; threat actor = concurrent request threads racing the shared DB file. Framing: data-integrity + DoS-via-panic.

STRIDE-light:

| ID | STRIDE | Threat | Vector | Mitigation | Test |
|---|---|---|---|---|---|
| TM1 | Tampering | `master.db` corruption | ≥2 threads write rbox `MasterDb` per-thread handles (`live_database.py:41`) on one file unserialised | RLock serialises every writer (decorator + callsite) | T-conc1 |
| TM2 | Tampering | Silent unprotected writer added later | new mutator off the hand list / off-prefix / rbox-direct | AST write-sink drift guard, prefix-independent | T-conc2 |
| TM3 | DoS | Sidecar process abort | rbox 0.1.7 `unwrap()` panic on concurrent write (`coding-rules.md`) → exit `0xC0000409`, whole sidecar down | serialisation removes concurrent-write trigger | T-conc1 |
| TM4 | DoS | sqlite "database is locked" → request failures | competing handles, no app-level serialisation | RLock = single in-process writer at a time | T-conc1 |

Spoofing / Repudiation / Info-disclosure / EoP: **N/A** — internal class/callsite change, single local user/session, no identity boundary, no secret on this path, no privilege boundary.

**Negative control** (T-conc3): lock monkeypatched no-op → harness MUST fail, proving the lock is load-bearing not decorative.

### Residual risk
Cross-thread deadlock IF a wrapped mutator offloads to another thread that calls a wrapped mutator (RLock reentrancy is thread-local; Adversarial 2026-05-29). Latent — beatgrid loader (`live_database.py:94`) is read-only today. Out of scope; note for future writer-from-worker-thread additions.

## Migration Path

N/A — no migration. Code-only: class-decorator swap + 1 callsite lock + 1 new test file. Nothing on-disk changes — no `master.db` schema/row change, no PDB/ANLZ byte layout, no IPC contract, no FastAPI route signature, no settings/`.env` key, no Tauri command. Lock semantics identical to today's `_serialised` (same wrapper, applied by pattern instead of name list). Existing libraries open unchanged; no data backfill, no version flag, no reverse-migration. `git revert` is the only rollback path.

## Performance Budget

RLock acquire/release per mutator call = microseconds (uncontended `threading.RLock`, pure-Python, no syscall on CPython fast path). Mutator work (rbox `update_content`, XML write, `OneLibrary.create`) is milliseconds-to-seconds — lock overhead is < 0.01% of any call. Per-batch serialisation already exists today (21 methods wrapped via `setattr` loop); this change widens coverage, not depth.

| Path | Budget | Measured today | Source |
|---|---|---|---|
| Mutator-call lock overhead | negligible (< 0.01% of call) | ~µs (21 wrapped today) | estimate (uncontended RLock) |
| Newly-wrapped `ensure_standalone_master_db` | no steady-state cost | one-shot startup, `if exists: return` guard | code (`database.py:728`) |
| `_update_db` callsite lock | µs/track, invisible vs seconds/track analysis | untested | estimate |
| 8-thread concurrent-write harness (T-conc1) | completes, 0 errors, single-writer throughput | corrupts/panics today | harness (new) |

### Worst-case scenario
- Input shape: 8+ threads writing (e.g. Phase-2 mobile companion concurrent edits).
- Expected impact: writes serialise → throughput bounded by single-writer rate.
- Mitigation if exceeded: **acceptable, not a regression** — rbox 0.1.7 cannot do concurrent `master.db` writes regardless (panics); serialised single-writer is the only correct mode. No throughput target beyond "no corruption, no panic, forward progress."

## API / UX Surface

### Backend (FastAPI)
- **none** — internal class-decorator (`database.py`/`live_database.py`) + one callsite lock (`analysis_db_writer.py`). All 85 mutating routes unchanged; request/response contracts identical. Lock lives on DB methods, not route decorators — `require_session`/`@rate_limit` stacks untouched.

### Frontend (React)
- **none** — no IPC/component/axios change. Behavior identical (writes just serialise correctly under concurrency).

### Tauri (Rust commands)
- **none** — no new/changed `#[tauri::command]`; sidecar boot unchanged.

### CLI / sidecar logs
- **changed (optional, minor)** — optional `logger.debug("db_lock: waiting …")` on contended acquire; diagnostic only, off at INFO, no secret. Decision deferrable to PR. Existing `live_database.py:40` debug stays.

## Telemetry

Minimal. The CI drift guard (`test_no_unprotected_master_db_writer`) is the real "how we know it keeps working" — fails the build the instant an unprotected `master.db` writer appears, prefix-independently. No runtime metric/counter needed; no user-visible feature to measure. Optional debug-level lock-wait log (API/UX surface) is the only runtime signal, off by default. Slow harness (T-conc1) runs on demand / nightly, not a steady telemetry stream.

## Test Plan

| ID | Layer | Test file | Case | Covers |
|---|---|---|---|---|
| T-conc2 | py | `tests/test_concurrency.py::test_no_unprotected_master_db_writer` | AST write-sink enumeration across database/live_database/analysis_db_writer; each flagged writer `__wrapped__` or in `KNOWN_CALLSITE_PROTECTED`; 0 unprotected | Goal-1/-2, TM2, Step 7 |
| T-conc1 | py (slow) | `tests/test_concurrency.py::test_concurrent_writers_serialise` | 8 threads write temp `master.db` via wrapped mutators → 0 exceptions / 0 rbox panics / 0 sqlite-locked | Goal-4, TM1/TM3/TM4, Step 8 |
| T-conc3 | py (slow) | `tests/test_concurrency.py::test_noop_lock_fails_harness` | monkeypatch `_db_write_lock`→no-op → harness fails (negative control, lock load-bearing) | TM-neg, Step 8 |
| TC4 | py | `tests/test_concurrency.py::test_decorator_wraps_all_rekordboxdb_mutators` | every `RekordboxDB` mutator (incl. `ensure_standalone_master_db`) has `__wrapped__` | Goal-1, Steps 1-4 |
| TC5 | py | `tests/test_concurrency.py::test_decorator_wraps_live_mytag_mutators` | `create_mytag`/`delete_mytag`/`set_track_mytags` on `LiveRekordboxDB` wrapped | Goal-1 (gap 2), Step 3 |
| TC6 | py | `tests/test_concurrency.py::test_read_paths_unwrapped` | `get_*`/`list_*`/properties NOT wrapped (no behavior change) | Goal-3, Step 1 |
| TC7 | py | `tests/test_concurrency.py::test_update_db_acquires_lock` | `AnalysisDBWriter._update_db` acquires `_db_write_lock` around write region | Goal-1 (gap 3), Step 5 |
| TC8 | py | `tests/test_concurrency.py::test_import_no_cycle` | `import app.database` + `app.live_database` boot clean (no circular import) | Risk (import cycle), Step 3 |
| TC9 | integration | `pytest tests/` | full suite green; no regression from decorator swap | Goal-3 |

## Task Queue

<!--
Small, individually-committable implementation tasks. 1 task = 1 routine/db-write-lock-retrofit-task-N branch = 1 PR.
Each task maps to Steps in ## Implementation Plan + ≥1 row in ## Test Plan.
-->

- [ ] **T-1 — `@serialise_mutators` decorator + apply + delete loop.** Define decorator + `_MUTATOR_PREFIXES` (resolve cross-module lock/decorator hosting, no import cycle — `app/_db_lock.py` if needed); apply to `RekordboxDB` + `LiveRekordboxDB`; delete `setattr` loop `:1076-1086`. — covers Steps 1-4, tests TC4, TC5, TC6, TC8.
- [ ] **T-2 — AnalysisDBWriter callsite lock + manifest.** `with db_lock():` around `_update_db` write region (`:244-258`); add `KNOWN_CALLSITE_PROTECTED` manifest. — covers Steps 5-6, test TC7.
- [ ] **T-3 — AST write-sink drift guard (CI gate).** `tests/test_concurrency.py::test_no_unprotected_master_db_writer` — prefix-independent write-sink detection across 3 modules. — covers Step 7, test T-conc2.
- [ ] **T-4 — Concurrent harness + negative control.** `@pytest.mark.slow` 8-thread write harness + no-op-lock negative control. — covers Step 8, tests T-conc1, T-conc3.
- [ ] **T-5 — Docs sync.** `docs/FILE_MAP.md` + `/regen-maps` (new `test_concurrency.py`, decorator symbol); `CHANGELOG.md` if deemed user-visible (internal hardening — likely a one-line note). — done at `implemented_`.

## Review

Stage 3 Reviewer-Agent (`review_`). Unchecked box or rework reason → `rework_`.

### 2026-05-31 — Plan-Reviewer → PASS

- [x] Plan addresses all goals — Steps 1-4 (RekordboxDB+LiveRekordboxDB auto-wrap) + Step 5 (AnalysisDBWriter callsite) → Goal-1; Step 7 prefix-independent drift guard → Goal-2; TC6 read-paths → Goal-3; Step 8 harness + T-conc3 negative control → Goal-4. T-1..T-4 map.
- [x] Plan matches `## Original Idea` — no scope-creep — Non-goals park per-thread-pool refactor, save_track_cues/grid AttributeError (own task), row-level locking; XMLDB = optional non-gap, not coverage scope.
- [x] Open questions answered or deferred — OQ1-6 RESOLVED; 4 draftplan gate conds addressed: prefix tuple finalised (Step 2), harness→`@pytest.mark.slow` (Step 8), XMLDB EXCLUDE+optional sweep, Option C DEFERRED.
- [x] Prior Art referenced — no duplicated past work — security-api-auth-hardening (parent carve-out), metadata-name-fixer (sibling).
- [x] Threat Model present + each threat has a test (or N/A justified) — TM1→T-conc1, TM2→T-conc2, TM3/TM4→T-conc1, neg-control→T-conc3; all real Test-Plan rows. Spoof/Repud/Info/EoP N/A justified (no identity/secret/privilege boundary, single local user).
- [x] Migration Path present + rollback documented (or N/A justified) — N/A verified: code-only, no master.db schema/row, no PDB/ANLZ bytes, no IPC contract, no route signature, no .env/settings key, no Tauri command. `git revert` rollback.
- [x] Performance Budget set + worst-case scenario documented (or N/A justified) — µs uncontended RLock; worst-case serialised single-writer "acceptable, not a regression" reasoning holds — rbox 0.1.7 cannot do concurrent master.db writes regardless (coding-rules.md).
- [x] API / UX Surface enumerated for every layer touched — backend none (all 85 routes unchanged), frontend none, tauri none, logs optional-debug-only; verified change adds no route/IPC.
- [x] Telemetry defined for shipped behavior (or N/A justified) — CI drift guard is the keep-working signal; no runtime counter; optional debug lock-wait log off by default. Justified.
- [x] Test Plan covers every Threat + every Step + every Perf row — Step1→TC4/TC6, Step2→TC4/TC5, Step3→TC5/TC8 (import-cycle), Step4→TC4 (old-loop-deletion coverage preserved: every RekordboxDB mutator incl. ensure_standalone_master_db wrapped), Step5→TC7, Step6→T-conc2, Step7→T-conc2, Step8→T-conc1/T-conc3. Every threat + perf row (T-conc1) covered.
- [x] Task Queue items are small + independently committable + reference Steps + Tests — T-1..T-5 each ref Steps + Tests; ordering unblocks (T-1 decorator before T-3 guard asserting `__wrapped__`). T-1 is the largest (decorator def + 2-class apply + loop delete) but is genuinely atomic — loop-delete must land with decorator-apply or coverage regresses mid-sequence; splitting creates a red intermediate. Acceptable.
- [x] Dependencies audited — new libs have Schicht-A entries — none added; stdlib `ast`/`functools`/`threading` only.
- [x] Risk mitigations defined — import cycle (shared `app/_db_lock.py` or post-import apply + boot verify + TC8), prefix over/under-wrap (drift guard prefix-INDEPENDENT → under-wrap fails CI, over-wrap harmless RLock), harness flakiness (`@pytest.mark.slow`, drift guard is the CI gate).
- [x] Affected docs identified (`architecture.md`, `FILE_MAP.md`, indexes, `CHANGELOG.md`) — T-5: FILE_MAP + regen-maps + CHANGELOG. architecture.md correctly omitted (no data-flow change, concurrency-internal).

**Rework reasons:**
- none — **PASS**.

**Reviewer notes (non-blocking):**
- Verified import-cycle is real: `app/database.py:13` does `from .live_database import LiveRekordboxDB`, so `live_database.py` importing the lock/decorator back would cycle. Step-3 mitigation (`app/_db_lock.py` host or post-import apply) is concrete + TC8-tested.
- Verified decorator/drift-guard consistency on mytag mutators: `create_mytag`/`delete_mytag`/`set_track_mytags` reach rbox via `self._try_call([...])` (`live_database.py:1012`), NOT a literal `.db.<write>`. Decorator catches by name-prefix; drift guard catches by the dedicated `_try_call` AST rule. Both cover, consistent.
- Verified AnalysisDBWriter ProcessPoolExecutor is vestigial (no `.submit()` callsite) → write runs in-process → RLock at `_update_db` callsite serialises correctly.
- 3-module AST scope (database/live_database/analysis_db_writer) captures every live-master.db writer: `soundcloud_api.py` writes route through wrapped facade/active_db methods (consumer, not rbox-direct); `usb_one_library.py`/`build_template.py` write the USB export `exportLibrary.db`, not master.db. A future *new* rbox-direct module would need adding to the in-test asserted module list — acceptable documented manual surface, same class as `KNOWN_CALLSITE_PROTECTED`.

## Approval Summary

**What it does:** An internal safety fix. Today, when two things try to write to your Rekordbox database at the same time (for example a tag edit while a background analysis saves), they can collide — which can crash the helper process or, worst case, corrupt the library. This change makes sure every database write takes a turn, closes three gaps where some writes slipped past the existing guard, and adds an automatic test that fails the build if anyone ever reintroduces the gap.

**What you'll notice:**
- Nothing visible — no UI change, no new buttons, same behaviour.
- Fewer rare crashes/corruption under heavy or concurrent use (and a foundation the planned mobile companion needs before it can safely send edits).

**Scope:** 3–4 files touched · 5 tasks · effort **S–M** · risk **low** (pure code refactor, no data/format change; a CI test pins correctness).

**Rollback:** Pure code change with no on-disk effect — a single `git revert` restores the previous behaviour exactly.

**Mockup:** see `## Mockup` below.

## Mockup

### Backend — concrete example

```text
# BEFORE — coverage maintained by a hand-edited name list that silently drifts:
#   app/database.py:1076-1086
for _name in ("update_track_comment", "add_track", ...21 names...):
    setattr(RekordboxDB, _name, _serialised(getattr(RekordboxDB, _name)))
# → MISSED: ensure_standalone_master_db (RekordboxDB), 3 LiveRekordboxDB mytag
#   writers (reached via _require_live_db()), and AnalysisDBWriter._update_db
#   (rbox-direct write — no class decorator can reach it).

# AFTER — one prefix-matched decorator + a callsite lock:
@serialise_mutators           # database.py
class RekordboxDB: ...
@serialise_mutators           # live_database.py
class LiveRekordboxDB: ...

def _update_db(self, ...):    # analysis_db_writer.py
    with db_lock():           # rbox-direct write now serialised
        self.live_db.db.update_content(item)
        self.live_db.db.update_content_key(...)

# The drift guard (runs in CI) — detects writers by what they CALL, not by name:
$ pytest tests/test_concurrency.py::test_no_unprotected_master_db_writer
FAILED - unprotected master.db writer: LiveRekordboxDB.import_library
         (calls self.db.update_content at live_database.py:NNN; not @serialise_mutators-wrapped
          and not in KNOWN_CALLSITE_PROTECTED)
# ^ exactly the failure a future un-guarded writer triggers — the gap can't silently return.
```

---

> ⛔ APPROVAL GATE — user `/approve` (→ `accepted_`) or `/reject "<reason>"` (→ `rework_`). The single sign-off: read `## Approval Summary` + `## Mockup`. After approval, nothing is re-researched.
> ↓ Stage 4 — `inprogress_`. `research-implement` builds each Task Queue item on a `routine/*` branch. You test + merge the branch yourself.

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
