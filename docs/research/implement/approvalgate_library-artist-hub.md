---
slug: library-artist-hub
title: Artist Hub — favourite-artist overview, Rekordbox folder sync, SC discovery, artist merge
owner: tb
created: 2026-09-04
last_updated: 2026-09-04
tags: []
related: []
supersedes: []
superseded_by: []
---

# Artist Hub — favourite-artist overview, Rekordbox folder sync, SC discovery, artist merge

> **Caveman+ style.** Fragments, bullets. Drop articles/filler/hedges. No prose paragraphs.
> Word caps are **soft** — recommendations, not hard blocks. Exceed when topic complexity demands; routines may flag excess length but never truncate facts.
> State = folder + filename prefix (not frontmatter). Lifecycle = audit trail. See `../README.md`.
> Routines advance this doc **autonomously** by state. **One** user gate: `approvalgate_` — read `## Approval Summary` + `## Mockup`, then `/approve` or `/reject`. After approval you test the finished branch locally and merge it yourself.
> Section ownership: each `> ↓ Stage X — <agent>: …` marker names the agent that fills the section. Don't write into a section before its stage.

## Lifecycle

- 2026-09-04 — `research/idea_` — created from template (user idea, interactive session)
- 2026-09-04 — `research/drafting_` — Stage 1 filled interactively (Prior Art, Problem, Goals incl. 4 owner decisions, Constraints + Dependencies from a codebase scan, 14 OQs, 5-agent Research Plan)
- 2026-09-04 — `research/exploring_` — Idea-Verifier PASS; promoted. Stage-2 wave 1 (codebase surface) already banked in `## Findings`
- 2026-09-04 — `research/exploring_` — wave 2 (SoundCloud): OQ5 + OQ6 both ANSWERED from the official OpenAPI spec; wave-1 claim "API lacks these endpoints" corrected — they exist, the client never called them. New OQ15 (ToU aggregation) raised for the Approval Gate.
- 2026-09-04 — `research/exploring_` — wave 3 (Rekordbox write + merge): OQ3 + OQ4 ANSWERED, OQ1 + OQ2 PARTIAL (7 empirical checks listed, 5 need no user data). Found a live bug (`remove_track_from_playlist` calls rbox with the wrong arity), an undocumented second artifact (`masterPlaylists6.xml`), a USB re-copy blast radius (new OQ16), and a `_file_sha1` cliff in the shipped applier. Two wave-1 Constraints claims corrected.
- 2026-09-04 — `research/exploring_` — wave 4 (rbox Rust source via docs.rs; upstream repo is a 404) + wave 5 (**empirical, owner-approved, against a copy** of the real `master.db`). OQ1 + OQ2 now ANSWERED. Decisive result: `update_content_artist` does **not** bump the content row's `rb_local_usn`, `update_content(item)` does → the merge writer changes. Live bug reproduced (`delete_playlist_song` arity) and the fix recipe proven. `search_str` is unpopulated in this library → that risk is closed.
- 2026-09-04 — `research/evaluated_` — Stage 2 closed: Adversarial (7 concerns, incl. the `update_content` full-row clobber), Citation PASS, Research-Verifier PASS, 3 Options + Recommendation = **Option A** (sidecar store + projection engine) with 4 commit-blockers
- 2026-09-04 — `implement/draftplan_` — Stage 3 filled: plan, threat model (8 threats), migration, perf budget, API/UX surface, telemetry, 21 test rows, 18-task queue across 3 milestones (M1 usable without SoundCloud)
- 2026-09-04 — `implement/review_` — Plan-Reviewer: 15/15 boxes, PASS, no rework reasons
- 2026-09-04 — `implement/approvalgate_` — ⛔ **AWAITING /approve**. Two owner decisions bundled into the Approval Summary: USB re-copy after a merge (OQ16) and the SC catalogue-enumeration boundary (OQ15)
- 2026-09-04 — `implement/approvalgate_` — owner answered both gate questions **as refinements, not as picks**: (a) merge propagates to the audio-file tags and the USB exporter **merges folders** instead of re-copying → new Step 5b, tasks T-11a/T-11b, threats T9/T10, perf rows, 7 new test rows; (b) catalogue is fetched **on artist selection**, and the missing list splits into "definitely theirs" (uploader-id equality) vs "remixes by others" → threat T11, task T-13 extended. Blockers 3+4 rewritten accordingly. Mockup updated. Still awaiting `/approve`.

## Original Idea (verbatim — never edit)

<!--
Written ONCE by the user. 1–3 sentences, raw. NEVER edited after — not by routines, not by the user.
Every verifier (Stage 1 idea-check, Stage 2 research-check, Stage 3 plan-review, Stage 4 doc-sync) checks
its work against this block. It is the anchor against scope-creep and misreading.
-->

Ich möchte ein Feature bauen, welches mir hilft einen Überblick über meine Lieblingskünstler und deren Musik zu haben und der download/localsync soll gut sein und bequem. Ich möchte in Rekordbox einen Folder Artist nennen wollen. ich will eine Liste an Artists haben, Unter soundcloud oder so soll es ein feature Artists geben, Es soll auf möglich sien vorschläge anzu zeigen, welche auf den lokalen künstlern basiert und der mit den meisten tracks am weitesten oben außer er ist schon hinzugefügt. Es muss auch eine Einfache möglichkeit geben künstler zu mergen, es kann ja einfach zu mehrfachen künstlern vom gleichen durch kleinschreibung kommen yk

Kleiner seiten gedanke,  so Ordner wie Artist und automatisch erkennen kann man ja weiter denken zu laben/Libary/Setlists/genres etc

---

> ↓ Stage 1 — `drafting_`. `research-draft` fills Problem → Research Plan via 4 agents (Scout, Prior-Art, Risk-Surface, Worker). Verifier fills Idea Verification.

## Prior Art

- **Active — overlap, must not duplicate:** [inprogress_metadata-name-fixer](../implement/inprogress_metadata-name-fixer.md) — normalises the artist/title **string per track** (8 malformed classes, `feat.`, reversed fields). Shipped: `app/metadata_fixer/{detector,schema,applier}.py` (25 tests). **Boundary:** name-fixer fixes a track's field; this doc merges artist **entities**. **Reuse:** `schema.py` undo-log + `applier.py` 6-step atomic mutation are the merge write-through template (OQ4). Casing/punctuation rules are shared, not re-derived.
- **Active — consumer relationship:** [accepted_downloader-unified-multi-source](../implement/accepted_downloader-unified-multi-source.md) — single-track, multi-source, quality-ranked download. Explicit non-goal there: *"Playlist-level imports as the primary path in v1"*. Artist-Hub batch download is exactly that layer → it **consumes** the downloader per track, never forks it.
- **Active — shared matcher:** [inprogress_external-track-match-unified-module](../implement/inprogress_external-track-match-unified-module.md) — `app/external_track_match.py` shipped (`parse_version_tag`, `extract_title_stem`, fuzzy, fingerprint; 26 tests). The "do I already own this SC track?" diff (OQ8) uses it.
- **Active — adjacent, not overlapping:** [accepted_recommender-rules-baseline](../implement/accepted_recommender-rules-baseline.md) + [accepted_recommender-similar-tracks](../implement/accepted_recommender-similar-tracks.md) + [inprogress_recommender-taste-llm-audio](../implement/inprogress_recommender-taste-llm-audio.md) — recommend **tracks**. This doc recommends **artists**. Tier-2 discovery may later borrow their taste vector; v1 does not depend on it.
- **Active — dependency:** [evaluated_soundcloud-persistent-login](../research/evaluated_soundcloud-persistent-login.md) — background artist sync needs a token that survives without re-login. Silent-refresh (Option A) is a soft prereq for the background-sync goal.
- **Active — perf constraint:** [drafting_performance-overhaul](../research/drafting_performance-overhaul.md) — documents unpaginated `/api/library/tracks`, no list virtualization, blocking startup. Artist list + per-artist track list must not add another unpaginated view.
- **Active — write-safety:** [exploring_db-write-lock-retrofit](../research/exploring_db-write-lock-retrofit.md) — known `_db_write_lock` coverage gaps. Every new `master.db` writer here (merge, playlist projection) must go through `db_lock()` from `app/database.py`.
- **Shipped — hard constraint:** [implemented_security-api-auth-hardening](../archived/implemented_security-api-auth-hardening_2026-05-17.md) — all mutation routes behind `Depends(require_session)`. Applies to every route in this doc.
- **In-code prior art — half-built "By Artist" playlists:** `app/services.py:664-741` (`LibraryTools.generate_smart_playlists`) already builds an artist folder tree in Rekordbox, threshold 5. **Broken for our purpose:** groups on the **raw** `track["Artist"]` string (`app/services.py:672-676`), bypassing `_split_artists` / `_normalize_artist_name` entirely → exactly the casing/variant split the Original Idea complains about. Artist-Hub must absorb or replace it, not run beside it (double-writer risk).
- **In-code prior art — merge already exists, but alias-only:** `POST /api/metadata/merge` (`app/main.py:995-1004`) → `MetadataManager` writing `metadata_mappings.json`, categories `artists|labels|albums` (`app/services.py:894-927`); UI = GitMerge hover button in the artist grid (`frontend/src/components/MetadataView.jsx:74-91,182`). Never touches `master.db`. Owner decision 2026-09-04 = write through to Rekordbox → this doc **upgrades the existing merge**: keep the button + mapping file as the alias layer, add the RB write + undo-log.
- **In-code prior art — stubbed artist↔SC link:** `app/sidecar.py:39-49` (`get_artist_link`/`set_artist_link`, JSON `app_data.json`, keyed by artist **name**) + route `POST /api/artist/soundcloud` `app/main.py:2714-2717` — **route body has the storage call commented out, returns a fake success**, and no frontend calls it. Half of OQ7 is pre-designed; finish it instead of inventing a new binding.
- **In-code prior art — normalisation already written twice:** `_split_artists` `app/live_database.py:579-587` (dup `app/database.py:291-298`), `_normalize_artist_name` `app/live_database.py:589-618` (dup `app/database.py:300+`). Merge-candidate detection reuses these; de-duplicating them is a cleanup candidate, not this doc's job.
- **External precedent:** Rekordbox has no artist-favourites concept — only per-track artist strings + manual playlist folders; its "Related Tracks"/Cloud Library Sync do not group by artist. Serato has Crates, no artist entity. So: the folder-projection shape (folder `Artists` + one playlist per artist) is the native-compatible way to express this on CDJ hardware, which reads playlists, not app state.

## Problem

Library has no artist-level view. Artist exists only as a per-track string — no entity, no favourites, no "what else does this artist have". Casing/spelling variants split one artist into several. Keeping a favourite artist's catalogue complete = manual SC-profile checking + manual download + manual Rekordbox playlist upkeep. Cost of not doing: catalogue gaps found at the gig, dupe artists in RB browse, hours of manual bookkeeping.

## Goals / Non-goals

**Goals**
- **Artist entity + favourites list.** Own artist record (canonical name + aliases + links), user-curated favourites list. **Metric:** favourite artist resolves to all local tracks incl. every alias variant; 0 tracks lost on merge.
- **Per-artist overview.** Local tracks vs. remote (SC) catalogue, diff = "missing". **Metric:** artist page renders local+missing split for a 200-track artist < 1 s from cache.
- **"Definitely theirs" vs "remixes by others"** (owner, 2026-09-04): selecting an artist lists tracks that are provably from that artist's own SC account, **separated** from tracks where they are only named in a title/credit (`… (X Remix)`, `feat. X`) and uploaded by someone else. Both lists are viewable and downloadable; only the first is auto-queued. **Metric:** 0 tracks from a foreign uploader appear in the "definitely theirs" list on a 200-track corpus.
- **Rekordbox projection** (owner, 2026-09-04): **one folder `Artists`, one playlist per favourite artist**, flat. Playlist = all local tracks of the artist (alias-merged). Refreshed on sync. **Metric:** folder + N playlists appear in Rekordbox after sync; re-sync is idempotent (no dupe playlists, no dupe entries).
- **Merge writes through to Rekordbox** (owner, 2026-09-04): merging `boys noize` + `Boys Noize` + `BOYS NOIZE` rewrites `DjmdArtist`/`DjmdContent` in `master.db` directly. **Every merge is journalled + revertible** (undo-log pattern already shipped in `app/metadata_fixer/schema.py`) and preceded by a dry-run preview — direct write, never blind write. **Metric:** revert restores byte-identical pre-image rows; `pytest tests/test_pdb_structure.py` stays green after a mass merge.
- **Merge propagates to the files and to the stick** (owner, 2026-09-04, refining the earlier decision): the artist tag is rewritten **inside the audio files** (`app/audio_tags.py`, the path `metadata_fixer/applier.py` already owns), and the USB exporter **merges the variant folders** on the stick instead of re-copying the tracks. **Metric:** after a merge, `ffprobe` on a touched file shows the canonical artist; the next USB sync moves 0 bytes of audio across the wire for a pure artist rename.
- **Merge-candidate detection.** Auto-surface variant groups (casefold, punctuation, `&`/`and`, whitespace, smart-quote, `feat.`-contamination). **Metric:** ≥ 95 % precision on a seeded variant corpus; one-click merge per group.
- **Suggestions, 2 tiers** (owner, 2026-09-04): **Tier 1 local backlog** — artists present in the library, ranked by owned-track count desc, already-favourited excluded. **Tier 2 external SC discovery** — related/adjacent artists not in the library, seeded from the favourites. **Metric:** Tier 1 needs 0 network calls; both tiers exclude already-added.
- **Download / local-sync convenience** (owner, 2026-09-04): per-artist **Update** button (manual, immediate) + **background sync while the app is open and idle** (no sync under load), mode configurable in Settings. **Metric:** background sync never runs during analysis/export/playback load; manual Update completes a 1-artist diff in < 5 s.
- Reuse, don't rebuild: download goes through the existing SC downloader / unified-downloader path; matching through `app/external_track_match.py`; normalisation shares rules with `metadata-name-fixer`.

**Non-goals** (deliberately out of scope)
- Label / genre / setlist folder projection — side-thought from the Original Idea. Schema + projection engine designed **generic** (`collection_kind`), but only `artist` implemented here. Follow-up doc.
- New download backend. This doc consumes the existing/planned downloader, it does not extend it.
- Artist bio / images / social-graph browsing. Overview = tracks, not a fan page.
- Non-SC artist sources (Spotify/Bandcamp/Beatport artist pages) in v1.
- Auto-merge without user confirmation. Detection is automatic; the merge click is not.
- Rewriting the per-track `artist` **string** for reasons other than a merge — that is `metadata-name-fixer`'s job. (A merge itself **does** now rewrite tags — owner decision 2026-09-04.)

## Constraints

- **Artist is not an entity today.** Only a per-track string. `DjmdArtist` reached exclusively via `db.get_artists()` → flattened `id → name` dict (`app/live_database.py:128`), resolved per track at `app/live_database.py:192`. The literal `DjmdArtist` / `ArtistID` appears **nowhere** in `app/`.
- **UI artist ids are unstable — hard blocker.** `art_{i}` is the index into a sorted list, rebuilt on every library load (`app/live_database.py:492-528`, XML twin `app/database.py:235-263`). Any favourites/alias store keyed on that id silently corrupts on the next scan → own store must key on a **canonical name or own stable id**, never `art_{i}`.
- **RB folder + playlist writing already exists.** `create_playlist_folder` / `create_playlist` at `app/live_database.py:1306-1325` (`"ROOT"` → `None` at `:1308`), track link `create_playlist_song` `:1328-1333`. Facade: `app/database.py:1046-1060` (`create_playlist(..., tracks=[...])`), `app/database.py:992-996` (`create_folder`). Routes `app/main.py:1308-1311`, `:1464-1478`.
- **Concurrency — only the facade is locked.** `_db_write_lock` (RLock) `app/database.py:23`, `db_lock()` `:27-41`; auto-serialised method list `app/database.py:1238-1262` covers `create_playlist`/`create_folder`/`add_track_to_playlist`. The **live-layer** mutators `app/live_database.py:1306,1328` are unguarded — calling `db.active_db.<mutator>` bypasses the lock. Every writer in this doc goes through the **facade**, never `active_db`. ⚠️ Two wave-1 claims corrected in wave 3: `app/soundcloud_downloader.py:1572-1578` is **not** a live offender (it prefers the facade and only falls back to `active_db` if the method is missing, which it never is — dead branch), and `tests/test_library_format_swap.py:489-580` is **not** a general enforcement net (its AST walk parses only `app.library_format_swap`, `:512-517`) → a new merge module needs its own lock test.
- **Artist write path is per-track, not per-entity.** Only `update_content_artist(tid, ...)` exists (`app/live_database.py:1057-1061`). A merge = N per-track writes, not one row update → batching + lock-hold time is a real budget item (OQ11).
- **SC API — the needed endpoints exist upstream but are NOT implemented in our client** (corrected 2026-09-04 wave 2; the first pass wrongly implied the API lacks them). Present: `/me` `app/soundcloud_api.py:279-292`, `get_user_profile` `:295-321`, `/resolve` `:359-402`, `/users/{id}/playlists` `:404-475`, `/users/{id}/favorites` (max 500) `:477-540`. **Not wired up: `/users/{urn}/tracks`, `/users/{urn}/related`, `/users/{urn}/reposts/*`** — all three are documented public-API endpoints (see Findings wave 2). Search exists only in Rust (`src-tauri/src/soundcloud_client.rs:241`) and serves export, not discovery. Shared pager/retry to reuse: `_sc_get` `app/soundcloud_api.py:181`.
- **SC auth.** Token in OS keyring (`library_management_system` / `sc_token`, `app/main.py:78-80`), header `Authorization: OAuth <token>` `app/soundcloud_api.py:275`, `AuthExpiredError` `:147`. PKCE flow is Rust-side (`src-tauri/src/soundcloud_client.rs:172,210,412`). Background sync therefore inherits the re-login problem tracked in `evaluated_soundcloud-persistent-login`.
- **Sidecar-DB pattern is fixed.** 6 sidecars exist (`auth.db`, `download_registry.db`, `variants.db`, `popularity.sqlite`, `track_vectors.db`, `metadata_fixer_log.db`). Shape: `sqlite3.connect(check_same_thread=False)` + `WAL` + `synchronous=NORMAL` + **module-private** `threading.Lock` — never the global `_db_write_lock` (`app/auth_db.py:12-17`, `app/variant_schema.py:7-9`). Only real migration runner to copy: `app/variant_schema.py:59-90`.
- **Auth.** Every mutation route behind `Depends(require_session)` (`app/auth.py`) — non-negotiable, `implemented_security-api-auth-hardening`.
- **Perf / capacity.** No pagination on the library track route and no list virtualization (`drafting_performance-overhaul`). Artist list + per-artist track list must be paginated/virtualised or they inherit the same hotspot. `artist_view_threshold` already filters the artist list (`app/live_database.py:513`, default `app/services.py:781`).
- **No job infrastructure.** No Celery/RQ/APScheduler, no persistent job table, no WebSocket/SSE — all job state in-process, lost on sidecar restart. Best existing template: phrase batch (`app/main.py:5121-5188`: `job_id`, `BackgroundTasks`, module dict + asyncio lock, 409 on double-start, `total/done/percent/eta_seconds/cancel_requested`) + `frontend/src/components/usePhraseBatch.js` 1500 ms poll.
- **No idle/load signal exists.** Nothing exposes "app open, not under load" — background sync must derive it (running-job counts across `_phrase_jobs`, SC `self.tasks` `app/soundcloud_downloader.py:1597-1620`, `app/import_tracker.py`).
- **Downloads land at** `MUSIC_DIR/SoundCloud/{artist}/{title}.{ext}` (`app/soundcloud_downloader.py:175-213`, `MUSIC_DIR = ./music` `app/config.py:11`), Windows 250-char truncation `:196-212`. Post-download chain (analysis → `_auto_import` → ANLZ → playlist) `:1425-1557` — reuse as-is, do not fork.
- **Legal.** SC downloader boundaries stay: no `snipped:true`, respect 401/403, no DRM bypass, host allowlist `app/soundcloud_downloader.py:260,265`. Artist-batch download must not become a bulk-scraper — rate-limit and honour per-track licensing exactly like the single-track path.
- **Frontend.** No react-router; workspaces + tabs in `frontend/src/main.jsx:123-192`, render switch `:1075-1170`, all views `lazy()`. Artists tab already exists (`frontend/src/main.jsx:131`, `lib-artists`). Style reference is **`frontend/src/components/MetadataView.jsx`** — `frontend/src/components/LibraryView.jsx` is **dead code** (`docs/frontend-index.md:77,102`), do not copy it. No `alert()/confirm()` — `react-hot-toast` + `confirmModal()`/`promptModal()`.

## Dependencies

**None — uses existing stack only.**

- SC artist-tracks + discovery ride the existing `_sc_get` pager (`app/soundcloud_api.py:181`) + keyring token. No new HTTP client.
- Artist store = new SQLite sidecar following `app/variant_schema.py:59-90`. Stdlib `sqlite3`, no ORM, no new dep.
- Download reuses `app/soundcloud_downloader.py`; matching reuses `app/external_track_match.py`; undo-log reuses `app/metadata_fixer/schema.py`.
- Background sync uses `BackgroundTasks` + threads like the phrase-batch job — explicitly **no** scheduler dep (APScheduler etc.); adding one would be a Schicht-A decision, so it stays out.

## Open Questions

> Stage-1 codebase scan (2026-09-04) closed feasibility for RB folder writing and settled the sidecar-store pattern — see `## Constraints`. Remaining questions are the real unknowns.

1. ~~**RB folder idempotency + visibility.**~~ **ANSWERED waves 4+5.** rbox bumps USN itself (+2 per create) and updates `masterPlaylists6.xml` (hex ids) — nothing for us to bump. No uniqueness at any level and `get_playlist_by_path` silently returns the first duplicate ⇒ **own id-map**, verified per sync. Diff-in-place unblocked by the proven one-arg `delete_playlist_song(row.id)` fix. Only the visual "does RB render it after a restart" remains, and it is no longer load-bearing. *(superseded detail from wave 3:)* No lookup-or-create exists anywhere; `app/services.py:718-720` already duplicates artist playlists on re-run. rbox exposes no USN setter and `uuid` is dropped by both repo readers → **own id-map** is the answer. Diff-in-place is **blocked** until `remove_track_from_playlist` (`app/live_database.py:1342`) is fixed. Remaining: does rbox bump USN internally, does RB show it after restart → empirical 1 + 5.
2. ~~**Does a per-track artist rewrite merge the entity?**~~ **ANSWERED waves 4+5.** Yes for the link, no for the entity: `update_content_artist` creates the canonical artist on demand and repoints the track, but leaves the old row orphaned **and the content row's `rb_local_usn` stale** — so the merge must go through `update_content(item)` instead, which bumps USN + `updated_at`. `search_str` is unpopulated in this library, so nothing to maintain. Orphan deletion = explicit opt-in. *(superseded detail from wave 3:)* `update_content_artist` takes a **name** and almost certainly creates-on-demand. `delete_artist` exists but nulls Remixer/OrgArtist/Composer/Lyricist as a side effect and leaves no tombstone. Field key must be exactly `"Artist"` (silent no-op otherwise). Remaining: does the orphan linger in RB browse, and does `search_str` need maintaining → empirical 2 + 3 + 4 + 5.
3. ~~**Merge blast radius.**~~ **ANSWERED wave 3** — `master.db` alone covers RB display **and** USB export; no tag rewrite, no ANLZ rewrite. **But** the artist name is baked into the USB destination path and into `_track_hash`, so the next USB sync re-copies every merged track's audio. Surface that in the merge dialog.
4. ~~**Undo-log reuse.**~~ **ANSWERED wave 3** — reusable with 3 deltas (`entity_kind`+`entity_id`+`after_json`, nullable `rule_id`, an INSERT path in `revert_run`) and one pre-image fix (capture `artist_id`, not just the name). Ordering holds at N=5000. Real cliff is `_file_sha1` running unconditionally — skip when `write_tags=False`.
5. ~~**SC artist catalogue.**~~ **ANSWERED wave 2** — `GET /users/{urn}/tracks`, limit 200, `linked_partitioning`, `access=playable`; reposts on a separate path; metadata endpoints currently unthrottled; `track_type` does not exist on the public API; filter rule agreed. See Findings.
6. ~~**SC related-artists.**~~ **ANSWERED wave 2** — `GET /users/{urn}/related` exists (shipped 2026-05-19) and returns ranking fields inline. Primary = that endpoint; fallback = uploader co-occurrence in already-fetched playlists/likes (0 network calls) when the collection comes back empty. See Findings.
7. **Local↔SC binding.** Finish `app/sidecar.py:39-49` + the stubbed `POST /api/artist/soundcloud`: permalink match / fuzzy / manual pin? Keyed by artist **name** today — does that survive a merge (alias → canonical rewrite)? False-bind cost is high. Resolvable: matching rule + confidence threshold + override UX.
8. **"Missing track" diff threshold.** `app/external_track_match.py:337-372` fuzzy-matches `"artist - title"` at **0.65**, tuned for a different job. Which threshold stops flagging owned remixes/edits as missing? Resolvable: threshold + seeded corpus.
9. **Idle signal.** Nothing exposes "app open, not under load" (NOT PRESENT). Compose from running-job counts (`_phrase_jobs` `app/main.py:5121+`, SC `self.tasks` `app/soundcloud_downloader.py:1597-1620`, `app/import_tracker.py`) plus playback/CPU? Resolvable: named signal set + threshold + hard "never during export/analysis" rule.
10. **Artist-store schema.** New sidecar following `app/variant_schema.py:59-90`. Open: tables for artists (canonical + aliases + sc_link + sync_mode) with a generic `collection_kind` for the label/genre/setlist follow-up, and **what the stable key is** given `art_{i}` is unusable (`app/live_database.py:520`). Resolvable: one DDL.
11. **Projection cost.** 50 favourites over a 10k-track library: rewrite every artist playlist per sync, or diff? What is the `_db_write_lock` hold time, does it stall the UI? Resolvable: measured budget + chunking rule.
12. **Tier-1 ranking cost.** Track counts already fall out of `_finalize_ui_metadata` (`app/live_database.py:492-528`) — enough, or does the backlog list need its own cache at 10k–50k tracks? Resolvable: measured.
13. **Fate of `generate_smart_playlists` "By Artist"** (`app/services.py:664-741`). Replace it, feed it from the artist store, or accept two writers in the same RB folder space? Resolvable: pick one + migration for anyone who already ran it.
16. ~~**USB re-copy after a merge.**~~ **RESOLVED by owner 2026-09-04: neither accept nor avoid — merge the folders.** The exporter treats a pure artist rename as a folder merge/move on the stick, not a re-copy. New work in the USB differ; see Task T-12a. *(original framing:)* A merge changes `<usb>/Contents/<Artist>/...` and `_track_hash`, so the next USB sync relocates every affected track's audio. Options: accept it, teach the USB differ to treat a pure-artist rename as a move, or offer "merge without touching the USB layout". Resolvable: pick one — but the cost belongs in the Approval Summary.
15. ~~**⛔ Owner decision — SC ToU aggregation boundary.**~~ **RESOLVED by owner 2026-09-04:** catalogue fetch is **on artist selection**, user-initiated — narrower than the guardrail set that was offered. No speculative pre-fetch for non-favourited artists. The remaining guardrails (one discovery hop, TTL cache, per-run call cap, `aggressive_mode` not inherited) stand. *(original framing:)* Does systematic per-artist catalogue enumeration + stored diff stay inside the accepted-risk envelope the single-track downloader already occupies? Mitigations listed in Findings wave 2. **Not resolvable by research — belongs in the Approval Summary.**
14. **Migrate `metadata_mappings.json`?** Existing artist aliases live in `MetadataManager` (`app/services.py:894-927`). Import as pre-seeded merges, or keep the JSON as the alias layer and store only RB-write history? Resolvable: one-way import vs. dual-source decision.

## Research Plan

- Agent 1 (codebase + empirical on a `master.db` copy): RB write surface — OQ1 + OQ2 + OQ11. Folder/playlist idempotency, USN semantics, whether a per-track rewrite collapses the artist entity, lock-hold budget.
- Agent 2 (codebase): merge safety — OQ3 + OQ4 + OQ14. Blast radius across DB/tags/ANLZ/USB-PDB, undo-log reuse at large N, alias-map migration.
- Agent 3 (web + codebase): SoundCloud — OQ5 + OQ6. `/users/{id}/tracks` shape, pagination, rate limits, repost/set filtering; related-artists availability + fallback derivation.
- Agent 4 (codebase): identity + diff — OQ7 + OQ8. Finish the stubbed artist↔SC link, tune the `external_track_match` threshold.
- Agent 5 (codebase): runtime + schema — OQ9 + OQ10 + OQ12 + OQ13. Idle-signal composition, sidecar DDL with generic `collection_kind`, ranking cost, fate of `generate_smart_playlists`.

## Idea Verification

### 2026-09-04 — PASS

- All 6 asks in `## Original Idea` map to a Goal: overview → Goal 2; RB folder → Goal 3 (owner shape confirmed); artist list → Goal 1; SC artists feature → Goals 2+7; suggestions ranked by track count minus already-added → Goal 6 Tier 1; merge for casing dupes → Goals 4+5.
- Side-thought (label/library/setlist/genre) captured as Non-goal **with** a generic `collection_kind` carve-out, so the follow-up is a projection rule, not a rewrite.
- No scope-creep: download stays a consumer of `accepted_downloader-unified-multi-source`; string-level fixes stay with `inprogress_metadata-name-fixer`.
- Owner decisions recorded 2026-09-04 (RB folder shape, merge writes through to RB, 2-tier suggestions, per-artist Update button + idle background sync).
- Risk flagged for Stage 2, not blocking: merge is a direct `master.db` mutation over N tracks — undo-log + dry-run are mandatory Goal text, not optional.

> ↓ Stage 2 — `exploring_` (autonomous; no user gate). On Idea-Verifier PASS, `research-draft` advances `drafting_` → `exploring_` directly. `research-explore` runs parallel tiered agents (codebase + web + synthesis per OQ), an Adversarial agent, a Citation-Quality verifier, and a Research-Verifier — one autonomous pass to `evaluated_`.

## Findings / Investigation

### 2026-09-04 — wave 1: codebase surface scan (read-only)

Full detail distilled into `## Constraints` + `## Prior Art` with `file:line`. Load-bearing results:

- **No artist entity anywhere.** `DjmdArtist` is read-only through `db.get_artists()` (`app/live_database.py:128`); the literal `DjmdArtist`/`ArtistID` appears nowhere in `app/`. UI artist ids are `art_{i}` list indexes, rebuilt per library load (`app/live_database.py:492-528`) → **unusable as a key**. Store must own a stable id.
- **RB folder + playlist writing already works** (`app/live_database.py:1306-1333`, facade `app/database.py:992-996,1046-1060`). OQ1 reduces from "is it possible" to "is a re-sync idempotent + does it survive an RB restart".
- **Only the facade holds `_db_write_lock`** (`app/database.py:1238-1262`); live-layer mutators are unguarded and an existing caller already bypasses it (`app/soundcloud_downloader.py:1572-1576`). Rule for this feature: facade only.
- **Three half-built pieces of this exact feature already exist** — artist folder playlists on raw strings (`app/services.py:664-741`), an alias-only merge with a working UI button (`app/main.py:995-1004`, `frontend/src/components/MetadataView.jsx:74-91,182`), and a stubbed artist↔SC link whose route returns a fake success (`app/sidecar.py:39-49`, `app/main.py:2714-2717`). Artist-Hub consolidates them; building beside them creates double writers.
- **SC client cannot fetch an artist's catalogue.** Implemented: `/me`, profile, `/resolve`, `/users/{id}/playlists`, `/users/{id}/favorites`. Not wired up: artist tracks, reposts, related. ~~OQ5/OQ6 genuinely open~~ → **both closed in wave 2**; the endpoints exist upstream, the client just never called them.
- **No job infrastructure and no idle signal.** All job state in-process, lost on restart; best template is the phrase batch (`app/main.py:5121-5188` + `frontend/src/components/usePhraseBatch.js`). Background sync must compose its own load signal.
- **Frontend has an Artists tab but no artist page.** `lib-artists` (`frontend/src/main.jsx:131`) renders inside `MetadataView.jsx` (grid at `:167-201`). Style reference is `MetadataView.jsx`; `frontend/src/components/LibraryView.jsx` is dead code — name trap.

### 2026-09-04 — wave 2: SoundCloud API (OQ5 + OQ6 both ANSWERED)

Source: SoundCloud OpenAPI spec (`github.com/soundcloud/api/blob/master/openapi/api.yaml`), developer docs, dated release notes. Public API + OAuth app token — **no api-v2 needed** for any of it.

**OQ5 — artist catalogue: solved.**
- `GET /users/{user_urn}/tracks` (spec `:903`). `limit` default 50 / **max 200**; `sort=asc|desc` (added 2026-07-19); `access` array, **default `playable,preview`**.
- Pagination = `linked_partitioning=true` → `next_href` cursor. `offset` is spec-deprecated (deprecation post 2015-03-02) — our existing callers still send it (`app/soundcloud_api.py:415,488`).
- `/tracks` is **own uploads only**. Reposts are separate: `/users/{urn}/reposts/tracks` (spec `:971`), `/reposts/playlists` (`:991`), both added 2026-03-24.
- **Rate limits** (developers.soundcloud.com/docs/api/rate-limits): play-stream 15 000/24 h on `/tracks/:id/stream` **only**; client-credentials 50/12 h per app, 30/h per IP; **metadata endpoints: "No limit is currently enforced"**. 429 body carries `errors[].meta.rate_limit` + `reset_time`; **no documented `Retry-After` header** — `app/soundcloud_api.py:243` reads only that header and otherwise blind-sleeps 10 s.
- Call budget: 50 favourites ≈ **50–100 metadata calls** per full refresh, 0 stream calls.
- ⚠️ **`track_type` does not exist on the public API** — not on the read schema (`Track` `:2312-2472`) nor the upload schema. Any DJ-set filter assuming it is wrong; it is an api-v2/retired-v1 field.
- `access` is the public-API equivalent of the downloader's `snipped` gate: `playable` = full, `preview` = snippet, `blocked` = metadata only (spec `:2440-2451`). Request `access=playable` so previews never enter the "missing" list.
- **Mix/set filter rule:** `access == playable` AND `streamable` AND `sharing == public` AND `duration <= 15 min` AND NOT keyword-regex (`podcast|dj set|live set|radio show|episode|ep. NN|b2b|boiler room|essential mix|guest mix|mixtape|takeover|residency`). Bare `\bmix\b` deliberately **excluded** from the regex — "Original Mix"/"Extended Mix" are exactly what we want; long-form is caught by duration. `downloadable` = ranking signal, never a filter (matches `app/soundcloud_downloader.py:1081-1086`). Excluded items go into a collapsed "Mixes & sets (N)" section, never silently dropped.

**OQ6 — related artists: the endpoint exists.** Wave-1 assumption was wrong.
- `GET /users/{user_urn}/related` — *"related artist recommendations for a user"* (spec `:806-820`), shipped **2026-05-19**, i.e. 3.5 months old.
- Returns `User` objects already carrying `track_count`, `followers_count`, `playlist_count`, `permalink_url`, `urn` (spec `:2058+`) → the "most tracks at top" ranking needs **zero** follow-up calls.
- Costed alternatives for 50 favourites: **A** `/related` = 50 calls, best signal. **B** followings-of-favourites = 50 calls, noisier, `linked_partitioning` undocumented on that path. **C** uploader co-occurrence in playlists/likes we already fetch = **0 new calls**, offline-safe, weak for true discovery. **D** `/tracks/{urn}/related` pivoted to uploader = 250 calls, no unique value.
- **Recommendation: A primary, C fallback** — C costs nothing and covers A's weak spot (niche artist → plausibly empty `collection`). Empty must degrade to C silently, never surface an error. B and D rejected.

**Client refactor required before adding endpoints** (order matters — three new endpoints on top of the current duplication is the wrong sequence):
1. `app/soundcloud_api.py:236-240` raises `AuthExpiredError` on **every** 404. A deleted/private/renamed artist legitimately 404s → today that pops a bogus "re-login" toast per dead artist. Needs `auth_404: bool` opt-out + a typed `NotFoundError`.
2. One shared `_sc_paginate` — `get_playlists:421-437` and `get_likes:492-524` hand-roll the same `next_href` loop with divergent bugs.
3. Parse the 429 body (`reset_time`) instead of the undocumented `Retry-After`.
4. **No `@lru_cache` on artist fetches** — `:403,:476,:541` cache keyed on `auth_token`: a background sync would never see new uploads, and the OAuth token becomes a process-lifetime cache key. TTL cache belongs in the artist sidecar (OQ10).
5. Keep the `time.sleep(0.3)` spacing (`:470,:524`) for batch loops; 50 artists = 15 s background, irrelevant for the 1-artist Update button.

**Free drift findings (pre-existing, not caused by this feature):** `/users/{id}/favorites` (`app/soundcloud_api.py:487`) is `deprecated: true` in the spec (`:823`) — replacement `/users/{urn}/likes/tracks` (`:934`). Numeric IDs (`:414,:487`) deprecated in favour of string URNs 2025-04-23; still working, but new call sites should build `soundcloud:users:{id}`.

**⚠️ Owner decision needed at the Approval Gate — ToU aggregation.** The SC API Terms of Use prohibit aggregating platform data beyond legitimately-accessible User Content, prohibit apps designed to persistently store User Content, and prohibit offline audio access. The existing single-track downloader already sits on that boundary as an accepted project risk; Artist-Hub **adds** systematic per-artist catalogue enumeration plus a stored diff, which reads closer to "aggregate". Defensibility levers to build in: user-initiated only, restricted to explicitly favourited artists, at most one related-hop (no transitive crawl), TTL cache not a permanent mirror, hard per-run call cap, and `aggressive_mode` (`app/soundcloud_downloader.py:511-513`) **not** inherited by the batch path. Not an implementation call.

**Unverified (no live token used — read-only pass):** live payload shape of `/users/{urn}/related` for a niche artist; whether `linked_partitioning` works on `/followings`/`/followers` (spec lists only `limit`); whether numeric ids still resolve on the newest paths; any undocumented soft throttle; whether `/users/{id}/tracks` returns the authenticated user's own private uploads.

### 2026-09-04 — wave 3: Rekordbox write + merge semantics (OQ3 + OQ4 ANSWERED, OQ1 + OQ2 PARTIAL)

Source: repo, rbox type stubs (`.venv/Lib/site-packages/rbox/_rbox.pyi`), SQL strings extracted from the compiled `_rbox.cp311-win_amd64.pyd`, pyrekordbox for schema semantics. No user library touched.

**OQ1 — folder/playlist projection: PARTIAL.**
- `create_playlist_folder(name, parent_id, seq)` `_rbox.pyi:2384`, `create_playlist(...)` `:2373`, both via `create_playlist_node` `:2361`. Caller-settable columns `NewDjmdPlaylist` `:1397-1411` — **no `uuid`, no `usn`**; rbox generates them, caller cannot influence.
- `attribute` 0=List / 1=Folder / 4=SmartList (`:1391`, enum `:192`). Repo's inverted `ATTR_TO_TYPE` (`app/live_database.py:412`) matches the create-cache write `:1319` — **not** a bug.
- Sibling `Seq` is resequenced by rbox with a `ROW_NUMBER() OVER (ORDER BY Seq)` window UPDATE on `djmdPlaylist` (same shape for `djmdSongPlaylist.TrackNo`).
- **No lookup-or-create anywhere.** `app/main.py:1307-1310` and `:1464-1481` create unconditionally → two same-named siblings on a second call. `app/services.py:688-712` gets the *folder* right (idempotent name+parent lookup) but the per-artist playlist loop `:718-720` creates **unconditionally** → re-running `generate_smart_playlists` duplicates every artist playlist. Confirms the double-writer risk.
- rbox has the primitives the facade hides: `get_playlist_by_path` `:2341`, `get_playlist_children` `:2333`. Facade passthrough NOT FOUND. `DjmdPlaylist.uuid` `:1364` exists but **both repo readers drop it** (`app/live_database.py:452-458`, `:1315-1320`) → unusable as a key today.
- ⛔ **`remove_track_from_playlist` is broken.** `app/live_database.py:1342` calls `delete_playlist_song(str(pid), str(tid))` — **two** args; rbox's signature takes **one**, the `DjmdSongPlaylist.id` (`_rbox.pyi:2422`). Always TypeError, swallowed at `:1343`, returns False. The comment at `:1339-1341` admits the signature was guessed. Diff-in-place re-sync is impossible until this is fixed. Correct form: `get_playlist_songs(pid)` `:2345` → match `content_id` → `delete_playlist_song(row.id)`, or batch `delete_playlist_songs([...])` `:2426`.
- **USN:** global counter = `agentRegistry` row `localUpdateCount`, per-row `rb_local_usn` set to its own increment (pyrekordbox `db6/registry.py:196-247`, `db6/database.py:657-674`). **rbox exposes only `get_local_usn()` `:1959` — no setter.** Not trigger-maintained either (the binary's only triggers are diesel's `updated_at`). Whether rbox's Rust path bumps it internally: **NOT DETERMINABLE from code** → empirical check 1.
- 🆕 **Second artifact nobody in this repo knows about:** rbox also maintains `%APPDATA%/Pioneer/rekordbox/masterPlaylists6.xml` (`playlist_xml_path()` `:1947`, module `rbox/src/masterdb/playlist_xml.rs`) and **degrades to a warning, not an error**, when it cannot ("Couldn't update playlist XML, file not found!"). Repo grep for `masterPlaylists|playlist_xml` → NOT FOUND. Any backup taken before a projection/merge must include it. Also unused: `rbox.is_rekordbox_running()` (`rbox/__init__.py:16`) already guards analysis writes with a 409 (`app/main.py:3767,3797,3851`) but guards **no** playlist or metadata writer.

**OQ2 — does a per-track rewrite merge the entity: PARTIAL.**
- `update_content_artist(id, name)` takes a **name**, not an id (`_rbox.pyi:2117`; repo call `app/live_database.py:1057-1059`). Create-on-demand is strongly indicated (`get_artist_by_name` `:2045` + `create_artist` `:2053` ship together; `add_track` `app/live_database.py:911-936` depends on it or every download would lose its artist) but the Rust body is unreadable → empirical check 2.
- ⚠️ **Field key must be exactly `"Artist"`.** `"ArtistName"` is UI-only synthesis (`app/main.py:1036`, `:2672`), and `update_track_metadata` **returns True for an unrecognised key** (`app/live_database.py:1073-1074`) → silent no-op. `app/metadata_fixer/applier.py:60` names `"ArtistName"` in its docstring as an example — a live trap. The merge path needs an explicit field allowlist so this cannot fire.
- **Orphan removal = hard delete + reference detach, no tombstone.** `delete_artist(id)` `:2061`; SQL extracted verbatim from the binary nulls **five** columns before deleting: `ArtistID`, `RemixerID`, `OrgArtistID`, `ComposerID`, `Lyricist`. So it also clears Remixer/OrgArtist/Composer links you never meant to touch → repoint those first (`update_content_remixer` `:2121`, `update_content_original_artist` `:2125`, `update_content_composer` `:2129` — repo calls **none** of them). `rb_local_deleted` (`:498`) is not used by this path ⇒ no tombstone ⇒ Cloud Library Sync never learns of the removal.
- Whether an orphan lingers in RB artist browse: NOT ANSWERABLE from code → empirical check 5.
- ❓ **`search_str` is the real unknown.** `DjmdArtist.search_str` `:514`, `DjmdContent.search_str` `:664`, `src_artist_name` `:740` are denormalised. Repo grep → **NOT FOUND** (nothing reads or writes them). If `update_content_artist` does not refresh them, merged tracks stay findable in Rekordbox search under the **old** name → empirical check 4.

**OQ3 — blast radius: ANSWERED. `master.db` alone is enough. No tag rewrite, no ANLZ rewrite.**
- USB export artist chain is pure DB: `encode_artist_row` `app/usb_pdb.py:380-397` ← `PdbBuilder.add_artist` `:705` ← `write_export_pdb` `:1014` ← `app/usb_one_library.py:817`, whose dict is `{int(a.id): a.name for a in db.get_artists()}` `:663`. The PDB track row carries only the FK (`app/usb_pdb.py:625`, offset `0x44`) — no artist string.
- No export module imports `audio_tags`/`mutagen` for metadata; **no path rewrites the artist tag during import or export**.
- ANLZ carries no artist — the only string tag is `PPTH` (file path); repo writer emits none (`app/anlz_writer.py:9-11`).
- 🆕 **But the real merge cost is the USB stick, and the doc missed it.** The artist name is baked into the USB destination path — `_dest_audio_path` `app/usb_one_library.py:904-912` = `<usb>/Contents/<Artist>/<Title>/<file>` (also `app/usb_manager.py:1895`) — and `_track_hash` includes `ArtistName` (`app/usb_manager.py:1068`). ⇒ After a merge, every affected track is dirty in the USB diff and **the next USB sync re-copies and relocates its audio**. Merging a 500-track artist means half a gig of re-copy at the next export, not a metadata blip. Must be surfaced in the merge confirm dialog.

**OQ4 — undo-log reuse: ANSWERED. Reusable, 3 schema deltas + 1 perf cliff.**
- Delta 1 — **`entity_kind` needed.** Track repoints fit the existing DDL (`app/metadata_fixer/schema.py:84-97`). The artist-row delete does not: no `content_id`, no DjmdContent field. Add `entity_kind TEXT NOT NULL DEFAULT 'content'` + `entity_id TEXT` + `after_json` (so a delete can be re-INSERTed on revert).
- Delta 2 — `rule_id INTEGER NOT NULL` `:88` is fixer-specific → nullable or sentinel.
- Delta 3 — **revert is single-field only.** `revert_run` `applier.py:144-164` restores `{field: before_value}` (`:151`); no INSERT path to resurrect a deleted `DjmdArtist`. Also `set_run_status(RUN_REVERTED)` fires unconditionally at `:163` → a partially-failed revert is recorded as complete.
- **Ordering at N=5000 holds.** `get_mutations(reverse=True)` orders `created_at DESC, rowid DESC` (`schema.py:221`); `rowid` breaks same-timestamp ties. Journal the artist delete **last** so reverse replay re-inserts it **first**.
- ⚠️ **Pre-image shape is wrong for a merge.** `before_json` is `db.get_track_details(cid)` (`applier.py:114`, `:133`) = the UI dict (`app/live_database.py:908-909`), not the DjmdContent row, despite the comment at `schema.py:92`. It carries `"Artist"` (the name) but **not `artist_id`** → revert can restore a name but not the original entity link. Capture `item.artist_id` explicitly.
- **Perf: the journal is not the cliff** — measured on a synthetic replica of the DDL at N=5000 with 947-byte rows: per-row commit 338 ms vs one transaction 190 ms (1.8×), ~7 MiB. Negligible.
- ⛔ **The cliff is `_file_sha1`** (`applier.py:79-94`): called **twice per row** (`:116`, `:135`) and **unconditionally, even when `write_tags=False`** (`:108`, `:123`). It reads the whole audio file. 5000 AIFFs at ~63 MiB ⇒ **≈ 630 GiB of disk reads** for a merge that writes zero bytes to disk. Skip it entirely when `write_tags=False` — artist merges never touch files (OQ3). Second cost: `db_lock()` acquired/released **per row** (`applier.py:99-100`); batch in chunks of ~200.

**Empirical checks still outstanding** — 1–4 and 7 need **no user data** (synthetic throwaway db in a scratch dir); 5–6 need a **copy** of the library with Rekordbox closed, and must include `masterPlaylists6.xml` in the copy:
1. (synthetic) folder+playlist+song create → read `get_local_usn()` and `rb_local_usn` before/after → does rbox bump USN at all. **Highest value, lowest risk.**
2. (synthetic) `create_artist` → point content → `update_content_artist` → `get_artists()` → create-on-demand + does the old row survive.
3. (synthetic) `delete_artist` → re-read content row → confirm the detach-then-delete SQL incl. Remixer/OrgArtist/Composer nulling.
4. (synthetic) read `search_str` before/after `update_content_artist` → decides whether the merge must maintain it.
5. (library **copy**) one folder+playlist create, then open Rekordbox against the copy → appears without a USN bump? survives restart? does an orphan artist still show in artist browse?
6. (library **copy**) run the sync twice → are duplicate same-name siblings tolerated or shown twice.
7. (no db) call `remove_track_from_playlist` in live mode and read the log → expect the TypeError at `app/live_database.py:1342`.

### 2026-09-04 — wave 4: rbox Rust source (docs.rs) — USN + write-guard semantics

`github.com/dylanljones/rbox` is a **404** — PyPI/crates.io advertise it as the source but the repo is gone. No README beyond PyPI, no CHANGELOG, no issue tracker. docs.rs serves the complete Rust source, which is the only upstream evidence available: `docs.rs/crate/rbox/0.1.7/source/src/masterdb/`.

- **USN bumps live in the model layer, not `database.rs`.** `NewDjmdArtist::insert` does `AgentRegistry::increment_local_usn(conn)` → `UPDATE agentRegistry SET int_1 = int_1 + delta WHERE id = 'localUpdateCount'`.
- **`create_playlist` / `create_playlist_folder` / `create_playlist_song` bump by +2**, with the source comment *"1 for creating, 1 for renaming from 'New Playlist'"*. pyrekordbox does the same trick in pure Python (*"Then update with correct name for correct USN"*) — so +2 is Rekordbox-faithful. The two libraries **disagree** on add-song (+2 vs +1); both are reverse-engineered, neither proven.
- ⛔ **`DjmdContent::set_*_id` writes a bare `diesel::update` with NO USN bump and NO `updated_at`.** Audited all of them: `set_artist_id`, `set_album_id`, `set_remixer_id`, `set_original_artist_id`, `set_composer_id`, `set_genre_id`, `set_label_id`, `set_key_id`, `set_path` — none bump. `DjmdContent::update` (the `ModelUpdate` path) **does**. ⇒ **`update_content_artist` — the repo's only artist writer (`app/live_database.py:1057-1061`) — leaves the content row's `rb_local_usn` stale.**
- **Write guard is free.** `assert_write_mode()` (`if !unsafe_writes && is_rekordbox_running() { Err(RekordboxRunning) }`) is called from **47** write methods. `set_unsafe_writes(true)` disables **only** the process-name check — no locking, no WAL handling. pyrekordbox refuses outright with no override.
- **`MasterDb::new(path)` sets `plxml_path = None` when `masterPlaylists6.xml` is not beside the db**, and `insert_playlist` then **silently skips** the XML update (`let _ = pl_xml.dump()` discards errors) while `rename`/`delete` at least warn. Use `open()`/`from_options`.
- **No UNIQUE constraint anywhere in `djmdPlaylist`** — not on `Name`, `ParentID` or `UUID`; `ID` is the sole PK. UUID is freshly minted per create ⇒ **not** usable as a re-run key.
- Artists do have library-level name identity: `create_artist_if_not_exists` → `find_by_name` (exact, **case-sensitive**) → reuses. So our merge cannot create duplicate artist rows, but it always orphans the old one.
- `rb_local_deleted` semantics: pyrekordbox's own docs say **"Unknown"**; neither library ever writes or filters it. Third-party consensus is "tombstone for cloud sync", but the one precise claim enumerates `djmdContent`/`djmdGenre`/`djmdMyTag`/`djmdSongMyTag` — **`djmdArtist` is not in that list**. Orphan-artist behaviour in the RB browse is undocumented everywhere; the closest analogue is genre, where the **track-filter pane hides orphans but the metadata-edit dropdown shows them** (Pioneer community thread, RB 6.4.2→6.7.1), and Pioneer's own answer is *"Rekordbox does not delete the data"*. Coverage gap: Reddit/djtechtools were unreachable (403 / CAPTCHA), so "not found" there means unsearched.

### 2026-09-04 — wave 5: EMPIRICAL, run against a copy of the real library (owner-approved)

Method: `master.db` + `-wal` + `-shm` + `masterPlaylists6.xml` copied to a scratchpad (SHA-256 of the copy verified identical to the original), Rekordbox confirmed closed before the copy and `rbox.is_rekordbox_running()` = `False` at run time. **The real library was never opened for writing** (SHA-256 re-verified unchanged afterwards). Reproducible via `scripts/dev/rbox_artist_merge_probe.py --db <copy>` — it refuses the real library path and refuses to run while Rekordbox is open. Library: 4719 content rows, `localUpdateCount` = 414258 at start. Copy deleted after the run.

| # | Check | Result |
|---|---|---|
| 7 | `delete_playlist_song(pid, tid)` | ⛔ **`TypeError: PyMasterDb.delete_playlist_song() takes 1 positional arguments but 2 were given`** — the bug at `app/live_database.py:1342` is real and reproducible |
| 10 | `get_playlist_songs(pid)` → `delete_playlist_song(row.id)` | ✅ works, USN +1, song removed — **the fix recipe is proven** |
| 1 | USN on create | folder **+2**, playlist **+2**, song **+2**; `rb_local_usn` written on each new row (414260 / 414262 / 414264). Matches the Rust source. |
| 6 | Idempotency | ⛔ **Two identically-named folders under `root` both created, no error.** `get_playlist_by_path(['X'])` then silently returns **the first**. Confirms: own id-map, dedupe ourselves. |
| 2 | `update_content_artist(cid, "New Name")` | ✅ creates the artist row on demand (global USN +1, new row gets `rb_local_usn`), repoints `content.artist_id`, **old artist row survives as an orphan**. ⛔ **`content.rb_local_usn` unchanged — 330569 before AND after.** |
| 4 | `search_str` | ✅ **Non-issue in this library.** `DjmdContent.search_str`, `DjmdArtist.search_str` and `src_artist_name` are all `None` — Rekordbox never populated them here. Nothing to maintain. |
| 3 | `delete_artist(id)` | Nulls `ArtistID`, `RemixerID`, `ComposerID` on the referencing content row (verified all three were repointed at the test artist and all three came back `None`), deletes the row, global USN +1. `OrgArtistID` pointing at a *different* artist was left alone. **Content rows' `rb_local_usn` stays stale after the detach.** |
| 8 | `update_content(item)` with a modified `artist_id` | ✅ **Bumps `content.rb_local_usn` (292918 → 414270) and sets `updated_at`.** |
| 9 | `get_playlist_by_path` / `get_playlist_children` | Both work; `children('root')` = 7. Facade passthroughs worth adding. |
| — | `masterPlaylists6.xml` | ✅ rbox **did** update it (31042 → 32191 bytes). Node ids are **hex**: `37501150` → `Id="23C38DE"`, `175782530` → `Id="A7A3A82"`. Folders carry `Attribute="1"`, playlists `Attribute="0"`. Names are **not** in the XML. |

**Load-bearing conclusion — the merge must not use `update_content_artist`.** It is the only artist writer in the repo today (`app/live_database.py:1057-1061`) and it leaves every touched content row's `rb_local_usn` stale, which is what Rekordbox uses for change tracking and cloud sync. `update_content(item)` with `item.artist_id` set to the canonical artist bumps the USN and `updated_at` properly. Route: resolve/create the canonical artist once (`get_artist_by_name` → `create_artist`), then `update_content` per track.

**Second conclusion — orphan deletion stays OFF by default.** `delete_artist` works, but it hard-deletes with no tombstone, detaches Remixer/Composer as collateral, and leaves the content rows' USN stale. Since `search_str` is unpopulated here and the genre analogue suggests the RB **filter pane is reference-driven**, an orphan artist most likely disappears from the browse column on its own. Offer deletion as an explicit opt-in ("also remove the empty artist entry"), never as part of the default merge.

**Third conclusion — projection identity.** No uniqueness at any level, `get_playlist_by_path` silently picks the first duplicate ⇒ the artist sidecar owns `artist_key → playlist_id`, verified per sync with `get_playlist_by_id`; `(Name, ParentID)` is used exactly once, to adopt a pre-existing `Artists` folder. And `masterPlaylists6.xml` must be beside the db (it is, in production) or playlist creation silently desyncs it — assert `playlist_xml_path()` is not `None` at startup.

## Adversarial Findings

### 2026-09-04

- **`update_content(item)` writes the WHOLE row.** Wave 5 picked it as the merge writer because it bumps the USN — but it is a full-row update, not a field patch. A stale `item` silently clobbers every other column (BPM, key, comment, colour, rating) with whatever we read minutes ago. **Mitigation is mandatory, not optional:** re-read `get_content_by_id(cid)` **inside** `db_lock()`, mutate only `artist_id`, write immediately. Any design that batches "read 5000 rows → write 5000 rows" is a data-loss bug.
- **rbox is unmaintained and unauditable.** `github.com/dylanljones/rbox` is a 404 — no repo, no issues, no changelog. Every `master.db` write in this feature goes through a compiled Rust wheel whose source only survives on docs.rs. A silent behaviour change on the next version breaks the merge with no upstream to report to. `scripts/dev/rbox_artist_merge_probe.py` is the mitigation — it must run before any rbox bump.
- **`/users/{urn}/related` is 3.5 months old.** No deprecation history, but no track record either. Tier-2 discovery must degrade to the zero-call local fallback on an empty collection **and** on any non-200, never surface an error.
- **The USB re-copy may make the merge net-negative.** A merge is cheap in the DB and expensive on the stick (OQ16). A user who merges 10 artists before a gig triggers a multi-GB re-copy at the worst possible moment. The confirm dialog has to state it in bytes, not in prose.
- **Orphan-artist behaviour is undocumented worldwide.** Wave-4 found no source, and the genre analogue splits by UI surface. Any claim that merged duplicates "disappear from Rekordbox" is unverified. Ship with orphan deletion **off**, describe the outcome honestly.
- **`is_rekordbox_running()` is a process-name check, not a lock.** rbox guards 47 write methods with it, but a user who opens Rekordbox mid-merge races us. Guard at the start of a run **and** re-check per chunk; abort the run cleanly rather than half-writing.
- **Counter-example to "the sidecar is the source of truth":** the user can rename or delete the `Artists` folder inside Rekordbox at any time. The id-map then points at a dead row. Every sync verifies each stored id with `get_playlist_by_id` and re-adopts by name before assuming it is gone.

## Citation Quality

### 2026-09-04 — PASS

- PASS: Findings waves 1-5 — repo `file:line` refs spot-checked against source; rbox stub refs verified in `.venv/Lib/site-packages/rbox/_rbox.pyi`; SC endpoints verified against the official OpenAPI spec; wave-5 numbers come from a logged run, not inference.
- CORRECTED (wave 3, already applied): `app/soundcloud_downloader.py:1572-1578` re-read as a dead fallback branch, not a live lock bypass; `tests/test_library_format_swap.py:489-580` re-read as module-scoped, not a general enforcement net.
- WEAK (flagged, non-load-bearing): orphan-artist UI behaviour rests on a genre analogue in a Pioneer community thread, not on artist evidence. Reddit/djtechtools unreachable (403/CAPTCHA) — "not found" there means unsearched.

---

> ↓ Stage 2 phase 2 (autonomous; no user gate) — `research-explore` deepens findings, runs Adversarial + Citation verifiers, then the Research-Verifier gates the whole body before Options-Synthesis advances the doc to `evaluated_`.

## Research Verification

### 2026-09-04 — PASS

- **OQ coverage:** 1-6 ANSWERED (1+2 empirically), 7-14 are design calls resolved in `## Recommendation`, 15+16 are owner decisions deliberately deferred to the Approval Summary. No OQ left silently open.
- **Internal consistency:** wave-1 claims that later waves disproved were corrected in place, not left standing (SC endpoint availability, lock-bypass offender, enforcement-test scope).
- **Citations:** PASS with one flagged-weak, non-load-bearing item.
- **Adversarial:** all seven concerns carry a named mitigation in the plan; the `update_content` full-row hazard is promoted to a commit-blocker rather than a note.
- **Empirical basis:** the load-bearing merge decision rests on a measured run against a copy of the real library, reproducible via `scripts/dev/rbox_artist_merge_probe.py`.

## Options Considered

### Option A — Sidecar artist store + projection engine

- Sketch: new `artists.db` sidecar (pattern `app/variant_schema.py:59-90`) holding canonical artist + aliases + SC binding + per-artist sync mode + `artist_key → rb_playlist_id` map, with a generic `collection_kind` column. Projection writes folder `Artists` + one playlist per favourite through the **facade**. Merge repoints tracks with `update_content(item)` under `db_lock()`, journalled in the extended metadata-fixer undo log. Absorbs `generate_smart_playlists` "By Artist".
- Pros: stable key (survives the `art_{i}` reshuffle); per-artist state has somewhere to live; id-map solves the no-uniqueness problem; one schema serves the label/genre/setlist follow-up; reuses four shipped modules instead of forking them.
- Cons: a seventh sidecar DB; a migration for anyone who already ran the old artist-playlist generator; most code of the three options.
- Effort: **L**
- Risk: Medium — mitigated by the empirical probe and by orphan-deletion staying opt-in.
- Prior-art match: `inprogress_analysis-remix-detector` (sidecar + migration runner), `inprogress_metadata-name-fixer` (undo log), `inprogress_external-track-match-unified-module` (matcher).

### Option B — Extend `metadata_mappings.json`

- Sketch: keep `MetadataManager` (`app/services.py:894-927`) as the single store; add favourites, SC links and sync mode as new JSON categories beside `artists|labels|albums`.
- Pros: smallest diff; the merge UI already writes there; no new DB, no migration.
- Cons: no id-map (JSON cannot safely hold Rekordbox playlist ids that must be verified per sync); no TTL cache for SC catalogues; whole-file rewrite per change is not concurrency-safe against a background sync; no schema evolution path for the label/genre follow-up.
- Effort: **M**
- Risk: High — the concurrency hole shows up exactly when background sync ships.
- Prior-art match: `app/services.py:894-927` (the thing being extended).

### Option C — Rekordbox-native, no app state

- Sketch: the `Artists` folder in `master.db` **is** the favourites list. Read it back on every load; no sidecar at all.
- Sketch: merge stays a pure `master.db` operation; suggestions computed live from the library.
- Pros: zero migration; nothing to keep in sync; the user can curate favourites inside Rekordbox itself.
- Cons: nowhere to store the SC binding, sync mode, last-sync timestamp, or catalogue cache — which is most of the feature; every read hits `master.db`; two identically-named folders are indistinguishable (wave 5); the user renaming a playlist silently renames a "favourite".
- Effort: **S**
- Risk: High — cannot express the Original Idea's download/local-sync half at all.
- Prior-art match: novel.

## Recommendation

**Option A.** B fails on concurrency the moment background sync lands; C cannot hold the SC binding or sync state, so it cannot deliver the download half of the Original Idea. A's one good idea is borrowed from C: the `Artists` folder is **adoptable**, not owned — if it already exists, adopt it by `(Name, ParentID)` once, then track it by id.

Resolves the remaining design OQs: **OQ7** finish the stubbed `app/sidecar.py:39-49` binding, keyed by the store's own artist id (not the name, so it survives a merge); **OQ8** raise the `external_track_match` threshold from 0.65 to a tuned value on a seeded corpus before the missing-diff ships; **OQ9** idle = no running job across the three trackers + nothing exporting; **OQ10** one sidecar with `collection_kind`; **OQ12** reuse the counts from `_finalize_ui_metadata`, no second cache; **OQ13** absorb `generate_smart_playlists` "By Artist"; **OQ14** one-way import of `metadata_mappings.json` artist aliases as pre-seeded merges.

**Four commit-blockers:**
1. `update_content(item)` re-reads inside the lock and mutates only `artist_id` — full-row clobber is a data-loss bug, not a style issue.
2. `remove_track_from_playlist` (`app/live_database.py:1342`) is fixed first — diff-in-place projection is impossible without it.
3. `_file_sha1` never runs where it buys nothing: skipped entirely when `write_tags=False`, and whole-file verification is **opt-in above 250 tracks**. The tag pre-image is journalled either way, so revert is correct without it — whole-file hashing only adds byte-identity *proof*, at ~63 MiB of reads per track per hash.
4. The merge confirm dialog states all three effects up front: N tracks rewritten in `master.db`, N audio files re-tagged, and which folders merge on the stick.

> ↓ Stage 3 — `implement/draftplan_`. `research-plan` fills Implementation Plan + Task Queue via 5 agents (Planner, Threat-Modeller, Migration, Perf-Budget, Test-Plan). Reviewer fills Review. On Review PASS, the Mockup+Summary-Agent fills `## Approval Summary` + `## Mockup`, then advances to `approvalgate_`.

## Implementation Plan

### Scope

- **In:** artist entity + favourites store (sidecar); merge (detection → dry-run → `master.db` write → revert); Rekordbox projection (folder `Artists`, one playlist per favourite, idempotent); Tier-1 local backlog suggestions; SC artist catalogue + missing-diff + batch download through the existing downloader; Tier-2 SC discovery; per-artist Update button + idle background sync; absorbing `generate_smart_playlists` "By Artist".
- **Out:** label/genre/setlist projection (schema carries `collection_kind`, no UI); new download backend; artist bios/images; non-SC artist sources; auto-merge without confirmation; per-track artist-string repair (that is `metadata-name-fixer`).

### Step-by-step

1. **Unblock the primitives.** Fix `remove_track_from_playlist` (`app/live_database.py:1342`) to the proven one-arg form; add facade passthroughs for `get_playlist_by_path` / `get_playlist_children`; surface `uuid` in `_load_playlists` (`app/live_database.py:452-458`) so the projection can hold a second identity.
2. **Extend the undo log.** `app/metadata_fixer/schema.py`: `entity_kind` (default `content`), `entity_id`, `after_json`, `rule_id` nullable. `applier.py`: an INSERT path in `revert_run`, honest partial-revert status, and `_file_sha1` skipped when `write_tags=False`.
3. **Artist store.** `app/artist_store/schema.py` — sidecar `artists.db`, WAL + module-private lock + versioned migration runner mirroring `app/variant_schema.py:59-90`. Tables: `collections(id, kind, canonical_name, sort_key)`, `aliases(collection_id, alias, source)`, `links(collection_id, provider, remote_id, permalink, confidence)`, `sync_state(collection_id, mode, last_sync_at, last_error)`, `projection(collection_id, rb_playlist_id, rb_uuid, last_projected_at)`, `catalogue_cache(collection_id, payload_json, fetched_at)`.
4. **Registry.** `app/artist_store/registry.py` — resolve library artist strings to store rows through the existing `_split_artists` / `_normalize_artist_name`; favourites CRUD; Tier-1 backlog = counts from `_finalize_ui_metadata` (`app/live_database.py:492-528`), descending, favourited excluded.
5. **Merge engine.** `app/artist_store/merge.py` — candidate grouping (casefold, punctuation, `&`/`and`, whitespace collapse, smart-quote fold); `preview()` pure; `apply()` per chunk of ~200 under one `db_lock()`: **re-read `get_content_by_id` inside the lock, mutate only `artist_id`, `update_content(item)`**, journal each row. Then **rewrite the artist tag in the file** via `app/audio_tags.py` (owner, 2026-09-04) using the applier's existing `write_tags` path — tag pre-image always journalled, whole-file SHA-1 verification opt-in (see Perf). Orphan `delete_artist` only when explicitly requested, journalled last.
5b. **USB folder merge** (owner, 2026-09-04). A pure artist rename must not re-copy audio. Add a **relocation pass** ahead of the copy phase in `app/usb_one_library.py` / `app/usb_manager.py`: for a track whose only diff is `_dest_audio_path` (`app/usb_one_library.py:904-912`), `os.replace()` within the volume instead of copy; merge into an existing canonical folder; prune the emptied variant folders. Two traps to handle explicitly: a **case-only** rename (`boys noize` → `Boys Noize`) needs a two-step rename through a temp name on Windows/exFAT, and a name collision inside the target folder must fall back to copy-and-verify rather than clobber. `_track_hash` (`app/usb_manager.py:1068`) still flags the track dirty — that is correct, the pass changes *how* it is resolved, not *whether*.
6. **Projection engine.** `app/artist_store/projection.py` — adopt-or-create folder `Artists` by `(Name, ParentID)` once, then track by id; per artist verify `get_playlist_by_id`, re-adopt by name if dead, else create; diff songs in place (add missing, remove stale via the fixed primitive). `rbox.is_rekordbox_running()` guard at run start **and** per chunk.
7. **Routes.** All mutations behind `Depends(require_session)`; all `master.db` writers through the facade.
8. **Frontend.** `ArtistHubView` replaces the artist branch of `MetadataView`; merge dialog carries the USB re-copy cost in bytes; projection panel with last-synced.
9. **Absorb + import.** Retire `generate_smart_playlists` "By Artist" (`app/services.py:664-741`); one-way import of `metadata_mappings.json` artist aliases as pre-seeded merges.
10. **SoundCloud.** Harden `_sc_get` first (404 opt-out, shared paginator, 429 body, no token-keyed `lru_cache`), then `get_user_tracks` / `get_related_artists`; bind artist ↔ SC user; missing-diff via `app/external_track_match.py` at a tuned threshold; batch download delegates per track to `app/soundcloud_downloader.py`.
11. **Background sync.** Idle signal composed from the three job trackers; job record + polling mirroring the phrase batch (`app/main.py:5121-5188`, `frontend/src/components/usePhraseBatch.js`).

### Files touched

- `app/live_database.py` — edit — fix removal arity, expose `uuid`.
- `app/database.py` — edit — facade passthroughs, add new writers to the auto-serialised list (`:1238-1262`).
- `app/metadata_fixer/{schema,applier}.py` — edit — undo-log deltas + sha1 skip.
- `app/artist_store/{__init__,schema,registry,merge,projection,sync}.py` — new — the feature.
- `app/soundcloud_api.py` — edit — `_sc_get` hardening, `get_user_tracks`, `get_related_artists`.
- `app/sidecar.py` — edit — retire the artist-link JSON in favour of `links`.
- `app/main.py` — edit — routes (via `route-architect`).
- `app/services.py` — edit — retire "By Artist", expose the alias import.
- `app/audio_tags.py` — read/edit — artist-tag write path reused by the merge.
- `app/usb_one_library.py`, `app/usb_manager.py` — edit — relocation pass so an artist rename moves folders on the stick instead of re-copying.
- `frontend/src/components/ArtistHubView.jsx` + `artistHub/*` — new; `frontend/src/main.jsx`, `MetadataView.jsx` — edit — mount + hand off.
- `frontend/src/api/api.js` — edit — client calls.
- `tests/test_artist_store_*.py`, `tests/test_artist_merge.py`, `tests/test_artist_projection.py` — new.
- `docs/{backend,frontend}-index.md`, `docs/FILE_MAP.md`, `docs/MAP*.md`, `CHANGELOG.md` — edit — doc sync.

### Testing

- Merge: dry-run writes nothing; apply is byte-revertable; full-row clobber regression (a concurrent BPM edit survives a merge).
- Projection: two syncs produce one folder and N playlists, not 2N; a user-deleted playlist is re-created; a user-renamed folder is re-adopted once.
- Locking: every new `master.db` writer sits inside `db_lock()` — its own AST test, since the format-swap one is module-scoped.
- `pytest tests/test_pdb_structure.py` green after a mass merge.

### Risks & rollback

- **rbox behaviour drift** — `scripts/dev/rbox_artist_merge_probe.py` before any bump.
- **Merge regret** — every run is journalled; revert restores the pre-image `artist_id`.
- **Projection regret** — delete the `Artists` folder in Rekordbox; the store re-adopts or recreates on the next sync. Nothing else in the library is touched.
- **Feature-level rollback** — revert the merge commits; `artists.db` is a sidecar, deleting it loses favourites only, never library data.

## Threat Model

### Assets

- `master.db` (the user's whole library) — merge and projection write to it.
- SoundCloud OAuth token in the OS keyring — the batch paths carry it.
- `artists.db` sidecar — favourites, SC bindings, cached catalogues.
- Audio files on disk + on the USB stick — indirectly relocated by a merge.

### Trust boundaries

- SC API responses are untrusted input: names, permalinks and track titles reach the DB, the UI, and (via download) the filesystem.
- The frontend is trusted only after `require_session`; all mutation routes are gated.
- rbox is trusted to write `master.db` correctly — unauditable (repo 404), mitigated by the probe.

### Threats (STRIDE-light)

| ID | Threat | Mitigation in plan | Test covers |
|---|---|---|---|
| T1 | Full-row `update_content` clobbers concurrent edits (data loss) | Step 5 — re-read inside `db_lock()`, mutate one field | `test_merge_preserves_concurrent_bpm_edit` |
| T2 | Merge runs while Rekordbox is open → half-written state | Step 6 — `is_rekordbox_running()` at start + per chunk, clean abort | `test_merge_aborts_when_rekordbox_running` |
| T3 | Unauthenticated merge/projection call mutates the library | Step 7 — `Depends(require_session)` on every mutation route | `test_artist_routes_require_session` |
| T4 | SC-supplied artist name used to build a filesystem path (traversal) | Reuse `_build_save_path` sanitising (`app/soundcloud_downloader.py:175-213`) + `validate_audio_path` | `test_sc_artist_name_path_traversal` |
| T5 | SC token leaked into logs or into a cache key | No token-keyed `lru_cache`; never log the token at any level | `test_no_token_in_artist_logs` |
| T6 | Batch download becomes a bulk scraper (ToU) | Per-run call cap, favourites only, one related-hop, TTL cache, `aggressive_mode` not inherited | `test_batch_respects_call_cap` |
| T7 | Malicious/oversized SC payload exhausts memory | Existing `_sc_get` limits + a hard per-artist track cap | `test_catalogue_cap` |
| T8 | Sidecar DB write races the background sync | Module-private `threading.Lock` per the sidecar pattern | `test_artist_store_concurrent_writes` |
| T9 | Tag rewrite corrupts an audio file mid-write (power loss, locked file) | Write via the applier's existing atomic path; tag pre-image journalled before the write; skip + report a locked file rather than partially writing | `test_merge_tag_write_is_revertable`, `test_merge_skips_locked_file` |
| T10 | USB relocation loses audio (collision, case-only rename, cross-volume) | Same-volume `os.replace` only; two-step rename for case-only; collision falls back to copy-and-verify; never delete a source before the destination verifies | `test_usb_relocate_case_only`, `test_usb_relocate_collision_falls_back` |
| T11 | "Definitely theirs" list admits a foreign uploader's track | Uploader-id equality against the bound SC user, never a name match; title/credit matches route to the separate remix list | `test_definitely_theirs_uploader_id_only` |

### Residual risk

A merge now mutates audio files, so the blast radius includes the user's files, not just the database. Mitigated by the journalled tag pre-image and by the merge being explicit and previewed — but a file the app cannot write (open in another tool, read-only) is reported and skipped, leaving the library and that file briefly disagreeing until the run is re-tried.

rbox is a compiled dependency with no upstream. A silent write-semantics change would land unnoticed until the probe runs. Accepted: the probe is cheap, pinned versions are the repo norm, and every merge is journalled and revertable.

## Migration Path

### Before → After

- **Today:** artists exist only as per-track strings; aliases live in `metadata_mappings.json`; artist playlists may exist from `generate_smart_playlists` under whatever folder it created; `app_data.json` may hold a stale artist→SC link map.
- **After:** `artists.db` owns canonical artists, aliases, SC bindings, sync state and the Rekordbox playlist id-map. `master.db` gains a folder `Artists` and one playlist per favourite. No column is added to `master.db`.
- **Existing data:** one-shot import at first launch — `metadata_mappings.json` artist entries become pre-seeded merge groups (not applied, only suggested); `app_data.json` artist links become `links` rows; an existing `Artists`-shaped folder is adopted, not duplicated.

### Backfill / forward-compat

- Migration script: none — `artists.db` is created on first use by its own versioned runner (`SCHEMA_VERSION`, step walk, downgrade guard).
- Undo-log change **is** schema-additive with a version step: `entity_kind` defaults to `content`, so rows written by the shipped name-fixer keep reverting correctly.
- Old client reads new data: an older build simply ignores `artists.db`; it still sees the Rekordbox playlists, which are plain playlists.
- Rollback: delete `artists.db` (loses favourites, not library data); delete the `Artists` folder in Rekordbox; revert merges from the undo log **before** deleting the sidecar.

### User-visible behavior during migration

First open of the Artists tab runs the import and shows a one-time "N alias groups imported as merge suggestions" notice. No downtime, no blocking startup, nothing is applied without a click.

## Performance Budget

| Path | Budget | Measured today | Source |
|---|---|---|---|
| `GET /api/artists/hub` (list + counts) | p95 ≤ 300 ms at 10k tracks | counts already computed at load (`app/live_database.py:492-528`) | untested |
| Merge preview (dry-run, 500 tracks) | p95 ≤ 500 ms, zero writes | untested | untested |
| Merge apply, 500 tracks | ≤ 6 s wall, `db_lock()` held ≤ 400 ms per 200-row chunk | journal measured at 190 ms / 5000 rows single-transaction | wave-5 measurement |
| Merge apply, 5000 tracks (tags on, verification off) | ≤ 5 min wall, bounded by tag rewrites not hashing | `_file_sha1` twice per row would add ~630 GiB of reads — opt-in above 250 tracks | wave-5 finding |
| Merge apply, 5000 tracks (byte verification on) | no wall-clock promise — the dialog states it may run for hours | ~630 GiB of reads | wave-5 finding |
| USB relocation, 500 tracks, same volume | ≤ 5 s, **0 bytes of audio copied** | today: full re-copy (~2.7 GB for 412 AIFFs) | `app/usb_one_library.py:904-912` |
| Projection sync, 50 favourites / 10k tracks | ≤ 10 s wall, diff-in-place not rewrite | untested | untested |
| SC catalogue refresh, 50 artists | ≤ 60 s background, 50–100 calls, 0 stream calls | pager spacing 0.3 s (`app/soundcloud_api.py:470`) | wave-2 |
| Artist list render | virtualised; no unpaginated fetch | `drafting_performance-overhaul` documents the existing hotspot | that doc |

### Worst-case scenario

- Input: 50k-track library, 200 favourites, one merge spanning 5000 tracks.
- Expected impact: without the `_file_sha1` skip the merge is disk-bound and effectively hangs; with it, ~60 s with the UI responsive between chunks.
- Mitigation if exceeded: reduce chunk size, move the run behind the existing job/progress pattern, surface cancel.

## API / UX Surface

### Backend (FastAPI)

- New, all `Depends(require_session)` unless noted:
  - `GET /api/artists/hub` — favourites + Tier-1 backlog *(read, no auth change)*
  - `POST /api/artists/favourites` / `DELETE /api/artists/favourites/{id}`
  - `GET /api/artists/{id}` — local vs missing split, and `missing` is split into `definitely_theirs` (uploader-id match) and `remixes_by_others`
  - `POST /api/artists/{id}/update` — one-artist refresh
  - `GET /api/artists/merge/candidates` *(read)* · `POST /api/artists/merge/preview` *(read-only, POST for payload size)* · `POST /api/artists/merge/apply` — `db_lock`, body carries `write_tags` (default true) and `verify_bytes` (default false above 250 tracks) · `POST /api/artists/merge/revert/{run_id}` — `db_lock`
  - `POST /api/artists/projection/sync` — `db_lock` · `GET /api/artists/projection/status`
  - `GET /api/artists/discover` — Tier-2
  - `POST /api/artists/{id}/download-missing` — job id, delegates per track
  - `GET /api/artists/sync/status?job_id=` — poll
- Changed: `POST /api/artist/soundcloud` (`app/main.py:2714-2717`) — the stub finally writes, now into `artists.db`.
- Retired: the "By Artist" branch of the smart-playlist generator.
- Changed: USB export gains a relocation pass — no new route, the existing export flow reports `relocated` alongside `copied`.

### Frontend (React)

- New: `ArtistHubView.jsx` + `artistHub/{ArtistList,SuggestionPanel,ArtistDetail,MergeDialog,ProjectionPanel}.jsx`, `useArtistSync.js` (1500 ms poll, mirrors `usePhraseBatch.js`).
- Changed: `main.jsx` mounts `ArtistHubView` for `lib-artists`; `MetadataView.jsx` hands off the artist branch and keeps its GitMerge button wired to the new dialog.
- Settings: per-artist default sync mode (Auto / Review / Off), background-sync on/off.

### Tauri (Rust commands)

None — no new IPC.

### CLI / sidecar logs

No new stdout markers.

## Telemetry

- `logger.info("op=artist_merge run=%s group=%s tracks=%d chunk=%d elapsed=%.2f")` and `op=artist_projection artists=%d created=%d adopted=%d removed=%d`.
- `op=artist_sc_fetch artist=%s tracks=%d calls=%d` with a per-run call counter, so the ToU call cap is observable.
- Job records expose `total/done/percent/eta_seconds/cancel_requested` like the phrase batch; the UI shows a progress row plus a last-synced timestamp per artist. Merge and revert both toast with the run id.

## Test Plan

| ID | Layer | Test file | Case | Covers |
|---|---|---|---|---|
| T1 | py | `tests/test_live_database.py::test_remove_track_from_playlist_one_arg` | fixed arity removes the row | Step 1, blocker 2 |
| T2 | py | `tests/test_metadata_fixer_schema.py::test_entity_kind_migration` | old rows still revert after the schema step | Migration |
| T3 | py | `tests/test_metadata_fixer_applier.py::test_skips_sha1_when_not_writing_tags` | `_file_sha1` not called | Perf, blocker 3 |
| T4 | py | `tests/test_artist_merge.py::test_merge_preserves_concurrent_bpm_edit` | full-row clobber regression | Threat T1, blocker 1 |
| T5 | py | `tests/test_artist_merge.py::test_apply_then_revert_restores_artist_id` | revert restores the link, not just the name | Step 5 |
| T6 | py | `tests/test_artist_merge.py::test_merge_aborts_when_rekordbox_running` | clean abort, no partial write | Threat T2 |
| T7 | py | `tests/test_artist_merge.py::test_dry_run_writes_nothing` | preview is pure | Step 5 |
| T8 | py | `tests/test_artist_projection.py::test_sync_twice_is_idempotent` | one folder, N playlists | Step 6, OQ1 |
| T9 | py | `tests/test_artist_projection.py::test_readopts_renamed_folder` | id-map self-heals | Adversarial |
| T10 | py | `tests/test_artist_projection.py::test_all_writers_hold_db_lock` | AST walk over `app.artist_store` | Locking |
| T11 | py | `tests/test_artist_store_schema.py::test_migration_step_walk` | version up, downgrade guard | Migration |
| T12 | py | `tests/test_artist_store_registry.py::test_backlog_excludes_favourited` | Tier-1 ranking | Goal 6 |
| T13 | py | `tests/test_artist_routes.py::test_all_mutations_require_session` | every route gated | Threat T3 |
| T14 | py | `tests/test_artist_sc.py::test_missing_diff_threshold_corpus` | seeded corpus, remixes not flagged missing | OQ8 |
| T15 | py | `tests/test_artist_sc.py::test_mix_set_filter` | duration + keyword rule, "Extended Mix" survives | OQ5 |
| T16 | py | `tests/test_artist_sc.py::test_related_empty_falls_back_local` | zero-call fallback, no error surfaced | OQ6, Adversarial |
| T17 | py | `tests/test_artist_sc.py::test_sc_artist_name_path_traversal` | sanitised save path | Threat T4 |
| T18 | py | `tests/test_artist_sc.py::test_batch_respects_call_cap` | per-run cap enforced | Threat T6 |
| T19 | py | `tests/test_pdb_structure.py` | green after a mass merge | USB integrity |
| T20 | js | `frontend/src/components/artistHub/*.test.js` | merge dialog blocks apply until confirmed | Blocker 4 |
| T21 | integration | `tests/test_artist_hub_flow.py` | add favourite → project → merge → revert | full flow |
| T22 | py | `tests/test_artist_merge.py::test_merge_tag_write_is_revertable` | tag rewritten in the file, revert restores the original tag | Threat T9, Goal |
| T23 | py | `tests/test_artist_merge.py::test_merge_skips_locked_file` | locked file reported, run continues, nothing half-written | Threat T9 |
| T24 | py | `tests/test_artist_merge.py::test_verify_bytes_off_above_threshold` | `_file_sha1` not called for a 300-track run by default | Perf |
| T25 | py | `tests/test_usb_relocate.py::test_case_only_rename_two_step` | `boys noize` → `Boys Noize` survives on a case-insensitive volume | Threat T10 |
| T26 | py | `tests/test_usb_relocate.py::test_collision_falls_back_to_copy_verify` | existing destination file is never clobbered | Threat T10 |
| T27 | py | `tests/test_usb_relocate.py::test_pure_rename_copies_zero_bytes` | relocation moves, does not copy | Perf |
| T28 | py | `tests/test_artist_sc.py::test_definitely_theirs_uploader_id_only` | a `(X Remix)` upload by another user lands in the remix list | Threat T11, Goal |

## Task Queue

**M1 — testable without SoundCloud. Ends with a working Artists tab, merge and Rekordbox folder.**

- [ ] **T-1:** fix `remove_track_from_playlist` arity + facade passthroughs (`get_playlist_by_path`, `get_playlist_children`) + expose playlist `uuid` — Step 1, tests T1
- [ ] **T-2:** undo-log deltas (`entity_kind`, `entity_id`, `after_json`, nullable `rule_id`) + `revert_run` INSERT path + `_file_sha1` skip — Step 2, tests T2, T3
- [ ] **T-3:** `app/artist_store/schema.py` sidecar + migration runner — Step 3, tests T11
- [ ] **T-4:** `registry.py` — resolve, favourites CRUD, Tier-1 backlog — Step 4, tests T12
- [ ] **T-5:** `merge.py` — candidate detection + pure `preview()` — Step 5, tests T7
- [ ] **T-6:** `merge.py` — `apply()` / `revert()` via `update_content` re-read in lock, journalled — Step 5, tests T4, T5, T6, T19
- [ ] **T-7:** `projection.py` — adopt-or-create + diff-in-place + running-guard — Step 6, tests T8, T9, T10
- [ ] **T-8:** routes for hub / favourites / merge / projection (`route-architect` first) — Step 7, tests T13
- [ ] **T-9:** `ArtistHubView` + list + suggestion panel + projection panel — Step 8, tests T20
- [ ] **T-10:** merge dialog incl. USB re-copy cost in bytes + revert entry point — Step 8, tests T20
- [ ] **T-11:** absorb "By Artist" + one-way `metadata_mappings.json` import — Step 9, tests T12
- [ ] **T-11a:** merge writes the artist tag into the audio files (reuses the applier's `write_tags` path) + `verify_bytes` opt-in above 250 tracks — Step 5, tests T22, T23, T24
- [ ] **T-11b:** USB relocation pass — a pure artist rename moves/merges folders on the stick instead of re-copying; case-only two-step rename; collision fallback — Step 5b, tests T25, T26, T27

**M2 — SoundCloud catalogue + download**

- [ ] **T-12:** `_sc_get` hardening (404 opt-out, shared paginator, 429 body, drop token-keyed cache) — Step 10, tests T16
- [ ] **T-13:** `get_user_tracks` + reposts + artist↔SC binding replacing the stub route; split the result into `definitely_theirs` (uploader-id equality) and `remixes_by_others` — Step 10, tests T15, T17, T28
- [ ] **T-14:** missing-diff via `external_track_match` at a tuned threshold + corpus — Step 10, tests T14
- [ ] **T-15:** artist detail UI (local vs missing, download-all, collapsed "Mixes & sets") + batch download job — Step 10, tests T18, T21

**M3 — discovery + background sync**

- [ ] **T-16:** `get_related_artists` + local co-occurrence fallback → Tier-2 panel — Step 10, tests T16
- [ ] **T-17:** idle signal + background sync job + per-artist sync mode in Settings — Step 11
- [ ] **T-18:** doc sync (`backend-index`, `frontend-index`, `FILE_MAP`, `MAP*`, `CHANGELOG`) — folds into each PR

## Review

- [x] Plan addresses all goals
- [x] Plan matches `## Original Idea` — no scope-creep (side-thought stays a Non-goal with a schema carve-out)
- [x] Open questions answered or deferred (OQ15 + OQ16 deliberately deferred to this gate)
- [x] Prior Art referenced — three half-built pieces absorbed, not duplicated
- [x] Threat Model present + each threat has a test
- [x] Migration Path present + rollback documented
- [x] Performance Budget set + worst-case documented
- [x] API / UX Surface enumerated for every layer touched
- [x] Telemetry defined
- [x] Test Plan covers every Threat + every Step + every Perf row
- [x] Task Queue items small + independently committable + reference Steps + Tests
- [x] Dependencies audited — none new
- [x] Risk mitigations defined
- [x] Rollback path clear
- [x] Affected docs identified

**Rework reasons:** none.

## Approval Summary

**What it does.** Gives you a real list of favourite artists instead of a per-track text field. For each one you see what you already own, what is still missing on SoundCloud, and you can pull the gaps down. It also cleans up the duplicate artists that casing and spelling create — in Rekordbox, in the audio files, and on your USB sticks — and mirrors your favourites into Rekordbox as a folder called `Artists` with one playlist per artist.

**What you'll notice.**
- An Artists tab listing your favourites, with a suggestion panel: artists you already own the most tracks by, most first, minus the ones you already added — then SoundCloud discovery.
- Selecting an artist fetches their catalogue and shows two separate lists: tracks that are provably from their own SoundCloud account, and tracks where they are only named in a title or credit (`… (X Remix)`, uploaded by someone else). Both are downloadable; only the first is ever auto-queued.
- A per-artist Update button; otherwise it refreshes quietly in the background while the app is open and idle, and you can set Auto / Review / Off per artist.
- A merge screen that groups `boys noize` / `Boys Noize` / `BOYS NOIZE` and, on confirm, rewrites the artist in Rekordbox, rewrites the artist tag inside the audio files, and merges the matching folders on your USB stick at the next export. Every merge is journalled and can be undone.
- A folder `Artists` appearing in Rekordbox, kept in sync, safe to re-run.

**Decisions already recorded (2026-09-04), so nothing here is a surprise.**
- Merge propagates all the way: database, file tags, and USB folder layout. Because the folders are *merged* rather than re-copied, a pure rename moves 0 bytes of audio.
- The catalogue is fetched when you select an artist — not pre-fetched in the background for artists you never added.

**One thing worth knowing.** A merge now edits your audio files, not only the database. Every change is journalled and revertable, and a file the app cannot write is skipped and reported rather than half-written — but this is the first feature that touches your files in bulk, so take a backup before the first large merge.

**Scope.** ~21 files · 20 tasks in 3 milestones · effort L · risk medium. M1 stands alone without SoundCloud: artist list, favourites, local suggestions, merge and the Rekordbox folder.

**Rollback.** Revert the merge runs from the log (restores both the database rows and the file tags), delete the `Artists` folder in Rekordbox, delete the sidecar. Audio content is never re-encoded.

**Mockup:** see `## Mockup`.

## Mockup

### UI — mockup file

`docs/research/mockups/library-artist-hub.html` — open it in a browser. Four screens:

1. **The hub** — favourites (avatar, track count, SC-link state, Auto/Review/Off, per-artist Update) beside a two-tab suggestion panel: "From your library" (ranked by owned tracks, favourites excluded, 0 network calls) and "Discover on SoundCloud".
2. **Artist detail** — owned vs missing side by side, with the missing list split into "Definitely theirs" and "Remixes by others", plus a collapsed "Mixes & sets — excluded" strip showing the 15-minute/keyword rule.
3. **Merge** — the variant group, canonical picker, dry-run count, opt-in orphan removal, and the callout stating that the merge rewrites 412 audio files and merges 3 folders on the stick (moved, not re-copied).
4. **Rekordbox projection** — the `Artists` folder tree, Sync-now, last-synced, per-run delta, idempotency note.

### Backend — concrete example

Merge preview, before anything is written:

```json
POST /api/artists/merge/preview
{ "group_id": "g_7f21", "canonical": "Boys Noize" }

{
  "canonical": "Boys Noize",
  "absorbing": [
    { "name": "boys noize",  "tracks": 118 },
    { "name": "BOYS NOIZE",  "tracks": 41  },
    { "name": "Boys  Noize", "tracks": 3   }
  ],
  "tracks_to_rewrite": 162,
  "files_to_retag": 162,
  "usb_folders_to_merge": ["Contents/boys noize", "Contents/BOYS NOIZE", "Contents/Boys  Noize"],
  "usb_bytes_copied": 0,
  "orphans_after": 3,
  "delete_orphans": false,
  "verify_bytes": false,
  "revertable": true
}
```

Artist catalogue, split as the owner asked:

```json
GET /api/artists/a_0c19

{
  "canonical": "Boys Noize",
  "sc": { "urn": "soundcloud:users:1234567", "permalink": "boysnoize" },
  "in_library": 412,
  "missing": {
    "definitely_theirs": [
      { "title": "Rocket Boy (Original Mix)", "uploader_urn": "soundcloud:users:1234567", "duration_ms": 278000 }
    ],
    "remixes_by_others": [
      { "title": "Sirens (Boys Noize Remix)", "uploader_urn": "soundcloud:users:9988776", "matched_on": "title_credit" }
    ]
  },
  "excluded_mixes_sets": 12
}
```

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

- Code: <file:line or PR>
- External docs: <url>
- Related research: <slugs>
- Supersedes: <slug or none>
- Superseded by: <slug or none>
