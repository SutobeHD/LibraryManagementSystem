---
slug: metadata-name-fixer
title: Normalise artist/title metadata (artist-in-title, featuring, parentheses)
owner: tb
created: 2026-05-15
last_updated: 2026-05-15
tags: []
related: []
---

# Normalise artist/title metadata (artist-in-title, featuring, parentheses)

> **State**: derived from filename + folder. Do not store state in frontmatter.
> Start the file as `docs/research/research/idea_<slug>.md`. Rename + move on each transition (see `../README.md`).

## Lifecycle

> Append-only audit trail. One line per `git mv`. Newest at the bottom.

- 2026-05-15 — `research/idea_` — created from template
- 2026-05-15 — `research/idea_` — section fill (research dive)
- 2026-05-15 — research/idea_ — option refinement after Problem framing

---

## Problem

> Required from `idea_` onward. Keep under 100 words. What are we solving? Why does it matter? What happens if we don't?

Real-world DJ libraries (especially anything sourced from SoundCloud, YouTube, or DMs) carry **malformed artist/title metadata** — artist accidentally inside the title parens, `feat. X` glued to the wrong field, `Title - Artist` reversed, `01 - Title` track-number prefixes, mismatched casing, smart-quote vs ASCII drift, HTML entities, embedded label/year markers, double-encoded remix attributions. Cumulative effect: search misses, sort-by-artist groups split, USB-export to Pioneer hardware shows confusing labels **at the gig**. Manual fixing across 10k–50k tracks is infeasible. This doc designs the automation — deterministic patterns + canonical-source lookup + LLM-assisted edge-cases — with hard safety boundaries (dry-run, per-track preview, undo log, file-snapshot) since it **writes to user metadata** with maximal blast radius.

## Goals / Non-goals

**Goals**
- Detect and propose fixes for malformed `artist` / `title` pairs across the library (Rekordbox DB + ID3 tags + optionally filename).
- Catalogue malformation patterns and apply deterministic transforms with high precision (low false-positive rate).
- Provide a dry-run preview UI: per-track before/after, batch-confirm with select/unselect.
- Persist an audit log of applied changes for revert.
- Optionally enrich from a canonical source (MusicBrainz / Discogs) when local heuristics are ambiguous.

**Non-goals** (deliberately out of scope)
- Album/genre/year/label normalisation (separate topic; share infra later).
- Audio-fingerprint-based identification (AcoustID/Chromaprint) — defer to a dedicated research doc.
- Auto-apply without user confirmation. Never. Not even for "obviously safe" rules.
- Filename rewrites on first iteration — file moves cascade into Rekordbox `Location` and break broken-link state. Tags + DB only, phase 1.

## Constraints

> External facts that bound the solution space — API rate limits, existing data shape, performance budgets, legal/licensing, team capacity. Cite source where possible.

- **Blast radius is huge.** A wrong regex on 30k tracks silently corrupts the library. Every mutation path must be gated by user confirm + audit-log + revert.
- **DB writer serialisation.** Any write to `master.db` MUST acquire `app/main.py:_db_write_lock` (RLock). See `.claude/rules/coding-rules.md` "Backend concurrency". The existing `database.update_tracks_metadata` path already respects this.
- **rbox quirks.** rbox 0.1.5/0.1.7 has `unwrap()` panics on parse paths; mutation goes through `pyrekordbox` directly, not via `SafeAnlzParser`. Verify the writer used here doesn't accidentally re-enter `OneLibrary.create_content` (broken — see `app/usb_one_library.py`).
- **Three sources of truth disagree.** ID3 tag (file), Rekordbox `DjmdContent` row (DB), filename. Currently `app/audio_tags.py:read_tags` reads ID3 with filename fallback for missing fields only. The analysis pipeline writes back to ID3 via `app/audio_tags.py:write_tags` and to the DB via `database.update_tracks_metadata`. **Precedence policy is undefined today** — must be decided per-field before any fixer ships.
- **Backup engine was removed** (commit `8fe5036`, 2026-05-12). No automatic snapshot exists. A fixer that mutates `master.db` + ID3 tags must ship its own scoped before-state capture (per-track JSON diff log at minimum), or block on a replacement snapshot mechanism.
- **MusicBrainz** — free, requires `User-Agent` with contact, rate-limit 1 req/s. ISRC lookup is the cleanest disambiguator when the ID3 carries one (`audio_tags.py` already extracts `isrc`).
- **Discogs** — 60 req/min authenticated, rich electronic-music coverage, but requires OAuth token in `.env`. Not currently wired.
- **Beatport / Spotify** — clean data, commercial APIs, ToS limits redistribution of metadata; legally murky for "rewrite my local library from your catalog".
- **Security sandbox.** `ALLOWED_AUDIO_ROOTS` + `validate_audio_path` (see `docs/SECURITY.md`, `app/main.py`) bound which files can be opened. Fixer must honor this — no shortcuts.
- **`usb_pdb.py` byte invariants** are downstream of metadata. A re-export after fixing strings re-runs the PDB writer; long UTF-16 strings vs short ASCII path are already handled by the string encoder, but artist/title length changes shift page packing. Run `pytest tests/test_pdb_structure.py` against the touched fixture after a mass fix lands.

## Open Questions

> Numbered. Each one should be resolvable (yes/no, or "X vs Y"), not open-ended philosophy.

1. Precedence on conflict: ID3 vs Rekordbox DB vs filename — which wins per field, and is this configurable per-run?
2. Scope of mutation in phase 1: DB only / DB + ID3 / DB + ID3 + filename?
3. Regex-only first pass, or hybrid (regex → LLM for low-confidence cases)?
4. External enrichment: MusicBrainz only (free, ISRC-driven), or Discogs added behind opt-in OAuth?
5. Granularity of confirmation: per-track / per-rule / per-batch with select-all?
6. Audit-log format and location: SQLite table in `master.db` (risk: writes during a fix run), separate `metadata_fixer_log.db`, or JSONL on disk under app data dir?
7. Revert granularity: per-change row, per-run, per-track?
8. Does the fixer require a fresh snapshot of `master.db` before run, given backup engine removal? If yes, ship a minimal `shutil.copy2` snapshot helper as part of this feature or block on a separate snapshot replacement?
9. Smart-quotes / unicode normalisation: NFC vs NFKC? CDJ-3000 firmware tolerance for non-ASCII has been historically fragile.
10. Featuring placement convention: `Artist feat. X` in artist field, or `Title (feat. X)` in title — what does Rekordbox itself emit on export, and do we mirror that?

## Findings / Investigation

> Required from `exploring_` onward. Append dated subsections as you learn. Never edit past entries — supersede with a new one.

### 2026-05-15 — initial audit

**Malformation catalogue (real-world DJ libraries):**

| # | Pattern | Example (bad → good) | Source typical |
|---|---------|----------------------|----------------|
| 1 | Artist embedded in title parens | `Title: "Strobe (Deadmau5)"` / `Artist: ""` → `Artist: "Deadmau5", Title: "Strobe"` | YouTube rips |
| 2 | "feat." in title, should be artist-or-artist-suffix | `Title: "Levels (feat. Ne-Yo)"` → keep in title OR migrate to `Artist: "Avicii feat. Ne-Yo"` (policy call) | Beatport edge cases |
| 3 | "X vs Y" / "X & Y" remix attribution in title | `Title: "Track (Artist1 vs Artist2 Remix)"` → leave title intact, parse remixer for tagging | SoundCloud, Bootleg |
| 4 | Double-encoded `Artist - Title (Artist Remix)` in title field | `Title: "Daft Punk - One More Time (Daft Punk Remix)"` / `Artist: "Daft Punk"` → `Title: "One More Time (Daft Punk Remix)"` | YouTube, mislabeled rips |
| 5 | Reversed `Title - Artist` | `Artist: "One More Time", Title: "Daft Punk"` → swap | Filename-derived imports |
| 6 | Track-number prefix in title | `Title: "01 - Intro"` → `Title: "Intro"` | Album rips |
| 7 | HTML-entity encoding | `Title: "Rock &amp; Roll"` → `"Rock & Roll"` | Web-scraped imports |
| 8 | Smart-quotes vs ASCII | `Title: "Don't Stop"` (U+2019) → `"Don't Stop"` (U+0027) | Beatport, copy-paste |
| 9 | Trailing/leading whitespace, double spaces | `"  Title  "` → `"Title"` | Universal |
| 10 | Casing inconsistencies | `"ARTIST NAME"` / `"artist name"` → titlecase per locale | SoundCloud uploads |
| 11 | Bracket style drift | `"Title [Original Mix]"` vs `"Title (Original Mix)"` | Beatport vs labels |
| 12 | Year/label tag in title parens | `"Title (2024 Remaster)"` | Reissues |
| 13 | Catalog number in title | `"Title (DEF123)"` → strip to `label`/`catno` field | Promo channels |
| 14 | Misencoded UTF-8 → Latin-1 → UTF-8 (mojibake) | `"Björk"` → `"Björk"` | Old Windows imports |

**Source-of-truth quality (anecdotal):** Beatport > Spotify > MusicBrainz > Discogs (UGC variance) > YouTube/SoundCloud (worst). Free + license-clean for derivative writes: MusicBrainz only.

**Existing metadata paths (codebase):**
- Read: `app/audio_tags.py:read_tags` — mutagen-based, ID3/MP4/Vorbis/RIFF/AIFF; filename fallback only when fields missing; handles `feat.`/`vs.`/`&`/`/` etc. as artist *splitters* (`app/database.py:_split_artists` line 271) — note: splitting != normalising.
- Write to file: `app/audio_tags.py:write_tags` — same matrix, format-agnostic key map at line 30.
- Write to DB: `app/database.py:update_tracks_metadata` (used via `app/main.py` routes, holds `_db_write_lock`).
- Filename fallback parsing: `app/audio_tags.py:_parse_filename` line 342 — naive ` - ` split.

**Backup-engine status:** removed in `8fe5036` (`refactor(backend): drop backup engine, routes, scheduler`). No replacement landed. The metadata fixer can't rely on a project-wide snapshot — must ship its own narrow before-state capture.

**Parsing strategy options:**
- **Pure regex/rules.** Deterministic, fast, auditable, no external deps. Coverage caps at ~70-80% of well-formed malformations; ambiguous cases (#5 reversed, #4 double-encoded with no anchor) need either a corpus check or external lookup.
- **LLM-assisted.** Local LLM via Ollama / OpenAI API for ambiguous cases. Cost + latency + non-determinism. Hard to audit. Probably acceptable behind a "review every suggestion" UI; unacceptable for batch-apply.
- **Hybrid (recommended below).** Regex first pass with confidence score; route low-confidence (<0.85) to external MusicBrainz lookup (ISRC if available, else fuzzy title+artist); fall back to "leave alone, surface in UI".

### 2026-05-15 — pattern catalogue + safety design after Problem framing

**Real-world pattern audit** (concrete before/after):

| # | Class | Before | After |
|---|-------|--------|-------|
| 1 | Artist-in-title parens | `Artist:"" Title:"Strobe (Deadmau5)"` | `Artist:"Deadmau5" Title:"Strobe"` |
| 2 | `feat.` wrong field | `Artist:"Avicii feat. Ne-Yo" Title:"Levels"` | policy A: keep / policy B: `Artist:"Avicii" Title:"Levels (feat. Ne-Yo)"` |
| 3 | Reversed Title-Artist (SC convention) | `Artist:"One More Time" Title:"Daft Punk"` | `Artist:"Daft Punk" Title:"One More Time"` |
| 4 | Track-num prefix | `Title:"01 - Intro"` | `Title:"Intro"` |
| 5 | HTML entities | `Title:"Rock &amp; Roll"` | `Title:"Rock & Roll"` |
| 6 | Smart-quotes | `Title:"Don’t Stop"` (U+2019) | `Title:"Don't Stop"` (U+0027) |
| 7 | Double-encoded remix | `Artist:"Daft Punk" Title:"Daft Punk - One More Time (Daft Punk Remix)"` | `Artist:"Daft Punk" Title:"One More Time (Daft Punk Remix)"` |
| 8 | Label+catalog marker | `Title:"Strobe [MAU5001]"` | `Title:"Strobe"` + `label:"mau5trap" catno:"MAU5001"` |

**Source-of-truth decision matrix.** Decision: **Rekordbox `DjmdContent` row is the editable copy**; ID3 tag is write-through, filename is read-only context. DB drives CDJ export and Rekordbox UI; tag drift is recoverable from DB but not vice-versa.

| Field | Authority | On conflict |
|-------|-----------|-------------|
| title / artist / album | DB | DB wins; tag rewritten |
| isrc | tag (canonical) | tag wins; DB filled if blank |
| filename | read-only | never mutated phase 1 |

**Safety architecture (4 layers).**

1. **Always dry-run preview** — detector emits proposed-changes set; nothing mutates until explicit Apply.
2. **Per-track confirm by default** — UI groups by rule, checkbox per track. Mass-apply needs an extra "I reviewed N tracks" gate.
3. **Snapshot-before-mutate** — backup-engine removed in `8fe5036`, so fixer captures (a) original ID3 block (raw, sidecar file) and (b) original `DjmdContent` row (JSON) into the undo log before any write.
4. **Append-only undo log** — sidecar SQLite at app-data dir (NOT `master.db`; avoids `_db_write_lock` contention). One row per field-mutation: `run_id, ts, track_id, rule_id, field, before, after, applied`. Revert = replay-in-reverse.

**MusicBrainz / Discogs match-cost.** Same constraint as remix-detector: MB 1 req/s → 30k tracks ≈ 8h wall-clock. Mitigation: persistent cache keyed on `sha1(normalise(title)||"\x00"||normalise(artist)||"\x00"||normalise(album))` → canonical answer + ETag. Survives sessions, cuts repeat runs to delta-only. ISRC lookups (when tag has one) bypass fuzzy and are O(1) once cached.

## Options Considered

> Required by `evaluated_`. For each viable approach: sketch (2-4 lines), pros, cons, effort (S/M/L/XL), risk.

### Option A — Pure-regex rules engine, dry-run UI
- Sketch: catalogue 12-14 patterns from the table above as Python rule classes with `match() → (confidence, suggested_fix)`. UI lists matches grouped by rule, user selects, batch-apply through existing `database.update_tracks_metadata` path + `audio_tags.write_tags`. Audit log to JSONL.
- Pros: deterministic, fully offline, no API rate-limit drama, easy to unit-test, reviewable in diff.
- Cons: caps at ~75% of real malformations. Won't catch #5 (reversed) without external truth.
- Effort: M
- Risk: medium — wrong rule on a large library is still catastrophic. Confidence threshold + per-track confirm mandatory.

### Option B — Hybrid regex + MusicBrainz enrichment
- Sketch: Option A + MusicBrainz client. For low-confidence matches OR tracks with an ISRC tag, fetch canonical artist/title from MB. Compare local vs MB. Surface mismatches as suggestions, never auto-apply.
- Pros: catches the hard cases (reversed, mojibake, casing). ISRC path is highly accurate. Builds a reusable enrichment service.
- Cons: rate-limit (1 req/s) makes 30k-track sweep a ~8-hour job; need persistent cache. Network failure modes. Legal: MB is CC0, safe to write back.
- Effort: L
- Risk: medium — same blast radius, but more confidence on hard cases.

### Option C — LLM-assisted classification
- Sketch: send `{artist, title, filename}` to a local LLM (Ollama) or cloud API, ask for normalised pair + confidence. Apply only if confidence > threshold AND user confirms.
- Pros: handles arbitrary patterns including mojibake and reversed pairs in one shot.
- Cons: non-deterministic, hard to audit, latency 200-2000ms/track, cost if cloud, privacy if cloud. Cannot defend rule decisions in a code review.
- Effort: M (wiring) + ongoing tuning cost
- Risk: high — opaque mutations on user data.

### Option D — Surface-only (no mutation, just reporting)
- Sketch: ship the catalogue + detector. UI lists "probably malformed" tracks with suggestions. User edits manually through existing track-edit UI.
- Pros: zero blast-radius. Useful even as a phase-0 ship.
- Cons: solves only half the problem (the "what's wrong" half). User still does the work.
- Effort: S
- Risk: low.

## Recommendation

Three milestones, each shippable independently:

- **M0 — Option D (detector + report only).** Ship the 8-class catalogue from the 2026-05-15 Findings as a read-only audit pass. Validates the rule set against the real user library before any mutation path exists. Zero blast radius.
- **M1 — Option A (regex rules + dry-run + per-track confirm + undo log).** Leads with the deterministic patterns 1, 4, 5, 6, 7, 8 (high-precision classes). Mutates the DB row first (DB = authority per matrix above), tag write-through second, both inside a single undo-log transaction. Snapshot helper (Open Q8) is the gating dependency.
- **M2 — Option B (MusicBrainz enrichment).** Adds ISRC-driven lookups + fuzzy fallback for the ambiguous classes (#3 reversed; mojibake; casing). Persistent cache (see Findings) makes repeat runs cheap.

**LLM placement (Option C).** Not a primary mutation source. Lives in a single opt-in slot inside the M1 UI: for tracks the regex flagged but couldn't fix confidently, an "Ask LLM for suggestion" button surfaces a proposal that still flows through the same per-track confirm + undo log. Never batch.

Mutation-phase prerequisites still mandatory (Open Q1 precedence, Q2 scope, Q6 log format, Q8 snapshot). See Findings above — Q1/Q6/Q8 are now answerable.

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
