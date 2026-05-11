---
slug: recommender-taste-llm-audio
title: Taste-aware audio recommender (Teil 2 of the recommender split)
owner: unassigned
created: 2026-05-11
last_updated: 2026-05-11
tags: [recommender, ml, audio-analysis, soundcloud, embeddings, llm]
related: [recommender-rules-baseline]
---

# Taste-aware audio recommender (Teil 2)

> **State**: derived from filename + folder. See `## Lifecycle` for transition history.

## Lifecycle

- 2026-05-11 — `research/idea_` — created as Teil 2 of recommender split (gated by Teil 1 landing first)
- 2026-05-11 — `research/exploring_` — options A-D outlined; pending audio-embedding benchmark and Teil 1 baseline

## Problem

The "Teil 1" recommender (see [recommender-rules-baseline.md](exploring_recommender-rules-baseline.md)) is a deterministic rule engine: given a seed track, return tracks whose **measurable features** (BPM, key, energy, genre tag, duration) are compatible. It works without any user history and answers the question *"what mixes well with this?"*.

It does **not** answer *"what does this user actually want next?"*. A taste-aware recommender needs to:

1. Build a representation of the user's preferences from observed behaviour (plays, skips, likes, tag patterns, dwell time, manual playlist groupings).
2. Compare candidate tracks to that representation using something richer than 5 hand-crafted features — ideally a learned audio embedding that captures timbre, production style, instrumentation, mood beyond what BPM/Key/Energy can express.
3. Combine 1 + 2 to rank candidates from the local library and/or SoundCloud.

This doc collects options and constraints so we can pick a direction later, possibly with a different model (Claude 5.x, GPT-5, local Llama, etc.) and re-evaluated audio embedding tools.

## Goals / Non-goals

**Goals**
- Personalised "play next" / "build a set" suggestions that improve over time as the user uses the app.
- Audio-level similarity that catches "this sounds like X" even when metadata is sparse or wrong.
- Work for both modes: rank local library tracks, **and** rank SoundCloud candidates (e.g. tracks returned by `/tracks/{id}/related` or a stream feed).
- Local-first: inference must run on the user's machine (this app has no shared cloud backend by design — see `README.md`).
- Explainable: the user should be able to see *why* a track was suggested (e.g. "matches your Friday-evening pattern: deep house, 122 BPM, B-minor cluster").

**Non-goals**
- Beating Spotify's recommender on cold-start. We have a single-user, library-bounded problem — different game.
- Real-time training. Periodic batch updates (nightly / on-demand) are fine.
- Generating audio. We rank existing tracks, we don't synthesise.
- Replacing Teil 1. The dumb recommender stays — it's the fallback when taste data is thin and is the right tool for harmonic-mixing answers.

## Constraints

- **Local-first**: cloud inference is out unless the user opts in per-call. Models must run on a typical DJ laptop (RAM ≤ 32 GB, GPU optional). Source: `README.md:5-10`.
- **Stack**: Python 3.10+ backend (FastAPI), Rust audio engine (CPAL/Symphonia). Adding heavy ML deps (PyTorch, TF) inflates the installer significantly — needs explicit cost/benefit.
- **Audio access**: tracks already decode-able via `app/audio_analyzer.py` (librosa) and Rust `audio/engine.rs` (Symphonia). Embedding extraction can piggyback on the existing analysis pipeline (`audio_analyzer.py:analyze_async`) rather than re-decoding.
- **No play history exists yet** — Teil 1 must land first (it introduces the `plays` table that feeds this). Without that table, taste signal is limited to: file mtime, Rekordbox `PlayCount` (static), Rekordbox `Rating`, MyTag membership, playlist co-occurrence.
- **SoundCloud API rate limits**: see `app/soundcloud_api.py:169-234` (exponential backoff, 0.3s polite spacing). Any approach that needs to fetch metadata for hundreds of candidate SC tracks per recommendation is a non-starter.
- **Library scale**: target ~1k–50k local tracks. FAISS / sklearn `NearestNeighbors` handle this trivially; bigger ML infra is overkill.

## Open Questions

1. **Audio embedding source** — pre-trained model (CLAP / MusicNN / OpenL3 / MERT) vs. handcrafted feature vector from existing `analysis_engine.py` outputs? Trade-off: model quality vs. installer size and inference cost.
2. **Taste representation** — single user-embedding vector (centroid of liked tracks, weighted by recency / engagement) vs. multiple "mood clusters" (Friday-night vs. Sunday-brunch personas) vs. an LLM-readable text profile ("user likes deep, dubby techno around 122 BPM with vocal samples")?
3. **Role of LLM** — is the LLM in the recommendation loop (ranking / reasoning), or only at the explanation layer ("here's why")? Putting the LLM in the loop makes every recommendation an API call, which conflicts with local-first.
4. **Storage** — embeddings as a column in the existing `tracks` table (Rekordbox-incompatible — would need a sidecar SQLite), as flat `.npy` files keyed by track ID, or in a vector store (FAISS, chroma, sqlite-vss)?
5. **Cold-start** — when the user has 0 plays, what does the taste vector look like? Fallback to Teil 1? Use Rekordbox `Rating` + MyTag as a seed?
6. **Negative signals** — skips: hard signal (skip within 10s = strong dislike) or noisy (could be an accidental click)? Need a threshold heuristic.
7. **SoundCloud candidate set** — for ranking SC tracks, where do candidates come from? `/tracks/{id}/related`, `/stations/track:{id}`, user's stream feed, followed-user uploads? Each is a different query budget.
8. **Privacy** — if we ever want to do collaborative filtering (compare to anonymised other users), how? The app has no shared backend by design — would require an opt-in cloud component, which is a separate decision.

## Options Considered

### Option A — Handcrafted features + cosine similarity + weighted user centroid
- **Sketch**: Extract a ~40-dim vector per track from existing `analysis_engine.py` outputs (BPM, key, LUFS, spectral centroid/rolloff/flatness/bandwidth, MFCC mean+std for 13 coefficients, chroma mean for 12 pitch classes, tempo variability). Build user vector as time-decayed centroid of liked / played-to-end tracks. Rank candidates by cosine similarity. Store vectors in a sidecar SQLite.
- **Pros**: Zero new ML deps, all primitives already exist in the codebase. Trains instantly. Easy to explain ("you favour high spectral centroid, low LUFS, 120-125 BPM"). Fits the "Python-only, offline" constraint cleanly.
- **Cons**: MFCCs are crude vs. modern learned embeddings; will miss subtler "this sounds like that" similarity. No semantic understanding ("vocal house" vs. "instrumental house" only separable if MFCC patterns differ — not guaranteed).
- **Effort**: M
- **Risk**: Low — worst case the suggestions feel "close in feature space but emotionally wrong". Still likely better than rule-based for personalisation.

### Option B — Pre-trained audio embedding (CLAP / OpenL3 / MERT) + FAISS
- **Sketch**: Run each track through a pre-trained model once during initial analysis; store the resulting embedding (CLAP: 512-d, OpenL3: 512-d, MERT: 768-d per layer). Use FAISS for nearest-neighbour. User taste = recency-weighted centroid of liked-track embeddings, or per-cluster centroids via k-means.
- **Pros**: Much richer similarity. CLAP also enables **text queries** ("find tracks like 'late-night driving techno with strings'"), which would be a killer UX feature. MERT is trained specifically on music.
- **Cons**: ~200-500 MB extra in the installer (torch + model weights). Inference is slow on CPU (~1-2s per track for embedding extraction → fine for batch analysis, painful for live add). Needs PyTorch as a Python dep — significant.
- **Effort**: L
- **Risk**: Medium — depends on whether torch as a dep is acceptable. PyInstaller / Tauri sidecar bundling with torch has known weight/startup issues; needs validation.

### Option C — LLM in the loop (text-only, no audio embedding)
- **Sketch**: Build a text profile per track from metadata + analysis outputs ("Title X, Artist Y, 122 BPM, A-minor, deep house tag, energy 0.6, dark mood"). Build a text profile of the user from their listening history. Each recommendation call: feed candidate list + user profile to an LLM, ask for ranked suggestions with reasons.
- **Pros**: Zero ML infra to maintain locally. Reasoning + explanations come free. LLM can incorporate fuzzy preferences ("user likes vocals but not female vocals — except on Sundays") that no embedding captures.
- **Cons**: Every recommendation is a paid API call. Breaks local-first guarantee. Latency (~1-3s per ranking). Doesn't actually look at the audio — only what we tell it about the audio. Same false-positive ceiling as metadata-based recommenders.
- **Effort**: S (if we ignore building the profile-extraction pipeline well)
- **Risk**: High — operational cost + privacy + dependency on a third party.

### Option D — Hybrid: Option A or B for candidate generation, LLM for explanation
- **Sketch**: Embedding-based recall ("here are the 50 most similar tracks"), then optionally pass to LLM for re-rank with reasons. LLM only sees ~50 candidates per call, keeping costs low. Explanation is opt-in and cached.
- **Pros**: Best of both worlds. Local-first by default, LLM as an enrichment layer the user can toggle.
- **Cons**: More moving parts. Two systems to maintain.
- **Effort**: L (A) / XL (B)
- **Risk**: Medium.

## Recommendation

Don't decide yet. Concrete next steps that don't commit to a path:

1. **Land Teil 1 first** — without the `plays` table and Teil-1 baseline numbers, there's no way to measure whether Teil 2 actually helps. Teil 1 is also the natural place to plumb the `plays` recording.
2. **Prototype Option A** (handcrafted features + cosine) on a developer machine with 1-2k tracks. Measure: do the top-10 suggestions feel meaningfully better than Teil 1 for a small set of seed tracks? If yes, that's the floor — proceed.
3. **Benchmark CLAP / MERT embedding extraction time** on a typical track. If it's <5s per track and the installer cost is acceptable, Option B / D becomes viable. If it's >10s or the installer doubles, Option A is the answer.
4. **Defer LLM-in-the-loop** (Option C / D-with-LLM) until a stable embedding-based baseline exists. The LLM is a UX feature on top, not a foundation.

## Decision

_Not yet decided. Status: `exploring`._

## Log

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
