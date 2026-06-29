---
slug: performance-overhaul
title: Speed & efficiency overhaul — eliminate perceptible app slowness
owner: tb
created: 2026-06-09
last_updated: 2026-06-09
tags: []
related: []
supersedes: []
superseded_by: []
---

# Speed & efficiency overhaul — eliminate perceptible app slowness

> **Caveman+ style.** Fragments, bullets. Drop articles/filler/hedges. No prose paragraphs.
> Word caps are **soft** — recommendations, not hard blocks. Exceed when topic complexity demands; routines may flag excess length but never truncate facts.
> State = folder + filename prefix (not frontmatter). Lifecycle = audit trail. See `../README.md`.
> Routines advance this doc **autonomously** by state. **One** user gate: `approvalgate_` — read `## Approval Summary` + `## Mockup`, then `/approve` or `/reject`. After approval you test the finished branch locally and merge it yourself.
> Section ownership: each `> ↓ Stage X — <agent>: …` marker names the agent that fills the section. Don't write into a section before its stage.

## Lifecycle

- 2026-06-09 — `research/idea_` — created from template
- 2026-06-09 — `drafting_` — promoted; Stage-1 (Prior Art→Research Plan) pre-filled from 9-agent codebase perf investigation (48 hotspots, file:line evidence). Idea Verification left for the research-draft Verifier.

## Original Idea (verbatim — never edit)

<!--
Written ONCE by the user. 1–3 sentences, raw. NEVER edited after — not by routines, not by the user.
Every verifier (Stage 1 idea-check, Stage 2 research-check, Stage 3 plan-review, Stage 4 doc-sync) checks
its work against this block. It is the anchor against scope-creep and misreading.
-->

App feels slow in several places — want a speed & efficiency overhaul so it feels fast everywhere. Concretely slow today: the USB section; scrolling in the library (partially); switching tabs; and expanding playlists — clicking a playlist (e.g. in library mode) so it expands and shows more is slow. More things go in the same direction; goal = find and fix the perceptible slowness across the whole app (frontend, Python sidecar, audio, USB export).

---

> ↓ Stage 1 — `drafting_`. `research-draft` fills Problem → Research Plan via 4 agents (Scout, Prior-Art, Risk-Surface, Worker). Verifier fills Idea Verification.

## Prior Art

**Internal:** None — greenfield perf work. No perf research doc in `docs/research/{research,implement,archived}` (only security + feature docs). This `performance-overhaul` doc is the first.

**Prior-art patterns already in repo (reuse, don't reinvent):**
- `useMemo`/`useCallback`/`React.memo` used in 51 files (262 occ) — but **zero** on top-level views or `TrackTable` rows.
- Canvas waveform LOD + rAF + OffscreenCanvas bitmap cache (`frontend/src/components/daw/timeline/useTimelineRender.js`) — correct perf model, leave it.
- Server in-memory track cache (`app/live_database.py:178 self.tracks`); background threaded beatgrid/cue loaders (`live_database.py:85-112`); `SafeAnlzParser` ProcessPoolExecutor isolation.
- axios `AbortController`/`cancellableGet` helpers exist (`frontend/src/api/api.js:286-303`) — largely unused.

**External precedent (big-library scroll + USB export):**
- Rekordbox/Serato/Traktor all virtualize/window the track list — only visible rows in DOM; never render N-thousand rows at once.
- Serato/Rekordbox export USB with streamed per-file progress (live bar + file count), not one opaque blocking call.
- Rekordbox caches device/library scan; doesn't re-decrypt the export DB on every passive view.

## Problem

App feels slow across USB section, library scroll, tab switching, and playlist expand. Root causes: zero list virtualization (whole library → DOM), unpaginated `/api/library/tracks`, all heavy views kept mounted + unmemoized (re-render forest on any state change), USB export = one blocking request discarding all progress, USB scan/diff = N+1 + O(n²) + repeated PowerShell/rbox opens, waveform decode on the event loop, 30s blocking sidecar startup. Cost-of-not-doing: unusable at multi-thousand-track scale, daily friction.

## Goals / Non-goals

**Goals**
- Library/Collection scroll stays ~60fps at 20k tracks (only visible rows mounted)
- Tab switch feels instant — active subtree re-render <100ms, no full view-forest re-render
- Playlist expand <150ms perceived; cached revisits near-instant
- USB "Sync Now" shows real streamed progress (per-file %), no fake 0%→100% bar
- USB view open / device select <500ms (cached bus-types + track-count, no rbox open on passive scan)
- USB "Preview changes" (diff) returns within axios timeout on multi-thousand-track libs
- Track-select / waveform never blocks the FastAPI event loop or other requests
- App cold-start serves the sidecar immediately (library load backgrounded, status=`loading`); no fixed 2s splash delay
- No constant idle CPU/network — gate ImportProgressBanner 1.5s double-poll on active tasks
- First library open fetches once, not twice

**Non-goals**
- No audio-engine (Rust cpal/symphonia/rubato) rewrite
- No new heavy frontend dep without explicit Schicht-A audit + user sign-off (react-window / @tanstack/react-query are decisions, not assumptions)
- Not a visual redesign — same layout, columns, interactions
- No `master.db` / ANLZ / USB PDB schema or byte-layout change
- No change to `_db_write_lock` serialization or `SafeAnlzParser` single-worker quarantine
- No new auth/transport model — streaming sync stays behind `require_session`
- Not a switch from XML to live mode (or vice versa) — both modes must benefit
- No backend framework swap (stays FastAPI on 8000)

## Constraints

Stage 1 Worker + Risk-Surface-Agent. External facts bounding solution.

- **External APIs / rate limits:** None on hot paths — local-first, no cloud calls in scroll/expand/tab/USB-view flows. SoundCloud/import polling is the only background network (`frontend/src/components/ImportProgressBanner.jsx:37`, 1.5s).
- **Data shape (`master.db`, ANLZ, USB PDB):** USB PDB byte layout in `app/usb_pdb.py` byte-verified vs real Pioneer F: drive — fixes must NOT touch flag/offset/page invariants (data-page flag `0x34`, descriptor `empty_candidate`, index-page heap). Per-track dict carries ~25 fields incl. `beatGrid`+`positionMarks` (`app/database.py:137,153` / `live_database.py:189-224`) the list view never uses — candidate to strip from list projection, fetch on demand via `/api/track/{tid}/beatgrid`.
- **Schicht-A pinning / library version:** `requirements.txt` all `==X.Y.Z`; frontend lockfile canonical (`npm ci` in CI, `npm run lint:lockfile`). Current frontend stack: react 18.3.1, axios 1.16.0, wavesurfer 7.12.6 — **no** virtualization/query lib (`frontend/package.json`). Any new perf dep = security decision + user sign-off.
- **Perf / capacity:** Cost scales with track count (folder comment mentions 3322 — `app/usb_manager.py:1525`). Unpaginated `/api/library/tracks` returns full library (`app/main.py:861`); default axios timeout 10s (`frontend/src/api/api.js:24`) — diff/contents can exceed it on large libs.
- **Legal / compliance:** None new — local desktop app, no PII, no new data flows.
- **Concurrency invariants:** `_db_write_lock` (RLock, `app/database.py:22`) serializes ALL `master.db` writers — sync write path + inline rating/color PATCH must keep acquiring it; no parallel DB writes. `validate_audio_path` sandbox (`app/main.py:186`) + `/api/artwork` dir jail (`main.py:1886-1908`) gate FS — any artwork caching/offload must preserve jail + extension allowlist. `SafeAnlzParser` ProcessPoolExecutor `max_workers=1` (`app/anlz_safe.py:232`) quarantines rbox `unwrap()` panics — cannot widen pool, cannot call rbox concurrently from main process. Streaming/WebSocket replacement of `/api/usb/sync` must stay behind `Depends(require_session)`.

## Dependencies

Prefer existing stack. Most fixes need **no** new dep — virtualization/debounce can be hand-rolled, GZip is stdlib-backed, cache headers ship with starlette. New libs below are plan-time options for the Schicht-A decision only.

| Dep | Kind | Version | License | Schicht-A audit needed? | Why |
|---|---|---|---|---|---|
| react-window | npm | latest pinned | MIT | yes | Table-row virtualization for `TrackTable` — cleaner than hand-rolled, but new dep |
| @tanstack/react-virtual | npm | latest pinned | MIT | yes | Alt virtualization (headless, div/grid rows) — fits sticky-thead refactor |
| @tanstack/react-query | npm | latest pinned | MIT | yes | Shared track cache + request dedup across views — alt to module-level Map |
| swr | npm | latest pinned | MIT | yes | Lighter alt to react-query for response cache/dedup |
| GZipMiddleware (starlette) | py | bundled w/ FastAPI | BSD | no | Compress oversized JSON — already in tree, no `requirements.txt` change |
| Hand-rolled windowing hook + debounce | n/a | n/a | n/a | no | Zero-dep path: small `useVirtualRows` + debounce util in `frontend/src/utils/` |

If plan picks the hand-rolled + stdlib path: **None — uses existing stack only.**

## Open Questions

Stage 1 Worker. Numbered. Each resolvable (yes/no or X vs Y). Each becomes a parallel research agent in Stage 2.

1. What is the user's real library size (track count in `master.db`)? Folder comment mentions 3322 — confirm; severity of every N+1/O(n²)/unvirtualized-render scales with it.
2. Is the perceived slowness dominated by the React re-render cascade (main-thread CPU) or by sidecar network re-fetch? Profiler trace vs Network timing on one tab switch to disambiguate.
3. Virtualization approach: keep `<table>`+sticky-`<thead>` and window `<tbody>` rows (react-window) vs swap to div/grid rows (@tanstack/react-virtual) vs hand-rolled windowing hook — which preserves `TrackTable`'s 4-caller props API (columns, customColumns, onReorder drag/drop, onSortedTracksChange)?
4. New dep (react-window / @tanstack/*) vs hand-rolled windowing — does a zero-dep hook meet the Schicht-A "prefer existing stack" bias acceptably, or is the audited lib worth the sign-off?
5. Add a shared client cache/dedup layer (react-query/swr vs module-level Map keyed by endpoint) so tab revisits + repeated playlist clicks serve cached data — which fits the axios-via-`api.js` mandate with least churn?
6. Should `/api/library/tracks` gain server-side pagination + search params + a slim list projection (strip beatGrid/positionMarks), or is stripping the projection alone enough once the frontend virtualizes? (DawBrowser already sends `limit:200`, ignored — `app/main.py:861`.)
7. Is the USB export bottleneck the OneLibrary writer or the legacy XML `_copy_file_stream` serial loop — does the 16-slot OneLibrary template cap (`usb_one_library.py:130-133`) mean most tracks only flow through the legacy path? Determines what to parallelize.
8. Can the per-track export copy+ANLZ+artwork loop be offloaded to a thread pool, and can the redundant second full-library pass (both library_one+library_legacy forced at `main.py:2583`) be skipped when both target the same Contents dir — without violating `_db_write_lock` / `SafeAnlzParser` quarantine?
9. Replace blocking POST `/api/usb/sync` with StreamingResponse/SSE vs WebSocket to stream real progress to `syncProgress` (`main.py:2567`, `UsbView.jsx:185`) — which keeps `require_session` auth simplest and survives minutes-long exports?
10. Can USB scan cost be cut: cache bus-types + per-drive track_count across scans (longer TTL, invalidate on sync) and stop opening the rbox export DB on every passive `_probe_drive` (`usb_manager.py:343-356`) — and share one scan across get_usb_contents / profile / devices instead of re-scanning per user step?
11. Move the waveform endpoint off the event loop (`loop.run_in_executor`, mirroring `/api/track/{tid}/analyze` at `main.py:1008`) and memoize via AnalysisCache keyed on (path,mtime,size,pps) — does this fully remove the global event-loop stall on track select (`main.py:731` / `services.py:439`)?
12. Make sidecar startup non-blocking — background `db.load_library` + report status=`loading` (pattern already used for beatgrids) instead of the 30s blocking `asyncio.wait_for` (`app/main.py:2337`)? And drop the fixed 2s splash `setTimeout` for an on-mount `close_splashscreen` (`frontend/src/main.jsx:774`)?
13. Cache the hide_streaming setting in memory (invalidate on settings save) so `db.tracks` stops doing a per-access disk read + JSON parse (`database.py:756` / `services.py:706`) — confirm this is the single-spot systemic win across most read endpoints?
14. Unify `main.jsx` render strategy: should heavy stateful views be `React.memo`'d + keep-mounted consistently (vs the current mix of hidden-div keep-mounted at `main.jsx:894-946` and unmount-on-switch at `948-961`), and which views are cheap enough to leave conditionally rendered?
15. Add Cache-Control/ETag to `/api/artwork` (`main.py:1913`) + offload its blocking file read off the event loop — does header caching alone remove the per-row artwork re-fetch storm once rows are virtualized?
16. How to set baselines: which measurement method (React Profiler flamegraph, Chrome/WebView2 performance trace, backend timing logs, a `tests/perf/` harness) gives reproducible before/after numbers per hotspot — and is jank meaningfully worse under Tauri WebView2 vs browser dev?

## Research Plan

Stage 1 Worker. Which aspects Stage 2 researches in parallel — one bullet per agent.

- Agent 1 (codebase + web): TrackTable virtualization — measure unvirtualized render cost at scale (`TrackTable.jsx:170`, 4 callers' props API); compare react-window vs @tanstack/react-virtual vs hand-rolled windowing for a sticky-thead `<table>`; web: best-practice big-list windowing in React 18 + how rekordbox/serato window track lists.
- Agent 2 (codebase + web): React render-cascade — top-level views unmemoized + kept mounted (`main.jsx:894-961`), unmemoized allPlaylists (`PlaylistBrowser.jsx:181`), inline handler props, onSortedTracksChange round-trip; quantify re-render fan-out; web: React.memo/useCallback patterns + keep-mounted-vs-unmount tradeoffs.
- Agent 3 (codebase + web): Backend list payload — paginate + project `/api/library/tracks` (strip beatGrid/positionMarks, `main.py:861` / `database.py:137,153`), add GZipMiddleware + artwork Cache-Control/ETag (`main.py:1913`); web: FastAPI pagination + starlette compression/cache-header patterns.
- Agent 4 (codebase + web): Client data cache — dedup the PlaylistBrowser double mount-fetch (`PlaylistBrowser.jsx:209,216`), drop cache-buster (`:234`), shared track cache keyed by endpoint/playlist-id; web: react-query vs swr vs module-Map, and Schicht-A cost of each new dep.
- Agent 5 (codebase + web): USB export streaming + parallel copy — StreamingResponse/SSE vs WebSocket for `/api/usb/sync` (`main.py:2567`, `UsbView.jsx:185`), thread-pool the per-track copy/ANLZ/artwork loop (`usb_one_library.py:257-347`, `usb_manager.py:1496-1567`), skip redundant double library pass — respecting `_db_write_lock` + `SafeAnlzParser`; web: how DJ tools stream USB-export progress.
- Agent 6 (codebase + web): USB scan/diff/contents caching — cache bus-types + per-drive track_count, stop rbox open on passive scan (`usb_manager.py:182-201,343-356`), batch artist N+1 + index diff matcher O(n) (`usb_manager.py:1006,1082-1091`), cache contents by exportLibrary.db mtime; web: SQLCipher/pyrekordbox read-cost mitigation.
- Agent 7 (codebase + web): Event-loop + sidecar startup — offload waveform via run_in_executor + AnalysisCache memoize (`main.py:731`/`services.py:439`), background db.load_library + status=`loading` (`main.py:2337`), cache hide_streaming setting (`database.py:756`/`services.py:706`), drop fixed 2s splash (`main.jsx:774`); web: FastAPI sync-CPU offloading + non-blocking startup patterns.
- Agent 8 (codebase + web): Measurement + baselines — pick reproducible profiling per hotspot (React Profiler, Chrome/WebView2 trace, backend timing logs, `tests/perf/` harness), confirm idle polling (ImportProgressBanner 1.5s `ImportProgressBanner.jsx:37`, 1s library-status, 5s heartbeat) quiesces post-load; web: React/Tauri-WebView2 perf profiling methodology + jank metrics.

## Idea Verification

Stage 1 Verifier. Dated entries, append-only. PASS / FAIL + ≤40-word reason (checked vs `## Original Idea` + `## Prior Art`).

### YYYY-MM-DD — <PASS|FAIL>
- …

---

> ↓ Stage 2 — `exploring_` (autonomous; no user gate). On Idea-Verifier PASS, `research-draft` advances `drafting_` → `exploring_` directly. `research-explore` runs parallel tiered agents (codebase + web + synthesis per OQ), an Adversarial agent, a Citation-Quality verifier, and a Research-Verifier — one autonomous pass to `evaluated_`.

## Findings / Investigation

Stage 2 Synthesis-Agents (one per OQ). Dated subsections, append-only. ≤150 words each (soft). Never edit past entries — supersede.

### YYYY-MM-DD — <label>
- **Codebase:** … (`file:line` refs required)
- **Web:** … (cited URLs required)
- **Synthesis:** …
- **Confidence:** high / medium / low

## Adversarial Findings

Stage 2 Adversarial-Agent (phase 2). Devil's-advocate — what could go wrong, what assumptions are weak, what dependencies betray us. ≤120 words. Append-only.

### YYYY-MM-DD
- **Weak assumption:** …
- **Failure mode:** …
- **Counter-example:** …

If none survive scrutiny: **"No surviving objections — proceed with caution flags above."**

## Citation Quality

Stage 2 Citation-Verifier (phase 2). Checks every `file:line` ref + URL in `## Findings` exists + says what the Finding claims. PASS / FAIL list. ≤80 words.

### YYYY-MM-DD — <PASS|FAIL>
- PASS: Findings 1, 2, 4 — citations verified
- FAIL: Finding 3 — `app/main.py:123` no such symbol, replace or remove

---

> ↓ Stage 2 phase 2 (autonomous; no user gate) — `research-explore` deepens findings, runs Adversarial + Citation verifiers, then the Research-Verifier gates the whole body before Options-Synthesis advances the doc to `evaluated_`.

## Research Verification

Stage 2 wave-2 verifier over whole research body. ≤120 words. PASS → `evaluated_`; gaps → more Findings.

### YYYY-MM-DD — <PASS|GAPS>
- Coverage of Open Questions: …
- Internal consistency: …
- Citation quality (cross-ref `## Citation Quality`): …
- Adversarial concerns addressed: …

## Options Considered

Stage 2 Synthesis-Agent (phase 2 PASS). Per option: sketch ≤5 bullets, pros, cons, S/M/L/XL, risk, prior-art match.

### Option A — <name>
- Sketch:
- Pros:
- Cons:
- Effort:
- Risk:
- Prior-art match: <slug or "novel">

### Option B — <name>
- Sketch:
- Pros:
- Cons:
- Effort:
- Risk:
- Prior-art match: <slug or "novel">

## Recommendation

Stage 2 Synthesis-Agent (phase 2 PASS). ≤120 words. Which option + what blocks commit + which OQ each Finding answers.

---

> ↓ Stage 3 — `implement/draftplan_`. `research-plan` fills Implementation Plan + Task Queue via 5 agents (Planner, Threat-Modeller, Migration, Perf-Budget, Test-Plan). Reviewer fills Review. On Review PASS, the Mockup+Summary-Agent fills `## Approval Summary` + `## Mockup`, then advances to `approvalgate_`.

## Implementation Plan

Stage 3 Planner-Agent. Concrete enough that someone else executes without re-deriving.

### Scope
- **In:** …
- **Out:** …

### Step-by-step
1. …

### Files touched
Path + role (read / edit / new):
- `<path>` — <role> — <why>

### Testing
High-level (see `## Test Plan` for concrete pytest/cargo cases):
- …

### Risks & rollback
- …

## Threat Model

Stage 3 Threat-Modeller-Agent. Required when feature touches: auth, `require_session`, filesystem (paths in / out), `master.db` writes, network, secrets, user-supplied paths. Otherwise: **"N/A — no security surface."**

### Assets
- … (data, secrets, attacker goal)

### Trust boundaries
- … (which layer trusts which input)

### Threats (STRIDE-light)
| ID | Threat | Mitigation in plan | Test covers |
|---|---|---|---|
| T1 | … | step N / file X | test_… |

### Residual risk
- ≤60 words — what cannot be eliminated, why acceptable.

## Migration Path

Stage 3 Migration-Path-Agent. Required when feature changes: DB schema, file layout, settings/config shape, IPC contract, on-disk caches, USB export bytes. Otherwise: **"N/A — no migration."**

### Before → After
- Data shape today: …
- Data shape after: …
- Existing-data handling: in-place migrate / lazy on read / one-shot backfill

### Backfill / forward-compat
- Migration script: `<file>` (or "no script — schema-additive")
- Old client reads new data: yes/no — how degraded
- Rollback: restore via `<backup>` / re-run reverse migration `<file>`

### User-visible behavior during migration
- … (downtime, progress UI, can app start before complete?)

## Performance Budget

Stage 3 Perf-Budget-Agent. Numbers, not "fast". If feature has no perceptible runtime cost: **"N/A — analysis-only / one-shot."**

| Path | Budget | Measured today | Source |
|---|---|---|---|
| <e.g. POST /api/duplicates/scan> | p95 ≤ 800ms / 50MB peak | … | `tests/perf/…` or "untested" |

### Worst-case scenario
- Input shape: <e.g. 50k tracks, 200 dupes>
- Expected impact: …
- Mitigation if exceeded: …

## API / UX Surface

Stage 3 Planner-Agent. What is added / changed at every layer the user / frontend touches.

### Backend (FastAPI)
- New routes: `<METHOD> <path>` — auth: `require_session`? rate-limited? lock?
- Changed routes: `<METHOD> <path>` — what changed in request/response shape

### Frontend (React)
- New components / hooks / IPC calls (axios + invoke):
- Changed components: …

### Tauri (Rust commands)
- New `#[tauri::command]`s: …
- Changed signatures: …

### CLI / sidecar logs
- New stdout markers (e.g. `LMS_TOKEN=`-style): …

## Telemetry

Stage 3 Planner-Agent. How we know it works after ship. ≤80 words. Otherwise: **"N/A — no runtime behavior to observe."**

- Log markers (`logger.info("op=… …")`): …
- Counters / timing: …
- Health-endpoint surface: …
- User-visible status (toast, statusline, dashboard tile): …

## Test Plan

Stage 3 Test-Plan-Agent. Concrete test cases, one row per. Must cover Threat Model + Migration + Perf budgets.

| ID | Layer | Test file | Case | Covers (Threat / OQ / Step) |
|---|---|---|---|---|
| T1 | py | `tests/test_<area>.py::test_<case>` | … | Threat T1 |
| T2 | rust | `src-tauri/src/audio/.../tests` | … | Step 3 |
| T3 | js | `frontend/src/**/*.test.js` | … | OQ 2 |
| T4 | integration | `tests/test_<integration>.py` | end-to-end happy path | full flow |
| T5 | perf | `tests/perf/<file>.py` (new) | p95 budget vs target | Perf table row N |

## Task Queue

<!--
Small, individually-committable implementation tasks. Written by research-plan (Stage 3),
approved by the user at the Approval Gate. research-implement works ONE task per branch:
routine/<slug>-task-<N>. 1 task = 1 feature = 1 PR. Tick - [x] when the PR is merged.
Keep tasks small — a task too big to review in one PR must be split.
Each task should map back to a Step in ## Implementation Plan and have ≥1 row in ## Test Plan.
-->

- [ ] <task — small, single-purpose, independently testable> — covers Step N, tests T<m>, T<n>

## Review

Stage 3 Reviewer-Agent (`review_`). Unchecked box or rework reason → `rework_`.

- [ ] Plan addresses all goals
- [ ] Plan matches `## Original Idea` — no scope-creep
- [ ] Open questions answered or deferred
- [ ] Prior Art referenced — no duplicated past work
- [ ] Threat Model present + each threat has a test (or N/A justified)
- [ ] Migration Path present + rollback documented (or N/A justified)
- [ ] Performance Budget set + worst-case scenario documented (or N/A justified)
- [ ] API / UX Surface enumerated for every layer touched
- [ ] Telemetry defined for shipped behavior (or N/A justified)
- [ ] Test Plan covers every Threat + every Step + every Perf row
- [ ] Task Queue items are small + independently committable + reference Steps + Tests
- [ ] Dependencies audited — new libs have Schicht-A entries
- [ ] Risk mitigations defined
- [ ] Rollback path clear
- [ ] Affected docs identified (`architecture.md`, `FILE_MAP.md`, indexes, `CHANGELOG.md`)

**Rework reasons:**
- …

## Approval Summary

Stage 3 Mockup+Summary-Agent (after Plan-Reviewer PASS). **Plain user-facing English — NOT Caveman.** This block is what the user reads to decide yes/no. ≤200 words. No `file:line` jargon — describe effects, not internals.

- **What it does:** 1–2 sentences, plain language. What the feature gives the user.
- **What you'll notice:** bullet list of user-visible effects (new button, faster scan, new export option, …).
- **Scope:** N files touched · N tasks · effort S/M/L · risk low/med/high.
- **Rollback:** one line — how it's undone if you dislike it after merge.
- **Mockup:** see `## Mockup` below.

## Mockup

Stage 3 Mockup+Summary-Agent. Adaptive to feature type — decide from `## API / UX Surface`:

- **UI feature** (has frontend components): write a self-contained static wireframe to `docs/research/mockups/<slug>.html` (inline CSS, no build step, no external assets — open in a browser locally). Fill the **UI** block below. Leave the **Backend** block empty/removed.
- **Backend / DSP / USB / DB feature** (no visible UI): fill the **Backend** block with a concrete example — sample API request/response, CLI/log output, or before→after data (metadata tags, USB tree, DB rows). Show the shape the user will actually see. Leave the **UI** block empty/removed.

### UI — mockup file
- `docs/research/mockups/<slug>.html` — <one-line layout + key-interaction description>

### Backend — concrete example
```text
<sample response / CLI output / before→after — the user-visible shape>
```

---

> ⛔ APPROVAL GATE — user `/approve` (→ `accepted_`) or `/reject "<reason>"` (→ `rework_`). The single sign-off: read `## Approval Summary` + `## Mockup`. After approval, nothing is re-researched.
> ↓ Stage 4 — `inprogress_`. `research-implement` builds each Task Queue item via 5 agents (Approach-Probe, Code, Standard-Review, Security-Review, Test-Coverage-Review, Doc-Sync) on a `routine/*` branch. You test + merge the branch yourself.

## PR Log

Stage 4. One row per task PR. `research-implement` appends; user notes merge after local testing.

| Task | Branch | PR | CI | Std Rev | Sec Rev | Test Cov | Doc Sync | Merged |
|---|---|---|---|---|---|---|---|---|
| … | `routine/<slug>-task-N` | #… | pass/fail | pass/fail | pass/fail | pass/fail | pass/fail | YYYY-MM-DD |

## Implementation Log

Stage 4 Code-Agent + Approach-Probe. Dated entries. What built / surprised / changed-from-plan.

### YYYY-MM-DD — Approach Probe (task N)
- Sketches considered: A (…), B (…), C (…)
- Selected: <letter> — why
- Rejected: … — why

### YYYY-MM-DD — Implementation
- Built: …
- Surprised: …
- Deviation from plan: …

---

## Decision / Outcome

Required by `archived/*`. Stage 4 Doc-Sync-Agent populates the checklist; user signs off after testing the branch locally + merging.

**Result**: implemented | superseded | abandoned
**Why**: …
**Rejected alternatives:**
- …

**Code references**: PR #…, commits …, files …

**Performance achieved** (vs `## Performance Budget`):
- <path> — measured p95 / peak — pass/fail

**Telemetry confirmed live**:
- <marker> visible in <logs / dashboard / health endpoint>

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
- Supersedes: <slug or none>
- Superseded by: <slug or none>
