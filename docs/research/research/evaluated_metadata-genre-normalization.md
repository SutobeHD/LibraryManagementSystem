---
slug: metadata-genre-normalization
title: Normalise / unify genre tags (canonical vocab + runtime fuzzy + growing alias map)
owner: tb
created: 2026-06-26
last_updated: 2026-06-26
tags: [metadata, library, normalization]
related: [metadata-name-fixer]
supersedes: []
superseded_by: []
---

# Normalise / unify genre tags (canonical vocab + runtime fuzzy + growing alias map)

> **Caveman+ style.** Fragments, bullets. State = folder + filename prefix. One user gate: `approvalgate_`.

## Lifecycle

- 2026-06-26 — `research/idea_` — created from user request (genre unification question)
- 2026-06-26 — `research/drafting_` — Problem + Prior Art + Constraints + OQ + Research Plan filled (interactive agent)
- 2026-06-26 — `research/exploring_` — 6 parallel research agents (3 codebase map + 3 web: taxonomies / algorithms / prior-art) → Findings + Adversarial + Citation Quality
- 2026-06-26 — `research/evaluated_` — Options + Recommendation synthesised; Research-Verifier PASS (caveats: line refs agent-read, re-verify at draftplan)

## Original Idea (verbatim — never edit)

<!--
Captured from user dictation 2026-06-26 (DE → EN paraphrase of intent, faithful to ask).
-->

User asks: do we have tools to unify / clean up genres? Real-world libraries carry many different spellings/variants of the *same* genre. User wants tooling to standardise them. Proposed approach: keep a big curated list of many genre names; make matching case-insensitive (capitalisation should not matter); recognise misspellings/typos so variants map onto one canonical genre — WITHOUT pre-storing hundreds of literal variant spellings (that would waste storage). User explicitly asks: is there a better approach than pre-storing hundreds of variants?

---

> ↓ Stage 1 — `drafting_`.

## Prior Art

- **Active sibling:** [inprogress_metadata-name-fixer](../implement/inprogress_metadata-name-fixer.md) — artist/title normaliser. Declares this topic out of scope at `:60`: *"Album/genre/year/label normalisation (separate topic; share infra later)."* Ships reusable infra: `app/metadata_fixer/{detector,schema,applier}.py`, sidecar SQLite undo-log (`metadata_fixer_log.db`), `db_lock()` write path, 4-layer safety (dry-run → per-item confirm → snapshot → undo). **No conflict — this doc IS the carved-out genre sibling.**
- **External — Lexicon DJ:** ships a dedicated *"Genre Cleanup"* tool: scans library for every distinct genre, user multi-selects variants and merges into one canonical; autocomplete suggests existing values; DB-backup before mass edit. ([lexicondj.com/manual/genre-cleanup](https://www.lexicondj.com/manual/genre-cleanup))
- **External — MusicBrainz Picard:** no built-in genre whitelist; standardisation via *Genre Mapper* plugin = user-defined alias→canonical replacement map (not a stored variant list). Folksonomy-tags gated against MB's curated genre vocab. ([Genre Mapper](https://github.com/rdswift/picard-plugin-genre-mapper), [genre docs](https://picard-docs.musicbrainz.org/en/latest/config/options_genres.html))
- **External — Rekordbox / Serato / Traktor / Mixed In Key:** genre is free-text, no normalisation/merge feature. Rekordbox dropdown = previously-seen values only. **No DJ app ships a fixed genre vocabulary → a bundled normaliser is genuinely novel.** ([Pioneer community](https://community.pioneerdj.com/hc/en-us/community/posts/22977636417817-Genres-in-Rekordbox))
- **External whitelist pattern:** [genre-tagger](https://github.com/svetixoxo/genre-tagger) = {one canonical per line} + runtime normalisation (lowercase, strip spaces/hyphens, re-check) — the canonical-vocab model in production; never stores the variant universe.

## Problem

Genre is a free-text string per track. Same genre arrives spelled many ways (`Drum & Bass` / `drum n bass` / `DnB` / `Drum&Bass`; `Tech House` / `tech-house` / `techhouse`; casing drift). The app's distinct-genre list groups by **exact, case-sensitive** string (`app/database.py:223-248`) → "Rock"/"rock"/"ROCK" become 3 genres; filtering, smart-playlists, Insights, and USB browsing all fragment. No dedup, no case-fold, no typo handling today. Cost of not doing it: messy genre menus on CDJ at the gig, split smart-playlists, useless genre stats.

## Goals / Non-goals

**Goals**
- Detect genre variants/typos and cluster them onto a canonical genre. **Metric:** key-collapse + fuzzy resolve ≥ 90% of true variant-dupes on a real library, near-zero wrong-merges at auto threshold.
- Case-insensitive by construction (capitalisation irrelevant) — directly answers the user's ask.
- **No variant-list bloat:** storage = canonical vocab + small alias map (grows from confirmed merges) + 1 FK/track. NOT hundreds of literal spellings.
- Non-destructive: keep raw genre, every merge reversible (undo-log). Dry-run preview before any write.
- Reuse metadata-name-fixer safety infra (share, don't reinvent).

**Non-goals**
- Auto-apply merges without user confirm. Never.
- Imposing an external taxonomy over the DJ's own genres (external seed = opt-in, editable).
- Folding subgenres into parents (`Tech House` must NOT become `House`).
- Audio-content genre *detection* (classifier) — separate topic.
- Filename rewrites (cascades into Rekordbox `Location`).

## Constraints

- **Genre stored as free string; distinct list = exact + case-sensitive grouping** — `app/database.py:229` (`genre_counts[t["Genre"]] += 1`), `:248` (list build). No normalisation anywhere on genres today. (verified 2026-06-26)
- **Inconsistency to resolve:** smart-playlist genre matching IS already case-insensitive (`.lower()` both sides) — `app/smart_playlist_engine.py:52` (field "4"=Genre), `:156-171` (string ops). So dedup list is case-sensitive but filtering is case-insensitive → split-brain. Normalisation must unify both.
- **Alias infra half-exists:** `MetadataManager` (`app/services.py:746-777`) already does alias→canonical mapping for `artists`/`labels`/`albums` — **genres absent** (`:752`,`:760` hardcode the 3 categories, no `genres`). Extensible: add a `genres` category + JSON-persisted map.
- **Genre change = 3-tier rewrite.** (1) file tags: ID3 `TCON` `app/audio_tags.py:90`, MP4 `©gen`, Vorbis `genre`, AIFF/WAV `:225`; (2) `exportLibrary.db` genre FK via `_get_or_create_genre` `app/usb_one_library.py:541`; (3) `export.pdb` rows `encode_genre_row` `app/usb_pdb.py:460`, table `T_GENRES=0x01` `:71`.
- **USB dedup is exact + case-sensitive** — `_get_or_create_genre` keys cache by exact name (`app/usb_one_library.py:544-547`, `get_genre_by_name` exact match). Genre id = u32 FK on every track row → a merge must rewrite all track FKs to the canonical id, then re-export.
- **USB PDB byte-verified** vs real F: drive (table order, per-table blank pages). A genre rename/merge re-runs the PDB writer → run `pytest tests/test_pdb_structure.py`. No incremental export — full rewrite.
- **Rekordbox flattens multi-genre destructively:** writes `Acid;Techno` → `Acid Techno` on analysis (new unwanted genre). Any write-back must decide multi-genre policy. ([Pioneer forum](https://forums.pioneerdj.com/hc/en-us/community/posts/115011563106-Multiple-genres-in-Rekordbox))
- **MusicBrainz genres are CC BY-NC-SA 3.0, NOT CC0** — supplementary data; commercial use needs paid MetaBrainz licence → **not bundle-clean** for a paid Rekordbox competitor. ([MB data licence](https://musicbrainz.org/doc/About/Data_License))
- **Bundle-clean seed sources:** Discogs *Electronic* styles (119, **CC0** — [data.discogs.com](https://data.discogs.com/)); ID3v1 genres 0-191 (public domain, legacy numeric decode map). Beatport ~36 genres + subgenres = best DJ structure but **no data licence** → use names as facts to curate, don't ship verbatim as "Beatport's list".
- **db_lock:** all `master.db` writers acquire `db_lock()` (`app/database.py:25-26`). Genre write routes must too.
- **New dep = Schicht-A decision** (`coding-rules.md`): `rapidfuzz==3.14.5` (MIT, C++ wheels, zero runtime deps) — pin + user approval.

## Dependencies

| Dep | Kind | Version | License | Schicht-A audit needed? | Why |
|---|---|---|---|---|---|
| rapidfuzz | py | 3.14.5 | MIT | yes | fuzzy match (token_sort_ratio/WRatio); C++ core, prebuilt wheels, 0 runtime deps |
| ~~python-Levenshtein~~ | py | — | GPL-2.0 | REJECT | GPL — license-incompatible with paid product |
| ~~jellyfish~~ (phonetic) | py | — | MIT | REJECT | metaphone/soundex = noise for short genre jargon; rapidfuzz covers typos |
| ~~sentence-embeddings~~ | py | — | — | REJECT | overkill; heavy unpinnable tree; alias map encodes the few real semantic links better |
| Discogs Electronic styles | data asset | 2019+ dump | CC0 | no (data) | optional bundled seed vocab (119 DJ-electronic styles) |
| ID3v1 genre table | data asset | static | public domain | no (data) | legacy numeric→string decode + flat staples |

## Open Questions

1. Canonical vocab source v1: **user's own genres only** vs **bundled seed (Discogs Electronic CC0)** vs **hybrid** (learn-from-library + opt-in seed)?
2. Bundle a seed vocab in v1 at all, or learn-only (seed = later milestone)?
3. Multi-genre policy: support a list (`House; Disco`) or single canonical? What to write back given Rekordbox's `;`→space collapse?
4. Subgenre policy: encode parent→child (`Tech House`⊂`House`) but never auto-merge across the boundary — confirm the rule + how fuzzy is fenced from bridging them.
5. Write-back scope v1: `master.db` / app-state only (detect+remap), or also rewrite file tags + trigger USB re-export?
6. Fuzzy thresholds: `token_sort_ratio ≥ 90` auto-suggest / `80–90` review / `<80` unmatched — confirm + tune on a real library (short strings swing scores hard → bias to review).
7. Reversibility granularity: reuse `metadata_fixer` sidecar schema — per-merge vs per-run undo? Keep raw genre in a side field or only in undo-log?
8. Canonical identity storage: new `genres`/`genre_alias` tables in app state, vs overwrite the Rekordbox `Genre` field in place?
9. Consumers after normalisation: do smart-playlists / Insights / USB query **canonical** or **raw** genre? (resolves the case-sensitivity split-brain.)
10. `rapidfuzz==3.14.5` Schicht-A dep approval — yes/no.

## Research Plan

- Agent 1 (codebase): genre data model, dedup, API, normalisation hooks → DONE
- Agent 2 (codebase): genre write/export paths (tags, exportLibrary.db, PDB) + merge/rename invariants → DONE
- Agent 3 (codebase+doc): frontend genre surface + reusable metadata-fixer infra → DONE
- Agent 4 (web): canonical taxonomies + bundling licenses → DONE
- Agent 5 (web): normalisation algorithms + storage schema + perf → DONE
- Agent 6 (web): DJ-software prior art + critique of user's variant-store idea → DONE

## Idea Verification

### 2026-06-26 — PASS
- Matches Original Idea: unify genre variants, case-insensitive, avoid storing hundreds of variants. ✓
- User's two instincts confirmed correct: (a) case-insensitive is right (= casefold stage-0); (b) don't store hundreds of variants — the canonical-vocab + alias model is BOTH smaller storage AND higher recall (Findings 2026-06-26 algorithms). The refinement is *how* to not store variants, not *whether*.
- No scope overlap with metadata-name-fixer beyond shared infra (explicitly sanctioned at sibling `:60`).

---

> ↓ Stage 2 — `exploring_` (autonomous).

## Findings / Investigation

### 2026-06-26 — codebase: data model + dedup
- **Codebase:** genre = free `str`/`None` per track (`app/database.py:114`, `app/main.py:327`). Distinct list built once at load by exact-string, case-sensitive `defaultdict(int)` accumulation (`app/database.py:223-229`) → sorted to `self.genres` (`:248`), same in `live_database.py`. `get_all_genres()` `:858`. Zero normalisation/case-fold/alias for genres. `_normalize_artist_name` exists for **artists** (`:274-296`, strips `NN - ` prefix) — pattern to mirror. `MetadataManager` alias map (`app/services.py:746-777`) supports artists/labels/albums, **not genres**.
- **Synthesis:** clean hook points = (a) extend `MetadataManager` with `genres` category, (b) add a canonical-key + alias layer between raw genre and `genre_counts`/`get_all_genres`.
- **Confidence:** high (refs verified 2026-06-26).

### 2026-06-26 — codebase: write/export paths + merge invariants
- **Codebase:** genre change must rewrite 3 tiers — file tags (`audio_tags.py:90` TCON / MP4 / Vorbis / AIFF), `exportLibrary.db` FK (`usb_one_library.py:541` `_get_or_create_genre`, exact-name cache `:544-547`), `export.pdb` (`usb_pdb.py:460` `encode_genre_row`, `T_GENRES=0x01` `:71`). USB dedup exact+case-sensitive. Genre id = u32 FK on every track → merge = pick canonical, repoint all track FKs, rewrite 3 tiers, drop orphan row. PDB byte-verified (table order, blank pages) → `pytest tests/test_pdb_structure.py`. No incremental export — full rewrite.
- **Synthesis:** detect/remap is cheap (in app state); the *write-back + USB re-export* is the expensive, risky half → phase it; default v1 to remap-in-app + dry-run, gate file/USB writes behind explicit apply.
- **Confidence:** high.

### 2026-06-26 — codebase: frontend + reusable infra
- **Codebase:** genre UI = BatchEditBar text input (`BatchEditBar.jsx:80-87`), SmartPlaylistEditor criterion (`:10`/field "4"), InsightsView top-genres stats (`:123-154`), RankingView hardcoded genre tag suggestions (`:9-14`). New "Genre Cleanup" view = mirror LibraryView/TrackTable styling (`text-ink-*`, `hover:bg-white/5`, `amber2`). Sibling `metadata_fixer` infra 100% reusable: 4-layer safety, sidecar SQLite (`schema.py`), 6-step atomic applier with `db_lock()`, frontend "I reviewed N" confirm gate. Genre-specific = the rule/cluster logic + canonical vocab.
- **Synthesis:** build `app/genre_normalizer/` as a sibling package; factor the apply/undo/schema as shared utilities.
- **Confidence:** high.

### 2026-06-26 — web: canonical taxonomies + licensing
- **Web:** No DJ app ships a fixed genre vocabulary (Rekordbox/Serato/Traktor/MIK all free-text) → bundled normaliser is novel. **MB genres = CC BY-NC-SA 3.0, not CC0** ([licence](https://musicbrainz.org/doc/About/Data_License)) → license landmine for paid product. **Discogs Electronic styles = 119, CC0** ([data.discogs.com](https://data.discogs.com/)) = best license-clean DJ-electronic seed. **ID3v1 0-191 = public domain** (legacy decode). Beatport ~36 genres + subgenres = best modern DJ structure, **no data licence** (names are facts, list isn't redistributable as a dataset). Spotify seeds deprecated 2024-11 + proprietary; Apple proprietary. ([Discogs blog](https://blog.discogs.com/en/genres-and-styles-on-discogs/), [Beatport genres](https://greenroomsupport.beatport.com/hc/en-us/articles/41043520429076-Beatport-Genres-Including-NEW-Open-Format-Genres), [ID3v1 list](https://en.wikipedia.org/wiki/List_of_ID3v1_genres))
- **Synthesis:** if bundling — hybrid: Discogs-Electronic (CC0) core + ID3v1 (PD) staples, curated/renamed against Beatport's two-tier structure. Skip MB/Spotify/Apple for bundling. But default v1 vocab = the **user's own existing genres** (their personal taxonomy); seed = opt-in enrichment.
- **Confidence:** high (a few counts from search snippets where pages 403'd — flagged).

### 2026-06-26 — web: algorithms + storage (answers the user's core question)
- **Web:** canonical-key pipeline = NFKC → `casefold()` → symbol-to-word (`&`/`+`→`and`, ` n `→`and`) → strip non-alphanumeric → collapse whitespace. `Drum & Bass`/`drum n bass`/`Drum&Bass` → `drumandbass` (free O(1) merge). Abbreviations (`DnB`→`dnb`) DON'T key-collide → need the alias table, not fuzzy. Fuzzy lib = **rapidfuzz 3.14.5 (MIT, C++)** beats GPL python-Levenshtein (license) and stdlib difflib (speed/scorers). Phonetic (jellyfish) = noise for genres; embeddings = overkill. **Storage proof:** {canonical_id FK per track + ~80-row vocab + ~200-400-row alias map} ≈ **15-30 KB** AND generalises to unseen variants; {pre-store hundreds of literal variants} = 5-10× larger AND still misses the next novel spelling. Perf trivial — you normalise the few hundred *distinct* strings, not 50k tracks (~24k comparisons, sub-second). ([rapidfuzz](https://pypi.org/project/RapidFuzz/), [casefold/NFKC](https://djangocas.dev/blog/python-unicode-string-lowercase-casefold-caseless-match/))
- **Synthesis:** pipeline = normalise-key → exact alias lookup → fuzzy vs vocab (≥90 auto-suggest / 80-90 review / <80 unmatched) → user confirm grows alias map. **This is the "better approach": smaller storage + higher recall + self-learning.**
- **Confidence:** high.

### 2026-06-26 — web: prior art + critique of user's idea
- **Web:** Lexicon DJ's "Genre Cleanup" = exactly this niche (scan distinct genres, manual multi-select merge, autocomplete suggestions, DB-backup first). Picard's Genre Mapper = alias→canonical map. genre-tagger = whitelist + runtime normalise. **None pre-store the variant universe** — all use canonical-vocab + runtime/alias. Critique of "store hundreds of variants": it's a denormalised cache of a function you can compute at runtime; rots on every new typo; doesn't generalise. **Top risks:** (1) subgenre collapse (`Tech House`→`House`); (2) multi-genre flattening + Rekordbox `;`→space; (3) destructive irreversible merge; (4) external taxonomy over personal one; (5) full USB re-export cost on mass rewrite. ([Lexicon](https://www.lexicondj.com/manual/genre-cleanup), [Picard Genre Mapper](https://github.com/rdswift/picard-plugin-genre-mapper), [DJ genre granularity](https://www.productlondon.com/how-to-categorize-genres-in-a-dj-library/))
- **Synthesis:** validates user's instincts (case-insensitive + don't store variants), refutes the storage *mechanism*; supplies the safe-merge guardrails.
- **Confidence:** high.

## Adversarial Findings

### 2026-06-26
- **Subgenre collapse:** fuzzy `token_sort_ratio("Tech House","House")` is high-ish → risk auto-folding distinct DJ subgenres. **Mitigation:** vocab treats subgenres as first-class canonicals; fuzzy fenced to never bridge two vocab entries; bias to review on short strings.
- **Multi-genre flattening:** track `House; Disco` — if collapsed to one, or written back, Rekordbox turns `Acid;Techno`→`Acid Techno`. **Mitigation:** decide OQ3 before any write-back; preserve separators; never silently flatten.
- **Destructive merge:** mass mis-merge unrecoverable. **Mitigation:** keep raw genre, reversible undo-log (reuse `metadata_fixer` sidecar), dry-run + per-cluster confirm, "I reviewed N" gate.
- **Personal vs external taxonomy:** bundled Discogs/Beatport names may not match this DJ's filing. **Mitigation:** default vocab = user's own genres; external seed opt-in + fully editable.
- **USB re-export cost:** mass genre rewrite forces full PDB/exportLibrary re-export (no incremental). **Mitigation:** stage merges, preview diff, confirm, export once — never auto-rewrite-then-export.
- **Parallel-writer race (inherited):** sibling doc found 0/85 `master.db` routes hold `db_lock()` — a fixer run can't gate other writers. **Mitigation:** acquire `db_lock()` on genre write routes; carry the broader retrofit as the sibling's parked task.

## Citation Quality

### 2026-06-26 — interactive-agent spot-check
- `app/database.py:223-229,248` genre dedup exact+case-sensitive — **PASS** (read 2026-06-26).
- `app/smart_playlist_engine.py:52` field "4"=Genre; `:156-171` case-insensitive ops — **PASS** (`:52` read; ops range agent-read).
- `app/services.py:746,752,760,775` MetadataManager, no `genres` category — **PASS** (read 2026-06-26).
- `app/usb_one_library.py:541` `_get_or_create_genre` exact-name cache — **PASS** (read 2026-06-26).
- `inprogress_metadata-name-fixer.md:60` genre = separate topic — **PASS** (read 2026-06-26).
- `app/audio_tags.py:90/225`, `app/usb_pdb.py:71/460` — **agent-read, not re-verified line-exact** — re-verify at draftplan (repo has documented line-drift; sibling doc needed a 892→1124 refresh).
- Web license claims (MB CC BY-NC-SA, Discogs CC0, ID3v1 PD) — **PASS** (cited official sources).

## Research Verification

### 2026-06-26 — PASS (with caveats)
- Open Questions coverage: storage model resolved (canonical+alias+fuzzy); vocab source, multi-genre, subgenre, write-back scope remain as numbered OQs for draftplan — appropriate.
- Internal consistency: codebase + algorithm + prior-art findings agree (canonical-vocab model). No contradictions.
- Citation quality: load-bearing codebase refs re-verified by interactive agent; 4 secondary refs (audio_tags/usb_pdb lines) flagged for draftplan re-verify.
- Adversarial concerns addressed: 6 surfaced, each with a mitigation that maps to an OQ or a safety layer.
- **Premise correction folded in:** MB genres are NOT CC0 (original assumption wrong) → bundling recommendation changed to Discogs-CC0/ID3v1-PD. Material, captured.

## Options Considered

### Option A — Detect-only report (dry-run, zero writes)
- Sketch: canonical-key + fuzzy over distinct genres → cluster report ("these 6 spellings look like one genre"), counts, suggested canonical. No mutation. New `GET /api/genres/normalize/scan` + read-only view.
- Pros: zero blast-radius; useful phase-0 ship; validates thresholds on real data.
- Cons: solves only "what's messy", user still merges manually.
- Effort: S
- Risk: low
- Prior-art match: Lexicon scan step

### Option B — Canonical vocab + runtime fuzzy + user-confirmed merge + undo  ★ recommended core
- Sketch: vocab = user's own genres (+ opt-in seed). Pipeline: normalise-key → exact alias lookup → fuzzy vs vocab (90/80 thresholds) → unmatched bucket → user confirms → merge remaps track→canonical + grows alias map. Reuses `metadata_fixer` sidecar undo + `db_lock` + 4-layer safety. `MetadataManager` gains a `genres` category.
- Pros: answers user exactly; smallest storage; self-learning; non-destructive/reversible; reuses proven infra.
- Cons: merge UI + write-back work; USB re-export cost on apply.
- Effort: M (app-state remap) → L (with file-tag + USB write-back)
- Risk: medium (mitigated by dry-run + confirm + undo)
- Prior-art match: Lexicon + Picard Genre Mapper

### Option C — Hand-curated alias table only (no fuzzy, no seed)
- Sketch: just the `MetadataManager` genres category; user types alias→canonical rules.
- Pros: tiny; deterministic; no new dep.
- Cons: no auto-suggest; doesn't generalise to typos/casing without manual rules; high manual effort.
- Effort: S
- Risk: low
- Prior-art match: Picard Genre Mapper (subset)

### Option D — Bundle external seed taxonomy (Discogs Electronic CC0)
- Sketch: ship a curated ~150-220 two-tier DJ vocab (Discogs-Electronic + ID3v1, Beatport-structured); map library onto it. Layer on top of B.
- Pros: rich modern subgenres out-of-box; consistent naming.
- Cons: imposes external taxonomy if not opt-in/editable; curation work; license care (Discogs/ID3v1 only).
- Effort: M (on top of B)
- Risk: medium (personal-taxonomy mismatch)
- Prior-art match: genre-tagger whitelist

### Option E — LLM-assisted classification
- Sketch: send genre (+ artist/title) to an LLM, ask for canonical.
- Pros: handles arbitrary mess.
- Cons: non-deterministic, opaque, latency/privacy, unauditable, overkill for a closed small vocab.
- Effort: M + tuning
- Risk: high
- Prior-art match: none in DJ tools

### Option F — User's literal "pre-store hundreds of variants" (strawman)
- Sketch: store every spelling/case/separator permutation per genre.
- Pros: simple lookups.
- Cons: 5-10× larger storage AND still misses the next unseen variant; brittle; must hand-add forever.
- Effort: S-M
- Risk: medium (rots over time)
- Prior-art match: none (anti-pattern)

## Recommendation

**Phased B**, with vocab = the DJ's own genres first, external seed (D) opt-in later.

Direct answer to the user: **yes, there is a better approach than pre-storing hundreds of variants.** Store a **canonical vocabulary** (one row per real genre) + a **small alias/synonym map that grows from your confirmed merges** + **runtime fuzzy matching** (rapidfuzz). A normalise-key (NFKC + casefold + separator-collapse) makes capitalisation and spelling/separator noise free; abbreviations/synonyms live in the alias map; typos are caught by fuzzy as *suggestions* you confirm. This is **smaller storage** (~15-30 KB vs a 5-10× larger variant table) **and higher recall** (generalises to spellings never seen), and it **learns** — exactly what Lexicon/Picard do, none of which pre-store variants.

Milestones: **M0** = Option A detect-only report (validate thresholds, zero risk). **M1** = Option B merge + undo, app-state remap, reuse `metadata_fixer` safety infra, `MetadataManager` genres category, `rapidfuzz==3.14.5` (Schicht-A approval). **M2** = write-back to file tags + USB re-export (gated, staged) and optional bundled Discogs-CC0 seed (Option D). Guardrails throughout: subgenres are first-class (never fold into parents), keep raw genre, reversible, dry-run + confirm, decide multi-genre policy (OQ3) before any write-back. Blocks commit: OQ1/3/5 decisions + dep approval (OQ10).

---

> ↓ Stage 3 — `implement/draftplan_`. `research-plan` fills Implementation Plan + Task Queue (Planner + Threat-Modeller + Migration + Perf-Budget + Test-Plan), Reviewer fills Review, then Mockup+Summary → `approvalgate_`.

## Implementation Plan

Stage 3 Planner-Agent. _(unfilled — awaiting evaluated_ → draftplan_ promotion)_

## Threat Model

Stage 3 Threat-Modeller-Agent. _(unfilled)_

## Migration Path

Stage 3 Migration-Path-Agent. _(unfilled — genre canonical store + alias map = additive schema; existing raw genre preserved)_

## Performance Budget

Stage 3 Perf-Budget-Agent. _(unfilled — Findings: normalise ~hundreds distinct strings, sub-second; USB re-export = existing full-rewrite cost)_

## API / UX Surface

Stage 3 Planner-Agent. _(unfilled)_

## Telemetry

Stage 3 Planner-Agent. _(unfilled)_

## Test Plan

Stage 3 Test-Plan-Agent. _(unfilled — must cover key-collapse correctness, subgenre non-merge, multi-genre, undo round-trip, `tests/test_pdb_structure.py` after write-back)_

## Task Queue

_(unfilled — written at draftplan_, approved at the gate)_

## Review

Stage 3 Reviewer-Agent. _(unfilled)_

## Approval Summary

Stage 3 Mockup+Summary-Agent (plain English). _(unfilled — written after Plan-Reviewer PASS)_

## Mockup

Stage 3 Mockup+Summary-Agent. _(unfilled)_

---

> ⛔ APPROVAL GATE — user `/approve` or `/reject`. Single sign-off. Not reached yet (doc at `evaluated_`).

## PR Log

_(Stage 4)_

## Implementation Log

_(Stage 4)_

---

## Decision / Outcome

_(Required by `archived/*` — filled at graduation.)_

## Links

- Code: `app/database.py:223-248`, `app/services.py:746-777`, `app/usb_one_library.py:541`, `app/usb_pdb.py:460`, `app/smart_playlist_engine.py:52`
- Sibling infra: [inprogress_metadata-name-fixer](../implement/inprogress_metadata-name-fixer.md)
- External: [Lexicon Genre Cleanup](https://www.lexicondj.com/manual/genre-cleanup), [Picard Genre Mapper](https://github.com/rdswift/picard-plugin-genre-mapper), [rapidfuzz](https://pypi.org/project/RapidFuzz/), [Discogs data (CC0)](https://data.discogs.com/), [MB data licence](https://musicbrainz.org/doc/About/Data_License)
- Related research: metadata-name-fixer
- Supersedes: none
- Superseded by: none
