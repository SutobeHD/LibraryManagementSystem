# Research-first rule for features

**Feature touches ≥ 2 modules or has multiple plausible approaches → start in `docs/research/`.** Don't dive into code first.

## Workflow

1. Check `docs/research/_INDEX.md` — in-flight doc for this area? Read end-to-end before suggesting anything.
2. No existing doc → `/research-new <slug>` scaffolds `docs/research/research/idea_<slug>.md` from `_TEMPLATE.md`.
3. Move stages explicitly: `idea_` → `exploring_` → `evaluated_` → (sign-off) → `implement/draftplan_` → `review_` → `accepted_` → `inprogress_` → `archived/implemented_<date>`. State change = `git mv` + Lifecycle line + `_INDEX.md` update.
4. **Skip pipeline for:** one-off bug fixes, single-file refactors, plain questions, doc edits.

**You may NOT promote states unilaterally.** `review_` → `accepted_` and `inprogress_` → `implemented_` need explicit user sign-off.

Full stage/prefix cheat-sheet + transitions: `docs/research/README.md`.

## Writing style for research docs — Caveman+

Research docs are **persistent files**, not user output. Apply Caveman+ per `working-style.md`:

- Bullets > prose. Fragments OK. Drop articles/filler/hedges.
- Respect per-section word caps in `_TEMPLATE.md` (Problem ≤60 words, Findings entries ≤80 words, Recommendation ≤80 words).
- No "we considered", "it appears that", "in order to", "it should be noted", "after investigation". Direct subject + verb + object.
- No section meta-prose ("This section captures..."). The heading carries the meaning.

**Bad** (real example, 38 words for one fact):
> After investigation, it appears that the AcoustID free tier has a rate limit of 3 requests per second which would require us to consider batching strategies for the bulk lookup endpoint.

**Good** (8 words, same info):
> AcoustID 3 req/s. Bulk endpoint preferred. Batch by 100.

If you carry guidance blockquotes from old docs (e.g. `> Required from X onward...`), strip them — `_TEMPLATE.md` no longer ships them.

## Graduation: `implemented_` lands

Archive as `implemented_` = rename + doc-syncer hits. **Before** the move:

1. `docs/architecture.md` — data flows reflect shipped behavior
2. `docs/FILE_MAP.md` (or `/regen-maps`) — new files
3. `docs/{backend,frontend,rust}-index.md` — new endpoints / symbols
4. `CHANGELOG.md` if user-visible (`/changelog-bump`)

`## Decision / Outcome` checkbox list in the doc enforces the audit trail.
