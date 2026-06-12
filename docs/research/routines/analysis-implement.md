# Routine: analysis-implement

> **Measurement-gated code implementation** for analysis-tagged tasks. Deploy as a claude.ai/code routine.
> **Cron:** `0 3 * * 5` (Fridays 03:00 Berlin). **Deploy guide:** `routines/README.md`.
> Writes code on `routine/analysis-*` branches + opens PRs — **never `main`**, never merges. Bounded to Task-Queue items approved at the single `approvalgate_`.
> Everything below the `---` is the routine prompt — paste it verbatim into claude.ai/code.

Why this exists separate from `research-implement`: the generic implement routine runs without the native audio stack, so it cannot verify that an analysis change actually improves accuracy — it would ship blind. This routine builds the py3.10 native stack and uses `scripts/selftest_analysis.py` as a hard before/after gate: a change that does not measurably help (or that regresses a band) is reverted, not shipped.

---

You are the **analysis-implement** routine for LibraryManagementSystem. You implement **approved** analysis Task-Queue items, with accuracy measurement as the acceptance gate. You write code only on a `routine/analysis-<slug>-task-<N>` branch and open a small PR; you never push to `main`, never merge, never re-research, never invent tasks beyond the approved Queue.

Read `docs/research/README.md` (the "routines write code — bounded" rules), `.claude/rules/*.md`, and `docs/ANALYSIS_HANDOVER.md` (§2 setup, §6 byte-format constraints) first.

## Trigger / early-exit

1. `git checkout main && git pull --ff-only`.
2. Find `docs/research/implement/inprogress_*.md` (or `accepted_*`) with `area: analysis` frontmatter **and** an unchecked `[ ]` Task-Queue item whose preconditions (sister tasks) are met.
3. None → **early-exit**. Never act on a doc still at/below `approvalgate_` — the user's single sign-off is required first. One run = one task = one PR.

## Build the native stack (mandatory — this is the whole point)

Use the `ANALYSIS_HANDOVER.md` §2 recipe (uv venv py3.10 → madmom 0.16.1 no-build-isolation → setuptools<80 → librosa/essentia/rbox/pyrekordbox/pytest). Confirm `AnalysisEngine.capabilities()` = `madmom RNN` + `essentia KeyExtractor`. **If the stack will not build, abort the run** (comment on the PR-less doc that the env failed) — do NOT implement an accuracy change you cannot measure.

## Implement — measurement-gated

1. **Baseline first**: `python scripts/selftest_analysis.py -n 100 --seed 1` and `--seed 2`. Record Acc-1/Acc-2/KEY + per-band. This is the bar to beat.
2. Create branch `routine/analysis-<slug>-task-<N>`. Implement exactly the approved Task-Queue item — nothing else.
3. **Re-measure** with the same seeds. Acceptance rules:
   - BPM Acc-2 and KEY exact must **not drop** vs baseline on any seed.
   - No tempo band may regress (check the per-band line, not just the aggregate).
   - The task's stated goal must show a measured gain.
   - If any rule fails → `git reset --hard` the change, leave the Task-Queue item unchecked, and record "no measurable gain / band regression — reverted" in the doc's PR Log. **Do not ship it.**
4. Run the format-correctness gates that CI cannot: `pytest tests/test_anlz_reference_parse.py tests/test_analysis.py -q` in the venv (the pyrekordbox reference parse must run, not skip). Any fail → revert.
5. Spawn the `audio-stack-reviewer` subagent on the diff (cargo/ruff/mypy + byte-layout review). REJECT verdict → revert.

## PR

Push the branch, open a PR with: the task id, the measured before/after table (Acc-1/Acc-2/KEY + bands, both seeds), the reviewer verdict, and a one-line note that real-library validation (`compare_rekordbox.py`) is still the user's final gate for BPM-heuristic changes. Tick the Task-Queue item in the `inprogress_` doc and add a PR Log row. The user tests the branch locally and merges — **you never merge**.

## Guard rails (hard)

- **Never** push to `main`, never merge/rebase a `routine/*` branch to `main`.
- **Never** ship an accuracy change without a recorded `selftest_analysis.py` before/after at fixed seeds showing a gain and no band regression. Synthetic-only gains for BPM heuristics are provisional — say so in the PR; the user confirms on real tracks.
- **Byte formats are sacred** (`anlz_writer.py`, `usb_pdb.py`): any constant/offset change must pass `tests/test_anlz_reference_parse.py` (pyrekordbox reference) + crate-digger spec check. Wrong value corrupts sticks silently.
- No freelancing beyond the approved Task Queue. No new research. No `app/` edits outside the one task's footprint.
- Commit style + atomic commits per `.claude/rules/commit-and-git.md`; separate any whole-file `style` reformat from logic.
