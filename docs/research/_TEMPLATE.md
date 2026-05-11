---
slug: <area>-<topic>
title: <one-line title — what is being researched / built?>
owner: <name or "unassigned">
created: YYYY-MM-DD
last_updated: YYYY-MM-DD
tags: []
related: []
---

# <Same as title>

> **State**: derived from filename + folder. Do not store state in frontmatter.
> Start the file as `docs/research/research/idea_<slug>.md`. Rename + move on each transition (see `../README.md`).

## Lifecycle

> Append-only audit trail. One line per `git mv`. Newest at the bottom.

- YYYY-MM-DD — `research/idea_` — created

---

## Problem

> Required from `idea_` onward. Keep under 100 words. What are we solving? Why does it matter? What happens if we don't?

## Goals / Non-goals

**Goals**
- …

**Non-goals** (deliberately out of scope)
- …

## Constraints

> External facts that bound the solution space — API rate limits, existing data shape, performance budgets, legal/licensing, team capacity. Cite source where possible.

- …

## Open Questions

> Numbered. Each one should be resolvable (yes/no, or "X vs Y"), not open-ended philosophy.

1. …

## Findings / Investigation

> Required from `exploring_` onward. Append dated subsections as you learn. Never edit past entries — supersede with a new one.

### YYYY-MM-DD — <short label>
…

## Options Considered

> Required by `evaluated_`. For each viable approach: sketch (2-4 lines), pros, cons, effort (S/M/L/XL), risk.

### Option A — <name>
- Sketch:
- Pros:
- Cons:
- Effort: S/M/L/XL
- Risk:

### Option B — <name>
- Sketch:
- Pros:
- Cons:
- Effort:
- Risk:

## Recommendation

> Required by `evaluated_`. Which option, what we wait on before committing.

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
