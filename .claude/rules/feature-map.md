# Feature map — look before you build

`docs/features/*.toml` = the one registry of everything the app has, builds and plans: status, owning files, relations. `scripts/feature_map.py` overlays live git state (unmerged branches + every worktree's uncommitted files) onto it → who is touching which feature right now, where work overlaps. Goal: no chat rebuilds something that exists, sits on a branch, or was dropped; no chat walks into another chat's construction site.

## Session start — automatic

SessionStart hook prints `feature_map.py --brief`: status counts, active construction sites (branch/worktree → features), overlaps. Read it before planning.

## Before touching code — mandatory

1. `python scripts/feature_map.py --who <id|path|text>` for every feature or file the task changes. Prints status, files, deps + dependents, research doc, open todos, and which branches/worktrees touch it.
2. Feature has **non-stale active work** on another branch/worktree → do not start parallel work. Tell the user (`branch`, worktree, last commit) and offer: continue on that branch, stack on it, or wait.
3. Status `unmerged` → the code exists on a branch. Port or land it; never re-implement.
4. Status `dropped` → do not rebuild. Reason is in `notes`; ask the user before reviving.
5. Status `research` / `planned` with a research doc → read the doc first, don't contradict it.
6. Hub file (`app/main.py`, `app/services.py`, `frontend/src/main.jsx`, `api.js`, …) → shared by everything; check `--active` for other sites editing it.
7. Nothing matches → new work. Add the entry **first** (`status = "in_progress"`, `branch`), commit it with the first code commit.

## While / after working — same commit as the code

- Start → `status = "in_progress"`, `branch = "<branch>"`.
- New file → add to `paths` of the feature that owns it. Shared module → only its owner lists it; others use `depends_on`.
- Merged to `main` → `shipped`, or `partial` + `todo`/`notes` for known gaps. Drop `branch`/`pr`.
- Branch finished but not merged → `unmerged` + `branch` (+ `pr`).
- User mentions an idea in chat → `idea` entry right away. Ideas never live only in chat.
- Decided against → `dropped` + reason in `notes` (keeps it from being re-proposed).
- Before commit: `python scripts/feature_map.py --check` (CI runs it; fails on bad ids/refs or `shipped`/`partial` paths that match nothing).

## Status values

| Status | Meaning |
|---|---|
| `shipped` | on `main`, usable |
| `partial` | on `main`, known gaps/bugs (`todo`, `notes`) |
| `unmerged` | code exists on a branch, not in `main` |
| `in_progress` | being built right now |
| `planned` | decided/approved (`accepted_` doc), not started |
| `research` | research doc in flight |
| `idea` | backlog only |
| `dropped` | deliberately not doing — reason in `notes` |

## Entry schema (`[[feature]]` in `docs/features/<area>.toml`)

| Key | Req | Notes |
|---|---|---|
| `id` | ✓ | kebab-case, globally unique, stable (other entries reference it) |
| `group` | ✓ | sub-category inside the area file; reuse existing group names |
| `name` | ✓ | short German label (the map is the user's view) |
| `status` | ✓ | see table |
| `desc` | | one sentence, what it does for the user |
| `paths` | | owned files/globs; `dir/` = everything below. Never hub files |
| `routes` | | API prefixes |
| `branch`, `pr` | | where unmerged/in-progress work lives |
| `research` | | research-doc slug (no state prefix) — state is read from disk |
| `parent` | | sub-feature of another id (fix, follow-up, part) |
| `depends_on` | | ids this needs |
| `related` | | ids worth knowing about (overlap, sister feature) |
| `todo` | | open points, short |
| `notes` | | gaps, bugs, reasons, warnings |

Area files carry `[area]` (`id`, `name`, `order`, `desc`). Global settings (hubs, ignore, parked branches, stale days): `docs/features/_meta.toml`.

## Commands

```bash
python scripts/feature_map.py --who <id|path|text>   # before touching X
python scripts/feature_map.py --active               # all construction sites + overlaps
python scripts/feature_map.py --list [--status S] [--area A]
python scripts/feature_map.py --html --open          # interactive mindmap -> tmp/feature-map.html
python scripts/feature_map.py --check                # validate (CI)
python scripts/feature_map.py --coverage             # source files no feature owns
```

`/feature-map` wraps these.

## Relation to the research pipeline

Research docs plan a feature; the registry records that the feature exists and where it stands. Link them via `research = "<slug>"`. `--check` warns when the registry status contradicts the doc state (e.g. `planned` but doc is `inprogress_`).
