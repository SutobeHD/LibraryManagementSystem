---
slug: recommender-taste-llm-audio
title: Taste-aware audio recommender (Teil 2 of the recommender split)
owner: unassigned
created: 2026-05-11
last_updated: 2026-05-15
tags: [recommender, ml, audio-analysis, soundcloud, embeddings, llm]
related: [recommender-rules-baseline, recommender-similar-tracks]
ai_tasks: false
---

# Taste-aware audio recommender (Teil 2)

> **State**: derived from filename + folder. See `## Lifecycle` for transition history.

## Lifecycle

- 2026-05-11 — `research/idea_` — created as Teil 2 of recommender split (gated by Teil 1 landing first)
- 2026-05-11 — `research/exploring_` — options A-D outlined; pending audio-embedding benchmark and Teil 1 baseline
- 2026-05-15 — research/exploring_ — scope clarification re: new local-only sibling doc
- 2026-05-15 — research/exploring_ — deeper exploration pass (toward evaluated_ readiness)

## Problem

The "Teil 1" recommender (see [recommender-rules-baseline.md](exploring_recommender-rules-baseline.md)) is a deterministic rule engine: given a seed track, return tracks whose **measurable features** (BPM, key, energy, genre tag, duration) are compatible. It works without any user history and answers the question *"what mixes well with this?"*.

It does **not** answer *"what does this user actually want next?"*. A taste-aware recommender needs to:

1. Build a representation of the user's preferences from observed behaviour (plays, skips, likes, tag patterns, dwell time, manual playlist groupings).
2. Compare candidate tracks to that representation using something richer than 5 hand-crafted features — ideally a learned audio embedding that captures timbre, production style, instrumentation, mood beyond what BPM/Key/Energy can express.
3. Combine 1 + 2 to rank candidates from the local library and/or SoundCloud.

This doc collects options and constraints so we can pick a direction later, possibly with a different model (Claude 5.x, GPT-5, local Llama, etc.) and re-evaluated audio embedding tools.

## Goals / Non-goals

**Goals** (each with measurable acceptance metric)
- Personalised "play next" / "build a set" ranking. **Metric**: NDCG@10 on a 30-seed eval set (manually scored 0/1/2 per candidate) beats Teil-1 baseline by ≥ 0.15 absolute. Eval set captured as `eval/taste_recommender_2026-05.jsonl`.
- Audio-level similarity beyond metadata. **Metric**: ≥ 4/10 audio-judged-similar in top-10 for 10 seeds where Teil-1 returns ≤ 2/10 (genre-tag-mismatched but musically aligned cases).
- Dual-mode candidate ranking. **Metric**: same `find_taste_ranked(seed_or_context, source) -> list[Result]` signature for both `source="local"` (filter from `track_vectors.db`) and `source="soundcloud"` (consume Teil-1 candidate stream + same vector store). One code path, two candidate generators.
- Local-first. **Metric**: P95 ranking latency ≤ 200 ms for top-50 over 50k local vectors on dev laptop (i7-12700H, 32 GB) — Option-A handcrafted vector. Option-B target ≤ 400 ms (extra dim cost).
- Explainable. **Metric**: every result row carries `reasons: list[str]` ≥ 2 entries — at minimum one feature-level ("BPM 122 ±2 your cluster mean") + one history-level ("matches 5 of last 20 played-to-end tracks").
- Reuse shared infra. **Metric**: zero new vector-storage tables; consumes `app_data/track_vectors.db` from sister doc (sibling owns the schema).

**Non-goals**
- Beating Spotify cold-start. Single-user library-bounded.
- Real-time training. Nightly / on-demand batch updates fine.
- Generating audio. Rank existing only.
- Replacing Teil 1. Teil 1 stays — fallback when taste data thin; canonical harmonic-mixing answer.
- Owning the vector storage schema. Sibling [recommender-similar-tracks](exploring_recommender-similar-tracks.md) owns `app_data/track_vectors.db` shape; this doc adds a `user_taste_vectors` table only.
- Multi-user / collaborative filtering. App has no shared backend; deferred to a separate opt-in cloud doc.

## Constraints

- **Local-first hard rule** (`README.md`): cloud inference opt-in per-call only. Inference on typical DJ laptop (RAM ≤ 32 GB, GPU optional). Excludes Option C (LLM-in-loop) as default path.
- **Stack**: Python 3.10+ FastAPI, Rust CPAL/Symphonia. PyTorch dep inflates installer (~200 MB wheels) + PyInstaller `backend.spec` `collect_all` cost — `backend.spec:21` currently bundles only `librosa, numba, scipy, sklearn, soundfile, audioread, lazy_loader`. Adding `torch` requires explicit cost/benefit (M2 benchmark gate, see Recommendation).
- **Persisted track-level scalars TODAY** (re-verified `app/analysis_engine.py:2152-2201`, file length 2239 LOC): `bpm`, `bpm_raw`, `key`, `camelot`, `openkey`, `key_id`, `key_confidence`, `lufs`, `replay_gain`, `peak`, `grid_confidence`, `mood.{brightness,warmth,texture,spectral_centroid,spectral_rolloff}`, `genre_hint` (categorical). Total ~12-15 useful scalars. **NOT persisted** (corrects 2026-05-11 audit overclaim): `spectral_bandwidth`, `spectral_flatness`, MFCC track-aggregated (only per-phrase at `analysis_engine.py:1132`), chroma track-aggregated (only inside `_detect_key` at lines 357-373), `tempo_variability`. Sister doc Finding 2026-05-15 #3 already corrected this.
- **Vector-extraction code is sister-doc-owned**. Sister recommended Option A handcrafted ~46-dim with NEW extraction (sister Recommendation M1). This doc consumes the same `app_data/track_vectors.db (track_id PK, vector_blob, fps_id, computed_at)` schema. No duplicate extractor.
- **Audio re-decode avoided**: existing analysis cache (`app/analysis_cache.py`) handles fingerprint-keyed reuse. Embedding extraction (Option B) piggybacks on already-decoded `y` inside `analyze_audio_full` rather than re-loading.
- **No play-history table yet** (`Grep plays|play_history` returns docstrings only). Teil-1 owns landing the `plays` table. Without it: taste signal = Rekordbox `Rating`, `PlayCount` (static at import), `Color`, MyTag membership, playlist co-occurrence, file `mtime` proxy.
- **SoundCloud rate limits**: `app/soundcloud_api.py` exponential backoff + 0.3 s polite spacing. Fetch budget per recommendation ≤ 1 call (`/tracks/{id}/related` or `/stations/track:{id}` → ~20-50 candidates), then rank locally. Multi-call per-recommendation is non-starter.
- **Library scale**: target ~1k–50k local tracks. Brute cosine over 50k × 46-dim ≤ 50 ms (sister Finding); 50k × 512-d ≤ 200 ms uncached. FAISS / sklearn ANN only attractive at ≥ 200k.
- **Rekordbox `master.db` schema-frozen**: never add taste columns there. New `user_taste_vectors` table lives in sidecar SQLite (likely same `app_data/track_vectors.db` file with separate table, or a new `app_data/taste.db`).
- **`_db_write_lock` not needed** for the new sidecar SQLite. If we ever read `master.db` (e.g., to enumerate track IDs for backfill), that read is lock-free.

## Open Questions

1. **Audio embedding source** — **PARTIALLY RESOLVED**: M1 = Option A handcrafted (inherits sister doc's vector). M2 = benchmark Option B (CLAP vs. MERT vs. OpenL3) on real dev laptop using BENCHMARK PLAN in Recommendation. Path gate = extraction time + installer-size delta thresholds defined there.
2. **Taste representation** — **PARTIALLY RESOLVED**: M1 = single recency-weighted centroid + per-cluster centroids (k=3 KMeans on user's liked-vector set) as fallback "mood mode" toggle. **GATE FOR `evaluated_`**: needs user pick on whether "mood mode" toggle ships M1 or M2. Default proposal: M2 (KISS for M1, ship centroid only).
3. **Role of LLM** — **RESOLVED**: explanation layer only, opt-in. NEVER in ranking loop (violates local-first + adds 1-3 s per call + paid). When user clicks "Why?" on a result, post-hoc call with cached candidate features. Aligns with Option D framing.
4. **Storage** — **RESOLVED** (inherited from sister doc Finding 2026-05-15 #2 / OQ10): sidecar SQLite `app_data/track_vectors.db`, schema `(track_id PK, vector_blob, fps_id, computed_at)`. This doc adds a sibling table `user_taste_vectors(profile_id PK, vector_blob, n_source_tracks, computed_at, kind)` where `kind ∈ {"centroid", "cluster_0", "cluster_1", "cluster_2", ...}`.
5. **Cold-start** — **PARTIALLY RESOLVED**: with 0 plays, fall back to weighted Rekordbox seed: `Rating ≥ 4` tracks contribute weight 1.0, MyTag-overlap tracks contribute 0.5, others 0. If still empty (no ratings, no MyTags) → defer to Teil-1 rule-based ranking entirely and emit "taste profile cold — using rules" hint. **GATE FOR `evaluated_`**: confirm seed weights.
6. **Negative signals** — **PARTIALLY RESOLVED**: threshold heuristic = skip within 15 s of start = strong (weight −1.0); skip 15-60 s = weak (weight −0.3); skip > 60 s = neutral (weight 0). Validate via 2-week tb logging spike post-Teil-1 `plays` shipping; revise thresholds if false-positives > 20%. **PARK** the per-track-context (mid-set vs. solo listen) detail to M3.
7. **SoundCloud candidate set** — **PARTIALLY RESOLVED**: M1 SC mode = `/tracks/{id}/related` only (single API call per recommendation, ~20 candidates back per SC docs). M2 adds `/stations/track:{id}` (50 candidates) when seed has weak `/related` results (< 10 returned). M3 considers stream feed + followed-user uploads (multi-call, batch only). **GATE FOR `evaluated_`**: confirm M1 = `/related` only.
8. **Privacy / collaborative filtering** — **RESOLVED** (deferred): no collaborative filtering. App stays single-user. Documented as explicit non-goal above. Re-opens only if user signals interest in opt-in cloud sync — separate doc topic.
9. **NEW: Embedding extraction blocker** — **PARTIALLY RESOLVED**: Option-B benchmark deferred to M2 with concrete gate criteria (see Recommendation). M1 ships on Option A handcrafted, swap-in compatible.
10. **NEW: Taste-profile recompute cadence** — **PARTIALLY RESOLVED**: nightly batch + on-demand "refresh now" button. Incremental update on every play event = M3 (state-mgmt cost). **PARK** event-streaming approach.
11. **NEW: Per-feature weight tuning for the ranking score** — **PARK to M2**: default weights mirror sister doc (cosine 0.55, BPM 0.15, key 0.10, LUFS+spectral 0.10, MyTag 0.05, recency-bias 0.05). Re-tune from eval-set NDCG only after M1 ships.

## Options Considered

> Each option scored on five axes: **Impl cost** (S/M/L/XL), **Vector dim**, **Installer delta** (MB added vs. current `backend.spec` payload), **Per-track extraction latency** (CPU, no GPU assumed), **Query latency P95** (top-50 over 50k vectors), **Quality ceiling** (subjective).

### Option A — Handcrafted vector + cosine + recency-weighted user centroid [RECOMMENDED for M1]
- **Sketch**: Consume sister doc's `~46-dim` vector from `app_data/track_vectors.db` (no duplicate extraction code). User taste vector = time-decayed centroid of {liked, rated≥4, played-to-end}. Rank candidates by cosine to user vector; add per-feature bonuses (BPM Gaussian, Camelot distance, MyTag overlap). Re-compute taste vector nightly + on-demand.
- **Impl cost**: M | **Dim**: 46 (float32 = 184 B/track) | **Installer delta**: 0 MB (reuses sister) | **Extraction**: 0.3-0.5 s/track (sister-owned; runs once at analysis) | **Query P95**: ≤ 100 ms uncached | **Quality**: medium (MFCCs miss vocal/instrumental distinction)
- **Pros**: Zero new deps. Ships immediately after sister M1 lands. Explainable per-feature reasons. Backfill already addressed by sister.
- **Cons**: Quality ceiling capped at handcrafted-feature expressiveness; no semantic "deep dubby" vs "deep ambient" distinction unless MFCC happens to separate them.
- **Risk**: Low.

### Option B — Pre-trained learned audio embedding (CLAP / MERT / OpenL3) [M2 GATED ON BENCHMARK]
- **Sketch**: Run each track once through a pre-trained model, store embedding in same `track_vectors.db` schema (`vector_blob` just bigger; `fps_id` carries `embedding_kind`). User taste = same centroid approach but over the learned-embedding space. CLAP variant unlocks text queries.

Sub-variants (concrete `2026-05-15` package status, verified via pip):

| Model | Repo / pkg | Dim | Approx weights | CPU extract/track | GPU extract | torch req | Notes |
|---|---|---|---|---|---|---|---|
| **CLAP (LAION)** | `laion-clap` on PyPI | 512 | ~600 MB | 1-3 s | 0.1-0.3 s | yes | Text-query support. Audio + text dual encoder. Active maintenance through 2025. |
| **MERT-v1-95M** | `transformers` + HF model | 768/layer × 13 layers (use mean of last 4 ≈ 768) | ~380 MB | 2-4 s | 0.2-0.5 s | yes | Music-specific (95M params). Higher quality on genre tasks per [MARBLE benchmark](https://marble-bm.shef.ac.uk/). |
| **OpenL3** | `openl3` PyPI | 512 (music subset) | ~120 MB (env / music) | 1-2 s | 0.2-0.4 s | NO (TF/Keras) | Lighter installer, but pulls TensorFlow (different bundling headache). |
| **MusicNN** | `musicnn` PyPI | 200 (taggram) | ~30 MB | 0.5-1 s | n/a (TF1) | NO (TF1 legacy) | Smallest, but TF1-era — unmaintained since 2020. Skip unless brick-wall budget. |

- **Impl cost**: L | **Dim**: 200-768 (vector_blob 0.8-3 KB/track; 50k library = 40-150 MB) | **Installer delta**: +200-500 MB (torch wheel ~180 MB + model ~120-600 MB; `backend.spec:21` needs `torch` + model dir bundling — verified torch + transformers NOT in current `requirements.txt`) | **Extraction**: 1-4 s/track CPU = 14-55 h for 50k library cold scan, or 1.4-7 h on GPU | **Query P95**: ≤ 300 ms uncached (50k × 512-d brute cosine) | **Quality**: high (CLAP+text-query is a category-creating UX).
- **Pros**: Best similarity quality. CLAP text-query ("find tracks like 'late-night driving techno with strings'") is a flagship UX feature no competitor (Rekordbox/Serato/Engine) has.
- **Cons**: Installer ≥ 2× current size. PyInstaller `backend.spec` + Tauri sidecar bundling pain with torch — `collect_all('torch')` known to balloon, slow cold-start, and platform-specific wheel mismatches (Windows ARM, macOS Apple Silicon vs. x86_64). 50k library cold-scan = overnight job.
- **Risk**: Medium-High — installer-size acceptance, sidecar boot time, model licensing (LAION-CLAP CC0 OK; MERT Apache-2.0 OK; both fine commercially).

### Option C — LLM in ranking loop [REJECTED]
- **Sketch**: Build text profile per track + user; feed to LLM at every recommendation call.
- **Impl cost**: S | **Dim**: n/a | **Installer delta**: 0 (HTTP only) | **Extraction**: n/a | **Query P95**: 1500-3000 ms (LLM call) | **Quality**: medium (text-only; no audio signal)
- **Pros**: Free reasoning + explanations.
- **Cons**: **Violates local-first** (mandatory paid API call). Latency 10-30× the budget. Doesn't see audio. Per-recommendation cost: $0.002-$0.02 → unsustainable at "ranking sidebar updates on selection".
- **Decision**: Out as default path. Subsumed into Option D as opt-in explanation layer only.

### Option D — Hybrid: Option A (or B if benchmark passes) for ranking + LLM for explanation only [RECOMMENDED LONG-TERM]
- **Sketch**: Embedding-based ranking yields top-50 (Option A in M1, swap to Option B from M2 if benchmark passes). LLM consulted ONLY when user clicks "Why?" on a result — feeds ~5-10 features about seed + candidate + user-profile-summary, returns 1-paragraph explanation. Result cached on `(seed_id, candidate_id, taste_profile_hash)`.
- **Impl cost**: S over chosen A/B base | **Installer delta**: 0 above A/B | **Per-explanation latency**: 1-3 s (acceptable for opt-in UX) | **Cost per explanation**: ~$0.001 (small payload, single Claude/GPT call) | **Quality**: best practical UX
- **Pros**: Best of all worlds. Local-first preserved for the hot ranking path. LLM enrichment opt-in + cached.
- **Cons**: API-key UX (where does user enter it?). Cache invalidation on taste-profile changes (handled by hash in cache key).
- **Risk**: Low — explanation layer is additive; can ship A first, add LLM layer in M2 without touching ranking.

## Recommendation

**Commit to Option D phased over three milestones** with Option A as M1 base and Option B as M2 conditional swap-in. Storage schema inherited from sister doc (no duplicate `track_vectors.db` work).

### M1 — Option A taste-aware ranking (ships after sister M1 + Teil-1 `plays` lands)

**Deliverables:**
- `app/recommender_taste.py` — `find_taste_ranked(seed_or_context, source, *, limit, filters, weights) -> list[Result]`. Two candidate generators: `_local_candidates()` reads from `track_vectors.db`, `_soundcloud_candidates()` calls `/tracks/{id}/related` (single API call).
- `app/taste_profile.py` — `build_taste_vector(user_id, *, kind="centroid")` reads `plays` table + Rekordbox `Rating`/MyTag; writes to `user_taste_vectors` table (sibling of `track_vectors` in same SQLite file).
- Nightly batch + `POST /api/taste/refresh` (X-Session-Token gated).
- Frontend "play next" / "build a set" entry points; reasons chips.
- Eval harness `eval/taste_recommender_2026-05.jsonl` (30 seeds × top-10, manually scored 0/1/2).

**Gates to enter M1 (`evaluated_` → `accepted_`):**
- Sister doc `recommender-similar-tracks` has shipped Option A vector to `track_vectors.db` (M1 of sister) — **HARD DEPENDENCY**.
- Teil-1 has shipped `plays` table — **HARD DEPENDENCY** for non-cold-start path.
- User confirms OQ2 default (centroid only in M1, mood-cluster toggle M2).
- User confirms OQ5 cold-start seed weights (`Rating≥4` weight 1.0, MyTag-overlap 0.5).
- User confirms OQ7 (M1 SC = `/related` only).

**Exit criteria (`inprogress_` → `implemented_`):**
- NDCG@10 vs. Teil-1 baseline: ≥ 0.15 absolute improvement on eval set.
- ≥ 4/10 audio-judged-similar in top-10 for 10 mismatch-genre seeds.
- P95 ranking latency ≤ 200 ms (local), ≤ 800 ms (SC, dominated by one `/related` call).
- Zero new heavy deps.

### M2 — Option B benchmark + conditional swap

**Concrete benchmark plan** (run on dev laptop i7-12700H, 32 GB, no discrete GPU; report on identical machine + a low-end reference: 4-core / 16 GB):

1. **Extraction-time spike** — script `scripts/benchmark_embeddings.py`:
   - Pick 100 tracks from real library spanning 2-10 min durations.
   - For each of `{CLAP-LAION, MERT-v1-95M, OpenL3-music}`: install in isolated venv, warm-cache decoded `y`, measure per-track wall-clock for embedding-only (no decode).
   - Report p50, p95, p99. Estimate 50k library cold-scan time.
2. **Installer-impact spike** — build `backend.spec` with `torch` + chosen model bundled (`collect_all('torch')` + datas for HF cache); record `dist/RB_Backend.exe` size delta vs. current build. Note startup cold-time delta (sidecar boot).
3. **Quality spike** — re-score eval set with each Option-B variant; compute NDCG@10 vs. Option-A baseline.

**Gate conditions for Option-B path adoption (path-A→path-B swap):**

| Criterion | Threshold | Source |
|---|---|---|
| Per-track CPU extract time (p95) | ≤ 3.0 s | Spike 1 |
| 50k-library cold-scan time | ≤ 30 h (i.e. overnight + day, batchable) | Derived |
| Installer delta vs. current | ≤ +400 MB | Spike 2 |
| Sidecar cold-boot delta | ≤ +5 s | Spike 2 |
| NDCG@10 improvement over Option A | ≥ +0.10 absolute | Spike 3 |
| PyInstaller bundling success (Win + macOS x86_64 + macOS ARM) | all green | Spike 2 |

**All-of-above pass → swap in M2.5.** **Any-of-above fail → stay on Option A indefinitely, revisit only if user requests text-query feature explicitly.**

Path-B preference order when gate passes: CLAP (text-query bonus) → MERT (music-quality bonus, no text) → OpenL3 (lighter, but TF dependency replaces torch headache with TF headache; only attractive if `Spike 2` shows torch fails). MusicNN deprecated — skip.

### M3 — LLM explanation layer (Option D enrichment)

**Triggers:**
- M1 lands and user reports "I want to know why a track was suggested" qualitatively.
- API-key UX surface lands (separate doc — not in this scope).

**Deliverables:** `POST /api/taste/explain` (opt-in), result cache on `(seed_id, candidate_id, taste_profile_hash)`, frontend "Why?" button on result rows.

### M3+ — parked

- Mood-cluster toggle (OQ2 second-pass)
- Stream feed + followed-user upload SC candidates (OQ7 extension)
- Per-track-context skip detection (OQ6 detail)
- Event-driven taste-vector update (OQ10 incremental path)

### Cross-coordination with sister doc

- **Storage shape**: this doc commits to consuming the sister's `track_vectors.db` schema unmodified. Adds only `user_taste_vectors` table in same file. Sister owns vector extraction; this doc owns taste-vector building + ranking.
- **Vector swap**: if sister later adopts Option B from this doc's benchmark, this doc's `find_taste_ranked()` ranking code is unchanged (cosine works on any dim); only `vector_blob` width changes.
- **No coordinated re-deploy required.**

### Open Question status summary (for `exploring_` → `evaluated_` gate)

- **Resolved**: OQ3, OQ4, OQ8.
- **Partially resolved (defaults proposed, user-sign-off needed)**: OQ1, OQ2, OQ5, OQ6, OQ7, OQ9.
- **Gates before `evaluated_`** (need user sign-off): OQ2 (mood-cluster timing), OQ5 (cold-start weights), OQ7 (M1 = `/related` only).
- **Parked to M2**: OQ1 second-pass (Option B benchmark), OQ11 (weight tuning from real eval data).
- **Parked to M3**: OQ6 (per-context skip detail), OQ10 (incremental taste update).

## Decision

_Not yet decided. Status: `exploring`._

## Log

### 2026-05-15 — deeper exploration pass (toward `evaluated_` readiness)

**Reverified `app/analysis_engine.py`** post-hotfixes: file length 2239 LOC. Return dict at lines 2152-2201, fallback at 2219-2240. Earlier line-cites (114-118, 71) in this doc and the 2026-05-11 entry overstated which features are persisted — corrected via sister doc's Finding #3 + new Constraints section (~12-15 useful scalars actually persisted today, not the 26+ MFCC + 12 chroma claimed). MFCC at `analysis_engine.py:1132` is per-phrase only; chroma at lines 357-373 internal to `_detect_key`. `spectral_bandwidth`, `spectral_flatness`, `tempo_variability` not called anywhere (verified `Grep`). The 46-dim Option-A vector REQUIRES new extraction — sister doc M1 owns it.

**Sister doc carve-out absorbed**: [exploring_recommender-similar-tracks](exploring_recommender-similar-tracks.md) promoted to `exploring_` 2026-05-15, recommended Option A handcrafted ~46-dim → `app_data/track_vectors.db` schema `(track_id PK, vector_blob, fps_id, computed_at)`, swap-in compatible with Option B. This doc inherits the schema unmodified and adds a sibling `user_taste_vectors` table. No duplicate extractor.

**Pip + bundling verified**:
- Current `requirements.txt`: `librosa==0.10.1`, `madmom==0.16.1`, `essentia==2.1b6.dev1110`. **NO torch, NO tensorflow, NO transformers** — Option B = greenfield install.
- `backend.spec:21` `collect_all` set: `librosa, numba, scipy, sklearn, soundfile, audioread, lazy_loader`. Option B adds `torch` (~180 MB wheel) + HF cache datas — `collect_all('torch')` known to balloon installer; gate criterion added.
- Embedding-pkg PyPI status (2026-05-15): `laion-clap` active maintenance through 2025; `openl3` published 0.5.0 in 2025 (still TensorFlow-based, dropped TF1); `musicnn` last release 2020 — TF1-era, **skip** for any new work; MERT via `transformers` from `m-a-p/MERT-v1-95M` HF repo, Apache-2.0 license.

**Rewritten sections**: Goals (added metrics), Constraints (verified line-cites + sister inheritance), Open Questions (numbered status + gates + 3 new OQs), Options (added comparison table + concrete sub-variants), Recommendation (M1/M2/M3 phasing + 6-criterion benchmark gate table + sister coordination).

### 2026-05-15 — scope clarification + sibling doc landed

A new sibling doc — [idea_recommender-similar-tracks.md](idea_recommender-similar-tracks.md) — was created as the **local-only** seed-driven similar-tracks counterpart. This Teil 2 doc remains the broader taste-aware / embedding-based recommender covering **both local and SoundCloud modes**, with personalisation from play history. The local-only "find similar in my library" UX surface now lives in the sibling doc; the embedding extraction pipeline (Option A handcrafted, Option B CLAP/MERT) is the shared primitive both docs can consume.

**Open Question re-check:**
1. Embedding source — unresolved; sibling doc can ship on Option A independently.
2. Taste representation — unresolved; not affected by sibling.
3. LLM in loop — unresolved.
4. Storage — unresolved; sibling doc raises same question (its OQ-10), favours shared store.
5. Cold-start — unresolved; sibling sidesteps (seed-driven, not user-driven).
6. Negative signals — unresolved; still blocked on `plays` table.
7. SC candidate set — unresolved; sibling explicitly excludes SC.
8. Privacy — unresolved.

**Recent commits since 2026-05-11** touching `app/live_database.py`: `bd8c0f7` typed `restore_backup` return + structured logging, `cc171ee` dropped legacy session backups + `BACKUP_DIR`, `13b2197` type-hinted `LiveRekordboxDB` public API, `fbb4aad` typed bare excepts. No changes to `analysis_engine.py` or `audio_analyzer.py`. None alter signal sources for this doc.

### 2026-05-11 — initial drafting
- Created during the recommender-split discussion. Teil 1 (dumb, rules-based) is being implemented now.
- Captured what we know about the existing audio analysis pipeline from the codebase audit:
  - `app/analysis_engine.py` (~2200 LOC) already produces BPM, key, LUFS, spectral features, MFCCs, chroma, MFCC mean/std — enough for Option A out of the box.
  - `app/audio_analyzer.py` is the async wrapper running in `ProcessPoolExecutor`.
  - Rekordbox `master.db` is read-only with respect to schema additions — any new per-track data (embedding, taste vector) needs a sidecar store, not a Rekordbox column.
- No user-play history table exists yet. Rekordbox's `PlayCount` is static and import-time only. Need Teil 1 to introduce a local `plays` table before Teil 2 has signal to work with.
- SoundCloud `/tracks/{id}/related` and `/stations/track:{id}` are mentioned but not currently called by `app/soundcloud_api.py` — they would be the entry point for SC-mode candidates.
- Open question 4 (storage) is the most architecturally consequential — picking sqlite-vss vs. FAISS vs. flat .npy locks in update / portability characteristics. Worth a small spike before committing.

## Links

- Code (existing analysis pipeline):
  - [app/analysis_engine.py](../../app/analysis_engine.py)
  - [app/audio_analyzer.py](../../app/audio_analyzer.py)
  - [app/soundcloud_api.py](../../app/soundcloud_api.py)
- Audio embedding candidates (external):
  - CLAP — https://github.com/LAION-AI/CLAP
  - MERT — https://huggingface.co/m-a-p/MERT-v1-95M
  - OpenL3 — https://github.com/marl/openl3
  - MusicNN — https://github.com/jordipons/musicnn
- Vector store candidates:
  - FAISS — https://github.com/facebookresearch/faiss
  - sqlite-vss — https://github.com/asg017/sqlite-vss
  - chromadb — https://www.trychroma.com/
- Related research: [recommender-rules-baseline.md](exploring_recommender-rules-baseline.md) (Teil 1 — the deterministic baseline)
