---
slug: analysis-underground-mainstream-classifier
title: Underground vs Mainstream classifier / certifier for tracks
owner: tb
created: 2026-05-15
last_updated: 2026-05-15
tags: []
related: []
---

# Underground vs Mainstream classifier / certifier for tracks

> **State**: derived from filename + folder. Do not store state in frontmatter.
> Start the file as `docs/research/research/idea_<slug>.md`. Rename + move on each transition (see `../README.md`).

## Lifecycle

> Append-only audit trail. One line per `git mv`. Newest at the bottom.

- 2026-05-15 — `research/idea_` — created from template
- 2026-05-15 — research/idea_ — section fill (research dive)
- 2026-05-15 — research/idea_ — concrete API economics + match-key precision research

---

## Problem

> Required from `idea_` onward. Keep under 100 words. What are we solving? Why does it matter? What happens if we don't?

Classify each track as **Underground vs Mainstream** by estimating cross-platform popularity. Signal source: aggregated **play counts across all available platforms** (Spotify, SoundCloud, YouTube, Apple Music, Beatport, Tidal, Deezer, etc.) normalised into a single 0–1 mainstream score (or a banded label: `underground` / `niche` / `rising` / `mainstream`). Useful as a curatorial signal (filter, group, badge), for set-planning ("warm-up only underground"), and as a discoverability tag.

## Goals / Non-goals

**Goals**
- Assign every track in the local collection a mainstream/underground signal usable for filtering, grouping and badging in the UI.
- Aggregate plays/popularity from multiple public sources rather than trusting any single platform.
- Be robust to missing data — most tracks will only be findable on 1–2 platforms.
- Make the score genre-aware (underground-in-techno ≠ underground-in-pop).
- Stay local-first: no per-user cloud calls beyond the platform APIs themselves, no telemetry.
- Keep the score recomputable / replaceable — providers and weighting will change.

**Non-goals** (deliberately out of scope)
- Editorial taste judgements ("good" vs "bad", "DJ-worthy") — pure popularity signal only.
- Real-time / per-play tracking — daily-or-slower refresh cadence is fine.
- Writing the score into Rekordbox `master.db` user-facing columns (read-only / sidecar-only — see Constraints).
- Predicting future popularity ("rising" detection beyond a simple delta is a follow-up topic).
- Scraping platforms that explicitly forbid it in ToS (Apple Music public web, Tidal, Bandcamp playcounts).

## Constraints

> External facts that bound the solution space — API rate limits, existing data shape, performance budgets, legal/licensing, team capacity. Cite source where possible.

- SoundCloud V2 API access already in place via `app/soundcloud_api.py:36` (`get_sc_client_id`) — playback counts are part of the public track payload but the file currently does not read them (grep for `playback_count` returns no hits). New code would consume an existing field, not a new auth path.
- Cross-platform matching can reuse the SequenceMatcher-based fuzzy matcher at `app/soundcloud_api.py:566` (`_fuzzy_match_with_score`, threshold `0.65` at line 583). ISRC is already stored when present — written into `master.db` via `app/services.py:1111`, exported through `app/usb_pdb.py:497`, and parsed from tags at `app/audio_tags.py:319`. Real ISRC coverage in the wild is partial (SoundCloud uploads rarely have one — see `app/soundcloud_downloader.py:723-727` which mentions ISRC plumbing is incomplete).
- `master.db` is Rekordbox-controlled. All writes must serialise through `app/main.py:_db_write_lock` and not add custom columns the Pioneer hardware doesn't expect — popularity scores must live in a sidecar store (separate SQLite next to other LMS state), not as new `master.db` columns.
- Spotify Web API requires app credentials (client-credentials flow is enough — no user OAuth needed for `popularity`). New env vars would join `SOUNDCLOUD_CLIENT_ID/SECRET` (see `.env.example`).
- YouTube Data API v3 quota is 10 000 units/day per project; a `videos.list` is 1 unit and a `search.list` is 100 — search dominates cost when no direct ID is known.
- Last.fm API needs only an API key (no OAuth) and exposes `track.getInfo` with playcount/listeners — generous limits, but counts are scrobble-skewed (Last.fm demographics).
- MusicBrainz/Discogs expose no play counts but excellent canonical IDs / ISRC linkage — useful as a matching layer, not a signal source.
- Beatport has no public popularity endpoint; chart-position scraping is fragile and ToS-grey.
- Analysis pipeline (`app/analysis_engine.py:1`) is offline / batch-oriented and unrelated to network calls — popularity enrichment is a separate phase, not part of DSP.

## Open Questions

> Numbered. Each one should be resolvable (yes/no, or "X vs Y"), not open-ended philosophy.

1. Score as continuous 0–1 OR discrete bands (`underground` / `niche` / `rising` / `mainstream`) — or expose both (continuous stored, banded derived)?
2. Genre-relative normalisation OR global normalisation across the whole library? (Genre-relative needs reliable genre tags — how many tracks lack one?)
3. Which platforms are MVP — Spotify + SoundCloud + YouTube only, or include Last.fm at v1?
4. Trust each platform equally (mean of normalised counts) OR weight by genre relevance (e.g. SoundCloud counts more for techno, Spotify more for pop)?
5. Refresh cadence: per-import (one-shot at track add) vs scheduled (weekly background) vs lazy on-demand (when user opens detail panel)?
6. How do we handle tracks present on 0 platforms after matching — `unknown` band, or pessimistically `underground`?
7. Match-key priority: ISRC → MusicBrainz MBID → fuzzy(title+artist) — is fuzzy threshold `0.65` (as in `_fuzzy_match_with_score`) appropriate for cross-platform, or should it be tightened (e.g. `0.80`) to avoid false positives between similarly-titled tracks?
8. Display in UI as a numeric badge, a color band, both, or as a sortable column only?
9. Surface to user the per-platform raw counts (transparency) or only the aggregated score (simplicity)?
10. Do we cache responses across sessions (sidecar DB rows with `fetched_at`) and re-use until stale, or fetch fresh every refresh cycle?

## Findings / Investigation

> Required from `exploring_` onward. Append dated subsections as you learn. Never edit past entries — supersede with a new one.

### 2026-05-15 — initial scope audit

Codebase already has partial scaffolding for the matching half of the problem. `app/soundcloud_api.py` holds an authenticated V2 client (`get_sc_client_id` at line 36, dynamic-scrape fallback at line 69+) plus a fuzzy track matcher (`SoundCloudSyncEngine._fuzzy_match_with_score` at line 566, SequenceMatcher, threshold `0.65`). The same payload that `sync_playlist` consumes carries `playback_count` natively in the SoundCloud V2 response but the file does not currently read it — adding popularity is a pure read, no new auth. ISRC is stored end-to-end (tags → DB → USB export: `app/audio_tags.py:319`, `app/services.py:1111`, `app/usb_pdb.py:497`) which makes it the strongest cross-platform match key when present, but SoundCloud-sourced tracks largely lack ISRC (`app/soundcloud_downloader.py:723-727` shows the plumbing is acknowledged-incomplete). `master.db` is Rekordbox-managed and write-serialised by `app/main.py:_db_write_lock`; popularity therefore wants a sidecar SQLite (precedent: `app/anlz_sidecar.py` for per-track artefacts; no per-library sidecar DB exists yet). Spotify `popularity` is 0–100 already-normalised, Last.fm exposes raw playcount+listeners, YouTube exposes raw view counts; magnitudes span 4–6 orders of magnitude, so log + percentile-within-genre is the realistic normalisation path. No existing research doc touches this topic (checked `docs/research/_INDEX.md` is the canonical index).

### 2026-05-15 — concrete API economics + match-key precision research

Per-provider cost, match precision, demographic bias. Q3/Q5/Q7/Q10 become directly answerable — see follow-ups inline.

**Spotify Web API — `popularity`.** `GET /v1/tracks/{id}` returns `popularity: 0–100` (already log-normalised, proprietary recency-weighted — a 2020 hit may score lower than a current sleeper). Batch `GET /v1/tracks?ids=...` accepts up to 50 IDs/call. Auth: Client Credentials (no user OAuth); env vars `SPOTIFY_CLIENT_ID` + `SPOTIFY_CLIENT_SECRET`; ~60min token refresh. Rate limit ~180 req/min, bursty + `Retry-After`. Match: `GET /v1/search?q=isrc:USAB12345678&type=track` is exact (near-complete ISRC coverage for commercial releases). Without ISRC: `q=artist:"X" track:"Y"` + fuzzy-rank.

**SoundCloud V2 — `playback_count`.** Already authenticated via `app/soundcloud_api.py:36`. Track JSON also carries `favoritings_count`, `comment_count`, `reposts_count`. No ISRC in SC search — fuzzy on title+artist via existing `_fuzzy_match_with_score`. SC catalogue is bedroom-producer-heavy: SC `playback_count` is THE key underground signal (where Spotify shows 5/100, SC may show 50k plays). V2 rate limit undocumented; observed-safe at 0.3s spacing (`app/soundcloud_api.py:169-234`).

**YouTube Data API v3 — `viewCount`.** `videos.list?part=statistics&id=...` costs 1 unit; `search.list?q=...` costs 100. Quota 10 000 units/day. Hard ceiling: 100 cold lookups/day (search) or 10 000 warm (videos.list with known IDs). Auth: API key. No ISRC. Search results polluted (covers, fan uploads, lyric videos); low confidence without uploader-vs-canonical-artist gate.

**Last.fm — `track.getInfo`.** Returns `playcount` (total scrobbles) + `listeners` (unique). Auth: API key only. Documented 5 req/sec — generous. MBID-based when available (highest precision; MB-fetched cheaply); else artist+title fuzzy. Demographic skew: older / Western / indie-heavy.

**MusicBrainz / Discogs.** No play counts but excellent canonical-ID / ISRC linkage. Use as match-key resolvers: library track → MBID → MB-linked services. MB 1 req/s; Discogs 60 req/min (auth).

**Normalisation math.** Counts span 4–6 orders of magnitude. (1) per-platform `log10(1 + count)`. (2) per-platform percentile-rank within library (SC=10k is low percentile in bedroom-techno collection, high in Top-40 — context matters). Aggregate weighting genre-aware: house/techno → SC > Beatport > Spotify > YouTube > Last.fm; pop → Spotify > YouTube > Last.fm > SC. Banding (0–1 composite): underground <0.25, niche 0.25–0.55, rising 0.55–0.75, mainstream >0.75. User-tunable.

**Caching + cadence.** Sidecar SQLite row per (track_id, platform) with raw_count, fetched_at, score. TTL: SC daily, Spotify/YouTube/Last.fm weekly. Cold scan of 30k library: Spotify ≈3h (30k/180/min), SC ≈2.5h (0.3s spacing), YT NOT FEASIBLE without ISRC (30k×100 units = 30 days of quota). Mitigation: YT-lookup only tracks where Spotify+SC+LastFM is inconclusive (rising band).

**Open Questions touched:** Q3 (MVP set) — Spotify+SC+Last.fm; YouTube fails economics. Q5 (cadence) — TTL sidecar refresh wins over per-import or full-rescan. Q7 (threshold) — ISRC > MBID > fuzzy@0.80 (tighten from 0.65; cross-platform false positives costlier than within-SC). Q10 (caching) — mandatory; cold rescan is hours-scale.

## Options Considered

> Required by `evaluated_`. For each viable approach: sketch (2-4 lines), pros, cons, effort (S/M/L/XL), risk.

### Option A — Single-source MVP (SoundCloud only)
- Sketch: Read `playback_count` from the SoundCloud V2 response already fetched by `soundcloud_api.py`, log-scale, percentile-rank within library, store in sidecar DB. No new providers.
- Pros: Zero new auth or env vars; reuses existing client + fuzzy matcher; ships fastest; validates UX and storage shape before scaling.
- Cons: Heavily biased toward SoundCloud demographics (electronic-leaning); silent on tracks not on SC; one platform = one outage = no score.
- Effort: S
- Risk: Low. Worst case = poor signal quality; easy to layer more providers later.

### Option B — Multi-source aggregate (Spotify + SoundCloud + YouTube + Last.fm)
- Sketch: Match each track against 3–4 platforms (ISRC → MBID → fuzzy). Normalise each platform's count via log + per-genre percentile. Aggregate by mean of available normalised values; emit continuous score + derived band.
- Pros: Robust to single-platform gaps; cross-validates; banding is meaningful across genres.
- Cons: Four new API integrations, four sets of rate limits + secrets; YouTube quota requires careful caching; matching quality dominates the signal — bad matches = bad scores.
- Effort: L
- Risk: Medium. Quota exhaustion and matching false-positives are the main failure modes; both mitigable with caching + tightened thresholds.

### Option C — MusicBrainz-anchored canonical aggregate
- Sketch: Resolve every track to a MusicBrainz Recording MBID first (via ISRC or fuzzy), then look up popularity from platforms keyed by MBID (Spotify, Last.fm, ListenBrainz). Anything unresolvable falls back to fuzzy-per-platform.
- Pros: Highest match quality; ListenBrainz gives open scrobble data with no quota; durable canonical IDs survive title edits.
- Cons: MusicBrainz coverage of underground electronic releases is patchy — the very tracks we want to classify as "underground" are the ones with no MBID; adds an extra resolution hop per track.
- Effort: L
- Risk: Medium-high. Coverage gap may invert the signal (most-underground = unscored).

### Option D — Banding-only heuristic (no continuous score)
- Sketch: Look up per platform; bucket directly into `underground` (<1k plays), `niche` (1k–50k), `rising` (50k–500k), `mainstream` (>500k) using fixed log thresholds per platform; take majority vote across available platforms.
- Pros: Simplest UX; no normalisation maths; resilient to missing genre tags.
- Cons: Thresholds are arbitrary and platform-specific; loses ordering within a band; harder to recombine when adding/removing platforms later.
- Effort: M
- Risk: Medium. Likely needs re-tuning per platform over time; banding feels "magic" to users.

## Recommendation

Start with **Option A** as the MVP (one-week effort, validates storage + UX), then expand to **Option B** once the sidecar-DB shape and UI affordances are settled. Defer Option C until ISRC/MBID coverage in the library is measured (open question 7 informs this). Option D's banding rules can be layered on top of either A or B's continuous score — they aren't mutually exclusive.

**Phasing (per 2026-05-15 Findings above):**
- **Phase 1:** Spotify + SoundCloud + Last.fm with ISRC-driven match (Spotify `q=isrc:`; Last.fm via MBID-from-ISRC), fuzzy@0.80 fallback. All three are cost-feasible for a 30k cold scan in hours, and cover bedroom-producer / Western-indie / commercial-pop axes.
- **Phase 2:** Beatport popularity-rank (opt-in, ToS-grey scrape) and MusicBrainz-relations to widen MBID coverage upstream of Last.fm.
- **Phase 3:** YouTube `videos.list` only on tracks still `rising` after Phases 1–2. Downgraded from MVP because `search.list` at 100 units/call makes cold ISRC-less scans infeasible (~30 days of quota for 30k tracks).

Gates that must be answered before promotion to `evaluated_`:
- Open questions 1, 3, 5, 7 (score shape, MVP platform set, refresh cadence, match-key priority) — Q3/Q5/Q7 partially answered in Findings.
- Concrete sidecar-DB location decision (alongside existing app data, distinct from `master.db`).
- Confirmation that Spotify client-credentials use is acceptable under their ToS for a desktop app distributed as a Tauri binary (commercial / non-commercial distinction).

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
