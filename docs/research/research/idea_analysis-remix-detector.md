---
slug: analysis-remix-detector
title: Detect remix / edit / bootleg variants of a track
owner: tb
created: 2026-05-15
last_updated: 2026-05-15
tags: []
related: [library-extended-remix-finder, metadata-name-fixer]
---

# Detect remix / edit / bootleg variants of a track

> **State**: derived from filename + folder. Do not store state in frontmatter.
> Start the file as `docs/research/research/idea_<slug>.md`. Rename + move on each transition (see `../README.md`).

## Lifecycle

> Append-only audit trail. One line per `git mv`. Newest at the bottom.

- 2026-05-15 — `research/idea_` — created from template
- 2026-05-15 — research/idea_ — section fill (research dive)

---

## Problem

> Required from `idea_` onward. Keep under 100 words. What are we solving? Why does it matter? What happens if we don't?

DJ libraries accumulate many tracks that are **variants of the same original** — Radio Edit, Extended Mix, "Some Artist Remix", VIP, Bootleg, Dub, Acapella, Instrumental, Club Mix. Today these sit as independent library rows with **no relationship signal**, making it hard to (a) know whether a usable version is already present, (b) pick the right variant for a set context, (c) dedupe or group intelligently in the Library/Ranking UI. This doc designs the detector that **classifies each track's variant type** and **links related variants** — both within the local library and against external metadata sources where the canonical original may not be local yet.

## Goals / Non-goals

**Goals**
- Detect that two local tracks are versions of the same underlying work (e.g. `Original Mix` vs `Extended Mix` vs `<Artist> Remix`).
- Classify each track with a precise variant label: `original | extended | radio | club | dub | instrumental | acapella | remix | edit | bootleg | vip | mashup`.
- Group tracks into a "version family" keyed by a canonical original; surface ambiguity rather than guess.
- Identify the canonical original for a remix where possible (local match, else external lookup).
- Produce a confidence score per relation; cheap title-only pass first, optional audio-fingerprint upgrade.
- Persist relations as track-to-track edges + per-track variant flags; UI grouping is a downstream consumer.

**Non-goals** (deliberately out of scope)
- Finding *missing* extended/remix versions to acquire — that is `idea_library-extended-remix-finder`.
- Auto-correcting track titles — that is `idea_metadata-name-fixer`.
- Full music-recognition over arbitrary audio (Shazam-class); we only resolve known library tracks.
- Cover-detection across genres (e.g. orchestral cover of pop song).

## Constraints

- Local-first: must work offline with title-only pass. External lookups (AcoustID, MusicBrainz, Discogs) opt-in, throttled, cacheable.
- AcoustID free tier: 3 req/s per app key; bulk lookup endpoint preferred. `fpcalc` binary (libchromaprint) ~3 MB, must bundle or detect on PATH.
- MusicBrainz: 1 req/s per IP, requires User-Agent string with contact. Relations come back as `recording-recording` with type `remix of` / `edited version of` / `compilation`.
- Library size target: 10k–100k tracks; title-pass must complete in seconds, fingerprint pass batched as a background job.
- Track titles in the wild are dirty: nested parens, mixed brackets, semicolons, emoji, non-Latin scripts, missing parens around `feat.`.
- No write to `master.db` from this feature without `_db_write_lock`; relations live in a new table or sidecar JSON.
- Must not block the analysis pipeline — runs alongside `analysis_engine.py`, not inside it.

## Open Questions

1. Storage: new `track_relations` table in `master.db` (with lock) vs sidecar `relations.json` in app data dir?
2. Canonical-original picker: shortest title? earliest release date? presence of `Original Mix` token? user-pinned?
3. Confidence floor for surfacing a relation in the UI — 0.6? 0.8? configurable?
4. Title normalisation: strip `feat. X`, `vs.`, `&`, accents, case — before or after parenthetical extraction?
5. Fingerprint pass: opt-in per-folder, opt-in globally, or always-on background?
6. How to handle mashups (two originals) — multi-parent edge or a separate `mashup_of` table?
7. AcoustID matches without MBID — accept the bare fingerprint cluster, or require MBID for a relation?
8. Re-runs: invalidate cached relations when a track's tags change, or only on explicit "rescan"?
9. Surface confidence in UI numerically, as stars, or hide and only show high-confidence edges?
10. Variant taxonomy — fixed enum (above) or free-tagged label set?

## Findings / Investigation

### 2026-05-15 — initial audit

**Title-pattern catalogue.** The dominant signal is the parenthetical/bracketed suffix. A two-pass parser is needed: (1) find the outermost balanced `()` or `[]` group at the tail, (2) tokenise its contents. Patterns observed in real DJ libraries:

- Pure variant: `(Original Mix)`, `(Extended Mix)`, `(Radio Edit)`, `(Club Mix)`, `(Dub)`, `(Dub Mix)`, `(Instrumental)`, `(Acapella)`, `(VIP)`, `[VIP Mix]`, `(<Year> Edit)` e.g. `(2024 Edit)`.
- Remixer-bearing: `(<Artist> Remix)`, `(<Artist> Bootleg)`, `(<Artist> Edit)`, `(<Artist> Rework)`, `(<Artist> Flip)`, `(<Artist> Refix)`, `(<Artist> Mashup)`.
- Compound: `(<Artist> Extended Remix)`, `(<Artist> Club Mix)`, `(<Artist> Dub Mix)`, `(<Artist> Instrumental Remix)`.
- Featuring/credits (not variants — must not be misread as a remix): `feat. X`, `ft. X`, `featuring X`, `with X`, `& X`, `vs. X`, `x X`.
- Edge cases: nested `((Original Mix) Extended)`, mixed brackets `[Extended Mix]`, semicolon-separated `(Original Mix; Remastered 2020)`, multiple suffixes `(<Artist> Remix) (Extended)`, emoji in artist name, non-Latin scripts (Cyrillic, Japanese), missing parens (`- Extended Mix` after a dash).

**Audio fingerprinting.** Chromaprint via `fpcalc` binary outputs ~120-char compressed fingerprint + duration; runs ~0.3 s per track at default 120 s sample. AcoustID matches fingerprints to MBID clusters. Two tracks with the same MBID-recording = same recording; two MBIDs in the same MBID-work = same composition (i.e. remix relation in MB sense). Self-contained mode = fingerprint-similarity only (Hamming distance on the integer arrays) — works for "is this the same recording" but not for "is this a remix of that".

**External relations.** MusicBrainz `recording-recording` relation types of interest: `remix`, `edited version`, `mashes up`, `samples`, `cover recording`. Discogs has `Remix`, `Edit`, `Bootleg`, `Mashup` as release-level credits, less reliable but covers white-labels MB doesn't have.

**Confidence tiers.** Title-pattern + same normalised root title = 0.5–0.7. Add same artist on root = 0.75. Add fingerprint-cluster match = 0.9. Add MB `remix of` edge = 0.95.

## Options Considered

### Option A — Title-only, in-process

- Sketch: Regex catalogue + title normaliser in `app/version_classifier.py`. Run during/after `analysis_engine`. Emit per-track `variant_label`, `root_title`, `remixer`. Group by `(normalised_root, primary_artist)`.
- Pros: Zero network, fast, no binary deps, deterministic, easy to test.
- Cons: Misses untitled remixes ("Track 04"), can't pick canonical original, no cross-validation, fragile to dirty titles.
- Effort: S
- Risk: Low; failure mode is missed relations, not wrong relations.

### Option B — Chromaprint + AcoustID, opt-in batched

- Sketch: Bundle `fpcalc`, add `app/fingerprint.py`, background job hashes library, queries AcoustID in batches, caches MBID + MB relations in `track_relations` table. UI shows version families with confidence.
- Pros: Catches untitled variants, validates title guesses, picks canonical original via MB.
- Cons: Network dependency, AcoustID rate limits at scale, bundles a ~3 MB binary, MB coverage uneven for underground/bootleg material.
- Effort: L
- Risk: Medium; rate-limit and cache-invalidation handling are easy to get wrong.

### Option C — Hybrid layered (recommended shape)

- Sketch: Option A always on, cheap. Option B opt-in per library, runs as a background task, upgrades confidence on existing relations rather than replacing them. Local fingerprint-clustering (no network) as a middle tier for offline-only users.
- Pros: Useful on day one without network; degrades gracefully; user controls the network cost.
- Cons: Two code paths to maintain; merging relations from different sources needs a clear precedence rule.
- Effort: L
- Risk: Medium; complexity in the merge layer.

### Option D — External-only, ignore titles

- Sketch: Skip title parsing entirely, rely on AcoustID/MB for everything.
- Pros: Bypasses messy title problem; ground truth from MB.
- Cons: Useless offline; useless for bootlegs MB doesn't have; slow first run; over-trusts a noisy external dataset.
- Effort: M
- Risk: High; breaks the local-first principle.

## Recommendation

Pursue **Option C (hybrid layered)**, scoped as two milestones: M1 ships Option A (title-only classifier + variant labels + naive grouping) — usable immediately, no new deps. M2 adds the fingerprint + AcoustID/MB enrichment as a background job that upgrades existing relations. Before committing to M2, resolve OQ1 (storage), OQ2 (canonical picker rule), OQ4 (normalisation order), and decide on the `fpcalc` bundling vs PATH-detect question. Sister-doc `idea_library-extended-remix-finder` should consume this module's variant labels rather than re-deriving them.

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
