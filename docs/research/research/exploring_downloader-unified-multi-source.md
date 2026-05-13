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
- 2026-05-13 — `research/exploring_` — owner resolved Q1-Q14; 3 expanded goals added (auto-search, AIFF default, genre-sync); core algorithms sketched (D1-D8)

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
- **Auto-search mode** (Q1d resolved): when input is free-form `Artist – Title` instead of a URL, the system probes every source's *search* endpoint in parallel, optionally pivots via Songlink/Odesli for cross-platform URL resolution, and returns a candidate grid (one card per platform with platform-icon + claimed quality) for the user to pick from. Picked candidate then enters the same resolve→download pipeline.
- **AIFF-as-default output** (Q11 resolved): post-download lossless conversion to AIFF (uncompressed PCM, 16/24-bit native, ID3v2-tagged, CDJ-3000 native format). Source FLAC/ALAC/WAV → AIFF via FFmpeg `-c:a pcm_s16le|pcm_s24le -map_metadata 0`. MP3/AAC stay in their original lossy container (no fake-lossless re-encode). Bit depth + sample rate preserved from source.
- **Genre-sync against existing library** (Q11 expansion): incoming genre strings from Spotify / Tidal / Qobuz are normalised against the library's canonical genre set before write-back. Strategy: lowercase + dash-normalise + lookup-table + fuzzy-match (≥ 90%); novel genres surface a confirmation dialog rather than silently expanding the library.

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
- **Mutagen pin** ([mutagen.readthedocs.io](https://mutagen.readthedocs.io/)): cross-format tag-write library. Pin `mutagen==<latest>` in `requirements.txt`. Even though Q13 resolved to "COMMENT-field only", we still need a library that handles Vorbis Comments (FLAC), ID3v2 (MP3 / AIFF / WAV), and MP4 atoms (M4A/ALAC) uniformly. Mutagen is mature, pure-Python, zero native build deps.
- **FFmpeg AIFF conversion** (Q11): `ffmpeg -i <src> -c:a pcm_s16le -map_metadata 0 <dst>.aiff` for 16-bit sources, `pcm_s24le` for 24-bit. `-map_metadata 0` carries over the source's tags (artist/title/album/etc.) so the post-download tagger only adds our additions (provenance URLs, normalised genre, ISRC, cover-art if missing). Bit-depth detection via `ffprobe -show_streams` → `bits_per_raw_sample`.
- **Songlink/Odesli API** (Q1d): for cross-platform URL resolution from any input URL. Free tier, no auth, public endpoint (`https://api.song.link/v1-alpha.1/links?url=<encoded>`). Rate-limit unclear → bounded retry + cache (1-week TTL acceptable since URLs are stable).
- **Spotify search without OAuth** (open in `exploring_`): SpotiFLAC scrapes the Web Player without credentials. Investigate whether it exposes a usable `search()` entry point or whether we have to add Client-Credentials-Flow with `SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` in `.env` (matches existing `SOUNDCLOUD_CLIENT_ID` pattern). Either way, no user-OAuth — `non-goals` still hold.

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

### 2026-05-13 — Owner decisions (Q1-Q14 resolved)

Captured directly from owner response. Numbers match `## Open Questions` above.

| # | Topic | Chosen | Rationale (owner-paraphrased) |
|---|---|---|---|
| 1 | Input-format scope | **d** + free-form auto-search | Accept any platform URL; if no link, app searches everywhere and lets user pick from candidate grid with platform-icons + quality-badge |
| 2 | 100%-match definition | Title-variance-tolerant, duration strict | Title can vary (e.g. `Title - Artist` swap, remix tags, featurings); length must match. Algorithm designed below. |
| 3 | Quality-ranking tiebreak | **c** — biggest/best file wins | Best quality always wins (proxy via bit-depth + sample-rate + file-size) |
| 4 | Hi-res support | **c** — default keep best | Settings switch lets user opt-in to local downconversion; default = preserve source |
| 5 | Single-track vs. playlist | **b** — playlist-batch in MVP | Playlist support included in v1 |
| 6 | Source-folder layout | **b** — unified `MUSIC_DIR/<artist>/` + `source` column | Breaking change for existing SC users acknowledged; migration plan sketched below |
| 7 | Failure UX | **a** then **b** fallback | Closest candidates first; if literally none ≥ threshold, hard-fail with diagnostic |
| 8 | SpotiFLAC integration | **c** — `ProcessPoolExecutor(max_workers=1)` | Owner wants "im Core, aber isoliert" → import the Python module but run it in a worker process. Exactly the `SafeAnlzParser` pattern (`app/anlz_safe.py`). Explained in detail below. |
| 9 | ISRC dedup | **a** (chosen by me, owner "idk") | ISRC as 3rd dedup key alongside SC-track-id + SHA-256; low cost, high payoff. Will explicitly re-confirm at `evaluated_`. |
| 10 | Provider on/off | **c** — default on, one-time onboarding disclaimer | Legal acknowledgement happens in onboarding flow, not per-activation |
| 11 | Standard metadata + format | **a** + AIFF-as-default + genre-sync | Album-art/year/ISRC/genre all written; output container is AIFF (lossless PCM, CDJ-native); genres normalised against library |
| 12 | Concurrency budget | **d** + auto-detect default | Settings-configurable; first-run benchmark sets default based on CPU/RAM/network |
| 13a | Provenance write location | **c** — `COMMENT` field only | Single field, simple, no custom-tag schema |
| 13b | Comment format | URLs comma+space separated, plain text | `"https://qobuz.com/..., https://tidal.com/..., https://soundcloud.com/..."` |
| 13c | Picked-source marker | **Implicit by order** — first URL = downloaded, descending quality | No separate marker tag — leading URL is by definition the chosen source |
| 14 | Tagging library | **a** — pin `mutagen` (decided for owner — clarified) | Mutagen is the standard Python lib for writing the `COMMENT` field across FLAC/MP3/AIFF/M4A. Even with the simplified Q13 format we still need *some* lib — mutagen is the obvious pick. |

### 2026-05-13 — Designs derived from decisions

**(D1) Title-variance detection algorithm (Q2)**

Input: `(needle_title, needle_artist, needle_duration_s)` vs. each candidate `(candidate_title, candidate_artist, candidate_duration_s)`.

Match counts as **100%** iff:

1. **Duration gate**: `abs(needle_duration_s - candidate_duration_s) <= 2` — hard requirement (owner: "Die länge muss übereinstimmen").
2. **AND** at least one of the following identity tests on normalised strings yields equality:
   - `norm(title) == norm(title)` AND artist-set-overlap ≥ 1
   - `norm(title + " " + artist) == norm(candidate_title + " " + candidate_artist)`
   - `norm(artist + " " + title) == norm(candidate_artist + " " + candidate_title)`
   - **Full swap**: `norm(title) == norm(candidate_artist)` AND `norm(artist) == norm(candidate_title)` — catches Spotify-vs-SC platform inconsistencies (some SC uploaders put `Artist - Title` in the title field with no separate artist)
   - **Containment**: `norm(title)` contains all words of `norm(candidate_title)` (after remix-tag stripping) — catches `Title (Original Mix)` vs `Title` or `Title - Extended Mix` vs `Title (Extended)`
3. **OR**: Sørensen-Dice bigram-similarity of `norm(title + " " + artist)` vs. candidate's concatenation ≥ 0.92 (last-resort fuzzy fallback, gated by the duration check above)

Normalisation pipeline (idempotent, per string):

1. NFKD-normalise (decompose accented chars: `é → e`)
2. Lowercase
3. Strip remix/version tags via regex list — `(Original Mix)`, `[Extended Mix]`, `- Extended`, `(Radio Edit)`, `[Club Mix]`, `(Acoustic)`, `(Live)`, `- Remastered`, `(Remastered 20XX)`, `(<Year> Remaster)`, `[Bonus Track]` etc. Maintained list in `app/downloader/match_rules.py`.
4. Strip parenthetical featuring tags: `(feat. X)`, `[feat. Y]`, `ft. Z`, `featuring W`
5. Replace separators `-` / `–` / `—` / `/` / `_` / `|` with single space
6. Strip all non-alphanumeric except space and apostrophe
7. Collapse multiple whitespace
8. Strip leading/trailing whitespace

Artist normalisation additionally splits on `,` / `&` / `feat.` / `featuring` / `ft.` / `vs.` / `x` → set (order-independent). Set-overlap ≥ 1 is the artist test.

**Validation gate for `exploring_`**: hand-curate a 50-entry test set from owner's actual library — `(Spotify-URL, expected matching SC-URL or expected "no match")` pairs covering the edge cases above (title-artist swap, remix tags, featurings, accents, multi-artist tracks). Algorithm ships only when ≥ 95% precision / ≥ 90% recall on that set. Test file: `tests/test_unified_downloader_match.py`.

**(D2) Auto-search flow (Q1d)**

```
User input: "Avicii - Wake Me Up"
     │
     ▼
Parallel search probes (bounded concurrency, default 4):
  ├─ Spotify Web Player search (via SpotiFLAC, no OAuth if possible)
  ├─ SoundCloud V2 /search/tracks  (existing pipeline auth)
  └─ YouTube Music search (via SpotiFLAC, optional)
     │
     ▼
For each hit (cap N=5 per platform):
  ├─ Pivot via Songlink/Odesli → cross-platform URL set
  └─ Probe Tidal/Qobuz/Amazon via SpotiFLAC for quality + availability
     │
     ▼
Dedupe by ISRC where available, else by title-variance algorithm (D1)
     │
     ▼
UI renders: candidate-grid, one card per ISRC-cluster
  - Platform icons (Spotify, Tidal, Qobuz, Amazon, SC, Apple, YT)
  - Quality badge per platform (FLAC 24/96, FLAC 16/44, MP3 320, AAC 256, …)
  - "Best available" pre-highlighted (descending quality tier)
     │
     ▼
User clicks card → enters resolve→download pipeline with that ISRC-cluster as the 100%-match anchor; auto-picks the highest-quality URL in the cluster (Q3-c rule)
```

Open in `exploring_`: does SpotiFLAC expose a usable `search()` API, or do we have to add `spotipy` for Spotify-Search? Direct experiment needed.

**(D3) SpotiFLAC ProcessPoolExecutor isolation (Q8 explained)**

Owner picked "b or c, unsure" and asked for in-Core integration with isolation. **c** is exactly that.

| Property | b) Subprocess CLI | **c) ProcessPoolExecutor (max_workers=1)** | a) In-process threadpool |
|---|---|---|---|
| Integration | External binary call, no `pip install` of the lib | `pip install SpotiFLAC`, *import* the module in our Python | `pip install SpotiFLAC`, import in main process |
| Process isolation | yes (each call spawns a new OS process) | yes (1 worker process kept warm, killable) | **no** (lives in sidecar process) |
| Crash recovery | clean (subprocess died, main fine) | clean (PPE auto-restarts the worker on next submit) | **bad** (a panic in SpotiFLAC kills the entire FastAPI sidecar) |
| Latency per call | ~200-500 ms (process startup + Python import overhead) | ~5-20 ms (worker stays warm, just dispatch over IPC) | ~1 ms (in-thread) |
| Feels "in Core"? | external feel — "we shell out to a tool" | **yes — we import and call a Python function** | yes |

Option **c** mirrors `app/anlz_safe.py:SafeAnlzParser` which quarantines rbox 0.1.5/0.1.7 `unwrap()` panics. We have a battle-tested template + tests in the repo (`tests/test_anlz_safe.py`).

Concrete shape:

```python
# app/downloader/providers/spotiflac.py
from concurrent.futures import ProcessPoolExecutor
from anyio import to_thread

_EXECUTOR = ProcessPoolExecutor(max_workers=1)  # single warm worker

async def resolve(spotify_url: str) -> list[Candidate]:
    return await to_thread.run_sync(_blocking_resolve, spotify_url, _EXECUTOR)

def _blocking_resolve(url: str) -> list[Candidate]:
    from SpotiFLAC import SpotiFLAC  # imported INSIDE the worker
    # ... probe each service, collect candidates ...
```

**(D4) AIFF post-download pipeline (Q11)**

```
Source format → AIFF strategy:
  FLAC 16/44     → ffmpeg -c:a pcm_s16le → 16/44 AIFF
  FLAC 24/96     → ffmpeg -c:a pcm_s24le → 24/96 AIFF  (hi-res preserved)
  FLAC 24/192    → ffmpeg -c:a pcm_s24le → 24/192 AIFF (hi-res preserved)
  ALAC 16/44     → ffmpeg -c:a pcm_s16le → 16/44 AIFF
  ALAC 24/96     → ffmpeg -c:a pcm_s24le → 24/96 AIFF
  WAV            → ffmpeg -c:a pcm_s{16,24}le → AIFF (container swap only)
  MP3 320        → NO conversion, stays MP3 (no fake-lossless re-encode)
  AAC 256 (Amazon HD)  → NO conversion, stays M4A
  OGG/Opus       → NO conversion (lossy stays lossy)

All conversions: `-map_metadata 0` carries source tags through, then
mutagen overlays our additions (provenance URLs in COMMENT, normalised
genre, ISRC, cover-art if not already embedded).
```

Optional setting `downconvert_hi_res_to_16_44: bool` (default `false` per Q4-c) — when `true`, post-AIFF, run a second FFmpeg pass with `-ar 44100 -sample_fmt s16` to downconvert. Always lossy-from-lossless if enabled; user must opt in explicitly.

**(D5) Genre-sync against existing library (Q11 expansion)**

```
Canonical genre table in `app/downloader/genre_sync.py`, seeded on
first run from the library's existing distinct-genres-set.

For each incoming genre string from Spotify / Tidal / Qobuz / Amazon:
  1. Normalise (lowercase, replace _/- with space, collapse whitespace)
  2. Exact lookup in canonical table → use canonical form
  3. Else: fuzzy match (Sørensen-Dice ≥ 0.90) against canonical entries
  4. Else: NOVEL — surface to user with 3-button dialog:
       [Add as new canonical genre] [Map to existing → dropdown] [Skip]
  5. Persist the decision (DB table `genre_mappings`) so the next track
     with the same novel genre is auto-mapped without re-asking
```

Open in `exploring_`: is the canonical table Rekordbox-genre-list-aware? CDJ-3000 reads genres from PDB; if our canonical form drifts from Rekordbox's expected vocabulary, the genre column may render oddly on deck.

**(D6) Comment-field URL serialisation (Q13 final)**

```python
def serialise_provenance(candidates: list[Candidate], picked: Candidate) -> str:
    """
    Order: picked first (= highest quality by construction, Q3-c),
    then remaining candidates in descending quality order.
    No separator marker — the leading URL IS the chosen source (Q13c).
    """
    ranked = [picked] + sorted(
        (c for c in candidates if c is not picked),
        key=lambda c: c.quality_tier_int,  # lower tier int = higher quality
    )
    return ", ".join(c.url for c in ranked)


# Example COMMENT field value after writing:
#   "https://www.qobuz.com/track/123456789,
#    https://tidal.com/track/987654321,
#    https://open.spotify.com/track/abc,
#    https://soundcloud.com/artist/title"
# Reading: first URL = the one we downloaded from (Qobuz 24/96 FLAC,
#          beat Tidal 16/44 FLAC on bit-depth).


def read_provenance(comment_str: str) -> list[tuple[str, str, bool]]:
    """Return list of (platform, url, was_picked). First entry has was_picked=True."""
    urls = [u.strip() for u in comment_str.split(",") if u.strip().startswith("http")]
    return [(_infer_platform(u), u, i == 0) for i, u in enumerate(urls)]
```

**(D7) Folder-migration plan (Q6 = unified layout)**

```
Migration on first launch after this feature ships:
  1. Scan existing `MUSIC_DIR/SoundCloud/<artist>/...` files
  2. Move each to `MUSIC_DIR/<artist>/...` (unified layout)
  3. Update DB rows with new path
  4. Update `source` column → 'soundcloud' for existing SC tracks
  5. Idempotent (re-runs safely — checks DB current_path before each move)

Rollback: settings flag `legacy_per_source_folders: bool` (default false
post-migration). When true, all NEW downloads use per-source folders
again. Migration is not reverted; the flag only affects new tracks.
```

**(D8) Concurrency auto-detection (Q12-d)**

```
First-run benchmark in `app/downloader/concurrency.py`:
  1. Probe SoundCloud V2 `/search/tracks?q=test&limit=1` 4× in parallel
     and 4× sequentially; measure wall-time of each batch
  2. Compute parallel-speedup ratio
  3. If speedup > 3.0× → recommended_concurrency = 8
     If speedup > 2.0× → recommended_concurrency = 6
     If speedup > 1.5× → recommended_concurrency = 4
     Else → recommended_concurrency = 2 (network-bound or rate-limited)
  4. Persist to `settings.json` as `unified_downloader.max_concurrency`
  5. User can override in Settings UI

Re-runs: settings UI has a "Re-benchmark" button. Auto-rerun after
ISP/network change is out of scope for v1.
```

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

> Required by `evaluated_`. Owner decisions Q1-Q14 captured 2026-05-13.

**Architecture**: Option B (Resolver / Downloader split, two-phase). Phase 1 — `Resolver.probe(identifier_or_query)` — runs in parallel across all enabled providers, returns `Candidate[]` with claimed quality + platform + URL + match-score. Phase 2 — `Downloader.fetch(candidate) → Path` — actually pulls bytes for the user-picked or auto-picked best candidate. Two-phase is *required* by the auto-search mode (Q1-d): the UI needs the candidate grid *before* committing a download.

**Isolation**: SpotiFLAC runs inside a `ProcessPoolExecutor(max_workers=1)` worker pool (the `SafeAnlzParser` pattern — see `app/anlz_safe.py`). Imported as a Python module ("in Core"), but called in a worker process that the orchestrator can kill+restart on panic. Hits the owner's Q8 constraint exactly.

**Post-download pipeline** per track:

1. Fetch bytes → temp file under `MUSIC_DIR/.staging/`
2. SHA-256 → dedup check (existing utility)
3. AIFF-conversion via FFmpeg if source is lossless and not already AIFF (D4)
4. Genre-normalise incoming genre strings against library canonical table (D5)
5. Write provenance URLs into the `COMMENT` field via mutagen, comma+space-separated, ordered descending by quality — first URL = the one we downloaded from (D6, implicit picked-source marker)
6. Write all incoming standard metadata (year, ISRC, album-art, normalised genre, etc.) via mutagen
7. Move to final `MUSIC_DIR/<artist>/<title>.aiff` location (Q6: unified layout, D7)
8. Registry update with `isrc`, `source`, `provenance_urls` (JSON), `picked_quality_tier`
9. Background: BPM/key analysis (existing utility)

**Failure-UX** (Q7-a→b): no 100%-match → surface closest candidates (≥ 85% Sørensen-Dice threshold) with explicit confirm; if no candidate ≥ threshold, hard-fail with diagnostic ("tried 6 sources, closest match was 71% on Spotify — review your input").

Confirm in `exploring_` (open):

- D1 — title-variance-detection algorithm precision/recall on a hand-curated 50-entry test set from owner's actual library (gate: ≥ 95% precision / ≥ 90% recall)
- D2 — Spotify search API path: does SpotiFLAC expose `search()`, or do we need `spotipy` + `SPOTIFY_CLIENT_ID/_SECRET` in `.env`?
- D3 — SpotiFLAC-in-PPE feasibility: does the module survive being called over the IPC boundary? Test by importing and invoking inside a `ProcessPoolExecutor` with a sample URL
- Q9 — ISRC backfill from SoundCloud (does the SC V2 API expose ISRC on the `/tracks/{id}` endpoint?)
- D8 — concurrency auto-detection: which baseline (the SC `/search` endpoint? a known-cached public URL?) yields a reproducible benchmark
- D5 — Rekordbox genre vocabulary alignment: should our canonical table mirror RB's expected genre strings, or is "whatever the user has" the right canonical?

---

## Implementation Plan

> Required from `implement/draftplan_` onward. Not filled at `idea_` stage.

### Scope
- **In**: …
- **Out (deliberately)**: …

### Step-by-step
1. …

### Files touched (expected)
- `app/downloader/__init__.py` (new) — orchestrator + `SourceProvider` ABC + `Candidate` dataclass
- `app/downloader/resolver.py` (new) — phase-1 parallel probe across providers, returns `Candidate[]`
- `app/downloader/search.py` (new) — phase-1 search mode for free-form input, cross-platform expansion via Songlink/Odesli
- `app/downloader/providers/soundcloud.py` (new) — wrap existing `soundcloud_downloader.py` (URL-resolve + V2 `/search/tracks`)
- `app/downloader/providers/spotiflac.py` (new) — wrap SpotiFLAC inside `ProcessPoolExecutor(max_workers=1)` worker (D3)
- `app/downloader/providers/songlink.py` (new) — Songlink/Odesli API client for cross-platform URL expansion
- `app/downloader/quality.py` (new) — quality-ranking (5 tiers, see Findings) + best-quality picker (file-size + bit-depth + sample-rate)
- `app/downloader/match.py` (new) — title-variance match algorithm (D1, hard duration gate + normalisation pipeline)
- `app/downloader/match_rules.py` (new) — maintained regex list of remix/version/featuring tags for normalisation
- `app/downloader/tagging.py` (new) — `COMMENT`-field provenance write + standard-metadata write via mutagen (per-format dispatch)
- `app/downloader/aiff.py` (new) — FFmpeg AIFF conversion (preserve bit-depth + sample-rate, `-map_metadata 0`)
- `app/downloader/genre_sync.py` (new) — incoming-genre → library-canonical normaliser (lookup-table + fuzzy ≥ 90% + confirm-on-novelty)
- `app/downloader/concurrency.py` (new) — first-run benchmark (D8) → settings recommendation
- `app/downloader/migration.py` (new) — first-launch `MUSIC_DIR/SoundCloud/<artist>/` → `MUSIC_DIR/<artist>/` migration (D7)
- `app/main.py` — new routes: `POST /api/downloads/unified/resolve`, `POST /api/downloads/unified/search`, `POST /api/downloads/unified/fetch`, all behind `X-Session-Token`
- `app/download_registry.py` — add columns: `isrc TEXT`, `source TEXT`, `provenance_urls TEXT` (JSON), `picked_quality_tier INTEGER`
- `requirements.txt` — pin `SpotiFLAC==<v>` + `mutagen==<v>` + (if Spotify-search needs OAuth) `spotipy==<v>`
- `.env.example` — optional `SPOTIFY_CLIENT_ID` + `SPOTIFY_CLIENT_SECRET` (only if D2-investigation shows OAuth required for search)
- `frontend/src/components/Download/*` — new UI: search-bar input mode, candidate-grid view with platform-icons + quality-badges, picked-source highlight, novel-genre confirmation dialog
- `tests/test_unified_downloader_match.py` (new) — 50-entry test set for D1 algorithm
- `tests/test_unified_downloader_quality.py` (new) — quality-ranker fixtures
- `tests/test_unified_downloader_e2e.py` (new) — end-to-end fixtures (mocked providers)
- `docs/architecture.md`, `docs/FILE_MAP.md`, `docs/backend-index.md`, `docs/frontend-index.md`, `CHANGELOG.md` — update at graduation

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
