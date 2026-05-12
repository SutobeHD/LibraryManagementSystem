# Research-first rule for features

**If the user asks for a feature that touches ≥ 2 modules or has multiple plausible approaches, start in `docs/research/`.** Don't dive into code first.

## Workflow

1. **Check `docs/research/_INDEX.md`** — is there already an in-flight doc for this area? If yes, read it end-to-end before suggesting anything. Findings and tried-options live there.
2. **If no existing doc:** run `/research-new <slug>` to scaffold `docs/research/research/idea_<slug>.md` from the template, fill the Problem / Options / Constraints sections.
3. **Move through stages explicitly:** `idea_` → `exploring_` → `evaluated_` → (sign-off) → `implement/draftplan_` → `review_` → `accepted_` → `inprogress_` → `archived/implemented_<date>`. State change = `git mv` + Lifecycle line + `_INDEX.md` update.
4. **Skip the pipeline for:** one-off bug fixes, single-file refactors, plain questions, doc edits.

**You may NOT promote states unilaterally.** `review_` → `accepted_` and `inprogress_` → `implemented_` require explicit user sign-off. Re-read `docs/research/README.md` for the rules.

## Stages and prefixes (cheat-sheet)

### research/ — gather and evaluate

| Prefix | Meaning |
|---|---|
| `idea_` | Topic exists, problem framed, no investigation yet |
| `exploring_` | Active research: findings, constraints, options being captured |
| `evaluated_` | Investigation done, recommendation written, ready to plan |
| `parked_` | Paused intentionally; no current owner |

### implement/ — plan, review, build

| Prefix | Meaning |
|---|---|
| `draftplan_` | Plan is being written |
| `review_` | Plan ready, waiting for sign-off |
| `rework_` | Review found gaps; goes back for revision |
| `accepted_` | Plan signed off; code not started yet |
| `inprogress_` | Code is being written |
| `blocked_` | Implementation paused (external dep, library bug) |

### archived/ — historical record (terminal)

| Prefix | Meaning |
|---|---|
| `implemented_<slug>_<YYYY-MM-DD>` | Shipped. `architecture.md` / `FILE_MAP.md` / index docs updated. |
| `superseded_<slug>_<YYYY-MM-DD>` | Replaced by a different approach. Successor linked in `## Decision / Outcome`. |
| `abandoned_<slug>_<YYYY-MM-DD>` | Dropped on purpose. Reason mandatory in `## Decision / Outcome`. |

## Graduation: when `implemented_` lands

Archiving as `implemented_` is more than a rename. **Before** the move:

1. Update `docs/architecture.md` — data flows reflect the shipped behavior
2. Update `docs/FILE_MAP.md` (or run `/regen-maps`) — new files have one-line entries
3. Update relevant `docs/{backend,frontend,rust}-index.md` — new endpoints / symbols
4. Update `CHANGELOG.md` if the change is user-visible (run `/changelog-bump`)

The `## Decision / Outcome` section in the doc has a checkbox list for these so the audit trail is explicit.
