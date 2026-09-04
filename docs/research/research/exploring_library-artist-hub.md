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
- **Rekordbox projection** (owner, 2026-09-04): **one folder `Artists`, one playlist per favourite artist**, flat. Playlist = all local tracks of the artist (alias-merged). Refreshed on sync. **Metric:** folder + N playlists appear in Rekordbox after sync; re-sync is idempotent (no dupe playlists, no dupe entries).
- **Merge writes through to Rekordbox** (owner, 2026-09-04): merging `boys noize` + `Boys Noize` + `BOYS NOIZE` rewrites `DjmdArtist`/`DjmdContent` in `master.db` directly. **Every merge is journalled + revertible** (undo-log pattern already shipped in `app/metadata_fixer/schema.py`) and preceded by a dry-run preview — direct write, never blind write. **Metric:** revert restores byte-identical pre-image rows; `pytest tests/test_pdb_structure.py` stays green after a mass merge.
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
- Rewriting the per-track `artist` **string** for reasons other than a merge — that is `metadata-name-fixer`'s job.

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

1. **RB folder idempotency + visibility — PARTIAL (wave 3).** No lookup-or-create exists anywhere; `app/services.py:718-720` already duplicates artist playlists on re-run. rbox exposes no USN setter and `uuid` is dropped by both repo readers → **own id-map** is the answer. Diff-in-place is **blocked** until `remove_track_from_playlist` (`app/live_database.py:1342`) is fixed. Remaining: does rbox bump USN internally, does RB show it after restart → empirical 1 + 5.
2. **Does a per-track artist rewrite merge the entity? — PARTIAL (wave 3).** `update_content_artist` takes a **name** and almost certainly creates-on-demand. `delete_artist` exists but nulls Remixer/OrgArtist/Composer/Lyricist as a side effect and leaves no tombstone. Field key must be exactly `"Artist"` (silent no-op otherwise). Remaining: does the orphan linger in RB browse, and does `search_str` need maintaining → empirical 2 + 3 + 4 + 5.
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
16. **USB re-copy after a merge — acceptable or must it be avoided?** A merge changes `<usb>/Contents/<Artist>/...` and `_track_hash`, so the next USB sync relocates every affected track's audio. Options: accept it, teach the USB differ to treat a pure-artist rename as a move, or offer "merge without touching the USB layout". Resolvable: pick one — but the cost belongs in the Approval Summary.
15. **⛔ Owner decision — SC ToU aggregation boundary.** Does systematic per-artist catalogue enumeration + stored diff stay inside the accepted-risk envelope the single-track downloader already occupies? Mitigations listed in Findings wave 2. **Not resolvable by research — belongs in the Approval Summary.**
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

- Code: <file:line or PR>
- External docs: <url>
- Related research: <slugs>
- Supersedes: <slug or none>
- Superseded by: <slug or none>
