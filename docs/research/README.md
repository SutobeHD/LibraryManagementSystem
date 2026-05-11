# Research & Implementation Pipeline

Persistent feature lifecycle. Every idea moves through three stages — `research/` → `implement/` → `archived/`. The current **stage + state** lives in the **folder + filename prefix**, not in any frontmatter field. The file system is the single source of truth.

Files are never deleted — closed topics live in `archived/` forever as the historical record of why we did (or didn't do) something.

---

## Layout

```
docs/research/
├── README.md                   ← this file: how the pipeline works
├── _TEMPLATE.md                ← copy when starting a new topic
├── _INDEX.md                   ← live dashboard; mirrors the file system
│
├── research/                   ← Stage 1: gather info, frame, evaluate
│   ├── idea_<slug>.md
│   ├── exploring_<slug>.md
│   ├── evaluated_<slug>.md
│   └── parked_<slug>.md
│
├── implement/                  ← Stage 2: plan, review, build
│   ├── draftplan_<slug>.md
│   ├── review_<slug>.md
│   ├── rework_<slug>.md
│   ├── accepted_<slug>.md
│   ├── inprogress_<slug>.md
│   └── blocked_<slug>.md
│
└── archived/                   ← Stage 3: done, historical record
    ├── implemented_<slug>_<YYYY-MM-DD>.md
    ├── superseded_<slug>_<YYYY-MM-DD>.md
    └── abandoned_<slug>_<YYYY-MM-DD>.md
```

The slug stays the same through the entire lifecycle. Only the prefix and folder change. The date suffix is added only when entering `archived/`.

---

## Stages and prefixes

### research/ — gather and evaluate

The topic exists; we are figuring out what to do. No commitment yet.

| Prefix | Meaning | Typical next state |
|---|---|---|
| `idea_` | Topic exists, problem framed, no investigation yet | `exploring_` |
| `exploring_` | Active research: findings, constraints, options being captured | `evaluated_` (or `parked_`) |
| `evaluated_` | Investigation done, recommendation written, ready to plan | move to `implement/draftplan_` |
| `parked_` | Paused intentionally; no current owner | `exploring_` when picked up again |

### implement/ — plan, review, build

A concrete plan exists or is being built. This is where sign-off lives.

| Prefix | Meaning | Typical next state |
|---|---|---|
| `draftplan_` | Plan is being written | `review_` |
| `review_` | Plan ready, waiting for sign-off | `accepted_` or `rework_` |
| `rework_` | Review found gaps; goes back for revision | `draftplan_` |
| `accepted_` | Plan signed off; code not started yet | `inprogress_` |
| `inprogress_` | Code is being written | move to `archived/implemented_` |
| `blocked_` | Implementation paused (external dep, library bug) | `inprogress_` when unblocked |

### archived/ — historical record (terminal)

| Prefix | Meaning |
|---|---|
| `implemented_<slug>_<YYYY-MM-DD>` | Shipped. `architecture.md` / `FILE_MAP.md` / relevant `*-index.md` updated. |
| `superseded_<slug>_<YYYY-MM-DD>` | Replaced by a different approach. Successor linked in `## Decision / Outcome`. |
| `abandoned_<slug>_<YYYY-MM-DD>` | Dropped on purpose. Reason mandatory in `## Decision / Outcome`. |

---

## Transitioning between states

Every state change is **four actions in order** (the order matters so the working tree is consistent if you stop midway):

1. **`git mv <old-path> <new-path>`** — moves the file, preserves history
   (If the file is brand new and not yet tracked, plain `mv` is fine; `git add` will pick it up.)
2. **Append a line to `## Lifecycle`** in the doc — `YYYY-MM-DD — <stage>/<state>_ — <one-line context>`
3. **Update `_INDEX.md`** — move the topic's line to the new state's section
4. **Bump `last_updated`** in frontmatter (only if you also touched content; not required for a pure rename)

### Skipping states is allowed

Trivial topics can skip stages — `idea_` → `accepted_` in one sitting is fine if framing, drafting, and sign-off happen in one go. Every skipped stage still gets a Lifecycle line so the audit trail stays complete.

### Splits and merges

- **Split** (one research → N features): when leaving `evaluated_`, archive the source as `superseded_<slug>_<date>.md` and create N new `draftplan_<sub-slug>.md` files. The superseded doc lists all children.
- **Merge** (two plans → one): archive both as `superseded_*`, create one new plan, cross-link.

---

## Frontmatter — minimal

State is encoded in the file path. Frontmatter intentionally schlank:

```yaml
---
slug: <area>-<topic>            # stable for the topic's entire lifecycle
title: <one-line description>
owner: <name or "unassigned">
created: YYYY-MM-DD
last_updated: YYYY-MM-DD
tags: []                        # e.g. [recommender, soundcloud, ml]
related: []                     # slugs of related docs
---
```

Optional, only when applicable:
- `superseded_by: <slug>` — only on `archived/superseded_*` files
- `supersedes: [<slug>, ...]` — on plans that replace earlier ones

**Do not** put `status:` in frontmatter — it duplicates the filename prefix and drifts.

---

## Graduation: when `implemented_` lands

Archiving as `implemented_` is more than a rename. **Before** the move:

1. Update `docs/architecture.md` — data flows reflect the shipped behavior
2. Update `docs/FILE_MAP.md` — new files have one-line entries
3. Update relevant `docs/{backend,frontend,rust}-index.md` — new endpoints / symbols
4. Update `CHANGELOG.md` if the change is user-visible

The `## Decision / Outcome` section in the doc has a checkbox list for these so the audit trail is explicit.

---

## For AI assistants working in this repo

1. **Check `_INDEX.md` first.** If the user mentions a feature area, find its current state and stage before suggesting anything.
2. **Don't promote states unilaterally.** `review_` → `accepted_` requires explicit user sign-off. `inprogress_` → `implemented_` requires verifying code shipped AND docs are updated.
3. **Read the matching doc end-to-end** before suggesting an approach. The `## Findings` and `## Lifecycle` sections capture things already tried, ruled out, or constrained externally — invisible in the code.
4. **Skip the pipeline only for one-off conversational fixes.** Bug fixes, single-file refactors, plain questions don't need a research doc. Features touching ≥ 2 modules or with multiple plausible approaches → start in `research/idea_`.

---

## Relationship to other docs

| Doc | Purpose |
|---|---|
| `docs/research/` (this) | **Open / in-flight feature lifecycle** |
| `docs/architecture.md` | How shipped systems work today — data flows |
| `docs/FILE_MAP.md` | File-level navigation |
| `docs/{backend,frontend,rust}-index.md` | Symbol/endpoint indexes |
| `CHANGELOG.md` | What changed, version-tagged |

A doc graduates from `archived/implemented_` to *being the past* — the shipped behavior lives in `architecture.md` from then on; the research doc remains as historical "why".
