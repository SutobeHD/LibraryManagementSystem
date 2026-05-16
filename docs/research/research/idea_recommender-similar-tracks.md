---
slug: recommender-similar-tracks
title: Similar-tracks recommender for a given seed track
owner: tb
created: 2026-05-15
last_updated: 2026-05-15
tags: []
related: [recommender-rules-baseline, recommender-taste-llm-audio]
---

# Similar-tracks recommender for a given seed track

> **State**: derived from filename + folder. Do not store state in frontmatter.
> Start the file as `docs/research/research/idea_<slug>.md`. Rename + move on each transition (see `../README.md`).

## Lifecycle

> Append-only audit trail. One line per `git mv`. Newest at the bottom.

- 2026-05-15 — `research/idea_` — created from template
- 2026-05-15 — research/idea_ — section fill (research dive)

---

## Problem

> Required from `idea_` onward. Keep under 100 words. What are we solving? Why does it matter? What happens if we don't?

Given a **seed track**, return tracks from the **local library only** that sound or feel similar. Pure offline — no SoundCloud, no online sources, no network calls. Useful for in-library exploration ("I like this — what else of mine is like it?"), playlist building from a seed, and rediscovering forgotten tracks.

**Scope boundary:** this is the **local-only** similar-tracks feature. The existing recommender docs are the SoundCloud / online-focused work and address a different surface:

- [exploring_recommender-rules-baseline.md](exploring_recommender-rules-baseline.md) — primarily online ("next track" / harmonic mixing into a SoundCloud candidate stream).
- [exploring_recommender-taste-llm-audio.md](exploring_recommender-taste-llm-audio.md) — taste-aware, also online-leaning.

Where the local ranking baseline can be **shared** (feature vectors, audio embeddings, similarity metric), that's a bonus, not a dependency. This doc owns the local similar-tracks UX, API, and ranking decisions independently.

## Goals / Non-goals

**Goals**
- Given any seed track in the local library, return a ranked list of similar-sounding / similar-feeling tracks **from the same local library**.
- Pure offline: zero network, zero SoundCloud, zero cloud inference. Works with the laptop disconnected.
- Explainable: each result ships a `reasons` list (e.g. "MFCC cosine 0.91", "shared MyTag: dark, peak-time", "key 8A", "energy 0.62 ≈ seed").
- Fast: ≤ 100 ms over a 50k-track library on a developer laptop (matches the Teil-1 budget).
- Reuse, don't duplicate: consume feature vectors / embeddings that already exist (or that Teil-2's local pipeline produces) — do not run a parallel analysis pipeline.
- Filters at query time: exclude same-artist, same-playlist, BPM/key/duration window, exclude recently-played.

**Non-goals** (deliberately out of scope)
- Any online candidate source (SoundCloud, Spotify, last.fm, web embedding APIs). The two existing recommender docs own that surface.
- "Mixes well into" / harmonic-next-track answers (that's Teil 1's `local` mode — different question, different ranking).
- Personalisation from play history. This recommender is seed-driven, not user-driven. Personalisation lives in Teil 2.
- Recommending tracks not in the local library. Pure in-library exploration only.
- Auto-DJ / beat-aligned mixing.
- Training new ML models. Off-the-shelf or feature-engineering only.

## Constraints

> External facts that bound the solution space — API rate limits, existing data shape, performance budgets, legal/licensing, team capacity. Cite source where possible.

- **Available track features today** (per Teil-2 codebase audit): `app/analysis_engine.py` already produces BPM, musical key, LUFS, spectral centroid/rolloff/flatness/bandwidth, MFCC mean+std (13 coefficients), chroma mean (12 pitch classes), tempo variability. `app/audio_analyzer.py` is the async `ProcessPoolExecutor` wrapper around it. No re-decoding needed.
- **MyTag membership** is exposed via `app/live_database.py` (flat tags, multi-per-track — see Teil-1 audit). Usable as a categorical similarity signal.
- **Static metadata signals** from Rekordbox: `Rating`, `Color`, `PlayCount`, `Genre` — all read-only at import; usable for tie-breaking but not as primary similarity.
- **No play-history table exists yet** (Teil-2 constraint). This doc cannot depend on play recency; if Teil 1 lands the `plays` table, "recently played" filtering becomes available — until then, treat as future-optional.
- **Local-first hard rule** (per `README.md` + Teil-2 constraints): no network calls in the request path. Embedding extraction, if any, runs offline at analysis time.
- **Rekordbox `master.db` is schema-frozen**: any new per-track payload (embedding vector, similarity cache) lives in a sidecar SQLite or flat file keyed by track ID.
- **Performance budget**: ≤ 100 ms for top-N over 50k tracks on a dev laptop. Rules out per-query re-extraction; vectors must be precomputed.
- **No new heavy deps for v1**: stay within the existing Python stack. PyTorch / FAISS / sqlite-vss are Teil-2 questions — this doc can run on numpy + sklearn `NearestNeighbors` or a brute cosine if Teil 2 hasn't shipped vectors yet.

## Open Questions

> Numbered. Each one should be resolvable (yes/no, or "X vs Y"), not open-ended philosophy.

1. **Shared vector pipeline with Teil 2** — does this doc *consume* whatever vector representation Teil-2 lands on (Option A handcrafted or Option B CLAP/MERT), or build its own minimal vector from `analysis_engine.py` outputs and ship before Teil 2 decides? Answer determines whether this can ship standalone.
2. **Similarity metric** — cosine over a single concatenated vector vs. weighted sum of per-feature distances (MFCC cosine + chroma cosine + |Δ BPM| Gaussian + |Δ LUFS|) vs. learned metric (skip for v1)?
3. **Mode switch vs. strict separation** — should the UI offer a toggle that re-ranks Teil-1 "mixes well" results by this doc's "sounds like" score (combined mode), or are the two features kept fully separate (separate context-menu entries)?
4. **UX entry points** — context-menu on a track row → "Find similar in library", a persistent sidebar panel that updates on selection, or both? Sidebar adds state-management cost.
5. **Default filters** — should same-artist be excluded by default (forces discovery) or included (user may want more by the same artist)? Same for same-playlist.
6. **BPM / key constraints as filters or as score components?** Strict filters mean fast SQL prefilter before vector search. Score components mean smoother ranking but full-library scan.
7. **Result count + diversity** — top 20 by raw score, or apply MMR-style diversity reranking to avoid 20 near-duplicates from the same album?
8. **Caching** — cache "similar(seed_id)" results keyed by seed_id + filter hash? Invalidation on library change is non-trivial; may not be worth it if queries are ≤ 100 ms.
9. **Cold-start for newly-imported tracks** — if a track has no analysis vector yet, should it be silently skipped from candidates, or trigger on-demand analysis?
10. **Where does the vector store live** — sidecar SQLite table next to `master.db`, flat `.npy` per track, or in-memory loaded on sidecar boot? Tied to OQ-1 (shared with Teil 2 means same storage).

## Findings / Investigation

> Required from `exploring_` onward. Append dated subsections as you learn. Never edit past entries — supersede with a new one.

### 2026-05-15 — initial codebase + scope audit

Confirmed signal sources for a **local-only** seed-based similarity ranker exist today, without writing any new analysis code:

- `app/analysis_engine.py` already outputs BPM, musical key, LUFS, spectral centroid/rolloff/flatness/bandwidth, MFCC mean+std (13 coeff), chroma mean (12 bins), tempo variability — verified via grep + cross-ref to the Teil-2 audit (`exploring_recommender-taste-llm-audio.md:114-118`). A ~40-dim handcrafted vector is reachable with zero new deps.
- `app/audio_analyzer.py` is the async wrapper; ingest is already happening for every imported track.
- `app/live_database.py` exposes MyTag CRUD (Teil-1 audit, lines 283-1130) — usable as a categorical overlap signal. Rekordbox `Rating` / `Color` / `PlayCount` / `Genre` are static columns available as tie-breakers.
- No `plays` table yet (Teil-2 finding) — "recently played" filter is future-optional, dependent on Teil 1 landing it.

**Scope clarity vs. existing docs:**
- Teil 1 (`exploring_recommender-rules-baseline.md`) answers "what mixes well after this?" — harmonic / BPM-driven, has a SoundCloud mode.
- Teil 2 (`exploring_recommender-taste-llm-audio.md`) answers "what does this user want?" — personalised, embedding-based, online-capable.
- This doc answers "what else in my library sounds like this?" — seed-driven, no personalisation, no online sources. Candidate pool is **strictly** `local tracks \ {seed}`.

**Sharing surface:** the vector pipeline (Teil 2 Option A or B) is the natural shared primitive. This doc consumes vectors; it does not depend on Teil-2's user-taste centroid, ranking, or SC candidate-fetch code. If Teil 2 hasn't shipped vectors, this doc can ship with handcrafted features as v1 and migrate later.

**Performance feasibility:** 50k × 40-dim float32 = ~8 MB. Brute cosine in numpy is sub-50 ms cold. `sklearn.NearestNeighbors` or FAISS only become attractive at ≥ 500k tracks. ≤ 100 ms budget is easily achievable.

## Options Considered

> Required by `evaluated_`. For each viable approach: sketch (2-4 lines), pros, cons, effort (S/M/L/XL), risk.

### Option A — Handcrafted vector + brute cosine over local library
- **Sketch**: Build a ~40-dim vector per track from existing `analysis_engine.py` outputs (MFCC mean+std, chroma mean, BPM, LUFS, spectral stats). Precompute on import, store in sidecar SQLite. Query = cosine vs. all rows, top-N. Reasons = per-feature subscore breakdown.
- **Pros**: Zero new deps. Ships independent of Teil 2. Fast (<50 ms over 50k). Explainable.
- **Cons**: MFCCs miss high-level semantics (vocal vs. instrumental). Quality ceiling lower than learned embeddings.
- **Effort**: M
- **Risk**: Low — worst case "feature-space close but vibe-wrong"; still useful.

### Option B — Consume Teil-2's learned embedding (CLAP / MERT) once it lands
- **Sketch**: Wait for Teil-2 to pick an embedding model, reuse its per-track vector + storage. This doc adds only the query-side: cosine top-N over local tracks, filters, reasons.
- **Pros**: Best quality similarity. Single shared pipeline. No duplicate infra.
- **Cons**: Hard dependency on Teil-2 decision + installer-size impact. Blocks shipping until Teil 2 chooses.
- **Effort**: S (query side only) but blocked
- **Risk**: Medium — slippage risk inherited from Teil 2.

### Option C — Hybrid: handcrafted + categorical (MyTag / genre / key) weighted score
- **Sketch**: Option A's cosine plus discrete bonuses for shared MyTag, same Genre, same Camelot key, |Δ BPM| Gaussian. Weights configurable per query.
- **Pros**: Explainable reasons map directly to feature names. Captures DJ-meaningful overlaps MFCCs alone miss. Still no new deps.
- **Cons**: Weight tuning hell (same OQ as Teil 1). Two-system feel.
- **Effort**: M
- **Risk**: Low.

### Option D — Approximate-NN index (FAISS / sklearn) over Option A or B vectors
- **Sketch**: Build a FAISS `IndexFlatIP` or `IVF` from precomputed vectors. Persist to disk; reload on sidecar boot.
- **Pros**: Scales beyond 50k. Sub-ms queries.
- **Cons**: Premature at current library scale — brute cosine is already ≤ 50 ms. FAISS adds a heavy dep + bundling pain (PyInstaller / Tauri sidecar).
- **Effort**: L
- **Risk**: Medium — installer + bundling.

## Recommendation

> Required by `evaluated_`. Which option, what we wait on before committing.

**Leaning: Option C (handcrafted vector + categorical weighting) for v1**, with a migration path to Option B when Teil 2 lands.

Rationale:
- Ships standalone, no dependency on Teil-2 decisions still in flight.
- Uses primitives already produced by `analysis_engine.py` — no new analysis pass, no new deps.
- Categorical bonuses (MyTag overlap, shared genre, key proximity) catch DJ-meaningful similarity that pure MFCC cosine misses, and feed the reasons list naturally.
- Brute cosine over ≤ 50k vectors meets the 100 ms budget — FAISS / ANN can be deferred until library scale demands it.
- When Teil 2 commits to a learned embedding, the vector source swaps but the query API, filters, reasons-list shape, and UX stay identical.

**Gate before promoting to `evaluated_`**: resolve OQ 1 (share with Teil 2 vs. ship standalone), OQ 3 (mode switch vs. strict separation from Teil 1), OQ 4 (UX entry point), and OQ 6 (BPM/key as filters vs. score components).

---

## Implementation Plan

> Required from `implement/draftplan_` onward. Concrete enough that someone else could execute it without re-deriving the design.

### Scope
- **In:** …
- **Out (deliberately):** …

### Step-by-step
1. …
2. …

### Files touched (expected)
- …

### Testing approach
- …

### Risks & rollback
- …

## Review

> Filled by reviewer at `review_`. If any box is unchecked or rework reasons are listed, the doc moves to `rework_`.

- [ ] Plan addresses all goals
- [ ] Open questions answered or explicitly deferred
- [ ] Risk mitigations defined
- [ ] Rollback path clear
- [ ] Affected docs identified (`architecture.md`, `FILE_MAP.md`, indexes, `CHANGELOG.md`)

**Rework reasons** (only if applicable):
- …

## Implementation Log

> Filled during `inprogress_`. What got built, what surprised us, what changed from the plan. Dated entries.

### YYYY-MM-DD
- …

---

## Decision / Outcome

> Required by `archived/*`. Final state of the topic.

**Result**: `implemented` | `superseded` | `abandoned`
**Why**: …
**Rejected alternatives** (one line each):
- …

**Code references**: PR #…, commits …, files …

**Docs updated** (required for `implemented_` graduation):
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
