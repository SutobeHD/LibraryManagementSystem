---
slug: usb-onelibrary-track-limit
title: Lift the 16-track cap of the USB export (exportLibrary.db + export.pdb)
owner: claude
created: 2026-11-21
last_updated: 2026-11-22
tags: [usb, onelibrary, pdb, cdj]
related: []
supersedes: []
superseded_by: []
---

# Lift the 16-track cap of the USB export (exportLibrary.db + export.pdb)

> Caveman+. Driven interactively (remote routines dead). Short note — only sections that carry facts.

## Lifecycle

- 2026-11-21 — `implement/approvalgate_` — created interactively; idea from feature registry + B9 test, research + plan in one pass, waiting for user sign-off
- 2026-11-22 — `implement/accepted_` — user approved in chat after rbox 0.3.1 probe: "A jetzt, Upgrade später"
- 2026-11-22 — `implement/inprogress_` — implementation on `fix/usb-onelibrary-track-limit`

## Original Idea (verbatim — never edit)

Feature registry `usb-onelibrary-track-limit` (`docs/features/usb.toml`), desc as written by user session: "OneLibrary-Export schreibt max. 16 Tracks (Template-Slots), Rest landet nur in rekordbox.xml." Test 2026-11-14 (B9): 20-track playlist → 16 rows in `exportLibrary.db`, 16 in `export.pdb`, 20 in `rekordbox.xml`.

## Prior Art

- `docs/reference/rbxport/export.md` §3: rbxport builds `exportLibrary.db` from scratch (SQLCipher 4, 22-table schema, `journal_mode=DELETE`). §10 #5 lists our template cap as P0 capability gap.
- `app/templates/build_template.py`: template = anonymised F: stick export, 16 content rows kept as placeholders.
- Feature `pyrekordbox-upgrade` (related) — dependency bumps, not started.

## Problem

Stick export writes ≤16 tracks. Cap = row count of `app/templates/exportLibrary_template.db`. Every playlist >16 tracks arrives truncated on CDJ. Roadmap 0.1 "Kern-Loop" blocker.

## Findings

### 2026-11-21 — where 16 comes from
- `usb_one_library.py:751` `placeholders = sorted(db.get_contents())` → 16 rows; `:836-839` tracks past `slot_count` counted as `skipped_overflow`, never written.
- Template: 16 content rows, ids 1..16, each own `image_id` 1..16, `property.numberOfContents = 16` (never updated by sync → stale on every stick).
- `export.pdb` has **no own cap**: `_write_pdb_from_db` (`:1179`) reads rows back out of OneLibrary DB → PDB follows the 16.
- **Confidence:** high (read + probe).

### 2026-11-21 — rbox 0.1.7 write paths (probed on template copy in `tmp/`)
- `create_content(path)` → `Diesel: Unexpected null for non-null column`. **But the INSERT lands**: row id = `max(id)+1` exists afterwards; error comes from deserialising the RETURNING row (`file_type` etc. NULL). Every read then fails on that row.
- `NewContent` not constructible from Python (`TypeError: cannot create 'builtins.NewContent' instances`) → `insert_content` unreachable.
- `OneLibrary.create()` fresh DB → FK mismatch on every insert (confirmed, as documented).
- **Repair works:** take a template `Content`, set `.id` to the half-row id, `update_content()` → all model columns filled, row readable, indistinguishable from a template slot. 1000 rows grown in 0.18 s, 500 deletes in 0.08 s.
- `create_image("")` + `update_property(numberOfContents)` work.
- **Confidence:** high (probe).

### 2026-11-21 — the "~500-track PDB limit"
- Source: `usb_pdb.py` module docstring — *assumption* "CDJs do a linear scan without B-tree index entries up to ~500 tracks". No measurement, no hardware report.
- Writer pages arbitrarily (`_pages_for_rows`, no row/page cap). rbxport writes identical empty index pages (export.md §2.5 "same bytes as our writer") on rekordbox-7-style sticks → no evidence of a hard limit. Verdict: **unbelegt, kein Writer-Limit.** Perf on CDJ menus with big libraries = open, only hardware can tell.
- Real new risk with >16 tracks: playlist-entry rows (12 B) reach **>255 rows/page** at ≥256 entries. rbxport #349: rekordbox 6.8.6 crashes on >255-row pages without its special header shape (export.md §2.3). Our header for that regime is unverified (§11 contradiction).
- **Confidence:** medium (no hardware).

### 2026-11-22 — rbox 0.3.1 probe (user request; throwaway venv, project `.venv` untouched)
- `create_content` still raises "Unexpected null"; failed INSERT now rolled back (no half-row) → Option-A trick is 0.1.7-only.
- `NewContent(path=...)` constructible; `insert_content` works once every non-null field is set (copied from a template row).
- `OneLibrary(path)` now takes the rekordbox **directory**; explicit file = `OneLibrary.from_path()`. `rbox.one_library` deprecated → `rbox.onelib`.
- New `DeviceLibrary` (export.pdb + exportExt.pdb read/write, `save()` atomic per file) — candidate to replace `usb_pdb.py`.
- Full suite with 0.3.1 on override path: only the 3 OneLibrary-path tests fail, other 2556 green. Live master.db behaviour untested.
- Decision: no bump in this change (shared `.venv` of parallel sessions, 15 rbox modules) → follow-up.

### 2026-11-21 — dependency landscape
- No SQLCipher binding / AES lib in `.venv` (no `cryptography`, `sqlcipher3`, `pycryptodome`). PyPI: `rbox` 0.3.1, `sqlcipher3-wheels` 0.5.7.

## Options Considered

### Option A — grow template slots at runtime via rbox 0.1.7 (create + repair)
- Sketch: after template copy, per missing slot: `create_content` (expect the null error) → verify half-row at `max+1` → clone a template row into it via `update_content` (own `image_id` from `create_image("")`). Then the existing slot loop runs unchanged.
- Pros: no new dep, ~60 lines, keeps template + WAL-flush + PDB paths byte-identical; ≤16-track exports unchanged.
- Cons: relies on a pinned-version quirk (half-row survives the error). Grown rows inherit template-only columns (dates, sample rate, master ids) like the 16 existing slots already do (rbxport gap #7).
- Effort S. Risk low-med (guarded: failed repair → delete half-row → fall back to old cap + warning).

### Option B — build exportLibrary.db from schema (rbxport way)
- Sketch: SQLCipher-4 binding (`sqlcipher3-wheels`) or own AES codec; create 22 tables + menuItem/category/sort seed rows; write all columns; `journal_mode=DELETE`.
- Pros: no cap, all columns correct, no WAL hack, matches rbxport.
- Cons: new native dep (Schicht-A audit, PyInstaller bundling) or self-written crypto; seed rows must be re-derived; full rewrite of writer + new invariants needing hardware proof.
- Effort L-XL. Risk high.

### Option C — upgrade rbox 0.1.7 → 0.3.1
- Sketch: hope `create_content`/`NewContent` fixed.
- Cons: unverified (needs download); rbox used in ~10 modules (master.db, ANLZ) → regression surface far beyond USB; dep bump = user decision.
- Effort M + unknown. Risk high.

## Recommendation

Option A now — closes B9 for 0.1 with minimal blast radius. Plus three small guards:
1. `property.numberOfContents` = written track count (was stuck at 16 — CDJ may size lists from it).
2. Grown slots each get own `image` row (template slots 1:1 too) — else artwork collides.
3. PDB: cap rows per data page at 255 → never enters the unverified >255 header regime (only playlist entries get there).

Option B stays the long-term target (gap #5/#7/#8) → follow-up after 0.1.

## Implementation Plan

1. `usb_one_library.py`: `_grow_slots(db, placeholders, needed)` before Stage 1b; returns grown placeholder list; guard + fallback.
2. Same file: update `numberOfContents` after Stage 3; overflow warning only when growth failed.
3. `usb_pdb.py:_pages_for_rows`: `MAX_ROWS_PER_PAGE = 255`.
4. Tests `tests/test_onelibrary_track_limit.py`: full `sync()` on fake stick in `tmp_path` for 17 / 100 / 1000 tracks with tiny fake audio + shared ANLZ sidecar → read back OneLibrary (rows, playlist membership + order, paths, ANLZ paths, image ids unique, numberOfContents) + PDB (track rows, entry rows, paths) via test-side PDB reader. PDB page-cap unit test.
5. Docs: docstrings, `docs/features/usb.toml`, `CHANGELOG.md`.

## Test Plan

| ID | Test | Case |
|---|---|---|
| T1 | `test_onelibrary_track_limit.py` | 17 / 100 / 1000 tracks → all rows in exportLibrary.db + export.pdb, playlist complete + ordered |
| T2 | same | paths + ANLZ paths per row exist on fake stick, unique buckets |
| T3 | same | ≤16 tracks: no rows grown, unused slots deleted (old behaviour) |
| T4 | same | growth failure (monkeypatched) → fallback cap + warning, DB still readable |
| T5 | `test_pdb_structure.py` (new case) | 600 playlist entries → every page ≤255 rows, invariants hold |
| T6 | existing | `test_pdb_structure.py`, `test_onelibrary_wal_flush.py`, `test_anlz_usb_export_sync.py` green |

## Approval Summary

- **What it does:** USB export puts every selected track onto the stick, not just the first 16. Both the modern library file (CDJ-3000 / Rekordbox 7) and the legacy file for older players get all tracks.
- **What you'll notice:** a 20-track (or 1000-track) playlist shows up complete on the CDJ; the "template has only 16 slots" warning disappears.
- **How:** the existing 16-slot template is grown on the fly with the same rbox version we already use (no new library, nothing re-architected). If growing fails for any reason, the export falls back to today's behaviour and says so.
- **Scope:** 2 code files + 1 new test file + docs · effort S · risk low-medium (final proof only on real hardware).
- **Not in this change:** rebuilding the DB from scratch like rbxport (bigger, follow-up), correct sample-rate/date/master-id columns for all tracks (same as today for the first 16).
- **Rollback:** revert the PR — export is capped at 16 again.

## Mockup

### Backend — concrete example
```text
before: 20 selected → exportLibrary.db 16 rows, export.pdb 16 rows
        warning "OneLibrary: 16/20 tracks written (4 skipped — template has only 16 slots)"
after:  20 selected → exportLibrary.db 20 rows, export.pdb 20 rows
        log "[OneLibrary] Grew template slots 16 -> 20"
        complete "OneLibrary export written: 20 tracks"
```

---

> ⛔ APPROVAL GATE — user `/approve` (→ `accepted_`) or `/reject "<reason>"` (→ `rework_`).

## Implementation Log

### 2026-11-22 — Implementation
- Built: `_grow_slots` / `_new_slot` (create + repair, round-robin template clone, own image row), `numberOfContents` = written rows, PDB `MAX_ROWS_PER_PAGE = 255`.
- Surprised: playlist links used the source index as `seq` → rbox rejects gaps ("Invalid sequence number"); one track missing on the stick emptied the rest of the playlist. Fixed: seq = links made so far.
- Deviation: `_new_slot` catches `Exception` (fake rbox in `test_usb_relocate.py`, future API drift) → any failure falls back to the template cap instead of aborting the export.
- Tests: `tests/test_onelibrary_track_limit.py` (17 / 100 / 1000 tracks read back from both DBs, ≤16 unchanged, growth-failure fallback); page-cap case in `tests/test_pdb_structure.py`. Mutation-checked: new tests fail on old code.

### 2026-11-22 — Review (independent agent, probes on template copies)
- No blocking bug. Half row at max+1, `delete_content` cleanup, Stage 1b/3 interplay, PDB mirror, page packing (255 → 1 page, 256 → 255+1, ext PDB unaffected) verified.
- Fixed from review: `_new_slot` decided on the error text; now decides on whether an unreadable row sits at the new id (repair or remove either way) + direct test for a refused repair.
- Open, hardware only: grown slots repeat the template's 16 `master_content_id`s (Rekordbox desktop matching); rows without ANLZ keep a dangling template `analysis_data_file_path` (same as the 16 template slots).
- Full suite 2566 passed / 2 skipped (branch head).

## Decision / Outcome

**Result**: pending
