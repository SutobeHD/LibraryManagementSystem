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

## AI Tasks marker — opt-in routine workload

Three remote routines (`research-exploring-push`, `research-triage-report`, `research-draftplan-scout`) advance docs autonomously. They process **only** docs that opt in via marker. Two-gate system:

**Gate 1 — Frontmatter flag:**
```yaml
ai_tasks: true
```
Without `true`, routine skips the doc entirely.

**Gate 2 — `## AI Tasks` section:**
```markdown
## AI Tasks
- [ ] resolve Q3: AcoustID rate limit
- [ ] grep `_db_write_lock` users in app/
- [ ] generate draftplan
```
Routine picks the first unchecked item whose prefix it owns (see `_TEMPLATE.md` AI Tasks HTML comment for the routing table). Done → ticks `- [x]` + `— done YYYY-MM-DD`, appends Lifecycle line, opens PR.

**When to use:**
- Doc has work the routine can do mechanically (grep, web lookup, well-scoped question with external answer, structural promotion with clear preconditions, draftplan from a fully-resolved evaluated_ doc).
- You're OK with the change landing as a PR while you sleep / are in uni.

**When NOT to use:**
- Decision needs your taste/judgment (Option A vs B trade-off, architecture-shaping choices).
- Task touches code, not just docs — routines are docs-only.
- You're mid-edit on the doc — set flag back to `false` to pause.

**Promotions allowed via marker:**
- `exploring_` → `evaluated_` (when all Open Qs resolved + Recommendation written)
- `evaluated_` → DraftPlan creation (when Recommendation has concrete picks)

**Still gated by you (no marker allows):**
- `review_` → `accepted_`
- `inprogress_` → `implemented_`

## Graduation: `implemented_` lands

Archive as `implemented_` = rename + doc-syncer hits. **Before** the move:

1. `docs/architecture.md` — data flows reflect shipped behavior
2. `docs/FILE_MAP.md` (or `/regen-maps`) — new files
3. `docs/{backend,frontend,rust}-index.md` — new endpoints / symbols
4. `CHANGELOG.md` if user-visible (`/changelog-bump`)

`## Decision / Outcome` checkbox list in the doc enforces the audit trail.
