# Research & Implementation Pipeline

Persistent feature lifecycle. Every idea moves: `research/` → `implement/` → `archived/`. **Stage + state = folder + filename prefix**, not frontmatter. File system is single source of truth.

Files are never deleted — closed topics live in `archived/` forever as historical record.

Doc style: **Caveman+** (fragments, bullets, no prose). Per-section word caps in `_TEMPLATE.md`. Full rule + bad/good example in `.claude/rules/research-pipeline.md`.

---

## Layout

```
docs/research/
├── README.md                   ← this file
├── _TEMPLATE.md                ← copy for new topic
├── _INDEX.md                   ← live dashboard
│
├── research/                   ← Stage 1: gather, frame, evaluate
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
└── archived/                   ← Stage 3: terminal
    ├── implemented_<slug>_<YYYY-MM-DD>.md
    ├── superseded_<slug>_<YYYY-MM-DD>.md
    └── abandoned_<slug>_<YYYY-MM-DD>.md
```

Slug stays through entire lifecycle. Only prefix + folder change. Date suffix added when entering `archived/`.

---

## Stages and prefixes

### research/ — gather and evaluate

| Prefix | Meaning | Typical next |
|---|---|---|
| `idea_` | Topic exists, problem framed, no investigation | `exploring_` |
| `exploring_` | Active research: findings, constraints, options captured | `evaluated_` (or `parked_`) |
| `evaluated_` | Investigation done, recommendation written | `implement/draftplan_` |
| `parked_` | Paused, no owner | `exploring_` when picked up |

### implement/ — plan, review, build

| Prefix | Meaning | Typical next |
|---|---|---|
| `draftplan_` | Plan being written | `review_` |
| `review_` | Plan ready, awaiting sign-off | `accepted_` or `rework_` |
| `rework_` | Review found gaps | `draftplan_` |
| `accepted_` | Signed off, code not started | `inprogress_` |
| `inprogress_` | Code being written | `archived/implemented_` |
| `blocked_` | Paused (external dep, library bug) | `inprogress_` when unblocked |

### archived/ — terminal

| Prefix | Meaning |
|---|---|
| `implemented_<slug>_<YYYY-MM-DD>` | Shipped. `architecture.md` / `FILE_MAP.md` / `*-index.md` updated. |
| `superseded_<slug>_<YYYY-MM-DD>` | Replaced. Successor in `## Decision / Outcome`. |
| `abandoned_<slug>_<YYYY-MM-DD>` | Dropped. Reason mandatory in `## Decision / Outcome`. |

---

## Transitioning between states

Four actions, in order (consistent working tree if interrupted):

1. **`git mv <old> <new>`** — preserves history. (New file not yet tracked → plain `mv` + `git add`.)
2. **Append `## Lifecycle` line:** `YYYY-MM-DD — <stage>/<state>_ — <one-line context>`
3. **Update `_INDEX.md`** — move topic to new state's section.
4. **Bump `last_updated`** in frontmatter (only if content touched too; not for pure rename).

### Skipping states OK

Trivial topics: `idea_` → `accepted_` in one sitting if framing+drafting+sign-off happen together. Every skipped stage still gets a Lifecycle line — audit trail stays complete.

### Splits / merges

- **Split** (one research → N features): leaving `evaluated_` → archive source as `superseded_<slug>_<date>.md`, create N new `draftplan_<sub-slug>.md`. Superseded doc lists all children.
- **Merge** (two plans → one): archive both as `superseded_*`, create one new plan, cross-link.

---

## AI Routines & Tasks marker

Three remote routines work the pipeline autonomously while you sleep / are in uni. They only touch docs you've explicitly opted in.

### Marker (two gates)

**Gate 1 — Frontmatter:**
```yaml
ai_tasks: true
```

**Gate 2 — `## AI Tasks` section** (auto-included by `_TEMPLATE.md`):
```markdown
## AI Tasks
- [ ] resolve Q3: AcoustID rate limit
- [ ] grep `_db_write_lock` users in app/
- [ ] generate draftplan
```

Routine picks the first unchecked item it owns by **item prefix**:

| Prefix | Routine | Action |
|---|---|---|
| `resolve Q<N>:` | research-exploring-push | Web+code lookup, appends finding to that Open Question |
| `investigate:` | research-exploring-push | Web+code research, appends to `## Findings / Investigation` |
| `grep <pat> in <area>` | research-exploring-push | Codebase grep, summarised into Findings |
| `web: <query>` | research-exploring-push | WebSearch, summarised into Findings |
| `promote to <state>` | research-exploring-push | `git mv` to next state if preconditions met |
| `generate draftplan` | research-draftplan-scout | Creates `implement/draftplan_<slug>.md` from a fully-resolved `evaluated_` doc |

After processing: routine ticks `- [x] <original text> — done YYYY-MM-DD`, appends Lifecycle line, opens PR.

### Routines

| Name | Cron UTC | Berlin | Scope |
|---|---|---|---|
| `research-exploring-push` | `0 2,14 * * *` | 04:00 + 16:00 | 1 marked task in any `ai_tasks: true` doc per run |
| `research-triage-report` | `0 5 * * *` | 07:00 | Read-only audit + counts open AI tasks per doc → GitHub Issue |
| `research-draftplan-scout` | `0 10 * * *` | 12:00 | 1 `generate draftplan` task in `evaluated_` docs per run |

Manage at https://claude.ai/code/routines.

### Hard rules

- Marker is **opt-in per doc** — routines skip everything without `ai_tasks: true`.
- Routines are **docs-only** — never touch `app/`, `frontend/`, `src-tauri/`, `tests/`.
- Promotions to `review_`/`accepted_`/`inprogress_`/`implemented_` are **never** automatable via marker — user sign-off only.
- PR on branch `routine/<purpose>-<slug-or-date>`, never direct main.
- Routine can also be told `promote to evaluated_` as an explicit task — preconditions checked before `git mv`.

## Graduation: `implemented_` lands

Rename + doc updates. **Before** the `git mv` → `archived/implemented_`:

1. `docs/architecture.md` — data flows reflect shipped behavior
2. `docs/FILE_MAP.md` — new files have one-line entries
3. `docs/{backend,frontend,rust}-index.md` — new endpoints/symbols
4. `CHANGELOG.md` if user-visible

`## Decision / Outcome` section in doc has checkbox list — audit trail explicit.

After `implemented_`, shipped behavior lives in `architecture.md`; research doc remains as historical "why".
