---
slug: external-track-match-unified-module
title: Unified track-matching + fingerprint + adapter-registry module shared across remix-detector / extended-remix-finder / quality-upgrade-finder
owner: tb
created: 2026-05-15
last_updated: 2026-05-15
tags: [architecture, shared-module, fuzzy-match, chromaprint, adapter-registry]
related: [analysis-remix-detector, library-extended-remix-finder, library-quality-upgrade-finder]
---

# Unified track-matching + fingerprint + adapter-registry module shared across remix-detector / extended-remix-finder / quality-upgrade-finder

> **Caveman style.** Fragments, bullets. Drop articles/filler/hedges. No prose paragraphs. Respect per-section caps below.
> State = folder + filename prefix (not frontmatter). Lifecycle = audit trail. See `../README.md`.

## Lifecycle

- 2026-05-15 — `research/idea_` — scaffolded + initial design fill (cross-cutting from 3 sister docs)

---

## Problem

Three sister-docs independently converged on the same recommendation: a unified module owning fuzzy match + version-parse + fingerprint + external-source adapter registry. If each ships its own fork, codebase gets 3 parallel-partial implementations of fuzzy matching (each at 0.65 threshold but drifting), 3 version-tag taxonomies, 3 chromaprint wrappers, 3 adapter shapes. Cost-of-not-doing: triple maintenance, taxonomy drift, divergent confidence semantics across UI. This doc designs the shared module shape up-front so the three sister features ship sequentially without re-architecting later.

## Goals / Non-goals

**Goals**
- Single source of truth for fuzzy matcher — read `_fuzzy_match_with_score` semantics + 0.65 threshold from `app/soundcloud_api.py:566`, decide keep-as-is vs per-source threshold tuning, expose stable API.
- Version-tag taxonomy as importable enum/dataclass — covers `original | extended | radio | club | dub | instrumental | acapella | vip | remix | bootleg | edit | mashup` + year-edit variants + remixer-bearing parens.
- Title-stem extractor — strip parenthetical/bracket suffixes, `feat.`/`ft.`/`featuring`/`with` clauses, trailing-dash `- Extended Mix`, normalise casing/accents. Cited by all three sister-docs.
- Fingerprint API — chromaprint wrapper with PATH-detect fallback (no bundled binary M1), graceful degrade to title-only when missing.
- External-source adapter registry — plugin pattern, all adapters (Discogs / Beatport / Bandcamp / Qobuz / YouTube / SoundCloud) implement same `search(title, artist, duration) → candidates[]` interface.
- Module is read-mostly — no DB writes, no `_db_write_lock` acquisition needed (see Constraints).

**Non-goals**
- Designing individual feature flows (UX, data-model, persistence) — those live in each sister-doc.
- Settling the cross-platform popularity classifier from `idea_analysis-underground-mainstream-classifier` — different domain (popularity, not matching).
- Hard-deciding rbox / Rekordbox metadata-migration logic — out-of-scope (lives in quality-upgrade-finder).
- Choosing the UI surface for any sister feature — UI is per-feature concern.
- Owning the candidate-storage sidecar SQLite schema — each sister-doc owns its own table; this module only returns transient `Candidate` objects.

## Constraints

External facts bounding the solution. Each cited.

- **Fuzzy matcher exists at `app/soundcloud_api.py:566`** — method `SoundCloudSyncEngine._fuzzy_match_with_score(sc_title, sc_artist, local_tracks)`. Threshold `0.65` hardcoded at `app/soundcloud_api.py:583` (`if ratio > best_ratio and ratio >= 0.65`). Uses rapidfuzz token-set ratio + artist gate (per sister-doc citations).
- **`SoundCloudSyncEngine` class** — `app/soundcloud_api.py:550`. Method is instance-bound, not static — extraction needs to break the coupling to `self` (or make a pure-function helper called by the method).
- **No `app/external_track_match.py` exists today** — verified via `Glob app/external_track_match*` → empty. Greenfield module path.
- **`fpcalc` (libchromaprint) NOT bundled today** — verified via `Grep backend.spec` for `fpcalc|chromaprint` → no matches. Bundling is a Schicht-A dep-pinning decision per-platform (~3 MB binary × 3 OS). M1 = PATH-detect + skip if missing (per remix-detector Recommendation, M2-deferred).
- **rbox quarantine pattern (`app/anlz_safe.py`)** — rbox 0.1.5/0.1.7 panics on malformed content via `Option::unwrap()` and aborts the entire process (Windows `0xC0000409`). Quarantine via `ProcessPoolExecutor(max_workers=1)`. This module does NOT call rbox directly (matching is title-based; fingerprinting is `fpcalc` subprocess, not rbox) → no ProcessPoolExecutor needed inside the module itself. If a sister feature wants to pull canonical-original metadata from local Rekordbox after a match, that read goes through `SafeAnlzParser`, not through this module.
- **`_db_write_lock` lives at `app/database.py:22`** (not `app/main.py` — sister-doc `library-quality-upgrade-finder` line 54 incorrectly references `app/main.py:138`; correction noted in the security draftplan). Module is read-mostly — no Rekordbox `master.db` writes — so does not acquire the lock. Sister-doc persistence layers (sidecar SQLite each) acquire their own locks.
- **`ALLOWED_AUDIO_ROOTS` sandboxing (`app/main.py:138-189`)** — applies only when the module actually opens a local audio file for fingerprinting. Path must pass `Path.is_relative_to(resolved_root)` before being handed to `fpcalc`. External URLs (SC/Bandcamp etc.) bypass this — they aren't filesystem reads.
- **Existing httpx pattern** — adapters that hit external APIs should use `httpx.AsyncClient` with timeout + retry (per coding-rules; no `requests.get` in async paths).
- **Schicht-A dep pinning** — any new dep (e.g. `python3-discogs-client`, `pyacoustid`) must land in `requirements.txt` as `==X.Y.Z` with CVE check. Hand-rolled httpx adapters are preferred over per-source SDKs (smaller dep surface, easier pinning).

## Open Questions

1. **Taxonomy strictness** — version-tag taxonomy as `Enum` (strict; unknown raises) or `Literal[str]` (flexible; new tags become string literals without code change)?
2. **`fpcalc` bundling** — required up-front (bundle per-platform in `app/bin/fpcalc/`) or PATH-detect + skip if missing (M1 PATH-detect, M2/M3 bundle)?
3. **Fuzzy-match cache scope** — single shared cache for all three sister features (deduplicates lookups across features) or per-feature cache (isolation but possible 3× cost)?
4. **Adapter-registry runtime config** — `settings.json` toggle per source (user-controlled, allows opt-out of paid sources) or hardcoded enabled list in module (simpler, less flexible)?
5. **API surface shape** — function-only (`extract_title_stem(...)`, `fuzzy_match(...)`, `fingerprint(...)`) or class-based (`TrackMatcher(...).extract_stem(...)`, owns cache + registry)?
6. **Module location** — flat `app/external_track_match.py` (FastAPI-coupled, single file) or sub-package `app/track_match/` with `match.py`, `version_parse.py`, `fingerprint.py`, `adapters/`? Promotion threshold = N sister features shipped?
7. **Logging / telemetry** — should fuzzy-match calls emit structured log line (`logger.info("match score=%.3f source=%s ...", ...)`) for hit-rate / threshold-calibration monitoring, or stay silent (avoid log spam at 30k-track scan)?
8. **Test ownership boundary** — does this module own its own unit tests (`tests/test_external_track_match.py`: regex edge-cases, taxonomy round-trip, fingerprint PATH-detect mock) OR do sister-doc integration tests cover it indirectly (no dedicated test file)?
9. **Per-source fuzzy threshold tuning** — keep universal 0.65 (current SC value) or expose per-source override (e.g. SC=0.65 dirty titles, Discogs=0.80 clean titles, YouTube=0.55 spam-loose)?
10. **Adapter return-type stability** — concrete `Candidate` dataclass owned by this module (sister features import it) or `dict[str, Any]` (looser, less type-safe but lower coupling)?

## Findings / Investigation

### 2026-05-15 — initial design landscape from sister-docs

**Cross-doc citation map** (what each sister-doc independently asks for):
- `idea_analysis-remix-detector.md` — Findings 2026-05-15-option-refinement: shares `_fuzzy_match_with_score` (0.65), title-stem extractor, version-tag taxonomy, chromaprint pipeline. Recommendation §M2 cites "sister-doc `idea_library-extended-remix-finder` should consume this module's variant labels rather than re-deriving them".
- `idea_library-extended-remix-finder.md` — Findings 2026-05-15-UX-refinement: "all three share `SoundCloudSyncEngine._fuzzy_match_with_score` (0.65), title-stem extractor, version-tag taxonomy, and (planned) chromaprint pipeline. Suggest unified `app/external_track_match.py` owning fuzzy + version-parse + fingerprint helpers, consumed by all three." Recommendation also calls for unified candidate-storage sidecar (out-of-scope here, but consistent with shared-module direction).
- `idea_library-quality-upgrade-finder.md` — Findings 2026-05-15-safety-refinement: "Recommend unified `app/external_track_match.py` module (match + fingerprint + adapter registry) consumed by all three. Avoids parallel partial implementations." Recommendation §cross-cutting: "extract `app/external_track_match.py` in Phase 1 (fuzzy + chromaprint + adapter registry) so sister-docs don't fork it."

**Converging design hints from sister-docs**:
- Version-tag taxonomy must be agreed once — remix-detector enumerated the patterns (year-edit, remixer-bearing, compound, bracket-variant, nested, semicolon-segmented, trailing-dash, multi-suffix, language variants DE/ES/PT/IT/EN). Extended-remix-finder added Extended-indicator tokens (`extended mix`, `extended version`, `club mix`, `long version`, `full version`, `12" mix`, `12" version`) + negative tokens (`radio edit`, `radio mix`, `short edit`, `clean edit`, `intro edit`, `single edit`). Quality-upgrade-finder needs the same taxonomy for same-edit detection (refuse-by-default when version-tag differs).
- Fuzzy threshold may need per-source tuning — SC titles dirtier (user-generated) than Discogs (canonical), Beatport `mix_name` field is structured. Universal 0.65 is the SC-calibrated value. Per-source override resolves OQ9.
- Chromaprint pipeline can be staged — M1 = match-only (title + version-tag), M2 = fingerprint added (catches untitled remixes per remix-detector; gates same-edit replacement per quality-upgrade-finder). PATH-detect with graceful skip lets M1 ship without bundling.
- Adapter registry shape — extended-remix-finder sketched `SourcePlugin` interface (`search`, `parse_version`, `quota_remaining`). Quality-upgrade-finder lists same set (Bandcamp, Beatport, SoundCloud Go+, Qobuz, local "HQ" folder). Remix-detector adds AcoustID/MusicBrainz as external relation source. All compatible with one registry pattern.

**Non-trivial decisions deferred to this doc**:
- Where the module lives (OQ6) — flat `app/external_track_match.py` vs sub-package `app/track_match/`. Promotion criteria gated on N sister features shipped (Option C → D in Options Considered).
- How the module is tested (OQ8) — own test file vs sister-coverage. Affects whether shared edge-cases (regex catalogue, taxonomy round-trip, PATH-detect mock) are tested once here or N times in sister tests.
- Who owns the fuzzy-match cache (OQ3) — single shared cache vs per-feature. Affects memory footprint and possible cross-feature cache poisoning.
- Whether to bundle `fpcalc` (OQ2) — Schicht-A dep-pinning decision crosses backend.spec, requirements.txt, and per-platform binary distribution. M1 PATH-detect avoids the decision; M2/M3 forces it.

**Existing SoundCloud-coupling friction**:
- `_fuzzy_match_with_score` is an instance method bound to `SoundCloudSyncEngine` (`app/soundcloud_api.py:566`). Two extraction paths: (a) lift to pure function `fuzzy_match_with_score(title, artist, local_tracks, threshold=0.65)` at module-level, sister-doc and SC engine both import; (b) keep method, add module-level free-function wrapper that delegates. Option (a) decouples cleanly; option (b) avoids touching SC code on day one. Resolvable in draftplan, not blocking idea_.

## Options Considered

### Option A — Function-only flat module

- Sketch: top-level functions in `app/external_track_match.py`: `extract_title_stem(title) → str`, `parse_version_tag(title) → VersionTag`, `fuzzy_match(title, artist, candidates, threshold=0.65) → list[Match]`, `fingerprint(path) → str | None`. No class. Adapter registry as module-level `dict[str, Callable]` populated at import.
- Pros: lightweight, no instantiation overhead, easiest to test (pure functions), minimal import cost for sister-docs that only need one helper.
- Cons: harder to wire dependency injection later (e.g. swap adapter registry for mocking), module-global state for cache + registry is hidden, refactor cost when N>3 features need different config.
- Effort: S
- Risk: Low. Worst case: refactor to class-based when DI becomes painful — pure functions migrate to methods cleanly.

### Option B — Class-based with adapter registry

- Sketch: `TrackMatcher` class holds adapter registry, fuzzy threshold, cache instance. Sister features instantiate one (`matcher = TrackMatcher(adapters=[...], threshold=0.65)`) or grab a module-singleton (`get_default_matcher()`).
- Pros: clean DI for testing (inject mock adapters), explicit lifecycle, per-instance config (e.g. quality-upgrade wants strict 0.80, extended-finder wants 0.65).
- Cons: more boilerplate, instantiation overhead per call-site, sister-docs forced into instance pattern even for one-shot title-stem extraction.
- Effort: M
- Risk: Low-medium. Risk = over-engineering before need is proven.

### Option C — Hybrid (functions + registry singleton)

- Sketch: pure module-level functions for stateless ops (`extract_title_stem`, `parse_version_tag`, `fuzzy_match`). Module-level `ADAPTER_REGISTRY: dict[str, SourcePlugin]` mutated at boot (via `register_adapter(name, plugin)`). Cache as module-level LRU. No class.
- Pros: lowest friction (sister-docs call functions, register adapters at boot), supports per-source threshold via function arg, easy to migrate to Option B if DI need emerges. Minimal API surface change to migrate forward.
- Cons: module-global state (registry, cache) — must be careful in tests (fixture reset). Less explicit than class-based.
- Effort: S-M
- Risk: Low. Module-global state in tests = `pytest` fixture with `reset_registry()` teardown.

### Option D — Subpackage `app/track_match/` with submodules

- Sketch: `app/track_match/__init__.py` re-exports public API; `match.py` (fuzzy), `version_parse.py` (taxonomy + extractor), `fingerprint.py` (chromaprint wrapper), `adapters/` (one file per source: `discogs.py`, `beatport.py`, `bandcamp.py`, `qobuz.py`, `youtube.py`, `soundcloud.py`).
- Pros: cleanest separation, each submodule independently testable, adapters easy to add/remove, scales to 5+ sources without becoming a 2k-line file.
- Cons: heaviest scaffolding cost up-front, premature for M1 when only 1-2 adapters exist. Risk of empty/skeleton submodules sitting unused for months.
- Effort: M-L
- Risk: Low — but the cost is paid up front whether all subdirs get used or not.

## Recommendation

**Option C for M1** (smallest viable change, exposes function-level API + adapter registry pattern). Migrate to **Option D when 3rd sister-feature ships** (clean break, paid by then via real adapter count > 3).

Rationale: Option A defers the adapter-registry decision entirely (each sister-doc invents its own). Option B forces class-based instantiation before DI is actually needed. Option D scaffolds 4+ submodules when only 1-2 are populated on day one. Option C lands the function-level API + a registry mutation point — sister-docs can call `register_adapter("discogs", ...)` at boot — without committing to package layout.

**Gating conditions before promoting Option C → Option D**:
- ≥ 3 sister features actually shipping (not just `idea_` stage).
- ≥ 3 adapters implemented (e.g. Discogs + SoundCloud-wrapper + Local-HQ-folder).
- Module file >800 LOC OR single function >150 LOC.
- ≥ 2 sister features each contributing test edge-cases — justifies test-file split per submodule.

**Open questions resolved in M1 (Option C) scope**:
- OQ5 (API surface) → function-only.
- OQ6 (location) → flat `app/external_track_match.py`.
- OQ10 (return type) → concrete `Candidate` dataclass (importable; cheaper than dict-with-comment-keys).

**Open questions deferred to draftplan**:
- OQ1 (taxonomy enum vs Literal) — decide when first sister-feature's UX needs it.
- OQ2 (fpcalc bundling) — M1 PATH-detect; bundling = M2/M3 dep-pinning decision.
- OQ3 (cache scope) — start single shared; split per-feature if cross-poisoning observed.
- OQ4 (adapter runtime config) — `settings.json` toggle once paid sources land (Phase 2+ in quality-upgrade-finder).
- OQ7 (logging) — start silent; add structured log line when first metric is actually consumed.
- OQ8 (test ownership) — module owns regex + taxonomy + PATH-detect unit tests; sister-docs cover end-to-end adapter behaviour.
- OQ9 (per-source threshold) — keep universal 0.65 in M1; expose per-source override when second adapter (Discogs) lands.

Before promoting `idea_` → `exploring_`, owner needs to: confirm cross-doc agreement on taxonomy with sister-doc owners, confirm `Candidate` dataclass shape with sister-doc owners (so persistence schemas align), confirm M1 scope does NOT include any adapter beyond the SC-extraction (Discogs et al. are first real test of the registry, but land inside extended-remix-finder M1, not this module).

---

## Implementation Plan

> Required from `implement/draftplan_` onward. Concrete enough that someone else executes without re-deriving.

### Scope
- **In:** …
- **Out:** …

### Step-by-step
1. …

### Files touched
- …

### Testing
- …

### Risks & rollback
- …

## Review

Filled at `review_`. Unchecked box or rework reason → `rework_`.

- [ ] Plan addresses all goals
- [ ] Open questions answered or deferred
- [ ] Risk mitigations defined
- [ ] Rollback path clear
- [ ] Affected docs identified (`architecture.md`, `FILE_MAP.md`, indexes, `CHANGELOG.md`)

**Rework reasons:**
- …

## Implementation Log

Filled during `inprogress_`. Dated entries. What built / surprised / changed-from-plan.

### YYYY-MM-DD
- …

---

## Decision / Outcome

Required by `archived/*`.

**Result**: implemented | superseded | abandoned
**Why**: …
**Rejected alternatives:**
- …

**Code references**: PR #…, commits …, files …

**Docs updated** (required for `implemented_`):
- [ ] `docs/architecture.md`
- [ ] `docs/FILE_MAP.md`
- [ ] `docs/backend-index.md` (if backend changed)
- [ ] `docs/frontend-index.md` (if frontend changed)
- [ ] `docs/rust-index.md` (if Rust/Tauri changed)
- [ ] `CHANGELOG.md` (if user-visible)

## Links

- Code (existing): `app/soundcloud_api.py:550` (`SoundCloudSyncEngine`), `app/soundcloud_api.py:566` (`_fuzzy_match_with_score`), `app/soundcloud_api.py:583` (0.65 threshold), `app/database.py:22` (`_db_write_lock`), `app/anlz_safe.py` (rbox quarantine pattern)
- External docs: <chromaprint / fpcalc upstream docs — fill at exploring_>
- Related research: `analysis-remix-detector`, `library-extended-remix-finder`, `library-quality-upgrade-finder`
