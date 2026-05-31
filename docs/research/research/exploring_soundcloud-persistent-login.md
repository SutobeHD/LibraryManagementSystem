---
slug: soundcloud-persistent-login
title: SoundCloud persistent login (refresh-token + survive restart)
owner: tb
created: 2026-05-31
last_updated: 2026-05-31
tags: []
related: []
supersedes: []
superseded_by: []
---

# SoundCloud persistent login (refresh-token + survive restart)

> **Caveman+ style.** Fragments, bullets. Drop articles/filler/hedges. No prose paragraphs.
> Word caps are **soft** — recommendations, not hard blocks. Exceed when topic complexity demands; routines may flag excess length but never truncate facts.
> State = folder + filename prefix (not frontmatter). Lifecycle = audit trail. See `../README.md`.
> Routines advance this doc **autonomously** by state. **One** user gate: `approvalgate_` — read `## Approval Summary` + `## Mockup`, then `/approve` or `/reject`. After approval you test the finished branch locally and merge it yourself.
> Section ownership: each `> ↓ Stage X — <agent>: …` marker names the agent that fills the section. Don't write into a section before its stage.

## Lifecycle

- 2026-05-31 — `research/idea_` — created from template
- 2026-05-31 — `research/drafting_` — Original Idea filled; advanced for research-draft routine
- 2026-05-31 — `research/exploring_` — drafted (scout + prior-art + risk-surface + worker + idea-verifier PASS), ready for explore

## Original Idea (verbatim — never edit)

After logging in to SoundCloud I have to log in again before almost every action, and again every time I restart the app. I want the login to persist — stay signed in across app restarts and across all SoundCloud features (browse, library sync, downloads) until I explicitly log out.

---

> ↓ Stage 1 — `drafting_`. `research-draft` fills Problem → Research Plan via 4 agents (Scout, Prior-Art, Risk-Surface, Worker). Verifier fills Idea Verification.

## Prior Art

- **Shipped:** [implemented_security-api-auth-hardening_2026-05-17](../archived/implemented_security-api-auth-hardening_2026-05-17.md) — Bearer + `require_session` + keyring token-handoff pattern. Covers app session token (`LMS_TOKEN`); does NOT touch SC OAuth refresh/expiry.
- **Shipped:** [implemented_security-cors-allow-credentials-tightening_2026-05-18](../archived/implemented_security-cors-allow-credentials-tightening_2026-05-18.md) — bearer-in-header only, no auth cookies. Constrains: SC refresh must not add cookie-auth.
- **Active:** [inprogress_security-mobile-paired-tokens-phase2](../implement/inprogress_security-mobile-paired-tokens-phase2.md) — hashed-token `auth.db` + `last_seen_at` throttle. Reusable storage pattern if keyring rejected.
- **Active:** [accepted_downloader-unified-multi-source](../implement/accepted_downloader-unified-multi-source.md) — downloads depend on SC auth; token expiry mid-download must not break flow.
- **External precedent:** SoundCloud OAuth 2.1 (`secure.soundcloud.com`) issues `refresh_token` + `expires_in` (~1h) for auth-code grant; `grant_type=refresh_token` renews (RFC 6749 §6). Verify in explore.
- Verdict: **greenfield** for SC token persistence/refresh — reuses existing auth infra, no overlap/duplication.

## Problem

SC OAuth access token ~1h TTL. App persists only bare access token (`app/main.py:3509`); `refresh_token` + `expires_in` arrive from SC but get discarded in Rust (`soundcloud_client.rs:107-115,232`), in the frontend, and in the backend (`ScAuthTokenReq` = 1 field, `app/main.py:3474`). No renewal path. On expiry every SC action 401s → forced interactive browser re-login (`api.js:168`). Restart shows false "logged in" (existence-only `auth-status`, `app/main.py:3534`). Cost: constant re-login; long sync/download breaks mid-flight.

## Goals / Non-goals

**Goals**
- SC login survives app + sidecar restart — no re-login on next launch.
- Token renews **silently server-side** — no browser popup until refresh genuinely fails.
- One shared auth state across all SC features (browse, library sync, downloads).
- Long-running download/sync survives token expiry mid-operation.
- Explicit logout still wipes all SC credentials.

**Non-goals**
- First-time interactive OAuth login unchanged (Rust PKCE flow stays).
- No multi-account / account switching.
- No new OAuth scopes.
- No cookie-based auth (forbidden, `coding-rules.md:16`).
- App session-token (`LMS_TOKEN`) auth untouched.

## Constraints

- **External API / rate limits:** SoundCloud OAuth `secure.soundcloud.com` — `AUTH_URL` `src-tauri/src/soundcloud_client.rs:89`, `TOKEN_URL` :90. Access token short-lived; renew via `grant_type=refresh_token`. Exact TTL + whether SC rotates/expires refresh tokens = OQ1/OQ2.
- **Token never-log:** `.claude/rules/coding-rules.md:15` + `docs/SECURITY.md:167,169` — never log token at any level; `refresh_token` falls under the same rule.
- **Bearer-only, no cookie auth:** `.claude/rules/coding-rules.md:16` — refresh path must not introduce `set_cookie`.
- **Secrets:** `SOUNDCLOUD_CLIENT_ID/SECRET` in `.env` only (`.claude/rules/coding-rules.md:13`); refresh grant needs `client_secret` — already present in Python `.env` + Rust config.
- **Keyring storage:** `KEYRING_SERVICE`/`KEYRING_SC_TOKEN` `app/main.py:76,78`; store at :3509, logout-delete at :3514. New `refresh_token` + `expires_at` need extra keys / blob.
- **Schicht-A pinning:** `.claude/rules/coding-rules.md:7` — deps `==X.Y.Z`. `requests==2.33.1` (`requirements.txt:20`) + `keyring==25.7.0` (`requirements.txt:45`) already pinned + already used by SC code.
- **No `requests` in async:** `.claude/rules/coding-rules.md:35`. Existing SC code is sync `requests` (`app/soundcloud_api.py:20`, `app/soundcloud_downloader.py:69`); refresh call must fit that context (sync helper / executor) → OQ3.
- **Auth gating + rate-limit:** `/api/soundcloud/auth-token` behind `require_session` + `@rate_limit(steady=5,burst=10)` `app/main.py:3481-3482`; a new refresh route needs both.
- **Concurrency invariants:** `_db_write_lock` / `validate_audio_path` / `SafeAnlzParser` — N/A (no `master.db` write, no filesystem path, no ANLZ).

## Dependencies

Baseline: **None — uses existing stack only.** Refresh reuses pinned `keyring` (store) + `requests` (refresh-grant POST, matches existing SC code). `httpx` only if explore (OQ3) picks async-by-the-book refresh → then a new Schicht-A dep.

| Dep | Kind | Version | License | Schicht-A audit needed? | Why |
|---|---|---|---|---|---|
| keyring | py | 25.7.0 (`requirements.txt:45`) | MIT | no — already pinned/used | store `refresh_token` + `expires_at` |
| requests | py | 2.33.1 (`requirements.txt:20`) | Apache-2.0 | no — already pinned/used | refresh-grant POST (matches `soundcloud_api.py`) |
| httpx | py | absent/unpinned | BSD-3 | yes — only IF added | only if async refresh chosen (OQ3) |

## Open Questions

1. Does SoundCloud's PKCE auth-code flow return a usable `refresh_token` + `expires_in`, and does `grant_type=refresh_token` mint a fresh access token without re-prompting? (yes/no — SC docs + already-deserialized struct fields `soundcloud_client.rs:107-115`).
2. Does SoundCloud rotate the `refresh_token` on each refresh (must re-store the new one), and do refresh tokens themselves expire? (rotate yes/no; refresh-TTL value).
3. Where does the refresh grant run — Python (reuse sync `requests`, `client_secret` from `.env`) vs Rust (`soundcloud_client.rs`, secret already there)? Sync `requests` vs httpx-async per `coding-rules.md:35`? (Python vs Rust).
4. Credential storage shape — keyring multi-key (`sc_refresh_token`, `sc_token_expiry`) vs single JSON blob under `sc_token` vs reuse `auth.db` (paired-tokens phase2)? (multikey vs blob vs auth.db).
5. Refresh trigger — proactive (on launch / when `now > expires_at − buffer`) vs reactive (on 401, retry-once) vs both? (which strategy).
6. Should `/api/soundcloud/auth-status` report real validity/refreshability instead of existence-only (`app/main.py:3534`)? (existence vs validity).
7. Frontend rework — replace interactive `_refreshScToken` → `invoke('login_to_soundcloud')` (`api.js:168`) with a silent backend `POST /api/soundcloud/refresh`; scope the 401 interceptor to SC URLs only (does it currently fire on non-SC 401s? `api.js:227`); share auth state across the 3 views. (confirm approach).
8. Logout ceremony — explicit logout must delete access + refresh + expiry (today only `sc_token` cleared, `app/main.py:3514`). (enumerate keys to clear).

## Research Plan

- Agent 1 (web + codebase): SoundCloud OAuth token semantics — `refresh_token` issuance, `expires_in` value, refresh-token rotation + expiry, `grant_type=refresh_token` request/response shape (SC dev docs) cross-checked vs `soundcloud_client.rs:107-234`. Covers OQ1, OQ2.
- Agent 2 (codebase + web): refresh ownership Rust-vs-Python — `client_secret` location, sync `requests` vs httpx-async constraint (`coding-rules.md:35`, `soundcloud_api.py:20`), how async routes invoke sync SC helpers. Covers OQ3, OQ7-async.
- Agent 3 (codebase): credential storage shape — keyring multi-key vs JSON blob vs `auth.db` reuse (paired-tokens phase2); never-log compliance; logout clear-all set. Covers OQ4, OQ8.
- Agent 4 (codebase): renewal trigger + `auth-status` validity + frontend interceptor/per-view rework (`api.js:227-249`, `SoundCloudView.jsx:15`, `SoundCloudSyncView.jsx:219`). Covers OQ5, OQ6, OQ7.

## Idea Verification

### 2026-05-31 — PASS
- **Intent fidelity:** clean — all 3 wants (restart-persist, silent per-action renewal, logout-wipe) map to Goals; Non-goals fence scope-creep.
- **Prior-art:** clean — 4 adjacent docs classified (overlap / constraint / reusable); greenfield verdict justified.
- **Research-Plan:** clean — 8 OQs all decidable, each maps to ≥1 agent, no orphans either way.
- Citations spot-checked (`main.py:3474/3509/3534`, `soundcloud_client.rs:107-115`, `api.js:168`, `requirements.txt:20/45`) — accurate.

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
