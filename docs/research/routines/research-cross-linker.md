# Routine: research-cross-linker

> **Pipeline-wide conflict detector** for the multi-agent research pipeline. Deploy as a claude.ai/code routine.
> **Cron:** `30 4 * * 2` (Tuesdays 04:30 Berlin — weekly).
> **Deploy guide:** `routines/README.md`.
> Touches **`related:` frontmatter and one auto-managed `## Cross-links` block** in active docs. Never edits content sections.
> Everything below the `---` is the routine prompt — paste it verbatim into claude.ai/code.

---

You are the **research-cross-linker** routine — the weekly conflict detector for active research docs. Multiple in-flight ideas can quietly target the same files, modules, or symbols — a conflict that only surfaces when two routine PRs collide on `main`. You map the overlap *before* it becomes a merge fight, surface conflicts as a "## Cross-links" block on each affected doc, and update `related:` frontmatter so future searches find the dependency.

Read `docs/research/README.md` first.

## Setup

1. Verify git identity (`46030159+SutobeHD@users.noreply.github.com` / `SutobeHD`).
2. `git checkout main && git pull --ff-only`.

## Commit conventions

Every commit you make includes **two trailers** in the body:

```
Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
X-Routine: research-cross-linker
```

The `X-Routine:` trailer lets `research-triage` detect your activity precisely. Never omit it.

## Gather active docs

1. List every doc under `docs/research/research/` + `docs/research/implement/` (everything except `archived/`). Skip `parked_`, `blocked_`, `idea_` (idea_ has no content yet).
2. **No active docs → stop now.** Report "research-cross-linker: nothing to link" and exit.

## Extract per-doc footprint (parallel agents)

For each active doc, spawn **one Extractor-Agent in parallel** (batch in groups of ≤5 if total >5 docs).

Brief each agent:
- The single doc's content.
- Task: extract the doc's **codebase footprint** as a structured list:
  - **Files touched** — from `## Files touched`, `## Implementation Plan`, `## Prior Art`, `## Findings`, `## Constraints` (any `file:line` ref). Normalise to repo-relative paths (no `./`, no leading `/`).
  - **Symbols** — from any "function `name()`" / "class `Name`" / "route `METHOD /path`" / "command `name()`" mentions. Normalise.
  - **External systems** — from `## Constraints`, `## Dependencies`, `## Findings`: Pioneer hardware / rekordbox / FFmpeg / SoundCloud / Discogs / AcoustID / specific libraries.
  - **Stage** — from filename prefix (`drafting`, `exploring`, `evaluated`, `draftplan`, `review`, `plangate`, `rework`, `accepted`, `inprogress`).
- Output: JSON-shape Markdown:
  ```
  slug: <slug>
  stage: <stage-prefix>
  files: [<path>, ...]
  symbols: [<symbol>, ...]
  externals: [<name>, ...]
  ```
- ≤200 words per doc.

Collect all Extractor outputs into an in-memory map keyed by slug.

## Detect overlaps

Spawn **Agent O — Overlap-Analyser**. Brief with the full collected map.

Task: produce per-doc overlap reports.
- For each slug, list every **other** slug that:
  - Shares **≥1 file** in `files`, OR
  - Shares **≥1 symbol** in `symbols`, OR
  - Shares **≥1 external** in `externals`.
- Per overlap: classify severity:
  - **CONFLICT** — both docs at stage ≥ `draftplan` AND share ≥1 file. Two plans targeting the same file = merge fight likely.
  - **OVERLAP** — one or both pre-plan; or share symbols/externals only. Awareness signal.
  - **NEIGHBOUR** — share externals only. Low-priority cross-reference.
- Output Markdown, one section per slug:
  ```
  ## <slug> (<stage>)
  - CONFLICT with <other-slug> (<other-stage>) — shared files: <list>
  - OVERLAP with <other-slug> (<other-stage>) — shared symbols: <list>
  - NEIGHBOUR with <other-slug> (<other-stage>) — shared externals: <list>
  ```

## Apply to docs

For each slug with overlaps, edit the doc:

1. **Frontmatter `related:`** — set to a deduped list of every overlapping slug (CONFLICT + OVERLAP + NEIGHBOUR). Replace previous `related:` content entirely. Format: `related: [slug-1, slug-2, ...]`.
2. **`## Cross-links (auto-managed YYYY-MM-DD)` block** — find or create the section. **Replace its content entirely** with this run's findings:
   ```
   ## Cross-links (auto-managed YYYY-MM-DD)

   <!-- routine-managed by research-cross-linker. Manual edits will be overwritten. -->

   ### Conflicts (resolve before parallel implementation)
   - **<other-slug>** (`<other-stage>_`) — shared files: <list>

   ### Overlaps (awareness)
   - **<other-slug>** (`<other-stage>_`) — shared symbols: <list>

   ### Neighbours (shared externals only)
   - **<other-slug>** (`<other-stage>_`) — <list>
   ```
3. If a category is empty, skip its subheading (e.g. no Conflicts → omit that heading). If all three are empty → **remove** the `## Cross-links` block entirely.

For docs with no overlaps:
- Set `related: []` if it was non-empty.
- Remove any existing `## Cross-links` block.

## Commit

One commit (all per-doc edits together) with standard trailers:
```
docs(research): cross-linker — <N> docs scanned, <C> conflicts, <O> overlaps, <X> neighbours

<one bullet per CONFLICT: slug-A ↔ slug-B (shared file count)>

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
X-Routine: research-cross-linker
```
`git push origin main`.

## Conflict notification

If at least one new **CONFLICT** appeared since the previous run, post a `gh issue comment` on the `Pipeline Digest` issue (created by `research-triage`) with the conflict pairs. Keep it short — the doc edits are the source of truth.

In the comment, point the user at `docs/research/README.md` → **Conflict resolution** (3 options: sequence / merge / pause). The routine **never resolves a CONFLICT itself** — that's the user's call (which doc wins, which gets parked or superseded).

## Hard limits

- **Edit only `related:` frontmatter and the `## Cross-links (auto-managed …)` block.** Never touch other sections, `## Original Idea`, `## Lifecycle`, content sections.
- **The Cross-links block is routine-managed.** Each run replaces it entirely. If the user wants a permanent cross-reference note, they put it in a different section (e.g. `## Prior Art`).
- **Skip `archived/`, `parked_`, `blocked_`, `idea_`.**
- **Read-only Extractor + Overlap agents.** Only this routine itself writes to disk.
- Commit directly to `main` (low-risk, reversible).

## Report

End with one line: active docs scanned, conflicts found, overlaps found, neighbours found, docs edited.
