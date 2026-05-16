---
slug: analysis-underground-mainstream-classifier
title: Underground vs Mainstream classifier / certifier for tracks
owner: tb
created: 2026-05-15
last_updated: 2026-05-15
tags: [analysis, popularity, sidecar-db, multi-source, fuzzy-match]
related: [external-track-match-unified-module]
---

# Underground vs Mainstream classifier / certifier for tracks

> **State**: derived from filename + folder. Do not store state in frontmatter.
> Start the file as `docs/research/research/idea_<slug>.md`. Rename + move on each transition (see `../README.md`).

## Lifecycle

> Append-only audit trail. One line per `git mv`. Newest at the bottom.

- 2026-05-15 — `research/idea_` — created from template
- 2026-05-15 — research/idea_ — section fill (research dive)
- 2026-05-15 — research/idea_ — concrete API economics + match-key precision research
- 2026-05-15 — research/idea_ — exploring_-ready rework loop (deep self-review pass)

---

## Problem

> Required from `idea_` onward. Keep under 100 words. What are we solving? Why does it matter? What happens if we don't?

Classify each track as **Underground vs Mainstream** by estimating cross-platform popularity. Signal source: aggregated **play counts across all available platforms** (Spotify, SoundCloud, YouTube, Apple Music, Beatport, Tidal, Deezer, etc.) normalised into a single 0–1 mainstream score (or a banded label: `underground` / `niche` / `rising` / `mainstream`). Useful as a curatorial signal (filter, group, badge), for set-planning ("warm-up only underground"), and as a discoverability tag.

## Goals / Non-goals

**Goals** (each testable — success metric in `[]`)
- Assign mainstream/underground signal to every local track usable for filter/group/badge UI. `[≥ 80% of library has non-null score after first full scan, given any track is on ≥ 1 of MVP-set platforms]`.
- Aggregate across platforms — no single-source dependency. `[score uses ≥ 2 platforms for ≥ 50% of tracks where Spotify+SC+LastFM coverage overlaps]`.
- Robust to missing data — most tracks only on 1–2 platforms. `[1-of-3 platform availability returns valid score, not null; flagged `low_confidence`]`.
- Genre-aware normalisation — underground-in-techno ≠ underground-in-pop. `[percentile rank computed within genre cluster when ≥ 100 tracks share genre; else falls back to library-wide]`.
- Local-first — no per-user cloud, no telemetry. `[zero outbound to non-platform hosts; verify in M1 via grep of `app/popularity_engine.py` for hostname allowlist + manual `mitmproxy` audit]`.
- Recomputable / providers swappable. `[deleting sidecar DB row + re-running re-fetches; weighting in config file, not code]`.
- Performance — full cold scan of 30k-track library completes in ≤ 6h on residential broadband. `[Spotify-batch 50/call + SC 0.3s spacing + LastFM 5 req/s = ~3h with overlap; budget 2× for retries]`.

**Non-goals** (deliberately out of scope)
- Editorial taste — pure popularity signal only.
- Real-time / per-play tracking — daily-or-slower refresh suffices.
- `master.db` user-facing column write — sidecar SQLite only (see Constraints).
- Predict future popularity ("rising" beyond simple delta = follow-up topic).
- ToS-forbidden scraping (Apple Music web, Tidal, Bandcamp playcounts).
- Local-DSP popularity proxy (no audio-feature → popularity model — separate research domain).

## Constraints

> External facts that bound the solution space — API rate limits, existing data shape, performance budgets, legal/licensing, team capacity. Cite source where possible.

- **SoundCloud V2 API in place** — `app/soundcloud_api.py:36` (`get_sc_client_id`). `Grep playback_count` in `app/` returns 0 hits — field arrives in payload but `_normalize_track` (line 297-330) drops it. Adding popularity = pure read + 1 dict-key in normalizer, no new auth path.
- **Fuzzy matcher exists** — `app/soundcloud_api.py:566` (`SoundCloudSyncEngine._fuzzy_match_with_score`), threshold `0.65` hardcoded at line 583. Cross-doc note: shared with `external_track_match_unified_module` (Option C/M1) — coordinate to import from `app/external_track_match.py` once that module lands, don't re-instantiate fuzzy logic here.
- **ISRC end-to-end verified** — parsed `app/audio_tags.py:319` (TSRC frame ID3 alias), stored `app/services.py:1111` (track_data ISRC field), exported `app/usb_pdb.py:497` (devicesql string slot 0). SoundCloud-sourced downloads rarely carry ISRC: `app/soundcloud_downloader.py:723-727` acknowledges "audio_tags.write_tags doesn't have an ISRC alias — skip silently". Library ISRC coverage thus skewed toward commercial purchases / Bandcamp / Beatport rips.
- **`master.db` lock lives at `app/database.py:22`** (NOT `app/main.py` — corrected vs prior idea_ draft). `RLock` + `db_lock()` context-manager + `_serialised` decorator (lines 25-53). All Rekordbox writes serialise through it; popularity data MUST stay in sidecar, not as new `master.db` columns (Pioneer hardware rejects unknown columns silently).
- **Sidecar precedent already in repo** (corrects prior "no per-library sidecar DB exists" claim):
  - `app/sidecar.py` — JSON sidecar `app_data.json` (artist→soundcloud_link map). Tiny scale only.
  - `app/analysis_cache.py` — per-file gzipped JSON + `index.json` (DSP results cache, lines 11-30).
  - `app/anlz_sidecar.py` — per-track ANLZ files in `.lms_anlz/<sha>/` next to audio.
  Popularity scale (30k rows × ~6 fields) → new SQLite sidecar (precedent shape: `app/analysis_cache.py` index, but SQL not JSON for query/sort).
- **Spotify Web API** — Client Credentials flow (no user OAuth) suffices for `popularity` field. New env: `SPOTIFY_CLIENT_ID` + `SPOTIFY_CLIENT_SECRET` joining existing `SOUNDCLOUD_CLIENT_ID/SECRET` in `.env.example`. Token TTL 3600s, refresh cheap.
- **YouTube Data API v3 quota** — 10 000 units/day/project. `videos.list?part=statistics` = 1 unit; `search.list?q=...` = 100 units. 30k tracks cold via search = 30 days of quota → infeasible without ISRC pre-resolution.
- **Last.fm API** — API key only (no OAuth). `track.getInfo` returns `playcount` (total scrobbles) + `listeners` (unique). Documented limit 5 req/s. Counts demographically skewed to Western indie / classic rock / early-2010s Pitchcore.
- **MusicBrainz / Discogs** — no playcounts but canonical ID / ISRC linkage. MB rate limit 1 req/s; Discogs 60 req/min authenticated. Useful as match-key resolvers only.
- **Beatport** — no public popularity API; chart-position scraping is fragile + ToS-grey. Excluded from MVP.
- **`ALLOWED_AUDIO_ROOTS` sandboxing** — `app/main.py:138-198` (resolved roots + `Path.is_relative_to` check at line 192 + 617). Popularity enrichment does NOT open audio files — pure HTTP — so sandbox does not gate this feature. Score lookups by `track_id`/ISRC/title+artist, not by file path.
- **Analysis pipeline isolation** — `app/analysis_engine.py` is offline DSP (librosa/madmom/essentia), no network. Popularity = orthogonal phase, runs after analysis completes or on demand. No `_db_write_lock` contention with analysis batches.
- **httpx pattern required** — `coding-rules.md` forbids `requests.get` in `async def`. Popularity adapters MUST use `httpx.AsyncClient` + timeout + retry (`tenacity` or hand-rolled exponential backoff, see SC pattern at `app/soundcloud_api.py:220-232`).
- **Schicht-A dep pinning** — every new dep in `requirements.txt` as `==X.Y.Z`. Hand-rolled httpx adapters preferred over per-source SDKs (smaller surface, easier pin / CVE check). Approx new pins: `spotipy` or hand-roll (prefer hand-roll), `pylast` or hand-roll (prefer hand-roll).

## Open Questions

> Numbered. Each one should be resolvable (yes/no, or "X vs Y"), not open-ended philosophy.

1. **Score shape** — continuous 0–1 OR discrete bands OR both? **RESOLVED:** both — store continuous (`mainstream_score: float`) + derived band (`mainstream_band: enum`). Continuous wins for sort/filter; band wins for badge UX + cross-platform aggregation tolerance. Cheap to derive band on read.
2. **Genre-relative vs global normalisation** — depends on genre-tag coverage. **PARKED until library audit**: needs `SELECT COUNT(*) WHERE Genre IS NULL OR Genre = ''` on real `master.db`. Hypothesis: SC-imported tracks ≥ 80% have genre (SC propagates), Bandcamp ≥ 60%, raw drag-drop ≤ 30%. Decision deferred to draftplan after measurement.
3. **MVP platform set** — **RESOLVED (Findings #2):** Spotify + SoundCloud + Last.fm. YouTube deferred to Phase 3 (quota math: 30k × 100 units search = 30 days). Last.fm IN (5 req/s + free + MBID match path).
4. **Trust weighting** — equal mean OR genre-aware? **RESOLVED (partial):** start equal-mean for MVP simplicity; user-tunable weights in `settings.json` once enough listening proves a default per-genre profile (e.g. SC>>Spotify for techno). Defaults shipped: `{spotify: 1.0, soundcloud: 1.0, lastfm: 1.0}`. Genre profiles = Phase 2 enhancement.
5. **Refresh cadence** — per-import vs scheduled vs lazy? **RESOLVED (Findings #2):** TTL sidecar (SC=24h, Spotify=7d, LastFM=7d) refreshed by scheduled background sweep + lazy fallback (`fetched_at IS NULL OR > TTL` triggers fetch on detail-panel open). Per-import = first-time scoring of newly added track only.
6. **Zero-platform tracks** — `unknown` vs pessimistic `underground`? **RESOLVED:** `unknown` band with `confidence=null`. Pessimistic-bias would silently corrupt set-planning filters ("warm-up only underground" picks unmatched obscure tracks as if curated). UI shows distinct visual (gray badge, "?" tooltip).
7. **Fuzzy threshold** — `0.65` vs `0.80` cross-platform? **RESOLVED (Findings #2):** ISRC > MBID > fuzzy@0.80. Tighten from 0.65 (which is SC-self matching — local tracks all share roughly comparable cleanliness) because cross-platform false-positive cost is higher (wrong-track popularity poisons score worse than missing data). Coordinate with `external_track_match_unified_module` OQ9 (per-source override pattern).
8. **UI display** — badge, color, both, sortable column? **PARKED until UX exploration**: UI affordance decision belongs in a frontend exploration loop, not idea_. Backend ships score + band + raw per-platform; frontend chooses surface (badge / color-coded row / column / facet filter) iteratively.
9. **Per-platform raw counts to user** — transparency vs simplicity? **RESOLVED:** ship both. Aggregated score on main row; expandable "popularity breakdown" panel showing per-platform raw + normalised. Transparency lets users sanity-check matches (`Spotify: 88, SC: 12k, LastFM: 0.5k` — does this match the track they expect?) and report bad matches.
10. **Cache responses** — sidecar with `fetched_at` vs always fresh? **RESOLVED (Findings #2):** caching mandatory — cold rescan is hours-scale. SQLite sidecar row per (track_id, platform) with `raw_count`, `normalised`, `fetched_at`, `match_method`, `match_confidence`. Re-fetch on TTL expiry only.
11. **Spotify ToS for desktop distribution** — does Client Credentials use in a Tauri-bundled binary qualify as "commercial use" requiring extended terms? **PARKED — legal-track**: needs ToS read by owner before Phase 1 ships. Fallback: ship feature gated by user-supplied keys (env vars), not bundled creds, sidesteps distribution-credential question.
12. **Genre-cluster size threshold for genre-relative percentile** — `≥ 100 tracks` heuristic from Goals; needs validation. **PARKED until library audit (sibling of Q2)**: small clusters give noisy percentiles. Decision in draftplan after measuring real genre histogram.

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

**Caching + cadence.** Sidecar SQLite row per (track_id, platform) with raw_count, fetched_at, score. TTL: SC daily, Spotify/YouTube/Last.fm weekly. Cold scan of 30k library: Spotify ≈3h (30k/180/min) [SUPERSEDED by Findings #3 — batch endpoint changes economics to ~3.3 min], SC ≈2.5h (0.3s spacing), YT NOT FEASIBLE without ISRC (30k×100 units = 30 days of quota). Mitigation: YT-lookup only tracks where Spotify+SC+LastFM is inconclusive (rising band).

**Open Questions touched:** Q3 (MVP set) — Spotify+SC+Last.fm; YouTube fails economics. Q5 (cadence) — TTL sidecar refresh wins over per-import or full-rescan. Q7 (threshold) — ISRC > MBID > fuzzy@0.80 (tighten from 0.65; cross-platform false positives costlier than within-SC). Q10 (caching) — mandatory; cold rescan is hours-scale.

### 2026-05-15 — normalisation + banding defended by data / precedent + sidecar verification

**Sidecar precedent correction.** Prior Findings #1 claimed "no per-library sidecar DB exists yet" — wrong. Repo has 3 sidecar shapes today:
- `app/sidecar.py` — JSON `app_data.json` (tiny scale: artist→SC link map).
- `app/analysis_cache.py` — per-file gzip JSON + master `index.json` (DSP cache, lines 11-30).
- `app/anlz_sidecar.py` — per-track ANLZ files in `.lms_anlz/<sha>/` next to audio.
None of these fit popularity's shape (30k rows × 6 fields × multi-platform × needs query/sort). New SQLite sidecar warranted — precedent for filename + lifecycle from `analysis_cache.py`, SQL shape new.

**Cross-doc dependency.** `external_track_match_unified_module` (sibling idea_) owns fuzzy + ISRC/MBID match infrastructure. Recommended import direction once that module lands (Option C/M1): popularity calls `from app.external_track_match import fuzzy_match, resolve_isrc, resolve_mbid` rather than re-importing `_fuzzy_match_with_score` from `soundcloud_api.py` directly. Per-source threshold override (sibling OQ9) — popularity wants 0.80 for cross-platform; SC sync keeps 0.65 for within-platform. Both flow through the unified module's per-source config.

**Normalisation formula (concrete).** Per (track, platform):
```
raw_count                      # int from API (SC playback_count, Spotify popularity, LastFM playcount)
log_count   = log10(1 + raw_count)              # squash 6-order range to ~6.5 max
percentile  = ECDF_within_genre(log_count)      # 0..1, computed across all library tracks sharing genre
                                                 # OR ECDF_library_wide if genre-cluster < 100 (Q12)
platform_score = percentile                      # already 0..1
```
Per track aggregate (MVP equal-weight):
```
score = mean(platform_score for p in available_platforms)
band  = "underground" if score < 0.25
        "niche"       if 0.25 <= score < 0.55
        "rising"      if 0.55 <= score < 0.75
        "mainstream"  if score >= 0.75
confidence = "high"   if len(available_platforms) >= 2
             "low"    if len(available_platforms) == 1
             "unknown" if len(available_platforms) == 0  → band = "unknown"
```

**Spotify `popularity` exception.** Already 0–100 normalised by Spotify proprietary recency-weighted algorithm (not raw count) — skip `log10` step, use `popularity/100` directly. Documented behavior: weighting favours recent plays, so 2015-hit-now-cold scores lower than 2024-sleeper-trending. This actually aligns with mainstream/underground intent (current cultural cachet).

**Banding threshold defence.** 0.25 / 0.55 / 0.75 chosen because:
- 25-th percentile naturally splits "long tail" from "tracked"; mirrors Pareto-style 80/20.
- 55 / 75 leaves a wider `niche` band than `rising` / `mainstream` because most curated DJ libraries skew underground-and-niche (intentional curation removes a chunk of pure-pop, so the natural distribution of a DJ library should not be uniform 0-1). Asymmetric bands compensate.
- Tunable: thresholds in `settings.json` as `{"underground_max": 0.25, "niche_max": 0.55, "rising_max": 0.75}`. User can re-band without recompute.

**ISRC coverage hypothesis.** Library composition shapes match-key choice:
- Beatport/iTunes/Bandcamp commercial purchases: ~100% ISRC (verified via `app/audio_tags.py:319` TSRC frame consumption).
- SC downloads via `app/soundcloud_downloader.py`: ~0% (line 723-727 explicitly drops ISRC, `audio_tags.write_tags` has no alias).
- Drag-drop / unknown source: ~30-50% (depends on ripper / source).
- → ISRC-first match works for purchased majority; fuzzy@0.80 fallback for SC + drag-drop tail. Q12 audit informs the exact split.

**Performance math redux (confirms goal G7).**
- Spotify: 30 000 tracks ÷ 50 IDs/batch = 600 batches × ~333ms (180 req/min) = 200s = **3.3 min** (was over-estimated as 3h — batch endpoint changes economics).
- SoundCloud: 30 000 × 0.3s = 9 000s = **2.5h** (no batch endpoint).
- LastFM: 30 000 ÷ 5/s = 6 000s = **1.7h**.
- All parallel-capable → wall-time ≈ max ≈ **2.5h** plus retries + match resolution. Within 6h budget (G7).

**Open Questions touched (this entry):** Q1 (score shape) — both stored. Q6 (zero-platform) — `unknown` not pessimistic. Q9 (raw counts to user) — both. Q11 (Spotify ToS) — PARKED legal-track. Q12 (cluster-size) — PARKED until audit.

## Options Considered

> Required by `evaluated_`. For each viable approach: sketch (2-4 lines), pros, cons, effort (S/M/L/XL), risk.

### Option A — Single-source MVP (SoundCloud only)
- Sketch: Read `playback_count` from the SoundCloud V2 response already fetched by `soundcloud_api.py`, log-scale, percentile-rank within library, store in sidecar DB. No new providers.
- Pros: Zero new auth or env vars; reuses existing client + fuzzy matcher; ships fastest; validates UX and storage shape before scaling.
- Cons: Heavily biased toward SoundCloud demographics (electronic-leaning); silent on tracks not on SC; one platform = one outage = no score.
- Effort: S
- Risk: Low. Worst case = poor signal quality; easy to layer more providers later.

### Option B — Multi-source aggregate (Spotify + SoundCloud + Last.fm; YouTube deferred to M4)
- Sketch: Match each track against 3 platforms at M2 (ISRC → MBID → fuzzy@0.80). Normalise via log + per-genre percentile (per Findings #3 formula). Aggregate by mean. Emit continuous score + derived band.
- Pros: Robust to single-platform gaps; cross-validates; bedroom/indie/commercial axes covered.
- Cons: Three new API integrations + secrets; matching quality dominates the signal — bad matches = bad scores; recency-biased Spotify `popularity` may misrepresent vintage hits.
- Effort: L
- Risk: Medium. Match false-positives + Spotify recency-bias are main failure modes; mitigable with caching + tightened thresholds + per-platform raw-count UI for user verification.

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

**Composite path = Option A → Option B (with banding heuristic from Option D layered on top).** Option C deferred to Phase 4 (post-MVP); coverage-gap risk on underground tracks inverts the signal.

**Phased rollout** — each milestone has concrete deliverable + entry/exit conditions:

### M1 — Single-source MVP (Option A)
- **Deliverable**: SoundCloud-only popularity. New `app/popularity_engine.py` reads `playback_count` from existing SC payload (just add 1 dict key in `_normalize_track` at `soundcloud_api.py:297-330`). New sidecar SQLite `popularity.sqlite` with schema `(track_id, platform, raw_count, log_count, percentile, fetched_at, match_method, match_confidence)`. Backend endpoint `GET /api/popularity/{track_id}`. Frontend stub: numeric badge on track row.
- **Entry**: Q1, Q3, Q6 RESOLVED (yes — see Findings #2 + #3). No Spotify dep at M1 → Q11 not gating.
- **Exit**: Backend + sidecar SQLite landed; `GET /api/popularity/{id}` returns valid JSON for ≥ 80% of SC-imported tracks in `tests/test_popularity_engine.py`; UI badge renders without breaking layout (e2e screenshot). Single-source `confidence=low` correctly tagged. Library audit (Q2/Q12) for genre histogram landed as side-deliverable so M2 entry isn't blocked on data-gathering.
- **Effort**: S (one week).
- **Rollback**: delete sidecar SQLite + revert endpoint registration; SC sync untouched (only payload-key add reverts cleanly).

### M2 — Multi-source aggregate (Option B)
- **Deliverable**: Add Spotify (`q=isrc:` batch lookup, 50 IDs/call) + Last.fm (`track.getInfo` via MBID/fuzzy@0.80). Aggregate score formula from Findings #3 (log + ECDF + mean). Banding (Option D heuristic layered). Per-platform raw counts surfaced in detail panel (Q9). UI: expandable popularity breakdown.
- **Entry**: M1 EXITED. Q2 + Q12 RESOLVED via M1's library-audit side-deliverable (genre histogram measured; global-vs-per-genre threshold chosen). Q11 RESOLVED — owner has read Spotify ToS OR user-supplied-key fallback wired. `external_track_match_unified_module` either shipped Option C M1 (fuzzy + ISRC/MBID exposed as functions, popularity imports them) OR popularity ships own copies + refactor scheduled at unified-module ship.
- **Exit**: First full scan completed; coverage metric measured (`≥ 50% of library has 2+ platform coverage` — if below, re-tune fuzzy thresholds or match-key order before declaring exit); cold full scan completes in ≤ 6h on residential broadband (G7 metric); per-platform raw counts displayed in UI detail panel without exposing API errors as visible noise.
- **Effort**: L (2-3 weeks).
- **Rollback**: feature-flag in `settings.json` — `{"popularity_platforms": ["soundcloud"]}` collapses M2 to M1 without code revert. Spotify/LastFM rows in sidecar remain (harmless data).

### M3 — Bias-correction + adaptive weighting
- **Deliverable**: Genre-aware weighting (techno → SC > Spotify > LastFM; pop → Spotify > LastFM > SC). User-tunable in `settings.json`. ListenBrainz integration (open scrobble data, no quota) as 4th MVP source.
- **Entry**: M2 EXITED for ≥ 2 weeks (real-usage telemetry from local-only logs reveals systematic genre bias OR user reports it).
- **Exit**: Equal-mean baseline replaced; "set-planning warm-up underground" filter selects tracks user agrees are underground in ≥ 80% spot-check (manual eval, n=30).
- **Effort**: M (one week, mostly config + tests).
- **Rollback**: `settings.json` toggle reverts to equal-weight.

### M4 — YouTube + Beatport (deferred, post-MVP)
- **Deliverable**: YouTube `videos.list` only on tracks still in `rising` band after M1-M3 (gates quota usage). Beatport chart-position scrape (opt-in ToS-grey).
- **Entry**: M3 EXITED. Quota math re-verified — `rising`-band size < 100 tracks/day refresh OR user accepts longer refresh cycle.
- **Exit**: YouTube/Beatport adapters in production, quota dashboard / log line shows < 50% daily budget consumed.
- **Effort**: M.

**Gates before promotion `exploring_` → `evaluated_`:**
- M1 entry conditions met (Q1/Q3/Q6 RESOLVED; ToS path chosen for Q11).
- Library audit started (informs Q2 + Q12 PARKED items).
- Cross-doc coordination point with `external_track_match_unified_module` reflected in M1 design (either: (a) wait for unified module M1, then import; or (b) own fuzzy locally, refactor at unified-module ship).
- Concrete sidecar SQLite location: alongside `app_data.json` (per `app/sidecar.py:7` pattern), named `popularity.sqlite`.

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

- Code (existing, M1 entry points):
  - `app/soundcloud_api.py:36` (`get_sc_client_id`) — auth resolution.
  - `app/soundcloud_api.py:297-330` (`_normalize_track`) — payload normalizer; add `playback_count` key here.
  - `app/soundcloud_api.py:566-587` (`_fuzzy_match_with_score`, threshold `0.65` at L583) — fuzzy matcher; coordinate with unified module.
  - `app/audio_tags.py:319` — ISRC tag parse (`TSRC` ID3 frame + iTunes `----:com.apple.iTunes:ISRC` MP4 atom).
  - `app/services.py:1111` — ISRC writer into `track_data` dict pre-`master.db` insert.
  - `app/usb_pdb.py:497` — ISRC USB-export devicesql string slot 0.
  - `app/database.py:22` — `_db_write_lock` RLock (NOT `app/main.py` — corrected vs prior).
  - `app/main.py:138-198` — `ALLOWED_AUDIO_ROOTS` sandboxing (not gating popularity; informational).
  - `app/sidecar.py:7-38` — JSON sidecar precedent (filename + lifecycle pattern).
  - `app/analysis_cache.py:11-30` — gzip JSON cache precedent.
  - `app/anlz_sidecar.py:24-27` — sidecar-dir hash pattern.
- External docs:
  - Spotify Web API: https://developer.spotify.com/documentation/web-api/reference/get-several-tracks (batch up to 50 IDs), https://developer.spotify.com/documentation/web-api/reference/search (ISRC search).
  - SoundCloud V2: undocumented; observed via dynamic-client-id scrape (`app/soundcloud_api.py:69-110`).
  - Last.fm `track.getInfo`: https://www.last.fm/api/show/track.getInfo
  - MusicBrainz: https://musicbrainz.org/doc/MusicBrainz_API (1 req/s)
  - YouTube Data API v3 quota: https://developers.google.com/youtube/v3/determine_quota_cost
- Related research:
  - `external-track-match-unified-module` (sibling) — owns fuzzy + ISRC/MBID resolution at M1; popularity imports from it once shipped.
