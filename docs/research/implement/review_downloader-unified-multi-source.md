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
- 2026-05-13 — content update — Claude resolved D2/D5/D8/Q9 + version pins (SpotiFLAC==0.5.0, mutagen already 1.47.0). Discovered reuse: `app/audio_tags.py` covers tagging, SpotiFLAC's `LinkResolver` covers Songlink, `SpotifyMetadataClient` covers search-without-OAuth. Scope shrunk: dropped 2 planned new modules (tagging.py, songlink.py).
- 2026-05-13 — `research/evaluated_` — exploring round 1 complete; consolidated Risks R1-R7 with impact × probability ratings + mitigations; ready for `draftplan_` (signoff-gated).
- 2026-05-13 — `implement/draftplan_` — Implementation Plan filled: Scope (in/out), 7-phase step-by-step (22 steps), testing approach, implementation-specific rollback. Cross-stage move research/ → implement/.
- 2026-05-13 — content update — Plan-agent pre-review at `draftplan_` stage: 6 factual repo-errors corrected in-place (`_db_write_lock` location, `X-Session-Token` nonexistence, `audio_tags` ISRC write-gap, `anlz_safe` pattern mis-copy, `_convert_to_aiff` overlap + 24-bit downgrade bug, `httpx`/`tenacity` pin). 2 new owner decisions raised (OQ-A route auth, OQ-B D3 timing). Doc stays in `draftplan_` until both answered.
- 2026-05-13 — `implement/review_` — owner answered all 3 sign-off-blocking decisions: OQ-A (no route gate; gap logged as `idea_api-route-auth-model`), OQ-B (D3 ran → PASS), legal-posture (two-mode: ToS-friendly default + opt-in Settings "backdoor" toggle). Review checklist fully ticked. Plan ready for `accepted_` — awaiting explicit owner sign-off.

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
- **Concurrency** (CORRECTED 2026-05-13 pre-review): the lock is `app/database.py:22` `_db_write_lock` (RLock), exposed via the `db_lock()` context manager at `database.py:26` — **not** in `app/main.py`. It serialises mutations on the **Rekordbox `master.db` / XML singleton only**. The `download_registry` is a **separate SQLite file** (`MUSIC_DIR/download_registry.db`, `download_registry.py:38`) with its own per-call WAL-mode connection — it does **not** use `_db_write_lock` and must not. The real lock concern for this feature: the post-download pipeline's writes into `master.db` (library auto-import, genre-sync canonical table if stored there) must go through `db_lock()`. Registry writes do not.
- **Filesystem sandbox**: downloads land under `MUSIC_DIR` only. Path validation goes through `validate_audio_path` so symlink-escape tricks fail. New per-source subfolders (`MUSIC_DIR/Spotify/`, `MUSIC_DIR/Tidal/`, …) follow the existing `MUSIC_DIR/SoundCloud/<artist>/<title>.<ext>` convention.
- **FFmpeg in PATH**: required for HLS remux on SC and for any Tidal/Qobuz container conversion if SpotiFLAC delegates.
- **Route auth** (RESOLVED 2026-05-13 — OQ-A, owner decision): there is **no `X-Session-Token` and no `init-token` endpoint** in the codebase (only `SHUTDOWN_TOKEN` at `main.py:126` for `/shutdown`+`/restart`; SC download routes have no route-level gate). **Owner decision**: option (b) — **no route-level token gate for v1**, consistent with the existing `/api/soundcloud/download` routes. The gap (no auth on local-API mutation routes generally) is **logged as a separate research topic** — `docs/research/research/idea_api-route-auth-model.md` — for future hardening, so it's tracked and not silently forgotten.
- **No `requests.get()` in async path**: any new orchestration in FastAPI handlers uses `httpx.AsyncClient` (see `coding-rules.md`). SpotiFLAC itself is sync — wrap it in `run_in_threadpool` or a `ProcessPoolExecutor` (parallel to the `SafeAnlzParser` pattern in `app/anlz_safe.py`).
- **SpotiFLAC stability**: third-party API endpoints can disappear (DMCA, rate limits, IP bans). The README explicitly warns "metadata fetching can fail due to IP rate-limits → VPN suggested". We must surface failures cleanly, never silently produce a low-quality fallback when the user asked for FLAC.
- **Legal posture — two-mode design** (RESOLVED 2026-05-13, owner decision): today's `soundcloud_downloader.py` has a 20-line `LEGAL BOUNDARIES` block documenting a careful ToS-mindful posture. SpotiFLAC's upstream APIs pull lossless audio from paid streaming services without per-user subscription verification — a different category. **Owner decision**: the project ships **ToS-friendly by default** — the default mode is SoundCloud-only and inherits the existing `LEGAL BOUNDARIES` posture unchanged. SpotiFLAC's Tidal/Qobuz/Amazon full-rip lives behind an explicit **Settings "backdoor" toggle**, default **OFF**, with a legal disclaimer shown at activation. A fresh install is posture-identical to today's SC-only downloader; the rip capability is strictly opt-in.
- **UPX / antivirus**: SpotiFLAC's standalone binaries are UPX-compressed and frequently flagged. We use the **Python module** (no UPX), not the bundled binary — sidesteps the AV noise but we should still document the risk.
- **Mutagen pin** ([mutagen.readthedocs.io](https://mutagen.readthedocs.io/)): cross-format tag-write library. **Already pinned `mutagen==1.47.0`** in `requirements.txt` line 53 (used by existing `app/audio_tags.py`). No new pin needed. Latest stable 1.47.0 (2023-09-03), Python 3.7+, covers all target containers (FLAC/MP3/M4A/AIFF/WAV/OGG/OPUS).
- **FFmpeg AIFF conversion** (Q11): `ffmpeg -i <src> -c:a pcm_s16le -map_metadata 0 <dst>.aiff` for 16-bit sources, `pcm_s24le` for 24-bit. `-map_metadata 0` carries over the source's tags (artist/title/album/etc.) so the post-download tagger only adds our additions (provenance URLs, normalised genre, ISRC, cover-art if missing). Bit-depth detection via `ffprobe -show_streams` → `bits_per_raw_sample`.
- **Songlink/Odesli API** (Q1d): for cross-platform URL resolution from any input URL. Free tier, no auth, public endpoint (`https://api.song.link/v1-alpha.1/links?url=<encoded>`). Rate-limit unclear → bounded retry + cache (1-week TTL acceptable since URLs are stable).
- **Spotify search without OAuth** (RESOLVED 2026-05-13): SpotiFLAC's `SpotifyMetadataClient` uses **hardcoded shared base64-encoded Spotify Web API client credentials** (verified in `SpotiFLAC/providers/spotify_metadata.py`). No `.env` keys needed on our side. **Caveat / risk**: the shared client can be revoked by Spotify at any time → SpotiFLAC upstream must respond; we'd lose Spotify search until they ship a new client. Mitigation: monitor `spotbye/SpotiFLAC` issues for credential-revocation events; ship optional fallback path that lets users add their own `SPOTIFY_CLIENT_ID`/`SPOTIFY_CLIENT_SECRET` in `.env` if the shared client dies.

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
| 10 | Provider on/off | **REVISED 2026-05-13 at sign-off** — two-mode: default ToS-friendly (SC-only, inherits existing `LEGAL BOUNDARIES`); SpotiFLAC full-rip behind explicit Settings "backdoor" toggle, default **OFF**, disclaimer at activation | Owner revised the earlier Q10-c "default-on" decision: project stays ToS-friendly by default, the rip capability is opt-in |
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

### 2026-05-13 — exploring results (D2/D5/D8/Q9 + version pins + reuse opportunities)

Five owner-blocked open items resolved by Claude this round; two material reuse opportunities discovered that shrink scope.

**Version pins (Q14 sub-resolution)**

| Package | Latest stable | Released | Python | Status in our repo |
|---|---|---|---|---|
| `SpotiFLAC` | **0.5.0** | 2026-05-13 (today) | >=3.9 | Not yet in `requirements.txt` |
| `mutagen` | **1.47.0** | 2023-09-03 | >=3.7 | **Already pinned** in `requirements.txt` line 53 (used by `app/audio_tags.py`) |

→ Pin `SpotiFLAC==0.5.0`. Note: SpotiFLAC released today — recommend 1-2 day burn-in before merge to catch any post-release bug surfacing in upstream issues. Mutagen pin already satisfied — no action needed.

**(Reuse-A) `app/audio_tags.py` already covers our tagging needs**

Discovered the repo already has a cross-format tag-write module that satisfies Q13's COMMENT-write requirement **without writing a new module**:

- **Public API**: `write_tags(path, updates: dict, artwork: bytes | None) -> bool` (line 254)
- **Format coverage**: MP3 (ID3v2.4) / FLAC (Vorbis) / M4A/MP4 (iTunes atoms) / OGG/OPUS (Vorbis) / **AIFF/WAV (ID3 chunk)**
- **Field aliases**: title, artist, album, **genre**, **comment**, rating, year, bpm, key (all six containers handled)
- **ISRC mapping already wired**: `_READ_KEYS["isrc"] = ["TSRC", "isrc", "----:com.apple.iTunes:ISRC", "ISRC"]` (line 319)
- **Non-fatal**: returns `False` on PermissionError / unsupported format / crash, never raises — same pattern we'd want
- **Already uses mutagen** (line 26) — single dependency entry-point already there

**Implication**: drop `app/downloader/tagging.py` from the planned files-list. Instead **extend `app/audio_tags.py`** with two thin helpers: `serialise_provenance(candidates, picked) -> str` (Q13b format: comma-space-joined URLs, descending quality) and `read_provenance(comment_str) -> list[(platform, url, was_picked)]`. The orchestrator then calls existing `write_tags(file_path, {"comment": serialised, "isrc": isrc, "genre": normalised, "year": year}, artwork_bytes)`.

**(Reuse-B) SpotiFLAC ships its own `LinkResolver` + `SpotifyMetadataClient`**

Examined `ShuShuzinhuu/SpotiFLAC-Module-Version` source. Key findings (`SpotiFLAC/__init__.py` exports):

- **`SpotifyMetadataClient`** — Spotify URL parsing + metadata + search. Uses **hardcoded shared Spotify Web API client credentials** (base64-encoded in `SpotiFLAC/providers/spotify_metadata.py` to dodge GitHub credential scanners): `_CLIENT_ID = base64.b64decode("ODNlNDQzMGI0NzAwNDM0YmFhMjEyMjhhOWM3ZDExYzU=")`. → **No `SPOTIFY_CLIENT_ID`/`_SECRET` in our `.env` needed**.
- **`LinkResolver`** (`SpotiFLAC/core/link_resolver.py`): wraps `https://api.song.link/v1-alpha.1/links` already. Method `resolve_all(track_id) -> Dict[str, str]` returns `{platform: url}` mapping. → **Drop `app/downloader/providers/songlink.py`** from planned files-list.
- **Individual provider classes exposed**: `QobuzProvider`, `TidalProvider`, `AmazonProvider`, `AppleMusicProvider`, `DeezerProvider`. → Option-B per-source probing is **directly supported** — we call each provider class individually instead of using the high-level `SpotiFLAC()` fallback-chain.
- **ISRC infrastructure**: `core/isrc_finder.py`, `core/isrc_helper.py`, `core/isrc_cache.py` already lookup ISRCs for cross-platform matching. We can either piggyback on these or run our own dedup logic.
- **Pydantic v2 dataclasses**: `TrackMetadata`, `DownloadResult` are `pydantic.BaseModel` subclasses (verified in `core/models.py`). Matches our `coding-rules.md` Pydantic-v2 stance.

**Risk added**: SpotiFLAC's shared Spotify client could be revoked by Spotify at any time. Mitigation: monitor `spotbye/SpotiFLAC` issues for credential-revocation events; ship a fallback path where users can add optional `SPOTIFY_CLIENT_ID`/`SPOTIFY_CLIENT_SECRET` in `.env` if the shared client dies.

**(D5 resolved) Rekordbox genre vocabulary**

Searched Pioneer DJ docs, Rekordbox 7 manual, forum threads, Mp3tag community discussions:

- Rekordbox does **NOT enforce a fixed genre dropdown / preset list**. Genre is a free-text field, populated from the file's `TCON` (ID3v2), `GENRE` (Vorbis), or `gnre`/`©gen` (MP4 atom) tag on import.
- Rekordbox 7 reads/writes ID3v1, v2.2/2.3/2.4, Vorbis Comments, and MP4 atoms.
- CDJ-3000 displays whatever string is in the Rekordbox library — long values are visually truncated on screen but the Track Filter / category browse still operates on the full string.
- Rekordbox's "My Tag" system (genre/components/situation) is a **separate internal-DB taxonomy**, NOT the ID3 genre field. My Tags don't write back to file tags.

**Decision**: canonical genre table stays **user-defined**, not mirrored from any Rekordbox preset (there is none to mirror). Ship a curated default of ~50-100 DJ-relevant genres seeded into `master.db` on first run (e.g. `["Tech House", "Deep House", "Techno", "Drum & Bass", "Trance", "Hardstyle", "Future Bass", ...]` — short plain strings, normalised casing). Apply Q11-genre-sync normalisation on incoming Spotify/Tidal/Qobuz genre strings → canonical → file tag. **Emit only short plain strings** (CDJ display safety). Multi-genre / subgenre fan-out lives in a separate DB column (`subgenres` JSON), not in the ID3 genre field.

**(Q9 resolved) SoundCloud ISRC backfill**

Verified the SC V2 API:

- Track responses expose **`publisher_metadata.isrc`** (string, nullable). Schema also includes `upc_or_ean`, `artist`, `album_title`, `p_line`, `c_line`, `writer_composer`, `release_title`, `publisher`, `explicit`, `contains_music`.
- Newer top-level Track schema documents an `isrc: Option[String]` field directly on the track.
- ISRC is **only populated when the track was distributed through SoundCloud-for-Artists or a label-distribution pipeline** (required for monetisation).
- Pure user-uploads from non-monetised accounts have `isrc: null`. Empirical expectation: **<30% hit rate** across a typical DJ library skewed toward edits/bootlegs/promos.

**Decision**: backfill is **opportunistic, best-effort**. In `app/soundcloud_api.py:_normalize_track`, extend the output dict with:
```python
"isrc": (raw.get("publisher_metadata") or {}).get("isrc") or raw.get("isrc"),
```
If present, store as third dedup key in `download_registry`. If absent, skip silently — do not retry, do not log as warning. Dedup priority order: ISRC (when both sides have it) > content-SHA256 > track-id.

**(D2 resolved) Spotify search path**

SpotiFLAC's `SpotifyMetadataClient` exposes Spotify metadata + search **without our own OAuth setup** (uses hardcoded shared base64-encoded creds). → No `spotipy` dependency, no `.env` keys. → Q1d auto-search feasibility confirmed.

**(D8 resolved) Concurrency benchmark methodology**

Baseline endpoint: **SoundCloud V2 `/resolve`** (stable, public, fast, idempotent — already exercised by `app/soundcloud_api.py:resolve_track_from_url`).

Algorithm:
```
1. Pick 4 unique stable SC track URLs (e.g. seed list shipped with the app)
2. Pre-warm: fire one throwaway request (DNS + TLS handshake amortisation)
3. Batch A — parallel: fire all 4 at once via threadpool, measure wall-time
4. Batch B — sequential: fire one at a time, measure cumulative wall-time
5. speedup = batch_b_total / batch_a_total
6. Apply thresholds (already in (D8) section above)
7. Persist to settings.json as unified_downloader.max_concurrency
```

Cache 7 days. Settings UI exposes "Re-benchmark" button for manual rerun. Auto-rerun on ISP/network change explicitly out of scope.

**Songlink/Odesli rate-limit policy**

10 RPM unauthenticated (per IP) / 60 RPM keyed. API key is free — request via contact form on odesli.co. Our recommended policy: **request a production key**, throttle to 8 RPM anon / 50 RPM keyed, cache responses for **30 days** (URLs are stable), retry 3x with exponential backoff (1s/4s/16s), honour `Retry-After` header on 429.

**Open items remaining for `exploring_`:**

- **D1**: 50-entry test-set for title-variance algorithm — **needs owner input** (real URL pairs from owner's library)
- **D3**: actual `pip install SpotiFLAC` + test-call in `ProcessPoolExecutor` — gated by owner's "no implementation" constraint, defer to `accepted_` phase
- **D5 starter list**: curated default genre-pool content — can be derived from owner's existing library on first run, but starter (~50 genres) needs a quick taste-pass from owner
- **Risk acknowledgements** for `evaluated_` phase: (a) shared Spotify client could be revoked, (b) Songlink rate-limit without key is tight, (c) SpotiFLAC released same-day as this research — burn-in needed

### 2026-05-13 — Pre-review corrections (Plan agent, draftplan_ stage)

An independent `Plan`-agent review of the filled Implementation Plan validated its assumptions against the actual repo. It found the risk/rollback/docs work solid but caught **6 factual errors / under-specifications** about the codebase. All are corrected in-place above; this subsection is the audit trail.

**5-item checklist verdict** (item 6, legal-posture, is owner-only):

| # | Item | Verdict |
|---|---|---|
| 1 | Plan addresses all goals | PASS-with-caveat — `COMMENT`-only provenance collides with existing SC pipeline's `permalink_url` write |
| 2 | Open questions deferred safely | PASS-with-caveat — D3 deferral was backwards (gate deferred *past* sign-off) |
| 3 | Risk mitigations defined | PASS |
| 4 | Rollback path clear | PASS |
| 5 | Affected docs identified | PASS |

**Corrections applied:**

1. **`_db_write_lock` location + applicability** — plan said `app/main.py:_db_write_lock` and claimed `download_registry` "is already on it". Reality: lock is `app/database.py:22` (`db_lock()` ctx mgr at `:26`), guards `master.db` only. `download_registry.db` is a **separate SQLite file** (`download_registry.py:38`) with its own WAL connection — does not and must not use the lock. → Corrected in Constraints, Step 3, Step 18.
2. **`X-Session-Token` does not exist** — plan gated routes "behind `X-Session-Token`" and referenced a `system_*` token policy. Reality: only `SHUTDOWN_TOKEN` exists (`main.py:126`), as a `?token=` param for `/shutdown`+`/restart`. SC download routes have no route-level token gate at all. → Corrected in Constraints + Step 19; raised as **OQ-A**.
3. **`audio_tags.py` cannot currently write ISRC** — plan's Step 15 assumed `write_tags(..., {"isrc": ...})` works. Reality: `_FIELD_ALIASES` has no `isrc` entry; no `_write_*` handler emits `TSRC`. The gap is explicitly documented at `soundcloud_downloader.py:723-727`. The extension is bigger than "2 thin helpers" — needs write-side ISRC aliasing + per-format wiring. → Corrected in Step 15 + Files-touched.
4. **`anlz_safe.py` PPE pattern mis-copied** — plan's D3 snippet wrapped the executor call in `anyio.to_thread.run_sync`; `anlz_safe.py` submits to the executor directly and calls `future.result(timeout=...)`. The snippet also omitted the load-bearing parts (`PER_CHUNK_TIMEOUT_S`, `BrokenExecutor` handling, panic budget, restart logic) and had no `timeout=` (a `coding-rules.md` violation). → Will be corrected when the D3 snippet graduates to real `spotiflac.py`; noted here so the implementer copies the *full* `anlz_safe` shape, not the sketch.
5. **AIFF / metadata work partly already exists** — plan listed `aiff.py` as greenfield. Reality: `_convert_to_aiff` exists at `soundcloud_downloader.py:745` and is hardcoded `pcm_s16le` — it would **downgrade 24-bit sources**, contradicting goal D4. `_apply_sc_metadata` (`:676`) already writes `permalink_url` into `COMMENT` (`:721`) — collides with our provenance write. → Corrected to "refactor not greenfield" in Step 13 + Files-touched; collision reconciliation added.
6. **`httpx` / `tenacity` not pinned** — plan's Constraints referenced `httpx.AsyncClient` but neither lib is in `requirements.txt`. → Corrected in Files-touched: default plan keeps the SC provider sync-wrapped via `asyncio.to_thread` (the existing `main.py` pattern), so no `httpx` for v1; if async orchestration is kept, both must be Schicht-A pinned.

**New open decisions surfaced by the pre-review — ALL RESOLVED 2026-05-13:**

- ~~**OQ-A — Route auth model**~~ ✅ **RESOLVED**: owner chose **(b)** — no route-level token gate for v1, consistent with existing `/api/soundcloud/download`. The general gap (no auth on local mutation routes) is logged as a separate research topic `idea_api-route-auth-model.md` for future hardening.
- ~~**OQ-B — D3 feasibility-test timing**~~ ✅ **RESOLVED**: owner chose **(a)** — lifted the no-implementation constraint for the one throwaway test. D3 ran 2026-05-13, **PASS** (see Step 2 + Findings § "D3 feasibility test executed"). `spotiflac.py` design verified before sign-off.
- ~~**Legal-posture**~~ ✅ **RESOLVED** (Review checklist item 6): owner chose **two-mode** — default ToS-friendly (SC-only), SpotiFLAC full-rip behind an explicit Settings "backdoor" toggle (default OFF, disclaimer at activation). Q10 + R6 + Constraints + Scope all updated.

### 2026-05-13 — D3 feasibility test executed (PASS)

Owner lifted the no-implementation constraint for this one throwaway test (OQ-B). Ran in an isolated temp venv, deleted afterwards — zero project-deps touched:

- `pip install SpotiFLAC==0.5.0` — clean install, no build errors
- Inside a `ProcessPoolExecutor(max_workers=1)` worker, with lazy in-worker imports (the `anlz_safe.py` pattern):
  - `import SpotiFLAC` → `__version__ == "0.5.0"`
  - `from SpotiFLAC import SpotifyMetadataClient, QobuzProvider, TidalProvider` → all import
  - `from SpotiFLAC.core.link_resolver import LinkResolver` → imports
  - `from SpotiFLAC.providers.spotify_metadata import parse_spotify_url` → imports
  - `parse_spotify_url("https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT")` → `{'type': 'track', 'id': '4cOdK2wGLETKBW3PvgPWqT'}` — offline parse round-trips across the IPC/pickle boundary
- Warm-reuse: 2 sequential `submit()`s to the same executor both succeeded

**Verdict: PASS.** Option-B + PPE-isolation architecture is feasible — no pickle-barrier issues, no breaking top-level-import side effects, offline parser round-trips cleanly. Phase 1's `spotiflac.py` is unblocked.

**Carry-forward**: the D3 test only proved import/instantiation feasibility. The production `spotiflac.py` must still copy the *full* `anlz_safe.py` crash-recovery shape — `future.result(timeout=...)`, `BrokenExecutor` catch + worker restart, panic budget. That scaffolding is the whole point of the PPE choice and is not optional.

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

Resolved in `exploring_` 2026-05-13:

- ~~D2~~ ✅ — Spotify search via SpotiFLAC's `SpotifyMetadataClient` (hardcoded shared creds, no `.env` keys needed; revocation-risk acknowledged)
- ~~Q9~~ ✅ — SC V2 API exposes `publisher_metadata.isrc` (nullable, <30% hit rate expected, opportunistic backfill)
- ~~D5~~ ✅ — Rekordbox has no fixed genre vocabulary → ship curated user-extensible default ~50 short DJ genres; short plain strings only
- ~~D8~~ ✅ — concurrency benchmark uses SC V2 `/resolve` baseline, 4 unique URLs, pre-warm + parallel-vs-sequential ratio
- ~~Versions~~ ✅ — `SpotiFLAC==0.5.0` (new pin), `mutagen==1.47.0` (already pinned)

Still open (carried into next round):

- **D1** — 50-entry title-variance test-set from owner's actual library (Spotify-URL → expected SC-URL pairs). Algorithm precision/recall gate at ≥ 95% / ≥ 90%. **Blocked on owner input** — but this is a test asset filled during Phase 2, not a sign-off blocker.
- ~~**D3**~~ ✅ **DONE 2026-05-13, PASS** — `pip install SpotiFLAC==0.5.0` in an isolated venv + PPE-boundary test-call. Module survives the IPC boundary, classes import inside the worker, warm-reuse holds. `spotiflac.py` design verified feasible.
- **D5-starter** — initial content of the curated genre table. Can be derived from owner's existing library on first-run scan; a starter ~50-entry hand-curated default would smooth onboarding. Not a sign-off blocker — implementation detail for Phase 4.
- **Risk-list**: (a) shared Spotify client revocation [R1], (b) Songlink rate-limit [R2], (c) SpotiFLAC same-day-release burn-in [R3] — all carried into the consolidated Risks section below.

---

## Risks & Mitigations (consolidated for `evaluated_`)

> Sourced from Findings sections above. Each risk has a mitigation that becomes actionable in `accepted_` / `inprogress_`. Rated by Impact (`low`/`medium`/`high`) × Probability (`unlikely`/`possible`/`likely`).

### R1 — SpotiFLAC's shared Spotify client revocation
- **Impact**: medium — we lose Spotify search + URL resolution; Tidal/Qobuz/Amazon paths unaffected
- **Probability**: possible — shared clients have a history of being killed; the credentials are findable in upstream sources
- **Mitigation**: ship optional fallback path that accepts user-provided `SPOTIFY_CLIENT_ID` + `SPOTIFY_CLIENT_SECRET` in `.env`. Detection: catch 401/403 from SpotiFLAC's Spotify calls → surface "Spotify search unavailable, see Settings → API Keys" toast. Monitor `spotbye/SpotiFLAC` issues for revocation events upstream.

### R2 — Songlink/Odesli unauthenticated rate limit (10 RPM)
- **Impact**: medium — cross-platform URL pivot stalls; falls back to per-platform search only
- **Probability**: likely — 10 RPM is tight for any concurrent user; first auto-search session likely hits it
- **Mitigation**: throttle to 8 RPM until a key is provisioned; cache responses 30 days; request free production key via odesli.co contact form (administrative — owner action); rebind throttle to 50 RPM once key lands in `.env`.

### R3 — SpotiFLAC same-day release (v0.5.0 released 2026-05-13)
- **Impact**: high — panics / regressions in upstream code crash our PPE worker repeatedly
- **Probability**: possible — any same-day release carries unsurfaced post-release bugs
- **Mitigation**: 1-2 day burn-in window before merging the pin. Check upstream issues + release notes daily during burn-in. PPE-isolation (D3) means crashes are recoverable but not invisible — log + surface to user. Have a `SpotiFLAC==0.4.x` fallback pin ready if a critical bug is found post-merge.

### R4 — SoundCloud V2 `client_id` rotation (inherited from existing SC pipeline)
- **Impact**: medium — entire SC provider stops working until ID is refreshed
- **Probability**: likely — already a known operational risk today, mitigated by existing dynamic scraper in `app/soundcloud_api.py`
- **Mitigation**: existing `get_sc_client_id()` already handles this — 1-hour memory cache + live scrape fallback. No new code needed in the unified downloader; just inherit the helper.

### R5 — Tidal/Qobuz/Amazon upstream API breakage (transitive via hifi-api, dabmusic.xyz, musicdl.me)
- **Impact**: high — specific provider goes dark, e.g. losing hi-res FLAC source
- **Probability**: likely over a 12-month horizon — third-party APIs that depend on reverse engineering have short half-lives
- **Mitigation**: per-provider feature flag in settings → user can disable a dead provider without crashing the whole downloader. Surface "<provider> currently unavailable, last working <timestamp>" to UI. Don't auto-fall-back to a lower-quality provider silently — surface the degradation explicitly.

### R6 — Legal-posture shift (kept for completeness; carried from `idea_`)
- **Impact**: high — project category shifts from "ToS-mindful SC downloader" to "streaming-ripping tool"
- **Probability**: certain if SpotiFLAC ships (this is a property of the feature, not a runtime risk)
- **Mitigation** (REVISED 2026-05-13, owner decision): the project ships **ToS-friendly by default** — SpotiFLAC's paid-streaming-rip is OFF until the user explicitly enables the Settings "backdoor" toggle, which shows the legal disclaimer at activation. A default install is posture-identical to today's SC-only downloader. Risk is **explicitly accepted** by owner with this two-mode mitigation in place — see corrected Constraints "Legal posture — two-mode design".

### R7 — Genre-sync novel-genre dialog UX dead-end on bootstrap
- **Impact**: low — user gets stuck if every Spotify-genre is novel during initial library bootstrap
- **Probability**: possible — a user with no library yet would see the dialog on every track of the first batch import
- **Mitigation**: dialog has a "always do this for unknown genres → [add as new]" persistence option so the user only hits the dialog once per import session, not once per track. Seed the canonical table from the ~50 DJ-genre starter list at install time so the bootstrap session has a base vocabulary.

---

## Implementation Plan

> Required from `implement/draftplan_` onward. Not filled at `idea_` stage.

### Scope

- **In**:
  - Single-track resolution + download across Spotify / SoundCloud / Tidal / Qobuz / Amazon / Apple Music / YouTube (any platform URL as input)
  - Playlist-batch download (Q5-b) — same per-track resolution loop applied over a playlist URL
  - Auto-search mode (Q1-d, D2) — free-form `Artist – Title` input → parallel platform search → candidate grid
  - Best-quality auto-pick among 100%-match candidates (Q3-c, D1 match + quality ranker)
  - AIFF-as-default output container (Q11, D4) — lossless source → AIFF; lossy source stays in original container
  - Provenance-URL write into `COMMENT` field (Q13, D6) via extended `app/audio_tags.py`
  - Standard metadata write-back: year, ISRC, album-art, normalised genre (Q11)
  - Genre-sync against a user-extensible canonical table (D5) with novel-genre confirmation dialog
  - Unified `MUSIC_DIR/<artist>/` folder layout (Q6) + one-time idempotent migration from `MUSIC_DIR/SoundCloud/<artist>/` (D7)
  - Concurrency auto-detection benchmark (Q12-d, D8) + Settings override
  - ISRC as third dedup key (Q9) — opportunistic backfill, never blocking
  - Two-mode design (Q10 REVISED 2026-05-13): default **ToS-friendly mode** (SoundCloud-only, inherits existing `LEGAL BOUNDARIES` posture); SpotiFLAC's Tidal/Qobuz/Amazon full-rip behind an explicit Settings "backdoor" toggle, default **OFF**, disclaimer at activation; per-provider feature flags within the backdoor mode

- **Out (deliberately)**:
  - Lyrics / LRC sync — SpotiFLAC supports it, but it's a separate research topic
  - Spotify OAuth / user-account login — public metadata only (uses SpotiFLAC's shared client)
  - Private-playlist read — only public playlists in v1
  - Target-format choice — AIFF is the *only* lossless target in v1; no user-selectable FLAC/WAV output
  - Auto-rerun of the concurrency benchmark on network/ISP change — manual "Re-benchmark" button only
  - CDJ-3000 PDB `COMMENT` propagation — the raw file tags are written, but threading the comment into `app/usb_pdb.py`'s PDB writer so it shows on the CDJ display is a **separate follow-up sub-task**
  - Re-implementing any streaming-service client — SpotiFLAC is the sole bridge
  - Hi-res *down*-conversion as a default — preserved by default (Q4-c); opt-in setting only

### Step-by-step

> Phased so each phase ends in a green, independently-committable state. Atomic commit per numbered step where practical.

**Phase 0 — Foundation**
1. Burn-in wait: monitor `spotbye/SpotiFLAC` issues for 1-2 days post-0.5.0-release (R3). Then add `SpotiFLAC==0.5.0` to `requirements.txt`.
2. **D3 feasibility test — DONE 2026-05-13, PASS** (owner lifted the no-implementation constraint for this one throwaway test per OQ-B). SpotiFLAC 0.5.0 installed cleanly in an isolated temp venv (no project-deps touched); `SpotifyMetadataClient` / `QobuzProvider` / `TidalProvider` / `LinkResolver` all import inside a `ProcessPoolExecutor(max_workers=1)` worker; the offline `parse_spotify_url()` returns `{'type':'track','id':...}` correctly across the IPC/pickle boundary; warm-reuse (2 sequential submits) survives. **The `spotiflac.py` provider design is verified feasible** — Phase 1 is unblocked. When this graduates to real code, copy the *full* `anlz_safe.py` shape (panic budget, `BrokenExecutor` handling, `future.result(timeout=)`, restart logic) — not the simplified sketch.
3. `download_registry` schema migration: additive columns only — `isrc TEXT`, `source TEXT`, `provenance_urls TEXT` (JSON), `picked_quality_tier INTEGER`. Old code ignores them; no drops. Migration uses `download_registry.py`'s own WAL connection — **does NOT touch `_db_write_lock`** (separate DB; corrected per pre-review).

**Phase 1 — Provider layer**
4. `app/downloader/__init__.py` — `SourceProvider` ABC (`resolve()`, `search()`, `download()`) + `Candidate` Pydantic-v2 dataclass (url, platform, claimed_quality, format, bit_depth, sample_rate, isrc, match_score, quality_tier_int).
5. `app/downloader/providers/spotiflac.py` — `ProcessPoolExecutor(max_workers=1)` worker (D3 pattern, mirrors `app/anlz_safe.py`). Import `QobuzProvider`/`TidalProvider`/`AmazonProvider`/`AppleMusicProvider`/`DeezerProvider`/`SpotifyMetadataClient`/`LinkResolver` *inside* the worker.
6. Extend `app/soundcloud_api.py:_normalize_track` — add `"isrc"` field (Q9 one-liner).
7. `app/downloader/providers/soundcloud.py` — wrap existing `soundcloud_downloader.py` acquisition logic + add V2 `/search/tracks` for search mode.

**Phase 2 — Matching + quality**
8. `app/downloader/match_rules.py` — maintained regex lists (remix/version/featuring tags, separators).
9. `app/downloader/match.py` — title-variance algorithm (D1): duration hard-gate + normalisation pipeline + 5 identity tests + Sørensen-Dice ≥ 0.92 fallback.
10. `app/downloader/quality.py` — 5-tier quality ranking + best-pick (Q3-c: bit-depth → sample-rate → file-size).

**Phase 3 — Resolver + Search**
11. `app/downloader/resolver.py` — phase-1 parallel probe across enabled providers (bounded concurrency from D8 setting), returns `Candidate[]` filtered through `match.py`.
12. `app/downloader/search.py` — free-form search → parallel platform search → SpotiFLAC `LinkResolver` cross-platform pivot → ISRC-dedupe → candidate grid.

**Phase 4 — Post-download pipeline**
13. `app/downloader/aiff.py` — **refactor, not greenfield** (corrected per pre-review). `_convert_to_aiff` already exists at `soundcloud_downloader.py:745` but is hardcoded `pcm_s16le` — it would **downgrade 24-bit sources**, contradicting goal D4. Extract it into `app/downloader/aiff.py`, add `ffprobe` bit-depth detection → `pcm_s16le`/`pcm_s24le`, add `-map_metadata 0`, then point the existing SC pipeline at the refactored function so there's one AIFF converter, not two.
14. `app/downloader/genre_sync.py` — canonical-table normaliser + ~50-genre starter seed + novel-genre dialog hook.
15. Extend `app/audio_tags.py` (corrected per pre-review — **more than 2 helpers**): (a) `serialise_provenance()` + `read_provenance()` helpers (D6); (b) **write-side ISRC support** — `_FIELD_ALIASES` currently has no `isrc` entry and no `_write_*` handler emits `TSRC`/`isrc`/`----:com.apple.iTunes:ISRC` (the gap is explicitly documented at `soundcloud_downloader.py:723-727`). Add the `isrc` alias + per-format frame wiring across all six `_write_*` handlers.
16. `app/downloader/migration.py` — idempotent `SoundCloud/<artist>/` → `<artist>/` folder migration (D7).
17. `app/downloader/concurrency.py` — first-run benchmark (D8) → `settings.json`.

**Phase 5 — Orchestration + API**
18. Orchestrator in `app/downloader/__init__.py` — wire the 9-step post-download pipeline from the Recommendation. Writes into `master.db` (library auto-import, genre canonical table) go through `db_lock()` from `app/database.py`; writes into `download_registry.db` use that module's own WAL connection (corrected per pre-review).
19. `app/main.py` routes: `POST /api/downloads/unified/{resolve,search,fetch}`. **No route-level token gate** (OQ-A resolved — matches existing `/api/soundcloud/download` pattern). Use `route-architect` agent before touching `main.py`.

**Phase 6 — Frontend**
20. `frontend/src/components/Download/*` — search-bar input mode, candidate-grid with platform-icons + quality-badges, picked-source highlight, novel-genre confirmation dialog. Routes through `frontend/src/api/api.js` axios instance.

**Phase 7 — Tests + graduation**
21. Test suite (see Testing approach).
22. Docs: `architecture.md` data-flow, `FILE_MAP.md`, `backend-index.md`, `frontend-index.md`, `CHANGELOG.md`. Then `git mv` doc → `archived/implemented_<date>`.

### Files touched (expected)
- `app/downloader/__init__.py` (new) — orchestrator + `SourceProvider` ABC + `Candidate` dataclass
- `app/downloader/resolver.py` (new) — phase-1 parallel probe across providers, returns `Candidate[]`
- `app/downloader/search.py` (new) — phase-1 search mode for free-form input; leverages SpotiFLAC's `LinkResolver` for cross-platform pivot (no own Songlink client needed — see Reuse-B finding)
- `app/downloader/providers/soundcloud.py` (new) — wrap existing `soundcloud_downloader.py` + V2 `/search/tracks`; extend `app/soundcloud_api.py:_normalize_track` to include `isrc` via `publisher_metadata.isrc`
- `app/downloader/providers/spotiflac.py` (new) — wrap SpotiFLAC inside `ProcessPoolExecutor(max_workers=1)` worker (D3); import `QobuzProvider` / `TidalProvider` / `AmazonProvider` / `AppleMusicProvider` / `DeezerProvider` individually for per-service probing; import `SpotifyMetadataClient` for search; import `LinkResolver` for Songlink pivot
- ~~`app/downloader/providers/songlink.py`~~ — **dropped**, use SpotiFLAC's bundled `core/link_resolver.py:LinkResolver`
- `app/downloader/quality.py` (new) — quality-ranking (5 tiers, see Findings) + best-quality picker (file-size + bit-depth + sample-rate, Q3-c rule)
- `app/downloader/match.py` (new) — title-variance match algorithm (D1, hard duration gate + 5 identity tests + Sørensen-Dice ≥ 0.92 fallback)
- `app/downloader/match_rules.py` (new) — maintained regex list of remix/version/featuring tags for normalisation
- ~~`app/downloader/tagging.py`~~ — **dropped**, extend existing `app/audio_tags.py` with `serialise_provenance()` + `read_provenance()` helpers (see Reuse-A); orchestrator calls existing `write_tags(file_path, {"comment": serialised, "isrc": isrc, "genre": normalised, "year": year}, artwork_bytes)`
- `app/downloader/aiff.py` (new, but **refactor of existing code** — see pre-review) — extract `soundcloud_downloader.py:745:_convert_to_aiff`, fix its hardcoded `pcm_s16le` to bit-depth-aware `pcm_s16le`/`pcm_s24le` via `ffprobe`, add `-map_metadata 0`. Existing SC pipeline re-points at this single converter.
- `app/downloader/genre_sync.py` (new) — incoming-genre → library-canonical normaliser (lookup-table + Sørensen-Dice ≥ 0.90 + confirm-on-novelty dialog); ship curated ~50 short DJ-genre default list
- `app/downloader/concurrency.py` (new) — first-run benchmark (D8): SC V2 `/resolve` baseline, 4 unique URLs, pre-warm + parallel-vs-sequential, 7-day cache, "Re-benchmark" button hook
- `app/downloader/migration.py` (new) — first-launch `MUSIC_DIR/SoundCloud/<artist>/` → `MUSIC_DIR/<artist>/` migration (D7); idempotent
- `app/main.py` — new routes: `POST /api/downloads/unified/resolve`, `POST /api/downloads/unified/search`, `POST /api/downloads/unified/fetch`, all behind `X-Session-Token`
- `app/download_registry.py` — add columns: `isrc TEXT`, `source TEXT`, `provenance_urls TEXT` (JSON), `picked_quality_tier INTEGER`
- `app/soundcloud_api.py` — **extend** `_normalize_track` output dict with `"isrc": (raw.get("publisher_metadata") or {}).get("isrc") or raw.get("isrc")` (Q9 opportunistic backfill)
- `app/audio_tags.py` — **extend** (corrected scope per pre-review): (1) `serialise_provenance()` + `read_provenance()` helpers (Q13 format); (2) **write-side ISRC** — add `isrc` to `_FIELD_ALIASES` + wire `TSRC` (ID3), `isrc` (Vorbis), `----:com.apple.iTunes:ISRC` (MP4) into all six `_write_*` handlers. Gap is documented at `soundcloud_downloader.py:723-727`.
- `app/soundcloud_downloader.py` — **refactor** (added per pre-review): re-point `_convert_to_aiff` (line 745) at the new bit-depth-aware `app/downloader/aiff.py`; reconcile `_apply_sc_metadata` (line 676) `Comment`-field write (currently `permalink_url`, line 721) with the unified provenance serialisation so the two don't collide — the SC permalink becomes one entry in the provenance URL list, not a separate overwrite.
- `requirements.txt` — pin `SpotiFLAC==0.5.0` (new; mutagen already pinned 1.47.0 line 53). **If** async orchestration uses `httpx.AsyncClient` + retry, also pin `httpx==<v>` + `tenacity==<v>` (neither is currently in `requirements.txt`). Default plan: keep SC provider sync-wrapped via `asyncio.to_thread` (the existing `main.py` pattern) → no `httpx` needed for v1.
- `.env.example` — **optional** `SPOTIFY_CLIENT_ID` + `SPOTIFY_CLIENT_SECRET` as fallback only (default uses SpotiFLAC's shared creds; users opt-in if Spotify revokes the shared client)
- `frontend/src/components/Download/*` — new UI: search-bar input mode, candidate-grid view with platform-icons + quality-badges, picked-source highlight, novel-genre confirmation dialog
- `tests/test_unified_downloader_match.py` (new) — 50-entry test set for D1 algorithm (blocked on owner input)
- `tests/test_unified_downloader_quality.py` (new) — quality-ranker fixtures
- `tests/test_unified_downloader_e2e.py` (new) — end-to-end fixtures (mocked providers)
- `docs/architecture.md`, `docs/FILE_MAP.md`, `docs/backend-index.md`, `docs/frontend-index.md`, `CHANGELOG.md` — update at graduation

### Testing approach

- **Unit**
  - `tests/test_unified_downloader_match.py` — D1 algorithm against the 50-entry owner-curated test-set. **Gate: ≥ 95% precision / ≥ 90% recall.** Phase 2 does not complete until this passes.
  - `tests/test_unified_downloader_quality.py` — quality-ranker fixtures: synthetic `Candidate[]` lists, assert correct tier ordering + tiebreak (bit-depth → sample-rate → file-size).
  - `genre_sync` fuzzy-match — known incoming strings → expected canonical (Sørensen-Dice ≥ 0.90 boundary cases).
  - `audio_tags` provenance round-trip — `serialise_provenance()` output fed back through `read_provenance()` must reconstruct order + picked-flag.
- **Integration** (pytest `integration` marker)
  - `resolver.py` with mocked providers — assert parallel probe aggregates + filters to 100%-match correctly.
  - `migration.py` idempotency — run twice, assert second run is a no-op; assert DB path rows updated.
  - `concurrency.py` benchmark determinism — mock the SC `/resolve` latencies, assert threshold mapping.
  - `download_registry` schema migration — assert additive columns present, old rows readable.
- **E2E** (`e2e-tester` subagent)
  - Real dev servers (`npm run dev:full`): paste a Spotify URL → candidate grid renders → pick → download → file lands in `MUSIC_DIR/<artist>/` as `.aiff` with correct `COMMENT` provenance + ISRC + genre tags.
  - Auto-search path: free-form input → grid with platform-icons → download.
  - Novel-genre dialog: import a track with an unknown genre → dialog appears → "always add" persists.
- **Manual gates**
  - D3 PPE-feasibility (Phase 0, step 2) — blocks Phase 1.
  - SpotiFLAC burn-in monitoring (Phase 0, step 1) — blocks the `requirements.txt` pin.
  - `audio-stack-reviewer` subagent on `aiff.py` (FFmpeg invocation, bit-depth handling).
  - `route-architect` subagent before `app/main.py` edits; `test-runner` after each phase; `doc-syncer` before graduation.
- **Per-area runner**: invoke `test-runner` subagent after each phase, not the whole suite — area-scoped runs (`pytest tests/test_unified_downloader_*.py -v`).

### Risks & rollback

Risk register R1-R7 above covers the runtime/operational risks with mitigations. Implementation-specific rollback:

- **Master kill-switch**: `unified_downloader.enabled` setting, **default `false`** until the full test suite is green + E2E passes. Feature is dark in production until explicitly switched on.
- **DB migration is additive-only** — four new columns, zero drops/renames. Old code paths ignore unknown columns; rolling back the code leaves the columns harmlessly present. No down-migration needed.
- **Folder migration (D7) is idempotent + flagged** — `legacy_per_source_folders` setting. Migration itself is not auto-reverted (files already moved), but the flag stops *new* downloads from using the unified layout if the user wants the old behaviour back.
- **Per-provider feature flags** — each of SpotiFLAC / SoundCloud / each sub-provider can be independently disabled in Settings. A dead upstream (R5) degrades gracefully instead of breaking the whole downloader.
- **SpotiFLAC pin fallback** — keep `SpotiFLAC==0.4.x` known-good as a documented fallback pin (R3). Pin bump is one-line revert.
- **Atomic commits per phase** — each numbered step lands as its own commit, so `git revert <sha>` cleanly backs out any single phase without unravelling the rest.
- **Phase 0 gate** — if D3 (PPE feasibility) fails, the entire `spotiflac.py` design is invalid and the plan returns to `rework_` before any provider code is written. This is the cheapest possible failure point.

## Review

> Filled by reviewer at `review_`. A pre-review already ran at `draftplan_` stage — see below.

**Pre-review (2026-05-13, `Plan` agent, `draftplan_` stage)**: independent validation against the real repo. Found the risk/rollback/docs work solid, caught 6 factual errors (all corrected in-place — see Findings § "Pre-review corrections"). Surfaced 2 new owner decisions (OQ-A, OQ-B) that block `review_` → sign-off. Checklist status reflects the pre-review:

- [x] Plan addresses all goals — *PASS-with-caveat: provenance/`COMMENT` collision with existing SC pipeline noted + reconciliation added to Step 15 / Files-touched*
- [x] Open questions answered or explicitly deferred — *D1 + D5-starter deferred (test asset / Phase-4 detail, not sign-off blockers); D3 executed → PASS*
- [x] Risk mitigations defined — *R1-R7 + implementation-specific rollback section*
- [x] Rollback path clear — *kill-switch default-off, additive-only migration, per-provider flags, atomic per-phase commits, Phase-0 gate*
- [x] Affected docs identified — *`architecture.md`, `FILE_MAP.md`, `backend-index.md`, `frontend-index.md`, `CHANGELOG.md`*
- [x] **Legal-posture shift acknowledged and accepted by owner** — *RESOLVED 2026-05-13: owner chose the two-mode design (default ToS-friendly, SpotiFLAC rip behind an opt-in Settings "backdoor" toggle). Explicitly accepted.*
- [x] **OQ-A answered** — *RESOLVED: option (b), no route-level token gate (matches existing SC routes); general gap logged as `idea_api-route-auth-model.md`.*
- [x] **OQ-B answered** — *RESOLVED: option (a), D3 ran before sign-off → PASS.*

**Rework reasons / notes:**
- Pre-review corrections were applied **in-place** rather than via a `rework_` round-trip — the doc was still in `draftplan_` ("plan is being written"), not yet formally submitted to `review_`. Full audit trail in Findings § "Pre-review corrections".
- 2026-05-13: OQ-A + OQ-B + legal-posture all answered by owner; doc promoted `draftplan_` → `review_`. The plan is now "ready, waiting for sign-off". The remaining `review_` → `accepted_` promotion requires **explicit owner sign-off** per `.claude/rules/research-pipeline.md` — this review checklist being fully ticked is a precondition, not the sign-off itself.

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
