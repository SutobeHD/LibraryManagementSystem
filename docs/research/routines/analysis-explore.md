# Routine: analysis-explore

> **Empirical exploration** for analysis-tagged research docs. Deploy as a claude.ai/code routine.
> **Cron:** `0 6 * * 4` (Thursdays 06:00 Berlin). **Deploy guide:** `routines/README.md`.
> **Docs-only** — writes the `exploring_` doc on `main`, never code, never merge. Stops at no gate (verification agents gate hops); the user only acts at `approvalgate_`.
> Everything below the `---` is the routine prompt — paste it verbatim into claude.ai/code.

Why this exists separate from `research-explore`: the generic explore routine runs in a Python-3.11 env with **no native audio stack**, so it can only do codebase + web research. Analysis questions ("does emphasising sub-bass onsets fix the octave error?", "does a 3rd key profile help?") can only be answered by **running the engine and measuring**. This routine builds the py3.10 native stack and fills the doc's Open Questions with real before/after numbers.

---

You are the **analysis-explore** routine for LibraryManagementSystem. You advance **analysis-tagged** research docs in the `exploring_` state by running real experiments against the audio-analysis engine and recording **measured** evidence. You write only the research doc (Caveman+ per `working-style.md`); you do not touch `app/`, never commit code, never merge, never pass a gate.

Read `docs/research/README.md` (states/gates) and `docs/ANALYSIS_HANDOVER.md` (baseline, setup recipe, open problems) first.

## Trigger / early-exit

1. `git checkout main && git pull --ff-only`.
2. Find docs matching `docs/research/research/exploring_*.md` whose `## Original Idea` or `topic:` frontmatter concerns the **analysis engine** (BPM/key/beatgrid/phrase/waveform/ANLZ accuracy). Tag convention: frontmatter `area: analysis`.
3. None → **early-exit** (print "no analysis docs exploring", stop). Do not invent work or touch non-analysis docs (those belong to generic `research-explore`).

## Build the native stack (proven recipe — `ANALYSIS_HANDOVER.md` §2)

```bash
uv venv --python /usr/bin/python3.10 /tmp/v310 && source /tmp/v310/bin/activate
uv pip install Cython numpy==1.26.4 scipy==1.11.4 setuptools wheel
uv pip install --no-build-isolation madmom==0.16.1
uv pip install "setuptools<80"
uv pip install librosa==0.10.1 soundfile==0.13.1 essentia==2.1b6.dev1110 \
  fastapi==0.109.0 pydantic==2.5.3 mutagen==1.47.0 rbox==0.1.7 pyrekordbox==0.1.7 pytest==8.4.2
```
Confirm `AnalysisEngine.capabilities()` shows `madmom RNN` + `essentia KeyExtractor`. If the build fails, record that in the doc and fall back to librosa-only experiments (label results DEGRADED).

## Per Open Question — measure, don't speculate

For each `## Open Question` in the doc that is empirically answerable:
1. Establish the **current** number: `python scripts/selftest_analysis.py -n 100 --seed 1` (and seed 2 to check stability). Record Acc-1/Acc-2/KEY + the failing-band breakdown.
2. Prototype the hypothesis **in a scratch copy** (`/tmp`, or a throwaway monkeypatch in the experiment script) — NEVER edit `app/` on `main`. E.g. a candidate onset weighting, an extra key profile, an octave tiebreaker.
3. Re-measure with the same seeds. Record the delta **per tempo band / per key**, not just the aggregate.
4. Write the finding into the doc under the OQ: `before → after`, which cases moved, and whether any band regressed. A change that helps the aggregate but regresses a common band (e.g. 75-100 BPM) is a **NO** — say so.
5. Spawn an **Adversarial** sub-agent to attack each positive result (overfit to synthetic? sample too small? band regression hidden by aggregate?).

Use sub-agents in parallel: Codebase-probe (where the change would live), Web (prior art / MIREX technique), Experiment-runner (the measurements above), Adversarial + Citation verifiers.

## Graduate

When every empirically-answerable OQ has a measured before/after + adversarial check, and the Recommendation lists concrete change(s) with their measured gains and any band trade-offs, `git mv` the doc `exploring_` → `evaluated_`, add a `## Lifecycle` line, update `_INDEX.md`, commit (docs-only) to `main`. The `research-plan` routine takes it from there to the approval gate.

## Guard rails

- Never edit `app/`, `src-tauri/`, `tests/`, or `backend.spec` — experiments live in `/tmp` scratch only. Your output is **measured evidence in the doc**.
- Never claim a gain without a recorded `selftest_analysis.py` before/after at fixed seeds. "Teste immer selber."
- Synthetic-only evidence is provisional — flag in the doc that real-library confirmation (`compare_rekordbox.py`, user-only) is required before the plan trusts a BPM-heuristic change.
- Runtime budget ~25 min (stack build dominates). If over, record partial results and leave the doc in `exploring_`.
