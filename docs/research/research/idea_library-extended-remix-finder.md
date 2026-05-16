---
slug: library-extended-remix-finder
title: Find Extended / Club / Long versions of every track in library
owner: tb
created: 2026-05-15
last_updated: 2026-05-15
tags: [remix, extended-mix, soundcloud, beatport, discovery, dj-workflow]
related: [analysis-remix-detector, library-quality-upgrade-finder]
---

# Find Extended / Club / Long versions of every track in library

> **State**: derived from filename + folder. Do not store state in frontmatter.
> Start the file as `docs/research/research/idea_<slug>.md`. Rename + move on each transition (see `../README.md`).

## Lifecycle

> Append-only audit trail. One line per `git mv`. Newest at the bottom.

- 2026-05-15 — `research/idea_` — created from template
- 2026-05-15 — research/idea_ — section fill (research dive)
- 2026-05-15 — research/idea_ — UX + source-priority refinement after Problem framing

---

## Problem

> Required from `idea_` onward. Keep under 100 words. What are we solving? Why does it matter? What happens if we don't?

DJs frequently end up with the **Radio Edit** (2:30–3:30) of a track from streaming/casual sources when what they actually need for mixing on the CDJs is the **Extended Mix / Club Mix / Long Version** (5:00–7:30) with the long intro/outro that gives 16–32 bars of clean kick/groove for blending. Today the library has no way to surface "your `Track X (Radio Edit)` has an Extended Mix on Beatport/SoundCloud/Bandcamp you don't own yet." DJs work around this manually (search per track at gig-prep time) or simply mix short versions, which produces ugly transitions. This doc designs the **cross-source scanner** that surfaces ranked replacement/companion suggestions per library track, with user-confirmed add. Sister-doc `analysis-remix-detector` handles the within-library variant grouping; this doc handles the not-yet-in-library discovery.

## Goals / Non-goals

**Goals**
- For each library track, surface a list of *candidate Extended / Club / Long versions* that exist on external platforms (SoundCloud, Beatport, Bandcamp, YouTube, Discogs) but are NOT yet in the local library.
- Score each candidate with a confidence band (high/med/low) based on artist match + title-stem match + duration band + provenance.
- One-click "Add to library" action per candidate (kicks the existing SoundCloud download path for SC; copy-link-to-clipboard for paid platforms like Beatport).
- Cache external query results so a 30k-track library doesn't re-hit every API every run.
- Reuse `SoundCloudSyncEngine._fuzzy_match_with_score` (threshold 0.65) for title/artist matching rather than re-inventing it.

**Non-goals** (deliberately out of scope)
- Detecting *remixes* of a track (different artist remixing same title) — that is `idea_analysis-remix-detector`'s job.
- Finding *higher-bitrate copies of the same edit* — that is `idea_library-quality-upgrade-finder`'s job.
- Automatic download/purchase without user confirmation. The user always decides per-candidate.
- Re-encoding YouTube rips. If the candidate is a YouTube re-upload, surface as low-confidence and let user decide.
- Bootleg / unauthorised mashup discovery.

## Constraints

> External facts that bound the solution space — API rate limits, existing data shape, performance budgets, legal/licensing, team capacity. Cite source where possible.

- **SoundCloud API:** already wired (`app/soundcloud_api.py`, OAuth client-credentials). Search endpoint exists, fuzzy matcher in `SoundCloudSyncEngine` (threshold 0.65). Rate-limit informal (~15k req/day per client_id from observation); back off on 429.
- **Beatport:** no public REST API for free use. Options: HTML scrape of `beatport.com/search?q=...` (fragile, ToS grey zone) or rely on user-provided links. Beatport's track JSON exposes `mix_name` field with values like "Extended Mix" / "Original Mix" / "Radio Edit" — the canonical taxonomy comes from here.
- **Bandcamp:** no official search API; `bandcamp.com/search?q=...` HTML scrape works but is rate-limited via Cloudflare. Often lossless WAV/FLAC available for purchase.
- **YouTube:** YouTube Data API v3 quota = 10k units/day default; `search.list` costs 100 units → ~100 searches/day per key. Insufficient for a 30k library scan; needs caching + on-demand triggers.
- **Discogs:** REST API, 60 req/min authenticated, free. Release tracklists expose duration + version labels reliably ("Extended Mix (7:32)" etc.). Good ground-truth source for "does an Extended exist at all?"
- **Library size:** target 5k–30k tracks. Linear scan even at 1 req/sec/source = hours per source. Must be incremental (delta scan since last run) and cache-heavy.
- **Title pattern ambiguity:** "Original Mix" on Beatport usually means "the canonical, un-remixed version" (often ~6–7 min, *is* the extended). On SoundCloud "Original Mix" frequently means the radio cut. Source-aware parsing required.
- **Duration heuristic bands:** radio ≤ 3:30, club 5:00–7:30, extended 5:30–9:00. Bands overlap — duration alone is never sufficient.
- **DB schema:** library tracks stored in Rekordbox `master.db` (read via `pyrekordbox`). All writes go through `app/main.py:_db_write_lock`. Candidate suggestions stay out of `master.db` — store in a sidecar SQLite (`extended_candidates.db`) so we don't pollute Rekordbox.
- **Existing engine:** `SoundCloudSyncEngine` (`app/soundcloud_api.py:550`) already does library-wide fuzzy matching against SC search results. Extending it for "find extended variants" is cheaper than a new engine.

## Open Questions

> Numbered. Each one should be resolvable (yes/no, or "X vs Y"), not open-ended philosophy.

1. **Which sources for v1?** SoundCloud-only (free, wired) vs SoundCloud + Discogs (free, adds ground-truth) vs all five. Recommendation: SC + Discogs for v1, Beatport/Bandcamp/YouTube as opt-in v2 plugins.
2. **Where do suggestions live?** Sidecar SQLite (`app/data/extended_candidates.db`) vs an in-memory cache vs a JSON-per-track file. Sidecar SQLite is the only one that survives restart and scales to 30k × N sources.
3. **What's the trigger model?** Continuous background scan on idle vs explicit user "Scan library for extended versions" button vs per-track "Find extended version" on right-click. Probably all three, but v1 = button + per-track.
4. **Confidence threshold to surface?** Show only `high` by default, `med` behind a toggle, `low` hidden? Or all bands with visual scoring?
5. **Caching TTL?** 30 days for negative results (no extended found), 90 days for positive matches, force re-scan never? Or weighted by source freshness (SC = 7d, Discogs = 180d, etc.)?
6. **De-dup across sources:** if the same Extended Mix appears on SC and Beatport, collapse into one candidate with multiple provenance links, or surface separately?
7. **What counts as "already in library"?** Currently-loaded `master.db` only, or also "in pending download queue from SC sync"? Need to avoid suggesting a track the user just queued.
8. **YouTube spam filter heuristic?** Block channels with `<X>` subs, block titles with "[FULL VERSION]" / "FREE DOWNLOAD" / "1 HOUR", block sped-up indicators ("nightcore", "+10%", "sped up")? Static deny-list vs ML classifier vs user-curated blocklist?
9. **Match key for "same track":** `(artist_normalised, title_stem_normalised)` where title-stem = title minus the parenthesised version tag? Or use ISRC where available (rare on SC, often on Beatport/Discogs)?
10. **UX surface:** new "Suggestions" tab vs inline badges on the track list vs a dedicated review modal? Affects implementation scope significantly.

## Findings / Investigation

> Required from `exploring_` onward. Append dated subsections as you learn. Never edit past entries — supersede with a new one.

### 2026-05-15 — initial audit

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

**Option B (Discogs-gated SoundCloud finder) for v1**, with Option C plugins (Beatport, Bandcamp, YouTube) deferred to v2 behind feature flags.

Rationale: Option A ships fastest but burns SC quota on tracks that have no Extended anywhere. Option B's Discogs gate is the cheapest win in precision-per-request — Discogs is free, canonical, and ~60 req/min is plenty for incremental scans. The plugin architecture pays dividends when v2 adds paid platforms.

**Milestone split (see Findings 2026-05-15 UX section):**
- **M1 = Option A surface + plugin-shaped backend.** SC-only path wrapped behind the Option-B plugin interface so Discogs slots in without UI rework. UX = badge + "Extended Audit" view. Scan is **explicit / opt-in only** (button or right-click); never auto at import.
- **M2 = Option B Discogs gate + medium-tier UX + right-click + Ranking sidebar.** Trigger model adds opt-in **idle delta-scan for newly-imported tracks** (last 24h, behind a setting).
- **M3 = Option C paid/spammy sources behind feature flags.** Only if M1+M2 metrics show recall gap.

Before promoting to `evaluated_` / `draftplan_`, resolve:
- Open question #1 (sources for v1) — likely "yes" to SC + Discogs (see Findings above: M1 = SC, M2 = +Discogs).
- Open question #2 (storage) — likely sidecar SQLite at `app/data/extended_candidates.db`.
- Open question #3 (trigger model) — see Findings above: M1 = explicit only, M2 = opt-in idle delta-scan, never auto-at-import.
- Open question #4 (confidence threshold UX) — see Findings above: high = badge, medium = Audit-view toggle, low = hidden behind toggle. Mockup still needed.
- Open question #6 (cross-source dedup) — see Findings above: collapse on `(artist, title_stem, duration_band)`, show source pills.
- Open question #8 (YouTube spam filter) — see Findings above: layered filter (verified-artist + chromaprint + popularity + keyword deny-list); not relevant until M3.
- Open question #10 (UX surface) — see Findings above: M1 badge + Audit view; sister doc `idea_analysis-remix-detector` surfaces in the same Audit view (rename to "Library Audit" if it covers multiple suggestion kinds). Coordinate the IA so all three sister features share one panel rather than three competing ones.

Cross-cutting with sister docs:
- `idea_analysis-remix-detector` shares the version-tag taxonomy + title-stem extractor — those should land in a shared `app/track_version_parser.py` module, not duplicated.
- `idea_library-quality-upgrade-finder` shares the candidate-storage schema (sidecar SQLite) and the Suggestions tab UX. Strongly consider unifying the sidecar DB as `app/data/track_suggestions.db` with a `kind` column (`extended` | `upgrade` | `remix`) rather than three databases.

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
