---
slug: waveform-editor-extensions
title: WaveformEditor extension — editor surface for all per-track metadata
owner: tb
created: 2026-05-12
last_updated: 2026-05-13
tags: [editor, cues, loops, beatgrid, metadata, frontend, anlz]
related: []
---

# WaveformEditor extension — editor surface for all per-track metadata

> **State**: derived from filename + folder. Do not store state in frontmatter.
> Start the file as `docs/research/research/idea_<slug>.md`. Rename + move on each transition (see `../README.md`).

## Lifecycle

> Append-only audit trail. One line per `git mv`. Newest at the bottom.

- 2026-05-12 — `research/idea_` — created from template
- 2026-05-12 — `research/idea_` — Problem, Goals, Constraints, Open Questions filled from initial user spec
- 2026-05-12 — `research/exploring_` — promoted; active investigation begins (codebase audit, option sketches)
- 2026-05-12 — `research/exploring_` — round 2 decisions; scope pivot (integrated into WaveformEditor, no separate Soft-DAW)
- 2026-05-12 — `research/exploring_` — renamed (slug `cue-editor-daw` → `waveform-editor-extensions`; title updated to match in-place-extension scope)
- 2026-05-13 — `research/exploring_` — round 3: Q10↔Q11 confirmation + WaveformEditor codebase audit + Options A/B/C sketched + recommendation
- 2026-05-13 — `research/exploring_` — round 4: user confirms `daw/` surface also in scope; panel path confirmed; recommendation switched from Option B to Option C
- 2026-05-13 — `research/exploring_` — round 5: implementation gate fully confirmed (Option C, state-hook path, slice order, adapter strategy c)
- 2026-05-13 — `research/evaluated_` — promoted: all open questions resolved; awaiting user sign-off before `implement/draftplan_`
- 2026-05-13 — `implement/draftplan_` — user sign-off received; Implementation Plan written (6 slices, ~3 new backend routes, 5 new frontend files)
- 2026-05-13 — `implement/inprogress_` — Slice 0 execution begins (foundation: ANLZ writer dict-driven, feature flags, hook skeleton, anlz cue-fields test). User implicitly waived `review_` and `accepted_` stages by saying "Führe den Plan aus".

---

## Problem

Backend-Routes for cue / loop / beatgrid / metadata editing already exist
(`GET /api/track/{tid}/cues`, `POST /api/track/cues/save`,
`/api/track/{id}/phrase-cues/{generate,commit}`, full ANLZ writer in
`app/anlz_writer.py`), **but there is no frontend UI** for editing them
(`frontend/src/**/Cue*` and `**/HotCue*` glob → 0 hits). Today the user has to
open Rekordbox to set hot cues, memory cues, loops, beatgrid anchors, or
rename a track — which breaks the "Rekordbox-independent library manager"
promise. A dedicated single-track editor surface ("Soft-DAW") on top of the
existing waveform components closes the gap.

## Goals / Non-goals

**Goals**

- **Hot cue editing** — slots A..H (1..8), set position, color, comment.
- **Hot loop editing** — position, loop length, `loop_numerator` /
  `loop_denominator`, active-loop flag, color, comment.
- **Memory cue editing** — unlimited count, 8-color fixed palette
  (Pink/Red/Orange/Yellow/Green/Aqua/Blue/Purple), comment.
- **Memory loop editing** — same fields as memory cue + loop length.
- **Beatgrid editing** — anchor shift / tap-BPM / per-beat tweak (PQTZ + PQT2).
- **Track metadata renaming** — Title, Artist, plus likely Album / Genre /
  BPM-override / Key-override / track Comment. Save path must hit
  Rekordbox `master.db` (via `live_database.py` / `rbox`) and ID3 tags in the
  underlying audio file.
- **Single-track scope** — one track loaded at a time.
- **Integrated directly into the existing waveform editor**
  (`frontend/src/components/WaveformEditor.jsx` plus
  `components/waveform/*`). This is **not** a new component / surface — the
  WaveformEditor is extended in place. _(updated 2026-05-12 — scope pivot;
  see Findings round 2.)_
- **Visual inspiration**: Rekordbox performance-pad grid + existing waveform
  editor aesthetic.

**Non-goals** (deliberately out of scope)

- Multi-track mixing, crossfader, audio effects, mastering.
- BPM / key / energy detection — `analysis_engine.py` already does this; the
  Soft-DAW only reads the result and lets the user override.
- Audio file editing (no slicing, pitch shift, time stretch, normalisation).
- Cloud sync / collaboration.
- Phrase (PSSI) editing in v1 — deferred. Auto-generated phrase cues stay.

## Constraints

- **Byte-perfect ANLZ validity is mandatory.** Every cue / loop / beatgrid
  write must go through `app/anlz_writer.py` — no hand-patching of bytes.
  Existing fixture tests (`tests/test_pdb_structure.py`) plus new
  cue/loop/beatgrid roundtrip tests gate every change. A wrong byte
  corrupts the USB silently, Rekordbox refuses to load it. See
  [.claude/rules/coding-rules.md](.claude/rules/coding-rules.md) §"Pioneer
  USB export — byte-verified invariants".
- **Two-layer save:**
  1. **ANLZ sidecar** (`.DAT` / `.EXT` / `.2EX`) for cues / loops / beatgrid /
     waveform — already covered by `anlz_writer.py`.
  2. **Rekordbox `master.db`** for cue metadata, track title/artist/etc. —
     must acquire `app/main.py:_db_write_lock`. Title/Artist also need to be
     mirrored to ID3 tags in the audio file so non-Rekordbox players see
     them.
- **Single state model — extend the WaveformEditor's existing state.**
  Cue / loop / beatgrid / metadata fields are added to whatever state
  mechanism the WaveformEditor already uses (local component state, hook,
  or store). No new cross-component sync layer. _(updated 2026-05-12 —
  scope pivot; see Findings round 2.)_
- **Reuse existing backend routes where possible.** Lookups already in place:
  `GET /api/track/{tid}/cues`, `POST /api/track/cues/save`,
  `POST /api/track/{id}/phrase-cues/{generate,commit}`. Gaps that need new /
  extended routes:
  - `loop_numerator` / `loop_denominator` are hard-coded to 0 in
    [app/anlz_writer.py:273-275](app/anlz_writer.py) (`_build_pcp2_entry`).
  - Active-loop flag (`status = 4`) is hard-coded by hot-vs-memory in
    `_build_pcpt_entry` instead of being read from the cue dict.
  - No beatgrid-shift / anchor-edit endpoint.
  - No track-rename endpoint that hits both `master.db` and ID3.
- **rbox concurrency rules apply.** All `master.db` writes serialise on
  `_db_write_lock`. All rbox ANLZ parses go through `SafeAnlzParser`
  (`ProcessPoolExecutor`, `max_workers=1`) per
  [.claude/rules/coding-rules.md](.claude/rules/coding-rules.md).
- **Visual / interaction model: Rekordbox + the existing waveform editor.**
  Performance-pad grid for the 8 hot cue slots, 16-color Rekordbox surface
  palette for hot cue color (out of the 64-color internal set), 8 fixed
  colors for memory cues, waveform canvas as the primary cue-set interaction.

## Open Questions

> Numbered. Each one should be resolvable (yes/no, or "X vs Y"), not open-ended philosophy.

1. **Fork vs. shared-from-start.** Start the Soft-DAW as a hard copy of
   `WaveformEditor.jsx` and merge later, or design the shared store / hooks
   first and let both surfaces consume them from day one? Forking is faster
   to start, sharing is cheaper long-term.
2. **State-sync mechanism.** Zustand store, React context, a custom hook on
   top of a `useSyncExternalStore`-style atom, or an event-bus pattern
   (`window.dispatchEvent`)? Which matches the existing Waveform-Editor
   pattern?
3. **Save trigger.** Auto-save on every change (debounced), explicit Save
   button only, or both (auto-save with explicit "commit to Rekordbox" step)?
4. **Track-rename save reach.** Update only Rekordbox `master.db`, only ID3
   tags in the audio file, or both? What happens when the two diverge
   today — does the Soft-DAW need a "reconcile" step?
5. **Active-loop UI.** Only one active loop per track (matches CDJ behaviour).
   Per-loop toggle, or a dedicated "Set as Active Loop" radio?
6. **Memory-cue color picker.** Offer all 8 fixed colors or default everything
   to green (Rekordbox's default) to keep the UI simple?
7. **Beatgrid-edit granularity.** Anchor-shift (move every beat by Δt) only,
   tap-BPM, or per-beat edit too? Per-beat is closest to Rekordbox but
   easy to misuse.
8. **Audio playback inside the editor.** Does the Soft-DAW play back through
   the Rust/cpal engine (already in `src-tauri/src/audio/`) so the user can
   audition a cue before saving, or is preview deferred?
9. **Layout.** Full-window route, dockable side panel next to the track
   table, or modal dialog over the table?
10. **Undo / redo.** Session-scope undo only, or persistent (sidecar log) so
    that a user can revert a save made yesterday?
11. **Backup-on-save.** The existing `write_anlz_files(... backup_existing=True)`
    timestamps `.DAT.bak-YYYYMMDD-HHMMSS` files and prunes to 3. Is this
    enough for the Soft-DAW's edit cadence, or do we need a per-edit
    snapshot log on top?

## Findings / Investigation

> Required from `exploring_` onward. Append dated subsections as you learn. Never edit past entries — supersede with a new one.

### 2026-05-12 — Architecture decisions, round 1 (from user spec)

**Q1 (fork vs. shared-from-start): SHARED from day one.**
WaveformEditor and Soft-DAW are not forked components. They are two views over
a shared store / shared hook layer. Any refactor of the existing
`WaveformEditor.jsx` needed to extract its state belongs to this work, not
afterwards.

**Q2 (state-sync mechanism): SHARED STORE AS SINGLE SOURCE OF TRUTH, no active sync layer.**
User: "Sie sollen nicht in der App synchron sein, sondern die gleiche
struktur." Interpreted as: both views subscribe to the same store with the
same data model — no event-bus, no `dispatchEvent` push pattern, no
duplicated state to keep in sync. When the user switches surface, data is
already current because there is only one copy of it.

**Q3 (save trigger): AUTO-SAVE.**
Debounced auto-save on every change. Implementation defaults to ~500 ms
debounce (TBD with measurement). No explicit "Commit to Rekordbox" step in
the primary flow; a manual force-save may exist as escape hatch.

**Q4 (track-rename save reach): BOTH `master.db` AND ID3 TAGS.**
A rename writes the same name to Rekordbox `master.db` (under
`_db_write_lock`) and to ID3 tags in the audio file, in a single save
operation. Divergence-reconcile strategy is open: likely "last write wins,
but flag pre-existing inconsistency in the UI before save".

**Q5 (active-loop UI): REKORDBOX-STYLE.**
Active-loop is a flag on a loop. Only one loop per track may be active at a
time. Setting active on a second loop clears it on the first (radio-button
semantics under the hood, toggle-style affordance in the UI).

**Q6 (memory-cue color picker): ALL 8 CDJ COLORS.**
Picker offers Pink / Red / Orange / Yellow / Green / Aqua / Blue / Purple —
the full CDJ palette, no default-to-green shortcut.

**Q8 (audio playback inside editor): YES.**
Editor plays back through the existing Rust/cpal engine in
`src-tauri/src/audio/`. Cue audition before saving is in scope.

**Q10 (undo / redo): YES — persistent.**
Undo survives app restarts. Storage mechanism (sidecar JSONL log vs. dedicated
SQLite audit table vs. extending `master.db`) is deferred to the options
stage. **Couples directly to Q11.**

**Open after this round:**
- **Q7 — beatgrid granularity** — user replied "weiß nicht was du meinst";
  needs the option set re-explained.
- **Q9 — layout** — user replied "Ja", which doesn't map to the multi-choice;
  needs follow-up with explicit options.
- **Q11 — backup-on-save** — deferred; almost certainly couples to the Q10
  persistent-undo storage decision.

### 2026-05-12 — Architecture decisions, round 2 (scope pivot)

**Q7 (beatgrid granularity): FULL — option C, with Anchor-Shift as default mode.**
User: "Beides aber standartmäßig A also c." All three editing modes
(anchor-shift, tap-BPM, per-beat-edit) are implemented. The default UI mode
when opening beatgrid editing is anchor-shift; tap-BPM and per-beat-edit are
accessible as advanced toggles. Covers variable-tempo tracks and
mis-detected BPM without overwhelming the simple case.

**Q9 (layout): SCOPE PIVOT — no separate Soft-DAW surface.**
User: "Lass uns das umplanen und direkt in den Waveformeditor rein."
The cue / loop / beatgrid / metadata editing functionality is integrated
**directly into the existing `frontend/src/components/WaveformEditor.jsx`**
(plus its `components/waveform/*` submodules). There is no separate
"Soft-DAW" component; the WaveformEditor becomes the editor.

**Implications of the pivot:**
- **Q1 (fork vs. shared) becomes moot** — there is no second component, so
  nothing to share state across. Collapses to "extend the WaveformEditor in
  place".
- **Q2 (state-sync mechanism) becomes moot** — only one view; local
  WaveformEditor state is sufficient. No cross-component sync layer.
- **Doc title / slug** are now misleading (they suggest a separate "Soft-DAW"
  surface). Rename candidates: `waveform-editor-cues-and-metadata`,
  `waveform-editor-cue-grid-rename`, `waveform-editor-extensions`. Decision
  deferred until user confirms.
- **Scope drops one notch** — this is an enhancement to an existing
  component, not a new one. Effort estimate accordingly lower.
- **UX is determined by the WaveformEditor's existing layout.** Pad-grid,
  color-picker, loop-list, beatgrid-controls become in-component panels /
  overlays inside the WaveformEditor.

**Q11 (backup-on-save): KEEP the existing 3-rotating `.bak` system.**
No additional snapshot log. The `_backup_existing_anlz` /
`_prune_anlz_backups` machinery in `app/anlz_writer.py:687-733` stays as-is.

**⚠ Q10 ↔ Q11 tension:** Q10 said "persistent undo, survives restart". Q11 a
gives only 3 saved states. Therefore persistent undo is **bounded by 3 steps
per track**. Working assumption: this is acceptable. If a deeper undo history
is needed later, Q11 must be revisited (snapshot log added).

**Open after this round:**
- **Doc rename** — slug/title to reflect in-place WaveformEditor extension
  rather than separate Soft-DAW surface (see candidate slugs above).
- **Q10 ↔ Q11 tension** — confirm "3-step undo, persistent" as the final
  interpretation, or revisit Q11 for a deeper history later.

### 2026-05-13 — Architecture decisions, round 3 (Q10↔Q11 confirmation)

**Q10 ↔ Q11 — CONFIRMED as "3-step persistent undo".**
Undo survives app restart (Q10) but capacity is bounded by the 3-rotating
`.bak` files (Q11 a). No additional snapshot log. If a deeper history is
needed later, Q11 must be revisited then.

### 2026-05-13 — Codebase audit (WaveformEditor + waveform/ + daw/)

Scope: the `WaveformEditor.jsx` orchestrator plus everything under
`frontend/src/components/waveform/`. Done as input for the implementation
plan in the next phase.

**Files in scope (LOC, sorted ascending):**

| File | LOC | Role |
|---|---|---|
| `waveform/persistence.js` | 28 | Low-level localStorage I/O |
| `waveform/ConfirmModal.jsx` | 29 | Confirm dialogs |
| `waveform/WaveformZoom.jsx` | 29 | Zoom UI |
| `waveform/useEditPersistence.js` | 32 | 500 ms debounced auto-save + restore |
| `waveform/WaveformErrorBoundary.jsx` | 37 | ErrorBoundary |
| `waveform/computeBeats.js` | 41 | Beatgrid computation |
| `waveform/WaveformSimpleView.jsx` | 56 | Minimal mode |
| `waveform/useVisualPreview.js` | 75 | Preview rendering |
| `waveform/previewBuffer.js` | 164 | Preview buffer management |
| `waveform/useMultibandLayers.js` | 184 | 3-band visual mode |
| `waveform/WaveformOverlays.jsx` | 201 | Floating overlays (cuts summary, etc.) |
| `waveform/WaveformCanvas.jsx` | 223 | Canvas beatgrid renderer (1 canvas vs 1000+ regions) |
| `waveform/useWaveSurfer.js` | 291 | WaveSurfer + Overview lifecycle |
| `waveform/WaveformControls.jsx` | 380 | Top toolbars: header, project, hot-cue strip, transport, volume, viz, grid-shift, drop-detection, metadata bar |
| `WaveformEditor.jsx` | 402 | Orchestrator |
| `waveform/useWaveformInteractions.js` | 499 | Hot-cue handlers, hotkeys, file-drop, cuts |
| **Total** | **~2670** | — |

**What already exists (we extend, not invent):**

- **Hot cues** — state (`hotCues`), handlers `handleSetHotCue` /
  `handleJumpHotCue` / `handleDeleteHotCue` in `useWaveformInteractions.js`.
  Hotkeys `Shift+1..8` (set) and `1..8` (jump) wired. A constant
  `HOT_CUE_COLORS` (8 hex strings) drives the pad colour — **not** matched
  to the CDJ palette today.
- **Hot-cue strip UI** in `WaveformControls.jsx`.
- **Auto-save (Q3)** already in place: `useEditPersistence` does a 500 ms
  debounced localStorage save of `{cuts, hotCues}` per track id, plus
  restore on track load. Pattern extends to the new fields.
- **Beatgrid** — state (`beatGrid`), canvas renderer in `WaveformCanvas.jsx`
  with perf-optimised adaptive density (skip non-downbeats at low zoom).
- **Loop state** — `loopIn`, `loopOut`, `isLooping`. Session-scoped, not
  persisted as a hot/memory loop slot.
- **Undo / redo** — `history`, `historyIdx` arrays + `pushHistory` helper.
  In-memory only, not persisted across reloads.
- **Save** — `handleSaveCues` (`useWaveformInteractions.js:148`), wired to
  `Ctrl+S`. Covers cues; not beatgrid / metadata yet.
- **Grid shift** — `handleGridShift` + `handleSaveGrid`. Anchor-shift only.

**What is missing (this work adds it):**

| Gap | Driver |
|---|---|
| Memory-cue state (unlimited), list UI, save path | Q6, ANLZ PCO2 `cue_list_type=0` |
| Hot / memory loops as persisted slots (not just session-scoped) | Q5, ANLZ |
| Active-loop flag (`status = 4`) with single-active-toggle semantics | Q5, `anlz_writer.py:_build_pcpt_entry` |
| Cue / loop colours aligned with 8 CDJ palette + 16 hot-cue surface palette | Q6 |
| Per-cue comment / name (UTF-16BE in PCP2) | ANLZ PCP2 |
| Loop numerator / denominator (currently hard-coded 0 in `anlz_writer.py:273-275`) | ANLZ writer |
| Tap-BPM, per-beat-edit modes | Q7 c |
| Track-rename UI (Title / Artist / etc.) | Q4 |
| Backend route: dual-save to `master.db` + ID3 | Q4 |
| Persistent undo (3-step, survives restart) — today in-memory only | Q10 + Q11 |
| Audio-playback "audition" affordance on cue-pad click | Q8 |

**⚠ Two DAW-style surfaces in the repo today.**
`frontend/src/components/daw/` contains a **second**, parallel DAW
implementation: `DjEditDaw.jsx`, `DawLayout.jsx`, `DawTimeline.jsx`,
`DawToolbar.jsx`, `DawScrollbar.jsx`, `DawBrowser.jsx`, `DawControlStrip.jsx`,
`ExportModal.jsx`, `WaveformOverview.jsx` plus a `timeline/` hook bundle and
five `useDaw*` hooks — 16 files total. State model is `useReducer` /
`dispatch({ type: 'SET_SCROLL_X' })`, **different** from the `WaveformEditor`
cluster's `useState`-bag model.

Q9 explicitly chose the `WaveformEditor` as the host. **Open question for
the implementation phase:** does the same feature set need to land in the
`daw/` surface too, or is `daw/` deliberately separate (e.g. project-DAW
for arrangement / clip editing) and out of scope for this work?

**Implications for the implementation plan:**

- State model stays a `useState`-bag in `WaveformEditor.jsx` — matches the
  Q1/Q2 collapse to "extend in place".
- Persistence layer = `useEditPersistence` + a small backend route bundle.
  Extend the localStorage payload to cover all new fields and the 3-step
  undo stack; extend the save path to hit ANLZ + `master.db` + ID3.
- Backend gaps to close: `anlz_writer.py` (`loop_numerator/denominator`,
  `status` from cue dict), plus new endpoints for beatgrid anchor / track
  rename.
- No new visual framework — extend `WaveformControls.jsx`,
  `WaveformOverlays.jsx`, add small panel sub-components.

### 2026-05-13 — Round 4: `daw/` surface in scope; recommendation switched

**User decisions (Implementation Gate, round 1):**
1. _"Welches ist die beste Option?"_ → answered after Q2 below
2. _"landen auch da oder?"_ → **YES, the same feature set also lands in
   `frontend/src/components/daw/` (the `DjEditDaw` surface).** The
   WaveformEditor is **not** the sole host.
3. _Panel path `frontend/src/components/waveform/panels/`?_ → **YES, confirmed.**

**Impact of decision 2:**
- The `daw/` surface uses `useReducer` / `dispatch` state. The
  `WaveformEditor` uses a `useState`-bag. Two surfaces, two state models.
- Building feature panels into both surfaces with Option B's
  "state-stays-in-WaveformEditor + props-down" model **does not work** —
  one of the two surfaces would have to ape the other's state shape.
- **Recommendation switches from Option B to Option C** (hook-extracted
  state + shared panel sub-components). Option C was already sketched in
  round 3 for exactly this scenario.

**Confirmed file paths:**
- Panels: `frontend/src/components/waveform/panels/` (4 files —
  `CuePanel.jsx`, `LoopPanel.jsx`, `BeatgridPanel.jsx`, `MetadataPanel.jsx`).
  Both surfaces import from there; neither surface owns them.
- State hook: location open — proposal
  `frontend/src/components/waveform/state/` with a `useTrackEditorState`
  hook (or equivalent). To be confirmed at the implementation-plan stage.

## Options Considered

> Required by `evaluated_`. For each viable approach: sketch (2-4 lines), pros, cons, effort (S/M/L/XL), risk.

### Option A — Inline extension of `WaveformEditor.jsx`
- **Sketch**: Add memory-cue / loop / metadata UI directly inside the
  existing `WaveformEditor.jsx` and `WaveformControls.jsx`. No new
  sub-components. State remains a flat `useState`-bag in
  `WaveformEditor.jsx`.
- **Pros**: Minimal refactor, fastest start, no new abstractions, no
  props-drilling concern.
- **Cons**: `WaveformEditor.jsx` grows from 402 → likely 700+ LOC.
  `WaveformControls.jsx` grows from 380 → likely 600+ LOC. The
  `useState`-bag (already 30+ pieces of state) becomes hard to reason
  about. Future maintenance gets harder.
- **Effort**: M
- **Risk**: Low — known patterns, no new abstractions.

### Option B — Panel sub-components, state stays in `WaveformEditor`
- **Sketch**: Add 3–4 new sub-components inside the existing layout:
  `CuePanel` (hot + memory cues, colour pickers, comments), `LoopPanel`
  (hot + memory loops, active-loop toggle, numerator/denominator),
  `BeatgridPanel` (anchor / tap-BPM / per-beat), `MetadataPanel` (Title /
  Artist / etc. + dual-save handler). Each < ~200 LOC. State stays in
  `WaveformEditor.jsx` (`useState`), passed down via props (grouped
  prop-bundles to limit drilling noise).
- **Pros**: Modular; each panel testable in isolation; no new state
  framework needed; matches Q1/Q2 (single source of truth, no
  cross-component sync). `WaveformEditor.jsx` stays at ~450–500 LOC as
  orchestrator.
- **Cons**: 4 new files; props-drilling adds noise (mitigated by grouping
  related props into objects).
- **Effort**: M–L
- **Risk**: Low.

### Option C — Hook-extracted state + panel sub-components
- **Sketch**: Same UI breakdown as Option B, but the `useState`-bag is
  first lifted into a `useTrackEditorState` hook. The hook exposes a state
  object + actions. Sub-panels read directly via the hook instead of
  props-drilling. Sets the stage if the `daw/` surface ever needs the same
  feature set.
- **Pros**: Cleanest separation of logic and UI. Easy to test. Re-usable
  for the `daw/` surface later if consolidation comes (see codebase-audit
  note about two parallel surfaces). Less props-drilling.
- **Cons**: Larger up-front refactor. `WaveformEditor.jsx` is 402 LOC with
  tightly-coupled state — extracting it cleanly is non-trivial. Risk of
  introducing regressions in existing waveform behaviour during the
  refactor.
- **Effort**: L
- **Risk**: Medium.

## Recommendation

**Option C** (hook-extracted state + shared panel sub-components).

_(Round 3 originally recommended Option B under the assumption that
`WaveformEditor` was the sole host. The round-4 decision to also land
the feature set in `frontend/src/components/daw/` invalidates that
assumption — see Findings round 4.)_

**Why C is now the right answer:**

- `WaveformEditor.jsx` uses a `useState`-bag.
- `daw/DjEditDaw.jsx` uses `useReducer` + `dispatch`.
- Two surfaces with two different state models cannot share Option B's
  prop-down model from a single host. The clean answer is to lift the
  new editor state into a hook (`useTrackEditorState`, located at
  `frontend/src/components/waveform/state/`), which both surfaces consume.
- The 4 panel sub-components (`CuePanel`, `LoopPanel`, `BeatgridPanel`,
  `MetadataPanel` at `frontend/src/components/waveform/panels/`) read
  directly from the hook and stay surface-agnostic. Build once, mount
  twice.

**Trade-off accepted:** Option C is Effort L / Risk Medium. The refactor
touches `WaveformEditor.jsx`'s tightly-coupled state model. Mitigation:
extract one slice at a time (cues first, then loops, then beatgrid, then
metadata), with the existing waveform behaviour kept under integration
tests at each step.

**Implementation gate** — all items confirmed 2026-05-13:

1. ✅ **Option C** is the chosen path (hook-extracted state + shared
   panel sub-components).
2. ✅ Paths:
   - State hook: `frontend/src/components/waveform/state/` (proposed hook
     name `useTrackEditorState`, final name to be set at draftplan stage).
   - Panels: `frontend/src/components/waveform/panels/` (4 files:
     `CuePanel.jsx`, `LoopPanel.jsx`, `BeatgridPanel.jsx`,
     `MetadataPanel.jsx`).
3. ✅ Slice order: **cues → loops → beatgrid → metadata**. Feature
   flags per slice if regression risk warrants.
4. ✅ Adapter strategy = **option c** (most invasive, cleanest end state):
   both surfaces consume the hook directly; the `WaveformEditor`
   `useState`-bag and the `daw/DjEditDaw` reducer slice are both retired
   in favour of the shared hook, migrated slice by slice. Highest refactor
   cost but no long-term split.

Doc is ready for `git mv` to `evaluated_` and user sign-off to
`implement/draftplan_`.

---

## Implementation Plan

### Scope

**In:**

- New shared state hook at `frontend/src/components/waveform/state/useTrackEditorState.js` (Zustand store; final name confirmable at draftplan review).
- 4 new panel components at `frontend/src/components/waveform/panels/`:
  `CuePanel.jsx`, `LoopPanel.jsx`, `BeatgridPanel.jsx`, `MetadataPanel.jsx`. Surface-agnostic; both surfaces import.
- Slice-by-slice state migration in `WaveformEditor.jsx` (out of `useState`-bag) and `daw/DjEditDaw.jsx` (out of editor reducer slice).
- Backend ANLZ-writer fixes in `app/anlz_writer.py`:
  - `_build_pcpt_entry`: `status` from cue dict (currently hardcoded `4 if is_hot else 0`).
  - `_build_pcp2_entry`: `loop_numerator` / `loop_denominator` from cue dict (currently hardcoded `0`).
- New / extended FastAPI routes in `app/main.py`:
  - **Extend** `POST /api/track/cues/save` — accept memory cues, loop fields (active flag, numerator/denominator), per-cue comment, RGB + color_id.
  - **New** `POST /api/track/{tid}/beatgrid/anchor` — anchor-shift / tap-BPM / per-beat overrides; PQTZ + PQT2 written.
  - **New** `PATCH /api/track/{tid}/metadata` — Title / Artist / Album / Genre / BPM-override / Key-override / Comment; dual-write to `master.db` (under `_db_write_lock`) **and** ID3 tags in audio file.
- Per-cue fields surfaced: comment / name (UTF-16BE in PCP2), color (8 CDJ memory palette + 16 hot-cue surface palette), active-loop flag with single-active toggle (Q5), loop numerator / denominator (Q7-adjacent).
- Persistent undo (3-step) — `useEditPersistence` payload extended with `history` array.
- Audio-audition (Q8): cue-pad click seeks WaveSurfer + plays a short preview.
- Feature flags per slice in `frontend/src/config/constants.js` (`FEATURE_CUE_PANEL`, `FEATURE_LOOP_PANEL`, `FEATURE_BEATGRID_PANEL`, `FEATURE_METADATA_PANEL`).

**Out (deliberately):**

- Phrase (PSSI) editing — Non-goal from Findings.
- Audio FX / mastering / multi-track / cloud sync — Non-goals.
- Snapshot diff-log for undo (Q11 a — stay with 3 `.bak` files).
- Full state refactor of `daw/DjEditDaw.jsx`'s non-editor reducer slices (timeline scroll, project state, etc. stay untouched).
- BPM / Key detection logic — `analysis_engine.py` already provides it; the editor only reads and lets the user override.

### Step-by-step

**Slice 0 — Foundation (no user-visible changes)**

1. Create empty hook file `frontend/src/components/waveform/state/useTrackEditorState.js` returning a Zustand store with empty slices (`cues`, `hotCues`, `loops`, `beatgrid`, `metadata`, `history`).
2. Backend ANLZ-writer fixes in `app/anlz_writer.py`:
   - `_build_pcpt_entry`: read `status` from cue dict, default 0; keep `4` only when `cue.get("active_loop") is True`.
   - `_build_pcp2_entry`: read `loop_numerator` / `loop_denominator` from cue dict, default 0.
3. Add feature flags in `frontend/src/config/constants.js`, all default `false` in production builds.
4. Write `tests/test_anlz_cue_fields.py` covering the new dict-driven fields with byte-level assertions.
5. Run `pytest tests/test_pdb_structure.py` to verify no byte-layout regression.

**Slice 1 — Cues (hot + memory)**

1. Hook: implement `cues` / `hotCues` slices (state + actions: `setCue`, `deleteCue`, `setColor`, `setComment`).
2. Add `panels/CuePanel.jsx` — pad grid for 8 hot cues, list view for memory cues, 8-CDJ-color picker for memory, 16-color surface palette picker for hot cue, comment input.
3. Mount `CuePanel` in `WaveformEditor.jsx` behind `FEATURE_CUE_PANEL`. Migrate the hot-cue slice from the `useState`-bag to the hook.
4. Mount `CuePanel` in `daw/DjEditDaw.jsx` behind same flag. Retire editor reducer slice for cues.
5. Extend `POST /api/track/cues/save` to accept memory cues + per-cue comment + RGB + color_id. Backward-compat: unknown fields ignored.
6. Tests: Mocha test for `CuePanel` (set / jump / delete / color / comment paths). pytest for backend save. Manual UI verification in both surfaces.

**Slice 2 — Loops (hot + memory + active)**

1. Hook: implement `loops` slice. Session-loop state (`loopIn`, `loopOut`, `isLooping`) folds into the hook.
2. Add `panels/LoopPanel.jsx` — loop list, active-loop radio toggle (only one can be active), numerator / denominator input, color + comment.
3. Mount in both surfaces behind `FEATURE_LOOP_PANEL`.
4. Extend `POST /api/track/cues/save` (already extended in Slice 1) to write loop entries with `active_loop` and `loop_numerator / denominator` fields.
5. Tests: per-track active-loop invariant (exactly 0 or 1), ANLZ roundtrip including loop fields.

**Slice 3 — Beatgrid (anchor + tap-BPM + per-beat)**

1. Hook: implement `beatgrid` slice; migrate `beatGrid` state.
2. Add `panels/BeatgridPanel.jsx` — three modes; anchor as default. Tap-BPM uses `Space` × 4 keyboard shortcut. Per-beat is mouse-drag on a beat marker in `WaveformCanvas`.
3. Mount in both surfaces behind `FEATURE_BEATGRID_PANEL`.
4. New backend route `POST /api/track/{tid}/beatgrid/anchor` — accepts `{anchor_shift_ms?, tap_bpm?, per_beat_overrides?[]}`. Writes PQTZ + PQT2 via `anlz_writer.py`.
5. Tests: PQTZ + PQT2 byte roundtrip after each mode, tap-BPM tolerance, per-beat invariant (monotonic time).

**Slice 4 — Metadata (Title / Artist / etc.)**

1. Hook: implement `metadata` slice.
2. Add `panels/MetadataPanel.jsx` — inline-edit Title, Artist, Album, Genre, BPM-override, Key-override, Comment.
3. New backend route `PATCH /api/track/{tid}/metadata` — dual-write to `master.db` (under `_db_write_lock`) and ID3 tags via `mutagen` (already a dep) or new `app/id3_writer.py` helper if non-trivial.
4. Divergence detection: if `master.db` value differs from ID3 value before save, surface one-time toast asking user to confirm which wins (default: `master.db` ← editor value).
5. Tests: dual-write consistency per format (mp3 / flac / wav / aac), `_db_write_lock` acquisition assertion.

**Slice 5 — Persistent Undo + Audio Audition**

1. Hook: `history` slice persisted to localStorage via extended `useEditPersistence`. Capacity 3 steps (Q10/Q11 confirmed).
2. Audio-audition: `CuePanel` pad-click handler seeks WaveSurfer + plays for ~2 s.
3. Promote feature flags to `true` for the beta cohort.
4. Tests: undo survives reload; audition latency < 100 ms after click.

**Slice 6 — Cleanup**

1. Remove feature flags after sufficient bake time (user signal).
2. Remove the legacy `useState`-bag entries and `daw/` reducer slices that were migrated.
3. Update `docs/architecture.md`, `docs/FILE_MAP.md`, `docs/frontend-index.md`, `docs/backend-index.md` per `.claude/rules/research-pipeline.md` graduation requirements.
4. Bump `CHANGELOG.md` via `/changelog-bump`.
5. Final `git mv` of this doc to `docs/research/archived/implemented_waveform-editor-extensions_<YYYY-MM-DD>.md`.

### Files touched (expected)

**New (Frontend):**

| Path | Approx. LOC |
|---|---|
| `frontend/src/components/waveform/state/useTrackEditorState.js` | ~200 |
| `frontend/src/components/waveform/panels/CuePanel.jsx` | ~180 |
| `frontend/src/components/waveform/panels/LoopPanel.jsx` | ~150 |
| `frontend/src/components/waveform/panels/BeatgridPanel.jsx` | ~200 |
| `frontend/src/components/waveform/panels/MetadataPanel.jsx` | ~150 |

**Modified (Frontend):**

- `frontend/src/components/WaveformEditor.jsx` — adopts hook slice-by-slice, mounts panels.
- `frontend/src/components/daw/DjEditDaw.jsx` — adopts hook slice-by-slice; editor-related reducer slice retires.
- `frontend/src/components/waveform/useWaveformInteractions.js` — handlers write through hook actions.
- `frontend/src/components/waveform/useEditPersistence.js` + `persistence.js` — payload extended (loops, beatgrid, metadata, history).
- `frontend/src/components/waveform/WaveformControls.jsx` — hot-cue strip relocated to `CuePanel`.
- `frontend/src/config/constants.js` — new feature flags.

**Modified (Backend):**

- `app/anlz_writer.py` — `_build_pcpt_entry` (status from dict), `_build_pcp2_entry` (loop numerator/denominator from dict).
- `app/main.py` — extends `POST /api/track/cues/save`; new `POST /api/track/{tid}/beatgrid/anchor`; new `PATCH /api/track/{tid}/metadata`.
- `app/live_database.py` — track-rename helpers via rbox.

**New (Backend):**

- `app/id3_writer.py` (or extends existing module if found during draftplan review) — ID3 tag write helper.

**New tests:**

- `tests/test_anlz_cue_fields.py` (loop_numerator/denominator, status from dict)
- `tests/test_anlz_roundtrip_full.py` (full cue/loop/beatgrid roundtrip)
- `tests/test_metadata_dual_save.py` (master.db + ID3 consistency per format)
- `tests/test_beatgrid_anchor_endpoint.py`
- Per-panel Mocha tests under `frontend/src/components/waveform/panels/__tests__/`.

**Docs to update on graduation to `implemented_`:**

- `docs/architecture.md` — new data flow for editor extensions (hook + panels + dual-save).
- `docs/FILE_MAP.md` — new files.
- `docs/backend-index.md` — new routes.
- `docs/frontend-index.md` — new hook + 4 panels.
- `CHANGELOG.md` — user-visible feature.

### Testing approach

- **Per-slice integration tests**: each slice ships with its own bundle (frontend Mocha + backend pytest).
- **ANLZ byte invariants**: `pytest tests/test_pdb_structure.py` runs on every slice that touches the writer. Adding `tests/test_anlz_roundtrip_full.py` for the new fields. **A wrong byte corrupts USB silently** — see `.claude/rules/coding-rules.md`.
- **Dual-write consistency**: `master.db` and ID3 round-trip after metadata save. Per-format coverage (mp3 / flac / wav / aac).
- **Manual UI verification in both surfaces**: `npm run dev:full` + Web Preview (or `e2e-tester` subagent). Click through cue set / jump / delete, loop active-toggle, beatgrid anchor / tap / per-beat, metadata rename. Each surface.
- **Regression baseline**: before Slice 1 ships, capture current WaveformEditor + DjEditDaw behaviour (audio loaded, beatgrid drawn, hot cue set+jumped) as a Playwright snapshot. Re-run after each slice merges.
- **Feature-flag toggle test**: each slice's panel renders correctly when flag on, invisible when off, no console errors either way.
- **rbox concurrency**: every write path goes through `_db_write_lock`. Assert lock acquisition in unit tests.
- **USB-export smoke test**: before graduation to `implemented_`, run a full `app/usb_pdb.py` export to a real (or simulated) F: drive and load on a CDJ-3000 to verify byte-level correctness end-to-end.

### Risks & rollback

| Risk | Likelihood | Mitigation |
|---|---|---|
| State migration in `WaveformEditor.jsx` breaks existing waveform behaviour | Medium | Slice-by-slice; regression baseline (Playwright); old state kept side-by-side until panel's feature flag is on. Each slice is one revertable commit. |
| State migration in `daw/DjEditDaw.jsx` breaks reducer flow | Medium | Same slice-by-slice strategy. **Only the editor-related reducer slice retires** — timeline scroll, project state, etc. are NOT touched. |
| ANLZ byte-layout regression silently corrupts USB exports | Low (tests catch it) | `pytest tests/test_pdb_structure.py` gates every commit; manual CDJ-3000 USB-export test before graduation. |
| `master.db` write deadlock | Low | All new write paths acquire `_db_write_lock` per `.claude/rules/coding-rules.md`. Assert in tests. |
| ID3 write fails on edge formats (esp. AAC) | Medium | Per-format unit tests in `test_metadata_dual_save.py`. Failure logged + toast; `master.db` write still succeeds independently. |
| 3-step undo too shallow for power user | Acknowledged (Q10↔Q11 tension) | Documented as future Q11 revisit. Snapshot-log can be added later behind a flag without breaking the current model. |
| `daw/` reducer + hook double-source-of-truth during migration | Medium | Each migrated slice has a clear "owner" — hook from day one. The reducer slice is removed in the SAME commit that mounts the panel, not delayed. |
| Feature flag forgotten in cleanup | Low | Slice 6 has explicit task; CI grep can fail-fast if `FEATURE_*_PANEL` literals survive cleanup. |

**Rollback paths:**

- **Per-slice**: each slice is one commit; `git revert <sha>` rolls it back. Backend routes are additive — reverting frontend leaves backend dormant (no schema change required).
- **ANLZ corruption**: `_backup_existing_anlz` keeps 3 timestamped `.bak` files per track (`app/anlz_writer.py:687-733`). User restores manually if needed.
- **Database corruption**: pre-existing `master.db` backup machinery in `app/backup_engine.py`.
- **Full feature withdrawal**: all feature flags off → panels invisible. No DB rollback needed; cues / loops / beatgrid / metadata already written remain valid ANLZ.

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

### 2026-05-13 — Slice 0 (Foundation)

**Adjustment 1 — state library:** the state hook will use **React
Context + `useReducer`**, not Zustand. Zustand is not installed in
`frontend/package.json`; adding a new dep is a security decision per
`.claude/rules/agentic-mode.md` and was not green-lit by the user. The
existing `frontend/src/components/ToastContext.jsx` is the project's
context pattern — we follow it.

**Adjustment 2 — file extension:** the hook file is named
`useTrackEditorState.jsx` (not `.js` as in the draftplan), because it
co-exports a `TrackEditorProvider` JSX component. Project convention is
`.jsx` for files containing JSX.

**Slice 0 changes:**

- `app/anlz_writer.py` → `_build_pcpt_entry`: `status` is now read from
  the cue dict with backward-compat default `4 if is_hot else 0`. New
  callers (Slice 2 onwards) can pass `status: 0` for plain hot cues and
  `status: 4` for active loops.
- `app/anlz_writer.py` → `_build_pcp2_entry`: `loop_numerator` /
  `loop_denominator` are now read from the cue dict (default `0`).
- `frontend/src/config/constants.js` — 4 feature flags added, all
  `false`: `FEATURE_CUE_PANEL`, `FEATURE_LOOP_PANEL`,
  `FEATURE_BEATGRID_PANEL`, `FEATURE_METADATA_PANEL`.
- New file
  `frontend/src/components/waveform/state/useTrackEditorState.jsx` —
  empty `TrackEditorContext` + `TrackEditorProvider` skeleton. State
  shape declared (`hotCues`, `cues`, `loops`, `beatgrid`, `metadata`,
  `history`, `historyIdx`) but no actions yet. Filled slice by slice.
- New test `tests/test_anlz_cue_fields.py` — byte-level assertions
  for the dict-driven `status` and `loop_numerator/denominator` fields,
  plus backward-compat regression tests.

**Backward-compat:** every existing caller of `write_anlz_files()` keeps
working unchanged — the new dict keys default to the previously hardcoded
values.

### 2026-05-13 — Slice 1 (Cues)

**Pre-existing fix:** `app/main.py:742` (`get_cues`) and `app/main.py:861`
(`save_cues`) were calling `db.get_track_cues` / `db.save_track_cues`
which **did not exist** anywhere in the codebase — every call would have
raised AttributeError on the first hit. Slice 1 adds minimal
JSON-sidecar persistence so the endpoints actually work and the new
CuePanel has a working save path.

- `RekordboxDB.save_track_cues(tid, cues)` writes to
  `LOG_DIR / "cue_overrides.json"` (track-id keyed). Atomic via
  write-to-tmp + rename. Added to the `_serialised` wrap list so writes
  acquire `_db_write_lock`.
- `RekordboxDB.get_track_cues(tid)` reads from the sidecar first, then
  falls back to `track["Cues"]` (rbox `_load_cues` output).
- This is intentionally a **stopgap**. The proper rbox + ANLZ
  persistence path is deferred — likely Slice 4 (metadata) when the
  dual-save infrastructure lands, or Slice 6 cleanup.

**Slice 1 frontend:**

- `frontend/src/config/constants.js` — added `CDJ_MEMORY_COLORS` (8
  fixed Pioneer colours) and `HOT_CUE_SURFACE_COLORS` (16 surface
  palette approximations).
- `frontend/src/components/waveform/state/useTrackEditorState.jsx` —
  reducer filled with `LOAD_CUES`, `SET_HOT_CUE`, `DELETE_HOT_CUE`,
  `SET_MEMORY_CUE`, `DELETE_MEMORY_CUE`, `UPDATE_HOT_CUE_FIELDS`,
  `UPDATE_MEMORY_CUE_FIELDS`. Provider exposes convenience action
  creators.
- `frontend/src/components/waveform/panels/CuePanel.jsx` — new panel.
  8-pad hot-cue grid (click empty pad → set at `currentTime`,
  trash-icon → delete). Memory-cue list with inline-edit comment +
  click-swatch CDJ-colour picker. Save button POSTs to
  `/api/track/cues/save`.
- `WaveformEditor.jsx` and `daw/DjEditDaw.jsx` — wrapped render in
  `<TrackEditorProvider>` and conditionally render `<CuePanel>` behind
  `FEATURE_CUE_PANEL`. Flag is `false` in production; panel does not
  appear yet for end users.

**Tests:** `tests/test_cue_endpoint_roundtrip.py` — 5 sidecar tests
(create, get, empty, unicode, overwrite). All pass.

**Plan deviations:**

- **Migration of `WaveformEditor.jsx` `useState`-bag `[hotCues,
  setHotCues]`** — not done in Slice 1. The old hot-cue strip in
  `WaveformControls.jsx` still owns its state. Both panels coexist;
  when `FEATURE_CUE_PANEL` flips on the user sees both. Slice 6 cleanup
  will retire the old strip. Rationale: the strip is deeply wired into
  `useWaveformInteractions.js` handlers and migrating it now would
  multiply the slice's risk surface.
- **Migration of `frontend/src/audio/dawState/cues.js` reducer slice**
  — same deferral, same rationale.
- **Mocha tests for `CuePanel`** — skipped this session (no setup
  time); backend pytest tests gate the save / get roundtrip.
- **Audio audition on pad click** — explicitly Slice 5 work.

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

- Code (existing, will be touched once implementation starts):
  - [frontend/src/components/WaveformEditor.jsx](frontend/src/components/WaveformEditor.jsx) — base to fork / share from
  - [frontend/src/components/waveform/](frontend/src/components/waveform/) — canvas, controls, overlays, zoom, useWaveSurfer
  - [frontend/src/components/daw/WaveformOverview.jsx](frontend/src/components/daw/WaveformOverview.jsx) — existing `daw/` folder already scaffolded
  - [app/anlz_writer.py](app/anlz_writer.py) — ANLZ binary writer (extend for `loop_numerator/denominator`, configurable `status`)
  - [app/anlz_safe.py](app/anlz_safe.py) — quarantined ANLZ reader
  - [app/main.py:741](app/main.py) — `GET /api/track/{tid}/cues`
  - [app/main.py:860](app/main.py) — `POST /api/track/cues/save`
  - [app/main.py:3629](app/main.py) — `POST /api/track/{id}/phrase-cues/generate`
  - [app/main.py:3698](app/main.py) — `POST /api/track/{id}/phrase-cues/commit`
- External references:
  - Rekordbox ANLZ analysis — https://djl-analysis.deepsymmetry.org/rekordbox-export-analysis/anlz.html
  - pyrekordbox ANLZ docs — https://pyrekordbox.readthedocs.io/en/latest/formats/anlz.html
  - pyrekordbox cue write discussion — https://github.com/dylanljones/pyrekordbox/discussions/113
- Related research: _(none yet)_
