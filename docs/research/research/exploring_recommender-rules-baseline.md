---
slug: recommender-rules-baseline
title: Deterministic rules-based track recommender (Teil 1 — baseline / Mixxx-style "next track")
owner: unassigned
created: 2026-05-11
last_updated: 2026-05-11
tags: [recommender, soundcloud, mixing, harmonic, baseline]
related: [recommender-taste-llm-audio]
---

# Deterministic rules-based track recommender (Teil 1)

> **State**: derived from filename + folder. See `## Lifecycle` for transition history.

## Lifecycle

- 2026-05-11 — `research/idea_` — created as Teil 1 of recommender split
- 2026-05-11 — `research/exploring_` — codebase audit captured, options A-D documented, recommendation drafted

## Problem

Given one **seed track**, suggest a ranked list of **next tracks** the user might pick — either from the local Rekordbox library or from SoundCloud — using only data already known at zero cost: BPM, musical key, genre, energy, MyTag membership.

This is the dumb/predictable half of the recommender split. It is intentionally not personalised — it answers *"what mixes well with this?"*, not *"what does this user want next?"*. The personalised half is covered in [recommender-taste-llm-audio.md](exploring_recommender-taste-llm-audio.md).

The deterministic recommender also doubles as:

- A **harmonic-mixing assistant** for DJs (Camelot wheel compatibility is its core).
- The **baseline** that the future personalised recommender must beat in user testing.
- The **fallback** when taste-data is too thin (cold-start, brand new track, brand new user).

## Goals / Non-goals

**Goals**
- Two modes — `local` ranks tracks from the user's library; `soundcloud` ranks tracks from SoundCloud's related/station endpoints.
- Fully deterministic: same seed + same settings → same output. No ML, no randomness.
- Explainable: each suggested track ships with a `reasons` list (`"bpm ±2%"`, `"key compat 8A→9A"`, `"genre techno"`). Used both in the UI as chips, and as a debug aid.
- Fast: ≤ 100 ms for local mode over a 50k-track library on a developer laptop. SC mode is bound by API latency, not us.
- Settings are per-call (query params) at first; persistence is a later question.

**Non-goals**
- Beat-aligned auto-mixing (that's Auto-DJ, separate feature, separate scope).
- Learning from user behaviour — explicitly punted to Teil 2.
- Cross-library similarity (e.g. "find SC tracks that sound like my library cluster X") — also Teil 2.

## Constraints

- **Data available today** (see [docs/architecture.md](../architecture.md) + codebase audit): track-level BPM, Key, Genre, Energy (from `analysis_engine.py` outputs), MyTag membership (via `live_database.py:283-1130`), Rekordbox `Rating`/`Color`/`PlayCount` (static).
- **MyTag is flat** — no hierarchy/dimensions (see `live_database.py`). Bonus per overlapping tag is the only viable scoring there.
- **Key field** in the library is a free-text string written by Rekordbox/analysis — must be normalised to Camelot (`1A..12A / 1B..12B`) before compatibility checks. Existing analysis output uses Krumhansl-style notation (`Am`, `C#`, etc.); a key-to-Camelot map is needed.
- **SC-side endpoints**: `/tracks/{id}/related` and `/stations/track:{id}` are mentioned but **not currently called** by `app/soundcloud_api.py`. Both need to be added. Polite spacing (0.3 s) + existing backoff (`app/soundcloud_api.py:169-234`) applies.
- **Seed track may have no SoundCloud ID** — if the user seeds with a local-only track, we need fuzzy title/artist matching to find a corresponding SC track (logic exists in `SoundCloudSyncEngine`, threshold 0.65 — see codebase audit). Reuse it.
- **No new dependencies** — pure Python + existing stack. Anything heavier (FAISS, numpy embeddings) belongs in Teil 2.

## Open Questions

1. **Frontend scope in v1** — backend-only (testable via curl) vs. minimal UI (context-menu entry on track row + side panel with mode toggle + results list with reason chips)? UI is small but non-trivial — needs to match the existing table-driven aesthetic.
2. **Default weights** — is the `BPM 0.35 / Key 0.30 / Genre 0.15 / MyTag 0.10 / Energy 0.10` split right? Many DJs treat key as *more* important than BPM (one can pitch ±6 % but a clashing key is a clashing key). Should the default be `Key 0.35 / BPM 0.30 / ...`?
3. **BPM tolerance default** — ±3 % (Pioneer CDJ-3000 default pitch range for "auto") vs. ±6 % (typical performance pitch range) vs. ±10 % (digital DJ liberal). And: is the score a binary "inside/outside tolerance" or a continuous decay (e.g. Gaussian on distance)?
4. **Key compatibility model** — Camelot wheel only (same, +1, -1, relative major/minor) vs. extended Camelot (also +7 = perfect fifth = "energy boost mix") vs. user-defined whitelist of moves? Strict-mode toggle = only same key.
5. **Half/double-time matching** — some DJs treat 174 BPM dnb as compatible with 87 BPM half-time. Score these as adjacent? Risk: false positives if genre is unrelated.
6. **SoundCloud candidate sources** — `/tracks/{id}/related` (kuratierter Klotz, ~20 results) vs. `/stations/track:{id}` (endloser Feed) vs. union of both deduped vs. only one configurable? Effort is similar — decision is product-feel.
7. **Filtering already-in-library** — for SC mode, hide candidates that already exist locally (matched by title+artist fuzzy)? Probably yes, but how aggressively (≥ 0.85 fuzzy match)?
8. **Settings persistence** — query-params only for v1, or persist in `app/analysis_settings.py`-style JSON config? If we ever add a settings UI it'll need persistence.
9. **Result limit + pagination** — hard cap at top 50? Paginate? For local mode this is a sort over a small array; for SC it costs API calls.
10. **Recording the recommendation event** — should we log `{seed_id, mode, returned_ids, ts}` somewhere? It would be useful baseline data for the eventual Teil-2 evaluation ("did dumb suggest the same thing taste-recommender would?"). Small `recommendations.log.jsonl` could do.

## Options Considered

### Option A — Pure rule-based, no Camelot weighting curve (binary tolerance)
- **Sketch**: A candidate passes if `|bpm_seed - bpm_cand| / bpm_seed ≤ tol`, key is in the Camelot compat set, energy is within ±0.15 (if enabled). Score = sum of binary feature matches.
- **Pros**: Trivial to implement, very fast.
- **Cons**: Hard cutoffs mean track at ±6.01 % BPM never appears even if it's a 10/10 mix otherwise. UX feels brittle.
- **Effort**: S

### Option B — Continuous score with weighted feature distances (recommended)
- **Sketch**: Each feature contributes a score in [0, 1] based on how close it is to ideal. BPM uses a Gaussian centred on seed BPM (σ tied to tolerance). Key uses a Camelot-distance table (same = 1.0, +1/-1/rel = 0.7, +2/-2 = 0.3, else = 0). Genre = 1.0 / 0.0. MyTag = `overlap / max(seed_tags, cand_tags)`. Energy = `1 - |Δenergy|`. Weighted sum → final score in [0, 1].
- **Pros**: Smooth ranking. Easy to tune weights without changing structure. Reasons list is naturally derived.
- **Cons**: Slightly more code; needs the distance tables.
- **Effort**: M

### Option C — Multi-criteria sort instead of single score
- **Sketch**: Filter by hard constraints (BPM ± tol, key compat), then sort remaining by lexicographic key (genre match → MyTag overlap → energy distance).
- **Pros**: Deterministic, no weight-tuning hell.
- **Cons**: No graceful degradation — if no candidate matches the hard constraints, returns nothing. Hard for the user to relax constraints without re-running.
- **Effort**: S

### Option D — Graph-based: precompute compatibility graph offline
- **Sketch**: Build a track-to-track graph where edges = compatibility score; query = neighbour lookup.
- **Pros**: Fast queries on huge libraries; reusable for "build a 60-min set from seed".
- **Cons**: Premature for 50k tracks where Option B is already <100 ms. Maintenance cost on every library change. Park for later if scale becomes an issue.
- **Effort**: L

## Recommendation

**Option B (weighted continuous score)** for the ranker. Concrete shape:

**Backend** — new module `app/recommender.py`, new routes in `app/main.py`:

```
GET /api/recommend/local?track_id=X&limit=20[&bpm_tol=0.06&key_strict=false&energy_match=true&weights=...]
GET /api/recommend/soundcloud?track_id=X&limit=20[&source=related|station|both]
```

Returns:
```json
{
  "seed": { "id": "...", "title": "...", "artist": "...", "bpm": 122, "key": "8A" },
  "mode": "local",
  "results": [
    {
      "track_id": "...",
      "score": 0.87,
      "reasons": ["bpm ±1.6%", "key compat 8A→9A", "genre: techno", "tags: peak-time, dark"]
    },
    ...
  ]
}
```

**Default weights** — TBD on open question 2, but starting point:
`bpm: 0.35, key: 0.30, genre: 0.15, mytag: 0.10, energy: 0.10`.

**BPM scoring** — Gaussian, `score = exp(-((Δbpm / (tol * bpm_seed)) ** 2))`, clipped at tol×1.5 (anything beyond gets 0).

**Key scoring** — Camelot distance table:
| Δ            | Score |
|--------------|-------|
| same         | 1.00  |
| +1, -1, rel  | 0.70  |
| +2, -2       | 0.30  |
| else         | 0.00  |

Where "rel" = relative major/minor flip on the same number (e.g. `8A` ↔ `8B`).

**Reasons list** — derived from the per-feature scores that contributed ≥ 0.05 to the final. Format `"<feature>: <human-readable>"`.

**SC mode** — start with `/tracks/{id}/related` only (open question 6 stays open). Filter out locally-existing tracks via reuse of the `SoundCloudSyncEngine` fuzzy matcher.

**Frontend** — punt for now (status `exploring`), revisit when status moves to `proposed`. Backend + a couple of HTTP examples in this doc is enough to prove the rules work.

## Decision

_Not yet decided. Status: `exploring`._

Implementation gate: pin down open questions 2, 3, 4, 6 and confirm frontend scope (open question 1) before moving to `proposed`.

## Log

### 2026-05-11 — split-out from initial discussion
- Originally framed as "implement now" in the planning session, then re-scoped to "research first, like Teil 2" — both halves of the recommender split live here as research before code.
- Code audit findings reused from [recommender-taste-llm-audio.md](exploring_recommender-taste-llm-audio.md):
  - `analysis_engine.py` already produces BPM/Key/Genre/Energy/MyTag-compatible outputs.
  - `soundcloud_api.py` has OAuth + rate-limit handling, but does **not** call `/tracks/{id}/related` or `/stations/track:{id}` yet — both endpoints need to be added.
  - `SoundCloudSyncEngine` has a fuzzy title/artist matcher (threshold 0.65) — reusable to (a) resolve local seed → SC track and (b) filter SC candidates against existing library.
  - `live_database.py:283-1130` exposes MyTag CRUD — flat tags, multi-tag per track.
- Captured the four "stellschrauben" raised during initial design (frontend scope, default weights, BPM tolerance shape, key model) as open questions 1-4.
- Added open question 10 (logging recommendation events) — cheap to add up front, valuable when Teil 2 lands and needs comparison data.

## Links

- Code (existing, will be touched once implementation starts):
  - [app/analysis_engine.py](../../app/analysis_engine.py) — feature source
  - [app/live_database.py](../../app/live_database.py) — MyTag access (lines 283-1130)
  - [app/soundcloud_api.py](../../app/soundcloud_api.py) — needs `/related` + `/stations` endpoints added
  - [app/main.py](../../app/main.py) — new routes go here
- External references:
  - Camelot wheel — https://mixedinkey.com/camelot-wheel/
  - SoundCloud API related endpoint — https://developers.soundcloud.com/docs/api/reference#tracks-tracks-id-related
  - Pioneer CDJ-3000 pitch ranges — manufacturer manual, sections on Master Tempo / Pitch
- Related research: [recommender-taste-llm-audio.md](exploring_recommender-taste-llm-audio.md)
