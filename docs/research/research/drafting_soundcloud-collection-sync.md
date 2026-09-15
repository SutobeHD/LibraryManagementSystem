---
slug: soundcloud-collection-sync
title: SoundCloud Collection Sync — likes + playlists mirrored into Rekordbox, incremental download, genre/sub-genre routing into the Genres tree
owner: tb
created: 2026-09-15
last_updated: 2026-09-15
tags: []
related: []
supersedes: []
superseded_by: []
---

# SoundCloud Collection Sync — likes + playlists mirrored into Rekordbox, incremental download, genre/sub-genre routing into the Genres tree

> **Caveman+ style.** Fragments, bullets. Drop articles/filler/hedges. No prose paragraphs.
> Word caps are **soft** — recommendations, not hard blocks. Exceed when topic complexity demands; routines may flag excess length but never truncate facts.
> State = folder + filename prefix (not frontmatter). Lifecycle = audit trail. See `../README.md`.
> Routines advance this doc **autonomously** by state. **One** user gate: `approvalgate_` — read `## Approval Summary` + `## Mockup`, then `/approve` or `/reject`. After approval you test the finished branch locally and merge it yourself.
> Section ownership: each `> ↓ Stage X — <agent>: …` marker names the agent that fills the section. Don't write into a section before its stage.

## Lifecycle

- 2026-09-15 — `research/idea_` — created from template (user idea from a voice note, interactive session; `## Original Idea` transcribed from the German voice message — user's own words, condensed)
- 2026-09-15 — `research/drafting_` — Stage 1 filled interactively (2 read-only codebase scans + verification reads + SoundCloud OpenAPI spec; Prior Art, Problem, Goals / Non-goals, Constraints, Dependencies, 17 OQs, 5-agent Research Plan). Wave-1 codebase surface already banked in `## Findings`

## Original Idea (verbatim — never edit)

<!--
Written ONCE by the user. 1–3 sentences, raw. NEVER edited after — not by routines, not by the user.
Every verifier (Stage 1 idea-check, Stage 2 research-check, Stage 3 plan-review, Stage 4 doc-sync) checks
its work against this block. It is the anchor against scope-creep and misreading.
-->

Mein Rekordbox-Library-System (Ordner wie Playlists, Artists, Genres …) hat ein paar Parallelen zu SoundCloud: Man könnte eine Playlist „Likes" hinzufügen und die mit den SoundCloud-Likes synchronisieren, und die Playlists mit den SoundCloud-Playlists synchronisieren, sodass die alle lokal runtergeladen sind — und wenn ein neuer Track dazukommt, wird nur der neue runtergeladen, nicht alle. Außerdem fände ich es schön, wenn man die SoundCloud-Genre-Sachen beim Download mitnimmt und den Tracks automatisch Genre und Subgenre gibt, sodass sie z. B. automatisch in die Genre-Playlists eingeordnet werden. Das ist sehr ähnlich zum Artist-Sync, den ich schon woanders am Plan habe — vielleicht als Erweiterung dazu.

---

> ↓ Stage 1 — `drafting_`. `research-draft` fills Problem → Research Plan via 4 agents (Scout, Prior-Art, Risk-Surface, Worker). Verifier fills Idea Verification.

## Prior Art

- **Active — parent, this doc is its declared follow-up:** [accepted_library-artist-hub](../implement/accepted_library-artist-hub.md) — approved 2026-09-04. Ships the pieces this doc must **reuse, not rebuild**: sidecar store with a generic `collection_kind` (`collections` / `sync_state` / `projection` / `catalogue_cache` tables, Step 3), adopt-or-create + diff-in-place Rekordbox projection engine (Step 6), `_sc_get` hardening + shared paginator (T-12), per-collection mode Auto / Review / Off + Update button + idle background sync (T-17), the `remove_track_from_playlist` arity fix (T-1). Its Non-goal *"label / genre / setlist folder projection … follow-up doc"* is exactly this doc. **Boundary:** artist-hub = per-**artist** catalogue diff + merge; this doc = per-**collection** (playlist / likes) mirror + genre routing. **Dependency:** M1 T-1, T-3, T-7 and M2 T-12 land first; this doc adds kinds `playlist` + `likes` to the same store.
- **Active — sibling, absorbs the one-shot half:** [accepted_downloader-unified-multi-source](../implement/accepted_downloader-unified-multi-source.md) — Q5-b "playlist-batch download over a playlist URL" (one-shot, no state), D5 genre-sync canonical table + `genre_mappings` + novel-genre dialog (`app/downloader/genre_sync.py`, Phase 4), sub-genres kept in a separate `subgenres` column rather than the ID3 genre field, provenance URLs into `COMMENT` (D6). **Boundary:** it downloads a URL once; this doc keeps a collection in sync over time and routes `tag_list`, which D5 never sees. **Reuse:** D5 table as the genre half of the rule engine (OQ8); D6 comment format must coexist with routing chips (OQ7).
- **Active — tag-write path:** [accepted_download-format-setting](../implement/accepted_download-format-setting.md) — AIFF default + `-map_metadata 0` + mutagen overlay. Every field this doc writes into a file rides that path.
- **Active — soft prereq:** [evaluated_soundcloud-persistent-login](evaluated_soundcloud-persistent-login.md) — unattended background sync dies on token expiry without silent refresh (same dependency artist-hub carries).
- **Active — shared matcher:** [inprogress_external-track-match-unified-module](../implement/inprogress_external-track-match-unified-module.md) — "do I already own this SC track?" must use it; the sync engine's private `SequenceMatcher ≥ 0.65` (`app/soundcloud_api.py:604-625`) is a third copy of the same rule.
- **Active — perf + lock constraints:** [drafting_performance-overhaul](drafting_performance-overhaul.md) (no pagination, blocking jobs) and [exploring_db-write-lock-retrofit](exploring_db-write-lock-retrofit.md) (the `active_db` fallback branches at `app/soundcloud_api.py:719-720` and `app/soundcloud_downloader.py:1572-1576` are the pattern *not* to copy).
- **Shipped — hard constraint:** [implemented_security-api-auth-hardening](../archived/implemented_security-api-auth-hardening_2026-05-17.md) — every mutation route behind `require_session`; all SC routes already are (`docs/backend-index.md:128-149`).
- **In-code prior art — the feature is half-built:** `SoundCloudSyncEngine` (`app/soundcloud_api.py:588-800`) creates `SC_<title>` playlists in `sc_sync_folder_id` and adds fuzzy-matched local tracks; routes `POST /api/soundcloud/{sync,sync-all,preview-matches,merge,download-playlist}` (`app/main.py:4364-4509`, `:3990-4071`); UI `frontend/src/components/SoundCloudSyncView.jsx`; download-side dedup gate skips already-downloaded tracks **and still links them** to the `SC_` playlist (`app/soundcloud_downloader.py:1089-1151`). What is missing = the whole "kept in sync" half: persisted collection state, automatic re-run, likes beyond 500, removal handling, genre/tag routing (`tag_list` dropped at `app/soundcloud_api.py:347-356`), user-tree placement (`SC_` prefix, name-only lookup `:634-637`). **Absorb, never run beside it** — two writers per SC playlist is the artist-hub double-writer risk again.
- **In-code prior art — taxonomy already exists twice:** chip vocabulary Genre / Subgenre / Components / Type hard-coded in `frontend/src/components/RankingView.jsx:9-14`, written into the free-text `Comment` (`:483-495`); live mode already **parses + evaluates** Rekordbox smart-list rules (`app/live_database.py:406-461`, `:785-917`). The user's `Genres` tree (screenshot 2026-09-15: `Raw / 4-5 / 130·140·150·160`, `Hypnotic`, `Clean Beat`, `Techno`, … as smart lists) is therefore readable by the app → the routing target can be **derived**, not typed.
- **External precedent:** `scdl` (github.com/scdl-org/scdl, GPL-2.0, maintenance inactive) — `-f` likes, `-p` playlists, `--download-archive` "skip already-downloaded", `--sync [file]` "compares an archive file to a playlist and downloads/removes any changed tracks" = the incremental-ledger idea in CLI form; writes Title/Artist/Album/Artwork tags only, no genre routing. Rekordbox itself streams SoundCloud Go+ playlists/likes in-app (streaming-only, no local files, no tag write) — cite in explore.

## Problem

SC likes + playlists reach the library only through manual, stateless runs: "Sync" = match-only into `SC_` playlists, "Download playlist" = re-list everything, registry gate skips the owned. No persisted collection state, no automatic re-run, likes capped at 500, removals never propagate, `SC_` names ignore the user's `Libary/Playlists` tree. SC `genre` lands as a bare Genre string, `tag_list` is thrown away, chips stay manual → new tracks pile up outside the `Genres` smart lists. Cost: manual re-download rituals, untagged inbox, likes > 500 invisible.

## Goals / Non-goals

**Goals**
- **Collection mirror.** Each chosen SC collection (own playlist, Likes; liked playlists = OQ1) ↔ exactly one local Rekordbox playlist, adopt-or-create inside the user's chosen folder, kept in sync by re-runs. **Metric:** 2nd run creates 0 playlists + 0 dupe entries; a track liked on SC shows in the local `Likes` playlist after the next sync.
- **Delta-only download.** Only tracks not already owned (registry `sc_track_id` → content hash → library match) are fetched. **Metric:** 200-track playlist + 1 new track → exactly 1 download and ≤ 2 listing calls.
- **Likes complete.** Whole Likes collection, not the first 500. **Metric:** mirrored count == SC `track_count` minus non-`playable` + dead.
- **Removal policy.** Unliked / removed-from-playlist → configurable (default: drop from the mirror playlist, keep file + library row). **Metric:** 0 audio files deleted in any mode.
- **Genre + sub-genre routing.** SC `genre` + `tag_list` (+ `bpm` when present) → user's own vocabulary via an editable rule table → written to the fields the `Genres` smart lists key on (carrier = OQ7: Genre field / Comment chips / MyTag). **Metric:** ≥ 90 % of a seeded 100-track corpus lands in the intended smart list with 0 manual tagging; 0 silently invented vocabulary (novel terms queue for review — D5 rule).
- **Taxonomy learned, not typed.** Rule table seeded from the user's existing smart-list rules (live-mode parser) + the chip vocabulary. **Metric:** first-run seed covers every playlist under `Genres` with ≥ 1 rule.
- **Same sync UX as Artist Hub.** Per-collection mode Auto / Review / Off, per-collection Update button, idle background sync — one job pattern, one Settings surface, one sidecar. **Metric:** no second scheduler / job store.
- **Absorb the half-built sync.** `SoundCloudSyncEngine`, the five SC sync routes and `SoundCloudSyncView.jsx` become the mirror, not a parallel path. **Metric:** one writer per SC playlist.

**Non-goals** (deliberately out of scope)
- Two-way sync — local edits never write SC likes / playlists. SC is a read-only source.
- Other users' collections, the following feed, reposts beyond the own account + explicitly liked playlists. No crawl.
- Non-`playable` tracks (preview / blocked), `snipped` bypass, DRM — the downloader's LEGAL BOUNDARIES stay untouched.
- Writing Rekordbox **smart-list rules** (`djmdPlaylist.SmartList`). v1 reads them, never writes them.
- Artist catalogue diff / discovery (artist-hub); one-shot playlist-URL download + multi-source resolution (downloader-unified); token refresh (persistent-login).
- Retro-tagging tracks that did not come from SoundCloud. (SC-origin backfill = OQ10.)
- New download backend, new scheduler dependency.

## Constraints

- **SC public API (OpenAPI spec, `github.com/soundcloud/api` → `openapi/api.yaml`):** `GET /me/likes/tracks` (`limit` ≤ 200, `linked_partitioning`, `access_explicit`), `GET /me/likes/playlists`, `GET /users/{urn}/likes/{tracks,playlists}` (`access` filter), `GET /me/playlists?show_tracks` (≤ 200), `GET /playlists/{urn}` + `/playlists/{urn}/tracks` (`secret_token`, `access`, `linked_partitioning`) — none deprecated. Track schema carries `genre`, `tag_list` ("space-separated, multi-word tags double-quoted", machine tags `ns:key=value`), `label_name`, `bpm`, `key_signature`, `created_at`, `access` (`playable|preview|blocked`), `urn`. Playlist carries `tracks`, `track_count`, `last_modified`, `urn`, `sharing`. **`release_date` and `publisher_metadata` are not on the public Track schema** — today they come from api-v2 `/tracks/{id}` (`app/soundcloud_downloader.py:117`, `_fetch_sc_metadata` `:820`, `:908`, `:915`). Rate limits: metadata endpoints unthrottled, stream 15 000 / 24 h (artist-hub wave 2); pager spacing 0.3 s (`app/soundcloud_api.py:524`).
- **Client drift:** `get_likes` hits deprecated `/users/{id}/favorites` with `offset` (`app/soundcloud_api.py:487-488`), caps at 500 (`:477`), `@lru_cache(maxsize=32)` keyed on the token (`:476`) → a long-running sidecar never sees a new like; `get_playlists` same cache (`:403`). `_normalize_track` keeps only id / title / artist / duration / permalink / artwork / downloadable / download_url (`:347-356`) — `genre`, `tag_list`, `label_name`, `bpm`, `access` dropped. `SC_API_BASE` is the public host (`:140`); the downloader mixes in v2 (`app/soundcloud_downloader.py:117`).
- **Data shape — playlists:** `find_or_create_playlist` matches by **name only** across the whole tree (`app/soundcloud_api.py:634-637`), no parent check, no id-map → a renamed / moved / duplicated playlist silently forks (rbox enforces no uniqueness — artist-hub wave 5). Prefix `SC_` hard-coded (`:591`); target folder = `sc_sync_folder_id` (`app/services.py:789`, read at `:641`). `sync_playlist` only adds, never removes (`:701-725`); removal needs `remove_track_from_playlist`, broken until artist-hub T-1 (`app/live_database.py:1342`).
- **Data shape — registry:** `download_history` = one row per `sc_track_id` (`UNIQUE`, `app/download_registry.py:94`) with a single `sc_playlist_title` (`:81`) and `local_track_id` (`:93`) → cannot express multi-playlist membership or "removed since"; it stays the download ledger, membership goes to a sidecar (artist-hub pattern: WAL + module-private lock, never `_db_write_lock`).
- **Data shape — genre:** Genre is a relationship field written via `update_content_genre` (`app/live_database.py:1073-1077`) on a **second** write after `create_content(path)` (`:930`, `:938-946`). SC `genre` already reaches `djmdGenre` today: file tag `TCON` (`app/soundcloud_downloader.py:924`) → re-read on import (`app/services.py:1325`, `:1333`, `:1354`, `:1372`). `tag_list` never written. **No sub-genre field** in Rekordbox / rbox; carriers today: `Comment` (DB `app/live_database.py:1014`, file `COMM`), `MyTag` (write API **unverified** — `_try_call` probes method names, `app/live_database.py:1090-1210`, `:1106`), `ColorID` / `Rating` (`:1017-1050`). Grouping has no writer (`app/audio_tags.py:33-56`; `app/live_database.py:845` maps `grouping` → `ColorID`). HTTP write surface = `TrackUpdateReq` Rating / ColorID / Comment / Genre (`app/main.py:345-351`, route `:1183`, batch `:1218`).
- **Smart lists:** live mode reads + evaluates RB smart-list XML — `_load_playlists` (`app/live_database.py:406-461`, raw XML kept as `smart_list` `:456`), `_parse_smart_rules` (`:785-806`), `_check_condition` (`:824-917`; fields artist / title / album / genre / label / bpm / rating / comment / key / myTag / grouping / duration `:834-847`; BPM stored ×100 `:900-901`; unmapped PropertyName → `False` `:850-852`). Writing RB smart lists exists for XML mode only (`app/database.py:560-577`); live fallback keeps criteria in memory (`:1009-1028`). Second, numeric-id engine `app/smart_playlist_engine.py:48-64` is *not* the live one. Chip vocabulary `frontend/src/components/RankingView.jsx:9-14` → `Comment` (`:483-495`).
- **Tag write:** `app/audio_tags.py` handles genre / comment / rating / year / bpm / key for MP3 / FLAC / M4A / OGG / AIFF / WAV (`:33-56`, dispatch `:312-324`, AIFF `:243-309`); no grouping / TXXX / ISRC. `_apply_sc_metadata` (`app/soundcloud_downloader.py:885-950`) sets **Album = SC playlist title** (`:912`) and **Comment = permalink** — routing chips must not clobber that comment, and downloader-unified D6 puts source URLs there too.
- **Concurrency invariants:** `_sync_lock` → 409 on double start (`app/main.py:4368-4369`); every `master.db` write through the facade under `db_lock()` (`app/database.py`); the dead `active_db` fallbacks (`app/soundcloud_api.py:719-720`, `app/soundcloud_downloader.py:1572-1576`) must not be copied; registry = own WAL connection, never `_db_write_lock`; downloads land under `MUSIC_DIR/SoundCloud/<artist>/` via `_build_save_path` + `validate_audio_path` (`app/soundcloud_downloader.py:175`).
- **Perf / capacity:** `_fuzzy_match_with_score` scans every local track per SC track (`app/soundcloud_api.py:611-625`) → 3 000 likes × 10 000 tracks = 3·10⁷ `SequenceMatcher` ratios per run; must index by normalised title or delegate to `external_track_match`. `self.db.tracks` is the whole in-memory dict. No list virtualisation in the sync view (`drafting_performance-overhaul`).
- **Runtime:** no scheduler, no persistent job table, no idle signal; download tasks in-memory (`SoundCloudDownloader.tasks`, `app/soundcloud_downloader.py:1597-1600`) — same gap as artist-hub OQ9 / T-17. Existing precedent for a persisted `last_sync_ts`: USB play-count sync (`app/playcount_sync.py`).
- **Auth / secrets:** all mutation routes `require_session`; token in keyring, `AuthExpiredError` → 401 `auth_expired` (`app/main.py:4399-4401`); unattended sync depends on `evaluated_soundcloud-persistent-login`. Never log token, never log a playlist `secret_token` URL.
- **Legal / ToU:** own-account likes + playlists = legitimately accessible User Content; persistent local audio = the risk the single-track downloader already accepts (module docstring LEGAL BOUNDARIES, `app/soundcloud_downloader.py`); `access == playable` only; no cross-user aggregation; per-run call cap + `aggressive_mode` not inherited (artist-hub T6).
- **Schicht-A pinning:** `rbox==0.1.7` (`requirements.txt:34`), `mutagen==1.47.0`, `keyring==25.7.0`, `requests==2.33.1` already pinned + used by SC code. No new deps. rbox wheel is Windows-only — empirical rbox checks run on the owner's machine (artist-hub wave-5 pattern, `scripts/dev/rbox_artist_merge_probe.py`).
- **Frontend:** home = `frontend/src/components/SoundCloudSyncView.jsx` (calls at `:313`, `:451-460`, `:490-492`, `:533`, `:567`, `:670`); no react-router; `react-hot-toast` + `confirmModal()`; `SmartPlaylistEditor.jsx` `FIELDS` must stay in sync with `_FIELD_MAP`.

## Dependencies

**None — uses existing stack only.**

- SC listing rides the artist-hub-hardened `_sc_get` pager + keyring token; public-API paths only need the OAuth token already stored.
- Membership ledger + rule table = tables in the artist-hub sidecar (stdlib `sqlite3`, versioned runner from `app/variant_schema.py:59-90`).
- Download reuses `app/soundcloud_downloader.py`; matching `app/external_track_match.py`; tag write `app/audio_tags.py`; smart-list reading `app/live_database.py`.
- Background sync shares artist-hub's `BackgroundTasks` + thread job — explicitly no APScheduler.

## Open Questions

1. **Collection scope.** Own playlists + Likes only, or also liked playlists (`/me/likes/playlists`) and reposts? Owner taste + ToU envelope. Resolvable: X vs Y.
2. **Tree placement.** Adopt the user's folder via `sc_sync_folder_id` (`Libary/Playlists`) vs an app-owned `SoundCloud` folder (artist-hub `Artists` shape)? Keep the `SC_` prefix or plain titles? Owner.
3. **Likes shape.** One playlist `Likes` (where — `Libary/Playlists/Likes`?) or a folder? Owner.
4. **Ledger DDL.** Extend the artist-hub sidecar (`collections.kind ∈ {artist, playlist, likes}` + new `members(collection_id, sc_urn, first_seen, last_seen, removed_at, local_track_id)`) vs the registry (`UNIQUE(sc_track_id)` blocks multi-membership). Resolvable: one DDL.
5. **Removal semantics.** Removed on SC → drop from mirror playlist / keep / move to a `SC removed` list? Same rule for unlike and playlist-removal? Owner default; files never deleted.
6. **Change detection.** Full re-list per run (200/page) vs playlist `last_modified` short-circuit vs likes newest-first early stop — call count per run for 30 playlists + 3 000 likes. Measurable.
7. **⛔ Empirical — sub-genre carrier.** Which fields / values do the owner's `Genres` smart lists key on (Comment chips? Genre? MyTag? Rating 4-5 + BPM buckets)? Dump the rules from a `master.db` copy via `_parse_smart_rules`. Decides Genre-field vs Comment vs MyTag writes. Plus: does rbox 0.1.7 expose any working MyTag write (`_try_call` probes, `app/live_database.py:1106`)?
8. **Rule engine.** Reuse D5 canonical table + `genre_mappings` (1 string → 1 canonical) or a sibling many-tokens → many-targets table? Seeding from smart-list rules + chip vocabulary. Resolvable: schema + a 20-track worked example.
9. **Novel-term UX.** D5 per-term dialog vs per-run Review queue; Auto mode must never block on a dialog. X vs Y.
10. **Backfill.** Apply routing to already-downloaded SC tracks (registry rows) — opt-in one-shot, one metadata call per track? yes/no + cost.
11. **Match rule.** Private `SequenceMatcher ≥ 0.65` (`app/soundcloud_api.py:621`) vs `external_track_match` at the artist-hub-tuned threshold — one shared rule? Plus the O(N·M) fix (normalised-title index). Resolvable: threshold + benchmark.
12. **Job sharing.** One background job for artist + collection kinds (artist-hub T-17 idle signal, call cap) vs separate? Design.
13. **Album-tag hijack.** `sc_playlist_title` → Album (`app/soundcloud_downloader.py:912`): keep / drop / move? A track in 3 playlists gets which? Owner.
14. **Token-keyed caches.** Remove `@lru_cache` on `get_playlists` / `get_likes` (`:403`, `:476`) — artist-hub T-12 — or TTL cache in the sidecar? Decision.
15. **Public API vs api-v2.** Which listing / metadata fields need v2 (`release_date`, `publisher_metadata`, transcodings) vs public (`genre`, `tag_list`, `access`, `last_modified`)? Resolvable: field matrix.
16. **Empirical — Rekordbox re-evaluation.** Do RB smart lists reflect rbox-written Genre / Comment changes without a restart? Does the USB PDB carry Genre + Comment so the CDJ shows them? Resolvable: test on a library copy + `pytest tests/test_pdb_structure.py`.
17. **Empirical — corpus reality.** Distribution of SC `genre` / `tag_list` on the owner's own likes (top-N, % empty, % multi-word) — sets the seed rules and the expected hit rate. Owner-run script with the token.

## Research Plan

- Agent 1 (empirical on a `master.db` copy + codebase): OQ7 + OQ16 — dump the `Genres` smart-list rules via `_parse_smart_rules`, map field / value → playlist; rbox MyTag write probe; RB re-evaluation; PDB genre / comment carry-through. Owner-approved copy, `scripts/dev/` probe like `rbox_artist_merge_probe.py`.
- Agent 2 (web + codebase): OQ1, OQ6, OQ14, OQ15 — public-API likes / playlists endpoints, ordering, `last_modified`, `access`, field matrix public vs v2, cache removal, call budget per run.
- Agent 3 (codebase): OQ2, OQ3, OQ4, OQ5 — sidecar DDL extending artist-hub `collections`, placement / adoption rules, removal semantics, how `SoundCloudSyncEngine` + the five routes + `SoundCloudSyncView.jsx` are absorbed.
- Agent 4 (codebase + web + owner corpus): OQ8, OQ9, OQ10, OQ13, OQ17 — rule engine vs D5, `tag_list` tokenizer, novel-term queue, backfill cost, Album-tag hijack.
- Agent 5 (codebase): OQ11, OQ12 — shared matcher + threshold, O(N·M) fix, one background job for both kinds.

## Idea Verification

Stage 1 Verifier. Dated entries, append-only. PASS / FAIL + ≤40-word reason (checked vs `## Original Idea` + `## Prior Art`).

### YYYY-MM-DD — <PASS|FAIL>
- …

---

> ↓ Stage 2 — `exploring_` (autonomous; no user gate). On Idea-Verifier PASS, `research-draft` advances `drafting_` → `exploring_` directly. `research-explore` runs parallel tiered agents (codebase + web + synthesis per OQ), an Adversarial agent, a Citation-Quality verifier, and a Research-Verifier — one autonomous pass to `evaluated_`.

## Findings / Investigation

### 2026-09-15 — wave 1: codebase surface scan (read-only)

Two parallel read-only scans (SoundCloud / download pipeline; Rekordbox genre / MyTag / smart-list surface) + verification reads of every load-bearing site. Distilled into `## Constraints` + `## Prior Art`; load-bearing results:

- **The feature is half-built and stateless.** `SoundCloudSyncEngine` (`app/soundcloud_api.py:588-800`): `SC_` prefix `:591`, name-only playlist lookup `:634-637`, `sc_sync_folder_id` `:641`, per-run "already in playlist" skip `:691-697`, add-only loop `:701-725`, dead `active_db` fallback `:719-720`, `preview_matches` dry-run `:737-800`. Routes: `sync` (`app/main.py:4364-4404`, `ScSyncReq.playlist_ids + include_likes` `:4360-4361`, `_sync_lock` 409 `:4368`), `preview-matches` `:4412-4455`, `sync-all` `:4458-4490`, `merge` `:4493-4509`, `download-playlist` `:3990-4071` (`is_likes` → `get_likes` `:4005-4007`, `force` wipes registry rows `:4041-4046`, per-track `download_track(..., sc_playlist_title=)` `:4049-4058`). UI `frontend/src/components/SoundCloudSyncView.jsx` (`:313`, `:451-460`, `:490-492`, `:533`, `:567`).
- **Delta download already exists in crude form.** Dedup gate `app/soundcloud_downloader.py:1089-1151`: `registry.is_already_downloaded` → skip the download, **still** link the local track into the `SC_` playlist via `_auto_add_to_playlist` (`:1119-1124`, `:1557-1593`), task status `Linked` / `Skipped` (`:1133`). So "only the new track" today = re-run "Download playlist"; what is missing is the automatic trigger, persisted state, removal, and >500 likes.
- **Likes are capped, deprecated, and cached.** `get_likes` (`app/soundcloud_api.py:476-538`): `@lru_cache` on the token `:476`, `max_tracks=500` `:477`, deprecated `/users/{id}/favorites` + `offset` `:487-488`, synthetic playlist `{"id": "likes", "is_likes": True}` `:527-538`. Public replacement `GET /me/likes/tracks` (≤ 200 / page, `linked_partitioning`) is spec'd and not deprecated.
- **Genre already flows, tags do not.** `_normalize_track` drops `genre` / `tag_list` (`:347-356`); the downloader fetches v2 `/tracks/{id}` separately (`_fetch_sc_metadata` `:820`) and writes `genre` → `TCON` (`:924`), Album = playlist title (`:912`), Comment = permalink; import re-reads the tag (`app/services.py:1325-1372`) → `update_content_genre` (`app/live_database.py:1073-1077`). `tag_list` is read nowhere.
- **Sub-genre has no field; the app can read the smart lists that would consume it.** Carriers: `Comment` (chips `frontend/src/components/RankingView.jsx:9-14`, DB write `app/live_database.py:1014`), `MyTag` (loader `:159-186`, writer speculative `:1090-1210`), `ColorID` / `Rating` (`:1017-1050`). Smart-list XML parsed + evaluated in live mode (`:406-461`, `:785-917`, field map `:834-847`, BPM ×100 `:900-901`); RB smart lists written in XML mode only (`app/database.py:560-577`). `generate_smart_playlists` has By-Artist / By-Label branches, no By-Genre (`app/services.py:674-743`). `MetadataManager` seeds `artists | labels | albums` only (`:899`, `:911`), `genres` creatable on demand (`:918-923`; `tests/test_services.py:129-130`).
- **Registry cannot hold membership.** `download_history` `UNIQUE(sc_track_id)` + single `sc_playlist_title` (`app/download_registry.py:81`, `:94`), `local_track_id` `:93`.
- **Matching is O(N·M) and private.** `_fuzzy_match_with_score` (`app/soundcloud_api.py:604-625`): exact normalised-title short-circuit `:617-618`, else `SequenceMatcher ≥ 0.65` over every local track `:620-623`.
- **Settings surface exists.** `sc_sync_folder_id`, `sc_auth_mode`, `sc_download_format` (`app/services.py:789-791`); SC-scoped routes `/api/soundcloud/settings` (`docs/backend-index.md:135-136`).
- **Web (spec):** SoundCloud OpenAPI `api.yaml` — `/me/likes/tracks`, `/me/likes/playlists`, `/me/playlists`, `/playlists/{urn}/tracks`, `limit` ≤ 200, `linked_partitioning`; Track `genre` / `tag_list` / `label_name` / `bpm` / `key_signature` / `access`; Playlist `last_modified` / `track_count`; `tag_list` = space-separated, multi-word quoted. `release_date` + `publisher_metadata` absent from the public Track schema. `scdl --sync` / `--download-archive` = archive-file precedent for the ledger.
- **Confidence:** high for repo `file:line` (verified by direct reads on 2026-09-15); medium for the spec extract (fetched raw `api.yaml`, not diffed against the live API).

**Unverified (no user data, no live token, Linux container without the Windows-only rbox wheel):** the owner's actual `Genres` smart-list rules (OQ7); whether rbox 0.1.7 has any MyTag write method (OQ7); RB re-evaluation of rbox-written fields (OQ16); the SC `genre` / `tag_list` distribution on the owner's likes (OQ17); live payload shape of `/me/likes/tracks` ordering (OQ6).

## Adversarial Findings

Stage 2 Adversarial-Agent (phase 2). Devil's-advocate — what could go wrong, what assumptions are weak, what dependencies betray us. ≤120 words. Append-only.

### YYYY-MM-DD
- **Weak assumption:** …
- **Failure mode:** …
- **Counter-example:** …

If none survive scrutiny: **"No surviving objections — proceed with caution flags above."**

## Citation Quality

Stage 2 Citation-Verifier (phase 2). Checks every `file:line` ref + URL in `## Findings` exists + says what the Finding claims. PASS / FAIL list. ≤80 words.

### YYYY-MM-DD — <PASS|FAIL>
- PASS: Findings 1, 2, 4 — citations verified
- FAIL: Finding 3 — `app/main.py:123` no such symbol, replace or remove

---

> ↓ Stage 2 phase 2 (autonomous; no user gate) — `research-explore` deepens findings, runs Adversarial + Citation verifiers, then the Research-Verifier gates the whole body before Options-Synthesis advances the doc to `evaluated_`.

## Research Verification

Stage 2 wave-2 verifier over whole research body. ≤120 words. PASS → `evaluated_`; gaps → more Findings.

### YYYY-MM-DD — <PASS|GAPS>
- Coverage of Open Questions: …
- Internal consistency: …
- Citation quality (cross-ref `## Citation Quality`): …
- Adversarial concerns addressed: …

## Options Considered

Stage 2 Synthesis-Agent (phase 2 PASS). Per option: sketch ≤5 bullets, pros, cons, S/M/L/XL, risk, prior-art match.

### Option A — <name>
- Sketch:
- Pros:
- Cons:
- Effort:
- Risk:
- Prior-art match: <slug or "novel">

### Option B — <name>
- Sketch:
- Pros:
- Cons:
- Effort:
- Risk:
- Prior-art match: <slug or "novel">

## Recommendation

Stage 2 Synthesis-Agent (phase 2 PASS). ≤120 words. Which option + what blocks commit + which OQ each Finding answers.

---

> ↓ Stage 3 — `implement/draftplan_`. `research-plan` fills Implementation Plan + Task Queue via 5 agents (Planner, Threat-Modeller, Migration, Perf-Budget, Test-Plan). Reviewer fills Review. On Review PASS, the Mockup+Summary-Agent fills `## Approval Summary` + `## Mockup`, then advances to `approvalgate_`.

## Implementation Plan

Stage 3 Planner-Agent. Concrete enough that someone else executes without re-deriving.

### Scope
- **In:** …
- **Out:** …

### Step-by-step
1. …

### Files touched
Path + role (read / edit / new):
- `<path>` — <role> — <why>

### Testing
High-level (see `## Test Plan` for concrete pytest/cargo cases):
- …

### Risks & rollback
- …

## Threat Model

Stage 3 Threat-Modeller-Agent. Required when feature touches: auth, `require_session`, filesystem (paths in / out), `master.db` writes, network, secrets, user-supplied paths. Otherwise: **"N/A — no security surface."**

### Assets
- … (data, secrets, attacker goal)

### Trust boundaries
- … (which layer trusts which input)

### Threats (STRIDE-light)
| ID | Threat | Mitigation in plan | Test covers |
|---|---|---|---|
| T1 | … | step N / file X | test_… |

### Residual risk
- ≤60 words — what cannot be eliminated, why acceptable.

## Migration Path

Stage 3 Migration-Path-Agent. Required when feature changes: DB schema, file layout, settings/config shape, IPC contract, on-disk caches, USB export bytes. Otherwise: **"N/A — no migration."**

### Before → After
- Data shape today: …
- Data shape after: …
- Existing-data handling: in-place migrate / lazy on read / one-shot backfill

### Backfill / forward-compat
- Migration script: `<file>` (or "no script — schema-additive")
- Old client reads new data: yes/no — how degraded
- Rollback: restore via `<backup>` / re-run reverse migration `<file>`

### User-visible behavior during migration
- … (downtime, progress UI, can app start before complete?)

## Performance Budget

Stage 3 Perf-Budget-Agent. Numbers, not "fast". If feature has no perceptible runtime cost: **"N/A — analysis-only / one-shot."**

| Path | Budget | Measured today | Source |
|---|---|---|---|
| <e.g. POST /api/duplicates/scan> | p95 ≤ 800ms / 50MB peak | … | `tests/perf/…` or "untested" |

### Worst-case scenario
- Input shape: <e.g. 50k tracks, 200 dupes>
- Expected impact: …
- Mitigation if exceeded: …

## API / UX Surface

Stage 3 Planner-Agent. What is added / changed at every layer the user / frontend touches.

### Backend (FastAPI)
- New routes: `<METHOD> <path>` — auth: `require_session`? rate-limited? lock?
- Changed routes: `<METHOD> <path>` — what changed in request/response shape

### Frontend (React)
- New components / hooks / IPC calls (axios + invoke):
- Changed components: …

### Tauri (Rust commands)
- New `#[tauri::command]`s: …
- Changed signatures: …

### CLI / sidecar logs
- New stdout markers (e.g. `LMS_TOKEN=`-style): …

## Telemetry

Stage 3 Planner-Agent. How we know it works after ship. ≤80 words. Otherwise: **"N/A — no runtime behavior to observe."**

- Log markers (`logger.info("op=… …")`): …
- Counters / timing: …
- Health-endpoint surface: …
- User-visible status (toast, statusline, dashboard tile): …

## Test Plan

Stage 3 Test-Plan-Agent. Concrete test cases, one row per. Must cover Threat Model + Migration + Perf budgets.

| ID | Layer | Test file | Case | Covers (Threat / OQ / Step) |
|---|---|---|---|---|
| T1 | py | `tests/test_<area>.py::test_<case>` | … | Threat T1 |
| T2 | rust | `src-tauri/src/audio/.../tests` | … | Step 3 |
| T3 | js | `frontend/src/**/*.test.js` | … | OQ 2 |
| T4 | integration | `tests/test_<integration>.py` | end-to-end happy path | full flow |
| T5 | perf | `tests/perf/<file>.py` (new) | p95 budget vs target | Perf table row N |

## Task Queue

<!--
Small, individually-committable implementation tasks. Written by research-plan (Stage 3),
approved by the user at the Approval Gate. research-implement works ONE task per branch:
routine/<slug>-task-<N>. 1 task = 1 feature = 1 PR. Tick - [x] when the PR is merged.
Keep tasks small — a task too big to review in one PR must be split.
Each task should map back to a Step in ## Implementation Plan and have ≥1 row in ## Test Plan.
-->

- [ ] <task — small, single-purpose, independently testable> — covers Step N, tests T<m>, T<n>

## Review

Stage 3 Reviewer-Agent (`review_`). Unchecked box or rework reason → `rework_`.

- [ ] Plan addresses all goals
- [ ] Plan matches `## Original Idea` — no scope-creep
- [ ] Open questions answered or deferred
- [ ] Prior Art referenced — no duplicated past work
- [ ] Threat Model present + each threat has a test (or N/A justified)
- [ ] Migration Path present + rollback documented (or N/A justified)
- [ ] Performance Budget set + worst-case scenario documented (or N/A justified)
- [ ] API / UX Surface enumerated for every layer touched
- [ ] Telemetry defined for shipped behavior (or N/A justified)
- [ ] Test Plan covers every Threat + every Step + every Perf row
- [ ] Task Queue items are small + independently committable + reference Steps + Tests
- [ ] Dependencies audited — new libs have Schicht-A entries
- [ ] Risk mitigations defined
- [ ] Rollback path clear
- [ ] Affected docs identified (`architecture.md`, `FILE_MAP.md`, indexes, `CHANGELOG.md`)

**Rework reasons:**
- …

## Approval Summary

Stage 3 Mockup+Summary-Agent (after Plan-Reviewer PASS). **Plain user-facing English — NOT Caveman.** This block is what the user reads to decide yes/no. ≤200 words. No `file:line` jargon — describe effects, not internals.

- **What it does:** 1–2 sentences, plain language. What the feature gives the user.
- **What you'll notice:** bullet list of user-visible effects (new button, faster scan, new export option, …).
- **Scope:** N files touched · N tasks · effort S/M/L · risk low/med/high.
- **Rollback:** one line — how it's undone if you dislike it after merge.
- **Mockup:** see `## Mockup` below.

## Mockup

Stage 3 Mockup+Summary-Agent. Adaptive to feature type — decide from `## API / UX Surface`:

- **UI feature** (has frontend components): write a self-contained static wireframe to `docs/research/mockups/<slug>.html` (inline CSS, no build step, no external assets — open in a browser locally). Fill the **UI** block below. Leave the **Backend** block empty/removed.
- **Backend / DSP / USB / DB feature** (no visible UI): fill the **Backend** block with a concrete example — sample API request/response, CLI/log output, or before→after data (metadata tags, USB tree, DB rows). Show the shape the user will actually see. Leave the **UI** block empty/removed.

### UI — mockup file
- `docs/research/mockups/<slug>.html` — <one-line layout + key-interaction description>

### Backend — concrete example
```text
<sample response / CLI output / before→after — the user-visible shape>
```

---

> ⛔ APPROVAL GATE — user `/approve` (→ `accepted_`) or `/reject "<reason>"` (→ `rework_`). The single sign-off: read `## Approval Summary` + `## Mockup`. After approval, nothing is re-researched.
> ↓ Stage 4 — `inprogress_`. `research-implement` builds each Task Queue item via 5 agents (Approach-Probe, Code, Standard-Review, Security-Review, Test-Coverage-Review, Doc-Sync) on a `routine/*` branch. You test + merge the branch yourself.

## PR Log

Stage 4. One row per task PR. `research-implement` appends; user notes merge after local testing.

| Task | Branch | PR | CI | Std Rev | Sec Rev | Test Cov | Doc Sync | Merged |
|---|---|---|---|---|---|---|---|---|
| … | `routine/<slug>-task-N` | #… | pass/fail | pass/fail | pass/fail | pass/fail | pass/fail | YYYY-MM-DD |

## Implementation Log

Stage 4 Code-Agent + Approach-Probe. Dated entries. What built / surprised / changed-from-plan.

### YYYY-MM-DD — Approach Probe (task N)
- Sketches considered: A (…), B (…), C (…)
- Selected: <letter> — why
- Rejected: … — why

### YYYY-MM-DD — Implementation
- Built: …
- Surprised: …
- Deviation from plan: …

---

## Decision / Outcome

Required by `archived/*`. Stage 4 Doc-Sync-Agent populates the checklist; user signs off after testing the branch locally + merging.

**Result**: implemented | superseded | abandoned
**Why**: …
**Rejected alternatives:**
- …

**Code references**: PR #…, commits …, files …

**Performance achieved** (vs `## Performance Budget`):
- <path> — measured p95 / peak — pass/fail

**Telemetry confirmed live**:
- <marker> visible in <logs / dashboard / health endpoint>

**Docs updated** (required for `implemented_`):
- [ ] `docs/architecture.md`
- [ ] `docs/FILE_MAP.md`
- [ ] `docs/backend-index.md` (if backend changed)
- [ ] `docs/frontend-index.md` (if frontend changed)
- [ ] `docs/rust-index.md` (if Rust/Tauri changed)
- [ ] `CHANGELOG.md` (if user-visible)

## Links

- Code: `app/soundcloud_api.py:588-800` (sync engine), `app/soundcloud_downloader.py:1089-1151` (dedup gate), `app/live_database.py:406-461,785-917` (smart-list read), `frontend/src/components/SoundCloudSyncView.jsx`
- External docs: https://github.com/soundcloud/api (OpenAPI `openapi/api.yaml`), https://developers.soundcloud.com/docs/api/rate-limits, https://github.com/scdl-org/scdl
- Related research: library-artist-hub, downloader-unified-multi-source, download-format-setting, soundcloud-persistent-login, external-track-match-unified-module
- Supersedes: none
- Superseded by: none
