---
slug: downloader-unified-multi-source
title: Unified multi-source downloader — best-quality auto-pick across Spotify (via SpotiFLAC), Tidal, Qobuz, Amazon, SoundCloud
owner: unassigned
created: 2026-05-13
last_updated: 2026-05-13
tags: [downloader, soundcloud, spotify, tidal, qobuz, amazon, flac, schicht-a]
related: []
---

# Unified multi-source downloader — best-quality auto-pick across Spotify (via SpotiFLAC), Tidal, Qobuz, Amazon, SoundCloud

> **State**: derived from filename + folder. Do not store state in frontmatter.
> Start the file as `docs/research/research/idea_<slug>.md`. Rename + move on each transition (see `../README.md`).

## Lifecycle

> Append-only audit trail. One line per `git mv`. Newest at the bottom.

- 2026-05-13 — `research/idea_` — created (request: combine Spotify-FLAC download via SpotiFLAC with existing SoundCloud pipeline; auto-pick highest quality on 100% match)

---

## Problem

Today the project can only download from SoundCloud (`app/soundcloud_downloader.py`). Users who think in Spotify links — or who want lossless when it exists — have no path. We want **one entry point**: paste any track identifier (Spotify URL, SoundCloud URL, Tidal/Qobuz/Amazon/Apple Music URL, or free-form `Artist – Title`), the system probes every source we support, filters to **100%-match candidates**, ranks them by **audio quality**, and downloads the best one. The downloader becomes source-agnostic; the user just gets the highest-fidelity file the network can offer for that exact track.

## Goals / Non-goals

**Goals**
- Single-entry-point API: `request_track(identifier_or_url) → best_quality_candidate → download`.
- Multi-source resolution **in parallel** (don't wait for source A before trying source B).
- **100%-match gate** — only candidates that match the requested track are kept. Quality ranking happens *only* among 100%-matches; we never trade match-accuracy for quality.
- **Deterministic quality ranker** with documented order (e.g. FLAC > ALAC > WAV > 320 kbps MP3 > 256 kbps AAC > 128 kbps MP3, source-tagged on ties).
- Integrate SpotiFLAC ([github.com/spotbye/SpotiFLAC](https://github.com/spotbye/SpotiFLAC), Python module: `pip install SpotiFLAC`) as the bridge to Tidal/Qobuz/Amazon/Apple-Music.
- Keep the existing SoundCloud pipeline (`app/soundcloud_api.py` + `app/soundcloud_downloader.py`) as one provider among many — its `LEGAL BOUNDARIES` semantics (no `snipped:true`, respect 401/403, no DRM bypass) stay intact.
- Two-layer dedup (track-ID + content hash) must continue to work across sources.
- BPM/key analysis + library auto-import flow stays the same regardless of source.
- Surface per-candidate metadata to the UI before commit: which source, what quality, what file size, what licensing — let user override the auto-pick.
- **Provenance write-back**: every source URL we resolved for this track (whether downloaded from or not) lands in the downloaded file's metadata — so later inspection of the file alone (in Rekordbox, on a CDJ display, via `ffprobe`, in our own UI) shows the full cross-reference set: "this track also exists on Spotify here, on Tidal here, on SoundCloud here". Includes the **picked** source plus all **rejected-but-matched** sources.

**Non-goals** (deliberately out of scope)
- Re-implementing Spotify/Tidal/Qobuz/Amazon clients ourselves. SpotiFLAC's reverse-engineered Web Player + third-party APIs (hifi-api, dabmusic.xyz, musicdl.me) are the sole bridge.
- Spotify OAuth / user account login. We use **public Web Player metadata only** (no token, no playlist read for private playlists in v1).
- Apple-Music ALAC unless it falls out of SpotiFLAC for free. The README claims support; if the integration is fragile we defer.
- DRM bypass beyond what SpotiFLAC's upstream APIs already perform — we are a client of their pipeline, we don't extend it.
- Lyrics / LRC sync (separate research topic if wanted).
- Playlist-level imports as the *primary* path in v1 — single-track resolution first, batch comes later.

## Constraints

> External facts that bound the solution space.

- **Schicht-A pinning** ([SECURITY.md](../../SECURITY.md), [coding-rules.md](../../../.claude/rules/coding-rules.md)): `SpotiFLAC==X.Y.Z` in `requirements.txt` — no `>=`. Lock both SpotiFLAC and its transitive deps. Verify CVE notes before any bump.
- **Concurrency**: every DB write through `master.db` must acquire `app/main.py:_db_write_lock` (RLock). The `download_registry` is already on it via the SC path — new sources must use the same registry, not a parallel table.
- **Filesystem sandbox**: downloads land under `MUSIC_DIR` only. Path validation goes through `validate_audio_path` so symlink-escape tricks fail. New per-source subfolders (`MUSIC_DIR/Spotify/`, `MUSIC_DIR/Tidal/`, …) follow the existing `MUSIC_DIR/SoundCloud/<artist>/<title>.<ext>` convention.
- **FFmpeg in PATH**: required for HLS remux on SC and for any Tidal/Qobuz container conversion if SpotiFLAC delegates.
- **`X-Session-Token` gate**: any new `/api/spotify/...` or `/api/downloads/unified/...` route writing the DB must follow the same token policy as existing `system_*` endpoints.
- **No `requests.get()` in async path**: any new orchestration in FastAPI handlers uses `httpx.AsyncClient` (see `coding-rules.md`). SpotiFLAC itself is sync — wrap it in `run_in_threadpool` or a `ProcessPoolExecutor` (parallel to the `SafeAnlzParser` pattern in `app/anlz_safe.py`).
- **SpotiFLAC stability**: third-party API endpoints can disappear (DMCA, rate limits, IP bans). The README explicitly warns "metadata fetching can fail due to IP rate-limits → VPN suggested". We must surface failures cleanly, never silently produce a low-quality fallback when the user asked for FLAC.
- **Legal posture shift**: today's `soundcloud_downloader.py` has a 20-line `LEGAL BOUNDARIES` block that documents a careful ToS-mindful posture (no `snipped:true`, no `hq` probing beyond paid tier, no re-encode). SpotiFLAC's upstream APIs pull lossless audio from paid streaming services without per-user subscription verification. **This is a different category and must be acknowledged as accepted risk in the implementation doc, not silently absorbed.**
- **UPX / antivirus**: SpotiFLAC's standalone binaries are UPX-compressed and frequently flagged. We use the **Python module** (no UPX), not the bundled binary — sidesteps the AV noise but we should still document the risk.

## Open Questions

> Each one should be resolvable. Numbered for cross-referencing.

1. **Input-format scope for v1**: do we accept *only* Spotify URLs + SoundCloud URLs as input, or also Tidal/Qobuz/Amazon/Apple/YouTube URLs (SpotiFLAC supports them) and free-form `Artist – Title` strings? My recommendation: Spotify + SoundCloud + free-form. Tidal/Qobuz direct URLs are niche for a DJ user.
2. **100%-match definition**: ISRC equality wins (when both sides expose it). Without ISRC, what's the fallback rule? Proposal: normalized `title` (lowercase, strip `(Original Mix)` / `[Extended]` / parenthetical remix tags optionally, NFKD-normalize) + normalized `artist` (split on `,` / `&` / `feat.`, set-equality) + duration within ±2 seconds. Tighter / looser?
3. **Quality ranking ties**: when Tidal-FLAC and Qobuz-FLAC are both 100%-match and both 16/44.1, which wins? Proposal: prefer the source that returns first (latency tiebreak) and log the loser. Alternative: deterministic source priority list in settings.
4. **Hi-res support**: if Qobuz returns 24/96 FLAC, do we keep it (CDJ-3000 supports up to 24/96 WAV via USB export)? Proposal: yes, mark in metadata; let user opt out via setting.
5. **Single-track vs. playlist in v1**: stay single-track only (clean MVP), or include playlist-level batch with the same per-track resolution loop? Proposal: single-track first; playlist comes as a follow-up in `inprogress_` if v1 ships clean.
6. **Source-folder layout**: do we keep `MUSIC_DIR/SoundCloud/<artist>/...` and add `MUSIC_DIR/Spotify/<artist>/...` etc., or unify everything under `MUSIC_DIR/<artist>/...` with a `source` column in the registry? The latter is cleaner but breaks existing folder layouts users may rely on.
7. **Failure UX**: if no source returns a 100%-match, what does the UI show? Proposal: surface the *closest* candidates (e.g. 92% match) with explicit "this is not exact, accept?" button — never auto-download a near-match.
8. **SpotiFLAC integration shape**: subprocess-launch the CLI vs. import the Python module in-process. Proposal: in-process via `pip install SpotiFLAC` + `run_in_threadpool`. Subprocess only if the module destabilises the sidecar.
9. **Dedup across sources**: a track imported via Spotify-then-Tidal-FLAC and later requested via SoundCloud should match the existing file. Two-layer dedup needs an ISRC layer added (today it's `sc_track_id` + content-SHA-256). Proposal: add `isrc` as a third dedup key; backfill SC tracks via API where available.
10. **Provider on/off in settings**: SpotiFLAC as a feature-flag, default off, gated by explicit user opt-in with disclaimer? Recommended yes (legal-posture acknowledgement happens once at first activation).
11. **Tagging / metadata write-back**: when we get the Spotify-side metadata (album art, year, ISRC, genre), do we write it into the FLAC tags or rely on our own DB? Proposal: write standard Vorbis comments + cover-art block into the downloaded file (FLAC native), keep DB as source of truth for relational queries.
12. **Concurrency budget**: how many sources do we probe in parallel per request? Each source = N HTTP requests + possible API key resolution. Proposal: bounded parallelism (4 sources, each with internal sequential retries).
13. **Provenance-URLs: which tag(s)?**: container-specific decision. FLAC/OGG (Vorbis Comments) supports multi-value keys — natural fit. ID3v2 (MP3) needs either repeated `COMM` frames with distinct `desc`/`lang` or a dedicated `TXXX:SOURCES`. MP4/M4A (Apple Lossless / Amazon HD AAC) uses iTunes-style atoms (`----:com.apple.iTunes:SOURCES`). Three sub-questions:
    - a) **Comment field vs. custom tag**: write into the standard `COMMENT` field (visible on CDJ-3000 "Comment" display, but display is short and may truncate), or use a dedicated custom tag (`SOURCES` / `TXXX:SOURCES`) that's invisible on the CDJ but visible to Rekordbox + our app? Proposal: **both** — short summary (e.g. `"sources: spotify, tidal, soundcloud"`) into `COMMENT` so it's CDJ-visible, full URL set into the custom tag.
    - b) **Format of the custom tag**: single JSON blob (`{"spotify":"https://...","tidal":"https://...","soundcloud":"https://..."}`), or one tag per source (`SPOTIFY_URL=...`, `TIDAL_URL=...`, …), or multi-value `SOURCE=spotify|https://...` lines? Trade-off: JSON is compact + extensible but Rekordbox won't parse it; per-source tags read cleanly in `kid3` / `mp3tag` / `ffprobe`. Proposal: per-source tags (`SPOTIFY_URL`, `TIDAL_URL`, `QOBUZ_URL`, `AMAZON_URL`, `SOUNDCLOUD_URL`, `APPLEMUSIC_URL`, `YOUTUBE_URL`).
    - c) **Picked-source marker**: how do we mark which source we actually downloaded from vs. ones that matched but weren't picked? Proposal: separate `DOWNLOADED_FROM=<source-key>` tag pointing at one of the URL keys above.
14. **Tagging library**: [`mutagen`](https://mutagen.readthedocs.io/) is the canonical Python lib for cross-format audio tagging (handles Vorbis Comments, ID3v2, MP4 atoms, ASF, etc.) — already widely used and pinnable. Confirm: pin `mutagen==<latest>` and route all writes through it? Alternative is per-format libs (`flacstream`, `eyed3`, `mutagen.mp4`) which is more code for no gain.

## Findings / Investigation

> Required from `exploring_` onward. Append dated subsections as you learn.

### 2026-05-13 — initial scan of SpotiFLAC + existing SC pipeline

**SpotiFLAC reality check** ([github.com/spotbye/SpotiFLAC](https://github.com/spotbye/SpotiFLAC), v7.1.6 released 2026-04-26, MIT, ~8.4k stars):
- Spotify URL → metadata via reverse-engineered Web Player (no login, no token).
- Audio bytes come from **Tidal / Qobuz / Amazon Music** via third-party APIs ([hifi-api](https://github.com/binimum/hifi-api), dabmusic.xyz, musicdl.me).
- Apple Music / SoundCloud / YouTube also supported (Apple as M4A/ALAC, SC/YT as MP3).
- Python module on PyPI: `pip install SpotiFLAC` ([PyPI](https://pypi.org/project/SpotiFLAC/), repo: [ShuShuzinhuu/SpotiFLAC-Module-Version](https://github.com/ShuShuzinhuu/SpotiFLAC-Module-Version)).
- API surface:
  ```python
  from SpotiFLAC import SpotiFLAC
  SpotiFLAC(
      url="https://open.spotify.com/track/...",
      output_dir="./out",
      services=["qobuz", "amazon", "tidal", "spoti"],
      filename_format="{year} - {album}/{track}. {title}",
      use_artist_subfolders=True,
      use_album_subfolders=True,
      loop=60,  # retry duration in minutes
  )
  ```
- The `services=[...]` parameter is the prioritised fallback list — first match wins inside SpotiFLAC. For our use case we want to flip this: enumerate *all* services and pick by quality, not by first-match.

**Open question that arose**: does SpotiFLAC expose a "list candidates" / "dry-run" mode? Or do we have to call it once per service and aggregate ourselves? Investigation needed in `exploring_` phase.

**Existing SC pipeline** ([app/soundcloud_downloader.py](../../../app/soundcloud_downloader.py)):
- Two acquisition paths: official `/tracks/{id}/download` (when `downloadable:true`) → original WAV/FLAC/MP3; otherwise `transcodings[]` from v2 API → progressive MP3 / HLS-AAC remuxed.
- Two-layer dedup: SC-track-ID (O(1) SQLite) + SHA-256 (post-download).
- File layout: `MUSIC_DIR/SoundCloud/<artist>/<title>.<ext>` (collision suffix `(1)`, `(2)`, …).
- Path-length-safe truncation (Windows MAX_PATH 260, target ≤ 250 to leave room for `.part` suffix).
- Sanitiser handles Windows reserved device names (`CON`, `PRN`, etc.) — prefixes with `_`.
- Post-download pipeline: SHA-256 dedup → registry update → background BPM/key analysis → background library auto-import + SC playlist auto-sort.

**Implication for the unified design**: the SC code already has a lot of the boring pieces (sanitisation, path-truncation, dedup, registry, background analysis hook). The unified downloader should keep these as utilities and only swap out the *acquisition step* per source.

**Quality ranking — initial proposal**:

| Tier | Sources | Quality |
|---|---|---|
| 0 (Lossless hi-res) | Qobuz (24/96+ FLAC), Tidal (MQA / HiRes FLAC) | 24-bit, > 44.1 kHz |
| 1 (Lossless CD) | Tidal FLAC, Qobuz FLAC, SC `downloadable:true` returning FLAC/WAV | 16/44.1 |
| 2 (Lossy hi-quality) | Amazon HD (256 kbps AAC), SC `downloadable:true` MP3 320, SC Go+ HLS (256 AAC) | 256+ kbps lossy |
| 3 (Lossy standard) | SC progressive MP3 128, Spotify-OGG 320 (if ever exposed) | 128-320 kbps lossy |
| 4 (Last resort) | YouTube MP3 (via SpotiFLAC) | source quality varies |

Within a tier, source-priority is a settings concern (open question 3).

**Risk acknowledgement** (must surface in `evaluated_` / `accepted_`):
- Current `soundcloud_downloader.py` has a written `LEGAL BOUNDARIES` block. Adding SpotiFLAC moves the project from "user accesses what they have rights to on SC" to "user receives lossless audio from paid streaming services they may not subscribe to". This is **the user's call to make**, but the doc must record the decision explicitly — not slip it in via feature-creep.

**Tagging — per-container reality** (re Q13):

| Container | Standard tag system | Multi-value support | "Comment" field name | Custom-tag idiom |
|---|---|---|---|---|
| FLAC | Vorbis Comments | yes (repeat key) | `COMMENT` | uppercase free-form (`SPOTIFY_URL=...`) |
| OGG / Opus | Vorbis Comments | yes | `COMMENT` | same as FLAC |
| MP3 | ID3v2.3 / v2.4 | per-frame (`COMM` w/ `desc`+`lang`, or `TXXX` w/ key) | `COMM` frame | `TXXX:SPOTIFY_URL` (User-defined text frame) |
| M4A / ALAC | MP4 atoms | yes (multi-value atoms) | `©cmt` | `----:com.apple.iTunes:SPOTIFY_URL` (reverse-DNS atom) |
| WAV | ID3v2 chunk or LIST/INFO | partial | `ICMT` (LIST/INFO) or ID3 `COMM` | ID3v2 path recommended for parity with MP3 |
| AIFF | ID3v2 chunk | same as MP3 | `COMM` | `TXXX:SPOTIFY_URL` |

[`mutagen`](https://mutagen.readthedocs.io/) abstracts all six. One write-back module (`app/downloader/tagging.py`) implements `write_provenance(file_path, urls_dict, picked_source)` and dispatches by extension.

**CDJ-3000 visibility note**: the CDJ reads Rekordbox-exported PDB metadata, not the raw file tags directly. So our PDB writer (`app/usb_pdb.py`) needs to know about the `COMMENT` content too if we want it on the CDJ display — separate sub-task. The raw file tags help in Rekordbox-on-desktop and in our own UI immediately, regardless.

## Options Considered

> Required by `evaluated_`. Sketched now as starting points; deepen in `exploring_`.

### Option A — Strategy pattern, one `SourceProvider` interface, parallel probe + merge

- **Sketch**: define `SourceProvider` ABC with `resolve(identifier) -> list[Candidate]` and `download(candidate) -> Path`. Implement `SoundCloudProvider` (wrap existing code), `SpotiFLACProvider` (per service: Tidal, Qobuz, Amazon — possibly one provider per service if SpotiFLAC exposes them granularly). Orchestrator calls `resolve` on all enabled providers in parallel, filters to 100%-match, ranks, calls `download` on the winner.
- **Pros**: clean separation, each provider testable in isolation, easy to add new sources later, mirrors the `SafeAnlzParser`-style isolation pattern.
- **Cons**: SpotiFLAC's API is opinionated (it picks the service internally based on `services=[...]` order); forcing per-service granularity may mean monkey-patching or N calls per request (wasteful).
- **Effort**: M
- **Risk**: medium — depends on whether SpotiFLAC exposes per-service probing.

### Option B — Resolver / Downloader split (two-phase)

- **Sketch**: phase 1 *resolution* gathers metadata + candidate descriptors (URL, service, claimed quality, claimed format) from every source — *no audio bytes downloaded yet*. Phase 2 *download* picks the winning candidate and fetches just that one. UI can sit between the two phases to show the user candidates before commit.
- **Pros**: dry-run mode is free, UI override is natural, network cost is bounded (we don't download N files and discard N-1), audit log is clean.
- **Cons**: phase 1 may not be cheap — for SpotiFLAC, "what would you give me for this URL" might require executing the whole download path; we can't always know quality without fetching. Requires investigation per service.
- **Effort**: M-L
- **Risk**: medium — feasibility depends on whether each source has a metadata/probe endpoint distinct from the audio endpoint.

### Option C — Naive fallback chain (no parallel probe)

- **Sketch**: settings define ordered `[qobuz, tidal, amazon, soundcloud-official, soundcloud-stream, youtube]`. Try in order; first 100%-match wins; download immediately.
- **Pros**: simplest, smallest diff, no concurrency to debug, matches SpotiFLAC's native model.
- **Cons**: deterministic but **not best-quality** — if user puts Qobuz first and Qobuz returns 16/44.1 while Tidal would have had 24/96, we miss it. Defeats the "best quality" requirement.
- **Effort**: S
- **Risk**: low; but fails the headline goal.

## Recommendation

> Required by `evaluated_`. Filled later — pending answers to Open Questions 1, 8, 12 at minimum.

Working hypothesis: **Option B (Resolver / Downloader split) with parallel probe, falling back to Option A's interface internally**. Two-phase gives us the dry-run + UI override "for free" and matches the headline goal cleanly. Confirm in `exploring_` once we know whether each source supports cheap metadata-only probing.

---

## Implementation Plan

> Required from `implement/draftplan_` onward. Not filled at `idea_` stage.

### Scope
- **In**: …
- **Out (deliberately)**: …

### Step-by-step
1. …

### Files touched (expected)
- `app/downloader/__init__.py` (new) — orchestrator + `SourceProvider` ABC
- `app/downloader/providers/soundcloud.py` (new) — wrap existing `soundcloud_downloader.py` logic
- `app/downloader/providers/spotiflac.py` (new) — wrap SpotiFLAC module
- `app/downloader/quality.py` (new) — quality-ranking + 100%-match logic
- `app/downloader/tagging.py` (new) — provenance-URL write-back via mutagen (cross-format dispatch)
- `app/main.py` — new routes (`/api/downloads/unified/*`)
- `app/download_registry.py` — add `isrc` column + `source` column + `provenance_urls` JSON column
- `requirements.txt` — pin `SpotiFLAC==<version>` + `mutagen==<version>`
- `frontend/src/components/Download*` — new UI entry point + candidate-list view
- `docs/architecture.md`, `docs/FILE_MAP.md`, `docs/backend-index.md`, `docs/frontend-index.md` — update at graduation

### Testing approach
- …

### Risks & rollback
- …

## Review

> Filled by reviewer at `review_`.

- [ ] Plan addresses all goals
- [ ] Open questions answered or explicitly deferred
- [ ] Risk mitigations defined
- [ ] Rollback path clear
- [ ] Affected docs identified (`architecture.md`, `FILE_MAP.md`, indexes, `CHANGELOG.md`)
- [ ] **Legal-posture shift acknowledged and accepted by owner** (this doc, specifically — SpotiFLAC moves us from ToS-mindful SC posture to paid-streaming-rip)

**Rework reasons** (only if applicable):
- …

## Implementation Log

> Filled during `inprogress_`.

---

## Decision / Outcome

> Required by `archived/*`.

**Result**: `implemented` | `superseded` | `abandoned`
**Why**: …
**Rejected alternatives**:
- …

**Code references**: PR #…, commits …, files …

**Docs updated** (required for `implemented_` graduation):
- [ ] `docs/architecture.md`
- [ ] `docs/FILE_MAP.md`
- [ ] `docs/backend-index.md`
- [ ] `docs/frontend-index.md`
- [ ] `CHANGELOG.md`

## Links

- Code (existing): [`app/soundcloud_api.py`](../../../app/soundcloud_api.py), [`app/soundcloud_downloader.py`](../../../app/soundcloud_downloader.py), [`app/download_registry.py`](../../../app/download_registry.py)
- External: [SpotiFLAC repo](https://github.com/spotbye/SpotiFLAC), [SpotiFLAC Python module](https://github.com/ShuShuzinhuu/SpotiFLAC-Module-Version), [PyPI](https://pypi.org/project/SpotiFLAC/)
- Upstream APIs (transitive via SpotiFLAC): [hifi-api](https://github.com/binimum/hifi-api), [dabmusic.xyz](https://dabmusic.xyz), [musicdl.me](https://musicdl.me), [MusicBrainz](https://musicbrainz.org), [LRCLIB](https://lrclib.net), [Songlink/Odesli](https://song.link)
- Related research: _(none yet)_
