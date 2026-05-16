---
slug: library-extended-remix-finder
title: Find Extended / Club / Long versions of every track in library
owner: tb
created: 2026-05-15
last_updated: 2026-05-15
tags: [remix, extended-mix, soundcloud, beatport, discovery, dj-workflow]
related: [analysis-remix-detector, library-quality-upgrade-finder, external-track-match-unified-module]
---

# Find Extended / Club / Long versions of every track in library

> **State**: derived from filename + folder. Do not store state in frontmatter.
> Start the file as `docs/research/research/idea_<slug>.md`. Rename + move on each transition (see `../README.md`).

## Lifecycle

> Append-only audit trail. One line per `git mv`. Newest at the bottom.

- 2026-05-15 — `research/idea_` — created from template
- 2026-05-15 — research/idea_ — section fill (research dive)
- 2026-05-15 — research/idea_ — UX + source-priority refinement after Problem framing
- 2026-05-15 — research/idea_ — exploring_-ready rework loop (deep self-review pass)

---

## Problem

> Required from `idea_` onward. Keep under 100 words. What are we solving? Why does it matter? What happens if we don't?

DJs frequently end up with the **Radio Edit** (2:30–3:30) of a track from streaming/casual sources when what they actually need for mixing on the CDJs is the **Extended Mix / Club Mix / Long Version** (5:00–7:30) with the long intro/outro that gives 16–32 bars of clean kick/groove for blending. Today the library has no way to surface "your `Track X (Radio Edit)` has an Extended Mix on Beatport/SoundCloud/Bandcamp you don't own yet." DJs work around this manually (search per track at gig-prep time) or simply mix short versions, which produces ugly transitions. This doc designs the **cross-source scanner** that surfaces ranked replacement/companion suggestions per library track, with user-confirmed add. Sister-doc `analysis-remix-detector` handles the within-library variant grouping; this doc handles the not-yet-in-library discovery.

## Goals / Non-goals

**Goals** (each with success metric)
- Surface candidate Extended/Club/Long versions per library track from external sources (SC, Beatport, Bandcamp, YouTube, Discogs) not in local lib. **Metric: precision >= 0.85 on a 200-track hand-labelled gold set; recall >= 0.60 on tracks where Discogs lists an Extended.**
- Confidence band (high/med/low) per candidate from artist + title-stem + duration band + provenance. **Metric: high-band precision >= 0.95 (almost no false-positives in green badges).**
- One-click "Add to library" per candidate (SC download path for SC; copy-link for paid platforms). **Metric: M1 covers >= 1 actionable source (SC).**
- Cache external queries — 30k library re-scan completes in <= 10 min if no library changes since last scan (negative-cache hit). **Metric: cache hit rate >= 0.90 on second consecutive scan.**
- Reuse `SoundCloudSyncEngine._fuzzy_match_with_score` (`app/soundcloud_api.py:566`, threshold 0.65) — extracted to shared module per sister-doc `external-track-match-unified-module`. **Metric: zero forks; single import path.**

**Non-goals** (deliberately out of scope)
- Detecting *remixes* of a track (different artist remixing same title) — that is `idea_analysis-remix-detector`'s job.
- Finding *higher-bitrate copies of the same edit* — that is `idea_library-quality-upgrade-finder`'s job.
- Automatic download/purchase without user confirmation. The user always decides per-candidate.
- Re-encoding YouTube rips. If the candidate is a YouTube re-upload, surface as low-confidence and let user decide.
- Bootleg / unauthorised mashup discovery.

## Constraints

> External facts that bound the solution space — API rate limits, existing data shape, performance budgets, legal/licensing, team capacity. Cite source where possible.

- **SoundCloud API:** OAuth wired (`app/soundcloud_api.py:_sc_get` at line 167). **Search endpoint NOT yet implemented** — current `SoundCloudClient` only resolves known IDs / fetches user playlists. `/tracks?q=...` (v1 API, `SC_API_BASE` at line 131) needs adding; shape returns `[{id, title, user.username, duration, permalink_url, ...}]` (same shape used by `get_full_playlist_tracks`). 429 backoff already implemented in `_sc_get` (Retry-After header, exponential retry, max 3). No documented hard rate limit; informal ~15k req/day per client_id observed.
- **SoundCloud fuzzy matcher:** `_fuzzy_match_with_score` (`app/soundcloud_api.py:566`). **Uses `difflib.SequenceMatcher` (stdlib), NOT rapidfuzz** — threshold 0.65 hardcoded at line 583. Reconciles SC playlist tracks → local lib; here we invert: SC search results → local-lib-derived query.
- **Beatport:** no public REST API for free use. Options: HTML scrape `beatport.com/search?q=...` (fragile, ToS grey) or user-provided links. Beatport track JSON exposes `mix_name` (`Extended Mix`/`Original Mix`/`Radio Edit`) — canonical taxonomy source. **Defer to M3.**
- **Bandcamp:** no official search API; `bandcamp.com/search?q=...` HTML scrape works but Cloudflare-rate-limited. Lossless WAV/FLAC often purchasable. **Defer to M3.**
- **YouTube:** YouTube Data API v3 quota = 10k units/day default; `search.list` costs 100 units → ~100 searches/day per key. **Per-track-trigger only; never batch.** **Defer to M3 behind feature flag.**
- **Discogs:** REST API, **60 req/min authenticated** (token in `Authorization: Discogs token=<token>`), free. User-Agent string required. Release tracklist exposes `duration` + version labels reliably (`Extended Mix (7:32)`). Ground-truth gate for "does an Extended exist at all?". 60/min × 60 min = 3600/hr → 30k-track delta scan ~ 8.3 hr sequential, batchable via release-page caching (one release covers many tracks).
- **Library size:** target 5k–30k tracks. Linear scan even at 1 req/s/source = hours per source. Must be incremental (delta-scan since last run) + cache-heavy.
- **Title pattern ambiguity:** "Original Mix" on Beatport = canonical un-remixed (often 6–7 min, *is* extended). On SoundCloud "Original Mix" often = radio cut. **Source-aware parsing required.**
- **Duration heuristic bands:** radio ≤ 3:30, club 5:00–7:30, extended 5:30–9:00. Bands overlap — duration alone never sufficient.
- **DB schema:** library tracks in Rekordbox `master.db` (read via `pyrekordbox`). All writes go through `_db_write_lock` at **`app/database.py:22`** (RLock). This feature is read-only against `master.db` → no lock acquisition needed. Candidate suggestions in sidecar SQLite (`app/data/track_suggestions.db` — unified with sister-docs per their recommendation; `kind='extended'` column).
- **rbox quarantine:** rbox 0.1.5/0.1.7 panics via `Option::unwrap()` — `SafeAnlzParser` (`app/anlz_safe.py`) isolates via `ProcessPoolExecutor(max_workers=1)`. This feature does NOT call rbox directly (title-based matching only) → no quarantine needed.
- **`ALLOWED_AUDIO_ROOTS` (`app/main.py:138-189`):** applies when user accepts a candidate and the existing SC download path writes audio. Validation via `Path.is_relative_to(resolved_root)`. External URL fetches bypass this.
- **Httpx requirement:** new adapter HTTP calls in async paths must use `httpx.AsyncClient` + timeout + retry (coding-rules — no `requests.get` in async). Sync adapters may reuse the `_sc_get` pattern.
- **Reuse target:** matcher logic lives in `app/external_track_match.py` per sister-doc `external-track-match-unified-module` (Option C function-only + adapter registry). This doc consumes; does not fork.

## Open Questions

> Numbered. Each one should be resolvable (yes/no, or "X vs Y"), not open-ended philosophy.

1. **Sources for M1?** **RESOLVED** — SC-only at M1 (Option A behind plugin API per Recommendation). Discogs joins at M2 as gate. Beatport/Bandcamp/YouTube = M3 behind feature flags.
2. **Suggestion storage?** **RESOLVED** — sidecar SQLite at `app/data/track_suggestions.db` unified with sister-docs (`kind` column: `extended`/`upgrade`/`remix`). In-memory + JSON-per-track rejected (no restart survival, no scale to 30k × N sources).
3. **Trigger model?** **RESOLVED** — M1 = explicit button + right-click. M2 = adds opt-in idle delta-scan for tracks imported last 24 h (setting-gated). M3 = continuous on idle only if user opts in.
4. **Confidence-band UX policy?** **RESOLVED** — high = green badge always surfaced. Medium = Audit-view default visible, badge optional behind toggle. Low = hidden by default, reachable via "Show low-confidence" toggle + always-on right-click. Numeric score on hover.
5. **Caching TTL?** **RESOLVED** — source-specific. SC negative = 7 d, SC positive = 30 d. Discogs negative = 90 d, positive = 365 d (canonical data, slow-changing). Force-rescan button per track. Rationale: Discogs catalogue is curated; SC users add/delete uploads frequently.
6. **Cross-source dedup?** **RESOLVED** — collapse on `(artist_norm, title_stem_norm, duration_band)`. UI row shows multi-source provenance pills (SC + Discogs + Beatport). Chromaprint cluster dedup only if fingerprint already in shared cache (don't fetch audio just to dedup; gated on `external-track-match-unified-module` M2 fingerprint pipeline).
7. **"Already in library" definition?** **RESOLVED** — exclude if matches (a) any `master.db` content row OR (b) any track in pending SC download queue (`app/soundcloud_*` queue) OR (c) any candidate already accepted into `track_suggestions.db` with `accepted_at IS NOT NULL`.
8. **YouTube spam filter?** **PARKED** — only relevant when M3 ships YouTube plugin. Layered filter (verified-artist + chromaprint + popularity + keyword deny-list) sketched in Findings 2026-05-15 UX. Re-open at M3 draftplan.
9. **Match key for "same track"?** **RESOLVED** — primary `(artist_norm, title_stem_norm)`. ISRC override when both sides have it (high precision). Title-stem via shared extractor from `external-track-match-unified-module`. Duration as third signal in score, not key.
10. **UX surface?** **RESOLVED** — M1 = per-track badge in Library row + standalone "Library Audit" view (shared with sister-docs `remix-detector` + `quality-upgrade-finder` — single IA panel, NOT three competing). M2 = right-click "Find extended version" + Ranking-view sidebar.

**Newly opened (this rework):**
11. **SC search-endpoint addition** — wrap `/tracks?q=<artist> <title-stem> extended` in `SoundCloudClient.search_tracks()` (`app/soundcloud_api.py`) or build entirely inside `external-track-match-unified-module` SC adapter? **PARKED** — depends on whether sister-module M1 ships before this feature's M1. Decide at draftplan.
12. **Query-construction strategy** — single query per track (`<artist> <title-stem> extended`) vs three-fanned (`extended`, `club`, `long`) per track? Three-fanned triples API cost, single misses Club/Long that don't include "extended" token. **RESOLVED** — single query with broad keyword set (`<artist> <title-stem>`) + score filter post-fetch on version-tag. Cheaper, broader recall.
13. **Gold-set source for Goals metric** — need labelled 200-track set spanning genres (trance/house/pop/hip-hop) where extended-exists status is hand-verified. **PARKED** — owner deferred to draftplan; tag-mining `tests/fixtures/` may yield seed.

## Findings / Investigation

> Required from `exploring_` onward. Append dated subsections as you learn. Never edit past entries — supersede with a new one.

### 2026-05-15 — initial audit

> Note: see superseding entry **2026-05-15 — verification rework** below for corrections to matcher library + lock location + SC search-endpoint status. The asset-survey text below is preserved for audit.

**Existing assets in repo**
- `app/soundcloud_api.py` — `SoundCloudClient` (OAuth, search, stream-url, download), `SoundCloudSyncEngine` (library-wide reconciliation). Fuzzy matcher: `_fuzzy_match_with_score(sc_title, sc_artist, local_tracks)` at line 566, threshold constant 0.65 (rapidfuzz token-set ratio + artist gate). This is reusable as-is for "is candidate the same edit as library track?" — invert the loop: instead of "for each SC track, find local match", do "for each local track, find SC candidates above threshold AND with extended markers".
- `app/main.py:_db_write_lock` — RLock guarding all `master.db` writes. Candidate storage in sidecar SQLite avoids touching this.
- `app/anlz_safe.py:SafeAnlzParser` — read-only path to ANLZ; not needed here, candidates aren't analysed until user accepts them (then existing import path takes over).
- No existing Beatport / Bandcamp / Discogs / YouTube client in `app/`. Adding any of these = new dep (`google-api-python-client`, `python3-discogs-client`, plain `httpx` for scrape). Each adds Schicht-A pinning burden.

**Title parsing — version-tag taxonomy**
Extended-indicator tokens (case-insensitive, in parentheses or after dash):
- High confidence Extended: `extended mix`, `extended version`, `extended`, `club mix`, `long version`, `full version`, `12" mix`, `12" version`.
- Medium: `original mix` (Beatport-context only — means "unremixed", usually = extended cut), `dub mix`, `instrumental` (sometimes longer), `vocal mix`.
- Negative (these mean NOT extended): `radio edit`, `radio mix`, `short edit`, `clean edit`, `intro edit`, `single edit`.
- Genre-specific: in trance/big-room, `extended` is the default release form; in pop/hip-hop, `extended` is rare and a real find.

**Title-stem extraction**
For matching, strip the version tag: `"Strobe (Radio Edit)" → "Strobe"`, `"Strobe - Extended Mix" → "Strobe"`. Regex: `r"\s*[\(\[\-–]\s*(?:radio|extended|club|long|original|short|dub|instrumental|vocal|intro|clean|single)\s+(?:edit|mix|version)\s*[\)\]]?$"`. Run on both library and candidate sides before similarity comparison.

**Duration bands**
- Radio: 2:30–3:45 (typical 3:00–3:30).
- Single edit: 3:30–4:30.
- Album / standard: 4:00–5:30 (highly variable).
- Club mix: 5:00–7:30.
- Extended mix: 5:30–9:00 (trance often 7–8 min).
- 12" mix: 6:00–10:00.
Duration alone is weak (a long album cut may be ~6 min without being "extended"). Combined with version-tag match, becomes strong.

**Confidence scoring (sketch)**
```
score = 0
+ 0.40  if artist exact (normalised)
+ 0.30  if title-stem exact (normalised)
+ 0.20  if duration >= 5:00
+ 0.15  if version-tag contains 'extended' / 'club' / 'long' / '12"'
- 0.30  if version-tag contains 'radio' / 'short' / 'clean'
- 0.20  if source = YouTube AND channel not in known-label-list
- 0.40  if title contains 'nightcore' / 'sped up' / 'slowed' / 'reverb' / 'remix by'

high   >= 0.85
med    0.65–0.85
low    0.45–0.65
drop   < 0.45
```

**Source-by-source quality assessment**
| Source | Has Extended distinct? | Metadata quality | API friction | Download path | v1? |
|---|---|---|---|---|---|
| SoundCloud | Often (producer/label uploads) | Good (title, duration, user) | Wired, OAuth | Existing | yes |
| Discogs | Yes (release tracklist) | Excellent (canonical) | REST, 60/min | None (link only) | yes |
| Beatport | Yes (`mix_name` field) | Excellent | Scrape, fragile | None (paid) | v2 |
| Bandcamp | Sometimes | Variable | Scrape, CF-gated | None (paid) | v2 |
| YouTube | Yes but spam-heavy | Poor (titles lie) | API quota tight | yt-dlp (legal grey) | v3 / opt-in |

**Discogs as ground-truth oracle**
Discogs release pages list every version of a track with canonical durations. Query pattern: `/database/search?artist=X&track=Y&type=release`. Each hit has a tracklist with `position`, `title`, `duration`. If Discogs shows a 7:32 "Extended Mix" exists and we only have the 3:24 "Radio Edit", that's an authoritative "extended exists somewhere" signal — even if we don't yet have a download source. Use Discogs to *gate* whether to spend SC/Beatport quota on a track.

**Caching layer**
Sidecar SQLite `app/data/extended_candidates.db`:
- `queries(track_id, source, query_hash, queried_at, result_status)` — negative-cache + dedup.
- `candidates(id, track_id, source, source_id, title, artist, duration_s, version_tag, url, score, band, discovered_at, dismissed_at, accepted_at)`.
- Index on `track_id`, `(source, source_id)` unique to dedup.
- TTL governed by `queried_at` + source-specific window (SC=7d, Discogs=90d).

**Reuse vs new module**
Extending `SoundCloudSyncEngine` with a `find_extended_candidates(track)` method is straightforward — it already has the SC client + fuzzy matcher. But the multi-source orchestrator (SC + Discogs + future Beatport) should be a new module `app/extended_finder.py` that owns the source plugins, scoring, caching, and exposes a single API for the frontend. Each source = plugin class with `search(track) -> list[Candidate]`.

**Performance ballpark**
30k tracks × 2 sources × 0.5s avg latency = 30k seconds ≈ 8 hours wall-clock single-threaded. Parallelism per-source (SC max 4 concurrent, Discogs max 1/sec) brings to ~2 hours. Caching + delta scans (only new/changed tracks since last full scan) makes incremental runs minutes.

### 2026-05-15 — UX + source-prioritisation after Problem framing

**UX entry-points (cheapest → richest)**
- **Per-track badge in Library view** — small "EXT?" pill on rows with high-confidence candidate. Cheap: reuses existing track-list. Cost: extra column query + async badge-fetch per viewport row.
- **Per-track right-click "Find extended version"** — on-demand, single track, ~2s. Good for one-off triage; bad for library-wide audit.
- **Standalone "Extended Audit" view** — dedicated panel listing every suggestion, sortable by confidence/date/source. Full scan kicked from here; UX cost: new route + view component.
- **Sidebar in Ranking view** — when user opens a Radio-Edit, show "Extended candidates" inline. Highest contextual relevance, lowest discoverability for tracks not currently being ranked.
- Recommend M1 = badge + Audit view (covers passive + active). Right-click + Ranking sidebar wait for M2.

**Source priority + dedup**
Surface all candidates per track, sorted: lossless paid (Beatport / Bandcamp) > Discogs link-only (canonical reference) > SoundCloud (free download) > YouTube (last resort). Quality marker badge per row. Dedup key = `(normalised_artist, title_stem, duration_band)` — same logical version across sources collapses into one row with multi-source provenance pills. Chromaprint dedup only if fingerprint already computed (don't fetch audio just to dedup).

**Confidence-tier policy**
- **High (green badge)** — artist exact + title-stem exact + duration ≥ 5:30 + version-tag matches Extended/Club/Long/12". Always surfaced.
- **Medium (yellow, details on click)** — one signal missing (e.g. duration met but version-tag is "Original Mix"). In Audit view; badge optional behind toggle.
- **Low (hidden by default)** — only fuzzy match, no version-tag. Reachable via "Show low-confidence" toggle + always on right-click search.

**Avoiding YouTube/spam re-uploads**
Layered filter: (1) uploader-vs-official-artist match via Discogs artist URLs / SC verified-artist flag, (2) chromaprint match against library Radio Edit (shared with `remix-detector` pipeline — extended must share harmonic profile, not be transposed nightcore), (3) play-count / follower threshold per platform, (4) deny-list keywords (`nightcore`, `sped up`, `slowed`, `1 hour`, `FREE DOWNLOAD`, `FULL VERSION`).

**Cross-doc coordination**
`remix-detector` + `quality-upgrade-finder` + this doc all share `SoundCloudSyncEngine._fuzzy_match_with_score` (0.65), title-stem extractor, version-tag taxonomy, and (planned) chromaprint pipeline. Suggest unified `app/external_track_match.py` owning fuzzy + version-parse + fingerprint helpers, consumed by all three. Design suggestion only — implementation belongs in whichever sister-doc lands first or a shared refactor doc.

### 2026-05-15 — verification rework + spam/source-priority deepening

**Code-truth corrections** (verified vs `app/soundcloud_api.py` + `app/database.py`):
- `_db_write_lock` lives at **`app/database.py:22`**, NOT `app/main.py`. Earlier draft was wrong; constraints corrected. This feature is read-only against `master.db` (only writes its sidecar) → lock not acquired.
- Fuzzy matcher uses **`difflib.SequenceMatcher`** (`app/soundcloud_api.py:16`, line 582), NOT rapidfuzz. Token-set behaviour weaker than rapidfuzz `token_set_ratio`; threshold 0.65 calibrated against SequenceMatcher. Sister-doc `external-track-match-unified-module` may migrate to rapidfuzz on extraction — if so, threshold needs recalibration on the gold set (`Goals` metric anchor).
- **SoundCloud `search()` endpoint NOT yet implemented** in `SoundCloudClient`. Need to add `search_tracks(q, limit)` wrapping `GET {SC_API_BASE}/tracks?q=<...>` + `client_id` + OAuth header via existing `_sc_get` helper. Response shape mirrors `get_full_playlist_tracks` (id, title, user.username, duration, permalink_url, …). Listed as OQ #11.
- `_sc_get` already has 429 backoff (Retry-After header parse, exponential, max 3 retries). Inherit transparently.

**Discogs API surface — verified for ground-truth gate**:
- Endpoint: `GET https://api.discogs.com/database/search?artist=<X>&track=<Y>&type=release&per_page=25`.
- Auth: `Authorization: Discogs token=<personal_token>` (free, no OAuth flow) OR consumer key/secret for higher trust tier. User-Agent header REQUIRED (`<AppName>/<Version> +<URL>`).
- Rate: **60 req/min authenticated** (1 / sec). Unauthenticated = 25 req/min — too tight; require token.
- Per-release follow-up: `GET https://api.discogs.com/releases/<id>` returns `tracklist[]` with `position`, `title`, `duration` ("7:32"). Single release covers up to ~20 tracks → batch-friendly.
- Pagination: `?per_page=25&page=N`. Stop at first release with matching `track.title` + Extended-indicator in tracklist.
- Negative-cache: empty search result OR no extended-tagged track in any matched release → cache 90 d.

**Source-priority refinement** (re-stated with M-mapping):
- **M1**: SoundCloud only. Surface link badges; existing SC download path handles "Add to library".
- **M2**: + Discogs as gate. Discogs query first → if no extended exists anywhere → cache negative + skip SC. Otherwise SC search runs. Discogs link surfaced as "Reference (not downloadable)" pill.
- **M3**: + Beatport/Bandcamp (link-only, paid). YouTube last, feature-flagged. Spam filter (OQ #8) lives here.

**Spam-filter primer** (parking until M3 but spec-shape settled):
- **Tier 1 deny-list keywords** (case-insensitive substring in title): `nightcore`, `sped up`, `slowed`, `reverb`, `1 hour`, `1hour`, `[FULL VERSION]`, `FREE DOWNLOAD`, `[FREE]`, `LEAK`, `+pitch`, `-pitch`, `bass boosted`. Hard reject.
- **Tier 2 uploader gating**: SC verified-artist flag OR uploader name matches official-artist Discogs page OR YouTube channel in user-curated allowlist. Below: cap at low-band.
- **Tier 3 audio gate** (M2-fingerprint dependent): chromaprint similarity vs library Radio Edit must be > threshold (same harmonic profile; rejects nightcore/sped-up). If fingerprint unavailable → cap candidate at medium-band.
- **Tier 4 popularity floor** (per-platform): SC plays >= 1k OR YouTube views >= 10k for low-band; >= 100k for medium. Adjustable in settings.
- User-curated blocklist: `app/data/spam_blocklist.json` (channel/uploader IDs). Trumps all tiers.

**Latest UX entry-point ordering** (M1 → M3, by discovery cost):
- **M1 entry-points**: (a) per-row green badge in Library view ("EXT" pill, click → candidate modal) for high-confidence. (b) Standalone "Library Audit" tab (shared with sister-docs) — single panel listing all surfaced suggestions across `extended` + `upgrade` + `remix` kinds, filterable by kind. (c) Bulk "Scan library" button inside Audit view.
- **M2 entry-points**: + (d) right-click "Find extended version" on any track (on-demand, single track, ~2 s). (e) Ranking-view sidebar when a Radio-Edit is opened (contextual).
- **M3 entry-points**: + (f) Settings panel for per-source enable/disable + YouTube spam thresholds.
- NEVER auto-at-import. NEVER auto-download. User explicit per candidate.

**Performance recheck with Discogs gate** (verified math):
- 30k tracks × 1 Discogs req each = 30k req. At 60/min = 500 min = 8.3 hr cold scan.
- With release-page caching: assuming ~50 % of library shares releases (compilations, EPs) → effective ~15k req → 4.2 hr.
- Discogs gate reduces SC fan-out by ~60 % (estimate based on Discogs catalogue coverage for electronic). Net 30k × 0.4 × 1 SC req = 12k req. At 4 concurrent → 50 min wall-clock.
- **Net cold-scan budget**: ~5 hr. Incremental delta-scan (only new/changed tracks since last run): minutes. **Metric-feasible** for the cache-hit goal.

## Options Considered

> Required by `evaluated_`. For each viable approach: sketch (2-4 lines), pros, cons, effort (S/M/L/XL), risk.

### Option A — SoundCloud-only minimal viable finder
- Sketch: Extend `SoundCloudSyncEngine` with `find_extended_candidates(track)` method. For each library track lacking an "extended" sibling, search SC for `"<artist> <title-stem> extended"`, filter results by duration ≥ 5:00 and title regex, score, store in sidecar SQLite. New FastAPI route `POST /api/extended/scan` (acquires `_db_write_lock` for reads only — actually no lock needed since we don't write `master.db`). New Suggestions tab in frontend lists candidates with "Download via SC" button (reuses existing SC download path).
- Pros: Single source = no new deps, no scraping, leverages wired OAuth. Existing fuzzy matcher reused. Smallest blast radius. Ships in a week.
- Cons: SC coverage is patchy outside electronic genres. Misses Beatport-exclusive releases entirely. No ground-truth gate, so wastes quota on tracks that have no extended anywhere.
- Effort: S
- Risk: Low. Worst case: low recall, but no spam since SC titles are reasonably honest within producer/label uploads.

### Option B — Multi-source with Discogs gate (recommended)
- Sketch: New module `app/extended_finder.py` owning `SourcePlugin` interface (`search`, `parse_version`, `quota_remaining`). Implements `DiscogsPlugin` (ground-truth oracle, gates whether to spend SC quota) + `SoundCloudPlugin` (existing client wrapped). Workflow per track: (1) Discogs lookup → does an Extended/Club/Long version exist on any release? If no → cache negative, skip. If yes → (2) SoundCloud search for downloadable candidates. (3) Score, dedup, persist. Sidecar SQLite + new routes `POST /api/extended/scan`, `GET /api/extended/candidates`, `POST /api/extended/dismiss`, `POST /api/extended/accept`. Frontend Suggestions tab.
- Pros: Discogs gate dramatically reduces wasted SC requests. Plugin architecture means Beatport/Bandcamp slot in later without refactor. Negative-cache from Discogs is durable (canonical data). Highest precision because two-source corroboration possible.
- Cons: New Discogs dep (`python3-discogs-client` or hand-rolled httpx — prefer hand-rolled, smaller surface). Two-stage flow adds latency. More moving parts than Option A.
- Effort: M
- Risk: Medium. Discogs catalogue gaps for very-new releases (< 30 days) cause false negatives — mitigated by treating Discogs miss as "unknown, try SC anyway with lower confidence" rather than hard skip.

### Option C — Plugin-architecture v2 with Beatport + Bandcamp + YouTube
- Sketch: Option B plus Beatport HTML scrape, Bandcamp HTML scrape, YouTube Data API plugin. Beatport/Bandcamp produce link-out candidates (no download, "Buy" CTA). YouTube produces low-confidence downloadable candidates behind a spam filter (channel allowlist, title deny-list). Optional yt-dlp integration behind a feature flag.
- Pros: Maximum coverage. Catches Beatport-exclusives that never reach SC. Bandcamp finds lossless purchases. YouTube catches obscure long-tail.
- Cons: Beatport / Bandcamp scraping is ToS grey and Cloudflare-fragile. YouTube quota (100 searches/day) is too low for batch scans — needs per-track-trigger mode only. yt-dlp introduces legal exposure for the project. Heaviest spam-filter burden falls here.
- Effort: L
- Risk: High. Maintenance load (scrapers break), legal exposure (yt-dlp), spam-filter false positives.

### Option D — Discogs-only "extended exists?" notifier
- Sketch: Just tell the user "for these N tracks an Extended Mix exists on Discogs" with the Discogs release URL. No download, no SC lookup, no Suggestions tab — just a report. User goes hunting on their own.
- Pros: Trivial to build (S). No spam, no quota concerns, no false positives because Discogs is canonical.
- Cons: No actionable "Add to library" path — the whole point of the feature is to close the loop. Useful as a fallback / reporting mode, not as the primary feature.
- Effort: S
- Risk: Very low. Could ship as a debug/preview mode for Option B.

## Recommendation

> Required by `evaluated_`. Which option, what we wait on before committing.

**Phased Option A → Option B → Option C**, behind plugin architecture from day one. Sister-doc `external-track-match-unified-module` Option C (function-only flat module + adapter registry) supplies fuzzy + version-parse from M1; chromaprint from M2.

Rationale: Pure Option A ships fastest but locks UX into single-source assumptions. Pure Option B forces Discogs dep into M1. Plugin-shaped Option A lets M2 slot Discogs in without UI rework — Option B's gate-precision win is paid for only when Discogs lands. Option C plugins live behind feature flags throughout.

### M1 — SC-only finder (Option A shape, plugin API)
**Deliverables**
- `app/external_track_match.py` consumed (per sister-doc): `extract_title_stem`, `parse_version_tag`, `fuzzy_match`. `Candidate` dataclass imported.
- `app/extended_finder.py` — orchestrator with `SourcePlugin` interface (`name`, `search(track) -> list[Candidate]`, `quota_remaining()`).
- `app/extended_finder/plugins/soundcloud.py` — wraps new `SoundCloudClient.search_tracks(q)` (NEW endpoint, see OQ #11). Scores candidates via version-tag + duration.
- Sidecar SQLite `app/data/track_suggestions.db` (unified, `kind='extended'`). Schema: `queries(track_id, source, query_hash, queried_at, result_status)`, `candidates(id, track_id, kind, source, source_id, title, artist, duration_s, version_tag, url, score, band, discovered_at, dismissed_at, accepted_at)`.
- FastAPI routes: `POST /api/extended/scan` (bulk, async job), `GET /api/extended/candidates?track_id=…`, `POST /api/extended/dismiss`, `POST /api/extended/accept` (kicks SC download).
- Frontend: per-row "EXT" badge in Library view + standalone "Library Audit" tab (kind filter; shared IA with sister-docs).
- Trigger: explicit button + right-click only. NEVER auto-at-import.

**Gates to ship**
- Gold-set evaluation: precision >= 0.85 on 200-track hand-labelled set (OQ #13 must close in draftplan).
- High-band precision >= 0.95 (no false-positive green badges).
- Cache hit rate >= 0.90 on second consecutive scan.
- `test-runner` green on `tests/test_extended_finder*.py`.
- `e2e-tester` confirms Library badge + Audit view + accept-flow round-trip.

### M2 — + Discogs gate + chromaprint (Option B shape)
**Deliverables**
- `app/extended_finder/plugins/discogs.py` — hand-rolled httpx (no SDK dep). Auth via `DISCOGS_TOKEN` env var; User-Agent string; 60/min throttle.
- Two-stage workflow: Discogs ground-truth gate → if extended exists, SC search. Else cache negative 90 d.
- `external-track-match-unified-module` M2 chromaprint pipeline consumed: same-edit detection upgrades scores; nightcore-rejection.
- UX: medium-band candidates default-visible in Audit view + right-click "Find extended version" + Ranking-view sidebar.
- Trigger model: + opt-in idle delta-scan (last 24h imports, setting-gated, default OFF).

**Gates to ship**
- Recall >= 0.60 on tracks where Discogs lists an Extended (Goals metric).
- Discogs gate reduces SC fan-out by >= 50 % on a 1k-track validation set.
- Chromaprint same-edit precision >= 0.95 (no wrong-version surfaced as match).
- `test-runner` green on Discogs adapter mock fixture suite.

### M3 — Paid + spammy sources (Option C shape, flagged)
**Deliverables**
- `app/extended_finder/plugins/beatport.py` (HTML scrape; link-out only; surface "Buy" CTA).
- `app/extended_finder/plugins/bandcamp.py` (HTML scrape; link-out only).
- `app/extended_finder/plugins/youtube.py` (Data API v3; per-track-trigger only, never batch). Spam filter Tiers 1–4 active.
- `app/data/spam_blocklist.json` user-curated blocklist.
- Settings UI: per-source enable/disable + spam thresholds + YouTube quota guard.

**Gates to ship**
- Only if M1+M2 metrics show recall gap > 0.20 vs gold set.
- YouTube spam filter precision >= 0.90 on a 100-spam-track adversarial test set.

### Cross-cutting (binds all milestones)
- Title-stem extractor + version-tag taxonomy in `external-track-match-unified-module`. NO fork.
- Sidecar `track_suggestions.db` unified with `quality-upgrade-finder` + `remix-detector`. Single schema, `kind` column.
- "Library Audit" frontend tab shared across the three sister-features. One IA panel, not three competing.
- Pre-promotion to `evaluated_`: confirm gold-set source (OQ #13), SC search-endpoint owner (OQ #11), sister-module `external-track-match-unified-module` lands at least M1 first.

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
