---
slug: recommender-rules-baseline
title: Deterministic rules-based track recommender (Teil 1 — baseline / Mixxx-style "next track")
owner: unassigned
created: 2026-05-11
last_updated: 2026-05-15
tags: [recommender, soundcloud, mixing, harmonic, baseline]
related: [recommender-taste-llm-audio, recommender-similar-tracks]
ai_tasks: false
---

# Deterministic rules-based track recommender (Teil 1)

> Caveman+. State = folder + filename. See `## Lifecycle` for transitions.

## Lifecycle

- 2026-05-11 — `research/idea_` — created as Teil 1 of recommender split
- 2026-05-11 — `research/exploring_` — codebase audit captured, options A-D documented, recommendation drafted
- 2026-05-15 — research/exploring_ — scope clarification re: new local-only sibling doc
- 2026-05-15 — research/exploring_ — deeper exploration pass (toward evaluated_ readiness)

## Problem

Seed track in → ranked list of next tracks out. Source = local Rekordbox library OR SoundCloud feed. Signal = data already present at zero cost: BPM, key, genre, energy, MyTag overlap. Camelot harmonic-mixing surface is the headline use.

Dumb/predictable half of the recommender split. Answers *"what mixes well after this?"* — not *"what does this user want?"*. Personalised half: [recommender-taste-llm-audio](exploring_recommender-taste-llm-audio.md). Local seed-similarity ("what else sounds like this?"): [recommender-similar-tracks](exploring_recommender-similar-tracks.md). This doc owns the **online "next track"** + **library harmonic-mix** surface.

Doubles as:
- Harmonic-mixing assistant (Camelot wheel core).
- Baseline the Teil-2 personalised ranker must beat in user A/B testing.
- Cold-start fallback (brand-new track, brand-new user, sparse taste data).

## Goals / Non-goals

**Goals** (each ships with a measurable acceptance metric)

- **Two modes** — `local` (rank from `master.db`) + `soundcloud` (rank from SC `/related` candidates). **Metric**: `GET /api/recommend/{local|soundcloud}?track_id=X` returns ≥ 5 results for any seed with valid BPM + key on a 50-seed eval set.
- **Fully deterministic** — same seed + same settings → same output. **Metric**: 100 repeat-call test, hashed output identical; zero `random`/`secrets`/`time.time()` calls in ranker module.
- **Explainable** — each result row carries `reasons: list[str]` with ≥ 2 entries derived from per-feature subscores ≥ 0.05. **Metric**: unit test asserts every result row in 50-seed eval has ≥ 2 reasons.
- **Latency** — local mode P95 ≤ 100 ms for top-20 over 50k tracks on dev laptop (i7-12700H, 32 GB), measured `pytest-benchmark` in `tests/test_recommender_perf.py`. SC mode unbounded (API-latency dominated, NOT our budget).
- **Reuses existing analysis output** — zero new librosa calls in ranker module. Reads `bpm`, `camelot`, `key`, `mood.brightness`, `genre_hint` straight from analysis cache + `master.db`. **Metric**: zero `import librosa` / `import essentia` in `app/recommender.py`.
- **Auth-gated** — both routes wrap `Depends(require_session)` once Phase-1 of [security-api-auth-hardening draftplan](../implement/draftplan_security-api-auth-hardening.md) ships. **Metric**: route audit table marks `/api/recommend/*` as `auth=required`.
- **Settings per-call** — query params at first. Persistence parks (OQ 8).

**Non-goals**

- Beat-aligned auto-mixing (separate Auto-DJ scope).
- Learning from user behaviour (Teil 2).
- Local seed-similarity ("sounds like this") — owned by [recommender-similar-tracks](exploring_recommender-similar-tracks.md).
- Cross-library similarity ("SC tracks like my library cluster X") — Teil 2.
- New ML training, embeddings, FAISS — all park to Teil 2 / scale-driven.

## Constraints

Re-verified 2026-05-15 against post-hotfix code (commit `e3a5ae8`).

- **BPM + key + camelot persisted today** — `app/analysis_engine.py:2162-2175` returns `bpm`, `bpm_raw`, `key`, `camelot`, `openkey`, `key_id`, `key_confidence`. Camelot already normalised by `_CAMELOT_MAP` (`analysis_engine.py:200`) → **no key-to-Camelot mapper needed in recommender** (this doc previously claimed one was needed; obsolete).
- **Energy signal** — NOT a single scalar. Closest: `mood.brightness` + `mood.warmth` + `mood.texture` (ZCR) + `mood.spectral_centroid` + `mood.spectral_rolloff` at `analysis_engine.py:2194`. Per-phrase energy lives in `phrases[].energy` at line 1203 — track-level rollup (mean + std) does NOT exist. **Implication**: pick one scalar proxy for M1 (`mood.brightness`, in [0,1]) — track-level energy aggregation is M2-or-Teil2 work.
- **Genre signal** — `genre_hint` at line 2195, single string. Rekordbox `Genre` column (multi-class, user-edited) also available via `master.db`. M1 uses `genre_hint` for SC candidates (no Rekordbox metadata available there) and Rekordbox `Genre` for local candidates.
- **MyTag membership** — `app/live_database.py:902-994` (NOT 283-1130; older line range obsolete). API: `list_mytags`, `get_track_mytags`, `set_track_mytags`, `create_mytag`, `delete_mytag`. Flat tags, multi-per-track. In-memory snapshot loaded once at `_load_mytags` (line 141). **Implication**: cheap O(1) tag lookup for ranker, no per-query DB hit.
- **SC `/tracks/{id}/related` + `/stations/track:{id}` not called today** — re-verified: grep `related|stations` in `app/soundcloud_api.py` finds zero matches (only a download-link comment at line 319). Both endpoints need to be added. Existing `_sc_get` at line 167 already handles 429 backoff + 401/403/404 → AuthExpiredError + retry → use it directly, don't re-implement.
- **Polite spacing already enforced** — `_sc_get` exponential backoff + `Retry-After` honoured at line 219-226. **No extra rate-limit code needed**.
- **Fuzzy-match shared surface** — `_fuzzy_match_with_score` at `app/soundcloud_api.py:566`, threshold `0.65` at line 583. Reusable for: (a) local seed → SC track resolution if seed has no `sc_track_id`, (b) "hide SC candidates already in library" filter (OQ 7). Cross-doc coordination: see `idea_external-track-match-unified-module.md` if extraction becomes desired (not blocking M1).
- **No new dependencies** — pure Python + existing stack. Anything heavier (FAISS, numpy embeddings) belongs in Teil 2.
- **Auth gate prerequisite** — Phase 1 of [security-api-auth-hardening](../implement/draftplan_security-api-auth-hardening.md) (now in `implement/draftplan_`, not yet shipped) defines `Depends(require_session)`. M1 ships routes **unauth** if Phase 1 not yet merged; M1.1 patches in the gate behind feature flag. Hard sequencing dependency: production rollout of `/api/recommend/*` gated on Phase 1 merge.
- **Rekordbox `master.db` read-only for this feature** — recommender NEVER writes. No `_db_write_lock` acquisition. No rbox `SafeAnlzParser` involvement (we read cached analysis output, not ANLZ files).

## Open Questions

Numbered. RESOLVED / PARKED / GATE FOR `evaluated_` flagged.

1. **Frontend scope in v1** — **GATE FOR `evaluated_`**: needs user pick. Default proposal: backend-only in M1 (curl/HTTPie testable); minimal UI (context-menu entry "Recommend next..." + side panel with mode toggle + result list w/ reason chips) lands M2 once API surface settles.
2. **Default weights** — **GATE FOR `evaluated_`**: needs user pick between (a) `bpm 0.35 / key 0.30 / genre 0.15 / mytag 0.10 / energy 0.10` or (b) key-heavy `key 0.35 / bpm 0.30 / genre 0.15 / mytag 0.10 / energy 0.10`. DJ-folklore argues (b); ship both behind `?weights_preset=bpm_first|key_first` query, default = (b) since unbeatable key clash is the more painful failure mode.
3. **BPM tolerance default** — **RESOLVED**: ship Gaussian continuous decay, default σ matches ±6% (Pioneer CDJ-3000 performance pitch range — manual confirmed). Clip at ±9% (1.5σ). Strict mode `?bpm_tol=0.03` for CDJ "auto" sync. Binary in/out tolerance rejected — UX brittle per Option A cons.
4. **Key compatibility model** — **PARTIALLY RESOLVED**: Camelot wheel core (same, +1, -1, relative = 1.0/0.7/0.7/0.7). +7 perfect-fifth jump = M2 toggle (`?key_extended=true`). User-defined whitelist parks. Strict mode `?key_strict=true` = only same-key. **GATE FOR `evaluated_`**: confirm relative-major-minor weight (0.7 vs full 1.0) with user — Mixed-In-Key UX gives full credit.
5. **Half/double-time matching** — **PARKED to M2**. 174↔87 BPM dnb-half-time is genre-specific (drums dnb yes, ambient no). Risk of false positive too high without genre gate. Re-evaluate post-M1 if user complains "missing the obvious dnb-jungle pairs".
6. **SoundCloud candidate sources** — **RESOLVED**: M1 = `/tracks/{id}/related` only (curated, ~20 results, deterministic). `/stations/track:{id}` = M2 toggle (`?source=related|station|both`). Union+dedup parks until usage data shows demand. Justification: `/related` is cheaper, simpler to reason about, sufficient signal for M1 quality bar.
7. **Filtering already-in-library** — **RESOLVED**: SC mode filters out candidates whose fuzzy-match score against local library ≥ 0.85 (stricter than the 0.65 sync threshold — false-positive cost is high for this filter). Toggleable via `?hide_owned=true|false`, default `true`.
8. **Settings persistence** — **PARKED to M2**. M1 = query params only. Persistence requires settings UI (not in M1 scope per OQ 1). Persisted config goes into `app_data/recommender_settings.json` (NOT `analysis_settings.py` — different lifecycle).
9. **Result limit + pagination** — **RESOLVED**: hard cap `limit=20` default, max 50. No pagination M1 — local mode sort is O(n log n) over ~50k, fits in latency budget; SC mode is bounded by `/related` returning ~20 anyway. Pagination = M2 if/when "list me 200 next-track candidates" surface appears.
10. **Recording recommendation events** — **RESOLVED for M1**: log to `app_data/recommendations.log.jsonl` with `{ts, seed_id, mode, weights_preset, returned_track_ids: [...], latency_ms}`. JSONL append-only, rotate at 100 MB. Justification: cheap insurance for Teil-2 baseline comparison ("did the dumb ranker pick the same N as the taste ranker?"). NO PII (no user query strings or free-text). Gated on `?log_events=true` default true; toggle for tests.
11. **NEW: Multi-seed input?** — **PARKED to Teil 2**. M1 single-seed only. Multi-seed averaging is a centroid problem (geometric mean of feature vectors) — fits the personalised ranker better. Document explicitly so users don't ask "why doesn't /recommend take track_ids[]?".

## Findings / Investigation

### 2026-05-11 — split-out from initial discussion
- Originally framed as "implement now" in the planning session, then re-scoped to "research first, like Teil 2" — both halves of the recommender split live here as research before code.
- Code audit findings reused from [recommender-taste-llm-audio.md](exploring_recommender-taste-llm-audio.md):
  - `analysis_engine.py` already produces BPM/Key/Genre/Energy/MyTag-compatible outputs.
  - `soundcloud_api.py` has OAuth + rate-limit handling, but does **not** call `/tracks/{id}/related` or `/stations/track:{id}` yet — both endpoints need to be added.
  - `SoundCloudSyncEngine` has a fuzzy title/artist matcher (threshold 0.65) — reusable to (a) resolve local seed → SC track and (b) filter SC candidates against existing library.
  - `live_database.py:283-1130` exposes MyTag CRUD — flat tags, multi-tag per track.
- Captured the four "stellschrauben" raised during initial design (frontend scope, default weights, BPM tolerance shape, key model) as open questions 1-4.
- Added open question 10 (logging recommendation events) — cheap to add up front, valuable when Teil 2 lands and needs comparison data.

### 2026-05-15 — scope clarification + sibling doc landed

Sibling [recommender-similar-tracks](exploring_recommender-similar-tracks.md) (promoted from `idea_` → `exploring_` same day) carves out the **local-only similar-tracks** surface ("what else of mine sounds like this?"). Owns its own UX/API/ranking decisions. This Teil 1 doc retains its `local` mode but emphasises the **harmonic-mix / SC-online** surface — the local mode here answers "mixes well after this?" (harmonic transition), NOT "sounds like this?" (similarity).

Open-question recheck (recent commits — `cc171ee` backup-engine drop, `8fe5036` route removal, `bd8c0f7` live_database typing — all orthogonal to recommender; OQs unchanged at this point).

### 2026-05-15 — deeper-exploration pass (toward evaluated_)

Re-verified codebase state post hotfix commit `e3a5ae8` (5 security findings landed). Concrete corrections vs the original doc:

- **Camelot mapper claim was wrong** — `_CAMELOT_MAP` already lives at `app/analysis_engine.py:200` and every analysed track ships `camelot` field at line 2171. No new mapper code needed. Removed constraint.
- **MyTag line range corrected** — actual: `live_database.py:902-994`. Old claim `283-1130` was the file when MyTag CRUD plus its in-memory cache were considered together (cache load at `_load_mytags()` line 141).
- **Energy is NOT a track-level scalar** — `mood.brightness` is the closest proxy (in [0,1], available at `analysis_engine.py:2194`). Track-level energy aggregation requires new code → M2 scope, not M1.
- **Genre signal is dual-track** — `genre_hint` (analysis output) vs Rekordbox `Genre` (user-edited metadata). Pick per-mode: local → Rekordbox `Genre` (user truth), SC → `genre_hint` (no Rekordbox metadata available for SC candidates).
- **SC `/related` + `/stations` confirmed not implemented** — re-grep zero matches in `app/soundcloud_api.py`. `SoundCloudPlaylistAPI` (line 239) has 11 methods, none for related/stations. Net-new endpoints required.
- **Fuzzy threshold confirmed** — `_fuzzy_match_with_score` at line 566, threshold `0.65` at line 583. Hide-owned filter OQ 7 uses stricter `0.85` to minimise false-positive hides.
- **Auth gate sequencing** — [security-api-auth-hardening](../implement/draftplan_security-api-auth-hardening.md) now in `implement/draftplan_`. 5 hotfixes shipped, Phase-1 broad gating NOT yet merged. Recommender routes must wrap `Depends(require_session)` once Phase 1 merges. Sequencing constraint added.
- **No play-history table exists** — verified via grep; sibling doc finding holds. "Don't recommend recently played" filter PARKS until Teil-1 ships plays table.
- **OQ resolution net**: 11 OQs total. **RESOLVED**: 3, 6, 7, 9, 10 (5/11). **PARTIALLY RESOLVED**: 4 (1/11). **GATE FOR `evaluated_`**: 1, 2, 4 (3 items needing user pick). **PARKED**: 5, 8, 11 (3/11). Quality bar met for `evaluated_` after items 1+2+4 confirmed.

**Cross-doc coordination summary** (4 sibling docs touched by this rework):
- `recommender-similar-tracks` (exploring_) — owns local seed-similarity; shares fuzzy-match dependency.
- `recommender-taste-llm-audio` (exploring_) — owns personalised ranker; this doc is its baseline-to-beat.
- `external-track-match-unified-module` (idea_) — future home for extracted fuzzy matcher.
- `security-api-auth-hardening` (implement/draftplan_) — Phase 1 gate sequencing.

## Options Considered

### Option A — Pure rule-based, binary tolerance (no continuous decay)
- **Sketch**: Candidate passes if `|Δbpm|/bpm_seed ≤ tol` AND key ∈ Camelot compat set AND `|Δenergy| ≤ 0.15`. Score = count of binary feature matches.
- **Pros**: Trivial to implement (~150 LOC), <10 ms even on 50k.
- **Cons**: Cliff at ±tol — a track at ±6.01% BPM never appears even if 10/10 mix otherwise. UX feels brittle. No graceful degradation if no candidate matches.
- **Effort**: S
- **Risk**: Low — but UX risk high (user complains "missed the obvious match").

### Option B — Continuous score with weighted feature distances (recommended for M1)
- **Sketch**: Each feature contributes [0,1] based on closeness. BPM = Gaussian (σ tied to tol). Key = Camelot-distance table (same=1.0, ±1/rel=0.7, ±2=0.3, else=0). Genre = 1.0/0.0. MyTag = `overlap / max(seed_tags, cand_tags)`. Energy = `1 - |Δbrightness|`. Weighted sum → final [0,1]. Reasons list = features contributing ≥ 0.05.
- **Pros**: Smooth ranking. Weight-tunable without structural change. Reasons emerge naturally. Honours latency budget (single pass + sort, ~30-50 ms on 50k per dev benchmark of similar pipeline in sibling doc).
- **Cons**: ~300-400 LOC. Needs distance tables. Weight-tuning needs an eval-set or user A/B.
- **Effort**: M
- **Risk**: Low — weights can be re-tuned post-ship without API change.

### Option C — Multi-criteria sort instead of single score
- **Sketch**: Hard-filter by BPM ± tol + key compat. Sort remaining by lexicographic key (genre match → MyTag overlap → energy distance).
- **Pros**: Deterministic, no weight-tuning. ~200 LOC.
- **Cons**: No graceful degradation — empty result if hard constraints don't match. User can't relax without re-running with explicit tol bump. Worse UX than B for cold/small libraries.
- **Effort**: S
- **Risk**: Medium — empty-result UX cliff.

### Option D — Graph-based: precompute compatibility graph offline
- **Sketch**: Build track-to-track graph, edges = compatibility score. Query = neighbour lookup. Reusable for "build 60-min set from seed".
- **Pros**: O(1) query on huge libraries. Reusable substrate for set-building.
- **Cons**: Premature at 50k where B is already <100 ms. Graph maintenance on every library change is non-trivial (add/delete/re-analyse invalidates row + neighbours). ~700-1000 LOC.
- **Effort**: L
- **Risk**: High — invalidation bugs are silent and pollute recommendations.
- **Park** until scale ≥ 500k tracks OR set-building surface lands.

## Recommendation

**Option B (weighted continuous score)** for M1 ranker. Sequenced into **M1 / M1.1 / M2**.

### M1 — Backend MVP (deliverable: routes + ranker + tests)

New module `app/recommender.py`. New routes in `app/main.py`:

```
GET /api/recommend/local?track_id=X&limit=20
    [&bpm_tol=0.06&key_strict=false&weights_preset=key_first|bpm_first]
GET /api/recommend/soundcloud?track_id=X&limit=20
    [&source=related&hide_owned=true]
```

Both return:
```json
{
  "seed": {"id": "...", "title": "...", "artist": "...", "bpm": 122, "camelot": "8A"},
  "mode": "local",
  "weights_preset": "key_first",
  "results": [
    {"track_id": "...", "score": 0.87,
     "reasons": ["bpm ±1.6%", "key 8A→9A (Camelot +1)", "genre: techno", "tags: peak-time, dark"]},
    ...
  ],
  "latency_ms": 42
}
```

**Default weights (M1)** — `key_first` preset:
| Feature | Weight |
|---------|--------|
| key     | 0.35   |
| bpm     | 0.30   |
| genre   | 0.15   |
| mytag   | 0.10   |
| energy  | 0.10   |

**BPM scoring** — Gaussian: `score = exp(-((Δbpm / (tol * bpm_seed)) ** 2))`. Clipped 0 beyond 1.5×tol.

**Key scoring** — Camelot distance:
| Δ | Score |
|---|-------|
| same         | 1.00 |
| +1, -1, rel  | 0.70 |
| +2, -2       | 0.30 |
| else         | 0.00 |

**Energy** — `1 - |brightness_seed - brightness_cand|` (M1 uses `mood.brightness` as scalar proxy).

**MyTag** — `len(seed_tags ∩ cand_tags) / max(len(seed_tags), len(cand_tags), 1)`.

**Genre** — `1.0` if equal (Rekordbox `Genre` for local; `genre_hint` for SC), else `0.0`.

**Reasons** — only features whose weighted contribution ≥ 0.05 emit a reason.

**Logging** — JSONL append to `app_data/recommendations.log.jsonl` per OQ 10.

**Tests** — `tests/test_recommender.py` (unit: ranker math + reasons), `tests/test_recommender_perf.py` (pytest-benchmark, latency budget gate).

### M1.1 — Auth gate (deliverable: feature-flag-gated)

Wrap both routes with `Depends(require_session)` from Phase-1 of [security-api-auth-hardening](../implement/draftplan_security-api-auth-hardening.md). Feature-flagged via env var if Phase 1 not yet merged at recommender ship.

### M2 — Frontend + extended modes (deliverable: UI + toggles)

- Frontend context-menu entry + side panel (gate-resolved OQ 1).
- `?source=both` for SC mode (`/related` ∪ `/stations`, deduped).
- `?key_extended=true` for +7 perfect-fifth move.
- MMR-style diversity rerank if eval shows clustering.
- Half/double-time match (OQ 5) revisit with genre-gated rule.
- Settings persistence (`app_data/recommender_settings.json`, OQ 8).

### Exit criteria — M1 → ship gate

- Top-20 returned in < 100 ms P95 over 50k synthetic tracks.
- 50-seed eval: ≥ 80% of seeds return ≥ 5 results.
- Reasons list ≥ 2 entries per row in eval.
- `ruff check app/recommender.py + tests` clean.
- `pytest tests/test_recommender*.py` green.

### Exit criteria — M2 → ship gate

- E2E test: context-menu → side panel → result chips render correctly in Tauri build.
- User A/B on 10 seeds: M2 ≥ M1 in subjective rating.

## Decision / Outcome

_Not yet decided. Status: `exploring_`._

Implementation gate (to promote `exploring_` → `evaluated_`): user sign-off on OQ 1 (frontend M1 scope), OQ 2 (default weights preset), OQ 4 (relative-major-minor weight 0.7 vs 1.0).

## Links

- Code (will be touched once implementation starts):
  - [app/analysis_engine.py](../../../app/analysis_engine.py) — feature source (BPM, camelot, mood.brightness, genre_hint at lines 2160-2200)
  - [app/live_database.py](../../../app/live_database.py) — MyTag access (lines 902-994; in-memory cache loaded at line 141)
  - [app/soundcloud_api.py](../../../app/soundcloud_api.py) — needs `/related` + `/stations` endpoints added (use existing `_sc_get` at line 167)
  - [app/main.py](../../../app/main.py) — new routes go here; auth gate via `Depends(require_session)` once Phase 1 ships
- External references:
  - Camelot wheel — https://mixedinkey.com/camelot-wheel/
  - SoundCloud API `/related` — https://developers.soundcloud.com/docs/api/reference#tracks-tracks-id-related
  - Pioneer CDJ-3000 pitch ranges — manufacturer manual (Master Tempo / Pitch sections)
- Related research:
  - [recommender-taste-llm-audio](exploring_recommender-taste-llm-audio.md) — Teil 2, personalised
  - [recommender-similar-tracks](exploring_recommender-similar-tracks.md) — local seed-similarity sibling
  - [external-track-match-unified-module](idea_external-track-match-unified-module.md) — future fuzzy-match extraction
  - [security-api-auth-hardening draftplan](../implement/draftplan_security-api-auth-hardening.md) — Phase-1 auth gate prerequisite
